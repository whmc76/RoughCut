import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { ServiceStatus } from "../../types";
import { useControlWorkspace } from "./useControlWorkspace";

const mockApi = vi.hoisted(() => ({
  getControlStatus: vi.fn(),
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

describe("useControlWorkspace", () => {
  beforeEach(() => {
    mockApi.getControlStatus.mockResolvedValue(SAMPLE_SERVICES);
    mockApi.stopServices.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("tracks docker stop preference and passes it into stop mutation", async () => {
    const { result } = renderHookWithQueryClient(() => useControlWorkspace());

    await waitFor(() => expect(result.current.status.data).toEqual(SAMPLE_SERVICES));

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
