from types import SimpleNamespace

import pytest

from roughcut import publication
from roughcut.publication_social_auto_upload import build_social_auto_upload_upload_command
from roughcut.publication_social_auto_upload import maybe_resolve_bilibili_tid
from roughcut.publication_social_auto_upload import resolve_bilibili_tid


def test_resolve_publication_target_adapter_uses_social_auto_upload_for_enabled_platform(monkeypatch):
    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(publication_social_auto_upload_platforms="douyin,xiaohongshu"),
    )

    assert publication._resolve_publication_target_adapter("douyin", "") == "social_auto_upload"
    assert publication._resolve_publication_target_adapter("kuaishou", "") == "browser_agent"


def test_resolve_publication_target_adapter_defaults_x_to_link_share():
    assert publication._resolve_publication_target_adapter("x", "") == "x_link_share"


def test_resolve_publication_target_adapter_keeps_youtube_on_browser_agent_even_when_sau_enabled(monkeypatch):
    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(publication_social_auto_upload_platforms="douyin,youtube,xiaohongshu"),
    )

    assert publication._resolve_publication_target_adapter("youtube", "") == "browser_agent"


def test_build_social_auto_upload_upload_command_for_douyin():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="douyin",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试", "发布"],
            "cover_path": "E:/fallback-thumb.png",
            "copy_material": {
                "cover_slots": [
                    {"slot": "landscape_4_3", "cover_path": "E:/thumb-43.png", "members": ["douyin"]},
                    {"slot": "portrait_3_4", "cover_path": "E:/thumb-34.png", "members": ["douyin"]},
                ]
            },
            "scheduled_publish_at": "2026-06-09T21:30:00+08:00",
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "douyin",
        "upload-video",
        "--account",
        "creator-a",
        "--file",
        "E:/video.mp4",
        "--title",
        "标题",
        "--desc",
        "简介",
        "--tags",
        "测试,发布",
        "--thumbnail-landscape",
        "E:/thumb-43.png",
        "--thumbnail-portrait",
        "E:/thumb-34.png",
        "--schedule",
        "2026-06-09 21:30",
    ]


def test_build_social_auto_upload_upload_command_for_douyin_uses_projected_landscape_slot_even_when_source_members_exclude_platform():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="douyin",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "copy_material": {
                "cover_slots": [
                    {"slot": "horizontal_4_3", "cover_path": "E:/thumb-43.png", "members": ["bilibili", "toutiao", "x"]},
                    {"slot": "vertical_3_4", "cover_path": "E:/thumb-34.png", "members": ["douyin"]},
                ]
            },
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert "--thumbnail-landscape" in command
    assert "E:/thumb-43.png" in command


def test_build_social_auto_upload_upload_command_for_xiaohongshu_group_chat_and_original():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="xiaohongshu",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "cover_path": "E:/thumb-34.png",
            "declaration": "原创声明",
            "platform_specific_overrides": {
                "selected_group_chat": "F.A.S EDC畅聊群",
                "selected_declarations": ["原创声明"],
            },
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "xiaohongshu",
        "upload-video",
        "--account",
        "creator-a",
        "--file",
        "E:/video.mp4",
        "--title",
        "标题",
        "--desc",
        "简介",
        "--tags",
        "测试",
        "--thumbnail",
        "E:/thumb-34.png",
        "--group-chat",
        "F.A.S EDC畅聊群",
        "--original-declaration",
    ]


def test_build_social_auto_upload_upload_command_for_collection_targets():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="kuaishou",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "platform_specific_overrides": {
                "collection_management": {
                    "status": "needs_create",
                    "target_collection_name": "EDC刀光火工具集",
                }
            },
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "kuaishou",
        "upload-video",
        "--account",
        "creator-a",
        "--file",
        "E:/video.mp4",
        "--title",
        "标题",
        "--desc",
        "简介",
        "--tags",
        "测试",
        "--collection",
        "EDC刀光火工具集",
    ]


def test_build_social_auto_upload_upload_command_for_wechat_channels_uses_dual_thumbnail_slots_and_category():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="wechat-channels",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试", "视频号"],
            "category": "时尚",
            "copy_material": {
                "cover_slots": [
                    {"slot": "landscape_4_3", "cover_path": "E:/thumb-43.png", "members": ["wechat-channels"]},
                    {"slot": "portrait_3_4", "cover_path": "E:/thumb-34.png", "members": ["wechat-channels"]},
                ]
            },
            "collection_name": "EDC刀光火工具集",
            "scheduled_publish_at": "2026-06-09T21:30:00+08:00",
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "tencent",
        "upload-video",
        "--account",
        "creator-a",
        "--file",
        "E:/video.mp4",
        "--title",
        "标题",
        "--desc",
        "简介",
        "--tags",
        "测试,视频号",
        "--thumbnail-landscape",
        "E:/thumb-43.png",
        "--thumbnail-portrait",
        "E:/thumb-34.png",
        "--category",
        "时尚",
        "--collection",
        "EDC刀光火工具集",
        "--schedule",
        "2026-06-09 21:30",
    ]




def test_build_social_auto_upload_upload_command_for_bilibili_uses_cover_matrix_slots() -> None:
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="bilibili",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "category": "数码",
            "declaration": "原创",
            "cover_path": "E:/legacy-platform-cover.jpg",
            "cover_slots": [
                {"slot": "landscape_16_9", "cover_path": "E:/legacy-16-9.jpg", "members": ["bilibili"]},
            ],
            "cover_matrix": {
                "landscape_4_3": {"cover_path": "E:/matrix-4-3.jpg"},
                "landscape_16_9": {"cover_path": "E:/matrix-16-9.jpg"},
                "portrait_3_4": {"cover_path": "E:/matrix-3-4.jpg"},
            },
            "collection_name": "合集A",
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "bilibili",
        "upload-video",
        "--account",
        "creator-a",
        "--file",
        "E:/video.mp4",
        "--title",
        "标题",
        "--desc",
        "简介",
        "--tid",
        "95",
        "--category",
        "数码",
        "--tags",
        "测试",
        "--thumbnail-4-3",
        "E:/matrix-4-3.jpg",
        "--thumbnail-16-9",
        "E:/matrix-16-9.jpg",
        "--declaration",
        "内容无需标注",
        "--collection",
        "合集A",
    ]


def test_resolve_bilibili_tid_from_plain_category_name():
    assert resolve_bilibili_tid({"category": "数码"}) == "95"


def test_build_social_auto_upload_upload_command_for_bilibili_preserves_ui_category_and_adds_stable_tid_fallback():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="bilibili",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["maxace", "蜂巢3顶配", "EDC折刀"],
            "category": "生活兴趣/户外潮流",
            "platform_specific_overrides": {
                "category_selection_plan": {
                    "category_display": "生活兴趣/户外潮流",
                    "category_path": ["生活兴趣", "户外潮流"],
                    "legacy_api_fallback": "生活/出行",
                }
            },
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert "--category" in command
    assert "生活兴趣/户外潮流" in command
    assert "--tid" in command
    assert "250" in command


def test_maybe_resolve_bilibili_tid_uses_legacy_fallback_when_ui_category_has_no_direct_alias():
    assert (
        maybe_resolve_bilibili_tid(
            {
                "category": "生活兴趣/户外潮流",
                "platform_specific_overrides": {
                    "category_selection_plan": {
                        "category_display": "生活兴趣/户外潮流",
                        "category_path": ["生活兴趣", "户外潮流"],
                        "legacy_api_fallback": "生活/出行",
                    }
                },
            }
        )
        == "250"
    )


def test_resolve_bilibili_tid_from_complete_partition_table_entry():
    assert resolve_bilibili_tid({"category": "动画/配音"}) == "257"


@pytest.mark.asyncio
async def test_submit_publication_attempt_to_social_auto_upload_marks_attempt_published(monkeypatch):
    responses = iter(
        [
            SimpleNamespace(ok=True, command=["check"], returncode=0, stdout="valid", stderr=""),
            SimpleNamespace(ok=True, command=["upload"], returncode=0, stdout="ok", stderr=""),
        ]
    )

    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(
            publication_social_auto_upload_root="E:/WorkSpace/_eval/social-auto-upload",
            publication_social_auto_upload_python="python",
            publication_social_auto_upload_timeout_sec=30,
            publication_social_auto_upload_auto_login=False,
            publication_social_auto_upload_headless=True,
        ),
    )

    async def fake_latest_run(session, attempt_id):
        return None

    monkeypatch.setattr(publication, "_latest_publication_run", fake_latest_run)

    async def fake_run(command, *, root, timeout_sec):
        return next(responses)

    monkeypatch.setattr(publication, "run_social_auto_upload_command", fake_run)

    class _FakeSession:
        async def flush(self):
            return None

    attempt = SimpleNamespace(
        id="attempt-social-1",
        platform="douyin",
        account_label="creator-a",
        credential_id="cred-1",
        creator_profile_id="profile-1",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
        provider_task_id=None,
        provider_execution_id=None,
        provider_status=None,
        response_payload=None,
        status="queued",
        run_status="claimed",
        submitted_at=None,
        next_retry_at=None,
        adapter="social_auto_upload",
        error_code=None,
        error_message=None,
        published_at=None,
        scheduled_at=None,
        operator_summary=None,
    )

    result = await publication.submit_publication_attempt_to_social_auto_upload(_FakeSession(), attempt)

    assert result["status"] == "published"
    assert attempt.status == "published"
    assert attempt.run_status == "published"
    assert attempt.provider_status == "published"
    assert attempt.error_code is None
    assert attempt.response_payload["executor"] == "social_auto_upload"
