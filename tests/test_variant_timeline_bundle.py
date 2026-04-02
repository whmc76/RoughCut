from __future__ import annotations

from pathlib import Path

import roughcut.media.variant_timeline_bundle as bundle_mod


def test_build_legacy_variant_timeline_bundle_reads_local_paths():
    bundle = bundle_mod.build_legacy_variant_timeline_bundle(
        {
            "packaged_mp4": "E:/tmp/demo.mp4",
            "packaged_srt": "",
            "quality_checks": {
                "subtitle_sync": {
                    "video_duration_sec": 8.5,
                }
            },
        }
    )

    assert bundle is not None
    assert bundle["variants"]["packaged"]["media"]["path"] == "E:/tmp/demo.mp4"
    assert bundle["variants"]["packaged"]["quality_checks"]["subtitle_sync"]["video_duration_sec"] == 8.5


def test_build_legacy_variant_timeline_bundle_maps_app_data_paths(monkeypatch, tmp_path):
    repo_root = tmp_path / "repo"
    srt_dir = repo_root / "data" / "output" / "demo"
    srt_dir.mkdir(parents=True)
    srt_path = srt_dir / "packaged.srt"
    srt_path.write_text(
        "\n".join(
            [
                "1",
                "00:00:01,000 --> 00:00:03,000",
                "mapped-start",
                "",
                "2",
                "00:00:04,000 --> 00:00:05,500",
                "mapped-end",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bundle_mod, "_REPO_ROOT", repo_root)

    bundle = bundle_mod.build_legacy_variant_timeline_bundle(
        {
            "packaged_mp4": "/app/data/output/demo/packaged.mp4",
            "packaged_srt": "/app/data/output/demo/packaged.srt",
            "quality_checks": {
                "subtitle_sync": {
                    "video_duration_sec": 5.5,
                }
            },
        }
    )

    assert bundle is not None
    packaged = bundle["variants"]["packaged"]
    assert packaged["media"]["srt_path"] == str(srt_path)
    assert [item["text"] for item in packaged["subtitle_events"]] == ["mapped-start", "mapped-end"]


def test_build_legacy_variant_timeline_bundle_warns_when_srt_cannot_be_loaded():
    bundle = bundle_mod.build_legacy_variant_timeline_bundle(
        {
            "packaged_mp4": "/app/data/output/demo/packaged.mp4",
            "packaged_srt": "/app/data/output/demo/missing.srt",
            "quality_checks": {
                "subtitle_sync": {
                    "status": "ok",
                    "duration_gap_sec": 8.0,
                    "trailing_gap_sec": 8.0,
                }
            },
        }
    )

    assert bundle is not None
    assert bundle["validation"]["status"] == "warning"
    assert any("subtitle events could not be loaded" in issue for issue in bundle["validation"]["issues"])
    assert any("large subtitle gap" in issue for issue in bundle["validation"]["issues"])
