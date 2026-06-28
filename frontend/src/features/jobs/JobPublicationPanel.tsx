import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../../api";
import { apiPath } from "../../api/core";
import {
  openManualHandoffTarget,
  publicationPlanExecutorPreflightMessages,
  publicationPlanHasManualHandoffReady,
  publicationPlanManualHandoffTargets,
  publicationPlanStatusKind,
} from "../intelligentCopy/useIntelligentCopyWorkspace";
import { publicationAttemptReceiptId } from "../publication/publicationAttempt";
import type {
  AvatarPublicationProfile,
  IntelligentCopyGenerateTask,
  Job,
  ManualHandoffTarget,
  PublicationAttempt,
  PublicationPlan,
  PublicationPlatformPublishOptions,
  PublicationTarget,
} from "../../types";

type PublicationPlatformOptionDraft = {
  scheduled_publish_at: string;
  collection_id: string;
  collection_name: string;
  category: string;
  visibility_or_publish_mode: string;
};

type PublicationMaterialCard = {
  platform: string;
  platform_label: string;
  account_label?: string | null;
  adapter?: string | null;
  status?: string | null;
  has_title?: boolean;
  title_label?: string | null;
  body_label?: string | null;
  tag_label?: string | null;
  separate_tags?: boolean;
  tags_embedded_in_body?: boolean;
  constraints?: Record<string, unknown> | null;
  publish_projects?: Array<Record<string, unknown>>;
  title?: string | null;
  body?: string | null;
  description?: string | null;
  tags?: string[];
  full_copy?: string | null;
  cover_path?: string | null;
  cover_slots?: Array<Record<string, unknown>>;
  category?: string | null;
  collection?: { id?: string; name?: string } | null;
  declaration?: string | null;
  visibility_or_publish_mode?: string | null;
  scheduled_publish_at?: string | null;
  login_url?: string | null;
  manual_publish_entry_url?: string | null;
  manual_reason?: string | null;
};

const AUTO_PUBLISH_PLATFORMS = new Set(["bilibili", "kuaishou", "douyin", "youtube", "x"]);
const JOB_BOUND_PUBLICATION_PROFILE_ID = "__job_bound_creator__";
const JOB_UNBOUND_PUBLICATION_PROFILE_ID = "__job_unbound_creator__";
const PUBLICATION_CREDENTIALS_ROUTE = "/tools/avatar";
const DEFAULT_PUBLICATION_MATERIAL_PLATFORM_IDS = [
  "bilibili",
  "xiaohongshu",
  "douyin",
  "kuaishou",
  "wechat-channels",
  "toutiao",
  "youtube",
  "x",
];

const PLATFORM_LABELS: Record<string, string> = {
  bilibili: "B站",
  kuaishou: "快手",
  douyin: "抖音",
  youtube: "YouTube",
  x: "X",
  xiaohongshu: "小红书",
  "wechat-channels": "视频号",
  toutiao: "头条",
};

function publicationAttemptStatusLabel(status: string) {
  if (status === "queued") return "已排队";
  if (status === "draft_created") return "草稿已创建";
  if (status === "scheduled_pending") return "已预约";
  if (status === "published") return "已发布";
  if (status === "failed") return "失败";
  return status || "待处理";
}

function normalizePublicationPlatformId(value: string | null | undefined): string {
  return String(value ?? "").trim().toLowerCase().replace(/_/g, "-");
}

function publicationPlatformLabel(platform: string, fallback?: string | null): string {
  const normalized = normalizePublicationPlatformId(platform);
  return String(fallback || PLATFORM_LABELS[normalized] || platform || "平台").trim();
}

function compactCopy(value: string | null | undefined, fallback = ""): string {
  return String(value ?? fallback).trim();
}

function tagsCopy(tags: string[] | null | undefined): string {
  return (tags ?? []).map((item) => String(item).trim()).filter(Boolean).join(" ");
}

function numberConstraint(card: PublicationMaterialCard, key: string): number | null {
  const value = card.constraints?.[key];
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function materialHasTitle(card: PublicationMaterialCard): boolean {
  if (card.has_title === false) return false;
  const titleLimit = numberConstraint(card, "title_limit");
  if (titleLimit !== null && titleLimit <= 0) return false;
  return true;
}

function materialHasSeparateTags(card: PublicationMaterialCard): boolean {
  if (card.separate_tags === false || card.tags_embedded_in_body) return false;
  const tagLimit = numberConstraint(card, "tag_limit");
  if (tagLimit !== null && tagLimit <= 0) return false;
  return true;
}

function materialTitleLabel(card: PublicationMaterialCard): string {
  return compactCopy(card.title_label, "标题");
}

function materialBodyLabel(card: PublicationMaterialCard): string {
  return compactCopy(card.body_label, card.platform === "kuaishou" ? "作品描述" : "正文");
}

function materialTagLabel(card: PublicationMaterialCard): string {
  return compactCopy(card.tag_label, "标签");
}

function materialPublishProjectLabels(card: PublicationMaterialCard): string[] {
  return (card.publish_projects ?? [])
    .map((item) => compactCopy(String(item?.label ?? item?.key ?? "")))
    .filter(Boolean);
}

function fullCopyFromMaterial(card: PublicationMaterialCard): string {
  const explicit = compactCopy(card.full_copy);
  if (explicit) return explicit;
  return [
    materialHasTitle(card) ? compactCopy(card.title) : "",
    compactCopy(card.body || card.description),
    materialHasSeparateTags(card) ? tagsCopy(card.tags) : "",
  ].filter(Boolean).join("\n\n");
}

async function copyText(value: string, label: string, setMessage: (value: string) => void) {
  const text = String(value || "").trim();
  if (!text) {
    setMessage("当前项没有可复制内容。");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    setMessage(label);
  } catch {
    setMessage("浏览器拒绝写入剪贴板，请手动选择复制。");
  }
}

function buildEnabledPublicationPlatforms(profile: AvatarPublicationProfile | null | undefined): string[] {
  const credentials = profile?.creator_profile?.publishing?.platform_credentials ?? [];
  const platforms = credentials
    .filter((credential) => credential.enabled !== false)
    .map((credential) => normalizePublicationPlatformId(credential.platform))
    .filter(Boolean);
  return Array.from(new Set(platforms));
}

function materialCardFromTarget(target: PublicationTarget): PublicationMaterialCard {
  return {
    platform: normalizePublicationPlatformId(target.platform),
    platform_label: target.platform_label,
    account_label: target.account_label,
    adapter: target.adapter,
    status: target.status,
    has_title: target.has_title,
    title_label: target.title_label,
    body_label: target.body_label,
    tag_label: target.tag_label,
    separate_tags: target.separate_tags,
    tags_embedded_in_body: target.tags_embedded_in_body,
    constraints: target.constraints,
    publish_projects: target.publish_projects,
    title: target.title,
    body: target.body,
    description: target.description,
    tags: target.tags,
    full_copy: target.full_copy,
    cover_path: target.cover_path,
    cover_slots: target.cover_slots,
    category: target.category,
    collection: target.collection,
    declaration: target.declaration,
    visibility_or_publish_mode: target.visibility_or_publish_mode,
    scheduled_publish_at: target.scheduled_publish_at,
    login_url: target.login_url,
    manual_publish_entry_url: target.manual_publish_entry_url,
  };
}

function materialCardFromManualTarget(target: ManualHandoffTarget): PublicationMaterialCard {
  const richTarget = target as ManualHandoffTarget & Partial<PublicationMaterialCard>;
  return {
    platform: normalizePublicationPlatformId(richTarget.platform),
    platform_label: publicationPlatformLabel(richTarget.platform, richTarget.label || richTarget.platform_label),
    account_label: richTarget.account_label,
    adapter: richTarget.adapter,
    status: richTarget.status || "manual_handoff",
    has_title: richTarget.has_title,
    title_label: richTarget.title_label,
    body_label: richTarget.body_label,
    tag_label: richTarget.tag_label,
    separate_tags: richTarget.separate_tags,
    tags_embedded_in_body: richTarget.tags_embedded_in_body,
    constraints: richTarget.constraints,
    publish_projects: richTarget.publish_projects,
    title: richTarget.title,
    body: richTarget.body,
    description: richTarget.description,
    tags: richTarget.tags,
    full_copy: richTarget.full_copy,
    cover_path: richTarget.cover_path,
    cover_slots: richTarget.cover_slots,
    category: richTarget.category,
    collection: richTarget.collection,
    declaration: richTarget.declaration,
    visibility_or_publish_mode: richTarget.visibility_or_publish_mode,
    scheduled_publish_at: richTarget.scheduled_publish_at,
    login_url: richTarget.login_url,
    manual_publish_entry_url: richTarget.manual_publish_entry_url || richTarget.login_url,
    manual_reason: richTarget.reason || richTarget.manual_reason,
  };
}

function mergeMaterialCard(base: PublicationMaterialCard | undefined, next: PublicationMaterialCard): PublicationMaterialCard {
  const merged: PublicationMaterialCard = { ...(base ?? next) };
  for (const [key, value] of Object.entries(next) as Array<[keyof PublicationMaterialCard, PublicationMaterialCard[keyof PublicationMaterialCard]]>) {
    if (value === undefined || value === null) continue;
    merged[key] = value as never;
  }
  return merged;
}

function mergePublicationMaterialCards(plan: PublicationPlan | null | undefined): PublicationMaterialCard[] {
  const byPlatform = new Map<string, PublicationMaterialCard>();
  for (const target of plan?.material_targets ?? []) {
    const card = materialCardFromTarget(target);
    byPlatform.set(card.platform, card);
  }
  for (const target of plan?.targets ?? []) {
    const card = materialCardFromTarget(target);
    byPlatform.set(card.platform, mergeMaterialCard(byPlatform.get(card.platform), card));
  }
  for (const target of publicationPlanManualHandoffTargets(plan)) {
    const card = materialCardFromManualTarget(target);
    byPlatform.set(card.platform, mergeMaterialCard(byPlatform.get(card.platform), card));
  }
  return Array.from(byPlatform.values());
}

function materialStatusLabel(card: PublicationMaterialCard): string {
  if (card.status === "material_ready") return "已生成物料";
  if (card.status === "manual_handoff") return "人工接管";
  return AUTO_PUBLISH_PLATFORMS.has(card.platform) ? "自动发布" : "手动发布";
}

function localImagePreviewUrl(path: string, version?: string | null): string {
  const imagePath = compactCopy(path);
  if (!imagePath) return "";
  return apiPath(`/intelligent-copy/local-image?path=${encodeURIComponent(imagePath)}&v=${encodeURIComponent(version || imagePath)}`);
}

function materialCoverPreviews(card: PublicationMaterialCard): Array<{ key: string; label: string; path: string }> {
  const seen = new Set<string>();
  const previews: Array<{ key: string; label: string; path: string }> = [];
  const addPreview = (path: unknown, label: unknown, fallback: string) => {
    const coverPath = compactCopy(String(path ?? ""));
    if (!coverPath || seen.has(coverPath)) return;
    seen.add(coverPath);
    previews.push({
      key: coverPath,
      label: compactCopy(String(label ?? ""), fallback),
      path: coverPath,
    });
  };
  addPreview(card.cover_path, "主封面", "主封面");
  for (const slot of card.cover_slots ?? []) {
    addPreview(slot.cover_path, slot.label || slot.slot, "封面");
  }
  return previews;
}

function openPublicationEntry(card: PublicationMaterialCard): boolean {
  const url = compactCopy(card.manual_publish_entry_url || card.login_url);
  if (!url || typeof window === "undefined") return false;
  window.open(url, "_blank", "noopener,noreferrer");
  return true;
}

function createEmptyPublicationPlatformOption(): PublicationPlatformOptionDraft {
  return {
    scheduled_publish_at: "",
    collection_id: "",
    collection_name: "",
    category: "",
    visibility_or_publish_mode: "",
  };
}

function buildPublicationPlatformOptions(
  draft: Record<string, PublicationPlatformOptionDraft>,
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

function hasActivePublicationAttempt(attempts: PublicationAttempt[] | undefined): boolean {
  return (attempts ?? []).some((attempt) =>
    ["queued", "submitted", "processing", "scheduled_pending"].includes(String(attempt.status ?? "")),
  );
}

function isTerminalMaterialTaskStatus(status: string | null | undefined): boolean {
  return ["completed", "manual_handoff", "blocked", "failed", "cancelled"].includes(String(status ?? ""));
}

function materialTaskProgress(task: IntelligentCopyGenerateTask | null | undefined): number {
  if (!task) return 0;
  const value = Number(task.progress ?? 0);
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function buildJobPublicationPlanQueryKey(
  jobId: string | null | undefined,
  selectedPublicationProfileId: string | null | undefined,
  jobUpdatedAt: string | null | undefined,
) {
  return [
    "job-publication-plan",
    String(jobId ?? ""),
    String(selectedPublicationProfileId ?? ""),
    String(jobUpdatedAt ?? ""),
  ] as const;
}

export function buildJobPublicationDraftContextKey(
  jobId: string | null | undefined,
  selectedPublicationProfileId: string | null | undefined,
  jobUpdatedAt: string | null | undefined,
) {
  return [
    String(jobId ?? ""),
    String(selectedPublicationProfileId ?? ""),
    String(jobUpdatedAt ?? ""),
  ].join("::");
}

function publicationProfileIdForRequest(selectedPublicationProfileId: string): string | null {
  if (
    !selectedPublicationProfileId
    || selectedPublicationProfileId === JOB_BOUND_PUBLICATION_PROFILE_ID
    || selectedPublicationProfileId === JOB_UNBOUND_PUBLICATION_PROFILE_ID
  ) {
    return null;
  }
  return selectedPublicationProfileId;
}

function jobBoundCreatorLabel(job: Job, plan: PublicationPlan | null | undefined): string {
  const name = compactCopy(job.creator_card_name || plan?.creator_profile_name);
  if (job.creator_card_id) {
    return name ? `已绑定：${name}` : "已绑定创作者（名称载入中）";
  }
  return "未绑定创作者";
}

type JobPublicationPanelProps = {
  job: Job;
  onCancel?: () => void;
};

export function JobPublicationPanel({ job, onCancel }: JobPublicationPanelProps) {
  const queryClient = useQueryClient();
  const avatarMaterials = useQuery({
    queryKey: ["avatar-materials", "publication-profiles"],
    queryFn: api.getAvatarPublicationProfiles,
    enabled: job.status === "done",
  });
  const publicationProfiles = useMemo(
    () => avatarMaterials.data?.profiles ?? [],
    [avatarMaterials.data?.profiles],
  );
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState(
    () => (job.creator_card_id ? JOB_BOUND_PUBLICATION_PROFILE_ID : JOB_UNBOUND_PUBLICATION_PROFILE_ID),
  );
  const [publicationPlatformOptions, setPublicationPlatformOptions] = useState<Record<string, PublicationPlatformOptionDraft>>({});
  const [selectedPlatformIds, setSelectedPlatformIds] = useState<string[]>([]);
  const [materialsPrepared, setMaterialsPrepared] = useState(false);
  const [selectedMaterialPlatform, setSelectedMaterialPlatform] = useState("");
  const [copyMessage, setCopyMessage] = useState("");
  const [activeMaterialTaskId, setActiveMaterialTaskId] = useState("");

  useEffect(() => {
    if (job.creator_card_id) {
      setSelectedPublicationProfileId((current) => {
        if (!current || current === JOB_BOUND_PUBLICATION_PROFILE_ID) return JOB_BOUND_PUBLICATION_PROFILE_ID;
        return publicationProfiles.some((profile) => profile.id === current)
          ? current
          : JOB_BOUND_PUBLICATION_PROFILE_ID;
      });
      return;
    }
    if (!publicationProfiles.length) {
      setSelectedPublicationProfileId(JOB_UNBOUND_PUBLICATION_PROFILE_ID);
      return;
    }
    setSelectedPublicationProfileId((current) =>
      current === JOB_UNBOUND_PUBLICATION_PROFILE_ID || publicationProfiles.some((profile) => profile.id === current)
        ? current
        : JOB_UNBOUND_PUBLICATION_PROFILE_ID,
    );
  }, [job.creator_card_id, publicationProfiles]);

  const requestPublicationProfileId = publicationProfileIdForRequest(selectedPublicationProfileId);

  const publicationQueryKey = buildJobPublicationPlanQueryKey(
    job.id,
    selectedPublicationProfileId,
    job.updated_at,
  );
  const publicationDraftContextKey = buildJobPublicationDraftContextKey(
    job.id,
    selectedPublicationProfileId,
    job.updated_at,
  );
  const publicationPlan = useQuery<PublicationPlan>({
    queryKey: publicationQueryKey,
    queryFn: () => api.getJobPublicationPlan(job.id, requestPublicationProfileId),
    enabled: Boolean(job.id && job.status === "done"),
    refetchInterval: (query) => (hasActivePublicationAttempt(query.state.data?.existing_attempts) ? 1_500 : false),
  });
  const materialTask = useQuery<IntelligentCopyGenerateTask>({
    queryKey: ["job-publication-material-task", activeMaterialTaskId],
    queryFn: () => api.getIntelligentCopyGenerateTask(activeMaterialTaskId),
    enabled: Boolean(activeMaterialTaskId),
    refetchInterval: (query) => (isTerminalMaterialTaskStatus(query.state.data?.status) ? false : 1_000),
  });
  const activeMaterialTask = materialTask.data ?? null;
  const materialTaskRunning = Boolean(activeMaterialTask && !isTerminalMaterialTaskStatus(activeMaterialTask.status));
  const activeMaterialTaskProgress = materialTaskProgress(activeMaterialTask);
  const manualHandoffTargets = publicationPlanManualHandoffTargets(publicationPlan.data);
  const manualHandoffReady = publicationPlanHasManualHandoffReady(publicationPlan.data);
  const publicationPlanStatus = publicationPlanStatusKind(publicationPlan.data);
  const publicationExecutorPreflightMessages = publicationPlanExecutorPreflightMessages(publicationPlan.data);
  const selectedPublicationProfile = useMemo(() => {
    const directProfile = publicationProfiles.find((profile) => profile.id === selectedPublicationProfileId);
    if (directProfile) return directProfile;
    if (selectedPublicationProfileId !== JOB_BOUND_PUBLICATION_PROFILE_ID) return null;
    const planProfileId = compactCopy(publicationPlan.data?.creator_profile_id);
    if (planProfileId) {
      const byPlanId = publicationProfiles.find((profile) => profile.id === planProfileId);
      if (byPlanId) return byPlanId;
    }
    const planProfileName = compactCopy(publicationPlan.data?.creator_profile_name || job.creator_card_name);
    if (planProfileName) {
      return publicationProfiles.find((profile) => profile.display_name === planProfileName) ?? null;
    }
    return null;
  }, [job.creator_card_name, publicationPlan.data?.creator_profile_id, publicationPlan.data?.creator_profile_name, publicationProfiles, selectedPublicationProfileId]);
  const configuredPlatformIds = useMemo(
    () => buildEnabledPublicationPlatforms(selectedPublicationProfile),
    [selectedPublicationProfile],
  );
  const materialCards = useMemo(() => mergePublicationMaterialCards(publicationPlan.data), [publicationPlan.data]);
  const isLoadingMaterialPlan = publicationPlan.isLoading && !publicationPlan.data;
  const platformChoices = useMemo(() => {
    const fromPlan = materialCards.map((card) => card.platform);
    const progressiveFallback = isLoadingMaterialPlan && job.status === "done" && !fromPlan.length
      ? DEFAULT_PUBLICATION_MATERIAL_PLATFORM_IDS
      : [];
    const ids = Array.from(new Set([...configuredPlatformIds, ...fromPlan, ...progressiveFallback])).filter(Boolean);
    return ids.map((platform) => ({
      platform,
      label: publicationPlatformLabel(platform, materialCards.find((card) => card.platform === platform)?.platform_label),
    }));
  }, [configuredPlatformIds, isLoadingMaterialPlan, job.status, materialCards]);
  const selectedMaterialCard = materialCards.find((card) => card.platform === selectedMaterialPlatform)
    ?? materialCards[0]
    ?? null;
  const publicationCredentialsMissing = !isLoadingMaterialPlan && platformChoices.length === 0;
  const autoPublishPlatformIds = (publicationPlan.data?.targets ?? [])
    .map((target) => normalizePublicationPlatformId(target.platform))
    .filter((platform) => selectedPlatformIds.includes(platform) && AUTO_PUBLISH_PLATFORMS.has(platform));
  const manualPublishCards = materialCards.filter(
    (card) =>
      selectedPlatformIds.includes(card.platform)
      && !AUTO_PUBLISH_PLATFORMS.has(card.platform)
      && (card.status === "manual_handoff" || Boolean(compactCopy(card.manual_publish_entry_url || card.login_url))),
  );

  useEffect(() => {
    setPublicationPlatformOptions({});
    setMaterialsPrepared(false);
    setSelectedMaterialPlatform("");
    setCopyMessage("");
    setActiveMaterialTaskId("");
  }, [publicationDraftContextKey]);

  useEffect(() => {
    if (!activeMaterialTask) return;
    void queryClient.invalidateQueries({ queryKey: publicationQueryKey });
    if (isTerminalMaterialTaskStatus(activeMaterialTask.status)) {
      setMaterialsPrepared(true);
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
    }
  }, [activeMaterialTask?.id, activeMaterialTask?.updated_at, activeMaterialTask?.status]);

  useEffect(() => {
    if (!platformChoices.length) {
      setSelectedPlatformIds([]);
      return;
    }
    setSelectedPlatformIds((current) => {
      const available = new Set(platformChoices.map((item) => item.platform));
      const kept = current.filter((platform) => available.has(platform));
      return kept.length ? kept : platformChoices.map((item) => item.platform);
    });
  }, [platformChoices]);

  useEffect(() => {
    if (!materialCards.length) {
      setSelectedMaterialPlatform("");
      return;
    }
    setSelectedMaterialPlatform((current) =>
      current && materialCards.some((card) => card.platform === current) ? current : materialCards[0].platform,
    );
  }, [materialCards]);

  useEffect(() => {
    const targetPlatforms = new Set(platformChoices.map((item) => item.platform));
    setPublicationPlatformOptions((current) => {
      const next = Object.fromEntries(Object.entries(current).filter(([platform]) => targetPlatforms.has(platform)));
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [platformChoices]);

  const updatePublicationPlatformOption = (platform: string, patch: Partial<PublicationPlatformOptionDraft>) => {
    setPublicationPlatformOptions((current) => {
      const currentOption = current[platform] ?? createEmptyPublicationPlatformOption();
      return {
        ...current,
        [platform]: { ...currentOption, ...patch },
      };
    });
  };

  const publishMutation = useMutation({
    mutationFn: () =>
      api.publishJob(job.id, {
        creator_profile_id: requestPublicationProfileId,
        platforms: autoPublishPlatformIds,
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (data) => {
      queryClient.setQueryData(publicationQueryKey, data);
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const prepareMaterialsMutation = useMutation({
    mutationFn: () =>
      api.createJobPublicationMaterialTask(job.id, {
        creator_profile_id: requestPublicationProfileId,
        platforms: selectedPlatformIds,
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (data) => {
      setActiveMaterialTaskId(data.id);
      queryClient.setQueryData(["job-publication-material-task", data.id], data);
      setMaterialsPrepared(false);
      await queryClient.invalidateQueries({ queryKey: publicationQueryKey });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  const materialGenerationActive = prepareMaterialsMutation.isPending || materialTaskRunning;
  const materialGenerationProgress = prepareMaterialsMutation.isPending && !activeMaterialTask
    ? 1
    : activeMaterialTaskProgress;

  const runOneClickPublish = () => {
    manualPublishCards.forEach((card) => openPublicationEntry(card));
    if (autoPublishPlatformIds.length) {
      publishMutation.mutate();
    }
  };

  return (
    <section className="form-stack">
      <div className="toolbar">
        <div>
          <strong>发布到创作者卡片绑定平台</strong>
          <div className="muted compact-top">{job.source_name}</div>
        </div>
        <span className={`status-pill ${publicationPlanStatus === "ready" ? "done" : "pending"}`}>
          {publicationPlanStatus === "ready" ? "可发布" : manualHandoffReady ? "人工接管" : "待补齐"}
        </span>
      </div>

      <div className="publication-stage-strip compact-top" aria-label="发布阶段">
        <span className={`publication-stage ${materialsPrepared || materialCards.length ? "done" : "active"}`}>1 生成物料</span>
        <span className={`publication-stage ${materialsPrepared ? "active" : ""}`}>2 发布</span>
      </div>

      <div className="publication-config-panel compact-top">
        <label className="publication-profile-field">
          <span>创作者卡片</span>
          <select
            className="input"
            value={selectedPublicationProfileId}
            onChange={(event) => setSelectedPublicationProfileId(event.target.value)}
            disabled={!job.creator_card_id && !publicationProfiles.length}
          >
            {job.creator_card_id ? (
              <option value={JOB_BOUND_PUBLICATION_PROFILE_ID}>
                {jobBoundCreatorLabel(job, publicationPlan.data)}
              </option>
            ) : (
              <option value={JOB_UNBOUND_PUBLICATION_PROFILE_ID}>未绑定创作者</option>
            )}
            {publicationProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.display_name}
              </option>
            ))}
          </select>
        </label>

        <div className="publication-platform-field">
          <div className="publication-config-head">
            <div>
              <strong>生成物料平台</strong>
              <div className="muted compact-top">按创作者绑定账号生成，选择会保留到本次发布。</div>
            </div>
            <div className="toolbar">
              <button
                className="button secondary"
                type="button"
                disabled={!platformChoices.length}
                onClick={() => setSelectedPlatformIds(platformChoices.map((item) => item.platform))}
              >
                全选
              </button>
              {publicationCredentialsMissing ? (
                <Link className="button secondary" to={PUBLICATION_CREDENTIALS_ROUTE}>
                  配置发布凭据
                </Link>
              ) : null}
            </div>
          </div>
          {platformChoices.length ? (
            <div className="publication-platform-picker compact-top">
              {platformChoices.map((item) => (
                <label key={item.platform} className={selectedPlatformIds.includes(item.platform) ? "selected" : ""}>
                  <input
                    type="checkbox"
                    checked={selectedPlatformIds.includes(item.platform)}
                    onChange={(event) => {
                      setSelectedPlatformIds((current) =>
                        event.target.checked
                          ? Array.from(new Set([...current, item.platform]))
                          : current.filter((platform) => platform !== item.platform),
                      );
                    }}
                  />
                  <span>{item.label}</span>
                </label>
              ))}
            </div>
          ) : isLoadingMaterialPlan ? (
            <div className="muted compact-top">正在补齐可选平台，生成物料可先用默认平台集。</div>
          ) : (
            <div className="toolbar compact-top">
              <div className="muted">当前创作者卡片没有启用的平台凭据。</div>
              <Link className="button ghost button-sm" to={PUBLICATION_CREDENTIALS_ROUTE}>
                去配置
              </Link>
            </div>
          )}
        </div>
      </div>

      {avatarMaterials.isLoading ? <div className="muted compact-top">正在载入创作者卡片...</div> : null}
      {isLoadingMaterialPlan ? <div className="muted compact-top">正在补齐物料详情，平台可先选择。</div> : null}
      {materialGenerationActive || activeMaterialTask ? (
        <article className="activity-card compact-top">
          <div className="toolbar">
            <div>
              <strong>{materialGenerationActive ? "物料生成中" : "物料生成任务"}</strong>
              <div className="muted compact-top">
                {activeMaterialTask?.message || (prepareMaterialsMutation.isPending ? "正在创建物料生成任务。" : "等待任务状态更新。")}
              </div>
            </div>
            <span className={`status-pill ${materialGenerationActive ? "running" : activeMaterialTask?.status === "failed" ? "failed" : "done"}`}>
              {materialGenerationActive ? `${materialGenerationProgress}%` : activeMaterialTask?.status || "完成"}
            </span>
          </div>
          <div
            className={`progress-bar compact-top${materialGenerationActive ? " is-animated" : ""}`}
            role="progressbar"
            aria-label="物料生成进度"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={materialGenerationProgress}
          >
            <span style={{ width: `${materialGenerationProgress}%` }} />
          </div>
          <div className="muted compact-top">
            {activeMaterialTask?.stage ? `当前阶段：${activeMaterialTask.stage}` : "正在启动生成流程"}
            {materialCards.length ? ` · 已显示 ${materialCards.length} 个平台物料` : " · 物料会在生成后逐步显示"}
          </div>
        </article>
      ) : null}
      {publicationPlan.data?.blocked_reasons?.length ? (
        <div className="list-stack compact-top">
          {publicationPlan.data.blocked_reasons.map((reason) => (
            <div key={reason} className="notice">{reason}</div>
          ))}
        </div>
      ) : null}
      {publicationPlan.data?.warnings?.length ? (
        <div className="list-stack compact-top">
          {publicationPlan.data.warnings.map((warning) => (
            <div key={warning} className="activity-card">{warning}</div>
          ))}
        </div>
      ) : null}
      {publicationExecutorPreflightMessages.length ? (
        <div className="list-stack compact-top">
          {publicationExecutorPreflightMessages.map((message) => (
            <div key={message} className="activity-card">{message}</div>
          ))}
        </div>
      ) : null}
      {manualHandoffTargets.length ? (
        <div className="list-stack compact-top">
          {manualHandoffTargets.map((target) => (
            <article className="activity-card" key={`${target.platform}-${target.login_url || "manual"}`}>
              <div className="toolbar">
                <div>
                  <strong>{target.label || target.platform}</strong>
                  <div className="muted compact-top">{target.reason || "该平台需人工登录后继续发布。"}</div>
                </div>
                {target.login_url ? (
                  <button type="button" className="button secondary" onClick={() => openManualHandoffTarget(target)}>
                    打开登录页
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {materialCards.length || isLoadingMaterialPlan ? (
        <div className="publication-material-layout compact-top">
          <div className="publication-material-card-list">
            {materialCards.length ? materialCards.map((card) => (
              <button
                type="button"
                key={card.platform}
                className={`publication-material-card${selectedMaterialCard?.platform === card.platform ? " selected" : ""}`}
                onClick={() => setSelectedMaterialPlatform(card.platform)}
              >
                <strong>{card.platform_label}</strong>
                <span>{materialStatusLabel(card)}</span>
                <small>{card.cover_path ? "有封面" : "缺封面"}</small>
              </button>
            )) : platformChoices.map((item) => (
              <button
                type="button"
                key={item.platform}
                className="publication-material-card loading"
                disabled
              >
                <strong>{item.label}</strong>
                <span>正在补齐物料</span>
                <small>文案和封面载入中</small>
              </button>
            ))}
          </div>
          {selectedMaterialCard ? (
            <article className="activity-card publication-material-detail">
              <div className="toolbar">
                <div>
                  <strong>{selectedMaterialCard.platform_label} 物料详情</strong>
                  <div className="muted compact-top">{selectedMaterialCard.account_label || selectedMaterialCard.adapter || "未绑定账号"}</div>
                </div>
                {!AUTO_PUBLISH_PLATFORMS.has(selectedMaterialCard.platform)
                && compactCopy(selectedMaterialCard.manual_publish_entry_url || selectedMaterialCard.login_url) ? (
                  <button type="button" className="button secondary" onClick={() => openPublicationEntry(selectedMaterialCard)}>
                    打开发送页
                  </button>
                ) : null}
              </div>
              <PublicationMaterialCoverPreview card={selectedMaterialCard} />
              {materialPublishProjectLabels(selectedMaterialCard).length ? (
                <div className="publication-material-specs compact-top">
                  <div className="publication-material-spec-row">
                    <span>项目</span>
                    <strong>{materialPublishProjectLabels(selectedMaterialCard).join(" / ")}</strong>
                  </div>
                  <div className="publication-material-spec-row">
                    <span>字段</span>
                    <strong>
                      {[
                        materialHasTitle(selectedMaterialCard) ? materialTitleLabel(selectedMaterialCard) : "",
                        materialBodyLabel(selectedMaterialCard),
                        materialHasSeparateTags(selectedMaterialCard) ? materialTagLabel(selectedMaterialCard) : "",
                      ].filter(Boolean).join(" / ")}
                    </strong>
                  </div>
                </div>
              ) : null}
              {materialHasTitle(selectedMaterialCard) ? (
                <PublicationMaterialCopyRow
                  label={materialTitleLabel(selectedMaterialCard)}
                  value={selectedMaterialCard.title}
                  onCopy={(value) =>
                    copyText(value, `${selectedMaterialCard.platform_label} ${materialTitleLabel(selectedMaterialCard)}已复制`, setCopyMessage)
                  }
                />
              ) : null}
              <PublicationMaterialCopyRow
                label={materialBodyLabel(selectedMaterialCard)}
                value={selectedMaterialCard.body || selectedMaterialCard.description}
                onCopy={(value) =>
                  copyText(value, `${selectedMaterialCard.platform_label} ${materialBodyLabel(selectedMaterialCard)}已复制`, setCopyMessage)
                }
              />
              {materialHasSeparateTags(selectedMaterialCard) ? (
                <PublicationMaterialCopyRow
                  label={materialTagLabel(selectedMaterialCard)}
                  value={tagsCopy(selectedMaterialCard.tags)}
                  onCopy={(value) =>
                    copyText(value, `${selectedMaterialCard.platform_label} ${materialTagLabel(selectedMaterialCard)}已复制`, setCopyMessage)
                  }
                />
              ) : null}
              <PublicationMaterialCopyRow
                label="封面"
                value={selectedMaterialCard.cover_path}
                onCopy={(value) => copyText(value, `${selectedMaterialCard.platform_label} 封面路径已复制`, setCopyMessage)}
              />
              <PublicationMaterialCopyRow
                label="整套文案"
                value={fullCopyFromMaterial(selectedMaterialCard)}
                multiline
                onCopy={(value) => copyText(value, `${selectedMaterialCard.platform_label} 整套文案已复制`, setCopyMessage)}
              />
              <div className="form-grid two-up compact-top">
                <label>
                  <span>定时发布</span>
                  <input
                    className="input"
                    type="datetime-local"
                    value={publicationPlatformOptions[selectedMaterialCard.platform]?.scheduled_publish_at ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(selectedMaterialCard.platform, { scheduled_publish_at: event.target.value })
                    }
                  />
                </label>
                <label>
                  <span>发布模式</span>
                  <select
                    className="input"
                    value={publicationPlatformOptions[selectedMaterialCard.platform]?.visibility_or_publish_mode ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(selectedMaterialCard.platform, { visibility_or_publish_mode: event.target.value })
                    }
                  >
                    <option value="">立即/默认</option>
                    <option value="scheduled">预约发布</option>
                    <option value="draft">仅创建草稿</option>
                    <option value="private">仅自己可见</option>
                  </select>
                </label>
                <label>
                  <span>合集/栏目 ID</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[selectedMaterialCard.platform]?.collection_id ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(selectedMaterialCard.platform, { collection_id: event.target.value })
                    }
                    placeholder="可选，平台合集或栏目 ID"
                  />
                </label>
                <label>
                  <span>合集/栏目名称</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[selectedMaterialCard.platform]?.collection_name ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(selectedMaterialCard.platform, { collection_name: event.target.value })
                    }
                    placeholder="可选，给发布运行器定位 UI"
                  />
                </label>
                <label>
                  <span>平台分类</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[selectedMaterialCard.platform]?.category ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(selectedMaterialCard.platform, { category: event.target.value })
                    }
                    placeholder="可选，例如 数码 / 装备"
                  />
                </label>
              </div>
              {copyMessage ? <div className="muted compact-top">{copyMessage}</div> : null}
            </article>
          ) : (
            <article className="activity-card publication-material-detail">
              <div className="toolbar">
                <div>
                  <strong>物料详情正在补齐</strong>
                  <div className="muted compact-top">正在从已生成文件索引平台文案和封面，平台选择可先调整。</div>
                </div>
              </div>
              <div className="publication-cover-preview-empty muted">封面预览载入中</div>
            </article>
          )}
        </div>
      ) : null}
      {prepareMaterialsMutation.error ? <div className="notice compact-top">{String(prepareMaterialsMutation.error)}</div> : null}
      {publishMutation.error ? <div className="notice compact-top">{String(publishMutation.error)}</div> : null}
      {publicationPlan.data?.existing_attempts?.length ? (
        <div className="timeline-list top-gap">
          {publicationPlan.data.existing_attempts.slice(0, 6).map((attempt) => (
            <div className="timeline-item" key={attempt.id}>
              <div className="toolbar">
                <strong>{attempt.platform_label || attempt.platform}</strong>
                <span className={`status-pill ${attempt.status === "failed" ? "failed" : attempt.status === "published" ? "done" : "running"}`}>
                  {publicationAttemptStatusLabel(attempt.status)}
                </span>
              </div>
              <div className="muted">
                {attempt.account_label} · {attempt.operator_summary || attempt.run_status || "等待运行器处理"}
              </div>
              {publicationAttemptReceiptId(attempt) ? (
                <div className="muted" title={publicationAttemptReceiptId(attempt)}>
                  回执：{publicationAttemptReceiptId(attempt)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <div className="toolbar top-gap">
        <button className="button ghost" type="button" onClick={onCancel}>
          取消
        </button>
        {manualHandoffTargets.length ? (
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              manualHandoffTargets.forEach((target) => {
                openManualHandoffTarget(target);
              });
            }}
          >
            打开人工登录页
          </button>
        ) : null}
        <button
          className="button secondary"
          type="button"
          disabled={!selectedPlatformIds.length || materialGenerationActive}
          onClick={() => prepareMaterialsMutation.mutate()}
        >
          {materialGenerationActive ? "生成中..." : materialCards.length ? "重新生成物料" : "生成物料"}
        </button>
        {materialsPrepared || materialCards.length ? (
          <button
            className="button primary"
            type="button"
            disabled={materialGenerationActive || publishMutation.isPending || (!autoPublishPlatformIds.length && !manualPublishCards.length)}
            onClick={runOneClickPublish}
          >
            {publishMutation.isPending ? "提交中..." : "一键发布"}
          </button>
        ) : null}
      </div>
    </section>
  );
}

function PublicationMaterialCoverPreview({ card }: { card: PublicationMaterialCard }) {
  const previews = materialCoverPreviews(card);
  if (!previews.length) {
    return <div className="publication-cover-preview-empty muted">暂无封面预览</div>;
  }
  return (
    <div className="publication-cover-preview-grid">
      {previews.map((preview) => (
        <figure className="publication-cover-preview" key={preview.key}>
          <img src={localImagePreviewUrl(preview.path, card.status || card.platform)} alt={`${card.platform_label} ${preview.label}`} loading="lazy" />
          <figcaption>{preview.label}</figcaption>
        </figure>
      ))}
    </div>
  );
}

function PublicationMaterialCopyRow({
  label,
  value,
  multiline = false,
  onCopy,
}: {
  label: string;
  value?: string | null;
  multiline?: boolean;
  onCopy: (value: string) => void;
}) {
  const text = compactCopy(value, "暂无");
  return (
    <div className={`publication-copy-row${multiline ? " multiline" : ""}`}>
      <span>{label}</span>
      <code title={text}>{text}</code>
      <button type="button" className="button ghost button-sm" onClick={() => onCopy(compactCopy(value))}>
        复制
      </button>
    </div>
  );
}
