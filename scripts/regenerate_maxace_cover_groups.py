from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from roughcut.review.intelligent_copy import rerender_existing_intelligent_copy_cover_groups


SMART_COPY_PARENT = Path(
    r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Regenerate MAXACE cover groups from existing smart-copy packaging context.")
    parser.add_argument(
        "--folder",
        default=str(SMART_COPY_PARENT),
        help="Source folder containing the video and smart-copy directory.",
    )
    parser.add_argument(
        "--platform",
        action="append",
        dest="platforms",
        help="Optional platform key to limit rerendering. Can be repeated.",
    )
    parser.add_argument(
        "--refresh-source",
        action="store_true",
        help="Force rerunning highlight/source selection instead of reusing the current verified source frame.",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    result = await rerender_existing_intelligent_copy_cover_groups(
        args.folder,
        platforms=args.platforms,
        refresh_cover_source=bool(args.refresh_source),
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    asyncio.run(_main())
