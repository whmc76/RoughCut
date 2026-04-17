import { PageHeader } from "../components/ui/PageHeader";
import { PageSection } from "../components/ui/PageSection";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useControlWorkspace } from "../features/control/useControlWorkspace";
import { useI18n } from "../i18n";
import { formatDate } from "../utils";

function renderRuntimeTone(status: string | undefined) {
  return status === "ready" || status === "held" || status === "free" || status === "pass" ? "status-ok" : "status-off";
}

export function ControlPage() {
  const { t } = useI18n();
  const workspace = useControlWorkspace();
  const lastChecked = workspace.status.data
    ? t("control.services.lastChecked").replace("{time}", formatDate(workspace.status.data.checked_at))
    : t("control.services.unavailable");
  const healthChecked = workspace.healthDetail.data
    ? `health detail ${formatDate(workspace.healthDetail.data.checked_at)}`
    : "health detail unavailable";
  const runtime = workspace.status.data?.runtime;
  const readinessChecks = Object.entries(runtime?.readiness_checks ?? {});
  const liveReadiness = runtime?.live_readiness;
  const reviewNotifications = workspace.reviewNotifications.data ?? runtime?.review_notifications;
  const visibleNotificationIds = (reviewNotifications?.items ?? []).map((item) => item.notification_id);
  const managedServices = workspace.healthDetail.data?.managed_services ?? [];
  const watchAutomation = workspace.healthDetail.data?.watch_automation;

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
          {runtime && (
            <div className="top-gap list-stack">
              <article className="list-card">
                <div>
                  <div className="row-title">Runtime readiness</div>
                  <div className="muted">区分“进程在线”与“依赖可用”。</div>
                </div>
                <div className="row-meta">
                  <strong className={renderRuntimeTone(runtime.readiness_status)}>{runtime.readiness_status ?? "unknown"}</strong>
                </div>
              </article>
              <article className="list-card">
                <div>
                  <div className="row-title">Orchestrator lock</div>
                  <div className="muted">{runtime.orchestrator_lock?.detail ?? "暂无锁状态详情"}</div>
                </div>
                <div className="row-meta">
                  <strong className={renderRuntimeTone(runtime.orchestrator_lock?.status)}>{runtime.orchestrator_lock?.status ?? "unknown"}</strong>
                  <span>{runtime.orchestrator_lock?.leader_active == null ? "leader=unknown" : `leader=${runtime.orchestrator_lock.leader_active ? "active" : "idle"}`}</span>
                </div>
              </article>
              {readinessChecks.map(([key, value]) => (
                <article key={key} className="list-card">
                  <div>
                    <div className="row-title">{key}</div>
                    <div className="muted">{value.detail}</div>
                  </div>
                  <div className="row-meta">
                    <strong className={renderRuntimeTone(value.status)}>{value.status}</strong>
                  </div>
                </article>
              ))}
              <article className="list-card">
                <div>
                  <div className="row-title">Review notification queue</div>
                  <div className="muted">{reviewNotifications?.store_file ?? "暂无补偿队列状态文件。"}</div>
                </div>
                <div className="row-meta">
                  <strong>{reviewNotifications?.summary?.pending ?? 0} pending</strong>
                  <span>{reviewNotifications?.summary?.failed ?? 0} failed</span>
                </div>
              </article>
              <article className="list-card">
                <div>
                  <div className="row-title">Live readiness</div>
                  <div className="muted">{liveReadiness?.summary ?? "尚无 live readiness 摘要。"}</div>
                  <div className="muted">{liveReadiness?.report_file ?? "未找到 batch_report.json"}</div>
                  {liveReadiness?.failure_reasons?.length ? (
                    <div className="muted">failures={liveReadiness.failure_reasons.join(" / ")}</div>
                  ) : null}
                  {liveReadiness?.warning_reasons?.length ? (
                    <div className="muted">warnings={liveReadiness.warning_reasons.join(" / ")}</div>
                  ) : null}
                  {liveReadiness?.detail ? <div className="muted">detail={liveReadiness.detail}</div> : null}
                </div>
                <div className="row-meta">
                  <strong className={renderRuntimeTone(liveReadiness?.status)}>
                    {liveReadiness?.status ?? "unknown"}
                  </strong>
                  <span>
                    stable={liveReadiness?.stable_run_count ?? 0}/{liveReadiness?.required_stable_runs ?? 0}
                  </span>
                </div>
              </article>
            </div>
          )}
        </section>
      </PageSection>

      <PageSection
        eyebrow="补偿队列"
        title="审核通知补偿"
        description="这里显示 Telegram 审核通知的补偿状态。优先看 due_now 和 failed，再决定是否手动重排。"
      >
        <section className="panel">
          <PanelHeader
            title="Review notifications"
            description={reviewNotifications?.state_dir ?? "当前没有可用的补偿队列目录"}
          />
          <div className="toolbar top-gap">
            <input
              type="text"
              placeholder="按 job_id 过滤"
              value={workspace.reviewNotificationJobIdFilter}
              onChange={(event) => workspace.setReviewNotificationJobIdFilter(event.target.value)}
            />
            <button
              className="button ghost"
              type="button"
              onClick={() => workspace.setReviewNotificationJobIdFilter("")}
              disabled={!workspace.reviewNotificationJobIdFilter}
            >
              Clear
            </button>
            <button
              className="button"
              type="button"
              onClick={() => workspace.requeueReviewNotifications.mutate(visibleNotificationIds)}
              disabled={!visibleNotificationIds.length || workspace.requeueReviewNotifications.isPending}
            >
              Requeue shown
            </button>
            <button
              className="button danger"
              type="button"
              onClick={() => workspace.dropReviewNotifications.mutate(visibleNotificationIds)}
              disabled={!visibleNotificationIds.length || workspace.dropReviewNotifications.isPending}
            >
              Drop shown
            </button>
          </div>
          {reviewNotifications?.detail ? <div className="notice">{reviewNotifications.detail}</div> : null}
          <div className="service-grid">
            <article className="service-card">
              <span>Total</span>
              <strong>{reviewNotifications?.summary?.total ?? 0}</strong>
            </article>
            <article className="service-card">
              <span>Pending</span>
              <strong className={(reviewNotifications?.summary?.pending ?? 0) > 0 ? "status-off" : "status-ok"}>
                {reviewNotifications?.summary?.pending ?? 0}
              </strong>
            </article>
            <article className="service-card">
              <span>Due now</span>
              <strong className={(reviewNotifications?.summary?.due_now ?? 0) > 0 ? "status-off" : "status-ok"}>
                {reviewNotifications?.summary?.due_now ?? 0}
              </strong>
            </article>
            <article className="service-card">
              <span>Failed</span>
              <strong className={(reviewNotifications?.summary?.failed ?? 0) > 0 ? "status-off" : "status-ok"}>
                {reviewNotifications?.summary?.failed ?? 0}
              </strong>
            </article>
          </div>
          <div className="top-gap list-stack">
            {(reviewNotifications?.items ?? []).map((item) => (
              <article key={item.notification_id} className="list-card">
                <div>
                  <div className="row-title">{item.kind} · {item.status}</div>
                  <div className="muted">
                    {item.notification_id} · job={item.job_id}
                  </div>
                  <div className="muted">
                    attempts={item.attempt_count} · next={formatDate(item.next_attempt_at)}
                  </div>
                  {item.last_error ? <div className="muted">error={item.last_error}</div> : null}
                </div>
                <div className="row-meta">
                  <button
                    className="button"
                    type="button"
                    onClick={() => workspace.requeueReviewNotification.mutate(item.notification_id)}
                    disabled={workspace.requeueReviewNotification.isPending}
                  >
                    Requeue
                  </button>
                  <button
                    className="button danger"
                    type="button"
                    onClick={() => workspace.dropReviewNotification.mutate(item.notification_id)}
                    disabled={workspace.dropReviewNotification.isPending}
                  >
                    Drop
                  </button>
                </div>
              </article>
            ))}
            {!reviewNotifications?.items?.length && (
              <article className="list-card">
                <div>
                  <div className="row-title">No queued notifications</div>
                  <div className="muted">当前没有待补偿或已记录的审核通知。</div>
                </div>
              </article>
            )}
            {workspace.requeueReviewNotification.error ? (
              <div className="notice top-gap">{(workspace.requeueReviewNotification.error as Error).message}</div>
            ) : null}
            {workspace.dropReviewNotification.error ? (
              <div className="notice top-gap">{(workspace.dropReviewNotification.error as Error).message}</div>
            ) : null}
            {workspace.requeueReviewNotifications.error ? (
              <div className="notice top-gap">{(workspace.requeueReviewNotifications.error as Error).message}</div>
            ) : null}
            {workspace.dropReviewNotifications.error ? (
              <div className="notice top-gap">{(workspace.dropReviewNotifications.error as Error).message}</div>
            ) : null}
          </div>
        </section>
      </PageSection>

      <PageSection
        eyebrow="运行细项"
        title="把问题拆到依赖和自动化层"
        description="这里单独展开 health detail，方便判断故障是出在受管服务、watcher 自动入队，还是基础依赖。"
      >
        <div className="panel-grid two-up">
          <section className="panel">
            <PanelHeader title="Managed services" description={healthChecked} />
            <div className="list-stack">
              {managedServices.map((service) => (
                <article key={`${service.name}-${service.url}`} className="list-card">
                  <div>
                    <div className="row-title">{service.name}</div>
                    <div className="muted">{service.url}</div>
                  </div>
                  <div className="row-meta">
                    <strong className={renderRuntimeTone(service.status)}>{service.status}</strong>
                    <span>{service.enabled ? "managed" : "disabled"}</span>
                  </div>
                </article>
              ))}
              {!managedServices.length && !workspace.healthDetail.isLoading && (
                <article className="list-card">
                  <div>
                    <div className="row-title">No managed services</div>
                    <div className="muted">当前配置没有启用受管 GPU sidecar，或接口未返回服务清单。</div>
                  </div>
                </article>
              )}
              {workspace.healthDetail.isError && (
                <article className="list-card">
                  <div>
                    <div className="row-title">Health detail unavailable</div>
                    <div className="muted">{(workspace.healthDetail.error as Error).message}</div>
                  </div>
                </article>
              )}
            </div>
          </section>

          <section className="panel">
            <PanelHeader title="Watch automation" description={healthChecked} />
            <div className="list-stack">
              {watchAutomation ? (
                <>
                  <article className="list-card">
                    <div>
                      <div className="row-title">Auto enqueue / merge</div>
                      <div className="muted">判断 watcher 当前是否在自动接片和自动合并。</div>
                    </div>
                    <div className="row-meta">
                      <strong className={watchAutomation.auto_enqueue_enabled ? "status-ok" : "status-off"}>
                        {watchAutomation.auto_enqueue_enabled ? "enqueue on" : "enqueue off"}
                      </strong>
                      <span>{watchAutomation.auto_merge_enabled ? "merge on" : "merge off"}</span>
                    </div>
                  </article>
                  <article className="list-card">
                    <div>
                      <div className="row-title">Watch roots / pending</div>
                      <div className="muted">根目录数量和缓存中的待处理素材规模。</div>
                    </div>
                    <div className="row-meta">
                      <strong>{watchAutomation.roots_total} roots</strong>
                      <span>{watchAutomation.cached_pending_total} pending</span>
                    </div>
                  </article>
                  <article className="list-card">
                    <div>
                      <div className="row-title">Scans / active jobs</div>
                      <div className="muted">同时看扫描活动和当前自动调度出的任务量。</div>
                    </div>
                    <div className="row-meta">
                      <strong>{watchAutomation.running_scans} scans</strong>
                      <span>{watchAutomation.active_jobs} jobs</span>
                    </div>
                  </article>
                  <article className="list-card">
                    <div>
                      <div className="row-title">GPU guard / idle slots</div>
                      <div className="muted">GPU 步骤是否在跑，以及自动调度还剩多少空位。</div>
                    </div>
                    <div className="row-meta">
                      <strong>{watchAutomation.running_gpu_steps} gpu</strong>
                      <span>{watchAutomation.idle_slots} idle</span>
                    </div>
                  </article>
                </>
              ) : (
                !workspace.healthDetail.isLoading && (
                  <article className="list-card">
                    <div>
                      <div className="row-title">Watch automation unavailable</div>
                      <div className="muted">接口还没有返回 watcher 自动入队状态。</div>
                    </div>
                  </article>
                )
              )}
            </div>
          </section>
        </div>
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
