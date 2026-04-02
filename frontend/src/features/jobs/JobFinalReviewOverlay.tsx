import type { Job, Report } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { StatCard } from "../../components/ui/StatCard";

export type FinalReviewJob = Job & {
  quality_score?: number | null;
  quality_grade?: string | null;
  quality_summary?: string | null;
  quality_issue_codes?: string[] | null;
};

type JobFinalReviewOverlayProps = {
  selectedJob: FinalReviewJob;
  report?: Report;
  className?: string;
  reviewDetail?: string | null;
  rejectNote?: string;
  previewSrc?: string | null;
  selectedRejectReasons?: string[];
  isPreviewing?: boolean;
  isDownloading?: boolean;
  isOpeningFolder?: boolean;
  isSubmittingDecision?: boolean;
  isApplyingSubtitleReview?: boolean;
  onPreview: () => void;
  onDownload: () => void;
  onOpenFolder: () => void;
  onRejectNoteChange?: (value: string) => void;
  onToggleRejectReason?: (reason: string) => void;
  onApplySubtitleReview?: (targetId: string, action: "accepted" | "rejected") => void;
  onApprove?: () => void;
  onReject?: () => void;
};

const REJECT_REASON_OPTIONS = ["字幕问题", "封面包装", "数字人口播", "节奏结构"] as const;

function formatQualityScore(score: number | null | undefined) {
  return typeof score === "number" && Number.isFinite(score) ? score.toFixed(1) : "—";
}

function buildSpotCheckItems(report?: Report) {
  if (!report?.items?.length) return [];
  return [...report.items]
    .sort((a, b) => a.index - b.index)
    .slice(0, 3)
    .map((item) => ({
      ...item,
      headline: item.text_final || item.text_norm || item.text_raw,
    }));
}

function buildPreviewTranscriptItems(report?: Report) {
  if (!report?.items?.length) return [];
  return [...report.items]
    .sort((a, b) => a.index - b.index)
    .slice(0, 6)
    .map((item) => ({
      ...item,
      headline: item.text_final || item.text_norm || item.text_raw,
    }));
}

function formatTime(seconds: number) {
  const totalSeconds = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

export function JobFinalReviewOverlay({
  selectedJob,
  report,
  className,
  reviewDetail,
  rejectNote = "",
  previewSrc = null,
  selectedRejectReasons = [],
  isPreviewing,
  isDownloading,
  isOpeningFolder,
  isSubmittingDecision,
  isApplyingSubtitleReview = false,
  onPreview,
  onDownload,
  onOpenFolder,
  onRejectNoteChange,
  onToggleRejectReason,
  onApplySubtitleReview,
  onApprove,
  onReject,
}: JobFinalReviewOverlayProps) {
  const qualityScore = selectedJob.quality_score ?? null;
  const qualityGrade = selectedJob.quality_grade?.trim() || null;
  const qualitySummary = selectedJob.quality_summary?.trim() || null;
  const issueCodes = (selectedJob.quality_issue_codes ?? []).filter(Boolean);
  const hasQuality = qualityScore !== null || Boolean(qualityGrade) || Boolean(qualitySummary) || issueCodes.length > 0;
  const spotCheckItems = buildSpotCheckItems(report);
  const previewTranscriptItems = buildPreviewTranscriptItems(report);
  const workflowDetails = [selectedJob.workflow_mode, selectedJob.enhancement_modes.length ? selectedJob.enhancement_modes.join(" / ") : "无增强"]
    .filter(Boolean)
    .join(" · ");

  return (
    <aside className={["panel detail-panel final-review-overlay", className].filter(Boolean).join(" ")}>
      <PanelHeader
        title="最终审核"
        description={[selectedJob.source_name, selectedJob.id].filter(Boolean).join(" · ")}
        actions={
          <div className="toolbar">
            <button className="button ghost" onClick={onPreview} disabled={Boolean(isPreviewing)}>
              {isPreviewing ? "打开中" : "打开成片"}
            </button>
            <button className="button ghost" onClick={onDownload} disabled={Boolean(isDownloading)}>
              {isDownloading ? "下载中" : "下载"}
            </button>
            <button className="button ghost" onClick={onOpenFolder} disabled={Boolean(isOpeningFolder)}>
              {isOpeningFolder ? "打开中" : "打开文件夹"}
            </button>
          </div>
        }
      />

      {previewSrc ? (
        <section className="detail-block">
          <div className="detail-key">成片预览</div>
          <div className="final-review-preview-frame" data-testid="final-review-preview-frame">
            <video
              data-testid="final-review-preview-player"
              className="packaging-video-preview final-review-preview-player"
              controls
              playsInline
              preload="metadata"
              src={previewSrc}
            />
          </div>
        </section>
      ) : null}

      <section className="detail-block">
        <div className="detail-key">审核证据</div>
        <div className="final-review-evidence-grid">
          <article className="activity-card final-review-evidence-card">
            <div className="detail-key">摘要与主题</div>
            <div className="final-review-evidence-copy">
              <strong>{selectedJob.content_subject?.trim() || "未生成主题摘要"}</strong>
              <div className="muted">
                {selectedJob.content_summary?.trim() || "当前没有可供审核的摘要，请先回看成片和字幕。"}
              </div>
              {selectedJob.avatar_delivery_summary ? (
                <div className="final-review-warning">
                  <span className={`status-pill ${selectedJob.avatar_delivery_status || "pending"}`}>数字人</span>
                  <span>{selectedJob.avatar_delivery_summary}</span>
                </div>
              ) : null}
            </div>
          </article>

          <article className="activity-card final-review-evidence-card">
            <div className="detail-key">字幕速览</div>
            {previewTranscriptItems.length ? (
              <div className="final-review-transcript-list">
                {previewTranscriptItems.map((item) => (
                  <div key={item.index} className="final-review-transcript-row">
                    <div className="final-review-transcript-meta">
                      #{item.index} · {formatTime(item.start)} - {formatTime(item.end)}
                    </div>
                    <div>{item.headline}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted">暂无可核对字幕</div>
            )}
          </article>
        </div>
      </section>

      <section className="detail-block">
        <div className="detail-key">当前需要你确认</div>
        <div className="activity-card">
          <strong>请决定这版成片是否可以继续后续包装</strong>
          <div className="muted compact-top">{reviewDetail || "优先检查质量评分、扣分项和字幕抽检，再决定通过或退回。"}</div>
          {(onApprove || onReject) ? (
            <>
              {onRejectNoteChange ? (
                <>
                  <div className="detail-key compact-top">问题分类</div>
                  <div className="mode-chip-list compact-top">
                    {REJECT_REASON_OPTIONS.map((reason) => (
                      <button
                        key={reason}
                        type="button"
                        className="button ghost button-sm"
                        aria-pressed={selectedRejectReasons.includes(reason)}
                        onClick={() => onToggleRejectReason?.(reason)}
                      >
                        {reason}
                      </button>
                    ))}
                  </div>
                  <textarea
                    className="input top-gap"
                    value={rejectNote}
                    onChange={(event) => onRejectNoteChange(event.target.value)}
                    placeholder="如需退回，请简要写明要修改的地方，例如：只改封面、字幕术语统一、重做数字人口播。"
                    rows={3}
                  />
                </>
              ) : null}
              <div className="toolbar top-gap">
                {onApprove ? (
                  <button className="button primary" onClick={onApprove} disabled={Boolean(isSubmittingDecision)}>
                    {isSubmittingDecision ? "提交中..." : "通过并继续"}
                  </button>
                ) : null}
                {onReject ? (
                  <button className="button danger" onClick={onReject} disabled={Boolean(isSubmittingDecision)}>
                    退回修改
                  </button>
                ) : null}
              </div>
            </>
          ) : null}
        </div>
      </section>

      <section className="detail-block">
        <div className="detail-key">质量结果</div>
        {hasQuality ? (
          <>
            <div className="stats-grid compact">
              <StatCard label="评分" value={formatQualityScore(qualityScore)} />
              <StatCard label="等级" value={qualityGrade || "—"} />
              <StatCard label="摘要" value={qualitySummary || "—"} compact />
              <StatCard label="问题" value={issueCodes.length ? `${issueCodes.length} 项` : "0"} />
            </div>
            {issueCodes.length ? (
              <div className="tag-row top-gap">
                {issueCodes.map((code) => (
                  <span key={code} className="status-pill failed">
                    {code}
                  </span>
                ))}
              </div>
            ) : null}
          </>
        ) : (
          <div className="muted">暂无质量结果</div>
        )}
      </section>

      <section className="detail-block">
        <div className="detail-key">字幕抽检</div>
        {report ? (
          <>
            <div className="stats-grid compact">
              <StatCard label="字幕总数" value={report.total_subtitle_items} />
              <StatCard label="纠错数" value={report.total_corrections} />
              <StatCard label="待审数" value={report.pending_count} />
            </div>

            <div className="list-stack top-gap">
              {spotCheckItems.length ? (
                spotCheckItems.map((item) => (
                  <article key={item.index} className="list-card column">
                    <div>
                      <div className="row-title">#{item.index} {item.headline}</div>
                      <div className="muted">原文：{item.text_raw}</div>
                    </div>
                    {item.corrections.length ? (
                      <div className="list-stack compact-top">
                        {item.corrections.slice(0, 2).map((correction) => (
                          <div key={correction.id} className="correction-row">
                            <div>
                              <strong>
                                {correction.original} → {correction.suggested}
                              </strong>
                              <div className="muted">
                                {correction.type} · {Math.round(correction.confidence * 100)}%
                                {correction.decision ? ` · 已${correction.decision === "accepted" ? "通过" : "退回"}` : ""}
                              </div>
                            </div>
                            {onApplySubtitleReview ? (
                              <div className="toolbar">
                                <button
                                  className="button ghost button-sm"
                                  onClick={() => onApplySubtitleReview(correction.id, "accepted")}
                                  disabled={isApplyingSubtitleReview}
                                >
                                  通过字幕
                                </button>
                                <button
                                  className="button danger button-sm"
                                  onClick={() => onApplySubtitleReview(correction.id, "rejected")}
                                  disabled={isApplyingSubtitleReview}
                                >
                                  退回字幕
                                </button>
                              </div>
                            ) : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="muted">暂无纠错候选</div>
                    )}
                  </article>
                ))
              ) : (
                <div className="muted">暂无可抽检字幕</div>
              )}
            </div>
          </>
        ) : (
          <div className="muted">暂无字幕报告</div>
        )}
      </section>

      <section className="detail-block">
        <div className="detail-key">辅助信息</div>
        <div className="muted">{workflowDetails}</div>
      </section>
    </aside>
  );
}
