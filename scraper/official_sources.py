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
import json
import html as html_lib
from html.parser import HTMLParser
from datetime import datetime, timezone, timedelta
from email.utils import format_datetime
from urllib.parse import urljoin

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


class _VisibleTextParser(HTMLParser):
    """Extract visible text without pulling in Next.js scripts or CSS."""
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _visible_text(html_text: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html_text or "")
    return re.sub(r"\s+", " ", html_lib.unescape(" ".join(parser.parts))).strip()


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
_CHIIKAWA_INFO_TOP = "https://chiikawa-info.jp/"
_CHIIKAWA_MOGUMOGU_CASTELLA = "https://www.chiikawamogumogu.jp/stores/castella/"
# 解析：### [ちいかわPOP UP STORE <會場>](https://chiikawa-info.jp/p26/.../index.html)  2026年6月5日(金)～6月22日(月)  <會場詳址>
_PUS_ROW = re.compile(
    r"\[ちいかわPOP ?UP ?STORE\s*([^\]]+?)\]"
    r"\((https://chiikawa-info\.jp/p26/[^)]+)\)\s*"
    r"(20\d\d)年(\d{1,2})月(\d{1,2})日[^〜～]*?[〜～]\s*"
    r"(?:(20\d\d)年)?(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*"
    r"([^\n\[]{0,60})"     # 會場詳址（日期後那段，含縣市/樓層）
)

_CHIIKAWA_OTARU_CASTELLA = re.compile(
    r"ちいかわベビーカステラ[\s\S]{0,600}?"
    r"(20\d\d)年(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?[〜～]\s*"
    r"ちいかわもぐもぐ本舗\s*小樽店にオープン"
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


def _chiikawa_otaru_castella_event(info_text: str, shop_text: str, correct_city=None) -> dict | None:
    combined = "\n".join(t for t in (info_text, shop_text) if t)
    m = _CHIIKAWA_OTARU_CASTELLA.search(combined)
    if not m:
        return None
    if "小樽" not in combined or "ちいかわベビーカステラ" not in combined:
        return None
    if not any(k in combined for k in ("オリジナルグッズ", "グッズのご紹介", "GOODS")):
        return None

    sy, sm, sd = (int(x) for x in m.groups())
    start = f"{sy:04d}-{sm:02d}-{sd:02d}"
    address = "北海道小樽市堺町6-1" if ("堺町6-1" in combined) else "北海道・小樽"
    city = correct_city(address, "小樽", "北海道") if correct_city else ""
    need_reservation = ("事前予約" in combined) or ("入店予約" in combined)

    return {
        "brand": "chiikawa",
        "title": "吉伊卡哇 小樽店 ちいかわベビーカステラ",
        "type": "store", "country": "JP", "city": city or "",
        "locationName": f"ちいかわベビーカステラ（{address}）",
        "startDate": start, "endDate": "",
        "summaryZh": "ちいかわもぐもぐ本舗的小樽店「ちいかわベビーカステラ」將開幕，販售店內現烤 Baby Castella、限定餐飲與原創周邊商品。",
        "needReservation": need_reservation, "hasLimitedGoods": True,
        "tags": ["吉伊卡哇", "小樽", "常設店", "限定餐飲", "限定周邊"],
        "id": _stable_id("ch", _CHIIKAWA_MOGUMOGU_CASTELLA + start),
        "sourceType": "official_site", "createdAt": _today_iso(),
        "sourceTitle": "7月に北海道・小樽にオープン！テイクアウトショップ「ちいかわベビーカステラ」フードメニュー、グッズのご紹介 - ちいかわもぐもぐ本舗",
        "sourceUrl": _CHIIKAWA_MOGUMOGU_CASTELLA,
    }


def fetch_chiikawa_mogumogu(correct_city=None) -> list[dict]:
    """解析ちいかわインフォ首頁與もぐもぐ本舗店鋪頁，抓常設店／限定餐飲／原創周邊情報。"""
    info_md = _proxy_markdown(_CHIIKAWA_INFO_TOP)
    shop_md = _proxy_markdown(_CHIIKAWA_MOGUMOGU_CASTELLA)
    if not info_md and not shop_md:
        print("    ⚠️  吉伊卡哇もぐもぐ本舗頁抓取失敗（直連＋代理都不行）")
        return []

    event = _chiikawa_otaru_castella_event(info_md, shop_md, correct_city=correct_city)
    return [event] if event else []


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


_POKE_TW_GOODS = "https://tw.portal-pokemon.com/goods/?p={page}"
_POKE_TW_BASE = "https://tw.portal-pokemon.com"
_POKE_TW_GOODS_LINK = re.compile(r'href="(/goods/post-[^"]+/)"[^>]*>(.*?)</a>', re.S)
_POKE_TW_NEXT_ITEM = re.compile(
    r'\\"item\\":\{.*?'
    r'\\"postId\\":(\d+).*?'
    r'\\"slug\\":\\"(post-\d+)\\".*?'
    r'\\"title\\":\\"(.*?)\\".*?'
    r'\\"startDateTime\\":\\"(20\d\d-\d\d-\d\d).*?'
    r'\\"category\\":\{.*?\\"categoryName\\":\\"([^"]+)\\"',
    re.S,
)
_POKE_TW_ALLOWED_CATEGORIES = (
    "玩具、玩偶、模型類",
    "文具類",
    "食品類",
    "寢具、家具、生活雜貨類",
    "衣服、飾品類",
)
_POKE_TW_GOODS_NOISE = (
    "LINE貼圖",
    "LINE主題",
    "Pokémon UNITE",
    "寶可夢集換式卡牌",
    "Trading Card Game",
    "卡牌",
)
_POKE_TW_STORE_TEXT = "Pokémon Center TAIPEI"
_POKE_TW_DATE = re.compile(r"(\d{2})\.(\d{2})\.(20\d{2})$")
_POKE_TW_ENTRY = re.compile(
    rf"(.+?)\s+({'|'.join(map(re.escape, _POKE_TW_ALLOWED_CATEGORIES + ('其他',)))})\s+"
    r"(\d{2})\.(\d{2})\.(20\d{2})$"
)
_POKE_TW_STORE_DATE = re.compile(
    r"(?:即將)?於\s*(\d{1,2})月(\d{1,2})日[^。！？]{0,90}?"
    r"(?:在)?\s*Pokémon Center TAIPEI[^。！？]{0,30}?(?:登場|販售)"
)


def _dedupe_repeated_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title or "").strip()
    if len(title) % 2 == 0:
        half = len(title) // 2
        if title[:half].strip() == title[half:].strip():
            return title[:half].strip()
    return title


def _next_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace("\\t", " ").replace("\\n", " ").replace('\\"', '"')


def _tw_goods_entries_from_next_html(h: str) -> list[dict]:
    out, seen = [], set()
    for post_id, slug, raw_title, published, category in _POKE_TW_NEXT_ITEM.findall(h):
        if not slug.startswith("post-") or slug in seen:
            continue
        seen.add(slug)
        out.append({
            "url": urljoin(_POKE_TW_BASE, f"/goods/{slug}/"),
            "title": _dedupe_repeated_title(_next_string(raw_title)),
            "category": _next_string(category),
            "published": published,
        })
    return out


def _tw_goods_entries(max_pages: int = 2) -> list[dict]:
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        h = fetch_html(_POKE_TW_GOODS.format(page=page))
        if not h:
            break
        for entry in _tw_goods_entries_from_next_html(h):
            if entry["url"] in seen:
                continue
            seen.add(entry["url"])
            out.append(entry)
        for m in _POKE_TW_GOODS_LINK.finditer(h):
            url = urljoin(_POKE_TW_BASE, m.group(1))
            if url in seen:
                continue
            seen.add(url)
            text = _plain_text(m.group(2))
            mm = _POKE_TW_ENTRY.search(text)
            if not mm:
                continue
            raw_title, category, mo, day, year = mm.groups()
            out.append({
                "url": url,
                "title": _dedupe_repeated_title(raw_title),
                "category": category,
                "published": f"{year}-{mo}-{day}",
            })
    return out


def _tw_store_sale_date(text: str, published: str) -> str:
    pub_year = int(published[:4])
    pub_month = int(published[5:7])
    for m in _POKE_TW_STORE_DATE.finditer(text):
        month, day = int(m.group(1)), int(m.group(2))
        year = pub_year + 1 if pub_month >= 11 and month < pub_month else pub_year
        return f"{year:04d}-{month:02d}-{day:02d}"
    return ""


def fetch_pokemon_tw_goods(correct_city=None, max_pages: int = 5, fresh_days: int = 75) -> list[dict]:
    """Parse Taiwan Pokémon official goods pages for physical Pokémon Center TAIPEI launches.

    The portal includes LINE stickers/themes, games, TCG and licensed online-only goods,
    so this source only accepts pages whose detail text explicitly says the product
    appears/sells at Pokémon Center TAIPEI.
    """
    today = _today_iso()
    out: list[dict] = []
    for entry in _tw_goods_entries(max_pages=max_pages):
        title = entry["title"]
        category = entry["category"]
        if category not in _POKE_TW_ALLOWED_CATEGORIES:
            continue
        if any(noise.lower() in title.lower() for noise in _POKE_TW_GOODS_NOISE):
            continue
        h = fetch_html(entry["url"])
        if not h:
            continue
        text = _visible_text(h)
        if any(noise.lower() in text.lower() for noise in _POKE_TW_GOODS_NOISE):
            continue
        if _POKE_TW_STORE_TEXT not in text:
            continue
        start = _tw_store_sale_date(text, entry["published"])
        if not start:
            continue
        age = (date.fromisoformat(today) - date.fromisoformat(start)).days
        if age > fresh_days:
            continue
        city = correct_city("台北", _POKE_TW_STORE_TEXT) if correct_city else "Taipei"
        out.append({
            "brand": "pokemon",
            "title": f"台灣寶可夢中心 {title}",
            "type": "new_product",
            "country": "TW",
            "city": city or "Taipei",
            "locationName": _POKE_TW_STORE_TEXT,
            "startDate": start,
            "endDate": "",
            "summaryZh": f"台灣寶可夢官方公告「{title}」於{start}起在Pokémon Center TAIPEI登場／販售。",
            "needReservation": False,
            "hasLimitedGoods": True,
            "tags": ["寶可夢", "新品", "台灣", "官方"],
            "id": _stable_id("po", entry["url"]),
            "sourceType": "official_site",
            "createdAt": today,
            "sourceTitle": f"{title} - 台灣寶可夢官方網站",
            "sourceUrl": entry["url"],
        })
        time.sleep(0.4)
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
_KIDDY_MIFFY_SEARCH = "https://www.kiddyland.co.jp/?s=miffy"
_KIDDY_MIFFY_LINK = re.compile(
    r"(?:\]\(|href=[\"'])(https://www\.kiddyland\.co\.jp/event/miffy[^)\"']+/)"
)
_KIDDY_SKIP = ["お詫び", "延期", "入店方法", "緊急案内"]
_KIDDY_SITE_SUFFIX = " | キデイランドへようこそ！"
_KIDDY_RANGE = re.compile(
    r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日[^。\n]{0,30}?"
    r"(?:から|[〜～~-])[^。\n]{0,30}?"
    r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日"
)


def _page_text(url: str) -> str:
    """先直抓 HTML；失敗再走 reader markdown。"""
    h = fetch_html(url)
    return h or _proxy_markdown(url)


def _plain_text(text: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _first_heading(md: str) -> str:
    m = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", md, re.I)
    if m:
        return _plain_text(m.group(1))
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return re.sub(r"\s+", " ", line[2:]).strip()
    return ""


def _kiddy_display_title(title: str) -> str:
    title = title.replace(_KIDDY_SITE_SUFFIX, "").strip()
    title = re.sub(r"^20\d{2}年\d{1,2}月\d{1,2}日\([^)]*\)", "", title).strip()
    title = re.sub(r"^(?:より開催|発売予定|～スタート|〜スタート|!|！)+", "", title).strip()
    title = re.sub(r"^miffy style[^!！]*受注開始予定[!！]", "", title).strip()
    return title or "miffy style 店頭活動"


def _kiddy_period(title: str, detail: str, extract_dates) -> tuple[str, str]:
    ref_year_m = re.search(r"(20\d{2})年", title)
    ref_year = int(ref_year_m.group(1)) if ref_year_m else date.today().year
    m = _KIDDY_RANGE.search(detail)
    if m:
        sy = int(m.group(1) or ref_year)
        sm, sd = int(m.group(2)), int(m.group(3))
        ey = int(m.group(4) or sy)
        em, ed = int(m.group(5)), int(m.group(6))
        if em < sm and not m.group(4):
            ey += 1
        return f"{sy:04d}-{sm:02d}-{sd:02d}", f"{ey:04d}-{em:02d}-{ed:02d}"
    return extract_dates(title + "\n" + detail, ref_year=ref_year, is_html=False, scan_chars=7000)


def _kiddy_location(title: str) -> tuple[str, str]:
    if "Birthday Fair" in title or "各店" in title:
        return "miffy style 各店＋キデイランド対象店", ""
    if "原宿店" in title:
        return "miffy style 原宿店", "Tokyo"
    if "大阪梅田店" in title:
        return "miffy style 大阪梅田店", "Osaka"
    if "心斎橋" in title or "心齋橋" in title:
        return "miffy style 心齋橋PARCO店", "Osaka"
    return "miffy style 各店＋一部キデイランド店舗", ""


def _kiddy_type(title: str) -> str:
    low = title.lower()
    if "受注" in title or "予約" in title:
        return "reservation"
    if "fair" in low or "フェア" in title or "ノベルティ" in title:
        return "campaign"
    if "pop up" in low or "popup" in low or "ポップアップ" in title:
        return "popup"
    return "new_product"


def fetch_kiddyland_miffy_events(extract_dates, correct_city, max_articles=3, fresh_days=45) -> list[dict]:
    """解析 Kiddy Land / miffy style 站內搜尋的近期 Miffy 店頭活動與新品。零 Gemini。"""
    md = _page_text(_KIDDY_MIFFY_SEARCH)
    if not md:
        print("    ⚠️  Kiddy Land miffy 搜尋抓取失敗（直連＋代理都不行）")
        return []
    today = _today_iso()
    out, seen = [], set()
    urls = list(dict.fromkeys(_KIDDY_MIFFY_LINK.findall(md)))
    for url in urls[:max_articles]:
        if url in seen:
            continue
        detail = _page_text(url)
        if not detail:
            continue
        detail_text = _plain_text(detail)
        title = _first_heading(detail)
        if not title or not any(k.lower() in title.lower() for k in ["miffy", "ミッフィー"]):
            continue
        if any(k in title for k in _KIDDY_SKIP):
            continue
        pub_m = re.search(r"On\s+(\d{1,2})月\s*(\d{1,2}),\s*(20\d{2})", detail_text)
        if pub_m:
            try:
                pub = date(int(pub_m.group(3)), int(pub_m.group(1)), int(pub_m.group(2)))
                if (date.today() - pub).days > fresh_days:
                    continue
            except ValueError:
                pass
        s, e = _kiddy_period(title, detail_text, extract_dates)
        if not s:
            continue
        # 沒有結束日的 Kiddy Land 新品/店頭活動讓過期規則處理；有結束日且已過期則略過。
        if e and e < today:
            continue
        loc, fallback_city = _kiddy_location(title)
        city = correct_city(title, loc) or fallback_city
        typ = _kiddy_type(title)
        summary = "Miffy style / Kiddy Land 店頭活動，販售或受注 Miffy 相關新品與限定／先行商品。"
        if "Birthday Fair" in title:
            summary = "miffy’s Birthday 2026 生日活動於 miffy style 與 Kiddy Land 指定店舖登場，販售生日限定商品並提供店頭特典。"
        elif typ == "reservation":
            summary = "Miffy 聯名商品於 miffy style 店頭期間限定受注，需於指定期間到店辦理。"
        display_title = _kiddy_display_title(title)
        out.append({
            "brand": "miffy",
            "title": "Miffy " + display_title,
            "type": typ,
            "country": "JP", "city": city or "",
            "locationName": loc,
            "startDate": s, "endDate": e or "",
            "summaryZh": summary,
            "needReservation": typ == "reservation" or "抽選" in title or "予約" in title,
            "hasLimitedGoods": True,
            "tags": ["米飛兔", "miffy style", "日本"],
            "id": _stable_id("mi", url),
            "sourceType": "official_site", "createdAt": today,
            "sourceTitle": f"{title} - キデイランド",
            "sourceUrl": url,
        })
        seen.add(url)
    return out


def fetch_miffy_events(extract_dates, correct_city, max_articles=16, fresh_days=80) -> list[dict]:
    """解析 Miffy 官方 dickbruna.jp/event/ 列表，逐篇抓開催期間，回傳現行成品情報。零 Gemini。
    需傳入 scrape.extract_dates 與 scrape.correct_city。"""
    out: list[dict] = []
    md = _proxy_markdown(_MIFFY_LIST)
    if not md:
        print("    ⚠️  Miffy dickbruna 列表抓取失敗（直連＋代理都不行）")
        return fetch_kiddyland_miffy_events(extract_dates, correct_city)
    from datetime import date as _d
    today = _today_iso()
    seen = set()
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
    out.extend(fetch_kiddyland_miffy_events(extract_dates, correct_city))
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
