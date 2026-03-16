from __future__ import annotations

from typing import Any

DEFAULT_TRANSCRIPTION_DIALECT = "mandarin"

_DIALECT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "value": "mandarin",
        "label": "普通话",
        "asr_label": "普通话",
        "prompt_hint": "",
        "hotwords": [],
    },
    {
        "value": "beijing",
        "label": "北京话",
        "asr_label": "北京话",
        "prompt_hint": "优先按北京口语理解，保留儿化音、京腔口语和地道表达，不要强行改写成普通话同义词。",
        "hotwords": ["倍儿", "甭", "搁", "局气", "犯贫", "可劲儿", "得嘞", "这茬儿"],
    },
    {
        "value": "northeast",
        "label": "东北话",
        "asr_label": "东北话",
        "prompt_hint": "优先按东北口语理解，保留高频口头词和语气词，不要误写成近音普通话词。",
        "hotwords": ["老铁", "整不会了", "嘎嘎", "埋汰", "唠嗑", "可劲造", "咋整", "虎了吧唧"],
    },
    {
        "value": "sichuan",
        "label": "四川话",
        "asr_label": "四川话",
        "prompt_hint": "优先按四川口语理解，注意轻声和卷舌缺失带来的近音误识别。",
        "hotwords": ["巴适", "安逸", "摆龙门阵", "幺儿", "雄起", "瓜娃子", "整起走", "耍朋友"],
    },
    {
        "value": "cantonese",
        "label": "粤语",
        "asr_label": "粤语口音普通话",
        "prompt_hint": "如果出现粤语口音普通话或夹杂粤语词，优先结合粤语表达理解，不要机械按普通话近音转写。",
        "hotwords": ["靓仔", "靓女", "搞掂", "收工", "埋单", "咩事", "叻", "顶唔顺"],
    },
    {
        "value": "shanghai",
        "label": "沪语",
        "asr_label": "沪语口音普通话",
        "prompt_hint": "优先按沪语口音普通话理解，注意儿化较少和连读带来的发音偏差。",
        "hotwords": ["老灵额", "拎得清", "哪能", "嘎讪胡", "勿要", "阿拉", "伊拉", "老克勒"],
    },
)

TRANSCRIPTION_DIALECT_OPTIONS = [
    {"value": str(item["value"]), "label": str(item["label"])}
    for item in _DIALECT_SPECS
]
_DIALECT_SPEC_BY_VALUE = {str(item["value"]): item for item in _DIALECT_SPECS}


def normalize_transcription_dialect(value: object) -> str:
    normalized = str(value or DEFAULT_TRANSCRIPTION_DIALECT).strip().lower() or DEFAULT_TRANSCRIPTION_DIALECT
    if normalized not in _DIALECT_SPEC_BY_VALUE:
        return DEFAULT_TRANSCRIPTION_DIALECT
    return normalized


def resolve_transcription_dialect(value: object) -> dict[str, Any]:
    normalized = normalize_transcription_dialect(value)
    spec = _DIALECT_SPEC_BY_VALUE[normalized]
    return {
        "value": normalized,
        "label": str(spec["label"]),
        "asr_label": str(spec.get("asr_label") or spec["label"]),
        "prompt_hint": str(spec.get("prompt_hint") or "").strip(),
        "hotwords": [str(item).strip() for item in spec.get("hotwords") or [] if str(item).strip()],
    }
