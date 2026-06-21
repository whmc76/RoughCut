import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PublicationManagementPage } from "./PublicationManagementPage";

const apiMock = vi.hoisted(() => ({
  listCreatorCards: vi.fn(),
  getPublicationProfile: vi.fn(),
  refinePublicationProfile: vi.fn(),
  patchPublicationProfile: vi.fn(),
  startSocialAutoUploadLogin: vi.fn(),
  checkSocialAutoUploadLogin: vi.fn(),
  openSocialAutoUploadDashboard: vi.fn(),
  bindSocialAutoUploadLogin: vi.fn(),
  deletePlatformBinding: vi.fn(),
}));

vi.mock("../api", () => ({
  api: apiMock,
}));

vi.mock("../components/ui/PageHeader", () => ({
  PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

function renderWithQueryClient(children: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{children}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.listCreatorCards.mockResolvedValue({
    items: [{ id: "creator-demo", name: "Demo Creator" }],
  });
  apiMock.getPublicationProfile.mockResolvedValue({
    id: "profile-1",
    creator_card_id: "creator-demo",
    status: "active",
    publication_payload_json: {
      default_platforms: ["bilibili"],
      platform_rules: {},
    },
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
    bindings: [],
    versions: [],
  });
  apiMock.startSocialAutoUploadLogin.mockResolvedValue({
    status: "login_started",
    pid: 12345,
    command: ["python", "sau_cli.py", "bilibili", "login", "--account", "Demo Creator · B 站", "--headed"],
  });
  apiMock.checkSocialAutoUploadLogin.mockResolvedValue({
    status: "login_invalid",
    check_source: "codex_host_bridge",
  });
  apiMock.openSocialAutoUploadDashboard.mockResolvedValue({
    status: "dashboard_started",
    account_label: "Demo Creator · Chrome",
  });
  apiMock.bindSocialAutoUploadLogin.mockResolvedValue({
    id: "profile-1",
    creator_card_id: "creator-demo",
    status: "active",
    publication_payload_json: { default_platforms: ["bilibili"] },
    created_at: "2026-06-19T00:00:00Z",
    updated_at: "2026-06-19T00:00:00Z",
    bindings: [],
    versions: [],
  });
});

afterEach(() => {
  cleanup();
});

describe("PublicationManagementPage platform binding", () => {
  it("opens a login modal instead of directly saving a platform binding", async () => {
    renderWithQueryClient(<PublicationManagementPage />);

    const bindButtons = await screen.findAllByRole("button", { name: "绑定平台" });
    fireEvent.click(bindButtons[0]);

    expect(screen.getByRole("dialog", { name: "B 站 登录绑定" })).toBeInTheDocument();
    expect(screen.getByDisplayValue("Demo Creator · B 站")).toBeInTheDocument();
    expect(apiMock.bindSocialAutoUploadLogin).not.toHaveBeenCalled();

    await waitFor(() => {
      expect(apiMock.startSocialAutoUploadLogin).toHaveBeenCalledWith("creator-demo", {
        platform: "bilibili",
        browser: "chrome",
        account_name: "Demo Creator · B 站",
      });
    });
    expect(await screen.findByText("登录窗口已启动")).toBeInTheDocument();
    expect(await screen.findByText("正在等待登录完成")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认已登录并绑定" }));
    await waitFor(() => {
      expect(apiMock.bindSocialAutoUploadLogin).toHaveBeenCalledWith("creator-demo", {
        platform: "bilibili",
        browser: "chrome",
        account_name: "Demo Creator · B 站",
        login_confirmed: true,
      });
    });
  });

  it("auto-confirms the binding after login status becomes valid", async () => {
    apiMock.checkSocialAutoUploadLogin.mockResolvedValueOnce({
      status: "login_valid",
      check_source: "codex_host_bridge",
    });
    renderWithQueryClient(<PublicationManagementPage />);

    const bindButtons = await screen.findAllByRole("button", { name: "绑定平台" });
    fireEvent.click(bindButtons[0]);

    await waitFor(() => {
      expect(apiMock.bindSocialAutoUploadLogin).toHaveBeenCalledWith("creator-demo", {
        platform: "bilibili",
        browser: "chrome",
        account_name: "Demo Creator · B 站",
        login_confirmed: true,
      });
    });
  });

  it("does not treat legacy login reference bindings as confirmed accounts", async () => {
    apiMock.getPublicationProfile.mockResolvedValueOnce({
      id: "profile-1",
      creator_card_id: "creator-demo",
      status: "active",
      publication_payload_json: {
        default_platforms: ["bilibili"],
        platform_rules: {},
      },
      created_at: "2026-06-19T00:00:00Z",
      updated_at: "2026-06-19T00:00:00Z",
      bindings: [
        {
          id: "binding-1",
          platform: "bilibili",
          credential_ref: "social-auto-upload:旧账号:bilibili",
          binding_payload_json: {
            adapter: "social_auto_upload",
            status: "login_reference_bound",
            account_name: "旧账号",
          },
          created_at: "2026-06-19T00:00:00Z",
          updated_at: "2026-06-19T00:00:00Z",
        },
      ],
      versions: [],
    });

    renderWithQueryClient(<PublicationManagementPage />);

    expect(await screen.findByText("需重新登录确认账号")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "自动发布" })[0]).toBeDisabled();
  });

  it("opens the bound platform dashboard for account confirmation", async () => {
    apiMock.getPublicationProfile.mockResolvedValueOnce({
      id: "profile-1",
      creator_card_id: "creator-demo",
      status: "active",
      publication_payload_json: {
        default_platforms: ["bilibili"],
        platform_rules: {},
      },
      created_at: "2026-06-19T00:00:00Z",
      updated_at: "2026-06-19T00:00:00Z",
      bindings: [
        {
          id: "binding-1",
          platform: "bilibili",
          credential_ref: "social-auto-upload:creator-demo-bilibili-chrome:bilibili",
          binding_payload_json: {
            adapter: "social_auto_upload",
            status: "login_confirmed",
            account_name: "creator-demo-bilibili-chrome",
            account_label: "Demo Creator · Chrome",
          },
          created_at: "2026-06-19T00:00:00Z",
          updated_at: "2026-06-19T00:00:00Z",
        },
      ],
      versions: [],
    });

    renderWithQueryClient(<PublicationManagementPage />);

    const dashboardButtons = await screen.findAllByRole("button", { name: "打开后台" });
    const enabledDashboardButton = dashboardButtons.find((button) => !button.hasAttribute("disabled"));
    expect(enabledDashboardButton).toBeTruthy();
    fireEvent.click(enabledDashboardButton!);

    await waitFor(() => {
      expect(apiMock.openSocialAutoUploadDashboard).toHaveBeenCalledWith("creator-demo", {
        platform: "bilibili",
        browser: "chrome",
      });
    });
    expect(await screen.findByText("后台窗口已打开")).toBeInTheDocument();
  });
});
