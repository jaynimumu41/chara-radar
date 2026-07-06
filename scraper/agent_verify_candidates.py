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
import source_reputation

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
REPUTATION_JSON = ROOT / "data" / "source_reputation.json"

# These official structured feeds are already parsed without AI and are treated
# as hand-quality data.
STRUCTURED_OFFICIAL_DOMAINS = (
    "chiikawa-info.jp",
    "chiikawamogumogu.jp",
    "oneheart65.net",
    "pokemon-cafe.jp",
    "tw.portal-pokemon.com",
    "dickbruna.jp",
    "kiddyland.co.jp",
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
    "structured_activity_missing_endDate": 4,
    "campaign_type": 3,
    "generic_title": 2,
    "missing_location": 2,
}

REVIEWED_SKIP_REASONS = {
    "missing_endDate",
    "structured_activity_missing_endDate",
    "campaign_type",
    "generic_title",
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
    url = ev.get("sourceUrl", "")
    if ev.get("sourceType") == "official_site" and has_domain(url, STRUCTURED_OFFICIAL_DOMAINS):
        return True
    # oneheart65 is a structured Pokemon Center branch schedule feed in this
    # project, even though existing records keep the legacy official_social type.
    return ev.get("brand") == "pokemon" and has_domain(url, ("oneheart65.net",))


def structured_activity_missing_end_date(ev: dict) -> bool:
    return (
        is_structured_official(ev)
        and ev.get("type") in scrape.ACTIVITY_TYPES
        and bool(ev.get("startDate"))
        and not ev.get("endDate")
    )


def is_generic_title(title: str) -> bool:
    return any(kw in (title or "") for kw in GENERIC_TITLE_KEYWORDS)


def verification_reasons(ev: dict) -> list[str]:
    if is_structured_official(ev) and not structured_activity_missing_end_date(ev):
        return []

    trusted_date_source = scrape.is_trusted_date_source(ev.get("sourceUrl", ""))
    reasons: list[str] = []
    if not ev.get("startDate") and not ev.get("endDate"):
        reasons.append("missing_dates")
    if not ev.get("endDate") and not (ev.get("type") == "new_product" and ev.get("startDate")):
        reasons.append("missing_endDate")
    if structured_activity_missing_end_date(ev):
        reasons.append("structured_activity_missing_endDate")
    if not trusted_date_source:
        source_domain = domain_of(ev.get("sourceUrl", "")) or "no_url"
        reasons.append(f"untrusted_date_domain:{source_domain}")
    if ev.get("type") == "campaign" and not (trusted_date_source and ev.get("startDate") and ev.get("endDate")):
        reasons.append("campaign_type")
    if not trusted_date_source and (is_generic_title(ev.get("title", "")) or is_generic_title(ev.get("sourceTitle", ""))):
        reasons.append("generic_title")
    if not ev.get("locationName"):
        reasons.append("missing_location")
    return reasons


def confirmed_event_ids(reputation_data: dict) -> set[str]:
    ids: set[str] = set()
    for entry in reputation_data.get("sources", {}).values():
        for item in entry.get("history", []):
            if item.get("outcome") == "confirmed" and item.get("eventId"):
                ids.add(str(item["eventId"]))
    return ids


def is_reviewed_candidate(ev: dict, reasons: list[str], reviewed_ids: set[str]) -> bool:
    if ev.get("id") not in reviewed_ids:
        return False
    return all(reason in REVIEWED_SKIP_REASONS or reason.startswith("untrusted_date_domain:") for reason in reasons)


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


def reputation_context(ev: dict, reputation_data: dict) -> dict:
    summary = source_reputation.summarize_source(reputation_data, ev)
    trusted_date_source = scrape.is_trusted_date_source(ev.get("sourceUrl", ""))
    structured_source = is_structured_official(ev)
    policy = source_reputation.evidence_policy(
        summary,
        trusted_date_source=trusted_date_source,
        structured_source=structured_source,
    )
    source_tier = "trusted_date" if trusted_date_source else summary["tier"]
    source_score = 100 if trusted_date_source else summary["score"]
    source_reputation_label = (
        "trusted-date source"
        if trusted_date_source
        else source_reputation.format_summary(summary)
    )
    return {
        "sourceId": summary["id"],
        "sourceKind": summary["kind"],
        "sourceTier": source_tier,
        "sourceScore": source_score,
        "sourceReviews": summary["reviews"],
        "sourceReputation": source_reputation_label,
        "sourceNotes": summary["notes"],
        "evidenceRequired": policy["label"],
        "minIndependentSources": policy["minIndependentSources"],
        "evidenceAction": policy["action"],
        "reputationRisk": 0 if trusted_date_source else source_reputation.risk_adjustment(summary),
    }


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
    reputation_data = source_reputation.load_reputation(REPUTATION_JSON)
    reviewed_ids = confirmed_event_ids(reputation_data)
    candidates: list[dict] = []
    for ev in events:
        reasons = verification_reasons(ev)
        if not reasons:
            continue
        if is_reviewed_candidate(ev, reasons, reviewed_ids):
            continue
        rep = reputation_context(ev, reputation_data)
        candidates.append({
            "risk": max(0, risk_score(ev, reasons) + rep["reputationRisk"]),
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
            **rep,
        })
    candidates.sort(key=lambda c: (-c["risk"], c["brand"], c["title"]))
    return candidates


def print_markdown(candidates: list[dict], total_events: int, limit: int) -> None:
    shown = candidates[:limit] if limit else candidates
    print("# Agent verification candidates")
    print()
    print(f"- Total events: {total_events}")
    print(f"- Candidates: {len(candidates)}")
    print("- Skip rule: complete structured-source records from chiikawa-info.jp, chiikawamogumogu.jp, oneheart65.net, pokemon-cafe.jp, tw.portal-pokemon.com, dickbruna.jp, and kiddyland.co.jp")
    print("- Exception: activity-like structured official records with a startDate but no endDate stay in the queue until source reputation confirms the open-ended period")
    print("- Source reputation: data/source_reputation.json adjusts risk and states how much corroboration is needed")
    print()
    print("| Risk | Reputation | Evidence | Brand | Type | Title | Location | Dates | Source | Reasons | Search query |")
    print("| --: | -- | -- | -- | -- | -- | -- | -- | -- | -- | -- |")
    for c in shown:
        dates = f"{c['startDate'] or '?'} to {c['endDate'] or '?'}"
        evidence = f"{c['evidenceRequired']} ({c['minIndependentSources']}+)"
        print(
            "| "
            + " | ".join([
                str(c["risk"]),
                clean_cell(c["sourceReputation"]),
                clean_cell(evidence),
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
