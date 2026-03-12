import { api } from "../../api";
import type { ContentProfileReview } from "../../types";
import { CONTENT_FIELDS } from "./constants";

type JobContentProfileSectionProps = {
  jobId: string;
  contentProfile?: ContentProfileReview;
  contentSource: Record<string, unknown> | null;
  contentDraft: Record<string, unknown>;
  contentKeywords: string;
  isSaving: boolean;
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
  onFieldChange,
  onKeywordsChange,
  onConfirm,
}: JobContentProfileSectionProps) {
  return (
    <section className="detail-block">
      <div className="detail-key">内容核对</div>
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
                <span>{field}</span>
                <input
                  className="input"
                  value={String(contentDraft[field] ?? contentSource[field] ?? "")}
                  onChange={(event) => onFieldChange(field, event.target.value)}
                />
              </label>
            ))}
            <label>
              <span>keywords</span>
              <input className="input" value={contentKeywords} onChange={(event) => onKeywordsChange(event.target.value)} />
            </label>
          </div>
          <div className="toolbar top-gap">
            <button className="button primary" onClick={onConfirm} disabled={isSaving}>
              {isSaving ? "正在保存..." : "确认内容信息"}
            </button>
            <span className="muted">状态：{contentProfile?.review_step_status || "—"}</span>
          </div>
        </>
      ) : (
        <div className="muted">暂无内容核对数据</div>
      )}
    </section>
  );
}
