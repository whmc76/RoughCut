import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import { classNames } from "../../utils";

type ConfigProfileSwitcherProps = {
  title?: string;
  description?: string;
  compact?: boolean;
  className?: string;
};

export function ConfigProfileSwitcher({
  title = "配置方案",
  description = "把当前数字人、包装、风格和增强模式组合保存为方案，并在这里一键切换。",
  compact = false,
  className,
}: ConfigProfileSwitcherProps) {
  const queryClient = useQueryClient();
  const [draftName, setDraftName] = useState("");
  const lastHydratedProfileRef = useRef<{ id: string; name: string } | null>(null);

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
    mutationFn: (name: string) => api.createConfigProfile(name),
    onSuccess: async () => {
      setDraftName("");
      await invalidateRelatedQueries();
    },
  });

  const updateProfile = useMutation({
    mutationFn: (payload: { profileId: string; name?: string; capture_current?: boolean }) =>
      api.updateConfigProfile(payload.profileId, {
        name: payload.name,
        capture_current: payload.capture_current,
      }),
    onSuccess: async () => {
      setDraftName("");
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
      !draftName.trim()
      || (previousHydrated
        && draftName.trim() === previousHydrated.name
        && previousHydrated.id !== activeProfile.id);

    if (shouldHydrate) {
      setDraftName(activeProfile.name);
    }
    lastHydratedProfileRef.current = { id: activeProfile.id, name: activeProfile.name };
  }, [activeProfile, draftName]);

  const pending =
    activateProfile.isPending
    || createProfile.isPending
    || updateProfile.isPending
    || deleteProfile.isPending;

  const normalizedName = draftName.trim();
  const canCreate = Boolean(normalizedName);
  const canRename = Boolean(activeProfile && normalizedName && normalizedName !== activeProfile.name);
  const activeSummary = activeProfile ? formatProfileSummary(activeProfile) : "还没有保存过方案，先把当前组合保存下来。";

  return (
    <section className={classNames("config-profile-switcher", compact ? "compact" : "", className)}>
      <div className="config-profile-head">
        <div>
          <div className="stat-label">{title}</div>
          <div className="muted compact-top">{description}</div>
        </div>
        {profiles.data?.active_profile_dirty ? (
          <span className="status-pill failed">当前方案已改动</span>
        ) : activeProfile ? (
          <span className="status-pill done">已激活 {activeProfile.name}</span>
        ) : (
          <span className="status-pill pending">未激活方案</span>
        )}
      </div>

      <div className="config-profile-chip-list top-gap">
        {profiles.data?.profiles.map((profile) => (
          <button
            key={profile.id}
            className={classNames(
              "button ghost button-sm config-profile-chip",
              profile.is_active && "active",
            )}
            disabled={pending}
            onClick={() => activateProfile.mutate(profile.id)}
            title={formatProfileSummary(profile)}
          >
            <span>{profile.name}</span>
            {profile.is_dirty ? <span className="config-profile-chip-mark">未保存</span> : null}
          </button>
        ))}
        {!profiles.data?.profiles.length ? <span className="muted">暂无方案</span> : null}
      </div>

      <div className="notice top-gap">
        <div>{activeSummary}</div>
        {activeProfile ? (
          <div className="muted compact-top">
            更新时间 {new Date(activeProfile.updated_at).toLocaleString()}
          </div>
        ) : null}
      </div>

      <div className="toolbar top-gap">
        <input
          className="input config-profile-name-input"
          value={draftName}
          onChange={(event) => setDraftName(event.target.value)}
          placeholder="输入方案名称，例如：评测口播增强"
        />
        <button
          className="button primary"
          disabled={!canCreate || pending}
          onClick={() => createProfile.mutate(normalizedName)}
        >
          保存为新方案
        </button>
        <button
          className="button ghost"
          disabled={!activeProfile || pending}
          onClick={() =>
            activeProfile
              && updateProfile.mutate({
                profileId: activeProfile.id,
                name: normalizedName || activeProfile.name,
                capture_current: true,
              })
          }
        >
          覆盖当前方案
        </button>
        <button
          className="button ghost"
          disabled={!canRename || pending}
          onClick={() =>
            activeProfile
              && updateProfile.mutate({
                profileId: activeProfile.id,
                name: normalizedName,
                capture_current: false,
              })
          }
        >
          重命名当前方案
        </button>
        <button
          className="button danger"
          disabled={!activeProfile || pending}
          onClick={() => {
            if (!activeProfile) return;
            if (!window.confirm(`确认删除方案“${activeProfile.name}”？`)) return;
            deleteProfile.mutate(activeProfile.id);
          }}
        >
          删除当前方案
        </button>
      </div>

      {profiles.isLoading ? <div className="muted compact-top">正在读取方案…</div> : null}
      {profiles.isError ? <div className="muted compact-top">{(profiles.error as Error).message}</div> : null}
      {mutationError ? <div className="muted compact-top">{mutationError}</div> : null}
    </section>
  );
}

function formatProfileSummary(profile: {
  workflow_mode: string;
  enhancement_modes: string[];
  copy_style: string;
  cover_style: string;
  title_style: string;
  subtitle_style: string;
  smart_effect_style: string;
  avatar_presenter_id: string;
  packaging_enabled: boolean;
  insert_pool_size: number;
  music_pool_size: number;
}) {
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
    `工作流 ${profile.workflow_mode}`,
    enhancementLabel,
    `文案 ${profile.copy_style}`,
    `封面 ${profile.cover_style}`,
    `标题 ${profile.title_style}`,
    `字幕 ${profile.subtitle_style}`,
    `特效 ${profile.smart_effect_style}`,
    avatarLabel,
    packagingLabel,
  ].join(" · ");
}
