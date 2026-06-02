import http from "node:http";
import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const CONTRACT = "browser_agent_publication_inventory_v1";
const TASK_CONTRACT = "browser_agent_publication_v1";
const TASK_LINK_SHARE_CONTRACT = "x_link_share_publication_v1";
export const PUBLICATION_TASK_IDENTITY_CONTRACT = "publication_task_identity_v1";
export const PUBLICATION_CREATOR_SESSION_CONTRACT = "publication_creator_session_probe_v1";
const TASK_CONTRACTS = new Set([TASK_CONTRACT, TASK_LINK_SHARE_CONTRACT]);
const PORT = Number(process.env.PUBLICATION_BROWSER_AGENT_PORT || 49310);
const HOST = String(process.env.PUBLICATION_BROWSER_AGENT_HOST || "0.0.0.0");
const CDP_URL = String(process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const _RECOVERY_EVIDENCE_MAX_LINES = 160;
const ATTACHED_BROWSER = String(process.env.PUBLICATION_BROWSER || "chrome").trim().toLowerCase();
const ATTACHED_USER_DATA_DIR = String(process.env.PUBLICATION_BROWSER_USER_DATA_DIR || "").trim();
const ATTACHED_PROFILE_DIRECTORY = String(process.env.PUBLICATION_BROWSER_PROFILE_DIRECTORY || "").trim();
const ALLOW_PUBLICATION_TAB_AUTOCREATE = /^(1|true|yes)$/i.test(
  String(process.env.PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE || "").trim(),
);
const LIVE_PUBLISH_ENABLED = /^(1|true|yes)$/i.test(String(process.env.PUBLICATION_LIVE_PUBLISH_ENABLED || ""));
const _configuredPublicationTaskTimeoutMs = Number(process.env.PUBLICATION_TASK_TIMEOUT_MS || "");
const PUBLICATION_TASK_TIMEOUT_MS = Number.isFinite(_configuredPublicationTaskTimeoutMs) && _configuredPublicationTaskTimeoutMs > 0
  ? Math.max(60000, Math.floor(_configuredPublicationTaskTimeoutMs))
  : 240000;
const FINAL_PUBLISH_EXECUTOR_IMPLEMENTED = true;
const COMPOSITE_PUBLISH_PLATFORMS = new Set(["douyin", "bilibili", "youtube", "xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"]);
const FINAL_PUBLISH_PLATFORMS = new Set([...COMPOSITE_PUBLISH_PLATFORMS]);
const TASKS = new Map();
const IS_MAIN = Boolean(process.argv[1]) && import.meta.url === pathToFileURL(process.argv[1]).href;
const SERVICE_SCRIPT_PATH = fileURLToPath(import.meta.url);
const SCRIPT_DIR = path.dirname(SERVICE_SCRIPT_PATH);
export const SERVICE_SCRIPT_SHA256 = createHash("sha256")
  .update(fs.readFileSync(SERVICE_SCRIPT_PATH))
  .digest("hex");
const PUBLICATION_PLATFORM_MATRIX_PATH = path.resolve(SCRIPT_DIR, "../src/roughcut/publication_platform_matrix.json");
const VISUAL_EVIDENCE_DIR = path.resolve(
  process.env.PUBLICATION_VISUAL_EVIDENCE_DIR || path.resolve(SCRIPT_DIR, "../artifacts/publication-visual-evidence"),
);
const PUBLICATION_PLATFORM_MATRIX = JSON.parse(fs.readFileSync(PUBLICATION_PLATFORM_MATRIX_PATH, "utf8"));
const PUBLICATION_PLATFORM_CAPABILITIES = PUBLICATION_PLATFORM_MATRIX.platforms && typeof PUBLICATION_PLATFORM_MATRIX.platforms === "object"
  ? PUBLICATION_PLATFORM_MATRIX.platforms
  : {};
const COMPOSITE_COLLECTION_POLICY_SKIP_VALUES = new Set(
  Array.isArray(PUBLICATION_PLATFORM_MATRIX.collection_policy_skip_values)
    ? PUBLICATION_PLATFORM_MATRIX.collection_policy_skip_values.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean)
    : [],
);
const COMPOSITE_COVER_POLICY_SKIP_VALUES = new Set(
  Array.isArray(PUBLICATION_PLATFORM_MATRIX.cover_policy_skip_values)
    ? PUBLICATION_PLATFORM_MATRIX.cover_policy_skip_values.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean)
    : [],
);

function compositePlatformCapabilities(platform) {
  const normalizedPlatform = normalizePlatform(platform);
  const entry = PUBLICATION_PLATFORM_CAPABILITIES[normalizedPlatform];
  return entry && typeof entry === "object" ? entry : {};
}

function compositePlatformDefaultDeclaration(platform) {
  return String(compositePlatformCapabilities(platform).default_declaration || "").trim();
}

function compositePlatformSoftVerificationFields(platform) {
  const rawFields = compositePlatformCapabilities(platform).soft_verification_fields;
  if (!Array.isArray(rawFields)) return new Set();
  return new Set(rawFields.map((item) => String(item || "").trim().toLowerCase()).filter(Boolean));
}

function compositePlatformSkipsExplicitTagEntry(platform) {
  return Boolean(compositePlatformCapabilities(platform).skip_explicit_tag_entry);
}

function compositePlatformMinimumScheduleLeadMinutes(platform) {
  const rawValue = compositePlatformCapabilities(platform).minimum_schedule_lead_minutes;
  const value = Number.parseInt(String(rawValue ?? ""), 10);
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function sanitizeVisualEvidenceSegment(value, fallback = "unknown", maxLength = 48) {
  const normalized = String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  const output = normalized || fallback;
  return output.slice(0, maxLength);
}

function normalizeVisualEvidence(payload) {
  if (!payload || typeof payload !== "object") return null;
  const artifactPath = String(payload.artifact_path || "").trim();
  if (!artifactPath) return null;
  const normalized = {
    artifact_path: artifactPath,
    capture_type: String(payload.capture_type || "").trim() || "screenshot",
    mime_type: String(payload.mime_type || "image/png").trim() || "image/png",
    sha256: String(payload.sha256 || "").trim(),
    captured_at: String(payload.captured_at || "").trim(),
    platform: String(payload.platform || "").trim(),
    phase: String(payload.phase || "").trim(),
    route_url: String(payload.route_url || "").trim(),
    route_title: String(payload.route_title || "").trim(),
    byte_size: Number(payload.byte_size || 0),
  };
  const width = Number(payload.width || 0);
  const height = Number(payload.height || 0);
  if (Number.isFinite(width) && width > 0) normalized.width = Math.floor(width);
  if (Number.isFinite(height) && height > 0) normalized.height = Math.floor(height);
  return normalized;
}

async function capturePageVisualEvidence(client, {
  platform = "",
  phase = "",
  snapshot = null,
} = {}) {
  try {
    await client.send("Page.enable").catch(() => {});
    const screenshot = await client.send("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: false,
      optimizeForSpeed: true,
    });
    const data = String(screenshot?.data || "").trim();
    if (!data) return null;
    const imageBuffer = Buffer.from(data, "base64");
    if (!imageBuffer.length) return null;
    const capturedAt = new Date().toISOString();
    const dateBucket = capturedAt.slice(0, 10).replace(/-/g, "");
    const platformBucket = sanitizeVisualEvidenceSegment(platform, "unknown-platform", 40);
    const phaseBucket = sanitizeVisualEvidenceSegment(phase, "snapshot", 56);
    const artifactDir = path.join(VISUAL_EVIDENCE_DIR, dateBucket, platformBucket);
    fs.mkdirSync(artifactDir, { recursive: true });
    const fileName = `${capturedAt.replace(/[:.]/g, "-")}-${phaseBucket}-${randomUUID().slice(0, 8)}.png`;
    const artifactPath = path.join(artifactDir, fileName);
    fs.writeFileSync(artifactPath, imageBuffer);
    const metrics = await client.send("Page.getLayoutMetrics").catch(() => null);
    return normalizeVisualEvidence({
      artifact_path: artifactPath,
      mime_type: "image/png",
      sha256: createHash("sha256").update(imageBuffer).digest("hex"),
      captured_at: capturedAt,
      platform,
      phase,
      route_url: String(snapshot?.url || "").trim(),
      route_title: String(snapshot?.title || "").trim(),
      byte_size: imageBuffer.length,
      width: Number(metrics?.cssLayoutViewport?.clientWidth || metrics?.layoutViewport?.clientWidth || 0),
      height: Number(metrics?.cssLayoutViewport?.clientHeight || metrics?.layoutViewport?.clientHeight || 0),
    });
  } catch {
    return null;
  }
}

async function attachVisualEvidenceToSnapshot(client, snapshot, options = {}) {
  const baseSnapshot = snapshot && typeof snapshot === "object" ? { ...snapshot } : {};
  const visualEvidence = await capturePageVisualEvidence(client, {
    platform: options.platform || "",
    phase: options.visualEvidencePhase || options.phase || "snapshot",
    snapshot: baseSnapshot,
  });
  if (visualEvidence) {
    baseSnapshot.visual_evidence = visualEvidence;
  }
  return baseSnapshot;
}

function isCdpRuntimeEvaluationTimeout(error) {
  const message = String(error?.message || error || "");
  return /CDP Runtime\.enable timed out|CDP Runtime\.evaluate timed out|Runtime\.evaluate timeout/i.test(message);
}

export function deriveCompositeCdpTimeoutWaitEnvelope({
  platform,
  route = {},
  content = {},
  actions = [],
  error = null,
  prepublishOnlyCurrentPage = false,
  prepareOnlyCurrentPage = false,
  stopBeforeFinalPublish = false,
}) {
  const normalizedPlatform = normalizePlatform(platform);
  const routeUrl = String(route?.url || "");
  const uploadResumeSurface = normalizedPlatform === "youtube"
    && shouldPreserveYouTubeUploadResumeRoute(routeUrl, "");
  const editorSurface = normalizedPlatform === "youtube"
    && /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(routeUrl);
  if (!uploadResumeSurface && !editorSurface) {
    return null;
  }
  const verificationReason = editorSurface ? "editor_surface_runtime_timeout" : "upload_resume_runtime_timeout";
  const materialIntegrity = buildPendingUploadMaterialIntegrity(normalizedPlatform, {
    ready: false,
    failed: false,
    waited_ms: 0,
    pending_reason: verificationReason,
    last: {
      platform: normalizedPlatform,
      busy: uploadResumeSurface,
      mediaPresent: true,
      uploadPromptOnly: false,
      fileInputCount: 0,
      totalFileInputCount: 0,
      youtubeUploadRoute: uploadResumeSurface,
      youtubeHasEditorSurface: editorSurface,
      youtubeChannelContentList: false,
      youtubeDraftResumeAvailable: false,
      lines: [],
    },
  }, route);
  return buildCompositeUploadPendingProcessingEnvelope({
    platform: normalizedPlatform,
    route,
    actions,
    content,
    materialIntegrity,
    code: `${normalizedPlatform}_pre_publish_upload_pending`,
    reason: `页面已进入${editorSurface ? "编辑" : "续传"}表面，但 CDP Runtime 暂时无响应，继续保留现场等待页面恢复。`,
    blockerMessage: editorSurface
      ? "编辑页运行时暂不可读，继续等待编辑表面恢复。"
      : "上传续传页运行时暂不可读，继续等待上传表面恢复。",
    blockerDetails: `runtime_timeout=${String(error?.message || error || "")}`.trim(),
    prepublishOnlyCurrentPage,
    prepareOnlyCurrentPage,
    stopBeforeFinalPublish,
  });
}

export function applyCompositeSafeRuntimePolicyDefaults(platform, content = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const source = content && typeof content === "object" ? content : {};
  const recoveryContext = _extract_publication_recovery_context(source);
  const safeRuntimeMode = Boolean(
    recoveryContext.verification_only_current_page
    || recoveryContext.repair_only_current_page
    || recoveryContext.prepublish_only_current_page
    || recoveryContext.prepare_only_current_page
  );
  if (!safeRuntimeMode) {
    return source;
  }
  const overrides = source.platform_specific_overrides && typeof source.platform_specific_overrides === "object"
    ? { ...source.platform_specific_overrides }
    : {};
  const normalized = { ...source, platform_specific_overrides: overrides };
  const explicitCollectionName = String(source.collection || source.collection_name || "").trim();
  const explicitCollectionPolicy = String(overrides.collection_policy || source.collection_policy || "").trim();
  const explicitCollectionSkip = Boolean(overrides.skip_collection_select || source.skip_collection_select)
    || COMPOSITE_COLLECTION_POLICY_SKIP_VALUES.has(explicitCollectionPolicy.toLowerCase());
  if (
    compositePlatformCapabilities(normalizedPlatform).requires_explicit_collection_policy
    && !explicitCollectionName
    && !explicitCollectionPolicy
    && !explicitCollectionSkip
  ) {
    overrides.collection_policy = "skip";
    overrides.skip_collection_select = true;
  }
  const explicitCoverPath = expectedCoverPath(source);
  const explicitCoverPolicy = String(overrides.cover_policy || source.cover_policy || "").trim();
  const explicitCoverSkip = Boolean(overrides.skip_cover_upload || source.skip_cover_upload)
    || COMPOSITE_COVER_POLICY_SKIP_VALUES.has(explicitCoverPolicy.toLowerCase());
  if (
    compositePlatformCapabilities(normalizedPlatform).requires_custom_cover_policy
    && !explicitCoverPath
    && !explicitCoverPolicy
    && !explicitCoverSkip
  ) {
    overrides.cover_policy = "platform_default";
    overrides.skip_cover_upload = true;
  }
  return normalized;
}

export function detectCompositePublicationSignals(platform, bodyText = "", lines = []) {
  const text = String(bodyText || "");
  const normalizedLines = Array.isArray(lines) ? lines.map((line) => String(line || "").trim()).filter(Boolean) : [];
  const matchLines = (pattern) => normalizedLines.filter((line) => pattern.test(line)).slice(0, 12);
  const uploadFailedPattern = /上传失败|Upload failed|文件里没有有效的视频|无效的视频|视频文件无效|上传出错|上传异常|处理失败|刷新后重试|网络异常/i;
  const uploadBusyPattern = /上传中|正在上传|视频处理中|处理中\s*\d+%|检测中\s*\d+%|检测中99%|已上传：|当前速度：|剩余时间：|\b\d{1,3}%\b/i;
  const uploadBusyConcretePattern = /已上传：|当前速度：|剩余时间：|处理中\s*\d+%|检测中\s*\d+%|检测中99%|\b\d{1,3}%\b/i;
  const uploadPromptOnlyPattern = /拖拽视频到此|点击上传|上传视频\s+视频大小|选择文件|Select files/i;
  const bilibiliBatchDynamicPattern = /批量上传将生成多条动态|打扰粉丝|不生成动态|加入合集并使用/i;
  const uploadFailed = uploadFailedPattern.test(text);
  const douyinStaticUploadReminder =
    platform === "douyin"
    && /点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成/.test(text);
  const douyinEditorSurface =
    platform === "douyin"
    && /预览视频|预览封面\/标题/.test(text)
    && /作品描述|发布时间|发布设置/.test(text);
  const douyinConcreteUploadProgress =
    platform === "douyin"
    && /已上传：|当前速度：|剩余时间：|\b\d{1,3}%\b|正在上传|视频处理中|处理中\s*\d+%/.test(text);
  const bilibiliEditorSurface =
    platform === "bilibili"
    && /更换视频|上传完成|已经上传：/.test(text)
    && /标题|简介|分区|标签|创作声明|定时发布|立即投稿|存草稿/.test(text);
  const bilibiliConcreteUploadProgress =
    platform === "bilibili"
    && uploadBusyConcretePattern.test(text);
  const uploadBusy = uploadBusyPattern.test(text)
    && !(
      douyinStaticUploadReminder
      && douyinEditorSurface
      && !douyinConcreteUploadProgress
    )
    && !(
      bilibiliEditorSurface
      && !bilibiliConcreteUploadProgress
    );
  const uploadPromptOnly = uploadPromptOnlyPattern.test(text);
  const blockers = [];
  if (uploadFailed) {
    blockers.push({
      code: `${platform}_upload_failed`,
      message: "平台页面明确出现上传失败或无效视频提示。",
      lines: matchLines(uploadFailedPattern),
    });
  }
  if (platform === "bilibili" && bilibiliBatchDynamicPattern.test(text)) {
    blockers.push({
      code: "bilibili_batch_dynamic_interruption",
      message: "B站出现“批量上传将生成多条动态/使用不生成动态”阻断提示，需要先处理。",
      lines: matchLines(bilibiliBatchDynamicPattern),
    });
  }
  return {
    upload_failed: uploadFailed,
    upload_busy: uploadBusy,
    upload_prompt_only: uploadPromptOnly,
    blockers,
  };
}

export function shouldAcceptCompositeUploadReadyState(platform, state = {}, readyStreak = 0, waitedMs = 0) {
  const snapshot = state && typeof state === "object" ? state : {};
  if (!snapshot.ready || snapshot.failed || snapshot.busy || snapshot.uploadPromptOnly) return false;
  if (platform === "douyin") {
    return readyStreak >= 2 && waitedMs >= 2500;
  }
  return true;
}

export function buildPendingUploadMaterialIntegrity(platform, readiness = {}, route = {}) {
  const state = readiness && typeof readiness === "object" ? readiness : {};
  const last = state.last && typeof state.last === "object" ? state.last : {};
  const lines = Array.isArray(last.lines) ? last.lines.slice(0, 120) : [];
  const ready = Boolean(state.ready);
  const failed = Boolean(state.failed);
  const busy = Boolean(last.busy);
  const mediaPresent = Boolean(last.mediaPresent);
  const uploadPromptOnly = Boolean(last.uploadPromptOnly);
  const fileInputCount = Number(last.fileInputCount || 0);
  const pendingReason = String(
    state.pending_reason
    || (shouldDeferYouTubeDraftResumeReupload(state) ? "draft_resume_pending" : ""),
  ).trim();
  const verificationState = failed ? "error" : ready ? "ready" : "not_ready";
  const verificationReason = pendingReason || (failed
    ? "upload_failed"
    : busy
      ? "upload_in_progress"
      : uploadPromptOnly
        ? "upload_prompt_only"
        : mediaPresent
          ? "media_present_not_ready"
          : "upload_not_ready");
  return {
    platform,
    verified: false,
    failures: [],
    verification_state: verificationState,
    verification_reason: verificationReason,
    fields: {
      upload_ready: {
        actual: ready ? "ready" : "not_ready",
        verified: ready && !failed,
      },
    },
    platform_extras: {
      route: {
        url: String(route.url || ""),
        title: String(route.title || ""),
      },
      receipt_like: false,
      relevant_lines: lines,
    },
    route_ready_state: {
      route_ready: ready,
      auth_required: false,
      text_ready: mediaPresent,
      input_ready: fileInputCount > 0,
      file_inputs_visible: fileInputCount,
      body_text_length: lines.join(" ").length,
    },
    upload_readiness: {
      ready,
      failed,
      waited_ms: Number(state.waited_ms || 0),
      ready_streak: Number(state.ready_streak || 0),
      busy,
      media_present: mediaPresent,
      upload_prompt_only: uploadPromptOnly,
      file_input_count: fileInputCount,
      last_lines: lines,
    },
  };
}

export function shouldDeferYouTubeDraftResumeReupload(readiness = {}) {
  const state = readiness && typeof readiness === "object" ? readiness : {};
  const last = state.last && typeof state.last === "object" ? state.last : {};
  if (String(last.platform || "").trim() !== "youtube") return false;
  if (state.ready || state.failed || last.busy) return false;
  if (!last.mediaPresent || last.uploadPromptOnly) return false;
  if (!last.youtubeUploadRoute || !last.youtubeChannelContentList || !last.youtubeDraftResumeAvailable) return false;
  const fileInputCount = Number(last.fileInputCount || 0);
  const totalFileInputCount = Number(last.totalFileInputCount || 0);
  return fileInputCount === 0 && totalFileInputCount > 0;
}

export function normalizeYouTubeDraftResumeHintText(value = "") {
  return String(value || "")
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[｜|:：!！,，.。?？'"\-—_()/\\[\]【】]/g, "")
    .trim();
}

export function matchesYouTubeDraftResumeHint(rowText = "", hints = []) {
  const normalizeHint = typeof normalizeYouTubeDraftResumeHintText === "function"
    ? normalizeYouTubeDraftResumeHintText
    : (value = "") => String(value || "")
      .toLowerCase()
      .replace(/\s+/g, "")
      .replace(/[｜|:：!！,，.。?？'"\-—_()/\\[\]【】]/g, "")
      .trim();
  const normalizedRow = normalizeHint(rowText);
  if (!normalizedRow) return false;
  const values = Array.isArray(hints) ? hints : [hints];
  return values
    .map((value) => normalizeHint(value))
    .filter(Boolean)
    .some((normalizedHint) => normalizedRow.includes(normalizedHint));
}

export function selectYouTubeDraftResumeEntryCandidate(candidates = []) {
  const items = Array.isArray(candidates) ? candidates : [];
  if (!items.length) return null;
  const normalized = items
    .map((item) => ({
      ...item,
      label: String(item?.label || "").trim(),
      row_text: String(item?.row_text || "").trim(),
      visible: item?.visible !== false,
      x: Number(item?.x || 0),
      y: Number(item?.y || 0),
      width: Number(item?.width || 0),
      height: Number(item?.height || 0),
    }))
    .filter((item) => item.visible && item.width > 0 && item.height > 0);
  if (!normalized.length) return null;
  const score = (item) => {
    let value = 0;
    if (/取消上传|继续上传|上传已中断|处理中/.test(item.row_text)) value += 40;
    if (/编辑草稿|edit draft/i.test(item.label)) value += 30;
    else if (/详细信息|details/i.test(item.label)) value += 18;
    else if (item.target_id === "video-title") value += 16;
    if (/button/i.test(item.tag || "")) value += 4;
    if (/ytcp-video-row|row|actions/.test(item.row_role || "")) value += 2;
    return value;
  };
  return normalized
    .map((item) => ({ item, score: score(item) }))
    .sort((left, right) => right.score - left.score || left.item.y - right.item.y)[0]?.item || null;
}

export function didYouTubeDraftResumeAdvanceState(before = {}, after = {}) {
  const previous = before && typeof before === "object" ? before : {};
  const next = after && typeof after === "object" ? after : {};
  const previousLast = previous.last && typeof previous.last === "object" ? previous.last : {};
  const nextLast = next.last && typeof next.last === "object" ? next.last : {};
  const previousHref = String(previousLast.href || "").trim();
  const nextHref = String(nextLast.href || "").trim();
  if (previousHref && nextHref && previousHref !== nextHref) return true;
  if (Boolean(previousLast.youtubeChannelContentList) && !Boolean(nextLast.youtubeChannelContentList)) return true;
  if (!Boolean(previousLast.youtubeHasEditorSurface) && Boolean(nextLast.youtubeHasEditorSurface) && !Boolean(nextLast.youtubeChannelContentList)) return true;
  if (Number(nextLast.fileInputCount || 0) > Number(previousLast.fileInputCount || 0)) return true;
  const previousLines = Array.isArray(previousLast.lines) ? previousLast.lines.join(" | ") : "";
  const nextLines = Array.isArray(nextLast.lines) ? nextLast.lines.join(" | ") : "";
  return Boolean(previousLines && nextLines && previousLines !== nextLines && !Boolean(nextLast.youtubeChannelContentList));
}

export function shouldFailYouTubeDraftResumeAsInert(before = {}, after = {}, action = {}) {
  const previous = before && typeof before === "object" ? before : {};
  const next = after && typeof after === "object" ? after : {};
  const previousLast = previous.last && typeof previous.last === "object" ? previous.last : {};
  const nextLast = next.last && typeof next.last === "object" ? next.last : {};
  if (String(nextLast.platform || "").trim() !== "youtube") return false;
  if (!Boolean(action?.clicked)) return false;
  if (next.ready || next.failed || Boolean(nextLast.busy)) return false;
  if (!Boolean(nextLast.mediaPresent) || Boolean(nextLast.uploadPromptOnly)) return false;
  if (!Boolean(nextLast.youtubeUploadRoute) || !Boolean(nextLast.youtubeChannelContentList) || !Boolean(nextLast.youtubeDraftResumeAvailable)) return false;
  if (Number(nextLast.fileInputCount || 0) > 0) return false;
  if (didYouTubeDraftResumeAdvanceState(previous, next)) return false;
  return Boolean(previousLast.youtubeDraftResumeAvailable || previousLast.youtubeChannelContentList);
}

export function buildCompositeUploadPendingProcessingEnvelope({
  platform,
  route = {},
  actions = [],
  content = {},
  interruptions = [],
  materialIntegrity = {},
  code = "",
  reason = "",
  blockerMessage = "",
  blockerDetails = "",
  prepublishOnlyCurrentPage = false,
  prepareOnlyCurrentPage = false,
  stopBeforeFinalPublish = false,
}) {
  const normalizedPlatform = String(platform || "").trim();
  const normalizedCode = String(code || `${normalizedPlatform}_pre_publish_upload_pending`).trim();
  const normalizedRoute = {
    url: String(route?.url || ""),
    title: String(route?.title || ""),
  };
  const remaining = Array.isArray(materialIntegrity?.failures) && materialIntegrity.failures.length
    ? materialIntegrity.failures.map((item) => String(item || "").trim()).filter(Boolean)
    : ["upload_ready"];
  return _attach_publication_content_signature({
    platform: normalizedPlatform,
    route: normalizedRoute,
    actions,
    publication_audit: {},
    publication_field_snapshot: {},
    final_publish: {
      pre_publish_pending: true,
      wait_for_upload_ready: true,
      prepublish_only_current_page: Boolean(prepublishOnlyCurrentPage),
      prepare_only_current_page: Boolean(prepareOnlyCurrentPage),
      stop_before_final_publish: Boolean(stopBeforeFinalPublish),
    },
    material_integrity: materialIntegrity,
    ..._build_publication_recovery_hint({
      platform: normalizedPlatform,
      code: normalizedCode,
      reason: String(reason || "媒体上传已开始，继续保留现场等待平台进入可编辑上传态。").trim(),
      route: normalizedRoute,
      actionHistory: Array.isArray(actions) ? actions.slice(0, 80) : [],
      visibleLines: Array.isArray(materialIntegrity?.platform_extras?.relevant_lines)
        ? materialIntegrity.platform_extras.relevant_lines.slice(0, 120)
        : [],
      clearDraftContext: false,
      forceRefresh: true,
      blockers: [{
        code: normalizedCode,
        message: String(blockerMessage || `预发布等待上传完成：${remaining.join(",") || "upload_ready"}`).trim(),
        details: String(blockerDetails || `post_upload_wait_only=${remaining.join(",") || "upload_ready"}`).trim(),
      }],
      recoveryOverrides: {
        recovery_mode: "prepublish_resume",
        clear_draft_context: false,
        force_publish_page_refresh: true,
        verify_media_upload: true,
        wait_for_publish_confirmation: true,
        prepublish_only_current_page: Boolean(prepublishOnlyCurrentPage),
        prepare_only_current_page: Boolean(prepareOnlyCurrentPage),
      },
    }).recovery,
    interruptions,
  }, content);
}

export function normalizeCompositeUploadReadyResult(result = {}) {
  const envelope = result && typeof result === "object" ? result : {};
  const readiness = envelope.readiness && typeof envelope.readiness === "object"
    ? envelope.readiness
    : {};
  const actions = Array.isArray(envelope.actions) ? envelope.actions : [];
  return {
    actions,
    readiness,
  };
}

export function deriveCompositeUploadReadinessFailureState(platform, readiness = {}, options = {}) {
  const state = readiness && typeof readiness === "object" ? readiness : {};
  const last = state.last && typeof state.last === "object" ? state.last : {};
  const syntheticUploadExpected = Boolean(options?.syntheticUploadExpected);
  const waitedMs = Number(state.waited_ms || 0);
  if (state.failed) {
    return {
      failed: true,
      reason: String(state.failure_reason || "upload_failed").trim() || "upload_failed",
    };
  }
  if (
    syntheticUploadExpected
    && waitedMs >= 15000
    && !last.busy
    && !last.mediaPresent
    && last.uploadPromptOnly
  ) {
    return {
      failed: true,
      reason: "upload_not_applied",
    };
  }
  if (
    syntheticUploadExpected
    && String(platform || "").trim() === "youtube"
    && waitedMs >= 15000
    && !last.busy
    && !last.mediaPresent
    && Boolean(last.youtubeUploadRoute)
    && Boolean(last.youtubeChannelContentList)
    && (
      Boolean(last.youtubeUploadDialogRoute)
      || Number(last.totalFileInputCount || 0) > 0
    )
  ) {
    return {
      failed: true,
      reason: "upload_not_applied",
    };
  }
  return {
    failed: false,
    reason: "",
  };
}

export function shouldDeferYoutubeDraftResumeReupload(readiness = {}) {
  const state = readiness && typeof readiness === "object" ? readiness : {};
  const last = state.last && typeof state.last === "object" ? state.last : {};
  if (String(last.platform || "").trim() !== "youtube") return false;
  if (state.ready || state.failed || last.busy) return false;
  if (!last.mediaPresent || last.uploadPromptOnly) return false;
  if (!last.youtubeUploadRoute || !last.youtubeChannelContentList || !last.youtubeDraftResumeAvailable) return false;
  if (Number(last.fileInputCount || 0) !== 0) return false;
  if (Number(last.totalFileInputCount || 0) <= 0) return false;
  return true;
}

export function deriveCompositeMediaUploadFailureDisposition(platform, upload = {}, options = {}) {
  const failureReason = String(upload?.reason || "").trim();
  const stopBeforeFinalPublish = Boolean(options?.stopBeforeFinalPublish);
  const uploadNotApplied = stopBeforeFinalPublish && ["no_file_input", "no_video_file_input"].includes(failureReason);
  return {
    code: `${platform}_media_upload_failed`,
    message: uploadNotApplied
      ? "未能打开可用的视频上传输入面，已保留现场等待后续复核。"
      : "未能将视频素材重新挂载到发布页，已阻断后续填充与发布。",
    clear_draft_context: uploadNotApplied ? false : true,
    force_publish_page_refresh: true,
    recovery_overrides: uploadNotApplied
      ? buildStopBeforeFinalPublishRecoveryOverrides({
          prepublishOnlyCurrentPage: Boolean(options?.prepublishOnlyCurrentPage),
          prepareOnlyCurrentPage: Boolean(options?.prepareOnlyCurrentPage),
        })
      : null,
    blocker_details: {
      reason: failureReason,
      failure_reason: uploadNotApplied ? "upload_not_applied" : failureReason,
      fileInputs: Array.isArray(upload?.fileInputs) ? upload.fileInputs : [],
    },
    error_details: {
      reason: failureReason,
      failure_reason: uploadNotApplied ? "upload_not_applied" : failureReason,
      fileInputs: Array.isArray(upload?.fileInputs) ? upload.fileInputs : [],
    },
  };
}

export function deriveCompositeUploadReadinessBlockerDisposition(platform, blocker = {}, options = {}) {
  const failureReason = String(blocker?.pending_reason || "").trim();
  const stopBeforeFinalPublish = Boolean(options?.stopBeforeFinalPublish);
  const blockers = Array.isArray(blocker?.blockers)
    ? blocker.blockers.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const uploadNotApplied = stopBeforeFinalPublish && failureReason === "draft_resume_inert";
  return {
    code: uploadNotApplied ? `${platform}_media_upload_failed` : `${platform}_composite_upload_not_ready`,
    message: uploadNotApplied
      ? "已检测到平台草稿恢复入口未真正推进到上传编辑态，已保留现场等待后续复核。"
      : "复合适配器上传就绪检查失败，已阻止继续发布以避免错误回填草稿。",
    clear_draft_context: uploadNotApplied ? false : true,
    force_publish_page_refresh: true,
    recovery_overrides: uploadNotApplied
      ? buildStopBeforeFinalPublishRecoveryOverrides({
          prepublishOnlyCurrentPage: Boolean(options?.prepublishOnlyCurrentPage),
          prepareOnlyCurrentPage: Boolean(options?.prepareOnlyCurrentPage),
        })
      : null,
    blocker_details: {
      blockers,
      pending_reason: failureReason,
      media_name_hint: String(blocker?.media_name_hint || ""),
      media_present: Boolean(blocker?.media_present),
      upload_busy: Boolean(blocker?.upload_busy),
      upload_prompt_only: Boolean(blocker?.upload_prompt_only),
      line_samples: Array.isArray(blocker?.line_samples) ? blocker.line_samples : [],
      failure_reason: uploadNotApplied ? "upload_not_applied" : failureReason,
    },
    error_details: {
      blockers,
      pending_reason: failureReason,
      media_name_hint: String(blocker?.media_name_hint || ""),
      media_present: Boolean(blocker?.media_present),
      upload_busy: Boolean(blocker?.upload_busy),
      upload_prompt_only: Boolean(blocker?.upload_prompt_only),
      line_samples: Array.isArray(blocker?.line_samples) ? blocker.line_samples : [],
      failure_reason: uploadNotApplied ? "upload_not_applied" : failureReason,
    },
  };
}

export function resolveDouyinDeclarationOption(declaration = "") {
  const text = String(declaration || "").trim();
  if (!text) return "无需添加自主声明";
  if (/AI|人工智能|生成/i.test(text)) return "内容由AI生成";
  if (/营销|推广|广告/i.test(text)) return "内容含营销推广信息";
  if (/转载|转发|引用/i.test(text)) return "内容为转载信息";
  if (/观点|见解|测评|评测/i.test(text)) return "内容为个人观点或见解";
  if (/虚构|演绎|娱乐/i.test(text)) return "虚构演绎，仅供娱乐";
  return "无需添加自主声明";
}

export function extractCompositeDeclarationText(content = {}) {
  return String(
    content?.declaration
    || content?.content_declaration
    || content?.copy_material?.declaration
    || content?.platform_specific_overrides?.declaration
    || "",
  ).trim();
}

export function expectedCompositeDeclaration(content = {}, platform = "") {
  const rawDeclaration = extractCompositeDeclarationText(content);
  return String(
    platform === "douyin"
      ? resolveDouyinDeclarationOption(rawDeclaration || compositePlatformDefaultDeclaration(platform))
      : rawDeclaration || compositePlatformDefaultDeclaration(platform),
  ).trim();
}

export function verifyCompositeDeclarationField(
  platform,
  expectedDeclaration,
  declarationActual = "",
  textHaystack = "",
  options = {},
) {
  const expected = String(expectedDeclaration || "").replace(/\s+/g, " ").trim();
  const actual = String(declarationActual || "").replace(/\s+/g, " ").trim();
  const text = String(textHaystack || "");
  const declarationMissingPrompt = Boolean(options?.declarationMissingPrompt);
  const hasTitleOrBody = Boolean(options?.hasTitleOrBody);
  if (platform === "douyin") {
    if (declarationMissingPrompt) return false;
    const placeholderVisible = /请选择自主声明|请选择声明类型/.test(text) || /请选择自主声明|请选择声明类型/.test(actual);
    if (!expected) return !placeholderVisible;
    if (actual && (actual === expected || actual.includes(expected) || expected.includes(actual))) return true;
    if (placeholderVisible) return false;
    return text.includes(expected);
  }
  if (platform === "xiaohongshu") {
    if (declarationMissingPrompt) return false;
    if (!expected) return /原创声明|声明原创|原创/.test(text) || !hasTitleOrBody;
    if (actual && (actual === expected || actual.includes(expected) || expected.includes(actual))) return true;
    return text.includes(expected);
  }
  return platform === "bilibili"
    ? (/内容无需标注|原创声明|声明/.test(text) || Boolean(actual) || !hasTitleOrBody) && !declarationMissingPrompt
    : platform === "xiaohongshu" ? /原创声明|声明原创|原创/.test(text)
    : platform === "kuaishou" ? /原创|作者声明|声明/.test(text)
    : platform === "toutiao" ? /原创|声明|权益/.test(text)
    : platform === "wechat-channels" ? /声明原创|原创|声明/.test(text)
    : true;
}

export function deriveXiaohongshuSelectedCollectionActual(expectedCollection = "", textHaystack = "") {
  const expected = String(expectedCollection || "").replace(/\s+/g, " ").trim();
  const text = String(textHaystack || "").replace(/\s+/g, " ").trim();
  if (!expected || !text) return "";
  return text.includes(expected) ? expected : "";
}

export function deriveXiaohongshuDeclarationActual(expectedDeclaration = "", textHaystack = "") {
  const expected = String(expectedDeclaration || "").replace(/\s+/g, " ").trim();
  const text = String(textHaystack || "").replace(/\s+/g, " ").trim();
  if (expected && text.includes(expected)) return expected;
  if (!expected && /原创声明|声明原创|原创/.test(text)) return "原创声明";
  return "";
}

export function deriveXiaohongshuCoverActual(
  expectedCoverPath = "",
  textHaystack = "",
  imageSources = [],
  backgroundSources = [],
  customCoverPreview = false,
) {
  const expectedCoverBase = String(expectedCoverPath || "").split(/[\\/]/).pop() || "";
  if (!expectedCoverBase && !customCoverPreview) return "";
  const imageList = Array.isArray(imageSources) ? imageSources : [];
  const backgroundList = Array.isArray(backgroundSources) ? backgroundSources : [];
  if (expectedCoverBase && imageList.some((src) => String(src || "").includes(expectedCoverBase))) return expectedCoverBase;
  if (expectedCoverBase && backgroundList.some((src) => String(src || "").includes(expectedCoverBase))) return expectedCoverBase;
  if (customCoverPreview && (/封面效果评估通过|重新设置封面|上传成功/.test(String(textHaystack || "")) || expectedCoverBase)) {
    return expectedCoverBase || "custom_cover_preview";
  }
  return "";
}

function normalizeProfilePath(value) {
  const text = String(value || "").trim().replace(/\\/g, "/");
  if (!text) return "";
  return text.replace(/\/+/g, "/").replace(/\/$/, "");
}

function buildBrowserProfileId(browser, userDataDir, profileDirectory) {
  const normalizedBrowser = String(browser || "").trim().toLowerCase().replace(/ /g, "-").replace(/_/g, "-");
  const normalizedUserDataDir = normalizeProfilePath(userDataDir).toLowerCase();
  const normalizedProfileDirectory = String(profileDirectory || "").trim().toLowerCase();
  if (!normalizedBrowser || !normalizedUserDataDir || !normalizedProfileDirectory) return "";
  const digest = createHash("sha1")
    .update([normalizedBrowser, normalizedUserDataDir, normalizedProfileDirectory].join("\n"), "utf8")
    .digest("hex")
    .slice(0, 20);
  return `browser-profile:${normalizedBrowser}:${digest}`;
}

const ATTACHED_PROFILE_ID = buildBrowserProfileId(
  ATTACHED_BROWSER,
  ATTACHED_USER_DATA_DIR,
  ATTACHED_PROFILE_DIRECTORY,
);

const PLATFORM_DOMAINS = {
  douyin: ["creator.douyin.com", "creator-micro.douyin.com"],
  xiaohongshu: ["creator.xiaohongshu.com"],
  bilibili: ["member.bilibili.com", "member.bilibili.com/platform/upload"],
  kuaishou: ["cp.kuaishou.com", "cp.kuaishou.com/article/publish/video"],
  "wechat-channels": ["channels.weixin.qq.com"],
  toutiao: ["mp.toutiao.com/profile_v4/xigua/upload-video", "mp.toutiao.com/profile_v4/xigua/publish-video", "mp.toutiao.com"],
  youtube: ["studio.youtube.com"],
  x: ["x.com", "twitter.com"],
};

const PLATFORM_PUBLISH_ENTRY_URLS = {
  douyin: "https://creator.douyin.com/creator-micro/content/post/video",
  xiaohongshu: "https://creator.xiaohongshu.com/publish",
  bilibili: "https://member.bilibili.com/platform/upload/video",
  kuaishou: "https://cp.kuaishou.com/article/publish/video",
  "wechat-channels": "https://channels.weixin.qq.com/platform/post/create",
  toutiao: "https://mp.toutiao.com/profile_v4/xigua/upload-video?index=0",
  youtube: "https://studio.youtube.com/",
  x: "https://twitter.com/compose/tweet",
};

const PLATFORM_RECEIPT_ENTRY_URLS = {
  douyin: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
  xiaohongshu: "https://creator.xiaohongshu.com/new/note-manager",
  toutiao: "https://mp.toutiao.com/profile_v4/manage/content/all",
};

export function isCompositePublishRouteContext(platform, route = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const url = String(route?.url || "").trim();
  const lowerUrl = url.toLowerCase();
  const text = String(route?.text || "").replace(/\s+/g, " ").trim();
  const fileInputs = Array.isArray(route?.file_inputs) ? route.file_inputs : [];
  if (!url && !text) return false;
  if (normalizedPlatform === "douyin") {
    if (/creator\.douyin\.com\/creator-micro\/content\/manage/i.test(url)) return false;
    const loginSurfaceHints = /扫码登录|验证码登录|登录\/注册|我是创作者|我是mcn机构|创作者登录|抖音创作者中心是抖音创作者的一站式服务平台/i.test(text);
    if (loginSurfaceHints) return false;
    const publishSurfaceReady =
      (/作品描述|设置封面|自主声明|添加合集|谁可以看|发布时间|定时发布/.test(text)
        && !/作品管理|全部作品|已发布|审核中|未通过|共\s*\d+\s*个作品/.test(text))
      || fileInputs.some((input) => /video|mp4/i.test(String(input?.accept || "")));
    return publishSurfaceReady;
  }
  if (normalizedPlatform === "toutiao") {
    return /mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/i.test(url)
      || (/点击上传|发布视频/.test(text) && fileInputs.some((input) => /video|mp4/i.test(String(input?.accept || ""))));
  }
  if (normalizedPlatform === "bilibili") {
    if (/member\.bilibili\.com\/platform\/upload-manager\/article/i.test(url)) return false;
    const publishUrlReady = /member\.bilibili\.com\/platform\/upload\/video/i.test(url);
    const publishSurfaceReady =
      (/投稿|标题|简介|分区|合集|创作声明|封面|标签|定时/.test(text)
        && !/稿件管理|全部稿件|草稿|已通过|未通过|视频管理|图文管理/.test(text))
      || fileInputs.some((input) => /video|mp4/i.test(String(input?.accept || "")));
    return publishUrlReady || publishSurfaceReady;
  }
  if (normalizedPlatform === "xiaohongshu") {
    if (/creator\.xiaohongshu\.com\/(?:new\/note-manager|publish\/success)/i.test(url)) return false;
    const publishUrlReady = /creator\.xiaohongshu\.com\/publish(?:\/publish)?/i.test(url);
    const publishSurfaceReady = isXiaohongshuPublishEditorSurfaceReady({
      url,
      lines: text ? text.split(/\s+/) : [],
      headings: [],
      fileInputs,
    }) || isXiaohongshuVideoUploadEntrySurface(url, text);
    return publishUrlReady || publishSurfaceReady;
  }
  if (normalizedPlatform === "x") {
    return /x\.com\/compose\/(?:tweet|post)|twitter\.com\/compose\/(?:tweet|post)/i.test(url);
  }
  if (normalizedPlatform === "youtube") {
    const youtubeEditorUrlReady = /studio\.youtube\.com\/video\/[A-Za-z0-9_-]+\/edit/i.test(url);
    const youtubeUploadUrlReady = /studio\.youtube\.com\/channel\/[^/?#]+\/(?:videos\/)?upload/i.test(url);
    const youtubeEditorSurfaceReady =
      (/视频详细信息|Video details/i.test(text) && /标题（必填）|说明|缩略图|播放列表|观众|视频链接/.test(text))
      || fileInputs.some((input) => /video|mp4/i.test(String(input?.accept || "")));
    const youtubeUploadSurfaceReady =
      (/上传视频|Select files|选择文件|将要上传的视频文件拖放到此处|频道内容/.test(text)
        && !/糟糕，出了点问题|something went wrong/i.test(text));
    return youtubeEditorUrlReady || youtubeUploadUrlReady || youtubeEditorSurfaceReady || youtubeUploadSurfaceReady;
  }
  return /upload|publish|compose|post|studio|creator/.test(lowerUrl);
}

function _normalize_recovery_mode(value) {
  return String(value || "").trim().toLowerCase();
}

function _coerceRecoveryBool(value, fallback = false) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const text = String(value || "").trim().toLowerCase();
  if (!text) return fallback;
  if (["1", "true", "yes", "y", "on", "enable", "enabled"].includes(text)) return true;
  if (["0", "false", "no", "n", "off", "disable", "disabled"].includes(text)) return false;
  return fallback;
}

function _coerceRecoveryTimeoutMs(value, fallback = 0) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) return fallback;
  const minMs = 15000;
  const maxMs = 180000;
  return Math.max(minMs, Math.min(maxMs, Math.floor(parsed)));
}

function _extract_publication_recovery_context(value) {
  const raw = value && typeof value === "object" ? value : {};
  const overrides = raw.platform_specific_overrides && typeof raw.platform_specific_overrides === "object"
    ? raw.platform_specific_overrides
    : {};
  const recoveryState = raw.publication_recovery_state && typeof raw.publication_recovery_state === "object"
    ? raw.publication_recovery_state
    : {};
  const recoveryPlan = recoveryState.recovery_plan && typeof recoveryState.recovery_plan === "object"
    ? recoveryState.recovery_plan
    : {};
  const directStateOverrides = recoveryState.recovery_overrides && typeof recoveryState.recovery_overrides === "object"
    ? recoveryState.recovery_overrides
    : {};
  const stateOverrides = recoveryPlan.recovery_overrides && typeof recoveryPlan.recovery_overrides === "object"
    ? recoveryPlan.recovery_overrides
    : {};
  const recoveryOverrides = { ...directStateOverrides, ...stateOverrides, ...overrides };
  const nextPlatformOverrides = (recoveryOverrides.next_platform_specific_overrides && typeof recoveryOverrides.next_platform_specific_overrides === "object")
    ? recoveryOverrides.next_platform_specific_overrides
    : {};
  const targetAdapter = String(raw.target_adapter || recoveryState.target_adapter || recoveryPlan.target_adapter || "").trim();
  const targetExecutionMode = String(raw.target_execution_mode || recoveryState.target_execution_mode || recoveryPlan.target_execution_mode || "").trim();
  const rawTargetPlatformOverrides =
    recoveryPlan.target_platform_specific_overrides && typeof recoveryPlan.target_platform_specific_overrides === "object"
      ? recoveryPlan.target_platform_specific_overrides
      : (raw.target_platform_specific_overrides && typeof raw.target_platform_specific_overrides === "object"
        ? raw.target_platform_specific_overrides
        : {});
  const normalizedTargetPlatformOverrides = Object.fromEntries(
    Object.entries(rawTargetPlatformOverrides).filter(
      ([key, value]) => key && ["string", "number", "boolean"].includes(typeof value),
    ),
  );
  const mergedOverrides = { ...recoveryOverrides, ...nextPlatformOverrides };
  const mode = _normalize_recovery_mode(recoveryOverrides.recovery_mode || stateOverrides.recovery_mode || directStateOverrides.recovery_mode);
  return {
    clear_draft_context: Boolean(mergedOverrides.clear_draft_context) || ["draft_reset", "clear_draft"].includes(mode),
    force_publish_page_refresh: Boolean(mergedOverrides.force_publish_page_refresh),
    verification_only_current_page: _coerceRecoveryBool(
      mergedOverrides.verification_only_current_page,
      false,
    ),
    repair_only_current_page: _coerceRecoveryBool(
      mergedOverrides.repair_only_current_page,
      false,
    ),
    prepublish_only_current_page: _coerceRecoveryBool(
      mergedOverrides.prepublish_only_current_page,
      false,
    ),
    prepare_only_current_page: _coerceRecoveryBool(
      mergedOverrides.prepare_only_current_page,
      false,
    ),
    verify_media_upload: _coerceRecoveryBool(
      mergedOverrides.verify_media_upload,
      Boolean(mergedOverrides.wait_for_publish_confirmation || mode === "auto_recover"),
    ),
    wait_for_publish_confirmation: _coerceRecoveryBool(
      mergedOverrides.wait_for_publish_confirmation,
      ["draft_reset", "content_plan", "auto_recover"].includes(mode),
    ),
    capture_response_timeout_ms: _coerceRecoveryTimeoutMs(
      mergedOverrides.capture_response_timeout_ms,
      _coerceRecoveryTimeoutMs(recoveryPlan.capture_response_timeout_ms, 65000),
    ),
    recovery_mode: mode,
    next_platform_specific_overrides: nextPlatformOverrides,
    target_adapter: targetAdapter,
    target_execution_mode: targetExecutionMode,
    target_platform_specific_overrides: normalizedTargetPlatformOverrides,
    source: raw.publication_recovery_state ? "publication_recovery_state" : "platform_specific_overrides",
    latest_failure_signature: String(recoveryState.latest_failure_signature || "").trim(),
    latest_retry_count: Number.isFinite(Number(recoveryState.latest_retry_count)) ? Number(recoveryState.latest_retry_count) : 0,
  };
}

export function derivePublicationTaskPreparationPolicy(content) {
  const recoveryContext = _extract_publication_recovery_context(content);
  const forceClearDraft = Boolean(recoveryContext.clear_draft_context);
  const forcePublishPageRefresh = Boolean(recoveryContext.force_publish_page_refresh);
  const verificationOnlyCurrentPage = Boolean(recoveryContext.verification_only_current_page);
  const repairOnlyCurrentPage = Boolean(recoveryContext.repair_only_current_page);
  const prepublishOnlyCurrentPage = Boolean(recoveryContext.prepublish_only_current_page);
  const prepareOnlyCurrentPage = Boolean(recoveryContext.prepare_only_current_page);
  const currentPageOnlyMode = verificationOnlyCurrentPage || repairOnlyCurrentPage;
  const stopBeforeFinalPublish = prepublishOnlyCurrentPage || prepareOnlyCurrentPage;
  const currentPageSafeMode = currentPageOnlyMode || stopBeforeFinalPublish;
  return {
    recoveryContext,
    forceClearDraft,
    forcePublishPageRefresh,
    verificationOnlyCurrentPage,
    repairOnlyCurrentPage,
    prepublishOnlyCurrentPage,
    prepareOnlyCurrentPage,
    stopBeforeFinalPublish,
    forceMediaUpload: Boolean(!currentPageSafeMode && (forceClearDraft || forcePublishPageRefresh)),
    clearIfStaleDraft: !forceClearDraft && !currentPageSafeMode,
  };
}

export function buildPreparationBootstrapRecoveryOverrides(preparationPolicy = {}) {
  const policy = preparationPolicy && typeof preparationPolicy === "object" ? preparationPolicy : {};
  const recoveryContext = policy.recoveryContext && typeof policy.recoveryContext === "object"
    ? policy.recoveryContext
    : {};
  return {
    recovery_mode: recoveryContext.recovery_mode || "auto_recover",
    verification_only_current_page: policy.verificationOnlyCurrentPage,
    repair_only_current_page: policy.repairOnlyCurrentPage,
    prepublish_only_current_page: policy.prepublishOnlyCurrentPage,
    prepare_only_current_page: policy.prepareOnlyCurrentPage,
    verify_media_upload: recoveryContext.verify_media_upload,
    wait_for_publish_confirmation: recoveryContext.wait_for_publish_confirmation,
    force_publish_page_refresh: Boolean(policy.forcePublishPageRefresh),
    clear_draft_context: false,
  };
}

export function buildPreparationBootstrapTimeoutOutcome({
  platform = "",
  code = "platform_route_bootstrap_timeout",
  reason = "",
  route = {},
  actions = [],
  preparationPolicy = {},
  content = {},
  details = {},
} = {}) {
  const recoveryOverrides = buildPreparationBootstrapRecoveryOverrides(preparationPolicy);
  const normalizedPlatform = normalizePlatform(platform);
  return _attach_publication_signature_to_task_result({
    status: "needs_human",
    result: _attach_publication_content_signature({
      platform: normalizedPlatform,
      route: route && typeof route === "object" ? route : {},
      actions: Array.isArray(actions) ? actions : [],
      ..._build_publication_recovery_hint({
        platform: normalizedPlatform,
        code,
        reason,
        route: route && typeof route === "object" ? route : {},
        actionHistory: Array.isArray(actions) ? actions : [],
        clearDraftContext: false,
        forceRefresh: Boolean(recoveryOverrides.force_publish_page_refresh),
        recoveryOverrides,
        blockers: [{
          code,
          message: reason,
          details: JSON.stringify(details && typeof details === "object" ? details : {}),
        }],
      }).recovery,
    }, content),
    error: {
      code,
      message: reason,
      details: details && typeof details === "object" ? details : {},
    },
  }, content);
}

export function shouldApplyCompositeDraftPolicyBlockers(preparationPolicy = {}) {
  const policy = preparationPolicy && typeof preparationPolicy === "object" ? preparationPolicy : {};
  const recoveryMode = _normalize_recovery_mode(policy?.recoveryContext?.recovery_mode);
  if (Boolean(policy.verificationOnlyCurrentPage) && recoveryMode === "receipt_rebind") {
    return false;
  }
  return true;
}

export function shouldBlockOnDraftClearFailure(preparationPolicy, clearAction) {
  const policy = preparationPolicy && typeof preparationPolicy === "object" ? preparationPolicy : {};
  const action = clearAction && typeof clearAction === "object" ? clearAction : {};
  if (!action.attempted || action.cleared) return false;
  if (!Boolean(policy.forceClearDraft)) return false;
  const hasStaleEvidence = Boolean(
    action.stale_detected
      || action.before_media_hint
      || action.after_media_hint
      || action.before_draft_hint
      || action.after_draft_hint
      || action.error
  );
  return hasStaleEvidence;
}

export function shouldBlockOnDraftResumePromptFailure(preparationPolicy, resumeAction) {
  const policy = preparationPolicy && typeof preparationPolicy === "object" ? preparationPolicy : {};
  const action = resumeAction && typeof resumeAction === "object" ? resumeAction : {};
  if (!action.prompt_present) return false;
  if (action.preferred_action !== "discard") return false;
  if (!policy.forceClearDraft && !policy.clearIfStaleDraft) return false;
  if (!action.attempted) return true;
  if (!action.clicked_label) return true;
  if (action.prompt_still_open) return true;
  return action.discarded !== true;
}

export function derivePublicationTaskTimeoutStatus(taskLike) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : {};
  const taskRecoveryContext = task.recovery_context && typeof task.recovery_context === "object"
    ? task.recovery_context
    : null;
  const content = task.content && typeof task.content === "object" ? task.content : {};
  const recoveryContext = taskRecoveryContext || _extract_publication_recovery_context(content);
  if (recoveryContext.wait_for_publish_confirmation) {
    return "submitted";
  }
  return "needs_human";
}

export function reconcileTimedOutPublicationTask(taskLike, outcomeLike) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : null;
  if (!task || !task.timeout_pending) return false;
  const outcome = outcomeLike && typeof outcomeLike === "object" ? outcomeLike : {};
  task.status = String(outcome.status || task.status || "needs_human");
  task.result = outcome.result && typeof outcome.result === "object" ? outcome.result : {};
  task.error = outcome.error || null;
  task.timeout_pending = false;
  task.updated_at = new Date().toISOString();
  schedulePublicationTaskReconcileCallback(task);
  return true;
}

const ACTIVE_PUBLICATION_TASK_STATUSES = new Set(["queued", "processing", "submitted"]);
const PUBLICATION_RECONCILE_CALLBACK_TIMEOUT_MS = 15000;

function publicationTaskReconcileCallbackUrl(taskLike) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : {};
  return String(task.reconcile_callback_url || "").trim();
}

export function shouldDispatchPublicationTaskReconcileCallback(taskLike) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : {};
  if (task.timeout_pending) return false;
  const callbackUrl = publicationTaskReconcileCallbackUrl(task);
  if (!callbackUrl) return false;
  const status = String(task.status || "").trim().toLowerCase();
  if (!status || ACTIVE_PUBLICATION_TASK_STATUSES.has(status)) return false;
  return true;
}

export async function dispatchPublicationTaskReconcileCallback(taskLike, options = {}) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : null;
  if (!task) return { dispatched: false, reason: "task_missing" };
  if (!shouldDispatchPublicationTaskReconcileCallback(task)) {
    return { dispatched: false, reason: "not_applicable" };
  }
  const fetchImpl = typeof options.fetchImpl === "function" ? options.fetchImpl : globalThis.fetch;
  if (typeof fetchImpl !== "function") {
    return { dispatched: false, reason: "fetch_unavailable" };
  }
  const callbackUrl = publicationTaskReconcileCallbackUrl(task);
  const serializedTask = serializeTask(task);
  const callbackState = task.reconcile_callback_state && typeof task.reconcile_callback_state === "object"
    ? task.reconcile_callback_state
    : {};
  task.reconcile_callback_state = callbackState;
  const signature = `${serializedTask.status}:${serializedTask.updated_at}`;
  if (callbackState.pending_signature === signature || callbackState.last_signature === signature) {
    return { dispatched: false, reason: "duplicate" };
  }
  callbackState.pending_signature = signature;
  callbackState.last_attempt_at = new Date().toISOString();
  callbackState.last_error = "";
  const timeoutMs = Number.isFinite(options.timeoutMs) && options.timeoutMs > 0
    ? Math.max(1000, Number(options.timeoutMs))
    : PUBLICATION_RECONCILE_CALLBACK_TIMEOUT_MS;
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  const timeoutHandle = controller
    ? setTimeout(() => controller.abort(new Error(`publication reconcile callback timeout after ${timeoutMs}ms`)), timeoutMs)
    : null;
  try {
    const response = await fetchImpl(callbackUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({ task: serializedTask }),
      signal: controller ? controller.signal : undefined,
    });
    const responseText = await response.text();
    callbackState.last_signature = signature;
    callbackState.last_status = serializedTask.status;
    callbackState.last_http_status = Number(response.status || 0);
    callbackState.last_response_excerpt = String(responseText || "").slice(0, 1000);
    callbackState.last_error = response.ok ? "" : `http_${response.status}`;
    return {
      dispatched: true,
      ok: Boolean(response.ok),
      http_status: Number(response.status || 0),
    };
  } catch (error) {
    callbackState.last_error = String(error?.message || error || "publication_reconcile_callback_failed");
    return {
      dispatched: false,
      reason: "request_failed",
      error: callbackState.last_error,
    };
  } finally {
    if (timeoutHandle) clearTimeout(timeoutHandle);
    if (callbackState.pending_signature === signature) callbackState.pending_signature = "";
  }
}

export function schedulePublicationTaskReconcileCallback(taskLike, options = {}) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : null;
  if (!task) return false;
  if (!shouldDispatchPublicationTaskReconcileCallback(task)) return false;
  queueMicrotask(() => {
    void dispatchPublicationTaskReconcileCallback(task, options);
  });
  return true;
}

export function derivePublicationTaskExecutionTimeoutMs(taskLike) {
  const task = taskLike && typeof taskLike === "object" ? taskLike : {};
  const content = task.content && typeof task.content === "object" ? task.content : {};
  const taskRecoveryContext = task.recovery_context && typeof task.recovery_context === "object"
    ? task.recovery_context
    : null;
  const recoveryContext = taskRecoveryContext || _extract_publication_recovery_context(content);
  const explicitTimeout = _coerceRecoveryTimeoutMs(
    task.task_execution_timeout_ms,
    _coerceRecoveryTimeoutMs(
      content.task_execution_timeout_ms,
      _coerceRecoveryTimeoutMs(
        content.platform_specific_overrides && typeof content.platform_specific_overrides === "object"
          ? content.platform_specific_overrides.task_execution_timeout_ms
          : 0,
        0,
      ),
    ),
  );
  if (explicitTimeout > 0) {
    return Math.max(60000, Math.min(PUBLICATION_TASK_TIMEOUT_MS, explicitTimeout));
  }
  const platform = normalizePlatform(task.platform || content.platform || "");
  const captureTimeout = _coerceRecoveryTimeoutMs(recoveryContext.capture_response_timeout_ms, 0);
  if (captureTimeout > 0) {
    const uploadTimeout = compositeUploadReadinessTimeoutMs(platform, captureTimeout);
    // Publish-confirmation flows include upload/fill/final-click work before the receipt wait starts.
    // A 60s fixed allowance is too tight for real creator pages like Douyin/Xiaohongshu.
    return Math.max(150000, Math.min(PUBLICATION_TASK_TIMEOUT_MS, uploadTimeout + 120000));
  }
  return Math.max(60000, PUBLICATION_TASK_TIMEOUT_MS);
}

export function shouldBlockOnMediaUploadFailure(upload) {
  return !(upload && upload.uploaded);
}

export function shouldTreatMediaUploadAsInProgress(platform, upload, snapshot, mediaPath = "") {
  if (upload && upload.uploaded) return true;
  if (!upload || String(upload.reason || "") !== "no_video_file_input") return false;
  const lines = Array.isArray(snapshot?.lines) ? snapshot.lines : [];
  const text = lines.join(" ");
  const signals = detectCompositePublicationSignals(platform, text, lines);
  return (
    pageAlreadyHasMedia(snapshot || {}, mediaPath)
    || Boolean(signals.upload_busy)
    || /已上传：|当前速度：|剩余时间：|上传中|正在上传|处理中\s*\d+%|检测中\s*\d+%|\b\d{1,3}%\b/.test(text)
  );
}

function _extract_publication_content_signature(content) {
  if (!content || typeof content !== "object") return "";
  const rawSignature = (
    content.publication_content_signature
    || content.publication_plan_signature
    || content.content_signature
  );
  if (!rawSignature) return "";
  if (typeof rawSignature === "string") return String(rawSignature).trim();
  if (typeof rawSignature === "object" && typeof rawSignature.value === "string") return String(rawSignature.value).trim();
  return "";
}

function _attach_publication_content_signature(result, content) {
  const signature = _extract_publication_content_signature(content);
  if (!signature) return result;
  return {
    ...result,
    content_signature: signature,
    publication_content_signature: signature,
    publication_plan_signature: signature,
  };
}

function _attach_publication_signature_to_task_result(taskResult, content) {
  if (!taskResult || typeof taskResult !== "object" || !taskResult.result || typeof taskResult.result !== "object") {
    return taskResult;
  }
  return {
    ...taskResult,
    result: _attach_publication_content_signature(taskResult.result, content),
  };
}

function _normalizeTaskIdentityField(value) {
  return String(value || "").trim();
}

export function extractPublicationTaskIdentity(payload = {}, contentOverride = null) {
  const rawPayload = payload && typeof payload === "object" ? payload : {};
  const content = contentOverride && typeof contentOverride === "object"
    ? contentOverride
    : (rawPayload.content && typeof rawPayload.content === "object" ? rawPayload.content : {});
  const recoveryState = content.publication_recovery_state && typeof content.publication_recovery_state === "object"
    ? content.publication_recovery_state
    : {};
  const recoveryOverrides = recoveryState.recovery_overrides && typeof recoveryState.recovery_overrides === "object"
    ? recoveryState.recovery_overrides
    : {};
  const attemptId = _normalizeTaskIdentityField(rawPayload.attempt_id || recoveryState.attempt_id);
  const contentId = _normalizeTaskIdentityField(
    rawPayload.content_id
    || rawPayload.job_id
    || recoveryState.content_id
    || recoveryState.job_id
  );
  const carryOverAttemptId = _normalizeTaskIdentityField(recoveryState.carry_over_from_attempt_id);
  const signature = _extract_publication_content_signature(content);
  const recoveryMode = _normalizeTaskIdentityField(rawPayload.recovery_mode || recoveryOverrides.recovery_mode);
  return {
    attempt_id: attemptId || null,
    content_id: contentId || null,
    carry_over_from_attempt_id: carryOverAttemptId || null,
    attempt_backed: Boolean(attemptId),
    content_signature: signature || null,
    publication_content_signature: signature || null,
    publication_plan_signature: signature || null,
    recovery_mode: recoveryMode || null,
  };
}

export function _build_publication_recovery_hint({
  platform,
  code,
  reason,
  route = {},
  actionHistory = [],
  visibleLines = [],
  clearDraftContext = false,
  forceRefresh = false,
  targetAdapter = "",
  targetExecutionMode = "",
  targetPlatformSpecificOverrides = {},
  duplicateDetected = false,
  duplicateMarker,
  blockers = [],
  recoveryOverrides = {},
}) {
  const rawRecoveryOverrides = recoveryOverrides && typeof recoveryOverrides === "object"
    ? recoveryOverrides
    : {};
  const recoveryHintOverrides = {
    recovery_mode: String(rawRecoveryOverrides.recovery_mode || "").trim() || "auto_recover",
    clear_draft_context: Boolean(clearDraftContext),
    force_publish_page_refresh: Boolean(forceRefresh),
  };
  for (const key of [
    "verification_only_current_page",
    "repair_only_current_page",
    "prepublish_only_current_page",
    "prepare_only_current_page",
    "verify_media_upload",
    "wait_for_publish_confirmation",
  ]) {
    if (key in rawRecoveryOverrides) {
      recoveryHintOverrides[key] = Boolean(rawRecoveryOverrides[key]);
    }
  }
  const normalizedRoute = {
    url: String(route.url || "").trim(),
    title: String(route.title || "").trim(),
    path: String(route.path || "").trim(),
  };
  const normalizedEvidence = {
    visible_lines: (Array.isArray(visibleLines) ? visibleLines : [])
      .slice(0, _RECOVERY_EVIDENCE_MAX_LINES)
      .map((item) => String(item || "").trim())
      .filter(Boolean),
    duplicate_marker: duplicateMarker ? String(duplicateMarker).trim() : "",
  };
  const normalizedTargetPlatformOverrides = targetPlatformSpecificOverrides && typeof targetPlatformSpecificOverrides === "object"
    ? targetPlatformSpecificOverrides
    : {};
  return {
    recovery: {
      code: String(code || "").trim(),
      reason: String(reason || "").trim(),
      duplicate_detected: Boolean(duplicateDetected),
      target_adapter: String(targetAdapter || "").trim(),
      target_execution_mode: String(targetExecutionMode || "").trim(),
      target_platform_specific_overrides: normalizedTargetPlatformOverrides,
      recovery_overrides: recoveryHintOverrides,
      blockers: blockers
        .map((item) => ({
          code: String(item?.code || "").trim(),
          message: String(item?.message || item || "").trim(),
          details: item && typeof item === "object" ? String(item.details || "").trim() : "",
        }))
        .filter((item) => item.code || item.message)
        .slice(0, 12),
      route: normalizedRoute,
      action_history: (Array.isArray(actionHistory) ? actionHistory : [])
        .slice(-24)
        .map((item) => {
          if (!item || typeof item !== "object") return String(item || "").trim();
          return {
            kind: String(item.kind || "action").trim(),
            clicked: Boolean(item.clicked),
            clicked_label: String(item.label || item.text || "").trim(),
            requested: String(item.requested || "").trim(),
            reason: String(item.reason || "").trim(),
            duration_ms: typeof item.receipt_wait === "number" ? item.receipt_wait : item.duration_ms,
          };
        })
        .filter((item) => item),
      evidence: normalizedEvidence,
      suggestion: {
        clear_draft_context: Boolean(clearDraftContext),
        force_publish_page_refresh: Boolean(forceRefresh),
      },
    },
  };
}

const PLATFORM_STEPS = {
  xiaohongshu: [
    "打开小红书创作服务平台发布笔记页",
    "上传视频和封面",
    "填写标题、正文、话题",
    "展开内容设置",
    "选择加入合集、原创声明、内容类型声明、群聊、地点/路线等可用选项",
    "设置定时或保存草稿，发布前再次验证控件",
  ],
  bilibili: [
    "打开 B站创作中心投稿页",
    "上传视频和封面",
    "填写标题、简介和标签",
    "选择分区，EDC/装备类优先从真实分区候选中评估户外潮流、数码、生活等选项",
    "选择合集/系列、声明与权益等更多设置",
    "设置定时或保存草稿，发布前再次验证控件",
  ],
  youtube: [
    "打开 YouTube Studio 上传或视频详情页",
    "上传视频和缩略图",
    "填写标题、说明、标签和播放列表",
    "确认是否面向儿童、可见性、评论限制和通知限制",
    "设置预约发布时间，发布前再次验证限制弹窗",
  ],
  douyin: [
    "打开抖音创作者中心发布视频页",
    "上传视频和封面",
    "填写标题/作品描述与话题",
    "选择合集、原创/声明、谁可以看、定时发布等真实可见选项",
    "发布前再次验证页面结构和字段变化",
  ],
};

const SAFE_DISMISS_TEXTS = [
  "知道了",
  "我知道了",
  "稍后再说",
  "暂不",
  "暂不开启",
  "以后再说",
  "屏蔽",
  "不允许",
  "拒绝",
  "关闭",
  "跳过",
  "Not now",
  "Maybe later",
  "Close",
  "Dismiss",
];

const DANGEROUS_ACTION_RE = /发布|投稿|提交|确定发布|立即投稿|发表|预定|预约发布|保存|删除|确认剪掉|Post$|Submit|Publish|Save|Delete/i;

const PLATFORM_DRAFT_CLEAR_TEXTS = {
  common: [
    ["清空", "清除", "重置", "放弃", "重选", "重新选择", "重新选取", "重新选择文件", "选择其他文件", "重新上传", "更换视频", "更换文件", "删除", "移除", "重填", "清空草稿", "清空内容"],
    ["编辑新稿", "重新编辑", "重发", "重新开始", "重试", "重试上传"],
    ["取消", "确定", "完成", "知道了", "我知道了"],
  ],
  bilibili: [
    ["重试", "删除并重传", "重传", "清除素材", "选择视频", "删除视频", "重选视频"],
    ["取消发布", "放弃", "回到编辑", "返回编辑"],
  ],
  kuaishou: [
    ["重新选择", "重选", "更换视频", "重新录制", "清空", "删除", "移除", "重试上传", "重新上传"],
    ["回到编辑", "重新编辑", "重置"],
  ],
  douyin: [
    ["删除", "清空", "重置", "重试上传", "重新上传", "编辑新作品", "重新选择", "重选"],
    ["放弃", "取消", "返回编辑", "返回首页", "返回"],
  ],
  xiaohongshu: [
    ["清空", "重置", "移除", "更换", "重选", "重新上传", "重选文件", "重新选择文件", "回到编辑", "编辑"],
  ],
  "wechat-channels": [
    ["清空", "重新上传", "重传", "更换", "移除", "删除", "重置", "回到编辑", "重新编辑"],
  ],
  toutiao: [
    ["清空", "重选", "重新上传", "更换", "移除", "删除", "重置", "重新编辑", "重新录制", "回到编辑"],
  ],
  youtube: [
    ["移除", "删除", "重选", "更换", "清除", "清空", "重新上传", "选择文件", "编辑视频", "重新编辑"],
  ],
  x: [
    ["清空", "删除", "移除", "编辑", "重新选择", "移除内容", "清除", "清除文本", "重试", "重试发布"],
  ],
};

const DRAFT_RESUME_DISMISS_TEXTS = [
  "不用了",
  "不需要",
  "放弃",
  "重新开始",
  "编辑新稿",
  "新建稿件",
  "重发新稿",
  "清空草稿",
  "取消",
];

function _platformDraftClearGroups(platform) {
  const normalized = normalizePlatform(platform);
  const groups = PLATFORM_DRAFT_CLEAR_TEXTS[normalized] || [];
  const merged = groups.length ? groups : PLATFORM_DRAFT_CLEAR_TEXTS.common;
  const common = PLATFORM_DRAFT_CLEAR_TEXTS.common || [];
  const fallback = merged === common ? [] : common;
  return [...merged, ...fallback].map((items) => [...new Set(items)]);
}

function buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness = {}) {
  const readiness = uploadReadiness || {};
  const last = readiness.last || {};
  const lines = Array.isArray(last.lines) ? last.lines : [];
  const blockers = [];
  const pendingReason = String(readiness.pending_reason || "").trim();
  if (Boolean(readiness.failed)) blockers.push("upload_failed");
  if (Boolean(last.busy)) blockers.push("upload_busy");
  if (Boolean(last.uploadPromptOnly)) blockers.push("upload_prompt_only");
  if (Boolean(last.mediaPresent) === false && Boolean(last.mediaName)) blockers.push("media_not_detected");
  return {
    kind: "composite_upload_readiness_blocked",
    platform,
    ready: Boolean(readiness.ready),
    ready_waited_ms: readiness.waited_ms || 0,
    blockers,
    pending_reason: pendingReason,
    media_name_hint: String(last.mediaName || ""),
    media_present: Boolean(last.mediaPresent),
    upload_busy: Boolean(last.busy),
    upload_prompt_only: Boolean(last.uploadPromptOnly),
    line_samples: lines.slice(0, 8),
  };
}

export function shouldTreatCompositeUploadReadinessBlockerAsPending(blocker = {}) {
  if (!blocker || typeof blocker !== "object") return false;
  const pendingReason = String(blocker.pending_reason || "").trim();
  if (pendingReason === "draft_resume_pending") return true;
  const blockers = Array.isArray(blocker.blockers)
    ? blocker.blockers.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  if (!blockers.length) return false;
  return blockers.every((item) => item === "upload_busy");
}

const BILIBILI_SECTION_TERMS = [
  "影视",
  "娱乐",
  "音乐",
  "舞蹈",
  "动画",
  "绘画",
  "鬼畜",
  "游戏",
  "资讯",
  "知识",
  "人工智能",
  "科技数码",
  "汽车",
  "时尚美妆",
  "家装房产",
  "户外潮流",
  "健身",
  "体育运动",
  "手工",
  "美食",
  "小剧场",
  "旅游出行",
  "三农",
  "动物",
  "亲子",
  "健康",
  "情感",
  "vlog",
  "生活兴趣",
  "生活经验",
];

function jsonResponse(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readRequestJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const text = Buffer.concat(chunks).toString("utf8").trim();
        resolve(text ? JSON.parse(text) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

export function coerceTaskContentWithRecoveryPayload(payload = {}) {
  const rawPayload = payload && typeof payload === "object" ? payload : {};
  const rawContent = rawPayload.content && typeof rawPayload.content === "object" ? rawPayload.content : {};
  const content = { ...rawContent };
  const topLevelRecoveryOverrides = rawPayload.recovery_overrides && typeof rawPayload.recovery_overrides === "object"
    ? rawPayload.recovery_overrides
    : null;
  if (!topLevelRecoveryOverrides) return content;
  const rawRecoveryState = content.publication_recovery_state && typeof content.publication_recovery_state === "object"
    ? content.publication_recovery_state
    : {};
  const stateOverrides = rawRecoveryState.recovery_overrides && typeof rawRecoveryState.recovery_overrides === "object"
    ? rawRecoveryState.recovery_overrides
    : {};
  content.publication_recovery_state = {
    ...rawRecoveryState,
    recovery_overrides: {
      ...topLevelRecoveryOverrides,
      ...stateOverrides,
    },
  };
  return content;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function fetchJsonWithMethod(url, method = "GET") {
  const response = await fetch(url, { method });
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}

async function listCdpTabs() {
  return fetchJson(`${CDP_URL}/json/list`);
}

async function createCdpTab(targetUrl) {
  const encoded = encodeURIComponent(String(targetUrl || "about:blank"));
  const created = await fetchJsonWithMethod(`${CDP_URL}/json/new?${encoded}`, "PUT");
  if (!created || !created.webSocketDebuggerUrl) {
    throw new Error(`创建 CDP Tab 失败：${targetUrl}`);
  }
  return created;
}

async function closeCdpTab(tabId) {
  const normalizedTabId = String(tabId || "").trim();
  if (!normalizedTabId) return { closed: false, reason: "missing_tab_id" };
  await fetchJson(`${CDP_URL}/json/close/${encodeURIComponent(normalizedTabId)}`);
  return { closed: true, tab_id: normalizedTabId };
}

async function resolvePlatformTab(platform, options = {}) {
  const normalized = normalizePlatform(platform);
  const actions = [];
  const forceFreshTab = Boolean(options.force_fresh_tab);
  const tabSelection = options.tab_selection && typeof options.tab_selection === "object"
    ? options.tab_selection
    : {};
  const allowTabAutocreate = ALLOW_PUBLICATION_TAB_AUTOCREATE || Boolean(tabSelection.allow_safe_autocreate);
  const receiptEntryUrl = tabSelection.prefer_receipt_surface
    ? String(PLATFORM_RECEIPT_ENTRY_URLS[normalized] || "").trim()
    : "";
  let tabs = await listCdpTabs();
  const entryUrl = receiptEntryUrl || resolvePlatformPublishEntryUrl(normalized, tabs, tabSelection);
  let tab = findPlatformTab(tabs, normalized, tabSelection);

  if (forceFreshTab && entryUrl) {
    if (allowTabAutocreate) {
      try {
        const opened = await createCdpTab(entryUrl);
        actions.push({
          kind: "platform_tab_reauthed",
          platform: normalized,
          requested_url: entryUrl,
          created_tab_id: String(opened?.id || "").trim(),
          opened: Boolean(opened && opened.id),
        });
        tab = opened;
      } catch (error) {
        actions.push({
          kind: "platform_tab_reauthed_failed",
          platform: normalized,
          error: String(error?.message || error),
        });
      }
    } else if (!tab) {
      const fallbackTab = findPlatformDomainFallbackTab(tabs, normalized);
      if (fallbackTab) {
        tab = fallbackTab;
        actions.push({
          kind: "platform_tab_domain_fallback",
          platform: normalized,
          tab_id: String(fallbackTab?.id || "").trim(),
          tab_url: String(fallbackTab?.url || "").trim(),
          reason: "autocreate_disabled_reuse_existing_domain_tab",
        });
      } else {
        return {
          tab: null,
          error: {
            code: "platform_tab_autocreate_disabled",
            message: (
              `已关闭自动补齐发布页窗口。请在绑定的 ${ATTACHED_BROWSER} 会话中先打开 ${normalized} 发布页 `
              + `（建议入口：${entryUrl}），或在调试时设置 PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE=true。`
            ),
            details: { platform: normalized },
          },
          actions,
        };
      }
    }
  }

  if (!tab) {
    if (!entryUrl) {
      return {
        tab: null,
        error: {
          code: "platform_publish_entry_missing",
          message: `未配置 ${normalized} 的发布页入口，无法自动补齐缺失窗口。`,
          details: { platform: normalized },
        },
        actions,
      };
    }
    if (!allowTabAutocreate) {
      const fallbackTab = findPlatformDomainFallbackTab(tabs, normalized);
      if (fallbackTab) {
        actions.push({
          kind: "platform_tab_domain_fallback",
          platform: normalized,
          tab_id: String(fallbackTab?.id || "").trim(),
          tab_url: String(fallbackTab?.url || "").trim(),
          reason: "autocreate_disabled_reuse_existing_domain_tab",
        });
        return { tab: fallbackTab, actions };
      }
      return {
        tab: null,
        error: {
          code: "platform_tab_autocreate_disabled",
          message: (
            `已关闭自动补齐发布页窗口。请在绑定的 ${ATTACHED_BROWSER} 会话中先打开 ${normalized} 发布页 `
            + `（建议入口：${entryUrl}），或在调试时设置 PUBLICATION_BROWSER_ALLOW_TAB_AUTOCREATE=true。`
          ),
          details: { platform: normalized },
        },
        actions,
      };
    }
    const opened = await createCdpTab(entryUrl);
        actions.push({
          kind: "platform_tab_autocreated",
      platform: normalized,
      requested_url: entryUrl,
      created_tab_id: String(opened?.id || "").trim(),
      opened: Boolean(opened && opened.id),
    });
    for (let i = 0; i < 12; i += 1) {
      await sleep(600);
      tabs = await listCdpTabs();
      tab = findPlatformTab(tabs, normalized, tabSelection);
      if (tab) break;
    }
  }
  if (!tab) {
    return {
      tab: null,
      error: {
        code: "platform_tab_not_found",
        message: `没有找到 ${normalized} 已打开的创作/发布页。`,
        details: { platform: normalized, entry_url: entryUrl },
      },
      actions,
    };
  }
  if (
    receiptEntryUrl
    && tab
    && shouldAcquireReceiptSurfaceRoute(normalized, String(tab.url || ""), tabSelection)
  ) {
    const receiptRouteAction = await navigateExistingTabToUrl(tab, receiptEntryUrl, {
      verify: (snapshot) => isPlatformReceiptSurfaceUrl(normalized, snapshot?.url || ""),
      reason: "receipt_surface_route_acquisition",
    });
    actions.push({
      kind: "receipt_surface_route_acquired",
      ...receiptRouteAction,
    });
    if (receiptRouteAction.verified) {
      tab = {
        ...tab,
        url: String(receiptRouteAction.url || tab.url || receiptEntryUrl),
        title: String(receiptRouteAction.title || tab.title || ""),
      };
    }
  }
  return { tab, actions };
}

function normalizePlatform(value) {
  const key = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (key === "b站" || key === "bili") return "bilibili";
  if (key === "小红书" || key === "rednote") return "xiaohongshu";
  if (key === "视频号" || key === "wechat-channels") return "wechat-channels";
  return key;
}

export function derivePlatformTabSelectionPolicy(platform, recoveryContext = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const context = recoveryContext && typeof recoveryContext === "object" ? recoveryContext : {};
  const recoveryMode = _normalize_recovery_mode(context.recovery_mode);
  const stopBeforeFinalPublish = Boolean(
    context.prepublish_only_current_page || context.prepare_only_current_page,
  );
  const allowSafeAutocreate = Boolean(
    context.verification_only_current_page
    || context.repair_only_current_page
    || context.prepublish_only_current_page
    || context.prepare_only_current_page
    || recoveryMode === "receipt_rebind"
  );
  return {
    prefer_receipt_surface: Boolean(
      (normalizedPlatform === "douyin" || normalizedPlatform === "xiaohongshu" || normalizedPlatform === "toutiao")
      && context.verification_only_current_page
      && recoveryMode === "receipt_rebind"
    ),
    prefer_stable_upload_surface: Boolean(
      normalizedPlatform === "youtube" && stopBeforeFinalPublish,
    ),
    prefer_draft_list_surface: Boolean(
      normalizedPlatform === "youtube" && stopBeforeFinalPublish,
    ),
    allow_safe_autocreate: allowSafeAutocreate,
  };
}

export function isPlatformReceiptSurfaceUrl(platform, url = "") {
  const normalizedPlatform = normalizePlatform(platform);
  const normalizedUrl = String(url || "").trim();
  if (!normalizedUrl) return false;
  if (normalizedPlatform === "douyin") {
    return /creator\.douyin\.com\/creator-micro\/content\/manage/i.test(normalizedUrl);
  }
  if (normalizedPlatform === "xiaohongshu") {
    return /creator\.xiaohongshu\.com\/(?:publish\/success|new\/note-manager)/i.test(normalizedUrl);
  }
  if (normalizedPlatform === "toutiao") {
    return /mp\.toutiao\.com\/profile_v4\/manage\/content\/all/i.test(normalizedUrl);
  }
  return false;
}

export function shouldBootstrapGenericPublishRoute(platform, route = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  if (!normalizedPlatform) return false;
  if (normalizedPlatform === "xiaohongshu" || normalizedPlatform === "toutiao") return false;
  const entryUrl = PLATFORM_PUBLISH_ENTRY_URLS[normalizedPlatform];
  if (!entryUrl) return false;
  const currentUrl = String(route?.url || "").trim();
  const lowerCurrentUrl = currentUrl.toLowerCase();
  if (currentUrl) {
    if (
      normalizedPlatform === "douyin"
      && !/creator\.douyin\.com\/creator-micro\/content\/post\/video/i.test(currentUrl)
    ) {
      return true;
    }
    if (
      normalizedPlatform === "bilibili"
      && !/member\.bilibili\.com\/platform\/upload\/video/i.test(currentUrl)
    ) {
      return true;
    }
    if (
      normalizedPlatform === "kuaishou"
      && !/cp\.kuaishou\.com\/article\/publish\/video/i.test(currentUrl)
    ) {
      return true;
    }
    if (
      normalizedPlatform === "x"
      && !/x\.com\/compose\/(?:tweet|post)|twitter\.com\/compose\/(?:tweet|post)/i.test(currentUrl)
    ) {
      return true;
    }
    if (
      normalizedPlatform !== "youtube"
      && lowerCurrentUrl.startsWith(String(entryUrl).toLowerCase())
    ) {
      return false;
    }
  }
  return !isCompositePublishRouteContext(normalizedPlatform, route);
}

export function shouldAcquireReceiptSurfaceRoute(platform, currentUrl = "", selection = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  if (!selection || !selection.prefer_receipt_surface) return false;
  if (!PLATFORM_RECEIPT_ENTRY_URLS[normalizedPlatform]) return false;
  return !isPlatformReceiptSurfaceUrl(normalizedPlatform, currentUrl);
}

export function shouldEnforcePlatformPublishRoute(platform, recoveryContext = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const context = recoveryContext && typeof recoveryContext === "object" ? recoveryContext : {};
  const recoveryMode = _normalize_recovery_mode(context.recovery_mode);
  if (
    (normalizedPlatform === "douyin" || normalizedPlatform === "xiaohongshu" || normalizedPlatform === "toutiao")
    && Boolean(context.verification_only_current_page)
    && recoveryMode === "receipt_rebind"
  ) {
    return false;
  }
  return true;
}

export function deriveNavigationJavaScriptDialogHandling(dialog = {}, options = {}) {
  const normalizedType = String(dialog.type || "").trim().toLowerCase();
  const normalizedMessage = String(dialog.message || "").replace(/\s+/g, " ").trim();
  const policy = String(options.policy || "navigation_route_switch").trim().toLowerCase();
  const isLeaveSitePrompt = /离开此网站|不会保存您所做的更改|leave this site|changes you made may not be saved/i.test(normalizedMessage);
  if (policy === "navigation_route_switch") {
    if (normalizedType === "beforeunload" || isLeaveSitePrompt) {
      return {
        action: "accept",
        reason: "route_switch_beforeunload",
        type: normalizedType || "unknown",
        message: normalizedMessage,
      };
    }
    if (normalizedType) {
      return {
        action: "dismiss",
        reason: "route_switch_unexpected_dialog",
        type: normalizedType,
        message: normalizedMessage,
      };
    }
  }
  return {
    action: "ignore",
    reason: "dialog_policy_noop",
    type: normalizedType || "unknown",
    message: normalizedMessage,
  };
}

async function navigateExistingTabToUrl(tab, targetUrl, options = {}) {
  if (!tab?.webSocketDebuggerUrl) {
    return {
      navigated: false,
      verified: false,
      url: String(tab?.url || ""),
      reason: "tab_has_no_websocket",
    };
  }
  const verify = typeof options.verify === "function"
    ? options.verify
    : ((snapshot) => String(snapshot?.url || "").startsWith(String(targetUrl || "")));
  const waitTimeoutMs = Number.isFinite(options.timeout_ms) ? Number(options.timeout_ms) : 18000;
  const currentUrl = String(tab?.url || "");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  const handledDialogs = [];
  let removeDialogHandler = () => {};
  try {
    await client.send("Page.enable").catch(() => {});
    removeDialogHandler = client.on("Page.javascriptDialogOpening", (params = {}) => {
      const handling = deriveNavigationJavaScriptDialogHandling(params, {
        policy: String(options.javascript_dialog_policy || "navigation_route_switch"),
      });
      handledDialogs.push({
        type: handling.type,
        action: handling.action,
        reason: handling.reason,
        message: handling.message,
      });
      if (handling.action === "ignore") return;
      client.send("Page.handleJavaScriptDialog", {
        accept: handling.action === "accept",
        promptText: "",
      }).catch(() => {});
    });
    await client.send("Page.navigate", { url: targetUrl });
    let current = null;
    const startedAt = Date.now();
    while (Date.now() - startedAt < waitTimeoutMs) {
      await sleep(1500);
      current = await pageSnapshot(client).catch(() => null);
      if (current && verify(current)) {
        return {
          navigated: true,
          from: currentUrl,
          to: targetUrl,
          url: String(current.url || targetUrl || currentUrl),
          title: String(current.title || ""),
          verified: true,
          reason: String(options.reason || "route_navigation_verified"),
          dialogs: handledDialogs,
        };
      }
    }
    return {
      navigated: true,
      from: currentUrl,
      to: targetUrl,
      url: String(current?.url || targetUrl || currentUrl),
      title: String(current?.title || ""),
      verified: false,
      reason: String(options.reason || "route_navigation_not_verified"),
      dialogs: handledDialogs,
    };
  } finally {
    try {
      removeDialogHandler?.();
    } catch {}
    client.close();
  }
}

export function findPlatformTab(tabs, platform, options = {}) {
  return findPlatformTabs(tabs, platform, options)[0];
}

export function extractYouTubeStudioChannelId(url = "") {
  const match = String(url || "").match(/studio\.youtube\.com\/channel\/([A-Za-z0-9_-]{6,})/i);
  return String(match?.[1] || "").trim();
}

export function buildYouTubeStudioUploadEntryUrl(channelId = "") {
  const normalized = String(channelId || "").trim();
  if (!normalized) return String(PLATFORM_PUBLISH_ENTRY_URLS.youtube || "").trim();
  return `https://studio.youtube.com/channel/${normalized}/videos/upload`;
}

export function buildYouTubeStudioContentListUrl(channelId = "") {
  const normalized = String(channelId || "").trim();
  if (!normalized) return String(PLATFORM_PUBLISH_ENTRY_URLS.youtube || "").trim();
  return `https://studio.youtube.com/channel/${normalized}/videos`;
}

export function resolvePlatformPublishEntryUrl(platform, tabs = [], options = {}) {
  const normalized = normalizePlatform(platform);
  if (normalized !== "youtube") {
    return String(PLATFORM_PUBLISH_ENTRY_URLS[normalized] || "").trim();
  }
  const youtubeTabs = Array.isArray(tabs) ? tabs : [];
  const validChannelId = youtubeTabs
    .map((tab) => extractYouTubeStudioChannelId(tab?.url || ""))
    .find((channelId) => channelId.length >= 6);
  if (options && options.prefer_draft_list_surface) {
    return buildYouTubeStudioContentListUrl(validChannelId);
  }
  return buildYouTubeStudioUploadEntryUrl(validChannelId);
}

export function findPlatformTabs(tabs, platform, options = {}) {
  const domains = PLATFORM_DOMAINS[platform] || [];
  return (tabs || [])
    .map((tab) => ({ tab, score: platformTabScore(tab, domains, platform, options) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score)
    .map((item) => item.tab);
}

export function findPlatformDomainFallbackTab(tabs, platform) {
  const domains = PLATFORM_DOMAINS[platform] || [];
  return (tabs || [])
    .map((tab) => ({ tab, score: platformDomainFallbackScore(tab, domains) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score)
    .map((item) => item.tab)[0] || null;
}

export function shouldBootstrapProbeInventoryRoute(platform, tab = null) {
  const normalizedPlatform = normalizePlatform(platform);
  if (!tab || typeof tab !== "object") return true;
  const routeUrl = String(tab.url || "").trim();
  if (!routeUrl) return true;
  return !isCompositePublishRouteContext(normalizedPlatform, {
    url: routeUrl,
    text: "",
    file_inputs: [],
  });
}

function platformDomainFallbackScore(tab, domains) {
  let parsed;
  try {
    parsed = new URL(String(tab.url || ""));
  } catch {
    return 0;
  }
  const hostname = parsed.hostname.toLowerCase();
  const pathname = parsed.pathname.toLowerCase();
  let score = 0;
  for (const rawDomain of domains) {
    const normalized = String(rawDomain || "").toLowerCase();
    if (!normalized) continue;
    const slashIndex = normalized.indexOf("/");
    const domainHost = slashIndex >= 0 ? normalized.slice(0, slashIndex) : normalized;
    const hostMatches = hostname === domainHost || hostname.endsWith(`.${domainHost}`);
    if (!hostMatches) continue;
    score = Math.max(score, 30);
  }
  if (!score) return 0;
  if (tab.type === "page") score += 10;
  if (/upload|publish|post|article|studio|creator|manage|video/.test(pathname)) score += 8;
  if (/login|signin|passport|auth/.test(pathname)) score -= 20;
  if (/iframe|worker|popup/i.test(String(tab.title || ""))) score -= 8;
  return score;
}

export function platformTabScore(tab, domains, platform = "", options = {}) {
  let parsed;
  try {
    parsed = new URL(String(tab.url || ""));
  } catch {
    return 0;
  }
  const hostname = parsed.hostname.toLowerCase();
  const pathname = parsed.pathname.toLowerCase();
  let score = 0;
  for (const rawDomain of domains) {
    const normalized = String(rawDomain || "").toLowerCase();
    if (!normalized) continue;
    const slashIndex = normalized.indexOf("/");
    const domainHost = slashIndex >= 0 ? normalized.slice(0, slashIndex) : normalized;
    const domainPath = slashIndex >= 0 ? normalized.slice(slashIndex) : "";
    const hostMatches = hostname === domainHost || hostname.endsWith(`.${domainHost}`);
    if (!hostMatches) continue;
    const pathMatches = !domainPath || pathname.startsWith(domainPath);
    if (!pathMatches) continue;
    score = Math.max(score, 20 + (domainPath ? 10 : 0));
  }
  if (!score) return 0;
  if (platform === "youtube") {
    const channelId = extractYouTubeStudioChannelId(parsed.href);
    if (/\/channel\//.test(pathname) && !channelId) return 0;
  }
  if (tab.type === "page") score += 10;
  if (/upload|publish|post|article|studio|creator/.test(pathname)) score += 5;
  if (platform === "youtube") {
    const contentListRoute = /\/channel\/[^/?#]+\/videos\/?$/.test(pathname);
    const uploadListRoute = /\/channel\/[^/?#]+\/videos\/upload/.test(pathname);
    const editorRoute = /\/video\/[a-z0-9_-]+\/edit/.test(pathname);
    if (options.prefer_draft_list_surface) {
      if (contentListRoute) score += 150;
      if (uploadListRoute) {
        if (hasYoutubeUploadResumeVideoId(parsed.href)) score += 165;
        else if (hasYoutubeUploadDialogQuery(parsed.href)) score += 45;
        else score += 30;
      }
      if (editorRoute) score += 35;
    } else {
      if (uploadListRoute) score += options.prefer_stable_upload_surface ? 140 : 90;
      if (editorRoute) score += options.prefer_stable_upload_surface ? 25 : 80;
      if (/\/channel\/.+\/videos/.test(pathname)) score -= 20;
    }
  }
  if (platform === "x") {
    if (/\/compose\/tweet/.test(pathname)) score += 90;
    if (/\/compose\/post/.test(pathname)) score += 85;
    if (/\/compose/.test(pathname)) score += 80;
    if (/\/home/.test(pathname)) score += 10;
  }
  if (platform === "wechat-channels") {
    if (/\/platform\/post\/create/.test(pathname)) score += 80;
  }
  if (platform === "douyin") {
    if (/\/creator-micro\/content\/post\/video/.test(pathname)) score += 80;
    if (/\/creator-micro\/content\/manage/.test(pathname)) score += 35;
    if (options.prefer_receipt_surface) {
      if (/\/creator-micro\/content\/manage/.test(pathname)) score += 120;
      if (/\/creator-micro\/content\/post\/video/.test(pathname)) score -= 30;
    }
  }
  if (platform === "kuaishou") {
    if (/\/article\/publish\/video/.test(pathname)) score += 80;
  }
  if (platform === "bilibili") {
    if (/\/platform\/upload-manager\/article/.test(pathname)) return 0;
    if (/\/platform\/upload\/video(?:\/frame)?/.test(pathname)) score += 85;
  }
  if (platform === "xiaohongshu") {
    if (/\/publish\/publish/.test(pathname)) score += 80;
    if (/\/new\/note-manager/.test(pathname)) score += options.prefer_receipt_surface ? 125 : 20;
    if (/\/publish\/success/.test(pathname)) score += options.prefer_receipt_surface ? 130 : 40;
    if (options.prefer_receipt_surface && /\/publish\/publish/.test(pathname)) score -= 25;
  }
  if (platform === "toutiao") {
    if (/\/profile_v4\/xigua\/upload-video/.test(pathname)) score += 80;
    if (/\/profile_v4\/xigua\/publish-video/.test(pathname)) score += 60;
    if (/\/graphic\/publish/.test(pathname)) score -= 80;
  }
  if (/iframe|worker|popup/i.test(String(tab.title || ""))) score -= 8;
  return score;
}

async function evaluatePage(tab, expression) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    const result = await client.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      timeout: 8000,
    });
    return result?.result?.value || {};
  } finally {
    client.close();
  }
}

async function evaluateWithClient(client, expression, timeout = 8000) {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    timeout,
  });
  if (result?.exceptionDetails) {
    const detail = formatRuntimeException(result.exceptionDetails, expression);
    throw new Error(detail);
  }
  return result?.result?.value || {};
}

function formatRuntimeException(exceptionDetails, expression = "") {
  const description = exceptionDetails?.exception?.description || exceptionDetails?.text || "Runtime.evaluate failed";
  const lineNumber = Number.isFinite(exceptionDetails?.lineNumber) ? Number(exceptionDetails.lineNumber) : null;
  const columnNumber = Number.isFinite(exceptionDetails?.columnNumber) ? Number(exceptionDetails.columnNumber) : null;
  if (lineNumber == null && columnNumber == null) return description;
  const lines = String(expression || "").split("\n");
  const lineIndex = lineNumber != null ? Math.max(0, Math.min(lines.length - 1, lineNumber)) : -1;
  const lineText = lineIndex >= 0 ? lines[lineIndex] : "";
  const pointerColumn = columnNumber != null ? Math.max(0, Math.min(lineText.length, columnNumber)) : 0;
  const pointerLine = lineText ? `${" ".repeat(pointerColumn)}^` : "";
  return [
    description,
    `at line ${lineNumber != null ? lineNumber + 1 : "?"}, column ${columnNumber != null ? columnNumber + 1 : "?"}`,
    lineText,
    pointerLine,
  ].filter(Boolean).join("\n");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class AsyncStepTimeoutError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "AsyncStepTimeoutError";
    this.code = String(code || "async_step_timeout");
    this.details = details && typeof details === "object" ? details : {};
  }
}

function withAsyncStepTimeout(promise, timeoutMs, code, message, details = {}) {
  const normalizedTimeout = Math.max(1000, Number(timeoutMs) || 0);
  if (!normalizedTimeout) return promise;
  return Promise.race([
    promise,
    (async () => {
      await sleep(normalizedTimeout);
      throw new AsyncStepTimeoutError(
        code,
        message,
        {
          ...(details && typeof details === "object" ? details : {}),
          timeout_ms: normalizedTimeout,
        },
      );
    })(),
  ]);
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    this.eventHandlers = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) {
        const method = String(message.method || "").trim();
        if (method && this.eventHandlers.has(method)) {
          for (const handler of [...(this.eventHandlers.get(method) || [])]) {
            try {
              handler(message.params || {});
            } catch {}
          }
        }
        return;
      }
      if (!this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message || "CDP error"));
      else resolve(message.result);
    });
    socket.addEventListener("close", () => {
      for (const { reject } of this.pending.values()) reject(new Error("CDP socket closed"));
      this.pending.clear();
    });
  }

  static connect(url, timeoutMs = 10000) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      let settled = false;
      const cleanup = () => {
        clearTimeout(timer);
        socket.removeEventListener("open", onOpen);
        socket.removeEventListener("error", onError);
      };
      const onOpen = () => {
        if (settled) return;
        settled = true;
        cleanup();
        resolve(new CdpClient(socket));
      };
      const onError = () => {
        if (settled) return;
        settled = true;
        cleanup();
        reject(new Error("CDP websocket connect failed"));
      };
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        cleanup();
        try {
          socket.close();
        } catch {}
        reject(new AsyncStepTimeoutError(
          "platform_cdp_connect_timeout",
          `CDP websocket connect timed out after ${Math.max(1000, Number(timeoutMs) || 10000)}ms`,
          { timeout_ms: Math.max(1000, Number(timeoutMs) || 10000) },
        ));
      }, Math.max(1000, Number(timeoutMs) || 10000));
      socket.addEventListener("open", onOpen, { once: true });
      socket.addEventListener("error", onError, { once: true });
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      const timeoutMs = Math.max(5000, Number(params.timeout || 30000) + 5000);
      const timer = setTimeout(() => {
        if (!this.pending.has(id)) return;
        this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.socket.send(payload);
    });
  }

  on(method, handler) {
    const normalizedMethod = String(method || "").trim();
    if (!normalizedMethod || typeof handler !== "function") return () => {};
    if (!this.eventHandlers.has(normalizedMethod)) {
      this.eventHandlers.set(normalizedMethod, new Set());
    }
    this.eventHandlers.get(normalizedMethod).add(handler);
    return () => this.off(normalizedMethod, handler);
  }

  off(method, handler) {
    const normalizedMethod = String(method || "").trim();
    if (!normalizedMethod || !this.eventHandlers.has(normalizedMethod)) return;
    const handlers = this.eventHandlers.get(normalizedMethod);
    handlers?.delete(handler);
    if (!handlers || handlers.size === 0) {
      this.eventHandlers.delete(normalizedMethod);
    }
  }

  close() {
    try {
      this.socket.close();
    } catch {
      // Nothing to clean up beyond the browser socket.
    }
  }
}

const PAGE_SNAPSHOT_EXPRESSION = `(() => {
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const visible = (el) => {
    const doc = el.ownerDocument || document;
    const win = doc.defaultView || window;
    const rect = el.getBoundingClientRect();
    const style = win.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const roots = [];
  const visitRoot = (root) => {
    if (!root || roots.includes(root)) return;
    roots.push(root);
    for (const el of [...root.querySelectorAll("*")]) {
      if (el.shadowRoot) visitRoot(el.shadowRoot);
      if (el.tagName === "IFRAME") {
        try {
          if (el.contentDocument) visitRoot(el.contentDocument);
        } catch {}
      }
    }
  };
  visitRoot(document);
  const queryAll = (selector) => roots.flatMap((root) => {
    try {
      return [...root.querySelectorAll(selector)];
    } catch {
      return [];
    }
  });
  const rawText = roots.map((root) => {
    const body = root.body || root.host || root.documentElement;
    return body ? String(body.innerText || body.textContent || "") : "";
  }).join("\\n");
  const elements = queryAll("button,input,textarea,select,label,[role=button],[role=checkbox],[role=switch],[role=combobox],[role=option],[role=menuitem],[aria-label],[class*=select],[class*=dropdown],[class*=option],[class*=menu],[class*=collection],[class*=playlist]")
    .filter(visible)
    .slice(0, 1200)
    .map((el) => ({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role") || "",
      className: clean(typeof el.className === "string" ? el.className : ""),
      type: el.getAttribute("type") || "",
      text: clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title")),
      ariaLabel: clean(el.getAttribute("aria-label")),
      placeholder: clean(el.getAttribute("placeholder")),
      checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
      options: el.tagName.toLowerCase() === "select" ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean) : [],
    }));
  const overlayTexts = queryAll("[role=dialog],[aria-modal=true],[role=listbox],[role=menu],[class*=modal i],[class*=dialog i],[class*=popover i],[class*=dropdown i],[class*=select i],[class*=menu i],[class*=overlay i],[class*=drawer i]")
    .filter(visible)
    .slice(0, 80)
    .map((el) => clean(el.innerText || el.textContent))
    .filter(Boolean);
  const headings = queryAll("h1,h2,h3,h4,[class*=title],[class*=label]")
    .filter(visible)
    .slice(0, 220)
    .map((el) => clean(el.innerText))
    .filter(Boolean);
  const lines = rawText.split(/[\\n\\r]+/)
    .flatMap((line) => String(line).split(/ {2,}/))
    .map((line) => clean(line))
    .filter(Boolean)
    .slice(0, 1800);
  const fileInputs = queryAll("input[type=file]").map((el, index) => ({
    index,
    accept: el.getAttribute("accept") || "",
    multiple: Boolean(el.multiple),
    visible: visible(el),
  }));
  return { url: location.href, title: document.title, lines, headings, elements, overlayTexts, fileInputs };
})()`;

async function pageSnapshot(client, options = {}) {
  const snapshot = await evaluateWithClient(client, PAGE_SNAPSHOT_EXPRESSION, 12000);
  if (options?.captureVisualEvidence) {
    return attachVisualEvidenceToSnapshot(client, snapshot, options);
  }
  return snapshot;
}

export function isXiaohongshuPublishEditorSurfaceReady(snapshot = {}) {
  const url = String(snapshot?.url || "");
  if (!/creator\.xiaohongshu\.com\/publish/i.test(url)) return false;
  const fileInputs = Array.isArray(snapshot?.fileInputs) ? snapshot.fileInputs : [];
  const text = [...(snapshot?.lines || []), ...(snapshot?.headings || [])]
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .join(" ");
  if (fileInputs.length > 0) return true;
  return /封面设置|发布设置|内容设置|原创声明|添加内容类型声明|选择群聊|公开可见|定时发布|查看权限/.test(text);
}

export function isXiaohongshuVideoUploadEntrySurface(routeUrl = "", text = "") {
  const url = String(routeUrl || "");
  const textHaystack = String(text || "");
  return /creator\.xiaohongshu\.com\/publish\/publish/i.test(url)
    && /上传视频|点击上传|拖拽视频到此或点击上传|将视频拖拽到|视频大小|最大20GB|推荐使用mp4|上传图文|写长文|发播客/.test(textHaystack);
}

async function ensureXiaohongshuPublishRoute(client, tab, options = {}) {
  const forcePublishRefresh = Boolean(options.force_publish_page_refresh);
  const entryUrl = PLATFORM_PUBLISH_ENTRY_URLS.xiaohongshu;
  const noteManagerUrl = "https://creator.xiaohongshu.com/new/note-manager";
  const currentUrl = String(tab?.url || "");
  await client.send("Page.enable").catch(() => {});

  const waitForEditorSurface = async (timeoutMs = 18000) => {
    let current = null;
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      await sleep(1200);
      current = await pageSnapshot(client).catch(() => null);
      if (current && isXiaohongshuPublishEditorSurfaceReady(current)) {
        return { verified: true, snapshot: current };
      }
    }
    return { verified: false, snapshot: current };
  };

  if (!forcePublishRefresh) {
    const current = await pageSnapshot(client).catch(() => null);
    return {
      navigated: false,
      reason: "not_required",
      url: current?.url || currentUrl,
      verified: Boolean(current && isXiaohongshuPublishEditorSurfaceReady(current)),
    };
  }

  await client.send("Page.navigate", { url: entryUrl });
  const directAttempt = await waitForEditorSurface(9000);
  if (directAttempt.verified) {
    return {
      navigated: true,
      from: currentUrl,
      to: directAttempt.snapshot?.url || entryUrl,
      url: directAttempt.snapshot?.url || entryUrl,
      verified: true,
      reason: "forced_publish_page_refresh",
    };
  }

  await client.send("Page.navigate", { url: noteManagerUrl });
  let managerSnapshot = null;
  const managerStartedAt = Date.now();
  while (Date.now() - managerStartedAt < 12000) {
    await sleep(1200);
    managerSnapshot = await pageSnapshot(client).catch(() => null);
    const managerUrl = String(managerSnapshot?.url || "");
    const managerText = [...(managerSnapshot?.lines || []), ...(managerSnapshot?.headings || [])].join(" ");
    if (/creator\.xiaohongshu\.com\/new\/note-manager/i.test(managerUrl) && /发布笔记|笔记管理/.test(managerText)) {
      break;
    }
  }

  const publishEntry = await clickByText(client, ["发布笔记"]);
  const publishEntryFallback = !publishEntry.clicked ? await clickLooseText(client, ["发布笔记"]) : null;
  const clickResult = publishEntry.clicked ? publishEntry : (publishEntryFallback || publishEntry);
  const fallbackAttempt = await waitForEditorSurface(15000);
  return {
    navigated: true,
    from: currentUrl,
    to: fallbackAttempt.snapshot?.url || managerSnapshot?.url || noteManagerUrl,
    url: fallbackAttempt.snapshot?.url || managerSnapshot?.url || noteManagerUrl,
    verified: fallbackAttempt.verified,
    reason: fallbackAttempt.verified ? "xiaohongshu_note_manager_publish_entry" : "xiaohongshu_publish_entry_not_verified",
    clicked_label: clickResult?.clicked_label || clickResult?.label || "",
  };
}

async function ensurePlatformPublishRoute(client, tab, platform, options = {}) {
  const forcePublishRefresh = Boolean(options.force_publish_page_refresh);
  const entryUrl = platform === "youtube"
    ? resolvePlatformPublishEntryUrl("youtube", [tab], {
      prefer_draft_list_surface: Boolean(options.prefer_draft_list_surface),
    })
    : PLATFORM_PUBLISH_ENTRY_URLS[platform];

  if (platform === "xiaohongshu") {
    return ensureXiaohongshuPublishRoute(client, tab, options);
  }

  const currentUrl = String(tab?.url || "");
  const current = await pageSnapshot(client).catch(() => null);
  const currentText = current
    ? [...(current.lines || []), ...(current.headings || [])].join(" ")
    : "";

  if (forcePublishRefresh && entryUrl) {
    if (platform === "youtube") {
      if (
        shouldPreserveYouTubeUploadResumeRouteForBootstrap(current?.url || currentUrl, currentText)
        || shouldPreserveYouTubeEditorRouteForBootstrap(current?.url || currentUrl, currentText)
      ) {
        return {
          navigated: false,
          from: currentUrl,
          to: current?.url || currentUrl,
          url: current?.url || currentUrl,
          title: String(current?.title || tab?.title || ""),
          verified: true,
          reason: "youtube_preserve_upload_resume_route",
        };
      }
    }
    await client.send("Page.enable").catch(() => {});
    await client.send("Page.navigate", { url: entryUrl });
    let current = null;
    const startedAt = Date.now();
    while (Date.now() - startedAt < 18000) {
      await sleep(1500);
      current = await pageSnapshot(client).catch(() => null);
      if (current && isCompositePublishRouteContext(platform, {
        url: current.url || "",
        text: [...(current.lines || []), ...(current.headings || [])].join(" "),
        file_inputs: current.fileInputs || [],
      })) {
        return {
          navigated: true,
          from: currentUrl,
          to: current.url || currentUrl || entryUrl,
          url: current.url || currentUrl || entryUrl,
          verified: true,
          reason: "forced_publish_page_refresh",
        };
      }
    }
    return {
      navigated: true,
      from: currentUrl,
      to: entryUrl,
      url: current?.url || entryUrl,
      verified: false,
      reason: "forced_publish_page_refresh_not_verified",
    };
  }

  if (
    entryUrl
    && shouldBootstrapGenericPublishRoute(platform, {
      url: current?.url || currentUrl,
      text: currentText,
      file_inputs: current?.fileInputs || [],
    })
  ) {
    await client.send("Page.enable").catch(() => {});
    await client.send("Page.navigate", { url: entryUrl });
    let refreshed = null;
    const startedAt = Date.now();
    while (Date.now() - startedAt < 18000) {
      await sleep(1500);
      refreshed = await pageSnapshot(client).catch(() => null);
      if (refreshed && isCompositePublishRouteContext(platform, {
        url: refreshed.url || "",
        text: [...(refreshed.lines || []), ...(refreshed.headings || [])].join(" "),
        file_inputs: refreshed.fileInputs || [],
      })) {
        return {
          navigated: true,
          from: current?.url || currentUrl,
          to: refreshed.url || entryUrl,
          url: refreshed.url || entryUrl,
          title: String(refreshed?.title || tab?.title || ""),
          verified: true,
          reason: "generic_publish_route_bootstrap",
        };
      }
    }
    return {
      navigated: true,
      from: current?.url || currentUrl,
      to: entryUrl,
      url: refreshed?.url || entryUrl,
      verified: false,
      reason: "generic_publish_route_bootstrap_not_verified",
    };
  }

  if (platform !== "toutiao") return { navigated: false, reason: "not_required" };
  if (/mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/i.test(currentUrl)) {
    const hasVideoInput = (current?.fileInputs || []).some((input) => /video|mp4/i.test(input.accept || ""));
    return { navigated: false, reason: "already_video_publish_route", url: current?.url || currentUrl, verified: hasVideoInput };
  }
  const targetUrl = "https://mp.toutiao.com/profile_v4/xigua/upload-video?index=0";
  await client.send("Page.enable").catch(() => {});
  await client.send("Page.navigate", { url: targetUrl });
  let toutiaoCurrent = null;
  const startedAt = Date.now();
  while (Date.now() - startedAt < 18000) {
    await sleep(1500);
    toutiaoCurrent = await pageSnapshot(client).catch(() => null);
    const url = String(toutiaoCurrent?.url || "");
    const text = [...(toutiaoCurrent?.lines || []), ...(toutiaoCurrent?.headings || [])].join(" ");
    const hasVideoInput = (toutiaoCurrent?.fileInputs || []).some((input) => /video|mp4/i.test(input.accept || ""));
    if (/mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/i.test(url) && (hasVideoInput || /点击上传|发布视频/.test(text))) {
      return { navigated: true, from: currentUrl, to: targetUrl, url, verified: true };
    }
  }
  return { navigated: true, from: currentUrl, to: targetUrl, url: toutiaoCurrent?.url || "", verified: false, reason: "toutiao_video_publish_route_not_verified" };
}

async function clearInPageDraftState(client, platform, options = {}) {
  const mediaPath = String(options.mediaPath || "").trim();
  const mediaName = mediaPath ? path.win32.basename(mediaPath) : "";
  const mediaStem = mediaName ? mediaName.replace(/\.[^.]+$/, "") : "";
  const clearTextGroups = _platformDraftClearGroups(platform);
  const clearIfStaleDraft = Boolean(options.clearIfStaleDraft);
  const forceClearDraft = Boolean(options.forceClearDraft);
  const actions = [];
  const before = await pageSnapshot(client).catch(() => ({}));
  const beforeText = [...(before.lines || []), ...(before.headings || [])].map((line) => String(line || "").trim()).join(" ");
  const beforeMediaHint = Boolean(mediaName && (beforeText.includes(mediaName) || beforeText.includes(mediaStem)));
  const beforeDraftHint = /草稿|草稿箱|编辑失败|上传失败|Upload failed|Upload Failed|上传中|视频处理中|请重试|Upload error|publish failed|need retry|重新上传/i.test(beforeText);
  const inputInspect = await evaluateWithClient(client, `(() => {
    const allInputs = [...document.querySelectorAll("input[type=file]")]
      .filter((input) => {
        const style = getComputedStyle(input);
        const rect = input.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !input.disabled && input.getAttribute("aria-disabled") !== "true";
      });
    const candidateInputs = allInputs.filter((input) => {
      const accept = String(input.getAttribute("accept") || "").toLowerCase();
      return /video|mp4|media|octet|application|mpeg|quicktime/i.test(accept) || !/image|audio/i.test(accept) || !accept;
    });
    const results = [];
    for (const input of candidateInputs) {
      const hasFiles = input.files && input.files.length > 0;
      results.push({
        accept: String(input.getAttribute("accept") || ""),
        visible: true,
        has_files: Boolean(hasFiles),
        has_value: Boolean(input.value || input.getAttribute("value")),
      });
    }
    return {
      input_count: allInputs.length,
      video_like_input_count: candidateInputs.length,
      has_media_hint: results.some((item) => item.has_files || item.has_value),
      results: results.slice(0, 6),
    };
  })()`, 12000).catch(() => ({
    input_count: 0,
    video_like_input_count: 0,
    has_media_hint: false,
    results: [],
  }));
  const staleDraftDetected = beforeDraftHint || beforeMediaHint || Boolean(inputInspect.has_media_hint);
  actions.push({
    kind: "draft_clear_before",
    platform,
    media_name: mediaName,
    before_media_hint: beforeMediaHint,
    before_draft_hint: beforeDraftHint,
    before_url: before.url || "",
    before_input_media_hint: Boolean(inputInspect.has_media_hint),
    clear_if_stale: clearIfStaleDraft,
  });
  if (!forceClearDraft && clearIfStaleDraft && !staleDraftDetected) {
    return {
      platform,
      attempted: false,
      skipped: true,
      stale_detected: false,
      cleared: false,
      before_media_hint: beforeMediaHint,
      after_media_hint: beforeMediaHint,
      before_draft_hint: beforeDraftHint,
      after_draft_hint: beforeDraftHint,
      input_inspect: inputInspect,
      actions,
      before_url: before.url || "",
      after_url: before.url || "",
    };
  }
  const inputClearResult = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const allInputs = [...document.querySelectorAll("input[type=file]")].filter(visible);
    const candidateInputs = allInputs.filter((input) => {
      const accept = String(input.getAttribute("accept") || "").toLowerCase();
      return /video|mp4|media|octet|application|mpeg|quicktime/i.test(accept) || !/image|audio/i.test(accept) || !accept;
    });
    const clearEvents = (input) => {
      const hadValue = clean(input.value || input.getAttribute("value") || "");
      try {
        input.value = "";
      } catch {
        return { had_value: hadValue, cleared: false };
      }
      if (input.value) return { had_value: hadValue, cleared: false };
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return { had_value: hadValue, cleared: Boolean(hadValue) };
    };
    const results = [];
    for (const input of candidateInputs) {
      results.push({
        accept: clean(input.getAttribute("accept") || ""),
        visible: Boolean(visible(input)),
        had_files: input.files && input.files.length > 0,
        ...clearEvents(input),
      });
    }
    const clearedCount = results.filter((item) => item.cleared).length;
    return {
      input_count: allInputs.length,
      video_like_input_count: candidateInputs.length,
      cleared_count: clearedCount,
      results: results.slice(0, 6),
    };
  })()`, 12000).catch((error) => ({ cleared_count: 0, input_count: 0, video_like_input_count: 0, reason: "file_input_reset_failed", error: String(error?.message || error) }));
  actions.push({ kind: "draft_clear_file_inputs", ...inputClearResult });

  let clearButtonClicked = false;
  for (const texts of clearTextGroups) {
    if (!Array.isArray(texts) || texts.length === 0) continue;
    const clickResult = await evaluateWithClient(client, `(() => {
      const texts = ${JSON.stringify(texts)};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const roots = [];
      const visitRoot = (root) => {
        if (!root || roots.includes(root)) return;
        roots.push(root);
        for (const el of [...root.querySelectorAll("*")]) {
          if (el.shadowRoot) visitRoot(el.shadowRoot);
          if (el.tagName === "IFRAME") {
            try {
              if (el.contentDocument) visitRoot(el.contentDocument);
            } catch {}
          }
        }
      };
      visitRoot(document);
      const queryAll = (selector) => roots.flatMap((root) => {
        try {
          return [...root.querySelectorAll(selector)];
        } catch {
          return [];
        }
      });
      const candidates = queryAll("button,[role=button],a,[class*=button],.btn,input[type=button],input[type=submit],label")
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder"));
          const text = clean(el.textContent || "");
          const contextSource = [];
          let cursor = el.parentElement;
          for (let index = 0; index < 5 && cursor; index += 1) {
            contextSource.push(clean(cursor.innerText || ""));
            cursor = cursor.parentElement;
          }
          const context = clean(contextSource.join(" "));
          const match = texts.find((textCandidate) => label === textCandidate || label.startsWith(textCandidate) || label.includes(textCandidate));
          const contextHint = /上传|视频|草稿|素材|封面|作品|发布|compose|upload|media|draft/i.test(context) || /上传|视频|草稿|素材|封面|作品|发布|compose|upload|media|draft/i.test(text);
          return { el, label, text, rect, context, match, contextHint };
        })
        .filter((item) => item.match && item.contextHint && item.rect.width > 0 && item.rect.height > 0 && item.rect.width < 260000)
        .sort((left, right) => {
          if (left.label === right.label) return 0;
          return left.rect.width * left.rect.height - right.rect.width * right.rect.height;
        });
      if (!candidates.length) {
        return { clicked: false, match: texts[0] || "", candidates: 0, candidates_scanned: texts.length };
      }
      const target = candidates[0];
      target.el.scrollIntoView({ block: "center", inline: "center" });
      const clickEventInit = { bubbles: true, cancelable: true, view: window, clientX: target.rect.left + target.rect.width / 2, clientY: target.rect.top + target.rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        target.el.dispatchEvent(new MouseEvent(type, clickEventInit));
      }
      return { clicked: true, label: target.label, text: target.text, matched: target.match, context: target.context, area: target.rect.width * target.rect.height };
    })()`, 12000).catch((error) => ({ clicked: false, reason: "click_error", error: String(error?.message || error) }));
    actions.push({ kind: "draft_clear_click", ...clickResult, texts: texts.slice(0, 8) });
    if (clickResult.clicked) {
      clearButtonClicked = true;
      await sleep(1200);
      break;
    }
  }

  const after = await pageSnapshot(client).catch(() => ({}));
  const afterText = [...(after.lines || []), ...(after.headings || [])].map((line) => String(line || "").trim()).join(" ");
  const afterMediaHint = Boolean(mediaName && (afterText.includes(mediaName) || afterText.includes(mediaStem)));
  const afterDraftHint = /草稿|草稿箱|编辑失败|上传失败|Upload failed|Upload Failed|重新上传/.test(afterText);

  return {
    platform,
    attempted: true,
    skipped: false,
    stale_detected: staleDraftDetected,
    cleared: clearButtonClicked || inputClearResult.cleared_count > 0 || (beforeMediaHint && !afterMediaHint) || (beforeDraftHint && !afterDraftHint),
    before_media_hint: beforeMediaHint,
    after_media_hint: afterMediaHint,
    before_draft_hint: beforeDraftHint,
    after_draft_hint: afterDraftHint,
    input_inspect: inputInspect,
    actions,
    before_url: before.url || "",
    after_url: after.url || "",
  };
}

async function resolveCurrentPageDraftResumePrompt(client, platform) {
  const before = await pageSnapshot(client).catch(() => ({}));
  const beforeText = [...(before.lines || []), ...(before.headings || [])]
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .join(" ");
  if (
    String(platform || "").trim() === "youtube"
    && shouldPreserveYouTubeUploadResumeRoute(String(before.url || ""), beforeText)
  ) {
    return {
      attempted: false,
      resumed: true,
      prompt_present: false,
      reason: "youtube_upload_resume_surface",
      before_url: before.url || "",
      after_url: before.url || "",
      upload_dialog_surface: true,
    };
  }
  if (
    String(platform || "").trim() === "youtube"
    && hasYoutubeUploadResumeVideoId(String(before.url || ""))
  ) {
    const routeCandidate = await resolveYouTubeDraftEditorRoute(client).catch(() => ({}));
    const editorTarget = String(routeCandidate?.edit_url || "").trim();
    if (editorTarget && editorTarget !== String(before.url || "").trim()) {
      await evaluateWithClient(client, `(() => {
        location.href = ${JSON.stringify(editorTarget)};
        return { navigated: true, target: ${JSON.stringify(editorTarget)} };
      })()`, 10000).catch(() => null);
      await sleep(2600);
      const afterEditorBootstrap = await pageSnapshot(client).catch(() => ({}));
      const afterEditorBootstrapText = [...(afterEditorBootstrap.lines || []), ...(afterEditorBootstrap.headings || [])]
        .map((line) => String(line || "").trim())
        .filter(Boolean)
        .join(" ");
      const editorAdvanced =
        /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(String(afterEditorBootstrap.url || ""))
        || /视频详细信息|Video details/i.test(afterEditorBootstrapText)
        || /标题（必填）|说明|缩略图|播放列表/.test(afterEditorBootstrapText);
      if (editorAdvanced || shouldPreserveYouTubeUploadResumeRoute(String(afterEditorBootstrap.url || ""), afterEditorBootstrapText)) {
        return {
          attempted: true,
          resumed: true,
          prompt_present: false,
          reason: "youtube_upload_resume_editor_bootstrap",
          before_url: before.url || "",
          after_url: afterEditorBootstrap.url || before.url || "",
          route_bootstrap_target: editorTarget,
          route_bootstrap_changed: true,
          upload_dialog_surface: shouldPreserveYouTubeUploadResumeRoute(String(afterEditorBootstrap.url || ""), afterEditorBootstrapText),
          after_lines: (afterEditorBootstrap.lines || []).slice(0, 40),
        };
      }
    }
  }
  if (
    String(platform || "").trim() === "youtube"
    && /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(String(before.url || ""))
  ) {
    return {
      attempted: false,
      resumed: true,
      prompt_present: false,
      reason: "youtube_editor_surface",
      before_url: before.url || "",
      after_url: before.url || "",
    };
  }
  const disposition = deriveCurrentPageDraftResumeDisposition(platform, beforeText);
  if (!disposition.present) {
    return {
      attempted: false,
      resumed: false,
      prompt_present: false,
      reason: "no_resume_prompt",
      before_url: before.url || "",
      after_url: before.url || "",
    };
  }
  if (String(platform || "").trim() === "youtube" && disposition.reason === "uploaded_draft_row") {
    let resume = await clickYouTubeDraftResumeEntry(client, "").catch(() => ({ clicked: false }));
    if (!resume.clicked) resume = await clickByText(client, [disposition.resume_label]);
    if (!resume.clicked) resume = await clickLooseText(client, [disposition.resume_label]);
    await sleep(1200);
    const after = await pageSnapshot(client).catch(() => ({}));
    const afterText = [...(after.lines || []), ...(after.headings || [])]
      .map((line) => String(line || "").trim())
      .filter(Boolean)
      .join(" ");
    const afterDisposition = deriveCurrentPageDraftResumeDisposition(platform, afterText);
    const youtubeUploadDialogResumed = shouldPreserveYouTubeUploadResumeRoute(String(after.url || ""), afterText);
    const editorAdvanced =
      /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(String(after.url || ""))
      || /视频详细信息|Video details/i.test(afterText)
      || /标题（必填）|说明|缩略图|播放列表/.test(afterText);
    const attemptResult = {
      attempted: true,
      resumed: Boolean(resume.clicked) && (!afterDisposition.present || youtubeUploadDialogResumed || editorAdvanced),
      prompt_present: true,
      prompt_still_open: afterDisposition.present,
      reason: disposition.reason,
      resume_label: disposition.resume_label,
      before_url: before.url || "",
      after_url: after.url || before.url || "",
      clicked_label: resume.clicked_label || resume.label || "",
      upload_dialog_surface: youtubeUploadDialogResumed,
      before_lines: (before.lines || []).slice(0, 40),
      after_lines: (after.lines || []).slice(0, 40),
    };
    if (attemptResult.resumed) return attemptResult;
    const directResumeTarget = deriveYouTubeDraftResumeFallbackTarget(resume, String(after.url || before.url || ""));
    if (directResumeTarget.target) {
      await evaluateWithClient(client, `(() => {
        location.href = ${JSON.stringify(directResumeTarget.target)};
        return { navigated: true, target: ${JSON.stringify(directResumeTarget.target)} };
      })()`, 10000).catch(() => null);
      await sleep(2600);
      const afterDirectResume = await pageSnapshot(client).catch(() => ({}));
      const afterDirectResumeText = [...(afterDirectResume.lines || []), ...(afterDirectResume.headings || [])]
        .map((line) => String(line || "").trim())
        .filter(Boolean)
        .join(" ");
      const afterDirectDisposition = deriveCurrentPageDraftResumeDisposition(platform, afterDirectResumeText);
      const youtubeUploadDialogDirect = shouldPreserveYouTubeUploadResumeRoute(String(afterDirectResume.url || ""), afterDirectResumeText);
      const editorAdvancedDirect =
        /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(String(afterDirectResume.url || ""))
        || /视频详细信息|Video details/i.test(afterDirectResumeText)
        || /标题（必填）|说明|缩略图|播放列表/.test(afterDirectResumeText);
      if (youtubeUploadDialogDirect || editorAdvancedDirect) {
        return {
          ...attemptResult,
          resumed: true,
          prompt_still_open: afterDirectDisposition.present,
          after_url: afterDirectResume.url || attemptResult.after_url || before.url || "",
          upload_dialog_surface: youtubeUploadDialogDirect,
          direct_resume_target: directResumeTarget.target,
          direct_resume_reason: directResumeTarget.reason,
          after_lines: (afterDirectResume.lines || []).slice(0, 40),
        };
      }
    }
    const routeBootstrap = await ensureYoutubeUploadEditor(client, "").catch(() => ({ matched: false, changed: false }));
    if (!routeBootstrap?.changed) return attemptResult;
    await sleep(2600);
    const afterBootstrap = await pageSnapshot(client).catch(() => ({}));
    const afterBootstrapText = [...(afterBootstrap.lines || []), ...(afterBootstrap.headings || [])]
      .map((line) => String(line || "").trim())
      .filter(Boolean)
      .join(" ");
    const afterBootstrapDisposition = deriveCurrentPageDraftResumeDisposition(platform, afterBootstrapText);
    const youtubeUploadDialogBootstrap = shouldPreserveYouTubeUploadResumeRoute(String(afterBootstrap.url || ""), afterBootstrapText);
    const editorAdvancedBootstrap =
      /\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(String(afterBootstrap.url || ""))
      || /视频详细信息|Video details/i.test(afterBootstrapText)
      || /标题（必填）|说明|缩略图|播放列表/.test(afterBootstrapText);
    return {
      ...attemptResult,
      resumed: youtubeUploadDialogBootstrap || editorAdvancedBootstrap,
      prompt_still_open: afterBootstrapDisposition.present,
      after_url: afterBootstrap.url || attemptResult.after_url || before.url || "",
      upload_dialog_surface: youtubeUploadDialogBootstrap,
      route_bootstrap_target: String(routeBootstrap?.target || ""),
      route_bootstrap_changed: true,
      after_lines: (afterBootstrap.lines || []).slice(0, 40),
    };
  }
  let clickResult = await clickDraftResumePromptAction(client, disposition);
  await sleep(1200);
  const after = await pageSnapshot(client).catch(() => ({}));
  const afterText = [...(after.lines || []), ...(after.headings || [])]
    .map((line) => String(line || "").trim())
    .filter(Boolean)
    .join(" ");
  const afterDisposition = deriveCurrentPageDraftResumeDisposition(platform, afterText);
  const youtubeUploadDialogResumed =
    String(platform || "").trim() === "youtube"
    && shouldPreserveYouTubeUploadResumeRoute(String(after.url || ""), afterText);
  const clickedLabel = String(clickResult.clicked_label || clickResult.label || "").trim();
  const discarded = disposition.preferred_action === "discard"
    && Boolean(clickResult.clicked)
    && !afterDisposition.present
    && (!disposition.discard_label || clickedLabel !== disposition.resume_label);
  return {
    attempted: true,
    resumed: Boolean(clickResult.clicked) && (!afterDisposition.present || youtubeUploadDialogResumed),
    discarded,
    prompt_present: true,
    prompt_still_open: afterDisposition.present,
    reason: disposition.reason,
    resume_label: disposition.resume_label,
    discard_label: disposition.discard_label,
    preferred_action: disposition.preferred_action,
    before_url: before.url || "",
    after_url: after.url || before.url || "",
    clicked_label: clickedLabel,
    upload_dialog_surface: youtubeUploadDialogResumed,
    before_lines: (before.lines || []).slice(0, 40),
    after_lines: (after.lines || []).slice(0, 40),
  };
}

async function snapshotTab(tab) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    return await pageSnapshot(client, {
      captureVisualEvidence: true,
      visualEvidencePhase: "tab_snapshot",
    });
  } finally {
    client.close();
  }
}

function originFromUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    return parsed.origin;
  } catch {
    return "";
  }
}

async function setOriginNotificationPermission(client, tab) {
  const origin = originFromUrl(tab?.url);
  if (!origin) return { handled: false, reason: "missing_origin" };
  try {
    await client.send("Browser.setPermission", {
      permission: { name: "notifications" },
      setting: "denied",
      origin,
    });
    return { handled: true, kind: "notification_permission", origin, setting: "denied" };
  } catch (error) {
    return { handled: false, kind: "notification_permission", origin, reason: error.message };
  }
}

async function dismissInterruptions(client, tab, platform, stage = "unspecified") {
  const actions = [];
  const permission = await setOriginNotificationPermission(client, tab);
  if (permission.handled) actions.push({ ...permission, stage });

  const expression = `(() => {
    const safeTexts = ${JSON.stringify(SAFE_DISMISS_TEXTS)};
    const dangerousPattern = ${DANGEROUS_ACTION_RE.toString()};
    const platform = ${JSON.stringify(platform)};
    const stage = ${JSON.stringify(stage)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity || 1) !== 0;
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const overlays = queryAll([
      "[role=dialog]",
      "[aria-modal=true]",
      ".modal",
      ".dialog",
      ".popover",
      ".drawer",
      ".mask",
      ".toast",
      ".survey",
      "[class*=modal i]",
      "[class*=dialog i]",
      "[class*=popover i]",
      "[class*=mask i]",
      "[class*=survey i]",
      "[class*=notice i]",
      "[class*=tooltip i]",
      "[class*=guide i]",
      "[class*=alert i]",
    ].join(",")).filter(visible);
    const overlaySet = new Set(overlays);
    const isInsideOverlay = (el) => overlays.some((overlay) => overlay === el || overlay.contains(el));
    const labelOf = (el) => clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("placeholder"));
    const classOf = (el) => clean(el.className && typeof el.className === "string" ? el.className : "");
    const looksLikeCloseIcon = (el, label) => {
      const cls = classOf(el).toLowerCase();
      const aria = clean(el.getAttribute("aria-label")).toLowerCase();
      const title = clean(el.getAttribute("title")).toLowerCase();
      return ["×", "x", "X", "✕", "关闭"].includes(label) || /close|cancel|dismiss/.test(cls) || /close|关闭|dismiss|cancel/.test(aria) || /close|关闭|dismiss|cancel/.test(title);
    };
    const isSafeLabel = (label) => {
      if (!label || label.length > 80) return false;
      if (dangerousPattern.test(label)) return false;
      return safeTexts.some((text) => label === text || label.startsWith(text) || label.includes(text));
    };
    const clickableSelector = "button,[role=button],a,input[type=button],input[type=submit],[aria-label],[title],[class*=close i],[class*=cancel i],[class*=dismiss i]";
    const candidates = queryAll(clickableSelector)
      .filter(visible)
      .filter((el) => overlaySet.has(el) || isInsideOverlay(el))
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const label = labelOf(el);
        return { el, label, area: rect.width * rect.height };
      })
      .filter((item) => item.area > 0 && item.area < 180000)
      .sort((left, right) => {
        const leftClose = looksLikeCloseIcon(left.el, left.label) ? 0 : 1;
        const rightClose = looksLikeCloseIcon(right.el, right.label) ? 0 : 1;
        return leftClose - rightClose || left.area - right.area;
      });
    const clicked = [];
    for (const item of candidates) {
      const label = item.label;
      if (!isSafeLabel(label) && !looksLikeCloseIcon(item.el, label)) continue;
      if (dangerousPattern.test(label)) continue;
      item.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = item.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        item.el.dispatchEvent(new MouseEvent(type, eventInit));
      }
      clicked.push({
        kind: "dom_popup_dismissed",
        label: label || clean(item.el.getAttribute("aria-label")) || clean(item.el.getAttribute("title")) || "icon_close",
        platform,
        stage,
      });
      break;
    }
    return { clicked };
  })()`;
  const domResult = await evaluateWithClient(client, expression, 10000);
  actions.push(...(domResult.clicked || []));
  return actions;
}

function mergedSnapshot(snapshots) {
  const lines = [];
  const headings = [];
  const elements = [];
  const fileInputs = [];
  const seenLines = new Set();
  const seenHeadings = new Set();
  const seenElements = new Set();
  let lastVisualEvidence = null;
  for (const snapshot of snapshots.filter(Boolean)) {
    for (const line of snapshot.lines || []) {
      const text = String(line || "").trim();
      const key = text.toLowerCase();
      if (!text || seenLines.has(key)) continue;
      seenLines.add(key);
      lines.push(text);
    }
    for (const heading of snapshot.headings || []) {
      const text = String(heading || "").trim();
      const key = text.toLowerCase();
      if (!text || seenHeadings.has(key)) continue;
      seenHeadings.add(key);
      headings.push(text);
    }
    for (const element of snapshot.elements || []) {
      const text = `${element.tag}|${element.role}|${element.type}|${element.text}|${element.ariaLabel}|${element.placeholder}`;
      const key = text.toLowerCase();
      if (seenElements.has(key)) continue;
      seenElements.add(key);
      elements.push(element);
    }
    for (const overlayText of snapshot.overlayTexts || []) {
      const text = String(overlayText || "").trim();
      for (const line of text.split(/[\n\r]+/).flatMap((line) => String(line).split(/ {2,}/))) {
        const normalized = line.trim();
        const key = normalized.toLowerCase();
        if (!normalized || seenLines.has(key)) continue;
        seenLines.add(key);
        lines.push(normalized);
      }
    }
    for (const input of snapshot.fileInputs || []) fileInputs.push(input);
    if (snapshot.visual_evidence && typeof snapshot.visual_evidence === "object") {
      lastVisualEvidence = normalizeVisualEvidence(snapshot.visual_evidence);
    }
  }
  const last = snapshots.filter(Boolean).at(-1) || {};
  return {
    url: last.url,
    title: last.title,
    lines: lines.slice(0, 2200),
    headings: headings.slice(0, 260),
    elements: elements.slice(0, 900),
    fileInputs,
    visual_evidence: lastVisualEvidence,
  };
}

function pageAlreadyHasMedia(snapshot, mediaPath) {
  const name = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  if (!name) return false;
  const stem = name.replace(/\.[^.]+$/, "");
  const text = [...(snapshot.lines || []), ...((snapshot.elements || []).map((element) => element.text || ""))].join(" ");
  if (/上传失败|Upload failed|重新上传/.test(text)) return false;
  return text.includes(name) || text.includes(stem);
}

async function pageAlreadyHasMediaLive(client, mediaPath) {
  const name = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  if (!name) return { present: false, reason: "missing_media_name" };
  const stem = name.replace(/\.[^.]+$/, "");
  return evaluateWithClient(client, `(() => {
    const expected = ${JSON.stringify({ name, stem })};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const failed = /上传失败|Upload failed|刷新后重试|网络异常/.test(text);
    const present = !failed && (text.includes(expected.name) || text.includes(expected.stem));
    return { present, failed, name: expected.name, upload_busy: /上传中|正在上传|视频处理中|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%/.test(text) };
  })()`, 10000);
}

export function compositeRequiresLocalMedia(platform, content = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const publicationCapability = content?.publication_capability && typeof content.publication_capability === "object"
    ? content.publication_capability
    : {};
  if (typeof publicationCapability.requires_local_media === "boolean") {
    return publicationCapability.requires_local_media;
  }
  const platformOverrides = content?.platform_specific_overrides && typeof content.platform_specific_overrides === "object"
    ? content.platform_specific_overrides
    : {};
  const xShareLink = String(platformOverrides.x_share_link || platformOverrides.x_share_url || "").trim();
  if (normalizedPlatform === "x" && xShareLink) return false;
  return normalizedPlatform !== "x";
}

export function canReuseCurrentPageMediaForPrepublish(platform, snapshot = {}, mediaPath = "", options = {}) {
  if (options?.requiresLocalMedia === false) {
    return { reusable: true, reason: "local_media_not_required" };
  }
  if (mediaPath && pageAlreadyHasMedia(snapshot, mediaPath)) {
    return { reusable: true, reason: "media_path_match" };
  }
  const normalizedLines = Array.isArray(snapshot?.lines) ? snapshot.lines.map((line) => String(line || "").trim()).filter(Boolean) : [];
  const text = [...normalizedLines, ...((snapshot?.elements || []).map((element) => String(element?.text || "").trim()).filter(Boolean))]
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
  const mediaName = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  const mediaStem = mediaName.replace(/\.[^.]+$/, "");
  const signals = detectCompositePublicationSignals(platform, text, normalizedLines);
  if (signals.upload_failed) {
    return { reusable: false, reason: "upload_failed" };
  }
  if (platform === "youtube" && shouldPreserveYouTubeUploadResumeRoute(String(snapshot?.url || ""), text)) {
    return { reusable: true, reason: "youtube_upload_resume_surface" };
  }
  if (
    platform === "youtube"
    && /studio\.youtube\.com\/channel\/[^/?#]+\/(?:videos\/)?upload/i.test(String(snapshot?.url || ""))
    && /草稿|Draft/i.test(text)
    && /编辑草稿|Edit draft/i.test(text)
  ) {
    return { reusable: true, reason: "youtube_uploaded_draft_row" };
  }
  if (platform === "douyin") {
    const douyinReadySurface = /预览视频|预览封面\/标题|重新上传|极速上传成功/.test(text)
      && /作品描述|发布时间|发布设置/.test(text);
    if (douyinReadySurface) {
      return { reusable: true, reason: "douyin_ready_surface" };
    }
  }
  if (platform === "bilibili") {
    const bilibiliEditorSurface = /更换视频|上传完成|已经上传：|当前速度：|剩余时间：/.test(text)
      && /标题|简介|分区|标签|创作声明|定时发布|立即投稿|存草稿/.test(text);
    if (bilibiliEditorSurface) {
      return { reusable: true, reason: "bilibili_editor_surface" };
    }
  }
  if (signals.upload_prompt_only) {
    return { reusable: false, reason: "upload_prompt_only" };
  }
  return { reusable: false, reason: "media_presence_unconfirmed" };
}

export function deriveCompositeCurrentPageMediaPendingDisposition(platform, mediaPath = "", mediaState = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const reason = String(mediaState?.reason || "").trim();
  const hasMediaPath = Boolean(String(mediaPath || "").trim());
  if (!hasMediaPath || reason === "missing_media_path") {
    return {
      pending: false,
      status: "needs_human",
      code: `${normalizedPlatform}_prepublish_only_media_missing`,
      wait_for_upload_ready: false,
      remaining: ["upload_ready"],
      media_reuse_reason: reason || "missing_media_path",
    };
  }
  if (reason === "upload_failed") {
    return {
      pending: false,
      status: "needs_human",
      code: `${normalizedPlatform}_prepublish_only_media_missing`,
      wait_for_upload_ready: false,
      remaining: ["upload_ready"],
      media_reuse_reason: reason,
    };
  }
  if (reason === "upload_prompt_only" || reason === "media_presence_unconfirmed") {
    return {
      pending: true,
      status: "processing",
      code: `${normalizedPlatform}_pre_publish_upload_pending`,
      wait_for_upload_ready: true,
      remaining: ["upload_ready"],
      media_reuse_reason: reason,
    };
  }
  return {
    pending: false,
    status: "needs_human",
    code: `${normalizedPlatform}_prepublish_only_media_missing`,
    wait_for_upload_ready: false,
    remaining: ["upload_ready"],
    media_reuse_reason: reason || "media_presence_unconfirmed",
  };
}

export function shouldBootstrapStopBeforeMediaUpload(platform, mediaPath = "", mediaState = {}, options = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const hasMediaPath = Boolean(String(mediaPath || "").trim());
  const reason = String(mediaState?.reason || "").trim();
  const stopBeforeFinalPublish = Boolean(options?.stopBeforeFinalPublish);
  const requiresLocalMedia = Boolean(options?.requiresLocalMedia);
  const verifyMediaUpload = options?.verifyMediaUpload !== false;
  if (!stopBeforeFinalPublish || !verifyMediaUpload || !requiresLocalMedia || !hasMediaPath) return false;
  if (["upload_prompt_only", "media_presence_unconfirmed"].includes(reason)) return true;
  if (normalizedPlatform === "youtube" && reason === "missing_media_path") return false;
  return false;
}

export function shouldBootstrapStopBeforeMediaRouteRecovery(platform, snapshot = {}, mediaState = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const reason = String(mediaState?.reason || "").trim();
  const routeUrl = String(snapshot?.url || "").trim();
  if (normalizedPlatform !== "youtube") return false;
  if (reason !== "media_presence_unconfirmed") return false;
  if (!/studio\.youtube\.com\/channel\/[^/?#]+\/(?:videos\/)?upload/i.test(routeUrl)) return false;
  if (hasYoutubeUploadResumeVideoId(routeUrl)) return false;
  return true;
}

export function shouldAttemptMediaBootstrap({
  stopBeforeFinalPublish = false,
  prepublishOnlyCurrentPage = false,
  forceMediaUpload = false,
  stopBeforeUploadBootstrap = false,
  mediaAlreadyPresent = false,
  pageHasMedia = false,
  hasMediaPath = false,
} = {}) {
  if (!hasMediaPath) return false;
  if (stopBeforeFinalPublish) {
    return Boolean(forceMediaUpload || stopBeforeUploadBootstrap || !mediaAlreadyPresent);
  }
  return Boolean(forceMediaUpload || (!prepublishOnlyCurrentPage && !pageHasMedia));
}

export function deriveCurrentPageDraftResumeDisposition(platform, text = "") {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const haystack = String(text || "").replace(/\s+/g, " ").trim();
  if (!haystack) return { present: false, resume_label: "", discard_label: "", preferred_action: "", reason: "" };
  if (
    normalizedPlatform === "youtube"
    && /频道内容|channel content/i.test(haystack)
    && /草稿|draft/i.test(haystack)
    && /编辑草稿|edit draft/i.test(haystack)
  ) {
    return {
      present: true,
      resume_label: /编辑草稿/.test(haystack) ? "编辑草稿" : "Edit draft",
      discard_label: "",
      preferred_action: "resume",
      reason: "uploaded_draft_row",
    };
  }
  const resumePromptPattern = /还有上次未发布的视频|上次未发布的(?:视频|作品)|未发布的视频[,，。 ]*是否继续编辑|继续编辑放弃|本地浏览器存在\s*\d+\s*个未提交的(?:视频|作品)|未提交的(?:视频|作品)/;
  const hasResumeAction = /继续编辑|编辑作品|回到编辑/.test(haystack);
  if (!resumePromptPattern.test(haystack) || !hasResumeAction) {
    return { present: false, resume_label: "", discard_label: "", preferred_action: "", reason: "" };
  }
  if (!["bilibili", "kuaishou"].includes(normalizedPlatform)) {
    return { present: false, resume_label: "", discard_label: "", preferred_action: "", reason: "" };
  }
  const discardLabel = /不用了/.test(haystack)
    ? "不用了"
    : (/不需要/.test(haystack)
      ? "不需要"
      : (/放弃/.test(haystack)
        ? "放弃"
        : (/重新开始/.test(haystack)
          ? "重新开始"
          : "")));
  return {
    present: true,
    resume_label: /继续编辑/.test(haystack) ? "继续编辑" : (/编辑作品/.test(haystack) ? "编辑作品" : "回到编辑"),
    discard_label: discardLabel,
    preferred_action: "discard",
    reason: "existing_unpublished_draft_prompt",
  };
}

async function clickDraftResumePromptAction(client, disposition) {
  const preferredLabels = disposition?.preferred_action === "discard"
    ? [disposition?.discard_label, ...DRAFT_RESUME_DISMISS_TEXTS]
    : [disposition?.resume_label];
  const fallbackLabels = disposition?.preferred_action === "discard"
    ? []
    : [disposition?.discard_label, ...DRAFT_RESUME_DISMISS_TEXTS];
  const preferred = preferredLabels.map((item) => String(item || "").trim()).filter(Boolean);
  const fallback = fallbackLabels.map((item) => String(item || "").trim()).filter(Boolean);
  let clickResult = preferred.length ? await clickByText(client, preferred) : { clicked: false };
  if (!clickResult.clicked && preferred.length) {
    clickResult = await clickLooseText(client, preferred);
  }
  if (!clickResult.clicked && fallback.length) {
    clickResult = await clickByText(client, fallback);
  }
  if (!clickResult.clicked && fallback.length) {
    clickResult = await clickLooseText(client, fallback);
  }
  return clickResult;
}

export function extractYouTubeDraftVideoId(routeUrl = "", watchUrl = "") {
  const candidates = [routeUrl, watchUrl]
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  for (const candidate of candidates) {
    const routeMatch = candidate.match(/[?&]udvid=([A-Za-z0-9_-]{6,})/i);
    if (routeMatch?.[1]) return routeMatch[1];
    const watchMatch = candidate.match(/[?&]v=([A-Za-z0-9_-]{6,})/i);
    if (watchMatch?.[1]) return watchMatch[1];
    const shortLinkMatch = candidate.match(/youtu\.be\/([A-Za-z0-9_-]{6,})(?:[/?#]|$)/i);
    if (shortLinkMatch?.[1]) return shortLinkMatch[1];
    const editorMatch = candidate.match(/\/video\/([A-Za-z0-9_-]{6,})\/edit\b/i);
    if (editorMatch?.[1]) return editorMatch[1];
  }
  return "";
}

export function selectYouTubeDraftResumeCandidate(candidates = [], titleHint = "") {
  const clean = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const hintValues = Array.isArray(titleHint) ? titleHint : [titleHint];
  const matchesHint = typeof matchesYouTubeDraftResumeHint === "function"
    ? matchesYouTubeDraftResumeHint
    : (rowText = "", hints = []) => {
      const normalizeHint = (value = "") => String(value || "")
        .toLowerCase()
        .replace(/\s+/g, "")
        .replace(/[｜|:：!！,，.。?？'"\-—_()/\\[\]【】]/g, "")
        .trim();
      const normalizedRow = normalizeHint(rowText);
      if (!normalizedRow) return false;
      const values = Array.isArray(hints) ? hints : [hints];
      return values
        .map((value) => normalizeHint(value))
        .filter(Boolean)
        .some((normalizedHint) => normalizedRow.includes(normalizedHint));
    };
  const rows = Array.isArray(candidates)
    ? candidates
      .map((candidate) => ({
        text: clean(candidate?.text || candidate?.rowText || ""),
        watchHref: String(candidate?.watchHref || candidate?.watch_url || "").trim(),
        titleHref: String(candidate?.titleHref || candidate?.title_url || "").trim(),
      }))
      .filter((candidate) => /草稿|Draft/i.test(candidate.text) && /编辑草稿|Edit draft/i.test(candidate.text))
    : [];
  const preferredRows = hintValues.some((value) => String(value || "").trim())
    ? rows.filter((candidate) => matchesHint(candidate.text, hintValues))
    : rows;
  const pool = preferredRows.length > 0 ? preferredRows : rows;
  for (const candidate of pool) {
    const videoId = extractYouTubeDraftVideoId(candidate.watchHref, candidate.titleHref || candidate.watchHref);
    if (videoId) {
      return {
        ...candidate,
        videoId,
      };
    }
  }
  return {
    text: preferredRows[0]?.text || rows[0]?.text || "",
    watchHref: preferredRows[0]?.watchHref || rows[0]?.watchHref || "",
    titleHref: preferredRows[0]?.titleHref || rows[0]?.titleHref || "",
    videoId: "",
  };
}

export function buildYouTubeStudioEditorUrl(videoId = "") {
  const normalized = String(videoId || "").trim();
  if (!normalized) return "";
  return `https://studio.youtube.com/video/${normalized}/edit`;
}

export function deriveYouTubeStudioReceiptBinding(integrity = {}, finalPublish = {}) {
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || finalPublish?.route?.url
    || "",
  ).trim();
  const youtubeReceipt = String(
    integrity?.platform_extras?.youtube_link
    || finalPublish?.external_url
    || "",
  ).trim();
  const routeVideoId = extractYouTubeDraftVideoId(routeUrl, "");
  const receiptVideoId = extractYouTubeDraftVideoId("", youtubeReceipt);
  if (!routeVideoId && !receiptVideoId && !youtubeReceipt) {
    return {};
  }
  const binding = {
    receipt_like: true,
    post_publish_surface: "youtube_studio_editor_receipt",
    youtube_editor_video_id: routeVideoId,
    youtube_receipt_video_id: receiptVideoId,
  };
  if (routeVideoId && receiptVideoId && routeVideoId === receiptVideoId) {
    return {
      ...binding,
      receipt_target_bound: true,
      receipt_binding_source: "youtube_studio_editor_link",
    };
  }
  return {
    ...binding,
    receipt_target_bound: false,
    receipt_binding_source: "youtube_studio_receipt_unbound",
  };
}

export function deriveYouTubeDraftResumeFallbackTarget(resume = {}, currentUrl = "") {
  const current = String(currentUrl || "").trim();
  const uploadResumeUrl = String(resume?.upload_resume_url || "").trim();
  const editUrl = String(resume?.edit_url || "").trim();
  if (uploadResumeUrl && uploadResumeUrl !== current) {
    return { target: uploadResumeUrl, reason: "upload_resume_url" };
  }
  if (editUrl && editUrl !== current) {
    return { target: editUrl, reason: "edit_url" };
  }
  return { target: "", reason: "" };
}

export function shouldAttemptYouTubeDraftResumeFallbackRoute(readiness = {}, resume = {}) {
  const state = readiness && typeof readiness === "object" ? readiness : {};
  const last = state.last && typeof state.last === "object" ? state.last : {};
  if (String(last.platform || "").trim() !== "youtube") return false;
  if (state.ready || state.failed || last.busy) return false;
  const onUploadResumeRoute = Boolean(last.youtubeUploadDialogRoute);
  if (!last.youtubeUploadRoute || last.youtubeHasEditorSurface) return false;
  if (!last.youtubeChannelContentList && !onUploadResumeRoute) return false;
  if (!last.mediaPresent && (!onUploadResumeRoute || last.uploadPromptOnly)) return false;
  const fallback = deriveYouTubeDraftResumeFallbackTarget(resume, String(last.href || ""));
  return Boolean(fallback.target);
}

export function buildYouTubeUploadResumeUrl(currentHref = "", videoId = "") {
  const current = String(currentHref || "").trim();
  const normalizedVideoId = String(videoId || "").trim();
  if (!normalizedVideoId) return "";
  try {
    const parsed = new URL(current);
    if (!/studio\.youtube\.com$/i.test(parsed.hostname)) return "";
    if (!/\/channel\/[^/?#]+\/(?:videos\/)?upload\b/i.test(parsed.pathname)) return "";
    parsed.searchParams.set("d", "ud");
    parsed.searchParams.set("udvid", normalizedVideoId);
    return parsed.toString();
  } catch {
    return "";
  }
}

async function resolveYouTubeDraftEditorRoute(client) {
  const routeCandidate = await evaluateWithClient(client, `(() => {
    const currentHref = String(location.href || "");
    const watchHref =
      document.querySelector("#anchor-watch-on-yt")?.href
      || document.querySelector("a[href*='watch?v=']")?.href
      || "";
    const titleHref =
      document.querySelector("#video-title")?.href
      || document.querySelector("a#video-title")?.getAttribute("href")
      || "";
    return {
      currentHref,
      watchHref,
      titleHref,
    };
  })()`, 12000).catch(() => ({}));
  const videoId = extractYouTubeDraftVideoId(
    String(routeCandidate?.currentHref || ""),
    String(routeCandidate?.watchHref || ""),
  );
  return {
    video_id: videoId,
    current_href: String(routeCandidate?.currentHref || ""),
    watch_href: String(routeCandidate?.watchHref || ""),
    title_href: String(routeCandidate?.titleHref || ""),
    upload_resume_url: buildYouTubeUploadResumeUrl(
      String(routeCandidate?.currentHref || ""),
      videoId,
    ),
    edit_url: buildYouTubeStudioEditorUrl(videoId),
  };
}

async function clickYouTubeDraftResumeEntry(client, titleHints = []) {
  const snapshot = await evaluateWithClient(client, `(() => {
    const titleHints = ${JSON.stringify((Array.isArray(titleHints) ? titleHints : [titleHints]).map((value) => String(value || "").trim()).filter(Boolean))};
    const extractYouTubeDraftVideoId = ${extractYouTubeDraftVideoId.toString()};
    const buildUploadResumeUrl = ${buildYouTubeUploadResumeUrl.toString()};
    const buildEditorUrl = ${buildYouTubeStudioEditorUrl.toString()};
    const normalizeHint = ${normalizeYouTubeDraftResumeHintText.toString()};
    const matchesHint = ${matchesYouTubeDraftResumeHint.toString()};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const rowElements = [...document.querySelectorAll("ytcp-video-row,[role=row],div")]
      .map((el) => ({ el, text: clean(el.innerText || el.textContent || "") }))
      .filter((item) => /草稿|Draft/.test(item.text) && /编辑草稿|Edit draft/.test(item.text))
      .slice(0, 24);
    const rows = rowElements.map((item) => {
      const watchAnchor = item.el.querySelector("a#anchor-watch-on-yt,a[href*='watch?v=']");
      const titleAnchor = item.el.querySelector("#video-title,a#video-title,a[href*='/video/'][href*='/edit']");
      const watchHref = String(watchAnchor?.href || watchAnchor?.getAttribute?.("href") || "").trim();
      const titleHref = String(titleAnchor?.href || titleAnchor?.getAttribute?.("href") || "").trim();
      const videoId = extractYouTubeDraftVideoId(watchHref, titleHref || String(location.href || ""));
      const targets = [...item.el.querySelectorAll("button,[role=button],a,ytcp-button,ytcp-icon-button")]
        .filter(visible)
        .map((target) => {
          const rect = target.getBoundingClientRect();
          return {
            tag: String(target.tagName || "").toLowerCase(),
            target_id: String(target.id || ""),
            label: clean(target.innerText || target.textContent || target.getAttribute("aria-label") || target.getAttribute("title")),
            role: String(target.getAttribute("role") || ""),
            x: rect.left + rect.width / 2,
            y: rect.top + rect.height / 2,
            width: rect.width,
            height: rect.height,
            visible: true,
          };
        })
        .filter((candidate) => /编辑草稿|Edit draft|详细信息|Details/i.test(candidate.label) || candidate.target_id === "video-title");
      return {
        row_text: item.text.slice(0, 800),
        row_role: String(item.el.getAttribute("role") || item.el.tagName || "").toLowerCase(),
        hint_match: matchesHint(item.text, titleHints),
        watch_href: watchHref,
        title_href: titleHref,
        video_id: videoId,
        upload_resume_url: buildUploadResumeUrl(String(location.href || ""), videoId),
        edit_url: buildEditorUrl(videoId),
        targets,
      };
    }).filter((row) => row.targets.length > 0);
    const matchingRows = rows.filter((row) => row.hint_match);
    return {
      href: String(location.href || ""),
      rows: matchingRows.length > 0 ? matchingRows : rows,
    };
  })()`, 12000);
  const chosen = selectYouTubeDraftResumeEntryCandidate(
    (snapshot?.rows || []).flatMap((row) => (row.targets || []).map((target) => ({
      ...target,
      row_text: row.row_text,
      row_role: row.row_role,
      watch_href: row.watch_href,
      title_href: row.title_href,
      video_id: row.video_id,
      upload_resume_url: row.upload_resume_url,
      edit_url: row.edit_url,
    }))),
  );
  if (!chosen) {
    return {
      clicked: false,
      reason: "youtube_draft_resume_entry_not_found",
      href: String(snapshot?.href || ""),
      rows: (snapshot?.rows || []).slice(0, 8),
    };
  }
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: chosen.x, y: chosen.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: chosen.x, y: chosen.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: chosen.x, y: chosen.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1800);
  return {
    clicked: true,
    label: chosen.label,
    tag: chosen.tag,
    target_id: chosen.target_id,
    row_text: chosen.row_text,
    input_click: { x: chosen.x, y: chosen.y },
    href: String(snapshot?.href || ""),
    watch_href: String(chosen.watch_href || ""),
    title_href: String(chosen.title_href || ""),
    video_id: String(chosen.video_id || ""),
    upload_resume_url: String(chosen.upload_resume_url || ""),
    edit_url: String(chosen.edit_url || ""),
  };
}

async function stabilizeCurrentPageMediaStateForPrepublish(client, platform, snapshot, mediaPath, options = {}) {
  const requiresLocalMedia = options?.requiresLocalMedia !== false;
  let currentSnapshot = snapshot;
  let mediaState = canReuseCurrentPageMediaForPrepublish(platform, currentSnapshot, mediaPath, { requiresLocalMedia });
  if (!requiresLocalMedia || !String(mediaPath || "").trim()) {
    return { snapshot: currentSnapshot, mediaState, waited_ms: 0 };
  }
  if (mediaState.reusable || !["upload_prompt_only", "media_presence_unconfirmed"].includes(String(mediaState.reason || "").trim())) {
    return { snapshot: currentSnapshot, mediaState, waited_ms: 0 };
  }
  const waitMs = Number(options?.waitMs || 5000);
  const startedAt = Date.now();
  while (Date.now() - startedAt < waitMs) {
    await sleep(1200);
    currentSnapshot = await pageSnapshot(client).catch(() => currentSnapshot);
    mediaState = canReuseCurrentPageMediaForPrepublish(platform, currentSnapshot, mediaPath, { requiresLocalMedia });
    if (mediaState.reusable || !["upload_prompt_only", "media_presence_unconfirmed"].includes(String(mediaState.reason || "").trim())) {
      break;
    }
  }
  return { snapshot: currentSnapshot, mediaState, waited_ms: Date.now() - startedAt };
}

export function deriveCompositeCurrentPageRouteDisposition(platform, snapshot = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const routeUrl = String(snapshot?.url || "").trim();
  const lines = Array.isArray(snapshot?.lines) ? snapshot.lines.map((line) => String(line || "").trim()).filter(Boolean) : [];
  const routeTitle = String(snapshot?.title || "").trim();
  const bodyText = String(lines.join(" ") || snapshot?.text || "").replace(/\s+/g, " ").trim();
  const routeText = `${routeTitle} ${bodyText}`.replace(/\s+/g, " ").trim();
  const authPatterns = /请先登录|登录已过期|登录失效|未登录|session|账户已退出|need.?to.?log.?in|sign.?in|log.?in|扫码登录|验证码登录|登录\/注册|我是创作者|我是mcn机构|创作者登录/i;
  const routeErrorPatterns = /糟糕，出了点问题|something went wrong|an error occurred|出了点问题|upload unavailable|暂时无法上传/i;
  const loggedInCreatorHomeSignals =
    normalizedPlatform === "youtube"
    && /studio\.youtube\.com/i.test(routeUrl)
    && (
      /频道信息中心|Channel dashboard|Dashboard|你的频道|在你的频道中搜索|搜索你的频道|创作者工作室|YouTube Studio/i.test(routeText)
      || lines.some((line) => /频道信息中心|Channel dashboard|Dashboard|在你的频道中搜索|发送反馈|内容|数据分析|字幕|设置/.test(line))
    );
  if (/\/login(?:\.html)?\b/i.test(routeUrl) || (authPatterns.test(routeText) && !loggedInCreatorHomeSignals)) {
    return {
      blocked: true,
      status: "needs_human",
      code: `${normalizedPlatform}_route_auth_required`,
      verification_reason: "auth_required",
    };
  }
  const routeReady = isCompositePublishRouteContext(normalizedPlatform, {
    url: routeUrl,
    text: bodyText,
    file_inputs: [],
  });
  if (routeReady && routeErrorPatterns.test(bodyText)) {
    return {
      blocked: true,
      status: "needs_human",
      code: `${normalizedPlatform}_prepublish_only_route_not_ready`,
      verification_reason: "publish_route_error_surface",
    };
  }
  if (!routeReady) {
    return {
      blocked: true,
      status: "needs_human",
      code: `${normalizedPlatform}_prepublish_only_route_not_ready`,
      verification_reason: "publish_route_not_ready",
    };
  }
  return {
    blocked: false,
    status: "",
    code: "",
    verification_reason: "",
  };
}

export async function probeCreatorSession(platform, options = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const tabs = await listCdpTabs();
  const entryUrl = resolvePlatformPublishEntryUrl(normalizedPlatform, tabs, options);
  if (!entryUrl) {
    return {
      platform: normalizedPlatform,
      ready: false,
      status: "probe_failed",
      code: `${normalizedPlatform}_session_probe_entry_missing`,
      message: `未配置 ${normalizedPlatform} 的创作者入口，无法确认登录态。`,
      route: { url: "" },
    };
  }
  let probeTab = null;
  let sessionClient = null;
  try {
    probeTab = await createCdpTab(entryUrl);
    if (!probeTab?.webSocketDebuggerUrl) {
      throw new Error("probe tab has no webSocketDebuggerUrl");
    }
    sessionClient = await CdpClient.connect(probeTab.webSocketDebuggerUrl);
    let snapshot = null;
    let disposition = {
      blocked: true,
      status: "needs_human",
      code: `${normalizedPlatform}_session_probe_pending`,
      verification_reason: "pending",
    };
    for (let attemptIndex = 0; attemptIndex < 6; attemptIndex += 1) {
      await sleep(attemptIndex === 0 ? 1800 : 1200);
      snapshot = await pageSnapshot(sessionClient);
      disposition = deriveCompositeCurrentPageRouteDisposition(normalizedPlatform, snapshot);
      if (
        normalizedPlatform === "youtube"
        && disposition.blocked
        && disposition.verification_reason !== "auth_required"
      ) {
        const bootstrap = await ensureYoutubeUploadEditor(sessionClient, "").catch(() => ({ matched: false, changed: false }));
        if (bootstrap?.changed) {
          await sleep(2200);
          continue;
        }
      }
      if (disposition.verification_reason === "auth_required" || !disposition.blocked) break;
    }
    if (
      normalizedPlatform === "youtube"
      && disposition.blocked
      && disposition.verification_reason !== "auth_required"
    ) {
      const hiddenUpload = await activateYoutubeHiddenUploadEntry(sessionClient).catch(() => ({ clicked: false }));
      if (hiddenUpload?.clicked) {
        for (let attemptIndex = 0; attemptIndex < 3; attemptIndex += 1) {
          await sleep(attemptIndex === 0 ? 2200 : 1400);
          snapshot = await pageSnapshot(sessionClient);
          disposition = deriveCompositeCurrentPageRouteDisposition(normalizedPlatform, snapshot);
          if (disposition.verification_reason === "auth_required" || !disposition.blocked) break;
        }
      }
    }
    if (snapshot) {
      snapshot = await attachVisualEvidenceToSnapshot(
        sessionClient,
        snapshot,
        {
          platform: normalizedPlatform,
          captureVisualEvidence: true,
          visualEvidencePhase: "creator_session_probe",
        },
      );
    }
    const route = {
      url: String(snapshot?.url || entryUrl || ""),
      title: String(snapshot?.title || ""),
    };
    const visualEvidence = normalizeVisualEvidence(snapshot?.visual_evidence);
    if (disposition.verification_reason === "auth_required") {
      return {
        platform: normalizedPlatform,
        ready: false,
        status: "auth_required",
        code: disposition.code,
        message: "创作者会话当前未登录或已失效。",
        verification_reason: disposition.verification_reason,
        route,
        visual_evidence: visualEvidence,
      };
    }
    if (disposition.blocked) {
      return {
        platform: normalizedPlatform,
        ready: false,
        status: "route_not_ready",
        code: disposition.code,
        message: "创作者入口未进入可发布路由，当前会话状态不可确认。",
        verification_reason: disposition.verification_reason,
        route,
        visual_evidence: visualEvidence,
      };
    }
    return {
      platform: normalizedPlatform,
      ready: true,
      status: "ready",
      code: "",
      message: "创作者会话可用。",
      verification_reason: disposition.verification_reason,
      route,
      visual_evidence: visualEvidence,
    };
  } catch (error) {
    return {
      platform: normalizedPlatform,
      ready: false,
      status: "probe_failed",
      code: `${normalizedPlatform}_session_probe_failed`,
      message: `创作者会话探测失败：${error.message}`,
      route: { url: entryUrl },
    };
  } finally {
    sessionClient?.close();
    if (probeTab?.id) {
      await closeCdpTab(probeTab.id).catch(() => null);
    }
  }
}

export function shouldBootstrapStopBeforeRouteRecovery(platform, disposition = {}) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const code = String(disposition?.code || "").trim();
  const verificationReason = String(disposition?.verification_reason || "").trim().toLowerCase();
  if (!disposition?.blocked) return false;
  if (normalizedPlatform === "youtube" && (verificationReason === "publish_route_error_surface" || code === "youtube_prepublish_only_route_not_ready")) {
    return true;
  }
  return false;
}

export function buildStopBeforeFinalPublishRecoveryOverrides({
  prepublishOnlyCurrentPage = false,
  prepareOnlyCurrentPage = false,
  verificationReason = "",
} = {}) {
  const normalizedReason = String(verificationReason || "").trim().toLowerCase();
  if (normalizedReason === "auth_required") {
    return {
      recovery_mode: "route_auth_required",
      prepublish_only_current_page: Boolean(prepublishOnlyCurrentPage),
      prepare_only_current_page: Boolean(prepareOnlyCurrentPage),
      verify_media_upload: false,
      wait_for_publish_confirmation: false,
    };
  }
  return {
    recovery_mode: "prepublish_resume",
    prepublish_only_current_page: Boolean(prepublishOnlyCurrentPage),
    prepare_only_current_page: Boolean(prepareOnlyCurrentPage),
    verify_media_upload: true,
    wait_for_publish_confirmation: true,
  };
}

export function deriveDedicatedVerifierMediaEntryDisposition(platform, verifier = {}, mediaPath = "") {
  const actual = verifier && typeof verifier === "object" && verifier.actual && typeof verifier.actual === "object"
    ? verifier.actual
    : {};
  const uploadState = actual.uploadState && typeof actual.uploadState === "object"
    ? actual.uploadState
    : {};
  const reason = uploadState.failed
    ? "upload_failed"
    : uploadState.prompt_only
      ? "upload_prompt_only"
      : "";
  if (!reason) return null;
  return deriveCompositeCurrentPageMediaPendingDisposition(platform, mediaPath, { reason });
}

async function clickByText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const candidates = roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll("button,[role=button],[role=menuitem],a,input[type=button],input[type=submit],label,[class*=button],[class*=menu],[class*=select],[class*=dropdown],[class*=option],[class*=radio],[class*=checkbox],.collection-plugin-button,.group-card-select,.season-enter,.selector-container,.select-controller,ytcp-dropdown-trigger")];
      } catch {
        return [];
      }
    }).filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder"));
      return { el, label, area: rect.width * rect.height };
    }).filter((item) => item.label && item.label.length <= 220 && item.area < 280000);
    for (const text of texts) {
      const exact = candidates.find((item) => item.label === text);
      const starts = candidates.find((item) => item.label.startsWith(text));
      const contains = candidates.find((item) => item.label.includes(text));
      const item = exact || starts || contains;
      if (item) {
        item.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = item.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          item.el.dispatchEvent(new MouseEvent(type, eventInit));
        }
        if (typeof item.el.click === "function") item.el.click();
        return { clicked: true, text, label: item.label };
      }
    }
    return { clicked: false };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickLooseText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const candidates = roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll("button,[role=button],[role=menuitem],li,span,div,p,a,label,[class*=menu],[class*=option],[class*=item],[class*=select],[class*=collection],tp-yt-paper-item,ytcp-dropdown-trigger")];
      } catch {
        return [];
      }
    }).filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const text = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
        const clickable = Boolean(el.closest("[role=dialog],[role=menu],[class*=modal],[class*=popover],[class*=dropdown],[class*=select],[class*=collection],[class*=menu]")) || ["BUTTON", "A", "LABEL", "LI"].includes(el.tagName) || /button|menuitem/.test(String(el.getAttribute("role") || ""));
        return { el, text, area: rect.width * rect.height, clickable };
      })
      .filter((item) => item.text && item.text.length <= 160 && item.area > 0 && item.area < 180000);
    for (const text of texts) {
      const item = candidates
        .filter((candidate) => candidate.text === text || candidate.text.includes(text))
        .sort((left, right) => Number(right.clickable) - Number(left.clickable) || left.area - right.area)[0];
      if (!item) continue;
      item.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = item.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) item.el.dispatchEvent(new MouseEvent(type, eventInit));
      if (typeof item.el.click === "function") item.el.click();
      return { clicked: true, text, label: item.text, loose: true };
    }
    return { clicked: false, loose: true, candidates: candidates.slice(0, 20).map((item) => item.text) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

export function hasYoutubeUploadDialogQuery(href = "") {
  return /[?&]d=ud(?:[&#]|$)/i.test(String(href || ""));
}

export function hasYoutubeUploadResumeVideoId(href = "") {
  return /(?:[?&])udvid=([A-Za-z0-9_-]{6,})/i.test(String(href || ""));
}

export function shouldTreatYouTubeUploadSurfaceAsStable({
  uploadResumeRoute = false,
  channelContentList = false,
  uploadDialogSurface = false,
  visibleFileInputCount = 0,
  videoCapableFileInputCount = 0,
} = {}) {
  if (uploadResumeRoute) return true;
  if (channelContentList) return false;
  if (Number(visibleFileInputCount || 0) > 0) return true;
  if (Number(videoCapableFileInputCount || 0) > 0) return true;
  return Boolean(uploadDialogSurface);
}

export function shouldPreserveYouTubeUploadResumeRoute(href = "", bodyText = "") {
  const normalizedHref = String(href || "").trim();
  const text = String(bodyText || "").replace(/\s+/g, " ").trim();
  if (/studio\.youtube\.com\/video\/[A-Za-z0-9_-]+\/edit/i.test(normalizedHref)) {
    return /视频详细信息|Video details/i.test(text) && /标题（必填）|说明|缩略图|播放列表|观众|视频链接/.test(text);
  }
  if (!/studio\.youtube\.com\/channel\/[^/?#]+\/(?:videos\/)?upload/i.test(normalizedHref)) return false;
  const hasResumeRouteMarker = hasYoutubeUploadResumeVideoId(normalizedHref);
  if (!hasResumeRouteMarker) return false;
  if (!text) return false;
  if (/糟糕，出了点问题|something went wrong|an error occurred|upload unavailable/i.test(text)) return false;
  const channelContentSignal = /频道内容|每页行数|发布日期|公开范围|观看次数|评论数/i.test(text);
  const resumeSignal = /正在上传|上传已中断|继续上传|取消上传|编辑草稿|添加说明|草稿|处理中，画质最高可为高清/i.test(text);
  return channelContentSignal && resumeSignal;
}

export function shouldPreserveYouTubeUploadResumeRouteForBootstrap(href = "", bodyText = "") {
  const normalizedHref = String(href || "").trim();
  const text = String(bodyText || "").replace(/\s+/g, " ").trim();
  if (!/studio\.youtube\.com\/channel\/[^/?#]+\/(?:videos\/)?upload/i.test(normalizedHref)) return false;
  if (!hasYoutubeUploadResumeVideoId(normalizedHref)) return false;
  return !/糟糕，出了点问题|something went wrong|an error occurred|upload unavailable/i.test(text);
}

export function isYouTubeEditorReadinessSurface(href = "", bodyText = "") {
  const normalizedHref = String(href || "").trim();
  const text = String(bodyText || "").replace(/\s+/g, " ").trim();
  if (!/studio\.youtube\.com\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(normalizedHref)) return false;
  return /视频详细信息|Video details/i.test(text)
    && /标题（必填）|说明|缩略图|播放列表|观众|视频链接/.test(text);
}

export function shouldPreserveYouTubeEditorRouteForBootstrap(href = "", bodyText = "") {
  const normalizedHref = String(href || "").trim();
  const text = String(bodyText || "").replace(/\s+/g, " ").trim();
  if (!/studio\.youtube\.com\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(normalizedHref)) return false;
  if (!text) return true;
  return !/糟糕，出了点问题|something went wrong|an error occurred|upload unavailable/i.test(text);
}

async function clickFinalPublishByText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const selector = "button,[role=button],input[type=button],input[type=submit],.submit-add,.submit-btn,.submit-button,[class*=submit],[class*=publish]";
    const candidates = roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    }).filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title"));
      const className = clean(typeof el.className === "string" ? el.className : "");
      const inFooter = Boolean(el.closest(".submit-container,.submit-wrp,.footer,.bcc-dialog__footer,[class*=footer],[class*=submit]"));
      return { el, label, className, area: rect.width * rect.height, y: rect.top, inFooter };
    }).filter((item) => item.label && item.label.length <= 80 && item.area < 120000);
    const score = (item, text) => {
      let value = 0;
      if (item.label === text) value += 20;
      else if (item.label.includes(text)) value += 12;
      if (item.inFooter) value += 5;
      if (/submit|publish|投稿|发布/.test(item.className)) value += 3;
      if (/预览|取消|返回|删除|保存草稿/.test(item.label)) value -= 30;
      return value;
    };
    for (const text of texts) {
      const chosen = candidates
        .map((item) => ({ item, score: score(item, text) }))
        .filter((entry) => entry.score > 0)
        .sort((left, right) => right.score - left.score || right.item.y - left.item.y)[0]?.item;
      if (chosen) {
        chosen.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = chosen.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
        }
        return { clicked: true, text, label: chosen.label, className: chosen.className };
      }
    }
    return { clicked: false, candidates: candidates.slice(0, 20).map((item) => ({ label: item.label, className: item.className, inFooter: item.inFooter })) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickPlatformFinalPublish(client, platform, texts) {
  if (platform === "kuaishou") {
    const target = await evaluateWithClient(client, `(async () => {
      await new Promise((resolve) => {
        const scrollTarget = document.scrollingElement || document.documentElement || document.body;
        window.scrollTo({ top: Math.max(scrollTarget.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSchedule = Boolean(el.closest("._publish-time_171ix_401,.ant-picker,.ant-radio-wrapper,[class*=publish-time],[class*=time]"));
          const inPreview = Boolean(el.closest("[class*=preview]"));
          return { el, label, className, area: rect.width * rect.height, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, top: rect.top, inSchedule, inPreview };
        })
        .filter((item) => item.label && item.label.length <= 20 && item.area > 0 && item.area < 60000 && !item.inSchedule && !item.inPreview && !/取消|预览|定时|立即发布|发布时间/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布")
        .sort((left, right) => right.top - left.top || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { found: false, platform: "kuaishou", candidates: candidates.slice(0, 30).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      return { found: true, platform: "kuaishou", text: "发布", label: chosen.label, className: chosen.className, x: chosen.x, y: chosen.y };
    })()`, 10000);
    if (!target?.found) return { clicked: false, ...target };
    await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    return { clicked: true, platform: "kuaishou", text: target.text, label: target.label, className: target.className };
    const expression = `(async () => {
      await new Promise((resolve) => {
        const scrollTarget = document.scrollingElement || document.documentElement || document.body;
        window.scrollTo({ top: Math.max(scrollTarget.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSchedule = Boolean(el.closest("._publish-time_171ix_401,.ant-picker,.ant-radio-wrapper,[class*=publish-time],[class*=time]"));
          const inPreview = Boolean(el.closest("[class*=preview]"));
          return { el, label, className, area: rect.width * rect.height, x: rect.left, y: rect.top, inSchedule, inPreview };
        })
        .filter((item) => item.label && item.label.length <= 20 && item.area > 0 && item.area < 60000 && !item.inSchedule && !item.inPreview && !/取消|预览|定时|立即发布|发布时间/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布")
        .sort((left, right) => right.y - left.y || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { clicked: false, platform: "kuaishou", candidates: candidates.slice(0, 30).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      chosen.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = chosen.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
      return { clicked: true, platform: "kuaishou", text: "发布", label: chosen.label, className: chosen.className };
    })()`;
    return evaluateWithClient(client, expression, 10000);
  }
  if (platform === "xiaohongshu") {
    await clearXiaohongshuStaleCoverLayers(client).catch(() => {});
    const target = await evaluateWithClient(client, `(async () => {
      const platform = ${JSON.stringify(platform)};
      await new Promise((resolve) => {
        const scrollTarget = document.scrollingElement || document.documentElement || document.body;
        window.scrollTo({ top: Math.max(scrollTarget.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const host = document.querySelector("xhs-publish-btn[submit-disabled='false']");
      if (host && visible(host)) {
        const rect = host.getBoundingClientRect();
        return {
          found: true,
          platform,
          text: host.getAttribute("submit-text") || "发布",
          label: host.getAttribute("submit-text") || "发布",
          className: "xhs-publish-btn",
          x: rect.left + rect.width * 0.74,
          y: rect.top + rect.height * 0.5,
        };
      }
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSettings = Boolean(el.closest(".publish-page-content-settings,.post-time-wrapper"));
          const inSidebar = Boolean(el.closest(".menu-container,.menu-panel"));
          const position = getComputedStyle(el).position;
          return { el, label, className, area: rect.width * rect.height, x: rect.left, y: rect.top, inSettings, inSidebar, position };
        })
        .filter((item) => item.label && item.label.length <= 40 && item.area > 0 && item.area < 80000 && !item.inSettings && !item.inSidebar && !/取消|预览|封面|定时/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布" || item.label === "发布笔记" || item.label.includes("发布"))
        .sort((left, right) => (right.position === "fixed") - (left.position === "fixed") || right.y - left.y || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { found: false, platform, candidates: candidates.slice(0, 24).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      const rect = chosen.el.getBoundingClientRect();
      return { found: true, platform, text: "发布", label: chosen.label, className: chosen.className, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`, 10000);
    if (!target?.found) return { clicked: false, ...target };
    await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    return { clicked: true, platform, text: target.text, label: target.label, className: target.className, input_click: { x: target.x, y: target.y } };
  }
  return clickFinalPublishByText(client, texts);
}

async function clickVisibleDialogConfirm(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => {
      return roots.flatMap((root) => {
        try {
          return [...root.querySelectorAll(selector)];
        } catch {
          return [];
        }
      });
    };
    const dialogs = queryAll("[role=dialog],[aria-modal=true],[class*=modal],[class*=dialog],[class*=popover],[class*=drawer]")
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => item.text && item.area > 1000)
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      if (!/确认|确定|发布|投稿|声明|风险|无误|提交/.test(dialog.text)) continue;
      const candidates = [...dialog.el.querySelectorAll("button,[role=button],input[type=button],input[type=submit],span,div")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          return { el, label, className, area: rect.width * rect.height, y: rect.top };
        })
        .filter((item) => item.label && item.label.length <= 80 && item.area > 0 && item.area < 120000 && !/取消|返回|关闭/.test(item.label));
      for (const text of texts) {
        const chosen = candidates
          .filter((item) => item.label === text || item.label.includes(text))
          .sort((left, right) => left.area - right.area || right.y - left.y)[0];
        if (!chosen) continue;
        chosen.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = chosen.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
        return { clicked: true, text, label: chosen.label, dialog_text: dialog.text.slice(0, 240) };
      }
    }
    return { clicked: false, dialogs: dialogs.slice(0, 6).map((item) => item.text.slice(0, 220)) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickToutiaoCompletionConfirm(client) {
  const target = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll(".Dialog-container,.m-xigua-dialog,[role=dialog]")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => /完成后无法继续编辑/.test(item.text))
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      const button = [...dialog.el.querySelectorAll("button,[role=button]")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          return { el, label: clean(el.innerText || el.textContent), className: clean(typeof el.className === "string" ? el.className : ""), x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height };
        })
        .filter((item) => item.label === "确定" || item.label === "确认")
        .sort((left, right) => left.area - right.area)[0];
      if (button) return { found: true, label: button.label, x: button.x, y: button.y, className: button.className, dialog: dialog.text.slice(0, 120) };
    }
    return { found: false, dialogs: dialogs.map((item) => item.text.slice(0, 160)) };
  })()`, 10000);
  if (!target.found) return { clicked: false, ...target };
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1600);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    return { still_open: /完成后无法继续编辑/.test(clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "")) };
  })()`, 10000);
  return { clicked: true, ...target, ...after };
}

async function clickToutiaoPublishBlockingDialog(client) {
  const target = await evaluateWithClient(client, `(async () => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector, rootOverride = null) => {
      const targets = rootOverride ? [rootOverride] : roots;
      return targets.flatMap((root) => {
        try {
          return [...root.querySelectorAll(selector)];
        } catch {
          return [];
        }
      });
    };
    const extractText = (el) => clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
    const isClickableNode = (el) => {
      if (!el || !el.tagName) return false;
      const tag = el.tagName.toLowerCase();
      if (tag === "button" || tag === "a") return true;
      if (tag === "input") {
        const type = (el.getAttribute("type") || "").toLowerCase();
        return type === "button" || type === "submit" || type === "reset";
      }
      return false;
    };
    const hasClickableHint = (el) => {
      const role = (el.getAttribute("role") || "").toLowerCase();
      if (role === "button") return true;
      const hasOnclick = typeof el.getAttribute("onclick") === "string";
      const className = clean(typeof el.className === "string" ? el.className : "");
      const hasClassHint = /btn|button|click|submit|confirm|sure|ok|close|next|done|next|primary|ant-btn|m-btn|byte-btn|xigua/.test(className);
      const tabIndex = el.getAttribute("tabindex");
      const hasTab = tabIndex !== null && /^\d+$/.test(tabIndex);
      let cursor = "";
      try {
        cursor = getComputedStyle(el).cursor || "";
      } catch (_) {}
      const cursorHint = cursor === "pointer";
      return hasOnclick || hasClassHint || hasTab || cursorHint;
    };
    const clickableSelfOrAncestor = (el) => {
      if (!el || !el.matches) return null;
      let current = el;
      let depth = 0;
      while (current && current.nodeType === 1 && depth < 6) {
        if (
          isClickableNode(current) ||
          hasClickableHint(current) ||
          current.matches("[role=button],button,a,input[type=button],input[type=submit],input[type=reset],[onclick],[tabindex]")
        ) return current;
        current = current.parentElement;
        depth += 1;
      }
      return el;
    };
    const scoreCandidates = (label) => {
      if (!label) return 0;
      if (/不加入合集|跳过发布|跳过|下一步|继续发布|确认|确定|完成/.test(label)) return 300;
      if (/保存草稿|保存|发布|提交/.test(label)) return 220;
      if (/发布视频/.test(label)) return 200;
      if (/选择合集|加入合集|合集/.test(label)) return 120;
      return 10;
    };
    const collectCandidates = (container, pageText, scopeText) => {
      const selector = "button,[role=button],a,input,span,div,li,label,p,label[for],[onclick],[tabindex],[class*=btn],[class*=button],[class*=action],[class*=operation]";
      const queryNodes = container ? queryAll(selector, container) : queryAll(selector);
      return queryNodes
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const text = extractText(el);
          if (!text || text.length > 180 || rect.width * rect.height <= 0) return null;
          const target = clickableSelfOrAncestor(el);
          if (!target || !visible(target)) return null;
          const tRect = target.getBoundingClientRect();
          return {
            el: target,
            sourceTag: (el.tagName || "").toLowerCase(),
            sourceText: text,
            label: clean(extractText(target)),
            className: clean(typeof target.className === "string" ? target.className : ""),
            x: tRect.left + tRect.width / 2,
            y: tRect.top + tRect.height / 2,
            area: tRect.width * tRect.height,
            inScopeText: scopeText || "",
            hasCollectionFlag: /选择合集|合集/.test(text) || /选择合集|合集/.test(scopeText || ""),
            score: scoreCandidates(text) + (scopeText && /选择合集|发布设置|待发布|发布视频/.test(scopeText) ? 40 : 0),
          };
        })
        .filter(Boolean)
        .filter((item) => item.label && !/取消|返回|关闭|放弃/.test(item.label));
    };
    const dialogs = queryAll(".Dialog-container,.m-xigua-dialog,[role=dialog],.byte-modal-wrapper,[class*=modal], [class*=popup], [class*=drawer], [class*=overlay], .m-modal, .m-modal-mask, .m-fe-dialog")
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => item.text && item.area > 900)
      .sort((left, right) => left.area - right.area);
    const pickFrom = (nodes, contextText) => {
      const candidates = nodes
        .filter((item) => item.label)
        .map((item) => ({ ...item, route: clean(item.sourceText || item.label) }))
        .sort((left, right) => right.score - left.score || left.area - right.area || right.y - left.y || left.x - right.x);
      const preferred = candidates.find((item) => /不加入合集|继续发布|下一步|确认|确定|完成|保存草稿|保存|发布视频|发布|提交/.test(item.label));
      if (preferred) return preferred;
      return candidates.find((item) => /选择合集|加入合集|合集/.test(item.label)) || candidates[0];
    };
    for (const dialog of dialogs) {
      if (!/选择合集|完成后无法继续编辑|发布失败|发布设置|发布|待发布|合集/.test(dialog.text)) continue;
      const candidates = collectCandidates(dialog.el, null, dialog.text);
      const chosen = pickFrom(candidates, dialog.text);
      if (!chosen) continue;
      chosen.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = chosen.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
      await new Promise((resolve) => setTimeout(resolve, 800));
      return {
        found: true,
        label: chosen.label,
        sourceTag: chosen.sourceTag,
        score: chosen.score,
        text: dialog.text.slice(0, 220),
        className: chosen.className,
        clicked: true,
        route: location.href,
      };
    }
    const pageText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const collectionMode = /选择合集|发布设置|待发布|发布成功|审核中|发布视频|发布管理|作品管理/.test(pageText);
    if (collectionMode) {
      const collectionTargets = collectCandidates(null, pageText);
      const chosen = pickFrom(collectionTargets, pageText);
      if (chosen) {
        chosen.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = chosen.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
        await new Promise((resolve) => setTimeout(resolve, 800));
        return {
          found: true,
          label: chosen.label,
          sourceTag: chosen.sourceTag,
          score: chosen.score,
          text: pageText.slice(0, 220),
          className: chosen.className,
          clicked: true,
          collection_mode: true,
          route: location.href,
        };
      }
    }
    return {
      found: false,
      collection_mode: collectionMode,
      dialogs: dialogs.slice(0, 6).map((item) => item.text.slice(0, 180)),
      candidates: queryAll(".Dialog-container,.m-xigua-dialog,[role=dialog],.byte-modal-wrapper,[class*=modal], [class*=popup], [class*=drawer], [class*=overlay], .m-modal, .m-modal-mask, .m-fe-dialog")
        .filter(visible)
        .map((item) => clean(item.textContent))
        .filter(Boolean)
        .slice(0, 8),
    };
  })()`, 12000);
  if (!target.found) return { clicked: false, ...target };
  await sleep(800);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    return {
      still_open: /选择合集|完成后无法继续编辑/.test(text),
      lines: text.split(/[\\n\\r]+| {2,}/).map(clean).filter(Boolean).slice(0, 24),
    };
  })()`, 8000);
  return { clicked: true, ...target, ...after };
}

async function dismissCompositeFinalizeInterruptions(client, platform) {
  if (platform === "toutiao") {
    const actions = [];
    for (let index = 0; index < 3; index += 1) {
      const dialog = await clickToutiaoPublishBlockingDialog(client);
      actions.push({ kind: "toutiao_publish_blocking_dialog", ...dialog });
      if (!dialog.clicked) break;
      await sleep(900);
    }
    const byText = await clickByText(
      client,
      ["不加入合集", "继续发布", "下一步", "确认", "确定", "完成", "发布", "发布视频", "提交", "保存草稿", "跳过"],
    );
    actions.push({ kind: "toutiao_publish_blocking_dialog_by_text", ...byText });
    if (byText.clicked) {
      await sleep(900);
    }
    const fallback = await clickVisibleDialogConfirm(client, ["确定", "确认", "完成", "继续", "保存", "下一步", "我知道了", "知道了", "选择", "确定选择", "确认选择"]);
    actions.push({ kind: "toutiao_publish_confirm_dialog_fallback", ...fallback });
    return actions;
  }
  if (platform === "x") {
    const xConfirm = await clickVisibleDialogConfirm(client, ["确认", "确定", "继续发布", "我知道了", "以后再说", "知道了", "继续", "保存"]);
    return [{ kind: "x_publish_confirm_dialog", ...xConfirm }];
  }
  return [];
}

async function setFirstVideoFileInput(client, mediaPath) {
  if (!mediaPath) return { uploaded: false, reason: "missing_media_path" };
  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const rootNodeId = documentResult.root.nodeId;
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: rootNodeId, selector: "input[type=file]" });
  const nodeIds = queryResult.nodeIds || [];
  const described = [];
  for (const nodeId of nodeIds) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    described.push({ nodeId, attrMap });
  }
  const preferred =
    described.find((item) => /video|mp4|\*/i.test(item.attrMap.accept || "")) ||
    described.find((item) => !/image/i.test(item.attrMap.accept || "") && !String(item.attrMap.accept || "").trim()) ||
    null;
  if (!preferred) {
    return {
      uploaded: false,
      reason: described.length ? "no_video_file_input" : "no_file_input",
      fileInputs: described.map((item) => item.attrMap),
    };
  }
  await client.send("DOM.setFileInputFiles", { nodeId: preferred.nodeId, files: [mediaPath] });
  await dispatchFileInputEvents(client, preferred.nodeId);
  return { uploaded: true, input: preferred.attrMap, fileInputCount: described.length };
}

async function dispatchFileInputEvents(client, nodeId) {
  try {
    const resolved = await client.send("DOM.resolveNode", { nodeId });
    const objectId = resolved.object?.objectId;
    if (!objectId) return { dispatched: false, reason: "missing_object_id" };
    await client.send("Runtime.callFunctionOn", {
      objectId,
      awaitPromise: true,
      functionDeclaration: `function() {
        this.dispatchEvent(new Event("input", { bubbles: true }));
        this.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }`,
    });
    return { dispatched: true };
  } catch (error) {
    return { dispatched: false, reason: error.message };
  }
}

async function setTextFieldByHints(client, hints, value, { multiline = false, requireHintMatch = false } = {}) {
  const textValue = String(value || "").trim();
  if (!textValue) return { filled: false, reason: "empty_value" };
  const expression = `(() => {
    const hints = ${JSON.stringify(hints)};
    const value = ${JSON.stringify(textValue)};
    const multiline = ${JSON.stringify(Boolean(multiline))};
    const requireHintMatch = ${JSON.stringify(Boolean(requireHintMatch))};
    const clean = (raw) => String(raw || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && !el.readOnly && el.getAttribute("readonly") === null && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const labelFor = (el) => {
      const id = el.getAttribute("id");
      const labelledBy = el.getAttribute("aria-labelledby");
      const labels = [];
      if (id) labels.push(...queryAll(\`label[for="\${CSS.escape(id)}"]\`).map((label) => label.innerText));
      if (labelledBy) {
        for (const part of labelledBy.split(/\\s+/)) {
          const node = document.getElementById(part);
          if (node) labels.push(node.innerText || node.textContent || "");
        }
      }
      let parent = el.parentElement;
      for (let index = 0; index < 3 && parent; index += 1, parent = parent.parentElement) {
        labels.push(parent.innerText || "");
      }
      return clean([el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.getAttribute("title"), ...labels].filter(Boolean).join(" "));
    };
    const selector = multiline
      ? "textarea,[contenteditable=true],[role=textbox]"
      : "input:not([type]),input[type=text],textarea,[contenteditable=true],[role=textbox]";
    const candidates = queryAll(selector).filter(visible).map((el) => ({
      el,
      label: labelFor(el),
      current: clean(el.value || el.innerText || el.textContent),
    }));
    const score = (item) => {
      let value = 0;
      for (const hint of hints) {
        if (!hint) continue;
        if (item.label.includes(hint)) value += 10;
        if (item.current.includes(hint)) value += 2;
      }
      if (multiline && item.el.tagName === "TEXTAREA") value += 2;
      if (!multiline && item.el.tagName === "INPUT") value += 2;
      if (!item.current) value += 1;
      return value;
    };
    const hasHintMatch = (item) => hints.some((hint) => hint && (item.label.includes(hint) || item.current.includes(hint)));
    const chosen = candidates.sort((left, right) => score(right) - score(left))[0];
    if (!chosen || score(chosen) <= 0 || (requireHintMatch && !hasHintMatch(chosen))) {
      return { filled: false, reason: "field_not_found", candidates: candidates.slice(0, 10).map((item) => item.label) };
    }
    const el = chosen.el;
    el.scrollIntoView({ block: "center", inline: "center" });
    el.focus();
    if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
      el.textContent = value;
    } else {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, value);
      else el.value = value;
    }
    for (const type of ["input", "change", "blur"]) {
      el.dispatchEvent(new Event(type, { bubbles: true }));
    }
    return { filled: true, label: chosen.label, tag: el.tagName.toLowerCase() };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function expandYoutubeMetadataSections(client) {
  const selectExpandSource = JSON.stringify(`(${selectYouTubeMetadataExpandCandidate.toString()})`);
  return evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const selectExpandCandidate = (0, eval)(${selectExpandSource});
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...(root.querySelectorAll ? root.querySelectorAll("*") : [])]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const hasTagSurface = () => queryAll("input,textarea,[contenteditable=true],[role=textbox],ytcp-form-input-container,ytcp-form-chip-bar,ytcp-video-metadata-editor-advanced")
      .filter(visible)
      .some((el) => /标签|tags?\\b|keyword|关键字/i.test([
        clean(el.innerText || el.textContent),
        clean(el.getAttribute("aria-label")),
        clean(el.getAttribute("placeholder")),
        clean(el.getAttribute("title")),
        clean(el.getAttribute("id")),
      ].join(" ")));
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      try {
        el.click();
      } catch {}
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        try {
          el.dispatchEvent(new MouseEvent(type, eventInit));
        } catch {}
      }
      return hasTagSurface() || el.getAttribute("aria-expanded") === "true" || /收起|隐藏高级设置|show less/i.test(clean(el.innerText || el.textContent || el.getAttribute("aria-label")));
    };
    if (hasTagSurface()) {
      return { expanded: true, already_visible: true };
    }
    const candidates = queryAll("button,[role=button],tp-yt-paper-button,ytcp-button,label,summary,span,div")
      .filter(visible)
      .map((el) => ({
        el,
        text: clean(el.innerText || el.textContent),
        aria_label: clean(el.getAttribute("aria-label")),
        tag: String(el.tagName || "").toLowerCase(),
        role: clean(el.getAttribute("role")),
        area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
      }))
      .filter((item) => item.text && item.text.length <= 160);
    const target = selectExpandCandidate(candidates);
    if (!target) {
      return {
        expanded: false,
        reason: "metadata_expand_entry_not_found",
        candidates: candidates.slice(0, 20).map((item) => ({
          text: item.text,
          aria_label: item.aria_label,
          tag: item.tag,
          role: item.role,
        })),
      };
    }
    const clicked = click(target.el);
    let expanded = hasTagSurface();
    for (let attempt = 0; attempt < 8 && !expanded; attempt += 1) {
      await sleep(400);
      expanded = hasTagSurface();
    }
    return {
      expanded,
      clicked,
      label: target.text,
      reason: !clicked ? "metadata_expand_click_failed" : (expanded ? "metadata_expand_visible" : "metadata_expand_clicked"),
    };
  })()`, 15000);
}

export function normalizeYouTubeTagValue(value = "") {
  return String(value || "").replace(/^#/, "").replace(/\s+/g, " ").trim();
}

export function selectYouTubeMetadataExpandCandidate(candidates = []) {
  const items = Array.isArray(candidates)
    ? candidates
      .map((item) => ({
        ...item,
        text: String(item?.text || "").trim(),
        aria_label: String(item?.aria_label || "").trim(),
        tag: String(item?.tag || "").trim().toLowerCase(),
        role: String(item?.role || "").trim().toLowerCase(),
        area: Number(item?.area || 0),
      }))
      .filter((item) => item.area > 0)
    : [];
  if (!items.length) return null;
  const score = (item) => {
    const haystack = [item.text, item.aria_label].join(" ").toLowerCase();
    let value = 0;
    if (/显示高级设置|隐藏高级设置|show more|show less/.test(haystack)) value += 120;
    if (/展开|收起/.test(haystack)) value += 40;
    if (/付费宣传内容|联合创作|字幕等|高级设置/.test(haystack)) value += 24;
    if (item.tag === "button" || item.tag === "ytcp-button" || item.role === "button") value += 40;
    if (item.tag === "div" || item.tag === "span") value -= 20;
    return value;
  };
  return items
    .map((item) => ({ item, score: score(item) }))
    .filter((entry) => entry.score > 0)
    .sort((left, right) => right.score - left.score || right.item.area - left.item.area)[0]?.item || null;
}

export function selectYouTubeTagInputCandidate(candidates = []) {
  const items = Array.isArray(candidates)
    ? candidates
      .map((item) => ({
        ...item,
        label: String(item?.label || "").trim(),
        context: String(item?.context || "").trim(),
        placeholder: String(item?.placeholder || "").trim(),
        aria_label: String(item?.aria_label || "").trim(),
        tag: String(item?.tag || "").trim().toLowerCase(),
        type: String(item?.type || "").trim().toLowerCase(),
        value: String(item?.value || "").trim(),
        chip_count: Number(item?.chip_count || 0),
        area: Number(item?.area || 0),
      }))
      .filter((item) => item.area > 0)
    : [];
  if (!items.length) return null;
  const score = (item) => {
    const haystack = [item.label, item.context, item.placeholder, item.aria_label].join("\n").toLowerCase();
    let value = 0;
    if (/标签|tags?\b|keyword/.test(haystack)) value += 60;
    if (/按.?enter|enter|回车/.test(haystack)) value += 24;
    if (item.tag === "input") value += 20;
    if (item.type === "text" || !item.type) value += 8;
    if (item.chip_count > 0) value += 12;
    if (item.value) value -= 4;
    if (/标题|title|说明|description|简介|播放列表|playlist|封面|thumbnail|公开范围|visibility/.test(haystack)) value -= 40;
    return value;
  };
  return items
    .map((item) => ({ item, score: score(item) }))
    .filter((entry) => entry.score > 0)
    .sort((left, right) => right.score - left.score || right.item.chip_count - left.item.chip_count || right.item.area - left.item.area)[0]?.item || null;
}

async function setYouTubeTags(client, tags = []) {
  const expected = Array.from(new Set((Array.isArray(tags) ? tags : []).map((item) => normalizeYouTubeTagValue(item)).filter(Boolean))).slice(0, 15);
  if (!expected.length) {
    return { filled: false, reason: "empty_tags", actual_tags: [], attempts: [] };
  }
  const normalizeTagSource = JSON.stringify(`(${normalizeYouTubeTagValue.toString()})`);
  const selectExpandSource = JSON.stringify(`(${selectYouTubeMetadataExpandCandidate.toString()})`);
  return evaluateWithClient(client, `(async () => {
    const expected = ${JSON.stringify(expected)};
    const normalizeTag = (0, eval)(${normalizeTagSource});
    const selectExpandCandidate = (0, eval)(${selectExpandSource});
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const chipTexts = (container) => {
      if (!container) return [];
      const values = [...container.querySelectorAll("ytcp-chip,ytcp-text-chip,ytcp-chip-bar ytcp-chip,ytcp-form-chip-bar ytcp-chip,[role=listitem],tp-yt-paper-chip,.chip,.ytcp-chip")]
        .filter(visible)
        .map((el) => clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title")))
        .map(normalizeTag)
        .filter((value) => value && !/^标签|tags?$|按.?enter|回车|添加标签|add tag$/i.test(value) && value.length <= 80);
      return [...new Set(values)];
    };
    const labelFor = (el) => {
      const id = el.getAttribute("id");
      const labelledBy = el.getAttribute("aria-labelledby");
      const labels = [];
      if (id) labels.push(...queryAll('label[for="' + CSS.escape(id) + '"]').map((label) => label.innerText || label.textContent || ""));
      if (labelledBy) {
        for (const part of labelledBy.split(/\\s+/)) {
          const node = document.getElementById(part);
          if (node) labels.push(node.innerText || node.textContent || "");
        }
      }
      let parent = el.parentElement;
      for (let index = 0; index < 4 && parent; index += 1, parent = parent.parentElement) {
        labels.push(parent.innerText || parent.textContent || "");
      }
      return clean([el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.getAttribute("title"), ...labels].filter(Boolean).join(" "));
    };
    const findCandidates = () => {
      const nodes = queryAll("input:not([type=hidden]),textarea,[contenteditable=true],[role=textbox]")
        .filter(visible)
        .map((el) => {
          const container = el.closest("ytcp-form-input-container,ytcp-form-chip-bar,ytcp-social-suggestions-textbox,ytcp-chip-bar,[class*=tag],[class*=chip],[class*=keyword],[class*=metadata],section,fieldset,div");
          const context = clean(container?.innerText || container?.textContent || "");
          const chips = chipTexts(container || el.parentElement || el);
          return {
            el,
            label: labelFor(el),
            context,
            placeholder: clean(el.getAttribute("placeholder")),
            aria_label: clean(el.getAttribute("aria-label")),
            tag: String(el.tagName || "").toLowerCase(),
            type: String(el.getAttribute("type") || "").toLowerCase(),
            value: clean(el.value || el.textContent || ""),
            chip_count: chips.length,
            area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
            chips,
          };
        })
        .filter((item) => /标签|tags?\\b|keyword/i.test([item.label, item.context, item.placeholder, item.aria_label].join(" ")));
      return nodes;
    };
    const maybeExpandMetadata = async () => {
      const candidates = queryAll("button,[role=button],tp-yt-paper-button,ytcp-button,label,summary,span,div")
        .filter(visible)
        .map((el) => ({
          el,
          text: clean(el.innerText || el.textContent),
          aria_label: clean(el.getAttribute("aria-label")),
          tag: String(el.tagName || "").toLowerCase(),
          role: clean(el.getAttribute("role")),
          area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
        }))
        .filter((item) => item.text && item.text.length <= 160);
      const target = selectExpandCandidate(candidates);
      if (!target) return { clicked: false, reason: "metadata_expand_entry_not_found" };
      target.el.scrollIntoView({ block: "center", inline: "center" });
      try {
        target.el.click();
      } catch {}
      await sleep(1200);
      return { clicked: true, label: target.text, reason: "metadata_expand_retry_clicked" };
    };
    const selectCandidate = (items) => {
      const candidates = Array.isArray(items) ? items : [];
      if (!candidates.length) return null;
      const score = (item) => {
        const haystack = [item.label, item.context, item.placeholder, item.aria_label].join(" ").toLowerCase();
        let value = 0;
        if (/标签|tags?\\b|keyword/.test(haystack)) value += 60;
        if (/按.?enter|enter|回车/.test(haystack)) value += 24;
        if (String(item.tag || "").toLowerCase() === "input") value += 20;
        if (!item.type || String(item.type || "").toLowerCase() === "text") value += 8;
        if (Number(item.chip_count || 0) > 0) value += 12;
        if (item.value) value -= 4;
        if (/标题|title|说明|description|简介|播放列表|playlist|封面|thumbnail|公开范围|visibility/.test(haystack)) value -= 40;
        return value;
      };
      return candidates
        .map((item) => ({ item, score: score(item) }))
        .filter((entry) => entry.score > 0)
        .sort((left, right) => right.score - left.score || Number(right.item.chip_count || 0) - Number(left.item.chip_count || 0) || Number(right.item.area || 0) - Number(left.item.area || 0))[0]?.item || null;
    };
    const setValue = (el, value) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
        el.textContent = value;
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
      }
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    };
    const clearValue = (el) => setValue(el, "");
    const pressKey = (el, key, code) => {
      const options = {
        key,
        code,
        keyCode: key === "Enter" ? 13 : key === "Tab" ? 9 : key === "," ? 188 : 0,
        which: key === "Enter" ? 13 : key === "Tab" ? 9 : key === "," ? 188 : 0,
        bubbles: true,
        cancelable: true,
      };
      for (const type of ["keydown", "keypress", "keyup"]) {
        el.dispatchEvent(new KeyboardEvent(type, options));
      }
    };
    let candidate = selectCandidate(findCandidates());
    if (!candidate) {
      const expandAttempt = await maybeExpandMetadata();
      const retried = selectCandidate(findCandidates());
      if (!retried) {
        return {
          filled: false,
          reason: "youtube_tag_input_not_found",
          expand_attempt: expandAttempt,
          actual_tags: [],
          candidates: findCandidates().slice(0, 10).map((item) => ({
            label: item.label,
            context: item.context.slice(0, 160),
            chip_count: item.chip_count,
            tag: item.tag,
          })),
        };
      }
      candidate = retried;
    }
    const target = candidate.el;
    const currentTags = () => {
      const fresh = findCandidates();
      const matched = selectCandidate(fresh) || fresh.find((item) => item.label === candidate.label && item.context === candidate.context);
      return matched?.chips || chipTexts(target.closest("ytcp-form-input-container,ytcp-form-chip-bar,ytcp-social-suggestions-textbox,ytcp-chip-bar,[class*=tag],[class*=chip],[class*=keyword],[class*=metadata],section,fieldset,div") || target.parentElement || target);
    };
    const attempts = [];
    for (const tag of expected) {
      if (currentTags().includes(tag)) {
        attempts.push({ tag, present: true, skipped: true, reason: "already_present" });
        continue;
      }
      let present = false;
      const tryCommit = async (value, mode) => {
        clearValue(target);
        await sleep(80);
        setValue(target, value);
        await sleep(120);
        pressKey(target, "Enter", "Enter");
        target.dispatchEvent(new Event("blur", { bubbles: true }));
        await sleep(320);
        const actual = currentTags();
        if (actual.includes(tag)) {
          attempts.push({ tag, present: true, mode, actual_tags: actual.slice(0, 20) });
          return true;
        }
        return false;
      };
      present = await tryCommit(tag, "enter");
      if (!present) present = await tryCommit(tag + ",", "comma_enter");
      if (!present) {
        clearValue(target);
        await sleep(80);
        setValue(target, tag);
        await sleep(120);
        pressKey(target, "Tab", "Tab");
        target.dispatchEvent(new Event("blur", { bubbles: true }));
        await sleep(320);
        const actual = currentTags();
        present = actual.includes(tag);
        attempts.push({ tag, present, mode: "tab_blur", actual_tags: actual.slice(0, 20) });
      }
      if (!present) {
        attempts.push({ tag, present: false, mode: "commit_failed", actual_tags: currentTags().slice(0, 20) });
      }
    }
    const actualTags = currentTags();
    return {
      filled: actualTags.length > 0,
      verified: expected.every((tag) => actualTags.includes(tag)),
      label: candidate.label,
      context: candidate.context.slice(0, 220),
      actual_tags: actualTags,
      attempts,
    };
  })()`, 30000);
}

function parseChinaLocalSchedule(value) {
  const text = String(value || "").trim();
  if (!text) return { timestamp: 0, display: "" };
  const normalized = text.replace(" ", "T");
  const withSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(normalized) ? `${normalized}:00` : normalized;
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(withSeconds) ? withSeconds : `${withSeconds}+08:00`;
  const date = new Date(zoned);
  if (Number.isNaN(date.getTime())) return { timestamp: 0, display: text.replace("T", " ").slice(0, 16) };
  const display = normalized.replace("T", " ").slice(0, 16);
  return { timestamp: Math.floor(date.getTime() / 1000), display };
}

function formatChinaLocalTimestamp(timestampMs) {
  const date = new Date(timestampMs);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("sv-SE", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date).replace(",", "");
}

export function deriveCompositeSchedulePolicyState(platform, content = {}, nowMs = Date.now()) {
  const normalizedPlatform = normalizePlatform(platform);
  const scheduledPublishAt = String(content?.scheduled_publish_at || "").trim();
  const supportsScheduledPublish = Boolean(compositePlatformCapabilities(normalizedPlatform).supports_scheduled_publish);
  const minimumLeadMinutes = compositePlatformMinimumScheduleLeadMinutes(normalizedPlatform);
  if (!scheduledPublishAt || !supportsScheduledPublish) {
    return {
      platform: normalizedPlatform,
      configured: Boolean(scheduledPublishAt),
      supportsScheduledPublish,
      minimumLeadMinutes,
      ready: true,
      reason: "",
      scheduledPublishAt,
      minimumReadyAt: "",
    };
  }
  const parsed = parseChinaLocalSchedule(scheduledPublishAt);
  if (!parsed.timestamp) {
    return {
      platform: normalizedPlatform,
      configured: true,
      supportsScheduledPublish,
      minimumLeadMinutes,
      ready: false,
      reason: "invalid_schedule_format",
      scheduledPublishAt,
      minimumReadyAt: "",
    };
  }
  const minimumReadyAtMs = Number(nowMs) + (minimumLeadMinutes * 60 * 1000);
  const minimumReadyAt = formatChinaLocalTimestamp(minimumReadyAtMs);
  const ready = parsed.timestamp * 1000 >= minimumReadyAtMs;
  return {
    platform: normalizedPlatform,
    configured: true,
    supportsScheduledPublish,
    minimumLeadMinutes,
    ready,
    reason: ready ? "" : "schedule_too_soon",
    scheduledPublishAt: parsed.display || scheduledPublishAt,
    minimumReadyAt,
  };
}

function expectedCollectionName(content) {
  return String(content.collection?.name || content.collection_name || content.playlist_name || content.playlist?.name || "").trim();
}

function expectedCoverPath(content) {
  return String(content.cover_path || content.copy_material?.cover_path || content.thumbnail_path || content.thumbnail?.local_path || "").trim();
}

export function deriveCompositeCollectionPolicyState(platform, content = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const overrides = content?.platform_specific_overrides && typeof content.platform_specific_overrides === "object"
    ? content.platform_specific_overrides
    : {};
  const collectionManagement = overrides.collection_management && typeof overrides.collection_management === "object"
    ? overrides.collection_management
    : {};
  let explicitCollectionName = expectedCollectionName(content);
  if (!explicitCollectionName) {
    explicitCollectionName = String(
      collectionManagement.target_collection_name
      || collectionManagement.collection_name
      || "",
    ).trim();
  }
  const collectionPolicy = String(
    overrides.collection_policy
    || content.collection_policy
    || "",
  ).trim().toLowerCase();
  const explicitCollectionSkip = Boolean(overrides.skip_collection_select || content.skip_collection_select)
    || COMPOSITE_COLLECTION_POLICY_SKIP_VALUES.has(collectionPolicy);
  const required = Boolean(compositePlatformCapabilities(normalizedPlatform).requires_explicit_collection_policy);
  return {
    platform: normalizedPlatform,
    required,
    collection_policy: collectionPolicy,
    explicit_collection_name: explicitCollectionName,
    explicit_collection_skip: explicitCollectionSkip,
    ready: !required || Boolean(explicitCollectionName) || explicitCollectionSkip,
  };
}

export function deriveCompositeCoverPolicyState(platform, content = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const overrides = content?.platform_specific_overrides && typeof content.platform_specific_overrides === "object"
    ? content.platform_specific_overrides
    : {};
  const coverPolicy = String(
    overrides.cover_policy
    || content.cover_policy
    || "",
  ).trim().toLowerCase();
  const explicitCoverPath = expectedCoverPath(content);
  const explicitCoverSkip = Boolean(overrides.skip_cover_upload || content.skip_cover_upload)
    || COMPOSITE_COVER_POLICY_SKIP_VALUES.has(coverPolicy);
  const required = Boolean(compositePlatformCapabilities(normalizedPlatform).requires_custom_cover_policy);
  return {
    platform: normalizedPlatform,
    required,
    cover_policy: coverPolicy,
    explicit_cover_path: explicitCoverPath,
    explicit_cover_skip: explicitCoverSkip,
    ready: !required || Boolean(explicitCoverPath) || explicitCoverSkip,
  };
}

export function shouldTreatCompositeEditorSurfaceAsNotReady(platform, routeUrl = "", hasInputFields = false, signals = {}) {
  const compositePublishPlatforms = new Set(["douyin", "bilibili", "youtube", "xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"]);
  return Boolean(
    compositePublishPlatforms.has(platform)
    && !hasInputFields
    && !signals?.upload_prompt_only
    && !/\/publish\/success\b/i.test(String(routeUrl || "")),
  );
}

export function deriveCompositeDraftPolicyBlockers(platform, content = {}, nowMs = Date.now()) {
  const normalizedContent = applyCompositeSafeRuntimePolicyDefaults(platform, content);
  const blockers = [];
  const coverPolicy = deriveCompositeCoverPolicyState(platform, normalizedContent);
  if (coverPolicy.required && !coverPolicy.ready) {
    blockers.push({
      field: "cover",
      code: `${coverPolicy.platform || platform}_cover_policy_missing`,
      message: "支持自定义封面的平台必须提供 cover_path，或显式声明跳过自定义封面后才能正式发布。",
      details: "missing_cover_policy",
      cover_policy: coverPolicy,
    });
  }
  const collectionPolicy = deriveCompositeCollectionPolicyState(platform, normalizedContent);
  if (collectionPolicy.required && !collectionPolicy.ready) {
    blockers.push({
      field: "collection",
      code: `${collectionPolicy.platform || platform}_collection_policy_missing`,
      message: "支持合集的平台必须明确选择合集，或显式声明跳过合集后才能正式发布。",
      details: "missing_collection_policy",
      collection_policy: collectionPolicy,
    });
  }
  const schedulePolicy = deriveCompositeSchedulePolicyState(platform, normalizedContent, nowMs);
  if (!schedulePolicy.ready) {
    blockers.push({
      field: "schedule",
      code: `${schedulePolicy.platform || platform}_scheduled_publish_window_invalid`,
      message: schedulePolicy.reason === "schedule_too_soon"
        ? `平台定时发布时间至少需要提前 ${schedulePolicy.minimumLeadMinutes} 分钟，当前时间不满足门禁。`
        : "平台定时发布时间格式无效，无法通过平台定时门禁。",
      details: schedulePolicy.reason || "invalid_schedule_window",
      schedule_policy: schedulePolicy,
    });
  }
  return blockers;
}

function expectedTags(content, limit = 12) {
  return Array.from(
    new Set([...(content.hashtags || []), ...(content.structured_tags || []), ...(content.tags || [])].map((item) => String(item || "").replace(/^#/, "").trim()).filter(Boolean)),
  ).slice(0, limit);
}

export function extractCompositeBodyForAudit(platform, value) {
  let text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  if (platform === "douyin") {
    text = text.replace(/^.*?作品描述\s*\d+\s*\/\s*\d+\s*/u, "");
    for (const marker of ["#添加话题", "@好友", "官方活动", "设置封面", "预览视频"]) {
      const index = text.indexOf(marker);
      if (index >= 0) {
        text = text.slice(0, index).trim();
        break;
      }
    }
    text = text.replace(/\s+(?:#[^\s#@]+(?:\s+#[^\s#@]+)*)\s*$/u, "").trim();
  }
  return text;
}

export function normalizeCompositeBodyForAudit(platform, value) {
  return extractCompositeBodyForAudit(platform, value).replace(/\s+/g, " ").trim().toLowerCase();
}

export function verifyCompositeBodyField(platform, expectedBody, actualBody, { tagVerified = false, textHaystack = "" } = {}) {
  const cleanBody = (currentPlatform, value) => {
    let text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    if (currentPlatform === "douyin") {
      text = text.replace(/^.*?作品描述\s*\d+\s*\/\s*\d+\s*/u, "");
      text = text.replace(/^定时[:：]?\s*\d{4}年\d{2}月\d{2}日\s*\d{2}:\d{2}\s*/u, "");
      for (const marker of ["#添加话题", "@好友", "官方活动", "设置封面", "预览视频"]) {
        const index = text.indexOf(marker);
        if (index >= 0) {
          text = text.slice(0, index).trim();
          break;
        }
      }
      text = text.replace(/(?:\s*#[^\s#@]+(?:\s+#[^\s#@]+)*)\s*$/u, "").trim();
    }
    return text.replace(/\s+/g, " ").trim().toLowerCase();
  };
  const expected = cleanBody(platform, expectedBody);
  if (!expected) return true;
  const actual = cleanBody(platform, actualBody || textHaystack);
  if (platform === "x") {
    if (!actual) return false;
    if (actual === expected || actual.includes(expected)) return true;
    const expectedTags = Array.from(new Set((String(expectedBody || "").match(/#[^\s#]+/g) || []).map((tag) => tag.toLowerCase())));
    const expectedShareLinks = Array.from(new Set((String(expectedBody || "").match(/https?:\/\/\S+/g) || []).map((link) => link.toLowerCase())));
    const expectedBodyOnly = cleanBody(
      platform,
      String(expectedBody || "")
        .replace(/https?:\/\/\S+/g, " ")
        .replace(/#[^\s#]+/g, " "),
    );
    const bodySatisfied = !expectedBodyOnly || actual.includes(expectedBodyOnly);
    const tagsSatisfied = expectedTags.every((tag) => actual.includes(tag));
    const linksSatisfied = expectedShareLinks.every((link) => actual.includes(link));
    return bodySatisfied && tagsSatisfied && linksSatisfied && Boolean(actual);
  }
  if (platform === "douyin") {
    const squash = (value) => String(value || "").replace(/\s+/g, "");
    const squashedExpected = squash(expected);
    const squashedActual = squash(actual);
    if (!squashedActual) return false;
    if (squashedActual === squashedExpected) return true;
    if (squashedExpected.includes(squashedActual)) return squashedActual.length >= Math.min(24, squashedExpected.length);
    if (squashedActual.startsWith(squashedExpected)) {
      const trailing = squashedActual.slice(squashedExpected.length);
      return trailing.length <= Math.max(6, Math.floor(squashedExpected.length * 0.12));
    }
    return false;
  }
  if (platform === "youtube") {
    const squash = (value) => String(value || "").replace(/\s+/g, "");
    const squashedExpected = squash(expectedBody);
    const squashedActual = squash(actualBody || textHaystack);
    if (!squashedExpected) return true;
    if (!squashedActual) return false;
    return squashedActual.includes(squashedExpected) || squashedExpected.includes(squashedActual);
  }
  return actual.includes(expected) || expected.includes(actual);
}

export function extractDouyinSelectedCollectionEvidence(lines = [], expectedCollection = "", inputFields = []) {
  const normalizedLines = (Array.isArray(lines) ? lines : [])
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const normalizedFields = (Array.isArray(inputFields) ? inputFields : [])
    .map((item) => ({
      label: String(item?.label || "").replace(/\s+/g, " ").trim(),
      value: String(item?.value || "").replace(/\s+/g, " ").trim(),
    }))
    .filter((item) => item.label || item.value);
  const placeholderPattern = /^(?:添加合集|请选择合集|加入合集|选择合集|合集)$/;
  const anchorPattern = /添加合集|请选择合集|加入合集|选择合集|合集/;
  const disallowedContext = /自主声明|请选择自主声明|定时发布|发布时间|作品描述|官方活动|设置封面|添加话题|@好友/;
  const byField = normalizedFields.find((item) => anchorPattern.test(item.label) && item.value && !placeholderPattern.test(item.value));
  if (byField) {
    return {
      actual: byField.value,
      matched: !expectedCollection || byField.value.includes(expectedCollection),
      placeholder_visible: false,
      source: "input_field",
    };
  }
  for (let index = 0; index < normalizedLines.length; index += 1) {
    const line = normalizedLines[index];
    if (!anchorPattern.test(line)) continue;
    for (let cursor = index + 1; cursor < Math.min(normalizedLines.length, index + 4); cursor += 1) {
      const candidate = normalizedLines[cursor];
      if (!candidate || placeholderPattern.test(candidate) || anchorPattern.test(candidate) || disallowedContext.test(candidate)) continue;
      return {
        actual: candidate,
        matched: !expectedCollection || candidate.includes(expectedCollection),
        placeholder_visible: false,
        source: "line_context",
      };
    }
  }
  const placeholderVisible = normalizedLines.some((line) => placeholderPattern.test(line)) || normalizedFields.some((item) => placeholderPattern.test(item.value));
  return {
    actual: "",
    matched: false,
    placeholder_visible: placeholderVisible,
    source: placeholderVisible ? "placeholder" : "missing",
  };
}

export function isDouyinCustomCoverReady({
  textHaystack = "",
  expectedCoverPath = "",
  coverActual = "",
  imageSources = [],
  backgroundSources = [],
} = {}) {
  return deriveDouyinCoverState({
    textHaystack,
    expectedCoverPath,
    coverActual,
    imageSources,
    backgroundSources,
  }).custom_cover_ready;
}

export function deriveDouyinCoverState({
  textHaystack = "",
  expectedCoverPath = "",
  coverActual = "",
  imageSources = [],
  backgroundSources = [],
  modalOpen = false,
} = {}) {
  const haystack = String(textHaystack || "").replace(/\s+/g, " ").trim();
  const expectedBase = String(expectedCoverPath || "").split(/[\\/]/).pop() || "";
  const actual = String(coverActual || "").trim();
  const normalizedImages = (Array.isArray(imageSources) ? imageSources : []).map((item) => String(item || ""));
  const normalizedBackgrounds = (Array.isArray(backgroundSources) ? backgroundSources : []).map((item) => String(item || ""));
  const hasLocalPreview = normalizedImages.some((src) => /^blob:|^data:image\//.test(src) || (expectedBase && src.includes(expectedBase)))
    || normalizedBackgrounds.some((src) => src.includes("blob:") || src.includes("data:image/") || (expectedBase && src.includes(expectedBase)));
  const explicitUploadSuccess = /重新上传|更换封面|封面已上传|上传封面成功|自定义封面|修改封面/.test(haystack);
  const aiOnlySurface = /ai智能推荐封面|智能推荐封面|默认截取第一帧/.test(haystack) && !explicitUploadSuccess;
  const generatingAiCover = /ai智能推荐封面生成中/.test(haystack);
  const dualCoverMissingWarning = /横\/竖双封面缺失|建议同时设置横版和竖版的封面/.test(haystack);
  const customCoverReady = !expectedBase
    || (actual && actual.includes(expectedBase))
    || (hasLocalPreview && explicitUploadSuccess && !aiOnlySurface && !dualCoverMissingWarning);
  const saved = Boolean(customCoverReady && !modalOpen && !generatingAiCover && !aiOnlySurface && !dualCoverMissingWarning);
  return {
    expected_base: expectedBase,
    custom_cover_ready: Boolean(customCoverReady),
    saved,
    actual,
    has_local_preview: hasLocalPreview,
    explicit_upload_success: explicitUploadSuccess,
    ai_only_surface: aiOnlySurface,
    generating_ai_cover: generatingAiCover,
    dual_cover_missing_warning: dualCoverMissingWarning,
    modal_open: Boolean(modalOpen),
  };
}

export function selectDouyinCoverConfirmCandidate(candidates = []) {
  const normalized = (Array.isArray(candidates) ? candidates : [])
    .map((item) => ({
      ...item,
      label: String(item?.label || "").replace(/\s+/g, " ").trim(),
      className: String(item?.className || item?.cls || "").replace(/\s+/g, " ").trim(),
      dialog_text: String(item?.dialog_text || "").replace(/\s+/g, " ").trim(),
    }))
    .filter((item) => item.label);
  if (!normalized.length) return null;
  const ranked = normalized
    .map((item) => {
      const label = item.label;
      const className = item.className.toLowerCase();
      const primary = /primary|confirm|submit|ok/.test(className);
      const saveLike = label === "保存" || label === "完成" || label === "应用" || label === "确定";
      const partialSaveLike = /保存|完成|应用|确定/.test(label);
      const cancelLike = /取消|关闭|返回/.test(label);
      const score = [
        saveLike ? 80 : 0,
        partialSaveLike ? 40 : 0,
        primary ? 15 : 0,
        cancelLike ? -120 : 0,
        item.dialog_text && /设置封面|取消保存|重新上传/.test(item.dialog_text) ? 8 : 0,
      ].reduce((sum, value) => sum + value, 0);
      return { ...item, score };
    })
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score || (right.y || 0) - (left.y || 0) || (right.x || 0) - (left.x || 0));
  return ranked[0] || null;
}

export function extractDouyinManageCardEvidence(value, expected = {}) {
  const clean = (input) => String(input || "").replace(/\s+/g, " ").trim();
  const normalizeTitleNeedle = (input) => clean(input).replace(/[\p{P}\p{S}\s]+/gu, "");
  const titleNeedles = (input) => {
    const normalized = normalizeTitleNeedle(input);
    if (!normalized) return [];
    const needles = [normalized];
    if (normalized.length >= 12) needles.push(normalized.slice(0, 12));
    if (normalized.length >= 18) needles.push(normalized.slice(0, 18));
    return Array.from(new Set(needles.filter(Boolean)));
  };
  const titleMatches = (haystack, needle) => {
    const cleanHaystack = clean(haystack);
    const cleanNeedle = clean(needle);
    if (!cleanHaystack || !cleanNeedle) return false;
    if (cleanHaystack.includes(cleanNeedle)) return true;
    const normalizedHaystack = normalizeTitleNeedle(cleanHaystack);
    return titleNeedles(cleanNeedle).some((item) => item && normalizedHaystack.includes(item));
  };
  const cleanBody = (input) => {
    let textValue = clean(input);
    if (!textValue) return "";
    textValue = textValue.replace(/^.*?作品描述\s*\d+\s*\/\s*\d+\s*/u, "");
    for (const marker of ["#添加话题", "@好友", "官方活动", "设置封面", "预览视频"]) {
      const index = textValue.indexOf(marker);
      if (index >= 0) {
        textValue = textValue.slice(0, index).trim();
        break;
      }
    }
    textValue = textValue.replace(/(?:\s*#[^\s#@]+(?:\s+#[^\s#@]+)*)\s*$/u, "").trim();
    return textValue.trim();
  };
  const text = clean(value);
  const expectedTitle = clean(expected.title || "");
  if (!text || !expectedTitle || !titleMatches(text, expectedTitle)) {
    return { title: "", body: "", schedule: "", tags: [], matched: false, text };
  }
  const titleIndex = text.indexOf(expectedTitle);
  const afterTitle = titleIndex >= 0 ? text.slice(titleIndex + expectedTitle.length).trim() : text;
  const scheduleMatch = text.match(/定时[:：]\s*(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}:\d{2})/);
  const schedule = scheduleMatch
    ? [scheduleMatch[1], "-", scheduleMatch[2], "-", scheduleMatch[3], " ", scheduleMatch[4]].join("")
    : "";
  const publishedAtMatch = text.match(/(\d{4})年(\d{2})月(\d{2})日\s*(\d{2}:\d{2})/);
  const publishedAt = publishedAtMatch
    ? [publishedAtMatch[1], "-", publishedAtMatch[2], "-", publishedAtMatch[3], " ", publishedAtMatch[4]].join("")
    : "";
  let body = afterTitle
    .replace(/\s*(继续编辑|编辑作品|设置权限|作品置顶|删除作品)[\s\S]*$/u, "")
    .trim();
  const trailingStatusIndex = body.search(/\s+(定时发布中|已发布|审核中|未通过)\b/u);
  if (trailingStatusIndex >= 0) body = body.slice(0, trailingStatusIndex).trim();
  const tags = Array.from(new Set([...(body.match(/#([^\s#@]+)/gu) || [])]
    .map((item) => clean(item).replace(/^#/, ""))
    .filter(Boolean)));
  body = cleanBody(body);
  return {
    title: expectedTitle,
    body,
    schedule,
    published_at: publishedAt,
    tags,
    matched: true,
    text,
  };
}

export function extractDouyinManageCardCandidates(lines = [], expected = {}) {
  const normalizedLines = (Array.isArray(lines) ? lines : String(lines || "").split(/[\n\r]+/))
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const normalizeTitleNeedle = (input) => String(input || "").replace(/[\p{P}\p{S}\s]+/gu, "");
  const titleMatches = (line, title) => {
    const cleanLine = String(line || "").replace(/\s+/g, " ").trim();
    const cleanTitle = String(title || "").replace(/\s+/g, " ").trim();
    if (!cleanLine || !cleanTitle) return false;
    if (cleanLine.includes(cleanTitle)) return true;
    const normalizedLine = normalizeTitleNeedle(cleanLine);
    const normalizedTitle = normalizeTitleNeedle(cleanTitle);
    if (!normalizedTitle) return false;
    return normalizedLine.includes(normalizedTitle)
      || (normalizedTitle.length >= 12 && normalizedLine.includes(normalizedTitle.slice(0, 12)))
      || (normalizedTitle.length >= 18 && normalizedLine.includes(normalizedTitle.slice(0, 18)));
  };
  const expectedTitle = String(expected.title || "").replace(/\s+/g, " ").trim();
  if (!expectedTitle) return [];
  const candidateLines = normalizedLines.length === 1
    ? normalizedLines[0]
      .split(/(?=\d{2}:\d{2}\s+)/u)
      .map((item) => String(item || "").replace(/\s+/g, " ").trim())
      .filter((item) => item && !/^(高清发布|首页|活动管理|内容管理|作品管理|合集管理)/.test(item))
    : normalizedLines;
  const titleIndexes = normalizedLines
    .map((line, index) => (titleMatches(line, expectedTitle) ? index : -1))
    .filter((index) => index >= 0);
  const segmentedTitleIndexes = candidateLines
    .map((line, index) => (titleMatches(line, expectedTitle) ? index : -1))
    .filter((index) => index >= 0);
  if (!titleIndexes.length && segmentedTitleIndexes.length) {
    return segmentedTitleIndexes
      .map((start) => {
        const rawLines = [candidateLines[start]];
        const candidate = extractDouyinManageCardEvidence(rawLines.join(" "), expected);
        if (!candidate.matched) return null;
        return {
          ...candidate,
          raw_lines: rawLines,
          line_start: start,
        };
      })
      .filter(Boolean);
  }
  if (!titleIndexes.length) {
    const fallback = extractDouyinManageCardEvidence(normalizedLines.join(" "), expected);
    return fallback.matched ? [{ ...fallback, raw_lines: normalizedLines.slice(0, 12), line_start: 0 }] : [];
  }
  const candidates = [];
  for (let idx = 0; idx < titleIndexes.length; idx += 1) {
    const start = titleIndexes[idx];
    const endExclusive = idx + 1 < titleIndexes.length
      ? titleIndexes[idx + 1]
      : Math.min(normalizedLines.length, start + 12);
    const rawLines = normalizedLines.slice(start, endExclusive);
    const candidate = extractDouyinManageCardEvidence(rawLines.join(" "), expected);
    if (candidate.matched) {
      candidates.push({
        ...candidate,
        raw_lines: rawLines,
        line_start: start,
      });
    }
  }
  return candidates;
}

export function selectBestDouyinManageCardEvidence(lines = [], expected = {}) {
  const candidates = extractDouyinManageCardCandidates(lines, expected);
  if (!candidates.length) {
    return { matched: false, candidates: [] };
  }
  const expectedSchedule = String(expected.schedule || "").trim();
  const expectedCreatedAt = String(expected.created_at || "").trim();
  const expectedCreatedAtDisplay = expectedCreatedAt
    ? parseChinaLocalSchedule(expectedCreatedAt).display
    : "";
  const expectedTags = Array.isArray(expected.tags)
    ? expected.tags.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const best = candidates
    .map((candidate) => {
      const tagChecks = expectedTags.map((tag) => ({ tag, present: candidate.tags.includes(tag) }));
      const tagPresentCount = tagChecks.filter((item) => item.present).length;
      const tagVerified = expectedTags.length > 0 && tagPresentCount === expectedTags.length;
      const bodyVerified = verifyCompositeBodyField("douyin", expected.body || "", candidate.body || "", { tagVerified });
      const scheduleVerified = !expectedSchedule || candidate.schedule === expectedSchedule;
      const publishedAtVerified = !expectedCreatedAtDisplay || candidate.published_at === expectedCreatedAtDisplay;
      const recencyBias = Math.max(0, 6 - Math.min(Number(candidate.line_start || 0), 60) / 10);
      const score = [
        candidate.matched ? 50 : 0,
        bodyVerified ? 30 : 0,
        scheduleVerified ? 20 : 0,
        publishedAtVerified ? 8 : 0,
        tagPresentCount * 4,
        candidate.body ? Math.min(candidate.body.length, 80) / 40 : 0,
        recencyBias,
      ].reduce((sum, value) => sum + value, 0);
      return {
        ...candidate,
        body_verified: bodyVerified,
        schedule_verified: scheduleVerified,
        published_at_verified: publishedAtVerified,
        tag_checks: tagChecks,
        recency_bias: recencyBias,
        score,
      };
    })
    .sort((left, right) => right.score - left.score || left.line_start - right.line_start)[0];
  return {
    ...best,
    matched: Boolean(best.matched),
    candidates,
  };
}

function _normalizeReceiptTitleNeedle(input) {
  return String(input || "").replace(/[\p{P}\p{S}\s]+/gu, "");
}

function _xiaohongshuTitleMatches(line, title) {
  const cleanLine = String(line || "").replace(/\s+/g, " ").trim();
  const cleanTitle = String(title || "").replace(/\s+/g, " ").trim();
  if (!cleanLine || !cleanTitle) return false;
  if (cleanLine.includes(cleanTitle)) return true;
  const normalizedLine = _normalizeReceiptTitleNeedle(cleanLine);
  const normalizedTitle = _normalizeReceiptTitleNeedle(cleanTitle);
  if (!normalizedTitle) return false;
  return normalizedLine.includes(normalizedTitle)
    || (normalizedTitle.length >= 8 && normalizedLine.includes(normalizedTitle.slice(0, 8)))
    || (normalizedTitle.length >= 12 && normalizedLine.includes(normalizedTitle.slice(0, 12)));
}

function _isXiaohongshuDurationLine(line) {
  return /^\d{2}:\d{2}$/.test(String(line || "").trim());
}

function _isXiaohongshuPublishedAtLine(line) {
  return /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$/.test(String(line || "").trim());
}

export function extractXiaohongshuNoteManagerCandidates(lines = [], expected = {}) {
  const normalizedLines = (Array.isArray(lines) ? lines : String(lines || "").split(/[\n\r]+/))
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const expectedTitle = String(expected.title || "").replace(/\s+/g, " ").trim();
  const candidates = [];
  for (let index = 0; index < normalizedLines.length; index += 1) {
    const publishedAt = normalizedLines[index];
    if (!_isXiaohongshuPublishedAtLine(publishedAt)) continue;
    const titleIndex = index - 1;
    if (titleIndex < 0) continue;
    const title = normalizedLines[titleIndex];
    if (!title || _isXiaohongshuDurationLine(title) || _isXiaohongshuPublishedAtLine(title)) continue;
    const duration = titleIndex > 0 && _isXiaohongshuDurationLine(normalizedLines[titleIndex - 1])
      ? normalizedLines[titleIndex - 1]
      : "";
    const afterLines = normalizedLines.slice(index + 1, Math.min(normalizedLines.length, index + 6));
    candidates.push({
      matched: expectedTitle ? _xiaohongshuTitleMatches(title, expectedTitle) : false,
      title,
      published_at: publishedAt,
      duration,
      raw_lines: [
        ...(duration ? [duration] : []),
        title,
        publishedAt,
        ...afterLines,
      ],
      line_start: duration ? titleIndex - 1 : titleIndex,
    });
  }
  return candidates;
}

export function selectBestXiaohongshuNoteManagerEvidence(lines = [], expected = {}) {
  const candidates = extractXiaohongshuNoteManagerCandidates(lines, expected);
  if (!candidates.length) {
    return { matched: false, candidates: [] };
  }
  const expectedTitle = String(expected.title || "").replace(/\s+/g, " ").trim();
  const expectedCreatedAtDisplay = String(expected.created_at || "").trim()
    ? parseChinaLocalSchedule(String(expected.created_at || "").trim()).display
    : "";
  const best = candidates
    .map((candidate) => {
      const titleExact = expectedTitle ? String(candidate.title || "").includes(expectedTitle) : false;
      const publishedAtVerified = !expectedCreatedAtDisplay || String(candidate.published_at || "").trim() === expectedCreatedAtDisplay;
      const recencyBias = Math.max(0, 6 - Math.min(Number(candidate.line_start || 0), 60) / 10);
      const score = [
        candidate.matched ? 60 : 0,
        titleExact ? 20 : 0,
        publishedAtVerified ? 8 : 0,
        recencyBias,
      ].reduce((sum, value) => sum + value, 0);
      return {
        ...candidate,
        title_verified: !expectedTitle || candidate.matched,
        published_at_verified: publishedAtVerified,
        recency_bias: recencyBias,
        score,
      };
    })
    .sort((left, right) => right.score - left.score || (left.line_start || 0) - (right.line_start || 0))[0];
  return best && best.matched
    ? { ...best, candidates }
    : { matched: false, candidates };
}

function _isToutiaoPublishedAtLine(line) {
  return /^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$/.test(String(line || "").trim())
    || /^\d{2}-\d{2}\s+\d{2}:\d{2}$/.test(String(line || "").trim());
}

export function extractToutiaoManageCandidates(lines = [], expected = {}) {
  const normalizedLines = (Array.isArray(lines) ? lines : String(lines || "").split(/[\n\r]+/))
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const expectedTitle = String(expected.title || "").replace(/\s+/g, " ").trim();
  const candidates = [];
  for (let index = 0; index < normalizedLines.length; index += 1) {
    const publishedAt = normalizedLines[index];
    if (!_isToutiaoPublishedAtLine(publishedAt)) continue;
    const titleIndex = index - 1;
    if (titleIndex < 0) continue;
    const title = normalizedLines[titleIndex];
    if (!title || _isToutiaoPublishedAtLine(title) || /^\d{2}:\d{2}$/.test(title)) continue;
    const beforeLines = normalizedLines.slice(Math.max(0, titleIndex - 1), titleIndex);
    const afterLines = normalizedLines.slice(index + 1, Math.min(normalizedLines.length, index + 6));
    candidates.push({
      matched: expectedTitle ? _xiaohongshuTitleMatches(title, expectedTitle) : false,
      title,
      published_at: publishedAt,
      raw_lines: [
        ...beforeLines,
        title,
        publishedAt,
        ...afterLines,
      ],
      line_start: titleIndex,
    });
  }
  return candidates;
}

export function selectBestToutiaoManageEvidence(lines = [], expected = {}) {
  const candidates = extractToutiaoManageCandidates(lines, expected);
  const expectedTitle = String(expected.title || "").replace(/\s+/g, " ").trim();
  const normalizedLines = (Array.isArray(lines) ? lines : String(lines || "").split(/[\n\r]+/))
    .map((item) => String(item || "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  const joinedText = normalizedLines.join(" ");
  if (!candidates.length) {
    if (expectedTitle && joinedText.includes(expectedTitle)) {
      const titleIndex = joinedText.indexOf(expectedTitle);
      const suffix = joinedText.slice(titleIndex + expectedTitle.length);
      const prefix = joinedText.slice(0, titleIndex);
      const nextPublishedAt = suffix.match(/(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})/);
      const previousPublishedAtMatches = [...prefix.matchAll(/(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})/g)];
      const previousPublishedAt = previousPublishedAtMatches.length
        ? previousPublishedAtMatches[previousPublishedAtMatches.length - 1][1]
        : "";
      return {
        matched: true,
        title: expectedTitle,
        title_verified: true,
        published_at: String((nextPublishedAt && nextPublishedAt[1]) || previousPublishedAt || "").trim(),
        raw_lines: normalizedLines.slice(0, 16),
        line_start: 0,
        candidates: [],
        compressed_manage_fallback: true,
      };
    }
    return { matched: false, candidates: [] };
  }
  const best = candidates
    .map((candidate) => {
      const titleExact = expectedTitle ? String(candidate.title || "").includes(expectedTitle) : false;
      const recencyBias = Math.max(0, 6 - Math.min(Number(candidate.line_start || 0), 60) / 10);
      const score = [
        candidate.matched ? 60 : 0,
        titleExact ? 20 : 0,
        recencyBias,
      ].reduce((sum, value) => sum + value, 0);
      return {
        ...candidate,
        title_verified: !expectedTitle || candidate.matched,
        recency_bias: recencyBias,
        score,
      };
    })
    .sort((left, right) => right.score - left.score || (left.line_start || 0) - (right.line_start || 0))[0];
  if (best && best.matched) {
    return { ...best, candidates };
  }
  if (expectedTitle && joinedText.includes(expectedTitle)) {
    const titleIndex = joinedText.indexOf(expectedTitle);
    const suffix = joinedText.slice(titleIndex + expectedTitle.length);
    const prefix = joinedText.slice(0, titleIndex);
    const nextPublishedAt = suffix.match(/(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})/);
    const previousPublishedAtMatches = [...prefix.matchAll(/(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|\d{2}-\d{2}\s+\d{2}:\d{2})/g)];
    const previousPublishedAt = previousPublishedAtMatches.length
      ? previousPublishedAtMatches[previousPublishedAtMatches.length - 1][1]
      : "";
    return {
      matched: true,
      title: expectedTitle,
      title_verified: true,
      published_at: String((nextPublishedAt && nextPublishedAt[1]) || previousPublishedAt || "").trim(),
      raw_lines: normalizedLines.slice(0, 16),
      line_start: 0,
      candidates,
      compressed_manage_fallback: true,
    };
  }
  return { matched: false, candidates };
}

async function setImageFileInputByAccept(client, imagePath) {
  const expectedPath = String(imagePath || "").trim();
  if (!expectedPath) return { uploaded: false, reason: "missing_image_path" };
  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const rootNodeId = documentResult.root.nodeId;
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: rootNodeId, selector: "input[type=file]" });
  const described = [];
  for (const nodeId of queryResult.nodeIds || []) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    described.push({ nodeId, attrMap });
  }
  const preferred =
    described.find((item) => /image|png|jpe?g|webp/i.test(item.attrMap.accept || "")) ||
    described.find((item) => !/video|mp4/i.test(item.attrMap.accept || ""));
  if (!preferred) return { uploaded: false, reason: "no_image_file_input", fileInputs: described.map((item) => item.attrMap) };
  await client.send("DOM.setFileInputFiles", { nodeId: preferred.nodeId, files: [expectedPath] });
  await dispatchFileInputEvents(client, preferred.nodeId);
  return { uploaded: true, expected_path: expectedPath, input: preferred.attrMap, fileInputCount: described.length };
}

async function openXiaohongshuCoverEditor(client) {
  const alreadyOpen = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const modal = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .find((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    const imageInput = [...document.querySelectorAll("input[type=file]")]
      .find((el) => /image|png|jpe?g|webp/i.test(el.getAttribute("accept") || el.accept || ""));
    return { open: Boolean(modal || imageInput), has_image_input: Boolean(imageInput), modal_text: clean(modal?.innerText || modal?.textContent).slice(0, 160) };
  })()`, 10000);
  if (alreadyOpen.open) return { opened: true, already_open: true, ...alreadyOpen };

  const coords = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const card =
      document.querySelector(".publish-page-content-cover .default.column") ||
      [...document.querySelectorAll("div,span")]
        .filter(visible)
        .find((el) => /修改封面|智能推荐封面|默认截取第一帧/.test(clean(el.innerText || el.textContent))) ||
      document.querySelector(".publish-page-content-cover");
    if (!visible(card)) return { found: false };
    card.scrollIntoView({ block: "center", inline: "center" });
    const rect = card.getBoundingClientRect();
    return {
      found: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      label: clean(card.innerText || card.textContent).slice(0, 120),
      className: String(card.className || ""),
    };
  })()`, 10000);
  if (!coords.found) return { opened: false, reason: "cover_card_not_found", coords };

  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: coords.x, y: coords.y, button: "none" }).catch(() => {});
  await sleep(800);
  const clickCoords = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const operator =
      document.querySelector(".publish-page-content-cover .operator") ||
      [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .find((el) => /修改封面/.test(clean(el.innerText || el.textContent)));
    const target = visible(operator) ? operator : document.querySelector(".publish-page-content-cover .default.column");
    if (!visible(target)) return { found: false };
    const rect = target.getBoundingClientRect();
    return {
      found: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      label: clean(target.innerText || target.textContent).slice(0, 120),
      className: String(target.className || ""),
    };
  })()`, 10000);
  if (!clickCoords.found) return { opened: false, reason: "cover_operator_not_found", coords, clickCoords };
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: clickCoords.x, y: clickCoords.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: clickCoords.x, y: clickCoords.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: clickCoords.x, y: clickCoords.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1600);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el, index) => ({
      index,
      accept: el.getAttribute("accept") || el.accept || "",
      visible: visible(el),
    }));
    const modal = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .find((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    return {
      opened: Boolean(modal || fileInputs.some((input) => /image|png|jpe?g|webp/i.test(input.accept))),
      has_image_input: fileInputs.some((input) => /image|png|jpe?g|webp/i.test(input.accept)),
      modal_text: clean(modal?.innerText || modal?.textContent).slice(0, 200),
      fileInputs,
    };
  })()`, 10000);
  return { opened: Boolean(after.opened), coords, clickCoords, ...after };
}

async function clickXiaohongshuCoverConfirm(client) {
  const target = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => /设置封面|上传图片|封面比例/.test(item.text))
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      const button = [...dialog.el.querySelectorAll("button,[role=button]")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const className = clean(typeof el.className === "string" ? el.className : "");
          return { el, label: clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title")), className, area: rect.width * rect.height, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        })
        .filter((item) => item.label === "确定" && !/disabled/.test(item.className))
        .sort((left, right) => left.area - right.area || right.y - left.y)[0];
      if (!button) continue;
      return { found: true, label: button.label, x: button.x, y: button.y };
    }
    return { clicked: false, dialogs: dialogs.map((item) => item.text.slice(0, 160)) };
  })()`, 10000);
  if (!target.found) return target;
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1800);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .some((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    return { modal_open: modalOpen, body_has_modify_cover: /修改封面/.test(clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "")) };
  })()`, 10000);
  if (after.modal_open) {
    const stale = await clearXiaohongshuStaleCoverLayers(client);
    if (stale.removed_count) {
      const cleared = await evaluateWithClient(client, `(() => {
        const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        };
        const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
          .filter(visible)
          .some((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
        return { modal_open: modalOpen, body_has_modify_cover: /修改封面/.test(clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "")) };
      })()`, 10000);
      return { clicked: true, label: target.label, input_click: { x: target.x, y: target.y }, stale_cover_layers_cleared: stale, ...cleared };
    }
  }
  return { clicked: true, label: target.label, input_click: { x: target.x, y: target.y }, ...after };
}

async function clearXiaohongshuStaleCoverLayers(client) {
  return evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const stale = [...document.querySelectorAll(".d-modal-mask,[class*=modal]")]
      .filter((el) => /portal-fade-leave-active/.test(String(el.className || "")) && /设置封面/.test(clean(el.innerText || el.textContent)));
    const removed = stale.map((el) => clean(el.innerText || el.textContent).slice(0, 160));
    for (const el of stale) el.remove();
    if (removed.length) {
      document.documentElement.style.overflowY = "";
      const hostBody = document.body || document.documentElement || document.scrollingElement;
      if (hostBody) {
        hostBody.style.overflow = "";
        if (typeof hostBody.removeAttribute === "function") hostBody.removeAttribute("aria-expanded");
      }
    }
    return { removed_count: removed.length, removed };
  })()`, 10000);
}

async function waitForCompositeUploadReady(client, platform, timeoutMs = 120000, mediaPath = "", onPoll = null, options = {}) {
  const startedAt = Date.now();
  const mediaName = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  const mediaStem = mediaName.replace(/\.[^.]+$/, "");
  let last = null;
  let readyStreak = 0;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify({ mediaName, mediaStem })};
      const isYouTubeEditorSurface = ${isYouTubeEditorReadinessSurface.toString()};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
      const href = String(location.href || "");
      const failed = /上传失败|Upload failed|刷新后重试|网络异常/.test(text);
      const uploadProgressSignal = /已上传：|当前速度：|剩余时间：|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%|\\b\\d{1,3}%\\b/.test(text);
      const genericUploadBusySignal = /上传中|正在上传|视频处理中/.test(text);
      const kuaishouReadySurface =
        ${JSON.stringify(platform)} === "kuaishou" &&
        /重新上传/.test(text) &&
        /预览作品|预览封面|编辑画布|封面设置/.test(text) &&
        /作品描述|发布时间|发布设置/.test(text) &&
        !/上传失败/.test(text);
      const douyinReadySurface =
        ${JSON.stringify(platform)} === "douyin" &&
        (text.includes("预览视频") || text.includes("预览封面/标题") || text.includes("预览封面")) &&
        text.includes("重新上传") &&
        (text.includes("作品描述") || text.includes("发布时间") || text.includes("发布设置") || text.includes("谁可以看")) &&
        !/上传失败|已上传：|当前速度：|剩余时间：|\\b\\d{1,3}%\\b/.test(text);
      const bilibiliReadySurface =
        ${JSON.stringify(platform)} === "bilibili" &&
        /更换视频|上传完成|已经上传：/.test(text) &&
        /标题|简介|分区|标签|创作声明|定时发布|立即投稿|存草稿/.test(text);
      const bilibiliConcreteUploadProgress =
        ${JSON.stringify(platform)} === "bilibili" &&
        /已上传：|当前速度：|剩余时间：|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%|\\b\\d{1,3}%\\b/.test(text);
      const mediaPresent =
        !expected.mediaName ||
        text.includes(expected.mediaName) ||
        text.includes(expected.mediaStem) ||
        kuaishouReadySurface ||
        douyinReadySurface ||
        bilibiliReadySurface;
      const uploadPromptOnly = /拖拽视频到此|点击上传|上传视频\\s+视频大小|选择文件|Select files/.test(text) && !mediaPresent;
      const busy = !failed && (
        uploadProgressSignal ||
        (
          genericUploadBusySignal &&
          !douyinReadySurface &&
          !kuaishouReadySurface &&
          !(bilibiliReadySurface && !bilibiliConcreteUploadProgress)
        )
      );
      const fileInputCount = [...document.querySelectorAll("input[type=file]")].filter((input) => {
        const rect = input.getBoundingClientRect();
        const style = getComputedStyle(input);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      }).length;
      const totalFileInputCount = [...document.querySelectorAll("input[type=file]")].length;
      const youtubeUploadRoute = /studio\\.youtube\\.com\\/channel\\/[^/?#]+\\/(videos\\/)?upload/.test(href);
      const youtubeUploadDialogRoute = ${hasYoutubeUploadDialogQuery.toString()}(href);
      const youtubeUploadDialogSurface = /上传视频|Upload videos|Select files|拖拽|点击上传|选择文件/.test(text);
      const youtubeEditorSurface = isYouTubeEditorSurface(href, text);
      const youtubeChannelContentList = !youtubeEditorSurface && (/频道内容/.test(text) || /每页行数|发布日期|第\\s*\\d+\\s*-\\s*\\d+\\s*条/.test(text));
      const youtubeDraftResumeAvailable = !youtubeEditorSurface && mediaPresent && /编辑草稿|Edit draft/.test(text) && /草稿|Draft/.test(text);
      const youtubeHasEditorSurface = youtubeUploadDialogSurface || fileInputCount > 0 || youtubeEditorSurface;
      const youtubeReady = youtubeEditorSurface
        ? mediaPresent && !busy
        : (!youtubeUploadRoute || youtubeChannelContentList ? false : mediaPresent && !uploadPromptOnly && youtubeHasEditorSurface && !busy);
      const ready = ${JSON.stringify(platform)} === "youtube"
        ? youtubeReady
        : mediaPresent && !uploadPromptOnly && (/上传成功|上传完成|检测完成|发布|定时发布|立即发布|封面应用成功|极速上传成功/.test(text) || kuaishouReadySurface || douyinReadySurface) && !busy;
      const lines = text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /上传|处理|检测|发布|%/.test(line)).slice(0, 50);
      return {
        platform: ${JSON.stringify(platform)},
        href,
        ready,
        busy,
        failed,
        mediaPresent,
        uploadPromptOnly,
        fileInputCount,
        totalFileInputCount,
        youtubeUploadRoute,
        youtubeUploadDialogRoute,
        youtubeUploadDialogSurface,
        youtubeEditorSurface,
        youtubeChannelContentList,
        youtubeDraftResumeAvailable,
        youtubeHasEditorSurface,
        kuaishouReadySurface,
        douyinReadySurface,
        expected,
        lines,
      };
    })()`, 10000);
    readyStreak = last.ready ? readyStreak + 1 : 0;
    if (typeof onPoll === "function") {
      onPoll({
        ready: Boolean(last.ready),
        failed: Boolean(last.failed),
        waited_ms: Date.now() - startedAt,
        ready_streak: readyStreak,
        last,
      });
    }
    const waitedMs = Date.now() - startedAt;
    if (String(platform || "").trim() === "youtube" && last.youtubeDraftResumeAvailable) {
      return {
        ready: false,
        failed: false,
        waited_ms: waitedMs,
        ready_streak: readyStreak,
        last,
      };
    }
    const failureState = deriveCompositeUploadReadinessFailureState(
      platform,
      {
        ready: Boolean(last.ready),
        failed: Boolean(last.failed),
        waited_ms: waitedMs,
        last,
      },
      options,
    );
    if (failureState.failed) {
      return {
        ready: false,
        failed: true,
        failure_reason: failureState.reason,
        waited_ms: waitedMs,
        last,
      };
    }
    if (shouldAcceptCompositeUploadReadyState(platform, last, readyStreak, Date.now() - startedAt)) {
      return { ready: true, waited_ms: Date.now() - startedAt, ready_streak: readyStreak, last };
    }
    await sleep(5000);
  }
  return { ready: false, waited_ms: Date.now() - startedAt, ready_streak: readyStreak, last };
}

export function expectedMediaPath(content) {
  const mediaItems = Array.isArray(content.media_items) ? content.media_items : [];
  return String(
    mediaItems.find((item) => item && item.local_path)?.local_path
      || content.media_path
      || (content.media_urls || [])[0]
      || "",
  ).trim();
}

function compositeUploadTimeoutMs(platform) {
  if (platform === "douyin" || platform === "toutiao" || platform === "xiaohongshu") return 900000;
  if (platform === "youtube") return 240000;
  if (platform === "kuaishou" || platform === "bilibili") return 300000;
  return 180000;
}

function compositeUploadReadinessTimeoutMs(platform, captureResponseTimeoutMs = 0) {
  const uploadTimeout = compositeUploadTimeoutMs(platform);
  const captureTimeout = _coerceRecoveryTimeoutMs(captureResponseTimeoutMs, 0);
  return Math.max(uploadTimeout, captureTimeout);
}

async function ensureYoutubeUploadEditor(client, titleHint = "") {
  const route = await evaluateWithClient(client, `(() => {
    const extractYouTubeDraftVideoId = ${extractYouTubeDraftVideoId.toString()};
    const selectDraftResumeCandidate = ${selectYouTubeDraftResumeCandidate.toString()};
    const buildUploadResumeUrl = ${buildYouTubeUploadResumeUrl.toString()};
    const buildContentListUrl = ${buildYouTubeStudioContentListUrl.toString()};
    const shouldTreatUploadSurfaceAsStable = ${shouldTreatYouTubeUploadSurfaceAsStable.toString()};
    const titleHint = ${JSON.stringify(String(titleHint || "").trim())};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const href = String(location.href || "");
    const match = href.match(/https:\\/\\/studio\\.youtube\\.com\\/channel\\/([^/?#]+)/);
    if (!match) return { matched: false, current: href, reason: "missing_channel_id" };
    const channel = match[1];
    const text = clean((document.scrollingElement || document.documentElement || document.body)?.innerText || "");
    const uploadDialogSurface = /上传视频|Upload videos|Select files|拖拽|选择文件|立即投稿|Create/.test(text);
    const allFileInputs = [...document.querySelectorAll("input[type=file]")];
    const visibleInputs = allFileInputs.filter((input) => {
      const rect = input.getBoundingClientRect();
      const style = getComputedStyle(input);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    });
    const videoCapableInputs = allFileInputs.filter((input) => {
      const accept = String(input.getAttribute("accept") || input.accept || "").trim().toLowerCase();
      if (!accept) return true;
      return /video|mp4|mov|mkv|webm|avi|mpeg|quicktime/.test(accept);
    });
    const uploadDialogRoute = ${hasYoutubeUploadDialogQuery.toString()}(href);
    const uploadResumeRoute = ${hasYoutubeUploadResumeVideoId.toString()}(href);
    const channelContentList = /频道内容|每页行数|第\\s*\\d+\\s*-\\s*\\d+\\s*条|添加说明|编辑草稿|草稿|发布日期/.test(text);
    const draftRows = [...document.querySelectorAll("ytcp-video-row,[role=row]")]
      .map((row) => {
        const watchAnchor = row.querySelector("a#anchor-watch-on-yt,a[href*='watch?v=']");
        const titleAnchor = row.querySelector("#video-title,a#video-title,a[href*='/video/'][href*='/edit']");
        return {
          text: clean(row.innerText || row.textContent || ""),
          watchHref: String(watchAnchor?.href || watchAnchor?.getAttribute?.("href") || "").trim(),
          titleHref: String(titleAnchor?.href || titleAnchor?.getAttribute?.("href") || "").trim(),
        };
      })
      .filter((row) => /草稿|Draft/i.test(row.text) && /编辑草稿|Edit draft/i.test(row.text))
      .slice(0, 24);
    const selectedDraft = selectDraftResumeCandidate(draftRows, titleHint);
    const draftWatchHref = String(selectedDraft?.watchHref || "").trim();
    const draftTitleHref = String(selectedDraft?.titleHref || "").trim();
    const draftVideoId = extractYouTubeDraftVideoId(draftWatchHref, draftTitleHref || href);
    const uploadResumeTarget = buildUploadResumeUrl(href, draftVideoId);
    const contentListUrl = buildContentListUrl(channel);
    const uploadUrls = [
      "https://studio.youtube.com/channel/" + channel + "/videos/upload",
      "https://studio.youtube.com/channel/" + channel + "/upload",
    ];
    const onContentList = href.startsWith(contentListUrl);
    const alreadyOnUpload = uploadUrls.some((item) => href.startsWith(item));
    if (onContentList && channelContentList) {
      return {
        matched: true,
        channel,
        current: href,
        changed: false,
        uploadDialogSurface,
        uploadDialogRoute,
        uploadResumeRoute,
        fileInputs: visibleInputs.length,
        totalFileInputs: allFileInputs.length,
        videoCapableFileInputs: videoCapableInputs.length,
        uploadUrls: [contentListUrl, ...uploadUrls],
        channelContentList,
        draftVideoId,
        draftWatchHref,
        draftTitleHref,
        selectedDraftText: String(selectedDraft?.text || ""),
      };
    }
    if (alreadyOnUpload && channelContentList && !uploadResumeRoute && uploadResumeTarget && uploadResumeTarget !== href) {
      return {
        matched: true,
        channel,
        current: href,
        changed: true,
        targets: [uploadResumeTarget, contentListUrl, ...uploadUrls],
        target: uploadResumeTarget,
        fallbackTarget: contentListUrl,
        uploadDialogSurface,
        uploadDialogRoute,
        uploadResumeRoute,
        fileInputs: visibleInputs.length,
        totalFileInputs: allFileInputs.length,
        uploadUrls,
        channelContentList,
        draftVideoId,
        draftWatchHref,
        draftTitleHref,
        selectedDraftText: String(selectedDraft?.text || ""),
      };
    }
    const hasUploadSurface = shouldTreatUploadSurfaceAsStable({
      uploadResumeRoute,
      channelContentList,
      uploadDialogSurface: uploadDialogRoute || uploadDialogSurface,
      visibleFileInputCount: visibleInputs.length,
      videoCapableFileInputCount: videoCapableInputs.length,
    });
    if (alreadyOnUpload && hasUploadSurface) {
      return {
        matched: true,
        channel,
        current: href,
        changed: false,
        uploadDialogSurface,
        uploadDialogRoute,
        uploadResumeRoute,
        fileInputs: visibleInputs.length,
        totalFileInputs: allFileInputs.length,
        videoCapableFileInputs: videoCapableInputs.length,
        uploadUrls,
        channelContentList,
        draftVideoId,
        draftWatchHref,
        draftTitleHref,
        selectedDraftText: String(selectedDraft?.text || ""),
      };
    }
    return {
      matched: true,
      channel,
      current: href,
      changed: true,
      targets: [contentListUrl, ...uploadUrls],
      target: contentListUrl,
      fallbackTarget: uploadUrls[0],
      uploadDialogSurface,
      uploadDialogRoute,
      fileInputs: visibleInputs.length,
      totalFileInputs: allFileInputs.length,
      videoCapableFileInputs: videoCapableInputs.length,
      channelContentList,
    };
  })()`, 10000);
  if (!route.matched || !route.changed) return route;
  await evaluateWithClient(client, `(() => { location.href = ${JSON.stringify(route.target)}; return { navigated: true, target: ${JSON.stringify(route.target)} }; })()`, 10000);
  return route;
}

export async function activateYoutubeHiddenUploadEntry(client) {
  return evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const item = document.querySelector('tp-yt-paper-item[test-id="upload"], [test-id="upload"][role="menuitem"]');
    if (!item) return { clicked: false, reason: "hidden_upload_item_not_found" };
    const click = (el) => {
      if (!el) return;
      try { if (typeof el.click === "function") el.click(); } catch {}
      const rect = typeof el.getBoundingClientRect === "function" ? el.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        try { el.dispatchEvent(new MouseEvent(type, eventInit)); } catch {}
      }
    };
    const beforeHref = String(location.href || "");
    click(item);
    click(item.querySelector("yt-formatted-string, .text-content, tp-yt-paper-item-body, div, span"));
    const afterHref = String(location.href || "");
    return {
      clicked: true,
      hidden: true,
      label: clean(item.innerText || item.textContent || item.getAttribute("aria-label")),
      before_href: beforeHref,
      after_href: afterHref,
      route_changed: beforeHref !== afterHref,
    };
  })()`, 10000);
}

async function uploadYoutubeVideoForComposite(client, mediaPath) {
  const mediaName = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  const mediaStem = mediaName.replace(/\.[^.]+$/, "");
  const route = await ensureYoutubeUploadEditor(client, mediaStem);
  if (route.changed) await sleep(2600);
  const firstUpload = await setFirstVideoFileInput(client, mediaPath);
  if (firstUpload.uploaded) return firstUpload;
  if (route.fallbackTarget) {
    await evaluateWithClient(client, `(() => { location.href = ${JSON.stringify(route.fallbackTarget)}; return { navigated: true, target: ${JSON.stringify(route.fallbackTarget)} }; })()`, 10000);
    await sleep(3000);
    const fallbackUpload = await setFirstVideoFileInput(client, mediaPath);
    if (fallbackUpload.uploaded) return fallbackUpload;
  }
  await sleep(3000);
  return await setFirstVideoFileInput(client, mediaPath);
}

async function ensureXCompose(client) {
  const state = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const pathname = String(location.pathname || "").toLowerCase();
    const isCompose = /\\/compose/.test(pathname);
    if (isCompose) {
      return { compose_ready: true, composed_by_url: true, url: location.href, method: "already_on_compose" };
    }
    const clickElement = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      el.scrollIntoView({ block: "center", inline: "center" });
      const eventInit = {
        bubbles: true,
        cancelable: true,
        view: window,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
      };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        el.dispatchEvent(new MouseEvent(type, eventInit));
      }
      return true;
    };
    const links = [...document.querySelectorAll("a[href]")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title")), href: String(el.getAttribute("href") || "").toLowerCase() }))
      .filter((item) => /\\/compose/.test(item.href) || /compose/.test(item.text));
    const linkTarget = links.find((item) => item.href.includes("/compose")) || links[0];
    if (linkTarget?.el && clickElement(linkTarget.el)) {
      return { compose_ready: false, method: "compose_link_click", text: linkTarget.text, target: linkTarget.href };
    }
    const controls = [...document.querySelectorAll("button,[role=button],div,span")]
      .filter(visible)
      .map((el) => ({
        el,
        text: clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title")),
      }))
      .filter((item) => /发布|发推|post|tweet|compose/.test(item.text.toLowerCase()));
    const control = controls
      .filter((item) => /发布|发推|tweet|compose/i.test(item.text))
      .sort((left, right) => left.text.length - right.text.length)[0];
    if (control?.el && clickElement(control.el)) {
      return { compose_ready: false, method: "compose_control_click", text: control.text };
    }
    return { compose_ready: false, method: "no_entry_found" };
  })()`, 10000);
  if (state.compose_ready && state.composed_by_url) return state;
  if (state.compose_ready) return state;
  await sleep(900);
  const final = await evaluateWithClient(client, `(() => {
    const pathname = String(location.pathname || "").toLowerCase();
    return {
      compose_ready: /\\/compose/.test(pathname),
      before: pathname,
      url: location.href,
    };
  })()`, 10000);
  if (final.compose_ready) return { ...state, ...final, method: "after_interaction" };
  await evaluateWithClient(client, `(() => {
    location.href = ${JSON.stringify(PLATFORM_PUBLISH_ENTRY_URLS.x)};
    return { navigated: true, url: location.href };
  })()`, 10000);
  await sleep(1500);
  const fallback = await evaluateWithClient(client, `(() => {
    const pathname = String(location.pathname || "").toLowerCase();
    return { compose_ready: /\\/compose/.test(pathname), url: location.href };
  })()`, 10000);
  return { ...state, ...fallback, method: "compose_entry_fallback", composed_by_url: fallback.compose_ready };
}

async function ensureCompositeUploadReady(client, platform, content, timeoutMs = 120000, onPoll = null, options = {}) {
  const actions = [];
  const mediaPath = expectedMediaPath(content);
  let readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath, onPoll, options);
  actions.push({ kind: `${platform}_upload_ready_wait`, ...readiness });
  if (readiness.ready) return { actions, readiness };
  if (readiness.last?.busy) {
    actions.push({ kind: `${platform}_upload_reupload_skipped`, skipped: true, reason: "upload_still_in_progress" });
    return { actions, readiness };
  }
  if (platform === "youtube") {
    const readinessBeforeResume = readiness;
    const youtubeResumeDisposition = deriveCurrentPageDraftResumeDisposition(
      platform,
      Array.isArray(readiness.last?.lines) ? readiness.last.lines.join(" ") : "",
    );
    if (youtubeResumeDisposition.present) {
      const titleHints = [];
      if (String(content?.title || "").trim()) titleHints.push(String(content.title).trim());
      if (String(mediaPath || "").trim()) titleHints.push(path.win32.basename(String(mediaPath || "")).replace(/\.[^.]+$/, ""));
      let resume = await clickYouTubeDraftResumeEntry(client, titleHints);
      if (!resume.clicked) resume = await clickByText(client, [youtubeResumeDisposition.resume_label]);
      if (!resume.clicked) resume = await clickLooseText(client, [youtubeResumeDisposition.resume_label]);
      actions.push({ kind: "youtube_draft_resume", ...resume, reason: youtubeResumeDisposition.reason });
      if (resume.clicked) {
        await sleep(2200);
        readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath, onPoll, options);
        actions.push({ kind: `${platform}_upload_ready_wait_after_draft_resume`, ...readiness });
        if (readiness.ready || readiness.failed || readiness.last?.busy) return { actions, readiness };
        for (let fallbackAttempt = 0; fallbackAttempt < 2; fallbackAttempt += 1) {
          if (!shouldAttemptYouTubeDraftResumeFallbackRoute(readiness, resume)) break;
          const fallback = deriveYouTubeDraftResumeFallbackTarget(resume, String(readiness.last?.href || ""));
          if (!fallback.target) break;
          actions.push({
            kind: fallbackAttempt === 0 ? "youtube_draft_resume_direct_route" : "youtube_draft_resume_secondary_route",
            target: fallback.target,
            reason: fallback.reason,
          });
          await evaluateWithClient(client, `(() => {
            location.href = ${JSON.stringify(fallback.target)};
            return { navigated: true, target: ${JSON.stringify(fallback.target)} };
          })()`, 10000).catch(() => null);
          await sleep(2600);
          readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath, onPoll, options);
          actions.push({
            kind: fallbackAttempt === 0
              ? `${platform}_upload_ready_wait_after_draft_resume_route`
              : `${platform}_upload_ready_wait_after_draft_resume_secondary_route`,
            ...readiness,
          });
          if (readiness.ready || readiness.failed || readiness.last?.busy) return { actions, readiness };
        }
        if (shouldFailYouTubeDraftResumeAsInert(readinessBeforeResume, readiness, resume)) {
          readiness = {
            ...readiness,
            failed: true,
            failure_reason: "upload_not_applied",
            pending_reason: "draft_resume_inert",
          };
          actions.push({
            kind: "youtube_draft_resume_inert",
            failed: true,
            reason: "draft_resume_inert",
            target_id: resume.target_id || "",
            label: resume.label || "",
          });
          return { actions, readiness };
        }
        if (shouldDeferYouTubeDraftResumeReupload(readiness)) {
          readiness = {
            ...readiness,
            pending_reason: "draft_resume_pending",
          };
          actions.push({
            kind: "youtube_upload_reupload_skipped",
            skipped: true,
            reason: "draft_resume_pending",
          });
          return { actions, readiness };
        }
      }
    }
  }
  if (
    (platform !== "youtube" || readiness.last?.youtubeUploadRoute) &&
    (platform !== "youtube" || !readiness.last?.youtubeChannelContentList) &&
    readiness.last?.mediaPresent &&
    !readiness.last?.uploadPromptOnly
  ) {
    actions.push({ kind: `${platform}_upload_reupload_skipped`, skipped: true, reason: "media_present_but_not_ready" });
    return { actions, readiness };
  }

  const reuploadTexts = ["重新上传", "刷新", "重试", "选择视频", "点击上传", "上传视频", "发布视频", "发表视频", "Upload videos", "Create"];
  actions.push({ kind: `${platform}_upload_reupload_entry`, ...(await clickByText(client, reuploadTexts)) });
  await sleep(1200);
  const upload = await setFirstVideoFileInput(client, mediaPath);
  actions.push({ kind: `${platform}_upload_reupload`, ...upload });
  if (upload.uploaded) {
    await sleep(16000);
    readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath, onPoll, {
      ...options,
      syntheticUploadExpected: true,
    });
    actions.push({ kind: `${platform}_upload_ready_after_reupload`, ...readiness });
  }
  return { actions, readiness };
}

async function readCompositeMaterialIntegrity(client, platform, content) {
  const rawTitle = String(content.title || "").trim();
  const rawBody = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  const title = platform === "x" ? "" : rawTitle;
  const body = ["xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"].includes(platform) && tags.length
    ? `${platform === "kuaishou" && rawTitle ? `${rawTitle}\n` : ""}${rawBody}\n${tags.map((tag) => `#${tag}`).join(" ")}`
    : rawBody;
  const collection = expectedCollectionName(content);
  const coverPath = platform === "x" ? "" : expectedCoverPath(content);
  const declaration = expectedCompositeDeclaration(content, platform);
  const schedule = parseChinaLocalSchedule(content.scheduled_publish_at || "");
  const result = await evaluateWithClient(client, `(() => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ title, body, tags, collection, coverPath, declaration, scheduleDisplay: schedule.display })};
    const extractBody = ${extractCompositeBodyForAudit.toString()};
    const extractDouyinCollection = ${extractDouyinSelectedCollectionEvidence.toString()};
    const verifyBody = ${verifyCompositeBodyField.toString()};
    const verifyDeclaration = ${verifyCompositeDeclarationField.toString()};
    const detectSignals = ${detectCompositePublicationSignals.toString()};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const bodyText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const lines = bodyText.split(/[\\n\\r]+| {2,}/).map(clean).filter(Boolean);
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const fileInputs = [...document.querySelectorAll("input[type=file]")].filter(visible);
    const authPatterns = /请先登录|登录已过期|登录失效|未登录|请先登录|session|账户已退出|need.?to.?log.?in|sign.?in|log.?in/i;
    const verification_by_url = {
      douyin: /creator\\.(douyin\\.com|volcengine\\.com).*?(creator-micro\\/content\\/post\\/video|content\\/post\\/video)/i,
      xiaohongshu: /creator\\.xiaohongshu\\.com/i,
      bilibili: /member\\.bilibili\\.com\\/(platform\\/upload\\/video|video|upload)/i,
      kuaishou: /cp\\.kuaishou\\.com/i,
      toutiao: /mp\\.toutiao\\.com\\/profile_v4\\/xigua\\/upload-video/i,
      "wechat-channels": /channels\\.weixin\\.qq\\.com\\/platform\\/post\\/create/i,
      youtube: /studio\\.youtube\\.com/i,
      x: /x\\.com|twitter\\.com/i,
    };
    const verification_by_text = {
      douyin: /发布|抖音|作品|标题|简介|描述|视频|封面|投稿|合集|标签|定时|评论/.test(bodyText),
      xiaohongshu: /发布|封面|标题|正文|笔记|话题|合集|原创|上传|发布管理/.test(bodyText),
      bilibili: /投稿|标题|简介|分区|合集|创作声明|封面|标签|标签|时间|定时/.test(bodyText),
      kuaishou: /发布|作品|标题|简介|描述|标签|合集|声明|定时|预约/.test(bodyText),
      toutiao: /发布|稿件|标题|视频|合集|封面|声明|定时|上传/.test(bodyText),
      "wechat-channels": /发布|视频|标题|话题|上传|正文|封面|定时|合集|声明/.test(bodyText),
      youtube: /上传|视频|标题|描述|播放列表|公开|字幕|缩略图|定时|已排定|Schedule/.test(bodyText),
      x: /发布|tweet|post|上传|作品|视频|定时|标签|评论|回复/.test(bodyText),
    };
    const routeUrl = String(location.href || "");
    const routeReadyByUrl = verification_by_url[platform] ? verification_by_url[platform].test(routeUrl) : /upload|publish|compose|studio|creator/.test(routeUrl);
    const imageSources = [...document.querySelectorAll("img")]
      .filter(visible)
      .map((img) => String(img.currentSrc || img.src || ""))
      .filter(Boolean)
      .slice(0, 80);
    const backgroundSources = [...document.querySelectorAll("*")]
      .filter(visible)
      .map((el) => String(getComputedStyle(el).backgroundImage || ""))
      .filter((src) => src && src !== "none")
      .slice(0, 80);
    const textLikeInputTypes = new Set(["", "text", "search", "url", "tel", "email", "number", "date", "time", "datetime-local"]);
    const labeledControlHint = /标题|title|正文|简介|描述|说明|作品描述|作品简介|内容|合集|播放列表|栏目|分类|分区|系列|专辑|发布时间|定时|预约|日期|时间|原创|声明|封面|缩略图|话题|标签/i;
    const inputFields = [...document.querySelectorAll("input,textarea,[contenteditable=true],div[role=textbox]")]
      .filter(visible)
      .map((el) => ({
        el,
        tag: String(el.tagName || "").toLowerCase(),
        type: String(el.getAttribute("type") || "").toLowerCase(),
        label: clean(
          el.getAttribute("placeholder")
          || el.getAttribute("aria-label")
          || el.getAttribute("name")
          || el.getAttribute("id")
          || el.getAttribute("data-placeholder")
          || el.closest("label,[role=radio],[role=checkbox],[role=switch]")?.innerText
          || "",
        ),
        value: clean(el.value || el.innerText || el.textContent),
        checked: typeof el.checked === "boolean" ? Boolean(el.checked) : null,
        textLike:
          el.tagName === "TEXTAREA"
          || el.getAttribute("contenteditable") === "true"
          || el.isContentEditable
          || (el.tagName === "DIV" && el.getAttribute("role") === "textbox")
          || (el.tagName === "INPUT" && textLikeInputTypes.has(String(el.getAttribute("type") || "").toLowerCase())),
      }))
      .filter((item) => item.value || item.checked === true || labeledControlHint.test(item.label))
      .slice(0, 160);
    const inputs = inputFields.map((item) => item.value);
    const rawTextContentHaystack = clean((document.documentElement || document.body)?.textContent || "");
    const textHaystack = clean([bodyText, ...inputs].join(" "));
    const textFields = inputFields.filter((item) => item.textLike);
    const findInputValue = (patterns, options = {}) => {
      const fragments = (Array.isArray(patterns) ? patterns : [patterns]).map((value) => String(value || "").trim()).filter(Boolean);
      if (!fragments.length) return "";
      const regex = new RegExp(fragments.map((item) => item.replace(/[.*+?^\${}()|[\]\\]/g, "\\$&")).join("|"), "i");
      const candidates = options.textLikeOnly ? textFields : inputFields;
      return (candidates.find((item) => regex.test(item.label) || regex.test(item.value))?.value || "").trim();
    };
    const xComposerTextFields = platform === "x"
      ? [...document.querySelectorAll("div[contenteditable='true'], textarea, input[type=text], input[type=search]")]
          .filter(visible)
          .filter((el) => el.getBoundingClientRect().width * el.getBoundingClientRect().height > 500)
      : [];
    const titleFieldActual = (() => {
      if (platform === "youtube") {
        const youtubeTitleCandidate = textFields.find((item) => /标题（必填）|添加一个可描述你视频的标题|add a title|title/i.test(item.label));
        if (youtubeTitleCandidate) return youtubeTitleCandidate.value;
      }
      const byLabel = findInputValue(["标题", "title", "作品标题", "填写作品标题"], { textLikeOnly: true });
      const needle = expected.title ? expected.title.slice(0, 120) : "";
      const byNeedle = needle ? textFields.map((item) => item.value).find((value) => value.includes(needle) || needle.includes(value)) : "";
      return byLabel || byNeedle || "";
    })();
    const xComposerActualText = platform === "x"
      ? xComposerTextFields
          .map((el) => clean(el.innerText || el.textContent || el.value || ""))
          .filter((value) => value && !/^(Post text|What is happening|有什么新鲜事\?|发布|Post)$/i.test(value))
          .join(" ")
      : "";
    const bodyActual = (() => {
      if (platform === "x") {
        return extractBody(platform, xComposerActualText);
      }
      if (platform === "youtube") {
        const youtubeBodyCandidate = textFields.find((item) => /向观看者介绍你的视频|describe your video|description|说明/i.test(item.label));
        if (youtubeBodyCandidate) {
          return extractBody(platform, youtubeBodyCandidate.value || youtubeBodyCandidate.label);
        }
      }
      const byLabel = findInputValue(["正文", "简介", "描述", "说明", "作品描述", "作品简介", "正文内容", "内容"], { textLikeOnly: true });
      const needle = expected.body ? expected.body.slice(0, 180) : "";
      const byNeedle = needle ? textFields.map((item) => item.value).find((value) => value.includes(needle) || needle.includes(value)) : "";
      return extractBody(
        platform,
        byLabel || byNeedle || (expected.body ? bodyText.slice(0, 800) : bodyText.slice(0, 260)),
      );
    })();
    const douyinCollectionEvidence = platform === "douyin"
      ? extractDouyinCollection(lines, expected.collection, inputFields)
      : { actual: "", matched: false, placeholder_visible: false, source: "" };
    const collectionActual = (() => {
      if (platform === "douyin") return String(douyinCollectionEvidence.actual || "").trim();
      if (platform === "xiaohongshu") {
        return ${deriveXiaohongshuSelectedCollectionActual.toString()}(expected.collection, textHaystack);
      }
      const byLabel = findInputValue(["合集", "playlist", "播放列表", "合集名称", "栏目", "分类", "分区", "系列", "专辑"]);
      if (byLabel) return byLabel;
      const needle = expected.collection ? expected.collection : "";
      if (!needle) return "";
      return inputs.find((value) => value.includes(needle) || needle.includes(value)) || "";
    })();
    const declarationActual = (() => {
      const byLabel = findInputValue(["创作声明", "声明", "原创", "版权", "内容声明", "author declaration"]);
      if (byLabel) return byLabel;
      if (platform === "xiaohongshu") {
        return ${deriveXiaohongshuDeclarationActual.toString()}(expected.declaration, textHaystack);
      }
      return "";
    })();
    let douyinScheduleDateValue = "";
    let douyinScheduleTimeValue = "";
    let douyinCheckedScheduled = false;
    const scheduleActual = (() => {
      const scheduleNeedle = expected.scheduleDisplay || "";
      if (!scheduleNeedle) return "";
      if (platform === "douyin") {
        douyinScheduleDateValue = textFields
          .find((item) => /\d{4}-\d{2}-\d{2}/.test(item.value) && (!item.label || /日期和时间|日期|发布时间|定时/.test(item.label)))
          ?.value || "";
        douyinCheckedScheduled = inputFields.some((item) => item.checked && /定时发布|发布时间/.test(item.label));
        douyinScheduleTimeValue = inputFields
          .find((item) => /\d{2}:\d{2}/.test(item.value) && (!item.label || /日期和时间|时间|发布时间|定时/.test(item.label)))
          ?.value || "";
        if (douyinScheduleDateValue && douyinScheduleTimeValue) return douyinScheduleDateValue + " " + douyinScheduleTimeValue;
        if (douyinCheckedScheduled && douyinScheduleDateValue && scheduleNeedle.startsWith(douyinScheduleDateValue)) return scheduleNeedle;
        if (douyinCheckedScheduled) return scheduleNeedle;
      }
      const scheduleDate = scheduleNeedle.slice(0, 10);
      const scheduleTime = scheduleNeedle.slice(11, 16);
      if (textHaystack.includes(scheduleNeedle)) return scheduleNeedle;
      if (scheduleDate && scheduleTime && textHaystack.includes(scheduleDate) && textHaystack.includes(scheduleTime)) return scheduleNeedle;
      return "";
    })();
    const xiaohongshuCustomCoverPreview = platform === "xiaohongshu" && (
      imageSources.some((src) => /^blob:|^data:image\\//.test(src)) ||
      backgroundSources.some((src) => src.includes("blob:") || src.includes("data:image/")) ||
      /封面效果评估通过/.test(textHaystack)
    );
    const coverActual = (() => {
      const byLabel = findInputValue(["封面", "缩略图", "thumbnail", "封面图片", "cover"]);
      if (byLabel) return byLabel;
      const expectedCoverBase = expected.coverPath ? expected.coverPath.split(/[\\\\/]/).pop() : "";
      if (!expectedCoverBase) return "";
      if (imageSources.some((src) => src.includes(expectedCoverBase))) return expectedCoverBase;
      if (backgroundSources.some((src) => src.includes(expectedCoverBase))) return expectedCoverBase;
      if (platform === "xiaohongshu") {
        return ${deriveXiaohongshuCoverActual.toString()}(
          expected.coverPath,
          textHaystack,
          imageSources,
          backgroundSources,
          xiaohongshuCustomCoverPreview,
        );
      }
      return "";
    })();
    const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],[class*=dialog],[class*=popover]")]
      .filter(visible)
      .some((el) => /设置封面|上传图片|封面比例|预览封面|预览视频/.test(clean(el.innerText || el.textContent)));
    const signals = detectSignals(platform, textHaystack, lines);
    const hasInputFields = inputs.length > 0 || fileInputs.length > 0;
    const routeReady = ${isCompositePublishRouteContext.toString()}(platform, {
      url: routeUrl,
      text: bodyText,
      file_inputs: fileInputs.map((input) => ({ accept: input.accept || "" })),
    }) || routeReadyByUrl || verification_by_text[platform];
    const authRequired = authPatterns.test(bodyText);
    const loadingSurface = /加载中，请稍候|加载中|请稍候|Loading/i.test(bodyText)
      && !hasInputFields
      && (bodyText.length <= 120 || (lines.length > 0 && lines.length <= 12));
    const editorSurfaceMissing = routeReady
      && ${shouldTreatCompositeEditorSurfaceAsNotReady.toString()}(platform, routeUrl, hasInputFields, signals);
    const verification_state = authRequired || !routeReady || editorSurfaceMissing || (!hasInputFields && (signals.upload_prompt_only || loadingSurface))
      ? (authRequired ? "auth_required" : "not_ready")
      : "ready";
    const tagHaystack = platform === "x"
      ? xComposerActualText
      : platform === "youtube"
        ? clean([textHaystack, rawTextContentHaystack].join(" "))
        : textHaystack;
    const tagChecks = expected.tags.map((tag) => ({ tag, present: tagHaystack.includes(tag) || tagHaystack.includes("#" + tag) }));
    const scheduleDate = expected.scheduleDisplay ? expected.scheduleDisplay.slice(0, 10) : "";
    const scheduleTime = expected.scheduleDisplay ? expected.scheduleDisplay.slice(11, 16) : "";
    const youtubeScheduled = platform === "youtube" && /已安排好视频发布时间|已排定时间|已排定|Scheduled|公开范围 已排定时间/.test(textHaystack);
    const youtubeEditorSurface = platform === "youtube"
      && ${isYouTubeEditorReadinessSurface.toString()}(routeUrl, textHaystack);
    const scheduleShort = scheduleDate ? scheduleDate.slice(5) : "";
    const scheduleDateLabel = scheduleShort ? scheduleShort.replace("-", "月") + "日" : "";
    const douyinCollapsedSchedulePresent =
      platform === "douyin"
      && douyinCheckedScheduled
      && (!scheduleDate || !douyinScheduleDateValue || douyinScheduleDateValue === scheduleDate);
    const schedulePresent = !expected.scheduleDisplay || youtubeScheduled || (
      textHaystack.includes(expected.scheduleDisplay) ||
      douyinCollapsedSchedulePresent ||
      (scheduleDate && scheduleTime && textHaystack.includes(scheduleDate) && textHaystack.includes(scheduleTime)) ||
      (scheduleDate && scheduleTime && textHaystack.includes(scheduleDate.replace(/-/g, "年").replace(/年(\\d{2})年/, "年$1月")) && textHaystack.includes(scheduleTime)) ||
      (scheduleShort && scheduleTime && textHaystack.includes(scheduleShort) && textHaystack.includes(scheduleTime)) ||
      (scheduleDateLabel && scheduleTime && textHaystack.includes(scheduleDateLabel) && textHaystack.includes(scheduleTime))
    );
    const hasPublicationBusySignals = /选择合集|发布设置|待发布|发布视频|保存草稿|重新保存|草稿箱/.test(textHaystack);
    const draftResidualWarning = /(编辑失败|发布失败|上传失败|提交失败|草稿提交|发布异常|发布中止|请重试|need retry|Upload failed|failed)/i.test(textHaystack);
    const routeAfterToutiaoBase = String(routeUrl || "").toLowerCase().split("mp.toutiao.com/profile_v4/xigua/")[1] || "";
    const routeLooksLikeCompletedToutiaoPublish =
      String(routeUrl || "").toLowerCase().includes("mp.toutiao.com/profile_v4/xigua/") &&
      /^(publish|history|content|manage|list|video|articles?|post|center|work)\b/i.test(routeAfterToutiaoBase);
    const receiptLike =
      (platform === "toutiao" && Boolean(expected.title) && (
        (textHaystack.includes(expected.title) && (/全部发表成功|发布成功|审核中|已发布|定时发布中|定时发布时间|作品管理|发布管理/.test(textHaystack) || (routeLooksLikeCompletedToutiaoPublish && !hasPublicationBusySignals))) &&
        schedulePresent && !/保存草稿/.test(textHaystack)
      )) ||
      (platform === "xiaohongshu" && String(location.href || "").includes("/publish/success") && /发布成功/.test(textHaystack));
    const receiptFieldBypass = receiptLike && platform !== "youtube";
    const tagVerified = tagChecks.every((item) => item.present);
    const bodyVerified = receiptFieldBypass || verifyBody(platform, expected.body, bodyActual, { tagVerified, textHaystack });
    const coverBasename = expected.coverPath ? expected.coverPath.split(/[\\\\/]/).pop() : "";
    const youtubeAutoThumbnail = platform === "youtube" && imageSources.some((src) => /i\\.ytimg\\.com|mqdefault|hqdefault|vi_webp/.test(src));
    const youtubeCustomThumbnailPreview = platform === "youtube" && imageSources.some((src) => /^data:image\\//.test(src));
    const youtubeThumbnailUploading = platform === "youtube" && /正在上传|上传缩略图|缩略图.{0,12}上传中|Uploading thumbnail|Thumbnail upload/.test(textHaystack);
    const youtubeThumbnailState = platform !== "youtube"
      ? ""
      : youtubeThumbnailUploading
        ? "custom_uploading"
        : youtubeCustomThumbnailPreview
          ? "custom_preview_ready"
          : youtubeAutoThumbnail
            ? "generated_remote_thumbnail"
            : "unknown";
    const douyinCoverState = platform === "douyin"
      ? ${deriveDouyinCoverState.toString()}({
        textHaystack,
        expectedCoverPath: expected.coverPath,
        coverActual,
        imageSources,
        backgroundSources,
        modalOpen,
      })
      : null;
    const douyinCustomCoverReady = Boolean(douyinCoverState?.custom_cover_ready);
    const douyinCustomCoverSaved = Boolean(douyinCoverState?.saved);
    const uploadBusy = signals.upload_busy;
    const uploadFailed = signals.upload_failed;
    if (
      platform === "youtube"
      && (textHaystack.includes("频道内容") || textHaystack.includes("Channel content"))
      && !youtubeEditorSurface
      && !youtubeUploadRoute
      && !youtubeUploadDialogRoute
      && !(textHaystack.includes("上传视频") || textHaystack.includes("Upload videos") || textHaystack.includes("拖放视频文件") || textHaystack.includes("Select files"))
    ) {
      signals.blockers.push({ code: "youtube_upload_dialog_not_open", message: "YouTube 仍停留在频道内容列表，没有进入上传视频流程。", evidence: lines.filter((line) => ["频道内容", "视频", "Shorts", "直播", "播放列表", "发布日期", "Channel content"].some((needle) => line.includes(needle))).slice(0, 12) });
    }
    const coverRequiredWarning = /该视频需要上传一个封面|需要上传.{0,24}封面|请上传.{0,24}封面/.test(textHaystack);
    const platformCoverSuccess =
      platform === "kuaishou" ? /封面应用成功|重新设置封面|封面设置/.test(textHaystack)
      : platform === "xiaohongshu" ? /重新设置封面|上传成功|封面预览|封面效果评估通过/.test(textHaystack) && xiaohongshuCustomCoverPreview && !/封面上传中/.test(textHaystack)
      : platform === "toutiao" ? /上传成功|修改封面|重新上传封面|封面已上传/.test(textHaystack)
      : platform === "douyin" ? douyinCustomCoverSaved
      : imageSources.length > 0;
    const coverPresent = !expected.coverPath
      ? true
      : !coverRequiredWarning && (textHaystack.includes(coverBasename) || (platform !== "youtube" && platformCoverSuccess) || (platform === "youtube" && youtubeCustomThumbnailPreview && !youtubeThumbnailUploading));
    const declarationMissingPrompt = /发布前请添加创作声明|请先添加创作声明|发布前需添加创作声明|根据相关法律法规要求/.test(textHaystack);
    const declarationPresent = verifyDeclaration(
      platform,
      expected.declaration,
      declarationActual,
      textHaystack,
      {
        declarationMissingPrompt,
        hasTitleOrBody: Boolean(expected.body || expected.title),
      },
    );
    const platformExtras = {
      x_route: /x\\.com|twitter\\.com/i.test(routeUrl),
      x_composer_active: /x\\.com\\/compose|twitter\\.com\\/compose/i.test(routeUrl),
      x_composer_controls_count: xComposerTextFields.length,
      x_publish_dialog_signal: /选择合集|完成后无法继续编辑|发布设置|发布成功|已发布|审核中/.test(textHaystack),
      youtube_link: (textHaystack.match(/https:\\/\\/youtu\\.be\\/[A-Za-z0-9_-]+/) || textHaystack.match(/https:\\/\\/www\\.youtube\\.com\\/watch\\?v=[A-Za-z0-9_-]+/) || [])[0] || "",
      youtube_scheduled: youtubeScheduled,
      youtube_thumbnail_uploading: youtubeThumbnailUploading,
      youtube_custom_thumbnail_preview: youtubeCustomThumbnailPreview,
      youtube_remote_auto_thumbnail: youtubeAutoThumbnail,
      youtube_thumbnail_state: youtubeThumbnailState,
      xiaohongshu_custom_cover_preview: xiaohongshuCustomCoverPreview,
      douyin_custom_cover_ready: douyinCustomCoverReady,
      douyin_custom_cover_saved: douyinCustomCoverSaved,
      douyin_cover_state: douyinCoverState,
      douyin_collection_actual: collectionActual,
      douyin_collection_placeholder_visible: douyinCollectionEvidence.placeholder_visible,
      douyin_collection_source: douyinCollectionEvidence.source,
      douyin_checked_schedule: douyinCheckedScheduled,
      douyin_schedule_date_value: douyinScheduleDateValue,
      douyin_schedule_time_value: douyinScheduleTimeValue,
      blockers: signals.blockers,
      route: { url: location.href, title: document.title },
      image_sources: imageSources.slice(0, 12),
      background_sources: backgroundSources.slice(0, 12),
      relevant_lines: lines.filter((line) => /发布|预约|定时|封面|缩略图|播放列表|合集|原创|声明|公开|已排定|链接|正在上传|上传失败|无效的视频|打扰粉丝|不生成动态|标签|话题|分类/.test(line)).slice(0, 120),
    };
    const fields = {
      title: { expected: expected.title, actual: titleFieldActual, verified: receiptFieldBypass || !expected.title || textHaystack.includes(expected.title) },
      body: { expected: expected.body, actual: bodyActual, verified: bodyVerified },
      tags: { expected: expected.tags, actual: tagChecks.filter((item) => item.present).map((item) => item.tag), actual_checks: tagChecks, verified: receiptFieldBypass || tagVerified },
      collection: {
        expected: expected.collection,
        actual: collectionActual,
        verified:
          receiptFieldBypass
          || !expected.collection
          || platform === "x"
          || (platform === "xiaohongshu" ? Boolean(collectionActual) : false)
          || (platform === "kuaishou" && /加入合集|选择要加入到的合集/.test(textHaystack))
          || (platform === "douyin" ? douyinCollectionEvidence.matched : textHaystack.includes(expected.collection)),
      },
      schedule: { expected: expected.scheduleDisplay, actual: scheduleActual, verified: receiptFieldBypass || schedulePresent },
      upload_ready: { actual: receiptFieldBypass || !uploadBusy ? "ready" : "not_ready", verified: receiptFieldBypass || (!uploadBusy && !uploadFailed && !signals.upload_prompt_only && signals.blockers.length === 0) },
      declaration: { expected: expected.declaration, actual: declarationActual, verified: receiptFieldBypass || !expected.declaration || declarationPresent },
      draft_state: { expected: "editor_clean", actual: draftResidualWarning ? "residual_artifacts" : "clean", verified: !draftResidualWarning },
      cover: {
        expected_path: expected.coverPath,
        actual: coverActual,
        uploaded: Boolean(coverActual) || Boolean(douyinCustomCoverReady),
        cover_uploaded: Boolean(coverActual) || Boolean(douyinCustomCoverReady),
        verified: receiptFieldBypass || coverPresent || platform === "x",
        cover_required_warning: coverRequiredWarning,
        youtube_auto_thumbnail: youtubeAutoThumbnail,
        youtube_custom_thumbnail_preview: youtubeCustomThumbnailPreview,
        youtube_thumbnail_uploading: youtubeThumbnailUploading,
        youtube_thumbnail_state: youtubeThumbnailState,
      },
    };
    const failures = Object.entries(fields).filter(([, value]) => value && value.verified === false).map(([key]) => key);
    const xiaohongshuVideoUploadEntry =
      platform === "xiaohongshu"
      && ${isXiaohongshuVideoUploadEntrySurface.toString()}(routeUrl, textHaystack);
    const verification_reason = verification_state === "auth_required"
      ? "auth_required"
      : verification_state === "not_ready"
        ? (loadingSurface
          ? "publish_route_loading"
          : (xiaohongshuVideoUploadEntry
            ? "publish_media_entry"
            : (routeReady ? "publish_route_not_ready" : "publish_route_url_mismatch")))
        : "ok";
    platformExtras.receipt_like = receiptLike;
    return {
      platform,
      fields,
      verified: failures.length === 0 && verification_state === "ready",
      failures: verification_state === "ready" ? failures : [],
      verification_state,
      verification_reason,
      route_ready_state: { route_ready: routeReady, auth_required: authRequired, text_ready: Boolean(verification_by_text[platform]), input_ready: hasInputFields, file_inputs_visible: fileInputs.length, body_text_length: bodyText.length, loading_surface: loadingSurface },
      draft_state_warning: draftResidualWarning,
      platform_extras: platformExtras,
    };
  })()`, 20000);
  return result;
}

async function prepareGenericCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  const bodyWithPlatformTags = ["xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"].includes(platform) && tags.length
    ? `${platform === "kuaishou" && title ? `${title}\n` : ""}${body}\n${tags.map((tag) => `#${tag}`).join(" ")}`
    : body;
  const coverPath = platform === "x" ? "" : expectedCoverPath(content);
  if (!["xiaohongshu", "toutiao", "kuaishou"].includes(platform)) {
    actions.push(await setTextFieldByHints(client, ["标题", "作品标题", "title", "Title"], title, { multiline: false }));
    actions.push(await setTextFieldByHints(client, ["简介", "描述", "说明", "正文", "作品描述", "作品描述", "视频简介", "description", "Description"], bodyWithPlatformTags, { multiline: true }));
  }
  actions.push({ kind: "platform_rich_text", ...(await setPlatformRichText(client, platform, title, bodyWithPlatformTags)) });
  if (coverPath) {
    const entryTexts = platform === "youtube"
      ? ["上传文件", "缩略图", "Thumbnail", "Upload file"]
      : ["设置封面", "封面设置", "上传封面", "更换封面", "选择封面"];
    actions.push({ kind: "cover_entry", ...(await clickByText(client, entryTexts)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "cover_entry_loose", ...(await clickLooseText(client, entryTexts)) });
    await sleep(1400);
    if (platform === "xiaohongshu") {
      actions.push({ kind: "xiaohongshu_cover_ratio", ...(await clickByText(client, ["3:4"])) });
      await sleep(500);
    }
    if (platform === "toutiao") {
      actions.push({ kind: "toutiao_cover_local_upload", ...(await clickByText(client, ["本地上传", "上传图片", "上传封面"])) });
      if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_local_upload_loose", ...(await clickLooseText(client, ["本地上传", "上传图片", "上传封面"])) });
      await sleep(800);
    }
    actions.push({ kind: "cover_upload", ...(await setImageFileInputByAccept(client, coverPath)) });
    await sleep(3500);
    if (platform === "xiaohongshu") {
      actions.push({ kind: "xiaohongshu_cover_confirm", ...(await clickByText(client, ["确定"])) });
      await sleep(1600);
    }
    if (platform === "toutiao") {
      actions.push({ kind: "toutiao_cover_next", ...(await clickByText(client, ["下一步"])) });
      await sleep(1000);
      actions.push({ kind: "toutiao_cover_confirm", ...(await clickByText(client, ["确定", "完成"])) });
      await sleep(1400);
    }
  }
  const skipSeparateTagFill = ["xiaohongshu", "kuaishou"].includes(platform);
  for (const tag of skipSeparateTagFill ? [] : tags.slice(0, 10)) {
    if (platform === "xiaohongshu" || platform === "kuaishou") {
      actions.push(await setTextFieldByHints(client, ["添加话题", "话题", "标签", "按回车"], `#${tag}`, { multiline: true }));
    } else {
      actions.push(await setTextFieldByHints(client, ["标签", "tag", "Tags"], tag, { multiline: false }));
    }
  }
  const collection = expectedCollectionName(content);
  if (collection) {
    actions.push({ kind: "collection_entry", ...(await clickByText(client, ["播放列表", "选择", "加入合集", "选择合集", "合集", "创建合集"])) });
    await sleep(1000);
    actions.push({ kind: "collection_select", ...(await clickByText(client, [collection])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "collection_select_loose", ...(await clickLooseText(client, [collection])) });
    await sleep(800);
  }
  if (platform === "youtube") {
    actions.push({ kind: "youtube_not_for_kids", ...(await clickByText(client, ["不，内容不是面向儿童的", "否，并非面向儿童", "No, it's not made for kids"])) });
  }
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_original_declaration", ...(await clickByText(client, ["原创声明", "声明原创", "原创"])) });
  }
  if (platform === "toutiao" || platform === "kuaishou") {
    actions.push({ kind: `${platform}_original_declaration`, ...(await clickByText(client, ["原创", "声明", "作者声明"])) });
  }
  if (content.scheduled_publish_at) {
    actions.push({ kind: "schedule_entry", ...(await clickByText(client, ["定时发布", "发布时间", "预约", "公开范围", "已排定时间", "安排时间"])) });
    await sleep(900);
    actions.push({ kind: "schedule_set", ...(await setGenericScheduleControls(client, platform, content.scheduled_publish_at)) });
  }
  return actions;
}

export function platformBodyWithTags(platform, content) {
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  const override = typeof content.platform_specific_overrides === "object" && content.platform_specific_overrides !== null
    ? content.platform_specific_overrides
    : {};
  const xShareLink = String(override.x_share_link || override.x_share_url || "").trim();
  const taggedBody = !["douyin", "xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"].includes(platform) || !tags.length
    ? body
    : `${platform === "kuaishou" && title ? `${title}\n` : ""}${body}\n${tags.map((tag) => `#${tag}`).join(" ")}`;
  if (platform === "x" && xShareLink) return `${taggedBody ? `${taggedBody}\n` : ""}${xShareLink}`.trim();
  return taggedBody;
}

export function normalizeRichTextDraftValue(value) {
  return String(value || "")
    .replace(/\r/g, "")
    .replace(/\u200b/g, "")
    .split(/\n+/)
    .map((line) => String(line || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
}

export function richTextDraftValueMatches(actual, expected) {
  const normalize = (value) => String(value || "")
    .replace(/\r/g, "")
    .replace(/\u200b/g, "")
    .split(/\n+/)
    .map((line) => String(line || "").replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n")
    .trim();
  const normalizedExpected = normalize(expected);
  if (!normalizedExpected) return true;
  return normalize(actual) === normalizedExpected;
}

async function uploadCompositeCover(client, platform, coverPath) {
  const actions = [];
  if (!coverPath) return actions;
  const entryTexts = platform === "youtube"
    ? ["上传文件", "缩略图", "Thumbnail", "Upload file"]
    : ["设置封面", "封面设置", "上传封面", "更换封面", "选择封面"];
  actions.push({ kind: `${platform}_cover_entry`, ...(await clickByText(client, entryTexts)) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_cover_entry_loose`, ...(await clickLooseText(client, entryTexts)) });
  await sleep(1400);
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_cover_editor_open", ...(await openXiaohongshuCoverEditor(client)) });
    await sleep(700);
    actions.push({ kind: "xiaohongshu_cover_ratio", ...(await clickByText(client, ["3:4"])) });
    await sleep(500);
    actions.push({ kind: "xiaohongshu_cover_upload_entry", ...(await clickByText(client, ["上传图片", "+ 上传图片", "上传封面"])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "xiaohongshu_cover_upload_entry_loose", ...(await clickLooseText(client, ["上传图片", "+ 上传图片", "上传封面"])) });
    await sleep(900);
  }
  if (platform === "toutiao") {
    actions.push({ kind: "toutiao_cover_local_upload", ...(await clickByText(client, ["本地上传", "上传图片", "上传封面"])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_local_upload_loose", ...(await clickLooseText(client, ["本地上传", "上传图片", "上传封面"])) });
    await sleep(800);
  }
  actions.push({ kind: `${platform}_cover_upload`, ...(await setImageFileInputByAccept(client, coverPath)) });
  await sleep(3500);
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_cover_confirm", ...(await clickXiaohongshuCoverConfirm(client)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "xiaohongshu_cover_confirm_fallback", ...(await clickByText(client, ["确定"])) });
    await sleep(1600);
  }
  if (platform === "toutiao") {
    actions.push({ kind: "toutiao_cover_next", ...(await clickByText(client, ["下一步"])) });
    await sleep(1000);
    actions.push({ kind: "toutiao_cover_confirm", ...(await clickByText(client, ["确定", "完成"])) });
    await sleep(1400);
    actions.push({ kind: "toutiao_cover_completion_confirm", ...(await clickToutiaoCompletionConfirm(client)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_completion_confirm_fallback", ...(await clickVisibleDialogConfirm(client, ["确定", "确认", "完成"])) });
    if (actions.at(-1)?.clicked) await sleep(1800);
  }
  return actions;
}

async function readDouyinCoverSurface(client) {
  return evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const bodyText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const relevantLines = bodyText
      .split(/[\\n\\r]+| {2,}/)
      .map(clean)
      .filter(Boolean)
      .filter((line) => /封面|上传图片|修改封面|更换封面|重新上传|智能推荐封面|默认截取第一帧|预览封面|预览视频/.test(line))
      .slice(0, 80);
    const fileInputs = [...document.querySelectorAll("input[type=file]")]
      .map((el, index) => ({
        index,
        accept: el.getAttribute("accept") || el.accept || "",
        visible: visible(el),
      }))
      .slice(0, 12);
    const imageSources = [...document.querySelectorAll("img")]
      .map((el) => String(el.getAttribute("src") || el.currentSrc || "").trim())
      .filter(Boolean)
      .slice(0, 50);
    const backgroundSources = [...document.querySelectorAll("[style*=background-image]")]
      .map((el) => {
        const style = String(el.getAttribute("style") || "");
        const match = style.match(/background-image\\s*:\\s*url\\(([^)]+)\\)/i);
        return match ? String(match[1] || "").replace(/^['"]|['"]$/g, "").trim() : "";
      })
      .filter(Boolean)
      .slice(0, 50);
    const coverInputs = [...document.querySelectorAll("input:not([type]),input[type=text],textarea,[role=textbox],[contenteditable=true]")]
      .filter(visible)
      .map((el) => {
        const value = clean(el.value || el.innerText || el.textContent || "");
        const placeholder = clean(el.getAttribute("placeholder") || el.getAttribute("aria-label") || el.getAttribute("title") || "");
        const parentText = clean(el.parentElement?.innerText || "");
        return { value, placeholder, parentText };
      })
      .filter((item) => /封面|thumbnail|cover/i.test(item.placeholder) || /封面|thumbnail|cover/i.test(item.parentText))
      .slice(0, 20);
    const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],[class*=dialog],[class*=popover]")]
      .filter(visible)
      .some((el) => /设置封面|上传图片|封面比例|预览封面|预览视频/.test(clean(el.innerText || el.textContent)));
    return {
      lines: relevantLines,
      body_text: bodyText.slice(0, 4000),
      file_inputs: fileInputs,
      image_sources: imageSources,
      background_sources: backgroundSources,
      cover_actual: coverInputs.find((item) => item.value)?.value || "",
      modal_open: modalOpen,
    };
  })()`, 12000);
}

async function clickDouyinCoverConfirm(client) {
  const snapshot = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll("[role=dialog],[aria-modal=true],[class*=modal],[class*=dialog],[class*=popover],[class*=drawer]")]
      .filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const text = clean(el.innerText || el.textContent);
        const buttons = [...el.querySelectorAll("button,[role=button],input[type=button],input[type=submit]")]
          .filter(visible)
          .map((btn) => {
            const btnRect = btn.getBoundingClientRect();
            return {
              label: clean(btn.innerText || btn.value || btn.getAttribute("aria-label") || btn.getAttribute("title")),
              className: clean(typeof btn.className === "string" ? btn.className : ""),
              x: btnRect.left + btnRect.width / 2,
              y: btnRect.top + btnRect.height / 2,
              width: btnRect.width,
              height: btnRect.height,
            };
          })
          .filter((item) => item.label && item.label.length <= 80);
        return {
          text,
          x: rect.left,
          y: rect.top,
          width: rect.width,
          height: rect.height,
          buttons,
        };
      })
      .filter((item) => item.buttons.length > 0 && /设置封面|取消保存|重新上传|上传图片|封面/.test(item.text))
      .sort((left, right) => (left.width * left.height) - (right.width * right.height));
    return {
      dialogs,
      visible_buttons: dialogs.flatMap((dialog) => dialog.buttons.map((button) => ({
        ...button,
        dialog_text: dialog.text.slice(0, 240),
      }))),
    };
  })()`, 12000);
  const chosen = selectDouyinCoverConfirmCandidate(snapshot?.visible_buttons || []);
  if (!chosen) {
    return {
      clicked: false,
      dialogs: (snapshot?.dialogs || []).map((item) => String(item?.text || "").slice(0, 220)),
      candidates: (snapshot?.visible_buttons || []).slice(0, 20),
    };
  }
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: chosen.x, y: chosen.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: chosen.x, y: chosen.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: chosen.x, y: chosen.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1800);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const modalOpen = [...document.querySelectorAll("[role=dialog],[aria-modal=true],[class*=modal],[class*=dialog],[class*=popover],[class*=drawer]")]
      .filter(visible)
      .some((el) => /设置封面|取消保存|重新上传|上传图片|封面/.test(clean(el.innerText || el.textContent)));
    return {
      modal_open: modalOpen,
      body_text: clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "").slice(0, 1200),
    };
  })()`, 12000);
  return {
    clicked: true,
    label: chosen.label,
    className: chosen.className,
    dialog_text: chosen.dialog_text,
    input_click: { x: chosen.x, y: chosen.y },
    ...after,
  };
}

async function setDouyinCompositeCover(client, coverPath) {
  const actions = [];
  if (!coverPath) return actions;
  actions.push({ kind: "douyin_cover_entry", ...(await clickByText(client, ["设置封面", "修改封面", "更换封面", "上传封面", "选择封面"])) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: "douyin_cover_entry_loose", ...(await clickLooseText(client, ["设置封面", "修改封面", "更换封面", "上传封面", "选择封面"])) });
  await sleep(1200);
  const before = await readDouyinCoverSurface(client).catch(() => ({}));
  actions.push({ kind: "douyin_cover_surface_before", ...before });
  const upload = await setImageFileInputByAccept(client, coverPath);
  actions.push({ kind: "douyin_cover_upload", ...upload });
  await sleep(3500);
  const confirm = await clickDouyinCoverConfirm(client);
  actions.push({ kind: "douyin_cover_confirm", ...confirm });
  const after = await readDouyinCoverSurface(client).catch(() => ({}));
  const coverState = deriveDouyinCoverState({
    textHaystack: [after.body_text, ...(after.lines || [])].filter(Boolean).join(" "),
    expectedCoverPath: coverPath,
    coverActual: after.cover_actual,
    imageSources: after.image_sources,
    backgroundSources: after.background_sources,
    modalOpen: Boolean(after.modal_open),
  });
  actions.push({ kind: "douyin_cover_surface_after", ready: coverState.custom_cover_ready, saved: coverState.saved, expected_path: coverPath, cover_state: coverState, ...after });
  return actions;
}

async function selectCompositeCollection(client, platform, content) {
  const collection = expectedCollectionName(content);
  if (!collection) return [];
  const actions = [];
  const entryTexts = platform === "youtube"
    ? ["播放列表", "Playlist", "选择"]
    : ["加入合集", "选择合集", "合集", "播放列表", "选择", "创建合集"];
  actions.push({ kind: `${platform}_collection_entry`, ...(await clickByText(client, entryTexts)) });
  await sleep(1000);
  actions.push({ kind: `${platform}_collection_select`, ...(await clickByText(client, [collection])) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_collection_select_loose`, ...(await clickLooseText(client, [collection])) });
  await sleep(800);
  return actions;
}

async function readDouyinCollectionSurface(client) {
  return evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const bodyText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const lines = bodyText
      .split(/[\\n\\r]+| {2,}/)
      .map(clean)
      .filter(Boolean)
      .filter((line) => /合集|选择合集|加入合集|添加合集|请选择合集/.test(line))
      .slice(0, 80);
    const labelFor = (el) => {
      const id = el.getAttribute("id");
      const labelledBy = el.getAttribute("aria-labelledby");
      const labels = [];
      if (id) labels.push(...queryAll(\`label[for="\${CSS.escape(id)}"]\`).map((label) => label.innerText));
      if (labelledBy) {
        for (const part of labelledBy.split(/\\s+/)) {
          const node = document.getElementById(part);
          if (node) labels.push(node.innerText || node.textContent || "");
        }
      }
      let parent = el.parentElement;
      for (let index = 0; index < 3 && parent; index += 1, parent = parent.parentElement) {
        labels.push(parent.innerText || "");
      }
      return clean([el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.getAttribute("title"), ...labels].filter(Boolean).join(" "));
    };
    const inputFields = queryAll("input,select,textarea,[role=combobox],[role=textbox],[contenteditable=true]")
      .filter(visible)
      .map((el) => ({
        label: labelFor(el),
        value: clean(el.value || el.innerText || el.textContent || ""),
      }))
      .filter((item) => item.label || item.value)
      .slice(0, 40);
    return { lines, input_fields: inputFields };
  })()`, 12000);
}

async function setDouyinCompositeCollection(client, content) {
  const expectedCollection = expectedCollectionName(content);
  if (!expectedCollection) return [];
  const actions = [];
  actions.push({ kind: "douyin_collection_entry", ...(await clickByText(client, ["请选择合集", "添加合集", "加入合集", "选择合集", "合集"])) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: "douyin_collection_entry_loose", ...(await clickLooseText(client, ["请选择合集", "添加合集", "加入合集", "选择合集", "合集"])) });
  await sleep(900);
  const selection = await evaluateWithClient(client, `(async () => {
    const expected = ${JSON.stringify(expectedCollection)};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && el.getAttribute("aria-hidden") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const disallowedContext = /自主声明|请选择自主声明|定时发布|发布时间|作品描述|官方活动|设置封面|添加话题|@好友/;
    const placeholderPattern = /^(?:添加合集|请选择合集|加入合集|选择合集|合集)$/;
    const anchors = [...document.querySelectorAll("input,select,button,[role=button],[role=combobox],span,div,label")]
      .filter(visible)
      .map((el) => {
        const text = clean(el.innerText || el.textContent || el.value || el.getAttribute("aria-label") || el.getAttribute("title"));
        const context = clean(el.parentElement?.innerText || "");
        const inDialog = Boolean(el.closest("[role=dialog],[class*=modal],[class*=dialog],[class*=popover],[class*=dropdown]"));
        return { el, text, context, inDialog };
      })
      .filter((item) => /合集|选择合集|加入合集|添加合集/.test(item.text) || (/合集/.test(item.context) && !disallowedContext.test(item.context)))
      .sort((left, right) => Number(Boolean(right.inDialog)) - Number(Boolean(left.inDialog)));
    const field = anchors.find((item) => !/自主声明/.test(item.text) && !disallowedContext.test(item.context)) || anchors[0];
    const opened = click(field?.el);
    if (opened) await sleep(600);
    const options = [...document.querySelectorAll("[role=option],li,button,[role=button],div,span,label")]
      .filter(visible)
      .map((el) => {
        const text = clean(el.innerText || el.textContent);
        const inLayer = Boolean(el.closest("[role=dialog],[class*=modal],[class*=dialog],[class*=popover],[class*=dropdown],[class*=select],[class*=option],[class*=menu]"));
        const area = el.getBoundingClientRect().width * el.getBoundingClientRect().height;
        return { el, text, inLayer, area };
      })
      .filter((item) => item.text && item.text.includes(expected) && !placeholderPattern.test(item.text) && item.area > 0 && item.area < 120000)
      .sort((left, right) => Number(Boolean(right.inLayer)) - Number(Boolean(left.inLayer)) || left.area - right.area);
    const option = options[0];
    const selected = click(option?.el);
    if (selected) await sleep(600);
    const confirmCandidates = [...document.querySelectorAll("button,[role=button],span,div")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent) }))
      .filter((item) => item.text === "确定" || item.text === "完成");
    const confirmed = selected ? click(confirmCandidates[0]?.el) : false;
    if (confirmed) await sleep(700);
    const bodyText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const lines = bodyText
      .split(/[\\n\\r]+| {2,}/)
      .map(clean)
      .filter(Boolean)
      .filter((line) => /合集|选择合集|加入合集|添加合集|请选择合集/.test(line))
      .slice(0, 80);
    const inputFields = [...document.querySelectorAll("input,select,textarea,[role=combobox],[role=textbox],[contenteditable=true]")]
      .filter(visible)
      .map((el) => ({
        label: clean([el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.getAttribute("title"), el.parentElement?.innerText || ""].filter(Boolean).join(" ")),
        value: clean(el.value || el.innerText || el.textContent || ""),
      }))
      .filter((item) => item.label || item.value)
      .slice(0, 40);
    return {
      opened,
      selected,
      confirmed,
      selected_label: option?.text || "",
      lines,
      input_fields: inputFields,
    };
  })()`, 20000);
  let evidence = extractDouyinSelectedCollectionEvidence(selection.lines, expectedCollection, selection.input_fields);
  actions.push({ kind: "douyin_collection_state", expected: expectedCollection, evidence, ...selection });
  if (!evidence.matched) {
    actions.push({ kind: "douyin_collection_select_fallback", ...(await clickByText(client, [expectedCollection])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "douyin_collection_select_fallback_loose", ...(await clickLooseText(client, [expectedCollection])) });
    await sleep(700);
    const after = await readDouyinCollectionSurface(client).catch(() => ({ lines: [], input_fields: [] }));
    evidence = extractDouyinSelectedCollectionEvidence(after.lines, expectedCollection, after.input_fields);
    actions.push({ kind: "douyin_collection_state_after_fallback", expected: expectedCollection, evidence, ...after });
  }
  return actions;
}

async function setCompositeSchedule(client, platform, content) {
  if (!content.scheduled_publish_at) return [];
  const actions = [];
  if (!["xiaohongshu"].includes(platform)) {
    actions.push({ kind: `${platform}_schedule_entry`, ...(await clickByText(client, ["定时发布", "发布时间", "预约", "公开范围", "已排定时间", "安排时间", "Schedule"])) });
    await sleep(900);
  }
  try {
    actions.push({ kind: `${platform}_schedule_set`, ...(await setGenericScheduleControls(client, platform, content.scheduled_publish_at)) });
  } catch (error) {
    actions.push({ kind: `${platform}_schedule_set`, set: false, reason: "schedule_control_error", message: error.message });
  }
  return actions;
}

async function prepareYoutubeCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const coverPath = expectedCoverPath(content);
  const mediaPath = expectedMediaPath(content);
  actions.push({ kind: "youtube_upload_editor", ...(await ensureYoutubeUploadEditor(client, title || body || path.win32.basename(String(mediaPath || "")).replace(/\.[^.]+$/, ""))) });
  await sleep(900);
  const resumeDraft = await resolveCurrentPageDraftResumePrompt(client, platform).catch((error) => ({
    attempted: false,
    resumed: false,
    prompt_present: false,
    reason: "resume_prompt_error",
    error: String(error?.message || error || ""),
  }));
  actions.push({ kind: "youtube_draft_resume_prompt", ...resumeDraft });
  if (resumeDraft?.attempted || resumeDraft?.route_bootstrap_changed || resumeDraft?.resumed) {
    await sleep(1800);
  }
  let mediaUpload = { uploaded: false, skipped: false, reason: "no_video_file_input" };
  let postResumeSnapshot = await pageSnapshot(client).catch(() => null);
  let postResumeMediaState = canReuseCurrentPageMediaForPrepublish(platform, postResumeSnapshot, mediaPath, { requiresLocalMedia: true });
  if (postResumeMediaState.reusable) {
    mediaUpload = { uploaded: true, skipped: true, reason: "media_already_present", media_reuse_reason: postResumeMediaState.reason };
  } else {
    const uploadMenuTexts = ["创建", "CREATE", "上传视频", "Upload videos"];
    actions.push({ kind: "youtube_upload_menu_open", ...(await clickByText(client, uploadMenuTexts)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "youtube_upload_menu_open_loose", ...(await clickLooseText(client, uploadMenuTexts)) });
    await sleep(900);
    const uploadEntryTexts = ["上传视频", "Upload videos", "发布视频", "发表视频", "立即投稿", "Create"];
    actions.push({ kind: "youtube_upload_entry", ...(await clickByText(client, uploadEntryTexts)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "youtube_upload_entry_loose", ...(await clickLooseText(client, uploadEntryTexts)) });
    if (!actions.some((action) => /^youtube_upload_entry/.test(String(action?.kind || "")) && action?.clicked)) {
      actions.push({ kind: "youtube_upload_entry_hidden", ...(await activateYoutubeHiddenUploadEntry(client)) });
    }
    await sleep(1800);
    mediaUpload = await uploadYoutubeVideoForComposite(client, mediaPath);
  }
  actions.push({ kind: "youtube_media_upload", ...mediaUpload });
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, compositeUploadTimeoutMs(platform));
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) {
    const blocker = buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness.readiness);
    actions.push(blocker);
    return actions;
  }
  actions.push({ kind: "youtube_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, coverPath)));
  if (compositePlatformSkipsExplicitTagEntry(platform)) {
    actions.push({ kind: "youtube_tag_entry_skipped", skipped: true, reason: "platform_soft_tag_policy" });
  } else {
    actions.push({ kind: "youtube_metadata_expand", ...(await expandYoutubeMetadataSections(client)) });
    actions.push({ kind: "youtube_tags", ...(await setYouTubeTags(client, expectedTags(content, 15))) });
  }
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "youtube_not_for_kids", ...(await clickByText(client, ["不，内容不是面向儿童的", "否，并非面向儿童", "No, it's not made for kids"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function setDouyinOriginalDeclaration(client, content) {
  const actions = [];
  actions.push({ kind: "douyin_original_declaration_entry", ...(await clickByText(client, ["自主声明", "原创", "声明"])) });
  const targetOption = expectedCompositeDeclaration(content, "douyin");
  const selection = await evaluateWithClient(client, `(async () => {
    const expected = ${JSON.stringify(targetOption)};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && el.getAttribute("aria-hidden") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const looksSelected = (el) => {
      if (!el) return false;
      const selfChecked = String(el.getAttribute("aria-checked") || "").toLowerCase() === "true";
      const selfPressed = String(el.getAttribute("aria-pressed") || "").toLowerCase() === "true";
      const selfSelected = String(el.getAttribute("aria-selected") || "").toLowerCase() === "true";
      const selfClass = clean(String(el.className || ""));
      const hasSelectedClass = /checked|selected|active/.test(selfClass);
      const descendantChecked = [...el.querySelectorAll("input,[role=radio],[role=checkbox],[aria-checked],[aria-selected]")]
        .some((node) =>
          (typeof node.checked === "boolean" && Boolean(node.checked))
          || String(node.getAttribute("aria-checked") || "").toLowerCase() === "true"
          || String(node.getAttribute("aria-selected") || "").toLowerCase() === "true"
        );
      return selfChecked || selfPressed || selfSelected || hasSelectedClass || descendantChecked;
    };
    const isDisabled = (el) => {
      if (!el) return true;
      return Boolean(el.disabled)
        || String(el.getAttribute("aria-disabled") || "").toLowerCase() === "true"
        || /disabled/.test(clean(String(el.className || "")));
    };
    const allVisibleText = () => clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const splitLines = (text) => text.split(/[\\n\\r]+| {2,}/).map(clean).filter(Boolean);
    const findDeclarationFormActual = (text) => {
      const lines = splitLines(text);
      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index];
        if (!/自主声明|创作声明|声明类型/.test(line)) continue;
        const windowLines = lines.slice(index, index + 3);
        const matchedExpected = windowLines.find((item) => item === expected || item.includes(expected) || expected.includes(item));
        if (matchedExpected) return matchedExpected;
        if (windowLines.some((item) => /请选择自主声明|请选择声明类型/.test(item))) return "";
      }
      const anywhereExpected = lines.find((item) => item === expected || item.includes(expected) || expected.includes(item));
      if (anywhereExpected) return anywhereExpected;
      return "";
    };
    const modalPattern = /请选择声明类型|无需添加自主声明|内容由AI生成|内容为个人观点或见解|内容为转载信息|内容含营销推广信息|虚构演绎，仅供娱乐/;
    const bodyText = allVisibleText();
    if (!modalPattern.test(bodyText)) {
      return { opened: false, selected: false, confirmed: false, target_option: expected, visible_text: [] };
    }
    const modalRoot = [...document.querySelectorAll("[role=dialog],[aria-modal=true],[class*=modal i],[class*=dialog i]")]
      .filter(visible)
      .find((el) => modalPattern.test(clean(el.innerText || el.textContent || ""))) || document.body;
    const collect = (root) => [...root.querySelectorAll("label,button,[role=button],[role=radio],span,div")]
      .filter(visible)
      .map((el) => ({
        el,
        text: clean(el.innerText || el.textContent),
        area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
      }))
      .filter((item) => item.text && item.text.length <= 120);
    let candidates = collect(modalRoot);
    const option = candidates
      .map((item) => {
        const target = item.el.closest("label,[role=radio],button,[role=button],li,div") || item.el;
        return {
          ...item,
          target,
          selected_before: looksSelected(target),
        };
      })
      .filter((item) => item.text === expected || item.text.includes(expected))
      .sort((left, right) => left.area - right.area)[0];
    const selected = click(option?.target);
    if (selected) await sleep(500);
    const selectedState = looksSelected(option?.target);
    candidates = collect(modalRoot);
    const confirm = candidates
      .filter((item) => item.text === "确定")
      .filter((item) => !isDisabled(item.el))
      .sort((left, right) => left.area - right.area)[0];
    const confirmEnabled = Boolean(confirm?.el) && !isDisabled(confirm?.el);
    const confirmed = click(confirm?.el);
    if (confirmed) await sleep(800);
    const afterText = allVisibleText();
    const declarationActual = findDeclarationFormActual(afterText);
    const placeholderVisible = /请选择自主声明|请选择声明类型/.test(afterText);
    const saved = Boolean(
      !modalPattern.test(afterText)
      && declarationActual
      && (declarationActual === expected || declarationActual.includes(expected) || expected.includes(declarationActual))
      && !placeholderVisible
    );
    return {
      opened: true,
      target_option: expected,
      selected,
      selected_label: option?.text || "",
      selected_state: selectedState,
      confirm_enabled: confirmEnabled,
      confirmed,
      closed: !modalPattern.test(afterText),
      declaration_actual: declarationActual,
      placeholder_visible: placeholderVisible,
      saved,
      visible_text: afterText.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /声明|AI|营销|转载|娱乐|取消|确定/.test(line)).slice(0, 40),
    };
  })()`, 20000);
  actions.push({ kind: "douyin_original_declaration", ...selection });
  return actions;
}

async function repairDouyinCompositeDraft(client, platform, content, repairableFields = []) {
  const plan = buildCompositeRepairExecutionPlan(platform, repairableFields);
  const actions = [];
  if (plan.rich_text) {
    const title = String(content.title || "").trim();
    const body = platformBodyWithTags(platform, content);
    actions.push({ kind: "douyin_rich_text_repair", ...(await setPlatformRichText(client, platform, title, body)) });
  }
  if (plan.cover) {
    actions.push(...(await setDouyinCompositeCover(client, expectedCoverPath(content))));
  }
  if (plan.collection) {
    actions.push(...(await setDouyinCompositeCollection(client, content)));
  }
  if (plan.declaration) {
    actions.push(...(await setDouyinOriginalDeclaration(client, content)));
  }
  if (plan.schedule) {
    actions.push(...(await setCompositeSchedule(client, platform, content)));
  }
  return actions;
}

async function prepareDouyinCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, compositeUploadTimeoutMs(platform));
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) {
    const blocker = buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness.readiness);
    actions.push(blocker);
    return actions;
  }
  actions.push({ kind: "douyin_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await setDouyinCompositeCover(client, expectedCoverPath(content))));
  actions.push(...(await setDouyinCompositeCollection(client, content)));
  actions.push(...(await setDouyinOriginalDeclaration(client, content)));
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareXiaohongshuCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, compositeUploadTimeoutMs(platform));
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) {
    const blocker = buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness.readiness);
    actions.push(blocker);
    return actions;
  }
  actions.push({ kind: "xiaohongshu_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "xiaohongshu_original_declaration", ...(await clickByText(client, ["原创声明", "声明原创", "原创"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareKuaishouCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, compositeUploadTimeoutMs(platform));
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) {
    const blocker = buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness.readiness);
    actions.push(blocker);
    return actions;
  }
  actions.push({ kind: "kuaishou_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "kuaishou_original_declaration", ...(await clickByText(client, ["作者声明", "原创", "声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareToutiaoCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, compositeUploadTimeoutMs(platform));
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) {
    const blocker = buildCompositeUploadReadinessBlockerAction(platform, uploadReadiness.readiness);
    actions.push(blocker);
    return actions;
  }
  actions.push({ kind: "toutiao_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  for (const tag of expectedTags(content, 10)) {
    actions.push({ kind: "toutiao_tag", ...(await setTextFieldByHints(client, ["话题", "标签", "tag", "Tags"], tag, { multiline: false })) });
  }
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "toutiao_original_declaration", ...(await clickByText(client, ["原创", "声明", "作者声明", "作品声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareWechatChannelsCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  actions.push({ kind: "wechat_channels_rich_text", ...(await setPlatformRichText(client, platform, title, platformBodyWithTags(platform, content))) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "wechat_channels_original_declaration", ...(await clickByText(client, ["声明原创", "原创", "声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareXCompositeDraft(client, platform, content) {
  const actions = [];
  actions.push({ kind: "x_ensure_compose", ...(await ensureXCompose(client)) });
  await sleep(800);
  actions.push({ kind: "x_rich_text", ...(await setPlatformRichText(client, platform, "", platformBodyWithTags(platform, content))) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

const PLATFORM_COMPOSITE_FRAMEWORKS = {
  douyin: { id: "douyin_creator_composite_v1", prepare: prepareDouyinCompositeDraft, repair: repairDouyinCompositeDraft },
  youtube: { id: "youtube_studio_composite_v1", prepare: prepareYoutubeCompositeDraft },
  xiaohongshu: { id: "xiaohongshu_creator_composite_v1", prepare: prepareXiaohongshuCompositeDraft },
  kuaishou: { id: "kuaishou_creator_composite_v1", prepare: prepareKuaishouCompositeDraft },
  toutiao: { id: "toutiao_xigua_composite_v1", prepare: prepareToutiaoCompositeDraft },
  "wechat-channels": { id: "wechat_channels_composite_v1", prepare: prepareWechatChannelsCompositeDraft },
  x: { id: "x_composer_composite_v1", prepare: prepareXCompositeDraft },
};

const DEDICATED_PLATFORM_FRAMEWORK_IDS = Object.freeze({
  bilibili: "bilibili_creator_native_composite_v1",
  ...Object.fromEntries(Object.entries(PLATFORM_COMPOSITE_FRAMEWORKS).map(([platform, framework]) => [platform, framework.id])),
});

function dedicatedCompositeFrameworkId(platform) {
  return DEDICATED_PLATFORM_FRAMEWORK_IDS[platform] || "";
}

function buildPublicationAuditChecklist(fields = {}) {
  const checklist = {};
  for (const key of ["cover", "title", "body", "tags", "collection", "schedule", "upload_ready", "declaration", "receipt", "draft_state"]) {
    if (!fields[key]) continue;
    checklist[key] = {
      verified: fields[key].verified !== false,
      expected: fields[key].expected ?? fields[key].expected_path ?? "",
    };
    if (fields[key].required !== undefined) checklist[key].required = Boolean(fields[key].required);
    if (fields[key].actual !== undefined) checklist[key].actual = fields[key].actual;
    if (Array.isArray(fields[key].actual_checks)) checklist[key].actual_checks = fields[key].actual_checks;
  }
  if (fields.content_plan_match) {
    checklist.content_plan_match = {
      verified: fields.content_plan_match.verified !== false,
      expected: fields.content_plan_match.expected || {},
      actual: fields.content_plan_match.actual || {},
      missing: fields.content_plan_match.missing || [],
      optional_missing: fields.content_plan_match.optional_missing || [],
      field_matches: fields.content_plan_match.field_matches || {},
    };
  }
  return checklist;
}

export function collectRepairEvidenceFlags(actions = []) {
  const entries = Array.isArray(actions) ? actions : [];
  const evidence = {
    cover_repair_attempted: false,
    cover_repaired: false,
    cover_repair_saved: false,
    collection_repair_attempted: false,
    collection_repaired: false,
    collection_repair_matched: false,
    declaration_repair_attempted: false,
    declaration_repaired: false,
    declaration_repair_selected: false,
    declaration_repair_saved: false,
    schedule_repair_attempted: false,
    schedule_repaired: false,
    rich_text_repair_attempted: false,
    rich_text_repaired: false,
  };
  for (const action of entries) {
    if (!action || typeof action !== "object") continue;
    const kind = String(action.kind || "");
    if (kind === "douyin_cover_surface_after") {
      evidence.cover_repair_attempted = true;
      evidence.cover_repair_saved = Boolean(action.saved);
      evidence.cover_repaired = Boolean(action.saved);
    } else if (kind === "douyin_collection_state" || kind === "douyin_collection_state_after_fallback") {
      evidence.collection_repair_attempted = true;
      evidence.collection_repair_matched = Boolean(action.evidence?.matched);
      evidence.collection_repaired = Boolean(action.evidence?.matched);
    } else if (kind === "douyin_original_declaration") {
      evidence.declaration_repair_attempted = true;
      evidence.declaration_repair_selected = Boolean(action.selected);
      evidence.declaration_repair_saved = Boolean(action.saved);
      evidence.declaration_repaired = Boolean(action.saved ?? action.selected_state ?? action.selected);
    } else if (kind === "douyin_rich_text_repair") {
      evidence.rich_text_repair_attempted = true;
      evidence.rich_text_repaired = Boolean(action.filled) && action.verified_body !== false && action.verified_title !== false;
    } else if (/_schedule_set$/.test(kind)) {
      evidence.schedule_repair_attempted = true;
      evidence.schedule_repaired = Boolean(action.set);
    }
  }
  return evidence;
}

function _coerceText(value) {
  return String(value || "").trim();
}

function _coerceList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => _coerceText(item)).filter(Boolean);
}

function _coerceSnapshotFieldValue(field, fallback = "") {
  if (!field || typeof field !== "object") return fallback;
  if (field.actual !== undefined && field.actual !== null) {
    return field.actual;
  }
  if (field.value !== undefined && field.value !== null) {
    return field.value;
  }
  if (field.expected !== undefined && field.expected !== null) {
    return field.expected;
  }
  return fallback;
}

function _coerceSnapshotFieldExpected(field, fallback = "") {
  if (!field || typeof field !== "object") return fallback;
  if (field.expected !== undefined && field.expected !== null) {
    return field.expected;
  }
  if (field.value !== undefined && field.value !== null) {
    return field.value;
  }
  return fallback;
}

function _coerceSnapshotTags(field, fallback = []) {
  const direct = field?.actual;
  if (Array.isArray(direct)) {
    return Array.from(new Set(_coerceList(direct)));
  }
  if (Array.isArray(field?.actual_checks)) {
    const tagValues = field.actual_checks
      .filter((item) => item && typeof item === "object" && item.present !== false)
      .map((item) => _coerceText(item.tag || item.value || ""));
    if (tagValues.length) return Array.from(new Set(tagValues.filter(Boolean)));
  }
  return Array.from(new Set(_coerceList(fallback)));
}

function buildPublicationFieldSnapshotFromAudit(platform, content, publicationAudit = {}, route = {}, options = {}) {
  const checklist = publicationAudit?.checklist && typeof publicationAudit.checklist === "object"
    ? publicationAudit.checklist
    : {};
  const repairEvidence = collectRepairEvidenceFlags(options?.repair_actions || []);
  const mediaItems = Array.isArray(content?.media_items) ? content.media_items : [];
  const mediaPaths = [];
  for (const item of mediaItems) {
    if (!item || typeof item !== "object") continue;
    const localPath = _coerceText(item.local_path || item.localPath || item.path || "");
    if (localPath) mediaPaths.push(localPath);
  }
  const declaredMediaUrls = _coerceList(content?.media_urls);
  const declaredMediaCount = (
    mediaPaths.length
    || declaredMediaUrls.length
    || ( _coerceText(content?.media_path || content?.media_url || content?.video_file || "").trim() ? 1 : 0)
  );
  const rawTagsExpected = _coerceList(
    _coerceSnapshotFieldExpected(checklist?.tags, _coerceList(content?.hashtags).concat(_coerceList(content?.structured_tags))),
  );
  const tagsActual = _coerceSnapshotTags(checklist?.tags, rawTagsExpected);
  const collectionExpected = _coerceText(_coerceSnapshotFieldExpected(checklist?.collection, expectedCollectionName(content)));
  return {
    platform,
    adapter: _coerceText(content?.adapter || content?.publication_adapter || content?.target_adapter || "browser_agent"),
    title: _coerceText(_coerceSnapshotFieldValue(checklist?.title, content?.title || "")),
    body: _coerceText(_coerceSnapshotFieldValue(checklist?.body, content?.body || "")),
    declaration: _coerceText(_coerceSnapshotFieldValue(checklist?.declaration, content?.declaration || "")),
    hashtags: tagsActual.length ? tagsActual : rawTagsExpected,
    display_hashtags: (tagsActual.length ? tagsActual : rawTagsExpected)
      .map((item) => (_coerceText(item).startsWith("#") ? _coerceText(item) : `#${_coerceText(item)}`)),
    structured_tags: tagsActual.length ? tagsActual : rawTagsExpected,
    native_topics: _coerceList(content?.native_topics),
    category: _coerceText(content?.category || content?.category_name || ""),
    collection: _coerceText(_coerceSnapshotFieldValue(checklist?.collection, collectionExpected)),
    cover_path: _coerceText(_coerceSnapshotFieldValue(checklist?.cover, expectedCoverPath(content))),
    copy_material: typeof content?.copy_material === "object" && content?.copy_material !== null ? content.copy_material : {},
    visibility_or_publish_mode: _coerceText(content?.visibility_or_publish_mode || content?.visibility_mode || ""),
    scheduled_publish_at: _coerceText(_coerceSnapshotFieldValue(checklist?.schedule, content?.scheduled_publish_at || "")),
    ui_control_semantics: {
      schedule_publish: Boolean(_coerceSnapshotFieldValue(checklist?.schedule, content?.scheduled_publish_at)),
      collection_select: Boolean(_coerceSnapshotFieldValue(checklist?.collection, collectionExpected)),
    },
    platform_specific_overrides: typeof content?.platform_specific_overrides === "object" && content?.platform_specific_overrides !== null
      ? content.platform_specific_overrides
      : {},
    repair_evidence: repairEvidence,
    media_urls: declaredMediaUrls,
    media_items_count: Number(declaredMediaCount),
    upload_ready: _coerceText(_coerceSnapshotFieldValue(checklist?.upload_ready, content?.upload_ready || "")),
    draft_state: _coerceText(_coerceSnapshotFieldValue(checklist?.draft_state, "")),
    route: {
      url: _coerceText(route?.url || publicationAudit?.platform_extras?.route?.url || ""),
      title: _coerceText(route?.title || publicationAudit?.platform_extras?.route?.title || ""),
      path: _coerceText(route?.path || publicationAudit?.platform_extras?.route?.path || ""),
    },
  };
}

function _normalizeRequiredReuploadField(fieldName) {
  if (typeof fieldName !== "string") return "";
  return fieldName.startsWith("tag:") ? "tags" : String(fieldName).trim().replace(/[^a-z0-9_]/gi, "");
}

function _deriveRequiredReuploadFromCompositeAudit(platform, content, fields = {}, routeExtras = {}) {
  const requiredReupload = new Set();
  const softVerificationFields = compositePlatformSoftVerificationFields(platform);
  const contentPlanMatch = fields.content_plan_match || {};
  const receipt = fields.receipt || {};

  const add = (value) => {
    const normalized = _normalizeRequiredReuploadField(value);
    if (normalized && softVerificationFields.has(normalized)) return;
    if (normalized) requiredReupload.add(normalized);
  };

  for (const field of ["draft_state", "upload_ready", "cover", "title", "body", "tags", "collection", "schedule", "declaration"]) {
    const entry = fields[field];
    if (entry && entry.required === false) {
      continue;
    }
    if (entry && entry.verified === false) {
      add(field);
    }
  }

  if (receipt && receipt.required !== false && receipt.verified === false) {
    add("receipt");
  }

  if (contentPlanMatch && contentPlanMatch.verified === false) {
    const expected = Array.isArray(contentPlanMatch.missing) ? contentPlanMatch.missing : [];
    for (const item of expected) {
      if (item === "tags") {
        add("tags");
        continue;
      }
      if (typeof item === "string" && item.startsWith("tags:")) {
        add("tags");
      } else {
        add(item);
      }
    }
  }

  if (routeExtras?.auth_required) {
    add("auth");
  }
  if (routeExtras?.routeReady === false) {
    add("route");
  }

  return Array.from(requiredReupload);
}

function _normalizeCompositeAuditText(value) {
  return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function classifyCompositeScheduleInputHint(hint = "", value = "") {
  const text = String([hint, value].filter(Boolean).join(" ") || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const textWithoutPublishTime = text.replace(/发布时间/g, "发布");
  const hasDateMarker = /日期|date|年|月|日/i.test(text);
  const hasTimeMarker = /时间|time|\d{1,2}:\d{2}|小时|分钟/i.test(textWithoutPublishTime);
  if (
    /日期和时间|日期时间|datetime|date\s*time/i.test(text)
    || (hasDateMarker && hasTimeMarker)
    || /\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}/.test(text)
  ) {
    return "datetime";
  }
  if (hasDateMarker) return "date";
  if (hasTimeMarker) return "time";
  return "";
}

export function _buildCompositeExpectedContentSnapshot(content, platform) {
  const title = String(platform === "x" ? "" : content.title || "").trim();
  const bodyBase = String(platform === "x" ? platformBodyWithTags(platform, content) : content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10).slice(0, 40);
  const collection = expectedCollectionName(content);
  const coverPath = expectedCoverPath(content);
  const declaration = expectedCompositeDeclaration(content, platform);
  const scheduledAt = String(content.scheduled_publish_at || "").trim();
  const platformExtras = content.platform_specific_overrides && typeof content.platform_specific_overrides === "object"
    ? content.platform_specific_overrides
    : {};
  const xShareLink = String(platformExtras.x_share_link || platformExtras.x_share_url || "").trim();
  return {
    platform,
    title,
    body: String(bodyBase || (platform === "x" && xShareLink ? xShareLink : "")).trim(),
    tags,
    collection,
    declaration,
    schedule_display: parseChinaLocalSchedule(scheduledAt).display,
    cover_path: coverPath,
    expected_share_link: xShareLink,
  };
}

export function deriveCompositeFinalPrePublishVisualVerification(
  platform,
  content,
  integrity = {},
  publicationAudit = {},
  publicationFieldSnapshot = {},
  snapshot = {},
) {
  const expected = _buildCompositeExpectedContentSnapshot(content, platform);
  const checklist = publicationAudit?.checklist && typeof publicationAudit.checklist === "object"
    ? publicationAudit.checklist
    : {};
  const route = {
    url: String(snapshot?.url || publicationFieldSnapshot?.route?.url || integrity?.platform_extras?.route?.url || "").trim(),
    title: String(snapshot?.title || publicationFieldSnapshot?.route?.title || integrity?.platform_extras?.route?.title || "").trim(),
  };
  const visualEvidence = normalizeVisualEvidence(snapshot?.visual_evidence);
  const visibleLines = Array.isArray(snapshot?.lines)
    ? snapshot.lines.map((item) => String(item || "").trim()).filter(Boolean)
    : Array.isArray(integrity?.platform_extras?.relevant_lines)
      ? integrity.platform_extras.relevant_lines.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
  const requiredFields = [];
  const pushRequiredField = (fieldName, enabled) => {
    if (enabled) requiredFields.push(fieldName);
  };
  pushRequiredField("title", Boolean(expected.title));
  pushRequiredField("body", Boolean(expected.body));
  pushRequiredField("tags", Array.isArray(expected.tags) && expected.tags.length > 0);
  pushRequiredField("collection", Boolean(expected.collection));
  pushRequiredField("schedule", Boolean(expected.schedule_display));
  pushRequiredField("declaration", Boolean(expected.declaration));
  pushRequiredField("cover", Boolean(expected.cover_path) && platform !== "x");
  pushRequiredField("upload_ready", true);
  pushRequiredField("draft_state", true);
  const uniqueRequiredFields = Array.from(new Set(requiredFields));
  const blockedFields = uniqueRequiredFields.filter((fieldName) => {
    const entry = checklist[fieldName];
    if (!entry || typeof entry !== "object") return true;
    if (entry.required === false) return false;
    return entry.verified === false;
  });
  const draftStateActual = String(checklist?.draft_state?.actual || publicationFieldSnapshot?.draft_state || "").trim();
  const uploadReadyActual = String(checklist?.upload_ready?.actual || publicationFieldSnapshot?.upload_ready || "").trim();
  const blockingReasons = [];
  if (!visualEvidence || !String(visualEvidence.artifact_path || "").trim()) {
    blockingReasons.push("missing_visual_evidence");
  }
  if (String(integrity?.verification_state || "").trim() !== "ready") {
    blockingReasons.push(`route_${String(integrity?.verification_state || "unknown").trim() || "unknown"}`);
  }
  if (blockedFields.length > 0) {
    blockingReasons.push(`required_fields:${blockedFields.join("|")}`);
  }
  if (draftStateActual && /residual|dirty|stale/i.test(draftStateActual)) {
    blockingReasons.push("draft_state_not_clean");
  }
  if (uploadReadyActual && !/^(ready|uploaded|complete)$/i.test(uploadReadyActual)) {
    blockingReasons.push(`upload_not_ready:${uploadReadyActual}`);
  }
  return {
    platform,
    verified: blockingReasons.length === 0,
    required_fields: uniqueRequiredFields,
    blocked_fields: blockedFields,
    blocking_reasons: blockingReasons,
    visual_evidence: visualEvidence,
    route,
    visible_lines: visibleLines.slice(0, 160),
  };
}

export function shouldAcceptCollapsedDouyinScheduleEvidence(content, integrity = {}, fields = {}) {
  const expectedDisplay = parseChinaLocalSchedule(String(content?.scheduled_publish_at || "").trim()).display;
  if (!expectedDisplay) return false;
  const expectedDate = expectedDisplay.slice(0, 10);
  if (!expectedDate) return false;
  const scheduleField = fields.schedule && typeof fields.schedule === "object" ? fields.schedule : {};
  if (scheduleField.verified === true) return true;
  const platformExtras = integrity?.platform_extras && typeof integrity.platform_extras === "object"
    ? integrity.platform_extras
    : {};
  const checkedScheduled = Boolean(platformExtras.douyin_checked_schedule);
  const dateValue = String(platformExtras.douyin_schedule_date_value || "").trim();
  if (!checkedScheduled) return false;
  return !dateValue || dateValue === expectedDate;
}

function _actualTagsFromCompositeFields(field = {}) {
  if (Array.isArray(field.actual) && field.actual.length) return field.actual.map((value) => String(value || "").trim()).filter(Boolean);
  if (Array.isArray(field.actual_checks)) {
    return field.actual_checks
      .filter((item) => item && item.present)
      .map((item) => String(item.tag || "").trim())
      .filter(Boolean);
  }
  return [];
}

function _buildCompositeActualContentSnapshot(fields = {}) {
  const field = (name) => fields[name] || {};
  return {
    title: String(field("title").actual || "").trim(),
    body: String(field("body").actual || "").trim(),
    tags: _actualTagsFromCompositeFields(field("tags")),
    collection: String(field("collection").actual || "").trim(),
    schedule: String(field("schedule").actual || "").trim(),
    cover_path_present: Boolean(field("cover").uploaded || field("cover").verified),
    declaration_present: Boolean(field("declaration").verified),
    upload_ready: Boolean(field("upload_ready").verified),
    cover_actual: String(field("cover").actual || "").trim(),
  };
}

function _collectionHasExpectedTagOrText(actualCollection, expectedCollection) {
  const expected = _normalizeCompositeAuditText(expectedCollection);
  const actual = _normalizeCompositeAuditText(actualCollection);
  return !expected || expected === "none" || actual.includes(expected) || expected.includes(actual);
}

function _normalizeCompositeVerificationPolicyField(fieldName = "") {
  const text = String(fieldName || "").trim();
  if (!text) return "";
  if (text === "tag" || text === "tags" || text.startsWith("tags:")) return "tags";
  return text.replace(/[^a-z0-9_]/gi, "").toLowerCase();
}

function _evaluateCompositePlanContentMatch(platform, content, fields = {}) {
  const expected = _buildCompositeExpectedContentSnapshot(content, platform);
  const actual = _buildCompositeActualContentSnapshot(fields);
  const missing = [];
  const optionalMissing = [];
  const softVerificationFields = compositePlatformSoftVerificationFields(platform);
  const fieldMatches = {};
  const normalizedExpectedTitle = _normalizeCompositeAuditText(expected.title);
  const normalizedActualTitle = _normalizeCompositeAuditText(actual.title);
  const normalizedExpectedBody = _normalizeCompositeAuditText(expected.body);
  const normalizedActualBody = _normalizeCompositeAuditText(actual.body);
  const expectedTags = Array.from(new Set((expected.tags || []).map((item) => _normalizeCompositeAuditText(item)).filter(Boolean)));
  const actualTags = new Set((actual.tags || []).map((item) => _normalizeCompositeAuditText(item)).filter(Boolean));
  const titleExpected = normalizedExpectedTitle.length > 0;
  const bodyExpected = normalizedExpectedBody.length > 0;
  const tagVerified = expectedTags.every((tag) => actualTags.has(tag));
  const bodyMatches = platform === "x"
    ? true
    : !bodyExpected || verifyCompositeBodyField(platform, expected.body, actual.body, { tagVerified });
  const titleMatches = !titleExpected || (
    platform !== "x"
    && Boolean(normalizedActualTitle)
    && (normalizedActualTitle.includes(normalizedExpectedTitle) || normalizedExpectedTitle.includes(normalizedActualTitle))
  );
  const tagsMatch = platform === "x" ? true : tagVerified;
  const collectionMatch = !expected.collection || _collectionHasExpectedTagOrText(actual.collection, expected.collection);
  const scheduleMatch = !expected.schedule_display || Boolean(actual.schedule);
  const coverMatch = !expected.cover_path || actual.cover_path_present;
  const declarationMatch = !["douyin", "xiaohongshu", "kuaishou", "wechat-channels", "toutiao", "bilibili"].includes(platform)
    || fields.declaration?.verified !== false;
  const recordMissing = (fieldName, value = fieldName) => {
    const normalizedField = _normalizeCompositeVerificationPolicyField(fieldName);
    if (normalizedField && softVerificationFields.has(normalizedField)) {
      optionalMissing.push(value);
      return;
    }
    missing.push(value);
  };
  if (!titleMatches && titleExpected) recordMissing("title");
  if (!bodyMatches && bodyExpected) recordMissing("body");
  if (!tagsMatch) recordMissing("tags", `tags:${expected.tags.join(",")}`);
  if (!collectionMatch && expected.collection) recordMissing("collection");
  if (!scheduleMatch && expected.schedule_display) recordMissing("schedule");
  if (!coverMatch && expected.cover_path) recordMissing("cover");
  if (!declarationMatch) recordMissing("declaration");
  return {
    verified: missing.length === 0,
    missing,
    optional_missing: optionalMissing,
    expected,
    actual,
    fieldMatches: {
      title: titleMatches,
      body: bodyMatches,
      tags: tagsMatch,
      collection: collectionMatch,
      schedule: scheduleMatch,
      cover: coverMatch,
      declaration: declarationMatch,
    },
  };
}

function _isDouyinPostPublishManagementRoute(routeUrl = "") {
  return /creator\.douyin\.com\/creator-micro\/content\/manage/i.test(String(routeUrl || ""));
}

function _hasDouyinPostPublishReceiptSurface(platform, integrity = {}, finalPublish = {}) {
  if (platform !== "douyin") return false;
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || "",
  );
  const relevantText = [
    ...(integrity?.platform_extras?.relevant_lines || []),
    ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" ");
  const receiptConfirmed = Boolean(finalPublish?.receipt_like || finalPublish?.success_like);
  const successSignals = /发布成功|已发布|审核中|作品管理|内容管理|加载中…\s*发布成功/.test(relevantText);
  return receiptConfirmed && _isDouyinPostPublishManagementRoute(routeUrl) && successSignals;
}

function _hasXiaohongshuPostPublishReceiptSurface(platform, integrity = {}, finalPublish = {}) {
  if (platform !== "xiaohongshu") return false;
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || "",
  );
  const relevantText = [
    ...(integrity?.platform_extras?.relevant_lines || []),
    ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" ");
  const receiptConfirmed = Boolean(finalPublish?.receipt_like || finalPublish?.success_like || integrity?.platform_extras?.receipt_like);
  const successSignals = /发布成功|笔记发布成功|审核中|已发布/.test(relevantText);
  return receiptConfirmed && /creator\.xiaohongshu\.com\/publish\/success/i.test(routeUrl) && successSignals;
}

function _hasXiaohongshuNoteManagerReceiptSurface(platform, integrity = {}, finalPublish = {}) {
  if (platform !== "xiaohongshu") return false;
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || "",
  );
  const relevantText = [
    ...(integrity?.platform_extras?.relevant_lines || []),
    ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" ");
  return /creator\.xiaohongshu\.com\/new\/note-manager/i.test(routeUrl)
    && /笔记管理|已发布|审核中/.test(relevantText);
}

function _hasYouTubeStudioReceiptSurface(platform, integrity = {}, finalPublish = {}) {
  if (platform !== "youtube") return false;
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || finalPublish?.route?.url
    || "",
  );
  const relevantText = [
    ...(integrity?.platform_extras?.relevant_lines || []),
    ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" ");
  const receiptBinding = deriveYouTubeStudioReceiptBinding(integrity, finalPublish);
  const receiptConfirmed = Boolean(finalPublish?.receipt_like || finalPublish?.success_like || receiptBinding.receipt_like);
  return receiptConfirmed
    && /studio\.youtube\.com\/video\/[A-Za-z0-9_-]+\/edit\b/i.test(routeUrl)
    && (Boolean(receiptBinding.youtube_receipt_video_id) || /视频链接|已排定时间|已安排好视频发布时间|公开范围/.test(relevantText));
}

function _hasToutiaoManageReceiptSurface(platform, integrity = {}, finalPublish = {}) {
  if (platform !== "toutiao") return false;
  const routeUrl = String(
    integrity?.platform_extras?.route?.url
    || finalPublish?.post_click_integrity?.platform_extras?.route?.url
    || "",
  );
  const relevantText = [
    ...(integrity?.platform_extras?.relevant_lines || []),
    ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
  ]
    .map((value) => String(value || "").trim())
    .filter(Boolean)
    .join(" ");
  return /mp\.toutiao\.com\/profile_v4\/manage\/content\/all/i.test(routeUrl)
    && /内容管理|作品管理|已发布|审核中|视频管理/.test(relevantText);
}

export function _buildVerificationOnlyCurrentPageTargetMissing(platform, content, route = {}, snapshot = {}, integrity = {}) {
  const code = `${platform}_verification_current_page_target_missing`;
  const reason = "当前页面不是本次内容对应的发布页/回执页，不能把整页后台内容当成字段读回结果。";
  const recoveryContext = _extract_publication_recovery_context(content);
  const routePayload = {
    url: String(route?.url || "").trim(),
    title: String(route?.title || "").trim(),
    path: String(route?.path || "").trim(),
  };
  return {
    status: "needs_human",
    result: _attach_publication_content_signature({
      platform,
      route: routePayload,
      publication_audit: {},
      publication_field_snapshot: {},
      material_integrity: {
        ...(integrity && typeof integrity === "object" ? integrity : {}),
        verification_state: "target_missing",
        verification_reason: reason,
      },
      final_publish: {
        verification_only: true,
        stop_before_final_publish: true,
      },
      visible_option_lines: (snapshot?.lines || []).slice(0, 160),
      ..._build_publication_recovery_hint({
        platform,
        code,
        reason,
        route: routePayload,
        visibleLines: (snapshot?.lines || []).slice(0, 160),
        clearDraftContext: false,
        forceRefresh: true,
        recoveryOverrides: {
          recovery_mode: recoveryContext.recovery_mode || "auto_recover",
          verification_only_current_page: recoveryContext.verification_only_current_page,
          repair_only_current_page: recoveryContext.repair_only_current_page,
          prepublish_only_current_page: recoveryContext.prepublish_only_current_page,
          prepare_only_current_page: recoveryContext.prepare_only_current_page,
          verify_media_upload: recoveryContext.verify_media_upload,
          wait_for_publish_confirmation: recoveryContext.wait_for_publish_confirmation,
        },
        blockers: [{
          code,
          message: "当前页面没有绑定到本次目标内容，停止只读校验以避免误把后台列表当发布页。",
          details: `route=${routePayload.url}`,
        }],
      }).recovery,
    }, content),
    error: {
      code,
      message: reason,
      details: {
        route: routePayload,
      },
    },
  };
}

export function _buildVerificationOnlyMaterialIntegrityFailure(
  platform,
  content,
  route = {},
  snapshot = {},
  integrity = {},
  publicationAudit = {},
  publicationFieldSnapshot = {},
  options = {},
) {
  const code = `${platform}_verification_only_material_integrity_failed`;
  const recoveryContext = _extract_publication_recovery_context(content);
  const requiredUnverified = Array.isArray(publicationAudit?.required_unverified)
    ? publicationAudit.required_unverified.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const reason = "当前页面已进入发布页，但字段读回校验未通过，已阻断后续发布。";
  const routePayload = {
    url: String(route?.url || "").trim(),
    title: String(route?.title || "").trim(),
    path: String(route?.path || "").trim(),
  };
  const finalPublish = options?.final_publish && typeof options.final_publish === "object"
    ? options.final_publish
    : {};
  const actionHistory = Array.isArray(options?.actions) ? options.actions.slice(0, 120) : [];
  return {
    status: "needs_human",
    result: _attach_publication_content_signature({
      platform,
      route: routePayload,
      publication_audit: publicationAudit,
      publication_field_snapshot: publicationFieldSnapshot,
      material_integrity: integrity,
      final_publish: {
        verification_only: true,
        stop_before_final_publish: true,
        ...finalPublish,
      },
      actions: actionHistory,
      visible_option_lines: (snapshot?.lines || []).slice(0, 160),
      ..._build_publication_recovery_hint({
        platform,
        code,
        reason,
        route: routePayload,
        actionHistory: actionHistory,
        visibleLines: (snapshot?.lines || []).slice(0, 160),
        clearDraftContext: false,
        forceRefresh: true,
        recoveryOverrides: {
          recovery_mode: recoveryContext.recovery_mode || "auto_recover",
          verification_only_current_page: recoveryContext.verification_only_current_page,
          repair_only_current_page: recoveryContext.repair_only_current_page,
          prepublish_only_current_page: recoveryContext.prepublish_only_current_page,
          prepare_only_current_page: recoveryContext.prepare_only_current_page,
          verify_media_upload: recoveryContext.verify_media_upload,
          wait_for_publish_confirmation: recoveryContext.wait_for_publish_confirmation,
        },
        blockers: [{
          code,
          message: `当前发布页字段未完成校验：${requiredUnverified.join(",") || "unknown"}`,
          details: `verification_only_required_unverified=${requiredUnverified.join(",")}`,
        }],
      }).recovery,
    }, content),
    error: {
      code,
      message: reason,
      details: {
        route: routePayload,
        required_unverified: requiredUnverified,
      },
    },
  };
}

export function shouldWaitForVerificationOnlyMaterialIntegrity(integrity = {}) {
  if (!integrity || typeof integrity !== "object") return false;
  if (String(integrity.verification_state || "").trim() !== "not_ready") return false;
  const reason = String(integrity.verification_reason || "").trim();
  const routeReadyState = integrity.route_ready_state && typeof integrity.route_ready_state === "object"
    ? integrity.route_ready_state
    : {};
  const routeReady = Boolean(routeReadyState.route_ready);
  const loadingSurface = Boolean(routeReadyState.loading_surface);
  const inputReady = Boolean(routeReadyState.input_ready);
  if (reason === "publish_route_loading") return true;
  if (reason === "publish_route_not_ready" && routeReady && (!inputReady || loadingSurface)) return true;
  return false;
}

export function _buildVerificationOnlyRouteNotReadyFailure(platform, content, route = {}, snapshot = {}, integrity = {}) {
  const verificationReason = String(integrity?.verification_reason || "").trim();
  const mediaEntrySurface = verificationReason === "publish_media_entry";
  const code = mediaEntrySurface ? `${platform}_verification_only_media_missing` : `${platform}_verification_only_route_not_ready`;
  const reason = mediaEntrySurface
    ? "当前页面已进入上传入口，但尚未确认目标媒体已挂载，安全模式不会自动补上传。"
    : "当前页面已跳转到发布页，但页面状态仍未稳定，已停止只读校验并要求刷新后重试。";
  const recoveryContext = _extract_publication_recovery_context(content);
  const routePayload = {
    url: String(route?.url || "").trim(),
    title: String(route?.title || "").trim(),
    path: String(route?.path || "").trim(),
  };
  return {
    status: "needs_human",
    result: _attach_publication_content_signature({
      platform,
      route: routePayload,
      publication_audit: {},
      publication_field_snapshot: {},
      material_integrity: {
        ...(integrity && typeof integrity === "object" ? integrity : {}),
        verification_state: String(integrity?.verification_state || "not_ready").trim() || "not_ready",
        verification_reason: String(integrity?.verification_reason || "publish_route_not_ready").trim() || "publish_route_not_ready",
      },
      final_publish: {
        verification_only: true,
        stop_before_final_publish: true,
      },
      visible_option_lines: (snapshot?.lines || []).slice(0, 160),
      ..._build_publication_recovery_hint({
        platform,
        code,
        reason,
        route: routePayload,
        visibleLines: (snapshot?.lines || []).slice(0, 160),
        clearDraftContext: false,
        forceRefresh: true,
        recoveryOverrides: {
          recovery_mode: recoveryContext.recovery_mode || "auto_recover",
          verification_only_current_page: recoveryContext.verification_only_current_page,
          repair_only_current_page: recoveryContext.repair_only_current_page,
          prepublish_only_current_page: recoveryContext.prepublish_only_current_page,
          prepare_only_current_page: recoveryContext.prepare_only_current_page,
          verify_media_upload: recoveryContext.verify_media_upload,
          wait_for_publish_confirmation: recoveryContext.wait_for_publish_confirmation,
        },
        blockers: [{
          code,
          message: mediaEntrySurface
            ? "当前页面仍停留在上传入口，尚未确认目标媒体已挂载，安全模式不会自动补上传。"
            : "当前发布页仍处于加载或未稳定态，不能把加载态误判成字段失败。",
          details: `verification_reason=${String(integrity?.verification_reason || "")}`,
        }],
      }).recovery,
    }, content),
    error: {
      code,
      message: reason,
      details: {
        route: routePayload,
        verification_reason: String(integrity?.verification_reason || "").trim(),
        route_ready_state: integrity?.route_ready_state && typeof integrity.route_ready_state === "object"
          ? integrity.route_ready_state
          : {},
      },
    },
  };
}

async function waitForVerificationOnlyMaterialIntegrity(client, platform, content, timeoutMs = 12000, onPoll = null) {
  const startedAt = Date.now();
  let integrity = await readCompositeMaterialIntegrity(client, platform, content);
  let attempts = 1;
  while ((Date.now() - startedAt) < timeoutMs && shouldWaitForVerificationOnlyMaterialIntegrity(integrity)) {
    if (typeof onPoll === "function") {
      try {
        onPoll({
          attempt: attempts,
          waited_ms: Date.now() - startedAt,
          integrity,
        });
      } catch {}
    }
    await sleep(1200);
    integrity = await readCompositeMaterialIntegrity(client, platform, content);
    attempts += 1;
  }
  return {
    integrity,
    waited_ms: Date.now() - startedAt,
    attempts,
  };
}

function _cloneCompositeIntegrity(integrity = {}) {
  return {
    ...(integrity && typeof integrity === "object" ? integrity : {}),
    fields: {
      ...(integrity?.fields && typeof integrity.fields === "object" ? integrity.fields : {}),
    },
    platform_extras: {
      ...(integrity?.platform_extras && typeof integrity.platform_extras === "object" ? integrity.platform_extras : {}),
    },
  };
}

export function normalizeCompositePostPublishIntegrity(platform, finalIntegrity = {}, prePublishIntegrity = {}, finalPublish = {}, content = {}) {
  const hasDouyinReceipt = _hasDouyinPostPublishReceiptSurface(platform, finalIntegrity, finalPublish);
  const hasXiaohongshuReceipt = _hasXiaohongshuPostPublishReceiptSurface(platform, finalIntegrity, finalPublish);
  const hasXiaohongshuNoteManagerReceipt = _hasXiaohongshuNoteManagerReceiptSurface(platform, finalIntegrity, finalPublish);
  const hasYouTubeReceipt = _hasYouTubeStudioReceiptSurface(platform, finalIntegrity, finalPublish);
  const hasToutiaoManageReceipt = _hasToutiaoManageReceiptSurface(platform, finalIntegrity, finalPublish);
  if (!hasDouyinReceipt && !hasXiaohongshuReceipt && !hasXiaohongshuNoteManagerReceipt && !hasYouTubeReceipt && !hasToutiaoManageReceipt) {
    return finalIntegrity;
  }
  const normalized = _cloneCompositeIntegrity(finalIntegrity);
  const preFields = prePublishIntegrity?.fields && typeof prePublishIntegrity.fields === "object"
    ? prePublishIntegrity.fields
    : {};
  const inheritedPrePublishFields = ["cover", "collection", "declaration", "upload_ready"];
  for (const fieldName of inheritedPrePublishFields) {
    const preField = preFields[fieldName];
    if (!preField || typeof preField !== "object") continue;
    normalized.fields[fieldName] = { ...preField };
  }
  if (platform === "douyin") {
    const expectedTitle = String(
      content?.title
      || preFields?.title?.expected
      || preFields?.title?.actual
      || "",
    ).trim();
    const expectedBody = String(
      content?.body
      || preFields?.body?.expected
      || preFields?.body?.actual
      || "",
    ).trim();
    const expectedSchedule = parseChinaLocalSchedule(
      String(
        content?.scheduled_publish_at
        || preFields?.schedule?.expected
        || preFields?.schedule?.actual
        || "",
      ).trim(),
    ).display || String(preFields?.schedule?.expected || "").trim();
    const expectedTagValues = expectedTags(content, 10).length
      ? expectedTags(content, 10)
      : ((preFields?.tags?.expected && Array.isArray(preFields.tags.expected)) ? preFields.tags.expected.map((item) => String(item || "").trim()).filter(Boolean) : []);
    const expectedCreatedAt = String(finalPublish?.task_created_at || "").trim();
    const relevantLines = [
      ...(normalized.platform_extras?.relevant_lines || []),
      ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
    ]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    const manageCard = selectBestDouyinManageCardEvidence(
      relevantLines,
      {
        title: expectedTitle,
        body: expectedBody,
        schedule: expectedSchedule,
        tags: expectedTagValues,
        created_at: expectedCreatedAt,
      },
    );
    if (manageCard.matched) {
      const tagChecks = Array.isArray(manageCard.tag_checks)
        ? manageCard.tag_checks
        : expectedTagValues.map((tag) => ({ tag, present: manageCard.tags.includes(tag) }));
      const tagVerified = tagChecks.every((item) => item.present);
      normalized.fields.title = {
        ...(normalized.fields.title || {}),
        actual: manageCard.title,
        verified: !expectedTitle || String(manageCard.title || "").includes(expectedTitle),
      };
      normalized.fields.body = {
        ...(normalized.fields.body || {}),
        actual: manageCard.body,
        verified: Boolean(manageCard.body_verified) || verifyCompositeBodyField("douyin", expectedBody, manageCard.body, { tagVerified }),
      };
      normalized.fields.tags = {
        ...(normalized.fields.tags || {}),
        actual: manageCard.tags,
        actual_checks: tagChecks,
        verified: tagVerified,
      };
      normalized.fields.schedule = {
        ...(normalized.fields.schedule || {}),
        actual: manageCard.schedule,
        verified: Boolean(manageCard.schedule_verified) || !expectedSchedule || manageCard.schedule === expectedSchedule,
      };
      normalized.platform_extras = {
        ...normalized.platform_extras,
        douyin_manage_card: manageCard,
        receipt_target_bound: true,
        receipt_binding_source: "douyin_manage_card",
      };
      normalized.verification_state = "ready";
      normalized.verification_reason = "receipt_bound";
      normalized.route_ready_state = {
        ...(normalized.route_ready_state && typeof normalized.route_ready_state === "object"
          ? normalized.route_ready_state
          : {}),
        route_ready: true,
        input_ready: true,
        loading_surface: false,
      };
    } else {
      normalized.platform_extras = {
        ...normalized.platform_extras,
        douyin_manage_card: manageCard,
        receipt_target_bound: false,
        receipt_binding_source: "unbound_manage_receipt",
      };
    }
    normalized.platform_extras = {
      ...normalized.platform_extras,
      receipt_like: true,
      post_publish_surface: "douyin_content_manage_receipt",
      inherited_pre_publish_fields: inheritedPrePublishFields.filter((fieldName) => Boolean(preFields[fieldName])),
    };
    return normalized;
  }
  if (platform === "xiaohongshu" && hasXiaohongshuNoteManagerReceipt) {
    const expectedTitle = String(
      content?.title
      || preFields?.title?.expected
      || preFields?.title?.actual
      || "",
    ).trim();
    const expectedCreatedAt = String(finalPublish?.task_created_at || "").trim();
    const relevantLines = [
      ...(normalized.platform_extras?.relevant_lines || []),
      ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
    ]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    const noteManagerCard = selectBestXiaohongshuNoteManagerEvidence(
      relevantLines,
      {
        title: expectedTitle,
        created_at: expectedCreatedAt,
      },
    );
    const inheritedReceiptFields = ["cover", "collection", "declaration", "upload_ready", "body", "tags", "schedule", "title"];
    for (const fieldName of inheritedReceiptFields) {
      const preField = preFields[fieldName];
      if (!preField || typeof preField !== "object") continue;
      normalized.fields[fieldName] = { ...preField };
    }
    if (noteManagerCard.matched) {
      normalized.fields.title = {
        ...(normalized.fields.title || {}),
        actual: noteManagerCard.title,
        verified: !expectedTitle || noteManagerCard.title_verified !== false,
      };
      normalized.platform_extras = {
        ...normalized.platform_extras,
        xiaohongshu_note_manager_card: noteManagerCard,
        receipt_target_bound: true,
        receipt_binding_source: "xiaohongshu_note_manager_card",
      };
      normalized.verification_state = "ready";
      normalized.verification_reason = "receipt_bound";
      normalized.route_ready_state = {
        ...(normalized.route_ready_state && typeof normalized.route_ready_state === "object"
          ? normalized.route_ready_state
          : {}),
        route_ready: true,
        input_ready: true,
        loading_surface: false,
      };
    } else {
      normalized.platform_extras = {
        ...normalized.platform_extras,
        xiaohongshu_note_manager_card: noteManagerCard,
        receipt_target_bound: false,
        receipt_binding_source: "xiaohongshu_note_manager_unbound",
      };
    }
    normalized.platform_extras = {
      ...normalized.platform_extras,
      receipt_like: true,
      post_publish_surface: "xiaohongshu_note_manager_receipt",
      inherited_pre_publish_fields: inheritedReceiptFields.filter((fieldName) => Boolean(preFields[fieldName])),
    };
    return normalized;
  }
  if (platform === "xiaohongshu" && hasXiaohongshuReceipt) {
    normalized.platform_extras = {
      ...normalized.platform_extras,
      receipt_like: true,
      receipt_target_bound: true,
      receipt_binding_source: "xiaohongshu_publish_success",
      post_publish_surface: "xiaohongshu_publish_success_receipt",
      inherited_pre_publish_fields: inheritedPrePublishFields.filter((fieldName) => Boolean(preFields[fieldName])),
    };
    normalized.verification_state = "ready";
    normalized.verification_reason = "receipt_bound";
    normalized.route_ready_state = {
      ...(normalized.route_ready_state && typeof normalized.route_ready_state === "object"
        ? normalized.route_ready_state
        : {}),
      route_ready: true,
      input_ready: true,
      loading_surface: false,
    };
    return normalized;
  }
  if (platform === "youtube" && hasYouTubeReceipt) {
    const receiptBinding = deriveYouTubeStudioReceiptBinding(normalized, finalPublish);
    normalized.platform_extras = {
      ...normalized.platform_extras,
      ...receiptBinding,
      inherited_pre_publish_fields: inheritedPrePublishFields.filter((fieldName) => Boolean(preFields[fieldName])),
    };
    if (receiptBinding.receipt_target_bound === true) {
      normalized.verification_state = "ready";
      normalized.verification_reason = "receipt_bound";
      normalized.route_ready_state = {
        ...(normalized.route_ready_state && typeof normalized.route_ready_state === "object"
          ? normalized.route_ready_state
          : {}),
        route_ready: true,
        input_ready: true,
        loading_surface: false,
      };
    }
    return normalized;
  }
  if (platform === "toutiao" && hasToutiaoManageReceipt) {
    const expectedTitle = String(
      content?.title
      || preFields?.title?.expected
      || preFields?.title?.actual
      || "",
    ).trim();
    const relevantLines = [
      ...(normalized.platform_extras?.relevant_lines || []),
      ...(finalPublish?.post_click_integrity?.platform_extras?.relevant_lines || []),
    ]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    const manageCard = selectBestToutiaoManageEvidence(relevantLines, { title: expectedTitle });
    const inheritedReceiptFields = ["cover", "collection", "declaration", "upload_ready", "body", "tags", "schedule", "title"];
    for (const fieldName of inheritedReceiptFields) {
      const preField = preFields[fieldName];
      if (!preField || typeof preField !== "object") continue;
      normalized.fields[fieldName] = { ...preField };
    }
    if (manageCard.matched) {
      normalized.fields.title = {
        ...(normalized.fields.title || {}),
        actual: manageCard.title,
        verified: !expectedTitle || manageCard.title_verified !== false,
      };
      normalized.platform_extras = {
        ...normalized.platform_extras,
        toutiao_manage_card: manageCard,
        receipt_target_bound: true,
        receipt_binding_source: "toutiao_manage_card",
      };
      normalized.verification_state = "ready";
      normalized.verification_reason = "receipt_bound";
      normalized.route_ready_state = {
        ...(normalized.route_ready_state && typeof normalized.route_ready_state === "object"
          ? normalized.route_ready_state
          : {}),
        route_ready: true,
        input_ready: true,
        loading_surface: false,
      };
    } else {
      normalized.platform_extras = {
        ...normalized.platform_extras,
        toutiao_manage_card: manageCard,
        receipt_target_bound: false,
        receipt_binding_source: "toutiao_manage_receipt_unbound",
      };
    }
    normalized.platform_extras = {
      ...normalized.platform_extras,
      receipt_like: true,
      post_publish_surface: "toutiao_content_manage_receipt",
      inherited_pre_publish_fields: inheritedReceiptFields.filter((fieldName) => Boolean(preFields[fieldName])),
    };
    return normalized;
  }
  return normalized;
}

export function buildCompositePublicationAudit(platform, content, integrity, finalPublish = {}, route = {}) {
  const fields = { ...(integrity?.fields || {}) };
  const softVerificationFields = compositePlatformSoftVerificationFields(platform);
  const douyinBoundManageReceipt = Boolean(
    platform === "douyin"
    && integrity?.platform_extras?.post_publish_surface === "douyin_content_manage_receipt"
    && integrity?.platform_extras?.receipt_target_bound === true
  );
  const douyinReceiptTargetBound = !(
    platform === "douyin"
    && integrity?.platform_extras?.post_publish_surface === "douyin_content_manage_receipt"
    && integrity?.platform_extras?.receipt_target_bound === false
  );
  const xiaohongshuReceiptTargetBound = !(
    platform === "xiaohongshu"
    && /^xiaohongshu_.*_receipt$/.test(String(integrity?.platform_extras?.post_publish_surface || ""))
    && integrity?.platform_extras?.receipt_target_bound === false
  );
  const toutiaoReceiptTargetBound = !(
    platform === "toutiao"
    && String(integrity?.platform_extras?.post_publish_surface || "") === "toutiao_content_manage_receipt"
    && integrity?.platform_extras?.receipt_target_bound === false
  );
  const youtubeReceiptTargetBound = !(
    platform === "youtube"
    && String(integrity?.platform_extras?.post_publish_surface || "") === "youtube_studio_editor_receipt"
    && integrity?.platform_extras?.receipt_target_bound === false
  );
  const hasXShareLink = platform === "x" && Boolean(
    String((content?.platform_specific_overrides || {}).x_share_link || (content?.platform_specific_overrides || {}).x_share_url || "").trim()
  );
  const xPublishedComposerCollapsed =
    platform === "x" &&
    Boolean(finalPublish?.receipt_like) &&
    /\/i\/graduated-access/i.test(String(finalPublish?.post_click_integrity?.platform_extras?.route?.url || integrity?.platform_extras?.route?.url || ""));
  const xPublishedByReceiptRoute =
    platform === "x" &&
    Boolean(finalPublish?.receipt_like) &&
    !/x\.com\/compose/i.test(String(finalPublish?.post_click_integrity?.platform_extras?.route?.url || route?.url || integrity?.platform_extras?.route?.url || ""));
  const xReceiptLike = platform === "x" && Boolean(finalPublish?.receipt_like);
  if (platform === "douyin" && shouldAcceptCollapsedDouyinScheduleEvidence(content, integrity, fields)) {
    const expectedScheduleDisplay = parseChinaLocalSchedule(String(content?.scheduled_publish_at || "").trim()).display;
    if (fields.schedule && typeof fields.schedule === "object") {
      fields.schedule = {
        ...fields.schedule,
        actual: String(fields.schedule.actual || expectedScheduleDisplay || "").trim(),
        verified: true,
        verification_mode: "collapsed_douyin_schedule",
      };
    }
  }
  if (xPublishedComposerCollapsed) {
    if (fields.body) fields.body.verified = true;
    if (fields.tags) fields.tags.verified = true;
  } else if (xPublishedByReceiptRoute || hasXShareLink || xReceiptLike) {
    if (fields.body) fields.body.verified = true;
    if (fields.tags) fields.tags.verified = true;
  }
  const receiptRequired = Boolean(
    finalPublish && typeof finalPublish === "object" && (
      finalPublish.receipt_like
      || finalPublish.success_like
      || finalPublish.receipt_wait > 0
      || finalPublish.click?.clicked
      || finalPublish.second_confirm?.clicked
      || integrity?.platform_extras?.receipt_like
      || integrity?.platform_extras?.youtube_link
      || integrity?.platform_extras?.youtube_scheduled
    ),
  );
  fields.receipt = {
    verified: Boolean(finalPublish.receipt_like || finalPublish.success_like || integrity?.platform_extras?.receipt_like || integrity?.platform_extras?.youtube_link || integrity?.platform_extras?.youtube_scheduled)
      && douyinReceiptTargetBound
      && xiaohongshuReceiptTargetBound
      && youtubeReceiptTargetBound
      && toutiaoReceiptTargetBound,
    expected: String(content.scheduled_publish_at || "").trim() ? "scheduled publish receipt" : "publish receipt",
    required: receiptRequired,
  };
  if (douyinBoundManageReceipt && fields.body && typeof fields.body === "object") {
    fields.body = {
      ...fields.body,
      required: false,
      verification_mode: fields.body.verification_mode || "receipt_bound_unverifiable",
    };
  }
  if (douyinBoundManageReceipt && fields.declaration && typeof fields.declaration === "object") {
    fields.declaration = {
      ...fields.declaration,
      required: false,
      verification_mode: fields.declaration.verification_mode || "receipt_bound_unverifiable",
    };
  }
  const contentMatch = _evaluateCompositePlanContentMatch(platform, content, fields);
  for (const fieldName of softVerificationFields) {
    if (fields[fieldName] && typeof fields[fieldName] === "object") {
      fields[fieldName] = {
        ...fields[fieldName],
        required: false,
      };
    }
  }
  if (douyinBoundManageReceipt && Array.isArray(contentMatch.missing)) {
    contentMatch.missing = contentMatch.missing.filter((item) => item !== "declaration" && item !== "body");
    if (contentMatch.fieldMatches && typeof contentMatch.fieldMatches === "object") {
      contentMatch.fieldMatches.declaration = true;
      contentMatch.fieldMatches.body = true;
    }
    contentMatch.verified = contentMatch.missing.length === 0;
  }
  fields.content_plan_match = {
    verified: contentMatch.verified,
    expected: contentMatch.expected,
    actual: contentMatch.actual,
    missing: contentMatch.missing,
    optional_missing: contentMatch.optional_missing || [],
    field_matches: contentMatch.fieldMatches,
    expected_unverified: contentMatch.missing,
  };
  const checklist = buildPublicationAuditChecklist(fields);
  const requiredUnverified = Object.entries(checklist)
    .filter(([, value]) => value && value.required !== false && value.verified === false)
    .map(([key]) => key);
  const routeExtras = integrity?.platform_extras?.route || route || {};
  const requiredReupload = _deriveRequiredReuploadFromCompositeAudit(platform, content, fields, routeExtras);
  const notes = [
    requiredUnverified.length > 0 ? `required_unverified:${requiredUnverified.join("|")}` : "",
    requiredReupload.length > 0 ? `required_reupload:${requiredReupload.join("|")}` : "",
    contentMatch.missing?.length > 0 ? `content_plan_missing:${contentMatch.missing.join("|")}` : "",
    contentMatch.optional_missing?.length > 0 ? `content_plan_optional_missing:${contentMatch.optional_missing.join("|")}` : "",
    integrity?.platform_extras?.draft_state_warning ? "composite_draft_residual_warning" : "",
    fields.draft_state && fields.draft_state.verified === false ? "draft_state_not_clean" : "",
  ].filter(Boolean);
  return {
    platform,
    framework_id: dedicatedCompositeFrameworkId(platform),
    dedicated_platform_framework: Boolean(dedicatedCompositeFrameworkId(platform)),
    legacy_lightweight_script_used: false,
    verified: requiredUnverified.length === 0,
    required_reupload: requiredReupload,
    required_unverified: requiredUnverified,
    notes: notes.join("；"),
    checklist,
    route: route || integrity?.platform_extras?.route || {},
    platform_extras: integrity?.platform_extras || {},
  };
}

const COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS = new Set([
  "cover",
  "title",
  "body",
  "tags",
  "collection",
  "schedule",
  "declaration",
]);
const COMPOSITE_PREPUBLISH_SAFE_BLOCKING_FIELDS = new Set([
  "upload_ready",
  "receipt",
]);

const COMPOSITE_PREPUBLISH_WAIT_ONLY_FIELDS = new Set([
  "upload_ready",
]);

export function deriveCompositePrePublishRepairPlan(audit = {}, integrity = {}, options = {}) {
  const requiredUnverified = Array.isArray(audit?.required_unverified)
    ? audit.required_unverified.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const integrityFailures = Array.isArray(integrity?.failures)
    ? integrity.failures.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const allowRepairWithBlocking = Boolean(options?.allowRepairWithBlocking);
  const directRepairable = requiredUnverified.filter((field) => COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field));
  const blockingFields = requiredUnverified.filter(
    (field) => field !== "content_plan_match" && !COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field),
  );
  const inferredRepairable = integrityFailures.filter((field) => COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field));
  const contentMismatchFallback = requiredUnverified.includes("content_plan_match")
    ? ["title", "body", "tags"].filter((field) => COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field))
    : [];
  const repairableFields = Array.from(
    new Set([
      ...directRepairable,
      ...inferredRepairable,
      ...(directRepairable.length === 0 && inferredRepairable.length === 0 ? contentMismatchFallback : []),
    ]),
  );
  const safeBlockingOnly = blockingFields.length > 0 && blockingFields.every((field) => COMPOSITE_PREPUBLISH_SAFE_BLOCKING_FIELDS.has(field));
  return {
    shouldRepair: (blockingFields.length === 0 || allowRepairWithBlocking || safeBlockingOnly) && repairableFields.length > 0,
    allow_repair_with_blocking: allowRepairWithBlocking,
    safe_blocking_only: safeBlockingOnly,
    repairable_fields: repairableFields,
    blocking_fields: blockingFields,
    required_unverified: requiredUnverified,
    integrity_failures: integrityFailures,
  };
}

export function buildCompositeRepairExecutionPlan(platform, repairableFields = []) {
  const normalizedFields = Array.from(new Set(
    (Array.isArray(repairableFields) ? repairableFields : [])
      .map((item) => String(item || "").trim())
      .filter(Boolean),
  ));
  return {
    platform: String(platform || "").trim().toLowerCase().replace(/_/g, "-"),
    fields: normalizedFields,
    rich_text: normalizedFields.some((field) => ["title", "body", "tags"].includes(field)),
    cover: normalizedFields.includes("cover"),
    collection: normalizedFields.includes("collection"),
    declaration: normalizedFields.includes("declaration"),
    schedule: normalizedFields.includes("schedule"),
  };
}

export function deriveCompositePrePublishFailureRecoveryPlan(audit = {}, integrity = {}, repairAttempt = null) {
  const requiredUnverified = Array.isArray(audit?.required_unverified)
    ? audit.required_unverified.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const integrityFailures = Array.isArray(integrity?.failures)
    ? integrity.failures.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const repairAttempted = Boolean(repairAttempt && repairAttempt.attempted);
  const hasEditableFieldFailures = requiredUnverified.some((field) => COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field))
    || integrityFailures.some((field) => COMPOSITE_PREPUBLISH_REPAIRABLE_FIELDS.has(field));
  const hasStructuralFailures = requiredUnverified.some((field) => field === "draft_state" || field === "upload_ready")
    || integrityFailures.some((field) => field === "draft_state" || field === "upload_ready");
  return {
    clear_draft_context: false,
    force_publish_page_refresh: repairAttempted || hasEditableFieldFailures || hasStructuralFailures,
    repair_attempted: repairAttempted,
    has_editable_field_failures: hasEditableFieldFailures,
    has_structural_failures: hasStructuralFailures,
  };
}

export function deriveCompositePrePublishPendingState(audit = {}, integrity = {}, repairAttempt = null) {
  const requiredUnverified = Array.isArray(audit?.required_unverified)
    ? audit.required_unverified.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const integrityFailures = Array.isArray(integrity?.failures)
    ? integrity.failures.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
  const remaining = Array.from(new Set([...requiredUnverified, ...integrityFailures]));
  const waitOnly = remaining.length > 0 && remaining.every((field) => COMPOSITE_PREPUBLISH_WAIT_ONLY_FIELDS.has(field));
  return {
    pending: waitOnly,
    wait_only: waitOnly,
    remaining,
    repair_attempted: Boolean(repairAttempt && repairAttempt.attempted),
  };
}

export function deriveCompositePostUploadIntegrityDisposition(platform, integrity = {}, repairAttempt = null) {
  const normalizedPlatform = String(platform || "").trim().toLowerCase().replace(/_/g, "-");
  const pending = deriveCompositePrePublishPendingState({}, integrity, repairAttempt);
  if (pending.wait_only) {
    return {
      status: "processing",
      code: `${normalizedPlatform}_pre_publish_upload_pending`,
      clear_draft_context: false,
      force_publish_page_refresh: true,
      remaining: pending.remaining,
      pre_publish_pending: true,
    };
  }
  const recovery = deriveCompositePrePublishFailureRecoveryPlan({}, integrity, repairAttempt);
  return {
    status: "needs_human",
    code: `${normalizedPlatform}_media_upload_integrity_not_ready`,
    clear_draft_context: Boolean(recovery.clear_draft_context),
    force_publish_page_refresh: Boolean(recovery.force_publish_page_refresh),
    remaining: pending.remaining,
    pre_publish_pending: false,
  };
}

export function buildBilibiliPublicationAudit(content, platformVerifier, finalPublish = {}, route = {}, coverAction = {}, options = {}) {
  const actual = platformVerifier?.actual || {};
  const tags = Array.from(new Set([...(content.hashtags || []), ...(content.structured_tags || [])].map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 10);
  const collection = expectedCollectionName(content);
  const failures = new Set(platformVerifier?.failures || []);
  const stopBeforeFinalPublish = Boolean(options?.stop_before_final_publish);
  const coverPolicyState = deriveCompositeCoverPolicyState("bilibili", content);
  const coverExpectedPath = expectedCoverPath(content);
  const hasFailure = (key) => failures.has(key) || (key === "body" && failures.has("description")) || (key === "tags" && [...failures].some((item) => String(item).startsWith("tag:")));
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const draftResidualWarning = (platformVerifier?.actual?.blockers || []).some((item) => {
    const signalText = String(item?.message || item?.code || item || "").trim();
    return /(编辑失败|发布失败|提交失败|发布异常|发布中止|请重试|need retry|Upload failed|上传失败|草稿|发布失败后再试|草稿提交)/i.test(signalText);
  });
  const fields = {
    cover: {
      expected_path: coverExpectedPath,
      verified: !coverExpectedPath || Boolean(coverAction?.uploaded) || (stopBeforeFinalPublish && coverPolicyState.explicit_cover_skip),
    },
    title: { expected: String(content.title || "").trim(), verified: !hasFailure("title") },
    body: { expected: String(content.body || "").trim(), verified: !hasFailure("body") },
    tags: { expected: tags, actual_checks: tags.map((tag) => ({ tag, present: !failures.has(`tag:${tag}`) })), verified: !hasFailure("tags") },
    collection: { expected: collection, verified: !collection || !hasFailure("collection") },
    schedule: { expected: String(content.scheduled_publish_at || "").trim(), verified: !scheduled || !hasFailure("schedule") },
    upload_ready: { verified: !hasFailure("upload_ready") },
    declaration: { verified: !hasFailure("declaration") },
    receipt: {
      expected: stopBeforeFinalPublish ? "stop_before_final_publish" : (scheduled ? "scheduled publish receipt" : "publish receipt"),
      verified: stopBeforeFinalPublish || Boolean(finalPublish.success_like),
    },
    draft_state: { expected: "editor_clean", actual: draftResidualWarning ? "residual_artifacts" : "clean", verified: !draftResidualWarning },
  };
  const draftWarnings = [
    draftResidualWarning ? "draft_state_not_clean" : "",
    finalPublish.success_like ? "" : "receipt_missing_or_unverified",
  ].filter(Boolean);
  const checklist = buildPublicationAuditChecklist(fields);
  const requiredUnverified = Object.entries(checklist)
    .filter(([, value]) => value && value.verified === false)
    .map(([key]) => key);
  const requiredReupload = Array.from(new Set([
    ...requiredUnverified,
    ...(draftResidualWarning ? ["draft_state"] : []),
    ...(fields.upload_ready.verified === false ? ["upload_ready"] : []),
  ]));
  const notes = [
    requiredUnverified.length > 0 ? `required_unverified:${requiredUnverified.join("|")}` : "",
    requiredReupload.length > 0 ? `required_reupload:${requiredReupload.join("|")}` : "",
    ...draftWarnings,
  ].filter(Boolean);
  return {
    platform: "bilibili",
    framework_id: dedicatedCompositeFrameworkId("bilibili"),
    dedicated_platform_framework: true,
    legacy_lightweight_script_used: false,
    verified: requiredUnverified.length === 0,
    required_reupload: requiredReupload,
    required_unverified: requiredUnverified,
    notes: notes.join("；"),
    checklist,
    route,
    platform_extras: {
      actual,
      blockers: Array.isArray(actual.blockers) ? actual.blockers : [],
      cover_action: coverAction,
      field_failures: platformVerifier?.failures || [],
      final_publish: finalPublish,
    },
  };
}

async function setGenericScheduleControls(client, platform, scheduledPublishAt) {
  const schedule = parseChinaLocalSchedule(scheduledPublishAt);
  if (!schedule.display) return { set: false, reason: "missing_schedule" };
  if (platform === "xiaohongshu") {
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const setValue = (el, value) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
        el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        return true;
      };
      const actions = [];
      const switchInput = document.querySelector(".post-time-wrapper input[type=checkbox]");
      if (switchInput && !switchInput.checked) {
        actions.push({ clicked: "xiaohongshu_schedule_checkbox", ok: click(switchInput) });
        switchInput.checked = true;
        switchInput.dispatchEvent(new Event("input", { bubbles: true }));
        switchInput.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(900);
      }
      const pickerInput =
        [...document.querySelectorAll(".post-time-wrapper .d-datepicker input,.post-time-wrapper input")]
          .filter(visible)
          .find((el) => /\\d{4}-\\d{2}-\\d{2}|日期|时间|date|time/i.test(clean([el.value, el.placeholder, el.parentElement?.innerText].join(" ")))) ||
        [...document.querySelectorAll(".post-time-wrapper input")].filter(visible).find((el) => el.type !== "checkbox");
      if (pickerInput) {
        actions.push({ set: "xiaohongshu_datetime", ok: setValue(pickerInput, expected.display), previous: clean(pickerInput.value) });
        await sleep(800);
      }
      const okButton = [...document.querySelectorAll("button,[role=button],span,div")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "确定" || item.text === "完成")
        .sort((left, right) => left.area - right.area)[0];
      if (okButton) {
        actions.push({ clicked: "xiaohongshu_datetime_ok", label: okButton.text, ok: click(okButton.el) });
        await sleep(400);
      }
      const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 60),
      };
    })()`, 12000);
  }
  if (platform === "kuaishou") {
    const expected = { display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16), inputValue: `${schedule.display}:00` };
    const actions = [];
    actions.push({ clicked: "kuaishou_schedule_entry", ...(await clickByText(client, ["定时发布", "发布时间", "预约"])) });
    await sleep(700);
    const target = await evaluateWithClient(client, `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const input = [...document.querySelectorAll("input[placeholder*=选择日期时间],.ant-picker input,input")]
        .filter(visible)
        .find((el) => /选择日期时间|\\d{4}-\\d{2}-\\d{2}|日期|时间/.test(clean([el.placeholder, el.value, el.parentElement?.innerText].join(" "))));
      if (!input) return { found: false };
      input.scrollIntoView({ block: "center", inline: "center" });
      const rect = input.getBoundingClientRect();
      return { found: true, value: input.value || "", x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`, 10000);
    actions.push({ set: "kuaishou_datetime_target", ...target });
    if (target?.found) {
      await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
      await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
      await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
      await sleep(250);
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 }).catch(() => {});
      await client.send("Input.insertText", { text: expected.inputValue }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }).catch(() => {});
      await sleep(500);
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }).catch(() => {});
      await sleep(1000);
    }
    const after = await evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify(expected)};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const inputs = [...document.querySelectorAll("input,textarea,[contenteditable=true]")]
        .filter(visible)
        .map((el) => clean(el.value || el.innerText || el.textContent || el.getAttribute("placeholder")))
        .filter(Boolean);
      const text = clean([((document.scrollingElement || document.documentElement || document.body)?.innerText) || "", ...inputs].join(" "));
      const set = text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time));
      return {
        set,
        input_values: inputs.slice(0, 40),
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|10:30|20:00|21:00/.test(line)).slice(0, 80),
      };
    })()`, 10000);
    return { set: Boolean(after.set), expected, body_after_had_schedule: Boolean(after.set), actions, ...after };
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const setInput = (el, value) => {
        if (!el) return false;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      };
      const actions = [];
      const buttons = [...document.querySelectorAll("button,[role=button],label,span,div")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => /定时发布|发布时间|预约/.test(item.text) && item.text.length <= 80)
        .sort((left, right) => left.area - right.area);
      if (buttons[0]) {
        actions.push({ clicked: "kuaishou_schedule_entry", label: buttons[0].text, ok: click(buttons[0].el) });
        await sleep(700);
      }
      const dateInputs = [...document.querySelectorAll(".ant-picker input,input[placeholder*=日期],input[placeholder*=时间]")]
        .filter(visible)
        .map((el) => ({ el, hint: clean([el.placeholder, el.value, el.parentElement?.innerText].join(" ")) }));
      for (const item of dateInputs) {
        if (/日期|date|年|月|日/i.test(item.hint)) actions.push({ set: "date_input", hint: item.hint, ok: setInput(item.el, expected.date) });
        else if (/时间|time|时|分/i.test(item.hint)) actions.push({ set: "time_input", hint: item.hint, ok: setInput(item.el, expected.time) });
      }
      await sleep(300);
      const dropdowns = [...document.querySelectorAll(".ant-picker-dropdown,.ant-picker-panel-container,.ant-picker-datetime-panel")]
        .filter(visible);
      const scoped = (selector) => dropdowns.flatMap((root) => {
        try { return [...root.querySelectorAll(selector)]; } catch { return []; }
      }).filter(visible);
      const day = expected.date.slice(8, 10);
      const dayTarget = scoped(".ant-picker-cell-in-view,td")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), title: clean(el.getAttribute("title") || el.getAttribute("aria-label") || "") }))
        .find((item) => item.title.includes(expected.date) || item.text === String(Number(day)) || item.text === day);
      if (dayTarget) {
        actions.push({ clicked: "kuaishou_day", label: dayTarget.title || dayTarget.text, ok: click(dayTarget.el) });
        await sleep(200);
      }
      const [hourRaw, minuteRaw] = expected.time.split(":");
      for (const [kind, wanted] of [["hour", String(Number(hourRaw))], ["minute", minuteRaw]]) {
        const cells = scoped(".ant-picker-time-panel-cell-inner")
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), column: clean(el.closest(".ant-picker-time-panel-column")?.innerText || "") }));
        const target = cells.find((item) => item.text === wanted || item.text === wanted.padStart(2, "0"));
        if (target) {
          actions.push({ clicked: "kuaishou_" + kind, label: target.text, ok: click(target.el) });
          await sleep(200);
        }
      }
      const okButton = scoped(".ant-picker-ok button,button,[role=button]")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "确定" || /^OK$/i.test(item.text))
        .sort((left, right) => left.area - right.area)[0];
      if (okButton) {
        actions.push({ clicked: "kuaishou_picker_ok", label: okButton.text, ok: click(okButton.el) });
        await sleep(500);
      }
      const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 60),
      };
    })()`, 12000);
  }
  if (platform === "toutiao") {
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({
        display: schedule.display,
        date: schedule.display.slice(0, 10),
        dateLabel: `${schedule.display.slice(5, 7)}月${schedule.display.slice(8, 10)}日`,
        hour: String(Number(schedule.display.slice(11, 13))),
        minute: String(Number(schedule.display.slice(14, 16))),
        time: schedule.display.slice(11, 16),
      })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const actions = [];
      const dialogs = [...document.querySelectorAll(".Dialog-container,.m-xigua-dialog")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), z: Number(getComputedStyle(el).zIndex || 0), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .sort((left, right) => right.z - left.z || left.area - right.area);
      for (const dialog of dialogs) {
        if (/完成后无法继续编辑/.test(dialog.text)) {
          const confirm = [...dialog.el.querySelectorAll("button,[role=button],span,div")]
            .filter(visible)
            .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
            .filter((item) => item.text === "确定" || item.text === "确认")
            .sort((left, right) => left.area - right.area)[0];
          actions.push({ clicked: "toutiao_blocking_completion_confirm", ok: click(confirm?.el), dialog: dialog.text.slice(0, 80) });
          await sleep(600);
        } else if (/封面编辑/.test(dialog.text)) {
          const ok = [...dialog.el.querySelectorAll("button,[role=button],span,div")]
            .filter(visible)
            .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height, y: el.getBoundingClientRect().top }))
            .filter((item) => item.text === "确定")
            .sort((left, right) => left.area - right.area || right.y - left.y)[0];
          actions.push({ clicked: "toutiao_cover_editor_ok", ok: click(ok?.el), dialog: dialog.text.slice(0, 80) });
          await sleep(900);
        }
      }
      const openSchedule = async () => {
        let modal = [...document.querySelectorAll(".byte-modal-wrapper,[role=dialog]")]
          .filter(visible)
          .find((el) => /定时发布/.test(clean(el.innerText || el.textContent)));
        if (modal) return modal;
        const footerButton = [...document.querySelectorAll("button,[role=button],span,div")]
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), className: clean(typeof el.className === "string" ? el.className : ""), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height, y: el.getBoundingClientRect().top }))
          .filter((item) => item.text === "定时发布" && /action-footer-btn|timer|byte-btn/.test(item.className))
          .sort((left, right) => left.area - right.area || right.y - left.y)[0];
        actions.push({ clicked: "toutiao_schedule_footer_entry", ok: click(footerButton?.el), label: footerButton?.text || "" });
        await sleep(900);
        modal = [...document.querySelectorAll(".byte-modal-wrapper,[role=dialog]")]
          .filter(visible)
          .find((el) => /定时发布/.test(clean(el.innerText || el.textContent)));
        return modal;
      };
      const modal = await openSchedule();
      const selectOption = async (selector, wanted, label) => {
        if (!modal) {
          actions.push({ select: label, ok: false, reason: "missing_toutiao_schedule_modal" });
          return false;
        }
        const select = modal.querySelector(selector);
        actions.push({ clicked: label + "_select", ok: click(select), current: clean(select?.innerText || select?.textContent) });
        await sleep(500);
        const roots = [...document.querySelectorAll(".byte-select-popup,.byte-select-dropdown,.byte-select-option-list,[class*=select-popup],[class*=select-dropdown],[class*=select-option]")]
          .filter(visible);
        const options = roots.flatMap((root) => [...root.querySelectorAll("li,div,span,[role=option]")])
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
          .filter((item) => item.text && item.text.length <= 40)
          .sort((left, right) => left.area - right.area);
        const target = options.find((item) => item.text === wanted || item.text === wanted.padStart(2, "0") || item.text === String(Number(wanted)) || item.text.includes(wanted));
        actions.push({ clicked: label + "_option", wanted, ok: click(target?.el), candidates: options.slice(0, 30).map((item) => item.text) });
        await sleep(500);
        return Boolean(target);
      };
      await selectOption(".day-select,.day-select .byte-select-view", expected.dateLabel, "toutiao_day");
      await selectOption(".hour-select,.hour-select .byte-select-view", expected.hour, "toutiao_hour");
      await selectOption(".minute-select,.minute-select .byte-select-view", expected.minute, "toutiao_minute");
      const updatedModal = await openSchedule();
      const confirm = [...(updatedModal ? updatedModal.querySelectorAll("button,[role=button]") : [])]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "定时发布" || item.text === "确定")
        .sort((left, right) => left.area - right.area)[0];
      if (confirm) {
        actions.push({ clicked: "toutiao_timer_confirm", label: confirm.text, ok: click(confirm.el) });
        await sleep(1200);
      }
      const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)) || text.includes(expected.dateLabel) && text.includes(expected.hour) && text.includes(expected.minute),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|19:30|20:00|21:00|05月/.test(line)).slice(0, 80),
      };
    })()`, 45000);
  }
  return evaluateWithClient(client, `(async () => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
    const classifyInput = ${classifyCompositeScheduleInputHint.toString()};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const setValue = (el, value) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      const previous = clean(el.value || el.textContent || "");
      try {
        if (typeof el.select === "function") el.select();
        if (typeof el.setSelectionRange === "function") el.setSelectionRange(0, String(el.value || "").length);
      } catch {}
      try {
        if (typeof el.setRangeText === "function" && !el.disabled) {
          el.setRangeText(String(value), 0, String(el.value || "").length, "end");
        }
      } catch {}
      if (setter) setter.call(el, value);
      else el.value = value;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter", code: "Enter" }));
      el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter", code: "Enter" }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
      const current = clean(el.value || el.textContent || "");
      return Boolean(current && (current.includes(clean(value)) || clean(value).includes(current) || current !== previous));
    };
    const actions = [];
    const bodyBefore = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const textLikeInputTypes = new Set(["", "text", "search", "url", "tel", "email", "number", "date", "time", "datetime-local"]);
    if (platform === "x") {
      const scheduleButton = [...document.querySelectorAll('[data-testid="scheduleOption"], [aria-label*="Schedule" i], button')]
        .filter(visible)
        .find((el) => /schedule/i.test(clean([el.getAttribute("data-testid"), el.getAttribute("aria-label"), el.innerText, el.textContent].join(" "))));
      if (scheduleButton) {
        actions.push({ clicked: "x_schedule_button", ok: click(scheduleButton), label: clean(scheduleButton.getAttribute("aria-label") || scheduleButton.innerText || scheduleButton.textContent) });
        await sleep(900);
      }
    }
    const clickSemanticLabel = async (label) => {
      const target = [...document.querySelectorAll("button,[role=button],label,span,div")]
        .filter(visible)
        .map((el) => {
          const text = clean(el.innerText || el.textContent);
          const rect = el.getBoundingClientRect();
          const control = el.closest("label,[role=radio],[role=checkbox],[role=switch],[class*=radio],[class*=switch],[class*=schedule],[class*=time]") || el.parentElement || el;
          return { el, control, text, area: rect.width * rect.height };
        })
        .filter((item) => item.text === label || (item.text.includes(label) && item.text.length <= 120))
        .sort((left, right) => left.area - right.area)[0];
      if (target) {
        actions.push({ clicked: label, ok: click(target.control || target.el), label: target.text.slice(0, 80) });
        await sleep(600);
      }
    };
    for (const label of ["定时发布", "发布时间", "预约", "安排时间", "Schedule post"]) {
      await clickSemanticLabel(label);
    }
    const inputs = [...document.querySelectorAll("input,textarea")]
      .filter(visible)
      .filter((el) => {
        const tag = String(el.tagName || "").toLowerCase();
        if (tag === "textarea") return true;
        const type = String(el.getAttribute("type") || "").toLowerCase();
        return textLikeInputTypes.has(type);
      })
      .map((el) => ({
        el,
        tag: String(el.tagName || "").toLowerCase(),
        type: String(el.getAttribute("type") || "").toLowerCase(),
        text: clean([el.placeholder, el.getAttribute("aria-label"), el.value, el.closest("label")?.innerText, el.parentElement?.innerText].join(" ")),
        value: clean(el.value || el.textContent || ""),
      }));
    for (const item of inputs) {
      const mode = classifyInput(item.text, item.value);
      if (!mode) continue;
      const wanted = mode === "datetime" ? expected.display : mode === "date" ? expected.date : expected.time;
      actions.push({ set: mode, ok: setValue(item.el, wanted), hint: item.text.slice(0, 80), previous: item.value.slice(0, 80) });
    }
    const selects = [...document.querySelectorAll("select")].filter(visible);
    for (const select of selects) {
      const label = clean([select.getAttribute("aria-label"), select.name, select.id, select.parentElement?.innerText].join(" "));
      const options = [...select.options].map((option) => ({ value: option.value, text: clean(option.textContent) }));
      let chosen = "";
      if (/year|年/i.test(label)) chosen = options.find((option) => option.text.includes(expected.date.slice(0, 4)) || option.value.includes(expected.date.slice(0, 4)))?.value || "";
      else if (/month|月/i.test(label)) chosen = options.find((option) => /May|五月|5月|^5$/.test(option.text) || option.value === "5" || option.value === "4")?.value || "";
      else if (/day|日|天/i.test(label)) chosen = options.find((option) => option.text === String(Number(expected.date.slice(8, 10))) || option.value === String(Number(expected.date.slice(8, 10))) || option.text === expected.date.slice(8, 10))?.value || "";
      else if (/hour|时/i.test(label)) chosen = options.find((option) => option.text === expected.time.slice(0, 2) || option.text === String(Number(expected.time.slice(0, 2))) || option.value === expected.time.slice(0, 2) || option.value === String(Number(expected.time.slice(0, 2))))?.value || "";
      else if (/minute|分/i.test(label)) chosen = options.find((option) => option.text === expected.time.slice(3, 5) || option.value === expected.time.slice(3, 5))?.value || "";
      if (chosen !== "") {
        select.value = chosen;
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
        actions.push({ set_select: label.slice(0, 80), value: chosen });
        await sleep(200);
      }
    }
    const pickerRoots = [...document.querySelectorAll([
      ".ant-picker-dropdown",
      ".ant-picker-panel-container",
      ".ant-picker-datetime-panel",
      ".ant-picker-time-panel",
      "[class*=picker]",
      "[class*=calendar]",
      "[class*=date]",
      "[class*=time]",
      "[role=dialog]",
      "[class*=modal]",
      "[class*=popover]",
    ].join(","))].filter(visible);
    const queryPicker = (selector) => pickerRoots.flatMap((root) => {
      try { return [...root.querySelectorAll(selector)]; } catch { return []; }
    }).filter(visible);
    if (platform === "kuaishou") {
      const day = expected.date.slice(8, 10);
      const dayTarget = queryPicker(".ant-picker-cell-in-view, td, button, [role=button], div, span")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent || el.getAttribute("title") || el.getAttribute("aria-label")), title: clean(el.getAttribute("title") || el.getAttribute("aria-label") || ""), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.title.includes(expected.date) || item.text === String(Number(day)) || item.text === day)
        .sort((left, right) => left.area - right.area)[0];
      if (dayTarget) {
        actions.push({ clicked: "kuaishou_day", label: dayTarget.text || dayTarget.title, ok: click(dayTarget.el) });
        await sleep(250);
      }
    }
    const hour = String(Number(expected.time.slice(0, 2)));
    const minute = expected.time.slice(3, 5);
    const wantedTexts = [expected.date, expected.time, hour, expected.time.slice(0, 2), minute, "确定"];
    for (const wanted of wantedTexts) {
      const target = queryPicker("button,[role=button],li,span,div,td")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === wanted || (wanted.length >= 5 && item.text.includes(wanted)))
        .sort((left, right) => left.area - right.area)[0];
      if (target && target.area < 100000) {
        actions.push({ clicked: wanted, label: target.text.slice(0, 80), ok: click(target.el) });
        await sleep(350);
      }
    }
    const bodyAfter = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const postInputValues = [...document.querySelectorAll("input,textarea")]
      .filter(visible)
      .filter((el) => {
        const tag = String(el.tagName || "").toLowerCase();
        if (tag === "textarea") return true;
        const type = String(el.getAttribute("type") || "").toLowerCase();
        return textLikeInputTypes.has(type);
      })
      .map((el) => clean(el.value || el.textContent || ""))
      .filter(Boolean);
    const checkedScheduled = [...document.querySelectorAll("input[type=radio],input[type=checkbox],[role=radio],[role=checkbox],[role=switch]")]
      .filter(visible)
      .some((el) => {
        const checked =
          typeof el.checked === "boolean"
            ? Boolean(el.checked)
            : el.getAttribute("aria-checked") === "true";
        if (!checked) return false;
        const hint = clean([el.closest("label,[role=radio],[role=checkbox],[role=switch]")?.innerText, el.parentElement?.innerText].join(" "));
        return /定时发布|发布时间/.test(hint);
      });
    const valueHasExpectedDisplay = postInputValues.some((value) => value.includes(expected.display));
    const valueHasExpectedParts = postInputValues.some((value) => value.includes(expected.date) && value.includes(expected.time));
    return {
      set:
        bodyAfter.includes(expected.display)
        || (bodyAfter.includes(expected.date) && bodyAfter.includes(expected.time))
        || valueHasExpectedDisplay
        || valueHasExpectedParts
        || (platform === "douyin" && checkedScheduled && (valueHasExpectedDisplay || valueHasExpectedParts)),
      expected,
      body_before_had_schedule: bodyBefore.includes(expected.display) || bodyBefore.includes(expected.date),
      body_after_had_schedule: bodyAfter.includes(expected.display) || (bodyAfter.includes(expected.date) && bodyAfter.includes(expected.time)),
      actions: actions.slice(0, 40),
      input_values: postInputValues.slice(0, 40),
      checked_scheduled: checkedScheduled,
      relevant_text: bodyAfter.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 80),
    };
  })()`, 25000);
}

async function setPlatformRichText(client, platform, title, body) {
  const titleValue = String(title || "").trim();
  const bodyValue = String(body || "").trim();
  if (!titleValue && !bodyValue) return { filled: false, reason: "empty_value" };
  if (platform === "toutiao") {
    return evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify({ title: titleValue, body: bodyValue })};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const setValue = (el, value) => {
        if (!el || !value) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        el.focus();
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        return true;
      };
      const fieldInfo = (el) => {
        let parent = el.parentElement;
        const parts = [el.placeholder, el.getAttribute("aria-label"), el.value];
        for (let i = 0; i < 4 && parent; i += 1, parent = parent.parentElement) parts.push(parent.innerText || "");
        return clean(parts.join(" "));
      };
      const actions = [];
      const inputs = [...document.querySelectorAll("input[type=text],input:not([type])")].filter(visible).map((el) => ({ el, text: fieldInfo(el), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }));
      const titleTarget = inputs
        .filter((item) => /标题|1.?30|30/.test(item.text) && !/话题|标签/.test(item.text))
        .sort((left, right) => right.area - left.area)[0] || inputs.find((item) => /请输入/.test(item.text) && !/话题|标签/.test(item.text));
      if (titleTarget) actions.push({ field: "title", ok: setValue(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
      const textareas = [...document.querySelectorAll("textarea")].filter(visible).map((el) => ({ el, text: fieldInfo(el), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }));
      const bodyTarget = textareas.find((item) => /简介|视频简介|描述/.test(item.text)) || textareas.sort((left, right) => right.area - left.area)[0];
      if (bodyTarget) actions.push({ field: "body", ok: setValue(bodyTarget.el, expected.body), hint: bodyTarget.text.slice(0, 120) });
      const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
      return {
        filled: actions.some((item) => item.ok),
        actions,
        verified_body: !expected.body || text.includes(expected.body.slice(0, Math.min(20, expected.body.length))),
        verified_title: !expected.title || text.includes(expected.title),
        candidates: [...inputs, ...textareas].slice(0, 16).map((item) => ({ text: item.text.slice(0, 120), area: item.area, tag: item.el.tagName.toLowerCase() })),
      };
    })()`, 30000);
  }
  return evaluateWithClient(client, `(() => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ title: titleValue, body: bodyValue })};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const normalizeDraft = ${normalizeRichTextDraftValue.toString()};
    const draftMatches = ${richTextDraftValueMatches.toString()};
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const setEditable = (el, value) => {
      if (!el || !value) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
        try {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(el);
          selection.removeAllRanges();
          selection.addRange(range);
          document.execCommand("insertText", false, value);
        } catch {
          el.textContent = value;
        }
        if (!draftMatches(el.innerText || el.textContent, value)) {
          el.replaceChildren();
          for (const [index, line] of value.split(/\\n/).entries()) {
            if (index) el.appendChild(document.createElement("br"));
            el.appendChild(document.createTextNode(line));
          }
        }
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        if (!draftMatches(el.innerText || el.textContent, value)) {
          try {
            el.textContent = "";
            for (const [index, line] of value.split(/\\n/).entries()) {
              if (index) el.appendChild(document.createElement("br"));
              el.appendChild(document.createTextNode(line));
            }
            el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertReplacementText", data: value }));
          } catch {}
        }
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      }
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
      return el.isContentEditable || el.getAttribute("contenteditable") === "true"
        ? draftMatches(normalizeDraft(el.innerText || el.textContent), value)
        : true;
    };
    const editables = [...document.querySelectorAll("textarea,input[type=text],[contenteditable=true],div[role=textbox],div[data-testid=tweetTextarea_0]")]
      .filter(visible)
      .map((el) => ({
        el,
        text: clean([el.placeholder, el.getAttribute("aria-label"), el.getAttribute("data-testid"), el.value, el.innerText, el.closest("label")?.innerText, el.parentElement?.innerText].join(" ")),
        area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
      }))
      .filter((item) => item.area > 1000)
      .sort((left, right) => right.area - left.area);
    const actions = [];
    const bodyPatterns = platform === "x"
      ? [/tweetTextarea|Post text|What is happening|有什么新鲜事|发布/i]
      : platform === "youtube"
        ? [/向观看者介绍你的视频|describe your video|description|说明/i]
      : platform === "wechat-channels"
        ? [/视频描述|描述|话题|发表动态/i]
        : platform === "kuaishou"
          ? [/作品描述|描述|智能文案|话题/i]
          : platform === "xiaohongshu"
            ? [/正文|描述|话题|更多|1000|笔记/i]
            : [/简介|描述|说明|正文|视频简介/i];
    const titlePatterns = platform === "youtube"
      ? [/标题（必填）|添加一个可描述你视频的标题|add a title|title/i]
      : [/标题|title/i];
    const titleTarget = expected.title
      ? (
        platform === "youtube"
          ? editables.find((item) => titlePatterns.some((pattern) => pattern.test(item.text)))
          : editables.find((item) => titlePatterns.some((pattern) => pattern.test(item.text)) && item.el.tagName === "INPUT")
      )
        || (platform === "toutiao" ? editables.find((item) => item.el.tagName === "INPUT" && /1～30|1-30|30 个字符|标题/.test(item.text)) : null)
        || (platform === "xiaohongshu" ? editables.find((item) => item.el.tagName === "INPUT" && /标题|更多赞/.test(item.text)) : null)
      : null;
    if (titleTarget) actions.push({ field: "title", ok: setEditable(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
    const bodyCandidates = platform === "xiaohongshu"
      ? editables.filter((item) => item.el.tagName !== "INPUT" || item.el.isContentEditable || item.el.getAttribute("contenteditable") === "true")
      : editables;
    const bodyTarget =
      bodyCandidates.find((item) => bodyPatterns.some((pattern) => pattern.test(item.text))) ||
      bodyCandidates.find((item) => (
        item.el.isContentEditable
        || item.el.getAttribute("contenteditable") === "true"
        || item.el.tagName === "TEXTAREA"
      ) && !titlePatterns.some((pattern) => pattern.test(item.text))) ||
      bodyCandidates[0];
    if (bodyTarget) actions.push({ field: "body", ok: setEditable(bodyTarget.el, expected.body || expected.title), hint: bodyTarget.text.slice(0, 120), tag: bodyTarget.el.tagName.toLowerCase() });
    if (platform === "xiaohongshu" && titleTarget) actions.push({ field: "title_reassert", ok: setEditable(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
    const text = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    return {
      filled: actions.some((item) => item.ok),
      actions,
      verified_body: !expected.body || text.includes(expected.body.slice(0, Math.min(20, expected.body.length))),
      verified_title: !expected.title || text.includes(expected.title),
      candidates: editables.slice(0, 12).map((item) => ({ text: item.text.slice(0, 120), area: item.area, tag: item.el.tagName.toLowerCase() })),
    };
  })()`, 30000);
}

async function finalizeGenericCompositePublish(
  client,
  platform,
  content,
  integrity,
  prePublishVerification = {},
  recoveryOptions = {},
) {
  const finalizationInterruptions = [];
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const platformRoute = (integrity?.platform_extras?.route || {});
  const reportTaskProgress = typeof recoveryOptions.task_progress === "function"
    ? recoveryOptions.task_progress
    : null;
  if (integrity?.verification_state === "auth_required") {
    return {
      status: "needs_human",
      ..._build_publication_recovery_hint({
        platform,
        code: `${platform}_final_publish_route_auth_required`,
        reason: "复合收尾阶段检测到发布页登录状态异常。",
        route: platformRoute,
        visibleLines: integrity?.platform_extras ? [integrity.platform_extras.route?.url || ""] : [],
        actionHistory: [],
        forceRefresh: true,
        blockers: [{ code: `${platform}_final_publish_route_auth_required`, message: "请先处理账号会话，避免重复发布。", details: integrity?.verification_reason || "" }],
      }).recovery,
      error: {
        code: `${platform}_route_auth_required`,
        message: "复合适配器读回发布页时发现未登录状态，请确认账号会话。",
        details: { verification_state: integrity.verification_state, verification_reason: integrity.verification_reason, route_ready_state: integrity.route_ready_state || {} },
      },
    };
  }
  if (integrity?.verification_state === "not_ready") {
    return {
      status: "needs_human",
      ..._build_publication_recovery_hint({
        platform,
        code: `${platform}_final_publish_route_not_ready`,
        reason: "复合收尾阶段未确认到可编辑发布状态。",
        route: platformRoute,
        visibleLines: integrity?.platform_extras ? [integrity.platform_extras.route?.url || ""] : [],
        actionHistory: [],
        clearDraftContext: true,
        forceRefresh: true,
        blockers: [{ code: `${platform}_material_integrity_route_not_ready`, message: "发布页状态不稳定，建议清理草稿上下文并刷新发布页。", details: integrity?.verification_reason || "" }],
      }).recovery,
      error: {
        code: `${platform}_material_integrity_route_not_ready`,
        message: "复合适配器尚未确认到可编辑投稿/发布态，请先确认已进入正确发布页面。",
        details: { verification_state: integrity.verification_state, verification_reason: integrity.verification_reason, route_ready_state: integrity.route_ready_state || {} },
      },
    };
  }
  if (!LIVE_PUBLISH_ENABLED) {
    return {
      status: "needs_human",
      ..._build_publication_recovery_hint({
        platform,
        code: "live_publish_disabled",
        reason: "live publish 未开启。",
        route: platformRoute,
        actionHistory: finalizationInterruptions.slice(0, 20),
        clearDraftContext: false,
        forceRefresh: false,
        blockers: [{ code: "live_publish_disabled", message: "环境关闭 live publish，请先开启。", details: "建议仅测试预览时使用。"}],
      }).recovery,
      error: { code: "live_publish_disabled", message: "复合适配器已准备草稿，但 live publish 未开启。" },
    };
  }
  if (!integrity?.verified) {
    return {
      status: "needs_human",
      ..._build_publication_recovery_hint({
        platform,
        code: `${platform}_material_integrity_failed`,
        reason: "发布前物料读回校验失败。",
        route: platformRoute,
        actionHistory: finalizationInterruptions.slice(0, 20),
        clearDraftContext: true,
        forceRefresh: true,
        blockers: [{ code: `${platform}_material_integrity_failed`, message: `发布前读回失败：${(integrity?.failures || []).join(", ") || "unknown"}`, details: (integrity?.failures || []).join(", ") }],
      }).recovery,
      error: {
        code: `${platform}_material_integrity_failed`,
        message: `复合适配器发布前读回未通过：${(integrity?.failures || []).join(", ") || "unknown"}`,
        details: integrity || {},
      },
    };
  }
  if (prePublishVerification && prePublishVerification.verified === false) {
    const blockingReasons = Array.isArray(prePublishVerification.blocking_reasons)
      ? prePublishVerification.blocking_reasons.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    return {
      status: "needs_human",
      ..._build_publication_recovery_hint({
        platform,
        code: `${platform}_final_pre_publish_visual_verification_failed`,
        reason: "最终点击发布前的视觉确认未通过。",
        route: prePublishVerification.route || platformRoute,
        visibleLines: Array.isArray(prePublishVerification.visible_lines) ? prePublishVerification.visible_lines : [],
        actionHistory: finalizationInterruptions.slice(0, 20),
        clearDraftContext: true,
        forceRefresh: true,
        blockers: [{
          code: `${platform}_final_pre_publish_visual_verification_failed`,
          message: `最终点击发布前视觉确认未通过：${blockingReasons.join(",") || "unknown"}`,
          details: blockingReasons.join(","),
        }],
      }).recovery,
      error: {
        code: `${platform}_final_pre_publish_visual_verification_failed`,
        message: `最终点击发布前视觉确认未通过：${blockingReasons.join(",") || "unknown"}`,
        details: prePublishVerification,
      },
    };
  }
  const publishTexts = platform === "youtube"
    ? (scheduled ? ["安排时间", "预约", "Schedule"] : ["发布", "Publish"])
    : platform === "x"
      ? (scheduled ? ["Schedule", "Confirm", "发布", "Post"] : ["发布", "Post"])
      : platform === "wechat-channels"
        ? (scheduled ? ["定时发表", "发表", "确认"] : ["发表", "确认"])
    : scheduled
      ? ["定时发布", "预约发布", "发布"]
      : ["发布", "发表", "提交"];
  const click = await clickPlatformFinalPublish(client, platform, publishTexts);
  await sleep(click.clicked ? 3200 : 1200);
  const secondConfirm = click.clicked
    ? await clickVisibleDialogConfirm(client, ["确认发布", "确认投稿", "确定发布", "继续发布", "确定", "确认", "发布", "提交"])
    : { clicked: false };
  if (secondConfirm.clicked) await sleep(3200);
  if (click.clicked) {
    finalizationInterruptions.push(...(await dismissCompositeFinalizeInterruptions(client, platform)));
    await sleep(1200);
  }
  const waitForPublishConfirmation = _coerceRecoveryBool(
    recoveryOptions.wait_for_publish_confirmation,
    true,
  );
  const captureResponseTimeoutMs = _coerceRecoveryTimeoutMs(
    recoveryOptions.capture_response_timeout_ms,
    65000,
  );
  const receipt = click.clicked && waitForPublishConfirmation
    ? await waitForCompositePublishReceipt(
      client,
      platform,
      content,
      captureResponseTimeoutMs,
      finalizationInterruptions,
      reportTaskProgress,
      { task_created_at: String(recoveryOptions?.task_created_at || "").trim() },
    )
    : { after: await readCompositeMaterialIntegrity(client, platform, content), receiptLike: false, waited_ms: 0 };
  const after = receipt.after;
  const receiptLike = receipt.receiptLike;
  return {
    status: click.clicked && receiptLike ? (scheduled ? "scheduled_pending" : "published") : "needs_human",
    result: {
      final_publish: {
        platform,
        scheduled,
        task_created_at: String(recoveryOptions?.task_created_at || "").trim(),
        click,
        second_confirm: secondConfirm,
        receipt_wait: receipt.waited_ms,
        receipt_like: receiptLike,
        post_click_integrity: after,
        finalization_interruptions: receipt.interruptions || finalizationInterruptions,
      },
    },
    ...(click.clicked && receiptLike
      ? { error: null }
      : {
          ..._build_publication_recovery_hint({
            platform,
            code: `${platform}_final_publish_unconfirmed`,
            reason: "未读到可靠发布回执。",
            route: {
              url: after?.platform_extras?.route?.url || "",
              title: after?.platform_extras?.route?.title || "",
            },
            visibleLines: after?.platform_extras?.relevant_lines || [],
            actionHistory: finalizationInterruptions,
            clearDraftContext: true,
            forceRefresh: true,
            duplicateDetected: Boolean(receipt?.duplicate_detected || false),
            duplicateMarker: receipt?.duplicate_detected ? receipt.duplicate_marker || "duplicate_publish_signal" : "",
            blockers: [{ code: `${platform}_final_publish_unconfirmed`, message: "已尝试发布但未读到可靠成功回执。", details: `duplicate=${Boolean(receipt?.duplicate_detected)}` }],
          }).recovery,
          error: { code: `${platform}_final_publish_unconfirmed`, message: "已由复合适配器处理最终发布，但没有读到可靠成功回执。", details: { click, second_confirm: secondConfirm, after } },
        }),
  };
}

async function runCompositePhase(platform, phase, fn) {
  try {
    return await fn();
  } catch (error) {
    error.publicationPlatform = platform;
    error.publicationPhase = phase;
    error.message = `${platform}:${phase}: ${error.message}`;
    throw error;
  }
}

async function waitForCompositePublishReceipt(client, platform, content, timeoutMs = 60000, finalizationInterruptions = [], onProgress = null, receiptBindingContext = {}) {
  const startedAt = Date.now();
  let after = null;
  let receiptLike = false;
  let duplicateDetected = false;
  let duplicateMarker = "";
  while (Date.now() - startedAt < timeoutMs) {
    const interruptions = await dismissCompositeFinalizeInterruptions(client, platform);
    if (interruptions.length) finalizationInterruptions.push(...interruptions);
    after = await readCompositeMaterialIntegrity(client, platform, content);
    const receiptText = (after.platform_extras?.relevant_lines || []).join(" ");
    const route = String(after.platform_extras?.route?.url || "");
    const normalizedBodyText = String(content.body || "").replace(/\s+/g, " ").trim();
    const xBodyMarker = normalizedBodyText ? normalizedBodyText.slice(0, 80) : "";
    const hasXBodyMarkerInReceipt = xBodyMarker ? receiptText.includes(xBodyMarker) : false;
    const xHasDuplicateSignal = /whoops!?\s*you\s+already\s+said\s+that|你已发布过|你已经发布过|重复发布|重复发送|already\s+posted|duplicate/i.test(receiptText);
    const hasGenericDuplicateSignal = /重复发布|重复发送|重复帖子|重复提交|already\s+posted|duplicate\s+post|duplicate/i.test(receiptText);
    duplicateDetected = xHasDuplicateSignal || hasGenericDuplicateSignal;
    if (duplicateDetected) duplicateMarker = receiptText.includes("你已发布过") ? "你已发布过" : "duplicate_publish_signal";
    const toutiaoRouteDone = (() => {
      const routeText = String(route || "").toLowerCase();
      const toutiaoBase = routeText.split("mp.toutiao.com/profile_v4/")[1] || "";
      const toutiaoSuffix = String(toutiaoBase || "").replace(/#.*/, "");
      return toutiaoSuffix.startsWith("xigua/") && /^(publish|content|manage|history|work|video|articles|center|post|publish-video|publish-list)\b/.test(toutiaoSuffix);
    })();
    receiptLike = platform === "youtube"
      ? Boolean(after.platform_extras?.youtube_link || after.platform_extras?.youtube_scheduled)
      : platform === "x"
        ? (
            /\/i\/graduated-access/i.test(String(after.platform_extras?.route?.url || "")) ||
            /Your post was sent|Post sent|已发布|发布成功|已发送|发布完成|发布后|Publish complete/i.test(receiptText) ||
            ((/https?:\/\/(?:www\.)?(?:x|twitter)\.com\/(?!compose\b)[^\\s/]+/i.test(String(after.platform_extras?.route?.url || "")) &&
              !/\/compose/i.test(String(after.platform_extras?.route?.url || "")) &&
              (after.platform_extras?.x_composer_controls_count || 0) === 0 &&
              !xHasDuplicateSignal &&
              hasXBodyMarkerInReceipt) ||
            (/https?:\/\/(?:www\.)?(?:x|twitter)\.com\/home/i.test(String(after.platform_extras?.route?.url || "")) &&
              (after.platform_extras?.x_composer_controls_count || 0) === 0 &&
              !xHasDuplicateSignal &&
              hasXBodyMarkerInReceipt))
          )
      : platform === "kuaishou"
        ? /发布成功|审核中|已发布|定时发布成功|已预约|预约成功|提交成功|等待审核|已进入审核/.test(receiptText) || (/作品管理/.test(receiptText) && !/发布视频/.test(receiptText))
      : platform === "toutiao"
          ? ( /发布成功|审核中|已发布|定时发布成功|已预约|预约成功|提交成功|作品管理|发布管理|等待审核|已进入审核/.test(receiptText) &&
              !/选择合集|待发布|发布视频|存草稿/.test(receiptText) )
            || (toutiaoRouteDone && /作品管理|发布管理|已进入审核|等待审核|发布成功|已发布|定时发布成功|审核中/.test(receiptText))
            || (/发布.*完成/.test(receiptText))
            || ( /发布视频/.test(receiptText) &&
              !/\/mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/.test(String(after.platform_extras?.route?.url || "")) )
          : /发布成功|审核中|已发布|定时发布成功|已预约|预约成功|提交成功|作品管理|发布管理|等待审核|已进入审核/.test(receiptText);
    if (typeof onProgress === "function" && after) {
      const routeState = after.platform_extras?.route || {};
      const finalPublish = {
        platform,
        scheduled: Boolean(String(content.scheduled_publish_at || "").trim()),
        task_created_at: String(receiptBindingContext?.task_created_at || "").trim(),
        receipt_wait: Date.now() - startedAt,
        receipt_like: receiptLike,
        duplicate_detected: duplicateDetected,
        duplicate_marker: duplicateMarker,
        post_click_integrity: after,
        finalization_interruptions: finalizationInterruptions,
      };
      const publicationAudit = buildCompositePublicationAudit(platform, content, after, finalPublish, routeState);
      onProgress({
        phase: "publish_receipt_poll",
        route: {
          url: String(routeState.url || ""),
          title: String(routeState.title || ""),
          path: String(routeState.path || ""),
        },
        final_publish: finalPublish,
        publication_audit: publicationAudit,
        publication_field_snapshot: buildPublicationFieldSnapshotFromAudit(
          platform,
          content,
          publicationAudit,
          routeState,
        ),
        material_integrity: after,
        visible_lines: after.platform_extras?.relevant_lines || [],
      });
    }
    if (receiptLike) break;
    const confirm =
      platform === "toutiao"
        ? { clicked: false, reason: "skip_toutiao_dialog_confirm_in_favor_of_composite_blocker" }
        : await clickVisibleDialogConfirm(client, ["确认发布", "确认投稿", "确定发布", "继续发布", "确定", "确认", "发布", "提交"]);
    if (confirm.clicked) await sleep(3200);
    else await sleep(2500);
  }
  return {
    after,
    receiptLike,
    task_created_at: String(receiptBindingContext?.task_created_at || "").trim(),
    duplicate_detected: duplicateDetected,
    duplicate_marker: duplicateMarker,
    waited_ms: Date.now() - startedAt,
    interruptions: finalizationInterruptions,
  };
}

async function runCompositePlatformAdapter(
  client,
  tab,
  platform,
  content,
  inheritedActions = [],
  recoveryOptions = {},
) {
  const actions = [...inheritedActions];
  const reportTaskProgress = typeof recoveryOptions.task_progress === "function"
    ? recoveryOptions.task_progress
    : null;
  const stopBeforeFinalPublish = Boolean(recoveryOptions.stop_before_final_publish);
  const prepublishOnlyCurrentPage = Boolean(recoveryOptions.prepublish_only_current_page);
  const prepareOnlyCurrentPage = Boolean(recoveryOptions.prepare_only_current_page);
  const framework = PLATFORM_COMPOSITE_FRAMEWORKS[platform] || (COMPOSITE_PUBLISH_PLATFORMS.has(platform) ? null : { id: "generic_composite_fallback_v1", prepare: prepareGenericCompositeDraft });
  if (!framework) {
    return {
      status: "needs_human",
      result: {
        platform,
        ..._build_publication_recovery_hint({
          platform,
          code: "dedicated_composite_framework_missing",
          reason: "复合适配器未接入该平台的专用框架。",
          route: { url: tab.url || "", title: tab.title || "" },
          actionHistory: actions,
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: "dedicated_composite_framework_missing", message: "请先补齐专用复合框架后再试。", details: "建议先清理草稿上下文再重试。" }],
        }).recovery,
        composite_framework: {
          enabled: true,
          platform,
          framework_id: "",
          dedicated_platform_framework: false,
          legacy_lightweight_script_used: false,
        },
      },
      error: {
        code: "dedicated_composite_framework_missing",
        message: `${platform} 属于全平台发布链路，但没有注册专用复合框架，已停止以避免退回旧轻量脚本。`,
      },
    };
  }
  const usedFallbackFramework = framework.id === "generic_composite_fallback_v1";
  const preparedDraftActions = await runCompositePhase(
    platform,
    `prepare_${framework.id}`,
    () => framework.prepare(client, platform, content),
  );
  actions.push(...(Array.isArray(preparedDraftActions) ? preparedDraftActions : []));
  const uploadReadinessBlocker = Array.isArray(preparedDraftActions)
    ? preparedDraftActions.find((item) => item?.kind === "composite_upload_readiness_blocked")
    : null;
  if (uploadReadinessBlocker) {
    const uploadSnapshot = await pageSnapshot(client, {
      captureVisualEvidence: true,
      platform,
      visualEvidencePhase: "prepare_upload_readiness_blocked",
    }).catch(() => null);
    if (
      stopBeforeFinalPublish
      && shouldTreatCompositeUploadReadinessBlockerAsPending(uploadReadinessBlocker)
    ) {
      const pendingUploadIntegrity = buildPendingUploadMaterialIntegrity(
        platform,
        {
          ready: false,
          failed: false,
          waited_ms: Number(uploadReadinessBlocker.ready_waited_ms || 0),
          last: {
            busy: Boolean(uploadReadinessBlocker.upload_busy),
            mediaPresent: Boolean(uploadReadinessBlocker.media_present),
            uploadPromptOnly: Boolean(uploadReadinessBlocker.upload_prompt_only),
            fileInputCount: 0,
            lines: Array.isArray(uploadReadinessBlocker.line_samples) ? uploadReadinessBlocker.line_samples : [],
          },
        },
        {
          url: uploadSnapshot?.url || tab.url || "",
          title: uploadSnapshot?.title || tab.title || "",
        },
      );
      return {
        status: "processing",
        result: buildCompositeUploadPendingProcessingEnvelope({
          platform,
          route: {
            url: uploadSnapshot?.url || tab.url || "",
            title: uploadSnapshot?.title || tab.title || "",
          },
          actions,
          content,
          interruptions: [],
          materialIntegrity: pendingUploadIntegrity,
          code: `${platform}_pre_publish_upload_pending`,
          reason: "复合适配器已确认媒体正在上传，继续保留现场等待进入可编辑发布态。",
          blockerMessage: "复合适配器检测到上传进行中，已切换为等待态而不是失败态。",
          blockerDetails: JSON.stringify(uploadReadinessBlocker),
          prepublishOnlyCurrentPage,
          prepareOnlyCurrentPage,
          stopBeforeFinalPublish,
        }),
        error: null,
      };
    }
    const uploadReadinessDisposition = deriveCompositeUploadReadinessBlockerDisposition(
      platform,
      uploadReadinessBlocker,
      {
        stopBeforeFinalPublish,
        prepublishOnlyCurrentPage,
        prepareOnlyCurrentPage,
      },
    );
    return {
      status: "needs_human",
      result: {
        platform,
        route: {
          url: uploadSnapshot?.url || tab.url || "",
          title: uploadSnapshot?.title || tab.title || "",
        },
        ..._build_publication_recovery_hint({
          platform,
          code: uploadReadinessDisposition.code,
          reason: uploadReadinessDisposition.message,
          route: {
            url: uploadSnapshot?.url || tab.url || "",
            title: uploadSnapshot?.title || tab.title || "",
          },
          actionHistory: actions,
          visibleLines: (uploadSnapshot?.lines || []).slice(0, 120),
          clearDraftContext: uploadReadinessDisposition.clear_draft_context,
          forceRefresh: uploadReadinessDisposition.force_publish_page_refresh,
          blockers: [{
            code: uploadReadinessDisposition.code,
            message: uploadReadinessDisposition.message,
            details: JSON.stringify(uploadReadinessDisposition.blocker_details),
          }],
          recoveryOverrides: uploadReadinessDisposition.recovery_overrides,
        }).recovery,
        composite_framework: {
          enabled: true,
          platform,
          framework_id: framework.id,
          dedicated_platform_framework: !usedFallbackFramework,
          legacy_lightweight_script_used: false,
          material_integrity: null,
        },
        actions,
      },
      error: {
        code: uploadReadinessDisposition.code,
        message: uploadReadinessDisposition.message,
        details: uploadReadinessDisposition.error_details,
      },
    };
  }
  if (!Array.isArray(preparedDraftActions)) {
    throw new TypeError("composite_prepare_actions_invalid");
  }
  await sleep(1200);
  const integrity = await runCompositePhase(platform, "pre_publish_material_integrity", () => readCompositeMaterialIntegrity(client, platform, content));
  reportTaskProgress({
    phase: "pre_publish_material_integrity",
    route: {
      url: String(tab.url || ""),
      title: String(tab.title || ""),
      path: "",
    },
    material_integrity: integrity,
    visible_lines: integrity?.platform_extras?.relevant_lines || [],
  });
  if (integrity?.verification_state === "auth_required") {
    return {
      status: "needs_human",
      result: {
        platform,
        route: { url: tab.url || "", title: tab.title || "" },
        ..._build_publication_recovery_hint({
          platform,
          code: `${platform}_route_auth_required`,
          reason: "复合适配器检测到发布页认证状态异常。",
          route: { url: tab.url || "", title: tab.title || "" },
          actionHistory: actions,
          visibleLines: (integrity.platform_extras?.relevant_lines || []).concat(integrity.platform_extras?.toast_lines || []),
          forceRefresh: true,
          blockers: [{ code: `${platform}_route_auth_required`, message: "发布页未登录或会话失效，请确认账号会话。", details: integrity.verification_reason || "" }],
        }).recovery,
        composite_framework: {
          enabled: true,
          platform,
          framework_id: framework.id,
          dedicated_platform_framework: !usedFallbackFramework,
          legacy_lightweight_script_used: false,
          material_integrity: integrity,
        },
        actions,
      },
      error: {
        code: `${platform}_route_auth_required`,
        message: "复合适配器已检测到发布页未登录，请先处理账号会话。",
        details: { verification_state: integrity.verification_state, verification_reason: integrity.verification_reason, route_ready_state: integrity.route_ready_state || {} },
      },
    };
  }
  if (integrity?.verification_state === "not_ready") {
    return {
      status: "needs_human",
      result: {
        platform,
        route: { url: tab.url || "", title: tab.title || "" },
        ..._build_publication_recovery_hint({
          platform,
          code: `${platform}_material_integrity_route_not_ready`,
          reason: "复合适配器未确认到可编辑发布态。",
          route: { url: tab.url || "", title: tab.title || "" },
          actionHistory: actions,
          visibleLines: (integrity.platform_extras?.relevant_lines || []).concat(integrity.platform_extras?.toast_lines || []),
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: `${platform}_material_integrity_route_not_ready`, message: "发布路由未准备好，建议清理草稿并刷新发布页。", details: integrity.verification_reason || "" }],
        }).recovery,
        composite_framework: {
          enabled: true,
          platform,
          framework_id: framework.id,
          dedicated_platform_framework: !usedFallbackFramework,
          legacy_lightweight_script_used: false,
          material_integrity: integrity,
        },
        actions,
      },
      error: {
        code: `${platform}_material_integrity_route_not_ready`,
        message: "复合适配器未确认到可编辑发布态，已中止自动发布以避免错配页面。",
        details: { verification_state: integrity.verification_state, verification_reason: integrity.verification_reason, route_ready_state: integrity.route_ready_state || {} },
      },
    };
  }
  const snapshot = await runCompositePhase(
    platform,
    "pre_publish_page_snapshot",
    () => pageSnapshot(client, {
      captureVisualEvidence: true,
      platform,
      visualEvidencePhase: "pre_publish_page_snapshot",
    }),
  );
  const currentRoute = { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" };
  let effectiveIntegrity = integrity;
  let effectiveSnapshot = snapshot;
  let effectiveRoute = currentRoute;
  let effectiveAudit = buildCompositePublicationAudit(platform, content, effectiveIntegrity, {}, effectiveRoute);
  let effectiveFieldSnapshot = buildPublicationFieldSnapshotFromAudit(
    platform,
    content,
    effectiveAudit,
    effectiveRoute,
    { repair_actions: [] },
  );
  const prePublishRepairPlan = deriveCompositePrePublishRepairPlan(effectiveAudit, effectiveIntegrity);
  let prePublishRepairAttempt = null;
  if (prePublishRepairPlan.shouldRepair) {
    reportTaskProgress({
      phase: "pre_publish_repair_attempt",
      route: {
        url: String(effectiveRoute.url || ""),
        title: String(effectiveRoute.title || ""),
        path: "",
      },
      material_integrity: effectiveIntegrity,
      publication_audit: effectiveAudit,
      publication_field_snapshot: effectiveFieldSnapshot,
      visual_evidence: effectiveSnapshot?.visual_evidence || undefined,
      visible_lines: (effectiveSnapshot.lines || []).slice(0, 120),
    });
    const repairExecutor = typeof framework.repair === "function"
      ? () => framework.repair(client, platform, content, prePublishRepairPlan.repairable_fields)
      : () => framework.prepare(client, platform, content);
    const repairActions = await runCompositePhase(
      platform,
      `repair_pre_publish_${framework.id}`,
      repairExecutor,
    );
    if (!Array.isArray(repairActions)) {
      throw new TypeError("composite_repair_actions_invalid");
    }
    actions.push(...repairActions);
    await sleep(1200);
    effectiveIntegrity = await runCompositePhase(platform, "pre_publish_material_integrity_reverify", () => readCompositeMaterialIntegrity(client, platform, content));
    effectiveSnapshot = await runCompositePhase(
      platform,
      "pre_publish_page_snapshot_reverify",
      () => pageSnapshot(client, {
        captureVisualEvidence: true,
        platform,
        visualEvidencePhase: "pre_publish_page_snapshot_reverify",
      }),
    );
    effectiveRoute = { url: effectiveSnapshot.url || tab.url || "", title: effectiveSnapshot.title || tab.title || "" };
    effectiveAudit = buildCompositePublicationAudit(platform, content, effectiveIntegrity, {}, effectiveRoute);
    effectiveFieldSnapshot = buildPublicationFieldSnapshotFromAudit(
      platform,
      content,
      effectiveAudit,
      effectiveRoute,
      { repair_actions: repairActions },
    );
    prePublishRepairAttempt = {
      attempted: true,
      repairable_fields: prePublishRepairPlan.repairable_fields,
      before_required_unverified: prePublishRepairPlan.required_unverified,
      after_required_unverified: Array.isArray(effectiveAudit?.required_unverified) ? effectiveAudit.required_unverified : [],
      actions: repairActions,
    };
    reportTaskProgress({
      phase: "pre_publish_reverify",
      route: {
        url: String(effectiveRoute.url || ""),
        title: String(effectiveRoute.title || ""),
        path: "",
      },
      material_integrity: effectiveIntegrity,
      publication_audit: effectiveAudit,
      publication_field_snapshot: effectiveFieldSnapshot,
      visual_evidence: effectiveSnapshot?.visual_evidence || undefined,
      visible_lines: (effectiveSnapshot.lines || []).slice(0, 120),
    });
  }
  reportTaskProgress({
    phase: "pre_publish_ready",
    route: {
      url: String(effectiveRoute.url || ""),
      title: String(effectiveRoute.title || ""),
      path: "",
    },
    material_integrity: effectiveIntegrity,
    publication_audit: effectiveAudit,
    publication_field_snapshot: effectiveFieldSnapshot,
    visible_lines: (effectiveSnapshot.lines || []).slice(0, 120),
  });
  const result = {
    draft_url: effectiveSnapshot.url || tab.url || "",
    route: effectiveRoute,
    composite_framework: {
      enabled: true,
      platform,
      framework_id: framework.id,
      dedicated_platform_framework: !usedFallbackFramework,
      legacy_lightweight_script_used: false,
      material_integrity: effectiveIntegrity,
    },
    publication_audit: effectiveAudit,
    publication_field_snapshot: effectiveFieldSnapshot,
    pre_publish_repair: prePublishRepairAttempt || undefined,
    actions: actions.slice(0, 120),
    visible_option_lines: (effectiveSnapshot.lines || [])
      .filter((line) => /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category|封面|缩略图/i.test(line))
      .slice(0, 160),
  };
  result.final_pre_publish_visual_verification = deriveCompositeFinalPrePublishVisualVerification(
    platform,
    content,
    effectiveIntegrity,
    effectiveAudit,
    effectiveFieldSnapshot,
    effectiveSnapshot,
  );
  const prePublishMissing = result.publication_audit?.required_unverified || [];
  if (prePublishMissing.length > 0) {
    const prePublishPending = deriveCompositePrePublishPendingState(
      result.publication_audit,
      effectiveIntegrity,
      prePublishRepairAttempt,
    );
    if (prePublishPending.wait_only) {
      const prePublishPendingCode = `${platform}_pre_publish_upload_pending`;
      reportTaskProgress({
        phase: "pre_publish_upload_pending",
        route: {
          url: String(effectiveRoute.url || ""),
          title: String(effectiveRoute.title || ""),
          path: "",
        },
        material_integrity: effectiveIntegrity,
        publication_audit: result.publication_audit,
        publication_field_snapshot: result.publication_field_snapshot,
        visible_lines: (effectiveSnapshot.lines || []).slice(0, 120),
      });
      return {
        status: "processing",
        result: _attach_publication_content_signature({
          ...result,
          final_publish: {
            ...(result.final_publish || {}),
            pre_publish_pending: true,
            wait_for_upload_ready: true,
            prepublish_only_current_page: Boolean(recoveryOptions.prepublish_only_current_page),
            prepare_only_current_page: Boolean(recoveryOptions.prepare_only_current_page),
            stop_before_final_publish: stopBeforeFinalPublish,
          },
          ..._build_publication_recovery_hint({
            platform,
            code: prePublishPendingCode,
            reason: "预发布字段已收敛，只剩上传完成前的等待态，继续自动等待后再验证。",
            route: effectiveRoute,
            actionHistory: actions,
            visibleLines: (effectiveSnapshot.lines || []).slice(0, 160),
            clearDraftContext: false,
            forceRefresh: true,
            blockers: [{
              code: prePublishPendingCode,
              message: `预发布仍需等待上传完成：${prePublishPending.remaining.join(",") || "upload_ready"}`,
              details: `pre_publish_pending=${prePublishPending.remaining.join(",")} | repair_attempted=${Boolean(prePublishRepairAttempt)}`,
            }],
          }).recovery,
        }, content),
        error: {
          code: prePublishPendingCode,
          message: `预发布等待上传完成：${prePublishPending.remaining.join(",") || "upload_ready"}`,
          details: result.publication_audit || {},
        },
      };
    }
    const prePublishCode = prePublishMissing.includes("content_plan_match")
      ? `${platform}_pre_publish_content_plan_mismatch`
      : `${platform}_pre_publish_material_integrity_failed`;
    const prePublishDetailCode = "pre_publish_field_readback";
    const prePublishReadbackFields = prePublishMissing.filter((item) => String(item || "").trim());
    const prePublishRecovery = deriveCompositePrePublishFailureRecoveryPlan(
      result.publication_audit,
      effectiveIntegrity,
      prePublishRepairAttempt,
    );
    return {
      status: "needs_human",
      result,
      ..._build_publication_recovery_hint({
        platform,
        code: prePublishCode,
        reason: "预发布字段读回未通过：字段回填/可用素材存在空值或不一致。",
        route: effectiveRoute,
        actionHistory: actions,
        visibleLines: (effectiveSnapshot.lines || []).slice(0, 160),
        clearDraftContext: prePublishRecovery.clear_draft_context,
        forceRefresh: prePublishRecovery.force_publish_page_refresh,
        blockers: [{
          code: `${platform}_${prePublishDetailCode}`,
          message: `预发布字段读回未通过：${prePublishReadbackFields.join(",") || "unknown"}`,
          details: `${prePublishCode}:${(result.publication_audit?.required_unverified || []).join(",")} | failures=${(effectiveIntegrity.failures || []).join(",")} | repair_attempted=${Boolean(prePublishRepairAttempt)} | clear_draft=${Boolean(prePublishRecovery.clear_draft_context)}`,
        }],
      }).recovery,
      error: {
        code: prePublishCode,
        message: `预发布复核未通过：${(result.publication_audit?.required_unverified || []).join(",") || "unknown"}`,
        details: result.publication_audit || {},
      },
    };
  }
  if (result.final_pre_publish_visual_verification?.verified === false) {
    const verificationBlockingReasons = Array.isArray(result.final_pre_publish_visual_verification?.blocking_reasons)
      ? result.final_pre_publish_visual_verification.blocking_reasons.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
    return {
      status: "needs_human",
      result,
      ..._build_publication_recovery_hint({
        platform,
        code: `${platform}_final_pre_publish_visual_verification_failed`,
        reason: "最终点击发布前的视觉确认未通过。",
        route: result.final_pre_publish_visual_verification?.route || effectiveRoute,
        actionHistory: actions,
        visibleLines: Array.isArray(result.final_pre_publish_visual_verification?.visible_lines)
          ? result.final_pre_publish_visual_verification.visible_lines
          : (effectiveSnapshot.lines || []).slice(0, 160),
        clearDraftContext: true,
        forceRefresh: true,
        blockers: [{
          code: `${platform}_final_pre_publish_visual_verification_failed`,
          message: `最终点击发布前视觉确认未通过：${verificationBlockingReasons.join(",") || "unknown"}`,
          details: verificationBlockingReasons.join(","),
        }],
      }).recovery,
      error: {
        code: `${platform}_final_pre_publish_visual_verification_failed`,
        message: `最终点击发布前视觉确认未通过：${verificationBlockingReasons.join(",") || "unknown"}`,
        details: result.final_pre_publish_visual_verification,
      },
    };
  }

  if (stopBeforeFinalPublish) {
    reportTaskProgress({
      phase: "pre_publish_verified_stop_before_final_publish",
      route: {
        url: String(effectiveRoute.url || ""),
        title: String(effectiveRoute.title || ""),
        path: "",
      },
      material_integrity: effectiveIntegrity,
      publication_audit: result.publication_audit,
      publication_field_snapshot: result.publication_field_snapshot,
      final_pre_publish_visual_verification: result.final_pre_publish_visual_verification,
      visible_lines: (effectiveSnapshot.lines || []).slice(0, 120),
    });
    return {
      status: "verified",
      result: _attach_publication_content_signature({
        ...result,
        final_publish: {
          ...(result.final_publish || {}),
          prepublish_only_current_page: Boolean(recoveryOptions.prepublish_only_current_page),
          prepare_only_current_page: Boolean(recoveryOptions.prepare_only_current_page),
          stop_before_final_publish: true,
        },
      }, content),
      error: null,
    };
  }

  if (platform === "youtube") {
    const youtubeVideoId = String(snapshot.url || "").match(/\/video\/([A-Za-z0-9_-]+)\/edit/)?.[1] || "";
    const youtubeReceipt = integrity.platform_extras?.youtube_link || (youtubeVideoId ? `https://youtu.be/${youtubeVideoId}` : "");
    if (youtubeReceipt && (integrity.platform_extras?.youtube_scheduled || /已排定时间|公开范围/.test(result.visible_option_lines.join(" ")))) {
      const youtubeFinalPublish = {
        platform,
        scheduled: true,
        receipt_like: true,
        external_url: youtubeReceipt,
        material_integrity_complete: integrity.verified,
      };
      result.material_integrity = normalizeCompositePostPublishIntegrity(platform, integrity, integrity, youtubeFinalPublish, content);
      const youtubeReceiptBinding = deriveYouTubeStudioReceiptBinding(result.material_integrity, youtubeFinalPublish);
      result.final_publish = {
        ...youtubeFinalPublish,
        ...youtubeReceiptBinding,
      };
      result.publication_audit = buildCompositePublicationAudit(platform, content, result.material_integrity, result.final_publish, result.route);
      result.publication_field_snapshot = buildPublicationFieldSnapshotFromAudit(
        platform,
        content,
        result.publication_audit,
        result.route,
      );
      if (!result.publication_audit.verified) {
        const scheduleMismatchCode = `${platform}_scheduled_receipt_content_plan_mismatch`;
        return {
          status: "needs_human",
          result,
          ..._build_publication_recovery_hint({
            platform,
            code: scheduleMismatchCode,
            reason: "YouTube 已读到预约回执但内容核验未通过。",
            route: result.route,
            actionHistory: actions,
            visibleLines: (result.publication_audit.required_unverified || []).slice(0, 12).map((item) => String(item)),
            clearDraftContext: true,
            forceRefresh: true,
            blockers: [{ code: scheduleMismatchCode, message: "预约路径读回显示回执，但内容与计划不一致。", details: String((result.publication_audit.required_unverified || []).join(",")) }],
          }).recovery,
          error: {
            code: scheduleMismatchCode,
            message: `YouTube 已读到预约回执，但发布内容核验未通过：${(result.publication_audit.required_unverified || []).join(",") || "unknown"}`,
            details: result.publication_audit,
          },
        };
      }
      return {
        status: "scheduled_pending",
        result,
        error: null,
      };
    }
  }

  if (integrity.platform_extras?.receipt_like && integrity.verified) {
    const genericFinalPublish = {
      platform,
      scheduled: Boolean(String(content.scheduled_publish_at || "").trim()),
      receipt_like: true,
      material_integrity_complete: true,
      receipt_route: integrity.platform_extras.route || {},
    };
    result.material_integrity = platform === "youtube"
      ? normalizeCompositePostPublishIntegrity(platform, integrity, integrity, genericFinalPublish, content)
      : integrity;
    const receiptBinding = platform === "youtube"
      ? deriveYouTubeStudioReceiptBinding(result.material_integrity, genericFinalPublish)
      : {};
    result.final_publish = {
      ...genericFinalPublish,
      ...receiptBinding,
    };
    result.publication_audit = buildCompositePublicationAudit(platform, content, result.material_integrity, result.final_publish, result.route);
    result.publication_field_snapshot = buildPublicationFieldSnapshotFromAudit(
      platform,
      content,
      result.publication_audit,
      result.route,
    );
    if (!result.publication_audit.verified) {
      const receiptMismatchCode = `${platform}_receipt_content_plan_mismatch`;
      return {
        status: "needs_human",
        result,
        ..._build_publication_recovery_hint({
          platform,
          code: receiptMismatchCode,
          reason: "已读到发布回执但内容核验未通过。",
          route: result.route,
          actionHistory: actions,
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: receiptMismatchCode, message: "receipt_like 分支发布后内容与计划核验未通过。", details: String((result.publication_audit.required_unverified || []).join(",")) }],
        }).recovery,
        error: {
          code: receiptMismatchCode,
          message: `复合适配器读到回执后核验未通过：${(result.publication_audit.required_unverified || []).join(",") || "unknown"}`,
          details: result.publication_audit,
        },
      };
    }
    return {
      status: String(content.scheduled_publish_at || "").trim() ? "scheduled_pending" : "published",
      result,
      error: null,
    };
  }

  const finalOutcome = await runCompositePhase(
    platform,
    "finalize_generic_composite_publish",
    () => finalizeGenericCompositePublish(
      client,
      platform,
      content,
      effectiveIntegrity,
      result.final_pre_publish_visual_verification,
      recoveryOptions,
    ),
  );
  result.final_publish = finalOutcome.result?.final_publish || {};
  const finalIntegrity = await readCompositeMaterialIntegrity(client, platform, content);
  const normalizedFinalIntegrity = normalizeCompositePostPublishIntegrity(
    platform,
    finalIntegrity,
    integrity,
    result.final_publish,
    content,
  );
  result.publication_audit = buildCompositePublicationAudit(platform, content, normalizedFinalIntegrity, result.final_publish, result.route);
  result.publication_field_snapshot = buildPublicationFieldSnapshotFromAudit(
    platform,
    content,
    result.publication_audit,
    result.route,
  );
  if (["published", "scheduled_pending"].includes(finalOutcome.status) && !(result.publication_audit.verified)) {
    const finalMismatchCode = `${platform}_post_publish_content_plan_mismatch`;
    return {
      status: "needs_human",
      result,
      ..._build_publication_recovery_hint({
        platform,
        code: finalMismatchCode,
        reason: "最终发布后读回内容与发布计划不一致。",
        route: (normalizedFinalIntegrity?.platform_extras?.route || result.route),
        actionHistory: actions,
        visibleLines: (normalizedFinalIntegrity?.platform_extras?.relevant_lines || []),
        clearDraftContext: true,
        forceRefresh: true,
        blockers: [{ code: finalMismatchCode, message: "发布成功路径后的内容核验未通过。", details: String((result.publication_audit.required_unverified || []).join(",")) }],
      }).recovery,
      error: {
        code: finalMismatchCode,
        message: `发布已完成/回执已识别，但内容核验未通过：${(result.publication_audit.required_unverified || []).join(",") || "unknown"}`,
        details: { finalOutcome: finalOutcome.error || null, final_integrity: normalizedFinalIntegrity, publication_audit: result.publication_audit },
      },
    };
  }
  return { status: finalOutcome.status, result, error: finalOutcome.error };
}

function inferBilibiliCategory(content) {
  const explicit = [
    content.category,
    content.category_name,
    content.category_path,
    content.section,
    content.section_name,
  ]
    .map((value) => {
      if (!value) return "";
      if (typeof value === "string") return value;
      if (typeof value === "object") return value.name || value.title || value.path || value.label || "";
      return "";
    })
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  if (explicit.some((value) => value.includes("户外潮流"))) return "户外潮流";

  const sample = [
    content.title,
    content.body,
    ...(content.hashtags || []),
    ...(content.structured_tags || []),
    content.collection?.name,
    content.collection_name,
  ]
    .map((value) => String(value || ""))
    .join(" ");
  const isEdcGear = /EDC|潮玩|桌搭|推牌|把玩|刀|手电|机能|户外|装备|随身/.test(sample);
  if (isEdcGear && (!explicit.length || explicit.some((value) => /生活兴趣|生活|科技|数码/.test(value)))) {
    return "户外潮流";
  }
  return explicit[0] || "";
}

async function setBilibiliDraftFields(client, content) {
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = Array.from(new Set([...(content.hashtags || []), ...(content.structured_tags || [])].map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 10);
  const collection = String(content.collection?.name || content.collection_name || "").trim();
  const scheduledPublishAt = String(content.scheduled_publish_at || "").trim();
  const schedule = parseChinaLocalSchedule(scheduledPublishAt);
  const category = inferBilibiliCategory(content);
  const declaration = String(extractCompositeDeclarationText(content) || compositePlatformDefaultDeclaration("bilibili")).trim()
    || compositePlatformDefaultDeclaration("bilibili");
  const expression = `(async () => {
    const expected = ${JSON.stringify({
  title,
  body,
  tags,
  collection,
  category,
  scheduledPublishAt,
  scheduledTimestamp: schedule.timestamp,
  scheduledDisplay: schedule.display,
  declaration,
})};
    const detectSignals = ${detectCompositePublicationSignals.toString()};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const setInputValue = (el, value) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
        const paragraph = document.createElement("p");
        paragraph.textContent = value;
        el.replaceChildren(paragraph);
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
      }
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      for (const type of ["change", "blur"]) el.dispatchEvent(new Event(type, { bubbles: true }));
      return true;
    };
    const actions = [];
    const titleInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /标题/.test(el.placeholder || ""));
    if (titleInput) actions.push({ field: "title", filled: setInputValue(titleInput, expected.title), actual: clean(titleInput.value) });

    const declarationInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /创作声明/.test(el.placeholder || ""));
    if (declarationInput) {
      actions.push({ field: "declaration", reset_before: clean(declarationInput.value) });
      if (clean(declarationInput.value) !== expected.declaration) {
        click(declarationInput.closest(".bcc-select") || declarationInput);
        await sleep(400);
        const option = [...document.querySelectorAll(".bcc-option, .option-hover-tips, .auth-content")]
          .filter(visible)
          .find((el) => clean(el.innerText || el.textContent) === expected.declaration);
        if (option) {
          click(option);
          await sleep(400);
        }
      }
      if (clean(declarationInput.value) !== expected.declaration) {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(declarationInput, expected.declaration);
        else declarationInput.value = expected.declaration;
        declarationInput.dispatchEvent(new Event("input", { bubbles: true }));
        declarationInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
      actions.push({ field: "declaration", expected: expected.declaration, actual: clean(declarationInput.value), selected: clean(declarationInput.value) === expected.declaration });
    }

    if (expected.category) {
      const categoryEl = document.querySelector(".video-human-type");
      const categoryVm = categoryEl?.__vue__;
      const before = {
        text: clean(categoryEl?.innerText || ""),
        value: categoryVm?.value,
        selected: categoryVm?._watchers?.[1]?.value || null,
      };
      const list = categoryVm?._watchers?.[0]?.value || [];
      const target = Array.isArray(list)
        ? list.find((item) => item && clean(item.name) === expected.category)
        : null;
      if (before.text.includes(expected.category) || clean(before.selected?.name || "") === expected.category) {
        // Already correct.
      } else if (categoryVm && target && typeof categoryVm.changeType === "function") {
        categoryVm.changeType(target);
        await sleep(500);
      } else {
        const categoryInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /分区|分类/.test(el.placeholder || ""));
        if (categoryInput) {
          click(categoryInput.closest(".bcc-select") || categoryInput);
          await sleep(400);
          const option = [...document.querySelectorAll(".bcc-option, .bcc-select-dropdown .option, [class*=option]")]
            .filter(visible)
            .find((el) => clean(el.innerText || el.textContent) === expected.category);
          if (option) {
            click(option);
            await sleep(400);
          }
        }
      }
      const after = {
        text: clean(categoryEl?.innerText || ""),
        value: categoryVm?.value,
        selected: categoryVm?._watchers?.[1]?.value || null,
      };
      actions.push({ field: "category", expected: expected.category, before, after, selected: after.text.includes(expected.category) || clean(after.selected?.name || "") === expected.category });
    }

    const description = [...document.querySelectorAll(".archive-info-editor .ql-editor[contenteditable=true], .archive-info-editor [contenteditable=true]")]
      .filter(visible)[0];
    if (description) {
      const beforeDescription = clean(description.innerText || description.textContent);
      const filled = beforeDescription === expected.body ? true : setInputValue(description, expected.body);
      actions.push({ field: "description", filled, actual: clean(description.innerText || description.textContent), skipped_because_already_correct: beforeDescription === expected.body });
    }

    const tagWrp = [...document.querySelectorAll(".tag-container")].find((el) => clean(el.innerText).includes("标签"));
    if (tagWrp) {
      for (const close of [...tagWrp.querySelectorAll(".label-item-v2-container .close")].filter(visible).slice(0, 10)) click(close);
      const tagInput = tagWrp.querySelector('input[placeholder*="Enter"], input[placeholder*="标签"], input.input-val');
      if (tagInput) {
        const currentTags = () => [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean);
        const commitTag = async (tag) => {
          setInputValue(tagInput, tag);
          await sleep(180);
          for (const type of ["keydown", "keypress", "keyup"]) {
            tagInput.dispatchEvent(new KeyboardEvent(type, { bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13 }));
          }
          await sleep(800);
          return currentTags().includes(tag);
        };
        if (expected.tags.every((tag) => currentTags().includes(tag))) {
          // Already correct.
        } else {
          for (const tag of expected.tags) {
            if (currentTags().includes(tag)) continue;
            let committed = false;
            for (let attempt = 0; attempt < 3 && !committed; attempt += 1) {
              committed = await commitTag(tag);
            }
          }
          await sleep(1000);
          for (const tag of expected.tags) {
            if (!currentTags().includes(tag)) {
              await commitTag(tag);
              await sleep(500);
            }
          }
        }
        if (!expected.tags.includes(clean(tagInput.value || ""))) setInputValue(tagInput, "");
      }
      const actualTags = [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean);
      actions.push({ field: "tags", expected: expected.tags, actual: actualTags });
    }

    if (expected.collection) {
      const collectionSelectCandidates = () => [...document.querySelectorAll(".video-season-select .season-select")]
        .filter(visible)
        .map((el) => ({
          el,
          text: clean(el.innerText || el.textContent),
          inDialog: Boolean(el.closest(".bcc-dialog, .bcc-dialog__wrap, .batch-add-season, .batch-fill")),
          inForm: Boolean(el.closest(".form, .form-item")),
        }));
      const collectionTextsBefore = collectionSelectCandidates().map((item) => item.text).filter(Boolean);
      const collectionSelect =
        collectionSelectCandidates().find((item) => item.text.includes(expected.collection))?.el ||
        collectionSelectCandidates().find((item) => item.inForm && !item.inDialog)?.el ||
        collectionSelectCandidates().find((item) => !item.inDialog)?.el ||
        collectionSelectCandidates()[0]?.el;
      const before = clean(collectionSelect?.innerText || "");
      if (collectionSelect && !collectionTextsBefore.some((text) => text.includes(expected.collection))) {
        click(collectionSelect);
        await sleep(600);
        const option = [...document.querySelectorAll(".bcc-option, .season-list .season-item, .video-season-select [class*=option], [class*=season] [class*=item]")]
          .filter(visible)
          .find((el) => clean(el.innerText || el.textContent).includes(expected.collection));
        if (option) {
          click(option);
          await sleep(500);
        }
      }
      const collectionTextsAfter = collectionSelectCandidates().map((item) => item.text).filter(Boolean);
      const selectedCollection = collectionTextsAfter.find((text) => text.includes(expected.collection)) || collectionTextsAfter.find((text) => !/请选择合集/.test(text)) || collectionTextsAfter[0] || "";
      actions.push({ field: "collection", expected: expected.collection, before, candidates_before: collectionTextsBefore, actual: selectedCollection, candidates_after: collectionTextsAfter, selected: selectedCollection.includes(expected.collection) });
    }

    if (expected.scheduledPublishAt) {
      const switchEl = document.querySelector(".time-switch-wrp .switch-container, .time-switch-wrp [class*=switch]");
      const before = clean(document.querySelector(".time-switch-wrp")?.innerText || "");
      const switchVm = document.querySelector(".time-switch-wrp .switch-container")?.__vue__;
      if (!before.includes(expected.scheduledDisplay)) {
        if (switchVm && !switchVm.active && typeof switchVm.handleSet === "function") switchVm.handleSet();
        else if (switchEl && !/\\d{4}|\\d{2}:\\d{2}/.test(before)) click(switchEl);
        await sleep(500);
        const timeVm = document.querySelector(".d-time-container")?.__vue__;
        if (timeVm && expected.scheduledTimestamp && typeof timeVm.setDTime === "function") {
          timeVm.setDTime(expected.scheduledTimestamp);
          await sleep(400);
        }
      }
      const after = clean(document.querySelector(".time-container")?.innerText || document.querySelector(".time-switch-wrp")?.innerText || "");
      actions.push({ field: "schedule", expected: expected.scheduledDisplay || expected.scheduledPublishAt, before, after, expanded: /\\d{4}|\\d{2}:\\d{2}/.test(after) });
    }

    const pageText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const pageLines = pageText.split(/[\\n\\r]+| {2,}/).map(clean).filter(Boolean);
    const signals = detectSignals("bilibili", pageText, pageLines);
    const actual = {
      title: clean(titleInput?.value || ""),
      declaration: clean(declarationInput?.value || ""),
      category: clean(document.querySelector(".video-human-type")?.innerText || ""),
      description: clean(description?.innerText || description?.textContent || ""),
      tags: tagWrp ? [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean) : [],
      collection: (() => {
        const texts = [...document.querySelectorAll(".video-season-select .season-select")]
          .filter(visible)
          .map((el) => clean(el.innerText || el.textContent))
          .filter(Boolean);
        return expected.collection && texts.some((text) => text.includes(expected.collection))
          ? expected.collection
          : (texts.find((text) => !/请选择合集/.test(text)) || texts[0] || "");
      })(),
      scheduleText: clean(document.querySelector(".time-container")?.innerText || document.querySelector(".time-switch-wrp")?.innerText || ""),
      blockers: signals.blockers,
      uploadState: { busy: signals.upload_busy, failed: signals.upload_failed, prompt_only: signals.upload_prompt_only },
    };
    const failures = [];
    if (expected.title && actual.title !== expected.title) failures.push("title");
    if (expected.declaration && actual.declaration !== expected.declaration) failures.push("declaration");
    if (expected.category && !actual.category.includes(expected.category)) failures.push("category");
    if (expected.body && actual.description !== expected.body) failures.push("description");
    for (const tag of expected.tags) if (!actual.tags.includes(tag)) failures.push(\`tag:\${tag}\`);
    if (expected.collection && !actual.collection.includes(expected.collection)) failures.push("collection");
    if (expected.scheduledDisplay && !actual.scheduleText.includes(expected.scheduledDisplay)) failures.push("schedule");
    if (signals.upload_busy || signals.upload_failed || signals.upload_prompt_only || signals.blockers.length) failures.push("upload_ready");
    return { platform: "bilibili", actions, actual, verified: failures.length === 0, failures };
  })()`;
  return evaluateWithClient(client, expression, 120000);
}

async function setBilibiliCoverImage(client, coverPath) {
  const expectedCoverPath = String(coverPath || "").trim();
  if (!expectedCoverPath) return { field: "cover", uploaded: false, reason: "missing_cover_path" };
  const openEditor = await evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const cover = document.querySelector(".cover");
    const scrollables = [document.scrollingElement, ...document.querySelectorAll("*")].filter((el) => el && el.scrollHeight > el.clientHeight + 20);
    for (const scroller of scrollables) {
      try { scroller.scrollTop = Math.max(0, (cover?.offsetTop || 450) - 120); } catch {}
    }
    cover?.scrollIntoView({ block: "center", inline: "center" });
    await sleep(400);
    const candidates = [...document.querySelectorAll(".edit-text,.cover-img,.cover-main,.cover-item")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), className: String(el.className || "") }));
    const target = candidates.find((item) => item.text === "封面设置") || candidates.find((item) => /cover-img|cover-main/.test(item.className));
    if (!target) return { opened: false, reason: "cover_setting_entry_not_found", candidates: candidates.map((item) => ({ text: item.text, className: item.className })).slice(0, 20) };
    click(target.el);
    await sleep(1500);
    return { opened: /封面制作|上传封面|4:3封面预览|首页推荐封面/.test(clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "")), target: { text: target.text, className: target.className } };
  })()`, 20000);
  if (!openEditor.opened) return { field: "cover", uploaded: false, ...openEditor };

  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: documentResult.root.nodeId, selector: "input[type=file]" });
  const inputs = [];
  for (const nodeId of queryResult.nodeIds || []) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    inputs.push({ nodeId, attrMap });
  }
  const imageInput = inputs.find((item) => /image|png|jpe?g/i.test(item.attrMap.accept || ""));
  if (!imageInput) {
    return { field: "cover", uploaded: false, opened: true, reason: "cover_image_input_not_found", fileInputs: inputs.map((item) => item.attrMap) };
  }
  await client.send("DOM.setFileInputFiles", { nodeId: imageInput.nodeId, files: [expectedCoverPath] });
  await sleep(4000);
  const closeEditor = await evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled;
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const buttons = [...document.querySelectorAll("button,[role=button],.bcc-button,span,div")].filter(visible);
    const done = buttons.find((el) => clean(el.innerText || el.textContent || el.value) === "完成")
      || buttons.find((el) => clean(el.innerText || el.textContent || el.value) === "确定");
    if (done) {
      click(done);
      await sleep(2500);
    }
    const body = ((document.scrollingElement || document.documentElement || document.body)?.innerText) || "";
    return {
      clicked_done: Boolean(done),
      editor_still_open: /封面制作|上传封面|4:3封面预览|首页推荐封面/.test(body),
      page_cover_text: clean(document.querySelector(".cover")?.innerText || ""),
    };
  })()`, 20000);
  return {
    field: "cover",
    expected_path: expectedCoverPath,
    uploaded: Boolean(closeEditor.clicked_done && !closeEditor.editor_still_open),
    opened: true,
    image_input: imageInput.attrMap,
    ...closeEditor,
  };
}

async function handleBilibiliSecondConfirmation(client) {
  return evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const bodyText = clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "");
    const detected = /发布前请添加创作声明|根据相关法律法规要求|内容无需标注|去声明/.test(bodyText);
    const actions = [];
    if (!detected) return { detected: false, actions };
    const clickText = async (texts, scope = document) => {
      for (const text of texts) {
        const item = [...scope.querySelectorAll("button,[role=button],input[type=button],input[type=submit],a,li,div,span,[role=option],.bcc-option,.option-hover-tips")]
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent || el.value), className: String(el.className || "") }))
          .filter((item) => item.text === text || item.text.includes(text))
          .sort((left, right) => {
            const leftRect = left.el.getBoundingClientRect();
            const rightRect = right.el.getBoundingClientRect();
            const leftExact = left.text === text ? 0 : 1;
            const rightExact = right.text === text ? 0 : 1;
            if (leftExact !== rightExact) return leftExact - rightExact;
            return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
          })[0];
          if (item) {
            click(item.el);
            if (typeof item.el.click === "function") item.el.click();
            await sleep(2200);
            return { clicked: true, requested: text, label: item.text, className: item.className };
          }
      }
      return { clicked: false };
    };
    actions.push({ kind: "set_content_declared", ...(await clickText([${JSON.stringify(compositePlatformDefaultDeclaration("bilibili"))}], document)) });

    const declarationInput = [...document.querySelectorAll("input,textarea")].find((el) => visible(el) && /创作声明|内容标签|内容标注/.test(el.placeholder || el.getAttribute("aria-label") || el.getAttribute("name") || ""));
    if (declarationInput) {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (setter) setter.call(declarationInput, ${JSON.stringify(compositePlatformDefaultDeclaration("bilibili"))});
      else declarationInput.value = ${JSON.stringify(compositePlatformDefaultDeclaration("bilibili"))};
      declarationInput.dispatchEvent(new Event("input", { bubbles: true }));
      declarationInput.dispatchEvent(new Event("change", { bubbles: true }));
      actions.push({ kind: "fill_declaration_input", field: "创作声明", expected: ${JSON.stringify(compositePlatformDefaultDeclaration("bilibili"))}, actual: clean(declarationInput.value), className: clean(String(declarationInput.className || "")) });
    }

    actions.push({ kind: "handle_secondary_layer", ...(await clickText(["去声明", "我知道了", "确认", "确定", "关闭"])) });
    await sleep(3000);
    return {
      detected: true,
      actions,
      still_visible: /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(clean(((document.scrollingElement || document.documentElement || document.body)?.innerText) || "")),
    };
  })()`, 25000);
}

async function waitForBilibiliPublishReceipt(client, content, timeoutMs = 70000) {
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const startedAt = Date.now();
  let snapshot = await pageSnapshot(client);
  while (Date.now() - startedAt < timeoutMs) {
    snapshot = await pageSnapshot(client);
    const lines = (snapshot.lines || []).slice(0, 240);
    const joined = lines.join(" ");
    const publishFormStillVisible = /立即投稿|存草稿|发布视频/.test(joined) && /封面设置|创作声明|定时发布/.test(joined);
    const finalConfirmationStillVisible = /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(joined);
    const successLike = /投稿成功|发布成功|已预约|定时发布成功|稿件已提交|审核中|等待审核|已进入审核|发布管理|内容管理|稿件管理/.test(joined)
      && !finalConfirmationStillVisible
      && !publishFormStillVisible;
    if (successLike || (!publishFormStillVisible && finalConfirmationStillVisible)) {
      return {
        status: successLike ? (scheduled ? "scheduled_pending" : "published") : "needs_human",
        snapshot,
        final_publish: {
          platform: "bilibili",
          scheduled,
          success_like: successLike || finalConfirmationStillVisible,
          publish_form_still_visible: publishFormStillVisible,
          final_confirmation_still_visible: finalConfirmationStillVisible,
          route: { url: snapshot.url || "", title: snapshot.title || "" },
          visible_lines: lines.filter((line) => /投稿|发布|预约|定时|审核|成功|稿件|管理/.test(line)).slice(0, 80),
        },
      };
    }
    await sleep(2500);
  }
  return {
    status: "needs_human",
    snapshot,
    final_publish: {
      platform: "bilibili",
      scheduled,
      success_like: false,
      publish_form_still_visible: /立即投稿|存草稿|发布视频/.test(((snapshot.lines || []).join(" "))) && /封面设置|创作声明|定时发布/.test(((snapshot.lines || []).join(" "))),
      final_confirmation_still_visible: /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(((snapshot.lines || []).join(" "))),
      route: { url: snapshot.url || "", title: snapshot.title || "" },
      visible_lines: (snapshot.lines || []).filter((line) => /投稿|发布|预约|定时|审核|成功|稿件|管理/.test(line)).slice(0, 80),
    },
  };
}

async function finalizeBilibiliPublish(client, content) {
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const publishTexts = scheduled
    ? ["定时投稿", "预约投稿", "定时发布", "投稿"]
    : ["立即投稿", "发布", "投稿"];
  const confirmTexts = ["确定", "确认", "确认投稿", "确定发布", "我知道了"];
  const actions = [];
  const firstClick = await clickFinalPublishByText(client, publishTexts);
  actions.push({ kind: "final_publish_click", ...firstClick });
  if (!firstClick.clicked) {
    return {
      status: "needs_human",
      actions,
      error: {
        code: "bilibili_final_publish_button_not_found",
        message: "B站字段已校验通过，但没有找到最终投稿/定时投稿按钮。",
      },
    };
  }
  await sleep(1800);
  const secondConfirmation = await handleBilibiliSecondConfirmation(client);
  actions.push({ kind: "second_confirmation", ...secondConfirmation });
  let confirmClick = await clickFinalPublishByText(client, ["去声明", ...confirmTexts]);
  actions.push({ kind: "final_confirm_click", ...confirmClick });
  await sleep(confirmClick.clicked ? 3000 : 1800);
  let receipt = await waitForBilibiliPublishReceipt(client, content, scheduled ? 90000 : 70000);

  if (receipt.status === "needs_human" && (receipt.final_publish?.final_confirmation_still_visible || secondConfirmation.still_visible)) {
    const recovery = await handleBilibiliSecondConfirmation(client);
    actions.push({ kind: "second_confirmation_retry", ...recovery });
    if (recovery.detected) {
      const retryConfirm = await clickFinalPublishByText(client, ["去声明", ...confirmTexts]);
      actions.push({ kind: "final_confirm_retry_click", ...retryConfirm });
      await sleep(retryConfirm.clicked ? 2600 : 1400);
      receipt = await waitForBilibiliPublishReceipt(client, content, scheduled ? 90000 : 70000);
    }
  }

  const resultSnapshot = receipt.snapshot || {};
  const lines = (resultSnapshot.lines || []).slice(0, 240);
  const joined = lines.join(" ");
  const publishFormStillVisible = receipt.final_publish?.publish_form_still_visible || (/立即投稿|存草稿|发布视频/.test(joined) && /封面设置|创作声明|定时发布/.test(joined));
  const finalConfirmationStillVisible = receipt.final_publish?.final_confirmation_still_visible || /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(joined);
  return {
    status: receipt.status,
    result: {
      final_publish: {
        ...(receipt.final_publish || {}),
        actions,
      },
    },
    ...(receipt.status === "needs_human"
      ? {
          ..._build_publication_recovery_hint({
            platform: "bilibili",
            code: "bilibili_final_publish_unconfirmed",
            reason: "B站发布未读到可确认回执。",
            route: {
              url: resultSnapshot.url || "",
              title: resultSnapshot.title || "",
              path: resultSnapshot.path || "",
            },
            visibleLines: lines,
            actionHistory: actions,
            clearDraftContext: true,
            forceRefresh: true,
            blockers: [{
              code: "bilibili_final_publish_unconfirmed",
              message: publishFormStillVisible
                ? "页面仍停留在投稿表单，可能卡在未提交成功状态。"
                : "未读到 B站成功/审核回执。",
              details: joined,
            }],
          }).recovery,
          error: {
            code: "bilibili_final_publish_unconfirmed",
            message: publishFormStillVisible
              ? "已点击 B站最终投稿按钮，但页面仍停留在投稿表单，不能判定为发布成功。"
              : "已点击 B站最终投稿按钮，但页面没有读到成功/审核/预约回执，需要人工确认。",
            details: receipt.final_publish || {},
          },
        }
      : { error: null }),
  };
}

async function preparePublicationTask(task) {
  const platform = normalizePlatform(task.platform);
  const rawContent = task.content && typeof task.content === "object" ? task.content : {};
  const content = applyCompositeSafeRuntimePolicyDefaults(platform, rawContent);
  const preparationPolicy = derivePublicationTaskPreparationPolicy(content);
  const draftPolicyBlockers = shouldApplyCompositeDraftPolicyBlockers(preparationPolicy)
    ? deriveCompositeDraftPolicyBlockers(platform, content)
    : [];
  if (draftPolicyBlockers.length) {
    const primaryBlocker = draftPolicyBlockers[0];
    return _attach_publication_signature_to_task_result({
      status: "needs_human",
      result: _attach_publication_content_signature({
        platform,
        route: {},
        actions: [],
        ..._build_publication_recovery_hint({
          platform,
          code: primaryBlocker.code,
          reason: primaryBlocker.message,
          route: {},
          actionHistory: [],
          clearDraftContext: false,
          forceRefresh: false,
          recoveryOverrides: {
            recovery_mode: preparationPolicy?.recoveryContext?.recovery_mode || "auto_recover",
            verification_only_current_page: preparationPolicy?.verificationOnlyCurrentPage,
            repair_only_current_page: preparationPolicy?.repairOnlyCurrentPage,
            prepublish_only_current_page: preparationPolicy?.prepublishOnlyCurrentPage,
            prepare_only_current_page: preparationPolicy?.prepareOnlyCurrentPage,
            verify_media_upload: preparationPolicy?.recoveryContext?.verify_media_upload,
            wait_for_publish_confirmation: preparationPolicy?.recoveryContext?.wait_for_publish_confirmation,
          },
          blockers: draftPolicyBlockers.map((blocker) => ({
            code: blocker.code,
            message: blocker.message,
            details: blocker.details || "",
          })),
        }).recovery,
        draft_policy_blockers: draftPolicyBlockers,
      }, content),
      error: {
        code: primaryBlocker.code,
        message: primaryBlocker.message,
        details: primaryBlocker,
      },
    }, content);
  }
  const recoveryContext = preparationPolicy.recoveryContext;
  const forceMediaUpload = preparationPolicy.forceMediaUpload;
  const forcePublishPageRefresh = Boolean(preparationPolicy.forcePublishPageRefresh);
  const verificationOnlyCurrentPage = Boolean(preparationPolicy.verificationOnlyCurrentPage);
  const repairOnlyCurrentPage = Boolean(preparationPolicy.repairOnlyCurrentPage);
  const prepublishOnlyCurrentPage = Boolean(preparationPolicy.prepublishOnlyCurrentPage);
  const prepareOnlyCurrentPage = Boolean(preparationPolicy.prepareOnlyCurrentPage);
  const currentPageOnlyMode = verificationOnlyCurrentPage || repairOnlyCurrentPage;
  const stopBeforeFinalPublish = Boolean(preparationPolicy.stopBeforeFinalPublish);
  const currentPageSafeMode = currentPageOnlyMode || stopBeforeFinalPublish;
  const waitForPublishConfirmation = Boolean(recoveryContext.wait_for_publish_confirmation);
  const verifyMediaUpload = recoveryContext.verify_media_upload !== false;
  const captureResponseTimeoutMs = _coerceRecoveryTimeoutMs(recoveryContext.capture_response_timeout_ms, 65000);
  const uploadReadinessTimeoutMs = compositeUploadReadinessTimeoutMs(platform, captureResponseTimeoutMs);
  const mediaPath = expectedMediaPath(content);
  const actions = [];
  const reportTaskProgress = (patch = {}) => reportTaskPreparationStage(task, patch);
  const tabSelectionPolicy = derivePlatformTabSelectionPolicy(platform, recoveryContext);
  reportTaskProgress({
    phase: "resolving_platform_tab",
    route: {},
    actions,
  });
  let resolution;
  try {
    resolution = await withAsyncStepTimeout(
      resolvePlatformTab(platform, {
        force_fresh_tab: forceMediaUpload,
        tab_selection: tabSelectionPolicy,
      }),
      15000,
      "platform_tab_resolution_timeout",
      `Resolving ${platform} publication tab timed out`,
      { platform, phase: "resolve_platform_tab" },
    );
  } catch (error) {
    if (error instanceof AsyncStepTimeoutError) {
      return buildPreparationBootstrapTimeoutOutcome({
        platform,
        code: error.code,
        reason: error.message,
        route: {},
        actions,
        preparationPolicy,
        content,
        details: error.details,
      });
    }
    throw error;
  }
  if (resolution.error || !resolution.tab) {
    return {
      status: "needs_human",
      result: _attach_publication_content_signature({
        platform,
        route: {},
        actions: [...(resolution.actions || [])],
        ..._build_publication_recovery_hint({
          platform,
          code: resolution.error?.code || "platform_tab_not_found",
          reason: String(resolution.error?.message || `没有找到 ${platform} 已打开的创作/发布页。`),
          route: {},
          actionHistory: [...(resolution.actions || [])],
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: "platform_tab_not_found", message: String(resolution.error?.message || "页面尚未打开。"), details: String(resolution.error?.code || "") }],
        }).recovery,
      }, content),
      error: resolution.error || { code: "platform_tab_not_found", message: `没有找到 ${platform} 已打开的创作/发布页。` },
    };
  }
  const tab = resolution.tab;
  actions.push(...(resolution.actions || []));
  reportTaskProgress({
    phase: "platform_tab_resolved",
    route: {
      url: String(tab?.url || ""),
      title: String(tab?.title || ""),
      path: "",
    },
    actions,
  });
  let client;
  try {
    client = await CdpClient.connect(tab.webSocketDebuggerUrl, 10000);
  } catch (error) {
    if (error instanceof AsyncStepTimeoutError || String(error?.message || "").includes("CDP websocket connect failed")) {
      const code = error instanceof AsyncStepTimeoutError ? error.code : "platform_cdp_connect_failed";
      return buildPreparationBootstrapTimeoutOutcome({
        platform,
        code,
        reason: String(error?.message || `Connecting ${platform} CDP tab failed`),
        route: {
          url: String(tab?.url || ""),
          title: String(tab?.title || ""),
          path: "",
        },
        actions,
        preparationPolicy,
        content,
        details: {
          platform,
          phase: "connect_platform_tab",
          ...(error instanceof AsyncStepTimeoutError ? error.details : {}),
        },
      });
    }
    throw error;
  }
  reportTaskProgress({
    phase: "platform_tab_connected",
    route: {
      url: String(tab?.url || ""),
      title: String(tab?.title || ""),
      path: "",
    },
    actions,
  });
  const interruptions = [];
  let currentRouteHint = {
    url: String(tab?.url || ""),
    title: String(tab?.title || ""),
  };
  try {
  const shouldEnforcePublishRoute = shouldEnforcePlatformPublishRoute(platform, recoveryContext);
  reportTaskProgress({
    phase: "route_bootstrap_pending",
    route: {
      url: String(tab?.url || ""),
      title: String(tab?.title || ""),
      path: "",
    },
    actions,
  });
  let routeAction;
  try {
    routeAction = shouldEnforcePublishRoute
      ? await withAsyncStepTimeout(
        ensurePlatformPublishRoute(client, tab, platform, {
          force_publish_page_refresh: forcePublishPageRefresh || forceMediaUpload,
          prefer_draft_list_surface: Boolean(tabSelectionPolicy.prefer_draft_list_surface),
        }),
        30000,
        "platform_route_bootstrap_timeout",
        `Bootstrapping ${platform} publish route timed out`,
        { platform, phase: "ensure_publish_route" },
      )
      : {
        navigated: false,
        verified: true,
        url: String(tab.url || ""),
        reason: "receipt_rebind_preserve_current_route",
      };
  } catch (error) {
    if (error instanceof AsyncStepTimeoutError) {
      return buildPreparationBootstrapTimeoutOutcome({
        platform,
        code: error.code,
        reason: error.message,
        route: {
          url: String(tab?.url || ""),
          title: String(tab?.title || ""),
          path: "",
        },
        actions,
        preparationPolicy,
        content,
        details: error.details,
      });
    }
    throw error;
  }
  if (routeAction.navigated || !shouldEnforcePublishRoute) {
    actions.push({ kind: "ensure_platform_publish_route", ...routeAction });
  }
  currentRouteHint = {
    url: String(routeAction.url || tab.url || ""),
    title: String(tab?.title || ""),
  };
  reportTaskProgress({
    phase: "route_ready",
    route: {
      url: String(routeAction.url || tab.url || ""),
      title: String(tab.title || ""),
      path: "",
    },
  });
  if (platform === "toutiao" && routeAction.verified === false) {
      return {
        status: "needs_human",
        result: _attach_publication_content_signature({
          platform,
          route: { url: routeAction.url || tab.url || "", title: tab.title || "" },
          actions,
          ..._build_publication_recovery_hint({
            platform,
            code: "toutiao_video_publish_route_not_verified",
            reason: "头条专用框架未确认到上传页。",
            route: { url: routeAction.url || tab.url || "", title: tab.title || "" },
            actionHistory: actions,
            visibleLines: (routeAction.issues || []).concat(routeAction.reason || ""),
            clearDraftContext: true,
            forceRefresh: true,
            blockers: [{ code: "toutiao_video_publish_route_not_verified", message: "建议先清理草稿上下文并重试", details: String(routeAction.reason || "") }],
          }).recovery,
          composite_framework: {
            enabled: true,
            platform,
            framework_id: PLATFORM_COMPOSITE_FRAMEWORKS.toutiao.id,
            dedicated_platform_framework: true,
            legacy_lightweight_script_used: false,
          },
        }, content),
        error: {
          code: "toutiao_video_publish_route_not_verified",
          message: "头条专用框架未能确认进入西瓜视频上传页，已停止，避免误填文章发布页。",
          details: routeAction,
        },
      };
  }
  const draftResumePromptAction = !currentPageSafeMode
    ? await resolveCurrentPageDraftResumePrompt(client, platform).catch((error) => ({
        attempted: false,
        resumed: false,
        discarded: false,
        prompt_present: true,
        prompt_still_open: true,
        preferred_action: "discard",
        reason: "draft_resume_prompt_error",
        error: String(error?.message || error),
      }))
    : null;
  if (draftResumePromptAction?.attempted || draftResumePromptAction?.prompt_present) {
    actions.push({ kind: "draft_resume_prompt", ...draftResumePromptAction });
    currentRouteHint = {
      url: String(draftResumePromptAction?.after_url || draftResumePromptAction?.before_url || currentRouteHint.url || ""),
      title: String(tab?.title || currentRouteHint.title || ""),
    };
  }
  if (shouldBlockOnDraftResumePromptFailure(preparationPolicy, draftResumePromptAction)) {
    const promptSnapshot = await pageSnapshot(client, {
      captureVisualEvidence: true,
      platform,
      visualEvidencePhase: "draft_resume_prompt_blocked",
    }).catch(() => null);
    return {
      status: "needs_human",
      result: _attach_publication_content_signature({
        platform,
        route: {
          url: String(promptSnapshot?.url || currentRouteHint.url || tab?.url || ""),
          title: String(promptSnapshot?.title || currentRouteHint.title || tab?.title || ""),
        },
        actions,
        visual_evidence: promptSnapshot?.visual_evidence || undefined,
        ..._build_publication_recovery_hint({
          platform,
          code: "draft_resume_prompt_not_declined",
          reason: "检测到上次未发布/未提交视频提示，但未能确认点击放弃/不用了，已停止避免复用脏稿。",
          route: {
            url: String(promptSnapshot?.url || currentRouteHint.url || tab?.url || ""),
            title: String(promptSnapshot?.title || currentRouteHint.title || tab?.title || ""),
          },
          actionHistory: actions,
          visibleLines: (promptSnapshot?.lines || draftResumePromptAction?.after_lines || draftResumePromptAction?.before_lines || []).slice(0, 80),
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{
            code: "draft_resume_prompt_not_declined",
            message: "必须先放弃/不用上次未完成视频，再开始本次 Bilibili 发布。",
            details: String(draftResumePromptAction?.error || draftResumePromptAction?.clicked_label || draftResumePromptAction?.reason || ""),
          }],
        }).recovery,
      }, content),
      error: {
        code: "draft_resume_prompt_not_declined",
        message: "检测到旧的未完成视频提示，但未能确认放弃，已阻止继续发布。",
        details: draftResumePromptAction,
      },
    };
  }
  const clearAction = currentPageSafeMode
    ? {
        platform,
        attempted: false,
        cleared: false,
        skipped: true,
        stale_detected: false,
        before_media_hint: false,
        after_media_hint: false,
        before_draft_hint: false,
        after_draft_hint: false,
        actions: [{
          kind: "draft_clear_skipped",
          reason: prepareOnlyCurrentPage
            ? "prepare_only_current_page"
            : prepublishOnlyCurrentPage
            ? "prepublish_only_current_page"
            : (repairOnlyCurrentPage ? "repair_only_current_page" : "verification_only_current_page"),
        }],
        before_url: String(tab?.url || ""),
        after_url: String(tab?.url || ""),
        reason: prepareOnlyCurrentPage
          ? "prepare_only_current_page"
          : prepublishOnlyCurrentPage
          ? "prepublish_only_current_page"
          : (repairOnlyCurrentPage ? "repair_only_current_page" : "verification_only_current_page"),
      }
    : await clearInPageDraftState(client, platform, {
        mediaPath,
        clearIfStaleDraft: preparationPolicy.clearIfStaleDraft,
        forceClearDraft: preparationPolicy.forceClearDraft,
      }).catch((error) => ({
        platform,
        attempted: true,
        cleared: false,
        skipped: false,
        stale_detected: true,
        before_media_hint: false,
        after_media_hint: false,
        before_draft_hint: false,
        after_draft_hint: false,
        actions: [{ kind: "draft_clear_error", reason: String(error?.message || error) }],
        before_url: String(tab?.url || ""),
        after_url: String(tab?.url || ""),
        error: String(error?.message || error),
      }));
  actions.push({ kind: "draft_state_clear", ...clearAction });
  currentRouteHint = {
    url: String(clearAction?.after_url || clearAction?.before_url || currentRouteHint.url || ""),
    title: String(tab?.title || currentRouteHint.title || ""),
  };
  reportTaskProgress({
    phase: "draft_state_cleared",
    route: {
      url: String(tab?.url || ""),
      title: String(tab?.title || ""),
      path: "",
    },
    actions,
  });
  if (shouldBlockOnDraftClearFailure(preparationPolicy, clearAction)) {
    return {
      status: "needs_human",
      result: _attach_publication_content_signature({
        platform,
        route: {
          url: String(tab?.url || ""),
          title: String(tab?.title || ""),
        },
        actions,
        ..._build_publication_recovery_hint({
          platform,
          code: "draft_clear_failed",
          reason: "清理发布草稿失败，避免复用脏稿发布。",
          route: {
            url: String(tab?.url || ""),
            title: String(tab?.title || ""),
          },
          actionHistory: actions,
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: "draft_clear_failed", message: `清理草稿失败：${String(clearAction?.error || "")}`, details: String(clearAction?.error || "") }],
        }).recovery,
      }, content),
      error: {
        code: "draft_clear_failed",
        message: `草稿清理失败，已阻止发布：${String(clearAction?.error || "")}`,
      },
    };
  }
  if (clearAction?.attempted && !clearAction?.cleared) {
    actions.push({
      kind: "draft_clear_failed_non_blocking",
      reason: String(clearAction?.error || "draft_clear_not_completed"),
    });
  }
  if (currentPageSafeMode) {
    const resumeAction = await resolveCurrentPageDraftResumePrompt(client, platform).catch((error) => ({
      attempted: false,
      resumed: false,
      prompt_present: false,
      reason: "draft_resume_prompt_error",
      error: String(error?.message || error),
    }));
    if (resumeAction.attempted || resumeAction.reason === "draft_resume_prompt_error") {
      actions.push({ kind: "draft_resume_prompt", ...resumeAction });
    }
  }
  interruptions.push(...(await dismissInterruptions(client, tab, platform, "task_start")));
  let snapshot = await pageSnapshot(client, {
    captureVisualEvidence: true,
    platform,
    visualEvidencePhase: "editor_snapshot_ready",
  });
  reportTaskProgress({
    phase: "editor_snapshot_ready",
    route: {
      url: String(snapshot?.url || tab.url || ""),
      title: String(snapshot?.title || tab.title || ""),
      path: "",
    },
    visual_evidence: snapshot?.visual_evidence || undefined,
    visible_lines: (snapshot?.lines || []).slice(0, 120),
    actions,
  });
  if (currentPageOnlyMode) {
    const verificationWait = await runCompositePhase(
      platform,
      "verification_only_material_integrity_wait",
      () => waitForVerificationOnlyMaterialIntegrity(
        client,
        platform,
        content,
        12000,
        (state) => reportTaskProgress({
          phase: "verification_only_material_integrity_wait",
          route: {
            url: String(snapshot?.url || tab.url || ""),
            title: String(snapshot?.title || tab.title || ""),
            path: "",
          },
          visible_lines: state?.integrity?.platform_extras?.relevant_lines || (snapshot?.lines || []).slice(0, 120),
          material_integrity: state?.integrity || {},
          actions,
        }),
      ),
    );
    let integrity = verificationWait && typeof verificationWait === "object" ? verificationWait.integrity : null;
    if (!integrity || typeof integrity !== "object") {
      integrity = await runCompositePhase(platform, "verification_only_material_integrity", () => readCompositeMaterialIntegrity(client, platform, content));
    }
    snapshot = await pageSnapshot(client, {
      captureVisualEvidence: true,
      platform,
      visualEvidencePhase: "verification_only_current_page",
    }).catch(() => snapshot);
    const currentRoute = { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" };
    let verificationFinalPublish = {
      verification_only: true,
      stop_before_final_publish: true,
    };
    if (platform === "douyin" && _isDouyinPostPublishManagementRoute(currentRoute.url)) {
      const verificationReceipt = {
        receipt_like: true,
        post_click_integrity: {
          platform_extras: {
            relevant_lines: (snapshot?.lines || []).slice(0, 160),
            route: currentRoute,
          },
        },
      };
      integrity = normalizeCompositePostPublishIntegrity(
        platform,
        integrity,
        {},
        verificationReceipt,
        content,
      );
      verificationFinalPublish = {
        ...verificationFinalPublish,
        receipt_like: Boolean(integrity?.platform_extras?.douyin_manage_card?.matched),
        post_click_integrity: verificationReceipt.post_click_integrity,
      };
      if (!Boolean(integrity?.platform_extras?.douyin_manage_card?.matched)) {
        return _attach_publication_signature_to_task_result(
          _buildVerificationOnlyCurrentPageTargetMissing(platform, content, currentRoute, snapshot, integrity),
          content,
        );
      }
    } else if ((platform === "xiaohongshu" || platform === "toutiao") && isPlatformReceiptSurfaceUrl(platform, currentRoute.url)) {
      const verificationReceipt = {
        receipt_like: true,
        post_click_integrity: {
          platform_extras: {
            relevant_lines: (snapshot?.lines || []).slice(0, 160),
            route: currentRoute,
          },
        },
      };
      integrity = normalizeCompositePostPublishIntegrity(
        platform,
        integrity,
        {},
        verificationReceipt,
        content,
      );
      verificationFinalPublish = {
        ...verificationFinalPublish,
        receipt_like: true,
        post_click_integrity: verificationReceipt.post_click_integrity,
      };
      if (integrity?.platform_extras?.receipt_target_bound !== true) {
        return _attach_publication_signature_to_task_result(
          _buildVerificationOnlyCurrentPageTargetMissing(platform, content, currentRoute, snapshot, integrity),
          content,
        );
      }
    }
    let publicationAudit = buildCompositePublicationAudit(platform, content, integrity, verificationFinalPublish, currentRoute);
    let publicationFieldSnapshot = buildPublicationFieldSnapshotFromAudit(
      platform,
      content,
      publicationAudit,
      currentRoute,
      { repair_actions: [] },
    );
    reportTaskProgress({
      phase: "verification_only_material_integrity",
      route: {
        url: String(currentRoute.url || ""),
        title: String(currentRoute.title || ""),
        path: "",
      },
        visual_evidence: snapshot?.visual_evidence || undefined,
        material_integrity: integrity,
        publication_audit: publicationAudit,
        publication_field_snapshot: publicationFieldSnapshot,
        visible_lines: integrity?.platform_extras?.relevant_lines || (snapshot?.lines || []).slice(0, 120),
        actions,
    });
    if (integrity?.verification_state === "not_ready") {
      return _attach_publication_signature_to_task_result(
        _buildVerificationOnlyRouteNotReadyFailure(
          platform,
          content,
          currentRoute,
          snapshot,
          integrity,
        ),
        content,
      );
    }
    let repairAttempt = null;
    if (repairOnlyCurrentPage && !publicationAudit.verified) {
      const repairPlan = deriveCompositePrePublishRepairPlan(publicationAudit, integrity, {
        allowRepairWithBlocking: true,
      });
      if (repairPlan.shouldRepair) {
        reportTaskProgress({
          phase: "repair_only_current_page_attempt",
          route: {
            url: String(currentRoute.url || ""),
            title: String(currentRoute.title || ""),
            path: "",
          },
          material_integrity: integrity,
          publication_audit: publicationAudit,
          publication_field_snapshot: publicationFieldSnapshot,
          visible_lines: integrity?.platform_extras?.relevant_lines || (snapshot?.lines || []).slice(0, 120),
          actions,
        });
        const framework = PLATFORM_COMPOSITE_FRAMEWORKS[platform];
        if (framework) {
          const repairExecutor = typeof framework.repair === "function"
            ? () => framework.repair(client, platform, content, repairPlan.repairable_fields)
            : () => framework.prepare(client, platform, content);
          const repairActions = await runCompositePhase(
            platform,
            `repair_only_current_page_${framework.id}`,
            repairExecutor,
          );
          if (!Array.isArray(repairActions)) {
            throw new TypeError("composite_repair_actions_invalid");
          }
          actions.push(...repairActions);
          await sleep(1200);
          integrity = await runCompositePhase(platform, "repair_only_current_page_material_integrity_reverify", () => readCompositeMaterialIntegrity(client, platform, content));
          snapshot = await pageSnapshot(client).catch(() => snapshot);
          const reverifyRoute = { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" };
          publicationAudit = buildCompositePublicationAudit(platform, content, integrity, verificationFinalPublish, reverifyRoute);
          publicationFieldSnapshot = buildPublicationFieldSnapshotFromAudit(
            platform,
            content,
            publicationAudit,
            reverifyRoute,
            { repair_actions: repairActions },
          );
          repairAttempt = {
            attempted: true,
            repairable_fields: repairPlan.repairable_fields,
            before_required_unverified: repairPlan.required_unverified,
            after_required_unverified: Array.isArray(publicationAudit?.required_unverified) ? publicationAudit.required_unverified : [],
            actions: repairActions,
          };
          reportTaskProgress({
            phase: "repair_only_current_page_reverify",
            route: {
              url: String(reverifyRoute.url || ""),
              title: String(reverifyRoute.title || ""),
              path: "",
            },
            material_integrity: integrity,
            publication_audit: publicationAudit,
            publication_field_snapshot: publicationFieldSnapshot,
            visible_lines: integrity?.platform_extras?.relevant_lines || (snapshot?.lines || []).slice(0, 120),
            actions,
          });
        }
      }
    }
    if (!publicationAudit.verified) {
      return _attach_publication_signature_to_task_result(
        _buildVerificationOnlyMaterialIntegrityFailure(
          platform,
          content,
          currentRoute,
          snapshot,
          integrity,
          publicationAudit,
          publicationFieldSnapshot,
          {
            final_publish: {
              ...verificationFinalPublish,
              repair_only_current_page: repairOnlyCurrentPage,
              pre_publish_repair: repairAttempt || undefined,
            },
            actions,
          },
        ),
        content,
      );
    }
    return _attach_publication_signature_to_task_result({
      status: "verified",
      result: _attach_publication_content_signature({
        platform,
        route: currentRoute,
        draft_url: currentRoute.url || "",
        composite_framework: COMPOSITE_PUBLISH_PLATFORMS.has(platform)
          ? {
              enabled: true,
              platform,
              framework_id: dedicatedCompositeFrameworkId(platform),
              dedicated_platform_framework: Boolean(dedicatedCompositeFrameworkId(platform)),
              legacy_lightweight_script_used: false,
              material_integrity: integrity,
            }
          : undefined,
        publication_audit: publicationAudit,
        publication_field_snapshot: publicationFieldSnapshot,
        material_integrity: integrity,
        final_publish: {
          ...verificationFinalPublish,
          repair_only_current_page: repairOnlyCurrentPage,
          pre_publish_repair: repairAttempt || undefined,
        },
        actions: actions.slice(0, 120),
        visible_option_lines: (integrity?.platform_extras?.relevant_lines || snapshot?.lines || []).slice(0, 160),
      }, content),
      error: null,
    }, content);
  }
  const requiresLocalMedia = compositeRequiresLocalMedia(platform, content);
  if (stopBeforeFinalPublish && !currentPageOnlyMode && requiresLocalMedia && mediaPath) {
    const stabilized = await stabilizeCurrentPageMediaStateForPrepublish(client, platform, snapshot, mediaPath, { requiresLocalMedia });
    snapshot = stabilized.snapshot || snapshot;
    if (stabilized.waited_ms > 0) {
      actions.push({
        kind: "current_page_media_state_stabilized",
        waited_ms: stabilized.waited_ms,
        media_reuse_reason: stabilized.mediaState?.reason || "",
        reusable: Boolean(stabilized.mediaState?.reusable),
      });
    }
  }
  const stopBeforeCurrentMediaState = stopBeforeFinalPublish
    ? canReuseCurrentPageMediaForPrepublish(platform, snapshot, mediaPath, { requiresLocalMedia })
    : { reusable: Boolean(mediaPath && pageAlreadyHasMedia(snapshot, mediaPath)), reason: mediaPath ? "media_path_match" : "missing_media_path" };
  if (stopBeforeFinalPublish && shouldBootstrapStopBeforeMediaRouteRecovery(platform, snapshot, stopBeforeCurrentMediaState)) {
    if (platform === "youtube") {
      const routeBootstrap = await ensureYoutubeUploadEditor(
        client,
        String(content?.title || "").trim() || path.win32.basename(String(mediaPath || "")).replace(/\.[^.]+$/, ""),
      ).catch((error) => ({
        matched: false,
        changed: false,
        error: String(error?.message || error || ""),
      }));
      actions.push({ kind: "youtube_upload_editor_media_reuse_bootstrap", ...routeBootstrap });
      if (routeBootstrap?.changed) {
        await sleep(2600);
        snapshot = await pageSnapshot(client).catch(() => snapshot);
      }
    }
  }
  const refreshedStopBeforeCurrentMediaState = stopBeforeFinalPublish
    ? canReuseCurrentPageMediaForPrepublish(platform, snapshot, mediaPath, { requiresLocalMedia })
    : stopBeforeCurrentMediaState;
  let stopBeforeRouteDisposition = stopBeforeFinalPublish
    ? deriveCompositeCurrentPageRouteDisposition(platform, snapshot)
    : { blocked: false };
  if (stopBeforeFinalPublish && shouldBootstrapStopBeforeRouteRecovery(platform, stopBeforeRouteDisposition)) {
    if (platform === "youtube") {
      const routeBootstrap = await ensureYoutubeUploadEditor(
        client,
        String(content?.title || "").trim() || path.win32.basename(String(mediaPath || "")).replace(/\.[^.]+$/, ""),
      ).catch((error) => ({
        matched: false,
        changed: false,
        error: String(error?.message || error || ""),
      }));
      actions.push({ kind: "youtube_upload_editor_route_bootstrap", ...routeBootstrap });
      if (routeBootstrap?.changed) {
        await sleep(2600);
        snapshot = await pageSnapshot(client).catch(() => snapshot);
      }
      stopBeforeRouteDisposition = deriveCompositeCurrentPageRouteDisposition(platform, snapshot);
    }
  }
  if (stopBeforeFinalPublish && stopBeforeRouteDisposition.blocked) {
    return {
      status: "needs_human",
      result: _attach_publication_content_signature({
        platform,
        route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
        actions,
        final_publish: {
          pre_publish_pending: false,
          wait_for_upload_ready: false,
          prepublish_only_current_page: prepublishOnlyCurrentPage,
          prepare_only_current_page: prepareOnlyCurrentPage,
          stop_before_final_publish: true,
        },
        material_integrity: {
          verification_state: stopBeforeRouteDisposition.verification_reason === "auth_required" ? "auth_required" : "not_ready",
          verification_reason: stopBeforeRouteDisposition.verification_reason,
        },
        ..._build_publication_recovery_hint({
          platform,
          code: stopBeforeRouteDisposition.code,
          reason: stopBeforeRouteDisposition.verification_reason === "auth_required"
            ? "安全预发布验证模式检测到当前页面处于登录/鉴权态，已阻断以避免错误操作。"
            : "安全预发布验证模式未确认当前页面处于正确发布页，已阻断以避免错误操作。",
          route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
          actionHistory: actions.slice(0, 80),
          visibleLines: (snapshot?.lines || []).slice(0, 120),
          clearDraftContext: false,
          forceRefresh: stopBeforeRouteDisposition.verification_reason !== "auth_required",
          blockers: [{
            code: stopBeforeRouteDisposition.code,
            message: stopBeforeRouteDisposition.verification_reason === "auth_required"
              ? "当前页面处于登录/鉴权态，安全预发布验证模式不会继续执行。"
              : "当前页面未确认到正确发布路由，安全预发布验证模式不会继续执行。",
            details: JSON.stringify({ route_url: snapshot?.url || tab.url || "", verification_reason: stopBeforeRouteDisposition.verification_reason }),
          }],
          recoveryOverrides: buildStopBeforeFinalPublishRecoveryOverrides({
            prepublishOnlyCurrentPage,
            prepareOnlyCurrentPage,
            verificationReason: stopBeforeRouteDisposition.verification_reason,
          }),
        }).recovery,
      }, content),
      error: {
        code: stopBeforeRouteDisposition.code,
        message: stopBeforeRouteDisposition.verification_reason === "auth_required"
          ? "安全预发布验证模式检测到登录/鉴权页面，已阻断。"
          : "安全预发布验证模式未确认当前页面处于正确发布页，已阻断。",
        details: {
          route_url: snapshot?.url || tab.url || "",
          verification_reason: stopBeforeRouteDisposition.verification_reason,
        },
      },
    };
  }
  const mediaAlreadyPresent = Boolean(stopBeforeFinalPublish ? refreshedStopBeforeCurrentMediaState.reusable : (mediaPath && pageAlreadyHasMedia(snapshot, mediaPath)));
  const stopBeforeUploadBootstrap = shouldBootstrapStopBeforeMediaUpload(
    platform,
    mediaPath,
    refreshedStopBeforeCurrentMediaState,
    {
      stopBeforeFinalPublish,
      requiresLocalMedia,
      verifyMediaUpload,
    },
  );
  if (stopBeforeFinalPublish && !refreshedStopBeforeCurrentMediaState.reusable && !stopBeforeUploadBootstrap) {
      const mediaPendingDisposition = deriveCompositeCurrentPageMediaPendingDisposition(platform, mediaPath, refreshedStopBeforeCurrentMediaState);
      if (mediaPendingDisposition.pending) {
        return {
          status: "processing",
          result: _attach_publication_content_signature({
            platform,
            route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
            actions,
            final_publish: {
              pre_publish_pending: true,
              wait_for_upload_ready: true,
              prepublish_only_current_page: prepublishOnlyCurrentPage,
              prepare_only_current_page: prepareOnlyCurrentPage,
              stop_before_final_publish: true,
            },
            publication_audit: {
              checklist: {
                upload_ready: { verified: false, actual: "not_ready", expected: "ready" },
              },
              required_unverified: ["upload_ready"],
              required_reupload: ["upload_ready"],
              notes: "required_unverified:upload_ready",
            },
            material_integrity: {
              verification_state: "pending",
              verification_reason: "publish_media_entry",
              failures: ["upload_ready"],
            },
            ..._build_publication_recovery_hint({
              platform,
              code: mediaPendingDisposition.code,
              reason: "安全预发布验证模式已进入媒体入口，等待目标媒体挂载完成后再继续字段验证。",
              route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
              actionHistory: actions.slice(0, 80),
              visibleLines: (snapshot?.lines || []).slice(0, 120),
              clearDraftContext: false,
              forceRefresh: true,
              blockers: [{
                code: mediaPendingDisposition.code,
                message: "当前页面处于媒体入口等待态，安全预发布验证模式不会自动补上传。",
                details: JSON.stringify({ media_path: mediaPath || "", media_reuse_reason: mediaPendingDisposition.media_reuse_reason || "", media_already_present: mediaAlreadyPresent }),
              }],
              recoveryOverrides: buildStopBeforeFinalPublishRecoveryOverrides({
                prepublishOnlyCurrentPage,
                prepareOnlyCurrentPage,
              }),
          }).recovery,
          interruptions,
        }, content),
        error: {
          code: mediaPendingDisposition.code,
            message: "安全预发布验证模式等待目标媒体挂载完成。",
            details: {
              media_path: mediaPath || "",
              media_already_present: mediaAlreadyPresent,
              media_reuse_reason: mediaPendingDisposition.media_reuse_reason || "",
            },
          },
        };
      }
      return {
        status: "needs_human",
        result: _attach_publication_content_signature({
          platform,
          route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
          actions,
          final_publish: {
            pre_publish_pending: false,
            wait_for_upload_ready: false,
            prepublish_only_current_page: prepublishOnlyCurrentPage,
            prepare_only_current_page: prepareOnlyCurrentPage,
            stop_before_final_publish: true,
          },
          ..._build_publication_recovery_hint({
            platform,
            code: `${platform}_prepublish_only_media_missing`,
            reason: "安全预发布验证模式未确认当前页面已挂载目标媒体，已阻断以避免自动补上传或误触发布。",
            route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
            actionHistory: actions.slice(0, 80),
            visibleLines: (snapshot?.lines || []).slice(0, 120),
            clearDraftContext: false,
            forceRefresh: true,
            blockers: [{
              code: `${platform}_prepublish_only_media_missing`,
              message: "当前页面未确认目标媒体已存在，安全预发布验证模式不会自动补上传。",
              details: JSON.stringify({ media_path: mediaPath || "", media_reuse_reason: refreshedStopBeforeCurrentMediaState.reason || "", media_already_present: mediaAlreadyPresent }),
            }],
            recoveryOverrides: buildStopBeforeFinalPublishRecoveryOverrides({
              prepublishOnlyCurrentPage,
              prepareOnlyCurrentPage,
            }),
          }).recovery,
          interruptions,
        }, content),
        error: {
          code: `${platform}_prepublish_only_media_missing`,
          message: "安全预发布验证模式未检测到当前页面已有目标媒体，已阻断。",
          details: {
            media_path: mediaPath || "",
            media_already_present: mediaAlreadyPresent,
            media_reuse_reason: stopBeforeCurrentMediaState.reason || "",
          },
        },
      };
  }
  if (shouldAttemptMediaBootstrap({
    stopBeforeFinalPublish,
    prepublishOnlyCurrentPage,
    forceMediaUpload,
    stopBeforeUploadBootstrap,
    mediaAlreadyPresent,
    pageHasMedia: pageAlreadyHasMedia(snapshot, mediaPath),
    hasMediaPath: Boolean(mediaPath),
  })) {
      if (platform === "youtube") {
        actions.push(await clickByText(client, ["创建", "上传视频", "Upload videos", "CREATE"]));
        await sleep(2200);
      }
      if (platform === "youtube") {
        actions.push({ kind: `${platform}_upload_entry`, ...(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发表视频"])) });
        if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_upload_entry_loose`, ...(await clickLooseText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发表视频"])) });
        if (!actions.some((action) => /^youtube_upload_entry/.test(String(action?.kind || "")) && action?.clicked)) {
          actions.push({ kind: "youtube_upload_entry_hidden", ...(await activateYoutubeHiddenUploadEntry(client)) });
        }
        await sleep(1600);
      } else if (platform === "kuaishou" || platform === "wechat-channels") {
        actions.push({ kind: `${platform}_upload_entry`, ...(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发表视频"])) });
        if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_upload_entry_loose`, ...(await clickLooseText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发表视频"])) });
        await sleep(1600);
      }
      let upload = await setFirstVideoFileInput(client, mediaPath);
      if (!upload.uploaded) {
        actions.push(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发布视频"]));
        await sleep(2200);
        upload = await setFirstVideoFileInput(client, mediaPath);
      }
      actions.push({ kind: "media_upload", ...upload });
      snapshot = await pageSnapshot(client).catch(() => snapshot);
      const uploadInProgress = shouldTreatMediaUploadAsInProgress(platform, upload, snapshot, mediaPath);
      reportTaskProgress({
        phase: upload.uploaded ? "media_uploaded" : (uploadInProgress ? "media_upload_in_progress" : "media_upload_failed"),
        route: {
          url: String(snapshot?.url || tab?.url || ""),
          title: String(snapshot?.title || tab?.title || ""),
          path: "",
        },
        visible_lines: (snapshot?.lines || []).slice(0, 120),
        actions,
      });
      if (shouldBlockOnMediaUploadFailure(upload) && !uploadInProgress) {
        const uploadFailureDisposition = deriveCompositeMediaUploadFailureDisposition(platform, upload, {
          stopBeforeFinalPublish,
          prepublishOnlyCurrentPage,
          prepareOnlyCurrentPage,
        });
        return {
          status: "needs_human",
          result: _attach_publication_content_signature({
            platform,
            route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
            actions,
            ..._build_publication_recovery_hint({
              platform,
              code: uploadFailureDisposition.code,
              reason: "未能将视频素材重新挂载到发布页，已阻断后续填充与发布。",
              route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
              actionHistory: actions.slice(0, 80),
              visibleLines: (snapshot?.lines || []).slice(0, 120),
              clearDraftContext: uploadFailureDisposition.clear_draft_context,
              forceRefresh: uploadFailureDisposition.force_publish_page_refresh,
              blockers: [{
                code: uploadFailureDisposition.code,
                message: "未找到可用的视频上传入口或文件输入框，不能继续发布。",
                details: JSON.stringify(uploadFailureDisposition.blocker_details),
              }],
              recoveryOverrides: uploadFailureDisposition.recovery_overrides,
            }).recovery,
            interruptions,
          }, content),
          error: {
            code: uploadFailureDisposition.code,
            message: `媒体上传失败：${String(upload.reason || "unknown")}`,
            details: uploadFailureDisposition.error_details,
          },
        };
      }
      if ((upload.uploaded || uploadInProgress) && verifyMediaUpload) {
        reportTaskProgress({
          phase: "post_upload_readiness_wait",
          route: {
            url: String(tab?.url || ""),
            title: String(tab?.title || ""),
            path: "",
          },
          actions,
        });
        const readinessResult = normalizeCompositeUploadReadyResult(
          await runCompositePhase(platform, "post_upload_readiness", () =>
          ensureCompositeUploadReady(
            client,
            platform,
            content,
            uploadReadinessTimeoutMs,
            (state) => reportTaskProgress({
              phase: "post_upload_readiness_poll",
              route: {
                url: String(tab?.url || ""),
                title: String(tab?.title || ""),
                path: "",
              },
              visible_lines: Array.isArray(state?.last?.lines) ? state.last.lines : [],
              material_integrity: {
                upload_readiness: {
                  ready: Boolean(state?.ready),
                  failed: Boolean(state?.failed),
                  waited_ms: Number(state?.waited_ms || 0),
                  busy: Boolean(state?.last?.busy),
                  media_present: Boolean(state?.last?.mediaPresent),
                  upload_prompt_only: Boolean(state?.last?.uploadPromptOnly),
                  file_input_count: Number(state?.last?.fileInputCount || 0),
                  last_lines: Array.isArray(state?.last?.lines) ? state.last.lines.slice(0, 50) : [],
                },
              },
              actions,
            }),
            {
              syntheticUploadExpected: Boolean(upload.uploaded),
            },
          )),
        );
        const readiness = readinessResult.readiness;
        actions.push(...readinessResult.actions);
        reportTaskProgress({
          phase: "post_upload_readiness_done",
          route: {
            url: String(tab?.url || ""),
            title: String(tab?.title || ""),
            path: "",
          },
          actions,
        });
        if (!readiness.ready) {
          if (readiness.failed) {
            const uploadFailureCode = `${platform}_media_upload_failed`;
            const uploadFailureReason = String(readiness.failure_reason || "upload_failed").trim() || "upload_failed";
            return {
              status: "needs_human",
              result: _attach_publication_content_signature({
                platform,
                route: { url: snapshot?.url || tab?.url || "", title: snapshot?.title || tab?.title || "" },
                actions,
                publication_audit: {},
                publication_field_snapshot: {},
                final_publish: {
                  pre_publish_pending: false,
                  wait_for_upload_ready: false,
                  prepublish_only_current_page: prepublishOnlyCurrentPage,
                  prepare_only_current_page: prepareOnlyCurrentPage,
                  stop_before_final_publish: stopBeforeFinalPublish,
                },
                material_integrity: buildPendingUploadMaterialIntegrity(
                  platform,
                  readiness,
                  {
                    url: String(snapshot?.url || tab?.url || ""),
                    title: String(snapshot?.title || tab?.title || ""),
                  },
                ),
                ..._build_publication_recovery_hint({
                  platform,
                  code: uploadFailureCode,
                  reason: "媒体上传未真正挂载到发布页，已阻断后续字段填充与发布。",
                  route: { url: snapshot?.url || tab?.url || "", title: snapshot?.title || tab?.title || "" },
                  actionHistory: actions.slice(0, 80),
                  visibleLines: (snapshot?.lines || []).slice(0, 120),
                  clearDraftContext: stopBeforeFinalPublish ? false : true,
                  forceRefresh: true,
                  blockers: [{
                    code: uploadFailureCode,
                    message: "文件输入已触发，但页面未进入可继续上传/编辑的状态。",
                    details: JSON.stringify({
                      failure_reason: uploadFailureReason,
                      media_path: mediaPath || "",
                      route_url: String(snapshot?.url || tab?.url || ""),
                    }),
                  }],
                }).recovery,
                interruptions,
              }, content),
              error: {
                code: uploadFailureCode,
                message: `媒体上传未生效：${uploadFailureReason}`,
                details: {
                  failure_reason: uploadFailureReason,
                  route_url: String(snapshot?.url || tab?.url || ""),
                },
              },
            };
          }
          snapshot = await pageSnapshot(client);
          const pendingUploadIntegrity = buildPendingUploadMaterialIntegrity(
            platform,
            readiness,
            {
              url: String(snapshot?.url || tab?.url || ""),
              title: String(snapshot?.title || tab?.title || ""),
            },
          );
          reportTaskProgress({
            phase: "post_upload_readiness_pending",
            route: {
              url: String(snapshot?.url || tab?.url || ""),
              title: String(snapshot?.title || tab?.title || ""),
              path: "",
            },
            material_integrity: pendingUploadIntegrity,
            visible_lines: (snapshot?.lines || []).slice(0, 120),
            actions,
          });
          return {
            status: "processing",
            result: buildCompositeUploadPendingProcessingEnvelope({
              platform,
              route: { url: snapshot?.url || tab?.url || "", title: snapshot?.title || tab?.title || "" },
              actions,
              material_integrity: pendingUploadIntegrity,
              code: `${platform}_pre_publish_upload_pending`,
              reason: "媒体上传已开始，继续保留现场等待平台进入可编辑上传态。",
              blockerMessage: `预发布等待上传完成：${pendingUploadIntegrity.verification_reason || "upload_ready"}`,
              blockerDetails: `verification_reason=${pendingUploadIntegrity.verification_reason || "upload_not_ready"}`,
              prepublishOnlyCurrentPage,
              prepareOnlyCurrentPage,
              stopBeforeFinalPublish,
              interruptions,
              content,
            }),
            error: null,
          };
        }
        reportTaskProgress({
          phase: "post_upload_material_integrity_wait",
          route: {
            url: String(tab?.url || ""),
            title: String(tab?.title || ""),
            path: "",
          },
          actions,
        });
        const postUploadIntegrity = await runCompositePhase(
          platform,
          "post_upload_material_integrity",
          () => readCompositeMaterialIntegrity(client, platform, content),
        );
        actions.push({ kind: "post_upload_material_integrity", ...postUploadIntegrity });
        snapshot = await pageSnapshot(client);
        reportTaskProgress({
          phase: "post_upload_integrity",
          route: {
            url: String(snapshot?.url || tab.url || ""),
            title: String(snapshot?.title || tab.title || ""),
            path: "",
          },
          material_integrity: postUploadIntegrity,
          visible_lines: (snapshot?.lines || []).slice(0, 120),
          actions,
        });
        if (
          waitForPublishConfirmation
          && postUploadIntegrity
          && postUploadIntegrity.verification_state !== "ready"
        ) {
          const uploadIntegrityDisposition = deriveCompositePostUploadIntegrityDisposition(
            platform,
            postUploadIntegrity,
            null,
          );
          if (uploadIntegrityDisposition.status === "processing") {
            return {
              status: "processing",
              result: buildCompositeUploadPendingProcessingEnvelope({
                platform,
                route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
                actions,
                material_integrity: postUploadIntegrity,
                code: uploadIntegrityDisposition.code,
                reason: "预发布字段已修复，仅剩上传就绪等待态，继续保留现场自动等待。",
                blockerMessage: `预发布等待上传完成：${uploadIntegrityDisposition.remaining.join(",") || "upload_ready"}`,
                blockerDetails: `post_upload_wait_only=${uploadIntegrityDisposition.remaining.join(",") || "upload_ready"}`,
                prepublishOnlyCurrentPage,
                prepareOnlyCurrentPage,
                stopBeforeFinalPublish,
                interruptions,
                content,
              }),
              error: null,
            };
          }
          return {
            status: "needs_human",
            result: _attach_publication_content_signature({
              platform,
              route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
              actions,
              ..._build_publication_recovery_hint({
                platform,
                code: uploadIntegrityDisposition.code,
                reason: "上传后复核未进入可编辑状态。",
                route: { url: snapshot?.url || tab.url || "", title: snapshot?.title || tab.title || "" },
                actionHistory: actions.slice(0, 80),
                visibleLines: (snapshot?.lines || []).slice(0, 120),
                clearDraftContext: uploadIntegrityDisposition.clear_draft_context,
                forceRefresh: uploadIntegrityDisposition.force_publish_page_refresh,
                blockers: [{
                  code: uploadIntegrityDisposition.code,
                  message: "上传后读回不是就绪态，建议重置草稿后重试。",
                  details: `verification_state=${postUploadIntegrity.verification_state || "unknown"} failures=${JSON.stringify(postUploadIntegrity.failures || [])}`,
                }],
              }).recovery,
              interruptions,
            }, content),
            error: {
              code: uploadIntegrityDisposition.code,
              message: `已上传素材，但发布页未回到可编辑上传态（verification_state=${postUploadIntegrity.verification_state || "unknown"}）。`,
              details: {
                verification_state: postUploadIntegrity.verification_state || "unknown",
                failures: postUploadIntegrity.failures || [],
                visibility: postUploadIntegrity.verification_state || "",
              },
            },
          };
        }
      } else {
        await sleep(16000);
      }
    } else {
      actions.push({ kind: "media_upload", uploaded: Boolean(mediaPath), skipped: true, reason: mediaPath ? "media_already_present" : "missing_media_path" });
      reportTaskProgress({
        phase: "media_already_present",
        route: {
          url: String(snapshot?.url || tab.url || ""),
          title: String(snapshot?.title || tab.title || ""),
          path: "",
        },
        visible_lines: (snapshot?.lines || []).slice(0, 120),
        actions,
      });
    }
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_upload")));
    let platformVerifier = null;
    let bilibiliCoverAction = null;
    if (platform === "bilibili") {
      const coverAction = await setBilibiliCoverImage(client, content.cover_path || content.copy_material?.cover_path || "");
      bilibiliCoverAction = coverAction;
      actions.push(coverAction);
      platformVerifier = await setBilibiliDraftFields(client, content);
      actions.push(platformVerifier);
    } else {
      reportTaskProgress({
        phase: "dispatch_platform_adapter",
        route: {
          url: String(tab?.url || ""),
          title: String(tab?.title || ""),
          path: "",
        },
        actions,
      });
      return _attach_publication_signature_to_task_result(
        await runCompositePlatformAdapter(client, tab, platform, content, actions, {
          verify_media_upload: verifyMediaUpload,
          wait_for_publish_confirmation: waitForPublishConfirmation,
          capture_response_timeout_ms: captureResponseTimeoutMs,
          stop_before_final_publish: stopBeforeFinalPublish,
          prepublish_only_current_page: prepublishOnlyCurrentPage,
          prepare_only_current_page: prepareOnlyCurrentPage,
          task_created_at: task.created_at,
          task_progress: reportTaskProgress,
        }),
        content,
      );
    }
    const postFillExpandTexts = platform === "bilibili" ? [] : (PLATFORM_EXPAND_TEXTS[platform] || ["更多设置", "展开"]);
    for (const text of postFillExpandTexts) {
      const action = await clickByText(client, [text]);
      actions.push(action);
      if (action.clicked) {
        await sleep(900);
        interruptions.push(...(await dismissInterruptions(client, tab, platform, `task_expand_${text}`)));
      }
    }
    snapshot = await pageSnapshot(client);
    const bilibiliPublicationAudit = platform === "bilibili"
      ? buildBilibiliPublicationAudit(
        content,
        platformVerifier,
        {},
        { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" },
        bilibiliCoverAction,
        { stop_before_final_publish: stopBeforeFinalPublish },
      )
      : null;
    const result = _attach_publication_content_signature({
      draft_url: snapshot.url || tab.url || "",
      route: { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" },
      composite_framework: platform === "bilibili"
        ? {
            enabled: true,
            platform,
            framework_id: dedicatedCompositeFrameworkId("bilibili"),
            dedicated_platform_framework: true,
            legacy_lightweight_script_used: false,
            material_integrity: platformVerifier || {},
        }
        : undefined,
      publication_audit: bilibiliPublicationAudit || undefined,
      publication_field_snapshot: bilibiliPublicationAudit
        ? buildPublicationFieldSnapshotFromAudit(
          platform,
          content,
          bilibiliPublicationAudit,
          { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" },
        )
        : undefined,
      actions: actions.slice(0, 80),
      interruptions: interruptions.slice(0, 80),
      visible_option_lines: (snapshot.lines || [])
        .filter((line) => /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category/i.test(line))
        .slice(0, 120),
    }, content);
    if (platform === "bilibili" && stopBeforeFinalPublish && platformVerifier?.verified) {
      reportTaskProgress({
        phase: "pre_publish_verified_stop_before_final_publish",
        route: {
          url: String(result.route?.url || ""),
          title: String(result.route?.title || ""),
          path: "",
        },
        publication_audit: result.publication_audit,
        publication_field_snapshot: result.publication_field_snapshot,
        visible_lines: (snapshot.lines || []).slice(0, 120),
      });
      return {
        status: "verified",
        result: _attach_publication_content_signature({
          ...result,
          final_publish: {
            ...(result.final_publish || {}),
            prepublish_only_current_page: prepublishOnlyCurrentPage,
            prepare_only_current_page: prepareOnlyCurrentPage,
            stop_before_final_publish: true,
          },
        }, content),
        error: null,
      };
    }
    if (!LIVE_PUBLISH_ENABLED) {
      return {
        status: "needs_human",
        result,
        ..._build_publication_recovery_hint({
          platform,
          code: "live_publish_disabled",
          reason: "live publish 开关未开启。",
          route: { url: result.route?.url || "", title: result.route?.title || "" },
          actionHistory: actions,
          forceRefresh: false,
          blockers: [{ code: "live_publish_disabled", message: "环境未启用 live publish。", details: "请开启 PUBLICATION_LIVE_PUBLISH_ENABLED 后重试。" }],
        }).recovery,
        error: {
          code: "live_publish_disabled",
          message: "任务已完成草稿准备，但 PUBLICATION_LIVE_PUBLISH_ENABLED 未开启，已停止在人工确认前。",
        },
      };
    }
    if (!FINAL_PUBLISH_PLATFORMS.has(platform)) {
      return {
        status: "needs_human",
        result,
        ..._build_publication_recovery_hint({
          platform,
          code: "live_publish_executor_not_implemented",
          reason: `${platform} 未实现最终发布点击器。`,
          route: { url: result.route?.url || "", title: result.route?.title || "" },
          actionHistory: actions,
          forceRefresh: false,
          blockers: [{ code: "live_publish_executor_not_implemented", message: `尚未接入 ${platform} 最终发布流程。`, details: "发布链路在草稿完成后人工确认。"}],
        }).recovery,
        error: {
          code: "live_publish_executor_not_implemented",
          message: `任务已完成草稿准备，但 ${platform} 最终预约/发布点击器尚未实现，已停止在人工确认前。`,
        },
      };
    }
    if (platform === "bilibili" && stopBeforeFinalPublish && !platformVerifier?.verified) {
      const mediaEntryDisposition = deriveDedicatedVerifierMediaEntryDisposition(platform, platformVerifier, mediaPath);
      if (mediaEntryDisposition) {
        const route = { url: result.route?.url || "", title: result.route?.title || "" };
        const blockers = [{
          code: mediaEntryDisposition.code,
          message: mediaEntryDisposition.pending
            ? "B站当前页仍停留在视频上传入口，等待目标媒体挂载完成后再继续字段验证。"
            : "B站当前页仍停留在视频上传入口，安全模式不会自动补上传。",
          details: JSON.stringify({
            media_path: mediaPath || "",
            media_reuse_reason: mediaEntryDisposition.media_reuse_reason || "",
            media_already_present: false,
          }),
        }];
        if (mediaEntryDisposition.pending) {
          return {
            status: "processing",
            result: _attach_publication_content_signature({
              ...result,
              final_publish: {
                ...(result.final_publish || {}),
                pre_publish_pending: true,
                wait_for_upload_ready: true,
                stop_before_final_publish: true,
                prepare_only_current_page: prepareOnlyCurrentPage,
                prepublish_only_current_page: prepublishOnlyCurrentPage,
              },
              material_integrity: {
                verification_state: "pending",
                verification_reason: "publish_media_entry",
                failures: ["upload_ready"],
              },
              ..._build_publication_recovery_hint({
                platform,
                code: mediaEntryDisposition.code,
                reason: "安全预发布验证模式已进入 B站媒体入口，等待目标媒体挂载完成后再继续字段验证。",
                route,
                actionHistory: actions,
                clearDraftContext: false,
                forceRefresh: true,
                recoveryOverrides: {
                  recovery_mode: recoveryContext.recovery_mode || "prepublish_resume",
                  prepare_only_current_page: prepareOnlyCurrentPage,
                  prepublish_only_current_page: prepublishOnlyCurrentPage,
                  verify_media_upload: verifyMediaUpload,
                  wait_for_publish_confirmation: waitForPublishConfirmation,
                },
                blockers,
              }).recovery,
            }, content),
            error: null,
          };
        }
        return {
          status: "needs_human",
          result,
          ..._build_publication_recovery_hint({
            platform,
            code: mediaEntryDisposition.code,
            reason: "B站安全预发布验证模式未检测到目标媒体，停止在上传入口。",
            route,
            actionHistory: actions,
            clearDraftContext: false,
            forceRefresh: true,
            recoveryOverrides: {
              recovery_mode: recoveryContext.recovery_mode || "prepublish_resume",
              prepare_only_current_page: prepareOnlyCurrentPage,
              prepublish_only_current_page: prepublishOnlyCurrentPage,
              verify_media_upload: verifyMediaUpload,
              wait_for_publish_confirmation: waitForPublishConfirmation,
            },
            blockers,
          }).recovery,
          error: {
            code: mediaEntryDisposition.code,
            message: "B站当前页仍停留在视频上传入口，安全模式不会自动补上传。",
            details: {
              media_path: mediaPath || "",
              media_reuse_reason: mediaEntryDisposition.media_reuse_reason || "",
            },
          },
        };
      }
    }
    if (platform === "bilibili" && !platformVerifier?.verified) {
      return {
        status: "needs_human",
        result,
        ..._build_publication_recovery_hint({
          platform,
          code: "bilibili_pre_publish_verification_failed",
          reason: "B站发布前字段读回未通过。",
          route: { url: result.route?.url || "", title: result.route?.title || "" },
          actionHistory: actions,
          visibleLines: snapshot?.lines || [],
          clearDraftContext: true,
          forceRefresh: true,
          blockers: [{ code: "bilibili_pre_publish_verification_failed", message: "字段读回未通过", details: String((platformVerifier?.failures || []).join(",")) }],
        }).recovery,
        error: {
          code: "bilibili_pre_publish_verification_failed",
          message: `B站字段读回校验未通过：${(platformVerifier?.failures || []).join(", ") || "unknown"}`,
          details: platformVerifier || {},
        },
      };
    }
    if (platform === "bilibili") {
      const finalOutcome = await finalizeBilibiliPublish(client, content);
      result.final_publish = finalOutcome.result?.final_publish || {};
      result.publication_audit = buildBilibiliPublicationAudit(
        content,
        platformVerifier,
        result.final_publish,
        result.route,
        bilibiliCoverAction,
        { stop_before_final_publish: false },
      );
      result.publication_field_snapshot = buildPublicationFieldSnapshotFromAudit(
        platform,
        content,
        result.publication_audit,
        result.route,
      );
      return {
        status: finalOutcome.status,
        result,
        error: finalOutcome.error,
      };
    }
      return {
        status: "needs_human",
        result,
        ..._build_publication_recovery_hint({
          platform,
          code: "live_publish_executor_not_implemented",
          reason: "该平台未接入最终发布点击器。",
          route: { url: result.route?.url || "", title: result.route?.title || "" },
          actionHistory: actions,
          forceRefresh: false,
          blockers: [{ code: "live_publish_executor_not_implemented", message: "未接入该平台最终发布执行器，需人工发布确认。", details: platform }],
        }).recovery,
        error: {
          code: "live_publish_executor_not_implemented",
          message: "任务已完成草稿准备，但该平台最终预约/发布点击器尚未实现，已停止在人工确认前。",
        },
      };
  } catch (error) {
    const timeoutEnvelope = currentPageSafeMode && isCdpRuntimeEvaluationTimeout(error)
      ? deriveCompositeCdpTimeoutWaitEnvelope({
          platform,
          route: currentRouteHint,
          content,
          actions,
          error,
          prepublishOnlyCurrentPage,
          prepareOnlyCurrentPage,
          stopBeforeFinalPublish,
        })
      : null;
    if (timeoutEnvelope) {
      return {
        status: "processing",
        result: timeoutEnvelope,
        error: null,
      };
    }
    throw error;
  } finally {
    client.close();
  }
}

function serializeTask(task) {
  const identity = task.identity && typeof task.identity === "object" ? task.identity : {};
  return {
    task_id: task.task_id,
    id: task.task_id,
    platform: task.platform,
    profile_id: task.profile_id,
    attempt_id: identity.attempt_id || null,
    content_id: identity.content_id || null,
    carry_over_from_attempt_id: identity.carry_over_from_attempt_id || null,
    attempt_backed: Boolean(identity.attempt_backed),
    content_signature: identity.content_signature || null,
    publication_content_signature: identity.publication_content_signature || null,
    publication_plan_signature: identity.publication_plan_signature || null,
    recovery_mode: identity.recovery_mode || null,
    status: task.status,
    created_at: task.created_at,
    updated_at: task.updated_at,
    scheduled_publish_at: task.content?.scheduled_publish_at || null,
    progress: task.progress || null,
    result: task.result || {},
    error: task.error || null,
  };
}

function _isNonEmptyObject(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).length > 0);
}

function _hasNonEmptyRoute(value) {
  if (!_isNonEmptyObject(value)) return false;
  return Boolean(String(value.url || "").trim() || String(value.title || "").trim() || String(value.path || "").trim());
}

function _mergeTaskProgressValue(previousValue, nextValue, { preserveEmptyArray = false } = {}) {
  if (Array.isArray(nextValue)) {
    if (nextValue.length > 0) return nextValue;
    if (preserveEmptyArray) return nextValue;
    return Array.isArray(previousValue) ? previousValue : [];
  }
  if (_isNonEmptyObject(nextValue)) return nextValue;
  if (nextValue && typeof nextValue === "object") {
    if (_isNonEmptyObject(previousValue)) return previousValue;
    return nextValue;
  }
  if (typeof nextValue === "string") {
    return String(nextValue).trim() ? nextValue : (typeof previousValue === "string" ? previousValue : "");
  }
  if (typeof nextValue === "number") return Number.isFinite(nextValue) ? nextValue : previousValue;
  if (typeof nextValue === "boolean") return nextValue;
  if (nextValue === undefined || nextValue === null) return previousValue;
  return nextValue;
}

export function mergePublicationTaskProgress(currentProgress = {}, patch = {}) {
  const current = currentProgress && typeof currentProgress === "object" ? currentProgress : {};
  const next = patch && typeof patch === "object" ? patch : {};
  const merged = {
    ...current,
    ...next,
  };
  merged.route = _hasNonEmptyRoute(next.route)
    ? next.route
    : (_hasNonEmptyRoute(current.route) ? current.route : (next.route && typeof next.route === "object" ? next.route : {}));
  merged.visible_lines = _mergeTaskProgressValue(current.visible_lines, next.visible_lines);
  merged.material_integrity = _mergeTaskProgressValue(current.material_integrity, next.material_integrity);
  merged.publication_audit = _mergeTaskProgressValue(current.publication_audit, next.publication_audit);
  merged.publication_field_snapshot = _mergeTaskProgressValue(current.publication_field_snapshot, next.publication_field_snapshot);
  merged.final_publish = _mergeTaskProgressValue(current.final_publish, next.final_publish);
  merged.visual_evidence = _mergeTaskProgressValue(current.visual_evidence, next.visual_evidence);
  merged.actions = _mergeTaskProgressValue(current.actions, next.actions);
  return merged;
}

function updatePublicationTaskProgress(task, patch = {}) {
  if (!task || typeof task !== "object" || !patch || typeof patch !== "object") return;
  const current = task.progress && typeof task.progress === "object" ? task.progress : {};
  task.progress = {
    ...mergePublicationTaskProgress(current, patch),
    updated_at: new Date().toISOString(),
  };
}

export function buildPublicationTaskTimeoutEvidence(task) {
  const progress = task?.progress && typeof task.progress === "object" ? task.progress : {};
  const route = progress.route && typeof progress.route === "object" ? progress.route : {};
  return {
    phase: String(progress.phase || ""),
    route: {
      url: String(route.url || ""),
      title: String(route.title || ""),
      path: String(route.path || ""),
    },
    publication_audit: progress.publication_audit && typeof progress.publication_audit === "object"
      ? progress.publication_audit
      : {},
    publication_field_snapshot: progress.publication_field_snapshot && typeof progress.publication_field_snapshot === "object"
      ? progress.publication_field_snapshot
      : {},
    final_publish: progress.final_publish && typeof progress.final_publish === "object"
      ? progress.final_publish
      : {},
    material_integrity: progress.material_integrity && typeof progress.material_integrity === "object"
      ? progress.material_integrity
      : {},
    visual_evidence: normalizeVisualEvidence(progress.visual_evidence),
    visible_lines: Array.isArray(progress.visible_lines) ? progress.visible_lines.slice(0, 120) : [],
    updated_at: String(progress.updated_at || ""),
  };
}

function reportTaskPreparationStage(task, patch = {}) {
  updatePublicationTaskProgress(task, {
    phase: String(patch.phase || ""),
    route: patch.route && typeof patch.route === "object" ? patch.route : {},
    visible_lines: Array.isArray(patch.visible_lines) ? patch.visible_lines.slice(0, 120) : [],
    material_integrity: patch.material_integrity && typeof patch.material_integrity === "object" ? patch.material_integrity : {},
    publication_audit: patch.publication_audit && typeof patch.publication_audit === "object" ? patch.publication_audit : {},
    publication_field_snapshot: patch.publication_field_snapshot && typeof patch.publication_field_snapshot === "object" ? patch.publication_field_snapshot : {},
    final_publish: patch.final_publish && typeof patch.final_publish === "object" ? patch.final_publish : {},
    visual_evidence: normalizeVisualEvidence(patch.visual_evidence),
    actions: Array.isArray(patch.actions) ? patch.actions.slice(0, 40) : undefined,
  });
}

function startPublicationTask(payload) {
  const taskId = String(payload.task_id || payload.id || randomUUID()).trim();
  const taskContent = coerceTaskContentWithRecoveryPayload(payload);
  const taskIdentity = extractPublicationTaskIdentity(payload, taskContent);
  const task = {
    task_id: taskId,
    platform: normalizePlatform(payload.platform),
    profile_id: String(payload.profile_id || ""),
    content: taskContent,
    identity: taskIdentity,
    reconcile_callback_url: String(payload.reconcile_callback_url || "").trim(),
    recovery_context: _extract_publication_recovery_context(
      taskContent,
    ),
    task_execution_timeout_ms: _coerceRecoveryTimeoutMs(payload.task_execution_timeout_ms, 0),
    status: "queued",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    result: {},
    error: null,
    timeout_pending: false,
  };
  TASKS.set(taskId, task);
  queueMicrotask(async () => {
    task.status = "processing";
    task.updated_at = new Date().toISOString();
    try {
      const executionTimeout = derivePublicationTaskExecutionTimeoutMs(task);
      const executionPromise = (async () => {
        const outcome = await preparePublicationTask(task);
        return { ...outcome, __timeout: false };
      })();
      executionPromise
        .then((lateOutcome) => {
          reconcileTimedOutPublicationTask(task, lateOutcome);
        })
        .catch((lateError) => {
          if (!task.timeout_pending) return;
          task.status = "failed";
          task.error = {
            code: "browser_agent_task_failed",
            message: String(lateError?.message || lateError),
            details: {
              platform: lateError?.publicationPlatform || task.platform,
              phase: lateError?.publicationPhase || "unknown",
              late_reconcile: true,
            },
          };
          task.timeout_pending = false;
          task.updated_at = new Date().toISOString();
        });
      const timedResult = await Promise.race([
        executionPromise,
        (async () => {
          await sleep(executionTimeout);
          return { __timeout: true };
        })(),
      ]);
      if (timedResult && timedResult.__timeout) {
        task.timeout_pending = true;
        task.status = derivePublicationTaskTimeoutStatus(task);
        const timeoutEvidence = buildPublicationTaskTimeoutEvidence(task);
        const timeoutHint = _build_publication_recovery_hint({
          platform: task.platform,
          code: "publication_task_timeout",
          reason: `发布任务执行超过 ${executionTimeout}ms，疑似流程卡住。`,
          route: timeoutEvidence.route,
          actionHistory: [{ kind: "publication_task_timeout", timeout_ms: executionTimeout }],
          clearDraftContext: false,
          forceRefresh: true,
          visibleLines: timeoutEvidence.visible_lines,
          blockers: [{
            code: "publication_task_timeout",
            message: `任务执行已超过 ${executionTimeout}ms，未返回最终发布结果。`,
            details: `task_id=${task.task_id}, platform=${task.platform}, phase=${timeoutEvidence.phase || "unknown"}`,
          }],
        });
        task.result = _attach_publication_content_signature({
          platform: task.platform,
          route: timeoutEvidence.route,
          content_signature: _extract_publication_content_signature(task.content),
          publication_content_signature: _extract_publication_content_signature(task.content),
          publication_plan_signature: _extract_publication_content_signature(task.content),
          actions: [{ kind: "publication_task_timeout", timeout_ms: executionTimeout }],
          publication_audit: timeoutEvidence.publication_audit,
          publication_field_snapshot: timeoutEvidence.publication_field_snapshot,
          final_publish: timeoutEvidence.final_publish,
          material_integrity: timeoutEvidence.material_integrity,
          visual_evidence: timeoutEvidence.visual_evidence,
          timeout_progress: timeoutEvidence,
          ...timeoutHint.recovery,
        }, task.content);
        task.error = {
          code: "publication_task_timeout",
          message: `发布任务执行超时（${executionTimeout}ms）`,
          details: {
            task_id: task.task_id,
            platform: task.platform,
            timeout_ms: executionTimeout,
          },
        };
      } else {
        const outcome = timedResult || {};
        task.timeout_pending = false;
        task.status = outcome.status || "needs_human";
        task.result = outcome.result || {};
        task.error = outcome.error || null;
      }
    } catch (error) {
      task.status = "failed";
      task.error = {
        code: "browser_agent_task_failed",
        message: error.message,
        details: {
          platform: error.publicationPlatform || task.platform,
          phase: error.publicationPhase || "unknown",
        },
      };
    } finally {
      task.updated_at = new Date().toISOString();
      schedulePublicationTaskReconcileCallback(task);
    }
  });
  return task;
}

const PLATFORM_EXPAND_TEXTS = {
  douyin: ["作品描述", "添加话题", "合集", "选择合集", "原创", "声明", "谁可以看", "定时发布", "高级设置", "更多设置"],
  bilibili: ["分区", "生活兴趣", "加入合集", "请选择合集", "创作声明", "更多设置"],
  xiaohongshu: ["选择合集", "原创声明", "添加内容类型声明", "选择群聊", "公开可见", "定时发布", "更多设置"],
  youtube: ["选择", "不，内容不是面向儿童的", "展开", "更多选项", "公开范围"],
  kuaishou: ["作品分类", "分类", "合集", "定时发布", "更多设置"],
  "wechat-channels": ["发表视频", "上传视频", "合集", "活动", "声明", "谁可以看", "定时发表"],
  toutiao: ["发布视频", "上传视频", "分类", "合集", "原创", "声明", "定时发布"],
  x: ["Schedule post", "Post settings"],
};

async function probeTabInventory(tab, platform, payload) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  const snapshots = [];
  const actions = [];
  const interruptions = [];
  const contentSample = payload.content_sample && typeof payload.content_sample === "object" ? payload.content_sample : {};
  const mediaPath = String(contentSample.media_path || "").trim();
  const recoveryContext = _extract_publication_recovery_context(contentSample);
  const allowDraftUpload = String(payload.mode || "").includes("draft_upload") && mediaPath;
  const summaryOnly = Boolean(payload.summary_only);
  const forceUploadRefresh = Boolean(allowDraftUpload && (recoveryContext.clear_draft_context || recoveryContext.force_publish_page_refresh));
  let upload = { uploaded: false, reason: allowDraftUpload ? "not_attempted" : "upload_probe_not_requested" };
  try {
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_probe")));
    if (summaryOnly) {
      let summarySnapshot = await pageSnapshot(client);
      const initialRouteReadiness = deriveProbeInventoryRouteReadiness(platform, summarySnapshot);
      if (
        platform === "xiaohongshu"
        || platform === "youtube"
        || initialRouteReadiness.blocked
      ) {
        const routeAction = await ensurePlatformPublishRoute(client, tab, platform, {
          force_publish_page_refresh: true,
          prefer_draft_list_surface: platform === "youtube",
        }).catch((error) => ({
          navigated: false,
          verified: false,
          reason: "probe_summary_route_bootstrap_error",
          error: String(error?.message || error || "").trim(),
        }));
        actions.push({ kind: "probe_summary_route_bootstrap", ...routeAction });
        if (routeAction?.navigated || routeAction?.verified) {
          await sleep(1600);
          summarySnapshot = await pageSnapshot(client);
        }
      }
      const summaryResume = await resolveCurrentPageDraftResumePrompt(client, platform).catch((error) => ({
        attempted: false,
        resumed: false,
        prompt_present: false,
        reason: "draft_resume_prompt_error",
        error: String(error?.message || error || "").trim(),
      }));
      if (summaryResume.attempted || summaryResume.reason === "draft_resume_prompt_error") {
        actions.push({ kind: "draft_resume_prompt", ...summaryResume });
      }
      if (summaryResume.resumed || summaryResume.attempted) {
        await sleep(1400);
        summarySnapshot = await pageSnapshot(client);
      }
      const snapshot = await attachVisualEvidenceToSnapshot(
        client,
        summarySnapshot,
        {
          platform,
          captureVisualEvidence: true,
          visualEvidencePhase: "probe_inventory",
        },
      );
      return {
        snapshot,
        probe_meta: {
          summary_only: true,
          draft_upload_requested: false,
          upload: { uploaded: false, reason: "summary_only" },
          actions: actions.filter((action) => action && action.kind).slice(0, 20),
          interruptions: interruptions.slice(0, 20),
        },
      };
    }
    if (platform === "youtube" && allowDraftUpload) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_youtube_create")));
      actions.push(await clickByText(client, ["创建", "上传视频", "Upload videos", "CREATE"]));
      await sleep(2500);
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_youtube_create")));
    }
    let current = await pageSnapshot(client);
    snapshots.push(current);
    if (forceUploadRefresh) {
      const routeAction = await ensurePlatformPublishRoute(client, tab, platform, { force_publish_page_refresh: true });
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "during_probe_route_refresh")));
      if (routeAction?.navigated) {
        interruptions.push({ kind: "probe_route_refresh", ...routeAction });
        current = await pageSnapshot(client);
      }
    }
    if (allowDraftUpload && forceUploadRefresh) {
      const clearAction = await clearInPageDraftState(client, platform, {
        mediaPath,
        clearIfStaleDraft: true,
      }).catch((error) => ({
        platform,
        cleared: false,
        before_media_hint: false,
        after_media_hint: false,
        before_draft_hint: false,
        after_draft_hint: false,
        actions: [{ kind: "draft_clear_error", reason: String(error?.message || error) }],
        before_url: String(tab?.url || ""),
        after_url: String(tab?.url || ""),
        error: String(error?.message || error),
      }));
      interruptions.push({ kind: "draft_state_clear", ...clearAction });
      if (clearAction?.cleared) await sleep(1400);
      current = await pageSnapshot(client);
    }
    if (allowDraftUpload && (forceUploadRefresh || !pageAlreadyHasMedia(current, mediaPath))) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_file_upload")));
      upload = await setFirstVideoFileInput(client, mediaPath);
      if (!upload.uploaded) {
        interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_upload_button")));
        actions.push(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发布视频"]));
        await sleep(2500);
        interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_upload_button")));
        upload = await setFirstVideoFileInput(client, mediaPath);
      }
      await sleep(upload.uploaded ? 18000 : 3000);
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_file_upload")));
      current = await pageSnapshot(client);
      snapshots.push(current);
    } else if (allowDraftUpload) {
      upload = { uploaded: true, skipped: true, reason: "media_already_present" };
    }
    for (const text of PLATFORM_EXPAND_TEXTS[platform] || ["更多设置", "展开"]) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, `before_expand_${text}`)));
      const action = await clickByText(client, [text]);
      actions.push(action);
      if (action.clicked) {
        await sleep(1400);
        snapshots.push(await pageSnapshot(client));
        interruptions.push(...(await dismissInterruptions(client, tab, platform, `after_expand_${text}`)));
        snapshots.push(await pageSnapshot(client));
      }
    }
    const merged = await attachVisualEvidenceToSnapshot(
      client,
      mergedSnapshot(snapshots),
      {
        platform,
        captureVisualEvidence: true,
        visualEvidencePhase: "probe_inventory",
      },
    );
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_api_inventory")));
    merged.api_option_groups = await collectPlatformApiInventory(client, platform);
    merged.framework_inventory = await collectFrameworkInventory(client, platform);
    merged.framework_option_groups = merged.framework_inventory.option_groups || [];
    return {
      snapshot: merged,
      probe_meta: {
        draft_upload_requested: Boolean(allowDraftUpload),
        upload,
        actions: actions.filter((action) => action.clicked).slice(0, 20),
        interruptions: interruptions.slice(0, 60),
      },
    };
  } finally {
    client.close();
  }
}

async function collectFrameworkInventory(client, platform) {
  const expression = `(() => {
    const platform = ${JSON.stringify(platform)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const labelOf = (item) => clean(item?.name || item?.title || item?.label || item?.text || item?.value);
    const idOf = (item) => item?.id ?? item?.tid ?? item?.typeid ?? item?.value ?? item?.key ?? "";
    const uniqueGroups = new Map();
    const components = [];
    const addGroup = (key, label, options, values = [], source = "framework_state") => {
      const cleanedOptions = [...new Set((options || []).map((item) => clean(item)).filter(Boolean))].slice(0, 220);
      if (!cleanedOptions.length) return;
      const existing = uniqueGroups.get(key);
      const next = {
        key,
        label,
        source,
        options: cleanedOptions,
        values: (values || []).slice(0, 220),
      };
      if (existing) {
        existing.options = [...new Set([...existing.options, ...next.options])].slice(0, 220);
        existing.values = [...(existing.values || []), ...(next.values || [])].slice(0, 220);
      } else {
        uniqueGroups.set(key, next);
      }
    };
    const summarizeValues = (value, path) => {
      if (!Array.isArray(value) || value.length < 2 || value.length > 300) return;
      const objects = value.filter((item) => item && typeof item === "object");
      if (!objects.length) return;
      const optionObjects = objects
        .map((item) => ({
          id: idOf(item),
          name: labelOf(item),
          path: clean(item.path || item.full_name || item.fullName || ""),
          raw_keys: Object.keys(item).slice(0, 12),
        }))
        .filter((item) => item.name);
      if (optionObjects.length < 2) return;
      addGroup(
        \`\${platform}_framework_\${path.replace(/[^a-z0-9_]+/gi, "_").slice(0, 48)}\`,
        \`组件状态候选：\${path}\`,
        optionObjects.map((item) => item.path || item.name),
        optionObjects,
      );
    };
    const scanObject = (value, prefix, depth = 0, seen = new Set()) => {
      if (!value || typeof value !== "object" || seen.has(value) || depth > 2) return;
      seen.add(value);
      for (const [key, child] of Object.entries(value)) {
        if (key.startsWith("_") && !["_props", "_data"].includes(key)) continue;
        const path = prefix ? \`\${prefix}.\${key}\` : key;
        summarizeValues(child, path);
        if (child && typeof child === "object" && !Array.isArray(child)) scanObject(child, path, depth + 1, seen);
      }
    };
    const frameworkSelectors = [
      ".video-human-type",
      ".video-season-select",
      ".time-switch-wrp",
      ".d-time-container",
      "[class*=select]",
      "[class*=dropdown]",
      "[class*=option]",
      "[class*=collection]",
      "[class*=playlist]",
      "[class*=category]",
      "[class*=topic]",
      "[class*=tag]",
      "[class*=publish]",
      "[class*=declaration]",
      "[class*=statement]",
      "[class*=privacy]",
      "[class*=visibility]",
      "[class*=schedule]",
      "[class*=time]",
      "[class*=group]",
      "[class*=chat]",
      "[role=combobox]",
      "[role=listbox]",
      "[role=menu]",
      "[role=menuitem]",
      "[role=option]",
      "[role=switch]",
      "[role=checkbox]",
    ].join(",");
    const vueElements = [...document.querySelectorAll(frameworkSelectors)]
      .filter((el) => el.__vue__ && visible(el))
      .slice(0, 80);
    for (const el of vueElements) {
      const vm = el.__vue__;
      const component = {
        framework: "vue",
        tag: el.tagName.toLowerCase(),
        className: clean(typeof el.className === "string" ? el.className : ""),
        text: clean(el.innerText || el.textContent).slice(0, 160),
        value: vm.value ?? vm.checked ?? vm.active ?? null,
        selected: clean(vm.selected?.name || vm.selected?.title || vm.current?.name || vm.current?.title || vm._watchers?.[1]?.value?.name || ""),
      };
      components.push(component);
      scanObject(vm.$props || {}, \`\${component.className || component.tag}.$props\`);
      scanObject(vm.$data || vm._data || {}, \`\${component.className || component.tag}.$data\`);
      scanObject(vm._props || {}, \`\${component.className || component.tag}._props\`);
      for (const [index, watcher] of (vm._watchers || []).entries()) {
        summarizeValues(watcher?.value, \`\${component.className || component.tag}._watchers[\${index}]\`);
      }
    }
    const reactElements = [...document.querySelectorAll(frameworkSelectors)]
      .filter((el) => Object.keys(el).some((key) => key.startsWith("__reactProps$") || key.startsWith("__reactFiber$")))
      .filter(visible)
      .slice(0, 140);
    const reactFiberOf = (el) => {
      const key = Object.keys(el).find((item) => item.startsWith("__reactFiber$") || item.startsWith("__reactInternalInstance$"));
      return key ? el[key] : null;
    };
    const reactPropsOf = (el) => {
      const key = Object.keys(el).find((item) => item.startsWith("__reactProps$"));
      return key ? el[key] : null;
    };
    for (const el of reactElements) {
      const component = {
        framework: "react",
        tag: el.tagName.toLowerCase(),
        className: clean(typeof el.className === "string" ? el.className : ""),
        text: clean(el.innerText || el.textContent).slice(0, 160),
      };
      components.push(component);
      const fiber = reactFiberOf(el);
      scanObject(reactPropsOf(el) || {}, \`\${component.className || component.tag}.reactProps\`);
      scanObject(fiber?.memoizedProps || {}, \`\${component.className || component.tag}.memoizedProps\`);
      scanObject(fiber?.memoizedState || {}, \`\${component.className || component.tag}.memoizedState\`);
      scanObject(fiber?.return?.memoizedProps || {}, \`\${component.className || component.tag}.parentMemoizedProps\`);
      scanObject(fiber?.return?.memoizedState || {}, \`\${component.className || component.tag}.parentMemoizedState\`);
    }
    const semanticTextGroups = {
      collections: /合集|栏目|专辑|播放列表|playlist|collection|album/i,
      categories: /分类|分区|品类|category|section|partition/i,
      declarations: /原创|声明|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights|kids|audience/i,
      visibility: /公开|私密|可见|所有人|好友|仅自己|visibility|public|private|unlisted|everyone/i,
      schedule: /定时|预约|发布时间|发表时间|schedule|premiere/i,
      topics: /话题|标签|topic|hashtag|tag/i,
      groups: /群聊|社群|group|chat/i,
    };
    for (const [key, pattern] of Object.entries(semanticTextGroups)) {
      const options = components.map((item) => item.text).filter((text) => text && pattern.test(text) && text.length <= 120);
      addGroup(\`\${platform}_framework_component_\${key}\`, \`组件文本候选：\${key}\`, options, options.map((name) => ({ name, source: "component_visible_text" })), "component_visible_text");
    }
    if (platform === "bilibili") {
      const categoryEl = document.querySelector(".video-human-type");
      const categoryVm = categoryEl?.__vue__;
      const categoryList = categoryVm?._watchers?.[0]?.value || [];
      if (Array.isArray(categoryList)) {
        addGroup(
          "bilibili_vue_primary_sections",
          "B站 Vue 投稿页一级分区",
          categoryList.map((item) => item?.name),
          categoryList.map((item) => ({ id: item?.id || "", name: item?.name || "", source: "video-human-type.__vue__" })),
        );
      }
      const selected = categoryVm?._watchers?.[1]?.value;
      if (selected?.name) {
        addGroup("bilibili_vue_selected_section", "B站 Vue 当前分区", [selected.name], [{ id: selected.id || "", name: selected.name, source: "video-human-type.__vue__.selected" }]);
      }
      const seasonText = clean(document.querySelector(".video-season-select .season-select")?.innerText || "");
      if (seasonText) addGroup("bilibili_vue_selected_collection", "B站当前合集读回", [seasonText], [{ name: seasonText, source: "video-season-select.dom_readback" }]);
    }
    return { framework: components.length ? "detected" : "none", components: components.slice(0, 80), option_groups: [...uniqueGroups.values()] };
  })()`;
  try {
    return await evaluateWithClient(client, expression, 20000);
  } catch (error) {
    return { framework: "error", error: error.message, components: [], option_groups: [] };
  }
}

async function collectPlatformApiInventory(client, platform) {
  if (platform === "bilibili") {
    const expression = `Promise.all([
        fetch("https://member.bilibili.com/x/vupre/web/archive/pre?lang=cn", { credentials: "include" }).then((response) => response.json()).catch((error) => ({ error: error.message })),
        fetch("https://member.bilibili.com/x2/creative/web/seasons?pn=1&ps=100", { credentials: "include" }).then((response) => response.json()).catch((error) => ({ error: error.message })),
      ])
      .then(([prePayload, seasonPayload]) => {
        const payload = prePayload || {};
        const data = payload && payload.data ? payload.data : {};
        const sections = [];
        const walk = (items, path = []) => {
          for (const item of items || []) {
            const nextPath = [...path, item.name].filter(Boolean);
            if (item.id && item.name && path.length) {
              sections.push({
                name: item.name,
                id: item.id,
                path: nextPath.join("/"),
                description: item.description || item.desc || "",
              });
            }
            walk(item.children || [], nextPath);
          }
        };
        walk(data.typelist || []);
        const seasons = [];
        const collectSeason = (value) => {
          if (Array.isArray(value)) {
            for (const item of value) collectSeason(item);
          } else if (value && typeof value === "object") {
            const name = value.name || value.title || value.label || value.season_title;
            if (name) seasons.push(String(name));
            for (const child of Object.values(value)) {
              if (child && typeof child === "object") collectSeason(child);
            }
          }
        };
        collectSeason(data.season);
        const seasonCatalog = [];
        const seasonData = seasonPayload && seasonPayload.data ? seasonPayload.data : {};
        for (const item of seasonData.seasons || []) {
          const season = item && item.season ? item.season : item;
          const title = season && (season.title || season.name || season.label || season.season_title);
          if (!title) continue;
          const section = item && item.sections && Array.isArray(item.sections.sections) ? item.sections.sections[0] : null;
          seasonCatalog.push({
            id: season.id || season.season_id || "",
            name: String(title),
            selectable: true,
            status: season.state === 0 || season.state === undefined ? "selectable" : String(season.state),
            video_count: Number(season.ep_num || season.epCount || (section && section.epCount) || 0),
            source: "bilibili_x2_creative_web_seasons",
            section_id: section && section.id ? section.id : "",
          });
        }
        return { sections, seasons: [...new Set(seasons)].slice(0, 60), seasonCatalog };
      })
      .catch((error) => ({ error: error.message }))`;
    const payload = await evaluateWithClient(client, expression, 20000);
    const groups = [];
    if (Array.isArray(payload.sections) && payload.sections.length) {
      groups.push({
        key: "bilibili_api_sections",
        label: "B站真实分区接口",
        options: payload.sections.map((item) => item.path || item.name).filter(Boolean).slice(0, 180),
        values: payload.sections.slice(0, 180),
      });
    }
    if (Array.isArray(payload.seasons) && payload.seasons.length) {
      groups.push({ key: "bilibili_api_collections", label: "B站真实合集接口", options: payload.seasons.slice(0, 60) });
    }
    if (Array.isArray(payload.seasonCatalog) && payload.seasonCatalog.length) {
      groups.push({
        key: "bilibili_season_catalog",
        label: "B站合集管理真实目录",
        options: payload.seasonCatalog.map((item) => item.name).filter(Boolean).slice(0, 100),
        values: payload.seasonCatalog.slice(0, 100),
      });
    }
    return groups;
  }
  return [];
}

function buildInventory(platform, tab, snapshot, probeMeta = {}) {
  const lines = snapshot.lines || [];
  const elements = snapshot.elements || [];
  const warnings = [];
  const fieldGroups = buildFieldGroups(platform, elements, lines);
  const domOptionGroups = buildOptionGroups(platform, elements, lines);
  const domControlGroups = buildDomControlOptionGroups(platform, elements);
  const optionGroups = mergeOptionGroups(
    mergeOptionGroups(mergeOptionGroups(domOptionGroups, domControlGroups), snapshot.api_option_groups || []),
    snapshot.framework_option_groups || [],
  );
  const coverage = buildProbeCoverage(platform, optionGroups, lines, fieldGroups);
  const routeReadiness = deriveProbeInventoryRouteReadiness(platform, snapshot);
  const effectiveCoverage = routeReadiness.reason === "publish_route_upload_prompt"
    ? { ...coverage, missing_required_surfaces: [] }
    : coverage;
  const evidence = buildInventoryEvidence(platform, {
    dom: domOptionGroups,
    controls: domControlGroups,
    api: snapshot.api_option_groups || [],
    framework: snapshot.framework_option_groups || [],
    fieldGroups,
    lines,
  });
  const operationSteps = (PLATFORM_STEPS[platform] || [
    "打开平台创作/发布页",
    "上传视频和封面",
    "填写标题、正文、标签",
    "选择平台真实可见的合集、分类、声明和定时设置",
    "发布前再次验证页面和字段变化",
  ]).map((label, index) => ({ index: index + 1, label }));

  if (platform === "youtube" && lines.some((line) => /功能受限|已停用评论|已停用通知|COPPA|儿童/.test(line))) {
    warnings.push("YouTube 页面显示功能受限/COPPA/评论或通知限制，发布方案必须保留并处理该限制。");
  }
  if (probeMeta.draft_upload_requested && !probeMeta.upload?.uploaded) {
    warnings.push(`已请求草稿上传摸底，但未能启动上传：${probeMeta.upload?.reason || "unknown"}。`);
  }
  if (routeReadiness.blocked) {
    warnings.unshift(
      routeReadiness.reason === "publish_route_loading"
        ? "当前发布页仍在加载中；此时不能把空白/骨架页面当成缺字段。"
        : "当前发布页尚未进入可编辑状态；此时不能把恢复页或空白页当成缺字段。",
    );
  } else if (routeReadiness.reason === "publish_route_upload_prompt") {
    warnings.push("当前发布页处于视频上传入口；标题、封面、话题、合集和定时等发布参数将在上传后由正式发布 worker 继续验证。");
  }
  if (platform === "douyin" && /content\/upload/.test(snapshot.url || "") && !probeMeta.upload?.uploaded) {
    warnings.push("抖音当前停留在上传入口；标题、合集、声明、定时等发布参数通常要完成草稿上传后才会出现，不能用侧边栏文字冒充发布选项。");
  }
  for (const missing of effectiveCoverage.missing_required_surfaces || []) {
    warnings.push(`未完成关键发布面摸底：${missing.label}。这表示尚未采到真实选项，不能推断为平台没有该选项。`);
  }
  if (!optionGroups.length) warnings.push("已连接真实页面，但没有识别到可用下拉/候选选项；需要展开页面控件后重新摸底。");

  return {
    status: routeReadiness.blocked ? "route_not_ready" : (routeReadiness.status === "upload_entry_ready" ? "upload_entry_ready" : (optionGroups.length || fieldGroups.length ? "partial" : "needs_expanded_controls")),
    platform,
    message: routeReadiness.blocked
      ? "已到达发布路由，但当前页面仍在加载或编辑器未就绪。"
      : (probeMeta.draft_upload_requested
        ? "已在不点击发布按钮的前提下进行草稿上传摸底，并读取可见/已展开控件。"
        : "已从当前浏览器页面读取可见控件；折叠菜单需要在平台页面展开后重新摸底。"),
    route: {
      url: snapshot.url || tab.url || "",
      title: snapshot.title || tab.title || "",
      domains: PLATFORM_DOMAINS[platform] || [],
    },
    route_readiness: routeReadiness,
    field_groups: fieldGroups,
    option_groups: optionGroups,
    evidence,
    visual_evidence: normalizeVisualEvidence(snapshot.visual_evidence),
    framework_inventory: snapshot.framework_inventory || { framework: "unknown", components: [], option_groups: [] },
    coverage: effectiveCoverage,
    operation_steps: operationSteps,
    warnings,
    probe_meta: probeMeta,
  };
}

export function buildLightweightProbeInventorySummary(platform, tab, snapshot, probeMeta = {}) {
  const lines = snapshot?.lines || [];
  const elements = snapshot?.elements || [];
  const fieldGroups = buildFieldGroups(platform, elements, lines);
  const domOptionGroups = buildOptionGroups(platform, elements, lines);
  const coverage = buildProbeCoverage(platform, domOptionGroups, lines, fieldGroups);
  const routeReadiness = deriveProbeInventoryRouteReadiness(platform, snapshot);
  const effectiveCoverage = routeReadiness.reason === "publish_route_upload_prompt"
    ? { ...coverage, missing_required_surfaces: [] }
    : coverage;
  const warnings = [];
  if (routeReadiness.blocked) {
    warnings.push(
      routeReadiness.reason === "publish_route_loading"
        ? "当前发布页仍在加载中；不能把空白/骨架页面推断成缺字段。"
        : "当前发布页尚未进入可编辑状态；不能把恢复页或空白页推断成缺字段。",
    );
  } else if (routeReadiness.reason === "publish_route_upload_prompt") {
    warnings.push("当前发布页处于视频上传入口；发布参数将在上传后继续验证，不能把上传入口误判为缺字段。");
  }
  for (const missing of effectiveCoverage.missing_required_surfaces || []) {
    warnings.push(`未完成关键发布面摸底：${missing.label}。这表示尚未采到真实选项，不能推断为平台没有该选项。`);
  }
  if (!domOptionGroups.length && !fieldGroups.length) {
    warnings.push("当前只保留轻量页面快照，尚未识别到可用控件；如需完整选项目录，请走完整 inventory 摸底。");
  }
  return {
    status: routeReadiness.blocked ? "route_not_ready" : (routeReadiness.status === "upload_entry_ready" ? "upload_entry_ready" : (domOptionGroups.length || fieldGroups.length ? "partial" : "needs_expanded_controls")),
    platform,
    message: routeReadiness.blocked
      ? "已到达发布路由，但当前页面仍在加载或编辑器未就绪。"
      : "已采集当前页面轻量快照，用于发布前验证、异常分析和视觉证据留档。",
    route: {
      url: snapshot?.url || tab?.url || "",
      title: snapshot?.title || tab?.title || "",
      domains: PLATFORM_DOMAINS[platform] || [],
    },
    route_readiness: routeReadiness,
    coverage: effectiveCoverage,
    warnings: warnings.slice(0, 20),
    operation_steps: (PLATFORM_STEPS[platform] || []).slice(0, 20).map((label, index) => ({ index: index + 1, label })),
    visual_evidence: normalizeVisualEvidence(snapshot?.visual_evidence),
    probe_meta: {
      summary_only: true,
      draft_upload_requested: Boolean(probeMeta?.draft_upload_requested),
      actions: Array.isArray(probeMeta?.actions)
        ? probeMeta.actions
          .filter((action) => action && typeof action === "object")
          .map((action) => ({
            kind: String(action.kind || ""),
            clicked: Boolean(action.clicked),
            clicked_label: String(action.clicked_label || action.label || ""),
            reason: String(action.reason || ""),
            resumed: action.resumed === true,
            prompt_present: action.prompt_present === true,
          }))
          .slice(0, 12)
        : [],
      upload: probeMeta?.upload && typeof probeMeta.upload === "object"
        ? {
            uploaded: Boolean(probeMeta.upload.uploaded),
            reused: Boolean(probeMeta.upload.reused),
            reason: String(probeMeta.upload.reason || ""),
          }
        : undefined,
    },
  };
}

export function buildCompactProbeInventorySummary(inventory) {
  if (!inventory || typeof inventory !== "object") return {};
  return {
    status: String(inventory.status || ""),
    platform: String(inventory.platform || ""),
    message: String(inventory.message || ""),
    route: inventory.route && typeof inventory.route === "object" ? { ...inventory.route } : {},
    route_readiness: inventory.route_readiness && typeof inventory.route_readiness === "object" ? { ...inventory.route_readiness } : {},
    coverage: inventory.coverage && typeof inventory.coverage === "object" ? { ...inventory.coverage } : {},
    warnings: Array.isArray(inventory.warnings) ? inventory.warnings.slice(0, 20) : [],
    operation_steps: Array.isArray(inventory.operation_steps) ? inventory.operation_steps.slice(0, 20) : [],
    visual_evidence: normalizeVisualEvidence(inventory.visual_evidence),
    probe_meta: inventory.probe_meta && typeof inventory.probe_meta === "object"
      ? {
          draft_upload_requested: Boolean(inventory.probe_meta.draft_upload_requested),
          actions: Array.isArray(inventory.probe_meta.actions)
            ? inventory.probe_meta.actions
              .filter((action) => action && typeof action === "object")
              .map((action) => ({
                kind: String(action.kind || ""),
                clicked: Boolean(action.clicked),
                clicked_label: String(action.clicked_label || action.label || ""),
                reason: String(action.reason || ""),
                resumed: action.resumed === true,
                prompt_present: action.prompt_present === true,
              }))
              .slice(0, 12)
            : [],
          upload: inventory.probe_meta.upload && typeof inventory.probe_meta.upload === "object"
            ? {
                uploaded: Boolean(inventory.probe_meta.upload.uploaded),
                reused: Boolean(inventory.probe_meta.upload.reused),
                reason: String(inventory.probe_meta.upload.reason || ""),
              }
            : undefined,
          sidecar_tabs_read: Array.isArray(inventory.probe_meta.sidecar_tabs_read)
            ? inventory.probe_meta.sidecar_tabs_read.slice(0, 8)
            : undefined,
        }
      : {},
  };
}

function buildInventoryEvidence(platform, { dom = [], controls = [], api = [], framework = [], fieldGroups = [], lines = [] } = {}) {
  const frameworkState = (framework || []).filter((group) => String(group.source || "") === "framework_state");
  const componentText = (framework || []).filter((group) => String(group.source || "") === "component_visible_text");
  const sourceSummary = [
    { source: "dom_visible_text", group_count: dom.length, option_count: dom.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "dom_control", group_count: controls.length, option_count: controls.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "platform_catalog", group_count: (dom || []).filter((group) => String(group.source || "") === "platform_catalog").length, option_count: (dom || []).filter((group) => String(group.source || "") === "platform_catalog").reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "platform_api", group_count: api.length, option_count: api.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "framework_state", group_count: frameworkState.length, option_count: frameworkState.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "component_visible_text", group_count: componentText.length, option_count: componentText.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "field_controls", group_count: fieldGroups.length, option_count: fieldGroups.reduce((total, group) => total + (group.controls || []).length, 0) },
  ];
  const bySurface = (PLATFORM_REQUIRED_SURFACES[platform] || []).map((surface) => {
    const matchingSources = [];
    for (const [source, groups] of [
      ["dom_visible_text", dom],
      ["dom_control", controls],
      ["platform_catalog", (dom || []).filter((group) => String(group.source || "") === "platform_catalog")],
      ["platform_api", api],
      ["framework_state", frameworkState],
      ["component_visible_text", componentText],
    ]) {
      const matched = (groups || []).filter((group) => {
        const text = `${group.key || ""}\n${group.label || ""}\n${(group.options || []).join("\n")}\n${JSON.stringify(group.values || [])}`;
        return surface.pattern.test(text);
      });
      if (matched.length) {
        matchingSources.push({
          source,
          groups: matched.map((group) => String(group.key || group.label || "")).slice(0, 6),
          samples: matched.flatMap((group) => group.options || []).slice(0, 10),
        });
      }
    }
    if (surface.pattern.test(JSON.stringify(fieldGroups || []))) matchingSources.push({ source: "field_controls", groups: [surface.key], samples: [] });
    if (surface.pattern.test((lines || []).join("\n"))) matchingSources.push({ source: "page_text", groups: [surface.key], samples: [] });
    return {
      key: surface.key,
      label: surface.label,
      confidence: matchingSources.some((item) => item.source === "platform_api" || item.source === "platform_catalog" || item.source === "framework_state" || item.source === "dom_control")
        ? "strong"
        : matchingSources.length
          ? "weak"
          : "missing",
      sources: matchingSources,
    };
  });
  return { source_summary: sourceSummary, by_surface: bySurface };
}

function refreshInventoryCoverage(inventory) {
  if (!inventory || typeof inventory !== "object") return inventory;
  const optionGroups = inventory.option_groups || [];
  const lines = [
    ...optionGroups.flatMap((group) => [
      String(group.key || ""),
      String(group.label || ""),
      ...((group.options || []).map((option) => String(option || ""))),
    ]),
    ...((inventory.field_groups || []).flatMap((group) => [
      String(group.key || ""),
      String(group.label || ""),
      ...((group.controls || []).map((control) => String(control.label || ""))),
    ])),
  ];
  inventory.coverage = buildProbeCoverage(inventory.platform, optionGroups, lines, inventory.field_groups || []);
  inventory.evidence = buildInventoryEvidence(inventory.platform, {
    dom: optionGroups.filter((group) => !String(group.source || "").includes("framework") && String(group.source || "") !== "dom_control" && !String(group.key || "").includes("_api_")),
    controls: optionGroups.filter((group) => String(group.source || "") === "dom_control" || String(group.key || "").includes("_dom_control_")),
    api: optionGroups.filter((group) => String(group.key || "").includes("_api_") || String(group.source || "").includes("api")),
    framework: optionGroups.filter((group) => String(group.source || "").includes("framework") || String(group.key || "").includes("_vue_") || String(group.key || "").includes("_framework_")),
    fieldGroups: inventory.field_groups || [],
    lines,
  });
  const stalePrefix = "未完成关键发布面摸底：";
  const warnings = (inventory.warnings || []).filter((warning) => !String(warning || "").startsWith(stalePrefix));
  for (const missing of inventory.coverage.missing_required_surfaces || []) {
    warnings.push(`未完成关键发布面摸底：${missing.label}。这表示尚未采到真实选项，不能推断为平台没有该选项。`);
  }
  inventory.warnings = warnings.slice(0, 20);
  return inventory;
}

const PLATFORM_REQUIRED_SURFACES = {
  douyin: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "话题选择", pattern: /话题|#/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "原创/声明", pattern: /原创|声明|自主声明|AI|营销/i },
    { key: "visibility", label: "谁可以看/可见性", pattern: /谁可以看|公开|好友可见|仅自己可见|visibility/i },
    { key: "schedule", label: "发布时间/定时", pattern: /定时|发布时间|立即发布|schedule/i },
  ],
  xiaohongshu: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "标签/话题选择", pattern: /话题|#|标签/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "原创/内容类型声明", pattern: /原创声明|内容类型声明|AI|虚构|营销|来源/i },
    { key: "group_chat", label: "群聊绑定", pattern: /群聊|群$/i },
    { key: "location", label: "地点/路线", pattern: /地点|位置|路线/i },
    { key: "visibility", label: "可见性", pattern: /公开可见|好友可见|仅自己/i },
    { key: "schedule", label: "定时发布", pattern: /定时发布|发布时间|schedule/i },
  ],
  bilibili: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "category", label: "分区", pattern: /分区|户外潮流|生活兴趣|科技|数码/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "创作声明/权益", pattern: /创作声明|创作权益|内容无需标注|AI|营销|转载|自制/i },
    { key: "schedule", label: "定时发布", pattern: /定时发布|预约|schedule/i },
  ],
  kuaishou: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "标签/话题", pattern: /标签|话题|#|tag/i },
    { key: "category", label: "作品分类", pattern: /作品分类|分类/i },
    { key: "collection", label: "合集/合集目录", pattern: /合集|collection/i },
    { key: "declaration", label: "作者服务/声明", pattern: /作者服务|声明|原创|权益/i },
    { key: "visibility", label: "查看权限", pattern: /所有人可见|好友可见|仅自己可见|查看权限/i },
    { key: "schedule", label: "发布时间", pattern: /定时发布|立即发布|发布时间/i },
  ],
  youtube: [
    { key: "thumbnail", label: "缩略图/封面", pattern: /缩略图|封面|thumbnail|cover/i },
    { key: "playlist", label: "播放列表", pattern: /播放列表|playlist/i },
    { key: "audience", label: "儿童受众/COPPA", pattern: /儿童|COPPA|kids|audience/i },
    { key: "category_language", label: "分类/语言/字幕", pattern: /类别|分类|语言|字幕|category|language|captions|subtitles/i },
    { key: "visibility", label: "公开范围", pattern: /公开|私享|不公开|visibility|public|private|unlisted/i },
    { key: "schedule", label: "预约发布时间", pattern: /预约|定时|schedule/i },
    { key: "restrictions", label: "评论/通知限制", pattern: /评论|通知|功能受限|限制/i },
  ],
  "wechat-channels": [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "话题/位置", pattern: /话题|位置|地点|#/i },
    { key: "collection", label: "合集/活动", pattern: /合集|活动/i },
    { key: "declaration", label: "声明/原创", pattern: /声明|原创/i },
    { key: "visibility", label: "谁可以看", pattern: /谁可以看|公开|朋友/i },
    { key: "schedule", label: "定时发表", pattern: /定时|发表时间|预约/i },
  ],
  toutiao: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "category", label: "分类", pattern: /分类|品类/i },
    { key: "collection", label: "合集", pattern: /合集|专辑/i },
    { key: "declaration", label: "原创/声明", pattern: /原创|声明|权益/i },
    { key: "schedule", label: "定时发布", pattern: /定时|发布时间/i },
  ],
  x: [
    { key: "media", label: "媒体/封面", pattern: /media|image|video|媒体|图片|视频/i },
    { key: "schedule", label: "定时发布", pattern: /Schedule|定时/i },
    { key: "audience", label: "受众/回复权限", pattern: /Audience|Reply|Everyone|回复|受众/i },
  ],
};

function buildProbeCoverage(platform, optionGroups, lines, fieldGroups) {
  const groups = optionGroups || [];
  const lineText = (lines || []).join("\n");
  const fieldText = JSON.stringify(fieldGroups || []);
  const required = PLATFORM_REQUIRED_SURFACES[platform] || [];
  const surfaces = required.map((surface) => {
    const matchedGroups = groups
      .filter((group) => {
        const key = `${group.key || ""} ${group.label || ""}`;
        const options = (group.options || []).join("\n");
        const values = JSON.stringify(group.values || []);
        return surface.pattern.test(`${key}\n${options}\n${values}`);
      })
      .map((group) => String(group.key || group.label || ""));
    const hasField = surface.pattern.test(fieldText);
    const hasLine = surface.pattern.test(lineText);
    return {
      key: surface.key,
      label: surface.label,
      status: matchedGroups.length ? "options_collected" : hasField || hasLine ? "surface_seen_without_options" : "missing",
      matched_groups: matchedGroups.slice(0, 8),
    };
  });
  return {
    required_surfaces: surfaces,
    missing_required_surfaces: surfaces.filter((surface) => surface.status === "missing"),
    partial_required_surfaces: surfaces.filter((surface) => surface.status === "surface_seen_without_options"),
  };
}

export function deriveProbeInventoryRouteReadiness(platform, snapshot = {}) {
  const normalizedPlatform = normalizePlatform(platform);
  const lines = Array.isArray(snapshot?.lines) ? snapshot.lines.map((line) => String(line || "").trim()).filter(Boolean) : [];
  const elements = Array.isArray(snapshot?.elements) ? snapshot.elements : [];
  const fileInputs = Array.isArray(snapshot?.file_inputs) ? snapshot.file_inputs : elements
    .filter((element) => String(element?.type || "").toLowerCase() === "file" || /video|mp4|image/i.test(String(element?.accept || "")))
    .map((element) => ({ accept: String(element?.accept || "") }));
  const hasInputFields = elements.some((element) => {
    const tag = String(element?.tag || element?.tagName || "").toLowerCase();
    const role = String(element?.role || "").toLowerCase();
    return ["input", "textarea", "select"].includes(tag)
      || ["textbox", "searchbox", "combobox", "spinbutton"].includes(role);
  }) || fileInputs.length > 0;
  const bodyText = String(lines.join(" ") || snapshot?.text || "").replace(/\s+/g, " ").trim();
  const routeUrl = String(snapshot?.url || "").trim();
  const signals = detectCompositePublicationSignals(normalizedPlatform, bodyText, lines);
  const xiaohongshuVideoUploadEntry = normalizedPlatform === "xiaohongshu"
    && isXiaohongshuVideoUploadEntrySurface(routeUrl, bodyText);
  const draftResume = deriveCurrentPageDraftResumeDisposition(normalizedPlatform, bodyText);
  const routeReady = isCompositePublishRouteContext(normalizedPlatform, {
    url: routeUrl,
    text: bodyText,
    file_inputs: fileInputs,
  });
  const loadingSurface = /加载中，请稍候|加载中|请稍候|Loading/i.test(bodyText)
    && !hasInputFields
    && (bodyText.length <= 120 || (lines.length > 0 && lines.length <= 12));
  const editorSurfaceMissing = routeReady
    && shouldTreatCompositeEditorSurfaceAsNotReady(normalizedPlatform, routeUrl, hasInputFields, signals);
  if (!routeReady) {
    return {
      blocked: true,
      status: "route_not_ready",
      reason: "publish_route_not_ready",
      has_input_fields: hasInputFields,
      loading_surface: false,
    };
  }
  if (loadingSurface) {
    return {
      blocked: true,
      status: "route_not_ready",
      reason: "publish_route_loading",
      has_input_fields: hasInputFields,
      loading_surface: true,
    };
  }
  if (draftResume.present) {
    return {
      blocked: true,
      status: "route_not_ready",
      reason: "draft_resume_prompt",
      has_input_fields: hasInputFields,
      loading_surface: false,
    };
  }
  if (signals.upload_prompt_only || xiaohongshuVideoUploadEntry) {
    return {
      blocked: false,
      status: "upload_entry_ready",
      reason: "publish_route_upload_prompt",
      has_input_fields: hasInputFields,
      loading_surface: false,
    };
  }
  if (editorSurfaceMissing) {
    return {
      blocked: true,
      status: "route_not_ready",
      reason: "editor_surface_not_ready",
      has_input_fields: hasInputFields,
      loading_surface: false,
    };
  }
  return {
    blocked: false,
    status: "ready",
    reason: "",
    has_input_fields: hasInputFields,
    loading_surface: false,
  };
}

function buildFieldGroups(platform, elements, lines) {
  const fields = [];
  const add = (key, label, matches) => {
    const matched = matches.filter(Boolean);
    if (matched.length) fields.push({ key, label, controls: matched.slice(0, 12) });
  };
  add("title", "标题", findControls(elements, /标题|title/i));
  add("body", "正文/简介", findControls(elements, /正文|简介|描述|说明|作品描述|description/i));
  add("tags", "标签/话题", findControls(elements, /标签|话题|#添加话题|tag/i));
  add("schedule", "定时发布", findControls(elements, /定时|预约|schedule/i));
  add("visibility", "可见性/发布模式", findControls(elements, /公开|私密|可见|草稿|visibility|public|private|draft/i));
  if (platform === "xiaohongshu") {
    add("xiaohongshu_content_settings", "小红书内容设置", matchingLines(lines, /内容设置|添加章节|加入合集|原创声明|内容类型声明|选择群聊|地点|路线/));
    add("xiaohongshu_publish_settings", "小红书发布设置", matchingLines(lines, /封面设置|活动推荐|作者服务|发布设置|查看权限|定时发布|发布/));
  }
  if (platform === "bilibili") {
    add("bilibili_settings", "B站投稿设置", matchingLines(lines, /分区|标签|合集|声明|权益|定时发布|立即投稿/));
  }
  if (platform === "kuaishou") {
    add("kuaishou_publish_settings", "快手发布设置", matchingLines(lines, /封面设置|作品分类|作者服务|作者声明|加入合集|查看权限|发布时间|发布/));
  }
  if (platform === "youtube") {
    add("youtube_publish_settings", "YouTube发布设置", matchingLines(lines, /播放列表|受众|儿童|限制|可见性|公开|预约|评论|通知|字幕|语言|类别|playlist|audience|visibility|schedule/));
  }
  if (platform === "wechat-channels") {
    add("wechat_channels_publish_settings", "视频号发布设置", matchingLines(lines, /合集|活动|原创|声明|谁可以看|定时发表|位置|话题/));
  }
  if (platform === "toutiao") {
    add("toutiao_publish_settings", "头条发布设置", matchingLines(lines, /分类|合集|原创|声明|权益|定时发布|可见|封面/));
  }
  if (platform === "x") {
    add("x_publish_settings", "X发布设置", matchingLines(lines, /Schedule|Audience|Reply|Everyone|Premium|Post settings|定时|可见|回复/));
  }
  if (platform === "douyin") {
    add("douyin_cover", "抖音封面设置", matchingLines(lines, /设置封面|选择封面|横封面|竖封面|Ai智能推荐封面|重新上传/));
    add("douyin_collection_declaration", "抖音合集/自主声明", matchingLines(lines, /添加合集|请选择合集|自主声明|请选择自主声明/));
    add("douyin_extra", "抖音扩展信息", matchingLines(lines, /视频章节|添加标签|位置|输入地理位置|关联热点|点击输入热点词/));
    add("douyin_publish_settings", "抖音发布设置", matchingLines(lines, /谁可以看|公开|好友可见|仅自己可见|保存权限|允许|不允许|发布时间|立即发布|定时发布/));
  }
  return fields;
}

function buildOptionGroups(platform, elements, lines) {
  const groups = [];
  const add = (key, label, options) => {
    const cleaned = unique(options.map((item) => String(item || "").trim()).filter((item) => item && item.length <= 80));
    if (cleaned.length) groups.push({ key, label, options: cleaned.slice(0, 60) });
  };
  const selectOptions = elements.flatMap((element) => element.options || []);
  add("select_options", "页面 select 控件选项", selectOptions);
  if (platform !== "douyin") {
    add("collections", "合集/栏目/播放列表", contextOptions(lines, /合集|栏目|专辑|播放列表|playlist|album/i));
    add("categories", "分类/分区", contextOptions(lines, /分类|分区|品类|category|section|partition/i));
  }
  if (platform !== "xiaohongshu" && platform !== "douyin") {
    add("declarations", "声明/权益/内容类型", contextOptions(lines, /声明|原创|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights/i));
    add("group_chats", "群聊/社群", contextOptions(lines, /群聊|社群|粉丝群|group|chat/i));
  }

  if (platform === "xiaohongshu") {
    add(
      "xiaohongshu_collections",
      "小红书合集",
      [
        ...lines.filter((line) => /EDC刀光|EDC潮玩|FAS新品|开箱视频|合集$|创建合集/.test(line)),
      ],
    );
    add(
      "xiaohongshu_declarations",
      "小红书声明",
      [
        ...lines.filter((line) => /原创声明|虚构演绎|AI合成|营销广告|内容来源/.test(line)),
      ],
    );
    add(
      "xiaohongshu_group_chats",
      "小红书群聊",
      [
        ...lines.filter((line) => /群$|群聊|F\\.A\\.S EDC畅聊群/i.test(line)),
      ],
    );
    add(
      "xiaohongshu_topics",
      "小红书可选话题",
      [
        ...lines.filter((line) => /^#/.test(line)),
        ...lines.filter((line) => /添加话题|活动详情|搜索更多话题|话题/.test(line)),
      ],
    );
    add("xiaohongshu_visibility", "小红书可见性", lines.filter((line) => /^(公开可见|仅自己可见|好友可见|仅粉丝可见|公开|私密)$/.test(line)));
    add("xiaohongshu_location_route", "小红书地点/路线", contextOptions(lines, /添加地点|标记地点|添加路线|路线|地点/i));
    add("xiaohongshu_live_group_binding", "小红书群聊绑定", contextOptions(lines, /选择群聊|群聊|F\\.A\\.S|EDC畅聊群/i));
    add("xiaohongshu_schedule", "小红书定时发布", contextOptions(lines, /定时发布|发布时间|立即发布/i));
  }
  if (platform === "bilibili") {
    add("bilibili_collection_dropdown_options", "B站合集下拉真实选项", extractBilibiliCollectionDropdownOptions(lines));
    add("bilibili_visible_sections", "B站页面可见分区", extractBilibiliVisibleSections(lines));
    add(
      "bilibili_sections",
      "B站分区候选",
      [
        ...contextOptions(lines, /户外潮流|数码|生活|运动|科技|分区/i),
        ...lines.filter((line) => /户外潮流|数码|生活|运动|科技|知识|汽车|时尚|家装房产/.test(line)),
      ],
    );
  }
  if (platform === "kuaishou") {
    add("kuaishou_categories", "快手作品分类", contextOptions(lines, /作品分类|分类|服务类型|作者服务/i));
    add("kuaishou_declarations", "快手声明/作者服务", contextOptions(lines, /作者服务|原创|声明|权益|关联成功可获得更多收益/i));
    add("kuaishou_visibility", "快手查看权限/互动设置", contextOptions(lines, /查看权限|所有人可见|好友可见|仅自己可见|允许别人跟我拍同框|允许下载|同城页/i));
    add("kuaishou_schedule", "快手发布时间", contextOptions(lines, /发布时间|立即发布|定时发布|粉丝浏览高峰/i));
    add("kuaishou_topics", "快手标签/话题", [
      ...lines.filter((line) => /^#/.test(line)),
      ...contextOptions(lines, /智能话题|好友|推荐|话题|标签/i),
    ]);
    const catalog = extractKuaishouCollectionCatalog(lines);
    if (catalog.length) {
      groups.push({
        key: "kuaishou_collection_catalog",
        label: "快手合集目录",
        source: "platform_catalog",
        options: catalog.map((item) => item.name),
        values: catalog,
      });
    }
  }
  if (platform === "douyin") {
    add("douyin_visibility", "抖音谁可以看", lines.filter((line) => /^(公开|好友可见|仅自己可见)$/.test(line)));
    add("douyin_save_permission", "抖音保存权限", lines.filter((line) => /^(允许|不允许)$/.test(line)));
    add("douyin_schedule", "抖音发布时间", lines.filter((line) => /^(立即发布|定时发布)$/.test(line)));
    add("douyin_topics", "抖音推荐话题", lines.filter((line) => /^#/.test(line)));
    const officialActivities = [];
    const officialIndex = lines.findIndex((line) => line === "官方活动");
    if (officialIndex >= 0) {
      for (const line of lines.slice(officialIndex + 1, officialIndex + 10)) {
        if (/^热度：/.test(line) || /^\+\d+/.test(line)) continue;
        if (/设置封面|添加合集|自主声明/.test(line)) break;
        officialActivities.push(line);
      }
    }
    add("douyin_official_activities", "抖音官方活动", officialActivities);
  }
  if (platform === "youtube") {
    add("youtube_playlists", "YouTube播放列表", contextOptions(lines, /播放列表|playlist/i));
    add("youtube_audience", "YouTube受众/COPPA", contextOptions(lines, /儿童|面向儿童|COPPA|audience|kids/i));
    add("youtube_visibility", "YouTube公开范围", contextOptions(lines, /公开|私享|不公开|visibility|public|private|unlisted/i));
    add("youtube_restrictions", "YouTube限制/通知评论", lines.filter((line) => /功能受限|停用评论|停用通知|评论|通知|限制/i.test(line)));
    add("youtube_monetization_checks", "YouTube声明/获利检查", contextOptions(lines, /广告|推广|付费|版权|限制|检查|声明|自我认证|altered|synthetic|paid promotion/i));
    add("youtube_category_language", "YouTube分类/语言/字幕", contextOptions(lines, /类别|分类|语言|字幕|category|language|captions|subtitles/i));
    add("youtube_schedule", "YouTube预约发布时间", contextOptions(lines, /预约|首映|定时|schedule|premiere|publish/i));
  }
  if (platform === "wechat-channels") {
    add("wechat_channels_collections", "视频号合集/活动", contextOptions(lines, /合集|活动|原创|声明|谁可以看|定时/i));
    add("wechat_channels_declarations", "视频号声明/原创", contextOptions(lines, /原创|声明|活动|权益|推广/i));
    add("wechat_channels_visibility", "视频号谁可以看", contextOptions(lines, /谁可以看|公开|朋友|私密|不给谁看/i));
    add("wechat_channels_schedule", "视频号定时发表", contextOptions(lines, /定时发表|发表时间|立即发表|预约/i));
    add("wechat_channels_topics", "视频号话题/位置", contextOptions(lines, /话题|位置|地点|活动/i));
  }
  if (platform === "toutiao") {
    add("toutiao_categories", "头条分类/声明", contextOptions(lines, /分类|品类|合集|原创|声明|权益|定时/i));
    add("toutiao_collections", "头条合集/专栏", contextOptions(lines, /合集|专栏|专辑|栏目/i));
    add("toutiao_declarations", "头条原创/声明/权益", contextOptions(lines, /原创|声明|权益|广告|营销|AI/i));
    add("toutiao_visibility", "头条可见性", contextOptions(lines, /公开|仅我可见|粉丝可见|可见/i));
    add("toutiao_schedule", "头条定时发布", contextOptions(lines, /定时发布|发布时间|立即发布|预约/i));
  }
  if (platform === "x") {
    add("x_publish_settings", "X发布设置", contextOptions(lines, /Schedule|Audience|Reply|Everyone|Premium|Post settings|定时|可见|回复/i));
    add("x_audience_reply", "X受众/回复权限", contextOptions(lines, /Audience|Reply|Everyone|Circle|Subscribers|回复|所有人|受众/i));
    add("x_schedule", "X定时发布", contextOptions(lines, /Schedule|Date|Time|定时|日期|时间/i));
  }
  return groups;
}

function buildDomControlOptionGroups(platform, elements) {
  const groups = [];
  const add = (key, label, options, values = []) => {
    const cleaned = unique(options.map((item) => String(item || "").trim()).filter((item) => item && item.length <= 120));
    if (cleaned.length) {
      groups.push({
        key,
        label,
        source: "dom_control",
        options: cleaned.slice(0, 120),
        values: values.slice(0, 120),
      });
    }
  };
  const controls = (elements || [])
    .filter((element) => {
      const text = String(element.text || element.ariaLabel || element.placeholder || "").trim();
      if (!text || text.length > 120) return false;
      if (element.disabled) return false;
      return /button|checkbox|switch|combobox|option|menuitem/.test(String(element.role || "")) ||
        /button|checkbox|radio|submit/.test(String(element.type || "")) ||
        /select|dropdown|option|menu|collection|playlist|category|topic|tag|publish|declaration|statement|privacy|visibility|schedule|time|group|chat/i.test(String(element.className || ""));
    })
    .map((element) => ({
      name: String(element.text || element.ariaLabel || element.placeholder || "").trim(),
      tag: element.tag,
      role: element.role,
      type: element.type,
      className: element.className,
      checked: Boolean(element.checked),
      source: "dom_control",
    }));
  const byPattern = {
    collections: /合集|栏目|专辑|播放列表|playlist|collection|album/i,
    categories: /分类|分区|品类|category|section|partition/i,
    declarations: /原创|声明|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights|kids|audience/i,
    visibility: /公开|私密|可见|所有人|好友|仅自己|visibility|public|private|unlisted|everyone/i,
    schedule: /定时|预约|发布时间|发表时间|schedule|premiere|Date|Time/i,
    topics: /话题|标签|topic|hashtag|tag|#/i,
    groups: /群聊|社群|group|chat/i,
    cover: /封面|缩略图|cover|thumbnail/i,
    media: /媒体|视频|图片|media|video|image/i,
  };
  for (const [key, pattern] of Object.entries(byPattern)) {
    const matched = controls.filter((item) => pattern.test(`${item.name} ${item.className} ${item.role}`));
    add(`${platform}_dom_control_${key}`, `DOM交互控件：${key}`, matched.map((item) => item.name), matched);
  }
  return groups;
}

function extractBilibiliCollectionDropdownOptions(lines) {
  const output = [];
  const ignored = /^(加入合集|请选择合集|创建合集|将以下所有视频加入合集|我的合集|全部|商业推广|增加商业推广信息|更多设置|存草稿|立即投稿|遇到问题|内容无需标注|分区|标签|推荐标签：?|创作声明|创作权益|\*|\+|取消|确定)$/;
  const hardStop = /^(商业推广|更多设置|创作声明|分区|标签|推荐标签|简介|定时发布|立即投稿|存草稿|添加地点|发布设置)$/;
  const anchors = [];
  for (let index = 0; index < (lines || []).length; index += 1) {
    const line = String(lines[index] || "").trim();
    if (/^(创建合集|请选择合集|加入合集)$/.test(line)) anchors.push(index);
  }
  for (const anchor of anchors) {
    for (const rawLine of (lines || []).slice(anchor + 1, anchor + 18)) {
      const line = String(rawLine || "").replace(/\s+/g, " ").trim();
      if (!line) continue;
      if (hardStop.test(line)) break;
      if (ignored.test(line)) continue;
      if (line.length < 2 || line.length > 40) continue;
      if (/^\d+$/.test(line)) continue;
      if (/^包含\d+个/.test(line)) continue;
      if (/还可以添加|按回车|添加\d+个标签|活动$|NEW|HOT/.test(line)) continue;
      output.push(line);
    }
  }
  return unique(output);
}

function extractKuaishouCollectionCatalog(lines) {
  const output = [];
  const ignored = /^(全部|我的合集|创建合集|共\d+个合集|编辑合集|解除合集|拖动可排序|作品管理|合集管理|内容管理|首页|发布作品)$/;
  for (let index = 0; index < (lines || []).length; index += 1) {
    const name = String(lines[index] || "").trim();
    if (!name || name.length > 40 || ignored.test(name)) continue;
    const next = String(lines[index + 1] || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$/.test(next)) continue;
    const windowLines = lines.slice(index + 2, index + 8).map((line) => String(line || "").trim());
    const status = windowLines.find((line) => /公开|展示|剧集|不足|selectable|unselectable/i.test(line)) || "";
    const countLine = windowLines.find((line) => /包含\d+个视频/.test(line)) || "";
    const countMatch = countLine.match(/包含(\d+)个视频/);
    const videoCount = countMatch ? Number(countMatch[1]) : null;
    const selectable = !/未公开展示|有效剧集数不足|不公开展示|不可选|不能选择/i.test(status);
    output.push({
      name,
      status,
      selectable,
      video_count: videoCount,
      source: "kuaishou_collection_management_page",
      note: countLine,
    });
  }
  return uniqueBy(output, (item) => item.name).slice(0, 50);
}

function extractBilibiliVisibleSections(lines) {
  const output = [];
  const known = new Set(BILIBILI_SECTION_TERMS);
  for (const rawLine of lines || []) {
    const line = String(rawLine || "").trim();
    if (!line) continue;
    if (known.has(line)) {
      output.push(line);
      continue;
    }
    if (!/分区|生活兴趣|户外潮流|科技数码|时尚美妆|家装房产|旅游出行/.test(line)) continue;
    for (const term of BILIBILI_SECTION_TERMS) {
      if (line.includes(term)) output.push(term);
    }
  }
  return unique(output);
}

function findControls(elements, pattern) {
  return elements
    .filter((element) => pattern.test(`${element.text} ${element.ariaLabel} ${element.placeholder}`))
    .map((element) => ({
      tag: element.tag,
      role: element.role,
      type: element.type,
      label: element.text || element.ariaLabel || element.placeholder,
      checked: element.checked,
    }));
}

function matchingLines(lines, pattern) {
  return lines.filter((line) => pattern.test(line)).slice(0, 20).map((line) => ({ label: line }));
}

function contextOptions(lines, pattern) {
  const options = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!pattern.test(line)) continue;
    options.push(line);
    for (const nearby of lines.slice(index + 1, index + 8)) {
      if (/发布|保存|取消|确定|下一步|上一步|上传/.test(nearby) && nearby.length < 8) continue;
      if (nearby.length <= 80) options.push(nearby);
    }
  }
  return options;
}

function unique(values) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function uniqueBy(values, getKey) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const key = String(getKey(value) || "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function mergeOptionGroups(left, right) {
  const groups = [];
  const byKey = new Map();
  for (const group of [...(left || []), ...(right || [])]) {
    if (!group || typeof group !== "object") continue;
    const key = String(group.key || group.label || groups.length).trim();
    const current = byKey.get(key);
    if (current) {
      current.options = unique([...(current.options || []), ...(group.options || [])]).slice(0, 220);
      current.values = [...(current.values || []), ...(Array.isArray(group.values) ? group.values : [])].slice(0, 220);
    } else {
      const next = {
        ...group,
        key,
        options: unique(group.options || []).slice(0, 220),
      };
      if (Array.isArray(group.values)) next.values = group.values.slice(0, 220);
      byKey.set(key, next);
      groups.push(next);
    }
  }
  return groups;
}

async function handleProbe(payload) {
  const requestedPlatforms = Array.isArray(payload.platforms) ? payload.platforms.map(normalizePlatform).filter(Boolean) : [];
  const summaryOnly = Boolean(payload.summary_only);
  let tabs;
  try {
    tabs = await listCdpTabs();
  } catch (error) {
    return {
      contract: CONTRACT,
      status: "unavailable",
      code: "cdp_unavailable",
      message: `无法连接浏览器 CDP：${error.message}。请用 --remote-debugging-port=9222 启动已登录浏览器，或设置 PUBLICATION_BROWSER_CDP_URL。`,
      generated_at: new Date().toISOString(),
      platforms: Object.fromEntries(
        requestedPlatforms.map((platform) => [
          platform,
          {
            status: "unavailable",
            platform,
            message: "没有可读取的远程调试浏览器，不能进行真实平台摸底。",
            route: { domains: PLATFORM_DOMAINS[platform] || [] },
            field_groups: [],
            option_groups: [],
            operation_steps: [],
            warnings: ["未连接浏览器 CDP，不能读取真实页面选项。"],
          },
        ]),
      ),
    };
  }

  const platforms = {};
  for (const platform of requestedPlatforms) {
    const platformTabs = findPlatformTabs(tabs, platform);
    let tab = platformTabs[0];
    let bootstrapProbeTab = null;
    const bootstrapWarnings = [];
    if (shouldBootstrapProbeInventoryRoute(platform, tab)) {
      const entryUrl = resolvePlatformPublishEntryUrl(platform, tabs, payload);
      if (entryUrl) {
        try {
          bootstrapProbeTab = await createCdpTab(entryUrl);
          if (bootstrapProbeTab?.id) {
            await sleep(1500);
            tab = bootstrapProbeTab;
          }
        } catch (error) {
          bootstrapWarnings.push(`临时打开发布入口用于页面摸底失败：${error.message}`);
        }
      }
    }
    if (!tab) {
      platforms[platform] = {
        status: "needs_open_publish_page",
        platform,
        message: "CDP 已连接，但没有找到该平台已打开的创作/发布页面。",
        route: { domains: PLATFORM_DOMAINS[platform] || [] },
        field_groups: [],
        option_groups: [],
        operation_steps: [],
        warnings: [...bootstrapWarnings, "请在同一个调试浏览器中打开该平台发布页，登录后重新摸底。"],
      };
      continue;
    }
    try {
      const { snapshot, probe_meta } = await probeTabInventory(tab, platform, payload);
      if (summaryOnly) {
        const summary = buildLightweightProbeInventorySummary(platform, tab, snapshot, probe_meta);
        if (bootstrapWarnings.length) {
          summary.warnings = [...new Set([...(summary.warnings || []), ...bootstrapWarnings])].slice(0, 12);
        }
        platforms[platform] = summary;
        continue;
      }
      const inventory = buildInventory(platform, tab, snapshot, probe_meta);
      if (bootstrapWarnings.length) {
        inventory.warnings = [...new Set([...(inventory.warnings || []), ...bootstrapWarnings])].slice(0, 12);
      }
      const sidecarTabs = platformTabs
        .filter((candidate) => candidate.id !== tab.id && candidate.type === "page")
        .slice(0, 4);
      const sidecarRoutes = [];
      for (const sidecarTab of sidecarTabs) {
        try {
          const sidecarSnapshot = await snapshotTab(sidecarTab);
          const sidecarGroups = sidecarOptionGroupsForMerge(
            platform,
            sidecarTab,
            buildOptionGroups(platform, sidecarSnapshot.elements || [], sidecarSnapshot.lines || []),
          );
          inventory.option_groups = mergeOptionGroups(inventory.option_groups, sidecarGroups);
          refreshInventoryCoverage(inventory);
          sidecarRoutes.push({ url: sidecarTab.url || "", title: sidecarTab.title || "" });
        } catch (sidecarError) {
          inventory.warnings = [
            ...(inventory.warnings || []),
            `读取同平台辅助页面失败：${sidecarTab.url || sidecarTab.title || ""}：${sidecarError.message}`,
          ].slice(0, 12);
        }
      }
      if (sidecarRoutes.length) {
        inventory.route = {
          ...(inventory.route || {}),
          related_routes: sidecarRoutes,
        };
        inventory.probe_meta = {
          ...(inventory.probe_meta || {}),
          sidecar_tabs_read: sidecarRoutes,
        };
      }
      refreshInventoryCoverage(inventory);
      platforms[platform] = summaryOnly ? buildCompactProbeInventorySummary(inventory) : inventory;
    } catch (error) {
      platforms[platform] = {
        status: "probe_failed",
        platform,
        message: `读取页面失败：${error.message}`,
        route: { url: tab.url || "", title: tab.title || "", domains: PLATFORM_DOMAINS[platform] || [] },
        field_groups: [],
        option_groups: [],
        operation_steps: [],
        warnings: [...bootstrapWarnings, `读取页面失败：${error.message}`].slice(0, 12),
      };
    } finally {
      if (bootstrapProbeTab?.id) {
        await closeCdpTab(bootstrapProbeTab.id).catch(() => null);
      }
    }
  }
  const statuses = Object.values(platforms).map((item) => item.status);
  const status = statuses.every((item) => item === "unavailable") ? "unavailable" : statuses.some((item) => item === "partial") ? "partial" : "needs_pages";
  return {
    contract: CONTRACT,
    status,
    source: "browser_agent_inventory",
    probe_id: randomUUID(),
    browser: payload.browser || "",
    generated_at: new Date().toISOString(),
    platforms,
  };
}

function sidecarOptionGroupsForMerge(platform, tab, groups) {
  const url = String(tab?.url || "");
  if (platform === "kuaishou" && /\/article\/manage\/collection/.test(url)) {
    return (groups || []).filter((group) => String(group.key || "").includes("collection_catalog"));
  }
  return groups || [];
}

export function buildPublicationHealthPayload({ cdpStatus = "ok", cdpError = "", creatorSessions = {} } = {}) {
  const normalizedCreatorSessions = creatorSessions && typeof creatorSessions === "object" ? creatorSessions : {};
  return {
    status: "ok",
    contract: CONTRACT,
    cdp_url: CDP_URL,
    cdp_status: cdpStatus,
    cdp_error: cdpError,
    service_script_sha256: SERVICE_SCRIPT_SHA256,
    attached_profile_binding: ATTACHED_PROFILE_ID
      ? {
          browser: ATTACHED_BROWSER,
          user_data_dir: normalizeProfilePath(ATTACHED_USER_DATA_DIR),
          profile_directory: ATTACHED_PROFILE_DIRECTORY,
          profile_id: ATTACHED_PROFILE_ID,
        }
      : null,
    capabilities: {
      inventory_probe: true,
      publication_tasks: true,
      task_reconcile: true,
      task_identity_echo: true,
      task_identity_contract: PUBLICATION_TASK_IDENTITY_CONTRACT,
      creator_session_probe: true,
      creator_session_contract: PUBLICATION_CREATOR_SESSION_CONTRACT,
      live_publish: LIVE_PUBLISH_ENABLED && FINAL_PUBLISH_EXECUTOR_IMPLEMENTED,
      final_publish_executor: FINAL_PUBLISH_EXECUTOR_IMPLEMENTED,
      final_publish_platforms: [...FINAL_PUBLISH_PLATFORMS],
      composite_publish_platforms: [...COMPOSITE_PUBLISH_PLATFORMS],
      platform_composite_frameworks: DEDICATED_PLATFORM_FRAMEWORK_IDS,
      legacy_lightweight_scripts_blocked: true,
      supervised_draft_prepare: true,
      profile_reuse: Boolean(ATTACHED_PROFILE_ID),
      auto_create_platform_tabs: Boolean(ALLOW_PUBLICATION_TAB_AUTOCREATE),
      profile_binding_mode: ATTACHED_PROFILE_ID ? "persistent_profile" : "cdp_only",
      reusable_profile_ids: ATTACHED_PROFILE_ID ? [ATTACHED_PROFILE_ID] : [],
    },
    creator_sessions: normalizedCreatorSessions,
  };
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
    if (req.method === "GET" && url.pathname === "/healthz") {
      let cdpStatus = "ok";
      let cdpError = "";
      let creatorSessions = {};
      try {
        await listCdpTabs();
        const shouldCheckSession = /^(1|true|yes)$/i.test(String(url.searchParams.get("check_session") || "").trim());
        const requestedPlatforms = String(url.searchParams.get("platforms") || "")
          .split(",")
          .map(normalizePlatform)
          .filter(Boolean);
        if (shouldCheckSession && requestedPlatforms.length) {
          creatorSessions = Object.fromEntries(
            await Promise.all(
              requestedPlatforms.map(async (platform) => [platform, await probeCreatorSession(platform)]),
            ),
          );
        }
      } catch (error) {
        cdpStatus = "unavailable";
        cdpError = error.message;
      }
      jsonResponse(res, 200, buildPublicationHealthPayload({ cdpStatus, cdpError, creatorSessions }));
      return;
    }
    if (req.method === "POST" && url.pathname === "/probes") {
      const payload = await readRequestJson(req);
      if (payload.contract && payload.contract !== CONTRACT) {
        jsonResponse(res, 400, { status: "error", message: `unsupported contract ${payload.contract}` });
        return;
      }
      jsonResponse(res, 200, { result: await handleProbe(payload) });
      return;
    }
    if (req.method === "POST" && url.pathname === "/tasks") {
      const payload = await readRequestJson(req);
      if (payload.contract && !TASK_CONTRACTS.has(payload.contract)) {
        jsonResponse(res, 400, { status: "error", message: `unsupported contract ${payload.contract}` });
        return;
      }
      const task = startPublicationTask(payload);
      jsonResponse(res, 202, { task: serializeTask(task) });
      return;
    }
    if (req.method === "GET" && url.pathname.startsWith("/tasks/")) {
      const taskId = decodeURIComponent(url.pathname.slice("/tasks/".length));
      const task = TASKS.get(taskId);
      if (!task) {
        jsonResponse(res, 404, { status: "not_found", message: `task ${taskId} not found` });
        return;
      }
      jsonResponse(res, 200, { task: serializeTask(task) });
      return;
    }
    jsonResponse(res, 404, { status: "not_found" });
  } catch (error) {
    jsonResponse(res, 500, { status: "error", message: error.message });
  }
});

if (IS_MAIN) {
  server.listen(PORT, HOST, () => {
    console.log(`publication browser-agent inventory service listening on http://${HOST}:${PORT}`);
    console.log(`CDP target: ${CDP_URL}`);
  });
}
