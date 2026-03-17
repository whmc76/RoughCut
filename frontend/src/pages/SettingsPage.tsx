import { PageHeader } from "../components/ui/PageHeader";
import { BotSettingsPanel } from "../features/settings/BotSettingsPanel";
import { CreativeSettingsPanel } from "../features/settings/CreativeSettingsPanel";
import { useI18n } from "../i18n";
import { ModelSettingsPanel } from "../features/settings/ModelSettingsPanel";
import { RuntimeSettingsPanel } from "../features/settings/RuntimeSettingsPanel";
import { useSettingsWorkspace } from "../features/settings/useSettingsWorkspace";

export function SettingsPage() {
  const { t } = useI18n();
  const workspace = useSettingsWorkspace();
  const saveTone =
    workspace.saveState === "saving" ? "running" : workspace.saveState === "error" ? "failed" : workspace.saveState === "saved" ? "done" : "";
  const saveLabel =
    workspace.saveState === "saving"
      ? t("autosave.saving")
      : workspace.saveState === "error"
        ? t("autosave.error")
        : workspace.saveState === "saved"
          ? t("autosave.saved")
          : t("autosave.idle");

  return (
    <section>
      <PageHeader
        eyebrow={t("settings.page.eyebrow")}
        title={t("settings.page.title")}
        description={t("settings.page.description")}
        actions={
          <>
            <button className="button ghost" onClick={() => workspace.reset.mutate()} disabled={workspace.reset.isPending}>
              {workspace.reset.isPending ? t("settings.page.resetting") : t("settings.page.reset")}
            </button>
            <span className={`status-pill ${saveTone}`}>{saveLabel}</span>
          </>
        }
      />
      {workspace.saveError && <div className="notice top-gap">{workspace.saveError}</div>}

      <div className="panel-grid two-up">
        <ModelSettingsPanel form={workspace.form} options={workspace.options.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
        <RuntimeSettingsPanel form={workspace.form} config={workspace.config.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
        <CreativeSettingsPanel
          form={workspace.form}
          config={workspace.config.data}
          options={workspace.options.data}
          onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))}
        />
        <BotSettingsPanel form={workspace.form} config={workspace.config.data} onChange={(key, value) => workspace.setForm((prev) => ({ ...prev, [key]: value }))} />
      </div>
    </section>
  );
}
