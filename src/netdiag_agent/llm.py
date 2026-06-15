from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from netdiag_agent.models import NetworkSnapshot
from netdiag_agent.planner import AgentPlan, plan_from_context


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass
class LlmReport:
    success: bool
    content: str
    model: str
    error: str | None = None


@dataclass
class LlmToolPlan:
    success: bool
    plan: AgentPlan
    model: str
    raw: str = ""
    error: str | None = None


def load_local_env() -> None:
    env_path = Path.cwd() / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_report_prompt(snapshot: NetworkSnapshot, user_context: str = "") -> list[dict[str, str]]:
    system = (
        "你是一个本地网络诊断 Agent，面向通信工程学生项目展示。"
        "你必须基于工具采集到的真实网络数据分析，不要编造不存在的测试结果。"
        "输出要包含：一句话结论、证据分析、可能原因、给用户的操作建议、给网络管理员或运营商的反馈版本。"
        "如果证据不足，要明确说明还需要做哪些补充测试。"
    )
    payload: dict[str, Any] = snapshot.to_dict()
    user = (
        f"用户补充描述：{user_context or '无'}\n\n"
        "下面是本地网络诊断工具采集到的结构化数据，请生成中文诊断报告：\n"
        f"{payload}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_agent_prompt(
    snapshot: NetworkSnapshot,
    user_context: str = "",
    plan: object | None = None,
    monitor_summary: object | None = None,
) -> list[dict[str, str]]:
    system = (
        "你是 NetDiag Agent 的大模型分析层。"
        "你需要解释 Agent 为什么选择这些工具、每个工具结果说明了什么、下一步应该做什么。"
        "不要编造未执行的测试，不要声称已经测了游戏服务器，除非数据里存在。"
        "输出结构：诊断结论、Agent 执行流程、证据分析、建议操作、给网络管理员或运营商的反馈。"
        "语言要自然、简洁、像中文技术报告，不要使用生硬直译。"
        "不要使用 Markdown 删除线语法，不要输出 ~~。时间范围请写成“20:00-23:00”。"
        "不要说“无法否认用户问题”，应改为“当前快照未捕捉到异常，仍建议用持续监控验证”。"
    )
    payload: dict[str, Any] = {
        "user_context": user_context,
        "agent_plan": getattr(plan, "__dict__", plan),
        "snapshot": snapshot.to_dict(),
        "monitor_summary": getattr(monitor_summary, "__dict__", monitor_summary),
    }
    user = f"请基于下面真实数据生成中文 Agent 诊断报告：\n{payload}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_tool_plan_prompt(user_context: str, requested_mode: str = "auto") -> list[dict[str, str]]:
    system = (
        "你是 NetDiag Agent 的工具规划器。你只能从白名单网络诊断工具中选择探测计划。"
        "不要输出 Markdown，不要解释，只输出一个 JSON 对象。"
        "可用工具含义：ping 用于测延迟和丢包；dns_lookup 用于测域名解析；"
        "traceroute 用于看路由路径但耗时较长；short_monitor 用于多次采样观察抖动。"
        "允许的目标只有：public_dns=223.5.5.5, tencent_dns=119.29.29.29, "
        "baidu=www.baidu.com, bilibili=www.bilibili.com。"
        "如果用户没有明确问题，选择快速诊断，不要默认开启 traceroute。"
        "如果用户描述出现游戏、打瓦、Valorant、LOL、跳 Ping、延迟、卡顿等实时交互问题，必须选择 gaming，"
        "目标必须包含 public_dns、tencent_dns、baidu，并且 monitor_recommended 必须为 true。"
        "如果是网页打不开或 DNS 问题，选择 public_dns、baidu、bilibili，并关注 DNS。"
        "如果是单个网站慢，可以开启 traceroute。"
        "示例1：用户说“晚上打游戏卡，但刷网页还行”，输出 mode=gaming。"
        "示例2：用户说“网页打不开，怀疑 DNS”，输出 mode=web。"
        "示例3：用户说“只有 B 站慢”，输出 mode=single_site。"
    )
    user = (
        "请基于用户描述选择工具计划。\n"
        f"用户描述：{user_context or '无'}\n"
        f"用户界面选择的模式：{requested_mode}\n"
        "输出 JSON 格式如下："
        '{"mode":"quick|gaming|web|single_site|deep",'
        '"title":"简短中文标题",'
        '"targets":{"public_dns":"223.5.5.5"},'
        '"include_trace":false,'
        '"monitor_recommended":false,'
        '"rationale":["为什么选择这些工具"]}'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_deepseek_tool_plan(user_context: str, requested_mode: str = "auto") -> LlmToolPlan:
    load_local_env()
    selected_model = os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    fallback = plan_from_context(user_context, requested_mode)
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")

    if not api_key:
        return LlmToolPlan(False, fallback, selected_model, error="DEEPSEEK_API_KEY is not configured.")

    payload = {
        "model": selected_model,
        "messages": build_tool_plan_prompt(user_context, requested_mode),
        "temperature": 0,
        "stream": False,
    }
    try:
        data = _chat_completion(base_url, api_key, payload, selected_model, timeout=30)
        content = data["choices"][0]["message"]["content"].strip()
        plan = parse_tool_plan(content, fallback)
        return LlmToolPlan(True, plan, selected_model, raw=content)
    except Exception as exc:
        return LlmToolPlan(False, fallback, selected_model, error=str(exc))


def parse_tool_plan(content: str, fallback: AgentPlan) -> AgentPlan:
    raw = content.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?", "", raw).strip()
        raw = re.sub(r"```$", "", raw).strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if match:
        raw = match.group(0)
    data = json.loads(raw)

    allowed_targets = {
        "public_dns": "223.5.5.5",
        "tencent_dns": "119.29.29.29",
        "baidu": "www.baidu.com",
        "bilibili": "www.bilibili.com",
    }
    requested_targets = data.get("targets") or {}
    targets = {
        name: allowed_targets[name]
        for name in requested_targets
        if name in allowed_targets
    }
    mode = str(data.get("mode") or fallback.mode)
    if mode not in {"quick", "gaming", "web", "single_site", "deep"}:
        mode = fallback.mode
    if fallback.mode != "quick" and mode == "quick":
        mode = fallback.mode
    if not targets or (
        mode == "gaming" and not {"public_dns", "tencent_dns", "baidu"}.issubset(targets)
    ):
        targets = fallback.targets
    title = str(data.get("title") or fallback.title)[:30]
    rationale_raw = data.get("rationale")
    rationale = (
        [str(item) for item in rationale_raw[:4]]
        if isinstance(rationale_raw, list)
        else fallback.rationale
    )

    return AgentPlan(
        mode=mode,
        title=title,
        targets=targets,
        include_trace=bool(data.get("include_trace", fallback.include_trace)),
        monitor_recommended=(
            True if mode == "gaming" else bool(data.get("monitor_recommended", fallback.monitor_recommended))
        ),
        rationale=rationale,
        source="llm",
    )


def generate_deepseek_report(
    snapshot: NetworkSnapshot,
    user_context: str = "",
    plan: object | None = None,
    monitor_summary: object | None = None,
    model: str | None = None,
    timeout: int = 45,
) -> LlmReport:
    load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    selected_model = model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")

    if not api_key:
        return LlmReport(
            success=False,
            content="",
            model=selected_model,
            error="DEEPSEEK_API_KEY is not configured.",
        )

    payload = {
        "model": selected_model,
        "messages": build_agent_prompt(snapshot, user_context, plan, monitor_summary),
        "temperature": 0.2,
        "stream": False,
    }

    try:
        data = _chat_completion(base_url, api_key, payload, selected_model, timeout)
        content = clean_llm_report(data["choices"][0]["message"]["content"])
        return LlmReport(success=True, content=content, model=selected_model)
    except Exception as exc:
        return LlmReport(
            success=False,
            content="",
            model=selected_model,
            error=str(exc),
        )


def _chat_completion(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    model: str,
    timeout: int,
) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "netdiag-agent/0.1",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        fallback = _generate_with_curl(base_url, api_key, payload, model, timeout, raw_json=True)
        if fallback.success:
            return json.loads(fallback.content)
        raise RuntimeError(f"requests failed: {exc}; curl fallback failed: {fallback.error}") from exc


def _generate_with_curl(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    model: str,
    timeout: int,
    raw_json: bool = False,
) -> LlmReport:
    command = [
        "curl.exe",
        "-sS",
        "-X",
        "POST",
        f"{base_url}/chat/completions",
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        json.dumps(payload, ensure_ascii=False),
        "-m",
        str(timeout),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
        )
        if completed.returncode != 0:
            return LlmReport(False, "", model, completed.stderr.strip() or "curl failed")
        data = json.loads(completed.stdout)
        if "error" in data:
            return LlmReport(False, "", model, str(data["error"]))
        if raw_json:
            return LlmReport(True, completed.stdout, model)
        return LlmReport(True, clean_llm_report(data["choices"][0]["message"]["content"]), model)
    except Exception as exc:
        return LlmReport(False, "", model, str(exc))


def clean_llm_report(content: str) -> str:
    cleaned = content.strip()
    cleaned = re.sub(r"(\d{1,2}:\d{2})\s*(?:~~|~|～|—|–)\s*(\d{1,2}:\d{2})", r"\1-\2", cleaned)
    cleaned = cleaned.replace("~~", "")
    cleaned = cleaned.replace("无法否认用户问题", "不能排除用户遇到的是间歇性问题")
    cleaned = cleaned.replace("仅凭当前凌晨数据", "仅凭当前这次快照数据")
    cleaned = cleaned.replace("当前凌晨数据", "当前这次快照数据")
    cleaned = re.sub(r"(?<!\d)10\s*30\s*分钟", "10-30 分钟", cleaned)
    cleaned = re.sub(r"(?<!\d)1030\s*分钟", "10-30 分钟", cleaned)
    return cleaned

