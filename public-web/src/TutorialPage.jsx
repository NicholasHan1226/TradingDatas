import { useState } from "react";
import { ArrowRight, ArrowSquareOut, BookmarkSimple, Copy, Play, DownloadSimple } from "@phosphor-icons/react";
import { papers, researchTitle } from "./researchCatalog.js";
import { preparationTutorials } from "./preparationTutorials.js";
import { tutorialCode, tutorialExamples } from "./tutorialExamples.js";
import { copyText } from "./copyText.js";
import "./tutorial.css";

export default function TutorialPage({ id, locale, onNavigate, saved, onToggleBookmark }) {
  const tutorial = preparationTutorials[id];
  const [output, setOutput] = useState(null);
  const [copyState, setCopyState] = useState("");
  const zh = locale === "zh";
  if (!tutorial) return <section className="object-detail-page"><h1>{zh ? "教程未找到" : "Tutorial not found"}</h1><a href="/research" onClick={(event) => onNavigate(event, "/research")}>{zh ? "返回研究" : "Back to Research"}</a></section>;
  const code = tutorialCode(id);
  async function copyCode() {
    setCopyState(await copyText(code));
  }
  function runExample() {
    try { const example = tutorialExamples[id]; setOutput({ value: example.execute(...example.args) }); }
    catch { setOutput({ error: true }); }
  }
  const related = tutorial.research.map((title) => papers.find((paper) => paper.title === title));
  return <article className="object-detail-page research-record tutorial-page">
    <a className="object-back" href="/research" onClick={(event) => onNavigate(event, "/research")}>← {zh ? "返回研究" : "Back to Research"}</a>
    <header className="research-reader-header"><div className="research-reader-meta"><span>{zh ? "数据准备教程" : "Data preparation tutorial"}</span><span>v1 · 2026-08-30</span></div><h1>{tutorial.title[locale]}</h1><p className="research-reader-intro">{tutorial.summary[locale]}</p><div className="research-reader-actions"><a className="primary-button" href="#tutorial-example">{zh ? "试运行示例" : "Try the example"}<ArrowRight /></a><button className="secondary-button" type="button" aria-pressed={saved} onClick={onToggleBookmark}><BookmarkSimple weight={saved ? "fill" : "regular"} />{saved ? (zh ? "已收藏" : "Saved") : (zh ? "收藏" : "Bookmark")}</button></div><p className="research-reader-action-note">{zh ? "示例在浏览器内运行，使用虚构数据，不连接账户或外部服务。收藏仅保存在当前浏览器。" : "Examples run locally with synthetic data, without account or external-service access. Bookmarks stay in this browser."}</p></header>
    <div className="research-reader-layout"><div className="research-reader-body">
      <section id="tutorial-goal"><h2>{zh ? "完成后得到什么" : "What you will produce"}</h2><p>{tutorial.goal[locale]}</p></section>
      <section id="tutorial-inputs"><h2>{zh ? "准备输入" : "Prepare the inputs"}</h2><ul>{tutorial.fields.map((field) => <li key={field.en}>{field[locale]}</li>)}</ul><p>{zh ? "下面是本地教学字段，不是直接可提交的API字段。真实数据需要按已授权目录映射并保留原始字段。" : "These are local teaching fields, not request-ready API fields. Map authorized source fields explicitly and retain the originals."}</p></section>
      {tutorial.steps.map((step, index) => <section key={step.title.en} id={`tutorial-step-${index + 1}`}><h2>{step.title[locale]}</h2><p>{step.body[locale]}</p></section>)}
      <section id="tutorial-example"><h2>{zh ? "用虚构小样本验证" : "Verify with a synthetic sample"}</h2><p>{tutorial.expected[locale]}</p><details><summary>{zh ? "查看输入与完整JavaScript示例" : "View inputs and complete JavaScript example"}</summary><pre tabIndex={0} aria-label={zh ? "JavaScript示例" : "JavaScript example"}><code>{code}</code></pre></details><div className="research-reader-actions"><button type="button" className="primary-button" onClick={runExample}><Play />{zh ? "运行虚构示例" : "Run synthetic example"}</button><button type="button" className="secondary-button" onClick={copyCode}><Copy />{zh ? "复制示例代码" : "Copy example code"}</button></div><p role="status">{copyState === "copied" ? (zh ? "代码已复制" : "Code copied") : copyState === "failed" ? (zh ? "无法自动复制，请选中下方代码手动复制。" : "Automatic copy failed. Select the code below to copy manually.") : ""}</p>{copyState === "failed" && <textarea className="research-citation-fallback" aria-label={zh ? "可复制代码" : "Selectable code"} readOnly value={code} onFocus={(event) => event.target.select()} />}
        {output && <div className="tutorial-output"><p role="status">{output.error ? (zh ? "示例未完成，请重新加载后重试。" : "Example failed. Reload and retry.") : (zh ? "示例完成；下方仅为虚构数据的处理结果。" : "Example complete. Output below is synthetic.")}</p>{!output.error && <pre tabIndex={0} aria-label={zh ? "虚构示例结果" : "Synthetic example output"}><code>{JSON.stringify(output.value, null, 2)}</code></pre>}</div>}
      </section>
      <section id="tutorial-downloads"><h2>{zh ? "下载后继续练习" : "Continue offline"}</h2><p>{zh ? "下载虚构输入数据、可独立运行的JavaScript示例，或中文Python笔记本。笔记本内含同一份输入和结果检查，使用Python 3.10+标准库，不需要密钥或联网；在已有Jupyter环境中打开即可。" : "Download synthetic inputs, a standalone JavaScript example, or an English Python notebook. The notebook includes the same inputs and output checks, uses the Python 3.10+ standard library, and needs no keys or network access. Open it in an existing Jupyter environment."}</p><div className="tutorial-downloads">
        {[["inputs.json", zh ? "虚构输入与预期结果 · JSON" : "Synthetic inputs & expected output · JSON"], ["example.mjs", zh ? "完整示例 · JavaScript" : "Complete example · JavaScript"], [`tutorial-${locale}.ipynb`, zh ? "中文笔记本 · Python" : "English notebook · Python"]].map(([file, label]) => <a key={file} href={`/downloads/research/${id}/${file}`} download={`${id}-${file}`}><DownloadSimple /><span>{label}</span></a>)}
      </div></section>
      <section id="tutorial-pitfalls"><h2>{zh ? "常见错误与验证" : "Pitfalls and validation"}</h2><ul>{tutorial.pitfalls.map((item) => <li key={item.en}>{item[locale]}</li>)}</ul></section>
      <section id="tutorial-real-data"><h2>{zh ? "换成真实数据之前" : "Before using real data"}</h2><p>{zh ? "先通过已认证的 GET /v1/catalog 确认可访问的数据集、schema_major、允许字段与过滤条件。下列ID来自项目目录合同，不保证你的账户已获授权或包含完整历史。" : "Use authenticated GET /v1/catalog to confirm datasets, schema_major, allowed fields and filters. These IDs come from the project contract, not proof of your entitlement or historical coverage."}</p><ul>{tutorial.datasetIds.map((datasetId) => <li key={datasetId}><code>{datasetId}</code></li>)}</ul><p>{zh ? "套餐要求：以账户对上述数据集的实际授权为准，不从套餐名称推断访问范围。财务版本、精确公告时点或额外原文授权可能仍需自行补充。" : "Plan requirement: actual grants for these datasets, not a plan-name assumption. Historical filing versions, exact announcement times or additional document rights may still be needed."}</p><details><summary>{zh ? "有界查询结构（仅供复制，不会发送）" : "Bounded query shape (copy only; never sent)"}</summary><pre tabIndex={0}><code>{`// POST /v1/query\n// catalogRow is the selected authenticated catalog entry.\nconst request = {\n  dataset_id: catalogRow.dataset_id,\n  schema_major: catalogRow.schema_major,\n  fields: [],\n  filters: {},\n  as_of: null,\n  limit: 3,\n  cursor: null\n};`}</code></pre></details><p>{zh ? "这只预览最多3行，不证明研究窗口完整。按目录允许的过滤条件限定实际窗口；保存每页游标和来源回执，并在取齐所需记录后离线完成连接。不要把API的as_of字段直接等同于历史披露版本。" : "This previews at most three rows, not a complete research window. Restrict the actual window with permitted filters, retain cursors and provenance, and join the required records offline. API as_of is not automatically a historical filing-version contract."}</p></section>
      <section><h2>{zh ? "参考资料" : "References"}</h2><ul>{tutorial.sources.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{source.label[locale]} <ArrowSquareOut /></a></li>)}</ul></section>
    </div><aside className="research-reader-aside" aria-label={zh ? "教程导航" : "Tutorial navigation"}><nav aria-label={zh ? "本页目录" : "On this page"}><h2>{zh ? "本页内容" : "On this page"}</h2>{[["tutorial-inputs", "准备输入", "Inputs"], ["tutorial-step-1", "操作步骤", "Steps"], ["tutorial-example", "运行示例", "Example"], ["tutorial-downloads", "离线下载", "Downloads"], ["tutorial-pitfalls", "常见错误", "Pitfalls"], ["tutorial-real-data", "真实数据", "Real data"]].map(([id, zhLabel, enLabel]) => <a key={id} href={`#${id}`}>{zh ? zhLabel : enLabel}</a>)}</nav><section><h2>{zh ? "相关研究" : "Related research"}</h2><div className="research-next-list">{related.filter(Boolean).map((paper) => <a key={paper.id} href={`/research/${paper.id}`} onClick={(event) => onNavigate(event, `/research/${paper.id}`)}>{researchTitle(paper, locale)}<ArrowRight /></a>)}</div></section></aside></div>
  </article>;
}
