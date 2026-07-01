import { useState } from "react";
import {
  CheckCircle2,
  ClipboardList,
  FolderCog,
  FolderOpen,
  ListChecks,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  UploadCloud,
  UserRound,
} from "lucide-react";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { WatchRootEditorModal } from "../features/watchRoots/WatchRootEditorModal";
import { WatchRootFormPanel } from "../features/watchRoots/WatchRootFormPanel";
import { WatchRootInventoryPanel } from "../features/watchRoots/WatchRootInventoryPanel";
import { useWatchRootWorkspace } from "../features/watchRoots/useWatchRootWorkspace";
import { useI18n } from "../i18n";
import type { ConfigProfile, WatchRoot } from "../types";
import { classNames } from "../utils";

const TASK_TYPE_LABELS: Record<WatchRoot["edit_mode"], string> = {
  auto: "智能匹配",
  talking_head: "口播剪辑",
  tutorial: "教程剪辑",
  vlog: "Vlog 剪辑",
  highlight: "高光剪辑",
  multi_material: "多素材剪辑",
};

function rootPolicyLabel(root: Pick<WatchRoot, "ingest_mode">) {
  return root.ingest_mode === "full_auto" ? "检测到新文件后立即开始" : "加入队列，手动开始";
}

function profileNameForRoot(root: WatchRoot, profiles: ConfigProfile[], activeProfile: ConfigProfile | null) {
  if (!root.config_profile_id) return activeProfile ? `跟随当前：${activeProfile.name}` : "跟随当前创作者配置";
  return profiles.find((profile) => profile.id === root.config_profile_id)?.name ?? "已绑定创作者配置";
}

function compactPath(path: string) {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts.length >= 2 ? parts.slice(-2).join("\\") : path;
}

export function WatchRootsPage() {
  const { t } = useI18n();
  const workspace = useWatchRootWorkspace();
  const [editorOpen, setEditorOpen] = useState(false);
  const [rootKeyword, setRootKeyword] = useState("");
  const roots = workspace.roots.data ?? [];
  const enabledRootCount = roots.filter((root) => root.enabled).length;
  const fullAutoRootCount = roots.filter((root) => root.ingest_mode === "full_auto").length;
  const manualQueueRootCount = roots.filter((root) => root.ingest_mode === "task_only").length;
  const pendingCount = workspace.inventory.data?.pending_count ?? 0;
  const processedCount = workspace.inventory.data?.deduped_count ?? 0;
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
    ? "新建自动任务"
    : workspace.selectedRoot
      ? workspace.selectedRoot.path
      : "编辑自动任务";
  const modalSubtitle = workspace.isCreatingRoot
    ? "设置监听目录、任务类型、创作者配置和进入剪辑队列的启动方式。"
    : "这些规则会用于自动创建普通剪辑任务，保存后立即生效。";
  const productControlSummary = workspace.selectedRoot
    ? `${rootPolicyLabel(workspace.selectedRoot)} / ${profileNameForRoot(workspace.selectedRoot, configProfiles, activeConfigProfile)}`
    : t("watch.page.pickRoot");
  const normalizedKeyword = rootKeyword.trim().toLowerCase();
  const visibleRoots = normalizedKeyword
    ? roots.filter((root) => {
        const searchable = [
          root.path,
          root.workflow_template ?? "",
          TASK_TYPE_LABELS[root.edit_mode],
          profileNameForRoot(root, configProfiles, activeConfigProfile),
          rootPolicyLabel(root),
        ].join(" ").toLowerCase();
        return searchable.includes(normalizedKeyword);
      })
    : roots;
  const queuePreviewItems = workspace.selectedRoot
    ? (workspace.inventory.data?.inventory.pending ?? []).slice(0, 3)
    : [];

  const openCreateEditor = () => {
    workspace.openCreateRoot();
    setEditorOpen(true);
  };

  const handleCloseEditor = () => {
    setEditorOpen(false);
    if (workspace.isCreatingRoot) {
      workspace.closeCreateRoot();
    }
  };

  return (
    <section className="page-stack watch-roots-page auto-task-page">
      <PageHeader
        eyebrow="Production Automation"
        title="自动任务设置"
        description="把目录里的新素材自动创建为普通剪辑任务，并进入制片队列。"
        actions={(
          <div className="auto-task-header-actions">
            <a className="button ghost" href="/jobs">返回队列</a>
            <button className="button ghost" type="button" onClick={workspace.refreshRoots}>
              <RefreshCw size={16} aria-hidden="true" />
              {t("watch.page.refresh")}
            </button>
            <button className="button primary" type="button" onClick={openCreateEditor}>
              <Plus size={16} aria-hidden="true" />
              新建规则
            </button>
          </div>
        )}
      />

      <section className="auto-task-command">
        <div className="auto-task-command-copy">
          <span className="auto-task-kicker">Queue Automation</span>
          <strong>目录到剪辑队列</strong>
          <p>每条规则监听一个素材目录，检测到新文件后创建普通剪辑任务；后续启动、恢复和审看都回到制片队列处理。</p>
        </div>
        <div className="auto-task-flow" aria-label="自动任务流程">
          <span>
            <FolderOpen size={16} aria-hidden="true" />
            <strong>监听目录</strong>
            <small>识别新增素材</small>
          </span>
          <span>
            <ClipboardList size={16} aria-hidden="true" />
            <strong>创建剪辑任务</strong>
            <small>套用任务类型</small>
          </span>
          <span>
            <UploadCloud size={16} aria-hidden="true" />
            <strong>进入队列</strong>
            <small>立即开始或待启动</small>
          </span>
        </div>
        <div className="auto-task-command-state">
          <span>选中规则</span>
          <strong>{productControlSummary}</strong>
        </div>
      </section>

      <section className="auto-task-metrics" aria-label="自动任务状态">
        <article>
          <FolderCog size={18} aria-hidden="true" />
          <span>监听目录</span>
          <strong>{roots.length}</strong>
          <small>{enabledRootCount} 个已启用</small>
        </article>
        <article>
          <PlayCircle size={18} aria-hidden="true" />
          <span>立即开始</span>
          <strong>{fullAutoRootCount}</strong>
          <small>检测到新文件后自动启动剪辑</small>
        </article>
        <article>
          <ListChecks size={18} aria-hidden="true" />
          <span>手动开始</span>
          <strong>{manualQueueRootCount}</strong>
          <small>只加入制片队列，等待人工启动</small>
        </article>
        <article>
          <CheckCircle2 size={18} aria-hidden="true" />
          <span>待处理</span>
          <strong>{pendingCount}</strong>
          <small>选中目录待创建队列任务，已处理 {processedCount}</small>
        </article>
      </section>

      <section className="auto-task-workbench">
        <aside className="auto-task-list-rail">
          <section className="panel auto-task-root-panel">
            <PanelHeader
              title="自动任务规则"
              description={`${roots.length} 个监听目录`}
              actions={<button className="button ghost button-sm" type="button" onClick={openCreateEditor}>新建</button>}
            />
            <label className="auto-task-root-search">
              <Search size={16} aria-hidden="true" />
              <input value={rootKeyword} onChange={(event) => setRootKeyword(event.target.value)} placeholder="搜索目录、任务类型或创作者配置" />
            </label>
            <div className="auto-task-root-list">
              {visibleRoots.map((root) => {
                const selected = root.id === workspace.selectedRootId;
                const actionPending = workspace.listActionRootId === root.id;
                return (
                  <article
                    key={root.id}
                    className={classNames("auto-task-root-card", selected && "is-selected", !root.enabled && "is-disabled")}
                    onClick={() => {
                      workspace.closeCreateRoot();
                      workspace.setSelectedRootId(root.id);
                      setEditorOpen(true);
                    }}
                  >
                    <div className="auto-task-root-main">
                      <span className="auto-task-root-icon">
                        <FolderOpen size={17} aria-hidden="true" />
                      </span>
                      <div>
                        <strong title={root.path}>{compactPath(root.path)}</strong>
                        <small>{root.path}</small>
                      </div>
                    </div>
                    <div className="auto-task-root-tags">
                      <span className={classNames("auto-task-root-tag", root.enabled ? "enabled" : "muted")}>
                        {root.enabled ? "已启用" : "已停用"}
                      </span>
                      <span className="auto-task-root-tag">{TASK_TYPE_LABELS[root.edit_mode]}</span>
                      <span className="auto-task-root-tag warm">
                        <UserRound size={13} aria-hidden="true" />
                        {profileNameForRoot(root, configProfiles, activeConfigProfile)}
                      </span>
                      <span className={classNames("auto-task-root-tag", root.ingest_mode === "full_auto" ? "auto" : "manual")}>
                        {root.ingest_mode === "full_auto" ? "立即开始" : "手动开始"}
                      </span>
                    </div>
                    <div className="auto-task-root-actions">
                      <button
                        className="button ghost button-sm"
                        type="button"
                        disabled={actionPending}
                        onClick={(event) => {
                          event.stopPropagation();
                          workspace.toggleRootEnabled.mutate(root);
                        }}
                      >
                        {root.enabled ? "停用" : "启用"}
                      </button>
                      <button
                        className="button ghost button-sm"
                        type="button"
                        disabled={actionPending}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (!window.confirm(`确认删除自动任务“${root.path}”？`)) return;
                          workspace.deleteRootById.mutate(root.id);
                        }}
                      >
                        删除
                      </button>
                    </div>
                  </article>
                );
              })}
              {!visibleRoots.length ? <EmptyState message="没有匹配的自动任务规则。" /> : null}
            </div>
          </section>
        </aside>

        <div className="auto-task-main-stage">
          {workspace.selectedRoot ? (
            <section className="panel auto-task-rule-summary">
              <PanelHeader
                title="规则设置"
                description="这条规则会把目录里的新素材创建为普通剪辑任务。"
                actions={<button className="button ghost button-sm" type="button" onClick={() => setEditorOpen(true)}>编辑规则</button>}
              />
              <div className="auto-task-rule-grid">
                <article>
                  <span>监听目录</span>
                  <strong>{workspace.selectedRoot.path}</strong>
                  <small>{workspace.selectedRoot.recursive ? "包含子目录" : "仅当前目录"} / {workspace.selectedRoot.scan_mode === "precise" ? "精确扫描" : "快速扫描"}</small>
                </article>
                <article>
                  <span>任务类型</span>
                  <strong>{TASK_TYPE_LABELS[workspace.selectedRoot.edit_mode]}</strong>
                  <small>{workspace.selectedRoot.workflow_template || "自动匹配工作流"} / {workspace.selectedRoot.job_flow_mode === "smart_assist" ? "智能辅助" : "自动流程"}</small>
                </article>
                <article>
                  <span>创作者配置绑定</span>
                  <strong>{profileNameForRoot(workspace.selectedRoot, configProfiles, activeConfigProfile)}</strong>
                  <small>{workspace.selectedRoot.config_profile_id ? "使用专属配置" : "跟随当前启用配置"}</small>
                </article>
                <article>
                  <span>入队策略</span>
                  <strong>{workspace.selectedRoot.ingest_mode === "full_auto" ? "立即开始" : "手动开始"}</strong>
                  <small>{rootPolicyLabel(workspace.selectedRoot)}</small>
                </article>
              </div>
            </section>
          ) : null}

          {workspace.selectedRoot ? (
            <section className="panel auto-task-queue-preview">
              <PanelHeader title="将创建的队列任务" description="自动任务创建后会出现在制片队列，和手动创建任务一致。" />
              <div className="auto-task-preview-list">
                {queuePreviewItems.length ? queuePreviewItems.map((item) => (
                  <article key={item.relative_path}>
                    <ClipboardList size={16} aria-hidden="true" />
                    <div>
                      <strong>{item.source_name}</strong>
                      <small>{item.relative_path}</small>
                    </div>
                    <span>{workspace.selectedRoot?.ingest_mode === "full_auto" ? "排队中" : "待处理"}</span>
                  </article>
                )) : <EmptyState message="当前没有待创建的队列任务。可以在下方重新扫描目录。" />}
              </div>
            </section>
          ) : null}

          <PageSection
            className="watch-health-lane auto-task-inventory-lane"
            title="待处理内容"
            description={workspace.selectedRoot ? "扫描目录、归并素材，并创建普通剪辑任务。" : t("watch.page.pickRoot")}
          >
            {workspace.selectedRoot ? (
              <WatchRootInventoryPanel
                root={workspace.selectedRoot}
                inventory={workspace.inventory.data}
                selectedPending={workspace.selectedPending}
                isScanning={workspace.scan.isPending}
                scanError={workspace.scan.error instanceof Error ? workspace.scan.error.message : undefined}
                isEnqueueing={workspace.enqueue.isPending}
                enqueueError={workspace.enqueue.error instanceof Error ? workspace.enqueue.error.message : undefined}
                isMerging={workspace.merge.isPending}
                mergeError={
                  workspace.merge.error instanceof Error
                    ? workspace.merge.error.message
                    : workspace.mergeSuggested.error instanceof Error
                      ? workspace.mergeSuggested.error.message
                      : undefined
                }
                isSuggesting={workspace.suggestMerge.isPending}
                suggestError={workspace.suggestMerge.error instanceof Error ? workspace.suggestMerge.error.message : undefined}
                onScan={(force) => workspace.scan.mutate(force)}
                onEnqueue={(enqueueAll) => workspace.enqueue.mutate({ enqueueAll })}
                onEnqueueItem={(relativePath) => workspace.enqueue.mutate({ relativePaths: [relativePath] })}
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
            if (!window.confirm(`确认删除自动任务“${workspace.selectedRoot.path}”？`)) return;
            workspace.deleteRoot.mutate(undefined, {
              onSuccess: () => setEditorOpen(false),
            });
          }}
        />
      </WatchRootEditorModal>
    </section>
  );
}
