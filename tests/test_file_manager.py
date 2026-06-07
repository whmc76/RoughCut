from __future__ import annotations

from pathlib import Path

from roughcut.api import intelligent_copy as intelligent_copy_api
from roughcut.host import file_manager


def test_open_in_file_manager_uses_startfile_for_windows_directories(tmp_path, monkeypatch) -> None:
    target = tmp_path / "smart-copy"
    target.mkdir()
    captured: dict[str, str] = {}

    def fake_startfile(path: str) -> None:
        captured["path"] = path

    def fail_popen(_args):
        raise AssertionError("directory open should not shell out to explorer")

    monkeypatch.setattr(file_manager.os, "name", "nt", raising=False)
    monkeypatch.setattr(file_manager.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(file_manager.subprocess, "Popen", fail_popen)

    file_manager.open_in_file_manager(target)

    assert Path(captured["path"]) == target.resolve()


def test_open_in_file_manager_uses_explorer_select_for_windows_files(tmp_path, monkeypatch) -> None:
    target = tmp_path / "result.txt"
    target.write_text("ok", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def fake_popen(args: list[str]) -> None:
        captured["args"] = args
        return None

    monkeypatch.setattr(file_manager.os, "name", "nt", raising=False)
    monkeypatch.setattr(file_manager.subprocess, "Popen", fake_popen)

    file_manager.open_in_file_manager(target)

    assert captured["args"] == ["explorer", "/select,", str(target.resolve())]


def test_open_in_file_manager_delegates_to_host_bridge_inside_container(tmp_path, monkeypatch) -> None:
    target = tmp_path / "smart-copy"
    target.mkdir()
    captured: dict[str, str] = {}

    def fake_bridge_open(path: str) -> None:
        captured["path"] = path

    def fail_popen(_args):
        raise AssertionError("container path should delegate to host bridge instead of local shell open")

    monkeypatch.setattr(file_manager, "_should_delegate_to_host_bridge", lambda: True)
    monkeypatch.setattr(file_manager, "_open_in_file_manager_via_host_bridge", fake_bridge_open)
    monkeypatch.setattr(file_manager.subprocess, "Popen", fail_popen)

    file_manager.open_in_file_manager(target)

    assert captured["path"] == str(target.resolve())


def test_intelligent_copy_open_folder_uses_shared_file_manager(tmp_path, monkeypatch) -> None:
    target = tmp_path / "smart-copy"
    target.mkdir()
    captured: dict[str, str] = {}

    def fake_open(path: str) -> None:
        captured["path"] = path

    monkeypatch.setattr(intelligent_copy_api, "open_in_file_manager", fake_open)

    result = intelligent_copy_api.open_folder(intelligent_copy_api.IntelligentCopyInspectIn(folder_path=str(target)))

    assert captured["path"] == str(target)
    assert result.kind == "folder"
    assert Path(result.path) == target.resolve()


def test_intelligent_copy_open_folder_accepts_host_style_path_via_shared_gate(monkeypatch) -> None:
    host_path = r"E:\WorkSpace\RoughCut\data\runtime\smart-copy"
    captured: dict[str, str] = {}

    def fake_open(path: str) -> None:
        captured["path"] = path

    monkeypatch.setattr(intelligent_copy_api, "can_open_in_file_manager", lambda _path: True)
    monkeypatch.setattr(intelligent_copy_api, "describe_file_manager_target", lambda _path: (host_path, "folder"))
    monkeypatch.setattr(intelligent_copy_api, "open_in_file_manager", fake_open)

    result = intelligent_copy_api.open_folder(intelligent_copy_api.IntelligentCopyInspectIn(folder_path=host_path))

    assert captured["path"] == host_path
    assert result.kind == "folder"
    assert result.path == host_path
