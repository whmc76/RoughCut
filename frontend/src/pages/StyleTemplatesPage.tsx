import type { CSSProperties } from "react";
import { PageHeader } from "../components/ui/PageHeader";
import { PanelHeader } from "../components/ui/PanelHeader";
import { useStyleTemplatesWorkspace } from "../features/styleTemplates/useStyleTemplatesWorkspace";
import {
  coverStyleGroups,
  coverStylePresets,
  findStylePreset,
  subtitleStyleGroups,
  subtitleStylePresets,
  titleStyleGroups,
  titleStylePresets,
  type StyleGroup,
  type StylePreset,
} from "../stylePresets";
import { classNames } from "../utils";

type SectionKind = "subtitle" | "cover" | "title";

export function StyleTemplatesPage() {
  const workspace = useStyleTemplatesWorkspace();
  const config = workspace.packaging.data?.config;

  return (
    <section>
      <PageHeader eyebrow="Style System" title="风格模板" description="样式选择独立成页，直接按分组折叠做可视化选择，不再混进素材配置。" />

      {!config && workspace.packaging.isLoading && <div className="panel">正在加载风格配置...</div>}

      {config && (
        <>
          <section className="panel">
            <PanelHeader title="当前选择" description="封面现在默认走“精彩帧 + 标题样式”组合。只有纯文案视频才建议额外强化底图风格。" />
            <div className="template-summary-grid">
              <article className="template-summary-card">
                <span className="stat-label">字幕样式</span>
                <strong>{findStylePreset(subtitleStylePresets, config.subtitle_style)?.label ?? config.subtitle_style}</strong>
                <p className="muted">{findStylePreset(subtitleStylePresets, config.subtitle_style)?.summary}</p>
              </article>
              <article className="template-summary-card">
                <span className="stat-label">封面风格</span>
                <strong>{findStylePreset(coverStylePresets, config.cover_style)?.label ?? config.cover_style}</strong>
                <p className="muted">{findStylePreset(coverStylePresets, config.cover_style)?.summary}</p>
              </article>
              <article className="template-summary-card">
                <span className="stat-label">标题样式</span>
                <strong>{findStylePreset(titleStylePresets, config.title_style)?.label ?? config.title_style}</strong>
                <p className="muted">{findStylePreset(titleStylePresets, config.title_style)?.summary}</p>
              </article>
            </div>
          </section>

          <StyleSection
            section="subtitle"
            title="字幕样式"
            description="影响成片字幕的字重、描边、信息层级和阅读气质。"
            currentKey={config.subtitle_style}
            groups={subtitleStyleGroups}
            presets={subtitleStylePresets}
            openGroups={workspace.openGroups}
            onToggleGroup={workspace.toggleGroup}
            onSelect={(value) => workspace.saveConfig.mutate({ subtitle_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="cover"
            title="封面风格"
            description="决定精彩帧外层的包装方向。纯文案视频才更依赖这个选择。"
            currentKey={config.cover_style}
            groups={coverStyleGroups}
            presets={coverStylePresets}
            openGroups={workspace.openGroups}
            onToggleGroup={workspace.toggleGroup}
            onSelect={(value) => workspace.saveConfig.mutate({ cover_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="title"
            title="标题样式"
            description="这是封面最核心的选择，决定大字布局、条幅结构和字效调性。"
            currentKey={config.title_style}
            groups={titleStyleGroups}
            presets={titleStylePresets}
            openGroups={workspace.openGroups}
            onToggleGroup={workspace.toggleGroup}
            onSelect={(value) => workspace.saveConfig.mutate({ title_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />
        </>
      )}
    </section>
  );
}

type StyleSectionProps = {
  section: SectionKind;
  title: string;
  description: string;
  currentKey: string;
  groups: StyleGroup[];
  presets: StylePreset[];
  openGroups: Record<string, boolean>;
  onToggleGroup: (section: SectionKind, groupId: string) => void;
  onSelect: (value: string) => void;
  isSaving: boolean;
};

function StyleSection({
  section,
  title,
  description,
  currentKey,
  groups,
  presets,
  openGroups,
  onToggleGroup,
  onSelect,
  isSaving,
}: StyleSectionProps) {
  return (
    <section className="panel top-gap">
      <PanelHeader title={title} description={description} actions={<span className="status-pill done">当前: {findStylePreset(presets, currentKey)?.label ?? currentKey}</span>} />

      <div className="accordion-stack">
        {groups.map((group) => {
          const sectionKey = `${section}:${group.id}`;
          const groupPresets = presets.filter((preset) => preset.groupId === group.id);
          const shouldOpen = openGroups[sectionKey] ?? groupPresets.some((preset) => preset.key === currentKey);

          return (
            <section key={group.id} className="accordion-panel">
              <button className="accordion-trigger" onClick={() => onToggleGroup(section, group.id)} type="button">
                <div>
                  <strong>{group.label}</strong>
                  <div className="muted compact-top">{group.description}</div>
                </div>
                <span className="status-pill">{shouldOpen ? "收起" : `展开 ${groupPresets.length} 款`}</span>
              </button>
              {shouldOpen && (
                <div className="preset-grid">
                  {groupPresets.map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      className={classNames("preset-card", preset.key === currentKey && "selected")}
                      onClick={() => onSelect(preset.key)}
                      disabled={isSaving}
                    >
                      <PresetPreview section={section} preset={preset} />
                      <div className="preset-copy">
                        <div className="toolbar">
                          <strong>{preset.label}</strong>
                          {preset.key === currentKey && <span className="status-pill done">已选中</span>}
                        </div>
                        <p className="muted">{preset.summary}</p>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </section>
          );
        })}
      </div>
    </section>
  );
}

function PresetPreview({ section, preset }: { section: SectionKind; preset: StylePreset }) {
  const previewStyle = {
    background: `linear-gradient(145deg, ${preset.accent}33, rgba(17, 15, 13, 0.92)), radial-gradient(circle at top right, ${preset.accent}55, transparent 34%)`,
    borderColor: `${preset.accent}66`,
  } satisfies CSSProperties;

  return (
    <div className={classNames("preset-preview", `preset-preview-${section}`)} style={previewStyle}>
      <span className="preset-badge">{preset.badge}</span>
      {section === "subtitle" && (
        <>
          <div className="mock-frame-line" />
          <div className="mock-subtitle">
            <span>{preset.sampleTop}</span>
            <strong>{preset.sampleBottom}</strong>
          </div>
          <div className="preset-foot">{preset.sampleFoot}</div>
        </>
      )}
      {section === "cover" && (
        <>
          <div className="mock-cover-frame" />
          <div className="mock-cover-copy">
            <strong>{preset.sampleTop}</strong>
            <span>{preset.sampleBottom}</span>
          </div>
          <div className="preset-foot">{preset.sampleFoot}</div>
        </>
      )}
      {section === "title" && (
        <>
          <div className="mock-title-stack">
            <strong>{preset.sampleTop}</strong>
            <span>{preset.sampleBottom}</span>
          </div>
          <div className="preset-foot">{preset.sampleFoot}</div>
        </>
      )}
    </div>
  );
}
