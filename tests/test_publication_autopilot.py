from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import pytest

from scripts import run_publication_autopilot as autopilot


def test_material_gate_fails_without_contract() -> None:
    report = autopilot._material_gate_report(
        material_payload={"platforms": []},
        target_platforms=["douyin", "xiaohongshu"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert any("material_contract" in item for item in report["failures"])


@pytest.mark.asyncio
async def test_run_script_accepts_structured_output_after_timeout(tmp_path: Path) -> None:
    script_path = tmp_path / "emit_report_then_sleep.py"
    report_path = tmp_path / "report.json"
    script_path.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import sys",
                "import time",
                "from pathlib import Path",
                "out = Path(sys.argv[1])",
                "out.write_text(json.dumps({'status': 'passed', 'source': 'child-report'}, ensure_ascii=False), encoding='utf-8')",
                "print('report-written', flush=True)",
                "time.sleep(120)",
            ]
        ),
        encoding="utf-8",
    )

    return_code, stdout, stderr = await autopilot._run_script(
        script_path,
        [str(report_path)],
        timeout=1,
        structured_output_path=report_path,
    )

    assert report_path.is_file()
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "passed"
    assert stderr == ""
    assert isinstance(return_code, int)


def test_material_gate_blocks_one_click_when_platform_metadata_missing() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "one_click_publish_ready": False,
                "platforms": {
                    "douyin": {
                        "one_click_publish_ready": False,
                        "blocking_reasons": [],
                        "missing_fields": ["publication_metadata"],
                    },
                    "xiaohongshu": {
                        "one_click_publish_ready": True,
                        "blocking_reasons": [],
                        "missing_fields": [],
                    },
                },
            }
        },
        target_platforms=["douyin", "xiaohongshu"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert any("douyin" in item and "publication_metadata" in item for item in report["failures"])


def test_material_gate_reports_platform_outside_material_scope() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "one_click_publish_ready": True,
                "platform_scope": {
                    "requested_platforms": ["douyin", "xiaohongshu"],
                    "covered_platforms": ["douyin", "xiaohongshu"],
                    "missing_requested_platforms": [],
                },
                "platforms": {
                    "douyin": {
                        "one_click_publish_ready": True,
                        "blocking_reasons": [],
                        "missing_fields": [],
                    },
                    "xiaohongshu": {
                        "one_click_publish_ready": True,
                        "blocking_reasons": [],
                        "missing_fields": [],
                    },
                },
            }
        },
        target_platforms=["douyin", "toutiao"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert any("toutiao" in item and "不在本期物料生成范围内" in item for item in report["failures"])
    assert report["recommendations"] == [
        {
            "platform": "toutiao",
            "issue": "platform_scope_mismatch",
            "operations": ["regenerate_platform_material", "restrict_requested_platforms"],
            "auto_remediable": True,
        }
    ]
    assert report["recovery_index"] == {
        "issue_counts": {"platform_scope_mismatch": 1},
        "platform_counts": {"toutiao": 1},
        "auto_recoverable_recommendations": 1,
        "manual_required_recommendations": 0,
    }


def test_material_gate_recomputes_stale_persisted_contract_for_current_target_platforms() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": False,
                "blocking_reasons": ["发布范围不匹配：bilibili 不在本期物料生成范围内。当前仅覆盖平台 -> 无"],
                "platform_scope": {
                    "requested_platforms": ["bilibili"],
                    "covered_platforms": [],
                    "missing_requested_platforms": ["bilibili"],
                },
                "platforms": {},
            },
            "platforms": [],
        },
        target_platforms=["kuaishou"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert report["contract"]["platform_scope"]["requested_platforms"] == ["kuaishou"]
    assert report["contract"]["platform_scope"]["missing_requested_platforms"] == ["kuaishou"]
    assert report["contract"]["blocking_reasons"] == [
        "发布范围不匹配：kuaishou 不在本期物料生成范围内。当前仅覆盖平台 -> 无"
    ]
    assert report["failures"] == ["kuaishou: 不在本期物料生成范围内。当前仅覆盖平台 -> 无"]
    assert report["recommendations"] == [
        {
            "platform": "kuaishou",
            "issue": "platform_scope_mismatch",
            "operations": ["regenerate_platform_material", "restrict_requested_platforms"],
            "auto_remediable": True,
        }
    ]


def test_material_gate_returns_manual_handoff_for_manual_only_platforms() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "status": "manual_handoff",
                "one_click_publish_ready": True,
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
                "platforms": {
                    "wechat-channels": {
                        "label": "视频号",
                        "one_click_publish_ready": False,
                        "manual_handoff_only": True,
                        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                        "blocking_reasons": [],
                        "missing_fields": ["cover_path", "live_publish_preflight"],
                    }
                },
            }
        },
        target_platforms=["wechat-channels"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "manual_handoff"
    assert report["one_click_publish_ready"] is False
    assert report["manual_handoff_ready"] is True
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert report["failures"] == []


def test_material_gate_allows_mixed_auto_publish_and_manual_handoff_scope() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "status": "manual_handoff",
                "one_click_publish_ready": True,
                "manual_handoff_platforms": [
                    {
                        "platform": "wechat-channels",
                        "label": "视频号",
                        "login_url": "https://channels.weixin.qq.com/login.html",
                    }
                ],
                "platforms": {
                    "douyin": {
                        "label": "抖音",
                        "one_click_publish_ready": True,
                        "blocking_reasons": [],
                        "missing_fields": [],
                    },
                    "wechat-channels": {
                        "label": "视频号",
                        "one_click_publish_ready": False,
                        "manual_handoff_only": True,
                        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
                        "blocking_reasons": [],
                        "missing_fields": ["cover_path"],
                    },
                },
            }
        },
        target_platforms=["douyin", "wechat-channels"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "passed"
    assert report["one_click_publish_ready"] is True
    assert report["manual_handoff_ready"] is True
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert report["failures"] == []


def test_material_gate_prefers_platform_status_failed_over_stale_one_click_publish_ready_true() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "status": "failed",
                "one_click_publish_ready": True,
                "platforms": {
                    "douyin": {
                        "status": "failed",
                        "one_click_publish_ready": True,
                        "blocking_reasons": ["缺少 live_publish_preflight"],
                        "missing_fields": [],
                    },
                },
            }
        },
        target_platforms=["douyin"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert report["one_click_publish_ready"] is False
    assert report["failures"] == ["douyin: 缺少 live_publish_preflight"]


def test_material_gate_blocks_stale_one_click_publish_ready_true_when_entry_has_blockers_without_status() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "one_click_publish_ready": True,
                "platforms": {
                    "douyin": {
                        "one_click_publish_ready": True,
                        "blocking_reasons": ["缺少 live_publish_preflight"],
                        "missing_fields": ["publication_metadata"],
                    },
                },
            }
        },
        target_platforms=["douyin"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["status"] == "failed"
    assert report["one_click_publish_ready"] is False


def test_material_gate_emits_structured_recommendation_for_missing_metadata_failures() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_contract": {
                "one_click_publish_ready": False,
                "platforms": {
                    "douyin": {
                        "one_click_publish_ready": False,
                        "blocking_reasons": [],
                        "missing_fields": ["publication_metadata"],
                    }
                },
            }
        },
        target_platforms=["douyin"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "material_gate_failed",
            "operations": ["repair_material_contract", "rerun_material_gate"],
            "auto_remediable": True,
        }
    ]
    assert report["recovery_index"] == {
        "issue_counts": {"material_gate_failed": 1},
        "platform_counts": {"douyin": 1},
        "auto_recoverable_recommendations": 1,
        "manual_required_recommendations": 0,
    }
    assert "douyin: 缺少一键发布必需物料 -> publication_metadata" in report["failures"]


def test_split_platforms_treats_wechat_channels_as_supported_manual_handoff_platform() -> None:
    stable, x_platforms, manual_handoff, unsupported = autopilot._split_platforms(
        ["douyin", "wechat-channels", "x"]
    )

    assert stable == ["douyin"]
    assert x_platforms == ["x"]
    assert manual_handoff == ["wechat-channels"]
    assert unsupported == []


def test_initial_gate_terminal_outcome_preserves_manual_handoff_success() -> None:
    status, exit_code = autopilot._derive_initial_gate_terminal_outcome(
        material_gate={
            "status": "manual_handoff",
            "failures": [],
        },
        duplicate_history_gate={
            "status": "passed",
            "failures": [],
        },
    )

    assert status == "manual_handoff"
    assert exit_code == 0


def test_initial_gate_terminal_outcome_keeps_duplicate_failure_higher_priority_than_manual_handoff() -> None:
    status, exit_code = autopilot._derive_initial_gate_terminal_outcome(
        material_gate={
            "status": "manual_handoff",
            "failures": [],
        },
        duplicate_history_gate={
            "status": "failed",
            "failures": ["wechat-channels: 命中历史重复发布风险 -> MAXACE [multiple_successful_publications]"],
        },
    )

    assert status == "failed"
    assert exit_code == 2


def test_build_terminal_gate_report_surfaces_duplicate_mitigation_and_verification() -> None:
    report = autopilot._build_terminal_gate_report(
        status="failed",
        platforms=["xiaohongshu"],
        target_profile_ids=[],
        material_gate={
            "status": "passed",
            "failures": [],
            "manual_handoff_targets": [],
            "manual_handoff_ready": False,
        },
        duplicate_history_gate={
            "status": "failed",
            "failures": [
                "xiaohongshu: 命中历史重复发布风险 -> MAXACE [multiple_active_attempts]"
            ],
        },
        run_dir=Path("E:/tmp/autopilot-terminal"),
    )

    assert report["failure_signatures"] == [
        "xiaohongshu: 命中历史重复发布风险 -> MAXACE [multiple_active_attempts]"
    ]
    assert report["suggestions"] == ["检测到重复发布痕迹，请核对去重策略后再发。"]
    assert report["mitigation"]["playbook"] == {
        "duplicate_guard": ["确认同素材未开启重复发布；必要时启用 --allow-republish。"]
    }
    assert report["publication_verification"]["platform_summaries"] == []
    assert report["publication_verification"]["summary_status"] == "failed"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "xiaohongshu",
            "issue": "duplicate_history_gate_failed",
            "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
            "auto_remediable": False,
        }
    ]
    assert report["publication_verification"]["recovery_index"] == {
        "issue_counts": {"duplicate_history_gate_failed": 1},
        "platform_counts": {"xiaohongshu": 1},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 1,
    }


def test_build_terminal_gate_report_surfaces_manual_handoff_playbook() -> None:
    report = autopilot._build_terminal_gate_report(
        status="manual_handoff",
        platforms=["wechat-channels"],
        target_profile_ids=[],
        material_gate={
            "status": "manual_handoff",
            "failures": [],
            "manual_handoff_ready": True,
            "manual_handoff_targets": [
                {
                    "platform": "wechat-channels",
                    "label": "视频号",
                    "login_url": "https://channels.weixin.qq.com/login.html",
                }
            ],
        },
        duplicate_history_gate={
            "status": "passed",
            "failures": [],
        },
        run_dir=Path("E:/tmp/autopilot-terminal"),
    )

    assert report["status"] == "manual_handoff"
    assert report["suggestions"] == ["存在人工接管平台，请打开对应登录页继续处理，不进入自动一键发布。"]
    assert report["mitigation"]["playbook"] == {
        "manual_handoff": ["视频号 -> https://channels.weixin.qq.com/login.html"]
    }
    assert report["publication_verification"]["summary_status"] == "manual_handoff"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]
    assert report["publication_verification"]["recovery_index"] == {
        "issue_counts": {"manual_handoff_required": 1},
        "platform_counts": {"wechat-channels": 1},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 1,
    }


def test_build_terminal_gate_report_surfaces_platform_scope_mismatch_playbook() -> None:
    report = autopilot._build_terminal_gate_report(
        status="failed",
        platforms=["bilibili"],
        target_profile_ids=[],
        material_gate={
            "status": "failed",
            "failures": ["bilibili: 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
            "manual_handoff_ready": False,
            "manual_handoff_targets": [],
        },
        duplicate_history_gate={
            "status": "passed",
            "failures": [],
        },
        run_dir=Path("E:/tmp/autopilot-terminal-scope"),
    )

    assert report["status"] == "failed"
    assert report["suggestions"] == ["检测到目标平台超出本期物料合同覆盖范围，请重生成该平台物料或缩小发布平台范围后再发。"]
    assert report["mitigation"]["playbook"] == {
        "platform_scope": ["重新生成目标平台物料，或仅对当前已覆盖平台执行发布。"]
    }
    assert report["publication_verification"]["summary_status"] == "failed"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "bilibili",
            "issue": "platform_scope_mismatch",
            "operations": ["regenerate_platform_material", "restrict_requested_platforms"],
            "auto_remediable": True,
        }
    ]
    assert report["publication_verification"]["recovery_index"] == {
        "issue_counts": {"platform_scope_mismatch": 1},
        "platform_counts": {"bilibili": 1},
        "auto_recoverable_recommendations": 1,
        "manual_required_recommendations": 0,
    }


def test_extract_verification_issues_trusts_strict_contract_verified_summary() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "passed",
            "publication_verification": {
                "platform_summaries": [
                    {
                        "platform": "douyin",
                        "status": "published",
                        "strict_contract_verified": True,
                        "duplicate_detected": False,
                        "public_url": "",
                        "signature_match": False,
                        "field_match": False,
                        "request_snapshot_plan_match": False,
                        "request_field_mismatch_fields": ["route"],
                    }
                ]
            },
        },
        strict_platforms={"douyin"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == []


def test_extract_verification_issues_ignores_stale_draft_when_strict_contract_verified() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "passed",
            "stale_draft_platforms": ["douyin"],
            "publication_verification": {
                "platform_summaries": [
                    {
                        "platform": "douyin",
                        "status": "published",
                        "strict_contract_verified": True,
                        "duplicate_detected": False,
                    }
                ]
            },
        },
        strict_platforms={"douyin"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == []


def test_extract_verification_issues_skips_missing_summary_when_duplicate_gate_preempts_platform_summary() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "failed",
            "duplicate_history_gate": {
                "status": "failed",
                "platforms": ["douyin"],
            },
            "publication_verification": {
                "platform_summaries": [],
                "recommendations": [
                    {
                        "platform": "douyin",
                        "issue": "duplicate_history_gate_failed",
                        "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
                        "auto_remediable": False,
                    }
                ],
            },
        },
        strict_platforms={"douyin"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == []


def test_extract_verification_issues_skips_missing_summary_for_passed_release_gate_backend_smoke() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "passed",
            "publication_verification": {
                "scope": "release_gate",
                "summary_status": "passed",
                "backend_smoke_status": "passed",
                "platform_summaries": [],
            },
        },
        strict_platforms={"bilibili"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == []


def test_extract_verification_issues_skips_missing_summary_for_media_path_unavailable_precondition() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "failed",
            "publication_verification": {
                "scope": "real_release",
                "summary_status": "failed",
                "platform_summaries": [],
                "recommendations": [
                    {
                        "platform": "bilibili",
                        "issue": "media_path_unavailable",
                        "operations": ["materialize_local_media", "verify_media_path"],
                        "auto_remediable": True,
                    }
                ],
            },
            "failures": ["素材文件不存在: E:/missing.mp4"],
        },
        strict_platforms={"bilibili"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == ["素材文件不存在: E:/missing.mp4"]


def test_build_real_release_cli_failure_report_surfaces_media_path_unavailable() -> None:
    report = autopilot._build_real_release_cli_failure_report(
        platforms=["bilibili"],
        media_path="E:/missing.mp4",
        stdout="素材文件不存在: E:/missing.mp4\n",
        stderr="",
    )

    assert report["status"] == "failed"
    assert report["failures"] == ["素材文件不存在或当前运行态不可读: E:/missing.mp4"]
    assert report["publication_verification"]["summary_status"] == "failed"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "bilibili",
            "issue": "media_path_unavailable",
            "operations": ["materialize_local_media", "verify_media_path"],
            "auto_remediable": True,
        }
    ]


@pytest.mark.asyncio
async def test_run_autopilot_returns_manual_handoff_for_wechat_channels_only_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "manual_handoff",
    "one_click_publish_ready": true,
    "manual_handoff_platforms": [
      {
        "platform": "wechat-channels",
        "label": "视频号",
        "login_url": "https://channels.weixin.qq.com/login.html"
      }
    ],
    "platforms": {
      "wechat-channels": {
        "label": "视频号",
        "one_click_publish_ready": false,
        "manual_handoff_only": true,
        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
        "blocking_reasons": [],
        "missing_fields": ["cover_path", "live_publish_preflight"]
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text("{}", encoding="utf-8")
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)

    args = argparse.Namespace(
        platform=["wechat-channels"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 0
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["status"] == "manual_handoff"
    assert report["manual_handoff_ready"] is True
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert report["manual_handoff_platforms"] == ["wechat-channels"]
    assert report["material_gate"]["manual_handoff_ready"] is True
    assert report["duplicate_history_gate"]["status"] == "passed"
    assert report["suggestions"] == ["存在人工接管平台，请打开对应登录页继续处理，不进入自动一键发布。"]
    assert report["mitigation"]["playbook"] == {
        "manual_handoff": ["视频号 -> https://channels.weixin.qq.com/login.html"]
    }
    assert report["publication_verification"]["summary_status"] == "manual_handoff"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]


@pytest.mark.asyncio
async def test_run_autopilot_keeps_duplicate_failure_higher_priority_than_manual_handoff_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "manual_handoff",
    "one_click_publish_ready": true,
    "manual_handoff_platforms": [
      {
        "platform": "wechat-channels",
        "label": "视频号",
        "login_url": "https://channels.weixin.qq.com/login.html"
      }
    ],
    "platforms": {
      "wechat-channels": {
        "label": "视频号",
        "one_click_publish_ready": false,
        "manual_handoff_only": true,
        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
        "blocking_reasons": [],
        "missing_fields": ["cover_path"]
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text("{}", encoding="utf-8")
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {
            "status": "failed",
            "failures": ["wechat-channels: 命中历史重复发布风险 -> MAXACE [multiple_successful_publications]"],
        }

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)

    args = argparse.Namespace(
        platform=["wechat-channels"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 2
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["manual_handoff_ready"] is True
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert report["manual_handoff_platforms"] == ["wechat-channels"]
    assert report["failure_signatures"] == [
        "wechat-channels: 命中历史重复发布风险 -> MAXACE [multiple_successful_publications]"
    ]
    assert report["suggestions"] == ["检测到重复发布痕迹，请核对去重策略后再发。"]
    assert report["publication_verification"]["summary_status"] == "failed"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "duplicate_history_gate_failed",
            "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
            "auto_remediable": False,
        }
    ]


@pytest.mark.asyncio
async def test_run_autopilot_preserves_manual_handoff_targets_in_mixed_auto_publish_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "manual_handoff",
    "one_click_publish_ready": true,
    "manual_handoff_platforms": [
      {
        "platform": "wechat-channels",
        "label": "视频号",
        "login_url": "https://channels.weixin.qq.com/login.html"
      }
    ],
    "platforms": {
      "douyin": {
        "label": "抖音",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      },
      "wechat-channels": {
        "label": "视频号",
        "one_click_publish_ready": false,
        "manual_handoff_only": true,
        "manual_publish_entry_url": "https://channels.weixin.qq.com/login.html",
        "blocking_reasons": [],
        "missing_fields": ["cover_path"]
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text("{}", encoding="utf-8")
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _run_stage_stub(**kwargs: object) -> dict[str, object]:
        return {
            "status": "passed",
            "summary_failures": [],
            "execution": [],
            "report": {"status": "passed", "platforms": kwargs.get("stage_platforms") or []},
            "mitigation": {"steps": []},
        }

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", lambda **_: (_ for _ in ()).throw(AssertionError("should not call real preflight")))
    monkeypatch.setattr(autopilot, "_run_release_gate", lambda **_: (_ for _ in ()).throw(AssertionError("should not call real release gate")))
    monkeypatch.setattr(autopilot, "_run_real_release", lambda **_: (_ for _ in ()).throw(AssertionError("should not call real release")))

    original_build_stage_packaging = autopilot._build_stage_platform_packaging
    monkeypatch.setattr(autopilot, "_build_stage_platform_packaging", lambda **kwargs: original_build_stage_packaging(**kwargs))

    # Patch the nested stage runner inputs by monkeypatching lower-level phases to harmless passes.
    async def _fake_preflight(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_release_gate(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_real_release(**kwargs: object):
        platforms = kwargs.get("platforms") or []
        return 0, {
            "status": "passed",
            "failures": [],
            "publication_verification": {
                "platform_summaries": [
                    {
                        "platform": platform,
                        "status": "published",
                        "public_url": f"https://example.com/{platform}/published",
                        "signature_match": True,
                        "field_match": True,
                        "request_payload_fields_match": True,
                        "request_payload_plan_match": True,
                        "request_snapshot_plan_match": True,
                        "strict_contract_verified": True,
                        "request_contract_ready": True,
                        "actual_fields": {"title": "ok"},
                        "requested_fields": {"title": "ok"},
                    }
                    for platform in platforms
                ],
                "recommendations": [],
            },
        }, 0

    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", _fake_release_gate)
    monkeypatch.setattr(autopilot, "_run_real_release", _fake_real_release)

    args = argparse.Namespace(
        platform=["douyin", "wechat-channels"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 0
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["manual_handoff_ready"] is True
    assert report["manual_handoff_targets"] == [
        {
            "platform": "wechat-channels",
            "label": "视频号",
            "login_url": "https://channels.weixin.qq.com/login.html",
        }
    ]
    assert report["manual_handoff_platforms"] == ["wechat-channels"]


@pytest.mark.asyncio
async def test_run_autopilot_stage_uses_derived_platform_packaging_when_only_material_json_is_provided(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "one_click_publish_ready": true,
    "platforms": {
      "douyin": {
        "label": "抖音",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platform_scope": {
    "requested_platforms": ["douyin"],
    "covered_platforms": ["douyin"]
  },
  "platforms": {
    "douyin": {
      "title": "真实标题",
      "body": "真实正文"
    }
  }
}""",
        encoding="utf-8",
    )
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")
    captured: dict[str, object] = {}

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _fake_preflight(**kwargs: object):
        captured["preflight_material_json"] = kwargs.get("material_json")
        captured["preflight_platform_packaging"] = kwargs.get("platform_packaging")
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_release_gate(**kwargs: object):
        captured["release_gate_material_json"] = kwargs.get("material_json")
        captured["release_gate_platform_packaging"] = kwargs.get("platform_packaging")
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_real_release(**kwargs: object):
        captured["platform_packaging"] = kwargs.get("platform_packaging")
        platforms = kwargs.get("platforms") or []
        return 0, {
            "status": "passed",
            "failures": [],
            "publication_verification": {
                "platform_summaries": [
                    {
                        "platform": platform,
                        "status": "published",
                        "public_url": f"https://example.com/{platform}/published",
                        "signature_match": True,
                        "field_match": True,
                        "request_payload_fields_match": True,
                        "request_payload_plan_match": True,
                        "request_snapshot_plan_match": True,
                        "strict_contract_verified": True,
                        "receipt_binding_id": f"receipt-binding:{platform}",
                        "receipt_target_unbound": False,
                        "verified_stop_before_final_publish": False,
                        "duplicate_detected": False,
                        "request_contract_ready": True,
                        "actual_fields": {"title": "ok"},
                        "requested_fields": {"title": "ok"},
                    }
                    for platform in platforms
                ],
                "recommendations": [],
            },
        }, 0

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", _fake_release_gate)
    monkeypatch.setattr(autopilot, "_run_real_release", _fake_real_release)

    args = argparse.Namespace(
        platform=["douyin"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging="",
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 0
    assert captured["preflight_material_json"] == str(material_json)
    assert captured["preflight_platform_packaging"] == str(packaging_json)
    assert captured["release_gate_material_json"] == str(material_json)
    assert captured["release_gate_platform_packaging"] == str(packaging_json)
    assert captured["platform_packaging"] == str(packaging_json)
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["publication_verification"]["receipt_binding_ids"] == {
        "douyin": "receipt-binding:douyin"
    }
    assert report["publication_verification"]["strict_contract_verified_platforms"] == ["douyin"]


@pytest.mark.asyncio
async def test_run_autopilot_keeps_passed_real_release_failures_as_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "one_click_publish_ready": true,
    "platforms": {
      "douyin": {
        "label": "抖音",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text("{}", encoding="utf-8")
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _fake_preflight(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_release_gate(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_real_release(**kwargs: object):
        platforms = kwargs.get("platforms") or []
        return 0, {
            "status": "passed",
            "failures": ["douyin 处于发布进行态（processing），等待平台真实回执与链接回读完成后再进入终态判定。"],
                "publication_verification": {
                    "summary_status": "passed",
                    "platform_summaries": [
                        {
                            "platform": platform,
                            "status": "published",
                            "public_url": f"https://example.com/{platform}/published",
                            "signature_match": True,
                            "field_match": True,
                            "request_payload_fields_match": True,
                            "request_payload_plan_match": True,
                            "request_snapshot_plan_match": True,
                            "strict_contract_verified": True,
                            "receipt_binding_id": f"receipt-binding:{platform}",
                            "receipt_target_unbound": False,
                            "verified_stop_before_final_publish": False,
                            "duplicate_detected": False,
                    }
                    for platform in platforms
                ],
                "recommendations": [],
            },
        }, 0

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", _fake_release_gate)
    monkeypatch.setattr(autopilot, "_run_real_release", _fake_real_release)

    args = argparse.Namespace(
        platform=["douyin"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 0
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert report["failure_signatures"] == []
    assert report["warning_signatures"] == [
        "douyin 处于发布进行态（processing），等待平台真实回执与链接回读完成后再进入终态判定。"
    ]
    assert report["publication_verification"]["summary_status"] == "passed"
    assert report["publication_verification"]["strict_contract_verified_platforms"] == ["douyin"]


def test_resolve_material_json_path_prefers_explicit_then_sibling(tmp_path: Path) -> None:
    explicit = tmp_path / "manual-smart-copy.json"
    explicit.write_text("{}", encoding="utf-8")
    packaging = tmp_path / "platform-packaging.json"
    packaging.write_text("{}", encoding="utf-8")
    sibling = tmp_path / "smart-copy.json"
    sibling.write_text("{}", encoding="utf-8")

    assert autopilot._resolve_material_json_path(
        material_json=str(explicit),
        platform_packaging=str(packaging),
    ) == explicit
    assert autopilot._resolve_material_json_path(
        material_json="",
        platform_packaging=str(packaging),
    ) == sibling


def test_load_material_payload_bundle_merges_platform_packaging_with_smart_copy_contract(tmp_path: Path) -> None:
    smart_copy = tmp_path / "smart-copy.json"
    platform_packaging = tmp_path / "platform-packaging.json"
    smart_copy.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "platforms": {
      "douyin": {
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  },
  "platforms": {
    "douyin": {
      "title": "OLD TITLE"
    }
  }
}""",
        encoding="utf-8",
    )
    platform_packaging.write_text(
        """{
  "platform_scope": {
    "requested_platforms": ["douyin"],
    "covered_platforms": ["douyin"]
  },
  "platforms": {
    "douyin": {
      "title": "NEW TITLE",
      "body": "NEW BODY"
    }
  }
}""",
        encoding="utf-8",
    )

    payload, sources = autopilot._load_material_payload_bundle(
        material_json=str(smart_copy),
        platform_packaging=str(platform_packaging),
    )

    assert payload is not None
    assert payload["material_contract"]["platforms"]["douyin"]["one_click_publish_ready"] is True
    assert "material_platforms" not in payload
    assert payload["platforms"]["douyin"]["title"] == "NEW TITLE"
    assert payload["platforms"]["douyin"]["body"] == "NEW BODY"
    assert payload["platform_scope"]["covered_platforms"] == ["douyin"]
    assert sources["smart_copy_path"] == str(smart_copy)
    assert sources["platform_packaging_path"] == str(platform_packaging)


def test_load_material_payload_bundle_preserves_smart_copy_platform_list_when_packaging_overrides_platforms(tmp_path: Path) -> None:
    smart_copy = tmp_path / "smart-copy.json"
    platform_packaging = tmp_path / "platform-packaging.json"
    smart_copy.write_text(
        """{
  "platforms": [
    {
      "key": "bilibili",
      "label": "B站",
      "title": "REAL TITLE",
      "body": "REAL BODY",
      "cover_path": "cover.jpg"
    }
  ]
}""",
        encoding="utf-8",
    )
    platform_packaging.write_text(
        """{
  "platforms": {
    "bilibili": {
      "title": "PACKAGING TITLE",
      "body": "PACKAGING BODY"
    }
  }
}""",
        encoding="utf-8",
    )

    payload, _sources = autopilot._load_material_payload_bundle(
        material_json=str(smart_copy),
        platform_packaging=str(platform_packaging),
    )

    assert payload is not None
    assert payload["platforms"]["bilibili"]["title"] == "PACKAGING TITLE"
    assert payload["material_platforms"] == [
        {
            "key": "bilibili",
            "label": "B站",
            "title": "REAL TITLE",
            "body": "REAL BODY",
            "cover_path": "cover.jpg",
        }
    ]


def test_material_gate_uses_preserved_smart_copy_platforms_when_packaging_overrides_platforms_dict() -> None:
    report = autopilot._material_gate_report(
        material_payload={
            "material_platforms": [
                {
                    "key": "bilibili",
                    "label": "B站",
                    "title": "REAL TITLE",
                    "body": "REAL BODY",
                    "cover_path": "cover.jpg",
                }
            ],
            "platforms": {
                "bilibili": {
                    "title": "PACKAGING TITLE",
                    "body": "PACKAGING BODY",
                }
            },
        },
        target_platforms=["bilibili"],
        source_path="D:/material/smart-copy.json",
    )

    assert report["contract"]["platform_scope"]["covered_platforms"] == ["bilibili"]
    assert report["contract"]["platform_scope"]["missing_requested_platforms"] == []
    assert not any("不在本期物料生成范围内" in item for item in report["failures"])


def test_resolve_base_platform_packaging_path_prefers_explicit_file_then_material_sources(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit-platform-packaging.json"
    explicit.write_text("{}", encoding="utf-8")
    derived = tmp_path / "derived-platform-packaging.json"
    derived.write_text("{}", encoding="utf-8")

    assert autopilot._resolve_base_platform_packaging_path(
        explicit_platform_packaging=str(explicit),
        material_sources={"platform_packaging_path": str(derived)},
    ) == str(explicit)
    assert autopilot._resolve_base_platform_packaging_path(
        explicit_platform_packaging="",
        material_sources={"platform_packaging_path": str(derived)},
    ) == str(derived)
    assert autopilot._resolve_base_platform_packaging_path(
        explicit_platform_packaging=str(tmp_path / "missing.json"),
        material_sources={"platform_packaging_path": str(derived)},
    ) == str(derived)


def test_build_autopilot_verification_digest_preserves_receipt_and_duplicate_evidence() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "platform_summaries": [
                    {
                        "platform": "douyin",
                        "status": "published",
                        "public_url": "https://www.douyin.com/video/123",
                        "strict_contract_verified": True,
                        "duplicate_detected": False,
                        "receipt_binding_id": "receipt-binding:abc123",
                        "receipt_target_unbound": False,
                        "verified_stop_before_final_publish": False,
                    },
                    {
                        "platform": "bilibili",
                        "status": "verified",
                        "public_url": "",
                        "strict_contract_verified": True,
                        "duplicate_detected": False,
                        "receipt_binding_id": "",
                        "receipt_target_unbound": False,
                        "verified_stop_before_final_publish": True,
                    },
                ]
            }
        }
    )

    assert digest["strict_contract_verified_platforms"] == ["bilibili", "douyin"]
    assert digest["verified_stop_before_final_publish_platforms"] == ["bilibili"]
    assert digest["receipt_binding_ids"] == {"douyin": "receipt-binding:abc123"}
    assert digest["public_urls"] == {"douyin": "https://www.douyin.com/video/123"}


def test_build_autopilot_verification_digest_preserves_recommendations_and_recovery_index() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "summary_status": "manual_handoff",
                "platform_summaries": [],
                "recommendations": [
                    {
                        "platform": "wechat-channels",
                        "issue": "manual_handoff_required",
                        "operations": ["open_manual_login", "continue_manual_publish"],
                        "auto_remediable": False,
                    }
                ],
                "recovery_index": {
                    "issue_counts": {"manual_handoff_required": 1},
                    "platform_counts": {"wechat-channels": 1},
                    "auto_recoverable_recommendations": 0,
                    "manual_required_recommendations": 1,
                },
            }
        }
    )

    assert digest["summary_status"] == "manual_handoff"
    assert digest["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]
    assert digest["recovery_index"] == {
        "issue_counts": {"manual_handoff_required": 1},
        "platform_counts": {"wechat-channels": 1},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 1,
    }


def test_build_autopilot_verification_digest_preserves_visual_evidence() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "summary_status": "failed",
                "platform_summaries": [
                    {
                        "platform": "douyin",
                        "status": "needs_human",
                        "strict_contract_verified": False,
                        "duplicate_detected": False,
                        "receipt_binding_id": "",
                        "receipt_target_unbound": False,
                        "verified_stop_before_final_publish": False,
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-prepublish.png",
                            "capture_type": "screenshot",
                            "phase": "pre_publish_page_snapshot",
                        },
                    }
                ],
                "recommendations": [],
                "recovery_index": {},
            }
        }
    )

    assert digest["visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-prepublish.png",
            "capture_type": "screenshot",
            "phase": "pre_publish_page_snapshot",
        }
    }
    assert digest["platform_summaries"][0]["visual_evidence"]["artifact_path"].endswith("douyin-prepublish.png")


def test_build_autopilot_verification_digest_preserves_creator_session_and_probe_visual_evidence() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "summary_status": "failed",
                "platform_summaries": [],
            },
            "live_gate": {
                "creator_sessions": {
                    "douyin": {
                        "platform": "douyin",
                        "status": "auth_required",
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-session.png",
                            "capture_type": "screenshot",
                            "phase": "creator_session_probe",
                        },
                    }
                }
            },
            "probe_inventory": {
                "platforms": {
                    "douyin": {
                        "status": "partial",
                        "visual_evidence": {
                            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-probe.png",
                            "capture_type": "screenshot",
                            "phase": "probe_inventory",
                        },
                    }
                }
            },
        }
    )

    assert digest["creator_session_visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-session.png",
            "capture_type": "screenshot",
            "phase": "creator_session_probe",
        }
    }
    assert digest["probe_inventory_visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-probe.png",
            "capture_type": "screenshot",
            "phase": "probe_inventory",
        }
    }


def test_build_autopilot_verification_digest_preserves_nested_phase_visual_evidence() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "summary_status": "failed",
                "platform_summaries": [],
            },
            "execution": [
                {
                    "phase": "preflight",
                    "report": {
                        "live_gate": {
                            "creator_sessions": {
                                "douyin": {
                                    "platform": "douyin",
                                    "status": "ready",
                                    "visual_evidence": {
                                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-nested-session.png",
                                        "capture_type": "screenshot",
                                        "phase": "creator_session_probe",
                                    },
                                }
                            }
                        },
                        "probe_inventory": {
                            "platforms": {
                                "douyin": {
                                    "status": "partial",
                                    "visual_evidence": {
                                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-nested-probe.png",
                                        "capture_type": "screenshot",
                                        "phase": "probe_inventory",
                                    },
                                }
                            }
                        },
                    },
                }
            ],
        }
    )

    assert digest["creator_session_visual_evidence_by_platform"]["douyin"]["artifact_path"].endswith(
        "douyin-nested-session.png"
    )
    assert digest["probe_inventory_visual_evidence_by_platform"]["douyin"]["artifact_path"].endswith(
        "douyin-nested-probe.png"
    )


def test_coalesce_report_mitigation_derives_preflight_contract_steps_from_packaging_failures() -> None:
    steps, playbook = autopilot._coalesce_report_mitigation(
        {
            "status": "failed",
            "failures": [
                "douyin: 缺少关键参数面 editor_surface",
                "缺少目标平台发布页标签: douyin",
            ],
        },
        phase="preflight",
    )

    assert "检测到发布前物料/门禁阻断，先补齐 packaging、live_publish_preflight 与缺失字段，再重跑 preflight。" in steps
    assert "检测到浏览器会话或发布页标签问题，先恢复 CDP/标签会话后再重跑 preflight。" in steps
    assert playbook["preflight_contract"] == [
        "优先修复 platform-packaging、live_publish_preflight 与缺失物料字段，再重跑 preflight。"
    ]


def test_coalesce_report_mitigation_derives_platform_scope_steps_from_scope_mismatch_failures() -> None:
    steps, playbook = autopilot._coalesce_report_mitigation(
        {
            "failures": ["bilibili: 不在本期物料生成范围内。当前仅覆盖平台 -> douyin, xiaohongshu"],
        },
        phase="preflight",
    )

    assert steps == ["检测到目标平台超出本期物料合同覆盖范围，请重生成该平台物料或缩小发布平台范围后再发。"]
    assert playbook["platform_scope"] == ["重新生成目标平台物料，或仅对当前已覆盖平台执行发布。"]


def test_collect_autopilot_verification_report_merges_stage_reports() -> None:
    report = autopilot._collect_autopilot_verification_report(
        [
            {
                "stage": "stable-primary",
                "report": {
                    "status": "passed",
                    "publication_verification": {
                        "platform_summaries": [
                            {
                                "platform": "douyin",
                                "status": "published",
                                "strict_contract_verified": True,
                                "receipt_binding_id": "receipt-binding:douyin",
                                "duplicate_detected": False,
                            }
                        ],
                        "recommendations": [
                            {"issue": "draft_cleanup", "operations": ["清理草稿"]},
                        ],
                    },
                },
            },
            {
                "stage": "x-post",
                "report": {
                    "status": "passed",
                    "publication_verification": {
                        "platform_summaries": [
                            {
                                "platform": "x",
                                "status": "published",
                                "strict_contract_verified": True,
                                "receipt_binding_id": "receipt-binding:x",
                                "duplicate_detected": False,
                            }
                        ],
                        "recommendations": [
                            {"issue": "draft_cleanup", "operations": ["清理草稿"]},
                        ],
                    },
                },
            },
        ]
    )

    summaries = report["publication_verification"]["platform_summaries"]
    assert [item["platform"] for item in summaries] == ["douyin", "x"]
    assert report["publication_verification"]["recommendations"] == [
        {"issue": "draft_cleanup", "operations": ["清理草稿"]},
    ]


def test_collect_autopilot_verification_report_preserves_release_gate_recommendations_and_recovery_index() -> None:
    report = autopilot._collect_autopilot_verification_report(
        [
            {
                "stage": "stable-primary",
                "report": {
                    "status": "failed",
                    "publication_verification": {
                        "summary_status": "manual_handoff",
                        "platform_summaries": [],
                        "recommendations": [
                            {
                                "platform": "wechat-channels",
                                "issue": "manual_handoff_required",
                                "operations": ["open_manual_login", "continue_manual_publish"],
                                "auto_remediable": False,
                            }
                        ],
                        "recovery_index": {
                            "issue_counts": {"manual_handoff_required": 1},
                            "platform_counts": {"wechat-channels": 1},
                            "auto_recoverable_recommendations": 0,
                            "manual_required_recommendations": 1,
                        },
                    },
                    "failures": ["发布计划要求人工接管，未达到自动一键发布条件"],
                },
            }
        ]
    )

    assert report["status"] == "failed"
    assert report["publication_verification"]["summary_status"] == "manual_handoff"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "wechat-channels",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]
    assert report["publication_verification"]["recovery_index"] == {
        "issue_counts": {"manual_handoff_required": 1},
        "platform_counts": {"wechat-channels": 1},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 1,
    }


def test_collect_autopilot_verification_report_preserves_creator_session_and_probe_visual_evidence() -> None:
    report = autopilot._collect_autopilot_verification_report(
        [
            {
                "stage": "stable-primary",
                "report": {
                    "status": "failed",
                    "probe_inventory": {
                        "platforms": {
                            "douyin": {
                                "status": "partial",
                                "visual_evidence": {
                                    "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-probe.png",
                                    "capture_type": "screenshot",
                                    "phase": "probe_inventory",
                                },
                            }
                        }
                    },
                    "live_gate": {
                        "creator_sessions": {
                            "douyin": {
                                "platform": "douyin",
                                "status": "auth_required",
                                "visual_evidence": {
                                    "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-session.png",
                                    "capture_type": "screenshot",
                                    "phase": "creator_session_probe",
                                },
                            }
                        }
                    },
                    "publication_verification": {
                        "summary_status": "failed",
                        "platform_summaries": [],
                        "recommendations": [],
                    },
                },
            }
        ]
    )

    assert report["publication_verification"]["creator_session_visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-session.png",
            "capture_type": "screenshot",
            "phase": "creator_session_probe",
        }
    }
    assert report["publication_verification"]["probe_inventory_visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-probe.png",
            "capture_type": "screenshot",
            "phase": "probe_inventory",
        }
    }


def test_collect_autopilot_verification_report_fails_closed_when_report_has_failures_without_summary() -> None:
    report = autopilot._collect_autopilot_verification_report(
        [
            {
                "stage": "stable-primary",
                "report": {
                    "failures": ["xiaohongshu: 实际发布页缺少关键参数面 cover, declaration"],
                },
            }
        ]
    )

    assert report["publication_verification"]["summary_status"] == "failed"


def test_build_autopilot_verification_digest_preserves_embedded_probe_inventory_visual_evidence() -> None:
    digest = autopilot._build_autopilot_verification_digest(
        {
            "publication_verification": {
                "summary_status": "failed",
                "platform_summaries": [],
                "probe_inventory_visual_evidence_by_platform": {
                    "douyin": {
                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-embedded-probe.png",
                        "capture_type": "screenshot",
                        "phase": "probe_inventory",
                    }
                },
            }
        }
    )

    assert digest["probe_inventory_visual_evidence_by_platform"] == {
        "douyin": {
            "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-embedded-probe.png",
            "capture_type": "screenshot",
            "phase": "probe_inventory",
        }
    }


def test_collect_autopilot_verification_report_preserves_nested_phase_visual_evidence() -> None:
    report = autopilot._collect_autopilot_verification_report(
        [
            {
                "stage": "stable-primary",
                "execution": [
                    {
                        "report": {
                            "phase": "preflight",
                            "executions": [
                                {
                                    "phase": "preflight",
                                    "report": {
                                        "live_gate": {
                                            "creator_sessions": {
                                                "douyin": {
                                                    "platform": "douyin",
                                                    "status": "ready",
                                                    "visual_evidence": {
                                                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-nested-session.png",
                                                        "capture_type": "screenshot",
                                                        "phase": "creator_session_probe",
                                                    },
                                                }
                                            }
                                        },
                                        "probe_inventory": {
                                            "platforms": {
                                                "douyin": {
                                                    "status": "partial",
                                                    "visual_evidence": {
                                                        "artifact_path": "C:/sample-workspace/RoughCut/artifacts/publication-visual-evidence/douyin-nested-probe.png",
                                                        "capture_type": "screenshot",
                                                        "phase": "probe_inventory",
                                                    },
                                                }
                                            }
                                        }
                                    }
                                }
                            ],
                        },
                    }
                ],
                "report": {
                    "status": "failed",
                    "publication_verification": {
                        "summary_status": "failed",
                        "platform_summaries": [],
                    },
                },
            }
        ]
    )

    assert report["publication_verification"]["creator_session_visual_evidence_by_platform"]["douyin"][
        "artifact_path"
    ].endswith("douyin-nested-session.png")
    assert report["publication_verification"]["probe_inventory_visual_evidence_by_platform"]["douyin"][
        "artifact_path"
    ].endswith("douyin-nested-probe.png")


def test_collect_autopilot_mitigation_merges_stage_playbooks() -> None:
    mitigation = autopilot._collect_autopilot_mitigation(
        [
            {
                "stage": "stable-primary",
                "mitigation": {
                    "steps": ["先补齐 packaging", "清理草稿"],
                    "playbook": {
                        "preflight_contract": ["补齐 live_publish_preflight"],
                    },
                },
            },
            {
                "stage": "x-post",
                "mitigation": {
                    "steps": ["清理草稿", "恢复浏览器标签"],
                    "playbook": {
                        "browser_session": ["确认目标平台发布页标签可用"],
                    },
                },
            },
        ]
    )

    assert mitigation["steps"] == ["先补齐 packaging", "恢复浏览器标签", "清理草稿"]
    assert mitigation["playbook"] == {
        "browser_session": ["确认目标平台发布页标签可用"],
        "preflight_contract": ["补齐 live_publish_preflight"],
    }


@pytest.mark.asyncio
async def test_run_autopilot_verification_digest_merges_all_stage_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "one_click_publish_ready": true,
    "platforms": {
      "douyin": {
        "label": "抖音",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      },
      "x": {
        "label": "X",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platform_scope": {
    "requested_platforms": ["douyin", "x"],
    "covered_platforms": ["douyin", "x"]
  },
  "platforms": {
    "douyin": {
      "title": "抖音标题"
    },
    "x": {
      "title": "X 标题"
    }
  }
}""",
        encoding="utf-8",
    )
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _fake_preflight(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_release_gate(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_real_release(**kwargs: object):
        platforms = kwargs.get("platforms") or []
        summaries = []
        for platform in platforms:
            platform_name = str(platform)
            summaries.append(
                {
                    "platform": platform_name,
                    "status": "published",
                    "public_url": f"https://example.com/{platform_name}/published",
                    "signature_match": True,
                    "field_match": True,
                    "request_payload_fields_match": True,
                    "request_payload_plan_match": True,
                    "request_snapshot_plan_match": True,
                    "strict_contract_verified": True,
                    "receipt_binding_id": f"receipt-binding:{platform_name}",
                    "receipt_target_unbound": False,
                    "verified_stop_before_final_publish": False,
                    "duplicate_detected": False,
                    "request_contract_ready": True,
                    "actual_fields": {"title": "ok"},
                    "requested_fields": {"title": "ok"},
                }
            )
        return 0, {
            "status": "passed",
            "failures": [],
            "publication_verification": {
                "platform_summaries": summaries,
                "recommendations": [],
            },
        }, 0

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", _fake_release_gate)
    monkeypatch.setattr(autopilot, "_run_real_release", _fake_real_release)

    args = argparse.Namespace(
        platform=["douyin", "x"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 0
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["publication_verification"]["strict_contract_verified_platforms"] == ["douyin", "x"]
    assert report["publication_verification"]["receipt_binding_ids"] == {
        "douyin": "receipt-binding:douyin",
        "x": "receipt-binding:x",
    }


@pytest.mark.asyncio
async def test_run_autopilot_preserves_release_gate_recommendations_in_top_level_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "one_click_publish_ready": true,
    "platforms": {
      "douyin": {
        "label": "抖音",
        "status": "passed",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text(
        """{
  "platform_scope": {
    "requested_platforms": ["douyin"],
    "covered_platforms": ["douyin"]
  },
  "platforms": {
    "douyin": {
      "title": "抖音标题"
    }
  }
}""",
        encoding="utf-8",
    )
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _fake_preflight(**_: object):
        return 0, {"status": "passed", "failures": []}, 0

    async def _fake_release_gate(**_: object):
        return 2, {
            "status": "failed",
            "failures": ["发布计划要求人工接管，未达到自动一键发布条件"],
            "publication_verification": {
                "summary_status": "manual_handoff",
                "platform_summaries": [],
                "recommendations": [
                    {
                        "platform": "douyin",
                        "issue": "manual_handoff_required",
                        "operations": ["open_manual_login", "continue_manual_publish"],
                        "auto_remediable": False,
                    }
                ],
                "recovery_index": {
                    "issue_counts": {"manual_handoff_required": 1},
                    "platform_counts": {"douyin": 1},
                    "auto_recoverable_recommendations": 0,
                    "manual_required_recommendations": 1,
                },
            },
        }, 0

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", _fake_release_gate)
    monkeypatch.setattr(
        autopilot,
        "_run_real_release",
        lambda **_: (_ for _ in ()).throw(AssertionError("should not call real release after release_gate failure")),
    )

    args = argparse.Namespace(
        platform=["douyin"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 2
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["publication_verification"]["summary_status"] == "manual_handoff"
    assert report["publication_verification"]["recommendations"] == [
        {
            "platform": "douyin",
            "issue": "manual_handoff_required",
            "operations": ["open_manual_login", "continue_manual_publish"],
            "auto_remediable": False,
        }
    ]
    assert report["publication_verification"]["recovery_index"] == {
        "issue_counts": {"manual_handoff_required": 1},
        "platform_counts": {"douyin": 1},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 1,
    }


@pytest.mark.asyncio
async def test_run_autopilot_preflight_failure_surfaces_mitigation_suggestions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_json = tmp_path / "smart-copy.json"
    material_json.write_text(
        """{
  "material_contract": {
    "status": "passed",
    "one_click_publish_ready": true,
    "platforms": {
      "douyin": {
        "label": "抖音",
        "one_click_publish_ready": true,
        "blocking_reasons": [],
        "missing_fields": []
      }
    }
  }
}""",
        encoding="utf-8",
    )
    packaging_json = tmp_path / "platform-packaging.json"
    packaging_json.write_text("{}", encoding="utf-8")
    media_path = tmp_path / "media.mp4"
    media_path.write_bytes(b"fake")

    async def _duplicate_gate(**_: object) -> dict[str, object]:
        return {"status": "passed", "failures": []}

    async def _fake_preflight(**_: object):
        return 5, {
            "status": "failed",
            "failures": ["douyin: 缺少关键参数面 editor_surface"],
        }, 0

    monkeypatch.setattr(autopilot, "_duplicate_history_gate_report", _duplicate_gate)
    monkeypatch.setattr(autopilot, "_run_preflight", _fake_preflight)
    monkeypatch.setattr(autopilot, "_run_release_gate", lambda **_: (_ for _ in ()).throw(AssertionError("should not call release gate after preflight failure")))
    monkeypatch.setattr(autopilot, "_run_real_release", lambda **_: (_ for _ in ()).throw(AssertionError("should not call real release after preflight failure")))

    args = argparse.Namespace(
        platform=["douyin"],
        target_profile_id=[],
        allow_anonymous_profile=True,
        output=str(tmp_path / "autopilot-output"),
        expected_status="published,scheduled_pending",
        platform_adapter=[],
        platform_execution_mode=[],
        material_json=str(material_json),
        platform_packaging=str(packaging_json),
        media_path=str(media_path),
        allow_republish=False,
        x_mode="link_share",
        browser_agent_base_url="",
        auth_token="",
        cdp_url="",
        timeout=12,
        poll_interval=5,
        max_wait_seconds=30,
        require_tabs=False,
        auto_recover=False,
        auto_recover_codes="",
        auto_recover_max_rounds=1,
        retry_cycles=1,
        retry_interval=1,
        auto_retry=False,
        skip_release_gate=False,
        skip_backend_smoke=False,
        x_share_link="",
        x_share_url="",
    )

    exit_code = await autopilot._run_autopilot(args)

    assert exit_code == 2
    report_paths = list((tmp_path / "autopilot-output").glob("run-*/autopilot_report.json"))
    assert len(report_paths) == 1
    report = __import__("json").loads(report_paths[0].read_text(encoding="utf-8"))
    assert report["status"] == "failed"
    assert report["suggestions"] == [
        "检测到发布前物料/门禁阻断，先补齐 packaging、live_publish_preflight 与缺失字段，再重跑 preflight。"
    ]
    assert report["mitigation"]["playbook"] == {
        "preflight_contract": [
            "优先修复 platform-packaging、live_publish_preflight 与缺失物料字段，再重跑 preflight。"
        ]
    }
    assert report["execution"][0]["mitigation"]["steps"] == report["suggestions"]


@pytest.mark.asyncio
async def test_duplicate_history_gate_blocks_same_media_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_audit_duplicate_publications(**_: object) -> dict[str, object]:
        return {
            "groups": [
                {
                    "platform": "douyin",
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "reasons": ["multiple_successful_publications", "multiple_schedule_variants_same_live_content"],
                }
            ]
        }

    monkeypatch.setattr(autopilot, "audit_duplicate_publications", _fake_audit_duplicate_publications)
    report = await autopilot._duplicate_history_gate_report(
        material_payload={
            "platforms": [
                {
                    "key": "douyin",
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "body": "正文",
                    "tags": ["EDC折刀"],
                }
            ]
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        allow_republish=False,
    )

    assert report["status"] == "failed"
    assert any("multiple_successful_publications" in item for item in report["failures"])


@pytest.mark.asyncio
async def test_duplicate_history_gate_warns_when_allow_republish(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_audit_duplicate_publications(**_: object) -> dict[str, object]:
        return {
            "groups": [
                {
                    "platform": "douyin",
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "reasons": ["multiple_active_attempts"],
                }
            ]
        }

    monkeypatch.setattr(autopilot, "audit_duplicate_publications", _fake_audit_duplicate_publications)
    report = await autopilot._duplicate_history_gate_report(
        material_payload={
            "platforms": [
                {
                    "key": "douyin",
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "body": "正文",
                    "tags": ["EDC折刀"],
                }
            ]
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        allow_republish=True,
    )

    assert report["status"] == "warn"
    assert "warning" in report


@pytest.mark.asyncio
async def test_duplicate_history_gate_relaxes_profile_filter_when_history_profile_marker_drifts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit_duplicate_publications(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        if len(calls) == 1:
            return {"groups": []}
        return {
            "groups": [
                {
                    "platform": "douyin",
                    "title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "reasons": ["multiple_successful_publications"],
                }
            ]
        }

    monkeypatch.setattr(autopilot, "audit_duplicate_publications", _fake_audit_duplicate_publications)
    report = await autopilot._duplicate_history_gate_report(
        material_payload={
            "platforms": [
                {
                    "key": "douyin",
                    "primary_title": "两款同时开！美杜莎4顶配次顶配差别出来了",
                    "body": "正文",
                    "tags": ["EDC折刀"],
                }
            ]
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["douyin"],
        target_profile_ids=["browser-profile:chrome:demo-profile-a"],
        allow_republish=False,
    )

    assert len(calls) == 2
    assert calls[0]["browser_profile_ids"] == ["browser-profile:chrome:demo-profile-a"]
    assert calls[1]["browser_profile_ids"] == []
    assert report["status"] == "failed"
    assert report["profile_filter_relaxed"] is True


@pytest.mark.asyncio
async def test_duplicate_history_gate_does_not_narrow_to_material_creator_profile_when_target_profile_is_anonymous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_audit_duplicate_publications(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"groups": []}

    monkeypatch.setattr(autopilot, "audit_duplicate_publications", _fake_audit_duplicate_publications)
    report = await autopilot._duplicate_history_gate_report(
        material_payload={
            "creator_profile_id": "creator-from-material",
            "publication_context": {
                "creator_profile_id": "creator-from-material",
            },
            "platforms": [
                {
                    "key": "xiaohongshu",
                    "primary_title": "新到的美杜莎4｜两款配置到手，差别一眼就",
                    "body": "正文",
                    "tags": [],
                }
            ],
        },
        media_path="E:/media/maxace4.mp4",
        target_platforms=["xiaohongshu"],
        target_profile_ids=[],
        allow_republish=False,
    )

    assert calls[0]["creator_profile_ids"] == []
    assert calls[0]["browser_profile_ids"] == []
    assert report["status"] == "passed"
