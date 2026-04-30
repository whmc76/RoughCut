from __future__ import annotations

import os

from roughcut.host import codex_bridge


def test_codex_command_prefers_windows_cmd_launcher(monkeypatch) -> None:
    if os.name != "nt":
        return

    paths = {
        "codex.cmd": r"C:\Users\user\AppData\Roaming\npm\codex.cmd",
        "codex.exe": r"C:\Program Files\WindowsApps\OpenAI.Codex\app\resources\codex.exe",
        "codex": r"C:\Users\user\AppData\Roaming\npm\codex",
    }

    monkeypatch.setattr(codex_bridge.shutil, "which", lambda name: paths.get(name))
    monkeypatch.setattr(codex_bridge.Path, "exists", lambda self: False)

    candidates = codex_bridge._resolve_codex_command_candidates("codex")

    assert candidates[0].endswith("codex.cmd")
    assert all(not item.endswith(r"\npm\codex") for item in candidates)


def test_codex_exec_falls_back_when_first_launcher_cannot_start(monkeypatch, tmp_path) -> None:
    calls: list[str] = []

    class FakeProcess:
        returncode = 0

        def communicate(self, *, input=None, timeout=None):
            return b"ok", b""

    def fake_popen(command, **_kwargs):
        calls.append(command[0])
        if command[0].endswith("bad.exe"):
            raise OSError(193, "%1 is not a valid Win32 application")
        return FakeProcess()

    monkeypatch.setattr(codex_bridge, "_resolve_codex_command_candidates", lambda _command: [r"C:\bad.exe", r"C:\codex.cmd"])
    monkeypatch.setattr(codex_bridge.subprocess, "Popen", fake_popen)

    result = codex_bridge.run_codex_exec({"repo_root": str(tmp_path), "prompt": "say ok"})

    assert calls == [r"C:\bad.exe", r"C:\codex.cmd"]
    assert result["stdout"] == "ok"
