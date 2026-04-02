import { render } from "@testing-library/react";
import { act } from "react";

import { useFrontendBuildRefresh } from "./useFrontendBuildRefresh";

function Harness({
  intervalMs = 1_000,
  onUpdate,
}: {
  intervalMs?: number;
  onUpdate: () => void;
}) {
  useFrontendBuildRefresh({ intervalMs, onUpdate });
  return null;
}

describe("useFrontendBuildRefresh", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", fetchMock);
    document.head.innerHTML = '<script type="module" src="/assets/index-old.js"></script>';
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
    document.head.innerHTML = "";
  });

  it("triggers update when a later check finds a different entry bundle", async () => {
    const onUpdate = vi.fn();
    fetchMock
      .mockResolvedValueOnce(new Response('<script type="module" src="/assets/index-old.js"></script>'))
      .mockResolvedValueOnce(new Response('<script type="module" src="/assets/index-new.js"></script>'));

    render(<Harness intervalMs={1_000} onUpdate={onUpdate} />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(onUpdate).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1_000);
      await Promise.resolve();
    });

    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it("does not trigger update when the entry bundle stays the same", async () => {
    const onUpdate = vi.fn();
    fetchMock.mockResolvedValue(new Response('<script type="module" src="/assets/index-old.js"></script>'));

    render(<Harness intervalMs={1_000} onUpdate={onUpdate} />);

    await act(async () => {
      vi.advanceTimersByTime(3_000);
      await Promise.resolve();
    });

    expect(onUpdate).not.toHaveBeenCalled();
  });
});
