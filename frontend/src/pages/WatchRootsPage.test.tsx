import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";

import { WatchRootsPage } from "./WatchRootsPage";

const mockUseWatchRootWorkspace = vi.fn();

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

vi.mock("../components/ui/PageSection", () => ({
  PageSection: ({ title, className, children }: { title: string; className?: string; children: ReactNode }) => (
    <section className={className}>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}));

vi.mock("../features/watchRoots/WatchRootFormPanel", () => ({
  WatchRootFormPanel: () => <div>watch-root-form-panel</div>,
}));

vi.mock("../features/watchRoots/WatchRootInventoryPanel", () => ({
  WatchRootInventoryPanel: () => <div>watch-root-inventory-panel</div>,
}));

vi.mock("../features/watchRoots/WatchRootList", () => ({
  WatchRootList: () => <div>watch-root-list</div>,
}));

vi.mock("../features/watchRoots/useWatchRootWorkspace", () => ({
  useWatchRootWorkspace: () => mockUseWatchRootWorkspace(),
}));

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    options: { data: undefined },
    configProfiles: { data: { profiles: [] } },
    form: { config_profile_id: "", workflow_template: "" },
    selectedRootId: null,
    selectedRoot: undefined,
    selectedPending: [],
    roots: { data: [] },
    inventory: { data: undefined },
    updateState: undefined,
    updateError: undefined,
    createRoot: { isPending: false, mutate: vi.fn() },
    deleteRoot: { isPending: false, mutate: vi.fn() },
    scan: { isPending: false, mutate: vi.fn() },
    enqueue: { isPending: false, mutate: vi.fn() },
    merge: { isPending: false, mutate: vi.fn() },
    suggestMerge: { isPending: false, mutate: vi.fn() },
    mergeSuggested: { isPending: false, mutate: vi.fn() },
    setSelectedRootId: vi.fn(),
    setSelectedPending: vi.fn(),
    setForm: vi.fn(),
    refreshRoots: vi.fn(),
    ...overrides,
  };
}

describe("WatchRootsPage", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not render the old summary strip or explanatory copy on the watch-roots page", () => {
    mockUseWatchRootWorkspace.mockReturnValue(buildWorkspace());

    render(<WatchRootsPage />);

    expect(screen.queryByText("目录接入")).not.toBeInTheDocument();
    expect(screen.queryByText("库存整理")).not.toBeInTheDocument();
    expect(screen.queryByText("批量处理")).not.toBeInTheDocument();
    expect(screen.queryByText("先维护监听目录")).not.toBeInTheDocument();
    expect(screen.queryByText("扫描、整理并批量入队")).not.toBeInTheDocument();
    expect(screen.queryByText("默认配置")).not.toBeInTheDocument();
  });

  it("uses an ingest deck with inventory as the main workspace", () => {
    mockUseWatchRootWorkspace.mockReturnValue(buildWorkspace());

    const { container } = render(<WatchRootsPage />);

    expect(screen.getAllByText("待处理")).toHaveLength(1);
    expect(screen.getByText("目录")).toBeInTheDocument();
    expect(screen.getByText("新建目录")).toBeInTheDocument();
    expect(screen.getAllByText("watch.page.pickRoot")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "watch.page.refresh" })).toBeInTheDocument();
    expect(screen.getByText("watch-root-list")).toBeInTheDocument();
    expect(screen.getByText("watch-root-form-panel")).toBeInTheDocument();
    expect(container.querySelector(".watch-command-strip")).toBeInTheDocument();
    expect(container.querySelector(".watch-workbench")).toBeInTheDocument();
    expect(container.querySelector(".watch-health-lane")).toBeInTheDocument();
    expect(container.querySelector(".watch-roots-lane")).toBeInTheDocument();
    expect(container.querySelector(".watch-form-lane")).toBeInTheDocument();
  });

  it("keeps the inventory actions available when a root is selected", () => {
    mockUseWatchRootWorkspace.mockReturnValue(
      buildWorkspace({
        selectedRootId: "root-1",
        selectedRoot: { id: "root-1", name: "root-1" },
        inventory: { data: undefined },
      }),
    );

    const { container } = render(<WatchRootsPage />);

    expect(screen.getByText("watch-root-inventory-panel")).toBeInTheDocument();
    expect(screen.getByText("watch-root-list")).toBeInTheDocument();
    expect(screen.getByText("watch-root-form-panel")).toBeInTheDocument();
    expect(container.querySelector(".watch-health-lane")).toBeInTheDocument();
    expect(screen.getByText("编辑目录")).toBeInTheDocument();
  });
});
