from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select

from roughcut.api import creator_assets as creator_assets_api
from roughcut.db.models import CreatorAsset

from tests.creator_assets_testkit import creator_assets_client


class _FakeReasoningResponse:
    model = "fake-llm"
    usage = {"input_tokens": 1, "output_tokens": 1}

    def __init__(self, payload):
        self._payload = payload

    def as_json(self):
        return self._payload


class _FakeReasoningProvider:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload or {}
        self.error = error

    async def complete(self, *_args, **_kwargs):
        if self.error is not None:
            raise self.error
        return _FakeReasoningResponse(self.payload)


def test_creator_card_crud_and_asset_upload(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])
    monkeypatch.setattr(
        creator_assets_api,
        "get_reasoning_provider",
        lambda: _FakeReasoningProvider({"natural_language_profile": "表达风格克制，判断先行"}),
    )

    create_response = client.post(
        "/creator-cards",
        json={
            "name": "FAS EDC",
            "positioning": "专业测评型创作者",
            "content_domains": ["edc", "flashlight"],
            "default_platforms": ["bilibili", "douyin"],
            "natural_language_profile": "克制、可信、结论先行。",
        },
    )
    assert create_response.status_code == 201
    creator = create_response.json()
    creator_id = creator["id"]
    assert creator["name"] == "FAS EDC"
    assert creator["assets"] == []

    refine_response = client.post(
        f"/creator-cards/{creator_id}/refine",
        json={"prompt": "创作者表达风格改成克制，判断先行。"},
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert "判断先行" in (refined["natural_language_profile"] or "")
    assert len(refined["preferences"]) == 1

    upload_response = client.post(
        f"/creator-cards/{creator_id}/assets",
        files={"file": ("reference.txt", b"creator reference", "text/plain")},
    )
    assert upload_response.status_code == 201
    uploaded = upload_response.json()
    assert len(uploaded["assets"]) == 1
    asset_id = uploaded["assets"][0]["id"]
    assert uploaded["assets"][0]["metadata_json"]["size_bytes"] == len(b"creator reference")

    patch_response = client.patch(
        f"/creator-cards/{creator_id}",
        json={"audience": "EDC 发烧友", "status": "active"},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["audience"] == "EDC 发烧友"
    assert patched["status"] == "active"

    delete_asset_response = client.delete(f"/creator-cards/{creator_id}/assets/{asset_id}")
    assert delete_asset_response.status_code == 200
    assert delete_asset_response.json()["assets"] == []

    list_response = client.get("/creator-cards")
    assert list_response.status_code == 200
    assert len(list_response.json()["items"]) == 1

    delete_response = client.delete(f"/creator-cards/{creator_id}")
    assert delete_response.status_code == 204
    assert client.get("/creator-cards").json()["items"] == []


def test_creator_asset_file_resolves_and_repairs_legacy_container_path(creator_assets_client, monkeypatch):
    client, session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])

    create_response = client.post(
        "/creator-cards",
        json={
            "name": "FAS EDC",
            "positioning": "专业测评型创作者",
            "content_domains": [],
            "default_platforms": [],
            "natural_language_profile": None,
        },
    )
    creator_id = create_response.json()["id"]
    upload_response = client.post(
        f"/creator-cards/{creator_id}/assets",
        files={"file": ("reference.txt", b"creator reference", "text/plain")},
    )
    asset = upload_response.json()["assets"][0]
    asset_id = asset["id"]
    asset_uuid = uuid.UUID(asset_id)
    stored_path = asset["stored_path"].replace("\\", "/")
    legacy_path = "/app/data/output/_creator_assets/" + stored_path.split("/_creator_assets/", 1)[1]

    async def _write_legacy_path() -> None:
        async with session_factory() as session:
            row = await session.get(CreatorAsset, asset_uuid)
            assert row is not None
            row.stored_path = legacy_path
            await session.commit()

    asyncio.run(_write_legacy_path())

    file_response = client.get(f"/creator-cards/{creator_id}/assets/{asset_id}/file")

    assert file_response.status_code == 200
    assert file_response.content == b"creator reference"

    async def _read_repaired_path() -> str:
        async with session_factory() as session:
            row = (await session.execute(select(CreatorAsset).where(CreatorAsset.id == asset_uuid))).scalar_one()
            return row.stored_path

    repaired_path = asyncio.run(_read_repaired_path())
    assert repaired_path != legacy_path
    assert repaired_path.endswith("/_creator_assets/" + stored_path.split("/_creator_assets/", 1)[1])


def test_creator_card_refine_updates_public_name_without_polluting_profile(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])
    monkeypatch.setattr(
        creator_assets_api,
        "get_reasoning_provider",
        lambda: _FakeReasoningProvider({"name": "FAS机神圣殿x潮玩EDC"}),
    )

    create_response = client.post(
        "/creator-cards",
        json={
            "name": "FAS",
            "positioning": None,
            "content_domains": [],
            "default_platforms": ["bilibili"],
            "natural_language_profile": "公开名称：FAS\n克制、可信。",
        },
    )
    assert create_response.status_code == 201
    creator_id = create_response.json()["id"]

    refine_response = client.post(
        f"/creator-cards/{creator_id}/refine",
        json={"prompt": "公开名称是 FAS机神圣殿x潮玩EDC"},
    )

    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["name"] == "FAS机神圣殿x潮玩EDC"
    assert "公开名称" not in (refined["natural_language_profile"] or "")
    assert any(
        preference["structured_payload"]["applied_patch"]["name"] == "FAS机神圣殿x潮玩EDC"
        and preference["structured_payload"]["agent"]["source"] == "llm"
        for preference in refined["preferences"]
    )


def test_creator_card_refine_rule_fallback_does_not_append_public_name_prompt(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])
    monkeypatch.setattr(
        creator_assets_api,
        "get_reasoning_provider",
        lambda: _FakeReasoningProvider(error=RuntimeError("llm unavailable")),
    )

    create_response = client.post(
        "/creator-cards",
        json={
            "name": "FAS",
            "positioning": None,
            "content_domains": [],
            "default_platforms": [],
            "natural_language_profile": "公开名称：FAS\n克制、可信。",
        },
    )
    creator_id = create_response.json()["id"]

    refine_response = client.post(
        f"/creator-cards/{creator_id}/refine",
        json={"prompt": "公开名称是 FAS机神圣殿x潮玩EDC"},
    )

    assert refine_response.status_code == 503
    assert "fallback result" in refine_response.json()["detail"]
    current = client.get(f"/creator-cards/{creator_id}")
    assert current.status_code == 200
    assert current.json()["name"] == "FAS"
    assert current.json()["natural_language_profile"] == "公开名称：FAS\n克制、可信。"


def test_creator_card_refine_rule_fallback_ignores_visual_only_request(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])
    monkeypatch.setattr(
        creator_assets_api,
        "get_reasoning_provider",
        lambda: _FakeReasoningProvider(error=RuntimeError("llm unavailable")),
    )

    create_response = client.post(
        "/creator-cards",
        json={
            "name": "FAS",
            "positioning": None,
            "content_domains": [],
            "default_platforms": [],
            "natural_language_profile": "克制、可信。",
        },
    )
    creator_id = create_response.json()["id"]

    refine_response = client.post(
        f"/creator-cards/{creator_id}/refine",
        json={"prompt": "字幕克制一点，标题不要广告腔"},
    )

    assert refine_response.status_code == 503
    assert "fallback result" in refine_response.json()["detail"]
    current = client.get(f"/creator-cards/{creator_id}")
    assert current.status_code == 200
    assert current.json()["name"] == "FAS"
    assert current.json()["natural_language_profile"] == "克制、可信。"


def test_creator_card_list_imports_legacy_avatar_profiles(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client

    monkeypatch.setattr(
        creator_assets_api,
        "list_avatar_material_profiles",
        lambda: [
            {
                "id": "legacy-fas",
                "display_name": "FAS",
                "presenter_alias": "flashlight_fas",
                "notes": "旧档案备注",
                "creator_profile": {
                    "identity": {"public_name": "FAS", "bio": "专注 EDC 和手电测评"},
                    "positioning": {
                        "creator_focus": "EDC 测评",
                        "expertise": ["edc", "flashlight"],
                        "audience": "装备发烧友",
                        "style": "克制结论型",
                        "tone_keywords": ["可信", "直接"],
                    },
                    "publishing": {
                        "primary_platform": "bilibili",
                        "active_platforms": ["douyin"],
                    },
                    "archive_notes": "从旧档案自动迁移",
                },
            }
        ],
    )

    first = client.get("/creator-cards")
    assert first.status_code == 200
    items = first.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "FAS"
    assert items[0]["content_domains"] == ["edc", "flashlight"]
    assert items[0]["default_platforms"] == ["bilibili", "douyin"]
    assert items[0]["audience"] == "装备发烧友"
    assert items[0]["status"] == "active"
    assert any(preference["source"] == "legacy_avatar_profile" for preference in items[0]["preferences"])

    second = client.get("/creator-cards")
    assert second.status_code == 200
    assert len(second.json()["items"]) == 1


def test_creator_card_create_rejects_when_limit_reached(creator_assets_client, monkeypatch):
    client, _session_factory = creator_assets_client
    monkeypatch.setattr(creator_assets_api, "list_avatar_material_profiles", lambda: [])

    for index in range(10):
        response = client.post(
            "/creator-cards",
            json={
                "name": f"Creator {index}",
                "positioning": None,
                "content_domains": [],
                "default_platforms": [],
                "natural_language_profile": None,
            },
        )
        assert response.status_code == 201

    rejected = client.post(
        "/creator-cards",
        json={
            "name": "Creator 10",
            "positioning": None,
            "content_domains": [],
            "default_platforms": [],
            "natural_language_profile": None,
        },
    )
    assert rejected.status_code == 400
    assert "最多只能保存 10 个创作者卡片" in rejected.json()["detail"]
