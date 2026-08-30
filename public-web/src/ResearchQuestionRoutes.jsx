import { ArrowRight } from "@phosphor-icons/react";
import { papers, researchTitle } from "./researchCatalog.js";
import { journeyStages } from "./researchJourneys.js";
import "./researchQuestionRoutes.css";

export function ResearchQuestionRoutes({locale, routes, currentPaper, onNavigate}) {
  if (!routes.length) return null;
  const zh = locale === "zh";
  return <section className="research-question-routes" aria-label={zh ? "按问题继续阅读" : "Read by question"}>
    <h2>{zh ? "按问题继续阅读" : "Read by question"}</h2>
    {routes.map(route => <details key={route.id} open={currentPaper ? true : undefined}>
      <summary>{route.question[locale]}</summary>
      <ol>{route.steps.map((step, index) => {
        const paper = papers.find(item => item.title === step.title);
        const current = paper.id === currentPaper?.id;
        const href = `/research/${paper.id}`;
        return <li key={paper.id}>
          <small>{String(index+1).padStart(2,"0")} · {journeyStages[index][locale]}{current ? (zh ? " · 正在阅读" : " · Reading now") : ""}</small>
          {current ? <span className="research-question-current" aria-current="page">{researchTitle(paper,locale)}</span> : <a href={href} onClick={event=>onNavigate(event,href)}>{researchTitle(paper,locale)}<ArrowRight /></a>}
          <p>{step.reason[locale]}</p>
        </li>;
      })}</ol>
    </details>)}
  </section>;
}
