"""Audit Chiikawa permanent specialty locations against official sources."""
from __future__ import annotations

import argparse
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

from store_audit import (
    OfficialStore,
    audit_stores,
    clean,
    load_local_official_names,
    normalize_name,
    print_result,
)
from verify_links import fetch_html


ROOT = Path(__file__).resolve().parents[1]
STORES_JSON = ROOT / "data" / "stores.json"
INFO_SECTION_URLS = (
    "https://chiikawa-info.jp/ck_land",
    "https://chiikawa-info.jp/magical_s.html",
    "https://chiikawa-info.jp/s_fes.html",
)
MOGUMOGU_SITEMAP_URL = "https://www.chiikawamogumogu.jp/page-sitemap.xml"
YAKI_URL = "https://www.chiikawa-yaki.com/"
BAKERY_URL = "https://chiikawabakery.jp/"
PARK_URL = "https://chiikawapark-tokyo.jp/"
PARK_STORE_URL = "https://chiikawapark-tokyo.jp/news/x0e64eb94v/"
OBANYAKI_URL = "https://prtimes.jp/main/html/rd/p/000000004.000187317.html"
TAIPEI_URL = "https://chiikawa-info.jp/ck_w/taipei/index.html"


class _PermanentSectionParser(HTMLParser):
    """Read h3 store cards only from a section explicitly marked permanent."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stores: list[OfficialStore] = []
        self._section = ""
        self._capture = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        if tag in {"h2", "h3"}:
            self._capture = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != self._capture:
            return
        text = clean(" ".join(self._parts))
        if tag == "h2":
            self._section = text
        elif "常設店" in self._section and text:
            self.stores.append(OfficialStore(text, self._section))
        self._capture = ""
        self._parts = []


def extract_info_permanent_stores(page_html: str) -> list[OfficialStore]:
    parser = _PermanentSectionParser()
    parser.feed(page_html or "")
    return parser.stores


def extract_mogumogu_store_urls(sitemap_xml: str) -> list[str]:
    urls = re.findall(r"<loc>\s*([^<]+/stores/[^<]+)\s*</loc>", sitemap_xml or "", re.I)
    return sorted({html.unescape(url).strip() for url in urls if url.rstrip("/").split("/")[-1]})


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._inside = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "title":
            self._inside = True

    def handle_data(self, data: str) -> None:
        if self._inside:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside = False


def extract_page_title(page_html: str) -> str:
    parser = _TitleParser()
    parser.feed(page_html or "")
    return clean(" ".join(parser.parts))


def extract_mogumogu_store(page_html: str) -> OfficialStore | None:
    title = extract_page_title(page_html)
    name = clean(re.split(r"\s*[|｜–—]\s*", title, maxsplit=1)[0])
    if name.startswith("ちいかわ") and name not in {"ちいかわもぐもぐ本舗", "ちいかわとは"}:
        return OfficialStore(name, "ちいかわもぐもぐ本舗")
    return None


class _YakiStoreParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: list[str] = []
        self._capture = False
        self._parts: list[str] = []

    def handle_starttag(self, tag, attrs) -> None:
        classes = next((value.split() for key, value in attrs if key == "class" and value), [])
        if tag == "a" and "reserve-store-btn" in classes:
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._capture:
            return
        name = clean(" ".join(self._parts))
        if name and "オンライン" not in name:
            self.names.append(f"ちいかわ焼き {name}")
        self._capture = False
        self._parts = []


def extract_yaki_stores(page_html: str) -> list[OfficialStore]:
    parser = _YakiStoreParser()
    parser.feed(page_html or "")
    return [OfficialStore(name, "ちいかわ焼き") for name in dict.fromkeys(parser.names)]


class _BakeryStoreParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.names: list[str] = []
        self._section_depth = 0
        self._capture = False
        self._parts: list[str] = []

    @staticmethod
    def _attr(attrs, key: str) -> str:
        return next((value for name, value in attrs if name == key and value), "")

    def handle_starttag(self, tag, attrs) -> None:
        if tag == "section" and not self._section_depth:
            section_id = self._attr(attrs, "id")
            if section_id in {"shop_tokyo", "shop_osaka"}:
                self._section_depth = 1
                return
        elif tag == "section" and self._section_depth:
            self._section_depth += 1
        if not self._section_depth:
            return
        classes = self._attr(attrs, "class").split()
        if tag == "p" and "shop_name" in classes:
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "p" and self._capture:
            name = clean(" ".join(self._parts))
            if name:
                self.names.append(name)
            self._capture = False
            self._parts = []
        if tag == "section" and self._section_depth:
            self._section_depth -= 1


def extract_bakery_stores(page_html: str) -> list[OfficialStore]:
    parser = _BakeryStoreParser()
    parser.feed(page_html or "")
    return [OfficialStore(name, "ちいかわベーカリー") for name in dict.fromkeys(parser.names)]


def extract_park_stores(park_html: str, store_html: str) -> list[OfficialStore]:
    stores: list[OfficialStore] = []
    park_text = clean(re.sub(r"<[^>]+>", " ", html.unescape(park_html or "")))
    store_text = clean(re.sub(r"<[^>]+>", " ", html.unescape(store_html or "")))
    if "ちいかわパーク" in park_text and "サンシャインシティ" in park_text:
        stores.append(OfficialStore("ちいかわパーク", "ちいかわパーク"))
    if "ちいかわパークストア" in store_text and "LUCUA SOUTH" in store_text:
        stores.append(OfficialStore("ちいかわパークストア", "ちいかわパーク"))
    return stores


def extract_taipei_store(page_html: str) -> list[OfficialStore]:
    title = extract_page_title(page_html)
    if "CHIIKAWA SHOP in TAIPEI" in title:
        return [OfficialStore("CHIIKAWA SHOP in TAIPEI", "Taiwan")]
    return []


def extract_obanyaki_store(page_html: str) -> list[OfficialStore]:
    text = clean(re.sub(r"<[^>]+>", " ", html.unescape(page_html or "")))
    if all(signal in text for signal in (
        "CHIIKAWA OBANYAKI in TAIPEI", "常設店舗", "2026年11月21日", "台北市大同區赤峰街41巷9號",
    )):
        return [OfficialStore("CHIIKAWA OBANYAKI in TAIPEI", "Taiwan")]
    return []


def _dedupe(stores: list[OfficialStore]) -> list[OfficialStore]:
    seen: set[str] = set()
    result: list[OfficialStore] = []
    for store in stores:
        key = normalize_name(store.name)
        if key and key not in seen:
            seen.add(key)
            result.append(store)
    return result


def fetch_official_stores(timeout: int = 30) -> list[OfficialStore]:
    stores: list[OfficialStore] = []
    for url in INFO_SECTION_URLS:
        page = fetch_html(url, timeout=timeout)
        if not page:
            raise RuntimeError(f"could not fetch {url}")
        stores.extend(extract_info_permanent_stores(page))

    sitemap = fetch_html(MOGUMOGU_SITEMAP_URL, timeout=timeout)
    if not sitemap:
        raise RuntimeError(f"could not fetch {MOGUMOGU_SITEMAP_URL}")
    store_urls = extract_mogumogu_store_urls(sitemap)
    if not store_urls:
        raise RuntimeError("Mogumogu sitemap returned no store pages")
    for url in store_urls:
        page = fetch_html(url, timeout=timeout)
        if not page:
            raise RuntimeError(f"could not fetch {url}")
        store = extract_mogumogu_store(page)
        if store:
            stores.append(store)

    pages = {}
    for url in (YAKI_URL, BAKERY_URL, PARK_URL, PARK_STORE_URL, TAIPEI_URL, OBANYAKI_URL):
        pages[url] = fetch_html(url, timeout=timeout)
        if not pages[url]:
            raise RuntimeError(f"could not fetch {url}")
    stores.extend(extract_yaki_stores(pages[YAKI_URL]))
    stores.extend(extract_bakery_stores(pages[BAKERY_URL]))
    stores.extend(extract_park_stores(pages[PARK_URL], pages[PARK_STORE_URL]))
    stores.extend(extract_taipei_store(pages[TAIPEI_URL]))
    stores.extend(extract_obanyaki_store(pages[OBANYAKI_URL]))
    return _dedupe(stores)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare data/stores.json Chiikawa locations with official sources."
    )
    parser.add_argument("--stores", type=Path, default=STORES_JSON)
    parser.add_argument("--format", choices=("summary", "text", "markdown"), default="text")
    parser.add_argument("--fail-on-review", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    try:
        official = fetch_official_stores(args.timeout)
    except RuntimeError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    if not official:
        print("ERROR official Chiikawa parsers returned no permanent stores", file=sys.stderr)
        return 2

    local = load_local_official_names("chiikawa", args.stores)
    result = audit_stores(official, local)
    print_result(result, args.format)
    return 1 if args.fail_on_review and not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
