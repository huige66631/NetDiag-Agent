from __future__ import annotations

import pandas as pd
import streamlit as st

from campusnet_agent.agent import build_agent_trace, trace_to_rows
from campusnet_agent.diagnosis import diagnose
from campusnet_agent.llm import generate_deepseek_report
from campusnet_agent.monitor import monitor_to_rows, run_monitor
from campusnet_agent.planner import plan_from_context
from campusnet_agent.probe import collect_snapshot
from campusnet_agent.report import render_markdown, save_report


st.set_page_config(page_title="CampusNet Agent", page_icon="🌐", layout="wide")

st.markdown(
    """
    <style>
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }
    [data-testid="stToolbar"] { display: none; }
    [data-testid="stDecoration"] { display: none; }
    [data-testid="stStatusWidget"] { display: none; }
    .block-container { padding-top: 1.6rem; max-width: 1180px; }
    .hero {
        padding: 1.2rem 1.4rem;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background: #ffffff;
        margin-bottom: 1rem;
    }
    .hero h1 { margin: 0 0 .25rem 0; font-size: 1.9rem; letter-spacing: 0; }
    .hero p { margin: 0; color: #5b6472; }
    .status-box {
        padding: .85rem 1rem;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        background: #fbfcfd;
        min-height: 110px;
    }
    .small-muted { color: #6b7280; font-size: .92rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>CampusNet Agent</h1>
      <p>面向宿舍和校园网场景的本地诊断 Agent：自动选择工具，采集真实网络数据，并用 DeepSeek 生成可解释报告。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("诊断任务")
    user_context = st.text_area(
        "你的网络现象",
        placeholder="例如：宿舍晚上打游戏卡，但刷网页还行",
        height=110,
    )
    mode_label = st.selectbox(
        "Agent 模式",
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
    use_llm = st.toggle("DeepSeek Agent 报告", value=True)
    run_monitor_enabled = st.toggle("短时持续监控", value=False)
    samples = st.slider("监控采样次数", min_value=3, max_value=12, value=5)
    interval = st.slider("采样间隔（秒）", min_value=2, max_value=20, value=5)
    save = st.toggle("保存本地报告", value=True)
    run = st.button("开始诊断", type="primary", use_container_width=True)

plan = plan_from_context(user_context, mode_map[mode_label])

plan_col, action_col = st.columns([1.1, 1])
with plan_col:
    st.subheader("Agent 计划")
    st.markdown(f"**{plan.title}**")
    for item in plan.rationale:
        st.write(f"- {item}")
    st.caption(
        f"目标：{', '.join(plan.targets.values())} | "
        f"路由追踪：{'开启' if plan.include_trace else '关闭'} | "
        f"建议监控：{'是' if plan.monitor_recommended else '否'}"
    )
    with st.expander("查看 Agent Trace 预案", expanded=False):
        st.dataframe(pd.DataFrame(trace_to_rows(build_agent_trace(user_context, plan))), hide_index=True)
with action_col:
    st.subheader("运行状态")
    st.markdown(
        """
        <div class="status-box">
          <div>1. 识别当前网关和 DNS</div>
          <div>2. 执行 Ping / DNS / 可选 tracert</div>
          <div>3. 根据规则定位问题</div>
          <div>4. DeepSeek 生成解释报告</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

if run:
    progress = st.progress(0)
    status = st.empty()

    status.write("正在执行网络探测...")
    snapshot = collect_snapshot(targets=plan.targets, include_trace=plan.include_trace)
    progress.progress(35)

    status.write("正在生成规则诊断...")
    diagnose(snapshot)
    progress.progress(55)

    monitor_summary = None
    if run_monitor_enabled or plan.monitor_recommended:
        status.write("正在执行短时持续监控...")
        monitor_summary = run_monitor(plan.targets, samples=samples, interval_seconds=interval)
    progress.progress(75)

    llm_report = None
    if use_llm:
        status.write("正在调用 DeepSeek 生成 Agent 报告...")
        llm_report = generate_deepseek_report(
            snapshot,
            user_context=user_context,
            plan=plan,
            monitor_summary=monitor_summary,
        )
    progress.progress(95)

    if save:
        save_report(snapshot)

    st.session_state.snapshot = snapshot
    st.session_state.plan = plan
    st.session_state.agent_trace = build_agent_trace(user_context, plan, snapshot, monitor_summary)
    st.session_state.monitor_summary = monitor_summary
    st.session_state.llm_report = llm_report
    progress.progress(100)
    status.write("诊断完成。")

snapshot = st.session_state.get("snapshot")
if snapshot:
    diagnosis = snapshot.diagnosis
    monitor_summary = st.session_state.get("monitor_summary")
    llm_report = st.session_state.get("llm_report")
    active_plan = st.session_state.get("plan") or plan
    agent_trace = st.session_state.get("agent_trace") or build_agent_trace(
        "", active_plan, snapshot, monitor_summary
    )

    st.divider()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("默认网关", snapshot.gateway or "未识别")
    col2.metric("DNS", ", ".join(snapshot.dns_servers[:2]) if snapshot.dns_servers else "未识别")
    col3.metric("风险等级", diagnosis.severity if diagnosis else "unknown")
    col4.metric("探测目标", len(snapshot.pings))

    st.subheader("诊断结论")
    st.info(diagnosis.summary if diagnosis else "尚未生成诊断结论。")

    st.subheader("Agent Trace")
    st.caption("展示 Agent 如何理解问题、选择工具、观察结果并决定下一步。")
    st.dataframe(pd.DataFrame(trace_to_rows(agent_trace)), use_container_width=True, hide_index=True)

    if llm_report:
        st.subheader("DeepSeek Agent 报告")
        if llm_report.success:
            st.markdown(llm_report.content)
        else:
            st.warning(f"DeepSeek 报告生成失败，已保留规则诊断结果：{llm_report.error}")

    evidence_col, suggestion_col = st.columns(2)
    with evidence_col:
        st.subheader("证据")
        for item in diagnosis.evidence:
            st.write(f"- {item}")
    with suggestion_col:
        st.subheader("建议")
        for item in diagnosis.suggestions:
            st.write(f"- {item}")

    st.subheader("Ping 结果")
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
    st.dataframe(ping_df, use_container_width=True, hide_index=True)

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
        st.subheader("DNS 结果")
        st.dataframe(dns_df, use_container_width=True, hide_index=True)

    if monitor_summary:
        st.subheader("短时监控")
        st.caption(monitor_summary.conclusion)
        monitor_df = pd.DataFrame(monitor_to_rows(monitor_summary))
        st.line_chart(monitor_df, x="time", y="avg_ms", color="target_name")
        st.dataframe(monitor_df, use_container_width=True, hide_index=True)

    with st.expander("Markdown 报告"):
        st.code(render_markdown(snapshot), language="markdown")
