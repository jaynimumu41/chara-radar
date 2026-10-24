"""Audit Miffy permanent-store coverage against the official shop list.

The public store names are localized for this project, so each Miffy row keeps
an ``officialName`` identity. This script compares those identities with the
current physical locations published by dickbruna.jp and reports additions or
closures that need review. It never edits data by itself.
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import sys

from store_audit import (
    AuditResult,
    OfficialStore,
    audit_stores,
    clean,
    load_local_official_names as load_brand_official_names,
    normalize_name,
    print_result,
)
from verify_links import fetch_html


ROOT = Path(__file__).resolve().parents[1]
STORES_JSON = ROOT / "data" / "stores.json"
OFFICIAL_SHOPS_URL = "https://dickbruna.jp/shop/"


def _clean(text: str) -> str:
    return clean(text)


class _OfficialShopParser(HTMLParser):
    """Parse the server-rendered official shop cards without extra packages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stores: list[OfficialStore] = []
        self._card_depth = 0
        self._category: list[str] = []
        self._name: list[str] = []
        self._address: list[str] = []
        self._capture = ""
        self._capture_tag = ""

    @staticmethod
    def _classes(attrs) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag, attrs) -> None:
        classes = self._classes(attrs)
        if tag == "div" and "c-card-shop-item" in classes and not self._card_depth:
            self._card_depth = 1
            self._category = []
            self._name = []
            self._address = []
            return
        if not self._card_depth:
            return
        if tag == "div":
            self._card_depth += 1
        if tag == "span" and "c-article-taxonomy" in classes:
            self._capture, self._capture_tag = "category", tag
        elif tag == "h3" and "c-card-shop-item__title" in classes:
            self._capture, self._capture_tag = "name", tag
        elif tag == "div" and "c-card-shop-item__address" in classes:
            self._capture, self._capture_tag = "address", tag

    def handle_data(self, data: str) -> None:
        if not self._card_depth or not self._capture:
            return
        getattr(self, f"_{self._capture}").append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._card_depth:
            return
        if tag == self._capture_tag:
            self._capture = ""
            self._capture_tag = ""
        if tag != "div":
            return
        self._card_depth -= 1
        if self._card_depth:
            return
        name = _clean(" ".join(self._name))
        address = _clean(" ".join(self._address))
        if name and address:
            self.stores.append(OfficialStore(
                name=name,
                category=_clean(" ".join(self._category)),
                address=address,
            ))


def extract_official_stores(page_html: str) -> list[OfficialStore]:
    parser = _OfficialShopParser()
    parser.feed(page_html or "")
    return parser.stores


def load_local_official_names(path: Path = STORES_JSON) -> list[str]:
    return load_brand_official_names("miffy", path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare data/stores.json Miffy locations with the official shop list."
    )
    parser.add_argument("--url", default=OFFICIAL_SHOPS_URL)
    parser.add_argument("--stores", type=Path, default=STORES_JSON)
    parser.add_argument("--format", choices=("summary", "text", "markdown"), default="text")
    parser.add_argument("--fail-on-review", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    page_html = fetch_html(args.url, timeout=args.timeout)
    if not page_html:
        print(f"ERROR could not fetch official Miffy shop list: {args.url}", file=sys.stderr)
        return 2
    official = extract_official_stores(page_html)
    if not official:
        print("ERROR official Miffy shop parser returned no physical stores", file=sys.stderr)
        return 2

    result = audit_stores(official, load_local_official_names(args.stores))
    print_result(result, args.format)
    return 1 if args.fail_on_review and not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
