from __future__ import annotations

from pathlib import Path

from scripts import codex_host_bridge


def test_materialize_host_directory_copies_existing_smart_copy_subtree(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    (source_dir / "clip.mp4").write_bytes(b"video")
    source_material_dir = source_dir / "smart-copy" / "_cover"
    source_material_dir.mkdir(parents=True)
    (source_material_dir / "00-cover-landscape_16_9.jpg").write_bytes(b"cover")
    (source_dir / "smart-copy" / "_meta").mkdir(parents=True)
    (source_dir / "smart-copy" / "_meta" / "smart-copy.json").write_text("{}", encoding="utf-8")

    host_output_root = tmp_path / "runtime"
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    result = codex_host_bridge.materialize_host_directory(
        {
            "folder_path": str(source_dir),
            "container_output_root": "/app/data",
        }
    )

    materialized_dir = Path(result["host_folder_path"])
    assert (materialized_dir / "clip.mp4").exists()
    assert (materialized_dir / "smart-copy" / "_cover" / "00-cover-landscape_16_9.jpg").read_bytes() == b"cover"
    assert (materialized_dir / "smart-copy" / "_meta" / "smart-copy.json").read_text(encoding="utf-8") == "{}"


def test_materialize_host_directory_skips_publication_runtime_subtree(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    source_dir.mkdir()
    (source_dir / "clip.mp4").write_bytes(b"video")
    runtime_dir = source_dir / "smart-copy" / "_publication_runtime"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "stale.publishable.mp4").write_bytes(b"stale")

    host_output_root = tmp_path / "runtime"
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    result = codex_host_bridge.materialize_host_directory(
        {
            "folder_path": str(source_dir),
            "container_output_root": "/app/data",
        }
    )

    materialized_dir = Path(result["host_folder_path"])
    assert not (materialized_dir / "smart-copy" / "_publication_runtime").exists()


def test_open_host_path_maps_runtime_mount_and_opens_on_host(tmp_path, monkeypatch) -> None:
    host_output_root = tmp_path / "runtime"
    target = host_output_root / "output" / "smart-copy"
    target.mkdir(parents=True)
    captured: dict[str, Path] = {}

    def fake_open(path: Path) -> None:
        captured["path"] = path

    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))
    monkeypatch.setattr(codex_host_bridge, "open_in_file_manager", fake_open)

    result = codex_host_bridge.open_host_path({"path": "/app/data/output/smart-copy"})

    assert captured["path"] == target.resolve()
    assert result == {"path": str(target.resolve()), "kind": "folder"}


def test_sync_smart_copy_directory_merges_materialized_output_back_to_source(tmp_path, monkeypatch) -> None:
    host_output_root = tmp_path / "runtime"
    source_material_dir = host_output_root / "host-intelligent-copy" / "abc-demo" / "smart-copy"
    (source_material_dir / "_cover").mkdir(parents=True)
    (source_material_dir / "_cover" / "00-cover-landscape_16_9.jpg").write_bytes(b"new-cover")
    (source_material_dir / "01-bilibili.md").write_text("# md\n", encoding="utf-8")

    target_folder = tmp_path / "share" / "MAXACE 美杜莎4 顶配次顶配开箱"
    target_folder.mkdir(parents=True)
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    result = codex_host_bridge.sync_smart_copy_directory(
        {
            "source_material_dir": "/app/data/host-intelligent-copy/abc-demo/smart-copy",
            "target_folder_path": str(target_folder),
        }
    )

    target_material_dir = target_folder / "smart-copy"
    assert (target_material_dir / "_cover" / "00-cover-landscape_16_9.jpg").read_bytes() == b"new-cover"
    assert (target_material_dir / "01-bilibili.md").read_text(encoding="utf-8") == "# md\n"
    assert result["target_material_dir"] == str(target_material_dir.resolve())


def test_sync_smart_copy_directory_prunes_internal_runtime_and_stale_generated_root_files(tmp_path, monkeypatch) -> None:
    host_output_root = tmp_path / "runtime"
    source_material_dir = host_output_root / "host-intelligent-copy" / "abc-demo" / "smart-copy"
    source_material_dir.mkdir(parents=True)
    (source_material_dir / "01-bilibili.md").write_text("# fresh\n", encoding="utf-8")

    target_material_dir = tmp_path / "share" / "MAXACE 美杜莎4 顶配次顶配开箱" / "smart-copy"
    (target_material_dir / "_publication_runtime").mkdir(parents=True)
    (target_material_dir / "_publication_runtime" / "stale.publishable.mp4").write_bytes(b"stale")
    (target_material_dir / "03-douyin-cover.jpg").write_bytes(b"stale-cover")

    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    codex_host_bridge.sync_smart_copy_directory(
        {
            "source_material_dir": "/app/data/host-intelligent-copy/abc-demo/smart-copy",
            "target_folder_path": str(target_material_dir.parent),
        }
    )

    assert not (target_material_dir / "_publication_runtime").exists()
    assert not (target_material_dir / "03-douyin-cover.jpg").exists()
    assert (target_material_dir / "01-bilibili.md").read_text(encoding="utf-8") == "# fresh\n"


def test_host_runtime_mount_prefers_container_mapping_over_windows_root_lookalike(tmp_path, monkeypatch) -> None:
    host_output_root = tmp_path / "runtime"
    mapped = host_output_root / "host-intelligent-copy" / "abc-demo" / "smart-copy"
    mapped.mkdir(parents=True)
    monkeypatch.setenv("ROUGHCUT_OUTPUT_HOST_ROOT", str(host_output_root))

    original_exists = Path.exists

    def fake_exists(path: Path) -> bool:
        normalized = str(path).replace("\\", "/").lower()
        if normalized.endswith("/app/data/host-intelligent-copy/abc-demo/smart-copy"):
            return True
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)

    resolved = codex_host_bridge._host_path_for_runtime_mount(
        "/app/data/host-intelligent-copy/abc-demo/smart-copy",
        require_exists=True,
    )

    assert resolved == str(mapped.resolve())
