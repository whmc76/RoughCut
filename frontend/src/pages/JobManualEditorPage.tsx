import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import type { JobManualEditSectionState } from "../features/jobs/JobManualEditSection";
import { STEP_LABELS } from "../features/jobs/constants";
import type { JobManualEditApplyPayload, JobManualEditorReadiness, JobManualEditorReadinessStep } from "../types";

const JobManualEditSection = lazy(async () => ({
  default: (await import("../features/jobs/JobManualEditSection")).JobManualEditSection,
}));

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || "未知错误");
}

function draftSaveErrorMessage(error: unknown) {
  const message = errorMessage(error);
  if (/method not allowed/i.test(message)) {
    return "后端服务尚未加载草稿保存接口，请重启 RoughCut API 后重试。";
  }
  return message || "请刷新后重试。";
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function stepProgressPercent(step: JobManualEditorReadinessStep) {
  if (step.status === "done" || step.status === "skipped") return 100;
  if (typeof step.progress === "number") return clampPercent(step.progress * 100);
  return 0;
}

function stepStatusText(step: JobManualEditorReadinessStep, isCurrent: boolean) {
  if (step.status === "done") return "已完成";
  if (step.status === "skipped") return "已跳过";
  if (step.status === "failed") return "失败";
  if (step.status === "cancelled") return "已取消";
  if (step.status === "running" || step.status === "processing") return "进行中";
  if (step.status === "queued") return "排队中";
  if (isCurrent) return "等待开始";
  return "未开始";
}

function stepDetailText(step: JobManualEditorReadinessStep, isCurrent: boolean) {
  if (step.detail) return step.detail;
  if (step.status === "done") return "该阶段产物已生成。";
  if (step.status === "skipped") return "当前任务不需要执行该阶段。";
  if (step.status === "failed") return "该阶段执行失败，请查看任务错误信息。";
  if (step.status === "queued") return "已进入任务队列，等待 worker 执行。";
  if (step.status === "running" || step.status === "processing") return "正在生成该阶段所需结果。";
  if (isCurrent) return "上游条件满足后会立即开始。";
  return "等待前置阶段完成。";
}

function readinessEmptyStateMessage(readiness: JobManualEditorReadiness) {
  if (readiness.status === "failed") {
    return readiness.detail ? `手动调整预处理失败：${readiness.detail}` : "手动调整预处理失败，请回到任务列表查看错误详情。";
  }
  if (readiness.status === "blocked") {
    return readiness.detail || "手动调整暂不可用，请先处理当前任务状态。";
  }
  return readiness.detail || "手动调整工作区还在预处理，完成后会自动打开编辑器。";
}

function manualEditorRetryStartStep(readiness?: JobManualEditorReadiness) {
  const failedStep = readiness?.required_steps.find((step) => step.status === "failed" || step.status === "cancelled");
  if (failedStep?.step_name) return failedStep.step_name;
  if (readiness?.missing?.some((item) => item === "editorial_timeline" || item === "render_plan")) return "edit_plan";
  if (readiness?.missing?.includes("media_meta")) return "probe";
  return null;
}

function manualEditorRetryStartLabel(startStep: string | null) {
  if (!startStep) return "";
  return STEP_LABELS[startStep] || startStep;
}

function hasCompletedRender(job: Awaited<ReturnType<typeof api.getJob>> | undefined) {
  return Boolean(job?.steps?.some((step) => step.step_name === "render" && step.status === "done" && step.finished_at));
}

function ManualEditorReadinessPanel({ readiness }: { readiness?: JobManualEditorReadiness }) {
  const progress = clampPercent(readiness?.progress_percent ?? 0);
  const requiredSteps = readiness?.required_steps ?? [];
  const currentStep = readiness?.required_steps.find((step) => step.step_name === readiness.current_step);
  const currentStepIndex = currentStep ? requiredSteps.findIndex((step) => step.step_name === currentStep.step_name) + 1 : 0;
  const completedCount = requiredSteps.filter((step) => step.status === "done" || step.status === "skipped").length;
  const failedCount = requiredSteps.filter((step) => step.status === "failed" || step.status === "cancelled").length;
  const activeStepNumber = currentStepIndex || Math.min(requiredSteps.length, completedCount + 1);
  const title = readiness?.status === "blocked"
    ? "手动调整暂不可用"
    : readiness?.status === "failed" ? "手动调整预处理失败" : "正在准备手动调整工作区";
  return (
    <section className="manual-editor-readiness-panel">
      <div className="manual-editor-preview-head">
        <div>
          <strong>{title}</strong>
          <p className="muted compact-top">
            {readiness?.detail || "正在生成手动调整所需媒体、字幕、剪辑时间线和渲染计划。"}
          </p>
        </div>
        <span className={`status-pill ${readiness?.status === "failed" ? "failed" : readiness?.status === "blocked" ? "pending" : "running"}`}>
          {progress}%
        </span>
      </div>
      {requiredSteps.length ? (
        <div className="manual-editor-readiness-summary" aria-label="手动调整预处理概览">
          <div>
            <strong>{completedCount}/{requiredSteps.length}</strong>
            <span>已完成阶段</span>
          </div>
          <div>
            <strong>{activeStepNumber || "-"}</strong>
            <span>当前阶段</span>
          </div>
          <div>
            <strong>{failedCount}</strong>
            <span>异常阶段</span>
          </div>
        </div>
      ) : null}
      <div className="manual-editor-readiness-progress" aria-label="手动调整预处理进度">
        <span style={{ width: `${progress}%` }} />
      </div>
      {currentStep ? (
        <p className="manual-editor-current-step">
          当前步骤：<strong>{currentStep.label}</strong>
          {typeof currentStep.progress === "number" ? <span>{stepProgressPercent(currentStep)}%</span> : null}
        </p>
      ) : null}
      {requiredSteps.length ? (
        <div className="manual-editor-readiness-step-list">
          {requiredSteps.map((step, index) => {
            const isCurrent = step.step_name === readiness?.current_step;
            const stepProgress = stepProgressPercent(step);
            return (
              <div
                key={step.step_name}
                className={`manual-editor-readiness-step ${step.status}${isCurrent ? " current" : ""}`}
              >
                <div className="manual-editor-readiness-step-index">{String(index + 1).padStart(2, "0")}</div>
                <div className="manual-editor-readiness-step-main">
                  <div className="manual-editor-readiness-step-head">
                    <strong>{step.label}</strong>
                    <span className={`status-pill ${step.status}`}>{stepStatusText(step, isCurrent)}</span>
                  </div>
                  <p>{stepDetailText(step, isCurrent)}</p>
                  <div
                    className="manual-editor-readiness-step-progress"
                    role="progressbar"
                    aria-label={`${step.label}进度`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={stepProgress}
                  >
                    <span style={{ width: `${stepProgress}%` }} />
                  </div>
                </div>
                <span className="manual-editor-readiness-step-percent">{stepProgress}%</span>
              </div>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

export function JobManualEditorPage() {
  const { jobId = "" } = useParams();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [lastDraftSavedAt, setLastDraftSavedAt] = useState<string | null>(null);
  const [manualEditState, setManualEditState] = useState<JobManualEditSectionState | null>(null);
  const [resetSignal, setResetSignal] = useState(0);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId),
    enabled: Boolean(jobId),
  });
  const manualEditorReadiness = useQuery({
    queryKey: ["job-manual-editor-readiness", jobId],
    queryFn: () => api.getJobManualEditorReadiness(jobId),
    enabled: Boolean(jobId),
    refetchInterval: (query) => (query.state.data?.status === "preprocessing" ? 2_500 : false),
    staleTime: 5_000,
    retry: 1,
  });
  const manualEditor = useQuery({
    queryKey: ["job-manual-editor", jobId],
    queryFn: () => api.getJobManualEditor(jobId),
    enabled: Boolean(jobId && manualEditorReadiness.data?.can_open_editor),
    staleTime: 15_000,
    retry: 1,
  });
  const manualEditorAssets = useQuery({
    queryKey: ["job-manual-editor-assets", jobId],
    queryFn: () => api.warmJobManualEditorAssets(jobId),
    enabled: Boolean(jobId && manualEditor.data?.source_url),
    refetchInterval: (query) => (query.state.data?.ready || query.state.data?.status === "failed" ? false : 2_500),
    staleTime: 10_000,
    retry: 1,
  });
  useEffect(() => {
    setLastDraftSavedAt(manualEditor.data?.draft_saved_at ?? null);
  }, [jobId, manualEditor.data?.draft_saved_at]);
  const applyManualEditor = useMutation({
    mutationFn: async (payload: JobManualEditApplyPayload) => api.applyJobManualEditor(jobId, payload),
    onSuccess: async (result) => {
      setNotice({
        tone: "success",
        message: result.detail?.trim() || `手动调整已保存，重跑链路：${result.rerun_steps.join(" -> ") || "render"}`,
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-manual-editor-readiness", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-manual-editor", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-manual-editor-assets", jobId] }),
      ]);
      navigate("/jobs");
    },
    onError: (error) => {
      setNotice({ tone: "error", message: `手动调整保存失败：${errorMessage(error) || "请刷新后重试。"}` });
    },
  });
  const saveManualEditorDraft = useMutation({
    mutationFn: async (payload: JobManualEditApplyPayload) => api.saveJobManualEditorDraft(jobId, payload),
    onSuccess: (result) => {
      setLastDraftSavedAt(result.saved_at);
      setNotice({
        tone: "success",
        message: result.detail?.trim() || "手动调整草稿已自动保存。",
      });
    },
    onError: (error) => {
      setNotice({ tone: "error", message: `自动保存失败：${draftSaveErrorMessage(error)}` });
    },
  });
  const detectRotation = useMutation({
    mutationFn: async () => api.detectJobManualEditorRotation(jobId),
    onError: (error) => {
      setNotice({ tone: "error", message: `画面方向检测失败：${errorMessage(error) || "请手动选择角度。"}` });
    },
  });
  const applyManualEditorMutate = applyManualEditor.mutate;
  const saveManualEditorDraftMutate = saveManualEditorDraft.mutate;
  const detectRotationMutateAsync = detectRotation.mutateAsync;

  const handleApplyManualEdit = () => {
    if (!manualEditState?.canApply) return;
    const confirmed = window.confirm(
      [
        "确认保存手动调整？",
        `保存类型：${manualEditState.savePlanLabel}`,
        `输出时长变化：${manualEditState.outputDurationDeltaLabel}`,
        `字幕修改：${manualEditState.subtitleOverrideCount} 条`,
        manualEditState.saveImpactSummary,
      ].join("\n"),
    );
    if (!confirmed) return;
    applyManualEditor.mutate(manualEditState.payload);
  };

  const handleDiscardManualEdit = () => {
    if (!manualEditState?.hasLocalEdits) return;
    setResetSignal((value) => value + 1);
    setNotice({ tone: "success", message: "已放弃本地改动，恢复到当前自动保存版本。" });
  };

  const handleManualEditStateChange = useCallback((nextState: JobManualEditSectionState) => {
    setManualEditState((currentState) => {
      if (
        currentState
        && currentState.canApply === nextState.canApply
        && currentState.hasMaterialEdits === nextState.hasMaterialEdits
        && currentState.hasLocalEdits === nextState.hasLocalEdits
        && currentState.hasVideoSummaryEdits === nextState.hasVideoSummaryEdits
        && currentState.savePlanLabel === nextState.savePlanLabel
        && currentState.baseSegmentCount === nextState.baseSegmentCount
        && currentState.effectiveSegmentCount === nextState.effectiveSegmentCount
        && currentState.outputDurationDeltaLabel === nextState.outputDurationDeltaLabel
        && currentState.subtitleOverrideCount === nextState.subtitleOverrideCount
        && currentState.saveImpactSummary === nextState.saveImpactSummary
        && JSON.stringify(currentState.payload) === JSON.stringify(nextState.payload)
      ) {
        return currentState;
      }
      return nextState;
    });
  }, []);

  const handleApplyManualEditorPayload = useCallback(
    (payload: JobManualEditApplyPayload) => {
      applyManualEditorMutate(payload);
    },
    [applyManualEditorMutate],
  );

  const handleAutoSaveManualEditorDraft = useCallback(
    (payload: JobManualEditApplyPayload) => {
      saveManualEditorDraftMutate(payload);
    },
    [saveManualEditorDraftMutate],
  );

  const handleDetectManualEditorRotation = useCallback(async () => {
    const result = await detectRotationMutateAsync();
    return result.rotation_cw;
  }, [detectRotationMutateAsync]);

  const noticeClass = notice?.tone === "error" ? "notice notice-error top-gap" : "notice top-gap";
  const manualEditorActionsEnabled = Boolean(manualEditor.data && manualEditorReadiness.data?.can_edit);
  const renderActionLabel = hasCompletedRender(job.data) ? "根据当前改动重新渲染" : "根据当前改动正式渲染";
  const renderSubmittingLabel = hasCompletedRender(job.data) ? "重新渲染提交中..." : "正式渲染提交中...";
  const retryStartStep = manualEditorRetryStartStep(manualEditorReadiness.data);
  const retryStartLabel = manualEditorRetryStartLabel(retryStartStep);
  const retryManualEditorPreparation = useMutation({
    mutationFn: async (startStep: string) => api.rerunJob(jobId, {
      rerun_start_step: startStep,
      note: "手动调整预处理失败后从断点重试",
    }),
    onSuccess: async (result) => {
      setNotice({
        tone: "success",
        message: result.detail?.trim() || `已请求从 ${result.rerun_start_step} 重试。`,
      });
      await Promise.all([
        queryClient.refetchQueries({ queryKey: ["job-manual-editor-readiness", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["jobs"] }),
        queryClient.invalidateQueries({ queryKey: ["job", jobId] }),
        queryClient.removeQueries({ queryKey: ["job-manual-editor", jobId] }),
        queryClient.removeQueries({ queryKey: ["job-manual-editor-assets", jobId] }),
      ]);
    },
    onError: (error) => {
      setNotice({ tone: "error", message: `断点重试失败：${errorMessage(error) || "请稍后重试。"}` });
    },
  });

  return (
    <section className="page-stack manual-editor-page">
      <PageHeader
        title="手动调整模式"
        description={job.data?.source_name || "独立剪辑窗口：预览、定位字幕，然后保存进入重渲染。"}
        actions={
          <div className="manual-editor-page-actions">
            <button
              type="button"
              className="button primary"
              disabled={!manualEditorActionsEnabled || !manualEditState?.canApply || applyManualEditor.isPending}
              onClick={handleApplyManualEdit}
            >
              {applyManualEditor.isPending ? renderSubmittingLabel : renderActionLabel}
            </button>
            <button
              type="button"
              className="button ghost"
              disabled={!manualEditorActionsEnabled || !manualEditState?.hasLocalEdits}
              onClick={handleDiscardManualEdit}
            >
              放弃本地改动
            </button>
            <Link className="button ghost" to="/jobs">
              返回任务列表
            </Link>
          </div>
        }
      />

      {notice ? <div className={noticeClass}>{notice.message}</div> : null}

      {!jobId ? (
        <section className="panel">
          <EmptyState message="缺少任务 ID，无法打开手动调整模式。" tone="error" />
        </section>
      ) : manualEditorReadiness.isLoading ? (
        <>
          <section className="panel manual-editor-shell-panel">
            <EmptyState message="正在检查手动调整准备状态…" />
          </section>
          <div className="manual-editor-readiness-floating">
            <ManualEditorReadinessPanel />
          </div>
        </>
      ) : manualEditorReadiness.isError ? (
        <section className="panel">
          <EmptyState
            message={`手动调整准备状态查询失败：${errorMessage(manualEditorReadiness.error)}`}
            tone="error"
          />
          <div className="toolbar top-gap">
            <Link className="button ghost" to="/jobs">
              返回任务列表
            </Link>
          </div>
        </section>
      ) : manualEditorReadiness.data && !manualEditorReadiness.data.can_open_editor ? (
        <>
          <section className="panel manual-editor-shell-panel">
            <EmptyState
              message={readinessEmptyStateMessage(manualEditorReadiness.data)}
              tone={manualEditorReadiness.data.status === "failed" ? "error" : undefined}
            />
            <div className="toolbar top-gap">
              {retryStartStep ? (
                <button
                  type="button"
                  className="button primary"
                  disabled={retryManualEditorPreparation.isPending}
                  onClick={() => retryManualEditorPreparation.mutate(retryStartStep)}
                >
                  {retryManualEditorPreparation.isPending ? "正在提交重试..." : `从${retryStartLabel}重试`}
                </button>
              ) : null}
              <button type="button" className="button ghost" onClick={() => void manualEditorReadiness.refetch()}>
                刷新状态
              </button>
              <Link className="button ghost" to="/jobs">
                返回任务列表
              </Link>
            </div>
          </section>
          <div className="manual-editor-readiness-floating">
            <ManualEditorReadinessPanel readiness={manualEditorReadiness.data} />
          </div>
        </>
      ) : manualEditor.isLoading ? (
        <section className="panel">
          <EmptyState message="正在加载手动调整工作区…" />
        </section>
      ) : manualEditor.isError ? (
        <section className="panel">
          <EmptyState
            message={`手动调整模式暂不可用：${errorMessage(manualEditor.error)}`}
            tone="error"
          />
          <div className="toolbar top-gap">
            <Link className="button ghost" to="/jobs">
              返回任务列表
            </Link>
          </div>
        </section>
      ) : manualEditor.data ? (
        <Suspense
          fallback={
            <section className="panel manual-editor-shell-panel">
              <EmptyState message="正在加载手动调整编辑器…" />
            </section>
          }
        >
          <JobManualEditSection
            job={job.data}
            session={manualEditor.data}
            previewAssets={manualEditorAssets.data}
            saving={applyManualEditor.isPending}
            autosaving={saveManualEditorDraft.isPending}
            autosavedAt={lastDraftSavedAt ?? manualEditor.data.draft_saved_at}
            detectingRotation={detectRotation.isPending}
            resetSignal={resetSignal}
            renderActionLabel={renderActionLabel}
            onStateChange={handleManualEditStateChange}
            onApply={handleApplyManualEditorPayload}
            onAutoSave={handleAutoSaveManualEditorDraft}
            onDetectRotation={handleDetectManualEditorRotation}
          />
        </Suspense>
      ) : (
        <section className="panel">
          <EmptyState message="没有可用的手动调整工作区。" />
        </section>
      )}
    </section>
  );
}
