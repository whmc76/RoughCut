// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../../i18n";
import type { Job } from "../../types";
import { JobQueueTable } from "./JobQueueTable";

function buildJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    source_name: "成片测试.mp4",
    status: "done",
    language: "zh-CN",
    job_flow_mode: "auto",
    workflow_mode: "standard_edit",
    enhancement_modes: [],
    progress_percent: 100,
    created_at: "2026-06-18T10:00:00Z",
    updated_at: "2026-06-18T10:05:00Z",
    steps: [],
    ...overrides,
  };
}

function renderTable(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          {children}
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  window.localStorage.setItem("roughcut.ui.locale", "zh-CN");
  document.documentElement.lang = "zh-CN";
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("JobQueueTable handoff actions", () => {
  it("puts completed jobs' review action first without queue-level file or publish actions", () => {
    const onSelect = vi.fn();

    renderTable(
      <JobQueueTable
        jobs={[buildJob()]}
        selectedJobId={null}
        isLoading={false}
        onSelect={onSelect}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.getByRole("link", { name: "去审看" })).toHaveAttribute("href", "/final-review?job=job-1");
    const actions = screen.getAllByRole("link").map((link) => link.getAttribute("aria-label") ?? link.textContent);
    expect(actions[0]).toBe("去审看");
    expect(screen.queryByRole("link", { name: "发布交接" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开文件夹" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下载" })).not.toBeInTheDocument();
  });

  it("does not show the preview action before a job is complete", () => {
    renderTable(
      <JobQueueTable
        jobs={[buildJob({ status: "running", progress_percent: 42 })]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.queryByRole("link", { name: "去审看" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "发布交接" })).not.toBeInTheDocument();
  });
});
