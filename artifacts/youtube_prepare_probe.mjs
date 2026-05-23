const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const TITLE = "MOT风灵音叉推牌锆合金版开箱：值不值";
const BODY = "这期是 MOT 风灵音叉推牌锆合金版本的开箱和上手记录，重点看材质质感、分量、操作手感和版本差异。没有核验到具体参数，所以只按画面和实际到手体验聊：锆合金版更适合在意手感、质感和收藏感的用户。\n\n#MOT风灵 #音叉推牌 #锆合金 #EDC玩具 #开箱 #上手体验 #把玩件";

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
      this.pending.set(id, { resolve: (v) => { clearTimeout(timer); resolve(v); }, reject: (e) => { clearTimeout(timer); reject(e); } });
    });
  }
  close() { this.socket.close(); }
}

const tabs = await (await fetch(`${CDP_URL}/json/list`)).json();
const tab = tabs.find((entry) => entry.type === "page" && entry.url.includes("studio.youtube.com") && entry.webSocketDebuggerUrl);
if (!tab) throw new Error("YouTube Studio tab not found");
const client = await CdpClient.connect(tab.webSocketDebuggerUrl);
try {
  await client.send("Runtime.enable");
  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
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
      const setEditable = (el, value) => {
        el.focus();
        document.execCommand("selectAll", false, null);
        document.execCommand("insertText", false, value);
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      };
      const details = [...document.querySelectorAll("button")].find((el) => visible(el) && clean(el.innerText || el.textContent) === "详细信息");
      if (details) {
        click(details);
        await sleep(1800);
      }
      const editables = [...document.querySelectorAll("#textbox[contenteditable=true], ytcp-social-suggestions-textbox #textbox")]
        .filter(visible);
      const before = editables.map((el) => clean(el.innerText || el.textContent));
      if (editables[0]) setEditable(editables[0], ${JSON.stringify(TITLE)});
      await sleep(600);
      if (editables[1]) setEditable(editables[1], ${JSON.stringify(BODY)});
      await sleep(2000);
      const after = [...document.querySelectorAll("#textbox[contenteditable=true], ytcp-social-suggestions-textbox #textbox")]
        .filter(visible)
        .map((el) => clean(el.innerText || el.textContent));
      return { url: location.href, before, after, body: clean(document.body.innerText).slice(0, 2500) };
    })()`,
  });
  console.log(JSON.stringify(result.result.value, null, 2));
} finally {
  client.close();
}
