from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from netdiag_agent.memory import NetworkMemory
from netdiag_agent.models import DnsResult, NetworkSnapshot, PingResult, TraceResult
from netdiag_agent.monitor import MonitorSummary, monitor_to_rows, run_monitor
from netdiag_agent.probe import compare_dns, dns_lookup, get_default_gateway, get_dns_servers, ping, traceroute
from netdiag_agent.rag import RagHit, rag_hits_to_rows, retrieve_knowledge


TARGET_ALIASES = {
    "gateway": "__gateway__",
    "public_dns": "223.5.5.5",
    "tencent_dns": "119.29.29.29",
    "baidu": "www.baidu.com",
    "bilibili": "www.bilibili.com",
}

AVAILABLE_REACT_TOOLS = {
    "get_network_profile": "读取默认网关和 DNS 服务器。",
    "ping_target": "测试某个 IP 或域名的延迟和丢包。",
    "dns_lookup": "测试某个域名的 DNS 解析耗时和结果。",
    "compare_dns": "对同一域名使用本机 DNS 和公共 DNS 做解析对比。",
    "traceroute": "追踪到某个目标的路由路径，耗时较长。",
    "short_monitor": "对某个目标做短时多次 Ping，观察抖动和间歇性丢包。",
    "rag_search": "从本地向量知识库检索网络排障知识。",
    "recall_memory": "召回本地历史诊断记忆。",
    "final_answer": "结束工具调用循环，进入最终诊断。",
}


@dataclass(frozen=True)
class ReactAction:
    thought: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReactObservation:
    step: int
    thought: str
    tool: str
    args: dict[str, Any]
    success: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReactGuardDecision:
    should_stop: bool
    reason: str = ""


def observation_rows(observations: list[ReactObservation]) -> list[dict[str, object]]:
    return [
        {
            "步骤": item.step,
            "模型判断": item.thought,
            "调用工具": item.tool,
            "参数": item.args,
            "成功": item.success,
            "观察结果": item.summary,
        }
        for item in observations
    ]


def evaluate_react_progress(
    observations: list[ReactObservation],
    repeated_limit: int = 2,
    failure_limit: int = 2,
) -> ReactGuardDecision:
    if not observations:
        return ReactGuardDecision(False)

    latest = observations[-1]
    if latest.tool == "final_answer":
        return ReactGuardDecision(True, latest.summary)

    failures = count_recent_failures(observations)
    if failures >= failure_limit:
        return ReactGuardDecision(
            True,
            f"最近连续 {failures} 次工具调用失败，已停止继续试探并转入保底诊断。",
        )

    repeated = count_recent_repeated_actions(observations)
    if repeated >= repeated_limit:
        return ReactGuardDecision(
            True,
            f"Agent 连续 {repeated} 次调用相同工具且没有切换策略，已停止自动循环并转入保底诊断。",
        )

    return ReactGuardDecision(False)


def execute_react_tool(
    action: ReactAction,
    step: int,
    user_context: str,
    observations: list[ReactObservation],
) -> ReactObservation:
    try:
        if action.tool == "get_network_profile":
            gateway = get_default_gateway()
            dns_servers = get_dns_servers()
            success = bool(gateway or dns_servers)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=success,
                summary=(
                    f"默认网关：{gateway or '未识别'}；DNS：{', '.join(dns_servers) or '未识别'}"
                    if success
                    else "没有识别到默认网关或 DNS，可能是当前网络未连接，或系统命令返回不完整。"
                ),
                data={"gateway": gateway, "dns_servers": dns_servers},
            )

        if action.tool == "ping_target":
            target_name, target = resolve_target(action.args.get("target"), observations)
            count = bounded_int(action.args.get("count"), default=4, minimum=1, maximum=8)
            result = ping(target, count=count)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"target": target_name, "resolved_target": target, "count": count},
                success=result.success,
                summary=(
                    f"{target_name}({target}) 平均延迟 {result.avg_ms} ms，丢包 {result.packet_loss_percent}%"
                    if result.success
                    else f"{target_name}({target}) Ping 失败，可能是目标不可达、被禁 Ping，或当前网络异常。"
                ),
                data={"target_name": target_name, "result": result.__dict__},
            )

        if action.tool == "dns_lookup":
            host_name, host = resolve_target(action.args.get("host") or action.args.get("target"), observations)
            dns_server = action.args.get("dns_server")
            if dns_server:
                _, dns_server = resolve_target(dns_server, observations)
            result = dns_lookup(host, dns_server=dns_server)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"host": host_name, "resolved_host": host, "dns_server": dns_server},
                success=result.success,
                summary=(
                    f"{host_name}({host}) DNS {'成功' if result.success else '失败'}，耗时 {result.elapsed_ms} ms"
                    if result.success
                    else f"{host_name}({host}) DNS 解析失败，可能是当前 DNS 服务异常，或目标域名暂时不可解析。"
                ),
                data={"target_name": host_name, "result": result.__dict__},
            )

        if action.tool == "compare_dns":
            host_name, host = resolve_target(action.args.get("host") or action.args.get("target"), observations)
            results = compare_dns(host)
            success = any(item.success for item in results.values())
            best = sorted(
                results.items(),
                key=lambda item: (not item[1].success, item[1].elapsed_ms if item[1].elapsed_ms is not None else 999999),
            )
            summary = (
                f"{host_name}({host}) DNS 对比完成，最快结果来自 {best[0][0]}，耗时 {best[0][1].elapsed_ms} ms。"
                if success and best
                else f"{host_name}({host}) DNS 对比未得到有效结果，可能是当前网络或 DNS 环境异常。"
            )
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"host": host_name, "resolved_host": host},
                success=success,
                summary=summary,
                data={
                    "target_name": host_name,
                    "results": {label: result.__dict__ for label, result in results.items()},
                },
            )

        if action.tool == "traceroute":
            target_name, target = resolve_target(action.args.get("target"), observations)
            max_hops = bounded_int(action.args.get("max_hops"), default=12, minimum=4, maximum=20)
            result = traceroute(target, max_hops=max_hops)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"target": target_name, "resolved_target": target, "max_hops": max_hops},
                success=result.success,
                summary=(
                    f"{target_name}({target}) 路由追踪完成，记录 {len(result.hops)} 跳。"
                    if result.success
                    else f"{target_name}({target}) 路由追踪失败或超时，已跳过该步骤继续分析。"
                ),
                data={"target_name": target_name, "result": result.__dict__},
            )

        if action.tool == "short_monitor":
            target_name, target = resolve_target(action.args.get("target"), observations)
            samples = bounded_int(action.args.get("samples"), default=5, minimum=3, maximum=12)
            interval = bounded_int(action.args.get("interval_seconds"), default=3, minimum=1, maximum=20)
            summary = run_monitor({target_name: target}, samples=samples, interval_seconds=interval)
            points = monitor_to_rows(summary)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"target": target_name, "resolved_target": target, "samples": samples, "interval": interval},
                success=bool(points),
                summary=summary.conclusion if points else "短时监控没有采集到有效数据，已跳过该步骤。",
                data={
                    "target_name": target_name,
                    "summary": summary.conclusion,
                    "points": points,
                },
            )

        if action.tool == "rag_search":
            query = str(action.args.get("query") or user_context or "网络故障诊断")
            hits = retrieve_knowledge(query, snapshot=None, top_k=4)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"query": query},
                success=bool(hits),
                summary=(
                    "检索到：" + "；".join(hit.title for hit in hits[:3])
                    if hits
                    else "知识库没有命中相关内容，后续结论将主要依据实时检测结果。"
                ),
                data={"hits": [hit.__dict__ for hit in hits], "rows": rag_hits_to_rows(hits)},
            )

        if action.tool == "recall_memory":
            mode = action.args.get("mode")
            records = NetworkMemory().recall(user_context, str(mode) if mode else None, limit=3)
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"mode": mode},
                success=True,
                summary=(
                    f"召回 {len(records)} 条历史诊断记忆。"
                    if records
                    else "没有找到可参考的历史诊断记录，本次将按当前检测结果独立分析。"
                ),
                data={"records": [record.__dict__ for record in records]},
            )

        if action.tool == "final_answer":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args=action.args,
                success=True,
                summary=str(action.args.get("reason") or "模型认为证据足够，结束工具调用。"),
                data={},
            )

        raise ValueError(f"Unknown tool: {action.tool}")
    except Exception as exc:
        return ReactObservation(
            step=step,
            thought=action.thought,
            tool=action.tool,
            args=action.args,
            success=False,
            summary=humanize_tool_error(action.tool, exc),
            data={"error": str(exc)},
        )


def build_snapshot_from_observations(observations: list[ReactObservation]) -> NetworkSnapshot:
    gateway = None
    dns_servers: list[str] = []
    pings: dict[str, PingResult] = {}
    dns: dict[str, DnsResult] = {}
    traces: dict[str, TraceResult] = {}

    for observation in observations:
        if observation.tool == "get_network_profile":
            gateway = observation.data.get("gateway")
            dns_servers = list(observation.data.get("dns_servers") or [])
            continue
        if observation.tool == "ping_target" and observation.data.get("result"):
            name = str(observation.data.get("target_name") or observation.args.get("target") or "target")
            pings[name] = PingResult(**observation.data["result"])
            continue
        if observation.tool == "dns_lookup" and observation.data.get("result"):
            name = str(observation.data.get("target_name") or observation.args.get("host") or "host")
            dns[name] = DnsResult(**observation.data["result"])
            continue
        if observation.tool == "compare_dns":
            target_name = str(observation.data.get("target_name") or observation.args.get("host") or "host")
            for label, result in (observation.data.get("results") or {}).items():
                dns[f"{target_name}:{label}"] = DnsResult(**result)
            continue
        if observation.tool == "traceroute" and observation.data.get("result"):
            name = str(observation.data.get("target_name") or observation.args.get("target") or "target")
            raw_result = observation.data["result"]
            traces[name] = TraceResult(
                target=raw_result["target"],
                success=raw_result["success"],
                hops=[],
                raw=raw_result.get("raw", ""),
                error=raw_result.get("error"),
            )

    return NetworkSnapshot(
        created_at=datetime.now(),
        gateway=gateway,
        dns_servers=dns_servers,
        pings=pings,
        dns=dns,
        traces=traces,
    )


def extract_rag_hits(observations: list[ReactObservation]) -> list[RagHit]:
    hits: list[RagHit] = []
    for observation in observations:
        if observation.tool != "rag_search":
            continue
        for item in observation.data.get("hits", []):
            try:
                hits.append(RagHit(**item))
            except TypeError:
                continue
    return hits


def extract_monitor_summary(observations: list[ReactObservation]) -> MonitorSummary | None:
    for observation in reversed(observations):
        if observation.tool == "short_monitor" and observation.success:
            return MonitorSummary(points=[], conclusion=observation.summary)
    return None


def resolve_target(value: object, observations: list[ReactObservation]) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        raw = "public_dns"
    lowered = raw.lower()
    if lowered in TARGET_ALIASES:
        resolved = TARGET_ALIASES[lowered]
        if resolved == "__gateway__":
            gateway = latest_gateway(observations) or get_default_gateway()
            if not gateway:
                raise ValueError("未识别到默认网关")
            return "gateway", gateway
        return lowered, resolved
    if is_safe_target(raw):
        return raw, raw
    raise ValueError(f"目标格式不受支持：{raw}")


def latest_gateway(observations: list[ReactObservation]) -> str | None:
    for observation in reversed(observations):
        if observation.tool == "get_network_profile":
            gateway = observation.data.get("gateway")
            return str(gateway) if gateway else None
    return None


def is_safe_target(value: str) -> bool:
    if len(value) > 253 or any(char.isspace() for char in value):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        pass
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,251}[A-Za-z0-9]", value))


def bounded_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def count_recent_failures(observations: list[ReactObservation]) -> int:
    count = 0
    for observation in reversed(observations):
        if observation.success:
            break
        count += 1
    return count


def count_recent_repeated_actions(observations: list[ReactObservation]) -> int:
    if not observations:
        return 0
    latest = observations[-1]
    count = 0
    for observation in reversed(observations):
        if observation.tool != latest.tool:
            break
        if normalize_args(observation.args) != normalize_args(latest.args):
            break
        count += 1
    return count


def normalize_args(args: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in args.items()))


def humanize_tool_error(tool: str, exc: Exception) -> str:
    message = str(exc)
    if tool == "get_network_profile":
        return f"读取本机网络信息失败：{message or '系统命令没有正常返回。'}"
    if tool == "ping_target":
        return f"Ping 检测失败：{message or '目标不可达或命令执行失败。'}"
    if tool == "dns_lookup":
        return f"DNS 检测失败：{message or '域名解析过程异常。'}"
    if tool == "compare_dns":
        return f"DNS 对比失败：{message or '多个 DNS 对比过程没有完成。'}"
    if tool == "traceroute":
        return f"路由追踪失败：{message or '命令超时或目标拒绝响应。'}"
    if tool == "short_monitor":
        return f"短时监控失败：{message or '连续采样未能完成。'}"
    if tool == "rag_search":
        return f"知识检索失败：{message or '本地向量库不可用。'}"
    if tool == "recall_memory":
        return f"历史记忆读取失败：{message or '本地记忆文件不可用。'}"
    return f"工具执行失败：{message or '未知异常。'}"
