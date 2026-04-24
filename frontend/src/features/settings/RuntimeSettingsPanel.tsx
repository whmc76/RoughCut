import type { Config, ProviderServiceStatus, RuntimeEnvironment } from "../../types";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { SettingsForm } from "./constants";
import { getProviderStatusLabel } from "./helpers";

const DEFAULT_OUTPUT_DIR = "output";

type RuntimeSettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  runtimeEnvironment?: RuntimeEnvironment;
  serviceStatus?: ProviderServiceStatus;
  onChange: (key: string, value: string | number | boolean) => void;
};

function getServiceSummary(serviceStatus?: ProviderServiceStatus) {
  const entries = Object.values(serviceStatus?.services ?? {});
  if (!entries.length) {
    return "还没有服务状态";
  }
  const okCount = entries.filter((entry) => entry.status === "ok" || entry.status === "configured").length;
  return `${okCount} / ${entries.length} 条链路可用`;
}

export function RuntimeSettingsPanel({ form, runtimeEnvironment, serviceStatus, onChange }: RuntimeSettingsPanelProps) {
  const maxUploadSizeMb = Number(form.max_upload_size_mb ?? 2048);
  const maxVideoDurationSec = Number(form.max_video_duration_sec ?? 7200);
  const ffmpegTimeoutSec = Number(form.ffmpeg_timeout_sec ?? 600);
  const transcribeRuntimeTimeoutSec = Number(form.transcribe_runtime_timeout_sec ?? 900);
  const transcriptionChunkingEnabled = Boolean(form.transcription_chunking_enabled ?? true);
  const transcriptionChunkThresholdSec = Number(form.transcription_chunk_threshold_sec ?? 600);
  const transcriptionChunkSizeSec = Number(form.transcription_chunk_size_sec ?? 60);
  const transcriptionChunkMinSec = Number(form.transcription_chunk_min_sec ?? 20);
  const transcriptionChunkOverlapSec = Number(form.transcription_chunk_overlap_sec ?? 1.5);
  const transcriptionChunkRequestTimeoutSec = Number(form.transcription_chunk_request_timeout_sec ?? 180);
  const localServiceCards = [
    {
      key: "local_http_asr",
      title: String(form.local_asr_display_name ?? "本地 HTTP ASR"),
      baseUrl: String(form.local_asr_api_base_url ?? ""),
      status: serviceStatus?.services.local_http_asr?.status ?? "not_configured",
      detail: serviceStatus?.services.local_http_asr?.error ?? "本地转写服务",
    },
    {
      key: "ollama",
      title: "Ollama",
      baseUrl: String(runtimeEnvironment?.ollama_base_url ?? ""),
      status: serviceStatus?.services.ollama?.status ?? "not_configured",
      detail: serviceStatus?.services.ollama?.error ?? "本地推理服务",
    },
    {
      key: "avatar",
      title: "数字人服务",
      baseUrl: String(runtimeEnvironment?.avatar_api_base_url ?? ""),
      status: runtimeEnvironment?.avatar_api_base_url ? "configured" : "not_configured",
      detail: runtimeEnvironment?.avatar_api_base_url ? "运行环境已提供地址" : "未设置地址",
    },
    {
      key: "voice",
      title: "语音服务",
      baseUrl: String(runtimeEnvironment?.voice_clone_api_base_url ?? ""),
      status: runtimeEnvironment?.voice_clone_api_base_url ? "configured" : "not_configured",
      detail: runtimeEnvironment?.voice_clone_api_base_url ? "运行环境已提供地址" : "未设置地址",
    },
  ];
  const environmentRows = [
    ["OpenAI", `${String(runtimeEnvironment?.openai_base_url ?? "未设置")} · ${String(runtimeEnvironment?.openai_auth_mode ?? "api_key")}`],
    ["Anthropic", `${String(runtimeEnvironment?.anthropic_base_url ?? "未设置")} · ${String(runtimeEnvironment?.anthropic_auth_mode ?? "api_key")}`],
    ["MiniMax", `${String(runtimeEnvironment?.minimax_base_url ?? "未设置")} · Host ${String(runtimeEnvironment?.minimax_api_host ?? "未设置")}`],
    ["输出目录", String(runtimeEnvironment?.output_dir ?? DEFAULT_OUTPUT_DIR)],
  ];

  return (
    <section className="panel settings-runtime-panel">
      <PanelHeader title="运行环境" description="检查本地服务、环境地址和上传限制。" />
      <div className="settings-runtime-grid">
        <article className="settings-runtime-summary-card">
          <span className="settings-overview-label">服务</span>
          <strong>{getServiceSummary(serviceStatus)}</strong>
          <div className="muted">当前输出目录：{String(runtimeEnvironment?.output_dir ?? DEFAULT_OUTPUT_DIR)}</div>
          <div className="muted">
            上传 {maxUploadSizeMb} MB · 视频 {maxVideoDurationSec} 秒 · FFmpeg {ffmpegTimeoutSec} 秒 · 转写 {transcribeRuntimeTimeoutSec} 秒
          </div>
        </article>
      </div>

      <div className="settings-service-card-grid">
        {localServiceCards.map((service) => (
          <article key={service.key} className="settings-service-card">
            <div className="settings-provider-card-head">
              <div>
                <span className="settings-overview-label">本地 / 环境服务</span>
                <strong>{service.title}</strong>
              </div>
              <span className={`status-pill ${service.status === "ok" || service.status === "configured" ? "done" : service.status === "not_configured" ? "" : "failed"}`}>
                {getProviderStatusLabel(service.status)}
              </span>
            </div>
            <div className="muted">{service.detail}</div>
            <div className="muted">{service.baseUrl || "未设置地址"}</div>
          </article>
        ))}
      </div>

      <div className="settings-environment-grid">
        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">环境地址</span>
              <strong>地址</strong>
            </div>
          </div>
          <div className="settings-environment-list">
            {environmentRows.map(([label, value]) => (
              <div key={label} className="settings-environment-row">
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">执行限制</span>
              <strong>上传与 FFmpeg</strong>
            </div>
          </div>
          <div className="settings-chain-card-body form-grid three-up">
            <TextField
              label="最大上传大小 MB"
              type="number"
              value={String(maxUploadSizeMb)}
              onChange={(event) => onChange("max_upload_size_mb", Number(event.target.value))}
            />
            <TextField
              label="最长视频秒数"
              type="number"
              value={String(maxVideoDurationSec)}
              onChange={(event) => onChange("max_video_duration_sec", Number(event.target.value))}
            />
            <TextField
              label="FFmpeg 超时秒数"
              type="number"
              value={String(ffmpegTimeoutSec)}
              onChange={(event) => onChange("ffmpeg_timeout_sec", Number(event.target.value))}
            />
            <TextField
              label="转写运行时超时秒数"
              type="number"
              value={String(transcribeRuntimeTimeoutSec)}
              onChange={(event) => onChange("transcribe_runtime_timeout_sec", Number(event.target.value))}
            />
          </div>
        </section>

        <section className="settings-chain-card">
          <div className="settings-chain-card-head">
            <div>
              <span className="settings-overview-label">长音频分块</span>
              <strong>Chunked ASR</strong>
            </div>
          </div>
          <div className="settings-chain-card-body">
            <CheckboxField
              label="超过阈值后启用分块转写"
              checked={transcriptionChunkingEnabled}
              onChange={(event) => onChange("transcription_chunking_enabled", event.target.checked)}
            />
            <div className="form-grid three-up">
              <TextField
                label="分块阈值秒数"
                type="number"
                value={String(transcriptionChunkThresholdSec)}
                onChange={(event) => onChange("transcription_chunk_threshold_sec", Number(event.target.value))}
              />
              <TextField
                label="单块长度秒数"
                type="number"
                value={String(transcriptionChunkSizeSec)}
                onChange={(event) => onChange("transcription_chunk_size_sec", Number(event.target.value))}
              />
              <TextField
                label="最小块长度秒数"
                type="number"
                value={String(transcriptionChunkMinSec)}
                onChange={(event) => onChange("transcription_chunk_min_sec", Number(event.target.value))}
              />
              <TextField
                label="块间重叠秒数"
                type="number"
                value={String(transcriptionChunkOverlapSec)}
                onChange={(event) => onChange("transcription_chunk_overlap_sec", Number(event.target.value))}
              />
              <TextField
                label="单块请求超时秒数"
                type="number"
                value={String(transcriptionChunkRequestTimeoutSec)}
                onChange={(event) => onChange("transcription_chunk_request_timeout_sec", Number(event.target.value))}
              />
            </div>
          </div>
        </section>
      </div>
    </section>
  );
}
