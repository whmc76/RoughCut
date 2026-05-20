import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import type {
  IntelligentCopyGenerateTask,
  IntelligentCopyInspect,
  IntelligentCopyResult,
  AvatarPublicationProfile,
  PublicationAttempt,
  PublicationPlatformPublishOptions,
} from "../../types";

export type PublishPlatformOptionDraft = {
  scheduled_publish_at: string;
  collection_id: string;
  collection_name: string;
  category: string;
  visibility_or_publish_mode: string;
};

const FOLDER_PATH_HISTORY_STORAGE_KEY = "roughcut.intelligentCopy.folderPathHistory";
const SELECTED_GENERATE_TASK_STORAGE_KEY = "roughcut.intelligentCopy.selectedGenerateTaskId";
const SELECTED_PUBLICATION_ATTEMPT_STORAGE_KEY = "roughcut.intelligentCopy.selectedPublicationAttemptId";
const FOLDER_PATH_HISTORY_LIMIT = 12;
const FOLDER_PATH_AUTOCOMPLETE_LIMIT = 8;

export const intelligentCopyPlatformOptions = [
  { id: "bilibili", label: "B站", detail: "横版封面、搜索标题" },
  { id: "xiaohongshu", label: "小红书", detail: "笔记正文、话题串" },
  { id: "douyin", label: "抖音", detail: "竖版封面、短节奏" },
  { id: "kuaishou", label: "快手", detail: "口语简介、竖版封面" },
  { id: "wechat_channels", label: "视频号", detail: "稳妥摘要、可信表达" },
  { id: "toutiao", label: "头条号", detail: "资讯导语、结论先行" },
  { id: "youtube", label: "YouTube", detail: "检索描述、标签列表" },
  { id: "x", label: "X", detail: "短推文、少量话题" },
] as const;

const defaultIntelligentCopyPlatformIds = intelligentCopyPlatformOptions.map((platform) => platform.id);

export function publicationAttemptStatusLabel(status: string) {
  if (status === "queued") return "已排队";
  if (status === "submitted") return "已提交";
  if (status === "processing") return "发布中";
  if (status === "draft_created") return "草稿已创建";
  if (status === "scheduled_pending") return "已预约";
  if (status === "published") return "已发布";
  if (status === "needs_human") return "需人工处理";
  if (status === "failed") return "失败";
  return status || "待处理";
}

function createEmptyPublicationPlatformOption(): PublishPlatformOptionDraft {
  return {
    scheduled_publish_at: "",
    collection_id: "",
    collection_name: "",
    category: "",
    visibility_or_publish_mode: "",
  };
}

function buildPublicationPlatformOptions(
  draft: Record<string, PublishPlatformOptionDraft>,
): Record<string, PublicationPlatformPublishOptions> {
  const entries = Object.entries(draft)
    .map(([platform, value]) => {
      const option: PublicationPlatformPublishOptions = {};
      const scheduledAt = value.scheduled_publish_at.trim();
      const collectionId = value.collection_id.trim();
      const collectionName = value.collection_name.trim();
      const category = value.category.trim();
      const visibility = value.visibility_or_publish_mode.trim();
      if (scheduledAt) option.scheduled_publish_at = scheduledAt;
      if (collectionId) option.collection_id = collectionId;
      if (collectionName) option.collection_name = collectionName;
      if (category) option.category = category;
      if (visibility) option.visibility_or_publish_mode = visibility;
      return [platform, option] as const;
    })
    .filter(([, option]) => Object.keys(option).length > 0);
  return Object.fromEntries(entries);
}

function normalizeFolderPath(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

export function mergeFolderPathHistory(paths: Array<string | null | undefined>, limit = FOLDER_PATH_HISTORY_LIMIT): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const path of paths) {
    const folderPath = normalizeFolderPath(path);
    if (!folderPath) continue;
    const key = folderPath.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    next.push(folderPath);
    if (next.length >= limit) break;
  }
  return next;
}

function readStoredFolderPathHistory(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(FOLDER_PATH_HISTORY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? mergeFolderPathHistory(parsed.map(String)) : [];
  } catch {
    return [];
  }
}

function writeStoredFolderPathHistory(paths: string[]) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(FOLDER_PATH_HISTORY_STORAGE_KEY, JSON.stringify(paths));
  } catch {
    // Path history only powers quick selections.
  }
}

function readStoredSelectedGenerateTaskId(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(SELECTED_GENERATE_TASK_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeStoredSelectedGenerateTaskId(taskId: string) {
  if (typeof window === "undefined") return;
  try {
    if (taskId) {
      window.localStorage.setItem(SELECTED_GENERATE_TASK_STORAGE_KEY, taskId);
    } else {
      window.localStorage.removeItem(SELECTED_GENERATE_TASK_STORAGE_KEY);
    }
  } catch {
    // Restoring a task is a convenience; generation still works without it.
  }
}

function readStoredSelectedPublicationAttemptId(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(SELECTED_PUBLICATION_ATTEMPT_STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

function writeStoredSelectedPublicationAttemptId(attemptId: string) {
  if (typeof window === "undefined") return;
  try {
    if (attemptId) {
      window.localStorage.setItem(SELECTED_PUBLICATION_ATTEMPT_STORAGE_KEY, attemptId);
    } else {
      window.localStorage.removeItem(SELECTED_PUBLICATION_ATTEMPT_STORAGE_KEY);
    }
  } catch {
    // Publishing history still works without persisted selection.
  }
}

function isTerminalGenerateTaskStatus(status: string | null | undefined): boolean {
  return ["completed", "failed", "cancelled"].includes(String(status ?? ""));
}

function hasActivePublicationAttempt(attempts: PublicationAttempt[] | undefined): boolean {
  return (attempts ?? []).some((attempt) =>
    ["queued", "submitted", "processing", "scheduled_pending"].includes(String(attempt.status ?? "")),
  );
}

function materialFromTask(task: IntelligentCopyGenerateTask | null | undefined): IntelligentCopyResult | null {
  return task?.result ?? task?.partial_result ?? null;
}

function withoutTrailingSeparators(path: string): string {
  if (/^[A-Za-z]:[\\/]?$/.test(path)) return path.length === 2 ? `${path}\\` : path;
  if (/^[\\/]+$/.test(path)) return path;
  return path.replace(/[\\/]+$/, "");
}

export function getParentFolderPath(path: string | null | undefined): string {
  const normalized = withoutTrailingSeparators(normalizeFolderPath(path));
  if (!normalized || /^[A-Za-z]:[\\/]?$/.test(normalized)) return "";
  const slashIndex = Math.max(normalized.lastIndexOf("\\"), normalized.lastIndexOf("/"));
  if (slashIndex < 0) return "";
  if (slashIndex === 0) return normalized.slice(0, 1);
  if (/^[A-Za-z]:[\\/]/.test(normalized) && slashIndex === 2) return normalized.slice(0, 3);
  return normalized.slice(0, slashIndex);
}

function folderPathMatchScore(path: string, query: string): number {
  const normalizedPath = path.toLowerCase();
  const normalizedQuery = query.toLowerCase();
  if (!normalizedQuery) return 1;
  if (normalizedPath.startsWith(normalizedQuery)) return 0;
  const leafName = normalizedPath.split(/[\\/]/).filter(Boolean).at(-1) ?? normalizedPath;
  if (leafName.startsWith(normalizedQuery)) return 1;
  if (normalizedPath.includes(normalizedQuery)) return 2;
  return 9;
}

function rankHistoricalFolderPaths(paths: string[], query: string): string[] {
  const normalizedQuery = normalizeFolderPath(query);
  return paths
    .map((path, index) => ({ path, index, score: folderPathMatchScore(path, normalizedQuery) }))
    .filter((item) => item.score < 9)
    .sort((left, right) => left.score - right.score || left.index - right.index)
    .map((item) => item.path);
}

export function useIntelligentCopyWorkspace() {
  const queryClient = useQueryClient();
  const [folderPath, setFolderPath] = useState("");
  const [debouncedFolderPath, setDebouncedFolderPath] = useState("");
  const [folderPathHistory, setFolderPathHistory] = useState<string[]>(readStoredFolderPathHistory);
  const [copyStyle, setCopyStyle] = useState("attention_grabbing");
  const [inspection, setInspection] = useState<IntelligentCopyInspect | null>(null);
  const [result, setResult] = useState<IntelligentCopyResult | null>(null);
  const [copyFeedback, setCopyFeedback] = useState("");
  const [selectedGenerateTaskId, setSelectedGenerateTaskIdState] = useState(readStoredSelectedGenerateTaskId);
  const [selectedPublicationAttemptId, setSelectedPublicationAttemptIdState] = useState(readStoredSelectedPublicationAttemptId);
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState("");
  const [selectedMaterialPlatformIds, setSelectedMaterialPlatformIds] = useState<string[]>(defaultIntelligentCopyPlatformIds);
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<string[]>([]);
  const [publicationPlatformOptions, setPublicationPlatformOptions] = useState<Record<string, PublishPlatformOptionDraft>>({});

  const publicationProfilesQuery = useQuery({
    queryKey: ["avatar-materials", "publication-profiles"],
    queryFn: api.getAvatarPublicationProfiles,
    staleTime: 30_000,
  });
  const publicationProfiles: AvatarPublicationProfile[] = useMemo(
    () => publicationProfilesQuery.data?.profiles ?? [],
    [publicationProfilesQuery.data?.profiles],
  );

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedFolderPath(folderPath), 180);
    return () => window.clearTimeout(handle);
  }, [folderPath]);

  const filesystemPathSuggestions = useQuery({
    queryKey: ["intelligent-copy", "path-suggestions", debouncedFolderPath],
    queryFn: () => api.suggestIntelligentCopyFolders(debouncedFolderPath, FOLDER_PATH_AUTOCOMPLETE_LIMIT),
    enabled: normalizeFolderPath(debouncedFolderPath).length >= 2,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!publicationProfiles.length) {
      setSelectedPublicationProfileId("");
      return;
    }
    setSelectedPublicationProfileId((current) =>
      publicationProfiles.some((profile) => profile.id === current) ? current : publicationProfiles[0]?.id ?? "",
    );
  }, [publicationProfiles]);

  const rememberFolderPath = (path: string | null | undefined) => {
    setFolderPathHistory((current) => {
      const next = mergeFolderPathHistory([path, ...current]);
      writeStoredFolderPathHistory(next);
      return next;
    });
  };

  const inspect = useMutation({
    mutationFn: (path: string) => api.inspectIntelligentCopyFolder(path),
    onSuccess: (payload) => {
      rememberFolderPath(payload.folder_path);
      setInspection(payload);
      setResult(null);
      setSelectedPlatformIds([]);
    },
  });

  const setSelectedGenerateTaskId = (taskId: string) => {
    setSelectedGenerateTaskIdState(taskId);
    writeStoredSelectedGenerateTaskId(taskId);
  };

  const recentGenerateTasks = useQuery({
    queryKey: ["intelligent-copy", "generate-tasks", "recent"],
    queryFn: () => api.getRecentIntelligentCopyGenerateTasks(12),
    refetchInterval: (query) => {
      const hasActive = (query.state.data?.tasks ?? []).some((task) => !isTerminalGenerateTaskStatus(task.status));
      return hasActive ? 1_500 : 8_000;
    },
  });

  useEffect(() => {
    if (selectedGenerateTaskId || !recentGenerateTasks.data?.tasks.length) return;
    const latest = recentGenerateTasks.data.tasks[0];
    if (latest) setSelectedGenerateTaskId(latest.id);
  }, [recentGenerateTasks.data?.tasks, selectedGenerateTaskId]);

  const selectedGenerateTask = useQuery({
    queryKey: ["intelligent-copy", "generate-task", selectedGenerateTaskId],
    queryFn: () => api.getIntelligentCopyGenerateTask(selectedGenerateTaskId),
    enabled: Boolean(selectedGenerateTaskId),
    refetchInterval: (query) => {
      const task = query.state.data;
      return isTerminalGenerateTaskStatus(task?.status) ? false : 1_000;
    },
  });

  const setSelectedPublicationAttemptId = (attemptId: string) => {
    setSelectedPublicationAttemptIdState(attemptId);
    writeStoredSelectedPublicationAttemptId(attemptId);
  };

  const recentPublicationAttempts = useQuery({
    queryKey: ["intelligent-publication-attempts", "recent"],
    queryFn: () => api.getRecentPublicationAttempts(24),
    refetchInterval: (query) => (hasActivePublicationAttempt(query.state.data?.attempts) ? 1_500 : 8_000),
  });

  useEffect(() => {
    const attempts = recentPublicationAttempts.data?.attempts ?? [];
    if (!attempts.length) return;
    if (selectedPublicationAttemptId && attempts.some((attempt) => attempt.id === selectedPublicationAttemptId)) return;
    setSelectedPublicationAttemptId(attempts[0].id);
  }, [recentPublicationAttempts.data?.attempts, selectedPublicationAttemptId]);

  useEffect(() => {
    const task = selectedGenerateTask.data;
    if (!task) return;
    if (task.inspection) {
      setInspection(task.inspection);
      setFolderPath(task.inspection.folder_path || task.folder_path || "");
    } else if (task.folder_path) {
      setFolderPath(task.folder_path);
    }
    const material = materialFromTask(task);
    if (material) {
      setResult(material);
    } else {
      setResult(null);
    }
  }, [selectedGenerateTask.data]);

  const generate = useMutation({
    mutationFn: (payload: { folderPath: string; copyStyle: string; platforms: string[] }) =>
      api.createIntelligentCopyGenerateTask(payload.folderPath, payload.copyStyle, payload.platforms),
    onSuccess: (payload) => {
      rememberFolderPath(payload.inspection?.folder_path || payload.folder_path);
      if (payload.inspection) setInspection(payload.inspection);
      setResult(materialFromTask(payload));
      setSelectedGenerateTaskId(payload.id);
      setSelectedPlatformIds([]);
      void queryClient.invalidateQueries({ queryKey: ["intelligent-copy", "generate-tasks", "recent"] });
      void queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
    },
  });

  const openFolder = useMutation({
    mutationFn: (path: string) => api.openIntelligentCopyFolder(path),
  });

  const publicationQueryKey = [
    "intelligent-publication-plan",
    result?.json_path ?? "",
    inspection?.folder_path ?? folderPath,
    selectedPublicationProfileId,
  ] as const;
  const hasResolvedPublicationProfileSelection = Boolean(publicationProfilesQuery.data) || publicationProfilesQuery.isFetched;
  const hasPublicationPlanInput = Boolean((result || inspection) && (inspection?.folder_path || folderPath).trim());
  const publicationPlan = useQuery({
    queryKey: publicationQueryKey,
    queryFn: () =>
      api.getIntelligentPublishPlan(inspection?.folder_path || folderPath, {
        creator_profile_id: selectedPublicationProfileId || null,
      }),
    enabled: hasPublicationPlanInput && hasResolvedPublicationProfileSelection,
    refetchInterval: (query) => (hasActivePublicationAttempt(query.state.data?.existing_attempts) ? 1_500 : false),
  });

  useEffect(() => {
    const targetPlatforms = (publicationPlan.data?.targets ?? []).map((target) => target.platform);
    if (!targetPlatforms.length) {
      setSelectedPlatformIds([]);
      setPublicationPlatformOptions({});
      return;
    }
    setSelectedPlatformIds((current) => {
      const filtered = current.filter((platform) => targetPlatforms.includes(platform));
      return filtered.length ? filtered : targetPlatforms;
    });
    setPublicationPlatformOptions((current) => {
      const next = Object.fromEntries(Object.entries(current).filter(([platform]) => targetPlatforms.includes(platform)));
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [publicationPlan.data?.targets]);

  const updatePublicationPlatformOption = (platform: string, patch: Partial<PublishPlatformOptionDraft>) => {
    setPublicationPlatformOptions((current) => {
      const currentOption = current[platform] ?? createEmptyPublicationPlatformOption();
      return {
        ...current,
        [platform]: { ...currentOption, ...patch },
      };
    });
  };

  const togglePlatform = (platform: string) => {
    setSelectedPlatformIds((current) =>
      current.includes(platform) ? current.filter((item) => item !== platform) : [...current, platform],
    );
  };

  const toggleMaterialPlatform = (platform: string) => {
    setSelectedMaterialPlatformIds((current) =>
      current.includes(platform) ? current.filter((item) => item !== platform) : [...current, platform],
    );
  };

  const selectAllMaterialPlatforms = () => {
    setSelectedMaterialPlatformIds(defaultIntelligentCopyPlatformIds);
  };

  const publish = useMutation({
    mutationFn: () =>
      api.publishIntelligentFolder(inspection?.folder_path || folderPath, {
        creator_profile_id: selectedPublicationProfileId || null,
        platforms: selectedPlatformIds,
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (payload) => {
      queryClient.setQueryData(publicationQueryKey, payload);
      const createdAttempt = payload.created_attempts?.[0];
      if (createdAttempt) setSelectedPublicationAttemptId(createdAttempt.id);
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-attempts"] });
    },
  });

  async function copyText(text: string, successLabel: string) {
    if (!text.trim()) {
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopyFeedback(successLabel);
    } catch {
      setCopyFeedback("复制失败，请检查系统剪贴板权限。");
    }
    window.setTimeout(() => setCopyFeedback(""), 1800);
  }

  const parentFolderSuggestions = useMemo(
    () =>
      mergeFolderPathHistory([
        getParentFolderPath(folderPath),
        ...folderPathHistory.map(getParentFolderPath),
      ], 6).filter((path) => path !== normalizeFolderPath(folderPath)),
    [folderPath, folderPathHistory],
  );

  const folderPathAutocompleteOptions = useMemo(() => {
    const filesystemSuggestions = filesystemPathSuggestions.data?.suggestions.map((suggestion) => suggestion.path) ?? [];
    const historicalSuggestions = rankHistoricalFolderPaths([
      ...folderPathHistory,
      ...parentFolderSuggestions,
    ], folderPath);
    return mergeFolderPathHistory([
      ...filesystemSuggestions,
      ...historicalSuggestions,
    ], FOLDER_PATH_AUTOCOMPLETE_LIMIT);
  }, [filesystemPathSuggestions.data?.suggestions, folderPath, folderPathHistory, parentFolderSuggestions]);

  return {
    folderPath,
    setFolderPath,
    folderPathAutocompleteOptions,
    parentFolderSuggestions,
    filesystemPathSuggestions,
    copyStyle,
    setCopyStyle,
    inspection,
    result,
    recentGenerateTasks,
    selectedGenerateTask: selectedGenerateTask.data ?? null,
    selectedGenerateTaskQuery: selectedGenerateTask,
    selectedGenerateTaskId,
    setSelectedGenerateTaskId,
    inspect,
    generate,
    openFolder,
    avatarMaterials: publicationProfilesQuery,
    publicationProfiles,
    selectedPublicationProfileId,
    setSelectedPublicationProfileId,
    materialPlatformOptions: intelligentCopyPlatformOptions,
    selectedMaterialPlatformIds,
    toggleMaterialPlatform,
    selectAllMaterialPlatforms,
    selectedPlatformIds,
    togglePlatform,
    publicationPlatformOptions,
    updatePublicationPlatformOption,
    publicationPlan,
    recentPublicationAttempts,
    selectedPublicationAttemptId,
    setSelectedPublicationAttemptId,
    selectedPublicationAttempt:
      (recentPublicationAttempts.data?.attempts ?? []).find((attempt) => attempt.id === selectedPublicationAttemptId) ?? null,
    publish,
    copyText,
    copyFeedback,
  };
}
