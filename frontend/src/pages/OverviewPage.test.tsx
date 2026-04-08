import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

import { OverviewPage } from "./OverviewPage";

const mockUseOverviewWorkspace = vi.fn();

vi.mock("react-router-dom", () => ({
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}));

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, summary }: { title: string; summary?: Array<{ value: string }> }) => (
    <header>
      <h1>{title}</h1>
      {summary?.map((item) => (
        <div key={item.value}>{item.value}</div>
      ))}
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
  PanelHeader: ({ title }: { title: string }) => <strong>{title}</strong>,
}));

vi.mock("../components/ui/StatCard", () => ({
  StatCard: ({ label, value }: { label: string; value: string | number }) => (
    <div>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  ),
}));

vi.mock("../components/ui/EmptyState", () => ({
  EmptyState: ({ message }: { message: string }) => <div>{message}</div>,
}));

vi.mock("../features/configProfiles/ConfigProfileSwitcher", () => ({
  ConfigProfileSwitcher: () => <div>config-profile-switcher</div>,
}));

vi.mock("../features/jobs/JobsUsageTrendPanel", () => ({
  JobsUsageTrendPanel: () => <div>usage-trend-panel</div>,
}));

vi.mock("../features/overview/useOverviewWorkspace", () => ({
  useOverviewWorkspace: () => mockUseOverviewWorkspace(),
}));

vi.mock("../utils", () => ({
  formatDate: (value: string) => value,
  statusLabel: (value: string) => value,
}));

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    jobs: { data: [], isLoading: false, isError: false, error: null },
    usageSummary: { data: undefined },
    usageTrend: { data: [] },
    usageTrendDays: 7,
    setUsageTrendDays: vi.fn(),
    usageTrendFocusType: "all",
    setUsageTrendFocusType: vi.fn(),
    usageTrendFocusName: "",
    setUsageTrendFocusName: vi.fn(),
    watchRoots: { data: [] },
    glossary: { data: [] },
    services: { data: { services: {}, runtime: undefined }, isLoading: false },
    stats: { jobs: 0, running: 0, watchRoots: 0, glossary: 0 },
    ...overrides,
  };
}

describe("OverviewPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not render the config profile switcher or config baseline copy on the overview page", () => {
    mockUseOverviewWorkspace.mockReturnValue(buildWorkspace());

    render(<OverviewPage />);

    expect(screen.queryByText("config-profile-switcher")).not.toBeInTheDocument();
    expect(screen.queryByText("统一剪辑配置")).not.toBeInTheDocument();
  });

  it("does not render the old summary strip or instructional copy on the overview page", () => {
    mockUseOverviewWorkspace.mockReturnValue(buildWorkspace());

    render(<OverviewPage />);

    expect(screen.queryByText("第一段")).not.toBeInTheDocument();
    expect(screen.queryByText("第二段")).not.toBeInTheDocument();
    expect(screen.queryByText("第三段")).not.toBeInTheDocument();
    expect(screen.queryByText("先判断现在能不能继续跑")).not.toBeInTheDocument();
    expect(screen.queryByText("最后决定进入哪一页继续处理")).not.toBeInTheDocument();
  });

  it("renders the full analysis module on the overview page", () => {
    mockUseOverviewWorkspace.mockReturnValue(
      buildWorkspace({
        usageSummary: {
          data: {
            job_count: 3,
            jobs_with_telemetry: 2,
            total_calls: 5,
            total_prompt_tokens: 3200,
            total_completion_tokens: 900,
            total_tokens: 4100,
            cache: {
              total_entries: 2,
              hits: 1,
              misses: 1,
              hit_rate: 0.5,
              avoided_calls: 1,
              steps_with_hits: 1,
              hits_with_usage_baseline: 1,
              saved_prompt_tokens: 2400,
              saved_completion_tokens: 700,
              saved_total_tokens: 3100,
              saved_tokens_hit_rate: 1,
            },
            top_steps: [{ step_name: "content_profile", label: "内容摘要", total_tokens: 3100, jobs: 2, calls: 3, cache_hits: 1 }],
            top_models: [{ model: "MiniMax-M2.7-highspeed", provider: "minimax", total_tokens: 4100, jobs: 2, calls: 5 }],
            top_providers: [{ provider: "minimax", total_tokens: 4100, jobs: 2, calls: 5 }],
          },
        },
      }),
    );

    render(<OverviewPage />);

    expect(screen.getByText("overview.deck.title")).toBeInTheDocument();
    expect(screen.getAllByText("overview.focus.jobs.title")).toHaveLength(2);
    expect(screen.getAllByText("overview.focus.watch.title")).toHaveLength(2);
    expect(screen.getByText("jobs.summary.topSteps")).toBeInTheDocument();
    expect(screen.getByText("jobs.summary.cachePanel")).toBeInTheDocument();
  });

  it("keeps the overview focused on a single command deck instead of stacked dashboard cards", () => {
    mockUseOverviewWorkspace.mockReturnValue(
      buildWorkspace({
        jobs: {
          data: [
            {
              id: "job-1",
              source_name: "IMG_0041.MOV",
              content_summary: "箱包对比视频",
              content_subject: "箱包",
              updated_at: "2026-04-09T00:42:00Z",
              status: "needs_review",
            },
          ],
          isLoading: false,
          isError: false,
          error: null,
        },
      }),
    );

    render(<OverviewPage />);

    expect(screen.getByText("overview.deck.title")).toBeInTheDocument();
    expect(screen.getAllByText("overview.deck.actions")).toHaveLength(2);
    expect(screen.getAllByText("overview.focus.jobs.title")).toHaveLength(2);
    expect(screen.getAllByText("overview.focus.watch.title")).toHaveLength(2);
    expect(screen.getAllByText("overview.focus.runtime.title")).toHaveLength(2);
    expect(screen.getAllByText("IMG_0041.MOV")).toHaveLength(2);
    expect(screen.queryByText("overview.triage.title")).not.toBeInTheDocument();
  });

  it("shows a friendly preview fallback instead of leaking raw transport errors", () => {
    mockUseOverviewWorkspace.mockReturnValue(
      buildWorkspace({
        jobs: {
          data: [],
          isLoading: false,
          isError: true,
          error: new Error("预览模式下实时数据不可用。连接后端后可查看真实数据。"),
        },
      }),
    );

    render(<OverviewPage />);

    expect(screen.getByText("预览模式下实时数据不可用。连接后端后可查看真实数据。")).toBeInTheDocument();
    expect(screen.queryByText("File not found")).not.toBeInTheDocument();
  });
});
