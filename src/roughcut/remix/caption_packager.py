from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from roughcut.remix import hyperframes


CAPTION_PACKAGE_SCHEMA = "roughcut.remix.caption_package.v1"
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_WATERMARK = "RoughCut"
CAPTION_STYLE_PROFILE = "jianying_reference_v2"
CHILDREN_STORYBOOK_STYLE_PROFILE = "children_storybook_v1"
SUPPORTED_CAPTION_STYLE_PROFILES = {CAPTION_STYLE_PROFILE, CHILDREN_STORYBOOK_STYLE_PROFILE}


@dataclass(frozen=True, slots=True)
class CaptionPackage:
    ass_text: str
    subtitle_event_count: int
    subtitle_text_coverage: float
    subtitle_style_profile: str
    max_subtitle_lines_per_event: int
    max_subtitle_line_chars: int
    packaging_event_count: int
    theme_banner_count: int
    keyword_sticker_count: int
    watermark_event_count: int
    emphasis_keyword_count: int
    animated_subtitle_event_count: int
    animated_packaging_event_count: int
    motion_effect_count: int
    highlight_effect_count: int
    audio_cue_count: int
    audio_cues: list[dict[str, Any]]
    source_bridge_count: int
    semantic_packaging_source: str
    semantic_packaging_llm_reviewed: bool
    semantic_packaging_plan: dict[str, Any]
    hyperframes_plan: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema": CAPTION_PACKAGE_SCHEMA,
            "packaging_framework": hyperframes.HYPERFRAMES_ENGINE,
            "hyperframes_enabled": True,
            "hyperframes_plan_schema": self.hyperframes_plan.get("schema"),
            "hyperframes_track_count": len(self.hyperframes_plan.get("tracks") or []),
            "hyperframes_element_count": int(self.hyperframes_plan.get("element_count") or 0),
            "hyperframes_effect_count": int(self.hyperframes_plan.get("effect_count") or 0),
            "hyperframes_plan": self.hyperframes_plan,
            "subtitle_event_count": self.subtitle_event_count,
            "subtitle_text_coverage": self.subtitle_text_coverage,
            "subtitle_style_profile": self.subtitle_style_profile,
            "max_subtitle_lines_per_event": self.max_subtitle_lines_per_event,
            "max_subtitle_line_chars": self.max_subtitle_line_chars,
            "packaging_event_count": self.packaging_event_count,
            "theme_banner_count": self.theme_banner_count,
            "keyword_sticker_count": self.keyword_sticker_count,
            "watermark_event_count": self.watermark_event_count,
            "emphasis_keyword_count": self.emphasis_keyword_count,
            "animated_subtitle_event_count": self.animated_subtitle_event_count,
            "animated_packaging_event_count": self.animated_packaging_event_count,
            "motion_effect_count": self.motion_effect_count,
            "highlight_effect_count": self.highlight_effect_count,
            "audio_cue_count": self.audio_cue_count,
            "audio_cues": self.audio_cues,
            "source_bridge_count": self.source_bridge_count,
            "semantic_packaging_source": self.semantic_packaging_source,
            "semantic_packaging_llm_reviewed": self.semantic_packaging_llm_reviewed,
            "semantic_packaging_plan": self.semantic_packaging_plan,
        }


def build_caption_package(
    *,
    episode: int,
    title: str,
    question: str,
    subtitle_timings: Sequence[tuple[str, float, float]],
    duration_sec: float,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    watermark: str = DEFAULT_WATERMARK,
    subtitle_style_profile: str | None = None,
    semantic_packaging_plan: dict[str, Any] | None = None,
    original_audio_insertions: Sequence[dict[str, Any]] | None = None,
) -> CaptionPackage:
    style_profile = normalize_caption_style_profile(subtitle_style_profile)
    semantic_plan = normalize_semantic_packaging_plan(
        semantic_packaging_plan,
        subtitle_timings=subtitle_timings,
        duration_sec=duration_sec,
        episode=episode,
        title=title,
        question=question,
    )
    subtitle_events: list[str] = []
    source_subtitle_texts: list[str] = []
    visible_subtitle_texts: list[str] = []
    subtitle_line_counts: list[int] = []
    subtitle_line_char_counts: list[int] = []
    hyperframe_elements: list[dict[str, Any]] = []
    emphasis_count = 0
    animated_subtitle_count = 0
    for subtitle_index, (chunk, start, end) in enumerate(subtitle_timings, start=1):
        subtitle_text, count = dynamic_subtitle_text(
            chunk,
            emphasis_keywords=semantic_plan["subtitle_emphasis_keywords"],
            subtitle_style_profile=style_profile,
        )
        source_subtitle_texts.append(str(chunk))
        visible_subtitle_texts.append(visible_ass_text(subtitle_text))
        plain_wrapped = wrap_ass_text(chunk)
        lines = [line for line in plain_wrapped.split(r"\N") if line]
        subtitle_line_counts.append(len(lines))
        subtitle_line_char_counts.extend(len(line) for line in lines)
        subtitle_events.append(
            f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{subtitle_text}"
        )
        hyperframe_elements.append(
            hyperframes.text_element(
                element_id=f"subtitle_{subtitle_index:03d}",
                track="subtitles",
                start_sec=start,
                end_sec=end,
                text=str(chunk),
                style="bottom_narration",
                layer=0,
                position=(960, 935),
                effects=[hyperframes.fade_in_out(70, 110), hyperframes.pop(0.96, 1.07, 160)],
            )
        )
        emphasis_count += count
        if has_motion_effect(subtitle_text):
            animated_subtitle_count += 1

    packaging = build_reference_style_packaging_events(
        episode=episode,
        title=title,
        question=question,
        duration_sec=duration_sec,
        width=width,
        watermark=watermark,
        semantic_packaging_plan=semantic_plan,
        original_audio_insertions=original_audio_insertions,
    )
    hyperframe_elements.extend(packaging["hyperframes_elements"])
    events = [*subtitle_events, *packaging["events"]]
    ass_text = build_ass_header(width=width, height=height, subtitle_style_profile=style_profile) + "\n".join(events) + "\n"
    hyperframes_plan = hyperframes.build_plan(
        width=width,
        height=height,
        duration_sec=duration_sec,
        elements=hyperframe_elements,
    )
    return CaptionPackage(
        ass_text=ass_text,
        subtitle_event_count=len(subtitle_events),
        subtitle_text_coverage=subtitle_text_coverage(source_subtitle_texts, visible_subtitle_texts),
        subtitle_style_profile=style_profile,
        max_subtitle_lines_per_event=max(subtitle_line_counts or [0]),
        max_subtitle_line_chars=max(subtitle_line_char_counts or [0]),
        packaging_event_count=len(packaging["events"]),
        theme_banner_count=int(packaging["theme_banner_count"]),
        keyword_sticker_count=int(packaging["keyword_sticker_count"]),
        watermark_event_count=int(packaging["watermark_event_count"]),
        emphasis_keyword_count=emphasis_count,
        animated_subtitle_event_count=animated_subtitle_count,
        animated_packaging_event_count=sum(1 for item in packaging["events"] if has_motion_effect(item)),
        motion_effect_count=sum(1 for item in events if has_motion_effect(item)),
        highlight_effect_count=emphasis_count
        + int(packaging["keyword_sticker_count"])
        + int(packaging["theme_banner_count"]),
        audio_cue_count=len(packaging["audio_cues"]),
        audio_cues=list(packaging["audio_cues"]),
        source_bridge_count=int(packaging["source_bridge_count"]),
        semantic_packaging_source=str(semantic_plan.get("source") or ""),
        semantic_packaging_llm_reviewed=bool(semantic_plan.get("llm_reviewed")),
        semantic_packaging_plan=semantic_plan,
        hyperframes_plan=hyperframes_plan,
    )


def normalize_caption_style_profile(value: str | None) -> str:
    profile = str(value or "").strip()
    return profile if profile in SUPPORTED_CAPTION_STYLE_PROFILES else CAPTION_STYLE_PROFILE


def build_ass_header(*, width: int, height: int, subtitle_style_profile: str | None = None) -> str:
    style_profile = normalize_caption_style_profile(subtitle_style_profile)
    default_style = (
        "Style: Default,Microsoft YaHei UI,68,&H004AE8FF,&H000000FF,&H00B55724,&H80FFFFFF,1,0,0,0,100,100,0,0,1,6.8,2.4,2,130,130,70,1"
        if style_profile == CHILDREN_STORYBOOK_STYLE_PROFILE
        else "Style: Default,Microsoft YaHei,62,&H00FFFFFF,&H000000FF,&H8A000000,&HAA000000,1,0,0,0,100,100,0,0,1,4.6,1.4,2,120,120,78,1"
    )
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {int(width)}
PlayResY: {int(height)}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{default_style}
Style: Watermark,Microsoft YaHei,40,&HCCFFFFFF,&H000000FF,&H55000000,&H00000000,0,0,0,0,100,100,0,0,1,1.8,0,9,34,48,34,1
Style: BigTitle,Microsoft YaHei,98,&H00EAF7FF,&H000000FF,&HAA183E5D,&H5A000000,1,0,0,0,100,100,0,0,1,6.4,1.8,7,100,100,140,1
Style: BlueBanner,Microsoft YaHei,76,&H00FFFFFF,&H000000FF,&H7A103A75,&H00000000,1,0,0,0,100,100,0,0,1,3.8,1.4,5,96,96,70,1
Style: Keyword,Microsoft YaHei,92,&H0000FFFF,&H000000FF,&HAA32003C,&H55000000,1,0,0,0,100,100,0,0,1,7.0,1.8,5,80,80,80,1
Style: RedKeyword,Microsoft YaHei,92,&H00F4F4FF,&H000000FF,&HAA00006C,&H55000000,1,0,0,0,100,100,0,0,1,7.2,1.8,5,80,80,80,1
Style: ImpactWord,Microsoft YaHei,116,&H000000FF,&H000000FF,&H00FFFFFF,&H7A000000,1,0,0,0,100,100,0,0,1,7.5,2.2,5,60,60,60,1
Style: Emphasis,Microsoft YaHei,76,&H0000F7FF,&H000000FF,&HAA1F003A,&H50000000,1,0,0,0,100,100,0,0,1,6.0,1.6,5,80,80,80,1
Style: PulseChip,Microsoft YaHei,48,&H00FFFFFF,&H000000FF,&HAA16324B,&H33000000,1,0,0,0,100,100,0,0,1,3.6,1.2,5,60,60,60,1
Style: BubbleText,Microsoft YaHei,64,&H00222531,&H000000FF,&H00FFFFFF,&H55000000,1,0,0,0,100,100,0,0,1,4.2,1.4,5,50,50,50,1
Style: SourceBridge,Microsoft YaHei,54,&H00FFFFFF,&H000000FF,&HAA111111,&H33000000,1,0,0,0,100,100,0,0,1,4.2,1.4,7,80,80,64,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def dynamic_subtitle_text(
    text: str,
    *,
    emphasis_keywords: Sequence[str] | None = None,
    subtitle_style_profile: str | None = None,
) -> tuple[str, int]:
    style_profile = normalize_caption_style_profile(subtitle_style_profile)
    wrapped = wrap_ass_text(text)
    escaped = escape_ass_text(wrapped)
    escaped, count = apply_inline_emphasis(
        escaped,
        emphasis_keywords=emphasis_keywords,
        subtitle_style_profile=style_profile,
    )
    if style_profile == CHILDREN_STORYBOOK_STYLE_PROFILE:
        return (
            r"{\an2\pos(960,928)\fad(80,130)"
            r"\c&H004AE8FF&\3c&H00B55724&\4c&H80FFFFFF&\bord6.8\shad2.4"
            r"\fscx95\fscy95\t(0,170,\fscx108\fscy108)\t(170,340,\fscx100\fscy100)}"
            + escaped,
            count,
        )
    return (
        r"{\an2\pos(960,935)\fad(70,110)"
        r"\fscx96\fscy96\t(0,160,\fscx107\fscy107)\t(160,320,\fscx100\fscy100)}"
        + escaped,
        count,
    )


def has_motion_effect(text: str) -> bool:
    value = str(text or "")
    return any(token in value for token in (r"\fad", r"\move", r"\t("))


def visible_ass_text(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "", str(text or "")).replace(r"\N", "")


def normalize_caption_text(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", str(text or ""))).lower()


def text_lcs_coverage(reference: str, candidate: str) -> float:
    reference_norm = normalize_caption_text(reference)
    candidate_norm = normalize_caption_text(candidate)
    if not reference_norm:
        return 1.0
    if not candidate_norm:
        return 0.0
    previous = [0] * (len(candidate_norm) + 1)
    for ref_char in reference_norm:
        current = [0]
        for column, cand_char in enumerate(candidate_norm, start=1):
            if ref_char == cand_char:
                current.append(previous[column - 1] + 1)
            else:
                current.append(max(previous[column], current[-1]))
        previous = current
    return previous[-1] / max(1, len(reference_norm))


def subtitle_text_coverage(source_chunks: Sequence[str], visible_chunks: Sequence[str]) -> float:
    source = "".join(str(item or "") for item in source_chunks)
    visible = "".join(str(item or "") for item in visible_chunks)
    return round(text_lcs_coverage(source, visible), 4)


def apply_inline_emphasis(
    escaped_text: str,
    *,
    emphasis_keywords: Sequence[str] | None = None,
    subtitle_style_profile: str | None = None,
) -> tuple[str, int]:
    style_profile = normalize_caption_style_profile(subtitle_style_profile)
    output = escaped_text
    count = 0
    for keyword in list(emphasis_keywords or [])[:16]:
        escaped_keyword = escape_ass_text(keyword)
        if escaped_keyword not in output:
            continue
        if style_profile == CHILDREN_STORYBOOK_STYLE_PROFILE:
            replacement = (
                rf"{{\c&H004C9BFF&\3c&H00FFFFFF&\4c&H553366CC&\bord5.8\shad2.6\fscx122\fscy122"
                rf"\t(0,130,\fscx136\fscy136)\t(130,280,\fscx112\fscy112)}}{escaped_keyword}"
                rf"{{\c&H004AE8FF&\3c&H00B55724&\4c&H80FFFFFF&\bord6.8\shad2.4\fscx100\fscy100}}"
            )
        else:
            replacement = (
                rf"{{\c&H0000FFFF&\3c&HAA00006C&\bord7.2\shad2.2\fscx128\fscy128"
                rf"\t(0,130,\fscx142\fscy142)\t(130,260,\fscx116\fscy116)}}{escaped_keyword}"
                rf"{{\c&H00FFFFFF&\3c&H8A000000&\bord4.6\shad1.4\fscx100\fscy100}}"
            )
        output = output.replace(
            escaped_keyword,
            replacement,
            1,
        )
        count += 1
    return output, count


def normalize_semantic_packaging_plan(
    payload: dict[str, Any] | None,
    *,
    subtitle_timings: Sequence[tuple[str, float, float]],
    duration_sec: float,
    episode: int,
    title: str,
    question: str,
) -> dict[str, Any]:
    source = str((payload or {}).get("source") or "deterministic_fallback")
    llm_reviewed = bool((payload or {}).get("llm_reviewed"))
    subtitle_text = "\n".join(str(item[0] or "") for item in subtitle_timings)
    emphasis_keywords = _semantic_keywords_from_payload(payload, subtitle_text=subtitle_text)
    allow_fallback = not llm_reviewed
    if not emphasis_keywords and allow_fallback:
        emphasis_keywords = _fallback_keywords_from_text(question + "\n" + subtitle_text)
    impact_events = _semantic_events_from_payload((payload or {}).get("impact_events"), timings=subtitle_timings, duration_sec=duration_sec)
    keyword_bubbles = _semantic_events_from_payload((payload or {}).get("keyword_bubbles"), timings=subtitle_timings, duration_sec=duration_sec)
    theme_banners = _semantic_events_from_payload((payload or {}).get("theme_banners"), timings=subtitle_timings, duration_sec=duration_sec)
    pulse_chips = _semantic_events_from_payload((payload or {}).get("pulse_chips"), timings=subtitle_timings, duration_sec=duration_sec)
    if not impact_events and allow_fallback:
        impact_events = _fallback_semantic_events(emphasis_keywords[:3], timings=subtitle_timings, duration_sec=duration_sec)
    if not keyword_bubbles and allow_fallback:
        keyword_bubbles = impact_events[:3]
    if not theme_banners and allow_fallback:
        theme_banners = _fallback_semantic_events([title, "剧情证据", "育儿提醒"], timings=subtitle_timings, duration_sec=duration_sec)
    if not pulse_chips and allow_fallback:
        pulse_chips = _fallback_semantic_events(emphasis_keywords[:3], timings=subtitle_timings, duration_sec=duration_sec)
    return {
        "source": source,
        "llm_reviewed": llm_reviewed,
        "episode": int(episode),
        "subtitle_emphasis_keywords": emphasis_keywords[:16],
        "impact_events": impact_events[:3],
        "keyword_bubbles": keyword_bubbles[:3],
        "theme_banners": theme_banners[:3],
        "pulse_chips": pulse_chips[:3],
        "opening_title": str((payload or {}).get("opening_title") or question or title).strip()[:18],
        "closing_title": str((payload or {}).get("closing_title") or "孩子需要被看见").strip()[:18],
    }


def _semantic_keywords_from_payload(payload: dict[str, Any] | None, *, subtitle_text: str) -> list[str]:
    keywords: list[str] = []
    for item in list((payload or {}).get("subtitle_emphasis_keywords") or []):
        keyword = str(item.get("phrase") if isinstance(item, dict) else item).strip()
        if keyword and keyword in subtitle_text and keyword not in keywords:
            keywords.append(keyword[:10])
    return keywords


def _semantic_events_from_payload(
    raw_events: Any,
    *,
    timings: Sequence[tuple[str, float, float]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for raw in list(raw_events or []):
        if not isinstance(raw, dict):
            continue
        phrase = str(raw.get("phrase") or "").strip()
        matched_text = str(raw.get("matched_text") or "").strip()
        if not phrase:
            continue
        start = _event_start_for_text(matched_text or phrase, timings=timings)
        if start is None:
            continue
        events.append(
            {
                "phrase": phrase[:8],
                "matched_text": matched_text,
                "reason": str(raw.get("reason") or "").strip(),
                "start_sec": round(max(0.5, min(float(duration_sec) - 1.5, start)), 3),
            }
        )
    return events


def _event_start_for_text(text: str, *, timings: Sequence[tuple[str, float, float]]) -> float | None:
    needle = str(text or "").strip()
    needle_norm = normalize_caption_text(needle)
    for chunk, start, _end in timings:
        chunk_text = str(chunk or "")
        if needle and (needle in chunk_text or chunk_text in needle):
            return float(start)
        chunk_norm = normalize_caption_text(chunk_text)
        if needle_norm and chunk_norm:
            if needle_norm in chunk_norm or (len(chunk_norm) >= 12 and chunk_norm in needle_norm):
                return float(start)
    parts = sorted(
        {
            part
            for part in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{4,}", needle)
            if len(normalize_caption_text(part)) >= 4
        },
        key=len,
        reverse=True,
    )
    for chunk, start, _end in timings:
        chunk_text = str(chunk or "")
        if any(part in chunk_text for part in parts):
            return float(start)
    return None


def _fallback_keywords_from_text(text: str) -> list[str]:
    candidates = re.findall(r"[\u4e00-\u9fff]{2,6}", str(text or ""))
    stop = {"这一集", "为什么", "孩子", "一个", "时候", "其实", "可以", "大家", "我们"}
    unique: list[str] = []
    for item in candidates:
        if item in stop or item in unique:
            continue
        unique.append(item)
        if len(unique) >= 8:
            break
    return unique


def _fallback_semantic_events(
    phrases: Sequence[str],
    *,
    timings: Sequence[tuple[str, float, float]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    starts = [float(item[1]) for item in timings] or [0.5]
    events: list[dict[str, Any]] = []
    for index, phrase in enumerate(list(phrases)[:3]):
        start = starts[min(len(starts) - 1, max(0, int((index + 1) * len(starts) / 4)))]
        events.append(
            {
                "phrase": str(phrase)[:8],
                "matched_text": "",
                "reason": "fallback",
                "start_sec": round(min(duration_sec - 1.5, start), 3),
            }
        )
    return events


def build_reference_style_packaging_events(
    *,
    episode: int,
    title: str,
    question: str,
    duration_sec: float,
    width: int = DEFAULT_WIDTH,
    watermark: str = DEFAULT_WATERMARK,
    semantic_packaging_plan: dict[str, Any] | None = None,
    original_audio_insertions: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    duration = max(0.0, float(duration_sec))
    overlays = packaging_phrases_for_episode(episode, title, question)
    semantic_plan = semantic_packaging_plan or {}
    overlays["opening"] = str(semantic_plan.get("opening_title") or overlays["opening"])
    overlays["closing"] = str(semantic_plan.get("closing_title") or overlays["closing"])
    banner_events = list(semantic_plan.get("theme_banners") or [])
    keyword_events = list(semantic_plan.get("keyword_bubbles") or [])
    impact_events = list(semantic_plan.get("impact_events") or keyword_events)
    pulse_events = list(semantic_plan.get("pulse_chips") or [])
    hyperframes_elements: list[dict[str, Any]] = []
    audio_cues: list[dict[str, Any]] = []
    events = [
        ass_event(1, 0.0, duration, "Watermark", rf"{{\fad(300,300)}}{escape_ass_text(watermark)}"),
    ]
    hyperframes_elements.append(
        hyperframes.text_element(
            element_id="watermark_001",
            track="watermark",
            start_sec=0.0,
            end_sec=duration,
            text=watermark,
            style="self_watermark",
            layer=1,
            position=(1886, 34),
            effects=[hyperframes.fade_in_out(300, 300)],
        )
    )
    watermark_count = 1
    if overlays["opening"]:
        events.append(
            ass_event(
                2,
                0.45,
                min(4.8, duration),
                "BigTitle",
                rf"{{\pos(120,150)\fad(120,220)\fscx72\fscy72\t(0,220,\fscx112\fscy112)\t(220,420,\fscx100\fscy100)\t(3200,4100,\frz-1)}}{escape_ass_text(overlays['opening'])}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id="opening_title_001",
                track="titles",
                start_sec=0.45,
                end_sec=min(4.8, duration),
                text=str(overlays["opening"]),
                style="opening_title",
                layer=2,
                position=(120, 150),
                effects=[hyperframes.fade_in_out(120, 220), hyperframes.pop(0.72, 1.12, 220), hyperframes.pulse(900)],
            )
        )
    banner_count = 0
    for index, raw_event in enumerate(banner_events[:3]):
        phrase = str(raw_event.get("phrase") if isinstance(raw_event, dict) else raw_event).strip() or str(overlays["banners"][index])
        start = float(raw_event.get("start_sec") or (26.0 + index * 38.0)) if isinstance(raw_event, dict) else min(duration - 2.0, 26.0 + index * 38.0)
        start = min(duration - 2.0, max(0.5, start))
        if start <= 0:
            continue
        banner_count += 1
        end = min(duration, start + 4.8)
        audio_cues.append({"time_sec": round(start + 0.08, 3), "kind": "banner_whoosh", "label": phrase})
        events.append(
            ass_event(
                2,
                start,
                end,
                "BlueBanner",
                rf"{{\p1\move(760,144,960,144,0,260)\c&HDD7A22&\alpha&H22&\bord0\shad0\fad(120,240)\t(0,220,\alpha&H08&)}}m -560 -58 l 560 -58 l 505 58 l -560 58",
            )
        )
        hyperframes_elements.append(
            hyperframes.shape_element(
                element_id=f"theme_banner_plate_{index + 1:03d}",
                track="theme_banners",
                start_sec=start,
                end_sec=end,
                shape="slanted_banner",
                style="blue_banner_plate",
                layer=2,
                position=(960, 144),
                effects=[hyperframes.fade_in_out(120, 240), hyperframes.slide((760, 144), (960, 144), 260)],
            )
        )
        events.append(
            ass_event(
                3,
                start,
                end,
                "BlueBanner",
                rf"{{\move(430,92,610,92,0,240)\fad(100,220)\fscx82\fscy82\t(0,220,\fscx104\fscy104)\t(220,380,\fscx96\fscy96)}}{escape_ass_text(phrase)}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id=f"theme_banner_title_{index + 1:03d}",
                track="theme_banners",
                start_sec=start,
                end_sec=end,
                text=phrase,
                style="theme_banner_title",
                layer=3,
                position=(610, 92),
                effects=[hyperframes.fade_in_out(100, 220), hyperframes.slide((430, 92), (610, 92), 240), hyperframes.pop(0.82, 1.04, 220)],
            )
        )
    keyword_count = 0
    for index, raw_event in enumerate(keyword_events[:3]):
        phrase = str(raw_event.get("phrase") if isinstance(raw_event, dict) else raw_event).strip() or str(overlays["keywords"][index])
        start = float(raw_event.get("start_sec") or (50.0 + index * 28.0)) if isinstance(raw_event, dict) else min(duration - 1.8, 50.0 + index * 28.0)
        start = min(duration - 1.8, max(0.5, start))
        if start <= 0:
            continue
        keyword_count += 1
        style = "RedKeyword" if index % 2 == 0 else "Keyword"
        y = 348 if index % 2 == 0 else 416
        x = 1440 if index % 3 == 0 else 500
        text_x = x - 205
        text_y = y - 66
        enter_x = text_x + (180 if x < width / 2 else -180)
        end = min(duration, start + 3.2)
        bubble_color = r"&H2DFBFF&" if index % 2 == 0 else r"&H75F2FF&"
        audio_cues.append({"time_sec": round(start + 0.06, 3), "kind": "keyword_pop", "label": phrase})
        events.append(
            ass_event(
                3,
                start,
                end,
                style,
                rf"{{\p1\pos({x},{y + 8})\c{bubble_color}\alpha&H10&\bord3\3c&HFFFFFF&\shad2\fad(80,160)\t(0,160,\alpha&H00&)}}m -205 -72 l 205 -72 l 205 42 l 54 42 l 30 76 l 8 42 l -205 42",
            )
        )
        hyperframes_elements.append(
            hyperframes.shape_element(
                element_id=f"keyword_plate_{index + 1:03d}",
                track="keyword_stickers",
                start_sec=start,
                end_sec=end,
                shape="rounded_label",
                style="keyword_speech_bubble",
                layer=3,
                position=(x, y + 8),
                effects=[hyperframes.fade_in_out(80, 160), hyperframes.pop(0.85, 1.02, 160)],
            )
        )
        events.append(
            ass_event(
                4,
                start,
                end,
                "BubbleText",
                rf"{{\move({enter_x},{text_y},{text_x},{text_y},0,170)\fad(70,160)\frz{(-4 if index % 2 == 0 else 3)}\fscx62\fscy62\t(0,160,\fscx118\fscy118)\t(160,310,\fscx100\fscy100)\t(1900,2600,\fscx108\fscy108)}}{escape_ass_text(phrase)}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id=f"keyword_text_{index + 1:03d}",
                track="keyword_stickers",
                start_sec=start,
                end_sec=end,
                text=phrase,
                style="keyword_text",
                layer=4,
                position=(text_x, text_y),
                effects=[hyperframes.fade_in_out(70, 160), hyperframes.slide((enter_x, text_y), (text_x, text_y), 170), hyperframes.pulse(700)],
            )
        )
        impact_raw = impact_events[index] if index < len(impact_events) and isinstance(impact_events[index], dict) else raw_event
        impact_phrase = str(impact_raw.get("phrase") if isinstance(impact_raw, dict) else phrase).strip() or phrase
        impact_start = float(impact_raw.get("start_sec") or start) + 0.18 if isinstance(impact_raw, dict) else start + 0.18
        impact_start = min(end - 0.8, max(0.5, impact_start))
        impact_end = min(duration, impact_start + 1.45)
        impact_x = 1340 if index % 2 == 0 else 640
        impact_y = 250 if index % 2 == 0 else 300
        audio_cues.append({"time_sec": round(impact_start + 0.03, 3), "kind": "impact_hit", "label": phrase})
        events.append(
            ass_event(
                5,
                impact_start,
                impact_end,
                "ImpactWord",
                rf"{{\pos({impact_x},{impact_y})\fad(50,120)\frz{(-3 if index % 2 == 0 else 3)}\fscx58\fscy58\t(0,120,\fscx132\fscy132)\t(120,260,\fscx100\fscy100)\t(760,1120,\fscx108\fscy108)}}{escape_ass_text(impact_phrase)}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id=f"impact_word_{index + 1:03d}",
                track="impact_words",
                start_sec=impact_start,
                end_sec=impact_end,
                text=impact_phrase,
                style="impact_word",
                layer=5,
                position=(impact_x, impact_y),
                effects=[hyperframes.fade_in_out(50, 120), hyperframes.pop(0.58, 1.32, 120), hyperframes.pulse(540)],
            )
        )
    if duration >= 30.0:
        start = max(0.0, min(duration - 4.6, duration * 0.78))
        events.append(
            ass_event(
                3,
                start,
                min(duration, start + 3.8),
                "Emphasis",
                rf"{{\pos(960,250)\fad(120,260)\fscx70\fscy70\t(0,220,\fscx112\fscy112)\t(220,420,\fscx100\fscy100)}}{escape_ass_text(overlays['closing'])}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id="closing_emphasis_001",
                track="emphasis",
                start_sec=start,
                end_sec=min(duration, start + 3.8),
                text=str(overlays["closing"]),
                style="closing_emphasis",
                layer=3,
                position=(960, 250),
                effects=[hyperframes.fade_in_out(120, 260), hyperframes.pop(0.7, 1.12, 220)],
            )
        )
    for index, raw_event in enumerate(pulse_events[:3]):
        phrase = str(raw_event.get("phrase") if isinstance(raw_event, dict) else raw_event).strip()
        if not phrase:
            continue
        start = float(raw_event.get("start_sec") or (14.0 + index * 32.0)) if isinstance(raw_event, dict) else min(duration - 1.2, 14.0 + index * 32.0)
        start = min(duration - 1.2, max(0.5, start))
        if start <= 0:
            continue
        end = min(duration, start + 2.4)
        audio_cues.append({"time_sec": round(start + 0.04, 3), "kind": "pulse_tick", "label": phrase})
        x = 330 if index % 2 == 0 else 1570
        y = 710 if index % 2 == 0 else 300
        events.append(
            ass_event(
                4,
                start,
                end,
                "PulseChip",
                rf"{{\pos({x},{y})\fad(60,160)\fscx58\fscy58\t(0,140,\fscx108\fscy108)\t(140,260,\fscx100\fscy100)\t(1180,1640,\fscx106\fscy106)}}{escape_ass_text(phrase)}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id=f"pulse_chip_{index + 1:03d}",
                track="pulse_chips",
                start_sec=start,
                end_sec=end,
                text=phrase,
                style="pulse_chip",
                layer=4,
                position=(x, y),
                effects=[hyperframes.fade_in_out(60, 160), hyperframes.pop(0.58, 1.08, 140), hyperframes.pulse(640)],
            )
        )
    source_bridge_count = 0
    cumulative_insert_offset = 0.0
    for index, insertion in enumerate(sorted(list(original_audio_insertions or []), key=lambda item: float(item.get("insert_at_sec") or 0.0))):
        bridge_duration = max(0.0, float(insertion.get("duration_sec") or 0.0))
        if bridge_duration <= 0.0:
            continue
        raw_insert_at = max(0.0, float(insertion.get("insert_at_sec") or 0.0))
        start = min(duration - 0.3, raw_insert_at + cumulative_insert_offset)
        end = min(duration, start + bridge_duration)
        cumulative_insert_offset += bridge_duration
        if end <= start + 0.2:
            continue
        source_bridge_count += 1
        matched = compact_bridge_label(str(insertion.get("matched_text") or insertion.get("context") or ""))
        label = f"原片片段：{matched}" if matched else "原片片段"
        audio_cues.append({"time_sec": round(start + 0.05, 3), "kind": "source_bridge", "label": label})
        events.append(
            ass_event(
                5,
                start,
                end,
                "SourceBridge",
                rf"{{\pos(96,116)\fad(80,140)\fscx86\fscy86\t(0,160,\fscx106\fscy106)\t(160,300,\fscx100\fscy100)}}{escape_ass_text(label)}",
            )
        )
        hyperframes_elements.append(
            hyperframes.text_element(
                element_id=f"source_bridge_{index + 1:03d}",
                track="source_audio_bridges",
                start_sec=start,
                end_sec=end,
                text=label,
                style="source_bridge_label",
                layer=5,
                position=(96, 116),
                effects=[hyperframes.fade_in_out(80, 140), hyperframes.pop(0.86, 1.06, 160)],
            )
        )
    return {
        "events": events,
        "hyperframes_elements": hyperframes_elements,
        "audio_cues": audio_cues,
        "theme_banner_count": banner_count,
        "keyword_sticker_count": keyword_count,
        "watermark_event_count": watermark_count,
        "source_bridge_count": source_bridge_count,
    }


def compact_bridge_label(text: str) -> str:
    clean = re.sub(r"\s+", "", str(text or ""))
    clean = re.sub(r"[{}\\]", "", clean)
    return clean[:12]


def packaging_phrases_for_episode(episode: int, title: str, question: str) -> dict[str, Any]:
    presets: dict[int, dict[str, list[str] | str]] = {
        1: {
            "opening": "好吧不等于愿意",
            "banners": ["孩子边界感", "先停一下", "给孩子拒绝权"],
            "keywords": ["不想要", "可以说不", "我愿意"],
            "pulses": ["边界", "选择", "看见"],
        },
        2: {
            "opening": "想要很多不等于贪心",
            "banners": ["购物欲望管理", "愿望可以被看见", "规则先说清"],
            "keywords": ["太想要", "先约定", "慢慢选"],
            "pulses": ["愿望", "规则", "等待"],
        },
        3: {
            "opening": "嘴上没关系不代表不难过",
            "banners": ["情绪表达练习", "别急着劝大度", "先承认感受"],
            "keywords": ["不舒服", "说出来", "被看见"],
            "pulses": ["感受", "表达", "接住"],
        },
    }
    if episode in presets:
        item = presets[episode]
        return {
            "opening": str(item["opening"]),
            "banners": list(item["banners"]),
            "keywords": list(item["keywords"]),
            "pulses": list(item["pulses"]),
            "closing": "孩子需要被看见",
        }
    compact_question = strip_punctuation(question)
    return {
        "opening": compact_question[:10] or title,
        "banners": ["看见孩子", "先共情", "再立规则"],
        "keywords": ["别急", "说出来", "慢慢来"],
        "pulses": ["观察", "回应", "边界"],
        "closing": "先看见，再引导",
    }


def ass_event(layer: int, start: float, end: float, style: str, text: str) -> str:
    return f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def wrap_ass_text(text: str, *, max_line_chars: int = 17, max_lines: int = 2) -> str:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if len(compact) <= max_line_chars:
        return compact
    if max_lines >= 2 and len(compact) <= max_line_chars * max_lines:
        lower = max(1, len(compact) - max_line_chars)
        upper = min(max_line_chars, len(compact) - 1)
        split_at = best_balanced_split(compact, lower=lower, upper=upper)
        return r"\N".join((compact[:split_at].strip("，、。"), compact[split_at:].strip("，、。")))
    lines: list[str] = []
    remaining = compact
    while len(remaining) > max_line_chars:
        split_at = max(
            remaining.rfind("，", 0, max_line_chars + 1),
            remaining.rfind("、", 0, max_line_chars + 1),
            remaining.rfind("。", 0, max_line_chars + 1),
        )
        if split_at < max_line_chars // 2:
            split_at = max_line_chars
        lines.append(remaining[:split_at].strip("，、。"))
        remaining = remaining[split_at:].strip("，、。")
    if remaining:
        lines.append(remaining)
    return r"\N".join(line for line in lines if line)


def best_balanced_split(text: str, *, lower: int, upper: int) -> int:
    target = len(text) / 2.0
    candidates = [
        index + 1
        for index, char in enumerate(text)
        if lower <= index + 1 <= upper and char in "，、。！？；：,.!?;:"
    ]
    if candidates:
        return min(candidates, key=lambda value: abs(value - target))
    return max(lower, min(upper, int(round(target))))


def escape_ass_text(text: str) -> str:
    return str(text or "").replace("{", r"\{").replace("}", r"\}")


def strip_punctuation(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:“”\"'《》]+", "", str(value or ""))
