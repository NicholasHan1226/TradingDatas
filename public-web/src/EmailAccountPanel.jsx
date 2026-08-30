import { ShieldCheck, ArrowRight } from "@phosphor-icons/react";

// A panel inside the existing Account shell, not another customer dashboard.
export function EmailAccountPanel({ account, section, locale, onSignOut, signingOut, navigate }) {
  const zh = locale === "zh";
  const copy = {
    overview: [zh ? "邮箱已验证" : "Email verified", zh ? "账户已建立，尚未订阅数据。" : "Your account is ready. No data subscription yet."],
    subscription: [zh ? "尚未订阅" : "Not subscribed", zh ? "可先了解三档基础数据套餐。支付仍未开放，浏览预览不会下单或扣费。" : "Explore the three base-data plans. Payment is not open; previews create no orders or charges."],
    usage: [zh ? "尚无数据用量" : "No data usage yet", zh ? "当前账户没有数据授权，因此没有可展示的 API 请求用量。" : "This account has no data entitlement, so no API usage is available."],
    keys: [zh ? "数据授权后再创建密钥" : "API keys follow data access", zh ? "邮箱登录不是 API 密钥。未订阅账户不能创建或继承数据权限；已有密钥也不会自动绑定。" : "An email login is not an API key. An unsubscribed account cannot create or inherit data access. Existing keys are not linked automatically."],
    billing: [zh ? "暂无订单与账单" : "No orders or bills", zh ? "支付暂未开放。邮箱验证不会创建订单、扣费或自动续费。" : "Payment is not open. Email verification creates no orders, charges, or automatic renewals."],
    security: [zh ? "独立邮箱会话" : "Independent email session", zh ? "网页登录与 API 密钥独立。退出后此会话在服务端撤销，不会修改任何数据密钥。" : "Web sign-in is independent of API keys. Signing out revokes this session on the server without changing any data keys."],
  }[section];
  return <div className="account-live-overview email-account-panel">
    <div className="account-live-status"><span className="is-active" /><strong>{zh ? "已登录 · 邮箱验证" : "Signed in · verified email"}</strong><button type="button" onClick={onSignOut} disabled={signingOut}>{signingOut ? (zh ? "正在退出…" : "Signing out…") : (zh ? "退出登录" : "Sign out")}</button></div>
    <div className="email-account-intro"><ShieldCheck size={28} /><h3>{copy[0]}</h3><p>{copy[1]}</p></div>
    {["overview", "security"].includes(section) && <dl className="account-facts account-live-facts">
      <div><dt>{zh ? "已验证邮箱" : "Verified email"}</dt><dd>{account.email}</dd></div>
      <div><dt>{zh ? "数据订阅" : "Data subscription"}</dt><dd>{zh ? "未订阅 · 无数据授权" : "Not subscribed · no data grants"}</dd></div>
      <div><dt>{zh ? "网页会话到期" : "Web session expires"}</dt><dd>{new Date(account.session_expires_at).toLocaleString(zh ? "zh-CN" : "en-US")}</dd></div>
      <div><dt>{zh ? "短信登录" : "Phone sign-in"}</dt><dd>{zh ? "尚未开放" : "Not available yet"}</dd></div>
    </dl>}
    {section !== "security" && <a className="account-inline-action" href="/pricing" onClick={event => navigate(event, "/pricing")}>{zh ? "了解套餐 · 支付暂未开放" : "Explore plans · payment unavailable"}<ArrowRight /></a>}
  </div>;
}
