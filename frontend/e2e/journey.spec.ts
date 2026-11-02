import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { expectAccessible, unlabeledPng, watchPage } from "./support";

// One reviewer's whole day, against the built stack in demo mode with the mock extractor.
// scripts/e2e.sh turns one delivered webhook into a dead job before each run, for the requeue.
test("a reviewer takes a document from upload to delivery and export", async ({ page }) => {
  const watch = watchPage(page);
  const file = unlabeledPng();
  const invoiceNumber = `E2E-${file.name.slice(4, 12).toUpperCase()}`;
  const today = new Date().toISOString().slice(0, 10);

  await test.step("sign in with the demo account shown on the page", async () => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/sign-in$/);
    const admin = page.getByRole("listitem").filter({ hasText: "admin@example.com" });
    const password = (await admin.locator("dd").nth(1).textContent()) ?? "";
    expect(password.length).toBeGreaterThanOrEqual(12);
    await expectAccessible(page, "sign in");

    await page.getByLabel("Email").fill("admin@example.com");
    await page.getByLabel("Password").fill(`${password}-wrong`);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expectAccessible(page, "sign in, wrong password");

    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Inbox" })).toBeVisible();
    await expect(page.getByRole("banner")).toContainText("Mock extractor");
  });

  let documentPath = "";
  await test.step("upload a document the extractor cannot read", async () => {
    await page.getByLabel("Invoices and receipts (PDF, PNG or JPEG)").setInputFiles(file);
    await page.getByRole("button", { name: "Upload", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "1 of 1 accepted." })).toBeVisible();
    const row = page.getByRole("row").filter({ hasText: file.name });
    // The inbox polls while anything is queued or processing.
    await expect(row).toContainText("Needs review", { timeout: 30_000 });
    await expectAccessible(page, "inbox");
    await row.getByRole("link", { name: file.name }).click();
    await expect(page.getByRole("heading", { level: 1, name: file.name })).toBeVisible();
    documentPath = new URL(page.url()).pathname;
  });

  await test.step("correct every field, and the rules pass", async () => {
    const reasons = page.getByRole("list", { name: "Why this document needs review" });
    await expect(reasons).toContainText("Required fields are missing.");
    await expectAccessible(page, "review, before correcting");

    await page.getByLabel("Document type", { exact: true }).selectOption("invoice");
    await page.getByLabel("Vendor", { exact: true }).fill("Brindlecote Stationers");
    await page.getByLabel("Invoice number", { exact: true }).fill(invoiceNumber);
    await page.getByLabel("Issue date", { exact: true }).fill(today);
    await page.getByLabel("Currency", { exact: true }).fill("USD");
    await page.getByLabel("Subtotal", { exact: true }).fill("120.00");
    await page.getByLabel("Tax", { exact: true }).fill("24.00");
    await page.getByLabel("Total", { exact: true }).fill("144.00");
    await page.getByRole("button", { name: "Save corrections" }).click();

    const saved = page.getByRole("status").filter({ hasText: "Corrections saved." });
    await expect(saved).toBeFocused();
    await expect(reasons).not.toContainText("Required fields are missing.");
    await expect(page.getByText("No rule has failed.")).toBeVisible();
    await expectAccessible(page, "review, after correcting");
  });

  await test.step("approve, and the next document opens", async () => {
    await page.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: `${file.name} was approved.` }),
    ).toBeVisible();
    expect(new URL(page.url()).pathname).not.toBe(documentPath);
  });

  await test.step("the signed webhook reached the sink", async () => {
    await page.goto(`${documentPath}/log`);
    const deliveries = page.getByRole("region", { name: "Deliveries" });
    // Sent by the worker after the approval commits, so it can lag the page by a moment.
    await expect(async () => {
      await page.reload();
      await expect(deliveries).toContainText("sink: delivered", { timeout: 1_000 });
    }).toPass({ timeout: 30_000 });
    await expect(deliveries).toContainText("Attempt 1: 200");
    const trail = page.getByRole("region", { name: "Audit trail" });
    await expect(trail).toContainText("Corrected total: empty to 144.00");
    await expect(trail).toContainText("ApprovedAda Admin");
    await expectAccessible(page, "document log");
  });

  await test.step("export the approved invoice as CSV", async () => {
    await page.getByRole("link", { name: "Inbox" }).click();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export CSV" }).click();
    const saved = await download;
    expect(saved.suggestedFilename()).toBe("approved-invoices.csv");
    const csv = await readFile(await saved.path(), "utf8");
    const row = csv.split(/\r?\n/).find((line) => line.includes(invoiceNumber)) ?? "";
    expect(row).toContain("Brindlecote Stationers");
    expect(row).toContain("144.00");
    await expect(
      page.getByRole("status").filter({ hasText: "Saved approved-invoices.csv." }),
    ).toBeVisible();
  });

  await test.step("read the metrics", async () => {
    await page.getByRole("link", { name: "Metrics" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Metrics" })).toBeVisible();
    await expect(
      page.getByRole("rowheader", { name: "Mock (plumbing test, not accuracy)" }),
    ).toBeVisible();
    await expectAccessible(page, "metrics");
  });

  await test.step("requeue a dead job, and focus moves to the result", async () => {
    await page.getByRole("link", { name: "Dead letters" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Dead letters" })).toBeVisible();
    await expectAccessible(page, "dead letters");
    const row = page.getByRole("row").filter({ hasText: "DeliveryFailed" }).first();
    const name = (await row.getByRole("rowheader").textContent()) ?? "";
    await row.getByRole("button", { name: `Requeue ${name}` }).click();
    await expect(
      page.getByRole("status").filter({ hasText: `${name} was requeued.` }),
    ).toBeFocused();
    await expect(page.getByText("No dead jobs.")).toBeVisible();
  });

  await watch.assertClean();
});
