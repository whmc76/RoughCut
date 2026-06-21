from datetime import timedelta
from types import SimpleNamespace

import pytest

from roughcut import publication
from roughcut.publication_social_auto_upload import build_social_auto_upload_account_name
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
    assert publication._resolve_publication_target_adapter("xiaohongshu", "") == "browser_agent"
    assert publication._resolve_publication_target_adapter("kuaishou", "") == "browser_agent"


def test_resolve_publication_target_adapter_defaults_x_to_link_share():
    assert publication._resolve_publication_target_adapter("x", "") == "x_link_share"


def test_resolve_publication_target_adapter_defaults_youtube_to_browser_agent_for_existing_browser_cookie(monkeypatch):
    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(publication_social_auto_upload_platforms="douyin,xiaohongshu"),
    )

    assert publication._resolve_publication_target_adapter("youtube", "") == "browser_agent"


def test_resolve_publication_target_adapter_uses_social_auto_upload_for_explicit_youtube_binding(monkeypatch):
    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(publication_social_auto_upload_platforms="douyin,xiaohongshu"),
    )

    assert publication._resolve_publication_target_adapter("youtube", "social_auto_upload") == "social_auto_upload"


def test_resolve_publication_target_adapter_keeps_explicit_x_link_share():
    assert publication._resolve_publication_target_adapter("x", "x_link_share") == "x_link_share"


def test_build_social_auto_upload_account_name_prefers_isolated_credential_ref():
    attempt = SimpleNamespace(
        credential_id="social-auto-upload:creator-abc123-bilibili-chrome:bilibili",
        account_label="Demo Creator · Chrome",
        creator_profile_id="profile-1",
        platform="bilibili",
    )

    assert build_social_auto_upload_account_name(attempt) == "creator-abc123-bilibili-chrome"


def test_build_social_auto_upload_account_name_prefers_payload_credential_ref_over_uuid():
    attempt = SimpleNamespace(
        credential_id="7619655d-3ac1-4e8f-915e-541a88978fba",
        account_label="Demo Creator · Chrome",
        creator_profile_id="profile-1",
        platform="bilibili",
        request_payload={
            "metadata": {
                "credential_ref": "social-auto-upload:creator-demo-bilibili-chrome:bilibili",
            }
        },
    )

    assert build_social_auto_upload_account_name(attempt) == "creator-demo-bilibili-chrome"


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


def test_build_social_auto_upload_upload_command_for_youtube_uses_cookie_cli_contract():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="youtube",
        account_name="creator-youtube",
        request_payload={
            "title": "NITECORE EDC17 三光源超薄",
            "body": "双版对比评测",
            "hashtags": ["NITECORE", "EDC17"],
            "visibility_or_publish_mode": "public",
            "scheduled_publish_at": "2026-06-21T20:00:00+08:00",
            "collection": {"name": "EDC刀光火工具集"},
            "copy_material": {
                "cover_matrix": {
                    "landscape_16_9": {"cover_path": "E:/cover-youtube.jpg"},
                }
            },
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command == [
        "python",
        "sau_cli.py",
        "youtube",
        "upload-video",
        "--account",
        "creator-youtube",
        "--file",
        "E:/video.mp4",
        "--title",
        "NITECORE EDC17 三光源超薄",
        "--desc",
        "双版对比评测",
        "--tags",
        "NITECORE,EDC17",
        "--thumbnail",
        "E:/cover-youtube.jpg",
        "--visibility",
        "public",
        "--playlist",
        "EDC刀光火工具集",
    ]


def test_build_social_auto_upload_upload_command_converts_utc_schedule_to_platform_local_time():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="bilibili",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "scheduled_publish_at": "2026-06-20T10:00:00+00:00",
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command[command.index("--schedule") + 1] == "2026-06-20 18:00"


def test_build_social_auto_upload_upload_command_derives_missing_title_from_body_for_title_required_platform():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="wechat-channels",
        account_name="creator-a",
        request_payload={
            "title": "",
            "body": "这期围绕S02E02展开，重点看画面里能确认的细节和实际观感。",
            "hashtags": ["S02E02"],
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command[command.index("--title") + 1] == "这期围绕S02E02展开，重点看画面里能确认的细节和实际观感。"


def test_build_social_auto_upload_upload_command_for_bilibili_uses_edc_safe_default_category_when_missing():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="bilibili",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["育儿"],
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert command[command.index("--tid") + 1] == "161"
    assert command[command.index("--category") + 1] == "生活兴趣/户外潮流"


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
        "--original-content-type",
        "虚构演绎，仅供娱乐",
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


def test_build_social_auto_upload_upload_command_for_kuaishou_omits_unstable_declaration():
    command = build_social_auto_upload_upload_command(
        python_executable="python",
        platform="kuaishou",
        account_name="creator-a",
        request_payload={
            "title": "标题",
            "body": "简介",
            "hashtags": ["测试"],
            "declaration": "原创声明",
            "media_items": [{"local_path": "E:/video.mp4"}],
        },
    )

    assert "--declaration" not in command


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
    assert "161" in command


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
        == "161"
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
            publication_social_auto_upload_root="C:/sample-workspace/_eval/social-auto-upload",
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


@pytest.mark.asyncio
async def test_bilibili_social_auto_upload_verifies_backend_archive_before_scheduled_success(monkeypatch):
    commands: list[list[str]] = []

    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(
            publication_social_auto_upload_root="C:/sample-workspace/_eval/social-auto-upload",
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
        commands.append(command)
        action = command[3]
        if action == "check":
            return SimpleNamespace(ok=True, command=command, returncode=0, stdout="valid", stderr="")
        if action == "upload-video":
            return SimpleNamespace(
                ok=True,
                command=command,
                returncode=0,
                stdout='{"code":0,"data":{"aid":116777056995111,"bvid":"BV15Uj66SEXz"}}',
                stderr="",
            )
        if action == "verify-video":
            return SimpleNamespace(
                ok=True,
                command=command,
                returncode=0,
                stdout='{"verified":true,"mismatches":[],"archive":{"aid":116777056995111,"tid":47,"human_type2":{"id":1025}}}',
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(publication, "run_social_auto_upload_command", fake_run)

    class _FakeSession:
        async def flush(self):
            return None

    attempt = SimpleNamespace(
        id="attempt-bilibili-success",
        platform="bilibili",
        account_label="creator-a",
        credential_id="cred-1",
        creator_profile_id="profile-1",
        request_payload={
            "title": "S02E02关键画面整理",
            "body": "简介",
            "hashtags": ["测试"],
            "media_items": [{"local_path": "E:/video.mp4"}],
            "scheduled_publish_at": "2026-06-20T18:00:00+08:00",
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

    assert result["status"] == "scheduled_pending"
    assert attempt.status == "scheduled_pending"
    assert attempt.provider_task_id == "bilibili:116777056995111"
    verify_command = commands[-1]
    assert verify_command[2:4] == ["bilibili", "verify-video"]
    assert verify_command[verify_command.index("--expected-category") + 1] == "生活兴趣/户外潮流"
    assert verify_command[verify_command.index("--expected-schedule") + 1] == "2026-06-20 18:00"
    assert attempt.response_payload["verification"]["payload"]["archive"]["human_type2"]["id"] == 1025


@pytest.mark.asyncio
async def test_bilibili_social_auto_upload_backend_mismatch_needs_human(monkeypatch):
    monkeypatch.setattr(
        publication,
        "get_settings",
        lambda: SimpleNamespace(
            publication_social_auto_upload_root="C:/sample-workspace/_eval/social-auto-upload",
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
        action = command[3]
        if action == "check":
            return SimpleNamespace(ok=True, command=command, returncode=0, stdout="valid", stderr="")
        if action == "upload-video":
            return SimpleNamespace(
                ok=True,
                command=command,
                returncode=0,
                stdout='{"code":0,"data":{"aid":116777056995111,"bvid":"BV15Uj66SEXz"}}',
                stderr="",
            )
        if action == "verify-video":
            return SimpleNamespace(
                ok=False,
                command=command,
                returncode=1,
                stdout='{"verified":false,"mismatches":[{"field":"human_type2","expected":1025,"actual":1029}]}',
                stderr="",
            )
        raise AssertionError(command)

    monkeypatch.setattr(publication, "run_social_auto_upload_command", fake_run)

    class _FakeSession:
        async def flush(self):
            return None

    attempt = SimpleNamespace(
        id="attempt-bilibili-mismatch",
        platform="bilibili",
        account_label="creator-a",
        credential_id="cred-1",
        creator_profile_id="profile-1",
        request_payload={
            "title": "S02E02关键画面整理",
            "body": "简介",
            "hashtags": ["测试"],
            "media_items": [{"local_path": "E:/video.mp4"}],
            "scheduled_publish_at": "2026-06-20T18:00:00+08:00",
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

    assert result["status"] == "needs_human"
    assert attempt.status == "needs_human"
    assert attempt.error_code == "social_auto_upload_post_submit_verification_failed"
    assert "human_type2 expected=1025 actual=1029" in attempt.error_message
    assert attempt.response_payload["stage"] == "verify"


@pytest.mark.asyncio
async def test_social_auto_upload_submit_commits_processing_state_before_cli(monkeypatch):
    observations: list[tuple[str, str, str, int]] = []
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
            publication_social_auto_upload_root="C:/sample-workspace/_eval/social-auto-upload",
            publication_social_auto_upload_python="python",
            publication_social_auto_upload_timeout_sec=30,
            publication_social_auto_upload_auto_login=False,
            publication_social_auto_upload_headless=True,
        ),
    )

    run = SimpleNamespace(
        status="claimed",
        phase="claim",
        heartbeat_at=None,
        lease_expires_at=None,
        provider_task_id=None,
        provider_status=None,
        error_message=None,
        completed_at=None,
        result_json=None,
        provider_execution_id=None,
    )

    async def fake_latest_run(session, attempt_id):
        return run

    monkeypatch.setattr(publication, "_latest_publication_run", fake_latest_run)

    class _FakeSession:
        def __init__(self):
            self.commits = 0

        async def flush(self):
            return None

        async def commit(self):
            self.commits += 1

    attempt = SimpleNamespace(
        id="attempt-social-processing",
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
        status="claimed",
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
    session = _FakeSession()

    async def fake_run(command, *, root, timeout_sec):
        observations.append((command[2], attempt.status, run.status, session.commits))
        return next(responses)

    monkeypatch.setattr(publication, "run_social_auto_upload_command", fake_run)

    result = await publication.submit_publication_attempt_to_social_auto_upload(session, attempt)

    assert result["status"] == "published"
    assert observations[0] == ("douyin", "processing", "processing", 1)
    assert run.phase == "completed"


@pytest.mark.asyncio
async def test_social_auto_upload_reconcile_requeues_expired_processing_attempt(monkeypatch):
    reference = publication._utc_now()
    expired_run = SimpleNamespace(
        status="processing",
        phase="submit",
        heartbeat_at=reference - timedelta(minutes=20),
        lease_expires_at=reference - timedelta(seconds=1),
        completed_at=None,
        provider_task_id="attempt-stale-social",
        provider_execution_id=None,
        provider_status="processing",
        result_json=None,
        error_message=None,
    )

    async def fake_latest_run(session, attempt_id):
        assert attempt_id == "attempt-stale-social"
        return expired_run

    monkeypatch.setattr(publication, "_latest_publication_run", fake_latest_run)

    class _FakeSession:
        def __init__(self):
            self.flushes = 0

        async def flush(self):
            self.flushes += 1

    attempt = SimpleNamespace(
        id="attempt-stale-social",
        platform="bilibili",
        adapter="social_auto_upload",
        status="processing",
        run_status="processing",
        provider_task_id="attempt-stale-social",
        provider_execution_id=None,
        provider_status="processing",
        error_code=None,
        error_message=None,
        next_retry_at=None,
        operator_summary=None,
    )
    session = _FakeSession()

    result = await publication.reconcile_publication_attempt_with_social_auto_upload(session, attempt)

    assert result == {
        "attempt_id": "attempt-stale-social",
        "status": "queued",
        "provider_task_id": None,
        "recovered": True,
    }
    assert attempt.status == "queued"
    assert attempt.run_status == "retry_scheduled"
    assert attempt.next_retry_at is not None
    assert attempt.provider_status is None
    assert expired_run.status == "retry_scheduled"
    assert expired_run.phase == "recovery"
    assert expired_run.completed_at is not None
    assert session.flushes == 1


@pytest.mark.asyncio
async def test_social_auto_upload_command_uses_host_bridge_when_root_is_not_runtime_accessible(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_host_bridge(command, *, root, timeout_sec):
        captured["command"] = command
        captured["root"] = root
        captured["timeout_sec"] = timeout_sec
        return SimpleNamespace(ok=True, command=command, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(
        "roughcut.publication_social_auto_upload._run_social_auto_upload_command_via_host_bridge",
        fake_host_bridge,
    )

    result = await publication.run_social_auto_upload_command(
        ["python", "sau_cli.py", "douyin", "check", "--account", "creator-a"],
        root="Z:/roughcut/does-not-exist/social-auto-upload",
        timeout_sec=30,
    )

    assert result.ok
    assert captured["root"] == "Z:/roughcut/does-not-exist/social-auto-upload"
