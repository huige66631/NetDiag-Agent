from __future__ import annotations

import json
from pathlib import Path

from campusnet_agent.models import NetworkSnapshot


def render_markdown(snapshot: NetworkSnapshot) -> str:
    diagnosis = snapshot.diagnosis
    lines = [
        "# 校园网诊断报告",
        "",
        f"- 生成时间：{snapshot.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 默认网关：{snapshot.gateway or '未识别'}",
        f"- DNS 服务器：{', '.join(snapshot.dns_servers) if snapshot.dns_servers else '未识别'}",
        "",
        "## 诊断结论",
        "",
        diagnosis.summary if diagnosis else "尚未生成诊断结论。",
        "",
    ]

    if diagnosis:
        lines.extend(["## 证据", ""])
        lines.extend(f"- {item}" for item in diagnosis.evidence)
        lines.extend(["", "## 可能原因", ""])
        lines.extend(f"- {item}" for item in diagnosis.likely_causes)
        lines.extend(["", "## 建议操作", ""])
        lines.extend(f"- {item}" for item in diagnosis.suggestions)

    lines.extend(["", "## Ping 结果", ""])
    for name, item in snapshot.pings.items():
        lines.append(
            f"- {name} ({item.target})：成功={item.success}，平均={item.avg_ms} ms，丢包={item.packet_loss_percent}%"
        )

    lines.extend(["", "## DNS 结果", ""])
    for name, item in snapshot.dns.items():
        lines.append(
            f"- {name} ({item.host})：成功={item.success}，耗时={item.elapsed_ms} ms，地址={', '.join(item.addresses) or '无'}"
        )

    return "\n".join(lines).strip() + "\n"


def save_report(snapshot: NetworkSnapshot, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    stamp = snapshot.created_at.strftime("%Y%m%d_%H%M%S")
    md_path = path / f"campusnet_report_{stamp}.md"
    json_path = path / f"campusnet_snapshot_{stamp}.json"
    md_path.write_text(render_markdown(snapshot), encoding="utf-8")
    json_path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return md_path, json_path

