// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicationTrackingPage } from "./PublicationTrackingPage";

const apiMock = vi.hoisted(() => ({
  listJobs: vi.fn(),
  getJobPublicationPlan: vi.fn(),
  getIntelligentCopyGenerateTask: vi.fn(),
  getRecentPublicationAttempts: vi.fn(),
  createJobPublicationMaterialTask: vi.fn(),
  backfillJobManualPublicationResult: vi.fn(),
  openPublicationEntry: vi.fn(),
  openJobFolder: vi.fn(),
  jobRenderedFileUrl: vi.fn(),
}));

vi.mock("../api", () => ({
  api: apiMock,
}));

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        {children}
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PublicationTrackingPage", () => {
  beforeEach(() => {
    apiMock.listJobs.mockResolvedValue([
      {
        id: "job-fas",
        source_name: "FAS 常规成片.mov",
        creator_card_id: "creator-fas",
        creator_card_name: "FAS",
        queue_task_kind: "edit",
        status: "done",
        language: "zh-CN",
        workflow_mode: "standard_edit",
        job_flow_mode: "auto",
        enhancement_modes: [],
        created_at: "2026-06-30T08:00:00+08:00",
        updated_at: "2026-06-30T09:00:00+08:00",
        steps: [],
      },
      {
        id: "job-jenny",
        source_name: "珍妮混剪成片.mov",
        creator_card_id: "creator-jenny",
        creator_card_name: "珍妮",
        queue_task_kind: "remix_production",
        status: "done",
        language: "zh-CN",
        workflow_mode: "script_footage_remix",
        job_flow_mode: "auto",
        enhancement_modes: [],
        created_at: "2026-06-29T08:00:00+08:00",
        updated_at: "2026-06-29T09:00:00+08:00",
        steps: [],
      },
      {
        id: "job-publication",
        source_name: "无绑定发布任务.mov",
        queue_task_kind: "publication",
        status: "done",
        language: "zh-CN",
        workflow_mode: "standard_edit",
        job_flow_mode: "auto",
        enhancement_modes: [],
        created_at: "2026-06-28T08:00:00+08:00",
        updated_at: "2026-06-28T09:00:00+08:00",
        steps: [],
      },
    ]);
    apiMock.getJobPublicationPlan.mockResolvedValue({
      status: "ready",
      media_path: "",
      creator_profile_id: "creator-fas",
      creator_profile_name: "FAS",
      creator_default_platforms: [],
      creator_platform_option_platforms: [],
      platform_options: {},
      material_targets: [],
      targets: [],
      manual_handoff_targets: [],
      existing_attempts: [],
    });
    apiMock.getRecentPublicationAttempts.mockResolvedValue({ attempts: [] });
    apiMock.jobRenderedFileUrl.mockReturnValue("");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("filters the video list by expandable creator and clip-type tags", async () => {
    renderWithQueryClient(<PublicationTrackingPage />);

    await screen.findAllByText("FAS 常规成片.mov");
    const videoList = screen.getByLabelText("待发布视频");
    expect(within(videoList).getByText("FAS 常规成片.mov")).toBeInTheDocument();
    expect(within(videoList).getByText("珍妮混剪成片.mov")).toBeInTheDocument();
    expect(within(videoList).getByText("无绑定发布任务.mov")).toBeInTheDocument();

    expect(screen.getByRole("button", { name: /标签筛选/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: "今天" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "最近三天" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "七天" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /FAS\s*1/ }));

    await waitFor(() => {
      const filteredList = screen.getByLabelText("待发布视频");
      expect(within(filteredList).getByText("FAS 常规成片.mov")).toBeInTheDocument();
      expect(within(filteredList).queryByText("珍妮混剪成片.mov")).not.toBeInTheDocument();
      expect(within(filteredList).queryByText("无绑定发布任务.mov")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /清除筛选/ }));
    fireEvent.click(screen.getByRole("button", { name: /混剪制作\s*1/ }));

    await waitFor(() => {
      const filteredList = screen.getByLabelText("待发布视频");
      expect(within(filteredList).queryByText("FAS 常规成片.mov")).not.toBeInTheDocument();
      expect(within(filteredList).getByText("珍妮混剪成片.mov")).toBeInTheDocument();
      expect(within(filteredList).queryByText("无绑定发布任务.mov")).not.toBeInTheDocument();
    });
  });

  it("does not render a title copy field for platforms without standalone titles", async () => {
    apiMock.getJobPublicationPlan.mockResolvedValueOnce({
      status: "ready",
      media_path: "",
      creator_profile_id: "creator-fas",
      creator_profile_name: "FAS",
      creator_default_platforms: ["kuaishou"],
      creator_platform_option_platforms: [],
      platform_options: {},
      material_targets: [
        {
          platform: "kuaishou",
          platform_label: "快手",
          credential_id: "cred-kuaishou",
          account_label: "FAS",
          adapter: "browser_agent",
          execution_mode: "manual_handoff",
          content_kind: "video",
          has_title: false,
          title_label: "",
          body_label: "作品描述",
          tag_label: "嵌入作品描述的话题",
          separate_tags: false,
          tags_embedded_in_body: true,
          constraints: {
            title_limit: 0,
            body_limit: 300,
            tag_limit: 4,
            tag_style: "hashtags_space",
            cover_size: { width: 1080, height: 1440 },
            rule_note: "按作品描述输出。",
          },
          title: "",
          titles: [],
          body: "快手正文 #EDC",
          description: "快手正文 #EDC",
          tags: ["EDC"],
          tags_copy: "#EDC",
          full_copy: "快手正文 #EDC",
          cover_path: "E:/materials/kuaishou-cover.jpg",
          status: "material_ready",
          enabled: true,
        },
      ],
      targets: [],
      manual_handoff_targets: [],
      existing_attempts: [],
    });

    renderWithQueryClient(<PublicationTrackingPage />);

    const kuaishouButtons = await screen.findAllByRole("button", { name: /快手\s*FAS/ });
    const kuaishouExpandButton = kuaishouButtons.find((button) => button.classList.contains("publication-tracking-platform-expand"));
    if (!kuaishouExpandButton) throw new Error("Missing Kuaishou expand button.");
    fireEvent.click(kuaishouExpandButton);

    const bodyLabel = await screen.findByText("作品描述");
    const materialGrid = bodyLabel.closest(".publication-material-grid");
    expect(materialGrid).not.toBeNull();
    expect(within(materialGrid as HTMLElement).queryByText("标题")).not.toBeInTheDocument();
    expect(within(materialGrid as HTMLElement).queryByRole("button", { name: /复制标题/ })).not.toBeInTheDocument();
    expect(within(materialGrid as HTMLElement).queryByText("嵌入作品描述的话题")).not.toBeInTheDocument();
    expect(within(materialGrid as HTMLElement).getByText("快手正文 #EDC")).toBeInTheDocument();
  });

  it("shows collection and playlist publication rules in expanded materials", async () => {
    apiMock.getJobPublicationPlan.mockResolvedValueOnce({
      status: "ready",
      media_path: "",
      creator_profile_id: "creator-fas",
      creator_profile_name: "FAS",
      creator_default_platforms: ["youtube"],
      creator_platform_option_platforms: [],
      platform_options: {},
      material_targets: [
        {
          platform: "youtube",
          platform_label: "YouTube",
          credential_id: "cred-youtube",
          account_label: "FAS",
          adapter: "browser_agent",
          execution_mode: "manual_handoff",
          content_kind: "video",
          has_title: true,
          title_label: "标题",
          body_label: "说明",
          tag_label: "标签",
          separate_tags: true,
          tags_embedded_in_body: false,
          constraints: {
            title_limit: 100,
            body_limit: 5000,
            tag_limit: 15,
            tag_style: "csv",
            cover_size: { width: 1280, height: 720 },
            rule_note: "YouTube 发布规则。",
          },
          title: "YouTube 标题",
          titles: ["YouTube 标题"],
          body: "YouTube 说明",
          description: "YouTube 说明",
          tags: ["EDC"],
          tags_copy: "EDC",
          full_copy: "YouTube 完整文案",
          cover_path: "E:/materials/youtube-cover.jpg",
          collection: { name: "新建播放列表" },
          platform_specific_overrides: {
            collection_management: {
              kind: "playlist",
              status: "needs_create",
              target_collection_name: "EDC刀光火工具集",
              create_required: true,
            },
          },
          status: "material_ready",
          enabled: true,
        },
      ],
      targets: [],
      manual_handoff_targets: [],
      existing_attempts: [],
    });

    renderWithQueryClient(<PublicationTrackingPage />);

    const youtubeButtons = await screen.findAllByRole("button", { name: /YouTube\s*FAS/ });
    const youtubeExpandButton = youtubeButtons.find((button) => button.classList.contains("publication-tracking-platform-expand"));
    if (!youtubeExpandButton) throw new Error("Missing YouTube expand button.");
    fireEvent.click(youtubeExpandButton);

    const playlistLabel = await screen.findByText("播放列表");
    const materialGrid = playlistLabel.closest(".publication-material-grid");
    expect(materialGrid).not.toBeNull();
    expect(within(materialGrid as HTMLElement).getByText("EDC刀光火工具集 · 需新建")).toBeInTheDocument();
    expect(within(materialGrid as HTMLElement).queryByText("新建播放列表")).not.toBeInTheDocument();
  });

  it("opens platform publication entries through the bound creator browser account", async () => {
    apiMock.openPublicationEntry.mockResolvedValue({
      opened: true,
      url: "https://member.example.com/platform/upload/video/frame",
      used_binding: true,
      mode: "browser_profile",
      message: "ok",
    });
    apiMock.getJobPublicationPlan.mockResolvedValueOnce({
      status: "ready",
      media_path: "",
      creator_profile_id: "creator-fas",
      creator_profile_name: "FAS",
      creator_default_platforms: ["bilibili"],
      creator_platform_option_platforms: [],
      platform_options: {},
      material_targets: [
        {
          platform: "bilibili",
          platform_label: "B站",
          credential_id: "cred-bilibili",
          credential_ref: "browser-agent:chrome:creator-fas:bilibili",
          browser_profile_id: "browser-profile:chrome:21104fd69d72ad7267c2",
          browser_binding: {
            browser: "chrome",
            user_data_dir: "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
            profile_directory: "Profile 2",
            profile_id: "browser-profile:chrome:21104fd69d72ad7267c2",
          },
          account_label: "FAS · Chrome",
          adapter: "browser_agent",
          title: "B站标题",
          titles: ["B站标题"],
          body: "B站正文",
          tags: ["EDC"],
          manual_publish_entry_url: "https://member.example.com/platform/upload/video/frame",
          status: "material_ready",
          enabled: true,
        },
      ],
      targets: [],
      manual_handoff_targets: [],
      existing_attempts: [],
    });

    renderWithQueryClient(<PublicationTrackingPage />);

    const bilibiliRow = await waitFor(() => {
      const row = screen
        .getAllByText("B站")
        .map((element) => element.closest(".publication-tracking-platform-summary") as HTMLElement | null)
        .find((element): element is HTMLElement => Boolean(element)) ?? null;
      if (!row) throw new Error("Missing Bilibili publication row.");
      return row;
    });
    fireEvent.click(within(bilibiliRow).getByRole("button", { name: "打开发布页" }));

    await waitFor(() => {
      expect(apiMock.openPublicationEntry).toHaveBeenCalledWith({
        url: "https://member.example.com/platform/upload/video/frame",
        platform: "bilibili",
        account_label: "FAS · Chrome",
        credential_ref: "browser-agent:chrome:creator-fas:bilibili",
        browser_profile_id: "browser-profile:chrome:21104fd69d72ad7267c2",
        browser_binding: {
          browser: "chrome",
          user_data_dir: "C:/Users/demo/AppData/Local/Google/Chrome/User Data",
          profile_directory: "Profile 2",
          profile_id: "browser-profile:chrome:21104fd69d72ad7267c2",
        },
      });
    });
  });
});
