export type TermForm = {
  wrong_forms: string;
  correct_form: string;
  scope_type: string;
  scope_value: string;
  category: string;
  context_hint: string;
};

export const EMPTY_TERM_FORM: TermForm = {
  wrong_forms: "",
  correct_form: "",
  scope_type: "global",
  scope_value: "",
  category: "",
  context_hint: "",
};
