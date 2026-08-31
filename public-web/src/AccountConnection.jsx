import { useRef, useState } from "react";
import { ArrowRight } from "@phosphor-icons/react";

export function AccountConnection({account,locale,onChange,disabled}) {
  const zh=locale==="zh", [key,setKey]=useState(""), [pending,setPending]=useState(false), [error,setError]=useState("");
  const inFlight=useRef(false);
  const connected=account.data_access_state==="connected";
  const hasConnection=account.data_connection_present===true;
  async function submit(event,remove=false) {
    event.preventDefault();if(inFlight.current || disabled || (!remove && !key.trim())) return;
    inFlight.current=true;setPending(true);setError("");
    const value=key;setKey("");
    try {await onChange(remove?"DELETE":"POST",remove?{}:{access_key:value});}
    catch(failure) {setError(failure.message);}
    finally {inFlight.current=false;setPending(false);}
  }
  const errors={
    recent_sign_in_required:zh?"请先退出并重新验证邮箱，再连接或移除数据访问。":"Sign out and verify your email again before connecting or removing data access.",
    invalid_access_key:zh?"服务端未认可这枚密钥，请核对是否有效。":"The service did not accept this key. Check that it is valid.",
    identity_changed:zh?"登录账户已改变。请刷新后重新确认。":"The signed-in account changed. Refresh and confirm the account.",
    connection_exists:zh?"已有数据连接，请先移除后再更换。":"A connection already exists. Remove it before replacing it.",
  };
  return <section className="account-connection" aria-labelledby="account-connection-title">
    <div><span className="mono-kicker">{zh?"数据访问":"DATA ACCESS"}</span><h3 id="account-connection-title">{connected?(zh?"已连接现有数据权限":"Existing data access connected"):(zh?"连接已有的数据访问":"Connect existing data access")}</h3>
      <p>{connected?(zh?`当前邮箱 ${account.email} · 数据账户 ${account.tenant_id}。权限由数据服务实时确认，非新订阅。`:`${account.email} · data account ${account.tenant_id}. Rights are confirmed by the data service, not a new subscription.`):(zh?"已经有 API 密钥？主动连接到当前邮箱账户，即可在这里查看权限、有效期和用量。邮箱登录本身不授予数据权限。":"Already have an API key? Connect it to this verified email to view access, expiry and usage here. Email sign-in itself grants no data access.")}</p>
    </div>
    {account.capabilities?.connection!==true?<p>{zh?"数据账户连接尚未开放。":"Data-account connection is not available yet."}</p>:hasConnection?<div>
      {account.data_access_state==="invalid" && <p role="status">{zh?"原连接已失效。邮箱账户与收藏仍保留，可移除后重新连接。":"The connection is no longer valid. Your email account and bookmarks remain; remove it before reconnecting."}</p>}
      <button type="button" className="account-inline-action" disabled={pending||disabled} onClick={event=>submit(event,true)}>{pending?(zh?"正在移除…":"Removing…"):(zh?"移除网页登录的数据连接":"Remove web data connection")}</button>
      <small>{zh?"不会删除上游 API 密钥或金融数据。":"Does not delete upstream API keys or financial data."}</small>
      {account.admin_available && <a className="account-inline-action" href="/admin/">{zh?"打开管理员工作台":"Open administrator workspace"}<ArrowRight /></a>}
    </div>:<form onSubmit={submit}>
      <label htmlFor="existing-data-access-key">{zh?"已有 API 密钥":"Existing API key"}</label>
      <div className="account-connection-input"><input id="existing-data-access-key" type="password" value={key} onChange={event=>setKey(event.target.value)} maxLength={1024} autoComplete="off" spellCheck={false} disabled={pending||disabled} /><button className="primary-button" type="submit" disabled={!key.trim()||pending||disabled}>{pending?(zh?"验证中…":"Verifying…"):(zh?"验证并连接":"Verify & connect")}<ArrowRight /></button></div>
      <small>{zh?"需要最近 10 分钟内验证过邮箱。密钥经服务端验证后加密保存，不会写入浏览器存储。已有连接需先移除才能更换。":"Requires an email sign-in within ten minutes. The service verifies and encrypts the key; it is never saved in browser storage. Remove any existing connection before replacing it."}</small>
    </form>}
    {error && <p className="account-key-error" role="alert">{errors[error]||(zh?"未能确认操作结果，请重新加载账户状态后再试。":"The operation could not be confirmed. Reload the account before retrying.")}</p>}
  </section>;
}
