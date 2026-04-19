from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _read_query() -> str:
    query = str(os.getenv("ROUGHCUT_SEARCH_QUERY") or "").strip()
    if not query:
        raise RuntimeError("ROUGHCUT_SEARCH_QUERY is empty")
    return query


def _read_max_results() -> int:
    raw = str(os.getenv("ROUGHCUT_SEARCH_MAX_RESULTS") or "5").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 5
    return max(1, min(value, 10))


def _resolve_command() -> str:
    command_name = str(os.getenv("ROUGHCUT_CODEX_SEARCH_COMMAND") or "codex").strip() or "codex"
    resolved = shutil.which(command_name)
    if not resolved:
        raise RuntimeError(f"Codex command not found in PATH: {command_name}")
    return resolved


def _build_command_prefix(resolved: str) -> list[str]:
    suffix = Path(resolved).suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        return ["cmd", "/c", resolved]
    return [resolved]


def _resolve_workdir() -> Path:
    configured = str(os.getenv("ROUGHCUT_CODEX_SEARCH_WORKDIR") or "").strip()
    if configured:
        return Path(configured).resolve()
    return Path.cwd().resolve()


def _build_prompt(query: str, max_results: int) -> str:
    return (
        f'Search the web for "{query}". '
        "Return only JSON with this exact shape: "
        '{"results":[{"title":"...","url":"...","snippet":"..."}]}. '
        f"Include at most {max_results} items. "
        "Do not wrap the JSON in markdown fences."
    )


def _extract_json_payload(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Codex search helper did not return JSON")
    return json.loads(text[start : end + 1])


def _normalize_results(payload: dict, max_results: int) -> dict[str, list[dict[str, str]]]:
    items = payload.get("results") if isinstance(payload, dict) else []
    results: list[dict[str, str]] = []
    for item in list(items or [])[:max_results]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": str(item.get("title") or "").strip(),
                "url": str(item.get("url") or "").strip(),
                "snippet": str(item.get("snippet") or item.get("content") or "").strip(),
            }
        )
    return {"results": results}


def main() -> int:
    try:
        query = _read_query()
        max_results = _read_max_results()
        resolved = _resolve_command()
        workdir = _resolve_workdir()
        model_name = str(os.getenv("ROUGHCUT_CODEX_SEARCH_MODEL") or "").strip()
        sandbox_mode = str(os.getenv("ROUGHCUT_CODEX_SEARCH_SANDBOX") or "danger-full-access").strip()
        timeout_sec = max(30, int(str(os.getenv("ROUGHCUT_CODEX_SEARCH_TIMEOUT_SEC") or "180").strip() or "180"))
        prompt = _build_prompt(query, max_results)

        with tempfile.TemporaryDirectory(prefix="roughcut-codex-search-") as temp_dir:
            output_path = Path(temp_dir) / "codex-search-output.txt"
            command = _build_command_prefix(resolved)
            command.extend(["-a", "never"])
            if model_name:
                command.extend(["-m", model_name])
            command.extend(
                [
                    "exec",
                    "--color",
                    "never",
                    "-C",
                    str(workdir),
                    "-s",
                    sandbox_mode,
                    "-o",
                    str(output_path),
                    prompt,
                ]
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_sec,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            raw = output_path.read_text(encoding="utf-8", errors="replace") if output_path.exists() else result.stdout
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or raw.strip() or f"codex exited with code {result.returncode}")

        payload = _extract_json_payload(raw)
        sys.stdout.write(json.dumps(_normalize_results(payload, max_results), ensure_ascii=False))
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
