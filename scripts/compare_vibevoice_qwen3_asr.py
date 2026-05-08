from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any


def _coerce_seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else 0.0


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


def _segment_text(item: dict[str, Any]) -> str:
    return str(item.get("text") or item.get("Content") or item.get("content") or "").strip()


def _timestamp_items(value: Any) -> list[dict[str, Any]]:
    data = _as_dict(value)
    if isinstance(data.get("items"), list):
        raw_items = data["items"]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]
    items = []
    for raw in raw_items:
        row = _as_dict(raw)
        text = str(row.get("text") or row.get("word") or row.get("char") or "").strip()
        start = row.get("start_time", row.get("start"))
        end = row.get("end_time", row.get("end"))
        if not text:
            continue
        items.append({"text": text, "start": _coerce_seconds(start), "end": _coerce_seconds(end)})
    return items


def _gpu_snapshot(torch: Any) -> dict[str, float | None]:
    if not torch.cuda.is_available():
        return {"allocated": None, "reserved": None, "peak_allocated": None, "peak_reserved": None}
    torch.cuda.synchronize()
    return {
        "allocated": round(torch.cuda.memory_allocated() / 1024 / 1024, 1),
        "reserved": round(torch.cuda.memory_reserved() / 1024 / 1024, 1),
        "peak_allocated": round(torch.cuda.max_memory_allocated() / 1024 / 1024, 1),
        "peak_reserved": round(torch.cuda.max_memory_reserved() / 1024 / 1024, 1),
    }


def _reset_gpu(torch: Any) -> None:
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()


def run_vibevoice(args: argparse.Namespace) -> dict[str, Any]:
    import torch
    from transformers import AutoConfig, AutoModelForCausalLM
    from vibevoice.modular.configuration_vibevoice import VibeVoiceASRConfig
    from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
    from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor

    _reset_gpu(torch)
    started = time.perf_counter()
    VibeVoiceASRConfig.model_type = "vibevoice"
    AutoConfig.register("vibevoice", VibeVoiceASRConfig)
    VibeVoiceASRConfig.model_type = "vibevoice_asr"
    AutoConfig.register("vibevoice_asr", VibeVoiceASRConfig)
    AutoModelForCausalLM.register(VibeVoiceASRConfig, VibeVoiceASRForConditionalGeneration)
    processor = VibeVoiceASRProcessor.from_pretrained(args.vibevoice_model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.vibevoice_model,
        trust_remote_code=True,
        device_map=args.device,
        torch_dtype=torch.bfloat16,
    ).eval()
    loaded_at = time.perf_counter()

    inputs = processor(
        audio=str(args.audio),
        return_tensors="pt",
        context_info=args.hotwords,
        use_streaming=False,
    )
    inputs = {key: value.to(model.device) if hasattr(value, "to") else value for key, value in inputs.items()}
    input_len = int(inputs["input_ids"].shape[1])
    infer_started = time.perf_counter()
    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=processor.pad_id,
        )
    infer_done = time.perf_counter()
    generated = output_ids[:, input_len:]
    raw_text = processor.decode(generated[0], skip_special_tokens=True)
    segments = processor.post_process_transcription(raw_text)
    normalized_segments = [
        {
            "start": _coerce_seconds(item.get("start_time") or item.get("Start")),
            "end": _coerce_seconds(item.get("end_time") or item.get("End")),
            "text": _segment_text(item),
            "speaker": item.get("speaker_id") or item.get("Speaker"),
        }
        for item in segments
        if _segment_text(item)
    ]
    text = "".join(item["text"] for item in normalized_segments).strip() or raw_text.strip()
    return {
        "candidate": "vibevoice_int8",
        "model": args.vibevoice_model,
        "hotwords": args.hotwords,
        "text": text,
        "segments": normalized_segments,
        "word_or_char_timestamps": [],
        "raw_text": raw_text,
        "timing": {
            "load_seconds": round(loaded_at - started, 3),
            "infer_seconds": round(infer_done - infer_started, 3),
            "total_seconds": round(infer_done - started, 3),
        },
        "gpu_memory_mib": _gpu_snapshot(torch),
    }


def run_qwen3(args: argparse.Namespace) -> dict[str, Any]:
    import torch
    from qwen_asr import Qwen3ASRModel

    _reset_gpu(torch)
    started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        args.qwen3_model,
        dtype=torch.bfloat16,
        device_map=args.device,
        max_inference_batch_size=1,
        max_new_tokens=args.max_new_tokens,
        forced_aligner=args.qwen3_aligner,
        forced_aligner_kwargs={"dtype": torch.bfloat16, "device_map": args.device},
    )
    loaded_at = time.perf_counter()
    results = model.transcribe(
        audio=str(args.audio),
        context=args.hotwords,
        language=args.language,
        return_time_stamps=True,
    )
    infer_done = time.perf_counter()
    first = results[0] if results else None
    text = str(getattr(first, "text", "") or "").strip()
    timestamps = _timestamp_items(getattr(first, "time_stamps", None))
    return {
        "candidate": "qwen3_asr_bf16_forced_aligner",
        "model": args.qwen3_model,
        "aligner": args.qwen3_aligner,
        "hotwords": args.hotwords,
        "text": text,
        "segments": [{"start": timestamps[0]["start"], "end": timestamps[-1]["end"], "text": text}] if timestamps else [],
        "word_or_char_timestamps": timestamps,
        "timing": {
            "load_seconds": round(loaded_at - started, 3),
            "infer_seconds": round(infer_done - loaded_at, 3),
            "total_seconds": round(infer_done - started, 3),
        },
        "gpu_memory_mib": _gpu_snapshot(torch),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("--candidate", choices=["vibevoice", "qwen3", "all"], default="all")
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--language", default="Chinese")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--vibevoice-model", default="Dubedo/VibeVoice-ASR-INT8")
    parser.add_argument("--qwen3-model", default="Qwen/Qwen3-ASR-1.7B")
    parser.add_argument("--qwen3-aligner", default="Qwen/Qwen3-ForcedAligner-0.6B")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    results = []
    if args.candidate in {"vibevoice", "all"}:
        results.append(run_vibevoice(args))
    if args.candidate in {"qwen3", "all"}:
        results.append(run_qwen3(args))
    payload = {
        "audio": str(args.audio),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
