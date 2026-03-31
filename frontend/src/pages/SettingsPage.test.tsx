import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

import { SettingsPage } from "./SettingsPage";

const mockUseSettingsWorkspace = vi.fn();

vi.mock("../i18n", () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title, actions }: { title: string; actions?: ReactNode }) => (
    <header>
      <h1>{title}</h1>
      {actions}
    </header>
  ),
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
  });

  it("keeps advanced engineering settings collapsed by default", () => {
    mockUseSettingsWorkspace.mockReturnValue(buildWorkspace());

    render(<SettingsPage />);

    const runtimeDetails = screen.getByText("接入与执行设置").closest("details");
    const advancedDetails = screen.getByText("高级工程设置").closest("details");
    expect(runtimeDetails).not.toHaveAttribute("open");
    expect(advancedDetails).not.toHaveAttribute("open");
    expect(screen.getByText(/推理 OpenAI · 自动跟随 OpenAI，失败回退 SearXNG/)).toBeInTheDocument();
    expect(screen.getByText("heygem + indextts2 · Telegram / Agent 未启用")).toBeInTheDocument();
  });

  it("auto-expands advanced engineering settings when telegram automation is enabled", () => {
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

    render(<SettingsPage />);

    const runtimeDetails = screen.getByText("接入与执行设置").closest("details");
    const advancedDetails = screen.getByText("高级工程设置").closest("details");
    expect(runtimeDetails).toHaveAttribute("open");
    expect(advancedDetails).toHaveAttribute("open");
    expect(screen.getByText("heygem + indextts2 · Telegram / Agent 已启用")).toBeInTheDocument();
  });
});
