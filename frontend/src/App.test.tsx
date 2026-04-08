import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./api", () => ({
  api: {
    getHealthDetail: vi.fn().mockResolvedValue({ api_version: "test-version" }),
    patchConfig: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("./hooks/useFrontendBuildRefresh", () => ({
  useFrontendBuildRefresh: vi.fn(),
}));

vi.mock("./i18n", () => ({
  useI18n: () => ({
    locale: "zh-CN",
    setLocale: vi.fn(),
    t: (key: string) =>
      (
        {
          "app.nav.overview": "总览",
          "app.nav.jobs": "任务",
          "app.nav.watchRoots": "监看目录",
          "app.nav.settings": "设置",
          "app.sidebar.language": "语言",
          "app.language.zh-CN": "简体中文",
          "app.language.en-US": "English",
        } satisfies Record<string, string>
      )[key] ?? key,
  }),
}));

vi.mock("./pages/OverviewPage", () => ({
  OverviewPage: () => <div>overview-page</div>,
}));

vi.mock("./pages/JobsPage", () => ({
  JobsPage: () => <div>jobs-page</div>,
}));

vi.mock("./pages/WatchRootsPage", () => ({
  WatchRootsPage: () => <div>watch-page</div>,
}));

vi.mock("./pages/StyleTemplatesPage", () => ({
  StyleTemplatesPage: () => <div>style-templates-page</div>,
}));

vi.mock("./pages/StyleLabPage", () => ({
  StyleLabPage: () => <div>style-lab-page</div>,
}));

vi.mock("./pages/PackagingPage", () => ({
  PackagingPage: () => <div>packaging-page</div>,
}));

vi.mock("./pages/CreativeModesPage", () => ({
  CreativeModesPage: () => <div>creative-modes-page</div>,
}));

vi.mock("./pages/CreatorProfilesPage", () => ({
  CreatorProfilesPage: () => <div>creator-profiles-page</div>,
}));

vi.mock("./pages/MemoryPage", () => ({
  MemoryPage: () => <div>memory-page</div>,
}));

vi.mock("./pages/GlossaryPage", () => ({
  GlossaryPage: () => <div>glossary-page</div>,
}));

vi.mock("./pages/SettingsPage", () => ({
  SettingsPage: () => <div>settings-page</div>,
}));

vi.mock("./pages/ControlPage", () => ({
  ControlPage: () => <div>control-page</div>,
}));

function renderApp(initialEntries: string[] = ["/"]) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let App: typeof import("./App").App;

beforeAll(async () => {
  ({ App } = await import("./App"));
});

describe("App shell", () => {
  it("shows only the five top-level destinations in the sidebar", async () => {
    renderApp();

    expect(await screen.findByRole("link", { name: /总览/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /任务/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /监看目录/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /风格实验/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /设置/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Packaging/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Creative Modes/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Creator Profiles/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Glossary/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Control/i })).not.toBeInTheDocument();
  });

  it("drops the old explanatory sidebar copy and keeps the shell minimal", async () => {
    renderApp();

    expect(await screen.findByText("RoughCut")).toBeInTheDocument();
    expect(screen.queryByText("Workspace")).not.toBeInTheDocument();
  });

  it("anchors a compact locale switcher in the rail footer and removes the stage header", async () => {
    const { container } = renderApp();

    await screen.findByText("overview-page");

    const rail = container.querySelector(".app-rail");
    const railNotes = container.querySelector(".rail-notes");
    const chineseButton = screen.getByRole("button", { name: "简中" });
    const englishButton = screen.getByRole("button", { name: "EN" });

    expect(rail).not.toBeNull();
    expect(railNotes).not.toBeNull();
    expect(rail?.contains(chineseButton)).toBe(true);
    expect(railNotes?.contains(chineseButton)).toBe(true);
    expect(railNotes?.contains(englishButton)).toBe(true);
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(container.querySelector(".app-stage-header")).toBeNull();
  });
});
