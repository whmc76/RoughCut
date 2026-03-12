import { NavLink, Route, Routes } from "react-router-dom";

import { ControlPage } from "./pages/ControlPage";
import { MemoryPage } from "./pages/MemoryPage";
import { GlossaryPage } from "./pages/GlossaryPage";
import { JobsPage } from "./pages/JobsPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PackagingPage } from "./pages/PackagingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { StyleTemplatesPage } from "./pages/StyleTemplatesPage";
import { WatchRootsPage } from "./pages/WatchRootsPage";

const navigation = [
  { to: "/", label: "概览" },
  { to: "/jobs", label: "任务" },
  { to: "/watch-roots", label: "监控目录" },
  { to: "/packaging", label: "包装素材" },
  { to: "/style-templates", label: "风格模板" },
  { to: "/memory", label: "行为记忆" },
  { to: "/glossary", label: "术语词表" },
  { to: "/settings", label: "系统设置" },
  { to: "/control", label: "服务控制" },
];

export function App() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div>
          <div className="brand-kicker">Prototype</div>
          <h1>RoughCut</h1>
          <p className="muted">
            React 控制台重构版。原型阶段直接以新架构替换旧静态页，不保留向后兼容层。
          </p>
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
          <div>API 前缀</div>
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
          <Route path="/memory" element={<MemoryPage />} />
          <Route path="/glossary" element={<GlossaryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/control" element={<ControlPage />} />
        </Routes>
      </main>
    </div>
  );
}
