import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { deadJob, renderApp, session, stubApi } from "../test-utils";

const URL_DEAD = "GET /jobs?status=dead";
const EMPTY = { body: { items: [], nextCursor: null } };
const ONE = { body: { items: [deadJob()], nextCursor: null } };

describe("dead letters", () => {
  it("shows a loading state", async () => {
    stubApi({
      "GET /auth/me": { body: session() },
      [URL_DEAD]: () =>
        new Promise(() => {
          // Never answers, so the loading state stays on screen.
        }),
    });
    renderApp("/dead-letters");

    expect(await screen.findByText("Loading dead jobs")).toBeVisible();
  });

  it("shows an empty state", async () => {
    stubApi({ "GET /auth/me": { body: session() }, [URL_DEAD]: EMPTY });
    renderApp("/dead-letters");

    expect(await screen.findByText("No dead jobs.")).toBeVisible();
  });

  it("shows an error and recovers on retry", async () => {
    stubApi({
      "GET /auth/me": { body: session() },
      [URL_DEAD]: [{ status: 400, body: { detail: "No list." } }, ONE],
    });
    const user = userEvent.setup();
    renderApp("/dead-letters");

    await user.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("row", { name: /broken\.pdf/ })).toBeVisible();
  });

  it("shows the job and why it died", async () => {
    stubApi({ "GET /auth/me": { body: session() }, [URL_DEAD]: ONE });
    renderApp("/dead-letters");

    const row = await screen.findByRole("row", { name: /broken\.pdf/ });
    expect(within(row).getByText("render_failed")).toBeVisible();
    expect(within(row).getByText("5 of 5")).toBeVisible();
  });

  it("offers a reviewer no way to requeue", async () => {
    stubApi({ "GET /auth/me": { body: session("reviewer") }, [URL_DEAD]: ONE });
    renderApp("/dead-letters");

    await screen.findByRole("row", { name: /broken\.pdf/ });
    expect(screen.queryByRole("button", { name: /Requeue/ })).not.toBeInTheDocument();
  });

  it("lets an admin requeue, then moves focus to the result", async () => {
    const calls = stubApi({
      "GET /auth/me": { body: session("admin") },
      [URL_DEAD]: [ONE, EMPTY],
      "POST /jobs/j1/retry": { status: 202, body: { status: "queued" } },
    });
    const user = userEvent.setup();
    renderApp("/dead-letters");

    await user.click(await screen.findByRole("button", { name: "Requeue broken.pdf" }));

    expect(await screen.findByText("broken.pdf was requeued.")).toHaveFocus();
    expect(await screen.findByText("No dead jobs.")).toBeVisible();
    expect(calls.map((call) => call.key)).toContain("POST /jobs/j1/retry");
    await waitFor(() => {
      expect(screen.getByText("broken.pdf was requeued.")).toHaveFocus();
    });
  });

  it("keeps focus on a busy requeue button", async () => {
    stubApi({
      "GET /auth/me": { body: session("admin") },
      [URL_DEAD]: ONE,
      "POST /jobs/j1/retry": () =>
        new Promise(() => {
          // Never answers, so the button stays busy.
        }),
    });
    const user = userEvent.setup();
    renderApp("/dead-letters");

    await user.click(await screen.findByRole("button", { name: "Requeue broken.pdf" }));

    await waitFor(() => {
      const busy = screen.getByRole("button", { name: "Requeue broken.pdf" });
      expect(busy).toHaveAttribute("aria-disabled", "true");
      expect(busy).toHaveFocus();
    });
  });

  it("shows a refused requeue", async () => {
    stubApi({
      "GET /auth/me": { body: session("admin") },
      [URL_DEAD]: ONE,
      "POST /jobs/j1/retry": { status: 409, body: { detail: "This job is not dead." } },
    });
    const user = userEvent.setup();
    renderApp("/dead-letters");

    await user.click(await screen.findByRole("button", { name: "Requeue broken.pdf" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This job is not dead.");
  });
});
