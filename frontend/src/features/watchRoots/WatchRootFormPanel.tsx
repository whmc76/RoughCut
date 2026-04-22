import type { RootForm } from "./constants";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import type { ConfigProfile, SelectOption } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { getTranscriptionProviderLabel } from "../settings/helpers";

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
        description={t("watch.form.description")}
        actions={isEditing ? <span className={`status-pill ${autosaveTone}`}>{autosaveLabel}</span> : undefined}
      />
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <TextField label={t("watch.form.path")} value={form.path} onChange={(event) => onChange({ ...form, path: event.target.value })} />
        <SelectField
          label={t("watch.form.configProfile")}
          value={form.config_profile_id}
          onChange={(event) => onChange({ ...form, config_profile_id: event.target.value })}
          options={configProfileOptions}
        />
        <div className="notice">
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
        <SelectField
          label={t("watch.form.workflowTemplate")}
          value={form.workflow_template}
          onChange={(event) => onChange({ ...form, workflow_template: event.target.value })}
          options={workflowTemplateOptions}
        />
        <TextField
          label={t("watch.form.outputDir")}
          value={form.output_dir}
          onChange={(event) => onChange({ ...form, output_dir: event.target.value })}
        />
        <div className="field-row">
          <CheckboxField
            label={t("watch.form.recursive")}
            checked={form.recursive}
            onChange={(event) => onChange({ ...form, recursive: event.target.checked })}
          />
        </div>
        <div className="field-row">
          <SelectField
            label={t("watch.form.ingestMode")}
            value={form.ingest_mode}
            onChange={(event) => onChange({ ...form, ingest_mode: event.target.value as RootForm["ingest_mode"] })}
            options={[
              { value: "task_only", label: t("watch.form.ingestModeTaskOnly") },
              { value: "full_auto", label: t("watch.form.ingestModeFullAuto") },
            ]}
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
        <div className="notice">
          <div className="stat-label">{t("watch.form.ingestModeSummaryTitle")}</div>
          <div className="muted compact-top">
            {form.ingest_mode === "task_only"
              ? t("watch.form.ingestModeTaskOnlyDescription")
              : t("watch.form.ingestModeFullAutoDescription")}
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
