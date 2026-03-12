import { PageHeader } from "../components/ui/PageHeader";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { WatchRootList } from "../features/watchRoots/WatchRootList";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";

export function WatchRootsPage() {
  const workspace = useWatchRootWorkspace();
  const channelProfileOptions = workspace.options.data?.channel_profiles ?? [{ value: "", label: "自动匹配" }];

  return (
    <section>
      <PageHeader eyebrow="Watcher" title="监控目录" description="页面层只保留状态协调，目录列表、编辑表单和库存清单已经拆成独立区块。" actions={<button className="button ghost" onClick={workspace.refreshRoots}>刷新</button>} />

      <div className="panel-grid watch-grid">
        <WatchRootList roots={workspace.roots.data ?? []} selectedRootId={workspace.selectedRootId} onSelect={workspace.setSelectedRootId} onCreateNew={() => workspace.setSelectedRootId(null)} />
        <WatchRootFormPanel
          form={workspace.form}
          channelProfileOptions={channelProfileOptions}
          isEditing={Boolean(workspace.selectedRootId)}
          isSaving={workspace.createRoot.isPending || workspace.updateRoot.isPending}
          isDeleting={workspace.deleteRoot.isPending}
          onChange={workspace.setForm}
          onSubmit={() => {
            if (workspace.selectedRootId) workspace.updateRoot.mutate();
            else workspace.createRoot.mutate();
          }}
          onDelete={() => workspace.deleteRoot.mutate()}
        />
      </div>

      {workspace.selectedRoot && (
        <WatchRootInventoryPanel
          root={workspace.selectedRoot}
          inventory={workspace.inventory.data}
          selectedPending={workspace.selectedPending}
          isScanning={workspace.scan.isPending}
          isEnqueueing={workspace.enqueue.isPending}
          onScan={(force) => workspace.scan.mutate(force)}
          onEnqueue={(enqueueAll) => workspace.enqueue.mutate(enqueueAll)}
          onTogglePending={(relativePath, checked) =>
            workspace.setSelectedPending((prev) => (checked ? [...prev, relativePath] : prev.filter((entry) => entry !== relativePath)))
          }
        />
      )}
    </section>
  );
}
