from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PingResult:
    target: str
    success: bool
    packets_sent: int | None = None
    packets_received: int | None = None
    packet_loss_percent: float | None = None
    min_ms: float | None = None
    avg_ms: float | None = None
    max_ms: float | None = None
    raw: str = ""
    error: str | None = None


@dataclass
class DnsResult:
    host: str
    success: bool
    addresses: list[str] = field(default_factory=list)
    elapsed_ms: float | None = None
    dns_server: str | None = None
    raw: str = ""
    error: str | None = None


@dataclass
class TraceHop:
    hop: int
    address: str | None
    latency_ms: float | None
    raw: str


@dataclass
class TraceResult:
    target: str
    success: bool
    hops: list[TraceHop] = field(default_factory=list)
    raw: str = ""
    error: str | None = None


@dataclass
class Diagnosis:
    summary: str
    severity: str
    likely_causes: list[str]
    evidence: list[str]
    suggestions: list[str]


@dataclass
class NetworkSnapshot:
    created_at: datetime
    gateway: str | None
    dns_servers: list[str]
    pings: dict[str, PingResult]
    dns: dict[str, DnsResult]
    traces: dict[str, TraceResult]
    diagnosis: Diagnosis | None = None

    def to_dict(self) -> dict[str, Any]:
        def obj(value: Any) -> Any:
            if hasattr(value, "__dataclass_fields__"):
                return {k: obj(v) for k, v in value.__dict__.items()}
            if isinstance(value, dict):
                return {k: obj(v) for k, v in value.items()}
            if isinstance(value, list):
                return [obj(v) for v in value]
            if isinstance(value, datetime):
                return value.isoformat(timespec="seconds")
            return value

        return obj(self)


