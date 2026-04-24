from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.db.models import Artifact
from roughcut.db.session import get_session_factory


_GLOBAL_POLLUTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("knife_drift_flashlight_model", re.compile(r"(?:折刀帕|刀)(?:幺七|幺7|一七|17|二三|23|三七|37)|EDC(?:17|23|37)折刀(?:帕)?|EDC17刀(?:幺七|幺7|一七|17)|EDC23刀(?:二三|23)|EDC37刀(?:三七|37)")),
    ("nonsense_fish_octopus", re.compile(r"鱼头的小章鱼")),
    ("nonsense_new_car", re.compile(r"新品小车")),
    ("duplicate_brand_run", re.compile(r"(狐蝠工业){2,}|(NITECORE){2,}|(OLIGHT){2,}", re.IGNORECASE)),
)

_FINDING_POLICY: dict[str, dict[str, str]] = {
    "knife_drift_flashlight_model": {
        "class": "semantic_contamination",
        "action": "manual_review_required",
        "note": "跨语义串台，禁止自动改写成另一类商品",
    },
    "cross_domain_drift": {
        "class": "semantic_contamination",
        "action": "manual_review_required",
        "note": "跨品类词汇污染，必须人工确认",
    },
    "nonsense_fish_octopus": {
        "class": "fabricated_content",
        "action": "manual_review_required",
        "note": "出现无中生有内容，不允许自动脑补修复",
    },
    "nonsense_new_car": {
        "class": "fabricated_content",
        "action": "manual_review_required",
        "note": "出现无中生有内容，不允许自动脑补修复",
    },
    "duplicate_brand_run": {
        "class": "garbled_output",
        "action": "manual_review_required",
        "note": "品牌词重复堆叠，需要人工核对原文",
    },
    "repeated_phrase": {
        "class": "garbled_output",
        "action": "review_recommended",
        "note": "重复短语偏多，优先回看原字幕切分",
    },
}

_CATEGORY_RULES: dict[str, dict[str, tuple[str, ...]]] = {
    "flashlight": {
        "forbidden": ("折刀", "折刀帕", "背夹", "柄材", "钢材", "刀鞘", "双肩包", "机能包"),
    },
    "knife": {
        "forbidden": ("手电", "电筒", "流明", "灯珠", "泛光", "聚光", "双肩包", "机能包"),
    },
    "bag": {
        "forbidden": ("折刀", "折刀帕", "开合", "锁定", "背夹", "柄材", "钢材", "手电", "电筒", "流明", "灯珠"),
    },
}
_BAG_CARRY_CONTEXT_TOKENS: tuple[str, ...] = (
    "包里",
    "包内",
    "这个包",
    "这包",
    "双肩包",
    "机能包",
    "胸包",
    "斜挎包",
    "通勤包",
    "收纳",
    "分仓",
    "挂点",
)
_BAG_CARRY_ACTION_TOKENS: tuple[str, ...] = (
    "放",
    "装",
    "塞",
    "带",
    "收纳",
    "装下",
    "放下",
    "背负",
)
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit subtitle content pollution for a batch report.")
    parser.add_argument("--batch-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def _detect_category(source_name: str, content_profile: dict[str, Any] | None) -> str:
    source = str(source_name or "")
    profile = content_profile or {}
    blob = " ".join(
        str(profile.get(key) or "")
        for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary")
    )
    merged = f"{source} {blob}".lower()
    if any(token in merged for token in ("手电", "nitecore", "奈特科尔", "olight", "傲雷", "edc17", "edc23", "edc37", "掠夺者")):
        return "flashlight"
    if any(token in merged for token in ("狐蝠", "foxbat", "阵风", "双肩包", "机能包", "背负", "收纳")):
        return "bag"
    return "knife"


def _read_srt_lines(path: str) -> list[str]:
    if not path:
        return []
    file_path = Path(path)
    if not file_path.exists():
        return []
    content = file_path.read_text(encoding="utf-8", errors="ignore")
    return [
        line.strip()
        for line in content.splitlines()
        if line.strip() and "-->" not in line and not line.strip().isdigit()
    ]


def _read_excerpt_lines(excerpt: str) -> list[str]:
    if not excerpt:
        return []
    lines: list[str] = []
    for raw_line in excerpt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^\[[^\]]+\]\s*", "", line)
        if line:
            lines.append(line)
    return lines


def _find_nested_string(obj: Any, key: str) -> str:
    if isinstance(obj, dict):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for nested in obj.values():
            found = _find_nested_string(nested, key)
            if found:
                return found
    if isinstance(obj, list):
        for item in obj:
            found = _find_nested_string(item, key)
            if found:
                return found
    return ""


def _resolve_subtitle_lines(job: dict[str, Any], render_outputs: dict[str, Any]) -> tuple[list[str], str, str]:
    srt_path = (
        str(render_outputs.get("packaged_srt") or "")
        or str(render_outputs.get("plain_srt") or "")
        or str(render_outputs.get("ai_effect_srt") or "")
    ).strip()
    srt_lines = _read_srt_lines(srt_path)
    if srt_lines:
        return srt_lines, "srt", srt_path

    transcript_excerpt = _find_nested_string(job, "transcript_excerpt")
    excerpt_lines = _read_excerpt_lines(transcript_excerpt)
    if excerpt_lines:
        return excerpt_lines, "transcript_excerpt", ""

    return [], "missing", ""


def _severity_from_counts(*, blocking_count: int, warning_count: int) -> str:
    if blocking_count > 0:
        return "critical"
    if warning_count >= 3:
        return "high"
    if warning_count > 0:
        return "medium"
    return "low"


def _enrich_finding(item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "")
    policy = _FINDING_POLICY.get(kind, {})
    enriched = dict(item)
    enriched["finding_class"] = policy.get("class", "unspecified")
    enriched["recommended_action"] = policy.get("action", "review_recommended")
    enriched["policy_note"] = policy.get("note", "")
    return enriched


def _is_bag_carry_context(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    has_bag_context = any(token in text for token in _BAG_CARRY_CONTEXT_TOKENS)
    has_carry_action = any(token in text for token in _BAG_CARRY_ACTION_TOKENS)
    has_listed_contents = any(token in text for token in ("包括", "比如", "像是", "什么的", "工艺钳", "工具钳", "充电宝"))
    return has_bag_context and (has_carry_action or has_listed_contents)


def _filter_cross_domain_tokens(category: str, line: str, tokens: list[str]) -> list[str]:
    if category == "bag" and _is_bag_carry_context(line):
        return [token for token in tokens if token not in {"手电", "电筒", "流明", "灯珠"}]
    return tokens


async def _load_render_outputs_by_job(job_ids: list[str]) -> dict[str, dict[str, Any]]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(Artifact.job_id, Artifact.data_json)
                .where(Artifact.artifact_type == "render_outputs", Artifact.job_id.in_(job_ids))
                .order_by(Artifact.created_at.desc())
            )
        ).all()
    result: dict[str, dict[str, Any]] = {}
    for job_id, data_json in rows:
        key = str(job_id)
        if key in result:
            continue
        result[key] = dict(data_json or {})
    return result


def _audit_job(job: dict[str, Any], render_outputs: dict[str, Any]) -> dict[str, Any]:
    category = _detect_category(str(job.get("source_name") or ""), job.get("content_profile") if isinstance(job.get("content_profile"), dict) else {})
    lines, subtitle_source, subtitle_path = _resolve_subtitle_lines(job, render_outputs)
    blocking_findings: list[dict[str, Any]] = []
    warning_findings: list[dict[str, Any]] = []

    forbidden_tokens = _CATEGORY_RULES.get(category, {}).get("forbidden", ())
    for line_no, line in enumerate(lines, start=1):
        matched_forbidden = [token for token in forbidden_tokens if token in line]
        matched_forbidden = _filter_cross_domain_tokens(category, line, matched_forbidden)
        if matched_forbidden:
            blocking_findings.append(
                {
                    "kind": "cross_domain_drift",
                    "line_no": line_no,
                    "line": line,
                    "tokens": matched_forbidden,
                }
            )
        for kind, pattern in _GLOBAL_POLLUTION_PATTERNS:
            if pattern.search(line):
                blocking_findings.append(
                    {
                        "kind": kind,
                        "line_no": line_no,
                        "line": line,
                        "tokens": [pattern.pattern],
                    }
                )
        if re.search(r"([\u4e00-\u9fff]{2,8})\1{1,}", line):
            warning_findings.append(
                {
                    "kind": "repeated_phrase",
                    "line_no": line_no,
                    "line": line,
                    "tokens": [],
                }
            )

    dedup_blocking: list[dict[str, Any]] = []
    seen_blocking: set[tuple[str, int, str]] = set()
    for item in blocking_findings:
        key = (str(item.get("kind")), int(item.get("line_no") or 0), str(item.get("line")))
        if key in seen_blocking:
            continue
        seen_blocking.add(key)
        dedup_blocking.append(_enrich_finding(item))

    dedup_warning: list[dict[str, Any]] = []
    seen_warning: set[tuple[str, int, str]] = set()
    for item in warning_findings:
        key = (str(item.get("kind")), int(item.get("line_no") or 0), str(item.get("line")))
        if key in seen_warning:
            continue
        seen_warning.add(key)
        dedup_warning.append(_enrich_finding(item))

    severity = _severity_from_counts(blocking_count=len(dedup_blocking), warning_count=len(dedup_warning))
    manual_review_required = bool(dedup_blocking)
    return {
        "job_id": str(job.get("job_id") or ""),
        "source_name": str(job.get("source_name") or ""),
        "status": str(job.get("status") or ""),
        "category": category,
        "quality_score": job.get("quality_score"),
        "quality_grade": job.get("quality_grade"),
        "subtitle_source": subtitle_source,
        "subtitle_path": subtitle_path,
        "severity": severity,
        "autocorrect_policy": "lexical_only",
        "manual_review_required": manual_review_required,
        "blocking_count": len(dedup_blocking),
        "warning_count": len(dedup_warning),
        "blocking_findings": dedup_blocking[:20],
        "warning_findings": dedup_warning[:20],
        "quality_issue_codes": list(job.get("quality_issue_codes") or []),
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Subtitle Pollution Audit",
        "",
        f"- batch_report: {report['batch_report']}",
        f"- job_count: {report['job_count']}",
        "- autocorrect_policy: lexical_only",
        "",
    ]
    for job in report["jobs"]:
        lines.append(f"## {job['source_name']}")
        lines.append(f"- severity: {job['severity']}")
        lines.append(f"- status: {job['status']}")
        lines.append(f"- quality: {job['quality_score']} ({job['quality_grade']})")
        lines.append(f"- subtitle_source: {job['subtitle_source']}")
        lines.append(f"- subtitle_path: {job['subtitle_path']}")
        lines.append(f"- manual_review_required: {job['manual_review_required']}")
        issue_codes = ", ".join(job["quality_issue_codes"]) if job["quality_issue_codes"] else "-"
        lines.append(f"- quality_issue_codes: {issue_codes}")
        if job["blocking_findings"]:
            lines.append("- blocking_findings:")
            for item in job["blocking_findings"][:8]:
                lines.append(
                    f"  - L{item['line_no']} [{item['kind']}] {item['line']} | class={item['finding_class']} | action={item['recommended_action']}"
                )
        else:
            lines.append("- blocking_findings: none")
        if job["warning_findings"]:
            lines.append("- warning_findings:")
            for item in job["warning_findings"][:5]:
                lines.append(
                    f"  - L{item['line_no']} [{item['kind']}] {item['line']} | class={item['finding_class']} | action={item['recommended_action']}"
                )
        else:
            lines.append("- warning_findings: none")
        lines.append("")
    return "\n".join(lines)


async def main_async() -> int:
    args = parse_args()
    batch_payload = json.loads(args.batch_report.read_text(encoding="utf-8"))
    jobs = [dict(item) for item in batch_payload.get("jobs") or [] if isinstance(item, dict)]
    render_outputs = await _load_render_outputs_by_job([str(item.get("job_id") or "") for item in jobs])
    audited_jobs = [_audit_job(job, render_outputs.get(str(job.get("job_id") or ""), {})) for job in jobs]
    report = {
        "batch_report": str(args.batch_report),
        "job_count": len(audited_jobs),
        "jobs": audited_jobs,
    }
    if args.output_json:
        args.output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(_render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "job_count": len(audited_jobs),
                "output_json": str(args.output_json) if args.output_json else "",
                "output_md": str(args.output_md) if args.output_md else "",
            },
            ensure_ascii=False,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
