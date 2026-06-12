const DEFAULT_SERVICE_BASE = "http://127.0.0.1:49310";
const STORAGE_KEYS = {
  clientId: "roughcut_publication_bridge_client_id",
  serviceBase: "roughcut_publication_bridge_service_base",
};
const BRIDGE_KEEPALIVE_ALARM = "roughcut_publication_bridge_keepalive";
const BRIDGE_AUTO_RELOAD_ALARM = "roughcut_publication_bridge_auto_reload";
const BRIDGE_POLL_TIMEOUT_MS = 1000;
const BRIDGE_IDLE_POLL_DELAY_MS = 750;
const BRIDGE_AUTO_RELOAD_DELAY_MINUTES = 0.5;
const BRIDGE_HTTP_TIMEOUT_MS = 8000;
const attachedTabs = new Set();
const eventSubscriptions = new Map();
let bridgeLoopStarted = false;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function getStorageValue(key, fallback = "") {
  const payload = await chrome.storage.local.get(key);
  return typeof payload[key] === "string" && payload[key].trim() ? payload[key].trim() : fallback;
}

async function ensureClientId() {
  let clientId = await getStorageValue(STORAGE_KEYS.clientId);
  if (!clientId) {
    clientId = crypto.randomUUID();
    await chrome.storage.local.set({ [STORAGE_KEYS.clientId]: clientId });
  }
  return clientId;
}

async function getServiceBase() {
  return await getStorageValue(STORAGE_KEYS.serviceBase, DEFAULT_SERVICE_BASE);
}

async function bridgeFetchJson(path, { method = "GET", body, timeoutMs = BRIDGE_HTTP_TIMEOUT_MS } = {}) {
  const serviceBase = await getServiceBase();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1000, Number(timeoutMs || BRIDGE_HTTP_TIMEOUT_MS)));
  try {
    const response = await fetch(`${serviceBase}${path}`, {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`bridge_http_${response.status}`);
    }
    return await response.json();
  } catch (error) {
    if (String(error?.name || "").trim() === "AbortError") {
      throw new Error(`bridge_http_timeout:${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function serializeTab(tab) {
  return {
    id: tab.id,
    title: tab.title || "",
    url: tab.url || "",
    active: tab.active === true,
  };
}

function originPattern(origin) {
  try {
    const parsed = new URL(String(origin || ""));
    return `${parsed.origin}/*`;
  } catch {
    return "";
  }
}

async function ensureDebuggerAttached(tabId) {
  if (attachedTabs.has(tabId)) return;
  try {
    await chrome.debugger.attach({ tabId }, "1.3");
  } catch (error) {
    const message = String(error?.message || error || "");
    if (!message.includes("Another debugger")) {
      throw error;
    }
  }
  attachedTabs.add(tabId);
}

async function postBridgeEvent(tabId, method, params) {
  const clientId = await ensureClientId();
  try {
    await bridgeFetchJson("/bridge/event", {
      method: "POST",
      body: {
        client_id: clientId,
        tab_id: tabId,
        method,
        params: params && typeof params === "object" ? params : {},
      },
    });
  } catch {}
}

function isSubscribedEvent(tabId, method) {
  const methods = eventSubscriptions.get(Number(tabId));
  return Boolean(methods && methods.has(String(method || "").trim()));
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  const tabId = Number(source?.tabId);
  if (!Number.isInteger(tabId) || tabId <= 0) return;
  if (!isSubscribedEvent(tabId, method)) return;
  postBridgeEvent(tabId, method, params).catch(() => {});
});

chrome.debugger.onDetach.addListener((source) => {
  const tabId = Number(source?.tabId);
  if (!Number.isInteger(tabId) || tabId <= 0) return;
  attachedTabs.delete(tabId);
});

async function handleBridgeCommand(command) {
  const type = String(command?.type || "").trim();
  const payload = command?.payload && typeof command.payload === "object" ? command.payload : {};
  switch (type) {
    case "list_tabs": {
      const tabs = await chrome.tabs.query({});
      return tabs.filter((tab) => Number.isInteger(tab.id)).map(serializeTab);
    }
    case "create_tab": {
      const tab = await chrome.tabs.create({ url: String(payload.url || "about:blank"), active: true });
      if (!Number.isInteger(tab.id)) throw new Error("created_tab_missing_id");
      return serializeTab(tab);
    }
    case "close_tab": {
      const tabId = Number(payload.tab_id);
      if (!Number.isInteger(tabId) || tabId <= 0) throw new Error("close_tab_id_invalid");
      await chrome.tabs.remove(tabId);
      attachedTabs.delete(tabId);
      eventSubscriptions.delete(tabId);
      return { closed: true, tab_id: tabId };
    }
    case "cdp_send": {
      const tabId = Number(payload.tab_id);
      const method = String(payload.method || "").trim();
      const params = payload.params && typeof payload.params === "object" ? payload.params : {};
      if (!Number.isInteger(tabId) || tabId <= 0) throw new Error("cdp_tab_id_invalid");
      if (!method) throw new Error("cdp_method_missing");
      await ensureDebuggerAttached(tabId);
      return await chrome.debugger.sendCommand({ tabId }, method, params);
    }
    case "set_origin_notification_permission": {
      const origin = String(payload.origin || "").trim();
      const pattern = originPattern(origin);
      const setting = String(payload.setting || "block").trim().toLowerCase() === "allow" ? "allow" : "block";
      if (!pattern) throw new Error("origin_pattern_invalid");
      await chrome.contentSettings.notifications.set({
        primaryPattern: pattern,
        setting,
      });
      return { handled: true, kind: "notification_permission", origin, setting };
    }
    case "subscribe_events": {
      const tabId = Number(payload.tab_id);
      const method = String(payload.method || "").trim();
      if (!Number.isInteger(tabId) || tabId <= 0) throw new Error("subscribe_tab_id_invalid");
      if (!method) throw new Error("subscribe_method_missing");
      await ensureDebuggerAttached(tabId);
      const methods = eventSubscriptions.get(tabId) || new Set();
      methods.add(method);
      eventSubscriptions.set(tabId, methods);
      return { subscribed: true, tab_id: tabId, method };
    }
    case "unsubscribe_events": {
      const tabId = Number(payload.tab_id);
      const method = String(payload.method || "").trim();
      const methods = eventSubscriptions.get(tabId);
      if (methods) {
        methods.delete(method);
        if (methods.size === 0) eventSubscriptions.delete(tabId);
      }
      return { unsubscribed: true, tab_id: tabId, method };
    }
    default:
      throw new Error(`bridge_command_unsupported:${type}`);
  }
}

async function postCommandResult(requestId, ok, resultOrError) {
  const clientId = await ensureClientId();
  const body = ok
    ? { client_id: clientId, request_id: requestId, ok: true, result: resultOrError }
    : { client_id: clientId, request_id: requestId, ok: false, error: String(resultOrError?.message || resultOrError || "bridge_command_failed") };
  await bridgeFetchJson("/bridge/result", { method: "POST", body });
}

async function sendHello() {
  const clientId = await ensureClientId();
  await bridgeFetchJson("/bridge/hello", {
    method: "POST",
    body: {
      client_id: clientId,
      extension_version: chrome.runtime.getManifest().version,
      capabilities: {
        debugger: true,
        tabs: true,
      },
    },
  });
  return clientId;
}

async function ensureBridgeKeepaliveAlarm() {
  try {
    await chrome.alarms.create(BRIDGE_KEEPALIVE_ALARM, {
      delayInMinutes: 0.5,
      periodInMinutes: 0.5,
    });
  } catch {}
}

async function ensureBridgeAutoReloadAlarm() {
  try {
    await chrome.alarms.create(BRIDGE_AUTO_RELOAD_ALARM, {
      delayInMinutes: BRIDGE_AUTO_RELOAD_DELAY_MINUTES,
      periodInMinutes: BRIDGE_AUTO_RELOAD_DELAY_MINUTES,
    });
  } catch {}
}

async function maybeAutoReloadBridge() {
  try {
    const devState = await bridgeFetchJson("/bridge/dev-state");
    const targetVersion = String(devState?.target_extension_version || "").trim();
    const currentVersion = String(chrome.runtime.getManifest().version || "").trim();
    if (targetVersion && currentVersion && targetVersion !== currentVersion) {
      chrome.runtime.reload();
    }
  } catch {}
}

async function pumpBridgeLoop() {
  if (bridgeLoopStarted) return;
  bridgeLoopStarted = true;
  while (true) {
    try {
      const clientId = await sendHello();
      const response = await bridgeFetchJson(
        `/bridge/next?client_id=${encodeURIComponent(clientId)}&timeout_ms=${BRIDGE_POLL_TIMEOUT_MS}`,
        { timeoutMs: BRIDGE_HTTP_TIMEOUT_MS },
      );
      const command = response?.command;
      if (!command || !command.request_id) {
        await sleep(BRIDGE_IDLE_POLL_DELAY_MS);
        continue;
      }
      try {
        const result = await handleBridgeCommand(command);
        await postCommandResult(command.request_id, true, result);
      } catch (error) {
        await postCommandResult(command.request_id, false, error);
      }
    } catch {
      await sleep(2000);
    }
  }
}

chrome.runtime.onInstalled.addListener(() => {
  ensureBridgeKeepaliveAlarm().catch(() => {});
  ensureBridgeAutoReloadAlarm().catch(() => {});
  pumpBridgeLoop().catch(() => {});
});

chrome.runtime.onStartup.addListener(() => {
  ensureBridgeKeepaliveAlarm().catch(() => {});
  ensureBridgeAutoReloadAlarm().catch(() => {});
  pumpBridgeLoop().catch(() => {});
});

chrome.alarms.onAlarm.addListener((alarm) => {
  const name = String(alarm?.name || "").trim();
  if (name === BRIDGE_KEEPALIVE_ALARM) {
    pumpBridgeLoop().catch(() => {});
    return;
  }
  if (name === BRIDGE_AUTO_RELOAD_ALARM) {
    maybeAutoReloadBridge().catch(() => {});
  }
});

ensureBridgeKeepaliveAlarm().catch(() => {});
ensureBridgeAutoReloadAlarm().catch(() => {});
maybeAutoReloadBridge().catch(() => {});
pumpBridgeLoop().catch(() => {});
