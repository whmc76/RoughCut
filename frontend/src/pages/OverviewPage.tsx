import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { StatCard } from "../components/ui/StatCard";
import { useOverviewWorkspace } from "../features/overview/useOverviewWorkspace";
import { formatDate, statusLabel } from "../utils";

export function OverviewPage() {
  const workspace = useOverviewWorkspace();

  return (
    <section>
      <PageHeader eyebrow="Console" title="系统概览" description="当前原型以 React 作为唯一 GUI 入口，后续页面会继续按模块拆分。" />

      <div className="stats-grid">
        <StatCard label="任务总数" value={workspace.stats.jobs} />
        <StatCard label="运行中任务" value={workspace.stats.running} />
        <StatCard label="监控目录" value={workspace.stats.watchRoots} />
        <StatCard label="术语规则" value={workspace.stats.glossary} />
      </div>

      <div className="panel-grid two-up">
        <section className="panel">
          <PanelHeader title="最近任务" description="直接从队列表拿最近状态，不再塞进单文件脚本里渲染。" actions={<Link className="text-link" to="/jobs">查看全部</Link>} />
          <div className="list-stack">
            {workspace.jobs.isLoading && <EmptyState message="正在加载任务..." />}
            {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
            {workspace.jobs.data?.slice(0, 6).map((job) => (
              <article key={job.id} className="list-card">
                <div>
                  <div className="row-title">{job.source_name}</div>
                  <div className="muted">{job.content_summary || job.content_subject || "暂无摘要"}</div>
                </div>
                <div className="row-meta">
                  <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                  <span>{formatDate(job.updated_at)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <PanelHeader title="服务状态" description="由 `/control/status` 轮询刷新。" actions={<Link className="text-link" to="/control">打开控制页</Link>} />
          <div className="service-grid">
            {Object.entries(workspace.services.data?.services ?? {}).map(([key, online]) => (
              <article key={key} className="service-card">
                <span>{key}</span>
                <strong className={online ? "status-ok" : "status-off"}>{online ? "在线" : "离线"}</strong>
              </article>
            ))}
            {!workspace.services.data && !workspace.services.isLoading && <EmptyState message="暂无服务数据" />}
          </div>
        </section>
      </div>
    </section>
  );
}
