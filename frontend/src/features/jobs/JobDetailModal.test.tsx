import { fireEvent, render, screen } from "@testing-library/react";

import { JobDetailModal } from "./JobDetailModal";

describe("JobDetailModal", () => {
  it("renders children only when open and closes on Escape or backdrop click", () => {
    const handleClose = vi.fn();
    const { rerender } = render(
      <JobDetailModal open={false} onClose={handleClose}>
        <div>任务详情内容</div>
      </JobDetailModal>,
    );

    expect(screen.queryByText("任务详情内容")).not.toBeInTheDocument();

    rerender(
      <JobDetailModal open title="fas_upgrade.mp4" onClose={handleClose}>
        <div>任务详情内容</div>
      </JobDetailModal>,
    );

    expect(screen.getByRole("dialog", { name: "fas_upgrade.mp4" })).toBeInTheDocument();
    expect(screen.getByText("任务详情内容")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(handleClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("presentation"));
    expect(handleClose).toHaveBeenCalledTimes(2);
  });
});
