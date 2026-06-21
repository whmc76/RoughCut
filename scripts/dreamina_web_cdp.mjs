import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { appendFile, copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, dirname, extname, resolve as resolvePath } from "node:path";

function normalizeText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function normalizeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function normalizeList(value) {
  return Array.isArray(value) ? value : [];
}

function firstNonEmpty(...values) {
  for (const value of values) {
    const normalized = normalizeText(value);
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function safeJsonParse(value, fallback = {}) {
  if (value && typeof value === "object") {
    return value;
  }
  const text = normalizeText(value);
  if (!text) {
    return fallback;
  }
  try {
    return JSON.parse(text);
  } catch {
    return fallback;
  }
}

function parseBooleanish(value, fallback = false) {
  if (typeof value === "boolean") {
    return value;
  }
  const normalized = normalizeText(String(value ?? "")).toLowerCase();
  if (!normalized) {
    return fallback;
  }
  if (["1", "true", "yes", "on"].includes(normalized)) {
    return true;
  }
  if (["0", "false", "no", "off"].includes(normalized)) {
    return false;
  }
  return fallback;
}

function isDreaminaDebugEnabled(config = {}) {
  return parseBooleanish(
    firstNonEmpty(
      String(normalizeObject(config).debug ?? ""),
      String(normalizeObject(config).verbose ?? ""),
      process.env.HYDRA_DREAMINA_DEBUG,
      process.env.INTELLIGENT_COPY_COVER_DREAMINA_DEBUG
    ),
    false
  );
}

function resolveDreaminaDebugLogPath(config = {}) {
  const configured = firstNonEmpty(
    normalizeObject(config).debugLogPath,
    normalizeObject(config).debug_log_path,
    process.env.HYDRA_DREAMINA_DEBUG_LOG_PATH,
    process.env.INTELLIGENT_COPY_COVER_DREAMINA_DEBUG_LOG_PATH
  );
  return configured ? resolvePath(configured) : "";
}

function logDreaminaStage(config = {}, stage = "", detail = {}) {
  if (!isDreaminaDebugEnabled(config)) {
    return;
  }
  const line = `[dreamina-runner] ${JSON.stringify({ ts: new Date().toISOString(), stage, ...normalizeObject(detail) })}`;
  process.stderr.write(`${line}\n`);
  const logPath = resolveDreaminaDebugLogPath(config);
  if (!logPath) {
    return;
  }
  ensureParentDirectory(logPath)
    .then(() => appendFile(logPath, `${line}\n`, "utf8"))
    .catch(() => {});
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function sleep(timeoutMs = 0) {
  return new Promise((resolve) => {
    setTimeout(resolve, Math.max(0, Number(timeoutMs) || 0));
  });
}

async function ensureParentDirectory(path = "") {
  const normalizedPath = normalizeText(path);
  if (!normalizedPath) {
    return;
  }
  await mkdir(dirname(normalizedPath), { recursive: true });
}

function encodeUtf8Base64(value = "") {
  return Buffer.from(String(value), "utf8").toString("base64");
}

function decodeUtf8Base64(value = "") {
  const normalized = normalizeText(value);
  if (!normalized) {
    return "";
  }
  try {
    return Buffer.from(normalized, "base64").toString("utf8");
  } catch {
    return "";
  }
}

function normalizeReferenceAliasFromPath(filePath = "") {
  const base = basename(normalizeText(filePath), extname(normalizeText(filePath)));
  return normalizeText(base).replace(/[^\w.-]+/gu, "_");
}

function buildDreaminaSafeReferenceFilename(alias = "", originalPath = "") {
  const normalizedAlias = normalizeReferenceAliasFromPath(alias || originalPath || "reference_image");
  const extension = extname(normalizeText(originalPath)) || ".png";
  return `${normalizedAlias}${extension}`;
}

function normalizeDreaminaReferenceImageSpecs(value) {
  return normalizeList(value)
    .map((entry) => {
      if (typeof entry === "string") {
        const filePath = normalizeText(entry);
        return filePath
          ? {
              path: filePath,
              alias: normalizeReferenceAliasFromPath(filePath)
            }
          : null;
      }
      const normalized = normalizeObject(entry);
      const filePath = firstNonEmpty(
        normalized.path,
        normalized.filePath,
        normalized.local_path,
        normalized.localPath
      );
      if (!filePath) {
        return null;
      }
      return {
        path: filePath,
        alias: firstNonEmpty(
          normalized.alias,
          normalized.mentionAlias,
          normalized.referenceAlias,
          normalizeReferenceAliasFromPath(filePath)
        )
      };
    })
    .filter(Boolean);
}

const DREAMINA_MODEL_REQ_KEY_ALIASES = new Map(
  [
    ["5.0", "high_aes_general_v50"],
    ["5.0lite", "high_aes_general_v50"],
    ["图片5.0", "high_aes_general_v50"],
    ["图片5.0lite", "high_aes_general_v50"],
    ["seedream5.0", "high_aes_general_v50"],
    ["seedream5.0lite", "high_aes_general_v50"],
    ["4.7", "high_aes_general_v43"],
    ["图片4.7", "high_aes_general_v43"],
    ["seedream4.7", "high_aes_general_v43"],
    ["4.6", "high_aes_general_v42"],
    ["图片4.6", "high_aes_general_v42"],
    ["seedream4.6", "high_aes_general_v42"],
    ["4.5", "high_aes_general_v40l"],
    ["图片4.5", "high_aes_general_v40l"],
    ["seedream4.5", "high_aes_general_v40l"],
    ["4.1", "high_aes_general_v41"],
    ["图片4.1", "high_aes_general_v41"],
    ["seedream4.1", "high_aes_general_v41"],
    ["4.0", "high_aes_general_v40"],
    ["图片4.0", "high_aes_general_v40"],
    ["seedream4.0", "high_aes_general_v40"],
    ["3.1", "high_aes_general_v30l_art_fangzhou:general_v3.0_18b"],
    ["图片3.1", "high_aes_general_v30l_art_fangzhou:general_v3.0_18b"],
    ["seedream3.1", "high_aes_general_v30l_art_fangzhou:general_v3.0_18b"],
    ["3.0", "high_aes_general_v30l:general_v3.0_18b"],
    ["图片3.0", "high_aes_general_v30l:general_v3.0_18b"],
    ["seedream3.0", "high_aes_general_v30l:general_v3.0_18b"]
  ].map(([key, value]) => [key.toLowerCase(), value])
);

function normalizeDreaminaModelSelector(value = "") {
  return normalizeText(value)
    .toLowerCase()
    .replace(/^by/iu, "")
    .replace(/seedream/giu, "seedream")
    .replace(/\s+/gu, "")
    .replace(/design/giu, "")
    .replace(/[()]/gu, "");
}

function resolveDreaminaKnownModelReqKey(value = "") {
  const normalized = normalizeText(value);
  if (!normalized) {
    return "";
  }
  if (/^high_aes_general_/iu.test(normalized)) {
    return normalized;
  }
  return (
    DREAMINA_MODEL_REQ_KEY_ALIASES.get(normalizeDreaminaModelSelector(normalized)) || normalized
  );
}

function isDreaminaModelSelector(value = "") {
  const normalized = normalizeText(value);
  if (!normalized) {
    return false;
  }
  if (/^high_aes_general_/iu.test(normalized)) {
    return true;
  }
  const selector = normalizeDreaminaModelSelector(normalized);
  if (DREAMINA_MODEL_REQ_KEY_ALIASES.has(selector)) {
    return true;
  }
  return /^(\d+\.\d+)(lite)?$/u.test(selector) || /^图片(\d+\.\d+)(lite)?$/u.test(selector);
}

function normalizeDreaminaResolutionType(value = "") {
  const normalized = normalizeText(value).toLowerCase();
  if (!normalized) {
    return "";
  }
  if (normalized === "2k" || normalized === "4k") {
    return normalized;
  }
  if (normalized === "高清2k" || normalized === "高清 2k") {
    return "2k";
  }
  if (normalized === "超清4k" || normalized === "超清 4k") {
    return "4k";
  }
  return normalized;
}

function normalizeDreaminaCandidateSelectionPolicy(value = "") {
  const normalized = normalizeText(value).toLowerCase().replace(/[\s-]+/gu, "_");
  if (normalized === "largest" || normalized === "largest_area" || normalized === "max_area") {
    return "largest_area";
  }
  if (normalized === "last" || normalized === "final") {
    return "last";
  }
  return "first";
}

function shouldHydrateDreaminaCookies(config = {}) {
  const cookieSourceBaseUrl = normalizeText(config.cdpCookieSourceBaseUrl);
  const targetBaseUrl = normalizeText(config.cdpBaseUrl);
  return Boolean(cookieSourceBaseUrl && cookieSourceBaseUrl !== targetBaseUrl);
}

function createDeferred() {
  let resolve = null;
  let reject = null;
  const promise = new Promise((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });
  return { promise, resolve, reject };
}

class CdpSession {
  constructor(webSocketUrl = "") {
    this.webSocketUrl = normalizeText(webSocketUrl);
    this.socket = null;
    this.nextId = 1;
    this.pending = new Map();
    this.eventQueue = [];
    this.waiters = new Set();
  }

  async connect() {
    if (!this.webSocketUrl) {
      throw new Error("dreamina_cdp_websocket_missing");
    }
    if (typeof WebSocket !== "function") {
      throw new Error("dreamina_cdp_websocket_unavailable");
    }
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return this;
    }
    const socket = new WebSocket(this.webSocketUrl);
    await new Promise((resolve, reject) => {
      socket.onopen = () => resolve();
      socket.onerror = (event) => reject(event?.error || new Error("dreamina_cdp_connect_failed"));
    });
    socket.onmessage = (event) => {
      const payload = safeJsonParse(event.data, null);
      if (!payload || typeof payload !== "object") {
        return;
      }
      if (payload.id) {
        const pending = this.pending.get(payload.id);
        if (!pending) {
          return;
        }
        this.pending.delete(payload.id);
        if (payload.error) {
          pending.reject(
            new Error(
              firstNonEmpty(
                normalizeObject(payload.error).message,
                "dreamina_cdp_command_failed"
              )
            )
          );
          return;
        }
        pending.resolve(payload.result ?? {});
        return;
      }
      this.eventQueue.push(payload);
      for (const waiter of Array.from(this.waiters)) {
        if (waiter.tryResolve(payload)) {
          this.waiters.delete(waiter);
        }
      }
    };
    socket.onclose = () => {
      for (const pending of this.pending.values()) {
        pending.reject(new Error("dreamina_cdp_socket_closed"));
      }
      this.pending.clear();
    };
    this.socket = socket;
    return this;
  }

  async send(method, params = {}) {
    await this.connect();
    const id = this.nextId++;
    const deferred = createDeferred();
    this.pending.set(id, deferred);
    this.socket.send(JSON.stringify({ id, method, params }));
    return deferred.promise;
  }

  async waitForEvent(predicate, timeoutMs = 30_000) {
    const eventPredicate = typeof predicate === "function" ? predicate : () => false;
    for (const event of this.eventQueue) {
      if (eventPredicate(event)) {
        return event;
      }
    }
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.waiters.delete(waiter);
        reject(new Error("dreamina_cdp_event_timeout"));
      }, Math.max(1, Number(timeoutMs) || 30_000));
      const waiter = {
        tryResolve: (event) => {
          if (!eventPredicate(event)) {
            return false;
          }
          clearTimeout(timeout);
          resolve(event);
          return true;
        }
      };
      this.waiters.add(waiter);
    });
  }

  async close() {
    if (!this.socket) {
      return;
    }
    try {
      this.socket.close();
    } finally {
      this.socket = null;
    }
  }
}

export function resolveDreaminaWebImageGenerationConfig(env = {}, backend = {}) {
  const normalizedBackend = normalizeObject(backend);
  const requestedModelVersion = firstNonEmpty(
    normalizedBackend.model,
    normalizedBackend.imageModel,
    env.HYDRA_DREAMINA_MODEL_VERSION,
    process.env.HYDRA_DREAMINA_MODEL_VERSION
  );
  const requestedResolutionType = firstNonEmpty(
    normalizedBackend.quality,
    env.HYDRA_DREAMINA_RESOLUTION_TYPE,
    process.env.HYDRA_DREAMINA_RESOLUTION_TYPE,
    "2k"
  );
  return {
    provider: firstNonEmpty(normalizedBackend.provider, "dreamina_web"),
    implementation: "dreamina_web_cdp",
    cdpBaseUrl: firstNonEmpty(
      normalizedBackend.cdpBaseUrl,
      normalizedBackend.cdp_base_url,
      env.HYDRA_DREAMINA_CDP_URL,
      process.env.HYDRA_DREAMINA_CDP_URL,
      "http://127.0.0.1:9222"
    ),
    cdpTargetPageUrl: firstNonEmpty(
      normalizedBackend.cdpTargetPageUrl,
      normalizedBackend.cdp_target_page_url,
      env.HYDRA_DREAMINA_TARGET_PAGE_URL,
      process.env.HYDRA_DREAMINA_TARGET_PAGE_URL,
      "https://jimeng.jianying.com/ai-tool/generate/?type=image"
    ),
    cdpWebSocketUrl: firstNonEmpty(
      env.HYDRA_DREAMINA_CDP_WEBSOCKET_URL,
      process.env.HYDRA_DREAMINA_CDP_WEBSOCKET_URL,
      normalizedBackend.cdpWebSocketUrl,
      normalizedBackend.cdp_websocket_url,
      ""
    ),
    pageUrlPattern: firstNonEmpty(
      normalizedBackend.pageUrlPattern,
      normalizedBackend.page_url_pattern,
      env.HYDRA_DREAMINA_PAGE_URL_PATTERN,
      process.env.HYDRA_DREAMINA_PAGE_URL_PATTERN,
      "jimeng.jianying.com/ai-tool/generate"
    ),
    cdpAutoLaunch: parseBooleanish(
      firstNonEmpty(
        String(normalizedBackend.cdpAutoLaunch ?? normalizedBackend.cdp_auto_launch ?? ""),
        env.HYDRA_DREAMINA_CDP_AUTO_LAUNCH,
        process.env.HYDRA_DREAMINA_CDP_AUTO_LAUNCH,
        "true"
      ),
      true
    ),
    cdpHeadless: parseBooleanish(
      firstNonEmpty(
        String(normalizedBackend.cdpHeadless ?? normalizedBackend.cdp_headless ?? ""),
        env.HYDRA_DREAMINA_CDP_HEADLESS,
        process.env.HYDRA_DREAMINA_CDP_HEADLESS,
        "true"
      ),
      true
    ),
    cdpKeepAlive: parseBooleanish(
      firstNonEmpty(
        String(normalizedBackend.cdpKeepAlive ?? normalizedBackend.cdp_keep_alive ?? ""),
        env.HYDRA_DREAMINA_CDP_KEEP_ALIVE,
        process.env.HYDRA_DREAMINA_CDP_KEEP_ALIVE,
        ""
      ),
      false
    ),
    cdpForceCreateTarget: parseBooleanish(
      firstNonEmpty(
        String(normalizedBackend.cdpForceCreateTarget ?? normalizedBackend.cdp_force_create_target ?? ""),
        env.HYDRA_DREAMINA_CDP_FORCE_CREATE_TARGET,
        process.env.HYDRA_DREAMINA_CDP_FORCE_CREATE_TARGET,
        ""
      ),
      false
    ),
    cdpExecutablePath: firstNonEmpty(
      normalizedBackend.cdpExecutablePath,
      normalizedBackend.cdp_executable_path,
      env.HYDRA_DREAMINA_CDP_EXECUTABLE_PATH,
      process.env.HYDRA_DREAMINA_CDP_EXECUTABLE_PATH,
      ""
    ),
    cdpUserDataDir: firstNonEmpty(
      normalizedBackend.cdpUserDataDir,
      normalizedBackend.cdp_user_data_dir,
      env.HYDRA_DREAMINA_CDP_USER_DATA_DIR,
      process.env.HYDRA_DREAMINA_CDP_USER_DATA_DIR,
      "./data/runtime/dreamina-profile"
    ),
    cdpHeadlessUserDataDir: firstNonEmpty(
      normalizedBackend.cdpHeadlessUserDataDir,
      normalizedBackend.cdp_headless_user_data_dir,
      env.HYDRA_DREAMINA_CDP_HEADLESS_USER_DATA_DIR,
      process.env.HYDRA_DREAMINA_CDP_HEADLESS_USER_DATA_DIR,
      "./data/runtime/dreamina-profile-headless"
    ),
    cdpCookieSourceBaseUrl: firstNonEmpty(
      normalizedBackend.cdpCookieSourceBaseUrl,
      normalizedBackend.cdp_cookie_source_base_url,
      env.HYDRA_DREAMINA_CDP_COOKIE_SOURCE_URL,
      process.env.HYDRA_DREAMINA_CDP_COOKIE_SOURCE_URL,
      "http://127.0.0.1:9222"
    ),
    cdpLaunchTimeoutMs: Math.max(
      1_000,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.cdpLaunchTimeoutMs ?? normalizedBackend.cdp_launch_timeout_ms ?? ""),
          env.HYDRA_DREAMINA_CDP_LAUNCH_TIMEOUT_MS,
          process.env.HYDRA_DREAMINA_CDP_LAUNCH_TIMEOUT_MS,
          "20000"
        ),
        10
      ) || 20_000
    ),
    submitUrlPattern: firstNonEmpty(
      normalizedBackend.submitUrlPattern,
      normalizedBackend.submit_url_pattern,
      env.HYDRA_DREAMINA_SUBMIT_URL_PATTERN,
      process.env.HYDRA_DREAMINA_SUBMIT_URL_PATTERN,
      ""
    ),
    captureTimeoutMs: Math.max(
      1_000,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.captureTimeoutMs ?? normalizedBackend.capture_timeout_ms ?? ""),
          env.HYDRA_DREAMINA_CAPTURE_TIMEOUT_MS,
          process.env.HYDRA_DREAMINA_CAPTURE_TIMEOUT_MS,
          "120000"
        ),
        10
      ) || 120_000
    ),
    templatePath: firstNonEmpty(
      normalizedBackend.templatePath,
      normalizedBackend.template_path,
      env.HYDRA_DREAMINA_CAPTURE_PATH,
      process.env.HYDRA_DREAMINA_CAPTURE_PATH,
      resolvePath(process.cwd(), ".hydra-host-dev", "dreamina-generate-template.json")
    ),
    promptFieldPath: firstNonEmpty(
      normalizedBackend.promptFieldPath,
      normalizedBackend.prompt_field_path,
      env.HYDRA_DREAMINA_PROMPT_FIELD_PATH,
      process.env.HYDRA_DREAMINA_PROMPT_FIELD_PATH,
      ""
    ),
    modelFieldPath: firstNonEmpty(
      normalizedBackend.modelFieldPath,
      normalizedBackend.model_field_path,
      env.HYDRA_DREAMINA_MODEL_FIELD_PATH,
      process.env.HYDRA_DREAMINA_MODEL_FIELD_PATH,
      ""
    ),
    resolutionFieldPath: firstNonEmpty(
      normalizedBackend.resolutionFieldPath,
      normalizedBackend.resolution_field_path,
      env.HYDRA_DREAMINA_RESOLUTION_FIELD_PATH,
      process.env.HYDRA_DREAMINA_RESOLUTION_FIELD_PATH,
      ""
    ),
    ratioFieldPath: firstNonEmpty(
      normalizedBackend.ratioFieldPath,
      normalizedBackend.ratio_field_path,
      env.HYDRA_DREAMINA_RATIO_FIELD_PATH,
      process.env.HYDRA_DREAMINA_RATIO_FIELD_PATH,
      ""
    ),
    candidateSelectionPolicy: normalizeDreaminaCandidateSelectionPolicy(
      firstNonEmpty(
        env.HYDRA_DREAMINA_CANDIDATE_SELECTION,
        process.env.HYDRA_DREAMINA_CANDIDATE_SELECTION,
        normalizedBackend.candidateSelectionPolicy,
        normalizedBackend.candidate_selection_policy,
        "first"
      )
    ),
    requestedModelVersion,
    requestedResolutionType,
    modelVersion: resolveDreaminaKnownModelReqKey(requestedModelVersion),
    resolutionType: normalizeDreaminaResolutionType(requestedResolutionType),
    submitTimeoutMs: Math.max(
      5_000,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.submitTimeoutMs ?? normalizedBackend.submit_timeout_ms ?? ""),
          env.HYDRA_DREAMINA_SUBMIT_TIMEOUT_MS,
          process.env.HYDRA_DREAMINA_SUBMIT_TIMEOUT_MS,
          "60000"
        ),
        10
      ) || 60_000
    ),
    pollIntervalMs: Math.max(
      1_000,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.pollIntervalMs ?? normalizedBackend.poll_interval_ms ?? ""),
          env.HYDRA_DREAMINA_POLL_INTERVAL_MS,
          process.env.HYDRA_DREAMINA_POLL_INTERVAL_MS,
          "5000"
        ),
        10
      ) || 5_000
    ),
    pollTimeoutMs: Math.max(
      5_000,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.pollTimeoutMs ?? normalizedBackend.poll_timeout_ms ?? ""),
          env.HYDRA_DREAMINA_POLL_TIMEOUT_MS,
          process.env.HYDRA_DREAMINA_POLL_TIMEOUT_MS,
          "300000"
        ),
        10
      ) || 300_000
    ),
    minSubmitIntervalMs: Math.max(
      0,
      Number.parseInt(
        firstNonEmpty(
          String(normalizedBackend.minSubmitIntervalMs ?? normalizedBackend.min_submit_interval_ms ?? ""),
          env.HYDRA_DREAMINA_MIN_SUBMIT_INTERVAL_MS,
          process.env.HYDRA_DREAMINA_MIN_SUBMIT_INTERVAL_MS,
          "45000"
        ),
        10
      ) || 45_000
    ),
    submitStatePath: firstNonEmpty(
      env.HYDRA_DREAMINA_SUBMIT_STATE_PATH,
      process.env.HYDRA_DREAMINA_SUBMIT_STATE_PATH,
      normalizedBackend.submitStatePath,
      normalizedBackend.submit_state_path,
      ""
    ),
    captureOnly: parseBooleanish(
      firstNonEmpty(
        env.HYDRA_DREAMINA_CAPTURE_ONLY,
        process.env.HYDRA_DREAMINA_CAPTURE_ONLY,
        ""
      ),
      false
    ),
    httpReplayEnabled: parseBooleanish(
      firstNonEmpty(
        env.HYDRA_DREAMINA_HTTP_REPLAY_ENABLED,
        process.env.HYDRA_DREAMINA_HTTP_REPLAY_ENABLED,
        "true"
      ),
      true
    )
  };
}

async function fetchJson(url = "") {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`dreamina_cdp_http_failed:${response.status}`);
  }
  return response.json();
}

async function isDreaminaCdpReady(baseUrl = "") {
  const normalizedBaseUrl = normalizeText(baseUrl).replace(/\/+$/u, "");
  if (!normalizedBaseUrl) {
    return false;
  }
  try {
    const response = await fetch(`${normalizedBaseUrl}/json/version`);
    return response.ok;
  } catch {
    return false;
  }
}

function resolveDreaminaCdpPort(baseUrl = "") {
  try {
    const parsed = new URL(normalizeText(baseUrl));
    return String(Number(parsed.port || 80) || 9222);
  } catch {
    return "9222";
  }
}

function resolveDreaminaBrowserExecutable(explicitPath = "") {
  const normalizedExplicitPath = normalizeText(explicitPath);
  if (normalizedExplicitPath) {
    return normalizedExplicitPath;
  }
  const candidates = [
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
  ];
  return firstNonEmpty(...candidates);
}

async function ensureDreaminaCdpReady(config = {}) {
  if (normalizeText(config.cdpWebSocketUrl)) {
    return { launchedBrowser: false, browserPid: null };
  }
  const baseUrl = normalizeText(config.cdpBaseUrl);
  if (await isDreaminaCdpReady(baseUrl)) {
    return { launchedBrowser: false, browserPid: null };
  }
  if (config.cdpAutoLaunch !== true) {
    throw new Error("dreamina_cdp_unavailable_and_auto_launch_disabled");
  }
  const executablePath = resolveDreaminaBrowserExecutable(config.cdpExecutablePath);
  if (!executablePath) {
    throw new Error("dreamina_cdp_executable_missing");
  }
  const userDataDir =
    config.cdpHeadless === true
      ? firstNonEmpty(config.cdpHeadlessUserDataDir, config.cdpUserDataDir)
      : normalizeText(config.cdpUserDataDir);
  const launchArgs = [
    `--remote-debugging-port=${resolveDreaminaCdpPort(baseUrl)}`,
    `--user-data-dir=${userDataDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,OptimizationHints,MediaRouter",
    "--disable-background-networking",
    "--disable-sync",
    "--hide-crash-restore-bubble",
    "--remote-allow-origins=*",
    "about:blank"
  ];
  if (config.cdpHeadless === true) {
    launchArgs.unshift("--headless=new");
  }
  const child = spawn(executablePath, launchArgs, {
    detached: true,
    stdio: "ignore",
    windowsHide: true
  });
  child.unref();
  const deadline = Date.now() + Math.max(1_000, Number(config.cdpLaunchTimeoutMs) || 20_000);
  while (Date.now() < deadline) {
    if (await isDreaminaCdpReady(baseUrl)) {
      return {
        launchedBrowser: true,
        browserPid: Number(child.pid || 0) || null
      };
    }
    await sleep(500);
  }
  throw new Error("dreamina_cdp_auto_launch_timeout");
}

async function createDreaminaPageTarget(config = {}) {
  const baseUrl = normalizeText(config.cdpBaseUrl).replace(/\/+$/u, "");
  const targetPageUrl = normalizeText(config.cdpTargetPageUrl);
  if (!baseUrl || !targetPageUrl) {
    throw new Error("dreamina_cdp_target_page_url_missing");
  }
  const response = await fetch(`${baseUrl}/json/new?${encodeURIComponent(targetPageUrl)}`, {
    method: "PUT"
  });
  if (!response.ok) {
    throw new Error(`dreamina_cdp_target_create_failed:${response.status}`);
  }
  const payload = normalizeObject(await response.json().catch(() => ({})));
  return {
    type: "page",
    url: firstNonEmpty(payload.url, targetPageUrl),
    id: firstNonEmpty(payload.id, payload.targetId),
    webSocketDebuggerUrl: firstNonEmpty(
      payload.webSocketDebuggerUrl,
      payload.webSocketDebuggerURL
    ),
    createdByHydra: true
  };
}

async function closeDreaminaPageTarget(config = {}, targetId = "") {
  const baseUrl = normalizeText(config.cdpBaseUrl).replace(/\/+$/u, "");
  const normalizedTargetId = normalizeText(targetId);
  if (!baseUrl || !normalizedTargetId) {
    return;
  }
  await fetch(`${baseUrl}/json/close/${normalizedTargetId}`).catch(() => {});
}

async function closeDreaminaBrowserProcess(browserPid = null) {
  const pid = Number(browserPid || 0) || 0;
  if (!pid) {
    return;
  }
  try {
    if (typeof process.kill === "function") {
      process.kill(pid);
      return;
    }
  } catch {}
  await new Promise((resolve) => {
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      detached: true,
      stdio: "ignore",
      windowsHide: true
    });
    killer.on("error", () => resolve());
    killer.on("close", () => resolve());
    killer.unref();
  });
}

export async function shutdownDreaminaCdpEndpoint(baseUrl = "") {
  const normalizedBaseUrl = normalizeText(baseUrl).replace(/\/+$/u, "");
  if (!normalizedBaseUrl) {
    return false;
  }
  const versionPayload = normalizeObject(
    await fetchJson(`${normalizedBaseUrl}/json/version`).catch(() => ({}))
  );
  const browserWebSocketUrl = firstNonEmpty(
    versionPayload.webSocketDebuggerUrl,
    versionPayload.webSocketDebuggerURL
  );
  if (!browserWebSocketUrl) {
    return false;
  }
  const session = new CdpSession(browserWebSocketUrl);
  await session.connect();
  try {
    await session.send("Browser.close");
    return true;
  } finally {
    await session.close().catch(() => {});
  }
}

async function resolveDreaminaPageTarget(config = {}) {
  const cdpRuntime = await ensureDreaminaCdpReady(config);
  const baseUrl = normalizeText(config.cdpBaseUrl).replace(/\/+$/u, "");
  const explicitWebSocketUrl = normalizeText(config.cdpWebSocketUrl);
  if (explicitWebSocketUrl) {
    return {
      target: {
        type: "page",
        url: firstNonEmpty(normalizeText(config.pageUrlPattern), "dreamina_explicit_target")
      },
      webSocketUrl: explicitWebSocketUrl,
      runtime: {
        ...cdpRuntime,
        createdTargetId: null
      }
    };
  }
  if (config.cdpForceCreateTarget === true) {
    const createdTarget = await createDreaminaPageTarget(config);
    const webSocketUrl = firstNonEmpty(
      createdTarget.webSocketDebuggerUrl,
      createdTarget.webSocketDebuggerURL
    );
    if (!webSocketUrl) {
      throw new Error("dreamina_cdp_page_websocket_missing");
    }
    return {
      target: createdTarget,
      webSocketUrl,
      runtime: {
        ...cdpRuntime,
        createdTargetId: firstNonEmpty(createdTarget.id)
      }
    };
  }
  const list = normalizeList(await fetchJson(`${baseUrl}/json/list`));
  const pagePattern = normalizeText(config.pageUrlPattern);
  const target =
    list.find(
      (entry) =>
        normalizeText(entry.type) === "page" &&
        (!pagePattern || normalizeText(entry.url).includes(pagePattern))
    ) ??
    null;
  const resolvedTarget =
    target ??
    (await createDreaminaPageTarget(config).catch(() => null)) ??
    list.find((entry) => normalizeText(entry.type) === "page");
  if (!resolvedTarget) {
    throw new Error("dreamina_cdp_page_target_missing");
  }
  const webSocketUrl = firstNonEmpty(
    resolvedTarget.webSocketDebuggerUrl,
    resolvedTarget.webSocketDebuggerURL
  );
  if (!webSocketUrl) {
    throw new Error("dreamina_cdp_page_websocket_missing");
  }
  return {
    target: resolvedTarget,
    webSocketUrl,
    runtime: {
      ...cdpRuntime,
      createdTargetId: firstNonEmpty(
        resolvedTarget.createdByHydra === true ? resolvedTarget.id : "",
        ""
      )
    }
  };
}

function readNestedValue(target = {}, path = "") {
  const segments = normalizeText(path)
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (segments.length === 0) {
    return undefined;
  }
  let cursor = target;
  for (const segment of segments) {
    if (!cursor || typeof cursor !== "object" || !Object.prototype.hasOwnProperty.call(cursor, segment)) {
      return undefined;
    }
    cursor = cursor[segment];
  }
  return cursor;
}

function setNestedValue(target = {}, path = "", value) {
  const segments = normalizeText(path)
    .split(".")
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (segments.length === 0) {
    return false;
  }
  let cursor = target;
  for (let index = 0; index < segments.length - 1; index += 1) {
    const segment = segments[index];
    if (!cursor[segment] || typeof cursor[segment] !== "object" || Array.isArray(cursor[segment])) {
      cursor[segment] = {};
    }
    cursor = cursor[segment];
  }
  cursor[segments.at(-1)] = value;
  return true;
}

function setFirstMatchingKey(target, keys = [], value) {
  const normalizedTarget = normalizeObject(target);
  for (const [key, entry] of Object.entries(normalizedTarget)) {
    if (keys.includes(key)) {
      normalizedTarget[key] = value;
      return true;
    }
    if (entry && typeof entry === "object" && !Array.isArray(entry)) {
      if (setFirstMatchingKey(entry, keys, value)) {
        return true;
      }
    }
  }
  return false;
}

function patchDreaminaGenerateBodyJson(
  bodyJson = {},
  {
    prompt = "",
    modelVersion = "",
    resolutionType = "",
    ratio = ""
  } = {}
) {
  const normalizedBody = cloneJson(normalizeObject(bodyJson));
  const updated = [];
  const promptValue = normalizeText(prompt);
  const modelValue = normalizeText(modelVersion);
  const resolutionValue = normalizeText(resolutionType);
  const ratioValue = normalizeText(ratio);

  const draftContent = safeJsonParse(normalizedBody.draft_content, {});
  const component = normalizeList(draftContent.component_list)[0];
  const coreParam = normalizeObject(
    normalizeObject(
      normalizeObject(component).abilities
    ).generate
  ).core_param;
  const largeImageInfo = normalizeObject(normalizeObject(coreParam).large_image_info);

  if (promptValue && coreParam && typeof coreParam === "object") {
    coreParam.prompt = promptValue;
    updated.push("draft_content.prompt");
  }
  if (modelValue && coreParam && typeof coreParam === "object") {
    coreParam.model = modelValue;
    normalizeObject(normalizedBody.extend).root_model = modelValue;
    updated.push("draft_content.model");
    updated.push("extend.root_model");
  }
  if (resolutionValue && largeImageInfo && typeof largeImageInfo === "object") {
    largeImageInfo.resolution_type = resolutionValue;
    updated.push("draft_content.large_image_info.resolution_type");
  }
  if (ratioValue && coreParam && typeof coreParam === "object") {
    const ratioMap = {
      "1:1": { width: 2048, height: 2048, image_ratio: 1 },
      "3:4": { width: 1728, height: 2304, image_ratio: 2 },
      "16:9": { width: 2560, height: 1440, image_ratio: 3 },
      "4:3": { width: 2304, height: 1728, image_ratio: 4 },
      "9:16": { width: 1440, height: 2560, image_ratio: 5 },
      "2:3": { width: 1664, height: 2496, image_ratio: 6 },
      "3:2": { width: 2496, height: 1664, image_ratio: 7 },
      "21:9": { width: 3024, height: 1296, image_ratio: 8 }
    };
    const ratioPayload = ratioMap[ratioValue];
    if (ratioPayload) {
      largeImageInfo.width = ratioPayload.width;
      largeImageInfo.height = ratioPayload.height;
      coreParam.image_ratio = ratioPayload.image_ratio;
      updated.push("draft_content.large_image_info.width");
      updated.push("draft_content.large_image_info.height");
      updated.push("draft_content.image_ratio");
    }
  }
  if (Object.keys(draftContent).length > 0) {
    normalizedBody.draft_content = JSON.stringify(draftContent);
  }

  const metricsExtra = safeJsonParse(normalizedBody.metrics_extra, {});
  if (promptValue && metricsExtra) {
    metricsExtra.generateId = firstNonEmpty(normalizeObject(normalizedBody).submit_id, metricsExtra.generateId);
    updated.push("metrics_extra.generateId");
  }
  if (resolutionValue && metricsExtra) {
    const rawSceneOptions = safeJsonParse(metricsExtra.sceneOptions, []);
    if (Array.isArray(rawSceneOptions)) {
      for (const sceneOption of rawSceneOptions) {
        if (sceneOption && typeof sceneOption === "object") {
          sceneOption.resolutionType = resolutionValue;
          if (modelValue) {
            sceneOption.modelReqKey = modelValue;
          }
        }
      }
      metricsExtra.sceneOptions = JSON.stringify(rawSceneOptions);
      updated.push("metrics_extra.sceneOptions");
    }
  }
  if (Object.keys(metricsExtra).length > 0) {
    normalizedBody.metrics_extra = JSON.stringify(metricsExtra);
  }

  return {
    payload: normalizedBody,
    updated: Array.from(new Set(updated))
  };
}

export function patchDreaminaTemplatePayload(
  templatePayload = {},
  {
    prompt = "",
    modelVersion = "",
    resolutionType = "",
    ratio = "",
    config = {}
  } = {}
) {
  const normalizedPayload = cloneJson(normalizeObject(templatePayload));
  if (
    normalizeText(normalizedPayload.submit_id) &&
    normalizeText(normalizedPayload.draft_content) &&
    normalizeText(normalizedPayload.metrics_extra)
  ) {
    return patchDreaminaGenerateBodyJson(normalizedPayload, {
      prompt,
      modelVersion,
      resolutionType,
      ratio
    });
  }
  const updated = [];
  const promptValue = normalizeText(prompt);
  const modelValue = normalizeText(modelVersion);
  const resolutionValue = normalizeText(resolutionType);
  const ratioValue = normalizeText(ratio);

  const patchers = [
    {
      label: "prompt",
      value: promptValue,
      path: normalizeText(config.promptFieldPath),
      keys: ["prompt", "text", "input", "content", "description"]
    },
    {
      label: "model_version",
      value: modelValue,
      path: normalizeText(config.modelFieldPath),
      keys: ["model_version", "modelVersion", "model", "model_req_key", "modelReqKey"]
    },
    {
      label: "resolution_type",
      value: resolutionValue,
      path: normalizeText(config.resolutionFieldPath),
      keys: ["resolution_type", "resolutionType", "resolution", "size"]
    },
    {
      label: "ratio",
      value: ratioValue,
      path: normalizeText(config.ratioFieldPath),
      keys: ["ratio", "aspect_ratio", "aspectRatio"]
    }
  ];

  for (const patcher of patchers) {
    if (!patcher.value) {
      continue;
    }
    let applied = false;
    if (patcher.path) {
      applied = setNestedValue(normalizedPayload, patcher.path, patcher.value);
    } else {
      applied = setFirstMatchingKey(normalizedPayload, patcher.keys, patcher.value);
    }
    if (applied) {
      updated.push(patcher.label);
    }
  }

  return {
    payload: normalizedPayload,
    updated
  };
}

function filterReplayHeaders(headers = {}) {
  const normalized = {};
  for (const [key, value] of Object.entries(normalizeObject(headers))) {
    const normalizedKey = normalizeText(key);
    if (!normalizedKey) {
      continue;
    }
    if (
      [
        "host",
        "content-length",
        "accept-encoding",
        "connection",
        "origin",
        "referer",
        "cookie"
      ].includes(normalizedKey.toLowerCase())
    ) {
      continue;
    }
    normalized[normalizedKey] = value;
  }
  normalized["content-type"] = firstNonEmpty(
    normalized["content-type"],
    normalized["Content-Type"],
    "application/json"
  );
  return normalized;
}

function buildDreaminaCookieHeader(cookies = []) {
  return normalizeList(cookies)
    .map((entry) => {
      const normalized = normalizeObject(entry);
      const name = normalizeText(normalized.name);
      const value = String(normalized.value ?? "");
      return name ? `${name}=${value}` : "";
    })
    .filter(Boolean)
    .join("; ");
}

function patchDreaminaMetricsExtraSubmitId(metricsExtra = "", submitId = "") {
  const normalizedSubmitId = normalizeText(submitId);
  const parsed = safeJsonParse(metricsExtra, null);
  if (!parsed || typeof parsed !== "object" || !normalizedSubmitId) {
    return normalizeText(metricsExtra);
  }
  return JSON.stringify({
    ...parsed,
    generateId: normalizedSubmitId
  });
}

export function buildDreaminaHttpReplayTemplate(
  template = {},
  {
    prompt = "",
    modelVersion = "",
    resolutionType = "",
    ratio = "",
    submitId = ""
  } = {}
) {
  const normalizedTemplate = cloneJson(normalizeObject(template));
  const normalizedSubmitId = firstNonEmpty(submitId, randomUUID());
  const sourcePayload =
    safeJsonParse(normalizedTemplate.bodyJson, null) ??
    safeJsonParse(normalizedTemplate.postData, null) ??
    {};
  const patched = patchDreaminaTemplatePayload(sourcePayload, {
    prompt,
    modelVersion,
    resolutionType,
    ratio,
    config: {}
  });
  patched.payload.submit_id = normalizedSubmitId;
  if (normalizeText(patched.payload.metrics_extra)) {
    patched.payload.metrics_extra = patchDreaminaMetricsExtraSubmitId(
      patched.payload.metrics_extra,
      normalizedSubmitId
    );
  }
  return {
    template: {
      ...normalizedTemplate,
      bodyJson: patched.payload,
      postData: JSON.stringify(patched.payload)
    },
    submitId: normalizedSubmitId,
    templatePatchSummary: Array.from(
      new Set([...normalizeList(patched.updated), "submit_id", "metrics_extra.generateId"])
    )
  };
}

function extractImageUrlFromResponse(value) {
  if (typeof value === "string") {
    if (/^https?:\/\/.+\.(?:png|jpg|jpeg|webp)(?:\?.*)?$/iu.test(value)) {
      return value;
    }
    return "";
  }
  if (Array.isArray(value)) {
    for (const entry of value) {
      const found = extractImageUrlFromResponse(entry);
      if (found) {
        return found;
      }
    }
    return "";
  }
  if (value && typeof value === "object") {
    for (const [key, entry] of Object.entries(value)) {
      if (/url|image|img|src/iu.test(key)) {
        const found = extractImageUrlFromResponse(entry);
        if (found) {
          return found;
        }
      }
    }
    for (const entry of Object.values(value)) {
      const found = extractImageUrlFromResponse(entry);
      if (found) {
        return found;
      }
    }
  }
  return "";
}

function buildReplayExpression({ url = "", method = "POST", headers = {}, bodyText = "" } = {}) {
  return `(() => {
    const requestUrl = ${JSON.stringify(url)};
    const requestMethod = ${JSON.stringify(method)};
    const requestHeaders = ${JSON.stringify(headers)};
    const requestBody = ${JSON.stringify(bodyText)};
    return fetch(requestUrl, {
      method: requestMethod,
      headers: requestHeaders,
      body: requestBody,
      credentials: "include"
    }).then(async (response) => {
      const rawText = await response.text();
      let json = null;
      try {
        json = JSON.parse(rawText);
      } catch {}
      return {
        ok: response.ok,
        status: response.status,
        url: response.url,
        headers: Object.fromEntries(response.headers.entries()),
        bodyText: rawText,
        bodyJson: json
      };
    });
  })()`;
}

function buildPageValueExpression(expressionBody = "") {
  return `(() => {
    ${expressionBody}
  })()`;
}

async function evaluateValue(session, expression = "", extraParams = {}) {
  const response = await session.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    ...extraParams
  });
  return normalizeObject(response.result).value;
}

async function readDreaminaPageSnapshot(session) {
  return normalizeObject(
    await evaluateValue(
      session,
      buildPageValueExpression(`
        return {
          title: document.title,
          url: location.href,
          readyState: document.readyState
        };
      `)
    ).catch(() => ({}))
  );
}

async function ensureDreaminaTargetPage(session, config = {}, timeoutMs = 15_000) {
  const targetPageUrl = normalizeText(config.cdpTargetPageUrl);
  const pagePattern = normalizeText(config.pageUrlPattern);
  if (!targetPageUrl && !pagePattern) {
    return readDreaminaPageSnapshot(session);
  }
  const deadline = Date.now() + Math.max(1_000, Number(timeoutMs) || 15_000);
  let navigated = false;
  let lastSnapshot = {};
  while (Date.now() < deadline) {
    const snapshot = await readDreaminaPageSnapshot(session);
    lastSnapshot = snapshot;
    const currentUrl = normalizeText(snapshot.url);
    const patternMatched = pagePattern ? currentUrl.includes(pagePattern) : currentUrl === targetPageUrl;
    if (patternMatched) {
      return {
        ...snapshot,
        navigated
      };
    }
    if (!navigated && targetPageUrl) {
      await session.send("Page.navigate", {
        url: targetPageUrl
      }).catch(() => {});
      navigated = true;
    }
    await sleep(500);
  }
  throw new Error(
    `dreamina_target_page_unavailable:${JSON.stringify({
      targetPageUrl,
      pagePattern,
      ...lastSnapshot
    })}`
  );
}

async function getDreaminaCookies(session, urls = []) {
  const response = await session.send("Network.getCookies", {
    urls: normalizeList(urls).filter(Boolean)
  });
  return normalizeList(response.cookies);
}

async function resolveDreaminaSourcePageTarget(config = {}) {
  const sourceBaseUrl = normalizeText(config.cdpCookieSourceBaseUrl).replace(/\/+$/u, "");
  if (!sourceBaseUrl || sourceBaseUrl === normalizeText(config.cdpBaseUrl).replace(/\/+$/u, "")) {
    return null;
  }
  const list = normalizeList(await fetchJson(`${sourceBaseUrl}/json/list`).catch(() => []));
  const pagePattern = normalizeText(config.pageUrlPattern);
  const target =
    list.find(
      (entry) =>
        normalizeText(entry.type) === "page" &&
        (!pagePattern || normalizeText(entry.url).includes(pagePattern))
    ) ?? list.find((entry) => normalizeText(entry.type) === "page");
  if (!target) {
    return null;
  }
  const webSocketUrl = firstNonEmpty(target.webSocketDebuggerUrl, target.webSocketDebuggerURL);
  return webSocketUrl ? { target, webSocketUrl } : null;
}

function buildDreaminaCookieSetPayload(cookies = []) {
  return normalizeList(cookies)
    .map((entry) => {
      const normalized = normalizeObject(entry);
      const name = normalizeText(normalized.name);
      const value = String(normalized.value ?? "");
      if (!name) {
        return null;
      }
      const payload = {
        name,
        value,
        domain: normalizeText(normalized.domain),
        path: firstNonEmpty(normalized.path, "/"),
        secure: normalized.secure === true,
        httpOnly: normalized.httpOnly === true
      };
      const sameSite = normalizeText(normalized.sameSite);
      if (sameSite) {
        payload.sameSite = sameSite;
      }
      if (normalized.session !== true && Number.isFinite(Number(normalized.expires))) {
        payload.expires = Number(normalized.expires);
      }
      return payload;
    })
    .filter(Boolean);
}

async function hydrateDreaminaCookiesFromSource(targetSession, config = {}) {
  const sourceResolved = await resolveDreaminaSourcePageTarget(config);
  if (!sourceResolved) {
    return {
      hydrated: false,
      reason: "dreamina_cookie_source_unavailable"
    };
  }
  const sourceSession = new CdpSession(sourceResolved.webSocketUrl);
  await sourceSession.connect();
  try {
    await sourceSession.send("Network.enable");
    const cookies = await getDreaminaCookies(sourceSession, [
      "https://jimeng.jianying.com/",
      normalizeText(config.cdpTargetPageUrl)
    ]);
    const cookiePayload = buildDreaminaCookieSetPayload(cookies);
    if (cookiePayload.length === 0) {
      return {
        hydrated: false,
        reason: "dreamina_cookie_source_empty"
      };
    }
    await targetSession.send("Network.setCookies", {
      cookies: cookiePayload
    });
    await targetSession.send("Page.navigate", {
      url: normalizeText(config.cdpTargetPageUrl)
    }).catch(() => {});
    await sleep(2_000);
    return {
      hydrated: true,
      cookieCount: cookiePayload.length
    };
  } finally {
    await sourceSession.close().catch(() => {});
  }
}

async function resolveDreaminaFileInputNodeId(session) {
  await session.send("DOM.enable");
  const documentResult = await session.send("DOM.getDocument", {
    depth: -1,
    pierce: true
  });
  const rootNodeId = Number(normalizeObject(documentResult.root).nodeId || 0);
  if (!rootNodeId) {
    throw new Error("dreamina_dom_root_missing");
  }
  const queryResult = await session.send("DOM.querySelector", {
    nodeId: rootNodeId,
    selector: 'input[type="file"]'
  });
  const nodeId = Number(normalizeObject(queryResult).nodeId || 0);
  if (!nodeId) {
    throw new Error("dreamina_reference_file_input_missing");
  }
  return nodeId;
}

function buildPromptEditorPreparationExpression() {
  return buildPageValueExpression(`
    const candidates = Array.from(document.querySelectorAll('[contenteditable="true"]'));
    const editor = candidates.find((entry) => {
      if (!(entry instanceof HTMLElement)) {
        return false;
      }
      const text = String(entry.getAttribute("placeholder") || entry.getAttribute("data-placeholder") || entry.ariaLabel || "");
      return /提示词|prompt|describe|输入/iu.test(text) || entry.innerText !== undefined;
    }) || candidates[0];
    if (!editor) {
      return { ok: false, reason: "prompt_editor_missing" };
    }
    editor.focus();
    editor.textContent = "";
    editor.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      inputType: "deleteContentBackward",
      data: ""
    }));
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    return { ok: true };
  `);
}

function buildUnicodeSafePromptInjectionExpression(promptBase64 = "") {
  return buildPageValueExpression(`
    const base64 = ${JSON.stringify(promptBase64)};
    const bytes = Uint8Array.from(atob(base64), (entry) => entry.charCodeAt(0));
    const text = new TextDecoder().decode(bytes);
    const candidates = Array.from(document.querySelectorAll('[contenteditable="true"]'));
    const editor = candidates.find((entry) => {
      if (!(entry instanceof HTMLElement)) {
        return false;
      }
      const label = String(
        entry.getAttribute("placeholder") ||
          entry.getAttribute("data-placeholder") ||
          entry.ariaLabel ||
          ""
      );
      return /提示词|prompt|describe|输入/iu.test(label) || entry.innerText !== undefined;
    }) || candidates[0];
    if (!editor) {
      return { ok: false, reason: "prompt_editor_missing" };
    }
    editor.focus();
    const selection = window.getSelection();
    if (selection) {
      const range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      selection.removeAllRanges();
      selection.addRange(range);
    }
    const inserted = typeof document.execCommand === "function"
      ? document.execCommand("insertText", false, text)
      : false;
    if (!inserted) {
      editor.textContent = text;
    }
    editor.dispatchEvent(new InputEvent("beforeinput", {
      bubbles: true,
      cancelable: true,
      data: text,
      inputType: "insertText"
    }));
    editor.dispatchEvent(new InputEvent("input", {
      bubbles: true,
      cancelable: true,
      data: text,
      inputType: "insertText"
    }));
    return {
      ok: true,
      text
    };
  `);
}

function buildReferenceImageClearExpression() {
  return buildPageValueExpression(`
    const removeButtons = Array.from(document.querySelectorAll('.remove-button-dY9tJN'));
    for (const button of removeButtons) {
      if (button instanceof HTMLElement) {
        button.click();
      }
    }
    return {
      removedCount: removeButtons.length
    };
  `);
}

function buildDreaminaAtMentionMenuOpenExpression() {
  return buildPageValueExpression(`
    const buttons = Array.from(document.querySelectorAll('button'));
    const iconButtons = buttons
      .filter((entry) => {
        if (!(entry instanceof HTMLElement)) {
          return false;
        }
        const rect = entry.getBoundingClientRect();
        const className = String(entry.className || "");
        return (
          /toolbar-button/iu.test(className) &&
          !/submit-button/iu.test(className) &&
          rect.width >= 30 &&
          rect.height >= 30
        );
      })
      .sort((left, right) => right.getBoundingClientRect().x - left.getBoundingClientRect().x);
    const atButton = iconButtons[0];
    if (!atButton) {
      return { ok: false, reason: "dreamina_at_button_missing" };
    }
    atButton.click();
    return { ok: true };
  `);
}

function buildDreaminaMentionAliasSelectionExpression(aliasBase64 = "") {
  return buildPageValueExpression(`
    const aliasBytes = Uint8Array.from(atob(${JSON.stringify(aliasBase64)}), (entry) => entry.charCodeAt(0));
    const alias = new TextDecoder().decode(aliasBytes);
    const normalize = (value) => String(value || "").trim().toLowerCase();
    const aliasNormalized = normalize(alias);
    const candidates = Array.from(document.querySelectorAll('body *'))
      .filter((entry) => {
        if (!(entry instanceof HTMLElement)) {
          return false;
        }
        const rect = entry.getBoundingClientRect();
        if (rect.width < 120 || rect.height < 20) {
          return false;
        }
        const text = String(entry.innerText || "").trim();
        const textNormalized = normalize(text);
        return (
          textNormalized === aliasNormalized ||
          textNormalized.includes(aliasNormalized) ||
          textNormalized.replace(/\\.[a-z0-9]+$/iu, "") === aliasNormalized
        );
      })
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        return leftRect.y - rightRect.y || leftRect.x - rightRect.x;
      });
    const target = candidates[0];
    if (!target) {
      return { ok: false, reason: "dreamina_reference_alias_missing", alias };
    }
    target.click();
    return { ok: true, alias };
  `);
}

function buildDreaminaMentionFirstSelectionExpression() {
  return buildPageValueExpression(`
    const candidates = Array.from(document.querySelectorAll('body *'))
      .filter((entry) => {
        if (!(entry instanceof HTMLElement)) {
          return false;
        }
        const rect = entry.getBoundingClientRect();
        if (rect.width < 120 || rect.height < 20) {
          return false;
        }
        const text = String(entry.innerText || "").trim();
        return Boolean(text) && !/^@$/u.test(text);
      })
      .sort((left, right) => {
        const leftRect = left.getBoundingClientRect();
        const rightRect = right.getBoundingClientRect();
        return leftRect.y - rightRect.y || leftRect.x - rightRect.x;
      });
    const target = candidates[0];
    if (!target) {
      return { ok: false, reason: "dreamina_reference_fallback_missing" };
    }
    target.click();
    return { ok: true, text: String(target.innerText || "").trim() };
  `);
}

function buildDreaminaRuntimeModelCatalogExpression() {
  return buildPageValueExpression(`
    const rawModelList =
      window.__image_generate_model_config__?.data?.model_list ||
      window.__debugger?.DreaminaCommercialFeatureService?._dreaminaModelConfigFeatureContainerService?._instance?._imageModelData?.data?.value?.modelList ||
      [];
    return rawModelList.map((item) => ({
      modelReqKey: item.model_req_key || item.modelReqKey || "",
      displayName:
        window.__lngResource?.[item.model_name_starling_key || item.modelNameStarlingKey] || "",
      modelSource:
        item.extra?.model_source ||
        item.extra?.modelSource ||
        item.extra?.raw_model_source ||
        item.extra?.rawModelSource ||
        ""
    }));
  `);
}

function buildDreaminaModelAliasCandidates(entry = {}) {
  const aliases = new Set();
  const normalizedEntry = normalizeObject(entry);
  const pushAlias = (value) => {
    const normalized = normalizeDreaminaModelSelector(value);
    if (normalized) {
      aliases.add(normalized);
    }
  };
  pushAlias(normalizedEntry.modelReqKey);
  pushAlias(normalizedEntry.displayName);
  pushAlias(normalizedEntry.modelSource);
  const displayName = normalizeText(normalizedEntry.displayName);
  const versionMatch = displayName.match(/(\d+\.\d+)/u);
  if (versionMatch?.[1]) {
    pushAlias(versionMatch[1]);
    pushAlias(`图片${versionMatch[1]}`);
  }
  if (/lite/iu.test(displayName) || /lite/iu.test(normalizeText(normalizedEntry.modelSource))) {
    if (versionMatch?.[1]) {
      pushAlias(`${versionMatch[1]}lite`);
      pushAlias(`图片${versionMatch[1]}lite`);
      pushAlias(`seedream${versionMatch[1]}lite`);
    }
  }
  return Array.from(aliases);
}

export function resolveDreaminaRequestedModelVersion({
  config = {},
  requestSpec = {},
  referenceImages = []
} = {}) {
  const explicitRequestedModelVersion = firstNonEmpty(
    config.requestedModelVersion,
    requestSpec.model,
    requestSpec.imageModel,
    requestSpec.modelVersion,
    requestSpec.model_version
  );
  if (isDreaminaModelSelector(explicitRequestedModelVersion)) {
    return explicitRequestedModelVersion;
  }
  return referenceImages.length > 0 ? "5.0" : "4.5";
}

async function resolveDreaminaRuntimeModelReqKey(session, requestedModelVersion = "") {
  const fallbackModelVersion = resolveDreaminaKnownModelReqKey(requestedModelVersion);
  try {
    const catalog = normalizeList(
      await evaluateValue(session, buildDreaminaRuntimeModelCatalogExpression())
    ).map((entry) => normalizeObject(entry));
    const requestedAlias = normalizeDreaminaModelSelector(requestedModelVersion);
    for (const entry of catalog) {
      const modelReqKey = normalizeText(entry.modelReqKey);
      if (!modelReqKey) {
        continue;
      }
      const aliases = buildDreaminaModelAliasCandidates(entry);
      if (
        aliases.includes(requestedAlias) ||
        aliases.includes(normalizeDreaminaModelSelector(fallbackModelVersion))
      ) {
        return {
          requestedModelVersion,
          resolvedModelVersion: modelReqKey,
          catalog
        };
      }
    }
    return {
      requestedModelVersion,
      resolvedModelVersion: fallbackModelVersion,
      catalog
    };
  } catch {
    return {
      requestedModelVersion,
      resolvedModelVersion: fallbackModelVersion,
      catalog: []
    };
  }
}

async function stageDreaminaReferenceImageSpecs(referenceImages = []) {
  const specs = normalizeDreaminaReferenceImageSpecs(referenceImages);
  if (specs.length === 0) {
    return [];
  }
  const stagingDir = resolvePath(process.cwd(), ".tmp", "dreamina-reference-aliases", randomUUID());
  await mkdir(stagingDir, { recursive: true });
  const staged = [];
  for (const entry of specs) {
    const sourcePath = normalizeText(entry.path);
    const alias = firstNonEmpty(entry.alias, normalizeReferenceAliasFromPath(sourcePath));
    if (!sourcePath) {
      continue;
    }
    const stagedPath = resolvePath(stagingDir, buildDreaminaSafeReferenceFilename(alias, sourcePath));
    await copyFile(sourcePath, stagedPath);
    staged.push({
      ...entry,
      alias,
      originalPath: sourcePath,
      path: stagedPath
    });
  }
  return staged;
}

async function uploadDreaminaReferenceImages(session, referenceImages = []) {
  const specs = await stageDreaminaReferenceImageSpecs(referenceImages);
  if (specs.length === 0) {
    return {
      uploaded: [],
      mentionAliases: []
    };
  }
  await evaluateValue(session, buildReferenceImageClearExpression());
  await sleep(800);
  const nodeId = await resolveDreaminaFileInputNodeId(session);
  await session.send("DOM.setFileInputFiles", {
    nodeId,
    files: specs.map((entry) => entry.path)
  });
  await sleep(4_000);
  return {
    uploaded: specs,
    mentionAliases: specs.map((entry) => entry.alias)
  };
}

async function bindDreaminaReferenceMentions(session, mentionAliases = []) {
  const aliases = normalizeList(mentionAliases).map((entry) => normalizeText(entry)).filter(Boolean);
  const bound = [];
  for (const alias of aliases) {
    let menuOpened = {};
    for (let attempt = 0; attempt < 10; attempt += 1) {
      menuOpened = normalizeObject(
        await evaluateValue(session, buildDreaminaAtMentionMenuOpenExpression())
      );
      if (menuOpened.ok === true) {
        break;
      }
      await sleep(500);
    }
    if (menuOpened.ok !== true) {
      throw new Error(firstNonEmpty(menuOpened.reason, "dreamina_at_menu_open_failed"));
    }
    await sleep(800);
    const selected = normalizeObject(
      await evaluateValue(
        session,
        buildDreaminaMentionAliasSelectionExpression(encodeUtf8Base64(alias))
      )
    );
    if (selected.ok !== true) {
      const fallbackSelected = normalizeObject(
        await evaluateValue(session, buildDreaminaMentionFirstSelectionExpression())
      );
      if (fallbackSelected.ok !== true) {
        throw new Error(
          firstNonEmpty(
            selected.reason,
            fallbackSelected.reason,
            "dreamina_reference_alias_selection_failed"
          )
        );
      }
      bound.push(alias);
      await sleep(300);
      continue;
    }
    bound.push(alias);
    await sleep(300);
  }
  return {
    boundAliases: bound
  };
}

function buildSubmitButtonStateExpression() {
  return buildPageValueExpression(`
    const scoreButton = (entry) => {
      if (!(entry instanceof HTMLElement)) {
        return -1;
      }
      const className = String(entry.className || "");
      const text = String(entry.innerText || "").trim();
      const rect = entry.getBoundingClientRect();
      if (rect.width < 32 || rect.height < 24) {
        return -1;
      }
      let score = 0;
      if (/submit-button/iu.test(className)) {
        score += 10;
      }
      if (/立即生成|开始生成|去生成|生成图片|生成/iu.test(text)) {
        score += 6;
      }
      if (rect.y > window.innerHeight * 0.45) {
        score += 2;
      }
      if (rect.x > window.innerWidth * 0.45) {
        score += 2;
      }
      return score;
    };
    const button = Array.from(document.querySelectorAll("button"))
      .map((entry) => ({ entry, score: scoreButton(entry) }))
      .filter((entry) => entry.score >= 6)
      .sort((left, right) => right.score - left.score)[0]?.entry || null;
    if (!button) {
      return { found: false, enabled: false };
    }
    return {
      found: true,
      enabled: button.disabled !== true,
      text: String(button.innerText || "").trim(),
      className: String(button.className || "")
    };
  `);
}

function buildSubmitClickExpression() {
  return buildPageValueExpression(`
    const scoreButton = (entry) => {
      if (!(entry instanceof HTMLElement) || entry.disabled === true) {
        return -1;
      }
      const className = String(entry.className || "");
      const text = String(entry.innerText || "").trim();
      const rect = entry.getBoundingClientRect();
      if (rect.width < 32 || rect.height < 24) {
        return -1;
      }
      let score = 0;
      if (/submit-button/iu.test(className)) {
        score += 10;
      }
      if (/立即生成|开始生成|去生成|生成图片|生成/iu.test(text)) {
        score += 6;
      }
      if (rect.y > window.innerHeight * 0.45) {
        score += 2;
      }
      if (rect.x > window.innerWidth * 0.45) {
        score += 2;
      }
      return score;
    };
    const button = Array.from(document.querySelectorAll("button"))
      .map((entry) => ({ entry, score: scoreButton(entry) }))
      .filter((entry) => entry.score >= 6)
      .sort((left, right) => right.score - left.score)[0]?.entry || null;
    if (!button) {
      return { ok: false, reason: "submit_button_unavailable" };
    }
    button.click();
    return {
      ok: true,
      text: String(button.innerText || "").trim(),
      className: String(button.className || "")
    };
  `);
}

async function waitForPromptSubmissionReady(session, timeoutMs = 30_000) {
  const deadline = Date.now() + Math.max(1_000, Number(timeoutMs) || 30_000);
  let lastState = {};
  while (Date.now() < deadline) {
    const state = normalizeObject(
      await evaluateValue(session, buildSubmitButtonStateExpression())
    );
    lastState = state;
    if (state.found === true && state.enabled === true) {
      return;
    }
    await sleep(250);
  }
  throw new Error(`dreamina_web_submit_button_timeout:${JSON.stringify(lastState)}`);
}

function resolveDreaminaSubmitStatePath(config = {}) {
  const explicit = normalizeText(config.submitStatePath);
  if (explicit) {
    return explicit;
  }
  const templatePath = normalizeText(config.templatePath);
  if (!templatePath) {
    return "";
  }
  return resolvePath(dirname(templatePath), "dreamina-submit-state.json");
}

async function readDreaminaSubmitState(path = "") {
  const resolvedPath = normalizeText(path);
  if (!resolvedPath) {
    return {};
  }
  const text = await readFile(resolvedPath, "utf8").catch(() => "");
  return safeJsonParse(text, {});
}

async function writeDreaminaSubmitState(path = "", state = {}) {
  const resolvedPath = normalizeText(path);
  if (!resolvedPath) {
    return;
  }
  await ensureParentDirectory(resolvedPath);
  await writeFile(resolvedPath, JSON.stringify(normalizeObject(state), null, 2), "utf8");
}

async function enforceDreaminaSubmitCooldown(config = {}) {
  const minSubmitIntervalMs = Math.max(0, Number(config.minSubmitIntervalMs) || 0);
  const submitStatePath = resolveDreaminaSubmitStatePath(config);
  if (!submitStatePath || minSubmitIntervalMs <= 0) {
    return {
      submitStatePath,
      waitedMs: 0
    };
  }
  const state = normalizeObject(await readDreaminaSubmitState(submitStatePath));
  const lastSubmittedAt = Number(state.last_submitted_at_ms ?? state.lastSubmittedAtMs) || 0;
  const now = Date.now();
  const waitRemainingMs = Math.max(0, lastSubmittedAt + minSubmitIntervalMs - now);
  if (waitRemainingMs > 0) {
    await sleep(waitRemainingMs);
  }
  return {
    submitStatePath,
    waitedMs: waitRemainingMs
  };
}

function extractSubmitIdFromPayload(payload = {}) {
  const normalized = normalizeObject(payload);
  return firstNonEmpty(
    normalized.submit_id,
    normalizeObject(normalized.task).submit_id,
    normalizeObject(normalized.data).submit_id,
    normalizeObject(normalized.data).submitId
  );
}

function buildDreaminaHistoryUrl(submitUrl = "") {
  const fallback =
    "https://jimeng.jianying.com/mweb/v1/get_history_by_ids?aid=513695&device_platform=web&region=cn";
  const normalizedSubmitUrl = normalizeText(submitUrl);
  if (!normalizedSubmitUrl) {
    return fallback;
  }
  try {
    const parsed = new URL(normalizedSubmitUrl);
    const nextUrl = new URL("/mweb/v1/get_history_by_ids", parsed.origin);
    for (const key of ["aid", "device_platform", "region"]) {
      const value = parsed.searchParams.get(key);
      if (value) {
        nextUrl.searchParams.set(key, value);
      }
    }
    if (!nextUrl.searchParams.get("aid")) {
      nextUrl.searchParams.set("aid", "513695");
    }
    if (!nextUrl.searchParams.get("device_platform")) {
      nextUrl.searchParams.set("device_platform", "web");
    }
    if (!nextUrl.searchParams.get("region")) {
      nextUrl.searchParams.set("region", "cn");
    }
    return nextUrl.toString();
  } catch {
    return fallback;
  }
}

function buildPageJsonFetchExpression({ url = "", method = "POST", body = {} } = {}) {
  return `(() => {
    return fetch(${JSON.stringify(url)}, {
      method: ${JSON.stringify(method)},
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(${JSON.stringify(body)}),
      credentials: "include"
    }).then(async (response) => {
      const rawText = await response.text();
      let json = null;
      try {
        json = JSON.parse(rawText);
      } catch {}
      return {
        ok: response.ok,
        status: response.status,
        url: response.url,
        bodyText: rawText,
        bodyJson: json
      };
    });
  })()`;
}

function extractDreaminaHistoryTask(historyEntry = {}) {
  const normalizedEntry = normalizeObject(historyEntry);
  return normalizeObject(
    normalizedEntry.task && typeof normalizedEntry.task === "object"
      ? normalizedEntry.task
      : normalizedEntry
  );
}

function extractDreaminaImageCandidates(historyEntry = {}) {
  const normalizedEntry = normalizeObject(historyEntry);
  const items = normalizeList(
    normalizedEntry.item_list ??
      normalizedEntry.itemList ??
      normalizeObject(normalizedEntry.data).item_list ??
      normalizeObject(normalizedEntry.data).itemList
  );
  const candidates = [];
  for (const item of items) {
    const normalizedItem = normalizeObject(item);
    const largeImages = normalizeList(
      normalizeObject(normalizedItem.image).large_images ??
        normalizeObject(normalizedItem.image).largeImages
    );
    const firstLargeImage = normalizeObject(largeImages[0]);
    const imageUrl = firstNonEmpty(
      firstLargeImage.image_url,
      firstLargeImage.imageUrl,
      normalizeObject(normalizedItem.common_attr).cover_url,
      normalizeObject(normalizedItem.common_attr).coverUrl
    );
    if (!imageUrl) {
      continue;
    }
    candidates.push({
      candidateIndex: candidates.length,
      url: imageUrl,
      outputType: firstNonEmpty(normalizeObject(normalizedItem.image).format, "png"),
      width: Number(firstLargeImage.width || 0) || null,
      height: Number(firstLargeImage.height || 0) || null,
      item: normalizedItem
    });
  }
  return candidates;
}

function summarizeDreaminaDebugObject(value = {}) {
  const normalized = normalizeObject(value);
  const summary = {};
  for (const [key, entry] of Object.entries(normalized)) {
    if (entry == null) {
      continue;
    }
    if (typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean") {
      summary[key] = entry;
      continue;
    }
    if (Array.isArray(entry)) {
      summary[key] = `[array:${entry.length}]`;
      continue;
    }
    if (typeof entry === "object") {
      summary[key] = `[object:${Object.keys(entry).length}]`;
    }
  }
  return summary;
}

export function selectDreaminaImageCandidate(
  candidates = [],
  selectionPolicy = "first"
) {
  const normalizedCandidates = normalizeList(candidates)
    .map((entry, index) => ({
      candidateIndex: Number(normalizeObject(entry).candidateIndex ?? index) || 0,
      ...normalizeObject(entry)
    }))
    .filter((entry) => firstNonEmpty(entry.url));
  if (normalizedCandidates.length === 0) {
    return {
      selectionPolicy: normalizeDreaminaCandidateSelectionPolicy(selectionPolicy),
      selectedCandidate: null,
      selectedCandidateIndex: -1,
      candidates: []
    };
  }
  const normalizedPolicy = normalizeDreaminaCandidateSelectionPolicy(selectionPolicy);
  let selectedCandidate = normalizedCandidates[0];
  if (normalizedPolicy === "last") {
    selectedCandidate = normalizedCandidates.at(-1);
  } else if (normalizedPolicy === "largest_area") {
    selectedCandidate = normalizedCandidates.reduce((best, candidate) => {
      const bestArea = (Number(best.width || 0) || 0) * (Number(best.height || 0) || 0);
      const candidateArea =
        (Number(candidate.width || 0) || 0) * (Number(candidate.height || 0) || 0);
      return candidateArea > bestArea ? candidate : best;
    }, normalizedCandidates[0]);
  }
  const selectedCandidateIndex = Math.max(
    0,
    normalizedCandidates.findIndex(
      (candidate) => Number(candidate.candidateIndex) === Number(selectedCandidate.candidateIndex)
    )
  );
  const annotatedCandidates = normalizedCandidates.map((candidate, index) => ({
    ...candidate,
    candidateIndex: Number(candidate.candidateIndex ?? index) || 0,
    isSelected: index === selectedCandidateIndex
  }));
  return {
    selectionPolicy: normalizedPolicy,
    selectedCandidate: annotatedCandidates[selectedCandidateIndex],
    selectedCandidateIndex,
    candidates: annotatedCandidates
  };
}

export function isDreaminaTextGenerateTemplate(template = {}) {
  const normalizedTemplate = normalizeObject(template);
  const bodyJson = normalizeObject(normalizedTemplate.bodyJson);
  const directExtra = normalizeObject(bodyJson.extra);
  if (firstNonEmpty(directExtra.ai_feature) === "text_generate_image") {
    return true;
  }
  const draftContent = safeJsonParse(bodyJson.draft_content, null);
  const firstComponent = normalizeObject(normalizeList(normalizeObject(draftContent).component_list)[0]);
  const abilities = normalizeObject(firstComponent.abilities);
  if (abilities.generate && !abilities.blend) {
    return true;
  }
  const generateType = Number(
    bodyJson.generate_type ??
      normalizeObject(bodyJson.http_common_info).generate_type ??
      normalizeObject(bodyJson.aigc_image_params).generate_type
  );
  return generateType === 1;
}

async function submitPromptThroughDreaminaPage(session, prompt = "", config = {}, submitOptions = {}) {
  const promptValue = normalizeText(prompt);
  if (!promptValue) {
    throw new Error("dreamina_web_prompt_missing");
  }
  const referenceImages = normalizeDreaminaReferenceImageSpecs(submitOptions.referenceImages);
  const referenceMentions = normalizeList(submitOptions.referenceMentions)
    .map((entry) => normalizeText(entry))
    .filter(Boolean);
  const clearedReferences = normalizeObject(
    await evaluateValue(session, buildReferenceImageClearExpression())
  );
  await sleep(800);
  const prepareResult = normalizeObject(
    await evaluateValue(session, buildPromptEditorPreparationExpression())
  );
  if (prepareResult.ok !== true) {
    throw new Error(firstNonEmpty(prepareResult.reason, "dreamina_web_prompt_editor_missing"));
  }
  const injected = normalizeObject(
    await evaluateValue(
      session,
      buildUnicodeSafePromptInjectionExpression(encodeUtf8Base64(promptValue))
    )
  );
  if (injected.ok !== true || normalizeText(injected.text) !== promptValue) {
    throw new Error(
      firstNonEmpty(
        injected.reason,
        "dreamina_web_prompt_unicode_injection_failed"
      )
    );
  }
  let referenceMeta = {
    cleared: clearedReferences,
    uploaded: [],
    boundAliases: []
  };
  if (referenceImages.length > 0) {
    const uploaded = await uploadDreaminaReferenceImages(session, referenceImages);
    const mentionAliases =
      referenceMentions.length > 0 ? referenceMentions : normalizeList(uploaded.mentionAliases);
    const bound = await bindDreaminaReferenceMentions(session, mentionAliases);
    referenceMeta = {
      uploaded: uploaded.uploaded,
      boundAliases: bound.boundAliases
    };
  }
  await waitForPromptSubmissionReady(session, config.submitTimeoutMs);
  await session.send("Fetch.enable", {
    patterns: [
      {
        urlPattern: "*jimeng.jianying.com/mweb/v1/aigc_draft/generate*",
        requestStage: "Request"
      }
    ]
  });
  const requestEventPromise = session.waitForEvent((payload) => {
    if (payload.method !== "Fetch.requestPaused") {
      return false;
    }
    const request = normalizeObject(normalizeObject(payload.params).request);
    const requestUrl = normalizeText(request.url);
    return (
      /\/mweb\/v1\/aigc_draft\/generate/iu.test(requestUrl) &&
      normalizeText(request.method).toUpperCase() === "POST"
    );
  }, config.submitTimeoutMs);
  const clickResult = normalizeObject(
    await evaluateValue(session, buildSubmitClickExpression())
  );
  if (clickResult.ok !== true) {
    throw new Error(firstNonEmpty(clickResult.reason, "dreamina_web_submit_click_failed"));
  }
  try {
    const event = await requestEventPromise;
    const params = normalizeObject(event.params);
    const request = normalizeObject(params.request);
    const originalPostData = normalizeText(request.postData);
    const originalBodyJson = safeJsonParse(originalPostData, null);
    const patched = patchDreaminaTemplatePayload(originalBodyJson, {
      prompt: submitOptions.skipPromptPatch ? "" : promptValue,
      modelVersion: firstNonEmpty(submitOptions.modelVersion, config.modelVersion),
      resolutionType: firstNonEmpty(submitOptions.resolutionType, config.resolutionType),
      ratio: firstNonEmpty(submitOptions.ratio),
      config
    });
    const continuedBodyText =
      originalBodyJson && typeof originalBodyJson === "object"
        ? JSON.stringify(patched.payload)
        : originalPostData;
    await session.send("Fetch.continueRequest", {
      requestId: normalizeText(params.requestId),
      postData: Buffer.from(continuedBodyText, "utf8").toString("base64")
    });
    const template = {
      capturedAt: new Date().toISOString(),
      source: "dreamina_web_cdp",
      url: normalizeText(request.url),
      method: normalizeText(request.method).toUpperCase() || "POST",
      headers: normalizeObject(request.headers),
      postData: continuedBodyText,
      bodyJson:
        originalBodyJson && typeof originalBodyJson === "object"
          ? patched.payload
          : safeJsonParse(continuedBodyText, null),
      originalBodyJson,
      templatePatchSummary: patched.updated,
      referenceMeta
    };
    if (config.templatePath && referenceImages.length === 0) {
      await ensureParentDirectory(config.templatePath);
      await writeFile(config.templatePath, JSON.stringify(template, null, 2), "utf8");
    }
    return template;
  } finally {
    await session.send("Fetch.disable").catch(() => {});
  }
}

async function pollDreaminaHistoryResult(
  session,
  {
    historyUrl = "",
    submitId = "",
    pollIntervalMs = 5_000,
    pollTimeoutMs = 300_000,
    config = {}
  } = {}
) {
  const normalizedSubmitId = normalizeText(submitId);
  if (!normalizedSubmitId) {
    throw new Error("dreamina_web_submit_id_missing");
  }
  const deadline = Date.now() + Math.max(5_000, Number(pollTimeoutMs) || 300_000);
  let attempt = 0;
  while (Date.now() < deadline) {
    attempt += 1;
    const historyResponse = normalizeObject(
      await evaluateValue(
        session,
        buildPageJsonFetchExpression({
          url: historyUrl,
          method: "POST",
          body: {
            submit_ids: [normalizedSubmitId]
          }
        })
      )
    );
    if (historyResponse.ok !== true) {
      throw new Error(
        `dreamina_web_history_failed:${firstNonEmpty(String(historyResponse.status), "unknown")}`
      );
    }
    const historyBody = normalizeObject(historyResponse.bodyJson);
    if (firstNonEmpty(historyBody.ret) && historyBody.ret !== "0") {
      throw new Error(
        `dreamina_web_history_error:${firstNonEmpty(
          historyBody.errmsg,
          historyBody.ret,
          "unknown"
        )}`
      );
    }
    const historyEntry = normalizeObject(normalizeObject(historyBody.data)[normalizedSubmitId]);
    const task = extractDreaminaHistoryTask(historyEntry);
    const status = Number(task.status ?? historyEntry.status ?? 0) || 0;
    const candidates = extractDreaminaImageCandidates(historyEntry);
    logDreaminaStage(config, "history_poll_tick", {
      submitId: normalizedSubmitId,
      attempt,
      status,
      candidateCount: candidates.length,
      hasData: Object.keys(normalizeObject(historyBody.data)).length > 0,
      taskSummary: summarizeDreaminaDebugObject(task),
      entrySummary: summarizeDreaminaDebugObject(historyEntry)
    });
    if (status === 50 && candidates.length > 0) {
      return {
        historyBody,
        historyEntry,
        task,
        candidates
      };
    }
    if (status < 0) {
      throw new Error(`dreamina_web_generation_failed:${status}`);
    }
    await sleep(pollIntervalMs);
  }
  throw new Error("dreamina_web_history_timeout");
}

async function pollDreaminaHistoryResultViaHttp(
  {
    historyUrl = "",
    submitId = "",
    headers = {},
    pollIntervalMs = 5_000,
    pollTimeoutMs = 300_000
  } = {}
) {
  const normalizedSubmitId = normalizeText(submitId);
  if (!normalizedSubmitId) {
    throw new Error("dreamina_web_submit_id_missing");
  }
  const deadline = Date.now() + Math.max(5_000, Number(pollTimeoutMs) || 300_000);
  while (Date.now() < deadline) {
    const historyResponse = await fetch(historyUrl, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...normalizeObject(headers)
      },
      body: JSON.stringify({
        submit_ids: [normalizedSubmitId]
      })
    });
    const rawText = await historyResponse.text();
    const historyBody = normalizeObject(safeJsonParse(rawText, {}));
    if (!historyResponse.ok) {
      throw new Error(
        `dreamina_web_history_failed:${firstNonEmpty(String(historyResponse.status), "unknown")}`
      );
    }
    if (firstNonEmpty(historyBody.ret) && historyBody.ret !== "0") {
      throw new Error(
        `dreamina_web_history_error:${firstNonEmpty(
          historyBody.errmsg,
          historyBody.ret,
          "unknown"
        )}`
      );
    }
    const historyEntry = normalizeObject(normalizeObject(historyBody.data)[normalizedSubmitId]);
    const task = extractDreaminaHistoryTask(historyEntry);
    const status = Number(task.status ?? historyEntry.status ?? 0) || 0;
    const candidates = extractDreaminaImageCandidates(historyEntry);
    if (status === 50 && candidates.length > 0) {
      return {
        historyBody,
        historyEntry,
        task,
        candidates
      };
    }
    if (status < 0) {
      throw new Error(`dreamina_web_generation_failed:${status}`);
    }
    await sleep(pollIntervalMs);
  }
  throw new Error(`dreamina_web_history_timeout:${normalizedSubmitId}`);
}

async function submitDreaminaPromptViaHttpReplay(
  session,
  {
    prompt = "",
    modelVersion = "",
    resolutionType = "",
    ratio = "",
    config = {}
  } = {}
) {
  const templatePath = normalizeText(config.templatePath);
  if (!templatePath) {
    throw new Error("dreamina_http_replay_template_path_missing");
  }
  const template = safeJsonParse(await readFile(templatePath, "utf8"), null);
  if (!template || typeof template !== "object") {
    throw new Error("dreamina_http_replay_template_invalid");
  }
  if (!isDreaminaTextGenerateTemplate(template)) {
    throw new Error("dreamina_http_replay_template_incompatible");
  }
  const replayPlan = buildDreaminaHttpReplayTemplate(template, {
    prompt,
    modelVersion,
    resolutionType,
    ratio
  });
  const effectiveTemplate = replayPlan.template;
  const cookieHeader = buildDreaminaCookieHeader(
    await getDreaminaCookies(session, [
      firstNonEmpty(effectiveTemplate.url, "https://jimeng.jianying.com/"),
      "https://jimeng.jianying.com/",
      firstNonEmpty(
        normalizeObject(effectiveTemplate.headers).Referer,
        normalizeObject(effectiveTemplate.headers).referer,
        "https://jimeng.jianying.com/ai-tool/generate/?type=image"
      )
    ])
  );
  const submitHeaders = {
    ...filterReplayHeaders(effectiveTemplate.headers),
    cookie: cookieHeader
  };
  const submitResponse = await fetch(normalizeText(effectiveTemplate.url), {
    method: firstNonEmpty(effectiveTemplate.method, "POST"),
    headers: submitHeaders,
    body: normalizeText(effectiveTemplate.postData)
  });
  const submitBodyText = await submitResponse.text();
  const submitBodyJson = safeJsonParse(submitBodyText, null);
  if (!submitResponse.ok) {
    throw new Error(
      `dreamina_http_replay_submit_failed:${firstNonEmpty(String(submitResponse.status), "unknown")}`
    );
  }
  const historyUrl = buildDreaminaHistoryUrl(effectiveTemplate.url);
  const historyResult = await pollDreaminaHistoryResultViaHttp({
    historyUrl,
    submitId: replayPlan.submitId,
    headers: {
      cookie: cookieHeader,
      referer: firstNonEmpty(
        normalizeObject(effectiveTemplate.headers).Referer,
        normalizeObject(effectiveTemplate.headers).referer,
        "https://jimeng.jianying.com/ai-tool/generate/?type=image"
      )
    },
    pollIntervalMs: config.pollIntervalMs,
    pollTimeoutMs: config.pollTimeoutMs
  });
  return {
    submitId: replayPlan.submitId,
    historyUrl,
    submitResponse: {
      ok: submitResponse.ok,
      status: submitResponse.status,
      bodyText: submitBodyText,
      bodyJson: submitBodyJson
    },
    historyResult,
    templatePatchSummary: replayPlan.templatePatchSummary,
    templatePath,
    transport: "http_replay"
  };
}

export async function captureDreaminaRequestTemplate(config = {}) {
  const resolved = await resolveDreaminaPageTarget(config);
  const session = new CdpSession(resolved.webSocketUrl);
  await session.connect();
  try {
    await session.send("Network.enable");
    await session.send("Page.enable");
    if (normalizeObject(resolved.runtime).launchedBrowser === true || shouldHydrateDreaminaCookies(config)) {
      await hydrateDreaminaCookiesFromSource(session, config).catch(() => {});
    }
    await ensureDreaminaTargetPage(session, config, config.submitTimeoutMs).catch((error) => {
      throw error;
    });
    const submitPattern = normalizeText(config.submitUrlPattern);
    const event = await session.waitForEvent((payload) => {
      if (payload.method !== "Network.requestWillBeSent") {
        return false;
      }
      const request = normalizeObject(payload.params).request;
      const requestUrl = normalizeText(request.url);
      if (!requestUrl) {
        return false;
      }
      if (submitPattern && !requestUrl.includes(submitPattern)) {
        return false;
      }
      return (
        /jimeng\.jianying\.com|dreamina/iu.test(requestUrl) &&
        ["POST", "PUT"].includes(normalizeText(request.method).toUpperCase())
      );
    }, config.captureTimeoutMs);
    const request = normalizeObject(normalizeObject(event.params).request);
    const template = {
      capturedAt: new Date().toISOString(),
      source: "dreamina_web_cdp",
      pageUrl: normalizeText(resolved.target.url),
      url: normalizeText(request.url),
      method: normalizeText(request.method).toUpperCase() || "POST",
      headers: normalizeObject(request.headers),
      postData: normalizeText(request.postData),
      bodyJson: safeJsonParse(request.postData, null)
    };
    if (config.templatePath) {
      await ensureParentDirectory(config.templatePath);
      await writeFile(config.templatePath, JSON.stringify(template, null, 2), "utf8");
    }
    return template;
  } finally {
    await session.close().catch(() => {});
    await closeDreaminaPageTarget(
      config,
      normalizeObject(resolved.runtime).createdTargetId
    ).catch(() => {});
    if (
      normalizeObject(resolved.runtime).launchedBrowser === true &&
      config.cdpKeepAlive !== true
    ) {
      await closeDreaminaBrowserProcess(normalizeObject(resolved.runtime).browserPid).catch(() => {});
    }
  }
}

export async function requestDreaminaWebImageGeneration({
  env = {},
  config = {},
  requestSpec = {}
} = {}) {
  const resolvedConfig = resolveDreaminaWebImageGenerationConfig(env, config);
  logDreaminaStage(resolvedConfig, "request_start", {
    promptLength: String(
      decodeUtf8Base64(firstNonEmpty(requestSpec.prompt_base64, requestSpec.promptBase64)) ||
        firstNonEmpty(requestSpec.prompt, requestSpec.image_prompt_seed)
    ).length,
    ratio: firstNonEmpty(requestSpec.ratio),
    hasReferenceImages:
      normalizeDreaminaReferenceImageSpecs(
        firstNonEmpty(requestSpec.reference_images_json, requestSpec.referenceImagesJson)
          ? safeJsonParse(firstNonEmpty(requestSpec.reference_images_json, requestSpec.referenceImagesJson), [])
          : Array.isArray(requestSpec.referenceImages)
            ? requestSpec.referenceImages
            : Array.isArray(requestSpec.reference_images)
              ? requestSpec.reference_images
              : []
      ).length > 0
  });
  const cooldown = await enforceDreaminaSubmitCooldown(resolvedConfig);
  logDreaminaStage(resolvedConfig, "cooldown_complete", { waitedMs: cooldown.waitedMs });
  const submitStatePath = resolveDreaminaSubmitStatePath(resolvedConfig);
  const resolved = await resolveDreaminaPageTarget(resolvedConfig);
  logDreaminaStage(resolvedConfig, "page_target_resolved", {
    webSocketUrl: normalizeText(resolved.webSocketUrl),
    launchedBrowser: normalizeObject(resolved.runtime).launchedBrowser === true,
    browserPid: normalizeObject(resolved.runtime).browserPid
  });
  const session = new CdpSession(resolved.webSocketUrl);
  await session.connect();
  try {
    logDreaminaStage(resolvedConfig, "cdp_connected");
    await session.send("Network.enable");
    await session.send("Runtime.enable");
    await session.send("Page.enable").catch(() => {});
    if (normalizeObject(resolved.runtime).launchedBrowser === true || shouldHydrateDreaminaCookies(resolvedConfig)) {
      logDreaminaStage(resolvedConfig, "cookie_hydration_start");
      await hydrateDreaminaCookiesFromSource(session, resolvedConfig).catch(() => {});
      logDreaminaStage(resolvedConfig, "cookie_hydration_complete");
    }
    logDreaminaStage(resolvedConfig, "ensure_target_page_start");
    await ensureDreaminaTargetPage(session, resolvedConfig, resolvedConfig.submitTimeoutMs);
    logDreaminaStage(resolvedConfig, "ensure_target_page_complete");
    const prompt = firstNonEmpty(requestSpec.prompt, requestSpec.image_prompt_seed);
    const normalizedPrompt = decodeUtf8Base64(
      firstNonEmpty(requestSpec.prompt_base64, requestSpec.promptBase64)
    ) || prompt;
    const referenceImagesJson = firstNonEmpty(
      requestSpec.reference_images_json,
      requestSpec.referenceImagesJson
    );
    const referenceImagesSource = referenceImagesJson
      ? safeJsonParse(referenceImagesJson, [])
      : Array.isArray(requestSpec.referenceImages)
        ? requestSpec.referenceImages
        : Array.isArray(requestSpec.reference_images)
          ? requestSpec.reference_images
          : [];
    const referenceImages = normalizeDreaminaReferenceImageSpecs(referenceImagesSource);
    logDreaminaStage(resolvedConfig, "request_normalized", {
      referenceImageCount: referenceImages.length
    });
    const requestedModelVersion = resolveDreaminaRequestedModelVersion({
      config: resolvedConfig,
      requestSpec,
      referenceImages
    });
    let useHttpReplay =
      resolvedConfig.httpReplayEnabled &&
      referenceImages.length === 0 &&
      !resolvedConfig.captureOnly;
    let httpReplayFallbackReason = "";
    if (useHttpReplay) {
      try {
        const replayTemplate = safeJsonParse(
          await readFile(normalizeText(resolvedConfig.templatePath), "utf8"),
          null
        );
        useHttpReplay = isDreaminaTextGenerateTemplate(replayTemplate);
      } catch {
        useHttpReplay = false;
      }
    }
    const resolvedModel = useHttpReplay
      ? {
          resolvedModelVersion: resolveDreaminaKnownModelReqKey(requestedModelVersion),
          catalog: []
        }
      : await resolveDreaminaRuntimeModelReqKey(session, requestedModelVersion);
    const effectiveModelVersion = firstNonEmpty(
      resolvedModel.resolvedModelVersion,
      resolveDreaminaKnownModelReqKey(requestedModelVersion)
    );
    const effectiveResolutionType = normalizeDreaminaResolutionType(
      resolvedConfig.resolutionType
    );
    await writeDreaminaSubmitState(submitStatePath, {
      last_attempted_at_ms: Date.now(),
      last_model_version: effectiveModelVersion,
      last_resolution_type: effectiveResolutionType
    });
    logDreaminaStage(resolvedConfig, "submit_state_written", {
      effectiveModelVersion,
      effectiveResolutionType,
      useHttpReplay
    });
    if (useHttpReplay) {
      try {
        logDreaminaStage(resolvedConfig, "http_replay_submit_start");
        const replayed = await submitDreaminaPromptViaHttpReplay(session, {
          prompt: normalizedPrompt,
          modelVersion: effectiveModelVersion,
          resolutionType: effectiveResolutionType,
          ratio: firstNonEmpty(requestSpec.ratio),
          config: resolvedConfig
        });
        await writeDreaminaSubmitState(submitStatePath, {
          last_submitted_at_ms: Date.now(),
          last_submit_id: replayed.submitId,
          last_model_version: effectiveModelVersion,
          last_resolution_type: effectiveResolutionType
        });
        const candidateSelection = selectDreaminaImageCandidate(
          replayed.historyResult.candidates,
          resolvedConfig.candidateSelectionPolicy
        );
        logDreaminaStage(resolvedConfig, "http_replay_complete", {
          submitId: replayed.submitId,
          candidateCount: candidateSelection.candidates.length
        });
        const primaryCandidate = normalizeObject(candidateSelection.selectedCandidate);
        const imageUrl = firstNonEmpty(primaryCandidate.url);
        if (!imageUrl) {
          throw new Error("dreamina_web_image_url_missing");
        }
        return {
          result: {
            url: imageUrl,
            outputType: firstNonEmpty(primaryCandidate.outputType, "png"),
            selectedCandidateIndex: candidateSelection.selectedCandidateIndex,
            selected_candidate_index: candidateSelection.selectedCandidateIndex,
            selectedCandidate: primaryCandidate,
            selected_candidate: primaryCandidate,
            candidates: candidateSelection.candidates
          },
          revisedPrompt: "",
          generationStatus: "submitted_via_http_replay_and_polled",
          responseMeta: {
            submit_id: replayed.submitId,
            history_url: replayed.historyUrl,
            cooldown_waited_ms: cooldown.waitedMs,
            requested_model_version: requestedModelVersion,
            resolved_model_version: effectiveModelVersion,
            requested_resolution_type: resolvedConfig.requestedResolutionType,
            resolved_resolution_type: effectiveResolutionType,
            runtime_model_catalog: resolvedModel.catalog,
            transport: replayed.transport,
            submit_response: replayed.submitResponse,
            task: replayed.historyResult.task,
            candidate_selection_policy: candidateSelection.selectionPolicy,
            selected_candidate_index: candidateSelection.selectedCandidateIndex,
            selected_candidate: primaryCandidate,
            candidate_count: candidateSelection.candidates.length,
            candidates: candidateSelection.candidates
          },
          templatePatchSummary: normalizeList(replayed.templatePatchSummary)
        };
      } catch (error) {
        logDreaminaStage(resolvedConfig, "http_replay_failed", {
          message: normalizeText(error?.message)
        });
        if (!/^dreamina_web_history_timeout:/u.test(error?.message || "")) {
          throw error;
        }
        httpReplayFallbackReason = error?.message || "dreamina_web_history_timeout";
      }
    }
    logDreaminaStage(resolvedConfig, "page_submit_start", {
      referenceImageCount: referenceImages.length
    });
    const template = await submitPromptThroughDreaminaPage(
      session,
      normalizedPrompt,
      resolvedConfig,
      {
        modelVersion: effectiveModelVersion,
        resolutionType: effectiveResolutionType,
        ratio: firstNonEmpty(requestSpec.ratio),
        referenceImages,
        referenceMentions: referenceImages.map((entry) => entry.alias),
        skipPromptPatch: referenceImages.length > 0
      }
    );
    const bodyJson = normalizeObject(template.bodyJson);
    const patched = patchDreaminaTemplatePayload(bodyJson, {
      prompt: referenceImages.length > 0 ? "" : normalizedPrompt,
      modelVersion: effectiveModelVersion,
      resolutionType: effectiveResolutionType,
      ratio: firstNonEmpty(requestSpec.ratio),
      config: resolvedConfig
    });
    const submitId = firstNonEmpty(
      extractSubmitIdFromPayload(bodyJson),
      extractSubmitIdFromPayload(patched.payload)
    );
    logDreaminaStage(resolvedConfig, "page_submit_complete", {
      submitId,
      templateUrl: normalizeText(template.url)
    });
    if (resolvedConfig.captureOnly) {
      return {
        result: {
          template_path: normalizeText(resolvedConfig.templatePath),
          patched_body: patched.payload,
          submit_id: submitId,
          capture_only: true
        },
        revisedPrompt: "",
        generationStatus: "captured_via_page_submit",
        templatePatchSummary: Array.from(
          new Set([
            ...normalizeList(template.templatePatchSummary),
            ...normalizeList(patched.updated)
          ])
        )
      };
    }
    const historyUrl = buildDreaminaHistoryUrl(template.url);
    logDreaminaStage(resolvedConfig, "history_poll_start", {
      submitId,
      historyUrl
    });
    const historyResult = await pollDreaminaHistoryResult(session, {
      historyUrl,
      submitId,
      pollIntervalMs: resolvedConfig.pollIntervalMs,
      pollTimeoutMs: resolvedConfig.pollTimeoutMs,
      config: resolvedConfig
    });
    await writeDreaminaSubmitState(submitStatePath, {
      last_submitted_at_ms: Date.now(),
      last_submit_id: submitId,
      last_model_version: effectiveModelVersion,
      last_resolution_type: effectiveResolutionType
    });
    const candidateSelection = selectDreaminaImageCandidate(
      historyResult.candidates,
      resolvedConfig.candidateSelectionPolicy
    );
    logDreaminaStage(resolvedConfig, "history_poll_complete", {
      submitId,
      candidateCount: candidateSelection.candidates.length
    });
    const primaryCandidate = normalizeObject(candidateSelection.selectedCandidate);
    const imageUrl = firstNonEmpty(primaryCandidate.url);
    if (!imageUrl) {
      throw new Error("dreamina_web_image_url_missing");
    }
    return {
      result: {
        url: imageUrl,
        outputType: firstNonEmpty(primaryCandidate.outputType, "png"),
        selectedCandidateIndex: candidateSelection.selectedCandidateIndex,
        selected_candidate_index: candidateSelection.selectedCandidateIndex,
        selectedCandidate: primaryCandidate,
        selected_candidate: primaryCandidate,
        candidates: candidateSelection.candidates
      },
      revisedPrompt: "",
      generationStatus: "submitted_via_page_and_polled",
      responseMeta: {
        submit_id: submitId,
        history_url: historyUrl,
        cooldown_waited_ms: cooldown.waitedMs,
        requested_model_version: requestedModelVersion,
        resolved_model_version: effectiveModelVersion,
        requested_resolution_type: resolvedConfig.requestedResolutionType,
        resolved_resolution_type: effectiveResolutionType,
        runtime_model_catalog: resolvedModel.catalog,
        reference_images: template.referenceMeta,
        transport: httpReplayFallbackReason
          ? "cdp_page_submit_after_http_replay_timeout"
          : "cdp_page_submit",
        http_replay_fallback_reason: httpReplayFallbackReason || undefined,
        task: historyResult.task,
        candidate_selection_policy: candidateSelection.selectionPolicy,
        selected_candidate_index: candidateSelection.selectedCandidateIndex,
        selected_candidate: primaryCandidate,
        candidate_count: candidateSelection.candidates.length,
        candidates: candidateSelection.candidates
      },
      templatePatchSummary: Array.from(
        new Set([
          ...normalizeList(template.templatePatchSummary),
          ...normalizeList(patched.updated)
        ])
      )
    };
  } finally {
    await session.close().catch(() => {});
    await closeDreaminaPageTarget(
      resolvedConfig,
      normalizeObject(resolved.runtime).createdTargetId
    ).catch(() => {});
    if (
      normalizeObject(resolved.runtime).launchedBrowser === true &&
      resolvedConfig.cdpKeepAlive !== true
    ) {
      await closeDreaminaBrowserProcess(normalizeObject(resolved.runtime).browserPid).catch(() => {});
    }
  }
}
