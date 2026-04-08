import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { ConfigProfile, ConfigProfiles } from "../../types";
import { api } from "../../api";
import { createTestQueryClient } from "../../test/renderWithQueryClient";
import { ConfigProfileSwitcher } from "./ConfigProfileSwitcher";

vi.mock("../../api", () => ({
  api: {
    getConfigProfiles: vi.fn(),
    activateConfigProfile: vi.fn(),
    createConfigProfile: vi.fn(),
    updateConfigProfile: vi.fn(),
    deleteConfigProfile: vi.fn(),
  },
}));

function buildProfile(overrides: Partial<ConfigProfile> = {}): ConfigProfile {
  return {
    id: "profile_active",
    name: "高节奏口播",
    description: "适合高节奏测评和数字人口播",
    created_at: "2026-03-26T08:00:00Z",
    updated_at: "2026-03-26T09:30:00Z",
    is_active: true,
    is_dirty: false,
    dirty_keys: [],
    dirty_details: [],
    llm_mode: "cloud",
    transcription_provider: "openai",
    transcription_model: "gpt-4o-transcribe",
    transcription_dialect: "mandarin",
    reasoning_provider: "openai",
    reasoning_model: "gpt-4.1",
    workflow_mode: "standard_edit",
    enhancement_modes: ["avatar_commentary", "ai_director"],
    auto_confirm_content_profile: true,
    content_profile_review_threshold: 0.72,
    packaging_selection_min_score: 0.64,
    quality_auto_rerun_enabled: true,
    quality_auto_rerun_below_score: 78,
    copy_style: "attention_grabbing",
    cover_style: "preset_default",
    title_style: "preset_default",
    subtitle_style: "bold_yellow_outline",
    smart_effect_style: "smart_effect_rhythm",
    avatar_presenter_id: "presenter_demo",
    packaging_enabled: true,
    insert_pool_size: 3,
    music_pool_size: 5,
    ...overrides,
  };
}

function renderSwitcher(data: ConfigProfiles) {
  const queryClient = createTestQueryClient();
  vi.mocked(api.getConfigProfiles).mockResolvedValue(data);
  vi.mocked(api.activateConfigProfile).mockResolvedValue({
    active_profile_id: data.active_profile_id,
    active_profile_dirty: false,
    active_profile_dirty_keys: [],
    active_profile_dirty_details: [],
    profiles: data.profiles,
  });
  vi.mocked(api.createConfigProfile).mockResolvedValue(data);
  vi.mocked(api.updateConfigProfile).mockResolvedValue(data);
  vi.mocked(api.deleteConfigProfile).mockResolvedValue(data);

  return render(
    <QueryClientProvider client={queryClient}>
      <ConfigProfileSwitcher />
    </QueryClientProvider>,
  );
}

describe("ConfigProfileSwitcher", () => {
  const confirmSpy = vi.spyOn(window, "confirm");

  beforeEach(() => {
    confirmSpy.mockReturnValue(true);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("renders expanded production summary for the active profile", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [buildProfile()],
    });

    await waitFor(() => expect(screen.getByText("当前 高节奏口播")).toBeTruthy());

    expect(screen.getByText("生产链路")).toBeTruthy();
    expect(screen.getByText("审核阈值")).toBeTruthy();
    expect(screen.getByText("风格与绑定")).toBeTruthy();
    expect(screen.getByText(/转写 OpenAI \(api\) \/ gpt-4o-transcribe/)).toBeTruthy();
    expect(screen.getByText(/推理 openai \/ gpt-4.1/)).toBeTruthy();
    expect(screen.getByText(/方言 mandarin/)).toBeTruthy();
    expect(screen.getByText(/画像自动确认 0.72/)).toBeTruthy();
    expect(screen.getByText(/低分复跑 78/)).toBeTruthy();
    expect(screen.getByText(/包装最低分 0.64/)).toBeTruthy();
    expect(screen.getByText(/数字人已绑定/)).toBeTruthy();
    expect(screen.getAllByText("适合高节奏测评和数字人口播").length).toBeGreaterThan(0);
  });

  it("shows a read-only preview when hovering another profile", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [
        buildProfile(),
        buildProfile({
          id: "profile_local",
          name: "本地审稿",
          description: "适合本地模型审稿和低成本预审",
          is_active: false,
          llm_mode: "local",
          transcription_provider: "faster_whisper",
          transcription_model: "large-v3",
          reasoning_provider: "ollama",
          reasoning_model: "qwen3:8b",
          auto_confirm_content_profile: false,
          quality_auto_rerun_enabled: false,
          packaging_enabled: false,
          avatar_presenter_id: "",
          insert_pool_size: 0,
          music_pool_size: 0,
        }),
      ],
    });

    await waitFor(() => expect(screen.getByRole("button", { name: /^本地审稿/ })).toBeTruthy());

    fireEvent.mouseEnter(screen.getByRole("button", { name: /^本地审稿/ }));

    expect(screen.getByText("预览")).toBeTruthy();
    expect(screen.getByText(/这里显示“本地审稿”的关键设置/)).toBeTruthy();
    expect(screen.getAllByText("适合本地模型审稿和低成本预审").length).toBeGreaterThan(0);
    expect(screen.getByText(/转写 Faster Whisper \(local\) \/ large-v3/)).toBeTruthy();
    expect(screen.getByText(/推理 ollama \/ qwen3:8b/)).toBeTruthy();
    expect(screen.getByText("包装关闭")).toBeTruthy();
    expect(screen.getByText(/和当前方案“高节奏口播”相比/)).toBeTruthy();
    expect(screen.getByText("推理 provider")).toBeTruthy();
    expect(screen.getByText(/openai -> ollama/)).toBeTruthy();
  });

  it("filters by name or description and supports list sorting", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [
        buildProfile({
          updated_at: "2026-03-26T09:30:00Z",
        }),
        buildProfile({
          id: "profile_local",
          name: "Zulu审稿",
          description: "适合本地模型审稿和低成本预审",
          updated_at: "2026-03-26T07:00:00Z",
          is_active: false,
        }),
        buildProfile({
          id: "profile_batch",
          name: "Alpha混剪",
          description: "适合多素材批量混剪和包装自动联动",
          updated_at: "2026-03-26T11:00:00Z",
          is_active: false,
        }),
        buildProfile({
          id: "profile_archive",
          name: "Mid归档",
          description: "适合长期保留的专题版本",
          updated_at: "2026-03-25T08:00:00Z",
          is_active: false,
        }),
        buildProfile({
          id: "profile_backup",
          name: "Omega备用",
          description: "适合低频切换的备用方案",
          updated_at: "2026-03-20T08:00:00Z",
          is_active: false,
        }),
      ],
    });

    await waitFor(() => expect(screen.getAllByText("当前方案").length).toBeGreaterThan(0));
    expect(screen.getByText("最近更新")).toBeTruthy();
    expect(screen.getByText("其他方案")).toBeTruthy();

    const activeButton = screen.getByRole("button", { name: /^高节奏口播/ });
    const alphaButton = screen.getByRole("button", { name: /^Alpha混剪/ });
    const zuluButton = screen.getByRole("button", { name: /^Zulu审稿/ });
    const archiveButton = screen.getByRole("button", { name: /^Mid归档/ });
    const backupButton = screen.getByRole("button", { name: /^Omega备用/ });

    expect(activeButton.compareDocumentPosition(alphaButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(alphaButton.compareDocumentPosition(zuluButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(zuluButton.compareDocumentPosition(archiveButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(archiveButton.compareDocumentPosition(backupButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.change(screen.getByPlaceholderText("筛选方案"), {
      target: { value: "批量混剪" },
    });

    expect(screen.getByRole("button", { name: /^Alpha混剪/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Zulu审稿/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Mid归档/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Omega备用/ })).toBeNull();
    expect(screen.getByRole("button", { name: /^高节奏口播/ })).toBeTruthy();
    expect(screen.queryByText("其他方案")).toBeNull();

    fireEvent.change(screen.getByDisplayValue("最近改动"), {
      target: { value: "name_asc" },
    });

    fireEvent.change(screen.getByPlaceholderText("筛选方案"), {
      target: { value: "" },
    });

    const sortedAlphaButton = screen.getByRole("button", { name: /^Alpha混剪/ });
    const sortedArchiveButton = screen.getByRole("button", { name: /^Mid归档/ });
    const sortedZuluButton = screen.getByRole("button", { name: /^Zulu审稿/ });
    const sortedBackupButton = screen.getByRole("button", { name: /^Omega备用/ });
    expect(sortedAlphaButton.compareDocumentPosition(sortedArchiveButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sortedArchiveButton.compareDocumentPosition(sortedZuluButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(sortedZuluButton.compareDocumentPosition(sortedBackupButton) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("locks comparison view when compare button is clicked", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [
        buildProfile(),
        buildProfile({
          id: "profile_local",
          name: "本地审稿",
          description: "适合本地模型审稿和低成本预审",
          is_active: false,
          llm_mode: "local",
          transcription_provider: "faster_whisper",
          transcription_model: "large-v3",
          reasoning_provider: "ollama",
          reasoning_model: "qwen3:8b",
          packaging_enabled: false,
          avatar_presenter_id: "",
          insert_pool_size: 0,
          music_pool_size: 0,
        }),
      ],
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "查看差异" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "查看差异" }));

    expect(screen.getByText("方案差异")).toBeTruthy();
    expect(screen.getByText("对比中")).toBeTruthy();
    expect(screen.getByText(/正在和“本地审稿”做对比/)).toBeTruthy();

    fireEvent.click(screen.getAllByRole("button", { name: "关闭对比" })[0]);

    expect(screen.queryByText("方案差异")).toBeNull();
  });

  it("activates another profile when its chip is clicked", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: true,
      active_profile_dirty_keys: ["reasoning_model"],
      active_profile_dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
      ],
      profiles: [
        buildProfile({
          dirty_keys: ["reasoning_model"],
          dirty_details: [
            {
              key: "reasoning_model",
              saved_value: "gpt-4.1",
              current_value: "gpt-4.1-mini",
            },
          ],
        }),
        buildProfile({
          id: "profile_local",
          name: "本地审稿",
          is_active: false,
          is_dirty: true,
          dirty_keys: ["llm_mode", "reasoning_model"],
          dirty_details: [
            {
              key: "llm_mode",
              saved_value: "local",
              current_value: "cloud",
            },
            {
              key: "reasoning_model",
              saved_value: "qwen3:8b",
              current_value: "gpt-4.1-mini",
            },
          ],
          llm_mode: "local",
          transcription_provider: "faster_whisper",
          transcription_model: "large-v3",
          reasoning_provider: "ollama",
          reasoning_model: "qwen3:8b",
          auto_confirm_content_profile: false,
          quality_auto_rerun_enabled: false,
          packaging_enabled: false,
          avatar_presenter_id: "",
          insert_pool_size: 0,
          music_pool_size: 0,
        }),
      ],
    });

    await waitFor(() => expect(screen.getByText(/有未保存变更/)).toBeTruthy());
    expect(screen.getByText("推理模型")).toBeTruthy();
    expect(screen.getByText(/gpt-4.1 -> gpt-4.1-mini/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^本地审稿/ }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("以下差异会被放弃");
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("当前方案“高节奏口播”还有未保存改动，确认切换到“本地审稿”？");
    await waitFor(() => expect(api.activateConfigProfile).toHaveBeenCalledWith("profile_local"));
    expect(screen.getByText("未保存")).toBeTruthy();
  });

  it("does not activate another profile when switch confirmation is cancelled", async () => {
    confirmSpy.mockReturnValue(false);

    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: true,
      active_profile_dirty_keys: ["reasoning_model"],
      active_profile_dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
      ],
      profiles: [
        buildProfile({
          dirty_keys: ["reasoning_model"],
          dirty_details: [
            {
              key: "reasoning_model",
              saved_value: "gpt-4.1",
              current_value: "gpt-4.1-mini",
            },
          ],
        }),
        buildProfile({
          id: "profile_local",
          name: "本地审稿",
          is_active: false,
          llm_mode: "local",
          transcription_provider: "faster_whisper",
          transcription_model: "large-v3",
          reasoning_provider: "ollama",
          reasoning_model: "qwen3:8b",
          packaging_enabled: false,
          avatar_presenter_id: "",
          insert_pool_size: 0,
          music_pool_size: 0,
        }),
      ],
    });

    await waitFor(() => expect(screen.getByText(/有未保存变更/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /^本地审稿/ }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(api.activateConfigProfile).not.toHaveBeenCalled();
  });

  it("confirms diff summary before overwriting the active profile", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: true,
      active_profile_dirty_keys: ["reasoning_model", "packaging.copy_style"],
      active_profile_dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
        {
          key: "packaging.copy_style",
          saved_value: "trusted_expert",
          current_value: "attention_grabbing",
        },
      ],
      profiles: [
        buildProfile({
          dirty_keys: ["reasoning_model", "packaging.copy_style"],
          dirty_details: [
            {
              key: "reasoning_model",
              saved_value: "gpt-4.1",
              current_value: "gpt-4.1-mini",
            },
            {
              key: "packaging.copy_style",
              saved_value: "trusted_expert",
              current_value: "attention_grabbing",
            },
          ],
        }),
      ],
    });

    await waitFor(() => expect(screen.getByText(/覆盖会把这 2 项差异写回/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "覆盖当前方案" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("推理模型: gpt-4.1 -> gpt-4.1-mini");
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("文案风格: trusted_expert -> attention_grabbing");
    await waitFor(() =>
      expect(api.updateConfigProfile).toHaveBeenCalledWith("profile_active", {
        name: "高节奏口播",
        description: "适合高节奏测评和数字人口播",
        capture_current: true,
      }),
    );
  });

  it("confirms delete impact before removing the active profile", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: true,
      active_profile_dirty_keys: ["reasoning_model", "packaging.copy_style"],
      active_profile_dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
        {
          key: "packaging.copy_style",
          saved_value: "trusted_expert",
          current_value: "attention_grabbing",
        },
      ],
      profiles: [
        buildProfile({
          dirty_keys: ["reasoning_model", "packaging.copy_style"],
          dirty_details: [
            {
              key: "reasoning_model",
              saved_value: "gpt-4.1",
              current_value: "gpt-4.1-mini",
            },
            {
              key: "packaging.copy_style",
              saved_value: "trusted_expert",
              current_value: "attention_grabbing",
            },
          ],
        }),
      ],
    });

    await waitFor(() => expect(screen.getByText(/删除后会移除“高节奏口播”这套方案/)).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "删除方案" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("删除后会失去这套方案快照和后续回滚点");
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("当前还存在未保存差异");
    expect(confirmSpy.mock.calls.at(-1)?.[0]).toContain("推理模型: gpt-4.1 -> gpt-4.1-mini");
    await waitFor(() => expect(api.deleteConfigProfile).toHaveBeenCalledWith("profile_active"));
  });

  it("does not delete the active profile when delete confirmation is cancelled", async () => {
    confirmSpy.mockReturnValue(false);

    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: true,
      active_profile_dirty_keys: ["reasoning_model"],
      active_profile_dirty_details: [
        {
          key: "reasoning_model",
          saved_value: "gpt-4.1",
          current_value: "gpt-4.1-mini",
        },
      ],
      profiles: [
        buildProfile({
          dirty_keys: ["reasoning_model"],
          dirty_details: [
            {
              key: "reasoning_model",
              saved_value: "gpt-4.1",
              current_value: "gpt-4.1-mini",
            },
          ],
        }),
      ],
    });

    await waitFor(() => expect(screen.getByRole("button", { name: "删除方案" })).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: "删除方案" }));

    expect(api.deleteConfigProfile).not.toHaveBeenCalled();
  });

  it("shows naming conflict hint and disables create or rename for duplicate names", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [
        buildProfile(),
        buildProfile({
          id: "profile_duplicate",
          name: "专题混剪方案",
          is_active: false,
        }),
      ],
    });

    await waitFor(() => expect(screen.getByDisplayValue("高节奏口播")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("方案名称，例如：评测口播"), {
      target: { value: "专题混剪方案" },
    });

    expect(screen.getByText(/已存在同名方案“专题混剪方案”/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "保存为新方案" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "更新方案说明" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("updates profile description alongside profile metadata", async () => {
    renderSwitcher({
      active_profile_id: "profile_active",
      active_profile_dirty: false,
      active_profile_dirty_keys: [],
      active_profile_dirty_details: [],
      profiles: [buildProfile()],
    });

    await waitFor(() => expect(screen.getByDisplayValue("高节奏口播")).toBeTruthy());

    fireEvent.change(screen.getByPlaceholderText("补充用途，例如：适合测评口播和数字人解说"), {
      target: { value: "适合产品测评、数字人口播和自动复跑" },
    });

    expect(screen.getByText(/备注会和方案一起保存/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "更新方案说明" }));

    await waitFor(() =>
      expect(api.updateConfigProfile).toHaveBeenCalledWith("profile_active", {
        name: "高节奏口播",
        description: "适合产品测评、数字人口播和自动复跑",
        capture_current: false,
      }),
    );
  });
});
