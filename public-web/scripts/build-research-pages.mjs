import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { papers, readingPaths } from "../src/researchCatalog.js";
import { preparationTutorials } from "../src/preparationTutorials.js";
import { pageMetadata } from "../src/pageMetadata.js";

export const escapeHtml = (text) => String(text).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
export function renderResearchPage(template, route) {
  const en = pageMetadata(route, "en"), zh = pageMetadata(route, "zh");
  const title = `${zh.title.replace(/ \| TradingDatas$/, "")} / ${en.title}`;
  const description = `${zh.description} ${en.description}`;
  return template.replace(/<title>[\s\S]*?<\/title>/, `<title>${escapeHtml(title)}</title>`)
    .replace(/<meta name="description"[^>]*>/, `<meta name="description" content="${escapeHtml(description)}" />`)
    .replace(/<link rel="canonical"[^>]*>/, `<link rel="canonical" href="${escapeHtml(en.url)}" />`)
    .replace("</head>", `<meta property="og:title" content="${escapeHtml(title)}" />\n<meta property="og:description" content="${escapeHtml(description)}" />\n<meta property="og:url" content="${escapeHtml(en.url)}" />\n<meta property="og:type" content="${en.type}" />\n<meta property="og:site_name" content="TradingDatas" />\n<meta name="twitter:card" content="summary" />\n</head>`);
}
export const researchPageRoutes = ["research", "recipes", ...papers.map((paper) => `research/${paper.id}`), ...readingPaths.map((item) => `research/paths/${item.id}`), ...Object.keys(preparationTutorials).map((id) => `recipes/${id}`)];

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const dist = fileURLToPath(new URL("../dist/client/", import.meta.url));
  const template = readFileSync(path.join(dist, "index.html"), "utf8");
  for (const route of researchPageRoutes) {
    const directory = path.join(dist, route);
    mkdirSync(directory, { recursive: true });
    writeFileSync(path.join(directory, "index.html"), renderResearchPage(template, route));
  }
  console.log(`Prepared ${researchPageRoutes.length} research/tutorial HTML entries with share metadata.`);
}
