import type { ReactNode } from "react";
import { fireEvent, render, screen } from "@testing-library/react";

import type { HealthDetail, ServiceStatus } from "../types";
import { ControlPage } from "./ControlPage";

const mockUseControlWorkspace = vi.fn();

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, actions }: { title: string; actions?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  ),
}));

vi.mock("../components/ui/PageSection", () => ({
  PageSection: ({ title, children }: { title: string; children: ReactNode }) => (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}));

vi.mock("../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title, description }: { title: string; description?: string }) => (
    <div>
      <strong>{title}</strong>
      {description ? <div>{description}</div> : null}
    </div>
  ),
}));

vi.mock("../features/control/useControlWorkspace", () => ({
  useControlWorkspace: () => mockUseControlWorkspace(),
}));

const SAMPLE_STATUS: ServiceStatus = {
  checked_at: "2026-03-27T06:00:00Z",
  services: {
    api: true,
    orchestrator: true,
    watcher: false,
  },
  runtime: {
    readiness_status: "ready",
    readiness_checks: {
      database: { status: "ok", detail: "database ok" },
    },
    live_readiness: {
      status: "fail",
      gate_passed: false,
      summary: "未满足 live dry run 准入门槛",
      stable_run_count: 2,
      required_stable_runs: 3,
      failure_reasons: ["连续稳定批次不足：2/3", "P0 blocker 未清零：1 个"],
      warning_reasons: ["未显式提供 golden jobs，当前按本次 batch 全量样本评估"],
      report_file: "E:/WorkSpace/RoughCut/output/test/fullchain-batch/batch_report.json",
      report_created_at: "2026-03-27T06:00:00Z",
      detail: "",
    },
    orchestrator_lock: {
      status: "held",
      leader_active: true,
      detail: "active leader",
    },
    review_notifications: {
      state_dir: "F:/roughcut_outputs/telegram-agent",
      store_file: "F:/roughcut_outputs/telegram-agent/review_notifications.json",
      detail: "2 queued notifications",
      summary: {
        total: 2,
        pending: 1,
        due_now: 1,
        failed: 1,
        delivered: 0,
      },
      items: [
        {
          notification_id: "notif-1",
          kind: "content_profile",
          job_id: "job-1",
          status: "failed",
          attempt_count: 3,
          next_attempt_at: "2026-03-27T06:10:00Z",
          last_error: "network timeout",
          force_full_review: true,
          updated_at: "2026-03-27T06:00:30Z",
        },
        {
          notification_id: "notif-2",
          kind: "final_review",
          job_id: "job-2",
          status: "pending",
          attempt_count: 1,
          next_attempt_at: "2026-03-27T06:15:00Z",
          last_error: "",
          force_full_review: false,
          updated_at: "2026-03-27T06:01:00Z",
        },
      ],
    },
  },
};

const SAMPLE_HEALTH: HealthDetail = {
  checked_at: "2026-03-27T06:00:10Z",
  status: "degraded",
  readiness: {
    status: "ready",
    checks: {
      database: { status: "ok", detail: "database ok" },
      redis: { status: "ok", detail: "redis ok" },
    },
  },
  orchestrator_lock: {
    status: "held",
    leader_active: true,
    detail: "active leader",
  },
  managed_services: [
    { name: "heygem", url: "http://127.0.0.1:49202", status: "ok", enabled: true },
    { name: "indextts2", url: "http://127.0.0.1:49204", status: "failed", enabled: true },
  ],
  watch_automation: {
    roots_total: 2,
    running_scans: 1,
    cached_pending_total: 3,
    auto_enqueue_enabled: true,
    auto_merge_enabled: false,
    active_jobs: 1,
    running_gpu_steps: 0,
    idle_slots: 1,
  },
};

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    stopDocker: false,
    setStopDocker: vi.fn(),
    reviewNotificationJobIdFilter: "",
    setReviewNotificationJobIdFilter: vi.fn(),
    status: { data: SAMPLE_STATUS, isLoading: false, isError: false, error: null },
    healthDetail: { data: SAMPLE_HEALTH, isLoading: false, isError: false, error: null },
    reviewNotifications: { data: SAMPLE_STATUS.runtime?.review_notifications, isLoading: false, isError: false, error: null },
    requeueReviewNotification: { mutate: vi.fn(), isPending: false, error: null },
    requeueReviewNotifications: { mutate: vi.fn(), isPending: false, error: null },
    dropReviewNotification: { mutate: vi.fn(), isPending: false, error: null },
    dropReviewNotifications: { mutate: vi.fn(), isPending: false, error: null },
    stop: { mutate: vi.fn(), data: undefined },
    ...overrides,
  };
}

describe("ControlPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders managed services and watcher automation detail", () => {
    mockUseControlWorkspace.mockReturnValue(buildWorkspace());

    render(<ControlPage />);

    expect(screen.getByText("Managed services")).toBeInTheDocument();
    expect(screen.getByText("heygem")).toBeInTheDocument();
    expect(screen.getByText("indextts2")).toBeInTheDocument();
    expect(screen.getByText("Watch automation")).toBeInTheDocument();
    expect(screen.getByText("Auto enqueue / merge")).toBeInTheDocument();
    expect(screen.getByText("2 roots")).toBeInTheDocument();
    expect(screen.getByText("3 pending")).toBeInTheDocument();
    expect(screen.getByText("Live readiness")).toBeInTheDocument();
    expect(screen.getByText("未满足 live dry run 准入门槛")).toBeInTheDocument();
    expect(screen.getByText("stable=2/3")).toBeInTheDocument();
    expect(screen.getByText(/failures=连续稳定批次不足：2\/3/)).toBeInTheDocument();
  });

  it("renders review notification queue details and triggers queue actions", () => {
    const workspace = buildWorkspace();
    mockUseControlWorkspace.mockReturnValue(workspace);

    render(<ControlPage />);

    expect(screen.getByText("Review notifications")).toBeInTheDocument();
    expect(screen.getByText("F:/roughcut_outputs/telegram-agent")).toBeInTheDocument();
    expect(screen.getByText("2 queued notifications")).toBeInTheDocument();
    expect(screen.getByText("Total").closest("article")).toHaveTextContent("2");
    expect(screen.getByText("Pending").closest("article")).toHaveTextContent("1");
    expect(screen.getByText("Due now").closest("article")).toHaveTextContent("1");
    expect(screen.getByText("Failed").closest("article")).toHaveTextContent("1");
    expect(screen.getByText("notif-1 · job=job-1")).toBeInTheDocument();
    expect(screen.getByText("error=network timeout")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("按 job_id 过滤")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Requeue" })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: "Drop" })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Requeue shown" }));
    fireEvent.click(screen.getByRole("button", { name: "Drop shown" }));

    expect(workspace.requeueReviewNotification.mutate).toHaveBeenCalledWith("notif-1");
    expect(workspace.dropReviewNotification.mutate).toHaveBeenCalledWith("notif-1");
    expect(workspace.requeueReviewNotifications.mutate).toHaveBeenCalledWith(["notif-1", "notif-2"]);
    expect(workspace.dropReviewNotifications.mutate).toHaveBeenCalledWith(["notif-1", "notif-2"]);
  });
});
