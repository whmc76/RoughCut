import { getCurrentUiLocale } from "./i18n";

export function formatDate(value?: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString(getCurrentUiLocale(), {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const precision = index === 0 ? 0 : 1;
  return `${size.toFixed(precision)} ${units[index]}`;
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remain = Math.round(seconds % 60);
  return `${minutes}m ${remain}s`;
}

export function classNames(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function statusLabel(status: string): string {
  const locale = getCurrentUiLocale();
  const labels: Record<string, Record<string, string>> = {
    "zh-CN": {
      pending: "待处理",
      running: "进行中",
      done: "已完成",
      failed: "失败",
      cancelled: "已取消",
      skipped: "已跳过",
      processing: "处理中",
      needs_review: "待核对",
    },
    "en-US": {
      pending: "Pending",
      running: "Running",
      done: "Done",
      failed: "Failed",
      cancelled: "Cancelled",
      skipped: "Skipped",
      processing: "Processing",
      needs_review: "Needs Review",
    },
  };
  return labels[locale]?.[status] ?? labels["zh-CN"][status] ?? status;
}
