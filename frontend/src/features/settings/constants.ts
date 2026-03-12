export type SettingsForm = Record<string, string | number | boolean>;

export const REASONING_PROVIDER_OPTIONS = ["openai", "anthropic", "minimax", "ollama"] as const;
export const LLM_MODE_OPTIONS = ["performance", "local"] as const;
export const OPENAI_AUTH_OPTIONS = ["api_key", "codex_compat"] as const;
export const ANTHROPIC_AUTH_OPTIONS = ["api_key", "claude_code_compat"] as const;
