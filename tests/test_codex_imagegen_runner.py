from __future__ import annotations

from pathlib import Path

from roughcut.host import codex_imagegen_runner as runner


class _FakePipe:
    def __init__(self) -> None:
        self.payload = b""

    def write(self, data: bytes) -> int:
        self.payload += data
        return len(data)

    def close(self) -> None:
        return None

    def read(self) -> bytes:
        return b""


class _FakeProcess:
    def __init__(self) -> None:
        self.stdin = _FakePipe()
        self.stdout = _FakePipe()
        self.stderr = _FakePipe()
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def communicate(self, input=None, timeout=None):  # noqa: ANN001
        self.returncode = 0
        return b"", b""


def test_run_single_codex_imagegen_harvests_generated_bitmap_before_process_exit(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    generated = tmp_path / "generated.png"
    generated.write_bytes(b"generated")
    output = tmp_path / "output.png"
    fake_process = _FakeProcess()
    calls = {"resolve": 0, "terminated": 0}

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *args, **kwargs: fake_process)
    session_reads = {"count": 0}

    def fake_read_codex_session_id(*_args, fallback: str = "", **_kwargs) -> str:  # noqa: ANN001
        session_reads["count"] += 1
        if session_reads["count"] >= 2:
            return "session-123"
        return fallback

    monkeypatch.setattr(runner, "_read_codex_session_id", fake_read_codex_session_id)

    def fake_resolve_generated_image(*, session_id: str, started_at: float) -> Path | None:  # noqa: ARG001
        calls["resolve"] += 1
        assert session_id == "session-123"
        if calls["resolve"] >= 2:
            return generated
        return None

    monkeypatch.setattr(runner, "_resolve_generated_image", fake_resolve_generated_image)

    def fake_terminate(process) -> None:  # noqa: ANN001
        calls["terminated"] += 1
        process.returncode = 0

    monkeypatch.setattr(runner, "_terminate_process_tree", fake_terminate)
    monkeypatch.setattr(runner.time, "sleep", lambda _sec: None)

    result = runner._run_single_codex_imagegen(
        command="codex",
        repo_root=repo_root,
        source_image_path=source,
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
    assert calls["terminated"] == 1


def test_build_codex_imagegen_prompt_requires_final_bitmap_cover_with_integrated_typography() -> None:
    prompt = runner._build_codex_imagegen_prompt("请直接生成最终封面")

    assert "The bitmap itself must be the final publishable cover" in prompt
    assert "Render the requested brand line, main title, subtitle, and hook text directly in the bitmap" in prompt
    assert "Keep the bitmap text-free" not in prompt
    assert "local post-overlay" not in prompt
