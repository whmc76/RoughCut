import { api } from "../../api";
import { useI18n } from "../../i18n";
import type { ContentProfileReview } from "../../types";
import { statusLabel } from "../../utils";
import { CONTENT_FIELDS, contentFieldLabel } from "./constants";
import {
  formatIdentityEvidenceGlossaryAliases,
  formatIdentityEvidenceSources,
  getTextValue,
  getVideoTypeOptions,
  hasIdentityEvidence as hasIdentityEvidenceReview,
  normalizeVideoTypeValue,
} from "./contentProfile";

type JobContentProfileSectionProps = {
  jobId: string;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isSaving: boolean;
  reviewMode?: boolean;
  showThumbnails?: boolean;
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
  showThumbnails = true,
  onFieldChange,
  onKeywordsChange,
  onConfirm,
}: JobContentProfileSectionProps) {
  const { t, locale } = useI18n();
  const videoTypeOptions = getVideoTypeOptions(locale);
  const contentDraftUnderstanding =
    typeof contentDraft.content_understanding === "object" && !Array.isArray(contentDraft.content_understanding)
      ? (contentDraft.content_understanding as Record<string, unknown>)
      : null;
  const contentUnderstanding = contentSource
    && typeof contentSource.content_understanding === "object"
    && !Array.isArray(contentSource.content_understanding)
    ? (contentSource.content_understanding as Record<string, unknown>)
    : null;
  const resolvedVideoType = normalizeVideoTypeValue(
    [
      getTextValue(contentUnderstanding?.video_type),
      getTextValue(contentSource?.video_type),
      getTextValue(contentSource?.content_kind),
      getTextValue(contentSource?.subject_type),
    ].find(Boolean),
  );
  const fallbackSubjectType = getTextValue(contentSource?.subject_type);
  const effectiveContentSource: Record<string, unknown> = contentUnderstanding
      ? {
        ...contentSource,
        video_type: resolvedVideoType,
        subject_type:
          getTextValue(contentUnderstanding.primary_subject)
          || (normalizeVideoTypeValue(fallbackSubjectType) ? "" : fallbackSubjectType),
        video_theme:
          getTextValue(contentUnderstanding.video_theme)
          || getTextValue(contentSource?.video_theme),
        summary:
          getTextValue(contentUnderstanding.summary)
          || getTextValue(contentSource?.summary),
        hook_line:
          getTextValue(contentUnderstanding.hook_line)
          || getTextValue(contentSource?.hook_line),
        engagement_question:
          getTextValue(contentUnderstanding.question)
          || getTextValue(contentUnderstanding.engagement_question)
          || getTextValue(contentSource?.engagement_question)
          || getTextValue(contentSource?.question),
      }
    : {
      ...(contentSource ?? {}),
      video_type: resolvedVideoType,
      subject_type: normalizeVideoTypeValue(fallbackSubjectType) ? "" : fallbackSubjectType,
    };
  const identityReview = contentProfile?.identity_review;
  const evidenceBundle = identityReview?.evidence_bundle;
  const supportSources = formatIdentityEvidenceSources(identityReview?.support_sources ?? []);
  const matchedGlossaryAliases = formatIdentityEvidenceGlossaryAliases(evidenceBundle);
  const hasIdentityEvidence = hasIdentityEvidenceReview(identityReview);

  return (
    <section className={["detail-block", reviewMode ? "summary-review-editor" : ""].filter(Boolean).join(" ")}>
      <div className="detail-key">{t("jobs.contentReview.title")}</div>
      {effectiveContentSource ? (
        <>
          {showThumbnails ? (
            <div className="thumbnail-strip">
              {[0, 1, 2].map((index) => (
                <img
                  key={index}
                  className="profile-thumb"
                  loading="lazy"
                  decoding="async"
                  src={api.contentProfileThumbnailUrl(jobId, index)}
                  alt={`thumbnail-${index}`}
                />
              ))}
            </div>
          ) : null}
          <div className={["form-stack", reviewMode ? "summary-review-form-stack" : ""].filter(Boolean).join(" ")}>
            {CONTENT_FIELDS.map((field) => (
              <label key={field}>
                <span>{contentFieldLabel(field)}</span>
                {field === "video_type" ? (
                  <select
                    className="input"
                    value={normalizeVideoTypeValue(contentDraft[field] ?? contentDraftUnderstanding?.video_type ?? effectiveContentSource[field] ?? "")}
                    onChange={(event) => onFieldChange(field, event.target.value)}
                  >
                    {videoTypeOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input"
                    value={String(contentDraft[field] ?? effectiveContentSource[field] ?? "")}
                    onChange={(event) => onFieldChange(field, event.target.value)}
                  />
                )}
              </label>
            ))}
            <label>
              <span>{t("jobs.contentReview.keywords")}</span>
              <input className="input" value={contentKeywords} onChange={(event) => onKeywordsChange(event.target.value)} />
            </label>
          </div>
          <div className={["toolbar", "top-gap", reviewMode ? "summary-review-actions" : ""].filter(Boolean).join(" ")}>
            <button className="button primary" onClick={onConfirm} disabled={isSaving}>
              {isSaving ? t("jobs.contentReview.confirming") : reviewMode ? "确认配置并继续执行" : t("jobs.contentReview.confirm")}
            </button>
            <span className="muted">{t("jobs.contentReview.status")}：{contentProfile?.review_step_status ? statusLabel(contentProfile.review_step_status) : "—"}</span>
          </div>
          {contentProfile?.review_step_detail ? (
            <div className="muted top-gap">{contentProfile.review_step_detail}</div>
          ) : null}
          {hasIdentityEvidence ? (
            <div className="timeline-list top-gap">
              <div className={["timeline-item", reviewMode ? "summary-review-evidence-card" : ""].filter(Boolean).join(" ")}>
                <div className="toolbar">
                  <strong>主体证据包</strong>
                  {identityReview?.evidence_strength ? (
                    <span className={`status-pill ${identityReview.evidence_strength === "strong" ? "done" : "pending"}`}>
                      证据强度：{identityReview.evidence_strength}
                    </span>
                  ) : null}
                </div>
                <div>候选品牌：{evidenceBundle?.candidate_brand || "未识别"}</div>
                <div>候选型号：{evidenceBundle?.candidate_model || "未识别"}</div>
                {supportSources.length ? <div className="muted">支撑来源：{supportSources.join("、")}</div> : null}
                {matchedGlossaryAliases.length ? <div className="muted">命中词表别名：{matchedGlossaryAliases.join("；")}</div> : null}
                {evidenceBundle?.matched_source_name_terms?.length ? (
                  <div className="muted">文件名命中：{evidenceBundle.matched_source_name_terms.join("、")}</div>
                ) : null}
                {evidenceBundle?.matched_visible_text_terms?.length ? (
                  <div className="muted">画面文字命中：{evidenceBundle.matched_visible_text_terms.join("、")}</div>
                ) : null}
                {evidenceBundle?.matched_evidence_terms?.length ? (
                  <div className="muted">外部证据命中：{evidenceBundle.matched_evidence_terms.join("、")}</div>
                ) : null}
                {evidenceBundle?.matched_subtitle_snippets?.length ? (
                  <div className="compact-top">
                    {evidenceBundle.matched_subtitle_snippets.map((snippet) => (
                      <div key={snippet} className="muted">{snippet}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <div className="muted">{t("jobs.contentReview.noData")}</div>
      )}
    </section>
  );
}
