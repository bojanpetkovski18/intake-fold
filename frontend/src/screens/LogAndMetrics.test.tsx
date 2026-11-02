import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { MetricsRow, RunLog, RunStepView } from "../api/types";
import { renderApp, session, stubApi, type Reply } from "../test-utils";

const ME = { "GET /auth/me": { body: session() } };
const NEVER = () =>
  new Promise<Reply>(() => {
    // Never answers, so the loading state stays on screen.
  });

function step(overrides: Partial<RunStepView> = {}): RunStepView {
  return {
    step: "extract",
    attempt: 1,
    status: "succeeded",
    startedAt: "2026-10-01T09:00:00Z",
    finishedAt: "2026-10-01T09:00:02Z",
    durationMs: 2000,
    extractor: "claude",
    model: "claude-opus-5-5",
    inputTokens: 1200,
    outputTokens: 300,
    cacheReadTokens: 0,
    cacheWriteTokens: 0,
    estimatedCostUsd: "0.010800",
    errorCode: null,
    ...overrides,
  };
}

const LOG: RunLog = {
  steps: [
    step({
      step: "render",
      extractor: null,
      model: null,
      inputTokens: null,
      outputTokens: null,
      estimatedCostUsd: null,
    }),
    step(),
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
    {
      action: "document_routed",
      field: null,
      oldValue: null,
      newValue: "needs_review",
      actorName: null,
      createdAt: "2026-10-01T09:00:03Z",
    },
  ],
};

const DELIVERED = [
  {
    target: "sink",
    eventId: "e1",
    status: "delivered",
    createdAt: "2026-10-01T09:06:00Z",
    attempts: [
      { attempt: 1, statusCode: 503, durationMs: 20, errorCode: "http_503", createdAt: "x" },
      { attempt: 2, statusCode: 200, durationMs: 4, errorCode: null, createdAt: "y" },
    ],
  },
];

function row(overrides: Partial<MetricsRow> = {}): MetricsRow {
  return {
    extractor: "mock",
    processed: 5,
    autoApproved: 2,
    wentToReview: 2,
    failed: 1,
    autoApprovedShare: "0.4000",
    reviewShare: "0.4000",
    failureShare: "0.2000",
    averageSeconds: "25.0",
    ...overrides,
  };
}

describe("document log", () => {
  it("shows a loading state", async () => {
    stubApi({ ...ME, "GET /documents/d1/run-log": NEVER, "GET /documents/d1/deliveries": NEVER });
    renderApp("/documents/d1/log");

    expect(await screen.findByText("Loading the document log")).toBeVisible();
  });

  it("shows steps with tokens and cost, the trail, and deliveries", async () => {
    stubApi({
      ...ME,
      "GET /documents/d1/run-log": { body: LOG },
      "GET /documents/d1/deliveries": { body: DELIVERED },
    });
    renderApp("/documents/d1/log");

    const extract = await screen.findByRole("row", { name: /extract/ });
    expect(within(extract).getByText("1200 / 300")).toBeVisible();
    expect(within(extract).getByText("0.010800")).toBeVisible();
    expect(within(extract).getByText("claude, claude-opus-5-5")).toBeVisible();
    const render = screen.getByRole("row", { name: /render/ });
    expect(within(render).getAllByText("None")).toHaveLength(3);
    const trail = screen.getByRole("region", { name: "Audit trail" });
    expect(within(trail).getByText(/^Riley Reviewer,/)).toBeVisible();
    expect(screen.getByText("total")).toBeVisible();
    expect(screen.getByText(/999\.00 to 110\.00/)).toBeVisible();
    expect(screen.getByText(/^System,/)).toBeVisible();
    expect(screen.getByText(/Attempt 1: 503 \(http_503\)/)).toBeVisible();
  });

  it("shows empty states", async () => {
    stubApi({
      ...ME,
      "GET /documents/d1/run-log": { body: { steps: [], events: [] } },
      "GET /documents/d1/deliveries": { body: [] },
    });
    renderApp("/documents/d1/log");

    expect(await screen.findByText("No steps have run yet.")).toBeVisible();
    expect(screen.getByText("Nothing has been recorded yet.")).toBeVisible();
    expect(screen.getByText(/No deliveries/)).toBeVisible();
  });

  it("shows a missing document as not found", async () => {
    stubApi({
      ...ME,
      "GET /documents/d1/run-log": { status: 404, body: { detail: "There is no such document." } },
      "GET /documents/d1/deliveries": { status: 404, body: { detail: "No." } },
    });
    renderApp("/documents/d1/log");

    expect(await screen.findByRole("heading", { name: "Document not found" })).toBeVisible();
  });

  it("shows an error and recovers", async () => {
    stubApi({
      ...ME,
      "GET /documents/d1/run-log": [{ status: 400, body: { detail: "Broken." } }, { body: LOG }],
      "GET /documents/d1/deliveries": { body: [] },
    });
    const user = userEvent.setup();
    renderApp("/documents/d1/log");

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("row", { name: /extract/ })).toBeVisible();
  });
});

describe("metrics", () => {
  it("shows a loading state", async () => {
    stubApi({ ...ME, "GET /metrics": NEVER });
    renderApp("/metrics");

    expect(await screen.findByText("Loading metrics")).toBeVisible();
  });

  it("is honest when nothing has been processed", async () => {
    stubApi({ ...ME, "GET /metrics": { body: { rows: [] } } });
    renderApp("/metrics");

    expect(await screen.findByText(/nothing to measure/)).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("labels each extractor, and says the mock is not accuracy", async () => {
    stubApi({
      ...ME,
      "GET /metrics": {
        body: {
          rows: [
            row({
              extractor: "claude",
              processed: 3,
              autoApprovedShare: "0.6667",
              averageSeconds: "4.5",
            }),
            row(),
            row({ extractor: "none", averageSeconds: null }),
          ],
        },
      },
    });
    renderApp("/metrics");

    const mock = await screen.findByRole("row", { name: /Mock \(plumbing test, not accuracy\)/ });
    expect(within(mock).getAllByText("40.00% (2)")).toHaveLength(2);
    expect(within(mock).getByText("20.00% (1)")).toBeVisible();
    expect(within(mock).getByText("25.0 s")).toBeVisible();
    const claude = screen.getByRole("row", { name: /claude/ });
    expect(within(claude).getByText("66.67% (2)")).toBeVisible();
    expect(
      within(screen.getByRole("row", { name: /Not extracted/ })).getByText("No timing"),
    ).toBeVisible();
  });

  it("shows whole shares exactly", async () => {
    stubApi({
      ...ME,
      "GET /metrics": {
        body: {
          rows: [
            row({ autoApprovedShare: "1.0000", reviewShare: "0.0000", failureShare: "0.0005" }),
          ],
        },
      },
    });
    renderApp("/metrics");

    const mock = await screen.findByRole("row", { name: /Mock/ });
    expect(within(mock).getByText(/^100\.00%/)).toBeVisible();
    expect(within(mock).getByText(/^0\.00%/)).toBeVisible();
    expect(within(mock).getByText(/^0\.05%/)).toBeVisible();
  });

  it("shows an error and recovers", async () => {
    stubApi({
      ...ME,
      "GET /metrics": [
        { status: 500, body: { detail: "Down." } },
        { status: 500, body: { detail: "Down." } },
        { status: 500, body: { detail: "Down." } },
        { body: { rows: [] } },
      ],
    });
    const user = userEvent.setup();
    renderApp("/metrics");

    await user.click(await screen.findByRole("button", { name: "Try again" }, { timeout: 8000 }));

    expect(await screen.findByText(/nothing to measure/)).toBeVisible();
  }, 10_000);
});
