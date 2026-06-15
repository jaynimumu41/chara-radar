"""Verify that the committed data is actually published.

Checks:
1. Local HEAD equals origin/main.
2. GitHub Pages data/events.json eventually matches local data/events.json.

This is meant for the daily agent verification step, where edits are committed
after the normal scraper. Without this guard, a local agent commit can exist
while the public site still shows the earlier Python scraper commit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_JSON = ROOT / "data" / "events.json"
PAGES_EVENTS_URL = "https://jaynimumu41.github.io/chara-radar/data/events.json"


def run_git(args: list[str]) -> str:
    return subprocess.check_output(
        ["git", *args],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).strip()


def load_local_events() -> list[dict]:
    return json.loads(EVENTS_JSON.read_text(encoding="utf-8"))


def fetch_json(url: str, timeout: int) -> list[dict]:
    cache_buster = f"cb={int(time.time())}"
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(
        f"{url}{sep}{cache_buster}",
        headers={"User-Agent": "chara-radar-publish-check/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def canonical_events(events: list[dict]) -> str:
    return json.dumps(
        sorted(events, key=lambda e: e.get("id", "")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages-url", default=PAGES_EVENTS_URL)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()

    local_head = run_git(["rev-parse", "HEAD"])
    remote_line = run_git(["ls-remote", "origin", "refs/heads/main"])
    remote_head = remote_line.split()[0] if remote_line else ""
    print(f"local_head={local_head}")
    print(f"remote_head={remote_head}")
    if local_head != remote_head:
        print("ERROR remote main does not match local HEAD; run git push origin main", file=sys.stderr)
        return 1

    local_events = load_local_events()
    local_canon = canonical_events(local_events)
    deadline = time.time() + args.timeout
    attempt = 0
    last_error = ""
    while True:
        attempt += 1
        try:
            online_events = fetch_json(args.pages_url, timeout=45)
            online_canon = canonical_events(online_events)
            print(f"attempt={attempt} online_total={len(online_events)} local_total={len(local_events)}")
            if online_canon == local_canon:
                print("publish_ok=true")
                return 0
            local_ids = {e.get("id") for e in local_events}
            online_ids = {e.get("id") for e in online_events}
            missing = sorted(local_ids - online_ids)
            extra = sorted(online_ids - local_ids)
            last_error = f"events mismatch missing={missing[:8]} extra={extra[:8]}"
        except Exception as exc:
            last_error = str(exc)
            print(f"attempt={attempt} error={last_error}")

        if time.time() >= deadline:
            print(f"ERROR GitHub Pages did not match local events.json: {last_error}", file=sys.stderr)
            return 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
