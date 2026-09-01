// Development fallback; the production projection replaces this with one
// explicit dynamic import per published guide, never an import of all bodies.
export async function loadResearchGuide(id) {
  const [{ papers }, { researchReaderNotes }] = await Promise.all([
    import("./researchCatalog.js"), import("./researchReaderNotes.js"),
  ]);
  const paper = papers.find(item => item.id === id);
  const guide = paper && researchReaderNotes[paper.title];
  if (!guide) throw new Error("unknown_research_guide");
  return { readingNotes: guide.sections, readerLimits: guide.limits };
}
