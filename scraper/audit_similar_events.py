"""Block publication when high-confidence duplicate event pairs remain."""
from __future__ import annotations

import argparse
import json
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

import scrape


EVENTS_JSON = Path(__file__).resolve().parents[1] / "data" / "events.json"


def _norm(value: str) -> str:
    return scrape._norm(value or "")


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _ranges_overlap(left: dict, right: dict) -> bool:
    left_start = _date(left.get("startDate", ""))
    right_start = _date(right.get("startDate", ""))
    if not left_start or not right_start:
        return False
    left_end = _date(left.get("endDate", "")) or left_start
    right_end = _date(right.get("endDate", "")) or right_start
    return max(left_start, right_start) <= min(left_end, right_end)


def _parent_child(left: dict, right: dict) -> bool:
    left_id = str(left.get("id", ""))
    right_id = str(right.get("id", ""))
    return (
        str(left.get("parentEventId", "")) == right_id
        or str(right.get("parentEventId", "")) == left_id
    )


def suspicious_pair(left: dict, right: dict) -> dict | None:
    """Return only pairs strong enough to stop automatic publication."""
    if left.get("brand") != right.get("brand") or _parent_child(left, right):
        return None
    if left.get("id") and left.get("id") == right.get("id"):
        return None

    left_title = str(left.get("title", ""))
    right_title = str(right.get("title", ""))
    title_score = SequenceMatcher(None, _norm(left_title), _norm(right_title)).ratio()

    if (
        scrape.is_same_event_for_update_diff(left, right)
        or scrape.is_same_event_for_update_diff(right, left)
    ):
        return {
            "leftId": str(left.get("id", "")),
            "rightId": str(right.get("id", "")),
            "brand": str(left.get("brand", "")),
            "score": round(title_score, 3),
            "reason": "deterministic same-event matcher",
            "leftTitle": left_title,
            "rightTitle": right_title,
        }

    if (
        left.get("type") not in scrape.ACTIVITY_TYPES
        or right.get("type") not in scrape.ACTIVITY_TYPES
        or not _ranges_overlap(left, right)
    ):
        return None

    left_loc = str(left.get("locationName", ""))
    right_loc = str(right.get("locationName", ""))
    left_canon = scrape.canon_venue(left_loc, left_title)
    right_canon = scrape.canon_venue(right_loc, right_title)
    same_canon = bool(left_canon and left_canon == right_canon)
    location_match = scrape.location_compatibility(
        left_loc, right_loc, left_title, right_title
    )

    # This catches the common media-error case where the activity and known
    # venue match but one article assigned the wrong city.
    if same_canon and title_score >= 0.40:
        reason = "same known venue, overlapping dates, and similar titles"
        if (
            left.get("city")
            and right.get("city")
            and left.get("city") != right.get("city")
        ):
            reason += " with conflicting cities"
        return {
            "leftId": str(left.get("id", "")),
            "rightId": str(right.get("id", "")),
            "brand": str(left.get("brand", "")),
            "score": round(title_score, 3),
            "reason": reason,
            "leftTitle": left_title,
            "rightTitle": right_title,
        }

    if location_match is True and title_score >= 0.55:
        return {
            "leftId": str(left.get("id", "")),
            "rightId": str(right.get("id", "")),
            "brand": str(left.get("brand", "")),
            "score": round(title_score, 3),
            "reason": "same concrete venue, overlapping dates, and similar titles",
            "leftTitle": left_title,
            "rightTitle": right_title,
        }
    return None


def find_suspicious_pairs(events: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for index, left in enumerate(events):
        for right in events[index + 1:]:
            row = suspicious_pair(left, right)
            if row:
                rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Find high-confidence duplicates that survived normal cleanup."
    )
    parser.add_argument("--format", choices=("text", "markdown", "json"), default="text")
    parser.add_argument("--fail-on-review", action="store_true")
    args = parser.parse_args()

    events = json.loads(EVENTS_JSON.read_text(encoding="utf-8-sig"))
    rows = find_suspicious_pairs(events)
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print("# Similar event release gate")
        print()
        print(f"- Events: {len(events)}")
        print(f"- Needs review: {len(rows)}")
        for row in rows:
            print(
                f"- **{row['leftId']} / {row['rightId']}** "
                f"({row['brand']}, score={row['score']}): {row['reason']}"
            )
            print(f"  - {row['leftTitle']}")
            print(f"  - {row['rightTitle']}")
    else:
        print(f"events={len(events)} needs_review={len(rows)}")
        for row in rows:
            print(
                f"REVIEW {row['leftId']} {row['rightId']} "
                f"score={row['score']} reason={row['reason']}"
            )

    if args.fail_on_review and rows:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
