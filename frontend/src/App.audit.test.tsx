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
vi.mock("./pages/ToolsPage", () => ({
  ToolsPage: () => <main data-testid="route-tools">Tools route</main>,
  TtsToolPage: () => <main data-testid="route-tools-tts">TTS route</main>,
  AsrToolPage: () => <main data-testid="route-tools-asr">ASR route</main>,
  AvatarToolPage: () => <main data-testid="route-tools-avatar">Avatar route</main>,
}));
vi.mock("./pages/CreatorCardsPage", () => ({ CreatorCardsPage: () => <main data-testid="route-creator-cards">Creator cards route</main> }));
vi.mock("./pages/TaskStrategiesPage", () => ({ TaskStrategiesPage: () => <main data-testid="route-task-strategies">Task strategies route</main> }));
vi.mock("./pages/VisualPlansPage", () => ({ VisualPlansPage: () => <main data-testid="route-visual-plans">Visual plans route</main> }));
vi.mock("./pages/PublicationManagementPage", () => ({ PublicationManagementPage: () => <main data-testid="route-publication-management">Publication management route</main> }));
vi.mock("./pages/MemoryPage", () => ({ MemoryPage: () => <main data-testid="route-memory">Memory route</main> }));
vi.mock("./pages/GlossaryPage", () => ({ GlossaryPage: () => <main data-testid="route-glossary">Glossary route</main> }));
vi.mock("./pages/SettingsPage", () => ({ SettingsPage: () => <main data-testid="route-settings">Settings route</main> }));
vi.mock("./pages/ControlPage", () => ({ ControlPage: () => <main data-testid="route-control">Control route</main> }));

const routes = [
  ["/", "route-overview"],
  ["/jobs", "route-jobs"],
  ["/watch-roots", "route-watch-roots"],
  ["/intelligent-copy", "route-intelligent-copy"],
  ["/tools", "route-tools"],
  ["/tools/tts", "route-tools-tts"],
  ["/tools/asr", "route-tools-asr"],
  ["/tools/avatar", "route-tools-avatar"],
  ["/creator-cards", "route-creator-cards"],
  ["/task-strategies", "route-task-strategies"],
  ["/visual-plans", "route-visual-plans"],
  ["/publication-management", "route-publication-management"],
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

    for (const label of ["概览", "剪辑制片", "自动任务", "智能发布", "百宝箱", "创作者卡片库", "任务策略库", "智能视觉方案", "智能发布管理", "系统设置", "记忆", "术语表", "控制台"]) {
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
