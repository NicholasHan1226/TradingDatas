import fs from "node:fs/promises";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { createHash } from "node:crypto";
import { researchSeeds } from "../src/researchSeeds.js";

const run = promisify(execFile);
const legacy = JSON.parse(await fs.readFile(new URL("../src/researchLegacy.json", import.meta.url), "utf8"));
const target = new URL("../src/researchBibliography.json", import.meta.url);
const refresh = process.argv.includes("--refresh");
const bibliography = refresh ? {} : JSON.parse(await fs.readFile(target, "utf8").catch(() => "{}"));
const normalize = (text) => text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/<[^>]*>/g, "").replace(/[^a-z0-9]/g, "");
const sourcePages = JSON.parse(await fs.readFile(new URL("../src/researchSourcePages.json", import.meta.url), "utf8").catch(() => "{}"));
const lookups = JSON.parse(await fs.readFile(new URL("../src/researchLookups.json", import.meta.url), "utf8"));
const candidates = [...legacy.filter((item) => item.kind === "paper").map((item) => ({ ...item, authorHint: item.authors.split(" · ")[0].split(" ").at(-1) })), ...researchSeeds].filter((item) => !sourcePages[item.title]).map((item) => ({ ...item, ...lookups[item.title] }));
const pending = candidates.filter((item) => !bibliography[item.title]?.venue || /CFA Digest|SSRN Electronic Journal/.test(bibliography[item.title]?.venue) || (item.doi && bibliography[item.title]?.doi !== item.doi) || !(bibliography[item.title]?.authors || []).some((author) => normalize(author).includes(normalize(item.authorHint))));
const unresolved = [];
let index = 0;

function compact(item) {
  return {
    title: item.title?.[0], doi: item.DOI, venue: item["container-title"]?.[0] || item.publisher,
    year: (item["published-print"] || item.published || item["published-online"])?.["date-parts"]?.[0]?.[0],
    authors: (item.author || []).map((author) => [author.given, author.family || author.name].filter(Boolean).join(" ")),
    type: item.type,
  };
}

async function worker() {
  while (index < pending.length) {
    const item = pending[index++];
    const url = new URL(item.doi ? `https://api.crossref.org/works/${encodeURIComponent(item.doi)}` : "https://api.crossref.org/works");
    if (!item.doi) {
      url.searchParams.set("query.title", item.lookupTitle || item.title);
      url.searchParams.set("rows", "12");
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
    try {
      const { stdout } = await run("curl", ["--fail", "--silent", "--show-error", "--retry", "2", "--max-time", "35", "--user-agent", "TradingDatasResearchBibliography/1.0 (public bibliographic verification)", url.href], { maxBuffer: 4 * 1024 * 1024 });
      const response = JSON.parse(stdout).message;
      const found = item.doi ? [response] : response.items;
      const matches = found.filter((match) => normalize(match.title?.[0] || "") === normalize(item.lookupTitle || item.title)
        && (!item.authorHint || (match.author || []).some((author) => normalize(`${author.given || ""} ${author.family || author.name || ""}`).includes(normalize(item.authorHint)))));
      const journals = matches.filter((match) => match.type === "journal-article" && !/SSRN|Discussion Papers|Discussion Series/i.test(match["container-title"]?.[0] || ""));
      const selected = journals.find((match) => compact(match).year === (item.expectedYear || Number(item.year)) && !match.DOI.startsWith("10.2307/")) || journals.find((match) => !match.DOI.startsWith("10.2307/")) || journals[0] || matches[0];
      if (!selected) {
        delete bibliography[item.title];
        unresolved.push({ requested: item.title, candidates: found.map(compact) });
        console.log(`REVIEW ${item.title}`);
        continue;
      }
      const metadata = compact(selected);
      bibliography[item.title] = {
        ...metadata,
        checkedAt: new Date().toISOString().slice(0, 10),
        evidenceUrl: `https://api.crossref.org/works/${encodeURIComponent(selected.DOI)}`,
        sourceUrl: `https://doi.org/${selected.DOI}`,
        verification: "publisher_registered_metadata",
        metadataSha256: createHash("sha256").update(JSON.stringify(metadata)).digest("hex"),
      };
      console.log(`OK ${Object.keys(bibliography).length} ${item.title}`);
      await fs.writeFile(target, `${JSON.stringify(bibliography, null, 2)}\n`);
    } catch (error) {
      delete bibliography[item.title];
      unresolved.push({ requested: item.title, error: error.message });
      console.log(`ERROR ${item.title}`);
    }
  }
}

await worker();
await fs.writeFile(target, `${JSON.stringify(bibliography, null, 2)}\n`);
const reviewPath = new URL("../research-source-review.json", import.meta.url);
await fs.writeFile(reviewPath, `${JSON.stringify(unresolved, null, 2)}\n`);
console.log(JSON.stringify({ requested: candidates.length, verified: candidates.filter((item) => bibliography[item.title]).length, unresolved: unresolved.length }));
if (unresolved.length) process.exitCode = 1;
