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

function moveFile(files: File[], fromIndex: number, toIndex: number): File[] {
  if (toIndex < 0 || toIndex >= files.length || fromIndex === toIndex) {
    return files;
  }
  const next = [...files];
  const [file] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, file);
  return next;
}

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
  const previewFile = upload.files[0] ?? null;
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const reorderFile = (fromIndex: number, toIndex: number) => {
    onChange({
      ...upload,
      files: moveFile(upload.files, fromIndex, toIndex),
    });
  };

  useEffect(() => {
    if (!previewFile || typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return undefined;
    }

    const objectUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(objectUrl);
    return () => {
      if (typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [previewFile]);

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
            multiple
            onChange={(event) => onChange({ ...upload, files: Array.from(event.target.files ?? []) })}
          />
          <span className="muted">{t("jobs.upload.fileHint")}</span>
        </label>
        <SelectField
          label={t("jobs.upload.language")}
          value={upload.language}
          onChange={(event) => onChange({ ...upload, language: event.target.value })}
          options={languageOptions}
        />
        <SelectField
          label={t("jobs.upload.workflowTemplate")}
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
          <span className="muted">
            {upload.files.length > 1 ? t("jobs.upload.previewMultipleDescription") : t("jobs.upload.previewDescription")}
          </span>
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
        <button type="button" className="button primary" disabled={upload.files.length === 0 || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? t("jobs.upload.submitting") : t("jobs.upload.submit")}
        </button>
        {upload.files.length > 0 ? (
          <span className="muted">
            {t("jobs.upload.selectedCount").replace("{count}", String(upload.files.length))}
          </span>
        ) : null}
      </div>
      {upload.files.length > 0 ? (
        <div className="job-upload-file-list top-gap" aria-label={t("jobs.upload.selectedList")}>
          {upload.files.map((file, index) => (
            <div key={`${file.name}-${file.size}-${index}`} className="job-upload-file-list-item">
              <div className="job-upload-file-list-copy">
                <span>{file.name}</span>
                <div className="job-upload-file-list-meta muted">
                  <span>{t("jobs.upload.fileOrder").replace("{index}", String(index + 1))}</span>
                  {index === 0 && previewUrl ? <span>{t("jobs.upload.previewBadge")}</span> : null}
                </div>
              </div>
              <div className="job-upload-file-list-actions">
                <button
                  type="button"
                  className="button ghost button-sm"
                  onClick={() => reorderFile(index, index - 1)}
                  disabled={index === 0}
                  aria-label={t("jobs.upload.moveUp")}
                >
                  {t("jobs.upload.moveUp")}
                </button>
                <button
                  type="button"
                  className="button ghost button-sm"
                  onClick={() => reorderFile(index, index + 1)}
                  disabled={index === upload.files.length - 1}
                  aria-label={t("jobs.upload.moveDown")}
                >
                  {t("jobs.upload.moveDown")}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
