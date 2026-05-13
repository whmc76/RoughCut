import { type ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import type { ToolAsrResult, ToolAvatarResult, ToolRunStage, ToolRunStatus, ToolServiceStatus, ToolTtsMode, ToolTtsReferenceAudioItem, ToolTtsResult } from "../types";
import { formatDate } from "../utils";
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

const TTS_REFERENCE_HISTORY_LIMIT = 5;
const TTS_INSTRUCT_HINT_MAX_CHARS = 48;
const TTS_LONG_TEXT_SEGMENT_HINT_CHARS = 120;

const cosyVoiceTtsModes = [
  {
    key: "sft",
    label: "sft",
    name: "内置音色",
    summary: "使用模型内置音色 ID 合成。",
    useCase: "适合固定 speaker id 批量出音。",
    detail: "需要填写 /query_tts_model 返回的 spk_id；如果模型没有内置音色列表，此模式不可用。",
  },
  {
    key: "zero_shot",
    label: "zero_shot",
    name: "零样本复刻",
    summary: "使用 prompt_wav 和 prompt_text 复刻参考音色。",
    useCase: "适合有参考音频和准确原文时克隆音色。",
    detail: "需要 prompt_wav/reference_audio；只填写参考音频里实际说过的文本，官方分隔符由后台自动补齐。",
  },
  {
    key: "cross_lingual",
    label: "cross_lingual",
    name: "跨语言音色",
    summary: "用参考音频音色合成另一种语言的文本。",
    useCase: "适合保留音色并切换中文、英文、粤语等文本。",
    detail: "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。",
  },
  {
    key: "instruct2",
    label: "instruct2",
    name: "指令口播",
    summary: "用 instruct_text 控制语言、方言、情绪、语速或音量。",
    useCase: "推荐：最适合小工具试音、口播风格和数字人配音。",
    detail: "需要 prompt_wav/reference_audio；只填写想要的口播指令，官方分隔符由后台自动补齐。",
    recommended: true,
  },
] satisfies CosyVoiceTtsMode[];

type CosyVoiceTtsModeKey = ToolTtsMode;
type CosyVoiceTtsMode = {
  key: CosyVoiceTtsModeKey;
  label: string;
  name: string;
  summary: string;
  useCase: string;
  detail: string;
  recommended?: boolean;
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

const instructTextPresetGroups = [
  {
    title: "情绪",
    detail: "控制整体情绪色彩。",
    presets: [
      { label: "开心", text: "请用开心、明亮、有感染力的语气说这句话。" },
      { label: "兴奋", text: "请用兴奋、节奏更积极的语气说这句话。" },
      { label: "温柔", text: "请用温柔、亲近、放松的语气说这句话。" },
      { label: "严肃", text: "请用严肃、克制、有分量的语气说这句话。" },
      { label: "惊喜", text: "请用带有惊喜感和轻微上扬语调的方式说这句话。" },
    ],
  },
  {
    title: "方言/语言",
    detail: "适合地域化口播和本地化素材。",
    presets: [
      { label: "四川话", text: "请用自然的四川话表达这句话。" },
      { label: "粤语", text: "请用自然的粤语表达这句话。" },
      { label: "东北话", text: "请用自然的东北口音表达这句话。" },
      { label: "英文", text: "Please say this sentence in clear and natural English." },
      { label: "中英混合", text: "请用自然的中英混合口播方式表达这句话。" },
    ],
  },
  {
    title: "场景",
    detail: "按内容用途快速套用口播风格。",
    presets: [
      { label: "产品介绍", text: "请用清晰、可信、适合产品介绍的口播语气说这句话。" },
      { label: "直播带货", text: "请用有热情、有成交感但不夸张的直播口播语气说这句话。" },
      { label: "新闻播报", text: "请用标准、平稳、信息密度高的新闻播报语气说这句话。" },
      { label: "知识讲解", text: "请用耐心、清楚、适合知识讲解的语气说这句话。" },
      { label: "短视频旁白", text: "请用紧凑、有节奏、适合短视频旁白的方式说这句话。" },
    ],
  },
  {
    title: "内容赛道",
    detail: "面向常见内容品类的声音表达。",
    presets: [
      { label: "有声故事", text: "请用有声故事演播风格表达，语气有画面感，人物和情节转折要更清楚。" },
      { label: "儿童绘本", text: "请用适合儿童绘本朗读的温暖语气表达，节奏放慢，语调更有亲和力。" },
      { label: "卡通人物", text: "请用卡通人物般活泼、夸张但清晰的方式说这句话。" },
      { label: "课程教学", text: "请用课堂教学风格表达，逻辑清楚，重点词需要自然强调。" },
      { label: "纪录片", text: "请用纪录片旁白风格表达，沉稳、有叙事感，并保持信息清晰。" },
      { label: "情感电台", text: "请用情感电台主播风格表达，语气柔和、缓慢，并带有陪伴感。" },
      { label: "游戏解说", text: "请用游戏解说风格表达，节奏更快，情绪更投入。" },
      { label: "旅游导览", text: "请用旅游导览风格表达，亲切、清楚，并带一点探索感。" },
    ],
  },
  {
    title: "速度/力度",
    detail: "改变节奏、停顿和强调。",
    presets: [
      { label: "慢速强调", text: "请用较慢语速表达，并在重点词上做清晰强调。" },
      { label: "快速", text: "请用稍快但仍然清晰的语速说这句话。" },
      { label: "强强调", text: "请明显强调关键词，语气更坚定。" },
      { label: "轻声", text: "请用更轻、更柔和的音量说这句话。" },
      { label: "有停顿", text: "请在语义分段处加入自然停顿，让信息更容易理解。" },
    ],
  },
  {
    title: "职业/身份",
    detail: "按职业身份调整可信度和表达方式。",
    presets: [
      { label: "教师", text: "请像教师一样讲解，表达耐心、清楚，重点信息要适合学生理解。" },
      { label: "幼教老师", text: "请像幼教老师一样，声音亲切、有耐心，语气更温柔活泼。" },
      { label: "医生科普", text: "请像医生做健康科普一样，专业、谨慎、清楚地说这句话。" },
      { label: "律师解读", text: "请像律师解读条款一样，严谨、稳重、逻辑分明地说这句话。" },
      { label: "财经主播", text: "请像财经主播一样，语气专业、稳健，数字和结论要更清晰。" },
      { label: "房产顾问", text: "请像房产顾问一样，语气可信、有服务感，并突出关键信息。" },
      { label: "主持人", text: "请像活动主持人一样，声音开阔、热情，衔接自然。" },
      { label: "播音员", text: "请像专业播音员一样，字音清楚、语速稳定、气息平稳。" },
    ],
  },
  {
    title: "角色",
    detail: "给数字人和脚本预览更明确的人设。",
    presets: [
      { label: "专业顾问", text: "请像专业顾问一样，清晰、冷静、可信地说这句话。" },
      { label: "亲切客服", text: "请像亲切客服一样，礼貌、耐心、自然地说这句话。" },
      { label: "电影旁白", text: "请用有画面感、沉浸式的电影旁白语气说这句话。" },
      { label: "测评博主", text: "请像数码测评博主一样，节奏清楚、观点明确地说这句话。" },
      { label: "品牌主播", text: "请像品牌官方主播一样，稳重、有亲和力地说这句话。" },
      { label: "童话讲述", text: "请像童话故事讲述者一样，温暖、有想象力，并带一点神秘感。" },
      { label: "动画主角", text: "请像动画主角一样，声音明亮、有行动感，情绪更鲜活。" },
      { label: "机智助手", text: "请像机智助手一样，语气轻快、聪明、反应灵敏。" },
    ],
  },
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
const defaultInstructTextPreset = instructTextPresetGroups[0]?.presets[0]?.text ?? "";

const defaultTtsOptions: TtsToolOptions = {
  mode: "instruct2",
  ttsText: defaultTtsText,
  promptText: "希望你以后能够做的比我还好呦。",
  instructText: defaultInstructTextPreset,
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

function appendInstructionPreset(currentValue: string, presetValue: string): string {
  const preset = String(presetValue || "").trim();
  return preset || String(currentValue || "").trim();
}

const ttsTextUiHintFragments = cosyVoiceTtsModes.map((mode) => mode.detail);

function cleanTtsTextInput(value: string): string {
  let cleaned = String(value || "").trim();
  for (const fragment of ttsTextUiHintFragments) {
    cleaned = cleaned.replaceAll(fragment, "").trim();
  }
  return cleaned.replace(/\s{2,}/g, " ").trim();
}

function cleanTtsInstructInput(value: string): string {
  const firstLine = String(value || "")
    .split(/[\n；;]/)
    .map((line) => line.trim())
    .find(Boolean) ?? "";
  const normalized = firstLine
    .replace(/\s+/g, "")
    .replace(/^请/, "")
    .replace(/^像(.+?)一样[，,]?/, "$1风格，")
    .replace(/^用(.+?)(?:的方式)?(?:说|表达)[，,]?/, "$1，")
    .replaceAll("这句话", "")
    .replaceAll("一句话", "")
    .replaceAll("更温柔", "温柔")
    .replaceAll("更清楚", "清楚")
    .replace(/[，,。.\s]+$/g, "");
  if (normalized.length <= TTS_INSTRUCT_HINT_MAX_CHARS) {
    return normalized ? `${normalized}。` : "";
  }
  const truncated = normalized.slice(0, TTS_INSTRUCT_HINT_MAX_CHARS).replace(/[，,、\s]+$/g, "");
  return truncated ? `${truncated}。` : "";
}

function findTtsTextPollution(ttsText: string, ...controlValues: string[]): string {
  const spokenText = String(ttsText || "");
  for (const controlValue of controlValues) {
    const controlText = String(controlValue || "").trim();
    if (controlText && spokenText.includes(controlText)) return controlText;
  }
  return "";
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

function isVideoReference(value?: string | null): boolean {
  const raw = String(value || "").toLowerCase();
  return /\.(mp4|mov|mkv|webm|avi|m4v)(?:[?#].*)?$/.test(raw);
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

function formatFileSize(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) return "";
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDuration(value?: number | null): string {
  if (typeof value !== "number" || Number.isNaN(value) || value <= 0) return "";
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function formatHistoryTimestamp(item: ToolTtsReferenceAudioItem): string {
  return formatDate(item.created_at || item.updated_at);
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

function stageStatusClass(status?: string | null): string {
  const safeStatus = String(status || "unknown")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-");
  return `tool-stage-status-${safeStatus}`;
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
  const visibleStages = (run.stages ?? []).filter((stage) => !(run.status === "completed" && stageLabel(stage) === "failed" && stage.status === "pending"));
  const currentStage = currentStageLabel(run);
  const isRunning = !isTerminalStatus(run.status);
  return (
    <div className="tool-run-progress">
      <div className="tool-run-summary">
        <strong className={toneForStatus(run.status)}>{run.status}</strong>
        <span className="muted">Run {run.run_id}</span>
        <span className="mode-chip subtle">{progress}%</span>
      </div>
      <div
        className={`progress-bar tool-run-progress-bar${isRunning ? " is-animated" : ""}`}
        role="progressbar"
        aria-label="工具运行进度"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span className="tool-run-progress-fill" style={{ width: `${progress}%` }} />
        {visibleStages.map((stage, index) => {
          const markerLeft = visibleStages.length <= 1 ? 100 : (index / (visibleStages.length - 1)) * 100;
          return (
            <div
              className={`tool-run-progress-marker ${stageStatusClass(stage.status)}`}
              key={`${stage.key || stage.name || stage.label || "stage"}-marker-${index}`}
              style={{ left: `${markerLeft}%` }}
              title={`${stageLabel(stage)} · ${stage.status}`}
            />
          );
        })}
      </div>
      <div className="tool-run-meta">
        <span>当前阶段：{currentStage}</span>
        {run.detail ? <span>{run.detail}</span> : null}
      </div>
      <div className="tool-stage-strip" aria-label="阶段状态">
        {visibleStages.map((stage, index) => {
          const stageProgress = normalizeProgress(stage.progress);
          return (
            <span
              className={`tool-stage-chip ${stageStatusClass(stage.status)}`}
              key={`${stage.key || stage.name || stage.label || "stage"}-${index}`}
              title={`${stageLabel(stage)} · ${stage.status} · ${stageProgress}%${stage.detail || stage.error ? ` · ${stage.detail || stage.error}` : ""}`}
            >
              <span className="tool-stage-chip-dot" />
              <strong>{stageLabel(stage)}</strong>
              <span>{stage.status}</span>
            </span>
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
  const referenceHistory = useQuery({ queryKey: ["tools", "tts", "reference-audio"], queryFn: api.getToolTtsReferenceAudio, refetchInterval: 20_000 });
  const outputHistory = useQuery({ queryKey: ["tools", "tts", "outputs"], queryFn: api.getToolTtsOutputs, refetchInterval: 20_000 });
  const [ttsOptions, setTtsOptions] = useStoredOptions(toolOptionStorageKeys.tts, defaultTtsOptions, coerceTtsOptions);
  const [selectedReferencePath, setSelectedReferencePath] = useState("");
  const [localSubmitError, setLocalSubmitError] = useState("");
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
  const cleanedTtsTextLength = cleanTtsTextInput(ttsOptions.ttsText).length;
  const estimatedTtsSegmentCount = Math.max(1, Math.ceil(cleanedTtsTextLength / TTS_LONG_TEXT_SEGMENT_HINT_CHARS));
  const referenceHistoryItems = useMemo(() => {
    const seen = new Set<string>();
    const items: ToolTtsReferenceAudioItem[] = [];
    for (const item of referenceHistory.data?.items ?? []) {
      const key = item.path || item.audio_url || item.name;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      items.push(item);
      if (items.length >= TTS_REFERENCE_HISTORY_LIMIT) break;
    }
    return items;
  }, [referenceHistory.data?.items]);
  const outputHistoryItems = useMemo(() => {
    const seen = new Set<string>();
    const items: ToolTtsReferenceAudioItem[] = [];
    for (const item of outputHistory.data?.items ?? []) {
      const key = item.path || item.audio_url || item.name;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      items.push(item);
    }
    return items;
  }, [outputHistory.data?.items]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const cleanedTtsText = cleanTtsTextInput(ttsOptions.ttsText);
    const cleanedInstructText = cleanTtsInstructInput(ttsOptions.instructText);
    const pollutedControlText = findTtsTextPollution(cleanedTtsText, ttsOptions.promptText, cleanedInstructText);
    if (pollutedControlText) {
      setLocalSubmitError("朗读正文里包含参考文本或口播指令。请把 tts_text 保持为只需要说出口的正文，指令只放在 instruct_text。");
      return;
    }
    setLocalSubmitError("");
    formData.set("tts_text", cleanedTtsText);
    formData.set("text", cleanedTtsText);
    formData.set("instruct_text", cleanedInstructText);
    if (cleanedTtsText !== ttsOptions.ttsText.trim() || cleanedInstructText !== ttsOptions.instructText.trim()) {
      setTtsOptions((current) => ({ ...current, ttsText: cleanedTtsText, instructText: cleanedInstructText }));
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
              <input type="hidden" name="reference_history_path" value={selectedReferencePath} />
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
                      aria-label={`${mode.label} ${mode.name}${mode.recommended ? " 推荐" : ""}`}
                      role="radio"
                      onClick={() =>
                        setTtsOptions((current) => ({
                          ...current,
                          mode: mode.key,
                          promptText: mode.key === "zero_shot" && !current.promptText.trim() ? defaultTtsOptions.promptText : current.promptText,
                          instructText: mode.key === "instruct2" && !current.instructText.trim() ? defaultInstructTextPreset : current.instructText,
                        }))
                      }
                    >
                      <span className="tts-mode-title-row">
                        <strong>{mode.label}</strong>
                        {mode.recommended ? <span className="tts-mode-recommended">推荐</span> : null}
                      </span>
                      <span className="tts-mode-name">{mode.name}</span>
                      <span className="tts-mode-summary">{mode.summary}</span>
                      <span className="tts-mode-use-case">{mode.useCase}</span>
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
                <span className="muted compact">
                  当前约 {cleanedTtsTextLength} 字；超过约 {TTS_LONG_TEXT_SEGMENT_HINT_CHARS} 字会自动按语义分段合成并拼接
                  {estimatedTtsSegmentCount > 1 ? `，预计 ${estimatedTtsSegmentCount} 段。` : "。"}
                </span>
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
                    <span>参考音频文本 prompt_text</span>
                    <textarea
                      className="input"
                      name="prompt_text"
                      rows={3}
                      required
                      value={ttsOptions.promptText}
                      onChange={(event) => setTtsOptions((current) => ({ ...current, promptText: event.target.value }))}
                      placeholder="参考音频里实际说出的话。"
                    />
                  </label>
                </div>
              ) : null}
              {usesInstructText ? (
                <div className="tts-prompt-text-field">
                  <div className="tts-instruct-input-row">
                    <label className="tts-instruct-card">
                      <span>口播指令 instruct_text</span>
                      <textarea
                        className="input"
                        name="instruct_text"
                        rows={4}
                        required
                        value={ttsOptions.instructText}
                        onChange={(event) => setTtsOptions((current) => ({ ...current, instructText: event.target.value }))}
                        placeholder="例如：请用四川话、开心一点、语速稍慢地表达。"
                      />
                    </label>
                    <ReferenceAudioPicker
                      items={referenceHistoryItems}
                      loading={referenceHistory.isLoading}
                      selectedPath={selectedReferencePath}
                      required={usesReferenceAudio}
                      onSelect={setSelectedReferencePath}
                      onFileChange={() => setSelectedReferencePath("")}
                    />
                  </div>
                  <div className="tts-preset-category-list">
                    {instructTextPresetGroups.map((group, groupIndex) => (
                      <section className={`tts-preset-category preset-tone-${groupIndex % 5}`} key={group.title}>
                        <div className="tts-preset-category-head">
                          <strong>{group.title}</strong>
                          <span>{group.detail}</span>
                        </div>
                        <div className="tts-preset-chip-grid">
                          {group.presets.map((preset) => (
                            <button
                              key={`${group.title}-${preset.label}`}
                              type="button"
                              className={ttsOptions.instructText.includes(preset.text) ? "tts-preset-chip active" : "tts-preset-chip"}
                              onClick={() => setTtsOptions((current) => ({ ...current, instructText: appendInstructionPreset(current.instructText, preset.text) }))}
                            >
                              {preset.label}
                            </button>
                          ))}
                        </div>
                      </section>
                    ))}
                  </div>
                  <div className="muted compact">点击预设会替换口播指令；CosyVoice3 instruct2 只适合单条短指令，后台会压缩为一条安全风格提示。</div>
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
              {usesReferenceAudio && !usesInstructText ? (
                <>
                  <ReferenceAudioPicker
                    items={referenceHistoryItems}
                    loading={referenceHistory.isLoading}
                    selectedPath={selectedReferencePath}
                    required={usesReferenceAudio}
                    onSelect={setSelectedReferencePath}
                    onFileChange={() => setSelectedReferencePath("")}
                  />
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
              <div className="notice compact">限制：stream=true 时 speed 必须为 1；CosyVoice3 官方分隔符由后台自动校验并补齐。</div>
              <button className="button primary" type="submit" disabled={pending}>
                {pending ? "生成中..." : "生成语音"}
              </button>
            </form>
          </section>

          <section className="panel">
            <PanelHeader title="结果" description="显示 run 进度、阶段详情；完成后会显示输出路径和播放器。" />
            {localSubmitError ? <div className="notice notice-error">{localSubmitError}</div> : null}
            <TtsResult run={run} error={error} pending={pending} />
            <TtsOutputHistoryPanel items={outputHistoryItems} loading={outputHistory.isLoading} />
          </section>
        </div>
      </PageSection>
    </section>
  );
}

function ReferenceAudioPicker({
  items,
  loading,
  selectedPath,
  required,
  onSelect,
  onFileChange,
}: {
  items: ToolTtsReferenceAudioItem[];
  loading: boolean;
  selectedPath: string;
  required: boolean;
  onSelect: (path: string) => void;
  onFileChange: () => void;
}) {
  const selectedItem = items.find((item) => item.path === selectedPath);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploadPreview, setUploadPreview] = useState<{ url: string; name: string; type: string } | null>(null);
  const selectedPreviewUrl = selectedItem?.audio_url ? assetUrl(selectedItem.audio_url) : uploadPreview?.url ?? "";
  const selectedPreviewName = selectedItem?.name ?? uploadPreview?.name ?? "";
  const selectedPreviewIsVideo = selectedItem
    ? isVideoReference(selectedItem.name || selectedItem.audio_url || selectedItem.path)
    : uploadPreview?.type.startsWith("video/") || isVideoReference(uploadPreview?.name);

  useEffect(() => {
    return () => {
      if (uploadPreview?.url) URL.revokeObjectURL(uploadPreview.url);
    };
  }, [uploadPreview?.url]);

  const clearUploadPreview = () => {
    setUploadPreview((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return null;
    });
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleHistorySelect = (path: string) => {
    clearUploadPreview();
    onSelect(path);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    if (!file) {
      clearUploadPreview();
      return;
    }
    setUploadPreview((current) => {
      if (current?.url) URL.revokeObjectURL(current.url);
      return { url: URL.createObjectURL(file), name: file.name, type: file.type };
    });
    onFileChange();
  };

  return (
    <div className="tts-reference-upload">
      <div className="tts-reference-upload-head">
        <strong>prompt_wav / reference_audio</strong>
        {selectedPath ? (
          <button className="text-button" type="button" onClick={() => onSelect("")}>
            清除历史选择
          </button>
        ) : null}
      </div>
      <input ref={inputRef} className="input" name="prompt_wav" type="file" accept="audio/*,video/*" required={required && !selectedPath} onChange={handleFileChange} />
      <div className="muted compact">可上传音频或视频；视频会自动抽取音频并转换为参考音频。</div>
      {selectedItem ? <div className="mode-chip subtle">已选择历史：{selectedItem.name}</div> : null}
      {selectedPreviewUrl ? (
        <div className="tts-reference-preview">
          <div className="tts-reference-preview-head">
            <span>预览确认</span>
            <span>{selectedPreviewName}</span>
          </div>
          {selectedPreviewIsVideo ? (
            <video className="tts-reference-preview-media" controls src={selectedPreviewUrl} />
          ) : (
            <audio className="tts-reference-preview-media" controls src={selectedPreviewUrl} />
          )}
        </div>
      ) : null}
      <div className="tts-reference-history">
        <div className="tts-reference-history-head">
          <span>参考历史</span>
          <span>{loading ? "加载中" : `${items.length} 个`}</span>
        </div>
        {items.length > 0 ? (
          <div className="tts-reference-history-list">
            {items.map((item) => (
              <button
                key={item.path}
                type="button"
                className={item.path === selectedPath ? "tts-reference-history-item active" : "tts-reference-history-item"}
                onClick={() => handleHistorySelect(item.path)}
                title={item.path}
              >
                <strong>{item.name}</strong>
                <span>
                  {item.source}
                  {formatDuration(item.duration) ? ` · ${formatDuration(item.duration)}` : ""}
                  {item.will_trim ? " · 自动去静音并截取30s" : ""}
                  {formatFileSize(item.size) ? ` · ${formatFileSize(item.size)}` : ""}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <div className="muted compact">暂无参考历史；提交一次参考音频或视频后会出现在这里。</div>
        )}
      </div>
    </div>
  );
}

function TtsOutputHistoryPanel({ items, loading }: { items: ToolTtsReferenceAudioItem[]; loading: boolean }) {
  return (
    <section className="tts-output-history" aria-label="历史输出文件">
      <div className="tts-output-history-head">
        <div>
          <strong>历史输出文件</strong>
          <span>最近生成的 TTS 音频，独立于参考历史。</span>
        </div>
        <span className="mode-chip subtle">{loading ? "加载中" : `${items.length} 个`}</span>
      </div>
      {items.length > 0 ? (
        <div className="tts-output-history-list">
          {items.map((item) => {
            const primaryName = item.display_name || item.name;
            const secondaryMeta = [
              formatHistoryTimestamp(item),
              item.config_summary,
              formatDuration(item.duration),
              formatFileSize(item.size),
            ].filter(Boolean);
            return (
              <article className="tts-output-history-item" key={item.path || item.audio_url || item.name}>
                <div className="tts-output-history-item-head">
                  <strong title={item.path}>{primaryName}</strong>
                  <span>{formatDuration(item.duration) || formatHistoryTimestamp(item)}</span>
                </div>
                <div className="tts-output-history-meta">{secondaryMeta.join(" · ")}</div>
                {item.text_preview ? <div className="tts-output-history-text">{item.text_preview}</div> : null}
                {item.audio_url ? <audio className="tts-output-history-player" controls src={assetUrl(item.audio_url)} /> : null}
                <div className="muted compact">{item.name === primaryName ? item.source : `${item.source} · ${item.name}`}</div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state compact">还没有历史输出。</div>
      )}
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
            {result.segment_count && result.segment_count > 1 ? <span className="mode-chip subtle">{result.segment_count} 段拼接</span> : null}
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
          {result.text_segments && result.text_segments.length > 1 ? (
            <div className="tts-style-preview result-preview">
              <div className="tts-style-preview-head">
                <strong>自动分段</strong>
                <span className="mode-chip subtle">{result.text_segments.length} 段</span>
              </div>
              <pre>{result.text_segments.map((segment) => `${segment.index}. ${segment.text}`).join("\n")}</pre>
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
