from __future__ import annotations

import json
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
