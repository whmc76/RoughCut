import type { Job, JobActivity } from "../../types";
import { StatCard } from "../../components/ui/StatCard";
import { formatDate, statusLabel } from "../../utils";
import { stepLabel } from "./constants";

type SubtitleDecision = JobActivity["decisions"][number];

type JobSubtitleDiagnosticsSectionProps = {
  activity?: Pick<JobActivity, "decisions">;
  job?: Pick<Job, "quality_score" | "quality_grade" | "quality_summary" | "quality_issue_codes">;
  showQualitySnapshot?: boolean;
  isTriggeringRerun?: boolean;
  pendingRerunStartStep?: string | null;
  pendingRerunIssueCode?: string | null;
  onTriggerRerun?: (decision: SubtitleDecision) => void;
};

const SUBTITLE_DIAGNOSTIC_STEPS = new Set([
  "subtitle_postprocess",
  "subtitle_term_resolution",
  "subtitle_consistency_review",
  "subtitle_quality",
]);

function isSubtitleDecision(decision: SubtitleDecision) {
  return SUBTITLE_DIAGNOSTIC_STEPS.has(decision.step_name ?? "")
    || SUBTITLE_DIAGNOSTIC_STEPS.has(decision.kind);
}

function formatQualityScore(score: number | null | undefined) {
  return typeof score === "number" && Number.isFinite(score) ? score.toFixed(1) : "—";
}

export function JobSubtitleDiagnosticsSection({
  activity,
  job,
  showQualitySnapshot = true,
  isTriggeringRerun = false,
  pendingRerunStartStep = null,
  pendingRerunIssueCode = null,
  onTriggerRerun,
}: JobSubtitleDiagnosticsSectionProps) {
  const decisions = (activity?.decisions ?? []).filter(isSubtitleDecision);
  const qualityIssueCodes = (job?.quality_issue_codes ?? []).filter(Boolean);
  const hasQualitySnapshot = Boolean(
    showQualitySnapshot
      && (
        job?.quality_score != null
        || job?.quality_grade?.trim()
        || job?.quality_summary?.trim()
        || qualityIssueCodes.length
      ),
  );

  if (!decisions.length && !hasQualitySnapshot) {
    return null;
  }

  return (
    <section className="detail-block">
      <div className="detail-key">字幕决策与阻断</div>
      {hasQualitySnapshot ? (
        <>
          <div className="stats-grid compact">
            <StatCard label="评分" value={formatQualityScore(job?.quality_score)} />
            <StatCard label="等级" value={job?.quality_grade?.trim() || "—"} />
            <StatCard label="问题" value={qualityIssueCodes.length ? `${qualityIssueCodes.length} 项` : "0"} />
            <StatCard label="摘要" value={job?.quality_summary?.trim() || "—"} compact />
          </div>
          {qualityIssueCodes.length ? (
            <div className="tag-row top-gap">
              {qualityIssueCodes.map((code) => (
                <span key={code} className="status-pill failed">
                  {code}
                </span>
              ))}
            </div>
          ) : null}
        </>
      ) : null}

      {decisions.length ? (
        <div className="list-stack top-gap">
          {decisions.map((decision) => {
            const reason = decision.detail?.trim() || decision.summary?.trim() || "暂无说明";
            const recommendedAction = decision.recommended_action?.trim();
            const rerunSteps = (decision.rerun_steps ?? []).filter(Boolean);
            const canTriggerRerun = Boolean(onTriggerRerun && decision.rerun_start_step);
            const isPendingRerun = Boolean(
              decision.rerun_start_step
              && pendingRerunStartStep
              && decision.rerun_start_step === pendingRerunStartStep
              && (!pendingRerunIssueCode || (decision.issue_codes ?? []).includes(pendingRerunIssueCode)),
            );
            const displayStepKey = decision.kind === "subtitle_quality"
              ? "subtitle_quality"
              : (decision.step_name ?? decision.kind);
            return (
              <article
                key={`${decision.kind}-${decision.step_name ?? "na"}-${decision.updated_at ?? decision.title}`}
                className="activity-card final-review-evidence-card"
              >
                <div className="toolbar">
                  <strong>{stepLabel(displayStepKey)}</strong>
                  <span className={`status-pill ${decision.status}`}>{statusLabel(decision.status)}</span>
                </div>
                <div className="final-review-evidence-copy">
                  <strong>{decision.title}</strong>
                  <div className="muted">{reason}</div>
                  {decision.detail ? <div className="final-review-warning">阻断原因：{decision.detail}</div> : null}
                  {recommendedAction ? <div className="muted">处理动作：{recommendedAction}</div> : null}
                  {decision.rerun_start_step ? (
                    <div className="muted">
                      自动回退：{decision.rerun_start_step}
                      {rerunSteps.length ? ` -> ${rerunSteps.slice(1).join(" -> ")}` : ""}
                    </div>
                  ) : null}
                  {isPendingRerun ? (
                    <div className="final-review-warning">
                      已请求重跑，等待调度器从 {decision.rerun_start_step} 继续。
                    </div>
                  ) : null}
                  {canTriggerRerun ? (
                    <div className="toolbar compact-top">
                      <button
                        type="button"
                        className="button ghost button-sm"
                        disabled={isTriggeringRerun || isPendingRerun}
                        onClick={() => onTriggerRerun?.(decision)}
                      >
                        {isPendingRerun ? "已请求重跑" : isTriggeringRerun ? "重跑中..." : "按建议重跑"}
                      </button>
                    </div>
                  ) : null}
                  {decision.updated_at ? <div className="muted">{formatDate(decision.updated_at)}</div> : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}

    </section>
  );
}
