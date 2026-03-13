import { useQuery } from "@tanstack/react-query";

import { api } from "../../api";
import type { Config, ConfigOptions } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";

type CreativeSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  options?: ConfigOptions;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function CreativeSettingsPanel({ form, config, options, onChange }: CreativeSettingsPanelProps) {
  const avatarProviders = options?.avatar_providers ?? [{ value: "mock", label: "mock" }];
  const voiceProviders = options?.voice_providers ?? [{ value: "edge", label: "edge" }];
  const avatarMaterials = useQuery({ queryKey: ["avatar-materials", "settings"], queryFn: api.getAvatarMaterials });
  const presenterOptions = (avatarMaterials.data?.profiles ?? [])
    .flatMap((profile) =>
      (profile.files ?? [])
        .filter((file) => file.role === "speaking_video")
        .map((file) => ({
          value: file.path,
          label: `${profile.display_name} · ${file.original_name}`,
        })),
    )
    .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
  const selectedPresenter = presenterOptions.find((item) => item.value === String(form.avatar_presenter_id ?? ""));

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
          label="数字人训练 / 预处理 API Base URL"
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
          label="从数字人档案选择讲话视频模板"
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
            : "可以直接填写本地模板视频路径，也可以从上面的数字人档案里一键选用讲话视频片段。"}
        </div>
        <TextField
          label="数字人布局模板"
          value={String(form.avatar_layout_template ?? "")}
          onChange={(event) => onChange("avatar_layout_template", event.target.value)}
        />
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
            value={String(form.avatar_overlay_scale ?? 0.24)}
            onChange={(event) => onChange("avatar_overlay_scale", Number(event.target.value))}
          />
        </div>
        <SelectField
          label="语音 Provider"
          value={String(form.voice_provider ?? "")}
          onChange={(event) => onChange("voice_provider", event.target.value)}
          options={voiceProviders}
        />
        <TextField
          label="语音克隆 API Base URL"
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
          label="RunningHub 工作流 ID / Voice ID"
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
