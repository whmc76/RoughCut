from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path
from typing import Iterable


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
DISALLOWED_PATTERNS: dict[str, re.Pattern[str]] = {
    "personal_windows_user_dir": re.compile(r"[A-Z]:[\\/]+Users[\\/]+(?!demo\b|test\b)[^\\/\s\"']+", re.IGNORECASE),
    "private_eval_workspace_root": re.compile(r"[A-Z]:[\\/]+WorkSpace[\\/]+_eval", re.IGNORECASE),
    "private_project_workspace_root": re.compile(r"[A-Z]:[\\/]+WorkSpace[\\/]+RoughCut", re.IGNORECASE),
    "private_heygem_data_root": re.compile(r"[A-Z]:[\\/]+duix_avatar_data", re.IGNORECASE),
    "private_output_drive": re.compile(r"F:[\\/]+roughcut_outputs", re.IGNORECASE),
    "private_creator_email": re.compile(r"fas\.galactic@gmail\.com", re.IGNORECASE),
    "minimax_api_key": re.compile(r"\bsk-cp-[A-Za-z0-9_-]{40,}\b"),
    "telegram_bot_token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35,}\b"),
}
HEAD_GREP_PATTERNS: dict[str, str] = {
    "personal_windows_user_dir": r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+",
    "private_eval_workspace_root": r"[A-Za-z]:[\\/]+WorkSpace[\\/]+_eval",
    "private_project_workspace_root": r"[A-Za-z]:[\\/]+WorkSpace[\\/]+RoughCut",
    "private_heygem_data_root": r"[A-Za-z]:[\\/]+duix_avatar_data",
    "private_output_drive": r"F:[\\/]+roughcut_outputs",
    "private_creator_email": r"fas\.galactic@gmail\.com",
    "minimax_api_key": r"sk-cp-[A-Za-z0-9_-]{40,}",
    "telegram_bot_token": r"\d{8,10}:[A-Za-z0-9_-]{35,}",
}
TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".bat",
    ".sh",
    ".md",
    ".json",
    ".yml",
    ".yaml",
    ".ts",
    ".tsx",
    ".mjs",
    ".js",
    ".txt",
    ".toml",
    ".ini",
    ".env",
}
TEXT_FILENAMES = {".env.example"}


def _git(args: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )


def _tracked_files(*, cwd: Path | None = None) -> list[Path]:
    result = _git(["ls-files"], cwd=cwd)
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in TEXT_FILENAMES


def _scan_text(text: str, *, display_name: str) -> list[str]:
    findings: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in EMAIL_RE.finditer(line):
            domain = match.group(1).lower()
            if domain == "example.com":
                continue
            findings.append(f"{display_name}:{lineno}: email: {match.group(0)}")
        for label, pattern in DISALLOWED_PATTERNS.items():
            if pattern.search(line):
                findings.append(f"{display_name}:{lineno}: {label}: {line.strip()}")
    return findings


def _parse_git_grep_output(output: str) -> list[tuple[str, int, str]]:
    matches: list[tuple[str, int, str]] = []
    for raw_line in output.splitlines():
        parts = raw_line.split(":", 3)
        if len(parts) != 4:
            continue
        ref_name, path, lineno_text, line = parts
        try:
            lineno = int(lineno_text)
        except ValueError:
            continue
        matches.append((f"{ref_name}:{path}", lineno, line))
    return matches


def scan_files(paths: Iterable[Path]) -> list[str]:
    findings: list[str] = []
    for rel_path in paths:
        if not _is_text_file(rel_path):
            continue
        if not rel_path.exists():
            continue
        try:
            text = rel_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(_scan_text(text, display_name=str(rel_path)))
    return findings


def scan_head_files(paths: Iterable[Path], *, cwd: Path | None = None, ref: str = "HEAD") -> list[str]:
    pathspecs = [rel_path.as_posix() for rel_path in paths if _is_text_file(rel_path)]
    if not pathspecs:
        return []

    findings: list[str] = []
    email_result = _git(["grep", "-n", "-I", "-E", EMAIL_RE.pattern, ref, "--", *pathspecs], cwd=cwd, check=False)
    if email_result.returncode in {0, 1}:
        for display_name, lineno, line in _parse_git_grep_output(email_result.stdout):
            for match in EMAIL_RE.finditer(line):
                domain = match.group(1).lower()
                if domain == "example.com":
                    continue
                findings.append(f"{display_name}:{lineno}: email: {match.group(0)}")
    else:
        raise RuntimeError(f"git grep email scan failed with exit code {email_result.returncode}")

    for label, pattern in DISALLOWED_PATTERNS.items():
        grep_pattern = HEAD_GREP_PATTERNS[label]
        result = _git(["grep", "-n", "-I", "-E", grep_pattern, ref, "--", *pathspecs], cwd=cwd, check=False)
        if result.returncode not in {0, 1}:
            raise RuntimeError(f"git grep scan failed for {label} with exit code {result.returncode}")
        for display_name, lineno, line in _parse_git_grep_output(result.stdout):
            if pattern.search(line):
                findings.append(f"{display_name}:{lineno}: {label}: {line.strip()}")
    return findings


def scan_repo(*, scope: str = "both", cwd: Path | None = None) -> list[str]:
    tracked_files = _tracked_files(cwd=cwd)
    findings: list[str] = []
    if scope in {"worktree", "both"}:
        base = cwd or Path.cwd()
        findings.extend(scan_files(base / rel_path for rel_path in tracked_files))
    if scope in {"head", "both"}:
        findings.extend(scan_head_files(tracked_files, cwd=cwd))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan tracked repo content for open-source release blockers.")
    parser.add_argument(
        "--scope",
        choices=("worktree", "head", "both"),
        default="both",
        help="Scan the current worktree, the committed HEAD snapshot, or both (default).",
    )
    args = parser.parse_args()

    findings = scan_repo(scope=args.scope)

    if findings:
        print("open-source-readiness: failed")
        for item in findings:
            print(item)
        return 1

    print("open-source-readiness: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
