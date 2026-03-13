import { api } from "../../api";
import { useI18n } from "../../i18n";
import type { ContentProfileReview } from "../../types";
import { statusLabel } from "../../utils";
import { CONTENT_FIELDS, contentFieldLabel } from "./constants";

type JobContentProfileSectionProps = {
  jobId: string;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isSaving: boolean;
  reviewMode?: boolean;
  onFieldChange: (field: string, value: string) => void;
  onKeywordsChange: (value: string) => void;
  onConfirm: () => void;
};

export function JobContentProfileSection({
  jobId,
  contentProfile,
  contentSource,
  contentDraft,
  contentKeywords,
  isSaving,
  reviewMode = false,
  onFieldChange,
  onKeywordsChange,
  onConfirm,
}: JobContentProfileSectionProps) {
  const { t } = useI18n();

  return (
    <section className="detail-block">
      <div className="detail-key">{t("jobs.contentReview.title")}</div>
      {contentSource ? (
        <>
          <div className="thumbnail-strip">
            {[0, 1, 2].map((index) => (
              <img key={index} className="profile-thumb" src={api.contentProfileThumbnailUrl(jobId, index)} alt={`thumbnail-${index}`} />
            ))}
          </div>
          <div className="form-stack">
            {CONTENT_FIELDS.map((field) => (
              <label key={field}>
                <span>{contentFieldLabel(field)}</span>
                <input
                  className="input"
                  value={String(contentDraft[field] ?? contentSource[field] ?? "")}
                  onChange={(event) => onFieldChange(field, event.target.value)}
                />
              </label>
            ))}
            <label>
              <span>{t("jobs.contentReview.keywords")}</span>
              <input className="input" value={contentKeywords} onChange={(event) => onKeywordsChange(event.target.value)} />
            </label>
          </div>
          <div className="toolbar top-gap">
            <button className="button primary" onClick={onConfirm} disabled={isSaving}>
              {isSaving ? t("jobs.contentReview.confirming") : reviewMode ? "确认配置并继续执行" : t("jobs.contentReview.confirm")}
            </button>
            <span className="muted">{t("jobs.contentReview.status")}：{contentProfile?.review_step_status ? statusLabel(contentProfile.review_step_status) : "—"}</span>
          </div>
        </>
      ) : (
        <div className="muted">{t("jobs.contentReview.noData")}</div>
      )}
    </section>
  );
}
