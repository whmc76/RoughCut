from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import roughcut.config as config_mod
from roughcut.config import _normalize_settings, get_settings
from roughcut.providers.image_generation import CodexImageGenerationPending, generate_edited_cover_image
from roughcut.providers.reasoning.base import Message, ReasoningResponse
from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider
from roughcut.providers.reasoning.openai_reasoning import OpenAIReasoningProvider


REPORT_ROOT = Path("logs/model-route-benchmarks")


@dataclass(frozen=True)
class ModelSpec:
    key: str
    provider: str
    model: str
    effort: str = "medium"


@dataclass(frozen=True)
class BenchmarkCase:
    slug: str
    task_type: str
    title: str
    system_prompt: str
    user_prompt: str
    json_mode: bool
    max_tokens: int
    temperature: float
    expected_role: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare model performance for RoughCut task routes.")
    parser.add_argument("--report-root", type=Path, default=REPORT_ROOT)
    parser.add_argument("--include-image", action="store_true", help="Also record cover-image route availability.")
    parser.add_argument(
        "--include-openai-image-api",
        action="store_true",
        help="Explicitly probe the OpenAI Images API backend. This is not the Codex built-in imagegen path.",
    )
    parser.add_argument("--image-source", type=Path, default=Path("frame_002.jpg"))
    parser.add_argument("--limit-cases", type=int, default=0)
    return parser.parse_args()


@contextmanager
def temporary_settings(**updates: Any):
    config_mod._settings = None
    settings = get_settings()
    backup = {key: getattr(settings, key) for key in updates}
    try:
        for key, value in updates.items():
            object.__setattr__(settings, key, value)
        _normalize_settings(settings)
        yield settings
    finally:
        for key, value in backup.items():
            object.__setattr__(settings, key, value)
        _normalize_settings(settings)


def _build_provider(spec: ModelSpec):
    with temporary_settings(
        reasoning_provider=spec.provider,
        reasoning_model=spec.model,
        reasoning_effort=spec.effort,
        llm_mode="performance",
        llm_routing_mode="bundled",
    ):
        if spec.provider == "openai":
            return OpenAIReasoningProvider()
        if spec.provider == "minimax":
            return MiniMaxReasoningProvider(model=spec.model)
    raise ValueError(f"Unsupported provider: {spec.provider}")


async def _run_text_case(spec: ModelSpec, case: BenchmarkCase) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        with temporary_settings(
            reasoning_provider=spec.provider,
            reasoning_model=spec.model,
            reasoning_effort=spec.effort,
            llm_mode="performance",
            llm_routing_mode="bundled",
        ):
            provider = _build_provider(spec)
            max_tokens = max(case.max_tokens, 2400) if spec.provider == "minimax" else case.max_tokens
            response = await provider.complete(
                [
                    Message(role="system", content=case.system_prompt),
                    Message(role="user", content=case.user_prompt),
                ],
                temperature=case.temperature,
                max_tokens=max_tokens,
                json_mode=case.json_mode,
            )
        elapsed = round(time.perf_counter() - start, 3)
        evaluation = _evaluate_case(case, response)
        return {
            "model_key": spec.key,
            "provider": spec.provider,
            "configured_model": spec.model,
            "reported_model": response.model,
            "effort": spec.effort,
            "case": case.slug,
            "task_type": case.task_type,
            "expected_role": case.expected_role,
            "latency_sec": elapsed,
            "usage": response.usage,
            "output": response.content,
            "evaluation": evaluation,
        }
    except Exception as exc:
        elapsed = round(time.perf_counter() - start, 3)
        return {
            "model_key": spec.key,
            "provider": spec.provider,
            "configured_model": spec.model,
            "effort": spec.effort,
            "case": case.slug,
            "task_type": case.task_type,
            "expected_role": case.expected_role,
            "latency_sec": elapsed,
            "error": str(exc),
            "evaluation": {"score": 0, "max_score": 1, "pass_rate": 0.0, "checks": [{"name": "no_error", "passed": False}]},
        }


def _evaluate_case(case: BenchmarkCase, response: ReasoningResponse) -> dict[str, Any]:
    text = str(response.content or "").strip()
    payload: Any = None
    checks: list[dict[str, Any]] = []
    if case.json_mode:
        try:
            payload = ReasoningResponse(content=text, usage={}, model="").as_json()
            checks.append({"name": "valid_json", "passed": True})
        except Exception as exc:
            return {
                "score": 0,
                "max_score": 1,
                "pass_rate": 0.0,
                "checks": [{"name": "valid_json", "passed": False, "detail": str(exc)}],
            }
    else:
        checks.append({"name": "non_empty", "passed": bool(text)})

    if case.task_type == "copywriting":
        checks.extend(_evaluate_copywriting(case.slug, payload if isinstance(payload, dict) else {}, text))
    elif case.task_type == "analysis":
        checks.extend(_evaluate_analysis(case.slug, payload if isinstance(payload, dict) else {}, text))
    else:
        checks.append({"name": "known_task_type", "passed": False, "detail": case.task_type})

    score = sum(1 for item in checks if item.get("passed"))
    max_score = len(checks)
    return {
        "score": score,
        "max_score": max_score,
        "pass_rate": round(score / max(max_score, 1), 3),
        "checks": checks,
    }


def _evaluate_copywriting(slug: str, payload: dict[str, Any], text: str) -> list[dict[str, Any]]:
    title = str(payload.get("title") or payload.get("primary_title") or "").strip()
    body = str(payload.get("body") or payload.get("description") or payload.get("tweet") or "").strip()
    tags = payload.get("tags") if isinstance(payload.get("tags"), list) else []
    forbidden = ("已按保守策略", "建议发布前人工核对", "多平台发布素材", "这条视频主要围绕")
    platform_names = {"B站", "小红书", "抖音", "快手", "视频号", "头条号", "YouTube", "X"}
    checks = [
        {"name": "has_body", "passed": len(body) >= 20},
        {"name": "no_internal_boilerplate", "passed": not any(item in text for item in forbidden)},
        {"name": "tags_list_nonempty", "passed": len([tag for tag in tags if str(tag).strip()]) >= 2},
        {"name": "tags_not_duplicate", "passed": len(set(map(str, tags))) == len(tags)},
        {"name": "mentions_subject", "passed": any(token in text for token in ("MOT", "风灵", "音叉", "锆合金"))},
    ]
    if slug != "copy_x":
        checks.append({"name": "title_present", "passed": bool(title)})
        checks.append({"name": "title_not_platform_name", "passed": title not in platform_names})
    if slug == "copy_x":
        checks.append({"name": "x_body_280_limit", "passed": 0 < len(body) <= 280})
        checks.append({"name": "x_no_title_required", "passed": not title})
    if slug == "copy_xiaohongshu":
        checks.append({"name": "xhs_title_20_limit", "passed": 0 < len(title) <= 20})
        checks.append({"name": "xhs_note_length", "passed": len(body) >= 120})
    if slug == "copy_douyin":
        checks.append({"name": "douyin_fast_hook", "passed": len(body) <= 180 and any(mark in body for mark in ("先看", "直接", "这次", "值不值"))})
    if slug == "copy_youtube":
        checks.append({"name": "youtube_description_rich", "passed": len(body) >= 160})
    return checks


def _evaluate_analysis(slug: str, payload: dict[str, Any], text: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if slug == "analysis_profile":
        checks.extend(
            [
                {"name": "brand_mot", "passed": "MOT" in str(payload.get("subject_brand") or "")},
                {"name": "model_mentions_fengling", "passed": "风灵" in str(payload.get("subject_model") or "")},
                {"name": "model_mentions_yincha", "passed": "音叉" in str(payload.get("subject_model") or "")},
                {"name": "material_not_lost", "passed": "锆合金" in text},
                {"name": "has_search_queries", "passed": len(payload.get("search_queries") or []) >= 2},
            ]
        )
    elif slug == "analysis_copy_verify":
        issues = json.dumps(payload.get("issues") or payload, ensure_ascii=False)
        checks.extend(
            [
                {"name": "detects_platform_title_error", "passed": "标题等于平台名" in issues or "platform" in issues.lower()},
                {"name": "detects_boilerplate", "passed": "保守策略" in issues or "模板" in issues},
                {"name": "detects_x_too_long", "passed": "280" in issues or "过长" in issues},
                {"name": "has_actionable_fix", "passed": "rewrite" in issues.lower() or "重写" in issues},
            ]
        )
    elif slug == "analysis_edit_plan":
        checks.extend(
            [
                {"name": "has_keep_segments", "passed": bool(payload.get("keep_segments"))},
                {"name": "has_remove_segments", "passed": bool(payload.get("remove_segments"))},
                {"name": "detects_blurry_segment", "passed": "3" in json.dumps(payload, ensure_ascii=False)},
                {"name": "has_reasoning", "passed": len(str(payload.get("reason") or payload.get("rationale") or "")) >= 20},
            ]
        )
    else:
        checks.append({"name": "non_empty_analysis", "passed": bool(text)})
    return checks


def _build_models() -> list[ModelSpec]:
    return [
        ModelSpec(key="openai_gpt55_low", provider="openai", model="gpt-5.5", effort="low"),
        ModelSpec(key="minimax_m27", provider="minimax", model="MiniMax-M2.7", effort="medium"),
    ]


def _build_cases() -> list[BenchmarkCase]:
    subject = (
        "视频主题：MOT 风灵音叉推牌 锆合金版本开箱。"
        "确定信息：MOT、风灵音叉推牌、锆合金版本、开箱、细节展示、上手体验。"
        "不得编造价格、参数、官方卖点。"
    )
    return [
        BenchmarkCase(
            slug="copy_xiaohongshu",
            task_type="copywriting",
            title="小红书笔记文案",
            expected_role="copy",
            system_prompt="你是中文小红书视频笔记文案策划，只输出 JSON。",
            user_prompt=(
                f"{subject}\n"
                "输出 JSON：{\"title\":\"20字内\",\"body\":\"120-260字真实分享笔记\",\"tags\":[\"话题\"]}。"
                "要求：标题不能是平台名；正文不能出现内部生成说明；像真实玩家分享。"
            ),
            json_mode=True,
            max_tokens=700,
            temperature=0.35,
        ),
        BenchmarkCase(
            slug="copy_douyin",
            task_type="copywriting",
            title="抖音短文案",
            expected_role="copy",
            system_prompt="你是抖音短视频发布文案策划，只输出 JSON。",
            user_prompt=(
                f"{subject}\n"
                "输出 JSON：{\"title\":\"55字内\",\"body\":\"180字内，前半句要有钩子\",\"tags\":[\"标签\"]}。"
                "要求：短、直接、结果先行；不能出现内部生成说明。"
            ),
            json_mode=True,
            max_tokens=500,
            temperature=0.35,
        ),
        BenchmarkCase(
            slug="copy_youtube",
            task_type="copywriting",
            title="YouTube 描述",
            expected_role="copy",
            system_prompt="你是 YouTube 开箱视频 SEO 包装助手，只输出 JSON。",
            user_prompt=(
                f"{subject}\n"
                "输出 JSON：{\"title\":\"100字内\",\"body\":\"160-420字描述，可包含中文和英文关键词但不要混乱夹杂\",\"tags\":[\"tags\"]}。"
                "要求：标题和描述要利于搜索，不能编造参数。"
            ),
            json_mode=True,
            max_tokens=900,
            temperature=0.3,
        ),
        BenchmarkCase(
            slug="copy_x",
            task_type="copywriting",
            title="X 推文",
            expected_role="copy",
            system_prompt="你是 X/Twitter 短帖文案助手，只输出 JSON。",
            user_prompt=(
                f"{subject}\n"
                "输出 JSON：{\"body\":\"280字内推文，不要独立 title\",\"tags\":[\"hashtags\"]}。"
                "要求：像真实短帖，有观点，不要摘要腔。"
            ),
            json_mode=True,
            max_tokens=400,
            temperature=0.35,
        ),
        BenchmarkCase(
            slug="analysis_profile",
            task_type="analysis",
            title="内容画像抽取",
            expected_role="analysis",
            system_prompt="你是严谨的视频内容分析助手，只输出 JSON。",
            user_prompt=(
                "根据文件名和字幕节选抽取事实，不确定留空。\n"
                "输出 JSON：{\"subject_brand\":\"\",\"subject_model\":\"\",\"subject_type\":\"\",\"video_theme\":\"\",\"search_queries\":[\"\"]}\n"
                "文件名：MOT 风灵音叉推牌 锆合金版本.mp4\n"
                "字幕：今天拆的是 MOT 风灵音叉推牌锆合金版本。先看包装，再看本体细节。"
                "这版重点不是讲玄学参数，而是看锆合金版本的质感和开箱观感。"
            ),
            json_mode=True,
            max_tokens=600,
            temperature=0.1,
        ),
        BenchmarkCase(
            slug="analysis_copy_verify",
            task_type="analysis",
            title="文案质量校验",
            expected_role="analysis",
            system_prompt="你是平台发布物料质检助手，只输出 JSON。",
            user_prompt=(
                "检查下面物料问题，输出 JSON：{\"issues\":[{\"platform\":\"\",\"severity\":\"error|warning\",\"message\":\"\",\"fix\":\"\"}]}\n"
                "物料："
                "{\"platform\":\"快手\",\"title\":\"快手\",\"body\":\"这条视频主要围绕 MOT 风灵音叉推牌展开，已按保守策略生成多平台发布素材，建议发布前人工核对具体型号与参数。\",\"tags\":[\"EDC\",\"EDC\"]}\n"
                "{\"platform\":\"X\",\"body\":\"这条视频主要围绕 MOT 风灵音叉推牌展开，已按保守策略生成多平台发布素材，建议发布前人工核对具体型号与参数。"
                "这里继续补很多无信息量内容让推文超过平台适合长度，仍然没有观点，没有短帖节奏。\",\"tags\":[]}"
            ),
            json_mode=True,
            max_tokens=800,
            temperature=0.1,
        ),
        BenchmarkCase(
            slug="analysis_edit_plan",
            task_type="analysis",
            title="剪辑逻辑判断",
            expected_role="analysis",
            system_prompt="你是短视频剪辑逻辑分析助手，只输出 JSON。",
            user_prompt=(
                "根据片段摘要判断保留/删除。输出 JSON：{\"keep_segments\":[1],\"remove_segments\":[3],\"reason\":\"\"}\n"
                "片段：1 开箱露出包装和主体；2 近景展示锆合金版本细节；3 画面失焦且口播重复上一句；4 上手转动展示声音和手感。"
            ),
            json_mode=True,
            max_tokens=500,
            temperature=0.1,
        ),
    ]


async def _run_image_probe(report_dir: Path, source_path: Path, *, include_openai_image_api: bool = False) -> list[dict[str, Any]]:
    if not source_path.exists():
        return [{"backend": "codex_builtin", "model": "codex_imagegen", "error": f"source image not found: {source_path}"}]
    results: list[dict[str, Any]] = []

    codex_request_path = report_dir / "codex_builtin_imagegen_request.json"
    start = time.perf_counter()
    try:
        with temporary_settings(intelligent_copy_cover_image_backend="codex_builtin"):
            await generate_edited_cover_image(
                source_image_path=source_path,
                output_path=report_dir / "codex_builtin_cover.jpg",
                request_path=codex_request_path,
                prompt=(
                    "基于参考图生成视频封面底图，保留主体，不画文字，增强清晰度和质感，"
                    "预留标题安全区。"
                ),
                width=1280,
                height=720,
            )
    except CodexImageGenerationPending as exc:
        results.append(
            {
                "backend": "codex_builtin",
                "model": "codex_imagegen",
                "latency_sec": round(time.perf_counter() - start, 3),
                "status": "pending_external_codex_imagegen",
                "metadata": exc.metadata,
                "note": "Recorded a Codex built-in image_gen request manifest; this script does not benchmark the App-only built-in image tool.",
            }
        )
    except Exception as exc:
        results.append(
            {
                "backend": "codex_builtin",
                "model": "codex_imagegen",
                "latency_sec": round(time.perf_counter() - start, 3),
                "status": "error",
                "error": str(exc),
            }
        )

    if not include_openai_image_api:
        results.append(
            {
                "backend": "openai_images_api",
                "model": "image2/gpt-image-1",
                "status": "skipped",
                "note": "Direct OpenAI Images API backend was not probed. Pass --include-openai-image-api to test it explicitly.",
            }
        )
        return results

    for model in ("image2", "gpt-image-1"):
        output_path = report_dir / f"image_probe_{model.replace('/', '_')}.jpg"
        start = time.perf_counter()
        try:
            with temporary_settings(
                intelligent_copy_cover_image_backend="openai_images_api",
                intelligent_copy_cover_image_model=model,
            ):
                metadata = await generate_edited_cover_image(
                    source_image_path=source_path,
                    output_path=output_path,
                    prompt=(
                        "基于参考图生成视频封面底图，保留主体，不画文字，增强清晰度和质感，"
                        "预留标题安全区。"
                    ),
                    width=1280,
                    height=720,
                )
            results.append(
                {
                    "backend": "openai_images_api",
                    "model": model,
                    "latency_sec": round(time.perf_counter() - start, 3),
                    "output_path": str(output_path),
                    "metadata": metadata,
                    "status": "ok",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "backend": "openai_images_api",
                    "model": model,
                    "latency_sec": round(time.perf_counter() - start, 3),
                    "status": "error",
                    "error": str(exc),
                }
            )
    return results


def _summarize_text(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for row in results:
        key = str(row.get("model_key") or "")
        bucket = summary.setdefault(
            key,
            {
                "provider": row.get("provider"),
                "configured_model": row.get("configured_model"),
                "cases": 0,
                "errors": 0,
                "score": 0,
                "max_score": 0,
                "latency_sec": 0.0,
                "by_task_type": {},
            },
        )
        evaluation = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
        bucket["cases"] += 1
        if row.get("error"):
            bucket["errors"] += 1
        bucket["score"] += int(evaluation.get("score") or 0)
        bucket["max_score"] += int(evaluation.get("max_score") or 0)
        bucket["latency_sec"] += float(row.get("latency_sec") or 0.0)
        task_bucket = bucket["by_task_type"].setdefault(
            row.get("task_type") or "unknown",
            {"cases": 0, "score": 0, "max_score": 0, "latency_sec": 0.0},
        )
        task_bucket["cases"] += 1
        task_bucket["score"] += int(evaluation.get("score") or 0)
        task_bucket["max_score"] += int(evaluation.get("max_score") or 0)
        task_bucket["latency_sec"] += float(row.get("latency_sec") or 0.0)

    for bucket in summary.values():
        bucket["pass_rate"] = round(bucket["score"] / max(bucket["max_score"], 1), 3)
        bucket["avg_latency_sec"] = round(bucket["latency_sec"] / max(bucket["cases"], 1), 3)
        for task_bucket in bucket["by_task_type"].values():
            task_bucket["pass_rate"] = round(task_bucket["score"] / max(task_bucket["max_score"], 1), 3)
            task_bucket["avg_latency_sec"] = round(task_bucket["latency_sec"] / max(task_bucket["cases"], 1), 3)
    return summary


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Model Route Performance Comparison",
        "",
        f"- created_at: {report.get('created_at')}",
        f"- text_case_count: {report.get('text_case_count')}",
        f"- image_probe_enabled: {bool(report.get('image_results'))}",
        "",
        "## Summary",
        "",
    ]
    for key, item in (report.get("text_summary") or {}).items():
        lines.extend(
            [
                f"### {key}",
                "",
                f"- provider/model: {item.get('provider')} / {item.get('configured_model')}",
                f"- pass_rate: {item.get('pass_rate')} ({item.get('score')}/{item.get('max_score')})",
                f"- avg_latency_sec: {item.get('avg_latency_sec')}",
                f"- errors: {item.get('errors')}",
            ]
        )
        for task_type, task in (item.get("by_task_type") or {}).items():
            lines.append(
                f"- {task_type}: pass_rate={task.get('pass_rate')} avg_latency={task.get('avg_latency_sec')}s"
            )
        lines.append("")

    if report.get("image_results"):
        lines.extend(["## Image Probe", ""])
        for row in report.get("image_results") or []:
            lines.append(
                f"- {row.get('backend') or '-'} / {row.get('model')}: {row.get('status')} | latency={row.get('latency_sec')}s | {row.get('error') or row.get('output_path') or row.get('note') or ''}"
            )
        lines.append("")

    lines.extend(["## Per Case", ""])
    for row in report.get("text_results") or []:
        evaluation = row.get("evaluation") or {}
        lines.extend(
            [
                f"### {row.get('model_key')} / {row.get('case')}",
                "",
                f"- task_type: {row.get('task_type')}",
                f"- pass_rate: {evaluation.get('pass_rate')} ({evaluation.get('score')}/{evaluation.get('max_score')})",
                f"- latency_sec: {row.get('latency_sec')}",
                f"- error: {row.get('error') or '-'}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


async def main() -> None:
    args = parse_args()
    report_dir = args.report_root / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    models = _build_models()
    cases = _build_cases()
    if args.limit_cases and args.limit_cases > 0:
        cases = cases[: args.limit_cases]

    text_results: list[dict[str, Any]] = []
    for spec in models:
        for case in cases:
            print(f"[text] model={spec.key} case={case.slug}", flush=True)
            text_results.append(await _run_text_case(spec, case))

    image_results = []
    if args.include_image:
        image_results = await _run_image_probe(
            report_dir,
            args.image_source,
            include_openai_image_api=bool(args.include_openai_image_api),
        )

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_dir": str(report_dir),
        "models": [spec.__dict__ for spec in models],
        "text_case_count": len(cases),
        "text_summary": _summarize_text(text_results),
        "text_results": text_results,
        "image_results": image_results,
    }
    json_path = report_dir / "model_route_performance_comparison.json"
    md_path = report_dir / "model_route_performance_comparison.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": report["text_summary"], "image": image_results}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
