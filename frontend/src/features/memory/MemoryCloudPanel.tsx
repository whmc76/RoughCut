import type { ContentProfileMemoryStats } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";

type MemoryCloudPanelProps = {
  stats: ContentProfileMemoryStats;
};

export function MemoryCloudPanel({ stats }: MemoryCloudPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title="记忆词云" description="按人工反馈累计出来的关键词。" />
      <div className="chip-wrap">
        {stats.cloud.words?.map((word) => (
          <span key={word.label} className="status-pill running">
            {word.label} ×{word.count}
          </span>
        )) ?? <EmptyState message="暂无词云" />}
      </div>
    </section>
  );
}
