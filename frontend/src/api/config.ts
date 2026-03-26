import type { Config, ConfigOptions, ConfigProfiles, RuntimeEnvironment } from "../types";
import { request } from "./core";

export const configApi = {
  getConfig: () => request<Config>("/config"),
  getRuntimeEnvironment: () => request<RuntimeEnvironment>("/config/environment"),
  getConfigOptions: () => request<ConfigOptions>("/config/options"),
  getConfigProfiles: () => request<ConfigProfiles>("/config/profiles"),
  createConfigProfile: (name: string, description?: string) =>
    request<ConfigProfiles>("/config/profiles", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
  updateConfigProfile: (profileId: string, body: { name?: string; description?: string; capture_current?: boolean }) =>
    request<ConfigProfiles>(`/config/profiles/${profileId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  activateConfigProfile: (profileId: string) =>
    request<ConfigProfiles>(`/config/profiles/${profileId}/activate`, {
      method: "POST",
    }),
  deleteConfigProfile: (profileId: string) =>
    request<ConfigProfiles>(`/config/profiles/${profileId}`, {
      method: "DELETE",
    }),
  patchConfig: (body: Record<string, unknown>) => request<Config>("/config", { method: "PATCH", body: JSON.stringify(body) }),
  resetConfig: () => request<void>("/config/overrides", { method: "DELETE" }),
};
