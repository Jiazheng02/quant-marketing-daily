#!/usr/bin/env python3
"""Send the latest daily report via email.

Triggered by GitHub Actions after ``src.fetch`` completes.
Reads SMTP credentials from environment variables (see ``.env.example``).

Environment variables required
----------------------------
SMTP_SERVER     SMTP server host (e.g. ``smtp.gmail.com``)
SMTP_PORT       SMTP port, default 587
SMTP_USERNAME   SMTP login username
SMTP_PASSWORD   SMTP login password (use app password, NOT regular password)
SMTP_FROM       ``From`` address (defaults to ``SMTP_USERNAME``)
NOTIFY_EMAIL    Recipient email address(es), comma-separated
"""

import glob
import os
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def _find_latest_report() -> str | None:
    """Return path to the most recent daily report, or ``None``."""
    pattern = os.path.join("output", "2*.md")
    reports = sorted(glob.glob(pattern))
    return reports[-1] if reports else None


def send_email(report_path: str) -> None:
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ.get("SMTP_FROM", username)
    to_addrs = [a.strip() for a in os.environ["NOTIFY_EMAIL"].split(",") if a.strip()]

    if not to_addrs:
        print("[NOTIFY] No recipient configured (NOTIFY_EMAIL is empty). Skipping.")
        return

    # Read report
    with open(report_path, "r", encoding="utf-8") as f:
        report_content = f.read()

    date_str = os.path.basename(report_path).replace(".md", "")

    # Build multipart email (plain text + HTML)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Quant Marketing Daily — {date_str}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    # Plain-text version
    msg.attach(MIMEText(report_content, "plain", "utf-8"))

    # HTML version — render Markdown minimally for readability
    html_body = report_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html_body = html_body.replace("\n", "<br>\n")
    # Make headings bold
    import re
    html_body = re.sub(r"^###\s+(.*?)<br>", r"<h4>\1</h4>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^##\s+(.*?)<br>", r"<h3>\1</h3>", html_body, flags=re.MULTILINE)
    html_body = re.sub(r"^#\s+(.*?)<br>", r"<h2>\1</h2>", html_body, flags=re.MULTILINE)
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 720px; margin: 2rem auto; color: #24292f; line-height: 1.6; }}
h2, h3, h4 {{ margin-top: 1.5em; }}
a {{ color: #0969da; }}
</style></head><body>
{html_body}
</body></html>"""
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    # Send
    use_ssl = smtp_port == 465
    if use_ssl:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.starttls()

    try:
        server.login(username, password)
        server.send_message(msg)
        print(f"[NOTIFY] ✅ Email sent to {', '.join(to_addrs)}")
    finally:
        server.quit()


if __name__ == "__main__":
    latest = _find_latest_report()
    if not latest:
        print("[NOTIFY] No daily report found in output/. Nothing to send.")
        sys.exit(0)

    print(f"[NOTIFY] Sending report: {latest}")
    send_email(latest)
