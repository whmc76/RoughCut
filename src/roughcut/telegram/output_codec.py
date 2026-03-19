from __future__ import annotations

import locale
import re

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_C1_ESCAPE_RE = re.compile(r"\x1b[@-Z\\-_]")
_DEFAULT_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "gb18030",
    "gbk",
    "cp936",
    "big5",
    "cp1252",
    "latin-1",
)


def decode_process_output(raw: bytes | str | None) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return clean_console_text(raw)
    if not raw:
        return ""

    best = ""
    best_score: tuple[int, int, int] | None = None
    for encoding in _candidate_encodings():
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            decoded = raw.decode(encoding, errors="replace")
        cleaned = clean_console_text(decoded)
        score = _score_decoded_text(cleaned)
        if best_score is None or score < best_score:
            best = cleaned
            best_score = score
            if score[0] == 0 and score[1] == 0:
                break
    return best


def clean_console_text(text: str) -> str:
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    normalized = _ANSI_ESCAPE_RE.sub("", normalized)
    normalized = _C1_ESCAPE_RE.sub("", normalized)
    return normalized.strip()


def _candidate_encodings() -> list[str]:
    candidates: list[str] = []
    for name in (
        locale.getpreferredencoding(False),
        "utf-8",
        "utf-8-sig",
        "gb18030",
        "gbk",
        "cp936",
        "big5",
        "cp1252",
        "latin-1",
    ):
        normalized = str(name or "").strip().lower()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    for name in _DEFAULT_ENCODINGS:
        if name not in candidates:
            candidates.append(name)
    return candidates


def _score_decoded_text(text: str) -> tuple[int, int, int]:
    replacement_count = text.count("\ufffd")
    suspicious_count = sum(1 for char in text if ord(char) < 32 and char not in "\n\t")
    cjk_count = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    return (replacement_count, suspicious_count, -cjk_count)
