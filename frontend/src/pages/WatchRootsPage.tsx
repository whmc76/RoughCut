import { useState } from "react";

import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { EmptyState } from "../components/ui/EmptyState";
import { WatchRootEditorModal } from "../features/watchRoots/WatchRootEditorModal";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { WatchRootList } from "../features/watchRoots/WatchRootList";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";
import { useI18n } from "../i18n";

export function WatchRootsPage() {
  const { t } = useI18n();
  const workspace = useWatchRootWorkspace();
  const [editorOpen, setEditorOpen] = useState(false);
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const configProfiles = workspace.configProfiles.data?.profiles ?? [];
  const activeConfigProfile = configProfiles.find((profile) => profile.is_active) ?? null;
  const boundConfigProfile = configProfiles.find((profile) => profile.id === workspace.form.config_profile_id) ?? null;
  const effectiveConfigProfile = boundConfigProfile ?? activeConfigProfile;
  const configProfileOptions = [
    { value: "", label: t("watch.form.followActiveProfileOption") },
    ...configProfiles.map((profile) => ({ value: profile.id, label: profile.name })),
  ];
  const modalTitle = workspace.isCreatingRoot
    ? "新建监看目录"
    : workspace.selectedRoot
      ? workspace.selectedRoot.path
      : "编辑监看目录";
  const modalSubtitle = workspace.isCreatingRoot
    ? "设置目录路径、默认方案和扫描规则。"
    : "点击目录卡片进入编辑，保存会自动同步到当前监看配置。";

  const handleCloseEditor = () => {
    setEditorOpen(false);
    if (workspace.isCreatingRoot) {
      workspace.closeCreateRoot();
    }
  };

  return (
    <section className="page-stack watch-roots-page">
      <PageHeader
        title={t("watch.page.title")}
        description={t("watch.page.description")}
        actions={<button className="button ghost" type="button" onClick={workspace.refreshRoots}>{t("watch.page.refresh")}</button>}
      />

      <section className="watch-command-strip">
        <article className="watch-command-chip">
          <span className="watch-command-label">已选目录</span>
          <strong>{workspace.selectedRoot ? workspace.selectedRoot.path : t("watch.page.pickRoot")}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">目录数</span>
          <strong>{`${(workspace.roots.data ?? []).length} ${t("watch.list.count")}`}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">待处理</span>
          <strong>{workspace.selectedRoot ? t("watch.page.healthTitle") : t("watch.page.pickRoot")}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">默认方案</span>
          <strong>{effectiveConfigProfile?.name ?? t("watch.form.followActiveProfileOption")}</strong>
        </article>
      </section>

      <section className="watch-workbench">
        <div className="watch-main-stage">
          <PageSection
            className="watch-health-lane"
            title="待处理内容"
            description={workspace.selectedRoot ? "查看这个目录里的内容。" : t("watch.page.pickRoot")}
          >
            {workspace.selectedRoot ? (
              <WatchRootInventoryPanel
                root={workspace.selectedRoot}
                inventory={workspace.inventory.data}
                selectedPending={workspace.selectedPending}
                isScanning={workspace.scan.isPending}
                scanError={workspace.scan.error instanceof Error ? workspace.scan.error.message : undefined}
                isEnqueueing={workspace.enqueue.isPending}
                isMerging={workspace.merge.isPending}
                isSuggesting={workspace.suggestMerge.isPending}
                onScan={(force) => workspace.scan.mutate(force)}
                onEnqueue={(enqueueAll) => workspace.enqueue.mutate(enqueueAll)}
                onMerge={() => workspace.merge.mutate()}
                onSmartMergeSuggest={() => workspace.suggestMerge.mutate()}
                isSmartGroupMerging={workspace.mergeSuggested.isPending}
                smartGroups={workspace.smartMergeGroups}
                onMergeSmartGroup={(relativePaths) => workspace.mergeSuggested.mutate(relativePaths)}
                onTogglePending={(relativePath, checked) =>
                  workspace.setSelectedPending((prev) => (checked ? [...prev, relativePath] : prev.filter((entry) => entry !== relativePath)))
                }
              />
            ) : (
              <EmptyState message={t("watch.page.pickRoot")} />
            )}
          </PageSection>
        </div>

        <aside className="watch-side-rail">
          <PageSection
            className="watch-roots-lane"
            title="目录"
            description={`${(workspace.roots.data ?? []).length} ${t("watch.list.count")}`}
          >
            <WatchRootList
              roots={workspace.roots.data ?? []}
              selectedRootId={workspace.selectedRootId}
              actionRootId={workspace.listActionRootId}
              onSelect={(rootId) => {
                workspace.closeCreateRoot();
                workspace.setSelectedRootId(rootId);
                setEditorOpen(true);
              }}
              onCreateNew={() => {
                workspace.openCreateRoot();
                setEditorOpen(true);
              }}
              onToggleEnabled={(root) => workspace.toggleRootEnabled.mutate(root)}
              onDelete={(root) => {
                if (!window.confirm(`确认删除监看目录“${root.path}”？`)) return;
                workspace.deleteRootById.mutate(root.id);
              }}
            />
          </PageSection>
        </aside>
      </section>

      <WatchRootEditorModal
        open={editorOpen}
        title={modalTitle}
        subtitle={modalSubtitle}
        onClose={handleCloseEditor}
      >
        <WatchRootFormPanel
          form={workspace.form}
          configProfileOptions={configProfileOptions}
          boundConfigProfile={boundConfigProfile}
          effectiveConfigProfile={effectiveConfigProfile}
          workflowTemplateOptions={workflowTemplateOptions}
          isEditing={!workspace.isCreatingRoot && Boolean(workspace.selectedRootId)}
          isSaving={workspace.createRoot.isPending}
          isDeleting={workspace.deleteRoot.isPending}
          autosaveState={workspace.updateState}
          autosaveError={workspace.updateError}
          onChange={workspace.setForm}
          onSubmit={() => {
            if (workspace.isCreatingRoot) {
              workspace.createRoot.mutate(undefined, {
                onSuccess: () => setEditorOpen(false),
              });
            }
          }}
          onDelete={() => {
            if (!workspace.selectedRoot) return;
            if (!window.confirm(`确认删除监看目录“${workspace.selectedRoot.path}”？`)) return;
            workspace.deleteRoot.mutate(undefined, {
              onSuccess: () => setEditorOpen(false),
            });
          }}
        />
      </WatchRootEditorModal>
    </section>
  );
}
