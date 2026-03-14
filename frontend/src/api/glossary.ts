import type { BuiltinGlossaryPack, GlossaryTerm } from "../types";
import { request } from "./core";

export const glossaryApi = {
  listGlossary: (params?: { scope_type?: string; scope_value?: string }) => {
    const query = new URLSearchParams();
    if (params?.scope_type) query.set("scope_type", params.scope_type);
    if (params?.scope_value !== undefined) query.set("scope_value", params.scope_value);
    const suffix = query.toString();
    return request<GlossaryTerm[]>(`/glossary${suffix ? `?${suffix}` : ""}`);
  },
  listBuiltinGlossaryPacks: () => request<BuiltinGlossaryPack[]>("/glossary/builtin-packs"),
  createGlossary: (body: { wrong_forms: string[]; correct_form: string; scope_type?: string; scope_value?: string; category?: string; context_hint?: string }) =>
    request<GlossaryTerm>("/glossary", { method: "POST", body: JSON.stringify(body) }),
  updateGlossary: (termId: string, body: Partial<Omit<GlossaryTerm, "id" | "created_at">>) =>
    request<GlossaryTerm>(`/glossary/${termId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteGlossary: (termId: string) => request<void>(`/glossary/${termId}`, { method: "DELETE" }),
};
