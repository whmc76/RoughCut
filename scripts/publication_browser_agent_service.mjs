import http from "node:http";
import { randomUUID } from "node:crypto";
import path from "node:path";

const CONTRACT = "browser_agent_publication_inventory_v1";
const TASK_CONTRACT = "browser_agent_publication_v1";
const PORT = Number(process.env.PUBLICATION_BROWSER_AGENT_PORT || 49310);
const HOST = String(process.env.PUBLICATION_BROWSER_AGENT_HOST || "0.0.0.0");
const CDP_URL = String(process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const LIVE_PUBLISH_ENABLED = /^(1|true|yes)$/i.test(String(process.env.PUBLICATION_LIVE_PUBLISH_ENABLED || ""));
const FINAL_PUBLISH_EXECUTOR_IMPLEMENTED = true;
const COMPOSITE_PUBLISH_PLATFORMS = new Set(["bilibili", "youtube", "xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"]);
const FINAL_PUBLISH_PLATFORMS = new Set([...COMPOSITE_PUBLISH_PLATFORMS]);
const TASKS = new Map();

const PLATFORM_DOMAINS = {
  douyin: ["creator.douyin.com", "creator-micro.douyin.com"],
  xiaohongshu: ["creator.xiaohongshu.com"],
  bilibili: ["member.bilibili.com", "member.bilibili.com/platform/upload"],
  kuaishou: ["cp.kuaishou.com", "cp.kuaishou.com/article/publish/video"],
  "wechat-channels": ["channels.weixin.qq.com"],
  toutiao: ["mp.toutiao.com/profile_v4/xigua/upload-video", "mp.toutiao.com/profile_v4/xigua/publish-video", "mp.toutiao.com"],
  youtube: ["studio.youtube.com"],
  x: ["x.com", "twitter.com"],
};

const PLATFORM_STEPS = {
  xiaohongshu: [
    "打开小红书创作服务平台发布笔记页",
    "上传视频和封面",
    "填写标题、正文、话题",
    "展开内容设置",
    "选择加入合集、原创声明、内容类型声明、群聊、地点/路线等可用选项",
    "设置定时或保存草稿，发布前再次验证控件",
  ],
  bilibili: [
    "打开 B站创作中心投稿页",
    "上传视频和封面",
    "填写标题、简介和标签",
    "选择分区，EDC/装备类优先从真实分区候选中评估户外潮流、数码、生活等选项",
    "选择合集/系列、声明与权益等更多设置",
    "设置定时或保存草稿，发布前再次验证控件",
  ],
  youtube: [
    "打开 YouTube Studio 上传或视频详情页",
    "上传视频和缩略图",
    "填写标题、说明、标签和播放列表",
    "确认是否面向儿童、可见性、评论限制和通知限制",
    "设置预约发布时间，发布前再次验证限制弹窗",
  ],
  douyin: [
    "打开抖音创作者中心发布视频页",
    "上传视频和封面",
    "填写标题/作品描述与话题",
    "选择合集、原创/声明、谁可以看、定时发布等真实可见选项",
    "发布前再次验证页面结构和字段变化",
  ],
};

const SAFE_DISMISS_TEXTS = [
  "知道了",
  "我知道了",
  "稍后再说",
  "暂不",
  "暂不开启",
  "以后再说",
  "屏蔽",
  "不允许",
  "拒绝",
  "关闭",
  "跳过",
  "Not now",
  "Maybe later",
  "Close",
  "Dismiss",
];

const DANGEROUS_ACTION_RE = /发布|投稿|提交|确定发布|立即投稿|发表|预定|预约发布|保存|删除|确认剪掉|Post$|Submit|Publish|Save|Delete/i;

const BILIBILI_SECTION_TERMS = [
  "影视",
  "娱乐",
  "音乐",
  "舞蹈",
  "动画",
  "绘画",
  "鬼畜",
  "游戏",
  "资讯",
  "知识",
  "人工智能",
  "科技数码",
  "汽车",
  "时尚美妆",
  "家装房产",
  "户外潮流",
  "健身",
  "体育运动",
  "手工",
  "美食",
  "小剧场",
  "旅游出行",
  "三农",
  "动物",
  "亲子",
  "健康",
  "情感",
  "vlog",
  "生活兴趣",
  "生活经验",
];

function jsonResponse(res, statusCode, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

function readRequestJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const text = Buffer.concat(chunks).toString("utf8").trim();
        resolve(text ? JSON.parse(text) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function listCdpTabs() {
  return fetchJson(`${CDP_URL}/json/list`);
}

function normalizePlatform(value) {
  const key = String(value || "").trim().toLowerCase().replace(/_/g, "-");
  if (key === "b站" || key === "bili") return "bilibili";
  if (key === "小红书" || key === "rednote") return "xiaohongshu";
  if (key === "视频号" || key === "wechat-channels") return "wechat-channels";
  return key;
}

function findPlatformTab(tabs, platform) {
  return findPlatformTabs(tabs, platform)[0];
}

function findPlatformTabs(tabs, platform) {
  const domains = PLATFORM_DOMAINS[platform] || [];
  return (tabs || [])
    .map((tab) => ({ tab, score: platformTabScore(tab, domains, platform) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score)
    .map((item) => item.tab);
}

function platformTabScore(tab, domains, platform = "") {
  let parsed;
  try {
    parsed = new URL(String(tab.url || ""));
  } catch {
    return 0;
  }
  const hostname = parsed.hostname.toLowerCase();
  const pathname = parsed.pathname.toLowerCase();
  let score = 0;
  for (const rawDomain of domains) {
    const normalized = String(rawDomain || "").toLowerCase();
    if (!normalized) continue;
    const slashIndex = normalized.indexOf("/");
    const domainHost = slashIndex >= 0 ? normalized.slice(0, slashIndex) : normalized;
    const domainPath = slashIndex >= 0 ? normalized.slice(slashIndex) : "";
    const hostMatches = hostname === domainHost || hostname.endsWith(`.${domainHost}`);
    if (!hostMatches) continue;
    const pathMatches = !domainPath || pathname.startsWith(domainPath);
    if (!pathMatches) continue;
    score = Math.max(score, 20 + (domainPath ? 10 : 0));
  }
  if (!score) return 0;
  if (tab.type === "page") score += 10;
  if (/upload|publish|post|article|studio|creator/.test(pathname)) score += 5;
  if (platform === "toutiao") {
    if (/\/profile_v4\/xigua\/upload-video/.test(pathname)) score += 80;
    if (/\/profile_v4\/xigua\/publish-video/.test(pathname)) score += 60;
    if (/\/graphic\/publish/.test(pathname)) score -= 80;
  }
  if (/iframe|worker|popup/i.test(String(tab.title || ""))) score -= 8;
  return score;
}

async function evaluatePage(tab, expression) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    const result = await client.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      timeout: 8000,
    });
    return result?.result?.value || {};
  } finally {
    client.close();
  }
}

async function evaluateWithClient(client, expression, timeout = 8000) {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
    timeout,
  });
  if (result?.exceptionDetails) {
    const detail = result.exceptionDetails.exception?.description || result.exceptionDetails.text || "Runtime.evaluate failed";
    throw new Error(detail);
  }
  return result?.result?.value || {};
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const { resolve, reject } = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) reject(new Error(message.error.message || "CDP error"));
      else resolve(message.result);
    });
    socket.addEventListener("close", () => {
      for (const { reject } of this.pending.values()) reject(new Error("CDP socket closed"));
      this.pending.clear();
    });
  }

  static connect(url) {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.addEventListener("open", () => resolve(new CdpClient(socket)), { once: true });
      socket.addEventListener("error", () => reject(new Error("CDP websocket connect failed")), { once: true });
    });
  }

  send(method, params = {}) {
    const id = this.nextId++;
    const payload = JSON.stringify({ id, method, params });
    return new Promise((resolve, reject) => {
      const timeoutMs = Math.max(5000, Number(params.timeout || 30000) + 5000);
      const timer = setTimeout(() => {
        if (!this.pending.has(id)) return;
        this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.socket.send(payload);
    });
  }

  close() {
    try {
      this.socket.close();
    } catch {
      // Nothing to clean up beyond the browser socket.
    }
  }
}

const PAGE_SNAPSHOT_EXPRESSION = `(() => {
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const visible = (el) => {
    const doc = el.ownerDocument || document;
    const win = doc.defaultView || window;
    const rect = el.getBoundingClientRect();
    const style = win.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const roots = [];
  const visitRoot = (root) => {
    if (!root || roots.includes(root)) return;
    roots.push(root);
    for (const el of [...root.querySelectorAll("*")]) {
      if (el.shadowRoot) visitRoot(el.shadowRoot);
      if (el.tagName === "IFRAME") {
        try {
          if (el.contentDocument) visitRoot(el.contentDocument);
        } catch {}
      }
    }
  };
  visitRoot(document);
  const queryAll = (selector) => roots.flatMap((root) => {
    try {
      return [...root.querySelectorAll(selector)];
    } catch {
      return [];
    }
  });
  const rawText = roots.map((root) => {
    const body = root.body || root.host || root.documentElement;
    return body ? String(body.innerText || body.textContent || "") : "";
  }).join("\\n");
  const elements = queryAll("button,input,textarea,select,label,[role=button],[role=checkbox],[role=switch],[role=combobox],[role=option],[role=menuitem],[aria-label],[class*=select],[class*=dropdown],[class*=option],[class*=menu],[class*=collection],[class*=playlist]")
    .filter(visible)
    .slice(0, 1200)
    .map((el) => ({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role") || "",
      className: clean(typeof el.className === "string" ? el.className : ""),
      type: el.getAttribute("type") || "",
      text: clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title")),
      ariaLabel: clean(el.getAttribute("aria-label")),
      placeholder: clean(el.getAttribute("placeholder")),
      checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
      disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
      options: el.tagName.toLowerCase() === "select" ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean) : [],
    }));
  const overlayTexts = queryAll("[role=dialog],[aria-modal=true],[role=listbox],[role=menu],[class*=modal i],[class*=dialog i],[class*=popover i],[class*=dropdown i],[class*=select i],[class*=menu i],[class*=overlay i],[class*=drawer i]")
    .filter(visible)
    .slice(0, 80)
    .map((el) => clean(el.innerText || el.textContent))
    .filter(Boolean);
  const headings = queryAll("h1,h2,h3,h4,[class*=title],[class*=label]")
    .filter(visible)
    .slice(0, 220)
    .map((el) => clean(el.innerText))
    .filter(Boolean);
  const lines = rawText.split(/[\\n\\r]+/)
    .flatMap((line) => String(line).split(/ {2,}/))
    .map((line) => clean(line))
    .filter(Boolean)
    .slice(0, 1800);
  const fileInputs = queryAll("input[type=file]").map((el, index) => ({
    index,
    accept: el.getAttribute("accept") || "",
    multiple: Boolean(el.multiple),
    visible: visible(el),
  }));
  return { url: location.href, title: document.title, lines, headings, elements, overlayTexts, fileInputs };
})()`;

async function pageSnapshot(client) {
  return evaluateWithClient(client, PAGE_SNAPSHOT_EXPRESSION, 12000);
}

async function ensurePlatformPublishRoute(client, tab, platform) {
  if (platform !== "toutiao") return { navigated: false, reason: "not_required" };
  const currentUrl = String(tab?.url || "");
  if (/mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/i.test(currentUrl)) {
    const current = await pageSnapshot(client).catch(() => ({}));
    const hasVideoInput = (current.fileInputs || []).some((input) => /video|mp4/i.test(input.accept || ""));
    return { navigated: false, reason: "already_video_publish_route", url: current.url || currentUrl, verified: hasVideoInput };
  }
  const targetUrl = "https://mp.toutiao.com/profile_v4/xigua/upload-video?index=0";
  await client.send("Page.enable").catch(() => {});
  await client.send("Page.navigate", { url: targetUrl });
  let current = null;
  const startedAt = Date.now();
  while (Date.now() - startedAt < 18000) {
    await sleep(1500);
    current = await pageSnapshot(client).catch(() => null);
    const url = String(current?.url || "");
    const text = [...(current?.lines || []), ...(current?.headings || [])].join(" ");
    const hasVideoInput = (current?.fileInputs || []).some((input) => /video|mp4/i.test(input.accept || ""));
    if (/mp\.toutiao\.com\/profile_v4\/xigua\/upload-video/i.test(url) && (hasVideoInput || /点击上传|发布视频/.test(text))) {
      return { navigated: true, from: currentUrl, to: targetUrl, url, verified: true };
    }
  }
  return { navigated: true, from: currentUrl, to: targetUrl, url: current?.url || "", verified: false, reason: "toutiao_video_publish_route_not_verified" };
}

async function snapshotTab(tab) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    return await pageSnapshot(client);
  } finally {
    client.close();
  }
}

function originFromUrl(url) {
  try {
    const parsed = new URL(String(url || ""));
    return parsed.origin;
  } catch {
    return "";
  }
}

async function setOriginNotificationPermission(client, tab) {
  const origin = originFromUrl(tab?.url);
  if (!origin) return { handled: false, reason: "missing_origin" };
  try {
    await client.send("Browser.setPermission", {
      permission: { name: "notifications" },
      setting: "denied",
      origin,
    });
    return { handled: true, kind: "notification_permission", origin, setting: "denied" };
  } catch (error) {
    return { handled: false, kind: "notification_permission", origin, reason: error.message };
  }
}

async function dismissInterruptions(client, tab, platform, stage = "unspecified") {
  const actions = [];
  const permission = await setOriginNotificationPermission(client, tab);
  if (permission.handled) actions.push({ ...permission, stage });

  const expression = `(() => {
    const safeTexts = ${JSON.stringify(SAFE_DISMISS_TEXTS)};
    const dangerousPattern = ${DANGEROUS_ACTION_RE.toString()};
    const platform = ${JSON.stringify(platform)};
    const stage = ${JSON.stringify(stage)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity || 1) !== 0;
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const overlays = queryAll([
      "[role=dialog]",
      "[aria-modal=true]",
      ".modal",
      ".dialog",
      ".popover",
      ".drawer",
      ".mask",
      ".toast",
      ".survey",
      "[class*=modal i]",
      "[class*=dialog i]",
      "[class*=popover i]",
      "[class*=mask i]",
      "[class*=survey i]",
      "[class*=notice i]",
      "[class*=tooltip i]",
      "[class*=guide i]",
      "[class*=alert i]",
    ].join(",")).filter(visible);
    const overlaySet = new Set(overlays);
    const isInsideOverlay = (el) => overlays.some((overlay) => overlay === el || overlay.contains(el));
    const labelOf = (el) => clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("placeholder"));
    const classOf = (el) => clean(el.className && typeof el.className === "string" ? el.className : "");
    const looksLikeCloseIcon = (el, label) => {
      const cls = classOf(el).toLowerCase();
      const aria = clean(el.getAttribute("aria-label")).toLowerCase();
      const title = clean(el.getAttribute("title")).toLowerCase();
      return ["×", "x", "X", "✕", "关闭"].includes(label) || /close|cancel|dismiss/.test(cls) || /close|关闭|dismiss|cancel/.test(aria) || /close|关闭|dismiss|cancel/.test(title);
    };
    const isSafeLabel = (label) => {
      if (!label || label.length > 80) return false;
      if (dangerousPattern.test(label)) return false;
      return safeTexts.some((text) => label === text || label.startsWith(text) || label.includes(text));
    };
    const clickableSelector = "button,[role=button],a,input[type=button],input[type=submit],[aria-label],[title],[class*=close i],[class*=cancel i],[class*=dismiss i]";
    const candidates = queryAll(clickableSelector)
      .filter(visible)
      .filter((el) => overlaySet.has(el) || isInsideOverlay(el))
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const label = labelOf(el);
        return { el, label, area: rect.width * rect.height };
      })
      .filter((item) => item.area > 0 && item.area < 180000)
      .sort((left, right) => {
        const leftClose = looksLikeCloseIcon(left.el, left.label) ? 0 : 1;
        const rightClose = looksLikeCloseIcon(right.el, right.label) ? 0 : 1;
        return leftClose - rightClose || left.area - right.area;
      });
    const clicked = [];
    for (const item of candidates) {
      const label = item.label;
      if (!isSafeLabel(label) && !looksLikeCloseIcon(item.el, label)) continue;
      if (dangerousPattern.test(label)) continue;
      item.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = item.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
        item.el.dispatchEvent(new MouseEvent(type, eventInit));
      }
      clicked.push({
        kind: "dom_popup_dismissed",
        label: label || clean(item.el.getAttribute("aria-label")) || clean(item.el.getAttribute("title")) || "icon_close",
        platform,
        stage,
      });
      break;
    }
    return { clicked };
  })()`;
  const domResult = await evaluateWithClient(client, expression, 10000);
  actions.push(...(domResult.clicked || []));
  return actions;
}

function mergedSnapshot(snapshots) {
  const lines = [];
  const headings = [];
  const elements = [];
  const fileInputs = [];
  const seenLines = new Set();
  const seenHeadings = new Set();
  const seenElements = new Set();
  for (const snapshot of snapshots.filter(Boolean)) {
    for (const line of snapshot.lines || []) {
      const text = String(line || "").trim();
      const key = text.toLowerCase();
      if (!text || seenLines.has(key)) continue;
      seenLines.add(key);
      lines.push(text);
    }
    for (const heading of snapshot.headings || []) {
      const text = String(heading || "").trim();
      const key = text.toLowerCase();
      if (!text || seenHeadings.has(key)) continue;
      seenHeadings.add(key);
      headings.push(text);
    }
    for (const element of snapshot.elements || []) {
      const text = `${element.tag}|${element.role}|${element.type}|${element.text}|${element.ariaLabel}|${element.placeholder}`;
      const key = text.toLowerCase();
      if (seenElements.has(key)) continue;
      seenElements.add(key);
      elements.push(element);
    }
    for (const overlayText of snapshot.overlayTexts || []) {
      const text = String(overlayText || "").trim();
      for (const line of text.split(/[\n\r]+/).flatMap((line) => String(line).split(/ {2,}/))) {
        const normalized = line.trim();
        const key = normalized.toLowerCase();
        if (!normalized || seenLines.has(key)) continue;
        seenLines.add(key);
        lines.push(normalized);
      }
    }
    for (const input of snapshot.fileInputs || []) fileInputs.push(input);
  }
  const last = snapshots.filter(Boolean).at(-1) || {};
  return {
    url: last.url,
    title: last.title,
    lines: lines.slice(0, 2200),
    headings: headings.slice(0, 260),
    elements: elements.slice(0, 900),
    fileInputs,
  };
}

function pageAlreadyHasMedia(snapshot, mediaPath) {
  const name = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  if (!name) return false;
  const stem = name.replace(/\.[^.]+$/, "");
  const text = [...(snapshot.lines || []), ...((snapshot.elements || []).map((element) => element.text || ""))].join(" ");
  if (/上传失败|Upload failed|重新上传/.test(text)) return false;
  return text.includes(name) || text.includes(stem);
}

async function pageAlreadyHasMediaLive(client, mediaPath) {
  const name = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  if (!name) return { present: false, reason: "missing_media_name" };
  const stem = name.replace(/\.[^.]+$/, "");
  return evaluateWithClient(client, `(() => {
    const expected = ${JSON.stringify({ name, stem })};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const text = clean(document.body.innerText || "");
    const failed = /上传失败|Upload failed|刷新后重试|网络异常/.test(text);
    const present = !failed && (text.includes(expected.name) || text.includes(expected.stem));
    return { present, failed, name: expected.name, upload_busy: /上传中|正在上传|视频处理中|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%/.test(text) };
  })()`, 10000);
}

async function clickByText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const candidates = roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll("button,[role=button],a,input[type=button],input[type=submit],label,[class*=button],[class*=select],[class*=dropdown],[class*=option],[class*=radio],[class*=checkbox],.collection-plugin-button,.group-card-select,.season-enter,.selector-container,.select-controller,ytcp-dropdown-trigger")];
      } catch {
        return [];
      }
    }).filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title") || el.getAttribute("placeholder"));
      return { el, label, area: rect.width * rect.height };
    }).filter((item) => item.label && item.label.length <= 220 && item.area < 280000);
    for (const text of texts) {
      const exact = candidates.find((item) => item.label === text);
      const starts = candidates.find((item) => item.label.startsWith(text));
      const contains = candidates.find((item) => item.label.includes(text));
      const item = exact || starts || contains;
      if (item) {
        item.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = item.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          item.el.dispatchEvent(new MouseEvent(type, eventInit));
        }
        return { clicked: true, text, label: item.label };
      }
    }
    return { clicked: false };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickLooseText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const candidates = [...document.querySelectorAll("button,[role=button],li,span,div,p,a,label,[class*=option],[class*=item],[class*=select],[class*=collection]")]
      .filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        const text = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
        const clickable = Boolean(el.closest("[role=dialog],[class*=modal],[class*=popover],[class*=dropdown],[class*=select],[class*=collection]")) || ["BUTTON", "A", "LABEL", "LI"].includes(el.tagName) || el.getAttribute("role") === "button";
        return { el, text, area: rect.width * rect.height, clickable };
      })
      .filter((item) => item.text && item.text.length <= 160 && item.area > 0 && item.area < 180000);
    for (const text of texts) {
      const item = candidates
        .filter((candidate) => candidate.text === text || candidate.text.includes(text))
        .sort((left, right) => Number(right.clickable) - Number(left.clickable) || left.area - right.area)[0];
      if (!item) continue;
      item.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = item.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) item.el.dispatchEvent(new MouseEvent(type, eventInit));
      return { clicked: true, text, label: item.text, loose: true };
    }
    return { clicked: false, loose: true, candidates: candidates.slice(0, 20).map((item) => item.text) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickFinalPublishByText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const selector = "button,[role=button],input[type=button],input[type=submit],.submit-add,.submit-btn,.submit-button,[class*=submit],[class*=publish]";
    const candidates = roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    }).filter(visible).map((el) => {
      const rect = el.getBoundingClientRect();
      const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title"));
      const className = clean(typeof el.className === "string" ? el.className : "");
      const inFooter = Boolean(el.closest(".submit-container,.submit-wrp,.footer,.bcc-dialog__footer,[class*=footer],[class*=submit]"));
      return { el, label, className, area: rect.width * rect.height, y: rect.top, inFooter };
    }).filter((item) => item.label && item.label.length <= 80 && item.area < 120000);
    const score = (item, text) => {
      let value = 0;
      if (item.label === text) value += 20;
      else if (item.label.includes(text)) value += 12;
      if (item.inFooter) value += 5;
      if (/submit|publish|投稿|发布/.test(item.className)) value += 3;
      if (/预览|取消|返回|删除|保存草稿/.test(item.label)) value -= 30;
      return value;
    };
    for (const text of texts) {
      const chosen = candidates
        .map((item) => ({ item, score: score(item, text) }))
        .filter((entry) => entry.score > 0)
        .sort((left, right) => right.score - left.score || right.item.y - left.item.y)[0]?.item;
      if (chosen) {
        chosen.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = chosen.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
          chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
        }
        return { clicked: true, text, label: chosen.label, className: chosen.className };
      }
    }
    return { clicked: false, candidates: candidates.slice(0, 20).map((item) => ({ label: item.label, className: item.className, inFooter: item.inFooter })) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickPlatformFinalPublish(client, platform, texts) {
  if (platform === "kuaishou") {
    const target = await evaluateWithClient(client, `(async () => {
      await new Promise((resolve) => {
        window.scrollTo({ top: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSchedule = Boolean(el.closest("._publish-time_171ix_401,.ant-picker,.ant-radio-wrapper,[class*=publish-time],[class*=time]"));
          const inPreview = Boolean(el.closest("[class*=preview]"));
          return { el, label, className, area: rect.width * rect.height, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, top: rect.top, inSchedule, inPreview };
        })
        .filter((item) => item.label && item.label.length <= 20 && item.area > 0 && item.area < 60000 && !item.inSchedule && !item.inPreview && !/取消|预览|定时|立即发布|发布时间/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布")
        .sort((left, right) => right.top - left.top || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { found: false, platform: "kuaishou", candidates: candidates.slice(0, 30).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      return { found: true, platform: "kuaishou", text: "发布", label: chosen.label, className: chosen.className, x: chosen.x, y: chosen.y };
    })()`, 10000);
    if (!target?.found) return { clicked: false, ...target };
    await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    return { clicked: true, platform: "kuaishou", text: target.text, label: target.label, className: target.className };
    const expression = `(async () => {
      await new Promise((resolve) => {
        window.scrollTo({ top: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSchedule = Boolean(el.closest("._publish-time_171ix_401,.ant-picker,.ant-radio-wrapper,[class*=publish-time],[class*=time]"));
          const inPreview = Boolean(el.closest("[class*=preview]"));
          return { el, label, className, area: rect.width * rect.height, x: rect.left, y: rect.top, inSchedule, inPreview };
        })
        .filter((item) => item.label && item.label.length <= 20 && item.area > 0 && item.area < 60000 && !item.inSchedule && !item.inPreview && !/取消|预览|定时|立即发布|发布时间/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布")
        .sort((left, right) => right.y - left.y || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { clicked: false, platform: "kuaishou", candidates: candidates.slice(0, 30).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      chosen.el.scrollIntoView({ block: "center", inline: "center" });
      const rect = chosen.el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
      return { clicked: true, platform: "kuaishou", text: "发布", label: chosen.label, className: chosen.className };
    })()`;
    return evaluateWithClient(client, expression, 10000);
  }
  if (platform === "xiaohongshu") {
    await clearXiaohongshuStaleCoverLayers(client).catch(() => {});
    const target = await evaluateWithClient(client, `(async () => {
      const platform = ${JSON.stringify(platform)};
      await new Promise((resolve) => {
        window.scrollTo({ top: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight), behavior: "instant" });
        setTimeout(resolve, 600);
      });
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const host = document.querySelector("xhs-publish-btn[submit-disabled='false']");
      if (host && visible(host)) {
        const rect = host.getBoundingClientRect();
        return {
          found: true,
          platform,
          text: host.getAttribute("submit-text") || "发布",
          label: host.getAttribute("submit-text") || "发布",
          className: "xhs-publish-btn",
          x: rect.left + rect.width * 0.74,
          y: rect.top + rect.height * 0.5,
        };
      }
      const candidates = [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          const inSettings = Boolean(el.closest(".publish-page-content-settings,.post-time-wrapper"));
          const inSidebar = Boolean(el.closest(".menu-container,.menu-panel"));
          const position = getComputedStyle(el).position;
          return { el, label, className, area: rect.width * rect.height, x: rect.left, y: rect.top, inSettings, inSidebar, position };
        })
        .filter((item) => item.label && item.label.length <= 40 && item.area > 0 && item.area < 80000 && !item.inSettings && !item.inSidebar && !/取消|预览|封面|定时/.test(item.label));
      const chosen = candidates
        .filter((item) => item.label === "发布" || item.label === "发布笔记" || item.label.includes("发布"))
        .sort((left, right) => (right.position === "fixed") - (left.position === "fixed") || right.y - left.y || right.x - left.x || left.area - right.area)[0];
      if (!chosen) return { found: false, platform, candidates: candidates.slice(0, 24).map((item) => ({ label: item.label, className: item.className, x: item.x, y: item.y })) };
      const rect = chosen.el.getBoundingClientRect();
      return { found: true, platform, text: "发布", label: chosen.label, className: chosen.className, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`, 10000);
    if (!target?.found) return { clicked: false, ...target };
    await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
    return { clicked: true, platform, text: target.text, label: target.label, className: target.className, input_click: { x: target.x, y: target.y } };
  }
  return clickFinalPublishByText(client, texts);
}

async function clickVisibleDialogConfirm(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll("[role=dialog],[aria-modal=true],[class*=modal],[class*=dialog],[class*=popover],[class*=drawer]")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => item.text && item.area > 1000)
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      if (!/确认|确定|发布|投稿|声明|风险|无误|提交/.test(dialog.text)) continue;
      const candidates = [...dialog.el.querySelectorAll("button,[role=button],input[type=button],input[type=submit],span,div")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const label = clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("title"));
          const className = clean(typeof el.className === "string" ? el.className : "");
          return { el, label, className, area: rect.width * rect.height, y: rect.top };
        })
        .filter((item) => item.label && item.label.length <= 80 && item.area > 0 && item.area < 120000 && !/取消|返回|关闭/.test(item.label));
      for (const text of texts) {
        const chosen = candidates
          .filter((item) => item.label === text || item.label.includes(text))
          .sort((left, right) => left.area - right.area || right.y - left.y)[0];
        if (!chosen) continue;
        chosen.el.scrollIntoView({ block: "center", inline: "center" });
        const rect = chosen.el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) chosen.el.dispatchEvent(new MouseEvent(type, eventInit));
        return { clicked: true, text, label: chosen.label, dialog_text: dialog.text.slice(0, 240) };
      }
    }
    return { clicked: false, dialogs: dialogs.slice(0, 6).map((item) => item.text.slice(0, 220)) };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

async function clickToutiaoCompletionConfirm(client) {
  const target = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll(".Dialog-container,.m-xigua-dialog,[role=dialog]")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => /完成后无法继续编辑/.test(item.text))
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      const button = [...dialog.el.querySelectorAll("button,[role=button]")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          return { el, label: clean(el.innerText || el.textContent), className: clean(typeof el.className === "string" ? el.className : ""), x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height };
        })
        .filter((item) => item.label === "确定" || item.label === "确认")
        .sort((left, right) => left.area - right.area)[0];
      if (button) return { found: true, label: button.label, x: button.x, y: button.y, className: button.className, dialog: dialog.text.slice(0, 120) };
    }
    return { found: false, dialogs: dialogs.map((item) => item.text.slice(0, 160)) };
  })()`, 10000);
  if (!target.found) return { clicked: false, ...target };
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1600);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    return { still_open: /完成后无法继续编辑/.test(clean(document.body.innerText || "")) };
  })()`, 10000);
  return { clicked: true, ...target, ...after };
}

async function setFirstVideoFileInput(client, mediaPath) {
  if (!mediaPath) return { uploaded: false, reason: "missing_media_path" };
  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const rootNodeId = documentResult.root.nodeId;
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: rootNodeId, selector: "input[type=file]" });
  const nodeIds = queryResult.nodeIds || [];
  const described = [];
  for (const nodeId of nodeIds) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    described.push({ nodeId, attrMap });
  }
  const preferred =
    described.find((item) => /video|mp4|\*/i.test(item.attrMap.accept || "")) ||
    described.find((item) => !/image/i.test(item.attrMap.accept || "")) ||
    described[0];
  if (!preferred) return { uploaded: false, reason: "no_file_input", fileInputs: described.map((item) => item.attrMap) };
  await client.send("DOM.setFileInputFiles", { nodeId: preferred.nodeId, files: [mediaPath] });
  await dispatchFileInputEvents(client, preferred.nodeId);
  return { uploaded: true, input: preferred.attrMap, fileInputCount: described.length };
}

async function dispatchFileInputEvents(client, nodeId) {
  try {
    const resolved = await client.send("DOM.resolveNode", { nodeId });
    const objectId = resolved.object?.objectId;
    if (!objectId) return { dispatched: false, reason: "missing_object_id" };
    await client.send("Runtime.callFunctionOn", {
      objectId,
      awaitPromise: true,
      functionDeclaration: `function() {
        this.dispatchEvent(new Event("input", { bubbles: true }));
        this.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      }`,
    });
    return { dispatched: true };
  } catch (error) {
    return { dispatched: false, reason: error.message };
  }
}

async function setTextFieldByHints(client, hints, value, { multiline = false } = {}) {
  const textValue = String(value || "").trim();
  if (!textValue) return { filled: false, reason: "empty_value" };
  const expression = `(() => {
    const hints = ${JSON.stringify(hints)};
    const value = ${JSON.stringify(textValue)};
    const multiline = ${JSON.stringify(Boolean(multiline))};
    const clean = (raw) => String(raw || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const doc = el.ownerDocument || document;
      const win = doc.defaultView || window;
      const rect = el.getBoundingClientRect();
      const style = win.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none" && !el.disabled && !el.readOnly && el.getAttribute("readonly") === null && el.getAttribute("aria-disabled") !== "true";
    };
    const roots = [];
    const visitRoot = (root) => {
      if (!root || roots.includes(root)) return;
      roots.push(root);
      for (const el of [...root.querySelectorAll("*")]) {
        if (el.shadowRoot) visitRoot(el.shadowRoot);
        if (el.tagName === "IFRAME") {
          try {
            if (el.contentDocument) visitRoot(el.contentDocument);
          } catch {}
        }
      }
    };
    visitRoot(document);
    const queryAll = (selector) => roots.flatMap((root) => {
      try {
        return [...root.querySelectorAll(selector)];
      } catch {
        return [];
      }
    });
    const labelFor = (el) => {
      const id = el.getAttribute("id");
      const labelledBy = el.getAttribute("aria-labelledby");
      const labels = [];
      if (id) labels.push(...queryAll(\`label[for="\${CSS.escape(id)}"]\`).map((label) => label.innerText));
      if (labelledBy) {
        for (const part of labelledBy.split(/\\s+/)) {
          const node = document.getElementById(part);
          if (node) labels.push(node.innerText || node.textContent || "");
        }
      }
      let parent = el.parentElement;
      for (let index = 0; index < 3 && parent; index += 1, parent = parent.parentElement) {
        labels.push(parent.innerText || "");
      }
      return clean([el.getAttribute("aria-label"), el.getAttribute("placeholder"), el.getAttribute("title"), ...labels].filter(Boolean).join(" "));
    };
    const selector = multiline
      ? "textarea,[contenteditable=true],[role=textbox]"
      : "input:not([type]),input[type=text],textarea,[contenteditable=true],[role=textbox]";
    const candidates = queryAll(selector).filter(visible).map((el) => ({
      el,
      label: labelFor(el),
      current: clean(el.value || el.innerText || el.textContent),
    }));
    const score = (item) => {
      let value = 0;
      for (const hint of hints) {
        if (!hint) continue;
        if (item.label.includes(hint)) value += 10;
        if (item.current.includes(hint)) value += 2;
      }
      if (multiline && item.el.tagName === "TEXTAREA") value += 2;
      if (!multiline && item.el.tagName === "INPUT") value += 2;
      if (!item.current) value += 1;
      return value;
    };
    const chosen = candidates.sort((left, right) => score(right) - score(left))[0];
    if (!chosen || score(chosen) <= 0) return { filled: false, reason: "field_not_found", candidates: candidates.slice(0, 10).map((item) => item.label) };
    const el = chosen.el;
    el.scrollIntoView({ block: "center", inline: "center" });
    el.focus();
    if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
      el.textContent = value;
    } else {
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, value);
      else el.value = value;
    }
    for (const type of ["input", "change", "blur"]) {
      el.dispatchEvent(new Event(type, { bubbles: true }));
    }
    return { filled: true, label: chosen.label, tag: el.tagName.toLowerCase() };
  })()`;
  return evaluateWithClient(client, expression, 10000);
}

function parseChinaLocalSchedule(value) {
  const text = String(value || "").trim();
  if (!text) return { timestamp: 0, display: "" };
  const normalized = text.replace(" ", "T");
  const withSeconds = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(normalized) ? `${normalized}:00` : normalized;
  const zoned = /(?:Z|[+-]\d{2}:\d{2})$/i.test(withSeconds) ? withSeconds : `${withSeconds}+08:00`;
  const date = new Date(zoned);
  if (Number.isNaN(date.getTime())) return { timestamp: 0, display: text.replace("T", " ").slice(0, 16) };
  const display = normalized.replace("T", " ").slice(0, 16);
  return { timestamp: Math.floor(date.getTime() / 1000), display };
}

function expectedCollectionName(content) {
  return String(content.collection?.name || content.collection_name || content.playlist_name || content.playlist?.name || "").trim();
}

function expectedCoverPath(content) {
  return String(content.cover_path || content.copy_material?.cover_path || content.thumbnail_path || content.thumbnail?.local_path || "").trim();
}

function expectedTags(content, limit = 12) {
  return Array.from(
    new Set([...(content.hashtags || []), ...(content.structured_tags || []), ...(content.tags || [])].map((item) => String(item || "").replace(/^#/, "").trim()).filter(Boolean)),
  ).slice(0, limit);
}

async function setImageFileInputByAccept(client, imagePath) {
  const expectedPath = String(imagePath || "").trim();
  if (!expectedPath) return { uploaded: false, reason: "missing_image_path" };
  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const rootNodeId = documentResult.root.nodeId;
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: rootNodeId, selector: "input[type=file]" });
  const described = [];
  for (const nodeId of queryResult.nodeIds || []) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    described.push({ nodeId, attrMap });
  }
  const preferred =
    described.find((item) => /image|png|jpe?g|webp/i.test(item.attrMap.accept || "")) ||
    described.find((item) => !/video|mp4/i.test(item.attrMap.accept || ""));
  if (!preferred) return { uploaded: false, reason: "no_image_file_input", fileInputs: described.map((item) => item.attrMap) };
  await client.send("DOM.setFileInputFiles", { nodeId: preferred.nodeId, files: [expectedPath] });
  await dispatchFileInputEvents(client, preferred.nodeId);
  return { uploaded: true, expected_path: expectedPath, input: preferred.attrMap, fileInputCount: described.length };
}

async function openXiaohongshuCoverEditor(client) {
  const alreadyOpen = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const modal = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .find((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    const imageInput = [...document.querySelectorAll("input[type=file]")]
      .find((el) => /image|png|jpe?g|webp/i.test(el.getAttribute("accept") || el.accept || ""));
    return { open: Boolean(modal || imageInput), has_image_input: Boolean(imageInput), modal_text: clean(modal?.innerText || modal?.textContent).slice(0, 160) };
  })()`, 10000);
  if (alreadyOpen.open) return { opened: true, already_open: true, ...alreadyOpen };

  const coords = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const card =
      document.querySelector(".publish-page-content-cover .default.column") ||
      [...document.querySelectorAll("div,span")]
        .filter(visible)
        .find((el) => /修改封面|智能推荐封面|默认截取第一帧/.test(clean(el.innerText || el.textContent))) ||
      document.querySelector(".publish-page-content-cover");
    if (!visible(card)) return { found: false };
    card.scrollIntoView({ block: "center", inline: "center" });
    const rect = card.getBoundingClientRect();
    return {
      found: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      label: clean(card.innerText || card.textContent).slice(0, 120),
      className: String(card.className || ""),
    };
  })()`, 10000);
  if (!coords.found) return { opened: false, reason: "cover_card_not_found", coords };

  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: coords.x, y: coords.y, button: "none" }).catch(() => {});
  await sleep(800);
  const clickCoords = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      if (!el) return false;
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const operator =
      document.querySelector(".publish-page-content-cover .operator") ||
      [...document.querySelectorAll("button,[role=button],div,span")]
        .filter(visible)
        .find((el) => /修改封面/.test(clean(el.innerText || el.textContent)));
    const target = visible(operator) ? operator : document.querySelector(".publish-page-content-cover .default.column");
    if (!visible(target)) return { found: false };
    const rect = target.getBoundingClientRect();
    return {
      found: true,
      x: rect.left + rect.width / 2,
      y: rect.top + rect.height / 2,
      label: clean(target.innerText || target.textContent).slice(0, 120),
      className: String(target.className || ""),
    };
  })()`, 10000);
  if (!clickCoords.found) return { opened: false, reason: "cover_operator_not_found", coords, clickCoords };
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: clickCoords.x, y: clickCoords.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: clickCoords.x, y: clickCoords.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: clickCoords.x, y: clickCoords.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1600);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el, index) => ({
      index,
      accept: el.getAttribute("accept") || el.accept || "",
      visible: visible(el),
    }));
    const modal = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .find((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    return {
      opened: Boolean(modal || fileInputs.some((input) => /image|png|jpe?g|webp/i.test(input.accept))),
      has_image_input: fileInputs.some((input) => /image|png|jpe?g|webp/i.test(input.accept)),
      modal_text: clean(modal?.innerText || modal?.textContent).slice(0, 200),
      fileInputs,
    };
  })()`, 10000);
  return { opened: Boolean(after.opened), coords, clickCoords, ...after };
}

async function clickXiaohongshuCoverConfirm(client) {
  const target = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const dialogs = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
      .filter((item) => /设置封面|上传图片|封面比例/.test(item.text))
      .sort((left, right) => left.area - right.area);
    for (const dialog of dialogs) {
      const button = [...dialog.el.querySelectorAll("button,[role=button]")]
        .filter(visible)
        .map((el) => {
          const rect = el.getBoundingClientRect();
          const className = clean(typeof el.className === "string" ? el.className : "");
          return { el, label: clean(el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("title")), className, area: rect.width * rect.height, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        })
        .filter((item) => item.label === "确定" && !/disabled/.test(item.className))
        .sort((left, right) => left.area - right.area || right.y - left.y)[0];
      if (!button) continue;
      return { found: true, label: button.label, x: button.x, y: button.y };
    }
    return { clicked: false, dialogs: dialogs.map((item) => item.text.slice(0, 160)) };
  })()`, 10000);
  if (!target.found) return target;
  await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
  await sleep(1800);
  const after = await evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
      .filter(visible)
      .some((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
    return { modal_open: modalOpen, body_has_modify_cover: /修改封面/.test(clean(document.body.innerText || "")) };
  })()`, 10000);
  if (after.modal_open) {
    const stale = await clearXiaohongshuStaleCoverLayers(client);
    if (stale.removed_count) {
      const cleared = await evaluateWithClient(client, `(() => {
        const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        };
        const modalOpen = [...document.querySelectorAll("[role=dialog],[class*=modal],.d-modal,.d-modal-content")]
          .filter(visible)
          .some((el) => /设置封面|上传图片|封面比例/.test(clean(el.innerText || el.textContent)));
        return { modal_open: modalOpen, body_has_modify_cover: /修改封面/.test(clean(document.body.innerText || "")) };
      })()`, 10000);
      return { clicked: true, label: target.label, input_click: { x: target.x, y: target.y }, stale_cover_layers_cleared: stale, ...cleared };
    }
  }
  return { clicked: true, label: target.label, input_click: { x: target.x, y: target.y }, ...after };
}

async function clearXiaohongshuStaleCoverLayers(client) {
  return evaluateWithClient(client, `(() => {
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const stale = [...document.querySelectorAll(".d-modal-mask,[class*=modal]")]
      .filter((el) => /portal-fade-leave-active/.test(String(el.className || "")) && /设置封面/.test(clean(el.innerText || el.textContent)));
    const removed = stale.map((el) => clean(el.innerText || el.textContent).slice(0, 160));
    for (const el of stale) el.remove();
    if (removed.length) {
      document.documentElement.style.overflowY = "";
      document.body.style.overflow = "";
      document.body.removeAttribute("aria-expanded");
    }
    return { removed_count: removed.length, removed };
  })()`, 10000);
}

async function waitForCompositeUploadReady(client, platform, timeoutMs = 120000, mediaPath = "") {
  const startedAt = Date.now();
  const mediaName = mediaPath ? path.win32.basename(String(mediaPath)) : "";
  const mediaStem = mediaName.replace(/\.[^.]+$/, "");
  let last = null;
  while (Date.now() - startedAt < timeoutMs) {
    last = await evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify({ mediaName, mediaStem })};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const text = clean(document.body.innerText || "");
      const failed = /上传失败|Upload failed|刷新后重试|网络异常/.test(text);
      const busy = !failed && /上传中|正在上传|视频处理中|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%/.test(text);
      const kuaishouReadySurface =
        ${JSON.stringify(platform)} === "kuaishou" &&
        /重新上传/.test(text) &&
        /预览作品|预览封面|编辑画布|封面设置/.test(text) &&
        /作品描述|发布时间|发布设置/.test(text) &&
        !/上传失败/.test(text);
      const mediaPresent = !expected.mediaName || text.includes(expected.mediaName) || text.includes(expected.mediaStem) || kuaishouReadySurface;
      const uploadPromptOnly = /拖拽视频到此|点击上传|上传视频\\s+视频大小|选择文件|Select files/.test(text) && !mediaPresent;
      const ready = mediaPresent && !uploadPromptOnly && (/上传成功|上传完成|检测完成|发布|定时发布|立即发布|封面应用成功/.test(text) || kuaishouReadySurface) && !busy;
      const lines = text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /上传|处理|检测|发布|%/.test(line)).slice(0, 50);
      return { platform: ${JSON.stringify(platform)}, ready, busy, failed, mediaPresent, uploadPromptOnly, kuaishouReadySurface, expected, lines };
    })()`, 10000);
    if (last.failed) return { ready: false, failed: true, waited_ms: Date.now() - startedAt, last };
    if (last.ready) return { ready: true, waited_ms: Date.now() - startedAt, last };
    await sleep(5000);
  }
  return { ready: false, waited_ms: Date.now() - startedAt, last };
}

function expectedMediaPath(content) {
  const mediaItems = Array.isArray(content.media_items) ? content.media_items : [];
  return String(mediaItems.find((item) => item && item.local_path)?.local_path || (content.media_urls || [])[0] || "").trim();
}

async function ensureCompositeUploadReady(client, platform, content, timeoutMs = 120000) {
  const actions = [];
  const mediaPath = expectedMediaPath(content);
  let readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath);
  actions.push({ kind: `${platform}_upload_ready_wait`, ...readiness });
  if (readiness.ready) return { actions, readiness };

  actions.push({ kind: `${platform}_upload_reupload_entry`, ...(await clickByText(client, ["重新上传", "刷新", "重试", "选择视频", "点击上传", "上传视频"])) });
  await sleep(1200);
  const upload = await setFirstVideoFileInput(client, mediaPath);
  actions.push({ kind: `${platform}_upload_reupload`, ...upload });
  if (upload.uploaded) {
    await sleep(16000);
    readiness = await waitForCompositeUploadReady(client, platform, timeoutMs, mediaPath);
    actions.push({ kind: `${platform}_upload_ready_after_reupload`, ...readiness });
  }
  return { actions, readiness };
}

async function readCompositeMaterialIntegrity(client, platform, content) {
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  const collection = expectedCollectionName(content);
  const coverPath = platform === "x" ? "" : expectedCoverPath(content);
  const schedule = parseChinaLocalSchedule(content.scheduled_publish_at || "");
  const result = await evaluateWithClient(client, `(() => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ title, body, tags, collection, coverPath, scheduleDisplay: schedule.display })};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const bodyText = clean(document.body.innerText || "");
    const lines = bodyText.split(/[\\n\\r]+| {2,}/).map(clean).filter(Boolean);
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const imageSources = [...document.querySelectorAll("img")]
      .filter(visible)
      .map((img) => String(img.currentSrc || img.src || ""))
      .filter(Boolean)
      .slice(0, 80);
    const backgroundSources = [...document.querySelectorAll("*")]
      .filter(visible)
      .map((el) => String(getComputedStyle(el).backgroundImage || ""))
      .filter((src) => src && src !== "none")
      .slice(0, 80);
    const inputs = [...document.querySelectorAll("input,textarea,[contenteditable=true]")]
      .filter(visible)
      .map((el) => clean(el.value || el.innerText || el.textContent || el.getAttribute("aria-label") || el.getAttribute("placeholder")))
      .filter(Boolean)
      .slice(0, 160);
    const textHaystack = clean([bodyText, ...inputs].join(" "));
    const tagChecks = expected.tags.map((tag) => ({ tag, present: textHaystack.includes(tag) || textHaystack.includes("#" + tag) }));
    const scheduleDate = expected.scheduleDisplay ? expected.scheduleDisplay.slice(0, 10) : "";
    const scheduleTime = expected.scheduleDisplay ? expected.scheduleDisplay.slice(11, 16) : "";
    const youtubeScheduled = platform === "youtube" && /已安排好视频发布时间|已排定时间|已排定|Scheduled|公开范围 已排定时间/.test(textHaystack);
    const scheduleShort = scheduleDate ? scheduleDate.slice(5) : "";
    const scheduleDateLabel = scheduleShort ? scheduleShort.replace("-", "月") + "日" : "";
    const schedulePresent = !expected.scheduleDisplay || youtubeScheduled || (
      textHaystack.includes(expected.scheduleDisplay) ||
      (scheduleDate && scheduleTime && textHaystack.includes(scheduleDate) && textHaystack.includes(scheduleTime)) ||
      (scheduleDate && scheduleTime && textHaystack.includes(scheduleDate.replace(/-/g, "年").replace(/年(\\d{2})年/, "年$1月")) && textHaystack.includes(scheduleTime)) ||
      (scheduleShort && scheduleTime && textHaystack.includes(scheduleShort) && textHaystack.includes(scheduleTime)) ||
      (scheduleDateLabel && scheduleTime && textHaystack.includes(scheduleDateLabel) && textHaystack.includes(scheduleTime))
    );
    const receiptLike =
      (platform === "toutiao" && Boolean(expected.title) && textHaystack.includes(expected.title) && (
        /全部发表成功|发布成功|审核中|已发布|定时发布中|定时发布时间/.test(textHaystack)
      ) && schedulePresent) ||
      (platform === "xiaohongshu" && /\/publish\/success/.test(location.href) && /发布成功/.test(textHaystack));
    const receiptFieldBypass = receiptLike && platform !== "youtube";
    const coverBasename = expected.coverPath ? expected.coverPath.split(/[\\\\/]/).pop() : "";
    const youtubeAutoThumbnail = platform === "youtube" && imageSources.some((src) => /i\\.ytimg\\.com|mqdefault|hqdefault|vi_webp/.test(src));
    const youtubeCustomThumbnailPreview = platform === "youtube" && imageSources.some((src) => /^data:image\\//.test(src));
    const youtubeThumbnailUploading = platform === "youtube" && /正在上传|上传缩略图|缩略图.{0,12}上传中|Uploading thumbnail|Thumbnail upload/.test(textHaystack);
    const youtubeThumbnailState = platform !== "youtube"
      ? ""
      : youtubeThumbnailUploading
        ? "custom_uploading"
        : youtubeCustomThumbnailPreview
          ? "custom_preview_ready"
          : youtubeAutoThumbnail
            ? "generated_remote_thumbnail"
            : "unknown";
    const xiaohongshuCustomCoverPreview = platform === "xiaohongshu" && (
      imageSources.some((src) => /^blob:|^data:image\\//.test(src)) ||
      backgroundSources.some((src) => src.includes("blob:") || src.includes("data:image/")) ||
      /封面效果评估通过/.test(textHaystack)
    );
    const uploadBusy = /上传中|正在上传|视频处理中|处理中\\s*\\d+%|检测中\\s*\\d+%|检测中99%/.test(textHaystack);
    const coverRequiredWarning = /该视频需要上传一个封面|需要上传.{0,24}封面|请上传.{0,24}封面/.test(textHaystack);
    const platformCoverSuccess =
      platform === "kuaishou" ? /封面应用成功|重新设置封面|封面设置/.test(textHaystack)
      : platform === "xiaohongshu" ? /重新设置封面|上传成功|封面预览|封面效果评估通过/.test(textHaystack) && xiaohongshuCustomCoverPreview && !/封面上传中/.test(textHaystack)
      : platform === "toutiao" ? /上传成功|修改封面|重新上传封面|封面已上传/.test(textHaystack)
      : imageSources.length > 0;
    const coverPresent = !expected.coverPath
      ? true
      : !coverRequiredWarning && (textHaystack.includes(coverBasename) || (platform !== "youtube" && platformCoverSuccess) || (platform === "youtube" && youtubeCustomThumbnailPreview && !youtubeThumbnailUploading));
    const declarationPresent =
      platform === "bilibili" ? /内容无需标注/.test(textHaystack)
      : platform === "xiaohongshu" ? /原创声明|声明原创|原创/.test(textHaystack)
      : platform === "kuaishou" ? /原创|作者声明|声明/.test(textHaystack)
      : platform === "toutiao" ? /原创|声明|权益/.test(textHaystack)
      : platform === "wechat-channels" ? /声明原创|原创|声明/.test(textHaystack)
      : true;
    const platformExtras = {
      youtube_link: (textHaystack.match(/https:\\/\\/youtu\\.be\\/[A-Za-z0-9_-]+/) || textHaystack.match(/https:\\/\\/www\\.youtube\\.com\\/watch\\?v=[A-Za-z0-9_-]+/) || [])[0] || "",
      youtube_scheduled: youtubeScheduled,
      youtube_thumbnail_uploading: youtubeThumbnailUploading,
      youtube_custom_thumbnail_preview: youtubeCustomThumbnailPreview,
      youtube_remote_auto_thumbnail: youtubeAutoThumbnail,
      youtube_thumbnail_state: youtubeThumbnailState,
      xiaohongshu_custom_cover_preview: xiaohongshuCustomCoverPreview,
      route: { url: location.href, title: document.title },
      image_sources: imageSources.slice(0, 12),
      background_sources: backgroundSources.slice(0, 12),
      relevant_lines: lines.filter((line) => /发布|预约|定时|封面|缩略图|播放列表|合集|原创|声明|公开|已排定|链接|正在上传|标签|话题|分类/.test(line)).slice(0, 120),
    };
    const fields = {
      title: { expected: expected.title, verified: receiptFieldBypass || !expected.title || textHaystack.includes(expected.title) },
      body: { expected: expected.body, verified: receiptFieldBypass || !expected.body || textHaystack.includes(expected.body.slice(0, Math.min(28, expected.body.length))) },
      tags: { expected: expected.tags, actual_checks: tagChecks, verified: receiptFieldBypass || tagChecks.every((item) => item.present) },
      collection: { expected: expected.collection, verified: receiptFieldBypass || !expected.collection || platform === "x" || (platform === "kuaishou" && /加入合集|选择要加入到的合集/.test(textHaystack)) || textHaystack.includes(expected.collection) },
      schedule: { expected: expected.scheduleDisplay, verified: receiptFieldBypass || schedulePresent },
      upload_ready: { verified: receiptFieldBypass || !uploadBusy },
      declaration: { verified: receiptFieldBypass || declarationPresent },
      cover: { expected_path: expected.coverPath, verified: receiptFieldBypass || coverPresent || platform === "x", cover_required_warning: coverRequiredWarning, youtube_auto_thumbnail: youtubeAutoThumbnail, youtube_custom_thumbnail_preview: youtubeCustomThumbnailPreview, youtube_thumbnail_uploading: youtubeThumbnailUploading, youtube_thumbnail_state: youtubeThumbnailState },
    };
    const failures = Object.entries(fields).filter(([, value]) => value && value.verified === false).map(([key]) => key);
    platformExtras.receipt_like = receiptLike;
    return { platform, fields, verified: failures.length === 0, failures, platform_extras: platformExtras };
  })()`, 20000);
  return result;
}

async function prepareGenericCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  const bodyWithPlatformTags = ["xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"].includes(platform) && tags.length
    ? `${platform === "kuaishou" && title ? `${title}\n` : ""}${body}\n${tags.map((tag) => `#${tag}`).join(" ")}`
    : body;
  const coverPath = platform === "x" ? "" : expectedCoverPath(content);
  if (!["xiaohongshu", "toutiao", "kuaishou"].includes(platform)) {
    actions.push(await setTextFieldByHints(client, ["标题", "作品标题", "title", "Title"], title, { multiline: false }));
    actions.push(await setTextFieldByHints(client, ["简介", "描述", "说明", "正文", "作品描述", "作品描述", "视频简介", "description", "Description"], bodyWithPlatformTags, { multiline: true }));
  }
  actions.push({ kind: "platform_rich_text", ...(await setPlatformRichText(client, platform, title, bodyWithPlatformTags)) });
  if (coverPath) {
    const entryTexts = platform === "youtube"
      ? ["上传文件", "缩略图", "Thumbnail", "Upload file"]
      : ["设置封面", "封面设置", "上传封面", "更换封面", "选择封面"];
    actions.push({ kind: "cover_entry", ...(await clickByText(client, entryTexts)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "cover_entry_loose", ...(await clickLooseText(client, entryTexts)) });
    await sleep(1400);
    if (platform === "xiaohongshu") {
      actions.push({ kind: "xiaohongshu_cover_ratio", ...(await clickByText(client, ["3:4"])) });
      await sleep(500);
    }
    if (platform === "toutiao") {
      actions.push({ kind: "toutiao_cover_local_upload", ...(await clickByText(client, ["本地上传", "上传图片", "上传封面"])) });
      if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_local_upload_loose", ...(await clickLooseText(client, ["本地上传", "上传图片", "上传封面"])) });
      await sleep(800);
    }
    actions.push({ kind: "cover_upload", ...(await setImageFileInputByAccept(client, coverPath)) });
    await sleep(3500);
    if (platform === "xiaohongshu") {
      actions.push({ kind: "xiaohongshu_cover_confirm", ...(await clickByText(client, ["确定"])) });
      await sleep(1600);
    }
    if (platform === "toutiao") {
      actions.push({ kind: "toutiao_cover_next", ...(await clickByText(client, ["下一步"])) });
      await sleep(1000);
      actions.push({ kind: "toutiao_cover_confirm", ...(await clickByText(client, ["确定", "完成"])) });
      await sleep(1400);
    }
  }
  const skipSeparateTagFill = ["xiaohongshu", "kuaishou"].includes(platform);
  for (const tag of skipSeparateTagFill ? [] : tags.slice(0, 10)) {
    if (platform === "xiaohongshu" || platform === "kuaishou") {
      actions.push(await setTextFieldByHints(client, ["添加话题", "话题", "标签", "按回车"], `#${tag}`, { multiline: true }));
    } else {
      actions.push(await setTextFieldByHints(client, ["标签", "tag", "Tags"], tag, { multiline: false }));
    }
  }
  const collection = expectedCollectionName(content);
  if (collection) {
    actions.push({ kind: "collection_entry", ...(await clickByText(client, ["播放列表", "选择", "加入合集", "选择合集", "合集", "创建合集"])) });
    await sleep(1000);
    actions.push({ kind: "collection_select", ...(await clickByText(client, [collection])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "collection_select_loose", ...(await clickLooseText(client, [collection])) });
    await sleep(800);
  }
  if (platform === "youtube") {
    actions.push({ kind: "youtube_not_for_kids", ...(await clickByText(client, ["不，内容不是面向儿童的", "否，并非面向儿童", "No, it's not made for kids"])) });
  }
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_original_declaration", ...(await clickByText(client, ["原创声明", "声明原创", "原创"])) });
  }
  if (platform === "toutiao" || platform === "kuaishou") {
    actions.push({ kind: `${platform}_original_declaration`, ...(await clickByText(client, ["原创", "声明", "作者声明"])) });
  }
  if (content.scheduled_publish_at) {
    actions.push({ kind: "schedule_entry", ...(await clickByText(client, ["定时发布", "发布时间", "预约", "公开范围", "已排定时间", "安排时间"])) });
    await sleep(900);
    actions.push({ kind: "schedule_set", ...(await setGenericScheduleControls(client, platform, content.scheduled_publish_at)) });
  }
  return actions;
}

function platformBodyWithTags(platform, content) {
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = expectedTags(content, platform === "youtube" ? 15 : 10);
  if (!["xiaohongshu", "kuaishou", "toutiao", "wechat-channels", "x"].includes(platform) || !tags.length) return body;
  return `${platform === "kuaishou" && title ? `${title}\n` : ""}${body}\n${tags.map((tag) => `#${tag}`).join(" ")}`;
}

async function uploadCompositeCover(client, platform, coverPath) {
  const actions = [];
  if (!coverPath) return actions;
  const entryTexts = platform === "youtube"
    ? ["上传文件", "缩略图", "Thumbnail", "Upload file"]
    : ["设置封面", "封面设置", "上传封面", "更换封面", "选择封面"];
  actions.push({ kind: `${platform}_cover_entry`, ...(await clickByText(client, entryTexts)) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_cover_entry_loose`, ...(await clickLooseText(client, entryTexts)) });
  await sleep(1400);
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_cover_editor_open", ...(await openXiaohongshuCoverEditor(client)) });
    await sleep(700);
    actions.push({ kind: "xiaohongshu_cover_ratio", ...(await clickByText(client, ["3:4"])) });
    await sleep(500);
    actions.push({ kind: "xiaohongshu_cover_upload_entry", ...(await clickByText(client, ["上传图片", "+ 上传图片", "上传封面"])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "xiaohongshu_cover_upload_entry_loose", ...(await clickLooseText(client, ["上传图片", "+ 上传图片", "上传封面"])) });
    await sleep(900);
  }
  if (platform === "toutiao") {
    actions.push({ kind: "toutiao_cover_local_upload", ...(await clickByText(client, ["本地上传", "上传图片", "上传封面"])) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_local_upload_loose", ...(await clickLooseText(client, ["本地上传", "上传图片", "上传封面"])) });
    await sleep(800);
  }
  actions.push({ kind: `${platform}_cover_upload`, ...(await setImageFileInputByAccept(client, coverPath)) });
  await sleep(3500);
  if (platform === "xiaohongshu") {
    actions.push({ kind: "xiaohongshu_cover_confirm", ...(await clickXiaohongshuCoverConfirm(client)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "xiaohongshu_cover_confirm_fallback", ...(await clickByText(client, ["确定"])) });
    await sleep(1600);
  }
  if (platform === "toutiao") {
    actions.push({ kind: "toutiao_cover_next", ...(await clickByText(client, ["下一步"])) });
    await sleep(1000);
    actions.push({ kind: "toutiao_cover_confirm", ...(await clickByText(client, ["确定", "完成"])) });
    await sleep(1400);
    actions.push({ kind: "toutiao_cover_completion_confirm", ...(await clickToutiaoCompletionConfirm(client)) });
    if (!actions.at(-1)?.clicked) actions.push({ kind: "toutiao_cover_completion_confirm_fallback", ...(await clickVisibleDialogConfirm(client, ["确定", "确认", "完成"])) });
    if (actions.at(-1)?.clicked) await sleep(1800);
  }
  return actions;
}

async function selectCompositeCollection(client, platform, content) {
  const collection = expectedCollectionName(content);
  if (!collection) return [];
  const actions = [];
  const entryTexts = platform === "youtube"
    ? ["播放列表", "Playlist", "选择"]
    : ["加入合集", "选择合集", "合集", "播放列表", "选择", "创建合集"];
  actions.push({ kind: `${platform}_collection_entry`, ...(await clickByText(client, entryTexts)) });
  await sleep(1000);
  actions.push({ kind: `${platform}_collection_select`, ...(await clickByText(client, [collection])) });
  if (!actions.at(-1)?.clicked) actions.push({ kind: `${platform}_collection_select_loose`, ...(await clickLooseText(client, [collection])) });
  await sleep(800);
  return actions;
}

async function setCompositeSchedule(client, platform, content) {
  if (!content.scheduled_publish_at) return [];
  const actions = [];
  if (!["xiaohongshu"].includes(platform)) {
    actions.push({ kind: `${platform}_schedule_entry`, ...(await clickByText(client, ["定时发布", "发布时间", "预约", "公开范围", "已排定时间", "安排时间", "Schedule"])) });
    await sleep(900);
  }
  try {
    actions.push({ kind: `${platform}_schedule_set`, ...(await setGenericScheduleControls(client, platform, content.scheduled_publish_at)) });
  } catch (error) {
    actions.push({ kind: `${platform}_schedule_set`, set: false, reason: "schedule_control_error", message: error.message });
  }
  return actions;
}

async function prepareYoutubeCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const coverPath = expectedCoverPath(content);
  actions.push({ kind: "youtube_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, coverPath)));
  for (const tag of expectedTags(content, 15)) {
    actions.push({ kind: "youtube_tag", ...(await setTextFieldByHints(client, ["标签", "tag", "Tags"], tag, { multiline: false })) });
  }
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "youtube_not_for_kids", ...(await clickByText(client, ["不，内容不是面向儿童的", "否，并非面向儿童", "No, it's not made for kids"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareXiaohongshuCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  actions.push({ kind: "xiaohongshu_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "xiaohongshu_original_declaration", ...(await clickByText(client, ["原创声明", "声明原创", "原创"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareKuaishouCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, 180000);
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) return actions;
  actions.push({ kind: "kuaishou_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "kuaishou_original_declaration", ...(await clickByText(client, ["作者声明", "原创", "声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareToutiaoCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  const body = platformBodyWithTags(platform, content);
  const uploadReadiness = await ensureCompositeUploadReady(client, platform, content, 180000);
  actions.push(...uploadReadiness.actions);
  if (!uploadReadiness.readiness?.ready) return actions;
  actions.push({ kind: "toutiao_rich_text", ...(await setPlatformRichText(client, platform, title, body)) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  for (const tag of expectedTags(content, 10)) {
    actions.push({ kind: "toutiao_tag", ...(await setTextFieldByHints(client, ["话题", "标签", "tag", "Tags"], tag, { multiline: false })) });
  }
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "toutiao_original_declaration", ...(await clickByText(client, ["原创", "声明", "作者声明", "作品声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareWechatChannelsCompositeDraft(client, platform, content) {
  const actions = [];
  const title = String(content.title || "").trim();
  actions.push({ kind: "wechat_channels_rich_text", ...(await setPlatformRichText(client, platform, title, platformBodyWithTags(platform, content))) });
  actions.push(...(await uploadCompositeCover(client, platform, expectedCoverPath(content))));
  actions.push(...(await selectCompositeCollection(client, platform, content)));
  actions.push({ kind: "wechat_channels_original_declaration", ...(await clickByText(client, ["声明原创", "原创", "声明"])) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

async function prepareXCompositeDraft(client, platform, content) {
  const actions = [];
  actions.push({ kind: "x_rich_text", ...(await setPlatformRichText(client, platform, "", platformBodyWithTags(platform, content))) });
  actions.push(...(await setCompositeSchedule(client, platform, content)));
  return actions;
}

const PLATFORM_COMPOSITE_FRAMEWORKS = {
  youtube: { id: "youtube_studio_composite_v1", prepare: prepareYoutubeCompositeDraft },
  xiaohongshu: { id: "xiaohongshu_creator_composite_v1", prepare: prepareXiaohongshuCompositeDraft },
  kuaishou: { id: "kuaishou_creator_composite_v1", prepare: prepareKuaishouCompositeDraft },
  toutiao: { id: "toutiao_xigua_composite_v1", prepare: prepareToutiaoCompositeDraft },
  "wechat-channels": { id: "wechat_channels_composite_v1", prepare: prepareWechatChannelsCompositeDraft },
  x: { id: "x_composer_composite_v1", prepare: prepareXCompositeDraft },
};

const DEDICATED_PLATFORM_FRAMEWORK_IDS = Object.freeze({
  bilibili: "bilibili_creator_native_composite_v1",
  ...Object.fromEntries(Object.entries(PLATFORM_COMPOSITE_FRAMEWORKS).map(([platform, framework]) => [platform, framework.id])),
});

function dedicatedCompositeFrameworkId(platform) {
  return DEDICATED_PLATFORM_FRAMEWORK_IDS[platform] || "";
}

function buildPublicationAuditChecklist(fields = {}) {
  const checklist = {};
  for (const key of ["cover", "title", "body", "tags", "collection", "schedule", "upload_ready", "declaration", "receipt"]) {
    if (!fields[key]) continue;
    checklist[key] = {
      verified: fields[key].verified !== false,
      expected: fields[key].expected ?? fields[key].expected_path ?? "",
    };
    if (Array.isArray(fields[key].actual_checks)) checklist[key].actual_checks = fields[key].actual_checks;
  }
  return checklist;
}

function buildCompositePublicationAudit(platform, content, integrity, finalPublish = {}, route = {}) {
  const fields = { ...(integrity?.fields || {}) };
  fields.receipt = {
    verified: Boolean(finalPublish.receipt_like || finalPublish.success_like || integrity?.platform_extras?.receipt_like || integrity?.platform_extras?.youtube_link || integrity?.platform_extras?.youtube_scheduled),
    expected: String(content.scheduled_publish_at || "").trim() ? "scheduled publish receipt" : "publish receipt",
  };
  const checklist = buildPublicationAuditChecklist(fields);
  const requiredUnverified = Object.entries(checklist)
    .filter(([, value]) => value && value.verified === false)
    .map(([key]) => key);
  return {
    platform,
    framework_id: dedicatedCompositeFrameworkId(platform),
    dedicated_platform_framework: Boolean(dedicatedCompositeFrameworkId(platform)),
    legacy_lightweight_script_used: false,
    verified: requiredUnverified.length === 0,
    required_unverified: requiredUnverified,
    checklist,
    route: route || integrity?.platform_extras?.route || {},
    platform_extras: integrity?.platform_extras || {},
  };
}

function buildBilibiliPublicationAudit(content, platformVerifier, finalPublish = {}, route = {}, coverAction = {}) {
  const actual = platformVerifier?.actual || {};
  const tags = Array.from(new Set([...(content.hashtags || []), ...(content.structured_tags || [])].map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 10);
  const collection = expectedCollectionName(content);
  const failures = new Set(platformVerifier?.failures || []);
  const hasFailure = (key) => failures.has(key) || (key === "body" && failures.has("description")) || (key === "tags" && [...failures].some((item) => String(item).startsWith("tag:")));
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const fields = {
    cover: { expected_path: expectedCoverPath(content), verified: !expectedCoverPath(content) || Boolean(coverAction?.uploaded) },
    title: { expected: String(content.title || "").trim(), verified: !hasFailure("title") },
    body: { expected: String(content.body || "").trim(), verified: !hasFailure("body") },
    tags: { expected: tags, actual_checks: tags.map((tag) => ({ tag, present: !failures.has(`tag:${tag}`) })), verified: !hasFailure("tags") },
    collection: { expected: collection, verified: !collection || !hasFailure("collection") },
    schedule: { expected: String(content.scheduled_publish_at || "").trim(), verified: !scheduled || !hasFailure("schedule") },
    upload_ready: { verified: true },
    declaration: { verified: !hasFailure("declaration") },
    receipt: { expected: scheduled ? "scheduled publish receipt" : "publish receipt", verified: Boolean(finalPublish.success_like) },
  };
  const checklist = buildPublicationAuditChecklist(fields);
  const requiredUnverified = Object.entries(checklist)
    .filter(([, value]) => value && value.verified === false)
    .map(([key]) => key);
  return {
    platform: "bilibili",
    framework_id: dedicatedCompositeFrameworkId("bilibili"),
    dedicated_platform_framework: true,
    legacy_lightweight_script_used: false,
    verified: requiredUnverified.length === 0,
    required_unverified: requiredUnverified,
    checklist,
    route,
    platform_extras: {
      actual,
      cover_action: coverAction,
      field_failures: platformVerifier?.failures || [],
      final_publish: finalPublish,
    },
  };
}

async function setGenericScheduleControls(client, platform, scheduledPublishAt) {
  const schedule = parseChinaLocalSchedule(scheduledPublishAt);
  if (!schedule.display) return { set: false, reason: "missing_schedule" };
  if (platform === "xiaohongshu") {
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const setValue = (el, value) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, key: "Enter" }));
        el.dispatchEvent(new KeyboardEvent("keyup", { bubbles: true, key: "Enter" }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        return true;
      };
      const actions = [];
      const switchInput = document.querySelector(".post-time-wrapper input[type=checkbox]");
      if (switchInput && !switchInput.checked) {
        actions.push({ clicked: "xiaohongshu_schedule_checkbox", ok: click(switchInput) });
        switchInput.checked = true;
        switchInput.dispatchEvent(new Event("input", { bubbles: true }));
        switchInput.dispatchEvent(new Event("change", { bubbles: true }));
        await sleep(900);
      }
      const pickerInput =
        [...document.querySelectorAll(".post-time-wrapper .d-datepicker input,.post-time-wrapper input")]
          .filter(visible)
          .find((el) => /\\d{4}-\\d{2}-\\d{2}|日期|时间|date|time/i.test(clean([el.value, el.placeholder, el.parentElement?.innerText].join(" ")))) ||
        [...document.querySelectorAll(".post-time-wrapper input")].filter(visible).find((el) => el.type !== "checkbox");
      if (pickerInput) {
        actions.push({ set: "xiaohongshu_datetime", ok: setValue(pickerInput, expected.display), previous: clean(pickerInput.value) });
        await sleep(800);
      }
      const okButton = [...document.querySelectorAll("button,[role=button],span,div")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "确定" || item.text === "完成")
        .sort((left, right) => left.area - right.area)[0];
      if (okButton) {
        actions.push({ clicked: "xiaohongshu_datetime_ok", label: okButton.text, ok: click(okButton.el) });
        await sleep(400);
      }
      const text = clean(document.body.innerText || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 60),
      };
    })()`, 12000);
  }
  if (platform === "kuaishou") {
    const expected = { display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16), inputValue: `${schedule.display}:00` };
    const actions = [];
    actions.push({ clicked: "kuaishou_schedule_entry", ...(await clickByText(client, ["定时发布", "发布时间", "预约"])) });
    await sleep(700);
    const target = await evaluateWithClient(client, `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const input = [...document.querySelectorAll("input[placeholder*=选择日期时间],.ant-picker input,input")]
        .filter(visible)
        .find((el) => /选择日期时间|\\d{4}-\\d{2}-\\d{2}|日期|时间/.test(clean([el.placeholder, el.value, el.parentElement?.innerText].join(" "))));
      if (!input) return { found: false };
      input.scrollIntoView({ block: "center", inline: "center" });
      const rect = input.getBoundingClientRect();
      return { found: true, value: input.value || "", x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    })()`, 10000);
    actions.push({ set: "kuaishou_datetime_target", ...target });
    if (target?.found) {
      await client.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y, button: "none" }).catch(() => {});
      await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
      await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", clickCount: 1 }).catch(() => {});
      await sleep(250);
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", modifiers: 2, key: "a", code: "KeyA", windowsVirtualKeyCode: 65 }).catch(() => {});
      await client.send("Input.insertText", { text: expected.inputValue }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 }).catch(() => {});
      await sleep(500);
      await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }).catch(() => {});
      await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 }).catch(() => {});
      await sleep(1000);
    }
    const after = await evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify(expected)};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const inputs = [...document.querySelectorAll("input,textarea,[contenteditable=true]")]
        .filter(visible)
        .map((el) => clean(el.value || el.innerText || el.textContent || el.getAttribute("placeholder")))
        .filter(Boolean);
      const text = clean([document.body.innerText || "", ...inputs].join(" "));
      const set = text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time));
      return {
        set,
        input_values: inputs.slice(0, 40),
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|10:30|20:00|21:00/.test(line)).slice(0, 80),
      };
    })()`, 10000);
    return { set: Boolean(after.set), expected, body_after_had_schedule: Boolean(after.set), actions, ...after };
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const setInput = (el, value) => {
        if (!el) return false;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
      };
      const actions = [];
      const buttons = [...document.querySelectorAll("button,[role=button],label,span,div")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => /定时发布|发布时间|预约/.test(item.text) && item.text.length <= 80)
        .sort((left, right) => left.area - right.area);
      if (buttons[0]) {
        actions.push({ clicked: "kuaishou_schedule_entry", label: buttons[0].text, ok: click(buttons[0].el) });
        await sleep(700);
      }
      const dateInputs = [...document.querySelectorAll(".ant-picker input,input[placeholder*=日期],input[placeholder*=时间]")]
        .filter(visible)
        .map((el) => ({ el, hint: clean([el.placeholder, el.value, el.parentElement?.innerText].join(" ")) }));
      for (const item of dateInputs) {
        if (/日期|date|年|月|日/i.test(item.hint)) actions.push({ set: "date_input", hint: item.hint, ok: setInput(item.el, expected.date) });
        else if (/时间|time|时|分/i.test(item.hint)) actions.push({ set: "time_input", hint: item.hint, ok: setInput(item.el, expected.time) });
      }
      await sleep(300);
      const dropdowns = [...document.querySelectorAll(".ant-picker-dropdown,.ant-picker-panel-container,.ant-picker-datetime-panel")]
        .filter(visible);
      const scoped = (selector) => dropdowns.flatMap((root) => {
        try { return [...root.querySelectorAll(selector)]; } catch { return []; }
      }).filter(visible);
      const day = expected.date.slice(8, 10);
      const dayTarget = scoped(".ant-picker-cell-in-view,td")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), title: clean(el.getAttribute("title") || el.getAttribute("aria-label") || "") }))
        .find((item) => item.title.includes(expected.date) || item.text === String(Number(day)) || item.text === day);
      if (dayTarget) {
        actions.push({ clicked: "kuaishou_day", label: dayTarget.title || dayTarget.text, ok: click(dayTarget.el) });
        await sleep(200);
      }
      const [hourRaw, minuteRaw] = expected.time.split(":");
      for (const [kind, wanted] of [["hour", String(Number(hourRaw))], ["minute", minuteRaw]]) {
        const cells = scoped(".ant-picker-time-panel-cell-inner")
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), column: clean(el.closest(".ant-picker-time-panel-column")?.innerText || "") }));
        const target = cells.find((item) => item.text === wanted || item.text === wanted.padStart(2, "0"));
        if (target) {
          actions.push({ clicked: "kuaishou_" + kind, label: target.text, ok: click(target.el) });
          await sleep(200);
        }
      }
      const okButton = scoped(".ant-picker-ok button,button,[role=button]")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "确定" || /^OK$/i.test(item.text))
        .sort((left, right) => left.area - right.area)[0];
      if (okButton) {
        actions.push({ clicked: "kuaishou_picker_ok", label: okButton.text, ok: click(okButton.el) });
        await sleep(500);
      }
      const text = clean(document.body.innerText || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 60),
      };
    })()`, 12000);
  }
  if (platform === "toutiao") {
    return evaluateWithClient(client, `(async () => {
      const expected = ${JSON.stringify({
        display: schedule.display,
        date: schedule.display.slice(0, 10),
        dateLabel: `${schedule.display.slice(5, 7)}月${schedule.display.slice(8, 10)}日`,
        hour: String(Number(schedule.display.slice(11, 13))),
        minute: String(Number(schedule.display.slice(14, 16))),
        time: schedule.display.slice(11, 16),
      })};
      const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const click = (el) => {
        if (!el) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        const rect = el.getBoundingClientRect();
        const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
        return true;
      };
      const actions = [];
      const dialogs = [...document.querySelectorAll(".Dialog-container,.m-xigua-dialog")]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), z: Number(getComputedStyle(el).zIndex || 0), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .sort((left, right) => right.z - left.z || left.area - right.area);
      for (const dialog of dialogs) {
        if (/完成后无法继续编辑/.test(dialog.text)) {
          const confirm = [...dialog.el.querySelectorAll("button,[role=button],span,div")]
            .filter(visible)
            .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
            .filter((item) => item.text === "确定" || item.text === "确认")
            .sort((left, right) => left.area - right.area)[0];
          actions.push({ clicked: "toutiao_blocking_completion_confirm", ok: click(confirm?.el), dialog: dialog.text.slice(0, 80) });
          await sleep(600);
        } else if (/封面编辑/.test(dialog.text)) {
          const ok = [...dialog.el.querySelectorAll("button,[role=button],span,div")]
            .filter(visible)
            .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height, y: el.getBoundingClientRect().top }))
            .filter((item) => item.text === "确定")
            .sort((left, right) => left.area - right.area || right.y - left.y)[0];
          actions.push({ clicked: "toutiao_cover_editor_ok", ok: click(ok?.el), dialog: dialog.text.slice(0, 80) });
          await sleep(900);
        }
      }
      const openSchedule = async () => {
        let modal = [...document.querySelectorAll(".byte-modal-wrapper,[role=dialog]")]
          .filter(visible)
          .find((el) => /定时发布/.test(clean(el.innerText || el.textContent)));
        if (modal) return modal;
        const footerButton = [...document.querySelectorAll("button,[role=button],span,div")]
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), className: clean(typeof el.className === "string" ? el.className : ""), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height, y: el.getBoundingClientRect().top }))
          .filter((item) => item.text === "定时发布" && /action-footer-btn|timer|byte-btn/.test(item.className))
          .sort((left, right) => left.area - right.area || right.y - left.y)[0];
        actions.push({ clicked: "toutiao_schedule_footer_entry", ok: click(footerButton?.el), label: footerButton?.text || "" });
        await sleep(900);
        modal = [...document.querySelectorAll(".byte-modal-wrapper,[role=dialog]")]
          .filter(visible)
          .find((el) => /定时发布/.test(clean(el.innerText || el.textContent)));
        return modal;
      };
      const modal = await openSchedule();
      const selectOption = async (selector, wanted, label) => {
        if (!modal) {
          actions.push({ select: label, ok: false, reason: "missing_toutiao_schedule_modal" });
          return false;
        }
        const select = modal.querySelector(selector);
        actions.push({ clicked: label + "_select", ok: click(select), current: clean(select?.innerText || select?.textContent) });
        await sleep(500);
        const roots = [...document.querySelectorAll(".byte-select-popup,.byte-select-dropdown,.byte-select-option-list,[class*=select-popup],[class*=select-dropdown],[class*=select-option]")]
          .filter(visible);
        const options = roots.flatMap((root) => [...root.querySelectorAll("li,div,span,[role=option]")])
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
          .filter((item) => item.text && item.text.length <= 40)
          .sort((left, right) => left.area - right.area);
        const target = options.find((item) => item.text === wanted || item.text === wanted.padStart(2, "0") || item.text === String(Number(wanted)) || item.text.includes(wanted));
        actions.push({ clicked: label + "_option", wanted, ok: click(target?.el), candidates: options.slice(0, 30).map((item) => item.text) });
        await sleep(500);
        return Boolean(target);
      };
      await selectOption(".day-select,.day-select .byte-select-view", expected.dateLabel, "toutiao_day");
      await selectOption(".hour-select,.hour-select .byte-select-view", expected.hour, "toutiao_hour");
      await selectOption(".minute-select,.minute-select .byte-select-view", expected.minute, "toutiao_minute");
      const updatedModal = await openSchedule();
      const confirm = [...(updatedModal ? updatedModal.querySelectorAll("button,[role=button]") : [])]
        .filter(visible)
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === "定时发布" || item.text === "确定")
        .sort((left, right) => left.area - right.area)[0];
      if (confirm) {
        actions.push({ clicked: "toutiao_timer_confirm", label: confirm.text, ok: click(confirm.el) });
        await sleep(1200);
      }
      const text = clean(document.body.innerText || "");
      return {
        set: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)) || text.includes(expected.dateLabel) && text.includes(expected.hour) && text.includes(expected.minute),
        expected,
        body_after_had_schedule: text.includes(expected.display) || (text.includes(expected.date) && text.includes(expected.time)),
        actions,
        relevant_text: text.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|19:30|20:00|21:00|05月/.test(line)).slice(0, 80),
      };
    })()`, 45000);
  }
  return evaluateWithClient(client, `(async () => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ display: schedule.display, date: schedule.display.slice(0, 10), time: schedule.display.slice(11, 16) })};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const setValue = (el, value) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
      if (setter) setter.call(el, value);
      else el.value = value;
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
      return true;
    };
    const actions = [];
    const bodyBefore = clean(document.body.innerText || "");
    if (platform === "x") {
      const scheduleButton = [...document.querySelectorAll('[data-testid="scheduleOption"], [aria-label*="Schedule" i], button')]
        .filter(visible)
        .find((el) => /schedule/i.test(clean([el.getAttribute("data-testid"), el.getAttribute("aria-label"), el.innerText, el.textContent].join(" "))));
      if (scheduleButton) {
        actions.push({ clicked: "x_schedule_button", ok: click(scheduleButton), label: clean(scheduleButton.getAttribute("aria-label") || scheduleButton.innerText || scheduleButton.textContent) });
        await sleep(900);
      }
    }
    const clickSemanticLabel = async (label) => {
      const target = [...document.querySelectorAll("button,[role=button],label,span,div")]
        .filter(visible)
        .map((el) => {
          const text = clean(el.innerText || el.textContent);
          const rect = el.getBoundingClientRect();
          const control = el.closest("label,[role=radio],[role=checkbox],[role=switch],[class*=radio],[class*=switch],[class*=schedule],[class*=time]") || el.parentElement || el;
          return { el, control, text, area: rect.width * rect.height };
        })
        .filter((item) => item.text === label || (item.text.includes(label) && item.text.length <= 120))
        .sort((left, right) => left.area - right.area)[0];
      if (target) {
        actions.push({ clicked: label, ok: click(target.control || target.el), label: target.text.slice(0, 80) });
        await sleep(600);
      }
    };
    for (const label of ["定时发布", "发布时间", "预约", "安排时间", "Schedule post"]) {
      await clickSemanticLabel(label);
    }
    const inputs = [...document.querySelectorAll("input")]
      .filter(visible)
      .map((el) => ({ el, text: clean([el.placeholder, el.getAttribute("aria-label"), el.value, el.closest("label")?.innerText, el.parentElement?.innerText].join(" ")) }));
    for (const item of inputs) {
      if (/日期|时间|发布|date|time/i.test(item.text)) {
        if (/日期|date/i.test(item.text)) actions.push({ set: "date", ok: setValue(item.el, expected.date), hint: item.text.slice(0, 80) });
        else actions.push({ set: "time", ok: setValue(item.el, expected.time), hint: item.text.slice(0, 80) });
      }
    }
    const selects = [...document.querySelectorAll("select")].filter(visible);
    for (const select of selects) {
      const label = clean([select.getAttribute("aria-label"), select.name, select.id, select.parentElement?.innerText].join(" "));
      const options = [...select.options].map((option) => ({ value: option.value, text: clean(option.textContent) }));
      let chosen = "";
      if (/year|年/i.test(label)) chosen = options.find((option) => option.text.includes(expected.date.slice(0, 4)) || option.value.includes(expected.date.slice(0, 4)))?.value || "";
      else if (/month|月/i.test(label)) chosen = options.find((option) => /May|五月|5月|^5$/.test(option.text) || option.value === "5" || option.value === "4")?.value || "";
      else if (/day|日|天/i.test(label)) chosen = options.find((option) => option.text === String(Number(expected.date.slice(8, 10))) || option.value === String(Number(expected.date.slice(8, 10))) || option.text === expected.date.slice(8, 10))?.value || "";
      else if (/hour|时/i.test(label)) chosen = options.find((option) => option.text === expected.time.slice(0, 2) || option.text === String(Number(expected.time.slice(0, 2))) || option.value === expected.time.slice(0, 2) || option.value === String(Number(expected.time.slice(0, 2))))?.value || "";
      else if (/minute|分/i.test(label)) chosen = options.find((option) => option.text === expected.time.slice(3, 5) || option.value === expected.time.slice(3, 5))?.value || "";
      if (chosen !== "") {
        select.value = chosen;
        select.dispatchEvent(new Event("input", { bubbles: true }));
        select.dispatchEvent(new Event("change", { bubbles: true }));
        actions.push({ set_select: label.slice(0, 80), value: chosen });
        await sleep(200);
      }
    }
    const pickerRoots = [...document.querySelectorAll([
      ".ant-picker-dropdown",
      ".ant-picker-panel-container",
      ".ant-picker-datetime-panel",
      ".ant-picker-time-panel",
      "[class*=picker]",
      "[class*=calendar]",
      "[class*=date]",
      "[class*=time]",
      "[role=dialog]",
      "[class*=modal]",
      "[class*=popover]",
    ].join(","))].filter(visible);
    const queryPicker = (selector) => pickerRoots.flatMap((root) => {
      try { return [...root.querySelectorAll(selector)]; } catch { return []; }
    }).filter(visible);
    if (platform === "kuaishou") {
      const day = expected.date.slice(8, 10);
      const dayTarget = queryPicker(".ant-picker-cell-in-view, td, button, [role=button], div, span")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent || el.getAttribute("title") || el.getAttribute("aria-label")), title: clean(el.getAttribute("title") || el.getAttribute("aria-label") || ""), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.title.includes(expected.date) || item.text === String(Number(day)) || item.text === day)
        .sort((left, right) => left.area - right.area)[0];
      if (dayTarget) {
        actions.push({ clicked: "kuaishou_day", label: dayTarget.text || dayTarget.title, ok: click(dayTarget.el) });
        await sleep(250);
      }
    }
    const hour = String(Number(expected.time.slice(0, 2)));
    const minute = expected.time.slice(3, 5);
    const wantedTexts = [expected.date, expected.time, hour, expected.time.slice(0, 2), minute, "确定"];
    for (const wanted of wantedTexts) {
      const target = queryPicker("button,[role=button],li,span,div,td")
        .map((el) => ({ el, text: clean(el.innerText || el.textContent), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }))
        .filter((item) => item.text === wanted || (wanted.length >= 5 && item.text.includes(wanted)))
        .sort((left, right) => left.area - right.area)[0];
      if (target && target.area < 100000) {
        actions.push({ clicked: wanted, label: target.text.slice(0, 80), ok: click(target.el) });
        await sleep(350);
      }
    }
    const bodyAfter = clean(document.body.innerText || "");
    return {
      set: bodyAfter.includes(expected.display) || (bodyAfter.includes(expected.date) && bodyAfter.includes(expected.time)) || /定时发布|发布时间/.test(bodyAfter),
      expected,
      body_before_had_schedule: bodyBefore.includes(expected.display) || bodyBefore.includes(expected.date),
      body_after_had_schedule: bodyAfter.includes(expected.display) || (bodyAfter.includes(expected.date) && bodyAfter.includes(expected.time)),
      actions: actions.slice(0, 40),
      relevant_text: bodyAfter.split(/[\\n\\r]+| {2,}/).map(clean).filter((line) => /定时|发布时间|预约|确定|2026|20:00|21:00|11:30/.test(line)).slice(0, 80),
    };
  })()`, 25000);
}

async function setPlatformRichText(client, platform, title, body) {
  const titleValue = String(title || "").trim();
  const bodyValue = String(body || "").trim();
  if (!titleValue && !bodyValue) return { filled: false, reason: "empty_value" };
  if (platform === "toutiao") {
    return evaluateWithClient(client, `(() => {
      const expected = ${JSON.stringify({ title: titleValue, body: bodyValue })};
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
      };
      const setValue = (el, value) => {
        if (!el || !value) return false;
        el.scrollIntoView({ block: "center", inline: "center" });
        el.focus();
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true }));
        return true;
      };
      const fieldInfo = (el) => {
        let parent = el.parentElement;
        const parts = [el.placeholder, el.getAttribute("aria-label"), el.value];
        for (let i = 0; i < 4 && parent; i += 1, parent = parent.parentElement) parts.push(parent.innerText || "");
        return clean(parts.join(" "));
      };
      const actions = [];
      const inputs = [...document.querySelectorAll("input[type=text],input:not([type])")].filter(visible).map((el) => ({ el, text: fieldInfo(el), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }));
      const titleTarget = inputs
        .filter((item) => /标题|1.?30|30/.test(item.text) && !/话题|标签/.test(item.text))
        .sort((left, right) => right.area - left.area)[0] || inputs.find((item) => /请输入/.test(item.text) && !/话题|标签/.test(item.text));
      if (titleTarget) actions.push({ field: "title", ok: setValue(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
      const textareas = [...document.querySelectorAll("textarea")].filter(visible).map((el) => ({ el, text: fieldInfo(el), area: el.getBoundingClientRect().width * el.getBoundingClientRect().height }));
      const bodyTarget = textareas.find((item) => /简介|视频简介|描述/.test(item.text)) || textareas.sort((left, right) => right.area - left.area)[0];
      if (bodyTarget) actions.push({ field: "body", ok: setValue(bodyTarget.el, expected.body), hint: bodyTarget.text.slice(0, 120) });
      const text = clean(document.body.innerText || "");
      return {
        filled: actions.some((item) => item.ok),
        actions,
        verified_body: !expected.body || text.includes(expected.body.slice(0, Math.min(20, expected.body.length))),
        verified_title: !expected.title || text.includes(expected.title),
        candidates: [...inputs, ...textareas].slice(0, 16).map((item) => ({ text: item.text.slice(0, 120), area: item.area, tag: item.el.tagName.toLowerCase() })),
      };
    })()`, 30000);
  }
  return evaluateWithClient(client, `(() => {
    const platform = ${JSON.stringify(platform)};
    const expected = ${JSON.stringify({ title: titleValue, body: bodyValue })};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const setEditable = (el, value) => {
      if (!el || !value) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
        try {
          const selection = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(el);
          selection.removeAllRanges();
          selection.addRange(range);
          document.execCommand("insertText", false, value);
        } catch {
          el.textContent = value;
        }
        if (!clean(el.innerText || el.textContent).includes(value.slice(0, Math.min(20, value.length)))) {
          el.innerHTML = "";
          for (const [index, line] of value.split(/\\n/).entries()) {
            if (index) el.appendChild(document.createElement("br"));
            el.appendChild(document.createTextNode(line));
          }
        }
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      }
      el.dispatchEvent(new Event("change", { bubbles: true }));
      el.dispatchEvent(new Event("blur", { bubbles: true }));
      return true;
    };
    const editables = [...document.querySelectorAll("textarea,input[type=text],[contenteditable=true],div[role=textbox],div[data-testid=tweetTextarea_0]")]
      .filter(visible)
      .map((el) => ({
        el,
        text: clean([el.placeholder, el.getAttribute("aria-label"), el.getAttribute("data-testid"), el.value, el.innerText, el.closest("label")?.innerText, el.parentElement?.innerText].join(" ")),
        area: el.getBoundingClientRect().width * el.getBoundingClientRect().height,
      }))
      .filter((item) => item.area > 1000)
      .sort((left, right) => right.area - left.area);
    const actions = [];
    const bodyPatterns = platform === "x"
      ? [/tweetTextarea|Post text|What is happening|有什么新鲜事|发布/i]
      : platform === "wechat-channels"
        ? [/视频描述|描述|话题|发表动态/i]
        : platform === "kuaishou"
          ? [/作品描述|描述|智能文案|话题/i]
          : platform === "xiaohongshu"
            ? [/正文|描述|话题|更多|1000|笔记/i]
            : [/简介|描述|说明|正文|视频简介/i];
    const titlePatterns = [/标题|title/i];
    const titleTarget = expected.title
      ? editables.find((item) => titlePatterns.some((pattern) => pattern.test(item.text)) && item.el.tagName === "INPUT")
        || (platform === "toutiao" ? editables.find((item) => item.el.tagName === "INPUT" && /1～30|1-30|30 个字符|标题/.test(item.text)) : null)
        || (platform === "xiaohongshu" ? editables.find((item) => item.el.tagName === "INPUT" && /标题|更多赞/.test(item.text)) : null)
      : null;
    if (titleTarget) actions.push({ field: "title", ok: setEditable(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
    const bodyCandidates = platform === "xiaohongshu"
      ? editables.filter((item) => item.el.tagName !== "INPUT" || item.el.isContentEditable || item.el.getAttribute("contenteditable") === "true")
      : editables;
    const bodyTarget =
      bodyCandidates.find((item) => bodyPatterns.some((pattern) => pattern.test(item.text))) ||
      bodyCandidates.find((item) => item.el.isContentEditable || item.el.getAttribute("contenteditable") === "true" || item.el.tagName === "TEXTAREA") ||
      bodyCandidates[0];
    if (bodyTarget) actions.push({ field: "body", ok: setEditable(bodyTarget.el, expected.body || expected.title), hint: bodyTarget.text.slice(0, 120), tag: bodyTarget.el.tagName.toLowerCase() });
    if (platform === "xiaohongshu" && titleTarget) actions.push({ field: "title_reassert", ok: setEditable(titleTarget.el, expected.title), hint: titleTarget.text.slice(0, 120) });
    const text = clean(document.body.innerText || "");
    return {
      filled: actions.some((item) => item.ok),
      actions,
      verified_body: !expected.body || text.includes(expected.body.slice(0, Math.min(20, expected.body.length))),
      verified_title: !expected.title || text.includes(expected.title),
      candidates: editables.slice(0, 12).map((item) => ({ text: item.text.slice(0, 120), area: item.area, tag: item.el.tagName.toLowerCase() })),
    };
  })()`, 30000);
}

async function finalizeGenericCompositePublish(client, platform, content, integrity) {
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  if (!LIVE_PUBLISH_ENABLED) {
    return {
      status: "needs_human",
      error: { code: "live_publish_disabled", message: "复合适配器已准备草稿，但 live publish 未开启。" },
    };
  }
  if (!integrity?.verified) {
    return {
      status: "needs_human",
      error: {
        code: `${platform}_material_integrity_failed`,
        message: `复合适配器发布前读回未通过：${(integrity?.failures || []).join(", ") || "unknown"}`,
        details: integrity || {},
      },
    };
  }
  const publishTexts = platform === "youtube"
    ? (scheduled ? ["安排时间", "预约", "Schedule"] : ["发布", "Publish"])
    : platform === "x"
      ? (scheduled ? ["Schedule", "Confirm", "Post"] : ["Post"])
      : platform === "wechat-channels"
        ? (scheduled ? ["定时发表", "发表", "确认"] : ["发表", "确认"])
    : scheduled
      ? ["定时发布", "预约发布", "发布"]
      : ["发布", "发表", "提交"];
  const click = await clickPlatformFinalPublish(client, platform, publishTexts);
  await sleep(click.clicked ? 3200 : 1200);
  const secondConfirm = click.clicked
    ? await clickVisibleDialogConfirm(client, ["确认发布", "确认投稿", "确定发布", "继续发布", "确定", "确认", "发布", "提交"])
    : { clicked: false };
  if (secondConfirm.clicked) await sleep(3200);
  const receipt = click.clicked
    ? await waitForCompositePublishReceipt(client, platform, content, 65000)
    : { after: await readCompositeMaterialIntegrity(client, platform, content), receiptLike: false, waited_ms: 0 };
  const after = receipt.after;
  const receiptLike = receipt.receiptLike;
  return {
    status: click.clicked && receiptLike ? (scheduled ? "scheduled_pending" : "published") : "needs_human",
    result: { final_publish: { platform, scheduled, click, second_confirm: secondConfirm, receipt_wait: receipt.waited_ms, receipt_like: receiptLike, post_click_integrity: after } },
    error: click.clicked && receiptLike
      ? null
      : { code: `${platform}_final_publish_unconfirmed`, message: "已由复合适配器处理最终发布，但没有读到可靠成功回执。", details: { click, second_confirm: secondConfirm, after } },
  };
}

async function runCompositePhase(platform, phase, fn) {
  try {
    return await fn();
  } catch (error) {
    error.publicationPlatform = platform;
    error.publicationPhase = phase;
    error.message = `${platform}:${phase}: ${error.message}`;
    throw error;
  }
}

async function waitForCompositePublishReceipt(client, platform, content, timeoutMs = 60000) {
  const startedAt = Date.now();
  let after = null;
  let receiptLike = false;
  while (Date.now() - startedAt < timeoutMs) {
    after = await readCompositeMaterialIntegrity(client, platform, content);
    const receiptText = (after.platform_extras?.relevant_lines || []).join(" ");
    receiptLike = platform === "youtube"
      ? Boolean(after.platform_extras?.youtube_link || after.platform_extras?.youtube_scheduled)
      : platform === "kuaishou"
        ? /发布成功|审核中|已发布|定时发布成功|已预约|预约成功|提交成功|等待审核|已进入审核/.test(receiptText) || (/作品管理/.test(receiptText) && !/发布视频/.test(receiptText))
        : /发布成功|审核中|已发布|定时发布成功|已预约|预约成功|提交成功|作品管理|发布管理|等待审核|已进入审核/.test(receiptText);
    if (receiptLike) break;
    const confirm = await clickVisibleDialogConfirm(client, ["确认发布", "确认投稿", "确定发布", "继续发布", "确定", "确认", "发布", "提交"]);
    if (confirm.clicked) await sleep(3200);
    else await sleep(2500);
  }
  return { after, receiptLike, waited_ms: Date.now() - startedAt };
}

async function runCompositePlatformAdapter(client, tab, platform, content, inheritedActions = []) {
  const actions = [...inheritedActions];
  const framework = PLATFORM_COMPOSITE_FRAMEWORKS[platform] || (COMPOSITE_PUBLISH_PLATFORMS.has(platform) ? null : { id: "generic_composite_fallback_v1", prepare: prepareGenericCompositeDraft });
  if (!framework) {
    return {
      status: "needs_human",
      result: {
        platform,
        composite_framework: {
          enabled: true,
          platform,
          framework_id: "",
          dedicated_platform_framework: false,
          legacy_lightweight_script_used: false,
        },
      },
      error: {
        code: "dedicated_composite_framework_missing",
        message: `${platform} 属于全平台发布链路，但没有注册专用复合框架，已停止以避免退回旧轻量脚本。`,
      },
    };
  }
  const usedFallbackFramework = framework.id === "generic_composite_fallback_v1";
  actions.push(...(await runCompositePhase(platform, `prepare_${framework.id}`, () => framework.prepare(client, platform, content))));
  await sleep(1200);
  const integrity = await runCompositePhase(platform, "pre_publish_material_integrity", () => readCompositeMaterialIntegrity(client, platform, content));
  const snapshot = await runCompositePhase(platform, "pre_publish_page_snapshot", () => pageSnapshot(client));
  const result = {
    draft_url: snapshot.url || tab.url || "",
    route: { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" },
    composite_framework: {
      enabled: true,
      platform,
      framework_id: framework.id,
      dedicated_platform_framework: !usedFallbackFramework,
      legacy_lightweight_script_used: false,
      material_integrity: integrity,
    },
    publication_audit: buildCompositePublicationAudit(platform, content, integrity, {}, { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" }),
    actions: actions.slice(0, 120),
    visible_option_lines: (snapshot.lines || [])
      .filter((line) => /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category|封面|缩略图/i.test(line))
      .slice(0, 160),
  };

  if (platform === "youtube") {
    const youtubeVideoId = String(snapshot.url || "").match(/\/video\/([A-Za-z0-9_-]+)\/edit/)?.[1] || "";
    const youtubeReceipt = integrity.platform_extras?.youtube_link || (youtubeVideoId ? `https://youtu.be/${youtubeVideoId}` : "");
    if (youtubeReceipt && (integrity.platform_extras?.youtube_scheduled || /已排定时间|公开范围/.test(result.visible_option_lines.join(" ")))) {
      result.final_publish = {
        platform,
        scheduled: true,
        receipt_like: true,
        external_url: youtubeReceipt,
        material_integrity_complete: integrity.verified,
      };
      result.publication_audit = buildCompositePublicationAudit(platform, content, integrity, result.final_publish, result.route);
      return {
        status: "scheduled_pending",
        result,
        error: integrity.verified
          ? null
          : {
              code: "youtube_scheduled_but_material_integrity_failed",
              message: `YouTube 已读到预约成功回执，但发布物料读回仍未完整：${(integrity.failures || []).join(", ")}`,
              details: integrity,
            },
      };
    }
  }

  if (integrity.platform_extras?.receipt_like && integrity.verified) {
    result.final_publish = {
      platform,
      scheduled: Boolean(String(content.scheduled_publish_at || "").trim()),
      receipt_like: true,
      material_integrity_complete: true,
      receipt_route: integrity.platform_extras.route || {},
    };
    result.publication_audit = buildCompositePublicationAudit(platform, content, integrity, result.final_publish, result.route);
    return {
      status: String(content.scheduled_publish_at || "").trim() ? "scheduled_pending" : "published",
      result,
      error: null,
    };
  }

  const finalOutcome = await runCompositePhase(platform, "finalize_generic_composite_publish", () => finalizeGenericCompositePublish(client, platform, content, integrity));
  result.final_publish = finalOutcome.result?.final_publish || {};
  result.publication_audit = buildCompositePublicationAudit(platform, content, await readCompositeMaterialIntegrity(client, platform, content), result.final_publish, result.route);
  return { status: finalOutcome.status, result, error: finalOutcome.error };
}

function inferBilibiliCategory(content) {
  const explicit = [
    content.category,
    content.category_name,
    content.category_path,
    content.section,
    content.section_name,
  ]
    .map((value) => {
      if (!value) return "";
      if (typeof value === "string") return value;
      if (typeof value === "object") return value.name || value.title || value.path || value.label || "";
      return "";
    })
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  if (explicit.some((value) => value.includes("户外潮流"))) return "户外潮流";

  const sample = [
    content.title,
    content.body,
    ...(content.hashtags || []),
    ...(content.structured_tags || []),
    content.collection?.name,
    content.collection_name,
  ]
    .map((value) => String(value || ""))
    .join(" ");
  const isEdcGear = /EDC|潮玩|桌搭|推牌|把玩|刀|手电|机能|户外|装备|随身/.test(sample);
  if (isEdcGear && (!explicit.length || explicit.some((value) => /生活兴趣|生活|科技|数码/.test(value)))) {
    return "户外潮流";
  }
  return explicit[0] || "";
}

async function setBilibiliDraftFields(client, content) {
  const title = String(content.title || "").trim();
  const body = String(content.body || "").trim();
  const tags = Array.from(new Set([...(content.hashtags || []), ...(content.structured_tags || [])].map((item) => String(item || "").trim()).filter(Boolean))).slice(0, 10);
  const collection = String(content.collection?.name || content.collection_name || "").trim();
  const scheduledPublishAt = String(content.scheduled_publish_at || "").trim();
  const schedule = parseChinaLocalSchedule(scheduledPublishAt);
  const category = inferBilibiliCategory(content);
  const expression = `(async () => {
    const expected = ${JSON.stringify({ title, body, tags, collection, category, scheduledPublishAt, scheduledTimestamp: schedule.timestamp, scheduledDisplay: schedule.display })};
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
      return true;
    };
    const setInputValue = (el, value) => {
      if (!el) return false;
      el.scrollIntoView({ block: "center", inline: "center" });
      el.focus();
      if (el.isContentEditable || el.getAttribute("contenteditable") === "true") {
        el.innerHTML = "";
        const paragraph = document.createElement("p");
        paragraph.textContent = value;
        el.appendChild(paragraph);
      } else {
        const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
        if (setter) setter.call(el, value);
        else el.value = value;
      }
      el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      for (const type of ["change", "blur"]) el.dispatchEvent(new Event(type, { bubbles: true }));
      return true;
    };
    const actions = [];
    const titleInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /标题/.test(el.placeholder || ""));
    if (titleInput) actions.push({ field: "title", filled: setInputValue(titleInput, expected.title), actual: clean(titleInput.value) });

    const declarationInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /创作声明/.test(el.placeholder || ""));
    if (declarationInput) {
      actions.push({ field: "declaration", reset_before: clean(declarationInput.value) });
      if (clean(declarationInput.value) !== "内容无需标注") {
        click(declarationInput.closest(".bcc-select") || declarationInput);
        await sleep(400);
        const option = [...document.querySelectorAll(".bcc-option, .option-hover-tips, .auth-content")]
          .filter(visible)
          .find((el) => clean(el.innerText || el.textContent) === "内容无需标注");
        if (option) {
          click(option);
          await sleep(400);
        }
      }
      if (clean(declarationInput.value) !== "内容无需标注") {
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (setter) setter.call(declarationInput, "内容无需标注");
        else declarationInput.value = "内容无需标注";
        declarationInput.dispatchEvent(new Event("input", { bubbles: true }));
        declarationInput.dispatchEvent(new Event("change", { bubbles: true }));
      }
      actions.push({ field: "declaration", expected: "内容无需标注", actual: clean(declarationInput.value), selected: clean(declarationInput.value) === "内容无需标注" });
    }

    if (expected.category) {
      const categoryEl = document.querySelector(".video-human-type");
      const categoryVm = categoryEl?.__vue__;
      const before = {
        text: clean(categoryEl?.innerText || ""),
        value: categoryVm?.value,
        selected: categoryVm?._watchers?.[1]?.value || null,
      };
      const list = categoryVm?._watchers?.[0]?.value || [];
      const target = Array.isArray(list)
        ? list.find((item) => item && clean(item.name) === expected.category)
        : null;
      if (before.text.includes(expected.category) || clean(before.selected?.name || "") === expected.category) {
        // Already correct.
      } else if (categoryVm && target && typeof categoryVm.changeType === "function") {
        categoryVm.changeType(target);
        await sleep(500);
      } else {
        const categoryInput = [...document.querySelectorAll("input")].find((el) => visible(el) && /分区|分类/.test(el.placeholder || ""));
        if (categoryInput) {
          click(categoryInput.closest(".bcc-select") || categoryInput);
          await sleep(400);
          const option = [...document.querySelectorAll(".bcc-option, .bcc-select-dropdown .option, [class*=option]")]
            .filter(visible)
            .find((el) => clean(el.innerText || el.textContent) === expected.category);
          if (option) {
            click(option);
            await sleep(400);
          }
        }
      }
      const after = {
        text: clean(categoryEl?.innerText || ""),
        value: categoryVm?.value,
        selected: categoryVm?._watchers?.[1]?.value || null,
      };
      actions.push({ field: "category", expected: expected.category, before, after, selected: after.text.includes(expected.category) || clean(after.selected?.name || "") === expected.category });
    }

    const description = [...document.querySelectorAll(".archive-info-editor .ql-editor[contenteditable=true], .archive-info-editor [contenteditable=true]")]
      .filter(visible)[0];
    if (description) {
      const beforeDescription = clean(description.innerText || description.textContent);
      const filled = beforeDescription === expected.body ? true : setInputValue(description, expected.body);
      actions.push({ field: "description", filled, actual: clean(description.innerText || description.textContent), skipped_because_already_correct: beforeDescription === expected.body });
    }

    const tagWrp = [...document.querySelectorAll(".tag-container")].find((el) => clean(el.innerText).includes("标签"));
    if (tagWrp) {
      for (const close of [...tagWrp.querySelectorAll(".label-item-v2-container .close")].filter(visible).slice(0, 10)) click(close);
      const tagInput = tagWrp.querySelector('input[placeholder*="Enter"], input[placeholder*="标签"], input.input-val');
      if (tagInput) {
        const currentTags = () => [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean);
        const commitTag = async (tag) => {
          setInputValue(tagInput, tag);
          await sleep(180);
          for (const type of ["keydown", "keypress", "keyup"]) {
            tagInput.dispatchEvent(new KeyboardEvent(type, { bubbles: true, cancelable: true, key: "Enter", code: "Enter", keyCode: 13, which: 13 }));
          }
          await sleep(800);
          return currentTags().includes(tag);
        };
        if (expected.tags.every((tag) => currentTags().includes(tag))) {
          // Already correct.
        } else {
          for (const tag of expected.tags) {
            if (currentTags().includes(tag)) continue;
            let committed = false;
            for (let attempt = 0; attempt < 3 && !committed; attempt += 1) {
              committed = await commitTag(tag);
            }
          }
          await sleep(1000);
          for (const tag of expected.tags) {
            if (!currentTags().includes(tag)) {
              await commitTag(tag);
              await sleep(500);
            }
          }
        }
        if (!expected.tags.includes(clean(tagInput.value || ""))) setInputValue(tagInput, "");
      }
      const actualTags = [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean);
      actions.push({ field: "tags", expected: expected.tags, actual: actualTags });
    }

    if (expected.collection) {
      const collectionSelectCandidates = () => [...document.querySelectorAll(".video-season-select .season-select")]
        .filter(visible)
        .map((el) => ({
          el,
          text: clean(el.innerText || el.textContent),
          inDialog: Boolean(el.closest(".bcc-dialog, .bcc-dialog__wrap, .batch-add-season, .batch-fill")),
          inForm: Boolean(el.closest(".form, .form-item")),
        }));
      const collectionTextsBefore = collectionSelectCandidates().map((item) => item.text).filter(Boolean);
      const collectionSelect =
        collectionSelectCandidates().find((item) => item.text.includes(expected.collection))?.el ||
        collectionSelectCandidates().find((item) => item.inForm && !item.inDialog)?.el ||
        collectionSelectCandidates().find((item) => !item.inDialog)?.el ||
        collectionSelectCandidates()[0]?.el;
      const before = clean(collectionSelect?.innerText || "");
      if (collectionSelect && !collectionTextsBefore.some((text) => text.includes(expected.collection))) {
        click(collectionSelect);
        await sleep(600);
        const option = [...document.querySelectorAll(".bcc-option, .season-list .season-item, .video-season-select [class*=option], [class*=season] [class*=item]")]
          .filter(visible)
          .find((el) => clean(el.innerText || el.textContent).includes(expected.collection));
        if (option) {
          click(option);
          await sleep(500);
        }
      }
      const collectionTextsAfter = collectionSelectCandidates().map((item) => item.text).filter(Boolean);
      const selectedCollection = collectionTextsAfter.find((text) => text.includes(expected.collection)) || collectionTextsAfter.find((text) => !/请选择合集/.test(text)) || collectionTextsAfter[0] || "";
      actions.push({ field: "collection", expected: expected.collection, before, candidates_before: collectionTextsBefore, actual: selectedCollection, candidates_after: collectionTextsAfter, selected: selectedCollection.includes(expected.collection) });
    }

    if (expected.scheduledPublishAt) {
      const switchEl = document.querySelector(".time-switch-wrp .switch-container, .time-switch-wrp [class*=switch]");
      const before = clean(document.querySelector(".time-switch-wrp")?.innerText || "");
      const switchVm = document.querySelector(".time-switch-wrp .switch-container")?.__vue__;
      if (!before.includes(expected.scheduledDisplay)) {
        if (switchVm && !switchVm.active && typeof switchVm.handleSet === "function") switchVm.handleSet();
        else if (switchEl && !/\\d{4}|\\d{2}:\\d{2}/.test(before)) click(switchEl);
        await sleep(500);
        const timeVm = document.querySelector(".d-time-container")?.__vue__;
        if (timeVm && expected.scheduledTimestamp && typeof timeVm.setDTime === "function") {
          timeVm.setDTime(expected.scheduledTimestamp);
          await sleep(400);
        }
      }
      const after = clean(document.querySelector(".time-container")?.innerText || document.querySelector(".time-switch-wrp")?.innerText || "");
      actions.push({ field: "schedule", expected: expected.scheduledDisplay || expected.scheduledPublishAt, before, after, expanded: /\\d{4}|\\d{2}:\\d{2}/.test(after) });
    }

    const actual = {
      title: clean(titleInput?.value || ""),
      declaration: clean(declarationInput?.value || ""),
      category: clean(document.querySelector(".video-human-type")?.innerText || ""),
      description: clean(description?.innerText || description?.textContent || ""),
      tags: tagWrp ? [...tagWrp.querySelectorAll(".label-item-v2-content")].map((el) => clean(el.innerText || el.textContent)).filter(Boolean) : [],
      collection: (() => {
        const texts = [...document.querySelectorAll(".video-season-select .season-select")]
          .filter(visible)
          .map((el) => clean(el.innerText || el.textContent))
          .filter(Boolean);
        return expected.collection && texts.some((text) => text.includes(expected.collection))
          ? expected.collection
          : (texts.find((text) => !/请选择合集/.test(text)) || texts[0] || "");
      })(),
      scheduleText: clean(document.querySelector(".time-container")?.innerText || document.querySelector(".time-switch-wrp")?.innerText || ""),
    };
    const failures = [];
    if (expected.title && actual.title !== expected.title) failures.push("title");
    if (actual.declaration !== "内容无需标注") failures.push("declaration");
    if (expected.category && !actual.category.includes(expected.category)) failures.push("category");
    if (expected.body && actual.description !== expected.body) failures.push("description");
    for (const tag of expected.tags) if (!actual.tags.includes(tag)) failures.push(\`tag:\${tag}\`);
    if (expected.collection && !actual.collection.includes(expected.collection)) failures.push("collection");
    if (expected.scheduledDisplay && !actual.scheduleText.includes(expected.scheduledDisplay)) failures.push("schedule");
    return { platform: "bilibili", actions, actual, verified: failures.length === 0, failures };
  })()`;
  return evaluateWithClient(client, expression, 120000);
}

async function setBilibiliCoverImage(client, coverPath) {
  const expectedCoverPath = String(coverPath || "").trim();
  if (!expectedCoverPath) return { field: "cover", uploaded: false, reason: "missing_cover_path" };
  const openEditor = await evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const cover = document.querySelector(".cover");
    const scrollables = [document.scrollingElement, ...document.querySelectorAll("*")].filter((el) => el && el.scrollHeight > el.clientHeight + 20);
    for (const scroller of scrollables) {
      try { scroller.scrollTop = Math.max(0, (cover?.offsetTop || 450) - 120); } catch {}
    }
    cover?.scrollIntoView({ block: "center", inline: "center" });
    await sleep(400);
    const candidates = [...document.querySelectorAll(".edit-text,.cover-img,.cover-main,.cover-item")]
      .filter(visible)
      .map((el) => ({ el, text: clean(el.innerText || el.textContent), className: String(el.className || "") }));
    const target = candidates.find((item) => item.text === "封面设置") || candidates.find((item) => /cover-img|cover-main/.test(item.className));
    if (!target) return { opened: false, reason: "cover_setting_entry_not_found", candidates: candidates.map((item) => ({ text: item.text, className: item.className })).slice(0, 20) };
    click(target.el);
    await sleep(1500);
    return { opened: /封面制作|上传封面|4:3封面预览|首页推荐封面/.test(document.body.innerText || ""), target: { text: target.text, className: target.className } };
  })()`, 20000);
  if (!openEditor.opened) return { field: "cover", uploaded: false, ...openEditor };

  const documentResult = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  const queryResult = await client.send("DOM.querySelectorAll", { nodeId: documentResult.root.nodeId, selector: "input[type=file]" });
  const inputs = [];
  for (const nodeId of queryResult.nodeIds || []) {
    const description = await client.send("DOM.describeNode", { nodeId });
    const attrs = description.node?.attributes || [];
    const attrMap = {};
    for (let index = 0; index < attrs.length; index += 2) attrMap[attrs[index]] = attrs[index + 1] || "";
    inputs.push({ nodeId, attrMap });
  }
  const imageInput = inputs.find((item) => /image|png|jpe?g/i.test(item.attrMap.accept || ""));
  if (!imageInput) {
    return { field: "cover", uploaded: false, opened: true, reason: "cover_image_input_not_found", fileInputs: inputs.map((item) => item.attrMap) };
  }
  await client.send("DOM.setFileInputFiles", { nodeId: imageInput.nodeId, files: [expectedCoverPath] });
  await sleep(4000);
  const closeEditor = await evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled;
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const buttons = [...document.querySelectorAll("button,[role=button],.bcc-button,span,div")].filter(visible);
    const done = buttons.find((el) => clean(el.innerText || el.textContent || el.value) === "完成")
      || buttons.find((el) => clean(el.innerText || el.textContent || el.value) === "确定");
    if (done) {
      click(done);
      await sleep(2500);
    }
    const body = document.body.innerText || "";
    return {
      clicked_done: Boolean(done),
      editor_still_open: /封面制作|上传封面|4:3封面预览|首页推荐封面/.test(body),
      page_cover_text: clean(document.querySelector(".cover")?.innerText || ""),
    };
  })()`, 20000);
  return {
    field: "cover",
    expected_path: expectedCoverPath,
    uploaded: Boolean(closeEditor.clicked_done && !closeEditor.editor_still_open),
    opened: true,
    image_input: imageInput.attrMap,
    ...closeEditor,
  };
}

async function handleBilibiliSecondConfirmation(client) {
  return evaluateWithClient(client, `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden" && !el.disabled && el.getAttribute("aria-disabled") !== "true";
    };
    const click = (el) => {
      el.scrollIntoView({ block: "center", inline: "center" });
      const rect = el.getBoundingClientRect();
      const eventInit = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
      for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, eventInit));
    };
    const bodyText = clean(document.body.innerText || "");
    const detected = /发布前请添加创作声明|根据相关法律法规要求|内容无需标注|去声明/.test(bodyText);
    const actions = [];
    if (!detected) return { detected: false, actions };
    const clickText = async (texts) => {
      const modal = [...document.querySelectorAll(".videoup-confirm-modal, .bcc-dialog__wrap, .bcc-dialog")]
        .filter(visible)
        .sort((left, right) => {
          const leftRect = left.getBoundingClientRect();
          const rightRect = right.getBoundingClientRect();
          return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
        })[0] || document;
      for (const text of texts) {
        const item = [...modal.querySelectorAll("button,[role=button],input[type=button],input[type=submit],a")]
          .filter(visible)
          .map((el) => ({ el, text: clean(el.innerText || el.textContent || el.value), className: String(el.className || "") }))
          .filter((item) => item.text === text || item.text.includes(text))
          .sort((left, right) => {
            const leftRect = left.el.getBoundingClientRect();
            const rightRect = right.el.getBoundingClientRect();
            const leftExact = left.text === text ? 0 : 1;
            const rightExact = right.text === text ? 0 : 1;
            if (leftExact !== rightExact) return leftExact - rightExact;
            return (leftRect.width * leftRect.height) - (rightRect.width * rightRect.height);
          })[0];
        if (item) {
          click(item.el);
          if (typeof item.el.click === "function") item.el.click();
          await sleep(2200);
          return { clicked: true, requested: text, label: item.text, className: item.className };
        }
      }
      return { clicked: false };
    };
    actions.push({ kind: "select_declaration", ...(await clickText(["内容无需标注"])) });
    await sleep(3000);
    return {
      detected: true,
      actions,
      still_visible: /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(clean(document.body.innerText || "")),
    };
  })()`, 25000);
}

async function finalizeBilibiliPublish(client, content) {
  const scheduled = Boolean(String(content.scheduled_publish_at || "").trim());
  const publishTexts = scheduled
    ? ["定时投稿", "预约投稿", "定时发布", "投稿"]
    : ["立即投稿", "发布", "投稿"];
  const confirmTexts = ["确定", "确认", "确认投稿", "确定发布", "我知道了"];
  const actions = [];
  const firstClick = await clickFinalPublishByText(client, publishTexts);
  actions.push({ kind: "final_publish_click", ...firstClick });
  if (!firstClick.clicked) {
    return {
      status: "needs_human",
      actions,
      error: {
        code: "bilibili_final_publish_button_not_found",
        message: "B站字段已校验通过，但没有找到最终投稿/定时投稿按钮。",
      },
    };
  }
  await sleep(1800);
  const secondConfirmation = await handleBilibiliSecondConfirmation(client);
  actions.push({ kind: "second_confirmation", ...secondConfirmation });
  const confirmClick = secondConfirmation.detected ? { clicked: false, skipped: true, reason: "handled_by_second_confirmation" } : await clickFinalPublishByText(client, confirmTexts);
  actions.push({ kind: "final_confirm_click", ...confirmClick });
  await sleep(confirmClick.clicked ? 3000 : 1800);
  const snapshot = await pageSnapshot(client);
  const lines = (snapshot.lines || []).slice(0, 240);
  const joined = lines.join(" ");
  const finalConfirmationStillVisible = /发布前请添加创作声明|根据相关法律法规要求|去声明/.test(joined);
  const publishFormStillVisible = /立即投稿|存草稿|发布视频/.test(joined) && /封面设置|创作声明|定时发布/.test(joined);
  const successLike = /投稿成功|发布成功|已预约|定时发布成功|稿件已提交|审核中|等待审核|已进入审核|发布管理|内容管理|稿件管理/.test(joined)
    && !finalConfirmationStillVisible
    && !publishFormStillVisible;
  return {
    status: successLike ? (scheduled ? "scheduled_pending" : "published") : "needs_human",
    result: {
      final_publish: {
        platform: "bilibili",
        scheduled,
        actions,
        success_like: successLike,
        publish_form_still_visible: publishFormStillVisible,
        final_confirmation_still_visible: finalConfirmationStillVisible,
        route: { url: snapshot.url || "", title: snapshot.title || "" },
        visible_lines: lines.filter((line) => /投稿|发布|预约|定时|审核|成功|稿件|管理/.test(line)).slice(0, 80),
      },
    },
    error: successLike
      ? null
      : {
          code: "bilibili_final_publish_unconfirmed",
          message: publishFormStillVisible
            ? "已点击 B站最终投稿按钮，但页面仍停留在投稿表单，不能判定为发布成功。"
            : "已点击 B站最终投稿按钮，但页面没有读到成功/审核/预约回执，需要人工确认。",
        },
  };
}

async function preparePublicationTask(task) {
  const platform = normalizePlatform(task.platform);
  const content = task.content && typeof task.content === "object" ? task.content : {};
  const mediaItems = Array.isArray(content.media_items) ? content.media_items : [];
  const mediaPath =
    String(mediaItems.find((item) => item && item.local_path)?.local_path || "").trim() ||
    String((content.media_urls || [])[0] || "").trim();
  const tabs = await listCdpTabs();
  const tab = findPlatformTab(tabs, platform);
  if (!tab) {
    return {
      status: "needs_human",
      error: { code: "platform_tab_not_found", message: `没有找到 ${platform} 已打开的创作/发布页。` },
    };
  }
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  const actions = [];
  const interruptions = [];
  try {
    const routeAction = await ensurePlatformPublishRoute(client, tab, platform);
    if (routeAction.navigated) actions.push({ kind: "ensure_platform_publish_route", ...routeAction });
    if (platform === "toutiao" && routeAction.verified === false) {
      return {
        status: "needs_human",
        result: {
          platform,
          route: { url: routeAction.url || tab.url || "", title: tab.title || "" },
          actions,
          composite_framework: {
            enabled: true,
            platform,
            framework_id: PLATFORM_COMPOSITE_FRAMEWORKS.toutiao.id,
            dedicated_platform_framework: true,
            legacy_lightweight_script_used: false,
          },
        },
        error: {
          code: "toutiao_video_publish_route_not_verified",
          message: "头条专用框架未能确认进入西瓜视频上传页，已停止，避免误填文章发布页。",
          details: routeAction,
        },
      };
    }
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "task_start")));
    let snapshot = await pageSnapshot(client);
    if (mediaPath && !pageAlreadyHasMedia(snapshot, mediaPath)) {
      if (platform === "youtube") {
        actions.push(await clickByText(client, ["创建", "上传视频", "Upload videos", "CREATE"]));
        await sleep(2200);
      }
      let upload = await setFirstVideoFileInput(client, mediaPath);
      if (!upload.uploaded) {
        actions.push(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发布视频"]));
        await sleep(2200);
        upload = await setFirstVideoFileInput(client, mediaPath);
      }
      actions.push({ kind: "media_upload", ...upload });
      await sleep(upload.uploaded ? 16000 : 2500);
    } else {
      actions.push({ kind: "media_upload", uploaded: Boolean(mediaPath), skipped: true, reason: mediaPath ? "media_already_present" : "missing_media_path" });
    }
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_upload")));
    let platformVerifier = null;
    let bilibiliCoverAction = null;
    if (platform === "bilibili") {
      const coverAction = await setBilibiliCoverImage(client, content.cover_path || content.copy_material?.cover_path || "");
      bilibiliCoverAction = coverAction;
      actions.push(coverAction);
      platformVerifier = await setBilibiliDraftFields(client, content);
      actions.push(platformVerifier);
    } else {
      return await runCompositePlatformAdapter(client, tab, platform, content, actions);
    }
    const postFillExpandTexts = platform === "bilibili" ? [] : (PLATFORM_EXPAND_TEXTS[platform] || ["更多设置", "展开"]);
    for (const text of postFillExpandTexts) {
      const action = await clickByText(client, [text]);
      actions.push(action);
      if (action.clicked) {
        await sleep(900);
        interruptions.push(...(await dismissInterruptions(client, tab, platform, `task_expand_${text}`)));
      }
    }
    snapshot = await pageSnapshot(client);
    const result = {
      draft_url: snapshot.url || tab.url || "",
      route: { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" },
      composite_framework: platform === "bilibili"
        ? {
            enabled: true,
            platform,
            framework_id: dedicatedCompositeFrameworkId("bilibili"),
            dedicated_platform_framework: true,
            legacy_lightweight_script_used: false,
            material_integrity: platformVerifier || {},
          }
        : undefined,
      publication_audit: platform === "bilibili"
        ? buildBilibiliPublicationAudit(content, platformVerifier, {}, { url: snapshot.url || tab.url || "", title: snapshot.title || tab.title || "" }, bilibiliCoverAction)
        : undefined,
      actions: actions.slice(0, 80),
      interruptions: interruptions.slice(0, 80),
      visible_option_lines: (snapshot.lines || [])
        .filter((line) => /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category/i.test(line))
        .slice(0, 120),
    };
    if (!LIVE_PUBLISH_ENABLED) {
      return {
        status: "needs_human",
        result,
        error: {
          code: "live_publish_disabled",
          message: "任务已完成草稿准备，但 PUBLICATION_LIVE_PUBLISH_ENABLED 未开启，已停止在人工确认前。",
        },
      };
    }
    if (!FINAL_PUBLISH_PLATFORMS.has(platform)) {
      return {
        status: "needs_human",
        result,
        error: {
          code: "live_publish_executor_not_implemented",
          message: `任务已完成草稿准备，但 ${platform} 最终预约/发布点击器尚未实现，已停止在人工确认前。`,
        },
      };
    }
    if (platform === "bilibili" && !platformVerifier?.verified) {
      return {
        status: "needs_human",
        result,
        error: {
          code: "bilibili_pre_publish_verification_failed",
          message: `B站字段读回校验未通过：${(platformVerifier?.failures || []).join(", ") || "unknown"}`,
          details: platformVerifier || {},
        },
      };
    }
    if (platform === "bilibili") {
      const finalOutcome = await finalizeBilibiliPublish(client, content);
      result.final_publish = finalOutcome.result?.final_publish || {};
      result.publication_audit = buildBilibiliPublicationAudit(content, platformVerifier, result.final_publish, result.route, bilibiliCoverAction);
      return {
        status: finalOutcome.status,
        result,
        error: finalOutcome.error,
      };
    }
    return {
      status: "needs_human",
      result,
      error: {
        code: "live_publish_executor_not_implemented",
        message: "任务已完成草稿准备，但该平台最终预约/发布点击器尚未实现，已停止在人工确认前。",
      },
    };
  } finally {
    client.close();
  }
}

function serializeTask(task) {
  return {
    task_id: task.task_id,
    id: task.task_id,
    platform: task.platform,
    profile_id: task.profile_id,
    status: task.status,
    created_at: task.created_at,
    updated_at: task.updated_at,
    scheduled_publish_at: task.content?.scheduled_publish_at || null,
    result: task.result || {},
    error: task.error || null,
  };
}

function startPublicationTask(payload) {
  const taskId = String(payload.task_id || payload.id || randomUUID()).trim();
  const task = {
    task_id: taskId,
    platform: normalizePlatform(payload.platform),
    profile_id: String(payload.profile_id || ""),
    content: payload.content && typeof payload.content === "object" ? payload.content : {},
    status: "queued",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    result: {},
    error: null,
  };
  TASKS.set(taskId, task);
  queueMicrotask(async () => {
    task.status = "processing";
    task.updated_at = new Date().toISOString();
    try {
      const outcome = await preparePublicationTask(task);
      task.status = outcome.status || "needs_human";
      task.result = outcome.result || {};
      task.error = outcome.error || null;
    } catch (error) {
      task.status = "failed";
      task.error = {
        code: "browser_agent_task_failed",
        message: error.message,
        details: {
          platform: error.publicationPlatform || task.platform,
          phase: error.publicationPhase || "unknown",
        },
      };
    } finally {
      task.updated_at = new Date().toISOString();
    }
  });
  return task;
}

const PLATFORM_EXPAND_TEXTS = {
  douyin: ["作品描述", "添加话题", "合集", "选择合集", "原创", "声明", "谁可以看", "定时发布", "高级设置", "更多设置"],
  bilibili: ["分区", "生活兴趣", "加入合集", "请选择合集", "创作声明", "更多设置"],
  xiaohongshu: ["选择合集", "原创声明", "添加内容类型声明", "选择群聊", "公开可见", "定时发布", "更多设置"],
  youtube: ["选择", "不，内容不是面向儿童的", "展开", "更多选项", "公开范围"],
  kuaishou: ["作品分类", "分类", "合集", "定时发布", "更多设置"],
  "wechat-channels": ["发表视频", "上传视频", "合集", "活动", "声明", "谁可以看", "定时发表"],
  toutiao: ["发布视频", "上传视频", "分类", "合集", "原创", "声明", "定时发布"],
  x: ["Schedule post", "Post settings"],
};

async function probeTabInventory(tab, platform, payload) {
  if (!tab.webSocketDebuggerUrl) throw new Error("tab has no webSocketDebuggerUrl");
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  const snapshots = [];
  const actions = [];
  const interruptions = [];
  const contentSample = payload.content_sample && typeof payload.content_sample === "object" ? payload.content_sample : {};
  const mediaPath = String(contentSample.media_path || "").trim();
  const allowDraftUpload = String(payload.mode || "").includes("draft_upload") && mediaPath;
  let upload = { uploaded: false, reason: allowDraftUpload ? "not_attempted" : "upload_probe_not_requested" };
  try {
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_probe")));
    if (platform === "youtube" && allowDraftUpload) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_youtube_create")));
      actions.push(await clickByText(client, ["创建", "上传视频", "Upload videos", "CREATE"]));
      await sleep(2500);
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_youtube_create")));
    }
    let current = await pageSnapshot(client);
    snapshots.push(current);
    if (allowDraftUpload && !pageAlreadyHasMedia(current, mediaPath)) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_file_upload")));
      upload = await setFirstVideoFileInput(client, mediaPath);
      if (!upload.uploaded) {
        interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_upload_button")));
        actions.push(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files", "发布视频"]));
        await sleep(2500);
        interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_upload_button")));
        upload = await setFirstVideoFileInput(client, mediaPath);
      }
      await sleep(upload.uploaded ? 18000 : 3000);
      interruptions.push(...(await dismissInterruptions(client, tab, platform, "after_file_upload")));
      current = await pageSnapshot(client);
      snapshots.push(current);
    } else if (allowDraftUpload) {
      upload = { uploaded: true, skipped: true, reason: "media_already_present" };
    }
    for (const text of PLATFORM_EXPAND_TEXTS[platform] || ["更多设置", "展开"]) {
      interruptions.push(...(await dismissInterruptions(client, tab, platform, `before_expand_${text}`)));
      const action = await clickByText(client, [text]);
      actions.push(action);
      if (action.clicked) {
        await sleep(1400);
        snapshots.push(await pageSnapshot(client));
        interruptions.push(...(await dismissInterruptions(client, tab, platform, `after_expand_${text}`)));
        snapshots.push(await pageSnapshot(client));
      }
    }
    const merged = mergedSnapshot(snapshots);
    interruptions.push(...(await dismissInterruptions(client, tab, platform, "before_api_inventory")));
    merged.api_option_groups = await collectPlatformApiInventory(client, platform);
    merged.framework_inventory = await collectFrameworkInventory(client, platform);
    merged.framework_option_groups = merged.framework_inventory.option_groups || [];
    return {
      snapshot: merged,
      probe_meta: {
        draft_upload_requested: Boolean(allowDraftUpload),
        upload,
        actions: actions.filter((action) => action.clicked).slice(0, 20),
        interruptions: interruptions.slice(0, 60),
      },
    };
  } finally {
    client.close();
  }
}

async function collectFrameworkInventory(client, platform) {
  const expression = `(() => {
    const platform = ${JSON.stringify(platform)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const labelOf = (item) => clean(item?.name || item?.title || item?.label || item?.text || item?.value);
    const idOf = (item) => item?.id ?? item?.tid ?? item?.typeid ?? item?.value ?? item?.key ?? "";
    const uniqueGroups = new Map();
    const components = [];
    const addGroup = (key, label, options, values = [], source = "framework_state") => {
      const cleanedOptions = [...new Set((options || []).map((item) => clean(item)).filter(Boolean))].slice(0, 220);
      if (!cleanedOptions.length) return;
      const existing = uniqueGroups.get(key);
      const next = {
        key,
        label,
        source,
        options: cleanedOptions,
        values: (values || []).slice(0, 220),
      };
      if (existing) {
        existing.options = [...new Set([...existing.options, ...next.options])].slice(0, 220);
        existing.values = [...(existing.values || []), ...(next.values || [])].slice(0, 220);
      } else {
        uniqueGroups.set(key, next);
      }
    };
    const summarizeValues = (value, path) => {
      if (!Array.isArray(value) || value.length < 2 || value.length > 300) return;
      const objects = value.filter((item) => item && typeof item === "object");
      if (!objects.length) return;
      const optionObjects = objects
        .map((item) => ({
          id: idOf(item),
          name: labelOf(item),
          path: clean(item.path || item.full_name || item.fullName || ""),
          raw_keys: Object.keys(item).slice(0, 12),
        }))
        .filter((item) => item.name);
      if (optionObjects.length < 2) return;
      addGroup(
        \`\${platform}_framework_\${path.replace(/[^a-z0-9_]+/gi, "_").slice(0, 48)}\`,
        \`组件状态候选：\${path}\`,
        optionObjects.map((item) => item.path || item.name),
        optionObjects,
      );
    };
    const scanObject = (value, prefix, depth = 0, seen = new Set()) => {
      if (!value || typeof value !== "object" || seen.has(value) || depth > 2) return;
      seen.add(value);
      for (const [key, child] of Object.entries(value)) {
        if (key.startsWith("_") && !["_props", "_data"].includes(key)) continue;
        const path = prefix ? \`\${prefix}.\${key}\` : key;
        summarizeValues(child, path);
        if (child && typeof child === "object" && !Array.isArray(child)) scanObject(child, path, depth + 1, seen);
      }
    };
    const frameworkSelectors = [
      ".video-human-type",
      ".video-season-select",
      ".time-switch-wrp",
      ".d-time-container",
      "[class*=select]",
      "[class*=dropdown]",
      "[class*=option]",
      "[class*=collection]",
      "[class*=playlist]",
      "[class*=category]",
      "[class*=topic]",
      "[class*=tag]",
      "[class*=publish]",
      "[class*=declaration]",
      "[class*=statement]",
      "[class*=privacy]",
      "[class*=visibility]",
      "[class*=schedule]",
      "[class*=time]",
      "[class*=group]",
      "[class*=chat]",
      "[role=combobox]",
      "[role=listbox]",
      "[role=menu]",
      "[role=menuitem]",
      "[role=option]",
      "[role=switch]",
      "[role=checkbox]",
    ].join(",");
    const vueElements = [...document.querySelectorAll(frameworkSelectors)]
      .filter((el) => el.__vue__ && visible(el))
      .slice(0, 80);
    for (const el of vueElements) {
      const vm = el.__vue__;
      const component = {
        framework: "vue",
        tag: el.tagName.toLowerCase(),
        className: clean(typeof el.className === "string" ? el.className : ""),
        text: clean(el.innerText || el.textContent).slice(0, 160),
        value: vm.value ?? vm.checked ?? vm.active ?? null,
        selected: clean(vm.selected?.name || vm.selected?.title || vm.current?.name || vm.current?.title || vm._watchers?.[1]?.value?.name || ""),
      };
      components.push(component);
      scanObject(vm.$props || {}, \`\${component.className || component.tag}.$props\`);
      scanObject(vm.$data || vm._data || {}, \`\${component.className || component.tag}.$data\`);
      scanObject(vm._props || {}, \`\${component.className || component.tag}._props\`);
      for (const [index, watcher] of (vm._watchers || []).entries()) {
        summarizeValues(watcher?.value, \`\${component.className || component.tag}._watchers[\${index}]\`);
      }
    }
    const reactElements = [...document.querySelectorAll(frameworkSelectors)]
      .filter((el) => Object.keys(el).some((key) => key.startsWith("__reactProps$") || key.startsWith("__reactFiber$")))
      .filter(visible)
      .slice(0, 140);
    const reactFiberOf = (el) => {
      const key = Object.keys(el).find((item) => item.startsWith("__reactFiber$") || item.startsWith("__reactInternalInstance$"));
      return key ? el[key] : null;
    };
    const reactPropsOf = (el) => {
      const key = Object.keys(el).find((item) => item.startsWith("__reactProps$"));
      return key ? el[key] : null;
    };
    for (const el of reactElements) {
      const component = {
        framework: "react",
        tag: el.tagName.toLowerCase(),
        className: clean(typeof el.className === "string" ? el.className : ""),
        text: clean(el.innerText || el.textContent).slice(0, 160),
      };
      components.push(component);
      const fiber = reactFiberOf(el);
      scanObject(reactPropsOf(el) || {}, \`\${component.className || component.tag}.reactProps\`);
      scanObject(fiber?.memoizedProps || {}, \`\${component.className || component.tag}.memoizedProps\`);
      scanObject(fiber?.memoizedState || {}, \`\${component.className || component.tag}.memoizedState\`);
      scanObject(fiber?.return?.memoizedProps || {}, \`\${component.className || component.tag}.parentMemoizedProps\`);
      scanObject(fiber?.return?.memoizedState || {}, \`\${component.className || component.tag}.parentMemoizedState\`);
    }
    const semanticTextGroups = {
      collections: /合集|栏目|专辑|播放列表|playlist|collection|album/i,
      categories: /分类|分区|品类|category|section|partition/i,
      declarations: /原创|声明|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights|kids|audience/i,
      visibility: /公开|私密|可见|所有人|好友|仅自己|visibility|public|private|unlisted|everyone/i,
      schedule: /定时|预约|发布时间|发表时间|schedule|premiere/i,
      topics: /话题|标签|topic|hashtag|tag/i,
      groups: /群聊|社群|group|chat/i,
    };
    for (const [key, pattern] of Object.entries(semanticTextGroups)) {
      const options = components.map((item) => item.text).filter((text) => text && pattern.test(text) && text.length <= 120);
      addGroup(\`\${platform}_framework_component_\${key}\`, \`组件文本候选：\${key}\`, options, options.map((name) => ({ name, source: "component_visible_text" })), "component_visible_text");
    }
    if (platform === "bilibili") {
      const categoryEl = document.querySelector(".video-human-type");
      const categoryVm = categoryEl?.__vue__;
      const categoryList = categoryVm?._watchers?.[0]?.value || [];
      if (Array.isArray(categoryList)) {
        addGroup(
          "bilibili_vue_primary_sections",
          "B站 Vue 投稿页一级分区",
          categoryList.map((item) => item?.name),
          categoryList.map((item) => ({ id: item?.id || "", name: item?.name || "", source: "video-human-type.__vue__" })),
        );
      }
      const selected = categoryVm?._watchers?.[1]?.value;
      if (selected?.name) {
        addGroup("bilibili_vue_selected_section", "B站 Vue 当前分区", [selected.name], [{ id: selected.id || "", name: selected.name, source: "video-human-type.__vue__.selected" }]);
      }
      const seasonText = clean(document.querySelector(".video-season-select .season-select")?.innerText || "");
      if (seasonText) addGroup("bilibili_vue_selected_collection", "B站当前合集读回", [seasonText], [{ name: seasonText, source: "video-season-select.dom_readback" }]);
    }
    return { framework: components.length ? "detected" : "none", components: components.slice(0, 80), option_groups: [...uniqueGroups.values()] };
  })()`;
  try {
    return await evaluateWithClient(client, expression, 20000);
  } catch (error) {
    return { framework: "error", error: error.message, components: [], option_groups: [] };
  }
}

async function collectPlatformApiInventory(client, platform) {
  if (platform === "bilibili") {
    const expression = `Promise.all([
        fetch("https://member.bilibili.com/x/vupre/web/archive/pre?lang=cn", { credentials: "include" }).then((response) => response.json()).catch((error) => ({ error: error.message })),
        fetch("https://member.bilibili.com/x2/creative/web/seasons?pn=1&ps=100", { credentials: "include" }).then((response) => response.json()).catch((error) => ({ error: error.message })),
      ])
      .then(([prePayload, seasonPayload]) => {
        const payload = prePayload || {};
        const data = payload && payload.data ? payload.data : {};
        const sections = [];
        const walk = (items, path = []) => {
          for (const item of items || []) {
            const nextPath = [...path, item.name].filter(Boolean);
            if (item.id && item.name && path.length) {
              sections.push({
                name: item.name,
                id: item.id,
                path: nextPath.join("/"),
                description: item.description || item.desc || "",
              });
            }
            walk(item.children || [], nextPath);
          }
        };
        walk(data.typelist || []);
        const seasons = [];
        const collectSeason = (value) => {
          if (Array.isArray(value)) {
            for (const item of value) collectSeason(item);
          } else if (value && typeof value === "object") {
            const name = value.name || value.title || value.label || value.season_title;
            if (name) seasons.push(String(name));
            for (const child of Object.values(value)) {
              if (child && typeof child === "object") collectSeason(child);
            }
          }
        };
        collectSeason(data.season);
        const seasonCatalog = [];
        const seasonData = seasonPayload && seasonPayload.data ? seasonPayload.data : {};
        for (const item of seasonData.seasons || []) {
          const season = item && item.season ? item.season : item;
          const title = season && (season.title || season.name || season.label || season.season_title);
          if (!title) continue;
          const section = item && item.sections && Array.isArray(item.sections.sections) ? item.sections.sections[0] : null;
          seasonCatalog.push({
            id: season.id || season.season_id || "",
            name: String(title),
            selectable: true,
            status: season.state === 0 || season.state === undefined ? "selectable" : String(season.state),
            video_count: Number(season.ep_num || season.epCount || (section && section.epCount) || 0),
            source: "bilibili_x2_creative_web_seasons",
            section_id: section && section.id ? section.id : "",
          });
        }
        return { sections, seasons: [...new Set(seasons)].slice(0, 60), seasonCatalog };
      })
      .catch((error) => ({ error: error.message }))`;
    const payload = await evaluateWithClient(client, expression, 20000);
    const groups = [];
    if (Array.isArray(payload.sections) && payload.sections.length) {
      groups.push({
        key: "bilibili_api_sections",
        label: "B站真实分区接口",
        options: payload.sections.map((item) => item.path || item.name).filter(Boolean).slice(0, 180),
        values: payload.sections.slice(0, 180),
      });
    }
    if (Array.isArray(payload.seasons) && payload.seasons.length) {
      groups.push({ key: "bilibili_api_collections", label: "B站真实合集接口", options: payload.seasons.slice(0, 60) });
    }
    if (Array.isArray(payload.seasonCatalog) && payload.seasonCatalog.length) {
      groups.push({
        key: "bilibili_season_catalog",
        label: "B站合集管理真实目录",
        options: payload.seasonCatalog.map((item) => item.name).filter(Boolean).slice(0, 100),
        values: payload.seasonCatalog.slice(0, 100),
      });
    }
    return groups;
  }
  return [];
}

function buildInventory(platform, tab, snapshot, probeMeta = {}) {
  const lines = snapshot.lines || [];
  const elements = snapshot.elements || [];
  const warnings = [];
  const fieldGroups = buildFieldGroups(platform, elements, lines);
  const domOptionGroups = buildOptionGroups(platform, elements, lines);
  const domControlGroups = buildDomControlOptionGroups(platform, elements);
  const optionGroups = mergeOptionGroups(
    mergeOptionGroups(mergeOptionGroups(domOptionGroups, domControlGroups), snapshot.api_option_groups || []),
    snapshot.framework_option_groups || [],
  );
  const coverage = buildProbeCoverage(platform, optionGroups, lines, fieldGroups);
  const evidence = buildInventoryEvidence(platform, {
    dom: domOptionGroups,
    controls: domControlGroups,
    api: snapshot.api_option_groups || [],
    framework: snapshot.framework_option_groups || [],
    fieldGroups,
    lines,
  });
  const operationSteps = (PLATFORM_STEPS[platform] || [
    "打开平台创作/发布页",
    "上传视频和封面",
    "填写标题、正文、标签",
    "选择平台真实可见的合集、分类、声明和定时设置",
    "发布前再次验证页面和字段变化",
  ]).map((label, index) => ({ index: index + 1, label }));

  if (platform === "youtube" && lines.some((line) => /功能受限|已停用评论|已停用通知|COPPA|儿童/.test(line))) {
    warnings.push("YouTube 页面显示功能受限/COPPA/评论或通知限制，发布方案必须保留并处理该限制。");
  }
  if (probeMeta.draft_upload_requested && !probeMeta.upload?.uploaded) {
    warnings.push(`已请求草稿上传摸底，但未能启动上传：${probeMeta.upload?.reason || "unknown"}。`);
  }
  if (platform === "douyin" && /content\/upload/.test(snapshot.url || "") && !probeMeta.upload?.uploaded) {
    warnings.push("抖音当前停留在上传入口；标题、合集、声明、定时等发布参数通常要完成草稿上传后才会出现，不能用侧边栏文字冒充发布选项。");
  }
  for (const missing of coverage.missing_required_surfaces || []) {
    warnings.push(`未完成关键发布面摸底：${missing.label}。这表示尚未采到真实选项，不能推断为平台没有该选项。`);
  }
  if (!optionGroups.length) warnings.push("已连接真实页面，但没有识别到可用下拉/候选选项；需要展开页面控件后重新摸底。");

  return {
    status: optionGroups.length || fieldGroups.length ? "partial" : "needs_expanded_controls",
    platform,
    message: probeMeta.draft_upload_requested
      ? "已在不点击发布按钮的前提下进行草稿上传摸底，并读取可见/已展开控件。"
      : "已从当前浏览器页面读取可见控件；折叠菜单需要在平台页面展开后重新摸底。",
    route: {
      url: snapshot.url || tab.url || "",
      title: snapshot.title || tab.title || "",
      domains: PLATFORM_DOMAINS[platform] || [],
    },
    field_groups: fieldGroups,
    option_groups: optionGroups,
    evidence,
    framework_inventory: snapshot.framework_inventory || { framework: "unknown", components: [], option_groups: [] },
    coverage,
    operation_steps: operationSteps,
    warnings,
    probe_meta: probeMeta,
  };
}

function buildInventoryEvidence(platform, { dom = [], controls = [], api = [], framework = [], fieldGroups = [], lines = [] } = {}) {
  const frameworkState = (framework || []).filter((group) => String(group.source || "") === "framework_state");
  const componentText = (framework || []).filter((group) => String(group.source || "") === "component_visible_text");
  const sourceSummary = [
    { source: "dom_visible_text", group_count: dom.length, option_count: dom.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "dom_control", group_count: controls.length, option_count: controls.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "platform_catalog", group_count: (dom || []).filter((group) => String(group.source || "") === "platform_catalog").length, option_count: (dom || []).filter((group) => String(group.source || "") === "platform_catalog").reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "platform_api", group_count: api.length, option_count: api.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "framework_state", group_count: frameworkState.length, option_count: frameworkState.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "component_visible_text", group_count: componentText.length, option_count: componentText.reduce((total, group) => total + (group.options || []).length, 0) },
    { source: "field_controls", group_count: fieldGroups.length, option_count: fieldGroups.reduce((total, group) => total + (group.controls || []).length, 0) },
  ];
  const bySurface = (PLATFORM_REQUIRED_SURFACES[platform] || []).map((surface) => {
    const matchingSources = [];
    for (const [source, groups] of [
      ["dom_visible_text", dom],
      ["dom_control", controls],
      ["platform_catalog", (dom || []).filter((group) => String(group.source || "") === "platform_catalog")],
      ["platform_api", api],
      ["framework_state", frameworkState],
      ["component_visible_text", componentText],
    ]) {
      const matched = (groups || []).filter((group) => {
        const text = `${group.key || ""}\n${group.label || ""}\n${(group.options || []).join("\n")}\n${JSON.stringify(group.values || [])}`;
        return surface.pattern.test(text);
      });
      if (matched.length) {
        matchingSources.push({
          source,
          groups: matched.map((group) => String(group.key || group.label || "")).slice(0, 6),
          samples: matched.flatMap((group) => group.options || []).slice(0, 10),
        });
      }
    }
    if (surface.pattern.test(JSON.stringify(fieldGroups || []))) matchingSources.push({ source: "field_controls", groups: [surface.key], samples: [] });
    if (surface.pattern.test((lines || []).join("\n"))) matchingSources.push({ source: "page_text", groups: [surface.key], samples: [] });
    return {
      key: surface.key,
      label: surface.label,
      confidence: matchingSources.some((item) => item.source === "platform_api" || item.source === "platform_catalog" || item.source === "framework_state" || item.source === "dom_control")
        ? "strong"
        : matchingSources.length
          ? "weak"
          : "missing",
      sources: matchingSources,
    };
  });
  return { source_summary: sourceSummary, by_surface: bySurface };
}

function refreshInventoryCoverage(inventory) {
  if (!inventory || typeof inventory !== "object") return inventory;
  const optionGroups = inventory.option_groups || [];
  const lines = [
    ...optionGroups.flatMap((group) => [
      String(group.key || ""),
      String(group.label || ""),
      ...((group.options || []).map((option) => String(option || ""))),
    ]),
    ...((inventory.field_groups || []).flatMap((group) => [
      String(group.key || ""),
      String(group.label || ""),
      ...((group.controls || []).map((control) => String(control.label || ""))),
    ])),
  ];
  inventory.coverage = buildProbeCoverage(inventory.platform, optionGroups, lines, inventory.field_groups || []);
  inventory.evidence = buildInventoryEvidence(inventory.platform, {
    dom: optionGroups.filter((group) => !String(group.source || "").includes("framework") && String(group.source || "") !== "dom_control" && !String(group.key || "").includes("_api_")),
    controls: optionGroups.filter((group) => String(group.source || "") === "dom_control" || String(group.key || "").includes("_dom_control_")),
    api: optionGroups.filter((group) => String(group.key || "").includes("_api_") || String(group.source || "").includes("api")),
    framework: optionGroups.filter((group) => String(group.source || "").includes("framework") || String(group.key || "").includes("_vue_") || String(group.key || "").includes("_framework_")),
    fieldGroups: inventory.field_groups || [],
    lines,
  });
  const stalePrefix = "未完成关键发布面摸底：";
  const warnings = (inventory.warnings || []).filter((warning) => !String(warning || "").startsWith(stalePrefix));
  for (const missing of inventory.coverage.missing_required_surfaces || []) {
    warnings.push(`未完成关键发布面摸底：${missing.label}。这表示尚未采到真实选项，不能推断为平台没有该选项。`);
  }
  inventory.warnings = warnings.slice(0, 20);
  return inventory;
}

const PLATFORM_REQUIRED_SURFACES = {
  douyin: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "话题选择", pattern: /话题|#/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "原创/声明", pattern: /原创|声明|自主声明|AI|营销/i },
    { key: "visibility", label: "谁可以看/可见性", pattern: /谁可以看|公开|好友可见|仅自己可见|visibility/i },
    { key: "schedule", label: "发布时间/定时", pattern: /定时|发布时间|立即发布|schedule/i },
  ],
  xiaohongshu: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "标签/话题选择", pattern: /话题|#|标签/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "原创/内容类型声明", pattern: /原创声明|内容类型声明|AI|虚构|营销|来源/i },
    { key: "group_chat", label: "群聊绑定", pattern: /群聊|群$/i },
    { key: "location", label: "地点/路线", pattern: /地点|位置|路线/i },
    { key: "visibility", label: "可见性", pattern: /公开可见|好友可见|仅自己/i },
    { key: "schedule", label: "定时发布", pattern: /定时发布|发布时间|schedule/i },
  ],
  bilibili: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "category", label: "分区", pattern: /分区|户外潮流|生活兴趣|科技|数码/i },
    { key: "collection", label: "合集", pattern: /合集|collection/i },
    { key: "declaration", label: "创作声明/权益", pattern: /创作声明|创作权益|内容无需标注|AI|营销|转载|自制/i },
    { key: "schedule", label: "定时发布", pattern: /定时发布|预约|schedule/i },
  ],
  kuaishou: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "标签/话题", pattern: /标签|话题|#|tag/i },
    { key: "category", label: "作品分类", pattern: /作品分类|分类/i },
    { key: "collection", label: "合集/合集目录", pattern: /合集|collection/i },
    { key: "declaration", label: "作者服务/声明", pattern: /作者服务|声明|原创|权益/i },
    { key: "visibility", label: "查看权限", pattern: /所有人可见|好友可见|仅自己可见|查看权限/i },
    { key: "schedule", label: "发布时间", pattern: /定时发布|立即发布|发布时间/i },
  ],
  youtube: [
    { key: "thumbnail", label: "缩略图/封面", pattern: /缩略图|封面|thumbnail|cover/i },
    { key: "playlist", label: "播放列表", pattern: /播放列表|playlist/i },
    { key: "audience", label: "儿童受众/COPPA", pattern: /儿童|COPPA|kids|audience/i },
    { key: "category_language", label: "分类/语言/字幕", pattern: /类别|分类|语言|字幕|category|language|captions|subtitles/i },
    { key: "visibility", label: "公开范围", pattern: /公开|私享|不公开|visibility|public|private|unlisted/i },
    { key: "schedule", label: "预约发布时间", pattern: /预约|定时|schedule/i },
    { key: "restrictions", label: "评论/通知限制", pattern: /评论|通知|功能受限|限制/i },
  ],
  "wechat-channels": [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "topics", label: "话题/位置", pattern: /话题|位置|地点|#/i },
    { key: "collection", label: "合集/活动", pattern: /合集|活动/i },
    { key: "declaration", label: "声明/原创", pattern: /声明|原创/i },
    { key: "visibility", label: "谁可以看", pattern: /谁可以看|公开|朋友/i },
    { key: "schedule", label: "定时发表", pattern: /定时|发表时间|预约/i },
  ],
  toutiao: [
    { key: "cover", label: "封面", pattern: /封面|cover/i },
    { key: "category", label: "分类", pattern: /分类|品类/i },
    { key: "collection", label: "合集", pattern: /合集|专辑/i },
    { key: "declaration", label: "原创/声明", pattern: /原创|声明|权益/i },
    { key: "schedule", label: "定时发布", pattern: /定时|发布时间/i },
  ],
  x: [
    { key: "media", label: "媒体/封面", pattern: /media|image|video|媒体|图片|视频/i },
    { key: "schedule", label: "定时发布", pattern: /Schedule|定时/i },
    { key: "audience", label: "受众/回复权限", pattern: /Audience|Reply|Everyone|回复|受众/i },
  ],
};

function buildProbeCoverage(platform, optionGroups, lines, fieldGroups) {
  const groups = optionGroups || [];
  const lineText = (lines || []).join("\n");
  const fieldText = JSON.stringify(fieldGroups || []);
  const required = PLATFORM_REQUIRED_SURFACES[platform] || [];
  const surfaces = required.map((surface) => {
    const matchedGroups = groups
      .filter((group) => {
        const key = `${group.key || ""} ${group.label || ""}`;
        const options = (group.options || []).join("\n");
        const values = JSON.stringify(group.values || []);
        return surface.pattern.test(`${key}\n${options}\n${values}`);
      })
      .map((group) => String(group.key || group.label || ""));
    const hasField = surface.pattern.test(fieldText);
    const hasLine = surface.pattern.test(lineText);
    return {
      key: surface.key,
      label: surface.label,
      status: matchedGroups.length ? "options_collected" : hasField || hasLine ? "surface_seen_without_options" : "missing",
      matched_groups: matchedGroups.slice(0, 8),
    };
  });
  return {
    required_surfaces: surfaces,
    missing_required_surfaces: surfaces.filter((surface) => surface.status === "missing"),
    partial_required_surfaces: surfaces.filter((surface) => surface.status === "surface_seen_without_options"),
  };
}

function buildFieldGroups(platform, elements, lines) {
  const fields = [];
  const add = (key, label, matches) => {
    const matched = matches.filter(Boolean);
    if (matched.length) fields.push({ key, label, controls: matched.slice(0, 12) });
  };
  add("title", "标题", findControls(elements, /标题|title/i));
  add("body", "正文/简介", findControls(elements, /正文|简介|描述|说明|作品描述|description/i));
  add("tags", "标签/话题", findControls(elements, /标签|话题|#添加话题|tag/i));
  add("schedule", "定时发布", findControls(elements, /定时|预约|schedule/i));
  add("visibility", "可见性/发布模式", findControls(elements, /公开|私密|可见|草稿|visibility|public|private|draft/i));
  if (platform === "xiaohongshu") {
    add("xiaohongshu_content_settings", "小红书内容设置", matchingLines(lines, /内容设置|添加章节|加入合集|原创声明|内容类型声明|选择群聊|地点|路线/));
    add("xiaohongshu_publish_settings", "小红书发布设置", matchingLines(lines, /封面设置|活动推荐|作者服务|发布设置|查看权限|定时发布|发布/));
  }
  if (platform === "bilibili") {
    add("bilibili_settings", "B站投稿设置", matchingLines(lines, /分区|标签|合集|声明|权益|定时发布|立即投稿/));
  }
  if (platform === "kuaishou") {
    add("kuaishou_publish_settings", "快手发布设置", matchingLines(lines, /封面设置|作品分类|作者服务|作者声明|加入合集|查看权限|发布时间|发布/));
  }
  if (platform === "youtube") {
    add("youtube_publish_settings", "YouTube发布设置", matchingLines(lines, /播放列表|受众|儿童|限制|可见性|公开|预约|评论|通知|字幕|语言|类别|playlist|audience|visibility|schedule/));
  }
  if (platform === "wechat-channels") {
    add("wechat_channels_publish_settings", "视频号发布设置", matchingLines(lines, /合集|活动|原创|声明|谁可以看|定时发表|位置|话题/));
  }
  if (platform === "toutiao") {
    add("toutiao_publish_settings", "头条发布设置", matchingLines(lines, /分类|合集|原创|声明|权益|定时发布|可见|封面/));
  }
  if (platform === "x") {
    add("x_publish_settings", "X发布设置", matchingLines(lines, /Schedule|Audience|Reply|Everyone|Premium|Post settings|定时|可见|回复/));
  }
  if (platform === "douyin") {
    add("douyin_cover", "抖音封面设置", matchingLines(lines, /设置封面|选择封面|横封面|竖封面|Ai智能推荐封面|重新上传/));
    add("douyin_collection_declaration", "抖音合集/自主声明", matchingLines(lines, /添加合集|请选择合集|自主声明|请选择自主声明/));
    add("douyin_extra", "抖音扩展信息", matchingLines(lines, /视频章节|添加标签|位置|输入地理位置|关联热点|点击输入热点词/));
    add("douyin_publish_settings", "抖音发布设置", matchingLines(lines, /谁可以看|公开|好友可见|仅自己可见|保存权限|允许|不允许|发布时间|立即发布|定时发布/));
  }
  return fields;
}

function buildOptionGroups(platform, elements, lines) {
  const groups = [];
  const add = (key, label, options) => {
    const cleaned = unique(options.map((item) => String(item || "").trim()).filter((item) => item && item.length <= 80));
    if (cleaned.length) groups.push({ key, label, options: cleaned.slice(0, 60) });
  };
  const selectOptions = elements.flatMap((element) => element.options || []);
  add("select_options", "页面 select 控件选项", selectOptions);
  if (platform !== "douyin") {
    add("collections", "合集/栏目/播放列表", contextOptions(lines, /合集|栏目|专辑|播放列表|playlist|album/i));
    add("categories", "分类/分区", contextOptions(lines, /分类|分区|品类|category|section|partition/i));
  }
  if (platform !== "xiaohongshu" && platform !== "douyin") {
    add("declarations", "声明/权益/内容类型", contextOptions(lines, /声明|原创|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights/i));
    add("group_chats", "群聊/社群", contextOptions(lines, /群聊|社群|粉丝群|group|chat/i));
  }

  if (platform === "xiaohongshu") {
    add(
      "xiaohongshu_collections",
      "小红书合集",
      [
        ...lines.filter((line) => /EDC刀光|EDC潮玩|FAS新品|开箱视频|合集$|创建合集/.test(line)),
      ],
    );
    add(
      "xiaohongshu_declarations",
      "小红书声明",
      [
        ...lines.filter((line) => /原创声明|虚构演绎|AI合成|营销广告|内容来源/.test(line)),
      ],
    );
    add(
      "xiaohongshu_group_chats",
      "小红书群聊",
      [
        ...lines.filter((line) => /群$|群聊|F\\.A\\.S EDC畅聊群/i.test(line)),
      ],
    );
    add(
      "xiaohongshu_topics",
      "小红书可选话题",
      [
        ...lines.filter((line) => /^#/.test(line)),
        ...lines.filter((line) => /添加话题|活动详情|搜索更多话题|话题/.test(line)),
      ],
    );
    add("xiaohongshu_visibility", "小红书可见性", lines.filter((line) => /^(公开可见|仅自己可见|好友可见|仅粉丝可见|公开|私密)$/.test(line)));
    add("xiaohongshu_location_route", "小红书地点/路线", contextOptions(lines, /添加地点|标记地点|添加路线|路线|地点/i));
    add("xiaohongshu_live_group_binding", "小红书群聊绑定", contextOptions(lines, /选择群聊|群聊|F\\.A\\.S|EDC畅聊群/i));
    add("xiaohongshu_schedule", "小红书定时发布", contextOptions(lines, /定时发布|发布时间|立即发布/i));
  }
  if (platform === "bilibili") {
    add("bilibili_collection_dropdown_options", "B站合集下拉真实选项", extractBilibiliCollectionDropdownOptions(lines));
    add("bilibili_visible_sections", "B站页面可见分区", extractBilibiliVisibleSections(lines));
    add(
      "bilibili_sections",
      "B站分区候选",
      [
        ...contextOptions(lines, /户外潮流|数码|生活|运动|科技|分区/i),
        ...lines.filter((line) => /户外潮流|数码|生活|运动|科技|知识|汽车|时尚|家装房产/.test(line)),
      ],
    );
  }
  if (platform === "kuaishou") {
    add("kuaishou_categories", "快手作品分类", contextOptions(lines, /作品分类|分类|服务类型|作者服务/i));
    add("kuaishou_declarations", "快手声明/作者服务", contextOptions(lines, /作者服务|原创|声明|权益|关联成功可获得更多收益/i));
    add("kuaishou_visibility", "快手查看权限/互动设置", contextOptions(lines, /查看权限|所有人可见|好友可见|仅自己可见|允许别人跟我拍同框|允许下载|同城页/i));
    add("kuaishou_schedule", "快手发布时间", contextOptions(lines, /发布时间|立即发布|定时发布|粉丝浏览高峰/i));
    add("kuaishou_topics", "快手标签/话题", [
      ...lines.filter((line) => /^#/.test(line)),
      ...contextOptions(lines, /智能话题|好友|推荐|话题|标签/i),
    ]);
    const catalog = extractKuaishouCollectionCatalog(lines);
    if (catalog.length) {
      groups.push({
        key: "kuaishou_collection_catalog",
        label: "快手合集目录",
        source: "platform_catalog",
        options: catalog.map((item) => item.name),
        values: catalog,
      });
    }
  }
  if (platform === "douyin") {
    add("douyin_visibility", "抖音谁可以看", lines.filter((line) => /^(公开|好友可见|仅自己可见)$/.test(line)));
    add("douyin_save_permission", "抖音保存权限", lines.filter((line) => /^(允许|不允许)$/.test(line)));
    add("douyin_schedule", "抖音发布时间", lines.filter((line) => /^(立即发布|定时发布)$/.test(line)));
    add("douyin_topics", "抖音推荐话题", lines.filter((line) => /^#/.test(line)));
    const officialActivities = [];
    const officialIndex = lines.findIndex((line) => line === "官方活动");
    if (officialIndex >= 0) {
      for (const line of lines.slice(officialIndex + 1, officialIndex + 10)) {
        if (/^热度：/.test(line) || /^\+\d+/.test(line)) continue;
        if (/设置封面|添加合集|自主声明/.test(line)) break;
        officialActivities.push(line);
      }
    }
    add("douyin_official_activities", "抖音官方活动", officialActivities);
  }
  if (platform === "youtube") {
    add("youtube_playlists", "YouTube播放列表", contextOptions(lines, /播放列表|playlist/i));
    add("youtube_audience", "YouTube受众/COPPA", contextOptions(lines, /儿童|面向儿童|COPPA|audience|kids/i));
    add("youtube_visibility", "YouTube公开范围", contextOptions(lines, /公开|私享|不公开|visibility|public|private|unlisted/i));
    add("youtube_restrictions", "YouTube限制/通知评论", lines.filter((line) => /功能受限|停用评论|停用通知|评论|通知|限制/i.test(line)));
    add("youtube_monetization_checks", "YouTube声明/获利检查", contextOptions(lines, /广告|推广|付费|版权|限制|检查|声明|自我认证|altered|synthetic|paid promotion/i));
    add("youtube_category_language", "YouTube分类/语言/字幕", contextOptions(lines, /类别|分类|语言|字幕|category|language|captions|subtitles/i));
    add("youtube_schedule", "YouTube预约发布时间", contextOptions(lines, /预约|首映|定时|schedule|premiere|publish/i));
  }
  if (platform === "wechat-channels") {
    add("wechat_channels_collections", "视频号合集/活动", contextOptions(lines, /合集|活动|原创|声明|谁可以看|定时/i));
    add("wechat_channels_declarations", "视频号声明/原创", contextOptions(lines, /原创|声明|活动|权益|推广/i));
    add("wechat_channels_visibility", "视频号谁可以看", contextOptions(lines, /谁可以看|公开|朋友|私密|不给谁看/i));
    add("wechat_channels_schedule", "视频号定时发表", contextOptions(lines, /定时发表|发表时间|立即发表|预约/i));
    add("wechat_channels_topics", "视频号话题/位置", contextOptions(lines, /话题|位置|地点|活动/i));
  }
  if (platform === "toutiao") {
    add("toutiao_categories", "头条分类/声明", contextOptions(lines, /分类|品类|合集|原创|声明|权益|定时/i));
    add("toutiao_collections", "头条合集/专栏", contextOptions(lines, /合集|专栏|专辑|栏目/i));
    add("toutiao_declarations", "头条原创/声明/权益", contextOptions(lines, /原创|声明|权益|广告|营销|AI/i));
    add("toutiao_visibility", "头条可见性", contextOptions(lines, /公开|仅我可见|粉丝可见|可见/i));
    add("toutiao_schedule", "头条定时发布", contextOptions(lines, /定时发布|发布时间|立即发布|预约/i));
  }
  if (platform === "x") {
    add("x_publish_settings", "X发布设置", contextOptions(lines, /Schedule|Audience|Reply|Everyone|Premium|Post settings|定时|可见|回复/i));
    add("x_audience_reply", "X受众/回复权限", contextOptions(lines, /Audience|Reply|Everyone|Circle|Subscribers|回复|所有人|受众/i));
    add("x_schedule", "X定时发布", contextOptions(lines, /Schedule|Date|Time|定时|日期|时间/i));
  }
  return groups;
}

function buildDomControlOptionGroups(platform, elements) {
  const groups = [];
  const add = (key, label, options, values = []) => {
    const cleaned = unique(options.map((item) => String(item || "").trim()).filter((item) => item && item.length <= 120));
    if (cleaned.length) {
      groups.push({
        key,
        label,
        source: "dom_control",
        options: cleaned.slice(0, 120),
        values: values.slice(0, 120),
      });
    }
  };
  const controls = (elements || [])
    .filter((element) => {
      const text = String(element.text || element.ariaLabel || element.placeholder || "").trim();
      if (!text || text.length > 120) return false;
      if (element.disabled) return false;
      return /button|checkbox|switch|combobox|option|menuitem/.test(String(element.role || "")) ||
        /button|checkbox|radio|submit/.test(String(element.type || "")) ||
        /select|dropdown|option|menu|collection|playlist|category|topic|tag|publish|declaration|statement|privacy|visibility|schedule|time|group|chat/i.test(String(element.className || ""));
    })
    .map((element) => ({
      name: String(element.text || element.ariaLabel || element.placeholder || "").trim(),
      tag: element.tag,
      role: element.role,
      type: element.type,
      className: element.className,
      checked: Boolean(element.checked),
      source: "dom_control",
    }));
  const byPattern = {
    collections: /合集|栏目|专辑|播放列表|playlist|collection|album/i,
    categories: /分类|分区|品类|category|section|partition/i,
    declarations: /原创|声明|权益|AI|合成|广告|营销|儿童|COPPA|declaration|statement|rights|kids|audience/i,
    visibility: /公开|私密|可见|所有人|好友|仅自己|visibility|public|private|unlisted|everyone/i,
    schedule: /定时|预约|发布时间|发表时间|schedule|premiere|Date|Time/i,
    topics: /话题|标签|topic|hashtag|tag|#/i,
    groups: /群聊|社群|group|chat/i,
    cover: /封面|缩略图|cover|thumbnail/i,
    media: /媒体|视频|图片|media|video|image/i,
  };
  for (const [key, pattern] of Object.entries(byPattern)) {
    const matched = controls.filter((item) => pattern.test(`${item.name} ${item.className} ${item.role}`));
    add(`${platform}_dom_control_${key}`, `DOM交互控件：${key}`, matched.map((item) => item.name), matched);
  }
  return groups;
}

function extractBilibiliCollectionDropdownOptions(lines) {
  const output = [];
  const ignored = /^(加入合集|请选择合集|创建合集|将以下所有视频加入合集|我的合集|全部|商业推广|增加商业推广信息|更多设置|存草稿|立即投稿|遇到问题|内容无需标注|分区|标签|推荐标签：?|创作声明|创作权益|\*|\+|取消|确定)$/;
  const hardStop = /^(商业推广|更多设置|创作声明|分区|标签|推荐标签|简介|定时发布|立即投稿|存草稿|添加地点|发布设置)$/;
  const anchors = [];
  for (let index = 0; index < (lines || []).length; index += 1) {
    const line = String(lines[index] || "").trim();
    if (/^(创建合集|请选择合集|加入合集)$/.test(line)) anchors.push(index);
  }
  for (const anchor of anchors) {
    for (const rawLine of (lines || []).slice(anchor + 1, anchor + 18)) {
      const line = String(rawLine || "").replace(/\s+/g, " ").trim();
      if (!line) continue;
      if (hardStop.test(line)) break;
      if (ignored.test(line)) continue;
      if (line.length < 2 || line.length > 40) continue;
      if (/^\d+$/.test(line)) continue;
      if (/^包含\d+个/.test(line)) continue;
      if (/还可以添加|按回车|添加\d+个标签|活动$|NEW|HOT/.test(line)) continue;
      output.push(line);
    }
  }
  return unique(output);
}

function extractKuaishouCollectionCatalog(lines) {
  const output = [];
  const ignored = /^(全部|我的合集|创建合集|共\d+个合集|编辑合集|解除合集|拖动可排序|作品管理|合集管理|内容管理|首页|发布作品)$/;
  for (let index = 0; index < (lines || []).length; index += 1) {
    const name = String(lines[index] || "").trim();
    if (!name || name.length > 40 || ignored.test(name)) continue;
    const next = String(lines[index + 1] || "").trim();
    if (!/^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$/.test(next)) continue;
    const windowLines = lines.slice(index + 2, index + 8).map((line) => String(line || "").trim());
    const status = windowLines.find((line) => /公开|展示|剧集|不足|selectable|unselectable/i.test(line)) || "";
    const countLine = windowLines.find((line) => /包含\d+个视频/.test(line)) || "";
    const countMatch = countLine.match(/包含(\d+)个视频/);
    const videoCount = countMatch ? Number(countMatch[1]) : null;
    const selectable = !/未公开展示|有效剧集数不足|不公开展示|不可选|不能选择/i.test(status);
    output.push({
      name,
      status,
      selectable,
      video_count: videoCount,
      source: "kuaishou_collection_management_page",
      note: countLine,
    });
  }
  return uniqueBy(output, (item) => item.name).slice(0, 50);
}

function extractBilibiliVisibleSections(lines) {
  const output = [];
  const known = new Set(BILIBILI_SECTION_TERMS);
  for (const rawLine of lines || []) {
    const line = String(rawLine || "").trim();
    if (!line) continue;
    if (known.has(line)) {
      output.push(line);
      continue;
    }
    if (!/分区|生活兴趣|户外潮流|科技数码|时尚美妆|家装房产|旅游出行/.test(line)) continue;
    for (const term of BILIBILI_SECTION_TERMS) {
      if (line.includes(term)) output.push(term);
    }
  }
  return unique(output);
}

function findControls(elements, pattern) {
  return elements
    .filter((element) => pattern.test(`${element.text} ${element.ariaLabel} ${element.placeholder}`))
    .map((element) => ({
      tag: element.tag,
      role: element.role,
      type: element.type,
      label: element.text || element.ariaLabel || element.placeholder,
      checked: element.checked,
    }));
}

function matchingLines(lines, pattern) {
  return lines.filter((line) => pattern.test(line)).slice(0, 20).map((line) => ({ label: line }));
}

function contextOptions(lines, pattern) {
  const options = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (!pattern.test(line)) continue;
    options.push(line);
    for (const nearby of lines.slice(index + 1, index + 8)) {
      if (/发布|保存|取消|确定|下一步|上一步|上传/.test(nearby) && nearby.length < 8) continue;
      if (nearby.length <= 80) options.push(nearby);
    }
  }
  return options;
}

function unique(values) {
  const seen = new Set();
  const output = [];
  for (const value of values) {
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function uniqueBy(values, getKey) {
  const seen = new Set();
  const output = [];
  for (const value of values || []) {
    const key = String(getKey(value) || "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    output.push(value);
  }
  return output;
}

function mergeOptionGroups(left, right) {
  const groups = [];
  const byKey = new Map();
  for (const group of [...(left || []), ...(right || [])]) {
    if (!group || typeof group !== "object") continue;
    const key = String(group.key || group.label || groups.length).trim();
    const current = byKey.get(key);
    if (current) {
      current.options = unique([...(current.options || []), ...(group.options || [])]).slice(0, 220);
      current.values = [...(current.values || []), ...(Array.isArray(group.values) ? group.values : [])].slice(0, 220);
    } else {
      const next = {
        ...group,
        key,
        options: unique(group.options || []).slice(0, 220),
      };
      if (Array.isArray(group.values)) next.values = group.values.slice(0, 220);
      byKey.set(key, next);
      groups.push(next);
    }
  }
  return groups;
}

async function handleProbe(payload) {
  const requestedPlatforms = Array.isArray(payload.platforms) ? payload.platforms.map(normalizePlatform).filter(Boolean) : [];
  let tabs;
  try {
    tabs = await listCdpTabs();
  } catch (error) {
    return {
      contract: CONTRACT,
      status: "unavailable",
      code: "cdp_unavailable",
      message: `无法连接浏览器 CDP：${error.message}。请用 --remote-debugging-port=9222 启动已登录浏览器，或设置 PUBLICATION_BROWSER_CDP_URL。`,
      generated_at: new Date().toISOString(),
      platforms: Object.fromEntries(
        requestedPlatforms.map((platform) => [
          platform,
          {
            status: "unavailable",
            platform,
            message: "没有可读取的远程调试浏览器，不能进行真实平台摸底。",
            route: { domains: PLATFORM_DOMAINS[platform] || [] },
            field_groups: [],
            option_groups: [],
            operation_steps: [],
            warnings: ["未连接浏览器 CDP，不能读取真实页面选项。"],
          },
        ]),
      ),
    };
  }

  const platforms = {};
  for (const platform of requestedPlatforms) {
    const platformTabs = findPlatformTabs(tabs, platform);
    const tab = platformTabs[0];
    if (!tab) {
      platforms[platform] = {
        status: "needs_open_publish_page",
        platform,
        message: "CDP 已连接，但没有找到该平台已打开的创作/发布页面。",
        route: { domains: PLATFORM_DOMAINS[platform] || [] },
        field_groups: [],
        option_groups: [],
        operation_steps: [],
        warnings: ["请在同一个调试浏览器中打开该平台发布页，登录后重新摸底。"],
      };
      continue;
    }
    try {
      const { snapshot, probe_meta } = await probeTabInventory(tab, platform, payload);
      const inventory = buildInventory(platform, tab, snapshot, probe_meta);
      const sidecarTabs = platformTabs
        .filter((candidate) => candidate.id !== tab.id && candidate.type === "page")
        .slice(0, 4);
      const sidecarRoutes = [];
      for (const sidecarTab of sidecarTabs) {
        try {
          const sidecarSnapshot = await snapshotTab(sidecarTab);
          const sidecarGroups = sidecarOptionGroupsForMerge(
            platform,
            sidecarTab,
            buildOptionGroups(platform, sidecarSnapshot.elements || [], sidecarSnapshot.lines || []),
          );
          inventory.option_groups = mergeOptionGroups(inventory.option_groups, sidecarGroups);
          refreshInventoryCoverage(inventory);
          sidecarRoutes.push({ url: sidecarTab.url || "", title: sidecarTab.title || "" });
        } catch (sidecarError) {
          inventory.warnings = [
            ...(inventory.warnings || []),
            `读取同平台辅助页面失败：${sidecarTab.url || sidecarTab.title || ""}：${sidecarError.message}`,
          ].slice(0, 12);
        }
      }
      if (sidecarRoutes.length) {
        inventory.route = {
          ...(inventory.route || {}),
          related_routes: sidecarRoutes,
        };
        inventory.probe_meta = {
          ...(inventory.probe_meta || {}),
          sidecar_tabs_read: sidecarRoutes,
        };
      }
      refreshInventoryCoverage(inventory);
      platforms[platform] = inventory;
    } catch (error) {
      platforms[platform] = {
        status: "probe_failed",
        platform,
        message: `读取页面失败：${error.message}`,
        route: { url: tab.url || "", title: tab.title || "", domains: PLATFORM_DOMAINS[platform] || [] },
        field_groups: [],
        option_groups: [],
        operation_steps: [],
        warnings: [`读取页面失败：${error.message}`],
      };
    }
  }
  const statuses = Object.values(platforms).map((item) => item.status);
  const status = statuses.every((item) => item === "unavailable") ? "unavailable" : statuses.some((item) => item === "partial") ? "partial" : "needs_pages";
  return {
    contract: CONTRACT,
    status,
    source: "browser_agent_inventory",
    probe_id: randomUUID(),
    browser: payload.browser || "",
    generated_at: new Date().toISOString(),
    platforms,
  };
}

function sidecarOptionGroupsForMerge(platform, tab, groups) {
  const url = String(tab?.url || "");
  if (platform === "kuaishou" && /\/article\/manage\/collection/.test(url)) {
    return (groups || []).filter((group) => String(group.key || "").includes("collection_catalog"));
  }
  return groups || [];
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
    if (req.method === "GET" && url.pathname === "/healthz") {
      let cdpStatus = "ok";
      let cdpError = "";
      try {
        await listCdpTabs();
      } catch (error) {
        cdpStatus = "unavailable";
        cdpError = error.message;
      }
      jsonResponse(res, 200, {
        status: "ok",
        contract: CONTRACT,
        cdp_url: CDP_URL,
        cdp_status: cdpStatus,
        cdp_error: cdpError,
        capabilities: {
          inventory_probe: true,
          publication_tasks: true,
          task_reconcile: true,
          live_publish: LIVE_PUBLISH_ENABLED && FINAL_PUBLISH_EXECUTOR_IMPLEMENTED,
          final_publish_executor: FINAL_PUBLISH_EXECUTOR_IMPLEMENTED,
          final_publish_platforms: [...FINAL_PUBLISH_PLATFORMS],
          composite_publish_platforms: [...COMPOSITE_PUBLISH_PLATFORMS],
          platform_composite_frameworks: DEDICATED_PLATFORM_FRAMEWORK_IDS,
          legacy_lightweight_scripts_blocked: true,
          supervised_draft_prepare: true,
        },
      });
      return;
    }
    if (req.method === "POST" && url.pathname === "/probes") {
      const payload = await readRequestJson(req);
      if (payload.contract && payload.contract !== CONTRACT) {
        jsonResponse(res, 400, { status: "error", message: `unsupported contract ${payload.contract}` });
        return;
      }
      jsonResponse(res, 200, { result: await handleProbe(payload) });
      return;
    }
    if (req.method === "POST" && url.pathname === "/tasks") {
      const payload = await readRequestJson(req);
      if (payload.contract && payload.contract !== TASK_CONTRACT) {
        jsonResponse(res, 400, { status: "error", message: `unsupported contract ${payload.contract}` });
        return;
      }
      const task = startPublicationTask(payload);
      jsonResponse(res, 202, { task: serializeTask(task) });
      return;
    }
    if (req.method === "GET" && url.pathname.startsWith("/tasks/")) {
      const taskId = decodeURIComponent(url.pathname.slice("/tasks/".length));
      const task = TASKS.get(taskId);
      if (!task) {
        jsonResponse(res, 404, { status: "not_found", message: `task ${taskId} not found` });
        return;
      }
      jsonResponse(res, 200, { task: serializeTask(task) });
      return;
    }
    jsonResponse(res, 404, { status: "not_found" });
  } catch (error) {
    jsonResponse(res, 500, { status: "error", message: error.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`publication browser-agent inventory service listening on http://${HOST}:${PORT}`);
  console.log(`CDP target: ${CDP_URL}`);
});
