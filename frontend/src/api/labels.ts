import type { DocumentStatus } from "./types";

export const STATUS_LABELS: Record<DocumentStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  auto_approved: "Auto-approved",
  needs_review: "Needs review",
  approved: "Approved",
  rejected: "Rejected",
  failed: "Failed",
};
