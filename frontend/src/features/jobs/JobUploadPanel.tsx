import type { UploadForm } from "./constants";
import { PanelHeader } from "../../components/ui/PanelHeader";

type JobUploadPanelProps = {
  upload: UploadForm;
  onChange: (next: UploadForm) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
};

export function JobUploadPanel({ upload, onChange, onSubmit, isSubmitting }: JobUploadPanelProps) {
  return (
    <section className="panel top-gap">
      <PanelHeader title="新建任务" description="直接上传原视频创建任务。" />
      <div className="form-grid three-up">
        <label>
          <span>视频文件</span>
          <input
            className="input"
            type="file"
            accept="video/*"
            onChange={(event) => onChange({ ...upload, file: event.target.files?.[0] ?? null })}
          />
        </label>
        <label>
          <span>语言</span>
          <input className="input" value={upload.language} onChange={(event) => onChange({ ...upload, language: event.target.value })} />
        </label>
        <label>
          <span>频道配置</span>
          <input
            className="input"
            value={upload.channelProfile}
            onChange={(event) => onChange({ ...upload, channelProfile: event.target.value })}
            placeholder="如 edc_tactical"
          />
        </label>
      </div>
      <div className="toolbar top-gap">
        <button className="button primary" disabled={!upload.file || isSubmitting} onClick={onSubmit}>
          {isSubmitting ? "正在创建..." : "上传并创建任务"}
        </button>
        {upload.file && <span className="muted">{upload.file.name}</span>}
      </div>
    </section>
  );
}
