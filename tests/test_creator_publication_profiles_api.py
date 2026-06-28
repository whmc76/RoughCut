from __future__ import annotations

from types import SimpleNamespace

from roughcut.api import creator_assets


def _expected_social_auto_upload_account_key(creator_id: str, platform: str, browser: str = "chrome") -> str:
    return f"creator-{creator_id.replace('-', '')[:12]}-{platform}-{browser}"


def _mock_social_auto_upload_login_valid(monkeypatch):
    async def fake_check(**kwargs):  # noqa: ANN003
        return {
            "status": "login_valid",
            "command": ["python", "sau_cli.py", kwargs["platform"], "check", "--account", kwargs["account_name"]],
            "check_source": "test",
            "returncode": 0,
            "stdout": "valid",
            "stderr": "",
            "warning": "",
        }

    monkeypatch.setattr(creator_assets, "_run_social_auto_upload_login_check", fake_check)


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


def test_social_auto_upload_login_binding_requires_confirmed_account(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["wechat_channels"]},
    ).json()["id"]

    missing_account_response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={"platform": "wechat_channels", "browser": "chrome", "login_confirmed": True},
    )
    assert missing_account_response.status_code == 400

    unconfirmed_response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={"platform": "wechat_channels", "browser": "chrome", "account_name": "FAS 视频号主号"},
    )
    assert unconfirmed_response.status_code == 409

    profile = client.get(f"/creator-cards/{creator_id}/publication-profile").json()
    assert profile["bindings"] == []


def test_social_auto_upload_login_binding_writes_executor_metadata(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    _mock_social_auto_upload_login_valid(monkeypatch)
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["wechat_channels"]},
    ).json()["id"]

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={
            "platform": "wechat_channels",
            "browser": "chrome",
            "account_name": "FAS 视频号主号",
            "login_confirmed": True,
        },
    )

    assert response.status_code == 200
    profile = response.json()
    account_key = _expected_social_auto_upload_account_key(creator_id, "wechat-channels")
    assert profile["bindings"][0]["platform"] == "wechat-channels"
    assert profile["bindings"][0]["credential_ref"] == f"social-auto-upload:{account_key}:wechat-channels"
    payload = profile["bindings"][0]["binding_payload_json"]
    assert payload["adapter"] == "social_auto_upload"
    assert payload["account_name"] == account_key
    assert payload["account_label"] == "FAS 视频号主号"
    assert payload["platform_label"] == "视频号"
    assert payload["browser"] == "chrome"
    assert payload["status"] == "login_confirmed"

    delete_response = client.delete(f"/creator-cards/{creator_id}/platform-bindings/wechat_channels")
    assert delete_response.status_code == 200
    assert delete_response.json()["bindings"] == []


def test_social_auto_upload_account_key_is_isolated_by_creator(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    _mock_social_auto_upload_login_valid(monkeypatch)
    creator_a_id = client.post("/creator-cards", json={"name": "创作者A", "default_platforms": ["bilibili"]}).json()["id"]
    creator_b_id = client.post("/creator-cards", json={"name": "创作者B", "default_platforms": ["bilibili"]}).json()["id"]

    body = {
        "platform": "bilibili",
        "browser": "chrome",
        "account_name": "同名 B 站账号",
        "login_confirmed": True,
    }

    profile_a = client.post(f"/creator-cards/{creator_a_id}/platform-bindings/social-auto-upload", json=body).json()
    profile_b = client.post(f"/creator-cards/{creator_b_id}/platform-bindings/social-auto-upload", json=body).json()
    binding_a = profile_a["bindings"][0]
    binding_b = profile_b["bindings"][0]

    assert binding_a["credential_ref"] == f"social-auto-upload:{_expected_social_auto_upload_account_key(creator_a_id, 'bilibili')}:bilibili"
    assert binding_b["credential_ref"] == f"social-auto-upload:{_expected_social_auto_upload_account_key(creator_b_id, 'bilibili')}:bilibili"
    assert binding_a["credential_ref"] != binding_b["credential_ref"]
    assert binding_a["binding_payload_json"]["account_label"] == "同名 B 站账号"
    assert binding_b["binding_payload_json"]["account_label"] == "同名 B 站账号"


def test_social_auto_upload_binding_rejects_invalid_runtime_login(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "Demo Creator", "default_platforms": ["wechat_channels"]},
    ).json()["id"]

    async def fake_check(**kwargs):  # noqa: ANN003
        return {
            "status": "login_invalid",
            "command": ["python", "sau_cli.py", kwargs["platform"], "check", "--account", kwargs["account_name"]],
            "check_source": "test",
            "returncode": 1,
            "stdout": "invalid",
            "stderr": "",
            "warning": "",
        }

    monkeypatch.setattr(creator_assets, "_run_social_auto_upload_login_check", fake_check)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={
            "platform": "wechat_channels",
            "browser": "chrome",
            "account_name": "Demo Creator · 视频号",
            "login_confirmed": True,
        },
    )

    assert response.status_code == 409
    assert client.get(f"/creator-cards/{creator_id}/publication-profile").json()["bindings"] == []


def test_social_auto_upload_login_endpoint_starts_headed_login_command(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["douyin"]},
    ).json()["id"]
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, True),
    )

    def fake_spawn(command, *, root):  # noqa: ANN001
        observed["command"] = command
        observed["root"] = root
        return 12345

    monkeypatch.setattr(creator_assets, "_spawn_social_auto_upload_login", fake_spawn)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/login",
        json={"platform": "douyin", "browser": "chrome", "account_name": "FAS 抖音主号"},
    )

    assert response.status_code == 200
    payload = response.json()
    account_key = _expected_social_auto_upload_account_key(creator_id, "douyin")
    assert payload["status"] == "login_started"
    assert payload["pid"] == 12345
    assert payload["root_exists_in_api_runtime"] is True
    assert payload["account_name"] == account_key
    assert payload["account_label"] == "FAS 抖音主号"
    assert observed["root"] == "C:/sample-workspace/_eval/social-auto-upload"
    assert observed["command"] == ["python", "sau_cli.py", "douyin", "login", "--account", account_key, "--headed"]


def test_social_auto_upload_login_endpoint_returns_manual_command_when_root_is_not_accessible(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["douyin"]},
    ).json()["id"]

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, False),
    )
    async def fake_host_login(**kwargs):  # noqa: ANN003
        return None

    monkeypatch.setattr(creator_assets, "_start_social_auto_upload_login_via_host_bridge", fake_host_login)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/login",
        json={"platform": "douyin", "browser": "chrome", "account_name": "FAS 抖音主号"},
    )

    assert response.status_code == 200
    payload = response.json()
    account_key = _expected_social_auto_upload_account_key(creator_id, "douyin")
    assert payload["status"] == "manual_login_required"
    assert payload["pid"] is None
    assert payload["root_exists_in_api_runtime"] is False
    assert "不可访问" in payload["warning"]
    assert payload["command"] == ["python", "sau_cli.py", "douyin", "login", "--account", account_key, "--headed"]


def test_social_auto_upload_login_endpoint_uses_host_bridge_when_api_runtime_cannot_access_root(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["douyin"]},
    ).json()["id"]

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, False),
    )

    async def fake_host_login(**kwargs):  # noqa: ANN003
        account_key = _expected_social_auto_upload_account_key(creator_id, "douyin")
        assert kwargs["root"] == "C:/sample-workspace/_eval/social-auto-upload"
        assert kwargs["platform"] == "douyin"
        assert kwargs["account_name"] == account_key
        return {
            "status": "login_started",
            "pid": 456,
            "launch_source": "codex_host_bridge",
            "command": ["python", "sau_cli.py", "douyin", "login", "--account", account_key, "--headed"],
        }

    monkeypatch.setattr(creator_assets, "_start_social_auto_upload_login_via_host_bridge", fake_host_login)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/login",
        json={"platform": "douyin", "browser": "chrome", "account_name": "FAS 抖音主号"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "login_started"
    assert payload["pid"] == 456
    assert payload["launch_source"] == "codex_host_bridge"
    assert payload["root_exists_in_api_runtime"] is False


def test_social_auto_upload_login_status_endpoint_reports_valid_local_check(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["douyin"]},
    ).json()["id"]

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, True),
    )

    async def fake_run(command, *, root, timeout_sec):  # noqa: ANN001
        account_key = _expected_social_auto_upload_account_key(creator_id, "douyin")
        assert command == ["python", "sau_cli.py", "douyin", "check", "--account", account_key]
        assert root == "C:/sample-workspace/_eval/social-auto-upload"
        assert timeout_sec == 120
        return SimpleNamespace(returncode=0, stdout="valid\n", stderr="", ok=True)

    monkeypatch.setattr(creator_assets, "run_social_auto_upload_command", fake_run)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/login-status",
        json={"platform": "douyin", "browser": "chrome", "account_name": "FAS 抖音主号"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "login_valid"
    assert payload["check_source"] == "api_runtime"
    assert payload["stdout"] == "valid"


def test_social_auto_upload_login_status_endpoint_uses_host_bridge_when_api_runtime_cannot_access_root(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "default_platforms": ["douyin"]},
    ).json()["id"]

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, False),
    )

    async def fake_host_check(**kwargs):  # noqa: ANN003
        account_key = _expected_social_auto_upload_account_key(creator_id, "douyin")
        assert kwargs["platform"] == "douyin"
        assert kwargs["account_name"] == account_key
        return {
            "status": "login_valid",
            "returncode": 0,
            "stdout": "valid",
            "stderr": "",
            "check_source": "codex_host_bridge",
            "command": ["python", "sau_cli.py", "douyin", "check", "--account", account_key],
        }

    monkeypatch.setattr(creator_assets, "_check_social_auto_upload_login_via_host_bridge", fake_host_check)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/login-status",
        json={"platform": "douyin", "browser": "chrome", "account_name": "FAS 抖音主号"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "login_valid"
    assert payload["check_source"] == "codex_host_bridge"
    assert payload["root_exists_in_api_runtime"] is False


def test_social_auto_upload_dashboard_uses_bound_isolated_account_key(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    _mock_social_auto_upload_login_valid(monkeypatch)
    creator_id = client.post(
        "/creator-cards",
        json={"name": "Demo Creator", "default_platforms": ["bilibili"]},
    ).json()["id"]
    account_key = _expected_social_auto_upload_account_key(creator_id, "bilibili")
    client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload",
        json={
            "platform": "bilibili",
            "browser": "chrome",
            "account_name": "Demo Creator · Chrome",
            "login_confirmed": True,
        },
    )

    monkeypatch.setattr(
        creator_assets,
        "_social_auto_upload_settings_or_400",
        lambda: ("C:/sample-workspace/_eval/social-auto-upload", "python", 1800, False),
    )

    async def fake_host_dashboard(**kwargs):  # noqa: ANN003
        assert kwargs["platform"] == "bilibili"
        assert kwargs["account_name"] == account_key
        return {
            "status": "dashboard_started",
            "pid": 789,
            "launch_source": "codex_host_bridge",
            "command": ["python", "sau_cli.py", "bilibili", "open-dashboard", "--account", account_key, "--headed"],
        }

    monkeypatch.setattr(creator_assets, "_open_social_auto_upload_dashboard_via_host_bridge", fake_host_dashboard)

    response = client.post(
        f"/creator-cards/{creator_id}/platform-bindings/social-auto-upload/dashboard",
        json={"platform": "bilibili", "browser": "chrome"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "dashboard_started"
    assert payload["pid"] == 789
    assert payload["account_name"] == account_key
    assert payload["account_label"] == "Demo Creator · Chrome"
    assert payload["credential_ref"] == f"social-auto-upload:{account_key}:bilibili"
    assert payload["root_exists_in_api_runtime"] is False
