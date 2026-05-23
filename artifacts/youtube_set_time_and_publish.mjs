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
      const setInput = (el, value) => {
        el.focus();
        el.value = value;
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        el.blur();
      };
      const inputs = [...document.querySelectorAll("input")].filter(visible);
      const time = inputs.find((el) => /^\\d{1,2}:\\d{2}$/.test(el.value || ""));
      if (time) setInput(time, "20:00");
      await sleep(2500);
      const bodyBeforeClick = clean(document.body.innerText);
      const publishButtons = [...document.querySelectorAll("button")].filter(visible).filter((el) => clean(el.innerText || el.textContent) === "预定");
      const button = publishButtons.find((el) => !(el.disabled || el.hasAttribute("disabled") || /disabled/.test(String(el.className || ""))));
      const verification = {
        hasTitle: /MOT风灵音叉推牌锆合金版开箱：值不值/.test(bodyBeforeClick),
        hasDate: /2026年5月23日/.test(bodyBeforeClick),
        hasFutureError: /请选择一个未来的时间/.test(bodyBeforeClick),
        hasVideoLink: /https:\\/\\/youtu\\.be\\//.test(bodyBeforeClick),
        buttonEnabled: Boolean(button),
        timeValue: time?.value || "",
      };
      if (verification.hasTitle && verification.hasDate && verification.hasVideoLink && verification.buttonEnabled && !verification.hasFutureError) {
        click(button);
        await sleep(7000);
      }
      const bodyAfterClick = clean(document.body.innerText);
      return {
        verification,
        clicked: verification.hasTitle && verification.hasDate && verification.hasVideoLink && verification.buttonEnabled && !verification.hasFutureError,
        bodyAfterClick: bodyAfterClick.slice(0, 2800),
        url: location.href,
      };
    })()`,
  });
  console.log(JSON.stringify(result.result.value, null, 2));
} finally {
  client.close();
}
