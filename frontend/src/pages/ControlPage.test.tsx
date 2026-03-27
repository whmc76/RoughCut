import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

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
    orchestrator_lock: {
      status: "held",
      leader_active: true,
      detail: "active leader",
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
    status: { data: SAMPLE_STATUS, isLoading: false, isError: false, error: null },
    healthDetail: { data: SAMPLE_HEALTH, isLoading: false, isError: false, error: null },
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
  });
});
