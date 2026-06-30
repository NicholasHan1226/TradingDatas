"""
SharedSignals email sender — independent of Tradings.
Uses Cloudflare Email Routing with DeadSimple + SMTP fallback.
Configure via SharedSignals/.env or env vars.
"""
from __future__ import annotations
import hashlib, json, os, smtplib, time, urllib.error, urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "email"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Config from env (each repo has its own)
CF_ACCOUNT_ID = os.getenv("CF_EMAIL_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_EMAIL_API_TOKEN", "")
FROM_TRADING = os.getenv("EMAIL_FROM_TRADING", "notice@agentspaces.cc")
FROM_SYSTEM = os.getenv("EMAIL_FROM_SYSTEM", "notice@tradingagent.cc")
TO_TRADING = os.getenv("EMAIL_TO_TRADING", "tradingadviser@coze.email")
TO_SYSTEM = os.getenv("EMAIL_TO_SYSTEM", "soc@coze.email")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")

CHANNELS = {
    "trading": {"from": FROM_TRADING, "to": TO_TRADING},
    "system": {"from": FROM_SYSTEM, "to": TO_SYSTEM},
}


def _save_local(to: str, subject: str, body: str, channel: str, errors: list) -> dict:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    h = hashlib.md5(ts.encode()).hexdigest()[:8]
    path = LOG_DIR / "fallback" / f"{ts}-{h}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"to": to, "subject": subject, "body": body, "channel": channel, "errors": errors}, indent=2))
    return {"status": "saved_local", "provider": "local_file", "saved_to": str(path)}


def _try_cloudflare(to: str, subject: str, body: str, from_addr: str) -> bool:
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        raise Exception("CF credentials not configured")
    data = json.dumps({
        "from": from_addr,
        "to": [to],
        "subject": subject,
        "text_body": body[:10000],
        "html_body": body[:50000] if "<" in body else "",
        "priority": "normal",
    }).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/email/routing/messages",
        data=data,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read())
    return result.get("success", False)


def _try_smtp(to: str, subject: str, body: str, from_addr: str) -> bool:
    if not SMTP_HOST:
        raise Exception("SMTP not configured")
    msg = MIMEText(body, "html" if "<" in body else "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
        s.starttls()
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    return True


def send_email(*, to: str, subject: str, html_body: str, channel: str = "system") -> dict:
    """Send email via CF→DeadSimple→SMTP→local fallback. Independent of Tradings."""
    ch = CHANNELS.get(channel, CHANNELS["system"])
    from_addr = ch["from"]
    errors = []
    
    # 1. Cloudflare
    try:
        if _try_cloudflare(to, subject, html_body, from_addr):
            return {"status": "sent", "provider": "cloudflare", "to": to, "from": from_addr, "subject": subject}
    except Exception as e:
        errors.append(f"cloudflare: {e}")
    
    # 2. DeadSimple (generic HTTP mail API)
    try:
        ds_url = os.getenv("DEADSIMPLE_URL", "")
        if ds_url:
            data = json.dumps({"from": from_addr, "to": to, "subject": subject, "html": html_body}).encode()
            req = urllib.request.Request(ds_url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return {"status": "sent", "provider": "deadsimple", "to": to}
    except Exception as e:
        errors.append(f"deadsimple: {e}")
    
    # 3. SMTP
    try:
        if _try_smtp(to, subject, html_body, from_addr):
            return {"status": "sent", "provider": "smtp", "to": to}
    except Exception as e:
        errors.append(f"smtp: {e}")
    
    # 4. Local fallback
    return _save_local(to, subject, html_body, channel, errors)


def send_daily_report(date_str: str, data: dict) -> dict:
    """Send SharedSignals daily data report."""
    funcs = data.get("functions", {})
    fresh = data.get("freshness", {})
    issues = data.get("issues", [])
    
    rows = ""
    for m, info in fresh.items():
        e = "✅" if info.get("status") == "OK" else "⚠️"
        rows += f"<tr><td>{m}</td><td>{info.get('latest','?')}</td><td>{e} {info.get('status','?')}</td></tr>"
    
    body = f"""<html><body style="font-family:Arial;max-width:600px">
<h2>SharedSignals Data Daily Report</h2>
<p>{date_str} | Auto-generated | Research only</p>
<h3>Functions ({funcs.get('ok',0)}/{funcs.get('total',10)})</h3>
<p>{"ALL CLEAN" if funcs.get('ok')==funcs.get('total') else 'DEGRADED: '+','.join(funcs.get('degraded',[]))}</p>
<h3>Freshness</h3>
<table border="1" cellpadding="4"><tr><th>Market</th><th>Latest</th><th>Status</th></tr>{rows}</table>
{"" if not issues else "<h3>Issues</h3><ul>"+"".join(f"<li>{i}</li>" for i in issues)+"</ul>"}
</body></html>"""
    
    return send_email(to=TO_SYSTEM, subject=f"[SharedSignals] Data Report — {date_str}", html_body=body, channel="system")
