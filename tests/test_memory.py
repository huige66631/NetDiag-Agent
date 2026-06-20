from datetime import datetime

from netdiag_agent.memory import NetworkMemory
from netdiag_agent.models import Diagnosis, DnsResult, NetworkSnapshot, PingResult
from netdiag_agent.planner import AgentPlan


def build_plan(mode: str = "web", custom_target: str | None = None) -> AgentPlan:
    targets = {"public_dns": "223.5.5.5", "baidu": "www.baidu.com"}
    if custom_target:
        targets["custom"] = custom_target
    return AgentPlan(
        mode=mode,
        title="测试计划",
        targets=targets,
        include_trace=False,
        monitor_recommended=False,
        rationale=["test"],
    )


def build_snapshot(
    *,
    summary: str,
    severity: str,
    evidence: list[str],
    suggestions: list[str],
    dns_elapsed_ms: float = 900,
    ping_loss: float = 0,
) -> NetworkSnapshot:
    return NetworkSnapshot(
        created_at=datetime.now(),
        gateway="192.168.1.1",
        dns_servers=["223.5.5.5"],
        pings={
            "public_dns": PingResult(
                target="223.5.5.5",
                success=ping_loss < 100,
                packets_sent=4,
                packets_received=0 if ping_loss >= 100 else 4,
                packet_loss_percent=ping_loss,
                min_ms=15,
                avg_ms=30,
                max_ms=45,
            )
        },
        dns={
            "baidu": DnsResult(
                host="www.baidu.com",
                success=dns_elapsed_ms < 1500,
                addresses=["1.1.1.1"],
                elapsed_ms=dns_elapsed_ms,
                dns_server="223.5.5.5",
            )
        },
        traces={},
        diagnosis=Diagnosis(
            summary=summary,
            severity=severity,
            likely_causes=["test"],
            evidence=evidence,
            suggestions=suggestions,
        ),
    )


def test_memory_merges_repeated_cases_and_keeps_overview(tmp_path):
    store = NetworkMemory(tmp_path / "memory.jsonl")
    plan = build_plan(custom_target="www.qq.com")
    snapshot = build_snapshot(
        summary="更像是 DNS 解析慢，导致网页打开延迟。",
        severity="medium",
        evidence=["DNS 耗时 920 ms", "公网 Ping 基本正常"],
        suggestions=["更换 DNS 再试一次"],
    )

    first = store.remember("网页打不开，DNS 很慢", plan, snapshot)
    second = store.remember("网页还是打不开，DNS 问题反复出现", plan, snapshot)

    records = store.load(limit=None)
    overview = store.overview()

    assert first is not None
    assert second is not None
    assert len(records) == 1
    assert records[0].occurrences == 2
    assert records[0].issue_type == "dns"
    assert overview.total_records == 1
    assert overview.repeated_records == 1
    assert overview.high_value_records == 1


def test_memory_recall_prefers_similar_cases(tmp_path):
    store = NetworkMemory(tmp_path / "memory.jsonl")

    dns_snapshot = build_snapshot(
        summary="更像是 DNS 解析慢，导致网页打开延迟。",
        severity="medium",
        evidence=["DNS 耗时 900 ms", "本地链路正常"],
        suggestions=["切换公共 DNS"],
    )
    latency_snapshot = build_snapshot(
        summary="更像是公网链路抖动，导致游戏延迟升高。",
        severity="high",
        evidence=["Ping 丢包 12%", "晚高峰抖动明显"],
        suggestions=["避开高峰期", "继续短时监控"],
        dns_elapsed_ms=60,
        ping_loss=12,
    )

    store.remember("网页打不开，DNS 特别慢", build_plan(mode="web"), dns_snapshot)
    store.remember("打游戏跳 ping，很卡", build_plan(mode="gaming"), latency_snapshot)
    store.remember("网页打不开，DNS 特别慢", build_plan(mode="web"), dns_snapshot)

    matches = store.recall_matches("现在打开网站很慢，怀疑是 DNS 解析问题", mode="web", limit=2)

    assert len(matches) >= 1
    assert matches[0].record.issue_type == "dns"
    assert matches[0].record.occurrences >= 2
    assert matches[0].score >= matches[-1].score
    assert any("关键词重合" in reason or "症状描述较相似" in reason for reason in matches[0].reasons)
