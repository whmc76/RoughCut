const CDP_URL = (process.env.PUBLICATION_BROWSER_CDP_URL || "http://127.0.0.1:9222").replace(/\/$/, "");
const COVER = "\\\\Z4pro-gwil\\团队文件-媒体工作台\\EDC系列\\待发布\\MOT 风灵音叉推牌 锆合金版本\\smart-copy\\07-youtube-cover.jpg";

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
      }, 45000);
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
  await client.send("DOM.enable");
  const inspect = async () => (await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      return {
        body: clean(document.body.innerText).slice(0, 2600),
        buttons: [...document.querySelectorAll("button,ytcp-button,ytcp-icon-button")].filter(visible).map((el) => ({
          text: clean(el.innerText || el.textContent),
          aria: el.getAttribute("aria-label") || "",
          disabled: el.disabled || el.hasAttribute("disabled") || /disabled/.test(String(el.className || "")),
          className: String(el.className || "").slice(0, 120),
        })).slice(0, 80),
        inputs: [...document.querySelectorAll("input")].map((el) => ({
          type: el.type || "",
          accept: el.accept || "",
          value: el.value || "",
          visible: visible(el),
        })).slice(0, 40),
      };
    })()`,
  })).result.value;

  let actions = [];
  let root = await client.send("DOM.getDocument", { depth: -1, pierce: true });
  let input = await client.send("DOM.querySelector", { nodeId: root.root.nodeId, selector: "input[type=file][accept*='image']" });
  if (input.nodeId) {
    await client.send("DOM.setFileInputFiles", { nodeId: input.nodeId, files: [COVER] });
    actions.push({ kind: "thumbnail_upload", uploaded: true, path: COVER });
    await new Promise((resolve) => setTimeout(resolve, 3500));
  } else {
    actions.push({ kind: "thumbnail_upload", uploaded: false, reason: "image_file_input_not_found" });
  }
  const nav = await client.send("Runtime.evaluate", {
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
      for (let i = 0; i < 10; i++) {
        if (!/正在保存/.test(clean(document.body.innerText))) break;
        await sleep(1000);
      }
      let clicked = [];
      for (let i = 0; i < 3; i++) {
        const cont = [...document.querySelectorAll("button")].filter(visible).find((el) => clean(el.innerText || el.textContent) === "继续");
        if (!cont) break;
        click(cont);
        clicked.push("继续");
        await sleep(1500);
      }
      const visibility = [...document.querySelectorAll("button")].filter(visible).find((el) => clean(el.innerText || el.textContent) === "公开范围");
      if (visibility) { click(visibility); clicked.push("公开范围"); await sleep(1500); }
      return { clicked, body: clean(document.body.innerText).slice(0, 2400) };
    })()`,
  });
  actions.push({ kind: "navigate_visibility", ...nav.result.value });
  const after = await inspect();
  console.log(JSON.stringify({ actions, after }, null, 2));
} finally {
  client.close();
}
