import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "../components/ui/PageHeader";
import { api } from "../api";

const SUPPORTED_PLATFORMS = [
  { id: "bilibili", label: "B 站" },
  { id: "douyin", label: "抖音" },
  { id: "xiaohongshu", label: "小红书" },
  { id: "kuaishou", label: "快手" },
  { id: "wechat-channels", label: "视频号" },
];

const PLATFORM_ALIASES: Record<string, string> = {
  wechat_channels: "wechat-channels",
  wechat: "wechat-channels",
};

const PLATFORM_MATERIAL_SPECS: Record<string, Array<{ label: string; value: string }>> = {
  bilibili: [
    { label: "封面", value: "首页推荐 4:3 1440x1080；个人空间 16:9 1600x900" },
    { label: "标题", value: "字段名“标题”；硬上限 80 字，建议 10-30 字" },
    { label: "简介", value: "字段名“简介”；建议 40-900 字" },
    { label: "标签", value: "1-10 个；保留主体/品类/场景标签" },
    { label: "合集", value: "支持；需显式选择合集策略" },
    { label: "声明", value: "创作声明可选：内容无需标注、含AI生成内容、含虚构演绎内容、内容含营销信息、个人观点仅供参考、内容为转载" },
    { label: "分区", value: "支持分区；当前稳定选项：生活兴趣/户外潮流，兜底 tid=250" },
    { label: "定时", value: "支持；上传进度只阻塞最终投稿，不阻塞字段填写" },
  ],
  douyin: [
    { label: "封面", value: "横封面 4:3 1440x1080；竖封面 3:4 1080x1440" },
    { label: "标题", value: "字段名“作品标题”；硬上限 55 字，建议 6-22 字" },
    { label: "简介", value: "字段名“作品描述”；建议 16-160 字" },
    { label: "标签", value: "1-8 个；话题写入正文优先，推荐词只作辅助" },
    { label: "合集", value: "支持；已验证准确选择合集" },
    { label: "声明", value: "自主声明可选；默认“无需添加自主声明”，按平台弹窗条目让客户选择" },
    { label: "定时", value: "支持；当前正式合同默认直接发布优先" },
  ],
  xiaohongshu: [
    { label: "封面", value: "3:4 竖版母版 1080x1440；先做封面避免后续弹窗打断" },
    { label: "标题", value: "字段名“标题”；硬上限 20 字，建议 8-20 字" },
    { label: "简介", value: "字段名“正文”；建议 35-520 字，真实笔记感" },
    { label: "标签", value: "1-10 个；字段名“话题”，按主体/场景选择" },
    { label: "合集", value: "支持；已验证合集选择" },
    { label: "群聊", value: "支持；已验证群聊绑定选择" },
    { label: "声明", value: "原创声明可选；按平台原创/非原创声明条目让客户选择" },
  ],
  kuaishou: [
    { label: "封面", value: "4:3 横版母版 1440x1080；主封面槽位" },
    { label: "简介", value: "字段名“作品描述”；建议 18-180 字，可内嵌标签" },
    { label: "标签", value: "1-8 个；优先真实下拉推荐，大小写漂移不阻塞发布" },
    { label: "合集", value: "支持；已验证合集选择" },
    { label: "声明", value: "作者声明可选；默认“个人观点，仅供参考”，按平台声明清单让客户选择" },
    { label: "定时", value: "支持；字段可在上传过程中完成" },
  ],
  "wechat-channels": [
    { label: "封面", value: "动态封面 4:3 1440x1080；主页卡片 3:4 1080x1440" },
    { label: "标题", value: "字段名“标题”；建议 6-16 字，稳妥可信" },
    { label: "简介", value: "字段名“描述”；建议 18-220 字" },
    { label: "标签", value: "1-6 个；字段名“标签/话题”" },
    { label: "合集", value: "支持；需显式选择合集策略" },
    { label: "声明", value: "原创声明/原创类型可选；按平台声明清单让客户选择" },
  ],
};

const PLATFORM_SELECT_OPTIONS: Record<string, Array<{ key: string; label: string; options: Array<{ value: string; label: string }> }>> = {
  bilibili: [
    {
      key: "declaration",
      label: "内容类型声明",
      options: [
        { value: "内容无需标注", label: "内容无需标注" },
        { value: "含AI生成内容", label: "含AI生成内容" },
        { value: "含虚构演绎内容", label: "含虚构演绎内容" },
        { value: "内容含营销信息", label: "内容含营销信息" },
        { value: "个人观点，仅供参考", label: "个人观点，仅供参考" },
        { value: "内容为转载", label: "内容为转载" },
      ],
    },
    {
      key: "category",
      label: "分区",
      options: [
        { value: "生活兴趣/户外潮流", label: "生活兴趣/户外潮流" },
        { value: "数码", label: "科技/数码" },
        { value: "日常", label: "生活/日常" },
        { value: "出行", label: "生活/出行" },
        { value: "手工", label: "生活/手工" },
      ],
    },
  ],
  douyin: [
    {
      key: "declaration",
      label: "内容类型声明",
      options: [
        { value: "无需添加自主声明", label: "无需添加自主声明" },
        { value: "个人观点，仅供参考", label: "个人观点，仅供参考" },
      ],
    },
  ],
  xiaohongshu: [
    {
      key: "platform_specific_overrides.selected_declarations",
      label: "原创声明",
      options: [
        { value: "原创声明", label: "声明原创" },
      ],
    },
  ],
  kuaishou: [
    {
      key: "declaration",
      label: "内容类型声明",
      options: [
        { value: "个人观点，仅供参考", label: "个人观点，仅供参考" },
        { value: "内容无需标注", label: "内容无需标注" },
      ],
    },
  ],
  "wechat-channels": [
    {
      key: "platform_specific_overrides.original_statement",
      label: "原创类型",
      options: [
        { value: "原创", label: "原创" },
        { value: "非原创", label: "非原创" },
      ],
    },
    {
      key: "declaration",
      label: "内容类型声明",
      options: [
        { value: "个人观点，仅供参考", label: "个人观点，仅供参考" },
        { value: "内容无需标注", label: "内容无需标注" },
      ],
    },
  ],
};

const COLLECTION_NAME_OPTIONS = ["EDC刀光火工具集", "EDC潮玩桌搭", "FAS新品", "机能户外装备"];

function normalizePlatformId(platform: string) {
  const key = String(platform || "").trim();
  return PLATFORM_ALIASES[key] ?? key;
}

function payloadText(payload: Record<string, unknown> | undefined, key: string, fallback = "未设置") {
  const value = payload?.[key];
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value || "").trim() || fallback;
}

function normalizeCollectionStrategy(value: unknown) {
  const raw = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
  const platforms = raw.platforms && typeof raw.platforms === "object" && !Array.isArray(raw.platforms)
    ? raw.platforms as Record<string, Record<string, unknown>>
    : {};
  const candidateCollections = Array.isArray(raw.candidate_collections)
    ? raw.candidate_collections.map((item) => String(item)).filter(Boolean)
    : [];
  const rules = Array.isArray(raw.rules)
    ? raw.rules.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object" && !Array.isArray(item)))
    : [];
  return {
    mode: String(raw.mode ?? "auto"),
    default_collection_name: String(raw.default_collection_name ?? ""),
    candidate_collections: candidateCollections,
    rules,
    platforms,
  };
}

function collectionRuleText(rule: Record<string, unknown>) {
  return String(rule.natural_language_rule ?? rule.rule ?? rule.description ?? "").trim();
}

function collectionRuleExamples(rule: Record<string, unknown>) {
  const examples = rule.examples ?? [];
  if (Array.isArray(examples)) return examples.map((item) => String(item)).filter(Boolean);
  const value = String(examples || "").trim();
  return value ? [value] : [];
}

function platformOptionValue(options: Record<string, Record<string, unknown>>, platform: string, key: string) {
  const value = options[platform];
  if (!value) return "";
  if (key.includes(".")) {
    const [root, child] = key.split(".");
    const nested = value[root];
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      const nestedValue = (nested as Record<string, unknown>)[child];
      if (Array.isArray(nestedValue)) return String(nestedValue[0] ?? "");
      return String(nestedValue ?? "");
    }
    return "";
  }
  return String(value[key] ?? "");
}

function withPlatformOptionValue(
  options: Record<string, Record<string, unknown>>,
  platform: string,
  key: string,
  value: string,
) {
  const next = { ...options };
  const current = { ...(next[platform] ?? {}) };
  if (key.includes(".")) {
    const [root, child] = key.split(".");
    const nested = { ...((current[root] && typeof current[root] === "object" && !Array.isArray(current[root])) ? current[root] as Record<string, unknown> : {}) };
    if (value) nested[child] = child === "selected_declarations" ? [value] : value;
    else delete nested[child];
    if (Object.keys(nested).length) current[root] = nested;
    else delete current[root];
  } else if (value) {
    current[key] = value;
  } else {
    delete current[key];
  }
  if (Object.keys(current).length) next[platform] = current;
  else delete next[platform];
  return next;
}

function platformBindingStatus(bindingPayload: Record<string, unknown> | null | undefined) {
  if (bindingPayload?.adapter !== "social_auto_upload") return "unbound";
  return bindingPayload.status === "login_confirmed" ? "confirmed" : "needs_confirmation";
}

function errorText(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error || "");
}

export function PublicationManagementPage() {
  const queryClient = useQueryClient();
  const creators = useQuery({ queryKey: ["creator-cards"], queryFn: api.listCreatorCards });
  const [selectedCreatorId, setSelectedCreatorId] = useState("");
  const [refinePrompt, setRefinePrompt] = useState("");
  const [bindingModal, setBindingModal] = useState<{ id: string; label: string } | null>(null);
  const [bindingAccountName, setBindingAccountName] = useState("");
  const [loginLaunchResult, setLoginLaunchResult] = useState<Record<string, unknown> | null>(null);
  const [loginStatusResult, setLoginStatusResult] = useState<Record<string, unknown> | null>(null);
  const [dashboardOpenResult, setDashboardOpenResult] = useState<Record<string, unknown> | null>(null);
  const lastAutoLoginKeyRef = useRef("");
  const autoConfirmedLoginKeyRef = useRef("");
  const creatorId = selectedCreatorId || creators.data?.items[0]?.id || "";
  const selectedCreator = creators.data?.items.find((creator) => creator.id === creatorId) ?? null;
  const publicationProfile = useQuery({
    queryKey: ["creator-publication-profile", creatorId],
    queryFn: () => api.getPublicationProfile(creatorId),
    enabled: Boolean(creatorId),
  });

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["creator-publication-profile", creatorId] });
  };

  const refine = useMutation({
    mutationFn: () => api.refinePublicationProfile(creatorId, refinePrompt),
    onSuccess: async () => {
      setRefinePrompt("");
      await refresh();
    },
  });
  const startLogin = useMutation({
    mutationFn: () => {
      if (!bindingModal) throw new Error("未选择平台。");
      return api.startSocialAutoUploadLogin(creatorId, {
        platform: bindingModal.id,
        browser: "chrome",
        account_name: bindingAccountName.trim(),
      });
    },
    onSuccess: (result) => {
      setLoginLaunchResult(result);
    },
  });
  const confirmBinding = useMutation({
    mutationFn: () => {
      if (!bindingModal) throw new Error("未选择平台。");
      return api.bindSocialAutoUploadLogin(creatorId, {
        platform: bindingModal.id,
        browser: "chrome",
        account_name: bindingAccountName.trim(),
        login_confirmed: true,
      });
    },
    onSuccess: async () => {
      setBindingModal(null);
      setBindingAccountName("");
      setLoginLaunchResult(null);
      setLoginStatusResult(null);
      lastAutoLoginKeyRef.current = "";
      autoConfirmedLoginKeyRef.current = "";
      await refresh();
    },
  });
  const openDashboard = useMutation({
    mutationFn: (platformId: string) => api.openSocialAutoUploadDashboard(creatorId, {
      platform: platformId,
      browser: "chrome",
    }),
    onSuccess: (result) => {
      setDashboardOpenResult(result);
    },
    onError: (error) => {
      setDashboardOpenResult({ status: "dashboard_failed", warning: errorText(error) });
    },
    onSettled: async () => {
      await refresh();
    },
  });
  const profilePayload = publicationProfile.data?.publication_payload_json as Record<string, unknown> | undefined;
  const platformOptions = (profilePayload?.platform_options && typeof profilePayload.platform_options === "object" && !Array.isArray(profilePayload.platform_options))
    ? profilePayload.platform_options as Record<string, Record<string, unknown>>
    : {};
  const collectionStrategy = normalizeCollectionStrategy(profilePayload?.collection_strategy);
  const patchProfile = useMutation({
    mutationFn: (payload: Record<string, unknown>) => api.patchPublicationProfile(creatorId, { publication_payload_json: payload }),
    onSuccess: async () => {
      await refresh();
    },
  });
  const platformRules = (profilePayload?.platform_rules && typeof profilePayload.platform_rules === "object" && !Array.isArray(profilePayload.platform_rules))
    ? profilePayload.platform_rules as Record<string, Record<string, unknown>>
    : {};
  const defaultPlatforms = new Set(
    Array.isArray(profilePayload?.default_platforms)
      ? profilePayload?.default_platforms.map((item) => normalizePlatformId(String(item)))
      : [],
  );
  const bindingByPlatform = useMemo(() => {
    const entries = publicationProfile.data?.bindings ?? [];
    return new Map(entries.map((item) => [normalizePlatformId(item.platform), item]));
  }, [publicationProfile.data?.bindings]);
  const normalizedPlatformRules = useMemo(() => {
    return Object.fromEntries(Object.entries(platformRules).map(([platform, rules]) => [normalizePlatformId(platform), rules]));
  }, [platformRules]);
  const platformCards = useMemo(() => {
    const platformIds = new Set([
      ...SUPPORTED_PLATFORMS.map((item) => item.id),
      ...Object.keys(normalizedPlatformRules),
      ...Array.from(defaultPlatforms),
      ...Array.from(bindingByPlatform.keys()),
    ]);
    return Array.from(platformIds).map((platform) => {
      const known = SUPPORTED_PLATFORMS.find((item) => item.id === platform);
      return { id: platform, label: known?.label ?? platform };
    });
  }, [bindingByPlatform, defaultPlatforms, normalizedPlatformRules]);
  const updatePlatformOption = (platform: string, key: string, value: string) => {
    if (!profilePayload || patchProfile.isPending) return;
    const normalizedOptions = Object.fromEntries(
      Object.entries(platformOptions).map(([optionPlatform, optionValue]) => [normalizePlatformId(optionPlatform), optionValue]),
    );
    patchProfile.mutate({
      ...profilePayload,
      platform_options: withPlatformOptionValue(normalizedOptions, platform, key, value),
    });
  };
  const updateCollectionStrategy = (patch: Record<string, unknown>) => {
    if (!profilePayload || patchProfile.isPending) return;
    const nextStrategy = {
      ...collectionStrategy,
      ...patch,
    };
    patchProfile.mutate({
      ...profilePayload,
      collection_strategy: nextStrategy,
    });
  };
  const openBindingModal = (platform: { id: string; label: string }, bindingPayload?: Record<string, unknown> | null) => {
    setBindingModal(platform);
    setBindingAccountName(
      String(bindingPayload?.account_label || bindingPayload?.account_name || "").trim()
      || `${selectedCreator?.name || "发布账号"} · ${platform.label}`,
    );
    setLoginLaunchResult(null);
    setLoginStatusResult(null);
    lastAutoLoginKeyRef.current = "";
    autoConfirmedLoginKeyRef.current = "";
    startLogin.reset();
    confirmBinding.reset();
  };
  useEffect(() => {
    if (!bindingModal || !creatorId || !bindingAccountName.trim()) return;
    const loginKey = `${creatorId}:${bindingModal.id}`;
    if (lastAutoLoginKeyRef.current === loginKey) return;
    lastAutoLoginKeyRef.current = loginKey;
    setLoginLaunchResult(null);
    setLoginStatusResult(null);
    startLogin.mutate();
  }, [bindingModal?.id, creatorId]);

  useEffect(() => {
    if (!bindingModal || !creatorId || !bindingAccountName.trim()) return;
    if (!loginLaunchResult && !startLogin.isSuccess) return;
    let stopped = false;
    const loginKey = `${creatorId}:${bindingModal.id}:${bindingAccountName.trim()}`;
    const poll = async () => {
      try {
        const result = await api.checkSocialAutoUploadLogin(creatorId, {
          platform: bindingModal.id,
          browser: "chrome",
          account_name: bindingAccountName.trim(),
        });
        if (stopped) return;
        setLoginStatusResult(result);
        if (result.status === "login_valid" && autoConfirmedLoginKeyRef.current !== loginKey) {
          autoConfirmedLoginKeyRef.current = loginKey;
          confirmBinding.mutate();
        }
      } catch (error) {
        if (!stopped) setLoginStatusResult({ status: "monitor_unavailable", warning: errorText(error) });
      }
    };
    poll();
    const timer = window.setInterval(poll, 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [bindingModal?.id, bindingAccountName, creatorId, loginLaunchResult?.status, startLogin.isSuccess]);
  return (
    <section className="page-stack asset-workspace-page">
      <PageHeader
        eyebrow="资产库"
        title="平台发布档案"
        description="维护创作者平台绑定、发布档案和登录确认，不承担发布执行。"
      />
      <section className="page-section asset-workspace-section asset-workspace-section-plain">
        <div className="page-section-body">
          <div className="asset-workspace-topline">
            <div className="asset-workspace-controls">
              <label>
                <span>创作者</span>
                <select className="input" value={creatorId} onChange={(event) => setSelectedCreatorId(event.target.value)}>
                  <option value="">请选择创作者</option>
                  {(creators.data?.items ?? []).map((creator) => <option key={creator.id} value={creator.id}>{creator.name}</option>)}
                </select>
              </label>
              <label>
                <span>发布调整</span>
                <textarea
                  className="input"
                  rows={2}
                  value={refinePrompt}
                  onChange={(event) => setRefinePrompt(event.target.value)}
                  placeholder="例如：B 站标题保留型号和完整结论，抖音前三秒更直接。"
                />
              </label>
              <div className="asset-workspace-actions">
                <button type="button" className="button primary" disabled={!creatorId || !refinePrompt.trim() || refine.isPending} onClick={() => refine.mutate()}>
                  {refine.isPending ? "调整中" : "智能调整"}
                </button>
              </div>
            </div>
          </div>
          {publicationProfile.data ? (
            <div className="publication-collection-strategy">
              <div>
                <strong>合集策略</strong>
                <span>{collectionStrategy.mode === "rule_based" ? "按任务内容自动命中合集，未命中时使用兜底。" : "统一决定各平台发布时加入哪个合集。"}</span>
              </div>
              <label>
                <span>选择方式</span>
                <select
                  className="input"
                  value={collectionStrategy.mode}
                  disabled={patchProfile.isPending}
                  onChange={(event) => updateCollectionStrategy({ mode: event.target.value })}
                >
                  <option value="llm_classify">LLM 理解分类</option>
                  <option value="rule_based">兼容旧规则</option>
                  <option value="select_existing">固定选择合集</option>
                  <option value="auto">发布时自动选择</option>
                </select>
              </label>
              <label>
                <span>{collectionStrategy.mode === "rule_based" ? "兜底合集" : "默认合集"}</span>
                <select
                  className="input"
                  value={collectionStrategy.default_collection_name}
                  disabled={patchProfile.isPending}
                  onChange={(event) => updateCollectionStrategy({ default_collection_name: event.target.value })}
                >
                  <option value="">自动选择</option>
                  {COLLECTION_NAME_OPTIONS.map((name) => (
                    <option key={name} value={name}>{name}</option>
                  ))}
                </select>
              </label>
              {(collectionStrategy.mode === "llm_classify" || collectionStrategy.mode === "rule_based" || collectionStrategy.rules.length > 0) ? (
                <div className="publication-collection-rules">
                  <div className="publication-collection-rules-head">
                    <strong>分类标准</strong>
                    <span>
                      {collectionStrategy.mode === "llm_classify"
                        ? "发布时由 LLM 理解任务内容，先统一判断合集名，再应用到所有发布平台。"
                        : "当前选择方式未启用 LLM 分类，切到“LLM 理解分类”后生效。"}
                    </span>
                  </div>
                  {collectionStrategy.rules.length ? (
                    <div className="publication-collection-rule-list">
                      {collectionStrategy.rules.map((rule, index) => {
                        const ruleText = collectionRuleText(rule);
                        const examples = collectionRuleExamples(rule);
                        return (
                          <div className="publication-collection-rule-row" key={`${String(rule.collection_name ?? index)}-${index}`}>
                            <strong>{String(rule.collection_name ?? "未命名合集")}</strong>
                            <span>{ruleText || "未填写自然语言分类标准"}</span>
                            {examples.length ? <em>例：{examples.join(" / ")}</em> : null}
                          </div>
                        );
                      })}
                      <div className="publication-collection-rule-row fallback">
                        <strong>未命中兜底</strong>
                        <span>{collectionStrategy.default_collection_name || "发布时自动选择"}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="publication-collection-rule-empty">当前没有配置自然语言分类标准，会退回平台发布时自动选择。</div>
                  )}
                </div>
              ) : null}
            </div>
          ) : null}
          {publicationProfile.data ? (
            <div className="publication-platform-grid">
              {platformCards.map((platform) => {
                const binding = bindingByPlatform.get(platform.id);
                const bindingPayload = binding?.binding_payload_json;
                const bindingStatus = platformBindingStatus(bindingPayload);
                const isSocialAutoUploadBound = bindingStatus === "confirmed";
                const rules = normalizedPlatformRules[platform.id] ?? {};
                const materialSpecs = PLATFORM_MATERIAL_SPECS[platform.id] ?? [];
                const selectOptions = PLATFORM_SELECT_OPTIONS[platform.id] ?? [];
                return (
                  <article key={platform.id} className="publication-platform-card">
                    <div className="publication-platform-card-head">
                      <div>
                        <strong>{platform.label}</strong>
                        <span>
                          {isSocialAutoUploadBound
                            ? `已绑定 · ${String(bindingPayload?.account_label || bindingPayload?.account_name || binding?.credential_ref || "").trim()}`
                            : bindingStatus === "needs_confirmation"
                              ? "需重新登录确认账号"
                              : defaultPlatforms.has(platform.id) ? "默认发布平台" : "可选平台"}
                        </span>
                      </div>
                      <div className="publication-platform-card-actions">
                        <button type="button" className="button button-sm" disabled={!creatorId} onClick={() => openBindingModal(platform, bindingPayload)}>
                          {isSocialAutoUploadBound ? "更换账号" : "绑定平台"}
                        </button>
                        <button
                          type="button"
                          className="button ghost button-sm"
                          disabled={!isSocialAutoUploadBound || openDashboard.isPending}
                          onClick={() => openDashboard.mutate(platform.id)}
                        >
                          打开后台
                        </button>
                        <button type="button" className="button ghost button-sm" disabled={!isSocialAutoUploadBound}>
                          自动发布
                        </button>
                        {binding ? (
                          <button type="button" className="button ghost button-sm" onClick={() => api.deletePlatformBinding(creatorId, platform.id).then(refresh)}>
                            解除
                          </button>
                        ) : null}
                      </div>
                    </div>
                    <div className="publication-material-specs">
                      {materialSpecs.map((spec) => (
                        <div key={spec.label} className="publication-material-spec-row">
                          <span>{spec.label}</span>
                          <strong>{spec.value}</strong>
                        </div>
                      ))}
                    </div>
                    {selectOptions.length ? (
                      <div className="publication-platform-config">
                        {selectOptions.map((field) => (
                          <label key={field.key}>
                            <span>{field.label}</span>
                            <select
                              className="input"
                              value={platformOptionValue(platformOptions, platform.id, field.key)}
                              disabled={patchProfile.isPending}
                              onChange={(event) => updatePlatformOption(platform.id, field.key, event.target.value)}
                            >
                              <option value="">发布时自动选择</option>
                              {field.options.map((option) => (
                                <option key={option.value} value={option.value}>{option.label}</option>
                              ))}
                            </select>
                          </label>
                        ))}
                      </div>
                    ) : null}
                    <div className="publication-rule-list">
                      <span>标题：{payloadText(rules, "title_rule", "按创作者结论和关键实体生成")}</span>
                      <span>开头：{payloadText(rules, "intro_rule", "前三秒突出本条最重要信息")}</span>
                      <span>标签：{payloadText(rules, "tag_rules", "按平台和内容自动建议")}</span>
                      <span>栏目：{payloadText(rules, "category", "发布前确认")}</span>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : <div className="muted top-gap">先选择创作者。</div>}
          {dashboardOpenResult ? (
            <div className={`publication-login-status publication-login-status-${String(dashboardOpenResult.status || "unknown").replace(/_/g, "-")}`}>
              <strong>{dashboardOpenResult.status === "dashboard_started" ? "后台窗口已打开" : "后台窗口未打开"}</strong>
              <span>{String(dashboardOpenResult.account_label || dashboardOpenResult.warning || dashboardOpenResult.next_step || "").trim()}</span>
            </div>
          ) : null}
          {bindingModal ? (
            <div className="floating-modal-backdrop" role="presentation">
              <div className="floating-modal-shell publication-login-modal" role="dialog" aria-modal="true" aria-label={`${bindingModal.label} 登录绑定`}>
                <button
                  className="button ghost floating-modal-close"
                  type="button"
                  onClick={() => {
                    setBindingModal(null);
                    setLoginLaunchResult(null);
                    setLoginStatusResult(null);
                    lastAutoLoginKeyRef.current = "";
                    autoConfirmedLoginKeyRef.current = "";
                  }}
                >
                  关闭
                </button>
                <div className="publication-login-modal-content">
                  <div>
                    <span className="publication-login-modal-kicker">平台账号绑定</span>
                    <h2>{bindingModal.label}</h2>
                    <p>先用独立账号标签打开登录窗口，完成扫码或手动登录后再确认绑定。</p>
                  </div>
                  <label>
                    <span>账号标签</span>
                    <input
                      className="input"
                      value={bindingAccountName}
                      onChange={(event) => setBindingAccountName(event.target.value)}
                      placeholder="例如：Demo Creator · B站主号"
                    />
                  </label>
                  {loginLaunchResult ? (
                    <div className="publication-login-command">
                      <strong>{loginLaunchResult.status === "login_started" ? "登录窗口已启动" : "需要手动登录"}</strong>
                      {loginLaunchResult.launch_source ? <span>启动方式：{String(loginLaunchResult.launch_source)}</span> : null}
                      {loginLaunchResult.pid ? <span>进程：{String(loginLaunchResult.pid || "")}</span> : null}
                      {loginLaunchResult.warning ? <span>{String(loginLaunchResult.warning)}</span> : null}
                      <code>{Array.isArray(loginLaunchResult.command) ? loginLaunchResult.command.join(" ") : ""}</code>
                    </div>
                  ) : null}
                  {loginStatusResult ? (
                    <div className={`publication-login-status publication-login-status-${String(loginStatusResult.status || "unknown").replace(/_/g, "-")}`}>
                      <strong>
                        {loginStatusResult.status === "login_valid"
                          ? "已检测到登录成功，正在保存绑定"
                          : loginStatusResult.status === "login_invalid"
                            ? "正在等待登录完成"
                            : "暂时无法自动检测登录状态"}
                      </strong>
                      {loginStatusResult.check_source ? <span>检测方式：{String(loginStatusResult.check_source)}</span> : null}
                      {loginStatusResult.warning ? <span>{String(loginStatusResult.warning)}</span> : null}
                    </div>
                  ) : null}
                  {startLogin.isError ? <div className="publication-login-error">{errorText(startLogin.error)}</div> : null}
                  {confirmBinding.isError ? <div className="publication-login-error">{errorText(confirmBinding.error)}</div> : null}
                  <div className="publication-login-modal-actions">
                    <button
                      type="button"
                      className="button"
                      disabled={!bindingAccountName.trim() || startLogin.isPending}
                      onClick={() => startLogin.mutate()}
                    >
                      {startLogin.isPending ? "正在打开" : "重新打开登录窗口"}
                    </button>
                    <button
                      type="button"
                      className="button primary"
                      disabled={!bindingAccountName.trim() || confirmBinding.isPending}
                      onClick={() => confirmBinding.mutate()}
                    >
                      {confirmBinding.isPending ? "保存中" : "确认已登录并绑定"}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ) : null}
        </div>
      </section>
    </section>
  );
}
