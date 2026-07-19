"""Audit official Pokemon and Miffy source coverage.

This tool is intentionally read-only. It compares official listing pages against
data/events.json and reports pages that look like physical store, goods, popup,
or cafe information but are not represented by a current event sourceUrl.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import official_sources
import scrape
from verify_links import fetch_html


EVENTS_JSON = Path(__file__).parent.parent / "data" / "events.json"

POKEMON_CAFE_NEWS = "https://www.pokemon-cafe.jp/ja/cafe/news/"
POKEMON_SHOP_LIST = "https://www.pokemon.co.jp/shop/"
POKEMON_TW_GOODS = "https://tw.portal-pokemon.com/goods/?p=1"
MIFFY_EVENT = "https://dickbruna.jp/event/"
MIFFY_NEWS = "https://dickbruna.jp/news/"
KIDDY_MIFFY_SEARCH = "https://www.kiddyland.co.jp/?s=miffy"

OFFICIAL_HOSTS = {
    "www.pokemon-cafe.jp",
    "shop.pokemon.co.jp",
    "tw.portal-pokemon.com",
    "dickbruna.jp",
    "www.kiddyland.co.jp",
}

# Pages here are official but either duplicate a richer canonical event source,
# or are known out-of-scope after human review.
IGNORED_OFFICIAL_PAGES: dict[str, str] = {
    "https://www.pokemon-cafe.jp/ja/cafe/news/260619_3441.html": (
        "Pokemon Cafe seat reservation schedule, not an event or goods launch"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260601_3427.html": (
        "Pokemon Cafe seat reservation schedule, not an event or goods launch"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260529_3387.html": (
        "same 2026-06-17 Pokemon Cafe menu/show renewal represented by 260529_3377"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260525_3429.html": (
        "Pokemon Cafe reservation-system maintenance notice"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260514_3419.html": (
        "Pokemon Cafe reservation-system maintenance notice"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260511_3376.html": (
        "same Pokemon Cafe TOKYO renewal represented by 260529_3377"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260511_3404.html": (
        "same Pokemon Cafe TOKYO renewal represented by 260529_3377"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260424_3386.html": (
        "Pokemon Cafe Osaka temporary-closure and reservation notice; menu renewal covered by 260529_3377"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260209_3368.html": (
        "old Pokemon Cafe TOKYO closure notice; reopening represented by 260529_3377"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/260122_3369.html": (
        "Pokemon Cafe one-day closure notice"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/251126_3329.html": (
        "Pokemon Cafe holiday business-hours notice"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/251107_3304.html": (
        "historical Pokemon Cafe menu/tableware update outside current freshness window"
    ),
    "https://www.pokemon-cafe.jp/ja/cafe/news/251017_3303.html": (
        "historical Pokemon Cafe placemat/coaster update outside current freshness window"
    ),
    "https://tw.portal-pokemon.com/goods/post-5937/": (
        "apparel/medical uniform licensed product; not a target physical-store event"
    ),
    "https://tw.portal-pokemon.com/goods/post-5343/": (
        "game music jukebox product, excluded by game/music rule"
    ),
    "https://tw.portal-pokemon.com/goods/post-5286/": (
        "online jewelry product page, not a POP UP Promotion or Pokemon Center TAIPEI launch"
    ),
    "https://tw.portal-pokemon.com/goods/post-4794/": (
        "broad online furniture product page, not a Pokemon Center TAIPEI launch"
    ),
    "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-shibuya/news/202607/000413.html": (
        "Pokemon Design Lab crowd-control and advance-lottery guidance, not a new event or product launch"
    ),
    "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-shibuya/news/202607/000399.html": (
        "temporary Pokemon Design Lab service suspension notice"
    ),
    "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-shibuya/events/202607/000394.html": (
        "media-focused product presentation with only a small public lottery allocation; excluded conservatively"
    ),
    "https://dickbruna.jp/news/202607/47193/": (
        "general Liberty Fabrics collaboration goods, not a venue-bounded popup or store event"
    ),
    "https://dickbruna.jp/news/202606/46872/": (
        "open-ended Flower Miffy stock-limited birthday campaign aged out with no current availability confirmation"
    ),
    "https://dickbruna.jp/news/202606/46833/": (
        "Miffy zakka Festa season schedule overview; individual venue pages are parsed when detailed dates publish"
    ),
    "https://dickbruna.jp/news/202605/46046/": (
        "expired Yokohama Nature Week outdoor event, not current target coverage"
    ),
    "https://www.kiddyland.co.jp/miffy_style/": (
        "miffy style top page, not a single event or product page"
    ),
    "https://www.kiddyland.co.jp/event/miffy_tokyo20260704/": (
        "same-day miffy style single-product page covered by the 2026-07-04 novelty campaign"
    ),
    "https://www.kiddyland.co.jp/event/miffy_20260704/": (
        "same-day miffy style single-product page covered by the 2026-07-04 novelty campaign"
    ),
    "https://www.kiddyland.co.jp/event/miffy_20260606/": (
        "same-day miffy style single-product page covered by Birthday Fair 2026"
    ),
    "https://www.kiddyland.co.jp/event/miffystyle_birthday2026/": (
        "same Birthday Fair represented by dickbruna.jp/news/202606/46398/"
    ),
    "https://www.kiddyland.co.jp/event/miffy_nove202605/": (
        "previous miffy style novelty day outside current freshness window"
    ),
    "https://www.kiddyland.co.jp/event/miffy_20260502/": (
        "previous miffy style same-day single-product page outside current freshness window"
    ),
    "https://www.kiddyland.co.jp/event/miffy_20260424/": (
        "previous miffy style single-product page outside current freshness window"
    ),
    "https://www.kiddyland.co.jp/event/miffy_harajuku202604/": (
        "past miffy style Harajuku opening/reservation notice, not a current event"
    ),
}

DATE_RE = re.compile(
    r"20\d{2}[./-]\d{1,2}[./-]\d{1,2}|"
    r"20\d{2}年\d{1,2}月\d{1,2}日|"
    r"\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}"
)
DATE_RANGE_RE = re.compile(
    r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日[^。\n]{0,35}"
    r"(?:[〜～~\-]|から|より)[^。\n]{0,35}"
    r"(?:20\d{2}年)?\d{1,2}月\d{1,2}日|"
    r"\d{1,2}/\d{1,2}[^。\n]{0,20}[〜～~\-][^。\n]{0,20}\d{1,2}/\d{1,2}"
)
COLLECTIBLE_RE = re.compile(
    r"POP\s*UP|ポップアップ|ストア|ショップ|STORE|SHOP|カフェ|Cafe|"
    r"メニュー|グッズ|商品|発売|販売|受注|ノベルティ|フェア|キャンペーン|"
    r"リニューアル|OPEN|オープン|予約商品",
    re.I,
)
VENUE_RE = re.compile(
    r"店|店舗|会場|ポケモンセンター|Pok[eé]mon Cafe|Pokemon Cafe|"
    r"miffy style|キデイランド|Flower Miffy|フラワーミッフィー|"
    r"東京|大阪|神戸|台北|日本橋|原宿|PARCO|高島屋|松坂屋|"
    r"サンシャイン|ルクア|浅草|梅田|心斎橋",
    re.I,
)
ALWAYS_IGNORE_RE = re.compile(
    r"カードゲーム|ポケモンカード|ポケカ|抽選販売商品|当選者|販売方法について|"
    r"ゲーム教室|グリーティング|なりきりサマー|ポケモンフレンダ|フレンダ|"
    r"店頭大会|ミュウツーバトル|わくわく大冒険|ビンゴラリー|"
    r"#キミにあえた|ご来店予定|来店予定|ご来店のお客様へ|"
    r"整理券|入場制限|入場整理券|付録|宝島社|BOOK|メッセージを送ろう|"
    r"シャンブル|LINE|Tシャツ|Ｔシャツ|T-shirt|tee|ユニクロ|UNIQLO|"
    r"Game Music|Jukebox|遊戲音樂機|音樂機|刷手衣|刷手服|醫療服",
    re.I,
)
CONDITIONAL_IGNORE_RE = re.compile(
    r"メンテナンス|休業|営業時間|お詫び|延期|入店方法|配送遅れ|"
    r"Pok[eé]mon GO|ポケモンGO|アプリ",
    re.I,
)


@dataclass(frozen=True)
class OfficialCandidate:
    brand: str
    source: str
    url: str
    title: str = ""
    published: str = ""
    meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PageSignals:
    has_date: bool
    has_date_range: bool
    has_collectible: bool
    has_venue: bool
    start_date: str = ""
    end_date: str = ""
    auto_ignore_reason: str = ""

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
        if self.start_date:
            labels.append(f"start:{self.start_date}")
        if self.end_date:
            labels.append(f"end:{self.end_date}")
        if self.auto_ignore_reason:
            labels.append("auto_ignore")
        return labels


@dataclass(frozen=True)
class AuditRow:
    brand: str
    source: str
    status: str
    risk: str
    title: str
    url: str
    reason: str
    signals: PageSignals
    event_ids: tuple[str, ...] = ()
    published: str = ""


class _AnchorCollector(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._active_url = ""
        self._active_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        href = ""
        for key, value in attrs:
            if key.lower() == "href" and value:
                href = value
                break
        if href:
            self._active_url = urljoin(self.base_url, html.unescape(href))
            self._active_text = []

    def handle_data(self, data):
        if self._active_url and data:
            self._active_text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._active_url:
            return
        self.links.append((self._active_url, clean_text(" ".join(self._active_text))))
        self._active_url = ""
        self._active_text = []


def clean_text(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def normalize_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    url = urldefrag(html.unescape(raw_url.strip()))[0]
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    host = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunparse(("https", host, path, "", parsed.query, ""))


def _official_url(raw_url: str) -> str:
    url = normalize_url(raw_url)
    host = urlparse(url).netloc
    return url if host in OFFICIAL_HOSTS else ""


def extract_links(text: str, base_url: str) -> list[tuple[str, str]]:
    found: dict[str, str] = {}

    parser = _AnchorCollector(base_url)
    parser.feed(text or "")
    for raw_url, title in parser.links:
        url = _official_url(raw_url)
        if url and (url not in found or (title and not found[url])):
            found[url] = title

    for title, raw_url in re.findall(r"\[([^\]]*)\]\((https?://[^)\s]+)\)", text or ""):
        url = _official_url(raw_url)
        if url and (url not in found or (title and not found[url])):
            found[url] = clean_text(title)

    for raw_url in re.findall(r"https?://[^\s\"'<>)]*(?:/|\.html)", text or ""):
        url = _official_url(raw_url)
        if url and url not in found:
            found[url] = ""

    return list(found.items())


def _page_text(url: str) -> str:
    return fetch_html(url) or official_sources._proxy_markdown(url)


def _page_title(page_text: str) -> str:
    for pattern in (
        r"<h1[^>]*>([\s\S]*?)</h1>",
        r'<meta property="og:title" content="([^"]*)"',
        r"<title[^>]*>([\s\S]*?)</title>",
        r"^#\s+(.+)$",
    ):
        m = re.search(pattern, page_text or "", re.I | re.M)
        if m:
            return clean_text(m.group(1))
    visible = clean_text(page_text)
    for sep in ("｜ニュース｜", " | 商品 |", " | dickbruna.jp"):
        if sep in visible:
            return visible.split(sep, 1)[0].strip()[:160]
    return ""


def _candidate_title(candidate: OfficialCandidate, page_text: str) -> str:
    title = _page_title(page_text)
    if title:
        return title
    return candidate.title


def _signal_text(candidate: OfficialCandidate, page_text: str, title: str) -> str:
    visible = clean_text(page_text)
    anchors = [title, candidate.title]
    for anchor in anchors:
        anchor = clean_text(anchor)
        if not anchor:
            continue
        needle = anchor[: min(40, len(anchor))]
        idx = visible.find(needle)
        if idx >= 0:
            visible = visible[idx:idx + 4500]
            break
    for marker in (
        "関連記事", "最新の記事", "この記事をシェアする", "ネット通販",
        "ニュースカテゴリー", "ポケモンセンター公式 SNS", "その他のニュース",
        "OTHER NEWS", "RECOMMEND",
    ):
        idx = visible.find(marker)
        if idx >= 0:
            visible = visible[:idx]
    return "\n".join(part for part in (title, candidate.title, visible) if part)


def _is_expired(signals: PageSignals) -> bool:
    today = date.today().isoformat()
    if signals.end_date:
        return signals.end_date < today
    return False


def detect_signals(text: str, *, ref_year: int | None = None,
                   ignore_text: str | None = None) -> PageSignals:
    visible = clean_text(text)
    ignore_visible = clean_text(ignore_text if ignore_text is not None else text)
    ref_year = ref_year or date.today().year
    start, end = scrape.extract_dates(visible, ref_year=ref_year, is_html=False, scan_chars=9000)
    auto_ignore = ""
    if ALWAYS_IGNORE_RE.search(ignore_visible):
        auto_ignore = "matches out-of-scope official audit rule"
    elif CONDITIONAL_IGNORE_RE.search(ignore_visible) and not re.search(r"リニューアル|オープン|OPEN", ignore_visible, re.I):
        auto_ignore = "matches out-of-scope official audit rule"
    return PageSignals(
        has_date=bool(DATE_RE.search(visible) or start),
        has_date_range=bool(DATE_RANGE_RE.search(visible) or (start and end)),
        has_collectible=bool(COLLECTIBLE_RE.search(visible)),
        has_venue=bool(VENUE_RE.search(visible)),
        start_date=start,
        end_date=end,
        auto_ignore_reason=auto_ignore,
    )


def load_parsed_event_pages(events_path: Path = EVENTS_JSON) -> dict[str, list[str]]:
    parsed: dict[str, list[str]] = {}
    if not events_path.exists():
        return parsed
    events = json.loads(events_path.read_text(encoding="utf-8"))
    for event in events:
        if event.get("brand") not in {"pokemon", "miffy"}:
            continue
        url = normalize_url(event.get("sourceUrl", ""))
        if not url:
            continue
        parsed.setdefault(url, []).append(event.get("id", ""))
    return parsed


def fetch_pokemon_cafe_candidates(max_items: int = 14) -> list[OfficialCandidate]:
    page = _page_text(POKEMON_CAFE_NEWS)
    out: list[OfficialCandidate] = []
    seen: set[str] = set()
    for url, title in extract_links(page, POKEMON_CAFE_NEWS):
        if not re.search(r"/ja/(?:cafe|pika_sweets)/news/\d+_\d+\.html$", url):
            continue
        if url in seen:
            continue
        out.append(OfficialCandidate("pokemon", "pokemon-cafe-news", url, title))
        seen.add(url)
        if len(out) >= max_items:
            break
    return out


def fetch_pokemon_tw_goods_candidates(max_pages: int = 3) -> list[OfficialCandidate]:
    out: list[OfficialCandidate] = []
    try:
        entries = official_sources._tw_goods_entries(max_pages=max_pages)
    except Exception:
        entries = []
    for entry in entries:
        out.append(OfficialCandidate(
            "pokemon",
            "pokemon-tw-goods",
            normalize_url(entry.get("url", "")),
            entry.get("title", ""),
            entry.get("published", ""),
            {"category": entry.get("category", "")},
        ))
    return out


def _pokemon_store_home_urls(max_stores: int) -> list[str]:
    page = _page_text(POKEMON_SHOP_LIST)
    urls: list[str] = []
    seen: set[str] = set()
    for url, _title in extract_links(page, POKEMON_SHOP_LIST):
        if not re.search(r"^https://shop\.pokemon\.co\.jp/ja/shop/[^/]+/$", url):
            continue
        if "pokemoncenter-singapore" in url:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if max_stores and len(urls) >= max_stores:
            break
    return urls


def fetch_pokemon_store_candidates(max_stores: int = 30,
                                   max_items_per_section: int = 4) -> list[OfficialCandidate]:
    out: list[OfficialCandidate] = []
    seen: set[str] = set()
    for home in _pokemon_store_home_urls(max_stores):
        slug = home.rstrip("/").rsplit("/", 1)[-1]
        for section in ("news", "events"):
            page_url = urljoin(home, section + "/")
            page = _page_text(page_url)
            links = [
                (url, title) for url, title in extract_links(page, page_url)
                if re.search(rf"/ja/shop/{re.escape(slug)}/{section}/\d+/\d+\.html$", url)
            ]
            for url, title in links[:max_items_per_section]:
                if url in seen:
                    continue
                seen.add(url)
                out.append(OfficialCandidate("pokemon", f"pokemon-store-{section}", url, title))
            time.sleep(0.05)
    return out


def fetch_dickbruna_candidates(max_items: int = 24) -> list[OfficialCandidate]:
    out: list[OfficialCandidate] = []
    seen: set[str] = set()
    for source, list_url in (("miffy-dickbruna-event", MIFFY_EVENT),
                             ("miffy-dickbruna-news", MIFFY_NEWS)):
        page = _page_text(list_url)
        for url, title in extract_links(page, list_url):
            if not re.search(r"^https://dickbruna\.jp/news/\d+/\d+/$", url):
                continue
            if url in seen:
                continue
            out.append(OfficialCandidate("miffy", source, url, title))
            seen.add(url)
            if len(out) >= max_items:
                break
        if len(out) >= max_items:
            break
    return out


def fetch_kiddy_miffy_candidates(max_items: int = 16) -> list[OfficialCandidate]:
    page = _page_text(KIDDY_MIFFY_SEARCH)
    out: list[OfficialCandidate] = []
    seen: set[str] = set()
    for url, title in extract_links(page, KIDDY_MIFFY_SEARCH):
        if not re.search(r"^https://www\.kiddyland\.co\.jp/(?:event|miffy_style)/", url):
            continue
        if not re.search(r"miffy|ミッフィ", url + " " + title, re.I):
            continue
        if url in seen:
            continue
        out.append(OfficialCandidate("miffy", "miffy-kiddyland-search", url, title))
        seen.add(url)
        if len(out) >= max_items:
            break
    return out


def fetch_candidates(args) -> list[OfficialCandidate]:
    candidates: list[OfficialCandidate] = []
    brands = set(args.brand)
    if "pokemon" in brands:
        candidates.extend(fetch_pokemon_cafe_candidates(args.max_pokemon_cafe))
        candidates.extend(fetch_pokemon_tw_goods_candidates(args.max_tw_goods_pages))
        if args.max_pokemon_stores:
            candidates.extend(fetch_pokemon_store_candidates(
                args.max_pokemon_stores, args.max_store_items))
    if "miffy" in brands:
        candidates.extend(fetch_dickbruna_candidates(args.max_dickbruna))
        candidates.extend(fetch_kiddy_miffy_candidates(args.max_kiddy))
    seen: set[str] = set()
    unique: list[OfficialCandidate] = []
    for candidate in candidates:
        url = normalize_url(candidate.url)
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(OfficialCandidate(
            candidate.brand, candidate.source, url, candidate.title,
            candidate.published, candidate.meta,
        ))
    return unique


def _risk_for(status: str, signals: PageSignals) -> str:
    if status != "needs_review":
        return "-"
    if signals.has_date_range and signals.has_collectible and signals.has_venue:
        return "high"
    if signals.has_date and (signals.has_collectible or signals.has_venue):
        return "medium"
    return "low"


def audit_candidates(
    candidates: list[OfficialCandidate],
    parsed_pages: dict[str, list[str]] | None = None,
    ignored_pages: dict[str, str] | None = None,
    details_by_url: dict[str, str] | None = None,
) -> list[AuditRow]:
    parsed_pages = parsed_pages or {}
    ignored_pages = ignored_pages or {}
    details_by_url = details_by_url or {}
    rows: list[AuditRow] = []
    for candidate in candidates:
        url = normalize_url(candidate.url)
        detail = details_by_url.get(url, "")
        title = _candidate_title(candidate, detail) if detail else candidate.title
        signals = detect_signals(
            _signal_text(candidate, detail, title),
            ignore_text="\n".join(part for part in (title, candidate.title) if part),
        )
        if url in parsed_pages:
            status = "parsed"
            reason = "represented by current event sourceUrl"
        elif url in ignored_pages:
            status = "ignored"
            reason = ignored_pages[url]
        elif signals.auto_ignore_reason:
            status = "ignored"
            reason = signals.auto_ignore_reason
        elif _is_expired(signals):
            status = "ignored"
            reason = "official page appears expired"
        else:
            status = "needs_review"
            reason = "official listing exposes this page, but no current event sourceUrl covers it"
        rows.append(AuditRow(
            brand=candidate.brand,
            source=candidate.source,
            status=status,
            risk=_risk_for(status, signals),
            title=title,
            url=url,
            reason=reason,
            signals=signals,
            event_ids=tuple(parsed_pages.get(url, ())),
            published=candidate.published,
        ))
    return rows


def fetch_review_details(candidates: list[OfficialCandidate],
                         parsed_pages: dict[str, list[str]]) -> dict[str, str]:
    details: dict[str, str] = {}
    for candidate in candidates:
        url = normalize_url(candidate.url)
        if url in parsed_pages:
            continue
        details[url] = _page_text(url) or candidate.title
        time.sleep(0.05)
    return details


def _format_markdown(rows: list[AuditRow]) -> str:
    counts = {status: sum(1 for row in rows if row.status == status)
              for status in ("parsed", "ignored", "needs_review")}
    risky = sum(1 for row in rows if row.status == "needs_review" and row.risk in {"high", "medium"})
    lines = [
        "# Official Pokemon/Miffy coverage audit",
        "",
        f"- found: {len(rows)}",
        f"- parsed: {counts['parsed']}",
        f"- ignored: {counts['ignored']}",
        f"- needs_review: {counts['needs_review']}",
        f"- high_or_medium_risk: {risky}",
        "",
        "| brand | source | status | risk | signals | title | url | reason | eventIds |",
        "| -- | -- | -- | -- | -- | -- | -- | -- | -- |",
    ]
    for row in rows:
        signals = ", ".join(row.signals.labels) or "-"
        title = (row.title or "-").replace("|", "\\|")
        reason = row.reason.replace("|", "/")
        event_ids = ", ".join(eid for eid in row.event_ids if eid) or "-"
        lines.append(
            f"| {row.brand} | {row.source} | {row.status} | {row.risk} | "
            f"{signals} | {title} | {row.url} | {reason} | {event_ids} |"
        )
    return "\n".join(lines)


def _format_text(rows: list[AuditRow]) -> str:
    lines: list[str] = []
    for row in rows:
        signals = ",".join(row.signals.labels) or "-"
        title = f" {row.title}" if row.title else ""
        lines.append(
            f"[{row.brand}/{row.source} {row.status} risk={row.risk} signals={signals}]"
            f"{title}\n  {row.url}\n  {row.reason}"
        )
    return "\n".join(lines)


def _format_json(rows: list[AuditRow]) -> str:
    payload = [
        {
            "brand": row.brand,
            "source": row.source,
            "status": row.status,
            "risk": row.risk,
            "signals": row.signals.labels,
            "title": row.title,
            "url": row.url,
            "reason": row.reason,
            "eventIds": list(row.event_ids),
            "published": row.published,
        }
        for row in rows
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_summary(rows: list[AuditRow]) -> str:
    statuses = {status: sum(1 for row in rows if row.status == status)
                for status in ("parsed", "ignored", "needs_review")}
    by_source: dict[str, dict[str, int]] = {}
    for row in rows:
        by_source.setdefault(row.source, {"parsed": 0, "ignored": 0, "needs_review": 0})
        by_source[row.source][row.status] += 1
    risky = [
        row for row in rows
        if row.status == "needs_review" and row.risk in {"high", "medium"}
    ]
    lines = [
        "Official Pokemon/Miffy coverage audit",
        f"found={len(rows)} parsed={statuses['parsed']} ignored={statuses['ignored']} "
        f"needs_review={statuses['needs_review']} high_or_medium={len(risky)}",
        "",
        "By source:",
    ]
    for source in sorted(by_source):
        counts = by_source[source]
        lines.append(
            f"- {source}: parsed={counts['parsed']} ignored={counts['ignored']} "
            f"needs_review={counts['needs_review']}"
        )
    lines.append("")
    lines.append("High/medium needs_review:")
    if not risky:
        lines.append("- none")
    for row in risky:
        signals = ", ".join(row.signals.labels) or "-"
        title = row.title or "-"
        lines.append(
            f"- [{row.risk}] {row.brand}/{row.source}: {title}\n"
            f"  {row.url}\n"
            f"  signals={signals}"
        )
    return "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Audit official Pokemon/Miffy coverage.")
    parser.add_argument("--brand", choices=("pokemon", "miffy"), action="append")
    parser.add_argument("--format", choices=("markdown", "text", "json", "summary"),
                        default="markdown")
    parser.add_argument("--no-fetch-details", action="store_true",
                        help="Only inspect listing pages; do not fetch candidate detail pages.")
    parser.add_argument("--fail-on-review", action="store_true",
                        help="Exit 2 when any high/medium risk needs_review page is found.")
    parser.add_argument("--max-pokemon-cafe", type=int, default=14)
    parser.add_argument("--max-tw-goods-pages", type=int, default=3)
    parser.add_argument("--max-pokemon-stores", type=int, default=24,
                        help="Number of JP/TW Pokemon Center store pages to sample; 0 disables store audit.")
    parser.add_argument("--max-store-items", type=int, default=4)
    parser.add_argument("--max-dickbruna", type=int, default=24)
    parser.add_argument("--max-kiddy", type=int, default=16)
    args = parser.parse_args()
    if not args.brand:
        args.brand = ["pokemon", "miffy"]

    candidates = fetch_candidates(args)
    if not candidates:
        print(
            "Official coverage audit failed: no official candidates were fetched. "
            "Check network/source availability instead of treating this as clean.",
            file=sys.stderr,
        )
        return 3
    parsed_pages = load_parsed_event_pages()
    ignored_pages = {normalize_url(k): v for k, v in IGNORED_OFFICIAL_PAGES.items()}
    details = {} if args.no_fetch_details else fetch_review_details(candidates, parsed_pages)
    rows = audit_candidates(candidates, parsed_pages, ignored_pages, details)

    if args.format == "json":
        print(_format_json(rows))
    elif args.format == "summary":
        print(_format_summary(rows))
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
