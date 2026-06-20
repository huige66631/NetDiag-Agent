# NetDiag Agent

NetDiag Agent is a local network diagnosis agent for everyday network problems such as slow
web access, DNS failures, Wi-Fi packet loss, gaming latency, and intermittent jitter. It runs
network probes on the user's own computer, uses LangGraph to orchestrate the workflow, retrieves
troubleshooting knowledge from a local Chroma vector database, remembers historical diagnosis
cases, and can call DeepSeek to generate an evidence-based Chinese report.

## Why Local

Network diagnosis must happen on the user's current device and current network. If the whole
app is deployed to a cloud server, it will diagnose the cloud server's network instead of the
user's Wi-Fi, router, DNS, gateway, or ISP path. NetDiag Agent therefore runs locally and uses
the LLM only for planning and explanation.

## Core Features

- ReAct-style LangGraph loop: the LLM decides one tool, Python executes it, the observation
  returns to the LLM, and the loop continues until evidence is sufficient
- DeepSeek tool decision layer with a local heuristic fallback
- Local tools: `ipconfig`, `ipconfig /all`, `ping`, `nslookup`, optional `tracert`, and short
  monitoring
- RAG knowledge base backed by local ChromaDB and project-owned troubleshooting documents
- Long-term memory stored locally as historical diagnosis cases
- Rule-based diagnosis for access-link issues, DNS problems, network exit congestion, target
  site/CDN issues, and normal snapshots
- Streamlit UI showing Agent Trace, LangGraph nodes, RAG retrieval hits, memory recall, raw
  evidence, charts, and final report
- DeepSeek report generation based only on collected evidence, retrieved knowledge, and memory

## Architecture

```text
User symptom
    |
    v
LangGraph ReAct loop
    |
    |-- react.init
    |-- llm.decide
    |      |-- choose exactly one tool
    |      |-- no arbitrary shell command execution
    |-- tool.execute
    |      |-- get_network_profile / ping_target / dns_lookup
    |      |-- traceroute / short_monitor / rag_search / recall_memory
    |-- observation returned to LLM
    |-- loop until final_answer
    |-- react.synthesize
    |      |-- rule diagnosis
    |      |-- RAG context
    |      |-- memory context
    |      |-- DeepSeek final explanation
    |-- memory.write
    v
Evidence-based diagnosis report
```

## Quick Start

```powershell
git clone <your-repo-url>
cd NetDiag-Agent
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
DEEPSEEK_API_KEY=<your-deepseek-api-key>
DEEPSEEK_MODEL=deepseek-v4-flash
```

Build the local RAG vector database:

```powershell
netdiag-agent build-rag
```

Run the web UI:

```powershell
streamlit run app.py
```

Open:

```text
http://localhost:8501
```

Run the ReAct LangGraph agent from CLI:

```powershell
netdiag-agent agent --context "晚上打游戏跳 Ping，但刷网页还行" --mode auto
```

Run a faster rule-only diagnosis:

```powershell
netdiag-agent diagnose --no-trace --context "网页偶尔打不开"
```

## Project Structure

```text
NetDiag-Agent
|-- app.py                         # Streamlit UI
|-- docs/knowledge                 # RAG troubleshooting knowledge base
|-- src/netdiag_agent
|   |-- graph.py                   # LangGraph workflow
|   |-- rag.py                     # Chroma vector database and retrieval
|   |-- memory.py                  # Long-term local diagnosis memory
|   |-- planner.py                 # Rule-based fallback planner
|   |-- agent.py                   # Agent trace display
|   |-- probe.py                   # Local network probing tools
|   |-- diagnosis.py               # Rule-based diagnosis
|   |-- monitor.py                 # Short monitoring and jitter summary
|   |-- llm.py                     # DeepSeek planner and report generation
|   |-- report.py                  # Markdown / JSON report export
|   `-- models.py                  # Data models
`-- tests
```

## Example Use Cases

- "晚上打游戏跳 Ping，但刷网页还行"
- "Wi-Fi 能连上，但网页经常打不开"
- "只有 B 站加载慢，其他网站正常"
- "我想给网络管理员或运营商提交一份有证据的反馈报告"

## Security

Do not commit API keys. This repository ignores `.env.local`, generated reports, logs, caches,
local Chroma data, memory files, and virtual environments. Use `.env.example` as the template.

The LLM never executes arbitrary shell commands. In the ReAct loop it can only choose one tool
from an allowlist, and Python executes fixed local network functions with validated arguments.

## Limitations

- The agent cannot directly change router, ISP, or network infrastructure.
- A one-time snapshot may miss intermittent evening congestion.
- Gaming diagnosis is more accurate when the user runs monitoring during the actual lag period
  or provides the target game server address.
