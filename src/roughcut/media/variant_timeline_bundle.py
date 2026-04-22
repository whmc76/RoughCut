from __future__ import annotations

from typing import Any


def resolve_effective_variant_timeline_bundle(bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    if isinstance(bundle, dict) and isinstance(bundle.get("variants"), dict):
        return bundle
    return None
