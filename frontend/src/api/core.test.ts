import { request, requestForm } from "./core";

describe("api core preview fallback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("converts static preview 404 responses into a predictable unavailable message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<html><body>File not found</body></html>", {
        status: 404,
        statusText: "File not found",
        headers: {
          "Content-Type": "text/html; charset=utf-8",
        },
      }),
    );

    await expect(request("/health/detail")).rejects.toThrow("预览模式下实时数据不可用。连接后端后可查看真实数据。");
  });

  it("converts unsupported API methods in static preview into the same unavailable message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("Unsupported method", {
        status: 501,
        statusText: "Unsupported method",
        headers: {
          "Content-Type": "text/plain; charset=utf-8",
        },
      }),
    );

    await expect(requestForm("/config", new FormData())).rejects.toThrow("预览模式下实时数据不可用。连接后端后可查看真实数据。");
  });
});
