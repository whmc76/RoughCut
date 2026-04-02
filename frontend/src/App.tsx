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

  const navigationGroups = [
    {
      label: "工作台",
      items: [
        { to: "/", label: t("app.nav.overview") },
        { to: "/jobs", label: t("app.nav.jobs") },
        { to: "/watch-roots", label: t("app.nav.watchRoots") },
      ],
    },
    {
      label: "包装与风格",
      items: [
        { to: "/packaging", label: t("app.nav.packaging") },
        { to: "/style-templates", label: t("app.nav.styleTemplates") },
        { to: "/creative-modes", label: t("app.nav.creativeModes") },
        { to: "/creator-profiles", label: t("app.nav.creatorProfiles") },
      ],
    },
    {
      label: "知识与配置",
      items: [
        { to: "/memory", label: t("app.nav.memory") },
        { to: "/glossary", label: t("app.nav.glossary") },
        { to: "/settings", label: t("app.nav.settings") },
      ],
    },
    {
      label: "系统",
      items: [{ to: "/control", label: t("app.nav.control") }],
    },
  ];

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="brand-kicker">{t("app.sidebar.kicker")}</div>
          <h1>RoughCut</h1>
          <p className="muted">{t("app.sidebar.description")}</p>
        </div>
        <nav className="nav-list">
          {navigationGroups.map((group) => (
            <div key={group.label} className="nav-group">
              <div className="sidebar-section-label">{group.label}</div>
              <div className="nav-group-links">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
                  >
                    {item.label}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </nav>
        <div className="sidebar-footer">
          <label className="form-stack">
            <span>{t("app.sidebar.language")}</span>
            <select className="input" value={locale} onChange={(event) => setLocale(event.target.value as "zh-CN" | "en-US")}>
              <option value="zh-CN">{t("app.language.zh-CN")}</option>
              <option value="en-US">{t("app.language.en-US")}</option>
            </select>
          </label>
          <div>{t("app.sidebar.apiPrefix")}</div>
          <code>/api/v1</code>
        </div>
      </aside>
      <main className="main-content">
        <Suspense fallback={<section className="panel">加载页面中…</section>}>
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/watch-roots" element={<WatchRootsPage />} />
            <Route path="/packaging" element={<PackagingPage />} />
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
