import type { Config } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { ANTHROPIC_AUTH_OPTIONS, OPENAI_AUTH_OPTIONS } from "./constants";

type RuntimeSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function RuntimeSettingsPanel({ form, config, onChange }: RuntimeSettingsPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title="运行参数" description="原型阶段优先保证直观可改，不做兼容层。" />
      <div className="form-stack">
        <TextField label="输出目录" value={String(form.output_dir ?? "")} onChange={(event) => onChange("output_dir", event.target.value)} />
        <TextField label="OpenAI Base URL" value={String(form.openai_base_url ?? "")} onChange={(event) => onChange("openai_base_url", event.target.value)} />
        <TextField label="OpenAI Key Helper" value={String(form.openai_api_key_helper ?? "")} onChange={(event) => onChange("openai_api_key_helper", event.target.value)} />
        <TextField
          label="OpenAI API Key"
          type="password"
          value={String(form.openai_api_key ?? "")}
          onChange={(event) => onChange("openai_api_key", event.target.value)}
          placeholder={config?.openai_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <SelectField
          label="OpenAI Auth 模式"
          value={String(form.openai_auth_mode ?? "")}
          onChange={(event) => onChange("openai_auth_mode", event.target.value)}
          options={OPENAI_AUTH_OPTIONS.map((option) => ({ value: option, label: option }))}
        />
        <TextField label="Anthropic Base URL" value={String(form.anthropic_base_url ?? "")} onChange={(event) => onChange("anthropic_base_url", event.target.value)} />
        <SelectField
          label="Anthropic Auth 模式"
          value={String(form.anthropic_auth_mode ?? "")}
          onChange={(event) => onChange("anthropic_auth_mode", event.target.value)}
          options={ANTHROPIC_AUTH_OPTIONS.map((option) => ({ value: option, label: option }))}
        />
        <TextField
          label="Anthropic Key Helper"
          value={String(form.anthropic_api_key_helper ?? "")}
          onChange={(event) => onChange("anthropic_api_key_helper", event.target.value)}
        />
        <TextField
          label="Anthropic API Key"
          type="password"
          value={String(form.anthropic_api_key ?? "")}
          onChange={(event) => onChange("anthropic_api_key", event.target.value)}
          placeholder={config?.anthropic_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <TextField label="MiniMax Base URL" value={String(form.minimax_base_url ?? "")} onChange={(event) => onChange("minimax_base_url", event.target.value)} />
        <TextField
          label="MiniMax API Key"
          type="password"
          value={String(form.minimax_api_key ?? "")}
          onChange={(event) => onChange("minimax_api_key", event.target.value)}
          placeholder={config?.minimax_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <TextField label="Ollama Base URL" value={String(form.ollama_base_url ?? "")} onChange={(event) => onChange("ollama_base_url", event.target.value)} />
        <TextField
          label="Ollama API Key"
          type="password"
          value={String(form.ollama_api_key ?? "")}
          onChange={(event) => onChange("ollama_api_key", event.target.value)}
          placeholder={config?.ollama_api_key_set ? "已设置，留空则不更新" : "留空则不更新"}
        />
        <div className="field-row">
          <TextField
            label="最大上传大小 MB"
            type="number"
            value={String(form.max_upload_size_mb ?? 2048)}
            onChange={(event) => onChange("max_upload_size_mb", Number(event.target.value))}
          />
          <TextField
            label="最长视频秒数"
            type="number"
            value={String(form.max_video_duration_sec ?? 7200)}
            onChange={(event) => onChange("max_video_duration_sec", Number(event.target.value))}
          />
        </div>
        <TextField
          label="FFmpeg 超时秒数"
          type="number"
          value={String(form.ffmpeg_timeout_sec ?? 600)}
          onChange={(event) => onChange("ffmpeg_timeout_sec", Number(event.target.value))}
        />
      </div>
    </section>
  );
}
