import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import type { ToolAsrResult, ToolAvatarResult, ToolRunStage, ToolRunStatus, ToolServiceStatus, ToolTtsMode, ToolTtsResult } from "../types";
import "./ToolsPage.css";

const toolCards = [
  {
    key: "tts",
    title: "TTS",
    label: "文本转语音",
    route: "/tools/tts",
    provider: "CosyVoice3",
    detail: "上传参考音色，输入脚本后直接生成 WAV。",
  },
  {
    key: "asr",
    title: "ASR",
    label: "音频转文字",
    route: "/tools/asr",
    provider: "MOSS-Audio / Local HTTP ASR",
    detail: "上传音频，复用当前本地 ASR 配置输出文本和片段。",
  },
  {
    key: "avatar",
    title: "数字人",
    label: "口播预览",
    route: "/tools/avatar",
    provider: "HeyGem",
    detail: "上传主播视频和配音音频，生成一段数字人口播预览。",
  },
];

const toolOptionStorageKeys = {
  tts: "roughcut.tools.tts.options",
  asr: "roughcut.tools.asr.options",
  avatar: "roughcut.tools.avatar.options",
};

const cosyVoiceTtsModes = [
  {
    key: "sft",
    label: "sft",
    summary: "使用模型内置音色 ID 合成。",
    detail: "需要填写 /query_tts_model 返回的 spk_id；如果模型没有内置音色列表，此模式不可用。",
  },
  {
    key: "zero_shot",
    label: "zero_shot",
    summary: "使用 prompt_wav 和 prompt_text 复刻参考音色。",
    detail: "需要 prompt_wav/reference_audio；CosyVoice3 prompt_text 需要包含 <|endofprompt|> 分隔符。",
  },
  {
    key: "cross_lingual",
    label: "cross_lingual",
    summary: "用参考音频音色合成另一种语言的文本。",
    detail: "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。",
  },
  {
    key: "instruct2",
    label: "instruct2",
    summary: "用 instruct_text 控制语言、方言、情绪、语速或音量。",
    detail: "需要 prompt_wav/reference_audio；instruct_text 需要包含 <|endofprompt|> 分隔符。",
  },
] satisfies CosyVoiceTtsMode[];

type CosyVoiceTtsModeKey = ToolTtsMode;
type CosyVoiceTtsMode = {
  key: CosyVoiceTtsModeKey;
  label: string;
  summary: string;
  detail: string;
};

const typicalSftVoiceIds = [
  { id: "中文女", label: "中文女" },
  { id: "中文男", label: "中文男" },
  { id: "英文女", label: "英文女" },
  { id: "英文男", label: "英文男" },
  { id: "日语男", label: "日语男" },
  { id: "粤语女", label: "粤语女" },
  { id: "韩语女", label: "韩语女" },
];

const crossLingualTextPresets = [
  { label: "中文", text: "这是一段跨语言音色测试文本。" },
  { label: "English", text: "This is a cross-lingual voice test for the selected reference voice." },
  { label: "日本語", text: "これは参照音声を使ったクロスリンガル音声テストです。" },
  { label: "粤语", text: "呢段系跨语言音色测试文本。" },
];

const instructTextPresets = [
  { label: "开心", text: "You are a helpful assistant. 请非常开心地说一句话。<|endofprompt|>" },
  { label: "沉稳", text: "You are a helpful assistant. 请用沉稳、清晰、可信的语气说这句话。<|endofprompt|>" },
  { label: "四川话", text: "You are a helpful assistant. 请用四川话表达。<|endofprompt|>" },
  { label: "慢速强调", text: "You are a helpful assistant. 请用尽可能慢地语速说一句话。<|endofprompt|>" },
  { label: "温柔旁白", text: "You are a helpful assistant. 请用温柔、贴近耳边旁白的方式说这句话。<|endofprompt|>" },
];

type TtsToolOptions = {
  mode: CosyVoiceTtsModeKey;
  ttsText: string;
  promptText: string;
  instructText: string;
  spkId: string;
  zeroShotSpkId: string;
  stream: "true" | "false";
  speed: string;
  seed: string;
  textFrontend: "true" | "false";
};

type AsrToolOptions = {
  language: string;
  prompt: string;
};

type AvatarToolOptions = {
  script: string;
};

const defaultTtsText = "这是一段 RoughCut 小工具页面的 CosyVoice3 试音。";
const cosyVoicePromptBoundary = "<|endofprompt|>";

const defaultTtsOptions: TtsToolOptions = {
  mode: "zero_shot",
  ttsText: defaultTtsText,
  promptText: "You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。",
  instructText: "",
  spkId: "",
  zeroShotSpkId: "",
  stream: "true",
  speed: "1",
  seed: "0",
  textFrontend: "true",
};

const defaultAsrOptions: AsrToolOptions = {
  language: "zh-CN",
  prompt: "",
};

const defaultAvatarOptions: AvatarToolOptions = {
  script: "",
};

function resolveCosyVoiceTtsMode(key: string): CosyVoiceTtsMode {
  return cosyVoiceTtsModes.find((mode) => mode.key === key) ?? cosyVoiceTtsModes[0];
}

function coerceTtsMode(value: unknown): CosyVoiceTtsModeKey {
  const raw = String(value || "");
  return cosyVoiceTtsModes.some((mode) => mode.key === raw) ? (raw as CosyVoiceTtsModeKey) : defaultTtsOptions.mode;
}

function coerceBooleanString(value: unknown, fallback: "true" | "false"): "true" | "false" {
  if (value === "true" || value === "false") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  return fallback;
}

function readStoredOptions<T extends Record<string, unknown>>(key: string, defaults: T, coerce: (value: Partial<T>) => T): T {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return defaults;
    const parsed = JSON.parse(raw) as Partial<T>;
    return coerce(parsed);
  } catch {
    return defaults;
  }
}

function useStoredOptions<T extends Record<string, unknown>>(key: string, defaults: T, coerce: (value: Partial<T>) => T) {
  const [options, setOptions] = useState<T>(() => readStoredOptions(key, defaults, coerce));
  useEffect(() => {
    window.localStorage.setItem(key, JSON.stringify(options));
  }, [key, options]);
  return [options, setOptions] as const;
}

function coerceTtsOptions(value: Partial<TtsToolOptions>): TtsToolOptions {
  return {
    mode: coerceTtsMode(value.mode),
    ttsText: String(value.ttsText ?? defaultTtsOptions.ttsText),
    promptText: String(value.promptText ?? defaultTtsOptions.promptText),
    instructText: String(value.instructText ?? defaultTtsOptions.instructText),
    spkId: String(value.spkId ?? defaultTtsOptions.spkId),
    zeroShotSpkId: String(value.zeroShotSpkId ?? defaultTtsOptions.zeroShotSpkId),
    stream: coerceBooleanString(value.stream, defaultTtsOptions.stream),
    speed: String(value.speed ?? defaultTtsOptions.speed),
    seed: String(value.seed ?? defaultTtsOptions.seed),
    textFrontend: coerceBooleanString(value.textFrontend, defaultTtsOptions.textFrontend),
  };
}

function ensureCosyVoicePromptBoundary(value: string, fallback = ""): string {
  const raw = String(value || fallback || "").trim();
  if (!raw) return raw;
  return raw.includes(cosyVoicePromptBoundary) ? raw : `${raw}${cosyVoicePromptBoundary}`;
}

function coerceAsrOptions(value: Partial<AsrToolOptions>): AsrToolOptions {
  const language = String(value.language || defaultAsrOptions.language);
  return {
    language: language === "en-US" ? "en-US" : "zh-CN",
    prompt: String(value.prompt ?? defaultAsrOptions.prompt),
  };
}

function coerceAvatarOptions(value: Partial<AvatarToolOptions>): AvatarToolOptions {
  return {
    script: String(value.script ?? defaultAvatarOptions.script),
  };
}

function assetUrl(value?: string | null): string {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (raw.startsWith("http://") || raw.startsWith("https://")) return raw;
  return raw;
}

function toneForStatus(status?: string) {
  return status === "online" || status === "success" || status === "completed" ? "status-ok" : status === "failed" ? "status-off" : "status-off";
}

function isTerminalStatus(status?: string | null) {
  return status === "completed" || status === "success" || status === "failed";
}

function normalizeProgress(value?: number | null): number {
  if (typeof value !== "number" || Number.isNaN(value)) return 0;
  const percent = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function stageLabel(stage: ToolRunStage): string {
  return stage.label || stage.name || stage.key || "stage";
}

function currentStageLabel<Result>(run?: ToolRunStatus<Result>): string {
  if (!run) return "等待提交";
  if (run.current_stage) return run.current_stage;
  const activeStage = run.stages.find((stage) => !isTerminalStatus(stage.status) && stage.status !== "pending");
  return activeStage ? stageLabel(activeStage) : run.status;
}

function useToolRun<Result>(runTool: (formData: FormData) => Promise<ToolRunStatus<Result>>) {
  const [runId, setRunId] = useState<string | null>(null);
  const mutation = useMutation<ToolRunStatus<Result>, Error, FormData>({
    mutationFn: runTool,
    onSuccess: (run) => setRunId(run.run_id),
  });
  const runQuery = useQuery({
    queryKey: ["tools", "run", runId],
    queryFn: () => api.getToolRun<Result>(runId || ""),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const data = query.state.data as ToolRunStatus<Result> | undefined;
      return isTerminalStatus(data?.status) ? false : 1_200;
    },
  });
  const run = runQuery.data ?? mutation.data;
  const pending = mutation.isPending || (Boolean(run) && !isTerminalStatus(run?.status) && !runQuery.isError);
  const error = mutation.error ?? (runQuery.error as Error | null);

  return { mutation, run, pending, error };
}

function ToolRunProgress<Result>({ run }: { run?: ToolRunStatus<Result> }) {
  if (!run) return null;
  const progress = normalizeProgress(run.progress);
  return (
    <div className="tool-run-progress">
      <div className="tool-run-summary">
        <strong className={toneForStatus(run.status)}>{run.status}</strong>
        <span className="muted">Run {run.run_id}</span>
        <span className="mode-chip subtle">{progress}%</span>
      </div>
      <div className="progress-bar tool-run-progress-bar">
        <span style={{ width: `${progress}%` }} />
      </div>
      <div className="tool-run-meta">
        <span>当前阶段：{currentStageLabel(run)}</span>
        {run.detail ? <span>{run.detail}</span> : null}
      </div>
      <div className="tool-stage-list">
        {(run.stages ?? []).map((stage, index) => {
          const stageProgress = normalizeProgress(stage.progress);
          return (
            <article className="tool-stage-row" key={`${stage.key || stage.name || stage.label || "stage"}-${index}`}>
              <div className="tool-stage-head">
                <strong>{stageLabel(stage)}</strong>
                <span className={toneForStatus(stage.status)}>{stage.status}</span>
              </div>
              <div className="progress-bar tool-stage-progress">
                <span style={{ width: `${stageProgress}%` }} />
              </div>
              <div className="tool-stage-detail">
                <span>{stageProgress}%</span>
                {stage.detail || stage.error ? <span>{stage.detail || stage.error}</span> : null}
              </div>
            </article>
          );
        })}
      </div>
      {run.error ? <div className="notice notice-error">{run.error}</div> : null}
    </div>
  );
}

export function ToolsPage() {
  const status = useQuery({ queryKey: ["tools", "status"], queryFn: api.getToolStatus, refetchInterval: 30_000 });

  return (
    <section className="page-stack tools-page">
      <PageHeader
        eyebrow="Tools"
        title="小工具"
        description="把 TTS、ASR、数字人口播这些能力拆成可直接调用的页面，方便单独试音、转写和预览。"
        summary={[
          { label: "TTS", value: "CosyVoice3 Docker", detail: "用于文本到语音和音色参考测试" },
          { label: "ASR", value: "当前本地 ASR", detail: "复用剪辑流水线里的转写服务" },
          { label: "数字人", value: "HeyGem", detail: "用上传素材跑单段口播预览" },
        ]}
      />

      <PageSection eyebrow="入口" title="选择要直接调用的能力" description="每个入口都进入独立页面，提交后直接调用后端服务。">
        <div className="tool-entry-grid">
          {toolCards.map((tool) => (
            <Link className="tool-entry" key={tool.key} to={tool.route}>
              <span className="tool-entry-code">{tool.title}</span>
              <strong>{tool.label}</strong>
              <span className="muted">{tool.provider}</span>
              <span className="tool-entry-detail">{tool.detail}</span>
            </Link>
          ))}
        </div>
      </PageSection>

      <PageSection eyebrow="状态" title="工具服务在线状态" description="这里检查的是直连入口依赖，不代表完整任务流水线状态。">
        <section className="panel">
          <PanelHeader title="Service endpoints" description={status.data?.checked_at ?? "正在检查服务状态"} />
          <div className="service-grid">
            {toolCards.map((tool) => (
              <ToolStatusCard key={tool.key} status={status.data?.tools[tool.key as "tts" | "asr" | "avatar"]} />
            ))}
          </div>
          {status.isError ? <div className="notice top-gap">{(status.error as Error).message}</div> : null}
        </section>
      </PageSection>
    </section>
  );
}

function ToolStatusCard({ status }: { status?: ToolServiceStatus }) {
  return (
    <article className="service-card">
      <span>{status?.name ?? "Service"}</span>
      <strong className={toneForStatus(status?.status)}>{status?.status ?? "checking"}</strong>
      <div className="muted compact-top">{status?.base_url ?? "endpoint unavailable"}</div>
      {status?.error ? <div className="muted compact-top">{status.error}</div> : null}
    </article>
  );
}

function ToolNav() {
  const location = useLocation();
  return (
    <div className="tool-tabs" role="navigation" aria-label="Tool pages">
      {toolCards.map((tool) => (
        <Link key={tool.key} className={location.pathname === tool.route ? "tool-tab active" : "tool-tab"} to={tool.route}>
          {tool.label}
        </Link>
      ))}
    </div>
  );
}

export function TtsToolPage() {
  const { mutation, run, pending, error } = useToolRun<ToolTtsResult>(api.runToolTts);
  const status = useQuery({ queryKey: ["tools", "status"], queryFn: api.getToolStatus, refetchInterval: 30_000 });
  const [ttsOptions, setTtsOptions] = useStoredOptions(toolOptionStorageKeys.tts, defaultTtsOptions, coerceTtsOptions);
  const selectedMode = resolveCosyVoiceTtsMode(ttsOptions.mode);
  const ttsService = status.data?.tools.tts as (ToolServiceStatus & { models?: string[] }) | undefined;
  const serviceVoiceIds = useMemo(() => (ttsService?.models ?? []).filter(Boolean), [ttsService]);
  const mergedSftVoiceIds = useMemo(() => {
    const seen = new Set<string>();
    return [
      ...serviceVoiceIds.map((id) => ({ id, label: id })),
      ...typicalSftVoiceIds,
    ].filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }, [serviceVoiceIds]);
  const usesReferenceAudio = selectedMode.key !== "sft";
  const usesPromptText = selectedMode.key === "zero_shot";
  const usesInstructText = selectedMode.key === "instruct2";
  const usesSpeakerId = selectedMode.key === "sft";
  const usesZeroShotSpeakerId = selectedMode.key === "zero_shot";
  const usesCrossLingualText = selectedMode.key === "cross_lingual";

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const nextOptions = { ...ttsOptions };
    if (usesPromptText) {
      const promptText = ensureCosyVoicePromptBoundary(ttsOptions.promptText || defaultTtsOptions.promptText);
      formData.set("prompt_text", promptText);
      nextOptions.promptText = promptText;
    }
    if (usesInstructText) {
      const instructText = ensureCosyVoicePromptBoundary(ttsOptions.instructText, instructTextPresets[0]?.text);
      formData.set("instruct_text", instructText);
      nextOptions.instructText = instructText;
    }
    if (nextOptions.promptText !== ttsOptions.promptText || nextOptions.instructText !== ttsOptions.instructText) {
      setTtsOptions(nextOptions);
    }
    mutation.mutate(formData);
  };

  return (
    <section className="page-stack tools-page">
      <PageHeader
        eyebrow="TTS"
        title="文本转语音"
        description="CosyVoice3 通过 Docker 服务提供推理，提交后返回可试听的 WAV。"
        actions={<Link className="button ghost" to="/tools">返回小工具</Link>}
      />
      <ToolNav />
      <PageSection eyebrow="调用" title="生成语音" description="覆盖 CosyVoice3 官方模式与参数。stream 与 speed 不等于 1 不能同时使用。">
        <div className="panel-grid tool-workbench tts-workbench-vertical">
          <section className="panel">
            <PanelHeader title="输入" description={selectedMode.detail} />
            <form className="form-stack" onSubmit={handleSubmit}>
              <input type="hidden" name="mode" value={selectedMode.key} />
              <div className="tts-style-field">
                <div>
                  <span className="field-label">mode</span>
                </div>
                <div className="tts-mode-grid" role="radiogroup" aria-label="CosyVoice3 mode">
                  {cosyVoiceTtsModes.map((mode) => (
                    <button
                      key={mode.key}
                      type="button"
                      className={mode.key === selectedMode.key ? "tts-style-option active" : "tts-style-option"}
                      aria-checked={mode.key === selectedMode.key}
                      role="radio"
                      onClick={() =>
                        setTtsOptions((current) => ({
                          ...current,
                          mode: mode.key,
                          promptText: mode.key === "zero_shot" ? ensureCosyVoicePromptBoundary(current.promptText || defaultTtsOptions.promptText) : current.promptText,
                          instructText: mode.key === "instruct2" ? ensureCosyVoicePromptBoundary(current.instructText, instructTextPresets[0]?.text) : current.instructText,
                        }))
                      }
                    >
                      <strong>{mode.label}</strong>
                      <span>{mode.summary}</span>
                    </button>
                  ))}
                </div>
              </div>
              <label>
                <span>tts_text / text</span>
                <textarea
                  className="input"
                  name="tts_text"
                  rows={4}
                  required
                  value={ttsOptions.ttsText}
                  onChange={(event) => setTtsOptions((current) => ({ ...current, ttsText: event.target.value }))}
                />
              </label>
              <div className="tts-mode-fields">
                <div className="tts-mode-fields-head">
                  <strong>{selectedMode.label} 可用字段</strong>
                  <span>{selectedMode.detail}</span>
                </div>
                <div className="tts-mode-fields-grid">
              {usesPromptText ? (
                <div className="tts-prompt-text-field">
                  <label>
                    <span>prompt_text</span>
                    <textarea
                      className="input"
                      name="prompt_text"
                      rows={3}
                      required
                      value={ttsOptions.promptText}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, promptText: event.target.value }))}
                      placeholder="You are a helpful assistant.<|endofprompt|>参考音频里实际说出的话。"
                    />
                  </label>
                </div>
              ) : null}
              {usesInstructText ? (
                <div className="tts-prompt-text-field">
                  <div className="tts-preset-chip-grid">
                    {instructTextPresets.map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        className={ttsOptions.instructText === preset.text ? "tts-preset-chip active" : "tts-preset-chip"}
                        onClick={() => setTtsOptions((current) => ({ ...current, instructText: preset.text }))}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                  <label>
                    <span>instruct_text</span>
                    <textarea
                      className="input"
                      name="instruct_text"
                      rows={3}
                      required
                      value={ttsOptions.instructText}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, instructText: event.target.value }))}
                      placeholder="You are a helpful assistant. 请用四川话表达。<|endofprompt|>"
                    />
                  </label>
                </div>
              ) : null}
              {usesCrossLingualText ? (
                <div className="tts-prompt-text-field">
                  <div className="tts-helper-panel">
                    <strong>跨语言文本预设</strong>
                    <span>cross_lingual 复用参考音频音色，适合直接切换目标语言文本。</span>
                  </div>
                  <div className="tts-preset-chip-grid">
                    {crossLingualTextPresets.map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        className={ttsOptions.ttsText === preset.text ? "tts-preset-chip active" : "tts-preset-chip"}
                        onClick={() => setTtsOptions((current) => ({ ...current, ttsText: preset.text }))}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {usesSpeakerId ? (
                <div className="tts-prompt-text-field">
                  <div className="tts-helper-panel">
                    <strong>可用 ID</strong>
                    <span>{serviceVoiceIds.length > 0 ? `服务返回 ${serviceVoiceIds.length} 个 ID；下方同时列出常见 CosyVoice 内置 ID。` : "服务暂未返回 ID；可先试用下方常见内置 ID。"}</span>
                  </div>
                  <div className="tts-preset-chip-grid">
                    {mergedSftVoiceIds.map((voice) => (
                      <button
                        key={voice.id}
                        type="button"
                        className={ttsOptions.spkId === voice.id ? "tts-preset-chip active" : "tts-preset-chip"}
                        onClick={() => setTtsOptions((current) => ({ ...current, spkId: voice.id }))}
                      >
                        {voice.label}
                      </button>
                    ))}
                  </div>
                  <label>
                    <span>spk_id</span>
                    <input
                      className="input"
                      name="spk_id"
                      value={ttsOptions.spkId}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, spkId: event.target.value }))}
                      placeholder="/query_tts_model 返回的 speaker id"
                      required
                    />
                  </label>
                </div>
              ) : null}
              {usesReferenceAudio ? (
                <>
                  <label>
                    <span>prompt_wav / reference_audio</span>
                    <input className="input" name="prompt_wav" type="file" accept="audio/*" required />
                  </label>
                  {usesZeroShotSpeakerId ? (
                  <label>
                    <span>zero_shot_spk_id</span>
                    <input
                      className="input"
                      name="zero_shot_spk_id"
                      value={ttsOptions.zeroShotSpkId}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, zeroShotSpkId: event.target.value }))}
                      placeholder="可选；官方缓存音色 ID"
                    />
                  </label>
                  ) : null}
                </>
              ) : null}
                </div>
              </div>
              <details className="tts-advanced-fields">
                <summary>高级参数</summary>
                <div className="tts-common-fields">
                  <label>
                    <span>stream</span>
                    <select
                      className="input"
                      name="stream"
                      value={ttsOptions.stream}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, stream: event.target.value as "true" | "false" }))}
                    >
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </label>
                  <label>
                    <span>speed</span>
                    <input
                      className="input"
                      name="speed"
                      type="number"
                      min="0.5"
                      max="2"
                      step="0.05"
                      value={ttsOptions.speed}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, speed: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>seed</span>
                    <input
                      className="input"
                      name="seed"
                      type="number"
                      min="0"
                      step="1"
                      value={ttsOptions.seed}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, seed: event.target.value }))}
                    />
                  </label>
                  <label>
                    <span>text_frontend</span>
                    <select
                      className="input"
                      name="text_frontend"
                      value={ttsOptions.textFrontend}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, textFrontend: event.target.value as "true" | "false" }))}
                    >
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </label>
                </div>
              </details>
              <div className="notice compact">限制：stream=true 时 speed 必须为 1；CosyVoice3 的 prompt_text / instruct_text 需要保留 &lt;|endofprompt|&gt;。</div>
              <button className="button primary" type="submit" disabled={pending}>
                {pending ? "生成中..." : "生成语音"}
              </button>
            </form>
          </section>

          <section className="panel">
            <PanelHeader title="结果" description="显示 run 进度、阶段详情；完成后会显示输出路径和播放器。" />
            <TtsResult run={run} error={error} pending={pending} />
          </section>
        </div>
      </PageSection>
    </section>
  );
}

function TtsResult({ run, error, pending }: { run?: ToolRunStatus<ToolTtsResult>; error: Error | null; pending: boolean }) {
  if (error) return <div className="notice">{error.message}</div>;
  if (!run) return <div className="empty-state compact">还没有生成结果。</div>;
  const result = run.result;
  return (
    <div className="tool-result">
      <ToolRunProgress run={run} />
      {pending ? <div className="notice">正在请求 TTS 服务。</div> : null}
      {result ? (
        <>
          <audio className="tool-media" controls src={assetUrl(result.audio_url)} />
          <div className="muted">{result.output_path}</div>
          <div className="mode-chip-list">
            <span className="mode-chip subtle">{result.provider}</span>
            <span className="mode-chip subtle">{result.mode}</span>
            <span className="mode-chip subtle">{result.format}</span>
            {result.sample_rate ? <span className="mode-chip subtle">{result.sample_rate} Hz</span> : null}
            {result.source_format ? <span className="mode-chip subtle">{result.source_format}</span> : null}
          </div>
          {result.text || result.tts_text || result.original_text ? (
            <div className="tts-style-preview result-preview">
              <div className="tts-style-preview-head">
                <strong>实际 TTS 文本</strong>
                <span className="mode-chip subtle">{result.mode}</span>
              </div>
              <pre>{result.tts_text || result.original_text || result.text}</pre>
            </div>
          ) : null}
          {result.prompt_text || result.instruct_text ? (
            <div className="mode-chip-list">
              {result.prompt_text ? <span className="mode-chip subtle">prompt_text</span> : null}
              {result.instruct_text ? <span className="mode-chip subtle">instruct2: {result.instruct_text}</span> : null}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export function AsrToolPage() {
  const { mutation, run, pending, error } = useToolRun<ToolAsrResult>(api.runToolAsr);
  const [asrOptions, setAsrOptions] = useStoredOptions(toolOptionStorageKeys.asr, defaultAsrOptions, coerceAsrOptions);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  };

  return (
    <section className="page-stack tools-page">
      <PageHeader
        eyebrow="ASR"
        title="音频转文字"
        description="上传音频后直接调用当前本地 HTTP ASR 服务，返回文本和片段。"
        actions={<Link className="button ghost" to="/tools">返回小工具</Link>}
      />
      <ToolNav />
      <PageSection eyebrow="调用" title="转写音频" description="热词会作为上下文传给本地 ASR，用于产品名、型号和专有名词。">
        <div className="panel-grid two-up tool-workbench">
          <section className="panel">
            <PanelHeader title="输入" description="支持本地 ASR 服务能处理的音频格式。" />
            <form className="form-stack" onSubmit={handleSubmit}>
              <label>
                <span>音频文件</span>
                <input className="input" name="audio" type="file" accept="audio/*,video/*" required />
              </label>
              <label>
                <span>语言</span>
                <select
                  className="input"
                  name="language"
                  value={asrOptions.language}
                  onChange={(event) => setAsrOptions((current) => ({ ...current, language: event.target.value }))}
                >
                  <option value="zh-CN">中文</option>
                  <option value="en-US">English</option>
                </select>
              </label>
              <label>
                <span>热词 / 上下文</span>
                <textarea
                  className="input"
                  name="prompt"
                  rows={4}
                  value={asrOptions.prompt}
                  onChange={(event) => setAsrOptions((current) => ({ ...current, prompt: event.target.value }))}
                  placeholder="品牌、型号、人物名、技术词。"
                />
              </label>
              <button className="button primary" type="submit" disabled={pending}>
                {pending ? "转写中..." : "开始转写"}
              </button>
            </form>
          </section>

          <section className="panel">
            <PanelHeader title="结果" description="主文本适合快速复制，片段用于检查时间信息；阶段区显示实际进度。" />
            <AsrResult run={run} error={error} pending={pending} />
          </section>
        </div>
      </PageSection>
    </section>
  );
}

function AsrResult({ run, error, pending }: { run?: ToolRunStatus<ToolAsrResult>; error: Error | null; pending: boolean }) {
  const result = run?.result;
  const segmentPreview = useMemo(() => result?.segments.slice(0, 12) ?? [], [result]);
  if (error) return <div className="notice">{error.message}</div>;
  if (!run) return <div className="empty-state compact">还没有转写结果。</div>;
  return (
    <div className="tool-result">
      <ToolRunProgress run={run} />
      {pending ? <div className="notice">正在请求 ASR 服务。</div> : null}
      {result ? (
        <>
          <div className="tool-transcript">{result.text || "无文本"}</div>
          <div className="mode-chip-list">
            <span className="mode-chip subtle">{result.provider ?? "asr"}</span>
            <span className="mode-chip subtle">{result.model ?? "model"}</span>
            <span className="mode-chip subtle">{result.duration.toFixed(2)}s</span>
          </div>
          <div className="list-stack">
            {segmentPreview.map((segment) => (
              <article className="list-card" key={segment.index}>
                <div>
                  <div className="row-title">{segment.text}</div>
                  <div className="muted">{segment.start.toFixed(2)}s - {segment.end.toFixed(2)}s</div>
                </div>
              </article>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}

export function AvatarToolPage() {
  const { mutation, run, pending, error } = useToolRun<ToolAvatarResult>(api.runToolAvatar);
  const [avatarOptions, setAvatarOptions] = useStoredOptions(toolOptionStorageKeys.avatar, defaultAvatarOptions, coerceAvatarOptions);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    mutation.mutate(new FormData(event.currentTarget));
  };

  return (
    <section className="page-stack tools-page">
      <PageHeader
        eyebrow="Avatar"
        title="数字人口播"
        description="上传一段主播视频和配音音频，直接调用 HeyGem 生成单段预览。"
        actions={<Link className="button ghost" to="/tools">返回小工具</Link>}
      />
      <ToolNav />
      <PageSection eyebrow="调用" title="生成口播预览" description="这页适合验证视频素材、音频素材和 HeyGem 服务是否能协同跑通。">
        <div className="panel-grid two-up tool-workbench">
          <section className="panel">
            <PanelHeader title="输入" description="主播视频会被准备成 HeyGem 可访问素材，音频会被提交为本段口播。" />
            <form className="form-stack" onSubmit={handleSubmit}>
              <label>
                <span>主播视频</span>
                <input className="input" name="presenter_video" type="file" accept="video/*" required />
              </label>
              <label>
                <span>配音音频</span>
                <input className="input" name="audio" type="file" accept="audio/*" required />
              </label>
              <label>
                <span>脚本文本</span>
                <textarea
                  className="input"
                  name="script"
                  rows={4}
                  value={avatarOptions.script}
                  onChange={(event) => setAvatarOptions((current) => ({ ...current, script: event.target.value }))}
                  placeholder="可选。用于记录本次预览对应的口播文本。"
                />
              </label>
              <button className="button primary" type="submit" disabled={pending}>
                {pending ? "生成中..." : "生成数字人预览"}
              </button>
            </form>
          </section>

          <section className="panel">
            <PanelHeader title="结果" description="成功时会显示可播放的预览视频，并保留每阶段进度详情。" />
            <AvatarResult run={run} error={error} pending={pending} />
          </section>
        </div>
      </PageSection>
    </section>
  );
}

function AvatarResult({ run, error, pending }: { run?: ToolRunStatus<ToolAvatarResult>; error: Error | null; pending: boolean }) {
  if (error) return <div className="notice">{error.message}</div>;
  if (!run) return <div className="empty-state compact">还没有预览结果。</div>;
  const result = run.result;
  return (
    <div className="tool-result">
      <ToolRunProgress run={run} />
      {pending ? <div className="notice">正在请求 HeyGem 服务，数字人预览可能需要几分钟。</div> : null}
      {result ? (
        <>
          {result.artifact_url ? <video className="tool-media" controls src={assetUrl(result.artifact_url)} /> : null}
          {result.artifact_path ? <div className="muted">{result.artifact_path}</div> : null}
          <div className="mode-chip-list">
            <span className="mode-chip subtle">{result.provider}</span>
            <span className="mode-chip subtle">{result.success_count ?? 0} success</span>
            <span className="mode-chip subtle">{result.failed_count ?? 0} failed</span>
          </div>
          <div className="list-stack">
            {(result.segments ?? []).map((segment, index) => (
              <article className="list-card" key={`${segment.segment_id ?? "segment"}-${index}`}>
                <div>
                  <div className="row-title">{segment.segment_id ?? "segment"} · {segment.status}</div>
                  <div className="muted">{segment.error || segment.local_result_path || segment.task_code || "无详情"}</div>
                </div>
              </article>
            ))}
          </div>
        </>
      ) : null}
    </div>
  );
}
