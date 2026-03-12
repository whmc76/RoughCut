import type { GlossaryTerm } from "../types";
import { request } from "./core";

export const glossaryApi = {
  listGlossary: () => request<GlossaryTerm[]>("/glossary"),
  createGlossary: (body: { wrong_forms: string[]; correct_form: string; category?: string; context_hint?: string }) =>
    request<GlossaryTerm>("/glossary", { method: "POST", body: JSON.stringify(body) }),
  updateGlossary: (termId: string, body: Partial<Omit<GlossaryTerm, "id" | "created_at">>) =>
    request<GlossaryTerm>(`/glossary/${termId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteGlossary: (termId: string) => request<void>(`/glossary/${termId}`, { method: "DELETE" }),
};
