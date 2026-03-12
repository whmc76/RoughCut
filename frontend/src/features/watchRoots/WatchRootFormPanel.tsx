import type { RootForm } from "./constants";
import { CheckboxField } from "../../components/forms/CheckboxField";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import type { SelectOption } from "../../types";
import { PanelHeader } from "../../components/ui/PanelHeader";

type WatchRootFormPanelProps = {
  form: RootForm;
  channelProfileOptions: SelectOption[];
  isEditing: boolean;
  isSaving: boolean;
  isDeleting: boolean;
  onChange: (next: RootForm) => void;
  onSubmit: () => void;
  onDelete: () => void;
};

export function WatchRootFormPanel({
  form,
  channelProfileOptions,
  isEditing,
  isSaving,
  isDeleting,
  onChange,
  onSubmit,
  onDelete,
}: WatchRootFormPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title={isEditing ? "编辑目录" : "创建目录"} description="支持直接切换快速扫描 / 精确扫描。" />
      <form
        className="form-stack"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <TextField label="目录路径" value={form.path} onChange={(event) => onChange({ ...form, path: event.target.value })} />
        <SelectField
          label="频道配置"
          value={form.channel_profile}
          onChange={(event) => onChange({ ...form, channel_profile: event.target.value })}
          options={channelProfileOptions}
        />
        <div className="field-row">
          <SelectField
            label="扫描模式"
            value={form.scan_mode}
            onChange={(event) => onChange({ ...form, scan_mode: event.target.value as RootForm["scan_mode"] })}
            options={[
              { value: "fast", label: "fast" },
              { value: "precise", label: "precise" },
            ]}
          />
          <CheckboxField label="启用监听" checked={form.enabled} onChange={(event) => onChange({ ...form, enabled: event.target.checked })} />
        </div>
        <FormActions>
          <button className="button primary" type="submit" disabled={isSaving}>
            {isSaving ? "保存中..." : isEditing ? "保存修改" : "创建目录"}
          </button>
          {isEditing && (
            <button className="button danger" type="button" onClick={onDelete} disabled={isDeleting}>
              {isDeleting ? "删除中..." : "删除"}
            </button>
          )}
        </FormActions>
      </form>
    </section>
  );
}
