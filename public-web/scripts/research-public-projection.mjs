import { papers, readingPaths, paperSlug, researchTitle, researchData, researchYear, researchUpdatedAt } from "../src/researchCatalog.js";
import { tutorialCode, tutorialExamples } from "../src/tutorialExamples.js";

export const publicResearchFields = ["id", "title", "titleZh", "sourceTitle", "authors", "venue", "year", "kind", "topic", "data", "dataZh", "summary", "related", "sourceNote", "sources", "readingNotes", "readerLimits"];
export function projectPaper(paper) {
  return Object.fromEntries(publicResearchFields.filter((key) => paper[key] !== undefined).map((key) => [key, paper[key]]));
}

// Build-time projection: editorial verification data remains in source control,
// but readers do not download duplicated bibliography responses and QA profiles.
export function publicResearchModule() {
  return [
    `export const papers = ${JSON.stringify(papers.map(projectPaper))};`,
    `export const readingPaths = ${JSON.stringify(readingPaths)};`,
    `export const researchUpdatedAt = ${JSON.stringify(researchUpdatedAt)};`,
    ...Object.entries({ paperSlug, researchTitle, researchData, researchYear }).map(([name, fn]) => `export const ${name} = ${fn.toString()};`),
  ].join("\n");
}

export function researchPublicProjection() {
  return {
    name: "research-public-projection", apply: "build", enforce: "pre",
    transform(source, id) {
      if (id.replaceAll("\\", "/").endsWith("/src/researchCatalog.js")) return { code: publicResearchModule(), map: null };
      if (id.replaceAll("\\", "/").endsWith("/src/tutorialExamples.js")) {
        const start = source.indexOf("export function tutorialCode(");
        if (start < 0) throw new Error("Tutorial code export changed; review the readable-code build projection.");
        const snippets = Object.fromEntries(Object.keys(tutorialExamples).map((key) => [key, tutorialCode(key)]));
        return { code: `${source.slice(0, start)}\nconst readableExamples = ${JSON.stringify(snippets)};\nexport const tutorialCode = (id) => readableExamples[id];`, map: null };
      }
    },
  };
}
