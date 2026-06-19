from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Sequence


BATCH_REPORT_SCHEMA = "roughcut.remix.batch_report.v1"


def build_batch_report_payload(
    reports: Sequence[dict[str, Any]],
    *,
    source_root: str,
    episodes: Sequence[int],
    min_sample_count: int = 1,
    min_pass_rate: float = 0.90,
    verify_file_exists: bool = False,
) -> dict[str, Any]:
    items = [dict(item) for item in reports]
    success_count = sum(1 for item in items if str(item.get("build_status") or "") == "done")
    qa_pass_count = sum(1 for item in items if str(item.get("qa_status") or "") == "pass")
    qa_warn_count = sum(1 for item in items if str(item.get("qa_status") or "") == "warn")
    qa_fail_count = sum(1 for item in items if str(item.get("qa_status") or "") == "fail")
    evaluated_count = len(items)
    accepted_count = qa_pass_count + qa_warn_count
    pass_rate = accepted_count / evaluated_count if evaluated_count else 0.0
    issue_codes = Counter()
    required_evidence_failures: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []
    for item in items:
        missing = missing_required_evidence(item, verify_file_exists=verify_file_exists)
        if missing:
            required_evidence_failures.append({"episode": item.get("episode"), "missing": missing})
        for issue in item.get("qa_issues") or []:
            code = issue.get("code") if isinstance(issue, dict) else None
            if code:
                issue_codes[str(code)] += 1
        episode_rows.append(
            {
                "episode": item.get("episode"),
                "title": item.get("title"),
                "creator_profile_id": item.get("creator_profile_id"),
                "creator_profile_name": item.get("creator_profile_name"),
                "build_status": item.get("build_status"),
                "qa_status": item.get("qa_status"),
                "qa_issue_count": item.get("qa_issue_count"),
                "output_duration_sec": item.get("output_duration_sec"),
                "subtitle_alignment_source": item.get("subtitle_alignment_source"),
                "tts_request_metadata_path": item.get("tts_request_metadata_path"),
                "tts_provider": item.get("tts_provider"),
                "tts_mode": item.get("tts_mode"),
                "tts_reference_history_path": item.get("tts_reference_history_path"),
                "tts_voice_signature": item.get("tts_voice_signature"),
                "original_audio_intent_analysis_path": item.get("original_audio_intent_analysis_path"),
                "original_audio_intent_source": item.get("original_audio_intent_source"),
                "original_audio_intent_decision": item.get("original_audio_intent_decision"),
                "original_audio_intent_confidence": item.get("original_audio_intent_confidence"),
                "original_audio_intent_llm_reviewed": item.get("original_audio_intent_llm_reviewed"),
                "original_audio_source_mapping_path": item.get("original_audio_source_mapping_path"),
                "original_audio_source_mapping_source": item.get("original_audio_source_mapping_source"),
                "original_audio_source_mapping_llm_reviewed": item.get("original_audio_source_mapping_llm_reviewed"),
                "original_audio_reference_intent_count": item.get("original_audio_reference_intent_count"),
                "original_audio_insert_count": item.get("original_audio_insert_count"),
                "original_audio_insert_total_duration_sec": item.get("original_audio_insert_total_duration_sec"),
                "original_audio_insertions_path": item.get("original_audio_insertions_path"),
                "original_audio_visual_bridge_count": item.get("original_audio_visual_bridge_count"),
                "subtitle_text_coverage": item.get("subtitle_text_coverage"),
                "subtitle_style_profile": item.get("subtitle_style_profile"),
                "packaging_framework": item.get("packaging_framework"),
                "hyperframes_enabled": item.get("hyperframes_enabled"),
                "hyperframes_plan_schema": item.get("hyperframes_plan_schema"),
                "hyperframes_element_count": item.get("hyperframes_element_count"),
                "hyperframes_effect_count": item.get("hyperframes_effect_count"),
                "semantic_packaging_plan_path": item.get("semantic_packaging_plan_path"),
                "semantic_packaging_source": item.get("semantic_packaging_source"),
                "semantic_packaging_llm_reviewed": item.get("semantic_packaging_llm_reviewed"),
                "max_subtitle_lines_per_event": item.get("max_subtitle_lines_per_event"),
                "max_subtitle_line_chars": item.get("max_subtitle_line_chars"),
                "tts_asr_coverage": item.get("tts_asr_coverage"),
                "source_asr_anchor_count": item.get("source_asr_anchor_count"),
                "theme_banner_count": item.get("theme_banner_count"),
                "keyword_sticker_count": item.get("keyword_sticker_count"),
                "emphasis_keyword_count": item.get("emphasis_keyword_count"),
                "motion_effect_count": item.get("motion_effect_count"),
                "packaging_audio_cue_count": item.get("packaging_audio_cue_count"),
                "source_bridge_count": item.get("source_bridge_count"),
                "animated_subtitle_event_count": item.get("animated_subtitle_event_count"),
                "animated_packaging_event_count": item.get("animated_packaging_event_count"),
                "review_frame_count": item.get("review_frame_count"),
                "output_path": item.get("output_path"),
                "narration_path": item.get("narration_path"),
                "render_narration_path": item.get("render_narration_path"),
                "subtitle_path": item.get("subtitle_path"),
                "caption_package_path": item.get("caption_package_path"),
                "subtitle_timing_audit_path": item.get("subtitle_timing_audit_path"),
                "topic_plan_path": item.get("topic_plan_path"),
                "edit_plan_path": item.get("edit_plan_path"),
                "qa_report_path": item.get("qa_report_path"),
                "review_frames_manifest_path": item.get("review_frames_manifest_path"),
                "scene_index_path": item.get("scene_index_path"),
                "tts_asr_evidence_path": item.get("tts_asr_evidence_path"),
                "source_asr_index_path": item.get("source_asr_index_path"),
                "missing_required_evidence": missing,
            }
        )
    gate_passed = evaluated_count >= min_sample_count and pass_rate >= min_pass_rate and qa_fail_count == 0 and not required_evidence_failures
    return {
        "schema": BATCH_REPORT_SCHEMA,
        "source_root": source_root,
        "episodes": [int(item) for item in episodes],
        "sample_count": evaluated_count,
        "success_count": success_count,
        "qa_pass_count": qa_pass_count,
        "qa_warn_count": qa_warn_count,
        "qa_fail_count": qa_fail_count,
        "accepted_count": accepted_count,
        "pass_rate": round(pass_rate, 4),
        "min_sample_count": max(1, int(min_sample_count)),
        "min_pass_rate": min_pass_rate,
        "gate_passed": gate_passed,
        "gate_reason": batch_gate_reason(
            evaluated_count=evaluated_count,
            min_sample_count=min_sample_count,
            pass_rate=pass_rate,
            min_pass_rate=min_pass_rate,
            qa_fail_count=qa_fail_count,
            required_evidence_failures=required_evidence_failures,
        ),
        "issue_code_counts": dict(sorted(issue_codes.items())),
        "required_evidence_failures": required_evidence_failures,
        "episodes_detail": episode_rows,
    }


def missing_required_evidence(report: dict[str, Any], *, verify_file_exists: bool = False) -> list[str]:
    required_fields = [
        "output_path",
        "narration_path",
        "render_narration_path",
        "tts_request_metadata_path",
        "subtitle_path",
        "caption_package_path",
        "semantic_packaging_plan_path",
        "subtitle_timing_audit_path",
        "topic_plan_path",
        "edit_plan_path",
        "qa_report_path",
        "review_frames_manifest_path",
        "scene_index_path",
        "tts_asr_evidence_path",
        "source_asr_index_path",
    ]
    missing: list[str] = []
    for field in required_fields:
        raw_path = str(report.get(field) or "").strip()
        if not raw_path:
            missing.append(field)
            continue
        if verify_file_exists and not Path(raw_path).exists():
            missing.append(f"{field}:file_missing")
    if int(_float(report.get("review_frame_count"))) <= 0:
        missing.append("review_frames")
    if str(report.get("subtitle_alignment_source") or "") != "qwen3_asr_forced_aligner_on_tts":
        missing.append("qwen3_tts_asr_subtitle_alignment")
    if str(report.get("packaging_framework") or "") != "hyperframes" or not bool(report.get("hyperframes_enabled")):
        missing.append("hyperframes_packaging_plan")
    if not str(report.get("hyperframes_plan_schema") or "").strip():
        missing.append("hyperframes_plan_schema")
    if str(report.get("semantic_packaging_source") or "") != "llm_script_packaging":
        missing.append("llm_semantic_caption_packaging")
    if not bool(report.get("semantic_packaging_llm_reviewed")):
        missing.append("semantic_packaging_llm_reviewed")
    if int(_float(report.get("packaging_audio_cue_count", report.get("audio_cue_count", 0)))) <= 0:
        missing.append("packaging_audio_cues")
    if int(_float(report.get("source_asr_anchor_count"))) <= 0:
        missing.append("source_asr_anchors")
    if not str(report.get("tts_provider") or "").strip():
        missing.append("tts_provider")
    if not str(report.get("tts_mode") or "").strip():
        missing.append("tts_mode")
    if not str(report.get("tts_voice_signature") or "").strip():
        missing.append("tts_voice_signature")
    raw_intent_path = str(report.get("original_audio_intent_analysis_path") or "").strip()
    if raw_intent_path and verify_file_exists and not Path(raw_intent_path).exists():
        missing.append("original_audio_intent_analysis_path:file_missing")
    if not bool(report.get("original_audio_intent_llm_reviewed")):
        missing.append("original_audio_intent_llm_reviewed")
    if int(_float(report.get("original_audio_reference_intent_count", 0))) > 0:
        if int(_float(report.get("original_audio_insert_count", 0))) <= 0:
            missing.append("original_audio_insertions")
        elif _float(report.get("original_audio_insert_total_duration_sec", 0)) < 6.0 * max(1, int(_float(report.get("original_audio_insert_count", 0)))):
            missing.append("original_audio_bridge_duration")
        if str(report.get("original_audio_source_mapping_source") or "") != "llm_source_asr_mapping":
            missing.append("original_audio_source_asr_mapping")
        if not bool(report.get("original_audio_source_mapping_llm_reviewed")):
            missing.append("original_audio_source_mapping_llm_reviewed")
        raw_mapping_path = str(report.get("original_audio_source_mapping_path") or "").strip()
        if not raw_mapping_path:
            missing.append("original_audio_source_mapping_path")
        elif verify_file_exists and not Path(raw_mapping_path).exists():
            missing.append("original_audio_source_mapping_path:file_missing")
        if int(_float(report.get("source_bridge_count", 0))) < int(_float(report.get("original_audio_insert_count", 0))):
            missing.append("original_audio_bridge_visuals")
        if int(_float(report.get("original_audio_visual_bridge_count", 0))) < int(_float(report.get("original_audio_insert_count", 0))):
            missing.append("original_audio_video_bridges")
        raw_path = str(report.get("original_audio_insertions_path") or "").strip()
        if not raw_path:
            missing.append("original_audio_insertions_path")
        elif verify_file_exists and not Path(raw_path).exists():
            missing.append("original_audio_insertions_path:file_missing")
    return missing


def batch_gate_reason(
    *,
    evaluated_count: int,
    min_sample_count: int,
    pass_rate: float,
    min_pass_rate: float,
    qa_fail_count: int = 0,
    required_evidence_failures: Sequence[dict[str, Any]],
) -> str:
    if evaluated_count < max(1, int(min_sample_count)):
        return f"evaluated_count_below_min:{evaluated_count}<{max(1, int(min_sample_count))}"
    if required_evidence_failures:
        return "required_evidence_missing"
    if qa_fail_count > 0:
        return f"qa_failed:{qa_fail_count}"
    if pass_rate < min_pass_rate:
        return f"pass_rate_below_min:{pass_rate:.4f}<{min_pass_rate:.4f}"
    return "passed"


def render_batch_report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Script-Footage Remix Batch Report",
        "",
        f"- schema: `{payload.get('schema')}`",
        f"- source_root: `{payload.get('source_root')}`",
        f"- episodes: {payload.get('episodes')}",
        f"- sample_count: {payload.get('sample_count')}",
        f"- min_sample_count: {payload.get('min_sample_count')}",
        f"- qa_pass_count: {payload.get('qa_pass_count')}",
        f"- pass_rate: {payload.get('pass_rate')}",
        f"- gate_passed: {payload.get('gate_passed')}",
        f"- gate_reason: {payload.get('gate_reason')}",
        "",
        "## Episodes",
        "",
        "| episode | title | qa | duration | tts_asr | source_asr | original_audio | av_bridge | caption_bridge | semantic_packaging | packaging | motion | review | missing |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |",
    ]
    for item in payload.get("episodes_detail") or []:
        packaging = f"{item.get('theme_banner_count')}/{item.get('keyword_sticker_count')}"
        motion = item.get("motion_effect_count")
        original_audio = f"{item.get('original_audio_insert_count') or 0}/{item.get('original_audio_reference_intent_count') or 0}"
        semantic_packaging = f"{item.get('semantic_packaging_source') or '-'}:{item.get('semantic_packaging_llm_reviewed')}"
        missing = ",".join(item.get("missing_required_evidence") or []) or "-"
        lines.append(
            "| {episode} | {title} | {qa} | {duration} | {tts} | {source} | {original_audio} | {av_bridge} | {bridge} | {semantic_packaging} | {packaging} | {motion} | {review} | {missing} |".format(
                episode=item.get("episode"),
                title=item.get("title"),
                qa=item.get("qa_status"),
                duration=item.get("output_duration_sec"),
                tts=item.get("tts_asr_coverage"),
                source=item.get("source_asr_anchor_count"),
                original_audio=original_audio,
                av_bridge=item.get("original_audio_visual_bridge_count"),
                bridge=item.get("source_bridge_count"),
                semantic_packaging=semantic_packaging,
                packaging=packaging,
                motion=motion,
                review=item.get("review_frame_count"),
                missing=missing,
            )
        )
    if payload.get("issue_code_counts"):
        lines.extend(["", "## Issue Codes", ""])
        for code, count in payload["issue_code_counts"].items():
            lines.append(f"- `{code}`: {count}")
    if payload.get("required_evidence_failures"):
        lines.extend(["", "## Required Evidence Failures", ""])
        for item in payload["required_evidence_failures"]:
            lines.append(f"- episode {item.get('episode')}: {', '.join(item.get('missing') or [])}")
    return "\n".join(lines) + "\n"


def render_methodology_report_markdown() -> str:
    return """# 文案引用原片型影视二创方法论与流程

## 定义

输入是成稿文案和对应原片，输出是解说主导成片。新 TTS 旁白、新字幕包装和新叙事结构是主体，原片画面只承担主题/剧情证据。2-3 分钟只是发布目标区间，不允许为了卡时长自动删改成稿文案。

## 标准链路

1. 输入检查：文案和原片按集数对应，探测原片时长、分辨率和音轨。
2. 文案主题拆解：完整保留成稿文案，将文案拆成 5-8 个主题/剧情块，不做删句、摘要或逐句镜头匹配。
3. MOSS TTS：默认用 MOSS 生成旁白，CosyVoice3 只作为显式 AB。
4. 气口压缩：压缩长无声，输出 raw/clean 两版旁白与压缩统计。
5. TTS-ASR：用 Qwen3-ASR + ForcedAligner 识别最终 TTS 音频，只取时间戳，字幕文本仍以原文案为准。
6. Source-ASR：用 Qwen3-ASR 识别原片候选窗口，用于剧情/主题定位，不参与字幕时间戳。
7. 原片情景桥：由 LLM 理解完整文案脚本，识别适合插入原片的具体场景、连续对话、角色动作、声音线索或关键剧情证据。随后由 LLM 基于原片 Source-ASR 文本选择 source_start_sec 和完整小片段 duration，并在 TTS-ASR 字幕时间线上把插入点落到对应文案 cue 后面；实际同步插入 6-12 秒原片画面和原片原声，再继续解说。只是泛泛提到原片、角色名或抽象观点，不触发原片情景桥。
8. 镜头索引：检测原片镜头边界，把选段和 scene_match 写入 edit plan。
9. 主题级连续选段：每个主题选择一段连续画面，到下一个主题点再切换。
10. 画面处理：Bluey 1080p 源使用 crop=1440:810:180:50 后放大到 1920x1080，弱化平台 logo 和原底字幕。
11. LLM 语义包装：由 LLM 基于完整文案和最终字幕时间戳输出主题条、关键词气泡、大字冲击、字幕重点词和小提示词；每个事件必须有 matched_text/reason，不能套用集数硬编码词。
12. Hyperframes 字幕包装：底部主字幕、自有水印、主题条、关键词贴纸、重点字特效、声桥提示和基础动效统一由 caption package 生成；主题条底板与标题文字必须共用中心运动，避免文字跑出框外。
13. 渲染：H.264/AAC MP4，默认 1920x1080、28fps。
14. 自动验收：QA report 检查时长、TTS-ASR、Source-ASR、原片声桥、LLM 语义包装、scene index、字幕包装、review frames。
15. 人工复核：用 review_frames 抽查画面裁切、字幕包装和连续画面观感。

## 关键质量门

- 成片时长 120-180 秒是目标区间；超出区间只作为 warning，不能通过自动压缩文案解决。
- 字幕时间戳来源必须是 qwen3_asr_forced_aligner_on_tts。
- TTS-ASR 覆盖率硬门 >= 0.90。
- Source-ASR 至少 3 个可用锚点，目标每集 10 个以上候选锚点。
- LLM 检测到原片场景/台词/对话/声音/关键剧情证据意图时，必须生成 `original_audio_insertions` 证据并实际插入原片原声和对应原片画面；单个桥段平均时长不得低于 6 秒，不能用 2-3 秒碎片冒充完整情景。
- 原片声画桥的 source_start_sec 必须来自 `llm_source_asr_mapping`，并带有 source_asr_text/evidence_text/reason 证据；不能用文案比例或固定锚点猜。
- 每集至少 3 个主题条、3 个关键词贴纸、1 个自有水印事件，字幕每屏最多 2 行、单行不超过 18 字。
- 每集至少 3 个重点字特效，并记录 subtitle/style/motion 指标；包装动效不足不能算剪映式成片。
- 字幕包装必须来自 `llm_script_packaging` 且 `llm_reviewed=true`；deterministic fallback 只能用于开发渲染，不能通过正式 QA。
- 若插入原片原声，必须有对应数量的原片视频桥段、`source_audio_bridges` Hyperframes 轨道和 `source_bridge` 可见提示事件。
- 每集至少 5 张 review frame。
- 每集必须有 TTS、clean TTS、TTS-ASR、Source-ASR、topic plan、edit plan、subtitle、caption package、QA report、review frames、final mp4 证据。

## 失败处理

失败必须落到具体质量门。不能用静音占位、跳过 ASR、MOSS live segment 时间戳、均匀抽样选段或缺少证据的 mp4 冒充最终样片。

## 批量收口

默认验收跑 1 集完整样片即可，可交付通过率不低于 90%，其中 `warn` 代表可交付但需要人工关注。需要验证批量稳定性时，再显式跑 10 集压力测试。`batch_report.json` 是机器验收事实源，`batch_report.md` 是人工复核入口。
"""


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
