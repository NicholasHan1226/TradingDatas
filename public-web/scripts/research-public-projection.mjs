import { papers, readingPaths, paperSlug, researchTitle, researchData, researchYear, researchUpdatedAt } from "../src/researchCatalog.js";
import { tutorialCode, tutorialExamples } from "../src/tutorialExamples.js";
import { gzipSync } from "node:zlib";

export const publicResearchFields = ["id", "title", "titleZh", "sourceTitle", "authors", "venue", "year", "kind", "topic", "data", "dataZh", "summary", "related", "sourceNote", "sources", "readingNotes", "readerLimits", "guideSectionCount", "readerReviewedAt"];
export function projectPaper(paper) {
  return Object.fromEntries(publicResearchFields.filter((key) => paper[key] !== undefined).map((key) => [key, paper[key]]));
}

export function projectResearchIndex(paper) {
  const { readingNotes, ...index } = projectPaper(paper);
  if (readingNotes?.length) delete index.readerLimits;
  return index;
}

const guidePrefix = "virtual:research-guide/";
export function inspectResearchChunks(bundle, expectedIds) {
  const initial = new Set();
  const visit = name => {
    if (initial.has(name)) return;
    const chunk = bundle[name];
    if (chunk?.type !== "chunk") return;
    initial.add(name);
    chunk.imports.forEach(visit);
  };
  Object.values(bundle).filter(item => item.type === "chunk" && item.isEntry).forEach(chunk => visit(chunk.fileName));
  const found = new Set();
  const guideChunks = [];
  for (const chunk of Object.values(bundle).filter(item => item.type === "chunk")) {
    const ids = Object.keys(chunk.modules).filter(id => id.startsWith(`\0${guidePrefix}`)).map(id => id.slice(guidePrefix.length + 1));
    if (!ids.length) continue;
    if (ids.length !== 1 || initial.has(chunk.fileName)) throw new Error("Research bodies must stay in individual non-initial chunks");
    if (found.has(ids[0])) throw new Error("Duplicate research body chunk");
    found.add(ids[0]); guideChunks.push(chunk);
  }
  if (found.size !== expectedIds.length || expectedIds.some(id => !found.has(id))) throw new Error("Research body chunk coverage mismatch");
  const size = chunks => ({ bytes: chunks.reduce((sum, c) => sum + Buffer.byteLength(c.code), 0), gzipBytes: chunks.reduce((sum, c) => sum + gzipSync(c.code).length, 0) });
  return { guideChunks: found.size, initialJavaScript: size([...initial].map(name => bundle[name])), deferredGuides: size(guideChunks) };
}
export function publicGuideModule(id) {
  const paper = papers.find(item => item.id === id && item.readingNotes?.length);
  if (!paper) throw new Error("unknown_research_guide");
  return `export default ${JSON.stringify({ readingNotes: paper.readingNotes, readerLimits: paper.readerLimits })};`;
}

export function publicResearchLoaderModule() {
  const imports = papers.filter(p => p.readingNotes?.length).map(p => `${JSON.stringify(p.id)}: () => import(${JSON.stringify(guidePrefix + p.id)})`);
  return `import { createResearchGuideLoader } from "./researchGuideLoading.js";\nexport const loadResearchGuide = createResearchGuideLoader({${imports.join(",\n")}});`;
}

// Build-time projection: editorial verification data remains in source control,
// but readers do not download duplicated bibliography responses and QA profiles.
export function publicResearchModule() {
  return [
    `export const papers = ${JSON.stringify(papers.map(projectResearchIndex))};`,
    `export const readingPaths = ${JSON.stringify(readingPaths)};`,
    `export const researchUpdatedAt = ${JSON.stringify(researchUpdatedAt)};`,
    ...Object.entries({ paperSlug, researchTitle, researchData, researchYear }).map(([name, fn]) => `export const ${name} = ${fn.toString()};`),
  ].join("\n");
}

export function researchPublicProjection() {
  return {
    name: "research-public-projection", apply: "build", enforce: "pre",
    resolveId(id) { if (id.startsWith(guidePrefix)) return `\0${id}`; },
    load(id) { if (id.startsWith(`\0${guidePrefix}`)) return publicGuideModule(id.slice(guidePrefix.length + 1)); },
    generateBundle(_options, bundle) {
      this.info(`Research delivery: ${JSON.stringify(inspectResearchChunks(bundle, papers.filter(p => p.readingNotes?.length).map(p => p.id)))}`);
    },
    transform(source, id) {
      if (id.replaceAll("\\", "/").endsWith("/src/researchGuideLoader.js")) return { code: publicResearchLoaderModule(), map: null };
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
