export type RootForm = {
  path: string;
  config_profile_id: string;
  workflow_template: string;
  output_dir: string;
  enabled: boolean;
  scan_mode: "fast" | "precise";
};

export const EMPTY_ROOT_FORM: RootForm = {
  path: "",
  config_profile_id: "",
  workflow_template: "",
  output_dir: "",
  enabled: true,
  scan_mode: "fast",
};
