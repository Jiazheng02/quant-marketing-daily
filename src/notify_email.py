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
import re
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


def _find_latest_report() -> str | None:
    """Return path to the most recent daily report, or ``None``."""
    pattern = os.path.join("output", "2*.md")
    reports = sorted(glob.glob(pattern))
    return reports[-1] if reports else None


# ---------------------------------------------------------------------------
# Custom Markdown → Email HTML renderer
# ---------------------------------------------------------------------------
# We do NOT use python-markdown for the main rendering because it mangles
# bold/italic inside list items (<li>).  Instead we hand-parse the specific
# structure produced by render.py and emit styled HTML directly.
#
# Expected paper block format from render.py:
#
#   - **English Title**
#     *Chinese Title*
#     *Authors*
#     `YYYY-MM` · `Vol.XX(I)` · `doi:10.xxxx/...`
#
#     **AI 总结：** one-liner
#     **原文链接：** [Source](url)
#
#     <details>
#     <summary><b>展开详情</b></summary>
#
#     **Abstract:** text...
#     **中文翻译：** text...
#     </details>
# ---------------------------------------------------------------------------

_EMAIL_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
        max-width: 780px; margin: 0 auto; padding: 1.5rem; color: #24292f; line-height: 1.65; }
h1 { font-size: 1.4em; border-bottom: 2px solid #d0d7de; padding-bottom: 0.4em; margin-bottom: 0.5em; color: #0969da; }
h2 { font-size: 1.15em; border-bottom: 1px solid #e1e4e8; padding-bottom: 0.25em;
     margin-top: 2em; color: #24292f; clear: both; }
h3 { font-size: 1em; color: #586069; }
.toc { background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; padding: 0.8rem 1.2rem; margin: 1em 0; }
.toc ul { list-style: none; padding-left: 0; margin: 0; }
.toc li::before { content: "· "; color: #0969da; font-weight: bold; }
.toc a { text-decoration: none; color: #0969da; }
.toc a:hover { text-decoration: underline; }

/* Paper card */
.paper-card { border-left: 3px solid #0969da; padding: 0.8rem 1rem 0.5rem 1.2rem; margin: 1em 0; background: #fafbfc; border-radius: 0 6px 6px 0; }
.paper-title { font-size: 1.05em; font-weight: 700; color: #24292f; margin-bottom: 0.25em; line-height: 1.4; }
.paper-title-zh { font-style: italic; color: #586069; font-size: 0.95em; margin-bottom: 0.15em; }
.paper-authors { font-style: italic; color: #586069; font-size: 0.92em; margin-bottom: 0.15em; }
.paper-meta { color: #6a737d; font-size: 0.85em; margin-bottom: 0.5em; letter-spacing: 0.01em; }
.paper-meta code { background: transparent; padding: 0; font-size: inherit; color: #6a737d; }
.paper-ai { color: #0366d6; font-size: 0.92em; margin: 0.4em 0; }
.paper-link { font-size: 0.92em; margin: 0.3em 0; }
.paper-link a { color: #0969da; }
.paper-abstract { margin-top: 0.6em; padding: 0.6rem 0.8rem; background: #ffffff; border-radius: 4px;
                border: 1px solid #e1e4e8; font-size: 0.92em; line-height: 1.65; color: #444; }
.paper-abstract strong { color: #24292f; }
.paper-abstract p { margin: 0.35em 0; }

blockquote { border-left: 4px solid #d0d7de; padding: 0.5em 1em; color: #656d76; margin: 1em 0;
             background: #f6f8fa; border-radius: 0 4px 4px 0; font-size: 0.92em; }
hr { border: none; border-top: 1px solid #e1e4e8; margin: 1.5em 0; }
.footer { color: #959da5; font-size: 0.85em; margin-top: 2em; padding-top: 1em; border-top: 1px solid #e1e4e8; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code { background: #f6f8fa; padding: 0.15em 0.35em; border-radius: 3px; font-size: 88%; }
"""


def _md_inline_to_html(text: str) -> str:
    """Convert inline Markdown to HTML (bold, italic, links, code)."""
    # Escape HTML entities first
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    # Code spans (`...`) — do first so inner content isn't touched
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold (**...**)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic (*...*)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    # Links ([text](url))
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    return text


def _render_email_html(md_text: str) -> str:
    """Convert render.py's Markdown output into a beautiful email-friendly HTML.

    Hand-parses the known structure rather than relying on python-markdown,
    which mishandles bold/italic inside <li> elements.
    """
    lines = md_text.split("\n")
    html_parts: list[str] = []
    i = 0
    n = len(lines)

    def peek(offset=0):
        j = i + offset
        return lines[j] if j < n else ""

    while i < n:
        line = lines[i]

        # --- Main title ---
        if line.startswith("# ") and not line.startswith("##"):
            html_parts.append(f"<h1>{_md_inline_to_html(line[2:].strip())}</h1>")
            i += 1
            continue

        # --- Subtitle / date line ---
        if line.startswith("_") and line.endswith("_"):
            html_parts.append(f"<p style='color:#586069;font-size:0.92em;'>{line.strip('_ ')}</p>")
            i += 1
            continue

        # --- Blockquote (degraded mode notice) ---
        if line.startswith("> "):
            bq_lines = []
            while i < n and (lines[i].startswith("> ") or (lines[i].strip() == "" and i + 1 < n and lines[i+1].startswith("> "))):
                if lines[i].startswith("> "):
                    bq_lines.append(lines[i][2:])
                elif lines[i].strip() == "":
                    bq_lines.append("")
                i += 1
            html_parts.append(f"<blockquote>{_md_inline_to_html('<br>'.join(bq_lines))}</blockquote>")
            continue

        # --- Horizontal rule ---
        if line.strip() == "---":
            html_parts.append("<hr>")
            i += 1
            continue

        # --- Section heading (## or ###) ---
        if line.startswith("## "):
            html_parts.append(f"<h2>{_md_inline_to_html(line[3:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("### "):
            html_parts.append(f"<h3>{_md_inline_to_html(line[4:].strip())}</h3>")
            i += 1
            continue

        # --- TOC section ---
        if line == "## 目录" or line == "## 目录"[:len(line)]:
            toc_items = []
            i += 1
            if i < n and lines[i].strip() == "":
                i += 1
            while i < n and lines[i].startswith("- ["):
                link_match = re.match(r'- \[(.+?)\]\((.+?)\)', lines[i])
                if link_match:
                    toc_items.append(f'<li><a href="{link_match.group(2)}">{link_match.group(1)}</a></li>')
                i += 1
            if toc_items:
                html_parts.append('<div class="toc"><ul>' + "\n".join(toc_items) + "</ul></div>")
            continue

        # --- Empty day notice ---
        if "今日无新论文" in line:
            html_parts.append(f"<p><em>{line}</em></p>")
            i += 1
            continue

        # --- Paper entry (starts with "- **") ---
        paper_match = re.match(r"- \*\*(.+?)\*\*\s*$", line)
        if paper_match:
            html_parts.append(_render_paper_block(lines, i))
            # Skip to after this paper block (find next "- **" or ## or EOF)
            i += 1
            while i < n:
                next_line = lines[i]
                # Next paper
                if re.match(r"- \*\*.+?\*\*\s*$", next_line):
                    break
                # Section header
                if next_line.startswith("#") or next_line.strip() == "---":
                    break
                # Footer
                if next_line.startswith("> Generated at"):
                    break
                i += 1
            continue

        # Fallback: treat as plain paragraph
        if line.strip():
            html_parts.append(f"<p>{_md_inline_to_html(line)}</p>")
        i += 1

    return "\n".join(html_parts)


def _render_paper_block(lines: list[str], start_idx: int) -> str:
    """Render a single paper block (from '- **Title**' to end of block).

    Returns the complete HTML for one .paper-card div.
    """
    parts: list[str] = []
    idx = start_idx

    # Line 0: - **English Title**
    title_m = re.match(r"- \*\*(.+?)\*\*", lines[idx])
    title_text = title_m.group(1).strip() if title_m else "Untitled"
    parts.append(f'<div class="paper-card">')
    parts.append(f'<div class="paper-title">{_md_inline_to_html(title_text)}</div>')
    idx += 1

    # Collect remaining lines until next block boundary
    meta_lines: list[str] = []   # authors, date, doi, etc.
    ai_summary = ""
    source_link = ""
    abstract_lines: list[str] = []  # labeled fields inside details
    in_abstract = False

    while idx < len(lines):
        raw = lines[idx]

        # Stop conditions
        if re.match(r"- \*\*.+?\*\*\s*$", raw) and not raw.startswith("  "):
            break
        if raw.startswith("#") or raw.strip() == "---":
            break
        if raw.startswith("> Generated at"):
            break

        stripped = raw.strip()

        # Skip blank lines between sections within the block
        if stripped == "":
            idx += 1
            continue

        # Italic line: could be Chinese title or authors
        italic_m = re.match(r"\s+\*([^*]+?)\*\s*$", raw)
        if italic_m and not raw.startswith("  **"):
            content = italic_m.group(1).strip()

            # Detect if this is a Chinese title (contains CJK) or authors (Latin names)
            has_cjk = bool(re.search(r'[\u4e00-\u9fff]', content))
            if has_cjk:
                parts.append(f'<div class="paper-title-zh">{_md_inline_to_html(content)}</div>')
            else:
                parts.append(f'<div class="paper-authors">{_md_inline_to_html(content)}</div>')
            idx += 1
            continue

        # Metadata line: `YYYY-MM` · `Vol.XX(I)` · `doi:10.xxxx/...`
        if ("`" in raw or "Vol." in raw or "doi:" in raw) and not raw.startswith("  **"):
            meta_html = _md_inline_to_html(stripped)
            parts.append(f'<div class="paper-meta">{meta_html}</div>')
            idx += 1
            continue

        # AI summary
        ai_m = re.match(r"\s+\*\*AI 总结[：:]\*\*\s*(.*)", raw)
        if ai_m:
            ai_summary = ai_m.group(1).strip()
            idx += 1
            continue

        # Source link
        src_m = re.match(r"\s+\*\*原文链接[：:]\*\*\s*\[Source\]\(([^)]+)\)", raw)
        if src_m:
            source_link = src_m.group(1)
            idx += 1
            continue

        # Abstract label
        abs_m = re.match(r"\s+\*\*Abstract[：:]?\*\*\s*(.*)", raw)
        if abs_m:
            in_abstract = True
            if abs_m.group(1).strip():
                abstract_lines.append(f"<strong>Abstract:</strong> {_md_inline_to_html(abs_m.group(1).strip())}")
            idx += 1
            continue

        # 中文翻译 label
        zh_abs_m = re.match(r"\s+\*\*中文翻译[：:]?\*\*\s*(.*)", raw)
        if zh_abs_m:
            in_abstract = True
            if zh_abs_m.group(1).strip():
                abstract_lines.append(f"<strong>中文翻译：</strong> {_md_inline_to_html(zh_abs_m.group(1).strip())}")
            idx += 1
            continue

        # 摘要缺失
        if "[摘要缺失]" in raw or "摘要缺失" in raw:
            in_abstract = True
            abstract_lines.append("<strong>Abstract:</strong> <em>[摘要缺失]</em>")
            idx += 1
            continue

        # <details>/<summary> tags — skip them
        if re.match(r"\s*<details?", raw) or re.match(r"\s*</details>", raw):
            idx += 1
            continue
        if re.match(r"\s*<summary>", raw):
            idx += 1
            continue

        # Continuation of abstract content (indented text)
        if in_abstract and raw.startswith("  ") and stripped:
            abstract_lines.append(f"<p>{_md_inline_to_html(stripped)}</p>")
            idx += 1
            continue

        # Other indented content (not yet categorized)
        if raw.startswith("  ") and stripped and in_abstract:
            abstract_lines.append(f"<p>{_md_inline_to_html(stripped)}</p>")
            idx += 1
            continue

        # Unknown non-indented line — probably end of block
        if not raw.startswith(" "):
            break

        idx += 1

    # AI summary
    if ai_summary:
        parts.append(f'<div class="paper-ai"><strong>AI 总结：</strong>{_md_inline_to_html(ai_summary)}</div>')

    # Source link
    if source_link:
        parts.append(f'<div class="paper-link"><strong>原文链接：</strong><a href="{source_link}">Source</a></div>')

    # Abstract block
    if abstract_lines:
        abs_content = "\n".join(abstract_lines)
        parts.append(f'<div class="paper-abstract">{abs_content}</div>')

    parts.append("</div>")  # close .paper-card
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Legacy fallback (used only as last resort)
# ---------------------------------------------------------------------------
def _render_fallback_md(text: str) -> str:
    """Basic Markdown → HTML conversion used when custom renderer isn't available."""
    # Strip details/summary
    text = re.sub(r"^\s*<details[^>]*>\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*<summary>.*?</summary>\s*\n?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*</details>\s*\n?", "", text, flags=re.MULTILINE)

    if _HAS_MD:
        return markdown.markdown(text, extensions=["extra", "nl2br", "sane_lists"])

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
    password_raw = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ.get("SMTP_FROM", username)
    to_addrs = [a.strip() for a in os.environ["NOTIFY_EMAIL"].split(",") if a.strip()]

    # Sanitize password: remove non-ASCII chars and whitespace
    password = unicodedata.normalize("NFKC", password_raw).strip().replace(" ", "")

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

    # Plain-text version (original markdown)
    msg.attach(MIMEText(report_content, "plain", "utf-8"))

    # HTML version — use custom renderer
    try:
        html_body = _render_email_html(report_content)
    except Exception:
        print("[WARN] Custom HTML renderer failed, falling back to basic conversion")
        html_body = _render_fallback_md(report_content)

    html_page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
{_EMAIL_CSS}
</style></head><body>
{html_body}
<div class="footer">Generated by quant-marketing-daily</div>
</body></html>"""
    msg.attach(MIMEText(html_page, "html", "utf-8"))

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
