from __future__ import annotations

from roughcut.api import intelligent_copy
from roughcut.review import intelligent_copy as review_intelligent_copy


def test_suggest_directory_paths_lists_existing_directory_children(tmp_path, monkeypatch):
    child = tmp_path / "MAXACE 美杜莎4 顶配次顶配开箱"
    child.mkdir()
    (tmp_path / "not-a-folder.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.delenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", raising=False)
    monkeypatch.delenv("ROUGHCUT_HOST_PATH_SUGGESTIONS_URL", raising=False)

    suggestions = intelligent_copy.suggest_directory_paths(str(tmp_path), limit=8)

    assert [item.path for item in suggestions] == [str(child.resolve())]
    assert suggestions[0].label == child.name


def test_suggest_directory_paths_falls_back_to_host_bridge(monkeypatch):
    monkeypatch.setattr(intelligent_copy, "_suggest_directory_paths_local", lambda query, *, limit: [])
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "http://host.docker.internal:38695/v1/codex/exec")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN", "token-1")

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "suggestions": [
                    {
                        "path": r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱",
                        "label": "MAXACE 美杜莎4 顶配次顶配开箱",
                        "parent": r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布",
                        "kind": "folder",
                    }
                ]
            }

    def fake_post(url, *, json, headers, timeout):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(intelligent_copy.httpx, "post", fake_post)

    suggestions = intelligent_copy.suggest_directory_paths(r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布", limit=8)

    assert captured["url"] == "http://127.0.0.1:38695/v1/host/path-suggestions"
    assert captured["headers"]["Authorization"] == "Bearer token-1"
    assert suggestions[0].label == "MAXACE 美杜莎4 顶配次顶配开箱"


def test_resolve_existing_folder_materializes_host_folder(monkeypatch, tmp_path):
    materialized = tmp_path / "materialized"
    materialized.mkdir()
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "http://host.docker.internal:38695/v1/codex/exec")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN", "token-1")
    monkeypatch.setenv("ROUGHCUT_OUTPUT_ROOT", "/app/data")

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"folder_path": str(materialized)}

    def fake_post(url, *, json, headers, timeout):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(review_intelligent_copy.httpx, "post", fake_post)

    resolved = review_intelligent_copy._resolve_existing_folder(r"\\host-only-share\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱")

    assert resolved == materialized.resolve()
    assert captured["url"] == "http://127.0.0.1:38695/v1/host/materialize-directory"
    assert captured["json"]["container_output_root"] == "/app/data"


def test_inspect_preserves_requested_host_folder_path_after_materialize(monkeypatch, tmp_path):
    from roughcut.review.intelligent_copy import inspect_intelligent_copy_folder

    materialized = tmp_path / "materialized"
    materialized.mkdir()
    (materialized / "clip.mp4").write_bytes(b"video")
    (materialized / "clip.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    requested = r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\clip"

    monkeypatch.setattr("roughcut.review.intelligent_copy._materialize_host_folder", lambda _path: materialized)

    inspection = inspect_intelligent_copy_folder(requested)

    assert inspection["folder_path"] == requested
    assert inspection["video_file"] == str(materialized / "clip.mp4")
    assert inspection["material_dir"] == str(materialized / "smart-copy")


def test_inspect_prefers_final_remix_video_over_intermediate_montage(tmp_path):
    from roughcut.review.intelligent_copy import inspect_intelligent_copy_folder

    folder = tmp_path / "sample"
    folder.mkdir()
    montage = folder / "s02e02_video_montage.mp4"
    final_video = folder / "bluey_s02e02_parenting_remix.mp4"
    montage.write_bytes(b"m" * 128)
    final_video.write_bytes(b"f" * 64)
    (folder / "s02e02_narration.ass").write_text(
        "[Script Info]\n\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hello\n",
        encoding="utf-8",
    )

    inspection = inspect_intelligent_copy_folder(str(folder))

    assert inspection["video_file"] == str(final_video)
    assert str(montage) in inspection["extra_video_files"]


def test_sync_materialized_smart_copy_to_host_posts_bridge_request(monkeypatch, tmp_path):
    material_dir = tmp_path / "host-intelligent-copy" / "demo" / "smart-copy"
    material_dir.mkdir(parents=True)
    requested = r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱"
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "http://host.docker.internal:38695/v1/codex/exec")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN", "token-1")

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, *, json, headers, timeout):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    monkeypatch.setattr(review_intelligent_copy.httpx, "post", fake_post)

    review_intelligent_copy._sync_materialized_smart_copy_to_host(
        requested_folder_path=requested,
        material_dir=material_dir,
    )

    assert captured["url"].endswith("/v1/host/sync-smart-copy")
    assert captured["headers"]["Authorization"] == "Bearer token-1"
    assert captured["json"]["target_folder_path"] == requested
    assert captured["json"]["source_material_dir"] == str(material_dir)
