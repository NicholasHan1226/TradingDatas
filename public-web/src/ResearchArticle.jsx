import { useEffect, useState } from "react";
import { ResearchRecord } from "./ResearchRecord.jsx";
import { loadResearchGuide } from "./researchGuideLoader.js";
import { observeResearchGuide, restoreGuideFragment } from "./researchGuideLoading.js";

export function ResearchArticle({ paper, ...props }) {
  const needsBody = paper.guideSectionCount > 0 && !paper.readingNotes;
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ status: needsBody ? "loading" : "ready", body: null });
  useEffect(() => {
    if (!needsBody) return undefined;
    return observeResearchGuide(paper.id, loadResearchGuide, setState);
  }, [paper.id, needsBody, attempt]);
  useEffect(() => {
    if (!needsBody || state.status !== "ready") return undefined;
    const frame = requestAnimationFrame(() => restoreGuideFragment(paper.id, window.location, document));
    return () => cancelAnimationFrame(frame);
  }, [paper.id, needsBody, state.status, state.body]);
  return <ResearchRecord {...props} paper={state.body ? { ...paper, ...state.body } : paper} bodyStatus={state.status} onRetryBody={() => setAttempt(value => value + 1)} />;
}
