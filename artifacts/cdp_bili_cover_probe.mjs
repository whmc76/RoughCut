import fs from "node:fs";

const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const OUT = process.argv[2] || "artifacts/bilibili-cover-after-upload.png";

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return response.json();
}

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
      if (message.error) pending.reject(new Error(message.error.message || "CDP error"));
      else pending.resolve(message.result);
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

const tabs = await fetchJson(`${CDP_URL}/json/list`);
const tab = tabs.find((entry) => /member\.bilibili\.com/.test(entry.url || "") && /upload|platform/.test(entry.url || ""));
if (!tab?.webSocketDebuggerUrl) throw new Error("Bilibili upload tab not found");

const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
try {
  await client.send("Runtime.enable");
  await client.send("Page.enable");
  const probe = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const labels = [...document.querySelectorAll("*")].filter((el) => visible(el) && clean(el.textContent) === "封面");
      const label = labels[0] || [...document.querySelectorAll("*")].find((el) => visible(el) && clean(el.textContent).includes("封面设置"));
      if (label) label.scrollIntoView({ block: "center", inline: "center" });
      return new Promise((resolve) => setTimeout(() => {
        const target = [...document.querySelectorAll("*")].find((el) => visible(el) && clean(el.textContent).includes("封面设置"));
        const rect = (target || label || document.body).getBoundingClientRect();
        const section = (target || label || document.body).closest(".upload-form-item, .form-item, section, div") || document.body;
        const images = [...section.querySelectorAll("img")].filter(visible).map((img) => ({
          src: img.currentSrc || img.src || "",
          width: img.naturalWidth,
          height: img.naturalHeight,
          rect: (() => { const r = img.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })(),
          alt: img.alt || "",
        }));
        resolve({
          url: location.href,
          title: document.title,
          pageText: clean(document.body.innerText).slice(0, 3000),
          targetText: clean((target || label || document.body).innerText).slice(0, 1000),
          rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
          viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
          images,
        });
      }, 600));
    })()`,
  });
  const value = probe?.result?.value || {};
  const captureRect = value.rect || { x: 0, y: 0, width: 1000, height: 700 };
  const viewport = value.viewport || { width: 1600, height: 900 };
  const x = Math.max(0, Math.floor(captureRect.x - 220));
  const y = Math.max(0, Math.floor(captureRect.y - 160));
  const width = Math.min(Math.floor(viewport.width - x), Math.max(900, Math.floor(captureRect.width + 760)));
  const height = Math.min(Math.floor(viewport.height - y), Math.max(520, Math.floor(captureRect.height + 420)));
  const shot = await client.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    clip: { x, y, width, height, scale: 1 },
  });
  fs.writeFileSync(OUT, Buffer.from(shot.data, "base64"));
  console.log(JSON.stringify({ output: OUT, tab: { url: tab.url, title: tab.title }, probe: value }, null, 2));
} finally {
  client.close();
}
