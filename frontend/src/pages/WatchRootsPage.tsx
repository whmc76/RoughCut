import { PageHeader } from "../components/ui/PageHeader";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { WatchRootList } from "../features/watchRoots/WatchRootList";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";
import { useI18n } from "../i18n";

export function WatchRootsPage() {
  const { t } = useI18n();
  const workspace = useWatchRootWorkspace();
  const channelProfileOptions = workspace.options.data?.channel_profiles ?? [{ value: "", label: t("watch.page.autoMatch") }];

  return (
    <section>
      <PageHeader
        eyebrow={t("watch.page.eyebrow")}
        title={t("watch.page.title")}
        description={t("watch.page.description")}
        actions={<button className="button ghost" onClick={workspace.refreshRoots}>{t("watch.page.refresh")}</button>}
      />

      <div className="panel-grid watch-grid">
        <WatchRootList roots={workspace.roots.data ?? []} selectedRootId={workspace.selectedRootId} onSelect={workspace.setSelectedRootId} onCreateNew={() => workspace.setSelectedRootId(null)} />
        <WatchRootFormPanel
          form={workspace.form}
          channelProfileOptions={channelProfileOptions}
          isEditing={Boolean(workspace.selectedRootId)}
          isSaving={workspace.createRoot.isPending}
          isDeleting={workspace.deleteRoot.isPending}
          autosaveState={workspace.updateState}
          autosaveError={workspace.updateError}
          onChange={workspace.setForm}
          onSubmit={() => {
            if (!workspace.selectedRootId) workspace.createRoot.mutate();
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
          isMerging={workspace.merge.isPending}
          isSuggesting={workspace.suggestMerge.isPending}
          isSmartGroupMerging={workspace.mergeSuggested.isPending}
          onScan={(force) => workspace.scan.mutate(force)}
          onEnqueue={(enqueueAll) => workspace.enqueue.mutate(enqueueAll)}
          onMerge={() => workspace.merge.mutate()}
          onSmartMergeSuggest={() => workspace.suggestMerge.mutate()}
          onMergeSmartGroup={(relativePaths) => workspace.mergeSuggested.mutate(relativePaths)}
          smartGroups={workspace.smartMergeGroups}
          onTogglePending={(relativePath, checked) =>
            workspace.setSelectedPending((prev) => (checked ? [...prev, relativePath] : prev.filter((entry) => entry !== relativePath)))
          }
        />
      )}
    </section>
  );
}
