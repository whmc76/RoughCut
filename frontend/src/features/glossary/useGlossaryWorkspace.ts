import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { GlossaryTerm } from "../../types";
import { EMPTY_TERM_FORM, type TermForm } from "./constants";

export function useGlossaryWorkspace() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<GlossaryTerm | null>(null);
  const [form, setForm] = useState<TermForm>(EMPTY_TERM_FORM);

  const glossary = useQuery({ queryKey: ["glossary"], queryFn: api.listGlossary });

  const resetForm = () => {
    setEditing(null);
    setForm(EMPTY_TERM_FORM);
  };

  const createTerm = useMutation({
    mutationFn: () =>
      api.createGlossary({
        wrong_forms: form.wrong_forms.split(",").map((item) => item.trim()).filter(Boolean),
        correct_form: form.correct_form.trim(),
        category: form.category || undefined,
        context_hint: form.context_hint || undefined,
      }),
    onSuccess: async () => {
      resetForm();
      await queryClient.invalidateQueries({ queryKey: ["glossary"] });
    },
  });

  const updateTerm = useMutation({
    mutationFn: () =>
      api.updateGlossary(editing!.id, {
        wrong_forms: form.wrong_forms.split(",").map((item) => item.trim()).filter(Boolean),
        correct_form: form.correct_form.trim(),
        category: form.category || undefined,
        context_hint: form.context_hint || undefined,
      }),
    onSuccess: async () => {
      resetForm();
      await queryClient.invalidateQueries({ queryKey: ["glossary"] });
    },
  });

  const deleteTerm = useMutation({
    mutationFn: (termId: string) => api.deleteGlossary(termId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["glossary"] }),
  });

  const submit = () => {
    if (editing) updateTerm.mutate();
    else createTerm.mutate();
  };

  const startEdit = (term: GlossaryTerm) => {
    setEditing(term);
    setForm({
      wrong_forms: term.wrong_forms.join(", "),
      correct_form: term.correct_form,
      category: term.category || "",
      context_hint: term.context_hint || "",
    });
  };

  return {
    editing,
    form,
    setForm,
    glossary,
    resetForm,
    createTerm,
    updateTerm,
    deleteTerm,
    submit,
    startEdit,
  };
}
