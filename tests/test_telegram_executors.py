from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import roughcut.telegram.executors as executors_mod


def test_execute_acp_preset_parses_bridge_json(monkeypatch, tmp_path):
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )

    class FakeResult:
        returncode = 0
        stdout = json.dumps(
            {
                "stdout": "bridge output",
                "stderr": "",
                "excerpt": "short summary",
            },
            ensure_ascii=False,
        )
        stderr = ""

    monkeypatch.setattr(executors_mod.subprocess, "run", lambda *args, **kwargs: FakeResult())

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="做一件事",
        scope_path="src",
        job_id="job-1",
    )

    assert result["provider"] == "acp"
    assert result["stdout"] == "bridge output"
    assert result["excerpt"] == "short summary"


def test_execute_acp_preset_falls_back_to_builtin_bridge(monkeypatch, tmp_path):
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_acp_command="",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False)
        stderr = ""

    def fake_run(command, *args, **kwargs):
        captured["command"] = command
        return FakeResult()

    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="做一件事",
        scope_path="src",
        job_id="job-1",
    )

    assert "scripts\\acp_bridge.py" in captured["command"] or "scripts/acp_bridge.py" in captured["command"]
    assert result["excerpt"] == "ok"


def test_execute_codex_preset_reads_last_message_file(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )
    monkeypatch.setattr(executors_mod.shutil, "which", lambda name: "C:/tools/codex.exe")

    class FakeTempDir:
        def __init__(self, path: Path):
            self.name = str(path)

        def __enter__(self):
            return self.name

        def __exit__(self, exc_type, exc, tb):
            return None

    def fake_tempdir(prefix: str):
        path = tmp_path / "codex-temp"
        path.mkdir(parents=True, exist_ok=True)
        return FakeTempDir(path)

    class FakeResult:
        returncode = 0
        stdout = "stream output"
        stderr = ""

    captured = {}

    def fake_run(command, *args, **kwargs):
        captured["command"] = command
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("codex final output", encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr(executors_mod.tempfile, "TemporaryDirectory", fake_tempdir)
    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        provider="codex",
        preset="plan",
        task_text="分析 telegram agent",
        scope_path="src",
        job_id="job-1",
    )

    assert result["provider"] == "codex"
    assert result["stdout"] == "codex final output"
    assert result["excerpt"] == "codex final output"
    assert "-a" in captured["command"]
