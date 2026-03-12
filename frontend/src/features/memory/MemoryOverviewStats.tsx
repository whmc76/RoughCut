import type { ContentProfileMemoryStats } from "../../types";
import { StatCard } from "../../components/ui/StatCard";

type MemoryOverviewStatsProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryOverviewStats({ stats }: MemoryOverviewStatsProps) {
  return (
    <div className="stats-grid">
      <StatCard label="累计纠正" value={stats.total_corrections} />
      <StatCard label="累计关键词" value={stats.total_keywords} />
      <StatCard label="记忆词数量" value={stats.cloud.words?.length ?? 0} />
      <StatCard label="作用域" value={stats.scope} />
    </div>
  );
}
