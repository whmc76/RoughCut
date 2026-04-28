import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { JobManualEditSection, type JobManualEditSectionState } from "../features/jobs/JobManualEditSection";
import type { JobManualEditApplyPayload } from "../types";

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

export function JobManualEditorPage() {
  const { jobId = "" } = useParams();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [lastDraftSavedAt, setLastDraftSavedAt] = useState<string | null>(null);
  const [manualEditState, setManualEditState] = useState<JobManualEditSectionState | null>(null);
  const [resetSignal, setResetSignal] = useState(0);

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId),
    enabled: Boolean(jobId),
  });
  const manualEditor = useQuery({
    queryKey: ["job-manual-editor", jobId],
    queryFn: () => api.getJobManualEditor(jobId),
    enabled: Boolean(jobId),
    staleTime: 15_000,
    retry: 1,
  });
  const manualEditorAssets = useQuery({
    queryKey: ["job-manual-editor-assets", jobId],
    queryFn: () => api.warmJobManualEditorAssets(jobId),
    enabled: Boolean(jobId && manualEditor.data?.source_url),
    refetchInterval: (query) => (query.state.data?.ready ? false : 2_500),
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
        queryClient.invalidateQueries({ queryKey: ["job-manual-editor", jobId] }),
        queryClient.invalidateQueries({ queryKey: ["job-manual-editor-assets", jobId] }),
      ]);
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
        `片段数：${manualEditState.baseSegmentCount} -> ${manualEditState.effectiveSegmentCount}`,
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
  const manualEditorActionsEnabled = Boolean(manualEditor.data);

  return (
    <section className="page-stack manual-editor-page">
      <PageHeader
        title="手动调整模式"
        description={job.data?.source_name || "独立剪辑窗口：预览、调整片段和字幕，然后保存进入重渲染。"}
        actions={
          <div className="manual-editor-page-actions">
            <button
              type="button"
              className="button primary"
              disabled={!manualEditState?.canApply || applyManualEditor.isPending}
              onClick={handleApplyManualEdit}
            >
              {applyManualEditor.isPending ? "重渲染提交中..." : "用当前自动保存版本重新渲染"}
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
        <JobManualEditSection
          job={job.data}
          session={manualEditor.data}
          previewAssets={manualEditorAssets.data}
          saving={applyManualEditor.isPending}
          autosaving={saveManualEditorDraft.isPending}
          autosavedAt={lastDraftSavedAt ?? manualEditor.data.draft_saved_at}
          detectingRotation={detectRotation.isPending}
          resetSignal={resetSignal}
          onStateChange={handleManualEditStateChange}
          onApply={handleApplyManualEditorPayload}
          onAutoSave={handleAutoSaveManualEditorDraft}
          onDetectRotation={handleDetectManualEditorRotation}
        />
      ) : (
        <section className="panel">
          <EmptyState message="没有可用的手动调整工作区。" />
        </section>
      )}
    </section>
  );
}
