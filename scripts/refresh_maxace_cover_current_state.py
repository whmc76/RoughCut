from __future__ import annotations

import argparse
import asyncio
import json
import sys

from roughcut.review.intelligent_copy import refresh_existing_intelligent_copy_cover_current_state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh MAXACE smart-copy current state from existing cover requests and outputs.")
    parser.add_argument(
        "--folder",
        default=r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱",
        help="Source folder containing the smart-copy directory.",
    )
    parser.add_argument(
        "--creator-profile-name",
        default="FAS",
        help="Optional creator profile display name to keep in publication context.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    result = await refresh_existing_intelligent_copy_cover_current_state(
        args.folder,
        creator_profile_name=str(args.creator_profile_name or "").strip() or None,
    )
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(_main())
