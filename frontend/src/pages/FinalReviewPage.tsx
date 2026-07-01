import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Filter, Search, X } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { getTextValue, normalizeVideoTypeValue } from "../features/jobs/contentProfile";
import type {
  ContentProfileReview,
  Job,
  JobActivity,
  JobActivityDecision,
  JobActivityEvent,
  JobDownloadFile,
  Report,
  TokenUsageReport,
} from "../types";
import { classNames, formatBytes, formatDate, formatDuration, statusLabel } from "../utils";

type AudienceReviewItem = {
  id: string;
  label: string;
  detail: string;
};

type ReviewCheckDecision = "pass" | "fail";

type FinalReviewEvidenceCard = {
  key: string;
  label: string;
  value: string;
  detail: string;
};

type FinalReviewLogIssue = {
  id: string;
  title: string;
  detail: string;
  status: string;
  source: string;
};

const DEFAULT_AUDIENCE_REVIEW_ITEMS: AudienceReviewItem[] = [
  { id: "edit_opening", label: "开头裁切保留必要上下文", detail: "没有把主题、人物、场景或第一句关键信息剪掉。" },
  { id: "edit_continuity", label: "剪切点没有误删关键信息", detail: "因果、动作、回答和画面承接没有被切断。" },
  { id: "edit_pace", label: "节奏压缩有效且不突兀", detail: "空拍、重复和等待被压缩，但没有硬跳或喘不过气。" },
  { id: "edit_overlay", label: "字幕和包装不遮挡主体", detail: "字幕、进度条、片头片尾和封面导向不挡关键画面。" },
  { id: "edit_audio_close", label: "音频衔接和结尾完整", detail: "音量、转场、尾音和最后一句没有突变或被截断。" },
];

const VIDEO_TYPE_REVIEW_ITEMS: Record<string, AudienceReviewItem[]> = {
  tutorial: [
    { id: "tutorial_edit_context", label: "开头没有剪掉目标和前置条件", detail: "已拍到的目标、材料、环境或结果预览没有被误删。" },
    { id: "tutorial_edit_steps", label: "步骤剪辑没有跳断必要过程", detail: "删减和加速后仍能看出从上一步到下一步怎么发生。" },
    { id: "tutorial_edit_hold", label: "关键操作停留时间足够", detail: "复杂点击、参数、结果画面没有被切得过短。" },
    { id: "tutorial_edit_overlay", label: "字幕和包装不挡操作区域", detail: "字幕、进度条和贴片不遮挡按钮、参数、鼠标或结果。" },
    { id: "tutorial_edit_close", label: "结果段和尾句没有被截断", detail: "成片结尾保留最终效果、复盘或自然停顿。" },
  ],
  unboxing: [
    { id: "product_edit_context", label: "主体和看点镜头未被误删", detail: "已拍到的产品名、外观、配件或开箱关键帧被保留下来。" },
    { id: "product_edit_detail", label: "细节展示有足够停留", detail: "结构、接口、开合、质感等近景没有被切太短。" },
    { id: "product_edit_sequence", label: "展示顺序和口播对得上", detail: "画面切换没有跑在解说前后，结论对应的镜头还在。" },
    { id: "product_edit_overlay", label: "字幕包装不遮挡物件细节", detail: "字幕、贴片和平台导向避开产品主体、参数和手部动作。" },
    { id: "product_edit_close", label: "取舍结论和尾句完整", detail: "最后的判断、建议或自然收口没有被截断。" },
  ],
  commentary: [
    { id: "commentary_edit_claim", label: "观点句没有被剪断", detail: "句首、转折、否定词和结论词没有被误切。" },
    { id: "commentary_edit_evidence", label: "论据片段保留必要前后文", detail: "删减后仍能听懂例子、引用或画面为什么支撑观点。" },
    { id: "commentary_edit_pace", label: "口播节奏去冗余但不断气", detail: "长停顿和重复被压掉，句子之间没有机械硬接。" },
    { id: "commentary_edit_subtitle", label: "字幕断句跟口播逻辑一致", detail: "字幕换行和切点不拆散专名、否定、转折或结论。" },
    { id: "commentary_edit_close", label: "结尾收束没有被截断", detail: "最后一句、CTA 或自然尾音保留完整。" },
  ],
  vlog: [
    { id: "vlog_edit_context", label: "场景切换保留必要交代", detail: "换地点、换人物、换时间时没有让观众失去上下文。" },
    { id: "vlog_edit_flow", label: "跳切和转场不破坏连续感", detail: "动作、表情和环境声承接自然，没有明显硬断。" },
    { id: "vlog_edit_moment", label: "关键反应没有被剪短", detail: "已拍到的笑点、情绪、结果或转折保留足够前后文。" },
    { id: "vlog_edit_audio", label: "环境声和人声衔接平顺", detail: "降噪、音乐、环境声和对白没有突然跳变。" },
    { id: "vlog_edit_close", label: "尾段保留自然收口", detail: "最后的动作、对白或情绪落点没有被截断。" },
  ],
  gameplay: [
    { id: "gameplay_edit_setup", label: "高光前置条件没有被剪掉", detail: "战局、任务、位置或资源状态保留到足够理解后续操作。" },
    { id: "gameplay_edit_highlight", label: "关键操作前后文完整", detail: "击杀、解谜、翻盘、失败原因没有只剩结果帧。" },
    { id: "gameplay_edit_ui", label: "字幕包装不遮挡游戏 UI", detail: "血量、地图、技能、比分、提示和菜单仍然可读。" },
    { id: "gameplay_edit_audio", label: "游戏声、语音和音乐衔接平衡", detail: "队友语音、解说和关键音效没有被盖住或突变。" },
    { id: "gameplay_edit_close", label: "结算或复盘段没有截断", detail: "胜负、奖励、失败原因或下一局过渡保留完整。" },
  ],
  food: [
    { id: "food_edit_context", label: "地点和菜品交代未被误删", detail: "已拍到的店名、菜名、价格或点单上下文保留可理解。" },
    { id: "food_edit_visual", label: "食物近景停留足够", detail: "出品、切面、热气、夹取或试吃镜头没有被切太短。" },
    { id: "food_edit_sync", label: "评价口播和画面对得上", detail: "口感、价格、份量评价对应的画面没有错位。" },
    { id: "food_edit_audio", label: "环境噪声和讲解衔接可听", detail: "店内噪声、音乐、降噪和人声没有突然跳变。" },
    { id: "food_edit_close", label: "推荐结论和尾句完整", detail: "是否推荐、避坑或复购判断没有被截断。" },
  ],
};

const TOPIC_REVIEW_ITEMS: Record<string, AudienceReviewItem[]> = {
  nature: [
    { id: "nature_edit_setup", label: "动作发生前后文未被剪断", detail: "已拍到的观察、接近、反应和结果保留足够连续性。" },
    { id: "nature_edit_subject", label: "主体镜头没有被裁切或遮挡", detail: "字幕、包装和裁切没有挡住关键动作、表情或环境关系。" },
    { id: "nature_edit_pace", label: "观察节奏没有被压得过快", detail: "悬念、停顿和动作变化有足够时间被看见。" },
    { id: "nature_edit_redundancy", label: "重复空镜和等待已适度压缩", detail: "无信息的长等待被删减，但不破坏动作因果。" },
    { id: "nature_edit_close", label: "结果镜头和尾音完整", detail: "反转、结果、旁白尾句或自然收口没有被截断。" },
  ],
  software: [
    { id: "software_edit_steps", label: "操作路径剪辑没有跳断", detail: "已拍到的入口、节点、参数和结果之间保留必要承接。" },
    { id: "software_edit_hold", label: "关键界面停留时间足够", detail: "菜单、节点、输入框、参数值和结果区域没有被切太短。" },
    { id: "software_edit_overlay", label: "字幕包装不挡界面关键信息", detail: "字幕、贴片和进度条避开菜单、参数、提示词和结果。" },
    { id: "software_edit_compare", label: "前后效果对比剪辑清楚", detail: "对比镜头、结果预览或失败修正没有被错位或删掉。" },
    { id: "software_edit_close", label: "结果段和尾句没有被截断", detail: "最终效果、保存动作、限制说明或自然停顿保留完整。" },
  ],
  edc: [
    { id: "edc_edit_subject", label: "主体展示镜头未被误删", detail: "已拍到的装备主体、开合、握持或装载镜头保留完整。" },
    { id: "edc_edit_detail", label: "细节近景停留足够", detail: "结构、尺寸、接口、收纳和手部动作没有被切太短。" },
    { id: "edc_edit_sequence", label: "展示顺序和评价口播对齐", detail: "优缺点、对比和实操动作对应的镜头没有错位。" },
    { id: "edc_edit_overlay", label: "字幕包装不遮挡装备细节", detail: "字幕、片头、进度条和贴片避开主体、接口和手部动作。" },
    { id: "edc_edit_close", label: "取舍建议和尾句完整", detail: "最后的适用人群、风险或购买建议没有被截断。" },
  ],
};

const TASK_REVIEW_ITEMS: Record<string, AudienceReviewItem[]> = {
  smart_director: [
    { id: "director_plan_alignment", label: "导演计划落地到成片节奏", detail: "镜头顺序、段落重点和包装节奏符合智能导演方案，没有只剩素材拼接。" },
    { id: "director_story_continuity", label: "叙事段落衔接清楚", detail: "开场、铺垫、主体、转折和收束之间没有跳断或重复绕回。" },
    { id: "director_asset_sync", label: "B-roll、字幕和音频同步", detail: "补充画面、字幕、旁白、音乐和转场没有错位。" },
    { id: "director_effects_pacing", label: "特效和包装服务表达", detail: "智能特效、贴片、章节和片头片尾不抢主体，也不空转堆效果。" },
    { id: "director_delivery_complete", label: "多版本输出和结尾完整", detail: "标准版、包装版或平台版的结尾、导向和输出规格完整。" },
  ],
  remix: [
    { id: "remix_source_context", label: "原片剧情和人物关系未剪断", detail: "二创删减后仍能理解事件、人物动机和前后因果。" },
    { id: "remix_commentary_sync", label: "解说与画面证据同步", detail: "旁白说到的角色、动作、反转和细节有对应画面支撑。" },
    { id: "remix_redundancy_cleanup", label: "冗余片段压缩但不损伤情绪", detail: "重复、长空镜和低信息段被压缩，关键情绪和反转保留。" },
    { id: "remix_transition_audio", label: "转场和音频桥接自然", detail: "跨场景混剪、BGM、原声和解说之间没有明显断裂。" },
    { id: "remix_platform_package", label: "平台包装不破坏叙事", detail: "字幕、进度条、贴片、标题钩子和结尾导向不遮挡关键剧情。" },
  ],
};

type ReviewTimeFilter = "all" | "today" | "three_days" | "seven_days";

type ReviewFilterOption = {
  key: string;
  label: string;
  count: number;
};

const REVIEW_TIME_FILTERS: Array<{ key: ReviewTimeFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "today", label: "今天" },
  { key: "three_days", label: "最近三天" },
  { key: "seven_days", label: "七天" },
];

function isCompletedClipJob(job: Job) {
  if (job.queue_task_kind === "publication") return false;
  if (job.status === "done" || job.status === "published") return true;
  if (job.status === "needs_review" && job.review_step === "final_review") return true;
  return Boolean(job.publication_status && job.publication_status !== "unpublished");
}

function finalVideoVariant(file: JobDownloadFile | null | undefined): "auto" | "enhanced" | "packaged" {
  if (!file) return "auto";
  if (file.id === "enhanced_mp4") return "enhanced";
  if (file.id === "packaged_mp4") return "packaged";
  return "auto";
}

function videoRoleLabel(file: JobDownloadFile, index: number) {
  if (file.id === "enhanced_mp4") return "最终增强版";
  if (file.id === "packaged_mp4") return "标准剪辑版";
  return file.label?.trim() || (index === 0 ? "候选成片" : "候选版本");
}

function activeContentProfilePayload(contentProfile?: ContentProfileReview | null) {
  return contentProfile?.final ?? contentProfile?.draft ?? null;
}

function contentProfileUnderstanding(contentProfile?: ContentProfileReview | null) {
  const payload = activeContentProfilePayload(contentProfile);
  return payload?.content_understanding && typeof payload.content_understanding === "object"
    ? payload.content_understanding
    : null;
}

function resolveFinalReviewVideoType(job: Job | null | undefined, contentProfile?: ContentProfileReview | null) {
  const payload = activeContentProfilePayload(contentProfile);
  const understanding = contentProfileUnderstanding(contentProfile);
  const explicit = normalizeVideoTypeValue(
    understanding?.video_type
    ?? payload?.video_type
    ?? payload?.content_kind
    ?? job?.workflow_template
    ?? "",
  );
  if (explicit) return explicit;

  const text = [
    job?.workflow_template,
    job?.content_subject,
    job?.content_summary,
    job?.source_name,
    job?.video_description,
  ].map((value) => getTextValue(value)).join(" ").toLowerCase();
  if (/tutorial|教程|教学|screen|操作|工作流|节点|参数/.test(text)) return "tutorial";
  if (/gameplay|游戏|实况|通关|战局|玩法/.test(text)) return "gameplay";
  if (/food|探店|美食|餐厅|菜品|口味/.test(text)) return "food";
  if (/vlog|日常|旅行|生活|探访|逛/.test(text)) return "vlog";
  if (/commentary|观点|评论|解说|分析|吐槽/.test(text)) return "commentary";
  if (/unboxing|开箱|测评|评测|装备|edc|刀|包|手电|工具/.test(text)) return "unboxing";
  return "";
}

function resolveFinalReviewTopicDomain(job: Job | null | undefined, contentProfile?: ContentProfileReview | null) {
  const payload = activeContentProfilePayload(contentProfile);
  const understanding = contentProfileUnderstanding(contentProfile);
  const domain = [
    understanding?.content_domain,
    payload?.content_domain,
    payload?.subject_domain,
    payload?.subject_type,
    payload?.video_theme,
    job?.workflow_template,
    job?.content_subject,
    job?.content_summary,
    job?.source_name,
    job?.video_description,
  ].map((value) => getTextValue(value)).join(" ").toLowerCase();

  if (/comfyui|runninghub|openclaw|软件|界面|节点|参数|提示词|工作流|智能体|agent|api|脚本|教程/.test(domain)) {
    return "software";
  }
  if (/edc|装备|刀|折刀|军刀|手电|背包|机能包|工具|收纳|户外|gear|knife|flashlight|bag/.test(domain)) {
    return "edc";
  }
  if (/动物|自然|野生|纪录|生态|猩猩|猴|鸟|海洋|森林|草原|animal|nature|wildlife/.test(domain)) {
    return "nature";
  }
  return "";
}

function resolveFinalReviewMetricProfile(job: Job | null | undefined, contentProfile?: ContentProfileReview | null) {
  return resolveFinalReviewTaskProfile(job) || resolveFinalReviewTopicDomain(job, contentProfile) || resolveFinalReviewVideoType(job, contentProfile) || "default";
}

function resolveFinalReviewTaskProfile(job: Job | null | undefined) {
  if (!job) return "";
  if (job.queue_task_kind === "smart_director") return "smart_director";
  if (job.queue_task_kind === "remix_production") return "remix";

  const taskText = [
    job.workflow_mode,
    job.workflow_template,
    job.job_flow_mode,
    job.source_name,
    job.content_subject,
    job.content_summary,
    job.task_brief,
  ].map((value) => getTextValue(value)).join(" ").toLowerCase();

  if (/smart_director|智能导演|导演计划|分镜|storyboard|director/.test(taskText)) {
    return "smart_director";
  }
  if (/script_footage_remix|remix|二创|影视|解说二创|混剪|movie|film/.test(taskText)) {
    return "remix";
  }
  return "";
}

export function buildAudienceReviewItems(
  job: Job | null | undefined,
  contentProfile?: ContentProfileReview | null,
): AudienceReviewItem[] {
  const taskProfile = resolveFinalReviewTaskProfile(job);
  if (taskProfile && TASK_REVIEW_ITEMS[taskProfile]) {
    return TASK_REVIEW_ITEMS[taskProfile];
  }
  const topicDomain = resolveFinalReviewTopicDomain(job, contentProfile);
  if (topicDomain && TOPIC_REVIEW_ITEMS[topicDomain]) {
    return TOPIC_REVIEW_ITEMS[topicDomain];
  }
  const videoType = resolveFinalReviewVideoType(job, contentProfile);
  if (videoType && VIDEO_TYPE_REVIEW_ITEMS[videoType]) {
    return VIDEO_TYPE_REVIEW_ITEMS[videoType];
  }
  return DEFAULT_AUDIENCE_REVIEW_ITEMS;
}

function compactText(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function uniqueTexts(values: unknown[]) {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const text = compactText(value);
    const key = text.toLowerCase();
    if (!text || seen.has(key)) continue;
    seen.add(key);
    result.push(text);
  }
  return result;
}

function formatScoreValue(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "未评分";
  }
  return value.toFixed(value % 1 === 0 ? 0 : 1);
}

function formatCompactNumber(value: unknown) {
  const number = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(number)) return "0";
  return Math.round(number).toLocaleString("zh-CN");
}

function sumCompletedStepDurationSeconds(job: Job) {
  return (job.steps ?? []).reduce((total, step) => {
    if (!step.started_at || !step.finished_at) return total;
    const started = new Date(step.started_at).getTime();
    const finished = new Date(step.finished_at).getTime();
    if (!Number.isFinite(started) || !Number.isFinite(finished) || finished <= started) return total;
    return total + ((finished - started) / 1000);
  }, 0);
}

function fallbackElapsedSeconds(job: Job) {
  const created = new Date(job.created_at).getTime();
  const updated = new Date(job.updated_at).getTime();
  if (!Number.isFinite(created) || !Number.isFinite(updated) || updated <= created) return 0;
  return (updated - created) / 1000;
}

function parseCountFromText(text: string, pattern: RegExp) {
  const match = text.match(pattern);
  if (!match?.[1]) return 0;
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseEditDecisionStats(activity: JobActivity | null | undefined) {
  const editDecision = findActivityDecision(activity, (decision) => decision.kind === "edit_plan");
  const text = uniqueTexts([editDecision?.summary, editDecision?.detail]).join("；");
  const removedSegments = parseCountFromText(text, /(?:建议移除|移除)\s*(\d+)\s*段/);
  const removedSeconds = parseCountFromText(text, /共\s*([0-9.]+)\s*秒/);
  const reasonCounts = new Map<string, number>();
  const detail = editDecision?.detail ?? "";
  for (const match of detail.matchAll(/([\w_一-龥+-]+)\s+(\d+)\s*段/g)) {
    const reason = match[1] ?? "";
    const count = Number(match[2] ?? 0);
    if (reason && Number.isFinite(count)) {
      reasonCounts.set(reason, (reasonCounts.get(reason) ?? 0) + count);
    }
  }
  const cleanupReasons = [
    "silence",
    "pause",
    "audio_vad",
    "word_gap",
    "filler",
    "filler_word",
    "catchphrase",
    "repeated",
    "repeated_speech",
    "low_signal_subtitle",
    "micro_keep",
    "gap_fill",
    "timing_trim",
  ];
  const cleanupCount = cleanupReasons.reduce((sum, reason) => sum + (reasonCounts.get(reason) ?? 0), 0);
  return {
    removedSegments,
    removedSeconds,
    cleanupCount,
    reasonCounts,
    summary: editDecision?.summary ?? "",
    detail: editDecision?.detail ?? "",
  };
}

function reportCorrectionDetail(report: Report | null | undefined) {
  if (!report) return "字幕报告未生成";
  const typeEntries = Object.entries(report.corrections_by_type ?? {})
    .filter(([, count]) => Number(count) > 0)
    .sort((left, right) => Number(right[1]) - Number(left[1]))
    .slice(0, 2)
    .map(([type, count]) => `${type} ${count}`);
  return uniqueTexts([
    `接受 ${report.accepted_count} 条`,
    report.pending_count ? `待审 ${report.pending_count} 条` : "",
    typeEntries.join("，"),
  ]).join(" · ") || `${report.total_subtitle_items} 条字幕`;
}

function enhancementCapabilityDetail(job: Job) {
  const modes = job.enhancement_modes ?? [];
  if (!modes.length) return "标准剪辑链路";
  const labels: Record<string, string> = {
    multilingual_translation: "多语言",
    auto_review: "异常门",
    multi_platform_adaptation: "多平台",
    avatar_commentary: "数字人",
    ai_effects: "智能特效",
    dialogue_polish: "台词润色",
  };
  return modes.map((mode) => labels[mode] ?? mode).join("、");
}

function findActivityDecision(activity: JobActivity | null | undefined, predicate: (decision: JobActivityDecision) => boolean) {
  return (activity?.decisions ?? []).find(predicate) ?? null;
}

function latestActivityEvent(activity: JobActivity | null | undefined, predicate?: (event: JobActivityEvent) => boolean) {
  const events = activity?.events ?? [];
  return (predicate ? events.filter(predicate) : events)[0] ?? null;
}

function buildFinalReviewEvidenceCards(
  job: Job,
  activity: JobActivity | null | undefined,
  report: Report | null | undefined,
  tokenUsage: TokenUsageReport | null | undefined,
  contentProfile: ContentProfileReview | null | undefined,
  videoFileCount: number,
): FinalReviewEvidenceCard[] {
  const metricProfile = resolveFinalReviewMetricProfile(job, contentProfile);
  const editStats = parseEditDecisionStats(activity);
  const diagnostics = job.timeline_diagnostics ?? null;
  const elapsedSeconds = sumCompletedStepDurationSeconds(job) || fallbackElapsedSeconds(job);
  const tokenTopStep = [...(tokenUsage?.steps ?? [])].sort((left, right) => right.total_tokens - left.total_tokens)[0];
  const directorDecisionKinds = new Set(["content_profile", "dialogue_polish", "avatar_commentary", "platform_package", "edit_plan"]);
  const directorDecisions = (activity?.decisions ?? []).filter((decision) => directorDecisionKinds.has(decision.kind));
  const directorPrimaryDecision = findActivityDecision(activity, (decision) => decision.kind === "edit_plan")
    ?? findActivityDecision(activity, (decision) => decision.kind === "dialogue_polish")
    ?? findActivityDecision(activity, (decision) => decision.kind === "content_profile");
  const dialogueDecision = findActivityDecision(activity, (decision) => decision.kind === "dialogue_polish")
    ?? findActivityDecision(activity, (decision) => decision.kind === "avatar_commentary");
  const dialogueText = uniqueTexts([dialogueDecision?.summary, dialogueDecision?.detail]).join("；");
  const voiceoverSegments = parseCountFromText(dialogueText, /(?:生成|重组|润色|改写)\s*([0-9]+)\s*段/);
  const cards: Record<string, FinalReviewEvidenceCard> = {
    elapsed: {
      key: "elapsed",
      label: "处理耗时",
      value: elapsedSeconds ? formatDuration(elapsedSeconds) : "未记录",
      detail: `${(job.steps ?? []).filter((step) => step.status === "done").length}/${job.steps?.length ?? 0} 个步骤完成`,
    },
    tokens: {
      key: "tokens",
      label: "Token 消耗",
      value: tokenUsage ? formatCompactNumber(tokenUsage.total_tokens) : "未记录",
      detail: tokenTopStep ? `最高 ${tokenTopStep.label || tokenTopStep.step_name} ${formatCompactNumber(tokenTopStep.total_tokens)}` : "暂无 LLM token 统计",
    },
    subtitles: {
      key: "subtitles",
      label: "字幕纠偏",
      value: report ? formatCompactNumber(report.total_corrections) : "未记录",
      detail: reportCorrectionDetail(report),
    },
    cuts: {
      key: "cuts",
      label: "智能删减",
      value: editStats.removedSegments ? `${editStats.removedSegments} 段` : "未记录",
      detail: editStats.removedSeconds ? `压缩 ${formatDuration(editStats.removedSeconds)} · ${editStats.detail || editStats.summary}` : (editStats.detail || editStats.summary || "暂无剪辑决策统计"),
    },
    cleanup: {
      key: "cleanup",
      label: "噪音/冗余清理",
      value: editStats.cleanupCount ? `${editStats.cleanupCount} 处` : "未记录",
      detail: "统计静音、口癖、重复、低信息和边界修剪类删减",
    },
    llm: {
      key: "llm",
      label: "LLM 剪辑复核",
      value: diagnostics?.llm_reviewed ? `${diagnostics.llm_candidate_count ?? 0} 个` : "未触发",
      detail: uniqueTexts([
        diagnostics?.llm_summary,
        diagnostics?.llm_restored_cut_count ? `恢复 ${diagnostics.llm_restored_cut_count} 个 cut` : "",
        diagnostics?.llm_provider ? `provider ${diagnostics.llm_provider}` : "",
      ]).join(" · ") || "无高风险 cut 复核记录",
    },
    visualProtection: {
      key: "visualProtection",
      label: "画面保护",
      value: `${diagnostics?.protected_visual_cut_count ?? 0}`,
      detail: `高保护证据 ${diagnostics?.high_protection_evidence_count ?? 0} 个，避免误删展示镜头`,
    },
    effects: {
      key: "effects",
      label: "增强能力",
      value: `${job.enhancement_modes?.length ?? 0} 项`,
      detail: enhancementCapabilityDetail(job),
    },
    outputs: {
      key: "outputs",
      label: "输出物",
      value: `${videoFileCount}`,
      detail: `${videoFileCount} 个候选视频文件 · ${job.publication_summary || "等待发布物料接收"}`,
    },
    directorPlan: {
      key: "directorPlan",
      label: "导演编排",
      value: directorDecisions.length ? `${directorDecisions.length} 项` : "未记录",
      detail: uniqueTexts([
        directorPrimaryDecision?.summary,
        directorPrimaryDecision?.detail,
      ]).join(" · ") || "等待智能导演计划、分镜、台词或包装日志",
    },
    voiceover: {
      key: "voiceover",
      label: "解说重组",
      value: voiceoverSegments ? `${voiceoverSegments} 段` : (dialogueDecision ? "已生成" : "未记录"),
      detail: dialogueText || "暂无台词润色、旁白重配或数字人解说统计",
    },
    remixAssembly: {
      key: "remixAssembly",
      label: "二创编排",
      value: editStats.removedSegments ? `${editStats.removedSegments} 段` : "未记录",
      detail: editStats.removedSeconds
        ? `重组/压缩 ${formatDuration(editStats.removedSeconds)} · ${editStats.detail || editStats.summary}`
        : (editStats.detail || editStats.summary || "暂无影视二创混剪编排统计"),
    },
    autoReview: {
      key: "autoReview",
      label: "异常门",
      value: job.auto_review_mode_enabled ? (job.auto_review_status === "applied" ? "放行" : statusLabel(job.auto_review_status || "running")) : "未启用",
      detail: uniqueTexts([job.auto_review_summary, ...(job.auto_review_reasons ?? [])]).join("；") || "无异常门拦截记录",
    },
    quality: {
      key: "quality",
      label: "质量产物",
      value: formatScoreValue(job.quality_score),
      detail: job.quality_summary || "final_review 质量产物未记录更多扣分项",
    },
  };
  const profileCards: Record<string, string[]> = {
    smart_director: ["elapsed", "tokens", "directorPlan", "voiceover", "visualProtection", "effects", "outputs", "llm"],
    remix: ["elapsed", "tokens", "remixAssembly", "voiceover", "cleanup", "subtitles", "llm", "outputs"],
    software: ["elapsed", "tokens", "subtitles", "cuts", "visualProtection", "llm", "effects", "outputs"],
    tutorial: ["elapsed", "tokens", "subtitles", "cuts", "visualProtection", "llm", "effects", "outputs"],
    edc: ["elapsed", "cuts", "visualProtection", "subtitles", "llm", "effects", "outputs", "tokens"],
    unboxing: ["elapsed", "cuts", "visualProtection", "subtitles", "llm", "effects", "outputs", "tokens"],
    commentary: ["elapsed", "tokens", "cleanup", "subtitles", "llm", "cuts", "effects", "outputs"],
    vlog: ["elapsed", "cleanup", "cuts", "subtitles", "visualProtection", "effects", "outputs", "tokens"],
    gameplay: ["elapsed", "cuts", "visualProtection", "llm", "subtitles", "effects", "outputs", "tokens"],
    food: ["elapsed", "cleanup", "visualProtection", "subtitles", "cuts", "effects", "outputs", "tokens"],
    nature: ["elapsed", "visualProtection", "cuts", "cleanup", "llm", "effects", "outputs", "tokens"],
    default: ["elapsed", "tokens", "subtitles", "cuts", "cleanup", "llm", "effects", "outputs"],
  };
  return (profileCards[metricProfile] ?? profileCards.default).map((key) => cards[key]).filter(Boolean).slice(0, 8);
}

function logIssueStatusLabel(status: string) {
  if (status === "done") return "记录";
  if (status === "needs_review") return "需复核";
  if (status === "failed") return "失败";
  if (status === "blocked") return "阻断";
  return statusLabel(status || "pending");
}

function pushIssue(
  issues: FinalReviewLogIssue[],
  seen: Set<string>,
  issue: FinalReviewLogIssue,
) {
  const key = [issue.title, issue.detail, issue.source].join("|").toLowerCase();
  if (seen.has(key)) return;
  seen.add(key);
  issues.push(issue);
}

function buildFinalReviewLogIssues(job: Job, activity: JobActivity | null | undefined): FinalReviewLogIssue[] {
  const issues: FinalReviewLogIssue[] = [];
  const seen = new Set<string>();
  const activityIssueCodes = new Set(
    (activity?.decisions ?? [])
      .flatMap((decision) => decision.issue_codes ?? [])
      .map((code) => compactText(code).toLowerCase())
      .filter(Boolean),
  );

  (job.quality_issue_codes ?? []).forEach((code, index) => {
    if (activityIssueCodes.has(compactText(code).toLowerCase())) return;
    pushIssue(issues, seen, {
      id: `quality-code-${index}`,
      title: compactText(code) || "质量扣分项",
      detail: job.quality_summary || "final_review 质量评分产物报告了扣分项。",
      status: "needs_review",
      source: "质量评分",
    });
  });

  (job.timeline_diagnostics?.review_reasons ?? []).forEach((reason, index) => {
    pushIssue(issues, seen, {
      id: `timeline-reason-${index}`,
      title: compactText(reason) || "时间线复核原因",
      detail: uniqueTexts([
        job.timeline_diagnostics?.llm_summary,
        job.timeline_diagnostics?.high_risk_cut_count ? `高风险 cut ${job.timeline_diagnostics.high_risk_cut_count} 个` : "",
        job.timeline_diagnostics?.protected_visual_cut_count ? `展示保护命中 ${job.timeline_diagnostics.protected_visual_cut_count} 个` : "",
      ]).join("；") || "时间线诊断建议复核。",
      status: "needs_review",
      source: "时间线诊断",
    });
  });

  (job.auto_review_reasons ?? []).forEach((reason, index) => {
    pushIssue(issues, seen, {
      id: `auto-review-${index}`,
      title: compactText(reason) || "异常门原因",
      detail: job.auto_review_summary || "自动审查报告了需要关注的原因。",
      status: job.auto_review_status || "needs_review",
      source: "异常门",
    });
  });

  (activity?.decisions ?? []).forEach((decision, index) => {
    const issueCodes = decision.issue_codes ?? [];
    const shouldShow = Boolean(
      decision.blocking
      || ["needs_review", "failed", "blocked"].includes(decision.status)
      || issueCodes.length
      || (decision.kind === "quality_assessment" && decision.detail)
    );
    if (!shouldShow) return;
    pushIssue(issues, seen, {
      id: `decision-${decision.kind}-${index}`,
      title: decision.title || decision.kind,
      detail: uniqueTexts([
        decision.summary,
        decision.detail,
        issueCodes.length ? `问题码：${issueCodes.join(", ")}` : "",
      ]).join("；") || "任务决策记录需要复核。",
      status: decision.blocking ? "blocked" : decision.status,
      source: decision.step_name || decision.kind,
    });
  });

  (activity?.events ?? []).forEach((event, index) => {
    if (!["failed", "needs_review", "blocked"].includes(event.status)) return;
    pushIssue(issues, seen, {
      id: `event-${event.type}-${index}`,
      title: event.title || event.type,
      detail: compactText(event.detail) || "任务事件记录需要复核。",
      status: event.status,
      source: event.step_name || event.type,
    });
  });

  return issues.slice(0, 8);
}

function reviewStatusFilterKey(job: Job): string {
  if (job.status === "published" || job.publication_status === "published") return "published";
  if (job.status === "needs_review") return "needs_review";
  return job.status || "unknown";
}

function reviewStatusFilterLabel(job: Job): string {
  if (job.status === "published" || job.publication_status === "published") return "已发布";
  if (job.status === "done") return "完成输出";
  return statusLabel(job.status);
}

function reviewCreatorFilterKey(job: Job): string {
  if (job.creator_card_id) return `creator:${job.creator_card_id}`;
  const name = String(job.creator_card_name || "").trim();
  return name ? `creator-name:${name}` : "creator:unbound";
}

function reviewCreatorFilterLabel(job: Job): string {
  return String(job.creator_card_name || "").trim() || "未绑定创作者";
}

function buildReviewFilterOptions(
  jobs: Job[],
  keyGetter: (job: Job) => string,
  labelGetter: (job: Job) => string,
): ReviewFilterOption[] {
  const options = new Map<string, ReviewFilterOption>();
  for (const job of jobs) {
    const key = keyGetter(job);
    const label = labelGetter(job);
    const existing = options.get(key);
    if (existing) {
      existing.count += 1;
    } else {
      options.set(key, { key, label, count: 1 });
    }
  }
  return Array.from(options.values()).sort((left, right) => {
    if (right.count !== left.count) return right.count - left.count;
    return left.label.localeCompare(right.label, "zh-CN");
  });
}

function matchesReviewTimeFilter(job: Job, filter: ReviewTimeFilter): boolean {
  const lowerBound = reviewTimeFilterLowerBound(filter);
  if (!lowerBound) return true;
  const updatedAt = new Date(job.updated_at).getTime();
  return Number.isFinite(updatedAt) && updatedAt >= lowerBound.getTime();
}

function reviewTimeFilterLowerBound(filter: ReviewTimeFilter): Date | null {
  if (filter === "all") return null;
  const daySpan = filter === "today" ? 1 : filter === "three_days" ? 3 : 7;
  const lowerBound = new Date();
  lowerBound.setHours(0, 0, 0, 0);
  lowerBound.setDate(lowerBound.getDate() - (daySpan - 1));
  return lowerBound;
}

function ReviewFilterGroup({
  title,
  emptyLabel,
  options,
  selectedKeys,
  onToggle,
}: {
  title: string;
  emptyLabel: string;
  options: ReviewFilterOption[];
  selectedKeys: string[];
  onToggle: (key: string) => void;
}) {
  return (
    <div className="publication-filter-group">
      <div className="publication-filter-group-head">
        <strong>{title}</strong>
        <span>{selectedKeys.length ? `已选 ${selectedKeys.length}` : "不限"}</span>
      </div>
      <div className="publication-filter-chip-grid">
        {options.length ? (
          options.map((option) => (
            <button
              key={option.key}
              type="button"
              className={`publication-filter-chip${selectedKeys.includes(option.key) ? " selected" : ""}`}
              aria-pressed={selectedKeys.includes(option.key)}
              onClick={() => onToggle(option.key)}
            >
              <span>{option.label}</span>
              <em>{option.count}</em>
            </button>
          ))
        ) : (
          <span className="publication-filter-empty">{emptyLabel}</span>
        )}
      </div>
    </div>
  );
}

export function FinalReviewPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, ReviewCheckDecision>>({});
  const [reviewNote, setReviewNote] = useState("整体剪辑体验符合要求，建议通过并进入发布跟踪。");
  const [jobSearch, setJobSearch] = useState("");
  const [filtersExpanded, setFiltersExpanded] = useState(true);
  const [selectedCreatorFilters, setSelectedCreatorFilters] = useState<string[]>([]);
  const [selectedStatusFilters, setSelectedStatusFilters] = useState<string[]>([]);
  const [selectedTimeFilter, setSelectedTimeFilter] = useState<ReviewTimeFilter>("all");
  const jobs = useQuery<Job[], Error>({ queryKey: ["jobs", "final-review", 500], queryFn: () => api.listJobs(500) });
  const completedClipJobs = useMemo(() => (jobs.data ?? []).filter(isCompletedClipJob), [jobs.data]);
  const creatorFilterOptions = useMemo(
    () => buildReviewFilterOptions(completedClipJobs, reviewCreatorFilterKey, reviewCreatorFilterLabel),
    [completedClipJobs],
  );
  const statusFilterOptions = useMemo(
    () => buildReviewFilterOptions(completedClipJobs, reviewStatusFilterKey, reviewStatusFilterLabel),
    [completedClipJobs],
  );
  const activeFilterCount = selectedCreatorFilters.length
    + selectedStatusFilters.length
    + (selectedTimeFilter === "all" ? 0 : 1);
  const filteredReviewJobs = useMemo(() => {
    const query = jobSearch.trim().toLowerCase();
    const creatorFilterSet = new Set(selectedCreatorFilters);
    const statusFilterSet = new Set(selectedStatusFilters);
    return completedClipJobs.filter((job) => {
      if (creatorFilterSet.size && !creatorFilterSet.has(reviewCreatorFilterKey(job))) return false;
      if (statusFilterSet.size && !statusFilterSet.has(reviewStatusFilterKey(job))) return false;
      if (!matchesReviewTimeFilter(job, selectedTimeFilter)) return false;
      if (!query) return true;
      return [
        job.source_name,
        job.content_subject,
        job.content_summary,
        job.creator_card_name,
        reviewStatusFilterLabel(job),
        job.status,
      ].join(" ").toLowerCase().includes(query);
    });
  }, [completedClipJobs, jobSearch, selectedCreatorFilters, selectedStatusFilters, selectedTimeFilter]);
  const routeJobId = searchParams.get("job");
  const selectedJob = completedClipJobs.find((job) => job.id === selectedJobId)
    ?? completedClipJobs.find((job) => job.id === routeJobId)
    ?? filteredReviewJobs[0]
    ?? completedClipJobs[0]
    ?? null;
  const files = useQuery({
    queryKey: ["job-download-files", selectedJob?.id],
    queryFn: () => api.getJobDownloadFiles(selectedJob!.id),
    enabled: Boolean(selectedJob?.id),
    retry: false,
  });
  const contentProfile = useQuery<ContentProfileReview, Error>({
    queryKey: ["job-content-profile", selectedJob?.id, "final-review"],
    queryFn: () => api.getContentProfile(selectedJob!.id),
    enabled: Boolean(selectedJob?.id),
    retry: false,
  });
  const activity = useQuery<JobActivity, Error>({
    queryKey: ["job-activity", selectedJob?.id, "final-review"],
    queryFn: () => api.getJobActivity(selectedJob!.id),
    enabled: Boolean(selectedJob?.id),
    retry: false,
  });
  const report = useQuery<Report, Error>({
    queryKey: ["job-report", selectedJob?.id, "final-review"],
    queryFn: () => api.getJobReport(selectedJob!.id),
    enabled: Boolean(selectedJob?.id),
    retry: false,
  });
  const tokenUsage = useQuery<TokenUsageReport, Error>({
    queryKey: ["job-token-usage", selectedJob?.id, "final-review"],
    queryFn: () => api.getJobTokenUsage(selectedJob!.id),
    enabled: Boolean(selectedJob?.id),
    retry: false,
  });
  const videoFiles = useMemo(() => {
    const candidates = (files.data?.files ?? []).filter((file) => file.kind === "video");
    return [...candidates].sort((left, right) => {
      const rank = (file: JobDownloadFile) => file.id === "enhanced_mp4" ? 0 : file.id === "packaged_mp4" ? 1 : 2;
      return rank(left) - rank(right);
    });
  }, [files.data]);
  const activeFile = videoFiles.find((file) => file.id === selectedFileId) ?? videoFiles[0] ?? null;
  const activeUrl = selectedJob && activeFile ? api.jobRenderedFileUrl(selectedJob.id, finalVideoVariant(activeFile)) : "";
  const audienceReviewItems = useMemo(
    () => buildAudienceReviewItems(selectedJob, contentProfile.data ?? null),
    [selectedJob, contentProfile.data],
  );
  useEffect(() => {
    const validIds = new Set(audienceReviewItems.map((item) => item.id));
    setChecks((current) => {
      const next = Object.fromEntries(Object.entries(current).filter(([id]) => validIds.has(id))) as Record<string, ReviewCheckDecision>;
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [audienceReviewItems]);
  const checkedCount = audienceReviewItems.filter((item) => checks[item.id]).length;
  const failedItems = audienceReviewItems.filter((item) => checks[item.id] === "fail");
  const pendingItems = audienceReviewItems.filter((item) => !checks[item.id]);
  const evaluationComplete = checkedCount === audienceReviewItems.length;
  const evaluationPassed = evaluationComplete && failedItems.length === 0;
  const evaluationStatusLabel = evaluationPassed ? "建议通过" : failedItems.length ? "建议调整" : "待评估";
  const evidenceCards = selectedJob
    ? buildFinalReviewEvidenceCards(
        selectedJob,
        activity.data ?? null,
        report.data ?? null,
        tokenUsage.data ?? null,
        contentProfile.data ?? null,
        videoFiles.length,
      )
    : [];
  const logIssues = selectedJob ? buildFinalReviewLogIssues(selectedJob, activity.data ?? null) : [];
  const finalReviewDecision = useMutation({
    mutationFn: (payload: { jobId: string; decision: "approve" | "reject"; note?: string }) =>
      api.finalReviewDecision(payload.jobId, { decision: payload.decision, note: payload.note }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["jobs", "final-review", 500] });
    },
  });

  const selectJob = (jobId: string) => {
    setSelectedJobId(jobId);
    setSearchParams({ job: jobId });
    setSelectedFileId(null);
    setChecks({});
    setReviewNote("整体剪辑体验符合要求，建议通过并进入发布跟踪。");
  };

  const toggleCreatorFilter = (creatorKey: string) => {
    setSelectedCreatorFilters((current) =>
      current.includes(creatorKey) ? current.filter((key) => key !== creatorKey) : [...current, creatorKey],
    );
  };

  const toggleStatusFilter = (statusKey: string) => {
    setSelectedStatusFilters((current) =>
      current.includes(statusKey) ? current.filter((key) => key !== statusKey) : [...current, statusKey],
    );
  };

  const clearFilters = () => {
    setSelectedCreatorFilters([]);
    setSelectedStatusFilters([]);
    setSelectedTimeFilter("all");
    setJobSearch("");
  };

  return (
    <section className="page-stack final-review-page">
      <PageHeader
        title="成片审看"
        description="围绕剪辑体验检查最终成片，确认是否进入发布跟踪。"
      />

      {jobs.isLoading ? <EmptyState message="正在加载已完成剪辑。" /> : null}
      {jobs.isError ? <EmptyState message={jobs.error.message} tone="error" /> : null}
      {!jobs.isLoading && !jobs.isError && completedClipJobs.length === 0 ? (
        <EmptyState message="当前没有已完成剪辑的视频。完成制片后会出现在这里。" />
      ) : null}

      {selectedJob ? (
        <div className="final-review-shell">
          <aside className="final-review-queue-panel final-review-video-picker" aria-label="待审看视频筛选">
            <PanelHeader
              title="选择待审看视频"
              description="显示所有已完成剪辑的视频，可搜索或按标签筛选。"
              actions={<span className="mode-chip subtle">{jobs.isLoading ? "读取中" : `${filteredReviewJobs.length} 条`}</span>}
            />
            <label className="publication-video-search">
              <Search size={15} aria-hidden="true" />
              <input
                className="input"
                value={jobSearch}
                onChange={(event) => setJobSearch(event.target.value)}
                placeholder="搜索成片 / 作业 / 创作者"
              />
            </label>
            <div className={`publication-video-filter-panel${filtersExpanded ? " expanded" : ""}`}>
              <button
                type="button"
                className="publication-video-filter-toggle"
                aria-expanded={filtersExpanded}
                onClick={() => setFiltersExpanded((current) => !current)}
              >
                <Filter size={15} aria-hidden="true" />
                <span>
                  <strong>标签筛选</strong>
                  <small>
                    {activeFilterCount
                      ? `${activeFilterCount} 项已启用 · ${filteredReviewJobs.length}/${completedClipJobs.length}`
                      : "创作者 / 状态 / 时间"}
                  </small>
                </span>
                <ChevronDown size={16} aria-hidden="true" />
              </button>
              {filtersExpanded ? (
                <div className="publication-video-filter-body">
                  <ReviewFilterGroup
                    title="创作者"
                    emptyLabel="暂无创作者"
                    options={creatorFilterOptions}
                    selectedKeys={selectedCreatorFilters}
                    onToggle={toggleCreatorFilter}
                  />
                  <ReviewFilterGroup
                    title="状态"
                    emptyLabel="暂无状态"
                    options={statusFilterOptions}
                    selectedKeys={selectedStatusFilters}
                    onToggle={toggleStatusFilter}
                  />
                  <div className="publication-filter-group">
                    <div className="publication-filter-group-head">
                      <strong>时间</strong>
                      <span>{selectedTimeFilter === "all" ? "不限" : REVIEW_TIME_FILTERS.find((item) => item.key === selectedTimeFilter)?.label}</span>
                    </div>
                    <div className="publication-time-filter-strip" aria-label="审看时间过滤">
                      {REVIEW_TIME_FILTERS.map((item) => (
                        <button
                          key={item.key}
                          type="button"
                          className={`publication-filter-chip${selectedTimeFilter === item.key ? " selected" : ""}`}
                          aria-pressed={selectedTimeFilter === item.key}
                          onClick={() => setSelectedTimeFilter(item.key)}
                        >
                          {item.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="publication-video-filter-footer">
                    <span>{filteredReviewJobs.length} 条匹配</span>
                    <button
                      type="button"
                      className="button ghost button-sm"
                      disabled={!activeFilterCount && !jobSearch.trim()}
                      onClick={clearFilters}
                    >
                      <X size={14} aria-hidden="true" />
                      清除筛选
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
            <div className="publication-video-list final-review-video-list" aria-label="待审看视频">
              {filteredReviewJobs.length ? (
                filteredReviewJobs.slice(0, 80).map((job) => (
                  <button
                    key={job.id}
                    type="button"
                    className={`publication-video-item final-review-video-item${job.id === selectedJob.id ? " selected" : ""}`}
                    onClick={() => selectJob(job.id)}
                  >
                    <span className={job.status === "done" ? "status-pill done" : "status-pill running"}>
                      {reviewStatusFilterLabel(job)}
                    </span>
                    <strong>{job.source_name}</strong>
                    <small>{formatDate(job.updated_at)} · {job.creator_card_name || job.content_subject || job.status}</small>
                  </button>
                ))
              ) : (
                <EmptyState message="没有匹配的已完成剪辑。请调整搜索或筛选条件。" />
              )}
              {filteredReviewJobs.length > 80 ? (
                <div className="publication-filter-empty">已显示前 80 条，请继续搜索缩小范围。</div>
              ) : null}
            </div>
          </aside>

          <main className="final-review-main-panel">
            <div className="final-review-tabs" aria-label="候选版本">
              {files.isLoading ? <span className="muted">正在读取视频清单...</span> : null}
              {files.isError ? <span className="muted">未找到候选版本</span> : null}
              {!files.isLoading && !files.isError && videoFiles.length === 0 ? <span className="muted">没有发现最终视频文件。</span> : null}
              {videoFiles.map((file, index) => (
                <button
                  key={file.id}
                  type="button"
                  className={classNames("final-review-tab", activeFile?.id === file.id && "is-active")}
                  onClick={() => setSelectedFileId(file.id)}
                >
                  {videoRoleLabel(file, index)}
                </button>
              ))}
            </div>

            <div className="final-review-video-frame">
              {activeUrl ? (
                <video
                  key={`${selectedJob.id}:${activeFile?.id || "auto"}`}
                  className="final-review-player"
                  src={activeUrl}
                  controls
                  preload="metadata"
                  playsInline
                />
              ) : (
                <EmptyState message={files.isError ? "未找到可播放成片，请回到制片队列检查输出。" : "暂无可播放的最终视频。"} />
              )}
            </div>

            <section className="final-review-info-block" aria-label="成片信息">
              <h2>成片信息</h2>
              <dl className="final-review-meta-row">
                <div>
                  <dt>项目名称</dt>
                  <dd>{selectedJob.source_name}</dd>
                </div>
                <div>
                  <dt>候选版本</dt>
                  <dd>{activeFile ? videoRoleLabel(activeFile, videoFiles.indexOf(activeFile)) : "-"}</dd>
                </div>
                <div>
                  <dt>文件大小</dt>
                  <dd>{activeFile ? formatBytes(activeFile.size_bytes) : "-"}</dd>
                </div>
                <div>
                  <dt>提交时间</dt>
                  <dd>{formatDate(selectedJob.updated_at)}</dd>
                </div>
                <div>
                  <dt>提交人</dt>
                  <dd>{selectedJob.creator_card_name || "系统"}</dd>
                </div>
              </dl>
            </section>

            <section className="final-review-info-block" aria-label="能力统计">
              <h2>能力统计</h2>
              <div className="final-review-quality-grid">
                {evidenceCards.map((card) => (
                  <div key={card.key}>
                    <span>{card.label}</span>
                    <strong>{card.value}</strong>
                    <small>{card.detail}</small>
                  </div>
                ))}
              </div>
            </section>

            <section className="final-review-info-block" aria-label="问题记录">
              <h2>问题记录</h2>
              <div className="final-review-issues">
                {activity.isLoading ? (
                  <div className="final-review-issue">
                    <span>读取中</span>
                    <strong>正在读取剪辑任务日志和分析结果。</strong>
                    <em>任务日志</em>
                  </div>
                ) : logIssues.length === 0 ? (
                  <div className="final-review-issue is-clear">
                    <span>无异常</span>
                    <strong>任务日志和 LLM 分析未报告阻断问题。</strong>
                    <em>系统证据</em>
                  </div>
                ) : (
                  logIssues.map((item, index) => (
                    <div
                      className={classNames(
                        "final-review-issue",
                        ["failed", "blocked", "needs_review"].includes(item.status) && "is-failed",
                      )}
                      key={item.id}
                    >
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <div className="final-review-issue-copy">
                        <strong>{item.title}</strong>
                        <small>{item.detail}</small>
                      </div>
                      <em>{item.source} · {logIssueStatusLabel(item.status)}</em>
                    </div>
                  ))
                )}
              </div>
            </section>
          </main>

          <aside className="final-review-inspector" aria-label="剪辑体验清单">
            <div className="final-review-inspector-head">
              <div>
                <span>剪辑体验清单</span>
                <strong>{evaluationComplete ? "评估完成" : "待评估"}</strong>
              </div>
              <span className={evaluationComplete ? "status-pill done" : "status-pill running"}>{checkedCount}/{audienceReviewItems.length}</span>
            </div>
            <div className="final-review-checklist">
              {audienceReviewItems.map((item) => (
                <div key={item.id} className={classNames("final-review-check", checks[item.id] && `is-${checks[item.id]}`)}>
                  <div className="final-review-check-actions" aria-label={`${item.label} 审看结果`}>
                    <button
                      type="button"
                      className={classNames("final-review-check-action", checks[item.id] === "pass" && "is-active")}
                      aria-label={`符合：${item.label}`}
                      title="符合"
                      aria-pressed={checks[item.id] === "pass"}
                      onClick={() => setChecks((current) => ({ ...current, [item.id]: "pass" }))}
                    >
                      <Check size={15} aria-hidden="true" />
                    </button>
                    <button
                      type="button"
                      className={classNames("final-review-check-action", checks[item.id] === "fail" && "is-active")}
                      aria-label={`不符合：${item.label}`}
                      title="不符合"
                      aria-pressed={checks[item.id] === "fail"}
                      onClick={() => setChecks((current) => ({ ...current, [item.id]: "fail" }))}
                    >
                      <X size={15} aria-hidden="true" />
                    </button>
                  </div>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.detail}</small>
                  </span>
                </div>
              ))}
            </div>
            <div className="final-review-evaluation">
              <div className="final-review-evaluation-head">
                <strong>总体评价</strong>
                <span>{evaluationStatusLabel}</span>
              </div>
              <textarea
                value={reviewNote}
                onChange={(event) => setReviewNote(event.target.value)}
                maxLength={200}
                aria-label="总体评价"
              />
              <small>{reviewNote.length}/200</small>
            </div>
            <div className="final-review-log">
              <strong>操作记录</strong>
              <div>
                <span>{selectedJob.creator_card_name || "系统"}</span>
                <small>{formatDate(selectedJob.updated_at)}</small>
                <p>{selectedJob.review_detail || selectedJob.quality_summary || "提交成片审看。"}</p>
              </div>
            </div>
            <div className={classNames("final-review-readiness", evaluationComplete && "is-complete")}>
              {evaluationPassed
                ? "剪辑体验评估通过，可进入发布确认。"
                : failedItems.length
                  ? `有 ${failedItems.length} 项不符合，建议退回手动调整；清单仅作评估，不阻挡进入发布跟踪。`
                  : `还有 ${audienceReviewItems.length - checkedCount} 项剪辑体验待评估；清单不作为发布入口阻断条件。`}
            </div>
            <div className="toolbar final-review-actions">
              <Link
                className={classNames("button ghost", finalReviewDecision.isPending && "is-disabled")}
                to={`/jobs/${encodeURIComponent(selectedJob.id)}/manual-editor`}
                aria-disabled={finalReviewDecision.isPending}
                onClick={(event) => {
                  if (finalReviewDecision.isPending) {
                    event.preventDefault();
                    return;
                  }
                  finalReviewDecision.mutate({ jobId: selectedJob.id, decision: "reject", note: reviewNote || "成片审看退回手动调整" });
                }}
              >
                退回手动调整
              </Link>
              <Link
                className={classNames("button primary", finalReviewDecision.isPending && "is-disabled")}
                to={`/publication-tracking?job=${encodeURIComponent(selectedJob.id)}`}
                aria-disabled={finalReviewDecision.isPending}
                onClick={(event) => {
                  if (finalReviewDecision.isPending) {
                    event.preventDefault();
                    return;
                  }
                  finalReviewDecision.mutate({ jobId: selectedJob.id, decision: "approve", note: reviewNote || "成片审看通过" });
                }}
              >
                通过并进入发布跟踪
              </Link>
            </div>
          </aside>
        </div>
      ) : null}
    </section>
  );
}
