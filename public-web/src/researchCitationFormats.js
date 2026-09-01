const escapeBibTeX = (value) => String(value ?? "").replace(/[{}\\]/g, (character) => `\\${character}`);
const citationKey = (paper) => `${paper.authors.split(" · ")[0]?.split(/\s+/).at(-1)?.toLowerCase() || "research"}${String(paper.year).replace(/\D/g, "") || "nd"}${paper.id.slice(0, 16)}`.replace(/[^a-z0-9]/gi, "");
const authors = (paper) => paper.authors.split(" · ").map((author) => author.trim()).filter(Boolean);
const year = (paper) => paper.year === "living" ? "" : String(paper.year).match(/\d{4}/)?.[0] || "";

export function researchBibTeX(paper) {
  const fields = [
    ["author", authors(paper).join(" and ")], ["title", paper.sourceTitle], ["journal", paper.venue], ["year", year(paper)], ["url", paper.sources[0]?.url],
  ].filter(([, value]) => value);
  return `@article{${citationKey(paper)},\n${fields.map(([key, value]) => `  ${key} = {${escapeBibTeX(value)}}`).join(",\n")}\n}`;
}

export function researchRis(paper) {
  const type = paper.kind === "book" ? "BOOK" : paper.kind === "industry-research" ? "RPRT" : "JOUR";
  return [
    `TY  - ${type}`, ...authors(paper).map((author) => `AU  - ${author}`), `TI  - ${paper.sourceTitle}`, `JO  - ${paper.venue}`,
    year(paper) && `PY  - ${year(paper)}`, paper.sources[0]?.url && `UR  - ${paper.sources[0].url}`, "ER  - ", "",
  ].filter((line) => line !== false).join("\n");
}

export function downloadCitation(text, filename, documentObject = document) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = documentObject.createElement("a");
  link.href = url; link.download = filename; link.hidden = true;
  documentObject.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}
