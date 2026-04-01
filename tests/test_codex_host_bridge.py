from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.host import codex_bridge as bridge_mod


def test_run_codex_exec_uses_local_codex_cli(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}

    class FakeResult:
        returncode = 0
        stdout = "stream output"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        output_path = Path(command[command.index("-o") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("host bridge ok", encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/codex.exe")
    monkeypatch.setattr(bridge_mod.subprocess, "run", fake_run)

    result = bridge_mod.run_codex_exec(
        {
            "repo_root": str(tmp_path),
            "prompt": "检查代码",
            "model": "gpt-5.4-mini",
            "sandbox": "danger-full-access",
            "timeout_sec": 45,
        }
    )

    assert captured["command"][0] == "C:/tools/codex.exe"
    assert captured["command"][captured["command"].index("-m") + 1] == "gpt-5.4-mini"
    assert result["backend"] == "codex"
    assert result["host_bridge"] is True
    assert result["excerpt"] == "host bridge ok"


def test_run_codex_exec_rejects_missing_prompt(tmp_path: Path):
    with pytest.raises(ValueError, match="prompt is required"):
        bridge_mod.run_codex_exec({"repo_root": str(tmp_path), "prompt": ""})
