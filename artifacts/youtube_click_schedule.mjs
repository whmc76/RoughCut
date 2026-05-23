const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");

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
      }, 60000);
      this.pending.set(id, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    });
  }
  close() { this.socket.close(); }
}

const tabs = await (await fetch(`${CDP_URL}/json/list`)).json();
const tab = tabs.find((entry) => entry.type === "page" && entry.url.includes("studio.youtube.com") && entry.webSocketDebuggerUrl);
const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
try {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    timeout: 50000,
    expression: `(async () => {
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
        const init = { bubbles: true, cancelable: true, view: window, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 };
        for (const type of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) el.dispatchEvent(new MouseEvent(type, init));
        if (typeof el.click === "function") el.click();
      };
      const before = clean(document.body.innerText);
      const button = [...document.querySelectorAll("button")].filter(visible).find((el) => clean(el.innerText || el.textContent) === "预定" && !(el.disabled || el.hasAttribute("disabled") || /disabled/.test(String(el.className || ""))));
      const gate = {
        hasTitle: /MOT风灵音叉推牌锆合金版开箱：值不值/.test(before),
        hasDate: /2026年5月23日/.test(before),
        hasVideoLink: /https:\\/\\/youtu\\.be\\//.test(before),
        checksPassed: /检查完毕。未发现任何问题/.test(before),
        buttonEnabled: Boolean(button),
      };
      if (Object.values(gate).every(Boolean)) click(button);
      await sleep(10000);
      const after = clean(document.body.innerText);
      return { gate, clicked: Object.values(gate).every(Boolean), after: after.slice(0, 3000), url: location.href };
    })()`,
  });
  console.log(JSON.stringify(result.result.value, null, 2));
} finally {
  client.close();
}
