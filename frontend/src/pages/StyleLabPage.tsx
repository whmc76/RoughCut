import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { useStyleTemplatesWorkspace } from "../features/styleTemplates/useStyleTemplatesWorkspace";
import type { AvatarMaterialProfile, CreativeModeDefinition } from "../types";
import {
  copyStylePresets,
  coverStylePresets,
  findStylePreset,
  smartEffectPresets,
  subtitleStylePresets,
  titleStylePresets,
} from "../stylePresets";
import { classNames } from "../utils";

export function StyleLabPage() {
  const queryClient = useQueryClient();
  const styleWorkspace = useStyleTemplatesWorkspace();
  const options = useQuery({ queryKey: ["config-options", "style-lab"], queryFn: api.getConfigOptions });
  const config = useQuery({ queryKey: ["config", "style-lab"], queryFn: api.getConfig });
  const avatarMaterials = useQuery({ queryKey: ["avatar-materials", "style-lab"], queryFn: api.getAvatarMaterials });
  const saveConfig = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patchConfig(body),
    onSuccess: (data) => {
      queryClient.setQueryData(["config", "style-lab"], data);
      queryClient.setQueryData(["config"], data);
      void queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  const packaging = styleWorkspace.packaging.data?.config;
  const catalog = options.data?.creative_mode_catalog;
  const activeEnhancementModes = config.data?.default_job_enhancement_modes ?? [];
  const activePresenterId = String(config.data?.avatar_presenter_id ?? "");
  const presenterProfiles = avatarMaterials.data?.profiles ?? [];

  const selectedSubtitle = findStylePreset(subtitleStylePresets, packaging?.subtitle_style ?? "");
  const selectedTitle = findStylePreset(titleStylePresets, packaging?.title_style ?? "");
  const selectedCopy = findStylePreset(copyStylePresets, packaging?.copy_style ?? "");
  const selectedCover = findStylePreset(coverStylePresets, packaging?.cover_style ?? "");
  const selectedEffect = findStylePreset(smartEffectPresets, packaging?.smart_effect_style ?? "");
  const activePresenter = presenterProfiles.find((profile) => getPresenterFilePath(profile) === activePresenterId);
  const activePresenterLabel = activePresenter?.display_name ?? (activePresenterId || "未绑定");

  const toggleEnhancementMode = (modeKey: string) => {
    const nextModes = activeEnhancementModes.includes(modeKey)
      ? activeEnhancementModes.filter((item) => item !== modeKey)
      : [...activeEnhancementModes, modeKey];
    saveConfig.mutate({ default_job_enhancement_modes: nextModes });
  };

  const selectWorkflowMode = (modeKey: string) => {
    if (config.data?.default_job_workflow_mode === modeKey) return;
    saveConfig.mutate({ default_job_workflow_mode: modeKey });
  };

  const selectPresenter = (profile: AvatarMaterialProfile) => {
    const presenterPath = getPresenterFilePath(profile);
    if (!presenterPath || presenterPath === activePresenterId) return;
    saveConfig.mutate({ avatar_presenter_id: presenterPath });
  };

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow="风格实验"
        title="风格实验"
        description="先定字幕、标题、文案、封面，再收紧增强和角色默认值。"
        actions={
          <div className="toolbar">
            <Link className="button ghost" to="/style-templates">
              旧风格页
            </Link>
            <Link className="button ghost" to="/creator-profiles">
              档案库
            </Link>
          </div>
        }
      />

      {styleWorkspace.packaging.isLoading || options.isLoading || config.isLoading || avatarMaterials.isLoading ? (
        <section className="panel">正在加载风格实验面板…</section>
      ) : null}

      {packaging && catalog && config.data ? (
        <>
          <PageSection
            eyebrow="当前方向"
            title="把默认值收紧到一屏内"
            description="现在的主成片默认值、增强项和角色默认会在这里集中显示。"
          >
            <section className="panel">
              <div className="toolbar" style={{ flexWrap: "wrap" }}>
                <StatusChip label="字幕" value={selectedSubtitle?.label ?? packaging.subtitle_style} />
                <StatusChip label="标题" value={selectedTitle?.label ?? packaging.title_style} />
                <StatusChip label="文案" value={selectedCopy?.label ?? packaging.copy_style} />
                <StatusChip label="封面" value={selectedCover?.label ?? packaging.cover_style} />
                <StatusChip label="特效" value={selectedEffect?.label ?? packaging.smart_effect_style} />
                <StatusChip label="增强" value={String(activeEnhancementModes.length)} />
                <StatusChip label="角色" value={activePresenterLabel} />
              </div>
            </section>
          </PageSection>

          <PageSection eyebrow="主风格" title="字幕、标题、文案、封面" description="每个分区只保留当前默认值和可选预设。">
            <div className="list-stack">
              <PresetRail
                title="字幕"
                currentKey={packaging.subtitle_style}
                currentLabel={selectedSubtitle?.label ?? packaging.subtitle_style}
                currentSummary={selectedSubtitle?.summary}
                presets={subtitleStylePresets}
                onSelect={(value) => styleWorkspace.saveConfig.mutate({ subtitle_style: value })}
                busy={styleWorkspace.saveConfig.isPending}
              />
              <PresetRail
                title="标题"
                currentKey={packaging.title_style}
                currentLabel={selectedTitle?.label ?? packaging.title_style}
                currentSummary={selectedTitle?.summary}
                presets={titleStylePresets}
                onSelect={(value) => styleWorkspace.saveConfig.mutate({ title_style: value })}
                busy={styleWorkspace.saveConfig.isPending}
              />
              <PresetRail
                title="文案"
                currentKey={packaging.copy_style}
                currentLabel={selectedCopy?.label ?? packaging.copy_style}
                currentSummary={selectedCopy?.summary}
                presets={copyStylePresets}
                onSelect={(value) => styleWorkspace.saveConfig.mutate({ copy_style: value })}
                busy={styleWorkspace.saveConfig.isPending}
              />
              <PresetRail
                title="封面"
                currentKey={packaging.cover_style}
                currentLabel={selectedCover?.label ?? packaging.cover_style}
                currentSummary={selectedCover?.summary}
                presets={coverStylePresets}
                onSelect={(value) => styleWorkspace.saveConfig.mutate({ cover_style: value })}
                busy={styleWorkspace.saveConfig.isPending}
              />
              <PresetRail
                title="智能特效"
                currentKey={packaging.smart_effect_style}
                currentLabel={selectedEffect?.label ?? packaging.smart_effect_style}
                currentSummary={selectedEffect?.summary}
                presets={smartEffectPresets}
                onSelect={(value) => styleWorkspace.saveConfig.mutate({ smart_effect_style: value })}
                busy={styleWorkspace.saveConfig.isPending}
              />
            </div>
          </PageSection>

          <PageSection eyebrow="创作模式" title="主流程和增强项" description="主流程只选一个，增强项只保留常用项。">
            <div className="preset-grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
              <section className="panel" style={{ minHeight: 0 }}>
                <div className="toolbar">
                  <strong>主流程</strong>
                  <span className="status-pill">{config.data.default_job_workflow_mode}</span>
                </div>
                <div className="list-stack compact-top">
                  {catalog.workflow_modes.map((mode) => (
                    <CreativeModeTile
                      key={mode.key}
                      mode={mode}
                      active={config.data.default_job_workflow_mode === mode.key}
                      onClick={() => selectWorkflowMode(mode.key)}
                    />
                  ))}
                </div>
              </section>

              <section className="panel" style={{ minHeight: 0 }}>
                <div className="toolbar">
                  <strong>增强</strong>
                  <span className="status-pill">{activeEnhancementModes.length} active</span>
                </div>
                <div className="list-stack compact-top">
                  {catalog.enhancement_modes.map((mode) => (
                    <CreativeModeTile
                      key={mode.key}
                      mode={mode}
                      active={activeEnhancementModes.includes(mode.key)}
                      onClick={() => toggleEnhancementMode(mode.key)}
                      toggleLabel={activeEnhancementModes.includes(mode.key) ? "移除" : "激活"}
                    />
                  ))}
                </div>
              </section>
            </div>
          </PageSection>

          <PageSection
            eyebrow="创作者默认"
            title="角色和画中预览"
            description="只保留能直接影响出片的角色默认值。"
            actions={<Link className="button ghost" to="/creator-profiles">打开档案库</Link>}
          >
            <section className="panel">
              <div className="toolbar" style={{ flexWrap: "wrap" }}>
                <StatusChip label="当前角色" value={activePresenterLabel} />
                <StatusChip label="可用档案" value={String(presenterProfiles.length)} />
                <StatusChip label="已就绪" value={String(presenterProfiles.filter((profile) => getPresenterFilePath(profile)).length)} />
              </div>
              <div className="list-stack top-gap">
                {presenterProfiles.length ? (
                  presenterProfiles.slice(0, 6).map((profile) => {
                    const presenterPath = getPresenterFilePath(profile);
                    const isActive = presenterPath === activePresenterId;
                    const ready = Boolean(presenterPath);
                    return (
                      <button
                        key={profile.id}
                        type="button"
                        className={classNames("mode-card", isActive && "selected")}
                        disabled={!ready || saveConfig.isPending}
                        onClick={() => selectPresenter(profile)}
                      >
                        <div className="mode-card-header">
                          <div>
                            <strong>{profile.display_name}</strong>
                            <div className="muted compact-top">
                              {profile.creator_profile?.identity?.public_name || profile.presenter_alias || "未命名"} · {profile.training_status}
                            </div>
                          </div>
                          <span className={`mode-chip ${isActive ? "" : ready ? "" : "planned"}`}>
                            {isActive ? "已激活" : ready ? "可激活" : "缺素材"}
                          </span>
                        </div>
                        <p className="muted">{profile.next_action}</p>
                        <div className="mode-chip-list">
                          {(profile.creator_profile?.positioning?.expertise ?? []).slice(0, 2).map((item) => (
                            <span key={item} className="mode-chip subtle">
                              {item}
                            </span>
                          ))}
                          {profile.creator_profile?.publishing?.primary_platform ? (
                            <span className="mode-chip subtle">{profile.creator_profile.publishing.primary_platform}</span>
                          ) : null}
                        </div>
                      </button>
                    );
                  })
                ) : (
                  <div className="empty-state">还没有创作者档案。</div>
                )}
              </div>
            </section>
          </PageSection>
        </>
      ) : null}
    </section>
  );
}

function PresetRail({
  title,
  currentKey,
  currentLabel,
  currentSummary,
  presets,
  onSelect,
  busy,
}: {
  title: string;
  currentKey: string;
  currentLabel: string;
  currentSummary?: string;
  presets: Array<{ key: string; label: string; summary: string; badge: string; groupId: string }>;
  onSelect: (value: string) => void;
  busy: boolean;
}) {
  return (
    <section className="panel" style={{ minHeight: 0 }}>
      <div className="toolbar" style={{ flexWrap: "wrap" }}>
        <strong>{title}</strong>
        <span className="status-pill done">{currentLabel}</span>
      </div>
      {currentSummary ? <div className="muted compact-top">{currentSummary}</div> : null}
      <div className="mode-chip-list top-gap">
        {presets.map((preset) => (
          <button
            key={preset.key}
            type="button"
            className={classNames("mode-chip", "subtle", preset.key === currentKey && "selected")}
            disabled={busy}
            onClick={() => onSelect(preset.key)}
          >
            {preset.label}
          </button>
        ))}
      </div>
    </section>
  );
}

function CreativeModeTile({
  mode,
  active,
  onClick,
  toggleLabel = "激活",
}: {
  mode: CreativeModeDefinition;
  active: boolean;
  onClick: () => void;
  toggleLabel?: string;
}) {
  return (
    <article className={classNames("mode-card", active && "selected")}>
      <div className="mode-card-header">
        <div>
          <strong>{mode.title}</strong>
          <div className="muted compact-top">{mode.tagline}</div>
        </div>
        <button className={active ? "button primary" : "button ghost"} type="button" onClick={onClick}>
          {active ? "已选中" : toggleLabel}
        </button>
      </div>
      <p className="muted">{mode.summary}</p>
      <div className="mode-chip-list compact-top">
        {mode.suitable_for.slice(0, 3).map((item) => (
          <span key={item} className="mode-chip subtle">
            {item}
          </span>
        ))}
      </div>
      <div className="muted compact-top">{describeModeOutput(mode)}</div>
    </article>
  );
}

function StatusChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="status-pill">
      {label}: {value}
    </span>
  );
}

function describeModeOutput(mode: CreativeModeDefinition): string {
  if (mode.kind === "workflow") {
    if (mode.key === "standard_edit") return "直接输出主成片。";
    if (mode.key === "long_text_to_video") return "规划中，当前还没有实际输出。";
    return "按工作流直接产出主输出。";
  }

  if (mode.key === "avatar_commentary") return "叠加到主成片，可形成含数字人的增强版输出。";
  if (mode.key === "ai_director") return "改写解说与配音后回写主流程，影响主成片输出。";
  if (mode.key === "multilingual_translation") return "当前产出字幕翻译等辅助产物，不单独导出新成片。";
  if (mode.key === "auto_review") return "只改变审核放行方式，不产生额外视频输出。";
  if (mode.key === "multi_platform_adaptation") return "当前主要写入平台适配配置，尚未自动分叉导出多平台成片。";
  if (mode.key === "ai_effects") return "当前主要完成配置挂载，暂未接入稳定的视频特效输出。";

  return "当前输出方式待补充。";
}

function getPresenterFilePath(profile: AvatarMaterialProfile): string {
  return profile.files.find((file) => file.role === "speaking_video")?.path ?? "";
}
