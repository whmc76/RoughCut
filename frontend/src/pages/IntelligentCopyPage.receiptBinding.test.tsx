// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { IntelligentCopyPage } from "./IntelligentCopyPage";

const workspaceMocks = vi.hoisted(() => ({
  useIntelligentCopyWorkspace: vi.fn(),
}));

vi.mock("../features/intelligentCopy/useIntelligentCopyWorkspace", async () => {
  const actual = await vi.importActual<typeof import("../features/intelligentCopy/useIntelligentCopyWorkspace")>(
    "../features/intelligentCopy/useIntelligentCopyWorkspace",
  );
  return {
    ...actual,
    useIntelligentCopyWorkspace: workspaceMocks.useIntelligentCopyWorkspace,
  };
});

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  workspaceMocks.useIntelligentCopyWorkspace.mockReset();
});

function buildAttempt() {
  return {
    id: "attempt-1",
    job_id: "job-1",
    creator_profile_id: "creator-1",
    creator_profile_name: "FAS",
    platform: "douyin",
    platform_label: "抖音",
    account_label: "FAS 主号",
    credential_id: "cred-1",
    adapter: "browser_agent",
    status: "published",
    run_status: "published",
    operator_summary: "已通过发布后回执绑定确认本次作品。",
    external_receipt_id: "receipt-binding:abc123",
    external_url: "https://www.douyin.com/video/123",
    public_url: "https://www.douyin.com/video/123",
    created_at: "2026-06-01T12:00:00Z",
    updated_at: "2026-06-01T12:05:00Z",
    runs: [
      {
        id: "run-1",
        attempt_id: "attempt-1",
        status: "published",
        phase: "completed",
        provider_task_id: "task-1",
        created_at: "2026-06-01T12:00:00Z",
        updated_at: "2026-06-01T12:05:00Z",
      },
    ],
  };
}

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  const attempt = buildAttempt();
  return {
    folderPath: "E:/materials/maxace",
    setFolderPath: vi.fn(),
    folderPathAutocompleteOptions: [],
    parentFolderSuggestions: [],
    copyStyle: "attention_grabbing",
    setCopyStyle: vi.fn(),
    useExistingCover: false,
    setUseExistingCover: vi.fn(),
    copyFeedback: "",
    inspect: { isPending: false, error: null, mutate: vi.fn() },
    generate: { isPending: false, error: null, mutate: vi.fn() },
    inspection: {
      video_file: "E:/materials/maxace/output.mp4",
      subtitle_file: "E:/materials/maxace/output.srt",
      cover_file: null,
      material_dir: "E:/materials/maxace/smart-copy",
      warnings: [],
    },
    materialPlatformOptions: [],
    selectedMaterialPlatformIds: [],
    toggleMaterialPlatform: vi.fn(),
    selectAllMaterialPlatforms: vi.fn(),
    recentGenerateTasks: { data: { tasks: [] }, isLoading: false },
    selectedGenerateTaskId: "",
    setSelectedGenerateTaskId: vi.fn(),
    selectedGenerateTask: null,
    selectedGenerateTaskQuery: { isLoading: false },
    result: {
      publish_ready: true,
      blocking_reasons: [],
      manual_handoff_ready: false,
      manual_handoff_targets: [],
      cover_source_path: "",
      material_dir: "E:/materials/maxace/smart-copy",
      platforms: [
        {
          key: "douyin",
          label: "抖音",
          has_title: true,
          titles: ["MAXACE 美杜莎4 顶配次顶配开箱"],
          primary_title: "MAXACE 美杜莎4 顶配次顶配开箱",
          body: "正文",
          tags: ["EDC折刀"],
          blocking_reasons: [],
        },
      ],
    },
    publicationProfiles: [],
    selectedPublicationProfileId: "",
    setSelectedPublicationProfileId: vi.fn(),
    selectedPublicationBrowser: "chrome",
    setSelectedPublicationBrowser: vi.fn(),
    publicationBrowserOptions: [{ id: "chrome", label: "Google Chrome" }],
    publicationLoginMatchMessage: "",
    matchPublicationBrowserLogin: { isPending: false, mutate: vi.fn() },
    avatarMaterials: { isLoading: false },
    publicationPlan: {
      isLoading: false,
      data: {
        publish_ready: true,
        blocked_reasons: [],
        warnings: [],
        targets: [
          {
            platform: "douyin",
            platform_label: "抖音",
            account_label: "FAS 主号",
            title: "MAXACE 美杜莎4 顶配次顶配开箱",
          },
        ],
        existing_attempts: [attempt],
        created_attempts: [],
      },
    },
    selectedPlatformIds: ["douyin"],
    togglePlatform: vi.fn(),
    publicationScheme: null,
    publicationSchemeInstruction: "",
    setPublicationSchemeInstruction: vi.fn(),
    generatePublicationScheme: { isPending: false, error: null, mutate: vi.fn() },
    modifyPublicationScheme: { isPending: false, error: null, mutate: vi.fn() },
    publish: { isPending: false, error: null, mutate: vi.fn() },
    recentPublicationAttempts: { data: { attempts: [attempt] }, isLoading: false },
    selectedPublicationAttempt: attempt,
    selectedPublicationAttemptId: "attempt-1",
    setSelectedPublicationAttemptId: vi.fn(),
    openFolder: { mutate: vi.fn() },
    copyText: vi.fn(),
    ...overrides,
  };
}

describe("IntelligentCopyPage receipt binding visibility", () => {
  it("shows the unique receipt binding id in both progress and history panels", async () => {
    workspaceMocks.useIntelligentCopyWorkspace.mockReturnValue(buildWorkspace());

    render(
      <MemoryRouter>
        <IntelligentCopyPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: /一键发布/ }));

    const receiptBadges = await screen.findAllByText("回执：receipt-binding:abc123");
    expect(receiptBadges.length).toBeGreaterThanOrEqual(2);
  });

  it("shows blocking reasons from material_contract even when root publish_ready is stale true", async () => {
    workspaceMocks.useIntelligentCopyWorkspace.mockReturnValue(buildWorkspace({
      result: {
        publish_ready: true,
        blocking_reasons: [],
        material_contract: {
          status: "failed",
          blocking_reasons: ["缺少 live_publish_preflight"],
        },
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        cover_source_path: "",
        material_dir: "E:/materials/maxace/smart-copy",
        platforms: [
          {
            key: "douyin",
            label: "抖音",
            has_title: true,
            titles: ["MAXACE 美杜莎4 顶配次顶配开箱"],
            primary_title: "MAXACE 美杜莎4 顶配次顶配开箱",
            body: "正文",
            tags: ["EDC折刀"],
            blocking_reasons: [],
          },
        ],
      },
    }));

    render(
      <MemoryRouter>
        <IntelligentCopyPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("缺少 live_publish_preflight")).toBeInTheDocument();
  });

  it("shows manual handoff targets even when only legacy root targets remain and publish_ready is stale true", async () => {
    workspaceMocks.useIntelligentCopyWorkspace.mockReturnValue(buildWorkspace({
      result: {
        publish_ready: true,
        blocking_reasons: [],
        manual_handoff_ready: false,
        manual_handoff_targets: [
          {
            platform: "wechat-channels",
            label: "视频号",
            login_url: "https://channels.weixin.qq.com/login.html",
          },
        ],
        cover_source_path: "",
        material_dir: "E:/materials/maxace/smart-copy",
        platforms: [
          {
            key: "douyin",
            label: "抖音",
            has_title: true,
            titles: ["MAXACE 美杜莎4 顶配次顶配开箱"],
            primary_title: "MAXACE 美杜莎4 顶配次顶配开箱",
            body: "正文",
            tags: ["EDC折刀"],
            blocking_reasons: [],
          },
        ],
      },
    }));

    render(
      <MemoryRouter>
        <IntelligentCopyPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("视频号")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开登录页" })).toBeInTheDocument();
  });

  it("shows publication executor preflight messages from the publication plan", async () => {
    workspaceMocks.useIntelligentCopyWorkspace.mockReturnValue(buildWorkspace({
      publicationPlan: {
        isLoading: false,
        data: {
          publish_ready: false,
          blocked_reasons: ["browser-agent 不支持正式发布。"],
          publication_executor_preflight: {
            ready: false,
            message: "browser-agent 不支持正式发布。",
            failures: ["缺少平台发布页标签"],
          },
          warnings: [],
          targets: [],
          existing_attempts: [buildAttempt()],
          created_attempts: [],
        },
      },
    }));

    render(
      <MemoryRouter>
        <IntelligentCopyPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("tab", { name: /一键发布/ }));

    const preflightMessages = await screen.findAllByText("browser-agent 不支持正式发布。");
    expect(preflightMessages.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("缺少平台发布页标签")).toBeInTheDocument();
  });
});
