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
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import markdown
    _HAS_MD = True
except ImportError:
    _HAS_MD = False
    import re


def _find_latest_report() -> str | None:
    """Return path to the most recent daily report, or ``None``."""
    pattern = os.path.join("output", "2*.md")
    reports = sorted(glob.glob(pattern))
    return reports[-1] if reports else None


def _strip_details_tags(text: str) -> str:
    """Remove <details> / <summary> wrappers from Markdown.

    Gmail does not support the HTML5 <details>/<summary> elements,
    and when they sit inside a list item Python-Markdown treats the
    inner content as raw HTML (so ``**Abstract:**`` never becomes
    bold).  We strip the wrappers here so:
    - the collapsible gimmick is gone (wouldn't work in email anyway)
    - ``**Abstract:**`` gets processed properly by the Markdown renderer
    """
    # Remove opening <details> (possibly with attributes)
    text = re.sub(r"^\s*<details[^>]*>\s*\n?", "", text, flags=re.MULTILINE)
    # Remove <summary>...</summary> lines
    text = re.sub(r"^\s*<summary>.*?</summary>\s*\n?", "", text, flags=re.MULTILINE)
    # Remove closing </details>
    text = re.sub(r"^\s*</details>\s*\n?", "", text, flags=re.MULTILINE)
    return text


def _render_html_md(text: str) -> str:
    """Convert Markdown to HTML (use `markdown` package if available)."""
    # Pre-process: strip <details>/<summary> (email incompatible)
    text = _strip_details_tags(text)

    if _HAS_MD:
        return markdown.markdown(
            text,
            extensions=["extra", "nl2br", "sane_lists"]
        )
    # Fallback: very basic conversion
    html = text
    html = re.sub(r"^### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)
    html = html.replace("\n\n", "<br><br>")
    return html


def send_email(report_path: str) -> None:
    smtp_server = os.environ["SMTP_SERVER"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ["SMTP_USERNAME"]
    password = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ.get("SMTP_FROM", username)
    to_addrs = [a.strip() for a in os.environ["NOTIFY_EMAIL"].split(",") if a.strip()]

    # Sanitize password: remove non-ASCII chars and whitespace
    password = unicodedata.normalize("NFKC", password).strip().replace(" ", "")

    if not to_addrs:
        print("[NOTIFY] No recipient configured (NOTIFY_EMAIL is empty). Skipping.")
        return

    # Read report
    with open(report_path, "r", encoding="utf-8") as f:
        report_content = f.read()

    date_str = os.path.basename(report_path).replace(".md", "")

    # Build multipart email (plain text + HTML)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Quant Marketing Daily \u2014 {date_str}"
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    # Plain-text version
    msg.attach(MIMEText(report_content, "plain", "utf-8"))

    # HTML version
    html_body = _render_html_md(report_content)
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #24292f; line-height: 1.6; }}
h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: 0.3em; margin-top: 2em; }}
h3 {{ margin-top: 1.5em; }}
h4 {{ margin-top: 1em; }}
a {{ color: #0969da; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
code {{ background: #f6f8fa; padding: 0.2em 0.4em; border-radius: 3px; font-size: 85%; }}
pre {{ background: #f6f8fa; padding: 1em; border-radius: 6px; overflow: auto; }}
blockquote {{ border-left: 4px solid #d0d7de; padding-left: 1em; color: #656d76; margin: 1em 0; }}
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
        print(f"[NOTIFY] \u2705 Email sent to {', '.join(to_addrs)}")
    finally:
        server.quit()


if __name__ == "__main__":
    latest = _find_latest_report()
    if not latest:
        print("[NOTIFY] No daily report found in output/. Nothing to send.")
        sys.exit(0)

    print(f"[NOTIFY] Sending report: {latest}")
    send_email(latest)
