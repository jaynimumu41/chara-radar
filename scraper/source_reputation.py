"""Track source reputation for non-official verification.

The scraper should collect broadly, while events.json stays conservative.  This
module gives the daily agent a small memory: sources that are repeatedly
confirmed become easier to trust, and sources that are rejected become louder
verification risks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPUTATION_JSON = ROOT / "data" / "source_reputation.json"
BASE_SCORE = 50
OUTCOMES = {"confirmed", "rejected", "uncertain"}

SOCIAL_HOSTS = {
    "instagram.com": "instagram",
    "threads.net": "threads",
    "threads.com": "threads",
    "x.com": "x",
    "twitter.com": "x",
    "facebook.com": "facebook",
}

NEWS_HOST_HINTS = (
    "news",
    "prtimes",
    "atpress",
    "dreamnews",
    "nownews",
    "udn",
    "tvbs",
    "dtimes",
    "game.watch",
    "famitsu",
    "inside-games",
    "4gamers",
    "pokemonhubs",
)


def utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def clamp(value: int, low: int = 5, high: int = 95) -> int:
    return max(low, min(high, value))


def normalize_host(host: str) -> str:
    host = (host or "").lower().strip()
    for prefix in ("www.", "m.", "mobile.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def unwrap_reader_url(url: str) -> str:
    url = (url or "").strip()
    marker = "://r.jina.ai/"
    if marker not in url:
        return url
    return re.sub(r"^https?://r\.jina\.ai/", "", url)


def classify_domain(host: str) -> str:
    if not host:
        return "missing"
    if host in SOCIAL_HOSTS:
        return "social"
    if host.endswith(".go.jp") or host.endswith(".gov.tw"):
        return "government"
    if any(hint in host for hint in NEWS_HOST_HINTS):
        return "news"
    return "site"


def handle_from_text(text: str) -> str:
    match = re.search(r"@([A-Za-z0-9._]{2,30})", text or "")
    return match.group(1).lower() if match else ""


def source_identity(url: str, source_title: str = "") -> dict:
    url = unwrap_reader_url(url)
    if not url:
        return {
            "id": "missing:no-url",
            "label": "no URL",
            "kind": "missing",
            "host": "",
            "handle": "",
        }
    if "google.com/search" in url:
        return {
            "id": "placeholder:google-search",
            "label": "Google search placeholder",
            "kind": "placeholder",
            "host": "google.com",
            "handle": "",
        }

    parsed = urlparse(url)
    host = normalize_host(parsed.netloc)
    parts = [p for p in parsed.path.split("/") if p]

    if host in ("instagram.com", "threads.net", "threads.com", "x.com", "twitter.com"):
        platform = SOCIAL_HOSTS[host]
        handle = ""
        if platform == "threads":
            if parts and parts[0].startswith("@"):
                handle = parts[0].lstrip("@").lower()
        elif platform == "instagram":
            if parts and parts[0] == "stories" and len(parts) > 1:
                handle = parts[1].lower()
            elif parts and parts[0] not in {"p", "reel", "tv", "explore"}:
                handle = parts[0].lstrip("@").lower()
            else:
                handle = handle_from_text(source_title)
        elif platform == "x":
            if parts and parts[0] not in {"i", "intent", "share"}:
                handle = parts[0].lstrip("@").lower()
        if handle:
            return {
                "id": f"{platform}:{handle}",
                "label": f"{platform} @{handle}",
                "kind": "social",
                "host": host,
                "handle": handle,
            }

    if host:
        return {
            "id": f"domain:{host}",
            "label": host,
            "kind": classify_domain(host),
            "host": host,
            "handle": "",
        }

    label = re.sub(r"\s+", " ", source_title or "unknown source").strip()
    return {
        "id": "missing:unparseable-url",
        "label": label[:80],
        "kind": "missing",
        "host": "",
        "handle": "",
    }


def new_reputation_data() -> dict:
    return {
        "version": 1,
        "updatedAt": "",
        "sources": {},
    }


def load_reputation(path: Path = DEFAULT_REPUTATION_JSON) -> dict:
    if not path.exists():
        return new_reputation_data()
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("version", 1)
    data.setdefault("updatedAt", "")
    data.setdefault("sources", {})
    return data


def save_reputation(data: dict, path: Path = DEFAULT_REPUTATION_JSON) -> None:
    data["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def empty_counts() -> dict:
    return {
        "confirmed": 0,
        "rejected": 0,
        "uncertain": 0,
        "crossChecked": 0,
        "score": BASE_SCORE,
    }


def default_entry(identity: dict) -> dict:
    entry = empty_counts()
    entry.update({
        "label": identity["label"],
        "kind": identity["kind"],
        "host": identity["host"],
        "handle": identity["handle"],
        "firstSeen": utc_today(),
        "lastReviewed": "",
        "lastOutcome": "",
        "notes": "",
        "byBrand": {},
        "byType": {},
        "byCountry": {},
        "history": [],
    })
    return entry


def ensure_source(data: dict, identity: dict) -> dict:
    sources = data.setdefault("sources", {})
    entry = sources.setdefault(identity["id"], default_entry(identity))
    entry.setdefault("label", identity["label"])
    entry.setdefault("kind", identity["kind"])
    entry.setdefault("host", identity["host"])
    entry.setdefault("handle", identity["handle"])
    entry.setdefault("confirmed", 0)
    entry.setdefault("rejected", 0)
    entry.setdefault("uncertain", 0)
    entry.setdefault("crossChecked", 0)
    entry.setdefault("score", BASE_SCORE)
    entry.setdefault("byBrand", {})
    entry.setdefault("byType", {})
    entry.setdefault("byCountry", {})
    entry.setdefault("history", [])
    return entry


def score_from_counts(counts: dict) -> int:
    confirmed = int(counts.get("confirmed", 0))
    rejected = int(counts.get("rejected", 0))
    uncertain = int(counts.get("uncertain", 0))
    cross_checked = int(counts.get("crossChecked", 0))
    if confirmed + rejected + uncertain == 0:
        return int(counts.get("score", BASE_SCORE))
    raw = BASE_SCORE + confirmed * 7 - rejected * 11 - uncertain * 3 + min(cross_checked * 2, 10)
    return clamp(raw)


def review_count(counts: dict) -> int:
    return int(counts.get("confirmed", 0)) + int(counts.get("rejected", 0)) + int(counts.get("uncertain", 0))


def source_tier(score: int, reviews: int) -> str:
    if reviews == 0:
        return "unproven"
    if score >= 78 and reviews >= 3:
        return "trusted"
    if score >= 65:
        return "promising"
    if score >= 45:
        return "mixed"
    if score >= 30:
        return "weak"
    return "poor"


def context_counts(entry: dict, bucket: str, key: str) -> dict | None:
    if not key:
        return None
    value = entry.get(bucket, {}).get(key.lower())
    return value if isinstance(value, dict) else None


def summarize_source(data: dict, ev: dict) -> dict:
    identity = source_identity(ev.get("sourceUrl", ""), ev.get("sourceTitle", ""))
    entry = data.get("sources", {}).get(identity["id"])
    if not entry:
        score = BASE_SCORE
        reviews = 0
        return {
            **identity,
            "score": score,
            "tier": source_tier(score, reviews),
            "reviews": reviews,
            "confirmed": 0,
            "rejected": 0,
            "uncertain": 0,
            "contextScores": {},
            "notes": "",
        }

    scores = [int(entry.get("score", BASE_SCORE))]
    context_scores: dict[str, int] = {}
    for bucket, ev_key, label in (
        ("byBrand", "brand", "brand"),
        ("byType", "type", "type"),
        ("byCountry", "country", "country"),
    ):
        counts = context_counts(entry, bucket, ev.get(ev_key, ""))
        if counts and review_count(counts):
            sc = score_from_counts(counts)
            scores.append(sc)
            context_scores[label] = sc
    score = round(sum(scores) / len(scores))
    reviews = review_count(entry)
    return {
        **identity,
        "score": score,
        "tier": source_tier(score, reviews),
        "reviews": reviews,
        "confirmed": int(entry.get("confirmed", 0)),
        "rejected": int(entry.get("rejected", 0)),
        "uncertain": int(entry.get("uncertain", 0)),
        "contextScores": context_scores,
        "notes": entry.get("notes", ""),
    }


def evidence_policy(summary: dict, *, trusted_date_source: bool, structured_source: bool) -> dict:
    if structured_source and trusted_date_source:
        return {
            "minIndependentSources": 0,
            "label": "structured source",
            "action": "check only if another risk reason exists",
        }
    if summary["kind"] in {"missing", "placeholder"}:
        return {
            "minIndependentSources": 2,
            "label": "find stable source",
            "action": "replace the placeholder before keeping the record",
        }
    if trusted_date_source:
        return {
            "minIndependentSources": 1,
            "label": "authoritative date check",
            "action": "fetch the original page and verify event fields",
        }
    tier = summary["tier"]
    if tier == "trusted":
        return {
            "minIndependentSources": 1,
            "label": "trusted source cross-check",
            "action": "confirm the original page; add one independent source for non-official records",
        }
    if tier == "promising":
        return {
            "minIndependentSources": 2,
            "label": "two-source check",
            "action": "confirm with another article, venue page, brand post, or social proof",
        }
    if tier in {"weak", "poor"}:
        return {
            "minIndependentSources": 3,
            "label": "high-risk source",
            "action": "keep only with strong independent corroboration; otherwise reject or leave pending",
        }
    return {
        "minIndependentSources": 2,
        "label": "unproven source",
        "action": "confirm with at least two independent signals before keeping",
    }


def risk_adjustment(summary: dict) -> int:
    if summary["kind"] in {"missing", "placeholder"}:
        return 4
    return {
        "trusted": -2,
        "promising": -1,
        "mixed": 1,
        "unproven": 2,
        "weak": 4,
        "poor": 5,
    }.get(summary["tier"], 2)


def add_to_counts(counts: dict, outcome: str, evidence_count: int) -> None:
    counts[outcome] = int(counts.get(outcome, 0)) + 1
    counts["crossChecked"] = int(counts.get("crossChecked", 0)) + max(0, evidence_count)
    counts["score"] = score_from_counts(counts)


def touch_context(entry: dict, bucket: str, key: str, outcome: str, evidence_count: int) -> None:
    if not key:
        return
    table = entry.setdefault(bucket, {})
    counts = table.setdefault(key.lower(), empty_counts())
    add_to_counts(counts, outcome, evidence_count)


def record_outcome(
    data: dict,
    *,
    url: str,
    outcome: str,
    brand: str = "",
    event_type: str = "",
    country: str = "",
    event_id: str = "",
    evidence_count: int = 0,
    notes: str = "",
    reviewed_at: str | None = None,
) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
    identity = source_identity(url)
    entry = ensure_source(data, identity)
    reviewed_at = reviewed_at or utc_today()
    add_to_counts(entry, outcome, evidence_count)
    touch_context(entry, "byBrand", brand, outcome, evidence_count)
    touch_context(entry, "byType", event_type, outcome, evidence_count)
    touch_context(entry, "byCountry", country, outcome, evidence_count)
    entry["lastReviewed"] = reviewed_at
    entry["lastOutcome"] = outcome
    if notes:
        entry["notes"] = notes
    history = entry.setdefault("history", [])
    history.append({
        "date": reviewed_at,
        "outcome": outcome,
        "brand": brand,
        "type": event_type,
        "country": country,
        "eventId": event_id,
        "evidenceCount": evidence_count,
        "notes": notes,
    })
    del history[:-50]
    return entry


def format_summary(summary: dict) -> str:
    return (
        f"{summary['tier']} {summary['score']}/100 "
        f"({summary['confirmed']}C/{summary['rejected']}R/{summary['uncertain']}U)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Update or inspect source reputation.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    show = sub.add_parser("show", help="Show reputation for a source URL.")
    show.add_argument("--url", required=True)
    show.add_argument("--brand", default="")
    show.add_argument("--type", default="")
    show.add_argument("--country", default="")

    record = sub.add_parser("record", help="Record a verification outcome.")
    record.add_argument("--url", required=True)
    record.add_argument("--outcome", required=True, choices=sorted(OUTCOMES))
    record.add_argument("--brand", default="")
    record.add_argument("--type", default="")
    record.add_argument("--country", default="")
    record.add_argument("--event-id", default="")
    record.add_argument("--evidence-count", type=int, default=0)
    record.add_argument("--notes", default="")

    args = parser.parse_args()
    data = load_reputation()
    if args.cmd == "record":
        entry = record_outcome(
            data,
            url=args.url,
            outcome=args.outcome,
            brand=args.brand,
            event_type=args.type,
            country=args.country,
            event_id=args.event_id,
            evidence_count=args.evidence_count,
            notes=args.notes,
        )
        save_reputation(data)
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0

    ev = {
        "sourceUrl": args.url,
        "brand": args.brand,
        "type": args.type,
        "country": args.country,
    }
    print(json.dumps(summarize_source(data, ev), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
