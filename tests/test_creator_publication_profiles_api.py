from __future__ import annotations

from tests.creator_assets_testkit import creator_assets_client


def test_publication_profile_patch_refine_and_bindings_keep_versions(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["bilibili", "douyin"]},
    ).json()["id"]

    get_response = client.get(f"/creator-cards/{creator_id}/publication-profile")
    assert get_response.status_code == 200
    profile = get_response.json()
    profile_id = profile["id"]
    assert profile["publication_payload_json"]["default_platforms"] == ["bilibili", "douyin"]
    collection_strategy = profile["publication_payload_json"]["collection_strategy"]
    assert collection_strategy["mode"] == "llm_classify"
    assert collection_strategy["default_collection_name"] == "EDC刀光火工具集"
    assert "EDC潮玩桌搭" in collection_strategy["candidate_collections"]
    assert collection_strategy["rules"][0]["natural_language_rule"]
    assert "bilibili" not in profile["publication_payload_json"]["platform_options"]
    assert len(profile["versions"]) == 1

    patch_response = client.patch(
        f"/creator-cards/{creator_id}/publication-profile",
        json={"status": "active", "publication_payload_json": {"default_platforms": ["douyin"], "publication_mode": "manual_handoff"}},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["status"] == "active"
    assert patched["publication_payload_json"]["publication_mode"] == "manual_handoff"
    assert len(patched["versions"]) == 2

    refine_response = client.post(
        f"/creator-cards/{creator_id}/publication-profile/refine",
        json={"prompt": "B 站标题保留型号和完整结论，抖音前三秒更直接。"},
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["status"] == "refined"
    assert len(refined["versions"]) == 3
    assert refined["versions"][-1]["operation"] == "refine"

    add_binding_response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings",
        json={
            "platform": "bilibili",
            "credential_ref": "cred-ref-bili",
            "binding_payload_json": {"channel": "测评"},
        },
    )
    assert add_binding_response.status_code == 200
    binding_profile = add_binding_response.json()
    assert binding_profile["bindings"][0]["credential_ref"] == "cred-ref-bili"

    delete_binding_response = client.delete(f"/creator-cards/{creator_id}/platform-bindings/bilibili")
    assert delete_binding_response.status_code == 200
    deleted_binding_profile = delete_binding_response.json()
    assert deleted_binding_profile["id"] == profile_id
    assert deleted_binding_profile["bindings"] == []


def test_publication_profile_collection_strategy_derives_platform_options(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["bilibili", "xiaohongshu"]},
    ).json()["id"]

    response = client.patch(
        f"/creator-cards/{creator_id}/publication-profile",
        json={
            "publication_payload_json": {
                "default_platforms": ["bilibili", "xiaohongshu"],
                "collection_strategy": {
                    "mode": "select_existing",
                    "default_collection_name": "EDC刀光火工具集",
                },
            }
        },
    )

    assert response.status_code == 200
    payload = response.json()["publication_payload_json"]
    assert payload["collection_strategy"]["default_collection_name"] == "EDC刀光火工具集"
    assert payload["platform_options"]["bilibili"]["collection_name"] == "EDC刀光火工具集"
    assert (
        payload["platform_options"]["bilibili"]["platform_specific_overrides"]["collection_management"]["selected_collection_name"]
        == "EDC刀光火工具集"
    )
    assert payload["platform_options"]["xiaohongshu"]["collection_name"] == "EDC刀光火工具集"


def test_fas_publication_profile_backfills_missing_rule_based_collection_rules(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["bilibili", "douyin"]},
    ).json()["id"]

    response = client.patch(
        f"/creator-cards/{creator_id}/publication-profile",
        json={
            "publication_payload_json": {
                "collection_strategy": {
                    "mode": "llm_classify",
                    "default_collection_name": "EDC刀光火工具集",
                    "rules": [{"match": ["MOT", "风灵"], "collection_name": "EDC潮玩桌搭"}],
                },
            }
        },
    )

    assert response.status_code == 200
    collection_strategy = response.json()["publication_payload_json"]["collection_strategy"]
    assert collection_strategy["mode"] == "llm_classify"
    assert collection_strategy["rules"]
    assert any(
        rule["collection_name"] == "EDC潮玩桌搭" and rule["natural_language_rule"]
        for rule in collection_strategy["rules"]
    )
    assert "bilibili" not in response.json()["publication_payload_json"]["platform_options"]


def test_social_auto_upload_login_binding_writes_executor_metadata(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["wechat_channels"]},
    ).json()["id"]

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={"platform": "wechat_channels", "browser": "chrome"},
    )

    assert response.status_code == 200
    profile = response.json()
    assert profile["bindings"][0]["platform"] == "wechat-channels"
    assert profile["bindings"][0]["credential_ref"] == "social-auto-upload:FAS · Chrome:wechat-channels"
    payload = profile["bindings"][0]["binding_payload_json"]
    assert payload["adapter"] == "social_auto_upload"
    assert payload["account_name"] == "FAS · Chrome"
    assert payload["platform_label"] == "视频号"
    assert payload["browser"] == "chrome"
    assert payload["status"] == "login_reference_bound"

    delete_response = client.delete(f"/creator-cards/{creator_id}/platform-bindings/wechat_channels")
    assert delete_response.status_code == 200
    assert delete_response.json()["bindings"] == []
