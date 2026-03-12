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
import { coverStylePresets, styleLabel, subtitleStylePresets, titleStylePresets } from "../stylePresets";
import { formatBytes, formatDate } from "../utils";

const ASSET_TYPES = [
  { key: "intro", label: "片头", accept: "video/*", multiple: false },
  { key: "outro", label: "片尾", accept: "video/*", multiple: false },
  { key: "insert", label: "植入素材", accept: "video/*", multiple: true },
  { key: "music", label: "背景音乐", accept: "audio/*", multiple: true },
  { key: "watermark", label: "水印", accept: "image/*", multiple: false },
] as const;

export function PackagingPage() {
  const workspace = usePackagingWorkspace(ASSET_TYPES);
  const config = workspace.packaging.data?.config;
  const assets = workspace.packaging.data?.assets ?? {};

  return (
    <section>
      <PageHeader eyebrow="Packaging" title="包装素材" description="这里只管理素材池和渲染策略。字幕、封面、标题样式已经拆到独立的风格模板页。" actions={<Link className="button primary" to="/style-templates">打开风格模板</Link>} />

      {!config && workspace.packaging.isLoading && <div className="panel">正在加载包装配置...</div>}

      {config && (
        <>
          <section className="panel">
            <PanelHeader title="包装策略" description="原型阶段直接按能力域拆分页面，不再把素材管理和风格选择挤在一起。" />
            <div className="template-summary-grid compact-gap">
              <article className="template-summary-card">
                <span className="stat-label">字幕样式</span>
                <strong>{styleLabel(subtitleStylePresets, config.subtitle_style)}</strong>
                <p className="muted">影响成片字幕阅读气质。</p>
              </article>
              <article className="template-summary-card">
                <span className="stat-label">封面风格</span>
                <strong>{styleLabel(coverStylePresets, config.cover_style)}</strong>
                <p className="muted">决定封面底图的包装方向。</p>
              </article>
              <article className="template-summary-card">
                <span className="stat-label">标题样式</span>
                <strong>{styleLabel(titleStylePresets, config.title_style)}</strong>
                <p className="muted">决定大字布局、条幅结构和字效层级。</p>
              </article>
            </div>
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
            </div>
          </section>

          <div className="panel-grid two-up">
            {ASSET_TYPES.map((assetType) => (
              <section key={assetType.key} className="panel">
                <PanelHeader title={assetType.label} description={`${(assets[assetType.key] ?? []).length} 个素材`} actions={<label className="button ghost">
                    上传
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
                    return (
                      <ListCard key={asset.id}>
                        <div>
                          <div className="row-title">{asset.original_name}</div>
                          <div className="muted">
                            {formatBytes(asset.size_bytes)} · {formatDate(asset.created_at)}
                          </div>
                        </div>
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
                              <span>加入池</span>
                            </label>
                          ) : (
                            <button
                              className={singleSelected ? "button primary" : "button ghost"}
                              onClick={() => workspace.saveConfig.mutate({ [`${assetType.key}_asset_id`]: asset.id })}
                            >
                              {singleSelected ? "已选中" : "设为默认"}
                            </button>
                          )}
                          <a className="button ghost" href={api.packagingAssetUrl(asset.id)} target="_blank" rel="noreferrer">
                            查看
                          </a>
                          <button className="button danger" onClick={() => workspace.deleteAsset.mutate(asset.id)}>
                            删除
                          </button>
                        </ListActions>
                      </ListCard>
                    );
                  })}
                  {!assets[assetType.key]?.length && <EmptyState message="暂无素材" />}
                </div>
              </section>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
