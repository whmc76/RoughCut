from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from roughcut.api.avatar_materials import get_avatar_materials
from roughcut.api.config import get_config
from roughcut.api.jobs import confirm_content_profile, get_content_profile
from roughcut.api.schemas import ContentProfileConfirmIn, ReviewActionCreate, ReviewApplyRequest
from roughcut.config import get_settings
from roughcut.creative.modes import build_active_enhancement_mode_options, build_active_workflow_mode_options
from roughcut.db.models import Job
from roughcut.db.session import get_session_factory
from roughcut.packaging.library import list_packaging_assets
from roughcut.review.report import generate_report
from roughcut.telegram.commands import handle_telegram_command, handle_telegram_freeform_request
from roughcut.telegram.policy import is_allowed_chat, telegram_agent_enabled
from roughcut.telegram.task_service import (
    get_agent_task_status,
    mark_task_notified,
    pending_notification_records,
)
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message

logger = logging.getLogger(__name__)

_REVIEW_KIND_CONTENT = "content_profile"
_REVIEW_KIND_SUBTITLE = "subtitle_review"
_REVIEW_REF_PATTERN = re.compile(
    r"RC:(?P<kind>content_profile|subtitle_review):(?P<job_id>[0-9a-fA-F-]{36})"
)
_SIMPLE_APPROVAL_PATTERN = re.compile(r"^(通过|确认|继续|好的|ok|okay|yes|y|pass)[！!。.，,\s]*$", re.IGNORECASE)
_ACCEPT_ALL_PATTERN = re.compile(r"(全部|全都|都)(通过|接受|采纳)|全部接受|全部通过", re.IGNORECASE)
_REJECT_ALL_PATTERN = re.compile(r"(全部|全都|都)(拒绝|驳回)|全部拒绝", re.IGNORECASE)
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
    "smart_effect_rhythm": "节奏卡点",
    "smart_effect_punch": "爆点冲击",
    "smart_effect_glitch": "故障赛博",
    "smart_effect_cinematic": "电影推进",
    "smart_effect_minimal": "克制轻特效",
}
_IDENTITY_SUPPORT_SOURCE_LABELS = {
    "transcript": "字幕",
    "source_name": "文件名",
    "visible_text": "画面文字",
    "evidence": "外部证据",
}
_CONTENT_FIELD_ORDER = (
    ("subject_type", "视频类型"),
    ("video_theme", "视频主题"),
    ("hook_line", "标题钩子"),
    ("visible_text", "画面文字"),
    ("summary", "内容摘要"),
    ("engagement_question", "互动提问"),
    ("correction_notes", "校对备注"),
    ("supplemental_context", "补充上下文"),
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
        if not _telegram_ready(settings):
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
            config = get_config()
            avatar_materials = await get_avatar_materials()
            message = _build_content_profile_review_message(
                source_name=job.source_name,
                job_id=job.id,
                review=review,
                draft=draft,
                packaging_assets=packaging_state.get("assets") or {},
                packaging_config=packaging_config,
                config=config,
                avatar_materials=avatar_materials,
            )
        await self._send_review_message(_REVIEW_KIND_CONTENT, job_id, message)

    async def notify_subtitle_review(self, job_id: uuid.UUID) -> None:
        settings = get_settings()
        if not _telegram_ready(settings):
            return

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            report = await generate_report(job_id, session)
            pending_candidates = _build_pending_subtitle_candidates(report)
            if not pending_candidates:
                return
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
        await self._send_review_message(_REVIEW_KIND_SUBTITLE, job_id, "\n".join(lines).strip())

    async def _run(self) -> None:
        while True:
            settings = get_settings()
            if not _telegram_ready(settings):
                await asyncio.sleep(10)
                continue
            try:
                await self._poll_updates()
                await self._poll_agent_tasks()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram review bot poll failed")
                await asyncio.sleep(5)

    async def _poll_updates(self) -> None:
        settings = get_settings()
        payload = {
            "timeout": 50,
            "allowed_updates": ["message"],
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
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        if not text:
            return
        actual_chat_id = str((message.get("chat") or {}).get("id") or "").strip()
        text_lower = text.lower()
        if text_lower in {"/start", "/help"}:
            await self._send_chat_text(
                "远程审核已启用，Telegram agent 控制面已接管。"
                "审核消息可直接回复“全部通过 / 全部拒绝”或类似“S1通过，S2改成 xxx”。\n"
                "命令：/status、/jobs [limit]、/job <job_id>、"
                "/run <claude|codex|acp> <preset> --task \"...\"、/task <task_id> [--full]、"
                "/tasks [limit]、/presets、/confirm <task_id>、/cancel <task_id>、"
                "/review [content|subtitle] <job_id> <pass|reject|note> [备注]\n"
                "如果直接发送复杂错误、结构优化、链路优化或未知命令需求，agent 会自动尝试分流并创建处理任务。",
                chat_id=actual_chat_id,
            )
            return
        if text_lower in {"/whoami", "/id"}:
            await self._send_chat_text(f"当前会话 Chat ID：{actual_chat_id}", chat_id=actual_chat_id)
            return

        settings = get_settings()
        if not is_allowed_chat(settings, actual_chat_id):
            return
        if text.startswith("/"):
            async def send_with_chat_id(reply_text: str) -> None:
                await self._send_chat_text(reply_text, chat_id=actual_chat_id)

            setattr(send_with_chat_id, "_telegram_chat_id", actual_chat_id)
            if await handle_telegram_command(text, send_text=send_with_chat_id):
                return

        review_ref = _extract_review_reference(text)
        if review_ref is None:
            reply_to_message = message.get("reply_to_message") or {}
            review_ref = _extract_review_reference(str(reply_to_message.get("text") or ""))
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

    async def _handle_content_profile_reply(self, job_id: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        factory = get_session_factory()
        async with factory() as session:
            review = await get_content_profile(job_id, session)
            if review.review_step_status == "done":
                await self._send_chat_text(f"任务 {job_id} 的内容摘要已经确认过了，无需重复提交。", chat_id=reply_chat_id)
                return
            payload = (
                {}
                if _SIMPLE_APPROVAL_PATTERN.match(text)
                else await _interpret_content_profile_reply(review, text)
            )
            await confirm_content_profile(job_id, ContentProfileConfirmIn(**payload), session)
        await self._send_chat_text(f"已接收任务 {job_id} 的审核意见，系统正在校正内容摘要并继续后续流程。", chat_id=reply_chat_id)

    async def _handle_subtitle_reply(self, job_id: uuid.UUID, text: str, *, reply_chat_id: str = "") -> None:
        factory = get_session_factory()
        async with factory() as session:
            report = await generate_report(job_id, session)
            candidates = _build_pending_subtitle_candidates(report)
            if not candidates:
                await self._send_chat_text(f"任务 {job_id} 当前没有待审核的字幕纠错候选。", chat_id=reply_chat_id)
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

    async def _poll_agent_tasks(self) -> None:
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

    async def _send_review_message(self, kind: str, job_id: uuid.UUID, body: str) -> None:
        chunks = _split_review_message(body)
        total = len(chunks)
        for index, chunk in enumerate(chunks, start=1):
            header = f"【RC:{kind}:{job_id}】"
            prefix = f"{header} ({index}/{total})" if total > 1 else header
            await self._send_text(f"{prefix}\n{chunk}")

    async def _send_text(self, text: str) -> None:
        settings = get_settings()
        chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
        if not _telegram_ready(settings) or not chat_id:
            return
        await self._send_chat_text(text, chat_id=chat_id)

    async def _send_chat_text(self, text: str, *, chat_id: str) -> None:
        settings = get_settings()
        if not _telegram_ready(settings) or not str(chat_id or "").strip():
            return
        payload = {
            "chat_id": str(chat_id).strip(),
            "text": text,
        }
        await self._call_api(settings, "sendMessage", payload)

    async def _call_api(self, settings: Any, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{str(settings.telegram_bot_api_base_url).rstrip('/')}"
            f"/bot{str(settings.telegram_bot_token).strip()}/{method}"
        )
        timeout = httpx.Timeout(65.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok", False):
            raise RuntimeError(str(data))
        return data


def _telegram_ready(settings: Any) -> bool:
    return telegram_agent_enabled(settings)


def _extract_review_reference(text: str) -> tuple[str, uuid.UUID] | None:
    match = _REVIEW_REF_PATTERN.search(str(text or ""))
    if match is None:
        return None
    try:
        return match.group("kind"), uuid.UUID(match.group("job_id"))
    except ValueError:
        return None


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
    review: Any,
    draft: dict[str, Any],
    packaging_assets: dict[str, list[dict[str, Any]]],
    packaging_config: dict[str, Any],
    config: Any | None = None,
    avatar_materials: Any | None = None,
) -> str:
    automation = draft.get("automation_review") if isinstance(draft, dict) else {}
    identity_review = draft.get("identity_review") if isinstance(draft, dict) else {}
    review_reasons = list(automation.get("review_reasons") or []) if isinstance(automation, dict) else []
    blocking_reasons = list(automation.get("blocking_reasons") or []) if isinstance(automation, dict) else []
    workflow_mode = _WORKFLOW_MODE_LABELS.get(str(review.workflow_mode or ""), str(review.workflow_mode or "") or "未设置")
    enhancement_modes = [
        _ENHANCEMENT_MODE_LABELS.get(str(item), str(item))
        for item in (review.enhancement_modes or [])
    ]
    copy_style_key = str(
        draft.get("copy_style")
        or packaging_config.get("copy_style")
        or "attention_grabbing"
    ).strip()
    copy_style = _COPY_STYLE_LABELS.get(copy_style_key, copy_style_key or "未设置")
    keywords = _join_non_empty(draft.get("keywords") or draft.get("search_queries") or [])

    asset_index = _build_packaging_asset_index(packaging_assets)
    packaging_summary = [
        ("片头", _asset_label(asset_index, packaging_config.get("intro_asset_id"))),
        ("片尾", _asset_label(asset_index, packaging_config.get("outro_asset_id"))),
        ("转场 / 包装插片", _asset_list_label(asset_index, packaging_config.get("insert_asset_ids") or [])),
        ("水印", _asset_label(asset_index, packaging_config.get("watermark_asset_id"))),
        ("音乐", _asset_list_label(asset_index, packaging_config.get("music_asset_ids") or [])),
    ]
    style_summary = [
        ("字幕风格", _style_label(packaging_config.get("subtitle_style"), _SUBTITLE_STYLE_LABELS)),
        ("封面模板", _style_label(packaging_config.get("cover_style"), _COVER_STYLE_LABELS)),
        ("标题模板", _style_label(packaging_config.get("title_style"), _TITLE_STYLE_LABELS)),
        ("文案风格", copy_style),
        ("智能剪辑特效", _style_label(packaging_config.get("smart_effect_style"), _SMART_EFFECT_STYLE_LABELS)),
    ]
    review_checks = _build_review_checks(
        enhancement_modes=list(review.enhancement_modes or []),
        config=config,
        packaging_config=packaging_config,
        avatar_materials=avatar_materials,
    )
    content_lines = [
        f"- {label}：{_display_value(draft.get(key))}"
        for key, label in _CONTENT_FIELD_ORDER
    ]
    content_lines.append(f"- 关键词：{keywords or '未识别'}")

    reference_identity = []
    if str(draft.get("subject_brand") or "").strip():
        reference_identity.append(f"品牌：{draft.get('subject_brand')}")
    if str(draft.get("subject_model") or "").strip():
        reference_identity.append(f"型号：{draft.get('subject_model')}")

    lines = [
        f"任务：{source_name}",
        f"Job ID：{job_id}",
        "",
        "核对配置：",
        f"- 工作流模式：{workflow_mode}",
        f"- 文案风格：{copy_style}",
        f"- 增强模式：{', '.join(enhancement_modes) if enhancement_modes else '未启用'}",
        "- 增强模式素材检查：",
        *[f"  - {item['status']} | {item['label']}：{item['detail']}" for item in review_checks],
        "- 包装素材清单：",
        *[f"  - {label}：{value}" for label, value in packaging_summary],
        "- 风格模板清单：",
        *[f"  - {label}：{value}" for label, value in style_summary],
        "",
        "内容核对：",
        *content_lines,
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

    lines.extend(
        [
            "",
            "字幕摘录：",
            str(draft.get("transcript_excerpt") or "无"),
            "",
            "回复方式：",
            "1. 直接回复“通过”即可继续后续流程。",
            "2. 也可以直接回复自然语言修改意见，系统会按前端同款审核字段解析。",
            "3. 如需改工作流、增强模式或文案风格，也可以直接在回复里说明。",
        ]
    )
    return "\n".join(lines)


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
    avatar_materials: Any | None,
) -> list[dict[str, str]]:
    packaging_enabled = bool(packaging_config.get("enabled"))
    checks = [
        {
            "label": "包装素材与风格模板",
            "status": "齐全" if packaging_enabled else "待补",
            "detail": (
                "全局包装已启用，审核后会沿用当前包装素材池与风格模板。"
                if packaging_enabled
                else "全局包装当前关闭，成片会跳过片头片尾、水印和背景音乐包装。"
            ),
        }
    ]

    if "avatar_commentary" in enhancement_modes:
        presenter_id = str(_get_value(config, "avatar_presenter_id") or "").strip()
        ready_profile = _find_preview_ready_profile(_get_value(avatar_materials, "profiles") or [])
        if presenter_id:
            detail = (
                f"已绑定数字人模板：{presenter_id}"
                + (
                    f"；另有可自动切换档案：{ready_profile}"
                    if ready_profile
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
        has_insert = bool(packaging_config.get("insert_asset_ids") or [])
        smart_effect_style = _style_label(packaging_config.get("smart_effect_style"), _SMART_EFFECT_STYLE_LABELS)
        if packaging_enabled:
            detail = (
                f"已启用智能剪辑特效，当前风格为 {smart_effect_style}；包装配置里也包含插片/转场素材，可直接叠加节奏强化效果。"
                if has_insert
                else f"已启用智能剪辑特效，当前风格为 {smart_effect_style}；将基于剪辑时间线自动补转场、强调动画与局部视觉强化。"
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


def _display_value(value: Any) -> str:
    text = str(value or "").strip()
    return text or "未识别"


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
                )
            )
            slot_index += 1
    return candidates


async def _interpret_subtitle_review_reply(
    text: str,
    candidates: list[TelegramReviewCandidate],
) -> list[dict[str, str]]:
    normalized = str(text or "").strip()
    if not normalized:
        return []

    if _ACCEPT_ALL_PATTERN.search(normalized):
        return [
            {"correction_id": item.correction_id, "action": "accepted"}
            for item in candidates
        ]
    if _REJECT_ALL_PATTERN.search(normalized):
        return [
            {"correction_id": item.correction_id, "action": "rejected"}
            for item in candidates
        ]

    provider = get_reasoning_provider()
    candidate_payload = [
        {
            "slot": item.slot,
            "correction_id": item.correction_id,
            "subtitle_index": item.subtitle_index,
            "original": item.original,
            "suggested": item.suggested,
            "change_type": item.change_type,
            "confidence": item.confidence,
            "source": item.source,
        }
        for item in candidates
    ]
    prompt = (
        "你在解析 Telegram 里的字幕审核回复。"
        "用户会针对若干待审核纠错项给出接受、拒绝或改写意见。"
        "如果用户要求“改成 xxx”，请输出 action=accepted 且 override_text=xxx。"
        "不要编造候选项，必须只使用我提供的 correction_id。"
        "输出 JSON："
        '{"actions":[{"correction_id":"","action":"accepted","override_text":""}]}'
        f"\n待审核候选：{json.dumps(candidate_payload, ensure_ascii=False)}"
        f"\n用户回复：{normalized}"
    )
    response = await provider.complete(
        [
            Message(role="system", content="你是严谨的字幕审核动作解析助手。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.0,
        max_tokens=900,
        json_mode=True,
    )
    payload = response.as_json()
    actions = payload.get("actions") if isinstance(payload, dict) else []
    if not isinstance(actions, list):
        return []

    allowed_ids = {item.correction_id for item in candidates}
    normalized_actions: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in actions:
        if not isinstance(item, dict):
            continue
        correction_id = str(item.get("correction_id") or "").strip()
        action = str(item.get("action") or "").strip().lower()
        if correction_id not in allowed_ids or correction_id in seen_ids:
            continue
        if action not in {"accepted", "rejected"}:
            continue
        seen_ids.add(correction_id)
        record = {
            "correction_id": correction_id,
            "action": action,
        }
        override_text = str(item.get("override_text") or "").strip()
        if action == "accepted" and override_text:
            record["override_text"] = override_text
        normalized_actions.append(record)
    return normalized_actions


async def _interpret_content_profile_reply(review: Any, text: str) -> dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        return {}

    provider = get_reasoning_provider()
    allowed_workflow_modes = [item["value"] for item in build_active_workflow_mode_options()]
    allowed_enhancement_modes = [item["value"] for item in build_active_enhancement_mode_options()]
    prompt = (
        "你在把 Telegram 里的远程审核回复，转换成与前端内容审核表单完全一致的确认 payload。"
        "用户可能会直接说修改意见，也可能顺手改工作流模式、增强模式、关键词、文案风格。"
        "如果用户没有提某个字段，就不要编造。"
        "如果用户只是补充说明，请把它放进 correction_notes 或 supplemental_context。"
        "输出 JSON，字段只允许来自这个集合："
        '{"workflow_mode":"","enhancement_modes":[],"copy_style":"","subject_brand":"","subject_model":"","subject_type":"",'
        '"video_theme":"","hook_line":"","visible_text":"","summary":"","engagement_question":"","keywords":[],'
        '"correction_notes":"","supplemental_context":""}'
        f"\n当前工作流模式：{review.workflow_mode}"
        f"\n当前增强模式：{json.dumps(list(review.enhancement_modes or []), ensure_ascii=False)}"
        f"\n当前草稿：{json.dumps(review.final or review.draft or {}, ensure_ascii=False)}"
        f"\n允许的 workflow_mode：{json.dumps(allowed_workflow_modes, ensure_ascii=False)}"
        f"\n允许的 enhancement_modes：{json.dumps(allowed_enhancement_modes, ensure_ascii=False)}"
        f"\n用户回复：{normalized}"
    )
    try:
        response = await provider.complete(
            [
                Message(role="system", content="你是严谨的审核表单解析助手。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=1000,
            json_mode=True,
        )
        payload = response.as_json()
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    normalized_payload: dict[str, Any] = {}
    for key in (
        "copy_style",
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
        "summary",
        "engagement_question",
        "correction_notes",
        "supplemental_context",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            normalized_payload[key] = value

    workflow_mode = str(payload.get("workflow_mode") or "").strip()
    if workflow_mode in allowed_workflow_modes:
        normalized_payload["workflow_mode"] = workflow_mode

    enhancement_modes = payload.get("enhancement_modes") or []
    if isinstance(enhancement_modes, list):
        filtered_modes: list[str] = []
        for item in enhancement_modes:
            value = str(item or "").strip()
            if value and value in allowed_enhancement_modes and value not in filtered_modes:
                filtered_modes.append(value)
        if filtered_modes:
            normalized_payload["enhancement_modes"] = filtered_modes

    keywords = payload.get("keywords") or []
    if isinstance(keywords, list):
        normalized_keywords: list[str] = []
        for item in keywords:
            value = str(item or "").strip()
            if value and value not in normalized_keywords:
                normalized_keywords.append(value)
        if normalized_keywords:
            normalized_payload["keywords"] = normalized_keywords

    if not normalized_payload:
        return {"correction_notes": normalized}
    if "correction_notes" not in normalized_payload:
        normalized_payload["correction_notes"] = normalized
    return normalized_payload


_telegram_review_bot_service: TelegramReviewBotService | None = None


def get_telegram_review_bot_service() -> TelegramReviewBotService:
    global _telegram_review_bot_service
    if _telegram_review_bot_service is None:
        _telegram_review_bot_service = TelegramReviewBotService()
    return _telegram_review_bot_service
