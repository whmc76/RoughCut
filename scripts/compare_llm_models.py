from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import roughcut.config as config_mod
from roughcut.config import get_settings
from roughcut.providers.reasoning.base import Message, ReasoningResponse
from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider
from roughcut.providers.reasoning.ollama_reasoning import OllamaReasoningProvider


REPORT_DIR = Path("logs/llm-benchmarks")


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    provider: str
    model: str
    extra_settings: dict[str, Any]


@dataclass(frozen=True)
class BenchmarkCase:
    slug: str
    title: str
    system_prompt: str
    user_prompt: str
    json_mode: bool
    max_tokens: int
    temperature: float
    expectations: dict[str, Any]


def _configure_settings(**overrides: Any):
    config_mod._settings = None
    settings = get_settings()
    for key, value in overrides.items():
        object.__setattr__(settings, key, value)
    return settings


def _build_provider(spec: ProviderSpec):
    settings = _configure_settings(
        reasoning_provider=spec.provider,
        reasoning_model=spec.model,
        **spec.extra_settings,
    )
    if spec.provider == "minimax":
        return MiniMaxReasoningProvider(), settings
    if spec.provider == "ollama":
        return OllamaReasoningProvider(), settings
    raise ValueError(f"Unsupported provider: {spec.provider}")


def _score_case(case: BenchmarkCase, output: str) -> dict[str, Any]:
    text = output.strip()
    result: dict[str, Any] = {
        "json_valid": False,
        "checks": [],
        "score": 0,
        "max_score": 0,
    }

    payload: Any = None
    if case.json_mode:
        try:
            payload = ReasoningResponse(content=text, usage={}, model="").as_json()
            result["json_valid"] = True
        except Exception as exc:
            result["error"] = f"invalid_json: {exc}"
            return result

    for check in case.expectations.get("contains_all", []):
        result["max_score"] += 1
        passed = check.lower() in text.lower()
        result["checks"].append({"type": "contains", "target": check, "passed": passed})
        if passed:
            result["score"] += 1

    for check in case.expectations.get("not_contains", []):
        result["max_score"] += 1
        passed = check.lower() not in text.lower()
        result["checks"].append({"type": "not_contains", "target": check, "passed": passed})
        if passed:
            result["score"] += 1

    if payload is not None:
        for field in case.expectations.get("required_fields", []):
            result["max_score"] += 1
            passed = field in payload and payload[field] not in ("", [], {}, None)
            result["checks"].append({"type": "required_field", "target": field, "passed": passed})
            if passed:
                result["score"] += 1

        for field, expected in case.expectations.get("equals", {}).items():
            result["max_score"] += 1
            passed = payload.get(field) == expected
            result["checks"].append(
                {"type": "equals", "target": field, "expected": expected, "actual": payload.get(field), "passed": passed}
            )
            if passed:
                result["score"] += 1

        for field, expected_items in case.expectations.get("field_contains_all", {}).items():
            target = payload.get(field)
            if isinstance(target, list):
                haystack = " ".join(str(item) for item in target)
            else:
                haystack = str(target or "")
            for expected in expected_items:
                result["max_score"] += 1
                passed = expected.lower() in haystack.lower()
                result["checks"].append(
                    {"type": "field_contains", "target": field, "expected": expected, "passed": passed}
                )
                if passed:
                    result["score"] += 1

        for field, limit in case.expectations.get("field_max_len", {}).items():
            value = payload.get(field)
            if isinstance(value, list):
                values = [str(item) for item in value]
            elif isinstance(value, dict):
                values = [str(item) for item in value.values()]
            else:
                values = [str(value or "")]
            for item in values:
                result["max_score"] += 1
                passed = len(item) <= limit
                result["checks"].append(
                    {"type": "field_max_len", "target": field, "limit": limit, "actual_len": len(item), "passed": passed}
                )
                if passed:
                    result["score"] += 1

    return result


async def _run_case(spec: ProviderSpec, case: BenchmarkCase) -> dict[str, Any]:
    provider, _ = _build_provider(spec)
    start = time.perf_counter()
    try:
        response = await provider.complete(
            [
                Message(role="system", content=case.system_prompt),
                Message(role="user", content=case.user_prompt),
            ],
            temperature=case.temperature,
            max_tokens=case.max_tokens,
            json_mode=case.json_mode,
        )
        latency = time.perf_counter() - start
        scored = _score_case(case, response.content)
        return {
            "provider": spec.name,
            "case": case.slug,
            "title": case.title,
            "latency_sec": round(latency, 3),
            "model": response.model,
            "usage": response.usage,
            "output": response.content,
            "evaluation": scored,
        }
    except Exception as exc:
        latency = time.perf_counter() - start
        return {
            "provider": spec.name,
            "case": case.slug,
            "title": case.title,
            "latency_sec": round(latency, 3),
            "error": str(exc),
            "evaluation": {"score": 0, "max_score": 0, "checks": []},
        }


def _build_cases() -> list[BenchmarkCase]:
    return [
        BenchmarkCase(
            slug="product_profile_limited",
            title="限定版主体识别",
            system_prompt="你是中文 EDC 开箱视频内容研究助手，只能根据给定信息做谨慎判断，输出严格 JSON。",
            user_prompt=(
                "根据下面的文件名和口播节选，识别主体品牌、型号/版本、主体类型、视频主题和适合的工作流预设。"
                "不确定就留空，不要编造。\n"
                "输出 JSON："
                '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"","preset_name":"","search_queries":[]}\n'
                "文件名：FAS刀帕马年限定版.mp4\n"
                "口播节选：这把是 FAS 的刀帕马年限定版，包装就已经和常规版不一样。"
                "正面这块纹理做得很细，拿在手里第一感觉就是限定味道很足。"
                "它本体还是刀帕这套结构，但是这次把马年元素和细节都压进去了。"
            ),
            json_mode=True,
            max_tokens=500,
            temperature=0.1,
            expectations={
                "required_fields": ["subject_brand", "subject_model", "subject_type", "preset_name"],
                "field_contains_all": {
                    "subject_brand": ["FAS"],
                    "subject_model": ["刀帕", "马年", "限定"],
                    "subject_type": ["刀"],
                },
                "equals": {"preset_name": "unboxing_limited"},
            },
        ),
        BenchmarkCase(
            slug="product_profile_upgrade",
            title="升级版主体识别",
            system_prompt="你是中文 EDC 开箱视频内容研究助手，只能根据给定信息做谨慎判断，输出严格 JSON。",
            user_prompt=(
                "根据下面的文件名和口播节选，识别主体品牌、型号/版本、主体类型、视频主题和适合的工作流预设。"
                "不确定就留空，不要编造。\n"
                "输出 JSON："
                '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"","preset_name":"","search_queries":[]}\n'
                "文件名：FAS刀帕战术版升级.mp4\n"
                "口播节选：今天看的是 FAS 刀帕战术版升级。"
                "这次不是简单换色，锁定和细节位都做了改。"
                "如果你之前玩过老版，这一代上手就能感觉出差别。"
            ),
            json_mode=True,
            max_tokens=500,
            temperature=0.1,
            expectations={
                "required_fields": ["subject_brand", "subject_model", "subject_type", "preset_name"],
                "field_contains_all": {
                    "subject_brand": ["FAS"],
                    "subject_model": ["刀帕", "战术", "升级"],
                    "subject_type": ["刀"],
                },
                "equals": {"preset_name": "unboxing_upgrade"},
            },
        ),
        BenchmarkCase(
            slug="subtitle_polish",
            title="字幕矫正与润色",
            system_prompt="你是严谨的中文开箱视频字幕审校助手，只输出 JSON。",
            user_prompt=(
                "把下面的 ASR 字幕修正成更适合烧录的中文短句。"
                "要求：不改变原意，不编造参数，品牌型号必须正确，每条尽量不超过 22 个汉字。"
                "\n输出 JSON：{\"items\":[{\"index\":1,\"text_final\":\"...\"}]}\n"
                "视频主体：{\"subject_brand\":\"FAS\",\"subject_model\":\"刀帕马年限定版\",\"subject_type\":\"EDC折刀\"}\n"
                "待处理字幕："
                "[{\"index\":1,\"text\":\"这个fas到怕马年限定版外观真的挺炸的\"},"
                "{\"index\":2,\"text\":\"它和普通版拿到手里那个感觉完全不太一样\"},"
                "{\"index\":3,\"text\":\"这一刀细节位给的比我预期更满\"}]"
            ),
            json_mode=True,
            max_tokens=800,
            temperature=0.1,
            expectations={
                "required_fields": ["items"],
                "contains_all": ["FAS", "刀帕", "马年限定版"],
                "not_contains": ["到怕"],
            },
        ),
        BenchmarkCase(
            slug="cover_title",
            title="封面三段标题生成",
            system_prompt="你是中文 EDC 开箱封面策划助手，只输出 JSON。",
            user_prompt=(
                "根据视频信息生成封面三段标题。"
                "要求：上中下三段都适合封面叠字，简短、硬核、不浮夸。"
                "品牌和型号要准确，避免空喊。"
                "\n输出 JSON：{\"cover_title\":{\"top\":\"\",\"main\":\"\",\"bottom\":\"\"}}\n"
                "视频信息：{\"subject_brand\":\"FAS\",\"subject_model\":\"刀帕战术版升级\",\"subject_type\":\"EDC折刀\",\"video_theme\":\"战术版升级开箱与上手\"}"
            ),
            json_mode=True,
            max_tokens=300,
            temperature=0.2,
            expectations={
                "required_fields": ["cover_title"],
                "field_contains_all": {"cover_title": ["FAS", "刀帕"]},
                "field_max_len": {"cover_title": 12},
            },
        ),
        BenchmarkCase(
            slug="preset_selection",
            title="预设选择准确性",
            system_prompt="你是 RoughCut 的剪辑工作流助手，只输出 JSON。",
            user_prompt=(
                "根据内容简介选择最合适的 preset_name。"
                "候选值只有：unboxing_default, unboxing_limited, unboxing_upgrade, edc_tactical。"
                "输出 JSON：{\"preset_name\":\"\",\"reason\":\"\"}\n"
                "内容简介：这是 FAS 刀帕战术版升级的开箱，重点讲锁定结构、手感、做工和这次改版是否真的有价值。"
            ),
            json_mode=True,
            max_tokens=200,
            temperature=0.1,
            expectations={
                "required_fields": ["preset_name", "reason"],
                "equals": {"preset_name": "unboxing_upgrade"},
            },
        ),
    ]


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for row in results:
        name = row["provider"]
        bucket = summary.setdefault(name, {"score": 0, "max_score": 0, "latency_sec": 0.0, "cases": 0})
        evaluation = row.get("evaluation", {})
        bucket["score"] += evaluation.get("score", 0)
        bucket["max_score"] += evaluation.get("max_score", 0)
        bucket["latency_sec"] += row.get("latency_sec", 0.0)
        bucket["cases"] += 1
    for name, bucket in summary.items():
        bucket["avg_latency_sec"] = round(bucket["latency_sec"] / max(bucket["cases"], 1), 3)
        bucket["pass_rate"] = round(bucket["score"] / max(bucket["max_score"], 1), 3)
    return summary


async def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    cases = _build_cases()
    providers = [
        ProviderSpec(
            name="MiniMax-M2.5",
            provider="minimax",
            model="MiniMax-M2.5",
            extra_settings={},
        ),
        ProviderSpec(
            name="qwen3.5:9b",
            provider="ollama",
            model="qwen3.5:9b",
            extra_settings={},
        ),
    ]

    results: list[dict[str, Any]] = []
    for spec in providers:
        for case in cases:
            results.append(await _run_case(spec, case))

    summary = _summarize(results)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": results,
        "summary": summary,
    }
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = REPORT_DIR / f"llm_compare_{timestamp}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
