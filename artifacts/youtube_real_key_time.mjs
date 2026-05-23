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
  await client.send("Input.setIgnoreInputEvents", { ignore: false });
  const locate = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const input = [...document.querySelectorAll("input")].filter(visible).find((el) => /^\\d{1,2}:\\d{2}$/.test(el.value || ""));
      if (!input) return null;
      input.scrollIntoView({ block: "center", inline: "center" });
      const r = input.getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2, value: input.value };
    })()`,
  });
  const pos = locate.result.value;
  if (!pos) throw new Error("time input not found");
  await client.send("Input.dispatchMouseEvent", { type: "mousePressed", x: pos.x, y: pos.y, button: "left", clickCount: 1 });
  await client.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: pos.x, y: pos.y, button: "left", clickCount: 1 });
  await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17, modifiers: 2 });
  await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "a", code: "KeyA", windowsVirtualKeyCode: 65, modifiers: 2 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Control", code: "ControlLeft", windowsVirtualKeyCode: 17 });
  await client.send("Input.insertText", { text: "20:00" });
  await client.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Tab", code: "Tab", windowsVirtualKeyCode: 9 });
  await new Promise((resolve) => setTimeout(resolve, 4000));
  const result = await client.send("Runtime.evaluate", {
    awaitPromise: true,
    returnByValue: true,
    expression: `(() => {
      const clean = (value) => String(value || "").replace(/\\s+/g, " ").trim();
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const input = [...document.querySelectorAll("input")].filter(visible).find((el) => /^\\d{1,2}:\\d{2}$/.test(el.value || ""));
      const buttons = [...document.querySelectorAll("button")].filter(visible).filter((el) => clean(el.innerText || el.textContent) === "预定").map((el) => ({
        disabled: el.disabled || el.hasAttribute("disabled") || /disabled/.test(String(el.className || "")),
        className: String(el.className || ""),
      }));
      return { time: input?.value || "", buttons, body: clean(document.body.innerText).slice(0, 1800) };
    })()`,
  });
  console.log(JSON.stringify({ before: pos, after: result.result.value }, null, 2));
} finally {
  client.close();
}
