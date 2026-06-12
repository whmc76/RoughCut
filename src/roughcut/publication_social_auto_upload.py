from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SOCIAL_AUTO_UPLOAD_ADAPTER = "social_auto_upload"
SOCIAL_AUTO_UPLOAD_SUPPORTED_PLATFORMS = {
    "douyin": "douyin",
    "kuaishou": "kuaishou",
    "xiaohongshu": "xiaohongshu",
    "bilibili": "bilibili",
    "wechat-channels": "tencent",
}

BILIBILI_DEFAULT_DECLARATION = "内容无需标注"
BILIBILI_DECLARATION_ALIASES = {
    "": BILIBILI_DEFAULT_DECLARATION,
    "原创": BILIBILI_DEFAULT_DECLARATION,
    "原創": BILIBILI_DEFAULT_DECLARATION,
    "原创声明": BILIBILI_DEFAULT_DECLARATION,
    "无需声明": BILIBILI_DEFAULT_DECLARATION,
    "无需添加自主声明": BILIBILI_DEFAULT_DECLARATION,
    "内容无需标注": "内容无需标注",
    "含ai生成内容": "含AI生成内容",
    "含虚构演绎内容": "含虚构演绎内容",
    "内容含营销信息": "内容含营销信息",
    "个人观点仅供参考": "个人观点，仅供参考",
    "个人观点，仅供参考": "个人观点，仅供参考",
    "内容为转载": "内容为转载",
}

# Complete Bilibili tid table used by the social-auto-upload adapter.
# Source basis:
# - biliup tid reference
# - bilitool tid reference
# RoughCut also adds a few pragmatic aliases such as "生活兴趣/户外潮流"
# so existing plan/category strings can resolve without caller-side patches.
BILIBILI_TID_ROWS: tuple[tuple[str, str, int], ...] = (
    ("动画", "动画", 1),
    ("动画", "MAD·AMV", 24),
    ("动画", "MMD·3D", 25),
    ("动画", "短片·手书", 47),
    ("动画", "配音", 257),
    ("动画", "手办·模玩", 210),
    ("动画", "特摄", 86),
    ("动画", "动漫杂谈", 253),
    ("动画", "综合", 27),
    ("番剧", "番剧", 13),
    ("番剧", "资讯", 51),
    ("番剧", "官方延伸", 152),
    ("番剧", "完结动画", 32),
    ("番剧", "连载动画", 33),
    ("国创", "国创", 167),
    ("国创", "国产动画", 153),
    ("国创", "国产原创相关", 168),
    ("国创", "布袋戏", 169),
    ("国创", "资讯", 170),
    ("国创", "动态漫·广播剧", 195),
    ("音乐", "音乐", 3),
    ("音乐", "原创音乐", 28),
    ("音乐", "翻唱", 31),
    ("音乐", "VOCALOID·UTAU", 30),
    ("音乐", "演奏", 59),
    ("音乐", "MV", 193),
    ("音乐", "音乐现场", 29),
    ("音乐", "音乐综合", 130),
    ("音乐", "乐评盘点", 243),
    ("音乐", "音乐教学", 244),
    ("舞蹈", "舞蹈", 129),
    ("舞蹈", "宅舞", 20),
    ("舞蹈", "舞蹈综合", 154),
    ("舞蹈", "舞蹈教程", 156),
    ("舞蹈", "街舞", 198),
    ("舞蹈", "明星舞蹈", 199),
    ("舞蹈", "国风舞蹈", 200),
    ("舞蹈", "手势·网红舞", 255),
    ("游戏", "游戏", 4),
    ("游戏", "单机游戏", 17),
    ("游戏", "电子竞技", 171),
    ("游戏", "手机游戏", 172),
    ("游戏", "网络游戏", 65),
    ("游戏", "桌游棋牌", 173),
    ("游戏", "GMV", 121),
    ("游戏", "音游", 136),
    ("游戏", "Mugen", 19),
    ("知识", "知识", 36),
    ("知识", "科学科普", 201),
    ("知识", "社科·法律·心理", 124),
    ("知识", "人文历史", 228),
    ("知识", "财经商业", 207),
    ("知识", "校园学习", 208),
    ("知识", "职业职场", 209),
    ("知识", "设计·创意", 229),
    ("知识", "野生技术协会", 122),
    ("科技", "科技", 188),
    ("科技", "数码", 95),
    ("科技", "软件应用", 230),
    ("科技", "计算机技术", 231),
    ("科技", "科工机械", 232),
    ("科技", "极客DIY", 233),
    ("运动", "运动", 234),
    ("运动", "篮球", 235),
    ("运动", "足球", 249),
    ("运动", "健身", 164),
    ("运动", "竞技体育", 236),
    ("运动", "运动文化", 237),
    ("运动", "运动综合", 238),
    ("汽车", "汽车", 223),
    ("汽车", "汽车知识科普", 258),
    ("汽车", "赛车", 245),
    ("汽车", "改装玩车", 246),
    ("汽车", "新能源车", 247),
    ("汽车", "房车", 248),
    ("汽车", "摩托车", 240),
    ("汽车", "购车攻略", 227),
    ("汽车", "汽车生活", 176),
    ("生活", "生活", 160),
    ("生活", "搞笑", 138),
    ("生活", "出行", 250),
    ("生活", "三农", 251),
    ("生活", "家居房产", 239),
    ("生活", "手工", 161),
    ("生活", "绘画", 162),
    ("生活", "日常", 21),
    ("生活", "亲子", 254),
    ("美食", "美食", 211),
    ("美食", "美食制作", 76),
    ("美食", "美食侦探", 212),
    ("美食", "美食测评", 213),
    ("美食", "田园美食", 214),
    ("美食", "美食记录", 215),
    ("动物圈", "动物圈", 217),
    ("动物圈", "喵星人", 218),
    ("动物圈", "汪星人", 219),
    ("动物圈", "动物二创", 220),
    ("动物圈", "野生动物", 221),
    ("动物圈", "小宠异宠", 222),
    ("动物圈", "动物综合", 75),
    ("鬼畜", "鬼畜", 119),
    ("鬼畜", "鬼畜调教", 22),
    ("鬼畜", "音MAD", 26),
    ("鬼畜", "人力VOCALOID", 126),
    ("鬼畜", "鬼畜剧场", 216),
    ("鬼畜", "教程演示", 127),
    ("时尚", "时尚", 155),
    ("时尚", "美妆护肤", 157),
    ("时尚", "仿妆cos", 252),
    ("时尚", "穿搭", 158),
    ("时尚", "时尚潮流", 159),
    ("资讯", "资讯", 202),
    ("资讯", "热点", 203),
    ("资讯", "环球", 204),
    ("资讯", "社会", 205),
    ("资讯", "综合", 206),
    ("娱乐", "娱乐", 5),
    ("娱乐", "综艺", 71),
    ("娱乐", "娱乐杂谈", 241),
    ("娱乐", "粉丝创作", 242),
    ("娱乐", "明星综合", 137),
    ("影视", "影视", 181),
    ("影视", "影视杂谈", 182),
    ("影视", "影视剪辑", 183),
    ("影视", "小剧场", 85),
    ("影视", "预告·资讯", 184),
    ("影视", "短片", 256),
    ("纪录片", "纪录片", 177),
    ("纪录片", "人文·历史", 37),
    ("纪录片", "科学·探索·自然", 178),
    ("纪录片", "军事", 179),
    ("纪录片", "社会·美食·旅行", 180),
    ("电影", "电影", 23),
    ("电影", "华语电影", 147),
    ("电影", "欧美电影", 145),
    ("电影", "日本电影", 146),
    ("电影", "其他国家", 83),
    ("电视剧", "电视剧", 11),
    ("电视剧", "国产剧", 185),
    ("电视剧", "海外剧", 187),
)


def _build_bilibili_tid_aliases() -> dict[str, int]:
    aliases: dict[str, int] = {}
    for major, minor, tid in BILIBILI_TID_ROWS:
        keys = {
            major,
            minor,
            f"{major}/{minor}",
            f"{major}-{minor}",
        }
        # RoughCut historical category strings and a few practical fallbacks.
        if major == "科技" and minor == "科工机械":
            keys.add("工业工程机械")
        if major == "舞蹈" and minor == "手势·网红舞":
            keys.add("手势网红舞")
        if major == "动画" and minor == "短片·手书":
            keys.add("短片手书")
        if major == "知识" and minor == "社科·法律·心理":
            keys.add("社科法律心理")
        if major == "纪录片" and minor == "科学·探索·自然":
            keys.add("科学探索自然")
        if major == "纪录片" and minor == "人文·历史":
            keys.add("人文历史")
        if major == "影视" and minor == "预告·资讯":
            keys.add("预告资讯")
        if major == "生活" and minor == "出行":
            keys.add("生活出行")
            keys.add("生活兴趣/户外潮流")
            keys.add("生活兴趣-户外潮流")
            keys.add("户外潮流")
        if major == "运动" and minor == "篮球":
            keys.add("篮球足球")
        for key in keys:
            aliases[_normalize_bilibili_category_key(key)] = tid
    return aliases

@dataclass(frozen=True)
class SocialAutoUploadCommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def supports_social_auto_upload_platform(platform: Any) -> bool:
    return str(platform or "").strip().lower() in SOCIAL_AUTO_UPLOAD_SUPPORTED_PLATFORMS


def social_auto_upload_cli_platform(platform: Any) -> str:
    normalized = str(platform or "").strip().lower()
    if normalized not in SOCIAL_AUTO_UPLOAD_SUPPORTED_PLATFORMS:
        raise ValueError(f"social-auto-upload 不支持平台：{normalized or '<empty>'}")
    return SOCIAL_AUTO_UPLOAD_SUPPORTED_PLATFORMS[normalized]


def build_social_auto_upload_account_name(attempt: Any) -> str:
    candidates = [
        getattr(attempt, "account_label", None),
        getattr(attempt, "credential_id", None),
        getattr(attempt, "creator_profile_id", None),
        getattr(attempt, "platform", None),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return "default"


def build_social_auto_upload_check_command(
    *,
    root: str,
    python_executable: str,
    platform: str,
    account_name: str,
) -> list[str]:
    return [
        python_executable,
        "sau_cli.py",
        social_auto_upload_cli_platform(platform),
        "check",
        "--account",
        account_name,
    ]


def build_social_auto_upload_login_command(
    *,
    python_executable: str,
    platform: str,
    account_name: str,
    headless: bool,
) -> list[str]:
    command = [
        python_executable,
        "sau_cli.py",
        social_auto_upload_cli_platform(platform),
        "login",
        "--account",
        account_name,
    ]
    command.append("--headless" if headless else "--headed")
    return command


def build_social_auto_upload_upload_command(
    *,
    python_executable: str,
    platform: str,
    account_name: str,
    request_payload: dict[str, Any],
) -> list[str]:
    normalized_platform = str(platform or "").strip().lower()
    title = str(request_payload.get("title") or "").strip()
    body = str(request_payload.get("body") or "").strip()
    tags = [str(item).strip().lstrip("#") for item in (request_payload.get("hashtags") or []) if str(item).strip()]
    media_items = [item for item in (request_payload.get("media_items") or []) if isinstance(item, dict)]
    local_media_path = str((media_items[0] if media_items else {}).get("local_path") or "").strip()
    if not local_media_path:
        raise ValueError("social-auto-upload 需要 request_payload.media_items[0].local_path")

    command = [
        python_executable,
        "sau_cli.py",
        social_auto_upload_cli_platform(normalized_platform),
        "upload-video",
        "--account",
        account_name,
        "--file",
        local_media_path,
        "--title",
        title,
    ]
    command.extend(["--desc", body or title])
    if normalized_platform == "bilibili":
        tid = maybe_resolve_bilibili_tid(request_payload)
        category_display = resolve_bilibili_category_display(request_payload)
        if tid:
            command.extend(["--tid", tid])
        if category_display:
            command.extend(["--category", category_display])
        if not tid and not category_display:
            raise ValueError("Bilibili 通过 social-auto-upload 发布时至少需要可用的 category 或 tid。")
    if tags:
        command.extend(["--tags", ",".join(tags)])
    portrait_thumbnail, landscape_thumbnail = _resolve_social_auto_upload_thumbnails(
        request_payload,
        platform=normalized_platform,
    )
    if normalized_platform == "douyin":
        if landscape_thumbnail:
            command.extend(["--thumbnail-landscape", landscape_thumbnail])
        if portrait_thumbnail:
            command.extend(["--thumbnail-portrait", portrait_thumbnail])
        elif str(request_payload.get("cover_path") or "").strip():
            command.extend(["--thumbnail", str(request_payload.get("cover_path") or "").strip()])
    elif normalized_platform == "bilibili":
        bilibili_cover_4_3, bilibili_cover_16_9 = _resolve_bilibili_social_auto_upload_thumbnails(
            request_payload
        )
        if bilibili_cover_4_3:
            command.extend(["--thumbnail-4-3", bilibili_cover_4_3])
        if bilibili_cover_16_9:
            command.extend(["--thumbnail-16-9", bilibili_cover_16_9])
    elif normalized_platform == "wechat-channels":
        if landscape_thumbnail:
            command.extend(["--thumbnail-landscape", landscape_thumbnail])
        if portrait_thumbnail:
            command.extend(["--thumbnail-portrait", portrait_thumbnail])
        elif str(request_payload.get("cover_path") or "").strip():
            command.extend(["--thumbnail", str(request_payload.get("cover_path") or "").strip()])
        category = str(request_payload.get("category") or "").strip()
        if category:
            command.extend(["--category", category])
    elif normalized_platform in {"kuaishou", "xiaohongshu"}:
        thumbnail = portrait_thumbnail or landscape_thumbnail or str(request_payload.get("cover_path") or "").strip()
        if thumbnail:
            command.extend(["--thumbnail", thumbnail])
    if normalized_platform == "bilibili":
        declaration = _resolve_bilibili_declaration(request_payload)
        if declaration:
            command.extend(["--declaration", declaration])
    if normalized_platform == "xiaohongshu":
        group_chat = _resolve_xiaohongshu_group_chat(request_payload)
        if group_chat:
            command.extend(["--group-chat", group_chat])
        if _resolve_xiaohongshu_original_declaration(request_payload):
            command.append("--original-declaration")
    if normalized_platform == "kuaishou":
        declaration = str(request_payload.get("declaration") or "").strip()
        if declaration:
            command.extend(["--declaration", declaration])
    collection_name = _resolve_social_auto_upload_collection_name(request_payload)
    if collection_name and normalized_platform in {"douyin", "kuaishou", "xiaohongshu", "wechat-channels", "bilibili"}:
        command.extend(["--collection", collection_name])
    scheduled_publish_at = _normalize_schedule_value(request_payload.get("scheduled_publish_at"))
    if scheduled_publish_at:
        command.extend(["--schedule", scheduled_publish_at])
    return command


def _resolve_social_auto_upload_thumbnails(
    request_payload: dict[str, Any],
    *,
    platform: str,
) -> tuple[str, str]:
    cover_slots: list[dict[str, Any]] = []
    for source in (
        request_payload.get("cover_slots"),
        (request_payload.get("copy_material") or {}).get("cover_slots")
        if isinstance(request_payload.get("copy_material"), dict)
        else None,
    ):
        if isinstance(source, list):
            cover_slots.extend(item for item in source if isinstance(item, dict))

    portrait = ""
    landscape = ""
    for slot in cover_slots:
        slot_name = str(slot.get("slot") or slot.get("matrix_key") or "").strip().lower()
        cover_path = str(slot.get("cover_path") or "").strip()
        members = [str(item).strip().lower() for item in slot.get("members") or [] if str(item).strip()]
        if not cover_path:
            continue
        is_portrait_slot = slot_name in {"portrait_3_4", "vertical_3_4"}
        is_landscape_slot = slot_name in {"landscape_4_3", "horizontal_4_3"}
        if members and platform not in members and not is_portrait_slot and not is_landscape_slot:
            continue
        if not portrait and is_portrait_slot:
            portrait = cover_path
        if not landscape and is_landscape_slot:
            landscape = cover_path
    return portrait, landscape


def _resolve_bilibili_social_auto_upload_thumbnails(
    request_payload: dict[str, Any],
) -> tuple[str, str]:
    cover_4_3 = ""
    cover_16_9 = ""

    def _assign_slot(slot_name: str, cover_path: str) -> None:
        nonlocal cover_4_3, cover_16_9
        normalized = str(slot_name or "").strip().lower()
        path = str(cover_path or "").strip()
        if not path:
            return
        if normalized in {"landscape_4_3", "horizontal_4_3"} and not cover_4_3:
            cover_4_3 = path
        if normalized in {"landscape_16_9", "horizontal_16_9"} and not cover_16_9:
            cover_16_9 = path

    def _iter_cover_matrices() -> list[dict[str, Any]]:
        matrices: list[dict[str, Any]] = []
        for source in (
            request_payload.get("cover_matrix"),
            (request_payload.get("copy_material") or {}).get("cover_matrix")
            if isinstance(request_payload.get("copy_material"), dict)
            else None,
        ):
            if isinstance(source, dict):
                matrices.append(source)
        return matrices

    for matrix in _iter_cover_matrices():
        for slot_name, slot_payload in matrix.items():
            if not isinstance(slot_payload, dict):
                continue
            _assign_slot(slot_name, str(slot_payload.get("cover_path") or "").strip())

    cover_slots: list[dict[str, Any]] = []
    for source in (
        request_payload.get("cover_slots"),
        (request_payload.get("copy_material") or {}).get("cover_slots")
        if isinstance(request_payload.get("copy_material"), dict)
        else None,
    ):
        if isinstance(source, list):
            cover_slots.extend(item for item in source if isinstance(item, dict))

    for slot in cover_slots:
        _assign_slot(
            str(slot.get("slot") or slot.get("matrix_key") or "").strip(),
            str(slot.get("cover_path") or "").strip(),
        )

    return cover_4_3, cover_16_9




def _resolve_xiaohongshu_group_chat(request_payload: dict[str, Any]) -> str:
    overrides = request_payload.get("platform_specific_overrides")
    if not isinstance(overrides, dict):
        return ""
    for candidate in (
        overrides.get("selected_group_chat"),
        overrides.get("group_chat"),
        overrides.get("group_chat_name"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _resolve_xiaohongshu_original_declaration(request_payload: dict[str, Any]) -> bool:
    declaration = str(request_payload.get("declaration") or "").strip()
    if "原创" in declaration:
        return True
    overrides = request_payload.get("platform_specific_overrides")
    if not isinstance(overrides, dict):
        return False
    selected = [str(item).strip() for item in overrides.get("selected_declarations") or [] if str(item).strip()]
    return any("原创" in item for item in selected)


def _resolve_bilibili_declaration(request_payload: dict[str, Any]) -> str:
    candidates: list[str] = []
    for candidate in (
        request_payload.get("declaration"),
        (request_payload.get("platform_specific_overrides") or {}).get("declaration")
        if isinstance(request_payload.get("platform_specific_overrides"), dict)
        else None,
    ):
        text = str(candidate or "").strip()
        if text:
            candidates.append(text)
    raw = candidates[0] if candidates else BILIBILI_DEFAULT_DECLARATION
    key = _normalize_bilibili_category_key(raw)
    return BILIBILI_DECLARATION_ALIASES.get(key, raw or BILIBILI_DEFAULT_DECLARATION)


def _resolve_social_auto_upload_collection_name(request_payload: dict[str, Any]) -> str:
    collection = request_payload.get("collection")
    if isinstance(collection, dict):
        text = str(collection.get("name") or collection.get("title") or collection.get("label") or "").strip()
        if text:
            return text
    text = str(request_payload.get("collection_name") or "").strip()
    if text:
        return text
    overrides = request_payload.get("platform_specific_overrides")
    if not isinstance(overrides, dict):
        return ""
    collection_management = (
        dict(overrides.get("collection_management"))
        if isinstance(overrides.get("collection_management"), dict)
        else {}
    )
    for candidate in (
        collection_management.get("selected_collection_name"),
        collection_management.get("target_collection_name"),
        collection_management.get("collection_name"),
        overrides.get("selected_collection_name"),
        overrides.get("target_collection_name"),
        overrides.get("collection_name"),
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def resolve_bilibili_category_display(request_payload: dict[str, Any]) -> str:
    category = request_payload.get("category")
    category_selection_plan = (
        (request_payload.get("platform_specific_overrides") or {}).get("category_selection_plan")
        if isinstance(request_payload.get("platform_specific_overrides"), dict)
        else None
    )
    for candidate in (
        category,
        category_selection_plan.get("category_display") if isinstance(category_selection_plan, dict) else None,
        "/".join(category_selection_plan.get("category_path") or []) if isinstance(category_selection_plan, dict) else None,
    ):
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def maybe_resolve_bilibili_tid(request_payload: dict[str, Any]) -> str:
    category = request_payload.get("category")
    category_selection_plan = (
        (request_payload.get("platform_specific_overrides") or {}).get("category_selection_plan")
        if isinstance(request_payload.get("platform_specific_overrides"), dict)
        else None
    )
    primary_candidates: list[str] = []
    fallback_candidates: list[str] = []
    for candidate in (
        category,
        category_selection_plan.get("category_display") if isinstance(category_selection_plan, dict) else None,
        "/".join(category_selection_plan.get("category_path") or []) if isinstance(category_selection_plan, dict) else None,
    ):
        text = str(candidate or "").strip()
        if text and text not in primary_candidates:
            primary_candidates.append(text)
    legacy_fallback = (
        category_selection_plan.get("legacy_api_fallback")
        if isinstance(category_selection_plan, dict)
        else None
    )
    legacy_text = str(legacy_fallback or "").strip()
    if legacy_text:
        fallback_candidates.append(legacy_text)
    for candidate in primary_candidates:
        if candidate.isdigit():
            return candidate
        resolved = _lookup_bilibili_tid_alias(candidate)
        if resolved is not None:
            return str(resolved)
    for candidate in fallback_candidates:
        if candidate.isdigit():
            return candidate
        resolved = _lookup_bilibili_tid_alias(candidate)
        if resolved is not None:
            return str(resolved)
    return ""


def resolve_bilibili_tid(request_payload: dict[str, Any]) -> str:
    resolved = maybe_resolve_bilibili_tid(request_payload)
    if resolved:
        return resolved
    category = request_payload.get("category")
    category_selection_plan = (
        (request_payload.get("platform_specific_overrides") or {}).get("category_selection_plan")
        if isinstance(request_payload.get("platform_specific_overrides"), dict)
        else None
    )
    raise ValueError(
        "Bilibili 通过 social-auto-upload 发布时需要可解析的 tid 分类；"
        f"当前 category={category!r}，category_selection_plan={category_selection_plan!r}"
    )


def _lookup_bilibili_tid_alias(category: str) -> int | None:
    normalized = _normalize_bilibili_category_key(category)
    if not normalized:
        return None
    if normalized in BILIBILI_TID_ALIASES:
        return BILIBILI_TID_ALIASES[normalized]
    if "/" in normalized:
        tail = normalized.split("/")[-1]
        if tail in BILIBILI_TID_ALIASES:
            return BILIBILI_TID_ALIASES[tail]
    return None


def _normalize_bilibili_category_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    normalized = (
        text.replace("·", "")
        .replace(" ", "")
        .replace("_", "")
        .replace("（", "(")
        .replace("）", ")")
    )
    return normalized


BILIBILI_TID_ALIASES = _build_bilibili_tid_aliases()


async def run_social_auto_upload_command(
    command: list[str],
    *,
    root: str,
    timeout_sec: int,
) -> SocialAutoUploadCommandResult:
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=str(Path(root).resolve()),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=max(1, int(timeout_sec)))
    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()
        return SocialAutoUploadCommandResult(
            command=command,
            returncode=124,
            stdout=(stdout or b"").decode("utf-8", errors="replace"),
            stderr=((stderr or b"").decode("utf-8", errors="replace") or "social-auto-upload command timed out"),
        )
    return SocialAutoUploadCommandResult(
        command=command,
        returncode=int(process.returncode or 0),
        stdout=(stdout or b"").decode("utf-8", errors="replace"),
        stderr=(stderr or b"").decode("utf-8", errors="replace"),
    )


def _normalize_schedule_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = _parse_datetime(text)
    if parsed is None:
        return text
    return parsed.strftime("%Y-%m-%d %H:%M")


def _parse_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None
