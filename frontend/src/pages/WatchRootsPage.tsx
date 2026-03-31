import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { WatchRootList } from "../features/watchRoots/WatchRootList";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";
import { useI18n } from "../i18n";

export function WatchRootsPage() {
  const { t } = useI18n();
  const workspace = useWatchRootWorkspace();
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("watch.page.eyebrow")}
        title={t("watch.page.title")}
        description={t("watch.page.description")}
        summary={[
          { label: "目录接入", value: "先选根目录与频道", detail: "左侧列表负责维护监听范围" },
          { label: "库存整理", value: "扫描后再决定入队", detail: "避免未整理内容直接进入生产队列" },
          { label: "批量处理", value: "合并、建议分组、批量入队", detail: "页面重点是减少重复手工操作" },
        ]}
        actions={<button className="button ghost" onClick={workspace.refreshRoots}>{t("watch.page.refresh")}</button>}
      />

      <PageSection
        eyebrow="接入"
        title="先维护监听目录"
        description="左边管理目录范围，右边维护当前选中目录的规则。先把入口整理好，再做扫描和入队。"
      >
        <div className="panel-grid watch-grid">
          <WatchRootList roots={workspace.roots.data ?? []} selectedRootId={workspace.selectedRootId} onSelect={workspace.setSelectedRootId} onCreateNew={() => workspace.setSelectedRootId(null)} />
          <WatchRootFormPanel
            form={workspace.form}
            workflowTemplateOptions={workflowTemplateOptions}
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
      </PageSection>

      {workspace.selectedRoot && (
        <PageSection
          eyebrow="库存"
          title="扫描、整理并批量入队"
          description="库存面板只在选中目录后显示，避免没有上下文时就出现大量批处理操作。"
        >
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
        </PageSection>
      )}
    </section>
  );
}
