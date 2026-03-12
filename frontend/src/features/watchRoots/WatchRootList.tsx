import type { WatchRoot } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";

type WatchRootListProps = {
  roots: WatchRoot[];
  selectedRootId: string | null;
  onSelect: (rootId: string) => void;
  onCreateNew: () => void;
};

export function WatchRootList({ roots, selectedRootId, onSelect, onCreateNew }: WatchRootListProps) {
  return (
    <section className="panel">
      <PanelHeader title="目录列表" description={`${roots.length} 个监控目录`} actions={<button className="button ghost" onClick={onCreateNew}>新建</button>} />

      <div className="list-stack">
        {roots.map((root) => (
          <ListCard
            key={root.id}
            as="button"
            selectable
            selected={selectedRootId === root.id}
            onClick={() => onSelect(root.id)}
          >
            <div>
              <div className="row-title">{root.path}</div>
              <div className="muted">{root.channel_profile || "未设置频道配置"}</div>
            </div>
            <div className="row-meta">
              <span className={`status-chip ${root.enabled ? "done" : "cancelled"}`}>{root.enabled ? "启用" : "停用"}</span>
              <span>{root.scan_mode}</span>
            </div>
          </ListCard>
        ))}
        {!roots.length && <EmptyState message="暂无监控目录" />}
      </div>
    </section>
  );
}
