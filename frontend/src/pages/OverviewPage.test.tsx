// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { MemoryRouter } from "react-router-dom";

import { OverviewPage } from "./OverviewPage";

const overviewWorkspaceMock = vi.hoisted(() => vi.fn());

vi.mock("../features/overview/useOverviewWorkspace", () => ({
  useOverviewWorkspace: () => overviewWorkspaceMock(),
}));

function buildOverviewWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    jobs: {
      isLoading: false,
      isError: false,
      error: null,
      data: [],
    },
    services: {
      data: {
        runtime: { readiness_status: "ready" },
        services: { api: true, orchestrator: true },
      },
    },
    usageSummary: {
      data: {
        total_tokens: 0,
        total_calls: 0,
        cache: { hit_rate: 0 },
        top_steps: [],
        top_models: [],
      },
    },
    glossary: { data: [] },
    stats: { jobs: 0, running: 0, glossary: 0 },
    ...overrides,
  };
}

describe("OverviewPage", () => {
  it("keeps the root page framed as a system overview", () => {
    overviewWorkspaceMock.mockReturnValue(buildOverviewWorkspace());

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("核心状态")).toBeInTheDocument();
    expect(screen.getByLabelText("工作入口")).toBeInTheDocument();
    expect(screen.getByText("当前队列")).toBeInTheDocument();
    expect(screen.getByText("运行健康")).toBeInTheDocument();
    expect(screen.queryByText("自动任务")).not.toBeInTheDocument();
    expect(screen.queryByText("自动目录")).not.toBeInTheDocument();
  });
});
