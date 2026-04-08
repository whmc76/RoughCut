import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SettingsPage } from "./SettingsPage";

const mockUseSettingsWorkspace = vi.fn();
let lastPageHeaderProps: { summary?: unknown[] } | null = null;

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, actions, summary }: { title: string; actions?: ReactNode; summary?: unknown[] }) => {
    lastPageHeaderProps = { summary };
    return (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
    );
  },
}));

vi.mock("../components/ui/PanelHeader", () => ({
  PanelHeader: ({ title, description }: { title: string; description?: string }) => (
    <div>
      <strong>{title}</strong>
      {description ? <div>{description}</div> : null}
    </div>
  ),
}));

vi.mock("../features/settings/SettingsOverviewPanel", () => ({
  SettingsOverviewPanel: () => <div>overview</div>,
}));

vi.mock("../features/settings/ModelSettingsPanel", () => ({
  ModelSettingsPanel: () => <div>model</div>,
}));

vi.mock("../features/settings/RuntimeSettingsPanel", () => ({
  RuntimeSettingsPanel: () => <div>runtime</div>,
}));

vi.mock("../features/settings/QualitySettingsPanel", () => ({
  QualitySettingsPanel: () => <div>quality</div>,
}));

vi.mock("../features/settings/CreativeSettingsPanel", () => ({
  CreativeSettingsPanel: () => <div>creative</div>,
}));

vi.mock("../features/settings/BotSettingsPanel", () => ({
  BotSettingsPanel: () => <div>bot</div>,
}));

vi.mock("../features/settings/useSettingsWorkspace", () => ({
  useSettingsWorkspace: () => mockUseSettingsWorkspace(),
}));

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    form: {
      llm_mode: "performance",
      reasoning_provider: "openai",
      search_provider: "auto",
      search_fallback_provider: "searxng",
      avatar_provider: "heygem",
      voice_provider: "indextts2",
      telegram_remote_review_enabled: false,
      telegram_agent_enabled: false,
    },
    config: { data: undefined },
    runtimeEnvironment: { data: undefined },
    serviceStatus: { data: undefined },
    configProfiles: { data: undefined },
    options: { data: undefined },
    setForm: vi.fn(),
    reset: { mutate: vi.fn(), isPending: false },
    saveState: "idle",
    saveError: "",
    ...overrides,
  };
}

describe("SettingsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
    lastPageHeaderProps = null;
  });

  it("organizes settings into overview, configuration, and maintenance chapters", () => {
    mockUseSettingsWorkspace.mockReturnValue(buildWorkspace());

    const { container } = render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(lastPageHeaderProps?.summary).toBeUndefined();
    expect(container.querySelector(".settings-architecture-page")).toBeInTheDocument();
    expect(container.querySelector(".settings-architecture-deck")).toBeInTheDocument();
    expect(container.querySelector(".settings-core-stack")).toBeInTheDocument();
    expect(container.querySelector(".settings-automation-stack")).toBeInTheDocument();
    expect(container.querySelector(".settings-link-grid")).toBeInTheDocument();
    expect(screen.getByText("已生效的默认设置")).toBeInTheDocument();
    expect(screen.getByText("模型与执行")).toBeInTheDocument();
    expect(screen.getByText("质量与输出")).toBeInTheDocument();
    expect(screen.getByText("辅助页面")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "查看包装页" })).toHaveAttribute("href", "/packaging");
    expect(screen.getByRole("link", { name: "查看记忆页" })).toHaveAttribute("href", "/memory");
    expect(screen.getByRole("link", { name: "查看词表页" })).toHaveAttribute("href", "/glossary");
    expect(screen.getByRole("link", { name: "查看 Control" })).toHaveAttribute("href", "/control");
  });

  it("still distinguishes telegram review from telegram agent in the automation summary", () => {
    mockUseSettingsWorkspace.mockReturnValue(
      buildWorkspace({
        form: {
          avatar_provider: "heygem",
          voice_provider: "indextts2",
          telegram_remote_review_enabled: true,
          telegram_agent_enabled: false,
        },
      }),
    );

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    );

    expect(screen.getByText(/Telegram 审核已启用/)).toBeInTheDocument();
    expect(screen.getByText(/Telegram Agent 关闭/)).toBeInTheDocument();
  });
});
