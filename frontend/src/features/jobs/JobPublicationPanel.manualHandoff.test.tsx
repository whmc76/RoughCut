// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildJobPublicationDraftContextKey,
  buildJobPublicationPlanQueryKey,
  JobPublicationPanel,
} from "./JobPublicationPanel";
import type { Job } from "../../types";

const reactQueryMocks = vi.hoisted(() => ({
  useQueryClient: vi.fn(() => ({
    setQueryData: vi.fn(),
    invalidateQueries: vi.fn(async () => undefined),
  })),
  useQuery: vi.fn(),
  useMutation: vi.fn(),
}));

vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual<typeof import("@tanstack/react-query")>("@tanstack/react-query");
  return {
    ...actual,
    useQueryClient: reactQueryMocks.useQueryClient,
    useQuery: reactQueryMocks.useQuery,
    useMutation: reactQueryMocks.useMutation,
  };
});

function buildJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    source_name: "MAXACE 美杜莎4 顶配次顶配开箱",
    status: "done",
    language: "zh-CN",
    job_flow_mode: "standard",
    workflow_mode: "standard",
    enhancement_modes: [],
    created_at: "2026-06-01T12:00:00Z",
    updated_at: "2026-06-01T12:05:00Z",
    steps: [],
    ...overrides,
  };
}

function renderPanel(job: Job) {
  return render(
    <MemoryRouter>
      <JobPublicationPanel job={job} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  reactQueryMocks.useQueryClient.mockClear();
  reactQueryMocks.useQuery.mockReset();
  reactQueryMocks.useMutation.mockReset();
});

describe("JobPublicationPanel manual handoff UI", () => {
  it("renders the manual handoff action and opens the login URL", async () => {
    const windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);

    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "manual_handoff",
            publish_ready: false,
            manual_handoff_ready: true,
            manual_handoff_targets: [
              {
                platform: "wechat-channels",
                label: "视频号",
                status: "manual_handoff",
                login_url: "https://channels.weixin.qq.com/login.html",
              },
            ],
            blocked_reasons: ["以下平台已切换为人工登录/人工发布，不再进入自动一键发布：视频号。"],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob());

    expect(await screen.findByText("视频号")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "打开人工登录页" });
    fireEvent.click(button);

    await waitFor(() => {
      expect(windowOpen).toHaveBeenCalledWith(
        "https://channels.weixin.qq.com/login.html",
        "_blank",
        "noopener,noreferrer",
      );
    });
  });

  it("defaults to the job-bound creator instead of the first legacy profile", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              { id: "legacy-other", display_name: "Other Creator" },
              { id: "legacy-fas", display_name: "FAS Legacy" },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "ready",
            publish_ready: true,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: [],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            material_targets: [],
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob({ creator_card_id: "creator-card-fas", creator_card_name: "FAS" }));

    expect(await screen.findByRole("combobox", { name: /创作者卡片/ })).toHaveValue("__job_bound_creator__");
    expect(screen.getByText("已绑定：FAS")).toBeInTheDocument();
  });

  it("uses the plan creator profile credentials for a job-bound creator before materials exist", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
                creator_profile: {
                  publishing: {
                    platform_credentials: [
                      {
                        id: "cred-douyin",
                        platform: "douyin",
                        platform_label: "抖音",
                        account_label: "FAS",
                        credential_ref: "chrome-profile:fas",
                        status: "logged_in",
                        enabled: true,
                        adapter: "browser_agent",
                      },
                    ],
                  },
                },
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "blocked",
            publish_ready: false,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: ["缺少多平台发布文案包，请先完成 platform_package。"],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            material_targets: [],
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob({ creator_card_id: "creator-card-fas", creator_card_name: "FAS" }));

    expect(await screen.findByLabelText("抖音")).toBeChecked();
    expect(screen.queryByText("当前创作者卡片没有启用的平台凭据。")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "配置发布凭据" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成物料" })).not.toBeDisabled();
  });

  it("progressively renders material platforms while the publication plan is loading", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: { profiles: [] },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: undefined,
          isLoading: true,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob({ creator_card_id: "4668c6ac-2168-49ef-99f3-e26badfef99a" }));

    expect(await screen.findByRole("combobox", { name: /创作者卡片/ })).toHaveValue("__job_bound_creator__");
    expect(screen.getByText("已绑定创作者（名称载入中）")).toBeInTheDocument();
    expect(screen.queryByText(/4668c6ac/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /小红书/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /快手/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /头条/ })).toBeInTheDocument();
    expect(screen.getByText("物料详情正在补齐")).toBeInTheDocument();
    expect(screen.getByText("正在补齐物料详情，平台可先选择。")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "生成物料" })).not.toBeDisabled();
    });
  });

  it("shows an explicit unbound creator option instead of selecting the first profile", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              { id: "legacy-other", display_name: "Other Creator" },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "blocked",
            publish_ready: false,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: ["创作者档案没有可发布的 browser-agent 登录凭据绑定。"],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "",
            creator_profile_name: "",
            media_path: "E:/materials/maxace/output.mp4",
            material_targets: [],
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob());

    expect(await screen.findByRole("combobox", { name: /创作者卡片/ })).toHaveValue("__job_unbound_creator__");
    expect(screen.getByText("未绑定创作者")).toBeInTheDocument();
  });

  it("links to publication credential setup when no enabled platform credentials are available", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
                creator_profile: {
                  publishing: {
                    platform_credentials: [],
                  },
                },
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "blocked",
            publish_ready: false,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: ["缺少多平台发布文案包，请先完成 platform_package。"],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            material_targets: [],
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob({ creator_card_id: "creator-card-fas", creator_card_name: "FAS" }));

    expect(await screen.findByText("当前创作者卡片没有启用的平台凭据。")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "配置发布凭据" })).toHaveAttribute("href", "/tools/avatar");
    expect(screen.getByRole("link", { name: "去配置" })).toHaveAttribute("href", "/tools/avatar");
    expect(screen.getByRole("button", { name: "生成物料" })).toBeDisabled();
  });

  it("refreshes the job publication plan query identity when the job is updated", () => {
    const firstKey = buildJobPublicationPlanQueryKey(
      "job-1",
      "creator-1",
      "2026-06-01T12:05:00Z",
    );
    const refreshedKey = buildJobPublicationPlanQueryKey(
      "job-1",
      "creator-1",
      "2026-06-01T12:06:00Z",
    );
    const switchedProfileKey = buildJobPublicationPlanQueryKey(
      "job-1",
      "creator-2",
      "2026-06-01T12:06:00Z",
    );

    expect(refreshedKey).not.toEqual(firstKey);
    expect(switchedProfileKey).not.toEqual(refreshedKey);
  });

  it("invalidates the job publication draft context when the job snapshot or profile changes", () => {
    const firstKey = buildJobPublicationDraftContextKey(
      "job-1",
      "creator-1",
      "2026-06-01T12:05:00Z",
    );
    const refreshedKey = buildJobPublicationDraftContextKey(
      "job-1",
      "creator-1",
      "2026-06-01T12:06:00Z",
    );
    const switchedProfileKey = buildJobPublicationDraftContextKey(
      "job-1",
      "creator-2",
      "2026-06-01T12:06:00Z",
    );

    expect(refreshedKey).not.toEqual(firstKey);
    expect(switchedProfileKey).not.toEqual(refreshedKey);
  });

  it("renders the unique receipt binding id for existing publication attempts", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "passed",
            publish_ready: true,
            blocked_reasons: [],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            targets: [],
            existing_attempts: [
              {
                id: "attempt-1",
                job_id: "job-1",
                creator_profile_id: "creator-1",
                creator_profile_name: "FAS",
                platform: "douyin",
                platform_label: "抖音",
                account_label: "FAS",
                credential_id: "cred-1",
                adapter: "browser_agent",
                status: "published",
                external_receipt_id: "receipt-binding:abc123",
                created_at: "2026-06-01T12:00:00Z",
                updated_at: "2026-06-01T12:05:00Z",
                runs: [],
              },
            ],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob());

    expect(await screen.findByText("回执：receipt-binding:abc123")).toBeInTheDocument();
  });

  it("routes manual handoff plans to the manual publication entry instead of auto submit", async () => {
    const windowOpen = vi.spyOn(window, "open").mockImplementation(() => null);
    const mutate = vi.fn();

    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "manual_handoff",
            publish_ready: true,
            manual_handoff_ready: false,
            manual_handoff_targets: [
              {
                platform: "wechat-channels",
                label: "视频号",
                status: "manual_handoff",
                login_url: "https://channels.weixin.qq.com/login.html",
              },
            ],
            blocked_reasons: [],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate,
    });

    renderPanel(buildJob());

    expect(await screen.findByText("人工接管")).toBeInTheDocument();
    const publishButton = await screen.findByRole("button", { name: "一键发布" });
    fireEvent.click(publishButton);

    await waitFor(() => {
      expect(windowOpen).toHaveBeenCalledWith(
        "https://channels.weixin.qq.com/login.html",
        "_blank",
        "noopener,noreferrer",
      );
    });
    expect(mutate).not.toHaveBeenCalled();
  });

  it("shows publication executor preflight messages from the plan contract", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "blocked",
            publish_ready: false,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: ["browser-agent 不支持正式发布。"],
            publication_executor_preflight: {
              ready: false,
              message: "browser-agent 不支持正式发布。",
              failures: ["缺少平台发布页标签"],
            },
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            targets: [],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob());

    const preflightMessages = await screen.findAllByText("browser-agent 不支持正式发布。");
    expect(preflightMessages.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("缺少平台发布页标签")).toBeInTheDocument();
  });

  it("uses generated material targets as the publication material checklist", async () => {
    reactQueryMocks.useQuery.mockImplementation((options: { queryKey?: unknown[] }) => {
      const queryKey = Array.isArray(options?.queryKey) ? options.queryKey : [];
      if (queryKey[0] === "avatar-materials") {
        return {
          data: {
            profiles: [
              {
                id: "creator-1",
                display_name: "FAS",
              },
            ],
          },
          isLoading: false,
        };
      }
      if (queryKey[0] === "job-publication-plan") {
        return {
          data: {
            job_id: "job-1",
            status: "ready",
            publish_ready: true,
            manual_handoff_ready: false,
            manual_handoff_targets: [],
            blocked_reasons: [],
            warnings: [],
            adapter: "browser-agent",
            creator_profile_id: "creator-1",
            creator_profile_name: "FAS",
            media_path: "E:/materials/maxace/output.mp4",
            material_targets: [
              {
                platform: "xiaohongshu",
                platform_label: "小红书",
                credential_id: "cred-xhs",
                account_label: "FAS",
                adapter: "browser_agent",
                title: "小红书标题",
                body: "小红书正文",
                tags: ["EDC"],
                cover_path: "E:/materials/smart-copy/02-xiaohongshu-cover.jpg",
                cover_slots: [
                  { slot: "portrait_3_4", label: "3:4 竖版", cover_path: "E:/materials/smart-copy/02-xiaohongshu-cover.jpg" },
                ],
                status: "material_ready",
              },
              {
                platform: "kuaishou",
                platform_label: "快手",
                credential_id: "cred-ks",
                account_label: "FAS",
                adapter: "browser_agent",
                title: "",
                body: "快手正文",
                tags: ["EDC"],
                cover_path: "E:/materials/smart-copy/04-kuaishou-cover.jpg",
                cover_slots: [
                  { slot: "portrait_3_4", label: "3:4 竖版", cover_path: "E:/materials/smart-copy/04-kuaishou-cover.jpg" },
                ],
                status: "material_ready",
              },
              {
                platform: "toutiao",
                platform_label: "头条",
                credential_id: "cred-tt",
                account_label: "FAS",
                adapter: "browser_agent",
                title: "头条标题",
                body: "头条正文",
                tags: ["EDC"],
                cover_path: "E:/materials/smart-copy/06-toutiao-cover.jpg",
                cover_slots: [
                  { slot: "landscape_16_9", label: "16:9 横版", cover_path: "E:/materials/smart-copy/06-toutiao-cover.jpg" },
                ],
                status: "material_ready",
              },
            ],
            targets: [
              {
                platform: "douyin",
                platform_label: "抖音",
                credential_id: "cred-dy",
                account_label: "FAS",
                adapter: "browser_agent",
                title: "抖音标题",
                body: "抖音正文",
                tags: ["EDC"],
                cover_path: "E:/materials/smart-copy/03-douyin-cover.jpg",
                status: "ready",
              },
            ],
            existing_attempts: [],
          },
          isLoading: false,
        };
      }
      return {
        data: undefined,
        isLoading: false,
      };
    });
    reactQueryMocks.useMutation.mockReturnValue({
      isPending: false,
      error: null,
      mutate: vi.fn(),
    });

    renderPanel(buildJob());

    expect(await screen.findByRole("button", { name: /小红书/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /快手/ })).toBeInTheDocument();
    const toutiaoCard = screen.getByRole("button", { name: /头条/ });
    expect(toutiaoCard).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /抖音/ })).toBeInTheDocument();

    fireEvent.click(toutiaoCard);

    const cover = await screen.findByRole("img", { name: "头条 主封面" });
    expect(cover).toHaveAttribute("src", expect.stringContaining("/intelligent-copy/local-image?path="));
    expect(screen.getByText("头条标题")).toBeInTheDocument();
  });
});
