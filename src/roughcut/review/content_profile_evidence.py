from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IdentityEvidenceBundle:
    transcript_excerpt: str
    source_name: str
    transcript_hints: dict[str, Any]
    source_hints: dict[str, Any]
    visual_hints: dict[str, Any]
    visible_text_hints: dict[str, Any]
    profile_identity: dict[str, Any]
    source_context_hints: dict[str, Any] = field(default_factory=dict)
    visual_cluster_hints: dict[str, Any] = field(default_factory=dict)
    memory_confirmed_hints: dict[str, Any] = field(default_factory=dict)
    transcript_source_labels: dict[str, Any] = field(default_factory=dict)
    ocr_hints: dict[str, Any] = field(default_factory=dict)
    graph_confirmed_entities: list[dict[str, Any]] = field(default_factory=list)
