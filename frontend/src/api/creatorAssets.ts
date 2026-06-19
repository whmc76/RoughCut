import type {
  CreatorCard,
  CreatorCardList,
  CreatorPublicationProfile,
  CreatorTaskStrategy,
  CreatorTaskStrategyList,
  CreatorVisualPlan,
  CreatorVisualPlanList,
  PlanVersion,
} from "../types";
import { apiPath, request, requestForm } from "./core";

export const creatorAssetsApi = {
  listCreatorCards: () => request<CreatorCardList>("/creator-cards"),
  createCreatorCard: (body: Record<string, unknown>) =>
    request<CreatorCard>("/creator-cards", { method: "POST", body: JSON.stringify(body) }),
  patchCreatorCard: (creatorId: string, body: Record<string, unknown>) =>
    request<CreatorCard>(`/creator-cards/${creatorId}`, { method: "PATCH", body: JSON.stringify(body) }),
  refineCreatorCard: (creatorId: string, prompt: string, preferenceType = "profile_refine") =>
    request<CreatorCard>(`/creator-cards/${creatorId}/refine`, {
      method: "POST",
      body: JSON.stringify({ prompt, preference_type: preferenceType }),
    }),
  uploadCreatorAsset: (creatorId: string, file: File, assetType?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (assetType) formData.append("asset_type", assetType);
    return requestForm<CreatorCard>(`/creator-cards/${creatorId}/assets`, formData);
  },
  deleteCreatorAsset: (creatorId: string, assetId: string) =>
    request<CreatorCard>(`/creator-cards/${creatorId}/assets/${assetId}`, { method: "DELETE" }),
  creatorAssetUrl: (creatorId: string, assetId: string) =>
    apiPath(`/creator-cards/${creatorId}/assets/${assetId}/file`),
  listTaskStrategies: (creatorId: string) =>
    request<CreatorTaskStrategyList>(`/creator-cards/${creatorId}/task-strategies`),
  generateTaskStrategies: (creatorId: string, body: { prompt: string; strategy_type?: string; candidate_count?: number }) =>
    request<CreatorTaskStrategyList>(`/creator-cards/${creatorId}/task-strategies/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  refineTaskStrategy: (strategyId: string, prompt: string) =>
    request<CreatorTaskStrategy>(`/creator-cards/task-strategies/${strategyId}/refine`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  activateTaskStrategy: (strategyId: string) =>
    request<CreatorTaskStrategy>(`/creator-cards/task-strategies/${strategyId}/activate`, { method: "POST" }),
  listTaskStrategyVersions: (strategyId: string) =>
    request<PlanVersion[]>(`/creator-cards/task-strategies/${strategyId}/versions`),
  listVisualPlans: (creatorId: string) =>
    request<CreatorVisualPlanList>(`/creator-cards/${creatorId}/visual-plans`),
  generateVisualPlans: (creatorId: string, body: { prompt: string; candidate_count?: number }) =>
    request<CreatorVisualPlanList>(`/creator-cards/${creatorId}/visual-plans/generate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  refineVisualPlan: (visualPlanId: string, prompt: string) =>
    request<CreatorVisualPlan>(`/creator-cards/visual-plans/${visualPlanId}/refine`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  activateVisualPlan: (visualPlanId: string) =>
    request<CreatorVisualPlan>(`/creator-cards/visual-plans/${visualPlanId}/activate`, { method: "POST" }),
  listVisualPlanVersions: (visualPlanId: string) =>
    request<PlanVersion[]>(`/creator-cards/visual-plans/${visualPlanId}/versions`),
  getPublicationProfile: (creatorId: string) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/publication-profile`),
  patchPublicationProfile: (creatorId: string, body: { status?: string; publication_payload_json?: Record<string, unknown> }) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/publication-profile`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  refinePublicationProfile: (creatorId: string, prompt: string) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/publication-profile/refine`, {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  addPlatformBinding: (
    creatorId: string,
    body: { platform: string; credential_ref?: string; binding_payload_json?: Record<string, unknown> },
  ) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/platform-bindings`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  bindSocialAutoUploadLogin: (
    creatorId: string,
    body: { platform: string; browser?: string; account_name?: string; login_confirmed?: boolean },
  ) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/platform-bindings/social-auto-upload`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  startSocialAutoUploadLogin: (
    creatorId: string,
    body: { platform: string; browser?: string; account_name?: string },
  ) =>
    request<Record<string, unknown>>(`/creator-cards/${creatorId}/platform-bindings/social-auto-upload/login`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  checkSocialAutoUploadLogin: (
    creatorId: string,
    body: { platform: string; browser?: string; account_name?: string },
  ) =>
    request<Record<string, unknown>>(`/creator-cards/${creatorId}/platform-bindings/social-auto-upload/login-status`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  openSocialAutoUploadDashboard: (
    creatorId: string,
    body: { platform: string; browser?: string },
  ) =>
    request<Record<string, unknown>>(`/creator-cards/${creatorId}/platform-bindings/social-auto-upload/dashboard`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deletePlatformBinding: (creatorId: string, platform: string) =>
    request<CreatorPublicationProfile>(`/creator-cards/${creatorId}/platform-bindings/${encodeURIComponent(platform)}`, {
      method: "DELETE",
    }),
};
