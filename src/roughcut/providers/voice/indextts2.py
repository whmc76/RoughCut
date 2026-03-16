from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services
from roughcut.providers.voice.base import VoiceProvider


class IndexTTS2VoiceProvider(VoiceProvider):
    def build_dubbing_request(
        self,
        *,
        job_id: str,
        segments: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        base_url = settings.voice_clone_api_base_url.rstrip("/")
        return {
            "provider": "indextts2",
            "base_url": base_url,
            "speech_endpoint": base_url + "/v1/audio/speech",
            "health_endpoint": base_url + "/health",
            "job_id": job_id,
            "segment_count": len(segments),
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "text": segment.get("rewritten_text") or segment.get("script") or segment.get("source_text"),
                    "target_duration_sec": segment.get("target_duration_sec"),
                    "emotion_text": _infer_emotion_text(segment),
                    "emotion_strength": _infer_emotion_strength(segment),
                    "purpose": segment.get("purpose"),
                }
                for segment in segments
            ],
            "metadata": metadata or {},
        }

    def execute_dubbing(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
        reference_audio_path: Path | None = None,
    ) -> dict[str, Any]:
        if reference_audio_path is None or not reference_audio_path.exists():
            return {
                "provider": "indextts2",
                "job_id": job_id,
                "status": "skipped",
                "reason": "missing_reference_audio",
                "segments": [],
            }

        segments = list(request.get("segments") or [])
        if not segments:
            return {
                "provider": "indextts2",
                "job_id": job_id,
                "status": "skipped",
                "reason": "empty_segments",
                "segments": [],
            }

        reference_audio_b64 = base64.b64encode(reference_audio_path.read_bytes()).decode("utf-8")
        timeout = httpx.Timeout(180.0, connect=20.0)
        output_dir = Path("data/avatar_dubbing") / str(job_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        results: list[dict[str, Any]] = []
        with hold_managed_gpu_services(
            required_urls=[str(request.get("speech_endpoint") or "")],
            reason="indextts2_dubbing",
        ):
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                for segment in segments:
                    try:
                        results.append(
                            self._execute_segment(
                                client=client,
                                request=request,
                                segment=segment,
                                reference_audio_b64=reference_audio_b64,
                                output_dir=output_dir,
                            )
                        )
                    except Exception as exc:
                        results.append(
                            {
                                "segment_id": segment.get("segment_id"),
                                "status": "failed",
                                "error": str(exc),
                            }
                        )

        success_count = sum(1 for item in results if item.get("status") == "success")
        failed_count = sum(1 for item in results if item.get("status") == "failed")
        status = "success"
        if success_count == 0 and failed_count:
            status = "failed"
        elif failed_count:
            status = "partial"

        return {
            "provider": "indextts2",
            "job_id": job_id,
            "status": status,
            "segment_count": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "segments": results,
        }

    def _execute_segment(
        self,
        *,
        client: httpx.Client,
        request: dict[str, Any],
        segment: dict[str, Any],
        reference_audio_b64: str,
        output_dir: Path,
    ) -> dict[str, Any]:
        text = str(segment.get("text") or "").strip()
        if not text:
            return {
                "segment_id": segment.get("segment_id"),
                "status": "failed",
                "error": "empty_text",
            }

        payload = {
            "input": text,
            "voice": "default",
            "model": "indextts2",
            "response_format": "wav",
            "provider_options": {
                "output_mode": "base64",
                "speaker_audio_base64": reference_audio_b64,
                "emo_text": str(segment.get("emotion_text") or "").strip(),
                "use_emo_text": True,
                "auto_mix_emotion": True,
                "emotion_strength": float(segment.get("emotion_strength") or 0.32),
                "max_text_tokens_per_segment": 120,
                "interval_silence": 120,
            },
        }

        response = client.post(str(request.get("speech_endpoint") or ""), json=payload)
        response.raise_for_status()
        body = response.json()
        audio_b64 = str(body.get("audio_base64") or "").strip()
        if not audio_b64:
            raise RuntimeError(f"indextts2 did not return audio_base64 for {segment.get('segment_id')}")

        file_name = _build_output_name(segment_id=str(segment.get("segment_id") or "segment"))
        output_path = output_dir / file_name
        output_path.write_bytes(base64.b64decode(audio_b64))

        return {
            "segment_id": segment.get("segment_id"),
            "status": "success",
            "audio_url": str(output_path),
            "local_audio_path": str(output_path),
            "format": str(body.get("format") or "wav"),
            "emotion_text": segment.get("emotion_text"),
            "emotion_strength": segment.get("emotion_strength"),
        }


def _build_output_name(*, segment_id: str) -> str:
    safe_segment = re.sub(r"[^a-zA-Z0-9._-]+", "_", segment_id).strip("_") or "segment"
    return f"{safe_segment}_{uuid.uuid4().hex[:8]}.wav"


def _infer_emotion_text(segment: dict[str, Any]) -> str:
    purpose = str(segment.get("purpose") or "").strip().lower()
    text = str(segment.get("text") or segment.get("rewritten_text") or "").strip()
    if any(token in text for token in ("惊喜", "震撼", "太强", "终于", "离谱", "牛")):
        return "轻微兴奋但保持自然，重点词更有精神。"
    if purpose == "hook":
        return "开场更有抓力，带一点悬念感和兴奋度。"
    if purpose in {"bridge", "explain", "science_boost"}:
        return "平静清晰，像在认真解释重点，节奏稳定。"
    if purpose == "closing":
        return "温和收口，带一点邀请互动的感觉。"
    return "自然口语化，语气稳定，轻微强调重点。"


def _infer_emotion_strength(segment: dict[str, Any]) -> float:
    purpose = str(segment.get("purpose") or "").strip().lower()
    if purpose == "hook":
        return 0.36
    if purpose == "closing":
        return 0.28
    if purpose in {"bridge", "explain", "science_boost"}:
        return 0.24
    return 0.3
