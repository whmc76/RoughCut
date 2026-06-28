import subprocess
from types import SimpleNamespace

from roughcut.providers.avatar import heygem


def test_heygem_no_progress_timeout_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        heygem,
        "get_settings",
        lambda: SimpleNamespace(avatar_render_no_progress_timeout_sec=0),
    )

    assert heygem._resolve_task_no_progress_timeout_seconds() is None


def test_heygem_no_progress_timeout_has_minimum(monkeypatch) -> None:
    monkeypatch.setattr(
        heygem,
        "get_settings",
        lambda: SimpleNamespace(avatar_render_no_progress_timeout_sec=30),
    )

    assert heygem._resolve_task_no_progress_timeout_seconds() == 60.0


def test_resolve_container_local_path_preserves_posix_segments(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)

    resolved = heygem._resolve_container_local_path("/code/data/inputs/audio/sample.wav")

    assert resolved == str((tmp_path / "inputs" / "audio" / "sample.wav").resolve())


def test_ensure_heygem_container_path_visible_copies_when_mount_is_split(monkeypatch, tmp_path) -> None:
    staged_audio = tmp_path / "inputs" / "audio" / "sample.wav"
    staged_audio.parent.mkdir(parents=True)
    staged_audio.write_bytes(b"wav")
    calls: list[list[str]] = []
    audio_ready_after_copy = False

    monkeypatch.setattr(heygem, "_detect_shared_root", lambda: tmp_path)
    monkeypatch.setattr(heygem, "_resolve_running_heygem_container_name", lambda: "heygem")

    def fake_run(command: list[str], *, timeout: float) -> subprocess.CompletedProcess[str] | None:
        del timeout
        nonlocal audio_ready_after_copy
        calls.append(command)
        if command[:3] == ["docker", "exec", "heygem"] and "ffprobe" in command:
            return subprocess.CompletedProcess(command, 0 if audio_ready_after_copy else 1, "12.5\n", "")
        if command[:4] == ["docker", "exec", "heygem", "mkdir"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[:2] == ["docker", "cp"]:
            audio_ready_after_copy = True
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected")

    monkeypatch.setattr(heygem, "_run_docker_command", fake_run)

    heygem._ensure_heygem_container_path_visible("/code/data/inputs/audio/sample.wav", media_kind="audio")

    assert ["docker", "cp", str(staged_audio.resolve()), "heygem:/code/data/inputs/audio/sample.wav"] in calls
