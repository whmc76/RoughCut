from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


GateSeverity = Literal["error", "warn"]
GateStatus = Literal["pass", "warn", "fail"]


@dataclass(frozen=True, slots=True)
class AsrToken:
    text: str
    start_sec: float
    end_sec: float


@dataclass(frozen=True, slots=True)
class SubtitleTiming:
    text: str
    start_sec: float
    end_sec: float


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    start_sec: float
    end_sec: float
    text: str = ""
    score: float = 0.0
    matched_keywords: tuple[str, ...] = ()
    status: str = "done"


@dataclass(frozen=True, slots=True)
class SceneSpan:
    start_sec: float
    end_sec: float
    score: float = 0.0
    source: str = "detected"


@dataclass(frozen=True, slots=True)
class GateIssue:
    code: str
    severity: GateSeverity
    message: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GateResult:
    status: GateStatus
    issues: tuple[GateIssue, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "warn"}

    @property
    def failed(self) -> bool:
        return self.status == "fail"


def merge_gate_results(*results: GateResult) -> GateResult:
    issues: list[GateIssue] = []
    metrics: dict[str, Any] = {}
    status: GateStatus = "pass"
    for result in results:
        issues.extend(result.issues)
        metrics.update(result.metrics)
        if result.status == "fail":
            status = "fail"
        elif result.status == "warn" and status != "fail":
            status = "warn"
    return GateResult(status=status, issues=tuple(issues), metrics=metrics)
