import { act, waitFor } from "@testing-library/react";

import { renderHookWithQueryClient } from "../../test/renderWithQueryClient";
import type { GlossaryTerm } from "../../types";
import { useGlossaryWorkspace } from "./useGlossaryWorkspace";

const mockApi = vi.hoisted(() => ({
  listGlossary: vi.fn(),
  listBuiltinGlossaryPacks: vi.fn(),
  createGlossary: vi.fn(),
  updateGlossary: vi.fn(),
  deleteGlossary: vi.fn(),
}));

vi.mock("../../api", () => ({
  api: mockApi,
}));

const SAMPLE_TERM: GlossaryTerm = {
  id: "term_1",
  scope_type: "global",
  scope_value: "",
  wrong_forms: ["GPT4", "gpt4"],
  correct_form: "GPT-4",
  category: "model",
  context_hint: "数码开箱",
  created_at: "2026-03-12T10:00:00Z",
};

describe("useGlossaryWorkspace", () => {
  beforeEach(() => {
    mockApi.listGlossary.mockResolvedValue([SAMPLE_TERM]);
    mockApi.listBuiltinGlossaryPacks.mockResolvedValue([]);
    mockApi.createGlossary.mockResolvedValue(SAMPLE_TERM);
    mockApi.updateGlossary.mockImplementation(async (termId: string, payload: Record<string, unknown>) => ({
      ...SAMPLE_TERM,
      id: termId,
      ...payload,
      wrong_forms: (payload.wrong_forms as string[]) ?? SAMPLE_TERM.wrong_forms,
    }));
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
      scope_type: "global",
      scope_value: "",
      category: "model",
      context_hint: "数码开箱",
    });

    act(() => {
      result.current.resetForm();
      result.current.setForm({
        wrong_forms: " ARC ,  leatherman arc ",
        correct_form: "Leatherman ARC",
        scope_type: "domain",
        scope_value: "gear",
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
        scope_type: "domain",
        scope_value: "gear",
        category: "model",
        context_hint: undefined,
      }),
    );
  });

  it("autosaves edits for the selected glossary term", async () => {
    const { result } = renderHookWithQueryClient(() => useGlossaryWorkspace());

    await waitFor(() => expect(result.current.glossary.data).toEqual([SAMPLE_TERM]));

    act(() => {
      result.current.startEdit(SAMPLE_TERM);
      result.current.setForm({
        wrong_forms: "GPT4, gpt4, gpt-4",
        correct_form: "GPT-4",
        scope_type: "global",
        scope_value: "",
        category: "model",
        context_hint: "数码开箱",
      });
    });

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    await waitFor(() =>
      expect(mockApi.updateGlossary).toHaveBeenCalledWith("term_1", {
        wrong_forms: ["GPT4", "gpt4", "gpt-4"],
        correct_form: "GPT-4",
        scope_type: "global",
        scope_value: "",
        category: "model",
        context_hint: "数码开箱",
      }),
    );
    await waitFor(() => expect(result.current.saveState).toBe("saved"));
  });

  it("imports builtin glossary terms into custom glossary", async () => {
    mockApi.listBuiltinGlossaryPacks.mockResolvedValue([
      {
        domain: "gear",
        presets: ["edc_tactical"],
        term_count: 1,
        terms: [
          {
            correct_form: "BRX",
            wrong_forms: ["比阿尔艾克斯", "B R X"],
            category: "term",
            context_hint: "圈内缩写",
          },
        ],
      },
    ]);

    const { result } = renderHookWithQueryClient(() => useGlossaryWorkspace());

    await waitFor(() => expect(result.current.builtinPacks.data?.[0].domain).toBe("gear"));

    await act(async () => {
      await result.current.importOneBuiltinTerm({
        correct_form: "BRX",
        wrong_forms: ["比阿尔艾克斯", "B R X"],
        category: "term",
        context_hint: "圈内缩写",
      });
    });

    await waitFor(() =>
      expect(mockApi.createGlossary).toHaveBeenCalledWith({
        wrong_forms: ["比阿尔艾克斯", "B R X"],
        correct_form: "BRX",
        scope_type: "global",
        scope_value: "",
        category: "term",
        context_hint: "圈内缩写",
      }),
    );
  });

  it("syncs aliases into existing glossary terms when sync mode is enabled", async () => {
    const existingTerm: GlossaryTerm = {
      id: "term_brx",
      scope_type: "global",
      scope_value: "",
      wrong_forms: ["老错写"],
      correct_form: "BRX",
      category: "term",
      context_hint: "旧提示",
      created_at: "2026-03-12T10:00:00Z",
    };
    mockApi.listGlossary.mockResolvedValue([existingTerm]);

    const { result } = renderHookWithQueryClient(() => useGlossaryWorkspace());

    await waitFor(() => expect(result.current.glossary.data?.[0].correct_form).toBe("BRX"));

    act(() => {
      result.current.setBuiltinImportMode("sync_aliases");
    });

    await act(async () => {
      await result.current.importOneBuiltinTerm({
        correct_form: "BRX",
        wrong_forms: ["比阿尔艾克斯", "B R X"],
        category: "term",
        context_hint: "圈内缩写",
      });
    });

    await waitFor(() =>
      expect(mockApi.updateGlossary).toHaveBeenCalledWith("term_brx", {
        wrong_forms: ["比阿尔艾克斯", "B R X"],
        category: "term",
        context_hint: "圈内缩写",
      }),
    );
  });
});
