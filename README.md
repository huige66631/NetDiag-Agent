# NetDiag Agent

NetDiag Agent is a local AI agent for diagnosing everyday network problems. It collects real
network evidence from the current computer, chooses a diagnosis workflow based on the user's
symptom, and uses DeepSeek to generate a readable troubleshooting report.

The project works for dorm Wi-Fi, home networks, office networks, gaming latency, slow DNS
resolution, single-site slowness, and evening congestion.

## Why Local

Network diagnosis must run on the user's own device and current network. If the app is moved
entirely to a cloud server, it will diagnose the cloud server's network instead of the user's
Wi-Fi, router, DNS, or ISP path. This project therefore runs locally and uses the LLM only for
analysis and report generation.

## Features

- Symptom-aware agent planning for gaming lag, web access issues, single-site slowness,
  and deeper route diagnosis
- DeepSeek tool planner that selects a safe network probe plan before execution
- Agent Trace view that shows task understanding, tool selection, observations, and next
  decisions
- Local network probing with `ping`, `ipconfig`, `nslookup`, and optional `tracert`
- Structured metrics: gateway, DNS servers, average latency, packet loss, DNS resolution time
- Rule-based diagnosis for access-link issues, DNS issues, network出口 congestion, and
  target-side/CDN problems
- Short monitoring mode to capture intermittent packet loss and jitter
- DeepSeek-powered Agent report with evidence, suggestions, and a network admin / ISP support
  feedback draft
- Streamlit web UI for local demonstration

## Architecture

```text
User symptom
    |
    v
Agent planner
    |-- optional DeepSeek tool planner
    |-- safe allowlisted tools only
    |-- gaming lag
    |-- web access issue
    |-- single-site slowness
    |-- deep route diagnosis
    v
Network tools
    |-- gateway / DNS discovery
    |-- ping
    |-- nslookup
    |-- optional tracert
    |-- optional short monitoring
    v
Rule diagnosis
    v
DeepSeek report generation
    v
User-facing and network-admin-facing report
```

## Quick Start

```powershell
git clone <your-repo-url>
cd netdiag-agent
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .[dev]
```

Create a local environment file:

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Set your DeepSeek API key in `.env.local`:

```text
DEEPSEEK_API_KEY=sk-your-key
DEEPSEEK_MODEL=deepseek-v4-flash
```

Run the web UI:

```powershell
streamlit run app.py
```

Open:

```text
http://localhost:8501
```

Run the CLI:

```powershell
netdiag-agent diagnose --no-trace --llm --context "晚上打游戏卡，但刷网页还行"
```

## Project Structure

```text
netdiag-agent
├── app.py                         # Streamlit UI
├── src/netdiag_agent
│   ├── planner.py                 # Symptom-aware agent plan
│   ├── agent.py                   # Agent trace and decision display
│   ├── probe.py                   # Local network probing tools
│   ├── diagnosis.py               # Rule-based diagnosis
│   ├── monitor.py                 # Short monitoring and jitter summary
│   ├── llm.py                     # DeepSeek report generation
│   ├── report.py                  # Markdown / JSON report export
│   └── models.py                  # Data models
└── tests
    └── test_diagnosis.py
```

## Example Use Cases

- "晚上打游戏卡，但网页还行"
- "Wi-Fi 能连上，但网页经常打不开"
- "只有 B 站加载慢，其他网站正常"
- "想给网络管理员或运营商提交一份有证据的反馈报告"

## Security

Do not commit API keys. This repository ignores `.env.local`, generated reports, logs, caches,
and virtual environments. Use `.env.example` as the template and keep real keys local.

The LLM does not execute arbitrary shell commands. It can only select from an allowlisted plan
of local network probes, and the Python application executes those probes with fixed arguments.

## Limitations

- The tool cannot directly change router, ISP, or network infrastructure.
- One-time snapshots may miss intermittent evening congestion.
- Gaming diagnosis is more accurate when the user provides the target game server IP or runs
  short monitoring during the actual lag period.

## Reference Projects

This project studied the design ideas of several open-source NetOps tools, but implements its
own local-network-focused workflow:

- `network-mcp`: structured network tool output for AI agents
- `Instability`: interactive network troubleshooting chatbot workflow
- `AI-Network-Troubleshooting-PoC`: alert-to-analysis-to-report NetOps flow

