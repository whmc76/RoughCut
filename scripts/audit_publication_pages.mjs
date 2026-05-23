import fs from "node:fs";
import path from "node:path";

const API_BASE = process.env.ROUGHCUT_API_BASE || "http://127.0.0.1:38471/api/v1";
const CDP_BASE = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const CREATOR_PROFILE_ID = process.env.PUBLICATION_AUDIT_CREATOR_PROFILE_ID || "d2d15bc6d77a47b79cf20a79b56596c2";
const OUTPUT_PATH = process.env.PUBLICATION_AUDIT_OUTPUT || path.resolve("artifacts", "publication-live-page-audit.json");

const PLATFORM_DOMAINS = {
  bilibili: ["member.bilibili.com/platform/upload"],
  xiaohongshu: ["creator.xiaohongshu.com/publish"],
  kuaishou: ["cp.kuaishou.com/article/publish/video"],
  toutiao: ["mp.toutiao.com/profile_v4/xigua/publish-video", "mp.toutiao.com/profile_v4/graphic/publish"],
  youtube: ["studio.youtube.com"],
  douyin: ["creator.douyin.com/creator-micro/content/post/video"],
  "wechat-channels": ["channels.weixin.qq.com/platform/post/create"],
  x: ["x.com/compose", "twitter.com/compose"],
};

function clean(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function normalizeText(value) {
  return clean(value).toLowerCase();
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

function platformTabScore(tab, domains) {
  let parsed;
  try {
    parsed = new URL(String(tab.url || ""));
  } catch {
    return 0;
  }
  const host = parsed.hostname.toLowerCase();
  const route = `${host}${parsed.pathname}`.toLowerCase();
  let score = 0;
  for (const raw of domains || []) {
    const needle = String(raw || "").toLowerCase();
    if (!needle) continue;
    const [domain] = needle.split("/");
    if (host === domain || host.endsWith(`.${domain}`)) score = Math.max(score, 10);
    if (route.includes(needle)) score = Math.max(score, 30);
  }
  if (tab.type === "page") score += 5;
  if (/upload|publish|post|create|compose/.test(parsed.pathname.toLowerCase())) score += 5;
  return score;
}

function bestTabForPlatform(tabs, platform) {
  return (tabs || [])
    .filter((tab) => tab.type === "page")
    .map((tab) => ({ tab, score: platformTabScore(tab, PLATFORM_DOMAINS[platform] || []) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => right.score - left.score)[0]?.tab;
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
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
    });
  }

  close() {
    try {
      this.socket.close();
    } catch {
      // Best-effort close only.
    }
  }
}

const SNAPSHOT_EXPRESSION = `(() => {
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
  };
  const all = [...document.querySelectorAll("*")].filter(visible);
  const fields = [...document.querySelectorAll("input,textarea,[contenteditable=true],[role=textbox],select")]
    .filter(visible)
    .map((el) => {
      const parents = [];
      let parent = el.parentElement;
      for (let i = 0; i < 4 && parent; i += 1, parent = parent.parentElement) parents.push(clean(parent.innerText).slice(0, 400));
      return {
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute("type") || "",
        role: el.getAttribute("role") || "",
        className: typeof el.className === "string" ? el.className : "",
        placeholder: el.getAttribute("placeholder") || "",
        value: clean(el.value || el.innerText || el.textContent),
        text: clean(el.innerText || el.textContent),
        checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
        parents,
      };
    });
  const lines = clean(document.body.innerText || document.body.textContent || "")
    .split(/\\n| {2,}/)
    .map(clean)
    .filter(Boolean)
    .slice(0, 1000);
  const text = clean(document.body.innerText || document.body.textContent || "");
  const byText = (exact) => all.find((el) => clean(el.innerText || el.textContent) === exact);
  const nearby = (label, selector) => {
    const labelNode = byText(label) || all.find((el) => clean(el.innerText || el.textContent).startsWith(label) && clean(el.innerText || el.textContent).length < 120);
    if (!labelNode) return [];
    const rows = [];
    let parent = labelNode;
    for (let level = 0; level < 7 && parent; level += 1, parent = parent.parentElement) {
      rows.push(...[...parent.querySelectorAll(selector)].filter(visible).map((el) => ({
        level,
        tag: el.tagName.toLowerCase(),
        type: el.getAttribute("type") || "",
        className: typeof el.className === "string" ? el.className : "",
        placeholder: el.getAttribute("placeholder") || "",
        value: clean(el.value || el.innerText || el.textContent),
        text: clean(el.innerText || el.textContent),
        checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
      })));
    }
    return rows.slice(0, 120);
  };
  const selectedImageStyle = [...document.querySelectorAll(".img-item-cover-selected,img,.cover img,[class*=cover] img")]
    .filter(visible)
    .slice(0, 20)
    .map((el) => ({ tag: el.tagName.toLowerCase(), src: el.currentSrc || el.src || "", className: typeof el.className === "string" ? el.className : "", text: clean(el.innerText || el.alt || el.title) }));
  return {
    url: location.href,
    title: document.title,
    scrollY: window.scrollY,
    text: text.slice(0, 8000),
    lines,
    fields,
    controlsByLabel: {
      title: nearby("标题", "input,textarea,[contenteditable=true],[role=textbox]"),
      declaration: nearby("创作声明", "input,.bcc-select,.bcc-option,.auth-content,[class*=select]"),
      category: nearby("分区", "input,.selector-container,.select-container,.select-controller,[class*=select]"),
      tags: nearby("标签", "input,.label-item-v2-content,.label-item-v2-container,.tag-pre-wrp,.hot-tag-container"),
      description: nearby("简介", "textarea,[contenteditable=true],[role=textbox],.ql-editor,input"),
      schedule: nearby("定时发布", "input,.switch-container,.time-switch-wrp,[class*=time],[class*=date],[class*=picker]"),
      collection: nearby("加入合集", "input,.season-select,.video-season-select,[class*=select],button,[role=button]"),
    },
    selectedImageStyle,
  };
})()`;

async function snapshotTab(tab) {
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    const result = await client.send("Runtime.evaluate", {
      expression: SNAPSHOT_EXPRESSION,
      awaitPromise: true,
      returnByValue: true,
      timeout: 12000,
    });
    return result?.result?.value || {};
  } finally {
    client.close();
  }
}

function platformExpectations(attempt) {
  const payload = attempt.request_payload || {};
  return {
    title: clean(payload.title),
    body: clean(payload.body),
    category: clean(payload.category),
    collection: clean(payload.collection?.name || payload.collection_name),
    tags: (payload.hashtags || payload.structured_tags || []).map(clean).filter(Boolean),
    scheduled_publish_at: clean(payload.scheduled_publish_at),
    cover_path: clean(payload.cover_path),
  };
}

function readBilibiliActual(snapshot) {
  const controls = snapshot.controlsByLabel || {};
  const valueFrom = (items, predicate = () => true) => (items || []).find((item) => predicate(item) && clean(item.value || item.text))?.value || "";
  const tags = (controls.tags || [])
    .filter((item) => /label-item-v2-content|label-item-v2-container/.test(item.className || ""))
    .map((item) => clean(item.value || item.text))
    .filter(Boolean);
  return {
    route: snapshot.url,
    title: valueFrom(controls.title, (item) => item.placeholder.includes("标题") || item.type === "text"),
    declaration: valueFrom(controls.declaration, (item) => item.placeholder.includes("创作声明") || item.className.includes("bcc-select-input-inner")),
    category: valueFrom(controls.category, (item) => /select-item|select-controller|selector-container/.test(item.className || "")),
    tags: [...new Set(tags)],
    description: valueFrom(controls.description, (item) => /ql-editor/.test(item.className || "") || item.tag === "textarea"),
    schedule_surface: (controls.schedule || []).map((item) => clean(item.value || item.text || item.className)).filter(Boolean).slice(0, 20),
    collection: valueFrom(controls.collection, (item) => /season-select|video-season-select/.test(item.className || "")),
    cover_observed: (snapshot.selectedImageStyle || []).slice(0, 10),
  };
}

function readGenericActual(snapshot) {
  const text = snapshot.text || "";
  const fields = snapshot.fields || [];
  return {
    route: snapshot.url,
    title_candidates: fields.filter((field) => /标题|title/i.test(`${field.placeholder} ${field.parents?.join(" ")}`)).map((field) => field.value).filter(Boolean).slice(0, 5),
    body_candidates: fields.filter((field) => /简介|描述|说明|正文|description|作品描述/i.test(`${field.placeholder} ${field.parents?.join(" ")}`)).map((field) => field.value || field.text).filter(Boolean).slice(0, 5),
    tag_candidates: fields.filter((field) => /标签|话题|tag|topic/i.test(`${field.placeholder} ${field.parents?.join(" ")}`)).map((field) => field.value || field.text).filter(Boolean).slice(0, 5),
    collection_visible: /合集|栏目|播放列表|playlist/i.test(text),
    schedule_visible: /定时|预约|schedule/i.test(text),
    raw_field_count: fields.length,
    visible_summary: (snapshot.lines || []).filter((line) => /标题|简介|描述|标签|话题|合集|栏目|播放列表|分类|分区|声明|原创|定时|预约|可见|公开|儿童|playlist|schedule/i.test(line)).slice(0, 80),
  };
}

function compareField(name, expected, actual, { contains = false, optional = false } = {}) {
  const expectedText = normalizeText(expected);
  const actualText = normalizeText(actual);
  if (!expectedText && optional) return { field: name, status: "skipped", expected, actual, reason: "no_expected_value" };
  if (!expectedText) return { field: name, status: "unknown", expected, actual, reason: "missing_expected_value" };
  if (!actualText) return { field: name, status: "mismatch", expected, actual, reason: "missing_actual_value" };
  const ok = contains ? actualText.includes(expectedText) : actualText === expectedText;
  return { field: name, status: ok ? "match" : "mismatch", expected, actual };
}

function validatePlatform(platform, expected, actual, snapshot) {
  const checks = [];
  if (platform === "bilibili") {
    checks.push(compareField("title", expected.title, actual.title));
    checks.push(compareField("declaration", "内容无需标注", actual.declaration));
    checks.push(compareField("category", "生活兴趣", actual.category, { contains: true }));
    checks.push(compareField("collection", expected.collection, actual.collection, { contains: true }));
    checks.push(compareField("description", expected.body, actual.description));
    for (const tag of expected.tags || []) {
      checks.push({ field: `tag:${tag}`, status: (actual.tags || []).includes(tag) ? "match" : "mismatch", expected: tag, actual: actual.tags });
    }
    checks.push({
      field: "schedule",
      status: /时间|日期|发布/.test((actual.schedule_surface || []).join(" ")) && !/最早≥5分钟/.test((actual.schedule_surface || []).join(" ")) ? "match" : "mismatch",
      expected: expected.scheduled_publish_at,
      actual: actual.schedule_surface,
      reason: "must_show_enabled_schedule_controls_or_selected_time",
    });
    checks.push({ field: "cover", status: "unknown", expected: expected.cover_path, actual: actual.cover_observed, reason: "cover_path_not_exposed_by_page_dom" });
  } else {
    const generic = actual;
    checks.push({ field: "route", status: generic.raw_field_count > 1 ? "match" : "mismatch", expected: "publish form with editable fields", actual: generic.route });
    checks.push({ field: "title", status: generic.title_candidates.some((value) => normalizeText(value) === normalizeText(expected.title)) ? "match" : "mismatch", expected: expected.title, actual: generic.title_candidates });
    checks.push({ field: "body", status: generic.body_candidates.some((value) => normalizeText(value).includes(normalizeText(expected.body))) ? "match" : "mismatch", expected: expected.body, actual: generic.body_candidates });
    checks.push({ field: "collection_surface", status: expected.collection ? (generic.collection_visible ? "unknown" : "mismatch") : "skipped", expected: expected.collection, actual: generic.collection_visible, reason: expected.collection ? "surface_seen_but_selection_requires_platform_specific_reader" : "no_expected_collection" });
    checks.push({ field: "schedule_surface", status: expected.scheduled_publish_at ? (generic.schedule_visible ? "unknown" : "mismatch") : "skipped", expected: expected.scheduled_publish_at, actual: generic.schedule_visible, reason: "surface_seen_but_selected_time_requires_platform_specific_reader" });
  }
  return checks;
}

async function main() {
  const attemptsPayload = await fetchJson(`${API_BASE}/intelligent-copy/publication/attempts/recent?creator_profile_id=${encodeURIComponent(CREATOR_PROFILE_ID)}&limit=30`);
  const attempts = [];
  const seen = new Set();
  for (const attempt of attemptsPayload.attempts || []) {
    if (!attempt.platform || seen.has(attempt.platform)) continue;
    seen.add(attempt.platform);
    attempts.push(attempt);
  }
  const tabs = await fetchJson(`${CDP_BASE}/json/list`);
  const platforms = [];
  for (const attempt of attempts) {
    const expected = platformExpectations(attempt);
    const tab = bestTabForPlatform(tabs, attempt.platform);
    if (!tab) {
      platforms.push({ platform: attempt.platform, expected, status: "missing_tab", checks: [{ field: "tab", status: "mismatch", expected: "open publish tab", actual: null }] });
      continue;
    }
    const snapshot = await snapshotTab(tab);
    const actual = attempt.platform === "bilibili" ? readBilibiliActual(snapshot) : readGenericActual(snapshot);
    const checks = validatePlatform(attempt.platform, expected, actual, snapshot);
    const mismatch_count = checks.filter((check) => check.status === "mismatch").length;
    const unknown_count = checks.filter((check) => check.status === "unknown").length;
    platforms.push({
      platform: attempt.platform,
      attempt_id: attempt.id,
      tab: { id: tab.id, title: tab.title, url: tab.url },
      expected,
      actual,
      checks,
      status: mismatch_count ? "failed" : unknown_count ? "needs_platform_specific_validation" : "passed",
    });
  }
  const report = {
    generated_at: new Date().toISOString(),
    creator_profile_id: CREATOR_PROFILE_ID,
    status: platforms.some((item) => item.status === "failed") ? "failed" : "needs_review",
    platforms,
  };
  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(report, null, 2), "utf8");
  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
