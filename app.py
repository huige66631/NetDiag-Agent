from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from netdiag_agent.agent import build_agent_trace, trace_to_rows
from netdiag_agent.diagnosis import diagnose, summarize_dns_comparison
from netdiag_agent.graph import run_netdiag_graph
from netdiag_agent.memory import NetworkMemory, memory_records_to_rows
from netdiag_agent.monitor import monitor_to_rows, run_monitor
from netdiag_agent.planner import plan_from_context
from netdiag_agent.probe import collect_snapshot
from netdiag_agent.rag import rag_hits_to_rows
from netdiag_agent.react import observation_rows
from netdiag_agent.report import render_markdown, save_report


st.set_page_config(
    page_title="NetDiag Agent",
    page_icon="CN",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stStatusWidget"] { display: none; }

    :root {
        --bg: #f5f7fa;
        --surface: #ffffff;
        --surface-subtle: #f8fafc;
        --surface-strong: #eef2f7;
        --border: #d9e2ec;
        --border-strong: #b8c4d4;
        --ink: #17212b;
        --muted: #5f6f82;
        --accent: #1769aa;
        --accent-soft: #e8f1fb;
        --good: #1d7a46;
        --warn: #b76a12;
        --danger: #b03a48;
        --shadow: 0 14px 34px rgba(15, 23, 42, 0.06);
    }

    .stApp {
        background: linear-gradient(180deg, #f6f8fb 0%, #eef3f8 100%);
    }

    .block-container {
        max-width: 1220px;
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f4f7fb 0%, #edf2f8 100%);
        border-right: 1px solid var(--border);
    }

    [data-testid="stSidebar"] .block-container {
        padding-top: 1rem;
        padding-bottom: 1.5rem;
        padding-left: 0.9rem;
        padding-right: 0.9rem;
    }

    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        line-height: 1.5;
    }

    [data-testid="stSidebar"] .stTextArea textarea,
    [data-testid="stSidebar"] .stTextInput input,
    [data-testid="stSidebar"] [data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stSlider,
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        border-radius: 8px;
    }

    [data-testid="stSidebar"] .stButton button {
        height: 2.9rem;
        border-radius: 8px;
        font-weight: 600;
    }

    .sidebar-panel {
        background: rgba(255, 255, 255, 0.78);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 0.95rem 1rem;
        box-shadow: 0 10px 22px rgba(15, 23, 42, 0.05);
        margin-bottom: 0.9rem;
    }

    .sidebar-panel-title {
        color: var(--ink);
        font-size: 0.98rem;
        font-weight: 600;
        margin-bottom: 0.3rem;
    }

    .sidebar-panel-copy {
        color: var(--muted);
        font-size: 0.86rem;
        line-height: 1.55;
    }

    .sidebar-section-label {
        color: var(--accent);
        font-size: 0.76rem;
        font-weight: 700;
        margin: 0.2rem 0 0.45rem 0;
    }

    .sidebar-divider {
        height: 1px;
        background: rgba(184, 196, 212, 0.8);
        margin: 0.8rem 0;
    }

    .hero {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1.35rem 1.45rem;
        box-shadow: var(--shadow);
        margin-bottom: 1rem;
    }

    .hero-copy {
        max-width: 64ch;
    }

    .eyebrow {
        color: var(--accent);
        font-size: 0.82rem;
        font-weight: 600;
        margin-bottom: 0.4rem;
    }

    .hero h1 {
        margin: 0;
        color: var(--ink);
        font-size: 2rem;
        line-height: 1.15;
        letter-spacing: 0;
        text-wrap: balance;
    }

    .hero p {
        margin: 0.65rem 0 0 0;
        color: var(--muted);
        font-size: 0.98rem;
        line-height: 1.65;
        text-wrap: pretty;
    }

    .memory-banner {
        margin-top: 0.9rem;
        background: var(--accent-soft);
        border: 1px solid #cfe0f5;
        border-radius: 8px;
        padding: 0.8rem 0.95rem;
        color: #274b73;
        font-size: 0.9rem;
        line-height: 1.55;
    }

    .section-card {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem 1.05rem;
        box-shadow: var(--shadow);
    }

    .card-title {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 600;
        margin-bottom: 0.28rem;
    }

    .card-copy {
        color: var(--muted);
        font-size: 0.9rem;
        line-height: 1.55;
    }

    .status-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(0, 1fr));
        gap: 0.75rem;
        margin: 1rem 0 1.1rem 0;
    }

    .status-tile {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 0.9rem 1rem;
        box-shadow: var(--shadow);
    }

    .status-label {
        color: var(--muted);
        font-size: 0.8rem;
        margin-bottom: 0.35rem;
    }

    .status-value {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 600;
        word-break: break-word;
    }

    .summary-band {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1.05rem 1.1rem;
        box-shadow: var(--shadow);
        margin-bottom: 1rem;
    }

    .summary-band .label {
        color: var(--muted);
        font-size: 0.82rem;
        margin-bottom: 0.45rem;
    }

    .summary-band .text {
        color: var(--ink);
        font-size: 1.02rem;
        line-height: 1.7;
    }

    .detail-grid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 1rem;
        margin-bottom: 1rem;
    }

    .detail-box {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem 1.05rem;
        box-shadow: var(--shadow);
        height: 100%;
    }

    .detail-box h3 {
        margin: 0 0 0.7rem 0;
        color: var(--ink);
        font-size: 1rem;
        letter-spacing: 0;
    }

    .detail-list {
        margin: 0;
        padding-left: 1.1rem;
        color: var(--muted);
        line-height: 1.65;
        font-size: 0.94rem;
    }

    .detail-list li + li {
        margin-top: 0.45rem;
    }

    .panel-title {
        margin: 0 0 0.7rem 0;
        color: var(--ink);
        font-size: 1.02rem;
    }

    .caption-muted {
        color: var(--muted);
        font-size: 0.88rem;
        line-height: 1.55;
    }

    .workflow-stack {
        display: grid;
        gap: 0.9rem;
        margin-bottom: 1rem;
    }

    .workflow-step {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 1rem 1.05rem;
        box-shadow: var(--shadow);
    }

    .workflow-step-head {
        display: flex;
        align-items: center;
        gap: 0.8rem;
        margin-bottom: 0.6rem;
        flex-wrap: wrap;
    }

    .workflow-step-index {
        width: 1.9rem;
        height: 1.9rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 0.88rem;
        font-weight: 700;
        flex: 0 0 auto;
    }

    .workflow-step-title {
        color: var(--ink);
        font-size: 1rem;
        font-weight: 600;
        margin: 0;
        letter-spacing: 0;
    }

    .workflow-step-body {
        color: var(--muted);
        font-size: 0.94rem;
        line-height: 1.68;
    }

    .workflow-step-body p {
        margin: 0 0 0.75rem 0;
    }

    .workflow-step-body p:last-child {
        margin-bottom: 0;
    }

    .workflow-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 0.5rem;
        margin-top: 0.75rem;
    }

    .workflow-chip {
        display: inline-flex;
        align-items: center;
        min-height: 2rem;
        padding: 0.32rem 0.7rem;
        border-radius: 999px;
        background: var(--surface-subtle);
        border: 1px solid var(--border);
        color: var(--ink);
        font-size: 0.84rem;
        line-height: 1.35;
    }

    .workflow-chip-strong {
        background: var(--accent-soft);
        border-color: #cfe0f5;
        color: #274b73;
    }

    .workflow-list {
        margin: 0;
        padding-left: 1.1rem;
        color: var(--muted);
        line-height: 1.68;
        font-size: 0.94rem;
    }

    .workflow-list li + li {
        margin-top: 0.45rem;
    }

    .workflow-inline-note {
        margin-top: 0.7rem;
        padding: 0.78rem 0.85rem;
        border-radius: 8px;
        background: var(--surface-subtle);
        border: 1px solid var(--border);
        color: var(--muted);
        font-size: 0.89rem;
        line-height: 1.58;
    }

    div[data-testid="stExpander"] {
        border: 1px solid var(--border);
        border-radius: 8px;
        background: var(--surface);
        box-shadow: var(--shadow);
    }

    div[data-testid="stExpander"] details summary p {
        color: var(--ink);
        font-weight: 600;
    }

    @media (max-width: 960px) {
        .status-grid,
        .detail-grid {
            grid-template-columns: 1fr 1fr;
        }
    }

    @media (max-width: 720px) {
        .status-grid,
        .detail-grid {
            grid-template-columns: 1fr;
        }

        .hero h1 {
            font-size: 1.65rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_memory_overview(memory_store: NetworkMemory, records: list) -> dict[str, object]:
    overview_method = getattr(memory_store, "overview", None)
    if callable(overview_method):
        overview = overview_method()
        return {
            "total_records": overview.total_records,
            "repeated_records": overview.repeated_records,
            "high_value_records": overview.high_value_records,
            "latest_seen_at": overview.latest_seen_at,
            "top_issue_types": overview.top_issue_types,
        }

    issue_counts: dict[str, int] = {}
    repeated = 0
    high_value = 0
    latest_seen_at = None
    for record in records:
        issue_type = getattr(record, "issue_type", "general") or "general"
        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
        if getattr(record, "occurrences", 1) > 1:
            repeated += 1
        if getattr(record, "value_score", 0) >= 7:
            high_value += 1
        record_seen_at = getattr(record, "last_seen_at", None) or getattr(record, "created_at", None)
        if record_seen_at and (latest_seen_at is None or str(record_seen_at) > str(latest_seen_at)):
            latest_seen_at = record_seen_at

    top_issue_types = sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)[:3]
    return {
        "total_records": len(records),
        "repeated_records": repeated,
        "high_value_records": high_value,
        "latest_seen_at": latest_seen_at,
        "top_issue_types": top_issue_types,
    }


def severity_meta(severity: str | None) -> tuple[str, str]:
    mapping = {
        "high": ("高", "问题比较明确，建议优先处理当前链路或出口异常。"),
        "medium": ("中", "已经看到可疑点，但还建议结合场景再复测一次。"),
        "low": ("低", "这次快照没有看到明显异常，更像是偶发问题或场景问题。"),
    }
    return mapping.get((severity or "").lower(), ("未知", "当前证据不足，暂时只能给出保守判断。"))


def build_check_chips(
    snapshot,
    monitor_summary,
    react_observations,
    rag_hits,
    memory_records,
) -> list[str]:
    chips = ["本机网络信息"]
    if snapshot.pings:
        chips.append(f"Ping {len(snapshot.pings)} 项")
    if snapshot.dns:
        chips.append(f"DNS {len(snapshot.dns)} 项")
    if snapshot.traces:
        chips.append(f"路由追踪 {len(snapshot.traces)} 项")
    if monitor_summary:
        chips.append("短时监控")
    if rag_hits:
        chips.append(f"RAG 检索 {len(rag_hits)} 条")
    if memory_records:
        chips.append(f"历史记忆 {len(memory_records)} 条")
    if react_observations:
        chips.append(f"工具调用 {len(react_observations)} 步")
    return chips


def confidence_summary(
    diagnosis,
    monitor_summary,
    rag_hits,
    memory_records,
    react_observations,
) -> tuple[str, list[str]]:
    evidence_count = len(diagnosis.evidence) if diagnosis else 0
    completed_checks = len(react_observations)
    notes = [
        f"已形成 {evidence_count} 条直接证据",
        f"本次实际执行 {completed_checks} 步工具调用" if completed_checks else "本次使用基础探测流程生成结果",
    ]
    score = 1 if diagnosis else 0
    if evidence_count >= 4:
        score += 1
    if monitor_summary:
        score += 1
        notes.append("包含短时监控，能看到是否存在抖动或间歇性丢包")
    else:
        notes.append("没有短时监控，偶发抖动类问题可能还没被捕捉到")
    if rag_hits:
        score += 1
        notes.append("结论参考了本地知识库，不只是模型自由发挥")
    if memory_records:
        score += 1
        notes.append("召回了历史案例，可判断是不是反复出现的问题")

    if score >= 4:
        return "较高", notes
    if score >= 2:
        return "中等", notes
    return "基础", notes


def build_visible_evidence(snapshot, diagnosis, monitor_summary) -> list[str]:
    if diagnosis and diagnosis.evidence:
        return [item for item in diagnosis.evidence if item][:6]

    fallback: list[str] = []
    if snapshot.gateway:
        fallback.append(f"当前默认网关是 {snapshot.gateway}。")

    for name, item in list(snapshot.pings.items())[:3]:
        fallback.append(
            f"Ping {name}（{item.target}）：{'成功' if item.success else '失败'}，平均延迟 {item.avg_ms} ms，丢包 {item.packet_loss_percent}% 。"
        )

    for name, item in list(snapshot.dns.items())[:3]:
        fallback.append(
            f"DNS 解析 {name}：{'成功' if item.success else '失败'}，耗时 {item.elapsed_ms} ms。"
        )

    if monitor_summary and monitor_summary.conclusion:
        fallback.append(monitor_summary.conclusion)

    if diagnosis and diagnosis.summary:
        fallback.append(f"规则诊断结论是：{diagnosis.summary}")

    if not fallback:
        fallback.append("这次没有拿到足够的结构化证据，建议重新诊断一次。")

    return fallback[:6]


def render_workflow_step(index: int, title: str, body: str, items: list[str] | None = None, chips: list[str] | None = None, note: str | None = None) -> str:
    body_html = f"<p>{escape(body)}</p>" if body else ""
    items_html = ""
    if items:
        item_list = "".join(f"<li>{escape(item)}</li>" for item in items if item)
        if item_list:
            items_html = f'<ul class="workflow-list">{item_list}</ul>'
    chips_html = ""
    if chips:
        chip_list = "".join(
            f'<span class="workflow-chip{" workflow-chip-strong" if idx == 0 else ""}">{escape(chip)}</span>'
            for idx, chip in enumerate(chips)
            if chip
        )
        if chip_list:
            chips_html = f'<div class="workflow-chip-row">{chip_list}</div>'
    note_html = f'<div class="workflow-inline-note">{escape(note)}</div>' if note else ""
    parts = [
        '<div class="workflow-step">',
        '<div class="workflow-step-head">',
        f'<div class="workflow-step-index">{index}</div>',
        f'<h3 class="workflow-step-title">{escape(title)}</h3>',
        "</div>",
        '<div class="workflow-step-body">',
        body_html,
        items_html,
        chips_html,
        note_html,
        "</div>",
        "</div>",
    ]
    return "".join(part for part in parts if part)


memory_store = NetworkMemory()
persisted_memory_records = memory_store.load(limit=12)
memory_overview = get_memory_overview(memory_store, persisted_memory_records)

st.markdown(
    """
    <div class="hero">
      <div class="hero-copy">
        <div class="eyebrow">本机网络诊断</div>
        <h1>NetDiag Agent</h1>
        <p>帮你判断网络问题更像出在哪一段，并告诉你下一步自己可以先做什么。默认先给结论和建议，需要时再展开 Agent 过程、工具轨迹、RAG 和记忆细节。</p>
      </div>
    """,
    unsafe_allow_html=True,
)

if persisted_memory_records:
    issue_text = "、".join(name for name, _ in memory_overview["top_issue_types"]) or "暂无分类"
    st.markdown(
        f"""
        <div class="memory-banner">
          本地记忆库已启用：累计 {memory_overview['total_records']} 条案例，
          其中重复问题 {memory_overview['repeated_records']} 条，高价值案例 {memory_overview['high_value_records']} 条。
          常见类型：{issue_text}
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.markdown("</div>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-panel">
          <div class="sidebar-panel-title">诊断控制台</div>
          <div class="sidebar-panel-copy">先描述你遇到的现象，再选择诊断模式。默认会优先给结论和下一步建议，需要时再展开底层细节。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-section-label">现象输入</div>', unsafe_allow_html=True)
    user_context = st.text_area(
        "你的网络现象",
        placeholder="例如：晚上打游戏卡，但刷网页还行；或者只有某个网站很慢",
        height=130,
    )
    custom_target = st.text_input(
        "自定义目标（可选）",
        placeholder="例如：www.qq.com 或 1.1.1.1",
    )
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">诊断模式</div>', unsafe_allow_html=True)
    mode_label = st.selectbox(
        "诊断模式",
        ["自动选择", "快速诊断", "游戏卡顿", "网页访问", "单站点慢", "深度路由"],
        index=0,
    )
    mode_map = {
        "自动选择": "auto",
        "快速诊断": "quick",
        "游戏卡顿": "gaming",
        "网页访问": "web",
        "单站点慢": "single_site",
        "深度路由": "deep",
    }
    st.caption("自动模式会根据你的描述优先决定从网页、游戏、单站点还是通用问题入手。")
    st.markdown('<div class="sidebar-divider"></div>', unsafe_allow_html=True)
    st.markdown('<div class="sidebar-section-label">运行选项</div>', unsafe_allow_html=True)
    run_monitor_enabled = st.toggle("短时持续监控", value=False)
    show_debug = st.toggle("显示开发者细节", value=False)
    with st.expander("高级设置", expanded=False):
        use_llm_planner = st.toggle("DeepSeek 自主决策工具", value=True)
        use_graph = st.toggle("启用 ReAct 工具循环", value=True)
        use_llm = st.toggle("DeepSeek Agent 报告", value=True)
        samples = st.slider("监控采样次数", min_value=3, max_value=12, value=5)
        interval = st.slider("采样间隔（秒）", min_value=2, max_value=20, value=5)
        save = st.toggle("保存本地报告", value=True)
    st.caption("需要更完整的证据时，再打开短时监控和开发者细节。")
    run = st.button("开始诊断", type="primary", width="stretch")

rule_plan = plan_from_context(user_context, mode_map[mode_label])
plan = st.session_state.get("preview_plan", rule_plan) if use_llm_planner else rule_plan

panel_col, status_col = st.columns([1.15, 1])
with panel_col:
    st.markdown(
        """
        <div class="section-card">
          <div class="card-title">你先描述现象，Agent 再决定怎么查</div>
          <div class="card-copy">它会先看本机网络信息，再按需要调用 DNS、Ping、短时监控、RAG 和记忆召回，不会默认把所有技术细节直接堆给你。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
with status_col:
    st.markdown(
        """
        <div class="section-card">
          <div class="card-title">结果会分成三层</div>
          <div class="card-copy">先给一句结论，再给发生了什么和下一步建议，最后才展开原始探测数据和 Agent 过程。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

if run:
    progress = st.progress(0)
    status = st.empty()

    if use_graph:
        status.write("正在分析当前网络情况，并逐步选择合适的检测工具...")
        state = run_netdiag_graph(
            user_context=user_context,
            requested_mode=mode_map[mode_label],
            use_llm_planner=use_llm_planner,
            use_llm_report=use_llm,
            run_monitor_enabled=run_monitor_enabled,
            custom_target=custom_target,
            samples=samples,
            interval_seconds=interval,
            max_steps=8,
        )
        active_plan = state["plan"]
        snapshot = state["snapshot"]
        monitor_summary = state.get("monitor_summary")
        tool_plan_result = None
        llm_report = state.get("llm_report")
        agent_trace = state.get("agent_trace")
        st.session_state.rag_hits = state.get("rag_hits", [])
        st.session_state.memory_records = state.get("memory_records", [])
        st.session_state.graph_steps = state.get("graph_steps", [])
        st.session_state.react_observations = state.get("react_observations", [])
        st.session_state.react_decisions = state.get("react_decisions", [])
        progress.progress(95)
    else:
        active_plan = rule_plan
        tool_plan_result = None
        status.write("正在执行基础网络检测...")
        snapshot = collect_snapshot(targets=active_plan.targets, include_trace=active_plan.include_trace)
        diagnose(snapshot)
        monitor_summary = (
            run_monitor(active_plan.targets, samples=samples, interval_seconds=interval)
            if run_monitor_enabled or active_plan.monitor_recommended
            else None
        )
        llm_report = None
        agent_trace = build_agent_trace(user_context, active_plan, snapshot, monitor_summary)
        st.session_state.rag_hits = []
        st.session_state.memory_records = []
        st.session_state.graph_steps = ["compat.probe", "compat.diagnose"]
        st.session_state.react_observations = []
        st.session_state.react_decisions = []
        progress.progress(95)

    if save:
        save_report(snapshot)

    st.session_state.snapshot = snapshot
    st.session_state.last_user_context = user_context
    st.session_state.last_custom_target = custom_target
    st.session_state.last_mode_label = mode_label
    st.session_state.plan = active_plan
    st.session_state.tool_plan_result = tool_plan_result
    st.session_state.agent_trace = agent_trace
    st.session_state.monitor_summary = monitor_summary
    st.session_state.llm_report = llm_report
    progress.progress(100)
    status.write("诊断完成。")
    persisted_memory_records = memory_store.load(limit=12)
    memory_overview = get_memory_overview(memory_store, persisted_memory_records)

snapshot = st.session_state.get("snapshot")
if snapshot:
    diagnosis = snapshot.diagnosis
    monitor_summary = st.session_state.get("monitor_summary")
    llm_report = st.session_state.get("llm_report")
    tool_plan_result = st.session_state.get("tool_plan_result")
    rag_hits = st.session_state.get("rag_hits", [])
    memory_records = st.session_state.get("memory_records", [])
    graph_steps = st.session_state.get("graph_steps", [])
    react_observations = st.session_state.get("react_observations", [])
    active_plan = st.session_state.get("plan") or plan
    last_user_context = st.session_state.get("last_user_context", user_context)
    last_custom_target = st.session_state.get("last_custom_target", custom_target)
    agent_trace = st.session_state.get("agent_trace") or build_agent_trace(
        last_user_context, active_plan, snapshot, monitor_summary
    )

    gateway_text = snapshot.gateway or "未识别"
    dns_text = ", ".join(snapshot.dns_servers[:2]) if snapshot.dns_servers else "未识别"
    severity_text, _ = severity_meta(diagnosis.severity if diagnosis else None)
    target_text = str(len(snapshot.pings))

    st.markdown(
        f"""
        <div class="status-grid">
          <div class="status-tile">
            <div class="status-label">默认网关</div>
            <div class="status-value">{gateway_text}</div>
          </div>
          <div class="status-tile">
            <div class="status-label">DNS</div>
            <div class="status-value">{dns_text}</div>
          </div>
          <div class="status-tile">
            <div class="status-label">风险等级</div>
            <div class="status-value">{severity_text}</div>
          </div>
          <div class="status-tile">
            <div class="status-label">探测目标数</div>
            <div class="status-value">{target_text}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if last_custom_target:
        st.caption(f"本次额外目标：{last_custom_target}")

    st.markdown(
        f"""
        <div class="summary-band">
          <div class="label">当前结论</div>
          <div class="text">{diagnosis.summary if diagnosis else '尚未生成诊断结论。'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    visible_evidence = build_visible_evidence(snapshot, diagnosis, monitor_summary)
    evidence_html = "".join(f"<li>{escape(item)}</li>" for item in visible_evidence)
    suggestion_html = "".join(f"<li>{escape(item)}</li>" for item in (diagnosis.suggestions[:6] if diagnosis else []))
    st.markdown(
        f"""
        <div class="detail-grid">
          <div class="detail-box">
            <h3>发生了什么</h3>
            <ul class="detail-list">{evidence_html}</ul>
          </div>
          <div class="detail-box">
            <h3>你现在可以怎么做</h3>
            <ul class="detail-list">{suggestion_html}</ul>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if llm_report:
        with st.expander("模型补充说明", expanded=False):
            if llm_report.success:
                st.markdown(llm_report.content)
            else:
                st.warning(f"DeepSeek 报告生成失败，已保留规则诊断结果：{llm_report.error}")

    st.markdown('<div class="panel-title">原始探测数据</div>', unsafe_allow_html=True)

    ping_df = pd.DataFrame(
        [
            {
                "名称": name,
                "目标": item.target,
                "成功": item.success,
                "平均延迟(ms)": item.avg_ms,
                "丢包率(%)": item.packet_loss_percent,
            }
            for name, item in snapshot.pings.items()
        ]
    )
    st.dataframe(ping_df, width="stretch", hide_index=True)

    dns_df = pd.DataFrame(
        [
            {
                "名称": name,
                "域名": item.host,
                "成功": item.success,
                "耗时(ms)": item.elapsed_ms,
                "解析地址": ", ".join(item.addresses[:4]),
            }
            for name, item in snapshot.dns.items()
        ]
    )
    if not dns_df.empty:
        st.markdown('<div class="panel-title" style="margin-top: 1rem;">DNS 结果</div>', unsafe_allow_html=True)
        st.dataframe(dns_df, width="stretch", hide_index=True)

        dns_compare_df = dns_df[dns_df["名称"].str.contains(":")]
        if not dns_compare_df.empty:
            st.markdown('<div class="panel-title" style="margin-top: 1rem;">DNS 对比</div>', unsafe_allow_html=True)
            compare_summary = summarize_dns_comparison(snapshot)
            if compare_summary:
                st.caption(compare_summary)
            st.dataframe(dns_compare_df, width="stretch", hide_index=True)

    if monitor_summary:
        st.markdown('<div class="panel-title" style="margin-top: 1rem;">短时监控</div>', unsafe_allow_html=True)
        st.caption(monitor_summary.conclusion)
        monitor_df = pd.DataFrame(monitor_to_rows(monitor_summary))
        if not monitor_df.empty and {"time", "avg_ms", "target_name"}.issubset(monitor_df.columns):
            st.line_chart(monitor_df, x="time", y="avg_ms", color="target_name")
            st.dataframe(monitor_df, width="stretch", hide_index=True)
        else:
            st.info("这次短时监控没有采集到可用于绘图的有效数据。")

    with st.expander("本地记忆库", expanded=False):
        overview_col1, overview_col2, overview_col3 = st.columns(3)
        overview_col1.metric("累计案例", memory_overview["total_records"])
        overview_col2.metric("重复问题", memory_overview["repeated_records"])
        overview_col3.metric("高价值案例", memory_overview["high_value_records"])
        if memory_overview["latest_seen_at"]:
            st.caption(f"最近一次写入：{memory_overview['latest_seen_at']}")
        if memory_overview["top_issue_types"]:
            st.caption(
                "常见问题类型："
                + "；".join(f"{name} {count} 条" for name, count in memory_overview["top_issue_types"])
            )
        if persisted_memory_records:
            st.dataframe(
                pd.DataFrame(memory_records_to_rows(persisted_memory_records)),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("还没有写入历史记忆。完成几次诊断后，这里会开始积累可召回的案例。")

    with st.expander("Markdown 报告", expanded=False):
        st.code(render_markdown(snapshot), language="markdown")

    if show_debug:
        with st.expander("开发者细节", expanded=False):
            st.subheader("Agent Trace")
            st.dataframe(pd.DataFrame(trace_to_rows(agent_trace)), width="stretch", hide_index=True)

            if react_observations:
                st.subheader("ReAct 工具调用轨迹")
                st.caption("大模型每一步只选择一个工具，工具结果会回到下一轮决策。")
                st.dataframe(
                    pd.DataFrame(observation_rows(react_observations)),
                    width="stretch",
                    hide_index=True,
                )

            if graph_steps:
                st.subheader("底层编排节点")
                st.caption("这里展示的是 LangGraph 在代码里的状态节点，主要用于开发和面试讲解。")
                st.dataframe(
                    pd.DataFrame({"顺序": range(1, len(graph_steps) + 1), "节点": graph_steps}),
                    width="stretch",
                    hide_index=True,
                )

            if rag_hits:
                st.subheader("RAG 检索依据")
                st.dataframe(pd.DataFrame(rag_hits_to_rows(rag_hits)), width="stretch", hide_index=True)

            if memory_records:
                st.subheader("本次召回的长期记忆")
                st.dataframe(
                    pd.DataFrame(memory_records_to_rows(memory_records)),
                    width="stretch",
                    hide_index=True,
                )

            if tool_plan_result:
                st.subheader("DeepSeek 工具规划器输出")
                if tool_plan_result.success:
                    st.code(tool_plan_result.raw, language="json")
                else:
                    st.warning(f"DeepSeek 工具规划失败，已回退规则规划：{tool_plan_result.error}")
else:
    st.markdown(
        """
        <div class="summary-band">
          <div class="label">开始之前</div>
          <div class="text">先描述你遇到的网络现象，再启动诊断。结果页会先给一句结论，再告诉你发生了什么和下一步怎么做。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("本地记忆库", expanded=False):
        overview_col1, overview_col2, overview_col3 = st.columns(3)
        overview_col1.metric("累计案例", memory_overview["total_records"])
        overview_col2.metric("重复问题", memory_overview["repeated_records"])
        overview_col3.metric("高价值案例", memory_overview["high_value_records"])
        if memory_overview["latest_seen_at"]:
            st.caption(f"最近一次写入：{memory_overview['latest_seen_at']}")
        if memory_overview["top_issue_types"]:
            st.caption(
                "常见问题类型："
                + "；".join(f"{name} {count} 条" for name, count in memory_overview["top_issue_types"])
            )
        if persisted_memory_records:
            st.dataframe(
                pd.DataFrame(memory_records_to_rows(persisted_memory_records)),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("还没有写入历史记忆。完成几次诊断后，这里会开始积累可召回的案例。")
