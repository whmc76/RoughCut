const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");

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

const tabs = await fetchJson(`${CDP_URL}/json/list`);
const tab = tabs.find((entry) => /member\.bilibili\.com/.test(entry.url || ""));
const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
try {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      };
      const candidates = [...document.querySelectorAll("button, [role=button], .btn, .bcc-button, .radio, .bcc-radio, label, span, div, a")]
        .filter(visible)
        .map((el, index) => {
          const r = el.getBoundingClientRect();
          return {
            index,
            tag: el.tagName,
            text: clean(el.innerText || el.textContent).slice(0, 160),
            aria: el.getAttribute("aria-label") || "",
            role: el.getAttribute("role") || "",
            className: String(el.className || "").slice(0, 180),
            rect: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) },
            pointer: getComputedStyle(el).pointerEvents,
            cursor: getComputedStyle(el).cursor,
          };
        })
        .filter((item) => /发布前请添加创作声明|内容无需标注|去声明|确定|确认|完成|取消|提交中/.test(item.text) || item.rect.x > 650 && item.rect.x < 1200 && item.rect.y > 200 && item.rect.y < 560)
        .slice(0, 120);
      return { url: location.href, body: clean(document.body.innerText).slice(0, 2200), candidates };
    })()`,
  });
  console.log(JSON.stringify(result.result.value, null, 2));
} finally {
  client.close();
}
