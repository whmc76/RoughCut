from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _candidate_paths() -> list[Path]:
    env_path = str(os.getenv("ROUGHCUT_CODEX_AUTH_FILE") or "").strip()
    paths: list[Path] = []
    if env_path:
        paths.append(Path(env_path))
    paths.append(Path("/host-codex/auth.json"))
    paths.append(Path.home() / ".codex" / "auth.json")
    return paths


def _load_payload() -> dict:
    for candidate in _candidate_paths():
        try:
            if candidate.exists():
                return json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
    raise RuntimeError("Codex auth.json not found")


def main() -> int:
    try:
        payload = _load_payload()
        direct_token = str(payload.get("OPENAI_API_KEY") or "").strip()
        if direct_token:
            sys.stdout.write(direct_token)
            return 0
        token = str(((payload.get("tokens") or {}).get("access_token")) or "").strip()
        if not token:
            raise RuntimeError("Codex access token is missing")
        sys.stdout.write(token)
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
