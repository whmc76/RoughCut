import type { ContentProfileMemoryStats } from "../../types";
import { StatCard } from "../../components/ui/StatCard";
import { useI18n } from "../../i18n";

type MemoryOverviewStatsProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryOverviewStats({ stats }: MemoryOverviewStatsProps) {
  const { t } = useI18n();

  return (
    <div className="stats-grid">
      <StatCard label={t("memory.stats.totalCorrections")} value={stats.total_corrections} />
      <StatCard label={t("memory.stats.totalKeywords")} value={stats.total_keywords} />
      <StatCard label={t("memory.stats.totalLearnedHotwords")} value={stats.total_learned_hotwords} />
      <StatCard label={t("memory.stats.wordCount")} value={stats.cloud.words?.length ?? 0} />
      <StatCard label={t("memory.stats.scope")} value={stats.scope} />
    </div>
  );
}
