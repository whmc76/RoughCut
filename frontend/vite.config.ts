/// <reference types="node" />

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function readEnvFile(path: string): Record<string, string> {
  if (!existsSync(path)) return {};
  const values: Record<string, string> = {};
  for (const line of readFileSync(path, "utf-8").split(/\r?\n/)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*(?:#.*)?$/);
    if (!match) continue;
    const raw = match[2].trim();
    values[match[1]] =
      (raw.startsWith('"') && raw.endsWith('"')) || (raw.startsWith("'") && raw.endsWith("'"))
        ? raw.slice(1, -1)
        : raw;
  }
  return values;
}

function readConfiguredPort(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

export default defineConfig(({ mode }) => {
  const repoRoot = resolve(__dirname, "..");
  const portEnv = readEnvFile(resolve(repoRoot, "roughcut.ports.env"));
  const rootEnv = loadEnv(mode, repoRoot, "");
  const frontendEnv = loadEnv(mode, ".", "");
  const env = { ...rootEnv, ...frontendEnv, ...portEnv };
  const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
  const apiPort = readConfiguredPort(runtimeEnv.ROUGHCUT_API_PORT || env.ROUGHCUT_API_PORT, 38471);
  const frontendPort = readConfiguredPort(
    runtimeEnv.VITE_DEV_PORT
      || env.VITE_DEV_PORT
      || runtimeEnv.ROUGHCUT_FRONTEND_DEV_PORT
      || env.ROUGHCUT_FRONTEND_DEV_PORT,
    5173,
  );
  const apiProxyTarget = runtimeEnv.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || `http://127.0.0.1:${apiPort}`;
  const devHost = runtimeEnv.VITE_DEV_HOST || env.VITE_DEV_HOST || "127.0.0.1";
  const devPort = frontendPort;
  const hmrHost = runtimeEnv.VITE_HMR_HOST || env.VITE_HMR_HOST || undefined;
  const hmrClientPort = Number(runtimeEnv.VITE_HMR_CLIENT_PORT || env.VITE_HMR_CLIENT_PORT || 0);

  return {
    plugins: [react()],
    server: {
      host: devHost,
      port: devPort,
      strictPort: true,
      hmr: hmrHost
        ? {
            host: hmrHost,
            ...(hmrClientPort > 0 ? { clientPort: hmrClientPort } : {}),
          }
        : undefined,
      proxy: {
        "/api": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
        "/health": {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
