import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import { I18nProvider } from "./i18n";

vi.mock("./api", () => ({
  api: {
    getConfig: vi.fn(async () => ({
      llm_mode: "performance",
      llm_routing_mode: "bundled",
      hybrid_analysis_provider: "openai",
      hybrid_copy_provider: "openai",
      preferred_ui_language: "zh-CN",
    })),
    patchConfig: vi.fn(async (body: Record<string, unknown>) => ({
      llm_mode: "performance",
      llm_routing_mode: body.llm_routing_mode ?? "bundled",
      hybrid_analysis_provider: "openai",
      hybrid_copy_provider: "openai",
      preferred_ui_language: body.preferred_ui_language ?? "zh-CN",
    })),
  },
}));

vi.mock("./pages/OverviewPage", () => ({ OverviewPage: () => <main data-testid="route-overview">Overview route</main> }));
vi.mock("./pages/JobsPage", () => ({ JobsPage: () => <main data-testid="route-jobs">Jobs route</main> }));
vi.mock("./pages/WatchRootsPage", () => ({ WatchRootsPage: () => <main data-testid="route-watch-roots">Watch roots route</main> }));
vi.mock("./pages/IntelligentCopyPage", () => ({ IntelligentCopyPage: () => <main data-testid="route-intelligent-copy">Intelligent copy route</main> }));
vi.mock("./pages/PackagingPage", () => ({ PackagingPage: () => <main data-testid="route-packaging">Packaging route</main> }));
vi.mock("./pages/StyleLabPage", () => ({ StyleLabPage: () => <main data-testid="route-style-lab">Style lab route</main> }));
vi.mock("./pages/StyleTemplatesPage", () => ({ StyleTemplatesPage: () => <main data-testid="route-style-templates">Style templates route</main> }));
vi.mock("./pages/CreativeModesPage", () => ({ CreativeModesPage: () => <main data-testid="route-creative-modes">Creative modes route</main> }));
vi.mock("./pages/CreatorProfilesPage", () => ({ CreatorProfilesPage: () => <main data-testid="route-creator-profiles">Creator profiles route</main> }));
vi.mock("./pages/MemoryPage", () => ({ MemoryPage: () => <main data-testid="route-memory">Memory route</main> }));
vi.mock("./pages/GlossaryPage", () => ({ GlossaryPage: () => <main data-testid="route-glossary">Glossary route</main> }));
vi.mock("./pages/SettingsPage", () => ({ SettingsPage: () => <main data-testid="route-settings">Settings route</main> }));
vi.mock("./pages/ControlPage", () => ({ ControlPage: () => <main data-testid="route-control">Control route</main> }));

const routes = [
  ["/", "route-overview"],
  ["/jobs", "route-jobs"],
  ["/watch-roots", "route-watch-roots"],
  ["/intelligent-copy", "route-intelligent-copy"],
  ["/packaging", "route-packaging"],
  ["/style-lab", "route-style-lab"],
  ["/style-templates", "route-style-templates"],
  ["/creative-modes", "route-creative-modes"],
  ["/creator-profiles", "route-creator-profiles"],
  ["/memory", "route-memory"],
  ["/glossary", "route-glossary"],
  ["/settings", "route-settings"],
  ["/control", "route-control"],
] as const;

function renderApp(path = "/") {
  window.localStorage.setItem("roughcut.ui.locale", "zh-CN");
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter initialEntries={[path]}>
          <App />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("App route and navigation audit", () => {
  it.each(routes)("renders route %s from the shell", async (path, testId) => {
    renderApp(path);

    expect(await screen.findByTestId(testId)).toBeInTheDocument();
  });

  it("exposes all grouped navigation entries", async () => {
    renderApp();

    expect(await screen.findByText("Overview route")).toBeInTheDocument();
    expect(screen.getByText("工作台")).toBeInTheDocument();
    expect(screen.getByText("创作资产")).toBeInTheDocument();
    expect(screen.getByText("系统")).toBeInTheDocument();

    for (const label of ["概览", "任务", "监看目录", "智能文案", "风格实验", "包装素材", "风格模板", "创作模式", "创作者档案", "系统设置", "记忆", "术语表", "控制台"]) {
      expect(screen.getByRole("link", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });

  it("keeps the language switch wired", async () => {
    renderApp();

    fireEvent.click(screen.getByRole("button", { name: "EN" }));

    await waitFor(() => {
      expect(screen.getByRole("link", { name: /Overview/ })).toBeInTheDocument();
    });
  });
});
