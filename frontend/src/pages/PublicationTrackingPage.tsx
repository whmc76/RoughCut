import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  Clipboard,
  ExternalLink,
  FileCheck2,
  Filter,
  FolderOpen,
  Link2,
  PlaySquare,
  Save,
  Search,
  X,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { EmptyState } from "../components/ui/EmptyState";
import { PanelHeader } from "../components/ui/PanelHeader";
import { normalizeIntelligentCopyPlatformId } from "../features/intelligentCopy/useIntelligentCopyWorkspace";
import {
  publicationAttemptReceiptId,
  publicationAttemptUrl,
} from "../features/publication/publicationAttempt";
import type {
  IntelligentCopyGenerateTask,
  Job,
  ManualHandoffTarget,
  PublicationAttempt,
  PublicationEntryOpenRequest,
  PublicationPlan,
  PublicationTarget,
} from "../types";
import { writeTextToClipboard } from "../utils/clipboard";

type PlatformRow = {
  key: string;
  label: string;
  accountLabel: string;
  material: PublicationTarget | null;
  target: PublicationTarget | null;
  manualTarget: ManualHandoffTarget | null;
  attempt: PublicationAttempt | null;
};

type BackfillDraft = {
  publicUrl: string;
  receiptId: string;
  postId: string;
};

type PublicationTimeFilter = "all" | "today" | "three_days" | "seven_days";
type PublicationClipTypeFilter = NonNullable<Job["queue_task_kind"]>;

type PublicationFilterOption = {
  key: string;
  label: string;
  count: number;
};

const DEFAULT_PLATFORM_ENTRY_URLS: Record<string, string> = {
  bilibili: "https://member.bilibili.com/platform/upload/video/frame",
  douyin: "https://creator.douyin.com/creator-micro/content/upload",
  kuaishou: "https://cp.kuaishou.com/article/publish/video",
  toutiao: "https://mp.toutiao.com/profile_v4/xigua/upload-video?index=0",
  "wechat-channels": "https://channels.weixin.qq.com/platform/post/create",
  xiaohongshu: "https://creator.xiaohongshu.com/publish",
  youtube: "https://studio.youtube.com/",
  x: "https://x.com/compose/post",
};

const PLATFORM_LABELS: Record<string, string> = {
  bilibili: "B站",
  douyin: "抖音",
  kuaishou: "快手",
  toutiao: "头条号",
  "wechat-channels": "视频号",
  xiaohongshu: "小红书",
  youtube: "YouTube",
  x: "X",
};

const TITLELESS_PLATFORM_KEYS = new Set(["kuaishou", "wechat-channels", "x"]);

const PUBLICATION_CLIP_TYPE_LABELS: Record<PublicationClipTypeFilter, string> = {
  edit: "常规剪辑",
  publication: "发布任务",
  remix_production: "混剪制作",
  smart_director: "智能导演",
};

const PUBLICATION_TIME_FILTERS: Array<{ key: PublicationTimeFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "today", label: "今天" },
  { key: "three_days", label: "最近三天" },
  { key: "seven_days", label: "七天" },
];

export function PublicationTrackingPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const routeJobId = searchParams.get("job") ?? "";
  const [selectedJobId, setSelectedJobId] = useState(routeJobId);
  const [selectedPlatformKeys, setSelectedPlatformKeys] = useState<string[]>([]);
  const [expandedPlatformKeys, setExpandedPlatformKeys] = useState<string[]>([]);
  const [platformSelectionOwnerJobId, setPlatformSelectionOwnerJobId] = useState("");
  const [platformSelectionHint, setPlatformSelectionHint] = useState("默认全平台");
  const [drafts, setDrafts] = useState<Record<string, BackfillDraft>>({});
  const [jobSearch, setJobSearch] = useState("");
  const [videoFiltersExpanded, setVideoFiltersExpanded] = useState(true);
  const [selectedCreatorFilters, setSelectedCreatorFilters] = useState<string[]>([]);
  const [selectedClipTypeFilters, setSelectedClipTypeFilters] = useState<PublicationClipTypeFilter[]>([]);
  const [selectedTimeFilter, setSelectedTimeFilter] = useState<PublicationTimeFilter>("all");
  const [copyFeedback, setCopyFeedback] = useState("");
  const [activeMaterialTaskId, setActiveMaterialTaskId] = useState("");

  const jobs = useQuery({
    queryKey: ["jobs", "publication-tracking"],
    queryFn: () => api.listJobs(100),
    refetchInterval: 8_000,
  });

  const candidateJobs = useMemo(
    () => (jobs.data ?? []).filter(isPublicationCandidate),
    [jobs.data],
  );
  const creatorFilterOptions = useMemo(
    () => buildPublicationFilterOptions(candidateJobs, jobCreatorFilterKey, jobCreatorFilterLabel),
    [candidateJobs],
  );
  const clipTypeFilterOptions = useMemo(
    () => buildPublicationFilterOptions(candidateJobs, jobClipTypeFilterKey, jobClipTypeFilterLabel),
    [candidateJobs],
  );
  const activeVideoFilterCount = selectedCreatorFilters.length
    + selectedClipTypeFilters.length
    + (selectedTimeFilter === "all" ? 0 : 1);
  const filteredJobs = useMemo(() => {
    const query = jobSearch.trim().toLowerCase();
    const creatorFilterSet = new Set(selectedCreatorFilters);
    const clipTypeFilterSet = new Set(selectedClipTypeFilters);
    return candidateJobs.filter((job) => {
      if (creatorFilterSet.size && !creatorFilterSet.has(jobCreatorFilterKey(job))) return false;
      if (clipTypeFilterSet.size && !clipTypeFilterSet.has(jobClipTypeFilterKey(job))) return false;
      if (!matchesPublicationTimeFilter(job, selectedTimeFilter)) return false;
      if (!query) return true;
      return [
        job.source_name,
        job.content_subject,
        job.content_summary,
        job.publication_summary,
        job.creator_card_name,
        job.status,
      ].join(" ").toLowerCase().includes(query);
    });
  }, [candidateJobs, jobSearch, selectedClipTypeFilters, selectedCreatorFilters, selectedTimeFilter]);

  useEffect(() => {
    if (!candidateJobs.length) {
      setSelectedJobId("");
      return;
    }
    if (routeJobId && candidateJobs.some((job) => job.id === routeJobId)) {
      setSelectedJobId(routeJobId);
      return;
    }
    if (!selectedJobId || !candidateJobs.some((job) => job.id === selectedJobId)) {
      setSelectedJobId(candidateJobs[0]?.id ?? "");
    }
  }, [candidateJobs, routeJobId, selectedJobId]);

  const selectedJob = candidateJobs.find((job) => job.id === selectedJobId) ?? null;
  const publicationPlanQueryKey = ["job-publication-plan", selectedJobId] as const;
  const publicationPlan = useQuery({
    queryKey: publicationPlanQueryKey,
    queryFn: () => api.getJobPublicationPlan(selectedJobId),
    enabled: Boolean(selectedJobId),
    refetchInterval: (query) => hasActivePublicationAttempt(query.state.data?.existing_attempts) ? 1_500 : 8_000,
  });
  const materialTask = useQuery<IntelligentCopyGenerateTask>({
    queryKey: ["job-publication-material-task", activeMaterialTaskId],
    queryFn: () => api.getIntelligentCopyGenerateTask(activeMaterialTaskId),
    enabled: Boolean(activeMaterialTaskId),
    refetchInterval: (query) => (isTerminalMaterialTaskStatus(query.state.data?.status) ? false : 1_000),
  });
  const recentPublicationAttempts = useQuery({
    queryKey: ["intelligent-publication-attempts", "recent"],
    queryFn: () => api.getRecentPublicationAttempts(48),
    refetchInterval: (query) => hasActivePublicationAttempt(query.state.data?.attempts) ? 1_500 : 8_000,
  });

  const plan = publicationPlan.data ?? null;
  const visibleAttempts = useMemo(() => {
    const jobAttempts = (recentPublicationAttempts.data?.attempts ?? []).filter(
      (attempt) => attempt.job_id === selectedJobId || attempt.content_id === selectedJobId,
    );
    return mergeAttempts([...(plan?.existing_attempts ?? []), ...jobAttempts]);
  }, [plan?.existing_attempts, recentPublicationAttempts.data?.attempts, selectedJobId]);
  const platformRows = useMemo(
    () => buildPlatformRows(
      plan?.material_targets ?? [],
      plan?.targets ?? [],
      plan?.manual_handoff_targets ?? [],
      visibleAttempts,
      plan,
    ),
    [plan, visibleAttempts],
  );
  const selectedPlatformKeySet = useMemo(() => new Set(selectedPlatformKeys), [selectedPlatformKeys]);
  const visiblePlatformRows = useMemo(
    () => platformRows.filter((row) => selectedPlatformKeySet.has(row.key)),
    [platformRows, selectedPlatformKeySet],
  );
  const materialActionLabel = useMemo(
    () => publicationMaterialActionLabel(visiblePlatformRows),
    [visiblePlatformRows],
  );
  const activeMaterialTask = materialTask.data ?? null;
  const materialTaskRunning = Boolean(activeMaterialTask && !isTerminalMaterialTaskStatus(activeMaterialTask.status));
  const publishedCount = visibleAttempts.filter((attempt) => publicationAttemptUrl(attempt)).length;
  const pendingBackfillCount = visiblePlatformRows.filter((row) => row.material && !publicationAttemptUrl(row.attempt)).length;

  useEffect(() => {
    if (!selectedJobId) {
      setSelectedPlatformKeys((current) => (current.length ? [] : current));
      setExpandedPlatformKeys((current) => (current.length ? [] : current));
      setPlatformSelectionOwnerJobId("");
      setPlatformSelectionHint("等待平台计划");
      return;
    }
    if (!plan) {
      setPlatformSelectionHint("读取平台计划");
      return;
    }
    const keys = platformRows.map((row) => row.key);
    if (platformSelectionOwnerJobId !== selectedJobId) {
      if (!keys.length) {
        setSelectedPlatformKeys((current) => (current.length ? [] : current));
        setExpandedPlatformKeys((current) => (current.length ? [] : current));
        setPlatformSelectionHint("等待平台计划");
        return;
      }
      const initialSelection = resolveInitialPlatformSelection(platformRows, plan);
      setSelectedPlatformKeys(initialSelection.keys);
      setExpandedPlatformKeys(initialSelection.expandedKeys);
      setPlatformSelectionHint(initialSelection.label);
      setPlatformSelectionOwnerJobId(selectedJobId);
      return;
    }
    setSelectedPlatformKeys((current) => current.filter((key) => keys.includes(key)));
    setExpandedPlatformKeys((current) => current.filter((key) => keys.includes(key)));
  }, [plan, platformRows, platformSelectionOwnerJobId, selectedJobId]);

  const selectJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setSelectedPlatformKeys([]);
    setExpandedPlatformKeys([]);
    setPlatformSelectionOwnerJobId("");
    setPlatformSelectionHint("默认全平台");
    setActiveMaterialTaskId("");
    setDrafts({});
    setSearchParams(jobId ? { job: jobId } : {});
  };

  const prepareMaterials = useMutation({
    mutationFn: () => {
      if (!selectedJobId) throw new Error("请先选择一个发布任务。");
      const requestedPlatforms = visiblePlatformRows.map((row) => row.key);
      if (!requestedPlatforms.length) throw new Error("请先选择要生成物料的平台。");
      return api.createJobPublicationMaterialTask(selectedJobId, {
        creator_profile_id: plan?.creator_profile_id || null,
        platforms: requestedPlatforms,
        platform_options: plan?.platform_options ?? {},
      });
    },
    onSuccess: async (payload) => {
      setActiveMaterialTaskId(payload.id);
      queryClient.setQueryData(["job-publication-material-task", payload.id], payload);
      await queryClient.invalidateQueries({ queryKey: ["job-publication-plan"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const materialGenerationActive = prepareMaterials.isPending || materialTaskRunning;
  const materialGenerationProgress = prepareMaterials.isPending && !activeMaterialTask ? 1 : materialTaskProgress(activeMaterialTask);

  useEffect(() => {
    if (!activeMaterialTask || !isTerminalMaterialTaskStatus(activeMaterialTask.status)) return;
    void queryClient.invalidateQueries({ queryKey: ["job-publication-plan"] });
    void queryClient.invalidateQueries({ queryKey: ["jobs"] });
  }, [activeMaterialTask?.id, activeMaterialTask?.status, activeMaterialTask?.updated_at, queryClient]);

  const backfill = useMutation({
    mutationFn: (payload: {
      platform: string;
      publicUrl: string;
      receiptId: string;
      postId: string;
    }) => {
      if (!selectedJobId) throw new Error("请先选择一个发布任务。");
      return api.backfillJobManualPublicationResult(selectedJobId, {
        creator_profile_id: plan?.creator_profile_id || null,
        platform: payload.platform,
        public_url: payload.publicUrl,
        receipt_id: payload.receiptId,
        post_id: payload.postId,
      });
    },
    onSuccess: async (attempt) => {
      if (attempt?.platform) {
        setDrafts((current) => ({
          ...current,
          [normalizeIntelligentCopyPlatformId(attempt.platform)]: buildDraftFromAttempt(attempt),
        }));
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["intelligent-publication-attempts"] }),
        queryClient.invalidateQueries({ queryKey: ["job-publication-plan"] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
      ]);
    },
  });

  const openJobFolder = useMutation({
    mutationFn: () => {
      if (!selectedJobId) throw new Error("请先选择一个发布任务。");
      return api.openJobFolder(selectedJobId);
    },
  });
  const openPublicationEntry = useMutation({
    mutationFn: (payload: PublicationEntryOpenRequest) => api.openPublicationEntry(payload),
  });

  const updateDraft = (platform: string, patch: Partial<BackfillDraft>, attempt?: PublicationAttempt | null) => {
    setDrafts((current) => ({
      ...current,
      [platform]: {
        ...(current[platform] ?? buildDraftFromAttempt(attempt)),
        ...patch,
      },
    }));
  };

  const togglePlatformSelection = (platform: string) => {
    setPlatformSelectionHint("手动选择");
    setSelectedPlatformKeys((current) => {
      const next = current.includes(platform)
        ? current.filter((item) => item !== platform)
        : [...current, platform];
      setExpandedPlatformKeys((currentExpanded) => {
        return currentExpanded.filter((item) => next.includes(item));
      });
      return next;
    });
  };

  const togglePlatformExpansion = (platform: string) => {
    setExpandedPlatformKeys((current) => {
      return current.includes(platform)
        ? current.filter((item) => item !== platform)
        : [...current, platform];
    });
  };

  const selectAllPlatforms = () => {
    setPlatformSelectionHint("手动全选");
    const next = platformRows.map((row) => row.key);
    setSelectedPlatformKeys(next);
    setExpandedPlatformKeys((current) => current.filter((key) => next.includes(key)));
  };

  const clearSelectedPlatforms = () => {
    setPlatformSelectionHint("手动清空");
    setSelectedPlatformKeys([]);
    setExpandedPlatformKeys([]);
  };

  const toggleCreatorFilter = (creatorKey: string) => {
    setSelectedCreatorFilters((current) =>
      current.includes(creatorKey) ? current.filter((key) => key !== creatorKey) : [...current, creatorKey],
    );
  };

  const toggleClipTypeFilter = (clipType: PublicationClipTypeFilter) => {
    setSelectedClipTypeFilters((current) =>
      current.includes(clipType) ? current.filter((key) => key !== clipType) : [...current, clipType],
    );
  };

  const clearVideoFilters = () => {
    setSelectedCreatorFilters([]);
    setSelectedClipTypeFilters([]);
    setSelectedTimeFilter("all");
    setJobSearch("");
  };

  const previewUrl = selectedJob ? api.jobRenderedFileUrl(selectedJob.id, "auto") : "";

  return (
    <section className="page-stack publication-tracking-page">
      <header className="publication-tracking-compact-header">
        <div>
          <span>工作流 / 发布跟踪</span>
          <strong>{selectedJob?.source_name || "选择成片后开始发布"}</strong>
        </div>
        <div className="publication-tracking-compact-stats" aria-label="发布跟踪状态">
          <span>{candidateJobs.length} 个待跟踪</span>
          <span>{selectedPlatformKeys.length || 0}/{platformRows.length || 0} 平台</span>
          <span>{pendingBackfillCount} 待回填</span>
          <span>{publishedCount} 已发布</span>
          <span>{platformSelectionHint}</span>
        </div>
        <Link className="button ghost button-sm" to="/publication-management">
          配置账号
        </Link>
      </header>

      <div className="publication-console-grid">
        <section className="panel publication-video-picker">
          <PanelHeader
            title="选择待发布视频"
            description="从已完成或发布中的真实作业中选择，后续平台物料和回填记录都绑定到该 job。"
            actions={<span className="mode-chip subtle">{jobs.isLoading ? "读取中" : `${filteredJobs.length} 条`}</span>}
          />
          <label className="publication-video-search">
            <Search size={15} aria-hidden="true" />
            <input
              className="input"
              value={jobSearch}
              onChange={(event) => setJobSearch(event.target.value)}
              placeholder="搜索成片 / 作业 / 创作者"
            />
          </label>
          <div className={`publication-video-filter-panel${videoFiltersExpanded ? " expanded" : ""}`}>
            <button
              type="button"
              className="publication-video-filter-toggle"
              aria-expanded={videoFiltersExpanded}
              onClick={() => setVideoFiltersExpanded((current) => !current)}
            >
              <Filter size={15} aria-hidden="true" />
              <span>
                <strong>标签筛选</strong>
                <small>
                  {activeVideoFilterCount
                    ? `${activeVideoFilterCount} 项已启用 · ${filteredJobs.length}/${candidateJobs.length}`
                    : "创作者 / 剪辑类型 / 时间"}
                </small>
              </span>
              <ChevronDown size={16} aria-hidden="true" />
            </button>
            {videoFiltersExpanded ? (
              <div className="publication-video-filter-body">
                <PublicationFilterGroup
                  title="创作者"
                  emptyLabel="暂无创作者"
                  options={creatorFilterOptions}
                  selectedKeys={selectedCreatorFilters}
                  onToggle={toggleCreatorFilter}
                />
                <PublicationFilterGroup
                  title="剪辑类型"
                  emptyLabel="暂无类型"
                  options={clipTypeFilterOptions}
                  selectedKeys={selectedClipTypeFilters}
                  onToggle={(key) => toggleClipTypeFilter(key as PublicationClipTypeFilter)}
                />
                <div className="publication-filter-group">
                  <div className="publication-filter-group-head">
                    <strong>时间</strong>
                    <span>{selectedTimeFilter === "all" ? "不限" : PUBLICATION_TIME_FILTERS.find((item) => item.key === selectedTimeFilter)?.label}</span>
                  </div>
                  <div className="publication-time-filter-strip" aria-label="发布时间过滤">
                    {PUBLICATION_TIME_FILTERS.map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        className={`publication-filter-chip${selectedTimeFilter === item.key ? " selected" : ""}`}
                        aria-pressed={selectedTimeFilter === item.key}
                        onClick={() => setSelectedTimeFilter(item.key)}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="publication-video-filter-footer">
                  <span>{filteredJobs.length} 条匹配</span>
                  <button
                    type="button"
                    className="button ghost button-sm"
                    disabled={!activeVideoFilterCount && !jobSearch.trim()}
                    onClick={clearVideoFilters}
                  >
                    <X size={14} aria-hidden="true" />
                    清除筛选
                  </button>
                </div>
              </div>
            ) : null}
          </div>
          <div className="publication-video-list" aria-label="待发布视频">
            {filteredJobs.length ? (
              filteredJobs.slice(0, 20).map((job) => (
                <button
                  key={job.id}
                  type="button"
                  className={`publication-video-item${job.id === selectedJobId ? " selected" : ""}`}
                  onClick={() => selectJob(job.id)}
                >
                  <span className={`status-pill ${job.publication_status === "published" || job.status === "published" ? "done" : "running"}`}>
                    {job.publication_status === "published" || job.status === "published" ? "已发布" : "待发布"}
                  </span>
                  <strong>{job.source_name}</strong>
                  <small>{formatDateTime(job.updated_at)} · {job.creator_card_name || job.status}</small>
                </button>
              ))
            ) : (
              <EmptyState message="暂无真实待发布作业。请先完成成片审看，或在制片队列生成发布物料。" />
            )}
          </div>
        </section>

        <div className="publication-console-main">
          <section className="panel publication-flow-strip" aria-label="半手动发布流程">
            <div>
              <FileCheck2 size={22} aria-hidden="true" />
              <strong>读取平台物料</strong>
              <span>只读取已生成平台包。</span>
            </div>
            <div>
              <ExternalLink size={22} aria-hidden="true" />
              <strong>打开发布页</strong>
              <span>在对应平台粘贴并完成发布。</span>
            </div>
            <div>
              <Link2 size={22} aria-hidden="true" />
              <strong>回填发布结果</strong>
              <span>保存公开视频链接或回执。</span>
            </div>
          </section>

          <section className="panel publication-platform-action-list">
            <PanelHeader
              title="发布平台与物料"
              description="勾选要处理的平台；平台条目展开后显示对应物料和回填栏。"
              actions={
                <button
                  type="button"
                  className="button primary publication-material-generate-button"
                  disabled={!selectedJobId || !visiblePlatformRows.length || materialGenerationActive || publicationPlan.isLoading}
                  onClick={() => prepareMaterials.mutate()}
                >
                  <FileCheck2 size={16} aria-hidden="true" />
                  {materialGenerationActive ? "生成中" : materialActionLabel}
                </button>
              }
            />
            {materialGenerationActive || activeMaterialTask ? (
              <div className="publication-material-task-status">
                <div>
                  <strong>{activeMaterialTask?.message || (prepareMaterials.isPending ? "正在创建智能物料生成任务。" : "等待任务状态更新。")}</strong>
                  <span>
                    {activeMaterialTask?.stage ? `当前阶段：${activeMaterialTask.stage}` : "智能生成物料链路"}
                    {activeMaterialTask ? ` · ${materialTaskDurationLabel(activeMaterialTask)}` : ""}
                  </span>
                </div>
                <span className={`status-pill ${materialGenerationActive ? "running" : activeMaterialTask?.status === "failed" ? "failed" : "done"}`}>
                  {materialGenerationActive ? `${materialGenerationProgress}%` : activeMaterialTask?.status || "完成"}
                </span>
              </div>
            ) : null}
            {platformRows.length ? (
              <>
                <div className="publication-platform-selector" aria-label="平台勾选">
                  <div className="publication-platform-selector-head">
                    <strong>平台勾选</strong>
                    <span>{selectedPlatformKeys.length ? `${platformSelectionHint} · 已选择 ${selectedPlatformKeys.length} 个` : "未选择平台"}</span>
                    <div className="toolbar">
                      <button type="button" className="button ghost button-sm" onClick={selectAllPlatforms}>
                        全选
                      </button>
                      <button type="button" className="button ghost button-sm" onClick={clearSelectedPlatforms}>
                        清空
                      </button>
                    </div>
                  </div>
                  <div className="publication-platform-checks">
                    {platformRows.map((row) => {
                      const materialStatus = platformMaterialStatus(row);
                      return (
                        <label key={row.key} className={`publication-platform-check${selectedPlatformKeySet.has(row.key) ? " selected" : ""}`}>
                          <input
                            type="checkbox"
                            checked={selectedPlatformKeySet.has(row.key)}
                            onChange={() => togglePlatformSelection(row.key)}
                          />
                          <span>
                            <strong>{row.label}</strong>
                            <small>{row.accountLabel || "未绑定账号"}</small>
                          </span>
                          <em className={`publication-platform-material-state ${materialStatus.tone}`}>{materialStatus.label}</em>
                        </label>
                      );
                    })}
                  </div>
                </div>

                {visiblePlatformRows.length ? (
                  <div className="publication-platform-list" aria-label="平台清单">
                    {visiblePlatformRows.map((row) => {
                      const rowUrl = publicationAttemptUrl(row.attempt);
                      const rowEntryUrl = platformEntryUrl(row);
                      const isExpanded = expandedPlatformKeys.includes(row.key);
                      const rowDraft = drafts[row.key] ?? buildDraftFromAttempt(row.attempt);
                      const rowTitle = platformTitle(row);
                      const rowBody = platformBody(row);
                      const rowTags = platformTags(row);
                      const rowCoverPath = platformCoverPath(row);
                      const hasTitle = platformHasTitle(row);
                      const hasSeparateTags = platformHasSeparateTags(row);
                      const publicationRuleRows = buildPublicationRuleRows(row);
                      return (
                        <article key={row.key} className={`publication-tracking-platform-card${isExpanded ? " expanded" : ""}`}>
                          <div
                            className="publication-tracking-platform-summary"
                            role="button"
                            tabIndex={0}
                            aria-expanded={isExpanded}
                            onClick={() => togglePlatformExpansion(row.key)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                togglePlatformExpansion(row.key);
                              }
                            }}
                          >
                            <button
                              type="button"
                              className="publication-tracking-platform-expand"
                              onClick={(event) => {
                                event.stopPropagation();
                                togglePlatformExpansion(row.key);
                              }}
                              aria-expanded={isExpanded}
                            >
                              <ChevronDown size={16} aria-hidden="true" />
                              <span>
                                <strong>{row.label}</strong>
                                <small>{row.accountLabel || "未绑定账号"}</small>
                              </span>
                            </button>
                            <span className={`status-pill ${rowUrl ? "done" : row.material ? "running" : "failed"}`}>
                              {rowUrl ? "已发布" : row.material ? "待回填" : "缺少物料"}
                            </span>
                            <div className="publication-platform-row-actions" onClick={(event) => event.stopPropagation()}>
                              <button
                                type="button"
                                className="button secondary button-sm"
                                disabled={!rowEntryUrl || openPublicationEntry.isPending}
                                onClick={() => openPublicationEntry.mutate(buildPublicationEntryOpenRequest(row, rowEntryUrl))}
                              >
                                <ExternalLink size={14} aria-hidden="true" />
                                打开发布页
                              </button>
                              <button type="button" className="button ghost button-sm" disabled={!selectedJobId || openJobFolder.isPending} onClick={() => openJobFolder.mutate()}>
                                <FolderOpen size={14} aria-hidden="true" />
                                打开文件夹
                              </button>
                            </div>
                            <span className={`publication-tracking-link-state ${rowUrl ? "has-link" : ""}`}>
                              {rowUrl ? "有跟踪链接" : "无跟踪链接"}
                            </span>
                          </div>
                          {isExpanded ? (
                            <div className="publication-platform-expanded">
                              {row.material ? (
                                <div className="publication-material-grid">
                                  {hasTitle ? (
                                    <CopyField label={platformTitleLabel(row)} value={rowTitle} onCopy={() => copyText(rowTitle, `${row.label} ${platformTitleLabel(row)}已复制`, setCopyFeedback)} />
                                  ) : null}
                                  <CopyField label={platformBodyLabel(row)} value={rowBody} multiline onCopy={() => copyText(rowBody, `${row.label} ${platformBodyLabel(row)}已复制`, setCopyFeedback)} />
                                  {hasSeparateTags ? (
                                    <CopyField label={platformTagLabel(row)} value={rowTags} onCopy={() => copyText(rowTags, `${row.label} ${platformTagLabel(row)}已复制`, setCopyFeedback)} />
                                  ) : null}
                                  <CopyField label="封面路径" value={rowCoverPath} onCopy={() => copyText(rowCoverPath, `${row.label} 封面路径已复制`, setCopyFeedback)} />
                                  {publicationRuleRows.map((item) => (
                                    <ReadonlyField key={`${row.key}-${item.label}`} label={item.label} value={item.value} />
                                  ))}
                                </div>
                              ) : (
                                <div className="publication-material-empty">
                                  <FileCheck2 size={18} aria-hidden="true" />
                                  <span>该平台还没有真实生成物料。</span>
                                </div>
                              )}
                              <div className="publication-backfill-box">
                                <div className="publication-backfill-head">
                                  <Link2 size={17} aria-hidden="true" />
                                  <strong>回填发布结果</strong>
                                  <span className="muted">平台发布完成后填写</span>
                                </div>
                                <label>
                                  <span>公开视频链接</span>
                                  <input
                                    className="input"
                                    value={rowDraft.publicUrl}
                                    onChange={(event) => updateDraft(row.key, { publicUrl: event.target.value }, row.attempt)}
                                    placeholder="https://..."
                                  />
                                </label>
                                <label>
                                  <span>回执 ID</span>
                                  <input
                                    className="input"
                                    value={rowDraft.receiptId}
                                    onChange={(event) => updateDraft(row.key, { receiptId: event.target.value }, row.attempt)}
                                    placeholder="receipt-binding:..."
                                  />
                                </label>
                                <label>
                                  <span>Post ID</span>
                                  <input
                                    className="input"
                                    value={rowDraft.postId}
                                    onChange={(event) => updateDraft(row.key, { postId: event.target.value }, row.attempt)}
                                    placeholder="可选"
                                  />
                                </label>
                                <button
                                  type="button"
                                  className="button primary"
                                  disabled={backfill.isPending || !selectedJobId || (!rowDraft.publicUrl.trim() && !rowDraft.receiptId.trim())}
                                  onClick={() =>
                                    backfill.mutate({
                                      platform: row.key,
                                      publicUrl: rowDraft.publicUrl,
                                      receiptId: rowDraft.receiptId,
                                      postId: rowDraft.postId,
                                    })
                                  }
                                >
                                  <Save size={16} aria-hidden="true" />
                                  {backfill.isPending ? "保存中" : "保存回填"}
                                </button>
                              </div>
                            </div>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <EmptyState message="请先在平台勾选区选择要处理的平台。" />
                )}
              </>
            ) : (
              <EmptyState message="选择真实作业后，这里会显示后端发布计划中的平台清单。" />
            )}
            {copyFeedback ? <div className="notice compact-top">{copyFeedback}</div> : null}
            {openJobFolder.error ? <div className="notice notice-error compact-top">{String(openJobFolder.error)}</div> : null}
            {backfill.error ? <div className="notice notice-error compact-top">{String(backfill.error)}</div> : null}
          </section>
        </div>

        <aside className="panel publication-selected-video publication-preview-rail">
          <PanelHeader title="成片预览" description="固定预览窗口和作业信息。" />
          <div className="publication-video-preview">
            <div className="publication-video-frame">
              {previewUrl ? (
                <video src={previewUrl} controls preload="metadata" />
              ) : (
                <>
                  <PlaySquare size={34} aria-hidden="true" />
                  <span>未选择视频</span>
                </>
              )}
            </div>
            <div className="publication-video-copy">
              <strong>{selectedJob?.source_name || "未选择成片"}</strong>
              <div className="publication-video-facts">
                <PathCell label="作业 ID" value={selectedJob?.id} />
                <PathCell label="成片视频" value={plan?.media_path} />
                <PathCell label="创作者" value={plan?.creator_profile_name || selectedJob?.creator_card_name} />
                <PathCell label="发布状态" value={selectedJob?.publication_summary || plan?.status} />
              </div>
            </div>
          </div>
          {publicationPlan.isError ? <div className="notice notice-error compact-top">{String(publicationPlan.error)}</div> : null}
          {openPublicationEntry.error ? <div className="notice notice-error compact-top">{String(openPublicationEntry.error)}</div> : null}
          {prepareMaterials.error ? <div className="notice notice-error compact-top">{String(prepareMaterials.error)}</div> : null}
        </aside>
      </div>
    </section>
  );
}

function PublicationFilterGroup({
  title,
  emptyLabel,
  options,
  selectedKeys,
  onToggle,
}: {
  title: string;
  emptyLabel: string;
  options: PublicationFilterOption[];
  selectedKeys: string[];
  onToggle: (key: string) => void;
}) {
  return (
    <div className="publication-filter-group">
      <div className="publication-filter-group-head">
        <strong>{title}</strong>
        <span>{selectedKeys.length ? `已选 ${selectedKeys.length}` : "不限"}</span>
      </div>
      <div className="publication-filter-chip-grid">
        {options.length ? (
          options.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`publication-filter-chip${selectedKeys.includes(option.key) ? " selected" : ""}`}
              aria-pressed={selectedKeys.includes(option.key)}
              onClick={() => onToggle(option.key)}
            >
              <span>{option.label}</span>
              <em>{option.count}</em>
            </button>
          ))
        ) : (
          <span className="publication-filter-empty">{emptyLabel}</span>
        )}
      </div>
    </div>
  );
}

function CopyField({ label, value, multiline = false, onCopy }: { label: string; value: string; multiline?: boolean; onCopy: () => void }) {
  return (
    <div className={`publication-copy-field${multiline ? " multiline" : ""}`}>
      <div>
        <span>{label}</span>
        {multiline ? <p>{value || "未生成"}</p> : <strong title={value || "未生成"}>{value || "未生成"}</strong>}
      </div>
      <button type="button" className="button ghost button-sm" disabled={!value} onClick={onCopy}>
        <Clipboard size={14} aria-hidden="true" />
        复制{label}
      </button>
    </div>
  );
}

function ReadonlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="publication-copy-field publication-rule-field">
      <div>
        <span>{label}</span>
        <strong title={value}>{value}</strong>
      </div>
    </div>
  );
}

function PathCell({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="publication-path-cell">
      <span>{label}</span>
      <strong title={value || "未绑定"}>{value || "未绑定"}</strong>
    </div>
  );
}

function buildPlatformRows(
  materials: PublicationTarget[],
  targets: PublicationTarget[],
  manualTargets: ManualHandoffTarget[],
  attempts: PublicationAttempt[],
  plan: PublicationPlan | null,
): PlatformRow[] {
  const keys = new Set<string>();
  normalizeSelectionPlatformKeys([
    ...(plan?.creator_default_platforms ?? []),
    ...(plan?.creator_platform_option_platforms ?? []),
    ...Object.keys(plan?.platform_options ?? {}),
  ]).forEach((key) => keys.add(key));
  materials.forEach((material) => keys.add(normalizeIntelligentCopyPlatformId(material.platform)));
  targets.forEach((target) => keys.add(normalizeIntelligentCopyPlatformId(target.platform)));
  manualTargets.forEach((target) => keys.add(normalizeIntelligentCopyPlatformId(target.platform)));
  attempts.forEach((attempt) => keys.add(normalizeIntelligentCopyPlatformId(attempt.platform)));
  return Array.from(keys).filter(Boolean).map((key) => {
    const material = materials.find((item) => normalizeIntelligentCopyPlatformId(item.platform) === key) ?? null;
    const target = targets.find((item) => normalizeIntelligentCopyPlatformId(item.platform) === key) ?? null;
    const manualTarget = manualTargets.find((item) => normalizeIntelligentCopyPlatformId(item.platform) === key) ?? null;
    const attempt = attempts.find((item) => normalizeIntelligentCopyPlatformId(item.platform) === key) ?? null;
    const manualTargetLabel = String(manualTarget?.label || "").trim();
    const manualTargetAccount = String((manualTarget as { account_label?: string | null } | null)?.account_label || "").trim();
    return {
      key,
      label: material?.platform_label || target?.platform_label || manualTargetLabel || attempt?.platform_label || PLATFORM_LABELS[key] || key,
      accountLabel: target?.account_label || material?.account_label || manualTargetAccount || attempt?.account_label || "",
      material,
      target,
      manualTarget,
      attempt,
    };
  });
}

function platformMaterialStatus(row: PlatformRow): { label: string; tone: "done" | "running" | "failed" } {
  if (!row.material) {
    return { label: "未生成物料", tone: "failed" };
  }
  if (!platformHasGeneratedMaterial(row)) {
    return { label: "待补全物料", tone: "running" };
  }
  return { label: "已生成物料", tone: "done" };
}

function resolveInitialPlatformSelection(
  rows: PlatformRow[],
  plan: PublicationPlan | null,
): { keys: string[]; expandedKeys: string[]; label: string } {
  const availableKeys = rows.map((row) => row.key);
  const availableSet = new Set(availableKeys);
  const creatorKeys = normalizeSelectionPlatformKeys([
    ...(plan?.creator_default_platforms ?? []),
    ...(!plan?.creator_default_platforms?.length ? plan?.creator_platform_option_platforms ?? [] : []),
  ]).filter((key) => availableSet.has(key));
  if (creatorKeys.length) {
    return { keys: creatorKeys, expandedKeys: [], label: "创作者平台设置" };
  }
  return { keys: availableKeys, expandedKeys: [], label: "默认全平台" };
}

function normalizeSelectionPlatformKeys(values: unknown[]): string[] {
  const keys: string[] = [];
  for (const value of values) {
    const key = normalizeIntelligentCopyPlatformId(String(value || ""));
    if (key && !keys.includes(key)) keys.push(key);
  }
  return keys;
}

function publicationMaterialActionLabel(rows: PlatformRow[]): string {
  if (!rows.length) {
    return "选择平台后生成物料";
  }
  const readyCount = rows.filter(platformHasGeneratedMaterial).length;
  if (readyCount === 0) {
    return rows.some((row) => row.material) ? "补全物料" : "生成物料";
  }
  if (readyCount === rows.length) {
    return "重新生成物料";
  }
  return "补全物料";
}

function platformHasGeneratedMaterial(row: PlatformRow): boolean {
  return Boolean(platformTitle(row) || platformBody(row) || platformTags(row) || platformCoverPath(row));
}

function rowConstraintNumber(row: PlatformRow, key: string): number | null {
  const constraints = row.material?.constraints as Record<string, unknown> | null | undefined;
  const value = constraints?.[key];
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function rowBooleanField(row: PlatformRow, key: "has_title" | "separate_tags" | "tags_embedded_in_body"): boolean | undefined {
  const manualTarget = row.manualTarget as (ManualHandoffTarget & Record<string, unknown>) | null;
  const value = row.material?.[key] ?? row.target?.[key] ?? manualTarget?.[key];
  return typeof value === "boolean" ? value : undefined;
}

function platformHasTitle(row: PlatformRow): boolean {
  const explicit = rowBooleanField(row, "has_title");
  if (explicit === false) return false;
  const titleLimit = rowConstraintNumber(row, "title_limit");
  if (titleLimit !== null && titleLimit <= 0) return false;
  if (explicit === true) return true;
  return !TITLELESS_PLATFORM_KEYS.has(row.key);
}

function platformHasSeparateTags(row: PlatformRow): boolean {
  const separateTags = rowBooleanField(row, "separate_tags");
  const tagsEmbeddedInBody = rowBooleanField(row, "tags_embedded_in_body");
  if (separateTags === false || tagsEmbeddedInBody === true) return false;
  const tagLimit = rowConstraintNumber(row, "tag_limit");
  if (tagLimit !== null && tagLimit <= 0) return false;
  if (separateTags === true) return true;
  return !TITLELESS_PLATFORM_KEYS.has(row.key);
}

function rowRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function rowSourceRecords(row: PlatformRow): Record<string, unknown>[] {
  return [row.material, row.target, row.manualTarget]
    .map((source) => rowRecord(source))
    .filter((source): source is Record<string, unknown> => Boolean(source));
}

function rowStringField(row: PlatformRow, key: string): string {
  for (const source of rowSourceRecords(row)) {
    const value = String(source[key] ?? "").trim();
    if (value) return value;
  }
  return "";
}

function rowRecordField(row: PlatformRow, key: string): Record<string, unknown> | null {
  for (const source of rowSourceRecords(row)) {
    const value = rowRecord(source[key]);
    if (value) return value;
  }
  return null;
}

function rowPlatformSpecificOverrides(row: PlatformRow): Record<string, unknown> | null {
  return rowRecordField(row, "platform_specific_overrides");
}

function rowCollectionManagement(row: PlatformRow): Record<string, unknown> | null {
  const overrides = rowPlatformSpecificOverrides(row);
  return rowRecord(overrides?.collection_management) || rowRecordField(row, "collection_management");
}

function rowCollectionName(row: PlatformRow, collectionManagement: Record<string, unknown> | null): string {
  const managementName = String(
    collectionManagement?.selected_collection_name
      ?? collectionManagement?.target_collection_name
      ?? collectionManagement?.collection_name
      ?? "",
  ).trim();
  const directName = rowStringField(row, "collection_name");
  const collection = rowRecordField(row, "collection");
  const collectionName = String(collection?.name ?? collection?.title ?? collection?.label ?? "").trim();
  return managementName || directName || collectionName;
}

function collectionRuleLabel(row: PlatformRow, collectionManagement: Record<string, unknown> | null): string {
  const kind = String(collectionManagement?.kind ?? "").trim().toLowerCase();
  if (kind === "playlist" || row.key === "youtube") return "播放列表";
  if (kind === "column") return "栏目";
  return "合集";
}

function collectionStatusLabel(status: string): string {
  if (status === "select_existing") return "已选择";
  if (status === "needs_create" || status === "create_required") return "需新建";
  if (status === "exists_but_not_selectable_on_publish_form") return "发布后关联";
  if (status === "skipped_by_policy") return "已跳过";
  if (status === "not_supported") return "不支持";
  if (status === "not_configured") return "未配置";
  return status;
}

function buildPublicationRuleRows(row: PlatformRow): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  const collectionManagement = rowCollectionManagement(row);
  const collectionName = rowCollectionName(row, collectionManagement);
  const collectionStatus = collectionStatusLabel(String(collectionManagement?.status ?? "").trim());
  const collectionDetails = [
    collectionStatus,
    collectionManagement?.create_required ? "需新建" : "",
    collectionManagement?.post_publish_association_required ? "发布后关联" : "",
  ].filter((item, index, list) => item && list.indexOf(item) === index);

  if (collectionName || collectionDetails.length) {
    rows.push({
      label: collectionRuleLabel(row, collectionManagement),
      value: [collectionName, ...collectionDetails].filter(Boolean).join(" · "),
    });
  }

  return rows;
}

function platformTitle(row: PlatformRow): string {
  return row.material?.title || row.material?.titles?.[0] || "";
}

function platformBody(row: PlatformRow): string {
  return row.material?.body || row.material?.description || "";
}

function platformTags(row: PlatformRow): string {
  const tagsCopy = String(row.material?.tags_copy || row.material?.copy_material?.tags_copy || "").trim();
  if (tagsCopy) {
    return row.key === "bilibili" || tagsCopy.includes("#") ? tagsCopy : hashtagTagCopy(tagsCopy.split(/[,，\s]+/));
  }
  const tags = row.material?.tags ?? [];
  const style = platformTagStyle(row);
  if (row.key !== "bilibili" || style === "hashtags_space") {
    return hashtagTagCopy(tags);
  }
  return tags.map((tag) => String(tag || "").trim().replace(/^#+/, "")).filter(Boolean).join(", ");
}

function platformCoverPath(row: PlatformRow): string {
  return row.material?.cover_path || "";
}

function platformTitleLabel(row: PlatformRow): string {
  return String(row.material?.title_label || row.target?.title_label || "标题").trim() || "标题";
}

function platformBodyLabel(row: PlatformRow): string {
  return String(row.material?.body_label || row.target?.body_label || (row.key === "kuaishou" ? "作品描述" : "正文")).trim() || "正文";
}

function platformTagLabel(row: PlatformRow): string {
  return String(row.material?.tag_label || row.target?.tag_label || "标签").trim() || "标签";
}

function platformTagStyle(row: PlatformRow): string {
  const constraints = row.material?.constraints;
  if (constraints && "tag_style" in constraints) {
    return String((constraints as { tag_style?: unknown }).tag_style || "").trim();
  }
  if (["douyin", "kuaishou", "wechat-channels", "xiaohongshu", "x"].includes(row.key)) {
    return "hashtags_space";
  }
  return "";
}

function hashtagTagCopy(tags: unknown[]): string {
  return tags.map((tag) => {
    const text = String(tag || "").trim();
    if (!text) return "";
    return text.startsWith("#") ? text : `#${text.replace(/^#+/, "")}`;
  }).filter(Boolean).join(" ");
}

function platformEntryUrl(row: PlatformRow): string {
  return String(
    row.material?.manual_publish_entry_url
      || row.target?.manual_publish_entry_url
      || row.manualTarget?.login_url
      || row.target?.login_url
      || row.material?.login_url
      || DEFAULT_PLATFORM_ENTRY_URLS[row.key]
      || "",
  ).trim();
}

function buildPublicationEntryOpenRequest(row: PlatformRow, url: string): PublicationEntryOpenRequest {
  const source = (row.target ?? row.material ?? row.manualTarget ?? {}) as Record<string, unknown>;
  return {
    url,
    platform: row.key,
    account_label: row.accountLabel,
    credential_ref: String(source.credential_ref ?? "").trim() || null,
    browser_profile_id: String(source.browser_profile_id ?? "").trim() || null,
    browser_binding: rowRecord(source.browser_binding),
  };
}

function buildDraftFromAttempt(attempt: PublicationAttempt | null | undefined): BackfillDraft {
  return {
    publicUrl: publicationAttemptUrl(attempt),
    receiptId: publicationAttemptReceiptId(attempt),
    postId: String(attempt?.external_post_id || ""),
  };
}

function mergeAttempts(attempts: PublicationAttempt[]) {
  const seen = new Set<string>();
  const merged: PublicationAttempt[] = [];
  for (const attempt of attempts) {
    if (!attempt?.id || seen.has(attempt.id)) continue;
    seen.add(attempt.id);
    merged.push(attempt);
  }
  return merged.sort((left, right) => {
    const leftTime = new Date(left.updated_at || left.created_at).getTime();
    const rightTime = new Date(right.updated_at || right.created_at).getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  });
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

function materialTaskDurationLabel(task: IntelligentCopyGenerateTask): string {
  const startMs = Date.parse(task.started_at || task.created_at || "");
  if (!Number.isFinite(startMs)) return "用时未记录";
  const endMs = Date.parse(task.completed_at || "");
  const durationMs = Math.max(0, (Number.isFinite(endMs) ? endMs : Date.now()) - startMs);
  const seconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const display = hours > 0
    ? `${hours}小时${minutes % 60}分`
    : minutes > 0
      ? `${minutes}分${seconds % 60}秒`
      : `${seconds}秒`;
  return task.completed_at ? `总用时 ${display}` : `已用时 ${display}`;
}

function buildPublicationFilterOptions(
  jobs: Job[],
  keyGetter: (job: Job) => string,
  labelGetter: (job: Job) => string,
): PublicationFilterOption[] {
  const options = new Map<string, PublicationFilterOption>();
  for (const job of jobs) {
    const key = keyGetter(job);
    const label = labelGetter(job);
    const existing = options.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      options.set(key, { key, label, count: 1 });
    }
  }
  return Array.from(options.values()).sort((left, right) => {
    if (right.count !== left.count) return right.count - left.count;
    return left.label.localeCompare(right.label, "zh-CN");
  });
}

function jobCreatorFilterKey(job: Job): string {
  if (job.creator_card_id) return `creator:${job.creator_card_id}`;
  const name = String(job.creator_card_name || "").trim();
  return name ? `creator-name:${name}` : "creator:unbound";
}

function jobCreatorFilterLabel(job: Job): string {
  return String(job.creator_card_name || "").trim() || "未绑定创作者";
}

function jobClipTypeFilterKey(job: Job): PublicationClipTypeFilter {
  return job.queue_task_kind ?? "edit";
}

function jobClipTypeFilterLabel(job: Job): string {
  return PUBLICATION_CLIP_TYPE_LABELS[jobClipTypeFilterKey(job)];
}

function matchesPublicationTimeFilter(job: Job, filter: PublicationTimeFilter): boolean {
  const lowerBound = publicationTimeFilterLowerBound(filter);
  if (!lowerBound) return true;
  const updatedAt = new Date(job.updated_at).getTime();
  return Number.isFinite(updatedAt) && updatedAt >= lowerBound.getTime();
}

function publicationTimeFilterLowerBound(filter: PublicationTimeFilter): Date | null {
  if (filter === "all") return null;
  const daySpan = filter === "today" ? 1 : filter === "three_days" ? 3 : 7;
  const lowerBound = new Date();
  lowerBound.setHours(0, 0, 0, 0);
  lowerBound.setDate(lowerBound.getDate() - (daySpan - 1));
  return lowerBound;
}

function isPublicationCandidate(job: Job): boolean {
  if (job.queue_task_kind === "publication") return true;
  if (job.publication_status && job.publication_status !== "unpublished") return true;
  return job.status === "done" || job.status === "published";
}

async function copyText(text: string, successLabel: string, setCopyFeedback: (value: string) => void) {
  if (!text.trim()) return;
  const result = await writeTextToClipboard(text);
  if (result.ok) {
    setCopyFeedback(successLabel);
  } else {
    setCopyFeedback("复制失败，请检查系统剪贴板权限。");
  }
  window.setTimeout(() => setCopyFeedback(""), 1800);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
