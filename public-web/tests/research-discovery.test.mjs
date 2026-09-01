import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { papers, readingPaths } from "../src/researchCatalog.js";
import { initialResearchView, researchViewReducer } from "../src/researchReader.js";
import { researchSubjects, researchSubject, researchMatches, researchHref, researchLocation, researchPageSize } from "../src/researchDiscovery.js";

test("eight display subjects partition all 200 records without changing source identities", () => {
  const counts = researchSubjects.slice(1).map((subject) => papers.filter((paper) => researchMatches(paper, subject.id, "all")).length);
  assert.deepEqual(counts, [27, 29, 28, 17, 21, 19, 36, 23]);
  assert.equal(counts.reduce((a, b) => a + b, 0), 200);
  assert.equal(researchSubject("quant-methods"), "research-methods");
  assert.equal(papers.filter((paper) => paper.topic === "quant-methods").length, 3);
});

test("discovery links round-trip view, subject, publication type and page", () => {
  for (const open of [false, true]) for (const topic of researchSubjects.map((item) => item.id)) {
    const state = { ...initialResearchView, open, topic };
    assert.deepEqual(researchLocation(new URL(researchHref(state), "https://example.test").search, papers), state);
  }
  const state = { open: true, topic: "research-methods", kind: "paper", page: 1 };
  assert.deepEqual(researchLocation(new URL(researchHref(state), "https://example.test").search, papers), state);
});

test("invalid query values and out-of-range pages normalize safely", () => {
  assert.deepEqual(researchLocation("?view=invalid&topic=unknown&format=unknown&page=-2", papers), initialResearchView);
  for (const value of ["Infinity", "NaN", "1.4", "0", "-3"]) assert.equal(researchLocation(`?page=${value}`, papers).page, 0);
  assert.equal(researchLocation("?view=topics&page=99999", papers).page, Math.ceil(papers.length / researchPageSize) - 1);
  assert.equal(researchLocation("?view=topics&topic=quant-methods", papers).topic, "research-methods");
});

test("switching views preserves filters; selecting a subject clears incompatible types", () => {
  const state = { open: true, topic: "research-methods", kind: "book", page: 1 };
  assert.deepEqual(researchViewReducer(state, { type: "visibility", value: false }), { ...state, open: false });
  assert.deepEqual(researchViewReducer(state, { type: "open", topic: "corporate-fundamentals" }), { open: true, topic: "corporate-fundamentals", kind: "all", page: 0 });
  assert.deepEqual(researchViewReducer(initialResearchView, { type: "restore", value: state }), state);
});

let server, ResearchHub;
before(async () => {
  server = await createServer({ root: fileURLToPath(new URL("..", import.meta.url)), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, esbuild: { jsx: "automatic" } });
  ({ ResearchHub } = await server.ssrLoadModule("/src/ResearchHub.jsx"));
});
after(async () => server?.close());
const props = {
  featuredPaper: papers.find((paper) => paper.id === "china-s-stock-market-a-marriage-of-capitalism-and-state-control"),
  atlas: { paths: readingPaths.map((path) => ({ question: path.title.en, data: "Data materials" })) },
  kindLabels: { all: "All types", paper: "Papers", book: "Books" }, methods: [], bookmarks: [], onToggleBookmark() {}, onNavigate() {}, onChange() {},
};

test("both languages and views render two navigation choices, stable links and no internal QA", () => {
  for (const locale of ["zh", "en"]) for (const open of [false, true]) {
    const html = renderToStaticMarkup(createElement(ResearchHub, { ...props, locale, view: { ...initialResearchView, open } }));
    assert.match(html, /research-view-nav/);
    assert.match(html, /aria-current="page"/);
    assert.doesNotMatch(html, /<input|准备状态|来源核验|出版信息已核对|undefined|\[object Object\]/);
    if (open) {
      assert.equal((html.match(/class="research-bibliographic-row"/g) || []).length, researchPageSize);
      assert.match(html, /aria-pressed="false"/);
      assert.ok(html.includes("200"));
    } else assert.match(html, /research-editorial-architecture.webp/);
  }
});

test("every topic and type has a bounded list or a clear actionable empty state", () => {
  for (const topic of researchSubjects.map((item) => item.id)) for (const kind of [...new Set(papers.map((paper) => paper.kind))]) {
    const html = renderToStaticMarkup(createElement(ResearchHub, { ...props, locale: "en", view: { open: true, topic, kind, page: 0 } }));
    const count = papers.filter((paper) => researchMatches(paper, topic, kind)).length;
    assert.equal((html.match(/class="research-bibliographic-row"/g) || []).length, Math.min(count, researchPageSize));
    if (!count) assert.match(html, /Show all types/);
  }
});
