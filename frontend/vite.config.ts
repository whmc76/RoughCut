/// <reference types="node" />

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { existsSync, readFileSync } from "node:fs";
import { createReadStream } from "node:fs";
import { extname, isAbsolute, resolve } from "node:path";

const LOCAL_IMAGE_PREVIEW_PATH = "/__roughcut_local_image";
const LOCAL_IMAGE_MIME_TYPES: Record<string, string> = {
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".png": "image/png",
  ".webp": "image/webp",
};

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

function resolveLocalPreviewImagePath(imagePath: string, repoRoot: string, runtimeEnv: Record<string, string | undefined>, env: Record<string, string>) {
  const normalized = String(imagePath || "").trim().replace(/\\/g, "/");
  if (!normalized) return "";
  const containerPrefix = "/app/data/";
  if (normalized.startsWith(containerPrefix)) {
    const hostRuntimeRoot = resolve(runtimeEnv.ROUGHCUT_OUTPUT_HOST_ROOT || env.ROUGHCUT_OUTPUT_HOST_ROOT || resolve(repoRoot, "data", "runtime"));
    const relativePath = normalized.slice(containerPrefix.length).replace(/^\/+/, "");
    return resolve(hostRuntimeRoot, relativePath);
  }
  if (isAbsolute(imagePath)) {
    return imagePath;
  }
  return resolve(repoRoot, normalized);
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
  const devHost = runtimeEnv.VITE_DEV_HOST || env.VITE_DEV_HOST || "0.0.0.0";
  const devPort = frontendPort;
  const hmrHost = runtimeEnv.VITE_HMR_HOST || env.VITE_HMR_HOST || undefined;
  const hmrClientPort = Number(runtimeEnv.VITE_HMR_CLIENT_PORT || env.VITE_HMR_CLIENT_PORT || 0);

  return {
    plugins: [
      react(),
      {
        name: "roughcut-local-image-preview",
        configureServer(server) {
          server.middlewares.use(LOCAL_IMAGE_PREVIEW_PATH, (req, res) => {
            const rawUrl = req.url ?? "";
            const url = new URL(rawUrl, "http://127.0.0.1");
            const imagePath = url.searchParams.get("path") ?? "";
            const resolvedPath = resolveLocalPreviewImagePath(imagePath, repoRoot, runtimeEnv, env);
            const extension = extname(resolvedPath).toLowerCase();
            const contentType = LOCAL_IMAGE_MIME_TYPES[extension];
            if (!resolvedPath || !contentType || !existsSync(resolvedPath)) {
              res.statusCode = 404;
              res.end("Not found");
              return;
            }
            res.setHeader("Content-Type", contentType);
            res.setHeader("Cache-Control", "no-store");
            createReadStream(resolvedPath).on("error", () => {
              if (!res.headersSent) res.statusCode = 500;
              res.end("Failed to read image");
            }).pipe(res);
          });
        },
      },
    ],
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
