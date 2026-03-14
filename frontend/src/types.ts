export type JobStep = {
  id: string;
  step_name: string;
  status: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
};

export type Job = {
  id: string;
  source_name: string;
  content_subject?: string | null;
  content_summary?: string | null;
  avatar_delivery_status?: string | null;
  avatar_delivery_summary?: string | null;
  status: string;
  language: string;
  channel_profile?: string | null;
  workflow_mode: string;
  enhancement_modes: string[];
  file_hash?: string | null;
  error_message?: string | null;
  progress_percent?: number;
  created_at: string;
  updated_at: string;
  steps: JobStep[];
};

export type JobTimeline = {
  id: string;
  version: number;
  data: Record<string, unknown>;
};

export type JobActivity = {
  job_id: string;
  status: string;
  current_step: {
    step_name: string;
    label: string;
    status: string;
    detail?: string | null;
    progress?: number | null;
    updated_at?: string | null;
  } | null;
  render: {
    status: string;
    progress: number;
    output_path?: string | null;
    updated_at?: string | null;
  } | null;
  decisions: Array<{
    kind: string;
    title: string;
    status: string;
    summary: string;
    detail?: string | null;
    updated_at?: string | null;
  }>;
  events: Array<{
    timestamp: string;
    type: string;
    status: string;
    title: string;
    detail?: string | null;
  }>;
};

export type GlossaryTerm = {
  id: string;
  scope_type: string;
  scope_value: string;
  wrong_forms: string[];
  correct_form: string;
  category?: string | null;
  context_hint?: string | null;
  created_at: string;
};

export type BuiltinGlossaryTerm = {
  correct_form: string;
  wrong_forms: string[];
  category?: string | null;
  context_hint?: string | null;
};

export type BuiltinGlossaryPack = {
  domain: string;
  presets: string[];
  term_count: number;
  terms: BuiltinGlossaryTerm[];
};

export type WatchRoot = {
  id: string;
  path: string;
  channel_profile?: string | null;
  enabled: boolean;
  scan_mode: "fast" | "precise";
  created_at: string;
};

export type WatchInventoryItem = {
  path: string;
  relative_path: string;
  source_name: string;
  stem: string;
  size_bytes: number;
  modified_at: string;
  duration_sec?: number | null;
  width?: number | null;
  height?: number | null;
  fps?: number | null;
  status: string;
  dedupe_reason?: string | null;
  matched_job_id?: string | null;
  matched_output_path?: string | null;
};

export type WatchInventoryStatus = {
  root_path: string;
  scan_mode: "fast" | "precise";
  status: string;
  started_at: string;
  updated_at: string;
  finished_at?: string | null;
  total_files: number;
  processed_files: number;
  pending_count: number;
  deduped_count: number;
  current_file?: string | null;
  current_phase?: string | null;
  current_file_size_bytes?: number | null;
  current_file_processed_bytes?: number | null;
  error?: string | null;
  inventory: {
    pending: WatchInventoryItem[];
    deduped: WatchInventoryItem[];
  };
};

export type WatchInventorySmartMergeGroup = {
  relative_paths: string[];
  score: number;
  reasons: string[];
};

export type WatchInventorySmartMerge = {
  source_count: number;
  groups: WatchInventorySmartMergeGroup[];
};

export type PackagingAsset = {
  id: string;
  asset_type: string;
  original_name: string;
  stored_name: string;
  path: string;
  size_bytes: number;
  content_type: string;
  watermark_preprocessed?: boolean | null;
  created_at: string;
};

export type PackagingConfig = {
  intro_asset_id?: string | null;
  outro_asset_id?: string | null;
  insert_asset_id?: string | null;
  insert_asset_ids: string[];
  insert_selection_mode: string;
  insert_position_mode: string;
  watermark_asset_id?: string | null;
  music_asset_ids: string[];
  music_selection_mode: string;
  music_loop_mode: string;
  subtitle_style: string;
  subtitle_motion_style: string;
  smart_effect_style: string;
  cover_style: string;
  title_style: string;
  copy_style: string;
  music_volume: number;
  watermark_position: string;
  watermark_opacity: number;
  watermark_scale: number;
  avatar_overlay_position: string;
  avatar_overlay_scale: number;
  avatar_overlay_corner_radius: number;
  avatar_overlay_border_width: number;
  avatar_overlay_border_color: string;
  export_resolution_mode?: string;
  export_resolution_preset?: string;
  enabled: boolean;
};

export type PackagingLibrary = {
  assets: Record<string, PackagingAsset[]>;
  config: PackagingConfig;
};

export type AvatarMaterialRule = {
  severity: string;
  title: string;
  detail: string;
};

export type AvatarMaterialSection = {
  title: string;
  rules: AvatarMaterialRule[];
};

export type AvatarMaterialFile = {
  id: string;
  original_name: string;
  stored_name: string;
  kind: string;
  role: string;
  role_label: string;
  pipeline_target: string;
  content_type: string;
  size_bytes: number;
  path: string;
  created_at: string;
  probe?: Record<string, unknown> | null;
  artifacts?: Record<string, unknown> | null;
  checks: Array<{ level: string; message: string }>;
};

export type AvatarMaterialPreviewRun = {
  id: string;
  status: string;
  script: string;
  task_code?: string | null;
  source_voice_file_id?: string | null;
  source_video_file_id?: string | null;
  output_path?: string | null;
  output_size_bytes?: number | null;
  duration_sec?: number | null;
  width?: number | null;
  height?: number | null;
  preview_mode?: string | null;
  fallback_reason?: string | null;
  error_message?: string | null;
  created_at: string;
};

export type AvatarMaterialProfile = {
  id: string;
  display_name: string;
  presenter_alias?: string | null;
  notes?: string | null;
  profile_dir: string;
  training_status: string;
  training_provider: string;
  training_api_available: boolean;
  next_action: string;
  capability_status: Record<string, string>;
  blocking_issues: string[];
  warnings: string[];
  created_at: string;
  files: AvatarMaterialFile[];
  preview_runs: AvatarMaterialPreviewRun[];
};

export type AvatarMaterialLibrary = {
  provider: string;
  training_api_available: boolean;
  preview_service_available?: boolean;
  intake_mode: string;
  summary: string;
  sections: AvatarMaterialSection[];
  profiles: AvatarMaterialProfile[];
};

export type ContentProfileReview = {
  job_id: string;
  status: string;
  review_step_status: string;
  workflow_mode: string;
  enhancement_modes: string[];
  draft: Record<string, any> | null;
  final: Record<string, any> | null;
  memory: Record<string, any> | null;
};

export type ContentProfileMemoryStats = {
  scope: string;
  channel_profile?: string | null;
  channel_profiles: string[];
  total_corrections: number;
  total_keywords: number;
  field_preferences: Record<string, Array<Record<string, any>>>;
  keyword_preferences: Array<Record<string, any>>;
  recent_corrections: Array<Record<string, any>>;
  cloud: {
    words?: Array<{ label: string; count: number; weight?: number }>;
  };
};

export type Report = {
  job_id: string;
  generated_at: string;
  total_subtitle_items: number;
  total_corrections: number;
  corrections_by_type: Record<string, number>;
  pending_count: number;
  accepted_count: number;
  rejected_count: number;
  items: Array<{
    index: number;
    start: number;
    end: number;
    text_raw: string;
    text_norm?: string | null;
    text_final?: string | null;
    corrections: Array<{
      id: string;
      original: string;
      suggested: string;
      type: string;
      confidence: number;
      source?: string | null;
      decision?: string | null;
      override?: string | null;
    }>;
  }>;
};

export type SelectOption = {
  value: string;
  label: string;
};

export type CreativeModeDefinition = {
  key: string;
  kind: "workflow" | "enhancement";
  status: string;
  title: string;
  tagline: string;
  summary: string;
  suitable_for: string[];
  pipeline_outline: string[];
  providers?: string[];
  delivery_scope?: string;
  default_delivery?: string;
};

export type Config = {
  transcription_provider: string;
  transcription_model: string;
  llm_mode: string;
  reasoning_provider: string;
  reasoning_model: string;
  local_reasoning_model: string;
  local_vision_model: string;
  multimodal_fallback_provider: string;
  multimodal_fallback_model: string;
  search_provider: string;
  search_fallback_provider: string;
  model_search_helper: string;
  openai_base_url: string;
  openai_auth_mode: string;
  openai_api_key_helper: string;
  avatar_provider: string;
  avatar_api_base_url: string;
  avatar_training_api_base_url: string;
  avatar_api_key_set: boolean;
  avatar_presenter_id: string;
  avatar_layout_template: string;
  avatar_safe_margin: number;
  avatar_overlay_scale: number;
  anthropic_base_url: string;
  anthropic_auth_mode: string;
  anthropic_api_key_helper: string;
  minimax_base_url: string;
  minimax_api_host: string;
  voice_provider: string;
  voice_clone_api_base_url: string;
  voice_clone_api_key_set: boolean;
  voice_clone_voice_id: string;
  director_rewrite_strength: number;
  ollama_api_key_set: boolean;
  openai_api_key_set: boolean;
  anthropic_api_key_set: boolean;
  minimax_api_key_set: boolean;
  minimax_coding_plan_api_key_set: boolean;
  ollama_base_url: string;
  max_upload_size_mb: number;
  max_video_duration_sec: number;
  ffmpeg_timeout_sec: number;
  allowed_extensions: string[];
  output_dir: string;
  default_job_workflow_mode: string;
  default_job_enhancement_modes: string[];
  fact_check_enabled: boolean;
  auto_confirm_content_profile: boolean;
  content_profile_review_threshold: number;
  auto_accept_glossary_corrections: boolean;
  glossary_correction_review_threshold: number;
  auto_select_cover_variant: boolean;
  cover_selection_review_gap: number;
  packaging_selection_review_gap: number;
  packaging_selection_min_score: number;
  overrides: Record<string, unknown>;
};

export type ConfigOptions = {
  job_languages: SelectOption[];
  channel_profiles: SelectOption[];
  workflow_modes: SelectOption[];
  enhancement_modes: SelectOption[];
  avatar_providers: SelectOption[];
  voice_providers: SelectOption[];
  creative_mode_catalog: {
    workflow_modes: CreativeModeDefinition[];
    enhancement_modes: CreativeModeDefinition[];
  };
  transcription_models: Record<string, string[]>;
  multimodal_fallback_providers: SelectOption[];
  search_providers: SelectOption[];
  search_fallback_providers: SelectOption[];
};

export type ServiceStatus = {
  checked_at: string;
  services: Record<string, boolean>;
};
