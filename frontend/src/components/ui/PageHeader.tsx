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
      </div>
      {actions ? <div className="toolbar page-header-actions">{actions}</div> : null}
    </header>
  );
}
