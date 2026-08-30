import{r as s,p as j,j as e,a as _,b as E,s as x,c as S,d as O,n as A,e as N,f as T}from"./index-BK6E7kqG.js";import"./react-vendor-CXZBankB.js";const D=new Map([["bold",s.createElement(s.Fragment,null,s.createElement("path",{d:"M234.49,111.07,90.41,22.94A20,20,0,0,0,60,39.87V216.13a20,20,0,0,0,30.41,16.93l144.08-88.13a19.82,19.82,0,0,0,0-33.86ZM84,208.85V47.15L216.16,128Z"}))],["duotone",s.createElement(s.Fragment,null,s.createElement("path",{d:"M228.23,134.69,84.15,222.81A8,8,0,0,1,72,216.12V39.88a8,8,0,0,1,12.15-6.69l144.08,88.12A7.82,7.82,0,0,1,228.23,134.69Z",opacity:"0.2"}),s.createElement("path",{d:"M232.4,114.49,88.32,26.35a16,16,0,0,0-16.2-.3A15.86,15.86,0,0,0,64,39.87V216.13A15.94,15.94,0,0,0,80,232a16.07,16.07,0,0,0,8.36-2.35L232.4,141.51a15.81,15.81,0,0,0,0-27ZM80,215.94V40l143.83,88Z"}))],["fill",s.createElement(s.Fragment,null,s.createElement("path",{d:"M240,128a15.74,15.74,0,0,1-7.6,13.51L88.32,229.65a16,16,0,0,1-16.2.3A15.86,15.86,0,0,1,64,216.13V39.87a15.86,15.86,0,0,1,8.12-13.82,16,16,0,0,1,16.2.3L232.4,114.49A15.74,15.74,0,0,1,240,128Z"}))],["light",s.createElement(s.Fragment,null,s.createElement("path",{d:"M231.36,116.19,87.28,28.06a14,14,0,0,0-14.18-.27A13.69,13.69,0,0,0,66,39.87V216.13a13.69,13.69,0,0,0,7.1,12.08,14,14,0,0,0,14.18-.27l144.08-88.13a13.82,13.82,0,0,0,0-23.62Zm-6.26,13.38L81,217.7a2,2,0,0,1-2.06,0,1.78,1.78,0,0,1-1-1.61V39.87a1.78,1.78,0,0,1,1-1.61A2.06,2.06,0,0,1,80,38a2,2,0,0,1,1,.31L225.1,126.43a1.82,1.82,0,0,1,0,3.14Z"}))],["regular",s.createElement(s.Fragment,null,s.createElement("path",{d:"M232.4,114.49,88.32,26.35a16,16,0,0,0-16.2-.3A15.86,15.86,0,0,0,64,39.87V216.13A15.94,15.94,0,0,0,80,232a16.07,16.07,0,0,0,8.36-2.35L232.4,141.51a15.81,15.81,0,0,0,0-27ZM80,215.94V40l143.83,88Z"}))],["thin",s.createElement(s.Fragment,null,s.createElement("path",{d:"M230.32,117.9,86.24,29.79a11.91,11.91,0,0,0-12.17-.23A11.71,11.71,0,0,0,68,39.89V216.11a11.71,11.71,0,0,0,6.07,10.33,11.91,11.91,0,0,0,12.17-.23L230.32,138.1a11.82,11.82,0,0,0,0-20.2Zm-4.18,13.37L82.06,219.39a4,4,0,0,1-4.07.07,3.77,3.77,0,0,1-2-3.35V39.89a3.77,3.77,0,0,1,2-3.35,4,4,0,0,1,4.07.07l144.08,88.12a3.8,3.8,0,0,1,0,6.54Z"}))]]),b=s.forwardRef((l,a)=>s.createElement(j,{ref:a,...l,weights:D}));b.displayName="PlayIcon";const M=b;function k(l,a){if(!l.length)throw new Error("empty_input");const d=new Set,h=l[0].security;for(const t of l){if(t.security!==h||!t.security)throw new Error("one_security_required");const o=Date.parse(`${t.date}T00:00:00Z`);if(!/^\d{4}-\d{2}-\d{2}$/.test(t.date)||!Number.isFinite(o)||new Date(o).toISOString().slice(0,10)!==t.date||d.has(t.date))throw new Error("invalid_or_duplicate_date");if(!Number.isFinite(t.close)||t.close<=0||!Number.isFinite(t.factor)||t.factor<=0)throw new Error("invalid_price_or_factor");d.add(t.date)}const u=l.find(t=>t.date===a);if(!u)throw new Error("missing_anchor");return[...l].sort((t,o)=>t.date.localeCompare(o.date)).map(t=>({...t,anchorDate:a,adjustedClose:Number((t.close*t.factor/u.factor).toFixed(6))}))}function C(l,a){const d=i=>{if(typeof i!="string"||!/T.*(Z|[+-]\d{2}:\d{2})$/.test(i)||!Number.isFinite(Date.parse(i)))throw new Error("timezone_required");return Date.parse(i)},h=d(a),u=new Map,t=new Set,o=new Set;for(const i of l){if(!i.entity||!i.period||!i.metric||!i.unit||!Number.isFinite(i.value))throw new Error("invalid_record");const c=d(i.publishedAt),m=d(i.firstSeenAt),n=JSON.stringify([i.entity,i.period,i.metric,i.unit]),f=JSON.stringify([n,i.version]);if(!i.version||t.has(f))throw new Error("duplicate_or_missing_version");t.add(f);const w=Math.max(c,m);if(w>h)continue;const v=JSON.stringify([n,c]);if(o.has(v))throw new Error("ambiguous_publication_order");o.add(v);const y=u.get(n);(!y||c>y.published)&&u.set(n,{published:c,row:{...i,availableAt:new Date(w).toISOString()}})}return[...u.values()].map(({row:i})=>i).sort((i,c)=>JSON.stringify([i.entity,i.period,i.metric,i.unit]).localeCompare(JSON.stringify([c.entity,c.period,c.metric,c.unit])))}function F(l,a){const d=t=>typeof t=="string"&&/T.*(Z|[+-]\d{2}:\d{2})$/.test(t)&&Number.isFinite(Date.parse(t));if(!a.length||a.some(t=>!d(t)))throw new Error("invalid_calendar");const h=[...new Set(a)].sort((t,o)=>Date.parse(t)-Date.parse(o)),u=new Map;return l.flatMap(t=>{if(!t.id||!t.version)throw new Error("missing_event_identity");const o=JSON.stringify([t.id,t.version]),i=JSON.stringify(t);if(u.has(o)){if(u.get(o)!==i)throw new Error("conflicting_event_version");return[]}if(u.set(o,i),!d(t.publishedAt)||!d(t.firstSeenAt))return[{...t,sessionOpen:null,status:"needs_review"}];const c=Math.max(Date.parse(t.publishedAt),Date.parse(t.firstSeenAt)),m=h.find(n=>Date.parse(n)>c)||null;return[{...t,availableAt:new Date(c).toISOString(),sessionOpen:m,status:m?"aligned":"outside_calendar"}]})}const J={"adjusted-price-series":{execute:k,args:[[{security:"DEMO",date:"2025-01-02",close:100,factor:1},{security:"DEMO",date:"2025-01-03",close:50,factor:2},{security:"DEMO",date:"2025-01-06",close:51,factor:2}],"2025-01-06"]},"pit-fundamentals-panel":{execute:C,args:[[{entity:"DEMO",period:"2024-12-31",metric:"revenue",unit:"CNY_million",value:100,version:"v1",publishedAt:"2025-03-20T18:00:00+08:00",firstSeenAt:"2025-03-20T18:05:00+08:00"},{entity:"DEMO",period:"2024-12-31",metric:"revenue",unit:"CNY_million",value:105,version:"v2",publishedAt:"2025-04-10T18:00:00+08:00",firstSeenAt:"2025-04-10T18:02:00+08:00"}],"2025-03-31T23:59:59+08:00"]},"company-event-timeline":{execute:F,args:[[{id:"DEMO-A",version:"v1",publishedAt:"2025-01-03T18:00:00+08:00",firstSeenAt:"2025-01-03T18:02:00+08:00"},{id:"DEMO-A",version:"v1",publishedAt:"2025-01-03T18:00:00+08:00",firstSeenAt:"2025-01-03T18:02:00+08:00"},{id:"DEMO-B",version:"v1",publishedAt:"2025-01-06",firstSeenAt:"2025-01-06T10:00:00+08:00"}],["2025-01-03T09:30:00+08:00","2025-01-06T09:30:00+08:00","2025-01-07T09:30:00+08:00"]]}},P={"adjusted-price-series":`// Synthetic teaching data. No network requests.
function adjustPrices(rows2, anchorDate) {
  if (!rows2.length) throw new Error("empty_input");
  const seen = /* @__PURE__ */ new Set();
  const security = rows2[0].security;
  for (const row of rows2) {
    if (row.security !== security || !row.security) throw new Error("one_security_required");
    const time = Date.parse(\`\${row.date}T00:00:00Z\`);
    if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(row.date) || !Number.isFinite(time) || new Date(time).toISOString().slice(0, 10) !== row.date || seen.has(row.date)) throw new Error("invalid_or_duplicate_date");
    if (!Number.isFinite(row.close) || row.close <= 0 || !Number.isFinite(row.factor) || row.factor <= 0) throw new Error("invalid_price_or_factor");
    seen.add(row.date);
  }
  const anchor = rows2.find((row) => row.date === anchorDate);
  if (!anchor) throw new Error("missing_anchor");
  return [...rows2].sort((a, b) => a.date.localeCompare(b.date)).map((row) => ({ ...row, anchorDate, adjustedClose: Number((row.close * row.factor / anchor.factor).toFixed(6)) }));
}

const inputs = [
  [
    {
      "security": "DEMO",
      "date": "2025-01-02",
      "close": 100,
      "factor": 1
    },
    {
      "security": "DEMO",
      "date": "2025-01-03",
      "close": 50,
      "factor": 2
    },
    {
      "security": "DEMO",
      "date": "2025-01-06",
      "close": 51,
      "factor": 2
    }
  ],
  "2025-01-06"
];
console.log(adjustPrices(...inputs));`,"pit-fundamentals-panel":`// Synthetic teaching data. No network requests.
function selectAsOf(rows2, cutoff) {
  const parse = (value) => {
    if (typeof value !== "string" || !/T.*(Z|[+-]\\d{2}:\\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error("timezone_required");
    return Date.parse(value);
  };
  const boundary = parse(cutoff);
  const eligible = /* @__PURE__ */ new Map();
  const identities = /* @__PURE__ */ new Set();
  const publicationOrders = /* @__PURE__ */ new Set();
  for (const row of rows2) {
    if (!row.entity || !row.period || !row.metric || !row.unit || !Number.isFinite(row.value)) throw new Error("invalid_record");
    const published = parse(row.publishedAt), observed = parse(row.firstSeenAt);
    const key = JSON.stringify([row.entity, row.period, row.metric, row.unit]);
    const identity = JSON.stringify([key, row.version]);
    if (!row.version || identities.has(identity)) throw new Error("duplicate_or_missing_version");
    identities.add(identity);
    const available = Math.max(published, observed);
    if (available > boundary) continue;
    const publicationOrder = JSON.stringify([key, published]);
    if (publicationOrders.has(publicationOrder)) throw new Error("ambiguous_publication_order");
    publicationOrders.add(publicationOrder);
    const previous = eligible.get(key);
    if (!previous || published > previous.published) eligible.set(key, { published, row: { ...row, availableAt: new Date(available).toISOString() } });
  }
  return [...eligible.values()].map(({ row }) => row).sort((a, b) => JSON.stringify([a.entity, a.period, a.metric, a.unit]).localeCompare(JSON.stringify([b.entity, b.period, b.metric, b.unit])));
}

const inputs = [
  [
    {
      "entity": "DEMO",
      "period": "2024-12-31",
      "metric": "revenue",
      "unit": "CNY_million",
      "value": 100,
      "version": "v1",
      "publishedAt": "2025-03-20T18:00:00+08:00",
      "firstSeenAt": "2025-03-20T18:05:00+08:00"
    },
    {
      "entity": "DEMO",
      "period": "2024-12-31",
      "metric": "revenue",
      "unit": "CNY_million",
      "value": 105,
      "version": "v2",
      "publishedAt": "2025-04-10T18:00:00+08:00",
      "firstSeenAt": "2025-04-10T18:02:00+08:00"
    }
  ],
  "2025-03-31T23:59:59+08:00"
];
console.log(selectAsOf(...inputs));`,"company-event-timeline":`// Synthetic teaching data. No network requests.
function alignEvents(events, sessionOpens) {
  const validTime = (value) => typeof value === "string" && /T.*(Z|[+-]\\d{2}:\\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
  if (!sessionOpens.length || sessionOpens.some((value) => !validTime(value))) throw new Error("invalid_calendar");
  const sessions = [...new Set(sessionOpens)].sort((a, b) => Date.parse(a) - Date.parse(b));
  const seen = /* @__PURE__ */ new Map();
  return events.flatMap((event) => {
    if (!event.id || !event.version) throw new Error("missing_event_identity");
    const key = JSON.stringify([event.id, event.version]);
    const fingerprint = JSON.stringify(event);
    if (seen.has(key)) {
      if (seen.get(key) !== fingerprint) throw new Error("conflicting_event_version");
      return [];
    }
    seen.set(key, fingerprint);
    if (!validTime(event.publishedAt) || !validTime(event.firstSeenAt)) return [{ ...event, sessionOpen: null, status: "needs_review" }];
    const available = Math.max(Date.parse(event.publishedAt), Date.parse(event.firstSeenAt));
    const sessionOpen = sessions.find((value) => Date.parse(value) > available) || null;
    return [{ ...event, availableAt: new Date(available).toISOString(), sessionOpen, status: sessionOpen ? "aligned" : "outside_calendar" }];
  });
}

const inputs = [
  [
    {
      "id": "DEMO-A",
      "version": "v1",
      "publishedAt": "2025-01-03T18:00:00+08:00",
      "firstSeenAt": "2025-01-03T18:02:00+08:00"
    },
    {
      "id": "DEMO-A",
      "version": "v1",
      "publishedAt": "2025-01-03T18:00:00+08:00",
      "firstSeenAt": "2025-01-03T18:02:00+08:00"
    },
    {
      "id": "DEMO-B",
      "version": "v1",
      "publishedAt": "2025-01-06",
      "firstSeenAt": "2025-01-06T10:00:00+08:00"
    }
  ],
  [
    "2025-01-03T09:30:00+08:00",
    "2025-01-06T09:30:00+08:00",
    "2025-01-07T09:30:00+08:00"
  ]
];
console.log(alignEvents(...inputs));`},R=l=>P[l];function $({id:l,locale:a,onNavigate:d,saved:h,onToggleBookmark:u}){const t=_[l],[o,i]=s.useState(null),[c,m]=s.useState(""),n=a==="zh";if(!t)return e.jsxs("section",{className:"object-detail-page",children:[e.jsx("h1",{children:n?"教程未找到":"Tutorial not found"}),e.jsx("a",{href:"/research",onClick:r=>d(r,"/research"),children:n?"返回研究":"Back to Research"})]});const f=R(l);async function w(){m(await T(f))}function v(){try{const r=J[l];i({value:r.execute(...r.args)})}catch{i({error:!0})}}const y=t.research.map(r=>E.find(p=>p.title===r));return e.jsxs("article",{className:"object-detail-page research-record tutorial-page",children:[e.jsxs("a",{className:"object-back",href:"/research",onClick:r=>d(r,"/research"),children:["← ",n?"返回研究":"Back to Research"]}),e.jsxs("header",{className:"research-reader-header",children:[e.jsxs("div",{className:"research-reader-meta",children:[e.jsx("span",{children:n?"数据准备教程":"Data preparation tutorial"}),e.jsx("span",{children:"v1 · 2026-08-30"})]}),e.jsx("h1",{children:t.title[a]}),e.jsx("p",{className:"research-reader-intro",children:t.summary[a]}),e.jsxs("div",{className:"research-reader-actions",children:[e.jsxs("a",{className:"primary-button",href:"#tutorial-example",children:[n?"试运行示例":"Try the example",e.jsx(x,{})]}),e.jsxs("button",{className:"secondary-button",type:"button","aria-pressed":h,onClick:u,children:[e.jsx(S,{weight:h?"fill":"regular"}),h?n?"已收藏":"Saved":n?"收藏":"Bookmark"]})]}),e.jsx("p",{className:"research-reader-action-note",children:n?"示例在浏览器内运行，使用虚构数据，不连接账户或外部服务。收藏仅保存在当前浏览器。":"Examples run locally with synthetic data, without account or external-service access. Bookmarks stay in this browser."})]}),e.jsxs("div",{className:"research-reader-layout",children:[e.jsxs("div",{className:"research-reader-body",children:[e.jsxs("section",{id:"tutorial-goal",children:[e.jsx("h2",{children:n?"完成后得到什么":"What you will produce"}),e.jsx("p",{children:t.goal[a]})]}),e.jsxs("section",{id:"tutorial-inputs",children:[e.jsx("h2",{children:n?"准备输入":"Prepare the inputs"}),e.jsx("ul",{children:t.fields.map(r=>e.jsx("li",{children:r[a]},r.en))}),e.jsx("p",{children:n?"下面是本地教学字段，不是直接可提交的API字段。真实数据需要按已授权目录映射并保留原始字段。":"These are local teaching fields, not request-ready API fields. Map authorized source fields explicitly and retain the originals."})]}),t.steps.map((r,p)=>e.jsxs("section",{id:`tutorial-step-${p+1}`,children:[e.jsx("h2",{children:r.title[a]}),e.jsx("p",{children:r.body[a]})]},r.title.en)),e.jsxs("section",{id:"tutorial-example",children:[e.jsx("h2",{children:n?"用虚构小样本验证":"Verify with a synthetic sample"}),e.jsx("p",{children:t.expected[a]}),e.jsxs("details",{children:[e.jsx("summary",{children:n?"查看输入与完整JavaScript示例":"View inputs and complete JavaScript example"}),e.jsx("pre",{tabIndex:0,"aria-label":n?"JavaScript示例":"JavaScript example",children:e.jsx("code",{children:f})})]}),e.jsxs("div",{className:"research-reader-actions",children:[e.jsxs("button",{type:"button",className:"primary-button",onClick:v,children:[e.jsx(M,{}),n?"运行虚构示例":"Run synthetic example"]}),e.jsxs("button",{type:"button",className:"secondary-button",onClick:w,children:[e.jsx(O,{}),n?"复制示例代码":"Copy example code"]})]}),e.jsx("p",{role:"status",children:c==="copied"?n?"代码已复制":"Code copied":c==="failed"?n?"无法自动复制，请选中下方代码手动复制。":"Automatic copy failed. Select the code below to copy manually.":""}),c==="failed"&&e.jsx("textarea",{className:"research-citation-fallback","aria-label":n?"可复制代码":"Selectable code",readOnly:!0,value:f,onFocus:r=>r.target.select()}),o&&e.jsxs("div",{className:"tutorial-output",children:[e.jsx("p",{role:"status",children:o.error?n?"示例未完成，请重新加载后重试。":"Example failed. Reload and retry.":n?"示例完成；下方仅为虚构数据的处理结果。":"Example complete. Output below is synthetic."}),!o.error&&e.jsx("pre",{tabIndex:0,"aria-label":n?"虚构示例结果":"Synthetic example output",children:e.jsx("code",{children:JSON.stringify(o.value,null,2)})})]})]}),e.jsxs("section",{id:"tutorial-pitfalls",children:[e.jsx("h2",{children:n?"常见错误与验证":"Pitfalls and validation"}),e.jsx("ul",{children:t.pitfalls.map(r=>e.jsx("li",{children:r[a]},r.en))})]}),e.jsxs("section",{id:"tutorial-real-data",children:[e.jsx("h2",{children:n?"换成真实数据之前":"Before using real data"}),e.jsx("p",{children:n?"先通过已认证的 GET /v1/catalog 确认可访问的数据集、schema_major、允许字段与过滤条件。下列ID来自项目目录合同，不保证你的账户已获授权或包含完整历史。":"Use authenticated GET /v1/catalog to confirm datasets, schema_major, allowed fields and filters. These IDs come from the project contract, not proof of your entitlement or historical coverage."}),e.jsx("ul",{children:t.datasetIds.map(r=>e.jsx("li",{children:e.jsx("code",{children:r})},r))}),e.jsx("p",{children:n?"套餐要求：以账户对上述数据集的实际授权为准，不从套餐名称推断访问范围。财务版本、精确公告时点或额外原文授权可能仍需自行补充。":"Plan requirement: actual grants for these datasets, not a plan-name assumption. Historical filing versions, exact announcement times or additional document rights may still be needed."}),e.jsxs("details",{children:[e.jsx("summary",{children:n?"有界查询结构（仅供复制，不会发送）":"Bounded query shape (copy only; never sent)"}),e.jsx("pre",{tabIndex:0,children:e.jsx("code",{children:`// POST /v1/query
// catalogRow is the selected authenticated catalog entry.
const request = {
  dataset_id: catalogRow.dataset_id,
  schema_major: catalogRow.schema_major,
  fields: [],
  filters: {},
  as_of: null,
  limit: 3,
  cursor: null
};`})})]}),e.jsx("p",{children:n?"这只预览最多3行，不证明研究窗口完整。按目录允许的过滤条件限定实际窗口；保存每页游标和来源回执，并在取齐所需记录后离线完成连接。不要把API的as_of字段直接等同于历史披露版本。":"This previews at most three rows, not a complete research window. Restrict the actual window with permitted filters, retain cursors and provenance, and join the required records offline. API as_of is not automatically a historical filing-version contract."})]}),e.jsxs("section",{children:[e.jsx("h2",{children:n?"参考资料":"References"}),e.jsx("ul",{children:t.sources.map(r=>e.jsx("li",{children:e.jsxs("a",{href:r.url,target:"_blank",rel:"noreferrer",children:[r.label[a]," ",e.jsx(A,{})]})},r.url))})]})]}),e.jsxs("aside",{className:"research-reader-aside","aria-label":n?"教程导航":"Tutorial navigation",children:[e.jsxs("nav",{"aria-label":n?"本页目录":"On this page",children:[e.jsx("h2",{children:n?"本页内容":"On this page"}),[["tutorial-inputs","准备输入","Inputs"],["tutorial-step-1","操作步骤","Steps"],["tutorial-example","运行示例","Example"],["tutorial-pitfalls","常见错误","Pitfalls"],["tutorial-real-data","真实数据","Real data"]].map(([r,p,g])=>e.jsx("a",{href:`#${r}`,children:n?p:g},r))]}),e.jsxs("section",{children:[e.jsx("h2",{children:n?"相关研究":"Related research"}),e.jsx("div",{className:"research-next-list",children:y.filter(Boolean).map(r=>e.jsxs("a",{href:`/research/${r.id}`,onClick:p=>d(p,`/research/${r.id}`),children:[N(r,a),e.jsx(x,{})]},r.id))})]})]})]})]})}export{$ as default};
