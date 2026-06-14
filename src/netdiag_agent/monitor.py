from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from netdiag_agent.probe import ping


@dataclass
class MonitorPoint:
    timestamp: datetime
    target_name: str
    target: str
    avg_ms: float | None
    packet_loss_percent: float | None
    success: bool


@dataclass
class MonitorSummary:
    points: list[MonitorPoint]
    conclusion: str


def run_monitor(
    targets: dict[str, str],
    samples: int = 5,
    interval_seconds: int = 5,
    ping_count: int = 2,
) -> MonitorSummary:
    points: list[MonitorPoint] = []
    bounded_samples = max(1, min(samples, 30))
    bounded_interval = max(1, min(interval_seconds, 60))

    for sample_index in range(bounded_samples):
        for name, target in targets.items():
            result = ping(target, count=ping_count, timeout=8)
            points.append(
                MonitorPoint(
                    timestamp=datetime.now(),
                    target_name=name,
                    target=target,
                    avg_ms=result.avg_ms,
                    packet_loss_percent=result.packet_loss_percent,
                    success=result.success,
                )
            )
        if sample_index < bounded_samples - 1:
            time.sleep(bounded_interval)

    conclusion = summarize_monitor(points)
    return MonitorSummary(points=points, conclusion=conclusion)


def summarize_monitor(points: list[MonitorPoint]) -> str:
    if not points:
        return "没有采集到监控数据。"

    loss_points = [p for p in points if (p.packet_loss_percent or 0) > 0]
    latency_values = [p.avg_ms for p in points if p.avg_ms is not None]
    if not latency_values:
        return "监控期间目标不可达，需要检查本机网络或目标地址。"

    avg_latency = sum(latency_values) / len(latency_values)
    max_latency = max(latency_values)
    jitter = max_latency - min(latency_values)

    if loss_points:
        return f"监控期间出现丢包，最高延迟 {max_latency:.1f} ms，更像实时链路质量不稳定。"
    if jitter >= 80:
        return f"监控期间延迟波动较大，抖动约 {jitter:.1f} ms，游戏/会议可能会卡。"
    if avg_latency >= 120:
        return f"监控期间平均延迟较高，约 {avg_latency:.1f} ms，可能存在出口或上游链路拥塞。"
    return f"监控期间链路稳定，平均延迟约 {avg_latency:.1f} ms，未发现明显持续性异常。"


def monitor_to_rows(summary: MonitorSummary) -> list[dict[str, object]]:
    return [
        {
            "time": point.timestamp.strftime("%H:%M:%S"),
            "target_name": point.target_name,
            "target": point.target,
            "avg_ms": point.avg_ms,
            "packet_loss_percent": point.packet_loss_percent,
            "success": point.success,
        }
        for point in summary.points
    ]


