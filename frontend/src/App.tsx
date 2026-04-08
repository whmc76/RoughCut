import { useQuery } from "@tanstack/react-query";
import { Suspense, lazy, useEffect, useRef } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
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
  const syncedLocaleRef = useRef<string>("");
  const appVersionQuery = useQuery({
    queryKey: ["health-detail"],
    queryFn: api.getHealthDetail,
    staleTime: 60_000,
  });
  const appVersion = appVersionQuery.data?.api_version?.trim();

  useFrontendBuildRefresh();

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

  return (
    <div className="app-shell">
      <aside className="app-rail">
        <div className="rail-brand">
          <div className="rail-brand-mark">RC</div>
          <div className="rail-brand-copy">
            <strong>RoughCut</strong>
            <span>local</span>
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
          <span className="rail-note-label">{t("app.sidebar.version")}</span>
          <code>{appVersion || t("app.sidebar.versionUnknown")}</code>
        </div>
      </aside>
      <main className="app-stage">
        <header className="app-stage-header">
          <div className="app-stage-controls">
            <label className="app-stage-locale">
              <span>{t("app.sidebar.language")}</span>
              <select className="input" value={locale} onChange={(event) => setLocale(event.target.value as "zh-CN" | "en-US")}>
                <option value="zh-CN">{t("app.language.zh-CN")}</option>
                <option value="en-US">{t("app.language.en-US")}</option>
              </select>
            </label>
          </div>
        </header>
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
