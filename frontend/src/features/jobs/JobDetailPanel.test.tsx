import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

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
          "jobs.detail.noEnhancements": "未启用增强模式",
          "jobs.actions.openFolder": "打开文件夹",
          "jobs.actions.downloadVideo": "下载成片",
          "jobs.actions.downloadHint.standard": "当前导出的是标准成片。",
          "jobs.actions.cancel": "取消",
          "jobs.actions.cancelling": "取消中...",
          "jobs.actions.restart": "重新开始",
          "jobs.actions.restarting": "重启中...",
          "jobs.actions.restartUnavailable": "当前状态不可重新开始",
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
  getRestartUnavailableReason: () => "jobs.actions.restartUnavailable",
  isRestartableJobStatus: () => true,
  stepLabel: (stepName: string) => stepName,
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
      created_at: "2026-04-10T00:00:00Z",
      updated_at: "2026-04-10T00:05:00Z",
      steps: [],
    },
    isLoading: false,
    contentSource: null,
    contentDraft: {},
    contentKeywords: "",
    reviewEnhancementModes: [],
    isConfirmingProfile: false,
    isApplyingReview: false,
    isCancelling: false,
    isRestarting: false,
    isDeleting: false,
    onContentFieldChange: vi.fn(),
    onKeywordsChange: vi.fn(),
    onConfirmProfile: vi.fn(),
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
});
