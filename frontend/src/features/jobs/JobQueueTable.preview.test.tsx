// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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

describe("JobQueueTable preview action", () => {
  it("shows an inline preview action for completed jobs without selecting the row", () => {
    const onPreview = vi.fn();
    const onSelect = vi.fn();

    renderTable(
      <JobQueueTable
        jobs={[buildJob()]}
        selectedJobId={null}
        isLoading={false}
        onSelect={onSelect}
        onPreview={onPreview}
        onOpenFolder={vi.fn()}
        onDownload={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "播放" }));

    expect(onPreview).toHaveBeenCalledWith("job-1");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("does not show the preview action before a job is complete", () => {
    renderTable(
      <JobQueueTable
        jobs={[buildJob({ status: "running", progress_percent: 42 })]}
        selectedJobId={null}
        isLoading={false}
        onSelect={vi.fn()}
        onOpenFolder={vi.fn()}
        onDownload={vi.fn()}
        onCancel={vi.fn()}
        onRestart={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    expect(screen.queryByRole("button", { name: "播放" })).not.toBeInTheDocument();
  });
});
