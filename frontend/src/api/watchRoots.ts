import type { WatchInventorySmartMerge, WatchInventoryStatus, WatchRoot } from "../types";
import { apiPath, request } from "./core";

export const watchRootsApi = {
  listWatchRoots: () => request<WatchRoot[]>("/watch-roots"),
  createWatchRoot: (body: Partial<WatchRoot> & { path: string }) => request<WatchRoot>("/watch-roots", { method: "POST", body: JSON.stringify(body) }),
  updateWatchRoot: (rootId: string, body: Partial<WatchRoot> & { path: string }) =>
    request<WatchRoot>(`/watch-roots/${rootId}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteWatchRoot: (rootId: string) => request<void>(`/watch-roots/${rootId}`, { method: "DELETE" }),
  startInventoryScan: (rootId: string, force = false) =>
    request<WatchInventoryStatus>(`/watch-roots/${rootId}/inventory/scan`, { method: "POST", body: JSON.stringify({ force }) }),
  getInventoryStatus: (rootId: string, includeInventory = true) =>
    request<WatchInventoryStatus>(`/watch-roots/${rootId}/inventory/status?include_inventory=${includeInventory ? "true" : "false"}&inventory_limit=200`),
  enqueueInventory: (rootId: string, relativePaths: string[], enqueueAll = false) =>
    request<{ requested_count: number; created_count: number; skipped_count: number; created_job_ids: string[] }>(
      `/watch-roots/${rootId}/inventory/enqueue`,
      { method: "POST", body: JSON.stringify({ relative_paths: relativePaths, enqueue_all: enqueueAll }) },
    ),
  mergeInventory: (rootId: string, relativePaths: string[]) =>
    request<{ requested_count: number; created_count: number; skipped_count: number; created_job_ids: string[] }>(
      `/watch-roots/${rootId}/inventory/merge`,
      { method: "POST", body: JSON.stringify({ relative_paths: relativePaths }) },
    ),
  getSmartMergeGroups: (rootId: string) =>
    request<WatchInventorySmartMerge>(`/watch-roots/${rootId}/inventory/smart-groups`),
  inventoryThumbnailUrl: (rootId: string, relativePath: string) =>
    apiPath(`/watch-roots/${rootId}/inventory/thumbnail?relative_path=${encodeURIComponent(relativePath)}`),
};
