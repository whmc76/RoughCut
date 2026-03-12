from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

import roughcut.cli as cli_mod


def test_init_creates_project_dirs_and_env(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    (tmp_path / ".env.example").write_text("OUTPUT_DIR=data/output\n", encoding="utf-8")
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir="data/output", render_debug_dir="logs/render-debug"),
    )

    result = runner.invoke(cli_mod.cli, ["init"])

    assert result.exit_code == 0
    assert (tmp_path / "data" / "output").exists()
    assert (tmp_path / "logs" / "render-debug").exists()
    assert (tmp_path / "watch").exists()
    assert (tmp_path / ".env").exists()


def test_doctor_reports_missing_ffmpeg_as_failure(tmp_path: Path, monkeypatch):
    runner = CliRunner()
    monkeypatch.setattr(cli_mod, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_mod,
        "get_settings",
        lambda: SimpleNamespace(output_dir="data/output", render_debug_dir="logs/render-debug"),
    )

    def fake_which(name: str) -> str | None:
        if name in {"ffmpeg", "ffprobe"}:
            return None
        if name == "uv":
            return "C:/tools/uv.exe"
        return None

    monkeypatch.setattr(cli_mod.shutil, "which", fake_which)

    result = runner.invoke(cli_mod.cli, ["doctor"])

    assert result.exit_code == 1
    assert "ffmpeg" in result.output
