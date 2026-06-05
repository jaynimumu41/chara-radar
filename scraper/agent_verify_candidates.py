"""Build a prioritized candidate list for the daily Codex verification pass.

This script is deliberately deterministic: it only selects records that need
agent/web verification. It never edits events.json, never calls network, and
never uses Gemini or any other API quota.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import scrape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"

# These official structured feeds are already parsed without AI and are treated
# as hand-quality data.
STRUCTURED_OFFICIAL_DOMAINS = (
    "chiikawa-info.jp",
    "oneheart65.net",
    "dickbruna.jp",
)

GENERIC_TITLE_KEYWORDS = (
    "新商品登場",
    "新商品",
    "新作グッズ",
    "新作アイテム",
    "新グッズ",
    "続々",
    "續々",
    "大集合",
    "ラインナップ",
    "商品情報",
    "発売開始",
    "開賣",
    "登場",
)

BRAND_JA = {
    "pokemon": "ポケモン",
    "miffy": "ミッフィー",
    "chiikawa": "ちいかわ",
}

REASON_WEIGHTS = {
    "missing_dates": 6,
    "missing_endDate": 4,
    "campaign_type": 3,
    "generic_title": 2,
    "missing_location": 2,
}


def load_events() -> list[dict]:
    return json.loads(EVENTS_JSON.read_text(encoding="utf-8"))


def domain_of(url: str) -> str:
    if not url:
        return ""
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def has_domain(url: str, domains: tuple[str, ...]) -> bool:
    host = domain_of(url)
    return any(d in host for d in domains)


def is_structured_official(ev: dict) -> bool:
    return (
        ev.get("sourceType") == "official_site"
        and has_domain(ev.get("sourceUrl", ""), STRUCTURED_OFFICIAL_DOMAINS)
    )


def is_generic_title(title: str) -> bool:
    return any(kw in (title or "") for kw in GENERIC_TITLE_KEYWORDS)


def verification_reasons(ev: dict) -> list[str]:
    if is_structured_official(ev):
        return []

    reasons: list[str] = []
    if not ev.get("startDate") and not ev.get("endDate"):
        reasons.append("missing_dates")
    if not ev.get("endDate"):
        reasons.append("missing_endDate")
    if not scrape.is_trusted_date_source(ev.get("sourceUrl", "")):
        source_domain = domain_of(ev.get("sourceUrl", "")) or "no_url"
        reasons.append(f"untrusted_date_domain:{source_domain}")
    if ev.get("type") == "campaign":
        reasons.append("campaign_type")
    if is_generic_title(ev.get("title", "")) or is_generic_title(ev.get("sourceTitle", "")):
        reasons.append("generic_title")
    if not ev.get("locationName"):
        reasons.append("missing_location")
    return reasons


def risk_score(ev: dict, reasons: list[str]) -> int:
    score = 0
    for reason in reasons:
        if reason.startswith("untrusted_date_domain"):
            score += 3
        else:
            score += REASON_WEIGHTS.get(reason, 1)
    if ev.get("sourceType") == "official_social":
        score += 1
    return score


def suggested_query(ev: dict) -> str:
    parts = [
        ev.get("locationName", ""),
        ev.get("title", ""),
        BRAND_JA.get(ev.get("brand", ""), ev.get("brand", "")),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        text = re.sub(r"\s+", " ", (part or "").strip())
        if not text:
            continue
        if any(text == old or text in old for old in out):
            continue
        out = [old for old in out if old not in text]
        out.append(text)
        seen.add(text)
    return " ".join(out)


def clean_cell(value) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.replace("|", "/")


def build_candidates(events: list[dict]) -> list[dict]:
    candidates: list[dict] = []
    for ev in events:
        reasons = verification_reasons(ev)
        if not reasons:
            continue
        candidates.append({
            "risk": risk_score(ev, reasons),
            "reasons": reasons,
            "query": suggested_query(ev),
            "id": ev.get("id", ""),
            "brand": ev.get("brand", ""),
            "type": ev.get("type", ""),
            "title": ev.get("title", ""),
            "locationName": ev.get("locationName", ""),
            "startDate": ev.get("startDate", ""),
            "endDate": ev.get("endDate", ""),
            "sourceType": ev.get("sourceType", ""),
            "sourceDomain": domain_of(ev.get("sourceUrl", "")),
            "sourceUrl": ev.get("sourceUrl", ""),
            "sourceTitle": ev.get("sourceTitle", ""),
        })
    candidates.sort(key=lambda c: (-c["risk"], c["brand"], c["title"]))
    return candidates


def print_markdown(candidates: list[dict], total_events: int, limit: int) -> None:
    shown = candidates[:limit] if limit else candidates
    print("# Agent verification candidates")
    print()
    print(f"- Total events: {total_events}")
    print(f"- Candidates: {len(candidates)}")
    print("- Skip rule: structured official_site records from chiikawa-info.jp, oneheart65.net, and dickbruna.jp")
    print()
    print("| Risk | Brand | Type | Title | Location | Dates | Source | Reasons | Search query |")
    print("| --: | -- | -- | -- | -- | -- | -- | -- | -- |")
    for c in shown:
        dates = f"{c['startDate'] or '?'} to {c['endDate'] or '?'}"
        print(
            "| "
            + " | ".join([
                str(c["risk"]),
                clean_cell(c["brand"]),
                clean_cell(c["type"]),
                clean_cell(c["title"]),
                clean_cell(c["locationName"]),
                clean_cell(dates),
                clean_cell(c["sourceDomain"]),
                clean_cell(", ".join(c["reasons"])),
                clean_cell(c["query"]),
            ])
            + " |"
        )
    if limit and len(candidates) > limit:
        print()
        print(f"Showing top {limit}; rerun without --limit for all candidates.")


def main() -> int:
    parser = argparse.ArgumentParser(description="List high-risk events for agent verification.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--limit", type=int, default=0, help="Maximum candidates to print; 0 means all.")
    args = parser.parse_args()

    events = load_events()
    candidates = build_candidates(events)
    if args.format == "json":
        print(json.dumps(candidates[:args.limit] if args.limit else candidates,
                         ensure_ascii=False, indent=2))
    else:
        print_markdown(candidates, len(events), args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
