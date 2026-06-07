from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.review.intelligent_copy import promote_platform_preview_to_intelligent_copy_result


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote a local preview JSON into canonical smart-copy production files.")
    parser.add_argument("--folder-path", required=True, help="Source folder or smart-copy dir")
    parser.add_argument("--preview-json", required=True, help="Preview JSON path")
    parser.add_argument("--platform", action="append", default=[], help="Optional platform key to promote; repeatable")
    parser.add_argument("--creator-profile-id", default="", help="Optional creator profile id used to rebuild publication metadata")
    parser.add_argument("--creator-profile-name", default="", help="Optional creator profile display name")
    parser.add_argument("--browser", default="chrome", help="Browser binding to use when rebuilding publication metadata")
    parser.add_argument("--output", default="", help="Optional output JSON path for the updated result")
    args = parser.parse_args()

    result = promote_platform_preview_to_intelligent_copy_result(
        args.folder_path,
        preview_path=args.preview_json,
        platforms=list(args.platform or []) or None,
        creator_profile_id=str(args.creator_profile_id or "").strip() or None,
        creator_profile_name=str(args.creator_profile_name or "").strip() or None,
        browser=str(args.browser or "chrome").strip() or "chrome",
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if str(args.output or "").strip():
        Path(args.output).expanduser().write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
