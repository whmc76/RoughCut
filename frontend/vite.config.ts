import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
  const apiProxyTarget = runtimeEnv.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000";
  const devHost = runtimeEnv.VITE_DEV_HOST || env.VITE_DEV_HOST || "127.0.0.1";
  const devPort = Number(runtimeEnv.VITE_DEV_PORT || env.VITE_DEV_PORT || 5173);
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
