from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from roughcut.providers.image_generation import mark_codex_imagegen_request_completed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect and finalize RoughCut Codex imagegen requests. "
            "This runner never creates fallback covers; it only marks requests completed after a real imagegen result exists."
        )
    )
    parser.add_argument("root", type=Path, help="Smart-copy material directory or parent folder to scan.")
    parser.add_argument("--complete", type=Path, help="Path to one *.codex-imagegen.json request to complete.")
    parser.add_argument("--result", type=Path, help="Generated bitmap produced by Codex built-in image_gen.")
    parser.add_argument("--list", action="store_true", help="List pending/completed requests as JSON.")
    return parser.parse_args()


def _load_request(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_request_path"] = str(path)
    return payload


def _iter_requests(root: Path) -> list[dict[str, Any]]:
    if root.is_file():
        return [_load_request(root)]
    return [_load_request(path) for path in sorted(root.rglob("*.codex-imagegen.json"))]


def _complete_request(request_path: Path, result_path: Path) -> dict[str, Any]:
    payload = _load_request(request_path)
    output_path = Path(str(payload.get("output_path") or "")).expanduser()
    if not output_path:
        raise ValueError(f"Request does not include output_path: {request_path}")
    if not result_path.exists():
        raise FileNotFoundError(f"Generated result does not exist: {result_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result_path, output_path)
    return mark_codex_imagegen_request_completed(
        request_path=request_path,
        output_path=output_path,
        result_path=result_path,
    )


def main() -> None:
    args = parse_args()
    root = args.root.expanduser()
    if args.complete:
        if args.result is None:
            raise SystemExit("--result is required with --complete")
        completed = _complete_request(args.complete.expanduser(), args.result.expanduser())
        print(json.dumps({"completed": completed}, ensure_ascii=False, indent=2))
        return

    requests = _iter_requests(root)
    print(
        json.dumps(
            {
                "root": str(root),
                "count": len(requests),
                "pending": [item for item in requests if str(item.get("status") or "") != "completed"],
                "completed": [item for item in requests if str(item.get("status") or "") == "completed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
