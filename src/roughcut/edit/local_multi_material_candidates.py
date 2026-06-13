from __future__ import annotations

from typing import Any

from roughcut.edit.capability_orchestrator import normalize_local_asset_inventory


def build_local_multi_material_candidates(
    *,
    content_profile: dict[str, Any] | None,
    local_asset_inventory: dict[str, Any] | None = None,
    max_count: int = 4,
) -> list[dict[str, Any]]:
    profile = dict(content_profile or {}) if isinstance(content_profile, dict) else {}
    merged_source_names = [
        str(item).strip()
        for item in list(profile.get("merged_source_names") or [])
        if str(item).strip()
    ]
    if len(merged_source_names) < 2:
        return []

    inventory = normalize_local_asset_inventory(local_asset_inventory)
    if not bool(inventory.get("multi_material_ready")):
        return []

    content_kind = str(profile.get("content_kind") or "").strip().lower()
    if content_kind not in {"commentary", "unboxing", "tutorial", "vlog"}:
        return []

    primary_name = merged_source_names[0]
    auxiliary_names = merged_source_names[1:]
    candidates: list[dict[str, Any]] = []

    for offset, source_name in enumerate(auxiliary_names[:max_count], start=1):
        role = _infer_material_role(source_name, content_kind=content_kind, order_index=offset)
        candidate = {
            "index": len(candidates),
            "source_name": source_name,
            "role": role,
            "order_index": offset,
            "primary_source_name": primary_name,
            "score": round(_multi_material_score(role=role, content_kind=content_kind, order_index=offset), 3),
            "suggested_operation": _suggested_operation(role),
            "reasons": _multi_material_reasons(
                role=role,
                content_kind=content_kind,
                source_name=source_name,
            ),
        }
        candidates.append(candidate)

    candidates.sort(key=lambda item: (-float(item.get("score", 0.0) or 0.0), int(item.get("order_index", 0) or 0)))
    for index, candidate in enumerate(candidates):
        candidate["index"] = index
    return candidates


def _infer_material_role(source_name: str, *, content_kind: str, order_index: int) -> str:
    normalized = str(source_name or "").strip().lower()
    if any(token in normalized for token in ("detail", "macro", "close", "cut", "insert", "shot")):
        return "detail_support"
    if any(token in normalized for token in ("screen", "demo", "step", "lesson", "guide")):
        return "step_support"
    if any(token in normalized for token in ("broll", "street", "travel", "ambience", "ambient")):
        return "context_support"
    if content_kind == "tutorial":
        return "step_support" if order_index <= 2 else "detail_support"
    if content_kind in {"vlog", "commentary"}:
        return "context_support"
    return "detail_support"


def _multi_material_score(*, role: str, content_kind: str, order_index: int) -> float:
    base = {
        "detail_support": 0.92,
        "step_support": 0.96,
        "context_support": 0.84,
    }.get(role, 0.76)
    kind_bonus = {
        ("tutorial", "step_support"): 0.14,
        ("tutorial", "detail_support"): 0.08,
        ("commentary", "context_support"): 0.08,
        ("unboxing", "detail_support"): 0.12,
        ("vlog", "context_support"): 0.12,
    }.get((content_kind, role), 0.0)
    order_penalty = max(0.0, (order_index - 1) * 0.06)
    return max(0.0, min(1.6, base + kind_bonus - order_penalty))


def _suggested_operation(role: str) -> str:
    if role == "step_support":
        return "interleave_after_step_boundary"
    if role == "context_support":
        return "interleave_between_body_sections"
    return "insert_into_detail_window"


def _multi_material_reasons(*, role: str, content_kind: str, source_name: str) -> list[str]:
    reasons = [f"检测到辅助上传素材 {source_name}"]
    if role == "step_support":
        reasons.append("素材名更像步骤演示或录屏补充")
    elif role == "context_support":
        reasons.append("素材名更像环境/上下文补充镜头")
    else:
        reasons.append("素材名更像细节或特写补充镜头")
    if content_kind == "tutorial":
        reasons.append("当前内容形态适合保守的多素材步骤补充")
    elif content_kind in {"commentary", "unboxing"}:
        reasons.append("当前内容形态适合保守的主讲 + 补充素材拼接")
    return reasons
