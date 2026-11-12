// Rebuilds data/*.json from the source repos for the travel site and Things Done site.
// Usage: node scripts/export-data.mjs <path-to-ashar-travel> <path-to-ashar-things-done> [--pr]
// With --pr, if the generated data differs from the remote default branch, only data/*.json
// is committed on a data-refresh/YYYY-MM-DD-<hash> branch (cut from that remote branch) and
// opened as a PR labelled data-refresh. With no change it prints that and exits 0.
import { build } from "esbuild";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
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

const sh = (cwd, cmd, ...a) => {
  try {
    return execFileSync(cmd, a, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
  } catch (err) {
    err.cmd = [cmd, ...a].join(" ");
    throw err;
  }
};
// A failed git/gh step prints its own error and a hint instead of a Node stack trace.
process.on("uncaughtException", (err) => {
  const detail = (err.stderr || err.message || String(err)).trim();
  console.error(`Refresh failed: ${err.cmd ?? ""}\n${detail}`);
  if (openPr) console.error("Fix the problem and run the same command again; it picks up where it stopped.");
  process.exit(1);
});
const git = (...a) => sh(root, "git", ...a);
const gh = (...a) => sh(root, "gh", ...a);

// With --pr, check prerequisites before touching anything, so a missing tool can't
// leave a half-finished refresh behind.
let base;
if (openPr) {
  try {
    gh("auth", "status");
  } catch {
    console.error("--pr needs the GitHub CLI installed and signed in: https://cli.github.com, then `gh auth login`.");
    process.exit(1);
  }
  // Remote default branch, e.g. "ref: refs/heads/main\tHEAD"
  base = git("ls-remote", "--symref", "origin", "HEAD").match(/refs\/heads\/(\S+)\s+HEAD/)?.[1];
  if (!base) {
    console.error("Couldn't find the default branch of the `origin` remote.");
    process.exit(1);
  }
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

// --- --pr: publish the refresh as a labelled PR ------------------------------
// Only the two generated files are published, on a branch cut from the remote default
// branch in a throwaway worktree, so the caller's branch, index and other files are
// never touched or pushed. The branch name includes a hash of the data, so re-running
// after a failed push or PR step finishes the same refresh instead of starting over.
const FILES = ["data/travel.json", "data/things-done.json"];
const remoteBase = `origin/${base}`;
git("fetch", "--quiet", "origin", base);

const atBase = (file) => {
  try {
    return git("show", `${remoteBase}:${file}`);
  } catch {
    return null;
  }
};
const generated = Object.fromEntries(FILES.map((f) => [f, readFileSync(join(root, f), "utf8")]));
if (FILES.every((f) => generated[f] === atBase(f))) {
  console.log(`No data changes compared with ${remoteBase}; nothing to refresh.`);
  process.exit(0);
}

// Headline counts for the PR body: remote base vs freshly generated.
const counts = (read) => {
  const travel = JSON.parse(read("data/travel.json") ?? "{}");
  const done = JSON.parse(read("data/things-done.json") ?? "{}");
  return {
    trips: travel.trips?.length ?? 0,
    countries: (travel.countries ?? []).filter((c) => c.visited).length,
    entries: Object.values(done.byYear ?? {})
      .flatMap((months) => Object.values(months))
      .reduce((n, items) => n + items.length, 0),
  };
};
const before = counts(atBase);
const after = counts((f) => generated[f]);
const delta = after.entries - before.entries;
const summary =
  `trips ${before.trips}→${after.trips}, countries ${before.countries}→${after.countries}, ` +
  `Things Done entries ${delta >= 0 ? "+" : ""}${delta}`;

const date = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
const hash = createHash("sha256").update(FILES.map((f) => generated[f]).join("\0")).digest("hex").slice(0, 8);
const branch = `data-refresh/${date}-${hash}`;
const title = `Refresh data (${date})`;

// Commit just the data files on top of the remote base, in a temporary worktree.
const tree = mkdtempSync(join(tmpdir(), "ashar-mcp-refresh-"));
try {
  git("worktree", "add", "--quiet", "--detach", tree, remoteBase);
  for (const f of FILES) writeFileSync(join(tree, f), generated[f]);
  sh(tree, "git", "add", "--", ...FILES);
  sh(tree, "git", "commit", "--quiet", "-m", title, "-m", summary);
  // The branch is owned by this script and named after its content, so overwriting is safe.
  sh(tree, "git", "push", "--quiet", "--force", "origin", `HEAD:refs/heads/${branch}`);
} finally {
  try {
    git("worktree", "remove", "--force", tree);
  } catch {
    rmSync(tree, { recursive: true, force: true });
    git("worktree", "prune");
  }
}

// Open the PR, or reuse it if an earlier run already did.
const prs = (...filter) =>
  JSON.parse(gh("pr", "list", "--state", "open", ...filter, "--json", "number,url,headRefName"));
let [pr] = prs("--head", branch);
if (pr) {
  console.log(`PR already open for this refresh: ${pr.url}`);
} else {
  const url = gh("pr", "create", "--base", base, "--head", branch, "--label", "data-refresh",
    "--title", title, "--body", summary).trim();
  console.log(url);
  // Close older refresh PRs: this one contains everything they did and more.
  for (const old of prs("--label", "data-refresh")) {
    if (old.headRefName === branch) continue;
    gh("pr", "close", String(old.number), "--delete-branch", "--comment", `Superseded by ${url}`);
    console.log(`closed superseded PR #${old.number}`);
  }
}
console.log(summary);
