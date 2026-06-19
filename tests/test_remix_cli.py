from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from roughcut.cli import cli


def test_remix_cli_exposes_only_generic_script_footage_command() -> None:
    runner = CliRunner()

    help_result = runner.invoke(cli, ["remix", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "script-footage" in help_result.output
    assert "bluey" not in help_result.output.lower()

    legacy_result = runner.invoke(cli, ["remix", "bluey-samples"])
    assert legacy_result.exit_code != 0
    assert "No such command" in legacy_result.output


def test_remix_script_footage_cli_invokes_formal_sample_builder(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, *, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("roughcut.cli.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli,
        [
            "remix",
            "script-footage",
            "--source-root",
            r"F:\布鲁伊育儿节目",
            "--episodes",
            "1,2,3",
            "--output-dir",
            "output/bluey-remix-cli-test",
            "--qwen3-asr-base",
            "http://127.0.0.1:30230",
            "--force",
        ],
    )

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert command[0] == sys.executable
    assert command[1].endswith(str(Path("scripts") / "build_script_footage_remix_samples.py"))
    assert "--source-root" in command
    assert r"F:\布鲁伊育儿节目" in command
    assert "--episodes" in command
    assert "1,2,3" in command
    assert "--output-dir" in command
    assert any(str(item).replace("\\", "/").endswith("output/bluey-remix-cli-test") for item in command)
    assert "--tts-provider" in command
    assert "moss_tts_local" in command
    assert "--qwen3-asr-base" in command
    assert "http://127.0.0.1:30230" in command
    assert "--creator-profile" in command
    assert "jenny_baby" not in command
    assert "--force" in command
    assert calls[0]["check"] is False


def test_remix_script_footage_cli_defaults_to_full_script_output_and_no_condense_flags(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, *, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("roughcut.cli.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli,
        [
            "remix",
            "script-footage",
            "--source-root",
            r"F:\布鲁伊育儿节目",
        ],
    )

    assert result.exit_code == 0, result.output
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--episodes" in command
    assert "1" in command
    assert "--output-dir" in command
    assert any(
        str(item).replace("\\", "/").endswith("output/script-footage-remix-full-script-samples")
        for item in command
    )
    assert "--creator-profile" in command
    assert "jenny_baby" not in command
    assert "--condense-script" not in command
    assert "--max-script-chars" not in command
    assert "--final-target-duration-sec" not in command


def test_remix_script_footage_cli_forwards_force_tts(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, *, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("roughcut.cli.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli,
        [
            "remix",
            "script-footage",
            "--source-root",
            r"F:\布鲁伊育儿节目",
            "--force-tts",
        ],
    )

    assert result.exit_code == 0, result.output
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--force-tts" in command


def test_remix_script_footage_cli_forwards_production_manifest(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(command, *, cwd, check):
        calls.append({"command": command, "cwd": cwd, "check": check})
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("roughcut.cli.subprocess.run", fake_run)

    result = CliRunner().invoke(
        cli,
        [
            "remix",
            "script-footage",
            "--production-manifest",
            "data/remix_production_tasks/jenny_baby_bluey_pending.json",
            "--task-status",
            "pending",
        ],
    )

    assert result.exit_code == 0, result.output
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--production-manifest" in command
    assert "data/remix_production_tasks/jenny_baby_bluey_pending.json" in [
        str(item).replace("\\", "/") for item in command
    ]
    assert "--source-root" in command
    assert r"F:\布鲁伊育儿节目" in command
    assert "--creator-profile" in command
    assert "jenny_baby" in command
    assert "--task-status" in command
    assert "pending" in command

