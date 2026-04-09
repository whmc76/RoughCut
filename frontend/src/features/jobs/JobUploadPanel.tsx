import { useEffect, useState } from "react";

import type { UploadForm } from "./constants";
import type { SelectOption } from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { Field } from "../../components/forms/Field";
import { SelectField } from "../../components/forms/SelectField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type JobUploadPanelProps = {
  upload: UploadForm;
  languageOptions: SelectOption[];
  workflowTemplateOptions: SelectOption[];
  workflowModeOptions: SelectOption[];
  enhancementOptions: SelectOption[];
  onChange: (next: UploadForm) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
};

export function JobUploadPanel({
  upload,
  languageOptions,
  workflowTemplateOptions,
  workflowModeOptions,
  enhancementOptions,
  onChange,
  onSubmit,
  isSubmitting,
}: JobUploadPanelProps) {
  const { t } = useI18n();
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!upload.file || typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return undefined;
    }

    const objectUrl = URL.createObjectURL(upload.file);
    setPreviewUrl(objectUrl);
    return () => {
      if (typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [upload.file]);

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
          value={upload.workflowTemplate}
          onChange={(event) => onChange({ ...upload, workflowTemplate: event.target.value })}
          options={workflowTemplateOptions}
        />
        <label>
          <span>{t("jobs.upload.outputDir")}</span>
          <input
            className="input"
            type="text"
            value={upload.outputDir}
            onChange={(event) => onChange({ ...upload, outputDir: event.target.value })}
            placeholder={t("jobs.upload.outputDir")}
          />
        </label>
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
      <Field label={t("jobs.upload.videoDescription")}>
        <textarea
          className="input"
          rows={5}
          value={upload.videoDescription}
          onChange={(event) => onChange({ ...upload, videoDescription: event.target.value })}
          placeholder={t("jobs.upload.videoDescriptionPlaceholder")}
        />
      </Field>
      <section className="job-upload-preview top-gap" aria-label={t("jobs.upload.previewTitle")}>
        <div className="job-upload-preview-header">
          <strong>{t("jobs.upload.previewTitle")}</strong>
          <span className="muted">{t("jobs.upload.previewDescription")}</span>
        </div>
        {previewUrl ? (
          <video
            className="packaging-video-preview job-upload-preview-player"
            controls
            playsInline
            preload="metadata"
            src={previewUrl}
            data-testid="job-upload-video-preview"
          />
        ) : (
          <div className="job-upload-preview-empty muted">{t("jobs.upload.previewEmpty")}</div>
        )}
      </section>
      <div className="toolbar top-gap">
        <button className="button primary" disabled={!upload.file || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? t("jobs.upload.submitting") : t("jobs.upload.submit")}
        </button>
        {upload.file && <span className="muted">{upload.file.name}</span>}
      </div>
    </section>
  );
}
