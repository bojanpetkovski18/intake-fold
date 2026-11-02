// Counts each limited field in a portfolio file and fails when one is over its limit.
//   node scripts/portfolio-count.mjs docs/portfolio/upwork.md
// A field is a heading "## Name (up to N characters)" followed by a ```text block.
import { readFileSync } from "node:fs";

const file = process.argv[2];
if (!file) {
  console.error("Usage: node scripts/portfolio-count.mjs <file>");
  process.exit(2);
}

const source = readFileSync(file, "utf8").replace(/\r\n/g, "\n");
const field = /^## (.+?) \(up to (\d+) characters\)\n+```text\n([\s\S]*?)\n```/gm;
let over = 0;
let found = 0;
for (const [, name, limit, text] of source.matchAll(field)) {
  found += 1;
  // Code points, as a person counts them; the fields here are plain ASCII anyway.
  const length = [...text.trim()].length;
  const ok = length <= Number(limit);
  if (!ok) over += 1;
  console.log(`${ok ? "ok  " : "OVER"} ${name}: ${length} of ${limit}`);
}
if (found === 0) {
  console.error("No limited fields found.");
  process.exit(1);
}
process.exit(over === 0 ? 0 : 1);
