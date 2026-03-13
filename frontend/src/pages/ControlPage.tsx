import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useControlWorkspace } from "../features/control/useControlWorkspace";
import { useI18n } from "../i18n";
import { formatDate } from "../utils";

export function ControlPage() {
  const { t } = useI18n();
  const workspace = useControlWorkspace();
  const lastChecked = workspace.status.data
    ? t("control.services.lastChecked").replace("{time}", formatDate(workspace.status.data.checked_at))
    : t("control.services.unavailable");

  return (
    <section>
      <PageHeader eyebrow={t("control.page.eyebrow")} title={t("control.page.title")} description={t("control.page.description")} />

      <div className="panel-grid two-up">
        <section className="panel">
          <PanelHeader title={t("control.services.title")} description={lastChecked} />
          <div className="service-grid">
            {Object.entries(workspace.status.data?.services ?? {}).map(([key, online]) => (
              <article key={key} className="service-card">
                <span>{key}</span>
                <strong className={online ? "status-ok" : "status-off"}>{online ? t("control.services.online") : t("control.services.offline")}</strong>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <PanelHeader title={t("control.stop.title")} description={t("control.stop.description")} />
          <label className="checkbox-row">
            <input type="checkbox" checked={workspace.stopDocker} onChange={(event) => workspace.setStopDocker(event.target.checked)} />
            <span>{t("control.stop.withDocker")}</span>
          </label>
          <div className="top-gap">
            <button className="button danger" onClick={() => workspace.stop.mutate()}>
              {t("control.stop.action")}
            </button>
          </div>
          {workspace.stop.data && (
            <div className="notice top-gap">
              <strong>{workspace.stop.data.status}</strong>
              <div>{workspace.stop.data.message}</div>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
