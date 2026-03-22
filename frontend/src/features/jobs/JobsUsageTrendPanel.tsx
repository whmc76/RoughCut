import type { ReactNode } from "react";

import type { JobsUsageTrend } from "../../types";

type JobsUsageTrendPanelProps = {
  title: string;
  description: string;
  trend?: JobsUsageTrend;
  actions?: ReactNode;
};

export function JobsUsageTrendPanel({ title, description, trend, actions }: JobsUsageTrendPanelProps) {
  const points = trend?.points ?? [];
  const maxTokens = Math.max(...points.map((point) => point.total_tokens), 1);

  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <div className="row-title">{title}</div>
          <div className="muted">{description}</div>
        </div>
        {actions ? <div className="toolbar">{actions}</div> : null}
      </div>

      <div className="usage-trend-grid">
        {points.map((point) => {
          const height = Math.max(10, Math.round((point.total_tokens / maxTokens) * 100));
          const topLabel = point.top_entry?.label ?? point.top_step?.label ?? "—";
          return (
            <article key={point.date} className="usage-trend-card">
              <div className="usage-trend-bar-wrap">
                <div className="usage-trend-bar" style={{ height: `${height}%` }} />
              </div>
              <strong>{point.label}</strong>
              <div className="muted">{point.total_tokens.toLocaleString()}</div>
              <div className="muted">{Math.round((point.cache.hit_rate || 0) * 100)}%</div>
              <div className="muted">{topLabel}</div>
            </article>
          );
        })}
      </div>
    </section>
  );
}
