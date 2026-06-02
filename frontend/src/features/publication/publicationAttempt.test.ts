import { describe, expect, it } from "vitest";

import { publicationAttemptReceiptId, publicationAttemptUrl } from "./publicationAttempt";

describe("publicationAttempt helpers", () => {
  it("reads the unique receipt binding id from the attempt payload", () => {
    expect(
      publicationAttemptReceiptId({
        external_receipt_id: "receipt-binding:abc123",
      } as never),
    ).toBe("receipt-binding:abc123");
  });

  it("prefers public_url over external_url for attempt tracking links", () => {
    expect(
      publicationAttemptUrl({
        public_url: "https://public.example/video/1",
        external_url: "https://backstage.example/video/1",
      } as never),
    ).toBe("https://public.example/video/1");
  });
});
