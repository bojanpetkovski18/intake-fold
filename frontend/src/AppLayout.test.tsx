import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { documentRow, renderApp, session, SIGNED_OUT, stubApi, type Reply } from "./test-utils";

const EMPTY = { body: { items: [], nextCursor: null } };

function signedIn() {
  return stubApi({
    "GET /auth/me": { body: session() },
    "GET /documents": EMPTY,
    "GET /metrics": { body: { rows: [] } },
  });
}

describe("app shell", () => {
  it("shows the inbox and marks its link as current", async () => {
    signedIn();
    renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Metrics" })).not.toHaveAttribute("aria-current");
  });

  it("moves focus to the main region after keyboard navigation", async () => {
    signedIn();
    const user = userEvent.setup();
    renderApp("/");

    (await screen.findByRole("link", { name: "Metrics" })).focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { level: 1, name: "Metrics" })).toBeVisible();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("does not take focus on first render", async () => {
    signedIn();
    renderApp("/");

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(screen.getByRole("main")).not.toHaveFocus();
  });

  it("offers a way back from an unknown address", async () => {
    signedIn();
    renderApp("/nowhere");

    expect(await screen.findByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to the inbox" })).toHaveAttribute("href", "/");
  });

  it("gives keyboard users a way past the header", () => {
    stubApi({ "GET /auth/me": SIGNED_OUT });
    renderApp("/sign-in");

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
  });

  it("shows the banner while the mock is active", async () => {
    signedIn();
    renderApp("/");

    expect(await screen.findByText(/Mock extractor/)).toBeVisible();
  });

  it("shows no banner with a real model", async () => {
    stubApi({
      "GET /auth/me": { body: { ...session(), extractor: "claude" } },
      "GET /documents": EMPTY,
    });
    renderApp("/");

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(screen.queryByText(/Mock extractor/)).not.toBeInTheDocument();
  });

  it("hides the navigation until signed in", async () => {
    stubApi({ "GET /auth/me": SIGNED_OUT });
    renderApp("/sign-in");

    await screen.findByRole("heading", { level: 1, name: "Sign in" });
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("signs out on the server and moves focus to the sign-in page", async () => {
    const calls = stubApi({
      "GET /auth/me": [{ body: session() }, SIGNED_OUT],
      "GET /documents": EMPTY,
      "POST /auth/logout": { status: 204 },
    });
    const user = userEvent.setup();
    const router = renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/sign-in");
    });
    expect(calls.map((call) => call.key)).toContain("POST /auth/logout");
    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("never shows the previous person's documents to the next one", async () => {
    let lists = 0;
    let current: Reply = { body: session() };
    stubApi({
      "GET /auth/me": () => Promise.resolve(current),
      "GET /documents": () => {
        lists += 1;
        return lists === 1
          ? Promise.resolve({
              body: { items: [documentRow({ filename: "private.pdf" })], nextCursor: null },
            })
          : new Promise(() => {
              // Never answers, so only a cached list could put a row on screen.
            });
      },
      "POST /auth/logout": () => {
        current = SIGNED_OUT;
        return Promise.resolve({ status: 204 });
      },
      "POST /auth/login": () => {
        current = { body: session("admin") };
        return Promise.resolve(current);
      },
    });
    const user = userEvent.setup();
    renderApp("/");

    await screen.findByRole("row", { name: /private\.pdf/ });
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    await user.type(await screen.findByLabelText("Email"), "admin@example.com");
    await user.type(screen.getByLabelText("Password"), "a-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    expect(await screen.findByText("Loading documents")).toBeVisible();
    expect(screen.queryByRole("row", { name: /private\.pdf/ })).not.toBeInTheDocument();
  });

  it("returns to sign-in when the session expires during use", async () => {
    stubApi({
      "GET /auth/me": [{ body: session() }, SIGNED_OUT],
      "GET /documents": SIGNED_OUT,
    });
    const router = renderApp("/");

    expect(await screen.findByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/sign-in");
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("sends the CSRF token on unsafe requests", async () => {
    const calls = stubApi({
      "GET /auth/me": { body: session() },
      "GET /documents": EMPTY,
      "POST /auth/logout": { status: 204 },
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      const logout = calls.find((call) => call.key === "POST /auth/logout");
      expect(new Headers(logout?.init?.headers).get("X-CSRF-Token")).toBe("csrf-1");
    });
  });

  it("reports a sign-out that failed", async () => {
    stubApi({
      "GET /auth/me": { body: session() },
      "GET /documents": EMPTY,
      "POST /auth/logout": { status: 500, body: { detail: "It broke.", traceId: "abc" } },
    });
    const user = userEvent.setup();
    renderApp("/");

    await user.click(await screen.findByRole("button", { name: "Sign out" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("It broke.");
    expect(screen.getByRole("alert")).toHaveTextContent("Reference: abc");
  });

  describe("demo mode", () => {
    function demo(role: "reviewer" | "admin", extra: Record<string, Reply | Reply[]> = {}) {
      return stubApi({
        "GET /auth/me": { body: { ...session(role), demoMode: true } },
        "GET /documents": EMPTY,
        ...extra,
      });
    }

    it("shows the demo banner without a reset control to a reviewer", async () => {
      demo("reviewer");
      renderApp("/");

      expect(await screen.findByRole("region", { name: "Demo mode" })).toHaveTextContent(
        "fictional",
      );
      expect(screen.queryByRole("button", { name: "Reset demo data" })).not.toBeInTheDocument();
    });

    it("shows no demo banner outside demo mode", async () => {
      signedIn();
      renderApp("/");

      await screen.findByRole("heading", { level: 1, name: "Inbox" });
      expect(screen.queryByRole("region", { name: "Demo mode" })).not.toBeInTheDocument();
    });

    it("asks before resetting, and cancel changes nothing", async () => {
      const calls = demo("admin");
      const user = userEvent.setup();
      renderApp("/");

      const trigger = await screen.findByRole("button", { name: "Reset demo data" });
      await user.click(trigger);

      expect(screen.getByRole("group", { name: /Delete every document/ })).toBeVisible();
      expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
      await user.keyboard("{Escape}");

      expect(screen.queryByRole("group", { name: /Delete every document/ })).toBeNull();
      expect(screen.getByRole("button", { name: "Reset demo data" })).toHaveFocus();
      expect(calls.some((call) => call.key === "POST /demo/reset")).toBe(false);
    });

    it("resets after confirmation, then reports it and refreshes the inbox", async () => {
      const calls = demo("admin", {
        "POST /demo/reset": { status: 202, body: { queued: 20 } },
        "GET /documents": [EMPTY, { body: { items: [documentRow()], nextCursor: null } }],
      });
      const user = userEvent.setup();
      renderApp("/");

      await user.click(await screen.findByRole("button", { name: "Reset demo data" }));
      await user.click(screen.getByRole("button", { name: "Reset" }));

      expect(await screen.findByRole("status")).toHaveTextContent(
        "Demo data reset. 20 documents are being processed again.",
      );
      await waitFor(() => {
        expect(screen.getByRole("main")).toHaveFocus();
      });
      expect(await screen.findByText("invoice.pdf")).toBeVisible();
      const reset = calls.find((call) => call.key === "POST /demo/reset");
      expect(new Headers(reset?.init?.headers).get("X-CSRF-Token")).toBe("csrf-1");
    });

    it("keeps the question open and says why when the reset fails", async () => {
      demo("admin", {
        "POST /demo/reset": { status: 500, body: { detail: "It broke.", traceId: "t1" } },
      });
      const user = userEvent.setup();
      renderApp("/");

      await user.click(await screen.findByRole("button", { name: "Reset demo data" }));
      await user.click(screen.getByRole("button", { name: "Reset" }));

      expect(await screen.findByRole("alert")).toHaveTextContent("It broke.");
      expect(screen.getByRole("group", { name: /Delete every document/ })).toBeVisible();
    });
  });
});
