import type { RootForm } from "./constants";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import type { ConfigProfile, SelectOption } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { classNames } from "../../utils";

const EDIT_MODE_OPTIONS: Array<{ value: RootForm["edit_mode"]; labelKey: string }> = [
  { value: "auto", labelKey: "watch.form.editModeAuto" },
  { value: "talking_head", labelKey: "watch.form.editModeTalkingHead" },
  { value: "tutorial", labelKey: "watch.form.editModeTutorial" },
  { value: "vlog", labelKey: "watch.form.editModeVlog" },
  { value: "highlight", labelKey: "watch.form.editModeHighlight" },
  { value: "multi_material", labelKey: "watch.form.editModeMultiMaterial" },
];

const AUTOMATION_LEVEL_OPTIONS: Array<{ value: RootForm["automation_level"]; labelKey: string }> = [
  { value: "conservative", labelKey: "watch.form.automationConservative" },
  { value: "standard", labelKey: "watch.form.automationStandard" },
  { value: "richer", labelKey: "watch.form.automationRicher" },
];

const MATERIAL_USAGE_OPTIONS: Array<{ value: RootForm["material_usage"]; labelKey: string }> = [
  { value: "main_only", labelKey: "watch.form.materialMainOnly" },
  { value: "all_uploaded", labelKey: "watch.form.materialAllUploaded" },
  { value: "selected_uploaded", labelKey: "watch.form.materialSelectedUploaded" },
];

type WatchRootFormPanelProps = {
  form: RootForm;
  configProfileOptions: SelectOption[];
  boundConfigProfile?: ConfigProfile | null;
  effectiveConfigProfile?: ConfigProfile | null;
  workflowTemplateOptions: SelectOption[];
  isEditing: boolean;
  isSaving: boolean;
  isDeleting: boolean;
  autosaveState?: "idle" | "saving" | "saved" | "error";
  autosaveError?: string | null;
  onChange: (next: RootForm) => void;
  onSubmit: () => void;
  onDelete: () => void;
};

export function WatchRootFormPanel({
  form,
  configProfileOptions,
  boundConfigProfile,
  effectiveConfigProfile,
  workflowTemplateOptions,
  isEditing,
  isSaving,
  isDeleting,
  autosaveState,
  autosaveError,
  onChange,
  onSubmit,
  onDelete,
}: WatchRootFormPanelProps) {
  const { t } = useI18n();
  const autosaveTone =
    autosaveState === "saving" ? "running" : autosaveState === "error" ? "failed" : autosaveState === "saved" ? "done" : "";
  const autosaveLabel =
    autosaveState === "saving"
      ? t("autosave.saving")
      : autosaveState === "error"
        ? t("autosave.error")
        : autosaveState === "saved"
          ? t("autosave.saved")
          : t("autosave.idle");

  return (
    <section className="panel">
      <PanelHeader
        title={isEditing ? t("watch.form.editTitle") : t("watch.form.createTitle")}
        description="设置监听目录、任务类型、创作者配置绑定和进入剪辑队列后的启动方式。"
        actions={isEditing ? <span className={`status-pill ${autosaveTone}`}>{autosaveLabel}</span> : undefined}
      />
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div className="auto-task-form-section">
          <div className="auto-task-form-section-head">
            <strong>监听目录</strong>
            <span>检测这个目录里的新增素材。</span>
          </div>
          <TextField label={t("watch.form.path")} value={form.path} onChange={(event) => onChange({ ...form, path: event.target.value })} />
          <div className="field-row compact-top">
            <CheckboxField
              label={t("watch.form.recursive")}
              checked={form.recursive}
              onChange={(event) => onChange({ ...form, recursive: event.target.checked })}
            />
            <SelectField
              label={t("watch.form.scanMode")}
              value={form.scan_mode}
              onChange={(event) => onChange({ ...form, scan_mode: event.target.value as RootForm["scan_mode"] })}
              options={[
                { value: "fast", label: t("watch.form.fast") },
                { value: "precise", label: t("watch.form.precise") },
              ]}
            />
          </div>
        </div>

        <div className="auto-task-form-section">
          <div className="auto-task-form-section-head">
            <strong>任务类型</strong>
            <span>决定自动创建到队列里的剪辑任务形态。</span>
          </div>
          <div className="field-row compact-top">
            <SelectField
              label={t("watch.form.editMode")}
              value={form.edit_mode}
              onChange={(event) => onChange({ ...form, edit_mode: event.target.value as RootForm["edit_mode"] })}
              options={EDIT_MODE_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            />
            <SelectField
              label={t("watch.form.workflowTemplate")}
              value={form.workflow_template}
              onChange={(event) => onChange({ ...form, workflow_template: event.target.value })}
              options={workflowTemplateOptions}
            />
          </div>
          <div className="field-row compact-top">
            <SelectField
              label={t("watch.form.automationLevel")}
              value={form.automation_level}
              onChange={(event) => onChange({ ...form, automation_level: event.target.value as RootForm["automation_level"] })}
              options={AUTOMATION_LEVEL_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            />
            <SelectField
              label={t("watch.form.materialUsage")}
              value={form.material_usage}
              onChange={(event) => onChange({ ...form, material_usage: event.target.value as RootForm["material_usage"] })}
              options={MATERIAL_USAGE_OPTIONS.map((option) => ({ value: option.value, label: t(option.labelKey) }))}
            />
            <div className="watch-flow-mode-field">
              <span>{t("watch.form.jobFlowMode")}</span>
              <div className="watch-flow-mode-control" role="group" aria-label={t("watch.form.jobFlowMode")}>
                {(["auto", "smart_assist"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    className={classNames("watch-flow-mode-toggle", form.job_flow_mode === mode && "active")}
                    onClick={() => onChange({ ...form, job_flow_mode: mode })}
                  >
                    {t(`jobs.flowMode.${mode}`)}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <TextField
            label={t("watch.form.outputDir")}
            value={form.output_dir}
            onChange={(event) => onChange({ ...form, output_dir: event.target.value })}
          />
        </div>

        <div className="auto-task-form-section warm">
          <div className="auto-task-form-section-head">
            <strong>创作者配置绑定</strong>
            <span>自动创建任务时带入这套创作者、文案、包装和风格配置。</span>
          </div>
          <SelectField
            label="创作者配置"
            value={form.config_profile_id}
            onChange={(event) => onChange({ ...form, config_profile_id: event.target.value })}
            options={configProfileOptions}
          />
          <div className="notice compact-top">
            <div className="stat-label">
              {form.config_profile_id ? t("watch.form.configProfileBoundTitle") : t("watch.form.configProfileFallbackTitle")}
            </div>
            <div className="muted compact-top">
              {form.config_profile_id
                ? t("watch.form.configProfileBoundDescription")
                : t("watch.form.configProfileFallbackDescription")}
            </div>
            {effectiveConfigProfile ? (
              <>
                <div className="compact-top">
                  <strong>{effectiveConfigProfile.name}</strong>
                  {boundConfigProfile ? null : <span className="status-pill done" style={{ marginLeft: 8 }}>{t("watch.form.followingActiveProfile")}</span>}
                  {effectiveConfigProfile.is_active ? <span className="status-pill done" style={{ marginLeft: 8 }}>{t("watch.form.currentActiveProfile")}</span> : null}
                </div>
                {effectiveConfigProfile.description ? <div className="muted compact-top">{effectiveConfigProfile.description}</div> : null}
                <div className="muted compact-top">{t("watch.form.profileUpdatedAt")}: {new Date(effectiveConfigProfile.updated_at).toLocaleString()}</div>
                <div className="config-profile-summary-grid compact-top">
                  {buildProfileSummaryGroups(effectiveConfigProfile).map((group) => (
                    <article key={`${effectiveConfigProfile.id}-${group.label}`} className="config-profile-summary-card">
                      <div className="stat-label">{group.label}</div>
                      <div className="config-profile-summary-tags compact-top">
                        {group.items.map((item) => (
                          <span key={`${effectiveConfigProfile.id}-${group.label}-${item}`} className="status-pill config-profile-summary-tag">
                            {item}
                          </span>
                        ))}
                      </div>
                    </article>
                  ))}
                </div>
              </>
            ) : null}
          </div>
        </div>

        <div className="auto-task-form-section">
          <div className="auto-task-form-section-head">
            <strong>入队策略</strong>
            <span>检测到新文件后，自动任务会创建普通剪辑任务。</span>
          </div>
          <div className="auto-task-policy-control" role="group" aria-label="入队策略">
            {([
              {
                value: "full_auto",
                title: "检测到新文件后立即开始",
                description: "创建队列任务并自动启动剪辑流程。",
              },
              {
                value: "task_only",
                title: "加入队列，手动开始",
                description: "只创建待处理任务，回到制片队列人工启动。",
              },
            ] as const).map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={classNames("auto-task-policy-option", form.ingest_mode === option.value && "active")}
                  onClick={() => onChange({ ...form, ingest_mode: option.value })}
                >
                  <strong>{option.title}</strong>
                  <span>{option.description}</span>
                </button>
              ))}
          </div>
          <div className="notice compact-top">
            <div className="stat-label">{t("watch.form.ingestModeSummaryTitle")}</div>
            <div className="muted compact-top">
              {form.ingest_mode === "task_only"
                ? t("watch.form.ingestModeTaskOnlyDescription")
                : t("watch.form.ingestModeFullAutoDescription")}
            </div>
            <div className="muted compact-top">{t("watch.form.productControlSummary")
              .replace("{editMode}", t(`watch.form.editMode.${form.edit_mode}`))
              .replace("{automationLevel}", t(`watch.form.automationLevel.${form.automation_level}`))
              .replace("{materialUsage}", t(`watch.form.materialUsage.${form.material_usage}`))}
            </div>
            {form.job_flow_mode === "smart_assist" ? (
              <div className="muted compact-top">{t("watch.form.jobFlowModeSmartAssistDescription")}</div>
            ) : null}
          </div>
        </div>

        <div className="field-row">
          <CheckboxField label={t("watch.form.enabled")} checked={form.enabled} onChange={(event) => onChange({ ...form, enabled: event.target.checked })} />
        </div>
        {autosaveError && isEditing && <div className="notice">{autosaveError}</div>}
        {isEditing ? (
          <FormActions>
            <button className="button danger" type="button" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? t("watch.form.deleting") : t("watch.form.delete")}
            </button>
          </FormActions>
        ) : (
          <FormActions>
            <button className="button primary" type="submit" disabled={isSaving}>
              {isSaving ? t("watch.form.saving") : t("watch.form.create")}
            </button>
          </FormActions>
        )}
      </form>
    </section>
  );
}

function buildProfileSummaryGroups(profile: ConfigProfile) {
  return [
    {
      label: "工作流",
      items: [
        `方言 ${profile.transcription_dialect || "默认"}`,
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
