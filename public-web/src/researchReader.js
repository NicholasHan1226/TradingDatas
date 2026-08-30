export const initialResearchView = { topic: "all", kind: "all", page: 0, open: false };

export function researchViewReducer(state, action) {
  switch (action.type) {
    case "open": return { ...initialResearchView, open: true, topic: action.topic || "all" };
    case "topic": return { ...state, topic: action.value, page: 0 };
    case "kind": return { ...state, kind: action.value, page: 0 };
    case "page": return { ...state, page: Math.max(0, Math.floor(action.value) || 0) };
    case "visibility": return { ...state, open: action.value };
    default: return state;
  }
}

export function researchCitation(paper) {
  return `${paper.authors} (${paper.year === "living" ? "n.d." : paper.year}). ${paper.sourceTitle}. ${paper.venue}. ${paper.sources[0].url}`;
}
