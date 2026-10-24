"""Audit Pokemon permanent locations against the official Japan shop list."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
import sys

from store_audit import OfficialStore, audit_stores, clean, load_local_official_names, print_result
from verify_links import fetch_html


ROOT = Path(__file__).resolve().parents[1]
STORES_JSON = ROOT / "data" / "stores.json"
OFFICIAL_SHOPS_URL = "https://www.pokemon.co.jp/shop/"


def _category(name: str) -> str:
    if name.startswith("ポケモンストア"):
        return "Pokemon Store"
    if "カフェ" in name or "スイーツ" in name:
        return "Pokemon Cafe / Sweets"
    return "Pokemon Center"


class _PokemonShopParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stores: list[OfficialStore] = []
        self._card_depth = 0
        self._card_classes: set[str] = set()
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
        if tag == "div" and "shop-list__element" in classes and not self._card_depth:
            self._card_depth = 1
            self._card_classes = classes
            self._name = []
            self._address = []
            return
        if not self._card_depth:
            return
        if tag == "div":
            self._card_depth += 1
        if tag == "div" and "shop-list__name" in classes:
            self._capture, self._capture_tag = "name", tag
        elif tag == "td":
            self._capture, self._capture_tag = "address", tag

    def handle_data(self, data: str) -> None:
        if self._card_depth and self._capture:
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
        name = clean(" ".join(self._name))
        address = clean(" ".join(self._address))
        in_scope = "〒" in address or name == "ポケモンセンタータイペイ"
        if name and address and in_scope:
            self.stores.append(OfficialStore(name, _category(name), address))


def extract_official_stores(page_html: str) -> list[OfficialStore]:
    parser = _PokemonShopParser()
    parser.feed(page_html or "")
    return parser.stores


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare data/stores.json Pokemon locations with the official shop list."
    )
    parser.add_argument("--url", default=OFFICIAL_SHOPS_URL)
    parser.add_argument("--stores", type=Path, default=STORES_JSON)
    parser.add_argument("--format", choices=("summary", "text", "markdown"), default="text")
    parser.add_argument("--fail-on-review", action="store_true")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    page_html = fetch_html(args.url, timeout=args.timeout)
    if not page_html:
        print(f"ERROR could not fetch official Pokemon shop list: {args.url}", file=sys.stderr)
        return 2
    official = extract_official_stores(page_html)
    if not official:
        print("ERROR official Pokemon shop parser returned no in-scope stores", file=sys.stderr)
        return 2

    local = load_local_official_names("pokemon", args.stores)
    result = audit_stores(official, local)
    print_result(result, args.format)
    return 1 if args.fail_on_review and not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
