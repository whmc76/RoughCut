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
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-kicker">{t("app.sidebar.kicker")}</div>
          <h1>RoughCut</h1>
          <p className="muted sidebar-tagline">{t("app.sidebar.description")}</p>
        </div>
        <nav className="nav-list">
          <div className="sidebar-section-label">Workspace</div>
          <div className="nav-group-links nav-group-links-primary">
            {navigationItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
              >
                <span>{item.label}</span>
              </NavLink>
            ))}
          </div>
        </nav>
        <div className="sidebar-footer">
          <label className="form-stack sidebar-footnote">
            <span className="sidebar-footer-label">{t("app.sidebar.language")}</span>
            <select className="input" value={locale} onChange={(event) => setLocale(event.target.value as "zh-CN" | "en-US")}>
              <option value="zh-CN">{t("app.language.zh-CN")}</option>
              <option value="en-US">{t("app.language.en-US")}</option>
            </select>
          </label>
          <div className="sidebar-version">
            <span className="sidebar-footer-label">{t("app.sidebar.version")}</span>
            <code>{appVersion || t("app.sidebar.versionUnknown")}</code>
          </div>
        </div>
      </aside>
      <main className="main-content">
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
      </main>
    </div>
  );
}
