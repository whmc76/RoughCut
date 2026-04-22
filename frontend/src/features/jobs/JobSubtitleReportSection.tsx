import type { Report } from "../../types";
import { StatCard } from "../../components/ui/StatCard";
import { useI18n } from "../../i18n";

type JobSubtitleReportSectionProps = {
  report?: Report;
  isApplying: boolean;
  onApplyReview: (targetId: string, action: "accepted" | "rejected") => void;
};

export function JobSubtitleReportSection({ report, isApplying, onApplyReview }: JobSubtitleReportSectionProps) {
  const { t } = useI18n();

  return (
    <section className="detail-block">
      <div className="detail-key">{t("jobs.subtitleReport.title")}</div>
      {report ? (
        <>
          <div className="stats-grid compact">
            <StatCard label={t("jobs.subtitleReport.total")} value={report.total_subtitle_items} />
            <StatCard label={t("jobs.subtitleReport.corrections")} value={report.total_corrections} />
            <StatCard label={t("jobs.subtitleReport.pending")} value={report.pending_count} />
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
                    <div className="muted">{t("jobs.subtitleReport.original")}：{item.text_raw}</div>
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
                        <button type="button" className="button ghost" onClick={() => onApplyReview(correction.id, "accepted")} disabled={isApplying}>
                          {t("jobs.subtitleReport.accept")}
                        </button>
                        <button type="button" className="button danger" onClick={() => onApplyReview(correction.id, "rejected")} disabled={isApplying}>
                          {t("jobs.subtitleReport.reject")}
                        </button>
                      </div>
                    </div>
                  ))}
                </article>
              ))}
          </div>
        </>
      ) : (
        <div className="muted">{t("jobs.subtitleReport.empty")}</div>
      )}
    </section>
  );
}
