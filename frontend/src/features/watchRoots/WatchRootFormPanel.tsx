import type { RootForm } from "./constants";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import type { SelectOption } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type WatchRootFormPanelProps = {
  form: RootForm;
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
          label={t("watch.form.channelProfile")}
          value={form.workflow_template}
          onChange={(event) => onChange({ ...form, workflow_template: event.target.value })}
          options={workflowTemplateOptions}
        />
        <div className="field-row">
          <SelectField
            label={t("watch.form.scanMode")}
            value={form.scan_mode}
            onChange={(event) => onChange({ ...form, scan_mode: event.target.value as RootForm["scan_mode"] })}
            options={[
              { value: "fast", label: t("watch.form.fast") },
              { value: "precise", label: t("watch.form.precise") },
            ]}
          />
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
