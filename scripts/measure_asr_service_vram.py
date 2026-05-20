from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = ROOT / "output" / "test" / "asr-alignment-matrix" / "samples" / "noc_bad_repeat_39_59_39.420_59.000.wav"

SERVICES: dict[str, dict[str, Any]] = {
    "faster_whisper_beam5_nohot": {
        "compose": "faster-whisper-large-v3",
        "container": "asr-faster-whisper-large-v3",
        "url": "http://127.0.0.1:30200",
        "data": {
            "language": "zh",
            "hotwords": "",
            "beam_size": "5",
            "best_of": "5",
            "condition_on_previous_text": "false",
            "vad_filter": "true",
        },
    },
    "funasr_nano_http": {
        "compose": "funasr-nano-2512",
        "container": "asr-funasr-nano-2512",
        "url": "http://127.0.0.1:30210",
        "data": {"language": "zh", "hotwords": "NOC, MT34, S06MINI, 折刀, 开箱", "use_itn": "false"},
    },
    "funasr_paraformer_http": {
        "compose": "funasr-paraformer-zh",
        "container": "asr-funasr-paraformer-zh",
        "url": "http://127.0.0.1:30211",
        "data": {"language": "zh", "hotwords": "NOC, MT34, S06MINI, 折刀, 开箱", "use_itn": "false"},
    },
    "moss_audio_fp16": {
        "compose": "moss-audio-8b-instruct-fp16",
        "container": "asr-moss-audio-8b-instruct-fp16",
        "url": "http://127.0.0.1:30222",
        "data": {"hotwords": "NOC, MT34, S06MINI, 折刀, 开箱", "max_new_tokens": "2048", "timestamp_mode": "false"},
    },
    "moss_audio_bnb4": {
        "compose": "moss-audio-8b-instruct-bnb4",
        "container": "asr-moss-audio-8b-instruct-bnb4",
        "url": "http://127.0.0.1:30221",
        "data": {"hotwords": "NOC, MT34, S06MINI, 折刀, 开箱", "max_new_tokens": "2048", "timestamp_mode": "false"},
    },
    "moss_audio_bnb8": {
        "compose": "moss-audio-8b-instruct-bnb8",
        "container": "asr-moss-audio-8b-instruct-bnb8",
        "url": "http://127.0.0.1:30220",
        "data": {"hotwords": "NOC, MT34, S06MINI, 折刀, 开箱", "max_new_tokens": "2048", "timestamp_mode": "false"},
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure isolated nvidia-smi VRAM for ASR services.")
    parser.add_argument("--compose-file", type=Path, default=ROOT / "docker-compose.asr-matrix.yml")
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument("--output-json", type=Path, default=ROOT / "output" / "test" / "asr-alignment-matrix" / "results" / "asr_isolated_vram.json")
    parser.add_argument("--services", nargs="*", default=list(SERVICES))
    parser.add_argument("--timeout-sec", type=float, default=1800.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = []
    for name in args.services:
        spec = SERVICES[name]
        print(f"== {name} ==", flush=True)
        stop_all(args)
        baseline = gpu_memory_used_mb()
        compose(args, "up", "-d", "--force-recreate", spec["compose"])
        wait_http(spec["url"], args.timeout_sec)
        after_start = gpu_memory_used_mb()
        unload(spec["url"])
        after_unload = gpu_memory_used_mb()
        first = transcribe(spec, args.sample, args.timeout_sec)
        after_first = gpu_memory_used_mb()
        second = transcribe(spec, args.sample, args.timeout_sec)
        after_second = gpu_memory_used_mb()
        result = {
            "name": name,
            "container": spec["container"],
            "baseline_gpu_used_mb": baseline,
            "after_start_gpu_used_mb": after_start,
            "after_unload_gpu_used_mb": after_unload,
            "after_first_gpu_used_mb": after_first,
            "after_second_gpu_used_mb": after_second,
            "model_resident_delta_mb": max(0, after_first - baseline),
            "steady_resident_delta_mb": max(0, after_second - baseline),
            "first_transcribe": first,
            "second_transcribe": second,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        results.append(result)
        stop_all(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output_json.with_suffix(".md").write_text(render_markdown(results), encoding="utf-8")
    print(f"JSON: {args.output_json}", flush=True)
    print(f"Markdown: {args.output_json.with_suffix('.md')}", flush=True)


def compose(args: argparse.Namespace, *parts: str) -> None:
    subprocess.run(["docker", "compose", "-f", str(args.compose_file), *parts], cwd=ROOT, check=True)


def stop_all(args: argparse.Namespace) -> None:
    compose(args, "stop", *[str(spec["compose"]) for spec in SERVICES.values()])
    time.sleep(3)


def wait_http(base_url: str, timeout_sec: float) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0)) as client:
                response = client.get(f"{base_url.rstrip('/')}/health")
                if response.status_code < 500:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"service did not become ready: {base_url}")


def unload(base_url: str) -> None:
    try:
        with httpx.Client(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            client.post(f"{base_url.rstrip('/')}/unload")
    except Exception:
        pass
    time.sleep(3)


def transcribe(spec: dict[str, Any], sample: Path, timeout_sec: float) -> dict[str, Any]:
    started = time.perf_counter()
    with sample.open("rb") as handle:
        with httpx.Client(timeout=httpx.Timeout(timeout_sec, connect=30.0)) as client:
            response = client.post(
                f"{spec['url'].rstrip('/')}/transcribe",
                data=spec["data"],
                files={"file": (sample.name, handle, "audio/wav")},
            )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    payload = dict(response.json() or {})
    meta = payload.get("meta_info") if isinstance(payload.get("meta_info"), dict) else {}
    return {
        "wall_seconds": round(elapsed, 3),
        "duration": payload.get("duration"),
        "rtf": round(elapsed / float(payload.get("duration") or 1.0), 4),
        "text_length": len(str(payload.get("text") or "")),
        "cuda_memory": meta.get("cuda_memory"),
    }


def gpu_memory_used_mb() -> int:
    output = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
        text=True,
        encoding="utf-8",
    )
    return int(float(output.strip().splitlines()[0]))


def render_markdown(results: list[dict[str, Any]]) -> str:
    lines = [
        "# ASR Isolated VRAM",
        "",
        "| Service | Baseline MB | After start MB | After first MB | After second MB | Resident delta MB | Second RTF | Torch allocated MB | Torch reserved MB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in results:
        second = item.get("second_transcribe") or {}
        cuda = second.get("cuda_memory") or {}
        lines.append(
            "| {name} | {baseline} | {start} | {first} | {second_used} | {resident} | {rtf} | {allocated} | {reserved} |".format(
                name=item["name"],
                baseline=item["baseline_gpu_used_mb"],
                start=item["after_start_gpu_used_mb"],
                first=item["after_first_gpu_used_mb"],
                second_used=item["after_second_gpu_used_mb"],
                resident=item["steady_resident_delta_mb"],
                rtf=second.get("rtf"),
                allocated=cuda.get("allocated_mb"),
                reserved=cuda.get("reserved_mb"),
            )
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
