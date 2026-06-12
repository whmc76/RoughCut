import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api";
import type {
  IntelligentCopyGenerateTask,
  IntelligentCopyInspect,
  IntelligentCopyResult,
  ManualHandoffTarget,
  AvatarPublicationProfile,
  PublicationAttempt,
  PublicationIntelligenceScheme,
  PublicationPlan,
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
const SELECTED_PUBLICATION_BROWSER_STORAGE_KEY = "roughcut.intelligentCopy.selectedPublicationBrowser";
const FOLDER_PATH_HISTORY_LIMIT = 12;
const FOLDER_PATH_AUTOCOMPLETE_LIMIT = 8;
const FOLDER_PATH_AUTO_INSPECT_DELAY_MS = 900;

export const publicationBrowserOptions = [
  { id: "edge", label: "Microsoft Edge" },
  { id: "chrome", label: "Google Chrome" },
  { id: "firefox", label: "Firefox" },
  { id: "browser-agent", label: "Browser Agent 默认浏览器" },
] as const;

export function normalizeIntelligentCopyPlatformId(value: string | null | undefined): string {
  const key = String(value ?? "").trim().toLowerCase().replace(/_/g, "-");
  if (key === "wechat" || key === "wechat-channels") return "wechat-channels";
  return key;
}

export const intelligentCopyPlatformOptions = [
  { id: "bilibili", label: "B站", detail: "横版封面、搜索标题" },
  { id: "xiaohongshu", label: "小红书", detail: "笔记正文、话题串" },
  { id: "douyin", label: "抖音", detail: "竖版封面、短节奏" },
  { id: "kuaishou", label: "快手", detail: "口语简介、竖版封面" },
  { id: "wechat-channels", label: "视频号", detail: "稳妥摘要、可信表达" },
  { id: "toutiao", label: "头条号", detail: "资讯导语、结论先行" },
  { id: "youtube", label: "YouTube", detail: "检索描述、标签列表" },
  { id: "x", label: "X", detail: "短推文、少量话题" },
] as const;

const defaultIntelligentCopyPlatformIds = intelligentCopyPlatformOptions.map((platform) =>
  normalizeIntelligentCopyPlatformId(platform.id),
);

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

function draftFromPublicationPlatformOptions(
  options: Record<string, PublicationPlatformPublishOptions> | null | undefined,
): Record<string, PublishPlatformOptionDraft> {
  const entries = Object.entries(options ?? {}).map(([platform, value]) => [
    platform,
    {
      scheduled_publish_at: String(value.scheduled_publish_at ?? ""),
      collection_id: String(value.collection_id ?? ""),
      collection_name: String(value.collection_name ?? ""),
      category: String(value.category ?? ""),
      visibility_or_publish_mode: String(value.visibility_or_publish_mode ?? ""),
    },
  ] as const);
  return Object.fromEntries(entries);
}

function normalizeFolderPath(value: string | null | undefined): string {
  return String(value ?? "").trim();
}

export function buildIntelligentPublicationPlanQueryKey(args: {
  resultJsonPath?: string | null;
  folderPath?: string | null;
  selectedPublicationProfileId?: string | null;
  selectedGenerateTaskId?: string | null;
  selectedGenerateTaskUpdatedAt?: string | null;
}) {
  return [
    "intelligent-publication-plan",
    String(args.resultJsonPath ?? ""),
    normalizeFolderPath(args.folderPath),
    String(args.selectedPublicationProfileId ?? ""),
    String(args.selectedGenerateTaskId ?? ""),
    String(args.selectedGenerateTaskUpdatedAt ?? ""),
  ] as const;
}

function normalizePlatformSignature(platforms: Array<string | null | undefined>): string {
  return platforms
    .map((platform) => normalizeIntelligentCopyPlatformId(platform))
    .filter(Boolean)
    .sort()
    .join("|");
}

export function buildPublicationSchemeContextKey(args: {
  folderPath?: string | null;
  selectedPublicationProfileId?: string | null;
  selectedPublicationBrowser?: string | null;
  selectedGenerateTaskId?: string | null;
  selectedGenerateTaskUpdatedAt?: string | null;
  targetPlatforms?: Array<string | null | undefined>;
}) {
  return [
    normalizeFolderPath(args.folderPath),
    String(args.selectedPublicationProfileId ?? ""),
    String(args.selectedPublicationBrowser ?? ""),
    String(args.selectedGenerateTaskId ?? ""),
    String(args.selectedGenerateTaskUpdatedAt ?? ""),
    normalizePlatformSignature(args.targetPlatforms ?? []),
  ].join("::");
}

function isMaterializedContainerFolderPath(value: string | null | undefined): boolean {
  return normalizeFolderPath(value).replace(/\\/g, "/").startsWith("/app/data/host-intelligent-copy/");
}

function preferredVisibleFolderPath(...paths: Array<string | null | undefined>): string {
  const normalized = paths.map(normalizeFolderPath).filter(Boolean);
  return normalized.find((path) => !isMaterializedContainerFolderPath(path)) ?? normalized[0] ?? "";
}

export function mergeFolderPathHistory(paths: Array<string | null | undefined>, limit = FOLDER_PATH_HISTORY_LIMIT): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const path of paths) {
    const folderPath = normalizeFolderPath(path);
    if (!folderPath) continue;
    if (isMaterializedContainerFolderPath(folderPath)) continue;
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

function readStoredSelectedPublicationBrowser(): string {
  if (typeof window === "undefined") return "edge";
  try {
    const stored = window.localStorage.getItem(SELECTED_PUBLICATION_BROWSER_STORAGE_KEY) ?? "";
    return publicationBrowserOptions.some((option) => option.id === stored) ? stored : "edge";
  } catch {
    return "edge";
  }
}

function writeStoredSelectedPublicationBrowser(browser: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SELECTED_PUBLICATION_BROWSER_STORAGE_KEY, browser);
  } catch {
    // Browser selection is only a local convenience.
  }
}

function isTerminalGenerateTaskStatus(status: string | null | undefined): boolean {
  return ["completed", "manual_handoff", "blocked", "failed", "cancelled"].includes(String(status ?? ""));
}

function hasActivePublicationAttempt(attempts: PublicationAttempt[] | undefined): boolean {
  return (attempts ?? []).some((attempt) =>
    ["queued", "submitted", "processing", "scheduled_pending"].includes(String(attempt.status ?? "")),
  );
}

function materialFromTask(task: IntelligentCopyGenerateTask | null | undefined): IntelligentCopyResult | null {
  return task?.result ?? task?.partial_result ?? null;
}

function resultMaterialContract(result: IntelligentCopyResult | null | undefined): Record<string, unknown> | null {
  if (!result || !result.material_contract || typeof result.material_contract !== "object") return null;
  return result.material_contract;
}

function resultContractStatus(result: IntelligentCopyResult | null | undefined): string {
  const contract = resultMaterialContract(result);
  const status = String(contract?.status ?? "").trim().toLowerCase();
  if (status === "passed" || status === "manual_handoff" || status === "failed" || status === "blocked") {
    return status;
  }
  const platformContracts = contract?.platforms;
  const hasRootBlockingReasons = Array.isArray(contract?.blocking_reasons)
    && contract.blocking_reasons.some((item) => typeof item === "string" && item.trim().length > 0);
  const hasManualHandoffPlatforms = Array.isArray(contract?.manual_handoff_platforms) && contract.manual_handoff_platforms.length > 0;
  if (platformContracts && typeof platformContracts === "object") {
    const platformStatuses = new Set(
      Object.values(platformContracts)
        .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
        .map((item) => String(item.status ?? "").trim().toLowerCase())
        .filter(Boolean),
    );
    if (platformStatuses.has("failed") || platformStatuses.has("blocked")) return "failed";
    if (platformStatuses.has("manual_handoff")) return "manual_handoff";
    if (
      Object.values(platformContracts).some(
        (item) => Boolean(item && typeof item === "object" && (item as Record<string, unknown>).manual_handoff_only),
      )
    ) {
      return "manual_handoff";
    }
    if (platformStatuses.size > 0 && Array.from(platformStatuses).every((item) => item === "passed")) return "passed";
  }
  if (hasManualHandoffPlatforms && contract?.one_click_publish_ready === true) {
    return "manual_handoff";
  }
  if (hasRootBlockingReasons) {
    return "failed";
  }
  if (hasManualHandoffPlatforms) {
    return "manual_handoff";
  }
  return "";
}

function resultContractOneClickPublishReady(result: IntelligentCopyResult | null | undefined): boolean | null {
  const contract = resultMaterialContract(result);
  if (!contract) return null;
  const contractStatus = resultContractStatus(result);
  if (contractStatus === "passed") return true;
  if (contractStatus === "manual_handoff" || contractStatus === "failed" || contractStatus === "blocked") return false;
  if (contract.one_click_publish_ready === true) return true;
  if (contract.one_click_publish_ready === false) return false;
  return null;
}

export function resultBlockingReasons(result: IntelligentCopyResult | null | undefined): string[] {
  const contract = resultMaterialContract(result);
  const contractReasons = Array.isArray(contract?.blocking_reasons)
    ? contract.blocking_reasons.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
  const rootReasons = Array.isArray(result?.blocking_reasons)
    ? result.blocking_reasons.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
  return Array.from(new Set([...(contractReasons || []), ...(rootReasons || [])]));
}

function resultContractManualHandoffTargets(result: IntelligentCopyResult | null | undefined): unknown[] {
  const contract = resultMaterialContract(result);
  const rawTargets = contract?.manual_handoff_platforms;
  return Array.isArray(rawTargets) ? rawTargets : [];
}

export function resultManualHandoffTargets(result: IntelligentCopyResult | null | undefined): ManualHandoffTarget[] {
  const rawTargets: unknown[] = Array.isArray(result?.manual_handoff_targets)
    ? result!.manual_handoff_targets
    : resultContractManualHandoffTargets(result);
  return rawTargets
    .map((item) => {
      if (!item || typeof item !== "object" || !("platform" in item)) return item;
      const candidate = item as ManualHandoffTarget & { platform?: unknown };
      if (!candidate.platform) return item;
      return {
        ...candidate,
        platform: normalizeIntelligentCopyPlatformId(String(candidate.platform)),
      };
    })
    .filter((item): item is ManualHandoffTarget => (
      Boolean(item && typeof item === "object" && "platform" in item && (item as { platform?: unknown }).platform)
    ));
}

export function resultHasManualHandoffReady(result: IntelligentCopyResult | null | undefined): boolean {
  if (!result) return false;
  if (resultContractStatus(result) === "manual_handoff") return true;
  if (result.manual_handoff_ready) return true;
  if (String(result.status ?? "").trim().toLowerCase() === "manual_handoff") return true;
  if (resultManualHandoffTargets(result).length > 0) return true;
  if (result.publish_ready) return false;
  return false;
}

export function resultStatusKind(result: IntelligentCopyResult | null | undefined): "ready" | "blocked" | "manual_handoff" {
  if (!result) return "blocked";
  if (resultHasManualHandoffReady(result)) return "manual_handoff";
  const contractReady = resultContractOneClickPublishReady(result);
  if (contractReady === true) return "ready";
  if (contractReady === false) return "blocked";
  if (resultBlockingReasons(result).length > 0) return "blocked";
  if (String(result.status ?? "").trim().toLowerCase() === "blocked") return "blocked";
  if (String(result.status ?? "").trim().toLowerCase() === "failed") return "blocked";
  if (result.publish_ready === false) return "blocked";
  if (result.publish_ready === true) return "ready";
  return "blocked";
}

export function taskHasContinueReadyMaterial(task: IntelligentCopyGenerateTask | null | undefined): boolean {
  const material = materialFromTask(task);
  if (!material) return false;
  return resultStatusKind(material) !== "blocked";
}

export function publicationPlanManualHandoffTargets(plan: PublicationPlan | null | undefined): ManualHandoffTarget[] {
  return Array.isArray(plan?.manual_handoff_targets)
    ? plan!.manual_handoff_targets
      .map((item) => {
        if (!item || typeof item !== "object" || !("platform" in item)) return item;
        const candidate = item as ManualHandoffTarget & { platform?: unknown };
        if (!candidate.platform) return item;
        return {
          ...candidate,
          platform: normalizeIntelligentCopyPlatformId(String(candidate.platform)),
        };
      })
      .filter((item): item is ManualHandoffTarget => (
        Boolean(item && typeof item === "object" && "platform" in item && (item as { platform?: unknown }).platform)
      ))
    : [];
}

export function publicationPlanHasManualHandoffReady(plan: PublicationPlan | null | undefined): boolean {
  if (!plan) return false;
  if (plan.manual_handoff_ready) return true;
  if (String(plan.status ?? "").trim().toLowerCase() === "manual_handoff") return true;
  if (publicationPlanManualHandoffTargets(plan).length > 0) return true;
  if (plan.publish_ready) return false;
  return false;
}

function publicationPlanHasExecutableTargets(plan: PublicationPlan | null | undefined): boolean {
  return Array.isArray(plan?.targets) && plan!.targets.length > 0;
}

export function publicationPlanStatusKind(plan: PublicationPlan | null | undefined): "ready" | "blocked" | "manual_handoff" {
  if (!plan) return "blocked";
  if (publicationPlanHasManualHandoffReady(plan)) return "manual_handoff";
  const status = String(plan.status ?? "").trim().toLowerCase();
  if ((status === "ready" || status === "passed") && publicationPlanHasExecutableTargets(plan)) return "ready";
  if (status === "blocked" || status === "failed") return "blocked";
  if (Array.isArray(plan.blocked_reasons) && plan.blocked_reasons.length > 0) return "blocked";
  if (plan.publish_ready === true && publicationPlanHasExecutableTargets(plan)) return "ready";
  if (plan.publish_ready === false) return "blocked";
  return "blocked";
}

export function publicationPlanIsReady(plan: PublicationPlan | null | undefined): boolean {
  return publicationPlanStatusKind(plan) === "ready";
}

export function publicationPlanExecutorPreflightMessages(plan: PublicationPlan | null | undefined): string[] {
  const preflight =
    plan?.publication_executor_preflight && typeof plan.publication_executor_preflight === "object"
      ? plan.publication_executor_preflight
      : null;
  if (!preflight) return [];
  const messages = [
    typeof preflight.message === "string" ? preflight.message.trim() : "",
    ...(Array.isArray(preflight.failures)
      ? preflight.failures.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
      : []),
  ].filter(Boolean);
  return Array.from(new Set(messages));
}

export function openManualHandoffTarget(target: ManualHandoffTarget | null | undefined): boolean {
  const url = String(target?.login_url ?? "").trim();
  if (!url || typeof window === "undefined") return false;
  window.open(url, "_blank", "noopener,noreferrer");
  return true;
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

function shouldAutoInspectFolderPath(path: string): boolean {
  const normalized = normalizeFolderPath(path);
  if (normalized.length < 3) return false;
  if (/^[A-Za-z]:[\\/]?$/.test(normalized)) return false;
  return normalized.split(/[\\/]/).filter(Boolean).length >= 3;
}

export function useIntelligentCopyWorkspace() {
  const queryClient = useQueryClient();
  const lastAutoInspectPathRef = useRef("");
  const folderPathSourceRef = useRef<"manual" | "task_restore">("manual");
  const [folderPath, setFolderPathState] = useState("");
  const [debouncedFolderPath, setDebouncedFolderPath] = useState("");
  const [folderPathHistory, setFolderPathHistory] = useState<string[]>(readStoredFolderPathHistory);
  const [copyStyle, setCopyStyle] = useState("attention_grabbing");
  const [useExistingCover, setUseExistingCover] = useState(false);
  const [inspection, setInspection] = useState<IntelligentCopyInspect | null>(null);
  const [result, setResult] = useState<IntelligentCopyResult | null>(null);
  const [copyFeedback, setCopyFeedback] = useState("");
  const [selectedGenerateTaskId, setSelectedGenerateTaskIdState] = useState(readStoredSelectedGenerateTaskId);
  const [selectedPublicationAttemptId, setSelectedPublicationAttemptIdState] = useState(readStoredSelectedPublicationAttemptId);
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState("");
  const [selectedPublicationBrowser, setSelectedPublicationBrowserState] = useState(readStoredSelectedPublicationBrowser);
  const [publicationLoginMatchMessage, setPublicationLoginMatchMessage] = useState("");
  const [selectedMaterialPlatformIds, setSelectedMaterialPlatformIds] = useState<string[]>(defaultIntelligentCopyPlatformIds);
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<string[]>([]);
  const [publicationPlatformOptions, setPublicationPlatformOptions] = useState<Record<string, PublishPlatformOptionDraft>>({});
  const [publicationScheme, setPublicationScheme] = useState<PublicationIntelligenceScheme | null>(null);
  const [publicationSchemeInstruction, setPublicationSchemeInstruction] = useState("");

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
    onMutate: (path) => {
      const nextPath = normalizeFolderPath(path);
      const currentPath = normalizeFolderPath(inspection?.folder_path);
      if (nextPath && currentPath && nextPath !== currentPath) {
        setInspection(null);
        setResult(null);
      }
    },
    onSuccess: (payload) => {
      rememberFolderPath(payload.folder_path);
      setInspection(payload);
      setResult(null);
      setSelectedPlatformIds([]);
    },
    onError: () => {
      setInspection(null);
      setResult(null);
    },
  });

  useEffect(() => {
    const normalizedPath = normalizeFolderPath(debouncedFolderPath);
    if (!shouldAutoInspectFolderPath(normalizedPath)) return;
    if (folderPathSourceRef.current !== "manual") return;
    if (inspect.isPending) return;
    if (lastAutoInspectPathRef.current === normalizedPath) return;

    const handle = window.setTimeout(() => {
      lastAutoInspectPathRef.current = normalizedPath;
      inspect.mutate(normalizedPath);
    }, FOLDER_PATH_AUTO_INSPECT_DELAY_MS);
    return () => window.clearTimeout(handle);
  }, [debouncedFolderPath, inspect.isPending, inspect.mutate]);

  const setFolderPath = (value: string) => {
    folderPathSourceRef.current = "manual";
    setFolderPathState(value);
  };

  const restoreFolderPathFromTask = (nextPath: string) => {
    const normalizedPath = normalizeFolderPath(nextPath);
    if (!normalizedPath) {
      return;
    }
    folderPathSourceRef.current = "task_restore";
    setFolderPathState(normalizedPath);
  };

  const setSelectedGenerateTaskId = (taskId: string) => {
    setSelectedGenerateTaskIdState(taskId);
    writeStoredSelectedGenerateTaskId(taskId);
  };

  const recentGenerateTasks = useQuery({
    queryKey: ["intelligent-copy", "generate-tasks", "recent"],
    queryFn: () => api.getRecentIntelligentCopyGenerateTasks(30),
    refetchInterval: (query) => {
      const hasActive = (query.state.data?.tasks ?? []).some((task) => !isTerminalGenerateTaskStatus(task.status));
      return hasActive ? 1_500 : 8_000;
    },
  });

  useEffect(() => {
    const tasks = recentGenerateTasks.data?.tasks;
    if (!tasks) return;
    if (selectedGenerateTaskId && !tasks.some((task) => task.id === selectedGenerateTaskId)) {
      setSelectedGenerateTaskId("");
      setResult(null);
      return;
    }
    if (selectedGenerateTaskId || !tasks.length) return;
    const latest = tasks[0];
    if (latest) setSelectedGenerateTaskId(latest.id);
  }, [recentGenerateTasks.data?.tasks, selectedGenerateTaskId]);

  const selectedGenerateTask = useQuery({
    queryKey: ["intelligent-copy", "generate-task", selectedGenerateTaskId],
    queryFn: () => api.getIntelligentCopyGenerateTask(selectedGenerateTaskId),
    enabled: Boolean(selectedGenerateTaskId),
    retry: false,
    refetchInterval: (query) => {
      const task = query.state.data;
      return isTerminalGenerateTaskStatus(task?.status) ? false : 1_000;
    },
  });

  useEffect(() => {
    if (!selectedGenerateTaskId || !selectedGenerateTask.isError) return;
    setSelectedGenerateTaskId("");
    setResult(null);
  }, [selectedGenerateTask.isError, selectedGenerateTaskId]);

  const setSelectedPublicationAttemptId = (attemptId: string) => {
    setSelectedPublicationAttemptIdState(attemptId);
    writeStoredSelectedPublicationAttemptId(attemptId);
  };

  const setSelectedPublicationBrowser = (browser: string) => {
    setSelectedPublicationBrowserState(browser);
    writeStoredSelectedPublicationBrowser(browser);
  };

  const recentPublicationAttempts = useQuery({
    queryKey: ["intelligent-publication-attempts", "recent"],
    queryFn: () => api.getRecentPublicationAttempts(48),
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
    const restoredFolderPath = preferredVisibleFolderPath(task.inspection?.folder_path, task.folder_path, folderPath);
    if (task.inspection) {
      setInspection(task.inspection);
      restoreFolderPathFromTask(restoredFolderPath);
    } else if (task.folder_path) {
      restoreFolderPathFromTask(restoredFolderPath);
    }
    const material = materialFromTask(task);
    if (material) {
      setResult(material);
    } else {
      setResult(null);
    }
  }, [selectedGenerateTask.data]);

  const generate = useMutation({
    mutationFn: (payload: { folderPath: string; copyStyle: string; platforms: string[]; useExistingCover: boolean; creatorProfileId?: string | null }) =>
      api.createIntelligentCopyGenerateTask(
        payload.folderPath,
        payload.copyStyle,
        payload.platforms,
        payload.useExistingCover,
        payload.creatorProfileId || null,
    ),
    onSuccess: (payload) => {
      rememberFolderPath(preferredVisibleFolderPath(payload.inspection?.folder_path, payload.folder_path, folderPath));
      if (payload.inspection) setInspection(payload.inspection);
      setResult(materialFromTask(payload));
      setSelectedGenerateTaskId(payload.id);
      setSelectedPlatformIds([]);
      setPublicationPlatformOptions({});
      setPublicationScheme(null);
      setPublicationSchemeInstruction("");
      void queryClient.invalidateQueries({ queryKey: ["intelligent-copy", "generate-tasks", "recent"] });
      void queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
    },
  });

  const openFolder = useMutation({
    mutationFn: (path: string) => api.openIntelligentCopyFolder(path),
  });

  const publicationQueryKey = buildIntelligentPublicationPlanQueryKey({
    resultJsonPath: result?.json_path,
    folderPath: inspection?.folder_path ?? folderPath,
    selectedPublicationProfileId,
    selectedGenerateTaskId,
    selectedGenerateTaskUpdatedAt: selectedGenerateTask.data?.updated_at,
  });
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
  const publicationSchemeContextKey = buildPublicationSchemeContextKey({
    folderPath: inspection?.folder_path ?? folderPath,
    selectedPublicationProfileId,
    selectedPublicationBrowser,
    selectedGenerateTaskId,
    selectedGenerateTaskUpdatedAt: selectedGenerateTask.data?.updated_at,
    targetPlatforms: (publicationPlan.data?.targets ?? []).map((target) => target.platform),
  });

  const matchPublicationBrowserLogin = useMutation({
    mutationFn: () =>
      api.matchPublicationBrowserLogin(
        selectedPublicationProfileId,
        selectedPublicationBrowser,
        (result?.platforms ?? []).map((platform) => platform.key),
      ),
    onSuccess: async (payload) => {
      queryClient.setQueryData(["avatar-materials", "publication-profiles"], payload);
      const matchedCount =
        payload.profiles
          .find((profile) => profile.id === selectedPublicationProfileId)
          ?.creator_profile?.publishing?.platform_credentials?.filter((credential) => credential.enabled !== false).length ?? 0;
      setPublicationLoginMatchMessage(`已匹配本地浏览器会话引用，当前创作者卡片有 ${matchedCount} 个可用发布绑定。`);
      await queryClient.invalidateQueries({ queryKey: ["avatar-materials", "publication-profiles"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
    },
    onError: (error) => {
      setPublicationLoginMatchMessage((error as Error).message || "自动匹配登录信息失败。");
    },
  });

  useEffect(() => {
    const targetPlatforms = (publicationPlan.data?.targets ?? [])
      .map((target) => normalizeIntelligentCopyPlatformId(target.platform))
      .filter(Boolean);
    if (!targetPlatforms.length) {
      setSelectedPlatformIds([]);
      setPublicationPlatformOptions({});
      setPublicationScheme(null);
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

  useEffect(() => {
    setPublicationPlatformOptions({});
    setPublicationScheme(null);
    setPublicationSchemeInstruction("");
  }, [publicationSchemeContextKey]);

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
    const normalizedPlatform = normalizeIntelligentCopyPlatformId(platform);
    setSelectedPlatformIds((current) =>
      current.includes(normalizedPlatform)
        ? current.filter((item) => item !== normalizedPlatform)
        : [...current, normalizedPlatform],
    );
  };

  const toggleMaterialPlatform = (platform: string) => {
    const normalizedPlatform = normalizeIntelligentCopyPlatformId(platform);
    setSelectedMaterialPlatformIds((current) =>
      current.includes(normalizedPlatform)
        ? current.filter((item) => item !== normalizedPlatform)
        : [...current, normalizedPlatform],
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
        platform_options: publicationScheme?.platform_options ?? buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (payload) => {
      queryClient.setQueryData(publicationQueryKey, payload);
      const createdAttempt = payload.created_attempts?.[0];
      if (createdAttempt) setSelectedPublicationAttemptId(createdAttempt.id);
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-plan"] });
      await queryClient.invalidateQueries({ queryKey: ["intelligent-publication-attempts"] });
    },
  });

  const applyPublicationScheme = (scheme: PublicationIntelligenceScheme) => {
    setPublicationScheme(scheme);
    setPublicationPlatformOptions(draftFromPublicationPlatformOptions(scheme.platform_options));
    const schemePlatforms = (scheme.items ?? [])
      .map((item) => normalizeIntelligentCopyPlatformId(item.platform))
      .filter(Boolean);
    if (schemePlatforms.length) setSelectedPlatformIds(schemePlatforms);
  };

  const generatePublicationScheme = useMutation<PublicationIntelligenceScheme, Error, boolean | undefined>({
    mutationFn: (forceProbe) =>
      api.generateIntelligentPublishScheme(inspection?.folder_path || folderPath, {
        creator_profile_id: selectedPublicationProfileId || null,
        platforms: selectedPlatformIds.length
          ? selectedPlatformIds
          : (publicationPlan.data?.targets ?? []).map((target) => target.platform),
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
        browser: selectedPublicationBrowser,
        force_probe: Boolean(forceProbe),
      }),
    onSuccess: (payload) => {
      applyPublicationScheme(payload);
      if (payload.plan) queryClient.setQueryData(publicationQueryKey, payload.plan);
    },
  });

  const modifyPublicationScheme = useMutation({
    mutationFn: () => {
      if (!publicationScheme) throw new Error("请先生成智能发布方案。");
      return api.modifyIntelligentPublishScheme(publicationScheme, publicationSchemeInstruction);
    },
    onSuccess: (payload) => {
      applyPublicationScheme(payload);
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
    useExistingCover,
    setUseExistingCover,
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
    publicationBrowserOptions,
    selectedPublicationBrowser,
    setSelectedPublicationBrowser,
    matchPublicationBrowserLogin,
    publicationLoginMatchMessage,
    materialPlatformOptions: intelligentCopyPlatformOptions,
    selectedMaterialPlatformIds,
    toggleMaterialPlatform,
    selectAllMaterialPlatforms,
    selectedPlatformIds,
    togglePlatform,
    publicationPlatformOptions,
    updatePublicationPlatformOption,
    publicationScheme,
    publicationSchemeInstruction,
    setPublicationSchemeInstruction,
    generatePublicationScheme,
    modifyPublicationScheme,
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
