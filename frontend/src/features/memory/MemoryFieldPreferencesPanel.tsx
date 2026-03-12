import type { ContentProfileMemoryStats } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { memoryFieldLabels } from "./constants";

type MemoryFieldPreferencesPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryFieldPreferencesPanel({ stats }: MemoryFieldPreferencesPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title="字段偏好" description="系统已记住的品牌/型号/主题偏好。" />
      <div className="list-stack">
        {Object.entries(stats.field_preferences).map(([field, values]) => (
          <article key={field} className="list-card">
            <div>
              <div className="row-title">{memoryFieldLabels[field] || field}</div>
              <div className="chip-wrap compact">
                {values.map((item) => (
                  <span key={`${field}-${item.value}`} className="status-pill done">
                    {String(item.value)} ×{Number(item.count)}
                  </span>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
