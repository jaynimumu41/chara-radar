"""Validate chara-radar data files without network or AI calls."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import scrape
import agent_verify_candidates

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
STORES_JSON = ROOT / "data" / "stores.json"
TODAY_UPDATES_JSON = ROOT / "data" / "today_updates.json"
LAST_UPDATED_JSON = ROOT / "data" / "last_updated.json"
HEALTH_JSON = ROOT / "data" / "health.json"

ACTIVE_BRANDS = set(scrape.DEFAULT_BRANDS)
PAUSED_BRANDS = {"sanrio"}
ALLOWED_TYPES = {"popup", "new_product", "campaign", "store", "cafe", "lottery", "reservation"}
ALLOWED_COUNTRIES = {"JP", "TW"}
REQUIRED_FIELDS = (
    "brand", "title", "type", "country", "city", "locationName", "startDate", "endDate",
    "summaryZh", "needReservation", "hasLimitedGoods", "tags", "id", "sourceType",
    "createdAt", "sourceUrl", "sourceTitle",
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
OPENING_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")
STORE_SOURCE_URLS = {
    "pokemon": {"https://www.pokemon.co.jp/shop/"},
    "miffy": {"https://dickbruna.jp/shop/"},
    "chiikawa": {
        "https://chiikawa-info.jp/ck_land",
        "https://chiikawa-info.jp/magical_s.html",
        "https://chiikawa-info.jp/s_fes.html",
        "https://www.chiikawamogumogu.jp/page-sitemap.xml",
        "https://www.chiikawa-yaki.com/",
        "https://chiikawabakery.jp/",
        "https://chiikawapark-tokyo.jp/",
        "https://chiikawapark-tokyo.jp/news/x0e64eb94v/",
        "https://chiikawa-info.jp/ck_w/taipei/index.html",
    },
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def norm(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").lower())


def valid_date(value: str) -> bool:
    if not value:
        return True
    if not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def store_data_errors(data: dict) -> list[str]:
    """Validate permanent-store structure and auditable official identities."""
    if not isinstance(data, dict):
        return ["data/stores.json must be a JSON object"]

    errors: list[str] = []
    missing_brands = sorted(ACTIVE_BRANDS.difference(data.keys()))
    if missing_brands:
        errors.append(f"stores.json missing active brands: {', '.join(missing_brands)}")

    for brand in sorted(ACTIVE_BRANDS.intersection(data.keys())):
        brand_data = data.get(brand)
        if not isinstance(brand_data, dict):
            errors.append(f"stores.json {brand} must be an object")
            continue
        if brand_data.get("linksOnly"):
            continue
        groups = brand_data.get("groups")
        if not isinstance(groups, list):
            errors.append(f"stores.json {brand}.groups must be an array")
            continue

        display_names: defaultdict[str, list[str]] = defaultdict(list)
        official_names: defaultdict[str, list[str]] = defaultdict(list)
        for group_index, group in enumerate(groups):
            prefix = f"stores.json {brand}.groups[{group_index}]"
            if not isinstance(group, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not group.get("label"):
                errors.append(f"{prefix} has blank label")
            rows = group.get("stores")
            if not isinstance(rows, list) or not rows:
                errors.append(f"{prefix}.stores must be a non-empty array")
                continue
            for store_index, store in enumerate(rows):
                row_prefix = f"{prefix}.stores[{store_index}]"
                if not isinstance(store, dict):
                    errors.append(f"{row_prefix} must be an object")
                    continue
                for field in ("name", "area", "country"):
                    if not store.get(field):
                        errors.append(f"{row_prefix} has blank {field}")
                if store.get("country") not in ALLOWED_COUNTRIES:
                    errors.append(f"{row_prefix} has invalid country: {store.get('country')}")
                if store.get("name"):
                    display_names[norm(store["name"])].append(store["name"])
                official_name = store.get("officialName", "")
                if not official_name:
                    errors.append(f"{row_prefix} has blank officialName")
                else:
                    official_names[norm(official_name)].append(official_name)
                opening = store.get("opening", "")
                if opening:
                    if not OPENING_RE.match(opening):
                        errors.append(f"{row_prefix} has invalid opening: {opening}")
                    else:
                        try:
                            datetime.strptime(opening, "%Y/%m/%d")
                        except ValueError:
                            errors.append(f"{row_prefix} has invalid opening: {opening}")

        for names in display_names.values():
            if len(names) > 1:
                errors.append(f"stores.json duplicate {brand} store name: {', '.join(names)}")
        for names in official_names.values():
            if len(names) > 1:
                errors.append(
                    f"stores.json duplicate {brand} officialName: {', '.join(names)}"
                )

        expected_sources = STORE_SOURCE_URLS.get(brand, set())
        actual_sources = brand_data.get("sourceUrls")
        if not isinstance(actual_sources, list):
            actual_sources = [brand_data.get("sourceUrl", "")]
        actual_sources = {url for url in actual_sources if isinstance(url, str) and url}
        missing_sources = sorted(expected_sources.difference(actual_sources))
        if missing_sources:
            errors.append(
                f"stores.json {brand} missing official source URLs: {', '.join(missing_sources)}"
            )
        checked_at = brand_data.get("sourceCheckedAt", "")
        if not checked_at or not valid_date(checked_at):
            errors.append(f"stores.json {brand}.sourceCheckedAt is invalid: {checked_at}")
    return errors


def today_update_duplicate_errors(events: list[dict], new_event_ids: list[str]) -> list[str]:
    """Flag newEventIds that still duplicate another visible event."""
    by_id = {ev.get("id", ""): ev for ev in events if isinstance(ev, dict)}
    errors: list[str] = []
    for new_id in new_event_ids:
        ev = by_id.get(str(new_id))
        if not ev:
            continue
        for other in events:
            if not isinstance(other, dict) or other.get("id") == ev.get("id"):
                continue
            if scrape.is_same_event_for_update_diff(other, ev):
                errors.append(
                    "today_updates.json marks duplicate as new: "
                    f"{ev.get('id')} duplicates existing {other.get('id')}"
                )
                break
    return errors


def today_update_count_errors(events: list[dict], updates: dict, new_event_ids: list[str]) -> list[str]:
    """Keep summary counts synchronized with the public event data."""
    errors: list[str] = []
    if updates.get("currentEventCount") != len(events):
        errors.append(
            "today_updates.json currentEventCount mismatch: "
            f"expected {len(events)}, got {updates.get('currentEventCount')}"
        )
    if updates.get("newEventCount") != len(new_event_ids):
        errors.append(
            "today_updates.json newEventCount mismatch: "
            f"expected {len(new_event_ids)}, got {updates.get('newEventCount')}"
        )
    return errors


def today_update_date_errors(updates: dict) -> list[str]:
    """Require each daily diff to compare against an earlier public date."""
    errors: list[str] = []
    update_date = str(updates.get("date", ""))
    baseline_date = str(updates.get("baselineDate", ""))
    if not valid_date(update_date):
        errors.append(f"today_updates.json date is invalid: {update_date}")
    if not valid_date(baseline_date):
        errors.append(f"today_updates.json baselineDate is invalid: {baseline_date}")
    elif valid_date(update_date) and baseline_date >= update_date:
        errors.append(
            "today_updates.json baselineDate must be earlier than date: "
            f"{baseline_date} >= {update_date}"
        )
    return errors


def stable_identity_duplicate_errors(events: list[dict]) -> list[str]:
    """Reject duplicate rows for activities with a deterministic real-world identity."""
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for ev in events:
        if not isinstance(ev, dict):
            continue
        identity = scrape.special_activity_key(ev)
        if identity:
            groups[identity].append(str(ev.get("id", "")))
    return [
        f"duplicate stable event identity {identity}: {', '.join(event_ids)}"
        for identity, event_ids in groups.items()
        if len(event_ids) > 1
    ]


def event_hierarchy_errors(events: list[dict]) -> list[str]:
    """Validate one-level parent/child grouping without weakening event identity."""
    by_id = {
        str(ev.get("id", "")): ev
        for ev in events
        if isinstance(ev, dict) and ev.get("id")
    }
    errors: list[str] = []
    for child_id, child in by_id.items():
        parent_id = child.get("parentEventId")
        if parent_id is None:
            continue
        if not isinstance(parent_id, str) or not parent_id:
            errors.append(f"{child_id}: parentEventId must be a non-empty string")
            continue
        if parent_id == child_id:
            errors.append(f"{child_id}: event cannot be its own parent")
            continue
        parent = by_id.get(parent_id)
        if not parent:
            errors.append(f"{child_id}: parentEventId references missing event {parent_id}")
            continue
        if parent.get("parentEventId"):
            errors.append(f"{child_id}: nested event hierarchy is not supported")
        if parent.get("brand") != child.get("brand"):
            errors.append(f"{child_id}: parent {parent_id} has a different brand")
        if parent.get("country") != child.get("country"):
            errors.append(f"{child_id}: parent {parent_id} has a different country")
        parent_start, parent_end = parent.get("startDate", ""), parent.get("endDate", "")
        child_start, child_end = child.get("startDate", ""), child.get("endDate", "")
        if parent_end and child_start and child_start > parent_end:
            errors.append(f"{child_id}: starts after parent {parent_id} ends")
        if child_end and parent_start and child_end < parent_start:
            errors.append(f"{child_id}: ends before parent {parent_id} starts")
    return errors


def replacement_mapping_errors(updates: dict) -> list[str]:
    """Replacement rows must form a one-to-one mapping between old and current IDs."""
    replacements = updates.get("replacements", [])
    if not isinstance(replacements, list):
        return ["today_updates.json replacements must be an array"]

    errors: list[str] = []
    from_ids: Counter[str] = Counter()
    to_ids: Counter[str] = Counter()
    for index, replacement in enumerate(replacements, 1):
        if not isinstance(replacement, dict):
            errors.append(f"today_updates.json replacement #{index} must be an object")
            continue
        from_id = str(replacement.get("from", ""))
        to_id = str(replacement.get("to", ""))
        if not from_id or not to_id:
            errors.append(f"today_updates.json replacement #{index} has a blank id")
            continue
        from_ids[from_id] += 1
        to_ids[to_id] += 1
    for event_id, count in from_ids.items():
        if count > 1:
            errors.append(f"today_updates.json replacement source reused: {event_id} ({count})")
    for event_id, count in to_ids.items():
        if count > 1:
            errors.append(f"today_updates.json replacement target reused: {event_id} ({count})")
    return errors


def health_data_errors(
    events: list[dict],
    updates: dict,
    health: dict,
    last_updated: dict,
) -> list[str]:
    """Keep the public operational snapshot consistent with formal data."""
    if not isinstance(health, dict):
        return ["data/health.json must be a JSON object"]
    errors: list[str] = []
    if health.get("schemaVersion") != 1:
        errors.append("health.json schemaVersion must be 1")
    if health.get("status") not in {"healthy", "limited"}:
        errors.append(f"health.json status is invalid: {health.get('status')!r}")

    generated_at = str(health.get("generatedAt", ""))
    try:
        datetime.fromisoformat(generated_at)
    except ValueError:
        errors.append(f"health.json generatedAt is invalid: {generated_at!r}")
    if str(last_updated.get("updatedAt", "")) != generated_at:
        errors.append("health.json generatedAt must match last_updated.json updatedAt")

    data_date = str(health.get("dataDate", ""))
    if not data_date or not valid_date(data_date):
        errors.append(f"health.json dataDate is invalid: {data_date!r}")
    if isinstance(updates, dict) and data_date != str(updates.get("date", "")):
        errors.append(
            "health.json dataDate must match today_updates.json date: "
            f"{data_date!r} != {updates.get('date', '')!r}"
        )

    metrics = health.get("metrics")
    if not isinstance(metrics, dict):
        errors.append("health.json metrics must be an object")
        metrics = {}
    numeric_fields = (
        "eventCount", "todayNewCount", "agentCandidateCount",
        "pendingArticleCount", "extractionFailureCount",
        "structuredSourceFailureCount", "keyCount",
        "exhaustedKeyCount", "keyRotationCount",
    )
    for field in numeric_fields:
        value = metrics.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"health.json metrics.{field} must be a non-negative integer")
    if metrics.get("eventCount") != len(events):
        errors.append(
            f"health.json eventCount mismatch: expected {len(events)}, "
            f"got {metrics.get('eventCount')}"
        )
    if isinstance(updates, dict) and metrics.get("todayNewCount") != updates.get("newEventCount"):
        errors.append(
            "health.json todayNewCount mismatch: "
            f"expected {updates.get('newEventCount')}, got {metrics.get('todayNewCount')}"
        )
    candidate_count = len(agent_verify_candidates.build_candidates(events))
    if metrics.get("agentCandidateCount") != candidate_count:
        errors.append(
            "health.json agentCandidateCount mismatch: "
            f"expected {candidate_count}, got {metrics.get('agentCandidateCount')}"
        )

    limited = bool(
        metrics.get("agentCandidateCount")
        or metrics.get("pendingArticleCount")
        or metrics.get("extractionFailureCount")
        or metrics.get("structuredSourceFailureCount")
        or metrics.get("aiUnavailable")
        or metrics.get("rateLimited")
    )
    expected_status = "limited" if limited else "healthy"
    if health.get("status") != expected_status:
        errors.append(
            f"health.json status mismatch: expected {expected_status}, "
            f"got {health.get('status')}"
        )

    brands = health.get("brands")
    if not isinstance(brands, dict):
        errors.append("health.json brands must be an object")
        brands = {}
    missing_brands = sorted(ACTIVE_BRANDS.difference(brands.keys()))
    if missing_brands:
        errors.append(f"health.json missing brands: {', '.join(missing_brands)}")
    pending_sum = 0
    for brand in ACTIVE_BRANDS.intersection(brands.keys()):
        row = brands.get(brand)
        if not isinstance(row, dict):
            errors.append(f"health.json brands.{brand} must be an object")
            continue
        value = row.get("pendingArticles")
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(
                f"health.json brands.{brand}.pendingArticles must be a non-negative integer"
            )
        else:
            pending_sum += value
    if metrics.get("pendingArticleCount") != pending_sum:
        errors.append(
            "health.json pendingArticleCount mismatch: "
            f"expected {pending_sum}, got {metrics.get('pendingArticleCount')}"
        )

    checks = health.get("checks")
    expected_checks = {"scrape", "smoke", "similarity", "lint"}
    if not isinstance(checks, dict) or any(checks.get(name) != "ok" for name in expected_checks):
        errors.append("health.json checks must mark scrape, smoke, similarity, and lint as ok")
    return errors


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    events = load_json(EVENTS_JSON)
    if not isinstance(events, list):
        errors.append("data/events.json must be a JSON array")
        events = []

    ids = Counter(e.get("id", "") for e in events if isinstance(e, dict))
    for id_, count in ids.items():
        if id_ and count > 1:
            errors.append(f"duplicate event id: {id_} ({count})")

    duplicate_keys: defaultdict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    for idx, ev in enumerate(events, 1):
        if not isinstance(ev, dict):
            errors.append(f"event #{idx} is not an object")
            continue

        missing = [f for f in REQUIRED_FIELDS if f not in ev]
        if missing:
            errors.append(f"{ev.get('id', '#' + str(idx))}: missing fields {', '.join(missing)}")

        brand = ev.get("brand", "")
        if brand in PAUSED_BRANDS:
            errors.append(f"{ev.get('id', '#' + str(idx))}: paused brand remains in events.json: {brand}")
        elif brand not in ACTIVE_BRANDS:
            errors.append(f"{ev.get('id', '#' + str(idx))}: unknown brand: {brand}")

        if ev.get("type") not in ALLOWED_TYPES:
            errors.append(f"{ev.get('id', '#' + str(idx))}: invalid type: {ev.get('type')}")
        if ev.get("country") not in ALLOWED_COUNTRIES:
            errors.append(f"{ev.get('id', '#' + str(idx))}: invalid country: {ev.get('country')}")

        sd, ed = ev.get("startDate", ""), ev.get("endDate", "")
        if not valid_date(sd):
            errors.append(f"{ev.get('id', '#' + str(idx))}: invalid startDate: {sd}")
        if not valid_date(ed):
            errors.append(f"{ev.get('id', '#' + str(idx))}: invalid endDate: {ed}")
        if sd and ed and valid_date(sd) and valid_date(ed) and ed < sd:
            errors.append(f"{ev.get('id', '#' + str(idx))}: endDate before startDate")

        if not ev.get("title"):
            errors.append(f"{ev.get('id', '#' + str(idx))}: blank title")
        if not ev.get("sourceUrl"):
            warnings.append(f"{ev.get('id', '#' + str(idx))}: blank sourceUrl")
        if ev.get("sourceUrl", "").lower().endswith(".env"):
            errors.append(f"{ev.get('id', '#' + str(idx))}: sourceUrl points to .env")

        key = (
            brand,
            norm(ev.get("locationName", "")),
            ev.get("startDate", ""),
            ev.get("endDate", ""),
            norm(ev.get("title", ""))[:24],
        )
        if key[0] and (key[1] or key[2] or key[4]):
            duplicate_keys[key].append(ev.get("id", "#" + str(idx)))

    for key, ids_for_key in duplicate_keys.items():
        if len(ids_for_key) > 1:
            warnings.append(f"possible duplicate cluster {key}: {', '.join(ids_for_key)}")

    errors.extend(stable_identity_duplicate_errors(events))
    errors.extend(event_hierarchy_errors(events))

    if STORES_JSON.exists():
        stores = load_json(STORES_JSON)
        if isinstance(stores, dict):
            paused = sorted(PAUSED_BRANDS.intersection(stores.keys()))
            if paused:
                errors.append(f"paused brands remain in stores.json: {', '.join(paused)}")
        errors.extend(store_data_errors(stores))

    updates: dict = {}
    if TODAY_UPDATES_JSON.exists():
        try:
            updates = load_json(TODAY_UPDATES_JSON)
            if not isinstance(updates, dict):
                errors.append("data/today_updates.json must be a JSON object")
            else:
                event_ids = set(ids.keys())
                new_event_ids = updates.get("newEventIds", [])
                if not isinstance(new_event_ids, list):
                    errors.append("today_updates.json newEventIds must be an array")
                    new_event_ids = []
                missing_update_ids = sorted(str(x) for x in new_event_ids if x not in event_ids)
                if missing_update_ids:
                    errors.append(f"today_updates.json references missing event ids: {', '.join(missing_update_ids)}")
                errors.extend(today_update_date_errors(updates))
                errors.extend(today_update_count_errors(events, updates, [str(x) for x in new_event_ids]))
                errors.extend(replacement_mapping_errors(updates))
                counts = Counter(e.get("brand", "") for e in events if e.get("id") in set(new_event_ids))
                counts_by_brand = updates.get("countsByBrand", {})
                if isinstance(counts_by_brand, dict):
                    for brand in ACTIVE_BRANDS:
                        if int(counts_by_brand.get(brand, 0)) != counts.get(brand, 0):
                            errors.append(f"today_updates.json count mismatch for {brand}")
                errors.extend(today_update_duplicate_errors(events, [str(x) for x in new_event_ids]))
        except Exception as exc:
            errors.append(f"today_updates.json is not parseable: {exc}")

    last_updated: dict = {}
    if LAST_UPDATED_JSON.exists():
        try:
            last_updated = load_json(LAST_UPDATED_JSON)
            updated_at = last_updated.get("updatedAt", "")
            if updated_at:
                datetime.fromisoformat(updated_at)
        except Exception as exc:
            last_updated = {}
            errors.append(f"last_updated.json is not parseable: {exc}")

    if not HEALTH_JSON.exists():
        errors.append("data/health.json is missing")
    else:
        try:
            health = load_json(HEALTH_JSON)
            errors.extend(health_data_errors(events, updates, health, last_updated))
        except Exception as exc:
            errors.append(f"health.json is not parseable: {exc}")

    print(f"events={len(events)} active_brands={','.join(scrape.DEFAULT_BRANDS)}")
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"lint: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
