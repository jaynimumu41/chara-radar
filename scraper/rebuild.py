"""把現有真實資料的來源重新解析成『直接文章連結』。
作法：用「地點+品牌」去 Google News RSS 搜尋，取最相關一篇、解碼成真實 URL。
有品牌關鍵字把關才採用，否則退回搜尋連結。不呼叫 AI、不花配額。
"""
import json
import time
from pathlib import Path
import scrape

EVENTS = Path(__file__).parent.parent / "data" / "events.json"
d = json.loads(EVENTS.read_text(encoding="utf-8"))

def brand_kw(e):
    return scrape.BRAND_KEYWORDS.get(e["brand"], [])

direct, fallback = 0, 0
for e in d:
    q = scrape.best_search_query(e)
    is_tw = e.get("country") == "TW"
    items = scrape.fetch_rss(q, is_tw)
    real_url = None
    # 取前 3 篇中，標題含品牌關鍵字的第一篇來解碼
    for it in items[:3]:
        tl = it["title"].lower()
        if any(k.lower() in tl for k in brand_kw(e)):
            real_url = scrape.decode_google_news_url(it["link"])
            if real_url:
                matched_title = it["title"]
                break
    time.sleep(0.4)
    if real_url:
        e["sourceUrl"] = real_url
        e["sourceTitle"] = matched_title
        direct += 1
        print(f"  ✅ {e['title'][:26]}")
        print(f"      -> {real_url[:70]}")
    else:
        e["sourceUrl"] = scrape.search_url(q)
        fallback += 1
        print(f"  🔍 {e['title'][:26]}（退回搜尋）")

EVENTS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\n完成！直連 {direct} 筆、搜尋退路 {fallback} 筆，共 {len(d)} 筆")
