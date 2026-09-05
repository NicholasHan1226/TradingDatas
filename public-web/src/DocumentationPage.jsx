import { useState } from "react";
import { copyText } from "./copyText.js";
import { ArrowRight, Copy, Check } from "@phosphor-icons/react";
import "./documentation.css";

function Example({ code, locale }) {
  const [result, setResult] = useState("");
  async function copy() {
    setResult(await copyText(code));
  }
  return <div className="doc-example"><div><span>{locale === "zh" ? "请求示例 · 仅供复制" : "Request example · copy only"}</span><button type="button" onClick={copy}>{result === "copied" ? <Check /> : <Copy />}{locale === "zh" ? "复制" : "Copy"}</button></div><pre tabIndex={0}><code>{code}</code></pre><span className="doc-copy-feedback" role="status">{result === "copied" ? (locale === "zh" ? "已复制" : "Copied") : result === "failed" ? (locale === "zh" ? "无法自动复制，请选择示例文字复制。" : "Select the example text to copy it manually.") : ""}</span></div>;
}

export function DocumentationPage({ locale, slug, documentation, onNavigate }) {
  const zh = locale === "zh";
  const { categories, guides } = documentation;
  const guide = guides.find(item => item.slug === slug);
  const link = (path) => event => onNavigate(event, path);
  const category = categories.find(item => item.key === guide?.category);
  const index = guides.findIndex(item => item.slug === slug);
  const sidebar = <nav aria-label={zh ? "文档目录" : "Documentation navigation"}>
    <a className="doc-overview-link" href="/docs" onClick={link("/docs")} aria-current={!slug ? "page" : undefined}>{zh ? "文档首页" : "Overview"}</a>
    {categories.map(group => <div className="doc-nav-group" key={group.key}><p>{group.label}</p>{guides.filter(item => item.category === group.key).map(item => <a key={item.slug} href={`/docs/${item.slug}`} onClick={link(`/docs/${item.slug}`)} aria-current={slug === item.slug ? "page" : undefined}>{item.title}</a>)}</div>)}
  </nav>;
  return <section className="documentation" aria-label="Docs">
    <aside className="doc-sidebar"><a className="doc-wordmark" href="/docs" onClick={link("/docs")}>Docs</a><div className="doc-desktop-directory">{sidebar}</div><details className="doc-mobile-directory" key={slug || "home"}><summary>{zh ? "浏览文档目录" : "Browse documentation"}</summary>{sidebar}</details></aside>
    <div className="doc-main" key={`${locale}-${slug}`}>
      {!slug ? <>
        <header className="doc-header"><span className="mono-kicker">TRADINGDATAS / DOC</span><h1>{zh ? "从了解数据，到完成接入。" : "From exploring data to your first request."}</h1><p>{zh ? "查找使用步骤、数据说明和账户帮助。文档可直接阅读，查询数据需要有效的 API 密钥。" : "Find practical steps, data guidance, and account help. Read freely; use a valid API key to query data."}</p></header>
        <section className="doc-start" aria-labelledby="doc-start-title"><h2 id="doc-start-title">{zh ? "从这里开始" : "Start here"}</h2><div>{["start-2", "api-3", "commerce-3"].map((id, i) => { const item = guides.find(g => g.slug === id); return item && <a href={`/docs/${id}`} key={id} onClick={link(`/docs/${id}`)}><span className="doc-start-number">0{i+1}</span><span><strong>{item.title}</strong><small>{item.description}</small></span><ArrowRight /></a>; })}</div></section>
        <div className="doc-directory">{categories.map(group => <section key={group.key}><header><h2>{group.label}</h2><p>{group.description}</p></header><ul>{guides.filter(item => item.category === group.key).map(item => <li key={item.slug}><a href={`/docs/${item.slug}`} onClick={link(`/docs/${item.slug}`)}><span><strong>{item.title}</strong><small>{item.description}</small></span><ArrowRight /></a></li>)}</ul></section>)}</div>
      </> : guide ? <>
        <header className="doc-header doc-reader-header"><nav aria-label={zh ? "当前位置" : "Breadcrumb"}><a href="/docs" onClick={link("/docs")}>Docs</a><span aria-hidden="true">/</span><span>{category?.label}</span></nav><h1>{guide.title}</h1><p>{guide.description}</p></header>
        <nav className="doc-on-page" aria-label={zh ? "本页内容" : "On this page"}><span>{zh ? "本页内容" : "On this page"}</span>{guide.sections.map(section => <a key={section.id} href={`#${section.id}`}>{section.title}</a>)}</nav>
        <article className="doc-prose">{guide.sections.map(section => <section key={section.id} id={section.id}><h2>{section.title}</h2>{section.paragraphs?.map((paragraph, i) => <p key={i}>{paragraph}</p>)}{section.steps?.length > 0 && <ol>{section.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}{section.code && <Example code={section.code} locale={locale} />}</section>)}</article>
        <section className="doc-related"><h2>{zh ? "继续阅读与使用" : "Continue reading & using"}</h2>{guide.related.map(item => <a key={item.path} href={item.path} onClick={link(item.path)}>{item.label}<ArrowRight /></a>)}</section>
        <nav className="doc-pagination" aria-label={zh ? "相邻文档" : "Adjacent guides"}>{[guides[index - 1], guides[index + 1]].map((item, i) => item ? <a key={item.slug} href={`/docs/${item.slug}`} onClick={link(`/docs/${item.slug}`)}><small>{i === 0 ? (zh ? "上一篇" : "Previous") : (zh ? "下一篇" : "Next")}</small><span>{item.title}</span></a> : <span key={i} />)}</nav>
      </> : <header className="doc-header"><h1>{zh ? "没有找到这篇文档" : "Guide not found"}</h1><p>{zh ? "请从左侧目录选择文档，或返回文档首页。" : "Choose a guide from the directory, or return to the overview."}</p><a className="text-link" href="/docs" onClick={link("/docs")}>{zh ? "返回 Docs" : "Back to Docs"}<ArrowRight /></a></header>}
    </div>
  </section>;
}
