import { Link } from "react-router-dom";

import { EmptyState } from "../components/ui/EmptyState";
import { useOverviewWorkspace } from "../features/overview/useOverviewWorkspace";
import { classNames, formatDate, statusLabel } from "../utils";

function renderRuntimeTone(status: string | undefined) {
  return status === "ready" || status === "held" || status === "free" ? "status-ok" : "status-off";
}

function formatCompactNumber(value: number | undefined) {
  if (!value) return "0";
  if (value >= 10000) return `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万`;
  return value.toLocaleString();
}

export function OverviewPage() {
  const workspace = useOverviewWorkspace();
  const jobs = workspace.jobs.data ?? [];
  const watchRoots = workspace.watchRoots.data ?? [];
  const runtime = workspace.services.data?.runtime;
  const serviceEntries = Object.entries(workspace.services.data?.services ?? {});
  const onlineServices = serviceEntries.filter(([, online]) => online);
  const blockedServices = serviceEntries.filter(([, online]) => !online);
  const runningJobs = jobs.filter((job) => job.status === "running" || job.status === "processing");
  const reviewJobs = jobs.filter((job) => job.status === "needs_review" || job.awaiting_manual_edit);
  const failedJobs = jobs.filter((job) => job.status === "failed");
  const activeJobs = jobs
    .filter((job) =>
      ["running", "processing", "needs_review", "queued", "pending", "awaiting_init", "awaiting_manual_edit"].includes(job.status),
    )
    .slice(0, 4);
  const enabledRoots = watchRoots.filter((root) => root.enabled);
  const publishReadyJobs = jobs.filter((job) => job.status === "done" || job.publication_status === "ready");
  const totalTokens = workspace.usageSummary.data?.total_tokens ?? 0;
  const cacheHitRate = workspace.usageSummary.data?.cache.hit_rate ?? 0;
  const servicePercent = serviceEntries.length ? Math.round((onlineServices.length / serviceEntries.length) * 100) : 0;
  const attentionCount = reviewJobs.length + failedJobs.length + blockedServices.length;
  const topSteps = workspace.usageSummary.data?.top_steps.slice(0, 3) ?? [];
  const topModels = workspace.usageSummary.data?.top_models.slice(0, 2) ?? [];
  const primaryTitle = blockedServices.length
    ? "服务需要处理"
    : reviewJobs.length
      ? `${reviewJobs.length} 项等待确认`
      : runningJobs.length
        ? `${runningJobs.length} 项正在处理`
        : "系统待命";
  const primaryLead = blockedServices.length
    ? "先恢复离线服务，再继续投递任务。"
    : reviewJobs.length
      ? "优先进入剪辑工作台处理审核和手动调整。"
      : runningJobs.length
        ? "队列正在推进，可以继续观察产出和服务负载。"
        : "没有阻塞项，可以从四个入口继续工作。";
  const commandEntries = [
    {
      to: "/jobs",
      label: "剪辑",
      eyebrow: "Edit",
      metric: reviewJobs.length ? `${reviewJobs.length} 待审` : `${runningJobs.length} 运行`,
      description: "任务队列、审核、手动精修和成片下载。",
      tone: "is-primary",
    },
    {
      to: "/watch-roots",
      label: "自动",
      eyebrow: "Auto",
      metric: `${enabledRoots.length}/${watchRoots.length}`,
      description: "目录监听、入库模式和自动任务库存。",
      tone: "",
    },
    {
      to: "/intelligent-copy",
      label: "发布",
      eyebrow: "Publish",
      metric: `${publishReadyJobs.length} 可用`,
      description: "标题、平台文案、发布包和内容复用。",
      tone: "",
    },
    {
      to: "/tools",
      label: "百宝箱",
      eyebrow: "Tools",
      metric: `${onlineServices.length} 在线`,
      description: "ASR、TTS、数字人和临时处理工具。",
      tone: "",
    },
  ];

  return (
    <section className="page-stack overview-page control-center-page" data-testid="overview-command-center">
      <header className="control-center-hero">
        <div className="control-center-hero-copy">
          <span className="control-center-kicker">RoughCut Monitor</span>
          <h2>{primaryTitle}</h2>
          <p>{primaryLead}</p>
        </div>
        <div className="control-center-live-strip" aria-label="核心状态">
          <article>
            <span>总任务</span>
            <strong>{workspace.stats.jobs}</strong>
          </article>
          <article>
            <span>待处理</span>
            <strong>{attentionCount}</strong>
          </article>
          <article>
            <span>自动目录</span>
            <strong>{enabledRoots.length}</strong>
          </article>
          <article>
            <span>服务在线</span>
            <strong>{serviceEntries.length ? `${servicePercent}%` : "—"}</strong>
          </article>
        </div>
      </header>

      <main className="control-center-grid">
        <section className="control-center-entry-zone" aria-label="四大入口">
          {commandEntries.map((entry, index) => (
            <Link key={entry.to} className={classNames("control-center-entry", entry.tone)} to={entry.to}>
              <span className="control-center-entry-index">{`0${index + 1}`}</span>
              <span className="control-center-entry-eyebrow">{entry.eyebrow}</span>
              <strong>{entry.label}</strong>
              <p>{entry.description}</p>
              <span className="control-center-entry-metric">{entry.metric}</span>
            </Link>
          ))}
        </section>

        <section className="control-center-queue-panel">
          <div className="control-center-panel-head">
            <span>当前队列</span>
            <strong>{activeJobs.length}</strong>
          </div>
          {workspace.jobs.isLoading && <EmptyState message="正在加载任务。" />}
          {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
          {!workspace.jobs.isLoading && !workspace.jobs.isError && activeJobs.length === 0 ? (
            <EmptyState message="当前没有需要处理的任务。" />
          ) : null}
          <div className="control-center-queue-list">
            {activeJobs.map((job, index) => (
              <article key={job.id} className="control-center-queue-row">
                <span>{`${index + 1}`.padStart(2, "0")}</span>
                <div>
                  <strong>{job.source_name}</strong>
                  <p>{job.content_summary || job.content_subject || "暂无摘要"}</p>
                </div>
                <div className="control-center-queue-meta">
                  <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                  <small>{formatDate(job.updated_at)}</small>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="control-center-side-panel">
          <section className="control-center-health">
            <div className="control-center-panel-head">
              <span>运行健康</span>
              <strong>{blockedServices.length ? `${blockedServices.length} 异常` : "正常"}</strong>
            </div>
            <div className="control-center-pressure">
              <div>
                <span>在线服务</span>
                <strong>{onlineServices.length}/{serviceEntries.length || 0}</strong>
              </div>
              <meter min="0" max="100" value={servicePercent} />
            </div>
            <div className="control-center-service-list">
              {serviceEntries.slice(0, 5).map(([key, online]) => (
                <article key={key}>
                  <span>{key}</span>
                  <strong className={online ? "status-ok" : "status-off"}>{online ? "在线" : "离线"}</strong>
                </article>
              ))}
              {runtime?.readiness_status ? (
                <article>
                  <span>运行就绪</span>
                  <strong className={renderRuntimeTone(runtime.readiness_status)}>{runtime.readiness_status}</strong>
                </article>
              ) : null}
            </div>
          </section>

          <section className="control-center-telemetry">
            <div className="control-center-panel-head">
              <span>资源用量</span>
              <strong>{formatCompactNumber(totalTokens)}</strong>
            </div>
            <div className="control-center-usage-grid">
              <article>
                <span>调用</span>
                <strong>{formatCompactNumber(workspace.usageSummary.data?.total_calls)}</strong>
              </article>
              <article>
                <span>缓存</span>
                <strong>{Math.round(cacheHitRate * 100)}%</strong>
              </article>
            </div>
            <div className="control-center-mini-list">
              {topSteps.map((step) => (
                <div key={step.step_name}>
                  <span>{step.label}</span>
                  <strong>{formatCompactNumber(step.total_tokens)}</strong>
                </div>
              ))}
              {topSteps.length === 0 && topModels.length === 0 ? <p>暂无 telemetry。</p> : null}
              {topModels.map((model) => (
                <div key={model.model}>
                  <span>{model.model}</span>
                  <strong>{formatCompactNumber(model.total_tokens)}</strong>
                </div>
              ))}
            </div>
          </section>
        </aside>
      </main>
    </section>
  );
}
