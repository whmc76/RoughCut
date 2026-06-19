import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "../../api";
import {
  openManualHandoffTarget,
  publicationPlanExecutorPreflightMessages,
  publicationPlanHasManualHandoffReady,
  publicationPlanManualHandoffTargets,
  publicationPlanStatusKind,
} from "../intelligentCopy/useIntelligentCopyWorkspace";
import { publicationAttemptReceiptId } from "../publication/publicationAttempt";
import type {
  Job,
  PublicationAttempt,
  PublicationPlan,
  PublicationPlatformPublishOptions,
} from "../../types";

type PublicationPlatformOptionDraft = {
  scheduled_publish_at: string;
  collection_id: string;
  collection_name: string;
  category: string;
  visibility_or_publish_mode: string;
};

function publicationAttemptStatusLabel(status: string) {
  if (status === "queued") return "已排队";
  if (status === "draft_created") return "草稿已创建";
  if (status === "scheduled_pending") return "已预约";
  if (status === "published") return "已发布";
  if (status === "failed") return "失败";
  return status || "待处理";
}

function createEmptyPublicationPlatformOption(): PublicationPlatformOptionDraft {
  return {
    scheduled_publish_at: "",
    collection_id: "",
    collection_name: "",
    category: "",
    visibility_or_publish_mode: "",
  };
}

function buildPublicationPlatformOptions(
  draft: Record<string, PublicationPlatformOptionDraft>,
): Record<string, PublicationPlatformPublishOptions> {
  const entries = Object.entries(draft)
    .map(([platform, value]) => {
      const option: PublicationPlatformPublishOptions = {};
      const scheduledAt = value.scheduled_publish_at.trim();
      const collectionId = value.collection_id.trim();
      const collectionName = value.collection_name.trim();
      const category = value.category.trim();
      const visibility = value.visibility_or_publish_mode.trim();
      if (scheduledAt) option.scheduled_publish_at = scheduledAt;
      if (collectionId) option.collection_id = collectionId;
      if (collectionName) option.collection_name = collectionName;
      if (category) option.category = category;
      if (visibility) option.visibility_or_publish_mode = visibility;
      return [platform, option] as const;
    })
    .filter(([, option]) => Object.keys(option).length > 0);
  return Object.fromEntries(entries);
}

function hasActivePublicationAttempt(attempts: PublicationAttempt[] | undefined): boolean {
  return (attempts ?? []).some((attempt) =>
    ["queued", "submitted", "processing", "scheduled_pending"].includes(String(attempt.status ?? "")),
  );
}

export function buildJobPublicationPlanQueryKey(
  jobId: string | null | undefined,
  selectedPublicationProfileId: string | null | undefined,
  jobUpdatedAt: string | null | undefined,
) {
  return [
    "job-publication-plan",
    String(jobId ?? ""),
    String(selectedPublicationProfileId ?? ""),
    String(jobUpdatedAt ?? ""),
  ] as const;
}

export function buildJobPublicationDraftContextKey(
  jobId: string | null | undefined,
  selectedPublicationProfileId: string | null | undefined,
  jobUpdatedAt: string | null | undefined,
) {
  return [
    String(jobId ?? ""),
    String(selectedPublicationProfileId ?? ""),
    String(jobUpdatedAt ?? ""),
  ].join("::");
}

type JobPublicationPanelProps = {
  job: Job;
  onCancel?: () => void;
};

export function JobPublicationPanel({ job, onCancel }: JobPublicationPanelProps) {
  const queryClient = useQueryClient();
  const avatarMaterials = useQuery({
    queryKey: ["avatar-materials", "publication"],
    queryFn: api.getAvatarMaterials,
    enabled: job.status === "done",
  });
  const publicationProfiles = useMemo(
    () => avatarMaterials.data?.profiles ?? [],
    [avatarMaterials.data?.profiles],
  );
  const [selectedPublicationProfileId, setSelectedPublicationProfileId] = useState("");
  const [publicationPlatformOptions, setPublicationPlatformOptions] = useState<Record<string, PublicationPlatformOptionDraft>>({});

  useEffect(() => {
    if (!publicationProfiles.length) {
      setSelectedPublicationProfileId("");
      return;
    }
    setSelectedPublicationProfileId((current) =>
      publicationProfiles.some((profile) => profile.id === current) ? current : publicationProfiles[0]?.id ?? "",
    );
  }, [publicationProfiles]);

  const publicationQueryKey = buildJobPublicationPlanQueryKey(
    job.id,
    selectedPublicationProfileId,
    job.updated_at,
  );
  const publicationDraftContextKey = buildJobPublicationDraftContextKey(
    job.id,
    selectedPublicationProfileId,
    job.updated_at,
  );
  const publicationPlan = useQuery<PublicationPlan>({
    queryKey: publicationQueryKey,
    queryFn: () => api.getJobPublicationPlan(job.id, selectedPublicationProfileId || null),
    enabled: Boolean(job.id && job.status === "done"),
    refetchInterval: (query) => (hasActivePublicationAttempt(query.state.data?.existing_attempts) ? 1_500 : false),
  });
  const manualHandoffTargets = publicationPlanManualHandoffTargets(publicationPlan.data);
  const manualHandoffReady = publicationPlanHasManualHandoffReady(publicationPlan.data);
  const publicationPlanStatus = publicationPlanStatusKind(publicationPlan.data);
  const publicationExecutorPreflightMessages = publicationPlanExecutorPreflightMessages(publicationPlan.data);

  useEffect(() => {
    setPublicationPlatformOptions({});
  }, [publicationDraftContextKey]);

  useEffect(() => {
    const targetPlatforms = new Set((publicationPlan.data?.targets ?? []).map((target) => target.platform));
    setPublicationPlatformOptions((current) => {
      const next = Object.fromEntries(Object.entries(current).filter(([platform]) => targetPlatforms.has(platform)));
      return Object.keys(next).length === Object.keys(current).length ? current : next;
    });
  }, [publicationPlan.data?.targets]);

  const updatePublicationPlatformOption = (platform: string, patch: Partial<PublicationPlatformOptionDraft>) => {
    setPublicationPlatformOptions((current) => {
      const currentOption = current[platform] ?? createEmptyPublicationPlatformOption();
      return {
        ...current,
        [platform]: { ...currentOption, ...patch },
      };
    });
  };

  const publishMutation = useMutation({
    mutationFn: () =>
      api.publishJob(job.id, {
        creator_profile_id: selectedPublicationProfileId || null,
        platform_options: buildPublicationPlatformOptions(publicationPlatformOptions),
      }),
    onSuccess: async (data) => {
      queryClient.setQueryData(publicationQueryKey, data);
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });

  return (
    <section className="form-stack">
      <div className="toolbar">
        <div>
          <strong>发布到创作者卡片绑定平台</strong>
          <div className="muted compact-top">{job.source_name}</div>
        </div>
        <span className={`status-pill ${publicationPlanStatus === "ready" ? "done" : "pending"}`}>
          {publicationPlanStatus === "ready" ? "可发布" : manualHandoffReady ? "人工接管" : "待补齐"}
        </span>
      </div>

      <div className="form-grid two-up compact-top">
        <label>
          <span>创作者卡片</span>
          <select
            className="input"
            value={selectedPublicationProfileId}
            onChange={(event) => setSelectedPublicationProfileId(event.target.value)}
            disabled={!publicationProfiles.length}
          >
            {!publicationProfiles.length ? <option value="">没有创作者卡片</option> : null}
            {publicationProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.display_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {avatarMaterials.isLoading || publicationPlan.isLoading ? <div className="muted compact-top">正在检查发布准入...</div> : null}
      {publicationPlan.data?.blocked_reasons?.length ? (
        <div className="list-stack compact-top">
          {publicationPlan.data.blocked_reasons.map((reason) => (
            <div key={reason} className="notice">{reason}</div>
          ))}
        </div>
      ) : null}
      {publicationPlan.data?.warnings?.length ? (
        <div className="list-stack compact-top">
          {publicationPlan.data.warnings.map((warning) => (
            <div key={warning} className="activity-card">{warning}</div>
          ))}
        </div>
      ) : null}
      {publicationExecutorPreflightMessages.length ? (
        <div className="list-stack compact-top">
          {publicationExecutorPreflightMessages.map((message) => (
            <div key={message} className="activity-card">{message}</div>
          ))}
        </div>
      ) : null}
      {manualHandoffTargets.length ? (
        <div className="list-stack compact-top">
          {manualHandoffTargets.map((target) => (
            <article className="activity-card" key={`${target.platform}-${target.login_url || "manual"}`}>
              <div className="toolbar">
                <div>
                  <strong>{target.label || target.platform}</strong>
                  <div className="muted compact-top">{target.reason || "该平台需人工登录后继续发布。"}</div>
                </div>
                {target.login_url ? (
                  <button type="button" className="button secondary" onClick={() => openManualHandoffTarget(target)}>
                    打开登录页
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {publicationPlan.data?.targets?.length ? (
        <div className="list-stack compact-top">
          {publicationPlan.data.targets.map((target) => (
            <article className="activity-card" key={target.platform}>
              <div className="toolbar">
                <div>
                  <strong>{target.platform_label}</strong>
                  <div className="muted compact-top">{target.account_label}</div>
                </div>
                <span className="status-pill done">待提交</span>
              </div>
              <div className="form-grid two-up compact-top">
                <label>
                  <span>定时发布</span>
                  <input
                    className="input"
                    type="datetime-local"
                    value={publicationPlatformOptions[target.platform]?.scheduled_publish_at ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(target.platform, { scheduled_publish_at: event.target.value })
                    }
                  />
                </label>
                <label>
                  <span>发布模式</span>
                  <select
                    className="input"
                    value={publicationPlatformOptions[target.platform]?.visibility_or_publish_mode ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(target.platform, { visibility_or_publish_mode: event.target.value })
                    }
                  >
                    <option value="">立即/默认</option>
                    <option value="scheduled">预约发布</option>
                    <option value="draft">仅创建草稿</option>
                    <option value="private">仅自己可见</option>
                  </select>
                </label>
                <label>
                  <span>合集/栏目 ID</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[target.platform]?.collection_id ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(target.platform, { collection_id: event.target.value })
                    }
                    placeholder="可选，平台合集或栏目 ID"
                  />
                </label>
                <label>
                  <span>合集/栏目名称</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[target.platform]?.collection_name ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(target.platform, { collection_name: event.target.value })
                    }
                    placeholder="可选，给 browser-agent 定位 UI"
                  />
                </label>
                <label>
                  <span>平台分类</span>
                  <input
                    className="input"
                    type="text"
                    value={publicationPlatformOptions[target.platform]?.category ?? ""}
                    onChange={(event) =>
                      updatePublicationPlatformOption(target.platform, { category: event.target.value })
                    }
                    placeholder="可选，例如 数码 / 装备"
                  />
                </label>
              </div>
              <div className="muted compact-top">{target.title}</div>
            </article>
          ))}
        </div>
      ) : null}
      {publishMutation.error ? <div className="notice compact-top">{String(publishMutation.error)}</div> : null}
      {publicationPlan.data?.existing_attempts?.length ? (
        <div className="timeline-list top-gap">
          {publicationPlan.data.existing_attempts.slice(0, 6).map((attempt) => (
            <div className="timeline-item" key={attempt.id}>
              <div className="toolbar">
                <strong>{attempt.platform_label || attempt.platform}</strong>
                <span className={`status-pill ${attempt.status === "failed" ? "failed" : attempt.status === "published" ? "done" : "running"}`}>
                  {publicationAttemptStatusLabel(attempt.status)}
                </span>
              </div>
              <div className="muted">
                {attempt.account_label} · {attempt.operator_summary || attempt.run_status || "等待运行器处理"}
              </div>
              {publicationAttemptReceiptId(attempt) ? (
                <div className="muted" title={publicationAttemptReceiptId(attempt)}>
                  回执：{publicationAttemptReceiptId(attempt)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      <div className="toolbar top-gap">
        <button className="button ghost" type="button" onClick={onCancel}>
          取消
        </button>
        {manualHandoffTargets.length ? (
          <button
            className="button secondary"
            type="button"
            onClick={() => {
              manualHandoffTargets.forEach((target) => {
                openManualHandoffTarget(target);
              });
            }}
          >
            打开人工登录页
          </button>
        ) : null}
        <button
          className="button primary"
          type="button"
          disabled={publicationPlanStatus === "manual_handoff" || publishMutation.isPending}
          onClick={() => publishMutation.mutate()}
        >
          {publishMutation.isPending ? "提交中..." : "生成物料并发布"}
        </button>
      </div>
    </section>
  );
}
