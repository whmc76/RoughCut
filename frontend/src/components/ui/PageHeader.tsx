import type { ReactNode } from "react";

export type PageHeaderSummaryItem = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
};

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
  summary?: PageHeaderSummaryItem[];
};

export function PageHeader({ eyebrow, title, description, actions, summary }: PageHeaderProps) {
  return (
    <>
      <header className="page-header">
        <div className="page-header-copy">
          <div className="page-eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
          <p className="muted">{description}</p>
        </div>
        {actions ? <div className="toolbar page-header-actions">{actions}</div> : null}
      </header>
      {summary?.length ? (
        <div className="page-summary-grid">
          {summary.map((item) => (
            <article key={item.label} className="page-summary-card">
              <span className="page-summary-label">{item.label}</span>
              <strong className="page-summary-value">{item.value}</strong>
              {item.detail ? <span className="page-summary-detail">{item.detail}</span> : null}
            </article>
          ))}
        </div>
      ) : null}
    </>
  );
}
