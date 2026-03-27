import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { HealthDetail, ServiceStatus } from "../../types";
import { useControlWorkspace } from "./useControlWorkspace";

const mockApi = vi.hoisted(() => ({
  getControlStatus: vi.fn(),
  getHealthDetail: vi.fn(),
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

describe("useControlWorkspace", () => {
  beforeEach(() => {
    mockApi.getControlStatus.mockResolvedValue(SAMPLE_SERVICES);
    mockApi.getHealthDetail.mockResolvedValue(SAMPLE_HEALTH_DETAIL);
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
});
