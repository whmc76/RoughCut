import type { ContentProfileMemoryStats } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type MemoryCloudPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryCloudPanel({ stats }: MemoryCloudPanelProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader title={t("memory.cloud.title")} description={t("memory.cloud.description")} />
      <div className="chip-wrap">
        {stats.cloud.words?.map((word) => (
          <span key={word.label} className="status-pill running">
            {word.label} ×{word.count}
          </span>
        )) ?? <EmptyState message={t("memory.cloud.empty")} />}
      </div>
    </section>
  );
}
