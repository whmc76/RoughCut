import { writeFile } from "node:fs/promises";
import path from "node:path";

const CDP_URL = process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222";
const VIDEO_PATH = process.argv[2];
const OUT_PATH = process.argv[3] || "artifacts/publication-live-upload-probe.json";
const VIDEO_BASENAME = path.win32.basename(VIDEO_PATH);

if (!VIDEO_PATH) {
  throw new Error("Usage: node scripts/live_publication_upload_probe.mjs <video-path> [out-json]");
}

const PLATFORM_DOMAINS = {
  bilibili: ["member.bilibili.com"],
  xiaohongshu: ["creator.xiaohongshu.com"],
  kuaishou: ["cp.kuaishou.com"],
  "wechat-channels": ["channels.weixin.qq.com"],
  toutiao: ["mp.toutiao.com"],
  youtube: ["studio.youtube.com"],
  x: ["x.com", "twitter.com"],
};

const platforms = (process.env.PROBE_PLATFORMS ? process.env.PROBE_PLATFORMS.split(",") : Object.keys(PLATFORM_DOMAINS))
  .map((item) => item.trim())
  .filter(Boolean);

async function fetchJson(url, init) {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

async function listTabs() {
  return fetchJson(`${CDP_URL.replace(/\/$/, "")}/json/list`);
}

function findPlatformTab(tabs, platform) {
  const domains = PLATFORM_DOMAINS[platform] || [];
  return tabs.find((tab) => tab.type === "page" && domains.some((domain) => String(tab.url || "").includes(domain)));
}

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message || "CDP error"));
      else pending.resolve(message.result);
    });
    socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("CDP socket closed"));
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
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close() {
    try {
      this.socket.close();
    } catch {
      // best effort
    }
  }
}

const SNAPSHOT_EXPRESSION = `(() => {
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
  const elements = [...document.querySelectorAll("input,textarea,select,button,[role=button],[role=checkbox],[role=switch],[role=combobox],[aria-label]")].filter(visible).slice(0, 500).map((el) => ({
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute("type") || "",
    role: el.getAttribute("role") || "",
    text: clean(el.innerText || el.value || el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title")),
    ariaLabel: clean(el.getAttribute("aria-label")),
    placeholder: clean(el.getAttribute("placeholder")),
    checked: Boolean(el.checked || el.getAttribute("aria-checked") === "true"),
    disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
    options: el.tagName.toLowerCase() === "select" ? [...el.options].map((option) => clean(option.textContent)).filter(Boolean) : [],
  }));
  const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el, index) => ({
    index,
    accept: el.getAttribute("accept") || "",
    multiple: Boolean(el.multiple),
    visible: visible(el),
  }));
  const lines = clean(document.body.innerText).split(/[\\n\\r]+| {2,}/).map((line) => clean(line)).filter(Boolean).slice(0, 1200);
  return { url: location.href, title: document.title, fileInputs, elements, lines };
})()`;

async function snapshot(client) {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    expression: SNAPSHOT_EXPRESSION,
    awaitPromise: true,
    returnByValue: true,
    timeout: 10000,
  });
  return result?.result?.value || {};
}

async function clickByText(client, texts) {
  const expression = `(() => {
    const texts = ${JSON.stringify(texts)};
    const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = window.getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
    };
    const candidates = [...document.querySelectorAll("button,[role=button],a,input[type=button],input[type=submit],[tabindex]")].filter(visible);
    for (const text of texts) {
      const node = candidates.find((el) => clean(el.innerText || el.getAttribute("aria-label") || el.getAttribute("title")).includes(text));
      if (node) {
        node.click();
        return { clicked: true, text, label: clean(node.innerText || node.getAttribute("aria-label") || node.getAttribute("title")) };
      }
    }
    return { clicked: false };
  })()`;
  const result = await client.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true, timeout: 8000 });
  return result?.result?.value || { clicked: false };
}

async function setFirstVideoFileInput(client) {
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
  await client.send("DOM.setFileInputFiles", { nodeId: preferred.nodeId, files: [VIDEO_PATH] });
  return { uploaded: true, input: preferred.attrMap, fileInputCount: described.length };
}

function pageAlreadyHasVideo(snapshotValue) {
  const text = [...(snapshotValue.lines || []), ...((snapshotValue.elements || []).map((element) => element.text || ""))].join(" ");
  return text.includes(VIDEO_BASENAME) || text.includes(VIDEO_BASENAME.replace(/\.[^.]+$/, ""));
}

function summarize(snapshotValue) {
  const lines = snapshotValue.lines || [];
  const optionLines = lines.filter((line) =>
    /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category/i.test(line),
  );
  const controls = (snapshotValue.elements || []).filter((element) =>
    /合集|栏目|播放列表|分区|分类|原创|声明|权益|群聊|定时|预约|可见|公开|私密|儿童|COPPA|playlist|visibility|schedule|category/i.test(
      `${element.text} ${element.ariaLabel} ${element.placeholder}`,
    ) || (element.options || []).length,
  );
  return {
    url: snapshotValue.url,
    title: snapshotValue.title,
    file_inputs: snapshotValue.fileInputs,
    option_lines: optionLines.slice(0, 80),
    controls: controls.slice(0, 80),
  };
}

async function probePlatform(platform, tab) {
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    let before = await snapshot(client);
    const clicks = [];
    if (platform === "youtube") {
      clicks.push(await clickByText(client, ["创建", "上传视频", "Upload videos", "CREATE"]));
      await new Promise((resolve) => setTimeout(resolve, 3000));
      before = await snapshot(client);
    }
    const uploadClicks = [];
    let upload = { uploaded: false, reason: "already_uploaded_or_skipped" };
    if (pageAlreadyHasVideo(before)) {
      upload = { uploaded: true, skipped: true, reason: "video_already_present" };
    } else {
      upload = await setFirstVideoFileInput(client);
      if (!upload.uploaded) {
        uploadClicks.push(await clickByText(client, ["上传视频", "点击上传", "选择视频", "选择文件", "从电脑中选择", "Upload videos", "Select files"]));
        await new Promise((resolve) => setTimeout(resolve, 3000));
        upload = await setFirstVideoFileInput(client);
      }
      if (!upload.uploaded && platform === "youtube") {
        uploadClicks.push(await clickByText(client, ["上传视频", "Upload videos"]));
        await new Promise((resolve) => setTimeout(resolve, 3000));
        upload = await setFirstVideoFileInput(client);
      }
    }
    await new Promise((resolve) => setTimeout(resolve, upload.uploaded && !upload.skipped ? 45000 : 5000));
    const after = await snapshot(client);
    clicks.push(await clickByText(client, ["更多设置", "更多选项", "展开", "内容设置", "选择合集", "添加到播放列表", "Show more", "More options"]));
    await new Promise((resolve) => setTimeout(resolve, 5000));
    const expanded = await snapshot(client);
    return {
      platform,
      status: upload.uploaded ? "uploaded_for_probe" : "upload_not_started",
      route: { url: expanded.url || after.url || before.url, title: expanded.title || after.title || before.title },
      clicks,
      upload_clicks: uploadClicks,
      upload,
      before: summarize(before),
      after: summarize(after),
      expanded: summarize(expanded),
    };
  } catch (error) {
    return { platform, status: "failed", error: error.message, route: { url: tab.url, title: tab.title } };
  } finally {
    client.close();
  }
}

const tabs = await listTabs();
const results = {};
for (const platform of platforms) {
  if (platform === "douyin") continue;
  const tab = findPlatformTab(tabs, platform);
  if (!tab) {
    results[platform] = { platform, status: "no_tab" };
    continue;
  }
  console.log(`probing ${platform}: ${tab.url}`);
  results[platform] = await probePlatform(platform, tab);
}

await writeFile(OUT_PATH, JSON.stringify({ generated_at: new Date().toISOString(), video_path: VIDEO_PATH, results }, null, 2), "utf8");
console.log(`wrote ${OUT_PATH}`);
