import type { ContentProfileMemoryStats } from "../types";
import { request } from "./core";

export const memoryApi = {
  getMemoryStats: (channelProfile?: string) =>
    request<ContentProfileMemoryStats>(`/jobs/stats/content-profile-memory${channelProfile ? `?channel_profile=${encodeURIComponent(channelProfile)}` : ""}`),
};
