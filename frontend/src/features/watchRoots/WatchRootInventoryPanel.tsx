import { api } from "../../api";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { StatCard } from "../../components/ui/StatCard";
import { useI18n } from "../../i18n";
import type { WatchInventorySmartMergeGroup, WatchInventoryStatus, WatchRoot } from "../../types";
import { formatBytes, formatDate, formatDuration, statusLabel } from "../../utils";

type WatchRootInventoryPanelProps = {
  root: WatchRoot;
  inventory?: WatchInventoryStatus;
  selectedPending: string[];
  isScanning: boolean;
  scanError?: string;
  isEnqueueing: boolean;
  isMerging: boolean;
  isSuggesting: boolean;
  onScan: (force: boolean) => void;
  onEnqueue: (enqueueAll: boolean) => void;
  onMerge: () => void;
  onSmartMergeSuggest: () => void;
  isSmartGroupMerging: boolean;
  smartGroups: WatchInventorySmartMergeGroup[];
  onMergeSmartGroup: (relativePaths: string[]) => void;
  onTogglePending: (relativePath: string, checked: boolean) => void;
};

export function WatchRootInventoryPanel({
  root,
  inventory,
  selectedPending,
  isScanning,
  scanError,
  isEnqueueing,
  isMerging,
  isSuggesting,
  onScan,
  onEnqueue,
  onMerge,
  onSmartMergeSuggest,
  isSmartGroupMerging,
  smartGroups,
  onMergeSmartGroup,
  onTogglePending,
}: WatchRootInventoryPanelProps) {
  const { t } = useI18n();
  const description = inventory
    ? t("watch.inventory.descriptionReady")
        .replace("{pending}", String(inventory.pending_count))
        .replace("{deduped}", String(inventory.deduped_count))
    : t("watch.inventory.description");
  const pendingItems = inventory?.inventory.pending ?? [];

  return (
    <section className="panel inventory-panel">
      <PanelHeader
        title={t("watch.inventory.title")}
        description={description}
        actions={
          <div className="toolbar">
            <button className="button ghost" type="button" onClick={() => onScan(false)} disabled={isScanning}>
              {isScanning ? t("watch.inventory.scanning") : t("watch.inventory.scan")}
            </button>
            <button className="button ghost" type="button" onClick={() => onScan(true)} disabled={isScanning}>
              {t("watch.inventory.forceScan")}
            </button>
            <button className="button primary" type="button" onClick={() => onEnqueue(true)} disabled={!pendingItems.length || isEnqueueing || isMerging}>
              {t("watch.inventory.enqueueAll")}
            </button>
            <button className="button ghost" type="button" onClick={onSmartMergeSuggest} disabled={!pendingItems.length || isScanning || isSuggesting}>
              {t("watch.inventory.smartMerge")}
            </button>
          </div>
        }
      />

      {scanError ? <div className="notice top-gap">{scanError}</div> : null}
      {!scanError && inventory?.error ? <div className="notice top-gap">{inventory.error}</div> : null}

      {inventory && (
        <>
          <div className="stats-grid compact">
            <StatCard label={t("watch.inventory.scanStatus")} value={statusLabel(inventory.status)} />
            <StatCard label={t("watch.inventory.progress")} value={`${inventory.processed_files} / ${inventory.total_files}`} />
            <StatCard label={t("watch.inventory.currentFile")} value={inventory.current_file || "—"} compact />
          </div>

          {smartGroups.length > 0 && (
            <div className="top-gap">
              <div style={{ marginBottom: 8 }}>
                <strong>{t("watch.inventory.smartSuggestions")}</strong>{" "}
                <span className="muted">({smartGroups.length})</span>
              </div>
              {smartGroups.map((group, index) => (
                <div className="panel" key={`${group.relative_paths.join("|")}-${index}`} style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
                    <div>
                      <div>{group.relative_paths.join(" + ")}</div>
                      <div className="muted">
                        {t("watch.inventory.smartScore").replace("{score}", `${(group.score * 100).toFixed(0)}%`)}
                      </div>
                      <div className="chip-wrap compact" style={{ marginTop: 8 }}>
                        {group.reasons.map((reason) => (
                          <span key={reason} className="muted">{reason}</span>
                        ))}
                      </div>
                    </div>
                      <button className="button ghost" type="button" onClick={() => onMergeSmartGroup(group.relative_paths)} disabled={isSmartGroupMerging || isMerging}>
                      {t("watch.inventory.mergeSuggested")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!!smartGroups.length && (
            <div className="toolbar top-gap">
              <button className="button ghost" type="button" onClick={onSmartMergeSuggest} disabled={isSuggesting || isSmartGroupMerging}>
                {t("watch.inventory.refreshSmartSuggestions")}
              </button>
              <button className="button primary" type="button" onClick={() => onMergeSmartGroup(smartGroups[0].relative_paths)} disabled={isSmartGroupMerging || isMerging}>
                {t("watch.inventory.mergeTopSuggestion")}
              </button>
            </div>
          )}

          {pendingItems.length ? (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th></th>
                    <th>{t("watch.inventory.file")}</th>
                    <th>{t("watch.inventory.info")}</th>
                    <th>{t("watch.inventory.modifiedAt")}</th>
                  </tr>
                </thead>
                <tbody>
                  {pendingItems.map((item) => {
                    const checked = selectedPending.includes(item.relative_path);
                    return (
                      <tr key={item.relative_path}>
                        <td>
                          <input type="checkbox" checked={checked} onChange={(event) => onTogglePending(item.relative_path, event.target.checked)} />
                        </td>
                        <td>
                          <div className="inventory-row">
                            <img
                              src={api.inventoryThumbnailUrl(root.id, item.relative_path)}
                              alt={item.source_name}
                              className="inventory-thumb"
                              loading="lazy"
                              decoding="async"
                            />
                            <div>
                              <div className="row-title">{item.source_name}</div>
                              <div className="muted">{item.relative_path}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          {formatDuration(item.duration_sec)} / {formatBytes(item.size_bytes)}
                        </td>
                        <td>{formatDate(item.modified_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState message="当前没有待处理素材。可以重新扫描目录，或先在左侧调整监听规则。" />
          )}

          {!!selectedPending.length && (
            <div className="toolbar top-gap">
              <button className="button primary" type="button" onClick={() => onEnqueue(false)} disabled={isEnqueueing}>
                {t("watch.inventory.enqueueSelected")}
              </button>
              <button className="button primary" type="button" onClick={onMerge} disabled={selectedPending.length < 2 || isMerging}>
                {t("watch.inventory.mergeSelected")}
              </button>
              <span className="muted">{t("watch.inventory.selectedCount").replace("{count}", String(selectedPending.length))}</span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
