// Written by hand: openapi-typescript needs TypeScript 5, and this project is on 6 (D-060).

export type Role = "reviewer" | "admin";

export interface User {
  id: string;
  email: string;
  displayName: string;
  role: Role;
}

export interface Session {
  user: User;
  csrfToken: string;
  extractor: "mock" | "claude";
}

export const DOCUMENT_STATUSES = [
  "queued",
  "processing",
  "auto_approved",
  "needs_review",
  "approved",
  "rejected",
  "failed",
] as const;

export type DocumentStatus = (typeof DOCUMENT_STATUSES)[number];

export interface DocumentSummary {
  id: string;
  filename: string;
  mediaType: string;
  sizeBytes: number;
  pageCount: number | null;
  status: DocumentStatus;
  receivedAt: string;
  finishedAt: string | null;
}

export interface Page<T> {
  items: T[];
  nextCursor: string | null;
}

export interface UploadedFile {
  filename: string;
  documentId: string | null;
  deduplicated: boolean;
  code: string | null;
  detail: string | null;
}

export interface UploadResult {
  batchId: string | null;
  files: UploadedFile[];
}

export interface DeadJob {
  id: string;
  kind: string;
  attempts: number;
  maxAttempts: number;
  lastError: string | null;
  updatedAt: string;
  documentId: string | null;
  filename: string | null;
}
