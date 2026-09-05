import test from "node:test";
import assert from "node:assert/strict";
import { getDocumentation } from "../src/documentation.js";

const slugs = ["start-1", "start-2", "data-1", "data-2", "data-3", "api-1", "api-2", "api-3", "learn-1", "learn-2", "commerce-1", "commerce-2", "commerce-3"];
const publicPaths = ["/data", "/data/sources", "/research", "/recipes", "/pricing", "/connect", "/bookmarks"];
const accountPaths = ["/account/subscription", "/account/usage", "/account/keys", "/account/billing", "/account/security"];

test("existing documentation deep links and reading anchors survive both languages", () => {
  const zh = getDocumentation("zh");
  const en = getDocumentation("en");
  assert.deepEqual(zh.guides.map(({ slug }) => slug), slugs);
  assert.deepEqual(en.guides.map(({ slug }) => slug), slugs);
  for (let index = 0; index < slugs.length; index++) {
    const chinese = zh.guides[index];
    const english = en.guides[index];
    assert.notEqual(chinese.title, english.title);
    assert.notEqual(chinese.description, english.description);
    assert.deepEqual(chinese.sections.map(({ id }) => id), english.sections.map(({ id }) => id));
    assert.deepEqual(chinese.related.map(({ path }) => path), english.related.map(({ path }) => path));
  }
});

test("every public guide has distinct useful content and resolvable next steps", () => {
  const validPaths = new Set([...publicPaths, ...accountPaths, ...slugs.map((slug) => `/docs/${slug}`)]);
  for (const locale of ["zh", "en"]) {
    const { categories, guides } = getDocumentation(locale);
    const categoryKeys = new Set(categories.map(({ key }) => key));
    const articleBodies = new Set();
    for (const entry of guides) {
      assert.ok(categoryKeys.has(entry.category));
      assert.ok(entry.sections.length >= 2 && entry.sections.length <= 4);
      assert.equal(new Set(entry.sections.map(({ id }) => id)).size, entry.sections.length);
      for (const section of entry.sections) {
        assert.match(section.id, /^[a-z][a-z-]*$/);
        assert.ok(section.title && section.paragraphs.length > 0);
        assert.ok(section.paragraphs.every((paragraph) => typeof paragraph === "string" && paragraph.length > 20));
      }
      const text = entry.sections.flatMap(({ paragraphs }) => paragraphs).join(" ");
      assert.doesNotMatch(text, /TODO|lorem ipsum|Guide structure|权威来源|说明结构|docs\/API\.md|backend contract/i);
      articleBodies.add(text);
      assert.ok(entry.related.length >= 2);
      for (const related of entry.related) assert.ok(validPaths.has(related.path), related.path);
    }
    assert.equal(articleBodies.size, guides.length);
  }
});

test("copy-only API examples use the public gateway and documented bounded request envelope", () => {
  for (const locale of ["zh", "en"]) {
    const { guides } = getDocumentation(locale);
    const catalog = guides.find(({ slug }) => slug === "api-1").sections[0].code;
    assert.match(catalog, /https:\/\/tradingdatas\.com\/v1\/catalog/);
    assert.match(catalog, /Authorization: Bearer \$\{TRADINGDATAS_API_KEY\}/);
    const query = JSON.parse(guides.find(({ slug }) => slug === "api-2").sections[0].code);
    assert.equal(query.dataset_id, "cn.equity.daily");
    assert.equal(query.schema_major, 2);
    assert.equal(query.limit, 10);
    assert.deepEqual(query.fields, []);
    assert.equal(query.cursor, null);
    assert.equal(query.as_of, null);
    assert.ok(!("token" in query) && !("access_key" in query));
  }
});
