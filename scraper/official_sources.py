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


# ─────────────────────────────────────────────────────────────────────────────
# 結構化官方排程頁 → 直接產生「成品情報」（零 AI／零 Gemini 額度）
# 這類官方頁已把「會場＋確切日期」列好，用 regex 解析 + 中文模板即可生成 events，
# 不需經過 Gemini 萃取。回傳的是「最終 event dict」（非待萃取 item），由 scrape 直接併入。
# ─────────────────────────────────────────────────────────────────────────────
import hashlib
from datetime import date

READER = "https://r.jina.ai/"


def _today_iso():
    return date.today().isoformat()


def _stable_id(prefix: str, key: str) -> str:
    return f"{prefix}-{hashlib.md5(key.encode('utf-8')).hexdigest()[:6]}"


def _proxy_markdown(url: str) -> str:
    """用 reader 代理取頁面 markdown（官方站常擋 bot）。失敗回 ''。"""
    try:
        r = requests.get(READER + url, headers={"User-Agent": HEADERS_UA}, timeout=70)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


HEADERS_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_CHIIKAWA_PUS = "https://chiikawa-info.jp/pus.html"
# 解析：### [ちいかわPOP UP STORE <會場>](https://chiikawa-info.jp/p26/.../index.html)  2026年6月5日(金)～6月22日(月)  <會場詳址>
_PUS_ROW = re.compile(
    r"\[ちいかわPOP ?UP ?STORE\s*([^\]]+?)\]"
    r"\((https://chiikawa-info\.jp/p26/[^)]+)\)\s*"
    r"(20\d\d)年(\d{1,2})月(\d{1,2})日[^〜～]*?[〜～]\s*"
    r"(?:(20\d\d)年)?(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*"
    r"([^\n\[]{0,60})"     # 會場詳址（日期後那段，含縣市/樓層）
)


def fetch_chiikawa_popups(correct_city=None) -> list[dict]:
    """解析吉伊卡哇官方 pus.html，回傳「現行（未過期）」POP UP STORE 的成品情報清單。
    零 Gemini。correct_city(可選)＝scrape.correct_city，用來判城市。"""
    md = _proxy_markdown(_CHIIKAWA_PUS)
    if not md:
        print("    ⚠️  吉伊卡哇 pus.html 抓取失敗（直連＋代理都不行）")
        return []
    today = _today_iso()
    out, seen = [], set()
    for m in _PUS_ROW.finditer(md):
        venue, url, sy, sm, sd, ey, em, ed, addr = m.groups()
        venue = re.sub(r"\s+", " ", venue).strip()
        addr = re.sub(r"\s+", " ", addr or "").strip()
        if "【終了】" in venue or url in seen:
            continue
        sy, sm, sd, em, ed = int(sy), int(sm), int(sd), int(em), int(ed)
        ey = int(ey) if ey else (sy + 1 if em < sm else sy)  # 結束月<開始月→跨年
        start = f"{sy:04d}-{sm:02d}-{sd:02d}"
        end = f"{ey:04d}-{em:02d}-{ed:02d}"
        if end < today:          # 已過期不收
            continue
        seen.add(url)
        # locationName 用較完整的會場詳址（含縣市/樓層）；城市從詳址＋會場名一起判
        loc = addr if len(addr) >= len(venue) else venue
        city = correct_city(addr, venue) if correct_city else None
        out.append({
            "brand": "chiikawa",
            "title": f"吉伊卡哇 POP UP STORE {venue}",
            "type": "popup", "country": "JP", "city": city or "",
            "locationName": loc,
            "startDate": start, "endDate": end,
            "summaryZh": f"ちいかわ POP UP STORE 於{venue}期間限定登場，販售豐富的吉伊卡哇限定周邊商品。",
            "needReservation": False, "hasLimitedGoods": True,
            "tags": ["吉伊卡哇", "快閃店", "日本", "限定周邊"],
            "id": _stable_id("ch", url),
            "sourceType": "official_site", "createdAt": today,
            "sourceTitle": f"ちいかわPOP UP STORE {venue}({start}～{end}) - ちいかわ公式",
            "sourceUrl": url,
        })
    return out


_POKE_SCHED = "https://oneheart65.net/pokemoncenterbranch_schedule_2/"
# 解析：2026年6月5日（金）〜7月22日（水）**兵庫県・イオンモール神戸北**専門店街3階 イオンホール
_POKE_ROW = re.compile(
    r"(20\d\d)年(\d{1,2})月(\d{1,2})日（[^）]*）[〜～]\s*"
    r"(?:(20\d\d)年)?(\d{1,2})月(\d{1,2})日（[^）]*）\s*"
    r"\*\*([^・*]+?)・([^*]+?)\*\*\s*([^\n*\[]{0,40})"
)


def fetch_pokemon_popups(correct_city=None) -> list[dict]:
    """解析寶可夢出張所排程，回傳「現行（未過期）」出張所的成品情報清單。零 Gemini。
    （oneheart65 為維護良好的排程彙整站，羽生等日期經官方 AEON 頁交叉驗證一致。）"""
    md = _proxy_markdown(_POKE_SCHED)
    if not md:
        print("    ⚠️  寶可夢出張所排程抓取失敗（直連＋代理都不行）")
        return []
    today = _today_iso()
    out, seen = [], set()
    for m in _POKE_ROW.finditer(md):
        sy, sm, sd, ey, em, ed, pref, venue, addr = m.groups()
        pref = pref.strip(); venue = re.sub(r"\s+", " ", venue).strip()
        addr = re.sub(r"\s+", " ", addr or "").strip()
        sy, sm, sd, em, ed = int(sy), int(sm), int(sd), int(em), int(ed)
        ey = int(ey) if ey else (sy + 1 if em < sm else sy)
        start = f"{sy:04d}-{sm:02d}-{sd:02d}"
        end = f"{ey:04d}-{em:02d}-{ed:02d}"
        key = venue + start
        if end < today or key in seen:
            continue
        seen.add(key)
        loc = f"{venue} {addr}".strip()
        city = correct_city(pref, venue, addr) if correct_city else None
        out.append({
            "brand": "pokemon",
            "title": f"Pokemon Center 出張所 in {venue}",
            "type": "popup", "country": "JP", "city": city or "",
            "locationName": loc,
            "startDate": start, "endDate": end,
            "summaryZh": f"寶可夢中心出張所於{pref}{venue}期間限定登場，販售多樣寶可夢周邊商品。",
            "needReservation": False, "hasLimitedGoods": True,
            "tags": ["寶可夢", "出張所", "快閃店", "日本"],
            "id": _stable_id("po", key),
            "sourceType": "official_social", "createdAt": today,
            "sourceTitle": f"ポケモンセンター出張所in{venue}（{start}～{end}）",
            "sourceUrl": _POKE_SCHED,
        })
    return out


_MIFFY_LIST = "https://dickbruna.jp/event/"
# 列表項：### <活動標題> 2026.05.27](https://dickbruna.jp/news/202605/46167/)
_MIFFY_ROW = re.compile(
    r"###\s*([^\n\]]+?)\s+(20\d\d)\.(\d{1,2})\.(\d{1,2})\]"
    r"\((https://dickbruna\.jp/news/\d+/\d+/)\)")
# 只收四類「去現場買得到」的：快閃/店舖/催事/咖啡廳/周邊
_MIFFY_INCLUDE = ["dick bruna stand", "stand by miia", "zakka", "flower miffy",
                  "pop-up", "pop up", "popup", "マルシェ", "table", "カフェ",
                  "ショップ", "グッズ", "ストア", "miffy⁺", "おやつ", "kitchen"]


def fetch_miffy_events(extract_dates, correct_city, max_articles=16, fresh_days=80) -> list[dict]:
    """解析 Miffy 官方 dickbruna.jp/event/ 列表，逐篇抓開催期間，回傳現行成品情報。零 Gemini。
    需傳入 scrape.extract_dates 與 scrape.correct_city。"""
    md = _proxy_markdown(_MIFFY_LIST)
    if not md:
        print("    ⚠️  Miffy dickbruna 列表抓取失敗（直連＋代理都不行）")
        return []
    from datetime import date as _d
    today = _today_iso()
    out, seen = [], set()
    rows = _MIFFY_ROW.findall(md)
    for title, py, pm, pd, url in rows[:max_articles]:
        title = re.sub(r"\s+", " ", title).strip()
        if url in seen:
            continue
        # 類別過濾：只收購物型活動
        if not any(k in title.lower() for k in _MIFFY_INCLUDE):
            continue
        # 發布太舊的略過（避免翻到去年活動）
        try:
            if (_d.today() - _d(int(py), int(pm), int(pd))).days > fresh_days:
                continue
        except ValueError:
            pass
        detail = _proxy_markdown(url)
        if not detail:
            continue
        s, e = extract_dates(detail, ref_year=int(py), is_html=False, scan_chars=9000)
        if not s or (e and e < today):     # 抓不到期間、或已過期 → 跳過
            continue
        seen.add(url)
        name_m = re.search(r"「([^」]+)」", title)
        name = name_m.group(1) if name_m else title
        venue = re.split(r"(?:にて|に|で)「", title)[0].strip("・ ")
        loc = venue or name
        city = correct_city(venue, title)
        out.append({
            "brand": "miffy",
            "title": f"Miffy {name}　{venue}".strip(),
            "type": "cafe" if any(k in title.lower() for k in ["カフェ", "kitchen", "おやつ", "table"]) else "popup",
            "country": "JP", "city": city or "",
            "locationName": loc,
            "startDate": s, "endDate": e or "",
            "summaryZh": f"Miffy（米飛兔）官方活動「{name}」於{venue}期間限定登場，販售限定周邊／餐點。",
            "needReservation": False, "hasLimitedGoods": True,
            "tags": ["米飛兔", "期間限定", "日本"],
            "id": _stable_id("mi", url),
            "sourceType": "official_site", "createdAt": today,
            "sourceTitle": f"{title} - dickbruna.jp",
            "sourceUrl": url,
        })
    return out


# 官方來源總入口：PR TIMES（待萃取 item）+ 之後新增來源在這裡串接
def fetch_official(brand: str) -> list[dict]:
    return fetch_prtimes(brand)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for b in ["miffy", "pokemon", "chiikawa", "sanrio"]:
        print(f"\n=== {b} ===")
        for it in fetch_official(b):
            print(f"  [{it['pubDate'][:16] or 'no-date'}] {it['title'][:60]}")
