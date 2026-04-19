from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from roughcut.api.avatar_materials import get_avatar_materials
from roughcut.api.config import get_config
from roughcut.api.jobs import _ensure_content_profile_thumbnail, confirm_content_profile, get_content_profile
from roughcut.api.schemas import ContentProfileConfirmIn, ReviewActionCreate, ReviewApplyRequest
from roughcut.config import get_settings
from roughcut.creative.modes import build_active_enhancement_mode_options, build_active_workflow_mode_options
from roughcut.db.models import Artifact, Job, JobStep, ReviewAction, SubtitleItem
from roughcut.db.session import get_session_factory
from roughcut.media.audio import extract_audio
from roughcut.media.probe import probe
from roughcut.media.variant_timeline_bundle import resolve_effective_variant_timeline_bundle
from roughcut.packaging.library import list_packaging_assets, resolve_packaging_plan_for_job
from roughcut.providers.factory import get_reasoning_provider, get_transcription_provider
from roughcut.review.downstream_context import select_resolved_downstream_profile
from roughcut.review.final_review_rerun import (
    FinalReviewRerunPlan,
    build_final_review_rerun_plan as _build_final_review_rerun_plan,
    build_final_review_rerun_plans as _build_final_review_rerun_plans,
    combine_final_review_rerun_plans as _combine_final_review_rerun_plans,
    extract_final_review_content_profile_feedback as _extract_final_review_content_profile_feedback,
)
from roughcut.review.final_review_state import (
    apply_final_review_rerun_metadata,
    mark_final_review_approved,
    mark_final_review_pending,
)
from roughcut.review.subtitle_memory import build_transcription_prompt
from roughcut.review.subtitle_review_actions import (
    build_subtitle_consistency_action,
    build_subtitle_quality_action,
    build_subtitle_term_resolution_action,
)
from roughcut.review import telegram_review_parsing
from roughcut.review.content_profile import (
    _build_review_keywords,
    _collect_review_keyword_seed_terms,
    _extract_review_keyword_tokens,
    build_review_feedback_search_queries,
    build_reviewed_transcript_excerpt,
)
from roughcut.review.report import generate_report
from roughcut.review.content_profile_field_rules import CONTENT_PROFILE_FIELD_GUIDELINES
from roughcut.review.content_understanding_schema import normalize_video_type
from roughcut.telegram.commands import handle_telegram_command, handle_telegram_freeform_request
from roughcut.telegram.policy import (
    is_allowed_chat,
    telegram_agent_enabled,
    telegram_review_enabled,
    telegram_service_enabled,
)
from roughcut.telegram.task_service import (
    get_agent_task_status,
    mark_task_notified,
    pending_notification_records,
)
from roughcut.telegram.review_notification_service import (
    mark_review_notification_delivered,
    mark_review_notification_failed,
    pending_review_notifications,
    reschedule_review_notification,
)
from roughcut.providers.reasoning.base import Message

logger = logging.getLogger(__name__)

_TELEGRAM_API_MAX_ATTEMPTS = 3
_TELEGRAM_API_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

_REVIEW_KIND_CONTENT = telegram_review_parsing.REVIEW_KIND_CONTENT
_REVIEW_KIND_SUBTITLE = telegram_review_parsing.REVIEW_KIND_SUBTITLE
_REVIEW_KIND_FINAL = telegram_review_parsing.REVIEW_KIND_FINAL
_SIMPLE_APPROVAL_PATTERN = telegram_review_parsing.SIMPLE_APPROVAL_PATTERN
_FINAL_APPROVAL_PATTERN = telegram_review_parsing.FINAL_APPROVAL_PATTERN
_NEGATED_SUBTITLE_CONTENT_PATTERN = telegram_review_parsing.NEGATED_SUBTITLE_CONTENT_PATTERN
_REVIEW_KEYWORD_SPLIT_RE = re.compile(r"[\\s,，、/|+*×xX·•_=\\-]+")
_REVIEW_KEYWORD_CONNECTOR_RE = re.compile(r"(?:与|和|及|及其|以及|并|并且|对比|联名|还是|或者|以及)")
_REVIEW_KEYWORD_TOKEN_LIMIT = 10
_REVIEW_KEYWORD_MIN_COUNT = 4
_WORKFLOW_MODE_LABELS = {
    "standard_edit": "标准成片",
    "long_text_to_video": "长文本转视频",
}
_ENHANCEMENT_MODE_LABELS = {
    "multilingual_translation": "多语言翻译",
    "auto_review": "自动审核",
    "avatar_commentary": "数字人解说",
    "ai_effects": "智能剪辑特效",
    "ai_director": "AI 导演",
}
_COPY_STYLE_LABELS = {
    "attention_grabbing": "吸引眼球",
    "balanced": "平衡稳妥",
    "premium_editorial": "高级编辑感",
    "trusted_expert": "专业可信",
    "playful_meme": "轻松玩梗",
    "emotional_story": "情绪叙事",
}
_SUBTITLE_STYLE_LABELS = {
    "bold_yellow_outline": "粗黄描边",
    "white_minimal": "纯白极简",
    "neon_green_glow": "荧绿霓虹",
    "cinema_blue": "蓝灰电影感",
    "bubble_pop": "圆角气泡",
    "keyword_highlight": "关键词高亮",
    "amber_news": "琥珀新闻",
    "punch_red": "爆点红字",
    "lime_box": "荧绿框",
    "soft_shadow": "柔影白字",
    "clean_box": "清爽信息框",
    "midnight_magenta": "午夜洋红",
    "mint_outline": "薄荷描边",
    "cobalt_pop": "钴蓝跳色",
    "rose_gold": "玫瑰金",
    "slate_caption": "石板灰",
    "ivory_serif": "象牙衬线",
    "cyber_orange": "赛博橙光",
    "streamer_duo": "主播双色",
    "doc_gray": "纪实灰白",
    "sale_banner": "活动横条",
    "coupon_green": "优惠绿标",
    "luxury_caps": "奢感大写",
    "film_subtle": "胶片低调",
    "archive_type": "档案字机",
    "teaser_glow": "预告辉光",
}
_COVER_STYLE_LABELS = {
    "preset_default": "平台策略联动",
    "tech_showcase": "科技展示",
    "collection_drop": "限定收藏",
    "upgrade_spotlight": "升级聚焦",
    "tactical_neon": "战术霓虹",
    "luxury_blackgold": "黑金奢感",
    "retro_poster": "复古海报",
    "creator_vlog": "创作者 vlog",
    "bold_review": "重磅测评",
    "tutorial_card": "教程信息卡",
    "food_magazine": "杂志生活感",
    "street_hype": "街头潮流",
    "minimal_white": "极简白牌",
    "cyber_grid": "赛博网格",
    "premium_silver": "银感质感",
    "comic_pop": "漫画爆点",
    "studio_red": "演播室红",
    "documentary_frame": "纪录边框",
    "pastel_lifestyle": "柔和彩度",
    "industrial_orange": "工业橙",
    "ecommerce_sale": "电商促销",
    "price_strike": "价格重击",
    "trailer_dark": "暗调预告",
    "festival_redgold": "节庆红金",
    "clean_lab": "实验室白蓝",
    "cinema_teaser": "电影预热",
}
_TITLE_STYLE_LABELS = {
    "preset_default": "跟随策略自动联动",
    "cyber_logo_stack": "赛博 logo 叠层",
    "chrome_impact": "镀铬冲击",
    "festival_badge": "节庆徽章",
    "double_banner": "双横幅爆字",
    "comic_boom": "漫画爆炸字",
    "luxury_gold": "奢感金字",
    "tutorial_blueprint": "教程蓝图",
    "magazine_clean": "杂志清排",
    "documentary_stamp": "纪录印章",
    "neon_night": "夜霓虹",
}
_SMART_EFFECT_STYLE_LABELS = {
    "smart_effect_commercial": "商业高能",
    "smart_effect_rhythm": "商业高能",
    "smart_effect_punch": "爆点冲击",
    "smart_effect_glitch": "故障赛博",
    "smart_effect_cinematic": "电影推进",
    "smart_effect_atmosphere": "氛围塑形",
    "smart_effect_minimal": "克制轻特效",
}
_IDENTITY_SUPPORT_SOURCE_LABELS = {
    "transcript": "字幕",
    "source_name": "文件名",
    "visible_text": "画面文字",
    "evidence": "外部证据",
}
_CONTENT_FIELD_ORDER = (
    ("subject_type", "视频类型（主类型）"),
    ("video_theme", "视频主题"),
    ("hook_line", "标题钩子"),
    ("visible_text", "画面文字（OCR/画面可见词）"),
    ("summary", "内容摘要"),
    ("engagement_question", "互动提问"),
    ("correction_notes", "校对备注（人工纠偏）"),
    ("supplemental_context", "补充上下文（拍摄与素材补充）"),
)
_FINAL_REVIEW_CALLBACK_ACTION_TEXT = {
    "approve": "成片通过",
    "edit_hook": "重剪 Hook 边界",
    "edit_mid": "重剪中段衔接",
    "edit_cta": "重剪 CTA 衔接",
    "edit": "高风险边界重剪",
    "cover": "只改封面",
    "music": "只改BGM",
    "platform": "只改平台文案",
    "avatar": "数字人口播重做",
}
_FINAL_REVIEW_CALLBACK_ACK_TEXT = {
    "approve": "已接收成片通过",
    "edit_hook": "已接收 Hook 边界重剪",
    "edit_mid": "已接收中段衔接重剪",
    "edit_cta": "已接收 CTA 衔接重剪",
    "edit": "已接收边界重剪",
    "cover": "已接收封面重出",
    "music": "已接收 BGM 重出",
    "platform": "已接收平台文案重出",
    "avatar": "已接收数字人口播重做",
}

_AUDIO_SUFFIX_BY_MIME = {
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
}
_REVIEW_KIND_TITLES = {
    _REVIEW_KIND_CONTENT: "内容摘要审核",
    _REVIEW_KIND_SUBTITLE: "字幕复核",
    _REVIEW_KIND_FINAL: "成片审核",
}
_REVIEW_STEP_NAME_BY_KIND = {
    _REVIEW_KIND_CONTENT: "summary_review",
    _REVIEW_KIND_SUBTITLE: "glossary_review",
    _REVIEW_KIND_FINAL: "final_review",
}
_SUBTITLE_REVIEW_ARTIFACT_TYPES = (
    "subtitle_term_resolution_patch",
    "subtitle_consistency_report",
    "subtitle_quality_report",
)


@dataclass
class TelegramReviewCandidate:
    slot: str
    correction_id: str
    subtitle_index: int
    original: str
    suggested: str
    change_type: str
    confidence: float
    source: str | None = None
    start_sec: float | None = None
    end_sec: float | None = None


@dataclass
class TelegramSubtitleLineCandidate:
    slot: str
    subtitle_item_id: str
    subtitle_index: int
    text: str
    start_sec: float | None = None
    end_sec: float | None = None


@dataclass
class TelegramReviewThumbnail:
    path: Path
    caption: str


@dataclass
class TelegramReviewVideo:
    path: Path
    caption: str


@dataclass
class TelegramFinalReviewClip:
    label: str
    start_sec: float
    duration_sec: float
    transcript_excerpt: str
    matched_keyword: str | None = None


class TelegramReviewBotService:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._offset: int | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="telegram-review-bot")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def run_forever(self) -> None:
        await self._run()

    async def notify_content_profile_review(self, job_id: uuid.UUID) -> None:
        settings = get_settings()
        if not _telegram_review_ready(settings):
            return

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            review = await get_content_profile(job_id, session)
            draft = dict(review.final or review.draft or {})
            packaging_state = list_packaging_assets()
            packaging_config = dict((packaging_state.get("config") or {}))
            packaging_plan = resolve_packaging_plan_for_job(str(job.id), content_profile=draft)
            config = get_config()
            avatar_materials = await get_avatar_materials()
            message = _build_content_profile_review_message(
                source_name=job.source_name,
                job_id=job.id,
                locale=job.language,
                review=review,
                draft=draft,
                packaging_assets=packaging_state.get("assets") or {},
                packaging_config=packaging_config,
                packaging_plan=packaging_plan,
                config=config,
                avatar_materials=avatar_materials,
            )
            thumbnails = await self._build_content_profile_thumbnails(job, kind=_REVIEW_KIND_CONTENT)
            if not thumbnails:
                message = (
                    f"{message}\n\n"
                    "参考缩略图：当前未能自动抽取，本次先按文字信息审核。"
                )
        await self._send_review_message(_REVIEW_KIND_CONTENT, job_id, message, thumbnails=thumbnails)

    async def notify_subtitle_review(self, job_id: uuid.UUID, *, force_full_review: bool = False) -> None:
        settings = get_settings()
        if not _telegram_review_ready(settings):
            return

        message = ""
        attachment_path: Path | None = None
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            report = await generate_report(job_id, session)
            subtitle_review_artifacts = await _load_subtitle_review_artifacts(job_id, session)
            pending_candidates = _build_pending_subtitle_candidates(report)
            if pending_candidates:
                lines = [
                    f"任务：{job.source_name}",
                    f"Job ID：{job.id}",
                    f"待审核字幕纠错：{len(pending_candidates)} 条",
                    f"总候选：{report.total_corrections}，已接受：{report.accepted_count}，已拒绝：{report.rejected_count}",
                    "",
                    "回复方式：",
                    "1. 回复“全部通过”会批量接受所有待审项。",
                    "2. 回复“全部拒绝”会批量拒绝所有待审项。",
                    "3. 也可以直接自然语言说明，例如：S1通过，S2改成锐钛，S3拒绝。",
                    "",
                    "待审清单：",
                ]
                for candidate in pending_candidates:
                    lines.extend(
                        [
                            f"{candidate.slot} · 字幕 #{candidate.subtitle_index}",
                            f"原文：{candidate.original}",
                            f"建议：{candidate.suggested}",
                            f"类型：{candidate.change_type} · 置信度：{round(candidate.confidence * 100)}%",
                            f"来源：{candidate.source or 'unknown'}",
                            "",
                        ]
                    )
                artifact_lines = _build_subtitle_review_artifact_lines(subtitle_review_artifacts)
                if artifact_lines:
                    lines.extend(
                        [
                            "",
                            "字幕审校状态：",
                            *artifact_lines,
                        ]
                    )
                message = "\n".join(lines).strip()
            elif force_full_review:
                subtitle_lines = await _load_full_subtitle_review_lines(job_id, session)
                if not subtitle_lines:
                    message = (
                        f"任务：{job.source_name}\n"
                        f"Job ID：{job.id}\n\n"
                        "当前没有可供复核的字幕内容。"
                    )
                    artifact_lines = _build_subtitle_review_artifact_lines(subtitle_review_artifacts)
                    if artifact_lines:
                        message = "\n".join(
                            [
                                message,
                                "",
                                "字幕审校状态：",
                                *artifact_lines,
                            ]
                        ).strip()
                else:
                    preview_excerpt = build_reviewed_transcript_excerpt(
                        [
                            {
                                "index": item.subtitle_index,
                                "start_time": item.start_sec or 0.0,
                                "end_time": item.end_sec or 0.0,
                                "text_final": item.text,
                            }
                            for item in subtitle_lines
                        ],
                        max_items=12,
                        max_chars=900,
                    )
                    message = "\n".join(
                        [
                            f"任务：{job.source_name}",
                            f"Job ID：{job.id}",
                            "自动字幕纠错未产出候选，已切换为全量人工字幕复核。",
                            f"字幕总条数：{len(subtitle_lines)}",
                            "",
                            "回复方式：",
                            "1. 回复“全部通过”表示整份字幕无需修改。",
                            "2. 回复类似“L17改成 狐蝠工业，L18通过”的格式逐条修订。",
                            "3. 我已附上完整字幕复核清单，可按行号核对。",
                            "",
                            "字幕预览：",
                            preview_excerpt or "无",
                        ]
                    ).strip()
                    artifact_lines = _build_subtitle_review_artifact_lines(subtitle_review_artifacts)
                    if artifact_lines:
                        message = "\n".join(
                            [
                                message,
                                "",
                                "字幕审校状态：",
                                *artifact_lines,
                            ]
                        ).strip()
                    attachment_path = _write_full_subtitle_review_attachment(job.id, subtitle_lines)
            else:
                return
        delivery = await self._send_review_message(_REVIEW_KIND_SUBTITLE, job_id, message)
        if attachment_path is not None and bool((delivery or {}).get("sent")):
            try:
                chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
                round_label = str((delivery or {}).get("round_label") or _format_review_round_label(1))
                await self._send_chat_document(
                    attachment_path,
                    chat_id=chat_id,
                    caption=_prepend_review_round_to_caption(
                        f"【RC:{_REVIEW_KIND_SUBTITLE}:{job_id}】\n全量字幕人工复核清单",
                        round_label=round_label,
                    ),
                )
            except Exception:
                logger.exception("Failed to send full subtitle review attachment for job %s", job_id)

    async def notify_final_review(self, job_id: uuid.UUID) -> None:
        settings = get_settings()
        if not _telegram_review_ready(settings):
            return

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            review_step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "final_review")
                )
            ).scalar_one_or_none()
            if review_step is None or review_step.status != "pending":
                return
            steps = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.id.asc())
                )
            ).scalars().all()
            render_outputs_artifact = (
                await session.execute(
                    select(Artifact)
                    .where(Artifact.job_id == job.id, Artifact.artifact_type == "render_outputs")
                    .order_by(Artifact.created_at.desc())
                )
            ).scalars().first()
            render_outputs = render_outputs_artifact.data_json if render_outputs_artifact and isinstance(render_outputs_artifact.data_json, dict) else {}
            variant_timeline_bundle_artifact = (
                await session.execute(
                    select(Artifact)
                    .where(Artifact.job_id == job.id, Artifact.artifact_type == "variant_timeline_bundle")
                    .order_by(Artifact.created_at.desc())
                )
            ).scalars().first()
            variant_timeline_bundle = (
                variant_timeline_bundle_artifact.data_json
                if variant_timeline_bundle_artifact and isinstance(variant_timeline_bundle_artifact.data_json, dict)
                else None
            )
            variant_timeline_bundle = resolve_effective_variant_timeline_bundle(
                variant_timeline_bundle,
                render_outputs=render_outputs,
            )
            content_profile_artifacts = (
                await session.execute(
                    select(Artifact)
                    .where(
                        Artifact.job_id == job.id,
                        Artifact.artifact_type.in_(("downstream_context", "content_profile_final", "content_profile", "content_profile_draft")),
                    )
                    .order_by(Artifact.created_at.desc())
                )
            ).scalars().all()
            content_profile = _select_final_review_content_profile(content_profile_artifacts)
            subtitle_report = await generate_report(job.id, session)
            message = _build_final_review_message(
                source_name=job.source_name,
                job_id=job.id,
                workflow_mode=str(getattr(job, "workflow_mode", "") or "standard_edit"),
                enhancement_modes=list(getattr(job, "enhancement_modes", []) or []),
                render_outputs=render_outputs,
                content_profile=content_profile,
                subtitle_report=subtitle_report,
                variant_timeline_bundle=variant_timeline_bundle,
                rerun_context=_extract_latest_final_review_rerun_context(steps),
            )
            videos = await _build_final_review_videos(
                job.id,
                render_outputs,
                content_profile=content_profile,
                subtitle_report=subtitle_report,
                variant_timeline_bundle=variant_timeline_bundle,
            )
        await self._send_review_message(
            _REVIEW_KIND_FINAL,
            job_id,
            message,
            videos=videos,
            variant_timeline_bundle=variant_timeline_bundle,
        )

    async def _run(self) -> None:
        consecutive_failures = 0
        while True:
            settings = get_settings()
            if not _telegram_service_ready(settings):
                consecutive_failures = 0
                await asyncio.sleep(10)
                continue
            try:
                await self._poll_updates()
                await self._poll_agent_tasks()
                await self._poll_review_notifications()
                consecutive_failures = 0
            except asyncio.CancelledError:
                raise
            except Exception:
                consecutive_failures += 1
                delay = _telegram_poll_failure_backoff_seconds(consecutive_failures)
                logger.exception("Telegram review bot poll failed; retrying in %.1fs", delay)
                await asyncio.sleep(delay)

    async def _poll_updates(self) -> None:
        settings = get_settings()
        payload = {
            "timeout": 50,
            "allowed_updates": ["message", "callback_query"],
        }
        if self._offset is not None:
            payload["offset"] = self._offset
        data = await self._call_api(settings, "getUpdates", payload)
        for item in data.get("result") or []:
            try:
                update_id = int(item.get("update_id"))
            except (TypeError, ValueError):
                continue
            self._offset = update_id + 1
            await self._handle_update(item)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        callback_query = update.get("callback_query") or {}
        if callback_query:
            await self._handle_callback_query(callback_query)
            return
        message = update.get("message") or {}
        actual_chat_id = str((message.get("chat") or {}).get("id") or "").strip()
        text = _message_text(message)
        text_lower = text.lower()
        if text_lower in {"/start", "/help"}:
            settings = get_settings()
            review_enabled = telegram_review_enabled(settings)
            agent_enabled = telegram_agent_enabled(settings)
            service_parts = [
                "远程审核已启用" if review_enabled else "远程审核未启用",
                "Telegram Agent 已启用" if agent_enabled else "Telegram Agent 未启用",
            ]
            await self._send_chat_text(
                f"{'；'.join(service_parts)}。"
                "审核消息可直接回复“全部通过 / 全部拒绝”或类似“S1通过，S2改成 xxx”。\n"
                "命令：/status、/jobs [limit]、/job <job_id>、"
                "/run <claude|codex|acp> <preset> --task \"...\"、/task <task_id> [--full]、"
                "/tasks [limit]、/presets、/confirm <task_id>、/cancel <task_id>、"
                "/review [content|subtitle|final] <job_id> <pass|reject|note> [备注]\n"
                "如果直接发送复杂错误、结构优化、链路优化或未知命令需求，agent 会自动尝试分流并创建处理任务。"
                "也支持直接发语音，我会先转写，再走命令、审核或 agent 分流。",
                chat_id=actual_chat_id,
            )
            return
        if text_lower in {"/whoami", "/id"}:
            await self._send_chat_text(f"当前会话 Chat ID：{actual_chat_id}", chat_id=actual_chat_id)
            return

        settings = get_settings()
        if not is_allowed_chat(settings, actual_chat_id):
            return
        text, from_voice = await self._resolve_message_text(message, chat_id=actual_chat_id, settings=settings)
        if not text:
            return
        if from_voice:
            text = _normalize_spoken_command_text(text)
        if text.startswith("/"):
            async def send_with_chat_id(reply_text: str) -> None:
                await self._send_chat_text(reply_text, chat_id=actual_chat_id)

            setattr(send_with_chat_id, "_telegram_chat_id", actual_chat_id)
            if await handle_telegram_command(text, send_text=send_with_chat_id):
                return

        review_ref = _extract_review_reference_from_message(message)
        if review_ref is None and bool(getattr(settings, "telegram_agent_enabled", False)):
            async def send_with_chat_id(reply_text: str) -> None:
                await self._send_chat_text(reply_text, chat_id=actual_chat_id)

            setattr(send_with_chat_id, "_telegram_chat_id", actual_chat_id)
            if await handle_telegram_freeform_request(text, send_text=send_with_chat_id):
                return
        if review_ref is None:
            await self._send_chat_text(
                "未识别到审核上下文。请直接在我推送的审核消息下点击“回复”并给出意见；不要新开一条无上下文消息。",
                chat_id=actual_chat_id,
            )
            return

        kind, job_id = review_ref
        if kind == _REVIEW_KIND_CONTENT:
            await self._handle_content_profile_reply(job_id, text, reply_chat_id=actual_chat_id)
        elif kind == _REVIEW_KIND_SUBTITLE:
            await self._handle_subtitle_reply(job_id, text, reply_chat_id=actual_chat_id)
        elif kind == _REVIEW_KIND_FINAL:
            await self._handle_final_review_reply(job_id, text, reply_chat_id=actual_chat_id)

    async def _resolve_message_text(
        self,
        message: dict[str, Any],
        *,
        chat_id: str,
        settings: Any,
    ) -> tuple[str, bool]:
        text = _message_text(message)
        if text:
            return text, False
        transcript = await self._transcribe_message_audio_text(message, chat_id=chat_id, settings=settings)
        return transcript, bool(transcript)

    async def _transcribe_message_audio_text(
        self,
        message: dict[str, Any],
        *,
        chat_id: str,
        settings: Any,
    ) -> str:
        attachment = _extract_audio_attachment(message)
        if attachment is None:
            return ""

        file_id = str(attachment.get("file_id") or "").strip()
        if not file_id:
            return ""

        try:
            transcript = await self._download_and_transcribe_audio(
                file_id=file_id,
                file_name=str(attachment.get("file_name") or "").strip(),
                mime_type=str(attachment.get("mime_type") or "").strip(),
                settings=settings,
            )
        except Exception as exc:
            logger.warning("Failed to transcribe Telegram audio message for chat %s: %s", chat_id, exc)
            await self._send_chat_text(
                "语音指令转写失败。请直接发送文字，或稍后重试更清晰的语音。",
                chat_id=chat_id,
            )
            return ""

        if not transcript:
            await self._send_chat_text(
                "语音里没有识别到清晰的可执行文本。请换一条更清晰的语音，或直接发送文字。",
                chat_id=chat_id,
            )
            return ""
        return transcript

    async def _download_and_transcribe_audio(
        self,
        *,
        file_id: str,
        file_name: str,
        mime_type: str,
        settings: Any,
    ) -> str:
        file_info = await self._call_api(settings, "getFile", {"file_id": file_id})
        file_path = str(((file_info.get("result") or {}).get("file_path")) or "").strip()
        if not file_path:
            raise RuntimeError(f"Telegram getFile did not return file_path for {file_id}")

        suffix = _guess_audio_suffix(file_name=file_name, mime_type=mime_type, fallback_path=file_path)
        with tempfile.TemporaryDirectory(prefix="roughcut-telegram-audio-") as tmpdir:
            workdir = Path(tmpdir)
            source_path = workdir / f"source{suffix}"
            wav_path = workdir / "source.wav"
            await self._download_telegram_file(settings, file_path=file_path, output_path=source_path)
            await extract_audio(source_path, wav_path)
            provider = get_transcription_provider()
            transcription_prompt = build_transcription_prompt(
                source_name=Path(file_path).name,
                workflow_template=None,
                review_memory=None,
                dialect_profile=getattr(settings, "transcription_dialect", None),
            )
            result = await provider.transcribe(
                wav_path,
                language="zh-CN",
                prompt=transcription_prompt or None,
            )
        return _compact_text(" ".join(str(segment.text or "").strip() for segment in result.segments if str(segment.text or "").strip()))

    async def _download_telegram_file(self, settings: Any, *, file_path: str, output_path: Path) -> Path:
        url = (
            f"{str(settings.telegram_bot_api_base_url).rstrip('/')}"
            f"/file/bot{str(settings.telegram_bot_token).strip()}/{file_path.lstrip('/')}"
        )
        timeout = httpx.Timeout(65.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
        response.raise_for_status()
        output_path.write_bytes(response.content)
        return output_path

    async def _handle_callback_query(self, callback_query: dict[str, Any]) -> None:
        callback_query_id = str(callback_query.get("id") or "").strip()
        message = callback_query.get("message") or {}
        actual_chat_id = str((message.get("chat") or {}).get("id") or "").strip()
        settings = get_settings()
        if not is_allowed_chat(settings, actual_chat_id):
            if callback_query_id:
                await self._answer_callback_query(callback_query_id, text="当前会话未授权。")
            return
        callback_ref = _extract_review_callback_reference(str(callback_query.get("data") or ""))
        if callback_ref is None:
            if callback_query_id:
                await self._answer_callback_query(callback_query_id, text="未识别审核操作。")
            return
        kind, job_id, action = callback_ref
        if kind != _REVIEW_KIND_FINAL:
            if callback_query_id:
                await self._answer_callback_query(callback_query_id, text="当前仅支持成片审核快捷按钮。")
            return
        reply_text = _FINAL_REVIEW_CALLBACK_ACTION_TEXT.get(action)
        if not reply_text:
            if callback_query_id:
                await self._answer_callback_query(callback_query_id, text="未识别审核操作。")
            return
        if callback_query_id:
            await self._answer_callback_query(
                callback_query_id,
                text=_FINAL_REVIEW_CALLBACK_ACK_TEXT.get(action, "已接收审核操作"),
            )
        await self._handle_final_review_reply(job_id, reply_text, reply_chat_id=actual_chat_id)

    async def _handle_content_profile_reply(self, job_id: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        subtitle_followup_requested = _looks_like_content_profile_subtitle_followup(text)
        factory = get_session_factory()
        subtitle_review_candidate_count = 0
        async with factory() as session:
            review = await get_content_profile(job_id, session)
            if review.review_step_status == "done":
                await self._send_chat_text(f"任务 {job_id} 的内容摘要已经确认过了，无需重复提交。", chat_id=reply_chat_id)
                return
            if reply_chat_id and (subtitle_followup_requested or not _SIMPLE_APPROVAL_PATTERN.match(text)):
                await self._send_chat_text(
                    f"已收到任务 {job_id} 的审核意见，正在处理，请稍候。",
                    chat_id=reply_chat_id,
                )
            payload = (
                {}
                if _SIMPLE_APPROVAL_PATTERN.match(text)
                else await _interpret_content_profile_reply(review, text)
            )
            await confirm_content_profile(job_id, ContentProfileConfirmIn(**payload), session)
            if subtitle_followup_requested:
                report = await generate_report(job_id, session)
                subtitle_review_candidate_count = len(_build_pending_subtitle_candidates(report))
        if subtitle_followup_requested and subtitle_review_candidate_count > 0:
            await self._send_chat_text(
                (
                    f"已确认任务 {job_id} 的内容摘要；检测到你还要校对字幕，"
                    f"我现在把 {subtitle_review_candidate_count} 条待审字幕项发你。"
                ),
                chat_id=reply_chat_id,
            )
            await self.notify_subtitle_review(job_id)
            return
        if subtitle_followup_requested:
            await self._send_chat_text(
                (
                    f"已确认任务 {job_id} 的内容摘要；"
                    "自动字幕纠错没有产出候选，我现在改发全量字幕人工复核包。"
                ),
                chat_id=reply_chat_id,
            )
            await self.notify_subtitle_review(job_id, force_full_review=True)
            return
        await self._send_chat_text(f"已接收任务 {job_id} 的审核意见，系统正在校正内容摘要并继续后续流程。", chat_id=reply_chat_id)

    async def _handle_subtitle_reply(self, job_id: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        factory = get_session_factory()
        async with factory() as session:
            report = await generate_report(job_id, session)
            subtitle_review_artifacts = await _load_subtitle_review_artifacts(job_id, session)
            candidates = _build_pending_subtitle_candidates(report)
            if not candidates:
                full_review_lines = await _load_full_subtitle_review_lines(job_id, session)
                if not full_review_lines:
                    artifact_lines = _build_subtitle_review_artifact_lines(subtitle_review_artifacts)
                    if artifact_lines:
                        await self._send_chat_text(
                            "\n".join(
                                [
                                    f"任务 {job_id} 当前没有可复核的字幕内容。",
                                    "",
                                    "最新字幕审校状态：",
                                    *artifact_lines,
                                    "",
                                    "字幕审核只处理字幕行和术语候选；如果你要改的是摘要，请回到内容摘要审核消息。",
                                ]
                            ),
                            chat_id=reply_chat_id,
                        )
                        return
                    await self._send_chat_text(f"任务 {job_id} 当前没有可复核的字幕内容。", chat_id=reply_chat_id)
                    return
                accept_all, actions = _interpret_full_subtitle_review_reply(text, full_review_lines)
                if accept_all:
                    await self._send_chat_text(
                        f"已确认任务 {job_id} 的全量字幕人工复核，无需字幕修改。",
                        chat_id=reply_chat_id,
                    )
                    return
                if not actions:
                    await self._send_chat_text(
                        "当前是全量字幕人工复核。请回复“全部通过”，或使用类似“L17改成 狐蝠工业，L18通过”的格式。",
                        chat_id=reply_chat_id,
                    )
                    return
                applied = await _apply_full_subtitle_review_actions(job_id, actions, session)
                await self._send_chat_text(
                    f"已应用任务 {job_id} 的 {applied} 条全量字幕人工复核修改。",
                    chat_id=reply_chat_id,
                )
                return
            actions = await _interpret_subtitle_review_reply(text, candidates)
            if not actions:
                await self._send_chat_text(
                    "没有识别出可执行的字幕审核动作。请回复“全部通过”或类似“S1通过，S2改成 xxx，S3拒绝”的格式。",
                    chat_id=reply_chat_id,
                )
                return
            action_request = ReviewApplyRequest(
                actions=[
                    ReviewActionCreate(
                        target_type="subtitle_correction",
                        target_id=uuid.UUID(item["correction_id"]),
                        action=item["action"],
                        override_text=item.get("override_text"),
                    )
                    for item in actions
                ]
            )
            from roughcut.api.jobs import apply_review

            result = await apply_review(job_id, action_request, session)
        await self._send_chat_text(f"已应用任务 {job_id} 的 {int(result.get('applied') or 0)} 条字幕审核意见。", chat_id=reply_chat_id)

    async def _handle_final_review_reply(self, job_id: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                await self._send_chat_text(f"任务 {job_id} 不存在。", chat_id=reply_chat_id)
                return
            review_step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "final_review")
                )
            ).scalar_one_or_none()
            if review_step is None:
                await self._send_chat_text(f"任务 {job_id} 当前没有成片审核节点。", chat_id=reply_chat_id)
                return
            if review_step.status == "done":
                await self._send_chat_text(f"任务 {job_id} 的成片已经确认过了，无需重复提交。", chat_id=reply_chat_id)
                return

            now = datetime.now(timezone.utc)
            note = str(text or "").strip()
            metadata = dict(review_step.metadata_ or {})
            subtitle_applied = 0
            if _looks_like_subtitle_review_reply(note):
                report = await generate_report(job_id, session)
                candidates = _build_pending_subtitle_candidates(report)
                if candidates:
                    actions = await _interpret_subtitle_review_reply(note, candidates)
                    if actions:
                        from roughcut.api.jobs import apply_review

                        action_request = ReviewApplyRequest(
                            actions=[
                                ReviewActionCreate(
                                    target_type="subtitle_correction",
                                    target_id=uuid.UUID(item["correction_id"]),
                                    action=item["action"],
                                    override_text=item.get("override_text"),
                                )
                                for item in actions
                            ]
                        )
                        result = await apply_review(job_id, action_request, session)
                        subtitle_applied = int(result.get("applied") or 0)
                        metadata["subtitle_review_applied_at"] = now.isoformat()
                        metadata["subtitle_review_applied_count"] = subtitle_applied
                        review_step.metadata_ = metadata
                        await session.refresh(job)
                        await session.refresh(review_step)

            if _SIMPLE_APPROVAL_PATTERN.match(note) or _FINAL_APPROVAL_PATTERN.search(note):
                mark_final_review_approved(
                    review_step=review_step,
                    job=job,
                    now=now,
                    approved_via="telegram",
                    metadata_updates=metadata,
                )
                await session.commit()
                if subtitle_applied > 0:
                    await self._send_chat_text(
                        f"已应用任务 {job_id} 的 {subtitle_applied} 条字幕审核意见，并确认成片通过，系统继续后续流程。",
                        chat_id=reply_chat_id,
                    )
                else:
                    await self._send_chat_text(f"已确认任务 {job_id} 的成片，系统继续后续流程。", chat_id=reply_chat_id)
                return

            rerun_plan = _combine_final_review_rerun_plans(_build_final_review_rerun_plans(note))
            if rerun_plan is not None:
                review_user_feedback = _extract_final_review_content_profile_feedback(note)
                from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun

                steps = (
                    await session.execute(
                        select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.id.asc())
                    )
                ).scalars().all()
                await _reset_job_for_quality_rerun(
                    session,
                    job,
                    steps,
                    rerun_steps=list(rerun_plan.rerun_steps),
                    issue_codes=[f"manual_review:{rerun_plan.category}"],
                )
                first_step = next((step for step in steps if step.step_name == rerun_plan.trigger_step), None)
                apply_final_review_rerun_metadata(
                    first_step=first_step,
                    rerun_plan=rerun_plan,
                    note=note,
                    now=now,
                    review_user_feedback=review_user_feedback,
                )
                await session.commit()
                target_text = f"目标：{', '.join(rerun_plan.targets)}；" if rerun_plan.targets else ""
                await self._send_chat_text(
                    f"已记录任务 {job_id} 的成片修改意见，{target_text}并按“{rerun_plan.label}”触发重跑："
                    f"{' -> '.join(rerun_plan.rerun_steps)}。",
                    chat_id=reply_chat_id,
                )
                return

            mark_final_review_pending(
                review_step=review_step,
                job=job,
                now=now,
                detail=(
                    f"已应用 {subtitle_applied} 条字幕审核意见，任务保持暂停，等待人工确认成片后再继续。"
                    if subtitle_applied > 0
                    else "已收到成片修改意见，任务保持暂停，等待人工处理后再继续。"
                ),
                note=note,
                via="telegram",
                metadata_updates=metadata,
            )
            await session.commit()
        if subtitle_applied > 0:
            await self._send_chat_text(
                f"已应用任务 {job_id} 的 {subtitle_applied} 条字幕审核意见；当前成片仍保持暂停。确认无误后可直接回复“成片通过”继续。",
                chat_id=reply_chat_id,
            )
        else:
            await self._send_chat_text(
                f"已记录任务 {job_id} 的成片修改意见，当前不会继续生成平台文案。请修订后重新送审，或直接回复“通过”继续。",
                chat_id=reply_chat_id,
            )

    async def _poll_agent_tasks(self) -> None:
        settings = get_settings()
        if not telegram_agent_enabled(settings):
            return
        for record in pending_notification_records():
            payload = get_agent_task_status(record.task_id)
            status = str(payload.get("status") or "").strip().lower()
            if status not in {"success", "failed", "cancelled"}:
                continue
            result_excerpt = str(payload.get("result_excerpt") or "").strip()
            error_text = str(payload.get("error_text") or "").strip()
            lines = [
                f"Agent 任务完成：{record.task_id}",
                f"- preset：{record.provider}/{record.preset}",
                f"- 状态：{status}",
            ]
            if result_excerpt:
                lines.extend(["结果摘要：", result_excerpt])
            if error_text:
                lines.extend(["错误：", error_text])
            await self._send_text("\n".join(lines))
            mark_task_notified(record.task_id)

    async def _poll_review_notifications(self) -> None:
        settings = get_settings()
        if not _telegram_review_ready(settings):
            return
        for record in pending_review_notifications():
            try:
                job_id = uuid.UUID(str(record.job_id))
            except (TypeError, ValueError):
                mark_review_notification_failed(
                    record.notification_id,
                    error_text=f"invalid_job_id:{record.job_id}",
                )
                continue
            try:
                if record.kind == _REVIEW_KIND_CONTENT:
                    await self.notify_content_profile_review(job_id)
                elif record.kind == _REVIEW_KIND_SUBTITLE:
                    await self.notify_subtitle_review(job_id, force_full_review=bool(record.force_full_review))
                elif record.kind == _REVIEW_KIND_FINAL:
                    await self.notify_final_review(job_id)
                else:
                    mark_review_notification_failed(
                        record.notification_id,
                        error_text=f"unknown_review_kind:{record.kind}",
                    )
                    continue
            except Exception as exc:
                updated = reschedule_review_notification(
                    record.notification_id,
                    error_text=str(exc),
                )
                logger.exception(
                    "Queued Telegram review notification failed job=%s kind=%s attempt=%s status=%s",
                    record.job_id,
                    record.kind,
                    int(getattr(updated, "attempt_count", 0) or 0),
                    str(getattr(updated, "status", "pending") or "pending"),
                )
                continue
            mark_review_notification_delivered(record.notification_id)

    async def _resolve_review_delivery(
        self,
        *,
        kind: str,
        job_id: uuid.UUID,
        signature: str,
    ) -> tuple[bool, int, str]:
        round_number = 1
        step_name = _REVIEW_STEP_NAME_BY_KIND.get(kind)
        if not step_name:
            return True, round_number, _format_review_round_label(round_number)

        factory = get_session_factory()
        async with factory() as session:
            step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == step_name)
                )
            ).scalar_one_or_none()
            if step is None:
                return True, round_number, _format_review_round_label(round_number)
            metadata = dict(step.metadata_ or {})
            round_number = _coerce_positive_int(metadata.get("review_round"), default=1)
            notifications = dict(metadata.get("telegram_review_notifications") or {})
            last_sent = dict(notifications.get(kind) or {})
            if (
                _coerce_positive_int(last_sent.get("round"), default=0) == round_number
                and str(last_sent.get("signature") or "").strip() == signature
            ):
                return False, round_number, _format_review_round_label(round_number)
        return True, round_number, _format_review_round_label(round_number)

    async def _record_review_delivery(
        self,
        *,
        kind: str,
        job_id: uuid.UUID,
        round_number: int,
        round_label: str,
        signature: str,
    ) -> None:
        step_name = _REVIEW_STEP_NAME_BY_KIND.get(kind)
        if not step_name:
            return

        factory = get_session_factory()
        async with factory() as session:
            step = (
                await session.execute(
                    select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == step_name)
                )
            ).scalar_one_or_none()
            if step is None:
                return
            metadata = dict(step.metadata_ or {})
            metadata["review_round"] = max(
                round_number,
                _coerce_positive_int(metadata.get("review_round"), default=1),
            )
            notifications = dict(metadata.get("telegram_review_notifications") or {})
            notifications[kind] = {
                "round": round_number,
                "round_label": round_label,
                "signature": signature,
                "sent_at": datetime.now(timezone.utc).isoformat(),
            }
            metadata["telegram_review_notifications"] = notifications
            step.metadata_ = metadata
            await session.commit()

    async def _send_review_message(
        self,
        kind: str,
        job_id: uuid.UUID,
        body: str,
        *,
        thumbnails: list[TelegramReviewThumbnail] | None = None,
        videos: list[TelegramReviewVideo] | None = None,
        variant_timeline_bundle: dict[str, Any] | None = None,
    ) -> None:
        settings = get_settings()
        chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
        if not _telegram_review_ready(settings) or not chat_id:
            return {"sent": False, "round_number": 1, "round_label": _format_review_round_label(1)}

        signature = _build_review_delivery_signature(
            kind,
            body,
            thumbnails=thumbnails,
            videos=videos,
        )
        should_send, round_number, round_label = await self._resolve_review_delivery(
            kind=kind,
            job_id=job_id,
            signature=signature,
        )
        if not should_send:
            logger.info(
                "Skipping duplicate Telegram review notification job=%s kind=%s round=%s",
                job_id,
                kind,
                round_number,
            )
            return {"sent": False, "round_number": round_number, "round_label": round_label}

        decorated_body = _prepend_review_round_context(
            body,
            kind=kind,
            round_label=round_label,
        )
        chunks = _split_review_message(decorated_body)
        total = len(chunks)
        anchor_message_id: int | None = None
        reply_markup = _build_review_reply_markup(kind, job_id, variant_timeline_bundle=variant_timeline_bundle)
        for index, chunk in enumerate(chunks, start=1):
            header = f"【RC:{kind}:{job_id}】"
            prefix = f"{header} ({index}/{total})" if total > 1 else header
            message_id = await self._send_text(
                f"{prefix}\n{chunk}",
                reply_markup=reply_markup if index == 1 else None,
            )
            if anchor_message_id is None:
                anchor_message_id = message_id
        thumbnail_items = list(thumbnails or [])
        if len(thumbnail_items) > 1:
            try:
                await self._send_chat_photo_group(
                    [
                        TelegramReviewThumbnail(
                            path=item.path,
                            caption=_prepend_review_round_to_caption(item.caption, round_label=round_label),
                        )
                        for item in thumbnail_items
                    ],
                    chat_id=chat_id,
                    reply_to_message_id=anchor_message_id,
                )
            except Exception:
                logger.exception("Failed to send review thumbnail group for job %s", job_id)
        else:
            for item in thumbnail_items:
                try:
                    await self._send_chat_photo(
                        item.path,
                        chat_id=chat_id,
                        caption=_prepend_review_round_to_caption(item.caption, round_label=round_label),
                        reply_to_message_id=anchor_message_id,
                    )
                except Exception:
                    logger.exception("Failed to send review thumbnail for job %s", job_id)
        for item in videos or []:
            try:
                await self._send_chat_video(
                    item.path,
                    chat_id=chat_id,
                    caption=_prepend_review_round_to_caption(item.caption, round_label=round_label),
                    reply_to_message_id=anchor_message_id,
                )
            except Exception:
                logger.exception("Failed to send review video for job %s", job_id)
        await self._record_review_delivery(
            kind=kind,
            job_id=job_id,
            round_number=round_number,
            round_label=round_label,
            signature=signature,
        )
        return {"sent": True, "round_number": round_number, "round_label": round_label}

    async def _send_text(self, text: str, *, reply_markup: dict[str, Any] | None = None) -> int | None:
        settings = get_settings()
        chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
        if not _telegram_service_ready(settings) or not chat_id:
            return None
        return await self._send_chat_text(text, chat_id=chat_id, reply_markup=reply_markup)

    async def _send_chat_text(
        self,
        text: str,
        *,
        chat_id: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> int | None:
        settings = get_settings()
        if not _telegram_service_ready(settings) or not str(chat_id or "").strip():
            return None
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": text,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        data = await self._call_api(settings, "sendMessage", payload)
        return _extract_message_id(data)

    async def _answer_callback_query(self, callback_query_id: str, *, text: str = "") -> None:
        settings = get_settings()
        callback_id = str(callback_query_id or "").strip()
        if not _telegram_service_ready(settings) or not callback_id:
            return
        payload: dict[str, Any] = {"callback_query_id": callback_id}
        trimmed_text = str(text or "").strip()
        if trimmed_text:
            payload["text"] = trimmed_text[:200]
            payload["show_alert"] = False
        await self._call_api(settings, "answerCallbackQuery", payload)

    async def _send_chat_photo(
        self,
        photo_path: Path,
        *,
        chat_id: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        settings = get_settings()
        if not _telegram_service_ready(settings) or not str(chat_id or "").strip() or not photo_path.exists():
            return None
        payload: dict[str, Any] = {
            "chat_id": str(chat_id).strip(),
        }
        trimmed_caption = str(caption or "").strip()
        if trimmed_caption:
            payload["caption"] = trimmed_caption[:1024]
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        files = {
            "photo": (
                photo_path.name,
                photo_path.read_bytes(),
                "image/jpeg",
            )
        }
        data = await self._call_api(settings, "sendPhoto", payload, files=files)
        return _extract_message_id(data)

    async def _send_chat_photo_group(
        self,
        photos: list[TelegramReviewThumbnail],
        *,
        chat_id: str,
        reply_to_message_id: int | None = None,
    ) -> list[int]:
        settings = get_settings()
        if not _telegram_service_ready(settings) or not str(chat_id or "").strip():
            return []
        media: list[dict[str, Any]] = []
        files: dict[str, tuple[str, bytes, str]] = {}
        for index, item in enumerate(photos):
            if not item.path.exists():
                continue
            attach_name = f"photo{index}"
            entry: dict[str, Any] = {
                "type": "photo",
                "media": f"attach://{attach_name}",
            }
            trimmed_caption = str(item.caption or "").strip()
            if trimmed_caption:
                entry["caption"] = trimmed_caption[:1024]
            media.append(entry)
            files[attach_name] = (
                item.path.name,
                item.path.read_bytes(),
                "image/jpeg",
            )
        if not media:
            return []
        payload: dict[str, Any] = {
            "chat_id": str(chat_id).strip(),
            "media": json.dumps(media, ensure_ascii=False),
        }
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        data = await self._call_api(settings, "sendMediaGroup", payload, files=files)
        if not isinstance(data, list):
            return []
        message_ids: list[int] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            message_id = _extract_message_id(item)
            if message_id is not None:
                message_ids.append(message_id)
        return message_ids

    async def _send_chat_video(
        self,
        video_path: Path,
        *,
        chat_id: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        settings = get_settings()
        if not _telegram_service_ready(settings) or not str(chat_id or "").strip() or not video_path.exists():
            return None
        payload: dict[str, Any] = {"chat_id": str(chat_id).strip()}
        trimmed_caption = str(caption or "").strip()
        if trimmed_caption:
            payload["caption"] = trimmed_caption[:1024]
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        content_type = "video/mp4" if video_path.suffix.lower() == ".mp4" else "application/octet-stream"
        files = {
            "video": (
                video_path.name,
                video_path.read_bytes(),
                content_type,
            )
        }
        try:
            data = await self._call_api(settings, "sendVideo", payload, files=files)
        except Exception:
            document_files = {
                "document": (
                    video_path.name,
                    video_path.read_bytes(),
                    content_type,
                )
            }
            data = await self._call_api(settings, "sendDocument", payload, files=document_files)
        return _extract_message_id(data)

    async def _send_chat_document(
        self,
        document_path: Path,
        *,
        chat_id: str,
        caption: str = "",
        reply_to_message_id: int | None = None,
    ) -> int | None:
        settings = get_settings()
        if not _telegram_service_ready(settings) or not str(chat_id or "").strip() or not document_path.exists():
            return None
        payload: dict[str, Any] = {"chat_id": str(chat_id).strip()}
        trimmed_caption = str(caption or "").strip()
        if trimmed_caption:
            payload["caption"] = trimmed_caption[:1024]
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = str(reply_to_message_id)
        files = {
            "document": (
                document_path.name,
                document_path.read_bytes(),
                "text/plain; charset=utf-8",
            )
        }
        data = await self._call_api(settings, "sendDocument", payload, files=files)
        return _extract_message_id(data)

    async def _build_content_profile_thumbnails(
        self,
        job: Job,
        *,
        kind: str,
    ) -> list[TelegramReviewThumbnail]:
        thumbnails: list[TelegramReviewThumbnail] = []
        for index in range(3):
            try:
                path = await _ensure_content_profile_thumbnail(job, index=index)
            except Exception as exc:
                logger.warning(
                    "Failed to prepare content profile thumbnail %s for job %s: %s",
                    index,
                    job.id,
                    exc,
                )
                continue
            thumbnails.append(
                TelegramReviewThumbnail(
                    path=path,
                    caption=f"【RC:{kind}:{job.id}】\n参考缩略图 {index + 1}/3",
                )
            )
        return thumbnails

    async def _call_api(
        self,
        settings: Any,
        method: str,
        payload: dict[str, Any],
        *,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        url = (
            f"{str(settings.telegram_bot_api_base_url).rstrip('/')}"
            f"/bot{str(settings.telegram_bot_token).strip()}/{method}"
        )
        timeout = httpx.Timeout(65.0, connect=10.0)
        for attempt in range(1, _TELEGRAM_API_MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if files:
                        response = await client.post(url, data=payload, files=files)
                    else:
                        response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok", False):
                    raise RuntimeError(str(data))
                return data
            except _TELEGRAM_API_RETRYABLE_EXCEPTIONS as exc:
                if attempt >= _TELEGRAM_API_MAX_ATTEMPTS:
                    raise
                delay = _telegram_api_retry_backoff_seconds(attempt)
                logger.warning(
                    "Telegram API %s transient failure on attempt %s/%s; retrying in %.1fs: %s",
                    method,
                    attempt,
                    _TELEGRAM_API_MAX_ATTEMPTS,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
        raise RuntimeError(f"Telegram API {method} exhausted retries")


def _telegram_api_retry_backoff_seconds(attempt: int) -> float:
    normalized_attempt = max(1, int(attempt))
    return float(min(4, normalized_attempt))


def _telegram_poll_failure_backoff_seconds(consecutive_failures: int) -> float:
    normalized_failures = max(1, int(consecutive_failures))
    return float(min(30, 5 * (2 ** (normalized_failures - 1))))


def _telegram_ready(settings: Any) -> bool:
    return _telegram_service_ready(settings)


def _telegram_service_ready(settings: Any) -> bool:
    return telegram_service_enabled(settings)


def _telegram_review_ready(settings: Any) -> bool:
    return telegram_review_enabled(settings)


def _extract_review_reference(text: str) -> tuple[str, uuid.UUID] | None:
    return telegram_review_parsing.extract_review_reference(text)


def _extract_review_reference_from_message(message: dict[str, Any]) -> tuple[str, uuid.UUID] | None:
    return telegram_review_parsing.extract_review_reference_from_message(message)


def _extract_review_callback_reference(data: str) -> tuple[str, uuid.UUID, str] | None:
    return telegram_review_parsing.extract_review_callback_reference(
        data,
        allowed_actions=_FINAL_REVIEW_CALLBACK_ACTION_TEXT,
    )


def _build_review_callback_data(kind: str, job_id: uuid.UUID, action: str) -> str | None:
    return telegram_review_parsing.build_review_callback_data(
        kind,
        job_id,
        action,
        allowed_actions=_FINAL_REVIEW_CALLBACK_ACTION_TEXT,
    )


def _build_final_review_reply_markup(
    job_id: uuid.UUID,
    *,
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first_row = [
        {
            "text": "成片通过",
            "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, "approve"),
        },
    ]
    if _final_review_has_high_risk_cuts(variant_timeline_bundle):
        edit_action = _final_review_edit_button_action(variant_timeline_bundle)
        first_row.append(
            {
                "text": _FINAL_REVIEW_CALLBACK_ACTION_TEXT.get(edit_action, _final_review_edit_button_text(variant_timeline_bundle)),
                "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, edit_action),
            }
        )
    first_row.append(
        {
            "text": "只改封面",
            "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, "cover"),
        }
    )
    return {
        "inline_keyboard": [
            first_row,
            [
                {
                    "text": "只改BGM",
                    "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, "music"),
                },
                {
                    "text": "只改平台文案",
                    "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, "platform"),
                },
            ],
            [
                {
                    "text": "数字人口播重做",
                    "callback_data": _build_review_callback_data(_REVIEW_KIND_FINAL, job_id, "avatar"),
                }
            ],
        ]
    }


def _build_review_reply_markup(
    kind: str,
    job_id: uuid.UUID,
    *,
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if kind == _REVIEW_KIND_FINAL:
        return _build_final_review_reply_markup(job_id, variant_timeline_bundle=variant_timeline_bundle)
    return None


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("text") or message.get("caption") or "").strip()


def _extract_audio_attachment(message: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("voice", "audio"):
        payload = message.get(key)
        if isinstance(payload, dict) and str(payload.get("file_id") or "").strip():
            return payload
    return None


def _guess_audio_suffix(*, file_name: str, mime_type: str, fallback_path: str) -> str:
    candidate = Path(str(file_name or fallback_path or "").strip()).suffix.lower()
    if candidate:
        return candidate
    normalized_mime = str(mime_type or "").strip().lower()
    if normalized_mime in _AUDIO_SUFFIX_BY_MIME:
        return _AUDIO_SUFFIX_BY_MIME[normalized_mime]
    return ".ogg"


def _normalize_spoken_command_text(text: str) -> str:
    normalized = _compact_text(text)
    if not normalized:
        return ""
    compact = re.sub(r"[\s，。,！？!?:：；;、\"'“”‘’（）()]+", "", normalized).lower()
    if compact in {"状态", "查看状态", "服务状态", "系统状态", "当前状态", "status"}:
        return "/status"
    if compact in {"谁", "我是谁", "id", "chatid", "会话id", "会话编号"}:
        return "/whoami"
    if compact in {"最近任务", "查看任务", "任务列表", "jobs", "joblist"}:
        return "/jobs"
    if compact in {"最近agent任务", "agent任务", "agent任务列表", "tasks", "tasklist"}:
        return "/tasks"
    if compact in {"预设", "预设列表", "查看预设", "presets"}:
        return "/presets"

    confirm_match = re.match(r"^(?:确认|确认任务|提交确认)([A-Za-z0-9-]+)$", compact, re.IGNORECASE)
    if confirm_match:
        return f"/confirm {confirm_match.group(1)}"

    cancel_match = re.match(r"^(?:取消|取消任务|撤销任务)([A-Za-z0-9-]+)$", compact, re.IGNORECASE)
    if cancel_match:
        return f"/cancel {cancel_match.group(1)}"

    task_match = re.match(r"^(?:查看任务|任务详情|查看agent任务|agent任务详情)([A-Za-z0-9-]+)$", compact, re.IGNORECASE)
    if task_match:
        return f"/task {task_match.group(1)}"

    return normalized


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _looks_like_subtitle_review_reply(text: str) -> bool:
    return telegram_review_parsing.looks_like_subtitle_review_reply(text)


def _looks_like_content_profile_subtitle_followup(text: str) -> bool:
    return telegram_review_parsing.looks_like_content_profile_subtitle_followup(text)
def _extract_latest_final_review_rerun_context(steps: list[JobStep]) -> dict[str, Any] | None:
    latest: tuple[datetime, dict[str, Any]] | None = None
    for step in steps or []:
        metadata = dict(step.metadata_ or {})
        targets = list(metadata.get("review_rerun_targets") or [])
        feedback = str(metadata.get("review_feedback") or "").strip()
        if not targets and not feedback:
            continue
        updated_at = metadata.get("updated_at")
        try:
            updated = datetime.fromisoformat(str(updated_at))
        except Exception:
            updated = datetime.min.replace(tzinfo=timezone.utc)
        payload = {
            "step_name": step.step_name,
            "targets": [str(item).strip() for item in targets if str(item).strip()],
            "feedback": feedback,
            "label": str(metadata.get("detail") or "").strip(),
            "focus": str(metadata.get("review_rerun_focus") or "").strip(),
        }
        if latest is None or updated > latest[0]:
            latest = (updated, payload)
    return latest[1] if latest is not None else None


def _build_final_review_rerun_context_lines(context: dict[str, Any] | None) -> list[str]:
    if not isinstance(context, dict) or not context:
        return []
    lines: list[str] = []
    targets = [str(item).strip() for item in (context.get("targets") or []) if str(item).strip()]
    if targets:
        lines.append(f"- 本次重跑目标：{', '.join(targets)}")
    step_name = str(context.get("step_name") or "").strip()
    if step_name:
        lines.append(f"- 触发起点：{step_name}")
    focus = str(context.get("focus") or "").strip()
    if focus:
        lines.append(f"- 风险焦点：{focus}")
    feedback = str(context.get("feedback") or "").strip()
    if feedback:
        snippet = feedback if len(feedback) <= 80 else feedback[:79].rstrip() + "…"
        lines.append(f"- 上次修改意见：{snippet}")
    return lines


def _extract_message_id(data: dict[str, Any]) -> int | None:
    result = data.get("result")
    if not isinstance(result, dict):
        return None
    try:
        return int(result.get("message_id"))
    except (TypeError, ValueError):
        return None


def _build_review_delivery_signature(
    kind: str,
    body: str,
    *,
    thumbnails: list[TelegramReviewThumbnail] | None = None,
    videos: list[TelegramReviewVideo] | None = None,
) -> str:
    payload = {
        "kind": kind,
        "body": str(body or "").strip(),
        "thumbnail_captions": [str(item.caption or "").strip() for item in thumbnails or []],
        "video_captions": [str(item.caption or "").strip() for item in videos or []],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _coerce_positive_int(value: object, *, default: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _to_chinese_count(value: int) -> str:
    digits = {0: "零", 1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
    number = max(0, int(value))
    if number < 10:
        return digits[number]
    if number == 10:
        return "十"
    if number < 20:
        return f"十{digits[number % 10]}"
    if number < 100:
        tens, ones = divmod(number, 10)
        ones_text = digits[ones] if ones else ""
        return f"{digits[tens]}十{ones_text}"
    return str(number)


def _format_review_round_label(round_number: int) -> str:
    ordinal = _to_chinese_count(_coerce_positive_int(round_number, default=1))
    suffix = "审核" if round_number <= 1 else "复核"
    return f"第{ordinal}次{suffix}"


def _prepend_review_round_context(body: str, *, kind: str, round_label: str) -> str:
    title = _REVIEW_KIND_TITLES.get(kind, "审核")
    content = str(body or "").strip()
    lines = [
        f"审核阶段：{round_label}",
        f"审核类型：{title}",
    ]
    if content:
        lines.extend(["", content])
    return "\n".join(lines).strip()


def _prepend_review_round_to_caption(caption: str, *, round_label: str) -> str:
    lines = str(caption or "").splitlines()
    if not lines:
        return f"审核阶段：{round_label}"
    if any(line.strip() == f"审核阶段：{round_label}" for line in lines):
        return "\n".join(lines).strip()
    return "\n".join([lines[0], f"审核阶段：{round_label}", *lines[1:]]).strip()


def _split_review_message(text: str, *, limit: int = 3200) -> list[str]:
    lines = [line for line in str(text or "").splitlines()]
    if not lines:
        return [""]

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for line in lines:
        line_length = len(line) + 1
        if current and current_length + line_length > limit:
            chunks.append("\n".join(current).strip())
            current = [line]
            current_length = line_length
            continue
        current.append(line)
        current_length += line_length
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def _build_content_profile_review_message(
    *,
    source_name: str,
    job_id: uuid.UUID,
    locale: str = "zh-CN",
    review: Any,
    draft: dict[str, Any],
    packaging_assets: dict[str, list[dict[str, Any]]],
    packaging_config: dict[str, Any],
    packaging_plan: dict[str, Any] | None = None,
    config: Any | None = None,
    avatar_materials: Any | None = None,
) -> str:
    automation = draft.get("automation_review") if isinstance(draft, dict) else {}
    identity_review = draft.get("identity_review") if isinstance(draft, dict) else {}
    review_reasons = list(automation.get("review_reasons") or []) if isinstance(automation, dict) else []
    blocking_reasons = list(automation.get("blocking_reasons") or []) if isinstance(automation, dict) else []
    effective_packaging_plan = packaging_plan or _build_packaging_plan_from_config(
        packaging_assets,
        packaging_config,
    )
    review_checks = _build_review_checks(
        enhancement_modes=list(review.enhancement_modes or []),
        config=config,
        packaging_config=packaging_config,
        packaging_plan=effective_packaging_plan,
        avatar_materials=avatar_materials,
    )
    content_lines = []
    summary = _display_value(draft.get("summary"))
    hook_line = _display_value(draft.get("hook_line"))
    visible_text = _display_value(draft.get("visible_text"))
    video_theme = _display_value(draft.get("video_theme"))
    source_subject_type = _display_value(draft.get("subject_type"))
    subject_type_contexts = [summary, hook_line, visible_text, video_theme, source_subject_type]
    for key, label in _CONTENT_FIELD_ORDER:
        if key == "subject_type":
            content_lines.append(
                f"- {label}：{_display_subject_type(draft.get(key), locale=locale, context_texts=subject_type_contexts)}"
            )
        else:
            content_lines.append(f"- {label}：{_display_value(draft.get(key))}")
    keyword_candidates = _build_review_keyword_candidates(
        draft,
        source_name=source_name,
    )
    split_keyword_candidates = _split_review_keywords(keyword_candidates)
    draft_keywords = _extract_final_review_keywords(
        draft,
        source_name=source_name,
    )
    if draft_keywords:
        content_lines.append(f"- 关键词：{_join_non_empty(draft_keywords)}")
        extra_suggestions = [item for item in split_keyword_candidates if item not in draft_keywords]
        if extra_suggestions:
            content_lines.append(f"- 关键词建议：{_join_non_empty(extra_suggestions)}")
    else:
        content_lines.append(f"- 关键词：{_join_non_empty(split_keyword_candidates) or '待补充'}")

    reference_identity = []
    if str(draft.get("subject_brand") or "").strip():
        reference_identity.append(f"品牌：{draft.get('subject_brand')}")
    if str(draft.get("subject_model") or "").strip():
        reference_identity.append(f"型号：{draft.get('subject_model')}")

    lines = [
        f"任务：{source_name}",
        f"Job ID：{job_id}",
        "",
        "剪辑配置：",
        "- 当前审核已继承当前激活的剪辑配置；如需改工作流、增强模式、数字人、包装或风格，请直接回复说明。",
        "- 审核就绪检查：",
        *[f"  - {item['status']} | {item['label']}：{item['detail']}" for item in review_checks],
        "",
        "内容核对：",
        *content_lines,
        "",
        "字段含义：",
        "- 画面文字：从字幕/画面中可直接识别的关键可见文本，不是主题总结。",
        "- 校对备注：记录风险点、误读点或复核结论。",
        "- 补充上下文：拍摄场景、对比规则、素材异常/后续处理约束。",
    ]

    if reference_identity:
        lines.extend(
            [
                "",
                "系统识别参考：",
                f"- {'；'.join(reference_identity)}",
            ]
        )

    if isinstance(automation, dict) and automation:
        lines.extend(
            [
                "",
                "审核原因：",
                (
                    f"- 自动审核得分：{float(automation.get('score') or 0.0):.2f} / "
                    f"阈值 {float(automation.get('threshold') or 0.0):.2f}"
                ),
                f"- 需人工复核：{'; '.join(review_reasons) if review_reasons else '无'}",
                f"- 阻塞原因：{'; '.join(blocking_reasons) if blocking_reasons else '无'}",
            ]
        )

    identity_lines = _build_identity_review_lines(identity_review)
    if identity_lines:
        lines.extend(
            [
                "",
                "主体证据包：",
                *identity_lines,
            ]
        )

    evidence_lines = _build_content_profile_evidence_lines(draft)
    if evidence_lines:
        lines.extend(
            [
                "",
                "OCR / 转写证据：",
                *evidence_lines,
            ]
        )

    lines.extend(
        [
            "",
            "字幕摘录：",
            str(draft.get("reviewed_subtitle_excerpt") or draft.get("transcript_excerpt") or "无"),
            "",
            "回复方式：",
            "1. 直接回复“通过”即可继续后续流程。",
            "2. 也可以直接回复自然语言修改意见，系统会按前端同款审核字段解析。",
            "3. 如需切换剪辑配置，或直接改工作流、增强模式、数字人、包装和风格，也可以直接在回复里说明。",
        ]
    )
    return "\n".join(lines)


def _build_final_review_message(
    *,
    source_name: str,
    job_id: uuid.UUID,
    workflow_mode: str,
    enhancement_modes: list[str],
    render_outputs: dict[str, Any],
    content_profile: dict[str, Any] | None = None,
    subtitle_report: Any | None = None,
    variant_timeline_bundle: dict[str, Any] | None = None,
    rerun_context: dict[str, Any] | None = None,
) -> str:
    summary = str((content_profile or {}).get("summary") or (content_profile or {}).get("video_theme") or "").strip()
    keywords = _join_non_empty(
        _extract_final_review_keywords(
            content_profile,
            source_name=source_name,
        )
    )
    subtitle_hints = _build_final_review_subtitle_hints(subtitle_report)
    variant_lines = []
    for label, key in (
        ("主成片", "packaged_mp4"),
        ("素板", "plain_mp4"),
        ("数字人版", "avatar_mp4"),
        ("AI 特效版", "ai_effect_mp4"),
    ):
        path = str(render_outputs.get(key) or "").strip()
        if path:
            variant_lines.append(f"- {label}：{Path(path).name}")
    cover = str(render_outputs.get("cover") or "").strip()
    cover_text = Path(cover).name if cover else "未生成"
    lines = [
        f"任务：{source_name}",
        f"Job ID：{job_id}",
        "",
        "剪辑配置：",
        "- 当前成片已按当前任务的剪辑配置生成；如需只改封面、BGM、平台文案或数字人口播，可直接回复。",
        "",
        "成片审核：",
        f"- 封面：{cover_text}",
        *variant_lines,
        "- 审片包：默认发送 3 段压缩预览，不直接上传整片，避免 Telegram 大文件卡顿。",
        f"- 内容摘要：{summary or '待补充'}",
        f"- 关键词：{keywords or '待补充'}",
    ]
    rerun_lines = _build_final_review_rerun_context_lines(rerun_context)
    if rerun_lines:
        lines.extend(
            [
                "",
                "重跑说明：",
                *rerun_lines,
            ]
        )
    if subtitle_hints:
        lines.extend(
            [
                "",
                "字幕复核提醒：",
                *subtitle_hints,
            ]
        )
    diagnostics_lines = _build_final_review_diagnostics_lines(variant_timeline_bundle)
    if diagnostics_lines:
        lines.extend(
            [
                "",
                "剪辑风险提示：",
                *diagnostics_lines,
            ]
        )
    validation_lines = _build_final_review_validation_lines(variant_timeline_bundle)
    if validation_lines:
        lines.extend(
            [
                "",
                "时间轴校验：",
                *validation_lines,
            ]
        )
    lines.extend(
        [
            "",
            "回复方式：",
            "1. 请结合下面的压缩片段、摘要和关键词一起审片。",
            "2. 可直接点下方快捷按钮，也可回复“通过”或“成片通过”继续平台文案和后续定稿。",
            "3. 也可以在同一条回复里写字幕动作，例如“S1通过，S2改成 Olight”。",
            "4. 回复修改意见会暂停在成片审核，不再自动继续。",
            "5. 修改完成后可继续在同一条消息下回复“通过”。",
            "",
            "快捷回复示例：",
            "- 成片通过",
            "- S1通过，S2改成 Olight",
            "- 只改封面",
            "- 只改BGM",
            "- 只改平台文案",
            "- 数字人口播重做",
        ]
    )
    return "\n".join(lines)


def _build_final_review_diagnostics_lines(variant_timeline_bundle: dict[str, Any] | None) -> list[str]:
    timeline_rules = (
        variant_timeline_bundle.get("timeline_rules")
        if isinstance(variant_timeline_bundle, dict)
        else None
    )
    diagnostics = (
        timeline_rules.get("diagnostics")
        if isinstance(timeline_rules, dict)
        else None
    )
    if not isinstance(diagnostics, dict):
        return []

    review_flags = diagnostics.get("review_flags") if isinstance(diagnostics.get("review_flags"), dict) else {}
    high_risk_cuts = [
        item
        for item in (diagnostics.get("high_risk_cuts") or [])
        if isinstance(item, dict)
    ]
    llm_cut_review = diagnostics.get("llm_cut_review") if isinstance(diagnostics.get("llm_cut_review"), dict) else {}
    high_energy_keeps = [
        item
        for item in (diagnostics.get("high_energy_keeps") or [])
        if isinstance(item, dict)
    ]

    lines: list[str] = []
    if review_flags.get("review_recommended"):
        reasons = [str(item).strip() for item in (review_flags.get("review_reasons") or []) if str(item).strip()]
        if reasons:
            lines.append(f"- 建议人工复核：{'；'.join(reasons[:2])}")
        else:
            lines.append("- 建议人工复核：检测到高风险剪辑边界。")

    if llm_cut_review.get("reviewed"):
        candidate_count = int(llm_cut_review.get("candidate_count") or 0)
        restored_cut_count = int(llm_cut_review.get("restored_cut_count") or 0)
        remaining_high_risk = len(high_risk_cuts)
        summary = str(llm_cut_review.get("summary") or "").strip()
        provider = str(llm_cut_review.get("provider") or "").strip()
        provider_text = f"（{provider}）" if provider else ""
        line = (
            f"- LLM 复核{provider_text}：审了 {candidate_count} 个高风险 cut，"
            f"恢复 {restored_cut_count} 个，当前剩余 {remaining_high_risk} 个高风险 cut。"
        )
        if summary:
            line = f"{line} {summary}"
        lines.append(line)

    for item in high_risk_cuts[:2]:
        start = round(float(item.get("start", 0.0) or 0.0), 2)
        end = round(float(item.get("end", 0.0) or 0.0), 2)
        boundary_keep_energy = round(float(item.get("boundary_keep_energy", 0.0) or 0.0), 2)
        left_role = str(item.get("left_keep_role") or "unknown")
        right_role = str(item.get("right_keep_role") or "unknown")
        lines.append(
            f"- 高风险 cut {start:.2f}s-{end:.2f}s：边界能量 {boundary_keep_energy:.2f}，"
            f"左侧 {left_role} / 右侧 {right_role}"
        )

    if not lines and high_energy_keeps:
        top_keep = max(high_energy_keeps, key=lambda item: float(item.get("keep_energy", 0.0) or 0.0))
        start = round(float(top_keep.get("start", 0.0) or 0.0), 2)
        end = round(float(top_keep.get("end", 0.0) or 0.0), 2)
        keep_energy = round(float(top_keep.get("keep_energy", 0.0) or 0.0), 2)
        section_role = str(top_keep.get("section_role") or "unknown")
        lines.append(
            f"- 最高能量保留段 {start:.2f}s-{end:.2f}s：{section_role}，保留能量 {keep_energy:.2f}"
        )
    return lines


def _build_final_review_validation_lines(variant_timeline_bundle: dict[str, Any] | None) -> list[str]:
    validation = (
        variant_timeline_bundle.get("validation")
        if isinstance(variant_timeline_bundle, dict)
        else None
    )
    if not isinstance(validation, dict):
        return []

    issues = [str(item).strip() for item in (validation.get("issues") or []) if str(item).strip()]
    status = str(validation.get("status") or "").strip().lower()
    if not issues and status in {"", "ok"}:
        return []

    risk_label = "异常" if status == "error" else "风险"
    lines = [f"- 检测到 {len(issues)} 条{risk_label}，请重点核对特效版/横板字幕与声音是否对齐。"]
    for issue in issues[:3]:
        lines.append(f"- {issue}")
    if len(issues) > 3:
        lines.append(f"- 其余 {len(issues) - 3} 条已省略")
    return lines


async def _build_final_review_videos(
    job_id: uuid.UUID,
    render_outputs: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None = None,
    subtitle_report: Any | None = None,
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> list[TelegramReviewVideo]:
    variant_timeline_bundle = resolve_effective_variant_timeline_bundle(
        variant_timeline_bundle,
        render_outputs=render_outputs,
    )
    source_path = _resolve_final_review_video_source(render_outputs, variant_timeline_bundle=variant_timeline_bundle)
    if source_path is None:
        return []
    try:
        meta = await probe(source_path)
    except Exception as exc:
        logger.warning("Failed to probe final review source for job %s: %s", job_id, exc)
        return []

    subtitle_items = _extract_preview_subtitle_items(
        render_outputs,
        subtitle_report=subtitle_report,
        variant_timeline_bundle=variant_timeline_bundle,
    )
    clip_specs = _build_final_review_clip_specs(
        duration_sec=float(meta.duration or 0.0),
        subtitle_items=subtitle_items,
        keywords=_extract_final_review_keywords(content_profile),
        variant_timeline_bundle=variant_timeline_bundle,
    )
    videos: list[TelegramReviewVideo] = []
    for index, clip in enumerate(clip_specs, start=1):
        try:
            preview_path = await _ensure_final_review_preview(
                job_id=job_id,
                source_path=source_path,
                clip_index=index,
                start_sec=clip.start_sec,
                duration_sec=clip.duration_sec,
            )
        except Exception as exc:
            logger.warning("Failed to build final review preview %s for job %s: %s", index, job_id, exc)
            continue
        keyword_suffix = f" · 关键词 {clip.matched_keyword}" if clip.matched_keyword else ""
        videos.append(
            TelegramReviewVideo(
                path=preview_path,
                caption=(
                    f"【RC:{_REVIEW_KIND_FINAL}:{job_id}】\n"
                    f"预览 {index}/3 · {clip.label}{keyword_suffix} · "
                    f"{_format_time_range(clip.start_sec, clip.start_sec + clip.duration_sec)}\n"
                    f"字幕：{clip.transcript_excerpt or '本段无明显字幕'}"
                ),
            )
        )
    return videos


def _select_final_review_content_profile(artifacts: list[Artifact]) -> dict[str, Any]:
    return select_resolved_downstream_profile(list(artifacts or []))


def _resolve_final_review_video_source(
    render_outputs: dict[str, Any],
    *,
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> Path | None:
    _bundle_variant, bundle_source_path = _select_final_review_bundle_variant(variant_timeline_bundle)
    if bundle_source_path is not None:
        return bundle_source_path
    for key in ("packaged_mp4", "avatar_mp4", "ai_effect_mp4", "plain_mp4"):
        value = str(render_outputs.get(key) or "").strip()
        if not value:
            continue
        candidate = Path(value)
        if candidate.exists():
            return candidate
    return None


def _extract_final_review_keywords(
    content_profile: dict[str, Any] | None,
    source_name: str = "",
) -> list[str]:
    profile = dict(content_profile or {})
    seed_terms = _collect_review_keyword_seed_terms(profile)
    return _split_review_keywords(
        _resolve_raw_review_keywords(
            content_profile=content_profile,
            source_name=source_name,
        ),
        seed_terms=seed_terms,
    )


def _resolve_raw_review_keywords(
    content_profile: dict[str, Any] | None,
    source_name: str = "",
) -> list[str]:
    profile = dict(content_profile or {})
    if source_name and not str(profile.get("source_name") or "").strip():
        profile["source_name"] = source_name
    seed_terms = _collect_review_keyword_seed_terms(profile)
    raw_keywords: list[str] = []
    deduped: set[str] = set()

    def add_keyword(value: str) -> None:
        for text in _expand_review_keyword_token(value):
            norm = "".join(text.upper().split())
            if not norm or norm in deduped:
                continue
            deduped.add(norm)
            raw_keywords.append(text)

    for raw in (profile.get("keywords") or profile.get("search_queries") or []):
        value = str(raw or "").strip()
        if not value:
            continue
        for token in _extract_review_keyword_tokens(value, seed_terms=seed_terms):
            add_keyword(token)

    if len(raw_keywords) < _REVIEW_KEYWORD_MIN_COUNT:
        for token in _build_review_keywords(profile):
            add_keyword(token)
    if len(raw_keywords) < _REVIEW_KEYWORD_MIN_COUNT:
        for query in _build_review_keyword_candidates(profile, source_name=source_name):
            for token in _extract_review_keyword_tokens(query, seed_terms=seed_terms):
                add_keyword(token)

    if raw_keywords:
        return raw_keywords
    return ["视频内容"]


def _expand_review_keyword_token(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    compact = "".join(text.split())
    if not compact:
        return []
    if re.search(r"[A-Za-z]", compact) and re.search(r"[\u4e00-\u9fff]", compact):
        parts = re.findall(r"[A-Za-z]+(?:\d+)?|[\u4e00-\u9fff]+(?:\d+)?", compact)
        normalized = [str(part).strip() for part in parts if str(part).strip()]
        if len(normalized) > 1:
            return normalized
    return [text]


def _split_review_keywords(values: list[str], *, seed_terms: list[str] | None = None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    normalized_seeds = [str(term or "").strip() for term in (seed_terms or []) if str(term or "").strip()]
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        for token in _extract_review_keyword_tokens(text, seed_terms=normalized_seeds):
            key = "".join(str(token).upper().split())
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(token)
            if len(deduped) >= _REVIEW_KEYWORD_TOKEN_LIMIT:
                return deduped
    return deduped[:_REVIEW_KEYWORD_TOKEN_LIMIT]


def _build_review_keyword_candidates(
    content_profile: dict[str, Any] | None,
    *,
    source_name: str = "",
    limit: int = 6,
) -> list[str]:
    profile = dict(content_profile or {})
    if source_name and not str(profile.get("source_name") or "").strip():
        profile["source_name"] = source_name
    extracted = _build_review_keywords(profile)
    if extracted:
        return extracted[:limit] if limit > 0 else extracted
    proposals = {
        "subject_brand": str(profile.get("subject_brand") or "").strip(),
        "subject_model": str(profile.get("subject_model") or "").strip(),
        "subject_type": str(profile.get("subject_type") or "").strip(),
        "video_theme": str(profile.get("video_theme") or "").strip(),
    }
    return build_review_feedback_search_queries(
        draft_profile=profile,
        proposed_feedback=proposals,
        source_name=source_name,
        limit=limit,
    )


def _extract_subtitle_items_from_report(report: Any | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in getattr(report, "items", []) or []:
        items.append(
            {
                "index": int(item.get("index") or 0),
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or item.get("start") or 0.0),
                "text": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip(),
            }
        )
    return items


def _extract_preview_subtitle_items(
    render_outputs: dict[str, Any],
    *,
    subtitle_report: Any | None = None,
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    bundle_variant, _bundle_source_path = _select_final_review_bundle_variant(variant_timeline_bundle)
    if isinstance(bundle_variant, dict):
        bundle_items = _extract_subtitle_items_from_variant(bundle_variant)
        if bundle_items:
            return bundle_items
    packaged_srt = Path(str(render_outputs.get("packaged_srt") or "").strip())
    if packaged_srt.exists():
        items = _extract_subtitle_items_from_srt(packaged_srt)
        if items:
            return items
    return _extract_subtitle_items_from_report(subtitle_report)


def _select_final_review_bundle_variant(
    bundle: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, Path | None]:
    variants = (bundle or {}).get("variants")
    if not isinstance(variants, dict):
        return None, None

    for variant_name in ("packaged", "avatar", "ai_effect", "plain"):
        variant = variants.get(variant_name)
        if not isinstance(variant, dict):
            continue
        media = variant.get("media")
        if not isinstance(media, dict):
            continue
        for key in ("path", "mp4", "video", "source_path"):
            value = str(media.get(key) or "").strip()
            if not value:
                continue
            candidate = Path(value)
            if candidate.exists():
                return variant, candidate
    return None, None


def _extract_subtitle_items_from_variant(variant: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(variant, dict):
        return []

    items: list[dict[str, Any]] = []
    for index, event in enumerate(variant.get("subtitle_events") or [], start=1):
        item = _coerce_subtitle_event_to_item(event, index=index)
        if item is not None:
            items.append(item)
    return items


def _coerce_subtitle_event_to_item(event: Any, *, index: int) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None

    def _event_float(*keys: str) -> float | None:
        for key in keys:
            value = event.get(key)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    start_sec = _event_float("start", "start_sec", "start_time", "begin", "begin_sec")
    end_sec = _event_float("end", "end_sec", "end_time", "stop", "stop_sec")
    duration_sec = _event_float("duration", "duration_sec")
    if start_sec is None:
        return None
    if end_sec is None and duration_sec is not None:
        end_sec = start_sec + duration_sec
    if end_sec is None:
        end_sec = start_sec

    text = ""
    for key in ("text", "text_final", "text_norm", "text_raw", "content", "subtitle"):
        value = str(event.get(key) or "").strip()
        if value:
            text = value
            break
    if not text:
        return None

    return {
        "index": int(event.get("index") or index),
        "start": float(start_sec),
        "end": float(end_sec),
        "text": text,
    }


def _extract_subtitle_items_from_srt(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    items: list[dict[str, Any]] = []
    for block in re.split(r"\r?\n\r?\n+", text):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_text, end_text = [part.strip() for part in lines[1].split("-->", 1)]
        start_sec = _parse_srt_timestamp(start_text)
        end_sec = _parse_srt_timestamp(end_text)
        if start_sec is None or end_sec is None:
            continue
        items.append(
            {
                "index": len(items) + 1,
                "start": start_sec,
                "end": end_sec,
                "text": " ".join(lines[2:]).strip(),
            }
        )
    return items


def _build_final_review_clip_specs(
    *,
    duration_sec: float,
    subtitle_items: list[dict[str, Any]],
    keywords: list[str],
    variant_timeline_bundle: dict[str, Any] | None = None,
) -> list[TelegramFinalReviewClip]:
    if duration_sec <= 0:
        return []
    clip_duration = min(8.0, max(5.0, duration_sec / 5.0))
    diagnostic_anchor = _pick_high_risk_cut_anchor(
        variant_timeline_bundle,
        subtitle_items=subtitle_items,
    )
    hook_anchor = _pick_high_energy_hook_anchor(
        variant_timeline_bundle,
        subtitle_items=subtitle_items,
    )
    anchor_plan = [
        ("开头节奏", hook_anchor or _pick_subtitle_anchor(subtitle_items, duration_sec * 0.12)),
        (
            "高风险边界" if diagnostic_anchor else "中段重点",
            diagnostic_anchor or _pick_keyword_anchor(subtitle_items, duration_sec, keywords) or _pick_subtitle_anchor(subtitle_items, duration_sec * 0.50),
        ),
        ("结尾收口", _pick_subtitle_anchor(subtitle_items, duration_sec * 0.84)),
    ]
    clips: list[TelegramFinalReviewClip] = []
    seen_starts: set[int] = set()
    fallback_centers = [duration_sec * 0.12, duration_sec * 0.50, duration_sec * 0.84]
    for index, (label, anchor) in enumerate(anchor_plan):
        matched_keyword = str((anchor or {}).get("matched_keyword") or "").strip() or None
        center = float((anchor or {}).get("center") or fallback_centers[index] or 0.0)
        start_sec = _clamp_clip_start(center=center, duration_sec=duration_sec, clip_duration=clip_duration)
        rounded_key = int(round(start_sec * 10))
        if rounded_key in seen_starts:
            center = fallback_centers[index]
            start_sec = _clamp_clip_start(center=center, duration_sec=duration_sec, clip_duration=clip_duration)
            rounded_key = int(round(start_sec * 10))
        seen_starts.add(rounded_key)
        transcript_excerpt = _build_clip_transcript_excerpt(
            subtitle_items,
            start_sec=start_sec,
            end_sec=min(duration_sec, start_sec + clip_duration),
        )
        clips.append(
            TelegramFinalReviewClip(
                label=label,
                start_sec=start_sec,
                duration_sec=min(clip_duration, max(1.5, duration_sec - start_sec)),
                transcript_excerpt=transcript_excerpt,
                matched_keyword=matched_keyword,
            )
        )
    return clips


def _pick_high_risk_cut_anchor(
    variant_timeline_bundle: dict[str, Any] | None,
    *,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    diagnostics = _final_review_diagnostics_payload(variant_timeline_bundle)
    if not diagnostics:
        return None
    best: dict[str, Any] | None = None
    best_score: tuple[float, float] | None = None
    for item in diagnostics.get("high_risk_cuts") or []:
        if not isinstance(item, dict):
            continue
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = max(start_sec, float(item.get("end", start_sec) or start_sec))
        center = start_sec + max(0.0, end_sec - start_sec) * 0.5
        boundary_keep_energy = float(item.get("boundary_keep_energy", 0.0) or 0.0)
        anchor = _pick_subtitle_anchor(subtitle_items, center) or {}
        anchor = dict(anchor)
        anchor["center"] = float(anchor.get("center") or center)
        anchor["matched_keyword"] = "高风险cut"
        score = (boundary_keep_energy, -abs(float(anchor["center"]) - center))
        if best_score is None or score > best_score:
            best = anchor
            best_score = score
    return best


def _pick_high_energy_hook_anchor(
    variant_timeline_bundle: dict[str, Any] | None,
    *,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    diagnostics = _final_review_diagnostics_payload(variant_timeline_bundle)
    if not diagnostics:
        return None
    best: dict[str, Any] | None = None
    best_score: tuple[float, float] | None = None
    for item in diagnostics.get("high_energy_keeps") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("section_role") or "").strip().lower() != "hook":
            continue
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = max(start_sec, float(item.get("end", start_sec) or start_sec))
        center = start_sec + max(0.0, end_sec - start_sec) * 0.35
        keep_energy = float(item.get("keep_energy", 0.0) or 0.0)
        anchor = _pick_subtitle_anchor(subtitle_items, center) or {}
        anchor = dict(anchor)
        anchor["center"] = float(anchor.get("center") or center)
        anchor["matched_keyword"] = str(anchor.get("matched_keyword") or "高能量hook")
        score = (keep_energy, -abs(float(anchor["center"]) - center))
        if best_score is None or score > best_score:
            best = anchor
            best_score = score
    return best


def _final_review_diagnostics_payload(variant_timeline_bundle: dict[str, Any] | None) -> dict[str, Any] | None:
    timeline_rules = (
        variant_timeline_bundle.get("timeline_rules")
        if isinstance(variant_timeline_bundle, dict)
        else None
    )
    diagnostics = timeline_rules.get("diagnostics") if isinstance(timeline_rules, dict) else None
    return diagnostics if isinstance(diagnostics, dict) else None


def _final_review_has_high_risk_cuts(variant_timeline_bundle: dict[str, Any] | None) -> bool:
    diagnostics = _final_review_diagnostics_payload(variant_timeline_bundle)
    if not diagnostics:
        return False
    return any(isinstance(item, dict) for item in (diagnostics.get("high_risk_cuts") or []))


def _final_review_edit_button_action(variant_timeline_bundle: dict[str, Any] | None) -> str:
    diagnostics = _final_review_diagnostics_payload(variant_timeline_bundle)
    if not diagnostics:
        return "edit"

    roles: set[str] = set()
    for item in diagnostics.get("high_risk_cuts") or []:
        if not isinstance(item, dict):
            continue
        left_role = str(item.get("left_keep_role") or "").strip().lower()
        right_role = str(item.get("right_keep_role") or "").strip().lower()
        if left_role:
            roles.add(left_role)
        if right_role:
            roles.add(right_role)

    if "hook" in roles:
        return "edit_hook"
    if "cta" in roles:
        return "edit_cta"
    if roles & {"detail", "body"}:
        return "edit_mid"
    return "edit"


def _final_review_edit_button_text(variant_timeline_bundle: dict[str, Any] | None) -> str:
    action = _final_review_edit_button_action(variant_timeline_bundle)
    return _FINAL_REVIEW_CALLBACK_ACTION_TEXT.get(action, "重剪高风险边界")


def _pick_subtitle_anchor(subtitle_items: list[dict[str, Any]], target_time: float) -> dict[str, Any] | None:
    if not subtitle_items:
        return None
    best: dict[str, Any] | None = None
    best_distance: float | None = None
    for item in subtitle_items:
        center = (float(item.get("start") or 0.0) + float(item.get("end") or 0.0)) / 2
        distance = abs(center - target_time)
        if best_distance is None or distance < best_distance:
            best = dict(item)
            best["center"] = center
            best_distance = distance
    return best


def _pick_keyword_anchor(
    subtitle_items: list[dict[str, Any]],
    duration_sec: float,
    keywords: list[str],
) -> dict[str, Any] | None:
    if not subtitle_items or not keywords:
        return None
    best: dict[str, Any] | None = None
    best_score: tuple[int, float] | None = None
    midpoint = duration_sec / 2
    normalized_keywords = [(keyword, _normalize_match_key(keyword)) for keyword in keywords if str(keyword).strip()]
    for item in subtitle_items:
        text = _normalize_match_key(item.get("text") or "")
        if not text:
            continue
        matches = [keyword for keyword, token in normalized_keywords if token and token in text]
        if not matches:
            continue
        center = (float(item.get("start") or 0.0) + float(item.get("end") or 0.0)) / 2
        score = (len(matches), -abs(center - midpoint))
        if best_score is None or score > best_score:
            best = dict(item)
            best["center"] = center
            best["matched_keyword"] = matches[0]
            best_score = score
    return best


def _clamp_clip_start(*, center: float, duration_sec: float, clip_duration: float) -> float:
    if duration_sec <= clip_duration:
        return 0.0
    start_sec = max(0.0, center - clip_duration * 0.35)
    return min(start_sec, max(0.0, duration_sec - clip_duration))


def _build_clip_transcript_excerpt(
    subtitle_items: list[dict[str, Any]],
    *,
    start_sec: float,
    end_sec: float,
    limit: int = 72,
) -> str:
    texts: list[str] = []
    for item in subtitle_items:
        item_start = float(item.get("start") or 0.0)
        item_end = float(item.get("end") or item_start)
        if item_end < start_sec or item_start > end_sec:
            continue
        text = str(item.get("text") or "").strip()
        if text:
            texts.append(text)
        if len(texts) >= 3:
            break
    combined = " / ".join(texts)
    if len(combined) <= limit:
        return combined
    return combined[: max(0, limit - 1)].rstrip() + "…"


def _build_final_review_subtitle_hints(report: Any | None, *, limit: int = 4) -> list[str]:
    candidates = _build_pending_subtitle_candidates(report) if report is not None else []
    if not candidates:
        return []
    low_confidence = [
        item
        for item in candidates
        if 0.0 < float(item.confidence or 0.0) < 0.9
    ]
    selected = sorted(
        low_confidence or candidates,
        key=lambda item: (
            float(item.confidence or 1.0) if float(item.confidence or 0.0) > 0 else 1.0,
            int(item.subtitle_index or 0),
        ),
    )[:limit]
    lines: list[str] = []
    for item in selected:
        time_range = (
            _format_time_range(float(item.start_sec or 0.0), float(item.end_sec or item.start_sec or 0.0))
            if item.start_sec is not None
            else "时间未知"
        )
        lines.append(
            f"- {item.slot} · 字幕 #{item.subtitle_index} · {time_range} · "
            f"原“{item.original}” -> 建议“{item.suggested}” · 置信度 {round(float(item.confidence or 0.0) * 100)}%"
        )
    return lines


def _format_time_range(start_sec: float, end_sec: float) -> str:
    return f"{_format_seconds(start_sec)}-{_format_seconds(max(end_sec, start_sec))}"


def _format_seconds(value: float) -> str:
    total_seconds = max(0, int(round(float(value or 0.0))))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def _parse_srt_timestamp(value: str) -> float | None:
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,.:](\d{3})", value.strip())
    if not match:
        return None
    hours, minutes, seconds, millis = (int(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


async def _ensure_final_review_preview(
    *,
    job_id: uuid.UUID,
    source_path: Path,
    clip_index: int,
    start_sec: float,
    duration_sec: float,
) -> Path:
    source_stat = source_path.stat()
    cache_dir = Path(tempfile.gettempdir()) / "roughcut_final_review_previews" / str(job_id)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_key = f"{source_stat.st_size}_{int(source_stat.st_mtime)}_{int(start_sec * 1000)}_{int(duration_sec * 1000)}"
    output_path = cache_dir / f"preview_{clip_index:02d}_{cache_key}.mp4"
    if output_path.exists():
        return output_path

    settings = get_settings()
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{max(0.0, start_sec):.2f}",
        "-i",
        str(source_path),
        "-t",
        f"{max(1.5, duration_sec):.2f}",
        "-vf",
        "scale=720:-2,fps=24",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "31",
        "-maxrate",
        "900k",
        "-bufsize",
        "1800k",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(45, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 180)),
        ),
    )
    if result.returncode != 0 or not output_path.exists():
        raise RuntimeError(f"ffmpeg preview render failed: {result.stderr.decode('utf-8', errors='replace')[-600:]}")
    return output_path


def _build_packaging_plan_from_config(
    packaging_assets: dict[str, list[dict[str, Any]]],
    packaging_config: dict[str, Any],
) -> dict[str, Any]:
    asset_index = _build_packaging_asset_index(packaging_assets)
    insert_ids = list(packaging_config.get("insert_asset_ids") or [])
    music_ids = list(packaging_config.get("music_asset_ids") or [])
    return {
        "intro": _resolved_packaging_item(asset_index, packaging_config.get("intro_asset_id")),
        "outro": _resolved_packaging_item(asset_index, packaging_config.get("outro_asset_id")),
        "insert": _resolved_packaging_item(asset_index, insert_ids[0] if insert_ids else None),
        "watermark": _resolved_packaging_item(asset_index, packaging_config.get("watermark_asset_id")),
        "music": _resolved_packaging_item(asset_index, music_ids[0] if music_ids else None),
        "subtitle_style": packaging_config.get("subtitle_style"),
        "cover_style": packaging_config.get("cover_style"),
        "title_style": packaging_config.get("title_style"),
        "copy_style": packaging_config.get("copy_style"),
        "smart_effect_style": packaging_config.get("smart_effect_style"),
    }


def _build_packaging_asset_index(packaging_assets: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for items in packaging_assets.values():
        for item in items or []:
            asset_id = str(item.get("id") or "").strip()
            if not asset_id:
                continue
            index[asset_id] = str(item.get("original_name") or asset_id).strip() or asset_id
    return index


def _asset_label(asset_index: dict[str, str], asset_id: Any) -> str:
    asset_key = str(asset_id or "").strip()
    if not asset_key:
        return "未选择"
    return asset_index.get(asset_key, asset_key)


def _asset_list_label(asset_index: dict[str, str], asset_ids: list[Any]) -> str:
    labels = [_asset_label(asset_index, asset_id) for asset_id in asset_ids if str(asset_id or "").strip()]
    return "、".join(labels) if labels else "未选择"


def _resolved_packaging_item(asset_index: dict[str, str], asset_id: Any) -> dict[str, str] | None:
    asset_key = str(asset_id or "").strip()
    if not asset_key:
        return None
    return {
        "asset_id": asset_key,
        "original_name": asset_index.get(asset_key, asset_key),
    }


def _resolved_packaging_label(item: Any) -> str:
    if not isinstance(item, dict):
        return "未选择"
    label = str(item.get("original_name") or item.get("asset_id") or "").strip()
    if not label:
        return "未选择"
    candidate_ids = [
        str(candidate).strip()
        for candidate in (item.get("candidate_asset_ids") or [])
        if str(candidate).strip()
    ]
    if len(candidate_ids) > 1:
        return f"{label}（候选池 {len(candidate_ids)} 首）"
    return label


def _style_label(value: Any, labels: dict[str, str]) -> str:
    key = str(value or "").strip()
    if not key:
        return "未设置"
    return labels.get(key, key)


def _build_review_checks(
    *,
    enhancement_modes: list[str],
    config: Any | None,
    packaging_config: dict[str, Any],
    packaging_plan: dict[str, Any] | None,
    avatar_materials: Any | None,
) -> list[dict[str, str]]:
    packaging_enabled = bool(packaging_config.get("enabled"))
    selected_packaging = _selected_packaging_labels(packaging_plan or {})
    checks = [
        {
            "label": "包装素材与风格模板",
            "status": "齐全" if packaging_enabled else "待补",
            "detail": (
                "全局包装已启用，审核后会沿用当前任务级包装方案："
                f"{'；'.join(selected_packaging)}。"
                if packaging_enabled and selected_packaging
                else "全局包装已启用，审核后会沿用当前包装素材池与风格模板。"
                if packaging_enabled
                else "全局包装当前关闭，成片会跳过片头片尾、水印和背景音乐包装。"
            ),
        }
    ]

    if "avatar_commentary" in enhancement_modes:
        presenter_id = str(_get_value(config, "avatar_presenter_id") or "").strip()
        profiles = list(_get_value(avatar_materials, "profiles") or [])
        bound_profile = _find_avatar_profile_label(profiles, presenter_id)
        ready_profile = _find_preview_ready_profile(profiles)
        if presenter_id:
            detail = (
                f"已绑定数字人模板：{_format_avatar_binding_label(bound_profile or presenter_id)}"
                + (
                    f"；另有可自动切换档案：{ready_profile}"
                    if ready_profile and ready_profile != bound_profile
                    else "；渲染时会优先使用这个模板生成画中画数字人口播。"
                )
            )
            status = "齐全"
        elif ready_profile:
            detail = (
                f"未显式绑定 avatar_presenter_id，但已有可用数字人档案：{ready_profile}；"
                "渲染时会自动选用该档案完成数字人解说。"
            )
            status = "齐全"
        else:
            detail = (
                "已启用数字人解说，但当前既没有 avatar_presenter_id，也没有 preview 就绪的数字人档案；"
                "本次任务会退回普通成片，不会生成数字人口播画中画。"
            )
            status = "待补"
        checks.append({"label": "数字人解说", "status": status, "detail": detail})

    if "ai_effects" in enhancement_modes:
        has_insert = _resolved_packaging_label((packaging_plan or {}).get("insert")) != "未选择"
        smart_effect_style = _style_label(
            (packaging_plan or {}).get("smart_effect_style") or packaging_config.get("smart_effect_style"),
            _SMART_EFFECT_STYLE_LABELS,
        )
        if packaging_enabled:
            detail = (
                f"已启用智能剪辑特效，当前风格为 {smart_effect_style}；包装配置里也包含插片/转场素材，可进一步放大转场、画面特效和氛围强化。"
                if has_insert
                else f"已启用智能剪辑特效，当前风格为 {smart_effect_style}；将基于剪辑时间线自动补转场、字幕动效、局部画面强化与氛围特效。"
            )
            status = "齐全"
        else:
            detail = "已启用智能剪辑特效，但当前全局包装关闭，最终只会保留基础剪辑层，特效空间较有限。"
            status = "待补"
        checks.append({"label": "智能剪辑特效", "status": status, "detail": detail})

    if "ai_director" in enhancement_modes:
        voice_provider = str(_get_value(config, "voice_provider") or "").strip().lower()
        voice_clone_api_base_url = str(_get_value(config, "voice_clone_api_base_url") or "").strip()
        voice_clone_voice_id = str(_get_value(config, "voice_clone_voice_id") or "").strip()
        voice_clone_api_key_set = bool(_get_value(config, "voice_clone_api_key_set"))
        index_tts_ready = voice_provider == "indextts2" and bool(voice_clone_api_base_url)
        runninghub_ready = voice_provider == "runninghub" and voice_clone_api_key_set and bool(voice_clone_voice_id)
        if index_tts_ready:
            detail = f"当前走 IndexTTS2 accel 主实例，本地服务：{voice_clone_api_base_url}；会自动做情绪文本和强度控制。"
            status = "齐全"
        elif runninghub_ready:
            detail = f"当前走 RunningHub，工作流 / voice id：{voice_clone_voice_id}"
            status = "齐全"
        else:
            detail = "已启用 AI 导演，但语音 provider 配置还不完整，缺少可用的 TTS / 语音克隆执行入口。"
            status = "待补"
        checks.append({"label": "AI 导演重配音", "status": status, "detail": detail})

    if not enhancement_modes:
        checks.append(
            {
                "label": "增强模式",
                "status": "齐全",
                "detail": "当前未启用额外增强模式，本次将按标准成片继续执行。",
            }
        )

    return checks


def _get_value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _find_preview_ready_profile(profiles: list[Any]) -> str | None:
    for profile in profiles:
        capability_status = _get_value(profile, "capability_status") or {}
        preview_status = (
            capability_status.get("preview")
            if isinstance(capability_status, dict)
            else getattr(capability_status, "preview", None)
        )
        if str(preview_status or "").strip() == "ready":
            display_name = str(_get_value(profile, "display_name") or "").strip()
            if display_name:
                return display_name
    return None


def _selected_packaging_labels(packaging_plan: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for label, key in (
        ("片头", "intro"),
        ("片尾", "outro"),
        ("转场", "insert"),
        ("水印", "watermark"),
        ("音乐", "music"),
    ):
        value = _resolved_packaging_label(packaging_plan.get(key))
        if value != "未选择":
            labels.append(f"{label} {value}")
    return labels


def _find_avatar_profile_label(profiles: list[Any], presenter_id: str) -> str | None:
    if not presenter_id:
        return None
    normalized_presenter = _normalize_match_key(presenter_id)
    presenter_name = Path(presenter_id).stem.strip()
    for profile in profiles:
        display_name = str(_get_value(profile, "display_name") or "").strip()
        presenter_alias = str(_get_value(profile, "presenter_alias") or "").strip()
        profile_dir = str(_get_value(profile, "profile_dir") or "").strip()
        profile_id = str(_get_value(profile, "id") or "").strip()
        candidates = {
            _normalize_match_key(display_name),
            _normalize_match_key(presenter_alias),
            _normalize_match_key(profile_dir),
            _normalize_match_key(profile_id),
            _normalize_match_key(Path(profile_dir).name if profile_dir else ""),
        }
        if normalized_presenter in {item for item in candidates if item}:
            return display_name or presenter_alias or presenter_name or presenter_id
        if profile_dir and normalized_presenter.startswith(_normalize_match_key(profile_dir)):
            return display_name or presenter_alias or presenter_name or presenter_id
        for file_item in _get_value(profile, "files") or []:
            file_path = str(_get_value(file_item, "path") or "").strip()
            original_name = str(_get_value(file_item, "original_name") or "").strip()
            stored_name = str(_get_value(file_item, "stored_name") or "").strip()
            file_id = str(_get_value(file_item, "id") or "").strip()
            file_candidates = {
                _normalize_match_key(file_path),
                _normalize_match_key(original_name),
                _normalize_match_key(stored_name),
                _normalize_match_key(file_id),
                _normalize_match_key(Path(file_path).name if file_path else ""),
                _normalize_match_key(Path(original_name).stem if original_name else ""),
            }
            if normalized_presenter in {item for item in file_candidates if item}:
                return display_name or presenter_alias or presenter_name or presenter_id
            if file_path and normalized_presenter.startswith(_normalize_match_key(Path(file_path).parent.as_posix())):
                return display_name or presenter_alias or presenter_name or presenter_id
    return presenter_name or None


def _format_avatar_binding_label(display_name: str) -> str:
    name = str(display_name or "").strip()
    if not name:
        return "已绑定数字人模板"
    return f"使用 {name}数字人的解说视频素材"


def _normalize_match_key(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").lower()


def _display_value(value: Any) -> str:
    text = str(value or "").strip()
    return text or "待补充"


_SUBJECT_TYPE_LABELS = {
    "zh-CN": {
        "tutorial": "教程",
        "vlog": "Vlog",
        "commentary": "观点",
        "gameplay": "游戏",
        "food": "探店",
        "unboxing": "开箱",
    },
    "en-US": {
        "tutorial": "Tutorial",
        "vlog": "Vlog",
        "commentary": "Commentary",
        "gameplay": "Gameplay",
        "food": "Food",
        "unboxing": "Unboxing",
    },
}


def _display_subject_type(value: Any, *, locale: str = "zh-CN", context_texts: list[str] | None = None) -> str:
    normalized_locale = "en-US" if str(locale or "").lower().startswith("en") else "zh-CN"
    labels = _SUBJECT_TYPE_LABELS[normalized_locale]
    texts = [value]
    texts.extend(context_texts or [])

    for text_value in texts:
        text = str(text_value or "").strip()
        if not text:
            continue
        key = text.strip().lower()
        for known_key, label in labels.items():
            if known_key in key or label.lower() in key.lower():
                return label
        if "unboxing" in key or "开箱" in key or "上手" in key:
            return labels["unboxing"]
        if "tutorial" in key or "教程" in key or "教学" in key or "演示" in key:
            return labels["tutorial"]
        if "vlog" in key or "生活" in key or "日常" in key:
            return labels["vlog"]
        if "commentary" in key or "观点" in key or "评论" in key:
            return labels["commentary"]
        if "gameplay" in key or "游戏" in key:
            return labels["gameplay"]
        if "food" in key or "探店" in key:
            return labels["food"]

    return "待补充" if normalized_locale == "zh-CN" else "Pending"


def _build_content_profile_evidence_lines(draft: dict[str, Any]) -> list[str]:
    if not isinstance(draft, dict):
        return []

    lines: list[str] = []

    ocr_evidence = draft.get("ocr_evidence")
    if isinstance(ocr_evidence, dict) and ocr_evidence:
        summary_source = str(ocr_evidence.get("visible_text") or "").strip()
        if not summary_source:
            snippets = [
                str(item.get("text") or "").strip()
                for item in (ocr_evidence.get("raw_snippets") or [])
                if isinstance(item, dict) and str(item.get("text") or "").strip()
            ]
            summary_source = " / ".join(snippets[:2])
        summary = _preview_inline_text(summary_source, limit=64)
        detail_parts = []
        if ocr_evidence.get("frame_count") is not None:
            detail_parts.append(f"{ocr_evidence.get('frame_count')} 帧")
        if ocr_evidence.get("line_count") is not None:
            detail_parts.append(f"{ocr_evidence.get('line_count')} 行")
        suffix = f"（{_join_non_empty(detail_parts)}）" if detail_parts else ""
        lines.append(f"- OCR 文字摘要：{summary or '未识别'}{suffix}")

    transcript_evidence = draft.get("transcript_evidence")
    if isinstance(transcript_evidence, dict) and transcript_evidence:
        provider = _display_value(transcript_evidence.get("provider"))
        model = _display_value(transcript_evidence.get("model"))
        prompt_source = str(
            transcript_evidence.get("prompt")
            or transcript_evidence.get("context")
            or transcript_evidence.get("hotword")
            or ""
        ).strip()
        prompt = _preview_inline_text(prompt_source, limit=80)
        lines.append(f"- 转写证据：{provider} / {model}")
        if prompt:
            lines.append(f"  - Prompt 轨迹：{prompt}")

    entity_resolution_trace = draft.get("entity_resolution_trace")
    if isinstance(entity_resolution_trace, dict) and entity_resolution_trace:
        trace_summary = _preview_inline_text(
            str(
                entity_resolution_trace.get("summary")
                or entity_resolution_trace.get("detail")
                or entity_resolution_trace.get("trace")
                or ""
            ).strip(),
            limit=80,
        )
        if trace_summary:
            lines.append(f"- 实体解析轨迹：{trace_summary}")

    return lines


def _preview_inline_text(text: str, *, limit: int = 80) -> str:
    compact = _compact_text(text)
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def _build_identity_review_lines(identity_review: Any) -> list[str]:
    if not isinstance(identity_review, dict):
        return []
    evidence_bundle = identity_review.get("evidence_bundle") if isinstance(identity_review.get("evidence_bundle"), dict) else {}
    support_sources = [
        _IDENTITY_SUPPORT_SOURCE_LABELS.get(str(item), str(item))
        for item in (identity_review.get("support_sources") or [])
        if str(item).strip()
    ]
    lines = [
        f"- 候选品牌：{_display_value(evidence_bundle.get('candidate_brand'))}",
        f"- 候选型号：{_display_value(evidence_bundle.get('candidate_model'))}",
        f"- 首次命中：品牌 {'是' if identity_review.get('first_seen_brand') else '否'} / 型号 {'是' if identity_review.get('first_seen_model') else '否'}",
        f"- 证据强度：{_display_value(identity_review.get('evidence_strength'))}",
        f"- 支撑来源：{_join_non_empty(support_sources) or '无'}",
    ]
    matched_glossary_aliases = []
    glossary_aliases = evidence_bundle.get("matched_glossary_aliases") if isinstance(evidence_bundle, dict) else {}
    if isinstance(glossary_aliases, dict):
        brand_aliases = _join_non_empty(glossary_aliases.get("brand") or [])
        model_aliases = _join_non_empty(glossary_aliases.get("model") or [])
        if brand_aliases:
            matched_glossary_aliases.append(f"品牌：{brand_aliases}")
        if model_aliases:
            matched_glossary_aliases.append(f"型号：{model_aliases}")
    if matched_glossary_aliases:
        lines.append(f"- 命中词表别名：{'; '.join(matched_glossary_aliases)}")
    lines.extend(_build_identity_match_lines("文件名命中", evidence_bundle.get("matched_source_name_terms")))
    lines.extend(_build_identity_match_lines("画面文字命中", evidence_bundle.get("matched_visible_text_terms")))
    lines.extend(_build_identity_match_lines("外部证据命中", evidence_bundle.get("matched_evidence_terms")))
    subtitle_snippets = [
        str(item).strip()
        for item in (evidence_bundle.get("matched_subtitle_snippets") or [])
        if str(item).strip()
    ]
    if subtitle_snippets:
        lines.append("- 命中字幕片段：")
        lines.extend(f"  - {item}" for item in subtitle_snippets)
    return lines


def _build_identity_match_lines(label: str, values: Any) -> list[str]:
    items = [str(item).strip() for item in (values or []) if str(item).strip()]
    if not items:
        return []
    return [f"- {label}：{_join_non_empty(items)}"]


def _join_non_empty(values: list[Any] | tuple[Any, ...]) -> str:
    return "，".join(str(item).strip() for item in values if str(item).strip())


def _build_pending_subtitle_candidates(report: Any) -> list[TelegramReviewCandidate]:
    candidates: list[TelegramReviewCandidate] = []
    slot_index = 1
    for item in report.items:
        for correction in item.get("corrections") or []:
            if correction.get("decision") in {"accepted", "rejected"}:
                continue
            candidates.append(
                TelegramReviewCandidate(
                    slot=f"S{slot_index}",
                    correction_id=str(correction.get("id") or ""),
                    subtitle_index=int(item.get("index") or 0),
                    original=str(correction.get("original") or ""),
                    suggested=str(correction.get("suggested") or ""),
                    change_type=str(correction.get("type") or ""),
                    confidence=float(correction.get("confidence") or 0.0),
                    source=str(correction.get("source") or "") or None,
                    start_sec=float(item.get("start") or 0.0),
                    end_sec=float(item.get("end") or item.get("start") or 0.0),
                )
            )
            slot_index += 1
    return candidates


async def _load_full_subtitle_review_lines(
    job_id: uuid.UUID,
    session: Any,
) -> list[TelegramSubtitleLineCandidate]:
    result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id)
        .order_by(SubtitleItem.item_index)
    )
    subtitle_items = result.scalars().all()
    lines: list[TelegramSubtitleLineCandidate] = []
    slot_index = 1
    for item in subtitle_items:
        text = str(item.text_final or item.text_norm or item.text_raw or "").strip()
        if not text:
            continue
        lines.append(
            TelegramSubtitleLineCandidate(
                slot=f"L{slot_index}",
                subtitle_item_id=str(item.id),
                subtitle_index=int(item.item_index),
                text=text,
                start_sec=float(item.start_time or 0.0),
                end_sec=float(item.end_time or item.start_time or 0.0),
            )
        )
        slot_index += 1
    return lines


def _write_full_subtitle_review_attachment(
    job_id: uuid.UUID,
    subtitle_lines: list[TelegramSubtitleLineCandidate],
) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".txt",
        prefix=f"roughcut-subtitle-review-{job_id}-",
        delete=False,
    ) as handle:
        handle.write(f"Job ID: {job_id}\n")
        handle.write("全量字幕人工复核清单\n\n")
        for item in subtitle_lines:
            handle.write(
                f"{item.slot} [{item.start_sec or 0.0:.1f}-{item.end_sec or 0.0:.1f}] "
                f"字幕#{item.subtitle_index}: {item.text}\n"
            )
    return Path(handle.name)


def _interpret_full_subtitle_review_reply(
    text: str,
    subtitle_lines: list[TelegramSubtitleLineCandidate],
) -> tuple[bool, list[dict[str, str]]]:
    return telegram_review_parsing.interpret_full_subtitle_review_reply(text, subtitle_lines)


async def _apply_full_subtitle_review_actions(
    job_id: uuid.UUID,
    actions: list[dict[str, str]],
    session: Any,
) -> int:
    applied = 0
    for action in actions:
        target_id = str(action.get("subtitle_item_id") or "").strip()
        if not target_id:
            continue
        try:
            subtitle_item_id = uuid.UUID(target_id)
        except ValueError:
            continue
        item = await session.get(SubtitleItem, subtitle_item_id)
        if item is None or item.job_id != job_id:
            continue
        override_text = str(action.get("override_text") or "").strip()
        if action.get("action") == "updated" and override_text:
            item.text_final = override_text
        session.add(
            ReviewAction(
                job_id=job_id,
                target_type="subtitle_item",
                target_id=subtitle_item_id,
                action=str(action.get("action") or "accepted"),
                override_text=override_text or None,
            )
        )
        applied += 1
    if applied > 0:
        await session.commit()
    return applied


async def _interpret_subtitle_review_reply(
    text: str,
    candidates: list[TelegramReviewCandidate],
) -> list[dict[str, str]]:
    return await telegram_review_parsing.interpret_subtitle_review_reply(
        text,
        candidates,
        provider=get_reasoning_provider(),
        message_cls=Message,
    )


async def _interpret_content_profile_reply(review: Any, text: str) -> dict[str, Any]:
    return await telegram_review_parsing.interpret_content_profile_reply(
        review,
        text,
        provider=get_reasoning_provider(),
        message_cls=Message,
        field_guidelines=CONTENT_PROFILE_FIELD_GUIDELINES,
        normalize_subject_type=normalize_video_type,
        allowed_workflow_modes=[item["value"] for item in build_active_workflow_mode_options()],
        allowed_enhancement_modes=[item["value"] for item in build_active_enhancement_mode_options()],
    )


async def _load_subtitle_review_artifacts(job_id: uuid.UUID, session: Any) -> dict[str, dict[str, Any]]:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(_SUBTITLE_REVIEW_ARTIFACT_TYPES),
        )
        .order_by(Artifact.created_at.desc())
    )
    artifacts = result.scalars().all()
    return {
        artifact_type: payload
        for artifact_type in _SUBTITLE_REVIEW_ARTIFACT_TYPES
        if (payload := _select_latest_artifact_payload(artifacts, artifact_type))
    }


def _select_latest_artifact_payload(artifacts: list[Artifact], artifact_type: str) -> dict[str, Any]:
    selected_payload: dict[str, Any] | None = None
    selected_created_at = datetime.min.replace(tzinfo=timezone.utc)
    for artifact in artifacts or []:
        if str(getattr(artifact, "artifact_type", "") or "").strip() != artifact_type:
            continue
        payload = getattr(artifact, "data_json", None)
        if not isinstance(payload, dict):
            continue
        created_at = getattr(artifact, "created_at", None) or selected_created_at
        if selected_payload is None or created_at > selected_created_at:
            selected_payload = dict(payload)
            selected_created_at = created_at
    return selected_payload or {}


def _build_subtitle_review_artifact_lines(artifacts: dict[str, dict[str, Any]] | None) -> list[str]:
    if not isinstance(artifacts, dict) or not artifacts:
        return []

    lines: list[str] = []

    term_patch = artifacts.get("subtitle_term_resolution_patch") or {}
    if isinstance(term_patch, dict) and term_patch:
        metrics = dict(term_patch.get("metrics") or {})
        candidate_terms = [str(item).strip() for item in (term_patch.get("candidate_terms") or []) if str(item).strip()]
        patch_count = int(metrics.get("patch_count") or len(term_patch.get("patches") or []))
        accepted_count = int(metrics.get("accepted_count") or 0)
        pending_count = int(metrics.get("pending_count") or 0)
        auto_applied_count = int(metrics.get("auto_applied_count") or 0)
        lines.append(
            f"- 术语修复：{patch_count} 条候选，已接受 {accepted_count}，待审 {pending_count}，词级自动应用 {auto_applied_count}"
        )
        if candidate_terms:
            lines.append(f"- 术语候选：{_join_non_empty(candidate_terms[:4])}")
        if term_patch.get("blocking"):
            lines.append("- 术语状态：仍有待确认候选，优先处理字幕审核")
        action_payload = build_subtitle_term_resolution_action(term_patch)
        if action_payload.get("recommended_action"):
            lines.append(f"- 处理动作：{action_payload['recommended_action']}")

    consistency_report = artifacts.get("subtitle_consistency_report") or {}
    if isinstance(consistency_report, dict) and consistency_report:
        blocking = bool(consistency_report.get("blocking"))
        score = consistency_report.get("score")
        score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "未评"
        blocking_reasons = [
            str(item).strip()
            for item in (consistency_report.get("blocking_reasons") or [])
            if str(item).strip()
        ]
        warning_reasons = [
            str(item).strip()
            for item in (consistency_report.get("warning_reasons") or [])
            if str(item).strip()
        ]
        lines.append(f"- 一致性：{score_text} 分，{'阻断' if blocking else '通过'}")
        if blocking_reasons:
            lines.append(f"- 一致性阻断：{_join_non_empty(blocking_reasons[:2])}")
        elif warning_reasons:
            lines.append(f"- 一致性提醒：{_join_non_empty(warning_reasons[:2])}")
        action_payload = build_subtitle_consistency_action(consistency_report)
        if action_payload.get("recommended_action"):
            lines.append(f"- 处理动作：{action_payload['recommended_action']}")

    quality_report = artifacts.get("subtitle_quality_report") or {}
    if isinstance(quality_report, dict) and quality_report:
        blocking = bool(quality_report.get("blocking"))
        score = quality_report.get("score")
        score_text = f"{float(score):.2f}" if isinstance(score, (int, float)) else "未评"
        blocking_reasons = [
            str(item).strip()
            for item in (quality_report.get("blocking_reasons") or [])
            if str(item).strip()
        ]
        warning_reasons = [
            str(item).strip()
            for item in (quality_report.get("warning_reasons") or [])
            if str(item).strip()
        ]
        lines.append(f"- 质量：{score_text} 分，{'阻断' if blocking else '通过'}")
        if blocking_reasons:
            lines.append(f"- 质量阻断：{_join_non_empty(blocking_reasons[:2])}")
        elif warning_reasons:
            lines.append(f"- 质量提醒：{_join_non_empty(warning_reasons[:2])}")
        action_payload = build_subtitle_quality_action(quality_report)
        if action_payload.get("recommended_action"):
            lines.append(f"- 处理动作：{action_payload['recommended_action']}")

    return lines


_telegram_review_bot_service: TelegramReviewBotService | None = None


def get_telegram_review_bot_service() -> TelegramReviewBotService:
    global _telegram_review_bot_service
    if _telegram_review_bot_service is None:
        _telegram_review_bot_service = TelegramReviewBotService()
    return _telegram_review_bot_service
