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
  enqueueError?: string;
  isMerging: boolean;
  mergeError?: string;
  isSuggesting: boolean;
  suggestError?: string;
  onScan: (force: boolean) => void;
  onEnqueue: (enqueueAll: boolean) => void;
  onEnqueueItem: (relativePath: string) => void;
  onMerge: () => void;
  onSmartMergeSuggest: () => void;
  isSmartGroupMerging: boolean;
  smartGroups: WatchInventorySmartMergeGroup[];
  onMergeSmartGroup: (relativePaths: string[]) => void;
  onTogglePending: (relativePath: string, checked: boolean) => void;
};

function processedStatusKey(item: WatchInventoryStatus["inventory"]["deduped"][number]) {
  const reason = item.dedupe_reason || "";
  if (reason.includes("merged")) return "merged";
  if (
    reason === "job:pending" ||
    reason === "job:auto_enqueued" ||
    reason === "job:auto_initialized" ||
    reason === "job_name:pending" ||
    reason === "job_name:running" ||
    reason === "job_name:processing"
  ) {
    return "queued";
  }
  if (reason === "existing_output" || reason === "filename_marked_edited") return "existing";
  if (reason.startsWith("job:") || reason.startsWith("job_name:")) return "existing";
  return "processed";
}

function processedReasonLabel(item: WatchInventoryStatus["inventory"]["deduped"][number], t: (key: string) => string) {
  const key = processedStatusKey(item);
  if (key === "merged") return t("watch.inventory.statusMerged");
  if (key === "queued") return t("watch.inventory.statusQueued");
  if (key === "existing") return t("watch.inventory.statusExisting");
  return t("watch.inventory.statusProcessed");
}

export function WatchRootInventoryPanel({
  root,
  inventory,
  selectedPending,
  isScanning,
  scanError,
  isEnqueueing,
  enqueueError,
  isMerging,
  mergeError,
  isSuggesting,
  suggestError,
  onScan,
  onEnqueue,
  onEnqueueItem,
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
  const processedItems = inventory?.inventory.deduped ?? [];
  const queuedCount = processedItems.filter((item) => processedStatusKey(item) === "queued").length;
  const mergedCount = processedItems.filter((item) => processedStatusKey(item) === "merged").length;
  const existingCount = processedItems.filter((item) => processedStatusKey(item) === "existing").length;
  const actionError = scanError || enqueueError || mergeError || suggestError;
  const actionBusy = isScanning || isEnqueueing || isMerging || isSmartGroupMerging;
  const activeAction = isScanning
    ? t("watch.inventory.statusScanning")
    : isEnqueueing
      ? t("watch.inventory.statusEnqueueing")
      : isMerging || isSmartGroupMerging
        ? t("watch.inventory.statusMerging")
        : isSuggesting
          ? t("watch.inventory.statusSuggesting")
          : null;

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
              {isScanning ? t("watch.inventory.scanning") : t("watch.inventory.forceScan")}
            </button>
            <button className="button primary" type="button" onClick={() => onEnqueue(true)} disabled={!pendingItems.length || actionBusy}>
              {isEnqueueing ? t("watch.inventory.enqueueing") : t("watch.inventory.enqueueAll")}
            </button>
            <button className="button ghost" type="button" onClick={onSmartMergeSuggest} disabled={!pendingItems.length || actionBusy || isSuggesting}>
              {isSuggesting ? t("watch.inventory.suggesting") : t("watch.inventory.smartMerge")}
            </button>
          </div>
        }
      />

      {inventory && (
        <div className={`inventory-status-bar${activeAction ? " working" : ""}`} role="status" aria-live="polite">
          <span className="inventory-status-dot" aria-hidden="true" />
          <strong>{activeAction || t("watch.inventory.statusReady")}</strong>
          <span>{t("watch.inventory.pendingStatus").replace("{count}", String(inventory.pending_count))}</span>
          <span>{t("watch.inventory.queuedStatus").replace("{count}", String(queuedCount))}</span>
          <span>{t("watch.inventory.mergedStatus").replace("{count}", String(mergedCount))}</span>
          <span>{t("watch.inventory.existingStatus").replace("{count}", String(existingCount))}</span>
        </div>
      )}

      {actionError ? <div className="notice notice-error top-gap">{actionError}</div> : null}
      {!actionError && inventory?.error ? <div className="notice notice-error top-gap">{inventory.error}</div> : null}

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
                      <button className="button ghost" type="button" onClick={() => onMergeSmartGroup(group.relative_paths)} disabled={actionBusy}>
                      {isSmartGroupMerging ? t("watch.inventory.merging") : t("watch.inventory.mergeSuggested")}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!!smartGroups.length && (
            <div className="toolbar top-gap">
              <button className="button ghost" type="button" onClick={onSmartMergeSuggest} disabled={actionBusy || isSuggesting}>
                {isSuggesting ? t("watch.inventory.suggesting") : t("watch.inventory.refreshSmartSuggestions")}
              </button>
              <button className="button primary" type="button" onClick={() => onMergeSmartGroup(smartGroups[0].relative_paths)} disabled={actionBusy}>
                {isSmartGroupMerging ? t("watch.inventory.merging") : t("watch.inventory.mergeTopSuggestion")}
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
                    <th>{t("watch.inventory.action")}</th>
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
                        <td>
                          <button
                            className="button ghost button-sm"
                            type="button"
                            onClick={() => onEnqueueItem(item.relative_path)}
                            disabled={actionBusy}
                          >
                            {isEnqueueing ? t("watch.inventory.enqueueingShort") : t("watch.inventory.enqueueOne")}
                          </button>
                        </td>
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
              <button className="button primary" type="button" onClick={() => onEnqueue(false)} disabled={actionBusy}>
                {isEnqueueing ? t("watch.inventory.enqueueing") : t("watch.inventory.enqueueSelected")}
              </button>
              <button className="button primary" type="button" onClick={onMerge} disabled={selectedPending.length < 2 || actionBusy}>
                {isMerging ? t("watch.inventory.merging") : t("watch.inventory.mergeSelected")}
              </button>
              <span className="muted">{t("watch.inventory.selectedCount").replace("{count}", String(selectedPending.length))}</span>
            </div>
          )}

          {processedItems.length ? (
            <div className="inventory-processed-section top-gap">
              <div className="inventory-section-head">
                <strong>{t("watch.inventory.processedTitle")}</strong>
                <span className="muted">{t("watch.inventory.processedCount").replace("{count}", String(processedItems.length))}</span>
              </div>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>{t("watch.inventory.file")}</th>
                      <th>{t("watch.inventory.statusColumn")}</th>
                      <th>{t("watch.inventory.info")}</th>
                      <th>{t("watch.inventory.modifiedAt")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {processedItems.map((item) => {
                      const statusKey = processedStatusKey(item);
                      return (
                        <tr key={`${item.relative_path}-${item.dedupe_reason || "processed"}`}>
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
                            <div className="inventory-status-cell">
                              <span className={`status-chip inventory-status-chip ${statusKey}`}>
                                {processedReasonLabel(item, t)}
                              </span>
                              {item.matched_job_id ? (
                                <span className="muted">{t("watch.inventory.jobId").replace("{id}", item.matched_job_id.slice(0, 8))}</span>
                              ) : null}
                              {item.matched_output_path ? <span className="muted">{item.matched_output_path}</span> : null}
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
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
