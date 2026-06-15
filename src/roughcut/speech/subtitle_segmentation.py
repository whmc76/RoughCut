from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass

try:
    import jieba
except ImportError:  # pragma: no cover - optional dependency in minimal installs
    jieba = None

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.media.subtitle_spans import drop_redundant_synthetic_word_payloads
from roughcut.media.subtitle_text import normalize_editable_subtitle_text
from roughcut.speech.alignment import tokenize_alignment_text


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


@dataclass(frozen=True)
class BoundaryAssessment:
    left_text: str
    right_text: str
    left_core: str
    quality: float
    damage_flags: tuple[str, ...] = ()
    positive_flags: tuple[str, ...] = ()
    forbidden: bool = False
    left_incomplete: bool = False


@dataclass
class SubtitleSegmentationAnalysis:
    entry_count: int
    fragment_start_count: int
    fragment_end_count: int
    protected_term_split_count: int
    generic_word_split_count: int
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
            "generic_word_split_count": self.generic_word_split_count,
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
    return tokenize_alignment_text(compact)


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
    "毫安",
    "安时",
    "瓦时",
    "赫兹",
    "英寸",
    "版本",
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
    "堆",
    "套",
    "只",
    "支",
    "根",
    "片",
    "双",
    "本",
    "台",
    "瓶",
    "包",
    "盒",
    "袋",
    "组",
    "枚",
    "段",
    "圈",
    "口",
    "份",
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
    "流明",
    "GB",
    "MB",
    "TB",
    "mAh",
    "Ah",
    "Wh",
    "Hz",
    "fps",
)
_DISPLAY_NUM_TOKEN = r"[零〇幺一二两三四五六七八九十百千万\d]+"
_DISPLAY_DIGIT_SEQUENCE_TOKEN = r"[零〇幺一二两三四五六七八九\d]+"
_DISPLAY_ORDINAL_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_ORDINAL_UNITS), key=len, reverse=True)
)
_DISPLAY_QUANTITY_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_QUANTITY_UNITS), key=len, reverse=True)
)
_DISPLAY_RANGE_CONNECTOR = r"(?:到|至|-|~|－|—)"
_PERCENT_NUMBER_RE = re.compile(rf"百分之(?P<number>{_DISPLAY_NUM_TOKEN})")
_ORDINAL_NUMBER_RE = re.compile(
    rf"第(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_ORDINAL_UNIT_PATTERN})"
)
_RANGE_QUANTITY_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<start>{_DISPLAY_NUM_TOKEN})(?P<connector>{_DISPLAY_RANGE_CONNECTOR})"
    rf"(?P<end>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_QUANTITY_UNIT_PATTERN})"
)
_QUANTITY_NUMBER_RE = re.compile(
    rf"(?<![第A-Za-z0-9.几数])(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_QUANTITY_UNIT_PATTERN})"
)
_DECIMAL_NUMBER_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<integer>{_DISPLAY_NUM_TOKEN})点(?P<fraction>{_DISPLAY_DIGIT_SEQUENCE_TOKEN})"
    rf"(?P<unit>{_DISPLAY_QUANTITY_UNIT_PATTERN})"
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
_CHINESE_DIGIT_SEQUENCE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>[零〇幺一二两三四五六七八九]{2,})"
    r"(?=(?:号|款|版|年|月|日|集|期|代|[\s，,。.!！？；;：:]|$))"
)
_DEFAULT_CHINESE_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>[零〇幺一二两三四五六七八九十百千万]{2,})(?![A-Za-z0-9])"
)
_SPOKEN_DIGIT_RUN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<number>[零〇幺一二两三四五六七八九\d]*幺[零〇幺一二两三四五六七八九\d]{1,5})"
)
_HOMOPHONE_DUPLICATE_TOKEN_RE = re.compile(
    r"\d{1,6}|[零〇幺一二两三四五六七八九十百千万七期起器气汽其奇齐棋漆]{1,8}"
)
_HOMOPHONE_DUPLICATE_SEPARATOR_RE = re.compile(r"^[\s了的啊呀嘛呢吧呗额呃]*$")
_CLAUSE_DUPLICATE_FILLER_RE = re.compile(r"^(?:这个|那个|就是|然后|其实|可能|但是|不过|所以|那么|那)+")
_CHINESE_NUMBER_PHRASE_RE = re.compile(r"[零〇幺一二两三四五六七八九十百千万]{2,}")
_CLAUSE_PUNCTUATION = "，,。！？!?；;"
_WORD_PARTICLE_TOKENS = {"了", "的", "啊", "呀", "嘛", "呢", "吧", "呗", "额", "呃"}
_HOMOPHONE_SYLLABLES = {
    "0": "ling",
    "1": "yi",
    "2": "er",
    "3": "san",
    "4": "si",
    "5": "wu",
    "6": "liu",
    "7": "qi",
    "8": "ba",
    "9": "jiu",
    "零": "ling",
    "〇": "ling",
    "幺": "yi",
    "一": "yi",
    "二": "er",
    "两": "er",
    "三": "san",
    "四": "si",
    "五": "wu",
    "六": "liu",
    "七": "qi",
    "八": "ba",
    "九": "jiu",
    "十": "shi",
    "百": "bai",
    "千": "qian",
    "万": "wan",
    "期": "qi",
    "起": "qi",
    "器": "qi",
    "气": "qi",
    "汽": "qi",
    "其": "qi",
    "奇": "qi",
    "齐": "qi",
    "棋": "qi",
    "漆": "qi",
}
_SPOKEN_DIGIT_CHAR_CLASS = "零〇幺一二两三四五六七八九0-9"
_SPLIT_SPOKEN_DIGIT_LEFT_RE = re.compile(
    rf"^(?P<prefix>.*?)(?P<digits>[{_SPOKEN_DIGIT_CHAR_CLASS}]{{0,5}}幺[{_SPOKEN_DIGIT_CHAR_CLASS}]*)[，,。.!！？；;：:\s]*$"
)
_SPLIT_SPOKEN_DIGIT_RIGHT_RE = re.compile(
    rf"^[，,。.!！？；;：:\s]*(?P<digits>[{_SPOKEN_DIGIT_CHAR_CLASS}]{{1,5}})(?P<suffix>.*)$"
)
_SAFE_DISPLAY_TERM_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z0-9])CAC(?=(?:的|外壳|壳体|机身|工艺|切削|精雕|加工|结构|边角|铝合金|中框|骨架))", re.IGNORECASE), "CNC"),
    (re.compile(r"预制感(?=(?:吧|，|。|的|它应该叫陶瓷|就是|有一种|$))"), "玉质感"),
)
_NATURAL_SINGLE_UNITS = {"个", "次", "年", "月", "天", "小时", "分钟", "秒"}
_NATURAL_SINGLE_QUANTITY_UNITS = {
    "个",
    "把",
    "堆",
    "颗",
    "条",
    "件",
    "款",
    "套",
    "只",
    "支",
    "根",
    "片",
    "双",
    "本",
    "台",
    "瓶",
    "包",
    "盒",
    "袋",
    "组",
    "枚",
    "段",
    "圈",
    "口",
    "份",
    "张",
    "面",
    "页",
    "层",
    "排",
    "项",
    "种",
    "次",
    "句",
    "步",
    "轮",
    "名",
    "块",
}
_NATURAL_SINGLE_DIGIT_DISPLAY = {
    "1": "一",
    "2": "两",
    "3": "三",
    "4": "四",
    "5": "五",
    "6": "六",
    "7": "七",
    "8": "八",
    "9": "九",
}
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
_VAGUE_NUMBER_CONTEXT_UNITS = _NATURAL_SINGLE_QUANTITY_UNITS | _NATURAL_SINGLE_UNITS | {
    "期",
    "集",
    "页",
    "张",
    "层",
    "排",
    "项",
    "种",
    "步",
    "轮",
    "名",
}
_DEFAULT_CHINESE_NUMBER_IDIOMS = {
    "零零散散",
    "三三两两",
    "七七八八",
    "一五一十",
    "十全十美",
}
_INFO_COUNT_NOUN_PREFIXES = (
    "档位",
    "接口",
    "版本",
    "型号",
    "规格",
    "模式",
    "方案",
    "步骤",
    "配色",
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
    "功能键",
    "参数",
    "孔位",
    "按钮",
    "刀型",
    "钢材",
    "容量",
    "续航",
)
_SUBTITLE_FILLER_PREFIX_TOKENS = (
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
_LOW_SIGNAL_SHORT_CLAUSE_TOKENS = {
    "今天",
    "开始",
    "开始吧",
    "今天介绍",
    "补充一段",
    "花了",
    "强行",
    "然后",
    "对",
    "因为",
    "基本",
    "什么",
    "哎哦对",
    "待会再说",
    "没事",
}
_LOW_SIGNAL_SHORT_CLAUSE_RE = re.compile(
    r"^(?:好开始|这个什么|那个什么|什么|待会再说(?:那个刀)?|完梗了(?:啊这个)?|今天|开始|开始吧|今天介绍|补充一段|花了|强行|然后|对|因为|基本|哎哦对|没事)$"
)
_INLINE_FILLER_RE = re.compile(r"(?:呃|嗯|诶|欸|哎|哈|哦)+")
_INLINE_PARTICLE_RE = re.compile(r"(?<=[\u4e00-\u9fffA-Za-z0-9])(?:啊|吧|呢|吗|嘛|呀)(?=[\u4e00-\u9fffA-Za-z0-9])")
_ASR_NOISE_LABEL = (
    r"(?:background[_\s-]?music|background[_\s-]?noise|environmental[_\s-]?sounds?|"
    r"environmentalsounds|human[_\s-]?sounds?|humansounds|sounds?|"
    r"no[_\s-]?speech|nospeech|silence|music|noise)"
)
_ASR_INLINE_NOISE_LABEL = (
    r"(?:EnvironmentalSounds|Environmental[_\s-]?Sounds?|BackgroundNoise|"
    r"HumanSounds|Human[_\s-]?Sounds?|Sounds?|Noise)"
)
_ASR_NOISE_MARKER_PATTERN = re.compile(
    r"(?i)"
    rf"(?:<\|?\s*(?:{_ASR_NOISE_LABEL}(?:\s+{_ASR_NOISE_LABEL})*)\s*\|?>)"
    rf"|(?:[\[\(（【<]\s*(?:{_ASR_NOISE_LABEL}(?:\s+{_ASR_NOISE_LABEL})*)\s*[\]\)）】>])"
    r"|[♪♫]+"
)
_ASR_INLINE_NOISE_MARKER_PATTERN = re.compile(_ASR_INLINE_NOISE_LABEL, re.IGNORECASE)
_ASR_NOISE_ONLY_PATTERN = re.compile(
    rf"(?i)^(?:(?:{_ASR_NOISE_LABEL})(?:\s+(?:{_ASR_NOISE_LABEL}))*|静音|无语音)$"
)
_TRAILING_FILLER_RE = re.compile(r"(?:呢|吗|嘛|呀|哈|哦|诶|欸|哎)+$")
_TRAILING_KEEPABLE_PARTICLE_RE = re.compile(r"(?:啊+|吧+)$")
_TERMINAL_PUNCTUATION = "。！？!?"
_HARD_BREAK_CHARS = "。！？!?；;"
_SOFT_BREAK_CHARS = "，,、：:"
_BOUNDARY_LEADING_PARTICLES = ("呃", "嗯", "啊", "吧", "呢", "吗", "嘛", "呀", "哈", "哦", "诶", "欸", "哎")
_BOUNDARY_TRAILING_BRIDGE_RE = re.compile(r"(?:呃|嗯|啊|吧|呢|吗|嘛|呀|哈|哦|诶|欸|哎|那){1,2}$")
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
    "来",
)
_DETACHABLE_LEAD_IN_CHAIN_TOKENS = frozenset(
    {
        "然后",
        "那么",
        "首先",
        "其实",
        "所以",
        "另外",
        "但是",
        "不过",
        "比如",
        "例如",
        "或者说",
        "就是说",
        "然后呢",
        "那么呢",
        "首先呢",
        "其实呢",
        "所以呢",
        "另外呢",
        "但是呢",
        "不过呢",
        *tuple(_BOUNDARY_LEADING_PARTICLES),
    }
)
_NO_SPLIT_ENDINGS = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "是", "只",
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
    *tuple(_INFO_COUNT_NOUN_PREFIXES),
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
    "比如",
    "或者说",
    "大家",
    "我们",
    "你们",
    "其他",
    "相当",
    "一个",
    "一直",
    "之前",
    "之后",
    "平时",
    "临时",
    "晚上",
    "没啥",
    "做一下",
    "讲一下",
    "说一下",
    "看一下",
    "试一下",
)
_CLAUSE_CLOSED_PARTICLE_ENDINGS = (
    "了",
    "呢",
    "吗",
    "嘛",
    "啊",
    "呀",
    "哦",
    "哇",
    "啦",
    "哈",
    "诶",
    "欸",
    "哎",
)
_SUBJECT_LED_CLAUSE_HEAD_TOKENS = (
    "我",
    "我们",
    "你",
    "你们",
    "他",
    "他们",
    "她",
    "她们",
    "它",
    "它们",
    "大家",
    "咱们",
)
_SUBJECT_LED_CLAUSE_CONTINUATION_PREFIXES = (
    "就",
    "也",
    "还",
    "都",
    "会",
    "要",
    "能",
    "可以",
    "应该",
    "直接",
    "简单",
    "继续",
    "开始",
    "先",
    "再",
    "拿",
    "做",
    "看",
    "讲",
    "说",
    "作为",
    "按",
    "长按",
    "短按",
    "双击",
    "单击",
    "点按",
    "触发",
    "打开",
    "关闭",
    "旋转",
    "进入",
)
_ADVERB_LED_CLAUSE_HEAD_TOKENS = (
    "也",
    "就",
    "还",
    "并",
    "又",
    "再",
    "都",
    "先",
)
_ADVERB_LED_CLAUSE_CONTINUATION_PREFIXES = (
    "不是",
    "没有",
    "不会",
    "不能",
    "不用",
    "只是",
    "就",
    "还",
    "要",
    "会",
    "能",
    "可以",
    "知道",
    "确认",
    "判断",
    "说明",
    "体现",
)
_PREDICATE_CONTINUATION_ENDINGS = (
    "应该",
    "可以",
    "需要",
    "必须",
    "继续",
    "准备",
    "能够",
    "值得",
    "方便",
    "看过",
    "听过",
    "见过",
    "聊过",
    "讲过",
    "说过",
    "提过",
    "用过",
    "发过",
    "带过",
    "出过",
    "定位",
    "符合",
    "满足",
    "没啥",
)
_PREDICATE_CONTINUATION_PREFIXES = (
    "可以",
    "看",
    "看出",
    "看出来",
    "说",
    "讲",
    "做",
    "用",
    "给",
    "把",
    "拿",
    "去",
    "来",
    "确认",
    "判断",
    "证明",
    "体现",
    "说明",
    "相当",
    "非常",
    "好说",
)
_PREDICATE_OBJECT_CONTINUATION_ENDINGS = (
    "看过",
    "听过",
    "见过",
    "聊过",
    "讲过",
    "说过",
    "提过",
    "用过",
    "发过",
    "带过",
    "出过",
)
_REASON_PREAMBLE_ENDINGS = (
    "为什么",
    "为什么我",
    "为什么你",
    "为什么我们",
    "为什么大家",
    "为什么他",
    "为什么她",
    "为什么它",
)
_REASON_PREAMBLE_PREFIXES = (
    "平时",
    "现在",
    "一般",
    "通常",
    "临时",
    "晚上",
    "出门",
    "拿",
    "用",
    "带",
    "会",
    "要",
    "喜欢",
    "选择",
    "做",
)
_BOUNDARY_FORBIDDEN_DAMAGE_FLAGS = frozenset(
    {
        "numeric_unit",
        "predicate_phrase",
        "reason_preamble",
        "suffix_particle_continuation",
        "subject_clause_restart",
        "demonstrative_modifier_phrase",
        "classifier_noun_phrase",
    }
)
_SUBJECT_CLAUSE_RESTART_TAILS = (
    "你",
    "我",
    "他",
    "她",
    "它",
    "我们",
    "你们",
    "他们",
    "她们",
    "咱们",
    "大家",
)
_SUBJECT_CLAUSE_RESTART_PREFIXES = (
    "可以",
    "也可以",
    "都可以",
    "就可以",
    "还能",
    "也能",
    "都能",
    "会",
    "也会",
    "都会",
    "要",
    "也要",
    "就要",
    "得",
    "就得",
    "需要",
    "就需要",
)
_DEMONSTRATIVE_MODIFIER_PREFIXES = (
    "这个版本",
    "那个版本",
    "这一版",
    "那一版",
    "这个",
    "那个",
    "这把",
    "那把",
    "这款",
    "那款",
    "这边",
    "那边",
    "这种",
    "那种",
)
_BOUNDARY_WORD_CONTINUATION_FLAGS = frozenset(
    {
        "protected_term",
        "generic_word",
        "compound_term",
    }
)
_BOUNDARY_SEMANTIC_DAMAGE_WEIGHTS = {
    "attached_fragment_start": 5.0,
    "soft_attached_fragment_start": 2.0,
    "measure_phrase_split": 5.0,
    "nominal_phrase": 5.0,
    "bare_determiner_phrase": 7.0,
    "pronoun_modifier_phrase": 6.0,
    "predicate_phrase": 6.0,
    "reason_preamble": 8.0,
    "subject_clause_restart": 8.0,
    "demonstrative_modifier_phrase": 7.0,
    "classifier_noun_phrase": 7.0,
    "repeated_model_suffix": 7.0,
    "honor_transition_phrase": 7.0,
    "possessive_phrase": 7.0,
    "compound_term": 5.0,
    "generic_word": 7.0,
    "single_char_residual": 6.0,
    "protected_term": 8.0,
    "no_split_ending": 2.5,
    "no_split_prefix": 2.5,
    "leading_punctuation": 6.0,
    "soft_fragmentary_tail": 2.0,
    "short_right": 1.5,
}
_BOUNDARY_SEMANTIC_POSITIVE_WEIGHTS = {
    "hard_break_closed": 5.0,
    "soft_break_closed": 2.0,
    "good_break_prefix": 1.5,
}
_BOUNDARY_BREAK_DAMAGE_WEIGHTS = {
    "no_split_ending": 24.0,
    "no_split_prefix": 26.0,
    "soft_attached_fragment_start": 14.0,
    "measure_phrase_split": 32.0,
    "nominal_phrase": 12.0,
    "bare_determiner_phrase": 42.0,
    "pronoun_modifier_phrase": 36.0,
    "predicate_phrase": 38.0,
    "subject_clause_restart": 44.0,
    "demonstrative_modifier_phrase": 40.0,
    "classifier_noun_phrase": 40.0,
    "repeated_model_suffix": 44.0,
    "possessive_phrase": 42.0,
    "soft_fragmentary_tail": 12.0,
    "compound_term": 30.0,
    "model_token": 16.0,
    "protected_term": 64.0,
    "generic_word": 56.0,
    "leading_punctuation": 30.0,
}
_BOUNDARY_BREAK_POSITIVE_WEIGHTS = {
    "hard_break_closed": 48.0,
    "hard_break_incomplete": 8.0,
    "soft_break_closed": 32.0,
    "soft_break_incomplete": 6.0,
    "good_break_prefix": 18.0,
}
_BOUNDARY_WORD_CANDIDATE_DAMAGE_WEIGHTS = {
    "no_split_ending": 8.0,
    "attached_fragment_start": 8.0,
    "soft_attached_fragment_start": 4.0,
    "soft_fragmentary_tail": 4.0,
    "compound_term": 10.0,
    "measure_phrase_split": 18.0,
    "nominal_phrase": 12.0,
    "predicate_phrase": 14.0,
    "subject_clause_restart": 16.0,
    "demonstrative_modifier_phrase": 14.0,
    "classifier_noun_phrase": 14.0,
    "model_token": 16.0,
    "honor_transition_phrase": 18.0,
    "protected_term": 12.0,
    "generic_word": 14.0,
}
_BOUNDARY_PAIR_DAMAGE_WEIGHTS = {
    "measure_phrase_split": 12.0,
    "nominal_phrase": 14.0,
    "protected_term": 16.0,
    "generic_word": 18.0,
    "predicate_phrase": 18.0,
    "reason_preamble": 20.0,
    "subject_clause_restart": 22.0,
    "demonstrative_modifier_phrase": 20.0,
    "classifier_noun_phrase": 20.0,
    "repeated_model_suffix": 24.0,
    "honor_transition_phrase": 24.0,
    "possessive_phrase": 22.0,
    "compound_term": 20.0,
}
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
    "入",
)
_BOUNDARY_COMPOUND_SPLITS: tuple[tuple[str, str], ...] = (
    ("直", "接"),
    ("需", "要"),
    ("设", "计"),
    ("那", "种"),
    ("这", "个"),
    ("那", "个"),
    ("可", "以"),
    ("因", "为"),
    ("另", "外"),
    ("之", "前"),
    ("应", "该"),
    ("使", "用"),
    ("没", "啥"),
    ("我", "们"),
    ("你", "们"),
    ("它", "们"),
    ("他", "妈"),
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
    ("节", "目"),
    ("我们", "节目"),
    ("小", "兄弟"),
    ("兄", "弟"),
    ("新", "兄弟"),
    ("退", "役"),
    ("耐", "克尔"),
    ("耐克", "尔"),
    ("对", "比"),
    ("特", "色"),
    ("手", "感"),
    ("配", "色"),
    ("版", "本"),
    ("胸", "包"),
    ("副", "包"),
    ("工", "业"),
    ("狐", "蝠"),
    ("狐蝠", "工业"),
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
    ("联", "名"),
    ("其", "实"),
)
_FALLBACK_GENERIC_CJK_BOUNDARY_TERMS = tuple(
    sorted(
        {
            "我们",
            "你们",
            "他们",
            "它们",
            "这个",
            "那个",
            "直接",
            "需要",
            "因为",
            "另外",
            "应该",
            "使用",
            "介绍",
            "一下",
            "今天",
            "终于",
            "收到",
            "年前",
            "最后",
            "一个",
            "一款",
            "小玩具",
            "玩具",
            "发售",
            "抢购",
            "难度",
            "直线",
            "上升",
            "没想到",
            "现在",
            "这么",
            "这次",
            "两次",
            "都是",
            "极限",
            "转账",
            "毫不费力",
            "油光水润",
            "玉质感",
            "预制感",
            "高抛光",
            "锆合金",
            "喜欢",
            "可以",
            "理解",
            "为什么",
            "大家",
            "设计",
            "工业",
            "狐蝠",
            "狐蝠工业",
            "特色",
            "手感",
            "配色",
            "版本",
            "胸包",
            "副包",
            "小副包",
            "对比",
            "角度",
            "产品",
            "功能",
            "内容",
            "东西",
            "细节",
            "参数",
            "结构",
            "材料",
            "质感",
            "容量",
            "重量",
            "尺寸",
            "开箱",
            "手电",
            "流明",
            "亮度",
            "升级",
            "定位",
            "符合",
            "满足",
        },
        key=len,
        reverse=True,
    )
)

_SPLIT_MEASURE_LEFT_RE = re.compile(
    rf"(?:{_DISPLAY_NUM_TOKEN}|这|那|每|某|另|前|后|首|第|几)$"
)
_SPLIT_MEASURE_RIGHT_RE = re.compile(
    rf"^(?:{_DISPLAY_NUM_TOKEN})?(?:个|只|把|条|点|件|款|袋|盒|包|支|瓶|片|颗|次|种|位|类|份|套|台|张|米|寸|段|步|层|页|代|号|年|月|天|周|小时|分钟|秒|流明)"
)
_NUMERIC_MEASURE_UNITS = tuple(
    sorted(
        set(_DISPLAY_QUANTITY_UNITS)
        | {
            "lm",
            "lumen",
            "lumens",
            "mAh",
            "Ah",
            "Wh",
            "mm",
            "cm",
            "km",
            "kg",
            "mg",
            "ml",
            "GB",
            "MB",
            "TB",
            "fps",
            "Hz",
            "kHz",
            "MHz",
            "GHz",
            "W",
            "V",
            "A",
            "K",
            "nit",
            "nits",
            "inch",
            "inches",
        },
        key=len,
        reverse=True,
    )
)
_NUMERIC_MEASURE_UNIT_PATTERN = "|".join(re.escape(unit) for unit in _NUMERIC_MEASURE_UNITS)
_NUMERIC_MEASURE_LEFT_RE = re.compile(rf"(?:\d+(?:\.\d+)?|{_DISPLAY_NUM_TOKEN})$")
_NUMERIC_MEASURE_RIGHT_RE = re.compile(
    rf"^(?:{_NUMERIC_MEASURE_UNIT_PATTERN})(?=$|[\u4e00-\u9fffA-Za-z])",
    re.IGNORECASE,
)
_NUMERIC_APPROX_RIGHT_RE = re.compile(r"^多(?:的|度|个|只|把|条|件|款|米|厘米|毫米|流明)?")
_NUMERIC_MEASURE_TOKEN_RE = re.compile(
    rf"\d+(?:\.\d+)?(?:{_NUMERIC_MEASURE_UNIT_PATTERN})(?=$|[\u4e00-\u9fffA-Za-z])",
    re.IGNORECASE,
)
_EMPHASIS_REPEAT_CUE_RE = re.compile(r"(?:说|讲|重复)(?:一|两|二|三|3|好多)遍")
_COUNTING_REPEAT_UNIT_RE = re.compile(r"^(?:第[\u4e00-\u9fff\d]{1,3}|[\u4e00-\u9fff\d]{1,3}个)$")
_UNCLOSED_NOMINAL_TAIL_RE = re.compile(
    r"(?:"
    r"第(?:[0-9]+|[一二两三四五六七八九十])个|"
    r"(?:[0-9]+|[一二两三四五六七八九十])个|"
    r"(?:[0-9]+|[一二两三四五六七八九十])款|"
    r"(?:这|那|该)(?:个|种|类|边|款|版|期|段|次|点)|"
    r"(?:这|那|该)升级|"
    r"(?:前头|后头|上头|里头|这头|那头)|"
    r"一款|"
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
_LOW_CONFIDENCE_WINDOW_MAX_ENTRIES = 6
_LOW_CONFIDENCE_WINDOW_MAX_CHARS = 84
_SYNTHETIC_WORD_SOURCES = {"synthetic", "segment_only", "provider_missing", "roughcut_synthesized"}
_SEGMENTATION_COMPACT_PUNCT_RE = re.compile(r"[\s，。！？!?；;：:,、（）()\[\]【】{}\"'《》<>]+")
_SINGLE_CHAR_CONTINUATION_HEADS = "我你他她它这那就也都还又才先再并但"
_SINGLE_CHAR_CONTINUATION_START_RE = re.compile(
    rf"^(?P<head>[{_SINGLE_CHAR_CONTINUATION_HEADS}])(?P<rest>也|都|就|是|有|会|要|在|来|去|从|跟|把|被|里|上|下)"
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


def _normalize_segmentation_words(raw_words: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for raw_word in list(raw_words or []):
        if not isinstance(raw_word, dict):
            continue
        word_text = re.sub(r"\s+", "", str(raw_word.get("word", "")))
        if not word_text:
            continue
        start = float(raw_word.get("start") or 0.0)
        end = max(start, float(raw_word.get("end") or start))
        alignment_source = _extract_word_alignment_source(raw_word)
        if alignment_source in _SYNTHETIC_WORD_SOURCES:
            subtokens = _tokenize_entry_text_for_resegmentation(word_text)
            if len(subtokens) > 1:
                duration = max(end - start, 0.001)
                total_units = sum(max(len(token), 1) for token in subtokens)
                unit_span = duration / max(total_units, 1)
                consumed_units = 0
                for index, token in enumerate(subtokens):
                    token_units = max(len(token), 1)
                    token_start = start + consumed_units * unit_span
                    consumed_units += token_units
                    token_end = end if index == len(subtokens) - 1 else min(end, start + consumed_units * unit_span)
                    normalized.append(
                        {
                            **dict(raw_word),
                            "word": token,
                            "start": token_start,
                            "end": max(token_start, token_end),
                        }
                    )
                continue
        normalized.append(
            {
                **dict(raw_word),
                "word": word_text,
                "start": start,
                "end": end,
            }
        )
    return _drop_timestamp_homophone_duplicate_words(normalized)


def _segmentation_word_source(words: list[dict]) -> str:
    normalized_words = _normalize_segmentation_words(words)
    if not normalized_words:
        return "missing"
    if any(_extract_word_alignment_source(word) in _SYNTHETIC_WORD_SOURCES for word in normalized_words):
        return "synthetic"
    return "provider"


def _segmentation_words_pass_coverage(text: str, words: list[dict]) -> bool:
    normalized_words = _normalize_segmentation_words(words)
    if len(normalized_words) < 2:
        return False

    compact_text = re.sub(r"[\s\uff0c\u3002\uff01\uff1f!?\uff1b;\uff1a:,\u3001\uff08\uff09()\u3010\u3011\[\]{}\"'\u300a\u300b<>]+", "", str(text or "").strip())
    compact_words = re.sub(
        r"[\s\uff0c\u3002\uff01\uff1f!?\uff1b;\uff1a:,\u3001\uff08\uff09()\u3010\u3011\[\]{}\"'\u300a\u300b<>]+",
        "",
        "".join(str(word.get("word") or "").strip() for word in normalized_words),
    )
    if compact_text and compact_words:
        coverage = difflib.SequenceMatcher(a=compact_words, b=compact_text).ratio()
        if coverage < 0.86:
            return False
    return True


def _classify_segmentation_words(text: str, words: list[dict]) -> str:
    source = _segmentation_word_source(words)
    if source == "missing":
        return "missing"
    if _segmentation_words_pass_coverage(text, words):
        return source
    return "untrusted"


def _words_are_usable_for_segmentation(text: str, words: list[dict]) -> bool:
    return _segmentation_words_pass_coverage(text, words)


def _words_for_segmentation(seg: TranscriptSegment) -> list[dict]:
    raw_words = drop_redundant_synthetic_word_payloads(list(getattr(seg, "words_json", []) or []))
    if not raw_words:
        return []
    if _words_are_usable_for_segmentation(getattr(seg, "text", ""), raw_words):
        normalized_words = _normalize_segmentation_words(raw_words)
        if _segmentation_words_use_alignment_timings_unsafely(getattr(seg, "text", ""), normalized_words):
            return _build_text_fallback_words(
                getattr(seg, "text", ""),
                start=float(getattr(seg, "start_time", 0.0) or 0.0),
                end=float(getattr(seg, "end_time", 0.0) or 0.0),
            )
        if _segmentation_words_are_overly_granular(getattr(seg, "text", ""), normalized_words):
            retokenized_words = _retokenize_granular_segmentation_words(
                getattr(seg, "text", ""),
                normalized_words,
            )
            if retokenized_words:
                return retokenized_words
            return _build_text_fallback_words(
                getattr(seg, "text", ""),
                start=float(getattr(seg, "start_time", 0.0) or 0.0),
                end=float(getattr(seg, "end_time", 0.0) or 0.0),
            )
        return normalized_words
    return _build_text_fallback_words(
        getattr(seg, "text", ""),
        start=float(getattr(seg, "start_time", 0.0) or 0.0),
        end=float(getattr(seg, "end_time", 0.0) or 0.0),
    )


def _segmentation_words_are_overly_granular(text: str, words: list[dict]) -> bool:
    if len(words) < 8:
        return False
    word_texts = [
        _SEGMENTATION_COMPACT_PUNCT_RE.sub("", str(word.get("word") or ""))
        for word in words
    ]
    word_texts = [word for word in word_texts if word]
    if len(word_texts) < 8:
        return False
    cjk_or_alnum_words = [word for word in word_texts if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", word)]
    if not cjk_or_alnum_words:
        return False
    single_unit_ratio = sum(1 for word in cjk_or_alnum_words if len(word) <= 1) / len(cjk_or_alnum_words)
    if single_unit_ratio < 0.72:
        return False
    tokenized = [
        token
        for token in tokenize_alignment_text(text)
        if _SEGMENTATION_COMPACT_PUNCT_RE.sub("", token)
    ]
    return len(tokenized) < len(cjk_or_alnum_words) * 0.82


def _segmentation_words_use_alignment_timings_unsafely(text: str, words: list[dict]) -> bool:
    if len(words) < 12:
        return False
    compact_words = [
        _SEGMENTATION_COMPACT_PUNCT_RE.sub("", str(word.get("word") or ""))
        for word in words
    ]
    compact_words = [word for word in compact_words if word]
    if len(compact_words) < 12:
        return False
    if not _segmentation_words_pass_coverage(text, words):
        return False
    cjk_or_alnum_words = [word for word in compact_words if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", word)]
    if len(cjk_or_alnum_words) < 12:
        return False
    short_chunk_ratio = sum(1 for word in cjk_or_alnum_words if len(word) <= 2) / len(cjk_or_alnum_words)
    if short_chunk_ratio < 0.9:
        return False
    alignment_sources = {
        str((word.get("alignment") or {}).get("source") or "")
        for word in words
        if isinstance(word, dict)
    }
    if alignment_sources and alignment_sources != {"canonical_realign"}:
        return False
    internal_gaps = [
        max(
            0.0,
            float(words[index + 1].get("start") or 0.0) - float(words[index].get("end") or 0.0),
        )
        for index in range(len(words) - 1)
    ]
    if not internal_gaps:
        return False
    max_gap = max(internal_gaps)
    gap_spike_count = sum(1 for gap in internal_gaps if gap >= 0.32)
    return max_gap >= 0.6 or gap_spike_count >= 2


def _retokenize_granular_segmentation_words(text: str, words: list[dict]) -> list[dict]:
    tokens = tokenize_alignment_text(text)
    if not tokens:
        return []
    units: list[dict[str, float | str | dict]] = []
    for word in words:
        word_text = str(word.get("word") or "").strip()
        chars = [
            char
            for char in _SEGMENTATION_COMPACT_PUNCT_RE.sub("", word_text)
            if char.strip()
        ]
        if not chars:
            continue
        start = float(word.get("start") or 0.0)
        end = max(start, float(word.get("end") or start))
        duration = max(0.0, end - start)
        for char_index, char in enumerate(chars):
            char_start = start + duration * (char_index / max(1, len(chars)))
            char_end = end if char_index == len(chars) - 1 else start + duration * ((char_index + 1) / max(1, len(chars)))
            units.append(
                {
                    "char": char.lower(),
                    "start": char_start,
                    "end": max(char_start, char_end),
                    "source_word": word_text,
                    "alignment": dict(word.get("alignment") or {}),
                }
            )
    if not units:
        return []

    unit_text = "".join(str(unit["char"]) for unit in units)
    cursor = 0
    retokenized: list[dict] = []
    for token in tokens:
        token_key = _SEGMENTATION_COMPACT_PUNCT_RE.sub("", str(token or "")).lower()
        if not token_key:
            continue
        match_at = unit_text.find(token_key, cursor)
        if match_at < 0:
            continue
        token_units = units[match_at:match_at + len(token_key)]
        if not token_units:
            continue
        retokenized.append(
            {
                "word": str(token),
                "start": float(token_units[0]["start"]),
                "end": float(token_units[-1]["end"]),
                "alignment": {
                    **dict(token_units[0].get("alignment") or {}),
                    "source": "provider_retokenized",
                    "strategy": "alignment_tokenizer",
                },
            }
        )
        cursor = match_at + len(token_key)
    compact_source = _SEGMENTATION_COMPACT_PUNCT_RE.sub("", str(text or "")).lower()
    compact_retokenized = _SEGMENTATION_COMPACT_PUNCT_RE.sub("", "".join(str(word.get("word") or "") for word in retokenized)).lower()
    if len(compact_retokenized) < len(compact_source) * 0.82:
        return []
    return retokenized


def _collect_segmentation_input_stats(segments: list[TranscriptSegment]) -> dict[str, int]:
    stats = {
        "provider_word_segment_count": 0,
        "synthetic_word_segment_count": 0,
        "untrusted_word_segment_count": 0,
        "text_only_segment_count": 0,
    }
    for seg in list(segments or []):
        raw_words = drop_redundant_synthetic_word_payloads(list(getattr(seg, "words_json", []) or []))
        if not raw_words:
            stats["text_only_segment_count"] += 1
            continue
        source = _segmentation_word_source(raw_words)
        if source == "provider":
            stats["provider_word_segment_count"] += 1
            continue
        if source == "synthetic":
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


def _normalize_display_text_core(
    text: str,
    *,
    cleanup_fillers: bool,
    lexical_cleanup: bool,
) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    result = _strip_asr_noise_markers(result)
    result = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", result)
    if cleanup_fillers:
        result = cleanup_subtitle_fillers(result)
    result = transcribe_subtitle_numerals(result)
    result = _normalize_safe_display_terms(result)
    if lexical_cleanup:
        result = _collapse_clause_level_homophone_duplicates(result)
        result = _collapse_inline_homophone_duplicates(result)
    result = apply_subtitle_clause_spacing(result)
    result = re.sub(r"\s+([，,。.!！？；;：:])", r"\1", result)
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[。.]{2,}", "。", result)
    result = re.sub(r"[，,]+([。.!！？])", r"\1", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip("，,")


def normalize_display_text(text: str, *, cleanup_fillers: bool = True) -> str:
    return _normalize_display_text_core(
        text,
        cleanup_fillers=cleanup_fillers,
        lexical_cleanup=True,
    )


def normalize_projection_display_text(text: str) -> str:
    """Projection-safe display normalization.

    Projection/display layers may normalize numerals, punctuation, and safe
    glossary terms, but they must not delete fillers or collapse clauses in a
    way that rewrites lexical content.
    """
    return _normalize_display_text_core(
        text,
        cleanup_fillers=False,
        lexical_cleanup=False,
    )


def normalize_display_numbers(text: str) -> str:
    """Compatibility wrapper for subtitle numeral transcription."""
    return transcribe_subtitle_numerals(text)


def cleanup_subtitle_fillers(text: str) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    result = _strip_asr_noise_markers(result)

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
        clause = clause.strip("，, ")
        if (
            not clause
            or _is_low_signal_short_clause(clause)
        ):
            continue
        cleaned.append(clause)

    collapsed = "".join(cleaned).strip("，,")
    collapsed = re.sub(r"([，,；;]){2,}", lambda match: match.group(0)[0], collapsed)
    collapsed = re.sub(r"[，,]+([。！？!?；;])", r"\1", collapsed)
    return collapsed


def _is_low_signal_short_clause(text: str) -> bool:
    clause = str(text or "").strip()
    if not clause:
        return True
    if _ASR_NOISE_ONLY_PATTERN.fullmatch(clause):
        return True
    if clause in _LOW_SIGNAL_SHORT_CLAUSE_TOKENS or _LOW_SIGNAL_SHORT_CLAUSE_RE.fullmatch(clause):
        return True
    if re.search(r"[A-Za-z0-9]", clause):
        return False
    compact = re.sub(r"\s+", "", clause)
    if len(compact) <= 2:
        return compact in {"今天", "开始", "花了", "强行", "对"}
    return False


def _strip_asr_noise_markers(text: str) -> str:
    result = _ASR_NOISE_MARKER_PATTERN.sub(" ", str(text or ""))
    result = _ASR_INLINE_NOISE_MARKER_PATTERN.sub("，", result)
    return re.sub(r"\s{2,}", " ", result).strip()


def apply_subtitle_clause_spacing(text: str) -> str:
    result = str(text or "").strip()
    if not result or len(result.replace(" ", "")) <= 10:
        return result
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    if " " not in result and len(result) >= 14:
        for token in _GOOD_BREAK_PREFIXES:
            result = re.sub(rf"(?<!^)(?<!\s)(?={re.escape(token)})", " ", result)
    return re.sub(r"\s{2,}", " ", result).strip()


def transcribe_subtitle_numerals(text: str) -> str:
    """Rewrite numeric expressions for readable Chinese subtitles.

    This intentionally handles only numeral presentation. It does not rewrite
    glossary terms, brands, product names, or semantic content.
    """
    if not text:
        return text

    result = _normalize_spaced_model_tokens(text)
    result = _normalize_colloquial_price_tokens(result)
    result = _normalize_alpha_numeric_tokens(result)
    result = _collapse_repeated_model_number_tokens(result)
    result = _normalize_time_tokens(result)
    result = _normalize_decimal_quantity_tokens(result)
    result = _normalize_spoken_digit_runs(result)
    result = _normalize_chinese_digit_sequences(result)
    result = _normalize_default_chinese_number_tokens(result)

    def replace_percent(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        return f"{number}%" if number else match.group(0)

    def replace_ordinal(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        unit = match.group("unit")
        return f"第{number}{unit}" if number else match.group(0)

    def replace_range(match: re.Match[str]) -> str:
        start_raw = str(match.group("start") or "")
        end_raw = str(match.group("end") or "")
        start_number = _normalize_numeric_token(start_raw)
        end_number = _normalize_numeric_token(end_raw)
        unit = str(match.group("unit") or "")
        if not start_number or not end_number:
            return match.group(0)
        tail_text = match.string[match.end():match.end() + 6]
        if _range_should_use_natural_chinese(start_raw, end_raw, unit, tail_text):
            connector = "到"
            return f"{_format_natural_number(start_number, raw_number=start_raw)}{connector}{_format_natural_number(end_number, raw_number=end_raw)}{unit}"
        connector = str(match.group("connector") or "到")
        return f"{start_number}{connector}{end_number}{unit}"

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
        natural_quantity = _format_natural_single_quantity(
            raw_number,
            number,
            unit,
            match.string[match.end():match.end() + 6],
        )
        if natural_quantity:
            return natural_quantity
        return f"{number}{unit}" if number else match.group(0)

    result = _PERCENT_NUMBER_RE.sub(replace_percent, result)
    result = _ORDINAL_NUMBER_RE.sub(replace_ordinal, result)
    result = _RANGE_QUANTITY_RE.sub(replace_range, result)
    result = _QUANTITY_NUMBER_RE.sub(replace_quantity, result)
    return result


def _normalize_safe_display_terms(text: str) -> str:
    result = str(text or "")
    for pattern, replacement in _SAFE_DISPLAY_TERM_REPLACEMENTS:
        result = pattern.sub(replacement, result)
    return result


def _collapse_clause_level_homophone_duplicates(text: str) -> str:
    pieces = [piece for piece in re.split(r"([，,。！？!?；;])", str(text or "")) if piece != ""]
    if len(pieces) < 3:
        return str(text or "")

    collapsed: list[str] = []
    for piece in pieces:
        if piece in _CLAUSE_PUNCTUATION:
            if collapsed and collapsed[-1] not in _CLAUSE_PUNCTUATION:
                collapsed.append(piece)
            continue

        clause = piece.strip()
        if not clause:
            continue
        previous_clause_index = next(
            (index for index in range(len(collapsed) - 1, -1, -1) if collapsed[index] not in _CLAUSE_PUNCTUATION),
            None,
        )
        if previous_clause_index is not None and _are_clause_level_homophone_duplicates(
            collapsed[previous_clause_index],
            clause,
        ):
            del collapsed[previous_clause_index:]
        collapsed.append(clause)
    return "".join(collapsed)


def _are_clause_level_homophone_duplicates(left: str, right: str) -> bool:
    left_key = _clause_duplicate_compare_key(left)
    right_key = _clause_duplicate_compare_key(right)
    if not left_key or not right_key:
        return False
    if len(left_key) < 6 or len(right_key) < 6:
        return False
    if left_key == right_key:
        return True
    shorter, longer = sorted((left_key, right_key), key=len)
    return len(shorter) >= 6 and shorter in longer


def _clause_duplicate_compare_key(text: str) -> str:
    result = str(text or "").strip()
    result = _CHINESE_NUMBER_PHRASE_RE.sub(_replace_chinese_number_phrase_for_duplicate_key, result)
    result = transcribe_subtitle_numerals(result)
    result = _CLAUSE_DUPLICATE_FILLER_RE.sub("", result)
    result = re.sub(r"(?:这个|那个|就是|然后|其实|可能|的话|一下|也算|算是)+", "", result)
    return re.sub(r"[\s，,。！？!?；;：:、.\-\"'()（）\[\]【】]+", "", result).lower()


def _replace_chinese_number_phrase_for_duplicate_key(match: re.Match[str]) -> str:
    token = str(match.group(0) or "")
    if token in _VAGUE_NUMBER_TOKENS:
        return token
    parsed = _parse_chinese_number(token)
    return str(parsed) if parsed is not None else token


def _collapse_inline_homophone_duplicates(text: str) -> str:
    result = str(text or "")
    changed = True
    while changed:
        changed = False
        candidates = list(_HOMOPHONE_DUPLICATE_TOKEN_RE.finditer(result))
        for left_index, left_match in enumerate(candidates):
            left_key = _homophone_duplicate_key(left_match.group(0))
            if not left_key:
                continue
            for right_match in candidates[left_index + 1:left_index + 4]:
                between = result[left_match.end():right_match.start()]
                if any(char in _CLAUSE_PUNCTUATION for char in between):
                    break
                if not _HOMOPHONE_DUPLICATE_SEPARATOR_RE.fullmatch(between):
                    continue
                right_key = _homophone_duplicate_key(right_match.group(0))
                if not right_key or right_key != left_key:
                    continue
                remove_end = right_match.end()
                compact_between = re.sub(r"\s+", "", between)
                if compact_between in {"了", "的"} and result[remove_end:remove_end + len(compact_between)] == compact_between:
                    remove_end += len(compact_between)
                result = f"{result[:right_match.start()]}{result[remove_end:]}"
                changed = True
                break
            if changed:
                break
    return result


def _homophone_duplicate_key(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return ""
    if value.isdigit():
        return "".join(_HOMOPHONE_SYLLABLES.get(char, "") for char in value)
    if re.fullmatch(r"[零〇幺一二两三四五六七八九十百千万]+", value):
        parsed = _parse_chinese_number(value)
        if parsed is not None and parsed >= 10:
            return "".join(_HOMOPHONE_SYLLABLES.get(char, "") for char in str(parsed))
    key = "".join(_HOMOPHONE_SYLLABLES.get(char, "") for char in value)
    return key if len(key) >= 4 else ""


def _drop_timestamp_homophone_duplicate_words(words: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    for word in list(words or []):
        if _is_timestamp_homophone_duplicate_word(deduped, word):
            continue
        deduped.append(word)
    return deduped


def _is_timestamp_homophone_duplicate_word(previous_words: list[dict], word: dict) -> bool:
    if not previous_words:
        return False
    current_key = _homophone_duplicate_key(str(word.get("word") or ""))
    if not current_key:
        return False

    candidates = [previous_words[-1]]
    if len(previous_words) >= 2 and str(previous_words[-1].get("word") or "") in _WORD_PARTICLE_TOKENS:
        candidates.append(previous_words[-2])
    for previous in candidates:
        previous_key = _homophone_duplicate_key(str(previous.get("word") or ""))
        if previous_key == current_key and _word_times_look_duplicate(previous, word):
            return True
    return False


def _word_times_look_duplicate(left: dict, right: dict) -> bool:
    try:
        left_start = float(left.get("start") or 0.0)
        left_end = float(left.get("end") or left_start)
        right_start = float(right.get("start") or 0.0)
        right_end = float(right.get("end") or right_start)
    except (TypeError, ValueError):
        return False
    overlap = max(0.0, min(left_end, right_end) - max(left_start, right_start))
    shorter = max(0.001, min(max(0.0, left_end - left_start), max(0.0, right_end - right_start)))
    if overlap / shorter >= 0.55:
        return True
    return abs(left_start - right_start) <= 0.12 and abs(left_end - right_end) <= 0.2


def _normalize_colloquial_price_tokens(text: str) -> str:
    def replace_price(match: re.Match[str]) -> str:
        integer = _normalize_numeric_token(match.group("integer"))
        fraction = _normalize_numeric_token(match.group("fraction"))
        if not integer or not fraction:
            return match.group(0)
        return f"{integer}块{fraction}"

    return _COLLOQUIAL_PRICE_RE.sub(replace_price, text)


def _normalize_decimal_quantity_tokens(text: str) -> str:
    def replace_decimal(match: re.Match[str]) -> str:
        integer = _normalize_numeric_token(match.group("integer"))
        fraction = _normalize_digit_sequence_token(match.group("fraction"))
        unit = str(match.group("unit") or "")
        if not integer or not fraction:
            return match.group(0)
        return f"{integer}.{fraction}{unit}"

    return _DECIMAL_NUMBER_RE.sub(replace_decimal, text)


def _normalize_spaced_model_tokens(text: str) -> str:
    def replace_model(match: re.Match[str]) -> str:
        letters = re.sub(r"\s+", "", str(match.group("letters") or "")).upper()
        number = _normalize_numeric_token(match.group("number"))
        suffix = re.sub(r"\s+", "", str(match.group("suffix") or ""))
        if not letters or not number:
            return match.group(0)
        suffix_text = suffix.lower() if suffix else ""
        return f"{letters}{number}{suffix_text}"

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
        return f"{prefix}{hour}点半" if hour else match.group(0)

    def replace_time_hour_only(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        return f"{prefix}{hour}点" if hour else match.group(0)

    result = _TIME_HALF_RE.sub(replace_time_half, text)
    result = _TIME_WITH_MINUTE_RE.sub(replace_time_with_minute, result)
    result = _TIME_HOUR_ONLY_RE.sub(replace_time_hour_only, result)
    return result


def _normalize_chinese_digit_sequences(text: str) -> str:
    def replace_sequence(match: re.Match[str]) -> str:
        raw_number = str(match.group("number") or "")
        if raw_number in _VAGUE_NUMBER_TOKENS:
            return raw_number
        if len(raw_number) == 2 and not any(char in raw_number for char in "零〇幺"):
            return raw_number
        return _normalize_numeric_token(raw_number) or raw_number

    return _CHINESE_DIGIT_SEQUENCE_RE.sub(replace_sequence, text)


def _normalize_default_chinese_number_tokens(text: str) -> str:
    def replace_number(match: re.Match[str]) -> str:
        raw_number = str(match.group("number") or "")
        tail_text = match.string[match.end():match.end() + 8]
        local_text = match.string[match.start():match.end() + 8]
        if any(local_text.startswith(idiom) for idiom in _DEFAULT_CHINESE_NUMBER_IDIOMS):
            return raw_number
        if _is_vague_number_phrase(raw_number) and _starts_with_any_unit(tail_text, _VAGUE_NUMBER_CONTEXT_UNITS):
            return raw_number
        if not _default_chinese_number_tail_allows_arabic(tail_text):
            return raw_number
        return _normalize_numeric_token(raw_number) or raw_number

    return _DEFAULT_CHINESE_NUMBER_RE.sub(replace_number, text)


def _normalize_spoken_digit_runs(text: str) -> str:
    def replace_sequence(match: re.Match[str]) -> str:
        raw_number = str(match.group("number") or "")
        return _normalize_digit_sequence_token(raw_number) or raw_number

    return _SPOKEN_DIGIT_RUN_RE.sub(replace_sequence, text)


def _is_vague_number_phrase(text: str) -> bool:
    value = str(text or "").strip()
    if value in _VAGUE_NUMBER_TOKENS:
        return True
    return bool(re.fullmatch(r"[一二两三四五六七八九]{2}[十百千万]", value))


def _starts_with_any_unit(text: str, units: set[str]) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return any(value.startswith(unit) for unit in sorted(units, key=len, reverse=True))


def _default_chinese_number_tail_allows_arabic(text: str) -> bool:
    value = str(text or "")
    if value and value[0].isspace():
        return True
    stripped = value.lstrip()
    if not stripped:
        return True
    if stripped[0] in "，,。.!！？；;：:、)]）】}」』":
        return True
    if _starts_with_any_unit(stripped, set(_DISPLAY_QUANTITY_UNITS) | set(_DISPLAY_ORDINAL_UNITS)):
        return True
    allowed_prefixes = (
        "了",
        "的",
        "啊",
        "呀",
        "嘛",
        "呢",
        "吧",
        "呗",
        "哦",
        "欸",
        "哎",
        "时候",
        "这种",
        "这个",
        "那个",
        "这些",
        "那些",
        "我",
        "你",
        "他",
        "她",
        "它",
        "咱",
        "和",
        "跟",
        "与",
        "对比",
        "上",
        "下",
        "里",
        "外",
        "都",
        "也",
        "就",
        "是",
        "有",
        "用",
        "带",
        "换",
        "买",
        "卖",
        "要",
        "给",
        "到",
        "比",
        "更",
        "还",
        "从",
        "没",
        "不",
        "能",
        "会",
        "可以",
        "应该",
        "可能",
        "很",
        "挺",
        "蛮",
        "真",
        "确实",
        "已经",
        "基本",
        "比较",
        "非常",
        "特别",
        "直接",
        "反正",
        "其实",
        "然后",
        "但是",
        "不过",
        "所以",
        "如果",
        "因为",
        "就是",
        "感觉",
        "看",
        "拿",
        "放",
        "装",
        "做",
        "说",
        "讲",
        "来",
        "去",
    )
    return stripped.startswith(allowed_prefixes)


def _format_natural_single_quantity(number_token: str, normalized_number: str, unit: str, tail_text: str) -> str:
    if unit not in _NATURAL_SINGLE_QUANTITY_UNITS:
        return ""
    if unit == "个" and _starts_with_info_count_noun(tail_text):
        return ""
    if unit == "块" and re.match(r"^\d", str(tail_text or "")):
        return ""
    display_number = _NATURAL_SINGLE_DIGIT_DISPLAY.get(str(normalized_number or ""))
    if not display_number:
        return ""
    raw_number = str(number_token or "").strip()
    if raw_number == "二":
        display_number = "二"
    return f"{display_number}{unit}"


def _range_should_use_natural_chinese(start_token: str, end_token: str, unit: str, tail_text: str) -> bool:
    start_number = _normalize_numeric_token(start_token)
    end_number = _normalize_numeric_token(end_token)
    if not start_number or not end_number:
        return False
    if not (start_number.isdigit() and end_number.isdigit()):
        return False
    if int(start_number) > 9 or int(end_number) > 9:
        return False
    if unit == "个" and _starts_with_info_count_noun(tail_text):
        return False
    return unit in _NATURAL_SINGLE_QUANTITY_UNITS


def _format_natural_number(normalized_number: str, *, raw_number: str = "") -> str:
    if str(raw_number or "").strip() == "二":
        return "二"
    return _NATURAL_SINGLE_DIGIT_DISPLAY.get(str(normalized_number or ""), str(normalized_number or ""))


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


def _normalize_digit_sequence_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return value
    if value.isdigit():
        return value
    if re.fullmatch(r"[零〇幺一二两三四五六七八九]+", value):
        return "".join(str(_CHINESE_DIGIT_VALUES[char]) for char in value)
    return _normalize_numeric_token(value)


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
    global_words = _flatten_segment_words(segments)
    global_word_segmentation_used = len(global_words) >= 2
    if global_word_segmentation_used:
        entries = _segment_subtitles_from_global_words(
            segments,
            max_chars=max_chars,
            max_duration=max_duration,
        )
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
    merged = _merge_short_chain_entries(merged, max_chars=max_chars, max_duration=max_duration)
    merged = _merge_same_source_segment_micro_fragments(merged, max_chars=max_chars, max_duration=max_duration)
    rebalanced = _rebalance_semantic_boundaries(merged, max_chars=max_chars, max_duration=max_duration)
    resolved = _merge_continuation_entries(rebalanced, max_chars=max_chars, max_duration=max_duration)
    resolved = _merge_short_chain_entries(resolved, max_chars=max_chars, max_duration=max_duration)
    resolved = _merge_same_source_segment_micro_fragments(resolved, max_chars=max_chars, max_duration=max_duration)
    if allow_window_refine:
        resolved = _refine_low_confidence_windows(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_continuation_entries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_short_chain_entries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_same_source_segment_micro_fragments(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _rebalance_semantic_boundaries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_continuation_entries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_short_chain_entries(resolved, max_chars=max_chars, max_duration=max_duration)
        resolved = _merge_same_source_segment_micro_fragments(resolved, max_chars=max_chars, max_duration=max_duration)
    resolved = _split_readability_overflow_entries(
        resolved,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    resolved = _repair_post_readability_split_fragments(
        resolved,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    return _cleanup_subtitle_entries(resolved)


def analyze_subtitle_segmentation(entries: list[SubtitleEntry]) -> SubtitleSegmentationAnalysis:
    if not entries:
        return SubtitleSegmentationAnalysis(
            entry_count=0,
            fragment_start_count=0,
            fragment_end_count=0,
            protected_term_split_count=0,
            generic_word_split_count=0,
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
    generic_word_split_count = 0
    suspicious_boundary_count = 0
    consecutive_fragment_window_count = 0
    inside_suspicious_window = False

    for left, right in zip(entries, entries[1:]):
        assessment = _assess_subtitle_boundary(left.text_raw, right.text_raw)
        tags = list(assessment.damage_flags)
        score = assessment.quality
        if "attached_fragment_start" in assessment.damage_flags:
            fragment_start_count += 1
        elif "soft_attached_fragment_start" in assessment.damage_flags:
            if "soft_fragment_start" not in tags:
                tags.append("soft_fragment_start")
            fragment_start_count += 1
        if "measure_phrase_split" in assessment.damage_flags:
            fragment_start_count += 1
        if assessment.left_incomplete:
            if "incomplete_left" not in tags:
                tags.append("incomplete_left")
        elif "soft_fragmentary_tail" in assessment.damage_flags and "soft_incomplete_left" not in tags:
            tags.append("soft_incomplete_left")
        if "protected_term" in assessment.damage_flags:
            if "protected_term_split" not in tags:
                tags.append("protected_term_split")
            protected_term_split_count += 1
        if "generic_word" in assessment.damage_flags:
            if "generic_word_split" not in tags:
                tags.append("generic_word_split")
            generic_word_split_count += 1
        if score <= -1.5:
            if "low_boundary_score" not in tags:
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
        generic_word_split_count=generic_word_split_count,
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
        segment_start = float(getattr(seg, "start_time", 0.0) or 0.0)
        segment_end = float(getattr(seg, "end_time", segment_start) or segment_start)
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
                    "segment_start": segment_start,
                    "segment_end": segment_end,
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
    boundary_assessment = _assess_subtitle_boundary(text, next_preview) if next_preview else None
    if boundary_assessment is not None and boundary_assessment.forbidden:
        return None
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

    text_core = _strip_boundary_trailing_punctuation(text) or text
    boundary_quality = boundary_assessment.quality if boundary_assessment is not None else 4.0
    score += boundary_quality * 4.5
    if boundary_assessment is not None:
        score -= _sum_boundary_flag_weights(boundary_assessment.damage_flags, _BOUNDARY_WORD_CANDIDATE_DAMAGE_WEIGHTS)
    if (
        len(text) > max_chars
        and len(text) <= max_chars + 6
        and duration <= _semantic_hold_duration_limit(
            text_length=len(text),
            max_chars=max_chars,
            max_duration=max_duration,
        )
        and boundary_quality >= 1.5
        and not _has_detached_trailing_clause_fragment(text)
    ):
        score += min(len(text) - max_chars, 6) * 4.0

    if gap_after >= 0.25:
        score += min(gap_after, 1.5) * (6.0 if boundary_quality >= 0 else -3.0)
    if max_internal_gap >= 0.45:
        score -= min(max_internal_gap, 1.5) * (5.0 if len(text) > max_chars else 3.0)
    if previous_preview and _starts_with_attached_fragment(text):
        score -= 10.0
    if next_preview and _has_detached_trailing_clause_fragment(text):
        score -= 32.0
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
        assessment = _assess_subtitle_boundary(left, right)
        if assessment.forbidden:
            continue
        duration = float(words[index - 1]["end"]) - float(words[0]["start"])
        overflow_penalty = max(0.0, duration - max_duration) * 8.0
        score = _score_break_boundary(left, right, index=len(left), target=target) - overflow_penalty
        boundary_quality = assessment.quality
        pause_after = max(0.0, float(words[index].get("start", 0.0) or 0.0) - float(words[index - 1].get("end", 0.0) or 0.0))
        if pause_after >= 0.25:
            score += min(pause_after, 1.2) * (6.0 if boundary_quality >= 0 else -4.0)
        if len(right) <= 4 and boundary_quality < 0:
            score -= 12
        if "measure_phrase_split" in assessment.damage_flags:
            score -= 18
        if "nominal_phrase" in assessment.damage_flags:
            score -= 12
        if "predicate_phrase" in assessment.damage_flags:
            score -= 14
        if "model_token" in assessment.damage_flags:
            score -= 16
        if "compound_term" in assessment.damage_flags:
            score -= 10
        if "soft_attached_fragment_start" in assessment.damage_flags:
            score -= 6
        if "soft_fragmentary_tail" in assessment.damage_flags:
            score -= 6
        if len(left) > max_chars + 2:
            score -= (len(left) - max_chars) * 6
        if score > best_score:
            best_score = score
            best_index = index
    return max(1, min(best_index, len(words) - 1))


def _soft_readability_char_limit(max_chars: int) -> int:
    if max_chars <= 12:
        return max_chars
    return min(max_chars, max(14, int(max_chars * 0.62)))


def _soft_readability_duration_limit(max_duration: float) -> float:
    return min(max_duration, max(3.2, max_duration * 0.72))


def _entry_exceeds_readability_soft_limit(
    entry: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    text = str(entry.text_raw or "").strip()
    if not text or max_chars <= 12:
        return False
    duration = max(0.0, float(entry.end) - float(entry.start))
    soft_char_limit = _soft_readability_char_limit(max_chars)
    soft_duration_limit = _soft_readability_duration_limit(max_duration)
    return len(text) > soft_char_limit or duration > soft_duration_limit


def _entry_requires_readability_split(
    entry: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    text = str(entry.text_raw or "").strip()
    if not text or max_chars <= 12:
        return False
    duration = max(0.0, float(entry.end) - float(entry.start))
    if duration <= 0.0:
        return False

    text_length = len(text)
    char_overflow = max(0, text_length - max_chars)
    duration_overflow = max(0.0, duration - max_duration)
    if _entry_can_keep_mild_semantic_overflow(entry, max_chars=max_chars, max_duration=max_duration):
        return False
    if char_overflow > 0:
        return True
    if duration_overflow > 0.0:
        if text_length >= max(max_chars - 2, 16):
            return True
        if duration_overflow >= 1.0:
            return True

    soft_char_limit = _soft_readability_char_limit(max_chars)
    soft_duration_limit = _soft_readability_duration_limit(max_duration)
    soft_char_overflow = max(0, text_length - soft_char_limit)
    soft_duration_overflow = max(0.0, duration - soft_duration_limit)
    if soft_char_overflow >= 4:
        return True
    if soft_duration_overflow >= 0.8 and text_length > max(soft_char_limit - 2, 10):
        return True
    return False


def _choose_readability_split_index(
    words: list[dict],
    *,
    max_chars: int,
    max_duration: float,
    entry_text: str | None = None,
    entry_duration: float | None = None,
) -> int | None:
    if len(words) <= 1 or max_chars <= 12:
        return None

    total_text = str(entry_text or _words_to_text(words))
    if not total_text:
        return None
    if entry_duration is None:
        total_duration = max(
            0.0,
            float(words[-1].get("end", 0.0) or 0.0) - float(words[0].get("start", 0.0) or 0.0),
        )
    else:
        total_duration = max(0.0, float(entry_duration))
    hard_overflow = len(total_text) > max_chars or total_duration > max_duration
    char_hard_overflow = len(total_text) > max_chars
    fallback_hard_overflow = len(total_text) <= max_chars and total_duration > (max_duration + 0.6)

    target = max(8, min(len(total_text) - 1, int(len(total_text) * 0.5)))
    best_index: int | None = None
    best_score = float("-inf")
    best_hard_overflow_index: int | None = None
    best_hard_overflow_score = float("-inf")
    min_side_chars = max(4, min(8, max_chars // 4))
    soft_char_limit = _soft_readability_char_limit(max_chars)
    soft_duration_limit = _soft_readability_duration_limit(max_duration)

    for index in range(1, len(words)):
        left_words = words[:index]
        right_words = words[index:]
        left = _words_to_text(left_words)
        right = _words_to_text(right_words)
        if not left or not right:
            continue
        detachable_lead_in = _looks_like_detachable_lead_in(left)
        if (len(left) < min_side_chars and not detachable_lead_in) or len(right) < min_side_chars:
            continue
        if _is_forbidden_subtitle_boundary(left, right):
            continue

        pause_after = max(
            0.0,
            float(right_words[0].get("start", 0.0) or 0.0)
            - float(left_words[-1].get("end", 0.0) or 0.0),
        )
        boundary_quality = _semantic_boundary_quality(left, right)
        boundary_score = _score_break_boundary(left, right, index=len(left), target=target)
        if pause_after < 0.18 and boundary_quality < 1.0 and boundary_score < 0.0 and not fallback_hard_overflow:
            continue

        attached_fragment = _starts_with_attached_fragment(right)
        soft_attached_fragment = _starts_with_soft_attached_fragment(right)
        soft_fragmentary_tail = _looks_like_soft_fragmentary_tail(left)
        right_incomplete = _is_incomplete_subtitle_text(right)

        left_duration = max(
            0.0,
            float(left_words[-1].get("end", 0.0) or 0.0)
            - float(left_words[0].get("start", 0.0) or 0.0),
        )
        right_duration = max(
            0.0,
            float(right_words[-1].get("end", 0.0) or 0.0)
            - float(right_words[0].get("start", 0.0) or 0.0),
        )

        # Readability overflow should not peel a sentence-initial filler/lead-in
        # into its own row when the remaining clause is still the substantive line.
        if detachable_lead_in:
            if len(right) >= max(min_side_chars + 2, soft_char_limit - 2):
                continue
            if right_duration >= max(2.8, soft_duration_limit - 0.4):
                continue

        score = boundary_score
        score += pause_after * 24.0
        score += boundary_quality * 4.0
        score -= abs(len(left) - len(right)) * 0.8
        if detachable_lead_in:
            score += 6.0
        if attached_fragment:
            score -= 10.0 if pause_after < 0.25 else 2.0
        if soft_attached_fragment:
            score -= 8.0 if pause_after < 0.25 else 1.5
        if soft_fragmentary_tail:
            score -= 10.0 if pause_after < 0.25 else 2.0
        if len(left) > soft_char_limit:
            score -= (len(left) - soft_char_limit) * 6.0
        if len(right) > soft_char_limit:
            score -= (len(right) - soft_char_limit) * 6.0
        if left_duration > soft_duration_limit:
            score -= (left_duration - soft_duration_limit) * 8.0
        if right_duration > soft_duration_limit:
            score -= (right_duration - soft_duration_limit) * 8.0
        if (
            pause_after >= 0.32
            and len(left) >= max(8, soft_char_limit - 6)
            and len(right) >= max(8, soft_char_limit - 8)
            and left_duration >= 1.0
            and right_duration >= 1.0
            and not attached_fragment
            and not soft_attached_fragment
            and not right_incomplete
        ):
            pause_supported_score = 8.0 + pause_after * 12.0 - abs(len(left) - len(right)) * 0.35
            if soft_fragmentary_tail:
                pause_supported_score += 2.0
            score = max(score, pause_supported_score)

        if score > best_score:
            best_score = score
            best_index = index

        fallback_score = float("-inf")
        if not attached_fragment and not soft_attached_fragment:
            left_incomplete = _is_incomplete_subtitle_text(left)
            right_attached = _starts_with_attached_fragment(right)
            left_text = str(left or "").strip()
            left_clause_closed = bool(left_text) and left_text[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
            left_overflow = max(0, len(left) - max_chars)
            right_overflow = max(0, len(right) - max_chars)
            left_duration_overflow = max(0.0, left_duration - max_duration)
            right_duration_overflow = max(0.0, right_duration - max_duration)
            fallback_score = 0.0
            fallback_score -= (left_overflow + right_overflow) * 18.0
            fallback_score -= (left_duration_overflow + right_duration_overflow) * 24.0
            fallback_score -= abs(len(left) - len(right)) * 0.35
            fallback_score += pause_after * 12.0
            fallback_score += min(boundary_quality, 3.0) * 2.0
            if not left_incomplete or left_clause_closed:
                fallback_score += 18.0
            if left_text:
                if left_text[-1] in _HARD_BREAK_CHARS:
                    fallback_score += 22.0
                elif left_text[-1] in _SOFT_BREAK_CHARS:
                    fallback_score += 14.0
            if any(str(right or "").startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
                fallback_score += 8.0
            if left_incomplete and not left_clause_closed:
                fallback_score -= 18.0
            if right_attached:
                fallback_score -= 24.0

        if fallback_score > best_hard_overflow_score:
            best_hard_overflow_score = fallback_score
            best_hard_overflow_index = index

    if best_index is None:
        punctuation_fallback_index = _choose_punctuation_supported_readability_split_index(
            words,
            max_chars=max_chars,
            max_duration=max_duration,
            entry_text=total_text,
            entry_duration=total_duration,
        )
        if punctuation_fallback_index is not None:
            return punctuation_fallback_index
        if char_hard_overflow and best_hard_overflow_index is not None and best_hard_overflow_score >= 8.0:
            return best_hard_overflow_index
        if fallback_hard_overflow and best_hard_overflow_index is not None and best_hard_overflow_score >= 0.0:
            return best_hard_overflow_index
        return None
    if hard_overflow and best_score < -6.0:
        punctuation_fallback_index = _choose_punctuation_supported_readability_split_index(
            words,
            max_chars=max_chars,
            max_duration=max_duration,
            entry_text=total_text,
            entry_duration=total_duration,
        )
        if punctuation_fallback_index is not None:
            return punctuation_fallback_index
    if best_score < 0.0 and not hard_overflow:
        return None
    if char_hard_overflow and best_score < -6.0 and best_hard_overflow_index is not None and best_hard_overflow_score >= 8.0:
        return best_hard_overflow_index
    if fallback_hard_overflow and best_score < -6.0 and best_hard_overflow_index is not None and best_hard_overflow_score >= 0.0:
        return best_hard_overflow_index
    if best_score < -6.0:
        return None
    return best_index


def _choose_punctuation_supported_readability_split_index(
    words: list[dict],
    *,
    max_chars: int,
    max_duration: float,
    entry_text: str | None = None,
    entry_duration: float | None = None,
) -> int | None:
    if len(words) <= 1:
        return None
    total_text = str(entry_text or _words_to_text(words))
    if not total_text or len(total_text) <= max_chars:
        return None
    total_duration = max(
        0.0,
        float(entry_duration)
        if entry_duration is not None
        else float(words[-1].get("end", 0.0) or 0.0) - float(words[0].get("start", 0.0) or 0.0),
    )
    if total_duration <= max_duration:
        return None

    target = max(8, min(len(total_text) - 1, int(len(total_text) * 0.5)))
    min_side_chars = max(4, min(8, max_chars // 4))
    best_index: int | None = None
    best_score = float("-inf")

    for index in range(1, len(words)):
        left = _words_to_text(words[:index])
        right = _words_to_text(words[index:])
        if not left or not right:
            continue
        left_core = _strip_boundary_trailing_punctuation(left)
        right_core = _strip_boundary_leading_particles(right) or right
        if len(left_core) < min_side_chars or len(right_core) < min_side_chars:
            continue
        if _is_forbidden_subtitle_boundary(left, right):
            continue
        if _starts_with_attached_fragment(right) or _starts_with_soft_attached_fragment(right):
            continue
        if not str(left or "").strip().endswith(tuple(_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)):
            continue
        left_duration = max(
            0.0,
            float(words[index - 1].get("end", 0.0) or 0.0) - float(words[0].get("start", 0.0) or 0.0),
        )
        right_duration = max(
            0.0,
            float(words[-1].get("end", 0.0) or 0.0) - float(words[index].get("start", 0.0) or 0.0),
        )
        if left_duration > max_duration + 0.8 or right_duration > max_duration + 0.8:
            continue
        score = 20.0
        score -= abs(len(left) - target) * 0.9
        score -= abs(len(right) - (len(total_text) - target)) * 0.6
        if any(right_core.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
            score += 6.0
        score += max(0.0, _semantic_boundary_quality(left, right)) * 2.0
        if score > best_score:
            best_score = score
            best_index = index

    return best_index


def _split_readability_overflow_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if not entries or max_chars <= 12:
        return entries

    split_entries: list[SubtitleEntry] = []
    for entry in entries:
        queue = [entry]
        while queue:
            current = queue.pop(0)
            words = list(current.words or ())
            if (
                len(words) < 2
                or not _entry_requires_readability_split(
                    current,
                    max_chars=max_chars,
                    max_duration=max_duration,
                )
            ):
                split_entries.append(current)
                continue

            split_index = _choose_readability_split_index(
                words,
                max_chars=max_chars,
                max_duration=max_duration,
                entry_text=current.text_raw,
                entry_duration=float(current.end) - float(current.start),
            )
            if split_index is None:
                split_entries.append(current)
                continue

            left_words = words[:split_index]
            right_words = words[split_index:]
            left_text = _words_to_text(left_words)
            right_text = _words_to_text(right_words)
            if not left_text or not right_text:
                split_entries.append(current)
                continue

            total_text = str(current.text_raw or "").strip()
            total_duration = max(0.0, float(current.end) - float(current.start))
            char_overflow = max(0, len(total_text) - max_chars)
            duration_overflow = max(0.0, total_duration - max_duration)
            mild_overflow = char_overflow <= 6 and duration_overflow <= 1.4
            left_short_residual = (
                len(str(left_text).strip()) <= 8
                and (
                    _is_incomplete_subtitle_text(left_text)
                    or _looks_like_short_followon_clause_fragment(left_text)
                    or _looks_like_soft_fragmentary_tail(left_text)
                )
            )
            right_short_residual = (
                len(str(right_text).strip()) <= 8
                and (
                    _is_incomplete_subtitle_text(right_text)
                    or _looks_like_short_followon_clause_fragment(right_text)
                    or _looks_like_soft_fragmentary_tail(right_text)
                )
            )
            if mild_overflow and (left_short_residual or right_short_residual):
                split_entries.append(current)
                continue

            queue = [
                _make_subtitle_entry(
                    current.index,
                    float(left_words[0]["start"]),
                    float(left_words[-1]["end"]),
                    left_text,
                    words=left_words,
                ),
                _make_subtitle_entry(
                    current.index,
                    float(right_words[0]["start"]),
                    float(right_words[-1]["end"]),
                    right_text,
                    words=right_words,
                ),
                *queue,
            ]
    return _reindex_subtitle_entries(split_entries)


def _repair_post_readability_split_fragments(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    repaired: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        current_text = str(current.text_raw or "").strip()
        if not _looks_like_short_followon_clause_fragment(current_text):
            repaired.append(current)
            index += 1
            continue

        if index + 1 < len(entries):
            following = entries[index + 1]
            following_text = str(following.text_raw or "").strip()
            gap = max(0.0, float(following.start) - float(current.end))
            combined_text = f"{current_text}{following_text}"
            combined_duration = max(0.0, float(following.end) - float(current.start))
            if (
                following_text
                and gap <= 0.18
                and len(combined_text) <= max_chars + 4
                and combined_duration <= max_duration + 1.4
            ):
                repaired.append(
                    _make_subtitle_entry(
                        len(repaired),
                        current.start,
                        following.end,
                        combined_text,
                        words=tuple(current.words or ()) + tuple(following.words or ()),
                    )
                )
                index += 2
                continue

        if repaired:
            previous = repaired[-1]
            previous_text = str(previous.text_raw or "").strip()
            gap = max(0.0, float(current.start) - float(previous.end))
            combined_text = f"{previous_text}{current_text}"
            combined_duration = max(0.0, float(current.end) - float(previous.start))
            if (
                previous_text
                and previous_text[-1] not in _HARD_BREAK_CHARS
                and gap <= 0.18
                and len(combined_text) <= max_chars + 4
                and combined_duration <= max_duration + 1.0
            ):
                repaired[-1] = _make_subtitle_entry(
                    len(repaired) - 1,
                    previous.start,
                    current.end,
                    combined_text,
                    words=tuple(previous.words or ()) + tuple(current.words or ()),
                )
                index += 1
                continue

        repaired.append(current)
        index += 1
    return _reindex_subtitle_entries(repaired)


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
    if _boundary_splits_numeric_unit(left_text, right_text):
        return True
    return bool(_SPLIT_MEASURE_LEFT_RE.search(left_text) and _SPLIT_MEASURE_RIGHT_RE.match(right_text))


def _boundary_splits_numeric_unit(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left)
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    right_text = re.sub(r"^[，。！？、：；,.!?\s]+", "", right_text)
    if not left_text or not right_text:
        return False
    return bool(
        _NUMERIC_MEASURE_LEFT_RE.search(left_text)
        and (_NUMERIC_MEASURE_RIGHT_RE.match(right_text) or _NUMERIC_APPROX_RIGHT_RE.match(right_text))
    )


def _boundary_starts_with_suffix_particle_continuation(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left)
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if str(left or "").strip()[-1:] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]$", left_text):
        return False
    return bool(re.match(r"^(?:的|了|得|地|着|过)(?:了|的)?[\u4e00-\u9fffA-Za-z0-9]", right_text))


def _sum_boundary_flag_weights(flags: tuple[str, ...] | set[str], weights: dict[str, float]) -> float:
    return sum(float(weights.get(flag, 0.0)) for flag in flags)


def _collect_boundary_damage_flags(left_text: str, right_text: str, *, left_core: str | None = None) -> set[str]:
    flags: set[str] = set()
    if not left_text or not right_text:
        return flags
    normalized_left_core = left_core or (_strip_boundary_trailing_punctuation(left_text) or left_text)
    clause_closed_particle_tail = _is_clause_closed_particle_tail(left_text)
    if _boundary_splits_numeric_unit(left_text, right_text):
        flags.add("numeric_unit")
    if _boundary_splits_model_token(left_text, right_text):
        flags.add("model_token")
    if _boundary_splits_compound_term(left_text, right_text):
        flags.add("compound_term")
    if _boundary_splits_protected_term(left_text, right_text):
        flags.add("protected_term")
    if _boundary_splits_generic_word(left_text, right_text):
        flags.add("generic_word")
    if _boundary_splits_nominal_phrase(left_text, right_text):
        flags.add("nominal_phrase")
    if _boundary_splits_bare_determiner_phrase(left_text, right_text):
        flags.add("bare_determiner_phrase")
    if _boundary_splits_pronoun_modifier_phrase(left_text, right_text):
        flags.add("pronoun_modifier_phrase")
    if _boundary_splits_predicate_phrase(left_text, right_text):
        flags.add("predicate_phrase")
    if _boundary_splits_reason_preamble(left_text, right_text):
        flags.add("reason_preamble")
    if _boundary_splits_subject_clause_restart(left_text, right_text):
        flags.add("subject_clause_restart")
    if _boundary_splits_demonstrative_modifier_phrase(left_text, right_text):
        flags.add("demonstrative_modifier_phrase")
    if _boundary_splits_classifier_noun_phrase(left_text, right_text):
        flags.add("classifier_noun_phrase")
    if _boundary_starts_with_suffix_particle_continuation(left_text, right_text):
        flags.add("suffix_particle_continuation")
    if _boundary_splits_repeated_model_suffix(left_text, right_text):
        flags.add("repeated_model_suffix")
    if _boundary_splits_honor_transition_phrase(left_text, right_text):
        flags.add("honor_transition_phrase")
    if _boundary_splits_possessive_phrase(left_text, right_text):
        flags.add("possessive_phrase")
    if _boundary_splits_single_char_residual(left_text, right_text):
        flags.add("single_char_residual")
    if _starts_with_attached_fragment(right_text):
        flags.add("attached_fragment_start")
    elif _starts_with_soft_attached_fragment(right_text):
        flags.add("soft_attached_fragment_start")
    if _looks_like_split_measure_phrase(normalized_left_core, right_text):
        flags.add("measure_phrase_split")
    if not clause_closed_particle_tail and any(normalized_left_core.endswith(token) for token in _NO_SPLIT_ENDINGS):
        flags.add("no_split_ending")
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        flags.add("no_split_prefix")
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        flags.add("leading_punctuation")
    if not clause_closed_particle_tail and _looks_like_soft_fragmentary_tail(normalized_left_core):
        flags.add("soft_fragmentary_tail")
    if len(right_text) <= 2:
        flags.add("short_right")
    return flags


def _collect_boundary_positive_flags(left_text: str, right_text: str, *, left_incomplete: bool) -> set[str]:
    flags: set[str] = set()
    if not left_text or not right_text:
        return flags
    last_char = left_text[-1]
    if last_char in _HARD_BREAK_CHARS:
        flags.add("hard_break_incomplete" if left_incomplete else "hard_break_closed")
    elif last_char in _SOFT_BREAK_CHARS:
        flags.add("soft_break_incomplete" if left_incomplete else "soft_break_closed")
    if any(right_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        flags.add("good_break_prefix")
    return flags


def _assess_subtitle_boundary(left: str, right: str) -> BoundaryAssessment:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return BoundaryAssessment(
            left_text=left_text,
            right_text=right_text,
            left_core=_strip_boundary_trailing_punctuation(left_text) or left_text,
            quality=-100.0,
            damage_flags=(),
            positive_flags=(),
            forbidden=False,
            left_incomplete=False,
        )

    left_core = _strip_boundary_trailing_punctuation(left_text) or left_text
    left_incomplete = _is_incomplete_subtitle_text(left_text)
    damage_flags = _collect_boundary_damage_flags(left_text, right_text, left_core=left_core)
    positive_flags = _collect_boundary_positive_flags(left_text, right_text, left_incomplete=left_incomplete)
    quality = 0.0
    if left_incomplete:
        quality -= 5.0
    quality -= _sum_boundary_flag_weights(tuple(sorted(damage_flags)), _BOUNDARY_SEMANTIC_DAMAGE_WEIGHTS)
    quality += _sum_boundary_flag_weights(tuple(sorted(positive_flags)), _BOUNDARY_SEMANTIC_POSITIVE_WEIGHTS)
    if left_incomplete and "short_right" in damage_flags:
        quality -= 3.0

    return BoundaryAssessment(
        left_text=left_text,
        right_text=right_text,
        left_core=left_core,
        quality=quality,
        damage_flags=tuple(sorted(damage_flags)),
        positive_flags=tuple(sorted(positive_flags)),
        forbidden=bool(damage_flags & _BOUNDARY_FORBIDDEN_DAMAGE_FLAGS),
        left_incomplete=left_incomplete,
    )


def _is_forbidden_subtitle_boundary(left: str, right: str) -> bool:
    return _assess_subtitle_boundary(left, right).forbidden


def _boundary_damage_flags(left: str, right: str) -> set[str]:
    assessment = _assess_subtitle_boundary(left, right)
    return set(assessment.damage_flags)


def _boundary_transfer_introduces_new_damage(
    original_left: str,
    original_right: str,
    new_left: str,
    new_right: str,
    *,
    allowed_damage: frozenset[str] | set[str] = frozenset(),
) -> bool:
    original_flags = _boundary_damage_flags(original_left, original_right)
    new_flags = _boundary_damage_flags(new_left, new_right)
    return bool((new_flags - original_flags) - set(allowed_damage))


def _is_strong_fragment_boundary(left: str, right: str, *, gap: float) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    assessment = _assess_subtitle_boundary(left_text, right_text)
    damage_flags = set(assessment.damage_flags)
    if _looks_like_particle_led_sentence_restart(right_text) and not (
        {"measure_phrase_split", "predicate_phrase", "honor_transition_phrase", "possessive_phrase", "compound_term"}
        & damage_flags
    ):
        return False
    if assessment.forbidden:
        return True
    if {"measure_phrase_split", "predicate_phrase", "repeated_model_suffix", "honor_transition_phrase", "possessive_phrase", "single_char_residual"} & damage_flags:
        return True
    return gap <= 0.05 and len(left_text) <= 5 and assessment.quality <= -2.5


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
        limit += 1.8
    if gap <= 0.05:
        limit += 0.8
    elif gap <= 0.4:
        limit += 0.4
    if text_length <= max_chars + 2:
        limit += 0.6
    return min(_MAX_SEMANTIC_BRIDGE_DURATION_SEC, limit)


def _left_has_explicit_clause_break(text: str) -> bool:
    candidate = str(text or "").strip()
    return bool(candidate) and candidate[-1] in _CLAUSE_PUNCTUATION


def _is_clause_closed_particle_tail(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or candidate[-1] not in _CLAUSE_PUNCTUATION:
        return False
    core = _strip_boundary_trailing_punctuation(candidate) or candidate
    return any(core.endswith(token) for token in _CLAUSE_CLOSED_PARTICLE_ENDINGS)


def _is_incomplete_subtitle_text(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    core = _strip_boundary_trailing_punctuation(candidate) or candidate
    if re.search(r"[A-Za-z]{2,8}$", core):
        return True
    if _is_clause_closed_particle_tail(candidate):
        return False
    if any(core.endswith(token) for token in _SOFT_FRAGMENTARY_ENDINGS):
        return True
    if _looks_like_unclosed_nominal_tail(core):
        return True
    if any(core.endswith(token) for token in _PREDICATE_CONTINUATION_ENDINGS):
        return True
    if any(core.endswith(token) for token in _NO_SPLIT_ENDINGS):
        return True
    return bool(re.search(r"(?:得很|会有|还有|没有|以及|为了|对于|因为|如果|或者|还是|就是|不是)$", core))


def _looks_like_unclosed_nominal_tail(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    core = _strip_boundary_trailing_punctuation(candidate) or candidate
    return bool(_UNCLOSED_NOMINAL_TAIL_RE.search(core))


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
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    return _looks_like_unclosed_nominal_tail(left_text) and _starts_with_nominal_head(right_text)


def _boundary_splits_predicate_phrase(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if not any(left_text.endswith(token) for token in _PREDICATE_CONTINUATION_ENDINGS):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    if any(left_text.endswith(token) for token in _PREDICATE_OBJECT_CONTINUATION_ENDINGS):
        if (
            _starts_with_nominal_head(stripped_right)
            or _boundary_splits_protected_term(left_text, stripped_right)
            or _boundary_splits_bare_determiner_phrase(left_text, stripped_right)
            or _boundary_splits_pronoun_modifier_phrase(left_text, stripped_right)
        ):
            return True
    return any(stripped_right.startswith(prefix) for prefix in _PREDICATE_CONTINUATION_PREFIXES)


def _boundary_splits_reason_preamble(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if not any(left_text.endswith(token) for token in _REASON_PREAMBLE_ENDINGS):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    if left_text.endswith("为什么"):
        for token in sorted(_SUBJECT_LED_CLAUSE_HEAD_TOKENS, key=len, reverse=True):
            if not stripped_right.startswith(token):
                continue
            rest = _strip_boundary_leading_particles(stripped_right[len(token):]) or stripped_right[len(token):]
            if any(rest.startswith(prefix) for prefix in _REASON_PREAMBLE_PREFIXES):
                return True
    return any(stripped_right.startswith(prefix) for prefix in _REASON_PREAMBLE_PREFIXES)


def _boundary_splits_subject_clause_restart(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _left_has_explicit_clause_break(str(left or "").strip()):
        return False
    if not any(left_text.endswith(token) for token in _SUBJECT_CLAUSE_RESTART_TAILS):
        return False
    return any(right_text.startswith(prefix) for prefix in _SUBJECT_CLAUSE_RESTART_PREFIXES)


def _boundary_splits_demonstrative_modifier_phrase(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _left_has_explicit_clause_break(str(left or "").strip()):
        return False
    compact_left = _SEGMENTATION_COMPACT_PUNCT_RE.sub("", left_text)
    if len(compact_left) < 2 or len(compact_left) > 8:
        return False
    return any(right_text.startswith(prefix) for prefix in _DEMONSTRATIVE_MODIFIER_PREFIXES)


def _boundary_splits_classifier_noun_phrase(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _left_has_explicit_clause_break(str(left or "").strip()):
        return False
    if not re.search(r"(?:一个|这个|那个|这把|那把|这款|那款|这种|那种)[\u4e00-\u9fffA-Za-z0-9]{1,4}$", left_text):
        return False
    return _starts_with_nominal_head(right_text)


def _boundary_splits_bare_determiner_phrase(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if not re.search(r"(?:这|那|该)$", left_text):
        return False
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    return bool(_NOMINAL_HEAD_RE.match(stripped_right))


def _boundary_splits_pronoun_modifier_phrase(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left) or str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if not any(left_text.endswith(token) for token in ("它", "他", "她", "这个", "那个")):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    return bool(
        re.match(r"^(?:前头|后头|上头|里头|这头|那头|前面|后面|上面|里面|一个|一种|一款)", stripped_right)
    )


def _semantic_boundary_quality(left: str, right: str) -> float:
    return _assess_subtitle_boundary(left, right).quality


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

    current_assessment = _assess_subtitle_boundary(left.text_raw, right.text_raw)
    current_damage_flags = set(current_assessment.damage_flags)
    right_words = list(right.words or ())
    if len(right_words) <= 1:
        return left, right
    left_words = list(left.words or ())
    trailing_word = _words_to_text(left_words[-1:]) if left_words else ""
    leading_word = _words_to_text(right_words[:1])
    current_quality = current_assessment.quality
    if current_assessment.forbidden:
        return left, right
    if (
        current_quality > -2.5
        and len(leading_word) > 1
        and not bool(current_damage_flags & (_BOUNDARY_WORD_CONTINUATION_FLAGS | _BOUNDARY_FORBIDDEN_DAMAGE_FLAGS))
        and not _prefix_begins_subject_led_clause(trailing_word, right.text_raw)
        and not _prefix_begins_adverb_led_clause(trailing_word, right.text_raw)
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
        if (
            left.text_raw[-1] in _CLAUSE_PUNCTUATION
            and (
                _prefix_begins_subject_led_clause(prefix_text, suffix_text)
                or _prefix_begins_adverb_led_clause(prefix_text, suffix_text)
            )
            and not (
                _boundary_splits_protected_term(left.text_raw, right.text_raw)
                or _boundary_splits_generic_word(left.text_raw, right.text_raw)
                or _boundary_splits_compound_term(left.text_raw, right.text_raw)
            )
        ):
            continue

        expanded_left_words = tuple(left.words or ()) + tuple(prefix_words)
        new_left_text = _words_to_text(list(expanded_left_words)) or f"{left.text_raw}{prefix_text}"
        if len(new_left_text) > max_chars + (8 if len(prefix_text) <= 4 else 6):
            continue
        if _boundary_transfer_introduces_new_damage(
            left.text_raw,
            right.text_raw,
            new_left_text,
            suffix_text,
            allowed_damage=frozenset({"no_split_ending"}),
        ):
            continue

        new_left_duration = float(prefix_words[-1]["end"]) - float(left.start)
        if new_left_duration > _semantic_hold_duration_limit(
            text_length=len(new_left_text),
            max_chars=max_chars,
            max_duration=max_duration,
        ):
            continue

        new_assessment = _assess_subtitle_boundary(new_left_text, suffix_text)
        new_damage_flags = set(new_assessment.damage_flags)
        new_quality = new_assessment.quality
        improvement = new_quality - current_quality
        if _is_incomplete_subtitle_text(left.text_raw) and not _is_incomplete_subtitle_text(new_left_text):
            improvement += 4.0
        if "attached_fragment_start" in current_damage_flags and "attached_fragment_start" not in new_damage_flags:
            improvement += 6.0
        if "soft_attached_fragment_start" in current_damage_flags and "soft_attached_fragment_start" not in new_damage_flags:
            improvement += 4.0
        if "no_split_prefix" in current_damage_flags and "no_split_prefix" not in new_damage_flags:
            improvement += 4.0
        if "no_split_ending" in current_damage_flags and "no_split_ending" not in new_damage_flags:
            improvement += 3.5
        if "compound_term" in current_damage_flags and "compound_term" not in new_damage_flags:
            improvement += 4.0
        if "protected_term" in current_damage_flags and "protected_term" not in new_damage_flags:
            improvement += 4.0
        if "generic_word" in current_damage_flags and "generic_word" not in new_damage_flags:
            improvement += 5.0
        if "suffix_particle_continuation" in current_damage_flags and "suffix_particle_continuation" not in new_damage_flags:
            improvement += 8.0
        if "reason_preamble" in current_damage_flags and "reason_preamble" not in new_damage_flags:
            improvement += 7.0
        if _looks_like_short_detached_clause_fragment(prefix_text):
            improvement += 3.0
        if _looks_like_soft_fragmentary_tail(right.text_raw) and not _looks_like_soft_fragmentary_tail(suffix_text):
            improvement += 2.5
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
        if "attached_fragment_start" in current_damage_flags:
            required_improvement -= 1.0
        if "soft_attached_fragment_start" in current_damage_flags:
            required_improvement -= 0.8
        if "no_split_prefix" in current_damage_flags:
            required_improvement -= 0.8
        if gap >= 0.8 and len(prefix_text) <= 4:
            required_improvement -= 0.5
        if "compound_term" in current_damage_flags:
            required_improvement -= 0.8
        if "measure_phrase_split" in current_damage_flags:
            required_improvement -= 0.8
        if "suffix_particle_continuation" in current_damage_flags:
            required_improvement -= 1.2
        if "reason_preamble" in current_damage_flags:
            required_improvement -= 1.0
        if _looks_like_short_detached_clause_fragment(prefix_text):
            required_improvement -= 0.8
        if _looks_like_soft_fragmentary_tail(right.text_raw):
            required_improvement -= 0.6

        if improvement < max(2.0, required_improvement):
            continue

        new_left = _make_subtitle_entry(
            left.index,
            left.start,
            float(prefix_words[-1]["end"]),
            new_left_text,
            words=expanded_left_words,
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

    max_suffix_words = min(max(len(left_words) - 1, 0), _MAX_SEMANTIC_TRANSFER_WORDS)
    for suffix_count in range(1, max_suffix_words + 1):
        kept_left_words = left_words[:-suffix_count]
        moved_words = left_words[-suffix_count:]
        if not kept_left_words or not moved_words:
            continue

        moved_text = _words_to_text(moved_words)
        new_left_text = _words_to_text(kept_left_words)
        new_right_words = moved_words + right_words
        new_right_text = _words_to_text(new_right_words)
        if not moved_text or not new_left_text or not new_right_text:
            continue
        if len(moved_text) > _MAX_SEMANTIC_TRANSFER_CHARS:
            break
        if _boundary_transfer_introduces_new_damage(
            left.text_raw,
            right.text_raw,
            new_left_text,
            new_right_text,
            allowed_damage=frozenset({"no_split_ending"}),
        ):
            continue
        if len(new_right_text) > max_chars + (8 if len(moved_text) <= 4 else 6):
            continue

        new_right_duration = float(right.end) - float(moved_words[0]["start"])
        if new_right_duration > _semantic_hold_duration_limit(
            text_length=len(new_right_text),
            max_chars=max_chars,
            max_duration=max_duration,
        ):
            continue

        new_assessment = _assess_subtitle_boundary(new_left_text, new_right_text)
        new_damage_flags = set(new_assessment.damage_flags)
        new_quality = new_assessment.quality
        improvement = new_quality - current_quality
        if _is_incomplete_subtitle_text(left.text_raw) and not _is_incomplete_subtitle_text(new_left_text):
            improvement += 4.0
        if "attached_fragment_start" in current_damage_flags and "attached_fragment_start" not in new_damage_flags:
            improvement += 6.0
        if "soft_attached_fragment_start" in current_damage_flags and "soft_attached_fragment_start" not in new_damage_flags:
            improvement += 4.0
        if "no_split_prefix" in current_damage_flags and "no_split_prefix" not in new_damage_flags:
            improvement += 4.0
        if "no_split_ending" in current_damage_flags and "no_split_ending" not in new_damage_flags:
            improvement += 3.5
        if "compound_term" in current_damage_flags and "compound_term" not in new_damage_flags:
            improvement += 5.0
        if "measure_phrase_split" in current_damage_flags and "measure_phrase_split" not in new_damage_flags:
            improvement += 5.0
        if "protected_term" in current_damage_flags and "protected_term" not in new_damage_flags:
            improvement += 4.0
        if "generic_word" in current_damage_flags and "generic_word" not in new_damage_flags:
            improvement += 5.0
        if "suffix_particle_continuation" in current_damage_flags and "suffix_particle_continuation" not in new_damage_flags:
            improvement += 8.0
        if "reason_preamble" in current_damage_flags and "reason_preamble" not in new_damage_flags:
            improvement += 7.0
        if _prefix_begins_subject_led_clause(moved_text, right.text_raw):
            improvement += 4.5
        if _prefix_begins_adverb_led_clause(moved_text, right.text_raw):
            improvement += 3.5
        if _looks_like_short_detached_clause_fragment(moved_text):
            improvement += 3.5
        if _looks_like_soft_fragmentary_tail(left.text_raw) and not _looks_like_soft_fragmentary_tail(new_left_text):
            improvement += 2.5
        if gap <= 0.05 and len(moved_text) <= 4:
            improvement += 1.6

        required_improvement = 3.0
        if _is_incomplete_subtitle_text(left.text_raw):
            required_improvement -= 0.9
        if "attached_fragment_start" in current_damage_flags:
            required_improvement -= 1.0
        if "soft_attached_fragment_start" in current_damage_flags:
            required_improvement -= 0.8
        if "no_split_prefix" in current_damage_flags:
            required_improvement -= 0.8
        if "compound_term" in current_damage_flags:
            required_improvement -= 0.8
        if "measure_phrase_split" in current_damage_flags:
            required_improvement -= 1.0
        if "generic_word" in current_damage_flags:
            required_improvement -= 1.0
        if "suffix_particle_continuation" in current_damage_flags:
            required_improvement -= 1.2
        if "reason_preamble" in current_damage_flags:
            required_improvement -= 1.0
        if _prefix_begins_subject_led_clause(moved_text, right.text_raw):
            required_improvement -= 1.0
        if _prefix_begins_adverb_led_clause(moved_text, right.text_raw):
            required_improvement -= 0.8
        if _looks_like_short_detached_clause_fragment(moved_text):
            required_improvement -= 0.8
        if _looks_like_soft_fragmentary_tail(left.text_raw):
            required_improvement -= 0.6

        if improvement < max(1.8, required_improvement):
            continue

        new_left = _make_subtitle_entry(
            left.index,
            left.start,
            float(kept_left_words[-1]["end"]),
            new_left_text,
            words=tuple(kept_left_words),
        )
        new_right = _make_subtitle_entry(
            right.index,
            float(moved_words[0]["start"]),
            right.end,
            new_right_text,
            words=tuple(new_right_words),
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

    assessment = _assess_subtitle_boundary(left.text_raw, right.text_raw)
    damage_flags = set(assessment.damage_flags)
    attached = "attached_fragment_start" in damage_flags
    incomplete = assessment.left_incomplete
    protected = "protected_term" in damage_flags
    generic_word_split = "generic_word" in damage_flags
    tiny_right = len(right.text_raw) <= 4
    strong_fragment_boundary = _is_strong_fragment_boundary(left.text_raw, right.text_raw, gap=gap)
    if not (assessment.forbidden or attached or incomplete or protected or generic_word_split or tiny_right or strong_fragment_boundary):
        return False
    if gap > 1.2 and not (assessment.forbidden or tiny_right or protected or generic_word_split or attached):
        return False
    if gap > 0.8 and not (assessment.forbidden or tiny_right or protected or generic_word_split or attached or (strong_fragment_boundary and incomplete)):
        return False
    if float(right.end) - float(left.start) > _fragmented_display_hold_duration_limit(
        text_length=len(combined_text),
        max_chars=max_chars,
        max_duration=max_duration,
        gap=gap,
        strong_fragment_boundary=strong_fragment_boundary,
    ):
        return False
    return assessment.forbidden or strong_fragment_boundary or assessment.quality <= -4.0


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
    assessment = _assess_subtitle_boundary(left, right)
    if not assessment.left_text or not assessment.right_text:
        return score - 100
    if assessment.forbidden:
        return score - 10000

    score += _sum_boundary_flag_weights(assessment.positive_flags, _BOUNDARY_BREAK_POSITIVE_WEIGHTS)
    score -= _sum_boundary_flag_weights(assessment.damage_flags, _BOUNDARY_BREAK_DAMAGE_WEIGHTS)
    score += assessment.quality * 4.0
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
        assessment = _assess_subtitle_boundary(prev.text_raw, entry.text_raw)
        damage_flags = set(assessment.damage_flags)
        combined_text = f"{prev.text_raw}{entry.text_raw}"
        combined_duration = float(entry.end) - float(prev.start)
        gap = max(0.0, float(entry.start) - float(prev.end))
        protected_boundary = "protected_term" in damage_flags
        measure_boundary = "measure_phrase_split" in damage_flags
        predicate_boundary = "predicate_phrase" in damage_flags
        bare_determiner_boundary = "bare_determiner_phrase" in damage_flags
        pronoun_modifier_boundary = "pronoun_modifier_phrase" in damage_flags
        honor_boundary = "honor_transition_phrase" in damage_flags
        possessive_boundary = "possessive_phrase" in damage_flags
        compound_boundary = "compound_term" in damage_flags
        prioritized_repair_boundary = (
            assessment.forbidden
            or
            protected_boundary
            or measure_boundary
            or predicate_boundary
            or bare_determiner_boundary
            or pronoun_modifier_boundary
            or honor_boundary
            or possessive_boundary
            or compound_boundary
        )
        fragment_boundary = _starts_with_attached_fragment(entry.text_raw)
        strong_fragment_boundary = _is_strong_fragment_boundary(prev.text_raw, entry.text_raw, gap=gap)
        overflow_chars = 0
        if fragment_boundary or strong_fragment_boundary:
            overflow_chars = max(overflow_chars, 2)
        if prioritized_repair_boundary:
            overflow_chars = max(overflow_chars, 4)
        if assessment.forbidden:
            overflow_chars = max(overflow_chars, 8)
        if protected_boundary:
            overflow_chars = max(overflow_chars, 6)
        allowed_chars = max_chars + overflow_chars

        duration_overflow = 0.0
        if fragment_boundary:
            duration_overflow = max(duration_overflow, 0.6)
        if strong_fragment_boundary:
            duration_overflow = max(duration_overflow, 0.8)
        if prioritized_repair_boundary:
            duration_overflow = max(duration_overflow, 1.2)
        if assessment.forbidden:
            duration_overflow = max(duration_overflow, 2.0)
        if protected_boundary:
            duration_overflow = max(duration_overflow, 1.8)
        allowed_duration = max_duration + duration_overflow
        if overflow_chars > 0 or duration_overflow > 0.0:
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
        collapsed_text = _collapse_exact_repeated_phrase(text_raw)
        if collapsed_text:
            text_raw = collapsed_text
        if cleaned:
            previous = cleaned[-1]
            gap = float(entry.start) - float(previous.end)
            if gap <= _MAX_SEMANTIC_BRIDGE_GAP_SEC:
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
            elif gap <= _MAX_SEMANTIC_BRIDGE_GAP_SEC:
                overlap = _shared_edge_overlap_text(previous.text_raw, text_raw, max_overlap=10)
                if overlap and 4 <= len(overlap) <= 10 and len(text_raw) >= len(overlap) + 2:
                    trimmed = text_raw[len(overlap):].lstrip("，。！？!?、：:；;,. ")
                    if len(trimmed) >= 2:
                        text_raw = trimmed
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
    collapsed = _merge_short_bridge_entries(_collapse_repeated_sequence_entries(cleaned))
    return _repair_cross_boundary_spoken_digit_runs(collapsed)


def _repair_cross_boundary_spoken_digit_runs(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    repaired: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        if index + 1 >= len(entries):
            repaired.append(current)
            break

        following = entries[index + 1]
        left_text = str(current.text_norm or current.text_raw or "").strip()
        right_text = str(following.text_norm or following.text_raw or "").strip()
        split_match = _split_spoken_digit_boundary(left_text, right_text)
        if split_match is None:
            repaired.append(current)
            index += 1
            continue

        left_prefix, normalized_digits, right_suffix = split_match
        repaired.append(
            SubtitleEntry(
                index=len(repaired),
                start=current.start,
                end=current.end,
                text_raw=current.text_raw,
                text_norm=normalize_text(f"{left_prefix}{normalized_digits}"),
                words=tuple(current.words or ()),
            )
        )
        if right_suffix.strip("，,。.!！？；;：: "):
            entries[index + 1] = SubtitleEntry(
                index=following.index,
                start=following.start,
                end=following.end,
                text_raw=following.text_raw,
                text_norm=normalize_text(right_suffix),
                words=tuple(following.words or ()),
            )
        else:
            index += 1
        index += 1
    return _reindex_subtitle_entries(repaired)


def _split_spoken_digit_boundary(left_text: str, right_text: str) -> tuple[str, str, str] | None:
    left_match = _SPLIT_SPOKEN_DIGIT_LEFT_RE.match(str(left_text or "").strip())
    right_match = _SPLIT_SPOKEN_DIGIT_RIGHT_RE.match(str(right_text or "").strip())
    if not left_match or not right_match:
        return None

    left_digits = str(left_match.group("digits") or "")
    right_digits = str(right_match.group("digits") or "")
    combined_digits = f"{left_digits}{right_digits}"
    if "幺" not in combined_digits:
        return None
    normalized_digits = _normalize_digit_sequence_token(combined_digits)
    if not normalized_digits or not normalized_digits.isdigit() or normalized_digits == combined_digits:
        return None
    return (
        str(left_match.group("prefix") or "").rstrip("，,。.!！？；;：: "),
        normalized_digits,
        str(right_match.group("suffix") or "").lstrip("，,。.!！？；;：: "),
    )


def _merge_short_chain_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    merged: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        consumed = False
        for window in (4, 3):
            if index + window > len(entries):
                continue
            group = entries[index:index + window]
            if any(float(group[pos + 1].start) - float(group[pos].end) > 0.08 for pos in range(len(group) - 1)):
                continue
            texts = [str(item.text_raw or "").strip() for item in group]
            if not all(texts):
                continue
            if any(len(text) > 6 for text in texts):
                continue
            if any(text[-1] in _HARD_BREAK_CHARS for text in texts[:-1]):
                continue
            combined_text = "".join(texts)
            if len(combined_text) > max_chars + 2:
                continue
            merged.append(
                _make_subtitle_entry(
                    len(merged),
                    group[0].start,
                    group[-1].end,
                    combined_text,
                    words=sum((tuple(item.words or ()) for item in group), ()),
                )
            )
            index += window
            consumed = True
            break
        if consumed:
            continue
        current = entries[index]
        current_text = str(current.text_raw or "").strip()
        stripped_current_text = _strip_boundary_trailing_punctuation(current_text)
        detachable_lead_in = (
            _looks_like_detachable_lead_in(current_text)
            or _looks_like_detachable_lead_in_chain_prefix(current_text)
        )
        short_followon_fragment = _looks_like_short_followon_clause_fragment(current_text)
        is_short_fragment = _is_short_subtitle_fragment(current_text) or bool(
            stripped_current_text
            and stripped_current_text != current_text
            and len(stripped_current_text) <= 2
        ) or detachable_lead_in or short_followon_fragment
        if is_short_fragment:
            best_direction: str | None = None
            best_gain = 0.0

            if merged and not detachable_lead_in:
                previous = merged[-1]
                previous_text = str(previous.text_raw or "").strip()
                left_gap = max(0.0, float(current.start) - float(previous.end))
                left_text = f"{previous_text}{current_text}"
                single_char_residual_left_merge = bool(
                    previous_text
                    and len(current_text) == 1
                    and _boundary_splits_single_char_residual(previous_text, current_text)
                )
                force_left_merge = bool(
                    previous_text
                    and (
                        _starts_with_attached_fragment(current_text)
                        or _starts_with_soft_attached_fragment(current_text)
                        or short_followon_fragment
                        or _boundary_splits_compound_term(previous_text, current_text)
                        or single_char_residual_left_merge
                        or _looks_like_soft_fragmentary_tail(previous_text)
                    )
                )
                if (
                    previous_text
                    and left_gap <= 0.18
                    and (
                        len(left_text)
                        <= max_chars + (4 if short_followon_fragment else 2)
                        or single_char_residual_left_merge
                    )
                    and previous_text[-1] not in _HARD_BREAK_CHARS
                ):
                    if force_left_merge:
                        best_direction = "left"
                        best_gain = max(best_gain, 999.0)
                    left_candidate = _make_subtitle_entry(
                        len(merged) - 1,
                        previous.start,
                        current.end,
                        left_text,
                        words=tuple(previous.words or ()) + tuple(current.words or ()),
                    )
                    left_gain = _score_entry_sequence(
                        [left_candidate],
                        max_chars=max_chars,
                        max_duration=max_duration,
                    ) - _score_entry_sequence(
                        [previous, current],
                        max_chars=max_chars,
                        max_duration=max_duration,
                    )
                    if left_gain > best_gain:
                        best_direction = "left"
                        best_gain = left_gain

            if index + 1 < len(entries):
                following = entries[index + 1]
                following_text = str(following.text_raw or "").strip()
                right_gap = max(0.0, float(following.start) - float(current.end))
                force_right_merge = bool(
                    stripped_current_text
                    and stripped_current_text != current_text
                    and len(stripped_current_text) <= 3
                    and (
                        _boundary_splits_compound_term(current_text, following_text)
                        or _starts_with_soft_attached_fragment(following_text)
                        or _starts_with_attached_fragment(following_text)
                    )
                ) or bool(detachable_lead_in and len(following_text) >= 8) or bool(
                    len(current_text) <= 4
                    and any(following_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
                    and current_text[-1] not in _HARD_BREAK_CHARS
                ) or bool(
                    short_followon_fragment
                    and following_text
                    and current_text[-1] not in _HARD_BREAK_CHARS
                )
                right_prefix = current_text if detachable_lead_in else (stripped_current_text if force_right_merge else current_text)
                right_text = f"{right_prefix}{following_text}"
                if (
                    following_text
                    and right_gap <= 0.18
                    and len(right_text) <= (max_chars + (4 if detachable_lead_in or short_followon_fragment else 2))
                    and (current_text[-1] not in _HARD_BREAK_CHARS or force_right_merge)
                ):
                    if force_right_merge:
                        best_direction = "right"
                        best_gain = max(best_gain, 999.0)
                    right_candidate = _make_subtitle_entry(
                        len(merged),
                        current.start,
                        following.end,
                        right_text,
                        words=tuple(current.words or ()) + tuple(following.words or ()),
                    )
                    right_gain = _score_entry_sequence(
                        [right_candidate],
                        max_chars=max_chars,
                        max_duration=max_duration,
                    ) - _score_entry_sequence(
                        [current, following],
                        max_chars=max_chars,
                        max_duration=max_duration,
                    )
                    if right_gain > best_gain:
                        best_direction = "right"
                        best_gain = right_gain

            if best_direction == "left":
                previous = merged[-1]
                merged[-1] = _make_subtitle_entry(
                    len(merged) - 1,
                    previous.start,
                    current.end,
                    f"{previous.text_raw}{current_text}",
                    words=tuple(previous.words or ()) + tuple(current.words or ()),
                )
                index += 1
                continue
            if best_direction == "right":
                following = entries[index + 1]
                merged.append(
                    _make_subtitle_entry(
                        len(merged),
                        current.start,
                        following.end,
                        right_text,
                        words=tuple(current.words or ()) + tuple(following.words or ()),
                    )
                )
                index += 2
                continue
        merged.append(
            SubtitleEntry(
                index=len(merged),
                start=current.start,
                end=current.end,
                text_raw=current.text_raw,
                text_norm=current.text_norm,
                words=tuple(current.words or ()),
            )
        )
        index += 1
    return merged


def _merge_same_source_segment_micro_fragments(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    merged: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        run = [current]
        current_segment_index = _single_source_segment_index(current)

        if current_segment_index is not None:
            next_index = index + 1
            while next_index < len(entries):
                candidate = entries[next_index]
                candidate_segment_index = _single_source_segment_index(candidate)
                gap = max(0.0, float(candidate.start) - float(run[-1].end))
                max_same_source_gap = 0.18
                if (
                    len(str(run[-1].text_raw or "").strip()) <= 6
                    or len(str(candidate.text_raw or "").strip()) <= 6
                ):
                    max_same_source_gap = 1.8
                if candidate_segment_index != current_segment_index or gap > max_same_source_gap:
                    break
                run.append(candidate)
                next_index += 1
            if len(run) == 2 and _should_merge_same_source_pair(run[0], run[1], max_chars=max_chars, max_duration=max_duration):
                merged_entry = _make_subtitle_entry(
                    len(merged),
                    run[0].start,
                    run[1].end,
                    f"{str(run[0].text_raw or '').strip()}{str(run[1].text_raw or '').strip()}",
                    words=tuple(run[0].words or ()) + tuple(run[1].words or ()),
                )
                if _boundary_splits_short_followon_clause(run[0].text_raw, run[1].text_raw):
                    merged.append(merged_entry)
                    index = next_index
                    continue
                if (
                    len(str(run[0].text_raw or "").strip()) <= 6
                    and _is_incomplete_subtitle_text(run[0].text_raw)
                    and not any(str(run[1].text_raw or "").startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
                ):
                    merged.append(merged_entry)
                    index = next_index
                    continue
                current_analysis = analyze_subtitle_segmentation(run)
                candidate_analysis = analyze_subtitle_segmentation([merged_entry])
                current_score = _score_entry_sequence(run, max_chars=max_chars, max_duration=max_duration)
                candidate_score = _score_entry_sequence([merged_entry], max_chars=max_chars, max_duration=max_duration)
                if _fragment_window_candidate_is_acceptable(
                    current_entries=run,
                    candidate_entries=[merged_entry],
                    current_score=current_score,
                    candidate_score=candidate_score,
                    current_analysis=current_analysis,
                    candidate_analysis=candidate_analysis,
                    max_chars=max_chars,
                    max_duration=max_duration,
                ):
                    merged.append(merged_entry)
                    index = next_index
                    continue
            if _should_compact_same_source_run(run, max_chars=max_chars, max_duration=max_duration):
                compacted = _compact_same_source_run(run, max_chars=max_chars, max_duration=max_duration)
                current_analysis = analyze_subtitle_segmentation(run)
                candidate_analysis = analyze_subtitle_segmentation(compacted)
                current_score = _score_entry_sequence(run, max_chars=max_chars, max_duration=max_duration)
                candidate_score = _score_entry_sequence(compacted, max_chars=max_chars, max_duration=max_duration)
                if _fragment_window_candidate_is_acceptable(
                    current_entries=run,
                    candidate_entries=compacted,
                    current_score=current_score,
                    candidate_score=candidate_score,
                    current_analysis=current_analysis,
                    candidate_analysis=candidate_analysis,
                    max_chars=max_chars,
                    max_duration=max_duration,
                ):
                    for entry in compacted:
                        merged.append(
                            SubtitleEntry(
                                index=len(merged),
                                start=entry.start,
                                end=entry.end,
                                text_raw=entry.text_raw,
                                text_norm=entry.text_norm,
                                words=tuple(entry.words or ()),
                            )
                        )
                    index = next_index
                    continue

        merged.append(
            SubtitleEntry(
                index=len(merged),
                start=current.start,
                end=current.end,
                text_raw=current.text_raw,
                text_norm=current.text_norm,
                words=tuple(current.words or ()),
            )
        )
        index += 1
    return merged


def _should_merge_same_source_pair(
    left: SubtitleEntry,
    right: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    left_text = str(left.text_raw or "").strip()
    right_text = str(right.text_raw or "").strip()
    if not left_text or not right_text:
        return False
    assessment = _assess_subtitle_boundary(left_text, right_text)
    damage_flags = set(assessment.damage_flags)
    gap = max(0.0, float(right.start) - float(left.end))
    if gap > 1.8:
        return False
    combined_text = f"{left_text}{right_text}"
    combined_duration = max(0.0, float(right.end) - float(left.start))
    repair_signal = (
        assessment.forbidden
        or "attached_fragment_start" in damage_flags
        or "soft_attached_fragment_start" in damage_flags
        or "soft_fragmentary_tail" in damage_flags
        or _boundary_splits_short_followon_clause(left_text, right_text)
        or "single_char_residual" in damage_flags
        or "predicate_phrase" in damage_flags
        or "compound_term" in damage_flags
        or "numeric_unit" in damage_flags
    )
    if not repair_signal:
        return False
    return len(combined_text) <= max_chars + 4 and combined_duration <= max(max_duration + 2.4, 6.5)


def _boundary_splits_short_followon_clause(left_text: str, right_text: str) -> bool:
    left_candidate = str(left_text or "").strip()
    right_candidate = str(right_text or "").strip()
    if not left_candidate or not right_candidate:
        return False
    if left_candidate[-1] not in tuple(_SOFT_BREAK_CHARS):
        return False
    right_core = _strip_boundary_leading_particles(right_candidate) or right_candidate
    right_core = _strip_boundary_trailing_punctuation(right_core)
    if not right_core or len(right_core) > 8:
        return False
    if _is_incomplete_subtitle_text(right_core):
        return False
    if any(right_core.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        return False
    if re.search(r"[A-Za-z0-9]{4,}", right_core):
        return False
    if right_candidate[-1] in tuple(_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return True
    return len(right_core) <= 5


def _merge_short_bridge_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    if len(entries) <= 1:
        return entries

    merged: list[SubtitleEntry] = []
    index = 0
    while index < len(entries):
        current = entries[index]
        if index + 1 < len(entries):
            following = entries[index + 1]
            candidate = str(current.text_raw or "").strip()
            following_text = str(following.text_raw or "").strip()
            gap = max(0.0, float(following.start) - float(current.end))
            if (
                gap <= 0.18
                and 1 <= len(candidate) <= 3
                and candidate[0] in _BOUNDARY_LEADING_PARTICLES
            ):
                if _looks_like_detachable_lead_in(candidate) and len(following_text) >= 10:
                    merged.append(
                        SubtitleEntry(
                            index=len(merged),
                            start=current.start,
                            end=current.end,
                            text_raw=current.text_raw,
                            text_norm=current.text_norm,
                            words=tuple(current.words or ()),
                        )
                    )
                    index += 1
                    continue
                combined_text = f"{candidate}{following.text_raw}"
                if len(combined_text) <= 24:
                    merged.append(
                        _make_subtitle_entry(
                            len(merged),
                            current.start,
                            following.end,
                            combined_text,
                            words=tuple(current.words or ()) + tuple(following.words or ()),
                        )
                    )
                    index += 2
                    continue
        merged.append(
            SubtitleEntry(
                index=len(merged),
                start=current.start,
                end=current.end,
                text_raw=current.text_raw,
                text_norm=current.text_norm,
                words=tuple(current.words or ()),
            )
        )
        index += 1
    return merged


def _is_low_confidence_boundary(left: SubtitleEntry, right: SubtitleEntry) -> bool:
    gap = max(0.0, float(right.start) - float(left.end))
    assessment = _assess_subtitle_boundary(left.text_raw, right.text_raw)
    damage_flags = set(assessment.damage_flags)
    if _looks_like_particle_led_sentence_restart(right.text_raw) and not (
        {"nominal_phrase", "protected_term", "generic_word", "measure_phrase_split", "compound_term"} & damage_flags
    ):
        return False
    if gap > _MAX_SEMANTIC_BRIDGE_GAP_SEC and not (
        assessment.forbidden
        or {"nominal_phrase", "protected_term", "generic_word", "measure_phrase_split", "compound_term", "attached_fragment_start"} & damage_flags
    ):
        return False
    score = assessment.quality
    if assessment.forbidden or score <= -1.5:
        return True
    if {"nominal_phrase", "protected_term", "generic_word", "measure_phrase_split", "compound_term", "predicate_phrase", "repeated_model_suffix", "honor_transition_phrase", "possessive_phrase"} & damage_flags:
        return True
    if gap <= _MAX_SEMANTIC_BRIDGE_GAP_SEC and _boundary_repeated_overlap_size(left.text_raw, right.text_raw, max_overlap=10) >= 4:
        return True
    if {"attached_fragment_start", "soft_attached_fragment_start", "soft_fragmentary_tail"} & damage_flags:
        return True
    if assessment.left_incomplete and not any(
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
    if (
        len(right.text_raw) <= 4
        and len(left.text_raw) >= 6
        and gap <= 0.18
        and score <= 0.0
        and _starts_with_nominal_head(right.text_raw)
        and left.text_raw[-1] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
    ):
        return True
    return False


def _is_dense_followon_boundary(left: SubtitleEntry, right: SubtitleEntry) -> bool:
    left_text = str(left.text_raw or "").strip()
    right_text = str(right.text_raw or "").strip()
    if not left_text or not right_text:
        return False
    assessment = _assess_subtitle_boundary(left_text, right_text)
    damage_flags = set(assessment.damage_flags)
    gap = max(0.0, float(right.start) - float(left.end))
    if gap > 0.18:
        return False
    if left_text[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        return False
    if any(right_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        return False
    if assessment.forbidden or {"attached_fragment_start", "soft_attached_fragment_start"} & damage_flags:
        return False
    if {"nominal_phrase", "protected_term", "generic_word", "measure_phrase_split", "predicate_phrase", "repeated_model_suffix", "honor_transition_phrase", "possessive_phrase", "compound_term"} & damage_flags:
        return False
    return True


def _collect_dense_followon_windows(entries: list[SubtitleEntry]) -> list[tuple[int, int]]:
    dense_boundaries = [
        index
        for index, (left, right) in enumerate(zip(entries, entries[1:]))
        if _is_dense_followon_boundary(left, right)
    ]
    if not dense_boundaries:
        return []

    windows: list[tuple[int, int]] = []
    group_start = group_end = dense_boundaries[0]
    for boundary_index in dense_boundaries[1:]:
        if boundary_index <= group_end + 1:
            group_end = boundary_index
            continue
        windows.extend(_materialize_dense_followon_windows(entries, group_start, group_end))
        group_start = group_end = boundary_index
    windows.extend(_materialize_dense_followon_windows(entries, group_start, group_end))
    return windows


def _materialize_dense_followon_windows(
    entries: list[SubtitleEntry],
    boundary_start: int,
    boundary_end: int,
) -> list[tuple[int, int]]:
    start = max(0, boundary_start - 1)
    end = min(len(entries) - 1, boundary_end + 1)
    candidate_entries = entries[start:end + 1]
    total_chars = sum(len(str(entry.text_raw or "").strip()) for entry in candidate_entries)
    total_duration = (
        max(0.0, float(candidate_entries[-1].end) - float(candidate_entries[0].start))
        if candidate_entries
        else 0.0
    )
    if (boundary_end - boundary_start + 1) < 2 and total_chars < 28 and total_duration < 4.8:
        return []

    windows: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        window_end = min(end, cursor + 4)
        if window_end - cursor >= 1:
            windows.append((cursor, window_end))
        if window_end >= end:
            break
        cursor += 3
    return windows


def _chunk_low_confidence_window(
    entries: list[SubtitleEntry],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    if start >= end:
        return [(start, end)]

    candidate_entries = entries[start:end + 1]
    focused_windows = _collect_residual_repair_focus_windows(entries, start, end)
    if focused_windows and len(candidate_entries) > 3:
        return focused_windows

    total_chars = sum(len(str(entry.text_raw or "").strip()) for entry in candidate_entries)
    if (
        len(candidate_entries) <= _LOW_CONFIDENCE_WINDOW_MAX_ENTRIES
        and total_chars <= _LOW_CONFIDENCE_WINDOW_MAX_CHARS
    ):
        return [(start, end)]

    chunked: list[tuple[int, int]] = []
    cursor = start
    while cursor <= end:
        chunk_end = cursor
        chunk_chars = 0
        while chunk_end <= end:
            next_len = len(str(entries[chunk_end].text_raw or "").strip())
            next_count = chunk_end - cursor + 1
            if next_count > _LOW_CONFIDENCE_WINDOW_MAX_ENTRIES:
                break
            if chunk_chars and chunk_chars + next_len > _LOW_CONFIDENCE_WINDOW_MAX_CHARS:
                break
            chunk_chars += next_len
            chunk_end += 1
        final_end = max(cursor, chunk_end - 1)
        if final_end == cursor and cursor < end:
            final_end = min(end, cursor + _LOW_CONFIDENCE_WINDOW_MAX_ENTRIES - 1)
        chunked.append((cursor, final_end))
        cursor = final_end + 1
    return chunked


def _collect_residual_repair_focus_windows(
    entries: list[SubtitleEntry],
    start: int,
    end: int,
) -> list[tuple[int, int]]:
    repair_indexes: list[int] = []
    for index in range(start, end + 1):
        current = entries[index]
        previous = entries[index - 1] if index > 0 else None
        following = entries[index + 1] if index + 1 < len(entries) else None
        if _entry_needs_residual_repair(
            previous=previous,
            current=current,
            following=following,
        ):
            repair_indexes.append(index)
    if not repair_indexes:
        return []

    windows: list[tuple[int, int]] = []
    for repair_index in repair_indexes:
        windows.append((max(start, repair_index - 1), min(end, repair_index + 1)))

    merged: list[tuple[int, int]] = []
    for window_start, window_end in windows:
        if not merged or window_start > merged[-1][1] + 1:
            merged.append((window_start, window_end))
            continue
        previous_start, previous_end = merged[-1]
        merged[-1] = (previous_start, max(previous_end, window_end))
    return merged


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
    windows.extend(_collect_dense_followon_windows(entries))

    merged_windows: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not merged_windows or start > merged_windows[-1][1]:
            merged_windows.append((start, end))
            continue
        previous_start, previous_end = merged_windows[-1]
        merged_windows[-1] = (previous_start, max(previous_end, end))
    chunked_windows: list[tuple[int, int]] = []
    for start, end in merged_windows:
        chunked_windows.extend(_chunk_low_confidence_window(entries, start, end))
    return chunked_windows


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
    previous_word_continuation = (
        previous is not None
        and 0.0 <= float(current.start) - float(previous.end) <= _MAX_SEMANTIC_BRIDGE_GAP_SEC
        and bool(_boundary_damage_flags(previous.text_raw, candidate) & _BOUNDARY_WORD_CONTINUATION_FLAGS)
        and not any(candidate.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
        and not re.match(r"^[，。！？、：；,.!?]", candidate)
    )
    if previous_word_continuation:
        return True
    if _looks_like_unclosed_nominal_tail(candidate):
        return True
    if _looks_like_short_detached_clause_fragment(candidate):
        previous_bad_boundary = (
            previous is not None
            and 0.0 <= float(current.start) - float(previous.end) <= _MAX_SEMANTIC_BRIDGE_GAP_SEC
            and _semantic_boundary_quality(previous.text_raw, candidate) <= -1.5
            and not any(candidate.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
        )
        following_bad_boundary = (
            following is not None
            and 0.0 <= float(following.start) - float(current.end) <= _MAX_SEMANTIC_BRIDGE_GAP_SEC
            and _semantic_boundary_quality(candidate, following.text_raw) <= -1.5
            and not any(following.text_raw.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES)
        )
        if previous_bad_boundary or following_bad_boundary:
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
    current_analysis = analyze_subtitle_segmentation(entries)
    candidate_entries = _resplit_fragment_window(entries, max_chars=max_chars, max_duration=max_duration)
    if not candidate_entries:
        return None

    candidate_score = _score_entry_sequence(candidate_entries, max_chars=max_chars, max_duration=max_duration)
    candidate_analysis = analyze_subtitle_segmentation(candidate_entries)
    if not _fragment_window_candidate_is_acceptable(
        current_entries=entries,
        candidate_entries=candidate_entries,
        current_score=current_score,
        candidate_score=candidate_score,
        current_analysis=current_analysis,
        candidate_analysis=candidate_analysis,
        max_chars=max_chars,
        max_duration=max_duration,
    ):
        return None
    return candidate_entries


def _resplit_fragment_window(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry] | None:
    def _build_deterministic_candidate() -> list[SubtitleEntry] | None:
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

    relaxed_max_chars = max_chars + 2
    relaxed_max_duration = max_duration + 0.5
    direct_candidate = _resolve_subtitle_entry_sequence(
        entries,
        max_chars=relaxed_max_chars,
        max_duration=relaxed_max_duration,
        allow_window_refine=False,
    )
    if direct_candidate:
        current_key = tuple(str(entry.text_raw or "").strip() for entry in entries)
        direct_key = tuple(str(entry.text_raw or "").strip() for entry in direct_candidate)
        if direct_key and direct_key != current_key:
            return _pick_best_fragment_window_candidate(
                entries,
                [direct_candidate],
                max_chars=max_chars,
                max_duration=max_duration,
            )
    deterministic_candidate = _build_deterministic_candidate()
    if deterministic_candidate and len(entries) > 2:
        return _pick_best_fragment_window_candidate(
            entries,
            [deterministic_candidate],
            max_chars=max_chars,
            max_duration=max_duration,
        )
    search_top_k = 30 if len(entries) <= 6 else 16
    searched_candidates = _search_fragment_window_segmentations(
        entries,
        max_chars=relaxed_max_chars,
        max_duration=relaxed_max_duration,
        top_k=search_top_k,
    )
    resolved_candidates: list[list[SubtitleEntry]] = []
    for searched_entries in searched_candidates:
        resolved = _resolve_subtitle_entry_sequence(
            searched_entries,
            max_chars=relaxed_max_chars,
            max_duration=relaxed_max_duration,
            allow_window_refine=False,
        )
        if resolved:
            resolved_candidates.append(resolved)

    if resolved_candidates:
        return _pick_best_fragment_window_candidate(
            entries,
            resolved_candidates,
            max_chars=max_chars,
            max_duration=max_duration,
        )

    if not deterministic_candidate:
        return None
    return _pick_best_fragment_window_candidate(
        entries,
        [deterministic_candidate],
        max_chars=max_chars,
        max_duration=max_duration,
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
    text = str(entry.text_raw or "").strip()
    score = 0.0
    score -= max(0, len(text) - max_chars) * 8.0
    score -= max(0.0, duration - max_duration) * 6.0
    if _starts_with_attached_fragment(text):
        score -= 14.0
    if _starts_with_soft_attached_fragment(text):
        score -= 6.0
    if _is_incomplete_subtitle_text(text):
        score -= 12.0
    if _looks_like_unclosed_nominal_tail(text):
        score -= 8.0
    if _looks_like_soft_fragmentary_tail(text):
        score -= 6.0
    if _is_short_subtitle_fragment(text):
        score -= 4.0
    if len(text) <= 2:
        score -= 5.0
    if max_chars > 12 and text:
        soft_char_limit = _soft_readability_char_limit(max_chars)
        soft_duration_limit = _soft_readability_duration_limit(max_duration)
        soft_char_overflow = max(0, len(text) - soft_char_limit)
        soft_duration_overflow = max(0.0, duration - soft_duration_limit)
        score -= soft_char_overflow * 4.0
        score -= soft_duration_overflow * 5.0
        if soft_char_overflow > 0 and soft_duration_overflow > 0.0:
            score -= 4.0
        if _entry_requires_readability_split(entry, max_chars=max_chars, max_duration=max_duration):
            score -= 6.0
    return score


def _score_boundary_pair(left: SubtitleEntry, right: SubtitleEntry) -> float:
    assessment = _assess_subtitle_boundary(left.text_raw, right.text_raw)
    if assessment.forbidden:
        return -10000.0
    score = assessment.quality * 5.0
    score -= _sum_boundary_flag_weights(assessment.damage_flags, _BOUNDARY_PAIR_DAMAGE_WEIGHTS)
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
    max_options_per_start = 10 if len(window_words) <= 24 else 8
    options_by_start: dict[int, list[tuple[int, SubtitleEntry, float]]] = {}
    for start_index in range(len(window_words)):
        options: list[tuple[int, SubtitleEntry, float]] = []
        for end_index in range(start_index + 1, len(window_words) + 1):
            candidate_words = window_words[start_index:end_index]
            text = _words_to_text(candidate_words)
            if not text:
                continue
            next_preview = _preview_words_text(window_words[end_index:end_index + 4])
            if next_preview and _is_forbidden_subtitle_boundary(text, next_preview):
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
        if len(options) > max_options_per_start:
            ranked_indexes = sorted(range(len(options)), key=lambda idx: options[idx][2], reverse=True)
            keep_indexes = set(ranked_indexes[:max_options_per_start])
            keep_indexes.add(0)
            keep_indexes.add(len(options) - 1)
            options = [option for idx, option in enumerate(options) if idx in keep_indexes]
        options_by_start[start_index] = options

    beam_width = 40 if len(window_words) <= 18 else 24
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
                    if _is_forbidden_subtitle_boundary(previous_entry.text_raw, new_entry.text_raw):
                        continue
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
        for window in (4, 3, 2):
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
        repeat_count = len(candidate) // unit_len
        if unit * repeat_count == candidate:
            if _looks_like_natural_emphasis_repetition(unit, repeat_count=repeat_count):
                return None
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


def _boundary_repeated_overlap_size(left: str, right: str, *, max_overlap: int = 8) -> int:
    left_text = str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return 0
    best = len(_shared_edge_overlap_text(left_text, right_text, max_overlap=max_overlap))
    trimmed_left = _BOUNDARY_TRAILING_BRIDGE_RE.sub("", left_text)
    if trimmed_left and trimmed_left != left_text:
        best = max(best, len(_shared_edge_overlap_text(trimmed_left, right_text, max_overlap=max_overlap)))
    return best


def _leading_repeated_prefix_text(text: str, *, max_unit: int = 6) -> str:
    candidate = str(text or "").strip()
    if len(candidate) < 4:
        return ""
    upper = min(max_unit, len(candidate) // 2)
    for size in range(upper, 1, -1):
        prefix = candidate[:size]
        if candidate.startswith(prefix * 2):
            tail = candidate[size * 2:]
            if _looks_like_natural_emphasis_repetition(prefix, repeat_count=2, tail=tail):
                continue
            return prefix
    return ""


def _looks_like_natural_emphasis_repetition(unit: str, *, repeat_count: int, tail: str = "") -> bool:
    phrase = str(unit or "").strip()
    remainder = str(tail or "").strip("，。！？!?、：:；;,. ")
    if not phrase or repeat_count < 2:
        return False
    combined = f"{phrase}{remainder}"
    if _EMPHASIS_REPEAT_CUE_RE.search(combined):
        return True
    if remainder:
        return False
    if repeat_count > 3:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", phrase):
        return False
    if _COUNTING_REPEAT_UNIT_RE.fullmatch(phrase):
        return False
    return True


def _should_merge_subtitle_pair(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    assessment = _assess_subtitle_boundary(left_text, right_text)
    damage_flags = set(assessment.damage_flags)
    if left_text[-1] in _HARD_BREAK_CHARS:
        return False
    if _looks_like_particle_led_sentence_restart(right_text) and not (
        assessment.forbidden
        or {"measure_phrase_split", "predicate_phrase", "honor_transition_phrase", "possessive_phrase", "compound_term", "nominal_phrase", "protected_term"} & damage_flags
    ):
        return False
    if assessment.forbidden:
        return True
    if "no_split_ending" in damage_flags:
        return True
    if "no_split_prefix" in damage_flags:
        return True
    if "predicate_phrase" in damage_flags:
        return True
    if "repeated_model_suffix" in damage_flags:
        return True
    if "honor_transition_phrase" in damage_flags:
        return True
    if "possessive_phrase" in damage_flags:
        return True
    if "single_char_residual" in damage_flags:
        return True
    if re.search(r"[A-Za-z]{2,8}$", left_text) and re.match(r"^[\u4e00-\u9fffA-Za-z0-9]", right_text):
        return True
    if (
        right_text[0] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and len(right_text) <= 4
        and len(left_text) >= len(right_text) + 2
        and (
            _starts_with_attached_fragment(right_text)
            or _starts_with_soft_attached_fragment(right_text)
            or _starts_with_nominal_head(right_text)
        )
    ):
        return True
    if "protected_term" in damage_flags:
        return True
    if "compound_term" in damage_flags:
        return True
    if "nominal_phrase" in damage_flags:
        return True
    if _boundary_repeated_overlap_size(left_text, right_text, max_overlap=8) >= 3:
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
    if _left_has_explicit_clause_break(left_text):
        return False
    for term in _BOUNDARY_PROTECTED_TERMS:
        for split_at in range(1, len(term)):
            if left_text.endswith(term[:split_at]) and right_text.startswith(term[split_at:]):
                return True
    return False


def _boundary_splits_generic_word(left: str, right: str) -> bool:
    if _left_has_explicit_clause_break(left):
        return False
    left_text = _strip_boundary_trailing_punctuation(left)
    right_text = str(right or "").strip()
    right_text = _strip_boundary_leading_particles(right_text) or right_text
    right_text = re.sub(r"^[，。！？、：；,.!?\s]+", "", right_text)
    if not left_text or not right_text:
        return False
    if not re.search(r"[\u4e00-\u9fffA-Za-z0-9]$", left_text):
        return False
    if not re.match(r"^[\u4e00-\u9fffA-Za-z0-9]", right_text):
        return False
    if _boundary_splits_protected_term(left_text, right_text):
        return True
    if _boundary_splits_model_token(left_text, right_text):
        return True
    if _boundary_splits_compound_term(left_text, right_text):
        return True
    if len(left_text) <= 3 and _boundary_splits_single_char_residual(left_text, right_text):
        return True
    if _boundary_splits_generic_chinese_word(left_text, right_text):
        return True
    return _boundary_splits_alnum_token(left_text, right_text)


def _boundary_splits_alnum_token(left: str, right: str) -> bool:
    if not re.search(r"[A-Za-z0-9]$", left or "") or not re.match(r"^[A-Za-z0-9]", right or ""):
        return False
    left_token = re.search(r"[A-Za-z0-9]{1,16}$", str(left or ""))
    right_token = re.match(r"[A-Za-z0-9]{1,16}", str(right or ""))
    if not left_token or not right_token:
        return False
    combined = f"{left_token.group(0)}{right_token.group(0)}"
    if len(combined) < 2:
        return False
    if len(left_token.group(0)) == 1 and len(right_token.group(0)) == 1 and combined.isdigit():
        return False
    return True


def _boundary_splits_generic_chinese_word(left: str, right: str) -> bool:
    if _boundary_splits_fallback_chinese_word(left, right):
        return True
    left_tail_match = re.search(r"[\u4e00-\u9fff]{1,8}$", str(left or ""))
    right_head_match = re.match(r"[\u4e00-\u9fff]{1,8}", str(right or ""))
    if not left_tail_match or not right_head_match:
        return False
    left_tail = left_tail_match.group(0)
    right_head = right_head_match.group(0)
    context = f"{left_tail}{right_head}"
    boundary = len(left_tail)
    if len(context) < 2:
        return False
    cursor = 0
    for token in tokenize_alignment_text(context):
        token = str(token or "")
        if not token:
            continue
        start = cursor
        end = cursor + len(token)
        cursor = end
        if not (start < boundary < end):
            continue
        if len(token) < 2 or not re.search(r"[\u4e00-\u9fff]{2,}", token):
            continue
        if token in _GOOD_BREAK_PREFIXES or token in _NO_SPLIT_ENDINGS or token in _NO_SPLIT_PREFIXES:
            continue
        if not _is_trusted_generic_boundary_token(token):
            continue
        return True
    if jieba is None:
        return False
    cursor = 0
    for token in jieba.lcut(context, HMM=True):
        token = str(token or "")
        if not token:
            continue
        start = cursor
        end = cursor + len(token)
        cursor = end
        if not (start < boundary < end):
            continue
        if len(token) < 2 or not re.search(r"[\u4e00-\u9fff]{2,}", token):
            continue
        if token in _GOOD_BREAK_PREFIXES or token in _NO_SPLIT_ENDINGS or token in _NO_SPLIT_PREFIXES:
            continue
        if not _is_trusted_generic_boundary_token(token):
            continue
        return True
    return False


def _is_trusted_generic_boundary_token(token: str) -> bool:
    normalized = str(token or "").strip()
    if len(normalized) < 2:
        return False
    if len(normalized) >= 3:
        return True
    return normalized in _FALLBACK_GENERIC_CJK_BOUNDARY_TERMS or normalized in _BOUNDARY_PROTECTED_TERMS


def _boundary_splits_fallback_chinese_word(left: str, right: str) -> bool:
    left_text = _strip_boundary_trailing_punctuation(left)
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    for term in _FALLBACK_GENERIC_CJK_BOUNDARY_TERMS:
        for split_at in range(1, len(term)):
            if left_text.endswith(term[:split_at]) and right_text.startswith(term[split_at:]):
                return True
    return False


def _boundary_splits_model_token(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _left_has_explicit_clause_break(left_text):
        return False
    if re.search(rf"[A-Za-z]{{2,8}}(?:{_DISPLAY_NUM_TOKEN})?$", left_text):
        return bool(re.match(rf"(?:{_DISPLAY_NUM_TOKEN}|[A-Za-z0-9]+)", right_text))
    if re.search(rf"[A-Za-z]{{1,8}}(?:{_DISPLAY_NUM_TOKEN}){{1,2}}$", left_text):
        return bool(re.match(rf"(?:{_DISPLAY_NUM_TOKEN}|\d+|[A-Za-z]+)", right_text))
    return False


def _boundary_splits_repeated_model_suffix(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if not re.match(rf"^(?:{_DISPLAY_NUM_TOKEN})(?:已经|已|退|退役|取代|来了|发布|上市|就|被)", right_text):
        return False
    return bool(
        re.search(
            rf"[A-Za-z]{{1,8}}(?:{_DISPLAY_NUM_TOKEN}){{2,3}}(?:啊|呀|呃|呢|嘛)?(?:{_DISPLAY_NUM_TOKEN})?$",
            left_text,
        )
    )


def _boundary_splits_honor_transition_phrase(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if re.search(r"(?:已经|已)$", left_text):
        return bool(re.match(r"^(?:荣誉|光荣)?(?:退役|取代)", right_text))
    if re.search(r"(?:荣誉|光荣)$", left_text):
        return bool(re.match(r"^(?:退役|取代)", right_text))
    if re.search(rf"[A-Za-z]{{1,8}}(?:{_DISPLAY_NUM_TOKEN}|\d){{1,4}}光荣$", left_text):
        return bool(re.match(r"^取代", right_text))
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


def _strip_boundary_trailing_punctuation(text: str) -> str:
    return str(text or "").strip().rstrip("，,。！？!?、：:；; ")


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


def _looks_like_detachable_lead_in_chain(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or candidate[-1] in _HARD_BREAK_CHARS:
        return False
    core = _strip_boundary_trailing_punctuation(candidate)
    if not core or len(core) > 10:
        return False
    if re.search(r"[A-Za-z0-9]{2,}", core):
        return False
    tokens = [part.strip() for part in re.split(r"[，,、：:；;\s]+", core) if part.strip()]
    if len(tokens) == 1:
        fallback_tokens = [str(token).strip() for token in tokenize_alignment_text(core) if str(token).strip()]
        if 2 <= len(fallback_tokens) <= 4:
            tokens = fallback_tokens
    if len(tokens) < 2 or len(tokens) > 4:
        return False
    return all(token in _DETACHABLE_LEAD_IN_CHAIN_TOKENS for token in tokens)


def _looks_like_detachable_lead_in_chain_prefix(text: str, *, max_tokens: int = 4) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    core = _strip_boundary_trailing_punctuation(candidate)
    if not core:
        return False
    tokens = [str(token).strip() for token in tokenize_alignment_text(core) if str(token).strip()]
    if len(tokens) < 2:
        return False
    for token_count in range(2, min(len(tokens), max_tokens) + 1):
        prefix_text = "".join(tokens[:token_count])
        if _looks_like_detachable_lead_in_chain(prefix_text):
            return True
    return False


def _looks_like_detachable_lead_in(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    if _looks_like_detachable_lead_in_chain(candidate):
        return True
    core = _strip_boundary_trailing_punctuation(candidate)
    if not core:
        return False
    if candidate[-1] in "，,、：:；;" and len(core) <= 6:
        if re.search(r"[A-Za-z0-9]{2,}", core):
            return False
        return True
    if len(core) > 4:
        return False
    return bool(
        re.fullmatch(
            r"(?:啊|呃|嗯|嗯啊|呃啊|然后啊|那么啊|但是呢|其实呢|所以呢|这儿|这玩意儿)",
            core,
        )
    )


def _suffix_after_last_hard_break(text: str) -> str:
    candidate = str(text or "").strip()
    if not candidate:
        return ""
    last_break = max(candidate.rfind(char) for char in _HARD_BREAK_CHARS)
    if last_break < 0 or last_break >= len(candidate) - 1:
        return ""
    return candidate[last_break + 1 :].strip()


def _has_detached_trailing_clause_fragment(text: str) -> bool:
    suffix = _suffix_after_last_hard_break(text)
    if not suffix or len(suffix) > 14:
        return False
    stripped_suffix = _strip_boundary_leading_particles(suffix) or suffix
    if len(stripped_suffix) <= 12 and _is_incomplete_subtitle_text(stripped_suffix):
        return True
    if (
        stripped_suffix != suffix
        and len(stripped_suffix) <= 8
        and stripped_suffix[-1] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and (
            any(stripped_suffix.startswith(token) for token in _SUBJECT_LED_CLAUSE_HEAD_TOKENS)
            or stripped_suffix.startswith(("其他", "这个", "那个"))
        )
    ):
        return True
    return bool(
        _looks_like_detachable_lead_in(suffix)
        or _looks_like_detachable_lead_in_chain(suffix)
        or _looks_like_short_followon_clause_fragment(suffix)
        or _looks_like_soft_fragmentary_tail(suffix)
    )


def _entry_can_keep_mild_semantic_overflow(
    entry: SubtitleEntry,
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    text = str(entry.text_raw or "").strip()
    if not text:
        return False
    duration = max(0.0, float(entry.end) - float(entry.start))
    char_overflow = max(0, len(text) - max_chars)
    duration_overflow = max(0.0, duration - max_duration)
    if char_overflow > 4 or duration_overflow > 1.0:
        return False
    if not _looks_like_detachable_lead_in_chain_prefix(text):
        return False
    return not _has_detached_trailing_clause_fragment(text)


def _looks_like_short_followon_clause_fragment(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or len(candidate) > 8:
        return False
    if re.search(r"[A-Za-z0-9]{2,}", candidate):
        return False

    stripped = _strip_boundary_leading_particles(candidate)
    core = stripped or candidate
    if not core or len(core) > 6:
        return False

    if _starts_with_attached_fragment(candidate) or _starts_with_soft_attached_fragment(candidate):
        return True
    if _looks_like_soft_fragmentary_tail(candidate):
        return True
    if candidate[-1] in _SOFT_BREAK_CHARS and any(marker in candidate for marker in ("呃", "嗯", "啊", "呢", "嘛")):
        return True
    token_count = len([token for token in tokenize_alignment_text(candidate) if str(token or "").strip()])
    if token_count >= 2 and candidate[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return True
    if stripped and stripped != candidate and candidate[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return True
    return False


def _strip_boundary_trailing_particles(text: str) -> str:
    result = _strip_boundary_trailing_punctuation(text)
    trimmed = _BOUNDARY_TRAILING_BRIDGE_RE.sub("", result).rstrip("，,。！？!?、：:；; ")
    return trimmed or result


def _looks_like_short_detached_clause_fragment(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or len(candidate) > 10:
        return False
    if re.search(r"[A-Za-z0-9]{2,}", candidate):
        return False
    stripped = _strip_boundary_leading_particles(candidate) or candidate
    core = _strip_boundary_trailing_particles(stripped)
    if not core or len(core) > 4:
        return False
    if _looks_like_detachable_lead_in(candidate):
        return True
    if _looks_like_short_followon_clause_fragment(candidate):
        return True
    return bool(re.search(r"[\u3400-\u9fff]", core))


def _starts_with_subject_led_clause(prefix_text: str, suffix_text: str) -> bool:
    prefix = _strip_boundary_trailing_particles(prefix_text)
    suffix = str(suffix_text or "").strip()
    if not prefix or not suffix:
        return False
    if prefix not in _SUBJECT_LED_CLAUSE_HEAD_TOKENS:
        return False
    stripped_suffix = _strip_boundary_leading_particles(suffix) or suffix
    return any(stripped_suffix.startswith(token) for token in _SUBJECT_LED_CLAUSE_CONTINUATION_PREFIXES)


def _prefix_begins_subject_led_clause(prefix_text: str, suffix_text: str) -> bool:
    combined = f"{str(prefix_text or '').strip()}{str(suffix_text or '').strip()}"
    for head in sorted(_SUBJECT_LED_CLAUSE_HEAD_TOKENS, key=len, reverse=True):
        if not combined.startswith(head):
            continue
        if _starts_with_subject_led_clause(head, combined[len(head):]):
            return True
    return False


def _prefix_begins_adverb_led_clause(prefix_text: str, suffix_text: str) -> bool:
    combined = f"{str(prefix_text or '').strip()}{str(suffix_text or '').strip()}"
    for head in sorted(_ADVERB_LED_CLAUSE_HEAD_TOKENS, key=len, reverse=True):
        if not combined.startswith(head):
            continue
        rest = _strip_boundary_leading_particles(combined[len(head):]) or combined[len(head):]
        if any(rest.startswith(token) for token in _ADVERB_LED_CLAUSE_CONTINUATION_PREFIXES):
            return True
    return False


def _is_short_subtitle_fragment(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate or len(candidate) > 4:
        return False
    if candidate[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\\-_/]{0,7}", candidate):
        return False
    if re.search(r"[A-Za-z0-9]", candidate):
        return False
    return True


def _single_source_segment_index(entry: SubtitleEntry) -> int | None:
    segment_indexes = {
        int(word.get("segment_index"))
        for word in tuple(entry.words or ())
        if word.get("segment_index") is not None
    }
    if len(segment_indexes) != 1:
        return None
    return next(iter(segment_indexes))


def _source_segment_span(entry: SubtitleEntry) -> tuple[float, float] | None:
    starts = [
        float(word.get("segment_start"))
        for word in tuple(entry.words or ())
        if word.get("segment_start") is not None
    ]
    ends = [
        float(word.get("segment_end"))
        for word in tuple(entry.words or ())
        if word.get("segment_end") is not None
    ]
    if not starts or not ends:
        return None
    return min(starts), max(ends)


def _should_compact_same_source_run(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    if len(entries) < 2:
        return False
    texts = [str(entry.text_raw or "").strip() for entry in entries]
    short_count = sum(1 for text in texts if len(text) <= 6)
    if len(entries) == 2:
        if not _should_merge_same_source_pair(entries[0], entries[1], max_chars=max_chars, max_duration=max_duration):
            return False
        combined_text = "".join(texts)
        if len(combined_text) > max_chars + 4:
            return False
    elif short_count < 2:
        return False
    if len(entries) > 2 and not any(len(text) <= 4 for text in texts):
        combined_text = "".join(texts)
        if len(combined_text) <= max_chars + 2:
            return False
    span = _source_segment_span(entries[0])
    if span is None:
        return False
    source_duration = max(0.0, span[1] - span[0])
    run_duration = max(0.0, float(entries[-1].end) - float(entries[0].start))
    return (
        len(entries) >= 4
        or source_duration >= max(10.0, max_duration + 4.0)
        or run_duration >= max_duration + 1.6
    )


def _compact_same_source_run(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if not entries:
        return []

    target_chars = min(max_chars, max(10, int(max_chars * 0.62)))
    soft_char_limit = max_chars + 4
    soft_duration_limit = max(max_duration + 2.4, 6.5)
    compacted: list[SubtitleEntry] = []
    bucket: list[SubtitleEntry] = []

    def _flush_bucket() -> None:
        nonlocal bucket
        if not bucket:
            return
        compacted.append(_merge_entry_bucket(bucket, index=len(compacted)))
        bucket = []

    for entry in entries:
        if not bucket:
            bucket = [entry]
            continue

        bucket_text = "".join(str(item.text_raw or "").strip() for item in bucket)
        candidate_text = f"{bucket_text}{str(entry.text_raw or '').strip()}"
        candidate_duration = max(0.0, float(entry.end) - float(bucket[0].start))
        if (
            len(bucket_text) >= max(8, target_chars - 4)
            and (len(candidate_text) > target_chars or candidate_duration > soft_duration_limit)
        ):
            _flush_bucket()
            bucket = [entry]
            continue
        if len(candidate_text) > soft_char_limit:
            _flush_bucket()
            bucket = [entry]
            continue
        bucket.append(entry)
        bucket_text = "".join(str(item.text_raw or "").strip() for item in bucket)
        bucket_duration = max(0.0, float(bucket[-1].end) - float(bucket[0].start))
        if len(bucket_text) >= target_chars or bucket_duration >= soft_duration_limit:
            _flush_bucket()

    _flush_bucket()
    if len(compacted) >= 2 and len(str(compacted[-1].text_raw or "").strip()) <= 6:
        previous = compacted[-2]
        current = compacted[-1]
        merged_text = f"{previous.text_raw}{current.text_raw}"
        merged_duration = max(0.0, float(current.end) - float(previous.start))
        if len(merged_text) <= soft_char_limit and merged_duration <= soft_duration_limit + 0.8:
            compacted[-2] = _make_subtitle_entry(
                previous.index,
                previous.start,
                current.end,
                merged_text,
                words=tuple(previous.words or ()) + tuple(current.words or ()),
            )
            compacted.pop()
    return _reindex_subtitle_entries(compacted)


def _merge_entry_bucket(entries: list[SubtitleEntry], *, index: int) -> SubtitleEntry:
    if len(entries) == 1:
        entry = entries[0]
        return _make_subtitle_entry(
            index,
            entry.start,
            entry.end,
            str(entry.text_raw or "").strip(),
            words=tuple(entry.words or ()),
        )
    return _make_subtitle_entry(
        index,
        entries[0].start,
        entries[-1].end,
        "".join(str(entry.text_raw or "").strip() for entry in entries),
        words=sum((tuple(entry.words or ()) for entry in entries), ()),
    )


def _boundary_splits_compound_term(left: str, right: str) -> bool:
    if _left_has_explicit_clause_break(left):
        return False
    left_text = _strip_boundary_trailing_punctuation(left)
    right_text = _strip_boundary_leading_particles(right) or str(right or "").strip()
    if not left_text or not right_text:
        return False
    if _boundary_splits_model_token(left_text, right_text):
        return True
    return any(left_text.endswith(prefix) and right_text.startswith(suffix) for prefix, suffix in _BOUNDARY_COMPOUND_SPLITS)


def _boundary_splits_single_char_residual(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    if not stripped_right:
        return False
    if any(stripped_right.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        return False
    if not re.search(r"[\u4e00-\u9fff]$", left_text):
        return False
    if not re.match(r"^[\u4e00-\u9fff]", stripped_right):
        return False
    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        return False

    left_tail_match = re.search(r"[\u4e00-\u9fff]{1,4}$", left_text)
    right_head_match = re.match(r"[\u4e00-\u9fff]{1,4}", stripped_right)
    if not left_tail_match or not right_head_match:
        return False

    left_tail = left_tail_match.group(0)
    right_head = right_head_match.group(0)
    boundary = len(left_tail)
    context = f"{left_tail}{right_head}"
    cursor = 0
    for token in tokenize_alignment_text(context):
        token = str(token or "")
        if not token:
            continue
        start = cursor
        end = cursor + len(token)
        cursor = end
        if start < boundary < end and len(token) >= 2:
            return True
    return False


def _boundary_splits_possessive_phrase(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text[-1] in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS):
        return False
    stripped_right = _strip_boundary_leading_particles(right_text) or right_text
    if not stripped_right.startswith("家的"):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]{1,12}$", left_text))


def _fragment_window_metrics(entries: list[SubtitleEntry]) -> tuple[int, int, int, int, int]:
    analysis = analyze_subtitle_segmentation(entries)
    fragment_count = int(analysis.fragment_start_count) + int(analysis.fragment_end_count)
    return (
        int(analysis.low_confidence_window_count),
        int(analysis.suspicious_boundary_count),
        int(analysis.protected_term_split_count),
        int(analysis.generic_word_split_count),
        fragment_count,
    )


def _fragment_window_improvement_score(
    current_analysis: SubtitleSegmentationAnalysis,
    candidate_analysis: SubtitleSegmentationAnalysis,
) -> float:
    current_fragment_count = int(current_analysis.fragment_start_count) + int(current_analysis.fragment_end_count)
    candidate_fragment_count = int(candidate_analysis.fragment_start_count) + int(candidate_analysis.fragment_end_count)
    score = 0.0
    score += (int(current_analysis.low_confidence_window_count) - int(candidate_analysis.low_confidence_window_count)) * 10.0
    score += (int(current_analysis.suspicious_boundary_count) - int(candidate_analysis.suspicious_boundary_count)) * 3.5
    score += (int(current_analysis.protected_term_split_count) - int(candidate_analysis.protected_term_split_count)) * 5.0
    score += (int(current_analysis.generic_word_split_count) - int(candidate_analysis.generic_word_split_count)) * 6.0
    score += (current_fragment_count - candidate_fragment_count) * 1.5
    return score


def _fragment_window_residual_entry_count(entries: list[SubtitleEntry]) -> int:
    count = 0
    for entry in entries:
        text = str(entry.text_raw or "").strip()
        if not text:
            continue
        if _is_short_subtitle_fragment(text):
            count += 1
            continue
        if len(text) <= 3 and (
            _starts_with_attached_fragment(text)
            or _starts_with_soft_attached_fragment(text)
            or _is_incomplete_subtitle_text(text)
        ):
            count += 1
            continue
        if len(text) <= 2 and _looks_like_soft_fragmentary_tail(text):
            count += 1
    return count


def _fragment_window_overlong_entry_count(entries: list[SubtitleEntry], *, max_chars: int) -> int:
    return sum(1 for entry in entries if len(str(entry.text_raw or "").strip()) > max_chars + 2)


def _fragment_window_readability_soft_overflow_count(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> int:
    return sum(
        1
        for entry in entries
        if _entry_exceeds_readability_soft_limit(entry, max_chars=max_chars, max_duration=max_duration)
    )


def _fragment_window_readability_soft_overflow_amount(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> float:
    if max_chars <= 12:
        return 0.0
    soft_char_limit = _soft_readability_char_limit(max_chars)
    soft_duration_limit = _soft_readability_duration_limit(max_duration)
    amount = 0.0
    for entry in entries:
        text = str(entry.text_raw or "").strip()
        duration = max(0.0, float(entry.end) - float(entry.start))
        amount += float(max(0, len(text) - soft_char_limit))
        amount += max(0.0, duration - soft_duration_limit) * 2.0
    return amount


def _fragment_window_candidate_has_hard_regression(
    *,
    current_entries: list[SubtitleEntry],
    candidate_entries: list[SubtitleEntry],
    current_analysis: SubtitleSegmentationAnalysis,
    candidate_analysis: SubtitleSegmentationAnalysis,
    max_chars: int,
    max_duration: float,
) -> bool:
    if int(candidate_analysis.protected_term_split_count) > int(current_analysis.protected_term_split_count):
        return True
    if int(candidate_analysis.generic_word_split_count) > int(current_analysis.generic_word_split_count):
        return True
    if _fragment_window_overlong_entry_count(candidate_entries, max_chars=max_chars) > _fragment_window_overlong_entry_count(
        current_entries,
        max_chars=max_chars,
    ):
        return True
    candidate_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
        candidate_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    current_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
        current_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    if candidate_soft_overflow_count > current_soft_overflow_count + 1:
        return True

    current_residual_count = _fragment_window_residual_entry_count(current_entries)
    candidate_residual_count = _fragment_window_residual_entry_count(candidate_entries)
    if (
        current_soft_overflow_count == 0
        and candidate_soft_overflow_count > 0
        and candidate_residual_count >= max(0, current_residual_count - 1)
    ):
        return True
    if candidate_residual_count > current_residual_count + 1:
        return True

    current_short_fragment_count = sum(
        1 for entry in current_entries if _is_short_subtitle_fragment(getattr(entry, "text_raw", ""))
    )
    candidate_short_fragment_count = sum(
        1 for entry in candidate_entries if _is_short_subtitle_fragment(getattr(entry, "text_raw", ""))
    )
    candidate_low_conf = int(candidate_analysis.low_confidence_window_count)
    current_low_conf = int(current_analysis.low_confidence_window_count)
    candidate_suspicious = int(candidate_analysis.suspicious_boundary_count)
    current_suspicious = int(current_analysis.suspicious_boundary_count)
    current_fragment_total = int(current_analysis.fragment_start_count) + int(current_analysis.fragment_end_count)
    candidate_fragment_total = int(candidate_analysis.fragment_start_count) + int(candidate_analysis.fragment_end_count)
    if (
        len(candidate_entries) > len(current_entries)
        and candidate_low_conf >= current_low_conf
        and candidate_suspicious >= current_suspicious
        and candidate_fragment_total >= current_fragment_total
    ):
        return True
    if (
        candidate_short_fragment_count > current_short_fragment_count
        and candidate_low_conf >= current_low_conf
        and candidate_suspicious >= current_suspicious
    ):
        return True
    if candidate_low_conf > current_low_conf and candidate_suspicious >= current_suspicious:
        return True
    return False


def _fragment_window_candidate_is_acceptable(
    *,
    current_entries: list[SubtitleEntry],
    candidate_entries: list[SubtitleEntry],
    current_score: float,
    candidate_score: float,
    current_analysis: SubtitleSegmentationAnalysis,
    candidate_analysis: SubtitleSegmentationAnalysis,
    max_chars: int,
    max_duration: float,
) -> bool:
    if (
        len(candidate_entries) == 1
        and len(current_entries) > 1
        and (
            len(candidate_entries[0].text_raw) > max_chars + 1
            or _is_incomplete_subtitle_text(candidate_entries[0].text_raw)
        )
    ):
        return False
    short_candidate_count = sum(1 for entry in candidate_entries if len(str(entry.text_raw or "").strip()) <= 3)
    if (
        len(candidate_entries) > len(current_entries)
        and short_candidate_count >= max(2, len(candidate_entries) - 1)
        and candidate_score < current_score + 6.0
    ):
        return False
    if _fragment_window_candidate_has_hard_regression(
        current_entries=current_entries,
        candidate_entries=candidate_entries,
        current_analysis=current_analysis,
        candidate_analysis=candidate_analysis,
        max_chars=max_chars,
        max_duration=max_duration,
    ):
        return False
    if candidate_score >= current_score + 2.0:
        return True

    current_metrics = _fragment_window_metrics(current_entries)
    candidate_metrics = _fragment_window_metrics(candidate_entries)
    improvement_score = _fragment_window_improvement_score(current_analysis, candidate_analysis)
    current_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
        current_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    candidate_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
        candidate_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    if (
        candidate_soft_overflow_count > current_soft_overflow_count
        and candidate_score < current_score + 4.0
        and improvement_score < 16.0
    ):
        return False
    if candidate_metrics == current_metrics:
        return False
    low_conf_delta = current_metrics[0] - candidate_metrics[0]
    suspicious_delta = current_metrics[1] - candidate_metrics[1]
    protected_delta = current_metrics[2] - candidate_metrics[2]
    generic_word_delta = current_metrics[3] - candidate_metrics[3]
    fragment_delta = current_metrics[4] - candidate_metrics[4]
    if (
        low_conf_delta > 0
        and suspicious_delta >= 0
        and fragment_delta >= 0
        and candidate_score >= current_score - 4.0
    ):
        return True
    if protected_delta > 0 and candidate_score >= current_score - 5.0:
        return True
    if generic_word_delta > 0 and candidate_score >= current_score - 6.0:
        return True
    if suspicious_delta >= 2 and fragment_delta >= 1 and candidate_score >= current_score - 4.0:
        return True
    if fragment_delta >= 2 and suspicious_delta >= 1 and candidate_score >= current_score - 4.0:
        return True
    if improvement_score >= 12.0 and candidate_score >= current_score - 8.0:
        return True
    if improvement_score >= 8.0 and candidate_score >= current_score - 5.0:
        return True
    if (
        low_conf_delta > 0
        and candidate_score >= current_score - 3.0
    ):
        return True
    return False


def _pick_best_fragment_window_candidate(
    current_entries: list[SubtitleEntry],
    candidates: list[list[SubtitleEntry]],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry] | None:
    if not candidates:
        return None

    current_analysis = analyze_subtitle_segmentation(current_entries)
    current_score = _score_entry_sequence(current_entries, max_chars=max_chars, max_duration=max_duration)
    current_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
        current_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    current_soft_overflow_amount = _fragment_window_readability_soft_overflow_amount(
        current_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    ranked: list[tuple[tuple[float, float, float, float, float, float, float], list[SubtitleEntry]]] = []
    for candidate_entries in candidates:
        candidate_analysis = analyze_subtitle_segmentation(candidate_entries)
        candidate_score = _score_entry_sequence(candidate_entries, max_chars=max_chars, max_duration=max_duration)
        improvement_score = _fragment_window_improvement_score(current_analysis, candidate_analysis)
        metrics = _fragment_window_metrics(candidate_entries)
        candidate_soft_overflow_count = _fragment_window_readability_soft_overflow_count(
            candidate_entries,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        candidate_soft_overflow_amount = _fragment_window_readability_soft_overflow_amount(
            candidate_entries,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        ranked.append(
            (
                (
                    improvement_score,
                    float(current_soft_overflow_count - candidate_soft_overflow_count),
                    float(current_soft_overflow_amount - candidate_soft_overflow_amount),
                    float(current_analysis.low_confidence_window_count - candidate_analysis.low_confidence_window_count),
                    float(current_analysis.suspicious_boundary_count - candidate_analysis.suspicious_boundary_count),
                    candidate_score - current_score,
                    -float(sum(metrics)),
                ),
                candidate_entries,
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


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
        if not str(entry.text_norm or "").strip():
            continue
        item = SubtitleItem(
            job_id=job_id,
            version=version,
            item_index=entry.index,
            start_time=entry.start,
            end_time=entry.end,
            text_raw=normalize_editable_subtitle_text(entry.text_raw),
            text_norm=normalize_editable_subtitle_text(entry.text_norm),
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items
