import { createContext, useContext, useEffect, useState } from 'react';
import { accountJson } from './accountSession.js';
import { catalogOwner, catalogQuery, catalogView, domesticRows, productBindings, runtimeStates, selectCatalogRows } from './catalogEvidence.js';
import './catalogEvidence.css';

const CatalogContext = createContext({ status: 'guest', rows: [], retry: () => {} });
export function CatalogProvider({ account, checking, error, active, onRetryAccount, children }) {
  const [snapshot, setSnapshot] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    if (!active || checking || !catalogOwner(account) || (account.identity_kind === 'email' && account.data_access_state !== 'connected')) return () => controller.abort();
    setSnapshot({ account, status: 'loading', rows: [] });
    accountJson('catalog', { expectedIdentity: catalogOwner(account), signal: controller.signal }, fetch, 45000)
      .then(payload => { if (!controller.signal.aborted) setSnapshot({ account, status: 'ready', readAt: new Date().toISOString(), rows: domesticRows(payload) }); })
      .catch(error => { if (!controller.signal.aborted) setSnapshot({ account, status: 'error', recheck: ['signed_out', 'identity_changed', 'access_denied'].includes(error.message), rows: [] }); });
    return () => controller.abort();
  }, [account, checking, active, attempt]);
  const status = catalogView({ account, checking, error, active, snapshot });
  return <CatalogContext.Provider value={{ status, rows: status === 'ready' ? snapshot.rows : [], readAt: status === 'ready' ? snapshot.readAt : null, retry: () => !account || snapshot?.recheck ? onRetryAccount?.() : setAttempt(value => value + 1) }}>{children}</CatalogContext.Provider>;
}

const labels = {
  success: ['最近采集成功', 'Latest collection succeeded'], empty: ['最近响应为空', 'Latest response empty'],
  stale: ['更新延迟', 'Update delayed'], paused: ['采集暂停', 'Collection paused'],
  failed: ['最近采集失败', 'Latest collection failed'], unobserved: ['尚无采集凭证', 'No collection receipt'],
};
function stateLabel(state, zh) { return labels[state]?.[zh ? 0 : 1] || state || (zh ? '状态未知' : 'Unknown'); }
function CatalogRow({ row, zh }) {
  const [copied, setCopied] = useState('');
  const runtime = row.runtime || {};
  const query = catalogQuery(row);
  async function copy() {
    try { await navigator.clipboard.writeText(JSON.stringify(query, null, 2)); setCopied('yes'); }
    catch { setCopied('error'); }
  }
  return <article className="catalog-live-row">
    <div className="catalog-live-identity"><strong>{row.dataset_id}</strong><span>{stateLabel(runtime.state, zh)}{runtime.degraded === true ? (zh ? ' · 数据有降级标记' : ' · Degraded') : ''}</span></div>
    <dl className="catalog-live-facts">
      <div><dt>{zh ? '存量记录' : 'Stored rows'}</dt><dd>{Number.isInteger(row.coverage?.row_count) ? row.coverage.row_count.toLocaleString(zh ? 'zh-CN' : 'en') : '—'}</dd></div>
      <div><dt>{zh ? '数据时间' : 'Data through'}</dt><dd>{runtime.data_through || '—'}</dd></div>
      <div><dt>{zh ? '最近观测' : 'Last observed'}</dt><dd>{runtime.observed_at || '—'}</dd></div>
      <div><dt>{zh ? '目录查询权限' : 'Catalog query access'}</dt><dd>{row.queryability?.queryable === true ? (zh ? '允许查询' : 'Queryable') : row.queryability?.queryable === false ? (zh ? '当前不可查询' : 'Not queryable') : '—'}</dd></div>
    </dl>
    <details><summary>{zh ? '凭证与查询示例' : 'Receipt & query example'}</summary>
      <p>{zh ? '采集凭证' : 'Receipt'}: <code>{runtime.receipt_id || '—'}</code></p>
      <p>{zh ? '采集原因' : 'Collection reasons'}: <code>{runtime.reasons?.join(', ') || '—'}</code></p>
      <p>{zh ? '查询限制原因' : 'Query restrictions'}: <code>{row.queryability?.reasons?.join(', ') || '—'}</code></p>
      <p>{zh ? '存储覆盖' : 'Stored coverage'}: {row.coverage?.earliest_observed_at || '—'} → {row.coverage?.latest_observed_at || '—'}</p>
      {query ? <><pre>{JSON.stringify(query, null, 2)}</pre><button type="button" className="account-inline-action" onClick={copy}>{zh ? '复制查询体' : 'Copy query body'}</button><span role="status">{copied === 'yes' ? (zh ? '已复制' : 'Copied') : copied === 'error' ? (zh ? '复制失败，可选中上方内容复制' : 'Copy failed; select the example to copy') : ''}</span></> : <p>{zh ? '目录缺少有效 schema 版本，暂不生成查询示例。' : 'No query example is generated without a valid catalog schema version.'}</p>}
      <p className="catalog-live-note">{zh ? '此示例用于 POST /v1/query，不会自动发送。目录权限与存量记录不保证此次查询非空，也不代表完整历史或连续稳定。' : 'Use this body with POST /v1/query; it is not sent automatically. Query access and stored rows do not guarantee a non-empty response, complete history or continuous stability.'}</p>
    </details>
  </article>;
}
export function CatalogEvidence({ locale, productId, query = '' }) {
  const zh = locale !== 'en';
  const { status, rows, retry, readAt } = useContext(CatalogContext);
  const [state, setState] = useState('all');
  const [limit, setLimit] = useState(20);
  useEffect(() => { setLimit(20); }, [productId, query, state, rows]);
  const filtered = selectCatalogRows(rows, { productId, query, state });
  if (status === 'inactive') return null;
  return <section className="catalog-live" aria-label={zh ? '授权目录与采集状态' : 'Authorized catalog and collection status'}>
    <header><span className="mono-kicker">{zh ? '采集状态' : 'COLLECTION STATUS'}</span><h2>{productId ? (zh ? '关联原始数据接口' : 'Related raw-data interfaces') : (zh ? '账户可见的数据接口' : 'Interfaces visible to your account')}</h2>
      <p>{zh ? '逐项展示当前授权目录的采集凭证。空响应、延迟和失败分别说明，已有数据按接口合同提供。' : 'Collection receipts from your current authorized catalog, with empty responses, delays and failures shown separately. Existing data remains available according to each interface contract.'}</p>
      {productId && <p className="catalog-live-note">{zh ? '关联仅帮助定位原始输入，不代表该产品的时点对齐、复权或加工层已完成。' : 'These links identify raw inputs; they do not establish completed point-in-time alignment, adjustments or a processed product.'}</p>}
    </header>
    {status === 'guest' && <p>{zh ? '产品介绍可直接浏览。登录并连接已有数据权限后，可查看你的授权接口与采集状态。' : 'Browse product descriptions freely. Sign in and connect existing data access to view your authorized interfaces and collection status.'} <a href="/account">{zh ? '登录' : 'Sign in'}</a></p>}
    {status === 'unconnected' && <p>{zh ? '账户尚未连接有效的数据权限；邮箱登录本身不授予数据访问。' : 'This account has no active data connection; email sign-in alone does not grant data access.'} <a href="/account/subscription">{zh ? '管理数据连接' : 'Manage data connection'}</a></p>}
    {status === 'loading' && <p role="status">{zh ? '正在读取授权目录…' : 'Reading authorized catalog…'}</p>}
    {status === 'error' && <p role="status">{zh ? '暂时无法读取目录，不能据此判断数据未采集。' : 'The catalog is temporarily unavailable; this does not mean data has not been collected.'} <button className="account-inline-action" type="button" onClick={retry}>{zh ? '重试' : 'Retry'}</button></p>}
    {status === 'ready' && <>
      <p className="catalog-live-note">{zh ? `状态读取于 ${readAt}；不包含内部 Crypto 数据。` : `Status read at ${readAt}; internal Crypto data is excluded.`}</p>
      <div className="catalog-live-controls"><label>{zh ? '最近采集状态' : 'Latest collection state'} <select value={state} onChange={event => setState(event.target.value)}><option value="all">{zh ? '全部状态' : 'All states'}</option>{runtimeStates.map(value => <option value={value} key={value}>{stateLabel(value, zh)}</option>)}</select></label><span role="status">{zh ? `${filtered.length} 个接口` : `${filtered.length} interfaces`}</span><button className="account-inline-action" type="button" onClick={retry}>{zh ? '刷新' : 'Refresh'}</button></div>
      {!filtered.length && <p>{productId && !productBindings[productId] ? (zh ? '该产品尚无明确的原始接口映射。完整授权目录可在 Data 页查看。' : 'This product has no explicit raw-interface mapping yet. See the full authorized catalog on Data.') : (zh ? '当前账户目录中没有符合此范围的接口；这不代表平台没有采集数据。' : 'No interfaces in this account’s catalog match this selection; this does not imply that the platform has collected no data.')}</p>}
      {filtered.slice(0, limit).map(row => <CatalogRow key={row.dataset_id} row={row} zh={zh} />)}
      {filtered.length > limit && <button className="account-inline-action" type="button" onClick={() => setLimit(value => value + 20)}>{zh ? '继续显示 20 个' : 'Show 20 more'}</button>}
    </>}
  </section>;
}
