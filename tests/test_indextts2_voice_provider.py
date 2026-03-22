from __future__ import annotations

import base64
from pathlib import Path

import pytest

from roughcut.providers.voice.indextts2 import IndexTTS2VoiceProvider


def test_build_dubbing_request_infers_emotion_controls(monkeypatch: pytest.MonkeyPatch):
    import roughcut.providers.voice.indextts2 as provider_mod

    class Settings:
        voice_clone_api_base_url = "http://127.0.0.1:49204"

    monkeypatch.setattr(provider_mod, "get_settings", lambda: Settings())

    provider = IndexTTS2VoiceProvider()
    request = provider.build_dubbing_request(
        job_id="job-1",
        segments=[
            {
                "segment_id": "hook",
                "rewritten_text": "终于等到这个功能上线了。",
                "purpose": "hook",
                "target_duration_sec": 3.2,
            }
        ],
    )

    assert request["provider"] == "indextts2"
    assert request["speech_endpoint"] == "http://127.0.0.1:49204/v1/audio/speech"
    assert request["segments"][0]["emotion_text"]
    assert request["segments"][0]["emotion_strength"] > 0.3
    assert request["segments"][0]["use_speed"] is True
    assert request["segments"][0]["target_dur"] == 3.2
    assert request["segments"][0]["emo_text_weight"] == 1.0


def test_build_dubbing_request_respects_indextts2_speed_overrides(monkeypatch: pytest.MonkeyPatch):
    import roughcut.providers.voice.indextts2 as provider_mod

    class Settings:
        voice_clone_api_base_url = "http://127.0.0.1:49204"

    monkeypatch.setattr(provider_mod, "get_settings", lambda: Settings())

    provider = IndexTTS2VoiceProvider()
    request = provider.build_dubbing_request(
        job_id="job-1",
        segments=[
            {
                "segment_id": "bridge",
                "rewritten_text": "这里我把节奏放慢一点。",
                "purpose": "bridge",
                "use_speed": True,
                "target_dur": 7.5,
                "emo_text_weight": 1.25,
            }
        ],
    )

    segment = request["segments"][0]
    assert segment["use_speed"] is True
    assert segment["target_dur"] == 7.5
    assert segment["emo_text_weight"] == 1.25


def test_execute_dubbing_downloads_audio_to_local_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import httpx

    reference_audio = tmp_path / "reference.wav"
    reference_audio.write_bytes(b"wav")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "audio_base64": base64.b64encode(b"generated-audio").decode("utf-8"),
                "format": "wav",
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url: str, json: dict[str, object]):
            assert url == "http://127.0.0.1:49204/v1/audio/speech"
            assert json["text"] == "大家好，我们来看看这个新功能。"
            assert json["use_speed"] is True
            assert json["target_dur"] == 2.8
            assert json["provider_options"]["use_emo_text"] is True
            assert json["provider_options"]["auto_mix_emotion"] is True
            assert json["provider_options"]["emo_text_weight"] == 1.15
            assert json["provider_options"]["target_dur"] == 2.8
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    provider = IndexTTS2VoiceProvider()
    result = provider.execute_dubbing(
        job_id="job-2",
        request={
            "speech_endpoint": "http://127.0.0.1:49204/v1/audio/speech",
            "segments": [
                {
                    "segment_id": "seg-1",
                    "text": "大家好，我们来看看这个新功能。",
                    "emotion_text": "自然亲切，带一点开场吸引力。",
                    "emotion_strength": 0.32,
                    "emo_text_weight": 1.15,
                    "use_speed": True,
                    "target_dur": 2.8,
                }
            ],
        },
        reference_audio_path=reference_audio,
    )

    assert result["status"] == "success"
    output_path = Path(result["segments"][0]["local_audio_path"])
    assert output_path.exists()
    assert output_path.read_bytes() == b"generated-audio"
    assert result["segments"][0]["use_speed"] is True
    assert result["segments"][0]["target_dur"] == 2.8
    assert result["segments"][0]["emo_text_weight"] == 1.15
