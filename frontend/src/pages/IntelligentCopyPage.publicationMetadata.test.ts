import { describe, expect, it } from "vitest";

import {
  buildPlatformPreviewMetadataRows,
  platformMaterialStatusKind,
  platformMaterialStatusTone,
} from "./IntelligentCopyPage";
import type { IntelligentCopyPlatformMaterial } from "../types";

function buildPlatformMaterial(overrides: Partial<IntelligentCopyPlatformMaterial> = {}): IntelligentCopyPlatformMaterial {
  return {
    key: "youtube",
    label: "YouTube",
    has_title: true,
    title_label: "标题",
    body_label: "简介",
    tag_label: "标签",
    constraints: {
      title_limit: 100,
      body_limit: 5000,
      tag_limit: 15,
      tag_style: "hashtags",
      cover_size: {
        width: 1280,
        height: 720,
      },
      rule_note: "测试规则",
    },
    titles: ["MAXACE 美杜莎4 顶配次顶配开箱"],
    primary_title: "MAXACE 美杜莎4 顶配次顶配开箱",
    title_copy_all: "MAXACE 美杜莎4 顶配次顶配开箱",
    body: "正文",
    tags: ["EDC折刀", "MAXACE美杜莎4"],
    tags_copy: "#EDC折刀 #MAXACE美杜莎4",
    full_copy: "完整文案",
    ...overrides,
  };
}

describe("buildPlatformPreviewMetadataRows", () => {
  it("surfaces critical publication metadata for preview auditing", () => {
    const rows = buildPlatformPreviewMetadataRows(
      buildPlatformMaterial({
        declaration: "原创声明",
        collection_name: "EDC潮玩桌搭",
        visibility_or_publish_mode: "scheduled",
        scheduled_publish_at: "2026-06-01 21:00",
        live_publish_preflight: {
          status: "ready",
          summary: "已满足发布前门禁",
        },
      }),
    );

    expect(rows).toEqual([
      { label: "声明", value: "原创声明" },
      { label: "合集", value: "EDC潮玩桌搭" },
      { label: "发布模式", value: "scheduled" },
      { label: "定时", value: "2026-06-01 21:00" },
      { label: "预发布门禁", value: "ready · 已满足发布前门禁" },
    ]);
  });

  it("falls back to collection object and missing required surfaces when preflight summary is absent", () => {
    const rows = buildPlatformPreviewMetadataRows(
      buildPlatformMaterial({
        collection: {
          name: "MAXACE 合集",
        },
        live_publish_preflight: {
          status: "blocked",
          missing_required_surfaces: ["cover", "schedule"],
        },
      }),
    );

    expect(rows).toEqual([
      { label: "合集", value: "MAXACE 合集" },
      { label: "预发布门禁", value: "blocked · 缺少：cover、schedule" },
    ]);
  });

  it("surfaces manual handoff metadata and marks the platform as pending instead of blocked", () => {
    const material = buildPlatformMaterial({
      key: "wechat-channels",
      label: "视频号",
      has_title: false,
      manual_handoff_only: true,
      manual_publish_entry_url: "https://channels.weixin.qq.com/login.html",
      publish_ready: false,
      blocking_reasons: ["当前平台仅支持人工登录后继续发布。"],
    });

    const rows = buildPlatformPreviewMetadataRows(material);

    expect(platformMaterialStatusKind(material)).toBe("manual_handoff");
    expect(platformMaterialStatusTone(material)).toBe("pending");
    expect(rows).toEqual([
      { label: "发布方式", value: "人工接管" },
      { label: "登录入口", value: "https://channels.weixin.qq.com/login.html" },
    ]);
  });

  it("treats stale publish_ready true as blocked when preflight is already blocked", () => {
    const material = buildPlatformMaterial({
      publish_ready: true,
      live_publish_preflight: {
        status: "blocked",
        missing_required_surfaces: ["cover"],
      },
      blocking_reasons: [],
    });

    expect(platformMaterialStatusKind(material)).toBe("blocked");
    expect(platformMaterialStatusTone(material)).toBe("failed");
  });

  it("treats platform materials without explicit ready evidence as blocked by default", () => {
    const material = buildPlatformMaterial({
      publish_ready: undefined,
      live_publish_preflight: undefined,
      blocking_reasons: [],
    });

    expect(platformMaterialStatusKind(material)).toBe("blocked");
    expect(platformMaterialStatusTone(material)).toBe("failed");
  });
});
