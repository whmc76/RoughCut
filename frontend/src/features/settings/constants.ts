export type SettingsForm = Record<string, string | number | boolean>;

export const REASONING_PROVIDER_OPTIONS = ["openai", "anthropic", "minimax", "ollama"] as const;
export const LLM_MODE_OPTIONS = ["performance", "local"] as const;
export const OPENAI_AUTH_OPTIONS = ["api_key", "helper"] as const;
export const ANTHROPIC_AUTH_OPTIONS = ["api_key", "helper"] as const;
export const ACP_BRIDGE_BACKEND_OPTIONS = ["", "codex", "claude"] as const;
export const COVER_IMAGE_BACKEND_OPTIONS = ["codex_builtin", "openai_images_api", "minimax_images_api"] as const;
export const CODEX_RUNNER_EFFORT_OPTIONS = ["minimal", "low", "medium", "high"] as const;
