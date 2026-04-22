import type { GlossaryTerm } from "../../types";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import type { TermForm } from "./constants";

type GlossaryFormPanelProps = {
  editing: GlossaryTerm | null;
  form: TermForm;
  isSaving: boolean;
  autosaveState?: "idle" | "saving" | "saved" | "error";
  autosaveError?: string | null;
  onChange: (next: TermForm) => void;
  onSubmit: () => void;
  onReset: () => void;
};

export function GlossaryFormPanel({ editing, form, isSaving, autosaveState, autosaveError, onChange, onSubmit, onReset }: GlossaryFormPanelProps) {
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
        title={editing ? t("glossary.form.editTitle") : t("glossary.form.createTitle")}
        description={t("glossary.form.description")}
        actions={
          editing ? (
            <div className="toolbar">
              <span className={`status-pill ${autosaveTone}`}>{autosaveLabel}</span>
              <button className="button ghost" type="button" onClick={onReset}>{t("glossary.form.cancelEdit")}</button>
            </div>
          ) : undefined
        }
      />

      <div className="form-stack">
        <TextField label={t("glossary.form.wrongForms")} value={form.wrong_forms} onChange={(event) => onChange({ ...form, wrong_forms: event.target.value })} placeholder="GPT4, gpt4" />
        <TextField label={t("glossary.form.correctForm")} value={form.correct_form} onChange={(event) => onChange({ ...form, correct_form: event.target.value })} placeholder="GPT-4" />
        <SelectField
          label={t("glossary.form.scopeType")}
          value={form.scope_type}
          onChange={(event) => onChange({ ...form, scope_type: event.target.value })}
          options={[
            { value: "global", label: t("glossary.form.scope.global") },
            { value: "domain", label: t("glossary.form.scope.domain") },
            { value: "workflow_template", label: t("glossary.form.scope.workflowTemplate") },
          ]}
        />
        <TextField
          label={t("glossary.form.scopeValue")}
          value={form.scope_value}
          onChange={(event) => onChange({ ...form, scope_value: event.target.value })}
          placeholder="gear / ai / edc_tactical / tutorial_standard"
        />
        <SelectField
          label={t("glossary.form.category")}
          value={form.category}
          onChange={(event) => onChange({ ...form, category: event.target.value })}
          options={[
            { value: "", label: t("glossary.form.unset") },
            { value: "brand", label: t("glossary.form.brand") },
            { value: "model", label: t("glossary.form.model") },
            { value: "tech_term", label: t("glossary.form.techTerm") },
            { value: "person", label: t("glossary.form.person") },
          ]}
        />
        <TextField
          label={t("glossary.form.contextHint")}
          value={form.context_hint}
          onChange={(event) => onChange({ ...form, context_hint: event.target.value })}
          placeholder="只在数码开箱里使用"
        />
        {autosaveError && editing && <div className="notice">{autosaveError}</div>}
        {!editing && (
          <FormActions>
            <button className="button primary" type="button" onClick={onSubmit} disabled={isSaving}>
              {isSaving ? t("glossary.form.saving") : t("glossary.form.create")}
            </button>
          </FormActions>
        )}
      </div>
    </section>
  );
}
