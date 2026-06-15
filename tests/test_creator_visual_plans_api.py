from __future__ import annotations

from tests.creator_assets_testkit import creator_assets_client


def test_visual_plans_generate_refine_activate_and_keep_versions(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测", "natural_language_profile": "画面干净，少广告感"},
    ).json()["id"]

    generate_response = client.post(
        f"/creator-cards/{creator_id}/visual-plans/generate",
        json={"prompt": "科技产品开箱对比，强调升级感和可信度", "candidate_count": 2},
    )
    assert generate_response.status_code == 200
    generated = generate_response.json()["items"]
    assert len(generated) == 2
    first_plan = generated[0]
    second_plan = generated[1]
    assert first_plan["is_active"] is True
    assert len(first_plan["versions"]) == 1
    assert first_plan["visual_payload_json"]["cover_direction"] != second_plan["visual_payload_json"]["cover_direction"]
    assert first_plan["visual_payload_json"]["sample_case"]["cover_text"] != second_plan["visual_payload_json"]["sample_case"]["cover_text"]
    assert first_plan["visual_payload_json"]["sample_case"]["subtitle_sample"]

    refine_response = client.post(
        f"/creator-cards/visual-plans/{first_plan['id']}/refine",
        json={"prompt": "封面不要过饱和，标题更像测评结论。"},
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["status"] == "refined"
    assert len(refined["versions"]) == 2
    assert refined["versions"][1]["operation"] == "refine"
    assert refined["visual_payload_json"]["copy_tone"] == "封面不要过饱和，标题更像测评结论。"

    activate_response = client.post(f"/creator-cards/visual-plans/{second_plan['id']}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True

    list_response = client.get(f"/creator-cards/{creator_id}/visual-plans")
    assert list_response.status_code == 200
    by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert by_id[first_plan["id"]]["is_active"] is False
    assert by_id[second_plan["id"]]["is_active"] is True

    versions_response = client.get(f"/creator-cards/visual-plans/{first_plan['id']}/versions")
    assert versions_response.status_code == 200
    assert [item["version"] for item in versions_response.json()] == [1, 2]


def test_visual_plans_generate_accepts_empty_prompt(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测", "natural_language_profile": "画面干净，少广告感"},
    ).json()["id"]

    response = client.post(
        f"/creator-cards/{creator_id}/visual-plans/generate",
        json={"prompt": "", "candidate_count": 1},
    )

    assert response.status_code == 200
    plan = response.json()["items"][0]
    assert plan["summary"] == "基于创作者卡片直接生成的候选视觉方向。"
    assert "基于创作者卡片直接生成默认视觉方向" in plan["visual_payload_json"]["copy_tone"]
    assert plan["visual_payload_json"]["sample_case"]["title_sample"]


def test_visual_plans_generate_replaces_previous_candidates(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测"},
    ).json()["id"]

    first_response = client.post(
        f"/creator-cards/{creator_id}/visual-plans/generate",
        json={"prompt": "第一轮", "candidate_count": 3},
    )
    assert first_response.status_code == 200
    first_ids = {item["id"] for item in first_response.json()["items"]}
    assert len(first_ids) == 3

    second_response = client.post(
        f"/creator-cards/{creator_id}/visual-plans/generate",
        json={"prompt": "第二轮", "candidate_count": 2},
    )
    assert second_response.status_code == 200
    second_items = second_response.json()["items"]
    second_ids = {item["id"] for item in second_items}

    assert len(second_items) == 2
    assert first_ids.isdisjoint(second_ids)
    assert [item["is_active"] for item in second_items].count(True) == 1
