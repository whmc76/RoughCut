from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_API_BASE = "http://127.0.0.1:38471/api/v1"


@dataclass(frozen=True)
class SampleSpec:
    job_id: str
    name: str
    expected_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]


SAMPLES = (
    SampleSpec(
        job_id="b5248dd9-b219-4ad0-a74a-9b360d8b7492",
        name="noc_mt34",
        expected_terms=(
            "小玩具啊",
            "这个也是",
            "欧气啊",
            "我靠",
            "没想到啊",
            "但是呢",
            "不过好在呢",
            "发售啊",
        ),
        forbidden_terms=("发烧啊", "两次发烧"),
    ),
    SampleSpec(
        job_id="fb30a42c-1af1-4c78-b065-bc3cd4004b2e",
        name="nitecore_edc17",
        expected_terms=(
            "今天我们直奔主题啊",
            "大家看到",
            "EDC17",
            "EDC37",
        ),
        forbidden_terms=("EDEDC17", "EDEDC37", "是是", "电池池"),
    ),
)


ASCII_MODEL_DUPLICATE_RE = re.compile(r"\b(?:EDC|NOC|NITECORE|UV)(?:EDC|NOC|NITECORE|UV)+\d*\b", re.IGNORECASE)
CJK_BOUNDARY_DUPLICATE_RE = re.compile(r"([\u4e00-\u9fff])\1")
KNOWN_REAL_DUPLICATES = {"看看", "慢慢", "常常", "刚刚", "哥哥", "弟弟", "谢谢", "讲讲", "静静", "试试", "轻轻", "削削", "点点", "好好好", "对对对"}


def fetch_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def subtitle_text(item: dict[str, Any]) -> str:
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")


def joined_text(rows: list[dict[str, Any]]) -> str:
    return "".join(subtitle_text(item) for item in rows)


def duplicate_snippets(text: str, limit: int = 24) -> list[str]:
    snippets: list[str] = []
    for match in ASCII_MODEL_DUPLICATE_RE.finditer(text):
        snippets.append(match.group(0))
    for match in CJK_BOUNDARY_DUPLICATE_RE.finditer(text):
        start = max(0, match.start() - 8)
        end = min(len(text), match.end() + 8)
        snippet = text[start:end]
        if any(real in snippet for real in KNOWN_REAL_DUPLICATES):
            continue
        snippets.append(snippet)
    return list(dict.fromkeys(snippets))[:limit]


def analyze_sample(api_base: str, sample: SampleSpec) -> dict[str, Any]:
    session = fetch_json(f"{api_base.rstrip('/')}/jobs/{sample.job_id}/manual-editor")
    source_rows = list(session.get("source_subtitles") or [])
    projected_rows = list(session.get("projected_subtitles") or [])
    source_text = joined_text(source_rows)
    projected_text = joined_text(projected_rows)
    term_rows = []
    for term in sample.expected_terms:
        term_rows.append(
            {
                "term": term,
                "source": term in source_text,
                "projected": term in projected_text,
            }
        )
    forbidden_rows = []
    for term in sample.forbidden_terms:
        forbidden_rows.append(
            {
                "term": term,
                "source": term in source_text,
                "projected": term in projected_text,
            }
        )
    return {
        "name": sample.name,
        "job_id": sample.job_id,
        "source_name": session.get("source_name"),
        "counts": {
            "source_subtitles": len(source_rows),
            "projected_subtitles": len(projected_rows),
            "keep_segments": len(session.get("keep_segments") or []),
            "smart_delete_segments": len(session.get("smart_delete_segments") or []),
        },
        "expected_terms": term_rows,
        "forbidden_terms": forbidden_rows,
        "source_duplicate_snippets": duplicate_snippets(source_text),
        "projected_duplicate_snippets": duplicate_snippets(projected_text),
        "source_head": source_text[:700],
        "projected_head": projected_text[:700],
    }


def has_failure(result: dict[str, Any]) -> bool:
    expected_failed = any(not row["source"] or not row["projected"] for row in result["expected_terms"])
    forbidden_failed = any(row["source"] or row["projected"] for row in result["forbidden_terms"])
    duplicate_failed = bool(result["projected_duplicate_snippets"])
    return expected_failed or forbidden_failed or duplicate_failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    args = parser.parse_args()

    results = [analyze_sample(args.api_base, sample) for sample in SAMPLES]
    if args.json:
        print(json.dumps(results, ensure_ascii=True, indent=2))
    else:
        for result in results:
            print(f"[{result['name']}] {result['source_name']}")
            print(f"  counts: {result['counts']}")
            for row in result["expected_terms"]:
                status = "ok" if row["source"] and row["projected"] else "MISS"
                print(f"  expected {status}: {row['term']} source={row['source']} projected={row['projected']}")
            for row in result["forbidden_terms"]:
                status = "BAD" if row["source"] or row["projected"] else "ok"
                print(f"  forbidden {status}: {row['term']} source={row['source']} projected={row['projected']}")
            if result["projected_duplicate_snippets"]:
                print(f"  projected duplicates: {', '.join(result['projected_duplicate_snippets'])}")
            else:
                print("  projected duplicates: none")
    return 1 if any(has_failure(result) for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
