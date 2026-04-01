import type { ReactNode } from "react";

type PageSectionProps = {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
  children: ReactNode;
};

export function PageSection({ eyebrow, title, description, actions, className, children }: PageSectionProps) {
  return (
    <section className={className ? `page-section ${className}` : "page-section"}>
      <div className="page-section-header">
        <div className="page-section-copy">
          {eyebrow ? <div className="page-eyebrow">{eyebrow}</div> : null}
          <h3 className="page-section-title">{title}</h3>
          {description ? <p className="page-section-description">{description}</p> : null}
        </div>
        {actions ? <div className="toolbar page-section-actions">{actions}</div> : null}
      </div>
      <div className="page-section-body">{children}</div>
    </section>
  );
}
