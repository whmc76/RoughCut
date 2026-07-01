import { useState } from "react";
import { Link } from "react-router-dom";
import { Activity, CheckCircle2, ClipboardCheck, ClipboardList, PlaySquare, Server, UploadCloud, Wrench } from "lucide-react";

import { api } from "../api";
import { EmptyState } from "../components/ui/EmptyState";
import { useOverviewWorkspace } from "../features/overview/useOverviewWorkspace";
import type { Job } from "../types";
import { classNames, formatDate, statusLabel } from "../utils";

function renderRuntimeTone(status: string | undefined) {
  return status === "ready" || status === "held" || status === "free" ? "status-ok" : "status-off";
}

function formatCompactNumber(value: number | undefined) {
  if (!value) return "0";
  if (value >= 10000) return `${(value / 10000).toFixed(value >= 100000 ? 0 : 1)}万`;
  return value.toLocaleString();
}

function clampProgress(value: number | undefined) {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value ?? 0)));
}

function queueStageLabel(job: Job) {
  if (job.review_label) return job.review_label;
  if (job.awaiting_manual_edit) return "手动调整";
  if (job.awaiting_initialization || job.status === "awaiting_init") return "等待初始化";
  if (job.status === "needs_review") return "脚本审核";
  if (job.status === "running" || job.status === "processing") return "生产处理中";
  if (job.status === "queued" || job.status === "pending") return "等待调度";
  return statusLabel(job.status);
}

function OverviewQueueThumbnail({ job }: { job: Job }) {
  const thumbnailVersion = job.queue_thumbnail_version || job.updated_at;
  const contentThumbnailUrl = api.contentProfileThumbnailUrl(job.id, 0, thumbnailVersion);
  const coverThumbnailUrl = api.jobCoverThumbnailUrl(job.id, thumbnailVersion);
  const [source, setSource] = useState<"cover" | "content_profile" | "fallback">(
    job.queue_thumbnail_source === "cover" ? "cover" : "content_profile",
  );

  if (source === "fallback") {
    return (
      <div className="overview-ops-thumb overview-ops-thumb-fallback" aria-hidden="true">
        RC
      </div>
    );
  }

  return (
    <img
      className="overview-ops-thumb"
      src={source === "cover" ? coverThumbnailUrl : contentThumbnailUrl}
      alt={job.source_name}
      loading="lazy"
      decoding="async"
      onError={() => setSource((current) => (current === "cover" ? "content_profile" : "fallback"))}
    />
  );
}

export function OverviewPage() {
  const workspace = useOverviewWorkspace();
  const jobs = workspace.jobs.data ?? [];
  const runtime = workspace.services.data?.runtime;
  const serviceEntries = Object.entries(workspace.services.data?.services ?? {});
  const onlineServices = serviceEntries.filter(([, online]) => online);
  const blockedServices = serviceEntries.filter(([, online]) => !online);
  const runningJobs = jobs.filter((job) => job.status === "running" || job.status === "processing");
  const reviewJobs = jobs.filter((job) => job.status === "needs_review" || job.awaiting_manual_edit);
  const failedJobs = jobs.filter((job) => job.status === "failed" || job.status === "blocked_missing_script");
  const doneJobs = jobs.filter((job) => job.status === "done" || job.status === "published");
  const activeJobs = jobs
    .filter((job) =>
      ["running", "processing", "needs_review", "queued", "pending", "awaiting_init", "awaiting_manual_edit"].includes(job.status),
    )
    .slice(0, 4);
  const recentJobs = [...jobs].sort((left, right) => new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()).slice(0, 3);
  const totalTokens = workspace.usageSummary.data?.total_tokens ?? 0;
  const cacheHitRate = workspace.usageSummary.data?.cache.hit_rate ?? 0;
  const servicePercent = serviceEntries.length ? Math.round((onlineServices.length / serviceEntries.length) * 100) : 0;
  const attentionCount = reviewJobs.length + failedJobs.length + blockedServices.length;
  const topSteps = workspace.usageSummary.data?.top_steps.slice(0, 3) ?? [];
  const topModels = workspace.usageSummary.data?.top_models.slice(0, 2) ?? [];
  const primaryTitle = blockedServices.length
    ? "服务需要处理"
    : failedJobs.length
      ? `${failedJobs.length} 项任务异常`
      : reviewJobs.length
        ? `${reviewJobs.length} 项等待确认`
        : runningJobs.length
          ? `${runningJobs.length} 项正在处理`
          : "系统待命";
  const primaryLead = blockedServices.length
    ? "先恢复离线服务，再继续投递任务。"
    : failedJobs.length
      ? "优先进入制片队列处理失败、缺脚本或需要人工调整的任务。"
      : reviewJobs.length
        ? "优先进入成片审看处理待确认输出。"
        : runningJobs.length
          ? "队列正在推进，可以继续观察产出和服务负载。"
          : "没有阻塞项，可以从工作入口继续。";
  const attentionTone = blockedServices.length || failedJobs.length ? "is-critical" : reviewJobs.length ? "is-warning" : "is-stable";
  const recoveryItems = [
    ...failedJobs.map((job) => ({
      key: `job-${job.id}`,
      title: job.source_name,
      detail: job.error_message || job.review_detail || statusLabel(job.status),
    })),
    ...blockedServices.map(([key]) => ({
      key: `service-${key}`,
      title: key,
      detail: "服务离线，需要恢复后再继续生产。",
    })),
  ].slice(0, 4);
  const overviewFlowItems = [
    {
      key: "attention",
      label: "待处理",
      value: attentionCount,
      detail: "失败、缺脚本、待确认或服务异常",
      actionLabel: attentionCount ? "看需处理" : "状态正常",
      icon: ClipboardList,
      to: "/jobs",
    },
    {
      key: "running",
      label: "运行中",
      value: runningJobs.length,
      detail: "正在生成、转写或包装",
      actionLabel: runningJobs.length ? "看运行中" : "暂无运行",
      icon: Activity,
      to: "/jobs",
    },
    {
      key: "done",
      label: "完成",
      value: doneJobs.length,
      detail: "可转入成片审看",
      actionLabel: doneJobs.length ? "看完成输出" : "等待输出",
      icon: CheckCircle2,
      to: "/final-review",
    },
    {
      key: "service",
      label: "服务在线",
      value: serviceEntries.length ? `${onlineServices.length}/${serviceEntries.length}` : "-",
      detail: "API、worker 和编排服务",
      actionLabel: serviceEntries.length ? `${servicePercent}% 在线` : "等待心跳",
      icon: Server,
      to: "/control",
    },
  ];
  const commandEntries = [
    {
      to: "/jobs",
      label: "制片队列",
      eyebrow: "Production",
      metric: reviewJobs.length ? `${reviewJobs.length} 待审` : `${runningJobs.length} 运行`,
      description: "导入、排队、运行、恢复和成片交接。",
      tone: "is-primary",
      icon: UploadCloud,
    },
    {
      to: "/final-review",
      label: "成片审看",
      eyebrow: "Review",
      metric: `${reviewJobs.length} 待确认`,
      description: "检查最终成片，决定通过或退回制片。",
      tone: "",
      icon: PlaySquare,
    },
    {
      to: "/publication-tracking",
      label: "发布跟踪",
      eyebrow: "Publish",
      metric: `${failedJobs.length ? failedJobs.length : reviewJobs.length} 关注`,
      description: "查看发布物料、平台状态和人工交接结果。",
      tone: "",
      icon: ClipboardCheck,
    },
    {
      to: "/tools",
      label: "工具箱",
      eyebrow: "Tools",
      metric: `${onlineServices.length} 在线`,
      description: "ASR、TTS、数字人和临时处理工具。",
      tone: "",
      icon: Wrench,
    },
  ];

  return (
    <section className="page-stack overview-page control-center-page overview-ops-page" data-testid="overview-command-center">
      <header className={classNames("overview-production-band", attentionTone)} aria-label="首页生产状态带">
        <div className="overview-production-brief">
          <span className="overview-production-kicker">RoughCut Monitor</span>
          <h2>{primaryTitle}</h2>
          <p>{primaryLead}</p>
          <div className="overview-production-command-row">
            <Link className="button primary button-sm" to="/jobs">
              进入制片队列
            </Link>
            <Link className="button ghost button-sm" to={attentionCount ? "/jobs" : "/final-review"}>
              {attentionCount ? `处理需处理 ${attentionCount}` : "查看成片审看"}
            </Link>
          </div>
        </div>

        <div className="overview-production-flow" aria-label="核心状态">
          {overviewFlowItems.map((item, index) => {
            const Icon = item.icon;
            return (
              <Link key={item.key} className={classNames("overview-production-flow-step", `is-${item.key}`)} to={item.to}>
                <span className="overview-production-flow-head">
                  <span className="overview-production-flow-index">{`0${index + 1}`}</span>
                  <Icon size={16} strokeWidth={2.1} aria-hidden="true" />
                </span>
                <span className="overview-production-flow-label">{item.label}</span>
                <strong>{item.value}</strong>
                <small>{item.detail}</small>
                <em>{item.actionLabel}</em>
              </Link>
            );
          })}
        </div>

        <section className="overview-production-list" aria-label="完成输出">
          <div className="overview-production-panel-head">
            <span>完成输出</span>
            <strong>{doneJobs.length} 条</strong>
          </div>
          <div className="overview-production-list-body">
            {doneJobs.slice(0, 3).map((job) => (
              <article key={job.id} className="overview-production-output-row">
                <div>
                  <strong>{job.source_name}</strong>
                  <span>{job.publication_summary || job.content_summary || job.content_subject || "等待审看或发布交接。"}</span>
                </div>
                <Link className="button ghost button-sm" to={`/final-review?job=${encodeURIComponent(job.id)}`}>
                  审看
                </Link>
              </article>
            ))}
            {!doneJobs.length ? <div className="overview-production-empty">暂无完成输出。先处理生产队列或异常项。</div> : null}
          </div>
        </section>

        <section className="overview-production-list overview-production-recovery" aria-label="异常恢复">
          <div className="overview-production-panel-head">
            <span>异常恢复</span>
            <strong>{recoveryItems.length} 条</strong>
          </div>
          <div className="overview-production-list-body">
            {recoveryItems.map((item) => (
              <article key={item.key} className="overview-production-recovery-row">
                <strong>{item.title}</strong>
                <span>{item.detail}</span>
              </article>
            ))}
            {!recoveryItems.length ? <div className="overview-production-empty">暂无异常恢复项。</div> : null}
          </div>
        </section>
      </header>

      <main className="control-center-grid overview-ops-grid">
        <section className="control-center-entry-zone overview-ops-entry-list" aria-label="工作入口">
          <div className="overview-ops-section-head">
            <ClipboardList size={16} strokeWidth={1.8} aria-hidden="true" />
            <span>工作入口</span>
          </div>
          {commandEntries.map((entry, index) => (
            <Link key={entry.to} className={classNames("control-center-entry overview-ops-entry", entry.tone)} to={entry.to}>
              <entry.icon className="overview-ops-entry-icon" size={18} strokeWidth={1.8} aria-hidden="true" />
              <span className="control-center-entry-index">{`0${index + 1}`}</span>
              <div className="overview-ops-entry-copy">
                <span className="control-center-entry-eyebrow">{entry.eyebrow}</span>
                <strong>{entry.label}</strong>
                <p>{entry.description}</p>
              </div>
              <span className="control-center-entry-metric">{entry.metric}</span>
            </Link>
          ))}
        </section>

        <section className="control-center-queue-panel overview-ops-panel overview-ops-queue-panel">
          <div className="control-center-panel-head">
            <span><Activity size={15} strokeWidth={1.9} aria-hidden="true" /> 当前队列</span>
            <Link to="/jobs">查看全部</Link>
          </div>
          {workspace.jobs.isLoading && <EmptyState message="正在加载任务。" />}
          {workspace.jobs.isError && <EmptyState message={(workspace.jobs.error as Error).message} tone="error" />}
          {!workspace.jobs.isLoading && !workspace.jobs.isError && activeJobs.length === 0 ? (
            <EmptyState message="当前没有需要处理的任务。" />
          ) : null}
          <div className="control-center-queue-list">
            {activeJobs.length ? (
              <div className="overview-ops-queue-head" aria-hidden="true">
                <span>任务</span>
                <span>状态</span>
                <span>阶段</span>
                <span>更新时间</span>
              </div>
            ) : null}
            {activeJobs.map((job, index) => (
              <article key={job.id} className="control-center-queue-row">
                <span>{`${index + 1}`.padStart(2, "0")}</span>
                <div className="overview-ops-queue-task">
                  <OverviewQueueThumbnail job={job} />
                  <div>
                    <strong>{job.source_name}</strong>
                    <p>{job.content_summary || job.content_subject || job.review_detail || "暂无摘要"}</p>
                  </div>
                </div>
                <span className={`status-chip ${job.status}`}>{statusLabel(job.status)}</span>
                <div className="overview-ops-queue-stage">
                  <strong>{queueStageLabel(job)}</strong>
                  <div aria-label={`进度 ${clampProgress(job.progress_percent)}%`}>
                    <span style={{ width: `${clampProgress(job.progress_percent)}%` }} />
                  </div>
                  <small>{clampProgress(job.progress_percent)}%</small>
                </div>
                <div className="control-center-queue-meta">
                  <small>{formatDate(job.updated_at)}</small>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="control-center-side-panel">
          <section className="control-center-health overview-ops-panel">
            <div className="control-center-panel-head">
              <span><Server size={15} strokeWidth={1.9} aria-hidden="true" /> 运行健康</span>
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

          <section className="control-center-telemetry overview-ops-panel">
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
              {topSteps.length === 0 && topModels.length === 0 ? <p>暂无资源用量。</p> : null}
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

      <footer className="overview-ops-footer">
        <section className="overview-ops-summary" aria-label="运行摘要">
          <div className="overview-ops-section-head">
            <CheckCircle2 size={16} strokeWidth={1.8} aria-hidden="true" />
            <span>运行摘要</span>
          </div>
          <article>
            <strong>{doneJobs.length}</strong>
            <span>已完成</span>
          </article>
          <article>
            <strong>{runningJobs.length}</strong>
            <span>运行中</span>
          </article>
          <article>
            <strong>{failedJobs.length}</strong>
            <span>异常</span>
          </article>
          <article>
            <strong>{reviewJobs.length}</strong>
            <span>待确认</span>
          </article>
        </section>
        <section className="overview-ops-activity" aria-label="最近动态">
          <div className="overview-ops-section-head">
            <Activity size={16} strokeWidth={1.8} aria-hidden="true" />
            <span>最近动态</span>
            <Link to="/jobs">查看全部</Link>
          </div>
          <div>
            {recentJobs.length === 0 ? <p>暂无最近任务动态。</p> : null}
            {recentJobs.map((job) => (
              <article key={job.id}>
                <span className={classNames("overview-ops-dot", job.status === "failed" || job.status === "blocked_missing_script" ? "is-critical" : job.status === "running" || job.status === "processing" ? "is-live" : "")} />
                <strong>{job.source_name}</strong>
                <span>{statusLabel(job.status)} · {queueStageLabel(job)}</span>
                <time>{formatDate(job.updated_at)}</time>
              </article>
            ))}
          </div>
        </section>
      </footer>
    </section>
  );
}
