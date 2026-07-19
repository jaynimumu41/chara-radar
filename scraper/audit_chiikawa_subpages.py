"""Audit Chiikawa official homepage p26 subpages.

The scraper intentionally favors accuracy over coverage. This tool does not add
events by itself; it lists official child pages linked from chiikawa-info.jp and
marks whether each page is already represented in data/events.json, explicitly
ignored, or still needs human review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

from verify_links import fetch_html


BASE_URL = "https://chiikawa-info.jp/"
HOME_URL = "https://chiikawa-info.jp/index.html"
PUS_URL = "https://chiikawa-info.jp/pus.html"
EVENTS_JSON = Path(__file__).parent.parent / "data" / "events.json"

# Add pages here only after a human has checked that they are out of scope for
# this project, e.g. pure online content, non-JP/TW, no physical sale/event, or
# an expired historical notice intentionally left on the homepage.
IGNORED_P26_PAGES: dict[str, str] = {
    "https://chiikawa-info.jp/p26/ck_tokyo/index.html": (
        "2026-02-06 handling-start page with no current event end date; "
        "outside the new_product freshness window"
    ),
}

RAW_P26_URL_RE = re.compile(
    r"https?://chiikawa-info\.jp/p26/[^\s\"'<>)]*(?:index\.html|/)",
    re.I,
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*p26/[^)]*)\)", re.I)
HTML_TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(r"20\d{2}年\d{1,2}月\d{1,2}日")
DATE_RANGE_RE = re.compile(
    r"20\d{2}年\d{1,2}月\d{1,2}日(?:\([^)]*\))?\s*[〜～~-]\s*"
    r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日"
)
COLLECTIBLE_RE = re.compile(
    r"POP\s*UP|ポップアップ|期間限定|限定|グッズ|商品|STORE|SHOP|ショップ|"
    r"ちいかわらんど|レストラン|カフェ|メニュー|オープン|物販|ノベルティ",
    re.I,
)
VENUE_RE = re.compile(
    r"会場|場所|住所|所在地|店|店舗|館|階|F\b|モール|イオン|百貨店|"
    r"PARCO|パルコ|空港|駅|華山|園區|園区|西街",
    re.I,
)


@dataclass(frozen=True)
class ChiikawaLink:
    url: str
    title: str = ""


@dataclass(frozen=True)
class PageSignals:
    has_date: bool
    has_date_range: bool
    has_collectible: bool
    has_venue: bool

    @property
    def labels(self) -> list[str]:
        labels: list[str] = []
        if self.has_date:
            labels.append("date")
        if self.has_date_range:
            labels.append("date_range")
        if self.has_collectible:
            labels.append("collectible")
        if self.has_venue:
            labels.append("venue")
        return labels


@dataclass(frozen=True)
class AuditRow:
    status: str
    url: str
    title: str
    reason: str
    risk: str
    signals: PageSignals
    event_ids: tuple[str, ...] = ()


class _P26HTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self._active_url = ""
        self._active_text: list[str] = []
        self.links: list[ChiikawaLink] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        url = normalize_p26_url(href, self.base_url)
        if url:
            self._active_url = url
            self._active_text = []

    def handle_data(self, data):
        if self._active_url and data:
            self._active_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._active_url:
            return
        title = _clean_text(" ".join(self._active_text))
        self.links.append(ChiikawaLink(self._active_url, title))
        self._active_url = ""
        self._active_text = []


def normalize_p26_url(raw_url: str, base_url: str = BASE_URL) -> str:
    if not raw_url:
        return ""
    raw_url = html.unescape(raw_url.strip())
    url = urljoin(base_url, raw_url)
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host != "chiikawa-info.jp":
        return ""
    path = parsed.path
    if "/p26/" not in path:
        return ""
    if path.endswith("/"):
        path += "index.html"
    if not path.endswith("/index.html"):
        return ""
    return urlunparse(("https", "chiikawa-info.jp", path, "", "", ""))


def _clean_text(text: str) -> str:
    text = HTML_TAG_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def is_ended_listing_title(title: str) -> bool:
    return "【終了】" in (title or "")


def extract_p26_links(text: str, base_url: str = HOME_URL) -> list[ChiikawaLink]:
    """Extract and normalize chiikawa-info.jp/p26/.../index.html links."""
    found: dict[str, str] = {}

    parser = _P26HTMLParser(base_url)
    parser.feed(text or "")
    for link in parser.links:
        if link.url not in found or (link.title and not found[link.url]):
            found[link.url] = link.title

    for title, href in MARKDOWN_LINK_RE.findall(text or ""):
        url = normalize_p26_url(href, base_url)
        if url and (url not in found or (title and not found[url])):
            found[url] = _clean_text(title)

    for raw in RAW_P26_URL_RE.findall(text or ""):
        url = normalize_p26_url(raw, base_url)
        if url and url not in found:
            found[url] = ""

    return [ChiikawaLink(url, title) for url, title in sorted(found.items())]


def load_parsed_event_pages(events_path: Path = EVENTS_JSON) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    if not events_path.exists():
        return parsed
    events = json.loads(events_path.read_text(encoding="utf-8"))
    for event in events:
        if event.get("brand") != "chiikawa":
            continue
        url = normalize_p26_url(event.get("sourceUrl", ""))
        if not url:
            continue
        parsed.setdefault(url, []).append(event.get("id", ""))
    return parsed


def strip_visible_text(page_text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", page_text or "", flags=re.I)
    text = HTML_TAG_RE.sub(" ", text)
    return _clean_text(text)


def detect_signals(page_text: str) -> PageSignals:
    visible = strip_visible_text(page_text)
    return PageSignals(
        has_date=bool(DATE_RE.search(visible)),
        has_date_range=bool(DATE_RANGE_RE.search(visible)),
        has_collectible=bool(COLLECTIBLE_RE.search(visible)),
        has_venue=bool(VENUE_RE.search(visible)),
    )


def _risk_for(status: str, signals: PageSignals) -> str:
    if status != "needs_review":
        return "-"
    if signals.has_date_range and signals.has_collectible and signals.has_venue:
        return "high"
    if signals.has_date and (signals.has_collectible or signals.has_venue):
        return "medium"
    return "low"


def audit_links(
    links: list[ChiikawaLink],
    parsed_pages: dict[str, list[str]] | None = None,
    ignored_pages: dict[str, str] | None = None,
    details_by_url: dict[str, str] | None = None,
) -> list[AuditRow]:
    parsed_pages = parsed_pages or {}
    ignored_pages = ignored_pages or {}
    details_by_url = details_by_url or {}
    rows: list[AuditRow] = []
    for link in links:
        if link.url in parsed_pages:
            status = "parsed"
            reason = "represented by chiikawa event sourceUrl"
        elif link.url in ignored_pages:
            status = "ignored"
            reason = ignored_pages[link.url]
        else:
            status = "needs_review"
            reason = "homepage links this official p26 page, but no current event sourceUrl covers it"
        signals = detect_signals(details_by_url.get(link.url, link.title))
        rows.append(AuditRow(
            status=status,
            url=link.url,
            title=link.title,
            reason=reason,
            risk=_risk_for(status, signals),
            signals=signals,
            event_ids=tuple(parsed_pages.get(link.url, ())),
        ))
    return rows


def fetch_homepage_links() -> list[ChiikawaLink]:
    home_text = fetch_html(HOME_URL) or fetch_html(BASE_URL)
    cache_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    pus_text = fetch_html(f"{PUS_URL}?chara_radar={cache_key}")
    if not home_text and not pus_text:
        raise RuntimeError("failed to fetch Chiikawa official homepage")
    found: dict[str, ChiikawaLink] = {}
    for text, base_url in ((home_text, HOME_URL), (pus_text, PUS_URL)):
        for link in extract_p26_links(text or "", base_url):
            if is_ended_listing_title(link.title):
                continue
            if link.url not in found or (link.title and not found[link.url].title):
                found[link.url] = link
    return [found[url] for url in sorted(found)]


def fetch_review_details(links: list[ChiikawaLink], parsed_pages: dict[str, list[str]]) -> dict[str, str]:
    details: dict[str, str] = {}
    for link in links:
        if link.url in parsed_pages:
            continue
        details[link.url] = fetch_html(link.url) or link.title
    return details


def _format_markdown(rows: list[AuditRow]) -> str:
    counts = {status: sum(1 for row in rows if row.status == status)
              for status in ("parsed", "ignored", "needs_review")}
    lines = [
        "# Chiikawa official p26 subpage audit",
        "",
        f"- source: {HOME_URL}",
        f"- found: {len(rows)}",
        f"- parsed: {counts['parsed']}",
        f"- ignored: {counts['ignored']}",
        f"- needs_review: {counts['needs_review']}",
        "",
        "| status | risk | signals | title | url | reason | eventIds |",
        "| -- | -- | -- | -- | -- | -- | -- |",
    ]
    for row in rows:
        signals = ", ".join(row.signals.labels) or "-"
        title = row.title.replace("|", "\\|") if row.title else "-"
        event_ids = ", ".join(eid for eid in row.event_ids if eid) or "-"
        lines.append(
            f"| {row.status} | {row.risk} | {signals} | {title} | "
            f"{row.url} | {row.reason.replace('|', '/')} | {event_ids} |"
        )
    return "\n".join(lines)


def _format_text(rows: list[AuditRow]) -> str:
    lines = []
    for row in rows:
        signals = ",".join(row.signals.labels) or "-"
        title = f" {row.title}" if row.title else ""
        lines.append(f"[{row.status} risk={row.risk} signals={signals}]{title}\n  {row.url}\n  {row.reason}")
    return "\n".join(lines)


def _format_json(rows: list[AuditRow]) -> str:
    payload = [
        {
            "status": row.status,
            "risk": row.risk,
            "signals": row.signals.labels,
            "title": row.title,
            "url": row.url,
            "reason": row.reason,
            "eventIds": list(row.event_ids),
        }
        for row in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Audit Chiikawa official homepage p26 subpages.")
    parser.add_argument("--format", choices=("markdown", "text", "json"), default="markdown")
    parser.add_argument("--no-fetch-details", action="store_true",
                        help="Only inspect homepage links; do not fetch unparsed child pages for signal hints.")
    parser.add_argument("--fail-on-review", action="store_true",
                        help="Exit 2 when any high/medium risk needs_review page is found.")
    args = parser.parse_args()

    links = fetch_homepage_links()
    parsed_pages = load_parsed_event_pages()
    details = {} if args.no_fetch_details else fetch_review_details(links, parsed_pages)
    rows = audit_links(links, parsed_pages, IGNORED_P26_PAGES, details)

    if args.format == "json":
        print(_format_json(rows))
    elif args.format == "text":
        print(_format_text(rows))
    else:
        print(_format_markdown(rows))

    risky = [row for row in rows if row.status == "needs_review" and row.risk in {"high", "medium"}]
    if args.fail_on_review and risky:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
