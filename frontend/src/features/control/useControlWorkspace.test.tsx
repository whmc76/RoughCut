import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { HealthDetail, ReviewNotificationSnapshot, ServiceStatus } from "../../types";
import { useControlWorkspace } from "./useControlWorkspace";

const mockApi = vi.hoisted(() => ({
  getControlStatus: vi.fn(),
  getHealthDetail: vi.fn(),
  getReviewNotifications: vi.fn(),
  requeueReviewNotification: vi.fn(),
  requeueReviewNotifications: vi.fn(),
  dropReviewNotification: vi.fn(),
  dropReviewNotifications: vi.fn(),
  stopServices: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_SERVICES: ServiceStatus = {
  checked_at: "2026-03-12T10:00:00Z",
  services: {
    api: true,
    watcher: true,
    worker: false,
  },
};

const SAMPLE_HEALTH_DETAIL: HealthDetail = {
  checked_at: "2026-03-12T10:00:05Z",
  status: "ok",
  readiness: {
    status: "ready",
    checks: {
      database: { status: "ok", detail: "ok" },
    },
  },
  orchestrator_lock: {
    status: "held",
    leader_active: true,
    detail: "active leader",
  },
  managed_services: [{ name: "heygem", url: "http://127.0.0.1:49202", status: "ok", enabled: true }],
  watch_automation: {
    roots_total: 2,
    running_scans: 1,
    cached_pending_total: 3,
    auto_enqueue_enabled: true,
    auto_merge_enabled: true,
    active_jobs: 1,
    running_gpu_steps: 0,
    idle_slots: 1,
  },
};

const SAMPLE_REVIEW_NOTIFICATIONS: ReviewNotificationSnapshot = {
  state_dir: "F:/roughcut_outputs/telegram-agent",
  store_file: "F:/roughcut_outputs/telegram-agent/review_notifications.json",
  summary: {
    total: 1,
    pending: 1,
    due_now: 1,
    failed: 0,
    delivered: 0,
  },
  items: [
    {
      notification_id: "n-1",
      kind: "content_profile",
      job_id: "job-1",
      status: "pending",
      attempt_count: 1,
      next_attempt_at: "2026-04-17T00:00:00+00:00",
      last_error: "",
      force_full_review: false,
      updated_at: "2026-04-17T00:00:00+00:00",
    },
  ],
};

describe("useControlWorkspace", () => {
  beforeEach(() => {
    mockApi.getControlStatus.mockResolvedValue(SAMPLE_SERVICES);
    mockApi.getHealthDetail.mockResolvedValue(SAMPLE_HEALTH_DETAIL);
    mockApi.getReviewNotifications.mockResolvedValue(SAMPLE_REVIEW_NOTIFICATIONS);
    mockApi.requeueReviewNotification.mockResolvedValue({ status: "requeued" });
    mockApi.requeueReviewNotifications.mockResolvedValue({ status: "requeued", count: 1, notification_ids: ["n-1"] });
    mockApi.dropReviewNotification.mockResolvedValue({ status: "dropped" });
    mockApi.dropReviewNotifications.mockResolvedValue({ status: "dropped", count: 1, notification_ids: ["n-1"] });
    mockApi.stopServices.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("tracks docker stop preference and passes it into stop mutation", async () => {
    const { result } = renderHookWithQueryClient(() => useControlWorkspace());

    await waitFor(() => expect(result.current.status.data).toEqual(SAMPLE_SERVICES));
    await waitFor(() => expect(result.current.healthDetail.data).toEqual(SAMPLE_HEALTH_DETAIL));

    act(() => {
      result.current.setStopDocker(true);
    });

    expect(result.current.stopDocker).toBe(true);

    await act(async () => {
      await result.current.stop.mutateAsync();
    });

    expect(mockApi.stopServices).toHaveBeenCalledWith(true);
  });

  it("loads review notifications with filters and refreshes status after queue mutations", async () => {
    const { result } = renderHookWithQueryClient(() => useControlWorkspace());

    await waitFor(() => expect(result.current.reviewNotifications.data).toEqual(SAMPLE_REVIEW_NOTIFICATIONS));
    expect(mockApi.getReviewNotifications).toHaveBeenCalledWith({ jobId: undefined, limit: 50 });

    act(() => {
      result.current.setReviewNotificationJobIdFilter("job-1");
    });

    await waitFor(() => expect(mockApi.getReviewNotifications).toHaveBeenCalledWith({ jobId: "job-1", limit: 50 }));

    const statusCallsBeforeMutation = mockApi.getControlStatus.mock.calls.length;
    const reviewCallsBeforeMutation = mockApi.getReviewNotifications.mock.calls.length;

    await act(async () => {
      await result.current.requeueReviewNotifications.mutateAsync(["n-1"]);
    });

    expect(mockApi.requeueReviewNotifications).toHaveBeenCalledWith(["n-1"]);
    await waitFor(() => expect(mockApi.getControlStatus.mock.calls.length).toBeGreaterThan(statusCallsBeforeMutation));
    await waitFor(() => expect(mockApi.getReviewNotifications.mock.calls.length).toBeGreaterThan(reviewCallsBeforeMutation));
  });
});
