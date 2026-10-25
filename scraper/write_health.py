"""Write the public status snapshot for the last successful validated run."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import agent_verify_candidates
import scrape


ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
UPDATES_JSON = ROOT / "data" / "today_updates.json"
HEALTH_JSON = ROOT / "data" / "health.json"
LAST_UPDATED_JSON = ROOT / "data" / "last_updated.json"
RUN_METRICS_JSON = ROOT / "scraper" / "run_metrics.json"


def _load(path: Path, fallback):
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _nonnegative(value) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def build_health(
    events: list[dict],
    updates: dict,
    run_metrics: dict,
    *,
    now: datetime | None = None,
) -> dict:
    current = now or datetime.now(scrape.TAIPEI_TZ)
    if current.tzinfo is None:
        current = current.replace(tzinfo=scrape.TAIPEI_TZ)
    current = current.astimezone(scrape.TAIPEI_TZ)

    data_date = str(updates.get("date", ""))
    metrics_date = str(run_metrics.get("runDate", ""))
    if metrics_date and metrics_date != data_date:
        run_metrics = {}

    brands = run_metrics.get("brands", {})
    if not isinstance(brands, dict):
        brands = {}
    public_brands: dict[str, dict] = {}
    for brand in scrape.DEFAULT_BRANDS:
        raw = brands.get(brand, {})
        if not isinstance(raw, dict):
            raw = {}
        public_brands[brand] = {
            "articlesFound": _nonnegative(raw.get("articlesFound")),
            "eligibleArticles": _nonnegative(raw.get("eligibleArticles")),
            "processedArticles": _nonnegative(raw.get("processedArticles")),
            "pendingArticles": _nonnegative(raw.get("pendingArticles")),
            "retryableFailures": _nonnegative(raw.get("retryableFailures")),
            "addedRecords": _nonnegative(raw.get("addedRecords")),
            "capReached": bool(raw.get("capReached", False)),
            "skippedDueRateLimit": bool(raw.get("skippedDueRateLimit", False)),
        }

    pending = sum(row["pendingArticles"] for row in public_brands.values())
    failures = _nonnegative(run_metrics.get("extractionFailureCount"))
    source_failures = run_metrics.get("structuredSourceFailures", [])
    if not isinstance(source_failures, list):
        source_failures = []
    candidates = agent_verify_candidates.build_candidates(events)
    ai_unavailable = bool(run_metrics.get("aiUnavailable", False))
    rate_limited = bool(run_metrics.get("rateLimited", False))
    limited = bool(
        candidates
        or pending
        or failures
        or source_failures
        or ai_unavailable
        or rate_limited
    )
    generated_at = current.isoformat(timespec="seconds")
    return {
        "schemaVersion": 1,
        "status": "limited" if limited else "healthy",
        "generatedAt": generated_at,
        "dataDate": data_date,
        "metrics": {
            "eventCount": len(events),
            "todayNewCount": _nonnegative(updates.get("newEventCount")),
            "agentCandidateCount": len(candidates),
            "pendingArticleCount": pending,
            "extractionFailureCount": failures,
            "structuredSourceFailureCount": len(source_failures),
            "aiBackend": str(run_metrics.get("aiBackend", "unknown")),
            "aiUnavailable": ai_unavailable,
            "keyCount": _nonnegative(run_metrics.get("keyCount")),
            "exhaustedKeyCount": _nonnegative(run_metrics.get("exhaustedKeyCount")),
            "keyRotationCount": _nonnegative(run_metrics.get("keyRotationCount")),
            "rateLimited": rate_limited,
        },
        "brands": public_brands,
        "checks": {
            "scrape": "ok",
            "smoke": "ok",
            "similarity": "ok",
            "lint": "ok",
        },
    }


def write_health(health: dict) -> None:
    text = json.dumps(health, ensure_ascii=False, indent=2) + "\n"
    HEALTH_JSON.write_text(text, encoding="utf-8")
    LAST_UPDATED_JSON.write_text(
        json.dumps({"updatedAt": health["generatedAt"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Write data/health.json after release gates pass.")
    parser.add_argument("--now", help="ISO timestamp override for deterministic testing.")
    args = parser.parse_args()
    now = datetime.fromisoformat(args.now) if args.now else None
    events = _load(EVENTS_JSON, [])
    updates = _load(UPDATES_JSON, {})
    run_metrics = _load(RUN_METRICS_JSON, {})
    health = build_health(events, updates, run_metrics, now=now)
    write_health(health)
    metrics = health["metrics"]
    print(
        f"health={health['status']} events={metrics['eventCount']} "
        f"new={metrics['todayNewCount']} candidates={metrics['agentCandidateCount']} "
        f"pending={metrics['pendingArticleCount']} failures={metrics['extractionFailureCount']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
