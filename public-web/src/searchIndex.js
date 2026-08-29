const synonymSets = [
  ["数据", "数据产品", "shuju", "shujuchanpin", "data", "dataset"],
  ["研究", "论文", "文献", "yanjiu", "lunwen", "wenxian", "research", "paper", "literature"],
  ["方法", "组合", "准备", "对齐", "fangfa", "zuhe", "zhunbei", "duiqi", "method", "recipe", "cookbook"],
  ["文档", "说明", "接口", "wendang", "shuoming", "jiekou", "docs", "documentation", "api"],
  ["a股", "a股市场", "股票", "agu", "agushichang", "gupiao", "a share", "a-share", "ashare", "cn equity"],
  ["行情", "价格", "报价", "hangqing", "jiage", "baojia", "market data", "quote", "price"],
  ["日线", "日频", "rixian", "ripin", "daily", "daily bars"],
  ["分钟", "分时", "fenzhong", "fenshi", "minute", "intraday"],
  ["实时", "快照", "shishi", "kuaizhao", "real time", "realtime", "snapshot"],
  ["财务", "基本面", "caiwu", "jibenmian", "financials", "fundamentals"],
  ["公司", "企业", "gongsi", "qiye", "company", "corporate"],
  ["公告", "事件", "gonggao", "shijian", "announcement", "event"],
  ["指数", "基金", "zhishu", "jijin", "index", "fund", "etf"],
  ["宏观", "利率", "hongguan", "lilv", "macro", "rate"],
  ["新闻", "文本", "xinwen", "wenben", "news", "text"],
  ["另类", "另类数据", "linglei", "lingleishuju", "alternative", "alternative data"],
  ["披萨", "披萨指数", "pisa", "pisa zhishu", "pizza", "pizza index"],
  ["全球", "海外", "quanqiu", "haiwai", "global", "international"],
  ["港股", "香港", "ganggu", "xianggang", "hong kong", "hk equity"],
  ["美股", "美国", "meigu", "meiguo", "us equity", "united states"],
  ["加密", "数字资产", "jiami", "shuzizichan", "crypto", "digital assets"],
  ["套餐", "订阅", "价格", "taocan", "dingyue", "jiage", "pricing", "plan", "subscription"],
  ["代理", "智能体", "daili", "zhinengti", "agent", "mcp", "claude", "codex", "openclaw", "hermes"],
];

const groupIntentAliases = {
  data: ["数据", "数据产品", "shuju", "shujuchanpin", "data", "dataset"],
  research: ["研究", "论文", "文献", "yanjiu", "lunwen", "wenxian", "research", "paper", "literature"],
  methods: ["方法", "组合", "准备", "fangfa", "zuhe", "zhunbei", "method", "recipe", "cookbook"],
  docs: ["文档", "说明", "接口", "wendang", "shuoming", "jiekou", "docs", "documentation", "api"],
};

export function normalizeSearchValue(value) {
  return String(value || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[·•—–_/]+/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim()
    .replace(/\s+/g, " ");
}

export function isGlobalSearchShortcut(event) {
  const key = String(event.key || "").toLowerCase();
  return Boolean(event.metaKey || event.ctrlKey) && (key === "k" || event.code === "KeyK");
}

export function getSearchNavigationIndex(currentIndex, resultCount, key) {
  if (!resultCount) return -1;
  if (key === "Home") return 0;
  if (key === "End") return resultCount - 1;
  if (key === "ArrowDown") return currentIndex >= resultCount - 1 ? 0 : currentIndex + 1;
  if (key === "ArrowUp") return currentIndex <= 0 ? resultCount - 1 : currentIndex - 1;
  return currentIndex;
}

export function createSearchDocument(values) {
  const base = normalizeSearchValue(values.flat(Infinity).filter(Boolean).join(" "));
  const compactBase = base.replace(/\s+/g, "");
  const aliases = synonymSets
    .filter((set) => set.some((term) => {
      const normalizedTerm = normalizeSearchValue(term);
      return base.includes(normalizedTerm) || compactBase.includes(normalizedTerm.replace(/\s+/g, ""));
    }))
    .flat();
  return normalizeSearchValue([base, ...aliases].join(" "));
}

function containsQuery(value, query) {
  const compactValue = value.replace(/\s+/g, "");
  const compactQuery = query.replace(/\s+/g, "");
  return value.includes(query) || compactValue.includes(compactQuery);
}

function isOneEditApart(left, right) {
  if (left === right) return true;
  if (Math.abs(left.length - right.length) > 1) return false;

  if (left.length === right.length) {
    const differences = [];
    for (let index = 0; index < left.length; index += 1) {
      if (left[index] !== right[index]) differences.push(index);
      if (differences.length > 2) return false;
    }
    if (differences.length === 1) return true;
    return differences.length === 2
      && differences[1] === differences[0] + 1
      && left[differences[0]] === right[differences[1]]
      && left[differences[1]] === right[differences[0]];
  }

  const [shorter, longer] = left.length < right.length ? [left, right] : [right, left];
  let shortIndex = 0;
  let longIndex = 0;
  let skipped = false;
  while (shortIndex < shorter.length && longIndex < longer.length) {
    if (shorter[shortIndex] === longer[longIndex]) {
      shortIndex += 1;
      longIndex += 1;
    } else if (skipped) {
      return false;
    } else {
      skipped = true;
      longIndex += 1;
    }
  }
  return true;
}

function fuzzyTokenMatch(document, token) {
  if (!/^[a-z][a-z0-9]*$/.test(token) || token.length < 4) return false;
  return document.split(" ").some((candidate) => candidate.length >= 4 && isOneEditApart(candidate, token));
}

function tokenMatchesDocument(document, token) {
  return containsQuery(document, token) || fuzzyTokenMatch(document, token);
}

export function rankSearchItem(item, rawQuery) {
  const query = normalizeSearchValue(rawQuery);
  if (!query) return -1;

  const label = normalizeSearchValue(item.label);
  const id = normalizeSearchValue(item.id || item.key);
  const type = normalizeSearchValue(item.type);
  const description = normalizeSearchValue(item.description);
  const document = item.searchDocument || createSearchDocument([label, id, type, description, item.aliases]);
  const queryTokens = query.split(" ").filter(Boolean);

  if (!queryTokens.every((token) => tokenMatchesDocument(document, token))) return -1;

  let score = 0;
  if (label === query) score += 140;
  else if (label.startsWith(query)) score += 110;
  else if (containsQuery(label, query)) score += 90;

  if (id === query) score += 130;
  else if (id.startsWith(query)) score += 95;
  else if (containsQuery(id, query)) score += 75;

  if (type === query) score += 70;
  else if (containsQuery(type, query)) score += 45;
  if (containsQuery(description, query)) score += 35;
  score += queryTokens.filter((token) => containsQuery(document, token)).length * 12;
  score += queryTokens.filter((token) => !containsQuery(document, token) && fuzzyTokenMatch(document, token)).length * 5;

  return score || 12;
}

export function getSearchMatchKind(item, rawQuery) {
  const query = normalizeSearchValue(rawQuery);
  if (!query) return null;
  const label = normalizeSearchValue(item.label);
  const id = normalizeSearchValue(item.id || item.key);
  const type = normalizeSearchValue(item.type);
  const description = normalizeSearchValue(item.description);
  const document = item.searchDocument || createSearchDocument([label, id, type, description, item.aliases]);
  const queryTokens = query.split(" ").filter(Boolean);

  if (containsQuery(label, query)) return null;
  if (containsQuery(id, query)) return "id";
  if (containsQuery(type, query) || containsQuery(description, query)) return null;
  if (queryTokens.some((token) => !containsQuery(document, token) && fuzzyTokenMatch(document, token))) return "fuzzy";
  return "alias";
}

export function searchGroups(items, rawQuery, groups, perGroupLimit = 4) {
  const query = normalizeSearchValue(rawQuery);
  if (!query) return [];

  const preferredGroups = Object.entries(groupIntentAliases)
    .filter(([, aliases]) => aliases.some((alias) => {
      const normalizedAlias = normalizeSearchValue(alias);
      return normalizedAlias === query || fuzzyTokenMatch(normalizedAlias, query);
    }))
    .map(([group]) => group);
  const orderedGroups = [...groups].sort((left, right) => {
    const leftPriority = preferredGroups.indexOf(left.key);
    const rightPriority = preferredGroups.indexOf(right.key);
    if (leftPriority >= 0 || rightPriority >= 0) {
      if (leftPriority < 0) return 1;
      if (rightPriority < 0) return -1;
      return leftPriority - rightPriority;
    }
    return 0;
  });

  return orderedGroups.map((group) => {
    const rankedItems = items
      .map((item, index) => ({ item, index }))
      .filter(({ item }) => item.group === group.key)
      .map(({ item, index }) => ({ item, index, score: rankSearchItem(item, query) }))
      .filter(({ score }) => score >= 0)
      .sort((left, right) => right.score - left.score || left.index - right.index);

    return {
      ...group,
      totalCount: rankedItems.length,
      items: rankedItems
        .slice(0, perGroupLimit)
        .map(({ item }) => ({ ...item, matchKind: getSearchMatchKind(item, query) })),
    };
  }).filter((group) => group.totalCount);
}
