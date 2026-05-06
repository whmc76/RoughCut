import type { ToolAsrResult, ToolAvatarResult, ToolRunStatus, ToolStatus, ToolTtsResult } from "../types";
import { request, requestForm } from "./core";

export const toolsApi = {
  getToolStatus: () => request<ToolStatus>("/tools/status"),
  getToolRun: <Result>(runId: string) => request<ToolRunStatus<Result>>(`/tools/runs/${encodeURIComponent(runId)}`),
  runToolTts: (formData: FormData) => requestForm<ToolRunStatus<ToolTtsResult>>("/tools/tts", formData),
  runToolAsr: (formData: FormData) => requestForm<ToolRunStatus<ToolAsrResult>>("/tools/asr", formData),
  runToolAvatar: (formData: FormData) => requestForm<ToolRunStatus<ToolAvatarResult>>("/tools/avatar", formData),
};
