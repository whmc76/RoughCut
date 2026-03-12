import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { GlossaryTerm } from "../../types";
import { useGlossaryWorkspace } from "./useGlossaryWorkspace";

const mockApi = vi.hoisted(() => ({
  listGlossary: vi.fn(),
  createGlossary: vi.fn(),
  updateGlossary: vi.fn(),
  deleteGlossary: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_TERM: GlossaryTerm = {
  id: "term_1",
  wrong_forms: ["GPT4", "gpt4"],
  correct_form: "GPT-4",
  category: "model",
  context_hint: "数码开箱",
  created_at: "2026-03-12T10:00:00Z",
};

describe("useGlossaryWorkspace", () => {
  beforeEach(() => {
    mockApi.listGlossary.mockResolvedValue([SAMPLE_TERM]);
    mockApi.createGlossary.mockResolvedValue(SAMPLE_TERM);
    mockApi.updateGlossary.mockResolvedValue(SAMPLE_TERM);
    mockApi.deleteGlossary.mockResolvedValue({});
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("maps edit state into form and normalizes payload on create", async () => {
    const { result } = renderHookWithQueryClient(() => useGlossaryWorkspace());

    await waitFor(() => expect(result.current.glossary.data).toEqual([SAMPLE_TERM]));

    act(() => {
      result.current.startEdit(SAMPLE_TERM);
    });

    expect(result.current.form).toEqual({
      wrong_forms: "GPT4, gpt4",
      correct_form: "GPT-4",
      category: "model",
      context_hint: "数码开箱",
    });

    act(() => {
      result.current.resetForm();
      result.current.setForm({
        wrong_forms: " ARC ,  leatherman arc ",
        correct_form: "Leatherman ARC",
        category: "model",
        context_hint: "",
      });
    });

    await act(async () => {
      result.current.submit();
    });

    await waitFor(() =>
      expect(mockApi.createGlossary).toHaveBeenCalledWith({
        wrong_forms: ["ARC", "leatherman arc"],
        correct_form: "Leatherman ARC",
        category: "model",
        context_hint: undefined,
      }),
    );
  });
});
