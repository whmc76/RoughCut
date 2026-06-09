from __future__ import annotations

import hashlib
import json
from typing import Any

from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text


def subtitle_payload_fingerprint(subtitles: list[dict[str, Any]]) -> str | None:
    rows: list[dict[str, Any]] = []
    for fallback_index, item in enumerate(subtitles):
        if not isinstance(item, dict):
            continue
        text = subtitle_display_rule_text(item)
        if not text:
            continue
        try:
            index = int(item.get("source_index", item.get("index", fallback_index)) or fallback_index)
            start_time = round(float(item.get("start_time", item.get("start", 0.0)) or 0.0), 3)
            end_time = round(float(item.get("end_time", item.get("end", start_time)) or start_time), 3)
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "index": index,
                "start": start_time,
                "end": end_time,
                "text": text,
            }
        )
    if not rows:
        return None
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
