"""HTML → PDF rendering and Excel → PDF on macOS."""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_EXCEL_APP = Path("/Applications/Microsoft Excel.app")


def is_packaged_app() -> bool:
    return bool(os.environ.get("LEADS_BUNDLE_BASE")) or getattr(sys, "frozen", False)


def xlsx_bytes_to_pdf_mac(xlsx_bytes: bytes, *, timeout: int = 120) -> Optional[bytes]:
    """Export workbook bytes to PDF via Microsoft Excel (macOS). Matches Excel Print layout."""
    if sys.platform != "darwin" or not _EXCEL_APP.is_dir():
        return None
    with tempfile.TemporaryDirectory() as tmp:
        xlsx = Path(tmp) / "export.xlsx"
        pdf = Path(tmp) / "export.pdf"
        xlsx.write_bytes(xlsx_bytes)
        script = f'''
tell application "Microsoft Excel"
    set xlsxPath to POSIX file "{xlsx}"
    set pdfPath to POSIX file "{pdf}"
    open xlsxPath
    save workbook as active workbook filename pdfPath file format PDF file format
    close active workbook saving no
end tell
'''
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            log.warning("Excel PDF export timed out or failed: %s", exc)
            return None
        if result.returncode != 0:
            log.warning(
                "Excel PDF export failed (exit %s): %s",
                result.returncode,
                (result.stderr or result.stdout or "").strip()[:300],
            )
            return None
        if not pdf.is_file() or pdf.stat().st_size < 500:
            return None
        return pdf.read_bytes()


def prepare_html_for_local_pdf(html: str, base: Path) -> str:
    """Inline local CSS and rewrite /static/ asset URLs for headless Chromium."""
    base = base.resolve()
    static_uri = (base / "static").as_uri() + "/"

    def _inline_stylesheet(match: re.Match[str]) -> str:
        href = match.group(1)
        if href.startswith("static/"):
            css_path = base / href
            if css_path.is_file():
                return f"<style>\n{css_path.read_text(encoding='utf-8')}\n</style>"
        if href.startswith("/static/"):
            css_path = base / href.lstrip("/")
            if css_path.is_file():
                return f"<style>\n{css_path.read_text(encoding='utf-8')}\n</style>"
        return match.group(0)

    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*/?>',
        _inline_stylesheet,
        html,
        flags=re.IGNORECASE,
    )
    html = html.replace('src="/static/', f'src="{static_uri}')
    html = html.replace("src='/static/", f"src='{static_uri}")
    return html


def render_html_to_pdf(html: str, *, base: Path) -> Optional[bytes]:
    """Render HTML to PDF using headless Chromium (Playwright). Skipped in packaged app."""
    if is_packaged_app():
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.debug("playwright not installed")
        return None

    prepared = prepare_html_for_local_pdf(html, base)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.set_content(prepared, wait_until="networkidle")
                return page.pdf(
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "12mm",
                        "right": "14mm",
                        "bottom": "12mm",
                        "left": "14mm",
                    },
                )
            finally:
                browser.close()
    except Exception as exc:
        log.warning("Playwright PDF render failed: %s", exc)
        return None
