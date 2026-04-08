from __future__ import annotations

import json
import re
import uuid
from typing import Any, Callable, Iterable, Protocol

REVIEW_KIND_CONTENT = "content_profile"
REVIEW_KIND_SUBTITLE = "subtitle_review"
REVIEW_KIND_FINAL = "final_review"

REVIEW_REF_PATTERN = re.compile(
    r"RC:(?P<kind>content_profile|subtitle_review|final_review):(?P<job_id>[0-9a-fA-F-]{36})"
)
REVIEW_CALLBACK_PATTERN = re.compile(
    r"^RCB:(?P<kind>final):(?P<job_id>[0-9a-fA-F-]{36}):(?P<action>[a-z_]+)$"
)
SIMPLE_APPROVAL_PATTERN = re.compile(r"^(通过|确认|继续|好的|ok|okay|yes|y|pass)[！!。.，,\s]*$", re.IGNORECASE)
FINAL_APPROVAL_PATTERN = re.compile(
    r"(?:(?:整体|整片|成片|片子|视频)\s*(?:通过|确认|继续)|(?:通过|确认|继续)\s*(?:整体|整片|成片|片子|视频))",
    re.IGNORECASE,
)
ACCEPT_ALL_PATTERN = re.compile(r"(全部|全都|都)(通过|接受|采纳)|全部接受|全部通过", re.IGNORECASE)
REJECT_ALL_PATTERN = re.compile(r"(全部|全都|都)(拒绝|驳回)|全部拒绝", re.IGNORECASE)
SUBTITLE_SLOT_PATTERN = re.compile(r"(?i)(?<![A-Za-z0-9])S\d{1,3}(?![A-Za-z0-9])")
FULL_SUBTITLE_ACTION_PATTERN = re.compile(
    r"(?is)(?<![A-Za-z0-9])L(?P<slot>\d{1,4})(?![A-Za-z0-9])\s*"
    r"(?:(?P<pass>通过|ok|okay|没问题|无误|无需修改|不用改)"
    r"|(?:(?:改成|改为|修改为|替换为)\s*[:：]?\s*(?P<replace>.*?)))"
    r"(?=(?:[\s，,。；;、!！?？]*)?(?<![A-Za-z0-9])L\d{1,4}(?![A-Za-z0-9])|[\s，,。；;、!！?？]*$)"
)
NEGATED_SUBTITLE_CONTENT_PATTERN = re.compile(r"字幕(?:内容|文本)?(?:本身)?(?:没问题|没有问题|无需修改|不用改)")
CONTENT_PROFILE_SUBTITLE_REVIEW_KEYWORDS = (
    "字幕校对",
    "字幕纠错",
    "字幕复核",
    "字幕确认",
    "字幕还需要",
    "字幕还有问题",
    "字幕不太对",
    "字幕不对",
    "字幕有问题",
    "字幕有错",
    "字幕错别字",
    "字幕术语",
    "字幕时间",
    "字幕不同步",
    "术语还要",
    "错别字还要",
)
FINAL_REVIEW_CALLBACK_ACTIONS = ("approve", "cover", "music", "platform", "avatar")
REVIEW_KEYWORD_SPLIT_RE = re.compile(r"[\s,，、/|+*×xX·•_=\-]+")
REVIEW_KEYWORD_CONNECTOR_RE = re.compile(r"(?:与|和|及|及其|以及|并|并且|对比|联名|还是|或者)")
REVIEW_KEYWORD_TOKEN_LIMIT = 10

WORKFLOW_MODE_ALIASES = {
    "standard_edit": ("standard_edit", "标准成片", "标准剪辑", "标准模式"),
    "long_text_to_video": ("long_text_to_video", "长文本转视频", "长文转视频", "图文转视频", "文稿转视频"),
}
ENHANCEMENT_MODE_ALIASES = {
    "multilingual_translation": ("multilingual_translation", "多语言翻译", "多语翻译"),
    "auto_review": ("auto_review", "自动审核", "自动复核"),
    "avatar_commentary": ("avatar_commentary", "数字人解说", "数字人口播", "虚拟人口播"),
    "ai_effects": ("ai_effects", "智能剪辑特效", "ai特效", "ai 特效"),
    "ai_director": ("ai_director", "ai导演", "ai 导演"),
}
KEYWORDS_CAPTURE_PATTERNS = (
    re.compile(r"(?:关键词|关键字)\s*(?:改成|改为|更新为|补充|增加|加上|设为|设置为|[:：])\s*([^\n。！？!?]+)"),
    re.compile(r"(?:关键词|关键字)\s*(?:有|是)\s*([^\n。！？!?]+)"),
)


class SubtitleReviewCandidate(Protocol):
    slot: str
    correction_id: str
    subtitle_index: int
    original: str
    suggested: str
    change_type: str
    confidence: float
    source: str | None


class SubtitleLineCandidate(Protocol):
    slot: str
    subtitle_item_id: str


def extract_review_reference(text: str) -> tuple[str, uuid.UUID] | None:
    match = REVIEW_REF_PATTERN.search(str(text or ""))
    if match is None:
        return None
    try:
        return match.group("kind"), uuid.UUID(match.group("job_id"))
    except ValueError:
        return None


def extract_review_reference_from_message(message: dict[str, Any]) -> tuple[str, uuid.UUID] | None:
    for candidate in (
        _message_text(message),
        _message_text(message.get("reply_to_message") or {}),
    ):
        review_ref = extract_review_reference(candidate)
        if review_ref is not None:
            return review_ref
    return None


def extract_review_callback_reference(
    data: str,
    *,
    allowed_actions: Iterable[str] | None = None,
) -> tuple[str, uuid.UUID, str] | None:
    match = REVIEW_CALLBACK_PATTERN.match(str(data or "").strip())
    if match is None:
        return None
    action = str(match.group("action") or "").strip().lower()
    accepted_actions = (
        tuple(FINAL_REVIEW_CALLBACK_ACTIONS)
        if allowed_actions is None
        else tuple(str(item).strip().lower() for item in allowed_actions if str(item).strip())
    )
    if action not in accepted_actions:
        return None
    try:
        return REVIEW_KIND_FINAL, uuid.UUID(match.group("job_id")), action
    except ValueError:
        return None


def build_review_callback_data(
    kind: str,
    job_id: uuid.UUID,
    action: str,
    *,
    allowed_actions: Iterable[str] | None = None,
) -> str | None:
    if kind != REVIEW_KIND_FINAL:
        return None
    normalized_action = str(action or "").strip().lower()
    accepted_actions = (
        tuple(FINAL_REVIEW_CALLBACK_ACTIONS)
        if allowed_actions is None
        else tuple(str(item).strip().lower() for item in allowed_actions if str(item).strip())
    )
    if normalized_action not in accepted_actions:
        return None
    return f"RCB:final:{job_id}:{normalized_action}"


def looks_like_subtitle_review_reply(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    return bool(
        ACCEPT_ALL_PATTERN.search(normalized)
        or REJECT_ALL_PATTERN.search(normalized)
        or SUBTITLE_SLOT_PATTERN.search(normalized)
    )


def looks_like_content_profile_subtitle_followup(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if NEGATED_SUBTITLE_CONTENT_PATTERN.search(normalized):
        return False
    if looks_like_subtitle_review_reply(normalized):
        return True
    return any(keyword in normalized for keyword in CONTENT_PROFILE_SUBTITLE_REVIEW_KEYWORDS)


def interpret_full_subtitle_review_reply(
    text: str,
    subtitle_lines: list[SubtitleLineCandidate],
) -> tuple[bool, list[dict[str, str]]]:
    normalized = str(text or "").strip()
    if not normalized:
        return False, []
    if ACCEPT_ALL_PATTERN.search(normalized):
        return True, []

    line_by_slot = {str(item.slot).lower(): item for item in subtitle_lines}
    actions: list[dict[str, str]] = []
    for match in FULL_SUBTITLE_ACTION_PATTERN.finditer(normalized):
        slot = f"L{match.group('slot')}".lower()
        candidate = line_by_slot.get(slot)
        if candidate is None:
            continue
        replacement = str(match.group("replace") or "").strip().rstrip("，。,；; ")
        if match.group("pass"):
            actions.append(
                {
                    "subtitle_item_id": str(candidate.subtitle_item_id),
                    "action": "accepted",
                }
            )
        elif replacement:
            actions.append(
                {
                    "subtitle_item_id": str(candidate.subtitle_item_id),
                    "action": "updated",
                    "override_text": replacement,
                }
            )
    return False, actions


async def interpret_subtitle_review_reply(
    text: str,
    candidates: list[SubtitleReviewCandidate],
    *,
    provider: Any,
    message_cls: type[Any],
) -> list[dict[str, str]]:
    normalized = str(text or "").strip()
    if not normalized:
        return []

    if ACCEPT_ALL_PATTERN.search(normalized):
        return [{"correction_id": item.correction_id, "action": "accepted"} for item in candidates]
    if REJECT_ALL_PATTERN.search(normalized):
        return [{"correction_id": item.correction_id, "action": "rejected"} for item in candidates]

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
    try:
        response = await provider.complete(
            [
                message_cls(role="system", content="你是严谨的字幕审核动作解析助手。"),
                message_cls(role="user", content=prompt),
            ],
            temperature=0.0,
            max_tokens=900,
            json_mode=True,
        )
        payload = response.as_json()
    except Exception:
        payload = {}

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
        record = {"correction_id": correction_id, "action": action}
        override_text = str(item.get("override_text") or "").strip()
        if action == "accepted" and override_text:
            record["override_text"] = override_text
        normalized_actions.append(record)
    return normalized_actions


async def interpret_content_profile_reply(
    review: Any,
    text: str,
    *,
    provider: Any,
    message_cls: type[Any],
    field_guidelines: str,
    normalize_subject_type: Callable[[str], str],
    allowed_workflow_modes: list[str],
    allowed_enhancement_modes: list[str],
) -> dict[str, Any]:
    normalized = str(text or "").strip()
    if not normalized:
        return {}

    prompt = (
        "你在把 Telegram 里的远程审核回复，转换成与前端内容审核表单完全一致的确认 payload。"
        "用户可能会直接说修改意见，也可能顺手改工作流模式、增强模式、关键词、文案风格。"
        f"字段规则：{field_guidelines}\n"
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
                message_cls(role="system", content="你是严谨的审核表单解析助手。"),
                message_cls(role="user", content=prompt),
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

    return normalize_content_profile_reply_payload(
        payload=payload,
        source_text=normalized,
        normalize_subject_type=normalize_subject_type,
        allowed_workflow_modes=allowed_workflow_modes,
        allowed_enhancement_modes=allowed_enhancement_modes,
    )


def normalize_content_profile_reply_payload(
    *,
    payload: dict[str, Any],
    source_text: str,
    normalize_subject_type: Callable[[str], str],
    allowed_workflow_modes: list[str],
    allowed_enhancement_modes: list[str],
) -> dict[str, Any]:
    normalized_payload: dict[str, Any] = {}
    normalized_subject_type = normalize_subject_type(str(payload.get("subject_type") or ""))
    if normalized_subject_type:
        normalized_payload["subject_type"] = normalized_subject_type

    for key in (
        "copy_style",
        "subject_brand",
        "subject_model",
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

    workflow_mode = _extract_allowed_value(
        raw_value=str(payload.get("workflow_mode") or "").strip(),
        allowed_values=allowed_workflow_modes,
    )
    if not workflow_mode:
        workflow_mode = _extract_workflow_mode_from_text(source_text, allowed_workflow_modes=allowed_workflow_modes)
    if workflow_mode:
        normalized_payload["workflow_mode"] = workflow_mode

    enhancement_modes = _normalize_enhancement_modes(
        values=payload.get("enhancement_modes") or [],
        allowed_values=allowed_enhancement_modes,
    )
    for mode in _extract_enhancement_modes_from_text(source_text, allowed_enhancement_modes=allowed_enhancement_modes):
        if mode not in enhancement_modes:
            enhancement_modes.append(mode)
    if enhancement_modes:
        normalized_payload["enhancement_modes"] = enhancement_modes

    keywords = _normalize_keywords(payload.get("keywords") or [])
    for token in _extract_keywords_from_text(source_text):
        if token not in keywords:
            keywords.append(token)
    if keywords:
        normalized_payload["keywords"] = keywords

    if not normalized_payload:
        return {"correction_notes": source_text}
    if "correction_notes" not in normalized_payload:
        normalized_payload["correction_notes"] = source_text
    return normalized_payload


def _extract_allowed_value(*, raw_value: str, allowed_values: list[str]) -> str:
    value = str(raw_value or "").strip()
    if value and value in allowed_values:
        return value
    return ""


def _extract_workflow_mode_from_text(text: str, *, allowed_workflow_modes: list[str]) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return ""
    for mode in allowed_workflow_modes:
        aliases = tuple(str(item).lower() for item in WORKFLOW_MODE_ALIASES.get(mode, ()) if str(item).strip())
        if mode.lower() in normalized or any(alias in normalized for alias in aliases):
            return mode
    return ""


def _extract_enhancement_modes_from_text(text: str, *, allowed_enhancement_modes: list[str]) -> list[str]:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return []
    resolved: list[str] = []
    for mode in allowed_enhancement_modes:
        aliases = tuple(str(item).lower() for item in ENHANCEMENT_MODE_ALIASES.get(mode, ()) if str(item).strip())
        if mode.lower() in normalized or any(alias in normalized for alias in aliases):
            resolved.append(mode)
    return resolved


def _normalize_enhancement_modes(*, values: Any, allowed_values: list[str]) -> list[str]:
    filtered_modes: list[str] = []
    allowed = set(allowed_values)
    if not isinstance(values, list):
        return filtered_modes
    for item in values:
        value = str(item or "").strip()
        if value and value in allowed and value not in filtered_modes:
            filtered_modes.append(value)
    return filtered_modes


def _extract_keywords_from_text(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []
    tokens: list[str] = []
    for pattern in KEYWORDS_CAPTURE_PATTERNS:
        for match in pattern.finditer(normalized):
            segment = str(match.group(1) or "").strip()
            if not segment:
                continue
            for token in _split_keyword_tokens(segment):
                if token not in tokens:
                    tokens.append(token)
                    if len(tokens) >= REVIEW_KEYWORD_TOKEN_LIMIT:
                        return tokens
    return tokens


def _split_keyword_tokens(text: str) -> list[str]:
    sanitized = REVIEW_KEYWORD_CONNECTOR_RE.sub(" ", str(text or "").strip())
    raw_tokens = REVIEW_KEYWORD_SPLIT_RE.split(sanitized)
    deduped: list[str] = []
    for raw in raw_tokens:
        token = str(raw or "").strip().strip("，,。；;:：")
        if not token:
            continue
        lowered = token.lower()
        if lowered in {"关键词", "关键字", "模式", "增强模式"}:
            continue
        if token not in deduped:
            deduped.append(token)
            if len(deduped) >= REVIEW_KEYWORD_TOKEN_LIMIT:
                return deduped
    return deduped


def _normalize_keywords(values: Any) -> list[str]:
    normalized_keywords: list[str] = []
    if not isinstance(values, list):
        return normalized_keywords
    for item in values:
        value = str(item or "").strip()
        if value and value not in normalized_keywords:
            normalized_keywords.append(value)
            if len(normalized_keywords) >= REVIEW_KEYWORD_TOKEN_LIMIT:
                return normalized_keywords
    return normalized_keywords


def _message_text(message: dict[str, Any]) -> str:
    return str(message.get("text") or message.get("caption") or "").strip()
