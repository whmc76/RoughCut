from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from roughcut.testing.manual_clip import run_manual_clip_test


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--channel-profile", default=None)
    parser.add_argument("--sample-seconds", type=int, default=90)
    args = parser.parse_args()

    report = await run_manual_clip_test(
        args.source,
        language=args.language,
        channel_profile=args.channel_profile,
        sample_seconds=args.sample_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
