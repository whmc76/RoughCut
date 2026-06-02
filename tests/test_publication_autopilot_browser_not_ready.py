from __future__ import annotations

from scripts import run_publication_autopilot as autopilot


def test_extract_verification_issues_skips_missing_summary_for_global_browser_agent_not_ready_precondition() -> None:
    issues = autopilot._extract_verification_issues(
        {
            "status": "failed",
            "publication_verification": {
                "scope": "real_release",
                "summary_status": "failed",
                "note": "preflight_failed",
                "platform_summaries": [],
                "recommendations": [
                    {
                        "platform": "",
                        "issue": "browser_agent_not_ready",
                        "operations": ["restore_browser_agent", "rerun_preflight"],
                        "auto_remediable": True,
                    }
                ],
            },
            "failures": ["browser-agent delta: browser_agent_creator_session_auth_required"],
        },
        strict_platforms={"bilibili", "xiaohongshu", "youtube"},
        expected_statuses={"published", "scheduled_pending"},
    )

    assert issues == ["browser-agent delta: browser_agent_creator_session_auth_required"]
