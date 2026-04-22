from __future__ import annotations

import subprocess

from roughcut.naming import normalize_auth_mode


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
