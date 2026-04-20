from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.host import codex_bridge as bridge_mod


def test_run_codex_exec_uses_local_codex_cli(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}
    original_exists = bridge_mod.Path.exists

    class FakeProcess:
        returncode = 0
        pid = 4321

        def __init__(self, command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            self.command = command

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            captured["timeout"] = timeout
            output_path = Path(self.command[self.command.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("host bridge ok", encoding="utf-8")
            return (b"stream output", b"")

    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/codex.cmd")
    monkeypatch.setattr(
        bridge_mod.Path,
        "exists",
        lambda self: str(self).replace("\\", "/") in {"C:/tools/codex.exe"} or original_exists(self),
    )
    monkeypatch.setattr(bridge_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(*args, **kwargs))
    monkeypatch.setattr(
        bridge_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("taskkill should not be called on success")),
    )

    result = bridge_mod.run_codex_exec(
        {
            "repo_root": str(tmp_path),
            "prompt": "检查代码",
            "model": "gpt-5.4-mini",
            "sandbox": "danger-full-access",
            "timeout_sec": 45,
            "output_schema": {"type": "object"},
        }
    )

    assert captured["command"][0].replace("\\", "/") == "C:/tools/codex.exe"
    assert captured["command"][captured["command"].index("-m") + 1] == "gpt-5.4-mini"
    assert "--output-schema" in captured["command"]
    assert captured["command"][-1] == "-"
    assert captured["input"] == "检查代码".encode("utf-8")
    assert captured["timeout"] == 45
    assert result["backend"] == "codex"
    assert result["host_bridge"] is True
    assert result["excerpt"] == "host bridge ok"


def test_run_codex_exec_rejects_missing_prompt(tmp_path: Path):
    with pytest.raises(ValueError, match="prompt is required"):
        bridge_mod.run_codex_exec({"repo_root": str(tmp_path), "prompt": ""})


def test_run_codex_exec_kills_process_tree_on_timeout(monkeypatch, tmp_path: Path):
    taskkill_commands: list[list[str]] = []
    original_exists = bridge_mod.Path.exists

    class FakeProcess:
        returncode = 1
        pid = 24680

        def communicate(self, input=None, timeout=None):
            if timeout == 35:
                raise bridge_mod.subprocess.TimeoutExpired(cmd="codex", timeout=35, output=b"", stderr=b"still running")
            return (b"", b"still running")

    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/tools/codex.exe")
    monkeypatch.setattr(
        bridge_mod.Path,
        "exists",
        lambda self: str(self).replace("\\", "/") == "C:/tools/codex.exe" or original_exists(self),
    )
    monkeypatch.setattr(bridge_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess())

    def fake_run(command, **kwargs):
        taskkill_commands.append(command)

        class Result:
            returncode = 0
            stdout = b""
            stderr = b""

        return Result()

    monkeypatch.setattr(bridge_mod.subprocess, "run", fake_run)

    with pytest.raises(TimeoutError, match="timed out after 35s"):
        bridge_mod.run_codex_exec(
            {
                "repo_root": str(tmp_path),
                "prompt": "检查代码",
                "timeout_sec": 35,
            }
        )

    assert taskkill_commands == [["taskkill", "/PID", "24680", "/T", "/F"]]


def test_run_codex_exec_prefers_windowsapps_codex_exe_over_npm_shim(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}
    original_exists = bridge_mod.Path.exists

    class FakeProcess:
        returncode = 0
        pid = 4321

        def __init__(self, command, **kwargs):
            captured["command"] = command
            self.command = command

        def communicate(self, input=None, timeout=None):
            output_path = Path(self.command[self.command.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")
            return (b"", b"")

    monkeypatch.setattr(bridge_mod.shutil, "which", lambda name: "C:/Users/test/AppData/Roaming/npm/codex.cmd")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")
    monkeypatch.setattr(
        bridge_mod.Path,
        "exists",
        lambda self: str(self).replace("\\", "/") in {
            "C:/Users/test/AppData/Local/Microsoft/WindowsApps",
            "C:/Users/test/AppData/Local/Microsoft/WindowsApps/codex.exe",
            "C:/Users/test/AppData/Roaming/npm/codex",
        }
        or original_exists(self),
    )
    monkeypatch.setattr(bridge_mod.subprocess, "Popen", lambda *args, **kwargs: FakeProcess(*args, **kwargs))
    monkeypatch.setattr(
        bridge_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("taskkill should not be called on success")),
    )

    bridge_mod.run_codex_exec(
        {
            "repo_root": str(tmp_path),
            "prompt": "检查代码",
        }
    )

    assert captured["command"][0].replace("\\", "/") == "C:/Users/test/AppData/Local/Microsoft/WindowsApps/codex.exe"


def test_run_codex_exec_falls_back_to_shim_when_preferred_command_is_permission_denied(monkeypatch, tmp_path: Path):
    captured: dict[str, object] = {}
    original_exists = bridge_mod.Path.exists

    class FakeProcess:
        returncode = 0
        pid = 4321

        def __init__(self, command, **kwargs):
            captured["command"] = command
            self.command = command

        def communicate(self, input=None, timeout=None):
            output_path = Path(self.command[self.command.index("-o") + 1])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")
            return (b"", b"")

    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")

    def fake_which(name):
        if name == "codex.exe":
            return "C:/Users/test/AppData/Local/Microsoft/WindowsApps/codex.exe"
        if name == "codex":
            return "C:/Users/test/AppData/Roaming/npm/codex.cmd"
        return None

    def fake_popen(command, **kwargs):
        if command[0].replace("\\", "/") == "C:/Users/test/AppData/Local/Microsoft/WindowsApps/codex.exe":
            raise PermissionError("[WinError 5] 拒绝访问。")
        return FakeProcess(command, **kwargs)

    monkeypatch.setattr(bridge_mod.shutil, "which", fake_which)
    monkeypatch.setattr(
        bridge_mod.Path,
        "exists",
        lambda self: str(self).replace("\\", "/") in {
            "C:/Users/test/AppData/Local/Microsoft/WindowsApps",
            "C:/Users/test/AppData/Local/Microsoft/WindowsApps/codex.exe",
            "C:/Users/test/AppData/Roaming/npm/codex.cmd",
        }
        or original_exists(self),
    )
    monkeypatch.setattr(bridge_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        bridge_mod.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("taskkill should not be called on success")),
    )

    bridge_mod.run_codex_exec(
        {
            "repo_root": str(tmp_path),
            "prompt": "检查代码",
        }
    )

    assert captured["command"][0].replace("\\", "/") == "C:/Users/test/AppData/Roaming/npm/codex.cmd"
