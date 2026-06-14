from __future__ import annotations

from dataclasses import dataclass

from campusnet_agent.models import NetworkSnapshot
from campusnet_agent.monitor import MonitorSummary
from campusnet_agent.planner import AgentPlan


@dataclass(frozen=True)
class AgentTraceStep:
    step: int
    phase: str
    action: str
    observation: str
    next_decision: str


def build_agent_trace(
    user_context: str,
    plan: AgentPlan,
    snapshot: NetworkSnapshot | None = None,
    monitor_summary: MonitorSummary | None = None,
) -> list[AgentTraceStep]:
    steps = [
        AgentTraceStep(
            step=1,
            phase="理解任务",
            action="读取用户描述并识别网络问题类型。",
            observation=f"用户描述：{user_context or '未提供具体症状'}",
            next_decision=f"选择“{plan.title}”流程。",
        ),
        AgentTraceStep(
            step=2,
            phase="选择工具",
            action="根据诊断模式选择本地网络探测工具。",
            observation=(
                f"目标：{', '.join(plan.targets.values())}；"
                f"tracert：{'开启' if plan.include_trace else '关闭'}；"
                f"短时监控建议：{'是' if plan.monitor_recommended else '否'}。"
            ),
            next_decision="开始采集当前设备和校园网环境下的真实数据。",
        ),
    ]

    if snapshot is None:
        return steps

    gateway = snapshot.pings.get("gateway")
    gateway_text = (
        f"网关 {gateway.target} 平均 {gateway.avg_ms} ms，丢包 {gateway.packet_loss_percent}%"
        if gateway
        else "未识别到默认网关。"
    )
    ping_targets = [
        f"{name}: {result.avg_ms} ms / 丢包 {result.packet_loss_percent}%"
        for name, result in snapshot.pings.items()
        if name != "gateway"
    ]
    steps.append(
        AgentTraceStep(
            step=3,
            phase="执行探测",
            action="执行网关、公网目标和 DNS 探测。",
            observation=f"{gateway_text}；" + "；".join(ping_targets),
            next_decision="将探测结果交给规则诊断模块判断瓶颈位置。",
        )
    )

    diagnosis = snapshot.diagnosis
    steps.append(
        AgentTraceStep(
            step=4,
            phase="规则判断",
            action="根据延迟、丢包和 DNS 耗时进行确定性诊断。",
            observation=diagnosis.summary if diagnosis else "尚未生成规则诊断。",
            next_decision=(
                "如果一次快照未发现异常，则建议用短时监控捕捉间歇性抖动。"
                if not monitor_summary
                else "结合短时监控结果生成最终报告。"
            ),
        )
    )

    if monitor_summary:
        steps.append(
            AgentTraceStep(
                step=5,
                phase="持续观察",
                action="执行多次采样，观察延迟波动和丢包趋势。",
                observation=monitor_summary.conclusion,
                next_decision="把快照证据和监控趋势交给大模型生成可解释报告。",
            )
        )

    steps.append(
        AgentTraceStep(
            step=len(steps) + 1,
            phase="生成报告",
            action="调用 DeepSeek，将结构化证据转成面向学生和网络中心的报告。",
            observation="大模型只基于已采集数据解释，不编造未执行的测试。",
            next_decision="输出最终建议，并提示还需要补充的证据。",
        )
    )
    return steps


def trace_to_rows(steps: list[AgentTraceStep]) -> list[dict[str, object]]:
    return [
        {
            "步骤": step.step,
            "阶段": step.phase,
            "动作": step.action,
            "观察": step.observation,
            "下一步决策": step.next_decision,
        }
        for step in steps
    ]

