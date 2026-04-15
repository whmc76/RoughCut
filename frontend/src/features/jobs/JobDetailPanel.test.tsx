import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import { JobDetailPanel } from "./JobDetailPanel";

vi.mock("../../i18n", () => ({
  useI18n: () => ({
    t: (key: string) =>
      (
        {
          "jobs.detail.empty": "选择一条任务后显示详情",
          "jobs.detail.loading": "加载详情中...",
          "jobs.detail.creativeMode": "创作模式",
          "jobs.detail.sourceBundle": "素材来源",
          "jobs.detail.mergedTask": "这是合并任务",
          "jobs.detail.mergedTaskCount": "共 {count} 段素材",
          "jobs.detail.videoDescription": "任务说明",
          "jobs.detail.filenameDerivedDescription": "文件名提取",
          "jobs.detail.filenameDerivedBadge": "来自文件名",
          "jobs.detail.manualDescription": "补充说明",
          "jobs.detail.noEnhancements": "未启用增强模式",
          "jobs.actions.openFolder": "打开文件夹",
          "jobs.actions.downloadVideo": "下载成片",
          "jobs.actions.downloadHint.standard": "当前导出的是标准成片。",
          "jobs.actions.cancel": "取消",
          "jobs.actions.cancelling": "取消中...",
          "jobs.actions.restart": "重新开始",
          "jobs.actions.restarting": "重启中...",
          "jobs.actions.restartUnavailable": "当前状态不可重新开始",
          "jobs.init.submit": "填写说明并开始处理",
          "jobs.init.submitting": "正在启动...",
          "jobs.actions.delete": "删除任务",
          "jobs.actions.deleting": "删除中...",
        } satisfies Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("../../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) => (
    <div>
      <strong>{title}</strong>
      <span>{description}</span>
      {actions}
    </div>
  ),
}));

vi.mock("../../components/ui/EmptyState", () => ({
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
}));

vi.mock("./JobContentProfileSection", () => ({
  JobContentProfileSection: () => <div>content-profile-section</div>,
}));

vi.mock("./JobSubtitleReportSection", () => ({
  JobSubtitleReportSection: () => <div>subtitle-report-section</div>,
}));

vi.mock("./JobReviewConfigSection", () => ({
  JobReviewConfigSection: () => <div>review-config-section</div>,
}));

vi.mock("./constants", () => ({
  autoReviewBadgeLabel: (job: { auto_review_status?: string | null }) => (job.auto_review_status === "applied" ? "自动审核已生效" : "自动审核已启用"),
  autoReviewTone: (status: string | null | undefined) => (status === "applied" ? "done" : status === "blocked" ? "pending" : "running"),
  getRestartUnavailableReason: () => "jobs.actions.restartUnavailable",
  isRestartableJobStatus: () => true,
  stepLabel: (stepName: string) =>
    (
      {
        subtitle_term_resolution: "术语纠偏",
        subtitle_consistency_review: "一致性审校",
        subtitle_quality: "字幕质量",
      } as Record<string, string>
    )[stepName] ?? stepName,
  workflowModeLabel: (mode: string) => mode,
  enhancementModeLabel: (mode: string) => mode,
}));

vi.mock("../../utils", () => ({
  classNames: (...values: Array<string | false | null | undefined>) => values.filter(Boolean).join(" "),
  formatDate: (value: string) => value,
  statusLabel: (status: string) => status,
}));

function buildProps(overrides: Record<string, unknown> = {}) {
  return {
    selectedJobId: "job-1",
    selectedJob: {
      id: "job-1",
      source_name: "merged_2_part-1.mp4",
      merged_source_names: ["part-1.mp4", "part-2.mp4"],
      status: "pending",
      language: "zh-CN",
      workflow_mode: "standard_edit",
      enhancement_modes: [],
      auto_review_mode_enabled: false,
      auto_review_status: null,
      auto_review_summary: null,
      auto_review_reasons: [],
      created_at: "2026-04-10T00:00:00Z",
      updated_at: "2026-04-10T00:05:00Z",
      steps: [],
    },
    isLoading: false,
    contentSource: null,
    contentDraft: {},
    contentKeywords: "",
    reviewEnhancementModes: [],
    languageOptions: [{ value: "zh-CN", label: "简体中文" }],
    workflowTemplateOptions: [{ value: "", label: "自动选择模板" }],
    workflowModeOptions: [{ value: "standard_edit", label: "标准成片" }],
    enhancementOptions: [],
    pendingInitialization: {
      language: "zh-CN",
      workflowTemplate: "",
      workflowMode: "standard_edit",
      enhancementModes: [],
      outputDir: "",
      videoDescription: "",
    },
    isConfirmingProfile: false,
    isInitializing: false,
    isApplyingReview: false,
    isCancelling: false,
    isRestarting: false,
    isDeleting: false,
    onContentFieldChange: vi.fn(),
    onKeywordsChange: vi.fn(),
    onPendingInitializationChange: vi.fn(),
    onConfirmProfile: vi.fn(),
    onInitialize: vi.fn(),
    onOpenFolder: vi.fn(),
    onCancel: vi.fn(),
    onRestart: vi.fn(),
    onDelete: vi.fn(),
    onApplyReview: vi.fn(),
    ...overrides,
  };
}

describe("JobDetailPanel", () => {
  it("shows explicit merged task metadata in the detail header area", () => {
    render(<JobDetailPanel {...buildProps()} />);

    expect(screen.getByText("素材来源")).toBeInTheDocument();
    expect(screen.getByText("这是合并任务")).toBeInTheDocument();
    expect(screen.getByText("共 2 段素材")).toBeInTheDocument();
    expect(screen.getByText("part-1.mp4")).toBeInTheDocument();
    expect(screen.getByText("part-2.mp4")).toBeInTheDocument();
  });

  it("does not show merged task metadata for a normal single-source job", () => {
    render(
      <JobDetailPanel
        {...buildProps({
          selectedJob: {
            id: "job-2",
            source_name: "single.mp4",
            merged_source_names: [],
            status: "pending",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [],
          },
        })}
      />,
    );

    expect(screen.queryByText("素材来源")).not.toBeInTheDocument();
    expect(screen.queryByText("这是合并任务")).not.toBeInTheDocument();
  });

  it("separates filename-derived description from manual notes in the detail panel", () => {
    render(
      <JobDetailPanel
        {...buildProps({
          selectedJob: {
            id: "job-2b",
            source_name: "20260316_狐蝠工业_FXX1小副包_开箱测评.mp4",
            merged_source_names: [],
            video_description: "任务说明依据文件名：狐蝠工业 FXX1小副包 开箱测评。\n重点保留近景细节和开合手感。",
            status: "pending",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [],
          },
        })}
      />,
    );

    expect(screen.getByText("任务说明")).toBeInTheDocument();
    expect(screen.getByText("文件名提取")).toBeInTheDocument();
    expect(screen.getByText("来自文件名")).toBeInTheDocument();
    expect(screen.getByText("狐蝠工业 FXX1小副包 开箱测评。")).toBeInTheDocument();
    expect(screen.getByText("补充说明")).toBeInTheDocument();
    expect(screen.getByText("重点保留近景细节和开合手感。")).toBeInTheDocument();
  });

  it("shows whether auto-review is enabled or already applied in the creative mode section", () => {
    render(
      <JobDetailPanel
        {...buildProps({
          selectedJob: {
            id: "job-3",
            source_name: "auto-review.mp4",
            merged_source_names: [],
            status: "needs_review",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: ["auto_review"],
            auto_review_mode_enabled: true,
            auto_review_status: "blocked",
            auto_review_summary: "已启用，但本次命中人工复核条件，未自动放行。",
            auto_review_reasons: ["首次品牌/型号证据不足，需人工确认"],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [],
          },
        })}
      />,
    );

    expect(screen.getAllByText("自动审核已启用").length).toBeGreaterThan(0);
    expect(screen.getByText("已启用，但本次命中人工复核条件，未自动放行。")).toBeInTheDocument();
    expect(screen.getByText("首次品牌/型号证据不足，需人工确认")).toBeInTheDocument();
  });

  it("surfaces subtitle decision and blocking reasons in the detail flow", () => {
    const onTriggerSubtitleRerun = vi.fn();
    render(
      <JobDetailPanel
        {...buildProps({
          onTriggerSubtitleRerun,
          selectedJob: {
            id: "job-5",
            source_name: "subtitle-review.mp4",
            merged_source_names: [],
            status: "processing",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            quality_score: 78.4,
            quality_grade: "B+",
            quality_summary: "字幕术语与一致性仍有待确认。",
            quality_issue_codes: ["subtitle_term_resolution", "subtitle_consistency_review"],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [
              {
                id: "subtitle-term",
                step_name: "subtitle_term_resolution",
                status: "done",
                attempt: 1,
                started_at: "2026-04-10T00:01:00Z",
                finished_at: "2026-04-10T00:02:00Z",
                error_message: null,
              },
            ],
          },
          activity: {
            job_id: "job-5",
            status: "processing",
            review_step: null,
            review_detail: null,
            current_step: null,
            render: null,
            decisions: [
              {
                kind: "subtitle_term_resolution",
                step_name: "subtitle_term_resolution",
                title: "术语解析已完成",
                status: "done",
                summary: "已生成字幕术语修正建议。",
                detail: "需要继续确认 2 个术语别名后再放行。",
                review_route: "subtitle_review",
                review_label: "术语候选确认",
                recommended_action: "先人工确认 2 条术语候选，再继续后续摘要与成片流程。",
                rerun_start_step: "subtitle_term_resolution",
                rerun_steps: ["subtitle_term_resolution", "subtitle_consistency_review", "glossary_review"],
                issue_codes: ["subtitle_terms_pending"],
                updated_at: "2026-04-10T00:02:00Z",
              },
              {
                kind: "subtitle_consistency_review",
                step_name: "subtitle_consistency_review",
                title: "一致性待核对",
                status: "pending",
                summary: "检测到摘要与字幕存在轻微偏差。",
                detail: "字幕和摘要对品牌型号的写法不一致。",
                review_route: "subtitle_review",
                review_label: "一致性冲突复核",
                recommended_action: "先复核一致性冲突：字幕和摘要对品牌型号的写法不一致。；确认后如需自动回退，从 subtitle_consistency_review 起重跑。",
                rerun_start_step: "subtitle_consistency_review",
                rerun_steps: ["subtitle_consistency_review", "glossary_review", "subtitle_translation"],
                issue_codes: ["subtitle_consistency_blocking"],
                updated_at: "2026-04-10T00:03:00Z",
              },
            ],
            events: [],
          },
        })}
      />,
    );

    expect(screen.getByText("字幕决策与阻断")).toBeInTheDocument();
    expect(screen.getAllByText("术语纠偏").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("一致性审校").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("字幕术语与一致性仍有待确认。")).toBeInTheDocument();
    expect(screen.getAllByText("需要继续确认 2 个术语别名后再放行。").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("字幕和摘要对品牌型号的写法不一致。").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("处理动作：先人工确认 2 条术语候选，再继续后续摘要与成片流程。")).toBeInTheDocument();
    expect(screen.getByText("自动回退：subtitle_term_resolution -> subtitle_consistency_review -> glossary_review")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "按建议重跑" })[0]);
    expect(onTriggerSubtitleRerun).toHaveBeenCalledWith(expect.objectContaining({
      kind: "subtitle_term_resolution",
      rerun_start_step: "subtitle_term_resolution",
    }));
  });

  it("groups activity items by structured step_name instead of parsing titles", () => {
    render(
      <JobDetailPanel
        {...buildProps({
          selectedJob: {
            id: "job-4",
            source_name: "render-activity.mp4",
            merged_source_names: [],
            status: "processing",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [
              {
                id: "render-step",
                step_name: "render",
                status: "running",
                attempt: 1,
                started_at: "2026-04-10T00:04:00Z",
                finished_at: null,
                error_message: null,
              },
            ],
          },
          activity: {
            job_id: "job-4",
            status: "processing",
            review_step: null,
            review_detail: null,
            current_step: {
              step_name: "render",
              label: "render",
              status: "running",
              detail: "执行 FFmpeg 渲染成片",
              progress: 0.6,
              updated_at: "2026-04-10T00:05:00Z",
            },
            render: null,
            decisions: [
              {
                kind: "render",
                step_name: "render",
                title: "完全自定义决策标题",
                status: "running",
                summary: "这条摘要不包含任何步骤关键词",
                detail: "但仍应归到 render 步骤下展示。",
                updated_at: "2026-04-10T00:05:00Z",
              },
            ],
            events: [
              {
                timestamp: "2026-04-10T00:05:00Z",
                type: "progress",
                status: "running",
                step_name: "render",
                title: "任意事件标题",
                detail: "这条事件也不依赖中文标题匹配。",
              },
            ],
          },
        })}
      />,
    );

    expect(screen.getByText("完全自定义决策标题")).toBeInTheDocument();
    expect(screen.getByText("任意事件标题")).toBeInTheDocument();
    expect(screen.getByText("但仍应归到 render 步骤下展示。")).toBeInTheDocument();
    expect(screen.getByText("这条事件也不依赖中文标题匹配。")).toBeInTheDocument();
  });

  it("highlights rerun review actions inside the step timeline", () => {
    render(
      <JobDetailPanel
        {...buildProps({
          selectedJob: {
            id: "job-rerun",
            source_name: "rerun-activity.mp4",
            merged_source_names: [],
            status: "processing",
            language: "zh-CN",
            workflow_mode: "standard_edit",
            enhancement_modes: [],
            created_at: "2026-04-10T00:00:00Z",
            updated_at: "2026-04-10T00:05:00Z",
            steps: [
              {
                id: "subtitle-step",
                step_name: "subtitle_postprocess",
                status: "pending",
                attempt: 1,
                started_at: null,
                finished_at: null,
                error_message: null,
              },
            ],
          },
          activity: {
            job_id: "job-rerun",
            status: "processing",
            review_step: null,
            review_detail: null,
            current_step: {
              step_name: "subtitle_postprocess",
              label: "subtitle_postprocess",
              status: "pending",
              detail: "等待自动改进重跑链路继续。",
              progress: null,
              updated_at: "2026-04-10T00:05:00Z",
            },
            render: null,
            decisions: [],
            events: [
              {
                timestamp: "2026-04-10T00:05:00Z",
                type: "review_action",
                status: "processing",
                step_name: "subtitle_postprocess",
                title: "已请求从 subtitle_postprocess 重跑",
                detail: "触发来源：Web；问题：subtitle_quality_blocking；回退链路：subtitle_postprocess -> subtitle_term_resolution -> subtitle_consistency_review",
              },
            ],
          },
        })}
      />,
    );

    expect(screen.getByText("已请求从 subtitle_postprocess 重跑")).toBeInTheDocument();
    expect(screen.getByText("重跑请求")).toBeInTheDocument();
    expect(screen.getByText(/触发来源：Web；问题：subtitle_quality_blocking/)).toBeInTheDocument();
  });
});
