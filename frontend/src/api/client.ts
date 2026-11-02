import type {
  DeadJob,
  DocumentStatus,
  DocumentSummary,
  Page,
  ReviewDocument,
  ReviewFields,
  Session,
  UploadedFile,
  UploadResult,
} from "./types";

const FALLBACK_DETAIL = "Something went wrong. Please try again.";

export interface FieldError {
  field: string;
  message: string;
}

interface Problem {
  detail?: string;
  traceId?: string | null;
  errors?: (UploadedFile | FieldError)[];
}

function isFieldError(error: UploadedFile | FieldError): error is FieldError {
  return "field" in error;
}

export class ApiError extends Error {
  readonly status: number;
  readonly traceId: string | null;
  readonly files: UploadedFile[];
  readonly fieldErrors: FieldError[];

  constructor(status: number, problem: Problem) {
    super(problem.detail ?? FALLBACK_DETAIL);
    this.name = "ApiError";
    this.status = status;
    this.traceId = problem.traceId ?? null;
    const errors = problem.errors ?? [];
    this.fieldErrors = errors.filter(isFieldError);
    this.files = errors.filter((error): error is UploadedFile => !isFieldError(error));
  }
}

// Kept in memory only: anything in web storage could be read by an injected script.
let csrfToken: string | null = null;

export function setCsrfToken(token: string | null) {
  csrfToken = token;
}

function parseProblem(text: string): Problem {
  try {
    return JSON.parse(text) as Problem;
  } catch {
    return {}; // A proxy error page, for example, is not JSON.
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.method && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, { detail: "The server could not be reached. Check your connection." });
  }
  const text = await response.text();
  if (!response.ok) {
    throw new ApiError(response.status, parseProblem(text));
  }
  return (text ? JSON.parse(text) : undefined) as T;
}

export async function getSession(): Promise<Session | null> {
  try {
    const session = await request<Session>("/auth/me");
    setCsrfToken(session.csrfToken);
    return session;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      setCsrfToken(null);
      return null;
    }
    throw error;
  }
}

export async function signIn(email: string, password: string): Promise<Session> {
  const session = await request<Session>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  setCsrfToken(session.csrfToken);
  return session;
}

export async function signOut(): Promise<void> {
  await request<unknown>("/auth/logout", { method: "POST" });
  setCsrfToken(null);
}

export interface DocumentQuery {
  status: DocumentStatus | null;
  cursor: string | null;
}

export function listDocuments({ status, cursor }: DocumentQuery): Promise<Page<DocumentSummary>> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (cursor) params.set("cursor", cursor);
  const query = params.size ? `?${params.toString()}` : "";
  return request<Page<DocumentSummary>>(`/documents${query}`);
}

export function getDocument(id: string): Promise<ReviewDocument> {
  return request<ReviewDocument>(`/documents/${id}`);
}

function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function correctDocument(
  id: string,
  version: number,
  fields: ReviewFields,
): Promise<ReviewDocument> {
  return sendJson("PATCH", `/documents/${id}/fields`, { version, fields });
}

export function approveDocument(
  id: string,
  version: number,
  overrideReason: string | null,
): Promise<ReviewDocument> {
  return sendJson("POST", `/documents/${id}/approve`, { version, overrideReason });
}

export function rejectDocument(
  id: string,
  version: number,
  reason: string,
): Promise<ReviewDocument> {
  return sendJson("POST", `/documents/${id}/reject`, { version, reason });
}

/** The next document waiting for a person, or null if the queue is clear. */
export async function nextInReview(currentId: string): Promise<string | null> {
  const page = await listDocuments({ status: "needs_review", cursor: null });
  return page.items.find((item) => item.id !== currentId)?.id ?? null;
}

export function listDeadJobs(cursor: string | null): Promise<Page<DeadJob>> {
  const params = new URLSearchParams({ status: "dead" });
  if (cursor) params.set("cursor", cursor);
  return request<Page<DeadJob>>(`/jobs?${params.toString()}`);
}

export async function retryJob(jobId: string): Promise<void> {
  await request<unknown>(`/jobs/${jobId}/retry`, { method: "POST" });
}

/** XMLHttpRequest, because fetch cannot report upload progress. */
export function uploadDocuments(
  files: File[],
  onProgress: (fraction: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const file of files) {
      form.append("files", file);
    }
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");
    if (csrfToken) {
      xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded / event.total);
      }
    };
    xhr.onerror = () => {
      reject(new ApiError(0, { detail: "The upload failed. Check your connection." }));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadResult);
        return;
      }
      const error = new ApiError(xhr.status, parseProblem(xhr.responseText));
      // Every file refused is still a per-file answer, not a failed request.
      if (error.files.length > 0) {
        resolve({ batchId: null, files: error.files });
      } else {
        reject(error);
      }
    };
    xhr.send(form);
  });
}
