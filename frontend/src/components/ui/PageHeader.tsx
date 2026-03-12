import type { ReactNode } from "react";

type PageHeaderProps = {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
};

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div>
        <div className="page-eyebrow">{eyebrow}</div>
        <h2>{title}</h2>
        <p className="muted">{description}</p>
      </div>
      {actions ? <div className="toolbar">{actions}</div> : null}
    </header>
  );
}
