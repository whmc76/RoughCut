import type { GlossaryTerm } from "../../types";
import { FormActions } from "../../components/forms/FormActions";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { TermForm } from "./constants";

type GlossaryFormPanelProps = {
  editing: GlossaryTerm | null;
  form: TermForm;
  isSaving: boolean;
  onChange: (next: TermForm) => void;
  onSubmit: () => void;
  onReset: () => void;
};

export function GlossaryFormPanel({ editing, form, isSaving, onChange, onSubmit, onReset }: GlossaryFormPanelProps) {
  return (
    <section className="panel">
      <PanelHeader title={editing ? "编辑术语" : "新增术语"} description="错误写法用逗号分隔。" actions={editing ? <button className="button ghost" onClick={onReset}>取消编辑</button> : undefined} />

      <div className="form-stack">
        <TextField label="错误写法" value={form.wrong_forms} onChange={(event) => onChange({ ...form, wrong_forms: event.target.value })} placeholder="GPT4, gpt4" />
        <TextField label="正确写法" value={form.correct_form} onChange={(event) => onChange({ ...form, correct_form: event.target.value })} placeholder="GPT-4" />
        <SelectField
          label="类别"
          value={form.category}
          onChange={(event) => onChange({ ...form, category: event.target.value })}
          options={[
            { value: "", label: "未设置" },
            { value: "brand", label: "品牌" },
            { value: "model", label: "型号" },
            { value: "tech_term", label: "技术术语" },
            { value: "person", label: "人名" },
          ]}
        />
        <TextField
          label="上下文提示"
          value={form.context_hint}
          onChange={(event) => onChange({ ...form, context_hint: event.target.value })}
          placeholder="只在数码开箱里使用"
        />
        <FormActions>
          <button className="button primary" onClick={onSubmit} disabled={isSaving}>
            {isSaving ? "保存中..." : editing ? "保存修改" : "新增术语"}
          </button>
        </FormActions>
      </div>
    </section>
  );
}
