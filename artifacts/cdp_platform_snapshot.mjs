import fs from "node:fs";

const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const platform = process.argv[2] || "";
const out = process.argv[3] || "";

const domains = {
  xiaohongshu: ["creator.xiaohongshu.com"],
  kuaishou: ["cp.kuaishou.com"],
  toutiao: ["mp.toutiao.com"],
  youtube: ["studio.youtube.com", "www.youtube.com"],
  x: ["x.com", "twitter.com"],
  "wechat-channels": ["channels.weixin.qq.com"],
  douyin: ["creator.douyin.com"],
};

class CdpClient {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      message.error ? pending.reject(new Error(message.error.message || "CDP error")) : pending.resolve(message.result);
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
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, 30000);
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
    });
  }
  close() {
    this.socket.close();
  }
}

const tabs = await (await fetch(`${CDP_URL}/json/list`)).json();
const candidates = tabs.filter((tab) => {
  if (tab.type !== "page" || !tab.webSocketDebuggerUrl) return false;
  if (!platform) return true;
  const hosts = domains[platform] || [platform];
  try {
    const host = new URL(tab.url).hostname;
    return hosts.some((item) => host === item || host.endsWith(`.${item}`));
  } catch {
    return false;
  }
});

const results = [];
for (const tab of candidates) {
  const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
  try {
    await client.send("Runtime.enable");
    const data = await client.send("Runtime.evaluate", {
      awaitPromise: true,
      returnByValue: true,
      expression: `(() => {
        const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        };
        const buttons = [...document.querySelectorAll("button,[role=button],input[type=button],input[type=submit],a")]
          .filter(visible)
          .map((el) => {
            const rect = el.getBoundingClientRect();
            return {
              tag: el.tagName,
              text: clean(el.innerText || el.textContent || el.value).slice(0, 120),
              aria: el.getAttribute("aria-label") || "",
              className: String(el.className || "").slice(0, 120),
              rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
            };
          })
          .filter((item) => item.text || item.aria)
          .slice(0, 120);
        const inputs = [...document.querySelectorAll("input,textarea,[contenteditable=true]")]
          .filter(visible)
          .map((el) => ({
            tag: el.tagName,
            type: el.getAttribute("type") || "",
            accept: el.getAttribute("accept") || "",
            placeholder: el.getAttribute("placeholder") || "",
            aria: el.getAttribute("aria-label") || "",
            value: (el.value || el.innerText || el.textContent || "").slice(0, 160),
            className: String(el.className || "").slice(0, 120),
          }))
          .slice(0, 100);
        return {
          url: location.href,
          title: document.title,
          text: clean(document.body?.innerText || "").slice(0, 5000),
          buttons,
          inputs,
        };
      })()`,
    });
    const item = { tab: { title: tab.title, url: tab.url }, snapshot: data.result.value };
    results.push(item);
    if (out && candidates.length === 1) {
      await client.send("Page.enable");
      const shot = await client.send("Page.captureScreenshot", { format: "png", fromSurface: true });
      fs.writeFileSync(out, Buffer.from(shot.data, "base64"));
    }
  } finally {
    client.close();
  }
}
console.log(JSON.stringify(results, null, 2));
