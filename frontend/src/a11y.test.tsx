import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import type { ReviewDocument } from "./api/types";
import {
  deadJob,
  documentRow,
  renderApp,
  session,
  SIGNED_OUT,
  stubApi,
  type Reply,
} from "./test-utils";

// jsdom has no layout or paint, so contrast and anything visual is checked in a real browser
// for docs/AUDIT.md. Everything else axe knows runs here, on every screen and state.
const OPTIONS: axe.RunOptions = { rules: { "color-contrast": { enabled: false } } };

const NEVER = () =>
  new Promise<Reply>(() => {
    // Never answers, so the loading state stays on screen.
  });
const FAILED: Reply = { status: 500, body: { detail: "It broke.", traceId: "t1" } };
const NOT_FOUND: Reply = { status: 404, body: { detail: "There is no such document." } };
const EMPTY: Reply = { body: { items: [], nextCursor: null } };
const ME = { "GET /auth/me": { body: session() } };
const ADMIN_DEMO = { "GET /auth/me": { body: { ...session("admin"), demoMode: true } } };

const REVIEW: ReviewDocument = {
  ...documentRow(),
  version: 1,
  statusReasons: ["total_reconciles", "embedded_instructions"],
  fields: {
    documentType: "invoice",
    vendorName: "Tarnwell Freight",
    invoiceNumber: "INV-1",
    issueDate: "2026-09-01",
    dueDate: null,
    currency: "USD",
    subtotal: "100.00",
    taxTotal: "10.00",
    adjustmentsTotal: "0.00",
    total: "999.00",
    lineItems: [{ description: "Item", quantity: "2", unitPrice: "50.00", amount: "100.00" }],
  },
  overallConfidence: "low",
  uncertainFields: ["total"],
  containsEmbeddedInstructions: true,
  ruleResults: [
    {
      rule: "total_reconciles",
      outcome: "fail",
      reasonCode: "total_mismatch",
      detail: "Subtotal, tax and adjustments come to 110.00, not the total 999.00.",
      fields: ["subtotal", "taxTotal", "adjustmentsTotal", "total"],
    },
  ],
};

const METRICS = {
  rows: [
    {
      extractor: "mock",
      processed: 5,
      autoApproved: 2,
      wentToReview: 2,
      failed: 1,
      autoApprovedShare: "0.4000",
      reviewShare: "0.4000",
      failureShare: "0.2000",
      averageSeconds: "25.0",
    },
  ],
};

const LOG = {
  steps: [
    {
      step: "extract",
      attempt: 1,
      status: "succeeded",
      startedAt: "2026-10-01T09:00:00Z",
      finishedAt: "2026-10-01T09:00:02Z",
      durationMs: 2000,
      extractor: "mock",
      model: null,
      inputTokens: null,
      outputTokens: null,
      cacheReadTokens: null,
      cacheWriteTokens: null,
      estimatedCostUsd: null,
      errorCode: null,
    },
  ],
  events: [
    {
      action: "field_corrected",
      field: "total",
      oldValue: "999.00",
      newValue: "110.00",
      actorName: "Riley Reviewer",
      createdAt: "2026-10-01T09:05:00Z",
    },
  ],
};

const DELIVERIES = [
  {
    target: "sink",
    eventId: "e1",
    status: "delivered",
    createdAt: "2026-10-01T09:06:00Z",
    attempts: [{ attempt: 1, statusCode: 200, durationMs: 4, errorCode: null, createdAt: "x" }],
  },
];

async function expectNoViolations() {
  const results = await axe.run(document.body, OPTIONS);
  const found = results.violations.map(
    (violation) => `${violation.id}: ${violation.nodes.map((node) => node.html).join(" | ")}`,
  );
  expect(found).toEqual([]);
}

interface Case {
  name: string;
  path: string;
  api: Record<string, Reply | Reply[] | (() => Promise<Reply>)>;
  ready: () => Promise<unknown>;
}

const heading = (name: string) => () => screen.findByRole("heading", { level: 1, name });
const text = (value: string | RegExp) => () => screen.findByText(value);
// A 500 is retried twice with backoff before the error shows, about three seconds.
const alert = () => screen.findByRole("alert", {}, { timeout: 6000 });

const CASES: Case[] = [
  {
    name: "sign in",
    path: "/sign-in",
    api: { "GET /auth/me": SIGNED_OUT },
    ready: heading("Sign in"),
  },
  {
    name: "sign in with demo accounts",
    path: "/sign-in",
    api: {
      "GET /auth/me": SIGNED_OUT,
      "GET /demo": {
        body: {
          accounts: [{ email: "admin@example.com", role: "admin", password: "demo-pass-1234" }],
        },
      },
    },
    ready: text("demo-pass-1234"),
  },
  {
    name: "inbox loading",
    path: "/",
    api: { ...ME, "GET /documents": NEVER },
    ready: text("Loading documents"),
  },
  {
    name: "inbox empty",
    path: "/",
    api: { ...ME, "GET /documents": EMPTY },
    ready: heading("Inbox"),
  },
  { name: "inbox error", path: "/", api: { ...ME, "GET /documents": FAILED }, ready: alert },
  {
    name: "inbox with documents",
    path: "/",
    api: {
      ...ME,
      "GET /documents": {
        body: {
          items: [documentRow(), documentRow({ id: "d2", status: "failed", filename: "scan.png" })],
          nextCursor: "next",
        },
      },
    },
    ready: text("scan.png"),
  },
  {
    name: "inbox with the demo banner and reset question",
    path: "/",
    api: { ...ADMIN_DEMO, "GET /documents": EMPTY },
    ready: async () => {
      await userEvent.setup().click(await screen.findByRole("button", { name: "Reset demo data" }));
    },
  },
  {
    name: "review loading",
    path: "/documents/d1",
    api: { ...ME, "GET /documents/d1": NEVER },
    ready: text(/Loading/),
  },
  {
    name: "review not found",
    path: "/documents/d1",
    api: { ...ME, "GET /documents/d1": NOT_FOUND },
    ready: heading("Document not found"),
  },
  {
    name: "review error",
    path: "/documents/d1",
    api: { ...ME, "GET /documents/d1": FAILED },
    ready: alert,
  },
  {
    name: "review with failures and the override question",
    path: "/documents/d1",
    api: { ...ME, "GET /documents/d1": { body: REVIEW } },
    ready: async () => {
      await userEvent.setup().click(await screen.findByRole("button", { name: "Approve" }));
      await screen.findByLabelText("A rule failed. Why approve anyway?");
    },
  },
  {
    name: "log loading",
    path: "/documents/d1/log",
    api: { ...ME, "GET /documents/d1/run-log": NEVER, "GET /documents/d1/deliveries": NEVER },
    ready: text("Loading the document log"),
  },
  {
    name: "log empty",
    path: "/documents/d1/log",
    api: {
      ...ME,
      "GET /documents/d1/run-log": { body: { steps: [], events: [] } },
      "GET /documents/d1/deliveries": { body: [] },
    },
    ready: heading("Document log"),
  },
  {
    name: "log error",
    path: "/documents/d1/log",
    api: { ...ME, "GET /documents/d1/run-log": FAILED, "GET /documents/d1/deliveries": FAILED },
    ready: alert,
  },
  {
    name: "log with steps, trail and deliveries",
    path: "/documents/d1/log",
    api: {
      ...ME,
      "GET /documents/d1/run-log": { body: LOG },
      "GET /documents/d1/deliveries": { body: DELIVERIES },
    },
    ready: text("Riley Reviewer"),
  },
  {
    name: "metrics loading",
    path: "/metrics",
    api: { ...ME, "GET /metrics": NEVER },
    ready: text(/Loading/),
  },
  {
    name: "metrics empty",
    path: "/metrics",
    api: { ...ME, "GET /metrics": { body: { rows: [] } } },
    ready: heading("Metrics"),
  },
  { name: "metrics error", path: "/metrics", api: { ...ME, "GET /metrics": FAILED }, ready: alert },
  {
    name: "metrics with rows",
    path: "/metrics",
    api: { ...ME, "GET /metrics": { body: METRICS } },
    ready: text(/25.0/),
  },
  {
    name: "dead letters loading",
    path: "/dead-letters",
    api: { ...ME, "GET /jobs?status=dead": NEVER },
    ready: text("Loading dead jobs"),
  },
  {
    name: "dead letters empty",
    path: "/dead-letters",
    api: { ...ME, "GET /jobs?status=dead": EMPTY },
    ready: heading("Dead letters"),
  },
  {
    name: "dead letters error",
    path: "/dead-letters",
    api: { ...ME, "GET /jobs?status=dead": FAILED },
    ready: alert,
  },
  {
    name: "dead letters with a job, as admin",
    path: "/dead-letters",
    api: {
      ...ADMIN_DEMO,
      "GET /jobs?status=dead": { body: { items: [deadJob()], nextCursor: null } },
    },
    ready: () => screen.findByRole("button", { name: /Requeue/ }),
  },
  { name: "page not found", path: "/nowhere", api: ME, ready: heading("Page not found") },
];

describe("automated accessibility checks", () => {
  it.each(CASES)(
    "$name has no violations",
    async ({ path, api, ready }) => {
      stubApi(api);
      renderApp(path);
      await ready();
      await waitFor(expectNoViolations);
    },
    10_000,
  );
});
