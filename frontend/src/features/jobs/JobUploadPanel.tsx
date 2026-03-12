import type { UploadForm } from "./constants";
import type { SelectOption } from "../../types";
import { SelectField } from "../../components/forms/SelectField";
import { PanelHeader } from "../../components/ui/PanelHeader";

type JobUploadPanelProps = {
  upload: UploadForm;
  languageOptions: SelectOption[];
  channelProfileOptions: SelectOption[];
  onChange: (next: UploadForm) => void;
  onSubmit: () => void;
  isSubmitting: boolean;
};

export function JobUploadPanel({
  upload,
  languageOptions,
  channelProfileOptions,
  onChange,
  onSubmit,
  isSubmitting,
}: JobUploadPanelProps) {
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
        <SelectField
          label="语言"
          value={upload.language}
          onChange={(event) => onChange({ ...upload, language: event.target.value })}
          options={languageOptions}
        />
        <SelectField
          label="频道配置"
          value={upload.channelProfile}
          onChange={(event) => onChange({ ...upload, channelProfile: event.target.value })}
          options={channelProfileOptions}
        />
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
