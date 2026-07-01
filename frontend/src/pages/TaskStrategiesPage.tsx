import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "../components/ui/PageHeader";
import { api } from "../api";

const STRATEGY_FALLBACKS = [
  {
    strategy_type: "creator_compact_dense_policy",
    strategy_goal: "把说话节奏剪快、镜头变短，让信息连续输出",
    opening_policy: "开头 3-8 秒直接给结果、冲突或最强信息点",
    structure_policy: "钩子 -> 高频信息点 -> 短证据 -> 快速收束",
    editing_playbook: "压短句间停顿，减少长镜头停留，用短段落连续推进",
    speech_rhythm_policy: "压缩停顿和重复语气词，让口播更利落",
    shot_length_policy: "多数镜头控制在 1.5-3 秒，证据镜头按理解需要稍作停留",
    keep_policy: "保留结果镜头、强变化、核心结论和最短必要证据",
    cut_policy: "删除长铺垫、弱信息解释、重复论证、等待和节奏低谷",
    packaging_strategy: "高密度包装，用字幕、强调条和节奏点维持注意力",
    transition_policy: "段落切换和信息峰值处允许快转场",
    effect_insert_policy: "在开头钩子、结果揭示、反差点和强信息点插入动态强调",
    effect_frequency: "中到高，每 8-15 秒允许 1 次明显包装或强调",
    effect_logic: "包装跟随信息峰值，不给低信息片段加装饰",
    effect_style: "快闪、速度线、弹出标题、节奏型音效点",
    expected_effect: "成片更短、更利落，适合信息流和高密度内容",
    sample_case: "同样能处理评测、教程、对比、高光；区别是整体更快、更短、更密集",
  },
  {
    strategy_type: "creator_relaxed_natural_policy",
    strategy_goal: "让成片像真实讲述，不把口播剪得过碎",
    opening_policy: "开头先自然进入主题，可以保留一句铺垫或现场语气",
    structure_policy: "自然引入 -> 重点段落 -> 解释/演示 -> 温和收束",
    editing_playbook: "保留自然呼吸、反应和现场过渡，只清掉明显冗余",
    speech_rhythm_policy: "保留短暂停顿、语气和转折，不追求每句话都顶满",
    shot_length_policy: "多数镜头 3-6 秒，操作、表情和展示镜头允许更长",
    keep_policy: "保留自然反应、现场解释、完整展示和能建立信任的上下文",
    cut_policy: "删除明显重复、长等待、跑题闲聊和技术性错误段",
    packaging_strategy: "低干扰包装，少特效，主要用字幕和轻提示辅助理解",
    transition_policy: "以硬切和自然过渡为主，少用明显转场",
    effect_insert_policy: "只在重点名词、步骤提醒和必要对比处插入轻标注",
    effect_frequency: "低，每 30-45 秒最多 1 次明显强调",
    effect_logic: "包装只解决理解问题，不为了热闹插入",
    effect_style: "轻字幕、淡入提示、少量局部放大，避免快闪和强音效",
    expected_effect: "更像真人自然表达，适合建立信任和长观看",
    sample_case: "同样能处理评测、教程、对比、高光；区别是更慢、更顺、更像真实讲述",
  },
  {
    strategy_type: "creator_professional_controlled_policy",
    strategy_goal: "在信息密度和可信度之间取中间值，成片干净有秩序",
    opening_policy: "开头先给明确主题或判断，但不使用夸张钩子",
    structure_policy: "主题 -> 依据 -> 对比/步骤 -> 结论，段落边界清楚",
    editing_playbook: "按信息层级剪辑，避免碎切和过度包装",
    speech_rhythm_policy: "去掉明显废话，但保留判断前后的解释空间",
    shot_length_policy: "多数镜头 2.5-5 秒，证据和细节镜头稳定停留",
    keep_policy: "保留证据、参数、关键步骤、对比依据和完整结论",
    cut_policy: "删除跑题、重复铺垫、无证据夸张表达和影响专业感的片段",
    packaging_strategy: "专业包装，用参数卡、对比框和小标题建立秩序",
    transition_policy: "段落间用干净短转场或标题卡，不使用花哨动效",
    effect_insert_policy: "在参数、对比结论、风险提醒处插入克制强调",
    effect_frequency: "中低，每个核心段落 1 次重点包装",
    effect_logic: "包装必须帮助建立信息层级或证据关系",
    effect_style: "低饱和、几何线框、参数卡、局部放大，偏专业感",
    expected_effect: "适合专业测评、教程和品牌型内容，质感更稳",
    sample_case: "同样能处理评测、教程、对比、高光；区别是更干净、更克制、更专业",
  },
];

function strategyValue(payload: Record<string, unknown>, key: string, fallback = "未设置") {
  const value = payload[key];
  if (Array.isArray(value)) return value.length ? value.join(" / ") : fallback;
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value || "").trim() || fallback;
}

function strategyDisplayValue(payload: Record<string, unknown>, index: number, key: string, fallback = "未设置") {
  return strategyValue(payload, key, String(STRATEGY_FALLBACKS[index % STRATEGY_FALLBACKS.length][key as keyof typeof STRATEGY_FALLBACKS[number]] || fallback));
}

function strategyList(payload: Record<string, unknown>, key: string) {
  const value = payload[key];
  return Array.isArray(value) ? value.map((item) => String(item || "").trim()).filter(Boolean) : [];
}

function strategyTone(payload: Record<string, unknown>, index: number) {
  const strategyType = strategyDisplayValue(payload, index, "strategy_type", "");
  if (strategyType.includes("comparison")) return "compare";
  if (strategyType.includes("step")) return "step";
  if (strategyType.includes("highlight")) return "highlight";
  return index % 3 === 1 ? "compare" : index % 3 === 2 ? "step" : "verdict";
}

export function TaskStrategiesPage() {
  const queryClient = useQueryClient();
  const creators = useQuery({ queryKey: ["creator-cards"], queryFn: api.listCreatorCards });
  const [selectedCreatorId, setSelectedCreatorId] = useState("");
  const [prompt, setPrompt] = useState("");
  const creatorId = selectedCreatorId || creators.data?.items[0]?.id || "";
  const strategies = useQuery({
    queryKey: ["creator-task-strategies", creatorId],
    queryFn: () => api.listTaskStrategies(creatorId),
    enabled: Boolean(creatorId),
  });
  const activeStrategy = useMemo(() => strategies.data?.items.find((item) => item.is_active) ?? strategies.data?.items[0] ?? null, [strategies.data]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["creator-task-strategies", creatorId] });
  };

  const generate = useMutation({
    mutationFn: () => api.generateTaskStrategies(creatorId, { prompt: prompt.trim(), strategy_type: "creator_bound", candidate_count: 3 }),
    onSuccess: async () => {
      setPrompt("");
      await refresh();
    },
  });
  const refine = useMutation({
    mutationFn: () => activeStrategy ? api.refineTaskStrategy(activeStrategy.id, prompt.trim()) : Promise.reject(new Error("没有可调整的策略")),
    onSuccess: async () => {
      setPrompt("");
      await refresh();
    },
  });
  const smartActionPending = generate.isPending || refine.isPending;
  const shouldRefine = Boolean(prompt.trim() && activeStrategy);
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
        title="任务策略"
        description="生成、比较、激活剪辑策略，并明确适用任务和审核门槛。"
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
              <span>策略想法</span>
              <textarea
                className="input"
                rows={2}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                placeholder="可留空智能生成；也可输入自然语言调整当前默认策略，例如：新品开箱和老款对比，开头先给结论。"
              />
            </label>
            <div className="asset-workspace-actions">
              <button type="button" className="button primary" disabled={!creatorId || smartActionPending} onClick={runSmartAction}>
                {smartActionLabel}
              </button>
              <span className="muted compact-text">{strategies.data?.items.length ?? 0} 个候选</span>
            </div>
          </div>
        </div>
        <div className="asset-workspace-results asset-workspace-results-wide">
          {strategies.data?.items.length ? strategies.data.items.map((item, index) => {
            const payload = item.strategy_payload_json as Record<string, unknown>;
            const rules = strategyList(payload, "rules");
            const tone = strategyTone(payload, index);
            return (
              <article key={item.id} className="asset-workspace-card strategy-plan-card">
                <div className={`strategy-plan-sample strategy-plan-sample-${tone}`}>
                  <div className="strategy-plan-sample-head">
                    <span>策略样品</span>
                    <strong>{strategyDisplayValue(payload, index, "strategy_goal", strategyValue(payload, "intent"))}</strong>
                  </div>
                  <div className="strategy-plan-flow">
                    <div>
                      <span>说话节奏</span>
                      <strong>{strategyDisplayValue(payload, index, "speech_rhythm_policy", strategyDisplayValue(payload, index, "opening_policy", rules[1] || "先给核心信息或结论"))}</strong>
                    </div>
                    <div>
                      <span>镜头长度</span>
                      <strong>{strategyDisplayValue(payload, index, "shot_length_policy", strategyDisplayValue(payload, index, "structure_policy", "按证据和段落重排素材"))}</strong>
                    </div>
                    <div>
                      <span>成片效果</span>
                      <strong>{strategyDisplayValue(payload, index, "expected_effect", "提升信息密度和观看完成度")}</strong>
                    </div>
                  </div>
                  <div className="strategy-plan-case">{strategyDisplayValue(payload, index, "sample_case", "按当前素材生成一条可执行剪辑策略")}</div>
                </div>
                <div className="asset-workspace-card-head">
                  <strong>{item.name}</strong>
                  {item.is_active ? <span className="job-upload-selected-pill">默认</span> : null}
                </div>
                <div className="asset-workspace-summary">{item.summary || item.strategy_type}</div>
                <div className="strategy-packaging-grid">
                  <span>包装：{strategyDisplayValue(payload, index, "packaging_strategy", "按内容重点自动选择包装强度")}</span>
                  <span>转场：{strategyDisplayValue(payload, index, "transition_policy", "只在段落切换时使用转场")}</span>
                  <span>特效：{strategyDisplayValue(payload, index, "effect_insert_policy", "在重点信息处插入强调特效")}</span>
                  <span>频率：{strategyDisplayValue(payload, index, "effect_frequency", "按信息密度控制特效频率")}</span>
                </div>
                <div className="asset-workspace-field-grid">
                  <span>保留：{strategyDisplayValue(payload, index, "keep_policy", rules[2] || "保留关键证据和结论")}</span>
                  <span>删除：{strategyDisplayValue(payload, index, "cut_policy", "删除重复、等待和无新增信息片段")}</span>
                  <span>风格：{strategyDisplayValue(payload, index, "effect_style", "按创作者风格控制包装表现")}</span>
                  <span>逻辑：{strategyDisplayValue(payload, index, "effect_logic", strategyDisplayValue(payload, index, "pacing_policy", "包装和剪辑都跟随信息重点"))}</span>
                </div>
                <details className="asset-workspace-details">
                  <summary>查看完整策略</summary>
                  <pre>{JSON.stringify(item.strategy_payload_json, null, 2)}</pre>
                </details>
                {!item.is_active ? (
                  <button type="button" className="button" onClick={() => api.activateTaskStrategy(item.id).then(refresh)}>
                    设为默认
                  </button>
                ) : null}
              </article>
            );
          }) : <div className="asset-workspace-empty">选择创作者后可直接生成默认策略。</div>}
        </div>
        </div>
      </section>
    </section>
  );
}
