import type { AvatarMaterialLibrary, Config, Job, PackagingAsset, PackagingLibrary, SelectOption } from "../../types";
import {
  copyStylePresets,
  coverStylePresets,
  findStylePreset,
  smartEffectPresets,
  subtitleStylePresets,
  titleStylePresets,
} from "../../stylePresets";
import { enhancementModeLabel, workflowModeLabel } from "./constants";

type JobReviewConfigSectionProps = {
  selectedJob?: Job;
  config?: Config;
  packaging?: PackagingLibrary;
  avatarMaterials?: AvatarMaterialLibrary;
  workflowMode: string;
  enhancementModes: string[];
  workflowOptions: SelectOption[];
  enhancementOptions: SelectOption[];
  copyStyle: string;
  onWorkflowModeChange: (value: string) => void;
  onEnhancementModesChange: (value: string[]) => void;
  onCopyStyleChange: (value: string) => void;
};

export type ReviewCheck = {
  key: string;
  label: string;
  status: "ready" | "warning";
  detail: string;
};

export function JobReviewConfigSection({
  selectedJob,
  config,
  packaging,
  avatarMaterials,
  workflowMode,
  enhancementModes,
  workflowOptions,
  enhancementOptions,
  copyStyle,
  onWorkflowModeChange,
  onEnhancementModesChange,
  onCopyStyleChange,
}: JobReviewConfigSectionProps) {
  const packagingAssets = flattenPackagingAssets(packaging);
  const packagingSummary = [
    { label: "片头", value: assetLabel(packagingAssets, packaging?.config.intro_asset_id) },
    { label: "片尾", value: assetLabel(packagingAssets, packaging?.config.outro_asset_id) },
    { label: "转场 / 包装插片", value: listAssetLabels(packagingAssets, packaging?.config.insert_asset_ids) },
    { label: "水印", value: assetLabel(packagingAssets, packaging?.config.watermark_asset_id) },
    { label: "音乐", value: listAssetLabels(packagingAssets, packaging?.config.music_asset_ids) },
  ];
  const styleSummary = [
    {
      label: "字幕风格",
      value: findStylePreset(subtitleStylePresets, packaging?.config.subtitle_style ?? "")?.label ?? packaging?.config.subtitle_style ?? "未设置",
    },
    {
      label: "封面模板",
      value: findStylePreset(coverStylePresets, packaging?.config.cover_style ?? "")?.label ?? packaging?.config.cover_style ?? "未设置",
    },
    {
      label: "标题模板",
      value: findStylePreset(titleStylePresets, packaging?.config.title_style ?? "")?.label ?? packaging?.config.title_style ?? "未设置",
    },
    {
      label: "文案风格",
      value: findStylePreset(copyStylePresets, copyStyle)?.label ?? copyStyle ?? "未设置",
    },
    {
      label: "智能剪辑特效",
      value:
        findStylePreset(smartEffectPresets, packaging?.config.smart_effect_style ?? "")?.label
        ?? packaging?.config.smart_effect_style
        ?? "未设置",
    },
  ];
  const reviewChecks = buildReviewChecks({
    enhancementModes,
    config,
    packaging,
    avatarMaterials,
  });
  const inheritedModes = sameStringArray(
    config?.default_job_enhancement_modes ?? [],
    enhancementModes,
  ) && (config?.default_job_workflow_mode ?? "standard_edit") === workflowMode;

  return (
    <section className="detail-block review-config-block">
      <div className="detail-key">核对配置</div>
      <div className="notice">
        自动入队任务会先继承你上次确认过的习惯，再在这里二次确认增强模式、包装素材和风格模板。
        {inheritedModes ? " 当前选项已与最近一次确认的默认习惯一致。" : " 当前选项已偏离最近默认习惯，确认后会覆盖为新的默认值。"}
      </div>

      <div className="review-config-grid top-gap">
        <article className="review-config-card">
          <div className="stat-label">创作模式</div>
          <div className="form-stack compact-top">
            <label>
              <span>工作流模式</span>
              <select className="input" value={workflowMode} onChange={(event) => onWorkflowModeChange(event.target.value)}>
                {workflowOptions.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="muted">当前任务：{selectedJob ? workflowModeLabel(selectedJob.workflow_mode) : "—"}，本次确认后默认沿用：{workflowModeLabel(workflowMode)}</div>
            <label>
              <span>文案风格</span>
              <select className="input" value={copyStyle} onChange={(event) => onCopyStyleChange(event.target.value)}>
                {copyStylePresets.map((preset) => (
                  <option key={preset.key} value={preset.key}>
                    {preset.label}
                  </option>
                ))}
              </select>
            </label>
            <div className="muted">这是全局文案口吻，会同时影响封面、标题和简介，确认后自动继承为后续默认。</div>
            <div className="muted">平台会自动做二次适配：B站更强调信息密度，小红书更偏分享质感，抖音更偏爆点短句，快手更直给，视频号更稳妥。</div>
            <div className="review-mode-list">
              {enhancementOptions.map((option) => {
                const checked = enhancementModes.includes(option.value);
                return (
                  <label key={option.value} className="review-mode-row">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        onEnhancementModesChange(
                          event.target.checked
                            ? [...enhancementModes, option.value]
                            : enhancementModes.filter((item) => item !== option.value),
                        )
                      }
                    />
                    <span>{option.label}</span>
                  </label>
                );
              })}
              {!enhancementOptions.length ? <div className="muted">暂无可选增强模式</div> : null}
            </div>
          </div>
        </article>

        <article className="review-config-card">
          <div className="stat-label">增强模式素材检查</div>
          <div className="list-stack compact-top">
            {reviewChecks.map((item) => (
              <div key={item.key} className="avatar-rule-row">
                <span className={`status-pill ${item.status === "ready" ? "done" : "failed"}`}>
                  {item.status === "ready" ? "齐全" : "待补"}
                </span>
                <div>
                  <div>{item.label}</div>
                  <div className="muted compact-top">{item.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </article>
      </div>

      <div className="review-config-grid top-gap">
        <article className="review-config-card">
          <div className="stat-label">包装素材清单</div>
          <div className="list-stack compact-top">
            {packagingSummary.map((item) => (
              <div key={item.label} className="summary-row">
                <strong>{item.label}</strong>
                <span className="muted">{item.value}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="review-config-card">
          <div className="stat-label">风格模板清单</div>
          <div className="list-stack compact-top">
            {styleSummary.map((item) => (
              <div key={item.label} className="summary-row">
                <strong>{item.label}</strong>
                <span className="muted">{item.value}</span>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

export function buildReviewChecks({
  enhancementModes,
  config,
  packaging,
  avatarMaterials,
}: {
  enhancementModes: string[];
  config?: Config;
  packaging?: PackagingLibrary;
  avatarMaterials?: AvatarMaterialLibrary;
}): ReviewCheck[] {
  const checks: ReviewCheck[] = [
    {
      key: "packaging",
      label: "包装素材与风格模板",
      status: packaging?.config.enabled ? "ready" : "warning",
      detail: packaging?.config.enabled
        ? "全局包装已启用，审核后会沿用当前包装素材池与风格模板。"
        : "全局包装当前关闭，成片会跳过片头片尾、水印和背景音乐包装。",
    },
  ];

  if (enhancementModes.includes("avatar_commentary")) {
    const presenterId = String(config?.avatar_presenter_id ?? "").trim();
    const hasPresenter = Boolean(presenterId);
    const readyProfile = (avatarMaterials?.profiles ?? []).find((profile) => profile.capability_status.preview === "ready");
    checks.push({
      key: "avatar_commentary",
      label: "数字人解说",
      status: hasPresenter || Boolean(readyProfile) ? "ready" : "warning",
      detail: hasPresenter
        ? `已绑定数字人模板：${presenterId}${readyProfile ? `；另有可自动切换档案：${readyProfile.display_name}` : "；渲染时会优先使用这个模板生成画中画数字人口播。"}`
        : readyProfile
        ? `未显式绑定 avatar_presenter_id，但已有可用数字人档案：${readyProfile.display_name}；渲染时会自动选用该档案完成数字人解说。`
        : "已启用数字人解说，但当前既没有 avatar_presenter_id，也没有 preview 就绪的数字人档案；本次任务会退回普通成片，不会生成数字人口播画中画。",
    });
  }

  if (enhancementModes.includes("ai_effects")) {
    const packagingEnabled = Boolean(packaging?.config.enabled);
    const hasInsert = Boolean(packaging?.config.insert_asset_ids?.length);
    checks.push({
      key: "ai_effects",
      label: "智能剪辑特效",
      status: packagingEnabled ? "ready" : "warning",
      detail: packagingEnabled
        ? hasInsert
          ? `已启用智能剪辑特效，当前风格为 ${findStylePreset(smartEffectPresets, packaging?.config.smart_effect_style ?? "")?.label ?? (packaging?.config.smart_effect_style ?? "未设置")}；包装配置里也包含插片/转场素材，可直接叠加节奏强化效果。`
          : `已启用智能剪辑特效，当前风格为 ${findStylePreset(smartEffectPresets, packaging?.config.smart_effect_style ?? "")?.label ?? (packaging?.config.smart_effect_style ?? "未设置")}；将基于剪辑时间线自动补转场、强调动画与局部视觉强化。`
        : "已启用智能剪辑特效，但当前全局包装关闭，最终只会保留基础剪辑层，特效空间较有限。",
    });
  }

  if (enhancementModes.includes("ai_director")) {
    const runningHubReady = config?.voice_provider === "runninghub"
      && config.voice_clone_api_key_set
      && Boolean(String(config.voice_clone_voice_id ?? "").trim());
    const edgeReady = config?.voice_provider === "edge";
    checks.push({
      key: "ai_director",
      label: "AI 导演重配音",
      status: runningHubReady || edgeReady ? "ready" : "warning",
      detail: runningHubReady
        ? `当前走 RunningHub，工作流 / voice id：${config?.voice_clone_voice_id}`
        : edgeReady
        ? "当前走 Edge TTS，可快速重配音，但不会保留严格一致的克隆音色。"
        : "已启用 AI 导演，但语音 provider 配置还不完整，缺少可用的 TTS / 语音克隆执行入口。",
    });
  }

  if (!enhancementModes.length) {
    checks.push({
      key: "enhancements_off",
      label: "增强模式",
      status: "ready",
      detail: "当前未启用额外增强模式，本次将按标准成片继续执行。",
    });
  }

  return checks;
}

function flattenPackagingAssets(packaging?: PackagingLibrary): Record<string, PackagingAsset> {
  return Object.fromEntries(
    Object.values(packaging?.assets ?? {})
      .flat()
      .map((item) => [item.id, item]),
  );
}

function assetLabel(assets: Record<string, PackagingAsset>, assetId?: string | null): string {
  if (!assetId) return "未选择";
  return assets[assetId]?.original_name ?? assetId;
}

function listAssetLabels(assets: Record<string, PackagingAsset>, assetIds?: string[] | null): string {
  if (!assetIds?.length) return "未选择";
  return assetIds.map((assetId) => assetLabel(assets, assetId)).join("、");
}

function sameStringArray(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false;
  const leftSorted = [...left].sort();
  const rightSorted = [...right].sort();
  return leftSorted.every((item, index) => item === rightSorted[index]);
}
