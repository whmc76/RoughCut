export type TermForm = {
  wrong_forms: string;
  correct_form: string;
  category: string;
  context_hint: string;
};

export const EMPTY_TERM_FORM: TermForm = {
  wrong_forms: "",
  correct_form: "",
  category: "",
  context_hint: "",
};
