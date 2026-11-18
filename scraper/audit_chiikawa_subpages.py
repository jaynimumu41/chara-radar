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

from official_sources import (
    _CHIIKAWA_MOVIE_POPUP,
    _chiikawa_movie_popup_events_from_text,
    _chiikawa_popup_detail_fields,
    _document_title,
)
from verify_links import fetch_html


BASE_URL = "https://chiikawa-info.jp/"
HOME_URL = "https://chiikawa-info.jp/index.html"
PUS_URL = "https://chiikawa-info.jp/pus.html"
PUS_FALLBACK_URL = "https://chiikawa-info.jp/pus"
EVENTS_JSON = Path(__file__).parent.parent / "data" / "events.json"

# Add pages here only after a human has checked that they are out of scope for
# this project, e.g. pure online content, non-JP/TW, no physical sale/event, or
# an expired historical notice intentionally left on the homepage.
IGNORED_P26_PAGES: dict[str, str] = {
    "https://chiikawa-info.jp/p26/ck_movie/index.html": (
        "aggregate movie-goods page: bounded goods and popup schedules use structured parsers; remaining permanent/broad retail listings are out of scope"
    ),
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
    r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日(?:\([^)]*\))?"
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
        self._pending_url = ""
        self._pending_title = ""
        self._pending_tail: list[str] = []
        self.links: list[ChiikawaLink] = []

    def _flush_pending(self):
        if not self._pending_url:
            return
        title = self._pending_title
        trailing = _clean_text(" ".join(self._pending_tail))
        schedule = DATE_RANGE_RE.search(trailing)
        if schedule and not DATE_RANGE_RE.search(title):
            title = f"{title}({schedule.group(0)})"
        self.links.append(ChiikawaLink(self._pending_url, title))
        self._pending_url = ""
        self._pending_title = ""
        self._pending_tail = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        # Official PUS cards put the bounded schedule immediately after the
        # linked heading.  Preserve that context before starting the next
        # card, including when reader markdown was converted to light HTML.
        self._flush_pending()
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
        elif self._pending_url and data:
            self._pending_tail.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._active_url:
            return
        title = _clean_text(" ".join(self._active_text))
        self._pending_url = self._active_url
        self._pending_title = title
        self._pending_tail = []
        self._active_url = ""
        self._active_text = []

    def close(self):
        super().close()
        self._flush_pending()


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
    parser.close()
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
    from official_sources import CLINIC_BASE, CLINIC_VENUES
    events = json.loads(events_path.read_text(encoding="utf-8"))
    clinic_ids: dict[str, list[str]] = {}
    clinic_parent = CLINIC_BASE + "index.html"
    for event in events:
        if event.get("brand") != "chiikawa":
            continue
        source_url = event.get("sourceUrl", "")
        source_parts = urlparse(source_url)
        if source_parts.path == urlparse(clinic_parent).path:
            slug = source_parts.fragment
            if slug in CLINIC_VENUES:
                clinic_ids.setdefault(slug, []).append(event.get("id", ""))
            # A parent URL represents full coverage only when every venue
            # fragment is present; never let one fragment mark it parsed.
            continue
        clinic_prefix = urlparse(CLINIC_BASE).path
        if source_parts.path.startswith(clinic_prefix) and source_parts.path.endswith(".html"):
            slug = source_parts.path.rsplit("/", 1)[-1][:-5]
            if slug in CLINIC_VENUES:
                clinic_ids.setdefault(slug, []).append(event.get("id", ""))
        url = normalize_p26_url(source_url)
        if not url:
            continue
        parsed.setdefault(url, []).append(event.get("id", ""))
    if set(clinic_ids) == set(CLINIC_VENUES):
        parsed[clinic_parent] = [
            event_id
            for slug in sorted(CLINIC_VENUES)
            for event_id in clinic_ids[slug]
        ]
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


def _structured_schedule_expiry_reason(url: str, detail: str, today: str) -> str:
    """Ignore a schedule page only when every parsed venue has explicitly ended."""
    if normalize_p26_url(url) != normalize_p26_url(_CHIIKAWA_MOVIE_POPUP):
        return ""
    all_events = _chiikawa_movie_popup_events_from_text(
        detail, today="1900-01-01")
    if not all_events or any(
        not event.get("endDate") or event["endDate"] >= today
        for event in all_events
    ):
        return ""
    latest_end = max(event["endDate"] for event in all_events)
    return f"all structured official venue schedules ended by {latest_end}"


def audit_links(
    links: list[ChiikawaLink],
    parsed_pages: dict[str, list[str]] | None = None,
    ignored_pages: dict[str, str] | None = None,
    details_by_url: dict[str, str] | None = None,
    today: str | None = None,
) -> list[AuditRow]:
    parsed_pages = parsed_pages or {}
    ignored_pages = ignored_pages or {}
    details_by_url = details_by_url or {}
    today = today or datetime.now().astimezone().date().isoformat()
    rows: list[AuditRow] = []
    for link in links:
        detail = details_by_url.get(link.url, link.title)
        detail_title = _document_title(detail)
        display_title = detail_title or link.title
        popup_fields = _chiikawa_popup_detail_fields(detail)
        schedule_expiry_reason = _structured_schedule_expiry_reason(
            link.url, detail, today)
        if link.url in parsed_pages:
            status = "parsed"
            reason = "represented by chiikawa event sourceUrl"
        elif link.url in ignored_pages:
            status = "ignored"
            reason = ignored_pages[link.url]
        elif schedule_expiry_reason:
            status = "ignored"
            reason = schedule_expiry_reason
        elif popup_fields and popup_fields[2] < today:
            status = "ignored"
            reason = f"official event ended {popup_fields[2]}"
        else:
            status = "needs_review"
            reason = "homepage links this official p26 page, but no current event sourceUrl covers it"
        signals = detect_signals(detail)
        rows.append(AuditRow(
            status=status,
            url=link.url,
            title=display_title,
            reason=reason,
            risk=_risk_for(status, signals),
            signals=signals,
            event_ids=tuple(parsed_pages.get(link.url, ())),
        ))
    return rows


def fetch_homepage_links() -> list[ChiikawaLink]:
    home_text = fetch_html(HOME_URL) or fetch_html(BASE_URL)
    # Use the canonical PUS URL so the reader may reuse its last valid cache.
    # Both independent listings must be live and parseable; accepting the
    # homepage alone would silently lose the much larger POP UP inventory.
    pus_text = fetch_html(PUS_URL)
    if not pus_text:
        # The official site exposes the same listing without the legacy .html
        # suffix.  This route often remains readable when one reader cache is
        # temporarily throttled; both routes still fail closed below.
        pus_text = fetch_html(PUS_FALLBACK_URL)
    if not home_text:
        raise RuntimeError("failed to fetch Chiikawa official homepage")
    if not pus_text:
        raise RuntimeError("failed to fetch Chiikawa official POP UP listing")
    found: dict[str, ChiikawaLink] = {}
    for text, base_url in ((home_text, HOME_URL), (pus_text, PUS_URL)):
        source_links = extract_p26_links(text, base_url)
        if not source_links:
            raise RuntimeError(
                f"official Chiikawa source returned no p26 links: {base_url}"
            )
        for link in source_links:
            if is_ended_listing_title(link.title):
                continue
            if link.url not in found or (link.title and not found[link.url].title):
                found[link.url] = link
    if not found:
        raise RuntimeError("official Chiikawa sources returned no p26 links; coverage cannot be verified")
    return [found[url] for url in sorted(found)]


def fetch_review_details(
    links: list[ChiikawaLink],
    parsed_pages: dict[str, list[str]],
    *,
    today: str | None = None,
) -> dict[str, str]:
    today = today or datetime.now().astimezone().date().isoformat()
    details: dict[str, str] = {}
    for link in links:
        if link.url in parsed_pages or link.url in IGNORED_P26_PAGES:
            continue
        # The official PUS listing title itself carries a complete bounded
        # schedule.  If it already proves the venue is over, no child request
        # is needed; current or dateless pages still fail closed below.
        listing_detail = f"<title>{link.title}</title>"
        listing_fields = _chiikawa_popup_detail_fields(listing_detail)
        if listing_fields and listing_fields[2] < today:
            details[link.url] = listing_detail
            continue
        detail = fetch_html(link.url)
        if not detail:
            raise RuntimeError(
                f"failed to fetch unclassified Chiikawa official detail: {link.url}"
            )
        details[link.url] = detail
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
