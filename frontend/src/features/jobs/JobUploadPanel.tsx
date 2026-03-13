import type { UploadForm } from "./constants";
import type { SelectOption } from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type JobUploadPanelProps = {
  upload: UploadForm;
  languageOptions: SelectOption[];
  channelProfileOptions: SelectOption[];
  workflowModeOptions: SelectOption[];
  enhancementOptions: SelectOption[];
  onChange: (next: UploadForm) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
};

export function JobUploadPanel({
  upload,
  languageOptions,
  channelProfileOptions,
  workflowModeOptions,
  enhancementOptions,
  onChange,
  onSubmit,
  isSubmitting,
}: JobUploadPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel top-gap">
      <PanelHeader title={t("jobs.upload.title")} description={t("jobs.upload.description")} />
      <div className="form-grid three-up">
        <label>
          <span>{t("jobs.upload.file")}</span>
          <input
            className="input"
            type="file"
            accept="video/*"
            onChange={(event) => onChange({ ...upload, file: event.target.files?.[0] ?? null })}
          />
        </label>
        <SelectField
          label={t("jobs.upload.language")}
          value={upload.language}
          onChange={(event) => onChange({ ...upload, language: event.target.value })}
          options={languageOptions}
        />
        <SelectField
          label={t("jobs.upload.channelProfile")}
          value={upload.channelProfile}
          onChange={(event) => onChange({ ...upload, channelProfile: event.target.value })}
          options={channelProfileOptions}
        />
        <SelectField
          label={t("jobs.upload.workflowMode")}
          value={upload.workflowMode}
          onChange={(event) => onChange({ ...upload, workflowMode: event.target.value })}
          options={workflowModeOptions}
        />
      </div>
      <div className="upload-enhancement-panel top-gap">
        <div className="stat-label">{t("jobs.upload.enhancements")}</div>
        <div className="checklist-grid top-gap">
          {enhancementOptions.map((option) => {
            const checked = upload.enhancementModes.includes(option.value);
            return (
              <CheckboxField
                key={option.value}
                label={option.label}
                checked={checked}
                onChange={(event) =>
                  onChange({
                    ...upload,
                    enhancementModes: event.target.checked
                      ? [...upload.enhancementModes, option.value]
                      : upload.enhancementModes.filter((item) => item !== option.value),
                  })
                }
              />
            );
          })}
        </div>
      </div>
      <div className="toolbar top-gap">
        <button className="button primary" disabled={!upload.file || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? t("jobs.upload.submitting") : t("jobs.upload.submit")}
        </button>
        {upload.file && <span className="muted">{upload.file.name}</span>}
      </div>
    </section>
  );
}
