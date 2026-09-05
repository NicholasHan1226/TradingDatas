// Navigation bindings only: raw inputs never establish a completed PIT product.
export const productBindings = {
  "cn-valuation-indicators": ["cn.dataset.daily_basic", "cn.dataset.fina_indicator", "cn.dataset.fina_mainbz"],
  "cn-company-actions": ["cn.dataset.dividend", "cn.dataset.repurchase", "cn.dataset.share_float", "cn.dataset.suspend_d"],
  "cn-announcements": ["cn.dataset.anns_d", "cn.dataset.disclosure_date"],
  "cn-ipo-calendar": ["cn.dataset.new_share"],
  "cn-index-constituents": ["cn.dataset.index_basic", "cn.dataset.index_weight", "cn.dataset.index_member_all"],
  "cn-etf-nav-iopv": ["cn.dataset.etf_basic", "cn.dataset.etf_share_size"],
  "cn-convertible-bonds": ["cn.dataset.cb_basic", "cn.dataset.cb_daily", "cn.dataset.cb_issue", "cn.dataset.cb_rating"],
  "cn-macro-calendar": ["cn.dataset.cn_cpi", "cn.dataset.cn_ppi", "cn.dataset.cn_pmi", "cn.dataset.cn_m", "cn.dataset.sf_month"],
  "cn-yield-curve": ["cn.dataset.shibor", "cn.dataset.shibor_quote"],
  "cn-futures-commodities": ["cn.dataset.fut_basic", "cn.dataset.fut_daily", "cn.dataset.fut_settle", "cn.dataset.fut_holding"],

  'cn-equity-daily': ['cn.equity.daily', 'cn.dataset.adj_factor', 'cn.market.trade_calendar'],
  'cn-equity-minute': ['cn.dataset.stk_mins'],
  'cn-auction-premarket': ['cn.dataset.stk_auction', 'cn.dataset.stk_premarket'],
  'cn-market-reference': ['cn.market.trade_calendar', 'cn.equity.security_master', 'cn.dataset.adj_factor', 'cn.dataset.suspend_d'],
  'cn-pit-fundamentals': ['cn.dataset.income', 'cn.dataset.balancesheet', 'cn.dataset.cashflow', 'cn.dataset.fina_indicator'],
  'cn-company-master': ['cn.equity.security_master', 'cn.dataset.stock_company', 'cn.dataset.namechange'],
  'cn-news-flashes': ['cn.dataset.news', 'cn.dataset.major_news', 'cn.dataset.cctv_news', 'cn.news.flash', 'global.news.flash'],
  'cn-broker-research': ['cn.dataset.research_report', 'cn.dataset.broker_recommend'],
  'cn-secretary-qa': ['cn.dataset.irm_qa_sh', 'cn.dataset.irm_qa_sz'],
  'cn-fund-portfolio': ['cn.dataset.fund_portfolio'],
  'cn-ownership-holdings': ['cn.dataset.top10_holders', 'cn.dataset.top10_floatholders', 'cn.dataset.pledge_detail', 'cn.dataset.fund_portfolio'],
};
export const runtimeStates = ['success', 'empty', 'stale', 'paused', 'failed', 'unobserved'];
export function domesticRows(payload) {
  if (!payload || !Array.isArray(payload.data) || payload.next_cursor != null) throw new Error('invalid_catalog');
  return payload.data.filter(row => typeof row?.dataset_id === 'string'
    && /^(cn\.|global\.news\.)/.test(row.dataset_id) && !String(row.market || '').toUpperCase().startsWith('CRYPTO'));
}
export function selectCatalogRows(rows, { productId, query = '', state = 'all' } = {}) {
  const binding = productId ? productBindings[productId] || [] : null;
  const needle = query.trim().toLowerCase();
  return rows.filter(row => (!binding || binding.includes(row.dataset_id))
    && (state === 'all' || (row.runtime?.state || 'unobserved') === state)
    && (!needle || [row.dataset_id, ...(row.aliases || []), row.market, row.cadence].join(' ').toLowerCase().includes(needle)));
}
export function catalogQuery(row) {
  if (typeof row?.dataset_id !== 'string' || !Number.isInteger(row.schema_major) || row.schema_major < 1) return null;
  return { dataset_id: row.dataset_id, schema_major: row.schema_major, fields: [], filters: {}, as_of: null, cursor: null, limit: 1, include_receipt_proofs: false };
}
export function catalogOwner(account) { return account?.user_id || account?.tenant_id || ''; }
export function catalogView({ account, checking, error, active, snapshot }) {
  if (!active) return 'inactive';
  if (checking) return 'loading';
  if (!account) return error && !['signed_out', 'invalid_token'].includes(error) ? 'error' : 'guest';
  if (account.identity_kind === 'email' && account.data_access_state !== 'connected') return 'unconnected';
  if (!catalogOwner(account)) return 'unconnected';
  // Comparing the account reference also hides an older session for the same tenant.
  if (snapshot?.account !== account) return 'loading';
  return snapshot.status;
}
