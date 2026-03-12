import { fireEvent, render, screen } from "@testing-library/react";

import { TextField } from "./TextField";

describe("TextField", () => {
  it("renders label and forwards input changes", () => {
    const handleChange = vi.fn();

    render(<TextField label="输出目录" value="data/output" onChange={handleChange} />);

    expect(screen.getByText("输出目录")).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("data/output"), {
      target: { value: "data/rendered" },
    });

    expect(handleChange).toHaveBeenCalledTimes(1);
  });
});
