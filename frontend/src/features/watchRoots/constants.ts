export type RootForm = {
  path: string;
  config_profile_id: string;
  workflow_template: string;
  output_dir: string;
  enabled: boolean;
  recursive: boolean;
  scan_mode: "fast" | "precise";
  ingest_mode: "task_only" | "full_auto";
  job_flow_mode: "auto" | "smart_assist";
  edit_mode: "auto" | "talking_head" | "tutorial" | "vlog" | "highlight" | "multi_material";
  automation_level: "conservative" | "standard" | "richer";
  material_usage: "main_only" | "all_uploaded" | "selected_uploaded";
};

export const EMPTY_ROOT_FORM: RootForm = {
  path: "",
  config_profile_id: "",
  workflow_template: "",
  output_dir: "",
  enabled: true,
  recursive: true,
  scan_mode: "fast",
  ingest_mode: "full_auto",
  job_flow_mode: "auto",
  edit_mode: "auto",
  automation_level: "standard",
  material_usage: "all_uploaded",
};
