from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from roughcut.host import codex_imagegen_runner as runner


def test_run_single_codex_imagegen_harvests_generated_bitmap_from_stdout_session(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"generated")
    output = tmp_path / "output.png"
    calls = {"resolve": 0}

    monkeypatch.setattr(
        runner,
        "run_codex_exec",
        lambda payload: {  # noqa: ARG005
            "stdout": "session id: session-123",
            "stderr": "",
            "excerpt": "",
        },
    )

    def fake_resolve_generated_image(*, session_id: str, started_at: float) -> Path | None:  # noqa: ARG001
        calls["resolve"] += 1
        assert session_id == "session-123"
        return generated

    monkeypatch.setattr(runner, "_resolve_generated_image", fake_resolve_generated_image)

    result = runner._run_single_codex_imagegen(
        command="codex",
        repo_root=repo_root,
        reference_image_paths=[source],
        prompt="生成封面",
        output_path=output,
        model_name="gpt-5.4-mini",
        sandbox_mode="danger-full-access",
        timeout_sec=60,
        started_at=runner.time.time(),
    )

    assert output.read_bytes() == b"generated"
    assert result["timed_out"] is False
    assert Path(result["result_path"]) == generated
    assert calls["resolve"] == 1


def test_run_single_codex_imagegen_harvests_generated_bitmap_without_session_id(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"generated")
    output = tmp_path / "output.png"
    calls = {"resolve": 0}

    monkeypatch.setattr(
        runner,
        "run_codex_exec",
        lambda payload: {  # noqa: ARG005
            "stdout": "",
            "stderr": "",
            "excerpt": "",
        },
    )

    def fake_resolve_generated_image(*, session_id: str, started_at: float) -> Path | None:  # noqa: ARG001
        calls["resolve"] += 1
        assert session_id == ""
        return generated

    monkeypatch.setattr(runner, "_resolve_generated_image", fake_resolve_generated_image)

    result = runner._run_single_codex_imagegen(
        command="codex",
        repo_root=repo_root,
        reference_image_paths=[source],
        prompt="生成封面",
        output_path=output,
        model_name="gpt-5.4-mini",
        sandbox_mode="danger-full-access",
        timeout_sec=60,
        started_at=runner.time.time(),
    )

    assert output.read_bytes() == b"generated"
    assert result["timed_out"] is False
    assert Path(result["result_path"]) == generated
    assert calls["resolve"] == 1


def test_build_codex_imagegen_prompt_requires_final_bitmap_cover_with_integrated_typography() -> None:
    prompt = runner._build_codex_imagegen_prompt("请直接生成最终封面", output_path=Path("C:/tmp/final-cover.png"))

    assert "The bitmap itself must be the final publishable cover" in prompt
    assert "Render the requested brand line, main title, subtitle, and hook text directly in the bitmap" in prompt
    assert "The final bitmap must be written exactly to this path before you finish" in prompt
    assert "Keep the bitmap text-free" not in prompt
    assert "local post-overlay" not in prompt


def test_build_codex_imagegen_prompt_mentions_reference_pack_for_multiple_images() -> None:
    prompt = runner._build_codex_imagegen_prompt(
        "请直接生成最终封面",
        output_path=Path("C:/tmp/final-cover.png"),
        reference_count=4,
    )

    assert "Use all attached images as a single same-product multi-angle reference pack." in prompt
    assert "combine them to preserve the same real product identity" in prompt
    assert "same real product or the same real comparison pair from different angles" in prompt
    assert "majority hero view across the pack" in prompt
    assert "Do not reinterpret a minority side-view reference" in prompt


def test_run_single_codex_imagegen_accepts_direct_output_path_written_by_codex(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "output.png"
    output.write_bytes(b"direct-render")
    monkeypatch.setattr(
        runner,
        "run_codex_exec",
        lambda payload: {  # noqa: ARG005
            "stdout": "",
            "stderr": "",
            "excerpt": "",
        },
    )

    result = runner._run_single_codex_imagegen(
        command="codex",
        repo_root=repo_root,
        reference_image_paths=[source],
        prompt="生成封面",
        output_path=output,
        model_name="gpt-5.4-mini",
        sandbox_mode="danger-full-access",
        timeout_sec=60,
        started_at=runner.time.time(),
    )

    assert output.read_bytes() == b"direct-render"
    assert Path(result["result_path"]) == output


def test_run_single_codex_imagegen_does_not_treat_stale_existing_output_as_generated(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "output.png"
    output.write_bytes(b"fallback")
    started_at = runner.time.time() + 5

    monkeypatch.setattr(
        runner,
        "run_codex_exec",
        lambda payload: {  # noqa: ARG005
            "stdout": "",
            "stderr": "",
            "excerpt": "",
        },
    )
    monkeypatch.setattr(runner, "_resolve_generated_image", lambda **kwargs: None)

    with pytest.raises(RuntimeError):
        runner._run_single_codex_imagegen(
            command="codex",
            repo_root=repo_root,
            reference_image_paths=[source],
            prompt="生成封面",
            output_path=output,
            model_name="gpt-5.4-mini",
            sandbox_mode="danger-full-access",
            timeout_sec=60,
            started_at=started_at,
        )


def test_run_single_codex_imagegen_does_not_accept_stale_output_path_echoed_in_stdout(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "output.jpg"
    output.write_bytes(b"fallback")

    def fake_run_codex_exec(_payload):  # noqa: ANN001
        return {
            "stdout": f'Generated file: "{output}"',
            "stderr": "",
            "excerpt": f'Generated file: "{output}"',
        }

    monkeypatch.setattr(runner, "run_codex_exec", fake_run_codex_exec)
    monkeypatch.setattr(runner, "_resolve_generated_image", lambda **_kwargs: None)
    started_at = runner.time.time() + 5

    with pytest.raises(RuntimeError):
        runner._run_single_codex_imagegen(
            command="codex",
            repo_root=repo_root,
            reference_image_paths=[source],
            prompt="生成封面",
            output_path=output,
            model_name="gpt-5.4-mini",
            sandbox_mode="danger-full-access",
            timeout_sec=60,
            started_at=started_at,
        )


def test_extract_generated_image_path_from_text_prefers_existing_latest_file(tmp_path) -> None:
    older = tmp_path / "older.png"
    latest = tmp_path / "final-cover.png"
    older.write_bytes(b"older")
    time.sleep(1.1)
    latest.write_bytes(b"latest")

    text = f'command output\n{older}\n"{latest}"\n'

    resolved = runner._extract_generated_image_path_from_text(text)

    assert resolved == latest.resolve()


def test_extract_generated_image_path_from_text_respects_allowed_roots(tmp_path) -> None:
    allowed_root = tmp_path / "allowed"
    allowed_root.mkdir()
    outsider_root = tmp_path / "outsider"
    outsider_root.mkdir()
    allowed = allowed_root / "final-cover.png"
    outsider = outsider_root / "other.png"
    outsider.write_bytes(b"outsider")
    time.sleep(1.1)
    allowed.write_bytes(b"allowed")

    text = f"{outsider}\n{allowed}\n"

    resolved = runner._extract_generated_image_path_from_text(
        text,
        allowed_roots=[allowed_root],
    )

    assert resolved == allowed.resolve()


def test_fulfill_codex_imagegen_request_persists_session_metadata(monkeypatch, tmp_path) -> None:
    request_path = tmp_path / "cover.codex-imagegen.json"
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "output.jpg"
    payload = {
        "status": "pending_codex_imagegen",
        "source_image_path": str(source),
        "reference_image_paths": [str(source)],
        "output_path": str(output),
        "prompt": "生成封面",
        "codex_runner": {"model": "gpt-5.4-mini"},
    }
    request_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def fake_run_single_codex_imagegen(**kwargs):  # noqa: ANN003
        Path(kwargs["output_path"]).write_bytes(b"generated")
        return {
            "session_id": "session-xyz",
            "result_path": str(source),
            "timed_out": False,
        }

    monkeypatch.setattr(runner, "_run_single_codex_imagegen", fake_run_single_codex_imagegen)
    monkeypatch.setattr(runner, "_resolve_codex_command_candidates", lambda _name: ["codex"])

    result = runner.fulfill_codex_imagegen_request(
        request_path=request_path,
        repo_root=tmp_path,
        timeout_sec=60,
        model="gpt-5.4-mini",
    )

    updated = json.loads(request_path.read_text(encoding="utf-8"))
    assert result["session_id"] == "session-xyz"
    assert updated["status"] == "completed"
    assert updated["session_id"] == "session-xyz"
    assert updated["auto_completion_error"] == ""
    assert updated["last_attempted_at"]
    assert updated["generated_by_codex_bridge"] is True


def test_run_single_codex_imagegen_passes_multiple_reference_images(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    extra = tmp_path / "extra.jpg"
    extra.write_bytes(b"extra")
    output = tmp_path / "output.png"
    observed: dict[str, object] = {}

    def fake_run_codex_exec(payload):  # noqa: ANN001
        observed["images"] = payload["images"]
        output.write_bytes(b"direct-render")
        return {"stdout": "", "stderr": "", "excerpt": ""}

    monkeypatch.setattr(runner, "run_codex_exec", fake_run_codex_exec)

    result = runner._run_single_codex_imagegen(
        command="codex",
        repo_root=repo_root,
        reference_image_paths=[source, extra],
        prompt="生成封面",
        output_path=output,
        model_name="gpt-5.4-mini",
        sandbox_mode="danger-full-access",
        timeout_sec=60,
        started_at=runner.time.time(),
    )

    assert observed["images"] == [str(source), str(extra)]
    assert Path(result["result_path"]) == output


def test_resolve_reference_image_paths_prefers_explicit_reference_pack(tmp_path) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    extra = tmp_path / "extra.jpg"
    extra.write_bytes(b"extra")

    resolved = runner._resolve_reference_image_paths(
        {
            "source_image_path": str(source),
            "reference_image_paths": [str(source), str(extra)],
        }
    )

    assert resolved == [source.resolve(), extra.resolve()]
