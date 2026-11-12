// Rebuilds data/*.json from the source repos for the travel site and Things Done site.
// Usage: node scripts/export-data.mjs <path-to-ashar-travel> <path-to-ashar-things-done> [--pr]
// With --pr, a change to data/ is committed on a data-refresh/YYYY-MM-DD branch and opened
// as a PR labelled data-refresh. With no change it prints that and exits 0.
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const args = process.argv.slice(2);
const openPr = args.includes("--pr");
const [travelRepo, doneRepo] = args.filter((a) => a !== "--pr");
if (!travelRepo || !doneRepo) {
  console.error("usage: node scripts/export-data.mjs <ashar-travel dir> <ashar-things-done dir> [--pr]");
  process.exit(1);
}
mkdirSync(join(root, "data"), { recursive: true });
const save = (name, value) => {
  writeFileSync(join(root, "data", name), JSON.stringify(value, null, 2) + "\n");
  console.log(`wrote data/${name}`);
};

// --- Travel: bundle the TypeScript data module and import it ---------------
const out = join(root, "scripts", ".travel-bundle.mjs");
await build({
  entryPoints: [join(travelRepo, "data", "data.ts")],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: out,
  alias: { "@": travelRepo },
  logLevel: "error",
});
const { travelData } = await import(out + `?t=${Date.now()}`);
save("travel.json", travelData);

// --- Things Done: pull top-level data literals out of the React components ---
function extractLiteral(file, name) {
  const src = readFileSync(join(doneRepo, "src", "components", file), "utf8");
  const start = src.indexOf(`const ${name} =`);
  if (start === -1) throw new Error(`${name} not found in ${file}`);
  let i = src.indexOf("=", start) + 1;
  while (/\s/.test(src[i])) i++;
  const open = src[i];
  const close = open === "[" ? "]" : "}";
  let depth = 0, inStr = null, j = i;
  for (; j < src.length; j++) {
    const c = src[j];
    if (inStr) {
      if (c === "\\") { j++; continue; }
      if (c === inStr) inStr = null;
      continue;
    }
    if (c === '"' || c === "'" || c === "`") inStr = c;
    else if (c === open) depth++;
    else if (c === close && --depth === 0) break;
  }
  return new Function(`return (${src.slice(i, j + 1)});`)();
}

save("things-done.json", {
  byYear: extractLiteral("ThingsDone.jsx", "thingsDoneByYear"),
  lifeHappenings: extractLiteral("MajorLifeHappenings.jsx", "lifeHappenings"),
  hackathons: extractLiteral("Hackathons.jsx", "hackathons"),
  conferences: extractLiteral("Conferences.jsx", "conferences"),
  funFacts: extractLiteral("FunFacts.jsx", "funFacts"),
});

if (!openPr) process.exit(0);

// --- --pr: open a data-refresh PR if data/ changed --------------------------
const run = (cmd, ...a) => execFileSync(cmd, a, { cwd: root, encoding: "utf8" });
if (!run("git", "status", "--porcelain", "--", "data").trim()) {
  console.log("No data changes; nothing to refresh.");
  process.exit(0);
}

// Headline counts for the PR body, before (HEAD) and after (working tree).
const counts = (read) => {
  const travel = JSON.parse(read("travel.json") ?? "{}");
  const done = JSON.parse(read("things-done.json") ?? "{}");
  return {
    trips: travel.trips?.length ?? 0,
    countries: (travel.countries ?? []).filter((c) => c.visited).length,
    entries: Object.values(done.byYear ?? {})
      .flatMap((months) => Object.values(months))
      .reduce((n, items) => n + items.length, 0),
  };
};
const before = counts((name) => {
  try {
    return run("git", "show", `HEAD:data/${name}`);
  } catch {
    return null;
  }
});
const after = counts((name) => readFileSync(join(root, "data", name), "utf8"));
const delta = after.entries - before.entries;
const summary =
  `trips ${before.trips}→${after.trips}, countries ${before.countries}→${after.countries}, ` +
  `Things Done entries ${delta >= 0 ? "+" : ""}${delta}`;

const date = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
const branch = `data-refresh/${date}`;
const title = `Refresh data (${date})`;
run("git", "switch", "-c", branch);
run("git", "add", "--", "data");
run("git", "commit", "-m", title, "-m", summary);
run("git", "push", "-u", "origin", branch);
console.log(run("gh", "pr", "create", "--label", "data-refresh", "--title", title, "--fill").trim());
console.log(summary);
