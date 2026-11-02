import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp, session, stubApi } from "../test-utils";

const ME = { body: session() };
const EMPTY = { body: { items: [], nextCursor: null } };
const CSV = "document_id,vendor\r\nd1,Example Vendor\r\n";

let saved: Blob[];
let clicked: string[];

beforeEach(() => {
  saved = [];
  clicked = [];
  // jsdom has no object URLs and does not download.
  URL.createObjectURL = (blob: Blob) => {
    saved.push(blob);
    return "blob:export";
  };
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    clicked.push(this.download);
  });
});

describe("export", () => {
  it("saves every approved invoice when no dates are given", async () => {
    const calls = stubApi({
      "GET /auth/me": ME,
      "GET /documents": EMPTY,
      "GET /exports/invoices.csv": { text: CSV },
    });
    renderApp("/");

    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    expect(await screen.findByText("Saved approved-invoices.csv.")).toHaveAttribute(
      "role",
      "status",
    );
    expect(calls.map((call) => call.key)).toContain("GET /exports/invoices.csv");
    expect(clicked).toEqual(["approved-invoices.csv"]);
    expect(await saved[0]?.text()).toBe(CSV);
  });

  it("sends only the dates that are set", async () => {
    const calls = stubApi({
      "GET /auth/me": ME,
      "GET /documents": EMPTY,
      "GET /exports/invoices.csv?from=2026-10-01": { text: CSV },
    });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Approved from"), "2026-10-01");
    await user.click(screen.getByRole("button", { name: "Export CSV" }));

    expect(await screen.findByText("Saved approved-invoices.csv.")).toBeInTheDocument();
    expect(calls.map((call) => call.key)).toContain("GET /exports/invoices.csv?from=2026-10-01");
  });

  it("shows why an export was refused and saves nothing", async () => {
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": EMPTY,
      "GET /exports/invoices.csv?from=2026-10-02&to=2026-10-01": {
        status: 422,
        body: { detail: "`from` must not be after `to`.", traceId: "t-9" },
      },
    });
    renderApp("/");
    const user = userEvent.setup();

    await user.type(await screen.findByLabelText("Approved from"), "2026-10-02");
    await user.type(screen.getByLabelText("Approved to"), "2026-10-01");
    await user.click(screen.getByRole("button", { name: "Export CSV" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("`from` must not be after `to`.");
    expect(alert).toHaveTextContent("Reference: t-9");
    expect(clicked).toEqual([]);
  });

  it("shows that it is busy while the export runs", async () => {
    let finish: (reply: { text: string }) => void = () => undefined;
    stubApi({
      "GET /auth/me": ME,
      "GET /documents": EMPTY,
      "GET /exports/invoices.csv": () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    });
    renderApp("/");

    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    const button = screen.getByRole("button", { name: "Exporting" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    finish({ text: CSV });
    expect(await screen.findByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });
});
