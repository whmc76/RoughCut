import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { useEffect, useState } from "react";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { EmptyState } from "../components/ui/EmptyState";
import { JobManualEditSection } from "../features/jobs/JobManualEditSection";
import type { JobManualEditApplyPayload } from "../types";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || "未知错误");
}

export function JobManualEditorPage() {
  const { jobId = "" } = useParams();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState<{ tone: "success" | "error"; message: string } | null>(null);
  const [lastDraftSavedAt, setLastDraftSavedAt] = useState<string | null>(null);

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
      setNotice({ tone: "error", message: `自动保存失败：${errorMessage(error) || "请刷新后重试。"}` });
    },
  });

  const noticeClass = notice?.tone === "error" ? "notice notice-error top-gap" : "notice top-gap";

  return (
    <section className="page-stack manual-editor-page">
      <PageHeader
        title="手动调整模式"
        description={job.data?.source_name || "独立剪辑窗口：预览、调整片段和字幕，然后保存进入重渲染。"}
        actions={
          <Link className="button ghost" to="/jobs">
            返回任务列表
          </Link>
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
          onApply={(payload) => applyManualEditor.mutate(payload)}
          onAutoSave={(payload) => saveManualEditorDraft.mutate(payload)}
        />
      ) : (
        <section className="panel">
          <EmptyState message="没有可用的手动调整工作区。" />
        </section>
      )}
    </section>
  );
}
