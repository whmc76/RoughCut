import type { ContentProfileMemoryStats } from "../types";
import { request } from "./core";

export const memoryApi = {
  getMemoryStats: (subjectDomain?: string) =>
    request<ContentProfileMemoryStats>(`/jobs/stats/content-profile-memory${subjectDomain ? `?subject_domain=${encodeURIComponent(subjectDomain)}` : ""}`),
};
