import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import { createQueryClient } from "./api/hooks";
import type { DeadJob, DocumentSummary, Role, Session } from "./api/types";
import { routes } from "./routes";

export interface Reply {
  status?: number;
  body?: unknown;
}

type Routes = Record<string, Reply | Reply[] | (() => Promise<Reply>)>;

export function session(role: Role = "reviewer"): Session {
  return {
    user: { id: "u1", email: `${role}@example.com`, displayName: "Riley Reviewer", role },
    csrfToken: "csrf-1",
    extractor: "mock",
  };
}

export function documentRow(overrides: Partial<DocumentSummary> = {}): DocumentSummary {
  return {
    id: "d1",
    filename: "invoice.pdf",
    mediaType: "application/pdf",
    sizeBytes: 1000,
    pageCount: 2,
    status: "needs_review",
    receivedAt: "2026-10-01T09:00:00Z",
    finishedAt: null,
    ...overrides,
  };
}

export function deadJob(overrides: Partial<DeadJob> = {}): DeadJob {
  return {
    id: "j1",
    kind: "process_document",
    attempts: 5,
    maxAttempts: 5,
    lastError: "render_failed",
    updatedAt: "2026-10-01T09:00:00Z",
    documentId: "d1",
    filename: "broken.pdf",
    ...overrides,
  };
}

export const SIGNED_OUT: Reply = { status: 401, body: { detail: "Sign in to continue." } };

/** Answers `METHOD /path?query` keys, and records every call. */
export function stubApi(api: Routes) {
  const calls: { key: string; init: RequestInit | undefined }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const key = `${init?.method ?? "GET"} ${url.replace("/api", "")}`;
      calls.push({ key, init });
      const entry = api[key];
      if (entry === undefined) {
        return new Response(JSON.stringify({ detail: `Unexpected ${key}` }), { status: 500 });
      }
      let reply: Reply;
      if (typeof entry === "function") {
        reply = await entry();
      } else if (Array.isArray(entry)) {
        reply = (entry.length > 1 ? entry.shift() : entry[0]) ?? {};
      } else {
        reply = entry;
      }
      const text = reply.body === undefined ? null : JSON.stringify(reply.body);
      return new Response(text, { status: reply.status ?? 200 });
    }),
  );
  return calls;
}

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(
    <QueryClientProvider client={createQueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}
