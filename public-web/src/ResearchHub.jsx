import { useEffect, useRef } from "react";
import { ArrowRight, ArrowSquareOut, BookmarkSimple } from "@phosphor-icons/react";
import { papers, readingPaths, researchTitle, researchYear } from "./researchCatalog.js";
import { researchSubjects, researchMatches, researchHref, researchPageSize } from "./researchDiscovery.js";
import { researchJourneys, journeyStages } from "./researchJourneys.js";
import { researchQuestionRoutes } from "./researchQuestionRoutes.js";
import { ResearchQuestionRoutes } from "./ResearchQuestionRoutes.jsx";
import "./researchHub.css";

export function ResearchHub({ locale, view, onChange, featuredPaper, atlas, kindLabels, methods, bookmarks, onToggleBookmark, onNavigate }) {
  const zh = locale === "zh";
  const resultsRef = useRef(null);
  const subjectsRef = useRef(null);
  useEffect(() => {
    const index = subjectsRef.current;
    if (!index) return;
    const revealSelected = () => {
      const selected = index.querySelector('[aria-current="true"]');
      if (selected && index.scrollWidth > index.clientWidth) {
        index.scrollLeft += selected.getBoundingClientRect().left - index.getBoundingClientRect().left - 8;
      }
    };
    revealSelected();
    const observer = new ResizeObserver(revealSelected);
    observer.observe(index);
    return () => observer.disconnect();
  }, [view.open, view.topic, locale]);
  const subject = researchSubjects.find((item) => item.id === view.topic) || researchSubjects[0];
  const matches = papers.filter((paper) => researchMatches(paper, subject.id, view.kind));
  const pageCount = Math.max(1, Math.ceil(matches.length / researchPageSize));
  const page = Math.min(view.page, pageCount - 1);
  const visible = matches.slice(page * researchPageSize, (page + 1) * researchPageSize);
  const featuredHref = `/research/${featuredPaper.id}`;
  const guides = papers.filter((paper) => paper.readingNotes?.length >= 4);
  const journey = researchJourneys[subject.id];
  function change(event, action, scroll = false) {
    if (event?.metaKey || event?.ctrlKey || event?.shiftKey || event?.altKey) return;
    event?.preventDefault();
    onChange(action);
    if (scroll) requestAnimationFrame(() => {
      resultsRef.current?.scrollIntoView({ block: "start", behavior: "instant" });
      resultsRef.current?.focus({ preventScroll: true });
    });
  }
  return <section className="research-hub" aria-label={zh ? "研究" : "Research"}>
    <nav className="research-view-nav" aria-label={zh ? "研究阅读视角" : "Research views"}>
      {[false, true].map((open) => <a key={String(open)} href={researchHref({ ...view, open })} aria-current={view.open === open ? "page" : undefined} onClick={(event) => change(event, { type: "visibility", value: open })}>{open ? (zh ? "主题" : "Topics") : (zh ? "精选" : "Featured")}</a>)}
    </nav>

    {!view.open ? <div className="research-curated">
      <section className="research-editorial-hero" aria-labelledby="research-feature-title">
        <div className="research-editorial-copy">
          <p className="research-editorial-kicker">{zh ? "推荐阅读 · 中国市场" : "FEATURED READING · CHINA MARKETS"}</p>
          <h1 id="research-feature-title"><a href={featuredHref} onClick={(event) => onNavigate(event, featuredHref)}>{zh ? <><span>中国股票市场的发展</span><span>及其全球经济意义</span></> : researchTitle(featuredPaper, locale)}</a></h1>
          <p className="research-editorial-authors">{featuredPaper.authors}</p>
          <p className="research-editorial-source">{featuredPaper.venue} · {researchYear(featuredPaper, locale)}</p>
          <p className="research-editorial-intro">{zh ? "从所有权与制度结构出发，理解中国股票市场的研究背景。" : "Understand China's stock market through its ownership, institutions, and development."}</p>
          <div className="research-editorial-actions"><a className="primary-button" href={featuredHref} onClick={(event) => onNavigate(event, featuredHref)}>{zh ? "阅读导读" : "Read guide"}<ArrowRight /></a><a className="text-link" href={featuredPaper.sources[0].url} target="_blank" rel="noreferrer">{zh ? "查看原文来源" : "View original source"}<ArrowSquareOut /></a></div>
        </div>
        <img className="research-editorial-art" src="/assets/research-editorial-architecture.webp" width="1024" height="1024" alt="" fetchPriority="high" />
      </section>
      <div className="research-curated-paths">{[0, 2].map((index) => {
        const path = atlas.paths[index];
        const href = `/research/paths/${readingPaths[index].id}`;
        return <a key={href} href={href} onClick={(event) => onNavigate(event, href)}><div><h2>{path.question}</h2><p>{path.data}</p></div><ArrowRight /></a>;
      })}</div>
      <a className="research-browse-link" href="/research?view=topics" onClick={(event) => change(event, { type: "open", topic: "all" })}>{zh ? "按主题浏览全部文献" : "Browse all literature by topic"}<ArrowRight /></a>
      <section className="research-guide-shelf" aria-labelledby="research-guides-title"><header><h2 id="research-guides-title">{zh ? "精选导读" : "Selected reading guides"}</h2><p>{zh ? "从研究问题出发，读懂方法、主要发现与适用边界。" : "Read the question, approach, findings, and limitations together."}</p></header><div>{guides.map((paper) => <article key={paper.id}><p className="research-bibliographic-meta">{researchSubjects.find((item) => researchMatches(paper, item.id, "all") && item.id !== "all")?.label[locale]} · {researchYear(paper, locale)}</p><h3><a href={`/research/${paper.id}`} onClick={(event) => onNavigate(event, `/research/${paper.id}`)}>{researchTitle(paper, locale)}<ArrowRight /></a></h3><p>{paper.summary[locale]}</p><p className="research-bibliographic-meta">{paper.authors}</p></article>)}</div></section>
      <details className="research-method-disclosure"><summary>{zh ? "更多阅读路径与数据准备方法" : "More reading paths & data preparation"}</summary><div>
        <a href="/research/paths/market-microstructure" onClick={(event) => onNavigate(event, "/research/paths/market-microstructure")}>{atlas.paths[1].question}<ArrowRight /></a>
        {methods.map((method) => <a key={method.id} href={`/recipes/${method.id}`} onClick={(event) => onNavigate(event, `/recipes/${method.id}`)}>{method.title[locale]}<ArrowRight /></a>)}
      </div></details>
    </div> : <div className="research-topic-view">
      <header className="research-topic-heading"><h1>{zh ? "研究文献" : "Research library"}</h1><p>{zh ? "按主题找到下一篇值得读的论文。" : "Find your next worthwhile read, by topic."}</p></header>
      <div className="research-subject-layout">
        <nav className="research-subject-index" ref={subjectsRef} aria-label={zh ? "研究主题" : "Research topics"}>{researchSubjects.map((item) => <a key={item.id} href={researchHref({ ...view, open: true, topic: item.id, kind: "all", page: 0 })} aria-current={subject.id === item.id ? "true" : undefined} onClick={(event) => change(event, { type: "open", topic: item.id })}><span>{item.label[locale]}</span><span>{papers.filter((paper) => researchMatches(paper, item.id, "all")).length}</span></a>)}</nav>
        <section className="research-subject-results" ref={resultsRef} tabIndex={-1} aria-labelledby="research-subject-title">
          <header className="research-subject-heading"><div><h2 id="research-subject-title">{subject.label[locale]}</h2><p>{subject.description[locale]}</p></div><select aria-label={zh ? "文献类型" : "Publication type"} value={view.kind} onChange={(event) => change(null, { type: "kind", value: event.target.value })}>{Object.entries(kindLabels).map(([id, label]) => <option key={id} value={id}>{id === "all" ? (zh ? "全部类型" : "All types") : label}</option>)}</select></header>
          {journey && view.kind === "all" && page === 0 && <section className="research-journey" aria-label={zh ? "建议阅读顺序" : "Suggested reading order"}><h3>{zh ? "从这里开始" : "A reading route"}</h3><ol>{journey.map((step, index) => {
            const paper = papers.find((item) => item.title === step.title || item.sourceTitle === step.title);
            return <li key={step.title}><span>{String(index + 1).padStart(2, "0")} · {journeyStages[index][locale]}</span><div><a href={`/research/${paper.id}`} onClick={(event) => onNavigate(event, `/research/${paper.id}`)}>{researchTitle(paper, locale)}<ArrowRight /></a><p>{step.reason[locale]}</p></div></li>;
          })}</ol></section>}
          <p className="research-result-status" role="status">{zh ? `${matches.length} 条文献` : `${matches.length} materials`}{view.kind !== "all" && <button type="button" onClick={() => onChange({ type: "kind", value: "all" })}>{zh ? "清除类型筛选" : "Clear type filter"}</button>}</p>
          {view.kind === "all" && page === 0 && <ResearchQuestionRoutes locale={locale} routes={researchQuestionRoutes.filter(route => route.topic === subject.id)} onNavigate={onNavigate} />}
          <div className="research-bibliographic-list">{visible.map((paper) => {
            const href = `/research/${paper.id}`;
            const title = researchTitle(paper, locale);
            const key = `research:${paper.id}`;
            const saved = bookmarks.includes(key);
            return <article className="research-bibliographic-row" key={paper.id}>
              <h3><a href={href} onClick={(event) => onNavigate(event, href)}>{title}</a></h3>
              {zh && <p className="research-bibliographic-original" lang="en">{paper.sourceTitle}</p>}
              <p className="research-bibliographic-meta">{paper.authors} · {researchYear(paper, locale)} · {paper.venue}</p>
              <p className="research-bibliographic-summary">{paper.summary[locale]}</p>
              <div className="research-bibliographic-actions"><a href={href} onClick={(event) => onNavigate(event, href)} aria-label={`${zh ? "阅读导读" : "Read guide"}: ${title}`}>{zh ? "阅读导读" : "Read guide"}<ArrowRight /></a><button type="button" aria-pressed={saved} aria-label={`${saved ? (zh ? "取消收藏" : "Remove bookmark") : (zh ? "收藏" : "Bookmark")}: ${title}`} onClick={() => onToggleBookmark(key)}><BookmarkSimple weight={saved ? "fill" : "regular"} /></button></div>
            </article>;
          })}</div>
          {!visible.length && <div className="research-library-empty"><h3>{zh ? "这个主题下暂无此类文献" : "No materials of this type in this topic"}</h3><p>{zh ? "试试全部类型，或切换左侧主题。" : "Try all publication types, or choose another topic."}</p><button className="secondary-button" type="button" onClick={() => onChange({ type: "kind", value: "all" })}>{zh ? "查看全部类型" : "Show all types"}</button></div>}
          {pageCount > 1 && <nav className="research-pagination" aria-label={zh ? "文献分页" : "Library pages"}><button type="button" disabled={page === 0} onClick={(event) => change(event, { type: "page", value: page - 1 }, true)}>{zh ? "上一页" : "Previous"}</button><span aria-live="polite">{page + 1} / {pageCount}</span><button type="button" disabled={page + 1 === pageCount} onClick={(event) => change(event, { type: "page", value: page + 1 }, true)}>{zh ? "下一页" : "Next"}<ArrowRight /></button></nav>}
        </section>
      </div>
      <p className="research-library-footnote">{zh ? "外部文献与本站导读。完整论述与结论请见原文；收藏保存在当前浏览器。" : "External literature with editorial reading guides. Consult the originals for full arguments and conclusions. Bookmarks stay in this browser."}</p>
    </div>}
  </section>;
}
