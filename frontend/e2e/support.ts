import { expect, type ConsoleMessage, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { crc32, deflateSync } from "node:zlib";

const AXE_SOURCE = readFileSync(createRequire(import.meta.url).resolve("axe-core/axe.min.js"), {
  encoding: "utf8",
});

// Browsers log every 4xx response themselves, and script cannot stop it. These two are the
// expected 401s: the session check while signed out, and a wrong password (D-063).
const ALLOWED_401_PATHS = ["/api/auth/me", "/api/auth/login"];

interface AxeResult {
  violations: { id: string; nodes: { target: string[] }[] }[];
}

declare global {
  interface Window {
    axe: { run: (context: Document) => Promise<AxeResult> };
    cspViolations: string[];
  }
}

function isAllowed(message: ConsoleMessage): boolean {
  const path = new URL(message.location().url || "http://invalid/").pathname;
  return message.text().includes("status of 401") && ALLOWED_401_PATHS.includes(path);
}

/** Collects what must stay empty: console errors and warnings, page errors, CSP violations. */
export function watchPage(page: Page) {
  const problems: string[] = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()) && !isAllowed(message)) {
      problems.push(`console ${message.type()}: ${message.text()} at ${message.location().url}`);
    }
  });
  page.on("pageerror", (error) => {
    problems.push(`page error: ${error.message}`);
  });
  // Init scripts run before the page's own, and the page's CSP does not apply to them.
  void page.addInitScript(() => {
    window.cspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.cspViolations.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  return {
    async assertClean() {
      const csp = await page.evaluate(() => window.cspViolations);
      expect([...problems, ...csp.map((item) => `CSP: ${item}`)]).toEqual([]);
    },
  };
}

/** Every axe rule, contrast included. Injected by evaluate, which the page's CSP allows. */
export async function expectAccessible(page: Page, state: string) {
  await page.evaluate(AXE_SOURCE);
  const result = await page.evaluate(() => window.axe.run(document));
  const found = result.violations.map(
    (violation) =>
      `${violation.id}: ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`,
  );
  expect(found, `axe on ${state}`).toEqual([]);
}

function chunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "latin1"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

/**
 * A real PNG the mock extractor has no label for, so it arrives with empty fields and goes
 * to review. The text chunk makes each run's file new, so the upload is never a duplicate.
 */
export function unlabeledPng(): { name: string; mimeType: string; buffer: Buffer } {
  const width = 320;
  const height = 200;
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header.writeUInt8(8, 8); // bit depth
  header.writeUInt8(0, 9); // greyscale
  const rows = Buffer.alloc((width + 1) * height, 0xf0);
  for (let row = 0; row < height; row++) rows[row * (width + 1)] = 0; // filter: none
  const buffer = Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("tEXt", Buffer.from(`Comment\0e2e ${randomUUID()}`, "latin1")),
    chunk("IDAT", deflateSync(rows)),
    chunk("IEND", Buffer.alloc(0)),
  ]);
  return { name: `e2e-${randomUUID().slice(0, 8)}.png`, mimeType: "image/png", buffer };
}
