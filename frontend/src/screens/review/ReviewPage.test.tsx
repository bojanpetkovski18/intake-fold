import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ReviewDocument } from "../../api/types";
import { documentRow, renderApp, session, stubApi, type Reply } from "../../test-utils";

const URL = "/documents/d1";
const QUEUE = "GET /documents?status=needs_review";
const EMPTY_QUEUE = { body: { items: [], nextCursor: null } };

function review(overrides: Partial<ReviewDocument> = {}): ReviewDocument {
  return {
    ...documentRow(),
    version: 3,
    statusReasons: ["total_reconciles"],
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
      lineItems: [{ description: "Item", quantity: "2.00", unitPrice: "50.00", amount: "100.00" }],
    },
    overallConfidence: "high",
    uncertainFields: [],
    containsEmbeddedInstructions: false,
    ruleResults: [
      {
        rule: "total_reconciles",
        outcome: "fail",
        reasonCode: "total_mismatch",
        detail: "Subtotal, tax and adjustments come to 110.00, not the total 999.00.",
        fields: ["subtotal", "taxTotal", "adjustmentsTotal", "total"],
      },
      { rule: "known_vendor", outcome: "pass", reasonCode: null, detail: null, fields: [] },
    ],
    ...overrides,
  };
}

const CLEAN = review({ statusReasons: [], ruleResults: [] });

function open(api: Record<string, Reply | Reply[] | (() => Promise<Reply>)>) {
  const calls = stubApi({ "GET /auth/me": { body: session() }, ...api });
  const router = renderApp(URL);
  return { calls, router };
}

function bodyOf(calls: ReturnType<typeof stubApi>, key: string): unknown {
  const call = calls.find((item) => item.key === key);
  return JSON.parse(call?.init?.body as string);
}

function pressShortcut(code: string) {
  fireEvent.keyDown(window, { code, altKey: true, shiftKey: true });
}

describe("review states", () => {
  it("shows a loading state", async () => {
    open({
      "GET /documents/d1": () =>
        new Promise(() => {
          // Never answers, so the loading state stays on screen.
        }),
    });

    expect(await screen.findByText("Loading document")).toBeVisible();
  });

  it("shows a missing document as not found", async () => {
    open({ "GET /documents/d1": { status: 404, body: { detail: "There is no such document." } } });

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document not found" }),
    ).toBeVisible();
  });

  it("shows an error and recovers on retry", async () => {
    open({
      "GET /documents/d1": [{ status: 400, body: { detail: "It failed." } }, { body: review() }],
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { level: 1, name: "invoice.pdf" })).toBeVisible();
  });

  it("shows the status in plain words", async () => {
    open({ "GET /documents/d1": { body: review() } });

    const heading = await screen.findByRole("heading", { level: 1, name: "invoice.pdf" });
    expect(heading.parentElement).toHaveTextContent("Needs review");
    expect(heading.parentElement).not.toHaveTextContent("needs_review");
  });

  it("shows why the document is here, in plain words", async () => {
    open({
      "GET /documents/d1": {
        body: review({ statusReasons: ["total_reconciles", "embedded_instructions"] }),
      },
    });

    const reasons = await screen.findByRole("list", { name: "Why this document needs review" });
    expect(within(reasons).getByText("The totals do not add up.")).toBeVisible();
    expect(within(reasons).getByText(/text aimed at the extractor/)).toBeVisible();
  });

  it("offers empty fields when extraction failed", async () => {
    open({
      "GET /documents/d1": {
        body: review({
          fields: null,
          statusReasons: ["extraction_invalid"],
          ruleResults: [],
        }),
      },
    });

    expect(await screen.findByText(/need entering by hand/)).toBeVisible();
    expect(screen.getByLabelText("Vendor")).toHaveValue("");
    expect(screen.getByText("No line items.")).toBeVisible();
  });

  it("makes a finished document read-only", async () => {
    open({
      "GET /documents/d1": { body: review({ status: "approved", statusReasons: [] }) },
    });

    expect(await screen.findByText(/This document is finished/)).toBeVisible();
    expect(screen.getByLabelText("Total")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add line" })).not.toBeInTheDocument();
  });
});

describe("fields", () => {
  it("highlights a failed rule on its fields with the reason", async () => {
    open({ "GET /documents/d1": { body: review() } });

    const total = await screen.findByLabelText("Total");
    expect(total).toHaveAttribute("aria-invalid", "true");
    expect(total).toHaveAccessibleDescription(/come to 110\.00, not the total 999\.00/);
    expect(screen.getByLabelText("Currency")).not.toHaveAttribute("aria-invalid");
  });

  it("marks fields the extractor was unsure about", async () => {
    open({
      "GET /documents/d1": { body: review({ uncertainFields: ["vendorName"], ruleResults: [] }) },
    });

    expect(await screen.findByLabelText("Vendor")).toHaveAccessibleDescription(
      "The extractor was not sure about this field.",
    );
  });

  it("sends money exactly as typed, as strings", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: review() },
      "PATCH /documents/d1/fields": { body: review({ version: 4 }) },
    });
    const user = userEvent.setup();

    const total = await screen.findByLabelText("Total");
    await user.clear(total);
    await user.type(total, "12345678901234.1000");
    await user.click(screen.getByRole("button", { name: "Save corrections" }));

    await screen.findByText(/Corrections saved/);
    const sent = bodyOf(calls, "PATCH /documents/d1/fields") as {
      version: number;
      fields: ReviewDocument["fields"];
    };
    expect(sent.version).toBe(3);
    expect(sent.fields?.total).toBe("12345678901234.1000");
    expect(sent.fields?.lineItems[0]?.unitPrice).toBe("50.00");
    expect(sent.fields?.dueDate).toBeNull();
  });

  it("re-renders the rules after saving and moves focus to the result", async () => {
    open({
      "GET /documents/d1": { body: review() },
      "PATCH /documents/d1/fields": { body: { ...CLEAN, version: 4 } },
    });
    const user = userEvent.setup();

    const total = await screen.findByLabelText("Total");
    await user.clear(total);
    await user.type(total, "110.00");
    await user.click(screen.getByRole("button", { name: "Save corrections" }));

    const status = await screen.findByText(/Corrections saved/);
    expect(status).toHaveFocus();
    expect(screen.getByLabelText("Subtotal")).not.toHaveAttribute("aria-invalid");
    expect(screen.queryByRole("list", { name: /Why this document/ })).not.toBeInTheDocument();
  });

  it("does not send a save when nothing changed", async () => {
    const { calls } = open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Save corrections" }));

    await screen.findByText(/Corrections saved/);
    expect(calls.some((call) => call.key.startsWith("PATCH"))).toBe(false);
  });

  it("shows server field errors on their fields", async () => {
    open({
      "GET /documents/d1": { body: review({ ruleResults: [] }) },
      "PATCH /documents/d1/fields": {
        status: 422,
        body: {
          detail: "The request is not valid.",
          errors: [
            { field: "body.fields.total", message: "Use digits and a dot." },
            { field: "body.fields.lineItems.0.amount", message: "Not an amount." },
          ],
        },
      },
    });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Total"), "x");
    await user.click(screen.getByRole("button", { name: "Save corrections" }));

    await screen.findByRole("alert");
    expect(screen.getByLabelText("Total")).toHaveAccessibleDescription("Use digits and a dot.");
    expect(screen.getByLabelText("Line 1 amount")).toHaveAccessibleDescription("Not an amount.");
  });

  it("adds a line and moves focus to it", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Add line" }));

    expect(screen.getByLabelText("Line 2 description")).toHaveFocus();
  });

  it("removes a line and keeps focus on the page", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Remove line 1" }));

    expect(screen.queryByLabelText("Line 1 description")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add line" })).toHaveFocus();
  });
});

describe("preview", () => {
  it("shows the page with an accessible name and moves between pages", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    const image = await screen.findByRole("img", { name: "Page 1 of 2 of invoice.pdf" });
    expect(image).toHaveAttribute("src", "/api/documents/d1/pages/1");

    await user.click(screen.getByRole("button", { name: "Next page" }));

    expect(screen.getByRole("img", { name: "Page 2 of 2 of invoice.pdf" })).toHaveAttribute(
      "src",
      "/api/documents/d1/pages/2",
    );
    expect(screen.getByRole("button", { name: "Next page" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("zooms in steps", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Zoom in" }));

    expect(screen.getByText("150%")).toBeVisible();
    expect(screen.getByRole("group", { name: "Page image, scrollable" })).toHaveClass("zoom-150");
  });

  it("shows loading, then the page, then a failure", async () => {
    open({ "GET /documents/d1": { body: review() } });

    const image = await screen.findByRole("img", { name: /Page 1/ });
    expect(screen.getByText("Loading page")).toBeVisible();

    fireEvent.load(image);
    expect(screen.queryByText("Loading page")).not.toBeInTheDocument();

    fireEvent.error(image);
    expect(await screen.findByText("This page could not be loaded.")).toBeVisible();
  });

  it("says so when there are no pages yet", async () => {
    open({ "GET /documents/d1": { body: review({ pageCount: null }) } });

    expect(await screen.findByText(/No pages are available/)).toBeVisible();
  });

  it("switches between fields and preview", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    const preview = await screen.findByRole("button", { name: "Preview" });
    expect(screen.getByRole("button", { name: "Fields" })).toHaveAttribute("aria-pressed", "true");

    await user.click(preview);

    expect(preview).toHaveAttribute("aria-pressed", "true");
    expect(document.querySelector(".review-grid")).toHaveAttribute("data-view", "preview");
  });
});

describe("decisions", () => {
  it("approves a clean document and moves to the next one", async () => {
    const { calls, router } = open({
      "GET /documents/d1": { body: CLEAN },
      "POST /documents/d1/approve": { body: { ...CLEAN, status: "approved", version: 4 } },
      [QUEUE]: { body: { items: [documentRow(), documentRow({ id: "d2" })], nextCursor: null } },
      "GET /documents/d2": {
        body: { ...CLEAN, id: "d2", filename: "second.pdf" },
      },
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("heading", { level: 1, name: "second.pdf" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/documents/d2");
    expect(screen.getByText("invoice.pdf was approved.")).toBeVisible();
    expect(screen.getByRole("main")).toHaveFocus();
    expect(bodyOf(calls, "POST /documents/d1/approve")).toEqual({
      version: 3,
      overrideReason: null,
    });
  });

  it("returns to the inbox when the queue is clear", async () => {
    const { router } = open({
      "GET /documents/d1": { body: CLEAN },
      "POST /documents/d1/approve": { body: { ...CLEAN, status: "approved" } },
      [QUEUE]: EMPTY_QUEUE,
      "GET /documents": EMPTY_QUEUE,
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Approve" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/");
  });

  it("asks for an override reason when a rule failed", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: review() },
      "POST /documents/d1/approve": { body: review({ status: "approved" }) },
      [QUEUE]: EMPTY_QUEUE,
      "GET /documents": EMPTY_QUEUE,
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Approve" }));

    const reason = await screen.findByLabelText("A rule failed. Why approve anyway?");
    expect(reason).toHaveFocus();
    expect(calls.some((call) => call.key.includes("approve"))).toBe(false);

    await user.type(reason, "Vendor confirmed.");
    await user.click(screen.getByRole("button", { name: "Approve with override" }));

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(bodyOf(calls, "POST /documents/d1/approve")).toEqual({
      version: 3,
      overrideReason: "Vendor confirmed.",
    });
  });

  it("saves unsaved edits before approving, with the new version", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: review() },
      "PATCH /documents/d1/fields": { body: { ...CLEAN, version: 4 } },
      "POST /documents/d1/approve": { body: { ...CLEAN, status: "approved", version: 5 } },
      [QUEUE]: EMPTY_QUEUE,
      "GET /documents": EMPTY_QUEUE,
    });
    const user = userEvent.setup();

    const total = await screen.findByLabelText("Total");
    await user.clear(total);
    await user.type(total, "110.00");
    await user.click(screen.getByRole("button", { name: "Approve" }));

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    const keys = calls.map((call) => call.key);
    expect(keys.indexOf("PATCH /documents/d1/fields")).toBeLessThan(
      keys.indexOf("POST /documents/d1/approve"),
    );
    expect(bodyOf(calls, "POST /documents/d1/approve")).toMatchObject({ version: 4 });
  });

  it("rejects with a reason", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: review() },
      "POST /documents/d1/reject": { body: review({ status: "rejected" }) },
      [QUEUE]: EMPTY_QUEUE,
      "GET /documents": EMPTY_QUEUE,
    });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("Why is this document rejected?"), "Not ours.");
    await user.keyboard("{Tab}{Enter}");

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(bodyOf(calls, "POST /documents/d1/reject")).toEqual({
      version: 3,
      reason: "Not ours.",
    });
  });

  it("does not submit a blank reason", async () => {
    const { calls } = open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("Why is this document rejected?"), "   ");
    await user.keyboard("{Tab}{Enter}");

    expect(screen.getByLabelText("Why is this document rejected?")).toHaveFocus();
    expect(calls.some((call) => call.key.includes("reject"))).toBe(false);
  });

  it("closes the reason panel with Escape and returns focus", async () => {
    open({ "GET /documents/d1": { body: review() } });
    const user = userEvent.setup();

    const reject = await screen.findByRole("button", { name: "Reject" });
    await user.click(reject);
    await user.keyboard("{Escape}");

    expect(screen.queryByLabelText("Why is this document rejected?")).not.toBeInTheDocument();
    expect(reject).toHaveFocus();
  });

  it("tells the reviewer when someone else got there first, and reloads", async () => {
    const base = review();
    const changedByAnotherReviewer = {
      ...base,
      version: 9,
      fields: base.fields && { ...base.fields, vendorName: "Changed" },
    };
    open({
      "GET /documents/d1": [{ body: review() }, { body: changedByAnotherReviewer }],
      "PATCH /documents/d1/fields": {
        status: 409,
        body: { detail: "Someone else changed this document. Reload to continue." },
      },
    });
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Total"), "1");
    await user.click(screen.getByRole("button", { name: "Save corrections" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Someone else changed");

    await user.click(screen.getByRole("button", { name: "Reload this document" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Vendor")).toHaveValue("Changed");
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps focus on a busy button and ignores a second press", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: CLEAN },
      "POST /documents/d1/approve": () =>
        new Promise(() => {
          // Never answers, so the button stays busy.
        }),
    });
    const user = userEvent.setup();

    const approve = await screen.findByRole("button", { name: "Approve" });
    await user.click(approve);
    await waitFor(() => {
      expect(approve).toHaveAttribute("aria-disabled", "true");
    });
    expect(approve).toHaveFocus();

    await user.click(approve);

    expect(calls.filter((call) => call.key === "POST /documents/d1/approve")).toHaveLength(1);
  });
});

describe("keyboard", () => {
  it("documents the shortcuts on screen", async () => {
    open({ "GET /documents/d1": { body: review() } });

    await screen.findByLabelText("Total");
    for (const keys of ["Alt+Shift+S", "Alt+Shift+A", "Alt+Shift+R", "Alt+Shift+N"]) {
      expect(screen.getByText(keys)).toBeVisible();
    }
  });

  it("approves from the keyboard while a field has focus", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: CLEAN },
      "POST /documents/d1/approve": { body: { ...CLEAN, status: "approved" } },
      [QUEUE]: EMPTY_QUEUE,
      "GET /documents": EMPTY_QUEUE,
    });

    (await screen.findByLabelText("Total")).focus();
    pressShortcut("KeyA");

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(calls.map((call) => call.key)).toContain("POST /documents/d1/approve");
  });

  it("ignores a repeated shortcut while the first is running", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: CLEAN },
      "POST /documents/d1/approve": () =>
        new Promise(() => {
          // Never answers, so the first approval is still running.
        }),
    });

    await screen.findByLabelText("Total");
    pressShortcut("KeyA");
    await waitFor(() => {
      expect(calls.filter((call) => call.key.includes("approve"))).toHaveLength(1);
    });
    pressShortcut("KeyA");
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(calls.filter((call) => call.key.includes("approve"))).toHaveLength(1);
  });

  it("saves from the keyboard", async () => {
    open({ "GET /documents/d1": { body: review() } });

    await screen.findByLabelText("Total");
    pressShortcut("KeyS");

    expect(await screen.findByText(/Corrections saved/)).toBeVisible();
  });

  it("opens the reject reason from the keyboard", async () => {
    open({ "GET /documents/d1": { body: review() } });

    await screen.findByLabelText("Total");
    pressShortcut("KeyR");

    expect(await screen.findByLabelText("Why is this document rejected?")).toHaveFocus();
  });

  it("goes to the next document from the keyboard", async () => {
    const { router } = open({
      "GET /documents/d1": { body: review() },
      [QUEUE]: { body: { items: [documentRow({ id: "d2" })], nextCursor: null } },
      "GET /documents/d2": { body: { ...CLEAN, id: "d2", filename: "second.pdf" } },
    });

    await screen.findByLabelText("Total");
    pressShortcut("KeyN");

    expect(await screen.findByRole("heading", { level: 1, name: "second.pdf" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/documents/d2");
    expect(screen.getByLabelText("Total")).toHaveValue("999.00");
  });

  it("ignores decision shortcuts on a finished document", async () => {
    const { calls } = open({
      "GET /documents/d1": { body: review({ status: "approved" }) },
    });

    await screen.findByLabelText("Total");
    pressShortcut("KeyA");
    pressShortcut("KeyR");

    expect(screen.queryByLabelText("Why is this document rejected?")).not.toBeInTheDocument();
    expect(calls.some((call) => call.key.startsWith("POST"))).toBe(false);
  });

  it("uses a real link from the inbox", async () => {
    stubApi({
      "GET /auth/me": { body: session() },
      "GET /documents": { body: { items: [documentRow()], nextCursor: null } },
      "GET /documents/d1": { body: review() },
    });
    const user = userEvent.setup();
    const router = renderApp("/");

    await user.click(await screen.findByRole("link", { name: "invoice.pdf" }));

    expect(await screen.findByRole("heading", { level: 1, name: "invoice.pdf" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/documents/d1");
  });
});
