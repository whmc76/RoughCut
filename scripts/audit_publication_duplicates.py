from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.publication_duplicate_audit import (
    audit_duplicate_publications,
)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    report = await audit_duplicate_publications(
        creator_profile_ids=[str(args.creator_profile_id).strip()] if str(args.creator_profile_id).strip() else [],
        platforms=[str(args.platform).strip()] if str(args.platform).strip() else [],
        media_path=str(args.media_path or "").strip(),
        limit=int(args.limit or 0),
    )
    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit historical publication attempts for duplicate publish risks.")
    parser.add_argument("--creator-profile-id", default="", help="Optional creator_profile_id filter.")
    parser.add_argument("--platform", default="", help="Optional platform filter, e.g. douyin / toutiao.")
    parser.add_argument("--media-path", default="", help="Optional media path filter for current live content.")
    parser.add_argument("--limit", type=int, default=50, help="Max suspicious groups to include in output.")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()
    report = asyncio.run(_run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
