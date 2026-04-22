import type { WatchRoot } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { ListActions } from "../../components/ui/ListActions";
import { ListCard } from "../../components/ui/ListCard";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type WatchRootListProps = {
  roots: WatchRoot[];
  selectedRootId: string | null;
  actionRootId?: string | null;
  onSelect: (rootId: string) => void;
  onCreateNew: () => void;
  onToggleEnabled: (root: WatchRoot) => void;
  onDelete: (root: WatchRoot) => void;
};

export function WatchRootList({
  roots,
  selectedRootId,
  actionRootId,
  onSelect,
  onCreateNew,
  onToggleEnabled,
  onDelete,
}: WatchRootListProps) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <PanelHeader
        title={t("watch.list.title")}
        description={`${roots.length} ${t("watch.list.count")}`}
        actions={<button className="button ghost" type="button" onClick={onCreateNew}>{t("watch.list.new")}</button>}
      />

      <div className="list-stack">
        {roots.map((root) => {
          const recursive = root.recursive ?? true;
          return (
            <ListCard
              key={root.id}
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
                <span className={`status-chip ${recursive ? "done" : "cancelled"}`}>{recursive ? t("watch.list.recursive") : t("watch.list.currentDirOnly")}</span>
                <ListActions className="watch-root-row-actions">
                  <button
                    className="button ghost button-sm"
                    type="button"
                    disabled={actionRootId === root.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      onToggleEnabled(root);
                    }}
                  >
                    {root.enabled ? t("watch.list.disabled") : t("watch.list.enabled")}
                  </button>
                  <button
                    className="button danger button-sm"
                    type="button"
                    disabled={actionRootId === root.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      onDelete(root);
                    }}
                  >
                    {t("watch.form.delete")}
                  </button>
                </ListActions>
              </div>
            </ListCard>
          );
        })}
        {!roots.length && <EmptyState message={t("watch.list.empty")} />}
      </div>
    </section>
  );
}
