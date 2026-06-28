import { useEffect, useState } from "react";

import type { JobCreateEntryMode, UploadForm } from "./constants";
import type { CapabilityDefinition, CreatorCard, SelectOption, SmartCutRuleDefinition } from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { Field } from "../../components/forms/Field";
import { SelectField } from "../../components/forms/SelectField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import { useI18n } from "../../i18n";

type JobUploadPanelProps = {
  upload: UploadForm;
  languageOptions: SelectOption[];
  workflowTemplateOptions: SelectOption[];
  workflowModeOptions: SelectOption[];
  enhancementOptions: SelectOption[];
  materialEnhancementOptions?: SelectOption[];
  smartCutRules?: SmartCutRuleDefinition[];
  capabilityCatalog?: CapabilityDefinition[];
  outputDirHistory?: string[];
  creatorCards?: CreatorCard[];
  agentMode?: boolean;
  createEntryMode?: JobCreateEntryMode;
  onChange: (next: UploadForm) => void;
};

function moveFile(files: File[], fromIndex: number, toIndex: number): File[] {
  if (toIndex < 0 || toIndex >= files.length || fromIndex === toIndex) {
    return files;
  }
  const next = [...files];
  const [file] = next.splice(fromIndex, 1);
  next.splice(toIndex, 0, file);
  return next;
}

function jobFlowModeOptions(t: (key: string) => string): SelectOption[] {
  return [
    { value: "auto", label: t("jobs.flowMode.auto") },
    { value: "smart_assist", label: t("jobs.flowMode.smart_assist") },
  ];
}

const AGENT_CAPABILITY_DESCRIPTIONS: Record<string, string> = {
  speech_density_trim: "启用语气词、重复、停顿阈值和智能删减等节奏控制。",
  screen_focus: "面向教程类素材，编排局部放大、热点强调和屏幕重点跟随。",
  chapter_cards: "根据段落结构和字幕边界生成章节卡片、步骤提示和过渡包装。",
  local_broll_insert: "把本地上传的补充视频或图片作为插片素材编排进成片版本。",
  local_audio_cues: "把本地上传的背景音乐或音效编排到包装节奏里。",
  highlight_window_selection: "从长素材中提炼高光窗口，供短视频或精华版剪辑使用。",
  multi_material_assembly: "将多个上传素材组合成一条连续叙事时间线。",
};

const FILM_REMIX_CAPABILITY_KEYS = [
  "highlight_window_selection",
  "multi_material_assembly",
  "local_broll_insert",
  "chapter_cards",
  "local_audio_cues",
  "speech_density_trim",
];

const FILM_REMIX_ENHANCEMENT_KEYS = new Set(["ai_effects"]);
const HYPERFRAMES_CONTROLLED_ENHANCEMENT_KEYS = new Set(["ai_effects"]);
const CREATE_TASK_EXCLUDED_ENHANCEMENT_KEYS = new Set(["ai_effects", "multi_platform_adaptation"]);
const FILM_REMIX_WORKFLOW_MODES = new Set(["remix_auto_commentary", "remix_llm_plan", "script_footage_remix"]);
const FILM_REMIX_AUTO_SWITCH_WORKFLOW_MODES = new Set(["remix_auto_commentary", "remix_llm_plan"]);

const FILM_REMIX_MODE_OPTIONS: Array<{ value: string; label: string; description: string }> = [
  {
    value: "remix_auto_commentary",
    label: "自动精简解说",
    description: "不输入文字时默认使用。自动生成精简解说、选镜头、配音和包装。",
  },
  {
    value: "remix_llm_plan",
    label: "智能方案编排",
    description: "输入主题、方向、要求或半成稿时使用。LLM 先分析用户方案，再决定脚本、镜头和包装。",
  },
  {
    value: "script_footage_remix",
    label: "按脚本文案讲解插入",
    description: "用于完整成稿文案。默认保留文案，不自动压缩删句，并按文案主题定位原片和插入声画桥段。",
  },
];

const FILM_REMIX_CAPABILITY_COPY: Record<string, { label: string; description: string }> = {
  highlight_window_selection: {
    label: "原片关键镜头匹配",
    description: "根据脚本段落、人物、场景、动作和情绪强度，从原片里自动提取最贴合的画面。",
  },
  multi_material_assembly: {
    label: "二创叙事组接",
    description: "把原片、补充素材和解说脚本组织成连续叙事时间线，优先保持剧情/观点连贯。",
  },
  local_broll_insert: {
    label: "补充画面插入",
    description: "把上传的参考图、补充片段或素材库画面作为解释、转场和情绪补充镜头。",
  },
  chapter_cards: {
    label: "解说段落包装",
    description: "按脚本结构生成开头钩子、段落提示、观点强调和转场包装。",
  },
  local_audio_cues: {
    label: "BGM 与音效节奏",
    description: "根据解说节奏、段落转折和画面情绪自动安排背景音乐与音效提示。",
  },
  speech_density_trim: {
    label: "解说节奏压缩",
    description: "在不破坏脚本含义的前提下压缩冗余停顿，让旁白和画面衔接更紧。",
  },
};

const FILM_REMIX_MATERIAL_LABELS: Record<string, string> = {
  auto_orientation_correction: "画面方向校正",
  voice_enhancement: "解说人声增强",
  loudness_normalization: "全片响度统一",
};

const HYPERFRAMES_OPTION_PRESENTATION: Array<{ key: string; label: string; description: string }> = [
  { key: "smart_effects", label: "智能特效与转场", description: "自动补充节奏转场、画面强调和局部视觉强化。" },
  { key: "subtitle_emphasis", label: "重点弹出字幕", description: "额外生成关键词和重点句的弹出贴片；标准字幕里的放大、变色由字幕样式控制。" },
  { key: "sound_cues", label: "音效提示", description: "在重点词、转场和节奏点自动加入轻量提示音。" },
  { key: "progress_bar", label: "分段进度条", description: "外挂包装能力：按 ASR 语义章节在成片底部显示分段进度，可随时关闭后重渲染移除。" },
  { key: "chapter_cards", label: "自动章节", description: "按内容段落生成章节卡、步骤提示和段落过渡。" },
  { key: "unified_subtitle_style", label: "统一字幕样式", description: "强制全片字幕使用同一套 Hyperframes 字幕风格。" },
];

const TRANSLATION_TARGET_LANGUAGE_OPTIONS: SelectOption[] = [
  { value: "auto", label: "自动（英文/中文）" },
  { value: "en-US", label: "英语" },
  { value: "zh-CN", label: "中文" },
  { value: "ja-JP", label: "日语" },
  { value: "ko-KR", label: "韩语" },
];

const AUTO_EDIT_RULE_GROUPS: Array<{
  key: string;
  label: string;
  stage: string;
  description: string;
  reasons: string[];
}> = [
  {
    key: "speech_cleanup",
    label: "语气词与口头禅",
    stage: "转写清理",
    description: "合并口头填充音、口头禅等低风险口播清理。",
    reasons: ["filler_word", "catchphrase_phrase"],
  },
  {
    key: "retake_cleanup",
    label: "重录口误清理",
    stage: "剪辑判定",
    description: "合并重复口误、重来提示、失败尝试和离题打断。",
    reasons: ["repeated_speech", "rollback_instruction", "restart_retake", "restart_cue", "failed_attempt", "off_topic_interruption"],
  },
  {
    key: "pause_rhythm_trim",
    label: "停顿与节奏收边",
    stage: "停顿/收边",
    description: "合并静音停顿、语义停顿和节奏边界修剪，避免重复裁同一段。",
    reasons: ["silence", "pause", "timing_trim"],
  },
  {
    key: "low_signal_cleanup",
    label: "低信息与噪音片段",
    stage: "审核候选",
    description: "合并 ASR 噪音、低信息字幕和长段非口播。",
    reasons: ["noise_subtitle", "low_signal_subtitle", "long_non_dialogue"],
  },
  {
    key: "timeline_fragment_cleanup",
    label: "短碎片与空隙清理",
    stage: "时间线收口",
    description: "合并短空段、碎片桥段和时间线空隙清理。",
    reasons: ["micro_keep", "micro_keep_bridge", "gap_fill"],
  },
];

function capabilityLayerLabel(layer: string): string {
  if (layer === "editorial") return "剪辑";
  if (layer === "packaging") return "包装";
  if (layer === "candidate") return "候选";
  if (layer === "audio") return "音频";
  return layer || "能力";
}

function capabilityDescription(capability: CapabilityDefinition): string {
  return AGENT_CAPABILITY_DESCRIPTIONS[capability.key] || capability.description || "";
}

function enhancementPresentation(option: SelectOption): SelectOption {
  if (option.value === "multilingual_translation") {
    return {
      ...option,
      label: "生成字幕译文",
    };
  }
  return option;
}

function smartCutRuleLabel(rule: SmartCutRuleDefinition): string {
  return String(rule.label || rule.reason)
    .replace(/^规则候选[：:]\s*/, "")
    .replace(/废片$/, "")
    .trim();
}

function smartCutRuleGroups(rules: SmartCutRuleDefinition[]) {
  const availableReasons = new Set(rules.map((rule) => rule.reason));
  const groupedReasons = new Set(AUTO_EDIT_RULE_GROUPS.flatMap((group) => group.reasons));
  const groups = AUTO_EDIT_RULE_GROUPS.map((group) => ({
    ...group,
    reasons: group.reasons.filter((reason) => availableReasons.has(reason)),
  })).filter((group) => group.reasons.length > 0);
  const fallbackGroups = rules
    .filter((rule) => !groupedReasons.has(rule.reason))
    .map((rule) => ({
      key: rule.reason,
      label: smartCutRuleLabel(rule),
      stage: capabilityLayerLabel(rule.kind),
      description: "未归入合并组的自动剪辑规则。",
      reasons: [rule.reason],
    }));
  return [...groups, ...fallbackGroups];
}

function filmRemixCapabilityPresentation(capability: CapabilityDefinition): CapabilityDefinition {
  const override = FILM_REMIX_CAPABILITY_COPY[capability.key];
  if (!override) return capability;
  return {
    ...capability,
    label: override.label,
    description: override.description,
  };
}

function resolveFilmRemixWorkflowMode(value: string, taskBrief: string) {
  const current = FILM_REMIX_WORKFLOW_MODES.has(value) ? value : "";
  if (current) return current;
  return taskBrief.trim() ? "remix_llm_plan" : "remix_auto_commentary";
}

function workflowModeForFilmRemixTextChange(current: string, text: string) {
  if (!FILM_REMIX_AUTO_SWITCH_WORKFLOW_MODES.has(current)) {
    return current;
  }
  return text.trim() ? "remix_llm_plan" : "remix_auto_commentary";
}

export function JobUploadPanel({
  upload,
  languageOptions,
  workflowTemplateOptions,
  workflowModeOptions,
  enhancementOptions,
  materialEnhancementOptions = [],
  smartCutRules = [],
  capabilityCatalog = [],
  outputDirHistory = [],
  creatorCards = [],
  agentMode = false,
  createEntryMode = "source_edit",
  onChange,
}: JobUploadPanelProps) {
  const { t } = useI18n();
  const previewFile = upload.files[0] ?? null;
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const isFilmRemix = createEntryMode === "film_remix";
  const isSmartDirector = createEntryMode === "smart_director";
  const filmRemixWorkflowMode = resolveFilmRemixWorkflowMode(upload.workflowMode, upload.taskBrief);
  const visibleEnhancementOptions = isFilmRemix
    ? enhancementOptions.filter((option) => FILM_REMIX_ENHANCEMENT_KEYS.has(option.value) && !HYPERFRAMES_CONTROLLED_ENHANCEMENT_KEYS.has(option.value))
    : enhancementOptions
      .filter((option) => !CREATE_TASK_EXCLUDED_ENHANCEMENT_KEYS.has(option.value))
      .map(enhancementPresentation);
  const visibleMaterialEnhancementOptions = isFilmRemix
    ? materialEnhancementOptions.map((option) => ({ ...option, label: FILM_REMIX_MATERIAL_LABELS[option.value] || option.label }))
    : materialEnhancementOptions;
  const autoEditRuleReasons = smartCutRules
    .filter((rule) => rule.kind === "filler" || rule.kind === "catchphrase" || rule.kind === "repeated" || rule.kind === "pause" || rule.kind === "smart_delete")
    .map((rule) => rule.reason);
  const visibleAutoEditRules = smartCutRules.filter((rule) => autoEditRuleReasons.includes(rule.reason));
  const visibleAutoEditRuleGroups = smartCutRuleGroups(visibleAutoEditRules);
  const agentCapabilities = isFilmRemix
    ? FILM_REMIX_CAPABILITY_KEYS
      .map((key) => capabilityCatalog.find((capability) => capability.key === key))
      .filter((capability): capability is CapabilityDefinition => Boolean(capability))
      .map(filmRemixCapabilityPresentation)
    : capabilityCatalog.filter((capability) => capability.key !== "speech_density_trim");
  const taskBriefLabel = isFilmRemix ? "脚本与任务要求" : isSmartDirector ? "一句话创意与成片要求" : "本条任务想法";
  const taskBriefPlaceholder = isFilmRemix
    ? "留空时使用自动精简解说。也可以写主题、风格、剪辑要求或半成稿；选择“按脚本文案讲解插入”时请粘贴完整成稿文案。"
    : isSmartDirector
      ? "例如：做一条 60 秒的 AI 科普短片，解释为什么手机夜景会越拍越亮，风格要像科技频道。"
    : "例如：新品开箱和老款对比，突出升级点和适合谁。";
  const reorderFile = (fromIndex: number, toIndex: number) => {
    onChange({
      ...upload,
      files: moveFile(upload.files, fromIndex, toIndex),
    });
  };
  const toggleListValue = (values: string[], value: string, checked: boolean): string[] => {
    if (checked) {
      return values.includes(value) ? values : [...values, value];
    }
    return values.filter((item) => item !== value);
  };
  const syncSpeechDensityTrimRules = (capabilityKeys: string[]): string[] => {
    const withoutAutoEditRules = upload.selectedSmartCutRuleReasons.filter((reason) => !autoEditRuleReasons.includes(reason));
    if (!capabilityKeys.includes("speech_density_trim")) return withoutAutoEditRules;
    return upload.selectedSmartCutRuleReasons;
  };
  const toggleHyperframesOption = (key: string, checked: boolean) => {
    const nextHyperframesOptions = {
      ...upload.hyperframesOptions,
      [key]: checked,
    };
    const nextEnhancementModes = key === "smart_effects"
      ? checked
        ? toggleListValue(upload.enhancementModes, "ai_effects", true)
        : upload.enhancementModes.filter((item) => item !== "ai_effects")
      : upload.enhancementModes;
    onChange({
      ...upload,
      enhancementModes: nextEnhancementModes,
      hyperframesOptions: nextHyperframesOptions,
    });
  };
  const toggleAutoEditRuleGroup = (reasons: string[], checked: boolean) => {
    const nextReasons = reasons.reduce(
      (currentReasons, reason) => toggleListValue(currentReasons, reason, checked),
      upload.selectedSmartCutRuleReasons,
    );
    const hasAutoEditReason = nextReasons.some((reason) => autoEditRuleReasons.includes(reason));
    onChange({
      ...upload,
      selectedAgentCapabilityKeys: toggleListValue(upload.selectedAgentCapabilityKeys, "speech_density_trim", hasAutoEditReason),
      selectedSmartCutRuleReasons: nextReasons,
    });
  };

  useEffect(() => {
    if (!previewFile || typeof URL.createObjectURL !== "function") {
      setPreviewUrl(null);
      return undefined;
    }

    const objectUrl = URL.createObjectURL(previewFile);
    setPreviewUrl(objectUrl);
    return () => {
      if (typeof URL.revokeObjectURL === "function") {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [previewFile]);

  return (
    <section className="panel top-gap job-upload-panel">
      <PanelHeader
        title={t("jobs.upload.title")}
        description={t("jobs.upload.description")}
        actions={
          upload.files.length > 0 ? (
            <span className="job-upload-selected-pill">
              {t("jobs.upload.selectedCount").replace("{count}", String(upload.files.length))}
            </span>
          ) : null
        }
      />
      <div className="job-upload-layout">
        <section className="job-upload-source-card">
          <label className="job-upload-file-drop">
            <span className="job-upload-file-kicker">{t("jobs.upload.file")}</span>
            <strong>{upload.files.length > 0 ? t("jobs.upload.selectedCount").replace("{count}", String(upload.files.length)) : "选择视频素材"}</strong>
            <input
              className="input"
              type="file"
              accept="video/*"
              multiple
              onChange={(event) => onChange({ ...upload, files: Array.from(event.target.files ?? []) })}
            />
            <span className="muted">{t("jobs.upload.fileHint")}</span>
          </label>
          <section className="job-upload-preview" aria-label={t("jobs.upload.previewTitle")}>
            <div className="job-upload-preview-header">
              <strong>{t("jobs.upload.previewTitle")}</strong>
              <span className="muted">
                {upload.files.length > 1 ? t("jobs.upload.previewMultipleDescription") : t("jobs.upload.previewDescription")}
              </span>
            </div>
            {previewUrl ? (
              <video
                className="packaging-video-preview job-upload-preview-player"
                controls
                playsInline
                preload="metadata"
                src={previewUrl}
                data-testid="job-upload-video-preview"
              />
            ) : (
              <div className="job-upload-preview-empty muted">{t("jobs.upload.previewEmpty")}</div>
            )}
          </section>
        </section>

        <section className="job-upload-settings-card">
          <div className="jobs-form-section-title">{agentMode ? "任务上下文" : "任务参数"}</div>
          <div className="form-grid job-upload-field-grid">
            {agentMode ? (
              <>
                <SelectField
                  label="创作者卡片"
                  value={upload.creatorCardId}
                  onChange={(event) => onChange({ ...upload, creatorCardId: event.target.value })}
                  options={[
                    { value: "", label: "暂不绑定创作者" },
                    ...creatorCards.map((creator) => ({ value: creator.id, label: creator.name })),
                  ]}
                />
                <SelectField
                  label="执行方式"
                  value={upload.executionMode}
                  onChange={(event) => {
                    const nextExecutionMode = event.target.value;
                    onChange({
                      ...upload,
                      executionMode: nextExecutionMode,
                      jobFlowMode: nextExecutionMode === "smart_assist" ? "smart_assist" : "auto",
                    });
                  }}
                  options={[
                    { value: "auto", label: "全自动" },
                    { value: "plan_first", label: "先生成方案" },
                    { value: "smart_assist", label: "智能辅助" },
                  ]}
                />
              </>
            ) : null}
            <SelectField
              label={t("jobs.upload.language")}
              value={upload.language}
              onChange={(event) => onChange({ ...upload, language: event.target.value })}
              options={languageOptions}
            />
            {agentMode ? (
              <CheckboxField
                className="job-upload-publication-material-option"
                label="自动生成发布物料"
                checked={upload.autoGeneratePublicationMaterials}
                onChange={(event) => onChange({ ...upload, autoGeneratePublicationMaterials: event.target.checked })}
              />
            ) : null}
            {!agentMode ? (
              <>
                <SelectField
                  label={t("jobs.upload.workflowTemplate")}
                  value={upload.workflowTemplate}
                  onChange={(event) => onChange({ ...upload, workflowTemplate: event.target.value })}
                  options={workflowTemplateOptions}
                />
                <SelectField
                  label={t("jobs.upload.jobFlowMode")}
                  value={upload.jobFlowMode}
                  onChange={(event) => onChange({ ...upload, jobFlowMode: event.target.value })}
                  options={jobFlowModeOptions(t)}
                />
                <SelectField
                  label={t("jobs.upload.workflowMode")}
                  value={upload.workflowMode}
                  onChange={(event) => onChange({ ...upload, workflowMode: event.target.value })}
                  options={workflowModeOptions}
                />
              </>
            ) : null}
            <div className="output-dir-field job-upload-output-field">
              <label>
                <span>{t("jobs.upload.outputDir")}</span>
                <input
                  className="input"
                  type="text"
                  value={upload.outputDir}
                  onChange={(event) => onChange({ ...upload, outputDir: event.target.value })}
                  placeholder={t("jobs.upload.outputDir")}
                />
              </label>
              {outputDirHistory.length > 0 ? (
                <div className="output-dir-history" aria-label={t("jobs.upload.outputDirHistory")}>
                  <span className="muted">{t("jobs.upload.outputDirHistory")}</span>
                  <div className="output-dir-history-list">
                    {outputDirHistory.map((outputDir) => (
                      <button
                        key={outputDir}
                        type="button"
                        className="button ghost button-sm output-dir-history-button"
                        onClick={() => onChange({ ...upload, outputDir })}
                        title={outputDir}
                      >
                        {outputDir}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      </div>

      {agentMode ? (
        <>
          {isFilmRemix ? (
            <div className="upload-enhancement-panel job-upload-remix-mode-panel top-gap">
              <div className="jobs-form-section-title">解说二创模式</div>
              <div className="job-upload-remix-mode-grid">
                {FILM_REMIX_MODE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={`job-upload-remix-mode-card${filmRemixWorkflowMode === option.value ? " is-active" : ""}`}
                    onClick={() => onChange({ ...upload, workflowMode: option.value })}
                  >
                    <strong>{option.label}</strong>
                    <span>{option.description}</span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
        <Field label={taskBriefLabel} className="job-upload-description-field job-upload-primary-brief-field">
          <textarea
            className="input"
            rows={isFilmRemix ? 8 : 5}
            value={upload.taskBrief}
            onChange={(event) => {
              const value = event.target.value;
              onChange({
                ...upload,
                workflowMode: isFilmRemix ? workflowModeForFilmRemixTextChange(filmRemixWorkflowMode, value) : upload.workflowMode,
                taskBrief: value,
                videoDescription: value,
              });
            }}
            placeholder={taskBriefPlaceholder}
          />
        </Field>
        </>
      ) : null}

      <div className="upload-enhancement-panel top-gap">
        <div className="jobs-form-section-title">Hyperframes 视觉包装</div>
        <div className="job-upload-capability-summary muted">
          特效、转场、字幕样式、音效、章节和进度条统一由 Hyperframes 计划驱动。
        </div>
        <div className="checklist-grid top-gap">
          {HYPERFRAMES_OPTION_PRESENTATION.map((option) => (
            <CheckboxField
              key={option.key}
              className="job-upload-enhancement-option"
              label={option.label}
              checked={Boolean(upload.hyperframesOptions[option.key])}
              onChange={(event) =>
                toggleHyperframesOption(option.key, event.target.checked)
              }
            />
          ))}
        </div>
      </div>

      {!agentMode ? (
        <div className="upload-enhancement-panel top-gap">
          <div className="jobs-form-section-title">{t("jobs.upload.enhancements")}</div>
          <div className="checklist-grid top-gap">
            {enhancementOptions.map((option) => {
              const checked = upload.enhancementModes.includes(option.value);
              return (
                <CheckboxField
                  key={option.value}
                  className="job-upload-enhancement-option"
                  label={option.label}
                  checked={checked}
                  onChange={(event) =>
                    onChange({
                      ...upload,
                      enhancementModes: event.target.checked
                        ? [...upload.enhancementModes, option.value]
                        : upload.enhancementModes.filter((item) => item !== option.value),
                    })
                  }
                />
              );
            })}
          </div>
        </div>
      ) : null}
      {agentMode ? (
        <div className="upload-enhancement-panel job-upload-capability-panel top-gap">
          <div className="jobs-form-section-title">{isFilmRemix ? "解说二创能力" : "Agent 编排与剪辑细项"}</div>
          <div className="job-upload-capability-summary muted">
            {isFilmRemix
              ? "勾选表示授权 Agent 按脚本、任务要求和原片类型使用该能力，不代表每条任务都会强制执行。"
              : "选择需要启用的成片能力；自动剪辑细项可单独选择。"}
          </div>
          <div className="job-upload-capability-columns">
            <section className="job-upload-capability-group">
              <div className="job-upload-capability-group-head">
                <strong>{isFilmRemix ? "二创成片增强" : "成片增强能力"}</strong>
                <span>{upload.enhancementModes.filter((value) => visibleEnhancementOptions.some((option) => option.value === value)).length}/{visibleEnhancementOptions.length} 项</span>
              </div>
              {!isFilmRemix ? (
                <div className="job-upload-capability-note">
                  智能特效与转场已移到 Hyperframes 视觉包装；多语言只生成字幕译文。平台发布包装在发布流程中配置。
                </div>
              ) : null}
              <div className="job-upload-enhancement-list">
                {visibleEnhancementOptions.map((option) => {
                  const checked = upload.enhancementModes.includes(option.value);
                  return (
                    <CheckboxField
                      key={option.value}
                      className="job-upload-enhancement-option"
                      label={option.label}
                      checked={checked}
                      onChange={(event) =>
                        onChange({
                          ...upload,
                          enhancementModes: toggleListValue(upload.enhancementModes, option.value, event.target.checked),
                        })
                      }
                    />
                  );
                })}
              </div>
              {upload.enhancementModes.includes("multilingual_translation") ? (
                <SelectField
                  label="字幕第二语言"
                  value={upload.translationTargetLanguage}
                  onChange={(event) => onChange({ ...upload, translationTargetLanguage: event.target.value })}
                  options={TRANSLATION_TARGET_LANGUAGE_OPTIONS}
                />
              ) : null}
            </section>
            <section className="job-upload-capability-group">
              <div className="job-upload-capability-group-head">
                <strong>{isFilmRemix ? "解说音频处理" : "素材增强能力"}</strong>
                <span>{upload.materialEnhancementModes.filter((value) => visibleMaterialEnhancementOptions.some((option) => option.value === value)).length}/{visibleMaterialEnhancementOptions.length} 项</span>
              </div>
              {!isFilmRemix ? (
                <div className="job-upload-capability-note">
                  方向校正会按 POV、文字和 Display Matrix 证据统一修正预览、缩略图和渲染输入。
                </div>
              ) : null}
              <div className="job-upload-enhancement-list">
                {visibleMaterialEnhancementOptions.map((option) => {
                  const checked = upload.materialEnhancementModes.includes(option.value);
                  return (
                    <CheckboxField
                      key={option.value}
                      className="job-upload-enhancement-option"
                      label={option.label}
                      checked={checked}
                      onChange={(event) =>
                        onChange({
                          ...upload,
                          materialEnhancementModes: toggleListValue(upload.materialEnhancementModes, option.value, event.target.checked),
                        })
                      }
                    />
                  );
                })}
              </div>
            </section>
            <section className="job-upload-capability-group">
              <div className="job-upload-capability-group-head">
                <strong>{isFilmRemix ? "二创 Agent 编排" : "Agent 编排能力"}</strong>
                <span>{agentCapabilities.length} 项</span>
              </div>
              <div className="job-upload-capability-card-list">
                {agentCapabilities.map((capability) => {
                  const checked = upload.selectedAgentCapabilityKeys.includes(capability.key);
                  return (
                    <label key={capability.key} className="job-upload-capability-card">
                      <input
                        type="checkbox"
                        aria-label={capability.label}
                        checked={checked}
                        onChange={(event) =>
                          onChange({
                            ...upload,
                            selectedAgentCapabilityKeys: toggleListValue(upload.selectedAgentCapabilityKeys, capability.key, event.target.checked),
                            selectedSmartCutRuleReasons: capability.key === "speech_density_trim"
                              ? syncSpeechDensityTrimRules(
                                toggleListValue(upload.selectedAgentCapabilityKeys, capability.key, event.target.checked),
                              )
                              : upload.selectedSmartCutRuleReasons,
                          })
                        }
                      />
                      <span className="job-upload-capability-card-copy">
                        <span className="job-upload-capability-card-head">
                          <strong>{capability.label}</strong>
                          <span>{capabilityLayerLabel(capability.layer)} · 按类型使用</span>
                        </span>
                        <p>{isFilmRemix ? capability.description : capabilityDescription(capability)}</p>
                      </span>
                    </label>
                  );
                })}
              </div>
            </section>
            {!isFilmRemix && visibleAutoEditRuleGroups.length ? (
              <section className="job-upload-capability-group">
                <div className="job-upload-capability-group-head">
                  <strong>自动剪辑细项</strong>
                  <span>{visibleAutoEditRuleGroups.filter((group) => group.reasons.some((reason) => upload.selectedSmartCutRuleReasons.includes(reason))).length}/{visibleAutoEditRuleGroups.length} 组</span>
                </div>
                <div className="job-upload-capability-note">
                  选择任一组会授权 Agent 使用对应的自动剪辑能力。
                </div>
                <div className="job-upload-rule-option-grid">
                  {visibleAutoEditRuleGroups.map((group) => {
                    const selectedCount = group.reasons.filter((reason) => upload.selectedSmartCutRuleReasons.includes(reason)).length;
                    const checked = selectedCount > 0;
                    return (
                      <label key={group.key} className="checkbox-row job-upload-rule-option job-upload-rule-group-option">
                        <input
                          type="checkbox"
                          checked={checked}
                          aria-label={group.label}
                          onChange={(event) => toggleAutoEditRuleGroup(group.reasons, event.target.checked)}
                        />
                        <span className="job-upload-rule-group-copy">
                          <span className="job-upload-rule-group-head">
                            <strong>{group.label}</strong>
                            <span>{group.stage} · {selectedCount || group.reasons.length}/{group.reasons.length}</span>
                          </span>
                          <span>{group.description}</span>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </section>
            ) : null}
          </div>
        </div>
      ) : null}
      {agentMode && !isFilmRemix ? (
        <>
          <Field label="平台目标" className="job-upload-description-field">
            <input
              className="input"
              type="text"
              value={upload.platformTargets.join(", ")}
              onChange={(event) =>
                onChange({
                  ...upload,
                  platformTargets: event.target.value
                    .split(",")
                    .map((item) => item.trim())
                    .filter(Boolean),
                })
              }
              placeholder="留空表示跟随创作者默认平台，例如：bilibili, douyin"
            />
          </Field>
        </>
      ) : null}
      {!agentMode ? (
        <Field label={t("jobs.upload.videoDescription")} className="job-upload-description-field">
          <textarea
            className="input"
            rows={5}
            value={upload.videoDescription}
            onChange={(event) => onChange({ ...upload, videoDescription: event.target.value })}
            placeholder={t("jobs.upload.videoDescriptionPlaceholder")}
          />
        </Field>
      ) : null}
      {upload.files.length > 0 ? (
        <div className="job-upload-file-list top-gap" aria-label={t("jobs.upload.selectedList")}>
          {upload.files.map((file, index) => (
            <div key={`${file.name}-${file.size}-${index}`} className="job-upload-file-list-item">
              <div className="job-upload-file-list-copy">
                <span>{file.name}</span>
                <div className="job-upload-file-list-meta muted">
                  <span>{t("jobs.upload.fileOrder").replace("{index}", String(index + 1))}</span>
                  {index === 0 && previewUrl ? <span>{t("jobs.upload.previewBadge")}</span> : null}
                </div>
              </div>
              <div className="job-upload-file-list-actions">
                <button
                  type="button"
                  className="button ghost button-sm"
                  onClick={() => reorderFile(index, index - 1)}
                  disabled={index === 0}
                  aria-label={t("jobs.upload.moveUp")}
                >
                  {t("jobs.upload.moveUp")}
                </button>
                <button
                  type="button"
                  className="button ghost button-sm"
                  onClick={() => reorderFile(index, index + 1)}
                  disabled={index === upload.files.length - 1}
                  aria-label={t("jobs.upload.moveDown")}
                >
                  {t("jobs.upload.moveDown")}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}
