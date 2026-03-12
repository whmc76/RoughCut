import { PageHeader } from "../components/ui/PageHeader";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import { useJobWorkspace } from "../features/jobs/useJobWorkspace";

export function JobsPage() {
  const workspace = useJobWorkspace();

  return (
    <section>
      <PageHeader
        eyebrow="Pipeline"
        title="任务列表"
        description="页面层只做查询编排，详情区块已经拆成独立组件，后续继续加功能不会再堆成一个大文件。"
        actions={
          <>
            <input className="input" value={workspace.keyword} onChange={(event) => workspace.setKeyword(event.target.value)} placeholder="搜索文件名、摘要、状态" />
            <button className="button ghost" onClick={workspace.refreshAll}>
              刷新
            </button>
          </>
        }
      />

      <JobUploadPanel upload={workspace.upload} onChange={workspace.setUpload} onSubmit={() => workspace.uploadJob.mutate()} isSubmitting={workspace.uploadJob.isPending} />

      <div className="panel-grid jobs-grid top-gap">
        <JobQueueTable
          jobs={workspace.filteredJobs}
          selectedJobId={workspace.selectedJobId}
          isLoading={workspace.jobs.isLoading}
          errorMessage={workspace.jobs.isError ? (workspace.jobs.error as Error).message : undefined}
          onSelect={workspace.setSelectedJobId}
        />

        <JobDetailPanel
          selectedJobId={workspace.selectedJobId}
          selectedJob={workspace.selectedJob}
          isLoading={workspace.detail.isLoading}
          activity={workspace.activity.data}
          report={workspace.report.data}
          timeline={workspace.timeline.data}
          contentProfile={workspace.contentProfile.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          onContentFieldChange={(field, value) => workspace.setContentDraft((prev) => ({ ...prev, [field]: value }))}
          onKeywordsChange={(value) =>
            workspace.setContentDraft((prev) => ({
              ...prev,
              keywords: value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            }))
          }
          onConfirmProfile={() => workspace.confirmProfile.mutate()}
          onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
          onCancel={() => workspace.selectedJob && workspace.cancelJob.mutate(workspace.selectedJob.id)}
          onRestart={() => workspace.selectedJob && workspace.restartJob.mutate(workspace.selectedJob.id)}
          onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        />
      </div>
    </section>
  );
}
