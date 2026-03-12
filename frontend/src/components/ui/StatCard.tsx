import type { ReactNode } from "react";

type StatCardProps = {
  label: string;
  value: ReactNode;
  compact?: boolean;
};

export function StatCard({ label, value, compact = false }: StatCardProps) {
  return (
    <article className="stat-card">
      <span className="stat-label">{label}</span>
      <strong className={compact ? "compact-text" : undefined}>{value}</strong>
    </article>
  );
}
