from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import roughcut.config as config_mod
from roughcut.config import get_settings
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message


REPORT_DIR = Path("logs/llm-benchmarks")


@dataclass(frozen=True)
class BenchmarkCase:
    slug: str
    json_mode: bool
    max_tokens: int
    temperature: float
    messages: list[Message]


def _build_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            slug="short",
            json_mode=False,
            max_tokens=128,
            temperature=0.2,
            messages=[
                Message(role="system", content="You are a concise assistant."),
                Message(role="user", content="用一句话解释什么是自动剪辑。"),
            ],
        ),
        BenchmarkCase(
            slug="json",
            json_mode=True,
            max_tokens=256,
            temperature=0.1,
            messages=[
                Message(role="system", content="Return valid JSON only."),
                Message(
                    role="user",
                    content=(
                        "输出一个JSON对象，字段包括 name, purpose, steps，其中steps是3个字符串。"
                        "主题是RoughCut视频处理流程。"
                    ),
                ),
            ],
        ),
        BenchmarkCase(
            slug="long",
            json_mode=False,
            max_tokens=768,
            temperature=0.2,
            messages=[
                Message(role="system", content="You are a concise assistant."),
                Message(
                    role="user",
                    content=(
                        "请用中文写一段约400到500字的说明，介绍自动剪辑系统在口播视频生产中的价值、"
                        "常见步骤和主要风险控制点。"
                    ),
                ),
            ],
        ),
    ]


def _clean_preview(text: str, limit: int = 160) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    return cleaned[:limit]


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _format_case_summary(summary: dict[str, Any]) -> str:
    rows = ["Case    Avg(s)  P50(s)  Min(s)  Max(s)  AvgOutTok  Tok/s"]
    for slug, item in summary.items():
        rows.append(
            f"{slug:<7} "
            f"{item['avg_elapsed_sec']:>6.3f}  "
            f"{item.get('p50_elapsed_sec', item['avg_elapsed_sec']):>6.3f}  "
            f"{item['min_elapsed_sec']:>6.3f}  "
            f"{item['max_elapsed_sec']:>6.3f}  "
            f"{item['avg_completion_tokens']:>9}  "
            f"{str(item.get('avg_tokens_per_sec', '-')):>5}"
        )
    return "\n".join(rows)


def _format_concurrency_summary(probe: dict[str, Any]) -> str:
    rows = [
        (
            f"Concurrency probe: case={probe['case']} "
            f"concurrency={probe['concurrency']} wall={probe['wall_elapsed_sec']:.3f}s"
        ),
        "Idx  Elapsed(s)  OutTok  Tok/s",
    ]
    for item in probe["runs"]:
        rows.append(
            f"{item['idx']:>3}  {item['elapsed_sec']:>10.3f}  "
            f"{item['completion_tokens']:>6}  {str(item.get('tokens_per_sec', '-')):>5}"
        )
    return "\n".join(rows)


def _configure_settings(provider: str | None, model: str | None) -> dict[str, Any]:
    config_mod._settings = None
    settings = get_settings()
    if provider:
        object.__setattr__(settings, "reasoning_provider", provider)
    if model:
        object.__setattr__(settings, "reasoning_model", model)
    return {
        "provider": settings.active_reasoning_provider,
        "model": settings.active_reasoning_model,
        "base_url": getattr(settings, f"{settings.active_reasoning_provider}_base_url", ""),
    }


async def _run_case(case: BenchmarkCase) -> dict[str, Any]:
    provider = get_reasoning_provider()
    started = time.perf_counter()
    response = await provider.complete(
        case.messages,
        temperature=case.temperature,
        max_tokens=case.max_tokens,
        json_mode=case.json_mode,
    )
    elapsed = time.perf_counter() - started
    usage = response.usage or {}
    completion_tokens = usage.get("completion_tokens") or 0
    return {
        "case": case.slug,
        "elapsed_sec": round(elapsed, 3),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": completion_tokens,
        "tokens_per_sec": round(completion_tokens / elapsed, 2) if completion_tokens else None,
        "response_chars": len(response.content or ""),
        "model": response.model,
        "preview": _clean_preview(response.content or ""),
    }


async def _run_concurrency_probe(case: BenchmarkCase, concurrency: int) -> dict[str, Any]:
    async def one(idx: int) -> dict[str, Any]:
        row = await _run_case(case)
        row["idx"] = idx
        return row

    started = time.perf_counter()
    rows = await asyncio.gather(*(one(idx) for idx in range(concurrency)))
    wall_elapsed = time.perf_counter() - started
    return {
        "case": case.slug,
        "concurrency": concurrency,
        "wall_elapsed_sec": round(wall_elapsed, 3),
        "runs": rows,
    }


def _summarize_case(rows: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed_values = [float(row["elapsed_sec"]) for row in rows]
    token_speeds = [float(row["tokens_per_sec"]) for row in rows if row.get("tokens_per_sec") is not None]
    completion_tokens = [int(row["completion_tokens"]) for row in rows]
    summary = {
        "runs": len(rows),
        "avg_elapsed_sec": round(statistics.mean(elapsed_values), 3),
        "min_elapsed_sec": round(min(elapsed_values), 3),
        "max_elapsed_sec": round(max(elapsed_values), 3),
        "avg_completion_tokens": round(statistics.mean(completion_tokens), 2),
        "avg_tokens_per_sec": round(statistics.mean(token_speeds), 2) if token_speeds else None,
    }
    if len(elapsed_values) >= 2:
        summary["p50_elapsed_sec"] = round(statistics.median(elapsed_values), 3)
    return summary


async def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(description="Benchmark RoughCut reasoning provider performance.")
    parser.add_argument("--provider", default=None, help="Override reasoning provider")
    parser.add_argument("--model", default=None, help="Override reasoning model")
    parser.add_argument("--rounds", type=int, default=3, help="Sequential rounds per case")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrency probe size for the short case")
    args = parser.parse_args()

    settings_info = _configure_settings(args.provider, args.model)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    cases = _build_cases()
    all_results: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}

    for case in cases:
        rows: list[dict[str, Any]] = []
        for _ in range(max(1, args.rounds)):
            rows.append(await _run_case(case))
        all_results.extend(rows)
        summaries[case.slug] = _summarize_case(rows)

    concurrency_probe = await _run_concurrency_probe(cases[0], max(1, args.concurrency))

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": settings_info,
        "args": vars(args),
        "cases": [asdict(case) for case in cases],
        "results": all_results,
        "summary": summaries,
        "concurrency_probe": concurrency_probe,
    }
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = REPORT_DIR / f"reasoning_benchmark_{timestamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Report: {out_path}")
    print(
        "Settings: "
        f"provider={settings_info['provider']} "
        f"model={settings_info['model']} "
        f"base_url={settings_info['base_url']}"
    )
    print()
    print(_format_case_summary(summaries))
    print()
    print(_format_concurrency_summary(concurrency_probe))
    print()
    print("JSON:")
    print(json.dumps({"report": str(out_path), "settings": settings_info}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
