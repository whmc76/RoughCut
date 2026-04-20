import type { ReactNode } from "react";

export type PageHeaderSummaryItem = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
};

type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  summary?: PageHeaderSummaryItem[];
};

export function PageHeader({ eyebrow, title, description, actions, summary }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        {eyebrow ? <div className="page-eyebrow">{eyebrow}</div> : null}
        <h2>{title}</h2>
        {description ? <p className="muted">{description}</p> : null}
        {summary?.length ? (
          <div className="page-header-summary">
            {summary.map((item, index) => (
              <article key={`${item.label}-${index}`} className="page-header-summary-item">
                <span className="page-header-summary-label">{item.label}</span>
                <strong className="page-header-summary-value">{item.value}</strong>
                {item.detail ? <span className="page-header-summary-detail muted">{item.detail}</span> : null}
              </article>
            ))}
          </div>
        ) : null}
      </div>
      {actions ? <div className="toolbar page-header-actions">{actions}</div> : null}
    </header>
  );
}
