from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
import uuid

from roughcut.api import intelligent_copy as intelligent_copy_api
from roughcut.api import jobs as jobs_api
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
    host_path = r"C:\sample-workspace\RoughCut\data\runtime\smart-copy"
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


def test_job_open_folder_resolves_relative_render_output_from_project_root(tmp_path, monkeypatch) -> None:
    project_root = tmp_path / "repo"
    output_path = project_root / "output" / "test" / "result.mp4"
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"video")
    unrelated_cwd = tmp_path / "server-cwd"
    unrelated_cwd.mkdir()

    class FakeScalarResult:
        def all(self):
            return [SimpleNamespace(output_path=r"output\test\result.mp4")]

    class FakeResult:
        def scalars(self):
            return FakeScalarResult()

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setattr(jobs_api, "DEFAULT_PROJECT_ROOT", project_root)

    target_path, kind = asyncio.run(
        jobs_api._resolve_job_open_target(
            SimpleNamespace(id=uuid.uuid4(), source_path=""),
            FakeSession(),
        )
    )

    assert Path(target_path) == output_path.resolve()
    assert kind == "output"


def test_job_open_target_maps_project_relative_output_to_host_project_root(monkeypatch) -> None:
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", "C:/sample-workspace/RoughCut/data/runtime")
    monkeypatch.setattr(jobs_api, "DEFAULT_PROJECT_ROOT", Path("/app"))
    monkeypatch.setattr(
        jobs_api,
        "can_open_in_file_manager",
        lambda path: str(path).replace("\\", "/")
        == "C:/sample-workspace/RoughCut/output/test/result.mp4",
    )

    target_path = jobs_api._resolve_file_manager_existing_path(r"output\test\result.mp4")

    assert str(target_path).replace("\\", "/") == "C:/sample-workspace/RoughCut/output/test/result.mp4"


def test_download_path_maps_host_runtime_root_to_container_runtime_root(tmp_path, monkeypatch) -> None:
    container_root = tmp_path / "container-runtime"
    target = container_root / "output" / "demo" / "final.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")

    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", "C:/sample-workspace/RoughCut/data/runtime")
    monkeypatch.setenv("ROUGHCUT_OUTPUT_ROOT", str(container_root))

    resolved = jobs_api._first_existing_download_path(
        r"C:\sample-workspace\RoughCut\data\runtime\output\demo\final.mp4",
    )

    assert resolved == target.resolve()


def test_collect_downloadable_files_uses_runtime_mapped_path(tmp_path, monkeypatch) -> None:
    container_root = tmp_path / "container-runtime"
    target = container_root / "output" / "demo" / "final.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")

    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", "C:/sample-workspace/RoughCut/data/runtime")
    monkeypatch.setenv("ROUGHCUT_OUTPUT_ROOT", str(container_root))

    files = jobs_api._collect_downloadable_files(
        None,
        {
            "packaged_mp4": r"C:\sample-workspace\RoughCut\data\runtime\output\demo\final.mp4",
        },
    )

    assert files[0]["id"] == "packaged_mp4"
    assert files[0]["_path"] == str(target.resolve())


def test_job_open_target_prefers_runtime_mount_path_for_host_runtime_output(tmp_path, monkeypatch) -> None:
    container_root = tmp_path / "container-runtime"
    target = container_root / "output" / "demo" / "final.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"video")
    host_path = r"C:\sample-workspace\RoughCut\data\runtime\output\demo\final.mp4"

    class FakeScalarResult:
        def all(self):
            return [SimpleNamespace(output_path=host_path)]

    class FakeResult:
        def scalars(self):
            return FakeScalarResult()

    class FakeSession:
        async def execute(self, _statement):
            return FakeResult()

    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", "C:/sample-workspace/RoughCut/data/runtime")
    monkeypatch.setenv("ROUGHCUT_OUTPUT_ROOT", str(container_root))
    monkeypatch.setattr(jobs_api, "can_open_in_file_manager", lambda path: Path(path).exists())

    target_path, kind = asyncio.run(
        jobs_api._resolve_job_open_target(
            SimpleNamespace(id=uuid.uuid4(), source_path=""),
            FakeSession(),
        )
    )

    assert Path(target_path) == target.resolve()
    assert kind == "output"
