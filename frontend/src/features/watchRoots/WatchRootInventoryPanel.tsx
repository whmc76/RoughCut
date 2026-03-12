import { api } from "../../api";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { StatCard } from "../../components/ui/StatCard";
import type { WatchInventoryStatus, WatchRoot } from "../../types";
import { formatBytes, formatDate, formatDuration, statusLabel } from "../../utils";

type WatchRootInventoryPanelProps = {
  root: WatchRoot;
  inventory?: WatchInventoryStatus;
  selectedPending: string[];
  isScanning: boolean;
  isEnqueueing: boolean;
  onScan: (force: boolean) => void;
  onEnqueue: (enqueueAll: boolean) => void;
  onTogglePending: (relativePath: string, checked: boolean) => void;
};

export function WatchRootInventoryPanel({
  root,
  inventory,
  selectedPending,
  isScanning,
  isEnqueueing,
  onScan,
  onEnqueue,
  onTogglePending,
}: WatchRootInventoryPanelProps) {
  return (
    <section className="panel inventory-panel">
      <PanelHeader
        title="待剪辑清单"
        description={inventory ? `${inventory.pending_count} 待剪辑 / ${inventory.deduped_count} 已去重` : "尚未扫描"}
        actions={
          <div className="toolbar">
            <button className="button ghost" onClick={() => onScan(false)} disabled={isScanning}>
              {isScanning ? "扫描中..." : "开始扫描"}
            </button>
            <button className="button ghost" onClick={() => onScan(true)} disabled={isScanning}>
              强制重扫
            </button>
            <button className="button primary" onClick={() => onEnqueue(true)} disabled={!inventory?.inventory.pending.length || isEnqueueing}>
              全部入队
            </button>
          </div>
        }
      />

      {inventory && (
        <>
          <div className="stats-grid compact">
            <StatCard label="扫描状态" value={statusLabel(inventory.status)} />
            <StatCard label="进度" value={`${inventory.processed_files} / ${inventory.total_files}`} />
            <StatCard label="当前文件" value={inventory.current_file || "—"} compact />
          </div>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th></th>
                  <th>文件</th>
                  <th>信息</th>
                  <th>修改时间</th>
                </tr>
              </thead>
              <tbody>
                {inventory.inventory.pending.map((item) => {
                  const checked = selectedPending.includes(item.relative_path);
                  return (
                    <tr key={item.relative_path}>
                      <td>
                        <input type="checkbox" checked={checked} onChange={(event) => onTogglePending(item.relative_path, event.target.checked)} />
                      </td>
                      <td>
                        <div className="inventory-row">
                          <img src={api.inventoryThumbnailUrl(root.id, item.relative_path)} alt={item.source_name} className="inventory-thumb" />
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

          {!!selectedPending.length && (
            <div className="toolbar top-gap">
              <button className="button primary" onClick={() => onEnqueue(false)} disabled={isEnqueueing}>
                将选中项加入剪辑任务
              </button>
              <span className="muted">已选 {selectedPending.length} 项</span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
