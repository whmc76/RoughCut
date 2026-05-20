import { useState } from "react";
import { Link } from "react-router-dom";

import { SelectField } from "../components/forms/SelectField";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { publicationAttemptStatusLabel, useIntelligentCopyWorkspace } from "../features/intelligentCopy/useIntelligentCopyWorkspace";
import { useI18n } from "../i18n";
import { copyStylePresets } from "../stylePresets";
import type { IntelligentCopyGenerateTask, IntelligentCopyPlatformMaterial, PublicationAttempt } from "../types";

export function IntelligentCopyPage() {
  const { t } = useI18n();
  const workspace = useIntelligentCopyWorkspace();
  const [previewPlatformKey, setPreviewPlatformKey] = useState<string | null>(null);
  const [pathInputFocused, setPathInputFocused] = useState(false);
  const [highlightedPathIndex, setHighlightedPathIndex] = useState(0);
  const selectedPublicationProfile = workspace.publicationProfiles.find((profile) => profile.id === workspace.selectedPublicationProfileId);
  const selectedPublicationCredentials = selectedPublicationProfile?.creator_profile?.publishing?.platform_credentials ?? [];
  const selectedTargets = (workspace.publicationPlan.data?.targets ?? []).filter((target) =>
    workspace.selectedPlatformIds.includes(target.platform),
  );
  const previewPlatform = workspace.result?.platforms.find((platform) => platform.key === previewPlatformKey) ?? null;
  const generateDisabled = !workspace.folderPath.trim() || workspace.generate.isPending || workspace.selectedMaterialPlatformIds.length === 0;
  const parentPathSuggestions = workspace.parentFolderSuggestions;
  const autocompletePathSuggestions = workspace.folderPathAutocompleteOptions.filter((path) => !parentPathSuggestions.includes(path));
  const pathDropdownItems = [
    ...parentPathSuggestions.map((path) => ({ path, group: "parent" as const })),
    ...autocompletePathSuggestions.map((path) => ({ path, group: "autocomplete" as const })),
  ];
  const pathDropdownOpen = pathInputFocused && pathDropdownItems.length > 0;
  const activePathSuggestion =
    pathDropdownItems[Math.min(highlightedPathIndex, Math.max(0, pathDropdownItems.length - 1))]?.path ?? "";

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
        summary={[
          { label: "直接读取", value: "成片 + 字幕 + 可选封面", detail: "先对现成目录出发布物料" },
          { label: "账号选择", value: "创作者卡片", detail: "先选择创作者，再检查各平台自动登录" },
          { label: "一键发布", value: "平台可勾选", detail: "按平台创建发布任务并交给发布运行器" },
        ]}
        actions={
          <div className="toolbar">
            <Link className="button ghost" to="/creator-profiles">
              {t("smartCopy.publish.configureAccounts")}
            </Link>
          </div>
        }
      />

      <section className="watch-command-strip">
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("smartCopy.page.folderLabel")}</span>
          <strong>{workspace.inspection?.folder_path || t("smartCopy.page.folderPlaceholder")}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("smartCopy.page.videoLabel")}</span>
          <strong>{workspace.inspection?.video_file || "—"}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("smartCopy.page.subtitleLabel")}</span>
          <strong>{workspace.inspection?.subtitle_file || "—"}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("smartCopy.page.outputLabel")}</span>
          <strong>{workspace.result?.material_dir || workspace.inspection?.material_dir || "—"}</strong>
        </article>
      </section>

      <div className="panel-grid two-up">
        <section className="panel">
          <PanelHeader
            title={t("smartCopy.form.title")}
            description={t("smartCopy.form.description")}
            actions={
              <button
                type="button"
                className="button ghost"
                onClick={() => workspace.inspect.mutate(workspace.folderPath)}
                disabled={!workspace.folderPath.trim() || workspace.inspect.isPending}
              >
                {workspace.inspect.isPending ? t("smartCopy.page.inspecting") : t("smartCopy.page.inspect")}
              </button>
            }
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
          </div>
          {workspace.copyFeedback ? <div className="notice top-gap">{workspace.copyFeedback}</div> : null}
          {workspace.inspect.error ? <div className="notice top-gap">{(workspace.inspect.error as Error).message}</div> : null}
          {workspace.generate.error ? <div className="notice top-gap">{(workspace.generate.error as Error).message}</div> : null}
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
        {workspace.result && workspace.result.publish_ready === false && workspace.result.blocking_reasons?.length ? (
          <div className="list-stack compact-top">
            {workspace.result.blocking_reasons.slice(0, 6).map((reason) => (
              <div key={reason} className="notice notice-error">{reason}</div>
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
                <span className={`status-pill ${platform.publish_ready === false ? "failed" : "done"}`}>
                  {platform.publish_ready === false ? t("smartCopy.materials.blocked") : t("smartCopy.materials.ready")}
                </span>
                <strong>{platform.primary_title || platform.titles[0] || platform.label}</strong>
                <span className="smart-copy-version-body">{platform.body}</span>
                {platform.blocking_reasons?.length ? (
                  <span className="notice notice-error compact-top">{platform.blocking_reasons[0]}</span>
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

      <PageSection
        eyebrow={t("smartCopy.publish.eyebrow")}
        title={t("smartCopy.publish.title")}
        description={t("smartCopy.publish.description")}
      >
        <PublicationHistoryPanel
          attempts={workspace.recentPublicationAttempts.data?.attempts ?? []}
          selectedAttempt={workspace.selectedPublicationAttempt}
          selectedAttemptId={workspace.selectedPublicationAttemptId}
          loading={workspace.recentPublicationAttempts.isLoading}
          onSelect={workspace.setSelectedPublicationAttemptId}
        />

        <div className="panel-grid two-up">
          <section className="panel">
            <PanelHeader
              title={t("smartCopy.publish.accountTitle")}
              description={t("smartCopy.publish.accountDescription")}
              actions={<Link className="button ghost" to="/creator-profiles">{t("smartCopy.publish.configureAccounts")}</Link>}
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
            </div>
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
            {workspace.publicationPlan.data?.targets?.length ? (
              <div className="list-stack compact-top">
                {workspace.publicationPlan.data.targets.map((target) => (
                  <label className="activity-card" key={target.platform}>
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
                    <div className="muted compact-top">{target.title}</div>
                  </label>
                ))}
              </div>
            ) : (
              <EmptyState message={t("smartCopy.publish.platformEmpty")} />
            )}
          </section>
        </div>

        {selectedTargets.length ? (
          <section className="panel top-gap">
            <PanelHeader title={t("smartCopy.publish.optionsTitle")} description={t("smartCopy.publish.optionsDescription")} />
            <div className="list-stack">
              {selectedTargets.map((target) => (
                <article className="activity-card" key={target.platform}>
                  <div className="toolbar">
                    <strong>{target.platform_label}</strong>
                    <span className="status-pill done">{t("smartCopy.publish.selected")}</span>
                  </div>
                  <div className="form-grid two-up compact-top">
                    <label>
                      <span>{t("smartCopy.publish.schedule")}</span>
                      <input
                        className="input"
                        type="datetime-local"
                        value={workspace.publicationPlatformOptions[target.platform]?.scheduled_publish_at ?? ""}
                        onChange={(event) =>
                          workspace.updatePublicationPlatformOption(target.platform, { scheduled_publish_at: event.target.value })
                        }
                      />
                    </label>
                    <label>
                      <span>{t("smartCopy.publish.mode")}</span>
                      <select
                        className="input"
                        value={workspace.publicationPlatformOptions[target.platform]?.visibility_or_publish_mode ?? ""}
                        onChange={(event) =>
                          workspace.updatePublicationPlatformOption(target.platform, { visibility_or_publish_mode: event.target.value })
                        }
                      >
                        <option value="">{t("smartCopy.publish.modeDefault")}</option>
                        <option value="scheduled">{t("smartCopy.publish.modeScheduled")}</option>
                        <option value="draft">{t("smartCopy.publish.modeDraft")}</option>
                        <option value="private">{t("smartCopy.publish.modePrivate")}</option>
                      </select>
                    </label>
                    <label>
                      <span>{t("smartCopy.publish.collectionId")}</span>
                      <input
                        className="input"
                        type="text"
                        value={workspace.publicationPlatformOptions[target.platform]?.collection_id ?? ""}
                        onChange={(event) =>
                          workspace.updatePublicationPlatformOption(target.platform, { collection_id: event.target.value })
                        }
                        placeholder={t("smartCopy.publish.collectionIdPlaceholder")}
                      />
                    </label>
                    <label>
                      <span>{t("smartCopy.publish.collectionName")}</span>
                      <input
                        className="input"
                        type="text"
                        value={workspace.publicationPlatformOptions[target.platform]?.collection_name ?? ""}
                        onChange={(event) =>
                          workspace.updatePublicationPlatformOption(target.platform, { collection_name: event.target.value })
                        }
                        placeholder={t("smartCopy.publish.collectionNamePlaceholder")}
                      />
                    </label>
                    <label>
                      <span>{t("smartCopy.publish.category")}</span>
                      <input
                        className="input"
                        type="text"
                        value={workspace.publicationPlatformOptions[target.platform]?.category ?? ""}
                        onChange={(event) =>
                          workspace.updatePublicationPlatformOption(target.platform, { category: event.target.value })
                        }
                        placeholder={t("smartCopy.publish.categoryPlaceholder")}
                      />
                    </label>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {workspace.publish.error ? <div className="notice top-gap">{String(workspace.publish.error)}</div> : null}
        {workspace.publicationPlan.data?.existing_attempts?.length ? (
          <section className="panel top-gap">
            <PanelHeader title={t("smartCopy.publish.historyTitle")} description={t("smartCopy.publish.historyDescription")} />
            <div className="timeline-list">
              {workspace.publicationPlan.data.existing_attempts.slice(0, 6).map((attempt) => (
                <div className="timeline-item" key={attempt.id}>
                  <div className="toolbar">
                    <strong>{attempt.platform_label || attempt.platform}</strong>
                    <span className={`status-pill ${attempt.status === "failed" ? "failed" : attempt.status === "published" ? "done" : "running"}`}>
                      {publicationAttemptStatusLabel(attempt.status)}
                    </span>
                  </div>
                  <div className="muted">
                    {attempt.account_label} · {attempt.operator_summary || attempt.run_status || t("smartCopy.publish.waitingRunner")}
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <div className="toolbar top-gap">
          <button
            className="button primary"
            type="button"
            disabled={
              !workspace.result ||
              !workspace.publicationPlan.data?.publish_ready ||
              !workspace.selectedPlatformIds.length ||
              workspace.publish.isPending
            }
            onClick={() => workspace.publish.mutate()}
          >
            {workspace.publish.isPending ? t("smartCopy.publish.submitting") : t("smartCopy.publish.submit")}
          </button>
          {!workspace.result ? <span className="muted">{t("smartCopy.publish.needGenerate")}</span> : null}
        </div>
      </PageSection>

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
                  {generateTaskStatusLabel(task.status)} · {task.folder_path.split(/[\\/]/).filter(Boolean).at(-1) || task.folder_path}
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
              <strong>{task.folder_path.split(/[\\/]/).filter(Boolean).at(-1) || task.folder_path}</strong>
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
  return !["completed", "blocked", "failed", "cancelled"].includes(task.status);
}

function taskStatusTone(status: string): string {
  if (status === "completed") return "done";
  if (status === "blocked") return "failed";
  if (status === "failed") return "failed";
  return "running";
}

function publicationStatusTone(status: string): string {
  if (status === "published" || status === "draft_created" || status === "scheduled_pending") return "done";
  if (status === "failed") return "failed";
  return "running";
}

function publicationAttemptUrl(attempt: PublicationAttempt | null): string {
  return String(attempt?.public_url || attempt?.external_url || "").trim();
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

function generateTaskStatusLabel(status: string): string {
  if (status === "queued") return "已排队";
  if (status === "running") return "生成中";
  if (status === "completed") return "已完成";
  if (status === "blocked") return "有阻断项";
  if (status === "failed") return "失败";
  return status || "待处理";
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
          {platform.publish_ready === false && platform.blocking_reasons?.length ? (
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
                <span>{platform.cover_path ? t("smartCopy.materials.coverReady") : t("smartCopy.materials.videoCover")}</span>
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
                      <span>{`${index + 1}. ${item}`}</span>
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
                {platform.cover_path ? <div className="muted">{platform.cover_path}</div> : null}
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function platformPreviewClass(platform: string): string {
  if (platform === "douyin") return "platform-preview-douyin";
  if (platform === "xiaohongshu") return "platform-preview-xiaohongshu";
  if (platform === "bilibili") return "platform-preview-bilibili";
  if (platform === "wechat-channels") return "platform-preview-wechat";
  return "platform-preview-default";
}
