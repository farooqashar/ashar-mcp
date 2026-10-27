// Rebuilds data/*.json from the source repos for the travel site and Things Done site.
// Usage: node scripts/export-data.mjs <path-to-ashar-travel> <path-to-ashar-things-done>
import { build } from "esbuild";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const [travelRepo, doneRepo] = process.argv.slice(2);
if (!travelRepo || !doneRepo) {
  console.error("usage: node scripts/export-data.mjs <ashar-travel dir> <ashar-things-done dir>");
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
