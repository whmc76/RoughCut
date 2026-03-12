import type { Report } from "../../types";
import { StatCard } from "../../components/ui/StatCard";

type JobSubtitleReportSectionProps = {
  report?: Report;
  isApplying: boolean;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
};

export function JobSubtitleReportSection({ report, isApplying, onApplyReview }: JobSubtitleReportSectionProps) {
  return (
    <section className="detail-block">
      <div className="detail-key">字幕报告</div>
      {report ? (
        <>
          <div className="stats-grid compact">
            <StatCard label="总字幕" value={report.total_subtitle_items} />
            <StatCard label="纠错候选" value={report.total_corrections} />
            <StatCard label="待审" value={report.pending_count} />
          </div>
          <div className="list-stack">
            {report.items
              .filter((item) => item.corrections.length)
              .slice(0, 8)
              .map((item) => (
                <article key={item.index} className="list-card column">
                  <div>
                    <div className="row-title">
                      #{item.index} {item.text_final || item.text_norm || item.text_raw}
                    </div>
                    <div className="muted">原文：{item.text_raw}</div>
                  </div>
                  {item.corrections.map((correction) => (
                    <div key={correction.id} className="correction-row">
                      <div>
                        <strong>
                          {correction.original} → {correction.suggested}
                        </strong>
                        <div className="muted">
                          {correction.type} · {Math.round(correction.confidence * 100)}%
                        </div>
                      </div>
                      <div className="toolbar">
                        <button className="button ghost" onClick={() => onApplyReview(correction.id, "accepted")} disabled={isApplying}>
                          接受
                        </button>
                        <button className="button danger" onClick={() => onApplyReview(correction.id, "rejected")} disabled={isApplying}>
                          拒绝
                        </button>
                      </div>
                    </div>
                  ))}
                </article>
              ))}
          </div>
        </>
      ) : (
        <div className="muted">暂无字幕报告</div>
      )}
    </section>
  );
}
