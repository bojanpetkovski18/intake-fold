import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { documentRow, renderApp, session, stubApi } from "../test-utils";

const ME = { body: session() };
const EMPTY = { body: { items: [], nextCursor: null } };
const ONE = { body: { items: [documentRow()], nextCursor: null } };

class FakeXhr {
  static instances: FakeXhr[] = [];
  static status = 201;
  static response: unknown = { batchId: "b1", files: [] };

  status = 0;
  responseText = "";
  headers: Record<string, string> = {};
  sent: FormData | null = null;
  upload: { onprogress: ((event: Partial<ProgressEvent>) => void) | null } = { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }

  open() {
    return undefined;
  }

  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }

  send(form: FormData) {
    this.sent = form;
  }

  finish() {
    this.status = FakeXhr.status;
    this.responseText = JSON.stringify(FakeXhr.response);
    this.onload?.();
  }
}

function useFakeXhr(status: number, response: unknown) {
  FakeXhr.instances = [];
  FakeXhr.status = status;
  FakeXhr.response = response;
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
}

function latestXhr(): FakeXhr {
  const xhr = FakeXhr.instances.at(-1);
  if (!xhr) throw new Error("No upload was started.");
  return xhr;
}

const pdf = new File(["%PDF-"], "invoice.pdf", { type: "application/pdf" });

async function chooseAndUpload(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(await screen.findByLabelText(/Invoices and receipts/), pdf);
  await user.click(screen.getByRole("button", { name: "Upload" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("document list", () => {
  it("shows a loading state", async () => {
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": () =>
        new Promise(() => {
          // Never answers, so the loading state stays on screen.
        }),
    });
    renderApp("/");

    expect(await screen.findByText("Loading documents")).toBeVisible();
  });

  it("shows an empty state", async () => {
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    renderApp("/");

    expect(await screen.findByText("No documents yet. Upload one to get started.")).toBeVisible();
  });

  it("shows an empty state that names the filter", async () => {
    stubApi({ "GET /auth/me": ME, "GET /documents?status=failed": EMPTY });
    renderApp("/?status=failed");

    expect(await screen.findByText("No documents are failed.")).toBeVisible();
  });

  it("shows documents", async () => {
    stubApi({ "GET /auth/me": ME, "GET /documents": ONE });
    renderApp("/");

    const row = await screen.findByRole("row", { name: /invoice\.pdf/ });
    expect(within(row).getByText("Needs review")).toBeVisible();
    expect(within(row).getByText("2")).toBeVisible();
  });

  it("shows an error, with its reference, and recovers on retry", async () => {
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": [{ status: 400, body: { detail: "Bad list.", traceId: "t-1" } }, ONE],
    });
    const user = userEvent.setup();
    renderApp("/");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Bad list.");
    expect(alert).toHaveTextContent("Reference: t-1");

    await user.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("row", { name: /invoice\.pdf/ })).toBeVisible();
  });

  it("filters by status through the address", async () => {
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": ONE,
      "GET /documents?status=failed": EMPTY,
    });
    const user = userEvent.setup();
    const router = renderApp("/");

    await user.selectOptions(await screen.findByLabelText("Status"), "Failed");

    expect(await screen.findByText("No documents are failed.")).toBeVisible();
    expect(router.state.location.search).toBe("?status=failed");
  });

  it("ignores an unknown status in the address", async () => {
    const calls = stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    renderApp("/?status=nonsense");

    await screen.findByText("No documents yet. Upload one to get started.");
    expect(calls.map((call) => call.key)).toContain("GET /documents");
  });

  it("loads more and keeps earlier rows", async () => {
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": { body: { items: [documentRow()], nextCursor: "next" } },
      "GET /documents?cursor=next": {
        body: { items: [documentRow({ id: "d2", filename: "second.pdf" })], nextCursor: null },
      },
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("row", { name: /second\.pdf/ })).toBeVisible();
    expect(screen.getByRole("row", { name: /invoice\.pdf/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("polls while work is active and stops when it ends", async () => {
    const calls = stubApi({
      "GET /auth/me": ME,
      "GET /documents": [
        { body: { items: [documentRow({ status: "queued" })], nextCursor: null } },
        { body: { items: [documentRow({ status: "auto_approved" })], nextCursor: null } },
      ],
    });
    renderApp("/");

    const row = await screen.findByRole("row", { name: /invoice\.pdf/ });
    expect(row).toHaveTextContent("Queued");
    await waitFor(
      () => {
        expect(screen.getByRole("row", { name: /invoice\.pdf/ })).toHaveTextContent(
          "Auto-approved",
        );
      },
      { timeout: 4000 },
    );

    const finished = calls.filter((call) => call.key === "GET /documents").length;
    await new Promise((resolve) => setTimeout(resolve, 2300));
    expect(calls.filter((call) => call.key === "GET /documents")).toHaveLength(finished);
  }, 10_000);
});

describe("upload", () => {
  it("sends the files with the CSRF token and shows progress", async () => {
    useFakeXhr(201, {
      batchId: "b1",
      files: [
        {
          filename: "invoice.pdf",
          documentId: "d1",
          deduplicated: false,
          code: null,
          detail: null,
        },
      ],
    });
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);

    const xhr = latestXhr();
    expect(xhr.headers["X-CSRF-Token"]).toBe("csrf-1");
    expect(xhr.sent?.getAll("files")).toHaveLength(1);
    const busy = screen.getByRole("button", { name: "Uploading" });
    expect(busy).toHaveFocus();
    expect(busy).toHaveAttribute("aria-disabled", "true");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
    await waitFor(() => {
      expect(screen.getByRole("progressbar", { name: "Upload progress" })).toHaveAttribute(
        "value",
        "0.5",
      );
    });

    xhr.finish();

    expect(await screen.findByRole("status")).toHaveTextContent("1 of 1 accepted.");
    expect(screen.getByRole("button", { name: "Upload" })).toHaveFocus();
  });

  it("refreshes the list after an upload", async () => {
    useFakeXhr(201, { batchId: "b1", files: [] });
    stubApi({ "GET /auth/me": ME, "GET /documents": [EMPTY, ONE] });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);
    latestXhr().finish();

    expect(await screen.findByRole("row", { name: /invoice\.pdf/ })).toBeVisible();
  });

  it("shows each refused file with its reason", async () => {
    useFakeXhr(201, {
      batchId: "b1",
      files: [
        { filename: "good.pdf", documentId: "d1", deduplicated: false, code: null, detail: null },
        {
          filename: "old.pdf",
          documentId: "d2",
          deduplicated: true,
          code: null,
          detail: null,
        },
        {
          filename: "bad.pdf",
          documentId: null,
          deduplicated: false,
          code: "unsupported_type",
          detail: "Only PDF, PNG and JPEG files are accepted.",
        },
      ],
    });
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);
    latestXhr().finish();

    expect(await screen.findByRole("status")).toHaveTextContent("2 of 3 accepted.");
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toContain("good.pdf: Queued.");
    expect(items).toContain("old.pdf: Already uploaded.");
    expect(items).toContain("bad.pdf: Only PDF, PNG and JPEG files are accepted.");
  });

  it("treats every file refused as per-file errors", async () => {
    useFakeXhr(422, {
      detail: "No file was accepted.",
      errors: [
        {
          filename: "bad.pdf",
          documentId: null,
          deduplicated: false,
          code: "too_large",
          detail: "The limit is 10 MiB for this type.",
        },
      ],
    });
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);
    latestXhr().finish();

    expect(await screen.findByRole("status")).toHaveTextContent("0 of 1 accepted.");
    expect(screen.getByText(/The limit is 10 MiB/)).toBeVisible();
  });

  it("shows a failed request as an error", async () => {
    useFakeXhr(429, { detail: "Too many uploads. Try again later." });
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);
    latestXhr().finish();

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many uploads");
  });

  it("reports a lost connection", async () => {
    useFakeXhr(0, {});
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await chooseAndUpload(user);
    latestXhr().onerror?.();

    expect(await screen.findByRole("alert")).toHaveTextContent("Check your connection");
  });

  it("moves focus to the file field when nothing was chosen", async () => {
    useFakeXhr(201, { batchId: null, files: [] });
    stubApi({ "GET /auth/me": ME, "GET /documents": EMPTY });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Upload" }));

    expect(screen.getByLabelText(/Invoices and receipts/)).toHaveFocus();
    expect(FakeXhr.instances).toHaveLength(0);
  });
});
