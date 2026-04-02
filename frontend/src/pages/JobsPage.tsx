import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { ConfigProfileSwitcher } from "../features/configProfiles/ConfigProfileSwitcher";
import { useI18n } from "../i18n";
import { JobDetailPanel } from "../features/jobs/JobDetailPanel";
import { JobDetailModal } from "../features/jobs/JobDetailModal";
import { JobReviewOverlay } from "../features/jobs/JobReviewOverlay";
import { JobQueueTable } from "../features/jobs/JobQueueTable";
import { JobUploadPanel } from "../features/jobs/JobUploadPanel";
import { useJobWorkspace } from "../features/jobs/useJobWorkspace";

export function JobsPage() {
  const { t } = useI18n();
  const workspace = useJobWorkspace();
  const languageOptions = workspace.options.data?.job_languages ?? [{ value: "zh-CN", label: "简体中文" }];
  const workflowTemplateOptions = workspace.options.data?.workflow_templates ?? [{ value: "", label: t("watch.page.autoMatch") }];
  const workflowModeOptions = workspace.options.data?.workflow_modes ?? [{ value: "standard_edit", label: t("creative.workflow.standard_edit") }];
  const enhancementOptions = workspace.options.data?.enhancement_modes ?? [];
  const activeReviewStep =
    workspace.activity.data?.current_step?.step_name === "summary_review" || workspace.activity.data?.current_step?.step_name === "final_review"
      ? workspace.activity.data.current_step.step_name
      : workspace.selectedJob?.steps.find(
        (step) =>
          (step.step_name === "summary_review" || step.step_name === "final_review")
          && step.status !== "done",
      )?.step_name;
  const reviewStep = activeReviewStep === "final_review" ? "final_review" : "summary_review";
  const isReviewJob = Boolean(workspace.selectedJobId && activeReviewStep);

  return (
    <section className="page-stack">
      <PageHeader
        eyebrow={t("jobs.page.eyebrow")}
        title={t("jobs.page.title")}
        description={t("jobs.page.description")}
        summary={[
          { label: "第一步", value: "上传并创建任务", detail: "语言、模式和增强项都在这里一次选完" },
          { label: "第二步", value: "筛选并跟进队列", detail: "搜索、状态和详情面板集中在任务表格" },
          { label: "第三步", value: "复盘用量", detail: "只在需要时查看模型、步骤和缓存消耗" },
        ]}
        actions={
          <>
            <input className="input" value={workspace.keyword} onChange={(event) => workspace.setKeyword(event.target.value)} placeholder={t("jobs.page.searchPlaceholder")} />
            <button className="button ghost" onClick={workspace.refreshAll}>
              {t("jobs.page.refresh")}
            </button>
          </>
        }
      />

      <PageSection
        eyebrow="创建"
        title="创建任务与设置默认参数"
        description="新任务的语言、工作流、增强项和当前配置基线都在这一段完成，不需要先滚到队列表尾。"
      >
        <ConfigProfileSwitcher
          description="任务创建和审核确认都会继承这里激活的剪辑配置，数字人卡片只是其中一个配置模块，切换后新任务默认参数会立刻跟随。"
        />

        <JobUploadPanel
          upload={workspace.upload}
          languageOptions={languageOptions}
          workflowTemplateOptions={workflowTemplateOptions}
          workflowModeOptions={workflowModeOptions}
          enhancementOptions={enhancementOptions}
          onChange={workspace.setUpload}
          onSubmit={() => workspace.uploadJob.mutate()}
          isSubmitting={workspace.uploadJob.isPending}
        />
      </PageSection>

      <PageSection
        eyebrow="执行"
        title="跟进任务队列与审核详情"
        description="搜索、打开详情、重跑、取消和删除都集中在这里，优先保证处理链路顺畅。"
      >
        <JobQueueTable
          jobs={workspace.filteredJobs}
          selectedJobId={workspace.selectedJobId}
          isLoading={workspace.jobs.isLoading}
          errorMessage={workspace.jobs.isError ? (workspace.jobs.error as Error).message : undefined}
          isOpeningFolder={workspace.openFolder.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
          onSelect={workspace.setSelectedJobId}
          onOpenFolder={(jobId) => workspace.openFolder.mutate(jobId)}
          onCancel={(jobId) => workspace.cancelJob.mutate(jobId)}
          onRestart={(jobId) => workspace.restartJob.mutate(jobId)}
          onDelete={(jobId) => workspace.deleteJob.mutate(jobId)}
        />
      </PageSection>

      <JobReviewOverlay
        open={Boolean(workspace.selectedJobId && isReviewJob)}
        reviewStep={reviewStep}
        selectedJob={workspace.selectedJob}
        activity={workspace.activity.data}
        report={workspace.report.data}
        contentProfile={workspace.contentProfile.data}
        contentSource={workspace.contentSource}
        contentDraft={workspace.contentDraft}
        contentKeywords={workspace.contentKeywords}
        isConfirmingProfile={workspace.confirmProfile.isPending}
        isApplyingReview={workspace.applyReview.isPending}
        isSubmittingFinalReview={workspace.finalReviewDecision.isPending}
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
        onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        onApproveFinalReview={() => workspace.finalReviewDecision.mutate({ decision: "approve" })}
        onRejectFinalReview={(note) => workspace.finalReviewDecision.mutate({ decision: "reject", note })}
        onOpenFolder={() => workspace.selectedJob && workspace.openFolder.mutate(workspace.selectedJob.id)}
        onClose={() => workspace.setSelectedJobId(null)}
      />

      <JobDetailModal
        open={Boolean(workspace.selectedJobId && !isReviewJob)}
        title={workspace.selectedJob?.source_name}
        onClose={() => workspace.setSelectedJobId(null)}
      >
        <JobDetailPanel
          className="detail-panel-modal"
          selectedJobId={workspace.selectedJobId}
          selectedJob={workspace.selectedJob}
          isLoading={workspace.detail.isLoading}
          activity={workspace.activity.data}
          report={workspace.report.data}
          tokenUsage={workspace.tokenUsage.data}
          timeline={workspace.timeline.data}
          contentProfile={workspace.contentProfile.data}
          config={workspace.config.data}
          packaging={workspace.packaging.data}
          avatarMaterials={workspace.avatarMaterials.data}
          contentSource={workspace.contentSource}
          contentDraft={workspace.contentDraft}
          contentKeywords={workspace.contentKeywords}
          reviewEnhancementModes={workspace.reviewEnhancementModes}
          isConfirmingProfile={workspace.confirmProfile.isPending}
          isApplyingReview={workspace.applyReview.isPending}
          isCancelling={workspace.cancelJob.isPending}
          isRestarting={workspace.restartJob.isPending}
          isDeleting={workspace.deleteJob.isPending}
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
          onDelete={() => workspace.selectedJob && workspace.deleteJob.mutate(workspace.selectedJob.id)}
          onApplyReview={(targetId, action) => workspace.applyReview.mutate({ targetId, action })}
        />
      </JobDetailModal>
    </section>
  );
}
