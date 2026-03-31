export type RootForm = {
  path: string;
  workflow_template: string;
  enabled: boolean;
  scan_mode: "fast" | "precise";
};

export const EMPTY_ROOT_FORM: RootForm = {
  path: "",
  workflow_template: "",
  enabled: true,
  scan_mode: "fast",
};
