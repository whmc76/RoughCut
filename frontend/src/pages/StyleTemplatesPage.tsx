import { useMemo, useState, type CSSProperties } from "react";
import { PageHeader } from "../components/ui/PageHeader";
import { useStyleTemplatesWorkspace } from "../features/styleTemplates/useStyleTemplatesWorkspace";
import { useI18n } from "../i18n";
import {
  copyStyleGroups,
  copyStylePresets,
  coverStyleGroups,
  coverStylePresets,
  findStylePreset,
  smartEffectGroups,
  smartEffectPresets,
  subtitleStyleGroups,
  subtitleStylePresets,
  subtitleMotionGroups,
  subtitleMotionPresets,
  titleStyleGroups,
  titleStylePresets,
  type StyleGroup,
  type StylePreset,
} from "../stylePresets";
import { classNames } from "../utils";

type SectionKind = "subtitle" | "subtitleMotion" | "cover" | "title" | "copy" | "effects" | "avatar";

export function StyleTemplatesPage() {
  const { t } = useI18n();
  const workspace = useStyleTemplatesWorkspace();
  const config = workspace.packaging.data?.config;

  return (
    <section>
      <PageHeader eyebrow={t("style.page.eyebrow")} title={t("style.page.title")} description={t("style.page.description")} />

      {!config && workspace.packaging.isLoading && <div className="panel">{t("style.page.loading")}</div>}

      {config && (
        <>
          <StyleSection
            section="subtitle"
            title={t("style.section.subtitle")}
            description={t("style.section.subtitleDescription")}
            currentKey={config.subtitle_style}
            groups={subtitleStyleGroups}
            presets={subtitleStylePresets}
            onSelect={(value) => workspace.saveConfig.mutate({ subtitle_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />
          <StyleSection
            section="subtitleMotion"
            title={t("style.section.subtitleMotion")}
            description={t("style.section.subtitleMotionDescription")}
            currentKey={config.subtitle_motion_style ?? "motion_static"}
            groups={subtitleMotionGroups}
            presets={subtitleMotionPresets}
            onSelect={(value) => workspace.saveConfig.mutate({ subtitle_motion_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="title"
            title={t("style.section.title")}
            description={t("style.section.titleDescription")}
            currentKey={config.title_style}
            groups={titleStyleGroups}
            presets={titleStylePresets}
            onSelect={(value) => workspace.saveConfig.mutate({ title_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="copy"
            title={t("style.section.copy")}
            description={t("style.section.copyDescription")}
            currentKey={config.copy_style}
            groups={copyStyleGroups}
            presets={copyStylePresets}
            onSelect={(value) => workspace.saveConfig.mutate({ copy_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="cover"
            title={t("style.section.cover")}
            description={t("style.section.coverDescription")}
            currentKey={config.cover_style}
            groups={coverStyleGroups}
            presets={coverStylePresets}
            onSelect={(value) => workspace.saveConfig.mutate({ cover_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <StyleSection
            section="effects"
            title="智能剪辑特效"
            description="控制自动转场、镜头强调和局部视觉强化的整体风格。这个模块默认放在最下面，只在需要时再展开。"
            currentKey={config.smart_effect_style ?? "smart_effect_rhythm"}
            groups={smartEffectGroups}
            presets={smartEffectPresets}
            onSelect={(value) => workspace.saveConfig.mutate({ smart_effect_style: value })}
            isSaving={workspace.saveConfig.isPending}
          />

          <AvatarPictureInPictureSection
            config={config}
            isSaving={workspace.saveConfig.isPending}
            onChange={(patch) => workspace.saveConfig.mutate(patch)}
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
  onSelect: (value: string) => void;
  isSaving: boolean;
};

const SECTION_DESCRIPTORS: Record<SectionKind, { tag: string; cue: string; angle: string }> = {
  subtitle: { tag: "字幕", cue: "读屏优先", angle: "高对比 + 可读层级" },
  subtitleMotion: { tag: "字幕动效", cue: "节奏感", angle: "差异化时间行为" },
  cover: { tag: "封面", cue: "外观包装", angle: "点击率第一" },
  title: { tag: "封面标题", cue: "大字结构", angle: "标题主次关系 + 条幅节奏" },
  copy: { tag: "文案", cue: "语气策略", angle: "节奏、转折与结尾" },
  effects: { tag: "特效", cue: "镜头节奏", angle: "转场、强调与氛围强化" },
  avatar: { tag: "数字人", cue: "画中画", angle: "位置、尺寸与避让关系" },
};

const AVATAR_POSITION_OPTIONS = [
  { value: "top_left", label: "左上" },
  { value: "top_right", label: "右上" },
  { value: "bottom_left", label: "左下" },
  { value: "bottom_right", label: "右下" },
] as const;

const AVATAR_BORDER_COLORS = ["#F4E4B8", "#FFFFFF", "#6FD3FF", "#59F4B0", "#FF8A65", "#E47CFF"];

const SUBTITLE_RENDER_CLASS: Record<string, string> = {
  bold_yellow_outline: "subtitle-render-outline-heavy",
  bubble_pop: "subtitle-render-bubble",
  keyword_highlight: "subtitle-render-keyword",
  punch_red: "subtitle-render-contrast",
  cyber_orange: "subtitle-render-neon",
  streamer_duo: "subtitle-render-duo-tone",
  white_minimal: "subtitle-render-minimal",
  clean_box: "subtitle-render-frame",
  lime_box: "subtitle-render-mint",
  mint_outline: "subtitle-render-mint-edge",
  cobalt_pop: "subtitle-render-blue",
  sale_banner: "subtitle-render-banner",
  coupon_green: "subtitle-render-green-tag",
  amber_news: "subtitle-render-news",
  soft_shadow: "subtitle-render-soft",
  slate_caption: "subtitle-render-muted",
  doc_gray: "subtitle-render-doc",
  archive_type: "subtitle-render-archive",
  cinema_blue: "subtitle-render-cinema",
  midnight_magenta: "subtitle-render-magenta",
  rose_gold: "subtitle-render-gold",
  ivory_serif: "subtitle-render-serif",
  luxury_caps: "subtitle-render-sansserif",
  film_subtle: "subtitle-render-film",
  neon_green_glow: "subtitle-render-neon-arc",
  teaser_glow: "subtitle-render-cinema-night",
};

const SUBTITLE_RENDER_PREVIEW_STYLE: Record<string, (accent: string) => CSSProperties> = {
  "subtitle-render-green-laser": () => ({
    color: "#050505",
    fontWeight: 900,
    letterSpacing: "0.04em",
    WebkitTextStrokeWidth: "2.4px",
    WebkitTextStrokeColor: "#14ff6a",
    textShadow: "0 0 8px rgba(20,255,106,0.52), 0 0 18px rgba(20,255,106,0.35), 0 2px 6px rgba(0,0,0,0.55)",
    borderColor: "#14ff6a99",
    borderWidth: "2px",
    borderRadius: "14px",
    background: "linear-gradient(180deg, rgba(10, 25, 12, 0.62), rgba(0,0,0,0.26))",
  }),
  "subtitle-render-outline-heavy": () => ({
    color: "#070707",
    fontWeight: 900,
    letterSpacing: "0.035em",
    WebkitTextStrokeWidth: "2px",
    WebkitTextStrokeColor: "#12ff67",
    textShadow: "0 0 8px rgba(18,255,103,0.58), 0 0 18px rgba(18,255,103,0.32), 0 2px 6px rgba(0,0,0,0.55)",
    borderColor: "#12ff67bb",
    borderWidth: "2px",
    borderRadius: "14px",
    background: "linear-gradient(180deg, rgba(10, 25, 12, 0.62), rgba(0,0,0,0.26))",
  }),
  "subtitle-render-bubble": (accent) => ({
    color: "#f2f8ff",
    fontWeight: 900,
    background: `linear-gradient(120deg, ${accent}2b, #0a1017 58%, ${accent}44)`,
    borderColor: `${accent}cc`,
    borderWidth: "2px",
    borderRadius: "14px",
    boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.38), 0 8px 18px rgba(0,0,0,0.28)",
    textShadow: "0 1px 4px rgba(0,0,0,0.45)",
  }),
  "subtitle-render-keyword": () => ({
    color: "#fff",
    fontWeight: 900,
    backgroundImage: "linear-gradient(90deg, #fff3a3 0%, #fff 56%, #a8e7ff 100%)",
    backgroundClip: "text",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
    borderColor: "rgba(255,255,255,0.45)",
    letterSpacing: "0.04em",
    textShadow: "0 0 8px rgba(255, 245, 210, 0.22)",
    textTransform: "none",
  }),
  "subtitle-render-contrast": (accent) => ({
    color: "#fff5d4",
    fontWeight: 900,
    background: `linear-gradient(180deg, ${accent}40, ${accent}1a)`,
    borderColor: `${accent}b3`,
    borderStyle: "solid",
    borderWidth: "2px",
    textShadow: "0 1px 0 rgba(0,0,0,0.52), 0 0 10px rgba(255,255,255,0.25)",
    letterSpacing: "0.04em",
  }),
  "subtitle-render-neon": (accent) => ({
    color: "#fffaf0",
    fontWeight: 700,
    borderColor: `${accent}dd`,
    textShadow: `0 0 6px ${accent}b3, 0 0 16px ${accent}80, 0 2px 6px rgba(0,0,0,0.55)`,
    background: `linear-gradient(180deg, rgba(255, 255, 255, 0.09), rgba(0,0,0,0.22))`,
    letterSpacing: "0.04em",
  }),
  "subtitle-render-neon-arc": () => ({
    color: "#efffef",
    fontWeight: 800,
    borderColor: "#39ff9b88",
    background: "linear-gradient(180deg, rgba(40, 255, 158, 0.26), rgba(0,0,0,0.34))",
    boxShadow: "inset 0 0 0 1px rgba(57,255,155,0.28)",
    textShadow: "0 0 8px rgba(57,255,155,0.52), 0 0 20px rgba(57,255,155,0.32)",
  }),
  "subtitle-render-duo-tone": (accent) => ({
    color: "#e9f6ff",
    fontWeight: 800,
    borderColor: `${accent}bb`,
    background: `linear-gradient(90deg, ${accent}4a, transparent)`,
    textShadow: "0 1px 0 rgba(0,0,0,0.45), 0 0 6px rgba(255,255,255,0.22)",
    letterSpacing: "0.03em",
  }),
  "subtitle-render-minimal": (accent) => ({
    color: "#f9f9fb",
    fontWeight: 700,
    borderColor: `${accent}88`,
    background: "linear-gradient(90deg, rgba(255,255,255,0.15), transparent)",
    textShadow: "0 1px 10px rgba(0,0,0,0.22)",
  }),
  "subtitle-render-frame": (accent) => ({
    color: "#fbfbff",
    fontWeight: 800,
    borderColor: `${accent}aa`,
    borderStyle: "dashed",
    background: "linear-gradient(180deg, rgba(255,255,255,0.08), transparent)",
    textShadow: "0 1px 4px rgba(0,0,0,0.35)",
  }),
  "subtitle-render-mint": (accent) => ({
    color: "#f4fffc",
    fontWeight: 700,
    letterSpacing: "0.03em",
    borderColor: `${accent}aa`,
    background: "linear-gradient(180deg, rgba(255,255,255,0.12), rgba(0,0,0,0.25))",
    textShadow: "0 1px 3px rgba(0,0,0,0.35)",
  }),
  "subtitle-render-mint-edge": (accent) => ({
    color: "#effeff",
    fontWeight: 700,
    letterSpacing: "0.03em",
    borderColor: `${accent}c6`,
    borderWidth: "2px",
    borderStyle: "solid",
    background: "linear-gradient(180deg, rgba(24, 37, 24, 0.74), rgba(0,0,0,0.28))",
    textShadow: "0 0 8px rgba(187,242,71,0.52), 0 1px 4px rgba(0,0,0,0.42)",
  }),
  "subtitle-render-green-tag": (accent) => ({
    color: "#f4ffea",
    fontWeight: 800,
    borderLeft: "6px solid #2dff78",
    borderColor: "#2dff78bb",
    background: `linear-gradient(90deg, ${accent}1c, transparent 45%)`,
    textShadow: "0 0 10px rgba(45,255,120,0.5)",
    paddingLeft: "10px",
    letterSpacing: "0.03em",
  }),
  "subtitle-render-blue": (accent) => ({
    color: "#f8fbff",
    fontWeight: 900,
    borderColor: `${accent}bb`,
    background: `linear-gradient(180deg, ${accent}2e, ${accent}12)`,
    textShadow: "0 0 12px rgba(100, 150, 255, 0.48)",
    letterSpacing: "0.02em",
  }),
  "subtitle-render-banner": (accent) => ({
    color: "#fffaf2",
    fontWeight: 900,
    borderLeft: `6px solid ${accent}`,
    borderColor: `${accent}bb`,
    background: `linear-gradient(90deg, ${accent}3a, ${accent}15)`,
    textShadow: "0 0 6px rgba(0,0,0,0.32)",
    paddingLeft: "10px",
    letterSpacing: "0.04em",
  }),
  "subtitle-render-news": () => ({
    color: "#f5f5ec",
    fontWeight: 800,
    borderColor: "rgba(255,255,255,0.42)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.14), rgba(255,255,255,0.02))",
    fontSize: "12px",
    textShadow: "0 1px 6px rgba(0,0,0,0.3)",
    letterSpacing: "0.01em",
  }),
  "subtitle-render-soft": () => ({
    color: "#fcfaf6",
    fontWeight: 600,
    borderColor: "rgba(255,255,255,0.25)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.14), rgba(255,255,255,0.02))",
    textShadow: "0 2px 12px rgba(255,255,255,0.14)",
  }),
  "subtitle-render-muted": (accent) => ({
    color: `${accent}`,
    fontWeight: 800,
    borderColor: `${accent}99`,
    background: "linear-gradient(180deg, rgba(255,255,255,0.04), rgba(0,0,0,0.25))",
    textShadow: "0 1px 6px rgba(0,0,0,0.35)",
  }),
  "subtitle-render-doc": () => ({
    color: "#f5f2eb",
    fontFamily: "\"Georgia\", \"Times New Roman\", serif",
    fontWeight: 600,
    borderLeft: "3px solid rgba(255, 255, 255, 0.28)",
    borderColor: "rgba(255,255,255,0.2)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.08), transparent)",
    textShadow: "0 1px 6px rgba(0,0,0,0.2)",
  }),
  "subtitle-render-archive": () => ({
    color: "#f7f2e8",
    fontFamily: "\"Times New Roman\", \"SimSun\", serif",
    fontWeight: 600,
    borderLeft: "3px solid rgba(255,255,255,0.3)",
    borderColor: "rgba(255,255,255,0.22)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.08), rgba(0,0,0,0.2))",
  }),
  "subtitle-render-cinema": (accent) => ({
    color: "#f4f3ff",
    fontWeight: 800,
    fontFamily: "\"Trebuchet MS\", \"PingFang SC\", sans-serif",
    letterSpacing: "0.05em",
    borderColor: `${accent}cc`,
    background: `linear-gradient(180deg, ${accent}22, transparent)`,
    textShadow: "0 4px 16px rgba(0,0,0,0.35)",
  }),
  "subtitle-render-magenta": () => ({
    color: "#fff8ff",
    fontWeight: 900,
    borderColor: "rgba(232, 90, 168, 0.7)",
    background: "linear-gradient(180deg, rgba(232, 90, 168, 0.18), transparent)",
    textShadow: "0 0 12px rgba(232, 90, 168, 0.45)",
  }),
  "subtitle-render-gold": () => ({
    color: "#fef6eb",
    fontWeight: 700,
    fontFamily: "\"Garamond\", \"Georgia\", serif",
    fontStyle: "italic",
    borderColor: "rgba(240, 177, 155, 0.72)",
    background: "linear-gradient(180deg, rgba(240, 177, 155, 0.18), rgba(0,0,0,0.25))",
    textShadow: "0 2px 10px rgba(0,0,0,0.3)",
  }),
  "subtitle-render-sansserif": () => ({
    color: "#fffdf8",
    fontFamily: "\"Arial\", \"Helvetica Neue\", sans-serif",
    fontWeight: 800,
    letterSpacing: "0.06em",
    borderColor: "rgba(255,255,255,0.28)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.1), transparent)",
    textTransform: "uppercase",
  }),
  "subtitle-render-serif": () => ({
    color: "#fff7ec",
    fontFamily: "\"Georgia\", \"Times New Roman\", serif",
    fontWeight: 800,
    fontStyle: "italic",
    letterSpacing: "0.02em",
    borderColor: "rgba(250, 245, 232, 0.44)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.12), transparent)",
  }),
  "subtitle-render-film": () => ({
    color: "#fff5ea",
    fontWeight: 700,
    fontStyle: "italic",
    letterSpacing: "0.01em",
    borderColor: "rgba(255,255,255,0.24)",
    background: "linear-gradient(180deg, rgba(255,255,255,0.09), transparent)",
    textShadow: "0 2px 8px rgba(0,0,0,0.32)",
  }),
  "subtitle-render-cinema-night": () => ({
    color: "#f6f7ff",
    fontFamily: "\"Trebuchet MS\", \"PingFang SC\", sans-serif",
    fontWeight: 700,
    textShadow: "0 1px 6px rgba(0,0,0,0.55)",
    borderColor: "rgba(90,110,255,0.65)",
    background: "linear-gradient(180deg, rgba(90,110,255,0.25), rgba(0,0,0,0.38))",
    letterSpacing: "0.06em",
    borderRadius: "6px",
  }),
};

function getSubtitleRenderVisualStyle(accent: string, presetKey: string): CSSProperties {
  const renderClass = SUBTITLE_RENDER_CLASS[presetKey] ?? "subtitle-render-frame";
  return (
    SUBTITLE_RENDER_PREVIEW_STYLE[renderClass]?.(accent) ?? {
      color: "#fff7ed",
      borderColor: `${accent}a6`,
      background: `linear-gradient(180deg, ${accent}22, transparent)`,
    }
  );
}

const SUBTITLE_MOTION_PREVIEW_CLASS: Record<string, string> = {
  motion_static: "subtitle-motion-static",
  motion_typewriter: "subtitle-motion-typewriter",
  motion_pop: "subtitle-motion-pop",
  motion_wave: "subtitle-motion-wave",
  motion_slide: "subtitle-motion-slide",
  motion_glitch: "subtitle-motion-glitch",
  motion_ripple: "subtitle-motion-ripple",
  motion_strobe: "subtitle-motion-strobe",
  motion_echo: "subtitle-motion-echo",
};

const SUBTITLE_MOTION_PREVIEW_STYLE: Record<string, (accent: string) => CSSProperties> = {
  "subtitle-motion-static": (accent) => ({
    color: "#f8f4ee",
    borderColor: `${accent}a6`,
    background: "linear-gradient(180deg, rgba(0, 0, 0, 0.22), rgba(255, 255, 255, 0.05))",
  }),
  "subtitle-motion-typewriter": (accent) => ({
    color: "#fff5e9",
    borderColor: `${accent}b0`,
    background: `linear-gradient(90deg, ${accent}2a, rgba(0, 0, 0, 0.28))`,
  }),
  "subtitle-motion-pop": (accent) => ({
    color: "#f8ffed",
    borderColor: `${accent}99`,
    background: `linear-gradient(160deg, ${accent}26, rgba(0, 0, 0, 0.2))`,
  }),
  "subtitle-motion-wave": (accent) => ({
    color: "#f5fffb",
    borderColor: `${accent}94`,
    background: `linear-gradient(45deg, ${accent}22, rgba(0, 0, 0, 0.16))`,
  }),
  "subtitle-motion-slide": (accent) => ({
    color: "#f3fdff",
    borderColor: `${accent}9d`,
    background: `linear-gradient(180deg, ${accent}18, transparent)`,
    letterSpacing: "0.05em",
  }),
  "subtitle-motion-glitch": (accent) => ({
    color: "#f8fbff",
    borderColor: `${accent}8d`,
    background: `linear-gradient(90deg, rgba(255, 255, 255, 0.08), ${accent}22)`,
    textShadow: "0 0 12px rgba(255,255,255,0.3)",
  }),
  "subtitle-motion-ripple": (accent) => ({
    color: "#f9fcff",
    borderColor: `${accent}99`,
    background: `linear-gradient(160deg, ${accent}34, rgba(0, 0, 0, 0.18))`,
    letterSpacing: "0.06em",
  }),
  "subtitle-motion-strobe": (accent) => ({
    color: "#fffde7",
    borderColor: `${accent}aa`,
    background: `linear-gradient(130deg, ${accent}28, rgba(0, 0, 0, 0.22))`,
    textShadow: `0 0 8px ${accent}80, 0 0 14px rgba(255,255,255,0.22)`,
  }),
  "subtitle-motion-echo": (accent) => ({
    color: "#ffeef7",
    borderColor: `${accent}8f`,
    background: `linear-gradient(45deg, ${accent}26, rgba(0, 0, 0, 0.22))`,
    textShadow: "0 1px 8px rgba(0,0,0,0.42)",
  }),
};

function getSubtitleMotionVisualStyle(
  accent: string,
  presetKey: string,
): CSSProperties {
  const renderClass = SUBTITLE_MOTION_PREVIEW_CLASS[presetKey] ?? "subtitle-motion-static";
  return SUBTITLE_MOTION_PREVIEW_STYLE[renderClass]?.(accent) ?? {
    color: "#f9f6ef",
    borderColor: `${accent}a6`,
  };
}

const TITLE_RENDER_CLASS: Record<string, string> = {
  preset_default: "title-render-default",
  cyber_logo_stack: "title-render-cyber-logo",
  chrome_impact: "title-render-chrome",
  festival_badge: "title-render-badge",
  double_banner: "title-render-banner",
  comic_boom: "title-render-comic",
  luxury_gold: "title-render-luxury",
  tutorial_blueprint: "title-render-blueprint",
  magazine_clean: "title-render-magazine",
  documentary_stamp: "title-render-stamp",
  neon_night: "title-render-neon",
};

const SMART_EFFECT_RENDER_STYLE: Record<string, { frame: CSSProperties; pulse: CSSProperties; label: CSSProperties }> = {
  smart_effect_rhythm: {
    frame: {
      borderColor: "rgba(102,212,255,0.6)",
      background: "linear-gradient(135deg, rgba(102,212,255,0.18), rgba(0,0,0,0.28))",
    },
    pulse: {
      background: "linear-gradient(90deg, rgba(102,212,255,0.95), rgba(102,212,255,0.22))",
      boxShadow: "0 0 16px rgba(102,212,255,0.35)",
    },
    label: { color: "#dff7ff" },
  },
  smart_effect_punch: {
    frame: {
      borderColor: "rgba(255,123,95,0.6)",
      background: "linear-gradient(135deg, rgba(255,123,95,0.2), rgba(0,0,0,0.35))",
    },
    pulse: {
      background: "linear-gradient(90deg, rgba(255,123,95,1), rgba(255,226,147,0.3))",
      boxShadow: "0 0 18px rgba(255,123,95,0.42)",
      transform: "scaleX(1.06)",
    },
    label: { color: "#fff0eb" },
  },
  smart_effect_glitch: {
    frame: {
      borderColor: "rgba(125,137,255,0.62)",
      background: "linear-gradient(135deg, rgba(125,137,255,0.18), rgba(12,16,30,0.38))",
    },
    pulse: {
      background: "linear-gradient(90deg, rgba(125,137,255,1), rgba(255,89,190,0.36))",
      boxShadow: "0 0 18px rgba(125,137,255,0.42)",
      filter: "saturate(1.2)",
    },
    label: { color: "#eef0ff", letterSpacing: "0.06em" },
  },
  smart_effect_cinematic: {
    frame: {
      borderColor: "rgba(242,181,107,0.52)",
      background: "linear-gradient(135deg, rgba(242,181,107,0.14), rgba(0,0,0,0.42))",
    },
    pulse: {
      background: "linear-gradient(90deg, rgba(242,181,107,0.86), rgba(242,181,107,0.18))",
      boxShadow: "0 0 14px rgba(242,181,107,0.24)",
    },
    label: { color: "#fff4e6" },
  },
  smart_effect_minimal: {
    frame: {
      borderColor: "rgba(182,195,217,0.46)",
      background: "linear-gradient(135deg, rgba(182,195,217,0.08), rgba(0,0,0,0.22))",
    },
    pulse: {
      background: "linear-gradient(90deg, rgba(182,195,217,0.72), rgba(182,195,217,0.14))",
      boxShadow: "0 0 10px rgba(182,195,217,0.18)",
    },
    label: { color: "#eef3fb" },
  },
};

const TITLE_RENDER_PREVIEW_STYLE: Record<
  string,
  (accent: string) => {
    heading: CSSProperties;
    secondary: CSSProperties;
  }
> = {
  "title-render-default": (accent) => ({
    heading: {
      letterSpacing: "0.04em",
      fontFamily: "\"PingFang SC\", \"Microsoft YaHei\", sans-serif",
      textShadow: `0 4px 14px ${accent}3b`,
      fontWeight: 900,
      border: `1px solid ${accent}90`,
      background: `linear-gradient(90deg, ${accent}2a, transparent)`,
      borderRadius: "10px 3px 10px 3px",
    },
    secondary: {
      letterSpacing: "0.03em",
      fontWeight: 800,
      border: `1px solid ${accent}85`,
      background: `linear-gradient(90deg, ${accent}20, transparent)`,
    },
  }),
  "title-render-cyber-logo": (accent) => ({
    heading: {
      letterSpacing: "0.08em",
      fontFamily: "\"Orbitron\", \"Arial Black\", sans-serif",
      textShadow: `0 0 6px ${accent}8f, 0 2px 14px rgba(0,0,0,0.5)`,
      fontWeight: 900,
      border: `1px solid ${accent}bc`,
      background: `linear-gradient(180deg, ${accent}2f, transparent)`,
      textTransform: "uppercase",
      borderRadius: "12px 5px 12px 5px",
    },
    secondary: {
      fontFamily: "\"Orbitron\", \"Arial Black\", sans-serif",
      letterSpacing: "0.08em",
      fontWeight: 800,
      border: `1px solid ${accent}99`,
      background: `linear-gradient(90deg, ${accent}18, transparent)`,
      color: "#ffffff",
    },
  }),
  "title-render-chrome": (accent) => ({
    heading: {
      fontFamily: "\"Impact\", \"Arial Black\", sans-serif",
      textTransform: "uppercase",
      letterSpacing: "0.01em",
      fontWeight: 900,
      border: `1px solid ${accent}ad`,
      boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.15)",
      background: `linear-gradient(160deg, ${accent}24, rgba(255,255,255,0.06), ${accent}10)`,
      color: "#fff7ea",
      textShadow: `0 2px 10px ${accent}7f`,
      borderRadius: "8px 14px 8px 14px",
    },
    secondary: {
      fontFamily: "\"Segoe UI\", \"Arial\", sans-serif",
      fontWeight: 800,
      letterSpacing: "0.04em",
      border: `1px solid ${accent}75`,
      background: `linear-gradient(90deg, ${accent}1a, transparent)`,
      textShadow: `0 1px 8px ${accent}88`,
    },
  }),
  "title-render-badge": (accent) => ({
    heading: {
      fontFamily: "\"Noto Sans SC\", \"PingFang SC\", sans-serif",
      borderLeft: `6px solid ${accent}`,
      borderRadius: "10px",
      padding: "3px 0 2px 8px",
      fontWeight: 900,
      letterSpacing: "0.06em",
      background: `linear-gradient(90deg, ${accent}2b, transparent)`,
      textShadow: "0 2px 8px rgba(0,0,0,.45)",
    },
    secondary: {
      fontFamily: "\"Noto Sans SC\", \"PingFang SC\", sans-serif",
      fontWeight: 800,
      letterSpacing: "0.04em",
      borderLeft: `6px solid ${accent}`,
      borderRadius: "8px",
      background: `linear-gradient(90deg, ${accent}1e, transparent)`,
      padding: "4px 0 4px 8px",
    },
  }),
  "title-render-banner": (accent) => ({
    heading: {
      fontFamily: "\"Arial\", \"Helvetica Neue\", sans-serif",
      fontWeight: 900,
      letterSpacing: "0.04em",
      border: `3px solid ${accent}`,
      boxShadow: "0 0 0 1px rgba(255,255,255,0.12)",
      textShadow: "0 4px 16px rgba(0,0,0,.42)",
      transform: "skew(-2deg)",
      background: `linear-gradient(90deg, ${accent}33, ${accent}10)`,
    },
    secondary: {
      fontFamily: "\"Arial\", \"Helvetica Neue\", sans-serif",
      fontWeight: 700,
      border: `2px solid ${accent}a0`,
      letterSpacing: "0.03em",
      transform: "skew(-2deg)",
      background: `linear-gradient(90deg, ${accent}15, transparent)`,
    },
  }),
  "title-render-comic": (accent) => ({
    heading: {
      fontFamily: "\"Comic Sans MS\", \"Marker Felt\", \"Segoe UI\", sans-serif",
      fontWeight: 900,
      letterSpacing: "0.03em",
      borderRadius: "999px 10px 18px 10px",
      border: `1px solid ${accent}cc`,
      boxShadow: `inset 0 0 0 1px rgba(255,255,255,.3), 0 0 12px ${accent}66`,
      textShadow: `0 2px 6px ${accent}90`,
      transform: "rotate(-1deg)",
    },
    secondary: {
      fontFamily: "\"Comic Sans MS\", \"Marker Felt\", \"Segoe UI\", sans-serif",
      fontWeight: 800,
      letterSpacing: "0.03em",
      borderRadius: "14px",
      border: `1px solid ${accent}bb`,
      transform: "rotate(-1deg)",
      background: `linear-gradient(90deg, ${accent}20, transparent)`,
    },
  }),
  "title-render-luxury": (accent) => ({
    heading: {
      fontFamily: "\"Garamond\", \"Times New Roman\", serif",
      fontStyle: "italic",
      fontWeight: 700,
      border: `1px solid ${accent}c0`,
      borderRadius: "12px",
      letterSpacing: "0.02em",
      textShadow: "0 2px 8px rgba(10,10,10,.45)",
      background: `linear-gradient(120deg, ${accent}2d, transparent)`,
    },
    secondary: {
      fontFamily: "\"Garamond\", \"Times New Roman\", serif",
      fontWeight: 600,
      letterSpacing: "0.02em",
      border: `1px solid ${accent}9a`,
      borderRadius: "10px",
      color: "#fff8ec",
      background: `linear-gradient(90deg, ${accent}18, transparent)`,
    },
  }),
  "title-render-blueprint": (accent) => ({
    heading: {
      fontFamily: "\"Courier New\", \"Menlo\", monospace",
      fontWeight: 700,
      letterSpacing: "0.06em",
      border: `1px dashed ${accent}9f`,
      background: "linear-gradient(145deg, rgba(11, 13, 18, 0.7), rgba(255,255,255,0.1))",
      textShadow: "0 2px 10px rgba(0,0,0,.45)",
      color: "#f3fff4",
    },
    secondary: {
      fontFamily: "\"Courier New\", \"Menlo\", monospace",
      fontWeight: 600,
      letterSpacing: "0.05em",
      border: `1px dashed ${accent}8d`,
      color: "#d8ffe9",
      background: "linear-gradient(145deg, rgba(255,255,255,0.06), rgba(0,0,0,0.18))",
    },
  }),
  "title-render-magazine": (accent) => ({
    heading: {
      fontFamily: "\"Inter\", \"PingFang SC\", sans-serif",
      fontWeight: 700,
      letterSpacing: "0.02em",
      border: `1px solid ${accent}88`,
      borderRadius: "6px 24px 8px 24px",
      textShadow: "0 2px 6px rgba(0,0,0,.38)",
      color: "#fff8ee",
      background: `linear-gradient(90deg, ${accent}22, transparent)`,
    },
    secondary: {
      fontFamily: "\"Inter\", \"PingFang SC\", sans-serif",
      fontWeight: 600,
      letterSpacing: "0.04em",
      border: `1px solid ${accent}77`,
      borderRadius: "22px 8px 22px 8px",
      background: `linear-gradient(90deg, ${accent}16, transparent)`,
    },
  }),
  "title-render-stamp": (accent) => ({
    heading: {
      fontFamily: "\"Georgia\", \"Times New Roman\", serif",
      fontWeight: 800,
      letterSpacing: "0.01em",
      border: `1px solid ${accent}a6`,
      borderRadius: "3px",
      textShadow: "0 0 7px rgba(255,255,255,.2)",
      background: `linear-gradient(130deg, ${accent}2f, transparent 72%)`,
      textTransform: "uppercase",
    },
    secondary: {
      fontFamily: "\"Georgia\", \"Times New Roman\", serif",
      fontStyle: "italic",
      letterSpacing: "0.01em",
      border: `1px solid ${accent}9e`,
      borderRadius: "3px",
      textShadow: "0 0 6px rgba(255,255,255,.16)",
      background: `linear-gradient(130deg, ${accent}1d, transparent 80%)`,
    },
  }),
  "title-render-neon": (accent) => ({
    heading: {
      fontFamily: "\"Arial Black\", \"PingFang SC\", sans-serif",
      fontWeight: 900,
      letterSpacing: "0.07em",
      border: `1px solid ${accent}c8`,
      textShadow: `0 0 10px ${accent}d2, 0 3px 14px rgba(0,0,0,.38)`,
      background: `linear-gradient(120deg, ${accent}2e, rgba(0,0,0,0))`,
      boxShadow: `0 0 10px ${accent}70`,
      textTransform: "uppercase",
    },
    secondary: {
      fontFamily: "\"Arial\", \"Helvetica Neue\", sans-serif",
      fontWeight: 800,
      letterSpacing: "0.05em",
      border: `1px solid ${accent}a6`,
      background: `linear-gradient(120deg, ${accent}1f, transparent)`,
      textShadow: `0 0 8px ${accent}8a`,
      color: "#fff7f0",
    },
  }),
};

function getTitleRenderVisualStyle(
  accent: string,
  presetKey: string,
): { heading: CSSProperties; secondary: CSSProperties } {
  const renderClass = TITLE_RENDER_CLASS[presetKey] ?? "title-render-default";
  return (
    TITLE_RENDER_PREVIEW_STYLE[renderClass]?.(accent) ?? {
      heading: {
        color: "#f8f4ee",
      },
      secondary: {
        color: "#fff8ea",
      },
    }
  );
}

function StyleSection({
  section,
  title,
  description,
  currentKey,
  groups,
  presets,
  onSelect,
  isSaving,
}: StyleSectionProps) {
  const { t } = useI18n();
  const [activeTag, setActiveTag] = useState("all");
  const [isCollapsed, setIsCollapsed] = useState(true);
  const descriptor = SECTION_DESCRIPTORS[section];
  const toggleCollapsed = () => setIsCollapsed((value) => !value);

  const tagOptions = useMemo(
    () => [{ id: "all", label: t("style.filterAll") }, ...groups.map((group) => ({ id: group.id, label: group.label }))],
    [groups, t],
  );

  const filteredPresets = useMemo(() => {
    if (activeTag === "all") {
      return presets;
    }
    return presets.filter((preset) => preset.groupId === activeTag);
  }, [activeTag, presets]);

  const activeGroup = useMemo(() => groups.find((group) => group.id === activeTag), [activeTag, groups]);
  const selectedPreset = useMemo(() => findStylePreset(presets, currentKey), [currentKey, presets]);

  return (
    <section className={classNames("panel", "top-gap", "style-section", `style-section-${section}`)}>
      <div
        className="style-section-header panel-header"
        role="button"
        tabIndex={0}
        onClick={toggleCollapsed}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleCollapsed();
          }
        }}
      >
        <div>
          <h3>{title}</h3>
          {description ? <p className="muted">{description}</p> : null}
        </div>
        <div className="toolbar">
          <span className="status-pill done">{t("style.section.current")}: {findStylePreset(presets, currentKey)?.label ?? currentKey}</span>
          <button
            type="button"
            className="button button-sm"
            onClick={(event) => {
              event.stopPropagation();
              toggleCollapsed();
            }}
          >
            {isCollapsed
              ? t("style.section.expand").replace("{count}", String(filteredPresets.length))
              : t("style.section.collapse")}
          </button>
        </div>
      </div>

      {isCollapsed ? (
        <div
          className="style-section-collapsed"
          role="button"
          tabIndex={0}
          onClick={toggleCollapsed}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggleCollapsed();
            }
          }}
        >
          <div className="status-chip">{t("style.section.selected")}: {selectedPreset?.label ?? currentKey}</div>
          {selectedPreset ? (
            <div className="style-selected-card">
              <PresetPreview section={section} preset={selectedPreset} isCompact />
              <div className="style-selected-card-copy">
                <strong>{selectedPreset.label}</strong>
                <p className="muted">{selectedPreset.summary}</p>
              </div>
            </div>
          ) : (
            <p className="muted">未找到当前已选样式，请展开后重新选择。</p>
          )}
        </div>
      ) : (
        <>
          <div className="style-section-strip">
            <span className="status-pill">{descriptor.tag}</span>
            <span className="muted">聚焦：{descriptor.cue}</span>
            <span className="muted">取向：{descriptor.angle}</span>
          </div>

          <div className="style-filter-bar" role="tablist" aria-label={`${title} ${t("style.filterAll")}`}>
            {tagOptions.map((tag) => (
              <button
                key={`${section}-${tag.id}`}
                type="button"
                className={classNames("button", "button-sm", "style-filter-chip", activeTag === tag.id && "selected")}
                onClick={() => setActiveTag(tag.id)}
                aria-pressed={activeTag === tag.id}
              >
                {tag.label}
              </button>
            ))}
          </div>

          {activeGroup && (
            <div className="muted compact-top">
              {t("style.filterHint").replace("{tag}", activeGroup.label)}
            </div>
          )}

          <div className={classNames("preset-grid", filteredPresets.length ? "" : "empty-presets")}>
            {filteredPresets.map((preset) => (
              <button
                key={preset.key}
                type="button"
                className={classNames("preset-card", `preset-card-${section}`, preset.key === currentKey && "selected")}
                onClick={() => onSelect(preset.key)}
                disabled={isSaving}
              >
                <PresetPreview section={section} preset={preset} />
                <div className="preset-copy">
                  <div className="toolbar">
                    <strong>{preset.label}</strong>
                    {preset.key === currentKey && <span className="status-pill done">{t("style.section.selected")}</span>}
                  </div>
                  <p className="muted">{preset.summary}</p>
                  <PresetMeta section={section} preset={preset} />
                </div>
              </button>
            ))}
          </div>
          {filteredPresets.length === 0 ? <p className="muted" style={{ margin: "12px 0 0" }}>{t("style.filterEmpty")}</p> : null}
        </>
      )}
    </section>
  );
}

function PresetPreview({
  section,
  preset,
  isCompact = false,
}: {
  section: SectionKind;
  preset: StylePreset;
  isCompact?: boolean;
}) {
  const accent = preset.accent || "#f0b56c";
  const baseTokens = {
    "--style-accent": accent,
    "--style-accent-soft": `${accent}33`,
    "--style-text": "#f8f4ee",
    "--style-frame": "#ffffff44",
  } as CSSProperties;

  const subtitleLineStyle = useMemo<CSSProperties>(() => {
    if (section === "title") {
      return {
        color: "#fff",
        borderColor: `${accent}88`,
        background: `linear-gradient(135deg, ${accent}2a, ${accent}99)`,
      };
    }
    if (section === "copy") {
      return {
        color: "#0f0f16",
        borderColor: `${accent}66`,
        background: `linear-gradient(180deg, ${accent}d9, ${accent}66)`,
      };
    }
    if (section === "cover") {
      return {
        color: "#fffef8",
        borderColor: `${accent}aa`,
        background: `linear-gradient(135deg, ${accent}2d, ${accent}55)`,
      };
    }
    return {
      color: "#fffef6",
      borderColor: `${accent}88`,
      background: `linear-gradient(180deg, ${accent}38, ${accent}99)`,
    };
  }, [section, accent]);

  const titleLineStyle = useMemo<CSSProperties>(
    () => ({
      color: section === "subtitle" ? "#09090a" : "#f7f6ff",
      borderColor: `${accent}99`,
      background: `linear-gradient(90deg, ${accent}66, ${accent}20)`,
    }),
    [section, accent],
  );

  const subtitleRenderClass = section === "subtitle" ? SUBTITLE_RENDER_CLASS[preset.key] ?? "subtitle-render-frame" : "";
  const subtitleRenderStyle = section === "subtitle" ? getSubtitleRenderVisualStyle(accent, preset.key) : {};
  const titleRenderClass = section === "title" ? TITLE_RENDER_CLASS[preset.key] ?? "title-render-default" : "";
  const titleRenderStyle = section === "title" ? getTitleRenderVisualStyle(accent, preset.key) : null;
  const titleLineStyleForTitle = section === "title" ? { ...titleLineStyle, ...titleRenderStyle?.heading } : titleLineStyle;
  const subtitleLineStyleForTitle = section === "title" ? { ...subtitleLineStyle, ...titleRenderStyle?.secondary } : subtitleLineStyle;
  const subtitleMotionClass = section === "subtitleMotion" ? SUBTITLE_MOTION_PREVIEW_CLASS[preset.key] ?? "subtitle-motion-static" : "";
  const subtitleMotionStyle = section === "subtitleMotion" ? getSubtitleMotionVisualStyle(accent, preset.key) : {};
  const subtitleMotionWords = section === "subtitleMotion"
    ? `${preset.sampleTop} ${preset.sampleBottom}`.trim().split(/\s+/)
    : [];
  const coverFrameStyle =
    section === "cover"
      ? ({
          borderColor: `${accent}88`,
          background: `radial-gradient(circle at 72% 18%, ${accent}44, transparent 32%), linear-gradient(145deg, rgba(255,255,255,0.06), rgba(0,0,0,0.32))`,
          boxShadow: `inset 0 0 0 1px ${accent}22`,
        } satisfies CSSProperties)
      : undefined;

  return (
    <div className={classNames("preset-preview", `preset-preview-${section}`, isCompact && "preset-preview-compact")} style={baseTokens}>
      {section === "subtitle" && (
        <>
          <div className="mock-subtitle-single">
            <strong
              className={classNames("subtitle-line", "subtitle-line-single", subtitleRenderClass)}
              style={{
                ...subtitleLineStyle,
                ...subtitleRenderStyle,
                fontSize: isCompact ? "12px" : "15px",
              }}
            >
              {`${preset.sampleTop} ${preset.sampleBottom}`}
            </strong>
          </div>
        </>
      )}
      {section === "subtitleMotion" && (
        <div className="mock-subtitle-motion">
          <div className={classNames("mock-subtitle-motion-line", subtitleMotionClass)} style={subtitleMotionStyle}>
            {subtitleMotionWords.map((word, index) => (
              <span
                key={`${preset.key}-${word}-${index}`}
                className="subtitle-motion-word"
                style={{
                  animationDelay: `${index * 90}ms`,
                }}
              >
                {word}
              </span>
            ))}
          </div>
        </div>
      )}
      {section === "cover" && (
        <>
          <div className="mock-cover-frame" style={coverFrameStyle} />
          <div className="mock-cover-scene">
            <div className="mock-cover-highlight" />
            <div className="mock-cover-surface" />
            <div className="mock-cover-corner-tag">{preset.badge}</div>
            <div className="mock-cover-caption">
              <strong>{preset.label}</strong>
              <span>{preset.summary}</span>
            </div>
          </div>
        </>
      )}
      {section === "title" && (
        <>
          <div className="mock-title-cover">
            <div className="mock-title-cover-frame" />
            <div className="mock-title-cover-noise" />
            <div className="mock-title-stage">
              <span className="mock-title-tag">{preset.badge}</span>
              <div className="mock-title-stack">
                <strong className={titleRenderClass} style={titleLineStyleForTitle}>
                  {preset.sampleTop}
                </strong>
                <span className={titleRenderClass} style={subtitleLineStyleForTitle}>
                  {preset.sampleBottom}
                </span>
              </div>
              <p className="mock-title-sub">{preset.sampleFoot}</p>
            </div>
          </div>
        </>
      )}
      {section === "copy" && (
        <>
          <div className="mock-copy-stage">
            <p className="copy-title copy-title-plain">
              {preset.sampleTop}
            </p>
            <p className="copy-copy copy-copy-plain">
              {preset.sampleBottom}
            </p>
            <p className="copy-foot copy-foot-plain">
              {preset.sampleFoot}
            </p>
          </div>
        </>
      )}
      {section === "effects" && (() => {
        const visual = SMART_EFFECT_RENDER_STYLE[preset.key] ?? SMART_EFFECT_RENDER_STYLE.smart_effect_rhythm;
        return (
          <div className="mock-cover-scene" style={{ gap: "10px", justifyContent: "center" }}>
            <div
              style={{
                width: "100%",
                border: "1px solid",
                borderRadius: "14px",
                padding: isCompact ? "10px" : "12px",
                ...visual.frame,
              }}
            >
              <div
                style={{
                  height: isCompact ? "8px" : "10px",
                  borderRadius: "999px",
                  marginBottom: isCompact ? "8px" : "10px",
                  ...visual.pulse,
                }}
              />
              <div style={{ display: "grid", gap: "6px" }}>
                <strong style={{ fontSize: isCompact ? "12px" : "14px", ...visual.label }}>{preset.sampleTop}</strong>
                <span className="muted" style={{ color: "#d6dbe4" }}>{preset.sampleBottom}</span>
                <span className="muted" style={{ color: "#aab3c0" }}>{preset.sampleFoot}</span>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function PresetMeta({ section, preset }: { section: SectionKind; preset: StylePreset }) {
  const descriptor = SECTION_DESCRIPTORS[section];
  if (section === "copy") {
    return null;
  }

  const labelMap: Record<Exclude<SectionKind, "copy">, [string, string, string]> = {
    subtitle: ["字幕形态", "读屏行为", "信息权重"],
    subtitleMotion: ["动效偏好", "节奏方式", "视觉识别"],
    cover: ["封面构图", "标题钩子", "转化目标"],
    title: ["标题层级", "策略联动", "字效强度"],
    effects: ["镜头强化", "节奏方式", "整体取向"],
    avatar: ["出镜形态", "布局重点", "避让关系"],
  };

  const valueMap: Record<Exclude<SectionKind, "copy">, [string, string, string]> = {
    subtitle: [preset.badge, preset.summary, preset.sampleFoot],
    subtitleMotion: [preset.badge, descriptor.cue, preset.summary],
    cover: [preset.sampleTop, preset.sampleBottom, preset.summary],
    title: [preset.label, descriptor.cue, preset.badge],
    effects: [preset.label, preset.sampleBottom, preset.sampleFoot],
    avatar: [preset.label, descriptor.cue, descriptor.angle],
  };

  const labels = labelMap[section];
  const values = valueMap[section];

  return (
    <div className="preset-meta-grid">
      <div className="preset-meta-item">
        <span>{labels[0]}</span>
        <strong>{values[0]}</strong>
      </div>
      <div className="preset-meta-item">
        <span>{labels[1]}</span>
        <strong>{values[1]}</strong>
      </div>
      <div className="preset-meta-item">
        <span>{labels[2]}</span>
        <strong>{values[2]}</strong>
      </div>
    </div>
  );
}

function AvatarPictureInPictureSection({
  config,
  isSaving,
  onChange,
}: {
  config: {
    avatar_overlay_position: string;
    avatar_overlay_scale: number;
    avatar_overlay_corner_radius: number;
    avatar_overlay_border_width: number;
    avatar_overlay_border_color: string;
  };
  isSaving: boolean;
  onChange: (patch: Record<string, unknown>) => void;
}) {
  const [isCollapsed, setIsCollapsed] = useState(true);
  const toggleCollapsed = () => setIsCollapsed((value) => !value);
  const scalePercent = Math.round((config.avatar_overlay_scale ?? 0.28) * 100);
  const bottomAligned = String(config.avatar_overlay_position || "bottom_right").startsWith("bottom_");

  return (
    <section className={classNames("panel", "top-gap", "style-section", "style-section-avatar")}>
      <div
        className="style-section-header panel-header"
        role="button"
        tabIndex={0}
        onClick={toggleCollapsed}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggleCollapsed();
          }
        }}
      >
        <div>
          <h3>数字人画中画</h3>
          <p className="muted">控制全程数字人解说窗口的位置、尺寸、圆角和描边。字幕会按这个窗口自动避让。</p>
        </div>
        <div className="toolbar">
          <span className="status-pill done">
            {AVATAR_POSITION_OPTIONS.find((item) => item.value === config.avatar_overlay_position)?.label ?? "右下"} · {scalePercent}%
          </span>
          <button
            type="button"
            className="button button-sm"
            onClick={(event) => {
              event.stopPropagation();
              toggleCollapsed();
            }}
          >
            {isCollapsed ? "展开配置" : "收起配置"}
          </button>
        </div>
      </div>

      {isCollapsed ? (
        <div
          className="style-section-collapsed"
          role="button"
          tabIndex={0}
          onClick={toggleCollapsed}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              toggleCollapsed();
            }
          }}
        >
          <div className="status-chip">字幕避让：{bottomAligned ? "已启用底部抬升" : "顶部窗口无需抬升"}</div>
          <div className="style-selected-card">
            <AvatarOverlayPreview config={config} compact />
            <div className="style-selected-card-copy">
              <strong>当前画中画样式</strong>
              <p className="muted">
                {AVATAR_POSITION_OPTIONS.find((item) => item.value === config.avatar_overlay_position)?.label ?? "右下"}，
                尺寸 {scalePercent}% ，圆角 {config.avatar_overlay_corner_radius}px，描边 {config.avatar_overlay_border_width}px。
              </p>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="style-section-strip">
            <span className="status-pill">画中画</span>
            <span className="muted">字幕避让：{bottomAligned ? "底部字幕自动上移" : "顶部布局默认不压字幕"}</span>
            <span className="muted">预览：真实输出会沿用这里的窗口参数</span>
          </div>

          <div className="preset-grid" style={{ gridTemplateColumns: "minmax(280px, 1.1fr) minmax(280px, 1fr)" }}>
            <div className="panel" style={{ minHeight: 0 }}>
              <div className="toolbar" style={{ marginBottom: 12 }}>
                <strong>预览</strong>
                <span className="muted">主画面 + 数字人窗口 + 字幕避让</span>
              </div>
              <AvatarOverlayPreview config={config} />
            </div>

            <div className="panel" style={{ minHeight: 0 }}>
              <div style={{ display: "grid", gap: 14 }}>
                <div>
                  <div className="detail-key">位置</div>
                  <div className="toolbar" style={{ flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                    {AVATAR_POSITION_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        className={classNames("button", "button-sm", config.avatar_overlay_position === option.value && "selected")}
                        disabled={isSaving}
                        onClick={() => onChange({ avatar_overlay_position: option.value })}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                <RangeField
                  label="尺寸"
                  value={scalePercent}
                  min={18}
                  max={42}
                  suffix="%"
                  disabled={isSaving}
                  onChange={(value) => onChange({ avatar_overlay_scale: Number((value / 100).toFixed(3)) })}
                />

                <RangeField
                  label="圆角"
                  value={config.avatar_overlay_corner_radius}
                  min={0}
                  max={64}
                  suffix="px"
                  disabled={isSaving}
                  onChange={(value) => onChange({ avatar_overlay_corner_radius: value })}
                />

                <RangeField
                  label="描边宽度"
                  value={config.avatar_overlay_border_width}
                  min={0}
                  max={12}
                  suffix="px"
                  disabled={isSaving}
                  onChange={(value) => onChange({ avatar_overlay_border_width: value })}
                />

                <div>
                  <div className="detail-key">描边颜色</div>
                  <div className="toolbar" style={{ flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                    {AVATAR_BORDER_COLORS.map((color) => (
                      <button
                        key={color}
                        type="button"
                        className={classNames("button", "button-sm", config.avatar_overlay_border_color === color && "selected")}
                        disabled={isSaving}
                        onClick={() => onChange({ avatar_overlay_border_color: color })}
                        style={{ display: "flex", alignItems: "center", gap: 8 }}
                      >
                        <span style={{ width: 14, height: 14, borderRadius: 999, background: color, border: "1px solid rgba(255,255,255,.28)" }} />
                        {color}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function RangeField({
  label,
  value,
  min,
  max,
  suffix,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  suffix: string;
  disabled: boolean;
  onChange: (value: number) => void;
}) {
  return (
    <label style={{ display: "grid", gap: 8 }}>
      <div className="toolbar">
        <span className="detail-key">{label}</span>
        <span className="muted">{value}{suffix}</span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

function AvatarOverlayPreview({
  config,
  compact = false,
}: {
  config: {
    avatar_overlay_position: string;
    avatar_overlay_scale: number;
    avatar_overlay_corner_radius: number;
    avatar_overlay_border_width: number;
    avatar_overlay_border_color: string;
  };
  compact?: boolean;
}) {
  const position = String(config.avatar_overlay_position || "bottom_right");
  const scale = Math.max(0.18, Math.min(0.42, Number(config.avatar_overlay_scale || 0.28)));
  const windowWidth = `${Math.round(scale * 100)}%`;
  const avatarWindowStyle: CSSProperties = {
    position: "absolute",
    width: windowWidth,
    aspectRatio: "3 / 4",
    borderRadius: `${config.avatar_overlay_corner_radius}px`,
    border: `${config.avatar_overlay_border_width}px solid ${config.avatar_overlay_border_color}`,
    background:
      "linear-gradient(180deg, rgba(254,244,220,.18), rgba(0,0,0,.55)), radial-gradient(circle at 50% 18%, rgba(255,255,255,.24), transparent 28%), linear-gradient(180deg, #1e2532, #0d1017)",
    boxShadow: "0 14px 28px rgba(0,0,0,.3)",
    overflow: "hidden",
  };

  if (position.includes("top")) avatarWindowStyle.top = compact ? 10 : 14;
  if (position.includes("bottom")) avatarWindowStyle.bottom = compact ? 10 : 14;
  if (position.includes("left")) avatarWindowStyle.left = compact ? 10 : 14;
  if (position.includes("right")) avatarWindowStyle.right = compact ? 10 : 14;

  const subtitleStyle: CSSProperties = {
    position: "absolute",
    left: "50%",
    transform: "translateX(-50%)",
    bottom: position.startsWith("bottom_") ? (compact ? 82 : 102) : (compact ? 14 : 20),
    borderRadius: 12,
    padding: compact ? "6px 10px" : "8px 14px",
    background: "rgba(7,10,15,.82)",
    color: "#fff7d8",
    fontWeight: 800,
    letterSpacing: "0.02em",
    border: "1px solid rgba(255,255,255,.14)",
    maxWidth: "72%",
    textAlign: "center",
    fontSize: compact ? 11 : 13,
  };

  return (
    <div
      style={{
        position: "relative",
        minHeight: compact ? 132 : 220,
        borderRadius: 18,
        overflow: "hidden",
        background:
          "radial-gradient(circle at 78% 16%, rgba(98,173,255,.22), transparent 24%), linear-gradient(135deg, rgba(255,255,255,.06), rgba(0,0,0,.28)), linear-gradient(180deg, #121721, #0b0f16)",
        border: "1px solid rgba(255,255,255,.08)",
      }}
    >
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(180deg, transparent 40%, rgba(0,0,0,.32))" }} />
      <div style={{ position: "absolute", left: 14, top: 14, color: "#dce6f6", fontSize: compact ? 10 : 12 }}>主画面持续保留</div>
      <div style={avatarWindowStyle}>
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(circle at 50% 26%, rgba(255,240,214,.42), transparent 18%)" }} />
        <div style={{ position: "absolute", left: "50%", top: "18%", transform: "translateX(-50%)", width: "42%", aspectRatio: "1 / 1", borderRadius: "50%", background: "linear-gradient(180deg, #f7d7bd, #b88f76)" }} />
        <div style={{ position: "absolute", left: "50%", top: "40%", transform: "translateX(-50%)", width: "62%", height: "42%", borderRadius: "46% 46% 18% 18%", background: "linear-gradient(180deg, #2e3340, #171c24)" }} />
      </div>
      <div style={subtitleStyle}>真正的重点是：字幕会自动抬高，避开数字人窗口。</div>
    </div>
  );
}


