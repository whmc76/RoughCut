import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
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
    <section className="page-stack">
      <PageHeader
        eyebrow={t("control.page.eyebrow")}
        title={t("control.page.title")}
        description={t("control.page.description")}
        summary={[
          { label: "先检查", value: "服务在线状态", detail: "确认异常是单点问题还是整体服务不可用" },
          { label: "再动作", value: "安全停机", detail: "停机入口独立放置，避免和日常管理动作混在一起" },
          { label: "适用场景", value: "排障与维护", detail: "这页不是高频操作页，重点是可靠和清晰" },
        ]}
      />

      <PageSection
        eyebrow="监控"
        title="先确认服务是否健康"
        description="服务状态单独成段，方便先判断故障范围，再决定是否需要停机。"
      >
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
      </PageSection>

      <PageSection
        eyebrow="维护"
        title="停机控制"
        description="停机操作单独放在后段，避免与状态查看混在同一块区域里误触。"
      >
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
      </PageSection>
    </section>
  );
}
