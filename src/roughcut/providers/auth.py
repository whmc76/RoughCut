from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from roughcut.naming import normalize_auth_mode


def _read_codex_access_token_from_auth_file() -> str:
    candidates: list[Path] = []
    env_path = str(os.getenv("ROUGHCUT_CODEX_AUTH_FILE") or "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/host-codex/auth.json"))
    candidates.append(Path.home() / ".codex" / "auth.json")

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        direct_token = str(payload.get("OPENAI_API_KEY") or "").strip()
        if direct_token:
            return direct_token
        access_token = str(((payload.get("tokens") or {}).get("access_token")) or "").strip()
        if access_token:
            return access_token
    raise RuntimeError("Codex auth.json not found or missing access token")


def _helper_command_uses_codex_token_file(helper_command: str) -> bool:
    normalized = str(helper_command or "").replace("\\", "/").strip().lower()
    return "print_codex_access_token.py" in normalized


def resolve_credential(
    *,
    mode: str,
    direct_value: str,
    helper_command: str,
    provider_name: str,
) -> str:
    normalized_mode = normalize_auth_mode(mode)
    value = direct_value.strip()
    if normalized_mode == "api_key":
        if not value:
            raise ValueError(f"{provider_name} API credential is not configured")
        return value

    if helper_command.strip():
        if _helper_command_uses_codex_token_file(helper_command):
            script_candidates = [
                part
                for part in helper_command.strip().split()
                if "print_codex_access_token.py" in part.replace("\\", "/")
            ]
            if script_candidates and not Path(script_candidates[0]).exists():
                return _read_codex_access_token_from_auth_file()
        result = subprocess.run(
            helper_command,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{provider_name} helper command failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        token = result.stdout.strip()
        if not token:
            raise RuntimeError(f"{provider_name} helper command returned an empty credential")
        return token

    if value:
        return value

    raise ValueError(
        f"{provider_name} is set to helper auth mode but no helper command or token is configured"
    )
