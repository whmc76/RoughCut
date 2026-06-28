from __future__ import annotations

import subprocess
from pathlib import Path

from roughcut.providers.avatar import heygem


def test_resolve_segment_busy_wait_uses_default_when_env_missing(monkeypatch) -> None:
    monkeypatch.delenv("ROUGHCUT_HEYGEM_SEGMENT_BUSY_MAX_WAIT_SECONDS", raising=False)

    assert heygem._resolve_segment_busy_max_wait_seconds() == heygem._SEGMENT_BUSY_MAX_WAIT_SECONDS


def test_resolve_segment_busy_wait_parses_and_clamps(monkeypatch) -> None:
    monkeypatch.setenv("ROUGHCUT_HEYGEM_SEGMENT_BUSY_MAX_WAIT_SECONDS", "12")

    assert heygem._resolve_segment_busy_max_wait_seconds() == 30.0


def test_resolve_segment_busy_wait_invalid_value_returns_default(monkeypatch) -> None:
    monkeypatch.setenv("ROUGHCUT_HEYGEM_SEGMENT_BUSY_MAX_WAIT_SECONDS", "abc")

    assert heygem._resolve_segment_busy_max_wait_seconds() == heygem._SEGMENT_BUSY_MAX_WAIT_SECONDS


def test_resolve_or_collect_result_path_copies_result_from_heygem_container(
    monkeypatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)
    monkeypatch.setattr(heygem, "_resolve_running_heygem_container_name", lambda: "heygem")

    def fake_file_ready(*, container_name: str, container_path: str, media_kind: str) -> bool:
        del container_name, media_kind
        return container_path.endswith("/result.avi")

    monkeypatch.setattr(heygem, "_heygem_container_file_ready", fake_file_ready)

    def fake_run_docker_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        commands.append(command)
        if command[:2] == ["docker", "cp"]:
            Path(command[3]).write_bytes(b"avatar")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(heygem, "_run_docker_command", fake_run_docker_command)

    result = heygem._resolve_or_collect_result_path(
        "/code/data/temp/avatar_full_track_part_00/result.avi",
        task_code="avatar_full_track_part_00",
    )

    assert result == str(tmp_path / "result" / "roughcut_collected" / "avatar_full_track_part_00_result.avi")
    assert commands == [
        [
            "docker",
            "cp",
            "heygem:/code/data/temp/avatar_full_track_part_00/result.avi",
            result,
        ]
    ]


def test_resolve_completed_task_result_collects_standard_temp_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    requested_container_paths: list[str] = []

    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)
    monkeypatch.setattr(heygem, "_resolve_running_heygem_container_name", lambda: "heygem")

    def fake_file_ready(*, container_name: str, container_path: str, media_kind: str) -> bool:
        del container_name, media_kind
        requested_container_paths.append(container_path)
        return container_path.endswith("/result.avi")

    def fake_run_docker_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        if command[:2] == ["docker", "cp"]:
            Path(command[3]).write_bytes(b"avatar")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(heygem, "_heygem_container_file_ready", fake_file_ready)
    monkeypatch.setattr(heygem, "_run_docker_command", fake_run_docker_command)

    result = heygem._resolve_completed_task_result("avatar_full_track_part_00")

    assert result == str(tmp_path / "result" / "roughcut_collected" / "avatar_full_track_part_00_result.avi")
    assert requested_container_paths[:3] == [
        "/code/data/avatar_full_track_part_00-r.mp4",
        "/code/data/result/avatar_full_track_part_00-r.mp4",
        "/code/data/temp/avatar_full_track_part_00/result.avi",
    ]


def test_result_collection_prefers_final_task_result_with_min_duration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    copied_sources: list[str] = []

    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)
    monkeypatch.setattr(heygem, "_resolve_running_heygem_container_name", lambda: "heygem")
    monkeypatch.setattr(heygem, "_heygem_container_file_ready", lambda **_kwargs: True)
    monkeypatch.setattr(heygem, "_probe_local_video_duration_seconds", lambda _path: 90.0)

    def fake_container_duration(*, container_name: str, container_path: str) -> float:
        del container_name
        return 9.84 if container_path.endswith("/result.avi") else 90.0

    def fake_run_docker_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        if command[:2] == ["docker", "cp"]:
            copied_sources.append(command[2])
            Path(command[3]).write_bytes(b"avatar")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(heygem, "_probe_heygem_container_video_duration_seconds", fake_container_duration)
    monkeypatch.setattr(heygem, "_run_docker_command", fake_run_docker_command)

    result = heygem._resolve_or_collect_result_path(
        "/code/data/temp/avatar_full_track_part_00/result.avi",
        task_code="avatar_full_track_part_00",
        min_duration_sec=90.0,
    )

    assert result == str(tmp_path / "result" / "roughcut_collected" / "avatar_full_track_part_00_avatar_full_track_part_00-r.mp4")
    assert copied_sources == ["heygem:/code/data/avatar_full_track_part_00-r.mp4"]


def test_result_collection_rejects_short_temp_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    copied_sources: list[str] = []

    monkeypatch.setattr(heygem, "_RESULT_READY_RETRIES", 1)
    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)
    monkeypatch.setattr(heygem, "_resolve_running_heygem_container_name", lambda: "heygem")
    monkeypatch.setattr(heygem, "_heygem_container_file_ready", lambda **_kwargs: True)
    monkeypatch.setattr(heygem, "_probe_heygem_container_video_duration_seconds", lambda **_kwargs: 9.84)

    def fake_run_docker_command(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
        del timeout
        if command[:2] == ["docker", "cp"]:
            copied_sources.append(command[2])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(heygem, "_run_docker_command", fake_run_docker_command)

    result = heygem._resolve_or_collect_result_path(
        "/code/data/temp/avatar_full_track_part_00/result.avi",
        min_duration_sec=90.0,
    )

    assert result is None
    assert copied_sources == []
