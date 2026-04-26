export type JobStep = {
  id: string;
  step_name: string;
  status: string;
  attempt: number;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
};

export type JobActivityDecision = {
  kind: string;
  step_name?: string | null;
  title: string;
  status: string;
  summary: string;
  detail?: string | null;
  blocking?: boolean | null;
  review_route?: string | null;
  review_label?: string | null;
  recommended_action?: string | null;
  rerun_start_step?: string | null;
  rerun_steps?: string[];
  issue_codes?: string[];
  updated_at?: string | null;
};

export type JobActivityEvent = {
  timestamp: string;
  type: string;
  status: string;
  step_name?: string | null;
  title: string;
  detail?: string | null;
  [key: string]: unknown;
};

export type Job = {
  id: string;
  source_name: string;
  merged_source_names?: string[];
  video_description?: string | null;
  content_subject?: string | null;
  content_summary?: string | null;
  quality_score?: number | null;
  quality_grade?: string | null;
  quality_summary?: string | null;
  quality_issue_codes?: string[] | null;
  timeline_diagnostics?: {
    review_recommended?: boolean;
    review_reasons?: string[];
    high_risk_cut_count?: number;
    high_energy_keep_count?: number;
    protected_visual_cut_count?: number;
    high_protection_evidence_count?: number;
    llm_reviewed?: boolean;
    llm_candidate_count?: number;
    llm_restored_cut_count?: number;
    llm_provider?: string | null;
    llm_summary?: string | null;
  } | null;
  avatar_delivery_status?: string | null;
  avatar_delivery_summary?: string | null;
  publication_status?: string;
  publication_summary?: string | null;
  status: string;
  language: string;
  workflow_template?: string | null;
  workflow_mode: string;
  enhancement_modes: string[];
  auto_review_mode_enabled?: boolean;
  auto_review_status?: string | null;
  auto_review_summary?: string | null;
  auto_review_reasons?: string[];
  review_step?: "summary_review" | "final_review" | null;
  review_label?: string | null;
  review_detail?: string | null;
  awaiting_initialization?: boolean;
  output_dir?: string | null;
  file_hash?: string | null;
  error_message?: string | null;
  progress_percent?: number;
  created_at: string;
  updated_at: string;
  steps: JobStep[];
};

export type JobDownloadFile = {
  id: string;
  label: string;
  filename: string;
  kind: string;
  size_bytes: number;
  recommended: boolean;
};

export type JobDownloadFiles = {
  job_id: string;
  files: JobDownloadFile[];
};

export type JobTimeline = {
  id: string;
  version: number;
  data: Record<string, unknown>;
};

export type JobManualEditSegment = {
  start: number;
  end: number;
  duration_sec: number;
  source_index: number;
};

export type JobManualEditSubtitle = {
  index: number;
  start_time: number;
  end_time: number;
  text_raw?: string | null;
  text_norm?: string | null;
  text_final?: string | null;
};

export type JobManualEditSession = {
  job_id: string;
  timeline_id: string;
  timeline_version: number;
  render_plan_version?: number | null;
  source_name: string;
  source_duration_sec: number;
  source_url?: string | null;
  keep_segments: JobManualEditSegment[];
  source_subtitles: JobManualEditSubtitle[];
  projected_subtitles: JobManualEditSubtitle[];
  subtitle_overrides: JobManualEditSubtitleOverride[];
  editable: boolean;
  detail?: string | null;
};

export type JobManualEditSubtitleOverride = {
  index: number;
  start_time?: number | null;
  end_time?: number | null;
  text_final?: string | null;
  delete?: boolean;
};

export type JobManualEditApplyResponse = {
  job_id: string;
  timeline_id: string;
  timeline_version: number;
  render_plan_id: string;
  render_plan_version: number;
  keep_segment_count: number;
  projected_subtitle_count: number;
  job_status: string;
  change_scope: string;
  render_strategy: string;
  rerun_steps: string[];
  detail?: string | null;
};

export type JobManualEditApplyPayload = {
  keep_segments: Array<{ start: number; end: number }>;
  subtitle_overrides?: JobManualEditSubtitleOverride[];
  base_timeline_id?: string;
  base_timeline_version?: number;
  base_render_plan_version?: number | null;
  note?: string;
};

export type JobManualEditPreviewAssets = {
  job_id: string;
  ready: boolean;
  warming: boolean;
  asset_version: number;
  status?: string | null;
  stage?: string | null;
  progress?: number | null;
  audio_url?: string | null;
  duration_sec: number;
  sample_rate: number;
  peaks: number[];
  peak_count: number;
  thumbnail_urls: string[];
  thumbnail_items: Array<{ url: string; time_sec: number }>;
  cached: boolean;
  detail?: string | null;
  error?: string | null;
  updated_at?: string | null;
};

export type JobActivity = {
  job_id: string;
  status: string;
  review_step?: "summary_review" | "final_review" | null;
  review_detail?: string | null;
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
  decisions: JobActivityDecision[];
  events: JobActivityEvent[];
};

export type TokenUsageReport = {
  job_id: string;
  has_telemetry: boolean;
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  cache: {
    total_entries: number;
    hits: number;
    misses: number;
    hit_rate: number;
    avoided_calls: number;
    steps_with_hits: number;
    hits_with_usage_baseline: number;
    saved_prompt_tokens: number;
    saved_completion_tokens: number;
    saved_total_tokens: number;
    saved_tokens_hit_rate: number;
  };
  steps: Array<{
    step_name: string;
    label: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    last_updated_at?: string | null;
    cache_entries: Array<{
      name: string;
      namespace: string;
      key: string;
      hit: boolean;
      usage_baseline?: {
        operation?: string;
        calls: number;
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
      } | null;
    }>;
    operations: Array<{
      operation: string;
      calls: number;
      prompt_tokens: number;
      completion_tokens: number;
      total_tokens: number;
    }>;
  }>;
  models: Array<{
    model: string;
    provider?: string | null;
    kind?: string | null;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  }>;
};

export type JobsUsageSummary = {
  job_count: number;
  jobs_with_telemetry: number;
  total_calls: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_tokens: number;
  cache: {
    total_entries: number;
    hits: number;
    misses: number;
    hit_rate: number;
    avoided_calls: number;
    steps_with_hits: number;
    hits_with_usage_baseline: number;
    saved_prompt_tokens: number;
    saved_completion_tokens: number;
    saved_total_tokens: number;
    saved_tokens_hit_rate: number;
  };
  top_steps: Array<{
    step_name: string;
    label: string;
    jobs: number;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cache_hits: number;
    cache_misses: number;
  }>;
  top_models: Array<{
    model: string;
    provider?: string | null;
    kind?: string | null;
    jobs: number;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  }>;
  top_providers: Array<{
    provider: string;
    jobs: number;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  }>;
};

export type JobsUsageTrend = {
  days: number;
  focus_type?: string | null;
  focus_name?: string | null;
  points: Array<{
    date: string;
    label: string;
    job_count: number;
    jobs_with_telemetry: number;
    total_calls: number;
    total_prompt_tokens: number;
    total_completion_tokens: number;
    total_tokens: number;
    cache: {
      total_entries: number;
      hits: number;
      misses: number;
      hit_rate: number;
      avoided_calls: number;
      steps_with_hits: number;
      hits_with_usage_baseline: number;
      saved_prompt_tokens: number;
      saved_completion_tokens: number;
      saved_total_tokens: number;
      saved_tokens_hit_rate: number;
    };
    top_entry?: {
      dimension: string;
      name: string;
      label: string;
      total_tokens: number;
    } | null;
    top_step?: {
      step_name: string;
      label: string;
      total_tokens: number;
    } | null;
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
  config_profile_id?: string | null;
  workflow_template?: string | null;
  output_dir?: string | null;
  enabled: boolean;
  recursive: boolean;
  scan_mode: "fast" | "precise";
  ingest_mode: "task_only" | "full_auto";
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

export type IntelligentCopyInspect = {
  folder_path: string;
  material_dir: string;
  video_file?: string | null;
  subtitle_file?: string | null;
  cover_file?: string | null;
  extra_video_files: string[];
  extra_subtitle_files: string[];
  extra_cover_files: string[];
  warnings: string[];
};

export type IntelligentCopyPlatformMaterial = {
  key: string;
  label: string;
  has_title: boolean;
  title_label: string;
  body_label: string;
  tag_label: string;
  constraints: {
    title_limit: number;
    body_limit: number;
    tag_limit: number;
    tag_style: string;
    cover_size: {
      width: number;
      height: number;
    };
    rule_note: string;
  };
  titles: string[];
  primary_title: string;
  title_copy_all: string;
  body: string;
  tags: string[];
  tags_copy: string;
  full_copy: string;
  cover_path?: string | null;
};

export type IntelligentCopyResult = {
  folder_path: string;
  material_dir: string;
  markdown_path: string;
  json_path: string;
  copy_style: string;
  inspection: IntelligentCopyInspect;
  highlights: Record<string, string>;
  content_profile_summary: Record<string, unknown>;
  platforms: IntelligentCopyPlatformMaterial[];
  warnings: string[];
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

export type AvatarPersonalInfo = {
  public_name?: string | null;
  real_name?: string | null;
  title?: string | null;
  organization?: string | null;
  location?: string | null;
  bio?: string | null;
  expertise?: string[];
  experience?: string | null;
  achievements?: string | null;
  creator_focus?: string | null;
  audience?: string | null;
  style?: string | null;
  contact?: string | null;
  extra_notes?: string | null;
};

export type AvatarCreatorProfile = {
  identity?: {
    public_name?: string | null;
    real_name?: string | null;
    title?: string | null;
    organization?: string | null;
    location?: string | null;
    bio?: string | null;
  };
  positioning?: {
    creator_focus?: string | null;
    expertise?: string[];
    audience?: string | null;
    style?: string | null;
    tone_keywords?: string[];
  };
  publishing?: {
    primary_platform?: string | null;
    active_platforms?: string[];
    signature?: string | null;
    default_call_to_action?: string | null;
    description_strategy?: string | null;
    platform_credentials?: PublicationCredentialBinding[];
  };
  business?: {
    contact?: string | null;
    collaboration_notes?: string | null;
    availability?: string | null;
  };
  archive_notes?: string | null;
};

export type PublicationCredentialBinding = {
  id?: string;
  platform: string;
  platform_label?: string;
  account_label?: string | null;
  credential_ref?: string | null;
  status: string;
  enabled: boolean;
  adapter?: string;
  verified_at?: string | null;
  notes?: string | null;
  last_error?: string | null;
};

export type PublicationTarget = {
  platform: string;
  platform_label: string;
  credential_id: string;
  account_label: string;
  adapter: string;
  title: string;
  body: string;
  tags: string[];
  category?: string | null;
  collection?: PublicationCollectionOption | null;
  visibility_or_publish_mode?: string | null;
  scheduled_publish_at?: string | null;
  status: string;
};

export type PublicationCollectionOption = {
  id?: string;
  name?: string;
};

export type PublicationPlatformPublishOptions = {
  scheduled_publish_at?: string | null;
  collection_id?: string | null;
  collection_name?: string | null;
  category?: string | null;
  visibility_or_publish_mode?: string | null;
};

export type PublicationAttempt = {
  id: string;
  job_id: string;
  creator_profile_id: string;
  creator_profile_name: string;
  platform: string;
  platform_label: string;
  account_label: string;
  credential_id: string;
  adapter: string;
  status: string;
  run_status?: string | null;
  operator_summary?: string | null;
  payload_path?: string | null;
  public_url?: string | null;
  scheduled_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type PublicationPlan = {
  job_id: string;
  status: string;
  publish_ready: boolean;
  blocked_reasons: string[];
  warnings: string[];
  adapter: string;
  creator_profile_id: string;
  creator_profile_name: string;
  media_path?: string | null;
  targets: PublicationTarget[];
  existing_attempts: PublicationAttempt[];
  created_attempts?: PublicationAttempt[];
};

export type AvatarProfileDashboard = {
  completeness_score: number;
  section_status: Record<string, boolean>;
  material_counts: {
    speaking_videos: number;
    portrait_photos: number;
    voice_samples: number;
  };
  strengths: string[];
  next_steps: string[];
};

export type AvatarMaterialProfile = {
  id: string;
  display_name: string;
  presenter_alias?: string | null;
  notes?: string | null;
  personal_info?: AvatarPersonalInfo;
  creator_profile?: AvatarCreatorProfile;
  profile_dashboard?: AvatarProfileDashboard;
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
  warnings?: string[];
  summary: string;
  sections: AvatarMaterialSection[];
  profiles: AvatarMaterialProfile[];
};

export type IdentitySupportSourceKey =
  | "transcript"
  | "subtitle_snippets"
  | "source_name"
  | "source_name_terms"
  | "visible_text"
  | "visible_text_terms"
  | "evidence"
  | "evidence_terms";

export type ContentProfilePayload = Record<string, any> & {
  content_understanding?: Partial<ContentUnderstanding> | null;
  keywords?: string[];
  search_queries?: string[];
};

export type ContentProfileReview = {
  job_id: string;
  status: string;
  review_step_status: string;
  review_step_detail?: string | null;
  review_reasons?: string[];
  blocking_reasons?: string[];
  identity_review?: {
    required?: boolean;
    first_seen_brand?: boolean;
    first_seen_model?: boolean;
    conservative_summary?: boolean;
    support_sources?: IdentitySupportSourceKey[];
    evidence_strength?: string;
    reason?: string;
    evidence_bundle?: {
      candidate_brand?: string | null;
      candidate_model?: string | null;
      matched_subtitle_snippets?: string[];
      matched_glossary_aliases?: {
        brand?: string[];
        model?: string[];
      } | null;
      matched_source_name_terms?: string[];
      matched_visible_text_terms?: string[];
      matched_evidence_terms?: string[];
    } | null;
  } | null;
  ocr_evidence: Record<string, any>;
  transcript_evidence: Record<string, any>;
  entity_resolution_trace: Record<string, any>;
  workflow_mode: string;
  enhancement_modes: string[];
  draft: ContentProfilePayload | null;
  final: ContentProfilePayload | null;
  memory: Record<string, any> | null;
};

export type ContentUnderstanding = {
  video_type: string;
  content_domain: string;
  primary_subject: string;
  subject_entities: Record<string, any>[];
  video_theme: string;
  summary: string;
  hook_line: string;
  engagement_question: string;
  question?: string;
  search_queries: string[];
  evidence_spans: Record<string, any>[];
  uncertainties: string[];
  confidence: Record<string, number>;
  needs_review: boolean;
  review_reasons: string[];
};

export type ContentProfileMemoryStats = {
  scope: string;
  subject_domain?: string | null;
  subject_domains: string[];
  total_corrections: number;
  total_keywords: number;
  total_learned_hotwords: number;
  field_preferences: Record<string, Array<Record<string, any>>>;
  keyword_preferences: Array<Record<string, any>>;
  learned_hotwords: LearnedHotword[];
  recent_corrections: Array<Record<string, any>>;
  cloud: {
    words?: Array<{ label: string; count: number; weight?: number; kind?: string; hint?: string }>;
    learned_hotwords?: LearnedHotword[];
  };
};

export type LearnedHotword = {
  id: string;
  subject_domain: string;
  term: string;
  canonical_form: string;
  aliases: string[];
  source: string;
  status: "active" | "suppressed" | "rejected" | string;
  evidence_count: number;
  positive_count: number;
  negative_count: number;
  prompt_count: number;
  confidence: number;
  metadata_json?: Record<string, any> | null;
  last_seen_at?: string | null;
  last_prompted_at?: string | null;
  created_at: string;
  updated_at?: string | null;
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
  persistence: {
    settings_store: string;
    profiles_store: string;
    packaging_store: string;
  };
  transcription_provider: string;
  transcription_model: string;
  transcription_dialect: string;
  llm_mode: string;
  llm_routing_mode?: string;
  reasoning_provider: string;
  reasoning_model: string;
  llm_backup_enabled?: boolean;
  backup_reasoning_provider?: string;
  backup_reasoning_model?: string;
  backup_reasoning_effort?: string;
  backup_vision_model?: string;
  backup_search_provider?: string;
  backup_search_fallback_provider?: string;
  backup_model_search_helper?: string;
  local_reasoning_model: string;
  local_vision_model: string;
  hybrid_analysis_provider?: string;
  hybrid_analysis_model?: string;
  hybrid_analysis_search_mode?: string;
  hybrid_copy_provider?: string;
  hybrid_copy_model?: string;
  hybrid_copy_search_mode?: string;
  multimodal_fallback_provider: string;
  multimodal_fallback_model: string;
  search_provider: string;
  search_fallback_provider: string;
  model_search_helper: string;
  local_asr_api_base_url: string;
  local_asr_model_name: string;
  local_asr_display_name: string;
  transcription_chunking_enabled: boolean;
  transcription_chunk_threshold_sec: number;
  transcription_chunk_size_sec: number;
  transcription_chunk_min_sec: number;
  transcription_chunk_overlap_sec: number;
  transcription_chunk_request_timeout_sec: number;
  avatar_provider: string;
  avatar_api_key_set: boolean;
  avatar_presenter_id: string;
  avatar_layout_template: string;
  avatar_safe_margin: number;
  avatar_overlay_scale: number;
  voice_provider: string;
  voice_clone_api_key_set: boolean;
  voice_clone_voice_id: string;
  director_rewrite_strength: number;
  publication_browser_agent_base_url: string;
  publication_browser_agent_auth_token_set: boolean;
  publication_worker_poll_interval_sec: number;
  publication_worker_batch_limit: number;
  publication_attempt_lease_sec: number;
  publication_browser_agent_timeout_sec: number;
  ollama_api_key_set: boolean;
  openai_api_key_set: boolean;
  anthropic_api_key_set: boolean;
  minimax_api_key_set: boolean;
  minimax_coding_plan_api_key_set: boolean;
  max_upload_size_mb: number;
  max_video_duration_sec: number;
  ffmpeg_timeout_sec: number;
  transcribe_runtime_timeout_sec: number;
  allowed_extensions: string[];
  preferred_ui_language: string;
  telegram_agent_enabled: boolean;
  telegram_agent_claude_enabled: boolean;
  telegram_agent_claude_command: string;
  telegram_agent_claude_model: string;
  telegram_agent_codex_command: string;
  telegram_agent_codex_model: string;
  telegram_agent_acp_command: string;
  telegram_agent_task_timeout_sec: number;
  telegram_agent_result_max_chars: number;
  telegram_agent_state_dir: string;
  acp_bridge_backend: string;
  acp_bridge_fallback_backend: string;
  acp_bridge_claude_model: string;
  acp_bridge_codex_command: string;
  acp_bridge_codex_model: string;
  telegram_remote_review_enabled: boolean;
  telegram_bot_api_base_url: string;
  telegram_bot_token_set: boolean;
  telegram_bot_chat_id: string;
  default_job_workflow_mode: string;
  default_job_enhancement_modes: string[];
  fact_check_enabled: boolean;
  auto_confirm_content_profile: boolean;
  content_profile_review_threshold: number;
  content_profile_auto_review_min_accuracy: number;
  content_profile_auto_review_min_samples: number;
  auto_accept_glossary_corrections: boolean;
  glossary_correction_review_threshold: number;
  auto_select_cover_variant: boolean;
  cover_selection_review_gap: number;
  packaging_selection_review_gap: number;
  packaging_selection_min_score: number;
  subtitle_filler_cleanup_enabled: boolean;
  quality_auto_rerun_enabled: boolean;
  quality_auto_rerun_below_score: number;
  quality_auto_rerun_max_attempts: number;
  override_keys: string[];
  session_secret_keys: string[];
  profile_bindable_keys: string[];
  overrides: Record<string, unknown>;
};

export type RuntimeEnvironment = {
  openai_base_url: string;
  openai_auth_mode: string;
  openai_api_key_helper: string;
  anthropic_base_url: string;
  anthropic_auth_mode: string;
  anthropic_api_key_helper: string;
  minimax_base_url: string;
  minimax_api_host: string;
  ollama_base_url: string;
  avatar_api_base_url: string;
  avatar_training_api_base_url: string;
  voice_clone_api_base_url: string;
  publication_browser_agent_base_url: string;
  output_dir: string;
};

export type ProviderServiceStatusEntry = {
  name: string;
  base_url: string;
  status: string;
  error?: string | null;
};

export type ProviderServiceStatus = {
  checked_at: string;
  services: Record<string, ProviderServiceStatusEntry>;
};

export type ProviderCheckResult = {
  provider: string;
  base_url: string;
  checked_at: string;
  status: string;
  detail?: string | null;
  models: string[];
};

export type ModelCatalog = {
  provider: string;
  kind: string;
  models: string[];
  source: string;
  refreshed_at: string;
  status: string;
  error?: string | null;
};

export type ReadinessCheck = {
  status: string;
  detail: string;
};

export type OrchestratorLockSnapshot = {
  status?: string;
  leader_active?: boolean | null;
  detail?: string;
};

export type ManagedServiceSnapshot = {
  name: string;
  url: string;
  status: string;
  enabled: boolean;
};

export type WatchAutomationSnapshot = {
  roots_total: number;
  running_scans: number;
  cached_pending_total: number;
  auto_enqueue_enabled: boolean;
  auto_merge_enabled: boolean;
  active_jobs: number;
  running_gpu_steps: number;
  idle_slots: number;
};

export type HealthDetail = {
  checked_at: string;
  status: string;
  api_version?: string;
  readiness: {
    status: string;
    checks: Record<string, ReadinessCheck>;
  };
  orchestrator_lock: OrchestratorLockSnapshot;
  managed_services: ManagedServiceSnapshot[];
  watch_automation: WatchAutomationSnapshot;
};

export type ConfigOptions = {
  job_languages: SelectOption[];
  workflow_templates: SelectOption[];
  workflow_modes: SelectOption[];
  enhancement_modes: SelectOption[];
  transcription_dialects: SelectOption[];
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

export type ConfigProfileDirtyDetail = {
  key: string;
  saved_value: unknown;
  current_value: unknown;
};

export type ConfigProfile = {
  id: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  is_active: boolean;
  is_dirty: boolean;
  dirty_keys: string[];
  dirty_details: ConfigProfileDirtyDetail[];
  llm_mode: string;
  transcription_provider: string;
  transcription_model: string;
  transcription_dialect: string;
  reasoning_provider: string;
  reasoning_model: string;
  workflow_mode: string;
  enhancement_modes: string[];
  auto_confirm_content_profile: boolean;
  content_profile_review_threshold: number;
  packaging_selection_min_score: number;
  quality_auto_rerun_enabled: boolean;
  quality_auto_rerun_below_score: number;
  copy_style: string;
  cover_style: string;
  title_style: string;
  subtitle_style: string;
  smart_effect_style: string;
  avatar_presenter_id: string;
  packaging_enabled: boolean;
  insert_pool_size: number;
  music_pool_size: number;
};

export type ConfigProfiles = {
  active_profile_id?: string | null;
  active_profile_dirty: boolean;
  active_profile_dirty_keys: string[];
  active_profile_dirty_details: ConfigProfileDirtyDetail[];
  profiles: ConfigProfile[];
};

export type ServiceStatus = {
  checked_at: string;
  services: Record<string, boolean>;
  runtime?: {
    readiness_status?: string;
    readiness_checks?: Record<string, ReadinessCheck>;
    orchestrator_lock?: OrchestratorLockSnapshot;
    review_notifications?: ReviewNotificationSnapshot;
    live_readiness?: LiveReadinessSnapshot;
  };
};

export type LiveReadinessSnapshot = {
  status: string;
  gate_passed: boolean;
  summary: string;
  stable_run_count: number;
  required_stable_runs: number;
  failure_reasons?: string[];
  warning_reasons?: string[];
  golden_job_count?: number;
  evaluated_job_count?: number;
  report_file?: string;
  report_created_at?: string | null;
  detail?: string;
};

export type ReviewNotificationSnapshot = {
  state_dir?: string;
  store_file?: string;
  detail?: string;
  summary?: {
    total: number;
    pending: number;
    due_now: number;
    failed: number;
    delivered: number;
  };
  items?: Array<{
    notification_id: string;
    kind: string;
    job_id: string;
    status: string;
    attempt_count: number;
    next_attempt_at: string;
    last_error: string;
    force_full_review: boolean;
    updated_at: string;
  }>;
};
