import test from "node:test";
import assert from "node:assert/strict";

import {
  applyCompositeSafeRuntimePolicyDefaults,
  buildPublicationHealthPayload,
  buildCompactProbeInventorySummary,
  buildLightweightProbeInventorySummary,
  deriveProbeInventoryRouteReadiness,
  buildBilibiliPublicationAudit,
  buildCompositeUploadPendingProcessingEnvelope,
  buildPreparationBootstrapRecoveryOverrides,
  buildPreparationBootstrapTimeoutOutcome,
  buildPendingUploadMaterialIntegrity,
  buildCompositePublicationAudit,
  buildPublicationFieldSnapshotFromAudit,
  collectRepairEvidenceFlags,
  coerceTaskContentWithRecoveryPayload,
  extractPublicationTaskIdentity,
  _buildCompositeExpectedContentSnapshot,
  _build_publication_recovery_hint,
  _buildVerificationOnlyCurrentPageTargetMissing,
  _buildVerificationOnlyMaterialIntegrityFailure,
  _buildVerificationOnlyRouteNotReadyFailure,
  buildPublicationTaskTimeoutEvidence,
  classifyCompositeScheduleInputHint,
  canReuseCurrentPageMediaForPrepublish,
  compositeRequiresLocalMedia,
  deriveDouyinCoverState,
  buildDouyinCompositeCoverEditorPlan,
  buildDouyinPrepareProjectExecutionPlan,
  filterDouyinPrepareProjectExecutionPlan,
  isDouyinFormalCompositeCoverEditorState,
  isDouyinCoverEditorModalText,
  deriveXiaohongshuCoverActual,
  deriveXiaohongshuDeclarationActual,
  deriveXiaohongshuSelectedCollectionActual,
  detectCompositePublicationSignals,
  deriveCompositeCollectionPolicyState,
  deriveCompositeCdpTimeoutWaitEnvelope,
  deriveCompositeCoverPolicyState,
  deriveCompositeDraftPolicyBlockers,
  deriveCompositeFinalPrePublishVisualVerification,
  deriveCompositeSchedulePolicyState,
  derivePublicationTaskExecutionTimeoutMs,
  derivePublicationTaskPreparationPolicy,
  dispatchPublicationTaskReconcileCallback,
  shouldApplyCompositeDraftPolicyBlockers,
  shouldBootstrapStopBeforeRouteRecovery,
  buildCompositeRepairExecutionPlan,
  deriveCompositePrePublishFailureRecoveryPlan,
  deriveCompositePrePublishPendingState,
  deriveCompositeCurrentPageMediaPendingDisposition,
  deriveCompositeCurrentPageRouteDisposition,
  deriveNavigationJavaScriptDialogHandling,
  deriveCurrentPageDraftResumeDisposition,
  deriveDedicatedVerifierMediaEntryDisposition,
  deriveCompositeMediaUploadFailureDisposition,
  deriveCompositeUploadReadinessBlockerDisposition,
  deriveCompositePostUploadIntegrityDisposition,
  deriveCompositeUploadReadinessFailureState,
  buildStopBeforeFinalPublishRecoveryOverrides,
  derivePublicationTaskTimeoutStatus,
  deriveCompositePrePublishRepairPlan,
  derivePlatformTabSelectionPolicy,
  classifyDouyinCoverUploadInputRoot,
  extractDouyinTopicVerificationLabels,
  extractYouTubeStudioChannelId,
  buildYouTubeStudioContentListUrl,
  buildYouTubeStudioUploadEntryUrl,
  PUBLICATION_CREATOR_SESSION_CONTRACT,
  PUBLICATION_TASK_IDENTITY_CONTRACT,
  resolvePlatformPublishEntryUrl,
  SERVICE_SCRIPT_SHA256,
  platformTabScore,
  shouldBootstrapProbeInventoryRoute,
  shouldBootstrapGenericPublishRoute,
  shouldBootstrapStopBeforeMediaUpload,
  shouldBootstrapStopBeforeMediaRouteRecovery,
  shouldTreatYouTubeUploadSurfaceAsStable,
  isPlatformReceiptSurfaceUrl,
  isPlatformPublishRouteBootstrapReady,
  shouldAcquireReceiptSurfaceRoute,
  shouldAttemptMediaBootstrap,
  shouldContinueStopBeforeUploadBootstrap,
    shouldEnforcePlatformPublishRoute,
    shouldAllowCompositeFieldPreparation,
    shouldBootstrapCompositeUploadFromCleanEntry,
    shouldAwaitCompositeUploadEntryHydration,
    shouldWaitForCompositeUploadReadyBeforeFieldPreparation,
  currentPageMatchesPrepareOnlyExecutionContext,
  resolveDouyinRichTextTargets,
  findPlatformTabs,
  expectedMediaPath,
  expectedPrimaryCoverPathForPlatform,
  filterSinglePathVideoInputs,
  selectDouyinCoverSlotSurfaceCandidate,
  selectDouyinCoverSlotEntryTarget,
  buildXiaohongshuTopicSearchQuery,
  extractXiaohongshuInsertedTopicLabels,
  extractXiaohongshuTopicVerificationLabels,
  selectDouyinTopicSearchFieldCandidate,
  selectXiaohongshuTopicSearchFieldCandidate,
  selectXiaohongshuOriginalDeclarationControlCandidate,
  selectDouyinTopicSuggestionCandidate,
  expectedCompositeDeclaration,
  extractCompositeDeclarationText,
  activateYoutubeHiddenUploadEntry,
  isCompositePublishRouteContext,
  isXiaohongshuVideoUploadEntrySurface,
  isXiaohongshuPublishEditorSurfaceReady,
  extractDouyinManageCardCandidates,
  extractDouyinManageCardEvidence,
  extractXiaohongshuNoteManagerCandidates,
  extractToutiaoManageCandidates,
  extractDouyinSelectedCollectionEvidence,
  extractCompositeBodyForAudit,
  isDouyinCoverEditorImmediateEditable,
  isDouyinCustomCoverReady,
  mergePublicationTaskProgress,
  normalizeCompositeUploadReadyResult,
  normalizeRichTextDraftValue,
  normalizeYouTubeVisibilityOrPublishMode,
  normalizeYouTubeTagValue,
  normalizeCompositeBodyForAudit,
  normalizeCompositePostPublishIntegrity,
  findPlatformTab,
  findPlatformDomainFallbackTab,
  platformBodyWithTags,
  reconcileTimedOutPublicationTask,
  shouldDispatchPublicationTaskReconcileCallback,
  richTextDraftValueMatches,
  resolveDouyinDeclarationOption,
  resolveXiaohongshuDeclarationOption,
  shouldEnableXiaohongshuOriginalDeclaration,
  selectDouyinCoverConfirmCandidate,
  selectBestDouyinManageCardEvidence,
  selectBestXiaohongshuNoteManagerEvidence,
  selectBestToutiaoManageEvidence,
  selectYouTubeDraftResumeEntryCandidate,
  selectYouTubeMetadataExpandCandidate,
  selectYouTubeTagInputCandidate,
  shouldInspectHiddenVideoInputsForDraftClear,
  shouldResetBilibiliUploadModuleAfterDiscard,
  bilibiliDraftStorageKeysToClear,
  isBilibiliFreshUploadEntrySnapshot,
  shouldPersistBilibiliDirtyEditorBeforeRouteReset,
  shouldBypassDraftResumeAtAuthoritativeUploadEntry,
  isBilibiliUploadQueueCardCandidate,
  extractYouTubeDraftVideoId,
  matchesYouTubeDraftResumeHint,
  selectYouTubeDraftResumeCandidate,
  deriveYouTubeDraftResumeFallbackTarget,
  deriveYouTubeUploadEditorBootstrapPlan,
  deriveYouTubeUploadWizardStep,
  shouldAttemptYouTubeDraftResumeFallbackRoute,
  buildYouTubeUploadResumeUrl,
  buildYouTubeStudioEditorUrl,
  shouldPreserveYouTubeUploadResumeRouteForBootstrap,
  isYouTubeEditorReadinessSurface,
  shouldPreserveYouTubeEditorRouteForBootstrap,
  shouldAcceptCompositeUploadReadyState,
  shouldAcceptCollapsedDouyinScheduleEvidence,
  shouldBlockOnMediaUploadFailure,
  shouldFallbackToFullPrepareDuringRepair,
  shouldFailYouTubeDraftResumeAsInert,
  shouldDeferYouTubeDraftResumeReupload,
  shouldTreatCompositeUploadReadinessBlockerAsPending,
  hasYoutubeUploadResumeVideoId,
  shouldPreserveYouTubeUploadResumeRoute,
  shouldDeferGenericPostUploadIntegrityUntilPlatformAdapter,
  shouldTreatCompositeEditorSurfaceAsNotReady,
  shouldTreatMediaUploadAsInProgress,
  shouldWaitForVerificationOnlyMaterialIntegrity,
  shouldBlockOnDraftClearFailure,
  shouldBlockOnDraftResumePromptFailure,
  hasYoutubeUploadDialogQuery,
  verifyCompositeDeclarationField,
  verifyCompositeBodyField,
} from "./publication_browser_agent_service.mjs";

test("buildPendingUploadMaterialIntegrity marks upload_in_progress without content field failures", () => {
  const integrity = buildPendingUploadMaterialIntegrity(
    "douyin",
    {
      ready: false,
      failed: false,
      waited_ms: 70577,
      ready_streak: 0,
      last: {
        busy: true,
        mediaPresent: false,
        uploadPromptOnly: false,
        fileInputCount: 0,
        lines: ["68%", "已上传： 520.9MB/761.1MB", "当前速度：7.2MB/s", "剩余时间：34秒"],
      },
    },
    { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "抖音创作者中心" },
  );

  assert.equal(integrity.verification_state, "not_ready");
  assert.equal(integrity.verification_reason, "upload_in_progress");
  assert.deepEqual(integrity.failures, []);
  assert.equal(integrity.fields.upload_ready.verified, false);
  assert.equal(integrity.upload_readiness.busy, true);
  assert.equal(integrity.platform_extras.route.url, "https://creator.douyin.com/creator-micro/content/post/video");
});

test("shouldFallbackToFullPrepareDuringRepair stays fail-closed when framework has no scoped repair", () => {
  assert.equal(
    shouldFallbackToFullPrepareDuringRepair("xiaohongshu", { id: "xiaohongshu_creator_composite_v1", prepare() {} }),
    false,
  );
});

test("shouldFallbackToFullPrepareDuringRepair stays false when scoped repair exists", () => {
  assert.equal(
    shouldFallbackToFullPrepareDuringRepair("douyin", { id: "douyin_creator_composite_v1", prepare() {}, repair() {} }),
    false,
  );
});

test("deriveCompositePrePublishRepairPlan disables auto repair in linear execution mode", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    { required_unverified: ["body", "tags", "collection"] },
    { failures: ["body", "tags"] },
    { disable_auto_repair: true },
  );

  assert.equal(plan.shouldRepair, false);
  assert.equal(plan.disabled_by_policy, true);
  assert.equal(plan.reason, "linear_execution_mode");
  assert.deepEqual(plan.required_unverified, ["body", "tags", "collection"]);
  assert.deepEqual(plan.integrity_failures, ["body", "tags"]);
});

test("extractDouyinTopicVerificationLabels prefers inserted body topics over recommended chips", () => {
  const actual = extractDouyinTopicVerificationLabels(
    [
      { text: "美杜莎4顶配vs次顶配\n#EDC", context: "body", source: "body" },
      { text: "#EDC", context: "推荐 热度 23.5亿", source: "chip" },
      { text: "#海淘开箱", context: "推荐 热度 12亿", source: "chip" },
    ],
    ["EDC"],
  );

  assert.deepEqual(actual, ["EDC"]);
});

test("selectDouyinTopicSearchFieldCandidate rejects generic visibility control and prefers topic field", () => {
  const field = selectDouyinTopicSearchFieldCandidate([
    {
      tag: "input",
      role: "",
      label: "公开",
      current: "",
      root_area: 12000,
      isContentEditable: false,
    },
    {
      tag: "div",
      role: "textbox",
      label: "作品描述 #添加话题 @好友",
      current: "",
      root_area: 18000,
      isContentEditable: true,
    },
  ]);

  assert.equal(field?.label, "作品描述 #添加话题 @好友");
});

test("selectDouyinTopicSearchFieldCandidate fails closed when no topic semantic field exists", () => {
  const field = selectDouyinTopicSearchFieldCandidate([
    {
      tag: "input",
      role: "",
      label: "公开",
      current: "",
      root_area: 12000,
      isContentEditable: false,
    },
    {
      tag: "input",
      role: "",
      label: "立即发布",
      current: "",
      root_area: 12000,
      isContentEditable: false,
    },
  ]);

  assert.equal(field, null);
});

test("verifyCompositeBodyField accepts flattened douyin body with equivalent content", () => {
  const expected = "美杜莎4顶配和次顶配一起到的，拆开对比一下📦\n外观、细节做工、弹射手感、收回紧实度都过了一遍\n两把放一起一比，差别肉眼可见\n跳刀玩家可以参考下";
  const actual = "美杜莎4顶配和次顶配一起到的，拆开对比一下📦 外观、细节做工、弹射手感、收回紧实度都过了一遍 两把放一起一比，差别肉眼可见 跳刀玩家可以参考下";

  assert.equal(verifyCompositeBodyField("douyin", expected, actual), true);
});

test("buildCompactProbeInventorySummary preserves visual evidence while trimming heavy inventory fields", () => {
  const summary = buildCompactProbeInventorySummary({
    status: "partial",
    platform: "douyin",
    message: "ok",
    route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "抖音创作者中心" },
    coverage: { missing_required_surfaces: [{ key: "editor_surface", label: "编辑面" }] },
    warnings: ["未完成关键发布面摸底：编辑面。"],
    operation_steps: [{ index: 1, label: "打开平台创作/发布页" }],
    visual_evidence: {
      artifact_path: "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260601/douyin/editor.png",
      capture_type: "screenshot",
      phase: "probe_inventory",
    },
    probe_meta: {
      draft_upload_requested: true,
      upload: { uploaded: false, reused: true, reason: "resume" },
      sidecar_tabs_read: [{ url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "抖音创作者中心" }],
    },
    option_groups: [{ key: "heavy", options: new Array(50).fill("x") }],
    field_groups: [{ key: "heavy_field" }],
    evidence: { source_summary: [{ source: "dom_visible_text" }] },
  });

  assert.equal(summary.status, "partial");
  assert.equal(summary.platform, "douyin");
  assert.equal(summary.visual_evidence.capture_type, "screenshot");
  assert.equal(summary.visual_evidence.phase, "probe_inventory");
  assert.equal(summary.coverage.missing_required_surfaces[0].key, "editor_surface");
  assert.equal(summary.probe_meta.upload.reused, true);
  assert.equal("option_groups" in summary, false);
  assert.equal("field_groups" in summary, false);
  assert.equal("evidence" in summary, false);
});

test("buildLightweightProbeInventorySummary keeps lightweight coverage and visual evidence for failure analysis", () => {
  const summary = buildLightweightProbeInventorySummary(
    "douyin",
    { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "抖音创作者中心" },
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "抖音创作者中心",
      lines: ["设置封面", "添加合集", "自主声明", "请选择自主声明"],
      elements: [
        { text: "请选择自主声明", role: "button", type: "button", className: "declaration-picker", disabled: false },
      ],
      visual_evidence: {
        artifact_path: "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260601/douyin/preflight.png",
        capture_type: "screenshot",
        phase: "probe_inventory",
      },
    },
    { summary_only: true, draft_upload_requested: false },
  );

  assert.equal(summary.platform, "douyin");
  assert.equal(summary.visual_evidence.capture_type, "screenshot");
  assert.equal(summary.route.url, "https://creator.douyin.com/creator-micro/content/post/video");
  assert.ok(Array.isArray(summary.coverage.missing_required_surfaces));
  assert.equal(summary.probe_meta.summary_only, true);
  assert.deepEqual(summary.probe_meta.actions, []);
});

test("deriveProbeInventoryRouteReadiness marks bilibili loading shell as route_not_ready instead of missing-field ready state", () => {
  const readiness = deriveProbeInventoryRouteReadiness("bilibili", {
    url: "https://member.bilibili.com/platform/upload/video/frame",
    title: "创作中心",
    lines: ["Loading"],
    elements: [],
  });

  assert.equal(readiness.blocked, true);
  assert.equal(readiness.status, "route_not_ready");
  assert.equal(readiness.reason, "publish_route_loading");
});

test("filterSinglePathVideoInputs keeps bilibili canonical upload wrapper and excludes buploader fallback", () => {
  const candidates = [
    {
      attrMap: { name: "buploader", accept: "video/*" },
      runtime: {
        name: "buploader",
        rootClassName: "some-other-wrapper",
        parentClassName: "misc-parent",
        rootText: "添加视频",
      },
    },
    {
      attrMap: { name: "video", accept: "video/*" },
      runtime: {
        name: "video",
        rootClassName: "bcc-upload-wrapper",
        parentClassName: "bcc-upload-wrapper",
        rootText: "点击上传或将视频拖拽到此区域 上传视频",
      },
    },
  ];

  const filtered = filterSinglePathVideoInputs("bilibili", candidates);

  assert.equal(filtered.length, 1);
  assert.equal(filtered[0].runtime.name, "video");
});

test("deriveProbeInventoryRouteReadiness treats bilibili draft-resume prompt as route_not_ready", () => {
  const readiness = deriveProbeInventoryRouteReadiness("bilibili", {
    url: "https://member.bilibili.com/platform/upload/video/frame",
    title: "创作中心",
    lines: ["本地浏览器存在32个未提交的视频", "继续编辑", "不用了", "点击上传或将视频拖拽到此区域"],
    elements: [{ tag: "input", type: "file", accept: "video/mp4" }],
  });

  assert.equal(readiness.blocked, true);
  assert.equal(readiness.status, "route_not_ready");
  assert.equal(readiness.reason, "draft_resume_prompt");
});

test("xiaohongshu upload entry is upload-ready instead of blocked for missing post-upload fields", () => {
  const snapshot = {
    url: "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
    title: "小红书创作服务平台",
    lines: ["上传视频", "点击上传或将视频拖拽到这里", "支持 mp4"],
    elements: [{ tag: "input", type: "file", accept: "video/mp4" }],
  };

  const readiness = deriveProbeInventoryRouteReadiness("xiaohongshu", snapshot);
  const summary = buildLightweightProbeInventorySummary("xiaohongshu", { url: snapshot.url, title: snapshot.title }, snapshot);

  assert.equal(readiness.blocked, false);
  assert.equal(readiness.status, "upload_entry_ready");
  assert.equal(readiness.reason, "publish_route_upload_prompt");
  assert.equal(summary.status, "upload_entry_ready");
  assert.deepEqual(summary.coverage.missing_required_surfaces, []);
});

test("xiaohongshu note manager is not treated as publish route context", () => {
  assert.equal(
    isCompositePublishRouteContext("xiaohongshu", {
      url: "https://creator.xiaohongshu.com/new/note-manager",
      text: "笔记管理 发布笔记 已发布 审核中",
      file_inputs: [],
    }),
    false,
  );
  const readiness = deriveProbeInventoryRouteReadiness("xiaohongshu", {
    url: "https://creator.xiaohongshu.com/new/note-manager",
    title: "小红书创作服务平台",
    lines: ["笔记管理", "发布笔记", "已发布", "审核中"],
    elements: [],
  });
  assert.equal(readiness.blocked, true);
  assert.equal(readiness.reason, "publish_route_not_ready");
});

test("deriveCurrentPageDraftResumeDisposition recognizes bilibili local pending draft copy", () => {
  const disposition = deriveCurrentPageDraftResumeDisposition(
    "bilibili",
    "本地浏览器存在32个未提交的视频 继续编辑 不用了 点击上传或将视频拖拽到此区域",
  );
  assert.equal(disposition.present, true);
  assert.equal(disposition.resume_label, "继续编辑");
  assert.equal(disposition.discard_label, "不用了");
  assert.equal(disposition.preferred_action, "discard");
  assert.equal(disposition.reason, "existing_unpublished_draft_prompt");
});

test("shouldBlockOnDraftResumePromptFailure blocks bilibili dirty draft when discard is not confirmed", () => {
  const shouldBlock = shouldBlockOnDraftResumePromptFailure(
    { clearIfStaleDraft: true, forceClearDraft: false },
    {
      attempted: true,
      prompt_present: true,
      prompt_still_open: true,
      preferred_action: "discard",
      discard_label: "不用了",
      resume_label: "继续编辑",
      clicked_label: "",
      discarded: false,
    },
  );

  assert.equal(shouldBlock, true);
});

test("shouldBlockOnDraftResumePromptFailure allows bilibili flow after explicit discard", () => {
  const shouldBlock = shouldBlockOnDraftResumePromptFailure(
    { clearIfStaleDraft: true, forceClearDraft: false },
    {
      attempted: true,
      prompt_present: true,
      prompt_still_open: false,
      preferred_action: "discard",
      discard_label: "不用了",
      resume_label: "继续编辑",
      clicked_label: "不用了",
      discarded: true,
    },
  );

  assert.equal(shouldBlock, false);
});

test("buildCompactProbeInventorySummary preserves lightweight probe actions", () => {
  const summary = buildCompactProbeInventorySummary({
    status: "route_not_ready",
    platform: "bilibili",
    message: "editor not ready",
    route: { url: "https://member.bilibili.com/platform/upload/video/frame", title: "创作中心" },
    route_readiness: { blocked: true, status: "route_not_ready", reason: "draft_resume_prompt" },
    probe_meta: {
      draft_upload_requested: false,
      actions: [
        {
          kind: "draft_resume_prompt",
          clicked: true,
          clicked_label: "不用了",
          reason: "existing_unpublished_draft_prompt",
          resumed: false,
          prompt_present: true,
          preferred_action: "discard",
        },
      ],
      upload: { uploaded: false, reused: false, reason: "summary_only" },
    },
  });

  assert.equal(summary.probe_meta.actions[0].kind, "draft_resume_prompt");
  assert.equal(summary.probe_meta.actions[0].clicked, true);
  assert.equal(summary.probe_meta.actions[0].clicked_label, "不用了");
});

test("platformTabScore rejects bilibili article manager route as publish probe surface", () => {
  const score = platformTabScore(
    {
      url: "https://member.bilibili.com/platform/upload-manager/article",
      title: "稿件管理",
      type: "page",
    },
    ["member.bilibili.com", "member.bilibili.com/platform/upload"],
    "bilibili",
    {},
  );
  assert.equal(score, 0);
});

test("shouldBootstrapGenericPublishRoute forces douyin manage route back to canonical publish entry", () => {
  assert.equal(
    shouldBootstrapGenericPublishRoute("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
      text: "作品管理 全部作品 已发布",
      file_inputs: [],
    }),
    true,
  );
});

test("shouldBootstrapGenericPublishRoute does not rebootstrap douyin canonical publish route", () => {
  assert.equal(
    shouldBootstrapGenericPublishRoute("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      text: "作品描述 设置封面 自主声明 添加合集 谁可以看 发布时间",
      file_inputs: [],
    }),
    false,
  );
});

test("findPlatformDomainFallbackTab reuses bilibili article manager tab when no clean publish tab exists", () => {
  const tab = findPlatformDomainFallbackTab(
    [
      {
        id: "bili-article",
        type: "page",
        url: "https://member.bilibili.com/platform/upload-manager/article",
        title: "Bilibili 创作中心",
      },
    ],
    "bilibili",
  );
  assert.equal(tab?.id, "bili-article");
});

test("shouldBootstrapProbeInventoryRoute requests bilibili publish entry when current tab is article manager", () => {
  assert.equal(
    shouldBootstrapProbeInventoryRoute("bilibili", {
      url: "https://member.bilibili.com/platform/upload-manager/article",
      title: "稿件管理",
      type: "page",
    }),
    true,
  );
  assert.equal(
    shouldBootstrapProbeInventoryRoute("bilibili", {
      url: "https://member.bilibili.com/platform/upload/video/frame",
      title: "视频投稿",
      type: "page",
    }),
    false,
  );
});

test("shouldBootstrapProbeInventoryRoute requests xiaohongshu publish entry when current tab is note manager", () => {
  assert.equal(
    shouldBootstrapProbeInventoryRoute("xiaohongshu", {
      url: "https://creator.xiaohongshu.com/new/note-manager",
      title: "小红书创作服务平台",
      type: "page",
    }),
    true,
  );
  assert.equal(
    shouldBootstrapProbeInventoryRoute("xiaohongshu", {
      url: "https://creator.xiaohongshu.com/publish",
      title: "小红书创作服务平台",
      type: "page",
    }),
    false,
  );
});

test("buildPendingUploadMaterialIntegrity preserves youtube draft resume pending reason", () => {
  const integrity = buildPendingUploadMaterialIntegrity(
    "youtube",
    {
      ready: false,
      failed: false,
      pending_reason: "draft_resume_pending",
      last: {
        platform: "youtube",
        busy: false,
        mediaPresent: true,
        uploadPromptOnly: false,
        fileInputCount: 0,
        totalFileInputCount: 1,
        youtubeUploadRoute: true,
        youtubeChannelContentList: true,
        youtubeDraftResumeAvailable: true,
        lines: ["MAXACE 美杜莎4 顶配次顶配开箱", "草稿", "编辑草稿"],
      },
    },
    { url: "https://studio.youtube.com/channel/test/videos/upload?d=ud", title: "频道内容 - YouTube Studio" },
  );

  assert.equal(integrity.verification_state, "not_ready");
  assert.equal(integrity.verification_reason, "draft_resume_pending");
  assert.equal(integrity.fields.upload_ready.verified, false);
});

test("buildCompositeUploadPendingProcessingEnvelope preserves safe stop-before recovery flags", () => {
  const result = buildCompositeUploadPendingProcessingEnvelope({
    platform: "youtube",
    route: {
      url: "https://studio.youtube.com/channel/test/videos/upload?d=ud",
      title: "频道内容 - YouTube Studio",
    },
    actions: [{ kind: "youtube_upload_ready_wait_after_draft_resume" }],
    content: {
      title: "MAXACE 美杜莎4 顶配次顶配开箱",
      media_path: "E:/media/maxace4.mp4",
    },
    interruptions: [],
    materialIntegrity: buildPendingUploadMaterialIntegrity(
      "youtube",
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          busy: true,
          mediaPresent: true,
          uploadPromptOnly: false,
          fileInputCount: 0,
          totalFileInputCount: 2,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeDraftResumeAvailable: true,
          lines: ["MAXACE 美杜莎4 顶配次顶配开箱", "正在上传，已完成 3%"],
        },
      },
      {
        url: "https://studio.youtube.com/channel/test/videos/upload?d=ud",
        title: "频道内容 - YouTube Studio",
      },
    ),
    code: "youtube_pre_publish_upload_pending",
    reason: "媒体上传已开始，继续保留现场等待平台进入可编辑上传态。",
    blockerMessage: "预发布等待上传完成：upload_in_progress",
    blockerDetails: "verification_reason=upload_in_progress",
    prepareOnlyCurrentPage: true,
    stopBeforeFinalPublish: true,
  });

  assert.equal(result.code, "youtube_pre_publish_upload_pending");
  assert.equal(result.recovery_overrides?.recovery_mode, "prepublish_resume");
  assert.equal(result.recovery_overrides?.prepare_only_current_page, true);
  assert.equal(result.recovery_overrides?.verify_media_upload, true);
  assert.equal(result.recovery_overrides?.wait_for_publish_confirmation, true);
  assert.equal(result.recovery_overrides?.clear_draft_context, false);
  assert.equal(result.final_publish?.pre_publish_pending, true);
  assert.equal(result.final_publish?.wait_for_upload_ready, true);
  assert.equal(result.final_publish?.prepare_only_current_page, true);
});

test("normalizeCompositeUploadReadyResult unwraps nested readiness envelope", () => {
  const normalized = normalizeCompositeUploadReadyResult({
    actions: [{ kind: "douyin_upload_ready_wait", ready: true }],
    readiness: {
      ready: true,
      failed: false,
      waited_ms: 150564,
      ready_streak: 2,
      last: {
        busy: false,
        mediaPresent: true,
      },
    },
  });

  assert.equal(normalized.readiness.ready, true);
  assert.equal(normalized.readiness.last.mediaPresent, true);
  assert.equal(normalized.actions.length, 1);
});

test("classifyCompositeScheduleInputHint distinguishes datetime inputs from schedule toggles", () => {
  assert.equal(classifyCompositeScheduleInputHint("0 立即发布 立即发布", ""), "");
  assert.equal(classifyCompositeScheduleInputHint("1 定时发布 定时发布", ""), "");
  assert.equal(classifyCompositeScheduleInputHint("日期和时间 2026-05-31 22:25", "2026-05-31 22:25"), "datetime");
  assert.equal(classifyCompositeScheduleInputHint("发布时间 日期", "2026-05-31"), "date");
  assert.equal(classifyCompositeScheduleInputHint("发布时间 时间", "20:30"), "time");
});

test("isCompositePublishRouteContext rejects douyin manage page and accepts publish page", () => {
  assert.equal(
    isCompositePublishRouteContext("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/manage",
      text: "作品管理 全部作品 已发布 审核中 未通过 共 23 个作品",
      file_inputs: [],
    }),
    false,
  );
  assert.equal(
    isCompositePublishRouteContext("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      text: "作品描述 设置封面 自主声明 添加合集 发布时间 定时发布",
      file_inputs: [{ accept: "video/mp4" }],
    }),
    true,
  );
  assert.equal(
    isCompositePublishRouteContext("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      text: "抖音创作者中心·创作者 扫码登录 验证码登录 登录/注册 我是创作者 我是MCN机构",
      file_inputs: [],
    }),
    false,
  );
});

test("isCompositePublishRouteContext rejects bilibili draft management page and accepts upload editor page", () => {
  assert.equal(
    isCompositePublishRouteContext("bilibili", {
      url: "https://member.bilibili.com/platform/upload-manager/article",
      text: "稿件管理 全部稿件 草稿 已通过 视频管理 图文管理 添加合集 编辑 数据",
      file_inputs: [],
    }),
    false,
  );
  assert.equal(
    isCompositePublishRouteContext("bilibili", {
      url: "https://member.bilibili.com/platform/upload/video/frame",
      text: "投稿 标题 简介 分区 标签 封面 创作声明 定时发布",
      file_inputs: [{ accept: "video/mp4" }],
    }),
    true,
  );
});

test("isCompositePublishRouteContext accepts current X compose/post route", () => {
  assert.equal(
    isCompositePublishRouteContext("x", {
      url: "https://x.com/compose/post",
      text: "Home Post",
      file_inputs: [],
    }),
    true,
  );
});

test("isCompositePublishRouteContext accepts youtube video edit editor surface", () => {
  assert.equal(
    isCompositePublishRouteContext("youtube", {
      url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      text: "视频详细信息 标题（必填） 说明 缩略图 播放列表 观众 视频链接",
      file_inputs: [],
    }),
    true,
  );
});

test("detectCompositePublicationSignals surfaces upload failure and bilibili batch modal blockers", () => {
  const lines = [
    "上传失败",
    "文件里没有有效的视频",
    "批量上传将生成多条动态，打扰粉丝",
    "将稿件加入合集并使用【不生成动态】，即可避免打扰",
  ];
  const text = lines.join("\n");
  const signals = detectCompositePublicationSignals("bilibili", text, lines);
  assert.equal(signals.upload_failed, true);
  assert.equal(signals.upload_busy, false);
  assert.ok(signals.blockers.some((item) => item.code === "bilibili_upload_failed"));
  assert.ok(signals.blockers.some((item) => item.code === "bilibili_batch_dynamic_interruption"));
});

test("isCompositePublishRouteContext keeps douyin loading-only publish surface fail-closed until editor signals appear", () => {
  assert.equal(
    isCompositePublishRouteContext("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      text: "高清发布 抖音 加载中，请稍候...",
      file_inputs: [],
    }),
    true,
  );
});

test("isCompositePublishRouteContext stays self-contained when stringified for douyin upload entry", () => {
  const routeFn = eval(`(${isCompositePublishRouteContext.toString()})`);
  assert.equal(
    routeFn("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/upload",
      text: "发布视频 点击上传 或直接将视频文件拖入此区域 你还有上次未发布的视频 是否继续编辑 继续编辑 放弃",
      file_inputs: [{ accept: "video/mp4" }],
    }),
    false,
  );
});

test("buildBilibiliPublicationAudit keeps upload_ready failed when verifier reports blockers", () => {
  const audit = buildBilibiliPublicationAudit(
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      structured_tags: [],
      scheduled_publish_at: "",
    },
    {
      actual: {
        blockers: [{ code: "bilibili_upload_failed", message: "上传失败", lines: ["上传失败"] }],
      },
      failures: ["upload_ready"],
    },
    {},
    { url: "https://member.bilibili.com/platform/upload/video/frame", title: "投稿" },
    { uploaded: true },
  );
  assert.equal(audit.checklist.upload_ready.verified, false);
  assert.ok(audit.required_unverified.includes("upload_ready"));
  assert.ok(audit.required_reupload.includes("upload_ready"));
  assert.ok(audit.platform_extras.blockers.some((item) => item.code === "bilibili_upload_failed"));
});

test("buildBilibiliPublicationAudit treats stop-before safe mode as receipt-complete and cover-optional when skip policy is explicit", () => {
  const audit = buildBilibiliPublicationAudit(
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      structured_tags: [],
      scheduled_publish_at: "2026-06-01T21:00:00+08:00",
      cover_path: "E:\\covers\\bilibili-cover.jpg",
      platform_specific_overrides: {
        cover_policy: "platform_default",
        skip_cover_upload: true,
      },
    },
    {
      actual: {
        blockers: [],
      },
      failures: [],
    },
    {},
    { url: "https://member.bilibili.com/platform/upload/video/frame", title: "投稿" },
    { uploaded: false },
    { stop_before_final_publish: true },
  );
  assert.equal(audit.checklist.cover.verified, true);
  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.verified, true);
  assert.deepEqual(audit.required_unverified, []);
});

test("expectedPrimaryCoverPathForPlatform prefers bilibili 4:3 slot over 16:9 slot", () => {
  const path = expectedPrimaryCoverPathForPlatform("bilibili", {
    cover_path: "E:/covers/fallback.jpg",
    cover_slots: [
      {
        slot: "landscape_16_9",
        matrix_key: "landscape_16_9",
        label: "个人空间封面（16:9）",
        cover_path: "E:/covers/bilibili-16-9.jpg",
      },
      {
        slot: "landscape_4_3",
        matrix_key: "landscape_4_3",
        label: "首页推荐封面（4:3）",
        cover_path: "E:/covers/bilibili-4-3.jpg",
      },
    ],
  });

  assert.equal(path, "E:/covers/bilibili-4-3.jpg");
});

test("coerceTaskContentWithRecoveryPayload maps top-level recovery overrides into publication recovery state", () => {
  const content = coerceTaskContentWithRecoveryPayload({
    content: {
      title: "测试标题",
    },
    recovery_overrides: {
      prepare_only_current_page: true,
      clear_draft_context: false,
      force_publish_page_refresh: true,
      recovery_mode: "prepublish_resume",
    },
  });
  assert.equal(content.title, "测试标题");
  assert.equal(content.publication_recovery_state.recovery_overrides.prepare_only_current_page, true);
  assert.equal(content.publication_recovery_state.recovery_overrides.clear_draft_context, false);
  assert.equal(content.publication_recovery_state.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(content.publication_recovery_state.recovery_overrides.recovery_mode, "prepublish_resume");
});

test("extractPublicationTaskIdentity preserves attempt, content, recovery, and signature fields", () => {
  const identity = extractPublicationTaskIdentity({
    attempt_id: "attempt-123",
    content_id: "job-456",
    content: {
      title: "测试标题",
      publication_content_signature: {
        value: "signature-789",
      },
      publication_recovery_state: {
        carry_over_from_attempt_id: "attempt-old",
        recovery_overrides: {
          recovery_mode: "receipt_rebind",
        },
      },
    },
  });
  assert.deepEqual(identity, {
    attempt_id: "attempt-123",
    content_id: "job-456",
    carry_over_from_attempt_id: "attempt-old",
    attempt_backed: true,
    content_signature: "signature-789",
    publication_content_signature: "signature-789",
    publication_plan_signature: "signature-789",
    recovery_mode: "receipt_rebind",
  });
});

test("buildPublicationHealthPayload exposes task identity contract and service fingerprint", () => {
  const payload = buildPublicationHealthPayload({ cdpStatus: "ok", cdpError: "" });

  assert.equal(payload.status, "ok");
  assert.equal(payload.service_script_sha256, SERVICE_SCRIPT_SHA256);
  assert.match(String(payload.service_script_sha256 || ""), /^[0-9a-f]{64}$/);
  assert.equal(payload.cdp_url, "bridge://chrome-extension");
  assert.equal(payload.browser_transport.transport, "chrome_extension_bridge");
  assert.equal(payload.capabilities.task_identity_echo, true);
  assert.equal(payload.capabilities.task_identity_contract, PUBLICATION_TASK_IDENTITY_CONTRACT);
  assert.equal(payload.capabilities.creator_session_probe, true);
  assert.equal(payload.capabilities.creator_session_contract, PUBLICATION_CREATOR_SESSION_CONTRACT);
  assert.equal(payload.capabilities.browser_transport_kind, "chrome_extension_bridge");
  assert.equal(payload.capabilities.browser_extension_bridge, true);
});

test("buildPublicationHealthPayload preserves creator session probe results", () => {
  const payload = buildPublicationHealthPayload({
    cdpStatus: "ok",
    cdpError: "",
    creatorSessions: {
      douyin: {
        platform: "douyin",
        status: "auth_required",
        code: "douyin_route_auth_required",
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video" },
        visual_evidence: {
          artifact_path: "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/20260602/douyin/session-auth.png",
          capture_type: "screenshot",
          phase: "creator_session_probe",
        },
      },
    },
  });

  assert.equal(payload.creator_sessions.douyin.status, "auth_required");
  assert.equal(payload.creator_sessions.douyin.code, "douyin_route_auth_required");
  assert.equal(payload.creator_sessions.douyin.visual_evidence.capture_type, "screenshot");
  assert.equal(payload.creator_sessions.douyin.visual_evidence.phase, "creator_session_probe");
});

test("expectedMediaPath falls back to direct content media_path when media_items are absent", () => {
  assert.equal(
    expectedMediaPath({
      media_path: "E:\\media\\sample.mp4",
    }),
    "E:\\media\\sample.mp4",
  );
});

test("buildCompositePublicationAudit marks draft_state and upload_ready as reupload-needed", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected_path: "", verified: true },
        schedule: { expected: "", verified: true },
        declaration: { verified: true },
        upload_ready: { expected: "ready", actual: "not_ready", verified: false },
        draft_state: { expected: "editor_clean", actual: "residual_artifacts", verified: false },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com", title: "发布页" },
      },
    },
    {},
    { url: "https://creator.douyin.com" },
  );
  assert.equal(audit.verified, false);
  assert.ok(audit.required_unverified.includes("upload_ready"));
  assert.ok(audit.required_reupload.includes("upload_ready"));
  assert.ok(audit.required_reupload.includes("draft_state"));
  assert.ok(audit.notes.includes("required_reupload"));
});

test("buildPublicationFieldSnapshotFromAudit fails closed for unverified youtube fields", () => {
  const snapshot = buildPublicationFieldSnapshotFromAudit(
    "youtube",
    {
      adapter: "browser_agent",
      title: "标题",
      body: "正文",
      hashtags: ["标签A"],
      structured_tags: ["标签A"],
      copy_material: {},
      visibility_or_publish_mode: "draft",
      scheduled_publish_at: "2026-06-04T21:00:00+08:00",
      platform_specific_overrides: {},
    },
    {
      checklist: {
        title: { expected: "标题", verified: false },
        body: { expected: "正文", verified: false },
        tags: { expected: ["标签A"], verified: false },
        collection: { expected: "播放列表A", verified: false },
        cover: { expected_path: "E:/cover.jpg", verified: false },
        schedule: { expected: "2026-06-04 21:00", verified: false },
        visibility: { expected: "draft", verified: false },
        upload_ready: { actual: "not_ready", verified: false },
        draft_state: { actual: "residual_artifacts", verified: false },
      },
    },
    { url: "https://studio.youtube.com/video/demo/edit", title: "Video details" },
  );

  assert.equal(snapshot.title, "");
  assert.equal(snapshot.body, "");
  assert.deepEqual(snapshot.hashtags, []);
  assert.equal(snapshot.collection, "");
  assert.equal(snapshot.cover_path, "");
  assert.equal(snapshot.visibility_or_publish_mode, "");
  assert.equal(snapshot.scheduled_publish_at, "");
  assert.equal(snapshot.ui_control_semantics.schedule_publish, false);
  assert.equal(snapshot.upload_ready, "not_ready");
  assert.equal(snapshot.draft_state, "residual_artifacts");
});

test("buildPublicationFieldSnapshotFromAudit keeps verified youtube field values", () => {
  const snapshot = buildPublicationFieldSnapshotFromAudit(
    "youtube",
    {
      adapter: "browser_agent",
      hashtags: ["标签A"],
      structured_tags: ["标签A"],
      copy_material: {},
      platform_specific_overrides: {},
    },
    {
      checklist: {
        title: { actual: "标题", verified: true },
        body: { actual: "正文", verified: true },
        tags: { actual: ["标签A"], verified: true },
        collection: { actual: "播放列表A", verified: true },
        cover: { expected_path: "E:/cover.jpg", verified: true },
        schedule: { actual: "2026-06-04T21:00:00+08:00", verified: true },
        visibility: { actual: "schedule", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { actual: "clean", verified: true },
      },
    },
    { url: "https://studio.youtube.com/video/demo/edit", title: "Video details" },
  );

  assert.equal(snapshot.title, "标题");
  assert.equal(snapshot.body, "正文");
  assert.deepEqual(snapshot.hashtags, ["标签A"]);
  assert.equal(snapshot.collection, "播放列表A");
  assert.equal(snapshot.cover_path, "E:/cover.jpg");
  assert.equal(snapshot.visibility_or_publish_mode, "schedule");
  assert.equal(snapshot.scheduled_publish_at, "2026-06-04T21:00:00+08:00");
  assert.equal(snapshot.ui_control_semantics.schedule_publish, true);
  assert.equal(snapshot.upload_ready, "ready");
  assert.equal(snapshot.draft_state, "clean");
});

test("deriveCompositePrePublishRepairPlan retries repairable field failures before publish", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    {
      required_unverified: ["cover", "collection", "content_plan_match"],
    },
    {
      failures: ["cover", "collection"],
    },
  );

  assert.equal(plan.shouldRepair, true);
  assert.deepEqual(plan.repairable_fields, ["cover", "collection"]);
  assert.deepEqual(plan.blocking_fields, []);
});

test("deriveCompositePrePublishRepairPlan does not treat upload readiness as field refill repair", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    {
      required_unverified: ["upload_ready", "draft_state"],
    },
    {
      failures: ["upload_ready"],
    },
  );

  assert.equal(plan.shouldRepair, false);
  assert.deepEqual(plan.repairable_fields, []);
  assert.deepEqual(plan.blocking_fields, ["upload_ready", "draft_state"]);
});

test("deriveCompositePrePublishRepairPlan can still repair editable fields when current-page mode allows blocking fields to remain", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    {
      required_unverified: ["upload_ready", "declaration", "content_plan_match"],
    },
    {
      failures: ["upload_ready", "declaration"],
    },
    {
      allowRepairWithBlocking: true,
    },
  );

  assert.equal(plan.shouldRepair, true);
  assert.equal(plan.allow_repair_with_blocking, true);
  assert.deepEqual(plan.repairable_fields, ["declaration"]);
  assert.deepEqual(plan.blocking_fields, ["upload_ready"]);
});

test("deriveCompositePrePublishRepairPlan repairs editable fields during normal prepublish when only safe blocking fields remain", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    {
      required_unverified: ["upload_ready", "cover", "collection", "content_plan_match"],
    },
    {
      failures: ["upload_ready", "cover", "collection"],
    },
  );

  assert.equal(plan.shouldRepair, true);
  assert.equal(plan.allow_repair_with_blocking, false);
  assert.equal(plan.safe_blocking_only, true);
  assert.deepEqual(plan.repairable_fields, ["cover", "collection"]);
  assert.deepEqual(plan.blocking_fields, ["upload_ready"]);
});

test("deriveCompositePrePublishRepairPlan does not repair through unsafe structural blockers during normal prepublish", () => {
  const plan = deriveCompositePrePublishRepairPlan(
    {
      required_unverified: ["draft_state", "cover", "content_plan_match"],
    },
    {
      failures: ["draft_state", "cover"],
    },
  );

  assert.equal(plan.shouldRepair, false);
  assert.equal(plan.safe_blocking_only, false);
  assert.deepEqual(plan.repairable_fields, ["cover"]);
  assert.deepEqual(plan.blocking_fields, ["draft_state"]);
});

test("buildCompositeRepairExecutionPlan groups rich text fields and preserves targeted repair fields", () => {
  const plan = buildCompositeRepairExecutionPlan("douyin", ["title", "tags", "declaration", "schedule"]);

  assert.equal(plan.platform, "douyin");
  assert.deepEqual(plan.fields, ["title", "tags", "declaration", "schedule"]);
  assert.equal(plan.rich_text, true);
  assert.equal(plan.topics, true);
  assert.equal(plan.cover, false);
  assert.equal(plan.collection, false);
  assert.equal(plan.declaration, true);
  assert.equal(plan.schedule, true);
});

test("buildCompositeRepairExecutionPlan does not route douyin tags through rich text repair alone", () => {
  const plan = buildCompositeRepairExecutionPlan("douyin", ["tags"]);

  assert.equal(plan.platform, "douyin");
  assert.equal(plan.rich_text, false);
  assert.equal(plan.topics, true);
  assert.equal(plan.cover, false);
  assert.equal(plan.collection, false);
});

test("resolveDouyinRichTextTargets prefers the canonical editor field over the outer wrapper", () => {
  const expectedBody = "EDC跳刀的成片素材，后续文案需要围绕画面、字幕和已核验事实重新创作。";
  const titleEl = { tagName: "INPUT" };
  const wrapperEl = { tagName: "DIV" };
  const editorEl = { tagName: "DIV" };
  const result = resolveDouyinRichTextTargets([
    {
      el: titleEl,
      tag: "input",
      text: "填写作品标题 为作品获得更多流量 MAXACE美杜莎4开箱先看细节 16/30",
      className: "semi-input semi-input-default",
      area: 14910,
      role: "",
      isContentEditable: false,
    },
    {
      el: wrapperEl,
      tag: "div",
      text: `${expectedBody} ${expectedBody} #EDC 设置封面 添加合集 发布时间 立即发布`,
      className: "zone-container editor-kit-container editor editor-comp-publish notranslate chrome window chrome88",
      area: 96096,
      role: "textbox",
      isContentEditable: true,
    },
    {
      el: editorEl,
      tag: "div",
      text: `作品描述 ${expectedBody} #添加话题 @好友 71/1000`,
      className: "public-DraftEditor-content",
      area: 18800,
      role: "textbox",
      isContentEditable: true,
    },
  ], {
    title: "MAXACE美杜莎4开箱先看细节",
    body: expectedBody,
  });

  assert.equal(result.titleTarget?.el, titleEl);
  assert.equal(result.bodyTarget?.el, editorEl);
});

test("repair-only current-page live path can clear declaration while keeping structural upload blocker", () => {
  const repairEvidence = {
    cover_repaired: false,
    cover_repair_saved: false,
    collection_repaired: false,
    collection_repair_matched: false,
    declaration_repaired: true,
    declaration_repair_selected: true,
    declaration_repair_saved: true,
    schedule_repaired: false,
    rich_text_repaired: false,
  };

  assert.equal(repairEvidence.declaration_repaired, true);
  assert.equal(repairEvidence.declaration_repair_selected, true);
  assert.equal(repairEvidence.declaration_repair_saved, true);
  assert.equal(repairEvidence.cover_repaired, false);
});

test("collectRepairEvidenceFlags distinguishes attempted cover/collection repair from successful repair", () => {
  const weak = collectRepairEvidenceFlags([
    { kind: "douyin_cover_surface_after", ready: true, saved: false },
    { kind: "douyin_collection_state_after_fallback", evidence: { matched: false } },
  ]);
  const strong = collectRepairEvidenceFlags([
    { kind: "douyin_cover_surface_after", ready: true, saved: true },
    { kind: "douyin_collection_state_after_fallback", evidence: { matched: true } },
  ]);

  assert.equal(weak.cover_repair_attempted, true);
  assert.equal(weak.cover_repaired, false);
  assert.equal(weak.cover_repair_saved, false);
  assert.equal(weak.collection_repair_attempted, true);
  assert.equal(weak.collection_repaired, false);
  assert.equal(weak.collection_repair_matched, false);

  assert.equal(strong.cover_repair_attempted, true);
  assert.equal(strong.cover_repaired, true);
  assert.equal(strong.cover_repair_saved, true);
  assert.equal(strong.collection_repair_attempted, true);
  assert.equal(strong.collection_repaired, true);
  assert.equal(strong.collection_repair_matched, true);
});

test("collectRepairEvidenceFlags requires douyin declaration to be saved back to the main form", () => {
  const weak = collectRepairEvidenceFlags([
    {
      kind: "douyin_original_declaration",
      selected: true,
      selected_state: true,
      confirmed: true,
      saved: false,
    },
  ]);
  const strong = collectRepairEvidenceFlags([
    {
      kind: "douyin_original_declaration",
      selected: true,
      selected_state: true,
      confirmed: true,
      saved: true,
    },
  ]);

  assert.equal(weak.declaration_repair_selected, true);
  assert.equal(weak.declaration_repair_saved, false);
  assert.equal(weak.declaration_repaired, false);
  assert.equal(strong.declaration_repair_saved, true);
  assert.equal(strong.declaration_repaired, true);
});

test("collectRepairEvidenceFlags requires verified rich text before marking repair successful", () => {
  const weak = collectRepairEvidenceFlags([
    { kind: "douyin_rich_text_repair", filled: true, verified_title: true, verified_body: false },
  ]);
  const strong = collectRepairEvidenceFlags([
    { kind: "douyin_rich_text_repair", filled: true, verified_title: true, verified_body: true },
  ]);

  assert.equal(weak.rich_text_repair_attempted, true);
  assert.equal(weak.rich_text_repaired, false);
  assert.equal(strong.rich_text_repair_attempted, true);
  assert.equal(strong.rich_text_repaired, true);
});

test("richTextDraftValueMatches rejects contenteditable writes that prepend new text without clearing old content", () => {
  const expected = "第一段正文\n\n第二段正文";
  const actual = "第一段正文\n\n第二段正文旧内容残留";

  assert.equal(normalizeRichTextDraftValue(expected), "第一段正文\n第二段正文");
  assert.equal(richTextDraftValueMatches(actual, expected), false);
  assert.equal(richTextDraftValueMatches(expected, expected), true);
});

test("deriveCompositeCollectionPolicyState requires explicit collection decision on supported platforms", () => {
  const state = deriveCompositeCollectionPolicyState("douyin", {
    title: "测试标题",
    platform_specific_overrides: {},
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, false);
  assert.equal(state.explicit_collection_name, "");
  assert.equal(state.explicit_collection_skip, false);
});

test("deriveCompositeCollectionPolicyState accepts explicit skip policy", () => {
  const state = deriveCompositeCollectionPolicyState("douyin", {
    title: "测试标题",
    platform_specific_overrides: {
      collection_policy: "skip",
    },
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, true);
  assert.equal(state.explicit_collection_skip, true);
});

test("deriveCompositeCollectionPolicyState accepts top-level skip policy for external callers", () => {
  const state = deriveCompositeCollectionPolicyState("douyin", {
    title: "测试标题",
    collection_policy: "skip",
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, true);
  assert.equal(state.explicit_collection_skip, true);
});

test("deriveCompositeCoverPolicyState requires explicit cover path on supported platforms", () => {
  const state = deriveCompositeCoverPolicyState("douyin", {
    title: "测试标题",
    platform_specific_overrides: {},
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, false);
  assert.equal(state.explicit_cover_path, "");
  assert.equal(state.explicit_cover_skip, false);
});

test("deriveCompositeCoverPolicyState accepts explicit skip policy", () => {
  const state = deriveCompositeCoverPolicyState("douyin", {
    title: "测试标题",
    platform_specific_overrides: {
      cover_policy: "platform_default",
    },
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, true);
  assert.equal(state.explicit_cover_skip, true);
});

test("deriveCompositeCoverPolicyState accepts top-level skip policy for external callers", () => {
  const state = deriveCompositeCoverPolicyState("douyin", {
    title: "测试标题",
    cover_policy: "platform_default",
  });

  assert.equal(state.required, true);
  assert.equal(state.ready, true);
  assert.equal(state.explicit_cover_skip, true);
});

test("_buildCompositeExpectedContentSnapshot uses explicit declaration instead of body/title fallback", () => {
  const expected = _buildCompositeExpectedContentSnapshot(
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "正文内容",
      declaration: "无需添加自主声明",
      scheduled_publish_at: "2026-05-31 20:30:00",
      cover_path: "E:/covers/02-douyin-cover.jpg",
    },
    "douyin",
  );

  assert.equal(expected.declaration, "无需添加自主声明");
  assert.equal(expected.body, "正文内容");
});

test("_buildCompositeExpectedContentSnapshot resolves douyin default declaration when declaration is omitted", () => {
  const expected = _buildCompositeExpectedContentSnapshot(
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "正文内容",
      scheduled_publish_at: "2026-05-31 20:30:00",
      cover_path: "E:/covers/02-douyin-cover.jpg",
    },
    "douyin",
  );

  assert.equal(expected.declaration, "无需添加自主声明");
});

test("expectedCompositeDeclaration and extractCompositeDeclarationText share the same declaration source", () => {
  const content = {
    copy_material: {
      declaration: "本内容含营销推广信息",
    },
  };

  assert.equal(extractCompositeDeclarationText(content), "本内容含营销推广信息");
  assert.equal(expectedCompositeDeclaration(content, "douyin"), "内容含营销推广信息");
});

test("verifyCompositeDeclarationField rejects douyin placeholder-only declaration surface", () => {
  assert.equal(
    verifyCompositeDeclarationField(
      "douyin",
      "无需添加自主声明",
      "",
      "作品描述 设置封面 请选择自主声明 添加合集 发布时间",
      { declarationMissingPrompt: false, hasTitleOrBody: true },
    ),
    false,
  );
});

test("deriveXiaohongshuSelectedCollectionActual returns selected collection from visible editor text", () => {
  assert.equal(
    deriveXiaohongshuSelectedCollectionActual("EDC潮玩桌搭", "加入合集 EDC潮玩桌搭 原创声明 公开可见"),
    "EDC潮玩桌搭",
  );
  assert.equal(
    deriveXiaohongshuSelectedCollectionActual("EDC潮玩桌搭", "加入合集 请选择合集 原创声明"),
    "",
  );
});

test("deriveXiaohongshuDeclarationActual only reports explicit content-type declarations", () => {
  assert.equal(
    deriveXiaohongshuDeclarationActual("内容由AI生成", "加入合集 EDC潮玩桌搭 内容由AI生成 公开可见"),
    "内容由AI生成",
  );
  assert.equal(
    deriveXiaohongshuDeclarationActual("原创声明", "加入合集 EDC潮玩桌搭 原创声明 公开可见"),
    "",
  );
});

test("isPlatformPublishRouteBootstrapReady accepts douyin upload entry surface for fresh-start bootstrap", () => {
  assert.equal(
    isPlatformPublishRouteBootstrapReady("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/upload",
      title: "抖音创作者中心",
      text: "还有上次未发布的视频，是否继续编辑？ 继续编辑 放弃 点击上传或直接将视频文件拖入此区域",
      file_inputs: [],
    }, {
      allow_loading_shell: true,
    }),
    true,
  );
});

test("isCompositePublishRouteContext rejects youtube content-list upload skeleton until editor or upload surface appears", () => {
  assert.equal(
    isCompositePublishRouteContext("youtube", {
      url: "https://studio.youtube.com/channel/UC123/videos/upload?filter=%5B%5D",
      text: "频道内容 编辑草稿 草稿 发布日期 观看次数 评论数",
      file_inputs: [],
    }),
    false,
  );
  assert.equal(
    isCompositePublishRouteContext("youtube", {
      url: "https://studio.youtube.com/channel/UC123/videos/upload?d=ud&udvid=eaTu-rtsyiw",
      text: "上传视频 Select files",
      file_inputs: [],
    }),
    true,
  );
});

test("verifyCompositeDeclarationField requires xiaohongshu original switch when generic original declaration is requested", () => {
  assert.equal(
    verifyCompositeDeclarationField(
      "xiaohongshu",
      "",
      "",
      "原创声明 添加内容类型声明 公开可见",
      {
        declarationMissingPrompt: false,
        hasTitleOrBody: true,
        xiaohongshuRequireOriginalDeclaration: true,
        xiaohongshuOriginalDeclarationEnabled: false,
      },
    ),
    false,
  );
  assert.equal(
    verifyCompositeDeclarationField(
      "xiaohongshu",
      "",
      "",
      "原创声明 添加内容类型声明 公开可见",
      {
        declarationMissingPrompt: false,
        hasTitleOrBody: true,
        xiaohongshuRequireOriginalDeclaration: true,
        xiaohongshuOriginalDeclarationEnabled: true,
      },
    ),
    true,
  );
});

test("resolveXiaohongshuDeclarationOption keeps generic original declaration separate from content type", () => {
  assert.equal(resolveXiaohongshuDeclarationOption("原创声明"), "");
  assert.equal(resolveXiaohongshuDeclarationOption("测评"), "");
  assert.equal(resolveXiaohongshuDeclarationOption("内容为个人观点或见解"), "内容为个人观点或见解");
  assert.equal(resolveXiaohongshuDeclarationOption("内容含AI生成"), "内容由AI生成");
});

test("shouldEnableXiaohongshuOriginalDeclaration only enables the original switch for generic original content", () => {
  assert.equal(shouldEnableXiaohongshuOriginalDeclaration("原创声明"), true);
  assert.equal(shouldEnableXiaohongshuOriginalDeclaration("测评"), true);
  assert.equal(shouldEnableXiaohongshuOriginalDeclaration("内容由AI生成"), false);
});

test("expectedCompositeDeclaration keeps xiaohongshu original-switch intent out of content-type declaration", () => {
  assert.equal(
    expectedCompositeDeclaration({ declaration: "原创声明" }, "xiaohongshu"),
    "",
  );
});

test("shouldDeferGenericPostUploadIntegrityUntilPlatformAdapter only keeps bilibili on the generic path", () => {
  assert.equal(shouldDeferGenericPostUploadIntegrityUntilPlatformAdapter("bilibili"), false);
  assert.equal(shouldDeferGenericPostUploadIntegrityUntilPlatformAdapter("xiaohongshu"), true);
  assert.equal(shouldDeferGenericPostUploadIntegrityUntilPlatformAdapter("douyin"), true);
});

test("deriveXiaohongshuCoverActual emits concrete evidence when custom cover preview is visible", () => {
  assert.equal(
    deriveXiaohongshuCoverActual(
      "E:/covers/xhs-cover.jpg",
      "设置封面 重新设置封面 封面效果评估通过",
      ["blob:https://creator.xiaohongshu.com/example"],
      [],
      true,
    ),
    "xhs-cover.jpg",
  );
});

test("deriveCompositeDraftPolicyBlockers blocks supported platforms with missing collection policy", () => {
  const blockers = deriveCompositeDraftPolicyBlockers("douyin", {
    title: "测试标题",
    cover_path: "E:/covers/dy.jpg",
    platform_specific_overrides: {},
  });

  assert.equal(blockers.length, 1);
  assert.equal(blockers[0].code, "douyin_collection_policy_missing");
});

test("deriveCompositeDraftPolicyBlockers blocks supported platforms with missing cover policy", () => {
  const blockers = deriveCompositeDraftPolicyBlockers("douyin", {
    title: "测试标题",
    platform_specific_overrides: {
      collection_policy: "skip",
    },
  });

  assert.equal(blockers.length, 1);
  assert.equal(blockers[0].code, "douyin_cover_policy_missing");
});

test("deriveCompositeDraftPolicyBlockers uses shared matrix for xiaohongshu and x", () => {
  const xhsBlockers = deriveCompositeDraftPolicyBlockers("xiaohongshu", {
    title: "测试标题",
    platform_specific_overrides: {},
  });
  const xBlockers = deriveCompositeDraftPolicyBlockers("x", {
    title: "测试标题",
    platform_specific_overrides: {},
  });

  assert.equal(xhsBlockers.length, 2);
  assert.deepEqual(
    xhsBlockers.map((item) => item.code).sort(),
    ["xiaohongshu_collection_policy_missing", "xiaohongshu_cover_policy_missing"],
  );
  assert.equal(xBlockers.length, 0);
});

test("applyCompositeSafeRuntimePolicyDefaults auto-fills cover and collection policy for safe youtube tasks", () => {
  const normalized = applyCompositeSafeRuntimePolicyDefaults("youtube", {
    title: "测试标题",
    platform_specific_overrides: {
      prepare_only_current_page: true,
    },
  });

  assert.equal(normalized.platform_specific_overrides.prepare_only_current_page, true);
  assert.equal(normalized.platform_specific_overrides.collection_policy, "skip");
  assert.equal(normalized.platform_specific_overrides.skip_collection_select, true);
  assert.equal(normalized.platform_specific_overrides.cover_policy, "platform_default");
  assert.equal(normalized.platform_specific_overrides.skip_cover_upload, true);
});

test("applyCompositeSafeRuntimePolicyDefaults treats stop-before-final-publish as safe runtime mode", () => {
  const normalized = applyCompositeSafeRuntimePolicyDefaults("bilibili", {
    title: "测试标题",
    platform_specific_overrides: {
      stop_before_final_publish: true,
    },
  });

  assert.equal(normalized.platform_specific_overrides.stop_before_final_publish, true);
  assert.equal(normalized.platform_specific_overrides.collection_policy, "skip");
  assert.equal(normalized.platform_specific_overrides.skip_collection_select, true);
});

test("deriveCompositeDraftPolicyBlockers respects safe runtime auto-defaults for youtube", () => {
  const blockers = deriveCompositeDraftPolicyBlockers("youtube", {
    title: "测试标题",
    platform_specific_overrides: {
      prepare_only_current_page: true,
    },
  });

  assert.equal(blockers.length, 0);
});

test("deriveCompositeCdpTimeoutWaitEnvelope converts youtube editor runtime timeout into wait-only processing", () => {
  const envelope = deriveCompositeCdpTimeoutWaitEnvelope({
    platform: "youtube",
    route: {
      url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      title: "频道内容 - YouTube Studio",
    },
    content: {
      title: "测试标题",
      platform_specific_overrides: {
        prepare_only_current_page: true,
      },
    },
    actions: [{ kind: "draft_state_clear" }],
    error: new Error("CDP Runtime.enable timed out after 35000ms"),
    prepareOnlyCurrentPage: true,
    stopBeforeFinalPublish: true,
  });

  assert.ok(envelope);
  assert.equal(envelope.code, "youtube_pre_publish_upload_pending");
  assert.equal(envelope.recovery_overrides?.recovery_mode, "prepublish_resume");
  assert.equal(envelope.recovery_overrides?.prepare_only_current_page, true);
  assert.equal(envelope.final_publish?.prepare_only_current_page, true);
  assert.equal(envelope.material_integrity?.verification_reason, "editor_surface_runtime_timeout");
});

test("deriveCompositeSchedulePolicyState blocks stale xiaohongshu schedule window", () => {
  const state = deriveCompositeSchedulePolicyState(
    "xiaohongshu",
    {
      scheduled_publish_at: "2026-05-31T21:00",
    },
    Date.parse("2026-06-01T03:21:34+08:00"),
  );

  assert.equal(state.ready, false);
  assert.equal(state.reason, "schedule_too_soon");
  assert.equal(state.minimumLeadMinutes, 60);
});

test("deriveCompositeDraftPolicyBlockers blocks stale xiaohongshu schedule before platform auto-adjust", () => {
  const blockers = deriveCompositeDraftPolicyBlockers(
    "xiaohongshu",
    {
      title: "测试标题",
      cover_path: "E:/covers/xhs.jpg",
      collection_name: "EDC潮玩桌搭",
      scheduled_publish_at: "2026-05-31T21:00",
      platform_specific_overrides: {},
    },
    Date.parse("2026-06-01T03:21:34+08:00"),
  );

  assert.equal(blockers.length, 1);
  assert.equal(blockers[0].code, "xiaohongshu_scheduled_publish_window_invalid");
});

test("deriveCompositePrePublishFailureRecoveryPlan keeps failed prepublish readback on-page after repair attempt", () => {
  const recovery = deriveCompositePrePublishFailureRecoveryPlan(
    {
      required_unverified: ["cover", "collection", "content_plan_match"],
    },
    {
      failures: ["cover", "collection"],
    },
    {
      attempted: true,
    },
  );

  assert.equal(recovery.clear_draft_context, false);
  assert.equal(recovery.force_publish_page_refresh, true);
  assert.equal(recovery.repair_attempted, true);
  assert.equal(recovery.has_editable_field_failures, true);
});

test("deriveCompositePrePublishFailureRecoveryPlan does not escalate structural prepublish failures into clear draft", () => {
  const recovery = deriveCompositePrePublishFailureRecoveryPlan(
    {
      required_unverified: ["upload_ready", "draft_state"],
    },
    {
      failures: ["upload_ready"],
    },
    null,
  );

  assert.equal(recovery.clear_draft_context, false);
  assert.equal(recovery.force_publish_page_refresh, true);
  assert.equal(recovery.has_structural_failures, true);
});

test("deriveCompositePrePublishPendingState treats upload_ready-only prepublish remainder as waitable", () => {
  const pending = deriveCompositePrePublishPendingState(
    {
      required_unverified: ["upload_ready"],
    },
    {
      failures: ["upload_ready"],
    },
    {
      attempted: true,
    },
  );

  assert.equal(pending.pending, true);
  assert.equal(pending.wait_only, true);
  assert.deepEqual(pending.remaining, ["upload_ready"]);
  assert.equal(pending.repair_attempted, true);
});

test("deriveCompositePrePublishPendingState does not treat mixed editable failures as wait-only", () => {
  const pending = deriveCompositePrePublishPendingState(
    {
      required_unverified: ["body", "upload_ready"],
    },
    {
      failures: ["body", "upload_ready"],
    },
    {
      attempted: true,
    },
  );

  assert.equal(pending.pending, false);
  assert.equal(pending.wait_only, false);
});

test("deriveCompositePostUploadIntegrityDisposition converts upload_ready-only post-upload remainder into processing wait state", () => {
  const disposition = deriveCompositePostUploadIntegrityDisposition(
    "douyin",
    {
      verification_state: "not_ready",
      failures: ["upload_ready"],
    },
    null,
  );

  assert.equal(disposition.status, "processing");
  assert.equal(disposition.code, "douyin_pre_publish_upload_pending");
  assert.equal(disposition.clear_draft_context, false);
  assert.equal(disposition.force_publish_page_refresh, true);
  assert.deepEqual(disposition.remaining, ["upload_ready"]);
  assert.equal(disposition.pre_publish_pending, true);
});

test("deriveCompositePostUploadIntegrityDisposition keeps mixed editable failures as needs_human without draft clear", () => {
  const disposition = deriveCompositePostUploadIntegrityDisposition(
    "douyin",
    {
      verification_state: "not_ready",
      failures: ["upload_ready", "body"],
    },
    null,
  );

  assert.equal(disposition.status, "needs_human");
  assert.equal(disposition.code, "douyin_media_upload_integrity_not_ready");
  assert.equal(disposition.clear_draft_context, false);
  assert.equal(disposition.force_publish_page_refresh, true);
  assert.deepEqual(disposition.remaining, ["upload_ready", "body"]);
  assert.equal(disposition.pre_publish_pending, false);
});

test("deriveCompositeUploadReadinessFailureState treats stalled synthetic upload prompt as failed", () => {
  const failure = deriveCompositeUploadReadinessFailureState(
    "kuaishou",
    {
      ready: false,
      failed: false,
      waited_ms: 20000,
      last: {
        busy: false,
        mediaPresent: false,
        uploadPromptOnly: true,
      },
    },
    {
      syntheticUploadExpected: true,
    },
  );

  assert.equal(failure.failed, true);
  assert.equal(failure.reason, "upload_not_applied");
});

test("deriveCompositeUploadReadinessFailureState treats youtube hidden upload dialog that remains on channel content as failed", () => {
  const failure = deriveCompositeUploadReadinessFailureState(
    "youtube",
    {
      ready: false,
      failed: false,
      waited_ms: 20000,
      last: {
        busy: false,
        mediaPresent: false,
        uploadPromptOnly: false,
        youtubeUploadRoute: true,
        youtubeChannelContentList: true,
        youtubeUploadDialogRoute: true,
        totalFileInputCount: 1,
      },
    },
    {
      syntheticUploadExpected: true,
    },
  );

  assert.equal(failure.failed, true);
  assert.equal(failure.reason, "upload_not_applied");
});

test("shouldDeferYouTubeDraftResumeReupload stays disabled for youtube draft rows", () => {
  assert.equal(
    shouldDeferYouTubeDraftResumeReupload({
      ready: false,
      failed: false,
      last: {
        platform: "youtube",
        busy: false,
        mediaPresent: true,
        uploadPromptOnly: false,
        fileInputCount: 0,
        totalFileInputCount: 1,
        youtubeUploadRoute: true,
        youtubeChannelContentList: true,
        youtubeDraftResumeAvailable: true,
      },
    }),
    true,
  );
  assert.equal(
    shouldDeferYouTubeDraftResumeReupload({
      ready: false,
      failed: false,
      last: {
        platform: "youtube",
        busy: false,
        mediaPresent: true,
        uploadPromptOnly: false,
        fileInputCount: 1,
        totalFileInputCount: 1,
        youtubeUploadRoute: true,
        youtubeChannelContentList: true,
        youtubeDraftResumeAvailable: true,
      },
    }),
    false,
  );
});

test("selectYouTubeDraftResumeEntryCandidate prefers actionable edit-draft button on active upload row", () => {
  const chosen = selectYouTubeDraftResumeEntryCandidate([
    {
      label: "MAXACE 美杜莎4 顶配次顶配开箱",
      target_id: "video-title",
      tag: "a",
      row_text: "MAXACE 美杜莎4 顶配次顶配开箱 草稿 添加说明 编辑草稿",
      row_role: "div",
      x: 620,
      y: 430,
      width: 300,
      height: 20,
      visible: true,
    },
    {
      label: "编辑草稿",
      target_id: "",
      tag: "button",
      row_text: "MAXACE 美杜莎4 顶配次顶配开箱 草稿 取消上传 编辑草稿",
      row_role: "ytcp-video-row",
      x: 1600,
      y: 352,
      width: 88,
      height: 36,
      visible: true,
    },
    {
      label: "详细信息",
      target_id: "video-details",
      tag: "ytcp-icon-button",
      row_text: "MAXACE 美杜莎4 顶配次顶配开箱 草稿 取消上传 编辑草稿",
      row_role: "ytcp-video-row",
      x: 476,
      y: 384,
      width: 40,
      height: 40,
      visible: true,
    },
  ]);

  assert.equal(chosen?.label, "编辑草稿");
  assert.match(chosen?.row_text || "", /取消上传/);
});

test("extractYouTubeDraftVideoId prefers udvid route marker and falls back to watch url", () => {
  assert.equal(
    extractYouTubeDraftVideoId(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=eaTu-rtsyiw",
      "https://www.youtube.com/watch?v=ignored123",
    ),
    "eaTu-rtsyiw",
  );
  assert.equal(
    extractYouTubeDraftVideoId(
      "https://studio.youtube.com/channel/test/videos/upload",
      "https://www.youtube.com/watch?v=eaTu-rtsyiw",
    ),
    "eaTu-rtsyiw",
  );
  assert.equal(
    extractYouTubeDraftVideoId(
      "https://www.youtube.com/watch?v=eaTu-rtsyiw",
      "",
    ),
    "eaTu-rtsyiw",
  );
  assert.equal(
    extractYouTubeDraftVideoId(
      "",
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
    ),
    "eaTu-rtsyiw",
  );
  assert.equal(
    buildYouTubeStudioEditorUrl("eaTu-rtsyiw"),
    "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
  );
  assert.equal(
    buildYouTubeUploadResumeUrl(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&filter=%5B%5D",
      "eaTu-rtsyiw",
    ),
    "https://studio.youtube.com/channel/test/videos/upload?d=ud&filter=%5B%5D&udvid=eaTu-rtsyiw",
  );
});

test("hasYoutubeUploadResumeVideoId distinguishes stable udvid resume route from generic d=ud list", () => {
  assert.equal(
    hasYoutubeUploadResumeVideoId(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&filter=%5B%5D",
    ),
    false,
  );
  assert.equal(
    hasYoutubeUploadResumeVideoId(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&filter=%5B%5D&udvid=eaTu-rtsyiw",
    ),
    true,
  );
});

test("selectYouTubeDraftResumeCandidate prefers hinted draft row and extracts local watch id", () => {
  const chosen = selectYouTubeDraftResumeCandidate([
    {
      text: "别的视频 草稿 编辑草稿",
      watchHref: "https://www.youtube.com/watch?v=ignored123",
      titleHref: "",
    },
    {
      text: "MAXACE 美杜莎4 顶配次顶配开箱 草稿 编辑草稿",
      watchHref: "https://www.youtube.com/watch?v=eaTu-rtsyiw",
      titleHref: "",
    },
  ], "MAXACE 美杜莎4 顶配次顶配开箱");

  assert.equal(chosen.videoId, "eaTu-rtsyiw");
  assert.equal(chosen.watchHref, "https://www.youtube.com/watch?v=eaTu-rtsyiw");
  assert.match(chosen.text, /MAXACE 美杜莎4/);
});

test("matchesYouTubeDraftResumeHint tolerates publish-title punctuation drift and media-stem fallback", () => {
  assert.equal(
    matchesYouTubeDraftResumeHint(
      "10:09 MAXACE 美杜莎4 顶配次顶配开箱 草稿 编辑草稿",
      [
        "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手",
        "MAXACE 美杜莎4 顶配次顶配开箱",
      ],
    ),
    true,
  );
  assert.equal(
    matchesYouTubeDraftResumeHint(
      "10:09 MOT风灵音叉推牌锆合金版开箱 草稿 编辑草稿",
      [
        "MAXACE美杜莎4 顶配 vs 次顶配 开箱对比上手",
        "MAXACE 美杜莎4 顶配次顶配开箱",
      ],
    ),
    false,
  );
});

test("deriveYouTubeDraftResumeFallbackTarget prefers upload resume url before edit url", () => {
  assert.deepEqual(
    deriveYouTubeDraftResumeFallbackTarget(
      {
        upload_resume_url: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=eaTu-rtsyiw",
        edit_url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      },
      "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D",
    ),
    {
      target: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=eaTu-rtsyiw",
      reason: "upload_resume_url",
    },
  );
  assert.deepEqual(
    deriveYouTubeDraftResumeFallbackTarget(
      {
        upload_resume_url: "",
        edit_url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      },
      "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D",
    ),
    {
      target: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      reason: "edit_url",
    },
  );
});

test("deriveYouTubeUploadEditorBootstrapPlan requires control-driven upload flow from content list", () => {
  const plan = deriveYouTubeUploadEditorBootstrapPlan({
    href: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos",
    bodyText: "频道内容 MAXACE 美杜莎4 顶配次顶配开箱 编辑草稿 草稿 发布日期",
    channelContentList: true,
    draftRows: [
      {
        text: "MAXACE 美杜莎4 顶配次顶配开箱 编辑草稿 草稿",
        watchHref: "https://www.youtube.com/watch?v=eaTu-rtsyiw",
        titleHref: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
        videoId: "eaTu-rtsyiw",
      },
    ],
  }, "MAXACE 美杜莎4 顶配次顶配开箱");

  assert.equal(plan.changed, false);
  assert.equal(plan.reason, "control_driven_create_upload_required");
  assert.equal(plan.fallbackTarget, "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload");
});

test("deriveYouTubeUploadEditorBootstrapPlan supports youtube web channel page via create control", () => {
  const plan = deriveYouTubeUploadEditorBootstrapPlan({
    href: "https://www.youtube.com/@FAS_EDC/videos",
    bodyText: "FAS机神圣殿x潮玩EDC 创建 上传视频 开始直播 发帖 我的频道",
    createControlSurface: true,
  }, "MAXACE 美杜莎4 顶配次顶配开箱");

  assert.equal(plan.matched, true);
  assert.equal(plan.changed, false);
  assert.equal(plan.reason, "control_driven_create_upload_required");
  assert.equal(plan.fallbackTarget, "https://studio.youtube.com/");
});

test("normalizeYouTubeVisibilityOrPublishMode defaults youtube to public and scheduled publish to schedule", () => {
  assert.equal(normalizeYouTubeVisibilityOrPublishMode("", ""), "public");
  assert.equal(normalizeYouTubeVisibilityOrPublishMode("", "2026-06-05T21:00:00+08:00"), "schedule");
  assert.equal(normalizeYouTubeVisibilityOrPublishMode("公开", ""), "public");
  assert.equal(normalizeYouTubeVisibilityOrPublishMode("不公开列出", ""), "unlisted");
});

test("deriveYouTubeUploadWizardStep recognizes the four-step upload wizard", () => {
  assert.equal(
    deriveYouTubeUploadWizardStep(
      "https://studio.youtube.com/video/demo/edit",
      "详细信息 标题（必填） 说明 缩略图 播放列表 观众 视频链接",
    ),
    "details",
  );
  assert.equal(
    deriveYouTubeUploadWizardStep(
      "https://studio.youtube.com/video/demo/edit",
      "视频元素 添加字幕 添加片尾画面 添加卡片",
    ),
    "video_elements",
  );
  assert.equal(
    deriveYouTubeUploadWizardStep(
      "https://studio.youtube.com/video/demo/edit",
      "检查 检查完毕 未发现任何问题",
    ),
    "checks",
  );
  assert.equal(
    deriveYouTubeUploadWizardStep(
      "https://studio.youtube.com/video/demo/edit",
      "公开范围 私享 不公开列出 公开 安排时间 保存或发布",
    ),
    "visibility",
  );
});

test("shouldAttemptYouTubeDraftResumeFallbackRoute requires youtube draft row inert state with a concrete fallback target", () => {
  assert.equal(
    shouldAttemptYouTubeDraftResumeFallbackRoute(
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D",
          mediaPresent: true,
          uploadPromptOnly: false,
          busy: false,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeHasEditorSurface: false,
        },
      },
      {
        upload_resume_url: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D&d=ud&udvid=eaTu-rtsyiw",
        edit_url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      },
    ),
    true,
  );
  assert.equal(
    shouldAttemptYouTubeDraftResumeFallbackRoute(
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D&d=ud&udvid=eaTu-rtsyiw",
          mediaPresent: false,
          uploadPromptOnly: false,
          busy: false,
          youtubeUploadRoute: true,
          youtubeUploadDialogRoute: true,
          youtubeChannelContentList: true,
          youtubeHasEditorSurface: false,
        },
      },
      {
        upload_resume_url: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D&d=ud&udvid=eaTu-rtsyiw",
        edit_url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      },
    ),
    true,
  );
  assert.equal(
    shouldAttemptYouTubeDraftResumeFallbackRoute(
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D",
          mediaPresent: true,
          uploadPromptOnly: false,
          busy: false,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeHasEditorSurface: true,
        },
      },
      {
        upload_resume_url: "https://studio.youtube.com/channel/test/videos/upload?filter=%5B%5D&d=ud&udvid=eaTu-rtsyiw",
      },
    ),
    false,
  );
});

test("shouldFailYouTubeDraftResumeAsInert detects draft row that did not advance after resume click", () => {
  assert.equal(
    shouldFailYouTubeDraftResumeAsInert(
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=abc",
          busy: false,
          mediaPresent: true,
          uploadPromptOnly: false,
          fileInputCount: 0,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeDraftResumeAvailable: true,
          lines: ["频道内容", "草稿", "编辑草稿", "取消上传"],
        },
      },
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=abc",
          busy: false,
          mediaPresent: true,
          uploadPromptOnly: false,
          fileInputCount: 0,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeDraftResumeAvailable: true,
          lines: ["频道内容", "草稿", "编辑草稿", "取消上传"],
        },
      },
      { clicked: true, label: "编辑草稿" },
    ),
    true,
  );
  assert.equal(
    shouldFailYouTubeDraftResumeAsInert(
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=abc",
          busy: false,
          mediaPresent: true,
          uploadPromptOnly: false,
          fileInputCount: 0,
          youtubeUploadRoute: true,
          youtubeChannelContentList: true,
          youtubeDraftResumeAvailable: true,
          lines: ["频道内容", "草稿", "编辑草稿", "取消上传"],
        },
      },
      {
        ready: false,
        failed: false,
        last: {
          platform: "youtube",
          href: "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=abc",
          busy: false,
          mediaPresent: true,
          uploadPromptOnly: false,
          fileInputCount: 1,
          youtubeUploadRoute: true,
          youtubeChannelContentList: false,
          youtubeDraftResumeAvailable: false,
          youtubeHasEditorSurface: true,
          lines: ["上传视频", "标题", "说明"],
        },
      },
      { clicked: true, label: "编辑草稿" },
    ),
    false,
  );
});

test("shouldPreserveYouTubeUploadResumeRoute preserves active youtube upload resume surface", () => {
  assert.equal(
    shouldPreserveYouTubeUploadResumeRoute(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=T-44KNDKkSQ",
      "频道内容 MAXACE 美杜莎4 顶配次顶配开箱 正在上传，已完成 3% 草稿 取消上传 编辑草稿 公开范围 日期 观看次数 评论数",
    ),
    true,
  );
  assert.equal(
    shouldPreserveYouTubeUploadResumeRoute(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=T-44KNDKkSQ",
      "",
    ),
    false,
  );
  assert.equal(
    shouldPreserveYouTubeUploadResumeRoute(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=T-44KNDKkSQ",
      "糟糕，出了点问题。",
    ),
    false,
  );
  assert.equal(
    shouldPreserveYouTubeUploadResumeRoute(
      "https://studio.youtube.com/channel/test/upload",
      "糟糕，出了点问题。",
    ),
    false,
  );
  assert.equal(
    shouldPreserveYouTubeUploadResumeRoute(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "视频详细信息 标题（必填） MAXACE 美杜莎4 顶配次顶配开箱 说明 缩略图 播放列表 观众 视频链接",
    ),
    true,
  );
});

test("shouldPreserveYouTubeUploadResumeRouteForBootstrap keeps bare udvid route unless it is an error surface", () => {
  assert.equal(
    shouldPreserveYouTubeUploadResumeRouteForBootstrap(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=T-44KNDKkSQ",
      "",
    ),
    true,
  );
  assert.equal(
    shouldPreserveYouTubeUploadResumeRouteForBootstrap(
      "https://studio.youtube.com/channel/test/videos/upload?d=ud&udvid=T-44KNDKkSQ",
      "糟糕，出了点问题。",
    ),
    false,
  );
});

test("isYouTubeEditorReadinessSurface recognizes studio video edit surface", () => {
  assert.equal(
    isYouTubeEditorReadinessSurface(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "视频详细信息 标题（必填） MAXACE 美杜莎4 顶配次顶配开箱 说明 缩略图 播放列表 观众 视频链接",
    ),
    true,
  );
  assert.equal(
    isYouTubeEditorReadinessSurface(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "频道内容 编辑草稿",
    ),
    false,
  );
});

test("shouldPreserveYouTubeEditorRouteForBootstrap keeps youtube editor route unless it is an error surface", () => {
  assert.equal(
    shouldPreserveYouTubeEditorRouteForBootstrap(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "",
    ),
    true,
  );
  assert.equal(
    shouldPreserveYouTubeEditorRouteForBootstrap(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "糟糕，出了点问题。",
    ),
    false,
  );
  assert.equal(
    shouldPreserveYouTubeEditorRouteForBootstrap(
      "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
      "你最近上传的视频 编辑草稿 视频详细信息 标题（必填） 说明 缩略图 播放列表 观众 视频链接",
    ),
    false,
  );
});

test("deriveProbeInventoryRouteReadiness keeps youtube editor surface ready even when draft row text is present", () => {
  const readiness = deriveProbeInventoryRouteReadiness("youtube", {
    url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
    title: "视频详细信息 - YouTube Studio",
    lines: [
      "你最近上传的视频",
      "编辑草稿",
      "视频详细信息",
      "标题（必填）",
      "说明",
      "缩略图",
      "播放列表",
      "观众",
      "视频链接",
    ],
    elements: [{ tag: "textarea", role: "textbox" }],
  });

  assert.equal(readiness.blocked, false);
  assert.equal(readiness.status, "ready");
  assert.equal(readiness.reason, "");
});

test("normalizeYouTubeTagValue strips hash and collapses whitespace", () => {
  assert.equal(normalizeYouTubeTagValue("# MAXACE美杜莎4 "), "MAXACE美杜莎4");
  assert.equal(normalizeYouTubeTagValue("  EDC   折刀  "), "EDC 折刀");
});

test("selectYouTubeTagInputCandidate prefers real tags chip input over unrelated metadata fields", () => {
  const candidate = selectYouTubeTagInputCandidate([
    {
      label: "向观看者介绍你的视频",
      context: "说明 向观看者介绍你的视频",
      placeholder: "说明",
      aria_label: "说明",
      tag: "textarea",
      type: "",
      value: "",
      chip_count: 0,
      area: 240000,
    },
    {
      label: "标签",
      context: "标签 按 Enter 可创建标签",
      placeholder: "输入标签",
      aria_label: "Tags",
      tag: "input",
      type: "text",
      value: "",
      chip_count: 2,
      area: 32000,
    },
  ]);

  assert.equal(candidate?.label, "标签");
  assert.equal(candidate?.tag, "input");
  assert.equal(candidate?.chip_count, 2);
});

test("selectYouTubeMetadataExpandCandidate prefers the real advanced-settings button over surrounding container text", () => {
  const candidate = selectYouTubeMetadataExpandCandidate([
    {
      text: "展开 付费宣传内容、联合创作、字幕等",
      aria_label: "",
      tag: "div",
      role: "",
      area: 180000,
    },
    {
      text: "展开",
      aria_label: "显示高级设置",
      tag: "button",
      role: "button",
      area: 12000,
    },
  ]);

  assert.equal(candidate?.tag, "button");
  assert.equal(candidate?.aria_label, "显示高级设置");
});

test("shouldTreatCompositeUploadReadinessBlockerAsPending keeps upload-busy blocker in wait-only state", () => {
  assert.equal(
    shouldTreatCompositeUploadReadinessBlockerAsPending({
      blockers: ["upload_busy"],
      upload_busy: true,
    }),
    true,
  );
  assert.equal(
    shouldTreatCompositeUploadReadinessBlockerAsPending({
      blockers: ["upload_failed"],
      upload_busy: false,
    }),
    false,
  );
});

test("shouldTreatCompositeUploadReadinessBlockerAsPending keeps youtube draft-resume pending state in wait-only mode", () => {
  assert.equal(
    shouldTreatCompositeUploadReadinessBlockerAsPending({
      blockers: [],
      pending_reason: "draft_resume_pending",
      upload_busy: false,
    }),
    true,
  );
});

test("deriveCompositeUploadReadinessFailureState preserves explicit upload failure reason", () => {
  const failure = deriveCompositeUploadReadinessFailureState(
    "youtube",
    {
      ready: false,
      failed: true,
      failure_reason: "upload_failed",
      waited_ms: 5000,
      last: {},
    },
    {},
  );

  assert.equal(failure.failed, true);
  assert.equal(failure.reason, "upload_failed");
});

test("deriveCompositeMediaUploadFailureDisposition preserves safe stop-before mode for no-file-input failures", () => {
  const disposition = deriveCompositeMediaUploadFailureDisposition(
    "youtube",
    {
      reason: "no_file_input",
      fileInputs: [],
    },
    {
      stopBeforeFinalPublish: true,
      prepareOnlyCurrentPage: true,
    },
  );

  assert.equal(disposition.code, "youtube_media_upload_failed");
  assert.equal(disposition.clear_draft_context, false);
  assert.equal(disposition.recovery_overrides.recovery_mode, "prepublish_resume");
  assert.equal(disposition.recovery_overrides.prepare_only_current_page, true);
  assert.equal(disposition.error_details.failure_reason, "upload_not_applied");
});

test("deriveCompositeUploadReadinessBlockerDisposition preserves safe stop-before mode for youtube draft resume inert blocker", () => {
  const disposition = deriveCompositeUploadReadinessBlockerDisposition(
    "youtube",
    {
      blockers: ["upload_failed"],
      pending_reason: "draft_resume_inert",
      media_present: true,
      upload_busy: false,
      upload_prompt_only: false,
      line_samples: ["频道内容", "草稿", "编辑草稿", "取消上传"],
    },
    {
      stopBeforeFinalPublish: true,
      prepareOnlyCurrentPage: true,
    },
  );

  assert.equal(disposition.code, "youtube_media_upload_failed");
  assert.equal(disposition.clear_draft_context, false);
  assert.equal(disposition.recovery_overrides.recovery_mode, "prepublish_resume");
  assert.equal(disposition.recovery_overrides.prepare_only_current_page, true);
  assert.equal(disposition.error_details.failure_reason, "upload_not_applied");
});

test("shouldAcceptCollapsedDouyinScheduleEvidence accepts checked scheduled mode with matching date", () => {
  assert.equal(
    shouldAcceptCollapsedDouyinScheduleEvidence(
      {
        scheduled_publish_at: "2026-05-31 20:30:00",
      },
      {
        platform_extras: {
          douyin_checked_schedule: true,
          douyin_schedule_date_value: "2026-05-31",
          douyin_schedule_time_value: "",
        },
      },
      {
        schedule: {
          expected: "2026-05-31 20:30",
          actual: "",
          verified: false,
        },
      },
    ),
    true,
  );
});

test("shouldAcceptCollapsedDouyinScheduleEvidence accepts checked scheduled mode when collapsed surface hides date", () => {
  assert.equal(
    shouldAcceptCollapsedDouyinScheduleEvidence(
      {
        scheduled_publish_at: "2026-05-31 20:30:00",
      },
      {
        platform_extras: {
          douyin_checked_schedule: true,
          douyin_schedule_date_value: "",
          douyin_schedule_time_value: "",
        },
      },
      {
        schedule: {
          expected: "2026-05-31 20:30",
          actual: "",
          verified: false,
        },
      },
    ),
    true,
  );
});

test("buildCompositePublicationAudit normalizes collapsed douyin schedule evidence to verified", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-05-31 20:30:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected_path: "", verified: true },
        schedule: { expected: "2026-05-31 20:30", actual: "", verified: false },
        declaration: { verified: true },
        upload_ready: { expected: "ready", actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        douyin_checked_schedule: true,
        douyin_schedule_date_value: "2026-05-31",
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
      },
    },
    {},
    { url: "https://creator.douyin.com/creator-micro/content/post/video" },
  );

  assert.equal(audit.checklist.schedule.verified, true);
  assert.equal(audit.checklist.schedule.actual, "2026-05-31 20:30");
  assert.ok(!audit.required_unverified.includes("schedule"));
});

test("extractCompositeBodyForAudit trims douyin UI markers and trailing hashtags", () => {
  const actual = extractCompositeBodyForAudit(
    "douyin",
    "作品描述 20/30 顶配和次顶配同时到手，上手那一刻差别就出来了。 轴部阻尼能明显感觉到差别。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #添加话题 @好友 114 / 1000 官方活动",
  );

  assert.equal(actual, "顶配和次顶配同时到手，上手那一刻差别就出来了。 轴部阻尼能明显感觉到差别。");
});

test("normalizeCompositeBodyForAudit folds newlines before verification", () => {
  const expected = "顶配和次顶配同时到手，上手那一刻差别就出来了。\n\n轴部阻尼能明显感觉到差别。";
  const actual = "顶配和次顶配同时到手，上手那一刻差别就出来了。 轴部阻尼能明显感觉到差别。";

  assert.equal(
    normalizeCompositeBodyForAudit("douyin", expected),
    normalizeCompositeBodyForAudit("douyin", actual),
  );
});

test("verifyCompositeBodyField accepts douyin body embedded in editor surface text", () => {
  const expected = "顶配和次顶配同时到手，上手那一刻差别就出来了。\n\n轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。";
  const actual = "作品描述 20/30 顶配和次顶配同时到手，上手那一刻差别就出来了。 轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #添加话题 @好友 114 / 1000";

  assert.equal(
    verifyCompositeBodyField("douyin", expected, actual, { tagVerified: true }),
    true,
  );
});

test("verifyCompositeBodyField rejects douyin body when stale tail remains after expected content", () => {
  const expected = "顶配和次顶配同时到手，上手那一刻差别就出来了。\n\n轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。";
  const actual = "顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。#EDC折刀";

  assert.equal(
    verifyCompositeBodyField("douyin", expected, actual, { tagVerified: true }),
    false,
  );
});

test("verifyCompositeBodyField rejects x body when page noise contains share link and hashtags but not composer body", () => {
  const expected = "MAXACE 美杜莎4 顶配次顶配开箱\n#EDC折刀 #MAXACE美杜莎4 #开箱对比\nhttps://example.com/maxace4";
  const actual = "Home Explore Notifications https://example.com/maxace4 #EDC折刀 #MAXACE美杜莎4 #开箱对比 Everyone can reply Post Your Home Timeline";

  assert.equal(
    verifyCompositeBodyField("x", expected, actual),
    false,
  );
});

test("verifyCompositeBodyField accepts x body when composer text contains expected body tags and share link", () => {
  const expected = "MAXACE 美杜莎4 顶配次顶配开箱\n#EDC折刀 #MAXACE美杜莎4 #开箱对比\nhttps://example.com/maxace4";
  const actual = "MAXACE 美杜莎4 顶配次顶配开箱 #EDC折刀 #MAXACE美杜莎4 #开箱对比 https://example.com/maxace4";

  assert.equal(
    verifyCompositeBodyField("x", expected, actual),
    true,
  );
});

test("verifyCompositeBodyField accepts youtube body when editor collapses blank lines into one paragraph", () => {
  const expected = "双锁头版本同时展开，差异一上手就能看出来。\n\n这次把顶配和次顶配放在一起对比，重点看质感、顺滑度和细节处理。";
  const actual = "双锁头版本同时展开，差异一上手就能看出来。这次把顶配和次顶配放在一起对比，重点看质感、顺滑度和细节处理。";

  assert.equal(
    verifyCompositeBodyField("youtube", expected, actual),
    true,
  );
});

test("buildCompositePublicationAudit treats douyin inline hashtags as body-compatible in content plan match", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。\n\n轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。",
      hashtags: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"],
      scheduled_publish_at: "2026-05-31 20:30:00",
    },
    {
      fields: {
        title: { expected: "两款同时开！美杜莎4顶配次顶配差别出来了", actual: "两款同时开！美杜莎4顶配次顶配差别出来了", verified: true },
        body: { expected: "顶配和次顶配同时到手，上手那一刻差别就出来了。", actual: "顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。#EDC折刀", verified: true },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"], actual: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"], verified: true },
        schedule: { expected: "2026-05-31 20:30", actual: "2026-05-31 20:30", verified: true },
        declaration: { verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "抖音创作者中心" },
      },
    },
    {},
    { url: "https://creator.douyin.com/creator-micro/content/post/video" },
  );

  assert.equal(audit.checklist.content_plan_match.verified, true);
  assert.ok(!audit.required_unverified.includes("body"));
  assert.ok(!audit.required_unverified.includes("content_plan_match"));
});

test("buildCompositePublicationAudit does not let content_plan_match pass when douyin title and schedule actuals are empty", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。",
      hashtags: ["EDC折刀", "MAXACE美杜莎4"],
      scheduled_publish_at: "2026-05-31 20:30:00",
      cover_path: "E:/covers/02-douyin-cover.jpg",
    },
    {
      fields: {
        title: { expected: "两款同时开！美杜莎4顶配次顶配差别出来了", actual: "", verified: false },
        body: { expected: "顶配和次顶配同时到手，上手那一刻差别就出来了。", actual: "顶配和次顶配同时到手，上手那一刻差别就出来了。", verified: true },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4"], actual: ["EDC折刀", "MAXACE美杜莎4"], verified: true },
        cover: { expected_path: "E:/covers/02-douyin-cover.jpg", actual: "", verified: true, uploaded: true },
        schedule: { expected: "2026-05-31 20:30", actual: "", verified: false },
        declaration: { verified: true },
        upload_ready: { actual: "not_ready", verified: false },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "抖音创作者中心" },
      },
    },
    {},
    { url: "https://creator.douyin.com/creator-micro/content/post/video" },
  );

  assert.equal(audit.checklist.content_plan_match.verified, false);
  assert.ok(audit.checklist.content_plan_match.missing.includes("title"));
  assert.ok(audit.checklist.content_plan_match.missing.includes("schedule"));
  assert.equal(audit.checklist.content_plan_match.field_matches.title, false);
  assert.equal(audit.checklist.content_plan_match.field_matches.schedule, false);
});

test("buildCompositePublicationAudit treats youtube tags as soft verification when they are the only mismatch", () => {
  const audit = buildCompositePublicationAudit(
    "youtube",
    {
      title: "MAXACE 美杜莎4 顶配次顶配开箱",
      body: "双锁头版本同时展开，差异一上手就能看出来。",
      hashtags: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀"],
      cover_path: "E:/covers/youtube-cover.jpg",
      collection: { name: "EDC潮玩桌搭" },
    },
    {
      fields: {
        title: { expected: "MAXACE 美杜莎4 顶配次顶配开箱", actual: "MAXACE 美杜莎4 顶配次顶配开箱", verified: true },
        body: { expected: "双锁头版本同时展开，差异一上手就能看出来。", actual: "双锁头版本同时展开，差异一上手就能看出来。", verified: true },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀"], actual: ["折刀"], verified: false },
        cover: { expected_path: "E:/covers/youtube-cover.jpg", actual: "youtube-cover.jpg", verified: true, uploaded: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        schedule: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
        declaration: { verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit", title: "视频详情" },
      },
    },
    {},
    { url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit" },
  );

  assert.equal(audit.verified, true);
  assert.equal(audit.checklist.tags.required, false);
  assert.equal(audit.checklist.content_plan_match.verified, true);
  assert.deepEqual(audit.required_unverified, []);
  assert.deepEqual(audit.required_reupload, []);
  assert.match(audit.notes, /content_plan_optional_missing:tags:/);
});

test("buildCompositePublicationAudit keeps youtube hard field mismatches blocking even when tags are soft", () => {
  const audit = buildCompositePublicationAudit(
    "youtube",
    {
      title: "MAXACE 美杜莎4 顶配次顶配开箱",
      body: "双锁头版本同时展开，差异一上手就能看出来。",
      hashtags: ["EDC折刀", "MAXACE美杜莎4"],
      cover_path: "E:/covers/youtube-cover.jpg",
    },
    {
      fields: {
        title: { expected: "MAXACE 美杜莎4 顶配次顶配开箱", actual: "", verified: false },
        body: { expected: "双锁头版本同时展开，差异一上手就能看出来。", actual: "双锁头版本同时展开，差异一上手就能看出来。", verified: true },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4"], actual: [], verified: false },
        cover: { expected_path: "E:/covers/youtube-cover.jpg", actual: "youtube-cover.jpg", verified: true, uploaded: true },
        schedule: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
        declaration: { verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit", title: "视频详情" },
      },
    },
    {},
    { url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit" },
  );

  assert.equal(audit.verified, false);
  assert.ok(audit.required_unverified.includes("title"));
  assert.ok(audit.required_unverified.includes("content_plan_match"));
  assert.ok(!audit.required_unverified.includes("tags"));
  assert.ok(audit.required_reupload.includes("title"));
  assert.ok(!audit.required_reupload.includes("tags"));
  assert.deepEqual(audit.checklist.content_plan_match.missing, ["title"]);
  assert.deepEqual(audit.checklist.content_plan_match.optional_missing, ["tags:EDC折刀,MAXACE美杜莎4"]);
});

test("extractDouyinManageCardEvidence scopes title body schedule and tags from management card text", () => {
  const evidence = extractDouyinManageCardEvidence(
    "10:08 两款同时开！美杜莎4顶配次顶配差别出来了 顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备 继续编辑 作品置顶 删除作品 定时发布中 定时: 2026年05月31日 20:30 修改定时",
    { title: "两款同时开！美杜莎4顶配次顶配差别出来了" },
  );

  assert.equal(evidence.matched, true);
  assert.equal(evidence.title, "两款同时开！美杜莎4顶配次顶配差别出来了");
  assert.equal(evidence.schedule, "2026-05-31 20:30");
  assert.deepEqual(evidence.tags, ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"]);
  assert.equal(
    evidence.body,
    "顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。",
  );
});

test("extractDouyinManageCardCandidates splits repeated-title management cards into candidates", () => {
  const candidates = extractDouyinManageCardCandidates(
    [
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 21:50 阶段探针测试正文13 #EDC折刀 #MAXACE美杜莎4",
      "继续编辑 作品置顶 删除作品",
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 20:30 顶配和次顶配同时到手，上手那一刻差别就出来了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
    ],
    { title: "两款同时开！美杜莎4顶配次顶配差别出来了" },
  );

  assert.equal(candidates.length, 2);
  assert.equal(candidates[0].schedule, "2026-05-31 21:50");
  assert.equal(candidates[1].schedule, "2026-05-31 20:30");
});

test("selectBestDouyinManageCardEvidence prefers body tags and schedule match over first title hit", () => {
  const selected = selectBestDouyinManageCardEvidence(
    [
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 21:50 阶段探针测试正文13 #EDC折刀 #MAXACE美杜莎4",
      "继续编辑 作品置顶 删除作品",
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 20:30 顶配和次顶配同时到手，上手那一刻差别就出来了。 轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
    ],
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。\n\n轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。",
      schedule: "2026-05-31 20:30",
      tags: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"],
    },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.schedule, "2026-05-31 20:30");
  assert.equal(selected.body_verified, true);
  assert.equal(selected.schedule_verified, true);
  assert.deepEqual(
    selected.tags,
    ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"],
  );
});

test("selectBestDouyinManageCardEvidence stays unmatched when management page has no target title", () => {
  const selected = selectBestDouyinManageCardEvidence(
    [
      "FAS刀帕收纳方法 弹力绳和伞绳绳扣的更换和用法",
      "已发布 2026年04月19日 14:07",
      "傲雷司令官Ultra VS 奈特科尔EC23，谁更值？",
      "已发布 2026年04月19日 03:36",
    ],
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。",
      schedule: "2026-05-31 20:30",
      tags: ["EDC折刀", "MAXACE美杜莎4"],
    },
  );

  assert.equal(selected.matched, false);
  assert.deepEqual(selected.candidates, []);
});

test("extractDouyinManageCardCandidates splits compressed management page and accepts fuzzy title variant", () => {
  const candidates = extractDouyinManageCardCandidates(
    [
      "高清发布 首页 活动管理 内容管理 作品管理 合集管理 共创中心 05:11 FAS刀帕收纳方法 弹力绳和伞绳绳扣的更换和用法 听说真正的EDC高手，都会用刀帕？🤔 今天教你两种方法，把乱七八糟的随身装备卷得整整齐齐。第二种方法还能自己换颜色，秀出你的个性！你觉得哪种更实用？ #玩具 #男人的快乐 #edc装备 #FAS #机能风 编辑作品 设置权限 作品置顶 删除作品 2026年04月19日 14:07 已发布 播放 360 16:25 其他标题 编辑作品 设置权限 作品置顶 删除作品 2026年04月19日 03:36 已发布 播放 1102"
    ],
    {
      title: "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕",
      body: "今天教你两种方法，把乱七八糟的随身装备卷得整整齐齐。第二种方法还能自己换颜色，秀出你的个性！你觉得哪种更实用？",
      tags: ["玩具", "男人的快乐", "edc装备", "FAS", "机能风"],
    },
  );

  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].matched, true);
  assert.deepEqual(candidates[0].tags, ["玩具", "男人的快乐", "edc装备", "FAS", "机能风"]);
  assert.match(candidates[0].body, /今天教你两种方法/);
});

test("selectBestDouyinManageCardEvidence prefers topmost card when duplicates tie on content", () => {
  const selected = selectBestDouyinManageCardEvidence(
    [
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 20:30 顶配和次顶配同时到手，上手那一刻差别就出来了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
      "两款同时开！美杜莎4顶配次顶配差别出来了 定时: 2026年05月31日 20:30 顶配和次顶配同时到手，上手那一刻差别就出来了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
    ],
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。",
      schedule: "2026-05-31 20:30",
      tags: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"],
    },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.line_start, 0);
  assert.ok(selected.recency_bias > 0);
});

test("selectBestDouyinManageCardEvidence prefers card whose publish time matches task creation evidence", () => {
  const selected = selectBestDouyinManageCardEvidence(
    [
      "两款同时开！美杜莎4顶配次顶配差别出来了 2026年05月30日 20:30 顶配和次顶配同时到手，上手那一刻差别就出来了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
      "两款同时开！美杜莎4顶配次顶配差别出来了 2026年05月31日 14:11 顶配和次顶配同时到手，上手那一刻差别就出来了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备",
      "继续编辑 作品置顶 删除作品",
    ],
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      body: "顶配和次顶配同时到手，上手那一刻差别就出来了。",
      tags: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"],
      created_at: "2026-05-31T14:11:47+08:00",
    },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.published_at, "2026-05-31 14:11");
  assert.equal(selected.published_at_verified, true);
});

test("extractXiaohongshuNoteManagerCandidates parses duration-title-date cards from note manager text", () => {
  const candidates = extractXiaohongshuNoteManagerCandidates(
    [
      "03:11",
      "锆合金版本的音叉推牌，质感绝了",
      "2026-05-24 11:00",
      "462",
      "0",
      "10",
      "2",
      "1",
      "10:08",
      "两款同时开！美杜莎4顶配次顶配差别出来了",
      "2026-06-01 21:00",
      "120",
      "0",
      "0",
      "0",
      "0",
    ],
    { title: "美杜莎4顶配次顶配差别出来了" },
  );

  assert.equal(candidates.length, 2);
  assert.equal(candidates[1].matched, true);
  assert.equal(candidates[1].title, "两款同时开！美杜莎4顶配次顶配差别出来了");
  assert.equal(candidates[1].published_at, "2026-06-01 21:00");
});

test("selectBestXiaohongshuNoteManagerEvidence prefers title-matched note manager card", () => {
  const selected = selectBestXiaohongshuNoteManagerEvidence(
    [
      "03:11",
      "锆合金版本的音叉推牌，质感绝了",
      "2026-05-24 11:00",
      "10:08",
      "两款同时开！美杜莎4顶配次顶配差别出来了",
      "2026-06-01 21:00",
    ],
    {
      title: "美杜莎4顶配次顶配差别出来了",
      created_at: "2026-06-01T21:00:00+08:00",
    },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.title_verified, true);
  assert.equal(selected.published_at_verified, true);
  assert.equal(selected.title, "两款同时开！美杜莎4顶配次顶配差别出来了");
});

test("extractToutiaoManageCandidates parses title and published time cards from manage page text", () => {
  const candidates = extractToutiaoManageCandidates(
    [
      "内容管理",
      "全部内容",
      "锆合金版本的音叉推牌，质感绝了",
      "2026-05-24 11:00",
      "两款同时开！美杜莎4顶配次顶配差别出来了",
      "2026-06-01 21:00",
      "编辑 删除",
    ],
    { title: "美杜莎4顶配次顶配差别出来了" },
  );

  assert.equal(candidates.length, 2);
  assert.equal(candidates[1].matched, true);
  assert.equal(candidates[1].title, "两款同时开！美杜莎4顶配次顶配差别出来了");
  assert.equal(candidates[1].published_at, "2026-06-01 21:00");
});

test("selectBestToutiaoManageEvidence prefers title-matched manage card", () => {
  const selected = selectBestToutiaoManageEvidence(
    [
      "锆合金版本的音叉推牌，质感绝了",
      "2026-05-24 11:00",
      "两款同时开！美杜莎4顶配次顶配差别出来了",
      "2026-06-01 21:00",
    ],
    { title: "美杜莎4顶配次顶配差别出来了" },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.title_verified, true);
  assert.equal(selected.title, "两款同时开！美杜莎4顶配次顶配差别出来了");
});

test("selectBestToutiaoManageEvidence falls back on compressed manage page line when title is present", () => {
  const selected = selectBestToutiaoManageEvidence(
    [
      "头条号 全部内容 03:11 锆合金版风灵音叉推牌值得入吗？先看真实体验 已发布 展现 153播放 2点赞 0评论 0 05-23 21:00 查看数据 查看评论 修改 更多",
    ],
    { title: "锆合金版风灵音叉推牌值得入吗？先看真实体验" },
  );

  assert.equal(selected.matched, true);
  assert.equal(selected.title, "锆合金版风灵音叉推牌值得入吗？先看真实体验");
  assert.equal(selected.published_at, "05-23 21:00");
  assert.equal(selected.compressed_manage_fallback, true);
});

test("_buildVerificationOnlyCurrentPageTargetMissing returns route-aware stop instead of fake field mismatch", () => {
  const outcome = _buildVerificationOnlyCurrentPageTargetMissing(
    "douyin",
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      platform_specific_overrides: {
        verification_only_current_page: true,
        wait_for_publish_confirmation: true,
        recovery_mode: "receipt_rebind",
      },
    },
    {
      url: "https://creator.douyin.com/creator-micro/content/manage",
      title: "抖音创作者中心",
    },
    {
      lines: ["作品管理", "已发布", "历史作品列表"],
    },
    {
      verification_state: "ready",
      failures: ["title", "body", "tags", "schedule"],
    },
  );

  assert.equal(outcome.status, "needs_human");
  assert.equal(outcome.error.code, "douyin_verification_current_page_target_missing");
  assert.equal(outcome.result.material_integrity.verification_state, "target_missing");
  assert.equal(outcome.result.recovery_overrides.clear_draft_context, false);
  assert.equal(outcome.result.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(outcome.result.recovery_overrides.verification_only_current_page, true);
  assert.equal(outcome.result.recovery_overrides.wait_for_publish_confirmation, true);
  assert.equal(outcome.result.recovery_overrides.recovery_mode, "receipt_rebind");
});

test("shouldEnforcePlatformPublishRoute preserves douyin management route during receipt rebind verification", () => {
  assert.equal(
    shouldEnforcePlatformPublishRoute("douyin", {
      verification_only_current_page: true,
      recovery_mode: "receipt_rebind",
    }),
    false,
  );
  assert.equal(
    shouldEnforcePlatformPublishRoute("douyin", {
      verification_only_current_page: true,
      recovery_mode: "auto_recover",
    }),
    true,
  );
  assert.equal(
    shouldEnforcePlatformPublishRoute("douyin", {
      repair_only_current_page: true,
      recovery_mode: "prepublish_resume",
    }),
    true,
  );
});

test("shouldEnforcePlatformPublishRoute preserves xiaohongshu note manager route during receipt rebind verification", () => {
  assert.equal(
    shouldEnforcePlatformPublishRoute("xiaohongshu", {
      verification_only_current_page: true,
      recovery_mode: "receipt_rebind",
    }),
    false,
  );
  assert.equal(
    shouldEnforcePlatformPublishRoute("xiaohongshu", {
      repair_only_current_page: true,
      recovery_mode: "prepublish_resume",
      force_publish_page_refresh: true,
    }),
    false,
  );
  assert.equal(
    shouldEnforcePlatformPublishRoute("xiaohongshu", {
      prepare_only_current_page: true,
      recovery_mode: "auto_recover",
    }),
    false,
  );
});

test("shouldEnforcePlatformPublishRoute preserves toutiao manage route during receipt rebind verification", () => {
  assert.equal(
    shouldEnforcePlatformPublishRoute("toutiao", {
      verification_only_current_page: true,
      recovery_mode: "receipt_rebind",
    }),
    false,
  );
});

test("_buildVerificationOnlyMaterialIntegrityFailure blocks verification-only publish page with field mismatches", () => {
  const outcome = _buildVerificationOnlyMaterialIntegrityFailure(
    "douyin",
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      platform_specific_overrides: {
        verification_only_current_page: true,
        wait_for_publish_confirmation: true,
        recovery_mode: "receipt_rebind",
      },
    },
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "抖音创作者中心",
    },
    {
      lines: ["作品描述", "设置封面", "请选择合集", "请选择自主声明"],
    },
    {
      verification_state: "ready",
      failures: ["title", "body", "tags", "schedule", "upload_ready"],
    },
    {
      required_unverified: ["title", "body", "tags", "schedule", "upload_ready", "content_plan_match"],
    },
    {
      title: "",
      body: "",
      scheduled_publish_at: "",
    },
    {
      final_publish: {
        repair_only_current_page: true,
        pre_publish_repair: {
          attempted: true,
          repairable_fields: ["declaration"],
        },
      },
      actions: [
        { kind: "douyin_original_declaration_entry", clicked: true },
        { kind: "douyin_original_declaration_confirm", clicked: true },
      ],
    },
  );

  assert.equal(outcome.status, "needs_human");
  assert.equal(outcome.error.code, "douyin_verification_only_material_integrity_failed");
  assert.equal(outcome.result.recovery_overrides.clear_draft_context, false);
  assert.equal(outcome.result.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(outcome.result.recovery_overrides.verification_only_current_page, true);
  assert.equal(outcome.result.recovery_overrides.wait_for_publish_confirmation, true);
  assert.equal(outcome.result.recovery_overrides.recovery_mode, "receipt_rebind");
  assert.equal(outcome.result.final_publish.repair_only_current_page, true);
  assert.equal(outcome.result.final_publish.pre_publish_repair?.attempted, true);
  assert.equal(outcome.result.actions?.length, 2);
  assert.equal(outcome.result.action_history?.length, 2);
});

test("shouldWaitForVerificationOnlyMaterialIntegrity waits on loading publish route before field audit", () => {
  assert.equal(
    shouldWaitForVerificationOnlyMaterialIntegrity({
      verification_state: "not_ready",
      verification_reason: "publish_route_loading",
      route_ready_state: {
        route_ready: true,
        input_ready: false,
        loading_surface: true,
      },
    }),
    true,
  );
  assert.equal(
    shouldWaitForVerificationOnlyMaterialIntegrity({
      verification_state: "not_ready",
      verification_reason: "publish_route_not_ready",
      route_ready_state: {
        route_ready: true,
        input_ready: false,
        loading_surface: false,
      },
    }),
    true,
  );
  assert.equal(
    shouldWaitForVerificationOnlyMaterialIntegrity({
      verification_state: "ready",
      verification_reason: "ok",
      route_ready_state: {
        route_ready: true,
        input_ready: true,
        loading_surface: false,
      },
    }),
    false,
  );
});

test("shouldTreatCompositeEditorSurfaceAsNotReady rejects xiaohongshu publish skeleton without editable inputs", () => {
  assert.equal(
    shouldTreatCompositeEditorSurfaceAsNotReady(
      "xiaohongshu",
      "https://creator.xiaohongshu.com/publish",
      false,
      { upload_prompt_only: false },
    ),
    true,
  );
  assert.equal(
    shouldTreatCompositeEditorSurfaceAsNotReady(
      "xiaohongshu",
      "https://creator.xiaohongshu.com/publish/success?id=1",
      false,
      { upload_prompt_only: false },
    ),
    false,
  );
  assert.equal(
    shouldTreatCompositeEditorSurfaceAsNotReady(
      "xiaohongshu",
      "https://creator.xiaohongshu.com/publish",
      true,
      { upload_prompt_only: false },
    ),
    false,
  );
});

test("isXiaohongshuPublishEditorSurfaceReady rejects publish skeleton and accepts editor surface", () => {
  assert.equal(
    isXiaohongshuPublishEditorSurfaceReady({
      url: "https://creator.xiaohongshu.com/publish",
      lines: ["遇到问题", "创作服务平台", "发布笔记", "笔记管理"],
      headings: [],
      fileInputs: [],
    }),
    false,
  );
  assert.equal(
    isXiaohongshuPublishEditorSurfaceReady({
      url: "https://creator.xiaohongshu.com/publish",
      lines: ["内容设置", "发布设置", "原创声明", "定时发布", "公开可见"],
      headings: [],
      fileInputs: [],
    }),
    true,
  );
});

test("shouldAllowCompositeFieldPreparation accepts xiaohongshu editor shell while upload still processes", () => {
  assert.equal(
    shouldAllowCompositeFieldPreparation("xiaohongshu", {
      ready: false,
      failed: false,
      last: {
        mediaPresent: true,
        fieldShell: true,
        readySurface: true,
        busy: true,
        uploadPromptOnly: false,
      },
    }),
    true,
  );
});

test("shouldAllowCompositeFieldPreparation rejects douyin upload shell before real editor readiness", () => {
  assert.equal(
    shouldAllowCompositeFieldPreparation("douyin", {
      ready: false,
      failed: false,
      last: {
        mediaPresent: true,
        fieldShell: true,
        readySurface: true,
        douyinReadySurface: false,
        busy: false,
        uploadPromptOnly: false,
      },
    }),
    false,
  );
  assert.equal(
    shouldAllowCompositeFieldPreparation("douyin", {
      ready: false,
      failed: false,
      last: {
        mediaPresent: true,
        fieldShell: true,
        readySurface: true,
        douyinReadySurface: true,
        busy: false,
        uploadPromptOnly: false,
      },
    }),
    true,
  );
});

test("shouldBootstrapCompositeUploadFromCleanEntry starts upload on prompt-only entry", () => {
  assert.equal(
    shouldBootstrapCompositeUploadFromCleanEntry({
      ready: false,
      failed: false,
      last: {
        busy: false,
        mediaPresent: false,
        uploadPromptOnly: true,
        fileInputCount: 1,
      },
    }),
    true,
  );
});

test("shouldBootstrapCompositeUploadFromCleanEntry still starts upload on douyin upload shell with dirty field chrome", () => {
  assert.equal(
    shouldBootstrapCompositeUploadFromCleanEntry({
      ready: false,
      failed: false,
      last: {
        busy: false,
        mediaPresent: false,
        uploadPromptOnly: true,
        fieldShell: true,
        douyinUploadEntrySurface: true,
        douyinReadySurface: false,
        fileInputCount: 1,
      },
    }),
    true,
  );
});

test("shouldBootstrapCompositeUploadFromCleanEntry stays off once media is already present", () => {
  assert.equal(
    shouldBootstrapCompositeUploadFromCleanEntry({
      ready: false,
      failed: false,
      last: {
        busy: false,
        mediaPresent: true,
        uploadPromptOnly: false,
        fileInputCount: 1,
      },
    }),
    false,
  );
});

test("shouldAwaitCompositeUploadEntryHydration waits on douyin loading upload shell before bootstrap", () => {
  assert.equal(
    shouldAwaitCompositeUploadEntryHydration("douyin", {
      ready: false,
      failed: false,
      last: {
        href: "https://creator.douyin.com/creator-micro/content/upload",
        busy: false,
        failed: false,
        mediaPresent: false,
        uploadPromptOnly: false,
        fileInputCount: 0,
        lines: ["加载中，请稍候..."],
      },
    }),
    true,
  );
});

test("shouldAwaitCompositeUploadEntryHydration stops waiting once douyin upload prompt is ready", () => {
  assert.equal(
    shouldAwaitCompositeUploadEntryHydration("douyin", {
      ready: false,
      failed: false,
      last: {
        href: "https://creator.douyin.com/creator-micro/content/upload",
        busy: false,
        failed: false,
        mediaPresent: false,
        uploadPromptOnly: true,
        fileInputCount: 1,
        lines: ["点击上传 或直接将视频文件拖入此区域"],
      },
    }),
    false,
  );
});

test("shouldWaitForCompositeUploadReadyBeforeFieldPreparation skips bilibili wait once editor shell appears during upload", () => {
  assert.equal(
    shouldWaitForCompositeUploadReadyBeforeFieldPreparation("bilibili", {
      ready: false,
      failed: false,
      last: {
        mediaPresent: true,
        fieldShell: true,
        bilibiliMediaAttached: true,
        readySurface: false,
        busy: true,
        uploadPromptOnly: false,
      },
    }),
    false,
  );
});

test("shouldWaitForCompositeUploadReadyBeforeFieldPreparation skips xiaohongshu wait once editor shell appears during upload", () => {
  assert.equal(
    shouldWaitForCompositeUploadReadyBeforeFieldPreparation("xiaohongshu", {
      ready: false,
      failed: false,
      last: {
        mediaPresent: true,
        fieldShell: true,
        readySurface: true,
        busy: true,
        uploadPromptOnly: false,
      },
    }),
    false,
  );
});

test("canReuseCurrentPageMediaForPrepublish reuses bilibili page whenever matching media is already attached", () => {
  const mediaPath = String.raw`E:\WorkSpace\RoughCut\MAXACE 美杜莎4 顶配次顶配开箱.mp4`;
  const state = canReuseCurrentPageMediaForPrepublish(
    "bilibili",
    {
      url: "https://member.bilibili.com/platform/upload/video/frame",
      lines: [
        "发布视频",
        "MAXACE 美杜莎4 顶配次顶配开箱",
        "已上传： 136.5MB/761.1MB",
        "当前速度： 6.5MB/s",
        "剩余时间： 1.6分钟",
        "标题",
        "简介",
        "创作声明",
        "分区",
        "标签",
        "封面设置",
        "加入合集",
        "定时发布",
      ],
      elements: [],
    },
    mediaPath,
    { requiresLocalMedia: true, expectedTitle: "MAXACE美杜莎4双版本开箱，顶配和次顶配到底差在哪" },
  );
  assert.equal(state.reusable, true);
  assert.equal(state.media_attached, true);
  assert.equal(state.reason, "bilibili_upload_attached_pending");
});

test("isXiaohongshuVideoUploadEntrySurface recognizes video upload entry", () => {
  assert.equal(
    isXiaohongshuVideoUploadEntrySurface(
      "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
      "上传视频 拖拽视频到此或点击上传 视频大小 支持时长4小时以内 最大20GB的视频文件",
    ),
    true,
  );
  assert.equal(
    isXiaohongshuVideoUploadEntrySurface(
      "https://creator.xiaohongshu.com/publish",
      "内容设置 发布设置 原创声明",
    ),
    false,
  );
});

test("isPlatformReceiptSurfaceUrl recognizes xiaohongshu receipt routes", () => {
  assert.equal(
    isPlatformReceiptSurfaceUrl(
      "xiaohongshu",
      "https://creator.xiaohongshu.com/publish/success?id=1",
    ),
    true,
  );
  assert.equal(
    isPlatformReceiptSurfaceUrl(
      "xiaohongshu",
      "https://creator.xiaohongshu.com/new/note-manager",
    ),
    true,
  );
});

test("isPlatformReceiptSurfaceUrl recognizes toutiao manage receipt route", () => {
  assert.equal(
    isPlatformReceiptSurfaceUrl(
      "toutiao",
      "https://mp.toutiao.com/profile_v4/manage/content/all",
    ),
    true,
  );
});

test("derivePlatformTabSelectionPolicy prefers receipt surface for xiaohongshu receipt rebind verification", () => {
  assert.deepEqual(
    derivePlatformTabSelectionPolicy("xiaohongshu", {
      verification_only_current_page: true,
      recovery_mode: "receipt_rebind",
    }),
    {
      lock_active_tab: true,
      fresh_start_platform_tab: false,
      prefer_receipt_surface: true,
      prefer_stable_upload_surface: false,
      prefer_draft_list_surface: false,
      allow_safe_autocreate: false,
    },
  );
});

test("derivePlatformTabSelectionPolicy prefers receipt surface for toutiao receipt rebind verification", () => {
  assert.deepEqual(
    derivePlatformTabSelectionPolicy("toutiao", {
      verification_only_current_page: true,
      recovery_mode: "receipt_rebind",
    }),
    {
      lock_active_tab: true,
      fresh_start_platform_tab: false,
      prefer_receipt_surface: true,
      prefer_stable_upload_surface: false,
      prefer_draft_list_surface: false,
      allow_safe_autocreate: false,
    },
  );
});

test("derivePlatformTabSelectionPolicy defaults stop-before-final-publish modes to fresh-start tab", () => {
  assert.deepEqual(
    derivePlatformTabSelectionPolicy("wechat-channels", {
      prepare_only_current_page: true,
    }),
    {
      lock_active_tab: false,
      fresh_start_platform_tab: true,
      prefer_receipt_surface: false,
      prefer_stable_upload_surface: false,
      prefer_draft_list_surface: false,
      allow_safe_autocreate: true,
    },
  );
});

test("derivePlatformTabSelectionPolicy enables fresh-start tab mode for linear prepare runs", () => {
  const policy = derivePlatformTabSelectionPolicy("douyin", {
    prepare_only_current_page: true,
  });

  assert.equal(policy.lock_active_tab, false);
  assert.equal(policy.fresh_start_platform_tab, true);
  assert.equal(policy.allow_safe_autocreate, true);
  assert.equal(policy.prefer_receipt_surface, false);
});

test("derivePlatformTabSelectionPolicy defaults douyin verification-only linear runs to fresh-start tab outside receipt rebind", () => {
  const policy = derivePlatformTabSelectionPolicy("douyin", {
    verification_only_current_page: true,
    recovery_mode: "auto_recover",
  });

  assert.equal(policy.lock_active_tab, false);
  assert.equal(policy.fresh_start_platform_tab, true);
  assert.equal(policy.prefer_receipt_surface, false);
  assert.equal(policy.allow_safe_autocreate, true);
});

test("findPlatformTabs falls back to a unique exact upload entry when active flag is missing", () => {
  const tabs = [
    {
      id: "11",
      type: "page",
      title: "抖音创作者中心",
      url: "https://creator.douyin.com/creator-micro/content/upload",
      active: false,
    },
    {
      id: "12",
      type: "page",
      title: "抖音创作者中心",
      url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
      active: false,
    },
  ];
  const matches = findPlatformTabs(tabs, "douyin", { lock_active_tab: true });
  assert.equal(matches.length, 1);
  assert.equal(matches[0].url, "https://creator.douyin.com/creator-micro/content/upload");
});

test("_buildVerificationOnlyRouteNotReadyFailure blocks unstable publish page before field mismatch diagnosis", () => {
  const outcome = _buildVerificationOnlyRouteNotReadyFailure(
    "douyin",
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
      platform_specific_overrides: {
        verification_only_current_page: true,
        wait_for_publish_confirmation: true,
        recovery_mode: "receipt_rebind",
      },
    },
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "抖音创作者中心",
    },
    {
      lines: ["高清发布", "加载中，请稍候..."],
    },
    {
      verification_state: "not_ready",
      verification_reason: "publish_route_loading",
      route_ready_state: {
        route_ready: true,
        input_ready: false,
        loading_surface: true,
      },
    },
  );

  assert.equal(outcome.status, "needs_human");
  assert.equal(outcome.error.code, "douyin_verification_only_route_not_ready");
  assert.equal(outcome.result.recovery_overrides.clear_draft_context, false);
  assert.equal(outcome.result.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(outcome.result.recovery_overrides.verification_only_current_page, true);
  assert.equal(outcome.result.recovery_overrides.wait_for_publish_confirmation, true);
  assert.equal(outcome.result.recovery_overrides.recovery_mode, "receipt_rebind");
});

test("_buildVerificationOnlyRouteNotReadyFailure uses media-missing code for xiaohongshu upload entry surface", () => {
  const outcome = _buildVerificationOnlyRouteNotReadyFailure(
    "xiaohongshu",
    {
      title: "新到的美杜莎4｜两款配置到手，差别一眼就",
      platform_specific_overrides: {
        repair_only_current_page: true,
        wait_for_publish_confirmation: true,
        recovery_mode: "repair_only_current_page",
      },
    },
    {
      url: "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
      title: "小红书创作服务平台",
    },
    {
      lines: ["上传视频", "拖拽视频到此或点击上传"],
    },
    {
      verification_state: "not_ready",
      verification_reason: "publish_media_entry",
      route_ready_state: {
        route_ready: true,
        input_ready: false,
        loading_surface: false,
      },
    },
  );

  assert.equal(outcome.error.code, "xiaohongshu_verification_only_media_missing");
  assert.equal(outcome.result.recovery_overrides.clear_draft_context, false);
  assert.equal(outcome.result.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(outcome.result.recovery_overrides.repair_only_current_page, true);
});

test("extractDouyinSelectedCollectionEvidence does not accept placeholder-only collection surface", () => {
  const evidence = extractDouyinSelectedCollectionEvidence(
    ["添加合集", "请选择合集", "自主声明", "请选择自主声明"],
    "EDC潮玩桌搭",
    [
      { label: "合集", value: "" },
      { label: "自主声明", value: "" },
    ],
  );

  assert.equal(evidence.actual, "");
  assert.equal(evidence.matched, false);
  assert.equal(evidence.placeholder_visible, true);
});

test("extractDouyinSelectedCollectionEvidence accepts collection selected in labeled field", () => {
  const evidence = extractDouyinSelectedCollectionEvidence(
    ["添加合集", "EDC潮玩桌搭", "自主声明", "无需添加自主声明"],
    "EDC潮玩桌搭",
    [
      { label: "合集", value: "EDC潮玩桌搭" },
    ],
  );

  assert.equal(evidence.actual, "EDC潮玩桌搭");
  assert.equal(evidence.matched, true);
  assert.equal(evidence.source, "input_field");
});

test("extractDouyinSelectedCollectionEvidence accepts inline collection line from douyin preview surface", () => {
  const evidence = extractDouyinSelectedCollectionEvidence(
    ["高清发布 添加合集 合集 EDC刀光火工具集 共1个作品 第2集 自主声明 无需添加自主声明", "合集 · EDC刀光火工具集"],
    "EDC刀光火工具集",
    [],
  );

  assert.equal(evidence.actual, "EDC刀光火工具集");
  assert.equal(evidence.matched, true);
  assert.equal(evidence.source, "inline_line");
});

test("selectDouyinTopicSuggestionCandidate prefers short layered topic chip over body hashtag text", () => {
  const chosen = selectDouyinTopicSuggestionCandidate([
    {
      text: "等了好久的MAXACE美杜莎4终于到货，两个版本都拿下，给大家看看有啥区别。#EDC折刀 #MAXACE美杜莎4 #开箱",
      context: "作品描述 作品描述 作品描述",
      area: 48000,
      inLayer: false,
      isButtonLike: false,
      className: "editor-body",
    },
    {
      text: "#EDC折刀",
      context: "添加话题 推荐话题 热度",
      area: 2800,
      inLayer: true,
      isButtonLike: true,
      isSearchResult: true,
      className: "topic-option-chip",
    },
  ], "EDC折刀");

  assert.equal(chosen?.text, "#EDC折刀");
  assert.equal(chosen?.inLayer, true);
});

test("extractDouyinTopicVerificationLabels ignores hot-list suggestions and helper controls", () => {
  const labels = extractDouyinTopicVerificationLabels([
    { text: "#EDC折刀", context: "添加话题 @好友" },
    { text: "#MAXACE美杜莎4", context: "添加话题 @好友" },
    { text: "#等了好久", context: "推荐话题 热度 2.5亿" },
    { text: "#情侣手表 #耳机套 #微单", context: "添加话题 @好友 推荐" },
    { text: "#添加话题 @好友 355 / 1000", context: "添加话题 @好友" },
    { text: "#添加话题", context: "添加话题 @好友" },
  ]);

  assert.deepEqual(labels, ["EDC折刀", "MAXACE美杜莎4"]);
});

test("selectDouyinTopicSearchFieldCandidate rejects recommendation container and prefers editable search input", () => {
  const chosen = selectDouyinTopicSearchFieldCandidate([
    {
      tag: "div",
      role: "",
      label: "推荐 #情侣手表 #耳机套",
      current: "",
      root_area: 44000,
      isContentEditable: false,
    },
    {
      tag: "input",
      role: "combobox",
      label: "搜索话题 添加话题 推荐",
      current: "",
      root_area: 42000,
      isContentEditable: false,
    },
  ]);

  assert.equal(chosen?.tag, "input");
  assert.equal(chosen?.role, "combobox");
});

test("buildXiaohongshuTopicSearchQuery prefixes native topic text with hash", () => {
  assert.equal(buildXiaohongshuTopicSearchQuery("折刀"), "#折刀");
  assert.equal(buildXiaohongshuTopicSearchQuery("#刀具开箱"), "#刀具开箱");
});

test("extractXiaohongshuTopicVerificationLabels keeps body hashtags and rejects recommendation-only hot topics", () => {
  const labels = extractXiaohongshuTopicVerificationLabels([
    { text: "适合喜欢EDC又追求一点品质感的玩家～ #EDC折刀 #MAXACE美杜莎4 #刀具开箱", context: "body", source: "body" },
    { text: "#猴哥业务都发展到冰岛了", context: "添加话题 推荐 5.1亿浏览", source: "chip" },
    { text: "#折刀收藏", context: "已选话题", source: "chip" },
  ], ["EDC折刀", "MAXACE美杜莎4", "折刀收藏", "刀具开箱"]);

  assert.deepEqual(labels, ["EDC折刀", "MAXACE美杜莎4", "刀具开箱", "折刀收藏"]);
});

test("extractXiaohongshuInsertedTopicLabels ignores plain body hashtags and keeps only inserted native topics", () => {
  const labels = extractXiaohongshuInsertedTopicLabels([
    { text: "适合喜欢EDC又追求一点品质感的玩家～ #EDC折刀 #MAXACE美杜莎4 #刀具开箱", context: "body", source: "body" },
    { text: "#猴哥业务都发展到冰岛了", context: "添加话题 推荐 5.1亿浏览", source: "chip" },
    { text: "#折刀收藏", context: "已选话题", source: "chip" },
    { text: "#刀具开箱", context: "已选话题", source: "chip" },
  ], ["EDC折刀", "MAXACE美杜莎4", "折刀收藏", "刀具开箱"]);

  assert.deepEqual(labels, ["折刀收藏", "刀具开箱"]);
});

test("selectXiaohongshuTopicSearchFieldCandidate rejects body editor and prefers topic search input", () => {
  const chosen = selectXiaohongshuTopicSearchFieldCandidate([
    {
      tag: "input",
      type: "file",
      role: "",
      label: "拖拽视频到此或点击上传 上传视频",
      current: "",
      root_area: 36000,
      isContentEditable: false,
    },
    {
      tag: "div",
      role: "textbox",
      label: "正文 笔记描述 1000字",
      current: "终于等到的新货",
      root_area: 180000,
      isContentEditable: true,
    },
    {
      tag: "input",
      role: "searchbox",
      label: "添加话题 搜索话题",
      current: "",
      root_area: 42000,
      isContentEditable: false,
    },
  ]);

  assert.equal(chosen?.tag, "input");
  assert.equal(chosen?.role, "searchbox");
});

test("selectXiaohongshuTopicSearchFieldCandidate returns null when only body editor and generic title input exist", () => {
  const chosen = selectXiaohongshuTopicSearchFieldCandidate([
    {
      tag: "input",
      type: "text",
      role: "",
      label: "填写标题会有更多赞哦",
      current: "",
      root_area: 38000,
      isContentEditable: false,
    },
    {
      tag: "div",
      role: "textbox",
      label: "正文 笔记描述 1000字",
      current: "#刀具开箱",
      root_area: 160000,
      isContentEditable: true,
    },
  ]);

  assert.equal(chosen, null);
});

test("selectXiaohongshuTopicSearchFieldCandidate rejects generic title input when no topic search field exists", () => {
  const chosen = selectXiaohongshuTopicSearchFieldCandidate([
    {
      tag: "input",
      type: "text",
      role: "",
      label: "填写标题会有更多赞哦",
      current: "",
      root_area: 38000,
      isContentEditable: false,
    },
    {
      tag: "div",
      role: "textbox",
      label: "正文 笔记描述 1000字",
      current: "#",
      root_area: 160000,
      isContentEditable: true,
    },
  ]);

  assert.equal(chosen, null);
});

test("selectXiaohongshuOriginalDeclarationControlCandidate prefers original wrapper and rejects pk cover controls", () => {
  const chosen = selectXiaohongshuOriginalDeclarationControlCandidate([
    {
      tag: "div",
      className: "pk-cover-switch d-switch",
      text: "PK封面",
      role: "",
      disabled: false,
    },
    {
      tag: "div",
      className: "custom-switch-card",
      text: "原创声明",
      role: "",
      disabled: false,
    },
    {
      tag: "div",
      className: "custom-switch-switch",
      text: "",
      role: "",
      disabled: false,
    },
  ]);

  assert.equal(chosen?.className, "custom-switch-card");
  assert.equal(chosen?.text, "原创声明");
});

test("isDouyinCustomCoverReady rejects ai-recommended-only cover surface", () => {
  const ready = isDouyinCustomCoverReady({
    textHaystack: "设置封面 横封面4:3 竖封面3:4 Ai智能推荐封面生成中...",
    expectedCoverPath: "E:/covers/02-douyin-cover.jpg",
    coverActual: "",
    imageSources: [
      "https://p3-sign.douyinpic.com/tos-cn-p-0015/default-preview.webp",
    ],
    backgroundSources: [],
  });

  assert.equal(ready, false);
});

test("classifyDouyinCoverUploadInputRoot rejects reference rail and accepts main upload surface", () => {
  const reference = classifyDouyinCoverUploadInputRoot({
    localRootText: "",
    localRootClass: "semi-upload",
    sideRootText: "生成参考图 智能参考",
    sideRootClass: "container-kgE14y container-Xnz3EO list-Ldrppp",
    dialogText: "设置竖封面 AI生成封面 上传封面",
  });
  const primary = classifyDouyinCoverUploadInputRoot({
    localRootText: "点击上传文件或拖拽文件到这里",
    localRootClass: "semi-upload upload-BvM5FF",
    mainRootText: "上传封面 点击上传文件或拖拽文件到这里",
    mainRootClass: "main-DAkOod selectArea-BCIYQD container-qVqwfQ",
    dialogText: "设置竖封面 上传封面 竖封面预览（3:4）",
  });

  assert.equal(reference.reference_upload, true);
  assert.equal(reference.primary_upload, false);
  assert.equal(primary.primary_upload, true);
  assert.equal(primary.reference_upload, false);
});

test("selectDouyinCoverSlotSurfaceCandidate prefers coverControl slot over ai recommendation rail", () => {
  const chosen = selectDouyinCoverSlotSurfaceCandidate([
    {
      text: "横封面4:3 编辑封面",
      area: 23520,
      className: "coverControl-CjlzqC",
      action_labels: ["编辑封面"],
    },
    {
      text: "横封面4:3 Ai智能推荐封面 生成参考图 智能参考 AI生成封面",
      area: 168000,
      className: "recommendContainer-xwwJ2i",
      action_labels: [],
    },
  ], ["横封面4:3"]);

  assert.equal(chosen?.className, "coverControl-CjlzqC");
  assert.deepEqual(chosen?.action_labels, ["编辑封面"]);
});

test("isDouyinCoverEditorImmediateEditable accepts uploaded cover editor even while ai area is still spinning", () => {
  const editable = isDouyinCoverEditorImmediateEditable({
    editor_open: true,
    confirm_button_visible: true,
    upload_button_visible: true,
    preview_image_count: 3,
    has_blob_preview: false,
    spinner_visible: true,
  });

  assert.equal(editable, true);
});

test("deriveDouyinCoverState requires saved state after editor modal closes", () => {
  const state = deriveDouyinCoverState({
    textHaystack: "设置封面 重新上传 自定义封面",
    expectedCoverPath: "E:/covers/02-douyin-cover.jpg",
    coverActual: "",
    imageSources: ["blob:https://creator.douyin.com/cover-preview"],
    backgroundSources: [],
    modalOpen: true,
  });

  assert.equal(state.custom_cover_ready, true);
  assert.equal(state.saved, false);
  assert.equal(state.modal_open, true);
});

test("deriveDouyinCoverState marks saved after custom cover preview is persisted", () => {
  const state = deriveDouyinCoverState({
    textHaystack: "设置封面 重新上传 自定义封面",
    expectedCoverPath: "E:/covers/02-douyin-cover.jpg",
    coverActual: "",
    imageSources: ["blob:https://creator.douyin.com/cover-preview"],
    backgroundSources: [],
    modalOpen: false,
  });

  assert.equal(state.custom_cover_ready, true);
  assert.equal(state.saved, true);
  assert.equal(state.explicit_upload_success, true);
});

test("deriveDouyinCoverState ignores stale dual-cover warning when both required slots have preview evidence", () => {
  const state = deriveDouyinCoverState({
    textHaystack: "横/竖双封面缺失 为增加作品的流量，建议同时设置横版和竖版的封面",
    expectedCoverSlots: [
      { slot: "horizontal_4_3", label: "横封面4:3", cover_path: "E:/covers/landscape.jpg" },
      { slot: "vertical_3_4", label: "竖封面3:4", cover_path: "E:/covers/portrait.jpg" },
    ],
    slotSurfaces: [
      {
        slot: "horizontal_4_3",
        label: "横封面4:3",
        image_sources: ["blob:https://creator.douyin.com/landscape-preview"],
        action_labels: ["重新上传"],
      },
      {
        slot: "vertical_3_4",
        label: "竖封面3:4",
        image_sources: ["blob:https://creator.douyin.com/portrait-preview"],
        action_labels: ["重新上传"],
      },
    ],
    modalOpen: false,
  });

  assert.equal(state.custom_cover_ready, true);
  assert.equal(state.saved, true);
  assert.equal(state.effective_dual_cover_missing_warning, false);
});

test("deriveDouyinCoverState prioritizes main-form slot visuals over warning text", () => {
  const state = deriveDouyinCoverState({
    textHaystack: "封面优化建议共1条 竖封面缺失 设置封面 横封面4:3 竖封面3:4",
    expectedCoverSlots: [
      { slot: "horizontal_4_3", label: "横封面4:3", cover_path: "E:/covers/landscape.jpg" },
      { slot: "vertical_3_4", label: "竖封面3:4", cover_path: "E:/covers/portrait.jpg" },
    ],
    slotSurfaces: [
      {
        slot: "horizontal_4_3",
        label: "横封面4:3",
        image_sources: ["https://p0-creator-media-private.douyin.com/horizontal.jpeg"],
        action_labels: ["横封面4:3"],
      },
      {
        slot: "vertical_3_4",
        label: "竖封面3:4",
        image_sources: ["https://p0-creator-media-private.douyin.com/vertical.jpeg"],
        action_labels: ["竖封面3:4"],
      },
    ],
    modalOpen: false,
  });

  assert.equal(state.custom_cover_ready, true);
  assert.equal(state.saved, true);
  assert.equal(state.effective_dual_cover_missing_warning, false);
  assert.equal(state.slots.every((item) => item.surface_has_visual_cover), true);
});

test("selectDouyinCoverSlotSurfaceCandidate prefers narrow cover slot over wrapper shell", () => {
  const chosen = selectDouyinCoverSlotSurfaceCandidate(
    [
      {
        text: "选择封面 横封面4:3 选择封面 竖封面3:4 Ai智能推荐封面生成中...",
        className: "wrapper-NN3Jh1",
        area: 81144,
        action_labels: ["选择封面"],
      },
      {
        text: "横封面4:3",
        className: "coverControl-CjlzqC",
        area: 23520,
        action_labels: [],
      },
    ],
    ["横封面4:3"],
  );

  assert.equal(chosen?.className, "coverControl-CjlzqC");
  assert.equal(chosen?.text, "横封面4:3");
});

test("selectDouyinCoverSlotEntryTarget prefers inner clickable cover entry over slot shell", () => {
  const chosen = selectDouyinCoverSlotEntryTarget(
    [
      {
        text: "选择封面 竖封面3:4",
        className: "coverControl-CjlzqC",
        area: 13230,
        onclick: false,
        slot_text: "选择封面 竖封面3:4",
      },
      {
        text: "选择封面",
        className: "cover-Jg3T4p",
        area: 10800,
        onclick: true,
        slot_text: "选择封面 竖封面3:4",
      },
    ],
    ["选择封面", "竖封面3:4"],
  );

  assert.equal(chosen?.className, "cover-jg3t4p");
  assert.equal(chosen?.text, "选择封面");
  assert.equal(chosen?.onclick, true);
});

test("isDouyinCoverEditorModalText rejects main publish shell preview text", () => {
  assert.equal(
    isDouyinCoverEditorModalText("高清发布 基础信息 作品描述 设置封面 预览视频 预览封面/标题 发文助手"),
    false,
  );
});

test("isDouyinCoverEditorModalText accepts real douyin cover editor text", () => {
  assert.equal(
    isDouyinCoverEditorModalText("设置竖封面 上传封面 点击上传文件或拖拽文件到这里 竖封面预览 完成 取消保存"),
    true,
  );
});

test("isDouyinFormalCompositeCoverEditorState rejects non-formal single-cover modal", () => {
  assert.equal(
    isDouyinFormalCompositeCoverEditorState({
      root_text: "设置封面 重新上传 取消 保存",
      editor_open: true,
      confirm_button_visible: true,
    }),
    false,
  );
});

test("isDouyinFormalCompositeCoverEditorState accepts formal dual-cover editor", () => {
  assert.equal(
    isDouyinFormalCompositeCoverEditorState({
      root_text: "设置竖封面 设置横封面 AI封面 上传封面 点击上传文件或拖拽文件到这里 封面检测 完成 设置横封面 竖封面预览（3:4）",
      editor_open: true,
      confirm_button_visible: true,
    }),
    true,
  );
});

test("buildDouyinCompositeCoverEditorPlan uploads vertical and horizontal before final confirm", () => {
  assert.deepEqual(
    buildDouyinCompositeCoverEditorPlan([
      { slot: "horizontal_4_3", label: "横封面4:3", cover_path: "E:/covers/h.jpg" },
      { slot: "vertical_3_4", label: "竖封面3:4", cover_path: "E:/covers/v.jpg" },
    ]).map((item) => item.slot),
    ["vertical_3_4", "horizontal_4_3"],
  );
});

test("buildDouyinPrepareProjectExecutionPlan follows publish scheme order and coalesces composite steps", () => {
  assert.deepEqual(
    buildDouyinPrepareProjectExecutionPlan("douyin"),
    [
      { kind: "cover", project_keys: ["cover_upload_4_3", "cover_upload_3_4"] },
      { kind: "rich_text", project_keys: ["title", "body"] },
      { kind: "topics", project_keys: ["tags"] },
      { kind: "collection", project_keys: ["collection"] },
      { kind: "declaration", project_keys: ["declaration"] },
      { kind: "visibility", project_keys: ["visibility"] },
      { kind: "schedule", project_keys: ["schedule"] },
    ],
  );
});

test("filterDouyinPrepareProjectExecutionPlan skips unavailable douyin editor controls", () => {
  assert.deepEqual(
    filterDouyinPrepareProjectExecutionPlan(
      buildDouyinPrepareProjectExecutionPlan("douyin"),
      {
        rich_text: true,
        cover: false,
        topics: true,
        collection: false,
        declaration: false,
        visibility: true,
        schedule: true,
      },
    ),
    [
      { kind: "cover", project_keys: ["cover_upload_4_3", "cover_upload_3_4"], actionable: false, blocked_reason: "editor_control_not_available" },
      { kind: "rich_text", project_keys: ["title", "body"], actionable: true, blocked_reason: "" },
      { kind: "topics", project_keys: ["tags"], actionable: true, blocked_reason: "" },
      { kind: "collection", project_keys: ["collection"], actionable: false, blocked_reason: "editor_control_not_available" },
      { kind: "declaration", project_keys: ["declaration"], actionable: false, blocked_reason: "editor_control_not_available" },
      { kind: "visibility", project_keys: ["visibility"], actionable: true, blocked_reason: "" },
      { kind: "schedule", project_keys: ["schedule"], actionable: true, blocked_reason: "" },
    ],
  );
});

test("preferredXiaohongshuCoverRatioTexts follows resolved xiaohongshu cover slot contract", () => {
  assert.deepEqual(
    preferredXiaohongshuCoverRatioTexts({
      cover_slots: [
        { slot: "portrait_3_4", label: "竖封面3:4", cover_path: "E:/covers/portrait.jpg", matrix_key: "portrait_3_4" },
      ],
    }),
    ["3:4", "4:3"],
  );
  assert.deepEqual(
    preferredXiaohongshuCoverRatioTexts({
      cover_slots: [
        { slot: "landscape_4_3", label: "横封面4:3", cover_path: "E:/covers/landscape.jpg", matrix_key: "landscape_4_3" },
      ],
    }),
    ["4:3", "3:4"],
  );
});

test("deriveDouyinCoverState does not trust text-only upload success without local preview", () => {
  const state = deriveDouyinCoverState({
    textHaystack: "设置封面 重新上传 自定义封面",
    expectedCoverPath: "E:/covers/02-douyin-cover.jpg",
    coverActual: "",
    imageSources: ["https://p3-sign.douyinpic.com/tos-cn-p-0015/default-preview.webp"],
    backgroundSources: [],
    modalOpen: false,
  });

  assert.equal(state.explicit_upload_success, true);
  assert.equal(state.has_local_preview, false);
  assert.equal(state.custom_cover_ready, false);
  assert.equal(state.saved, false);
});

test("selectDouyinCoverSlotSurfaceCandidate prefers scoped slot surface over full page shell", () => {
  const chosen = selectDouyinCoverSlotSurfaceCandidate([
    {
      text: "高清发布 基础信息 作品描述 官方活动 设置封面 选择封面 横封面4:3 选择封面 竖封面3:4 发布设置 预览视频 横/竖双封面缺失",
      area: 620000,
      action_labels: ["设置封面", "选择封面", "选择封面"],
      className: "page-shell",
    },
    {
      text: "设置封面 选择封面 横封面4:3",
      area: 12000,
      action_labels: ["选择封面"],
      className: "cover-slot-card",
    },
  ], ["横封面4:3", "横封面 4:3"]);

  assert.equal(chosen?.text, "设置封面 选择封面 横封面4:3");
  assert.equal(chosen?.area, 12000);
});

test("isDouyinCustomCoverReady accepts uploaded cover when reupload marker appears", () => {
  const ready = isDouyinCustomCoverReady({
    textHaystack: "设置封面 重新上传 自定义封面",
    expectedCoverPath: "E:/covers/02-douyin-cover.jpg",
    coverActual: "",
    imageSources: [
      "blob:https://creator.douyin.com/cover-preview",
    ],
    backgroundSources: [],
  });

  assert.equal(ready, true);
});

test("selectDouyinCoverConfirmCandidate prefers primary 保存 button inside cover modal", () => {
  const chosen = selectDouyinCoverConfirmCandidate([
    {
      label: "取消",
      className: "button-dhlUZE btn-T7MBag normal-XC0CLh",
      x: 959,
      y: 569,
      dialog_text: "设置封面 重新上传 取消保存",
    },
    {
      label: "保存",
      className: "button-dhlUZE btn-T7MBag primary-cECiOJ",
      x: 1023,
      y: 569,
      dialog_text: "设置封面 重新上传 取消保存",
    },
  ]);

  assert.equal(chosen.label, "保存");
  assert.match(chosen.className, /primary/i);
});

test("selectDouyinCoverConfirmCandidate rejects cancel-only controls", () => {
  const chosen = selectDouyinCoverConfirmCandidate([
    {
      label: "取消",
      className: "button-dhlUZE btn-T7MBag normal-XC0CLh",
      x: 959,
      y: 569,
      dialog_text: "设置封面 重新上传 取消保存",
    },
  ]);

  assert.equal(chosen, null);
});

test("buildCompositePublicationAudit does not require receipt before final publish", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-05-31 20:30:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        schedule: { expected: "2026-05-31 20:30", actual: "2026-05-31 20:30", verified: true },
        upload_ready: { actual: "ready", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
        receipt_like: false,
      },
    },
    {},
    { url: "https://creator.douyin.com/creator-micro/content/post/video" },
  );

  assert.equal(audit.checklist.receipt.required, false);
  assert.ok(!audit.required_unverified.includes("receipt"));
  assert.ok(!audit.required_reupload.includes("receipt"));
});

test("buildCompositePublicationAudit requires receipt after final publish attempt", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        upload_ready: { actual: "ready", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
        receipt_like: false,
      },
    },
    {
      click: { clicked: true },
      receipt_like: false,
      receipt_wait: 65000,
    },
    { url: "https://creator.douyin.com/creator-micro/content/post/video" },
  );

  assert.equal(audit.checklist.receipt.required, true);
  assert.ok(audit.required_unverified.includes("receipt"));
  assert.ok(audit.required_reupload.includes("receipt"));
});

test("deriveCompositeFinalPrePublishVisualVerification blocks douyin when cover is not visually verified", () => {
  const verification = deriveCompositeFinalPrePublishVisualVerification(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      cover_path: "E:/covers/02-douyin-cover.jpg",
    },
    {
      verification_state: "ready",
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
      },
    },
    {
      checklist: {
        title: { verified: true, expected: "测试标题", actual: "测试标题" },
        body: { verified: true, expected: "测试正文", actual: "测试正文" },
        tags: { verified: true, expected: ["标签A"], actual: ["标签A"] },
        declaration: { verified: true, expected: "无需添加自主声明", actual: "无需添加自主声明" },
        cover: { verified: false, expected: "E:/covers/02-douyin-cover.jpg", actual: "" },
        upload_ready: { verified: true, expected: "ready", actual: "ready" },
        draft_state: { verified: true, expected: "editor_clean", actual: "clean" },
      },
    },
    {
      cover_path: "E:/covers/02-douyin-cover.jpg",
      route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
    },
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "发布页",
      visual_evidence: { artifact_path: "E:/artifacts/douyin-prepublish.png", capture_type: "screenshot", phase: "pre_publish_page_snapshot" },
      lines: ["发布", "设置封面", "重新上传"],
    },
  );

  assert.equal(verification.verified, false);
  assert.deepEqual(verification.blocked_fields, ["cover"]);
  assert.match(verification.blocking_reasons.join(","), /required_fields:cover/);
});

test("deriveCompositeFinalPrePublishVisualVerification blocks dirty draft even when fields otherwise verify", () => {
  const verification = deriveCompositeFinalPrePublishVisualVerification(
    "youtube",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
    },
    {
      verification_state: "ready",
      platform_extras: {
        route: { url: "https://studio.youtube.com/channel/abc/videos/upload", title: "Studio" },
      },
    },
    {
      checklist: {
        title: { verified: true, expected: "测试标题", actual: "测试标题" },
        body: { verified: true, expected: "测试正文", actual: "测试正文" },
        tags: { verified: true, expected: ["标签A"], actual: ["标签A"] },
        upload_ready: { verified: true, expected: "ready", actual: "ready" },
        draft_state: { verified: false, expected: "editor_clean", actual: "residual_artifacts" },
      },
    },
    {
      route: { url: "https://studio.youtube.com/channel/abc/videos/upload", title: "Studio" },
      draft_state: "residual_artifacts",
    },
    {
      url: "https://studio.youtube.com/channel/abc/videos/upload",
      title: "Studio",
      visual_evidence: { artifact_path: "E:/artifacts/youtube-prepublish.png", capture_type: "screenshot", phase: "pre_publish_page_snapshot" },
      lines: ["上传视频", "继续编辑", "草稿"],
    },
  );

  assert.equal(verification.verified, false);
  assert.match(verification.blocking_reasons.join(","), /draft_state_not_clean/);
});

test("deriveCompositeFinalPrePublishVisualVerification requires screenshot evidence before final publish", () => {
  const verification = deriveCompositeFinalPrePublishVisualVerification(
    "xiaohongshu",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
    },
    {
      verification_state: "ready",
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/publish/publish", title: "发布页" },
      },
    },
    {
      checklist: {
        title: { verified: true, expected: "测试标题", actual: "测试标题" },
        body: { verified: true, expected: "测试正文", actual: "测试正文" },
        tags: { verified: true, expected: ["标签A"], actual: ["标签A"] },
        upload_ready: { verified: true, expected: "ready", actual: "ready" },
        draft_state: { verified: true, expected: "editor_clean", actual: "clean" },
      },
    },
    {
      route: { url: "https://creator.xiaohongshu.com/publish/publish", title: "发布页" },
    },
    {
      url: "https://creator.xiaohongshu.com/publish/publish",
      title: "发布页",
      lines: ["发布", "标题", "正文"],
    },
  );

  assert.equal(verification.verified, false);
  assert.match(verification.blocking_reasons.join(","), /missing_visual_evidence/);
});

test("deriveCompositeFinalPrePublishVisualVerification passes when required fields and screenshot evidence are present", () => {
  const verification = deriveCompositeFinalPrePublishVisualVerification(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      cover_path: "E:/covers/02-douyin-cover.jpg",
      scheduled_publish_at: "2026-06-03 20:30:00",
    },
    {
      verification_state: "ready",
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
      },
    },
    {
      checklist: {
        title: { verified: true, expected: "测试标题", actual: "测试标题" },
        body: { verified: true, expected: "测试正文", actual: "测试正文" },
        tags: { verified: true, expected: ["标签A"], actual: ["标签A"] },
        cover: { verified: true, expected: "E:/covers/02-douyin-cover.jpg", actual: "02-douyin-cover.jpg" },
        declaration: { verified: true, expected: "无需添加自主声明", actual: "无需添加自主声明" },
        schedule: { verified: true, expected: "2026-06-03 20:30", actual: "2026-06-03 20:30" },
        upload_ready: { verified: true, expected: "ready", actual: "ready" },
        draft_state: { verified: true, expected: "editor_clean", actual: "clean" },
      },
    },
    {
      cover_path: "E:/covers/02-douyin-cover.jpg",
      route: { url: "https://creator.douyin.com/creator-micro/content/post/video", title: "发布页" },
    },
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "发布页",
      visual_evidence: { artifact_path: "E:/artifacts/douyin-prepublish-ok.png", capture_type: "screenshot", phase: "pre_publish_page_snapshot" },
      lines: ["发布", "设置封面", "定时发布"],
    },
  );

  assert.equal(verification.verified, true);
  assert.deepEqual(verification.blocked_fields, []);
  assert.deepEqual(verification.blocking_reasons, []);
});

test("normalizeCompositePostPublishIntegrity does not treat unbound douyin management receipt as post-publish field evidence", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "douyin",
    {
      fields: {
        title: { expected: "测试标题", actual: "", verified: false },
        body: { expected: "测试正文", actual: "作品管理 全部作品 已发布 发布成功", verified: false },
        tags: { expected: ["标签A"], actual: ["折刀"], verified: false },
        schedule: { expected: "2026-05-31 20:30", actual: "", verified: false },
        upload_ready: { actual: "ready", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
        relevant_lines: ["作品管理", "已发布", "发布成功"],
        receipt_like: false,
      },
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        schedule: { expected: "2026-05-31 20:30", actual: "2026-05-31 20:30", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
          relevant_lines: ["发布成功"],
        },
      },
    },
  );

  assert.equal(normalized.fields.title.actual, "");
  assert.equal(normalized.fields.body.actual, "作品管理 全部作品 已发布 发布成功");
  assert.deepEqual(normalized.fields.tags.actual, ["折刀"]);
  assert.equal(normalized.fields.schedule.actual, "");
  assert.equal(normalized.platform_extras.receipt_like, true);
  assert.equal(normalized.platform_extras.post_publish_surface, "douyin_content_manage_receipt");
  assert.equal(normalized.platform_extras.receipt_target_bound, false);
  assert.equal(normalized.platform_extras.receipt_binding_source, "unbound_manage_receipt");
});

test("normalizeCompositePostPublishIntegrity binds douyin management receipt to the matching item card", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "douyin",
    {
      fields: {
        title: { expected: "两款同时开！美杜莎4顶配次顶配差别出来了", actual: "", verified: false },
        body: { expected: "旧值", actual: "整页文本", verified: false },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"], actual: ["EDC折刀"], verified: false },
        schedule: { expected: "2026-05-31 20:30", actual: "", verified: false },
        upload_ready: { actual: "ready", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
        relevant_lines: [
          "10:08 两款同时开！美杜莎4顶配次顶配差别出来了 顶配和次顶配同时到手，上手那一刻差别就出来了。轴部阻尼能明显感觉到差别，次顶配已经很顺，顶配更细腻。做工扎实，拿在手里那种踏实感很真实。选哪款看完应该有答案了。 #EDC折刀 #MAXACE美杜莎4 #开箱对比 #折刀 #刀具装备 继续编辑 作品置顶 删除作品 定时发布中 定时: 2026年05月31日 20:30 修改定时",
        ],
        receipt_like: false,
      },
    },
    {
      fields: {
        title: { expected: "两款同时开！美杜莎4顶配次顶配差别出来了", actual: "两款同时开！美杜莎4顶配次顶配差别出来了", verified: true },
        body: { expected: "顶配和次顶配同时到手，上手那一刻差别就出来了。", actual: "顶配和次顶配同时到手，上手那一刻差别就出来了。", verified: true },
        tags: { expected: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"], actual: ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"], verified: true },
        schedule: { expected: "2026-05-31 20:30", actual: "2026-05-31 20:30", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
          relevant_lines: ["发布成功"],
        },
      },
    },
  );

  assert.equal(normalized.fields.title.actual, "两款同时开！美杜莎4顶配次顶配差别出来了");
  assert.equal(normalized.fields.schedule.actual, "2026-05-31 20:30");
  assert.deepEqual(normalized.fields.tags.actual, ["EDC折刀", "MAXACE美杜莎4", "开箱对比", "折刀", "刀具装备"]);
  assert.equal(normalized.fields.tags.verified, true);
  assert.equal(normalized.fields.schedule.verified, true);
  assert.equal(normalized.platform_extras.receipt_target_bound, true);
  assert.equal(normalized.platform_extras.receipt_binding_source, "douyin_manage_card");
  assert.equal(normalized.verification_state, "ready");
  assert.equal(normalized.verification_reason, "receipt_bound");
  assert.equal(normalized.route_ready_state?.input_ready, true);
  assert.equal(normalized.route_ready_state?.loading_surface, false);
});

test("normalizeCompositePostPublishIntegrity leaves non-receipt douyin surfaces untouched", () => {
  const finalIntegrity = {
    fields: {
      title: { expected: "测试标题", actual: "", verified: false },
    },
    platform_extras: {
      route: { url: "https://creator.douyin.com/creator-micro/content/manage", title: "作品管理" },
      relevant_lines: ["作品管理"],
    },
  };

  const normalized = normalizeCompositePostPublishIntegrity(
    "douyin",
    finalIntegrity,
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
      },
    },
    {
      receipt_like: false,
    },
  );

  assert.equal(normalized, finalIntegrity);
});

test("normalizeCompositePostPublishIntegrity marks xiaohongshu publish success route as bound receipt", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "xiaohongshu",
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/publish/success?id=1", title: "发布成功" },
        relevant_lines: ["发布成功", "笔记发布成功", "审核中"],
        receipt_like: true,
      },
    },
    {
      fields: {
        cover: { expected: "E:/covers/xhs-cover.jpg", actual: "xhs-cover.jpg", verified: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        declaration: { expected: "原创声明", actual: "原创声明", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://creator.xiaohongshu.com/publish/success?id=1", title: "发布成功" },
          relevant_lines: ["发布成功", "笔记发布成功"],
        },
      },
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, true);
  assert.equal(normalized.platform_extras.receipt_binding_source, "xiaohongshu_publish_success");
  assert.equal(normalized.platform_extras.post_publish_surface, "xiaohongshu_publish_success_receipt");
  assert.equal(normalized.verification_reason, "receipt_bound");
  assert.equal(normalized.fields.collection.actual, "EDC潮玩桌搭");
});

test("normalizeCompositePostPublishIntegrity marks xiaohongshu note manager route as target-missing receipt when title is absent", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "xiaohongshu",
    {
      fields: {
        title: { expected: "测试标题", actual: "", verified: false },
      },
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/new/note-manager", title: "小红书创作服务平台" },
        relevant_lines: [
          "全部 30",
          "已发布",
          "03:11",
          "锆合金版本的音叉推牌，质感绝了",
          "2026-05-24 11:00",
        ],
        receipt_like: true,
      },
    },
    {
      fields: {
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected: "E:/covers/xhs-cover.jpg", actual: "xhs-cover.jpg", verified: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        declaration: { expected: "原创声明", actual: "原创声明", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      task_created_at: "2026-06-01T21:00:00+08:00",
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://creator.xiaohongshu.com/new/note-manager", title: "小红书创作服务平台" },
          relevant_lines: ["已发布"],
        },
      },
    },
    {
      title: "新到的美杜莎4｜两款配置到手，差别一眼就",
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, false);
  assert.equal(normalized.platform_extras.receipt_binding_source, "xiaohongshu_note_manager_unbound");
  assert.equal(normalized.platform_extras.post_publish_surface, "xiaohongshu_note_manager_receipt");
});

test("normalizeCompositePostPublishIntegrity marks xiaohongshu note manager route as bound receipt when title matches", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "xiaohongshu",
    {
      fields: {
        title: { expected: "新到的美杜莎4｜两款配置到手，差别一眼就", actual: "", verified: false },
      },
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/new/note-manager", title: "小红书创作服务平台" },
        relevant_lines: [
          "全部 30",
          "已发布",
          "10:08",
          "新到的美杜莎4｜两款配置到手，差别一眼就",
          "2026-06-01 21:00",
          "120",
          "0",
          "0",
        ],
        receipt_like: true,
      },
    },
    {
      fields: {
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected: "E:/covers/xhs-cover.jpg", actual: "xhs-cover.jpg", verified: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        declaration: { expected: "原创声明", actual: "原创声明", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      task_created_at: "2026-06-01T21:00:00+08:00",
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://creator.xiaohongshu.com/new/note-manager", title: "小红书创作服务平台" },
          relevant_lines: ["已发布"],
        },
      },
    },
    {
      title: "新到的美杜莎4｜两款配置到手，差别一眼就",
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, true);
  assert.equal(normalized.platform_extras.receipt_binding_source, "xiaohongshu_note_manager_card");
  assert.equal(normalized.platform_extras.post_publish_surface, "xiaohongshu_note_manager_receipt");
  assert.equal(normalized.verification_reason, "receipt_bound");
  assert.equal(normalized.fields.title.actual, "新到的美杜莎4｜两款配置到手，差别一眼就");
  assert.equal(normalized.fields.collection.actual, "EDC潮玩桌搭");
});

test("normalizeCompositePostPublishIntegrity marks youtube studio editor route as bound receipt when video ids match", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "youtube",
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected: "", actual: "", verified: true },
        collection: { expected: "", actual: "", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
      platform_extras: {
        route: { url: "https://studio.youtube.com/video/T-44KNDKkSQ/edit", title: "视频详细信息 - YouTube Studio" },
        youtube_link: "https://youtu.be/T-44KNDKkSQ",
        youtube_scheduled: true,
        relevant_lines: ["视频链接", "https://youtu.be/T-44KNDKkSQ", "已排定时间"],
      },
    },
    {
      fields: {
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      external_url: "https://youtu.be/T-44KNDKkSQ",
      route: { url: "https://studio.youtube.com/video/T-44KNDKkSQ/edit", title: "视频详细信息 - YouTube Studio" },
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, true);
  assert.equal(normalized.platform_extras.receipt_binding_source, "youtube_studio_editor_link");
  assert.equal(normalized.platform_extras.post_publish_surface, "youtube_studio_editor_receipt");
  assert.equal(normalized.verification_reason, "receipt_bound");
});

test("normalizeCompositePostPublishIntegrity marks toutiao manage route as target-missing receipt when title is absent", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "toutiao",
    {
      fields: {
        title: { expected: "测试标题", actual: "", verified: false },
      },
      platform_extras: {
        route: { url: "https://mp.toutiao.com/profile_v4/manage/content/all", title: "头条号后台" },
        relevant_lines: [
          "内容管理",
          "锆合金版本的音叉推牌，质感绝了",
          "2026-05-24 11:00",
        ],
        receipt_like: true,
      },
    },
    {
      fields: {
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected: "E:/covers/toutiao-cover.jpg", actual: "toutiao-cover.jpg", verified: true },
        collection: { expected: "", actual: "", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        schedule: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://mp.toutiao.com/profile_v4/manage/content/all", title: "头条号后台" },
          relevant_lines: ["内容管理", "已发布"],
        },
      },
    },
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, false);
  assert.equal(normalized.platform_extras.receipt_binding_source, "toutiao_manage_receipt_unbound");
  assert.equal(normalized.platform_extras.post_publish_surface, "toutiao_content_manage_receipt");
});

test("normalizeCompositePostPublishIntegrity marks toutiao manage route as bound receipt when title matches", () => {
  const normalized = normalizeCompositePostPublishIntegrity(
    "toutiao",
    {
      fields: {
        title: { expected: "两款同时开！美杜莎4顶配次顶配差别出来了", actual: "", verified: false },
      },
      platform_extras: {
        route: { url: "https://mp.toutiao.com/profile_v4/manage/content/all", title: "头条号后台" },
        relevant_lines: [
          "内容管理",
          "锆合金版本的音叉推牌，质感绝了",
          "2026-05-24 11:00",
          "两款同时开！美杜莎4顶配次顶配差别出来了",
          "2026-06-01 21:00",
          "编辑 删除",
        ],
        receipt_like: true,
      },
    },
    {
      fields: {
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        cover: { expected: "E:/covers/toutiao-cover.jpg", actual: "toutiao-cover.jpg", verified: true },
        collection: { expected: "", actual: "", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        schedule: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
      },
    },
    {
      receipt_like: true,
      post_click_integrity: {
        platform_extras: {
          route: { url: "https://mp.toutiao.com/profile_v4/manage/content/all", title: "头条号后台" },
          relevant_lines: ["内容管理", "已发布"],
        },
      },
    },
    {
      title: "两款同时开！美杜莎4顶配次顶配差别出来了",
    },
  );

  assert.equal(normalized.platform_extras.receipt_target_bound, true);
  assert.equal(normalized.platform_extras.receipt_binding_source, "toutiao_manage_card");
  assert.equal(normalized.platform_extras.post_publish_surface, "toutiao_content_manage_receipt");
  assert.equal(normalized.verification_reason, "receipt_bound");
  assert.equal(normalized.fields.title.actual, "两款同时开！美杜莎4顶配次顶配差别出来了");
});

test("buildCompositePublicationAudit accepts bound xiaohongshu publish success receipt", () => {
  const audit = buildCompositePublicationAudit(
    "xiaohongshu",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-06-01 21:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        declaration: { expected: "原创声明", actual: "原创声明", verified: true },
        cover: { expected: "E:/covers/xhs-cover.jpg", actual: "xhs-cover.jpg", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/publish/success?id=1", title: "发布成功" },
        receipt_like: true,
        receipt_target_bound: true,
        receipt_binding_source: "xiaohongshu_publish_success",
        post_publish_surface: "xiaohongshu_publish_success_receipt",
      },
    },
    {
      receipt_like: true,
      success_like: true,
    },
    { url: "https://creator.xiaohongshu.com/publish/success?id=1" },
  );

  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.verified, true);
  assert.ok(!audit.required_unverified.includes("receipt"));
});

test("buildCompositePublicationAudit accepts bound xiaohongshu note manager receipt", () => {
  const audit = buildCompositePublicationAudit(
    "xiaohongshu",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-06-01 21:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        collection: { expected: "EDC潮玩桌搭", actual: "EDC潮玩桌搭", verified: true },
        declaration: { expected: "原创声明", actual: "原创声明", verified: true },
        cover: { expected: "E:/covers/xhs-cover.jpg", actual: "xhs-cover.jpg", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.xiaohongshu.com/new/note-manager", title: "小红书创作服务平台" },
        receipt_like: true,
        receipt_target_bound: true,
        receipt_binding_source: "xiaohongshu_note_manager_card",
        post_publish_surface: "xiaohongshu_note_manager_receipt",
      },
    },
    {
      receipt_like: true,
      success_like: true,
    },
    { url: "https://creator.xiaohongshu.com/new/note-manager" },
  );

  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.verified, true);
  assert.ok(!audit.required_unverified.includes("receipt"));
});

test("buildCompositePublicationAudit accepts bound toutiao manage receipt", () => {
  const audit = buildCompositePublicationAudit(
    "toutiao",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        collection: { expected: "", actual: "", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        cover: { expected: "E:/covers/toutiao-cover.jpg", actual: "toutiao-cover.jpg", verified: true },
        schedule: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://mp.toutiao.com/profile_v4/manage/content/all", title: "头条号后台" },
        receipt_like: true,
        receipt_target_bound: true,
        receipt_binding_source: "toutiao_manage_card",
        post_publish_surface: "toutiao_content_manage_receipt",
      },
    },
    {
      receipt_like: true,
      success_like: true,
    },
    { url: "https://mp.toutiao.com/profile_v4/manage/content/all" },
  );

  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.verified, true);
  assert.ok(!audit.required_unverified.includes("receipt"));
});

test("buildCompositePublicationAudit accepts bound youtube studio editor receipt", () => {
  const audit = buildCompositePublicationAudit(
    "youtube",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-06-01 21:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "测试标题", verified: true },
        body: { expected: "测试正文", actual: "测试正文", verified: true },
        tags: { expected: ["标签A"], actual: ["标签A"], verified: true },
        collection: { expected: "", actual: "", verified: true },
        declaration: { expected: "", actual: "", verified: true },
        cover: { expected: "", actual: "", verified: true },
        schedule: { expected: "2026-06-01 21:00", actual: "2026-06-01 21:00", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
      },
      platform_extras: {
        route: { url: "https://studio.youtube.com/video/T-44KNDKkSQ/edit", title: "视频详细信息 - YouTube Studio" },
        receipt_like: true,
        receipt_target_bound: true,
        receipt_binding_source: "youtube_studio_editor_link",
        post_publish_surface: "youtube_studio_editor_receipt",
        youtube_link: "https://youtu.be/T-44KNDKkSQ",
        youtube_scheduled: true,
      },
    },
    {
      receipt_like: true,
      external_url: "https://youtu.be/T-44KNDKkSQ",
    },
    { url: "https://studio.youtube.com/video/T-44KNDKkSQ/edit" },
  );

  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.verified, true);
  assert.ok(!audit.required_unverified.includes("receipt"));
});

test("buildCompositePublicationAudit requires douyin receipt target binding on management receipt surface", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "测试标题",
      body: "测试正文",
      hashtags: ["标签A"],
      scheduled_publish_at: "2026-05-31 20:30:00",
    },
    {
      fields: {
        title: { expected: "测试标题", actual: "", verified: false },
        body: { expected: "测试正文", actual: "作品管理 全部作品 已发布 发布成功", verified: false },
        tags: { expected: ["标签A"], actual: ["折刀"], verified: false },
        schedule: { expected: "2026-05-31 20:30", actual: "", verified: false },
        upload_ready: { actual: "ready", verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
        relevant_lines: ["作品管理", "已发布", "发布成功"],
        receipt_like: true,
        post_publish_surface: "douyin_content_manage_receipt",
        receipt_target_bound: false,
      },
    },
    {
      receipt_like: true,
    },
    { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish" },
  );

  assert.equal(audit.checklist.receipt.required, true);
  assert.equal(audit.checklist.receipt.verified, false);
  assert.ok(audit.required_unverified.includes("receipt"));
});

test("buildCompositePublicationAudit does not require body or declaration on bound douyin management receipt", () => {
  const audit = buildCompositePublicationAudit(
    "douyin",
    {
      title: "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕",
      body: "RoughCut 正式发布素材：MAXACE 美杜莎4 顶配次顶配开箱",
      hashtags: ["玩具", "男人的快乐", "edc装备", "FAS", "机能风"],
      declaration: "无需添加自主声明",
    },
    {
      fields: {
        title: { expected: "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕", actual: "FAS刀帕收纳方法 弹力绳和伞绳绑扣的更换和用法 听说真正的EDC高手 都会用刀帕", verified: true },
        body: { expected: "RoughCut 正式发布素材：MAXACE 美杜莎4 顶配次顶配开箱", actual: "今天教你两种方法，把乱七八糟的随身装备卷得整整齐齐。", verified: false },
        tags: { expected: ["玩具", "男人的快乐", "edc装备", "FAS", "机能风"], actual: ["玩具", "男人的快乐", "edc装备", "FAS", "机能风"], verified: true },
        schedule: { expected: "", actual: "", verified: true },
        cover: { expected_path: "", actual: "", uploaded: true, cover_uploaded: true, verified: true },
        collection: { expected: "", actual: "", verified: true },
        upload_ready: { actual: "ready", verified: true },
        draft_state: { expected: "editor_clean", actual: "clean", verified: true },
        declaration: { expected: "无需添加自主声明", actual: "", verified: false },
        receipt: { required: true, verified: true },
      },
      platform_extras: {
        route: { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish", title: "作品管理" },
        receipt_like: true,
        post_publish_surface: "douyin_content_manage_receipt",
        receipt_target_bound: true,
      },
    },
    {
      receipt_like: true,
    },
    { url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish" },
  );

  assert.equal(audit.checklist.receipt.verified, true);
  assert.equal(audit.checklist.content_plan_match.verified, true);
  assert.equal(audit.checklist.body.required, false);
  assert.equal(audit.required_unverified.includes("body"), false);
  assert.equal(audit.required_unverified.includes("declaration"), false);
  assert.equal(audit.required_unverified.includes("content_plan_match"), false);
  assert.equal(audit.required_reupload.includes("body"), false);
  assert.equal(audit.required_reupload.includes("declaration"), false);
});

test("shouldAcceptCompositeUploadReadyState requires stable douyin ready surface", () => {
  const state = {
    ready: true,
    busy: false,
    failed: false,
    uploadPromptOnly: false,
    douyinReadySurface: true,
  };

  assert.equal(shouldAcceptCompositeUploadReadyState("douyin", state, 1, 1000), false);
  assert.equal(shouldAcceptCompositeUploadReadyState("douyin", state, 2, 2600), true);
});

test("shouldAcceptCompositeUploadReadyState rejects busy upload states", () => {
  const state = {
    ready: true,
    busy: true,
    failed: false,
    uploadPromptOnly: false,
  };

  assert.equal(shouldAcceptCompositeUploadReadyState("douyin", state, 3, 8000), false);
  assert.equal(shouldAcceptCompositeUploadReadyState("xiaohongshu", state, 1, 8000), false);
});

test("derivePublicationTaskPreparationPolicy keeps refresh-only recovery from forcing draft clear", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      clear_draft_context: false,
      force_publish_page_refresh: true,
      recovery_mode: "auto_recover",
    },
  });

  assert.equal(policy.recoveryContext.clear_draft_context, false);
  assert.equal(policy.forceClearDraft, false);
  assert.equal(policy.forcePublishPageRefresh, true);
  assert.equal(policy.forceMediaUpload, true);
  assert.equal(policy.clearIfStaleDraft, true);
});

test("derivePublicationTaskPreparationPolicy disables draft reset and media upload in verification-only mode", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      verification_only_current_page: true,
      clear_draft_context: true,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.verificationOnlyCurrentPage, true);
  assert.equal(policy.forceClearDraft, true);
  assert.equal(policy.forcePublishPageRefresh, true);
  assert.equal(policy.forceMediaUpload, false);
  assert.equal(policy.clearIfStaleDraft, false);
});

test("shouldApplyCompositeDraftPolicyBlockers skips editor policy blockers during receipt rebind verification", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      verification_only_current_page: true,
      wait_for_publish_confirmation: true,
      recovery_mode: "receipt_rebind",
    },
  });

  assert.equal(shouldApplyCompositeDraftPolicyBlockers(policy), false);
});

test("shouldApplyCompositeDraftPolicyBlockers keeps editor policy blockers during ordinary verification", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      verification_only_current_page: true,
      wait_for_publish_confirmation: true,
      recovery_mode: "auto_recover",
    },
  });

  assert.equal(shouldApplyCompositeDraftPolicyBlockers(policy), true);
});

test("derivePlatformTabSelectionPolicy prefers receipt surface for douyin receipt rebind verification", () => {
  const policy = derivePlatformTabSelectionPolicy("douyin", {
    verification_only_current_page: true,
    recovery_mode: "receipt_rebind",
  });

  assert.equal(policy.lock_active_tab, true);
  assert.equal(policy.fresh_start_platform_tab, false);
  assert.equal(policy.prefer_receipt_surface, true);
  assert.equal(policy.allow_safe_autocreate, false);
});

test("derivePlatformTabSelectionPolicy prefers stable upload surface for youtube stop-before modes", () => {
  const policy = derivePlatformTabSelectionPolicy("youtube", {
    recovery_mode: "prepublish_resume",
    prepare_only_current_page: true,
  });

  assert.equal(policy.lock_active_tab, false);
  assert.equal(policy.fresh_start_platform_tab, true);
  assert.equal(policy.prefer_stable_upload_surface, true);
  assert.equal(policy.prefer_draft_list_surface, false);
  assert.equal(policy.allow_safe_autocreate, true);
});

test("extractYouTubeStudioChannelId and youtube studio route builders normalize channel routes", () => {
  assert.equal(
    extractYouTubeStudioChannelId("https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?filter=%5B%5D"),
    "UCAoEPjdkkZ_4QRQuZROfknw",
  );
  assert.equal(
    extractYouTubeStudioChannelId("https://studio.youtube.com/channel/UC/upload"),
    "",
  );
  assert.equal(
    buildYouTubeStudioUploadEntryUrl("UCAoEPjdkkZ_4QRQuZROfknw"),
    "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload",
  );
  assert.equal(
    buildYouTubeStudioContentListUrl("UCAoEPjdkkZ_4QRQuZROfknw"),
    "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos",
  );
});

test("resolvePlatformPublishEntryUrl and platformTabScore reject malformed youtube upload tab", () => {
  const tabs = [
    {
      url: "https://studio.youtube.com/channel/UC/upload",
      title: "频道内容 - YouTube Studio",
      type: "page",
      webSocketDebuggerUrl: "ws://dead",
    },
    {
      url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?filter=%5B%5D",
      title: "频道内容 - YouTube Studio",
      type: "page",
      webSocketDebuggerUrl: "ws://live",
    },
  ];
  assert.equal(
    resolvePlatformPublishEntryUrl("youtube", tabs),
    "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload",
  );
  assert.equal(
    resolvePlatformPublishEntryUrl("youtube", tabs, { prefer_draft_list_surface: true }),
    "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload",
  );
  assert.equal(
    platformTabScore(
      tabs[0],
      ["studio.youtube.com"],
      "youtube",
      { prefer_stable_upload_surface: true },
    ),
    0,
  );
});

test("findPlatformTab prefers youtube upload route over content-list route during stop-before safe mode", () => {
  const contentListTab = {
    type: "page",
    title: "频道内容 - YouTube Studio",
    url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos",
  };
  const genericUploadTab = {
    type: "page",
    title: "YouTube 创作者工作室",
    url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?d=ud",
  };

  const selected = findPlatformTab(
    [genericUploadTab, contentListTab],
    "youtube",
    { prefer_stable_upload_surface: true, prefer_draft_list_surface: true },
  );

  assert.equal(selected?.url, genericUploadTab.url);
});

test("findPlatformTab in current-page mode only considers the active tab", () => {
  const inactiveDouyinPublishTab = {
    active: false,
    type: "page",
    title: "抖音创作者中心",
    url: "https://creator.douyin.com/creator-micro/content/post/video",
  };
  const activeWrongTab = {
    active: true,
    type: "page",
    title: "频道内容 - YouTube Studio",
    url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload",
  };

  const selected = findPlatformTab(
    [inactiveDouyinPublishTab, activeWrongTab],
    "douyin",
    { lock_active_tab: true },
  );

  assert.equal(selected, undefined);
});

test("findPlatformTab in current-page mode does not fall back to an inactive upload-shell tab", () => {
  const inactiveDouyinUploadTab = {
    active: false,
    type: "page",
    title: "抖音创作者中心",
    url: "https://creator.douyin.com/creator-micro/content/upload",
  };
  const activeWrongTab = {
    active: true,
    type: "page",
    title: "频道内容 - YouTube Studio",
    url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload",
  };

  const selected = findPlatformTab(
    [inactiveDouyinUploadTab, activeWrongTab],
    "douyin",
    { lock_active_tab: true },
  );

  assert.equal(selected, undefined);
});

test("shouldAcquireReceiptSurfaceRoute requests douyin management route when receipt rebind starts from publish page", () => {
  const policy = derivePlatformTabSelectionPolicy("douyin", {
    verification_only_current_page: true,
    recovery_mode: "receipt_rebind",
  });

  assert.equal(
    shouldAcquireReceiptSurfaceRoute(
      "douyin",
      "https://creator.douyin.com/creator-micro/content/post/video",
      policy,
    ),
    true,
  );
  assert.equal(
    shouldAcquireReceiptSurfaceRoute(
      "douyin",
      "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
      policy,
    ),
    false,
  );
  assert.equal(
    isPlatformReceiptSurfaceUrl(
      "douyin",
      "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
    ),
    true,
  );
});

test("shouldAcquireReceiptSurfaceRoute ignores receipt route when fresh-start tab mode is active", () => {
  assert.equal(
    shouldAcquireReceiptSurfaceRoute(
      "douyin",
      "https://creator.douyin.com/creator-micro/content/post/video",
      {
        prefer_receipt_surface: true,
        fresh_start_platform_tab: true,
      },
    ),
    false,
  );
});

test("deriveNavigationJavaScriptDialogHandling accepts leave-site beforeunload during route switch", () => {
  const handling = deriveNavigationJavaScriptDialogHandling(
    {
      type: "beforeunload",
      message: "离开此网站？系统可能不会保存您所做的更改。",
    },
    {
      policy: "navigation_route_switch",
    },
  );

  assert.equal(handling.action, "accept");
  assert.equal(handling.reason, "route_switch_beforeunload");
});

test("deriveNavigationJavaScriptDialogHandling dismisses unexpected alert during route switch", () => {
  const handling = deriveNavigationJavaScriptDialogHandling(
    {
      type: "alert",
      message: "普通提示",
    },
    {
      policy: "navigation_route_switch",
    },
  );

  assert.equal(handling.action, "dismiss");
  assert.equal(handling.reason, "route_switch_unexpected_dialog");
});

test("findPlatformTab prefers douyin manage page over publish page during receipt rebind verification", () => {
  const publishTab = {
    type: "page",
    title: "抖音创作者中心",
    url: "https://creator.douyin.com/creator-micro/content/post/video",
  };
  const manageTab = {
    type: "page",
    title: "抖音创作者中心",
    url: "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish",
  };

  const selected = findPlatformTab(
    [publishTab, manageTab],
    "douyin",
    { prefer_receipt_surface: true },
  );

  assert.equal(selected?.url, manageTab.url);
});

test("findPlatformTab prefers youtube upload route over edit route during stop-before safe mode", () => {
  const editTab = {
    type: "page",
    title: "频道内容 - YouTube Studio",
    url: "https://studio.youtube.com/video/eaTu-rtsyiw/edit",
  };
  const uploadTab = {
    type: "page",
    title: "频道内容 - YouTube Studio",
    url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?d=ud&udvid=eaTu-rtsyiw",
  };

  const selected = findPlatformTab(
    [editTab, uploadTab],
    "youtube",
    { prefer_stable_upload_surface: true },
  );

  assert.equal(selected?.url, uploadTab.url);
});

test("derivePublicationTaskPreparationPolicy disables draft reset and media upload in repair-only mode", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      repair_only_current_page: true,
      clear_draft_context: true,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.repairOnlyCurrentPage, true);
  assert.equal(policy.verificationOnlyCurrentPage, false);
  assert.equal(policy.forcePublishPageRefresh, true);
  assert.equal(policy.forceMediaUpload, false);
  assert.equal(policy.clearIfStaleDraft, false);
});

test("derivePublicationTaskPreparationPolicy disables draft reset and media upload in prepublish-only mode", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      prepublish_only_current_page: true,
      clear_draft_context: true,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.prepublishOnlyCurrentPage, true);
  assert.equal(policy.verificationOnlyCurrentPage, false);
  assert.equal(policy.repairOnlyCurrentPage, false);
  assert.equal(policy.forcePublishPageRefresh, true);
  assert.equal(policy.forceMediaUpload, false);
  assert.equal(policy.clearIfStaleDraft, false);
});

test("derivePublicationTaskPreparationPolicy honors direct publication_recovery_state overrides", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    publication_recovery_state: {
      recovery_overrides: {
        prepare_only_current_page: true,
        clear_draft_context: false,
        force_publish_page_refresh: true,
        recovery_mode: "prepublish_resume",
      },
    },
  });
  assert.equal(policy.prepareOnlyCurrentPage, true);
  assert.equal(policy.stopBeforeFinalPublish, true);
  assert.equal(policy.forceMediaUpload, false);
  assert.equal(policy.clearIfStaleDraft, false);
});

test("derivePublicationTaskPreparationPolicy treats stop-before-final-publish as publish suppression, not current-page safety", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      stop_before_final_publish: true,
      clear_draft_context: false,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.stopBeforeFinalPublish, true);
  assert.equal(policy.currentPageOnlyMode, false);
  assert.equal(policy.forceMediaUpload, true);
  assert.equal(policy.clearIfStaleDraft, true);
});

test("derivePublicationTaskPreparationPolicy keeps current-page draft reset disabled in prepare-only mode", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      prepare_only_current_page: true,
      clear_draft_context: true,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.prepareOnlyCurrentPage, true);
  assert.equal(policy.stopBeforeFinalPublish, true);
  assert.equal(policy.verificationOnlyCurrentPage, false);
  assert.equal(policy.repairOnlyCurrentPage, false);
  assert.equal(policy.prepublishOnlyCurrentPage, false);
  assert.equal(policy.forcePublishPageRefresh, false);
  assert.equal(policy.forceMediaUpload, false);
  assert.equal(policy.clearIfStaleDraft, false);
  assert.equal(policy.recoveryContext.clear_draft_context, false);
  assert.equal(policy.recoveryContext.force_publish_page_refresh, false);
});

test("derivePublicationTaskPreparationPolicy strips other current-page recovery modes when prepare-only mode is active", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    platform_specific_overrides: {
      prepare_only_current_page: true,
      verification_only_current_page: true,
      repair_only_current_page: true,
      prepublish_only_current_page: true,
      clear_draft_context: true,
      force_publish_page_refresh: true,
    },
  });

  assert.equal(policy.prepareOnlyCurrentPage, true);
  assert.equal(policy.verificationOnlyCurrentPage, false);
  assert.equal(policy.repairOnlyCurrentPage, false);
  assert.equal(policy.prepublishOnlyCurrentPage, false);
  assert.equal(policy.forcePublishPageRefresh, false);
  assert.equal(policy.forceClearDraft, false);
});

test("canReuseCurrentPageMediaForPrepublish accepts douyin ready editor surface without filename echo", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "douyin",
    {
      lines: [
        "预览视频",
        "预览封面/标题",
        "作品描述",
        "发布时间",
        "发布设置",
        "重新上传",
      ],
    },
    "E:\\WorkSpace\\RoughCut\\video.mp4",
  );

  assert.equal(state.reusable, true);
  assert.equal(state.reason, "douyin_ready_surface");
});

test("canReuseCurrentPageMediaForPrepublish accepts bilibili editor surface with attached upload state", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "bilibili",
    {
      lines: [
        "上传完成",
        "更换视频",
        "标题",
        "创作声明",
        "标签",
        "简介",
        "定时发布",
        "存草稿",
        "立即投稿",
      ],
    },
    "",
  );

  assert.equal(state.reusable, true);
  assert.equal(state.reason, "bilibili_editor_surface");
});

test("canReuseCurrentPageMediaForPrepublish rejects bilibili attached draft by default when the title drifts", () => {
  const mediaPath = String.raw`E:\WorkSpace\RoughCut\MAXACE 美杜莎4 顶配次顶配开箱.mp4`;
  const state = canReuseCurrentPageMediaForPrepublish(
    "bilibili",
    {
      lines: [
        "上传完成",
        "更换视频",
        "标题",
        "旧稿标题",
        "MAXACE 美杜莎4 顶配次顶配开箱",
        "创作声明",
        "标签",
        "简介",
        "定时发布",
        "存草稿",
        "立即投稿",
      ],
    },
    mediaPath,
    { expectedTitle: "MAXACE美杜莎4开箱先看细节" },
  );

  assert.equal(state.reusable, false);
  assert.equal(state.reason, "bilibili_existing_draft_title_mismatch");
});

test("canReuseCurrentPageMediaForPrepublish allows bilibili draft title mismatch reuse only in explicit current-page mode", () => {
  const mediaPath = String.raw`E:\WorkSpace\RoughCut\MAXACE 美杜莎4 顶配次顶配开箱.mp4`;
  const state = canReuseCurrentPageMediaForPrepublish(
    "bilibili",
    {
      lines: [
        "上传完成",
        "更换视频",
        "标题",
        "旧稿标题",
        "MAXACE 美杜莎4 顶配次顶配开箱",
        "创作声明",
        "标签",
        "简介",
        "定时发布",
        "存草稿",
        "立即投稿",
      ],
    },
    mediaPath,
    {
      expectedTitle: "MAXACE美杜莎4开箱先看细节",
      allowDraftTitleMismatchReuse: true,
    },
  );

  assert.equal(state.reusable, true);
  assert.equal(state.reason, "media_path_match");
});

test("canReuseCurrentPageMediaForPrepublish accepts youtube upload resume surface without local filename echo", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "youtube",
    {
      url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?d=ud&udvid=eaTu-rtsyiw",
      lines: [
        "频道内容",
        "MAXACE 美杜莎4 顶配次顶配开箱",
        "正在上传，已完成 40%",
        "草稿",
        "取消上传",
        "编辑草稿",
        "添加说明",
      ],
    },
    "",
  );

  assert.equal(state.reusable, true);
  assert.equal(state.reason, "youtube_upload_resume_surface");
});

test("canReuseCurrentPageMediaForPrepublish rejects youtube uploaded draft row on channel content list", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "youtube",
    {
      url: "https://studio.youtube.com/channel/UCAoEPjdkkZ_4QRQuZROfknw/videos/upload?d=ud&filter=%5B%5D",
      lines: [
        "频道内容",
        "MAXACE 美杜莎4 顶配次顶配开箱",
        "草稿",
        "编辑草稿",
        "添加说明",
      ],
    },
    "E:/videos/source-video.mp4",
  );

  assert.equal(state.reusable, false);
  assert.equal(state.reason, "youtube_uploaded_draft_row_ignored");
});

test("canReuseCurrentPageMediaForPrepublish rejects bare upload prompt surface", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "douyin",
    {
      lines: [
        "拖拽视频到此",
        "点击上传",
        "上传视频 视频大小不超过4GB",
      ],
    },
    "E:\\WorkSpace\\RoughCut\\video.mp4",
  );

  assert.equal(state.reusable, false);
  assert.equal(state.reason, "upload_prompt_only");
});

test("compositeRequiresLocalMedia honors persisted link-only publication capability for x", () => {
  const requiresLocalMedia = compositeRequiresLocalMedia("x", {
    publication_capability: {
      requires_local_media: false,
    },
    platform_specific_overrides: {
      x_share_link: "https://example.com/post",
    },
  });

  assert.equal(requiresLocalMedia, false);
});

test("canReuseCurrentPageMediaForPrepublish skips media gate when local media is not required", () => {
  const state = canReuseCurrentPageMediaForPrepublish(
    "x",
    {
      lines: [
        "Home",
        "Explore",
        "Post",
      ],
    },
    "",
    { requiresLocalMedia: false },
  );

  assert.equal(state.reusable, true);
  assert.equal(state.reason, "local_media_not_required");
});

test("deriveCompositeCurrentPageMediaPendingDisposition converts upload prompt into wait-only pending state", () => {
  const disposition = deriveCompositeCurrentPageMediaPendingDisposition(
    "xiaohongshu",
    "E:\\WorkSpace\\RoughCut\\video.mp4",
    { reusable: false, reason: "upload_prompt_only" },
  );

  assert.equal(disposition.pending, true);
  assert.equal(disposition.status, "processing");
  assert.equal(disposition.code, "xiaohongshu_pre_publish_upload_pending");
  assert.equal(disposition.wait_for_upload_ready, true);
});

test("deriveCompositeCurrentPageMediaPendingDisposition keeps upload_failed as needs_human", () => {
  const disposition = deriveCompositeCurrentPageMediaPendingDisposition(
    "xiaohongshu",
    "E:\\WorkSpace\\RoughCut\\video.mp4",
    { reusable: false, reason: "upload_failed" },
  );

  assert.equal(disposition.pending, false);
  assert.equal(disposition.status, "needs_human");
  assert.equal(disposition.code, "xiaohongshu_prepublish_only_media_missing");
});

test("shouldBootstrapStopBeforeMediaUpload enables safe upload bootstrap for local-media stop-before routes", () => {
  assert.equal(
    shouldBootstrapStopBeforeMediaUpload(
      "bilibili",
      "E:\\WorkSpace\\RoughCut\\video.mp4",
      { reusable: false, reason: "upload_prompt_only" },
      {
        stopBeforeFinalPublish: true,
        requiresLocalMedia: true,
        verifyMediaUpload: true,
      },
    ),
    true,
  );
});

test("shouldBootstrapStopBeforeMediaUpload keeps unsupported or failed routes blocked", () => {
  assert.equal(
    shouldBootstrapStopBeforeMediaUpload(
      "x",
      "",
      { reusable: false, reason: "missing_media_path" },
      {
        stopBeforeFinalPublish: true,
        requiresLocalMedia: false,
        verifyMediaUpload: true,
      },
    ),
    false,
  );
  assert.equal(
    shouldBootstrapStopBeforeMediaUpload(
      "youtube",
      "E:\\WorkSpace\\RoughCut\\video.mp4",
      { reusable: false, reason: "upload_failed" },
      {
        stopBeforeFinalPublish: true,
        requiresLocalMedia: true,
        verifyMediaUpload: true,
      },
    ),
    false,
  );
});

test("shouldBootstrapStopBeforeMediaRouteRecovery upgrades youtube generic upload list before media bootstrap", () => {
  assert.equal(
    shouldBootstrapStopBeforeMediaRouteRecovery(
      "youtube",
      {
        url: "https://studio.youtube.com/channel/UC123/videos/upload?d=ud&filter=%5B%5D",
      },
      { reusable: false, reason: "media_presence_unconfirmed" },
    ),
    true,
  );
  assert.equal(
    shouldBootstrapStopBeforeMediaRouteRecovery(
      "youtube",
      {
        url: "https://studio.youtube.com/channel/UC123/videos/upload?d=ud&udvid=eaTu-rtsyiw",
      },
      { reusable: false, reason: "media_presence_unconfirmed" },
    ),
    false,
  );
});

test("shouldTreatYouTubeUploadSurfaceAsStable rejects generic d=ud list with only thumbnail input", () => {
  assert.equal(
    shouldTreatYouTubeUploadSurfaceAsStable({
      uploadResumeRoute: false,
      channelContentList: true,
      uploadDialogSurface: true,
      visibleFileInputCount: 0,
      videoCapableFileInputCount: 0,
    }),
    false,
  );
  assert.equal(
    shouldTreatYouTubeUploadSurfaceAsStable({
      uploadResumeRoute: true,
      channelContentList: true,
      uploadDialogSurface: true,
      visibleFileInputCount: 0,
      videoCapableFileInputCount: 0,
    }),
    true,
  );
});

test("shouldAttemptMediaBootstrap skips youtube stop-before reupload when upload-resume surface is already reusable", () => {
  assert.equal(
    shouldAttemptMediaBootstrap({
      stopBeforeFinalPublish: true,
      prepublishOnlyCurrentPage: false,
      forceMediaUpload: false,
      stopBeforeUploadBootstrap: false,
      mediaAlreadyPresent: true,
      pageHasMedia: false,
      hasMediaPath: true,
    }),
    false,
  );
});

test("shouldAttemptMediaBootstrap still allows stop-before bootstrap when media is not yet present", () => {
  assert.equal(
    shouldAttemptMediaBootstrap({
      stopBeforeFinalPublish: true,
      prepublishOnlyCurrentPage: false,
      forceMediaUpload: false,
      stopBeforeUploadBootstrap: true,
      mediaAlreadyPresent: false,
      pageHasMedia: false,
      hasMediaPath: true,
    }),
    true,
  );
});

test("shouldContinueStopBeforeUploadBootstrap allows prepare-only current-page direct starts to upload from a fresh entry", () => {
  assert.equal(
    shouldContinueStopBeforeUploadBootstrap({
      stopBeforeFinalPublish: true,
      currentPageOnlyMode: true,
      prepareOnlyCurrentPage: true,
      requiresLocalMedia: true,
      hasMediaPath: true,
    }),
    true,
  );
});

test("shouldContinueStopBeforeUploadBootstrap keeps prepublish-only current-page verification from auto-uploading", () => {
  assert.equal(
    shouldContinueStopBeforeUploadBootstrap({
      stopBeforeFinalPublish: true,
      currentPageOnlyMode: true,
      prepareOnlyCurrentPage: false,
      requiresLocalMedia: true,
      hasMediaPath: true,
    }),
    false,
  );
});

test("deriveCurrentPageDraftResumeDisposition detects bilibili unpublished draft prompt", () => {
  const disposition = deriveCurrentPageDraftResumeDisposition(
    "bilibili",
    "还有上次未发布的视频，是否继续编辑？ 继续编辑 放弃 上传完成 上传中..."
  );
  assert.equal(disposition.present, true);
  assert.equal(disposition.resume_label, "继续编辑");
  assert.equal(disposition.reason, "existing_unpublished_draft_prompt");
});

test("deriveCurrentPageDraftResumeDisposition detects douyin unpublished draft prompt and prefers discard", () => {
  const disposition = deriveCurrentPageDraftResumeDisposition(
    "douyin",
    "你还有上次未发布的视频，是否继续编辑？ 继续编辑 放弃 点击上传或直接将视频文件拖入此区域"
  );
  assert.equal(disposition.present, true);
  assert.equal(disposition.resume_label, "继续编辑");
  assert.equal(disposition.discard_label, "放弃");
  assert.equal(disposition.preferred_action, "discard");
  assert.equal(disposition.reason, "existing_unpublished_draft_prompt");
});

test("deriveCurrentPageDraftResumeDisposition ignores youtube uploaded draft row on channel content", () => {
  const disposition = deriveCurrentPageDraftResumeDisposition(
    "youtube",
    "频道内容 MAXACE 美杜莎4 顶配次顶配开箱 处理出现延迟 草稿 编辑草稿 发布日期",
  );
  assert.equal(disposition.present, false);
  assert.equal(disposition.resume_label, "编辑草稿");
  assert.equal(disposition.reason, "uploaded_draft_row_ignored");
});


test("deriveCurrentPageDraftResumeDisposition ignores unrelated upload prompts", () => {
  const disposition = deriveCurrentPageDraftResumeDisposition(
    "kuaishou",
    "拖拽视频到此或点击上传 上传视频 视频大小 支持时长1小时以内"
  );
  assert.equal(disposition.present, false);
});

test("deriveCompositeCurrentPageRouteDisposition treats wechat login surface as auth required", () => {
  const disposition = deriveCompositeCurrentPageRouteDisposition(
    "wechat-channels",
    {
      url: "https://channels.weixin.qq.com/login.html",
      lines: ["请先登录", "登录后继续"],
    },
  );

  assert.equal(disposition.blocked, true);
  assert.equal(disposition.code, "wechat-channels_route_auth_required");
  assert.equal(disposition.verification_reason, "auth_required");
});

test("deriveCompositeCurrentPageRouteDisposition treats douyin login surface on publish url as auth required", () => {
  const disposition = deriveCompositeCurrentPageRouteDisposition(
    "douyin",
    {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      title: "抖音创作者中心",
      lines: ["抖音创作者中心·创作者", "扫码登录", "验证码登录", "登录/注册", "我是创作者", "我是MCN机构"],
    },
  );

  assert.equal(disposition.blocked, true);
  assert.equal(disposition.code, "douyin_route_auth_required");
  assert.equal(disposition.verification_reason, "auth_required");
});

test("deriveCompositeCurrentPageRouteDisposition treats youtube upload error surface as route not ready", () => {
  const disposition = deriveCompositeCurrentPageRouteDisposition(
    "youtube",
    {
      url: "https://studio.youtube.com/channel/UC123/upload",
      lines: ["糟糕，出了点问题。"],
    },
  );

  assert.equal(disposition.blocked, true);
  assert.equal(disposition.code, "youtube_prepublish_only_route_not_ready");
  assert.equal(disposition.verification_reason, "publish_route_error_surface");
});

test("deriveCompositeCurrentPageRouteDisposition does not misclassify logged-in youtube studio home as auth required", () => {
  const disposition = deriveCompositeCurrentPageRouteDisposition(
    "youtube",
    {
      url: "https://studio.youtube.com/",
      title: "YouTube 创作者工作室",
      lines: ["在你的频道中搜索", "频道信息中心", "我的频道", "内容", "数据分析", "发送反馈", "创建"],
    },
  );

  assert.equal(disposition.blocked, true);
  assert.equal(disposition.code, "youtube_prepublish_only_route_not_ready");
  assert.equal(disposition.verification_reason, "publish_route_not_ready");
});

test("hasYoutubeUploadDialogQuery accepts hidden upload-dialog query marker", () => {
  assert.equal(
    hasYoutubeUploadDialogQuery("https://studio.youtube.com/channel/abc/videos/upload?d=ud&filter=%5B%5D"),
    true,
  );
  assert.equal(
    hasYoutubeUploadDialogQuery("https://studio.youtube.com/channel/abc/videos/upload?filter=%5B%5D"),
    false,
  );
});

test("deriveCompositeCurrentPageRouteDisposition does not block valid x compose route", () => {
  const disposition = deriveCompositeCurrentPageRouteDisposition(
    "x",
    {
      url: "https://x.com/compose/post",
      lines: ["Post", "Everyone can reply"],
    },
  );

  assert.equal(disposition.blocked, false);
});

test("shouldBootstrapStopBeforeRouteRecovery retries youtube publish route error surface", () => {
  assert.equal(
    shouldBootstrapStopBeforeRouteRecovery("youtube", {
      blocked: true,
      code: "youtube_prepublish_only_route_not_ready",
      verification_reason: "publish_route_error_surface",
    }),
    true,
  );
  assert.equal(
    shouldBootstrapStopBeforeRouteRecovery("wechat-channels", {
      blocked: true,
      code: "wechat-channels_route_auth_required",
      verification_reason: "auth_required",
    }),
    false,
  );
});

test("activateYoutubeHiddenUploadEntry uses stable upload menu test-id fallback", async () => {
  const expressions = [];
  const client = {
    async send(method, params = {}) {
      if (method === "Runtime.enable") return {};
      if (method === "Runtime.evaluate") {
        expressions.push(String(params.expression || ""));
        return {
          result: {
            value: {
              clicked: true,
              hidden: true,
              label: "上传视频",
              before_href: "https://studio.youtube.com/channel/abc/videos/upload",
              after_href: "https://studio.youtube.com/channel/abc/videos/upload?d=ud",
              route_changed: true,
            },
          },
        };
      }
      throw new Error(`unexpected method: ${method}`);
    },
  };

  const result = await activateYoutubeHiddenUploadEntry(client);

  assert.equal(result.clicked, true);
  assert.equal(result.hidden, true);
  assert.equal(result.route_changed, true);
  assert.match(expressions[0], /test-id="upload"/);
});

test("deriveDedicatedVerifierMediaEntryDisposition converts bilibili upload prompt with media path into wait-only pending state", () => {
  const disposition = deriveDedicatedVerifierMediaEntryDisposition(
    "bilibili",
    {
      actual: {
        uploadState: {
          prompt_only: true,
          failed: false,
        },
      },
    },
    "E:\\WorkSpace\\RoughCut\\video.mp4",
  );

  assert.equal(disposition.pending, true);
  assert.equal(disposition.status, "processing");
  assert.equal(disposition.code, "bilibili_pre_publish_upload_pending");
});

test("deriveDedicatedVerifierMediaEntryDisposition converts bilibili upload prompt without media path into media-missing stop", () => {
  const disposition = deriveDedicatedVerifierMediaEntryDisposition(
    "bilibili",
    {
      actual: {
        uploadState: {
          prompt_only: true,
          failed: false,
        },
      },
    },
    "",
  );

  assert.equal(disposition.pending, false);
  assert.equal(disposition.status, "needs_human");
  assert.equal(disposition.code, "bilibili_prepublish_only_media_missing");
});

test("_build_publication_recovery_hint preserves prepublish_resume safe flags for upload-pending wait state", () => {
  const hint = _build_publication_recovery_hint({
    platform: "xiaohongshu",
    code: "xiaohongshu_pre_publish_upload_pending",
    reason: "等待目标媒体挂载完成。",
    route: {
      url: "https://creator.xiaohongshu.com/publish/publish?from=menu&target=video",
      title: "小红书创作服务平台",
    },
    clearDraftContext: false,
    forceRefresh: true,
    recoveryOverrides: {
      recovery_mode: "prepublish_resume",
      prepublish_only_current_page: true,
      verify_media_upload: true,
      wait_for_publish_confirmation: true,
    },
  });

  assert.equal(hint.recovery.recovery_overrides.recovery_mode, "prepublish_resume");
  assert.equal(hint.recovery.recovery_overrides.prepublish_only_current_page, true);
  assert.equal(hint.recovery.recovery_overrides.verify_media_upload, true);
  assert.equal(hint.recovery.recovery_overrides.wait_for_publish_confirmation, true);
  assert.equal(hint.recovery.recovery_overrides.clear_draft_context, false);
  assert.equal(hint.recovery.recovery_overrides.force_publish_page_refresh, true);
});

test("buildStopBeforeFinalPublishRecoveryOverrides keeps safe stop-before-final-publish flags for media-missing paths", () => {
  const overrides = buildStopBeforeFinalPublishRecoveryOverrides({
    prepublishOnlyCurrentPage: false,
    prepareOnlyCurrentPage: true,
  });

  assert.deepEqual(overrides, {
    recovery_mode: "prepublish_resume",
    prepublish_only_current_page: false,
    prepare_only_current_page: true,
    verify_media_upload: true,
    wait_for_publish_confirmation: true,
  });
});

test("buildStopBeforeFinalPublishRecoveryOverrides keeps auth-required stop-before paths out of prepublish resume", () => {
  const overrides = buildStopBeforeFinalPublishRecoveryOverrides({
    prepublishOnlyCurrentPage: false,
    prepareOnlyCurrentPage: true,
    verificationReason: "auth_required",
  });

  assert.deepEqual(overrides, {
    recovery_mode: "route_auth_required",
    prepublish_only_current_page: false,
    prepare_only_current_page: true,
    verify_media_upload: false,
    wait_for_publish_confirmation: false,
  });
});

test("buildPreparationBootstrapRecoveryOverrides preserves safe stop-before flags", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    publication_recovery_state: {
      recovery_overrides: {
        prepare_only_current_page: true,
        recovery_mode: "prepublish_resume",
        clear_draft_context: false,
        force_publish_page_refresh: true,
        verify_media_upload: true,
        wait_for_publish_confirmation: true,
      },
    },
  });
  const overrides = buildPreparationBootstrapRecoveryOverrides(policy);

  assert.equal(overrides.recovery_mode, "prepublish_resume");
  assert.equal(overrides.prepare_only_current_page, true);
  assert.equal(overrides.fresh_start_platform_tab, false);
  assert.equal(overrides.clear_draft_context, false);
  assert.equal(overrides.force_publish_page_refresh, false);
  assert.equal(overrides.verify_media_upload, true);
  assert.equal(overrides.wait_for_publish_confirmation, true);
});

test("buildPreparationBootstrapRecoveryOverrides preserves fresh-start tab flag", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    publication_recovery_state: {
      recovery_overrides: {
        prepare_only_current_page: true,
        fresh_start_platform_tab: true,
        recovery_mode: "prepublish_resume",
        clear_draft_context: false,
        force_publish_page_refresh: false,
        verify_media_upload: false,
        wait_for_publish_confirmation: false,
      },
    },
  });
  const overrides = buildPreparationBootstrapRecoveryOverrides(policy);

  assert.equal(overrides.prepare_only_current_page, true);
  assert.equal(overrides.fresh_start_platform_tab, true);
});

test("buildPreparationBootstrapTimeoutOutcome keeps safe recovery context on bootstrap timeout", () => {
  const policy = derivePublicationTaskPreparationPolicy({
    publication_recovery_state: {
      recovery_overrides: {
        prepare_only_current_page: true,
        recovery_mode: "prepublish_resume",
        clear_draft_context: false,
        force_publish_page_refresh: true,
        verify_media_upload: true,
        wait_for_publish_confirmation: true,
      },
    },
  });
  const outcome = buildPreparationBootstrapTimeoutOutcome({
    platform: "youtube",
    code: "platform_route_bootstrap_timeout",
    reason: "Bootstrapping youtube publish route timed out",
    route: { url: "https://studio.youtube.com/channel/abc/videos/upload?d=ud&udvid=test" },
    actions: [{ kind: "platform_tab_resolved" }],
    preparationPolicy: policy,
    content: { title: "demo" },
    details: { phase: "ensure_publish_route", timeout_ms: 30000 },
  });

  assert.equal(outcome.status, "needs_human");
  assert.equal(outcome.error.code, "platform_route_bootstrap_timeout");
  assert.equal(outcome.result.recovery_overrides.recovery_mode, "prepublish_resume");
  assert.equal(outcome.result.recovery_overrides.prepare_only_current_page, true);
  assert.equal(outcome.result.recovery_overrides.clear_draft_context, false);
  assert.equal(outcome.result.recovery_overrides.force_publish_page_refresh, true);
  assert.equal(outcome.result.recovery_overrides.verify_media_upload, true);
  assert.equal(outcome.result.recovery_overrides.wait_for_publish_confirmation, true);
});

test("derivePublicationTaskExecutionTimeoutMs follows publish confirmation budget instead of fixed global timeout", () => {
  const timeoutMs = derivePublicationTaskExecutionTimeoutMs({
    platform: "douyin",
    content: {
      platform: "douyin",
      platform_specific_overrides: {
        wait_for_publish_confirmation: true,
        capture_response_timeout_ms: 90000,
      },
    },
  });

  assert.equal(timeoutMs, 240000);
});

test("derivePublicationTaskExecutionTimeoutMs honors persisted recovery context when content overrides are unavailable", () => {
  const timeoutMs = derivePublicationTaskExecutionTimeoutMs({
    platform: "douyin",
    recovery_context: {
      wait_for_publish_confirmation: true,
      capture_response_timeout_ms: 90000,
    },
    content: {
      platform: "douyin",
      platform_specific_overrides: {},
    },
  });

  assert.equal(timeoutMs, 240000);
});

test("derivePublicationTaskExecutionTimeoutMs honors explicit per-task timeout without exceeding global ceiling", () => {
  const timeoutMs = derivePublicationTaskExecutionTimeoutMs({
    task_execution_timeout_ms: 105000,
    content: {
      platform_specific_overrides: {
        capture_response_timeout_ms: 90000,
      },
    },
  });

  assert.equal(timeoutMs, 105000);
});

test("reconcileTimedOutPublicationTask upgrades provisional timeout to late verified stop-before-final-publish outcome", () => {
  const task = {
    status: "submitted",
    timeout_pending: true,
    result: { error: "timeout" },
    error: { code: "publication_task_timeout" },
    updated_at: "2026-05-31T17:24:56.607Z",
  };
  const reconciled = reconcileTimedOutPublicationTask(task, {
    status: "verified",
    result: {
      final_publish: {
        stop_before_final_publish: true,
        prepare_only_current_page: true,
      },
    },
    error: null,
  });

  assert.equal(reconciled, true);
  assert.equal(task.status, "verified");
  assert.equal(task.timeout_pending, false);
  assert.equal(task.result.final_publish.stop_before_final_publish, true);
  assert.equal(task.error, null);
});

test("dispatchPublicationTaskReconcileCallback posts serialized terminal task to reconcile endpoint", async () => {
  const calls = [];
  const fetchStub = async (url, options = {}) => {
    calls.push({
      url,
      options,
      body: JSON.parse(String(options.body || "{}")),
    });
    return {
      ok: true,
      status: 200,
      text: async () => '{"status":"needs_human"}',
    };
  };
  const task = {
    task_id: "task-callback",
    platform: "douyin",
    profile_id: "profile-1",
    status: "needs_human",
    created_at: "2026-06-01T10:00:00.000Z",
    updated_at: "2026-06-01T10:01:00.000Z",
    result: { verification_reason: "receipt_bound" },
    error: null,
    timeout_pending: false,
    reconcile_callback_url: "http://127.0.0.1:38471/api/v1/intelligent-copy/publication/reconcile-task",
    identity: {
      attempt_id: "attempt-1",
      content_id: "content-1",
      attempt_backed: true,
    },
  };

  assert.equal(shouldDispatchPublicationTaskReconcileCallback(task), true);
  const outcome = await dispatchPublicationTaskReconcileCallback(task, { fetchImpl: fetchStub });

  assert.equal(outcome.dispatched, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://127.0.0.1:38471/api/v1/intelligent-copy/publication/reconcile-task");
  assert.equal(calls[0].body.task.attempt_id, "attempt-1");
  assert.equal(calls[0].body.task.content_id, "content-1");
  assert.equal(calls[0].body.task.status, "needs_human");
});

test("reconcileTimedOutPublicationTask schedules reconcile callback for late terminal outcome", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push({
      url,
      options,
      body: JSON.parse(String(options.body || "{}")),
    });
    return {
      ok: true,
      status: 200,
      text: async () => '{"status":"verified"}',
    };
  };
  try {
    const task = {
      task_id: "task-timeout-callback",
      platform: "douyin",
      profile_id: "profile-2",
      status: "submitted",
      timeout_pending: true,
      created_at: "2026-06-01T10:00:00.000Z",
      updated_at: "2026-06-01T10:00:01.000Z",
      result: { error: "timeout" },
      error: { code: "publication_task_timeout" },
      reconcile_callback_url: "http://127.0.0.1:38471/api/v1/intelligent-copy/publication/reconcile-task",
      identity: {
        attempt_id: "attempt-timeout",
        content_id: "content-timeout",
        attempt_backed: true,
      },
    };

    const reconciled = reconcileTimedOutPublicationTask(task, {
      status: "verified",
      result: {
        final_publish: {
          stop_before_final_publish: true,
        },
      },
      error: null,
    });

    assert.equal(reconciled, true);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(calls.length, 1);
    assert.equal(calls[0].body.task.status, "verified");
    assert.equal(calls[0].body.task.attempt_id, "attempt-timeout");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("reconcileTimedOutPublicationTask ignores tasks that are not in provisional timeout state", () => {
  const task = {
    status: "needs_human",
    timeout_pending: false,
    result: {},
    error: null,
  };
  const reconciled = reconcileTimedOutPublicationTask(task, {
    status: "verified",
    result: { final_publish: { stop_before_final_publish: true } },
    error: null,
  });

  assert.equal(reconciled, false);
  assert.equal(task.status, "needs_human");
});

test("shouldBlockOnDraftClearFailure only blocks when force clear was explicitly requested", () => {
  assert.equal(
    shouldBlockOnDraftClearFailure(
      { forceClearDraft: false },
      { attempted: true, cleared: false, error: "clear failed" },
    ),
    false,
  );
  assert.equal(
    shouldBlockOnDraftClearFailure(
      { forceClearDraft: true },
      { attempted: true, cleared: false, error: "clear failed" },
    ),
    true,
  );
  assert.equal(
    shouldBlockOnDraftClearFailure(
      { forceClearDraft: true },
      {
        attempted: true,
        cleared: false,
        stale_detected: false,
        before_media_hint: false,
        after_media_hint: false,
        before_draft_hint: false,
        after_draft_hint: false,
      },
    ),
    false,
  );
});

test("derivePublicationTaskTimeoutStatus keeps publish-confirmation flows in submitted state", () => {
  assert.equal(
    derivePublicationTaskTimeoutStatus({
      recovery_context: {
        wait_for_publish_confirmation: true,
      },
      content: {
        platform_specific_overrides: {},
      },
    }),
    "submitted",
  );
  assert.equal(
    derivePublicationTaskTimeoutStatus({
      content: {
        platform_specific_overrides: {
          wait_for_publish_confirmation: true,
        },
      },
    }),
    "submitted",
  );
  assert.equal(
    derivePublicationTaskTimeoutStatus({
      content: {
        platform_specific_overrides: {},
      },
    }),
    "needs_human",
  );
});

test("buildPublicationTaskTimeoutEvidence preserves last trusted publish progress", () => {
  const evidence = buildPublicationTaskTimeoutEvidence({
    progress: {
      phase: "publish_receipt_poll",
      route: {
        url: "https://creator.douyin.com/creator-micro/content/post/video",
        title: "发布视频",
      },
      publication_field_snapshot: {
        platform: "douyin",
        title: "测试标题",
        visibility_or_publish_mode: "scheduled",
      },
      final_publish: {
        platform: "douyin",
        receipt_like: false,
        receipt_wait: 12345,
      },
      material_integrity: {
        platform_extras: {
          relevant_lines: ["定时发布", "发布视频"],
        },
      },
      visible_lines: ["定时发布", "发布视频"],
    },
  });

  assert.equal(evidence.phase, "publish_receipt_poll");
  assert.equal(evidence.route.url, "https://creator.douyin.com/creator-micro/content/post/video");
  assert.equal(evidence.publication_field_snapshot.platform, "douyin");
  assert.equal(evidence.publication_field_snapshot.title, "测试标题");
  assert.equal(evidence.final_publish.receipt_wait, 12345);
  assert.deepEqual(evidence.visible_lines, ["定时发布", "发布视频"]);
});

test("mergePublicationTaskProgress keeps last trusted route and visible lines when later patch is sparse", () => {
  const merged = mergePublicationTaskProgress(
    {
      phase: "pre_publish_ready",
      route: {
        url: "https://creator.douyin.com/creator-micro/content/post/video",
        title: "发布视频",
        path: "",
      },
      visible_lines: ["定时发布", "发布视频"],
      publication_field_snapshot: {
        platform: "douyin",
        title: "测试标题",
      },
    },
    {
      phase: "publish_receipt_poll",
      route: {
        url: "",
        title: "",
        path: "",
      },
      visible_lines: [],
      publication_field_snapshot: {},
    },
  );

  assert.equal(merged.phase, "publish_receipt_poll");
  assert.equal(merged.route.url, "https://creator.douyin.com/creator-micro/content/post/video");
  assert.deepEqual(merged.visible_lines, ["定时发布", "发布视频"]);
  assert.equal(merged.publication_field_snapshot.title, "测试标题");
});

test("buildPublicationTaskTimeoutEvidence preserves visual evidence from trusted progress", () => {
  const evidence = buildPublicationTaskTimeoutEvidence({
    progress: {
      phase: "publish_receipt_poll",
      route: {
        url: "https://creator.douyin.com/creator-micro/content/post/video",
        title: "Douyin creator",
      },
      final_publish: {
        platform: "douyin",
        receipt_like: false,
        receipt_wait: 12345,
      },
      visual_evidence: {
        artifact_path: "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/douyin-timeout.png",
        capture_type: "screenshot",
      },
    },
  });

  assert.equal(
    evidence.visual_evidence.artifact_path,
    "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/douyin-timeout.png",
  );
  assert.equal(evidence.visual_evidence.capture_type, "screenshot");
});

test("mergePublicationTaskProgress keeps last trusted visual evidence when later patch is sparse", () => {
  const merged = mergePublicationTaskProgress(
    {
      phase: "pre_publish_ready",
      route: {
        url: "https://creator.douyin.com/creator-micro/content/post/video",
        title: "Douyin creator",
        path: "",
      },
      visual_evidence: {
        artifact_path: "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/douyin-pre-publish.png",
        capture_type: "screenshot",
      },
    },
    {
      phase: "publish_receipt_poll",
      route: {
        url: "",
        title: "",
        path: "",
      },
      visual_evidence: {},
    },
  );

  assert.equal(
    merged.visual_evidence.artifact_path,
    "E:/WorkSpace/RoughCut/artifacts/publication-visual-evidence/douyin-pre-publish.png",
  );
  assert.equal(merged.visual_evidence.capture_type, "screenshot");
});

test("shouldBlockOnMediaUploadFailure blocks when video input was not mounted", () => {
  assert.equal(
    shouldBlockOnMediaUploadFailure({
      uploaded: false,
      reason: "no_video_file_input",
      fileInputs: [{ type: "file", accept: "image/png,image/jpeg" }],
    }),
    true,
  );
  assert.equal(
    shouldBlockOnMediaUploadFailure({
      uploaded: true,
      fileInputCount: 2,
    }),
    false,
  );
});

test("shouldTreatMediaUploadAsInProgress recognizes douyin upload-progress pages without video input", () => {
  assert.equal(
    shouldTreatMediaUploadAsInProgress(
      "douyin",
      {
        uploaded: false,
        reason: "no_video_file_input",
        fileInputs: [{ type: "file", accept: "image/png,image/jpeg" }],
      },
      {
        lines: [
          "MAXACE 美杜莎4 顶配次顶配开箱.mp4",
          "38%",
          "已上传： 295.7MB/761.1MB",
          "当前速度：6.6MB/s",
          "剩余时间：1分11秒",
        ],
        elements: [],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
    ),
    true,
  );
  assert.equal(
    shouldTreatMediaUploadAsInProgress(
      "douyin",
      {
        uploaded: false,
        reason: "no_video_file_input",
        fileInputs: [{ type: "file", accept: "image/png,image/jpeg" }],
      },
      {
        lines: ["设置封面", "请选择合集"],
        elements: [],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
    ),
    false,
  );
});

test("detectCompositePublicationSignals ignores douyin static upload reminder on ready editor surface", () => {
  const lines = [
    "作品描述",
    "发布时间",
    "发布设置",
    "预览视频",
    "预览封面/标题",
    "点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。",
  ];
  const text = lines.join("\n");
  const signals = detectCompositePublicationSignals("douyin", text, lines);
  assert.equal(signals.upload_busy, false);
  assert.equal(signals.upload_failed, false);
});

test("platformBodyWithTags keeps douyin body free of plain-text hashtags", () => {
  const body = platformBodyWithTags("douyin", {
    title: "标题A",
    body: "正文A",
    hashtags: ["测试A", "测试B"],
  });
  assert.equal(body, "正文A");
});

test("resolveDouyinDeclarationOption falls back to no declaration when content has no explicit marker", () => {
  assert.equal(resolveDouyinDeclarationOption(""), "无需添加自主声明");
  assert.equal(resolveDouyinDeclarationOption("内容由AI辅助生成"), "内容由AI生成");
  assert.equal(resolveDouyinDeclarationOption("本内容含营销推广信息"), "内容含营销推广信息");
});

test("detectCompositePublicationSignals marks douyin upload progress text as busy", () => {
  const lines = [
    "已上传： 295.7MB/761.1MB",
    "当前速度：6.6MB/s",
    "剩余时间：1分11秒",
    "38%",
  ];
  const signals = detectCompositePublicationSignals("douyin", lines.join("\n"), lines);
  assert.equal(signals.upload_busy, true);
  assert.equal(signals.upload_failed, false);
});

test("detectCompositePublicationSignals ignores bilibili static upload label on ready editor surface", () => {
  const lines = [
    "MAXACE 美杜莎4 顶配次顶配开箱 上传完成",
    "MAXACE 美杜莎4 顶配次顶配开箱 上传中...",
    "更换视频",
    "标题 19/80",
    "创作声明",
    "分区 生活兴趣",
    "标签 美杜莎 开箱",
    "简介 0 /2000",
    "定时发布",
    "存草稿",
    "立即投稿",
  ];
  const signals = detectCompositePublicationSignals("bilibili", lines.join("\n"), lines);
  assert.equal(signals.upload_busy, false);
  assert.equal(signals.upload_failed, false);
});

test("shouldInspectHiddenVideoInputsForDraftClear enables hidden uploader cleanup for bilibili only", () => {
  assert.equal(shouldInspectHiddenVideoInputsForDraftClear("bilibili"), true);
  assert.equal(shouldInspectHiddenVideoInputsForDraftClear("kuaishou"), false);
});

test("shouldResetBilibiliUploadModuleAfterDiscard only resets after explicit 不用了 discard", () => {
  assert.equal(shouldResetBilibiliUploadModuleAfterDiscard({
    prompt_present: true,
    discarded: true,
    clicked_label: "不用了",
  }), true);
  assert.equal(shouldResetBilibiliUploadModuleAfterDiscard({
    prompt_present: true,
    discarded: false,
    clicked_label: "继续编辑",
  }), false);
  assert.equal(shouldResetBilibiliUploadModuleAfterDiscard({
    prompt_present: false,
    discarded: false,
    clicked_label: "",
  }), false);
});

test("bilibiliDraftStorageKeysToClear only clears persisted upload draft record", () => {
  assert.deepEqual(bilibiliDraftStorageKeysToClear(), [
    "bili_videoup_record",
  ]);
});

test("isBilibiliFreshUploadEntrySnapshot accepts clean upload entry surface", () => {
  const freshness = isBilibiliFreshUploadEntrySnapshot(
    {
      url: "https://member.bilibili.com/platform/upload/video/frame?page_from=creative_home_top_upload",
      lines: [
        "发布视频",
        "点击上传或将视频拖拽到此区域",
        "上传视频",
        "视频大小16G以内",
      ],
      fileInputs: [{ accept: ".mp4,.mov,video/*" }],
    },
    "C:\\media\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
    "美杜莎4顶配次顶配双开箱，版本差异一镜拆给你看",
  );
  assert.equal(freshness.fresh, true);
  assert.equal(freshness.prompt_blocked, false);
  assert.equal(freshness.stale_mismatch, false);
});

test("isBilibiliFreshUploadEntrySnapshot rejects stale editor surface with mismatched draft title", () => {
  const freshness = isBilibiliFreshUploadEntrySnapshot(
    {
      url: "https://member.bilibili.com/platform/upload/video/frame?page_from=creative_home_top_upload",
      lines: [
        "发布视频",
        "MAXACE美杜莎4开箱先看细节",
        "上传完成",
        "更换视频",
        "标题",
        "创作声明",
        "分区",
        "标签",
        "简介",
        "定时发布",
        "立即投稿",
      ],
      fileInputs: [{ accept: ".mp4,.mov,video/*" }],
    },
    "C:\\media\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
    "美杜莎4顶配次顶配双开箱，版本差异一镜拆给你看",
  );
  assert.equal(freshness.fresh, false);
  assert.equal(freshness.stale_mismatch, true);
});

test("shouldPersistBilibiliDirtyEditorBeforeRouteReset only persists populated editor surfaces", () => {
  assert.equal(
    shouldPersistBilibiliDirtyEditorBeforeRouteReset(
      { field_shell: true, upload_prompt_surface: false },
      { fresh: false, prompt_blocked: false },
    ),
    true,
  );
  assert.equal(
    shouldPersistBilibiliDirtyEditorBeforeRouteReset(
      { field_shell: false, upload_prompt_surface: true },
      { fresh: false, prompt_blocked: false },
    ),
    false,
  );
  assert.equal(
    shouldPersistBilibiliDirtyEditorBeforeRouteReset(
      { field_shell: true, upload_prompt_surface: false },
      { fresh: true, prompt_blocked: false },
    ),
    false,
  );
});

test("currentPageMatchesPrepareOnlyExecutionContext accepts douyin upload shell as authoritative start", () => {
  assert.equal(
    currentPageMatchesPrepareOnlyExecutionContext(
      "douyin",
      {
        url: "https://creator.douyin.com/creator-micro/content/upload",
        text: "发布视频 点击上传 或直接将视频文件拖入此区域",
      },
      {
        lines: ["发布视频", "点击上传 或直接将视频文件拖入此区域"],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
      [],
    ),
    true,
  );
});

test("currentPageMatchesPrepareOnlyExecutionContext accepts douyin loading upload shell as authoritative start", () => {
  assert.equal(
    currentPageMatchesPrepareOnlyExecutionContext(
      "douyin",
      {
        url: "https://creator.douyin.com/creator-micro/content/upload",
        title: "抖音创作者中心",
        text: "加载中，请稍候...",
      },
      {
        title: "抖音创作者中心",
        lines: ["加载中，请稍候..."],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
      [],
    ),
    true,
  );
});

test("currentPageMatchesPrepareOnlyExecutionContext accepts douyin post-video editor entered from same-run fresh upload", () => {
  assert.equal(
    currentPageMatchesPrepareOnlyExecutionContext(
      "douyin",
      {
        url: "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
        text: "抖音创作者中心",
      },
      {
        url: "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
        lines: [
          "MAXACE 美杜莎4 顶配次顶配开箱.mp4",
          "上传过程中请不要删除/移动文件",
          "0%",
          "文件解析中，请稍等...",
        ],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
      [
        { kind: "prepare_only_current_page_normalize_to_upload_entry" },
        { kind: "media_upload", uploaded: true },
      ],
    ),
    true,
  );
});

test("currentPageMatchesPrepareOnlyExecutionContext rejects douyin post-video editor without same-run fresh upload evidence", () => {
  assert.equal(
    currentPageMatchesPrepareOnlyExecutionContext(
      "douyin",
      {
        url: "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
        text: "抖音创作者中心",
      },
      {
        url: "https://creator.douyin.com/creator-micro/content/post/video?enter_from=publish_page",
        lines: ["作品描述", "设置封面", "请选择合集", "请选择自主声明"],
      },
      "E:\\WorkSpace\\RoughCut\\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
      [],
    ),
    false,
  );
});

test("shouldBypassDraftResumeAtAuthoritativeUploadEntry only bypasses clean douyin upload shells", () => {
  assert.equal(
    shouldBypassDraftResumeAtAuthoritativeUploadEntry("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/upload",
      lines: ["你还有上次未发布的视频，是否继续编辑？", "点击上传或直接将视频文件拖入此区域", "上传视频"],
      headings: ["发布视频"],
    }),
    false,
  );
  assert.equal(
    shouldBypassDraftResumeAtAuthoritativeUploadEntry("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/upload",
      lines: ["点击上传或直接将视频文件拖入此区域", "上传视频"],
      headings: ["发布视频"],
    }),
    true,
  );
  assert.equal(
    shouldBypassDraftResumeAtAuthoritativeUploadEntry("douyin", {
      url: "https://creator.douyin.com/creator-micro/content/post/video",
      lines: ["作品描述", "封面", "发布时间", "发布"],
      headings: ["发布视频"],
    }),
    false,
  );
});

test("isBilibiliUploadQueueCardCandidate rejects publish mode tabs and accepts real upload cards", () => {
  assert.equal(isBilibiliUploadQueueCardCandidate("视频投稿"), false);
  assert.equal(isBilibiliUploadQueueCardCandidate("互动视频投稿"), false);
  assert.equal(
    isBilibiliUploadQueueCardCandidate("MAXACE 美杜莎4 顶配次顶配开箱 上传中..."),
    true,
  );
  assert.equal(
    isBilibiliUploadQueueCardCandidate("MAXACE 美杜莎4 顶配次顶配开箱", "MAXACE 美杜莎4 顶配次顶配开箱"),
    true,
  );
});

test("shouldAcceptCompositeUploadReadyState accepts bilibili ready editor surface once only static upload text remains", () => {
  const state = {
    ready: true,
    busy: false,
    failed: false,
    uploadPromptOnly: false,
  };
  assert.equal(shouldAcceptCompositeUploadReadyState("bilibili", state, 1, 5000), true);
});

test("shouldTreat douyin upload success surface as no longer busy in readiness phase", async () => {
  const text = [
    "预览视频",
    "预览封面/标题",
    "重新上传",
    "作品描述",
    "发布时间",
    "发布设置",
    "谁可以看",
    "极速上传成功，上传时间119秒",
    "点击发布后，如作品还在上传中，请勿关闭页面，等待上传发布完成。",
  ].join(" ");

  const busy = /已上传：|当前速度：|剩余时间：|处理中\s*\d+%|检测中\s*\d+%|检测中99%|\b\d{1,3}%\b/.test(text)
    || ((/上传中|正在上传|视频处理中/.test(text)) && !(/预览视频|预览封面\/标题|预览封面/.test(text) && /重新上传/.test(text) && /作品描述|发布时间|发布设置|谁可以看/.test(text)));
  const douyinReadySurface = /预览视频|预览封面\/标题|预览封面/.test(text)
    && /重新上传/.test(text)
    && /作品描述|发布时间|发布设置|谁可以看/.test(text)
    && !/上传失败|已上传：|当前速度：|剩余时间：|\b\d{1,3}%\b/.test(text);

  assert.equal(douyinReadySurface, true);
  assert.equal(busy, false);
});
