from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPlan:
    mode: str
    title: str
    targets: dict[str, str]
    include_trace: bool
    monitor_recommended: bool
    rationale: list[str]


COMMON_TARGETS = {
    "public_dns": "223.5.5.5",
    "baidu": "www.baidu.com",
    "bilibili": "www.bilibili.com",
}

GAME_TARGETS = {
    "public_dns": "223.5.5.5",
    "tencent_dns": "119.29.29.29",
    "baidu": "www.baidu.com",
}


def plan_from_context(user_context: str, mode: str = "auto") -> AgentPlan:
    text = user_context.lower()
    selected = mode
    rationale: list[str] = []

    if mode == "auto":
        if any(word in text for word in ["游戏", "打瓦", "瓦", "valorant", "lol", "延迟", "跳ping", "卡顿"]):
            selected = "gaming"
            rationale.append("用户描述包含游戏/跳 Ping/卡顿，优先检测丢包、抖动和公网实时链路。")
        elif any(word in text for word in ["网页", "打不开", "域名", "dns", "解析"]):
            selected = "web"
            rationale.append("用户描述偏网页访问问题，优先检测 DNS 解析和常见站点连通性。")
        elif any(word in text for word in ["b站", "bilibili", "视频", "加载"]):
            selected = "single_site"
            rationale.append("用户描述偏单站点慢，优先检测目标站点 DNS、Ping 和路由路径。")
        else:
            selected = "quick"
            rationale.append("未识别到明确症状，使用通用快速诊断流程。")

    if selected == "gaming":
        return AgentPlan(
            mode="gaming",
            title="游戏卡顿诊断",
            targets=GAME_TARGETS,
            include_trace=False,
            monitor_recommended=True,
            rationale=rationale or ["游戏场景重点关注丢包、抖动和晚高峰变化。"],
        )
    if selected == "web":
        return AgentPlan(
            mode="web",
            title="网页访问诊断",
            targets=COMMON_TARGETS,
            include_trace=False,
            monitor_recommended=False,
            rationale=rationale or ["网页场景优先检查 DNS 和基础连通性。"],
        )
    if selected == "single_site":
        return AgentPlan(
            mode="single_site",
            title="单站点访问诊断",
            targets=COMMON_TARGETS,
            include_trace=True,
            monitor_recommended=False,
            rationale=rationale or ["单站点慢需要结合 DNS、Ping 和路由路径判断。"],
        )
    if selected == "deep":
        return AgentPlan(
            mode="deep",
            title="深度路由诊断",
            targets=COMMON_TARGETS,
            include_trace=True,
            monitor_recommended=True,
            rationale=rationale or ["深度诊断会执行 tracert，耗时更长但证据更完整。"],
        )

    return AgentPlan(
        mode="quick",
        title="快速通用诊断",
        targets=COMMON_TARGETS,
        include_trace=False,
        monitor_recommended=False,
        rationale=rationale or ["快速诊断默认跳过 tracert，优先给出基础判断。"],
    )


