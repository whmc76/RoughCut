import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api";
import type { Config, ConfigOptions } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";

const AVATAR_POSITION_SCHEMES = [
  {
    value: "subtitle_safe_top_left",
    label: "避字幕左上",
    position: "top_left",
    safeMargin: 0.1,
    note: "优先避开底部常见字幕区域，适合绝大多数竖版口播。",
  },
  {
    value: "brand_safe_top_right",
    label: "品牌信息右上",
    position: "top_right",
    safeMargin: 0.1,
    note: "保留下方字幕空间，适合左侧主体较强的画面。",
  },
  {
    value: "host_safe_bottom_left",
    label: "人物访谈左下",
    position: "bottom_left",
    safeMargin: 0.08,
    note: "适合右侧有主商品或主讲人的镜头。",
  },
  {
    value: "default_bottom_right",
    label: "常规右下",
    position: "bottom_right",
    safeMargin: 0.08,
    note: "常规画中画布局，适合横版或字幕较轻的内容。",
  },
] as const;

const AVATAR_SIZE_SCHEMES = [
  {
    value: "light",
    label: "轻量",
    scale: 0.18,
    note: "数字人存在感更弱，优先保主画面。",
  },
  {
    value: "balanced",
    label: "平衡",
    scale: 0.22,
    note: "默认推荐，兼顾可见性和主画面完整性。",
  },
  {
    value: "focus",
    label: "强存在感",
    scale: 0.26,
    note: "适合解说主导的内容，但更容易压缩主画面空间。",
  },
] as const;

type CreativeSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  options?: ConfigOptions;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function CreativeSettingsPanel({ form, config, options, onChange }: CreativeSettingsPanelProps) {
  const queryClient = useQueryClient();
  const avatarProviders = options?.avatar_providers ?? [{ value: "heygem", label: "heygem" }];
  const voiceProviders = options?.voice_providers ?? [{ value: "indextts2", label: "indextts2" }];
  const avatarMaterials = useQuery({ queryKey: ["avatar-materials", "settings"], queryFn: api.getAvatarMaterials });
  const packaging = useQuery({ queryKey: ["packaging"], queryFn: api.getPackaging });
  const savePackagingConfig = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.patchPackagingConfig(body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["packaging"] });
    },
  });
  const presenterOptions = (avatarMaterials.data?.profiles ?? [])
    .flatMap((profile) =>
      (profile.files ?? [])
        .filter((file) => file.role === "speaking_video")
        .map((file) => ({
          value: file.path,
          label: [
            profile.creator_profile?.identity?.public_name || profile.display_name,
            profile.creator_profile?.identity?.title,
            profile.creator_profile?.publishing?.primary_platform,
            file.original_name,
          ]
            .filter(Boolean)
            .join(" · "),
        })),
    )
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
  const selectedPresenter = presenterOptions.find((item) => item.value === String(form.avatar_presenter_id ?? ""));
  const packagingConfig = packaging.data?.config;
  const currentOverlayPosition = String(packagingConfig?.avatar_overlay_position ?? "top_left");
  const currentOverlayScale = Number(packagingConfig?.avatar_overlay_scale ?? form.avatar_overlay_scale ?? 0.22);
  const currentOverlayCornerRadius = Number(packagingConfig?.avatar_overlay_corner_radius ?? 26);
  const currentOverlayBorderWidth = Number(packagingConfig?.avatar_overlay_border_width ?? 4);
  const currentOverlayBorderColor = String(packagingConfig?.avatar_overlay_border_color ?? "#F4E4B8");
  const selectedPositionScheme =
    AVATAR_POSITION_SCHEMES.find(
      (item) =>
        item.position === currentOverlayPosition &&
        Math.abs(item.safeMargin - Number(form.avatar_safe_margin ?? 0.08)) < 0.001,
    )?.value ?? "";
  const selectedSizeScheme =
    AVATAR_SIZE_SCHEMES.find((item) => Math.abs(item.scale - currentOverlayScale) < 0.001)?.value ?? "";

  const handlePositionSchemeChange = (value: string) => {
    const scheme = AVATAR_POSITION_SCHEMES.find((item) => item.value === value);
    if (!scheme) return;
    onChange("avatar_safe_margin", scheme.safeMargin);
    savePackagingConfig.mutate({ avatar_overlay_position: scheme.position });
  };

  const handleSizeSchemeChange = (value: string) => {
    const scheme = AVATAR_SIZE_SCHEMES.find((item) => item.value === value);
    if (!scheme) return;
    onChange("avatar_overlay_scale", scheme.scale);
    savePackagingConfig.mutate({ avatar_overlay_scale: scheme.scale });
  };

  return (
    <section className="panel">
      <PanelHeader title="增强能力 Provider" description="数字人解说和 AI 导演的执行入口先接成可配置 provider。" />
      <div className="form-stack">
        <SelectField
          label="数字人 Provider"
          value={String(form.avatar_provider ?? "")}
          onChange={(event) => onChange("avatar_provider", event.target.value)}
          options={avatarProviders}
        />
        <TextField
          label="数字人 API Base URL"
          value={String(form.avatar_api_base_url ?? "")}
          onChange={(event) => onChange("avatar_api_base_url", event.target.value)}
        />
        <TextField
          label="数字人口播参考音频 / TTS API Base URL"
          value={String(form.avatar_training_api_base_url ?? "")}
          onChange={(event) => onChange("avatar_training_api_base_url", event.target.value)}
        />
        <TextField
          label="数字人 API Key"
          type="password"
          value={String(form.avatar_api_key ?? "")}
          onChange={(event) => onChange("avatar_api_key", event.target.value)}
          placeholder={config?.avatar_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <SelectField
          label="从创作者档案选择讲话视频模板"
          value={selectedPresenter?.value ?? ""}
          onChange={(event) => onChange("avatar_presenter_id", event.target.value)}
          options={[
            { value: "", label: presenterOptions.length ? "手动填写模板路径" : "暂无可选模板" },
            ...presenterOptions,
          ]}
        />
        <TextField
          label="数字人模板视频 / 形象标识"
          value={String(form.avatar_presenter_id ?? "")}
          onChange={(event) => onChange("avatar_presenter_id", event.target.value)}
        />
        <div className="muted">
          {selectedPresenter
            ? `当前已选模板：${selectedPresenter.label}`
            : "可以直接填写本地模板视频路径，也可以从上面的创作者档案里一键选用讲话视频片段。"}
        </div>
        <TextField
          label="数字人布局模板"
          value={String(form.avatar_layout_template ?? "")}
          onChange={(event) => onChange("avatar_layout_template", event.target.value)}
        />
        <SelectField
          label="数字人解说定位方案"
          value={selectedPositionScheme}
          onChange={(event) => handlePositionSchemeChange(event.target.value)}
          options={[
            { value: "", label: "自定义位置" },
            ...AVATAR_POSITION_SCHEMES.map((item) => ({ value: item.value, label: item.label })),
          ]}
        />
        <div className="muted">
          {AVATAR_POSITION_SCHEMES.find((item) => item.value === selectedPositionScheme)?.note ??
            `当前使用自定义位置：${currentOverlayPosition}，字幕安全边距 ${Number(form.avatar_safe_margin ?? 0.08).toFixed(2)}。`}
        </div>
        <SelectField
          label="数字人解说尺寸方案"
          value={selectedSizeScheme}
          onChange={(event) => handleSizeSchemeChange(event.target.value)}
          options={[
            { value: "", label: "自定义尺寸" },
            ...AVATAR_SIZE_SCHEMES.map((item) => ({ value: item.value, label: item.label })),
          ]}
        />
        <div className="muted">
          {AVATAR_SIZE_SCHEMES.find((item) => item.value === selectedSizeScheme)?.note ??
            `当前使用自定义尺寸：${Math.round(currentOverlayScale * 100)}%。`}
        </div>
        <div className="field-row">
          <TextField
            label="字幕安全边距"
            type="number"
            value={String(form.avatar_safe_margin ?? 0.08)}
            onChange={(event) => onChange("avatar_safe_margin", Number(event.target.value))}
          />
          <TextField
            label="数字人缩放比"
            type="number"
            value={String(currentOverlayScale)}
            onChange={(event) => {
              const value = Number(event.target.value);
              onChange("avatar_overlay_scale", value);
              savePackagingConfig.mutate({ avatar_overlay_scale: value });
            }}
          />
        </div>
        <div className="field-row">
          <TextField
            label="数字人圆角"
            type="number"
            value={String(currentOverlayCornerRadius)}
            onChange={(event) => {
              const value = Number(event.target.value);
              savePackagingConfig.mutate({ avatar_overlay_corner_radius: value });
            }}
          />
          <TextField
            label="数字人边框宽度"
            type="number"
            value={String(currentOverlayBorderWidth)}
            onChange={(event) => {
              const value = Number(event.target.value);
              savePackagingConfig.mutate({ avatar_overlay_border_width: value });
            }}
          />
        </div>
        <TextField
          label="数字人边框颜色"
          value={currentOverlayBorderColor}
          onChange={(event) => savePackagingConfig.mutate({ avatar_overlay_border_color: event.target.value })}
        />
        <div className="muted">圆角和边框会直接进入成片画中画渲染，不是预览样式。</div>
        <SelectField
          label="语音 Provider"
          value={String(form.voice_provider ?? "")}
          onChange={(event) => onChange("voice_provider", event.target.value)}
          options={voiceProviders}
        />
        <TextField
          label="语音合成 API Base URL"
          value={String(form.voice_clone_api_base_url ?? "")}
          onChange={(event) => onChange("voice_clone_api_base_url", event.target.value)}
        />
        <TextField
          label="语音克隆 API Key"
          type="password"
          value={String(form.voice_clone_api_key ?? "")}
          onChange={(event) => onChange("voice_clone_api_key", event.target.value)}
          placeholder={config?.voice_clone_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <TextField
          label="RunningHub 工作流 ID / Voice ID（仅 RunningHub）"
          value={String(form.voice_clone_voice_id ?? "")}
          onChange={(event) => onChange("voice_clone_voice_id", event.target.value)}
        />
        <TextField
          label="AI 导演改写强度"
          type="number"
          value={String(form.director_rewrite_strength ?? 0.55)}
          onChange={(event) => onChange("director_rewrite_strength", Number(event.target.value))}
        />
      </div>
    </section>
  );
}
