"""用地點關鍵字對照表修正現有 events.json 的城市（不花配額）。"""
import json
from pathlib import Path
import scrape

EVENTS = Path(__file__).parent.parent / "data" / "events.json"
d = json.loads(EVENTS.read_text(encoding="utf-8"))

changed = 0
for e in d:
    fixed = scrape.correct_city(e.get("locationName"), e.get("title"))
    old = e.get("city") or "—"
    if fixed and fixed != e.get("city"):
        print(f"  修正: {e['title'][:24]}  {old} → {fixed}  (loc={e.get('locationName')})")
        e["city"] = fixed
        changed += 1

EVENTS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n共修正 {changed} 筆城市")
