const cdpBaseUrl = process.argv[2] || "http://127.0.0.1:9223";
const targetUrl = process.argv[3] || "";

async function main() {
  const normalizedBaseUrl = cdpBaseUrl.replace(/\/+$/u, "");
  if (targetUrl) {
    await fetch(`${normalizedBaseUrl}/json/new?${encodeURIComponent(targetUrl)}`, { method: "PUT" });
    await new Promise((resolve) => setTimeout(resolve, 3000));
  }
  const pages = await fetch(`${normalizedBaseUrl}/json/list`).then((response) => response.json());
  const page = targetUrl
    ? pages.find((entry) => entry.type === "page" && String(entry.url || "").includes(targetUrl))
    : pages.find((entry) => entry.type === "page");
  if (!page?.webSocketDebuggerUrl) {
    throw new Error("dreamina_dom_page_not_found");
  }
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = (event) => reject(event?.error || new Error("dreamina_dom_ws_error"));
  });
  let nextId = 1;
  const pending = new Map();
  socket.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    if (!payload.id || !pending.has(payload.id)) {
      return;
    }
    const { resolve, reject } = pending.get(payload.id);
    pending.delete(payload.id);
    if (payload.error) {
      reject(new Error(payload.error.message || "dreamina_dom_cdp_error"));
      return;
    }
    resolve(payload.result ?? {});
  };
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
      socket.send(JSON.stringify({ id, method, params }));
    });

  await send("Runtime.enable");
  const expression = `(() => {
    const inputs = Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"]'))
      .map((entry, index) => ({
        index,
        tag: entry.tagName,
        type: entry.getAttribute('type') || '',
        placeholder:
          entry.getAttribute('placeholder') ||
          entry.getAttribute('data-placeholder') ||
          entry.getAttribute('aria-label') ||
          '',
        text: String(entry.innerText || entry.value || '').slice(0, 120),
        className: String(entry.className || ''),
        rect: (() => {
          const r = entry.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height };
        })()
      }))
      .filter((entry) => entry.rect.w > 10 && entry.rect.h > 10);
    const buttons = Array.from(document.querySelectorAll('button'))
      .map((entry, index) => ({
        index,
        text: String(entry.innerText || '').trim(),
        className: String(entry.className || ''),
        disabled: entry.disabled === true,
        rect: (() => {
          const r = entry.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height };
        })()
      }))
      .filter((entry) => entry.rect.w > 20 && entry.rect.h > 20);
    return {
      title: document.title,
      url: location.href,
      inputs,
      buttons
    };
  })()`;
  const result = await send("Runtime.evaluate", {
    expression,
    returnByValue: true,
  });
  console.log(JSON.stringify(result.result?.value || {}, null, 2));
  socket.close();
}

main().catch((error) => {
  console.error(error?.stack || String(error));
  process.exitCode = 1;
});
