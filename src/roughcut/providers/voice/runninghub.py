from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from roughcut.config import get_settings
from roughcut.providers.voice.base import VoiceProvider

_DEFAULT_WORKFLOW_ID = "2003864334474354690"
_DEFAULT_AUDIO_NODE_ID = "4"
_DEFAULT_TEXT_NODE_ID = "14"
_DEFAULT_EMOTION_NODE_ID = "15"
_POLL_INTERVAL_SECONDS = 4.0
_TASK_TIMEOUT_SECONDS = 240.0


class RunningHubVoiceProvider(VoiceProvider):
    def build_dubbing_request(
        self,
        *,
        job_id: str,
        segments: list[dict[str, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        workflow_id = str(settings.voice_clone_voice_id or _DEFAULT_WORKFLOW_ID).strip() or _DEFAULT_WORKFLOW_ID
        base_url = settings.voice_clone_api_base_url.rstrip("/")
        return {
            "provider": "runninghub",
            "base_url": base_url,
            "workflow_id": workflow_id,
            "create_endpoint": base_url + "/task/openapi/create",
            "status_endpoint": base_url + "/task/openapi/status",
            "outputs_endpoint": base_url + "/task/openapi/outputs",
            "upload_endpoint": base_url + "/openapi/v2/media/upload/binary",
            "job_id": job_id,
            "segment_count": len(segments),
            "segments": [
                {
                    "segment_id": segment.get("segment_id"),
                    "text": segment.get("rewritten_text") or segment.get("script") or segment.get("source_text"),
                    "target_duration_sec": segment.get("target_duration_sec"),
                    "emotion": _infer_emotion_text(segment),
                    "purpose": segment.get("purpose"),
                }
                for segment in segments
            ],
            "metadata": metadata or {},
            "node_mapping": {
                "reference_audio": _DEFAULT_AUDIO_NODE_ID,
                "text": _DEFAULT_TEXT_NODE_ID,
                "emotion": _DEFAULT_EMOTION_NODE_ID,
            },
        }

    def execute_dubbing(
        self,
        *,
        job_id: str,
        request: dict[str, Any],
        reference_audio_path: Path | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        api_key = str(settings.voice_clone_api_key or "").strip()
        if not api_key:
            return {
                "provider": "runninghub",
                "job_id": job_id,
                "status": "skipped",
                "reason": "missing_api_key",
                "segments": [],
            }
        if reference_audio_path is None or not reference_audio_path.exists():
            return {
                "provider": "runninghub",
                "job_id": job_id,
                "status": "skipped",
                "reason": "missing_reference_audio",
                "segments": [],
            }

        workflow_id = str(request.get("workflow_id") or _DEFAULT_WORKFLOW_ID).strip() or _DEFAULT_WORKFLOW_ID
        node_mapping = dict(request.get("node_mapping") or {})
        segments = list(request.get("segments") or [])
        if not segments:
            return {
                "provider": "runninghub",
                "job_id": job_id,
                "status": "skipped",
                "reason": "empty_segments",
                "segments": [],
            }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Host": httpx.URL(str(request.get("base_url") or settings.voice_clone_api_base_url)).host or "www.runninghub.cn",
        }
        timeout = httpx.Timeout(60.0, connect=30.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            reference_audio_url = self._upload_reference_audio(
                client=client,
                upload_endpoint=str(request["upload_endpoint"]),
                headers=headers,
                reference_audio_path=reference_audio_path,
            )
            results: list[dict[str, Any]] = []
            for segment in segments:
                try:
                    results.append(
                        self._execute_segment(
                            client=client,
                            headers=headers,
                            request=request,
                            workflow_id=workflow_id,
                            node_mapping=node_mapping,
                            reference_audio_url=reference_audio_url,
                            segment=segment,
                            api_key=api_key,
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
            "provider": "runninghub",
            "job_id": job_id,
            "status": status,
            "workflow_id": workflow_id,
            "reference_audio_url": reference_audio_url,
            "segment_count": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "segments": results,
        }

    def _upload_reference_audio(
        self,
        *,
        client: httpx.Client,
        upload_endpoint: str,
        headers: dict[str, str],
        reference_audio_path: Path,
    ) -> str:
        with reference_audio_path.open("rb") as file_handle:
            response = client.post(
                upload_endpoint,
                headers={"Authorization": headers["Authorization"]},
                files={"file": (reference_audio_path.name, file_handle, "audio/wav")},
            )
        response.raise_for_status()
        payload = response.json()
        if _response_code(payload) != 0:
            raise RuntimeError(f"RunningHub upload failed: {payload.get('msg') or payload}")
        data = payload.get("data") or {}
        audio_url = str(data.get("download_url") or "").strip()
        if not audio_url:
            raise RuntimeError("RunningHub upload did not return download_url")
        return audio_url

    def _execute_segment(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        request: dict[str, Any],
        workflow_id: str,
        node_mapping: dict[str, str],
        reference_audio_url: str,
        segment: dict[str, Any],
        api_key: str,
    ) -> dict[str, Any]:
        payload = {
            "apiKey": api_key,
            "workflowId": workflow_id,
            "nodeInfoList": [
                {
                    "nodeId": str(node_mapping.get("reference_audio") or _DEFAULT_AUDIO_NODE_ID),
                    "fieldName": "audio",
                    "fieldValue": reference_audio_url,
                },
                {
                    "nodeId": str(node_mapping.get("text") or _DEFAULT_TEXT_NODE_ID),
                    "fieldName": "text",
                    "fieldValue": str(segment.get("text") or "").strip(),
                },
                {
                    "nodeId": str(node_mapping.get("emotion") or _DEFAULT_EMOTION_NODE_ID),
                    "fieldName": "text",
                    "fieldValue": str(segment.get("emotion") or "").strip(),
                },
            ],
        }
        response = client.post(str(request["create_endpoint"]), headers=headers, json=payload)
        response.raise_for_status()
        create_payload = response.json()
        if _response_code(create_payload) != 0:
            return {
                "segment_id": segment.get("segment_id"),
                "status": "failed",
                "error": create_payload.get("msg") or "create_failed",
                "response": create_payload,
            }

        data = create_payload.get("data") or {}
        task_id = str(data.get("taskId") or "").strip()
        if not task_id:
            return {
                "segment_id": segment.get("segment_id"),
                "status": "failed",
                "error": "missing_task_id",
                "response": create_payload,
            }

        final_status = self._poll_task_status(
            client=client,
            headers=headers,
            status_endpoint=str(request["status_endpoint"]),
            api_key=api_key,
            task_id=task_id,
        )
        outputs = self._load_task_outputs(
            client=client,
            headers=headers,
            outputs_endpoint=str(request["outputs_endpoint"]),
            api_key=api_key,
            task_id=task_id,
        )
        first_output = outputs[0] if outputs else {}
        status = "success" if final_status == "SUCCESS" and outputs else "failed"
        return {
            "segment_id": segment.get("segment_id"),
            "status": status,
            "task_id": task_id,
            "task_status": final_status,
            "audio_url": first_output.get("fileUrl"),
            "file_type": first_output.get("fileType"),
            "consume_coins": first_output.get("consumeCoins"),
            "task_cost_time": first_output.get("taskCostTime"),
            "outputs": outputs,
        }

    def _poll_task_status(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        status_endpoint: str,
        api_key: str,
        task_id: str,
    ) -> str:
        started_at = time.monotonic()
        latest_status = "QUEUED"
        while time.monotonic() - started_at < _TASK_TIMEOUT_SECONDS:
            response = client.post(
                status_endpoint,
                headers=headers,
                json={"apiKey": api_key, "taskId": task_id},
            )
            response.raise_for_status()
            payload = response.json()
            if _response_code(payload) != 0:
                raise RuntimeError(f"RunningHub status failed: {payload.get('msg') or payload}")
            latest_status = str(payload.get("data") or "").strip().upper() or latest_status
            if latest_status not in {"RUNNING", "QUEUED"}:
                return latest_status
            time.sleep(_POLL_INTERVAL_SECONDS)
        raise TimeoutError(f"RunningHub task timed out: {task_id}")

    def _load_task_outputs(
        self,
        *,
        client: httpx.Client,
        headers: dict[str, str],
        outputs_endpoint: str,
        api_key: str,
        task_id: str,
    ) -> list[dict[str, Any]]:
        response = client.post(
            outputs_endpoint,
            headers=headers,
            json={"apiKey": api_key, "taskId": task_id},
        )
        response.raise_for_status()
        payload = response.json()
        if _response_code(payload) != 0:
            raise RuntimeError(f"RunningHub outputs failed: {payload.get('msg') or payload}")
        data = payload.get("data") or []
        return [item for item in data if isinstance(item, dict)]


def _infer_emotion_text(segment: dict[str, Any]) -> str:
    purpose = str(segment.get("purpose") or "").strip().lower()
    if purpose == "hook":
        return "稍微兴奋，带一点悬念感，句子更有抓力。"
    if purpose in {"bridge", "explain", "science_boost"}:
        return "平静清晰，像在认真解释重点，节奏稳定。"
    if purpose == "closing":
        return "温和收口，带一点邀请互动的感觉。"
    return "自然口语化，语气稳定，轻微强调重点。"


def _response_code(payload: dict[str, Any]) -> int:
    try:
        return int(payload.get("code"))
    except (TypeError, ValueError):
        return -1
