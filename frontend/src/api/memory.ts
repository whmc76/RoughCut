import type { ContentProfileMemoryStats, LearnedHotword } from "../types";
import { request } from "./core";

export const memoryApi = {
  getMemoryStats: (subjectDomain?: string) =>
    request<ContentProfileMemoryStats>(`/jobs/stats/content-profile-memory${subjectDomain ? `?subject_domain=${encodeURIComponent(subjectDomain)}` : ""}`),
  listLearnedHotwords: (params?: { subject_domain?: string; status?: "active" | "suppressed" | "rejected" | "all"; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.subject_domain) query.set("subject_domain", params.subject_domain);
    if (params?.status) query.set("status", params.status);
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return request<LearnedHotword[]>(`/learned-hotwords${suffix ? `?${suffix}` : ""}`);
  },
  updateLearnedHotword: (hotwordId: string, body: Partial<Pick<LearnedHotword, "aliases" | "confidence" | "status">>) =>
    request<LearnedHotword>(`/learned-hotwords/${hotwordId}`, { method: "PATCH", body: JSON.stringify(body) }),
};
