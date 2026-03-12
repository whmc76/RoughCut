import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useControlWorkspace } from "../features/control/useControlWorkspace";
import { formatDate } from "../utils";

export function ControlPage() {
  const workspace = useControlWorkspace();

  return (
    <section>
      <PageHeader eyebrow="Runtime" title="服务控制" description="保留最需要的操作：看状态、停止后台服务。" />

      <div className="panel-grid two-up">
        <section className="panel">
          <PanelHeader title="服务状态" description={workspace.status.data ? `最后检查：${formatDate(workspace.status.data.checked_at)}` : "尚未获取状态"} />
          <div className="service-grid">
            {Object.entries(workspace.status.data?.services ?? {}).map(([key, online]) => (
              <article key={key} className="service-card">
                <span>{key}</span>
                <strong className={online ? "status-ok" : "status-off"}>{online ? "在线" : "离线"}</strong>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <PanelHeader title="停止服务" description="停止后当前控制台可能会断开连接。" />
          <label className="checkbox-row">
            <input type="checkbox" checked={workspace.stopDocker} onChange={(event) => workspace.setStopDocker(event.target.checked)} />
            <span>同时停止 Docker 基础服务</span>
          </label>
          <div className="top-gap">
            <button className="button danger" onClick={() => workspace.stop.mutate()}>
              停止服务
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
