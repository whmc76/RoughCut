import type { ConfigProfileDirtyDetail } from "../../types";
import { getTranscriptionProviderLabel } from "../settings/helpers";

export function formatDirtyKeyLabel(key: string): string {
  const knownLabels: Record<string, string> = {
    transcription_provider: "转写 provider",
    transcription_model: "转写模型",
    transcription_dialect: "转写方言",
    llm_mode: "推理模式",
    reasoning_provider: "推理 provider",
    reasoning_model: "推理模型",
    llm_backup_enabled: "备用方案开关",
    backup_reasoning_provider: "备用推理 provider",
    backup_reasoning_model: "备用推理模型",
    backup_reasoning_effort: "备用推理深度",
    backup_vision_model: "备用视觉模型",
    backup_search_provider: "备用搜索 provider",
    backup_search_fallback_provider: "备用搜索回退 provider",
    backup_model_search_helper: "备用搜索辅助模型",
    local_reasoning_model: "本地推理模型",
    local_vision_model: "本地视觉模型",
    multimodal_fallback_provider: "多模态回退 provider",
    multimodal_fallback_model: "多模态回退模型",
    search_provider: "搜索 provider",
    search_fallback_provider: "搜索回退 provider",
    model_search_helper: "搜索辅助模型",
    local_asr_api_base_url: "本地 ASR 地址",
    local_asr_model_name: "本地 ASR 实际模型",
    local_asr_display_name: "本地 ASR 显示名称",
    transcription_chunking_enabled: "长音频分块转写",
    transcription_chunk_threshold_sec: "分块阈值秒数",
    transcription_chunk_size_sec: "分块长度秒数",
    transcription_chunk_min_sec: "最小分块秒数",
    transcription_chunk_overlap_sec: "分块重叠秒数",
    transcription_chunk_request_timeout_sec: "单块请求超时秒数",
    avatar_provider: "数字人 provider",
    avatar_presenter_id: "数字人模板",
    avatar_layout_template: "数字人布局",
    avatar_safe_margin: "数字人安全边距",
    avatar_overlay_scale: "数字人缩放",
    voice_provider: "配音 provider",
    voice_clone_voice_id: "配音 Voice ID",
    director_rewrite_strength: "导演改写强度",
    default_job_workflow_mode: "工作流模式",
    default_job_enhancement_modes: "增强模式",
    fact_check_enabled: "事实校验",
    auto_confirm_content_profile: "画像自动确认",
    content_profile_review_threshold: "画像审核阈值",
    content_profile_auto_review_min_accuracy: "画像自动审核准确率",
    content_profile_auto_review_min_samples: "画像自动审核样本数",
    auto_accept_glossary_corrections: "术语自动接受",
    glossary_correction_review_threshold: "术语审核阈值",
    auto_select_cover_variant: "封面自动选择",
    cover_selection_review_gap: "封面审核差值",
    packaging_selection_review_gap: "包装审核差值",
    packaging_selection_min_score: "包装最低分",
    subtitle_filler_cleanup_enabled: "字幕口头禅清洗",
    quality_auto_rerun_enabled: "低分自动复跑",
    quality_auto_rerun_below_score: "复跑分数线",
    quality_auto_rerun_max_attempts: "复跑次数上限",
    "packaging.enabled": "包装总开关",
    "packaging.copy_style": "文案风格",
    "packaging.cover_style": "封面风格",
    "packaging.title_style": "标题风格",
    "packaging.subtitle_style": "字幕风格",
    "packaging.smart_effect_style": "特效风格",
    "packaging.intro_asset_id": "片头素材",
    "packaging.outro_asset_id": "片尾素材",
    "packaging.insert_asset_id": "插片主素材",
    "packaging.insert_asset_ids": "插片素材池",
    "packaging.insert_selection_mode": "插片选择模式",
    "packaging.insert_position_mode": "插片位置模式",
    "packaging.watermark_asset_id": "水印素材",
    "packaging.music_asset_ids": "音乐素材池",
    "packaging.music_selection_mode": "音乐选择模式",
    "packaging.music_loop_mode": "音乐循环模式",
    "packaging.music_volume": "音乐音量",
    "packaging.watermark_position": "水印位置",
    "packaging.watermark_opacity": "水印透明度",
    "packaging.watermark_scale": "水印缩放",
    "packaging.avatar_overlay_position": "数字人画中画位置",
    "packaging.avatar_overlay_scale": "数字人画中画缩放",
    "packaging.avatar_overlay_corner_radius": "数字人圆角",
    "packaging.avatar_overlay_border_width": "数字人描边宽度",
    "packaging.avatar_overlay_border_color": "数字人描边颜色",
    "packaging.export_resolution_mode": "导出分辨率模式",
    "packaging.export_resolution_preset": "导出分辨率预设",
  };
  return knownLabels[key] ?? key;
}

export function formatDirtyValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "未设置";
  }
  if (typeof value === "boolean") {
    return value ? "开启" : "关闭";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => formatDirtyValue(item)).join(", ") : "空";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function formatDirtyDetailValue(key: string, value: unknown): string {
  if (key === "transcription_provider" && typeof value === "string") {
    return getTranscriptionProviderLabel(value);
  }
  return formatDirtyValue(value);
}

export function summarizeDirtyDetails(details: ConfigProfileDirtyDetail[]): string {
  return details
    .map((item) => `${formatDirtyKeyLabel(item.key)}: ${formatDirtyDetailValue(item.key, item.saved_value)} -> ${formatDirtyDetailValue(item.key, item.current_value)}`)
    .join("；");
}
