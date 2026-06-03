"""官方／權威來源直抓（分階段建立）。

用意：額度有限，先抓「一定正確」的官方來源，再用 Google News 補官方沒寫的。
這些來源回傳的 item 格式與 scrape.fetch_rss 相同（title/link/pubDate/description/source），
link 已是真實 URL（非 Google News 加密網址），直接流進 scrape.extract_event 既有流程
（AI 萃取 + 連結驗證 + 可信網域日期補抓）。

目前已接：
  - PR TIMES 關鍵字搜尋（官方新聞稿，網域 prtimes.jp 屬可信，日期可靠）
之後可再加：品牌官網活動頁、場館活動頁…（一個來源驗證對了再加一個）。
"""
import re
import time
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime

import requests
from verify_links import fetch_html  # 抓頁；被 bot 防護擋住時自動改用 reader 代理硬取

# 每品牌在 PR TIMES 用的關鍵字（日文官方名稱命中率最高）+ 標題須含的關聯字
PRTIMES_KEYWORD = {
    "miffy":    "ミッフィー",
    "pokemon":  "ポケモンセンター",
    "chiikawa": "ちいかわ",
    "sanrio":   "サンリオ",
}
TITLE_MUST_INCLUDE = {
    "miffy":    ["ミッフィー", "miffy"],
    "pokemon":  ["ポケモン", "pokemon"],
    "chiikawa": ["ちいかわ"],
    "sanrio":   ["サンリオ", "ハローキティ", "クロミ", "シナモロール",
                 "ポムポムプリン", "マイメロ"],
}

_REL_DATE = re.compile(r"（(20\d{2})年(\d{1,2})月(\d{1,2})日")


def _release_pubdate(html: str) -> str:
    """從 PR TIMES og:description「（2026年5月20日 10時00分）」取發稿日，回 RFC2822；失敗回 ''。"""
    m = _REL_DATE.search(html)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        dt = datetime(y, mo, d, tzinfo=timezone(timedelta(hours=9)))  # JST
        return format_datetime(dt)
    except ValueError:
        return ""


def _og(html: str, prop: str) -> str:
    m = re.search(rf'<meta property="og:{prop}" content="([^"]*)"', html)
    return m.group(1).strip() if m else ""


def fetch_prtimes(brand: str, limit: int = 8) -> list[dict]:
    """抓 PR TIMES 該品牌關鍵字下的官方新聞稿，回傳 item 清單（題材篩選交給後續 AI）。"""
    kw = PRTIMES_KEYWORD.get(brand)
    if not kw:
        return []
    list_html = fetch_html("https://prtimes.jp/topics/keywords/" + requests.utils.quote(kw))
    if not list_html:
        print(f"    ⚠️  PR TIMES 列表抓取失敗（直連＋代理都不行）")
        return []

    ids = list(dict.fromkeys(re.findall(r"/main/html/rd/p/(\d+\.\d+)\.html", list_html)))
    must = TITLE_MUST_INCLUDE.get(brand, [])
    items: list[dict] = []
    for rid in ids:
        if len(items) >= limit:
            break
        url = f"https://prtimes.jp/main/html/rd/p/{rid}.html"
        h = fetch_html(url)
        if not h:
            continue
        title = _og(h, "title")
        if not title:
            continue
        # 事前關聯過濾：標題沒提到本品牌就跳過，省 AI 額度
        if must and not any(k.lower() in title.lower() for k in must):
            continue
        items.append({
            "title": title,
            "link": url,                       # 已是真實 URL（prtimes.jp 可信）
            "pubDate": _release_pubdate(h),
            "description": _og(h, "description")[:300],
            "source": "PR TIMES",
        })
        time.sleep(0.5)
    return items


# 官方來源總入口：目前只有 PR TIMES，之後新增來源在這裡串接
def fetch_official(brand: str) -> list[dict]:
    return fetch_prtimes(brand)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for b in ["miffy", "pokemon", "chiikawa", "sanrio"]:
        print(f"\n=== {b} ===")
        for it in fetch_official(b):
            print(f"  [{it['pubDate'][:16] or 'no-date'}] {it['title'][:60]}")
