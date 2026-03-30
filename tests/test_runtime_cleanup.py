from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roughcut.storage.runtime_cleanup import cleanup_job_runtime_files


def test_cleanup_job_runtime_files_removes_job_storage_debug_and_heygem_temp(
    tmp_path: Path,
    monkeypatch,
):
    import roughcut.config as config_mod

    job_id = "job-cleanup-1"
    job_storage_dir = tmp_path / "jobs"
    render_debug_dir = tmp_path / "render-debug"
    heygem_root = tmp_path / "heygem"
    heygem_temp = heygem_root / "temp"
    deliverable = tmp_path / "output" / "final.mp4"

    storage_file = job_storage_dir / job_id / "audio.wav"
    storage_file.parent.mkdir(parents=True, exist_ok=True)
    storage_file.write_bytes(b"audio")

    debug_dir = render_debug_dir / f"{job_id}_demo"
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / "plain.log").write_text("debug", encoding="utf-8")

    heygem_temp.mkdir(parents=True, exist_ok=True)
    heygem_file = heygem_temp / "avatar_full_track-r.mp4"
    heygem_file.write_bytes(b"video")

    deliverable.parent.mkdir(parents=True, exist_ok=True)
    deliverable.write_bytes(b"final")

    monkeypatch.setenv("HEYGEM_SHARED_ROOT", str(heygem_root))
    config_mod._settings = config_mod.Settings(
        _env_file=None,
        output_dir=str(tmp_path / "output"),
        job_storage_dir=str(job_storage_dir),
        render_debug_dir=str(render_debug_dir),
    )

    cleanup_job_runtime_files(
        job_id,
        artifacts=[
            SimpleNamespace(
                storage_path=None,
                data_json={"avatar_result": {"local_result_path": str(heygem_file)}},
            )
        ],
        render_outputs=[SimpleNamespace(output_path=str(deliverable))],
        purge_deliverables=False,
    )

    assert not storage_file.exists()
    assert not debug_dir.exists()
    assert not heygem_file.exists()
    assert deliverable.exists()
