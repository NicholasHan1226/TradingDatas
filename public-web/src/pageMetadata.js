import { papers, researchTitle, readingPaths } from "./researchCatalog.js";
import { preparationTutorials } from "./preparationTutorials.js";

export const publicOrigin = "https://tradingdatas.com";
export function pageMetadata(route, locale = "en") {
  const path = route.replace(/^\/+|\/+$/g, "");
  const paper = path.startsWith("research/") && papers.find((item) => path === `research/${item.id}`);
  const tutorial = path.startsWith("recipes/") && preparationTutorials[path.slice(8)];
  const readingPath = readingPaths.find((item) => path === `research/paths/${item.id}`);
  const zh = locale === "zh";
  const title = paper ? researchTitle(paper, locale) : tutorial ? tutorial.title[locale] : readingPath ? readingPath.title[locale] : path === "research" ? (zh ? "研究文献与精选导读" : "Research library & reading guides") : path === "recipes" ? (zh ? "数据准备教程" : "Data preparation tutorials") : (zh ? "可追溯的金融研究数据" : "Research-ready financial data");
  const researchRoute = /^(research|recipes)(\/|$)/.test(path);
  const description = paper ? `${paper.authors} · ${paper.venue} · ${paper.year}. ${paper.summary[locale]}` : tutorial ? tutorial.summary[locale] : researchRoute ? (zh ? "按精选与主题阅读外部研究，探索数据准备方法。" : "Discover external research by topic and explore data preparation methods.") : (zh ? "TradingDatas — 面向研究与Agent的高质量、可追溯、可组合金融数据。" : "TradingDatas — high-quality, traceable and composable financial data for research and Agents.");
  const canonicalPath = path === "home" ? "" : researchRoute ? `${path}/` : path;
  return { title: `${title} | TradingDatas`, description, url: `${publicOrigin}/${canonicalPath}`, type: paper || tutorial ? "article" : "website" };
}

export function applyPageMetadata(metadata) {
  document.title = metadata.title;
  for (const [attribute, key, value] of [
    ["name", "description", metadata.description],
    ["property", "og:title", metadata.title], ["property", "og:description", metadata.description],
    ["property", "og:url", metadata.url], ["property", "og:type", metadata.type],
    ["property", "og:site_name", "TradingDatas"], ["name", "twitter:card", "summary"],
  ]) {
    const node = document.querySelector(`meta[${attribute}="${key}"]`) || document.head.appendChild(document.createElement("meta"));
    node.setAttribute(attribute, key); node.setAttribute("content", value);
  }
  const canonical = document.querySelector('link[rel="canonical"]') || document.head.appendChild(document.createElement("link"));
  canonical.setAttribute("rel", "canonical"); canonical.setAttribute("href", metadata.url);
}
