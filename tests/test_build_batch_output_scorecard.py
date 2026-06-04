from scripts import build_batch_output_scorecard as scorecard


def test_score_platform_package_skips_soft_youtube_tags_penalty() -> None:
    packaging = {
        "platforms": {
            "youtube": {
                "titles": ["真实 YouTube 标题"],
                "description": "真实 YouTube 描述",
                "tags": [],
                "publish_ready": True,
                "live_publish_preflight": {"status": "ready", "blocking_reasons": []},
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 100.0
    assert result["ready_count"] == 1
    assert result["blocked_count"] == 0
    assert result["manual_handoff_count"] == 0
    assert result["platform_scores"][0]["platform"] == "youtube"
    assert result["platform_scores"][0]["status"] == "ready"
    assert result["platform_scores"][0]["tag_count"] == 0


def test_score_platform_package_keeps_hard_tag_penalty_for_non_soft_platform() -> None:
    packaging = {
        "platforms": {
            "douyin": {
                "titles": ["真实抖音标题"],
                "description": "真实抖音描述",
                "tags": [],
                "publish_ready": True,
                "live_publish_preflight": {"status": "ready", "blocking_reasons": []},
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 85.0
    assert result["platform_scores"][0]["platform"] == "douyin"
    assert result["platform_scores"][0]["status"] == "ready"
    assert result["platform_scores"][0]["tag_count"] == 0


def test_score_platform_package_reports_manual_handoff_platforms_separately() -> None:
    packaging = {
        "platforms": {
            "wechat-channels": {
                "titles": [],
                "description": "",
                "tags": [],
                "publish_ready": False,
                "manual_handoff_only": True,
                "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                "live_publish_preflight": {
                    "status": "manual_handoff",
                    "blocking_reasons": ["需要人工登录"],
                },
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["score"] == 100.0
    assert result["manual_handoff_count"] == 1
    assert result["ready_count"] == 0
    assert result["blocked_count"] == 0
    assert "人工接管 1 个" in result["summary"]
    assert result["platform_scores"][0]["platform"] == "wechat-channels"
    assert result["platform_scores"][0]["status"] == "manual_handoff"


def test_score_platform_package_blocks_stale_publish_ready_true_when_preflight_is_blocked() -> None:
    packaging = {
        "platforms": {
            "douyin": {
                "titles": ["真实抖音标题"],
                "description": "真实抖音描述",
                "tags": ["开箱"],
                "publish_ready": True,
                "live_publish_preflight": {
                    "status": "blocked",
                    "blocking_reasons": ["缺少封面"],
                    "missing_required_surfaces": ["cover"],
                },
            }
        }
    }

    result = scorecard._score_platform_package(packaging, publish_path=None)

    assert result["ready_count"] == 0
    assert result["blocked_count"] == 1
    assert result["platform_scores"][0]["platform"] == "douyin"
    assert result["platform_scores"][0]["status"] == "blocked"


def test_score_editing_prefers_variant_bundle_cut_analysis_and_refine_summary() -> None:
    result = scorecard._score_editing_with_variant_bundle(
        {"keep_ratio": 0.5, "quality_issue_codes": []},
        {
            "analysis": {
                "accepted_cuts": [],
                "llm_cut_review": {"reviewed": False, "candidate_count": 0},
            }
        },
        {"editing_accents": {"transitions": {"boundary_indexes": [1, 2]}}},
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "cut_analysis_summary": {"accepted_cut_count": 3},
                    "llm_cut_review": {"reviewed": True, "candidate_count": 4},
                    "refine_decision_summary": {"mode": "auto_refine", "candidate_total": 6},
                }
            },
        },
    )

    assert result["status"] == "done"
    assert "accepted_cuts=3" in result["summary"]
    assert "llm_cut_review=yes" in result["summary"]
    assert "refine_mode=auto_refine" in result["summary"]
    assert "refine_candidates=6" in result["summary"]
