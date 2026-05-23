const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const platform = process.argv[2] || "xiaohongshu";
const scrollY = Number(process.argv[3] || 0);

const domains = {
  xiaohongshu: ["creator.xiaohongshu.com"],
  kuaishou: ["cp.kuaishou.com/article/publish/video"],
  toutiao: ["mp.toutiao.com/profile_v4/xigua/publish-video"],
  youtube: ["studio.youtube.com"],
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
const wanted = domains[platform] || [platform];
const tab = tabs.find((entry) => {
  if (entry.type !== "page" || !entry.webSocketDebuggerUrl) return false;
  return wanted.some((needle) => entry.url.includes(needle));
});
if (!tab) throw new Error(`tab not found for ${platform}`);
const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
try {
  await client.send("Runtime.enable");
  const data = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      window.scrollTo(0, ${scrollY});
      return new Promise((resolve) => setTimeout(() => {
        const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
        };
        const elements = [...document.querySelectorAll("button,[role=button],input,textarea,[contenteditable=true],a,div,span")]
          .filter(visible)
          .map((el) => {
            const rect = el.getBoundingClientRect();
            const text = clean(el.innerText || el.textContent || el.value || el.getAttribute("placeholder") || el.getAttribute("aria-label"));
            return {
              tag: el.tagName,
              text: text.slice(0, 140),
              type: el.getAttribute("type") || "",
              accept: el.getAttribute("accept") || "",
              className: String(el.className || "").slice(0, 100),
              rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
            };
          })
          .filter((item) => item.text || item.accept)
          .filter((item) => /发布|定时|预约|提交|下一步|完成|保存|预定|公开视频|私享|上传|封面|合集|声明|原创|选择|时间|日期|标题|描述|正文|话题|Post|Schedule|Publish/i.test(item.text + item.accept + item.className))
          .slice(0, 160);
        resolve({ url: location.href, title: document.title, scrollY: window.scrollY, body: clean(document.body.innerText).slice(0, 3500), elements });
      }, 800));
    })()`,
  });
  console.log(JSON.stringify(data.result.value, null, 2));
} finally {
  client.close();
}
