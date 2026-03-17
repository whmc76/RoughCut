import { useEffect, useRef } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { api } from "./api";
import { useI18n } from "./i18n";
import { ControlPage } from "./pages/ControlPage";
import { CreativeModesPage } from "./pages/CreativeModesPage";
import { MemoryPage } from "./pages/MemoryPage";
import { GlossaryPage } from "./pages/GlossaryPage";
import { JobsPage } from "./pages/JobsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PackagingPage } from "./pages/PackagingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StyleTemplatesPage } from "./pages/StyleTemplatesPage";
import { WatchRootsPage } from "./pages/WatchRootsPage";

export function App() {
  const { locale, setLocale, t } = useI18n();
  const syncedLocaleRef = useRef<string>("");

  useEffect(() => {
    if (syncedLocaleRef.current === locale) {
      return;
    }
    syncedLocaleRef.current = locale;
    void api.patchConfig({ preferred_ui_language: locale }).catch(() => {
      syncedLocaleRef.current = "";
    });
  }, [locale]);

  const navigation = [
    { to: "/", label: t("app.nav.overview") },
    { to: "/jobs", label: t("app.nav.jobs") },
    { to: "/watch-roots", label: t("app.nav.watchRoots") },
    { to: "/packaging", label: t("app.nav.packaging") },
    { to: "/style-templates", label: t("app.nav.styleTemplates") },
    { to: "/creative-modes", label: t("app.nav.creativeModes") },
    { to: "/memory", label: t("app.nav.memory") },
    { to: "/glossary", label: t("app.nav.glossary") },
    { to: "/settings", label: t("app.nav.settings") },
    { to: "/control", label: t("app.nav.control") },
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
          {navigation.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              {item.label}
            </NavLink>
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
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/watch-roots" element={<WatchRootsPage />} />
          <Route path="/packaging" element={<PackagingPage />} />
          <Route path="/style-templates" element={<StyleTemplatesPage />} />
          <Route path="/creative-modes" element={<CreativeModesPage />} />
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/glossary" element={<GlossaryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/control" element={<ControlPage />} />
        </Routes>
      </main>
    </div>
  );
}
