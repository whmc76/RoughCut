import { describe, expect, it } from "vitest";

import {
  publicationAttemptCoverPath,
  publicationAttemptCoverPreviewUrl,
  publicationAttemptReceiptId,
  publicationAttemptUrl,
} from "./publicationAttempt";

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

  it("reads the cover path from the top-level attempt contract", () => {
    expect(
      publicationAttemptCoverPath({
        cover_path: "E:/covers/cover.jpg",
      } as never),
    ).toBe("E:/covers/cover.jpg");
  });

  it("falls back to nested request payload cover fields", () => {
    expect(
      publicationAttemptCoverPath({
        request_payload: {
          copy_material: {
            cover_slots: [{ cover_path: "E:/covers/from-slot.jpg" }],
          },
        },
      } as never),
    ).toBe("E:/covers/from-slot.jpg");
  });

  it("builds a local preview url for attempt covers", () => {
    expect(
      publicationAttemptCoverPreviewUrl({
        cover_path: "E:/covers/cover.jpg",
        updated_at: "2026-06-04T10:30:00+08:00",
      } as never),
    ).toContain("/__roughcut_local_image?path=");
  });
});
