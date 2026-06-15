import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { SelectField } from "../components/forms/SelectField";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import {
  normalizeIntelligentCopyPlatformId,
  openManualHandoffTarget,
  publicationAttemptStatusLabel,
  publicationPlanExecutorPreflightMessages,
  publicationPlanIsReady,
  publicationPlanHasManualHandoffReady,
  publicationPlanManualHandoffTargets,
  resultBlockingReasons,
  resultManualHandoffTargets,
  resultStatusKind,
  taskHasContinueReadyMaterial,
  useIntelligentCopyWorkspace,
} from "../features/intelligentCopy/useIntelligentCopyWorkspace";
import {
  publicationAttemptCoverPreviewUrl,
  publicationAttemptReceiptId,
  publicationAttemptUrl,
} from "../features/publication/publicationAttempt";
import { useI18n } from "../i18n";
import { copyStylePresets } from "../stylePresets";
import type { IntelligentCopyGenerateTask, IntelligentCopyPlatformMaterial, PublicationAttempt, PublicationSchemeItem } from "../types";
import { apiPath } from "../api/core";

export function IntelligentCopyPage() {
  const { t } = useI18n();
  const workspace = useIntelligentCopyWorkspace();
  const [activePage, setActivePage] = useState<"generate" | "publish">("generate");
  const [previewPlatformKey, setPreviewPlatformKey] = useState<string | null>(null);
  const [pathInputFocused, setPathInputFocused] = useState(false);
  const [highlightedPathIndex, setHighlightedPathIndex] = useState(0);
  const selectedPublicationProfile = workspace.publicationProfiles.find((profile) => profile.id === workspace.selectedPublicationProfileId);
  const selectedPublicationCredentials = selectedPublicationProfile?.creator_profile?.publishing?.platform_credentials ?? [];
  const selectedTargets = (workspace.publicationPlan.data?.targets ?? []).filter((target) =>
    workspace.selectedPlatformIds.includes(normalizeIntelligentCopyPlatformId(target.platform)),
  );
  const previewPlatform = workspace.result?.platforms.find((platform) => platform.key === previewPlatformKey) ?? null;
  const generateDisabled = !workspace.folderPath.trim() || workspace.generate.isPending || workspace.selectedMaterialPlatformIds.length === 0;
  const recentGenerateTasks = workspace.recentGenerateTasks.data?.tasks ?? [];
  const completedMaterialTasks = useMemo(
    () => recentGenerateTasks.filter((task) => taskHasContinueReadyMaterial(task)),
    [recentGenerateTasks],
  );
  const selectedCompletedMaterialTask = completedMaterialTasks.find((task) => task.id === workspace.selectedGenerateTaskId) ?? null;
  const availableMaterialPlatformKeys = useMemo(
    () => new Set((workspace.result?.platforms ?? []).map((platform) => normalizePublicationPlatformKey(platform.key))),
    [workspace.result?.platforms],
  );
  const parentPathSuggestions = workspace.parentFolderSuggestions;
  const autocompletePathSuggestions = workspace.folderPathAutocompleteOptions.filter((path) => !parentPathSuggestions.includes(path));
  const pathDropdownItems = [
    ...parentPathSuggestions.map((path) => ({ path, group: "parent" as const })),
    ...autocompletePathSuggestions.map((path) => ({ path, group: "autocomplete" as const })),
  ];
  const pathDropdownOpen = pathInputFocused && pathDropdownItems.length > 0;
  const activePathSuggestion =
    pathDropdownItems[Math.min(highlightedPathIndex, Math.max(0, pathDropdownItems.length - 1))]?.path ?? "";
  const publicationPlanManualTargets = publicationPlanManualHandoffTargets(workspace.publicationPlan.data);
  const publicationPlanNeedsManualHandoff = publicationPlanHasManualHandoffReady(workspace.publicationPlan.data);
  const publicationPlanReady = publicationPlanIsReady(workspace.publicationPlan.data);
  const publicationPlanPreflightMessages = publicationPlanExecutorPreflightMessages(workspace.publicationPlan.data);
  const resultManualTargets = resultManualHandoffTargets(workspace.result);

  const choosePathSuggestion = (path: string) => {
    workspace.setFolderPath(path);
    setHighlightedPathIndex(0);
    setPathInputFocused(false);
  };

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("smartCopy.page.eyebrow")}
        title={t("smartCopy.page.title")}
        description={t("smartCopy.page.description")}
        actions={
          <div className="toolbar">
            <Link className="button ghost" to="/publication-management">
              {t("smartCopy.publish.configureAccounts")}
            </Link>
          </div>
        }
      />

      <nav className="smart-copy-page-tabs" role="tablist" aria-label="智能发布页面切换">
        <button
          type="button"
          role="tab"
          aria-selected={activePage === "generate"}
          className={`smart-copy-page-tab${activePage === "generate" ? " active" : ""}`}
          onClick={() => setActivePage("generate")}
        >
          <strong>生成物料</strong>
          <span>目录识别、封面和多平台文案</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activePage === "publish"}
          className={`smart-copy-page-tab${activePage === "publish" ? " active" : ""}`}
          onClick={() => setActivePage("publish")}
        >
          <strong>一键发布</strong>
          <span>选择完成物料并提交发布队列</span>
        </button>
      </nav>

      {activePage === "generate" ? (
        <>
          <div className="panel-grid two-up">
            <section className="panel">
              <PanelHeader
                title={t("smartCopy.form.title")}
                description={t("smartCopy.form.description")}
              />
              <div className="form-grid">
                <div className="smart-copy-path-field">
                  <div className="smart-copy-path-autocomplete">
                    <label>
                      <span>{t("smartCopy.form.folderPath")}</span>
                      <input
                        className="input"
                        type="text"
                        value={workspace.folderPath}
                        onFocus={() => setPathInputFocused(true)}
                        onBlur={() => setPathInputFocused(false)}
                        onChange={(event) => {
                          workspace.setFolderPath(event.target.value);
                          setHighlightedPathIndex(0);
                          setPathInputFocused(true);
                        }}
                        onKeyDown={(event) => {
                          if (pathDropdownOpen && event.key === "ArrowDown") {
                            event.preventDefault();
                            setHighlightedPathIndex((current) => Math.min(pathDropdownItems.length - 1, current + 1));
                            return;
                          }
                          if (pathDropdownOpen && event.key === "ArrowUp") {
                            event.preventDefault();
                            setHighlightedPathIndex((current) => Math.max(0, current - 1));
                            return;
                          }
                          if (pathDropdownOpen && event.key === "Enter" && activePathSuggestion) {
                            event.preventDefault();
                            choosePathSuggestion(activePathSuggestion);
                            return;
                          }
                          if (pathDropdownOpen && event.key === "Escape") {
                            event.preventDefault();
                            setPathInputFocused(false);
                            return;
                          }
                          if (event.key === "Enter" && workspace.folderPath.trim() && !workspace.inspect.isPending) {
                            workspace.inspect.mutate(workspace.folderPath);
                          }
                        }}
                        placeholder={t("smartCopy.form.folderPlaceholder")}
                        autoComplete="off"
                        role="combobox"
                        aria-expanded={pathDropdownOpen}
                        aria-controls="smart-copy-folder-path-dropdown"
                      />
                    </label>
                    {pathDropdownOpen ? (
                      <div
                        id="smart-copy-folder-path-dropdown"
                        className="smart-copy-path-dropdown"
                        role="listbox"
                        aria-label={t("smartCopy.form.pathSuggestions")}
                      >
                        {parentPathSuggestions.length ? (
                          <div className="smart-copy-path-dropdown-group" role="presentation">
                            <div className="smart-copy-path-dropdown-label">{t("smartCopy.form.parentFolders")}</div>
                            {parentPathSuggestions.map((path, index) => (
                              <button
                                key={`parent-${path}`}
                                type="button"
                                role="option"
                                aria-selected={path === activePathSuggestion}
                                className={`smart-copy-path-dropdown-option parent${path === activePathSuggestion ? " selected" : ""}`}
                                onMouseDown={(event) => event.preventDefault()}
                                onClick={() => choosePathSuggestion(path)}
                                onMouseEnter={() => setHighlightedPathIndex(index)}
                                title={path}
                              >
                                {path}
                              </button>
                            ))}
                          </div>
                        ) : null}
                        {autocompletePathSuggestions.length ? (
                          <div className="smart-copy-path-dropdown-group" role="presentation">
                            <div className="smart-copy-path-dropdown-label">{t("smartCopy.form.pathSuggestions")}</div>
                            {autocompletePathSuggestions.map((path, index) => {
                              const itemIndex = parentPathSuggestions.length + index;
                              return (
                                <button
                                  key={`autocomplete-${path}`}
                                  type="button"
                                  role="option"
                                  aria-selected={path === activePathSuggestion}
                                  className={`smart-copy-path-dropdown-option${path === activePathSuggestion ? " selected" : ""}`}
                                  onMouseDown={(event) => event.preventDefault()}
                                  onClick={() => choosePathSuggestion(path)}
                                  onMouseEnter={() => setHighlightedPathIndex(itemIndex)}
                                  title={path}
                                >
                                  {path}
                                </button>
                              );
                            })}
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
                <SelectField
                  label={t("smartCopy.form.copyStyle")}
                  value={workspace.copyStyle}
                  onChange={(event) => workspace.setCopyStyle(event.target.value)}
                  options={copyStylePresets.map((preset) => ({ value: preset.key, label: preset.label }))}
                />
                <label>
                  <span>创作者卡片</span>
                  <select
                    className="input"
                    value={workspace.selectedPublicationProfileId}
                    onChange={(event) => workspace.setSelectedPublicationProfileId(event.target.value)}
                    disabled={!workspace.publicationProfiles.length}
                  >
                    {!workspace.publicationProfiles.length ? <option value="">没有创作者卡片</option> : null}
                    {workspace.publicationProfiles.map((profile) => (
                      <option key={profile.id} value={profile.id}>
                        {profile.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="checkbox-line">
                  <input
                    type="checkbox"
                    checked={workspace.useExistingCover}
                    onChange={(event) => workspace.setUseExistingCover(event.target.checked)}
                  />
                  <span>
                    <strong>{t("smartCopy.form.useExistingCover")}</strong>
                    <small>{t("smartCopy.form.useExistingCoverHint")}</small>
                  </span>
                </label>
              </div>
              {workspace.copyFeedback ? <div className="notice top-gap">{workspace.copyFeedback}</div> : null}
              {workspace.inspect.error ? <div className="notice top-gap">{(workspace.inspect.error as Error).message}</div> : null}
              {workspace.generate.error ? <div className="notice top-gap">{(workspace.generate.error as Error).message}</div> : null}
              {workspace.openFolder.error ? <div className="notice top-gap">{(workspace.openFolder.error as Error).message}</div> : null}
            </section>

            <section className="panel">
              <PanelHeader title={t("smartCopy.inspect.title")} description={t("smartCopy.inspect.description")} />
              {workspace.inspection ? (
                <div className="list-stack">
                  <div>
                    <div className="row-title">{t("smartCopy.inspect.mainAssets")}</div>
                    <div className="muted">{workspace.inspection.video_file || "—"}</div>
                    <div className="muted">{workspace.inspection.subtitle_file || "—"}</div>
                    <div className="muted">{workspace.inspection.cover_file || "—"}</div>
                  </div>
                  {workspace.inspection.warnings.length ? (
                    <div>
                      <div className="row-title">{t("smartCopy.inspect.warnings")}</div>
                      {workspace.inspection.warnings.map((warning) => (
                        <div key={warning} className="muted">{warning}</div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : (
                <EmptyState message={t("smartCopy.inspect.empty")} />
              )}
            </section>
          </div>

          <PageSection
            eyebrow={t("smartCopy.materials.eyebrow")}
            title={t("smartCopy.materials.title")}
            description={t("smartCopy.materials.description")}
            actions={
              <div className="toolbar">
                {workspace.result?.material_dir ? (
                  <button type="button" className="button ghost" onClick={() => workspace.openFolder.mutate(workspace.result?.material_dir || "")}>
                    {t("smartCopy.page.openOutput")}
                  </button>
                ) : null}
                <button
                  type="button"
                  className="button primary"
                  onClick={() =>
                    workspace.generate.mutate({
                      folderPath: workspace.folderPath,
                      copyStyle: workspace.copyStyle,
                      platforms: workspace.selectedMaterialPlatformIds,
                      useExistingCover: workspace.useExistingCover,
                      creatorProfileId: workspace.selectedPublicationProfileId || null,
                    })
                  }
                  disabled={generateDisabled}
                >
                  {workspace.generate.isPending ? t("smartCopy.page.generating") : t("smartCopy.page.generate")}
                </button>
              </div>
            }
          >
        <section className="panel smart-copy-platform-picker">
          <PanelHeader
            title={t("smartCopy.materials.platformPickerTitle")}
            actions={
              <div className="toolbar">
                <span className="mode-chip subtle">
                  {t("smartCopy.materials.platformPickerCount").replace("{count}", String(workspace.selectedMaterialPlatformIds.length))}
                </span>
                <button type="button" className="button ghost" onClick={workspace.selectAllMaterialPlatforms}>
                  {t("smartCopy.materials.platformPickerAll")}
                </button>
              </div>
            }
          />
          <div className="smart-copy-platform-grid">
            {workspace.materialPlatformOptions.map((platform) => {
              const selected = workspace.selectedMaterialPlatformIds.includes(platform.id);
              return (
                <label className={`smart-copy-platform-option${selected ? " selected" : ""}`} key={platform.id} title={platform.detail}>
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={() => workspace.toggleMaterialPlatform(platform.id)}
                  />
                  <span>
                    <strong>{platform.label}</strong>
                  </span>
                </label>
              );
            })}
          </div>
          {workspace.selectedMaterialPlatformIds.length === 0 ? (
            <div className="notice compact-top">{t("smartCopy.materials.platformPickerEmpty")}</div>
          ) : null}
        </section>
        <RecentGenerateTasksPanel
          tasks={workspace.recentGenerateTasks.data?.tasks ?? []}
          selectedTaskId={workspace.selectedGenerateTaskId}
          loading={workspace.recentGenerateTasks.isLoading}
          onSelect={workspace.setSelectedGenerateTaskId}
        />
        <GenerateTaskProgress task={workspace.selectedGenerateTask} loading={workspace.selectedGenerateTaskQuery.isLoading} />
        {workspace.result && resultStatusKind(workspace.result) === "blocked" && resultBlockingReasons(workspace.result).length ? (
          <div className="list-stack compact-top">
            {resultBlockingReasons(workspace.result).slice(0, 6).map((reason) => (
              <div key={reason} className="notice notice-error">{reason}</div>
            ))}
          </div>
        ) : null}
        {workspace.result && resultStatusKind(workspace.result) === "manual_handoff" && resultManualTargets.length ? (
          <div className="list-stack compact-top">
            {resultManualTargets.map((target) => (
              <div className="activity-card" key={`${target.platform}-${target.login_url || "manual"}`}>
                <div className="toolbar">
                  <div>
                    <strong>{target.label || target.platform}</strong>
                    <div className="muted compact-top">{target.reason || "当前平台需人工登录后继续发布。"}</div>
                  </div>
                  {target.login_url ? (
                    <button type="button" className="button secondary" onClick={() => openManualHandoffTarget(target)}>
                      打开登录页
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : null}
        {workspace.result ? (
          <div className="smart-copy-version-grid">
            {workspace.result.platforms.map((platform) => (
              <button
                type="button"
                className="smart-copy-version-card"
                key={platform.key}
                onClick={() => setPreviewPlatformKey(platform.key)}
              >
                <span className="smart-copy-version-kicker">{platform.label}</span>
                <span className={`status-pill ${platformMaterialStatusTone(platform)}`}>
                  {platformMaterialStatusLabel(platform, t)}
                </span>
                <strong>{platform.primary_title || platform.titles[0] || platform.label}</strong>
                <span className="smart-copy-version-body">{platform.body}</span>
                {platformMaterialStatusKind(platform) === "blocked" && platform.blocking_reasons?.length ? (
                  <span className="notice notice-error compact-top">{platform.blocking_reasons[0]}</span>
                ) : null}
                {platformMaterialStatusKind(platform) === "manual_handoff" ? (
                  <span className="mode-chip subtle compact-top">需人工登录后继续发布</span>
                ) : null}
                <span className="smart-copy-version-meta">
                  {platform.has_title ? `${platform.titles.length} ${t("smartCopy.materials.titleCount")}` : t("smartCopy.materials.bodyOnly")} · {platform.tags.length} {t("smartCopy.materials.tagCount")}
                </span>
              </button>
            ))}
          </div>
        ) : workspace.selectedGenerateTask && !["completed", "failed"].includes(workspace.selectedGenerateTask.status) ? null : (
          <EmptyState message={t("smartCopy.materials.empty")} />
        )}
      </PageSection>
        </>
      ) : (
        <PageSection
          eyebrow={t("smartCopy.publish.eyebrow")}
          title={t("smartCopy.publish.title")}
          description="选择一个已完成的物料生成任务，确认视频、字幕和可发布平台后提交一键发布。发布任务会进入队列，页面可持续恢复每个平台的执行状态。"
        >
          <section className="panel smart-copy-publish-material-picker">
            <PanelHeader
              title="选择已完成物料任务"
              description="只列出已经生成完成、可继续自动发布或人工接管的物料任务。选择后会自动定位对应的视频、字幕、输出目录和平台物料。"
              actions={
                <div className="toolbar">
                  <select
                    className="input smart-copy-history-select"
                    value={selectedCompletedMaterialTask?.id ?? ""}
                    onChange={(event) => workspace.setSelectedGenerateTaskId(event.target.value)}
                    disabled={!completedMaterialTasks.length}
                    aria-label="选择已完成物料任务"
                  >
                    <option value="">选择已完成物料任务</option>
                    {completedMaterialTasks.map((task) => (
                      <option key={task.id} value={task.id}>
                        {formatGenerateTaskOptionTime(task)} · {formatGenerateTaskFolderName(task)}
                      </option>
                    ))}
                  </select>
                  <span className="mode-chip subtle">{completedMaterialTasks.length} 个可继续任务</span>
                </div>
              }
            />
            {selectedCompletedMaterialTask ? (
              <div className="smart-copy-publish-task-grid">
                <article className="activity-card">
                  <span className="stat-label">当前任务</span>
                  <strong>{formatGenerateTaskFolderName(selectedCompletedMaterialTask)}</strong>
                  <div className="muted compact-top">{selectedCompletedMaterialTask.message || "物料已完成，可进入发布队列。"}</div>
                </article>
                <article className="activity-card">
                  <span className="stat-label">发布平台</span>
                  <strong>{workspace.result?.platforms.length ?? 0} 个平台物料</strong>
                  <div className="mode-chip-list compact-top">
                    {(workspace.result?.platforms ?? []).map((platform) => (
                      <span className="mode-chip subtle" key={platform.key}>{platform.label}</span>
                    ))}
                  </div>
                </article>
                <article className="activity-card">
                  <span className="stat-label">队列恢复</span>
                  <strong>持久化发布任务</strong>
                  <div className="muted compact-top">提交后按平台创建发布记录，刷新页面也能继续跟踪状态和链接。</div>
                </article>
              </div>
            ) : (
              <EmptyState message="暂无可发布物料任务。请先到“生成物料”页完成一次物料生成。" />
            )}
          </section>

          <section className="panel top-gap">
            <PanelHeader title="视频与字幕定位" description="发布前确认本次物料绑定的成片、字幕、封面和输出目录。" />
            <div className="smart-copy-publish-asset-grid">
              <PathSummaryCard label="成片视频" value={workspace.inspection?.video_file} />
              <PathSummaryCard label="字幕文件" value={workspace.inspection?.subtitle_file} />
              <PathSummaryCard label="封面来源" value={workspace.inspection?.cover_file || workspace.result?.cover_source_path} />
              <PathSummaryCard label="物料目录" value={workspace.result?.material_dir || workspace.inspection?.material_dir} />
            </div>
          </section>

        <div className="panel-grid two-up">
          <section className="panel">
            <PanelHeader
              title={t("smartCopy.publish.accountTitle")}
              description={t("smartCopy.publish.accountDescription")}
              actions={<Link className="button ghost" to="/publication-management">{t("smartCopy.publish.configureAccounts")}</Link>}
            />
            <div className="form-grid">
              <label>
                <span>{t("smartCopy.publish.accountSelect")}</span>
                <select
                  className="input"
                  value={workspace.selectedPublicationProfileId}
                  onChange={(event) => workspace.setSelectedPublicationProfileId(event.target.value)}
                  disabled={!workspace.publicationProfiles.length}
                >
                  {!workspace.publicationProfiles.length ? <option value="">{t("smartCopy.publish.noAccounts")}</option> : null}
                  {workspace.publicationProfiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span>浏览器</span>
                <select
                  className="input"
                  value={workspace.selectedPublicationBrowser}
                  onChange={(event) => workspace.setSelectedPublicationBrowser(event.target.value)}
                >
                  {workspace.publicationBrowserOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="toolbar compact-top">
              <button
                type="button"
                className="button secondary"
                disabled={
                  !selectedPublicationProfile ||
                  !workspace.result?.platforms.length ||
                  workspace.matchPublicationBrowserLogin.isPending
                }
                onClick={() => workspace.matchPublicationBrowserLogin.mutate()}
              >
                {workspace.matchPublicationBrowserLogin.isPending ? "匹配中..." : "自动匹配登录信息"}
              </button>
              <span className="muted">只记录本地浏览器会话引用，不读取或保存平台密码、Cookie。</span>
            </div>
            {workspace.publicationLoginMatchMessage ? (
              <div className="notice compact-top">{workspace.publicationLoginMatchMessage}</div>
            ) : null}
            {workspace.avatarMaterials.isLoading ? <div className="muted compact-top">{t("smartCopy.publish.loadingAccounts")}</div> : null}
            {selectedPublicationProfile ? (
              <div className="mode-chip-list top-gap">
                {selectedPublicationCredentials.map((credential) => (
                  <span className="mode-chip subtle" key={credential.id ?? `${credential.platform}-${credential.account_label}`}>
                    {credential.platform_label || credential.platform} · {credential.account_label || credential.credential_ref || t("smartCopy.publish.unnamedAccount")}
                  </span>
                ))}
                {!selectedPublicationCredentials.length ? <div className="muted">{t("smartCopy.publish.credentialBindingsEmpty")}</div> : null}
              </div>
            ) : (
              <EmptyState message={t("smartCopy.publish.accountEmpty")} />
            )}
          </section>

          <section className="panel">
            <PanelHeader title={t("smartCopy.publish.platformTitle")} description={t("smartCopy.publish.platformDescription")} />
            {workspace.publicationPlan.isLoading ? <div className="muted compact-top">{t("smartCopy.publish.checking")}</div> : null}
            {workspace.publicationPlan.data?.blocked_reasons?.length ? (
              <div className="list-stack compact-top">
                {workspace.publicationPlan.data.blocked_reasons.map((reason) => (
                  <div key={reason} className="notice">{reason}</div>
                ))}
              </div>
            ) : null}
            {workspace.publicationPlan.data?.warnings?.length ? (
              <div className="list-stack compact-top">
                {workspace.publicationPlan.data.warnings.map((warning) => (
                  <div key={warning} className="activity-card">{warning}</div>
                ))}
              </div>
            ) : null}
            {publicationPlanPreflightMessages.length ? (
              <div className="list-stack compact-top">
                {publicationPlanPreflightMessages.map((message) => (
                  <div key={message} className="activity-card">{message}</div>
                ))}
              </div>
            ) : null}
            {publicationPlanManualTargets.length ? (
              <div className="list-stack compact-top">
                {publicationPlanManualTargets.map((target) => (
                  <div className="activity-card" key={`${target.platform}-${target.login_url || "manual"}`}>
                    <div className="toolbar">
                      <div>
                        <strong>{target.label || target.platform}</strong>
                        <div className="muted compact-top">{target.reason || "该平台已切换为人工接管，不再进入自动一键发布。"}</div>
                      </div>
                      {target.login_url ? (
                        <button type="button" className="button secondary" onClick={() => openManualHandoffTarget(target)}>
                          打开登录页
                        </button>
                      ) : null}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
            {workspace.publicationPlan.data?.targets?.length ? (
              <div className="list-stack compact-top">
                {workspace.publicationPlan.data.targets.map((target) => (
                  <label className={`activity-card smart-copy-publish-target${workspace.selectedPlatformIds.includes(target.platform) ? " selected" : ""}`} key={target.platform}>
                    <div className="toolbar">
                      <div>
                        <strong>{target.platform_label}</strong>
                        <div className="muted compact-top">{target.account_label}</div>
                      </div>
                      <input
                        type="checkbox"
                        checked={workspace.selectedPlatformIds.includes(target.platform)}
                        onChange={() => workspace.togglePlatform(target.platform)}
                      />
                    </div>
                    {availableMaterialPlatformKeys.has(target.platform) ? (
                      <span className="status-pill done compact-top">已有平台物料</span>
                    ) : (
                      <span className="status-pill pending compact-top">未在当前物料中生成</span>
                    )}
                    <div className="muted compact-top">{target.title}</div>
                  </label>
                ))}
              </div>
            ) : (
              <EmptyState message={publicationPlanNeedsManualHandoff ? "当前所选平台需人工登录接管，自动发布目标为空。" : t("smartCopy.publish.platformEmpty")} />
            )}
          </section>
        </div>

        {selectedTargets.length ? (
          <section className="panel top-gap">
            <PanelHeader
              title="智能发布方案"
              description="只使用真实平台数据生成合集/栏目和分类；未摸底到真实选项时只给发布时间，不自动填写伪造栏目。"
              actions={
                <div className="toolbar">
                  <button
                    className="button secondary"
                    type="button"
                    disabled={workspace.generatePublicationScheme.isPending || !publicationPlanReady}
                    onClick={() => workspace.generatePublicationScheme.mutate(false)}
                  >
                    {workspace.generatePublicationScheme.isPending ? "生成中..." : workspace.publicationScheme ? "重新生成方案" : "生成智能发布方案"}
                  </button>
                  <button
                    className="button ghost"
                    type="button"
                    disabled={workspace.generatePublicationScheme.isPending || !publicationPlanReady}
                    onClick={() => workspace.generatePublicationScheme.mutate(true)}
                  >
                    刷新摸底
                  </button>
                </div>
              }
            />
            {workspace.generatePublicationScheme.error ? (
              <div className="notice compact-top">{String(workspace.generatePublicationScheme.error)}</div>
            ) : null}
            {workspace.publicationScheme?.blocked_reasons?.length ? (
              <div className="list-stack compact-top">
                {workspace.publicationScheme.blocked_reasons.map((reason) => (
                  <div className="notice" key={reason}>{reason}</div>
                ))}
              </div>
            ) : null}
            {workspace.publicationScheme?.items?.length ? (
              <>
                <div className="smart-copy-scheme-meta compact-top">
                  <span className="status-pill done">摸底：{workspace.publicationScheme.probe?.status || "cached"}</span>
                  <span className="status-pill">调研：{workspace.publicationScheme.research?.search_status || "fallback"} / LLM {workspace.publicationScheme.research?.llm_status || "fallback"}</span>
                  <span className="muted">{workspace.publicationScheme.research?.summary}</span>
                </div>
                <div className="smart-copy-scheme-grid compact-top">
                  {workspace.publicationScheme.items.map((item) => (
                    <article className="activity-card smart-copy-scheme-card" key={item.platform}>
                      <div className="toolbar">
                        <div>
                          <strong>{item.platform_label}</strong>
                          <div className="muted compact-top">{item.account_label || "当前创作者账号"}</div>
                        </div>
                        <span className="status-pill done">{item.visibility_or_publish_mode || "scheduled"}</span>
                      </div>
                      <div className="smart-copy-scheme-fields">
                        <div>
                          <span>发布时间</span>
                          <strong>{item.scheduled_publish_at || "发布时决定"}</strong>
                        </div>
                        <div>
                          <span>合集/栏目</span>
                          <strong>{item.collection_name || "未摸底"}</strong>
                        </div>
                        <div>
                          <span>分类</span>
                          <strong>{item.category || "未摸底"}</strong>
                        </div>
                      </div>
                      <p className="muted compact-top">{item.rationale}</p>
                      <p className="muted compact-top">{item.probe_summary}</p>
                      <PublicationSchemeInventory item={item} />
                    </article>
                  ))}
                </div>
                <div className="smart-copy-scheme-modifier compact-top">
                  <textarea
                    className="input"
                    rows={3}
                    value={workspace.publicationSchemeInstruction}
                    onChange={(event) => workspace.setPublicationSchemeInstruction(event.target.value)}
                    placeholder="直接写你的修改想法，例如：B站放到 EDC装备评测合集，YouTube 改成今晚 21:30，小红书只建草稿。"
                  />
                  <button
                    className="button secondary"
                    type="button"
                    disabled={!workspace.publicationSchemeInstruction.trim() || workspace.modifyPublicationScheme.isPending}
                    onClick={() => workspace.modifyPublicationScheme.mutate()}
                  >
                    {workspace.modifyPublicationScheme.isPending ? "修改中..." : "修改方案"}
                  </button>
                </div>
                {workspace.modifyPublicationScheme.error ? (
                  <div className="notice compact-top">{String(workspace.modifyPublicationScheme.error)}</div>
                ) : null}
              </>
            ) : (
              <EmptyState message="已选平台后点击生成智能发布方案，系统会给出发布时间、合集/栏目、分类和发布模式建议。" />
            )}
          </section>
        ) : null}

        {workspace.publish.error ? <div className="notice top-gap">{String(workspace.publish.error)}</div> : null}
        <PublicationPlatformProgressPanel
          targets={workspace.publicationPlan.data?.targets ?? []}
          attempts={[
            ...(workspace.publicationPlan.data?.created_attempts ?? []),
            ...(workspace.publicationPlan.data?.existing_attempts ?? []),
          ]}
          selectedPlatformIds={workspace.selectedPlatformIds}
        />

        <PublicationHistoryPanel
          attempts={workspace.recentPublicationAttempts.data?.attempts ?? []}
          selectedAttempt={workspace.selectedPublicationAttempt}
          selectedAttemptId={workspace.selectedPublicationAttemptId}
          loading={workspace.recentPublicationAttempts.isLoading}
          onSelect={workspace.setSelectedPublicationAttemptId}
        />

        <div className="toolbar top-gap">
          <button
            className="button primary"
            type="button"
            disabled={
              !workspace.result ||
              !selectedCompletedMaterialTask ||
              !publicationPlanReady ||
              !workspace.selectedPlatformIds.length ||
              !workspace.publicationScheme?.items?.length ||
              workspace.publish.isPending
            }
            onClick={() => workspace.publish.mutate()}
          >
            {workspace.publish.isPending ? t("smartCopy.publish.submitting") : t("smartCopy.publish.submit")}
          </button>
          {publicationPlanManualTargets.length ? (
            <button
              className="button secondary"
              type="button"
              onClick={() => {
                publicationPlanManualTargets.forEach((target) => {
                  openManualHandoffTarget(target);
                });
              }}
            >
              打开人工登录页
            </button>
          ) : null}
          {!workspace.result ? <span className="muted">{t("smartCopy.publish.needGenerate")}</span> : null}
          {workspace.result && !selectedCompletedMaterialTask ? <span className="muted">请先选择一个已完成的物料任务。</span> : null}
        </div>
      </PageSection>
      )}

      {previewPlatform ? (
        <PlatformMaterialPreviewModal
          platform={previewPlatform}
          onClose={() => setPreviewPlatformKey(null)}
          onCopy={(text, label) => workspace.copyText(text, label)}
          onOpenCover={(path) => workspace.openFolder.mutate(path)}
        />
      ) : null}
    </section>
  );
}

type RecentGenerateTasksPanelProps = {
  tasks: IntelligentCopyGenerateTask[];
  selectedTaskId: string;
  loading: boolean;
  onSelect: (taskId: string) => void;
};

function RecentGenerateTasksPanel({ tasks, selectedTaskId, loading, onSelect }: RecentGenerateTasksPanelProps) {
  const { t } = useI18n();
  return (
    <section className="panel smart-copy-recent-tasks">
      <PanelHeader
        title={t("smartCopy.tasks.title")}
        description={t("smartCopy.tasks.description")}
        actions={
          <div className="toolbar">
            <select
              className="input smart-copy-history-select"
              value={selectedTaskId}
              onChange={(event) => onSelect(event.target.value)}
              disabled={!tasks.length}
              aria-label={t("smartCopy.tasks.select")}
            >
              <option value="">{t("smartCopy.tasks.select")}</option>
              {tasks.map((task) => (
                <option key={task.id} value={task.id}>
                  {generateTaskStatusLabel(task.status)} · {formatGenerateTaskOptionTime(task)} · {formatGenerateTaskFolderName(task)}
                </option>
              ))}
            </select>
            <span className="mode-chip subtle">{loading ? t("smartCopy.tasks.loading") : `${tasks.length} ${t("smartCopy.tasks.count")}`}</span>
          </div>
        }
      />
      {tasks.length ? (
        <div className="smart-copy-task-strip" aria-label={t("smartCopy.tasks.title")}>
          {tasks.map((task) => (
            <button
              key={task.id}
              type="button"
              className={`smart-copy-task-card${task.id === selectedTaskId ? " selected" : ""}`}
              onClick={() => onSelect(task.id)}
            >
              <span className={`status-pill ${taskStatusTone(task.status)}`}>{generateTaskStatusLabel(task.status)}</span>
              <strong>{formatGenerateTaskFolderName(task)}</strong>
              <span className="smart-copy-task-timestamp">{formatGenerateTaskTimeline(task)}</span>
              <span className="muted">{task.message || task.stage}</span>
              <div
                className={`progress-bar smart-copy-task-mini-progress${isGenerateTaskRunning(task) ? " is-animated" : ""}`}
                role="progressbar"
                aria-label={t("smartCopy.tasks.progress")}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={normalizePercent(task.progress)}
              >
                <span style={{ width: `${normalizePercent(task.progress)}%` }} />
              </div>
            </button>
          ))}
        </div>
      ) : (
        <EmptyState message={t("smartCopy.tasks.empty")} />
      )}
    </section>
  );
}

type PublicationHistoryPanelProps = {
  attempts: PublicationAttempt[];
  selectedAttempt: PublicationAttempt | null;
  selectedAttemptId: string;
  loading: boolean;
  onSelect: (attemptId: string) => void;
};

function PathSummaryCard({ label, value }: { label: string; value?: string | null }) {
  return (
    <article className="activity-card smart-copy-path-summary-card">
      <span className="stat-label">{label}</span>
      <strong title={value || "—"}>{value || "—"}</strong>
    </article>
  );
}

function normalizePublicationPlatformKey(value: string) {
  return normalizeIntelligentCopyPlatformId(value);
}

type PublicationPlatformProgressPanelProps = {
  targets: Array<{
    platform: string;
    platform_label: string;
    account_label: string;
    title: string;
  }>;
  attempts: PublicationAttempt[];
  selectedPlatformIds: string[];
};

function PublicationPlatformProgressPanel({ targets, attempts, selectedPlatformIds }: PublicationPlatformProgressPanelProps) {
  const { t } = useI18n();
  const selectedTargets = targets.filter((target) =>
    selectedPlatformIds.includes(normalizePublicationPlatformKey(target.platform)),
  );
  if (!selectedTargets.length) {
    return (
      <section className="panel top-gap">
        <PanelHeader title="发布进度" description="勾选发布平台后，这里会展示每个平台的队列状态、执行摘要和跟踪链接。" />
        <EmptyState message="还没有选择发布平台。" />
      </section>
    );
  }
  return (
    <section className="panel top-gap">
      <PanelHeader title="发布进度" description="每个平台独立进入发布队列，可单独查看状态、错误、执行摘要和最终链接。" />
      <div className="smart-copy-publication-progress-grid">
        {selectedTargets.map((target) => {
          const attempt = latestPublicationAttemptForPlatform(attempts, target.platform);
          const attemptUrl = publicationAttemptUrl(attempt);
          const latestRun = attempt?.runs?.[0];
          return (
            <article className="activity-card smart-copy-publication-progress-card" key={target.platform}>
              <PublicationAttemptCover attempt={attempt} label={target.platform_label} compact />
              <div className="toolbar">
                <div>
                  <strong>{target.platform_label}</strong>
                  <div className="muted compact-top">{target.account_label || t("smartCopy.publish.unnamedAccount")}</div>
                </div>
                <span className={`status-pill ${publicationStatusTone(attempt?.status || "queued")}`}>
                  {attempt ? publicationAttemptStatusLabel(attempt.status) : "待提交"}
                </span>
              </div>
              <div className="smart-copy-publication-meta compact-top">
                <span>标题：{target.title || "—"}</span>
                <span>状态：{attempt?.operator_summary || attempt?.run_status || (attempt ? t("smartCopy.publish.waitingRunner") : "尚未创建发布记录")}</span>
                <span>更新：{formatDateTime(attempt?.updated_at || attempt?.created_at)}</span>
                {latestRun?.phase ? <span>阶段：{latestRun.phase}</span> : null}
                {latestRun?.provider_task_id ? <span>任务：{latestRun.provider_task_id}</span> : null}
                {publicationAttemptReceiptId(attempt) ? (
                  <span title={publicationAttemptReceiptId(attempt)}>回执：{publicationAttemptReceiptId(attempt)}</span>
                ) : null}
              </div>
              {attempt?.error_message ? <div className="notice notice-error compact-top">{attempt.error_message}</div> : null}
              <div className="toolbar compact-top">
                {attemptUrl ? (
                  <a className="button ghost button-sm" href={attemptUrl} target="_blank" rel="noreferrer">
                    打开跟踪链接
                  </a>
                ) : (
                  <span className="muted">{attempt ? t("smartCopy.publish.publicUrlPending") : "提交后生成跟踪链接"}</span>
                )}
                {attempt?.payload_path ? <span className="mode-chip subtle" title={attempt.payload_path}>payload</span> : null}
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function PublicationSchemeInventory({ item }: { item: PublicationSchemeItem }) {
  const selectedOptions = item.selected_options ?? {};
  const selectedDeclarations = asStringList(selectedOptions.selected_declarations);
  const selectedGroupChat = String(selectedOptions.selected_group_chat ?? "");
  const operationSteps = item.operation_steps ?? [];
  const optionGroups = item.option_groups ?? [];
  const hasInventory =
    Boolean(item.declaration_options?.length) ||
    Boolean(item.group_chat_options?.length) ||
    Boolean(operationSteps.length) ||
    Boolean(optionGroups.length) ||
    Boolean(item.platform_warnings?.length);

  if (!hasInventory) {
    return <div className="notice compact-top">尚未读取到该平台的真实声明、群聊、分区/合集控件和发布路径。</div>;
  }

  return (
    <div className="smart-copy-scheme-inventory">
      {item.platform_warnings?.length ? (
        <div className="notice notice-error compact-top">{item.platform_warnings[0]}</div>
      ) : null}
      {item.declaration_options?.length ? (
        <div>
          <span className="stat-label">声明候选</span>
          <div className="smart-copy-scheme-chip-row">
            {item.declaration_options.slice(0, 8).map((option) => (
              <span className={`mode-chip ${selectedDeclarations.includes(option) ? "done" : "subtle"}`} key={option}>
                {option}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {item.group_chat_options?.length ? (
        <div>
          <span className="stat-label">群聊候选</span>
          <div className="smart-copy-scheme-chip-row">
            {item.group_chat_options.slice(0, 6).map((option) => (
              <span className={`mode-chip ${selectedGroupChat === option ? "done" : "subtle"}`} key={option}>
                {option}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {optionGroups.length ? (
        <div>
          <span className="stat-label">平台选项摸底</span>
          <div className="smart-copy-scheme-option-list">
            {optionGroups.slice(0, 5).map((group, index) => (
              <span key={`${item.platform}-option-${index}`}>
                {String(group.label ?? group.name ?? group.key ?? "选项组")}：{asStringList(group.options ?? group.values).slice(0, 5).join("、") || "已识别控件"}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {operationSteps.length ? (
        <div>
          <span className="stat-label">发布路径</span>
          <ol className="smart-copy-scheme-steps">
            {operationSteps.slice(0, 6).map((step, index) => (
              <li key={`${item.platform}-step-${index}`}>{String(step.label ?? step.action ?? step.name ?? step.selector ?? "页面操作")}</li>
            ))}
          </ol>
        </div>
      ) : null}
    </div>
  );
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item ?? "").trim()).filter(Boolean);
  if (typeof value === "string") return value.split(/[，,、;\n]+/).map((item) => item.trim()).filter(Boolean);
  return [];
}

function PublicationHistoryPanel({ attempts, selectedAttempt, selectedAttemptId, loading, onSelect }: PublicationHistoryPanelProps) {
  const { t } = useI18n();
  const selectedUrl = publicationAttemptUrl(selectedAttempt);
  return (
    <section className="panel smart-copy-publication-history">
      <PanelHeader
        title={t("smartCopy.publish.allHistoryTitle")}
        description={t("smartCopy.publish.allHistoryDescription")}
        actions={
          <div className="toolbar">
            <select
              className="input smart-copy-history-select"
              value={selectedAttemptId}
              onChange={(event) => onSelect(event.target.value)}
              disabled={!attempts.length}
              aria-label={t("smartCopy.publish.selectHistory")}
            >
              <option value="">{t("smartCopy.publish.selectHistory")}</option>
              {attempts.map((attempt) => (
                <option key={attempt.id} value={attempt.id}>
                  {publicationAttemptStatusLabel(attempt.status)} · {attempt.platform_label || attempt.platform} · {formatDateTime(attempt.updated_at || attempt.created_at)}
                </option>
              ))}
            </select>
            <span className="mode-chip subtle">{loading ? t("smartCopy.tasks.loading") : `${attempts.length} ${t("smartCopy.tasks.count")}`}</span>
          </div>
        }
      />
      {selectedAttempt ? (
        <div className="smart-copy-publication-history-layout">
          <article className="activity-card smart-copy-publication-selected">
            <PublicationAttemptCover attempt={selectedAttempt} label={selectedAttempt.platform_label || selectedAttempt.platform} />
            <div className="toolbar">
              <div>
                <strong>{selectedAttempt.platform_label || selectedAttempt.platform}</strong>
                <div className="muted compact-top">
                  {selectedAttempt.creator_profile_name || "—"} · {selectedAttempt.account_label || t("smartCopy.publish.unnamedAccount")}
                </div>
              </div>
              <span className={`status-pill ${publicationStatusTone(selectedAttempt.status)}`}>
                {publicationAttemptStatusLabel(selectedAttempt.status)}
              </span>
            </div>
            <div className="smart-copy-publication-meta">
              <span>{t("smartCopy.publish.updatedAt")}: {formatDateTime(selectedAttempt.updated_at || selectedAttempt.created_at)}</span>
              <span>{t("smartCopy.publish.runStatus")}: {selectedAttempt.operator_summary || selectedAttempt.run_status || t("smartCopy.publish.waitingRunner")}</span>
              {selectedAttempt.external_post_id ? <span>Post ID: {selectedAttempt.external_post_id}</span> : null}
              {publicationAttemptReceiptId(selectedAttempt) ? (
                <span title={publicationAttemptReceiptId(selectedAttempt)}>回执：{publicationAttemptReceiptId(selectedAttempt)}</span>
              ) : null}
            </div>
            {selectedAttempt.error_message ? <div className="notice notice-error compact-top">{selectedAttempt.error_message}</div> : null}
            <div className="toolbar compact-top">
              {selectedUrl ? (
                <a className="button ghost" href={selectedUrl} target="_blank" rel="noreferrer">
                  {t("smartCopy.publish.openPublicUrl")}
                </a>
              ) : (
                <span className="muted">{t("smartCopy.publish.noPublicUrl")}</span>
              )}
            </div>
          </article>
          <div className="smart-copy-publication-attempt-list">
            {attempts.slice(0, 8).map((attempt) => {
              const attemptUrl = publicationAttemptUrl(attempt);
              return (
                <button
                  key={attempt.id}
                  type="button"
                  className={`smart-copy-publication-attempt${attempt.id === selectedAttemptId ? " selected" : ""}`}
                  onClick={() => onSelect(attempt.id)}
                >
                  <PublicationAttemptCover attempt={attempt} label={attempt.platform_label || attempt.platform} compact />
                  <span className={`status-pill ${publicationStatusTone(attempt.status)}`}>
                    {publicationAttemptStatusLabel(attempt.status)}
                  </span>
                  <strong>{attempt.platform_label || attempt.platform}</strong>
                  <span className="muted">{attempt.operator_summary || attempt.run_status || formatDateTime(attempt.updated_at || attempt.created_at)}</span>
                  <span className={attemptUrl ? "done" : "muted"}>
                    {attemptUrl ? t("smartCopy.publish.publicUrlReady") : t("smartCopy.publish.publicUrlPending")}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      ) : (
        <EmptyState message={t("smartCopy.publish.historyEmpty")} />
      )}
    </section>
  );
}

function PublicationAttemptCover({
  attempt,
  label,
  compact = false,
}: {
  attempt: PublicationAttempt | null | undefined;
  label: string;
  compact?: boolean;
}) {
  const previewUrl = publicationAttemptCoverPreviewUrl(attempt);
  return (
    <div className={`smart-copy-publication-cover${compact ? " compact" : ""}`}>
      {previewUrl ? (
        <img src={previewUrl} alt={`${label} 封面`} loading="lazy" />
      ) : (
        <span>{compact ? "封面待同步" : "暂无封面"}</span>
      )}
    </div>
  );
}

function GenerateTaskProgress({ task, loading }: { task: IntelligentCopyGenerateTask | null; loading: boolean }) {
  const { t } = useI18n();
  if (!task && !loading) return null;
  const progress = normalizePercent(task?.progress ?? 0);
  const running = task ? isGenerateTaskRunning(task) : true;
  return (
    <div className="smart-copy-generate-progress" role="status">
      <div className="tool-run-summary">
        <strong className={task ? taskStatusTone(task.status) : "running"}>
          {task ? generateTaskStatusLabel(task.status) : t("smartCopy.tasks.loading")}
        </strong>
        {task ? <span className="muted">{task.message || task.stage}</span> : null}
        <span className="mode-chip subtle">{progress}%</span>
      </div>
      <div
        className={`progress-bar smart-copy-generate-progress-bar${running ? " is-animated" : ""}`}
        role="progressbar"
        aria-label={t("smartCopy.tasks.progress")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      {task?.error ? <div className="notice notice-error compact-top">{task.error}</div> : null}
    </div>
  );
}

function normalizePercent(value: number | null | undefined): number {
  if (!Number.isFinite(Number(value))) return 0;
  return Math.max(0, Math.min(100, Math.round(Number(value))));
}

function isGenerateTaskRunning(task: IntelligentCopyGenerateTask): boolean {
  return !["completed", "manual_handoff", "blocked", "failed", "cancelled"].includes(task.status);
}

function taskStatusTone(status: string): string {
  if (status === "completed") return "done";
  if (status === "manual_handoff") return "pending";
  if (status === "blocked") return "running";
  if (status === "failed") return "failed";
  return "running";
}

function publicationStatusTone(status: string): string {
  if (status === "published" || status === "draft_created" || status === "scheduled_pending") return "done";
  if (status === "failed") return "failed";
  return "running";
}

function latestPublicationAttemptForPlatform(attempts: PublicationAttempt[], platform: string): PublicationAttempt | null {
  const matched = attempts.filter((attempt) => attempt.platform === platform);
  if (!matched.length) return null;
  return [...matched].sort((left, right) => {
    const leftTime = new Date(left.updated_at || left.created_at).getTime();
    const rightTime = new Date(right.updated_at || right.created_at).getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  })[0] ?? null;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatGenerateTaskOptionTime(task: IntelligentCopyGenerateTask): string {
  return formatDateTime(task.completed_at || task.updated_at || task.started_at || task.created_at);
}

function formatGenerateTaskTimeline(task: IntelligentCopyGenerateTask): string {
  const created = formatDateTime(task.created_at);
  if (task.completed_at) return `创建 ${created} · 完成 ${formatDateTime(task.completed_at)}`;
  if (task.started_at) return `创建 ${created} · 开始 ${formatDateTime(task.started_at)} · 更新 ${formatDateTime(task.updated_at)}`;
  return `创建 ${created} · 更新 ${formatDateTime(task.updated_at)}`;
}

function formatGenerateTaskFolderName(task: IntelligentCopyGenerateTask): string {
  return formatFolderName(
    task.inspection?.folder_path
    || task.result?.folder_path
    || task.partial_result?.folder_path
    || task.folder_path,
  );
}

function formatFolderName(path: string | null | undefined): string {
  const raw = String(path ?? "").trim();
  if (!raw) return "";
  const segments = raw.split(/[\\/]/).filter(Boolean);
  const name = segments.at(-1) || raw;
  return name.replace(/^[a-f0-9]{16}-/i, "");
}

function generateTaskStatusLabel(status: string): string {
  if (status === "queued") return "已排队";
  if (status === "running") return "生成中";
  if (status === "completed") return "已完成";
  if (status === "manual_handoff") return "人工接管";
  if (status === "blocked") return "待补封面";
  if (status === "failed") return "失败";
  return status || "待处理";
}

export function buildPlatformPreviewMetadataRows(platform: IntelligentCopyPlatformMaterial): Array<{ label: string; value: string }> {
  const rows: Array<{ label: string; value: string }> = [];
  const manualPublishEntryUrl = String(platform.manual_publish_entry_url ?? "").trim();
  const declaration = String(platform.declaration ?? "").trim();
  const collectionName =
    String(platform.collection_name ?? "").trim() ||
    String((platform.collection as Record<string, unknown> | null | undefined)?.name ?? "").trim();
  const visibility = String(platform.visibility_or_publish_mode ?? "").trim();
  const scheduledAt = String(platform.scheduled_publish_at ?? "").trim();
  const preflight = platform.live_publish_preflight && typeof platform.live_publish_preflight === "object"
    ? platform.live_publish_preflight
    : null;
  const preflightStatus = String((preflight as Record<string, unknown> | null)?.status ?? "").trim();
  const preflightSummary = String((preflight as Record<string, unknown> | null)?.summary ?? "").trim();
  const missingRequiredSurfaces = Array.isArray((preflight as Record<string, unknown> | null)?.missing_required_surfaces)
    ? ((preflight as Record<string, unknown>).missing_required_surfaces as unknown[])
      .map((item) => String(item ?? "").trim())
      .filter(Boolean)
    : [];

  if (platformMaterialStatusKind(platform) === "manual_handoff") {
    rows.push({ label: "发布方式", value: "人工接管" });
    if (manualPublishEntryUrl) rows.push({ label: "登录入口", value: manualPublishEntryUrl });
  }
  if (declaration) rows.push({ label: "声明", value: declaration });
  if (collectionName) rows.push({ label: "合集", value: collectionName });
  if (visibility) rows.push({ label: "发布模式", value: visibility });
  if (scheduledAt) rows.push({ label: "定时", value: scheduledAt });
  if (preflightStatus || preflightSummary || missingRequiredSurfaces.length) {
    const statusLabel = preflightStatus || "unknown";
    const summary = preflightSummary || (missingRequiredSurfaces.length ? `缺少：${missingRequiredSurfaces.join("、")}` : "");
    rows.push({
      label: "预发布门禁",
      value: [statusLabel, summary].filter(Boolean).join(" · "),
    });
  }
  return rows;
}

export function platformMaterialStatusKind(
  platform: IntelligentCopyPlatformMaterial,
): "ready" | "blocked" | "manual_handoff" {
  if (platform.manual_handoff_only || String(platform.manual_publish_entry_url ?? "").trim()) {
    return "manual_handoff";
  }
  const preflight = platform.live_publish_preflight && typeof platform.live_publish_preflight === "object"
    ? platform.live_publish_preflight
    : null;
  const preflightStatus = String(preflight?.status ?? "").trim().toLowerCase();
  const missingRequiredSurfaces = Array.isArray(preflight?.missing_required_surfaces)
    ? preflight.missing_required_surfaces.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
  const blockingReasons = Array.isArray(platform.blocking_reasons)
    ? platform.blocking_reasons.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
  if (
    platform.publish_ready === false
    || preflightStatus === "blocked"
    || preflightStatus === "missing_required_surfaces"
    || missingRequiredSurfaces.length > 0
    || blockingReasons.length > 0
  ) {
    return "blocked";
  }
  if (platform.publish_ready === true) {
    return "ready";
  }
  return "blocked";
}

export function platformMaterialStatusTone(platform: IntelligentCopyPlatformMaterial): string {
  const status = platformMaterialStatusKind(platform);
  if (status === "manual_handoff") return "pending";
  if (status === "blocked") return "failed";
  return "done";
}

export function platformMaterialStatusLabel(
  platform: IntelligentCopyPlatformMaterial,
  t: (key: string) => string,
): string {
  const status = platformMaterialStatusKind(platform);
  if (status === "manual_handoff") return "人工接管";
  if (status === "blocked") return t("smartCopy.materials.blocked");
  return t("smartCopy.materials.ready");
}

type PlatformMaterialPreviewModalProps = {
  platform: IntelligentCopyPlatformMaterial;
  onClose: () => void;
  onCopy: (text: string, label: string) => void;
  onOpenCover: (path: string) => void;
};

function PlatformMaterialPreviewModal({ platform, onClose, onCopy, onOpenCover }: PlatformMaterialPreviewModalProps) {
  const { t } = useI18n();
  const title = platform.primary_title || platform.titles[0] || platform.label;
  const previewClassName = `platform-preview-shell ${platformPreviewClass(platform.key)}`;
  const coverPreviewUrl = platform.cover_path ? localImagePreviewUrl(platform.cover_path, platform.cover_generation) : "";
  const publicationMetadataRows = buildPlatformPreviewMetadataRows(platform);

  return (
    <div className="floating-modal-backdrop smart-copy-preview-backdrop" onClick={onClose} role="presentation">
      <div className="floating-modal-shell smart-copy-preview-modal-shell" role="dialog" aria-modal="true" aria-label={`${platform.label} ${t("smartCopy.materials.preview")}`} onClick={(event) => event.stopPropagation()}>
        <button className="button ghost floating-modal-close" type="button" onClick={onClose} aria-label={t("smartCopy.materials.closePreview")}>
          {t("smartCopy.materials.close")}
        </button>
        <section className="panel smart-copy-preview-modal">
          <PanelHeader
            title={`${platform.label} ${t("smartCopy.materials.version")}`}
            description={platform.constraints.rule_note}
            actions={
              <div className="toolbar">
                <button type="button" className="button ghost" onClick={() => onCopy(platform.full_copy, `${platform.label} 已复制`)}>
                  {t("smartCopy.results.copyAll")}
                </button>
                {platform.cover_path ? (
                  <button type="button" className="button ghost" onClick={() => onOpenCover(platform.cover_path || "")}>
                    {t("smartCopy.results.openCover")}
                  </button>
                ) : null}
              </div>
            }
          />
          {platformMaterialStatusKind(platform) === "blocked" && platform.blocking_reasons?.length ? (
            <div className="list-stack compact-top">
              {platform.blocking_reasons.map((reason) => (
                <div key={reason} className="notice notice-error">{reason}</div>
              ))}
            </div>
          ) : null}

          <div className="smart-copy-preview-layout">
            <article className={previewClassName}>
              <div className="platform-preview-device-bar">
                <span>{platform.label}</span>
                <span>{t("smartCopy.materials.previewMode")}</span>
              </div>
              <div className="platform-preview-media">
                {coverPreviewUrl ? (
                  <img src={coverPreviewUrl} alt={`${platform.label} ${t("smartCopy.results.openCover")}`} />
                ) : (
                  <span>{t("smartCopy.materials.videoCover")}</span>
                )}
              </div>
              <div className="platform-preview-content">
                <strong>{title}</strong>
                <p>{platform.body}</p>
                {platform.tags.length ? (
                  <div className="platform-preview-tags">
                    {platform.tags.slice(0, 8).map((tag) => (
                      <span key={tag}>#{tag.replace(/^#/, "")}</span>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="platform-preview-actions">
                <span>{t("smartCopy.materials.like")}</span>
                <span>{t("smartCopy.materials.comment")}</span>
                <span>{t("smartCopy.materials.share")}</span>
              </div>
            </article>

            <div className="smart-copy-preview-detail">
              {platform.has_title ? (
                <div className="list-stack">
                  <div className="row-title">{platform.title_label}</div>
                  {platform.titles.map((item, index) => (
                    <div key={`${platform.key}-${index}`} className="panel-subcard smart-copy-title-option">
                      <div className="smart-copy-title-copy">
                        <span>{`${index + 1}. ${item}`}</span>
                        {platform.title_goals?.[index] ? (
                          <small>
                            {`${platform.title_goals[index]?.goal || "创作目标"}：${platform.title_goals[index]?.direction || "明确这条标题承担的发布目标。"}`}
                          </small>
                        ) : null}
                      </div>
                      <button type="button" className="button ghost button-sm" onClick={() => onCopy(item, `${platform.label} 标题 ${index + 1} 已复制`)}>
                        {t("smartCopy.results.copyTitle")}
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}

              <div className="list-stack top-gap">
                <div>
                  <div className="row-title">{platform.body_label}</div>
                  <pre className="panel-code-block">{platform.body}</pre>
                  <button type="button" className="button ghost top-gap" onClick={() => onCopy(platform.body, `${platform.label} 正文已复制`)}>
                    {t("smartCopy.results.copyBody")}
                  </button>
                </div>
                <div>
                  <div className="row-title">{platform.tag_label}</div>
                  <pre className="panel-code-block">{platform.tags_copy || "—"}</pre>
                  <button type="button" className="button ghost top-gap" onClick={() => onCopy(platform.tags_copy, `${platform.label} 标签已复制`)}>
                    {t("smartCopy.results.copyTags")}
                  </button>
                </div>
                <div className="muted">
                  {`${t("smartCopy.results.constraints")}${platform.constraints.title_limit}/${platform.constraints.body_limit}/${platform.constraints.tag_limit}`}
                </div>
                {publicationMetadataRows.length ? (
                  <div className="list-stack">
                    {publicationMetadataRows.map((row) => (
                      <div key={`${platform.key}-${row.label}`} className="panel-subcard">
                        <div className="row-title">{row.label}</div>
                        <div>{row.value}</div>
                      </div>
                    ))}
                  </div>
                ) : null}
                {platform.cover_path ? <div className="muted">{platform.cover_path}</div> : null}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function localImagePreviewUrl(path: string, metadata?: Record<string, unknown> | null): string {
  const imageGeneration = metadata && typeof metadata === "object" ? metadata.image_generation : null;
  const completedAt =
    imageGeneration && typeof imageGeneration === "object" && "completed_at" in imageGeneration
      ? String((imageGeneration as Record<string, unknown>).completed_at ?? "")
      : "";
  return apiPath(`/intelligent-copy/local-image?path=${encodeURIComponent(path)}&v=${encodeURIComponent(completedAt || path)}`);
}

function platformPreviewClass(platform: string): string {
  if (platform === "douyin") return "platform-preview-douyin";
  if (platform === "xiaohongshu") return "platform-preview-xiaohongshu";
  if (platform === "bilibili") return "platform-preview-bilibili";
  if (platform === "wechat-channels") return "platform-preview-wechat";
  return "platform-preview-default";
}
