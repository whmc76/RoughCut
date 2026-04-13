from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem, TranscriptSegment


@dataclass
class SubtitleEntry:
    index: int
    start: float
    end: float
    text_raw: str
    text_norm: str
    words: tuple[dict, ...] = ()


@dataclass(frozen=True)
class BoundaryDecision:
    left_index: int
    right_index: int
    decision: str
    score: float
    reason_tags: tuple[str, ...] = ()
    source: str = "rule"
    left_text: str = ""
    right_text: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "left_index": self.left_index,
            "right_index": self.right_index,
            "decision": self.decision,
            "score": round(float(self.score), 3),
            "reason_tags": list(self.reason_tags),
            "source": self.source,
            "left_text": self.left_text,
            "right_text": self.right_text,
        }


@dataclass
class SubtitleSegmentationAnalysis:
    entry_count: int
    fragment_start_count: int
    fragment_end_count: int
    protected_term_split_count: int
    suspicious_boundary_count: int
    consecutive_fragment_window_count: int
    low_confidence_window_count: int
    boundary_decisions: tuple[BoundaryDecision, ...] = ()
    low_confidence_windows: tuple[dict[str, object], ...] = ()
    provider_word_segment_count: int = 0
    synthetic_word_segment_count: int = 0
    untrusted_word_segment_count: int = 0
    text_only_segment_count: int = 0
    global_word_segmentation_used: bool = False

    def as_dict(self) -> dict[str, object]:
        suspicious = [decision.as_dict() for decision in self.boundary_decisions if decision.decision != "natural_break"]
        return {
            "entry_count": self.entry_count,
            "fragment_start_count": self.fragment_start_count,
            "fragment_end_count": self.fragment_end_count,
            "protected_term_split_count": self.protected_term_split_count,
            "suspicious_boundary_count": self.suspicious_boundary_count,
            "consecutive_fragment_window_count": self.consecutive_fragment_window_count,
            "low_confidence_window_count": self.low_confidence_window_count,
            "provider_word_segment_count": self.provider_word_segment_count,
            "synthetic_word_segment_count": self.synthetic_word_segment_count,
            "untrusted_word_segment_count": self.untrusted_word_segment_count,
            "text_only_segment_count": self.text_only_segment_count,
            "global_word_segmentation_used": self.global_word_segmentation_used,
            "sample_suspicious_boundaries": suspicious[:12],
            "sample_low_confidence_windows": list(self.low_confidence_windows[:8]),
        }


@dataclass
class SubtitleSegmentationResult:
    entries: list[SubtitleEntry]
    analysis: SubtitleSegmentationAnalysis


def score_subtitle_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> float:
    return _score_entry_sequence(entries, max_chars=max_chars, max_duration=max_duration)


def generate_subtitle_window_candidates(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
    top_k: int = 4,
) -> list[list[SubtitleEntry]]:
    return _search_fragment_window_segmentations(
        entries,
        max_chars=max_chars,
        max_duration=max_duration,
        top_k=top_k,
    )


def _tokenize_entry_text_for_resegmentation(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return []
    return [token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|.", compact) if token.strip()]


def _window_words_for_resegmentation(
    entries: list[SubtitleEntry],
    *,
    use_text_fallback_only: bool = False,
) -> list[dict[str, float | str]]:
    window_words: list[dict[str, float | str]] = []
    for entry in list(entries or []):
        entry_words = tuple(entry.words or ())
        if entry_words and not use_text_fallback_only:
            for word in entry_words:
                text = str(word.get("word") or "").strip()
                if not text:
                    continue
                window_words.append(
                    {
                        "word": text,
                        "start": float(word.get("start") or 0.0),
                        "end": float(word.get("end") or 0.0),
                    }
                )
            continue
        fallback_tokens = _tokenize_entry_text_for_resegmentation(entry.text_raw)
        if not fallback_tokens:
            continue
        duration = max(float(entry.end) - float(entry.start), 0.001)
        token_span = duration / max(len(fallback_tokens), 1)
        for token_index, token in enumerate(fallback_tokens):
            token_start = float(entry.start) + token_index * token_span
            token_end = min(float(entry.end), token_start + token_span)
            window_words.append(
                {
                    "word": token,
                    "start": token_start,
                    "end": token_end,
                }
                )
    return window_words


def _window_word_streams_for_resegmentation(entries: list[SubtitleEntry]) -> list[list[dict[str, float | str]]]:
    streams: list[list[dict[str, float | str]]] = []
    seen: set[tuple[str, ...]] = set()
    for use_text_fallback_only in (False, True):
        stream = _window_words_for_resegmentation(entries, use_text_fallback_only=use_text_fallback_only)
        if len(stream) < 2:
            continue
        key = tuple(str(item.get("word") or "") for item in stream)
        if not key or key in seen:
            continue
        seen.add(key)
        streams.append(stream)
    return streams


def resegment_subtitle_window_from_cuts(
    entries: list[SubtitleEntry],
    *,
    cut_after_word_indices: list[int],
) -> list[SubtitleEntry] | None:
    window_entries = list(entries or [])
    if not window_entries:
        return None
    window_words = _window_words_for_resegmentation(window_entries)
    if len(window_words) < 2:
        return None

    normalized_cuts: list[int] = []
    last_allowed_index = len(window_words) - 2
    for raw_cut in cut_after_word_indices:
        try:
            cut = int(raw_cut)
        except (TypeError, ValueError):
            return None
        if cut < 0 or cut > last_allowed_index:
            return None
        if normalized_cuts and cut <= normalized_cuts[-1]:
            return None
        normalized_cuts.append(cut)

    ranges: list[tuple[int, int]] = []
    start_index = 0
    for cut in normalized_cuts:
        ranges.append((start_index, cut + 1))
        start_index = cut + 1
    ranges.append((start_index, len(window_words)))

    rebuilt: list[SubtitleEntry] = []
    for index, (start_index, end_index) in enumerate(ranges):
        candidate_words = window_words[start_index:end_index]
        if not candidate_words:
            return None
        text = _words_to_text(candidate_words)
        if not text:
            return None
        rebuilt.append(
            _make_subtitle_entry(
                index,
                float(candidate_words[0]["start"]),
                float(candidate_words[-1]["end"]),
                text,
                words=candidate_words,
            )
        )
    return _cleanup_subtitle_entries(rebuilt)


_ER_FILLER_RE = re.compile(r"呃+")
_CHINESE_DIGIT_VALUES = {
    "零": 0,
    "〇": 0,
    "幺": 1,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNIT_VALUES = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}
_DISPLAY_ORDINAL_UNITS = (
    "分钟",
    "小时",
    "句",
    "步",
    "代",
    "次",
    "档",
    "页",
    "期",
    "集",
    "层",
    "排",
    "条",
    "款",
    "件",
    "章",
    "轮",
    "名",
    "天",
    "年",
    "月",
    "秒",
    "个",
)
_DISPLAY_QUANTITY_UNITS = (
    "分钟",
    "小时",
    "毫米",
    "厘米",
    "英寸",
    "代",
    "档",
    "个",
    "倍",
    "号",
    "日",
    "次",
    "年",
    "月",
    "天",
    "秒",
    "寸",
    "项",
    "种",
    "款",
    "把",
    "条",
    "层",
    "米",
    "毫升",
    "升",
    "克",
    "千克",
    "公斤",
    "元",
    "块",
    "颗",
    "排",
    "面",
    "页",
    "张",
    "集",
    "级",
    "斤",
    "瓦",
    "伏",
    "安",
)
_DISPLAY_NUM_TOKEN = r"[零〇幺一二两三四五六七八九十百千万\d]+"
_DISPLAY_ORDINAL_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_ORDINAL_UNITS), key=len, reverse=True)
)
_DISPLAY_QUANTITY_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_QUANTITY_UNITS), key=len, reverse=True)
)
_PERCENT_NUMBER_RE = re.compile(rf"百分之(?P<number>{_DISPLAY_NUM_TOKEN})")
_ORDINAL_NUMBER_RE = re.compile(
    rf"第(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_ORDINAL_UNIT_PATTERN})"
)
_QUANTITY_NUMBER_RE = re.compile(
    rf"(?<![第A-Za-z0-9])(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_QUANTITY_UNIT_PATTERN})"
)
_TIME_WITH_MINUTE_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上)?)"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点(?P<minute>{_DISPLAY_NUM_TOKEN})(?:分|分钟)?"
)
_TIME_HALF_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上)?)"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点半"
)
_TIME_HOUR_ONLY_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上))"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点(?=(?:整|钟|左右|前|后|开始|开播|上线|下班|出发|到|[，,。！？!?；;]|$))"
)
_COLLOQUIAL_PRICE_RE = re.compile(
    rf"(?P<integer>{_DISPLAY_NUM_TOKEN})块(?P<fraction>{_DISPLAY_NUM_TOKEN})(?![\u4e00-\u9fffA-Za-z0-9])"
)
_ALPHA_NUMERIC_COMBO_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<prefix>[A-Za-z]{{1,8}})(?P<number>{_DISPLAY_NUM_TOKEN})(?=[\u4e00-\u9fff]|$)"
)
_REPEATED_MODEL_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<prefix>[A-Za-z]{1,8})(?P<number>\d{2,4})(?P=number)(?=[\u4e00-\u9fff])"
)
_SPACED_MODEL_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<letters>(?:[A-Za-z]\s+){{1,7}}[A-Za-z])\s+"
    rf"(?P<number>{_DISPLAY_NUM_TOKEN})(?:\s+(?P<suffix>[A-Za-z]+))?(?![A-Za-z0-9])"
)
_NATURAL_SINGLE_UNITS = {"个", "次", "年", "月", "天", "小时", "分钟", "秒"}
_VAGUE_NUMBER_TOKENS = {
    "一两",
    "一二",
    "二三",
    "两三",
    "三四",
    "四五",
    "五六",
    "六七",
    "七八",
    "八九",
}
_INFO_COUNT_NOUN_PREFIXES = (
    "档位",
    "接口",
    "版本",
    "型号",
    "规格",
    "参数",
    "模式",
    "方案",
    "步骤",
    "配色",
    "功能",
    "层",
    "页",
    "面",
    "代",
    "代目",
    "级",
    "级别",
    "平台",
    "模块",
    "尺寸",
    "机位",
    "镜头",
    "孔位",
    "按钮",
    "刀型",
    "钢材",
    "容量",
    "续航",
)
_SUBTITLE_FILLER_PREFIX_TOKENS = (
    "呃",
    "嗯",
    "啊",
    "吧",
    "呢",
    "吗",
    "嘛",
    "呀",
    "哈",
    "哦",
    "诶",
    "欸",
    "哎",
    "那个",
    "这个",
    "就是",
    "然后",
    "其实",
    "那么",
    "对吧",
    "好吧",
    "这样子",
    "所以说",
    "总的来说",
)
_SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS = {
    "那个",
    "这个",
    "就是",
    "然后",
    "其实",
    "那么",
    "对吧",
    "好吧",
    "这样子",
    "所以说",
    "总的来说",
}
_INLINE_FILLER_RE = re.compile(r"(?:呃|嗯|诶|欸|哎|哈|哦)+")
_INLINE_PARTICLE_RE = re.compile(r"(?<=[\u4e00-\u9fffA-Za-z0-9])(?:啊|吧|呢|吗|嘛|呀)(?=[\u4e00-\u9fffA-Za-z0-9])")
_TRAILING_FILLER_RE = re.compile(r"(?:呢|吗|嘛|呀|哈|哦|诶|欸|哎)+$")
_TRAILING_KEEPABLE_PARTICLE_RE = re.compile(r"(?:啊+|吧+)$")
_TERMINAL_PUNCTUATION = "。！？!?"
_HARD_BREAK_CHARS = "。！？!?；;"
_SOFT_BREAK_CHARS = "，,、：:"
_BOUNDARY_LEADING_PARTICLES = ("呃", "嗯", "啊", "吧", "呢", "吗", "嘛", "呀", "哈", "哦", "诶", "欸", "哎")
_PARTICLE_LED_RESTART_PREFIXES = (
    "这期",
    "这个",
    "我们",
    "我先",
    "我再",
    "你看",
    "大家",
    "接下来",
    "下面",
    "现在",
    "今天",
    "那我们",
    "然后我们",
)
_NO_SPLIT_ENDINGS = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "是",
    "然后", "所以", "但是", "而且", "并且", "会", "想", "要", "能",
)
_NO_SPLIT_PREFIXES = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "地", "得", "是",
    "起来", "下来", "上来", "下去", "一下", "喜欢",
)
_GOOD_BREAK_PREFIXES = (
    "但是", "不过", "所以", "然后", "而且", "并且", "如果", "因为", "另外", "同时",
)
_BOUNDARY_PROTECTED_TERMS = (
    "螺丝",
    "螺丝刀",
    "贴片",
    "电镀",
    "渐变",
    "阳极",
    "图纸",
    "美中不足",
    "极致",
    "华丽",
    "极致华丽",
    "EDC",
    "手电",
    "FAS",
    "彩雕",
    "深雕",
    "雾面",
    "拉丝",
    "镜面",
    "刀刃",
    "实用性",
)
_ATTACHED_FRAGMENT_PREFIXES = (
    "的",
    "了",
    "得",
    "地",
    "着",
    "过",
    "吗",
    "吧",
    "呢",
    "嘛",
    "啊",
    "呀",
    "哦",
    "哇",
    "啦",
    "来",
    "去",
    "起来",
    "下来",
    "上来",
    "下去",
    "一下",
)
_SOFT_FRAGMENTARY_ENDINGS = (
    "这个",
    "那个",
    "这边",
    "那边",
    "大家",
    "我们",
    "你们",
    "相当",
    "一个",
    "一直",
    "之前",
    "之后",
)
_SOFT_ATTACHED_FRAGMENT_PREFIXES = (
    "要",
    "觉",
    "冷",
    "人",
    "边",
    "备",
    "名",
    "隔",
    "看",
    "们",
    "品",
    "常",
    "么",
    "以",
)
_BOUNDARY_COMPOUND_SPLITS: tuple[tuple[str, str], ...] = (
    ("需", "要"),
    ("那", "种"),
    ("这", "个"),
    ("那", "个"),
    ("可", "以"),
    ("因", "为"),
    ("另", "外"),
    ("之", "前"),
    ("应", "该"),
    ("没", "啥"),
    ("我", "们"),
    ("你", "们"),
    ("它", "们"),
    ("或", "者"),
    ("制", "冷"),
    ("产", "品"),
    ("顾", "名"),
    ("建", "议"),
    ("介", "绍"),
    ("一", "下"),
    ("手", "电"),
    ("内", "容"),
    ("东", "西"),
    ("随", "身"),
    ("功", "能"),
    ("流", "明"),
    ("亮", "度"),
    ("日", "用"),
    ("小", "兄弟"),
    ("兄", "弟"),
    ("耐", "克尔"),
    ("耐克", "尔"),
    ("对", "比"),
    ("角", "度"),
    ("口", "香糖"),
    ("一", "颗"),
    ("一", "定"),
    ("没", "有"),
    ("压", "胶"),
    ("大", "网兜"),
    ("大", "家"),
    ("K", "片"),
    ("我", "自己"),
    ("这", "边"),
)

_SPLIT_MEASURE_LEFT_RE = re.compile(
    rf"(?:{_DISPLAY_NUM_TOKEN}|这|那|每|某|另|前|后|首|第|几)$"
)
_SPLIT_MEASURE_RIGHT_RE = re.compile(
    r"^(?:个|只|把|条|点|件|款|袋|盒|包|支|瓶|片|颗|次|种|位|类|份|套|台|张|米|寸|段|步|层|页|代|号)"
)
_UNCLOSED_NOMINAL_TAIL_RE = re.compile(
    r"(?:"
    r"第(?:[0-9]+|[一二两三四五六七八九十])个|"
    r"(?:[0-9]+|[一二两三四五六七八九十])个|"
    r"(?:这|那)(?:个|种|类|边)|"
    r"(?:每|某)个|"
    r"另一个|前一个|后一个|最后一个|"
    r"的(?:这|那)?(?:个|种|类)?"
    r")$"
)
_NOMINAL_HEAD_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9]{1,8}")
_MAX_SEMANTIC_BRIDGE_GAP_SEC = 3.2
_MAX_SEMANTIC_TRANSFER_WORDS = 4
_MAX_SEMANTIC_TRANSFER_CHARS = 8
_MAX_SEMANTIC_BRIDGE_DURATION_SEC = 8.6
_SYNTHETIC_WORD_SOURCES = {"synthetic", "segment_only", "provider_missing", "roughcut_synthesized"}
_SINGLE_CHAR_CONTINUATION_START_RE = re.compile(
    r"^(?P<head>[\u4e00-\u9fff])(?P<rest>也|都|就|是|有|会|要|在|来|去|从|跟|把|被|里|上|下)"
)
_SINGLE_CHAR_FREE_STARTERS = {"我", "你", "他", "她", "它", "这", "那", "可", "但", "先", "再"}


def _make_subtitle_entry(
    index: int,
    start: float,
    end: float,
    text: str,
    *,
    words: list[dict] | tuple[dict, ...] | None = None,
) -> SubtitleEntry:
    raw_text = str(text or "").strip()
    return SubtitleEntry(
        index=index,
        start=float(start),
        end=float(end),
        text_raw=raw_text,
        text_norm=normalize_text(raw_text),
        words=tuple(words or ()),
    )


def _reindex_subtitle_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    return [
        SubtitleEntry(
            index=index,
            start=item.start,
            end=item.end,
            text_raw=item.text_raw,
            text_norm=item.text_norm,
            words=tuple(item.words or ()),
        )
        for index, item in enumerate(entries)
    ]


def _extract_word_alignment_source(raw_word: dict) -> str:
    if not isinstance(raw_word, dict):
        return ""
    alignment = raw_word.get("alignment")
    if isinstance(alignment, dict):
        roughcut = alignment.get("_roughcut")
        if isinstance(roughcut, dict):
            source = str(roughcut.get("source") or "").strip().lower()
            if source:
                return source
        source = str(alignment.get("source") or "").strip().lower()
        if source:
            return source
    raw_payload = raw_word.get("raw_payload")
    if isinstance(raw_payload, dict):
        for key in ("source", "_roughcut_source"):
            source = str(raw_payload.get(key) or "").strip().lower()
            if source:
                return source
    return ""


def _build_text_fallback_words(text: str, *, start: float, end: float) -> list[dict]:
    tokens = _tokenize_entry_text_for_resegmentation(text)
    if not tokens:
        return []
    duration = max(float(end) - float(start), 0.001)
    token_span = duration / max(len(tokens), 1)
    rebuilt: list[dict] = []
    for token_index, token in enumerate(tokens):
        token_start = float(start) + token_index * token_span
        token_end = min(float(end), token_start + token_span)
        rebuilt.append(
            {
                "word": token,
                "start": token_start,
                "end": token_end,
                "alignment": {"source": "postprocess_text_fallback"},
            }
        )
    return rebuilt


def _words_are_usable_for_segmentation(text: str, words: list[dict]) -> bool:
    cleaned_words = [word for word in list(words or []) if isinstance(word, dict) and str(word.get("word") or "").strip()]
    if len(cleaned_words) < 2:
        return False
    if any(_extract_word_alignment_source(word) in _SYNTHETIC_WORD_SOURCES for word in cleaned_words):
        return False

    compact_text = re.sub(r"[\s，。！？!?；;：:,、（）()【】\[\]{}\"'《》<>]+", "", str(text or "").strip())
    compact_words = re.sub(
        r"[\s，。！？!?；;：:,、（）()【】\[\]{}\"'《》<>]+",
        "",
        "".join(str(word.get("word") or "").strip() for word in cleaned_words),
    )
    if compact_text and compact_words:
        coverage = difflib.SequenceMatcher(a=compact_words, b=compact_text).ratio()
        if coverage < 0.86:
            return False
    return True


def _words_for_segmentation(seg: TranscriptSegment) -> list[dict]:
    raw_words = list(getattr(seg, "words_json", []) or [])
    if not raw_words:
        return []
    if _words_are_usable_for_segmentation(getattr(seg, "text", ""), raw_words):
        normalized: list[dict] = []
        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                continue
            word_text = re.sub(r"\s+", "", str(raw_word.get("word", "")))
            if not word_text:
                continue
            start = float(raw_word.get("start") or 0.0)
            end = max(start, float(raw_word.get("end") or start))
            normalized.append(
                {
                    **dict(raw_word),
                    "word": word_text,
                    "start": start,
                    "end": end,
                }
            )
        return normalized
    return _build_text_fallback_words(
        getattr(seg, "text", ""),
        start=float(getattr(seg, "start_time", 0.0) or 0.0),
        end=float(getattr(seg, "end_time", 0.0) or 0.0),
    )


def _collect_segmentation_input_stats(segments: list[TranscriptSegment]) -> dict[str, int]:
    stats = {
        "provider_word_segment_count": 0,
        "synthetic_word_segment_count": 0,
        "untrusted_word_segment_count": 0,
        "text_only_segment_count": 0,
    }
    for seg in list(segments or []):
        raw_words = list(getattr(seg, "words_json", []) or [])
        if not raw_words:
            stats["text_only_segment_count"] += 1
            continue
        if _words_are_usable_for_segmentation(getattr(seg, "text", ""), raw_words):
            stats["provider_word_segment_count"] += 1
            continue
        if any(_extract_word_alignment_source(word) in _SYNTHETIC_WORD_SOURCES for word in raw_words if isinstance(word, dict)):
            stats["synthetic_word_segment_count"] += 1
            continue
        stats["untrusted_word_segment_count"] += 1
    return stats


def normalize_text(text: str) -> str:
    """Apply punctuation cleanup and whitespace normalization."""
    text = normalize_display_text(text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。.]{2,}", "。", text)
    text = re.sub(r"[，,]+[。.!！？]+", "。", text)
    text = re.sub(r"[。.!！？]+[，,]+", "。", text)
    if len(text) > 5 and text and text[-1] not in "。！？，、…":
        text += "。"
    return text


def normalize_display_text(text: str, *, cleanup_fillers: bool = True) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    result = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", result)
    if cleanup_fillers:
        result = cleanup_subtitle_fillers(result)
    result = _normalize_display_numbers(result)
    result = apply_subtitle_clause_spacing(result)
    result = re.sub(r"\s+([，,。.!！？；;：:])", r"\1", result)
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[。.]{2,}", "。", result)
    result = re.sub(r"[，,]+([。.!！？])", r"\1", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip("，,")


def normalize_display_numbers(text: str) -> str:
    """Normalize numeric expressions in subtitle text without touching spacing/punctuation."""
    return _normalize_display_numbers(str(text or "").strip())


def cleanup_subtitle_fillers(text: str) -> str:
    result = str(text or "").strip()
    if not result:
        return result

    pieces = [piece for piece in re.split(r"([，,。！？!?；;])", result) if piece != ""]
    cleaned: list[str] = []
    for index, piece in enumerate(pieces):
        if piece in "，,。！？!?；;":
            if cleaned and cleaned[-1] in "，,；;" and piece in _TERMINAL_PUNCTUATION:
                cleaned[-1] = piece
                continue
            if cleaned and cleaned[-1] not in "，,。！？!?；;":
                cleaned.append(piece)
            continue

        clause = piece.strip()
        if not clause:
            continue
        clause = _strip_subtitle_filler_prefixes(clause)
        clause = _ER_FILLER_RE.sub("", clause)
        clause = _INLINE_FILLER_RE.sub("", clause)
        clause = _INLINE_PARTICLE_RE.sub("", clause)
        clause = _strip_subtitle_filler_suffixes(
            clause,
            keep_sentence_final_particle=_next_piece_is_terminal_punctuation(pieces, index),
        )
        clause = _strip_subtitle_filler_prefixes(clause)
        clause = clause.strip("，, ")
        if not clause or clause in _SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS:
            continue
        cleaned.append(clause)

    collapsed = "".join(cleaned).strip("，,")
    collapsed = re.sub(r"([，,；;]){2,}", lambda match: match.group(0)[0], collapsed)
    collapsed = re.sub(r"[，,]+([。！？!?；;])", r"\1", collapsed)
    return collapsed


def apply_subtitle_clause_spacing(text: str) -> str:
    result = str(text or "").strip()
    if not result or len(result.replace(" ", "")) <= 10:
        return result
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    if " " not in result and len(result) >= 14:
        for token in _GOOD_BREAK_PREFIXES:
            result = re.sub(rf"(?<!^)(?<!\s)(?={re.escape(token)})", " ", result)
    return re.sub(r"\s{2,}", " ", result).strip()


def _normalize_display_numbers(text: str) -> str:
    if not text:
        return text

    result = _normalize_spaced_model_tokens(text)
    result = _normalize_colloquial_price_tokens(result)
    result = _normalize_alpha_numeric_tokens(result)
    result = _collapse_repeated_model_number_tokens(result)
    result = _normalize_time_tokens(result)

    def replace_percent(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        return f"{number}%" if number else match.group(0)

    def replace_ordinal(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        unit = match.group("unit")
        return f"第{number}{unit}" if number else match.group(0)

    def replace_quantity(match: re.Match[str]) -> str:
        raw_number = match.group("number")
        number = _normalize_numeric_token(match.group("number"))
        unit = match.group("unit")
        if _should_preserve_natural_quantity(
            raw_number,
            unit,
            match.string[match.end():match.end() + 6],
        ):
            return match.group(0)
        return f"{number}{unit}" if number else match.group(0)

    result = _PERCENT_NUMBER_RE.sub(replace_percent, result)
    result = _ORDINAL_NUMBER_RE.sub(replace_ordinal, result)
    result = _QUANTITY_NUMBER_RE.sub(replace_quantity, result)
    return result


def _normalize_colloquial_price_tokens(text: str) -> str:
    def replace_price(match: re.Match[str]) -> str:
        integer = _normalize_numeric_token(match.group("integer"))
        fraction = _normalize_numeric_token(match.group("fraction"))
        if not integer or not fraction:
            return match.group(0)
        return f"{integer}块{fraction}"

    return _COLLOQUIAL_PRICE_RE.sub(replace_price, text)


def _normalize_spaced_model_tokens(text: str) -> str:
    def replace_model(match: re.Match[str]) -> str:
        letters = re.sub(r"\s+", "", str(match.group("letters") or "")).upper()
        number = _normalize_numeric_token(match.group("number"))
        suffix = re.sub(r"\s+", "", str(match.group("suffix") or ""))
        if not letters or not number:
            return match.group(0)
        suffix_text = suffix.lower() if suffix else ""
        return f"{letters}-{number}{suffix_text}"

    return _SPACED_MODEL_TOKEN_RE.sub(replace_model, text)


def _normalize_alpha_numeric_tokens(text: str) -> str:
    def replace_alpha_numeric(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "").upper()
        number = _normalize_numeric_token(match.group("number"))
        return f"{prefix}{number}" if number else match.group(0)

    return _ALPHA_NUMERIC_COMBO_RE.sub(replace_alpha_numeric, text)


def _collapse_repeated_model_number_tokens(text: str) -> str:
    return _REPEATED_MODEL_NUMBER_RE.sub(
        lambda match: f"{match.group('prefix').upper()}{match.group('number')}",
        text,
    )


def _normalize_time_tokens(text: str) -> str:
    def replace_time_with_minute(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        minute = _normalize_numeric_token(match.group("minute"))
        if not hour or not minute:
            return match.group(0)
        return f"{prefix}{hour}点{minute}"

    def replace_time_half(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        return f"{prefix}{hour}点30" if hour else match.group(0)

    def replace_time_hour_only(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        return f"{prefix}{hour}点" if hour else match.group(0)

    result = _TIME_HALF_RE.sub(replace_time_half, text)
    result = _TIME_WITH_MINUTE_RE.sub(replace_time_with_minute, result)
    result = _TIME_HOUR_ONLY_RE.sub(replace_time_hour_only, result)
    return result


def _should_preserve_natural_quantity(number_token: str, unit: str, tail_text: str) -> bool:
    normalized_token = str(number_token or "").strip()
    if not normalized_token:
        return False
    if normalized_token in _VAGUE_NUMBER_TOKENS:
        return True
    if normalized_token == "一" and unit in _NATURAL_SINGLE_UNITS:
        if unit == "个" and _starts_with_info_count_noun(tail_text):
            return False
        return True
    return False


def _starts_with_info_count_noun(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    return any(candidate.startswith(prefix) for prefix in _INFO_COUNT_NOUN_PREFIXES)


def _normalize_numeric_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return value
    if value.isdigit():
        return value
    if re.fullmatch(r"[零〇幺一二两三四五六七八九]+", value):
        return "".join(str(_CHINESE_DIGIT_VALUES[char]) for char in value)
    parsed = _parse_chinese_number(value)
    return str(parsed) if parsed is not None else value


def _parse_chinese_number(token: str) -> int | None:
    if not token:
        return None
    total = 0
    section = 0
    number = 0
    saw_token = False
    for char in token:
        if char.isdigit():
            number = number * 10 + int(char)
            saw_token = True
            continue
        if char in _CHINESE_DIGIT_VALUES:
            number = _CHINESE_DIGIT_VALUES[char]
            saw_token = True
            continue
        unit = _CHINESE_UNIT_VALUES.get(char)
        if unit is None:
            return None
        saw_token = True
        if unit == 10000:
            section = (section + (number or 1)) * unit
            total += section
            section = 0
            number = 0
            continue
        section += (number or 1) * unit
        number = 0
    if not saw_token:
        return None
    return total + section + number


def _strip_subtitle_filler_prefixes(text: str) -> str:
    result = str(text or "").strip()
    changed = True
    while result and changed:
        changed = False
        result = result.lstrip("，, ")
        for token in _SUBTITLE_FILLER_PREFIX_TOKENS:
            if result.startswith(token) and len(result) > len(token):
                result = result[len(token):].lstrip("，, ")
                changed = True
                break
    return result


def _strip_subtitle_filler_suffixes(text: str, *, keep_sentence_final_particle: bool) -> str:
    result = str(text or "").strip().rstrip("，, ")
    if not result:
        return result

    while True:
        changed = False
        for token in (*_SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS, "呢", "吗", "嘛", "呀", "哈", "哦", "诶", "欸", "哎"):
            if result.endswith(token):
                result = result[:-len(token)].rstrip("，, ")
                changed = True
                break
        if not changed:
            break

    result = _TRAILING_FILLER_RE.sub("", result).rstrip("，, ")
    if keep_sentence_final_particle:
        result = _TRAILING_KEEPABLE_PARTICLE_RE.sub(lambda match: match.group(0)[-1], result)
    else:
        result = _TRAILING_KEEPABLE_PARTICLE_RE.sub("", result).rstrip("，, ")
    return result


def _next_piece_is_terminal_punctuation(pieces: list[str], index: int) -> bool:
    for next_index in range(index + 1, len(pieces)):
        next_piece = pieces[next_index]
        if not next_piece.strip():
            continue
        return next_piece in _TERMINAL_PUNCTUATION
    return True


def split_into_subtitles(
    segments: list[TranscriptSegment],
    *,
    max_chars: int = 30,
    max_duration: float = 5.0,
) -> list[SubtitleEntry]:
    return segment_subtitles(
        segments,
        max_chars=max_chars,
        max_duration=max_duration,
    ).entries


def segment_subtitles(
    segments: list[TranscriptSegment],
    *,
    max_chars: int = 30,
    max_duration: float = 5.0,
) -> SubtitleSegmentationResult:
    """
    Split transcript segments into subtitle display units.
    Each subtitle has at most max_chars characters and max_duration seconds.
    """
    input_stats = _collect_segmentation_input_stats(segments)
    global_word_segmentation_used = _can_use_global_word_segmentation(segments)
    if global_word_segmentation_used:
        entries = _segment_subtitles_from_global_words(segments, max_chars=max_chars, max_duration=max_duration)
        resolved = _resolve_subtitle_entry_sequence(
            entries,
            max_chars=max_chars,
            max_duration=max_duration,
            allow_window_refine=True,
        )
        if resolved:
            analysis = analyze_subtitle_segmentation(resolved)
            analysis.provider_word_segment_count = int(input_stats["provider_word_segment_count"])
            analysis.synthetic_word_segment_count = int(input_stats["synthetic_word_segment_count"])
            analysis.untrusted_word_segment_count = int(input_stats["untrusted_word_segment_count"])
            analysis.text_only_segment_count = int(input_stats["text_only_segment_count"])
            analysis.global_word_segmentation_used = True
            return SubtitleSegmentationResult(
                entries=resolved,
                analysis=analysis,
            )

    subtitles: list[SubtitleEntry] = []
    idx = 0

    for seg in segments:
        text = re.sub(r"\s+", "", seg.text.strip())
        if not text:
            continue

        words = _words_for_segmentation(seg)

        # If we have word-level timing, split by words
        if words:
            subtitles.extend(_split_with_words(text, words, idx, max_chars, max_duration))
            idx += len(subtitles) - idx
        else:
            # Fall back to time-based splitting
            duration = seg.end_time - seg.start_time
            if len(text) <= max_chars and duration <= max_duration:
                subtitles.append(_make_subtitle_entry(idx, seg.start_time, seg.end_time, text))
                idx += 1
            else:
                chunks = _split_plain_text(text, max_chars=max_chars)
                time_per_char = duration / max(len(text), 1)
                char_offset = 0
                for chunk in chunks:
                    chunk_start = seg.start_time + char_offset * time_per_char
                    chunk_end = chunk_start + len(chunk) * time_per_char
                    subtitles.append(
                        _make_subtitle_entry(idx, chunk_start, min(chunk_end, seg.end_time), chunk)
                    )
                    char_offset += len(chunk)
                    idx += 1

    resolved = _resolve_subtitle_entry_sequence(
        subtitles,
        max_chars=max_chars,
        max_duration=max_duration,
        allow_window_refine=True,
    )
    analysis = analyze_subtitle_segmentation(resolved)
    analysis.provider_word_segment_count = int(input_stats["provider_word_segment_count"])
    analysis.synthetic_word_segment_count = int(input_stats["synthetic_word_segment_count"])
    analysis.untrusted_word_segment_count = int(input_stats["untrusted_word_segment_count"])
    analysis.text_only_segment_count = int(input_stats["text_only_segment_count"])
    analysis.global_word_segmentation_used = bool(global_word_segmentation_used)
    return SubtitleSegmentationResult(
        entries=resolved,
        analysis=analysis,
    )


def _can_use_global_word_segmentation(segments: list[TranscriptSegment]) -> bool:
    if len(segments) <= 1:
        return False
    non_empty_segments = 0
    total_words = 0
    for seg in segments:
        words = _words_for_segmentation(seg)
        if not words:
            return False
        total_words += len([item for item in words if str(item.get("word", "")).strip()])
        non_empty_segments += 1
    return non_empty_segments >= 2 and total_words >= 4


def _segment_subtitles_from_global_words(
    segments: list[TranscriptSegment],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    words = _flatten_segment_words(segments)
    return _segment_entries_from_words(words, max_chars=max_chars, max_duration=max_duration)


def _segment_entries_from_words(
    words: list[dict],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if len(words) <= 1:
        return []

    limit_cache: dict[int, int] = {}
    scores: list[float] = [float("-inf")] * (len(words) + 1)
    jumps: list[int] = [len(words)] * (len(words) + 1)
    scores[len(words)] = 0.0

    for start_index in range(len(words) - 1, -1, -1):
        end_limit = limit_cache.setdefault(
            start_index,
            _candidate_end_limit(words, start_index, max_chars=max_chars, max_duration=max_duration),
        )
        for end_index in range(start_index + 1, end_limit + 1):
            candidate = _build_word_candidate(
                words,
                start_index,
                end_index,
                max_chars=max_chars,
                max_duration=max_duration,
            )
            if candidate is None:
                continue
            total_score = candidate["score"] + scores[end_index]
            if total_score > scores[start_index]:
                scores[start_index] = total_score
                jumps[start_index] = end_index

    if scores[0] == float("-inf"):
        return []

    entries: list[SubtitleEntry] = []
    cursor = 0
    while cursor < len(words):
        next_cursor = jumps[cursor]
        if next_cursor <= cursor or next_cursor > len(words):
            break
        candidate_words = words[cursor:next_cursor]
        entries.append(
            _make_subtitle_entry(
                len(entries),
                float(candidate_words[0]["start"]),
                float(candidate_words[-1]["end"]),
                _words_to_text(candidate_words),
                words=candidate_words,
            )
        )
        cursor = next_cursor
    return entries


def _resolve_subtitle_entry_sequence(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
    allow_window_refine: bool,
) -> list[SubtitleEntry]:
    merged = _merge_continuation_entries(entries, max_chars=max_chars, max_duration=max_duration)
    rebalanced = _rebalance_semantic_boundaries(merged, max_chars=max_chars, max_duration=max_duration)
    resolved = _merge_continuation_entries(rebalanced, max_chars=max_chars, max_duration=max_duration)
    if allow_window_refine:
        resolved = _refine_low_confidence_windows(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_continuation_entries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _rebalance_semantic_boundaries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_continuation_entries(resolved, max_chars=max_chars, max_duration=max_duration)
    return _cleanup_subtitle_entries(resolved)


def analyze_subtitle_segmentation(entries: list[SubtitleEntry]) -> SubtitleSegmentationAnalysis:
    if not entries:
        return SubtitleSegmentationAnalysis(
            entry_count=0,
            fragment_start_count=0,
            fragment_end_count=0,
            protected_term_split_count=0,
            suspicious_boundary_count=0,
            consecutive_fragment_window_count=0,
            low_confidence_window_count=0,
            boundary_decisions=(),
            low_confidence_windows=(),
        )

    fragment_end_count = sum(1 for entry in entries if _is_incomplete_subtitle_text(entry.text_raw))
    boundary_decisions: list[BoundaryDecision] = []
    fragment_start_count = 0
    protected_term_split_count = 0
    suspicious_boundary_count = 0
    consecutive_fragment_window_count = 0
    inside_suspicious_window = False

    for left, right in zip(entries, entries[1:]):
        tags: list[str] = []
        score = _semantic_boundary_quality(left.text_raw, right.text_raw)
        if _starts_with_attached_fragment(right.text_raw):
            tags.append("attached_fragment_start")
            fragment_start_count += 1
        elif _starts_with_soft_attached_fragment(right.text_raw):
            tags.append("soft_fragment_start")
            fragment_start_count += 1
        if _looks_like_split_measure_phrase(left.text_raw, right.text_raw):
            tags.append("measure_phrase_split")
            fragment_start_count += 1
        if _is_incomplete_subtitle_text(left.text_raw):
            tags.append("incomplete_left")
        elif _looks_like_soft_fragmentary_tail(left.text_raw):
            tags.append("soft_incomplete_left")
        if _boundary_splits_protected_term(left.text_raw, right.text_raw):
            tags.append("protected_term_split")
            protected_term_split_count += 1
        if score <= -1.5:
            tags.append("low_boundary_score")
        if _is_low_confidence_boundary(left, right):
            suspicious_boundary_count += 1
            if not inside_suspicious_window:
                consecutive_fragment_window_count += 1
                inside_suspicious_window = True
        else:
            inside_suspicious_window = False
        boundary_decisions.append(
            BoundaryDecision(
                left_index=left.index,
                right_index=right.index,
                decision="natural_break" if not tags else "low_confidence_break",
                score=score,
                reason_tags=tuple(tags),
                left_text=left.text_raw,
                right_text=right.text_raw,
            )
        )

    low_confidence_windows = _collect_low_confidence_windows(entries)
    low_confidence_window_count = len(low_confidence_windows)
    return SubtitleSegmentationAnalysis(
        entry_count=len(entries),
        fragment_start_count=fragment_start_count,
        fragment_end_count=fragment_end_count,
        protected_term_split_count=protected_term_split_count,
        suspicious_boundary_count=suspicious_boundary_count,
        consecutive_fragment_window_count=consecutive_fragment_window_count,
        low_confidence_window_count=low_confidence_window_count,
        boundary_decisions=tuple(boundary_decisions),
        low_confidence_windows=tuple(
            _build_low_confidence_window_summary(entries, start, end)
            for start, end in low_confidence_windows
        ),
    )


def _flatten_segment_words(segments: list[TranscriptSegment]) -> list[dict]:
    flattened: list[dict] = []
    for segment_index, seg in enumerate(segments):
        for word_index, raw_word in enumerate(_words_for_segmentation(seg)):
            word_text = re.sub(r"\s+", "", str(raw_word.get("word", "")))
            if not word_text:
                continue
            start = float(raw_word.get("start") or 0.0)
            end = max(start, float(raw_word.get("end") or start))
            flattened.append(
                {
                    **dict(raw_word),
                    "word": word_text,
                    "start": start,
                    "end": end,
                    "segment_index": segment_index,
                    "word_index": word_index,
                }
            )
    return flattened


def _candidate_end_limit(words: list[dict], start_index: int, *, max_chars: int, max_duration: float) -> int:
    hard_chars = max_chars + 10
    hard_duration = _semantic_hold_duration_limit(
        text_length=max_chars + 8,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    total_chars = 0
    for end_index in range(start_index, len(words)):
        total_chars += len(str(words[end_index].get("word") or ""))
        duration = float(words[end_index]["end"]) - float(words[start_index]["start"])
        if total_chars > hard_chars or duration > hard_duration:
            return max(start_index + 1, end_index)
    return len(words)


def _build_word_candidate(
    words: list[dict],
    start_index: int,
    end_index: int,
    *,
    max_chars: int,
    max_duration: float,
) -> dict[str, float | int | str] | None:
    candidate_words = words[start_index:end_index]
    if not candidate_words:
        return None
    text = _words_to_text(candidate_words)
    if not text:
        return None

    start = float(candidate_words[0]["start"])
    end = float(candidate_words[-1]["end"])
    duration = max(0.0, end - start)
    if duration <= 0.0:
        return None

    next_preview = _preview_words_text(words[end_index:end_index + 4])
    previous_preview = _preview_words_text(words[max(0, start_index - 3):start_index])
    gap_after = max(0.0, float(words[end_index]["start"]) - end) if end_index < len(words) else 0.0
    max_internal_gap = 0.0
    for index in range(start_index + 1, end_index):
        internal_gap = float(words[index]["start"]) - float(words[index - 1]["end"])
        if internal_gap > max_internal_gap:
            max_internal_gap = internal_gap

    score = 0.0
    target_chars = min(max_chars, max(8, int(max_chars * 0.82)))
    score -= abs(len(text) - target_chars) * 1.2
    if len(text) <= max_chars:
        score += 6.0
    else:
        score -= (len(text) - max_chars) * 3.5

    if duration <= max_duration:
        score += 4.0
    else:
        score -= (duration - max_duration) * 4.0

    boundary_quality = _semantic_boundary_quality(text, next_preview) if next_preview else 4.0
    score += boundary_quality * 4.5
    if any(text.endswith(token) for token in _NO_SPLIT_ENDINGS) and next_preview:
        score -= 8.0
    if _starts_with_attached_fragment(next_preview):
        score -= 8.0
    if _starts_with_soft_attached_fragment(next_preview):
        score -= 4.0
    if _looks_like_soft_fragmentary_tail(text):
        score -= 4.0
    if _boundary_splits_compound_term(text, next_preview):
        score -= 10.0
    if _boundary_splits_protected_term(text, next_preview):
        score -= 12.0

    if gap_after >= 0.25:
        score += min(gap_after, 1.5) * (6.0 if boundary_quality >= 0 else -3.0)
    if max_internal_gap >= 0.45:
        score -= min(max_internal_gap, 1.5) * (5.0 if len(text) > max_chars else 3.0)
    if previous_preview and _starts_with_attached_fragment(text):
        score -= 10.0
    if re.match(r"^[，。！？、：；,.!?]", text):
        score -= 16.0

    return {"score": score, "start": start, "end": end, "text": text}


def _preview_words_text(words: list[dict]) -> str:
    preview = _words_to_text(words)
    return preview[:10]


def _split_with_words(
    text: str,
    words: list[dict],
    start_idx: int,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    current_words: list[dict] = []
    idx = start_idx

    for word in words:
        word_text = re.sub(r"\s+", "", str(word.get("word", "")))
        if not word_text:
            continue
        candidate_words = current_words + [word]
        candidate = _words_to_text(candidate_words)

        seg_start = current_words[0]["start"] if current_words else word["start"]
        seg_end = word["end"]
        duration = seg_end - seg_start

        if current_words and (len(candidate) > max_chars or duration > max_duration):
            split_at = _choose_word_split_index(candidate_words, max_chars=max_chars, max_duration=max_duration)
            left_words = candidate_words[:split_at]
            right_words = candidate_words[split_at:]
            left_text = _words_to_text(left_words)
            if not left_words or not left_text:
                left_words = current_words
                right_words = [word]
                left_text = _words_to_text(left_words)
            entries.append(
                _make_subtitle_entry(
                    idx,
                    left_words[0]["start"],
                    left_words[-1]["end"],
                    left_text,
                    words=left_words,
                )
            )
            idx += 1
            current_words = right_words
        else:
            current_words = candidate_words

    if current_words:
        current_text = _words_to_text(current_words)
        entries.append(
            _make_subtitle_entry(
                idx,
                current_words[0]["start"],
                current_words[-1]["end"],
                current_text,
                words=current_words,
            )
        )

    return _merge_continuation_entries(entries, max_chars=max_chars, max_duration=max_duration)


def _split_plain_text(text: str, *, max_chars: int) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return []
    chunks: list[str] = []
    remaining = compact
    while len(remaining) > max_chars:
        split_at = _choose_char_split_index(remaining, max_chars=max_chars)
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def _choose_char_split_index(text: str, *, max_chars: int) -> int:
    limit = min(len(text) - 1, max_chars + 4)
    min_chars = min(limit, max(8, max_chars // 2))
    target = min(limit, max(10, int(max_chars * 0.78)))
    best_index = min(max_chars, len(text) - 1)
    best_score = float("-inf")
    for index in range(min_chars, limit + 1):
        score = _score_break_boundary(text[:index], text[index:], index=index, target=target)
        if score > best_score:
            best_score = score
            best_index = index
    return max(1, min(best_index, max_chars, len(text) - 1))


def _choose_word_split_index(words: list[dict], *, max_chars: int, max_duration: float) -> int:
    if len(words) <= 1:
        return 1
    target = min(max_chars, max(8, int(max_chars * 0.78)))
    best_index = len(words) - 1
    best_score = float("-inf")
    for index in range(1, len(words)):
        left = _words_to_text(words[:index])
        right = _words_to_text(words[index:])
        if not left or not right:
            continue
        duration = float(words[index - 1]["end"]) - float(words[0]["start"])
        overflow_penalty = max(0.0, duration - max_duration) * 8.0
        score = _score_break_boundary(left, right, index=len(left), target=target) - overflow_penalty
        boundary_quality = _semantic_boundary_quality(left, right)
        pause_after = max(0.0, float(words[index].get("start", 0.0) or 0.0) - float(words[index - 1].get("end", 0.0) or 0.0))
        if pause_after >= 0.25:
            score += min(pause_after, 1.2) * (6.0 if boundary_quality >= 0 else -4.0)
        if len(right) <= 4 and boundary_quality < 0:
            score -= 12
        if _boundary_splits_compound_term(left, right):
            score -= 10
        if _starts_with_soft_attached_fragment(right):
            score -= 6
        if _looks_like_soft_fragmentary_tail(left):
            score -= 6
        if len(left) > max_chars + 2:
            score -= (len(left) - max_chars) * 6
        if score > best_score:
            best_score = score
            best_index = index
    return max(1, min(best_index, len(words) - 1))


def _semantic_hold_duration_limit(*, text_length: int, max_chars: int, max_duration: float) -> float:
    limit = max(float(max_duration), 3.8) + 1.0
    if text_length <= max_chars:
        limit += 2.0
    elif text_length <= max_chars + 4:
        limit += 1.0
    return min(_MAX_SEMANTIC_BRIDGE_DURATION_SEC, limit)


def _looks_like_split_measure_phrase(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    return bool(_SPLIT_MEASURE_LEFT_RE.search(left_text) and _SPLIT_MEASURE_RIGHT_RE.match(right_text))


def _is_strong_fragment_boundary(left: str, right: str, *, gap: float) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _looks_like_split_measure_phrase(left_text, right_text):
        return True
    if _should_merge_subtitle_pair(left_text, right_text):
        return True
    return gap <= 0.05 and len(left_text) <= 5 and _semantic_boundary_quality(left_text, right_text) <= -2.5


def _fragmented_display_hold_duration_limit(
    *,
    text_length: int,
    max_chars: int,
    max_duration: float,
    gap: float,
    strong_fragment_boundary: bool,
) -> float:
    limit = _semantic_hold_duration_limit(
        text_length=text_length,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    if strong_fragment_boundary:
        limit += 1.6
    if gap <= 0.05:
        limit += 0.8
    elif gap <= 0.4:
        limit += 0.4
    if text_length <= max_chars + 2:
        limit += 0.6
    return min(_MAX_SEMANTIC_BRIDGE_DURATION_SEC, limit)


def _is_incomplete_subtitle_text(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if candidate[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    if re.search(r"[A-Za-z]{2,8}$", candidate):
        return True
    if _looks_like_unclosed_nominal_tail(candidate):
        return True
    if any(candidate.endswith(token) for token in _NO_SPLIT_ENDINGS):
        return True
    return bool(re.search(r"(?:得很|会有|还有|没有|以及|为了|对于|因为|如果|或者|还是|就是|不是)$", candidate))


def _looks_like_unclosed_nominal_tail(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if candidate[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    return bool(_UNCLOSED_NOMINAL_TAIL_RE.search(candidate))


def _starts_with_nominal_head(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if re.match(r"^[，。！？、：；,.!?]", candidate):
        return False
    if any(candidate.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        return False
    if any(candidate.startswith(token) for token in _NO_SPLIT_PREFIXES):
        return False
    return bool(_NOMINAL_HEAD_RE.match(candidate))


def _boundary_splits_nominal_phrase(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    return _looks_like_unclosed_nominal_tail(left_text) and _starts_with_nominal_head(right_text)


def _semantic_boundary_quality(left: str, right: str) -> float:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return -100.0

    score = 0.0
    if _is_incomplete_subtitle_text(left_text):
        score -= 5.0
    if _looks_like_soft_fragmentary_tail(left_text):
        score -= 2.0
    if _starts_with_attached_fragment(right_text):
        score -= 5.0
    if _starts_with_soft_attached_fragment(right_text):
        score -= 2.0
    if _boundary_splits_nominal_phrase(left_text, right_text):
        score -= 5.0
    if _boundary_splits_compound_term(left_text, right_text):
        score -= 5.0
    if _boundary_splits_protected_term(left_text, right_text):
        score -= 8.0
    if left_text[-1] in _HARD_BREAK_CHARS:
        score += 5.0
    elif left_text[-1] in _SOFT_BREAK_CHARS:
        score += 2.0
    if any(right_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        score += 1.5
    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        score -= 2.5
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        score -= 2.5
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        score -= 6.0
    if len(right_text) <= 2:
        score -= 1.5
    return score


def _rebalance_semantic_boundaries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    rebalanced: list[SubtitleEntry] = [entries[0]]
    for entry in entries[1:]:
        previous = rebalanced[-1]
        previous, entry = _rebalance_semantic_pair(
            previous,
            entry,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        rebalanced[-1] = previous
        if entry is None:
            continue
        if _should_bridge_semantic_gap(previous, entry, max_chars=max_chars, max_duration=max_duration):
            rebalanced[-1] = _merge_subtitle_entries(previous, entry)
            continue
        rebalanced.append(entry)
    return _reindex_subtitle_entries(rebalanced)


def _rebalance_semantic_pair(
    left: SubtitleEntry,
    right: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> tuple[SubtitleEntry, SubtitleEntry | None]:
    gap = float(right.start) - float(left.end)
    if gap < 0.0 or gap > _MAX_SEMANTIC_BRIDGE_GAP_SEC:
        return left, right

    right_words = list(right.words or ())
    if len(right_words) <= 1:
        return left, right
    leading_word = _words_to_text(right_words[:1])
    current_quality = _semantic_boundary_quality(left.text_raw, right.text_raw)
    if (
        current_quality > -2.5
        and len(leading_word) > 1
        and not _boundary_splits_protected_term(left.text_raw, right.text_raw)
    ):
        return left, right

    best_candidate: tuple[float, SubtitleEntry, SubtitleEntry] | None = None
    max_prefix_words = min(len(right_words) - 1, _MAX_SEMANTIC_TRANSFER_WORDS)
    for prefix_count in range(1, max_prefix_words + 1):
        prefix_words = right_words[:prefix_count]
        suffix_words = right_words[prefix_count:]
        prefix_text = _words_to_text(prefix_words)
        suffix_text = _words_to_text(suffix_words)
        if not prefix_text or not suffix_text:
            continue
        if len(prefix_text) > _MAX_SEMANTIC_TRANSFER_CHARS:
            break

        left_words = tuple(left.words or ()) + tuple(prefix_words)
        new_left_text = _words_to_text(list(left_words)) or f"{left.text_raw}{prefix_text}"
        if len(new_left_text) > max_chars + (8 if len(prefix_text) <= 4 else 6):
            continue

        new_left_duration = float(prefix_words[-1]["end"]) - float(left.start)
        if new_left_duration > _semantic_hold_duration_limit(
            text_length=len(new_left_text),
            max_chars=max_chars,
            max_duration=max_duration,
        ):
            continue

        new_quality = _semantic_boundary_quality(new_left_text, suffix_text)
        improvement = new_quality - current_quality
        if _is_incomplete_subtitle_text(left.text_raw) and not _is_incomplete_subtitle_text(new_left_text):
            improvement += 4.0
        if _starts_with_attached_fragment(right.text_raw) and not _starts_with_attached_fragment(suffix_text):
            improvement += 3.0
        if _boundary_splits_protected_term(left.text_raw, right.text_raw) and not _boundary_splits_protected_term(new_left_text, suffix_text):
            improvement += 4.0
        if len(prefix_text) <= 1 and any(suffix_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
            improvement += 3.0
        if (
            prefix_count == 1
            and gap <= 0.05
            and len(left.text_raw) <= max(10, max_chars - 2)
            and len(right.text_raw) >= 8
            and not any(suffix_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
        ):
            improvement += 2.4
        if gap >= 0.8 and len(prefix_text) <= 4:
            improvement += 1.0

        required_improvement = 3.5
        if _is_incomplete_subtitle_text(left.text_raw):
            required_improvement -= 0.9
        if gap >= 0.8 and len(prefix_text) <= 4:
            required_improvement -= 0.5
        if _looks_like_split_measure_phrase(left.text_raw, right.text_raw):
            required_improvement -= 0.8

        if improvement < max(2.0, required_improvement):
            continue

        new_left = _make_subtitle_entry(
            left.index,
            left.start,
            float(prefix_words[-1]["end"]),
            new_left_text,
            words=left_words,
        )
        new_right = _make_subtitle_entry(
            right.index,
            float(suffix_words[0]["start"]),
            right.end,
            suffix_text,
            words=suffix_words,
        )
        if best_candidate is None or improvement > best_candidate[0]:
            best_candidate = (improvement, new_left, new_right)

    if best_candidate is None:
        return left, right
    return best_candidate[1], best_candidate[2]


def _should_bridge_semantic_gap(
    left: SubtitleEntry,
    right: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    gap = float(right.start) - float(left.end)
    if gap <= 0.18 or gap > _MAX_SEMANTIC_BRIDGE_GAP_SEC:
        return False

    combined_text = f"{left.text_raw}{right.text_raw}"
    if len(combined_text) > max_chars + 8:
        return False

    attached = _starts_with_attached_fragment(right.text_raw)
    incomplete = _is_incomplete_subtitle_text(left.text_raw)
    protected = _boundary_splits_protected_term(left.text_raw, right.text_raw)
    tiny_right = len(right.text_raw) <= 4
    strong_fragment_boundary = _is_strong_fragment_boundary(left.text_raw, right.text_raw, gap=gap)
    if not (attached or incomplete or protected or tiny_right or strong_fragment_boundary):
        return False
    if gap > 1.2 and not (tiny_right or protected or attached):
        return False
    if gap > 0.8 and not (tiny_right or protected or attached or (strong_fragment_boundary and incomplete)):
        return False
    if float(right.end) - float(left.start) > _fragmented_display_hold_duration_limit(
        text_length=len(combined_text),
        max_chars=max_chars,
        max_duration=max_duration,
        gap=gap,
        strong_fragment_boundary=strong_fragment_boundary,
    ):
        return False
    return strong_fragment_boundary or _semantic_boundary_quality(left.text_raw, right.text_raw) <= -4.0


def _merge_subtitle_entries(left: SubtitleEntry, right: SubtitleEntry) -> SubtitleEntry:
    return _make_subtitle_entry(
        left.index,
        left.start,
        right.end,
        f"{left.text_raw}{right.text_raw}",
        words=tuple(left.words or ()) + tuple(right.words or ()),
    )


def _score_break_boundary(left: str, right: str, *, index: int, target: int) -> float:
    score = -abs(index - target)
    left_text = str(left or "")
    right_text = str(right or "")
    if not left_text or not right_text:
        return score - 100

    last_char = left_text[-1]
    if last_char in _HARD_BREAK_CHARS:
        score += 48
    elif last_char in _SOFT_BREAK_CHARS:
        score += 32

    if any(right_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        score += 18

    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        score -= 24
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        score -= 26
    if _starts_with_soft_attached_fragment(right_text):
        score -= 14
    if _looks_like_soft_fragmentary_tail(left_text):
        score -= 12
    if _boundary_splits_compound_term(left_text, right_text):
        score -= 30
    if _boundary_splits_protected_term(left_text, right_text):
        score -= 64

    if re.match(r"^[，。！？、：；,.!?]", right_text):
        score -= 30
    score += _semantic_boundary_quality(left_text, right_text) * 4.0
    return score


def _merge_continuation_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if not entries:
        return []
    merged: list[SubtitleEntry] = []
    for entry in entries:
        if not merged:
            merged.append(entry)
            continue
        prev = merged[-1]
        combined_text = f"{prev.text_raw}{entry.text_raw}"
        combined_duration = float(entry.end) - float(prev.start)
        gap = max(0.0, float(entry.start) - float(prev.end))
        protected_boundary = _boundary_splits_protected_term(prev.text_raw, entry.text_raw)
        fragment_boundary = _starts_with_attached_fragment(entry.text_raw)
        strong_fragment_boundary = _is_strong_fragment_boundary(prev.text_raw, entry.text_raw, gap=gap)
        allowed_chars = max_chars + 6 + (4 if protected_boundary else 0)
        short_text_bonus = 2.0 if len(combined_text) <= max(16, max_chars - 8) else 0.0
        allowed_duration = (
            max_duration
            + 1.0
            + (1.5 if protected_boundary else 0.0)
            + (0.6 if fragment_boundary else 0.0)
            + short_text_bonus
        )
        allowed_duration = max(
            allowed_duration,
            _fragmented_display_hold_duration_limit(
                text_length=len(combined_text),
                max_chars=max_chars,
                max_duration=max_duration,
                gap=gap,
                strong_fragment_boundary=strong_fragment_boundary,
            ),
        )
        if (
            gap <= 0.18
            and len(combined_text) <= allowed_chars
            and combined_duration <= allowed_duration
            and (strong_fragment_boundary or _should_merge_subtitle_pair(prev.text_raw, entry.text_raw))
        ):
            merged[-1] = _make_subtitle_entry(
                prev.index,
                prev.start,
                entry.end,
                combined_text,
                words=tuple(prev.words or ()) + tuple(entry.words or ()),
            )
            continue
        merged.append(entry)
    return _reindex_subtitle_entries(merged)


def _cleanup_subtitle_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    cleaned: list[SubtitleEntry] = []
    for entry in entries:
        duration = float(entry.end) - float(entry.start)
        if duration <= 0.08:
            continue
        text_raw = str(entry.text_raw or "").strip()
        if cleaned:
            previous = cleaned[-1]
            gap = float(entry.start) - float(previous.end)
            if gap <= 0.9:
                for _ in range(3):
                    overlap = _shared_edge_overlap_text(previous.text_raw, text_raw, max_overlap=10)
                    if overlap and 4 <= len(overlap) <= 10 and len(text_raw) >= len(overlap) + 2:
                        trimmed = text_raw[len(overlap):].lstrip("，。！？!?、：:；;,. ")
                        if len(trimmed) >= 2:
                            text_raw = trimmed
                            continue
                    repeated_prefix = _leading_repeated_prefix_text(text_raw)
                    if (
                        repeated_prefix
                        and len(text_raw) >= len(repeated_prefix) + 2
                        and repeated_prefix in previous.text_raw[max(0, len(previous.text_raw) - len(repeated_prefix) - 3):]
                    ):
                        trimmed = text_raw[len(repeated_prefix):].lstrip("，。！？!?、：:；;,. ")
                        if len(trimmed) >= 2:
                            text_raw = trimmed
                            continue
                    break
        normalized_text = normalize_text(entry.text_raw)
        if text_raw != str(entry.text_raw or "").strip():
            normalized_text = normalize_text(text_raw)
        if not normalized_text.strip("，。！？!?、,.；;：:\"'()（）[]【】"):
            continue
        if cleaned:
            previous = cleaned[-1]
            previous_norm = normalize_text(previous.text_raw)
            gap = float(entry.start) - float(previous.end)
            if normalized_text == previous_norm and gap <= 0.18:
                cleaned[-1] = SubtitleEntry(
                    index=previous.index,
                    start=previous.start,
                    end=max(previous.end, entry.end),
                    text_raw=previous.text_raw,
                    text_norm=previous_norm,
                    words=tuple(previous.words or ()) + tuple(entry.words or ()),
                )
                continue
            if gap <= 0.35 and _are_near_duplicate_subtitles(previous.text_raw, entry.text_raw):
                merged_text = _pick_clearer_duplicate_text(previous.text_raw, entry.text_raw)
                cleaned[-1] = SubtitleEntry(
                    index=previous.index,
                    start=previous.start,
                    end=max(previous.end, entry.end),
                    text_raw=merged_text,
                    text_norm=normalize_text(merged_text),
                    words=tuple(previous.words or ()) + tuple(entry.words or ()),
                )
                continue
        cleaned.append(
            SubtitleEntry(
                index=len(cleaned),
                start=entry.start,
                end=entry.end,
                text_raw=text_raw,
                text_norm=normalized_text,
                words=tuple(entry.words or ()),
            )
        )
    return _collapse_repeated_sequence_entries(cleaned)


def _is_low_confidence_boundary(left: SubtitleEntry, right: SubtitleEntry) -> bool:
    gap = max(0.0, float(right.start) - float(left.end))
    if _looks_like_particle_led_sentence_restart(right.text_raw) and not (
        _boundary_splits_nominal_phrase(left.text_raw, right.text_raw)
        or _boundary_splits_protected_term(left.text_raw, right.text_raw)
        or _looks_like_split_measure_phrase(left.text_raw, right.text_raw)
        or _boundary_splits_compound_term(left.text_raw, right.text_raw)
    ):
        return False
    if gap > _MAX_SEMANTIC_BRIDGE_GAP_SEC and not (
        _boundary_splits_nominal_phrase(left.text_raw, right.text_raw)
        or _boundary_splits_protected_term(left.text_raw, right.text_raw)
        or _looks_like_split_measure_phrase(left.text_raw, right.text_raw)
        or _boundary_splits_compound_term(left.text_raw, right.text_raw)
        or _starts_with_attached_fragment(right.text_raw)
    ):
        return False
    score = _semantic_boundary_quality(left.text_raw, right.text_raw)
    if score <= -1.5:
        return True
    if _boundary_splits_nominal_phrase(left.text_raw, right.text_raw):
        return True
    if _boundary_splits_protected_term(left.text_raw, right.text_raw):
        return True
    if _looks_like_split_measure_phrase(left.text_raw, right.text_raw):
        return True
    if _boundary_splits_compound_term(left.text_raw, right.text_raw):
        return True
    if _starts_with_attached_fragment(right.text_raw):
        return True
    if _starts_with_soft_attached_fragment(right.text_raw):
        return True
    if _looks_like_soft_fragmentary_tail(left.text_raw):
        return True
    if _is_incomplete_subtitle_text(left.text_raw) and not any(
        right.text_raw.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES
    ):
        return True
    if (
        len(left.text_raw) <= 5
        and len(right.text_raw) >= 8
        and gap <= 0.18
        and score <= -0.5
    ):
        return True
    return False


def _collect_low_confidence_windows(entries: list[SubtitleEntry]) -> list[tuple[int, int]]:
    if len(entries) <= 1:
        return []

    suspicious_boundaries = {
        index
        for index, (left, right) in enumerate(zip(entries, entries[1:]))
        if _is_low_confidence_boundary(left, right)
    }
    fragment_entry_indexes = {
        index
        for index, entry in enumerate(entries)
        if _entry_needs_residual_repair(
            previous=entries[index - 1] if index > 0 else None,
            current=entry,
            following=entries[index + 1] if index + 1 < len(entries) else None,
        )
    }
    if not suspicious_boundaries and not fragment_entry_indexes:
        return []

    windows: list[tuple[int, int]] = []
    sorted_boundaries = sorted(suspicious_boundaries)
    if sorted_boundaries:
        group_start = sorted_boundaries[0]
        group_end = sorted_boundaries[0]
    else:
        group_start = group_end = -1
    for boundary_index in sorted_boundaries[1:]:
        if boundary_index <= group_end + 1:
            group_end = boundary_index
            continue
        windows.append((max(0, group_start - 1), min(len(entries) - 1, group_end + 2)))
        group_start = group_end = boundary_index
    if sorted_boundaries:
        windows.append((max(0, group_start - 1), min(len(entries) - 1, group_end + 2)))
    for entry_index in sorted(fragment_entry_indexes):
        windows.append((max(0, entry_index - 1), min(len(entries) - 1, entry_index + 1)))

    merged_windows: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not merged_windows or start > merged_windows[-1][1]:
            merged_windows.append((start, end))
            continue
        previous_start, previous_end = merged_windows[-1]
        merged_windows[-1] = (previous_start, max(previous_end, end))
    return merged_windows


def _entry_needs_residual_repair(
    *,
    previous: SubtitleEntry | None,
    current: SubtitleEntry,
    following: SubtitleEntry | None,
) -> bool:
    candidate = str(current.text_raw or "").strip()
    if not candidate:
        return False
    near_neighbor = False
    if previous is not None and 0.0 <= float(current.start) - float(previous.end) <= _MAX_SEMANTIC_BRIDGE_GAP_SEC:
        near_neighbor = True
    if following is not None and 0.0 <= float(following.start) - float(current.end) <= _MAX_SEMANTIC_BRIDGE_GAP_SEC:
        near_neighbor = True
    if not near_neighbor:
        return False
    if _starts_with_attached_fragment(candidate):
        return True
    if _looks_like_unclosed_nominal_tail(candidate):
        return True
    if len(candidate) > 8:
        return False
    if _starts_with_soft_attached_fragment(candidate):
        return True
    if _is_incomplete_subtitle_text(candidate):
        return True
    if _looks_like_soft_fragmentary_tail(candidate):
        return True
    return False


def _build_low_confidence_window_summary(
    entries: list[SubtitleEntry],
    start: int,
    end: int,
) -> dict[str, object]:
    window_entries = entries[start:end + 1]
    return {
        "start_index": start,
        "end_index": end,
        "entry_count": max(0, end - start + 1),
        "texts": [entry.text_raw for entry in window_entries],
        "start_time": round(float(window_entries[0].start), 3) if window_entries else 0.0,
        "end_time": round(float(window_entries[-1].end), 3) if window_entries else 0.0,
    }


def _refine_low_confidence_windows(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    windows = _collect_low_confidence_windows(entries)
    if not windows:
        return entries

    refined: list[SubtitleEntry] = []
    cursor = 0
    for start, end in windows:
        refined.extend(entries[cursor:start])
        window_entries = entries[start:end + 1]
        candidate_entries = _resolve_fragment_window(
            window_entries,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        refined.extend(candidate_entries if candidate_entries is not None else window_entries)
        cursor = end + 1
    refined.extend(entries[cursor:])
    return _reindex_subtitle_entries(refined)


def _resolve_fragment_window(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry] | None:
    if len(entries) <= 1:
        return None

    current_score = _score_entry_sequence(entries, max_chars=max_chars, max_duration=max_duration)
    candidate_entries = _resplit_fragment_window(entries, max_chars=max_chars, max_duration=max_duration)
    if not candidate_entries:
        return None

    candidate_score = _score_entry_sequence(candidate_entries, max_chars=max_chars, max_duration=max_duration)
    if candidate_score < current_score + 2.0:
        return None
    return candidate_entries


def _resplit_fragment_window(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry] | None:
    relaxed_max_chars = max_chars + 2
    relaxed_max_duration = max_duration + 0.5
    searched_candidates = _search_fragment_window_segmentations(
        entries,
        max_chars=relaxed_max_chars,
        max_duration=relaxed_max_duration,
        top_k=1,
    )
    searched_entries = searched_candidates[0] if searched_candidates else None
    if searched_entries:
        return _resolve_subtitle_entry_sequence(
            searched_entries,
            max_chars=relaxed_max_chars,
            max_duration=relaxed_max_duration,
            allow_window_refine=False,
        )

    combined_words = [word for entry in entries for word in tuple(entry.words or ())]
    if len(combined_words) >= 2:
        candidate_entries = _segment_entries_from_words(
            combined_words,
            max_chars=relaxed_max_chars,
            max_duration=relaxed_max_duration,
        )
    else:
        candidate_entries = _segment_entries_from_text(entries, max_chars=relaxed_max_chars)
    if not candidate_entries:
        return None
    return _resolve_subtitle_entry_sequence(
        candidate_entries,
        max_chars=relaxed_max_chars,
        max_duration=relaxed_max_duration,
        allow_window_refine=False,
    )


def _segment_entries_from_text(entries: list[SubtitleEntry], *, max_chars: int) -> list[SubtitleEntry]:
    combined_text = "".join(entry.text_raw for entry in entries)
    if not combined_text:
        return []
    window_start = float(entries[0].start)
    window_end = float(entries[-1].end)
    if len(combined_text) <= max_chars:
        return [_make_subtitle_entry(0, window_start, window_end, combined_text)]

    chunks = _split_plain_text(combined_text, max_chars=max_chars)
    if not chunks:
        return []
    duration = max(window_end - window_start, 0.001)
    time_per_char = duration / max(len(combined_text), 1)
    char_offset = 0
    resolved: list[SubtitleEntry] = []
    for index, chunk in enumerate(chunks):
        start = window_start + char_offset * time_per_char
        end = start + len(chunk) * time_per_char
        resolved.append(_make_subtitle_entry(index, start, min(end, window_end), chunk))
        char_offset += len(chunk)
    return resolved


def _score_single_entry(
    entry: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> float:
    duration = max(0.0, float(entry.end) - float(entry.start))
    score = 0.0
    score -= max(0, len(entry.text_raw) - max_chars) * 8.0
    score -= max(0.0, duration - max_duration) * 6.0
    if _starts_with_attached_fragment(entry.text_raw):
        score -= 14.0
    if _starts_with_soft_attached_fragment(entry.text_raw):
        score -= 6.0
    if _is_incomplete_subtitle_text(entry.text_raw):
        score -= 12.0
    if _looks_like_unclosed_nominal_tail(entry.text_raw):
        score -= 8.0
    if _looks_like_soft_fragmentary_tail(entry.text_raw):
        score -= 6.0
    if len(entry.text_raw) <= 2:
        score -= 5.0
    return score


def _score_boundary_pair(left: SubtitleEntry, right: SubtitleEntry) -> float:
    score = _semantic_boundary_quality(left.text_raw, right.text_raw) * 5.0
    if _boundary_splits_nominal_phrase(left.text_raw, right.text_raw):
        score -= 14.0
    if _boundary_splits_protected_term(left.text_raw, right.text_raw):
        score -= 16.0
    if _looks_like_split_measure_phrase(left.text_raw, right.text_raw):
        score -= 12.0
    if _boundary_splits_compound_term(left.text_raw, right.text_raw):
        score -= 20.0
    return score


def _search_fragment_window_segmentations(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
    top_k: int = 4,
) -> list[list[SubtitleEntry]]:
    all_candidates: list[tuple[float, list[SubtitleEntry]]] = []
    seen: set[tuple[str, ...]] = set()
    for window_words in _window_word_streams_for_resegmentation(entries):
        for candidate_score, raw_entries in _search_fragment_window_segmentations_for_word_stream(
            window_words,
            max_chars=max_chars,
            max_duration=max_duration,
        ):
            if not raw_entries:
                continue
            cleaned_entries = _cleanup_subtitle_entries(raw_entries)
            key = tuple(entry.text_raw for entry in cleaned_entries)
            if not key or key in seen:
                continue
            seen.add(key)
            all_candidates.append((candidate_score, cleaned_entries))
    if not all_candidates:
        return []
    ranked = sorted(all_candidates, key=lambda item: item[0], reverse=True)
    current_entry_count = len(entries)
    selected: list[list[SubtitleEntry]] = []
    selected_keys: set[tuple[str, ...]] = set()

    def _add_candidate(candidate: list[SubtitleEntry]) -> None:
        key = tuple(entry.text_raw for entry in candidate)
        if not key or key in selected_keys:
            return
        selected_keys.add(key)
        selected.append(candidate)

    primary_slots = max(1, top_k // 2)
    for _score, candidate in ranked[:primary_slots]:
        _add_candidate(candidate)

    best_same_or_less_by_count: dict[int, tuple[float, list[SubtitleEntry]]] = {}
    for score, candidate in ranked:
        entry_count = len(candidate)
        if entry_count > current_entry_count:
            continue
        existing = best_same_or_less_by_count.get(entry_count)
        if existing is None or score > existing[0]:
            best_same_or_less_by_count[entry_count] = (score, candidate)
    for entry_count in sorted(best_same_or_less_by_count):
        _add_candidate(best_same_or_less_by_count[entry_count][1])
        if len(selected) >= max(1, top_k):
            return selected[: max(1, top_k)]

    for _score, candidate in ranked:
        _add_candidate(candidate)
        if len(selected) >= max(1, top_k):
            break
    return selected[: max(1, top_k)]


def _search_fragment_window_segmentations_for_word_stream(
    window_words: list[dict[str, float | str]],
    *,
    max_chars: int,
    max_duration: float,
) -> list[tuple[float, list[SubtitleEntry]]]:
    if len(window_words) < 2:
        return []

    hard_char_limit = max(max_chars + 8, int(max_chars * 1.7))
    hard_duration_limit = max_duration + 2.0
    options_by_start: dict[int, list[tuple[int, SubtitleEntry, float]]] = {}
    for start_index in range(len(window_words)):
        options: list[tuple[int, SubtitleEntry, float]] = []
        for end_index in range(start_index + 1, len(window_words) + 1):
            candidate_words = window_words[start_index:end_index]
            text = _words_to_text(candidate_words)
            if not text:
                continue
            duration = max(0.0, float(candidate_words[-1]["end"]) - float(candidate_words[0]["start"]))
            if len(text) > hard_char_limit or duration > hard_duration_limit:
                break
            entry = _make_subtitle_entry(
                0,
                float(candidate_words[0]["start"]),
                float(candidate_words[-1]["end"]),
                text,
                words=candidate_words,
            )
            options.append((end_index, entry, _score_single_entry(entry, max_chars=max_chars, max_duration=max_duration)))
        options_by_start[start_index] = options

    beam_width = 48
    beams: dict[int, list[tuple[float, list[SubtitleEntry]]]] = {0: [(0.0, [])]}
    for start_index in range(len(window_words)):
        current_beam = list(beams.get(start_index) or [])
        if not current_beam:
            continue
        advanced_positions: set[int] = set()
        for score_so_far, built_entries in current_beam:
            previous_entry = built_entries[-1] if built_entries else None
            for end_index, template_entry, entry_score in options_by_start.get(start_index, []):
                new_entry = SubtitleEntry(
                    index=len(built_entries),
                    start=template_entry.start,
                    end=template_entry.end,
                    text_raw=template_entry.text_raw,
                    text_norm=template_entry.text_norm,
                    words=tuple(template_entry.words or ()),
                )
                new_score = score_so_far + entry_score
                if previous_entry is not None:
                    new_score += _score_boundary_pair(previous_entry, new_entry) - 0.4
                beams.setdefault(end_index, []).append((new_score, built_entries + [new_entry]))
                advanced_positions.add(end_index)
        for end_index in advanced_positions:
            ranked = sorted(
                beams.get(end_index) or [],
                key=lambda item: item[0],
                reverse=True,
            )
            beams[end_index] = ranked[:beam_width]

    final_candidates = list(beams.get(len(window_words)) or [])
    if not final_candidates:
        return []

    ranked = sorted(final_candidates, key=lambda item: item[0], reverse=True)
    unique_candidates: list[tuple[float, list[SubtitleEntry]]] = []
    seen: set[tuple[str, ...]] = set()
    for _score, raw_entries in ranked:
        if not raw_entries:
            continue
        cleaned_entries = _cleanup_subtitle_entries(raw_entries)
        key = tuple(entry.text_raw for entry in cleaned_entries)
        if not key or key in seen:
            continue
        seen.add(key)
        unique_candidates.append(
            (_score_entry_sequence(cleaned_entries, max_chars=max_chars, max_duration=max_duration), cleaned_entries)
        )
        if len(unique_candidates) >= 48:
            break
    return unique_candidates


def _score_entry_sequence(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> float:
    if not entries:
        return float("-inf")

    score = 0.0
    for entry in entries:
        score += _score_single_entry(entry, max_chars=max_chars, max_duration=max_duration)
    for left, right in zip(entries, entries[1:]):
        score += _score_boundary_pair(left, right)
    score -= max(0, len(entries) - 1) * 0.4
    return score


def _collapse_repeated_sequence_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    collapsed: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        matched = False
        for window in (3, 2):
            if index + window > len(entries):
                continue
            group = entries[index:index + window]
            if any(float(group[pos + 1].start) - float(group[pos].end) > 0.18 for pos in range(len(group) - 1)):
                continue
            combined_text = "".join(item.text_raw for item in group)
            collapsed_text = _collapse_exact_repeated_phrase(combined_text)
            if not collapsed_text or collapsed_text == combined_text:
                continue
            collapsed.append(
                _make_subtitle_entry(
                    len(collapsed),
                    group[0].start,
                    group[-1].end,
                    collapsed_text,
                    words=sum((tuple(item.words or ()) for item in group), ()),
                )
            )
            index += window
            matched = True
            break
        if matched:
            continue
        item = entries[index]
        collapsed.append(
            SubtitleEntry(
                index=len(collapsed),
                start=item.start,
                end=item.end,
                text_raw=item.text_raw,
                text_norm=item.text_norm,
                words=tuple(item.words or ()),
            )
        )
        index += 1
    return collapsed


def _collapse_exact_repeated_phrase(text: str) -> str | None:
    candidate = str(text or "").strip()
    if len(candidate) < 4:
        return None
    for unit_len in range(2, len(candidate) // 2 + 1):
        if len(candidate) % unit_len != 0:
            continue
        unit = candidate[:unit_len]
        if unit * (len(candidate) // unit_len) == candidate:
            return unit
    return None


def _shared_edge_overlap_text(left: str, right: str, *, max_overlap: int = 8) -> str:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return ""
    upper = min(len(left_text), len(right_text), max_overlap)
    for size in range(upper, 2, -1):
        suffix = left_text[-size:]
        if right_text.startswith(suffix):
            return suffix
    return ""


def _leading_repeated_prefix_text(text: str, *, max_unit: int = 6) -> str:
    candidate = str(text or "").strip()
    if len(candidate) < 4:
        return ""
    upper = min(max_unit, len(candidate) // 2)
    for size in range(upper, 1, -1):
        prefix = candidate[:size]
        if candidate.startswith(prefix * 2):
            return prefix
    return ""


def _should_merge_subtitle_pair(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text[-1] in _HARD_BREAK_CHARS:
        return False
    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        return True
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        return True
    if re.search(r"[A-Za-z]{2,8}$", left_text) and re.match(r"^[\u4e00-\u9fffA-Za-z0-9]", right_text):
        return True
    if (
        left_text[-1] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and len(left_text) <= 6
        and len(right_text) >= len(left_text) + 2
    ):
        return True
    if (
        right_text[0] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and len(right_text) <= 4
        and len(left_text) >= len(right_text) + 2
    ):
        return True
    if _boundary_splits_protected_term(left_text, right_text):
        return True
    if _boundary_splits_compound_term(left_text, right_text):
        return True
    if _boundary_splits_nominal_phrase(left_text, right_text):
        return True
    if _starts_with_attached_fragment(right_text):
        return True
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        return True
    return False


def _boundary_splits_protected_term(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    for term in _BOUNDARY_PROTECTED_TERMS:
        for split_at in range(1, len(term)):
            if left_text.endswith(term[:split_at]) and right_text.startswith(term[split_at:]):
                return True
    return False


def _boundary_splits_model_token(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if re.search(rf"[A-Za-z]{{2,8}}(?:{_DISPLAY_NUM_TOKEN})?$", left_text):
        return bool(re.match(rf"(?:{_DISPLAY_NUM_TOKEN}|[A-Za-z0-9]+)", right_text))
    if re.search(rf"[A-Za-z]{{1,8}}(?:{_DISPLAY_NUM_TOKEN}){{1,2}}$", left_text):
        return bool(re.match(rf"(?:{_DISPLAY_NUM_TOKEN}|\d+|[A-Za-z]+)", right_text))
    return False


def _starts_with_attached_fragment(text: str) -> bool:
    right_text = str(text or "").strip()
    if not right_text:
        return False
    stripped_text = _strip_boundary_leading_particles(right_text)
    candidate = stripped_text or right_text
    if re.match(r"^[，。！？、：；,.!?]", candidate):
        return True
    if any(candidate.startswith(token) for token in _ATTACHED_FRAGMENT_PREFIXES):
        return True
    if len(candidate) <= 2 and not any(candidate.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        return True
    single_char_continuation = _SINGLE_CHAR_CONTINUATION_START_RE.match(candidate)
    if single_char_continuation and single_char_continuation.group("head") not in _SINGLE_CHAR_FREE_STARTERS:
        return True
    match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9])[，、：,.!?]", candidate)
    if not match:
        return False
    token = match.group(1)
    if token in _GOOD_BREAK_PREFIXES or token in _NO_SPLIT_PREFIXES:
        return False
    return True


def _starts_with_soft_attached_fragment(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if _starts_with_attached_fragment(candidate):
        return True
    stripped = _strip_boundary_leading_particles(candidate) or candidate
    return any(stripped.startswith(prefix) for prefix in _SOFT_ATTACHED_FRAGMENT_PREFIXES)


def _strip_boundary_leading_particles(text: str) -> str:
    result = str(text or "").strip()
    changed = True
    while result and changed:
        changed = False
        result = result.lstrip("，,。！？!?、：:；; ")
        for token in _BOUNDARY_LEADING_PARTICLES:
            if result.startswith(token) and len(result) > len(token):
                result = result[len(token):].lstrip("，,。！？!?、：:；; ")
                changed = True
                break
    return result


def _looks_like_particle_led_sentence_restart(text: str) -> bool:
    candidate = str(text or "").strip()
    stripped = _strip_boundary_leading_particles(candidate)
    if not stripped or stripped == candidate:
        return False
    if any(stripped.startswith(prefix) for prefix in _PARTICLE_LED_RESTART_PREFIXES):
        return True
    return False


def _looks_like_soft_fragmentary_tail(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if _is_incomplete_subtitle_text(candidate):
        return True
    return any(candidate.endswith(token) for token in _SOFT_FRAGMENTARY_ENDINGS)


def _boundary_splits_compound_term(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _boundary_splits_model_token(left_text, right_text):
        return True
    return any(left_text.endswith(prefix) and right_text.startswith(suffix) for prefix, suffix in _BOUNDARY_COMPOUND_SPLITS)


def _compact_compare_text(text: str) -> str:
    compact = re.sub(r"[，。！？!?、；;：:,.\-\"'()\[\]（）【】\s]+", "", str(text or "").strip())
    compact = re.sub(r"(其实|就是|然后|那个|这个|当然|的话|一下|一下子|也算|算是|上是|吧)+", "", compact)
    return compact


def _are_near_duplicate_subtitles(left: str, right: str) -> bool:
    left_compact = _compact_compare_text(left)
    right_compact = _compact_compare_text(right)
    if not left_compact or not right_compact:
        return False
    if left_compact == right_compact:
        return True
    shorter, longer = sorted((left_compact, right_compact), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return True
    ratio = difflib.SequenceMatcher(a=left_compact, b=right_compact).ratio()
    return ratio >= 0.8


def _pick_clearer_duplicate_text(left: str, right: str) -> str:
    left_text = _normalize_compare_subtitle_text(left).rstrip("。！？!?")
    right_text = _normalize_compare_subtitle_text(right).rstrip("。！？!?")
    left_compact = _compact_compare_text(left_text)
    right_compact = _compact_compare_text(right_text)
    if len(right_compact) > len(left_compact):
        return right_text
    if len(left_compact) > len(right_compact):
        return left_text
    if len(right_text) > len(left_text):
        return right_text
    return left_text


def _words_to_text(words: list[dict]) -> str:
    return "".join(re.sub(r"\s+", "", str(word.get("word", ""))) for word in words)


def _normalize_compare_subtitle_text(text: str) -> str:
    result = str(text or "").strip()
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[。.]{2,}", "。", result)
    result = re.sub(r"[，,]+[。.!！？]+", "。", result)
    result = re.sub(r"[。.!！？]+[，,]+", "。", result)
    result = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", result)
    return result


async def save_subtitle_items(
    job_id: uuid.UUID,
    entries: list[SubtitleEntry],
    session: AsyncSession,
    version: int = 1,
) -> list[SubtitleItem]:
    """Persist subtitle entries to the database."""
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.version == version))

    items: list[SubtitleItem] = []
    for entry in entries:
        item = SubtitleItem(
            job_id=job_id,
            version=version,
            item_index=entry.index,
            start_time=entry.start,
            end_time=entry.end,
            text_raw=entry.text_raw,
            text_norm=entry.text_norm,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items
