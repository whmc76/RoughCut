import type { ReactNode } from "react";

type PanelHeaderProps = {
  title: string;
  description?: string;
  actions?: ReactNode;
};

export function PanelHeader({ title, description, actions }: PanelHeaderProps) {
  return (
    <div className="panel-header">
      <div>
        <h3>{title}</h3>
        {description ? <p className="muted">{description}</p> : null}
      </div>
      {actions}
    </div>
  );
}
