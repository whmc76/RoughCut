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
  const activeWorkflowMode =
    catalog?.workflow_modes.find((mode) => mode.key === config.data?.default_job_workflow_mode) ?? null;
  const activeEnhancementLabels =
    catalog?.enhancement_modes.filter((mode) => activeEnhancementModes.includes(mode.key)).map((mode) => mode.title) ?? [];
  const activePresenterId = String(config.data?.avatar_presenter_id ?? "");
  const presenterProfiles = avatarMaterials.data?.profiles ?? [];

  const selectedSubtitle = findStylePreset(subtitleStylePresets, packaging?.subtitle_style ?? "");
  const selectedTitle = findStylePreset(titleStylePresets, packaging?.title_style ?? "");
  const selectedCopy = findStylePreset(copyStylePresets, packaging?.copy_style ?? "");
  const selectedCover = findStylePreset(coverStylePresets, packaging?.cover_style ?? "");
  const selectedEffect = findStylePreset(smartEffectPresets, packaging?.smart_effect_style ?? "");
  const activePresenter = presenterProfiles.find((profile) => getPresenterFilePath(profile) === activePresenterId);
  const activePresenterLabel = activePresenter?.display_name ?? (activePresenterId || "未选定");

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
    <section className="page-stack style-lab-page">
      <PageHeader
        title="风格"
        description="调整会直接影响出片的项目。"
        actions={
          <div className="toolbar">
            <Link className="button ghost" to="/style-templates">
              风格模板
            </Link>
            <Link className="button ghost" to="/creator-profiles">
              档案库
            </Link>
          </div>
        }
      />

      {styleWorkspace.packaging.isLoading || options.isLoading || config.isLoading || avatarMaterials.isLoading ? (
        <section className="panel style-lab-loading">正在加载风格设置…</section>
      ) : null}

      {packaging && catalog && config.data ? (
        <>
          <section className="style-lab-hero">
            <div className="style-lab-hero-copy">
              <h3>当前风格</h3>
              <p>这里只放会直接影响出片的项。</p>
            </div>
            <div className="style-lab-hero-signals">
              <StatusChip label="字幕" value={selectedSubtitle?.label ?? packaging.subtitle_style} />
              <StatusChip label="标题" value={selectedTitle?.label ?? packaging.title_style} />
              <StatusChip label="文案" value={selectedCopy?.label ?? packaging.copy_style} />
              <StatusChip label="封面" value={selectedCover?.label ?? packaging.cover_style} />
              <StatusChip label="特效" value={selectedEffect?.label ?? packaging.smart_effect_style} />
              <StatusChip label="增强" value={String(activeEnhancementModes.length)} />
              <StatusChip label="角色" value={activePresenterLabel} />
            </div>
          </section>

          <section className="style-lab-surface">
            <PageSection
              className="style-lab-panel style-lab-panel-primary"
              title="字幕、标题、文案、封面"
              description="这里只看当前已选项和预设。"
              actions={
                <Link className="button ghost" to="/packaging">
                  打开包装
                </Link>
              }
            >
              <div className="style-lab-preset-lanes">
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
              <div className="top-gap">
                <div className="settings-command-card">
                  <span className="settings-overview-label">包装</span>
                  <strong>素材和策略</strong>
                  <div className="muted">包装素材池和输出规则在这里单独维护。</div>
                  <div className="top-gap">
                    <Link className="button ghost" to="/packaging">
                      查看包装
                    </Link>
                  </div>
                </div>
              </div>
            </PageSection>

            <PageSection
              className="style-lab-panel style-lab-panel-dual"
              title="模式和增强"
              description="先选主模式，再按需开启增强。"
            >
              <div className="style-lab-mode-stack">
                <section className="style-lab-mode-overview">
                  <article className="style-lab-mode-summary">
                    <div className="toolbar">
                      <strong>主模式</strong>
                      <span className="status-pill">{activeWorkflowMode?.title ?? config.data.default_job_workflow_mode}</span>
                    </div>
                    <p className="muted">
                      {activeWorkflowMode?.summary ?? "主模式决定任务的基础产出路径，默认只保留一条稳定主流程。"}
                    </p>
                    <div className="style-lab-workflow-switcher top-gap">
                      {catalog.workflow_modes.map((mode) => (
                        <WorkflowModeOption
                          key={mode.key}
                          mode={mode}
                          active={config.data.default_job_workflow_mode === mode.key}
                          onClick={() => selectWorkflowMode(mode.key)}
                        />
                      ))}
                    </div>
                  </article>

                  <article className="style-lab-mode-summary">
                    <div className="toolbar">
                      <strong>增强</strong>
                      <span className="status-pill">{activeEnhancementModes.length}项已启用</span>
                    </div>
                    <p className="muted">{describeEnhancementState(activeEnhancementModes.length)}</p>
                    <div className="mode-chip-list top-gap">
                      {activeEnhancementLabels.length ? (
                        activeEnhancementLabels.map((label) => (
                          <span key={label} className="mode-chip subtle selected">
                            {label}
                          </span>
                        ))
                      ) : (
                        <span className="mode-chip subtle">当前只使用主模式</span>
                      )}
                    </div>
                  </article>
                </section>

                <section className="style-lab-enhancement-grid">
                  {catalog.enhancement_modes.map((mode) => (
                    <CreativeModeTile
                      key={mode.key}
                      mode={mode}
                      active={activeEnhancementModes.includes(mode.key)}
                      onClick={() => toggleEnhancementMode(mode.key)}
                      toggleLabel={activeEnhancementModes.includes(mode.key) ? "移除" : "启用"}
                      compact
                    />
                  ))}
                </section>
              </div>
            </PageSection>

            <PageSection
              className="style-lab-panel style-lab-panel-gallery"
              title="角色"
              description="这里只保留角色相关设置。"
              actions={<Link className="button ghost" to="/creator-profiles">打开档案库</Link>}
            >
              <section className="style-lab-presenter-stage">
                <div className="toolbar" style={{ flexWrap: "wrap" }}>
                  <StatusChip label="当前角色" value={activePresenterLabel} />
                  <StatusChip label="可用档案" value={String(presenterProfiles.length)} />
                  <StatusChip label="已就绪" value={String(presenterProfiles.filter((profile) => getPresenterFilePath(profile)).length)} />
                </div>
                <div className="style-lab-presenter-grid top-gap">
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
                                {profile.creator_profile?.identity?.public_name || profile.presenter_alias || "未命名"} · {describePresenterTrainingStatus(profile.training_status)}
                              </div>
                            </div>
                            <span className={`mode-chip ${isActive ? "" : ready ? "" : "planned"}`}>
                              {isActive ? "已启用" : ready ? "可启用" : "缺素材"}
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
          </section>
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
  toggleLabel = "启用",
  compact = false,
}: {
  mode: CreativeModeDefinition;
  active: boolean;
  onClick: () => void;
  toggleLabel?: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <article className={classNames("mode-card", "mode-card-compact", active && "selected")}>
        <div className="mode-card-header mode-card-compact-header">
          <div>
            <strong>{mode.title}</strong>
            <div className="muted compact-top">{mode.tagline}</div>
          </div>
          <button className={active ? "button primary button-sm" : "button ghost button-sm"} type="button" onClick={onClick}>
            {active ? "已启用" : toggleLabel}
          </button>
        </div>
        <p className="muted mode-card-compact-summary">{mode.summary}</p>
        <div className="mode-chip-list compact-top">
          {mode.suitable_for.slice(0, 3).map((item) => (
            <span key={item} className="mode-chip subtle">
              {item}
            </span>
          ))}
        </div>
        <div className="muted compact-top mode-card-compact-output">{describeModeOutput(mode)}</div>
      </article>
    );
  }

  return (
    <article className={classNames("mode-card", active && "selected")}>
      <div className="mode-card-header">
        <div>
          <strong>{mode.title}</strong>
          <div className="muted compact-top">{mode.tagline}</div>
        </div>
        <button className={active ? "button primary" : "button ghost"} type="button" onClick={onClick}>
          {active ? "已启用" : toggleLabel}
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

function WorkflowModeOption({
  mode,
  active,
  onClick,
}: {
  mode: CreativeModeDefinition;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={classNames("style-lab-workflow-option", active && "selected")}
      onClick={onClick}
    >
      <strong>{mode.title}</strong>
      <span>{mode.tagline}</span>
      <small>{mode.delivery_scope || describeModeOutput(mode)}</small>
    </button>
  );
}

function describeEnhancementState(enabledCount: number): string {
  if (enabledCount === 0) return "默认只跑主流程，需要时再叠加增强，避免把任务入口变成重配置面板。";
  if (enabledCount === 1) return "当前保留 1 个默认增强项，主流程保持清晰，增强仍按需叠加。";
  return `当前默认挂 ${enabledCount} 个增强项，建议只保留真正高频的增强能力。`;
}

function describeModeOutput(mode: CreativeModeDefinition): string {
  if (mode.kind === "workflow") {
    if (mode.key === "standard_edit") return "直接输出主成片。";
    if (mode.key === "long_text_to_video") return "还在规划中。";
    return "按这个模式直接出片。";
  }

  if (mode.key === "avatar_commentary") return "会叠加数字人口播。";
  if (mode.key === "ai_director") return "会调整解说和配音，再影响成片。";
  if (mode.key === "multilingual_translation") return "只提供字幕翻译，不单独出片。";
  if (mode.key === "auto_review") return "只调整审核放行，不额外出片。";
  if (mode.key === "multi_platform_adaptation") return "当前只记录平台适配，不自动分发多版本。";
  if (mode.key === "ai_effects") return "暂未提供稳定特效输出。";

  return "当前输出方式待补充。";
}

function getPresenterFilePath(profile: AvatarMaterialProfile): string {
  return profile.files.find((file) => file.role === "speaking_video")?.path ?? "";
}

function describePresenterTrainingStatus(status: string): string {
  if (status === "ready_for_manual_training") return "数字人链路可导入";
  return "待补素材";
}
