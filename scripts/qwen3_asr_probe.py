from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                dumped = method()
            except TypeError:
                try:
                    dumped = method(mode="json")
                except TypeError:
                    continue
            if isinstance(dumped, dict):
                return dict(dumped)
    if hasattr(value, "__dict__"):
        return {key: item for key, item in vars(value).items() if not key.startswith("_")}
    return {"value": repr(value)}


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    dumped = _as_dict(value)
    if dumped and dumped != {"value": repr(value)}:
        return {str(key): _jsonable(item) for key, item in dumped.items()}
    return repr(value)


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_timestamp_item(item: Any) -> dict[str, Any]:
    data = _as_dict(item)
    text = str(
        data.get("text")
        or data.get("word")
        or data.get("char")
        or data.get("value")
        or ""
    ).strip()
    start = _coerce_float(data.get("start_time", data.get("start")))
    end = _coerce_float(data.get("end_time", data.get("end")))
    normalized = {"text": text, "start": start, "end": end}
    confidence = _coerce_float(data.get("confidence", data.get("score")))
    if confidence is not None:
        normalized["confidence"] = confidence
    raw_extra = {
        key: value
        for key, value in data.items()
        if key not in {"text", "word", "char", "value", "start_time", "start", "end_time", "end", "confidence", "score"}
    }
    if raw_extra:
        normalized["raw"] = _jsonable(raw_extra)
    return normalized


def _normalize_timestamps(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        if value and isinstance(value[0], list):
            items = value[0]
        else:
            items = value
        normalized: list[dict[str, Any]] = []
        for item in items:
            data = _as_dict(item)
            nested_items = data.get("items")
            if isinstance(nested_items, list):
                normalized.extend(_normalize_timestamp_item(nested_item) for nested_item in nested_items)
            else:
                normalized.append(_normalize_timestamp_item(item))
        return normalized
    data = _as_dict(value)
    nested_items = data.get("items")
    if isinstance(nested_items, list):
        return [_normalize_timestamp_item(item) for item in nested_items]
    return [_normalize_timestamp_item(value)]


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe Qwen3-ASR with Qwen3-ForcedAligner timestamps on one audio file.")
    parser.add_argument("audio", type=Path)
    parser.add_argument("--asr-model", default="Qwen/Qwen3-ASR-1.7B")
    parser.add_argument("--aligner-model", default="Qwen/Qwen3-ForcedAligner-0.6B")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--context", default="")
    parser.add_argument("--device-map", default="cuda:0")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    if sys.platform == "win32" and not sys.flags.utf8_mode:
        raise SystemExit("Windows must run this probe with PYTHONUTF8=1, otherwise Chinese output can be mojibake.")

    started = time.perf_counter()
    import torch
    from qwen_asr import Qwen3ASRModel

    loaded_imports_at = time.perf_counter()
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.empty_cache()
    model = Qwen3ASRModel.from_pretrained(
        args.asr_model,
        dtype=torch.bfloat16,
        device_map=args.device_map,
        max_inference_batch_size=1,
        max_new_tokens=args.max_new_tokens,
        forced_aligner=args.aligner_model,
        forced_aligner_kwargs={
            "dtype": torch.bfloat16,
            "device_map": args.device_map,
        },
    )
    loaded_model_at = time.perf_counter()
    results = model.transcribe(
        audio=str(args.audio),
        context=args.context,
        language=args.language,
        return_time_stamps=True,
    )
    peak_allocated = None
    peak_reserved = None
    if torch.cuda.is_available():
        torch.cuda.synchronize()
        peak_allocated = round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1)
        peak_reserved = round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1)
    completed_at = time.perf_counter()

    rows: list[dict[str, Any]] = []
    for result in results:
        data = _as_dict(result)
        text = str(data.get("text") or getattr(result, "text", "") or "").strip()
        language = str(data.get("language") or getattr(result, "language", "") or "").strip()
        timestamps = _normalize_timestamps(data.get("time_stamps") or getattr(result, "time_stamps", None))
        rows.append(
            {
                "language": language,
                "text": text,
                "timestamps": timestamps,
                "timestamp_count": len(timestamps),
                "preview": text[:240],
            }
        )

    payload = {
        "audio": str(args.audio),
        "asr_model": args.asr_model,
        "aligner_model": args.aligner_model,
        "context": args.context,
        "results": rows,
        "timing": {
            "import_seconds": round(loaded_imports_at - started, 3),
            "load_seconds": round(loaded_model_at - loaded_imports_at, 3),
            "infer_seconds": round(completed_at - loaded_model_at, 3),
            "total_seconds": round(completed_at - started, 3),
        },
        "gpu_memory_mib": {
            "torch_peak_allocated": peak_allocated,
            "torch_peak_reserved": peak_reserved,
        },
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
