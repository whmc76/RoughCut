export type RootForm = {
  path: string;
  channel_profile: string;
  enabled: boolean;
  scan_mode: "fast" | "precise";
};

export const EMPTY_ROOT_FORM: RootForm = {
  path: "",
  channel_profile: "",
  enabled: true,
  scan_mode: "fast",
};
