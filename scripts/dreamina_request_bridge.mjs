import { appendFile, mkdir } from "node:fs/promises";
import { dirname, resolve as resolvePath } from "node:path";
import { pathToFileURL } from "node:url";

function normalizeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function isDebugEnabled(payload = {}) {
  const config = normalizeObject(payload.config);
  const values = [
    config.debug,
    config.verbose,
    process.env.HYDRA_DREAMINA_DEBUG,
    process.env.INTELLIGENT_COPY_COVER_DREAMINA_DEBUG
  ];
  return values.some((value) => {
    const normalized = normalizeText(String(value ?? "")).toLowerCase();
    return ["1", "true", "yes", "on", "debug"].includes(normalized);
  });
}

function resolveDebugLogPath(payload = {}) {
  const config = normalizeObject(payload.config);
  const configured = normalizeText(
    config.debugLogPath ||
      config.debug_log_path ||
      process.env.HYDRA_DREAMINA_DEBUG_LOG_PATH ||
      process.env.INTELLIGENT_COPY_COVER_DREAMINA_DEBUG_LOG_PATH
  );
  if (configured) {
    return resolvePath(configured);
  }
  return "";
}

async function appendDebugLog(logPath, line) {
  if (!logPath) {
    return;
  }
  await mkdir(dirname(logPath), { recursive: true });
  await appendFile(logPath, `${line}\n`, "utf8");
}

async function logDebug(enabled, logPath, stage, detail = {}) {
  if (!enabled) {
    return;
  }
  const line = `[dreamina-bridge] ${JSON.stringify({ ts: new Date().toISOString(), stage, ...normalizeObject(detail) })}`;
  process.stderr.write(`${line}\n`);
  await appendDebugLog(logPath, line).catch(() => {});
}

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk)));
  }
  return Buffer.concat(chunks).toString("utf8");
}

async function main() {
  const raw = await readStdin();
  const payload = raw ? JSON.parse(raw) : {};
  const debugEnabled = isDebugEnabled(payload);
  const debugLogPath = resolveDebugLogPath(payload);
  const runnerScript = normalizeText(payload.runnerScript);
  if (!runnerScript) {
    throw new Error("dreamina_runner_script_missing");
  }
  await logDebug(debugEnabled, debugLogPath, "bridge_start", {
    runnerScript,
    requestKeys: Object.keys(normalizeObject(payload.requestSpec)),
    configKeys: Object.keys(normalizeObject(payload.config))
  });
  const runnerModule = await import(pathToFileURL(runnerScript).href);
  if (typeof runnerModule.requestDreaminaWebImageGeneration !== "function") {
    throw new Error("dreamina_runner_missing_request_function");
  }
  await logDebug(debugEnabled, debugLogPath, "runner_imported");
  const result = await runnerModule.requestDreaminaWebImageGeneration({
    env: process.env,
    config: normalizeObject(payload.config),
    requestSpec: normalizeObject(payload.requestSpec)
  });
  await logDebug(debugEnabled, debugLogPath, "bridge_complete", {
    generationStatus: normalizeText(result?.generationStatus),
    transport: normalizeText(result?.responseMeta?.transport)
  });
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  const message = normalizeText(error?.stack) || normalizeText(error?.message) || "dreamina_bridge_failed";
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
