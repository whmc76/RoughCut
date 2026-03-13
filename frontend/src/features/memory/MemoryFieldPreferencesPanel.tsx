import type { ContentProfileMemoryStats } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { memoryFieldLabel } from "./constants";

type MemoryFieldPreferencesPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryFieldPreferencesPanel({ stats }: MemoryFieldPreferencesPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader title={t("memory.preferences.title")} description={t("memory.preferences.description")} />
      <div className="list-stack">
        {Object.entries(stats.field_preferences).map(([field, values]) => (
          <article key={field} className="list-card">
            <div>
              <div className="row-title">{memoryFieldLabel(field)}</div>
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
