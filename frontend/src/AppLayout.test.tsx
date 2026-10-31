import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import { routes } from "./routes";

function renderAt(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

describe("app shell", () => {
  it("shows the inbox and marks its link as current", () => {
    renderAt("/");

    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Inbox" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Metrics" })).not.toHaveAttribute("aria-current");
  });

  it("moves focus to the main region after keyboard navigation", async () => {
    const user = userEvent.setup();
    renderAt("/");

    screen.getByRole("link", { name: "Metrics" }).focus();
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { level: 1, name: "Metrics" })).toBeVisible();
    expect(screen.getByRole("main")).toHaveFocus();
  });

  it("does not take focus on first render", () => {
    renderAt("/");

    expect(screen.getByRole("main")).not.toHaveFocus();
  });

  it("offers a way back from an unknown address", () => {
    renderAt("/nowhere");

    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Back to the inbox" })).toHaveAttribute("href", "/");
  });

  it("has a skip link as the first focusable element", async () => {
    const user = userEvent.setup();
    renderAt("/");

    await user.tab();

    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveFocus();
  });
});
