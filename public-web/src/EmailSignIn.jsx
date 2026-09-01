import { useEffect, useRef, useState } from "react";
import { ArrowRight, ShieldCheck } from "@phosphor-icons/react";
import { accountJson } from "./accountSession";
import { getSystemEmailLocale } from "./systemEmailLocale";

export function EmailSignIn({ locale, checking, onVerify }) {
  const zh = locale === "zh";
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [challenge, setChallenge] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const controller = useRef(null);
  const codeInput = useRef(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => {
    if (!challenge) return undefined;
    const tick = () => setRemaining(Math.max(0, Math.ceil((challenge.retryAt - Date.now()) / 1000)));
    tick(); const timer = setInterval(tick, 1000); return () => clearInterval(timer);
  }, [challenge]);
  useEffect(() => { if (challenge) codeInput.current?.focus(); }, [challenge]);
  async function send(event) {
    event?.preventDefault();
    if (pending.current || checking || remaining > 0) return;
    pending.current = true; setBusy(true); setError(""); controller.current = new AbortController();
    try {
      const payload = await accountJson("email/challenge", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: email.trim(), locale: getSystemEmailLocale() }), signal: controller.current.signal });
      if (!mounted.current) return;
      if (payload.delivery !== "accepted" || typeof payload.challenge_id !== "string" || !Number.isFinite(payload.retry_after)) throw new Error("account_unavailable");
      setCode(""); setChallenge({ id: payload.challenge_id, email: email.trim(), retryAt: Date.now() + payload.retry_after * 1000 });
    } catch (failure) { if (mounted.current) setError(failure.message === "rate_limited" ? "rate" : "send"); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  async function verify(event) {
    event.preventDefault(); if (pending.current || checking || !challenge) return;
    pending.current = true; setBusy(true); setError("");
    try { await onVerify({ email: challenge.email, challenge_id: challenge.id, code }); }
    catch (failure) { if (mounted.current) setError(failure.message === "rate_limited" ? "rate" : failure.message === "invalid_code" ? "code" : "verify"); }
    finally { pending.current = false; if (mounted.current) setBusy(false); }
  }
  const errorText = { rate: zh ? "请求较频繁，请稍后重试。" : "Too many attempts. Please wait and try again.", send: zh ? "暂时无法发送验证码，请稍后重试。" : "The code could not be sent. Please try again later.", code: zh ? "验证码不正确、已过期或已使用。请检查或重新获取。" : "The code is incorrect, expired, or already used. Check it or request a new one.", verify: zh ? "暂时无法完成验证，请稍后重试。" : "Verification is temporarily unavailable. Please try again." }[error];
  return <form onSubmit={challenge ? verify : send} aria-busy={busy || checking} className="email-signin-form">
    <p className="login-method-note">{zh ? "无需密码。首次验证邮箱后创建账户，不会自动订阅或扣费。" : "No password needed. Your first verification creates an account, without subscribing or charging you."}</p>
    <label htmlFor="login-email">{zh ? "邮箱地址" : "Email address"}</label>
    <input id="login-email" type="email" value={email} onChange={event => { setEmail(event.target.value); setError(""); }} autoComplete="email" autoCapitalize="none" spellCheck={false} maxLength={254} placeholder="you@example.com" disabled={Boolean(challenge) || busy || checking} required />
    {challenge && <>
      <p className="login-email-status" role="status">{zh ? "邮件已交给发送服务，请查收收件箱或垃圾邮件。验证码 10 分钟内有效；实际送达可能稍有延迟。" : "The email was accepted for sending. Check your inbox or spam folder. Your code expires in 10 minutes; delivery may take a moment."}</p>
      <label htmlFor="login-email-code">{zh ? "8 位验证码" : "8-digit code"}</label>
      <input ref={codeInput} id="login-email-code" value={code} onChange={event => { setCode(event.target.value.replace(/\D/g, "").slice(0, 8)); setError(""); }} inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{8}" maxLength={8} required disabled={busy || checking} aria-invalid={Boolean(error)} aria-describedby={error ? "email-login-error" : undefined} />
    </>}
    {error && <p className="login-error" id="email-login-error" role="alert">{errorText}</p>}
    <button className="primary-button login-submit" disabled={busy || checking || (challenge ? code.length !== 8 : !email.trim())}>{busy ? (zh ? "正在处理…" : "Working…") : challenge ? (zh ? "验证并继续" : "Verify & continue") : (zh ? "获取验证码" : "Send code")}<ArrowRight /></button>
    {challenge && <div className="email-signin-actions"><button className="text-link" type="button" disabled={busy || checking || remaining > 0} onClick={send}>{remaining > 0 ? (zh ? `${remaining} 秒后重发` : `Resend in ${remaining}s`) : (zh ? "重新发送" : "Resend code")}</button><button className="text-link" type="button" disabled={busy || checking} onClick={() => {setChallenge(null); setCode(""); setError(""); setRemaining(0);}}>{zh ? "更换邮箱" : "Change email"}</button></div>}
    <p className="login-key-note"><ShieldCheck size={16} /><span>{zh ? "验证码仅用于本次登录；不会出现在链接、浏览器存储或公开日志中。" : "Codes are used only for sign-in, never stored in links, browser storage, or public logs."}</span></p>
  </form>;
}
