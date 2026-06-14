from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from campusnet_agent.models import NetworkSnapshot


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass
class LlmReport:
    success: bool
    content: str
    model: str
    error: str | None = None


def load_local_env() -> None:
    env_path = Path.cwd() / ".env.local"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def build_report_prompt(snapshot: NetworkSnapshot, user_context: str = "") -> list[dict[str, str]]:
    system = (
        "你是一个本地网络诊断 Agent，面向通信工程学生项目展示。"
        "你必须基于工具采集到的真实网络数据分析，不要编造不存在的测试结果。"
        "输出要包含：一句话结论、证据分析、可能原因、给用户的操作建议、给网络管理员或运营商的反馈版本。"
        "如果证据不足，要明确说明还需要做哪些补充测试。"
    )
    payload: dict[str, Any] = snapshot.to_dict()
    user = (
        f"用户补充描述：{user_context or '无'}\n\n"
        "下面是本地网络诊断工具采集到的结构化数据，请生成中文诊断报告：\n"
        f"{payload}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_agent_prompt(
    snapshot: NetworkSnapshot,
    user_context: str = "",
    plan: object | None = None,
    monitor_summary: object | None = None,
) -> list[dict[str, str]]:
    system = (
        "你是 CampusNet Agent 的大模型分析层。"
        "你需要解释 Agent 为什么选择这些工具、每个工具结果说明了什么、下一步应该做什么。"
        "不要编造未执行的测试，不要声称已经测了游戏服务器，除非数据里存在。"
        "输出结构：诊断结论、Agent 执行流程、证据分析、建议操作、给网络管理员或运营商的反馈。"
        "语言要自然、简洁、像中文技术报告，不要使用生硬直译。"
        "不要使用 Markdown 删除线语法，不要输出 ~~。时间范围请写成“20:00-23:00”。"
        "不要说“无法否认用户问题”，应改为“当前快照未捕捉到异常，仍建议用持续监控验证”。"
    )
    payload: dict[str, Any] = {
        "user_context": user_context,
        "agent_plan": getattr(plan, "__dict__", plan),
        "snapshot": snapshot.to_dict(),
        "monitor_summary": getattr(monitor_summary, "__dict__", monitor_summary),
    }
    user = f"请基于下面真实数据生成中文 Agent 诊断报告：\n{payload}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_deepseek_report(
    snapshot: NetworkSnapshot,
    user_context: str = "",
    plan: object | None = None,
    monitor_summary: object | None = None,
    model: str | None = None,
    timeout: int = 45,
) -> LlmReport:
    load_local_env()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    selected_model = model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_DEEPSEEK_MODEL
    base_url = (os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL).rstrip("/")

    if not api_key:
        return LlmReport(
            success=False,
            content="",
            model=selected_model,
            error="DEEPSEEK_API_KEY is not configured.",
        )

    payload = {
        "model": selected_model,
        "messages": build_agent_prompt(snapshot, user_context, plan, monitor_summary),
        "temperature": 0.2,
        "stream": False,
    }

    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "CampusNet-Agent/0.1",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = clean_llm_report(data["choices"][0]["message"]["content"])
        return LlmReport(success=True, content=content, model=selected_model)
    except Exception as exc:
        fallback = _generate_with_curl(base_url, api_key, payload, selected_model, timeout)
        if fallback.success:
            return fallback
        return LlmReport(
            success=False,
            content="",
            model=selected_model,
            error=f"requests failed: {exc}; curl fallback failed: {fallback.error}",
        )


def _generate_with_curl(
    base_url: str,
    api_key: str,
    payload: dict[str, Any],
    model: str,
    timeout: int,
) -> LlmReport:
    command = [
        "curl.exe",
        "-sS",
        "-X",
        "POST",
        f"{base_url}/chat/completions",
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        json.dumps(payload, ensure_ascii=False),
        "-m",
        str(timeout),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout + 5,
        )
        if completed.returncode != 0:
            return LlmReport(False, "", model, completed.stderr.strip() or "curl failed")
        data = json.loads(completed.stdout)
        if "error" in data:
            return LlmReport(False, "", model, str(data["error"]))
        return LlmReport(True, clean_llm_report(data["choices"][0]["message"]["content"]), model)
    except Exception as exc:
        return LlmReport(False, "", model, str(exc))


def clean_llm_report(content: str) -> str:
    cleaned = content.strip()
    cleaned = re.sub(r"(\d{1,2}:\d{2})\s*(?:~~|~|～|—|–)\s*(\d{1,2}:\d{2})", r"\1-\2", cleaned)
    cleaned = cleaned.replace("~~", "")
    cleaned = cleaned.replace("无法否认用户问题", "不能排除用户遇到的是间歇性问题")
    cleaned = cleaned.replace("仅凭当前凌晨数据", "仅凭当前这次快照数据")
    cleaned = cleaned.replace("当前凌晨数据", "当前这次快照数据")
    cleaned = re.sub(r"(?<!\d)10\s*30\s*分钟", "10-30 分钟", cleaned)
    cleaned = re.sub(r"(?<!\d)1030\s*分钟", "10-30 分钟", cleaned)
    return cleaned
