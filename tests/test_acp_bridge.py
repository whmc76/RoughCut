from __future__ import annotations

from pathlib import Path

import roughcut.telegram.acp_bridge as bridge_mod


def test_build_backend_command_uses_claude_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.delenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND", raising=False)
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/claude.exe")

    command, cwd, timeout = bridge_mod.build_backend_command(
        {"repo_root": str(tmp_path), "prompt": "检查代码"}
    )

    assert command[0] == "C:/tools/claude.exe"
    assert "--permission-mode" in command
    assert cwd == tmp_path.resolve()
    assert timeout == 900


def test_run_bridge_returns_json_payload(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/claude.exe")

    class FakeResult:
        returncode = 0
        stdout = "bridge ok"
        stderr = ""

    monkeypatch.setattr(bridge_mod.subprocess, "run", lambda *args, **kwargs: FakeResult())

    result = bridge_mod.run_bridge({"repo_root": str(tmp_path), "prompt": "检查代码"})

    assert result["provider"] == "acp"
    assert result["backend"] == "claude"
    assert result["excerpt"] == "bridge ok"
