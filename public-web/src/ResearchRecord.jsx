import { useState } from "react";
import { ArrowRight, ArrowSquareOut, BookmarkSimple, Check, Copy, LinkSimple } from "@phosphor-icons/react";
import { papers, researchTitle, researchData, researchYear } from "./researchCatalog.js";
import { readingJourney } from "./researchJourneys.js";
import { comparisonReadings } from "./researchConnections.js";
import { questionRoutesFor } from "./researchQuestionRoutes.js";
import { ResearchQuestionRoutes } from "./ResearchQuestionRoutes.jsx";
import { researchSubjects } from "./researchDiscovery.js";
import { researchCitation } from "./researchReader.js";
import { downloadCitation, researchBibTeX, researchRis } from "./researchCitationFormats.js";
import { copyText } from "./copyText.js";
import { pageMetadata } from "./pageMetadata.js";

export function ResearchRecord({ paper, locale, topicLabel, kindLabel, related, furtherReading, saved, onToggleBookmark, onNavigate, backHref = "/research", bodyStatus = "ready", onRetryBody }) {
  const [copyState, setCopyState] = useState("idle");
  const [linkState, setLinkState] = useState("idle");
  const [exportState, setExportState] = useState("");
  const zh = locale === "zh";
  const citation = researchCitation(paper);
  const shareUrl = pageMetadata(`research/${paper.id}`, locale).url;
  const journey = readingJourney(paper, papers);
  const journeyTopic = researchSubjects.find((subject) => subject.id === journey?.topic);
  const comparisons = comparisonReadings(paper, papers, journey?.links.map(link => link.paper.id));
  async function copyCitation() {
    setCopyState(await copyText(citation));
  }
  function download(format) {
    const extension = format === "bib" ? "bib" : "ris";
    downloadCitation(format === "bib" ? researchBibTeX(paper) : researchRis(paper), `${paper.id}.${extension}`);
    setExportState(format);
  }

  return <article className="object-detail-page research-record">
    <a className="object-back" href={backHref} onClick={(event) => onNavigate(event, backHref)}>← {zh ? "返回研究库" : "Back to Research"}</a>
    <header className="research-reader-header">
      <div className="research-reader-meta"><span>{topicLabel}</span><span>{kindLabel}</span><span>{researchYear(paper, locale)}</span></div>
      <h1>{researchTitle(paper, locale)}</h1>
      <p className="research-reader-authors">{paper.authors}</p>
      <p className="research-reader-venue">{paper.venue}</p>
      {zh && <p className="research-original-title" lang="en">{paper.sourceTitle}</p>}
      <div className="research-reader-actions">
        <a className="primary-button" href={paper.sources[0].url} target="_blank" rel="noreferrer">{zh ? "阅读原文" : "Read original"}<ArrowSquareOut /></a>
        <button className="secondary-button" type="button" aria-pressed={saved} onClick={onToggleBookmark}><BookmarkSimple weight={saved ? "fill" : "regular"} />{saved ? (zh ? "已收藏" : "Saved") : (zh ? "收藏" : "Bookmark")}</button>
        <button className="secondary-button" type="button" onClick={copyCitation}>{copyState === "copied" ? <Check /> : <Copy />}{zh ? "复制引用" : "Copy citation"}</button>
        <button className="secondary-button" type="button" onClick={() => download("bib")}>{zh ? "导出 BibTeX" : "Export BibTeX"}</button>
        <button className="secondary-button" type="button" onClick={() => download("ris")}>{zh ? "导出 RIS" : "Export RIS"}</button>
        <button className="secondary-button" type="button" onClick={async () => setLinkState(await copyText(shareUrl))}><LinkSimple />{zh ? "分享链接" : "Copy link"}</button>
      </div>
      <p className="research-reader-action-note">{zh ? "收藏保存在当前浏览器。原文可能需要出版方访问权限。" : "Bookmarks stay in this browser. Publisher access may be required."}</p>
      <span className="research-copy-status" role="status">{copyState === "copied" ? (zh ? "引用已复制" : "Citation copied") : copyState === "failed" ? (zh ? "未能复制，请选中下方引用手动复制。" : "Could not copy. Select the citation below to copy manually.") : ""}</span>
      {copyState === "failed" && <textarea className="research-citation-fallback" aria-label={zh ? "文献引用" : "Citation text"} readOnly value={citation} onFocus={(event) => event.target.select()} />}
      <span role="status">{linkState === "copied" ? (zh ? "链接已复制" : "Link copied") : linkState === "failed" ? (zh ? "请选中下方链接手动复制。" : "Select the link below to copy manually.") : ""}</span>
      <span className="research-copy-status" role="status">{exportState === "bib" ? (zh ? "BibTeX 已下载" : "BibTeX downloaded") : exportState === "ris" ? (zh ? "RIS 已下载" : "RIS downloaded") : ""}</span>
      {linkState === "failed" && <input className="research-citation-fallback" aria-label={zh ? "可复制链接" : "Selectable link"} readOnly value={shareUrl} onFocus={(event) => event.target.select()} />}
    </header>

    {paper.readingNotes?.length > 0 && <details className="research-article-contents"><summary>{zh ? "本篇内容" : "In this guide"}</summary><nav aria-label={zh ? "文章目录" : "Article contents"}><ol>{paper.readingNotes.map((section,index)=><li key={section.title.en}><a href={`#research-section-${index+1}`}>{section.title[locale]}</a></li>)}</ol></nav></details>}
    <div className="research-reader-layout">
      <div className="research-reader-body">
        {bodyStatus === "loading" && <p role="status">{zh ? "正在载入导读…" : "Loading reading guide…"}</p>}
        {bodyStatus === "error" && <div role="alert"><p>{zh ? "导读暂时未能载入，你仍可打开原文或重试。" : "The guide could not be loaded. You can still open the original or try again."}</p><button className="secondary-button" type="button" onClick={onRetryBody}>{zh ? "重试" : "Try again"}</button></div>}
        <p className="research-reader-intro">{paper.summary[locale]}</p>
        {paper.readingNotes?.map((section,index) => <section key={section.title.en} id={`research-section-${index+1}`} tabIndex={-1}><h2>{section.title[locale]}</h2><p>{section.body[locale]}</p>{section.reference && <a className="text-link" href={section.reference.url} target="_blank" rel="noreferrer">{section.reference.label[locale]}<ArrowSquareOut /></a>}</section>)}
        <section><h2>{zh ? "涉及的数据" : "Data in focus"}</h2><p>{researchData(paper, locale)}</p></section>
        {paper.readerLimits && <section><h2>{zh ? "阅读时留意" : "Keep in mind"}</h2><p>{paper.readerLimits[locale]}</p></section>}
        {paper.sourceNote && <p className="research-edition-note">{paper.sourceNote[locale]}</p>}
      </div>
      <aside className="research-reader-aside" aria-label={zh ? "延伸阅读" : "Further reading"}>
        <ResearchQuestionRoutes locale={locale} routes={questionRoutesFor(paper)} currentPaper={paper} onNavigate={onNavigate} />
        {journey ? <nav className="research-journey-continuation" aria-label={zh ? "主题阅读顺序" : "Topic reading sequence"}>
          <h2>{journeyTopic.label[locale]}</h2><p className="research-journey-position">{journey.index + 1} / 3 · {journey.stage[locale]}</p><p>{journey.reason[locale]}</p>
          {journey.links.map(({ paper: item, direction, stage, reason }) => <div className="research-journey-link" key={item.id}><a href={`/research/${item.id}`} onClick={(event) => onNavigate(event, `/research/${item.id}`)}><small>{direction === "next" ? (zh ? "下一篇" : "Next read") : (zh ? "上一篇" : "Previous read")} · {stage[locale]}</small><span>{researchTitle(item, locale)}<ArrowRight /></span></a><p>{reason[locale]}</p></div>)}
          <a className="text-link" href={`/research?view=topics&topic=${journey.topic}`} onClick={(event) => onNavigate(event, `/research?view=topics&topic=${journey.topic}`)}>{zh ? "浏览这个主题" : "Explore this topic"}<ArrowRight /></a>
        </nav> : comparisons.length === 0 && furtherReading.length > 0 && <section><h2>{zh ? "同主题文献" : "In this topic"}</h2><div className="research-next-list">{furtherReading.map((item) => <a key={item.id} href={`/research/${item.id}`} onClick={(event) => onNavigate(event, `/research/${item.id}`)}><span>{researchTitle(item, locale)}</span><ArrowRight /></a>)}</div></section>}
        {comparisons.length > 0 && <nav className="research-journey-continuation research-comparison-readings" aria-label={zh ? "对照阅读" : "Read alongside"}>
          <h2>{zh ? "对照阅读" : "Read alongside"}</h2>
          {comparisons.map(({ paper: item, reason }) => <div className="research-journey-link" key={item.id}><a href={`/research/${item.id}`} onClick={(event) => onNavigate(event, `/research/${item.id}`)}><span>{researchTitle(item, locale)}<ArrowRight /></span></a><p>{reason[locale]}</p></div>)}
        </nav>}
        {related.length > 0 && <details className="research-related-disclosure"><summary>{zh ? "相关数据与方法" : "Related data & methods"}</summary><p>{zh ? "用于延伸探索，不等同于论文原始样本。" : "For further exploration, not the paper’s original sample."}</p><div className="research-related-list">{related.map((item) => <a key={`${item.label}:${item.id}`} href={item.href} onClick={(event) => onNavigate(event, item.href)}><small>{item.label}</small><span>{item.title}<ArrowRight /></span></a>)}</div></details>}
        {paper.sources.length > 1 && <section><h2>{zh ? "更多来源" : "Additional sources"}</h2>{paper.sources.slice(1).map((source) => <a className="text-link" key={source.url} href={source.url} target="_blank" rel="noreferrer">{source.label}<ArrowSquareOut /></a>)}</section>}
      </aside>
    </div>
  </article>;
}
