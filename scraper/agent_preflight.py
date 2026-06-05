"""Preflight checks for the daily Codex agent verification automation."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "scraper" / "logs"
LAST_UPDATED_JSON = ROOT / "data" / "last_updated.json"
TW = timezone(timedelta(hours=8))


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)
    print(f"ERROR {message}")


def run_git(args: list[str]) -> tuple[int, str]:
    cmd = ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), *args]
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout.strip()


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Check whether daily scrape finished before agent verification.")
    parser.add_argument("--min-hour", type=int, default=16, help="Minimum local hour expected in last_updated.json.")
    parser.add_argument("--allow-dirty", action="store_true", help="Do not fail on a dirty git worktree.")
    args = parser.parse_args()

    errors: list[str] = []
    now = datetime.now(TW)
    today = now.strftime("%Y-%m-%d")
    print(f"preflight date={today} now={now.strftime('%H:%M:%S %z')}")

    if not LAST_UPDATED_JSON.exists():
        fail("data/last_updated.json is missing", errors)
    else:
        try:
            updated_raw = json.loads(LAST_UPDATED_JSON.read_text(encoding="utf-8-sig")).get("updatedAt", "")
            updated = parse_iso(updated_raw)
            if not updated:
                fail(f"data/last_updated.json updatedAt is invalid: {updated_raw!r}", errors)
            else:
                updated_tw = updated.astimezone(TW) if updated.tzinfo else updated.replace(tzinfo=TW)
                print(f"last_updated={updated_tw.isoformat()}")
                if updated_tw.date() != now.date():
                    fail(f"last_updated is not today: {updated_tw.date().isoformat()}", errors)
                if updated_tw.hour < args.min_hour:
                    fail(f"last_updated is before {args.min_hour}:00 local time", errors)
        except Exception as exc:
            fail(f"cannot read data/last_updated.json: {exc}", errors)

    scrape_log = LOG_DIR / f"scrape-{today}.log"
    if not scrape_log.exists():
        fail(f"today scrape log is missing: {scrape_log}", errors)
    else:
        text = scrape_log.read_text(encoding="utf-8", errors="replace")
        matches = re.findall(r"SCRAPE EXIT CODE:\s*(-?\d+)", text)
        if not matches:
            fail("today scrape log has no SCRAPE EXIT CODE", errors)
        elif matches[-1] != "0":
            fail(f"latest scrape exit code is {matches[-1]}", errors)
        else:
            print("scrape_exit_code=0")

    code, branch = run_git(["branch", "--show-current"])
    if code != 0:
        fail(f"git branch check failed: {branch}", errors)
    elif branch != "main":
        fail(f"current branch is {branch!r}, expected 'main'", errors)
    else:
        print("branch=main")

    code, status = run_git(["status", "--short"])
    if code != 0:
        fail(f"git status failed: {status}", errors)
    elif status and not args.allow_dirty:
        fail("git worktree is dirty before agent verification", errors)
        print(status)
    else:
        print("worktree=clean" if not status else "worktree=dirty_allowed")

    print(f"preflight: {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
