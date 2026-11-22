"""Traditional-Chinese display contract for public event data.

Internal ``title`` / ``locationName`` and source metadata stay untouched so
deduplication and official-source audits can use the original wording. Public
translations are bound to a fingerprint of that wording; changed source data
can never silently reuse stale copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
DISPLAY_FIELDS = ("titleZh", "locationNameZh", "summaryZh", "tags")

# Exclude the middle dot (・), which is also an established zh-TW address
# separator. The ranges below contain kana letters, not Japanese punctuation.
KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa\uff66-\uff9d]")
JAPANESE_DISPLAY_RE = re.compile(
    r"[駅浜広沢児関県区号階専売発実応楽焼気国内桜鉄豊静戸歳円処辺栄営条"
    r"会対予来価覧総様旧込舗体転観団数独軽続当点画図学徳帰黒歩毎済読]"
)
JAPANESE_TERM_RE = re.compile(
    r"出張所|整理券|店頭|売り場|売場|発売|開催|取扱い|おみやげ|本舗"
)
SIMPLIFIED_DISPLAY_RE = re.compile(
    r"[宝梦闪车楼层现贩卖这为与门东会国区号发开关体乐来产价优边纪动举办间绒"
    r"钥饮厅预约购赠实场点结网链馆广后个种线华万两页历时对从仅于并该况]"
)

# Future structured-source translations may be added here only under the exact
# source fingerprint printed by the scraper. Never key an override by ID alone.
STRUCTURED_DISPLAY_OVERRIDES: dict[str, dict] = {
    # 2026-11-22 official Chiikawa p26 page. Fingerprint binds the translation
    # to the exact venue, schedule, type, country/city, source title, and flags.
    "fe1d55a0803d74d0f41e": {
        "titleZh": "吉伊卡哇快閃店 水戶 EXCEL 本館",
        "locationNameZh": "水戶 EXCEL 本館",
        "summaryZh": "吉伊卡哇快閃店於水戶 EXCEL 本館期間限定登場，販售限定周邊商品。",
        "tags": ["吉伊卡哇", "快閃店", "日本", "限定周邊"],
    },
    # 2026-11-22 Kiddy Land official miffy style product pages.
    "d6b173ac7cd927949c67": {
        "titleZh": "miffy style 生肖羊系列限定商品",
        "locationNameZh": "miffy style 日本各門市",
        "summaryZh": (
            "miffy style 日本各門市自2026年12月5日起推出生肖羊系列限定商品；"
            "首日每款每筆交易最多購買2個，部分品項與店內贈品僅於實體店提供。"
        ),
        "tags": ["米飛兔", "miffy style", "生肖羊系列", "日本門市新品"],
    },
    "13bfb0aaa2439b24dc40": {
        "titleZh": "miffy style 京都四條河原町店限定巫女造型米飛兔小布偶",
        "locationNameZh": "miffy style 京都四條河原町店",
        "summaryZh": (
            "miffy style 京都四條河原町店自2026年12月5日起販售店舖限定的"
            "巫女造型米飛兔小布偶；每筆交易最多購買2個，解除限購日期未定。"
        ),
        "tags": ["米飛兔", "miffy style", "京都限定", "小布偶", "日本"],
    },
}


def contains_japanese_display(text: str) -> bool:
    value = text or ""
    return bool(
        KANA_RE.search(value)
        or JAPANESE_DISPLAY_RE.search(value)
        or JAPANESE_TERM_RE.search(value)
    )


def contains_simplified_display(text: str) -> bool:
    return bool(SIMPLIFIED_DISPLAY_RE.search(text or ""))


def display_source_fingerprint(event: dict) -> str:
    payload = {
        field: event.get(field, "")
        for field in (
            "brand", "id", "type", "country", "city", "title",
            "locationName", "sourceTitle", "startDate", "endDate",
            "needReservation", "hasLimitedGoods",
        )
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def normalize_zh_display_text(text: str) -> str:
    """Normalize common floor notation for zh-TW readers."""
    value = text or ""
    value = re.sub(r"\bB(\d+)F\b", lambda match: f"地下{match.group(1)}樓", value)
    value = re.sub(r"\b(\d+)F\b", lambda match: f"{match.group(1)}樓", value)
    return value


def _display_values_complete(event: dict) -> bool:
    for field in ("titleZh", "locationNameZh", "summaryZh"):
        value = event.get(field)
        if (
            not isinstance(value, str)
            or not value.strip()
            or contains_japanese_display(value)
            or contains_simplified_display(value)
        ):
            return False
    tags = event.get("tags")
    return bool(
        isinstance(tags, list)
        and all(
            isinstance(tag, str)
            and tag.strip()
            and not contains_japanese_display(tag)
            and not contains_simplified_display(tag)
            for tag in tags
        )
    )


def apply_event_display(
    event: dict,
    *,
    allow_source_copy: bool = False,
    approve_current: bool = False,
) -> dict:
    """Normalize zh-TW copy and stamp it only through an explicit trust path.

    Normal saves must never bless existing copy after the source fingerprint
    changes.  A stamp is created only for an exact structured override, newly
    approved AI/manual copy, or copy whose existing stamp already matches.
    """
    fingerprint = display_source_fingerprint(event)
    override_applied = fingerprint in STRUCTURED_DISPLAY_OVERRIDES
    override = STRUCTURED_DISPLAY_OVERRIDES.get(fingerprint, {})
    for field, value in override.items():
        event[field] = value[:] if isinstance(value, list) else value

    if allow_source_copy:
        if not event.get("titleZh") and not contains_japanese_display(event.get("title", "")):
            event["titleZh"] = event.get("title", "")
        if not event.get("locationNameZh") and not contains_japanese_display(event.get("locationName", "")):
            event["locationNameZh"] = event.get("locationName", "")

    for field in ("titleZh", "locationNameZh", "summaryZh"):
        if isinstance(event.get(field), str):
            event[field] = normalize_zh_display_text(event[field])
    if isinstance(event.get("tags"), list):
        event["tags"] = [
            normalize_zh_display_text(tag) if isinstance(tag, str) else tag
            for tag in event["tags"]
        ]

    existing_stamp_matches = event.get("displaySourceHash") == fingerprint
    if _display_values_complete(event) and (
        override_applied or approve_current or existing_stamp_matches
    ):
        event["displaySourceHash"] = fingerprint
    else:
        event.pop("displaySourceHash", None)
    return event


def carry_event_display(previous: dict, current: dict) -> bool:
    """Carry verified copy only when the complete raw identity is unchanged."""
    fingerprint = display_source_fingerprint(current)
    if previous.get("displaySourceHash") != fingerprint:
        return False
    if event_display_errors(previous):
        return False
    for field in DISPLAY_FIELDS:
        value = previous.get(field)
        current[field] = value[:] if isinstance(value, list) else value
    current["displaySourceHash"] = fingerprint
    return True


def event_display_errors(event: dict) -> list[str]:
    event_id = event.get("id", "<missing-id>")
    errors: list[str] = []
    for field in ("titleZh", "locationNameZh", "summaryZh"):
        value = event.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{event_id}: blank public display field {field}")
        elif contains_japanese_display(value):
            errors.append(f"{event_id}: public display field {field} contains Japanese: {value}")
        elif contains_simplified_display(value):
            errors.append(f"{event_id}: public display field {field} contains simplified Chinese: {value}")
    tags = event.get("tags")
    if not isinstance(tags, list):
        errors.append(f"{event_id}: public display field tags must be an array")
    else:
        for tag in tags:
            if not isinstance(tag, str) or not tag.strip():
                errors.append(f"{event_id}: public display tags contains a blank/non-string value")
            elif contains_japanese_display(tag):
                errors.append(f"{event_id}: public display tag contains Japanese: {tag}")
            elif contains_simplified_display(tag):
                errors.append(f"{event_id}: public display tag contains simplified Chinese: {tag}")

    expected_hash = display_source_fingerprint(event)
    actual_hash = event.get("displaySourceHash", "")
    if actual_hash != expected_hash:
        errors.append(
            f"{event_id}: stale public translation fingerprint: "
            f"expected {expected_hash}, got {actual_hash or '<missing>'}"
        )
    return errors


def migrate_events(path: Path = EVENTS_JSON) -> int:
    """Stamp existing reviewed translations; does not invent missing copy."""
    events = json.loads(path.read_text(encoding="utf-8-sig"))
    for event in events:
        apply_event_display(event, allow_source_copy=True, approve_current=True)
    path.write_text(
        json.dumps(events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return len(events)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-events", action="store_true")
    args = parser.parse_args()
    if not args.write_events:
        parser.error("pass --write-events to stamp reviewed data/events.json")
    print(f"events_migrated={migrate_events()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
