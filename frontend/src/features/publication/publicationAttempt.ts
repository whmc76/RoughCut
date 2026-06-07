import type { PublicationAttempt } from "../../types";

export function publicationAttemptUrl(attempt: PublicationAttempt | null | undefined): string {
  return String(attempt?.public_url || attempt?.external_url || "").trim();
}

export function publicationAttemptReceiptId(attempt: PublicationAttempt | null | undefined): string {
  return String(attempt?.external_receipt_id || "").trim();
}

export function publicationAttemptCoverPath(attempt: PublicationAttempt | null | undefined): string {
  if (!attempt) return "";
  const topLevel = String(attempt.cover_path || "").trim();
  if (topLevel) return topLevel;
  return extractCoverPathFromPayload(attempt.request_payload);
}

export function publicationAttemptCoverPreviewUrl(attempt: PublicationAttempt | null | undefined): string {
  const coverPath = publicationAttemptCoverPath(attempt);
  if (!coverPath) return "";
  const version = publicationAttemptCoverVersion(attempt);
  return `/__roughcut_local_image?path=${encodeURIComponent(coverPath)}&v=${encodeURIComponent(version || coverPath)}`;
}

function publicationAttemptCoverVersion(attempt: PublicationAttempt | null | undefined): string {
  if (!attempt) return "";
  const requestPayload = asRecord(attempt.request_payload);
  const responsePayload = asRecord(attempt.response_payload);
  return (
    String(responsePayload?.updated_at || "") ||
    String(requestPayload?.publication_plan_signature || "") ||
    String(attempt.updated_at || "") ||
    ""
  ).trim();
}

function extractCoverPathFromPayload(payload: Record<string, unknown> | undefined): string {
  const record = asRecord(payload);
  if (!record) return "";
  const direct = String(record.cover_path || "").trim();
  if (direct) return direct;
  const slotCover = extractCoverPathFromSlots(record.cover_slots);
  if (slotCover) return slotCover;
  const copyMaterial = asRecord(record.copy_material);
  if (!copyMaterial) return "";
  const copyDirect = String(copyMaterial.cover_path || "").trim();
  if (copyDirect) return copyDirect;
  return extractCoverPathFromSlots(copyMaterial.cover_slots);
}

function extractCoverPathFromSlots(value: unknown): string {
  if (!Array.isArray(value)) return "";
  for (const item of value) {
    const coverPath = String(asRecord(item)?.cover_path || "").trim();
    if (coverPath) return coverPath;
  }
  return "";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}
