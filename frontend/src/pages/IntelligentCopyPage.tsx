import { Link } from "react-router-dom";

import { SelectField } from "../components/forms/SelectField";
import { TextField } from "../components/forms/TextField";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { publicationAttemptStatusLabel, useIntelligentCopyWorkspace } from "../features/intelligentCopy/useIntelligentCopyWorkspace";
import { useI18n } from "../i18n";
import { copyStylePresets } from "../stylePresets";

export function IntelligentCopyPage() {
  const { t } = useI18n();
  const workspace = useIntelligentCopyWorkspace();
  const selectedPublicationProfile = workspace.publicationProfiles.find((profile) => profile.id === workspace.selectedPublicationProfileId);
  const selectedTargets = (workspace.publicationPlan.data?.targets ?? []).filter((target) =>
    workspace.selectedPlatformIds.includes(target.platform),
  );

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("smartCopy.page.eyebrow")}
        title={t("smartCopy.page.title")}
        description={t("smartCopy.page.description")}
        summary={[
          { label: "直接读取", value: "成片 + 字幕 + 可选封面", detail: "先对现成目录出发布物料" },
          { label: "账号选择", value: "创作者凭据", detail: "从创作者档案选择 browser-agent 登录账号" },
          { label: "一键发布", value: "平台可勾选", detail: "按平台创建发布任务并交给发布运行器" },
        ]}
        actions={
          <div className="toolbar">
            <Link className="button ghost" to="/creator-profiles">
              {t("smartCopy.publish.configureAccounts")}
            </Link>
            <button
              type="button"
              className="button ghost"
              onClick={() => workspace.inspect.mutate(workspace.folderPath)}
              disabled={!workspace.folderPath.trim() || workspace.inspect.isPending}
            >
              {workspace.inspect.isPending ? t("smartCopy.page.inspecting") : t("smartCopy.page.inspect")}
            </button>
            <button
              type="button"
              className="button primary"
              onClick={() => workspace.generate.mutate({ folderPath: workspace.folderPath, copyStyle: workspace.copyStyle })}
              disabled={!workspace.folderPath.trim() || workspace.generate.isPending}
            >
              {workspace.generate.isPending ? t("smartCopy.page.generating") : t("smartCopy.page.generate")}
            </button>
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
              workspace.result?.material_dir ? (
                <button type="button" className="button ghost" onClick={() => workspace.openFolder.mutate(workspace.result?.material_dir || "")}>
                  {t("smartCopy.page.openOutput")}
                </button>
              ) : null
            }
          />
          <div className="form-grid">
            <TextField
              label={t("smartCopy.form.folderPath")}
              value={workspace.folderPath}
              onChange={(event) => workspace.setFolderPath(event.target.value)}
              placeholder={t("smartCopy.form.folderPlaceholder")}
            />
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
        eyebrow={t("smartCopy.publish.eyebrow")}
        title={t("smartCopy.publish.title")}
        description={t("smartCopy.publish.description")}
      >
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
                {(selectedPublicationProfile.creator_profile?.publishing?.platform_credentials ?? []).map((credential) => (
                  <span className="mode-chip subtle" key={credential.id ?? `${credential.platform}-${credential.account_label}`}>
                    {credential.platform_label || credential.platform} · {credential.account_label || credential.credential_ref || t("smartCopy.publish.unnamedAccount")}
                  </span>
                ))}
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

      <PageSection
        eyebrow={t("smartCopy.results.eyebrow")}
        title={t("smartCopy.results.title")}
        description={t("smartCopy.results.description")}
      >
        {workspace.result ? (
          <div className="panel-grid two-up">
            {workspace.result.platforms.map((platform) => (
              <section key={platform.key} className="panel">
                <PanelHeader
                  title={platform.label}
                  description={platform.constraints.rule_note}
                  actions={
                    <div className="toolbar">
                      <button type="button" className="button ghost" onClick={() => workspace.copyText(platform.full_copy, `${platform.label} 已复制`)}>
                        {t("smartCopy.results.copyAll")}
                      </button>
                      {platform.cover_path ? (
                        <button type="button" className="button ghost" onClick={() => workspace.openFolder.mutate(platform.cover_path || "")}>
                          {t("smartCopy.results.openCover")}
                        </button>
                      ) : null}
                    </div>
                  }
                />
                {platform.has_title ? (
                  <div className="list-stack">
                    <div className="row-title">{platform.title_label}</div>
                    {platform.titles.map((title, index) => (
                      <div key={`${platform.key}-${index}`} className="panel-subcard">
                        <div className="row-title">{`${index + 1}. ${title}`}</div>
                        <button
                          type="button"
                          className="button ghost"
                          onClick={() => workspace.copyText(title, `${platform.label} 标题 ${index + 1} 已复制`)}
                        >
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
                    <button type="button" className="button ghost" onClick={() => workspace.copyText(platform.body, `${platform.label} 正文已复制`)}>
                      {t("smartCopy.results.copyBody")}
                    </button>
                  </div>
                  <div>
                    <div className="row-title">{platform.tag_label}</div>
                    <pre className="panel-code-block">{platform.tags_copy || "—"}</pre>
                    <button type="button" className="button ghost" onClick={() => workspace.copyText(platform.tags_copy, `${platform.label} 标签已复制`)}>
                      {t("smartCopy.results.copyTags")}
                    </button>
                  </div>
                  <div className="muted">
                    {`${t("smartCopy.results.constraints")}${platform.constraints.title_limit}/${platform.constraints.body_limit}/${platform.constraints.tag_limit}`}
                  </div>
                  {platform.cover_path ? <div className="muted">{platform.cover_path}</div> : null}
                </div>
              </section>
            ))}
          </div>
        ) : (
          <EmptyState message={t("smartCopy.results.empty")} />
        )}
      </PageSection>
    </section>
  );
}
