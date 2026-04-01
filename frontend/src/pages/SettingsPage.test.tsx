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

  it("organizes settings into core, quality, and automation chapters", () => {
    mockUseSettingsWorkspace.mockReturnValue(buildWorkspace());

    render(<SettingsPage />);

    expect(screen.getByText("核心链路与 Provider")).toBeInTheDocument();
    expect(screen.getByText("质量与默认策略")).toBeInTheDocument();
    expect(screen.getByText("扩展与自动化")).toBeInTheDocument();
    expect(screen.queryByText("接入与执行设置")).not.toBeInTheDocument();
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

    render(<SettingsPage />);

    expect(screen.getByText(/Telegram 审核已启用/)).toBeInTheDocument();
    expect(screen.getByText(/Telegram Agent 关闭/)).toBeInTheDocument();
  });
});
