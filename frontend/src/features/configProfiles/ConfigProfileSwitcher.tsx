import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { ConfigProfile } from "../../types";
import { classNames } from "../../utils";
import { getTranscriptionProviderLabel } from "../settings/helpers";
import { formatDirtyDetailValue, formatDirtyKeyLabel, formatDirtyValue, summarizeDirtyDetails } from "./diffPresentation";

type ConfigProfileSwitcherProps = {
  title?: string;
  description?: string;
  compact?: boolean;
  className?: string;
};

const RECENT_PROFILE_SECTION_SIZE = 3;

export function ConfigProfileSwitcher({
  title = "方案",
  description = "切换这里，新任务就会按这套方案创建。",
  compact = false,
  className,
}: ConfigProfileSwitcherProps) {
  const queryClient = useQueryClient();
  const [draftName, setDraftName] = useState("");
  const [draftDescription, setDraftDescription] = useState("");
  const [listQuery, setListQuery] = useState("");
  const [listSort, setListSort] = useState<"updated_desc" | "name_asc">("updated_desc");
  const [previewProfileId, setPreviewProfileId] = useState<string | null>(null);
  const [compareProfileId, setCompareProfileId] = useState<string | null>(null);
  const lastHydratedProfileRef = useRef<{ id: string; name: string; description: string } | null>(null);

  const profiles = useQuery({
    queryKey: ["config-profiles"],
    queryFn: api.getConfigProfiles,
  });

  const invalidateRelatedQueries = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["config-profiles"] }),
      queryClient.invalidateQueries({ queryKey: ["config"] }),
      queryClient.invalidateQueries({ queryKey: ["packaging"] }),
    ]);
  };

  const activateProfile = useMutation({
    mutationFn: (profileId: string) => api.activateConfigProfile(profileId),
    onSuccess: async () => {
      await invalidateRelatedQueries();
    },
  });

  const createProfile = useMutation({
    mutationFn: (payload: { name: string; description: string }) => api.createConfigProfile(payload.name, payload.description),
    onSuccess: async () => {
      setDraftName("");
      setDraftDescription("");
      await invalidateRelatedQueries();
    },
  });

  const updateProfile = useMutation({
    mutationFn: (payload: { profileId: string; name?: string; description?: string; capture_current?: boolean }) =>
      api.updateConfigProfile(payload.profileId, {
        name: payload.name,
        description: payload.description,
        capture_current: payload.capture_current,
      }),
    onSuccess: async () => {
      setDraftName("");
      setDraftDescription("");
      await invalidateRelatedQueries();
    },
  });

  const deleteProfile = useMutation({
    mutationFn: (profileId: string) => api.deleteConfigProfile(profileId),
    onSuccess: async () => {
      setDraftName("");
      await invalidateRelatedQueries();
    },
  });

  const activeProfile = useMemo(
    () => profiles.data?.profiles.find((profile) => profile.is_active) ?? null,
    [profiles.data?.profiles],
  );

  const mutationError =
    (activateProfile.error as Error | null)?.message
    ?? (createProfile.error as Error | null)?.message
    ?? (updateProfile.error as Error | null)?.message
    ?? (deleteProfile.error as Error | null)?.message
    ?? "";

  useEffect(() => {
    if (!activeProfile) return;
    const previousHydrated = lastHydratedProfileRef.current;
    const shouldHydrate =
      !previousHydrated
      || previousHydrated.id !== activeProfile.id
      || (!draftName.trim() && !draftDescription.trim());

    if (shouldHydrate) {
      setDraftName(activeProfile.name);
      setDraftDescription(activeProfile.description || "");
    }
    lastHydratedProfileRef.current = {
      id: activeProfile.id,
      name: activeProfile.name,
      description: activeProfile.description || "",
    };
  }, [activeProfile, draftDescription, draftName]);

  const pending =
    activateProfile.isPending
    || createProfile.isPending
    || updateProfile.isPending
    || deleteProfile.isPending;

  const existingProfiles = profiles.data?.profiles ?? [];
  const normalizedName = draftName.trim();
  const normalizedDescription = draftDescription.trim();
  const normalizedListQuery = listQuery.trim().toLowerCase();
  const nameValidation = buildNameValidation(normalizedName, activeProfile, existingProfiles);
  const descriptionValidation = buildDescriptionValidation(normalizedDescription);
  const canCreate = nameValidation.canCreate;
  const canUpdateProfileMeta = Boolean(
    activeProfile
    && nameValidation.canRename
    && descriptionValidation.valid
    && (
      normalizedName !== activeProfile.name
      || normalizedDescription !== (activeProfile.description || "")
    ),
  );
  const activeSummaryGroups = activeProfile ? buildProfileSummaryGroups(activeProfile) : [];
  const visibleProfiles = useMemo(() => {
    const filtered = existingProfiles.filter((profile) => {
      if (profile.is_active) return true;
      if (!normalizedListQuery) return true;
      const haystack = `${profile.name} ${profile.description || ""}`.toLowerCase();
      return haystack.includes(normalizedListQuery);
    });
    return sortProfiles(filtered, listSort);
  }, [existingProfiles, listSort, normalizedListQuery]);
  const profileSections = useMemo(() => buildProfileSections(visibleProfiles, listSort), [listSort, visibleProfiles]);
  const activePreviewProfileId = compareProfileId || previewProfileId;
  const previewProfile = useMemo(
    () => existingProfiles.find((profile) => profile.id === activePreviewProfileId && profile.id !== activeProfile?.id) ?? null,
    [activePreviewProfileId, activeProfile?.id, existingProfiles],
  );
  const previewSummaryGroups = previewProfile ? buildProfileSummaryGroups(previewProfile) : [];
  const previewComparisonDetails = useMemo(
    () => (activeProfile && previewProfile ? buildProfileComparisonDetails(activeProfile, previewProfile) : []),
    [activeProfile, previewProfile],
  );
  const previewLocked = Boolean(compareProfileId && previewProfile && compareProfileId === previewProfile.id);
  const dirtyKeyLabels = profiles.data?.active_profile_dirty_keys.map(formatDirtyKeyLabel) ?? [];
  const dirtyDetails = profiles.data?.active_profile_dirty_details ?? [];
  const overwriteConfirmMessage = activeProfile
    ? buildOverwriteConfirmMessage(activeProfile.name, dirtyDetails)
    : "";
  const activateConfirmMessage = activeProfile
    ? buildActivateConfirmMessage(activeProfile.name, dirtyDetails)
    : "";
  const deleteConfirmMessage = activeProfile
    ? buildDeleteConfirmMessage(activeProfile.name, dirtyDetails)
    : "";

  useEffect(() => {
    if (!compareProfileId) return;
    const compareProfile = existingProfiles.find((profile) => profile.id === compareProfileId);
    if (!compareProfile || compareProfile.is_active) {
      setCompareProfileId(null);
    }
  }, [compareProfileId, existingProfiles]);

  return (
    <section className={classNames("config-profile-switcher", compact ? "compact" : "", className)}>
      <div className="config-profile-head">
        <div>
          <div className="stat-label">{title}</div>
          <div className="muted compact-top">{description}</div>
        </div>
        {profiles.data?.active_profile_dirty ? (
          <span className="status-pill failed">
            有未保存变更{dirtyKeyLabels.length ? ` (${dirtyKeyLabels.length})` : ""}
          </span>
        ) : activeProfile ? (
          <span className="status-pill done">当前 {activeProfile.name}</span>
        ) : (
          <span className="status-pill pending">还没有方案</span>
        )}
      </div>

      <div className="config-profile-list-toolbar top-gap">
        <input
          className="input config-profile-filter-input"
          value={listQuery}
          onChange={(event) => setListQuery(event.target.value)}
          placeholder="筛选方案"
        />
        <select
          className="input config-profile-sort-select"
          value={listSort}
          onChange={(event) => setListSort(event.target.value as "updated_desc" | "name_asc")}
        >
          <option value="updated_desc">最近改动</option>
          <option value="name_asc">按名称排序</option>
        </select>
      </div>

      <div className="config-profile-list-stack top-gap">
        {!profiles.data?.profiles.length ? <span className="muted">还没有保存的方案</span> : null}
        {profiles.data?.profiles.length && !visibleProfiles.length ? <span className="muted">没有找到匹配方案</span> : null}
        {profileSections.map((section) => (
          <section key={section.key} className="config-profile-list-section">
            <div className="config-profile-list-section-head">
              <div className="stat-label">{section.label}</div>
              <div className="muted">{section.description}</div>
            </div>
            <div className="config-profile-chip-list">
              {section.profiles.map((profile) => (
                <article
                  key={profile.id}
                  className={classNames(
                    "config-profile-chip",
                    profile.is_active && "active",
                  )}
                >
                  <button
                    className="config-profile-chip-button"
                    disabled={pending}
                    onMouseEnter={() => {
                      if (!compareProfileId) {
                        setPreviewProfileId(profile.id);
                      }
                    }}
                    onMouseLeave={() => {
                      if (!compareProfileId) {
                        setPreviewProfileId((current) => (current === profile.id ? null : current));
                      }
                    }}
                    onFocus={() => {
                      if (!compareProfileId) {
                        setPreviewProfileId(profile.id);
                      }
                    }}
                    onBlur={() => {
                      if (!compareProfileId) {
                        setPreviewProfileId((current) => (current === profile.id ? null : current));
                      }
                    }}
                    onClick={() => {
                      if (profile.is_active) return;
                      if (profiles.data?.active_profile_dirty && dirtyDetails.length && !window.confirm(activateConfirmMessage.replace("{target}", profile.name))) {
                        return;
                      }
                      activateProfile.mutate(profile.id);
                    }}
                    title={formatProfileSummary(profile)}
                  >
                    <div className="config-profile-chip-copy">
                      <div className="config-profile-chip-head">
                        <span className="config-profile-chip-title">{profile.name}</span>
                        {profile.is_dirty ? <span className="config-profile-chip-mark">未保存</span> : null}
                      </div>
                      {profile.description ? <div className="config-profile-chip-description">{profile.description}</div> : null}
                      <div className="config-profile-chip-meta">
                        更新于 {formatProfileUpdatedLabel(profile.updated_at)}
                      </div>
                    </div>
                  </button>
                  <div className="config-profile-chip-actions">
                    {profile.is_active ? (
                      <span className="status-pill done">正在使用</span>
                    ) : (
                      <button
                        className="button ghost button-sm"
                        disabled={pending}
                        onClick={() => {
                          setCompareProfileId((current) => (current === profile.id ? null : profile.id));
                          setPreviewProfileId(profile.id);
                        }}
                      >
                        {compareProfileId === profile.id ? "关闭对比" : "查看差异"}
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
      {previewProfile ? (
        <div className="config-profile-preview notice top-gap">
          <div className="config-profile-preview-head">
            <div>
              <div className="stat-label">{previewLocked ? "方案差异" : "预览"}</div>
              <div className="muted compact-top">
                {previewLocked
                  ? `正在和“${previewProfile.name}”做对比。`
                  : `这里显示“${previewProfile.name}”的关键设置。`}
              </div>
              {previewProfile.description ? <div className="muted compact-top">{previewProfile.description}</div> : null}
            </div>
            <div className="config-profile-preview-actions">
              <span className={classNames("status-pill", previewLocked ? "processing" : "pending")}>
                {previewLocked ? "对比中" : "未启用"}
              </span>
              {previewLocked ? (
                <button
                  className="button ghost button-sm"
                  onClick={() => setCompareProfileId(null)}
                >
                  关闭对比
                </button>
              ) : null}
            </div>
          </div>
          <div className="config-profile-summary-grid compact-top">
            {previewSummaryGroups.map((group) => (
              <article key={`${previewProfile.id}-${group.label}`} className="config-profile-summary-card">
                <div className="stat-label">{group.label}</div>
                <div className="config-profile-summary-tags compact-top">
                  {group.items.map((item) => (
                    <span key={`${previewProfile.id}-${group.label}-${item}`} className="status-pill config-profile-summary-tag">
                      {item}
                    </span>
                  ))}
                </div>
              </article>
            ))}
          </div>
          {activeProfile ? (
            <div className="notice compact-top">
              <div>
                和当前方案“{activeProfile.name}”相比，
                {previewComparisonDetails.length ? `有 ${previewComparisonDetails.length} 处差异。` : "没有关键差异。"}
              </div>
              {previewComparisonDetails.length ? (
                <div className="config-profile-diff-list compact-top">
                  {previewComparisonDetails.slice(0, 6).map((item) => (
                    <div key={`${previewProfile.id}-${item.key}`} className="config-profile-diff-row">
                        <span className="status-pill pending config-profile-summary-tag">{item.label}</span>
                        <div className="muted">
                        {formatDirtyDetailValue(item.key, item.active_value)} -&gt; {formatDirtyDetailValue(item.key, item.preview_value)}
                        </div>
                      </div>
                  ))}
                  {previewComparisonDetails.length > 6 ? (
                    <div className="muted">
                      另外还有 {previewComparisonDetails.length - 6} 处差异。
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="notice top-gap">
        {activeProfile ? (
          <>
            {activeProfile.description ? <div className="muted compact-bottom">{activeProfile.description}</div> : null}
            {profiles.data?.active_profile_dirty ? (
              <>
                <div>当前设置和已保存方案不一致，切换前先看这些差异。</div>
                {dirtyDetails.length ? (
                  <div className="config-profile-diff-list compact-top">
                    {dirtyDetails.map((item) => (
                      <div key={item.key} className="config-profile-diff-row">
                        <span className="status-pill failed config-profile-summary-tag">
                          {formatDirtyKeyLabel(item.key)}
                        </span>
                        <div className="muted">
                          {formatDirtyDetailValue(item.key, item.saved_value)} -&gt; {formatDirtyDetailValue(item.key, item.current_value)}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="config-profile-diff-tags compact-top">
                    {dirtyKeyLabels.map((item) => (
                      <span key={item} className="status-pill failed config-profile-summary-tag">
                        {item}
                      </span>
                    ))}
                  </div>
                )}
              </>
            ) : null}
            <div>当前方案包含模型、审核、包装和风格设置。</div>
            <div className="config-profile-summary-grid compact-top">
              {activeSummaryGroups.map((group) => (
                <article key={group.label} className="config-profile-summary-card">
                  <div className="stat-label">{group.label}</div>
                  <div className="config-profile-summary-tags compact-top">
                    {group.items.map((item) => (
                      <span key={item} className="status-pill config-profile-summary-tag">
                        {item}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
            </div>
            <div className="muted compact-top">
              更新于 {new Date(activeProfile.updated_at).toLocaleString()}
            </div>
          </>
        ) : (
          <div>先把当前组合保存成一套方案。</div>
        )}
      </div>

      <div className="toolbar top-gap">
        <input
          className="input config-profile-name-input"
          value={draftName}
          onChange={(event) => setDraftName(event.target.value)}
          placeholder="方案名称，例如：评测口播"
        />
        <input
          className="input config-profile-description-input"
          value={draftDescription}
          onChange={(event) => setDraftDescription(event.target.value)}
          placeholder="补充用途，例如：适合测评口播和数字人解说"
        />
        <button
          className="button primary"
          disabled={!canCreate || !descriptionValidation.valid || pending}
          onClick={() => createProfile.mutate({ name: normalizedName, description: normalizedDescription })}
        >
          保存为新方案
        </button>
        <button
          className="button ghost"
          disabled={!activeProfile || pending}
          title={dirtyDetails.length ? `把当前 ${dirtyDetails.length} 项差异写回方案` : "用当前设置覆盖这个方案"}
          onClick={() => {
            if (!activeProfile) return;
            if (dirtyDetails.length && !window.confirm(overwriteConfirmMessage)) return;
            updateProfile.mutate({
              profileId: activeProfile.id,
              name: normalizedName || activeProfile.name,
              description: normalizedDescription,
              capture_current: true,
            });
          }}
        >
          覆盖当前方案
        </button>
        <button
          className="button ghost"
          disabled={!canUpdateProfileMeta || pending}
          onClick={() =>
            activeProfile
              && updateProfile.mutate({
                profileId: activeProfile.id,
                name: normalizedName,
                description: normalizedDescription,
                capture_current: false,
              })
          }
        >
          更新方案说明
        </button>
        <button
          className="button danger"
          disabled={!activeProfile || pending}
          title={activeProfile ? `删除后将失去“${activeProfile.name}”这套方案快照` : "删除当前方案"}
          onClick={() => {
            if (!activeProfile) return;
            if (!window.confirm(deleteConfirmMessage)) return;
            deleteProfile.mutate(activeProfile.id);
          }}
        >
          删除方案
        </button>
      </div>
      {activeProfile && dirtyDetails.length ? (
        <div className="muted compact-top">
          覆盖会把这 {dirtyDetails.length} 项差异写回“{activeProfile.name}”。
        </div>
      ) : null}
      <div className={classNames("compact-top", nameValidation.tone === "warning" ? "notice" : "muted")}>
        {nameValidation.message}
      </div>
      <div className={classNames("compact-top", descriptionValidation.valid ? "muted" : "notice")}>
        {descriptionValidation.message}
      </div>
      {activeProfile ? (
        <div className="muted compact-top">
          删除后会移除“{activeProfile.name}”这套方案，但当前设置不会立刻丢失。
        </div>
      ) : null}

      {profiles.isLoading ? <div className="muted compact-top">正在读取方案…</div> : null}
      {profiles.isError ? <div className="muted compact-top">{(profiles.error as Error).message}</div> : null}
      {mutationError ? <div className="muted compact-top">{mutationError}</div> : null}
    </section>
  );
}

function formatProfileSummary(profile: ConfigProfile) {
  const enhancementLabel = profile.enhancement_modes.length
    ? `增强 ${profile.enhancement_modes.length} 项`
    : "无增强";
  const avatarLabel = profile.avatar_presenter_id
    ? `数字人已绑定`
    : "数字人未绑定";
  const packagingLabel = profile.packaging_enabled
    ? `包装开 ${profile.insert_pool_size}/${profile.music_pool_size}`
    : "包装关闭";
  return [
    `${profile.llm_mode === "local" ? "本地" : "云端"}推理`,
    `转写 ${getTranscriptionProviderLabel(profile.transcription_provider)}`,
    `推理 ${profile.reasoning_provider}`,
    `工作流 ${profile.workflow_mode}`,
    enhancementLabel,
    profile.auto_confirm_content_profile ? `画像自动确认 ${profile.content_profile_review_threshold}` : "画像人工确认",
    profile.quality_auto_rerun_enabled ? `低分复跑 ${profile.quality_auto_rerun_below_score}` : "关闭复跑",
    `文案 ${profile.copy_style}`,
    `封面 ${profile.cover_style}`,
    `标题 ${profile.title_style}`,
    `字幕 ${profile.subtitle_style}`,
    `特效 ${profile.smart_effect_style}`,
    avatarLabel,
    packagingLabel,
  ].join(" · ");
}

function formatProfileUpdatedLabel(updatedAt: string) {
  const timestamp = Date.parse(updatedAt);
  if (Number.isNaN(timestamp)) return updatedAt;
  return new Date(timestamp).toLocaleString();
}

function sortProfiles(profiles: ConfigProfile[], sortMode: "updated_desc" | "name_asc") {
  return [...profiles].sort((left, right) => {
    if (left.is_active !== right.is_active) return left.is_active ? -1 : 1;
    if (sortMode === "name_asc") {
      return left.name.localeCompare(right.name, "zh-CN");
    }
    return Date.parse(right.updated_at) - Date.parse(left.updated_at);
  });
}

function buildProfileSections(
  profiles: ConfigProfile[],
  sortMode: "updated_desc" | "name_asc",
) {
  const active = profiles.filter((profile) => profile.is_active);
  const inactive = profiles.filter((profile) => !profile.is_active);
  const recentIds = new Set(
    [...inactive]
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))
      .slice(0, RECENT_PROFILE_SECTION_SIZE)
      .map((profile) => profile.id),
  );
  const recent = sortProfiles(
    inactive.filter((profile) => recentIds.has(profile.id)),
    sortMode,
  );
  const others = sortProfiles(
    inactive.filter((profile) => !recentIds.has(profile.id)),
    sortMode,
  );
  const sections: Array<{ key: string; label: string; description: string; profiles: ConfigProfile[] }> = [];

  if (active.length) {
    sections.push({
      key: "active",
      label: "当前方案",
      description: "正在使用。",
      profiles: active,
    });
  }
  if (recent.length) {
    sections.push({
      key: "recent",
      label: "最近更新",
      description: "最近改过的方案。",
      profiles: recent,
    });
  }
  if (others.length) {
    sections.push({
      key: "others",
      label: "其他方案",
      description: "其它可切换方案。",
      profiles: others,
    });
  }

  return sections;
}

function buildProfileComparisonDetails(activeProfile: ConfigProfile, previewProfile: ConfigProfile) {
  const comparisons = [
    {
      key: "llm_mode",
      label: "推理模式",
      active_value: activeProfile.llm_mode === "local" ? "本地" : "云端",
      preview_value: previewProfile.llm_mode === "local" ? "本地" : "云端",
    },
    {
      key: "transcription_provider",
      label: "转写 provider",
      active_value: getTranscriptionProviderLabel(activeProfile.transcription_provider),
      preview_value: getTranscriptionProviderLabel(previewProfile.transcription_provider),
    },
    {
      key: "transcription_model",
      label: "转写模型",
      active_value: activeProfile.transcription_model,
      preview_value: previewProfile.transcription_model,
    },
    {
      key: "transcription_dialect",
      label: "转写方言",
      active_value: activeProfile.transcription_dialect,
      preview_value: previewProfile.transcription_dialect,
    },
    {
      key: "reasoning_provider",
      label: "推理 provider",
      active_value: activeProfile.reasoning_provider,
      preview_value: previewProfile.reasoning_provider,
    },
    {
      key: "reasoning_model",
      label: "推理模型",
      active_value: activeProfile.reasoning_model,
      preview_value: previewProfile.reasoning_model,
    },
    {
      key: "workflow_mode",
      label: "工作流模式",
      active_value: activeProfile.workflow_mode,
      preview_value: previewProfile.workflow_mode,
    },
    {
      key: "enhancement_modes",
      label: "增强模式",
      active_value: activeProfile.enhancement_modes,
      preview_value: previewProfile.enhancement_modes,
    },
    {
      key: "auto_confirm_content_profile",
      label: "画像自动确认",
      active_value: activeProfile.auto_confirm_content_profile,
      preview_value: previewProfile.auto_confirm_content_profile,
    },
    {
      key: "content_profile_review_threshold",
      label: "画像审核阈值",
      active_value: activeProfile.content_profile_review_threshold,
      preview_value: previewProfile.content_profile_review_threshold,
    },
    {
      key: "quality_auto_rerun_enabled",
      label: "低分自动复跑",
      active_value: activeProfile.quality_auto_rerun_enabled,
      preview_value: previewProfile.quality_auto_rerun_enabled,
    },
    {
      key: "quality_auto_rerun_below_score",
      label: "复跑分数线",
      active_value: activeProfile.quality_auto_rerun_below_score,
      preview_value: previewProfile.quality_auto_rerun_below_score,
    },
    {
      key: "packaging_selection_min_score",
      label: "包装最低分",
      active_value: activeProfile.packaging_selection_min_score,
      preview_value: previewProfile.packaging_selection_min_score,
    },
    {
      key: "copy_style",
      label: "文案风格",
      active_value: activeProfile.copy_style,
      preview_value: previewProfile.copy_style,
    },
    {
      key: "cover_style",
      label: "封面风格",
      active_value: activeProfile.cover_style,
      preview_value: previewProfile.cover_style,
    },
    {
      key: "title_style",
      label: "标题风格",
      active_value: activeProfile.title_style,
      preview_value: previewProfile.title_style,
    },
    {
      key: "subtitle_style",
      label: "字幕风格",
      active_value: activeProfile.subtitle_style,
      preview_value: previewProfile.subtitle_style,
    },
    {
      key: "smart_effect_style",
      label: "特效风格",
      active_value: activeProfile.smart_effect_style,
      preview_value: previewProfile.smart_effect_style,
    },
    {
      key: "avatar_presenter_id",
      label: "数字人模板",
      active_value: activeProfile.avatar_presenter_id,
      preview_value: previewProfile.avatar_presenter_id,
    },
    {
      key: "packaging_enabled",
      label: "包装总开关",
      active_value: activeProfile.packaging_enabled,
      preview_value: previewProfile.packaging_enabled,
    },
    {
      key: "insert_pool_size",
      label: "插片素材池",
      active_value: activeProfile.insert_pool_size,
      preview_value: previewProfile.insert_pool_size,
    },
    {
      key: "music_pool_size",
      label: "音乐素材池",
      active_value: activeProfile.music_pool_size,
      preview_value: previewProfile.music_pool_size,
    },
  ];

  return comparisons.filter((item) => formatDirtyValue(item.active_value) !== formatDirtyValue(item.preview_value));
}

function buildProfileSummaryGroups(profile: ConfigProfile) {
  return [
    {
      label: "生产链路",
      items: [
        `${profile.llm_mode === "local" ? "本地" : "云端"}推理`,
        `转写 ${getTranscriptionProviderLabel(profile.transcription_provider)} / ${profile.transcription_model || "未设置"}`,
        `方言 ${profile.transcription_dialect || "默认"}`,
        `推理 ${profile.reasoning_provider} / ${profile.reasoning_model || "未设置"}`,
        `工作流 ${profile.workflow_mode}`,
        profile.enhancement_modes.length ? `增强 ${profile.enhancement_modes.length} 项` : "无增强",
      ],
    },
    {
      label: "审核阈值",
      items: [
        profile.auto_confirm_content_profile ? `画像自动确认 ${profile.content_profile_review_threshold}` : "画像人工确认",
        profile.quality_auto_rerun_enabled ? `低分复跑 ${profile.quality_auto_rerun_below_score}` : "关闭复跑",
        `包装最低分 ${profile.packaging_selection_min_score.toFixed(2)}`,
      ],
    },
    {
      label: "风格与绑定",
      items: [
        `文案 ${profile.copy_style}`,
        `封面 ${profile.cover_style}`,
        `标题 ${profile.title_style}`,
        `字幕 ${profile.subtitle_style}`,
        `特效 ${profile.smart_effect_style}`,
        profile.avatar_presenter_id ? "数字人已绑定" : "数字人未绑定",
        profile.packaging_enabled ? `包装开 ${profile.insert_pool_size}/${profile.music_pool_size}` : "包装关闭",
      ],
    },
  ];
}

function buildOverwriteConfirmMessage(profileName: string, dirtyDetails: Array<{ key: string; saved_value: unknown; current_value: unknown }>) {
  const preview = summarizeDirtyDetails(dirtyDetails.slice(0, 6));
  const omittedCount = Math.max(0, dirtyDetails.length - 6);
  return [
    `确认用当前运行配置覆盖剪辑配置“${profileName}”？`,
    "",
    preview || "当前没有检测到差异项。",
    omittedCount ? `另有 ${omittedCount} 项差异未展开。` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildActivateConfirmMessage(activeProfileName: string, dirtyDetails: Array<{ key: string; saved_value: unknown; current_value: unknown }>) {
  const preview = summarizeDirtyDetails(dirtyDetails.slice(0, 6));
  const omittedCount = Math.max(0, dirtyDetails.length - 6);
  return [
    `当前方案“${activeProfileName}”还有未保存改动，确认切换到“{target}”？`,
    "",
    "以下差异会被放弃：",
    preview || "当前没有检测到差异项。",
    omittedCount ? `另有 ${omittedCount} 项差异未展开。` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildDeleteConfirmMessage(profileName: string, dirtyDetails: Array<{ key: string; saved_value: unknown; current_value: unknown }>) {
  const preview = summarizeDirtyDetails(dirtyDetails.slice(0, 4));
  const omittedCount = Math.max(0, dirtyDetails.length - 4);
  return [
    `确认删除剪辑配置“${profileName}”？`,
    "",
    "删除后会失去这套方案快照和后续回滚点。",
    dirtyDetails.length ? "当前还存在未保存差异，删除后这些差异将无法再通过该方案找回：" : "",
    dirtyDetails.length ? preview : "",
    dirtyDetails.length && omittedCount ? `另有 ${omittedCount} 项差异未展开。` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildNameValidation(
  normalizedName: string,
  activeProfile: ConfigProfile | null,
  profiles: ConfigProfile[],
) {
  const duplicateProfile = profiles.find((profile) => profile.name === normalizedName && profile.id !== activeProfile?.id);
  const duplicateAnyProfile = profiles.find((profile) => profile.name === normalizedName);
  const tooLong = normalizedName.length > 60;
  const unchanged = Boolean(activeProfile && normalizedName && normalizedName === activeProfile.name);

  if (!normalizedName) {
    return {
      canCreate: false,
      canRename: false,
      tone: "info" as const,
      message: "名称建议 1-60 个字符，例如“评测口播增强”。",
    };
  }
  if (tooLong) {
    return {
      canCreate: false,
      canRename: false,
      tone: "warning" as const,
      message: "方案名称最多 60 个字符。",
    };
  }
  if (duplicateProfile || (duplicateAnyProfile && !activeProfile)) {
    return {
      canCreate: false,
      canRename: false,
      tone: "warning" as const,
      message: `已存在同名方案“${normalizedName}”。`,
    };
  }
  if (unchanged) {
    return {
      canCreate: false,
      canRename: Boolean(activeProfile),
      tone: "info" as const,
      message: "名称没变；如果只是想保存当前差异，请用“覆盖当前方案”。",
    };
  }
  return {
    canCreate: true,
    canRename: Boolean(activeProfile),
    tone: "info" as const,
    message: activeProfile
      ? "名称可用；可以新建，也可以更新当前方案。"
      : "名称可用；可以直接保存。",
  };
}

function buildDescriptionValidation(normalizedDescription: string) {
  if (normalizedDescription.length > 160) {
    return {
      valid: false,
      message: "方案备注最多 160 个字符。",
    };
  }
  return {
    valid: true,
    message: normalizedDescription
      ? "备注会和方案一起保存。"
      : "备注可选。",
  };
}
