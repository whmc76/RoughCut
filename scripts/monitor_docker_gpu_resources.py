from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sample Docker container stats plus whole-GPU utilization.")
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--duration-sec", type=float, default=0.0, help="0 means run until interrupted.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with args.output.open("w", encoding="utf-8") as handle:
        while True:
            row = {
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "elapsed_sec": round(time.perf_counter() - started, 3),
                "container": args.container,
                "docker": docker_stats(args.container),
                "gpu": gpu_stats(),
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            if args.duration_sec > 0 and time.perf_counter() - started >= args.duration_sec:
                break
            time.sleep(args.interval_sec)


def docker_stats(container: str) -> dict[str, Any]:
    try:
        raw = run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container], timeout=20)
        data = json.loads(raw.strip())
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    mem_used, mem_limit = parse_mem_usage(str(data.get("MemUsage") or ""))
    return {
        "name": data.get("Name"),
        "cpu_percent": parse_percent(data.get("CPUPerc")),
        "mem_percent": parse_percent(data.get("MemPerc")),
        "mem_used_mib": mem_used,
        "mem_limit_mib": mem_limit,
        "net_io": data.get("NetIO"),
        "block_io": data.get("BlockIO"),
        "pids": parse_int(data.get("PIDs")),
    }


def gpu_stats() -> dict[str, Any]:
    try:
        raw = run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            timeout=20,
        )
        first = raw.strip().splitlines()[0]
        used, total, util = [part.strip() for part in first.split(",")]
        return {
            "memory_used_mib": parse_float(used),
            "memory_total_mib": parse_float(total),
            "utilization_gpu_percent": parse_float(util),
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def parse_mem_usage(value: str) -> tuple[float | None, float | None]:
    if " / " not in value:
        return None, None
    left, right = value.split(" / ", 1)
    return parse_size_mib(left), parse_size_mib(right)


def parse_size_mib(value: str) -> float | None:
    text = value.strip().replace(" ", "")
    units = [
        ("KiB", 1 / 1024),
        ("MiB", 1),
        ("GiB", 1024),
        ("TiB", 1024 * 1024),
        ("kB", 1000 / 1024 / 1024),
        ("MB", 1000 / 1024),
        ("GB", 1000 * 1000 / 1024),
    ]
    for suffix, factor in units:
        if text.endswith(suffix):
            number = parse_float(text[: -len(suffix)])
            return round(number * factor, 3) if number is not None else None
    return parse_float(text)


def parse_percent(value: Any) -> float | None:
    return parse_float(str(value or "").strip().rstrip("%"))


def parse_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def run(cmd: list[str], *, timeout: int) -> str:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


if __name__ == "__main__":
    main()
