"""
SharedSignals email sender — independent of tradingagent.
Sends via Cloudflare Email Service REST endpoint, then saves a local fallback record.
Configure via SharedSignals env files or process env vars.
"""
from __future__ import annotations
import hashlib, json, os, smtplib, ssl, time, urllib.error, urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

def _normalize_env_value(raw: str) -> str:
    value = raw.strip()
    if value and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_email_env_files() -> None:
    env_files = (
        Path(os.environ.get("SHAREDSIGNALS_ENV_FILE", "/opt/sharedsignals/.env")),
        Path("/opt/investment/SharedSignals/.env"),
        Path(__file__).resolve().parent.parent / ".env",
    )
    for env_path in dict.fromkeys(env_files):
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].strip()
            key, value = line.split("=", 1)
            key = key.strip()
            if key and key not in os.environ:
                os.environ[key] = _normalize_env_value(value)


_load_email_env_files()

LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "email"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Config from env (each repo has its own)
CF_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "") or os.getenv("CF_EMAIL_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CLOUDFLARE_EMAIL_API_TOKEN", "") or os.getenv("CF_EMAIL_API_TOKEN", "")
FROM_TRADING = os.getenv("EMAIL_FROM_TRADING") or os.getenv("EMAIL_TRADING_FROM") or "notice@tradingagent.cc"
FROM_SYSTEM = os.getenv("EMAIL_FROM_SYSTEM") or os.getenv("EMAIL_SYSTEM_FROM") or "notice@tradingagent.cc"
TO_TRADING = os.getenv("EMAIL_TO_TRADING") or os.getenv("EMAIL_TRADING_TO") or "tradingadviser@coze.email"
TO_SYSTEM = os.getenv("EMAIL_TO_SYSTEM") or os.getenv("EMAIL_SYSTEM_TO") or "soc@coze.email"
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
        raise Exception("Cloudflare credentials not configured")
    data = json.dumps({
        "from": from_addr,
        "to": [to],
        "subject": subject,
        "text": body[:10000],
        "html": body[:50000] if "<" in body else body[:10000],
    }).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/email/sending/send",
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
        s.starttls(context=ssl.create_default_context())
        if SMTP_USER:
            s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    return True


def send_email(*, to: str, subject: str, html_body: str, channel: str = "system") -> dict:
    """Send email via Cloudflare; save locally when delivery is unavailable."""
    ch = CHANNELS.get(channel, CHANNELS["system"])
    from_addr = ch["from"]
    errors = []
    try:
        if _try_cloudflare(to, subject, html_body, from_addr):
            return {"status": "sent", "provider": "cloudflare", "to": to, "from": from_addr, "subject": subject}
    except Exception as e:
        errors.append(f"cloudflare: {e}")
    errors.append("smtp: removed from delivery chain")
    errors.append("deadsimple: removed from delivery chain")
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


def main():
    """CLI entry point for subprocess invocation from heal.py etc."""
    import argparse
    parser = argparse.ArgumentParser(description="SharedSignals email sender")
    parser.add_argument("--subject", required=True, help="Email subject")
    parser.add_argument("--body", required=True, help="Email body (HTML or plain text)")
    parser.add_argument("--channel", default="system", choices=["system", "trading"])
    parser.add_argument("--to", help="Override recipient (default: channel default)")
    args = parser.parse_args()

    ch = CHANNELS.get(args.channel, CHANNELS["system"])
    to = args.to or ch["to"]
    result = send_email(to=to, subject=args.subject, html_body=args.body, channel=args.channel)
    print(json.dumps(result, ensure_ascii=False))
    if result.get("status") != "sent":
        sys.exit(1)


if __name__ == "__main__":
    import sys
    main()
