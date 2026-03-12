import { PageHeader } from "../components/ui/PageHeader";
import { ModelSettingsPanel } from "../features/settings/ModelSettingsPanel";
import { RuntimeSettingsPanel } from "../features/settings/RuntimeSettingsPanel";
import { useSettingsWorkspace } from "../features/settings/useSettingsWorkspace";

export function SettingsPage() {
  const workspace = useSettingsWorkspace();

  return (
    <section>
      <PageHeader
        eyebrow="Runtime Config"
        title="系统设置"
        description="页面层只保留配置装载和保存动作，字段展示已拆成独立设置区块。"
        actions={
          <>
            <button className="button ghost" onClick={() => workspace.reset.mutate()} disabled={workspace.reset.isPending}>
              {workspace.reset.isPending ? "重置中..." : "重置覆盖"}
            </button>
            <button className="button primary" onClick={() => workspace.save.mutate()} disabled={workspace.save.isPending}>
              {workspace.save.isPending ? "保存中..." : "保存配置"}
            </button>
          </>
        }
      />

      <div className="panel-grid two-up">
        <ModelSettingsPanel form={workspace.form} options={workspace.options.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
        <RuntimeSettingsPanel form={workspace.form} config={workspace.config.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
      </div>
    </section>
  );
}
