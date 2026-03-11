from __future__ import annotations

import json
import uuid
from pathlib import Path

from roughcut.packaging import library


def test_packaging_library_saves_and_resolves_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    intro = library.save_packaging_asset(
        asset_type="intro",
        filename="intro.mp4",
        payload=b"intro",
    )
    music_a = library.save_packaging_asset(
        asset_type="music",
        filename="a.mp3",
        payload=b"a",
    )
    music_b = library.save_packaging_asset(
        asset_type="music",
        filename="b.mp3",
        payload=b"b",
    )
    insert = library.save_packaging_asset(
        asset_type="insert",
        filename="insert.mp4",
        payload=b"insert",
    )

    library.update_packaging_config(
        {
            "intro_asset_id": intro["id"],
            "insert_asset_id": insert["id"],
            "insert_asset_ids": [insert["id"]],
            "insert_selection_mode": "manual",
            "music_asset_ids": [music_a["id"], music_b["id"]],
            "music_selection_mode": "random",
            "music_loop_mode": "loop_all",
            "subtitle_style": "cinema_blue",
            "cover_style": "tactical_neon",
        }
    )

    plan = library.resolve_packaging_plan_for_job(str(uuid.uuid4()))
    assert plan["intro"]["asset_id"] == intro["id"]
    assert plan["insert"]["asset_id"] == insert["id"]
    assert plan["music"]["asset_id"] in {music_a["id"], music_b["id"]}
    assert plan["music"]["loop_mode"] == "loop_all"
    assert len(plan["music"]["candidate_paths"]) == 2
    assert plan["subtitle_style"] == "cinema_blue"
    assert plan["cover_style"] == "tactical_neon"


def test_packaging_library_delete_clears_selected_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    watermark = library.save_packaging_asset(
        asset_type="watermark",
        filename="mark.png",
        payload=b"watermark",
    )
    state = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert state["config"]["watermark_asset_id"] == watermark["id"]

    library.delete_packaging_asset(watermark["id"])
    state = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert state["config"]["watermark_asset_id"] is None


def test_packaging_library_migrates_legacy_none_loop_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"assets": [], "config": {"music_loop_mode": "none"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = library.list_packaging_assets()

    assert payload["config"]["music_loop_mode"] == "loop_all"
