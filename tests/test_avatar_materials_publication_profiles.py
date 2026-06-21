from __future__ import annotations

import json

from roughcut.api import avatar_materials
from roughcut.publication import build_publication_browser_profile_id
from roughcut.avatar.materials import avatar_materials_root


def test_resolve_browser_profile_binding_for_creator_matches_local_chrome_profile(tmp_path, monkeypatch):
    local_state_path = tmp_path / "Local State"
    local_state_path.write_text(
        json.dumps(
            {
                "profile": {
                    "info_cache": {
                        "Default": {
                            "name": "您的 Chrome",
                            "user_name": "",
                        },
                        "Profile 2": {
                            "name": "Demo Chrome",
                            "gaia_given_name": "Demo Chrome",
                            "gaia_name": "Demo Chrome",
                            "user_name": "demo.creator@example.com",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_data_dir = tmp_path / "User Data"
    user_data_dir.mkdir()
    body = avatar_materials.PublicationBrowserLoginMatchIn(browser="chrome", platforms=["douyin"])
    profile = {
        "display_name": "Demo Creator",
        "presenter_alias": "Demo Creator",
        "creator_profile": {
            "identity": {
                "public_name": "Demo Creator",
            }
        },
    }

    monkeypatch.setattr(
        avatar_materials,
        "_publication_browser_local_state_path",
        lambda browser: local_state_path,
    )
    monkeypatch.setattr(
        avatar_materials,
        "_publication_browser_user_data_dir",
        lambda browser: user_data_dir,
    )

    binding = avatar_materials._resolve_browser_profile_binding_for_creator(
        browser="chrome",
        profile=profile,
        body=body,
    )

    assert binding["browser"] == "chrome"
    assert binding["profile_directory"] == "Profile 2"
    assert binding["profile_name"] == "Demo Chrome"
    assert binding["profile_email"] == "demo.creator@example.com"
    assert binding["profile_id"] == build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir=str(user_data_dir),
        profile_directory="Profile 2",
    )


def test_resolve_browser_profile_binding_for_creator_falls_back_to_agent_attached_profile(tmp_path, monkeypatch):
    body = avatar_materials.PublicationBrowserLoginMatchIn(
        browser="chrome",
        platforms=["douyin"],
    )
    profile = {
        "display_name": "FAS",
        "presenter_alias": "FAS",
        "creator_profile": {
            "identity": {
                "public_name": "FAS",
            }
        },
    }
    fallback_user_data_dir = tmp_path / "agent user data"
    fallback_user_data_dir.mkdir()
    monkeypatch.setattr(avatar_materials, "_publication_browser_local_state_path", lambda browser: None)
    agent_profile_id = build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir=str(fallback_user_data_dir),
        profile_directory="Profile 2",
    )
    fake_binding = {
        "browser": "chrome",
        "user_data_dir": str(fallback_user_data_dir),
        "profile_directory": "Profile 2",
        "profile_id": agent_profile_id,
    }

    monkeypatch.setattr(
        avatar_materials,
        "_resolve_agent_attached_browser_binding",
        lambda browser: fake_binding,
    )

    binding = avatar_materials._resolve_browser_profile_binding_for_creator(
        browser="chrome",
        profile=profile,
        body=body,
    )

    assert binding["browser"] == "chrome"
    assert binding["user_data_dir"] == str(fallback_user_data_dir).replace("\\", "/")
    assert binding["profile_directory"] == "Profile 2"
    assert binding["profile_id"] == fake_binding["profile_id"]


def test_resolve_browser_profile_binding_for_creator_falls_back_to_existing_profile_credential(tmp_path, monkeypatch):
    local_state_path = tmp_path / "Local State"
    local_state_path.write_text(
        json.dumps(
            {
                "profile": {
                    "info_cache": {
                        "Profile 2": {
                            "name": "Demo Chrome",
                            "user_name": "other@example.com",
                        }
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_data_dir = tmp_path / "User Data"
    user_data_dir.mkdir()
    fallback_user_data_dir = tmp_path / "agent user data"
    fallback_user_data_dir.mkdir()
    fallback_profile_id = build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir=str(fallback_user_data_dir),
        profile_directory="Profile 9",
    )
    body = avatar_materials.PublicationBrowserLoginMatchIn(
        browser="chrome",
        platforms=["douyin"],
    )
    profile = {
        "creator_profile": {
            "identity": {
                "public_name": "",
                "real_name": "",
            },
            "publishing": {
                "platform_credentials": [
                    {
                        "platform": "douyin",
                        "adapter": "browser_agent",
                        "browser_profile_id": fallback_profile_id,
                        "browser_binding": {
                            "browser": "chrome",
                            "user_data_dir": str(fallback_user_data_dir),
                            "profile_directory": "Profile 9",
                            "profile_id": fallback_profile_id,
                        },
                    }
                ]
            }
        }
    }

    monkeypatch.setattr(avatar_materials, "_publication_browser_local_state_path", lambda browser: local_state_path)
    monkeypatch.setattr(avatar_materials, "_publication_browser_user_data_dir", lambda browser: user_data_dir)

    binding = avatar_materials._resolve_browser_profile_binding_for_creator(
        browser="chrome",
        profile=profile,
        body=body,
    )

    assert binding["user_data_dir"] == str(fallback_user_data_dir).replace("\\", "/")
    assert binding["profile_directory"] == "Profile 9"
    assert binding["profile_id"] == fallback_profile_id


def test_resolve_browser_profile_binding_for_creator_matches_by_contact_email(tmp_path, monkeypatch):
    local_state_path = tmp_path / "Local State"
    local_state_path.write_text(
        json.dumps(
            {
                "profile": {
                    "info_cache": {
                        "Default": {
                            "name": "您的 Chrome",
                            "user_name": "",
                        },
                        "Profile 2": {
                            "name": "Demo Chrome",
                            "gaia_given_name": "Demo Chrome",
                            "gaia_name": "Demo Chrome",
                            "user_name": "demo.creator@example.com",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_data_dir = tmp_path / "User Data"
    user_data_dir.mkdir()
    body = avatar_materials.PublicationBrowserLoginMatchIn(browser="chrome", platforms=["douyin"])
    profile = {
        "display_name": "",
        "presenter_alias": "",
        "personal_info": {"contact": "demo.creator@example.com"},
        "creator_profile": {
            "identity": {},
        },
    }

    monkeypatch.setattr(avatar_materials, "_publication_browser_local_state_path", lambda browser: local_state_path)
    monkeypatch.setattr(avatar_materials, "_publication_browser_user_data_dir", lambda browser: user_data_dir)

    binding = avatar_materials._resolve_browser_profile_binding_for_creator(
        browser="chrome",
        profile=profile,
        body=body,
    )

    assert binding["profile_directory"] == "Profile 2"
    assert binding["profile_email"] == "demo.creator@example.com"


def test_resolve_browser_profile_binding_for_creator_falls_back_to_agent_when_creator_tokens_missing(tmp_path, monkeypatch):
    local_state_path = tmp_path / "Local State"
    local_state_path.write_text(
        json.dumps(
            {
                "profile": {
                    "info_cache": {
                        "Default": {
                            "name": "您的 Chrome",
                            "user_name": "",
                        },
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    user_data_dir = tmp_path / "User Data"
    user_data_dir.mkdir()
    body = avatar_materials.PublicationBrowserLoginMatchIn(
        browser="chrome",
        platforms=["douyin"],
    )
    profile = {
        "display_name": "",
        "presenter_alias": "",
        "creator_profile": {
            "identity": {
                "public_name": "",
                "real_name": "",
            }
        },
    }

    monkeypatch.setattr(avatar_materials, "_publication_browser_local_state_path", lambda browser: local_state_path)
    monkeypatch.setattr(avatar_materials, "_publication_browser_user_data_dir", lambda browser: user_data_dir)
    fallback_user_data_dir = tmp_path / "agent user data"
    fallback_user_data_dir.mkdir()
    agent_profile_id = build_publication_browser_profile_id(
        browser="chrome",
        user_data_dir=str(fallback_user_data_dir),
        profile_directory="Profile 9",
    )
    monkeypatch.setattr(
        avatar_materials,
        "_resolve_agent_attached_browser_binding",
        lambda browser: {
            "browser": "chrome",
            "user_data_dir": str(fallback_user_data_dir),
            "profile_directory": "Profile 9",
            "profile_id": agent_profile_id,
        },
    )

    binding = avatar_materials._resolve_browser_profile_binding_for_creator(
        browser="chrome",
        profile=profile,
        body=body,
    )

    assert binding["user_data_dir"] == str(fallback_user_data_dir).replace("\\", "/")
    assert binding["profile_directory"] == "Profile 9"
    assert binding["profile_id"] == agent_profile_id


def test_preserve_profile_credentials_when_update_payload_omits_them(monkeypatch):
    existing = {
        "publishing": {
            "platform_credentials": [
                {"platform": "douyin", "platform_label": "抖音", "credential_ref": "keep-this-credential"}
            ]
        }
    }
    incoming = {
        "publishing": {
            "primary_platform": "抖音",
            "active_platforms": ["抖音"],
        },
        "identity": {"public_name": "FAS"},
    }

    normalized = avatar_materials._preserve_profile_credentials_on_update(existing, incoming)

    assert normalized["publishing"]["platform_credentials"] == existing["publishing"]["platform_credentials"]
    assert normalized["identity"]["public_name"] == "FAS"


def test_avatar_materials_root_respects_env_override(monkeypatch, tmp_path):
    override_root = tmp_path / "avatar-materials"
    monkeypatch.setenv("ROUGHCUT_AVATAR_MATERIALS_DIR", str(override_root))

    root = avatar_materials_root()

    assert root == override_root
    assert root.exists()
