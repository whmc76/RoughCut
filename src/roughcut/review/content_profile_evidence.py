from __future__ import annotations

from dataclasses import dataclass
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
