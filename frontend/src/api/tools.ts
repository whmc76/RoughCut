import type { ToolAsrResult, ToolAvatarResult, ToolRunStatus, ToolStatus, ToolTtsOutputHistory, ToolTtsReferenceAudioHistory, ToolTtsResult } from "../types";
import { request, requestForm } from "./core";

export const toolsApi = {
  getToolStatus: () => request<ToolStatus>("/tools/status"),
  getToolTtsReferenceAudio: () => request<ToolTtsReferenceAudioHistory>("/tools/tts/reference-audio"),
  getToolTtsOutputs: () => request<ToolTtsOutputHistory>("/tools/tts/outputs"),
  getToolRun: <Result>(runId: string) => request<ToolRunStatus<Result>>(`/tools/runs/${encodeURIComponent(runId)}`),
  runToolTts: (formData: FormData) => requestForm<ToolRunStatus<ToolTtsResult>>("/tools/tts", formData),
  runToolAsr: (formData: FormData) => requestForm<ToolRunStatus<ToolAsrResult>>("/tools/asr", formData),
  runToolAvatar: (formData: FormData) => requestForm<ToolRunStatus<ToolAvatarResult>>("/tools/avatar", formData),
};
