import type { Config, ConfigOptions } from "../types";
import { request } from "./core";

export const configApi = {
  getConfig: () => request<Config>("/config"),
  getConfigOptions: () => request<ConfigOptions>("/config/options"),
  patchConfig: (body: Record<string, unknown>) => request<Config>("/config", { method: "PATCH", body: JSON.stringify(body) }),
  resetConfig: () => request<void>("/config/overrides", { method: "DELETE" }),
};
