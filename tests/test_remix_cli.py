from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

import scripts.build_script_footage_remix_samples as script_footage_samples
from roughcut.cli import cli


def test_remix_cli_exposes_only_generic_script_footage_command() -> None:
    runner = CliRunner()

    help_result = runner.invoke(cli, ["remix", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "script-footage" in help_result.output
    assert "sample_show" not in help_result.output.lower()

    legacy_result = runner.invoke(cli, ["remix", "sample_show-samples"])
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
            r"C:\sample-remix-source",
            "--episodes",
            "1,2,3",
            "--output-dir",
            "output/example-remix-cli-test",
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
    assert r"C:\sample-remix-source" in command
    assert "--episodes" in command
    assert "1,2,3" in command
    assert "--output-dir" in command
    assert any(str(item).replace("\\", "/").endswith("output/example-remix-cli-test") for item in command)
    assert "--tts-provider" in command
    assert "moss_tts_local" in command
    assert "--qwen3-asr-base" in command
    assert "http://127.0.0.1:30230" in command
    assert "--creator-profile" in command
    assert "demo_creator" not in command
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
            r"C:\sample-remix-source",
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
    assert "demo_creator" not in command
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
            r"C:\sample-remix-source",
            "--force-tts",
        ],
    )

    assert result.exit_code == 0, result.output
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--force-tts" in command


def test_remix_script_footage_cli_forwards_production_manifest(monkeypatch, tmp_path) -> None:
    calls: list[dict[str, object]] = []
    manifest_path = tmp_path / "example_remix_pending.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_root": r"C:\sample-remix-source",
                "creator_profile": "demo_creator",
                "items": [{"status": "pending", "season": 2, "episode": 2}],
            }
        ),
        encoding="utf-8",
    )

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
                str(manifest_path),
                "--task-status",
                "pending",
            ],
        )

    assert result.exit_code == 0, result.output
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--production-manifest" in command
    assert str(manifest_path) in [str(item) for item in command]
    assert "--source-root" in command
    assert r"C:\sample-remix-source" in command
    assert "--creator-profile" in command
    assert "demo_creator" in command
    assert "--task-status" in command
    assert "pending" in command


def test_script_footage_loader_accepts_generic_script_filename(tmp_path) -> None:
    script_path = tmp_path / "示例动画第二季新风格育儿文案_第1-5集.md"
    script_path.write_text(
        "\n".join(
            [
                "## 第5集《理发师》",
                "",
                "**育儿问题：孩子说话慢，总被别人抢话怎么办？**",
                "",
                "今天借这集《理发师》，跟大家聊聊。",
            ]
        ),
        encoding="utf-8",
    )

    scripts = script_footage_samples.load_episode_scripts(tmp_path)

    assert 5 in scripts
    assert scripts[5].title == "理发师"
    assert scripts[5].question == "育儿问题：孩子说话慢，总被别人抢话怎么办？"


def test_script_footage_video_finder_accepts_generic_video_filename(tmp_path) -> None:
    season_dir = tmp_path / "中文配音 (中文字幕)" / "第二季 (Season 2)"
    season_dir.mkdir(parents=True)
    video_path = season_dir / "SampleShow.S02E05.1080p.bilibili.WEBRip.2.0.x264-APEXFORCE.mp4"
    video_path.write_bytes(b"video")

    assert script_footage_samples.find_episode_video(tmp_path, 5) == video_path

