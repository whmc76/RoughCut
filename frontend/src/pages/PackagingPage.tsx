import { Link } from "react-router-dom";
import { api } from "../api";
import { SelectField } from "../components/forms/SelectField";
import { TextField } from "../components/forms/TextField";
import { EmptyState } from "../components/ui/EmptyState";
import { ListActions } from "../components/ui/ListActions";
import { ListCard } from "../components/ui/ListCard";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { usePackagingWorkspace } from "../features/packaging/usePackagingWorkspace";
import { useI18n } from "../i18n";
import { formatBytes, formatDate } from "../utils";
import type { PackagingAsset } from "../types";

const ASSET_TYPES = [
  { key: "intro", label: "片头", accept: "video/*", multiple: false },
  { key: "outro", label: "片尾", accept: "video/*", multiple: false },
  { key: "insert", label: "植入素材", accept: "video/*", multiple: true },
  { key: "music", label: "背景音乐", accept: "audio/*", multiple: true },
  { key: "watermark", label: "水印", accept: "image/*", multiple: false },
] as const;

export function PackagingPage() {
  const { t } = useI18n();
  const workspace = usePackagingWorkspace(ASSET_TYPES);
  const config = workspace.packaging.data?.config;
  const assets = workspace.packaging.data?.assets ?? {};

  return (
    <section>
      <PageHeader
        eyebrow={t("packaging.page.eyebrow")}
        title={t("packaging.page.title")}
        description={t("packaging.page.description")}
        actions={<Link className="button primary" to="/style-templates">{t("packaging.page.openStyles")}</Link>}
      />

      {!config && workspace.packaging.isLoading && <div className="panel">{t("packaging.page.loading")}</div>}

      {config && (
        <>
          <section className="panel">
            <PanelHeader title={t("packaging.strategy.title")} description={t("packaging.strategy.description")} />
            <div className="form-grid three-up">
              <SelectField
                label="启用包装"
                value={String(config.enabled)}
                onChange={(event) => workspace.saveConfig.mutate({ enabled: event.target.value === "true" })}
                options={[
                  { value: "true", label: "启用" },
                  { value: "false", label: "停用" },
                ]}
              />
              <SelectField
                label="植入策略"
                value={config.insert_selection_mode}
                onChange={(event) => workspace.saveConfig.mutate({ insert_selection_mode: event.target.value })}
                options={[
                  { value: "manual", label: "manual" },
                  { value: "random", label: "random" },
                ]}
              />
              <SelectField
                label="植入位置"
                value={config.insert_position_mode}
                onChange={(event) => workspace.saveConfig.mutate({ insert_position_mode: event.target.value })}
                options={[
                  { value: "llm", label: "llm" },
                  { value: "midpoint", label: "midpoint" },
                  { value: "manual", label: "manual" },
                ]}
              />
              <SelectField
                label="音乐策略"
                value={config.music_selection_mode}
                onChange={(event) => workspace.saveConfig.mutate({ music_selection_mode: event.target.value })}
                options={[
                  { value: "random", label: "random" },
                  { value: "manual", label: "manual" },
                ]}
              />
              <SelectField
                label="循环策略"
                value={config.music_loop_mode}
                onChange={(event) => workspace.saveConfig.mutate({ music_loop_mode: event.target.value })}
                options={[
                  { value: "loop_single", label: "单曲循环铺满" },
                  { value: "loop_all", label: "多曲循环轮播" },
                ]}
              />
              <TextField
                label="音乐音量"
                type="number"
                min="0.05"
                max="1"
                step="0.01"
                value={String(config.music_volume)}
                onChange={(event) => workspace.saveConfig.mutate({ music_volume: Number(event.target.value) })}
              />
              <SelectField
                label="水印位置"
                value={config.watermark_position}
                onChange={(event) => workspace.saveConfig.mutate({ watermark_position: event.target.value })}
                options={[
                  { value: "top_right", label: "top_right" },
                  { value: "top_left", label: "top_left" },
                  { value: "bottom_right", label: "bottom_right" },
                  { value: "bottom_left", label: "bottom_left" },
                ]}
              />
              <TextField
                label="水印透明度"
                type="number"
                min="0.1"
                max="1"
                step="0.01"
                value={String(config.watermark_opacity)}
                onChange={(event) => workspace.saveConfig.mutate({ watermark_opacity: Number(event.target.value) })}
              />
              <TextField
                label="水印宽度比例"
                type="number"
                min="0.05"
                max="0.5"
                step="0.01"
                value={String(config.watermark_scale)}
                onChange={(event) => workspace.saveConfig.mutate({ watermark_scale: Number(event.target.value) })}
              />
              <SelectField
                label="导出分辨率模式"
                value={config.export_resolution_mode ?? "source"}
                onChange={(event) => workspace.saveConfig.mutate({ export_resolution_mode: event.target.value })}
                options={[
                  { value: "source", label: "保留原分辨率" },
                  { value: "specified", label: "指定分辨率" },
                ]}
              />
              <SelectField
                label="指定分辨率"
                value={config.export_resolution_preset ?? "1080p"}
                onChange={(event) => workspace.saveConfig.mutate({ export_resolution_preset: event.target.value })}
                options={[
                  { value: "1080p", label: "1080p" },
                  { value: "1440p", label: "2K" },
                  { value: "2160p", label: "4K" },
                ]}
              />
            </div>
          </section>

          <div className="panel-grid two-up">
            {ASSET_TYPES.map((assetType) => (
              <section key={assetType.key} className="panel">
                <PanelHeader title={assetType.label} description={`${(assets[assetType.key] ?? []).length} ${t("packaging.assets.count")}`} actions={<label className="button ghost">
                    {t("packaging.assets.upload")}
                    <input
                      type="file"
                      accept={assetType.accept}
                      multiple={assetType.multiple}
                      hidden
                      onChange={(event) => workspace.uploaders[assetType.key](event.target.files)}
                    />
                  </label>} />
                <div className="list-stack">
                    {(assets[assetType.key] ?? []).map((asset) => {
                    const singleSelected = config[`${assetType.key}_asset_id` as keyof typeof config] === asset.id;
                    const poolSelected =
                      assetType.key === "insert"
                        ? config.insert_asset_ids.includes(asset.id)
                        : assetType.key === "music"
                          ? config.music_asset_ids.includes(asset.id)
                          : false;
                    const watermarkPreprocessed = assetType.key === "watermark" && asset.watermark_preprocessed;
                        return (
                      <ListCard key={asset.id}>
                        <div>
                          <div className="row-title">{asset.original_name}</div>
                          <div className="muted">
                            {formatBytes(asset.size_bytes)} · {formatDate(asset.created_at)}
                          </div>
                          {watermarkPreprocessed ? (
                            <div className="mode-chip-list top-gap">
                              <span className="mode-chip">抠图结果</span>
                              <span className="mode-chip subtle">背景已去除</span>
                            </div>
                          ) : null}
                        </div>
                        <div className="packaging-asset-preview">{renderPackagingAssetPreview(asset, assetType.key)}</div>
                        <ListActions>
                          {assetType.key === "insert" || assetType.key === "music" ? (
                            <label className="checkbox-row">
                              <input
                                type="checkbox"
                                checked={poolSelected}
                                onChange={(event) =>
                                  workspace.togglePool(assetType.key === "insert" ? "insert_asset_ids" : "music_asset_ids", asset.id, event.target.checked)
                                }
                              />
                              <span>{t("packaging.assets.addToPool")}</span>
                            </label>
                          ) : (
                            <button
                              className={singleSelected ? "button primary" : "button ghost"}
                              onClick={() => workspace.saveConfig.mutate({ [`${assetType.key}_asset_id`]: asset.id })}
                            >
                              {singleSelected ? t("packaging.assets.selected") : t("packaging.assets.setDefault")}
                            </button>
                          )}
                          <a className="button ghost" href={api.packagingAssetUrl(asset.id)} target="_blank" rel="noreferrer">
                            {t("packaging.assets.view")}
                          </a>
                          <button className="button danger" onClick={() => workspace.deleteAsset.mutate(asset.id)}>
                            {t("packaging.assets.delete")}
                          </button>
                        </ListActions>
                      </ListCard>
                    );
                  })}
                  {!assets[assetType.key]?.length && <EmptyState message={t("packaging.assets.empty")} />}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function renderPackagingAssetPreview(asset: PackagingAsset, assetType: string) {
  if (assetType === "watermark") {
    return (
      <div className="packaging-watermark-preview">
        <img
          src={api.packagingAssetUrl(asset.id)}
          className="packaging-image-preview"
          alt={asset.original_name}
        />
      </div>
    );
  }

  if (assetType === "music") {
    return <audio className="packaging-audio-player" src={api.packagingAssetUrl(asset.id)} controls />;
  }

  if (assetType === "intro" || assetType === "outro" || assetType === "insert") {
    return (
      <video
        className="packaging-video-preview"
        src={api.packagingAssetUrl(asset.id)}
        controls
        playsInline
        preload="metadata"
      />
    );
  }

  return null;
}
