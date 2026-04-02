import { api } from "../../api";
import { useI18n } from "../../i18n";
import type { ContentProfileReview } from "../../types";
import { statusLabel } from "../../utils";
import { CONTENT_FIELDS, contentFieldLabel } from "./constants";

const IDENTITY_SUPPORT_SOURCE_LABELS: Record<string, string> = {
  transcript: "字幕",
  source_name: "文件名",
  visible_text: "画面文字",
  evidence: "外部证据",
};

function getTextValue(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

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
  const contentUnderstanding = contentSource
    && typeof contentSource.content_understanding === "object"
    && !Array.isArray(contentSource.content_understanding)
    ? (contentSource.content_understanding as Record<string, unknown>)
    : null;
  const effectiveContentSource = contentUnderstanding
    ? {
        ...contentSource,
        subject_type:
          getTextValue(contentUnderstanding.subject_type)
          || getTextValue(contentUnderstanding.primary_subject)
          || getTextValue(contentUnderstanding.video_type)
          || getTextValue(contentSource?.subject_type),
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
    : contentSource;
  const identityReview = contentProfile?.identity_review;
  const evidenceBundle = identityReview?.evidence_bundle;
  const supportSources = (identityReview?.support_sources ?? []).map((item) => IDENTITY_SUPPORT_SOURCE_LABELS[item] ?? item);
  const matchedGlossaryAliases = [
    evidenceBundle?.matched_glossary_aliases?.brand?.length
      ? `品牌：${evidenceBundle.matched_glossary_aliases.brand.join("、")}`
      : "",
    evidenceBundle?.matched_glossary_aliases?.model?.length
      ? `型号：${evidenceBundle.matched_glossary_aliases.model.join("、")}`
      : "",
  ].filter(Boolean);
  const hasIdentityEvidence = Boolean(
    identityReview
    && (
      identityReview.required
      || evidenceBundle?.matched_subtitle_snippets?.length
      || matchedGlossaryAliases.length
      || evidenceBundle?.matched_source_name_terms?.length
      || evidenceBundle?.matched_visible_text_terms?.length
      || evidenceBundle?.matched_evidence_terms?.length
    ),
  );

  return (
    <section className="detail-block">
      <div className="detail-key">{t("jobs.contentReview.title")}</div>
      {effectiveContentSource ? (
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
                  value={String(contentDraft[field] ?? effectiveContentSource[field] ?? "")}
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
          {contentProfile?.review_step_detail ? (
            <div className="muted top-gap">{contentProfile.review_step_detail}</div>
          ) : null}
          {hasIdentityEvidence ? (
            <div className="timeline-list top-gap">
              <div className="timeline-item">
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
