import { ArrowRight, ShieldCheck } from "@phosphor-icons/react";
import { BASE_PLANS, formatCny } from "./pricing.js";
import { buildPreviewPath, getPreviewState } from "./purchasePreview.js";
import "./purchasePreview.css";

export function PurchasePreview({ locale, selection, accountState, navigate, onRetry, onAccount }) {
  const zh = locale === "zh";
  const state = getPreviewState(selection, accountState);
  if (!selection) return <section className="purchase-preview preview-invalid">
    <span className="mono-kicker">PURCHASE PREVIEW</span>
    <h1>{zh ? "请重新选择套餐。" : "Choose a plan to begin."}</h1>
    <p>{zh ? "这个预览链接不完整或已失效。没有创建订单，也没有发生扣款。" : "This preview link is incomplete or invalid. No order was created and no payment was taken."}</p>
    <a className="primary-button" href="/pricing" onClick={(event) => navigate(event, "/pricing")}>{zh ? "返回套餐" : "Back to plans"}<ArrowRight /></a>
  </section>;
  const { plan, price, period } = selection;
  const path = buildPreviewPath(plan.id, period);
  const loginPath = `/login?next=${encodeURIComponent(path)}`;
  const editPath = `/pricing?plan=${plan.id}&period=${period}`;
  const accountCopy = {
    checking: [zh ? "正在验证账户" : "Checking account", zh ? "验证完成前不展示账户状态，无需重复登录。" : "Wait for session verification. You do not need to sign in again."],
    unavailable: [zh ? "账户连接暂不可用" : "Account connection unavailable", zh ? "可以继续查看价格；连接故障不会被当作退出登录。" : "You can still review prices. A connection failure is not a sign-out."],
    signed_out: [zh ? "先看清楚，再登录。" : "Review first. Sign in when ready.", zh ? "登录页会显示当前可用的验证方式；登录不会创建订单或授予数据权限。" : "The sign-in page shows the currently available verification methods. Signing in creates no order and grants no data access."],
    authenticated: [zh ? "账户已连接" : "Account connected", zh ? "这里只预览所选套餐，不会变更当前套餐、有效期或数据授权。" : "This is a preview of your selection. Your current plan, expiry, and data access stay unchanged."],
  }[state.identity];
  return <section className="purchase-preview" aria-labelledby="purchase-title">
    <a className="object-back" href={editPath} onClick={(event) => navigate(event, editPath)}>← {zh ? "返回套餐" : "Back to plans"}</a>
    <header className="purchase-heading"><span className="mono-kicker">BASE DATA / PURCHASE PREVIEW</span><h1 id="purchase-title">{zh ? "你的数据，选好了。" : "Your data. Your pace."}</h1><p>{zh ? "核对套餐与周期。支付暂未开放，这不是订单。" : "Review your plan and term. Payment is not open yet. This is not an order."}</p></header>
    <div className="purchase-layout">
      <div className="purchase-details">
        <section aria-labelledby="preview-plan-title"><div className="preview-section-title"><span>01</span><h2 id="preview-plan-title">{zh ? "基础数据套餐" : "Base-data plan"}</h2></div>
          <div className="preview-options" role="group" aria-label={zh ? "预览套餐" : "Preview plan"}>{BASE_PLANS.map((item) => <a key={item.id} href={buildPreviewPath(item.id, period)} aria-current={item.id === plan.id ? "true" : undefined} onClick={(event) => navigate(event, buildPreviewPath(item.id, period))}>{item.name[locale]}<small>{item.requestsPerMinute.toLocaleString("en-US")} / {zh ? "分钟" : "min"}</small></a>)}</div>
          <p>{zh ? "三档使用相同基础数据，仅请求频率不同。不设每日额度或商业档并发上限；不含另类数据。" : "The same base data at three request rates. No daily quota or commercial concurrency cap. Alternative data is not included."}</p>
          <a className="text-link" href="/data" onClick={(event) => navigate(event, "/data")}>{zh ? "查看数据范围与采集说明" : "Explore data and collection details"}<ArrowRight /></a>
        </section>
        <section aria-labelledby="preview-term-title"><div className="preview-section-title"><span>02</span><h2 id="preview-term-title">{zh ? "购买周期" : "Purchase term"}</h2></div>
          <div className="preview-options preview-terms" role="group" aria-label={zh ? "预览周期" : "Preview term"}>{["monthly", "annual"].map((item) => <a key={item} href={buildPreviewPath(plan.id, item)} aria-current={period === item ? "true" : undefined} onClick={(event) => navigate(event, buildPreviewPath(plan.id, item))}>{item === "monthly" ? (zh ? "月付" : "Monthly") : (zh ? "年付" : "Annual")}<small>{item === "annual" ? (zh ? "12 个月 · 9 折" : "12 months · save 10%") : (zh ? "1 个月" : "1 month")}</small></a>)}</div>
          <p>{zh ? "每次主动购买一段服务期，到期后手动续费。不自动扣款。续费衔接与升级规则会在正式下单前明确展示。" : "Actively purchase a service term and renew manually. No automatic debit. Renewal timing and upgrade rules will be disclosed before real checkout."}</p>
        </section>
        <section aria-labelledby="preview-account-title"><div className="preview-section-title"><span>03</span><h2 id="preview-account-title">{zh ? "账户" : "Account"}</h2></div>
          <div className="preview-account" aria-live="polite" aria-busy={state.identity === "checking"}><ShieldCheck size={22} /><div><strong>{accountCopy[0]}</strong><p>{accountCopy[1]}</p>
            {state.canSignIn && <a className="text-link" href={loginPath} onClick={(event) => navigate(event, loginPath)}>{zh ? "登录后返回预览" : "Sign in and return to preview"}<ArrowRight /></a>}
            {state.identity === "unavailable" && <button type="button" className="text-link" onClick={onRetry}>{zh ? "重试连接" : "Retry connection"}<ArrowRight /></button>}
            {state.identity === "authenticated" && <button type="button" className="text-link" onClick={onAccount}>{zh ? "查看当前套餐与授权" : "View current plan and access"}<ArrowRight /></button>}
          </div></div>
        </section>
      </div>
      <aside className="preview-summary" aria-labelledby="preview-summary-title">
        <span className="mono-kicker">{zh ? "购买预览 · 非订单" : "PREVIEW · NOT AN ORDER"}</span>
        <h2 id="preview-summary-title">{plan.name[locale]}</h2>
        <p>{plan.requestsPerMinute.toLocaleString("en-US")} {zh ? "次请求 / 分钟" : "requests / minute"}</p>
        <div className="preview-total" aria-live="polite"><span>{zh ? "所选周期总价" : "Selected term total"}</span><strong>{formatCny(price.totalMinor, locale)}<small>CNY</small></strong><p>{period === "annual" ? (zh ? `12 个月，折合 ${formatCny(price.monthlyEquivalentMinor, locale)} / 月` : `12 months, equivalent to ${formatCny(price.monthlyEquivalentMinor, locale)} / month`) : (zh ? "1 个月服务期" : "1-month service term")}</p></div>
        {period === "annual" && <div className="preview-saving"><span>{zh ? "比逐月购买节省" : "Saved versus monthly"}</span><strong>{formatCny(price.savingsMinor, locale)}</strong></div>}
        <button type="button" disabled className="primary-button preview-payment">{zh ? "支付暂未开放" : "Payment not available yet"}</button>
        <p className="preview-boundary">{zh ? "预览不会创建订单、收款或开通权限。正式开放后，价格和条款以服务端确认的订单为准。" : "Previewing creates no order, payment, or access. Final prices and terms will come from a server-confirmed order when checkout opens."}</p>
      </aside>
    </div>
  </section>;
}
