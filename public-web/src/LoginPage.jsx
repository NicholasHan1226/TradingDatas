import { useState } from "react";
import { ArrowRight, EnvelopeSimple, Key, ShieldCheck, DeviceMobile } from "@phosphor-icons/react";

export function LoginPage({ locale, theme, returnPath = "/account", token, onTokenChange, onSubmit, loading, submitting, error, navigate }) {
  const [method, setMethod] = useState("key");
  const zh = locale === "zh";
  const methods = [{ id: "key", label: zh ? "访问密钥" : "Access key", Icon: Key }, { id: "phone", label: zh ? "手机号" : "Phone", Icon: DeviceMobile }, { id: "email", label: zh ? "邮箱" : "Email", Icon: EnvelopeSimple }];
  const errorText = {
    invalid_token: zh ? "密钥无效、已停用或已过期。请检查后重试。" : "This key is invalid, disabled, or expired. Check it and try again.",
    access_denied: zh ? "当前凭证没有账户访问权限。" : "This credential does not have account access.",
    rate_limited: zh ? "请求较频繁，请稍后再试。" : "Too many attempts. Please wait before trying again.",
    account_timeout: zh ? "连接超时。请检查网络，然后重试。" : "The connection timed out. Check your network and try again.",
  }[error] || (zh ? "暂时无法连接登录服务，请稍后重试。" : "The sign-in service is temporarily unavailable. Please try again later.");
  return <section className="login-page" aria-labelledby="login-title">
    <div className="login-intro">
      <a href="/" onClick={(event) => navigate(event, "/")}>← {zh ? "返回首页" : "Back home"}</a>
      <div className="login-editorial">
        <span className="mono-kicker">YOUR NEXT DISCOVERY</span>
        <h2>{zh ? <>好数据。<br />好研究的起点。</> : <>Good data.<br />A place to begin.</>}</h2>
        <p>{zh ? "把数据交给我们，把探索留给你。" : "We take care of the data. You follow the questions."}</p>
      </div>
      <div className="login-material" aria-hidden="true"><img src={`/assets/data-material-${theme === "dark" ? "dark" : "light"}.png`} alt="" /><span>Data, with receipts.</span></div>
    </div>
    <div className="login-panel">
      <div className="login-panel-copy"><span className="mono-kicker">TRADINGDATAS ACCOUNT</span><h1 id="login-title">{zh ? "欢迎回来" : "Welcome back"}</h1><p>{zh ? "在同一个账户里管理数据访问与订阅。" : "Your data access and subscription, in one account."}</p></div>
      {returnPath !== "/account" && <p className="login-return-note">{zh ? "登录后回到刚才的购买预览。所选套餐与周期不会丢失，也不会自动下单。" : "After sign-in, return to your selected plan and term. No order is placed automatically."} <a className="text-link" href={returnPath} onClick={(event) => navigate(event, returnPath)}>{zh ? "先返回预览" : "Back to preview"}</a></p>}
      <div className="login-methods" aria-label={zh ? "登录方式" : "Sign-in method"}>
        {methods.map(({ id, label, Icon }) => <button type="button" key={id} aria-pressed={method === id} aria-controls="login-method-panel" disabled={submitting} onClick={() => setMethod(id)}><Icon size={17} />{label}</button>)}
      </div>
      <div id="login-method-panel" className="login-method-panel">
        {method === "key" ? <form onSubmit={onSubmit} aria-busy={loading}>
          <p className="login-method-note">{zh ? "已有 TradingDatas 访问密钥？在此建立网页会话。" : "Already have a TradingDatas access key? Start a web session here."}</p>
          <label htmlFor="login-token">{zh ? "访问密钥" : "Access key"}</label>
          <input id="login-token" type="password" value={token} onChange={(event) => onTokenChange(event.target.value)} maxLength={1024} placeholder={zh ? "粘贴你的访问密钥" : "Paste your access key"} autoComplete="off" autoCapitalize="none" spellCheck={false} disabled={loading} required aria-invalid={Boolean(error)} aria-describedby={error ? "login-error login-key-note" : "login-key-note"} />
          {error && <p id="login-error" className="login-error" role="alert">{errorText}</p>}
          <button className="primary-button login-submit" type="submit" disabled={!token.trim() || loading}>{loading ? (submitting ? (zh ? "正在登录…" : "Signing in…") : (zh ? "正在检查会话…" : "Checking session…")) : (zh ? "登录账户" : "Sign in")}<ArrowRight /></button>
          <p id="login-key-note" className="login-key-note"><ShieldCheck size={16} /><span>{zh ? "通过同站加密会话连接，不在浏览器存储中保留原始密钥。" : "A same-site encrypted session. No raw key in browser storage."}</span></p>
        </form> : <div className="login-coming" role="status">
          <span className="login-availability">{zh ? "尚未开放" : "Not available yet"}</span>
          <h3>{method === "phone" ? (zh ? "手机号验证码登录" : "Sign in by phone") : (zh ? "邮箱验证码登录" : "Sign in by email")}</h3>
          <p>{zh ? "邮箱与短信登录尚未开放。接通后可用验证码登录或注册；现在不会收集你的联系方式或发送验证码。" : "Email and SMS sign-in are not available yet. Once connected, a verification code will let you sign in or register. We are not collecting contact details or sending codes here."}</p>
          <button className="text-link" type="button" onClick={() => setMethod("key")}>{zh ? "已有密钥？继续登录" : "Have a key? Continue signing in"}<ArrowRight /></button>
        </div>}
      </div>
      <div className="login-help"><span>{zh ? "第一次来？先了解数据与套餐。" : "New here? Explore the data and plans."}</span><a href="/pricing" onClick={(event) => navigate(event, "/pricing")}>{zh ? "查看套餐" : "Explore plans"}<ArrowRight /></a></div>
    </div>
  </section>;
}
