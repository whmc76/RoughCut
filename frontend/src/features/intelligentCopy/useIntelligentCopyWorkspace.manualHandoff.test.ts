import { describe, expect, it } from "vitest";

import type { IntelligentCopyGenerateTask, PublicationPlan } from "../../types";
import {
  buildPublicationSchemeContextKey,
  buildIntelligentPublicationPlanQueryKey,
  intelligentCopyPlatformOptions,
  normalizeIntelligentCopyPlatformId,
  publicationPlanIsReady,
  publicationPlanHasManualHandoffReady,
  publicationPlanManualHandoffTargets,
  publicationPlanStatusKind,
  resultBlockingReasons,
  resultStatusKind,
  taskHasContinueReadyMaterial,
} from "./useIntelligentCopyWorkspace";

describe("manual handoff publication state helpers", () => {
  it("treats a manual_handoff generate task as a continue-ready material task", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-1",
      folder_path: "E:/materials/maxace",
      status: "manual_handoff",
      progress: 100,
      stage: "manual_handoff",
      message: "物料生成完成，部分平台需人工登录后继续发布。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        status: "manual_handoff",
        publish_ready: false,
        manual_handoff_ready: true,
        manual_handoff_targets: [
          {
            platform: "wechat-channels",
            label: "视频号",
            login_url: "https://channels.weixin.qq.com/login.html",
          },
        ],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(true);
  });

  it("treats material_contract manual_handoff as continue-ready even if root publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-stale-manual-handoff",
      folder_path: "E:/materials/maxace",
      status: "manual_handoff",
      progress: 100,
      stage: "manual_handoff",
      message: "视频号改为人工接管。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          status: "manual_handoff",
          one_click_publish_ready: false,
          manual_handoff_platforms: [
            {
              platform: "wechat-channels",
              label: "视频号",
              login_url: "https://channels.weixin.qq.com/login.html",
            },
          ],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(true);
  });

  it("blocks continue-ready when material_contract says failed even if root publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-stale-publish-ready",
      folder_path: "E:/materials/maxace",
      status: "blocked",
      progress: 100,
      stage: "manual_review",
      message: "物料仍未就绪。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          status: "failed",
          one_click_publish_ready: false,
          blocking_reasons: ["缺少 live_publish_preflight"],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少 live_publish_preflight"]);
  });

  it("treats failed material_contract as blocked even without explicit one_click_publish_ready", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-failed-no-flag",
      folder_path: "E:/materials/maxace",
      status: "blocked",
      progress: 100,
      stage: "manual_review",
      message: "物料仍未就绪。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          status: "failed",
          blocking_reasons: ["缺少封面"],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少封面"]);
  });

  it("treats failed material_contract as blocked even when one_click_publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-failed-stale-true",
      folder_path: "E:/materials/maxace",
      status: "blocked",
      progress: 100,
      stage: "manual_review",
      message: "物料仍未就绪。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          status: "failed",
          one_click_publish_ready: true,
          blocking_reasons: ["缺少 live_publish_preflight"],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少 live_publish_preflight"]);
  });

  it("treats blocking_reasons on material_contract as blocked even when status is missing and one_click_publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-blocking-reasons-only",
      folder_path: "E:/materials/maxace",
      status: "blocked",
      progress: 100,
      stage: "manual_review",
      message: "物料仍未就绪。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          one_click_publish_ready: true,
          blocking_reasons: ["缺少 live_publish_preflight"],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少 live_publish_preflight"]);
  });

  it("derives blocked state from platform statuses when root contract status is missing", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-platform-status-failed",
      folder_path: "E:/materials/maxace",
      status: "blocked",
      progress: 100,
      stage: "manual_review",
      message: "物料仍未就绪。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          one_click_publish_ready: true,
          blocking_reasons: ["缺少封面"],
          platforms: {
            douyin: {
              status: "failed",
              one_click_publish_ready: true,
            },
          },
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少封面"]);
  });

  it("derives manual_handoff from manual_handoff_platforms when root contract status is missing", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-platform-manual-handoff",
      folder_path: "E:/materials/maxace",
      status: "completed",
      progress: 100,
      stage: "completed",
      message: "物料已生成。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          one_click_publish_ready: true,
          manual_handoff_platforms: [
            {
              platform: "wechat-channels",
              label: "视频号",
              login_url: "https://channels.weixin.qq.com/login.html",
            },
          ],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(true);
    expect(resultStatusKind(task.result)).toBe("manual_handoff");
  });

  it("prefers manual_handoff contract over stale root blocking reasons when one_click_publish_ready remains true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-contract-manual-handoff-stale-root-blocker",
      folder_path: "E:/materials/maxace",
      status: "completed",
      progress: 100,
      stage: "completed",
      message: "物料已生成。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        material_contract: {
          one_click_publish_ready: true,
          blocking_reasons: ["视频号：当前平台仅支持人工登录后继续发布。"],
          manual_handoff_platforms: [
            {
              platform: "wechat-channels",
              label: "视频号",
              login_url: "https://channels.weixin.qq.com/login.html",
            },
          ],
        },
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: ["视频号：当前平台仅支持人工登录后继续发布。"],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(true);
    expect(resultStatusKind(task.result)).toBe("manual_handoff");
  });

  it("treats legacy root blocking_reasons as blocked even when root publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-legacy-root-blocked",
      folder_path: "E:/materials/maxace",
      status: "completed",
      progress: 100,
      stage: "completed",
      message: "物料已生成。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [],
        blocking_reasons: ["缺少 live_publish_preflight"],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
    expect(resultBlockingReasons(task.result)).toEqual(["缺少 live_publish_preflight"]);
  });

  it("treats legacy manual_handoff_targets as manual_handoff even when root publish_ready is stale true", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-legacy-root-manual-handoff",
      folder_path: "E:/materials/maxace",
      status: "completed",
      progress: 100,
      stage: "completed",
      message: "物料已生成。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        status: "completed",
        publish_ready: true,
        manual_handoff_ready: false,
        manual_handoff_targets: [
          {
            platform: "wechat-channels",
            label: "视频号",
            login_url: "https://channels.weixin.qq.com/login.html",
          },
        ],
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(true);
    expect(resultStatusKind(task.result)).toBe("manual_handoff");
  });

  it("treats results without explicit ready evidence as blocked by default", () => {
    const task: IntelligentCopyGenerateTask = {
      id: "task-missing-ready-evidence",
      folder_path: "E:/materials/maxace",
      status: "completed",
      progress: 100,
      stage: "completed",
      message: "物料已生成。",
      created_at: "2026-06-01T12:00:00Z",
      updated_at: "2026-06-01T12:05:00Z",
      result: {
        folder_path: "E:/materials/maxace",
        material_dir: "E:/materials/maxace/smart-copy",
        markdown_path: "E:/materials/maxace/smart-copy/smart-copy.md",
        json_path: "E:/materials/maxace/smart-copy/smart-copy.json",
        copy_style: "attention_grabbing",
        inspection: {
          folder_path: "E:/materials/maxace",
          material_dir: "E:/materials/maxace/smart-copy",
          extra_video_files: [],
          extra_subtitle_files: [],
          extra_cover_files: [],
          warnings: [],
        },
        highlights: {},
        content_profile_summary: {},
        platforms: [],
        status: "completed",
        blocking_reasons: [],
        warnings: [],
      },
    };

    expect(taskHasContinueReadyMaterial(task)).toBe(false);
    expect(resultStatusKind(task.result)).toBe("blocked");
  });

  it("recognizes manual_handoff publication plans and exposes login targets", () => {
    const plan: PublicationPlan = {
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
    };

    expect(publicationPlanHasManualHandoffReady(plan)).toBe(true);
    expect(publicationPlanManualHandoffTargets(plan)).toEqual([
      {
        platform: "wechat-channels",
        label: "视频号",
        status: "manual_handoff",
        login_url: "https://channels.weixin.qq.com/login.html",
      },
    ]);
  });

  it("recognizes manual_handoff publication plans even if root publish_ready is stale true", () => {
    const plan: PublicationPlan = {
      job_id: "job-stale-manual-handoff",
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
    };

    expect(publicationPlanHasManualHandoffReady(plan)).toBe(true);
    expect(publicationPlanStatusKind(plan)).toBe("manual_handoff");
    expect(publicationPlanIsReady(plan)).toBe(false);
  });

  it("treats blocked publication plans as blocked even if root publish_ready is stale true", () => {
    const plan: PublicationPlan = {
      job_id: "job-stale-blocked-plan",
      status: "blocked",
      publish_ready: true,
      manual_handoff_ready: false,
      manual_handoff_targets: [],
      blocked_reasons: ["缺少 live_publish_preflight"],
      warnings: [],
      adapter: "browser-agent",
      creator_profile_id: "creator-1",
      creator_profile_name: "FAS",
      media_path: "E:/materials/maxace/output.mp4",
      targets: [],
      existing_attempts: [],
    };

    expect(publicationPlanStatusKind(plan)).toBe("blocked");
    expect(publicationPlanIsReady(plan)).toBe(false);
  });

  it("derives manual_handoff from manual_handoff_targets even when status is missing and publish_ready is stale true", () => {
    const plan: PublicationPlan = {
      job_id: "job-manual-handoff-target-fallback",
      status: "",
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
    };

    expect(publicationPlanHasManualHandoffReady(plan)).toBe(true);
    expect(publicationPlanStatusKind(plan)).toBe("manual_handoff");
    expect(publicationPlanIsReady(plan)).toBe(false);
  });

  it("treats blocked reasons as blocked even when plan status is missing and publish_ready is stale true", () => {
    const plan: PublicationPlan = {
      job_id: "job-blocked-reasons-fallback",
      status: "",
      publish_ready: true,
      manual_handoff_ready: false,
      manual_handoff_targets: [],
      blocked_reasons: ["缺少 live_publish_preflight"],
      warnings: [],
      adapter: "browser-agent",
      creator_profile_id: "creator-1",
      creator_profile_name: "FAS",
      media_path: "E:/materials/maxace/output.mp4",
      targets: [],
      existing_attempts: [],
    };

    expect(publicationPlanStatusKind(plan)).toBe("blocked");
    expect(publicationPlanIsReady(plan)).toBe(false);
  });

  it("treats publish_ready true plans without executable targets as blocked", () => {
    const plan: PublicationPlan = {
      job_id: "job-ready-without-targets",
      status: "",
      publish_ready: true,
      manual_handoff_ready: false,
      manual_handoff_targets: [],
      blocked_reasons: [],
      warnings: [],
      adapter: "browser-agent",
      creator_profile_id: "creator-1",
      creator_profile_name: "FAS",
      media_path: "E:/materials/maxace/output.mp4",
      targets: [],
      existing_attempts: [],
    };

    expect(publicationPlanStatusKind(plan)).toBe("blocked");
    expect(publicationPlanIsReady(plan)).toBe(false);
  });

  it("normalizes legacy wechat platform ids to the canonical hyphenated key", () => {
    const optionIds = intelligentCopyPlatformOptions.map((option) => String(option.id));
    expect(normalizeIntelligentCopyPlatformId("wechat_channels")).toBe("wechat-channels");
    expect(optionIds.includes("wechat-channels")).toBe(true);
    expect(optionIds.includes("wechat_channels")).toBe(false);
    expect(publicationPlanManualHandoffTargets({
      job_id: "job-legacy",
      status: "manual_handoff",
      publish_ready: false,
      manual_handoff_ready: true,
      manual_handoff_targets: [
        {
          platform: "wechat_channels",
          label: "视频号",
          status: "manual_handoff",
          login_url: "https://channels.weixin.qq.com/login.html",
        },
      ],
      blocked_reasons: [],
      warnings: [],
      adapter: "browser-agent",
      creator_profile_id: "creator-legacy",
      creator_profile_name: "FAS",
      media_path: "E:/materials/maxace/output.mp4",
      targets: [],
      existing_attempts: [],
    })).toEqual([
      {
        platform: "wechat-channels",
        label: "视频号",
        status: "manual_handoff",
        login_url: "https://channels.weixin.qq.com/login.html",
      },
    ]);
  });

  it("refreshes publication plan query identity when the selected generate task snapshot changes", () => {
    const firstKey = buildIntelligentPublicationPlanQueryKey({
      resultJsonPath: "E:/materials/maxace/smart-copy/smart-copy.json",
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedGenerateTaskId: "task-1",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:05:00Z",
    });
    const refreshedKey = buildIntelligentPublicationPlanQueryKey({
      resultJsonPath: "E:/materials/maxace/smart-copy/smart-copy.json",
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedGenerateTaskId: "task-1",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:06:00Z",
    });
    const switchedTaskKey = buildIntelligentPublicationPlanQueryKey({
      resultJsonPath: "E:/materials/maxace/smart-copy/smart-copy.json",
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedGenerateTaskId: "task-2",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:06:00Z",
    });

    expect(refreshedKey).not.toEqual(firstKey);
    expect(switchedTaskKey).not.toEqual(refreshedKey);
  });

  it("invalidates publication scheme context when task snapshot or target platforms change", () => {
    const firstKey = buildPublicationSchemeContextKey({
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedPublicationBrowser: "edge",
      selectedGenerateTaskId: "task-1",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:05:00Z",
      targetPlatforms: ["douyin", "xiaohongshu"],
    });
    const refreshedTaskKey = buildPublicationSchemeContextKey({
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedPublicationBrowser: "edge",
      selectedGenerateTaskId: "task-1",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:06:00Z",
      targetPlatforms: ["douyin", "xiaohongshu"],
    });
    const changedTargetsKey = buildPublicationSchemeContextKey({
      folderPath: "E:/materials/maxace",
      selectedPublicationProfileId: "creator-1",
      selectedPublicationBrowser: "edge",
      selectedGenerateTaskId: "task-1",
      selectedGenerateTaskUpdatedAt: "2026-06-01T12:06:00Z",
      targetPlatforms: ["douyin", "youtube"],
    });

    expect(refreshedTaskKey).not.toEqual(firstKey);
    expect(changedTargetsKey).not.toEqual(refreshedTaskKey);
  });
});
