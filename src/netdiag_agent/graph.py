from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from netdiag_agent.agent import build_agent_trace
from netdiag_agent.diagnosis import diagnose
from netdiag_agent.llm import (
    LlmReactDecision,
    LlmReport,
    fallback_react_action,
    generate_deepseek_react_action,
    generate_deepseek_report,
)
from netdiag_agent.memory import MemoryRecord, NetworkMemory
from netdiag_agent.monitor import MonitorSummary
from netdiag_agent.planner import AgentPlan, plan_from_context
from netdiag_agent.rag import RagHit, rag_hits_to_context
from netdiag_agent.react import (
    ReactAction,
    ReactGuardDecision,
    ReactObservation,
    build_snapshot_from_observations,
    evaluate_react_progress,
    execute_react_tool,
    extract_monitor_summary,
    extract_rag_hits,
)


class NetDiagState(TypedDict, total=False):
    user_context: str
    requested_mode: str
    use_llm_planner: bool
    use_llm_report: bool
    run_monitor_enabled: bool
    custom_target: str
    samples: int
    interval_seconds: int
    max_steps: int
    plan: AgentPlan
    current_action: ReactAction
    current_decision: LlmReactDecision | None
    react_decisions: list[LlmReactDecision]
    react_observations: list[ReactObservation]
    guard_decision: ReactGuardDecision | None
    stop_reason: str
    snapshot: Any
    monitor_summary: MonitorSummary | None
    rag_hits: list[RagHit]
    rag_context: str
    memory_records: list[MemoryRecord]
    memory_context: str
    llm_report: LlmReport | None
    agent_trace: list[Any]
    graph_steps: list[str]


def append_step(state: NetDiagState, step: str) -> None:
    state.setdefault("graph_steps", []).append(step)


def init_react_node(state: NetDiagState) -> NetDiagState:
    user_context = state.get("user_context", "")
    custom_target = state.get("custom_target", "").strip()
    context_for_planning = (
        f"{user_context}\n[custom_target={custom_target}]"
        if custom_target
        else user_context
    )
    state["user_context"] = context_for_planning
    state["plan"] = plan_from_context(context_for_planning, state.get("requested_mode", "auto"))
    custom_target = state.get("custom_target", "").strip()
    if custom_target:
        state["plan"].targets["custom"] = custom_target
    state["react_decisions"] = []
    state["react_observations"] = []
    state["guard_decision"] = None
    state["stop_reason"] = ""
    state["memory_records"] = []
    state["memory_context"] = "暂无历史诊断记忆。"
    state["rag_hits"] = []
    state["rag_context"] = "未检索到相关网络知识。"
    append_step(state, "react.init")
    return state


def decide_next_tool_node(state: NetDiagState) -> NetDiagState:
    observations = state.get("react_observations", [])
    if state.get("use_llm_planner", True):
        decision = generate_deepseek_react_action(
            state.get("user_context", ""),
            observations,
            requested_mode=state.get("requested_mode", "auto"),
            max_steps=state.get("max_steps", 8),
        )
    else:
        action = fallback_react_action(
            state.get("user_context", ""),
            observations,
            requested_mode=state.get("requested_mode", "auto"),
            max_steps=state.get("max_steps", 8),
        )
        decision = LlmReactDecision(success=True, action=action, model="local-heuristic")
    state["current_decision"] = decision
    state["current_action"] = decision.action
    state.setdefault("react_decisions", []).append(decision)
    append_step(state, f"llm.decide:{decision.action.tool}")
    return state


def route_after_decision(state: NetDiagState) -> str:
    if state["current_action"].tool == "final_answer":
        return "synthesize"
    return "execute"


def execute_tool_node(state: NetDiagState) -> NetDiagState:
    observations = state.setdefault("react_observations", [])
    action = state["current_action"]
    if action.tool == "short_monitor":
        args = dict(action.args)
        args.setdefault("samples", state.get("samples", 5))
        args.setdefault("interval_seconds", state.get("interval_seconds", 5))
        action = ReactAction(thought=action.thought, tool=action.tool, args=args)
    observation = execute_react_tool(
        action,
        step=len(observations) + 1,
        user_context=state.get("user_context", ""),
        observations=observations,
    )
    observations.append(observation)
    guard = evaluate_react_progress(observations)
    state["guard_decision"] = guard
    if guard.should_stop:
        state["stop_reason"] = guard.reason
    append_step(state, f"tool.{observation.tool}")
    return state


def route_after_tool(state: NetDiagState) -> str:
    observations = state.get("react_observations", [])
    guard = state.get("guard_decision")
    if guard and guard.should_stop:
        return "synthesize"
    if len(observations) >= state.get("max_steps", 8):
        state["stop_reason"] = "已达到最大工具调用次数，停止继续试探并进入保底诊断。"
        return "synthesize"
    return "decide"


def synthesize_node(state: NetDiagState) -> NetDiagState:
    observations = state.get("react_observations", [])
    snapshot = build_snapshot_from_observations(observations)
    diagnose(snapshot)
    state["snapshot"] = snapshot
    state["rag_hits"] = extract_rag_hits(observations)
    state["rag_context"] = rag_hits_to_context(state["rag_hits"])
    state["monitor_summary"] = extract_monitor_summary(observations)

    records = _extract_memory_records(observations)
    state["memory_records"] = records
    state["memory_context"] = _safe_memory_context(records)

    if state.get("stop_reason"):
        snapshot.diagnosis.evidence.append(state["stop_reason"])

    if state.get("use_llm_report", True):
        state["llm_report"] = generate_deepseek_report(
            snapshot,
            user_context=state.get("user_context", ""),
            plan=state.get("plan"),
            monitor_summary=state.get("monitor_summary"),
            rag_context=state.get("rag_context", ""),
            memory_context=state.get("memory_context", ""),
        )
    else:
        state["llm_report"] = None

    state["agent_trace"] = build_agent_trace(
        state.get("user_context", ""),
        state["plan"],
        snapshot,
        state.get("monitor_summary"),
        rag_hits=state.get("rag_hits", []),
        memory_records=state.get("memory_records", []),
    )
    append_step(state, "react.synthesize")
    return state


def remember_node(state: NetDiagState) -> NetDiagState:
    try:
        NetworkMemory().remember(
            state.get("user_context", ""),
            state["plan"],
            state["snapshot"],
            state.get("monitor_summary"),
        )
    except Exception as exc:
        state["stop_reason"] = (
            f"{state.get('stop_reason', '')} 历史记忆写入失败：{exc}".strip()
        )
    append_step(state, "memory.write")
    return state


def _extract_memory_records(observations: list[ReactObservation]) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    for observation in observations:
        if observation.tool != "recall_memory":
            continue
        for item in observation.data.get("records", []):
            try:
                records.append(MemoryRecord(**item))
            except TypeError:
                continue
    return records


def _safe_memory_context(records: list[MemoryRecord]) -> str:
    try:
        return NetworkMemory().context_text(records)
    except Exception:
        return "历史记忆不可用，本次仅依据当前检测结果分析。"


def build_netdiag_graph():
    graph = StateGraph(NetDiagState)
    graph.add_node("init", init_react_node)
    graph.add_node("decide", decide_next_tool_node)
    graph.add_node("execute", execute_tool_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("remember", remember_node)

    graph.set_entry_point("init")
    graph.add_edge("init", "decide")
    graph.add_conditional_edges("decide", route_after_decision, {"execute": "execute", "synthesize": "synthesize"})
    graph.add_conditional_edges("execute", route_after_tool, {"decide": "decide", "synthesize": "synthesize"})
    graph.add_edge("synthesize", "remember")
    graph.add_edge("remember", END)
    return graph.compile()


def run_netdiag_graph(
    user_context: str,
    requested_mode: str = "auto",
    use_llm_planner: bool = True,
    use_llm_report: bool = True,
    run_monitor_enabled: bool = False,
    custom_target: str = "",
    samples: int = 5,
    interval_seconds: int = 5,
    max_steps: int = 8,
) -> NetDiagState:
    graph = build_netdiag_graph()
    initial_state: NetDiagState = {
        "user_context": user_context,
        "requested_mode": requested_mode,
        "use_llm_planner": use_llm_planner,
        "use_llm_report": use_llm_report,
        "run_monitor_enabled": run_monitor_enabled,
        "custom_target": custom_target,
        "samples": samples,
        "interval_seconds": interval_seconds,
        "max_steps": max_steps,
        "graph_steps": [],
    }
    return graph.invoke(initial_state)
