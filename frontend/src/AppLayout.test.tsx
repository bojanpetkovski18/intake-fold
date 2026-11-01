import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { documentRow, renderApp, session, SIGNED_OUT, stubApi, type Reply } from "./test-utils";

const EMPTY = { body: { items: [], nextCursor: null } };

function signedIn() {
  return stubApi({ "GET /auth/me": { body: session() }, "GET /documents": EMPTY });
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
});
