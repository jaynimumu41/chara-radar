"""Shared helpers for permanent-store coverage audits."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
import unicodedata


@dataclass(frozen=True)
class OfficialStore:
    name: str
    category: str = ""
    address: str = ""


@dataclass(frozen=True)
class AuditResult:
    official_count: int
    local_count: int
    missing: tuple[str, ...]
    stale: tuple[str, ...]
    duplicates: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.stale or self.duplicates)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_name(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return re.sub(r"\s+", "", normalized)


def load_local_official_names(brand: str, path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    names: list[str] = []
    for group in data.get(brand, {}).get("groups", []):
        for store in group.get("stores", []):
            official_name = clean(store.get("officialName", ""))
            if official_name:
                names.append(official_name)
    return names


def audit_stores(official: list[OfficialStore], local_names: list[str]) -> AuditResult:
    official_by_key = {normalize_name(store.name): store.name for store in official}
    local_by_key = {normalize_name(name): name for name in local_names if normalize_name(name)}
    local_counts = Counter(normalize_name(name) for name in local_names if normalize_name(name))

    missing = tuple(
        store.name for store in official if normalize_name(store.name) not in local_by_key
    )
    stale = tuple(
        name for name in local_names if normalize_name(name) not in official_by_key
    )
    duplicates = tuple(
        local_by_key[key] for key, count in local_counts.items() if count > 1
    )
    return AuditResult(
        official_count=len(official),
        local_count=len(local_names),
        missing=missing,
        stale=stale,
        duplicates=duplicates,
    )


def print_result(result: AuditResult, output_format: str) -> None:
    status = "ok" if result.ok else "needs_review"
    print(
        f"status={status} official={result.official_count} local={result.local_count} "
        f"missing={len(result.missing)} stale={len(result.stale)} "
        f"duplicates={len(result.duplicates)}"
    )
    if output_format == "summary" or result.ok:
        return

    rows = (
        [("missing", name) for name in result.missing]
        + [("stale", name) for name in result.stale]
        + [("duplicate", name) for name in result.duplicates]
    )
    if output_format == "markdown":
        print("\n| Status | Official name |")
        print("| -- | -- |")
        for row_status, name in rows:
            print(f"| {row_status} | {name} |")
        return
    for row_status, name in rows:
        print(f"{row_status.upper():9} {name}")
