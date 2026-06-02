import type { PublicationAttempt } from "../../types";

export function publicationAttemptUrl(attempt: PublicationAttempt | null | undefined): string {
  return String(attempt?.public_url || attempt?.external_url || "").trim();
}

export function publicationAttemptReceiptId(attempt: PublicationAttempt | null | undefined): string {
  return String(attempt?.external_receipt_id || "").trim();
}
