import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { EmptyState } from "../components/ui/EmptyState";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { WatchRootList } from "../features/watchRoots/WatchRootList";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";
import { useI18n } from "../i18n";

export function WatchRootsPage() {
  const { t } = useI18n();
  const workspace = useWatchRootWorkspace();
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const configProfiles = workspace.configProfiles.data?.profiles ?? [];
  const activeConfigProfile = configProfiles.find((profile) => profile.is_active) ?? null;
  const boundConfigProfile = configProfiles.find((profile) => profile.id === workspace.form.config_profile_id) ?? null;
  const effectiveConfigProfile = boundConfigProfile ?? activeConfigProfile;
  const configProfileOptions = [
    { value: "", label: t("watch.form.followActiveProfileOption") },
    ...configProfiles.map((profile) => ({ value: profile.id, label: profile.name })),
  ];

  return (
    <section className="page-stack watch-roots-page">
      <PageHeader
        eyebrow={t("watch.page.eyebrow")}
        title={t("watch.page.title")}
        description={t("watch.page.description")}
        actions={<button className="button ghost" onClick={workspace.refreshRoots}>{t("watch.page.refresh")}</button>}
      />

      <section className="watch-command-strip">
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("watch.page.healthEyebrow")}</span>
          <strong>{workspace.selectedRoot ? workspace.selectedRoot.path : t("watch.page.pickRoot")}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("watch.page.rootsEyebrow")}</span>
          <strong>{`${(workspace.roots.data ?? []).length} ${t("watch.list.count")}`}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("watch.page.healthTitle")}</span>
          <strong>{workspace.selectedRoot ? t("watch.page.healthTitle") : t("watch.page.pickRoot")}</strong>
        </article>
        <article className="watch-command-chip">
          <span className="watch-command-label">{t("watch.form.followActiveProfileOption")}</span>
          <strong>{effectiveConfigProfile?.name ?? t("watch.form.followActiveProfileOption")}</strong>
        </article>
      </section>

      <section className="watch-workbench">
        <div className="watch-main-stage">
          <PageSection
            className="watch-health-lane"
            eyebrow={t("watch.page.healthEyebrow")}
            title={t("watch.page.healthTitle")}
            description={workspace.selectedRoot ? t("watch.page.pickRoot") : t("watch.page.description")}
          >
            {workspace.selectedRoot ? (
              <WatchRootInventoryPanel
                root={workspace.selectedRoot}
                inventory={workspace.inventory.data}
                selectedPending={workspace.selectedPending}
                isScanning={workspace.scan.isPending}
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
            eyebrow={t("watch.page.rootsEyebrow")}
            title={t("watch.page.rootsTitle")}
            description={`${(workspace.roots.data ?? []).length} ${t("watch.list.count")}`}
          >
            <WatchRootList
              roots={workspace.roots.data ?? []}
              selectedRootId={workspace.selectedRootId}
              onSelect={workspace.setSelectedRootId}
              onCreateNew={() => workspace.setSelectedRootId(null)}
            />
          </PageSection>

          <PageSection
            className="watch-form-lane"
            title={workspace.selectedRootId ? t("watch.form.editTitle") : t("watch.form.createTitle")}
            description={t("watch.form.description")}
          >
            <WatchRootFormPanel
              form={workspace.form}
              configProfileOptions={configProfileOptions}
              boundConfigProfile={boundConfigProfile}
              effectiveConfigProfile={effectiveConfigProfile}
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
          </PageSection>
        </aside>
      </section>
    </section>
  );
}
