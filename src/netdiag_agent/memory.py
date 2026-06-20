from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from netdiag_agent.models import NetworkSnapshot
from netdiag_agent.monitor import MonitorSummary
from netdiag_agent.planner import AgentPlan
from netdiag_agent.rag import hashing_embedding


DEFAULT_MEMORY_PATH = Path("data/memory/network_memory.jsonl")
MAX_MEMORY_RECORDS = 200

ISSUE_TYPE_LABELS = {
    "dns": "DNS 异常",
    "gateway": "本地链路",
    "latency": "高延迟/抖动",
    "single_site": "单站点异常",
    "routing": "路由路径",
    "general": "通用网络问题",
}


@dataclass(frozen=True)
class MemoryRecord:
    created_at: str
    user_context: str
    mode: str
    summary: str
    severity: str
    evidence: list[str]
    suggestions: list[str]
    gateway: str | None
    dns_servers: list[str]
    memory_id: str = ""
    last_seen_at: str = ""
    issue_type: str = "general"
    value_score: int = 0
    occurrences: int = 1
    target_hint: str | None = None

    @property
    def retrieval_text(self) -> str:
        parts = [
            self.user_context,
            self.summary,
            issue_type_label(self.issue_type),
            " ".join(self.evidence[:5]),
            " ".join(self.suggestions[:3]),
            self.target_hint or "",
        ]
        return " ".join(part for part in parts if part).strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        created_at = str(data.get("created_at") or "")
        last_seen_at = str(data.get("last_seen_at") or created_at or "")
        record = cls(
            created_at=created_at,
            user_context=str(data.get("user_context") or "未提供具体症状"),
            mode=str(data.get("mode") or "auto"),
            summary=str(data.get("summary") or "未生成历史结论"),
            severity=str(data.get("severity") or "low"),
            evidence=_ensure_text_list(data.get("evidence")),
            suggestions=_ensure_text_list(data.get("suggestions")),
            gateway=_coerce_optional_text(data.get("gateway")),
            dns_servers=_ensure_text_list(data.get("dns_servers")),
            memory_id=str(data.get("memory_id") or ""),
            last_seen_at=last_seen_at,
            issue_type=str(data.get("issue_type") or "general"),
            value_score=int(data.get("value_score") or 0),
            occurrences=max(1, int(data.get("occurrences") or 1)),
            target_hint=_coerce_optional_text(data.get("target_hint")),
        )

        if not record.issue_type or record.issue_type == "general":
            record = replace(record, issue_type=infer_issue_type(record.user_context, record.summary, record.evidence))
        if record.value_score <= 0:
            record = replace(record, value_score=infer_value_score(record.severity, record.evidence, record.mode))
        if not record.last_seen_at:
            record = replace(record, last_seen_at=record.created_at)
        if not record.memory_id:
            record = replace(record, memory_id=build_memory_id(record))
        return record

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "created_at": self.created_at,
            "last_seen_at": self.last_seen_at,
            "user_context": self.user_context,
            "mode": self.mode,
            "summary": self.summary,
            "severity": self.severity,
            "issue_type": self.issue_type,
            "value_score": self.value_score,
            "occurrences": self.occurrences,
            "target_hint": self.target_hint,
            "evidence": self.evidence,
            "suggestions": self.suggestions,
            "gateway": self.gateway,
            "dns_servers": self.dns_servers,
        }


@dataclass(frozen=True)
class MemoryMatch:
    record: MemoryRecord
    score: float
    reasons: list[str]


@dataclass(frozen=True)
class MemoryOverview:
    total_records: int
    repeated_records: int
    high_value_records: int
    latest_seen_at: str | None
    top_issue_types: list[tuple[str, int]]


class NetworkMemory:
    def __init__(self, path: str | Path = DEFAULT_MEMORY_PATH) -> None:
        self.path = Path(path)

    def load(self, limit: int | None = 50) -> list[MemoryRecord]:
        if not self.path.exists():
            return []

        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            try:
                records.append(MemoryRecord.from_dict(payload))
            except (TypeError, ValueError):
                continue

        records = _coalesce_records(records)
        records.sort(key=_memory_sort_key, reverse=True)
        return records if limit is None else records[:limit]

    def remember(
        self,
        user_context: str,
        plan: AgentPlan,
        snapshot: NetworkSnapshot,
        monitor_summary: MonitorSummary | None = None,
    ) -> MemoryRecord | None:
        if snapshot.diagnosis is None:
            return None

        now = datetime.now().isoformat(timespec="seconds")
        candidate = MemoryRecord(
            memory_id="",
            created_at=now,
            last_seen_at=now,
            user_context=(user_context or "未提供具体症状").strip(),
            mode=plan.mode,
            summary=snapshot.diagnosis.summary,
            severity=snapshot.diagnosis.severity,
            issue_type=infer_issue_type(
                user_context=user_context,
                summary=snapshot.diagnosis.summary,
                evidence=snapshot.diagnosis.evidence,
            ),
            value_score=score_memory_case(plan, snapshot, monitor_summary),
            occurrences=1,
            target_hint=plan.targets.get("custom") or next(iter(plan.targets.values()), None),
            evidence=_merge_unique_texts(
                snapshot.diagnosis.evidence[:8],
                [monitor_summary.conclusion] if monitor_summary else [],
            ),
            suggestions=snapshot.diagnosis.suggestions[:6],
            gateway=snapshot.gateway,
            dns_servers=snapshot.dns_servers,
        )
        candidate = replace(candidate, memory_id=build_memory_id(candidate))

        records = self.load(limit=None)
        by_id = {record.memory_id: record for record in records}
        if candidate.memory_id in by_id:
            merged = merge_memory_records(by_id[candidate.memory_id], candidate)
            by_id[candidate.memory_id] = merged
            remembered = merged
        else:
            by_id[candidate.memory_id] = candidate
            remembered = candidate

        retained = retain_high_value_memories(list(by_id.values()), limit=MAX_MEMORY_RECORDS)
        self._write_all(retained)
        return remembered

    def recall(self, user_context: str, mode: str | None = None, limit: int = 3) -> list[MemoryRecord]:
        return [match.record for match in self.recall_matches(user_context, mode=mode, limit=limit)]

    def recall_matches(self, user_context: str, mode: str | None = None, limit: int = 3) -> list[MemoryMatch]:
        records = self.load(limit=None)
        if not records:
            return []

        query_terms = tokenize_for_memory(user_context or "通用网络故障")
        query_vector = hashing_embedding(user_context or "通用网络故障")

        matches: list[MemoryMatch] = []
        for record in records:
            score, reasons = score_memory_match(record, query_terms, query_vector, mode=mode)
            matches.append(MemoryMatch(record=record, score=score, reasons=reasons))

        matches.sort(key=lambda item: (item.score, _memory_sort_key(item.record)), reverse=True)
        useful = [match for match in matches[:limit] if match.score >= 0.18]
        if useful:
            return useful
        return matches[:1]

    def context_text(self, records: list[MemoryRecord]) -> str:
        if not records:
            return "暂无历史诊断记忆。"

        lines: list[str] = []
        for index, record in enumerate(records, start=1):
            lines.extend(
                [
                    f"[历史记忆 {index}] {record.last_seen_at or record.created_at}",
                    f"- 问题类型：{issue_type_label(record.issue_type)}",
                    f"- 用户症状：{record.user_context}",
                    f"- 场景模式：{record.mode}",
                    f"- 历史结论：{record.summary}",
                    f"- 风险等级：{record.severity}",
                    f"- 出现次数：{record.occurrences}",
                    f"- 关键证据：{'；'.join(record.evidence[:4]) or '无'}",
                    f"- 曾给建议：{'；'.join(record.suggestions[:3]) or '无'}",
                ]
            )
        return "\n".join(lines)

    def overview(self) -> MemoryOverview:
        records = self.load(limit=None)
        latest_seen_at = records[0].last_seen_at if records else None
        issue_counter = Counter(issue_type_label(record.issue_type) for record in records)
        return MemoryOverview(
            total_records=len(records),
            repeated_records=sum(1 for record in records if record.occurrences > 1),
            high_value_records=sum(1 for record in records if record.value_score >= 7),
            latest_seen_at=latest_seen_at,
            top_issue_types=issue_counter.most_common(3),
        )

    def _write_all(self, records: list[MemoryRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(record.to_dict(), ensure_ascii=False) for record in records]
        self.path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def issue_type_label(issue_type: str) -> str:
    return ISSUE_TYPE_LABELS.get(issue_type, ISSUE_TYPE_LABELS["general"])


def infer_issue_type(user_context: str, summary: str, evidence: list[str]) -> str:
    text = " ".join([user_context, summary, *evidence]).lower()
    if any(token in text for token in ["dns", "解析", "域名"]):
        return "dns"
    if any(token in text for token in ["网关", "gateway", "本地网络", "wifi", "wi-fi"]):
        return "gateway"
    if any(token in text for token in ["抖动", "丢包", "延迟", "ping", "卡顿", "游戏"]):
        return "latency"
    if any(token in text for token in ["路由", "tracert", "traceroute", "跃点"]):
        return "routing"
    if any(token in text for token in ["单站点", "站点", "网站", "cdn", "某个网站"]):
        return "single_site"
    return "general"


def infer_value_score(severity: str, evidence: list[str], mode: str) -> int:
    severity_score = {"high": 6, "medium": 4, "low": 2}.get(severity, 2)
    score = severity_score + min(len(evidence), 3)
    if mode in {"single_site", "deep"}:
        score += 1
    return score


def score_memory_case(
    plan: AgentPlan,
    snapshot: NetworkSnapshot,
    monitor_summary: MonitorSummary | None,
) -> int:
    diagnosis = snapshot.diagnosis
    if diagnosis is None:
        return 0

    score = infer_value_score(diagnosis.severity, diagnosis.evidence, plan.mode)
    if monitor_summary:
        score += 2
    if snapshot.traces:
        score += 1
    if any(not result.success or (result.packet_loss_percent or 0) >= 5 for result in snapshot.pings.values()):
        score += 2
    if any(not result.success or (result.elapsed_ms or 0) >= 500 for result in snapshot.dns.values()):
        score += 2
    if plan.targets.get("custom"):
        score += 1
    return score


def build_memory_id(record: MemoryRecord) -> str:
    fingerprint = "|".join(
        [
            record.issue_type,
            normalize_text(record.summary),
            normalize_text(record.target_hint or ""),
            normalize_text(record.gateway or ""),
            ",".join(sorted(record.dns_servers[:2])),
        ]
    )
    return hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:16]


def merge_memory_records(existing: MemoryRecord, incoming: MemoryRecord) -> MemoryRecord:
    return MemoryRecord(
        memory_id=existing.memory_id or incoming.memory_id,
        created_at=existing.created_at or incoming.created_at,
        last_seen_at=incoming.last_seen_at or existing.last_seen_at,
        user_context=pick_richer_text(existing.user_context, incoming.user_context),
        mode=incoming.mode or existing.mode,
        summary=pick_richer_text(existing.summary, incoming.summary),
        severity=pick_higher_severity(existing.severity, incoming.severity),
        issue_type=incoming.issue_type or existing.issue_type,
        value_score=max(existing.value_score, incoming.value_score),
        occurrences=existing.occurrences + 1,
        target_hint=incoming.target_hint or existing.target_hint,
        evidence=_merge_unique_texts(existing.evidence, incoming.evidence),
        suggestions=_merge_unique_texts(existing.suggestions, incoming.suggestions),
        gateway=incoming.gateway or existing.gateway,
        dns_servers=_merge_unique_texts(existing.dns_servers, incoming.dns_servers),
    )


def retain_high_value_memories(records: list[MemoryRecord], limit: int = MAX_MEMORY_RECORDS) -> list[MemoryRecord]:
    records = _coalesce_records(records)
    records.sort(key=lambda record: (record.value_score, record.occurrences, _memory_sort_key(record)), reverse=True)
    retained = records[:limit]
    retained.sort(key=_memory_sort_key, reverse=True)
    return retained


def score_memory_match(
    record: MemoryRecord,
    query_terms: set[str],
    query_vector: list[float],
    mode: str | None = None,
) -> tuple[float, list[str]]:
    record_text = record.retrieval_text
    record_terms = tokenize_for_memory(record_text)
    term_overlap = len(query_terms & record_terms)
    vector_score = dot_product(query_vector, hashing_embedding(record_text))
    score = vector_score * 0.65 + min(term_overlap, 6) * 0.08

    reasons: list[str] = []
    if term_overlap:
        reasons.append(f"关键词重合 {term_overlap} 个")
    if vector_score >= 0.45:
        reasons.append("症状描述较相似")
    if mode and record.mode == mode:
        score += 0.12
        reasons.append("同一诊断模式")
    if record.occurrences > 1:
        score += min(record.occurrences, 4) * 0.03
        reasons.append(f"该问题已重复 {record.occurrences} 次")
    if record.value_score >= 7:
        score += 0.05
        reasons.append("属于高价值案例")
    return score, reasons


def tokenize_for_memory(text: str) -> set[str]:
    lowered = text.lower()
    words = {part for part in lowered.replace("/", " ").replace(",", " ").split() if len(part) >= 2}
    chinese_bigrams = {
        lowered[index : index + 2]
        for index in range(max(0, len(lowered) - 1))
        if "\u4e00" <= lowered[index] <= "\u9fff"
    }
    return words | chinese_bigrams


def dot_product(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def pick_richer_text(left: str, right: str) -> str:
    return right if len(right.strip()) > len(left.strip()) else left


def pick_higher_severity(left: str, right: str) -> str:
    ranks = {"low": 1, "medium": 2, "high": 3}
    return right if ranks.get(right, 0) >= ranks.get(left, 0) else left


def _coalesce_records(records: list[MemoryRecord]) -> list[MemoryRecord]:
    merged: dict[str, MemoryRecord] = {}
    for record in sorted(records, key=_memory_sort_key):
        key = record.memory_id or build_memory_id(record)
        normalized = record if record.memory_id else replace(record, memory_id=key)
        if key in merged:
            merged[key] = merge_memory_records(merged[key], normalized)
        else:
            merged[key] = normalized
    return list(merged.values())


def _memory_sort_key(record: MemoryRecord) -> tuple[str, str]:
    return (
        record.last_seen_at or record.created_at,
        record.created_at,
    )


def _ensure_text_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _coerce_optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _merge_unique_texts(left: list[str], right: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for item in [*left, *right]:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def memory_records_to_rows(records: list[MemoryRecord]) -> list[dict[str, Any]]:
    return [
        {
            "最近出现": record.last_seen_at or record.created_at,
            "问题类型": issue_type_label(record.issue_type),
            "症状": record.user_context,
            "模式": record.mode,
            "结论": record.summary,
            "等级": record.severity,
            "重复次数": record.occurrences,
            "价值分": record.value_score,
        }
        for record in records
    ]


def memory_matches_to_rows(matches: list[MemoryMatch]) -> list[dict[str, Any]]:
    return [
        {
            "最近出现": match.record.last_seen_at or match.record.created_at,
            "问题类型": issue_type_label(match.record.issue_type),
            "结论": match.record.summary,
            "相关度": round(match.score, 3),
            "召回原因": "；".join(match.reasons) or "最近一次相关案例",
        }
        for match in matches
    ]

