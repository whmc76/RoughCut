import { lazy, Suspense, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Blocks,
  BookOpenCheck,
  Brain,
  ClipboardCheck,
  Gauge,
  Library,
  PlaySquare,
  Settings,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  Wrench,
} from "lucide-react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { getProviderLabel } from "./features/settings/helpers";
import { useFrontendBuildRefresh } from "./hooks/useFrontendBuildRefresh";
import { useI18n } from "./i18n";

const OverviewPage = lazy(async () => ({ default: (await import("./pages/OverviewPage")).OverviewPage }));
const JobsPage = lazy(async () => ({ default: (await import("./pages/JobsPage")).JobsPage }));
const JobManualEditorPage = lazy(async () => ({ default: (await import("./pages/JobManualEditorPage")).JobManualEditorPage }));
const FinalReviewPage = lazy(async () => ({ default: (await import("./pages/FinalReviewPage")).FinalReviewPage }));
const WatchRootsPage = lazy(async () => ({ default: (await import("./pages/WatchRootsPage")).WatchRootsPage }));
const IntelligentCopyPage = lazy(async () => ({ default: (await import("./pages/IntelligentCopyPage")).IntelligentCopyPage }));
const PublicationTrackingPage = lazy(async () => ({ default: (await import("./pages/PublicationTrackingPage")).PublicationTrackingPage }));
const CreatorCardsPage = lazy(async () => ({ default: (await import("./pages/CreatorCardsPage")).CreatorCardsPage }));
const TaskStrategiesPage = lazy(async () => ({ default: (await import("./pages/TaskStrategiesPage")).TaskStrategiesPage }));
const VisualPlansPage = lazy(async () => ({ default: (await import("./pages/VisualPlansPage")).VisualPlansPage }));
const PublicationManagementPage = lazy(async () => ({ default: (await import("./pages/PublicationManagementPage")).PublicationManagementPage }));
const TermsMemoryPage = lazy(async () => ({ default: (await import("./pages/TermsMemoryPage")).TermsMemoryPage }));
const ToolsPage = lazy(async () => ({ default: (await import("./pages/ToolsPage")).ToolsPage }));
const TtsToolPage = lazy(async () => ({ default: (await import("./pages/ToolsPage")).TtsToolPage }));
const AsrToolPage = lazy(async () => ({ default: (await import("./pages/ToolsPage")).AsrToolPage }));
const AvatarToolPage = lazy(async () => ({ default: (await import("./pages/ToolsPage")).AvatarToolPage }));
const SettingsPage = lazy(async () => ({ default: (await import("./pages/SettingsPage")).SettingsPage }));
const ControlPage = lazy(async () => ({ default: (await import("./pages/ControlPage")).ControlPage }));

export function App() {
  const { locale, setLocale, t } = useI18n();
  const queryClient = useQueryClient();
  const syncedLocaleRef = useRef<string>("");
  const config = useQuery({ queryKey: ["config"], queryFn: api.getConfig });

  useFrontendBuildRefresh();

  const routingToggle = useMutation({
    mutationFn: (nextMode: string) => api.patchConfig({ llm_routing_mode: nextMode }),
    onSuccess: async (nextConfig) => {
      queryClient.setQueryData(["config"], nextConfig);
      await queryClient.invalidateQueries({ queryKey: ["config"] });
    },
  });

  useEffect(() => {
    if (syncedLocaleRef.current === locale) {
      return;
    }
    syncedLocaleRef.current = locale;
    void api.patchConfig({ preferred_ui_language: locale }).catch(() => {
      syncedLocaleRef.current = "";
    });
  }, [locale]);

  const navigationGroups = [
    {
      title: "工作流",
      items: [
        { to: "/", label: t("app.nav.overview"), icon: Gauge },
        { to: "/jobs", label: t("app.nav.jobs"), icon: UploadCloud },
        { to: "/final-review", label: "成片审看", icon: PlaySquare },
        { to: "/publication-tracking", label: t("app.nav.intelligentCopy"), icon: ClipboardCheck },
      ],
    },
    {
      title: "资产库",
      items: [
        { to: "/creator-cards", label: "创作者卡片", icon: Library },
        { to: "/task-strategies", label: "任务策略", icon: SlidersHorizontal },
        { to: "/visual-plans", label: "视觉方案", icon: Sparkles },
        { to: "/terms-memory", label: "术语与记忆", icon: BookOpenCheck },
      ],
    },
    {
      title: "系统",
      items: [
        { to: "/tools", label: t("app.nav.tools"), icon: Wrench },
        { to: "/settings", label: t("app.nav.settings"), icon: Settings },
        { to: "/control", label: t("app.nav.control"), icon: Blocks },
      ],
    },
  ];
  const localeOptions = [
    { value: "zh-CN" as const, shortLabel: "简中", title: t("app.language.zh-CN") },
    { value: "en-US" as const, shortLabel: "EN", title: t("app.language.en-US") },
  ];
  const hybridEnabled = config.data?.llm_mode === "performance" && config.data?.llm_routing_mode === "hybrid_performance";
  const hybridAnalysisProvider = String(config.data?.hybrid_analysis_provider ?? "openai");
  const hybridCopyProvider = String(config.data?.hybrid_copy_provider ?? "openai");

  return (
    <div className="app-shell">
      <aside className="app-rail">
        <div className="rail-brand">
          <div className="rail-brand-mark">
            <img src="/roughcut-mark.svg" alt="" aria-hidden="true" />
          </div>
          <div className="rail-brand-copy">
            <strong>RoughCut</strong>
            <span>剪辑流水线控制台</span>
          </div>
        </div>
        <nav className="rail-nav" aria-label="Primary">
          {navigationGroups.map((group) => (
            <div className="rail-nav-section" key={group.title}>
              <div className="rail-nav-section-label">{group.title}</div>
              <div className="rail-nav-section-links">
                {group.items.map((item, index) => {
                  const Icon = item.icon ?? Brain;
                  return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) => (isActive ? "rail-link active" : "rail-link")}
                  >
                    <span className="rail-link-icon" aria-hidden="true"><Icon size={16} strokeWidth={1.8} /></span>
                    <span className="rail-link-label">{item.label}</span>
                  </NavLink>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <div className="rail-notes">
          <div className="rail-mode-card">
            <span className="rail-note-label">混合模式</span>
            <strong>{hybridEnabled ? "高性能已启用" : "当前 Bundled"}</strong>
            <div className="muted">
              {config.data?.llm_mode === "local"
                ? "本地模式下固定 bundled。"
                : hybridEnabled
                  ? `摘要/字幕 ${getProviderLabel(hybridAnalysisProvider)} · 文案 ${getProviderLabel(hybridCopyProvider)}`
                  : "摘要、字幕、视觉和搜索都跟随主 Provider。"}
            </div>
            <button
              type="button"
              className={hybridEnabled ? "rail-mode-toggle active" : "rail-mode-toggle"}
              disabled={routingToggle.isPending || config.data?.llm_mode === "local"}
              onClick={() => routingToggle.mutate(hybridEnabled ? "bundled" : "hybrid_performance")}
            >
              {routingToggle.isPending ? "切换中" : hybridEnabled ? "切回 Bundled" : "启用 Hybrid"}
            </button>
          </div>
          <div className="app-stage-locale rail-locale">
            <span>{t("app.sidebar.language")}</span>
            <div className="rail-locale-options" role="group" aria-label={t("app.sidebar.language")}>
              {localeOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={locale === option.value ? "rail-locale-option active" : "rail-locale-option"}
                  onClick={() => setLocale(option.value)}
                  title={option.title}
                  aria-pressed={locale === option.value}
                >
                  {option.shortLabel}
                </button>
              ))}
            </div>
          </div>
        </div>
      </aside>
      <main className="app-stage">
        <div className="main-content">
          <Suspense fallback={<div className="route-loading" role="status">加载页面...</div>}>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/jobs/:jobId/manual-editor" element={<JobManualEditorPage />} />
              <Route path="/final-review" element={<FinalReviewPage />} />
              <Route path="/auto-tasks" element={<WatchRootsPage />} />
              <Route path="/watch-roots" element={<WatchRootsPage />} />
              <Route path="/intelligent-copy" element={<IntelligentCopyPage />} />
              <Route path="/publication-tracking" element={<PublicationTrackingPage />} />
              <Route path="/creator-cards" element={<CreatorCardsPage />} />
              <Route path="/task-strategies" element={<TaskStrategiesPage />} />
              <Route path="/visual-plans" element={<VisualPlansPage />} />
              <Route path="/publication-management" element={<PublicationManagementPage />} />
              <Route path="/terms-memory" element={<TermsMemoryPage />} />
              <Route path="/tools" element={<ToolsPage />} />
              <Route path="/tools/tts" element={<TtsToolPage />} />
              <Route path="/tools/asr" element={<AsrToolPage />} />
              <Route path="/tools/avatar" element={<AvatarToolPage />} />
              <Route path="/memory" element={<Navigate to="/terms-memory?tab=memory" replace />} />
              <Route path="/glossary" element={<Navigate to="/terms-memory?tab=glossary" replace />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/control" element={<ControlPage />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
