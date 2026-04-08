import { useQuery } from "@tanstack/react-query";

import type { AvatarMaterialLibrary, Config, PackagingLibrary } from "../../types";
import { api } from "../../api";
import { ConfigProfileSwitcher } from "../configProfiles/ConfigProfileSwitcher";
import { findStylePreset, smartEffectPresets } from "../../stylePresets";

type JobReviewConfigSectionProps = {
  config?: Config;
  packaging?: PackagingLibrary;
  avatarMaterials?: AvatarMaterialLibrary;
  enhancementModes: string[];
};

export type ReviewCheck = {
  key: string;
  label: string;
  status: "ready" | "warning";
  detail: string;
};

export function JobReviewConfigSection({
  config,
  packaging,
  avatarMaterials,
  enhancementModes,
}: JobReviewConfigSectionProps) {
  const runtimeEnvironment = useQuery({ queryKey: ["config-environment"], queryFn: api.getRuntimeEnvironment });
  const reviewChecks = buildReviewChecks({
    enhancementModes,
    config,
    runtimeEnvironment: runtimeEnvironment.data,
    packaging,
    avatarMaterials,
  });

  return (
    <section className="detail-block review-config-block">
      <div className="detail-key">方案与审核</div>
      <div className="notice">
        审核页不再展开所有参数，只保留方案切换和审核检查。
      </div>
      <div className="notice compact-top">
        这里会提示资源是否齐全、服务是否可用，以及是否会自动降级。
      </div>
      <ConfigProfileSwitcher
        compact
        description="切换方案后，当前任务会按最新方案审核。"
      />

      <article className="review-config-card top-gap">
        <div className="stat-label">审核就绪检查</div>
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
    </section>
  );
}

export function buildReviewChecks({
  enhancementModes,
  config,
  runtimeEnvironment,
  packaging,
  avatarMaterials,
}: {
  enhancementModes: string[];
  config?: Config;
  runtimeEnvironment?: { voice_clone_api_base_url?: string };
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
    const indexTtsReady = config?.voice_provider === "indextts2"
      && Boolean(String(runtimeEnvironment?.voice_clone_api_base_url ?? "").trim());
    const runningHubReady = config?.voice_provider === "runninghub"
      && config.voice_clone_api_key_set
      && Boolean(String(config.voice_clone_voice_id ?? "").trim());
    checks.push({
      key: "ai_director",
      label: "AI 导演重配音",
      status: indexTtsReady || runningHubReady ? "ready" : "warning",
      detail: indexTtsReady
        ? `当前走 IndexTTS2 accel 主实例，本地服务：${runtimeEnvironment?.voice_clone_api_base_url}；会自动做情绪文本和强度控制。`
        : runningHubReady
        ? `当前走 RunningHub，工作流 / voice id：${config?.voice_clone_voice_id}`
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
