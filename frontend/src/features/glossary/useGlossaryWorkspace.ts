import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { BuiltinGlossaryPack, BuiltinGlossaryTerm, GlossaryTerm } from "../../types";
import { EMPTY_TERM_FORM, type TermForm } from "./constants";

function normalizeTermForm(form: TermForm) {
  return {
    wrong_forms: form.wrong_forms.split(",").map((item) => item.trim()).filter(Boolean),
    correct_form: form.correct_form.trim(),
    scope_type: form.scope_type || "global",
    scope_value: form.scope_value.trim(),
    category: form.category || undefined,
    context_hint: form.context_hint || undefined,
  };
}

function serializeTermForm(form: TermForm): string {
  return JSON.stringify({
    wrong_forms: form.wrong_forms,
    correct_form: form.correct_form,
    scope_type: form.scope_type,
    scope_value: form.scope_value,
    category: form.category,
    context_hint: form.context_hint,
  });
}

function normalizeGlossaryKey(value: string): string {
  return value.trim().toLowerCase();
}

export function useGlossaryWorkspace() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<GlossaryTerm | null>(null);
  const [form, setForm] = useState<TermForm>(EMPTY_TERM_FORM);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [builtinFilter, setBuiltinFilter] = useState<string>("all");
  const [scopeFilter, setScopeFilter] = useState<string>("all");
  const [builtinImportMode, setBuiltinImportMode] = useState<"add_only" | "sync_aliases">("add_only");
  const [importingPackDomain, setImportingPackDomain] = useState<string | null>(null);
  const [importingTerms, setImportingTerms] = useState<string[]>([]);
  const lastPersistedRef = useRef<string>(serializeTermForm(EMPTY_TERM_FORM));
  const updateVersionRef = useRef(0);

  const glossary = useQuery({
    queryKey: ["glossary", scopeFilter],
    queryFn: () => {
      if (scopeFilter === "all") return api.listGlossary();
      if (scopeFilter === "global") return api.listGlossary({ scope_type: "global", scope_value: "" });
      if (scopeFilter.startsWith("domain:")) return api.listGlossary({ scope_type: "domain", scope_value: scopeFilter.slice("domain:".length) });
      if (scopeFilter.startsWith("channel_profile:")) return api.listGlossary({ scope_type: "channel_profile", scope_value: scopeFilter.slice("channel_profile:".length) });
      return api.listGlossary();
    },
  });
  const builtinPacks = useQuery({ queryKey: ["glossary", "builtin-packs"], queryFn: api.listBuiltinGlossaryPacks });

  const resetForm = () => {
    setEditing(null);
    setForm(EMPTY_TERM_FORM);
    setSaveState("idle");
    setSaveError(null);
    lastPersistedRef.current = serializeTermForm(EMPTY_TERM_FORM);
  };

  const createTerm = useMutation({
    mutationFn: () => api.createGlossary(normalizeTermForm(form)),
    onSuccess: async () => {
      resetForm();
      await queryClient.invalidateQueries({ queryKey: ["glossary"] });
    },
  });

  const updateTerm = useMutation({
    mutationFn: (payload: ReturnType<typeof normalizeTermForm>) => api.updateGlossary(editing!.id, payload),
  });

  const deleteTerm = useMutation({
    mutationFn: (termId: string) => api.deleteGlossary(termId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossary"] }),
  });

  const importBuiltinTerm = useMutation({
    mutationFn: (term: BuiltinGlossaryTerm) =>
      api.createGlossary({
        wrong_forms: term.wrong_forms,
        correct_form: term.correct_form,
        scope_type: "global",
        scope_value: "",
        category: term.category || undefined,
        context_hint: term.context_hint || undefined,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossary"] }),
  });

  const syncBuiltinTerm = useMutation({
    mutationFn: ({ termId, payload }: { termId: string; payload: Partial<Omit<GlossaryTerm, "id" | "created_at">> }) =>
      api.updateGlossary(termId, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossary"] }),
  });

  const submit = () => {
    if (editing) updateTerm.mutate(normalizeTermForm(form));
    else createTerm.mutate();
  };

  const startEdit = (term: GlossaryTerm) => {
    const nextForm = {
      wrong_forms: term.wrong_forms.join(", "),
      correct_form: term.correct_form,
      scope_type: term.scope_type || "global",
      scope_value: term.scope_value || "",
      category: term.category || "",
      context_hint: term.context_hint || "",
    };
    setEditing(term);
    setForm(nextForm);
    lastPersistedRef.current = serializeTermForm(nextForm);
    setSaveState("idle");
    setSaveError(null);
  };

  useEffect(() => {
    if (!editing) return;
    const signature = serializeTermForm(form);
    if (signature === lastPersistedRef.current) {
      return;
    }

    const requestVersion = updateVersionRef.current + 1;
    updateVersionRef.current = requestVersion;
    const timer = window.setTimeout(() => {
      setSaveState("saving");
      setSaveError(null);
      updateTerm.mutate(normalizeTermForm(form), {
        onSuccess: async (updatedTerm) => {
          if (requestVersion !== updateVersionRef.current) return;
          const nextForm = {
            wrong_forms: updatedTerm.wrong_forms.join(", "),
            correct_form: updatedTerm.correct_form,
            scope_type: updatedTerm.scope_type || "global",
            scope_value: updatedTerm.scope_value || "",
            category: updatedTerm.category || "",
            context_hint: updatedTerm.context_hint || "",
          };
          lastPersistedRef.current = serializeTermForm(nextForm);
          setEditing(updatedTerm);
          setForm(nextForm);
          queryClient.setQueryData(["glossary"], (current: GlossaryTerm[] | undefined) =>
            (current ?? []).map((term) => (term.id === updatedTerm.id ? updatedTerm : term)),
          );
          setSaveState("saved");
          setSaveError(null);
        },
        onError: (error) => {
          if (requestVersion !== updateVersionRef.current) return;
          setSaveState("error");
          setSaveError(error instanceof Error ? error.message : String(error));
        },
      });
    }, 500);

    return () => window.clearTimeout(timer);
  }, [editing, form, queryClient, updateTerm]);

  const glossaryByCorrectForm = new Map((glossary.data ?? []).map((item) => [normalizeGlossaryKey(item.correct_form), item]));
  const builtinPacksFiltered = (builtinPacks.data ?? []).filter((pack) => builtinFilter === "all" || pack.domain === builtinFilter);

  const hasBuiltinTermImported = (correctForm: string) => glossaryByCorrectForm.has(normalizeGlossaryKey(correctForm));

  const upsertBuiltinTerm = async (term: BuiltinGlossaryTerm) => {
    const existing = glossaryByCorrectForm.get(normalizeGlossaryKey(term.correct_form));
    if (!existing) {
      await importBuiltinTerm.mutateAsync(term);
      return;
    }
    if (builtinImportMode !== "sync_aliases") return;
    await syncBuiltinTerm.mutateAsync({
      termId: existing.id,
      payload: {
        wrong_forms: term.wrong_forms,
        category: term.category || undefined,
        context_hint: term.context_hint || undefined,
      },
    });
  };

  const importOneBuiltinTerm = async (term: BuiltinGlossaryTerm) => {
    const existing = glossaryByCorrectForm.get(normalizeGlossaryKey(term.correct_form));
    if (importingTerms.includes(term.correct_form)) return;
    if (existing && builtinImportMode === "add_only") return;
    setImportingTerms((current) => [...current, term.correct_form]);
    try {
      await upsertBuiltinTerm(term);
    } finally {
      setImportingTerms((current) => current.filter((item) => item !== term.correct_form));
    }
  };

  const importBuiltinPack = async (pack: BuiltinGlossaryPack) => {
    if (importingPackDomain === pack.domain) return;
    setImportingPackDomain(pack.domain);
    try {
      for (const term of pack.terms) {
        if (glossaryByCorrectForm.has(normalizeGlossaryKey(term.correct_form)) && builtinImportMode === "add_only") continue;
        await upsertBuiltinTerm(term);
      }
    } finally {
      setImportingPackDomain(null);
    }
  };

  return {
    editing,
    form,
    setForm,
    glossary,
    builtinPacks,
    builtinPacksFiltered,
    builtinFilter,
    setBuiltinFilter,
    scopeFilter,
    setScopeFilter,
    builtinImportMode,
    setBuiltinImportMode,
    resetForm,
    createTerm,
    updateTerm,
    deleteTerm,
    importBuiltinTerm,
    importOneBuiltinTerm,
    importBuiltinPack,
    importingPackDomain,
    importingTerms,
    hasBuiltinTermImported,
    submit,
    startEdit,
    saveState,
    saveError,
  };
}
