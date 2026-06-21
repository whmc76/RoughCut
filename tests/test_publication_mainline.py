from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import roughcut.publication_mainline as publication_mainline


@pytest.fixture(autouse=True)
def _stub_mainline_publication_scheme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publication_mainline, "_derive_mainline_platform_option", lambda **kwargs: {})


def test_build_bilibili_mainline_task_uses_packaging_and_runtime_flags(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path_4_3 = tmp_path / "01-bilibili-cover-4-3.jpg"
    cover_path_4_3.write_bytes(b"cover-4-3")
    cover_path_16_9 = tmp_path / "01-bilibili-cover-16-9.jpg"
    cover_path_16_9.write_bytes(b"cover-16-9")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "browser_binding": {
                                    "browser": "chrome",
                                    "profile_id": "browser-profile:chrome:bili-1",
                                },
                                "status": "logged_in",
                                "adapter": "browser_agent",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "key": "bilibili",
                "titles": ["MAXACE 美杜莎4 顶配次顶配开箱"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path_4_3),
                "cover_slots": [
                    {
                        "slot": "landscape_4_3",
                        "matrix_key": "landscape_4_3",
                        "cover_path": str(cover_path_4_3),
                        "target_size": {"width": 1440, "height": 1080},
                    },
                    {
                        "slot": "landscape_16_9",
                        "matrix_key": "landscape_16_9",
                        "cover_path": str(cover_path_16_9),
                        "target_size": {"width": 1600, "height": 900},
                    }
                ],
                "declaration": "内容无需标注",
                "category": "生活兴趣/户外潮流",
                "collection_name": "EDC刀光火工具集",
                "scheduled_publish_at": "2026-06-06T19:30",
                "visibility_or_publish_mode": "scheduled",
                "copy_material": {
                    "source": "platform_packaging",
                    "cover_path": str(cover_path_4_3),
                    "cover_slots": [
                        {
                            "slot": "landscape_4_3",
                            "matrix_key": "landscape_4_3",
                            "cover_path": str(cover_path_4_3),
                            "target_size": {"width": 1440, "height": 1080},
                        },
                        {
                            "slot": "landscape_16_9",
                            "matrix_key": "landscape_16_9",
                            "cover_path": str(cover_path_16_9),
                            "target_size": {"width": 1600, "height": 900},
                        }
                    ],
                },
                "publish_ready": False,
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        current_page_only=True,
        stop_before_final_publish=True,
    )

    assert payload["platform"] == "bilibili"
    assert payload["content"]["title"] == "MAXACE 美杜莎4 顶配次顶配开箱"
    assert payload["content"]["body"] == "正文内容"
    assert payload["content"]["declaration"] == "内容无需标注"
    assert payload["content"]["category"] == "生活兴趣/户外潮流"
    assert payload["content"]["collection"] == {"name": "EDC刀光火工具集"}
    assert payload["content"]["scheduled_publish_at"] == "2026-06-06T19:30"
    assert payload["content"]["cover_path"] == str(cover_path_4_3)
    assert payload["content"]["cover_slots"][0]["cover_path"] == str(cover_path_4_3)
    assert payload["content"]["cover_slots"][1]["cover_path"] == str(cover_path_16_9)
    assert payload["content"]["media_items"][0]["local_path"] == str(media_path.resolve())
    assert payload["session_binding"]["browser_profile_id"] == "browser-profile:chrome:bili-1"
    assert payload["content"]["platform_specific_overrides"]["prepare_only_current_page"] is True
    assert payload["content"]["platform_specific_overrides"]["stop_before_final_publish"] is True


def test_build_bilibili_mainline_task_ignores_stale_explicit_publish_ready_false(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
                "publish_ready": False,
                "blocking_reasons": [],
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
    )

    assert payload["platform"] == "bilibili"
    assert payload["content"]["title"] == "MAXACE美杜莎4开箱先看细节"


def test_build_bilibili_mainline_task_defaults_collection_skip_for_stop_before_final_publish(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        stop_before_final_publish=True,
    )

    overrides = payload["content"]["platform_specific_overrides"]

    assert overrides["stop_before_final_publish"] is True
    assert overrides["collection_policy"] == "skip"
    assert overrides["skip_collection_select"] is True


def test_build_bilibili_mainline_task_accepts_runtime_collection_and_schedule_overrides(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        stop_before_final_publish=True,
        collection_override="EDC刀光火工具集",
        scheduled_publish_at_override="2026-06-06T19:30",
    )

    assert payload["content"]["collection"] == {"name": "EDC刀光火工具集"}
    assert payload["content"]["scheduled_publish_at"] == "2026-06-06T19:30"
    overrides = payload["content"]["platform_specific_overrides"]
    assert "collection_policy" not in overrides
    assert "skip_collection_select" not in overrides


def test_build_bilibili_mainline_task_derives_schedule_from_slot_without_requery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
                "category": "生活兴趣/户外潮流",
                "collection_name": "EDC刀光火工具集",
                "scheduled_publish_slot": "19:30",
            }
        }
    }

    def _unexpected_derive(**_kwargs):
        raise AssertionError("should not derive publication scheme when slot contract is already present")

    monkeypatch.setattr(publication_mainline, "_derive_mainline_platform_option", _unexpected_derive)
    monkeypatch.setattr(publication_mainline, "_next_local_datetime", lambda slot: f"2026-06-10T{slot}")

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
    )

    assert payload["content"]["scheduled_publish_at"] == "2026-06-10T19:30"


def test_build_bilibili_mainline_task_accepts_slot_override_for_schedule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
            }
        }
    }

    monkeypatch.setattr(publication_mainline, "_next_local_datetime", lambda slot: f"2026-06-10T{slot}")

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        scheduled_publish_at_override="19:30",
    )

    assert payload["content"]["scheduled_publish_at"] == "2026-06-10T19:30"


def test_build_bilibili_mainline_task_accepts_runtime_copy_overrides(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["短标题"],
                "description": "原始正文",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
                "copy_material": {
                    "primary_title": "短标题",
                    "titles": ["短标题"],
                    "body": "原始正文",
                },
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        title_override="MAXACE美杜莎4顶配次顶配双版本开箱细节一次看完",
        body_override="MAXACE美杜莎4顶配/次顶配双版本开箱，重点看外观细节、做工质感和上手表现。",
    )

    assert payload["content"]["title"] == "MAXACE美杜莎4顶配次顶配双版本开箱细节一次看完"
    assert payload["content"]["body"] == "MAXACE美杜莎4顶配/次顶配双版本开箱，重点看外观细节、做工质感和上手表现。"


def test_build_bilibili_mainline_task_allows_runtime_browser_binding_override(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "display_name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-agent:chrome:creator-1:bilibili",
                                "account_label": "FAS · Chrome",
                                "browser_profile_id": "browser-profile:chrome:legacy",
                                "browser_binding": {
                                    "browser": "chrome",
                                    "user_data_dir": "E:/legacy",
                                    "profile_directory": "Profile 2",
                                    "profile_id": "browser-profile:chrome:legacy",
                                },
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
            }
        }
    }

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
        browser_binding_override={
            "browser": "chrome",
            "user_data_dir": "E:/recovered",
            "profile_directory": "Profile 2",
            "profile_name": "FAS_EDC",
            "profile_email": "demo.creator@example.com",
            "cdp_base_url": "http://127.0.0.1:9222",
        },
    )

    assert payload["session_binding"]["browser_binding"]["user_data_dir"] == "E:/recovered"
    assert payload["session_binding"]["browser_profile_id"] == payload["session_binding"]["browser_binding"]["profile_id"]


def test_build_bilibili_mainline_task_raises_when_platform_packaging_missing(tmp_path: Path) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": str(uuid.uuid4()),
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }

    try:
        publication_mainline.build_platform_mainline_browser_agent_task(
            creator_profile_id="creator-1",
            profiles_payload=profiles_payload,
            platform_packaging={"platforms": {}},
            platform="bilibili",
            media_path=str(media_path),
        )
    except KeyError as exc:
        assert "platform packaging not found" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_build_bilibili_mainline_task_derives_missing_collection_schedule_and_category_from_scheme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    media_path = tmp_path / "video.mp4"
    media_path.write_bytes(b"video")
    cover_path = tmp_path / "01-bilibili-cover.jpg"
    cover_path.write_bytes(b"cover")

    profiles_payload = {
        "profiles": [
            {
                "id": "creator-1",
                "display_name": "FAS",
                "creator_profile": {
                    "publishing": {
                        "platform_credentials": [
                            {
                                "id": "cred-bili",
                                "platform": "bilibili",
                                "credential_ref": "browser-profile:chrome:bili-1",
                                "account_label": "FAS B站",
                                "browser_profile_id": "browser-profile:chrome:bili-1",
                                "status": "logged_in",
                            }
                        ]
                    }
                },
            }
        ]
    }
    platform_packaging = {
        "platforms": {
            "bilibili": {
                "titles": ["MAXACE美杜莎4开箱先看细节"],
                "description": "正文内容",
                "tags": ["MAXACE", "EDC"],
                "cover_path": str(cover_path),
                "declaration": "内容无需标注",
            }
        }
    }

    monkeypatch.setattr(
        publication_mainline,
        "_derive_mainline_platform_option",
        lambda **kwargs: {
            "category": "生活兴趣/户外潮流",
            "scheduled_publish_at": "2026-06-06T19:30",
            "collection_name": "EDC刀光火工具集",
            "platform_specific_overrides": {
                "collection_management": {
                    "status": "select_existing",
                    "selected_collection_name": "EDC刀光火工具集",
                    "target_collection_name": "EDC刀光火工具集",
                }
            },
        },
    )

    payload = publication_mainline.build_platform_mainline_browser_agent_task(
        creator_profile_id="creator-1",
        profiles_payload=profiles_payload,
        platform_packaging=platform_packaging,
        platform="bilibili",
        media_path=str(media_path),
    )

    assert payload["content"]["category"] == "生活兴趣/户外潮流"
    assert payload["content"]["scheduled_publish_at"] == "2026-06-06T19:30"
    assert payload["content"]["collection"] == {"name": "EDC刀光火工具集"}
    assert (
        payload["content"]["platform_specific_overrides"]["collection_management"]["selected_collection_name"]
        == "EDC刀光火工具集"
    )
