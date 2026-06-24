from __future__ import annotations

from pathlib import Path

import httpx

from scripts import check_strategy_fixture_runtime_preflight as preflight


class _FakeClient:
    def __init__(
        self,
        *,
        health_status: int = 200,
        transcribe_status: int = 200,
        transcribe_json: object | None = None,
        **kwargs,
    ):
        self.health_status = health_status
        self.transcribe_status = transcribe_status
        self.transcribe_json = {"text": ""} if transcribe_json is None else transcribe_json

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def get(self, url: str) -> httpx.Response:
        return httpx.Response(self.health_status, json={"status": "ok" if self.health_status == 200 else "failed"})

    def post(self, url: str, *, files, data) -> httpx.Response:
        if self.transcribe_status >= 400:
            return httpx.Response(self.transcribe_status, text="internal server error")
        return httpx.Response(self.transcribe_status, json=self.transcribe_json)


def test_strategy_fixture_runtime_preflight_accepts_health_and_transcribe(tmp_path: Path) -> None:
    sample = tmp_path / "probe.wav"
    preflight.write_asr_probe_wav(sample)

    result = preflight.check_strategy_fixture_runtime_preflight(
        base_url="http://127.0.0.1:30230",
        health_path="/health",
        transcribe_path="/transcribe",
        model_name="qwen3-asr-1.7b-forced-aligner",
        timeout_sec=1.0,
        sample_audio=sample,
        client_factory=_FakeClient,
    )

    assert result["ok"] is True
    assert result["health"]["ok"] is True
    assert result["transcribe"]["ok"] is True
    assert result["blocking_reasons"] == []


def test_strategy_fixture_runtime_preflight_reports_transcribe_http_failure(tmp_path: Path) -> None:
    sample = tmp_path / "probe.wav"
    preflight.write_asr_probe_wav(sample)

    def client_factory(**kwargs):
        return _FakeClient(transcribe_status=500, **kwargs)

    result = preflight.check_strategy_fixture_runtime_preflight(
        base_url="http://127.0.0.1:30230",
        health_path="/health",
        transcribe_path="/transcribe",
        model_name="qwen3-asr-1.7b-forced-aligner",
        timeout_sec=1.0,
        sample_audio=sample,
        client_factory=client_factory,
    )

    assert result["ok"] is False
    assert result["health"]["ok"] is True
    assert result["transcribe"]["status_code"] == 500
    assert result["blocking_reasons"] == ["local_asr_transcribe_http_500"]


def test_strategy_fixture_runtime_preflight_writes_generated_sample() -> None:
    result = preflight.check_strategy_fixture_runtime_preflight(
        base_url="http://127.0.0.1:30230",
        health_path="/health",
        transcribe_path="/transcribe",
        model_name="qwen3-asr-1.7b-forced-aligner",
        timeout_sec=1.0,
        client_factory=_FakeClient,
    )

    assert result["ok"] is True
    assert result["generated_sample"] is True


def test_strategy_fixture_runtime_preflight_can_keep_generated_sample(tmp_path: Path) -> None:
    sample = tmp_path / "kept-probe.wav"

    result = preflight.check_strategy_fixture_runtime_preflight(
        base_url="http://127.0.0.1:30230",
        health_path="/health",
        transcribe_path="/transcribe",
        model_name="qwen3-asr-1.7b-forced-aligner",
        timeout_sec=1.0,
        generated_sample_audio=sample,
        client_factory=_FakeClient,
    )

    assert result["ok"] is True
    assert result["generated_sample"] is True
    assert result["sample_audio"] == str(sample)
    assert sample.exists()
