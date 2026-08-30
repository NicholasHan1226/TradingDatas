import { ShieldCheck, ArrowRight } from "@phosphor-icons/react";
import { useRef, useState } from "react";

// A panel inside the existing Account shell, not another customer dashboard.
export function EmailAccountPanel({ account, section, locale, onSignOut, signingOut, navigate, onDelete }) {
  const zh = locale === "zh";
  const [confirming, setConfirming] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deletionInFlight = useRef(false);
  const confirmationInput = useRef(null);
  async function submitDeletion(event) {
    event.preventDefault();
    if (confirmation !== "DELETE" || deletionInFlight.current || signingOut) return;
    deletionInFlight.current = true; setDeleting(true); setDeleteError("");
    try { await onDelete(); }
    catch (error) { setDeleteError(error.message === "recent_sign_in_required" ? "reauth" : "unconfirmed"); }
    finally { deletionInFlight.current = false; setDeleting(false); }
  }
  const copy = {
    overview: [zh ? "邮箱已验证" : "Email verified", zh ? "账户已建立，尚未订阅数据。" : "Your account is ready. No data subscription yet."],
    subscription: [zh ? "尚未订阅" : "Not subscribed", zh ? "可先了解三档基础数据套餐。支付仍未开放，浏览预览不会下单或扣费。" : "Explore the three base-data plans. Payment is not open; previews create no orders or charges."],
    usage: [zh ? "尚无数据用量" : "No data usage yet", zh ? "当前账户没有数据授权，因此没有可展示的 API 请求用量。" : "This account has no data entitlement, so no API usage is available."],
    keys: [zh ? "数据授权后再创建密钥" : "API keys follow data access", zh ? "邮箱登录不是 API 密钥。未订阅账户不能创建或继承数据权限；已有密钥也不会自动绑定。" : "An email login is not an API key. An unsubscribed account cannot create or inherit data access. Existing keys are not linked automatically."],
    billing: [zh ? "暂无订单与账单" : "No orders or bills", zh ? "支付暂未开放。邮箱验证不会创建订单、扣费或自动续费。" : "Payment is not open. Email verification creates no orders, charges, or automatic renewals."],
    security: [zh ? "独立邮箱会话" : "Independent email session", zh ? "网页登录与 API 密钥独立。退出后此会话在服务端撤销，不会修改任何数据密钥。" : "Web sign-in is independent of API keys. Signing out revokes this session on the server without changing any data keys."],
  }[section];
  return <div className="account-live-overview email-account-panel">
    <div className="account-live-status"><span className="is-active" /><strong>{zh ? "已登录 · 邮箱验证" : "Signed in · verified email"}</strong><button type="button" onClick={onSignOut} disabled={signingOut || deleting}>{signingOut ? (zh ? "正在退出…" : "Signing out…") : (zh ? "退出登录" : "Sign out")}</button></div>
    <div className="email-account-intro"><ShieldCheck size={28} /><h3>{copy[0]}</h3><p>{copy[1]}</p></div>
    {["overview", "security"].includes(section) && <dl className="account-facts account-live-facts">
      <div><dt>{zh ? "已验证邮箱" : "Verified email"}</dt><dd>{account.email}</dd></div>
      <div><dt>{zh ? "数据订阅" : "Data subscription"}</dt><dd>{zh ? "未订阅 · 无数据授权" : "Not subscribed · no data grants"}</dd></div>
      <div><dt>{zh ? "网页会话到期" : "Web session expires"}</dt><dd>{new Date(account.session_expires_at).toLocaleString(zh ? "zh-CN" : "en-US")}</dd></div>
      <div><dt>{zh ? "短信登录" : "Phone sign-in"}</dt><dd>{zh ? "尚未开放" : "Not available yet"}</dd></div>
    </dl>}
    {section === "security" && <section className="email-account-deletion" aria-labelledby="account-deletion-title">
      <h3 id="account-deletion-title">{zh ? "账户资料与注销" : "Profile & deletion"}</h3>
      <p>{zh ? "注销会立即停用此账户并撤销所有邮箱会话，账户库中的资料将在 30 天内清理。重新注册不会恢复旧身份或权限。浏览器中的收藏需自行清除。" : "Deletion disables this account and revokes every email session immediately. Profile data in the account store is removed within 30 days. Registering again restores no old identity or access. Browser-local bookmarks need to be cleared separately."}</p>
      {account.deletion_available !== true ? <p>{zh ? "注销服务尚未开放，请先联系平台处理。" : "Self-service deletion is not available yet. Contact the platform for assistance."}</p> : !confirming ? <button type="button" className="account-inline-action" disabled={signingOut} onClick={() => { setConfirming(true); requestAnimationFrame(() => confirmationInput.current?.focus()); }}>{zh ? "申请注销账户" : "Request account deletion"}</button> : <form onSubmit={submitDeletion}>
        <label htmlFor="account-delete-confirm">{zh ? "输入 DELETE 确认注销（不可撤销）" : "Type DELETE to confirm (cannot be undone)"}</label>
        <input ref={confirmationInput} id="account-delete-confirm" value={confirmation} onChange={event => setConfirmation(event.target.value)} autoComplete="off" spellCheck={false} disabled={deleting || signingOut} />
        <small>{zh ? "需要在最近 10 分钟内重新验证过邮箱。这里只注销网页登录账户，不会删除旧 API 密钥或金融数据。" : "Requires an email sign-in within the last 10 minutes. This deletes only your web account, not legacy API keys or financial data."}</small>
        {deleteError && <p className="account-key-error" role="alert">{deleteError === "reauth" ? (zh ? "请先退出并重新通过邮箱验证，再返回此页注销。" : "Sign out and verify your email again, then return here to delete the account.") : (zh ? "未能确认注销结果。请重新加载账户状态；不要把网络错误当成已注销。" : "Deletion could not be confirmed. Reload your account status; a network error does not mean the account was deleted.")}</p>}
        <div className="email-deletion-actions"><button className="primary-button" type="submit" disabled={confirmation !== "DELETE" || deleting || signingOut}>{deleting ? (zh ? "正在提交…" : "Submitting…") : (zh ? "确认注销" : "Confirm deletion")}</button><button type="button" disabled={deleting} onClick={() => {setConfirming(false);setConfirmation("");setDeleteError("");}}>{zh ? "保留账户" : "Keep account"}</button></div>
      </form>}
    </section>}
    {section !== "security" && <a className="account-inline-action" href="/pricing" onClick={event => navigate(event, "/pricing")}>{zh ? "了解套餐 · 支付暂未开放" : "Explore plans · payment unavailable"}<ArrowRight /></a>}
  </div>;
}
