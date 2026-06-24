from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any, Callable

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from roughcut.config import get_settings


STRATEGY_FIXTURE_RUNTIME_PREFLIGHT_SCHEMA = "strategy_fixture_runtime_preflight.v1"


def check_strategy_fixture_runtime_preflight(
    *,
    base_url: str,
    health_path: str,
    transcribe_path: str,
    model_name: str,
    timeout_sec: float,
    sample_audio: Path | None = None,
    generated_sample_audio: Path | None = None,
    skip_health: bool = False,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
) -> dict[str, Any]:
    started = time.perf_counter()
    base_url = str(base_url or "").strip().rstrip("/")
    health_path = _normalize_path(health_path or "/health")
    transcribe_path = _normalize_path(transcribe_path or "/transcribe")
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    generated_sample = False
    if sample_audio is None:
        if generated_sample_audio is None:
            temp_dir = tempfile.TemporaryDirectory()
            sample_audio = Path(temp_dir.name) / "strategy_fixture_asr_probe.wav"
        else:
            sample_audio = generated_sample_audio
        write_asr_probe_wav(sample_audio)
        generated_sample = True

    health = _health_check(
        base_url=base_url,
        health_path=health_path,
        timeout_sec=timeout_sec,
        skip_health=skip_health,
        client_factory=client_factory,
    )
    transcribe = _transcribe_check(
        base_url=base_url,
        transcribe_path=transcribe_path,
        model_name=model_name,
        timeout_sec=timeout_sec,
        sample_audio=sample_audio,
        client_factory=client_factory,
    )
    ok = bool(health.get("ok")) and bool(transcribe.get("ok"))
    result = {
        "schema": STRATEGY_FIXTURE_RUNTIME_PREFLIGHT_SCHEMA,
        "ok": ok,
        "base_url": base_url,
        "health_path": health_path,
        "transcribe_path": transcribe_path,
        "model_name": model_name,
        "sample_audio": str(sample_audio),
        "generated_sample": generated_sample,
        "health": health,
        "transcribe": transcribe,
        "blocking_reasons": _blocking_reasons(health=health, transcribe=transcribe),
        "duration_sec": round(time.perf_counter() - started, 3),
    }
    if temp_dir is not None:
        temp_dir.cleanup()
    return result


def write_asr_probe_wav(path: Path, *, duration_sec: float = 0.4, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    amplitude = 0.18
    frequency = 440.0
    frame_count = max(1, int(sample_rate * duration_sec))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for index in range(frame_count):
            sample = int(32767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
            wav.writeframes(struct.pack("<h", sample))


def _health_check(
    *,
    base_url: str,
    health_path: str,
    timeout_sec: float,
    skip_health: bool,
    client_factory: Callable[..., httpx.Client],
) -> dict[str, Any]:
    if skip_health:
        return {"ok": True, "skipped": True}
    if not base_url:
        return {"ok": False, "error": "missing_base_url"}
    url = f"{base_url}{health_path}"
    try:
        with client_factory(timeout=timeout_sec) as client:
            response = client.get(url)
        return {
            "ok": 200 <= int(response.status_code) < 300,
            "url": url,
            "status_code": int(response.status_code),
            "body_preview": _body_preview(response),
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": type(exc).__name__, "detail": str(exc)}


def _transcribe_check(
    *,
    base_url: str,
    transcribe_path: str,
    model_name: str,
    timeout_sec: float,
    sample_audio: Path,
    client_factory: Callable[..., httpx.Client],
) -> dict[str, Any]:
    if not base_url:
        return {"ok": False, "error": "missing_base_url"}
    if not sample_audio.exists():
        return {"ok": False, "error": "missing_sample_audio", "sample_audio": str(sample_audio)}
    url = f"{base_url}{transcribe_path}"
    data = {
        "hotwords": "",
        "model": model_name,
        "model_name": model_name,
        "max_new_tokens": "512",
        "beam_size": "5",
        "best_of": "5",
        "condition_on_previous_text": "false",
        "vad_filter": "true",
    }
    try:
        with sample_audio.open("rb") as audio_file:
            files = {"file": (sample_audio.name, audio_file, "application/octet-stream")}
            with client_factory(timeout=timeout_sec) as client:
                response = client.post(url, files=files, data=data)
        parsed_json = _safe_json(response)
        return {
            "ok": 200 <= int(response.status_code) < 300 and parsed_json is not None,
            "url": url,
            "status_code": int(response.status_code),
            "json_response": parsed_json,
            "body_preview": _body_preview(response),
        }
    except Exception as exc:
        return {"ok": False, "url": url, "error": type(exc).__name__, "detail": str(exc)}


def _blocking_reasons(*, health: dict[str, Any], transcribe: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not health.get("ok"):
        reasons.append("local_asr_health_unavailable")
    if not transcribe.get("ok"):
        status = transcribe.get("status_code")
        if status:
            reasons.append(f"local_asr_transcribe_http_{status}")
        else:
            reasons.append("local_asr_transcribe_unavailable")
    return reasons


def _normalize_path(path: str) -> str:
    text = str(path or "").strip() or "/"
    return text if text.startswith("/") else f"/{text}"


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _body_preview(response: httpx.Response, *, limit: int = 500) -> str:
    try:
        text = response.text
    except Exception:
        text = ""
    return text[:limit]


def parse_args() -> argparse.Namespace:
    settings = get_settings()
    parser = argparse.ArgumentParser(
        description="Preflight the local ASR health and /transcribe path before running real strategy render fixtures."
    )
    parser.add_argument("--base-url", default=str(getattr(settings, "local_asr_api_base_url", "") or ""))
    parser.add_argument("--health-path", default=str(getattr(settings, "local_asr_health_path", "") or "/health"))
    parser.add_argument("--transcribe-path", default=str(getattr(settings, "local_asr_transcribe_path", "") or "/transcribe"))
    parser.add_argument("--model-name", default=str(getattr(settings, "local_asr_model_name", "") or ""))
    parser.add_argument("--sample-audio", type=Path, default=None)
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    parser.add_argument("--skip-health", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = check_strategy_fixture_runtime_preflight(
        base_url=args.base_url,
        health_path=args.health_path,
        transcribe_path=args.transcribe_path,
        model_name=args.model_name,
        timeout_sec=args.timeout_sec,
        sample_audio=args.sample_audio,
        generated_sample_audio=args.output.with_suffix(".probe.wav") if args.output and args.sample_audio is None else None,
        skip_health=args.skip_health,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
