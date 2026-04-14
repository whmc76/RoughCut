import type { WatchRoot } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type WatchRootListProps = {
  roots: WatchRoot[];
  selectedRootId: string | null;
  onSelect: (rootId: string) => void;
  onCreateNew: () => void;
};

export function WatchRootList({ roots, selectedRootId, onSelect, onCreateNew }: WatchRootListProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader
        title={t("watch.list.title")}
        description={`${roots.length} ${t("watch.list.count")}`}
        actions={<button className="button ghost" onClick={onCreateNew}>{t("watch.list.new")}</button>}
      />

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
              <div className="muted">{root.workflow_template || t("watch.list.unsetProfile")}</div>
            </div>
            <div className="row-meta">
              <span className={`status-chip ${root.enabled ? "done" : "cancelled"}`}>{root.enabled ? t("watch.list.enabled") : t("watch.list.disabled")}</span>
              <span>{root.ingest_mode === "task_only" ? t("watch.list.modeTaskOnly") : t("watch.list.modeFullAuto")}</span>
              <span>{root.scan_mode}</span>
            </div>
          </ListCard>
        ))}
        {!roots.length && <EmptyState message={t("watch.list.empty")} />}
      </div>
    </section>
  );
}
