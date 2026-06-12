import type {
  IntelligentCopyGenerateTask,
  IntelligentCopyGenerateTaskList,
  IntelligentCopyImagegenRequestList,
  IntelligentCopyInspect,
  IntelligentCopyPathSuggestResponse,
  IntelligentCopyResult,
  PublicationIntelligenceScheme,
  PublicationAttemptList,
  PublicationPlan,
  PublicationPlatformPublishOptions,
} from "../types";
import { request } from "./core";

export const intelligentCopyApi = {
  inspectIntelligentCopyFolder: (folderPath: string) =>
    request<IntelligentCopyInspect>("/intelligent-copy/inspect", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
  suggestIntelligentCopyFolders: (query: string, limit = 12) =>
    request<IntelligentCopyPathSuggestResponse>("/intelligent-copy/path-suggestions", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  generateIntelligentCopy: (
    folderPath: string,
    copyStyle?: string,
    platforms?: string[],
    useExistingCover = false,
    creatorProfileId?: string | null,
  ) =>
    request<IntelligentCopyResult>("/intelligent-copy/generate", {
      method: "POST",
      body: JSON.stringify({
        folder_path: folderPath,
        copy_style: copyStyle || null,
        platforms: platforms ?? [],
        use_existing_cover: useExistingCover,
        creator_profile_id: creatorProfileId || null,
      }),
    }),
  createIntelligentCopyGenerateTask: (
    folderPath: string,
    copyStyle?: string,
    platforms?: string[],
    useExistingCover = false,
    creatorProfileId?: string | null,
  ) =>
    request<IntelligentCopyGenerateTask>("/intelligent-copy/generate-tasks", {
      method: "POST",
      body: JSON.stringify({
        folder_path: folderPath,
        copy_style: copyStyle || null,
        platforms: platforms ?? [],
        use_existing_cover: useExistingCover,
        creator_profile_id: creatorProfileId || null,
      }),
    }),
  getIntelligentCopyGenerateTask: (taskId: string) =>
    request<IntelligentCopyGenerateTask>(`/intelligent-copy/generate-tasks/${taskId}`),
  getRecentIntelligentCopyGenerateTasks: (limit = 12) =>
    request<IntelligentCopyGenerateTaskList>(`/intelligent-copy/generate-tasks/recent?limit=${limit}`),
  listIntelligentCopyImagegenRequests: (folderPath: string) =>
    request<IntelligentCopyImagegenRequestList>("/intelligent-copy/imagegen-requests", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
  completeIntelligentCopyImagegenRequest: (folderPath: string, requestPath: string, resultPath: string) =>
    request<IntelligentCopyImagegenRequestList>("/intelligent-copy/imagegen-requests/complete", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, request_path: requestPath, result_path: resultPath }),
    }),
  getIntelligentPublishPlan: (
    folderPath: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>("/intelligent-copy/publication/plan", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, ...body }),
    }),
  generateIntelligentPublishScheme: (
    folderPath: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
      browser?: string | null;
      force_probe?: boolean;
    },
  ) =>
    request<PublicationIntelligenceScheme>("/intelligent-copy/publication/scheme", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, ...body }),
    }),
  modifyIntelligentPublishScheme: (scheme: PublicationIntelligenceScheme, instruction: string) =>
    request<PublicationIntelligenceScheme>("/intelligent-copy/publication/scheme/modify", {
      method: "POST",
      body: JSON.stringify({ scheme, instruction }),
    }),
  getRecentPublicationAttempts: (limit = 24, creatorProfileId?: string | null) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (creatorProfileId) params.set("creator_profile_id", creatorProfileId);
    return request<PublicationAttemptList>(`/intelligent-copy/publication/attempts/recent?${params.toString()}`);
  },
  publishIntelligentFolder: (
    folderPath: string,
    body: {
      creator_profile_id?: string | null;
      platforms?: string[];
      platform_options?: Record<string, PublicationPlatformPublishOptions>;
    },
  ) =>
    request<PublicationPlan>("/intelligent-copy/publication/publish", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath, ...body }),
    }),
  openIntelligentCopyFolder: (folderPath: string) =>
    request<{ path: string; kind: string }>("/intelligent-copy/open-folder", {
      method: "POST",
      body: JSON.stringify({ folder_path: folderPath }),
    }),
};
