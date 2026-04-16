from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import roughcut.telegram.executors as executors_mod


def _stub_isolated_workspace(monkeypatch, tmp_path: Path) -> Path:
    workspace = tmp_path / "worktree"
    workspace.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        executors_mod,
        "_prepare_execution_workspace",
        lambda **kwargs: executors_mod.ExecutionWorkspace(
            repo_root=tmp_path,
            cwd=workspace,
            workspace_mode="git_worktree",
            workspace_root=workspace,
        ),
    )
    return workspace


def test_execute_acp_preset_parses_bridge_json(monkeypatch, tmp_path):
    workspace = _stub_isolated_workspace(monkeypatch, tmp_path)
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
        ).encode("utf-8")
        stderr = b""

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
    assert result["workspace_mode"] == "git_worktree"
    assert result["workspace_root"] == str(workspace)


def test_execute_acp_preset_falls_back_to_builtin_bridge(monkeypatch, tmp_path):
    _stub_isolated_workspace(monkeypatch, tmp_path)
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
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False).encode("utf-8")
        stderr = b""

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


def test_execute_acp_preset_passes_claude_model_to_bridge_env(monkeypatch, tmp_path):
    _stub_isolated_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            acp_bridge_backend="claude",
            acp_bridge_fallback_backend="codex",
            acp_bridge_claude_model="opus",
            acp_bridge_codex_command="codex",
            acp_bridge_codex_model="gpt-5.4-mini",
            telegram_agent_claude_enabled=True,
            telegram_agent_claude_command="claude",
            telegram_agent_codex_command="codex",
            telegram_agent_codex_model="",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False).encode("utf-8")
        stderr = b""

    def fake_run(command, *args, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return FakeResult()

    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="做一件事",
        scope_path="src",
        job_id="job-1",
    )

    assert captured["env"]["TELEGRAM_AGENT_CLAUDE_MODEL"] == "opus"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL"] == "opus"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_BACKEND"] == "claude"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND"] == "codex"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_CODEX_MODEL"] == "gpt-5.4-mini"
    assert result["excerpt"] == "ok"


def test_execute_acp_preset_auto_follows_hybrid_models_when_fields_blank(monkeypatch, tmp_path):
    _stub_isolated_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            llm_routing_mode="hybrid_performance",
            hybrid_analysis_provider="openai",
            hybrid_analysis_model="gpt-5.4",
            hybrid_copy_provider="anthropic",
            hybrid_copy_model="claude-sonnet-4-20250514",
            acp_bridge_backend="",
            acp_bridge_fallback_backend="",
            acp_bridge_claude_model="",
            acp_bridge_codex_command="codex",
            acp_bridge_codex_model="",
            telegram_agent_claude_enabled=True,
            telegram_agent_claude_command="claude",
            telegram_agent_claude_model="",
            telegram_agent_codex_command="codex",
            telegram_agent_codex_model="",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
            active_reasoning_provider="openai",
            active_reasoning_model="gpt-5.4",
        ),
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False).encode("utf-8")
        stderr = b""

    def fake_run(command, *args, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return FakeResult()

    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="做一件事",
        scope_path="src",
        job_id="job-1",
    )

    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_BACKEND"] == "codex"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND"] == "claude"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_CODEX_MODEL"] == "gpt-5.4"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_CLAUDE_MODEL"] == "claude-sonnet-4-20250514"
    assert result["excerpt"] == "ok"


def test_execute_acp_preset_includes_task_context_in_bridge_payload(monkeypatch, tmp_path):
    workspace = _stub_isolated_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            acp_bridge_backend="codex",
            acp_bridge_fallback_backend="claude",
            acp_bridge_claude_model="opus",
            acp_bridge_codex_command="codex",
            acp_bridge_codex_model="gpt-5.4-mini",
            telegram_agent_claude_enabled=True,
            telegram_agent_claude_command="claude",
            telegram_agent_codex_command="codex",
            telegram_agent_codex_model="gpt-5.4-mini",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
            telegram_agent_state_dir=str(tmp_path),
        ),
    )

    store = executors_mod.TelegramAgentTaskStore(tmp_path / "tasks.json")
    store.create_record(
        chat_id="chat-1",
        provider="acp",
        preset="triage",
        task_text="排查上一次失败",
        status="success",
        confirmation_required=False,
        task_id="old-task",
    )
    store.update("old-task", result_excerpt="上一次确认是 ACP bridge fallback 导致的命令缺失。")

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False).encode("utf-8")
        stderr = b""

    def fake_run(command, *args, **kwargs):
        captured["payload"] = json.loads(kwargs["input"].decode("utf-8"))
        captured["env"] = kwargs.get("env", {})
        return FakeResult()

    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        task_id="new-task",
        chat_id="chat-1",
        provider="acp",
        preset="extend",
        task_text="增强 Telegram agent",
        scope_path="src/roughcut/telegram",
        job_id="job-1",
    )

    assert captured["payload"]["task_id"] == "new-task"
    assert captured["payload"]["chat_id"] == "chat-1"
    assert "项目规则与默认约束" in captured["payload"]["prompt"]
    assert "同会话近期任务记忆" in captured["payload"]["prompt"]
    assert "ACP bridge fallback" in captured["payload"]["prompt"]
    assert captured["env"]["ROUGHCUT_AGENT_TASK_ID"] == "new-task"
    assert captured["env"]["ROUGHCUT_AGENT_CHAT_ID"] == "chat-1"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_BACKEND"] == "codex"
    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_FALLBACK_BACKEND"] == "claude"
    assert str(workspace) in captured["payload"]["prompt"]
    assert result["excerpt"] == "ok"


def test_execute_acp_preset_skips_disabled_claude_backend(monkeypatch, tmp_path):
    _stub_isolated_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            acp_bridge_backend="claude",
            acp_bridge_fallback_backend="codex",
            acp_bridge_claude_model="opus",
            acp_bridge_codex_command="codex",
            acp_bridge_codex_model="gpt-5.4-mini",
            telegram_agent_claude_enabled=False,
            telegram_agent_claude_command="claude",
            telegram_agent_codex_command="codex",
            telegram_agent_codex_model="gpt-5.4-mini",
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )

    captured = {}

    class FakeResult:
        returncode = 0
        stdout = json.dumps({"stdout": "ok", "stderr": "", "excerpt": "ok"}, ensure_ascii=False).encode("utf-8")
        stderr = b""

    def fake_run(command, *args, **kwargs):
        captured["env"] = kwargs.get("env", {})
        return FakeResult()

    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="做一件事",
        scope_path="src",
        job_id="job-1",
    )

    assert captured["env"]["ROUGHCUT_ACP_BRIDGE_BACKEND"] == "codex"
    assert "ROUGHCUT_ACP_BRIDGE_CLAUDE_COMMAND" not in captured["env"]
    assert "TELEGRAM_AGENT_CLAUDE_COMMAND" not in captured["env"]
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
        stdout = b"stream output"
        stderr = b""

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


def test_execute_codex_preset_auto_follows_openai_hybrid_model(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            llm_routing_mode="hybrid_performance",
            hybrid_analysis_provider="openai",
            hybrid_analysis_model="gpt-5.4",
            hybrid_copy_provider="anthropic",
            hybrid_copy_model="claude-sonnet-4-20250514",
            telegram_agent_codex_model="",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
            active_reasoning_provider="openai",
            active_reasoning_model="gpt-5.4",
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
        stdout = b"stream output"
        stderr = b""

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

    assert captured["command"][captured["command"].index("-m") + 1] == "gpt-5.4"
    assert result["excerpt"] == "codex final output"


def test_execute_codex_build_preset_uses_isolated_workspace_and_writable_sandbox(monkeypatch, tmp_path: Path):
    workspace = _stub_isolated_workspace(monkeypatch, tmp_path)
    monkeypatch.setenv("TELEGRAM_AGENT_CODEX_COMMAND", "codex")
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_codex_model="",
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
        path = tmp_path / "codex-build-temp"
        path.mkdir(parents=True, exist_ok=True)
        return FakeTempDir(path)

    class FakeResult:
        returncode = 0
        stdout = b"stream output"
        stderr = b""

    captured = {}

    def fake_run(command, *args, **kwargs):
        captured["command"] = command
        captured["cwd"] = kwargs.get("cwd")
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text("build ok", encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr(executors_mod.tempfile, "TemporaryDirectory", fake_tempdir)
    monkeypatch.setattr(executors_mod.subprocess, "run", fake_run)

    result = executors_mod.execute_agent_preset(
        task_id="build-task",
        provider="codex",
        preset="build",
        task_text="执行 pnpm build 并回报结果",
        scope_path="frontend",
        job_id="job-build",
    )

    assert captured["command"][captured["command"].index("-C") + 1] == str(workspace)
    assert captured["command"][captured["command"].index("-s") + 1] == "danger-full-access"
    assert captured["cwd"] == str(workspace)
    assert result["workspace_mode"] == "git_worktree"
    assert result["workspace_root"] == str(workspace)


def test_execute_claude_preset_decodes_gb18030_stdout(monkeypatch):
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_claude_enabled=True,
            telegram_agent_claude_command="claude",
            telegram_agent_claude_model="",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )
    monkeypatch.setattr(executors_mod.shutil, "which", lambda name: "C:/tools/claude.exe")

    expected = "结论：当前 ACP bridge 默认不会指定模型。"

    class FakeResult:
        returncode = 0
        stdout = expected.encode("gb18030")
        stderr = b""

    monkeypatch.setattr(executors_mod.subprocess, "run", lambda *args, **kwargs: FakeResult())

    result = executors_mod.execute_agent_preset(
        provider="claude",
        preset="inspect",
        task_text="检查编码",
        scope_path="src",
        job_id="job-1",
    )

    assert result["stdout"] == expected
    assert result["excerpt"] == expected


def test_execute_acp_preset_decodes_non_utf8_bridge_json(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "worktree"
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_acp_command="python scripts/acp_bridge.py",
            telegram_agent_task_timeout_sec=900,
            telegram_agent_result_max_chars=3500,
        ),
    )

    payload = {
        "stdout": "结论：bridge 输出已恢复正常。",
        "stderr": "",
        "excerpt": "结论：bridge 输出已恢复正常。",
    }

    class FakeResult:
        returncode = 0
        stdout = json.dumps(payload, ensure_ascii=False).encode("gb18030")
        stderr = b""

    monkeypatch.setattr(
        executors_mod,
        "_prepare_execution_workspace",
        lambda **kwargs: executors_mod.ExecutionWorkspace(
            repo_root=workspace,
            cwd=workspace,
            workspace_mode="git_worktree",
            workspace_root=workspace,
        ),
    )
    monkeypatch.setattr(executors_mod.subprocess, "run", lambda *args, **kwargs: FakeResult())

    result = executors_mod.execute_agent_preset(
        provider="acp",
        preset="delegate",
        task_text="修复乱码",
        scope_path="src",
        job_id="job-1",
    )

    assert result["stdout"] == payload["stdout"]
    assert result["excerpt"] == payload["excerpt"]
    assert result["workspace_mode"] == "git_worktree"


def test_render_prompt_appends_project_rules_and_recent_task_memory(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        executors_mod,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_agent_state_dir=str(tmp_path),
        ),
    )
    store = executors_mod.TelegramAgentTaskStore(tmp_path / "tasks.json")
    store.create_record(
        chat_id="chat-1",
        provider="acp",
        preset="triage",
        task_text="分析 Telegram agent 链路",
        status="success",
        confirmation_required=False,
        task_id="task-1",
    )
    store.update("task-1", result_excerpt="确认 ACP->Codex 已可执行，但缺少记忆注入。")

    prompt = executors_mod._render_prompt(
        task_id="task-2",
        chat_id="chat-1",
        provider="acp",
        preset="extend",
        task_text="增强工程能力",
        scope_path="src/roughcut/telegram",
        job_id="job-2",
        workspace_mode="git_worktree",
        workspace_root=str(tmp_path / "worktree"),
    )

    assert "项目规则与默认约束" in prompt
    assert "同会话近期任务记忆" in prompt
    assert "缺少记忆注入" in prompt
    assert "当前优先关注范围：src/roughcut/telegram" in prompt
    assert "当前在隔离 worktree 中执行" in prompt
