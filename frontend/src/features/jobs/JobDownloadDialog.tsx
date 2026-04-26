import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../../api";
import type { Job } from "../../types";
import { EmptyState } from "../../components/ui/EmptyState";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type JobDownloadDialogProps = {
  open: boolean;
  job: Job | null;
  onClose: () => void;
};

function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function triggerBrowserDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function JobDownloadDialog({ open, job, onClose }: JobDownloadDialogProps) {
  const { t } = useI18n();
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const query = useQuery({
    queryKey: ["job-download-files", job?.id],
    queryFn: () => api.getJobDownloadFiles(job!.id),
    enabled: Boolean(open && job?.id),
  });
  const files = query.data?.files ?? [];
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const selectedCount = files.filter((file) => selectedSet.has(file.id)).length;
  const selectedBytes = files
    .filter((file) => selectedSet.has(file.id))
    .reduce((sum, file) => sum + file.size_bytes, 0);

  useEffect(() => {
    if (!open) {
      setSelectedIds([]);
      return;
    }
    if (files.length) {
      const recommended = files.filter((file) => file.recommended).map((file) => file.id);
      setSelectedIds(recommended.length ? recommended : files.map((file) => file.id));
    }
  }, [files, open]);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [open, onClose]);

  const download = useMutation({
    mutationFn: () => api.downloadJobFiles(job!.id, selectedIds),
    onSuccess: ({ blob, filename }) => {
      triggerBrowserDownload(blob, filename);
      onClose();
    },
  });

  if (!open || !job) return null;

  const toggleFile = (fileId: string) => {
    setSelectedIds((current) =>
      current.includes(fileId) ? current.filter((item) => item !== fileId) : [...current, fileId],
    );
  };

  return (
    <div className="floating-modal-backdrop job-download-dialog-backdrop" onClick={onClose} role="presentation">
      <div
        className="floating-modal-shell job-download-dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-label={t("jobs.actions.download")}
        onClick={(event) => event.stopPropagation()}
      >
        <button className="button ghost floating-modal-close" type="button" onClick={onClose} aria-label={t("jobs.modal.closeAria")}>
          {t("jobs.modal.close")}
        </button>
        <section className="job-download-dialog-content">
          <PanelHeader
            title="选择下载文件"
            description={job.source_name}
            actions={
              <div className="jobs-stage-meta">
                <span>已选择</span>
                <strong>{selectedCount} 个文件</strong>
              </div>
            }
          />

          {query.isLoading ? <EmptyState message="正在读取可下载文件..." /> : null}
          {query.isError ? <EmptyState message={(query.error as Error).message} tone="error" /> : null}
          {!query.isLoading && !query.isError && !files.length ? (
            <EmptyState message="当前任务没有可下载文件。" />
          ) : null}

          {files.length ? (
            <div className="job-download-file-list">
              {files.map((file) => (
                <label key={file.id} className="job-download-file-item">
                  <input
                    type="checkbox"
                    checked={selectedSet.has(file.id)}
                    onChange={() => toggleFile(file.id)}
                  />
                  <span className="job-download-file-copy">
                    <strong>{file.label}</strong>
                    <span>{file.filename}</span>
                  </span>
                  <span className="job-download-file-meta">{formatBytes(file.size_bytes)}</span>
                </label>
              ))}
            </div>
          ) : null}

          {download.isError ? <div className="notice notice-error">{(download.error as Error).message}</div> : null}

          <div className="job-download-dialog-actions">
            <button
              type="button"
              className="button ghost button-sm"
              onClick={() => setSelectedIds(files.map((file) => file.id))}
              disabled={!files.length || selectedCount === files.length || download.isPending}
            >
              全选
            </button>
            <button
              type="button"
              className="button ghost button-sm"
              onClick={() => setSelectedIds([])}
              disabled={!selectedCount || download.isPending}
            >
              清空
            </button>
            <div className="job-download-dialog-spacer" />
            <span className="muted">{formatBytes(selectedBytes)}</span>
            <button
              type="button"
              className="button primary"
              disabled={!selectedCount || download.isPending}
              onClick={() => download.mutate()}
            >
              {download.isPending ? "正在打包..." : "确认下载 ZIP"}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
