from __future__ import annotations

from pathlib import Path

import roughcut.telegram.acp_bridge as bridge_mod


def test_build_backend_command_uses_claude_defaults(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.delenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND", raising=False)
    monkeypatch.delenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL", raising=False)
    monkeypatch.delenv("TELEGRAM_AGENT_CLAUDE_MODEL", raising=False)
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/claude.exe")

    command, cwd, timeout = bridge_mod.build_backend_command(
        {"repo_root": str(tmp_path), "prompt": "检查代码"}
    )

    assert command[0] == "C:/tools/claude.exe"
    assert "--permission-mode" in command
    assert cwd == tmp_path.resolve()
    assert timeout == 900


def test_build_backend_command_passes_claude_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL", "opus")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/claude.exe")

    command, cwd, timeout = bridge_mod.build_backend_command(
        {"repo_root": str(tmp_path), "prompt": "检查代码"}
    )

    assert "--model" in command
    assert command[command.index("--model") + 1] == "opus"
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


def test_build_backend_command_supports_codex(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "codex")
    monkeypatch.delenv("ROUGHCUT_ACP_BRIDGE_CODEX_COMMAND", raising=False)
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/codex.exe")

    command, cwd, timeout = bridge_mod.build_backend_command(
        {"repo_root": str(tmp_path), "prompt": "分析 telegram agent"}
    )

    assert command[0] == "C:/tools/codex.exe"
    assert "-m" in command
    assert command[command.index("-m") + 1] == "gpt-5.4-mini"
    assert "exec" in command
    assert "-s" in command
    assert cwd == tmp_path.resolve()
    assert timeout == 900


def test_run_bridge_reads_codex_last_message_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "codex")
    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/codex.exe")

    class FakeTempDir:
        def __init__(self, path: Path):
            self.name = str(path)

        def cleanup(self):
            return None

    monkeypatch.setattr(
        bridge_mod.tempfile,
        "TemporaryDirectory",
        lambda prefix: FakeTempDir(tmp_path / "codex-temp"),
    )

    class FakeResult:
        returncode = 0
        stdout = "stream output"
        stderr = ""

    def fake_run(command, *args, **kwargs):
        output_path = Path(command[command.index("-o") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("bridge codex ok", encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr(bridge_mod.subprocess, "run", fake_run)

    result = bridge_mod.run_bridge({"repo_root": str(tmp_path), "prompt": "检查代码"})

    assert result["provider"] == "acp"
    assert result["backend"] == "codex"
    assert result["excerpt"] == "bridge codex ok"


def test_run_bridge_falls_back_to_codex_when_claude_fails(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_BACKEND", "claude")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND", "codex")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL", "opus")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_MODEL", "gpt-5.4-mini")
    monkeypatch.setattr(
        bridge_mod.shutil,
        "which",
        lambda name: f"C:/tools/{name}.exe",
    )

    class FakeTempDir:
        def __init__(self, path: Path):
            self.name = str(path)

        def cleanup(self):
            return None

    monkeypatch.setattr(
        bridge_mod.tempfile,
        "TemporaryDirectory",
        lambda prefix: FakeTempDir(tmp_path / "codex-temp"),
    )

    class FakeClaudeFailure:
        returncode = 1
        stdout = ""
        stderr = "claude failed"

    class FakeCodexSuccess:
        returncode = 0
        stdout = "stream output"
        stderr = ""

    calls: list[list[str]] = []

    def fake_run(command, *args, **kwargs):
        calls.append(command)
        if command[0].endswith("claude.exe"):
            return FakeClaudeFailure()
        output_path = Path(command[command.index("-o") + 1])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("bridge codex fallback ok", encoding="utf-8")
        return FakeCodexSuccess()

    monkeypatch.setattr(bridge_mod.subprocess, "run", fake_run)

    result = bridge_mod.run_bridge({"repo_root": str(tmp_path), "prompt": "检查代码"})

    assert len(calls) == 2
    assert calls[0][0].endswith("claude.exe")
    assert calls[1][0].endswith("codex.exe")
    assert result["backend"] == "codex"
    assert result["fallback_from"] == "claude"
    assert result["excerpt"] == "bridge codex fallback ok"
