import type { HealthDetail, ReviewNotificationSnapshot, ServiceStatus } from "../types";
import { request } from "./core";

export const controlApi = {
  getControlStatus: () => request<ServiceStatus>("/control/status"),
  getHealthDetail: () => request<HealthDetail>("/health/detail"),
  getReviewNotifications: (filters?: { statuses?: string[]; jobId?: string; kind?: string; limit?: number }) => {
    const params = new URLSearchParams();
    for (const status of filters?.statuses ?? []) {
      if (status) {
        params.append("status", status);
      }
    }
    if (filters?.jobId) {
      params.set("job_id", filters.jobId);
    }
    if (filters?.kind) {
      params.set("kind", filters.kind);
    }
    if (filters?.limit != null) {
      params.set("limit", String(filters.limit));
    }
    const query = params.toString();
    return request<ReviewNotificationSnapshot>(`/control/review-notifications${query ? `?${query}` : ""}`);
  },
  requeueReviewNotification: (notificationId: string) =>
    request<{ status: string; notification: { notification_id: string } }>("/control/review-notifications/requeue", {
      method: "POST",
      body: JSON.stringify({ notification_id: notificationId }),
    }),
  requeueReviewNotifications: (notificationIds: string[]) =>
    request<{ status: string; count: number; notification_ids: string[] }>("/control/review-notifications/requeue-batch", {
      method: "POST",
      body: JSON.stringify({ notification_ids: notificationIds }),
    }),
  dropReviewNotification: (notificationId: string) =>
    request<{ status: string; notification_id: string }>("/control/review-notifications/drop", {
      method: "POST",
      body: JSON.stringify({ notification_id: notificationId }),
    }),
  dropReviewNotifications: (notificationIds: string[]) =>
    request<{ status: string; count: number; notification_ids: string[] }>("/control/review-notifications/drop-batch", {
      method: "POST",
      body: JSON.stringify({ notification_ids: notificationIds }),
    }),
  stopServices: (stopDocker: boolean) =>
    request<{ status: string; message: string }>("/control/stop", { method: "POST", body: JSON.stringify({ stop_docker: stopDocker }) }),
};
