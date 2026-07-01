import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "../components/ui/PageHeader";
import { api } from "../api";

function visualValue(payload: Record<string, unknown>, key: string, fallback = "未设置") {
  const value = payload[key];
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value || "").trim() || fallback;
}

function visualRecord(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function visualSampleTone(payload: Record<string, unknown>, index: number) {
  const colorDirection = visualValue(payload, "color_direction", "");
  if (/高饱和|鲜明|活力|潮|霓虹/.test(colorDirection)) return "vivid";
  if (/深色|黑|暗|赛博|科技/.test(colorDirection)) return "dark";
  if (/温暖|生活|柔和|暖/.test(colorDirection)) return "warm";
  return index % 3 === 1 ? "warm" : index % 3 === 2 ? "dark" : "clean";
}

export function VisualPlansPage() {
  const queryClient = useQueryClient();
  const creators = useQuery({ queryKey: ["creator-cards"], queryFn: api.listCreatorCards });
  const [selectedCreatorId, setSelectedCreatorId] = useState("");
  const [prompt, setPrompt] = useState("");
  const creatorId = selectedCreatorId || creators.data?.items[0]?.id || "";
  const visualPlans = useQuery({
    queryKey: ["creator-visual-plans", creatorId],
    queryFn: () => api.listVisualPlans(creatorId),
    enabled: Boolean(creatorId),
  });
  const activePlan = useMemo(() => visualPlans.data?.items.find((item) => item.is_active) ?? visualPlans.data?.items[0] ?? null, [visualPlans.data]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["creator-visual-plans", creatorId] });
  };

  const generate = useMutation({
    mutationFn: () => api.generateVisualPlans(creatorId, { prompt: prompt.trim(), candidate_count: 3 }),
    onSuccess: async () => {
      setPrompt("");
      await refresh();
    },
  });
  const refine = useMutation({
    mutationFn: () => activePlan ? api.refineVisualPlan(activePlan.id, prompt.trim()) : Promise.reject(new Error("没有可调整的视觉方案")),
    onSuccess: async () => {
      setPrompt("");
      await refresh();
    },
  });
  const smartActionPending = generate.isPending || refine.isPending;
  const shouldRefine = Boolean(prompt.trim() && activePlan);
  const smartActionLabel = smartActionPending ? "处理中" : shouldRefine ? "智能调整" : "智能生成";
  const runSmartAction = () => {
    if (shouldRefine) {
      refine.mutate();
      return;
    }
    generate.mutate();
  };

  return (
    <section className="page-stack asset-workspace-page">
      <PageHeader
        eyebrow="资产库"
        title="视觉方案"
        description="管理包装、字幕、封面方向、画面增强和平台适配约束。"
      />
      <section className="page-section asset-workspace-section asset-workspace-section-plain">
        <div className="page-section-body">
        <div className="asset-workspace-topline">
          <div className="asset-workspace-controls">
            <label>
              <span>创作者</span>
              <select className="input" value={creatorId} onChange={(event) => setSelectedCreatorId(event.target.value)}>
                <option value="">请选择创作者</option>
                {(creators.data?.items ?? []).map((creator) => <option key={creator.id} value={creator.id}>{creator.name}</option>)}
              </select>
            </label>
            <label>
              <span>视觉想法</span>
              <textarea
                className="input"
                rows={2}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="可留空智能生成；也可输入自然语言调整当前默认方案，例如：画面干净克制，标题像结论，字幕高亮型号参数。"
              />
            </label>
            <div className="asset-workspace-actions">
              <button type="button" className="button primary" disabled={!creatorId || smartActionPending} onClick={runSmartAction}>
                {smartActionLabel}
              </button>
              <span className="muted compact-text">{visualPlans.data?.items.length ?? 0} 个方案</span>
            </div>
          </div>
        </div>
        <div className="asset-workspace-results asset-workspace-results-wide">
          {visualPlans.data?.items.length ? visualPlans.data.items.map((item, index) => {
            const payload = item.visual_payload_json as Record<string, unknown>;
            const sampleCase = visualRecord(payload, "sample_case");
            const tone = visualSampleTone(payload, index);
            return (
              <article key={item.id} className="asset-workspace-card visual-plan-card">
                <div className={`visual-plan-sample visual-plan-sample-${tone}`}>
                  <div className="visual-plan-cover-copy">
                    <span>案例：{visualValue(sampleCase, "scene", visualValue(payload, "title_tone", "结论式标题"))}</span>
                    <strong>{visualValue(sampleCase, "cover_text", visualValue(payload, "cover_direction", "封面视觉样品"))}</strong>
                  </div>
                  <div className="visual-plan-subtitle-line">{visualValue(sampleCase, "subtitle_sample", visualValue(payload, "subtitle_direction", "字幕高亮样品"))}</div>
                  <div className="visual-plan-swatches" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </div>
                </div>
                <div className="asset-workspace-card-head">
                  <strong>{item.name}</strong>
                  {item.is_active ? <span className="job-upload-selected-pill">默认</span> : null}
                </div>
                <div className="asset-workspace-summary">{item.summary || "视觉方向候选"}</div>
                <div className="asset-workspace-field-grid">
                  <span>封面：{visualValue(payload, "cover_direction")}</span>
                  <span>字幕：{visualValue(payload, "subtitle_direction")}</span>
                  <span>标题：{visualValue(payload, "title_tone")}</span>
                  <span>案例：{visualValue(sampleCase, "title_sample", visualValue(payload, "color_direction"))}</span>
                </div>
                <details className="asset-workspace-details">
                  <summary>查看完整方案</summary>
                  <pre>{JSON.stringify(item.visual_payload_json, null, 2)}</pre>
                </details>
                {!item.is_active ? (
                  <button type="button" className="button" onClick={() => api.activateVisualPlan(item.id).then(refresh)}>
                    设为默认
                  </button>
                ) : null}
              </article>
            );
          }) : <div className="asset-workspace-empty">选择创作者后可直接生成默认视觉方案。</div>}
        </div>
        </div>
      </section>
    </section>
  );
}
