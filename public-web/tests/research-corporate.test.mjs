import test, { before, after } from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
import { papers } from "../src/researchCatalog.js";
import { researchCorporateGuides } from "../src/researchCorporateGuides.js";
import { researchReaderNotes } from "../src/researchReaderNotes.js";
import { researchQuestionRoutes, questionRoutesFor } from "../src/researchQuestionRoutes.js";

test("three corporate additions retain 200 identities within 100 bilingual guides", () => {
  assert.equal(papers.length, 200);
  assert.equal(Object.keys(researchReaderNotes).length, 100);
  assert.equal(Object.keys(researchCorporateGuides).length, 3);
  for (const [title, guide] of Object.entries(researchCorporateGuides)) {
    const paper = papers.find(p => p.title === title);
    assert.equal(paper.topic, "corporate-fundamentals");
    assert.deepEqual(paper.readingNotes, guide.sections);
    assert.equal(guide.sections.length, 6);
    assert.equal(guide.reviewedAt, "2026-08-30");
    for (const section of guide.sections) for (const locale of ["zh", "en"]) {
      assert.ok(section.body[locale].length > (locale === "zh" ? 60 : 130));
      assert.ok(section.reference.label[locale]);
      assert.match(section.reference.url, /^https:\/\//);
    }
  }
  assert.match(researchCorporateGuides["Detecting Earnings Management"].sections[2].body.en, /event-period.*lagged assets/);
  assert.match(researchCorporateGuides["Earnings, Book Values, and Dividends in Equity Valuation"].sections[2].body.en, /beginning book equity/);
  assert.match(researchCorporateGuides["Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy"].limits.en, /not a calibrated bankruptcy probability/);
});

test("three questions resolve nine guides without changing the core journeys", () => {
  assert.equal(researchQuestionRoutes.length, 3);
  const titles = researchQuestionRoutes.flatMap(r => r.steps.map(s => s.title));
  assert.equal(new Set(titles).size, 9);
  for (const route of researchQuestionRoutes) {
    assert.equal(route.topic, "corporate-fundamentals");
    assert.equal(route.steps.length, 3);
    assert.ok(route.question.zh && route.question.en);
    for (const step of route.steps) {
      const paper = papers.find(p => p.title === step.title);
      assert.ok(paper?.readingNotes?.length >= 4, step.title);
      assert.ok(step.reason.zh.length > 15 && step.reason.en.length > 30);
      assert.ok(questionRoutesFor(paper).some(r => r.id === route.id));
    }
  }
  assert.deepEqual(questionRoutesFor({title:"Unknown"}), []);
});

let server, QuestionRoutes;
before(async () => {
  server = await createServer({root:fileURLToPath(new URL("..",import.meta.url)),configFile:false,logLevel:"silent",server:{middlewareMode:true,hmr:false,watch:null},esbuild:{jsx:"automatic"}});
  ({ ResearchQuestionRoutes: QuestionRoutes } = await server.ssrLoadModule("/src/ResearchQuestionRoutes.jsx"));
});
after(async () => server?.close());

test("question routes render both locales, current reading and stable links", () => {
  for (const locale of ["zh", "en"]) {
    const current = papers.find(p => p.title === "Detecting Earnings Management");
    const html = renderToStaticMarkup(createElement(QuestionRoutes, {locale,routes:questionRoutesFor(current),currentPaper:current,onNavigate(){}}));
    assert.match(html, /aria-current="page"/);
    assert.ok(html.includes(researchQuestionRoutes[0].question[locale]));
    assert.doesNotMatch(html, /undefined|\[object Object\]/);
    const all = renderToStaticMarkup(createElement(QuestionRoutes,{locale,routes:researchQuestionRoutes,onNavigate(){}}));
    assert.equal((all.match(/<details/g)||[]).length, 3);
    assert.equal((all.match(/href="\/research\//g)||[]).length, 9);
    assert.doesNotMatch(all, /<details[^>]*open/);
  }
});
