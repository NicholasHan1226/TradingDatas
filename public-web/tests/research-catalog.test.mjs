import assert from "node:assert/strict";
import test from "node:test";
import { createHash } from "node:crypto";
import { papers, readingPaths, researchTitle, researchData } from "../src/researchCatalog.js";
import { productManifest } from "../src/productManifest.js";
import { normalizeLanguageChoice, resolveLanguage } from "../src/language.js";
import { createSearchDocument, searchGroups } from "../src/searchIndex.js";

const normalize = (value) => value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]/g, "");

test("library contains 200 distinct source identities, not translated duplicates", () => {
  assert.equal(papers.length, 200);
  assert.equal(new Set(papers.map((paper) => paper.id)).size, 200);
  assert.equal(new Set(papers.map((paper) => normalize(paper.sourceTitle))).size, 200);
  const dois = papers.map((paper) => paper.evidence.doi?.toLowerCase()).filter(Boolean);
  assert.equal(new Set(dois).size, dois.length);
});

test("every record has bilingual editorial content and verified source identity", () => {
  for (const paper of papers) {
    for (const value of [paper.authors, paper.venue, paper.year, paper.titleZh, paper.dataZh, paper.data, paper.sourceTitle]) {
      assert.ok(typeof value === "string" && value.length > 0, `Missing identity: ${paper.title}`);
      assert.ok(!/undefined|\[object Object\]|&amp;/.test(value), paper.title);
    }
    for (const locale of ["zh", "en"]) {
      assert.ok(paper.summary[locale]?.length >= (locale === "zh" ? 12 : 30), `${paper.title}: summary ${locale}`);
      assert.ok(paper.limits[locale]?.length > 20, `${paper.title}: limits ${locale}`);
      assert.equal(paper.checks[locale]?.length, 3);
      assert.ok(researchTitle(paper, locale));
      assert.ok(researchData(paper, locale));
    }
    assert.match(paper.titleZh, /[\u4e00-\u9fff]/);
    assert.ok(paper.sources?.length, `${paper.title}: sources`);
    assert.ok(["publisher_registered_metadata", "official_source_page"].includes(paper.evidence.verification), paper.title);
    assert.match(paper.verifiedAt, /^\d{4}-\d{2}-\d{2}$/);
    for (const source of paper.sources) assert.equal(new URL(source.url).protocol, "https:");
    assert.ok(!paper.sources.some((source) => /scholar\.google|google\.com\/search/.test(source.url)), paper.title);
    assert.notEqual(paper.evidence.verification, "full_text_review");
  }
});

test("publisher metadata is traceable and not a digest or review substitution", () => {
  for (const paper of papers.filter((paper) => paper.evidence.verification === "publisher_registered_metadata")) {
    const evidence = paper.evidence;
    const { title, doi, venue, year, authors, type } = evidence;
    assert.ok(doi && authors.length && venue, paper.title);
    assert.ok(!/CFA Digest/i.test(venue), paper.title);
    assert.equal(evidence.sourceUrl, `https://doi.org/${doi}`);
    assert.equal(evidence.evidenceUrl, `https://api.crossref.org/works/${encodeURIComponent(doi)}`);
    assert.equal(evidence.metadataSha256, createHash("sha256").update(JSON.stringify({ title, doi, venue, year, authors, type })).digest("hex"), paper.title);
  }
});

test("reading paths and preparation links resolve to maintained records", () => {
  assert.equal(readingPaths.length, 3);
  for (const path of readingPaths) {
    assert.equal(path.titles.length, 4);
    assert.equal(new Set(path.titles).size, 4);
    for (const title of path.titles) assert.ok(papers.some((paper) => paper.title === title), title);
  }
  for (const paper of papers) for (const [kind, ids] of Object.entries(paper.related)) {
    for (const id of ids) assert.ok(productManifest.objects[kind]?.some((item) => item.id === id), `${paper.title}: ${id}`);
  }
});

test("corrected legacy records retain their existing bookmark and route identity", () => {
  const china = papers.find((paper) => paper.id === "china-s-stock-market-a-marriage-of-capitalism-and-state-control");
  assert.equal(normalize(china.sourceTitle), normalize("The Development of China's Stock Market and Stakes for the Global Economy"));
  assert.equal(china.year, "2017");
  assert.match(china.authors, /Carpenter/);
  assert.doesNotMatch(china.authors, /Fangzhou/);
  const intraday = papers.find((paper) => paper.title.startsWith("Intraday Information"));
  assert.match(intraday.authors, /Tao Chen/);
});

test("system language and explicit choices are deterministic", () => {
  for (const language of ["zh-CN", "zh-TW", "zh-HK", "ZH-cn"]) assert.equal(resolveLanguage("system", [language]), "zh");
  assert.equal(resolveLanguage("system", ["en-US", "zh-CN"]), "en");
  assert.equal(resolveLanguage("system", ["fr-FR"]), "en");
  assert.equal(resolveLanguage("system", []), "en");
  assert.equal(resolveLanguage("en", ["zh-CN"]), "en");
  assert.equal(resolveLanguage("zh", ["en-US"]), "zh");
  assert.equal(normalizeLanguageChoice(null), "system");
  assert.equal(normalizeLanguageChoice("invalid"), "system");
});

test("late-library records are searchable in either language with stable routes", () => {
  const target = papers.at(-1);
  for (const locale of ["zh", "en"]) {
    const items = papers.map((paper) => {
      const item = { id: paper.id, key: `research:${paper.id}`, group: "research", label: researchTitle(paper, locale), aliases: [paper.titleZh, paper.title, paper.sourceTitle], path: `/research/${paper.id}` };
      return { ...item, searchDocument: createSearchDocument([item.label, item.aliases]) };
    });
    for (const query of [target.titleZh, target.title]) {
      const results = searchGroups(items, query, [{ key: "research", label: "Research" }]);
      assert.equal(results[0].items[0].id, target.id);
    }
  }
});
