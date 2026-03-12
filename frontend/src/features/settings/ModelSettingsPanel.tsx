import type { ConfigOptions } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { LLM_MODE_OPTIONS, REASONING_PROVIDER_OPTIONS } from "./constants";

type ModelSettingsPanelProps = {
  form: SettingsForm;
  options?: ConfigOptions;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function ModelSettingsPanel({ form, options, onChange }: ModelSettingsPanelProps) {
  const transcriptionModels = options?.transcription_models?.[String(form.transcription_provider)] ?? [];

  return (
    <section className="panel">
      <PanelHeader title="转写与推理" description="配置立即写入 `roughcut_config.json`。" />
      <div className="form-stack">
        <SelectField
          label="转写 Provider"
          value={String(form.transcription_provider ?? "")}
          onChange={(event) => onChange("transcription_provider", event.target.value)}
          options={Object.keys(options?.transcription_models ?? {}).map((provider) => ({ value: provider, label: provider }))}
        />
        <SelectField
          label="转写模型"
          value={String(form.transcription_model ?? "")}
          onChange={(event) => onChange("transcription_model", event.target.value)}
          options={transcriptionModels.map((model) => ({ value: model, label: model }))}
        />
        <SelectField
          label="LLM 模式"
          value={String(form.llm_mode ?? "")}
          onChange={(event) => onChange("llm_mode", event.target.value)}
          options={LLM_MODE_OPTIONS.map((mode) => ({ value: mode, label: mode }))}
        />
        <SelectField
          label="推理 Provider"
          value={String(form.reasoning_provider ?? "")}
          onChange={(event) => onChange("reasoning_provider", event.target.value)}
          options={REASONING_PROVIDER_OPTIONS.map((provider) => ({ value: provider, label: provider }))}
        />
        <TextField label="推理模型" value={String(form.reasoning_model ?? "")} onChange={(event) => onChange("reasoning_model", event.target.value)} />
        <TextField label="本地推理模型" value={String(form.local_reasoning_model ?? "")} onChange={(event) => onChange("local_reasoning_model", event.target.value)} />
        <TextField label="本地视觉模型" value={String(form.local_vision_model ?? "")} onChange={(event) => onChange("local_vision_model", event.target.value)} />
        <TextField
          label="视觉回退 Provider"
          value={String(form.multimodal_fallback_provider ?? "")}
          onChange={(event) => onChange("multimodal_fallback_provider", event.target.value)}
        />
        <TextField
          label="视觉回退模型"
          value={String(form.multimodal_fallback_model ?? "")}
          onChange={(event) => onChange("multimodal_fallback_model", event.target.value)}
        />
        <TextField label="搜索 Provider" value={String(form.search_provider ?? "")} onChange={(event) => onChange("search_provider", event.target.value)} />
        <TextField
          label="搜索回退 Provider"
          value={String(form.search_fallback_provider ?? "")}
          onChange={(event) => onChange("search_fallback_provider", event.target.value)}
        />
        <TextField
          label="搜索辅助模型"
          value={String(form.model_search_helper ?? "")}
          onChange={(event) => onChange("model_search_helper", event.target.value)}
        />
      </div>
    </section>
  );
}
