// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FinalReviewPage } from "./FinalReviewPage";

const apiMock = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getJobDownloadFiles: vi.fn(),
  getContentProfile: vi.fn(),
  getJobActivity: vi.fn(),
  getJobReport: vi.fn(),
  getJobTokenUsage: vi.fn(),
  jobRenderedFileUrl: vi.fn(),
  finalReviewDecision: vi.fn(),
}));

vi.mock("../api", () => ({ api: apiMock }));

function renderPage(initialEntry = "/final-review") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/final-review" element={<FinalReviewPage />} />
          <Route path="/jobs/:jobId/manual-editor" element={<div data-testid="manual-editor-route">手动调整路由</div>} />
          <Route path="/publication-tracking" element={<div data-testid="publication-tracking-route">发布跟踪路由</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FinalReviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.getContentProfile.mockRejectedValue(new Error("content profile unavailable"));
    apiMock.getJobActivity.mockResolvedValue({
      job_id: "job-final-1",
      status: "done",
      review_step: "final_review",
      review_detail: null,
      current_step: null,
      render: null,
      decisions: [],
      events: [],
    });
    apiMock.getJobReport.mockResolvedValue({
      job_id: "job-final-1",
      generated_at: "2026-06-30T09:00:00Z",
      total_subtitle_items: 0,
      total_corrections: 0,
      corrections_by_type: {},
      pending_count: 0,
      accepted_count: 0,
      rejected_count: 0,
      items: [],
    });
    apiMock.getJobTokenUsage.mockResolvedValue({
      job_id: "job-final-1",
      has_telemetry: true,
      total_calls: 0,
      total_prompt_tokens: 0,
      total_completion_tokens: 0,
      total_tokens: 0,
      cache: {
        total_entries: 0,
        hits: 0,
        misses: 0,
        hit_rate: 0,
        avoided_calls: 0,
        steps_with_hits: 0,
        hits_with_usage_baseline: 0,
        saved_prompt_tokens: 0,
        saved_completion_tokens: 0,
        saved_total_tokens: 0,
        saved_tokens_hit_rate: 0,
      },
      steps: [],
      models: [],
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("reviews final render candidates with the audience checklist", async () => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-final-1",
        source_name: "发布候选成片.mp4",
        status: "done",
        language: "zh-CN",
        created_at: "2026-06-30T08:00:00Z",
        updated_at: "2026-06-30T09:00:00Z",
        steps: [],
        content_summary: "一条可进入发布前审看的成片。",
      },
      {
        id: "job-final-2",
        source_name: "已发布也可复审.mp4",
        status: "published",
        publication_status: "published",
        language: "zh-CN",
        created_at: "2026-06-29T08:00:00Z",
        updated_at: "2026-06-29T09:00:00Z",
        steps: [],
      },
      {
        id: "job-final-3",
        source_name: "final review 待处理.mp4",
        status: "needs_review",
        review_step: "final_review",
        language: "zh-CN",
        created_at: "2026-06-28T08:00:00Z",
        updated_at: "2026-06-28T09:00:00Z",
        steps: [],
      },
      {
        id: "job-running",
        source_name: "生产中不应出现.mp4",
        status: "running",
        language: "zh-CN",
        created_at: "2026-06-27T08:00:00Z",
        updated_at: "2026-06-27T09:00:00Z",
        steps: [],
      },
    ]);
    apiMock.getJobDownloadFiles.mockResolvedValue({
      job_id: "job-final-1",
      files: [
        { id: "packaged_mp4", label: "成片（标准剪辑版）", filename: "packaged.mp4", kind: "video", size_bytes: 2048, recommended: false },
        { id: "enhanced_mp4", label: "成片（最终增强版）", filename: "enhanced.mp4", kind: "video", size_bytes: 4096, recommended: true },
      ],
    });
    apiMock.jobRenderedFileUrl.mockImplementation((jobId: string, variant: string) => `/api/jobs/${jobId}/${variant}.mp4`);
    apiMock.finalReviewDecision.mockResolvedValue({ status: "ok" });

    const { container } = renderPage();

    expect((await screen.findAllByText("发布候选成片.mp4")).length).toBeGreaterThan(0);
    const videoList = screen.getByLabelText("待审看视频");
    expect(within(videoList).getByText("已发布也可复审.mp4")).toBeInTheDocument();
    expect(within(videoList).getByText("final review 待处理.mp4")).toBeInTheDocument();
    expect(within(videoList).queryByText("生产中不应出现.mp4")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "成片审看" })).toBeInTheDocument();
    expect(screen.getByLabelText("剪辑体验清单")).toBeInTheDocument();
    expect((await screen.findAllByText("最终增强版")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: /标准剪辑版/ })).toBeInTheDocument();
    const video = container.querySelector("video");
    expect(video).toHaveAttribute("src", "/api/jobs/job-final-1/enhanced.mp4");

    fireEvent.click(screen.getByRole("button", { name: /标准剪辑版/ }));
    await waitFor(() => {
      expect(container.querySelector("video")).toHaveAttribute("src", "/api/jobs/job-final-1/packaged.mp4");
    });

    for (const label of [
      /^符合：开头裁切保留必要上下文$/,
      /^符合：剪切点没有误删关键信息$/,
      /^符合：节奏压缩有效且不突兀$/,
      /^符合：字幕和包装不遮挡主体$/,
      /^符合：音频衔接和结尾完整$/,
    ]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
    }

    expect(screen.getByText("剪辑体验评估通过，可进入发布确认。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "通过并进入发布跟踪" })).toHaveAttribute("href", "/publication-tracking?job=job-final-1");
  });

  it("adapts the checklist to video type and topic, and keeps publication entry available for failed evaluations", async () => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-software-tutorial",
        source_name: "RunningHub 无限画布教程.mp4",
        status: "done",
        language: "zh-CN",
        workflow_template: "tutorial_standard",
        created_at: "2026-06-30T08:00:00Z",
        updated_at: "2026-06-30T09:00:00Z",
        steps: [
          {
            id: "step-edit",
            step_name: "edit_plan",
            status: "done",
            attempt: 1,
            started_at: "2026-06-30T08:00:00Z",
            finished_at: "2026-06-30T08:03:00Z",
            error_message: null,
          },
          {
            id: "step-render",
            step_name: "render",
            status: "done",
            attempt: 1,
            started_at: "2026-06-30T08:03:00Z",
            finished_at: "2026-06-30T08:07:30Z",
            error_message: null,
          },
        ],
        content_subject: "RunningHub 无限画布工作流",
        content_summary: "演示软件节点和参数设置。",
        quality_score: 82,
        quality_summary: "LLM 复核发现一个高风险剪切点需要人工确认。",
        quality_issue_codes: ["high_risk_cut_review"],
        timeline_diagnostics: {
          review_recommended: true,
          review_reasons: ["高风险 cut 需要复核"],
          high_risk_cut_count: 1,
          llm_reviewed: true,
          llm_candidate_count: 1,
          llm_restored_cut_count: 0,
          llm_provider: "zhipu",
          llm_summary: "候选剪切点靠近操作转折，建议人工确认。",
        },
      },
    ]);
    apiMock.getContentProfile.mockResolvedValue({
      job_id: "job-software-tutorial",
      status: "done",
      review_step_status: "done",
      ocr_evidence: {},
      transcript_evidence: {},
      entity_resolution_trace: {},
      workflow_mode: "tutorial",
      enhancement_modes: [],
      draft: null,
      final: {
        video_type: "tutorial",
        subject_domain: "software",
        video_theme: "软件工作流教程",
        content_understanding: {
          video_type: "tutorial",
          content_domain: "software",
        },
      },
      memory: null,
    });
    apiMock.getJobDownloadFiles.mockResolvedValue({
      job_id: "job-software-tutorial",
      files: [
        { id: "enhanced_mp4", label: "成片（最终增强版）", filename: "enhanced.mp4", kind: "video", size_bytes: 4096, recommended: true },
      ],
    });
    apiMock.jobRenderedFileUrl.mockReturnValue("/api/jobs/job-software-tutorial/enhanced.mp4");
    apiMock.getJobActivity.mockResolvedValue({
      job_id: "job-software-tutorial",
      status: "done",
      review_step: "final_review",
      review_detail: null,
      current_step: null,
      render: {
        status: "done",
        progress: 1,
        output_path: "data/runtime/output/software.mp4",
        updated_at: "2026-06-30T09:00:00Z",
      },
      decisions: [
        {
          kind: "edit_plan",
          step_name: "edit_plan",
          title: "剪辑决策",
          status: "done",
          summary: "建议移除 12 段，共 41.5 秒",
          detail: "silence 4 段；repeated_speech 3 段；low_signal_subtitle 5 段",
          updated_at: "2026-06-30T08:03:00Z",
        },
        {
          kind: "quality_assessment",
          step_name: "final_review",
          title: "质量评分",
          status: "done",
          summary: "B 82.0 · 1 个扣分项",
          detail: "问题：high_risk_cut_review；时间轴校验：高风险 cut 需要复核",
          issue_codes: ["high_risk_cut_review"],
          updated_at: "2026-06-30T09:00:00Z",
        },
      ],
      events: [],
    });
    apiMock.getJobReport.mockResolvedValue({
      job_id: "job-software-tutorial",
      generated_at: "2026-06-30T09:00:00Z",
      total_subtitle_items: 102,
      total_corrections: 18,
      corrections_by_type: { term: 11, punctuation: 7 },
      pending_count: 2,
      accepted_count: 16,
      rejected_count: 0,
      items: [],
    });
    apiMock.getJobTokenUsage.mockResolvedValue({
      job_id: "job-software-tutorial",
      has_telemetry: true,
      total_calls: 9,
      total_prompt_tokens: 21000,
      total_completion_tokens: 4500,
      total_tokens: 25500,
      cache: {
        total_entries: 3,
        hits: 1,
        misses: 2,
        hit_rate: 0.33,
        avoided_calls: 1,
        steps_with_hits: 1,
        hits_with_usage_baseline: 1,
        saved_prompt_tokens: 1200,
        saved_completion_tokens: 300,
        saved_total_tokens: 1500,
        saved_tokens_hit_rate: 0.06,
      },
      steps: [
        {
          step_name: "edit_plan",
          label: "剪辑",
          calls: 3,
          prompt_tokens: 10000,
          completion_tokens: 2000,
          total_tokens: 12000,
          last_updated_at: "2026-06-30T08:03:00Z",
          cache_entries: [],
          operations: [],
        },
      ],
      models: [],
    });
    apiMock.finalReviewDecision.mockResolvedValue({ status: "ok" });

    renderPage("/final-review?job=job-software-tutorial");

    await waitFor(() => {
      expect(screen.getAllByText("操作路径剪辑没有跳断").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("关键界面停留时间足够").length).toBeGreaterThan(0);
    const capabilityRegion = screen.getByLabelText("能力统计");
    expect(within(capabilityRegion).getByText("Token 消耗")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("25,500")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("字幕纠偏")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("18")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("智能删减")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("12 段")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("开头裁切保留必要上下文")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /^不符合：操作路径剪辑没有跳断$/ }));

    expect(screen.getByText("有 1 项不符合，建议退回手动调整；清单仅作评估，不阻挡进入发布跟踪。")).toBeInTheDocument();
    const issueRegion = screen.getByLabelText("问题记录");
    expect(within(issueRegion).getByText("质量评分")).toBeInTheDocument();
    expect(within(issueRegion).getAllByText(/high_risk_cut_review/).length).toBeGreaterThan(0);
    expect(within(issueRegion).queryByText("操作路径剪辑没有跳断")).not.toBeInTheDocument();
    const publicationLink = screen.getByRole("link", { name: "通过并进入发布跟踪" });
    expect(publicationLink).toHaveAttribute("href", "/publication-tracking?job=job-software-tutorial");
    expect(publicationLink).not.toHaveClass("is-disabled");

    fireEvent.click(publicationLink);

    await waitFor(() => {
      expect(apiMock.finalReviewDecision).toHaveBeenCalledWith("job-software-tutorial", {
        decision: "approve",
        note: "整体剪辑体验符合要求，建议通过并进入发布跟踪。",
      });
    });
    expect(await screen.findByTestId("publication-tracking-route")).toBeInTheDocument();
  });

  it("uses smart director checklist and director-specific capability stats", async () => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-director-1",
        source_name: "智能导演发布成片.mp4",
        status: "done",
        language: "zh-CN",
        queue_task_kind: "smart_director",
        workflow_mode: "smart_director",
        job_flow_mode: "smart_director",
        workflow_template: "smart_director_storyboard",
        task_brief: "智能导演分镜和包装生成任务",
        enhancement_modes: ["ai_effects", "dialogue_polish", "multi_platform_adaptation"],
        created_at: "2026-06-30T08:00:00Z",
        updated_at: "2026-06-30T09:00:00Z",
        steps: [],
        timeline_diagnostics: {
          llm_reviewed: true,
          llm_candidate_count: 3,
          llm_restored_cut_count: 1,
          protected_visual_cut_count: 4,
          high_protection_evidence_count: 9,
          llm_summary: "智能导演复核了高风险镜头切点。",
        },
      },
    ]);
    apiMock.getJobDownloadFiles.mockResolvedValue({
      job_id: "job-director-1",
      files: [
        { id: "enhanced_mp4", label: "成片（最终增强版）", filename: "enhanced.mp4", kind: "video", size_bytes: 4096, recommended: true },
      ],
    });
    apiMock.jobRenderedFileUrl.mockReturnValue("/api/jobs/job-director-1/enhanced.mp4");
    apiMock.getJobActivity.mockResolvedValue({
      job_id: "job-director-1",
      status: "done",
      review_step: "final_review",
      review_detail: null,
      current_step: null,
      render: null,
      decisions: [
        {
          kind: "edit_plan",
          step_name: "edit_plan",
          title: "导演计划",
          status: "done",
          summary: "完成 5 个叙事段落编排",
          detail: "开场钩子、主体展示、反转、结尾导向已对齐。",
          updated_at: "2026-06-30T08:03:00Z",
        },
        {
          kind: "dialogue_polish",
          step_name: "dialogue_polish",
          title: "台词润色",
          status: "done",
          summary: "生成 6 段旁白和转场台词",
          detail: "补齐开场钩子、段落转折和结尾 CTA。",
          updated_at: "2026-06-30T08:10:00Z",
        },
      ],
      events: [],
    });
    apiMock.getJobTokenUsage.mockResolvedValue({
      job_id: "job-director-1",
      has_telemetry: true,
      total_calls: 5,
      total_prompt_tokens: 18000,
      total_completion_tokens: 3000,
      total_tokens: 21000,
      cache: {},
      steps: [
        {
          step_name: "smart_director",
          label: "智能导演",
          calls: 2,
          prompt_tokens: 14000,
          completion_tokens: 2500,
          total_tokens: 16500,
          last_updated_at: "2026-06-30T08:10:00Z",
          cache_entries: [],
          operations: [],
        },
      ],
      models: [],
    });

    renderPage("/final-review?job=job-director-1");

    await waitFor(() => {
      expect(screen.getAllByText("导演计划落地到成片节奏").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("B-roll、字幕和音频同步").length).toBeGreaterThan(0);
    expect(screen.queryByText("开头裁切保留必要上下文")).not.toBeInTheDocument();
    const capabilityRegion = screen.getByLabelText("能力统计");
    expect(within(capabilityRegion).getByText("导演编排")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("2 项")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("解说重组")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("6 段")).toBeInTheDocument();
  });

  it("uses film remix checklist and remix-specific capability stats", async () => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-remix-1",
        source_name: "影视二创解说成片.mp4",
        status: "done",
        language: "zh-CN",
        queue_task_kind: "remix_production",
        workflow_mode: "script_footage_remix",
        job_flow_mode: "remix",
        workflow_template: "film_remix_commentary",
        task_brief: "影视二创解说混剪任务",
        enhancement_modes: ["dialogue_polish", "multi_platform_adaptation"],
        created_at: "2026-06-30T08:00:00Z",
        updated_at: "2026-06-30T09:00:00Z",
        steps: [],
      },
    ]);
    apiMock.getJobDownloadFiles.mockResolvedValue({
      job_id: "job-remix-1",
      files: [
        { id: "enhanced_mp4", label: "成片（最终增强版）", filename: "enhanced.mp4", kind: "video", size_bytes: 4096, recommended: true },
      ],
    });
    apiMock.jobRenderedFileUrl.mockReturnValue("/api/jobs/job-remix-1/enhanced.mp4");
    apiMock.getJobActivity.mockResolvedValue({
      job_id: "job-remix-1",
      status: "done",
      review_step: "final_review",
      review_detail: null,
      current_step: null,
      render: null,
      decisions: [
        {
          kind: "edit_plan",
          step_name: "edit_plan",
          title: "二创剪辑决策",
          status: "done",
          summary: "建议移除 20 段，共 180.0 秒",
          detail: "low_signal_subtitle 8 段；repeated_speech 5 段；silence 7 段",
          updated_at: "2026-06-30T08:03:00Z",
        },
        {
          kind: "dialogue_polish",
          step_name: "dialogue_polish",
          title: "解说重组",
          status: "done",
          summary: "生成 12 段剧情解说",
          detail: "按反转和人物关系重排旁白。",
          updated_at: "2026-06-30T08:10:00Z",
        },
      ],
      events: [],
    });

    renderPage("/final-review?job=job-remix-1");

    await waitFor(() => {
      expect(screen.getAllByText("原片剧情和人物关系未剪断").length).toBeGreaterThan(0);
    });
    expect(screen.getAllByText("解说与画面证据同步").length).toBeGreaterThan(0);
    expect(screen.queryByText("字幕和包装不遮挡主体")).not.toBeInTheDocument();
    const capabilityRegion = screen.getByLabelText("能力统计");
    expect(within(capabilityRegion).getByText("二创编排")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("20 段")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("噪音/冗余清理")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("20 处")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("解说重组")).toBeInTheDocument();
    expect(within(capabilityRegion).getByText("12 段")).toBeInTheDocument();
  });

  it("routes rejected final review work to the manual editor", async () => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-final-1",
        source_name: "需要调整成片.mp4",
        status: "done",
        language: "zh-CN",
        created_at: "2026-06-30T08:00:00Z",
        updated_at: "2026-06-30T09:00:00Z",
        steps: [],
      },
    ]);
    apiMock.getJobDownloadFiles.mockResolvedValue({
      job_id: "job-final-1",
      files: [
        { id: "enhanced_mp4", label: "成片（最终增强版）", filename: "enhanced.mp4", kind: "video", size_bytes: 4096, recommended: true },
      ],
    });
    apiMock.jobRenderedFileUrl.mockReturnValue("/api/jobs/job-final-1/enhanced.mp4");
    apiMock.finalReviewDecision.mockResolvedValue({ status: "ok" });

    renderPage("/final-review?job=job-final-1");

    const returnLink = await screen.findByRole("link", { name: "退回手动调整" });
    expect(returnLink).toHaveAttribute("href", "/jobs/job-final-1/manual-editor");

    fireEvent.click(returnLink);

    await waitFor(() => {
      expect(apiMock.finalReviewDecision).toHaveBeenCalledWith("job-final-1", {
        decision: "reject",
        note: "整体剪辑体验符合要求，建议通过并进入发布跟踪。",
      });
    });
    expect(await screen.findByTestId("manual-editor-route")).toBeInTheDocument();
  });
});
