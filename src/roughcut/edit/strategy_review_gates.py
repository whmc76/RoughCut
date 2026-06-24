from __future__ import annotations

from typing import Any

from roughcut.llm_cache import digest_payload


STRATEGY_REVIEW_GATES_SCHEMA_VERSION = "strategy_review_gates.v1"
STRATEGY_REVIEW_GATE_CONFIRMATIONS_SCHEMA_VERSION = "strategy_review_gate_confirmations.v1"

_GATE_KEY_MAP = {
    "strategy_confirmation_required": ("strategy_confirmation", "required"),
    "storyboard_review_required": ("storyboard_review", "required"),
    "timeline_preview_required": ("timeline_preview", "required"),
    "timeline_preview_optional": ("timeline_preview", "optional"),
    "manual_cut_review_recommended": ("manual_cut_review", "recommended"),
    "manual_cut_review_optional": ("manual_cut_review", "optional"),
    "highlight_review_recommended": ("highlight_review", "recommended"),
}
_SATISFIED_STATUSES = {"approved", "confirmed", "satisfied", "skipped"}
_VALID_CONFIRMATION_STATUSES = _SATISFIED_STATUSES | {"pending", "rejected"}


def _confirmation_status(confirmations: dict[str, Any], gate_id: str) -> str:
    value = confirmations.get(gate_id)
    if isinstance(value, dict):
        return str(value.get("status") or "").strip().lower()
    return str(value or "").strip().lower()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def strategy_review_gate_evidence_fingerprint(
    *,
    pipeline_plan: dict[str, Any] | None,
    classification: dict[str, Any] | None = None,
) -> str:
    plan = _as_dict(pipeline_plan)
    source_classification = _as_dict(classification)
    policy = _as_dict(plan.get("strategy_policy"))
    return digest_payload(
        {
            "strategy_type": str(plan.get("strategy_type") or "").strip(),
            "production_mode": str(plan.get("production_mode") or "").strip(),
            "primary_type": str(plan.get("primary_type") or "").strip(),
            "review_gates": [
                str(item or "").strip()
                for item in list(plan.get("review_gates") or [])
                if str(item or "").strip()
            ],
            "reason_codes": [
                str(item or "").strip()
                for item in list(plan.get("reason_codes") or [])
                if str(item or "").strip()
            ],
            "classification": {
                "primary_type": str(source_classification.get("primary_type") or "").strip(),
                "production_mode": str(source_classification.get("production_mode") or "").strip(),
                "content_tags": list(source_classification.get("content_tags") or []),
                "media_tags": list(source_classification.get("media_tags") or []),
                "editing_signals": list(source_classification.get("editing_signals") or []),
                "asset_tags": list(source_classification.get("asset_tags") or []),
                "confidence": source_classification.get("confidence"),
            },
            "strategy_policy": {
                "strategy_type": str(policy.get("strategy_type") or "").strip(),
                "review_policy": _as_dict(policy.get("review_policy")),
            },
        }
    )


def normalize_strategy_review_gate_confirmations(
    payload: dict[str, Any] | None,
    *,
    pipeline_plan: dict[str, Any] | None,
    classification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = _as_dict(payload)
    expected_fingerprint = strategy_review_gate_evidence_fingerprint(
        pipeline_plan=pipeline_plan,
        classification=classification,
    )
    stored_fingerprint = str(source.get("evidence_fingerprint") or "").strip()
    if not stored_fingerprint or stored_fingerprint != expected_fingerprint:
        return {}
    confirmations = _as_dict(source.get("confirmations"))
    normalized: dict[str, Any] = {}
    for gate_id, value in confirmations.items():
        normalized_gate_id = str(gate_id or "").strip()
        if not normalized_gate_id:
            continue
        if isinstance(value, dict):
            item = dict(value)
            status = str(item.get("status") or "").strip().lower()
        else:
            item = {}
            status = str(value or "").strip().lower()
        if status not in _VALID_CONFIRMATION_STATUSES:
            continue
        item["status"] = status
        normalized[normalized_gate_id] = item
    return normalized


def build_strategy_review_gate_confirmations_payload(
    *,
    gate_ids: list[str],
    pipeline_plan: dict[str, Any] | None,
    classification: dict[str, Any] | None = None,
    status: str = "approved",
    note: str = "",
    actor: str = "operator",
) -> dict[str, Any]:
    normalized_status = str(status or "").strip().lower() or "approved"
    if normalized_status not in _VALID_CONFIRMATION_STATUSES:
        normalized_status = "approved"
    normalized_gate_ids = []
    for gate_id in gate_ids:
        normalized = str(gate_id or "").strip()
        if normalized and normalized not in normalized_gate_ids:
            normalized_gate_ids.append(normalized)
    confirmation_item = {
        "status": normalized_status,
        "actor": str(actor or "operator").strip() or "operator",
    }
    normalized_note = str(note or "").strip()
    if normalized_note:
        confirmation_item["note"] = normalized_note
    return {
        "schema": STRATEGY_REVIEW_GATE_CONFIRMATIONS_SCHEMA_VERSION,
        "evidence_fingerprint": strategy_review_gate_evidence_fingerprint(
            pipeline_plan=pipeline_plan,
            classification=classification,
        ),
        "strategy_type": str((_as_dict(pipeline_plan)).get("strategy_type") or "").strip(),
        "confirmations": {
            gate_id: dict(confirmation_item)
            for gate_id in normalized_gate_ids
        },
    }


def build_strategy_review_gate_status(
    pipeline_plan: dict[str, Any] | None,
    *,
    confirmations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = dict(pipeline_plan or {}) if isinstance(pipeline_plan, dict) else {}
    confirmation_payload = dict(confirmations or {}) if isinstance(confirmations, dict) else {}
    raw_gates = [
        str(item or "").strip()
        for item in list(plan.get("review_gates") or [])
        if str(item or "").strip()
    ]
    gate_rows: list[dict[str, Any]] = []
    seen_gate_ids: set[str] = set()
    for raw_gate in raw_gates:
        gate_id, requirement = _GATE_KEY_MAP.get(raw_gate, (raw_gate, "optional"))
        if gate_id in seen_gate_ids:
            continue
        seen_gate_ids.add(gate_id)
        status = _confirmation_status(confirmation_payload, gate_id)
        satisfied = status in _SATISFIED_STATUSES
        if not status:
            status = "pending" if requirement == "required" else "not_required"
        blocking = requirement == "required" and not satisfied
        gate_rows.append(
            {
                "gate_id": gate_id,
                "source_key": raw_gate,
                "requirement": requirement,
                "status": status,
                "blocking": blocking,
            }
        )

    blocking_gate_ids = [item["gate_id"] for item in gate_rows if item["blocking"]]
    return {
        "schema": STRATEGY_REVIEW_GATES_SCHEMA_VERSION,
        "strategy_type": str(plan.get("strategy_type") or "").strip(),
        "gates": gate_rows,
        "blocking": bool(blocking_gate_ids),
        "blocking_gate_ids": blocking_gate_ids,
        "required_gate_count": sum(1 for item in gate_rows if item["requirement"] == "required"),
        "recommended_gate_count": sum(1 for item in gate_rows if item["requirement"] == "recommended"),
        "optional_gate_count": sum(1 for item in gate_rows if item["requirement"] == "optional"),
    }
