"""Validate chara-radar data files without network or AI calls."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import scrape

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
STORES_JSON = ROOT / "data" / "stores.json"
TODAY_UPDATES_JSON = ROOT / "data" / "today_updates.json"
LAST_UPDATED_JSON = ROOT / "data" / "last_updated.json"

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

    if STORES_JSON.exists():
        stores = load_json(STORES_JSON)
        if isinstance(stores, dict):
            paused = sorted(PAUSED_BRANDS.intersection(stores.keys()))
            if paused:
                errors.append(f"paused brands remain in stores.json: {', '.join(paused)}")
        else:
            errors.append("data/stores.json must be a JSON object")

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
                errors.extend(today_update_count_errors(events, updates, [str(x) for x in new_event_ids]))
                counts = Counter(e.get("brand", "") for e in events if e.get("id") in set(new_event_ids))
                counts_by_brand = updates.get("countsByBrand", {})
                if isinstance(counts_by_brand, dict):
                    for brand in ACTIVE_BRANDS:
                        if int(counts_by_brand.get(brand, 0)) != counts.get(brand, 0):
                            errors.append(f"today_updates.json count mismatch for {brand}")
                errors.extend(today_update_duplicate_errors(events, [str(x) for x in new_event_ids]))
        except Exception as exc:
            errors.append(f"today_updates.json is not parseable: {exc}")

    if LAST_UPDATED_JSON.exists():
        try:
            updated_at = load_json(LAST_UPDATED_JSON).get("updatedAt", "")
            if updated_at:
                datetime.fromisoformat(updated_at)
        except Exception as exc:
            warnings.append(f"last_updated.json is not parseable: {exc}")

    print(f"events={len(events)} active_brands={','.join(scrape.DEFAULT_BRANDS)}")
    for warning in warnings:
        print(f"WARN  {warning}")
    for error in errors:
        print(f"ERROR {error}")
    print(f"lint: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
