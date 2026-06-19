// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

function buildJob(): Job {
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
  };
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

    render(<JobPublicationPanel job={buildJob()} />);

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

    render(<JobPublicationPanel job={buildJob()} />);

    expect(await screen.findByText("回执：receipt-binding:abc123")).toBeInTheDocument();
  });

  it("keeps manual handoff plans non-publishable even if root publish_ready is stale true", async () => {
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
      mutate: vi.fn(),
    });

    render(<JobPublicationPanel job={buildJob()} />);

    expect(await screen.findByText("人工接管")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成物料并发布" })).toBeDisabled();
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

    render(<JobPublicationPanel job={buildJob()} />);

    const preflightMessages = await screen.findAllByText("browser-agent 不支持正式发布。");
    expect(preflightMessages.length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("缺少平台发布页标签")).toBeInTheDocument();
  });
});
