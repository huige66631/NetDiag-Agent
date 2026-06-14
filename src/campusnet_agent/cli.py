from __future__ import annotations

import argparse

from campusnet_agent.diagnosis import diagnose
from campusnet_agent.llm import generate_deepseek_report
from campusnet_agent.probe import collect_snapshot
from campusnet_agent.report import render_markdown, save_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus network diagnosis assistant")
    subparsers = parser.add_subparsers(dest="command")

    diagnose_cmd = subparsers.add_parser("diagnose", help="Run one network diagnosis")
    diagnose_cmd.add_argument("--no-trace", action="store_true", help="Skip traceroute to make the run faster")
    diagnose_cmd.add_argument("--save", action="store_true", help="Save markdown and JSON reports")
    diagnose_cmd.add_argument("--llm", action="store_true", help="Generate an LLM report with DeepSeek")
    diagnose_cmd.add_argument("--context", default="", help="User symptom description, such as evening gaming lag")

    args = parser.parse_args()
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
