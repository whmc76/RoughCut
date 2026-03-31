from __future__ import annotations

from pathlib import Path


def test_automation_compose_does_not_run_telegram_agent_container():
    compose_text = Path("docker-compose.automation.yml").read_text(encoding="utf-8")

    assert "telegram-agent:" not in compose_text


def test_start_script_manages_host_telegram_agent_for_full_mode():
    script_text = Path("start_roughcut.ps1").read_text(encoding="utf-8")

    assert "ensure-roughcut-telegram-agent.ps1" in script_text
    assert "stop-roughcut-telegram-agent.ps1" in script_text


def test_full_refresh_session_restarts_host_telegram_agent():
    script_text = Path("scripts/run-roughcut-docker-refresh-session.ps1").read_text(encoding="utf-8")

    assert "ensure-roughcut-telegram-agent.ps1" in script_text
    assert "stop-roughcut-telegram-agent.ps1" in script_text
