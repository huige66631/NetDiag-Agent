from __future__ import annotations

import argparse

from netdiag_agent.diagnosis import diagnose
from netdiag_agent.graph import run_netdiag_graph
from netdiag_agent.llm import generate_deepseek_report
from netdiag_agent.probe import collect_snapshot
from netdiag_agent.rag import build_knowledge_base
from netdiag_agent.react import observation_rows
from netdiag_agent.report import render_markdown, save_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Local network diagnosis assistant")
    subparsers = parser.add_subparsers(dest="command")

    diagnose_cmd = subparsers.add_parser("diagnose", help="Run one network diagnosis")
    diagnose_cmd.add_argument("--no-trace", action="store_true", help="Skip traceroute to make the run faster")
    diagnose_cmd.add_argument("--save", action="store_true", help="Save markdown and JSON reports")
    diagnose_cmd.add_argument("--llm", action="store_true", help="Generate an LLM report with DeepSeek")
    diagnose_cmd.add_argument("--context", default="", help="User symptom description, such as evening gaming lag")

    subparsers.add_parser("build-rag", help="Build or refresh the local Chroma knowledge base")

    graph_cmd = subparsers.add_parser("agent", help="Run the LangGraph agent workflow")
    graph_cmd.add_argument("--context", default="", help="User symptom description")
    graph_cmd.add_argument("--mode", default="auto", help="auto, quick, gaming, web, single_site, deep")
    graph_cmd.add_argument("--no-llm-planner", action="store_true", help="Use rule planner instead of LLM planner")
    graph_cmd.add_argument("--no-llm-report", action="store_true", help="Skip DeepSeek report generation")
    graph_cmd.add_argument("--monitor", action="store_true", help="Force short monitoring")
    graph_cmd.add_argument("--target", default="", help="Custom target domain or IP, such as example.com or 1.1.1.1")

    args = parser.parse_args()
    if args.command == "build-rag":
        count = build_knowledge_base(force=True)
        print(f"Built local RAG knowledge base with {count} chunks.")
        return

    if args.command == "agent":
        state = run_netdiag_graph(
            user_context=args.context,
            requested_mode=args.mode,
            use_llm_planner=not args.no_llm_planner,
            use_llm_report=not args.no_llm_report,
            run_monitor_enabled=args.monitor,
            custom_target=args.target,
        )
        print(render_markdown(state["snapshot"]))
        if state.get("llm_report") and state["llm_report"].success:
            print("\n# DeepSeek Agent Report\n")
            print(state["llm_report"].content)
        print("\n# ReAct Tool Calls\n")
        for row in observation_rows(state.get("react_observations", [])):
            print(f"- step {row['步骤']}: {row['模型判断']} -> {row['调用工具']} {row['参数']} => {row['观察结果']}")
        print("\n# LangGraph Steps\n")
        print("\n".join(f"- {step}" for step in state.get("graph_steps", [])))
        return

    if args.command in {None, "diagnose"}:
        snapshot = collect_snapshot(include_trace=not getattr(args, "no_trace", False))
        diagnose(snapshot)
        print(render_markdown(snapshot))
        if getattr(args, "llm", False):
            llm_report = generate_deepseek_report(snapshot, user_context=getattr(args, "context", ""))
            print("\n# DeepSeek Agent Report\n")
            if llm_report.success:
                print(llm_report.content)
            else:
                print(f"LLM report failed: {llm_report.error}")
        if getattr(args, "save", False):
            md_path, json_path = save_report(snapshot)
            print(f"\nSaved report: {md_path}")
            print(f"Saved snapshot: {json_path}")


if __name__ == "__main__":
    main()

