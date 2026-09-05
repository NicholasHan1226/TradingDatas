import { useEffect, useRef, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";
import { readCommerce, createSandboxOrder } from "./accountCommerce.js";
import "./accountCommerce.css";

export function AccountCommerce({ account, locale, section, navigate }) {
  const zh = locale === "zh";
  const identity = account.identity_kind === "email" ? account.user_id : null;
  const [revision, setRevision] = useState(0);
  const [view, setView] = useState({ loading: true, data: null, error: false });
  const [selected, setSelected] = useState("");
  const [pending, setPending] = useState(false);
  const [created, setCreated] = useState(null);
  const [orderError, setOrderError] = useState(false);
  const attempt = useRef(null);
  const submitting = useRef(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (!identity) return undefined;
    const controller = new AbortController();
    setView({ loading: true, data: null, error: false });
    readCommerce(identity, controller.signal).then(data => {
      if (!controller.signal.aborted) setView({ loading: false, data, error: false });
    }).catch(() => {
      if (!controller.signal.aborted) setView({ loading: false, data: null, error: true });
    });
    return () => controller.abort();
  }, [identity, revision]);
  const retry = () => setRevision(value => value + 1);
  const plan = tier => ({ basic: zh ? "基础版" : "Basic", standard: zh ? "专业版" : "Professional", flagship: zh ? "旗舰版" : "Flagship" })[tier];
  const term = period => period === "annual" ? (zh ? "年期" : "Annual term") : (zh ? "月期" : "Monthly term");
  const date = value => new Date(value).toLocaleString(zh ? "zh-CN" : "en-US");
  const money = order => new Intl.NumberFormat(zh ? "zh-CN" : "en-US", { style: "currency", currency: order.currency }).format(order.amount_minor / 100);
  const access = state => ({ not_provisioned: zh ? "未开通" : "Not activated", pending: zh ? "开通处理中" : "Activation pending", active: zh ? "测试开通完成" : "Test activation complete", failed: zh ? "开通未完成" : "Activation incomplete" })[state];
  const data = view.data;
  const offer = data?.offers.find(item => item.id === selected) || data?.offers[0];
  async function createOrder() {
    if (submitting.current || !identity || !offer || data?.mode !== "sandbox" || !data.checkout_available) return;
    submitting.current = true; setPending(true); setOrderError(false);
    if (!attempt.current || attempt.current.offer !== offer.id || attempt.current.version !== offer.version) {
      attempt.current = { offer: offer.id, version: offer.version, key: crypto.randomUUID() };
    }
    try {
      const order = await createSandboxOrder(identity, offer, attempt.current.key);
      if (alive.current) { setCreated(order); retry(); }
    } catch { if (alive.current) setOrderError(true); }
    finally { submitting.current = false; if (alive.current) setPending(false); }
  }
  return <section className="account-commerce" aria-label={zh ? "订阅与订单记录" : "Subscription and order records"}>
    <header><div><span className="mono-kicker">{section === "billing" ? "ORDERS & BILLING" : "SUBSCRIPTION"}</span><h3>{section === "billing" ? (zh ? "订单与账单" : "Orders & billing") : (zh ? "订阅记录" : "Subscription record")}</h3></div>{identity && <button type="button" className="account-inline-action" onClick={retry} disabled={view.loading || pending}>{zh ? "刷新记录" : "Refresh records"}</button>}</header>
    {!identity ? <p>{zh ? "当前通过数据密钥登录，尚未关联可读取订阅记录的邮箱身份。数据权限仍按下方账户信息显示；通过邮箱登录后可读取该身份的订阅与订单。" : "This data-key session is not linked to a billing identity. Your effective data access remains shown separately. Sign in by email to read that identity’s subscription and orders."}</p>
      : view.loading ? <p role="status">{zh ? "正在读取订阅记录…" : "Loading subscription records…"}</p>
      : view.error ? <div role="status"><p>{zh ? "暂时无法读取订阅与订单，请刷新重试。此故障不代表订阅取消，也不会改变已有数据权限。" : "Subscription and order records could not be loaded. Refresh to retry. This does not mean cancellation or change existing data access."}</p></div>
      : data.mode === "unavailable" ? <p>{zh ? "订阅账本暂未接通，当前无法确认购买与续费记录。在线支付仍未开放；已有数据访问与有效期以账户的实际权限为准。" : "The subscription ledger is not connected, so purchase and renewal records cannot be confirmed here. Online payment remains unavailable; your existing data access and expiry are shown separately."}</p>
      : <>
        <p className="commerce-sandbox-note" role="status">{zh ? "测试环境 · 不收款，不开通正式数据权限。月期按 30 天、年期按 365 天测试；这些不是正式购买条款。" : "Sandbox · no payment is collected and no production data access is granted. Test terms use 30 days monthly and 365 days annually; these are not live purchase terms."}</p>
        {data.subscription ? <dl className="commerce-facts"><div><dt>{zh ? "测试套餐" : "Test plan"}</dt><dd>{plan(data.subscription.tier)} · {term(data.subscription.period)}</dd></div><div><dt>{zh ? "订阅状态" : "Subscription state"}</dt><dd>{data.subscription.state === "active" ? (zh ? "测试有效" : "Test active") : (zh ? "已到期" : "Expired")}</dd></div><div><dt>{zh ? "开始时间" : "Starts"}</dt><dd>{date(data.subscription.starts_at)}</dd></div><div><dt>{zh ? "到期时间" : "Expires"}</dt><dd>{date(data.subscription.expires_at)}</dd></div></dl> : <p>{zh ? "该测试账户暂无订阅记录。" : "This test account has no subscription record."}</p>}
        {section === "billing" && <div className="commerce-orders"><h4>{zh ? "最近 20 笔测试订单" : "Latest 20 test orders"}</h4>{data.orders.length ? data.orders.map(order => <article key={order.id}><header><strong>{plan(order.tier)} · {term(order.period)}</strong><span>{money(order)}</span></header><p className="commerce-order-id">{order.id}</p><dl><div><dt>{zh ? "创建时间" : "Created"}</dt><dd>{date(order.created_at)}</dd></div><div><dt>{zh ? "支付状态" : "Payment"}</dt><dd>{order.payment_state === "verified_paid" ? (zh ? "测试支付已确认" : "Test payment confirmed") : (zh ? "待测试支付" : "Awaiting test payment")}</dd></div><div><dt>{zh ? "开通状态" : "Activation"}</dt><dd>{access(order.provisioning_state)}</dd></div></dl></article>) : <p>{zh ? "该测试账户暂无订单。" : "This test account has no orders."}</p>}</div>}
        {data.checkout_available && offer && <div className="commerce-create"><h4>{zh ? "创建测试订单" : "Create a test order"}</h4><label htmlFor={`commerce-offer-${section}`}>{zh ? "测试套餐与周期" : "Test plan and term"}</label><select id={`commerce-offer-${section}`} value={offer.id} disabled={pending} onChange={event => { setSelected(event.target.value); setCreated(null); setOrderError(false); attempt.current = null; }}>{data.offers.map(item => <option value={item.id} key={item.id}>{plan(item.tier)} · {term(item.period)} · {money(item)}</option>)}</select><p>{zh ? `${offer.requests_per_minute} 次 / 分钟 · 仅保存测试订单，不扣费、不自动续费。` : `${offer.requests_per_minute} requests / minute · saves a test order only, with no charge or automatic renewal.`}</p><button type="button" className="primary-button" disabled={pending || Boolean(created)} onClick={createOrder}>{pending ? (zh ? "正在保存…" : "Saving…") : created ? (zh ? "测试订单已保存" : "Test order saved") : (zh ? "保存测试订单" : "Save test order")}</button>{created && <p role="status" className="commerce-order-id">{created.id}</p>}{orderError && <p role="alert">{zh ? "未能确认订单结果，可重试同一次操作或刷新记录核对。不会将连接失败显示为付款成功。" : "The order result could not be confirmed. Retry the same operation or refresh records to check. A connection failure is never treated as payment success."}</p>}</div>}
        {section !== "billing" && <a className="account-inline-action" href="/account/billing" onClick={event => navigate(event, "/account/billing")}>{zh ? "查看订单记录" : "View order records"}<ArrowRight /></a>}
      </>}
  </section>;
}
