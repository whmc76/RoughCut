from __future__ import annotations

from tests.creator_assets_testkit import creator_assets_client


def test_task_strategies_generate_refine_activate_and_keep_versions(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测", "natural_language_profile": "先结论后依据"},
    ).json()["id"]

    generate_response = client.post(
        f"/creator-cards/{creator_id}/task-strategies/generate",
        json={"prompt": "新品开箱和老款对比，突出升级点和适合谁", "strategy_type": "product_review", "candidate_count": 2},
    )
    assert generate_response.status_code == 200
    generated = generate_response.json()["items"]
    assert len(generated) == 2
    first_strategy = generated[0]
    second_strategy = generated[1]
    assert first_strategy["is_active"] is True
    assert second_strategy["is_active"] is False
    assert len(first_strategy["versions"]) == 1
    assert first_strategy["strategy_payload_json"]["strategy_goal"] != second_strategy["strategy_payload_json"]["strategy_goal"]
    assert first_strategy["strategy_payload_json"]["editing_playbook"] != second_strategy["strategy_payload_json"]["editing_playbook"]
    assert first_strategy["strategy_payload_json"]["opening_policy"] != second_strategy["strategy_payload_json"]["opening_policy"]
    assert first_strategy["strategy_payload_json"]["structure_policy"] != second_strategy["strategy_payload_json"]["structure_policy"]
    assert first_strategy["strategy_payload_json"]["policy_scope"]
    assert first_strategy["strategy_payload_json"]["priority_bias"] != second_strategy["strategy_payload_json"]["priority_bias"]
    assert first_strategy["strategy_payload_json"]["speech_rhythm_policy"] != second_strategy["strategy_payload_json"]["speech_rhythm_policy"]
    assert first_strategy["strategy_payload_json"]["shot_length_policy"] != second_strategy["strategy_payload_json"]["shot_length_policy"]
    assert first_strategy["strategy_payload_json"]["keep_policy"]
    assert first_strategy["strategy_payload_json"]["cut_policy"]
    assert first_strategy["strategy_payload_json"]["packaging_strategy"] != second_strategy["strategy_payload_json"]["packaging_strategy"]
    assert first_strategy["strategy_payload_json"]["transition_policy"]
    assert first_strategy["strategy_payload_json"]["effect_insert_policy"]
    assert first_strategy["strategy_payload_json"]["effect_frequency"] != second_strategy["strategy_payload_json"]["effect_frequency"]
    assert first_strategy["strategy_payload_json"]["effect_logic"]
    assert first_strategy["strategy_payload_json"]["effect_style"]
    assert first_strategy["strategy_payload_json"]["evidence_policy"]
    assert first_strategy["strategy_payload_json"]["manual_review_boundary"]
    assert first_strategy["strategy_payload_json"]["applicable_scenes"]
    assert first_strategy["strategy_payload_json"]["routing_matrix"]["product_review"]
    assert first_strategy["strategy_payload_json"]["success_metric"]
    assert first_strategy["strategy_payload_json"]["expected_effect"]
    assert first_strategy["strategy_payload_json"]["sample_case"]

    refine_response = client.post(
        f"/creator-cards/task-strategies/{first_strategy['id']}/refine",
        json={"prompt": "开头再克制一点，不要太像营销。"},
    )
    assert refine_response.status_code == 200
    refined = refine_response.json()
    assert refined["status"] == "refined"
    assert len(refined["versions"]) == 2
    assert refined["versions"][0]["operation"] == "generate"
    assert refined["versions"][1]["operation"] == "refine"
    assert "营销" in refined["versions"][1]["prompt"]

    activate_response = client.post(f"/creator-cards/task-strategies/{second_strategy['id']}/activate")
    assert activate_response.status_code == 200
    activated = activate_response.json()
    assert activated["is_active"] is True

    list_response = client.get(f"/creator-cards/{creator_id}/task-strategies")
    assert list_response.status_code == 200
    by_id = {item["id"]: item for item in list_response.json()["items"]}
    assert by_id[first_strategy["id"]]["is_active"] is False
    assert by_id[second_strategy["id"]]["is_active"] is True

    versions_response = client.get(f"/creator-cards/task-strategies/{first_strategy['id']}/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert [item["version"] for item in versions] == [1, 2]


def test_task_strategies_generate_accepts_empty_prompt(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测", "natural_language_profile": "结论先行"},
    ).json()["id"]

    response = client.post(
        f"/creator-cards/{creator_id}/task-strategies/generate",
        json={"prompt": "", "strategy_type": "creator_bound", "candidate_count": 1},
    )

    assert response.status_code == 200
    strategy = response.json()["items"][0]
    assert strategy["summary"] == "基于创作者卡片直接生成的候选任务策略。"
    assert strategy["strategy_payload_json"]["intent"] == "基于创作者卡片直接生成默认剪辑策略"


def test_task_strategies_generate_replaces_previous_candidates(creator_assets_client):
    client, _session_factory = creator_assets_client
    creator_id = client.post(
        "/creator-cards",
        json={"name": "FAS", "positioning": "专业评测"},
    ).json()["id"]

    first_response = client.post(
        f"/creator-cards/{creator_id}/task-strategies/generate",
        json={"prompt": "第一轮", "strategy_type": "creator_bound", "candidate_count": 3},
    )
    assert first_response.status_code == 200
    first_ids = {item["id"] for item in first_response.json()["items"]}
    assert len(first_ids) == 3

    second_response = client.post(
        f"/creator-cards/{creator_id}/task-strategies/generate",
        json={"prompt": "第二轮", "strategy_type": "creator_bound", "candidate_count": 2},
    )
    assert second_response.status_code == 200
    second_items = second_response.json()["items"]
    second_ids = {item["id"] for item in second_items}

    assert len(second_items) == 2
    assert first_ids.isdisjoint(second_ids)
    assert [item["is_active"] for item in second_items].count(True) == 1
