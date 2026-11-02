import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { renderApp, session, SIGNED_OUT, stubApi } from "../test-utils";

const EMPTY = { body: { items: [], nextCursor: null } };

async function fillIn(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Email"), "reviewer@example.com");
  await user.type(screen.getByLabelText("Password"), "a-password");
}

describe("sign in", () => {
  it("sends an anonymous visitor to sign in and returns them afterwards", async () => {
    stubApi({
      "GET /auth/me": SIGNED_OUT,
      "POST /auth/login": { body: session() },
      "GET /documents?status=failed": EMPTY,
    });
    const user = userEvent.setup();
    const router = renderApp("/?status=failed");

    await fillIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
    expect(router.state.location.search).toBe("?status=failed");
  });

  it("submits from the keyboard", async () => {
    const calls = stubApi({
      "GET /auth/me": SIGNED_OUT,
      "POST /auth/login": { body: session() },
      "GET /documents": EMPTY,
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    await fillIn(user);
    await user.keyboard("{Enter}");

    await screen.findByRole("heading", { level: 1, name: "Inbox" });
    const login = calls.find((call) => call.key === "POST /auth/login");
    expect(login?.init?.body).toBe(
      JSON.stringify({ email: "reviewer@example.com", password: "a-password" }),
    );
  });

  it("shows a wrong password as an error and moves focus to it", async () => {
    stubApi({
      "GET /auth/me": SIGNED_OUT,
      "POST /auth/login": {
        status: 401,
        body: { detail: "The email or password is not correct." },
      },
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    await fillIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The email or password is not correct.");
    expect(alert).toHaveFocus();
  });

  it("explains the rate limit", async () => {
    stubApi({
      "GET /auth/me": SIGNED_OUT,
      "POST /auth/login": {
        status: 429,
        body: { detail: "Too many sign-in attempts. Try again later." },
      },
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    await fillIn(user);
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many sign-in attempts");
  });

  it("keeps focus on the button while busy and ignores a second press", async () => {
    let finish: (reply: { body: unknown }) => void = () => undefined;
    const calls = stubApi({
      "GET /auth/me": SIGNED_OUT,
      "POST /auth/login": () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
      "GET /documents": EMPTY,
    });
    const user = userEvent.setup();
    renderApp("/sign-in");

    await fillIn(user);
    const button = screen.getByRole("button", { name: "Sign in" });
    await user.click(button);

    const busy = await screen.findByRole("button", { name: "Signing in" });
    expect(busy).toHaveAttribute("aria-disabled", "true");
    expect(busy).not.toBeDisabled();
    expect(busy).toHaveFocus();

    await user.click(busy);
    expect(calls.filter((call) => call.key === "POST /auth/login")).toHaveLength(1);

    finish({ body: session() });
    await screen.findByRole("heading", { level: 1, name: "Inbox" });
  });

  it("sends a signed-in visitor straight to the inbox", async () => {
    stubApi({ "GET /auth/me": { body: session() }, "GET /documents": EMPTY });
    const router = renderApp("/sign-in");

    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("offers a retry when the session check itself fails", async () => {
    stubApi({
      "GET /auth/me": [
        { status: 503, body: { detail: "The database is not reachable." } },
        { status: 503, body: { detail: "The database is not reachable." } },
        { status: 503, body: { detail: "The database is not reachable." } },
        { body: session() },
      ],
      "GET /documents": EMPTY,
    });
    const user = userEvent.setup();
    renderApp("/");

    const retry = await screen.findByRole("button", { name: "Try again" }, { timeout: 8000 });
    expect(screen.getByRole("alert")).toHaveTextContent("not reachable");

    await user.click(retry);

    expect(await screen.findByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
  }, 10_000);
});
