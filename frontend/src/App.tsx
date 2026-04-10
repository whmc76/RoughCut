import { Suspense, lazy, useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { getProviderLabel } from "./features/settings/helpers";
import { useFrontendBuildRefresh } from "./hooks/useFrontendBuildRefresh";
import { useI18n } from "./i18n";

const OverviewPage = lazy(async () => ({
  default: (await import("./pages/OverviewPage")).OverviewPage,
}));
const JobsPage = lazy(async () => ({
  default: (await import("./pages/JobsPage")).JobsPage,
}));
const WatchRootsPage = lazy(async () => ({
  default: (await import("./pages/WatchRootsPage")).WatchRootsPage,
}));
const PackagingPage = lazy(async () => ({
  default: (await import("./pages/PackagingPage")).PackagingPage,
}));
const StyleTemplatesPage = lazy(async () => ({
  default: (await import("./pages/StyleTemplatesPage")).StyleTemplatesPage,
}));
const StyleLabPage = lazy(async () => ({
  default: (await import("./pages/StyleLabPage")).StyleLabPage,
}));
const CreativeModesPage = lazy(async () => ({
  default: (await import("./pages/CreativeModesPage")).CreativeModesPage,
}));
const CreatorProfilesPage = lazy(async () => ({
  default: (await import("./pages/CreatorProfilesPage")).CreatorProfilesPage,
}));
const MemoryPage = lazy(async () => ({
  default: (await import("./pages/MemoryPage")).MemoryPage,
}));
const GlossaryPage = lazy(async () => ({
  default: (await import("./pages/GlossaryPage")).GlossaryPage,
}));
const SettingsPage = lazy(async () => ({
  default: (await import("./pages/SettingsPage")).SettingsPage,
}));
const ControlPage = lazy(async () => ({
  default: (await import("./pages/ControlPage")).ControlPage,
}));

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

  const navigationItems = [
    { to: "/", label: t("app.nav.overview") },
    { to: "/jobs", label: t("app.nav.jobs") },
    { to: "/watch-roots", label: "监看目录" },
    { to: "/style-lab", label: "风格实验" },
    { to: "/settings", label: t("app.nav.settings") },
  ];
  const localeOptions = [
    { value: "zh-CN" as const, shortLabel: "简中", title: t("app.language.zh-CN") },
    { value: "en-US" as const, shortLabel: "EN", title: t("app.language.en-US") },
  ];
  const hybridEnabled = config.data?.llm_mode === "performance" && config.data?.llm_routing_mode === "hybrid_performance";
  const hybridAnalysisProvider = String(config.data?.hybrid_analysis_provider ?? "openai");
  const hybridCopyProvider = String(config.data?.hybrid_copy_provider ?? "minimax");

  return (
    <div className="app-shell">
      <aside className="app-rail">
        <div className="rail-brand">
          <div className="rail-brand-mark">RC</div>
          <div className="rail-brand-copy">
            <strong>RoughCut</strong>
          </div>
        </div>
        <nav className="rail-nav" aria-label="Primary">
          {navigationItems.map((item, index) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => (isActive ? "rail-link active" : "rail-link")}
            >
              <span className="rail-link-index">{`${index + 1}`.padStart(2, "0")}</span>
              <span className="rail-link-label">{item.label}</span>
            </NavLink>
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
          <Suspense fallback={<section className="panel">加载页面中…</section>}>
            <Routes>
              <Route path="/" element={<OverviewPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/watch-roots" element={<WatchRootsPage />} />
              <Route path="/packaging" element={<PackagingPage />} />
              <Route path="/style-lab" element={<StyleLabPage />} />
              <Route path="/style-templates" element={<StyleTemplatesPage />} />
              <Route path="/creative-modes" element={<CreativeModesPage />} />
              <Route path="/creator-profiles" element={<CreatorProfilesPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/glossary" element={<GlossaryPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/control" element={<ControlPage />} />
            </Routes>
          </Suspense>
        </div>
      </main>
    </div>
  );
}
