from pathlib import Path
import subprocess

from scripts.check_open_source_readiness import scan_files, scan_repo


def _write_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_scan_files_flags_backslash_private_workspace_path(tmp_path: Path) -> None:
    private_path = "E:" + "\\WorkSpace\\RoughCut\\data\\output"
    target = _write_text(tmp_path / "config.yml", f"ROOT={private_path}\n")

    findings = scan_files([target])

    assert any("private_project_workspace_root" in item for item in findings)


def test_scan_files_flags_live_secret_patterns(tmp_path: Path) -> None:
    minimax_key = "sk-cp-" + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    telegram_token = "1234567890" + ":ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmno"
    target = _write_text(
        tmp_path / "compose.yml",
        "\n".join(
            (
                f"MINIMAX_API_KEY={minimax_key}",
                f"TELEGRAM_BOT_TOKEN={telegram_token}",
            )
        ),
    )

    findings = scan_files([target])

    assert any("minimax_api_key" in item for item in findings)
    assert any("telegram_bot_token" in item for item in findings)


def test_scan_files_allows_example_email_and_demo_user_dir(tmp_path: Path) -> None:
    target = _write_text(
        tmp_path / "sample.env.example",
        "\n".join(
            (
                "CONTACT=demo.creator@example.com",
                "ROUGHCUT_CODEX_AUTH_HOST_DIR=C:/Users/demo/.codex",
            )
        ),
    )

    findings = scan_files([target])

    assert findings == []


def test_scan_repo_both_flags_sensitive_file_still_present_in_head_after_worktree_delete(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True, capture_output=True, text=True)
    minimax_key = "sk-cp-" + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
    target = _write_text(
        tmp_path / "compose-full.yml",
        f"MINIMAX_API_KEY={minimax_key}\n",
    )
    subprocess.run(["git", "add", "compose-full.yml"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add compose snapshot"], cwd=tmp_path, check=True, capture_output=True, text=True)
    target.unlink()

    worktree_findings = scan_repo(scope="worktree", cwd=tmp_path)
    both_findings = scan_repo(scope="both", cwd=tmp_path)

    assert worktree_findings == []
    assert any(item.startswith("HEAD:compose-full.yml:1: minimax_api_key:") for item in both_findings)
