import { CheckboxField } from "../../components/forms/CheckboxField";
import { SelectField } from "../../components/forms/SelectField";
import { TextField } from "../../components/forms/TextField";
import { PanelHeader } from "../../components/ui/PanelHeader";
import type { Config } from "../../types";
import { CODEX_RUNNER_EFFORT_OPTIONS, COVER_IMAGE_BACKEND_OPTIONS, type SettingsForm } from "./constants";

type QualitySettingsPanelProps = {
  form: SettingsForm;
  config?: Config;
  onChange: (key: string, value: string | number | boolean) => void;
};

export function QualitySettingsPanel({ form, config, onChange }: QualitySettingsPanelProps) {
  const profileBindableCount = config?.profile_bindable_keys.length ?? 0;
  const autoConfirmEnabled = true;
  const glossaryAutoEnabled = Boolean(form.auto_accept_glossary_corrections);
  const coverAutoEnabled = Boolean(form.auto_select_cover_variant);
  const rerunEnabled = Boolean(form.quality_auto_rerun_enabled);
  const contentProfileThreshold = Number(form.content_profile_review_threshold ?? 0.9);
  const contentProfileMinAccuracy = Number(form.content_profile_auto_review_min_accuracy ?? 0.9);
  const contentProfileMinSamples = Number(form.content_profile_auto_review_min_samples ?? 20);
  const glossaryThreshold = Number(form.glossary_correction_review_threshold ?? 0.9);
  const coverGap = Number(form.cover_selection_review_gap ?? 0.08);
  const coverImageGenerationEnabled = Boolean(form.intelligent_copy_cover_image_generation_enabled ?? true);
  const coverImageBackend = String(form.intelligent_copy_cover_image_backend ?? "codex_builtin");
  const coverCodexRunnerModel = String(form.intelligent_copy_cover_codex_runner_model ?? "gpt-5.4-mini");
  const coverCodexRunnerEffort = String(form.intelligent_copy_cover_codex_runner_effort ?? "low");
  const packagingGap = Number(form.packaging_selection_review_gap ?? 0.08);
  const packagingMinScore = Number(form.packaging_selection_min_score ?? 0.6);
  const rerunBelowScore = Number(form.quality_auto_rerun_below_score ?? 75);
  const rerunMaxAttempts = Number(form.quality_auto_rerun_max_attempts ?? 1);
  const advancedQualityOpen =
    Math.abs(contentProfileThreshold - 0.9) > 0.001 ||
    Math.abs(contentProfileMinAccuracy - 0.9) > 0.001 ||
    contentProfileMinSamples !== 20 ||
    Math.abs(glossaryThreshold - 0.9) > 0.001 ||
    Math.abs(coverGap - 0.08) > 0.001 ||
    !coverImageGenerationEnabled ||
    coverImageBackend !== "codex_builtin" ||
    coverCodexRunnerModel !== "gpt-5.4-mini" ||
    coverCodexRunnerEffort !== "low" ||
    Math.abs(packagingGap - 0.08) > 0.001 ||
    Math.abs(packagingMinScore - 0.6) > 0.001 ||
    rerunBelowScore !== 75 ||
    rerunMaxAttempts !== 1;
  const summaryParts = [
    `画像异常门 ${contentProfileThreshold.toFixed(2)} / ${contentProfileMinAccuracy.toFixed(2)} / ${contentProfileMinSamples}`,
    glossaryAutoEnabled ? `术语 ${glossaryThreshold.toFixed(2)}` : "术语手动确认",
    coverImageGenerationEnabled ? `生图 ${coverImageBackend}` : "生图关闭",
    `包装 ${packagingMinScore.toFixed(2)}`,
    rerunEnabled ? `复跑 < ${rerunBelowScore} · ${rerunMaxAttempts} 次` : "低分复跑关闭",
  ];

  return (
    <section className="panel settings-quality-panel">
      <PanelHeader
        title="质检与自动化"
        description={`影响审核、包装和复跑。当前有 ${profileBindableCount} 项会随配置方案绑定。`}
      />
      <div className="form-stack">
        <CheckboxField
          label="启用事实核查（预留）"
          checked={Boolean(form.fact_check_enabled)}
          disabled
          onChange={(event) => onChange("fact_check_enabled", event.target.checked)}
        />
        <div className="muted">事实核查配置项目前未接入任务运行链路，保留显示仅用于兼容旧配置，不会影响当前任务执行。</div>
        <CheckboxField
          label="内容画像异常门自动放行"
          checked
          disabled
          onChange={(event) => onChange("auto_confirm_content_profile", event.target.checked)}
        />
        <div className="muted">内容画像默认自动继续，只有主体冲突、字幕阻塞或质量门异常才暂停；下方阈值仅作为诊断和复跑参考。</div>
        <CheckboxField
          label="允许自动接受术语修正"
          checked={glossaryAutoEnabled}
          onChange={(event) => onChange("auto_accept_glossary_corrections", event.target.checked)}
        />
        <CheckboxField
          label="允许自动选封面"
          checked={coverAutoEnabled}
          onChange={(event) => onChange("auto_select_cover_variant", event.target.checked)}
        />
        <CheckboxField
          label="启用智能发布封面生图"
          checked={coverImageGenerationEnabled}
          onChange={(event) => onChange("intelligent_copy_cover_image_generation_enabled", event.target.checked)}
        />
        <CheckboxField
          label="去除字幕口癖和填充词"
          checked={Boolean(form.subtitle_filler_cleanup_enabled)}
          onChange={(event) => onChange("subtitle_filler_cleanup_enabled", event.target.checked)}
        />
        <CheckboxField
          label="启用低分自动复跑"
          checked={rerunEnabled}
          onChange={(event) => onChange("quality_auto_rerun_enabled", event.target.checked)}
        />
        <details className="settings-disclosure" open={advancedQualityOpen}>
          <summary className="settings-disclosure-trigger">
            <div>
              <strong>阈值与复跑策略</strong>
              <div className="muted">{summaryParts.join(" · ")}</div>
            </div>
          </summary>
          <div className="settings-disclosure-body">
            <div className="form-stack">
              {autoConfirmEnabled ? (
                <section className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>内容画像异常门</strong>
                    <span className="muted">阈值仅作参考</span>
                  </div>
                  <div className="field-row">
                    <TextField
                      label="内容画像参考阈值"
                      type="number"
                      value={String(contentProfileThreshold)}
                      onChange={(event) => onChange("content_profile_review_threshold", Number(event.target.value))}
                    />
                    <TextField
                      label="参考最小准确率"
                      type="number"
                      value={String(contentProfileMinAccuracy)}
                      onChange={(event) => onChange("content_profile_auto_review_min_accuracy", Number(event.target.value))}
                    />
                  </div>
                  <TextField
                    label="参考最小样本量"
                    type="number"
                    value={String(contentProfileMinSamples)}
                    onChange={(event) => onChange("content_profile_auto_review_min_samples", Number(event.target.value))}
                  />
                </section>
              ) : null}
              {glossaryAutoEnabled ? (
                <section className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>术语修正自动接受</strong>
                    <span className="muted">仅显示生效阈值</span>
                  </div>
                  <TextField
                    label="术语修正确认阈值"
                    type="number"
                    value={String(glossaryThreshold)}
                    onChange={(event) => onChange("glossary_correction_review_threshold", Number(event.target.value))}
                  />
                </section>
              ) : null}
              <section className="settings-subsection">
                <div className="settings-subsection-head">
                  <strong>包装复核</strong>
                  <span className="muted">{coverAutoEnabled ? "显示封面与包装间隔" : "仅保留最低通过分"}</span>
                </div>
                {coverAutoEnabled ? (
                  <div className="field-row">
                    <TextField
                      label="封面复核间隔"
                      type="number"
                      value={String(coverGap)}
                      onChange={(event) => onChange("cover_selection_review_gap", Number(event.target.value))}
                    />
                    <TextField
                      label="包装复核间隔"
                      type="number"
                      value={String(packagingGap)}
                      onChange={(event) => onChange("packaging_selection_review_gap", Number(event.target.value))}
                    />
                  </div>
                ) : null}
                <TextField
                  label="包装最低通过分"
                  type="number"
                  value={String(packagingMinScore)}
                  onChange={(event) => onChange("packaging_selection_min_score", Number(event.target.value))}
                />
              </section>
              {coverImageGenerationEnabled ? (
                <section className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>智能发布封面生图</strong>
                    <span className="muted">Codex 模型只负责执行，不决定底层画质</span>
                  </div>
                  <SelectField
                    label="封面生图后端"
                    value={coverImageBackend}
                    onChange={(event) => onChange("intelligent_copy_cover_image_backend", event.target.value)}
                    options={COVER_IMAGE_BACKEND_OPTIONS.map((backend) => ({
                      value: backend,
                      label: backend === "codex_builtin" ? "Codex 内置 image_gen" : "OpenAI Images API",
                    }))}
                  />
                  {coverImageBackend === "codex_builtin" ? (
                    <div className="field-row">
                      <TextField
                        label="Codex 执行代理模型"
                        value={coverCodexRunnerModel}
                        onChange={(event) => onChange("intelligent_copy_cover_codex_runner_model", event.target.value)}
                        placeholder="gpt-5.4-mini"
                      />
                      <SelectField
                        label="Codex 执行推理强度"
                        value={coverCodexRunnerEffort}
                        onChange={(event) => onChange("intelligent_copy_cover_codex_runner_effort", event.target.value)}
                        options={CODEX_RUNNER_EFFORT_OPTIONS.map((effort) => ({
                          value: effort,
                          label: effort,
                        }))}
                      />
                    </div>
                  ) : (
                    <>
                      <div className="field-row">
                        <TextField
                          label="Images API 模型"
                          value={String(form.intelligent_copy_cover_image_model ?? "image2")}
                          onChange={(event) => onChange("intelligent_copy_cover_image_model", event.target.value)}
                        />
                        <TextField
                          label="Images API 质量"
                          value={String(form.intelligent_copy_cover_image_quality ?? "medium")}
                          onChange={(event) => onChange("intelligent_copy_cover_image_quality", event.target.value)}
                        />
                      </div>
                      <TextField
                        label="Images API 超时秒数"
                        type="number"
                        value={String(form.intelligent_copy_cover_image_timeout_sec ?? 90)}
                        onChange={(event) => onChange("intelligent_copy_cover_image_timeout_sec", Number(event.target.value))}
                      />
                    </>
                  )}
                </section>
              ) : null}
              {rerunEnabled ? (
                <section className="settings-subsection">
                  <div className="settings-subsection-head">
                    <strong>低分自动复跑</strong>
                    <span className="muted">低于阈值时重跑</span>
                  </div>
                  <div className="field-row">
                    <TextField
                      label="触发复跑分数线"
                      type="number"
                      value={String(rerunBelowScore)}
                      onChange={(event) => onChange("quality_auto_rerun_below_score", Number(event.target.value))}
                    />
                    <TextField
                      label="最大复跑次数"
                      type="number"
                      value={String(rerunMaxAttempts)}
                      onChange={(event) => onChange("quality_auto_rerun_max_attempts", Number(event.target.value))}
                    />
                  </div>
                </section>
              ) : null}
            </div>
          </div>
        </details>
      </div>
    </section>
  );
}
