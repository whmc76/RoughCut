import type { ContentProfileMemoryStats } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";
import { memoryFieldLabel } from "./constants";

type MemoryRecentCorrectionsPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryRecentCorrectionsPanel({ stats }: MemoryRecentCorrectionsPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel top-gap">
      <PanelHeader title={t("memory.recent.title")} description={t("memory.recent.description")} />
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("memory.recent.field")}</th>
              <th>{t("memory.recent.original")}</th>
              <th>{t("memory.recent.corrected")}</th>
              <th>{t("memory.recent.source")}</th>
            </tr>
          </thead>
          <tbody>
            {stats.recent_corrections.map((item, index) => (
              <tr key={`${item.field_name}-${index}`}>
                <td>{memoryFieldLabel(String(item.field_name))}</td>
                <td>{String(item.original_value || t("memory.recent.emptyValue"))}</td>
                <td>{String(item.corrected_value || "—")}</td>
                <td>{String(item.source_name || "—")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
