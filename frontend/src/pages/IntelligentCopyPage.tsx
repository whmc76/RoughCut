import { SelectField } from "../components/forms/SelectField";
import { TextField } from "../components/forms/TextField";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useIntelligentCopyWorkspace } from "../features/intelligentCopy/useIntelligentCopyWorkspace";
import { useI18n } from "../i18n";
import { copyStylePresets } from "../stylePresets";

export function IntelligentCopyPage() {
  const { t } = useI18n();
  const workspace = useIntelligentCopyWorkspace();

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("smartCopy.page.eyebrow")}
        title={t("smartCopy.page.title")}
        description={t("smartCopy.page.description")}
        summary={[
          { label: "直接读取", value: "成片 + 字幕 + 可选封面", detail: "不走任务队列，直接对现成目录出发布物料" },
          { label: "一次生成", value: "8 个平台", detail: "标题、正文、标签和封面一起写回目录" },
          { label: "快速复制", value: "平台独立物料卡", detail: "每个平台都给单独复制入口和保存文件" },
        ]}
        actions={
          <div className="toolbar">
            <button
              className="button ghost"
              onClick={() => workspace.inspect.mutate(workspace.folderPath)}
              disabled={!workspace.folderPath.trim() || workspace.inspect.isPending}
            >
              {workspace.inspect.isPending ? t("smartCopy.page.inspecting") : t("smartCopy.page.inspect")}
            </button>
            <button
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
                <button className="button ghost" onClick={() => workspace.openFolder.mutate(workspace.result?.material_dir || "")}>
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
                      <button className="button ghost" onClick={() => workspace.copyText(platform.full_copy, `${platform.label} 已复制`)}>
                        {t("smartCopy.results.copyAll")}
                      </button>
                      {platform.cover_path ? (
                        <button className="button ghost" onClick={() => workspace.openFolder.mutate(platform.cover_path || "")}>
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
                    <button className="button ghost" onClick={() => workspace.copyText(platform.body, `${platform.label} 正文已复制`)}>
                      {t("smartCopy.results.copyBody")}
                    </button>
                  </div>
                  <div>
                    <div className="row-title">{platform.tag_label}</div>
                    <pre className="panel-code-block">{platform.tags_copy || "—"}</pre>
                    <button className="button ghost" onClick={() => workspace.copyText(platform.tags_copy, `${platform.label} 标签已复制`)}>
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
