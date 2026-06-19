"""
角色情報雷達 — 自動抓取腳本

需要 AI API key（擇一）：
  - Anthropic Claude：ANTHROPIC_API_KEY=sk-ant-...  （console.anthropic.com，新帳號 $5 免費額度）
  - Google Gemini：  GEMINI_API_KEY=AIza...         （aistudio.google.com，完全免費）

在 scraper/.env 填入其中一個，例如：
  GEMINI_API_KEY=AIzaSy...

用法：
  python scrape.py              # 抓取全部品牌
  python scrape.py --brand chiikawa
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from verify_links import check_url, page_mentions  # 存檔前驗證來源連結：連得過去 + 內容與品牌相關
from official_sources import (fetch_official, fetch_chiikawa_popups,
                              fetch_chiikawa_mogumogu,
                              fetch_chiikawa_movie_goods,
                              fetch_chiikawa_movie_popups,
                              fetch_pokemon_popups, fetch_pokemon_cafe_events,
                              fetch_pokemon_tw_goods,
                              fetch_miffy_events)  # 官方來源：PR TIMES + 結構化排程頁

# Windows 終端機 UTF-8 輸出 + 關閉緩衝（即時看到進度）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

DATA_DIR = Path(__file__).parent.parent / "data"
EVENTS_JSON = DATA_DIR / "events.json"
UPDATE_DIFF_JSON = DATA_DIR / "today_updates.json"
LAST_UPDATED_JSON = DATA_DIR / "last_updated.json"
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
MAX_PER_BRAND = 13  # 每品牌單次最多用 AI 判斷幾筆（控制速度與額度）

# ── RSS 搜尋條件 ───────────────────────────────────────────────────────────────

RSS_QUERIES = {
    "pokemon": [
        ("ポケモンセンター 新商品 OR ポップアップ OR 期間限定 OR 発売", False),
        ("寶可夢 台灣 OR 台北 快閃 OR 新品 OR 活動", True),
    ],
    "miffy": [
        ("ミッフィー グッズ OR ポップアップ OR カフェ OR 期間限定", False),
        ("miffy style OR ミッフィースタイル OR キデイランド ミッフィー 発売 OR フェア", False),
        ("Miffy 米飛 台灣 OR 台北 OR 台中 快閃 OR 展覧", True),
    ],
    "chiikawa": [
        ("ちいかわ グッズ OR ポップアップ OR カフェ OR イベント OR 発売", False),
        ("吉伊卡哇 台灣 OR 台北 快閃 OR 新品", True),
    ],
    "sanrio": [
        ("サンリオ ポップアップ OR 新商品 OR カフェ OR イベント OR 期間限定", False),
        ("三麗鷗 台灣 OR 台北 OR 高雄 快閃 OR 新品 OR 活動", True),
    ],
}

BRAND_KEYWORDS = {
    "pokemon":  ["ポケモン", "pokemon", "寶可夢", "pokémon"],
    "miffy":    ["ミッフィー", "miffy", "米飛"],
    "chiikawa": ["ちいかわ", "chiikawa", "吉伊卡哇"],
    "sanrio":   ["サンリオ", "sanrio", "三麗鷗", "ハローキティ", "マイメロ",
                 "シナモロール", "ポムポムプリン", "クロミ", "大耳狗", "玉桂狗"],
}

BRAND_LABELS = {
    "pokemon":  "Pokémon（寶可夢）",
    "miffy":    "Miffy（米飛兔）",
    "chiikawa": "Chiikawa（吉伊卡哇）",
    "sanrio":   "Sanrio（三麗鷗）",
}

# 地點關鍵字 → 正確城市（確定性對照，用來修正 AI 猜錯的城市）
# 城市不限於原本 8 個，任何有情報的地點都應正確標示
AREA_TO_CITY = {
    "Tokyo":    ["東京", "渋谷", "澀谷", "池袋", "銀座", "新宿", "原宿", "表参道", "表參道",
                 "スカイツリー", "晴空塔", "ソラマチ", "押上", "自由が丘", "自由之丘",
                 "お台場", "丸の内", "浅草", "上野", "中野", "吉祥寺", "多摩", "立川",
                 "ピューロランド", "Puroland", "彩虹樂園", "サンリオピューロランド"],
    "Osaka":    ["大阪", "梅田", "心斎橋", "心齋橋", "なんば", "難波", "中之島", "天王寺",
                 "ルクア", "LUCUA", "グランフロント", "万博", "あべの"],
    "Kyoto":    ["京都", "KYOTO", "河原町", "嵐山", "四条"],
    "Fukuoka":  ["福岡", "博多", "天神", "キャナルシティ", "キャナル"],
    "Nagoya":   ["名古屋", "栄", "ラシック", "名駅", "大須"],
    "Nagasaki": ["長崎", "ハウステンボス", "豪斯登堡", "Huis Ten Bosch", "佐世保"],
    "Saitama":  ["埼玉", "羽生", "Hanyu", "大宮", "Omiya", "越谷", "Koshigaya",
                 "レイクタウン", "Laketown", "川越", "川口"],
    "Hokkaido": ["北海道", "札幌", "小樽", "函館", "新千歳", "千歳"],
    "Okinawa":  ["沖縄", "沖繩", "那覇", "ライカム"],
    "Kanagawa": ["神奈川", "横浜", "横濱", "橫濱", "川崎", "みなとみらい", "ワールドポーターズ"],
    "Hyogo":    ["兵庫", "神戸", "神戶", "Kobe", "KOBE", "西宮", "三宮", "伊丹", "姫路", "ピオレ"],
    "Hiroshima":["広島", "廣島", "Hiroshima"],
    "Mie":      ["三重", "四日市", "津南"],
    "Miyagi":   ["仙台", "宮城", "名取", "新利府", "利府"],
    "Chiba":    ["千葉", "舞浜", "幕張"],
    "Niigata":  ["新潟", "亀田"],
    "Okayama":  ["岡山", "倉敷"],
    "Tottori":  ["鳥取", "日吉津"],
    "Nara":     ["奈良", "橿原"],
    "Fukushima":["福島", "いわき", "ハワイアンズ"],
    "Nagano":   ["長野", "須坂"],
    "Gifu":     ["岐阜", "各務原"],
    "Miyazaki": ["宮崎"],
    "Yamanashi":["山梨", "甲府", "昭和"],
    "Aomori":   ["青森", "Aomori", "弘前"],
    "Aichi":    ["愛知", "豊田", "名古屋", "常滑", "大高"],
    "Shizuoka": ["静岡", "靜岡", "富士宮", "浜松", "遠鉄", "セノバ"],
    "Yamaguchi":["山口", "小野田", "おのだ"],
    "Wakayama": ["和歌山", "Wakayama"],
    "Kochi":    ["高知", "Kochi"],
    "Ehime":    ["愛媛", "今治", "松山"],
    "Ishikawa": ["石川", "金沢", "金澤", "香林坊"],
    "Ibaraki":  ["茨城", "水戸", "京成百貨店"],
    "Taipei":   ["台北", "臺北", "信義", "西門", "微風", "南山", "華山", "中山",
                 "松山", "內湖", "板橋", "101"],
    "Taichung": ["台中", "臺中", "草悟", "勤美"],
    "Kaohsiung":["高雄", "漢神", "夢時代", "草衙"],
    "Tainan":   ["台南", "臺南"],
    "Taoyuan":  ["桃園", "中壢"],
}

def correct_city(*texts) -> str | None:
    """從地點/標題文字判斷正確城市；找不到回 None（不亂猜）。"""
    blob = " ".join(t for t in texts if t)
    for city, kws in AREA_TO_CITY.items():
        for kw in kws:
            if kw in blob:
                return city
    return None

# 預設抓取的品牌與順序。Sanrio 先暫停：新聞/Gemini 來源品質不穩，
# 會吃掉最多 agent 驗證時間；保留常數讓日後可用 --brand sanrio 手動復查。
DEFAULT_BRANDS = ["miffy", "pokemon", "chiikawa"]

# 標題含這些字 → 在打 AI 之前就先丟掉（明顯不是「專程去逛」的目標，省 API 額度）
NOISE_KEYWORDS = [
    # 超商 / 量販 / 百元店
    "セブン", "ローソン", "ファミマ", "ファミリーマート", "ドンキ", "ドン・キホーテ",
    "驚安", "唐吉訶德", "唐企鵝", "DAISO", "ダイソー", "ダイソ", "セリア", "キャンドゥ",
    "100円", "100均", "百円", "百元", "全家", "7-11", "統一超",
    # 藥妝 / 藥局（聯名小商品上架，順手買非專程去逛目標）
    "薬局", "ドラッグストア", "ドラッグ", "スギ薬局", "マツキヨ", "マツモトキヨシ",
    "ウエルシア", "ツルハ", "サンドラッグ", "ココカラ", "クスリのアオキ",
    "屈臣氏", "康是美",
    # 食品 / 飲料 / 零食
    "グミ", "ヨーグルト", "ボトル", "ドリンク", "醤油", "しょうゆ", "キャンディ",
    "チョコ", "お菓子", "リポビタン", "ポカリ", "ビール", "カステラ", "焼き", "本舗",
    "ベーカリー", "むちゃうま", "ソフビ",
    # 媒體 / 動畫 / 手遊
    "映画", "予告", "声優", "主題歌", "アプリ", "ぽけっと", "ゲーム",
    "劇場版", "預告", "聲優", "手遊", "動畫", "電影",
    "Pokémon GO", "Pokemon GO", "ポケモンGO", "寶可夢GO",
    # 隨機販售 / 開箱 / 夾娃娃機景品（非「去逛買」目標）
    "ガチャ", "カプセル", "扭蛋", "轉蛋", "盲盒", "開箱", "レビュー", "ガチレビュー",
    "付録", "レポ", "夾娃娃機", "ナムコ", "景品", "プライズ", "クレーンゲーム",
    "アミューズメント", "UFOキャッチャー",
    # 廣泛通路抽賞（書店/便利商店/玩具店等上架，不是特定現場活動）
    "一番くじ", "一番賞",
    # 冷卻片 / 文具雜貨小物（順手買，非專程）
    "冷却シート", "スマ冷え", "チャーム", "シール",
    # 海外（非日台）
    "香港", "上海", "ソウル", "韓国",
]

def is_noise(title: str) -> bool:
    return any(kw in title for kw in NOISE_KEYWORDS)

# 體育 / 路跑 / 棒球：體驗活動非購物情報。這類關鍵字可安全地對「標題＋摘要＋內文」
# 全面比對（不像食品/飲料字會誤殺「咖啡廳有飲料攤」之類的正當活動）。
SPORTS_NOISE = [
    "路跑", "マラソン", "ランニング", "ラン大会", "始球式", "開球", "開跑", "起跑",
    "棒球", "野球", "プロ野球", "中職", "球團", "球場", "スタジアム", "ドーム主題",
]

def is_sports_noise(*texts) -> bool:
    blob = " ".join(t for t in texts if t)
    return any(kw in blob for kw in SPORTS_NOISE)

# 多活動「彙整／懶人包」型報導：一篇雜揉多個活動、無單一明確檔期與地點。這類文章的價值在
# 「列出有哪些活動」，而非單一可信來源——真正值得收的活動會由其官方頁或單一新聞各自帶入，
# 故彙整文一律略過（符合「準確>覆蓋」：只有彙整文提到、無其他來源佐證者，本就該捨）。
# 關鍵詞刻意收斂，避免誤殺正當的單一活動攻略文（如「特展攻略…票價整理」不含下列詞）。
ROUNDUP_KEYWORDS = ["懶人包", "總整理", "行事曆", "整理包"]

def is_roundup_title(title: str) -> bool:
    return any(kw in (title or "") for kw in ROUNDUP_KEYWORDS)

GENERIC_MERCH_TITLE_KEYWORDS = (
    "新商品登場", "新商品", "新作グッズ", "新作アイテム", "新グッズ",
    "商品情報", "発売開始", "発売", "開賣", "登場", "グッズ",
)

APPAREL_PRODUCT_KEYWORDS = (
    "服裝", "服装", "服飾", "衣服", "衣料", "衣類", "衣著",
    "アパレル", "ファッション", "ウェア", "wear",
    "tシャツ", "t-shirt", "tee", "シャツ", "パーカー", "スウェット",
    "ワンピース", "ブラウス", "ジャケット", "コート", "カーディガン",
)

PHYSICAL_STORE_SIGNALS = (
    "pokemon center", "pokémon center", "ポケモンセンター", "寶可夢中心", "宝可梦中心",
    "pokemon center taipei", "台灣寶可夢中心", "台北寶可夢中心",
    "miffy style", "キデイランド", "kiddy land",
    "ちいかわらんど", "ちいかわもぐもぐ本舗", "もぐもぐ本舗",
    "pop up", "popup", "ポップアップ", "快閃", "期間限定店",
    "店頭", "店舗", "店舖", "店鋪", "門市", "實體店", "実店舗", "各店",
    "会場", "會場", "会期", "場館", "百貨", "商場", "モール", "mall",
    "カフェ", "cafe", "レストラン", "restaurant", "ベーカリー", "出張所",
)

MEDIA_LOCATION_HINTS = (
    "テレビ", "放送", "新聞", "ニュース", "通信", "メディア", "press", "times",
    "tv", "news", "magazine", "web", "編集部",
)

def is_generic_merch_title(*texts) -> bool:
    blob = " ".join(t for t in texts if t)
    return any(kw.lower() in blob.lower() for kw in GENERIC_MERCH_TITLE_KEYWORDS)

def is_apparel_new_product(ev: dict, source_title: str = "", page_text: str = "") -> bool:
    """Reject clothing/apparel product-only launches while keeping real events."""
    if ev.get("type") != "new_product":
        return False
    parts = [
        ev.get("title", ""),
        ev.get("summaryZh", ""),
        ev.get("locationName", ""),
        source_title,
        page_text[:12000],
    ]
    tags = ev.get("tags")
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags)
    blob = " ".join(part for part in parts if part).lower()
    return any(kw.lower() in blob for kw in APPAREL_PRODUCT_KEYWORDS)

def has_physical_store_signal(*texts) -> bool:
    blob = " ".join(t for t in texts if t).lower()
    return any(kw.lower() in blob for kw in PHYSICAL_STORE_SIGNALS)

def looks_like_media_location(location: str, source: str = "", source_title: str = "") -> bool:
    loc = re.sub(r"\s+", "", location or "").lower()
    if not loc:
        return False
    src = re.sub(r"\s+", "", " ".join([source or "", source_title or ""])).lower()
    if len(loc) >= 4 and loc in src:
        return True
    return any(kw.lower() in loc for kw in MEDIA_LOCATION_HINTS)

def is_venue_less_generic_new_product(ev: dict, source_title: str = "",
                                      source: str = "", source_url: str = "",
                                      page_text: str = "") -> bool:
    """High-confidence pre-save reject for generic merchandise articles.

    Keep this intentionally narrow: secondary media is allowed when it clearly
    names a physical store/venue. This only rejects non-trusted new_product
    records that look like generic merchandise coverage and lack store signals.
    """
    if ev.get("type") != "new_product":
        return False
    if is_trusted_date_source(source_url):
        return False

    loc = (ev.get("locationName") or "").strip()
    physical = has_physical_store_signal(
        loc, ev.get("title", ""), ev.get("summaryZh", ""),
        source_title, page_text[:12000],
    )
    if physical:
        return False

    generic = is_generic_merch_title(ev.get("title", ""), source_title)
    bad_location = (not loc) or looks_like_media_location(loc, source, source_title)
    return generic and bad_location

# 官方／權威來源（新聞稿、品牌官方）——額度有限，這些先處理（資料一定正確、日期齊全）
OFFICIAL_SOURCE_HINTS = [
    "pr times", "prtimes", "プレスリリース", "press release",
    "ポケモン", "pokemon", "サンリオ", "sanrio", "ちいかわ", "benelic",
    "スカイツリー", "skytree", "ハウステンボス", "huis ten bosch",
]

def is_official_source(source: str) -> bool:
    s = (source or "").lower()
    return any(h in s for h in OFFICIAL_SOURCE_HINTS)

# 只信任這些網域的「活動日期」：官方新聞稿、品牌官網、場館/百貨/商場的單一活動頁。
# 一般新聞媒體的內文常夾雜公告日、巡迴各城市日期 → 容易抓錯，故不從其內文自動補日期
# （寧可顯示「日期未定」，也不要顯示錯的日期）。
TRUSTED_DATE_DOMAINS = [
    # 新聞稿 / 官方
    "prtimes.jp", "atpress.ne.jp", "dreamnews.jp",
    "pokemon.co.jp", "pokemon.com.tw", "tw.portal-pokemon.com", "pokemon-cafe.jp",
    "oneheart65.net",
    "sanrio.co.jp", "sanrio.com.tw",
    "chiikawa-info.jp", "chiikawa-market.com", "chiikawamogumogu.jp", "benelic.com", "kiddyland.co.jp",
    "dickbruna.jp", "miffykitchenbakery.jp",
    # 場館 / 百貨 / 商場 / Outlet（單一活動頁，日期通常只有該活動）
    "tokyo-skytree.jp", "sunshinecity.jp", "parco.jp", "lucua.jp", "aeonmall.com",
    "mitsui-shopping-park.com", "takashimaya.co.jp", "mistore.jp",
    "hankyu-dept.co.jp", "hankyu-hanshin-dept.co.jp", "daimaru.co.jp",
    "matsuzakaya.co.jp", "sogo-seibu.jp", "lumine.ne.jp",
    "0101.co.jp", "tobu-dept.jp", "keionet.com", "odakyu-dept.co.jp",
    "hep-five.com", "grandfront-osaka.jp", "huistenbosch.co.jp",
    "leafkyoto.net", "store.tsite.jp", "collabo-cafe.com",
]

def is_trusted_date_source(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u or "google.com/search" in u:
        return False
    host = urlparse(u).netloc
    if host.startswith("www."):
        host = host[4:]
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in TRUSTED_DATE_DOMAINS)

def is_unstable_source_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return not u or "google.com/search" in u or "news.google.com" in u

GN_RSS    = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
GN_RSS_TW = "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ja,zh-TW;q=0.9,en;q=0.8",
}

# ── API Key 載入 ───────────────────────────────────────────────────────────────

def load_env():
    env = dict(os.environ)  # 系統環境變數作為底層
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if v:  # .env 的非空值覆蓋系統變數
                    env[k] = v
    return env

def _collect_keys(env: dict, base: str) -> list[str]:
    """收集多把 key：支援逗號分隔，或 KEY / KEY_2 / KEY_3 …多行"""
    keys: list[str] = []
    raw = env.get(base, "")
    if raw:
        keys.extend(k.strip() for k in raw.split(",") if k.strip())
    i = 2
    while env.get(f"{base}_{i}", ""):
        keys.extend(k.strip() for k in env[f"{base}_{i}"].split(",") if k.strip())
        i += 1
    # 去重但保留順序
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out

def detect_ai_backend(env: dict):
    """回傳 ('anthropic', [keys]) 或 ('gemini', [keys]) 或 None"""
    ak = _collect_keys(env, "ANTHROPIC_API_KEY")
    if ak:
        return ("anthropic", ak)
    gk = _collect_keys(env, "GEMINI_API_KEY")
    if gk:
        return ("gemini", gk)
    return None

# ── AI 呼叫（支援 Claude 和 Gemini）────────────────────────────────────────────

EXTRACT_PROMPT = """你是角色周邊情報萃取助手，專門幫旅人篩選「值得專程去逛、買得到限定商品」的活動。
以下是一則新聞（可能日文或中文）。

【relevant: true 只限這四種「去現場買得到東西」的情報】
1. 快閃店 / POP UP STORE / 期間限定店（販售周邊商品）
2. 新商品發售（在實體門市/官方店舖開賣的周邊新品）
3. 活動限定商品（特展、聯名活動、週年慶現場的「限定販售」周邊）
4. 限定餐飲：主題咖啡廳 / 限定菜單 / 限定甜點食物
並且：必須是 {brand_label} 的可信情報、地點在日本或台灣。

【一律 relevant: false（即使有提到本品牌也不要）】
- 體育/賽事類：棒球主題日、球場應援、始球式、開球、路跑、馬拉松、RUN 活動、運動賽事聯名出場
- 純體驗/無商品：見面會、握手會、拍照打卡點、燈光秀、遊行(parade)本身、抽獎派對（除非主軸是限定商品販售）
- 多活動「總整理/懶人包」式報導（內容雜揉很多無關活動，無單一明確的購物地點與檔期）
- 超商/藥妝/百元店/量販店的聯名小商品（7-11、全家、唐吉訶德、DAISO、Seria、Canddo、驚安殿堂等）
- 食品飲料聯名上架（醬油、優格、軟糖、糖果、寶礦力、力保美達等量販通路商品）
- 麥當勞兒童餐、扭蛋、轉蛋、盲盒等隨機販售
- 電影/動畫/聲優/主題曲/預告/手遊更新等媒體消息
- 純線上販售、再販通知、商品開箱評測
- 香港/海外（非日本非台灣）的活動

標題：{title}
摘要：{description}
來源：{source} / 新聞發布日：{pub_date}

【日期規則 — 非常重要，會影響旅行行程計算】
- startDate / endDate 只能填「新聞內文明確寫出的活動舉辦日期」
- 例如標題寫「7月10日から」「7/4開展」「5/22〜6/30」才可填入
- 若無法從標題或摘要明確判斷活動日期 → 一律留空字串 ""
- ⚠️ 絕對不可以把「新聞發布日（{pub_date}）」當成活動日期填入
- 寧可留空，也不要猜測或填錯日期

不符合 → 只回傳：{{"relevant": false}}

符合 → 回傳 JSON（繁體中文，非日文）：
{{
  "relevant": true,
  "brand": "{brand}",
  "title": "品牌名保留英文，其餘繁中，20字內",
  "type": "popup|new_product|campaign|store|cafe|lottery|reservation 擇一",
  "country": "JP 或 TW",
  "city": "活動實際所在的城市/縣，用英文（如 Tokyo/Osaka/Nagasaki/Saitama/Taipei…）；⚠️務必正確，絕不可把非該城市的場館硬塞成別的城市；無法確定就留空 ''",
  "locationName": "地點全名，不明填空",
  "startDate": "YYYY-MM-DD，不明填空",
  "endDate": "YYYY-MM-DD，未結束或不明填空",
  "summaryZh": "繁中摘要，60字內，說明地點、內容、注意事項",
  "needReservation": false,
  "hasLimitedGoods": false,
  "tags": ["最多4個繁中標籤"]
}}

只回傳 JSON。"""

class RateLimitError(Exception):
    """Gemini/Claude 配額或速率上限（429）"""

def call_claude_once(api_key: str, prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError:
        raise RateLimitError("Claude 429")
    return msg.content[0].text.strip()

GEMINI_MODEL = "gemini-2.5-flash-lite"

def call_gemini_once(api_key: str, prompt: str) -> str:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    last_err = None
    for attempt in range(3):
        try:
            resp = requests.post(url, json=body, timeout=30)
            if resp.status_code == 429:
                # 先當成短暫每分鐘上限，等一下重試一次；仍 429 視為此 key 配額用盡
                if attempt < 1:
                    time.sleep(20)
                    continue
                raise RateLimitError("429 配額/速率上限")
            if resp.status_code in (500, 502, 503, 504):
                last_err = f"{resp.status_code}"
                time.sleep(3 * (attempt + 1))
                continue
            resp.raise_for_status()
            data = resp.json()
            cand = data["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            if not parts:
                raise ValueError(f"Gemini 無輸出：finishReason={cand.get('finishReason')}")
            return parts[0]["text"].strip()
        except requests.RequestException as e:
            last_err = str(e)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Gemini 連續失敗：{last_err}")

class KeyRotator:
    """多把 key 自動輪替：一把撞配額（429）就換下一把，全部用完才丟 RateLimitError"""
    def __init__(self, kind: str, keys: list[str]):
        self.kind = kind
        self.keys = keys
        self.idx = 0
        self.exhausted: set[int] = set()
        self._once = call_claude_once if kind == "anthropic" else call_gemini_once

    @property
    def active_label(self) -> str:
        return f"key #{self.idx + 1}/{len(self.keys)}"

    def call(self, prompt: str) -> str:
        tried = 0
        while tried < len(self.keys):
            if self.idx in self.exhausted:
                self.idx = (self.idx + 1) % len(self.keys)
                tried += 1
                continue
            try:
                return self._once(self.keys[self.idx], prompt)
            except RateLimitError:
                self.exhausted.add(self.idx)
                if len(self.keys) > 1:
                    print(f"        （{self.active_label} 配額用盡，換下一把）")
                self.idx = (self.idx + 1) % len(self.keys)
                tried += 1
        raise RateLimitError("所有 key 配額都用盡")

# ── RSS 抓取 ──────────────────────────────────────────────────────────────────

def fetch_rss(query: str, is_tw: bool) -> list[dict]:
    url = (GN_RSS_TW if is_tw else GN_RSS).format(q=requests.utils.quote(query))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:
        print(f"  ⚠️  RSS 失敗：{e}")
        return []

    items = []
    for item in root.findall(".//item"):
        title = item.findtext("title", "").strip()
        link  = item.findtext("link", "").strip()
        pub   = item.findtext("pubDate", "").strip()
        desc  = re.sub(r"<[^>]+>", "", item.findtext("description", "")).strip()
        src_el = item.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        if title:
            items.append({"title": title, "link": link, "pubDate": pub,
                          "description": desc[:300], "source": source})
    return items

# 搜尋用的品牌關鍵字（日本活動用日文、台灣活動用中文，命中率較高）
BRAND_SEARCH_TERM = {
    "JP": {"pokemon": "ポケモン", "miffy": "ミッフィー", "chiikawa": "ちいかわ", "sanrio": "サンリオ"},
    "TW": {"pokemon": "寶可夢", "miffy": "Miffy", "chiikawa": "吉伊卡哇", "sanrio": "三麗鷗"},
}

def best_search_query(ev: dict) -> str:
    """組出最能命中原文的搜尋字串：地點 + 品牌；地點缺失才退回標題。"""
    loc = (ev.get("locationName") or "").strip()
    country = ev.get("country", "JP")
    brand = ev.get("brand", "")
    term = BRAND_SEARCH_TERM.get(country, BRAND_SEARCH_TERM["JP"]).get(brand, brand)
    if loc and len(loc) >= 3:
        return f"{loc} {term}".strip()
    return (ev.get("sourceTitle") or ev.get("title") or term).strip()

def search_url(query: str) -> str:
    # 退路：Google 搜尋連結（永遠可開，用「地點+品牌」命中率高）
    return "https://www.google.com/search?q=" + requests.utils.quote(query)

def _valid_md(mo: int, d: int) -> bool:
    return 1 <= mo <= 12 and 1 <= d <= 31

def _mk_iso(y: int, mo: int, d: int) -> str | None:
    return f"{y:04d}-{mo:02d}-{d:02d}" if _valid_md(mo, d) else None

# 起始日後常見的「開跑」提示語（用來提高單一日期的可信度，避免抓到隨機日期）
_WEEKDAY = r"[日月火水木金土一二三四五六]"
_DAY_SUFFIX = rf"\s*日?\s*[（(]?{_WEEKDAY}*[)）]?\s*"
_START_CUE = (rf"{_DAY_SUFFIX}"
              r"(?:から|スタート|開始|より|開幕|開催|販売|発売|登場|オープン|"
              r"起|開跑|開展|開賣|起跑|～|〜|~|－|—|–|-|至|到)")
_DATE_RANGE_LABEL = re.compile(r"(?:活動期間|開催期間|會期|会期|期間)\s*[:：]?\s*.{0,160}", re.S)

def extract_dates(text: str, ref_year: int | None = None, is_html: bool = True,
                  scan_chars: int = 4000) -> tuple[str, str]:
    """從來源頁面（或摘要）擷取活動期間。回傳 (startISO, endISO)，抓不到回 ('','')。

    支援：
      - 帶西元年：2026年5月27日～6月14日 / 2026/5/27-6/14
      - 無年份（日文常見）：5月27日(水)～6月14日(日) / 5/27〜6/14（年份用 ref_year 推定）
      - 中文：4月17日至6月8日 / 6月12日～6月14日 / 即日起至6月8日
      - 單一起始日（後接「から/スタート/起/開賣…」才採用，降低誤抓）
    日期通常在頁面開頭，只掃前段，避免抓到頁尾版權/其他活動日期。"""
    if not text:
        return "", ""
    if is_html:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text.replace("　", " "))[:scan_chars]
    ry = ref_year or datetime.now(timezone.utc).year

    ymd = r"(?:(20\d{2})\s*[年/.]\s*)?(\d{1,2})\s*[月/.]\s*(\d{1,2})"
    sep = rf"(?:{_DAY_SUFFIX}(?:から|より)\s*|{_DAY_SUFFIX}[～〜~\-−–—－至到]{{1,2}}\s*)"
    # 範圍：[年]M月D日 〜 [年]M月D日
    m = re.search(ymd + sep + ymd + rf"{_DAY_SUFFIX}(?:まで)?", text)
    if m:
        y1, mo1, d1, y2, mo2, d2 = m.groups()
        mo1, d1, mo2, d2 = int(mo1), int(d1), int(mo2), int(d2)
        Y1 = int(y1) if y1 else ry
        Y2 = int(y2) if y2 else Y1
        if not y2 and (mo2, d2) < (mo1, d1):
            Y2 = Y1 + 1  # 結束月份比開始小且未標年 → 跨年
        s, e = _mk_iso(Y1, mo1, d1), _mk_iso(Y2, mo2, d2)
        if s and e:
            return s, e
    # 中文「(即日起)至/到 M月D日」→ 只有結束日
    m = re.search(r"(?:即日起|即日|自即日|起)?\s*(?:至|到|截[至止])\s*" + ymd + r"\s*日?", text)
    if m:
        y, mo, d = m.groups()
        e = _mk_iso(int(y) if y else ry, int(mo), int(d))
        if e:
            return "", e
    # 單一起始日：[年]M月D日 + 開跑提示語
    m = re.search(ymd + _START_CUE, text)
    if m:
        y, mo, d = m.groups()
        s = _mk_iso(int(y) if y else ry, int(mo), int(d))
        if s:
            return s, ""
    return "", ""

def apply_labeled_extracted_dates(data: dict, text: str, ref_year: int | None, is_html: bool,
                                  scan_chars: int = 90000) -> bool:
    """For untrusted media, only fill dates from explicit labeled ranges.

    This is narrower than apply_extracted_dates(): the source text must say
    活動期間/開催期間/会期/期間 near the date range, and if the event already has a
    startDate, the extracted start must match it.
    """
    if data.get("startDate") and data.get("endDate"):
        return False
    if not text:
        return False
    if is_html:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text.replace("　", " "))[:scan_chars]
    for m in _DATE_RANGE_LABEL.finditer(text):
        s, e = extract_dates(m.group(0), ref_year=ref_year, is_html=False,
                             scan_chars=len(m.group(0)))
        if not s or not e:
            continue
        if data.get("startDate") and data["startDate"] != s:
            continue
        if e < s:
            continue
        changed = False
        if not data.get("startDate"):
            data["startDate"] = s
            changed = True
        if not data.get("endDate"):
            data["endDate"] = e
            changed = True
        if changed:
            print(f"    📅 標籤區間補抓：{data.get('startDate') or '—'} ~ {data.get('endDate') or '—'}")
            return True
    return False

def _pub_year(pub: str) -> int | None:
    try:
        return parsedate_to_datetime(pub).year
    except Exception:
        return None

def apply_extracted_dates(data: dict, text: str, ref_year: int | None, is_html: bool,
                          scan_chars: int = 4000) -> bool:
    """從 text 補抓活動日期，只填入 data 中目前為空的 start/end 欄位。
    防呆：起始日不早於約 400 天前（避免抓到舊報導/版權年份）。回傳是否有補上。"""
    if data.get("startDate") and data.get("endDate"):
        return False
    s, e = extract_dates(text, ref_year=ref_year, is_html=is_html, scan_chars=scan_chars)
    if not s and not e:
        return False
    if s:
        age = _days_ago_iso(s)
        if age is None or age > 400:
            return False  # 起始日太舊，整組不採用（多半抓錯）
    changed = False
    if s and not data.get("startDate"):
        data["startDate"] = s; changed = True
    if e and not data.get("endDate"):
        data["endDate"] = e; changed = True
    # 合理性檢查：結束日不可早於開始日（多半是抓錯第二個日期）→ 丟掉 endDate
    sd, ed = data.get("startDate"), data.get("endDate")
    if sd and ed and ed < sd:
        data["endDate"] = ""
    if changed:
        print(f"    📅 補抓日期：{data.get('startDate') or '—'} ~ {data.get('endDate') or '—'}")
    return changed

_KANA = re.compile(r"[぀-ヿ]")  # 平假名 + 片假名

def theme_tokens(*texts) -> list[str]:
    """抽出「」『』中、含日文假名的主題詞（產品線/活動名）。
    這類專有名詞會原樣出現在日文來源頁，可用來驗證活動是否真的對應來源。
    只取含假名者：純英文/純中文詞在日文頁常以不同寫法出現，比對易誤殺，故略過。"""
    toks = set()
    for t in texts:
        if not t:
            continue
        for m in re.findall(r"[「『]([^」』]{2,20})[」』]", t):
            m = m.strip()
            if _KANA.search(m):
                toks.add(m)
    return list(toks)

def decode_google_news_url(gurl: str) -> str | None:
    """把 Google News 加密網址解回真實文章 URL；失敗回 None。"""
    try:
        m = re.search(r"/articles/([^?]+)", gurl)
        if not m:
            return None
        art_id = m.group(1)
        r = requests.get(gurl, headers=HEADERS, timeout=15)
        sig = re.search(r'data-n-a-sg="([^"]+)"', r.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
        if not (sig and ts):
            return None
        payload = [[["Fbv4je", json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
              None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            art_id, ts.group(1), sig.group(1)]), None, "generic"]]]
        body = "f.req=" + requests.utils.quote(json.dumps(payload))
        br = requests.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=body, timeout=15)
        urls = [u for u in re.findall(r'https?://[^\\"]+', br.text)
                if "google.com" not in u and "gstatic" not in u]
        return urls[0] if urls else None
    except Exception:
        return None

# ── 資料讀寫 ───────────────────────────────────────────────────────────────────

def load_events() -> list[dict]:
    if EVENTS_JSON.exists():
        return json.loads(EVENTS_JSON.read_text(encoding="utf-8"))
    return []

DISPLAY_REPLACEMENTS = {
    "miffy": {
        "フラワーミッフィー": "Flower Miffy",
    },
}

def normalize_display_terms(ev: dict) -> dict:
    """Normalize brand/place display terms before writing public data."""
    replacements = DISPLAY_REPLACEMENTS.get(ev.get("brand", ""), {})
    if not replacements:
        return ev
    for field in ("title", "locationName", "summaryZh"):
        value = ev.get(field)
        if isinstance(value, str):
            for src, dst in replacements.items():
                value = value.replace(src, dst)
            ev[field] = value
    tags = ev.get("tags")
    if isinstance(tags, list):
        normalized_tags = []
        for tag in tags:
            if isinstance(tag, str):
                for src, dst in replacements.items():
                    tag = tag.replace(src, dst)
            normalized_tags.append(tag)
        ev["tags"] = normalized_tags
    return ev

def save_events(events: list[dict]):
    for ev in events:
        normalize_display_terms(ev)
    EVENTS_JSON.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

def load_last_updated_date() -> str:
    try:
        data = json.loads(LAST_UPDATED_JSON.read_text(encoding="utf-8"))
        updated_at = data.get("updatedAt", "")
        return updated_at[:10] if updated_at else ""
    except Exception:
        return ""

def build_update_diff(previous: list[dict], current: list[dict], *,
                      date: str = TODAY, baseline_date: str = "") -> dict:
    """Build the public 'today updates' file from the previous visible data state."""
    new_events: list[dict] = []
    replacements: list[dict] = []
    for ev in current:
        match = next((old for old in previous if is_same_event_for_update_diff(old, ev)), None)
        if match:
            if match.get("id") != ev.get("id"):
                replacements.append({"from": match.get("id", ""), "to": ev.get("id", "")})
            continue
        new_events.append(ev)

    counts = {brand: 0 for brand in DEFAULT_BRANDS}
    for ev in new_events:
        brand = ev.get("brand", "")
        if brand in counts:
            counts[brand] += 1

    return {
        "date": date,
        "baselineDate": baseline_date,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "baselineEventCount": len(previous),
        "currentEventCount": len(current),
        "newEventCount": len(new_events),
        "countsByBrand": counts,
        "newEventIds": [ev.get("id", "") for ev in new_events if ev.get("id")],
        "replacements": replacements,
    }

def save_update_diff(previous: list[dict], current: list[dict], baseline_date: str = "") -> dict:
    diff = build_update_diff(previous, current, baseline_date=baseline_date)
    UPDATE_DIFF_JSON.write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    return diff

def replace_in_place(events: list[dict], fresh: list[dict], should_replace) -> list[dict]:
    """Update structured-source events without moving unchanged records."""
    by_id = {e.get("id"): e for e in fresh if e.get("id")}
    used: set[str] = set()
    out: list[dict] = []

    for ev in events:
        eid = ev.get("id")
        if eid in by_id:
            out.append(by_id[eid])
            used.add(eid)
        elif should_replace(ev):
            continue
        else:
            out.append(ev)

    for ev in fresh:
        eid = ev.get("id")
        if not eid or eid not in used:
            out.append(ev)
            if eid:
                used.add(eid)
    return out

# ── 已處理新聞記錄（避免重跑時重複送 AI，省配額）──────────────────────────────

PROCESSED_JSON = Path(__file__).parent / "processed.json"

def load_processed() -> set[str]:
    if PROCESSED_JSON.exists():
        try:
            return set(json.loads(PROCESSED_JSON.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()

def save_processed(seen: set[str]):
    # 只保留最近 2000 筆，避免無限長大
    arr = list(seen)[-2000:]
    PROCESSED_JSON.write_text(json.dumps(arr, ensure_ascii=False), encoding="utf-8")

# ── 壞資料黑名單（已確認移除的，新聞再抓到就自動擋，防反覆復活）──────────────────
REJECTED_JSON = Path(__file__).parent / "rejected.json"

def load_rejected() -> dict:
    if REJECTED_JSON.exists():
        try:
            d = json.loads(REJECTED_JSON.read_text(encoding="utf-8"))
            return {"url_contains": [s.lower() for s in d.get("url_contains", [])],
                    "title_contains": d.get("title_contains", [])}
        except Exception:
            pass
    return {"url_contains": [], "title_contains": []}

_REJECTED = {"url_contains": [], "title_contains": []}  # run() 啟動時載入

def is_rejected_url(url: str) -> bool:
    u = (url or "").lower()
    return any(s in u for s in _REJECTED["url_contains"])

def is_rejected_title(title: str) -> bool:
    t = title or ""
    return any(s in t for s in _REJECTED["title_contains"])

# ── 年份驗證：擋「舊文復活」。掃頁面前段的「20XX年」，若最大年份 < 今年 → 整篇是舊活動 ──
# 抓「日期型年份」：20XX 後面接 年 / . / / / - 再接數字（如 2016年、2016.04.19、2026/6/1）
_YEAR_RE = re.compile(r"(20\d{2})\s*[年./\-]\s*\d")
CURRENT_YEAR = int(TODAY[:4])

def stale_by_year(text: str, scan_chars: int = 4000) -> bool:
    """頁面前段提到的最大「日期年份」< 今年 → 視為舊活動（如 2016 年的福岡咖啡廳被重新索引）。
    找不到任何年份則不判定（回 False，交給其他守則）。"""
    years = [int(y) for y in _YEAR_RE.findall((text or "")[:scan_chars])]
    return bool(years) and max(years) < CURRENT_YEAR

# ── 新聞時效過濾 ───────────────────────────────────────────────────────────────

MAX_NEWS_AGE_DAYS = 45  # 只處理近 N 天發布的新聞（過舊的多半是已結束活動）

def pubdate_age_days(pub: str) -> float | None:
    """回傳新聞距今幾天；無法解析回 None"""
    try:
        dt = parsedate_to_datetime(pub)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None

# ── 去重（同一活動不同媒體報導）────────────────────────────────────────────────

def _norm(s: str) -> str:
    """正規化字串：轉小寫、去空白與符號，方便比對"""
    s = (s or "").lower()
    return re.sub(r"[\s\(\)（）®™☆★・·\-:：、。.,!！?？]", "", s)

GENERIC_DEDUP_LOCATIONS = {
    "ポケモンセンター",
    "ポケモンセンター各店",
    "台北寶可夢中心",
    "台灣寶可夢中心",
    "台湾宝可梦中心",
    "pokemoncenter",
    "pokemoncentertaipei",
}
GENERIC_DEDUP_LOCATION_HINTS = [
    "各店",
    "各店舗",
    "対象店",
    "一部店舗",
    "一部キデイランド店舗",
    "公式ショップ",
    "ホビーショップ",
]
GENERIC_DEDUP_LOCATION_KEYS = {_norm(x) for x in GENERIC_DEDUP_LOCATIONS}
CHAINWIDE_LOCATION_HINTS = [
    "全国",
    "全國",
    "各店",
    "各店舗",
    "オンライン",
    "online",
]

CHAIN_CAMPAIGN_ALIASES = {
    "flower-miffy": ["Flower Miffy", "フラワーミッフィー"],
}

CHAIN_CAMPAIGN_CONCEPTS = [
    ("birthday", ["birthday", "バースデー", "誕生日", "生日"]),
    ("anniversary", ["anniversary", "周年", "週年"]),
]

def is_generic_dedup_location(loc: str) -> bool:
    """Locations too broad to prove two product launches are the same event."""
    text = loc or ""
    norm = _norm(text)
    return norm in GENERIC_DEDUP_LOCATION_KEYS or any(
        hint.lower() in text.lower() for hint in GENERIC_DEDUP_LOCATION_HINTS
    )

def is_chainwide_location(loc: str) -> bool:
    text = loc or ""
    lower = text.lower()
    return any(hint.lower() in lower for hint in CHAINWIDE_LOCATION_HINTS)

def _event_blob(ev: dict) -> str:
    parts = []
    for field in ("title", "locationName", "summaryZh", "sourceTitle"):
        value = ev.get(field)
        if isinstance(value, str):
            parts.append(value)
    tags = ev.get("tags")
    if isinstance(tags, list):
        parts.extend(str(tag) for tag in tags)
    return _norm(" ".join(parts))

def chain_campaign_key(ev: dict) -> str | None:
    """Stable key for chain-wide activity pages that may mention one store first."""
    if ev.get("type", "") not in ACTIVITY_TYPES:
        return None
    start = ev.get("startDate", "")
    if not start:
        return None
    blob = _event_blob(ev)
    chain = next(
        (
            name for name, aliases in CHAIN_CAMPAIGN_ALIASES.items()
            if any(_norm(alias) in blob for alias in aliases)
        ),
        "",
    )
    if not chain:
        return None
    concept = next(
        (
            name for name, aliases in CHAIN_CAMPAIGN_CONCEPTS
            if any(_norm(alias) in blob for alias in aliases)
        ),
        "",
    )
    if not concept:
        return None
    return "|".join([ev.get("brand", ""), chain, concept, start])

# 知名場館別名 → 統一代號（讓同場館不同寫法能去重）
VENUE_CANON = [
    (["ハウステンボス", "huistenbosch", "豪斯登堡", "huistenbo"], "huistenbosch"),
    (["ピューロランド", "puroland", "彩虹樂園", "三麗鷗樂園", "サンリオピューロランド"], "puroland"),
    (["スカイツリー", "晴空塔", "ソラマチ", "skytree", "そらまち"], "skytree"),
    # 台灣常見活動場館（同活動常被不同媒體用不同標題報導，靠場館統一去重）
    (["夢時代", "統一時代", "時代會館", "統一夢時代", "dream mall"], "kaohsiung-dreammall"),
    (["華山1914", "華山文創", "華山"], "huashan"),
    (["松山文創", "松菸", "松山文化創意"], "matsuyama-bunka"),
    (["駁二"], "pier2"),
    (["勤美誠品", "草悟道", "勤美"], "taichung-cmp"),
    (["新光三越台南", "南紡"], "tainan-skm"),
]

def canon_venue(loc: str, title: str = "") -> str | None:
    blob = _norm(loc) + _norm(title)
    for aliases, canon in VENUE_CANON:
        if any(a in blob for a in aliases):
            return canon
    return None

def _days_ago_iso(iso_date: str) -> float | None:
    """YYYY-MM-DD 距今幾天；無法解析回 None"""
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except Exception:
        return None

def _date_gap_days(a: str, b: str) -> int | None:
    try:
        da = datetime.strptime(a, "%Y-%m-%d")
        db = datetime.strptime(b, "%Y-%m-%d")
        return abs((da - db).days)
    except Exception:
        return None

# 無結束日時，依類型用「起始日距今天數」推估是否已過期（補洞：無 endDate 的活動
# 原本永遠清不掉，導致過期活動殘留）。活動型檔期通常數天~數週；商品發售熱度約兩月。
ACTIVITY_TYPES = {"popup", "cafe", "campaign"}      # 有明確檔期的活動
SELLING_TYPES  = {"new_product", "lottery", "reservation"}  # 商品發售/抽選/預約

def _real_source_url(ev: dict) -> str:
    url = ev.get("sourceUrl", "")
    return "" if "google.com/search" in url else url

def is_same_event_for_update_diff(old: dict, new: dict) -> bool:
    """Whether `new` is the same real-world item as an older public entry."""
    if old.get("id") and old.get("id") == new.get("id"):
        return True
    old_url, new_url = _real_source_url(old), _real_source_url(new)
    if old_url and old_url == new_url:
        old_city, new_city = old.get("city", ""), new.get("city", "")
        if old_city and new_city and old_city != new_city:
            return False
        old_start, new_start = old.get("startDate", ""), new.get("startDate", "")
        if old_start and new_start:
            gap = _date_gap_days(old_start, new_start)
            if gap is not None and gap > 14:
                return False
        return True
    if old.get("brand") != new.get("brand"):
        return False

    old_title = old.get("title", "")
    new_title = new.get("title", "")
    old_norm, new_norm = _norm(old_title), _norm(new_title)
    if old_norm and old_norm == new_norm:
        return True

    old_type, new_type = old.get("type", ""), new.get("type", "")
    if old_type in SELLING_TYPES or new_type in SELLING_TYPES:
        return False
    if old_type not in ACTIVITY_TYPES or new_type not in ACTIVITY_TYPES:
        return False

    old_city, new_city = old.get("city", ""), new.get("city", "")
    if old_city and new_city and old_city != new_city:
        return False

    old_start, new_start = old.get("startDate", ""), new.get("startDate", "")
    if not old_start or not new_start:
        return False
    gap = _date_gap_days(old_start, new_start)
    if gap is None or gap > 3:
        return False

    old_end, new_end = old.get("endDate", ""), new.get("endDate", "")
    if old_end and new_end and old_end != new_end:
        return False

    old_chain = chain_campaign_key(old)
    new_chain = chain_campaign_key(new)
    if old_chain and old_chain == new_chain:
        return True

    old_loc, new_loc = old.get("locationName", ""), new.get("locationName", "")
    old_canon = canon_venue(old_loc, old_title)
    new_canon = canon_venue(new_loc, new_title)
    if old_canon and old_canon == new_canon:
        return True
    if old_loc and new_loc and SequenceMatcher(None, _norm(old_loc), _norm(new_loc)).ratio() >= 0.6:
        return True
    return False

def _is_past(ev: dict) -> bool:
    """活動是否已結束。
    - 有結束日：已過今天 = 過期。
    - 無結束日（補洞，避免殘留）：
        · 活動型(popup/cafe/campaign)：起始日距今 >30 天 = 過期；完全無日期 = 無法確認現行 → 當過期。
        · 商品型(new_product/lottery/reservation)：起始日距今 >60 天 = 過期；完全無日期 → 當過期。
        · 其他(常設 store 等)：沿用起始日 >90 天的寬鬆規則，完全無日期則保留。
    未來日期(age<0)一律不算過期。"""
    end = ev.get("endDate")
    if end:
        return end < TODAY
    t = ev.get("type", "")
    sd = ev.get("startDate")
    age = _days_ago_iso(sd) if sd else None
    if t in ACTIVITY_TYPES:
        return True if age is None else age > 30
    if t in SELLING_TYPES:
        return True if age is None else age > 60
    # store / 其他：常設性質，保守
    return age is not None and age > 90

def dedup_events(events: list[dict]) -> tuple[list[dict], int]:
    """合併同一活動的重複條目。回傳（清理後清單, 移除數量）"""
    kept: list[dict] = []
    title_keys: dict[str, int] = {}     # (brand, norm_title) -> kept index
    loc_keys: dict[str, int] = {}       # (brand, norm_location) -> kept index
    url_keys: dict[str, int] = {}       # 真實來源 URL -> kept index
    date_keys: dict[str, int] = {}      # (brand, city, startDate) -> kept index
    theme_keys: dict[str, int] = {}     # (brand, 日文主題詞) -> kept index
    chain_campaign_keys: dict[str, int] = {}  # (brand, chain, concept, startDate)
    removed = 0

    def completeness(e: dict) -> int:
        score = sum(bool(e.get(f)) for f in ("startDate", "endDate", "city", "locationName"))
        if e.get("sourceType") == "official_site":  # 手動精選優先保留
            score += 10
        return score

    def direct_url(e: dict) -> str | None:
        u = e.get("sourceUrl", "")
        # 只有真實文章 URL 才拿來比對；搜尋連結是通用的，不算重複
        return u if u and "google.com/search" not in u else None

    for ev in events:
        b = ev.get("brand", "")
        tkey = b + "|" + _norm(ev.get("title", ""))
        loc = ev.get("locationName", "")
        lkey = (b + "|" + _norm(loc)) if (
            loc and len(_norm(loc)) >= 3 and not is_generic_dedup_location(loc)
        ) else None
        ukey = direct_url(ev)
        city, sd = ev.get("city", ""), ev.get("startDate", "")
        dkey = (b + "|" + city + "|" + sd) if (
            city and sd and ev.get("type", "") in ACTIVITY_TYPES
        ) else None  # 活動型同品牌同城同開始日；商品同日可能不同系列，不套用
        ckey = chain_campaign_key(ev)
        # 商品型同一品牌常在同日/同頁推出多個系列；不要只靠主題詞合併。
        thkeys = [] if ev.get("type", "") in SELLING_TYPES else [
            b + "|" + t for t in theme_tokens(ev.get("title"), ev.get("summaryZh"))
        ]

        hit = None
        if ukey and ukey in url_keys:        # 相同真實來源 = 同一活動
            hit = url_keys[ukey]
        elif tkey in title_keys:
            hit = title_keys[tkey]
        elif dkey and dkey in date_keys:     # 同品牌+同城市+同開始日 = 同一活動
            hit = date_keys[dkey]
        elif ckey and ckey in chain_campaign_keys:
            hit = chain_campaign_keys[ckey]
        elif any(tk in theme_keys for tk in thkeys):  # 同品牌+相同日文主題詞 = 同一活動
            hit = theme_keys[next(tk for tk in thkeys if tk in theme_keys)]
        elif lkey and lkey in loc_keys:
            hit = loc_keys[lkey]

        # 城市鐵則：兩筆城市都有值且不同 = 不同活動，即使同來源頁也不合併。
        # （彙整/排程清單頁會列多個不同城市的場次共用同一 URL，如各地出張所）
        if hit is not None and city and kept[hit].get("city") and city != kept[hit].get("city"):
            hit = None

        # 日期鐵則：兩筆都有開始日且差距 >14 天 = 不同檔期，不合併（同場館的春檔/秋檔
        # 巡迴標題常完全相同，僅靠日期區分）。同一真實來源 URL 視為同篇報導，為例外不套用。
        hit_by_url = ukey is not None and url_keys.get(ukey) == hit
        if hit is not None and not hit_by_url and sd and kept[hit].get("startDate"):
            ga, gb = _days_ago_iso(sd), _days_ago_iso(kept[hit]["startDate"])
            if ga is not None and gb is not None and abs(ga - gb) > 14:
                hit = None

        if hit is not None:
            # 視為重複：保留資料較完整的那筆
            removed += 1
            if completeness(ev) > completeness(kept[hit]):
                # 用新的取代，但補上舊的非空欄位
                for f in ("startDate", "endDate", "city", "locationName"):
                    if f == "city" and is_chainwide_location(ev.get("locationName", "")):
                        continue
                    if not ev.get(f) and kept[hit].get(f):
                        ev[f] = kept[hit][f]
                kept[hit] = ev
            else:
                for f in ("startDate", "endDate", "city", "locationName"):
                    if not kept[hit].get(f) and ev.get(f):
                        kept[hit][f] = ev[f]
            continue

        idx = len(kept)
        kept.append(ev)
        title_keys[tkey] = idx
        if lkey:
            loc_keys[lkey] = idx
        if ukey:
            url_keys[ukey] = idx
        if dkey:
            date_keys[dkey] = idx
        if ckey:
            chain_campaign_keys.setdefault(ckey, idx)
        for tk in thkeys:
            theme_keys.setdefault(tk, idx)

    # 收尾：模糊比對（同品牌，且「同知名場館」或「同城市」時，標題夠相似就合併）
    def tsim(a: str, b: str) -> float:
        return SequenceMatcher(None, _norm(a), _norm(b)).ratio()

    result: list[dict] = []
    for ev in kept:
        merged = False
        for k in result:
            if k.get("brand") != ev.get("brand"):
                continue
            # 兩筆城市都有值且不同 = 不同活動，絕不合併。
            # （巡迴各地的快閃/出張所標題幾乎相同，如「Pokemon Center 出張所 in AEON MALL ○○」，
            #   只能靠城市區分；放任 sim≥0.72 會把羽生/今治/神戸北併成一筆＝過度合併）
            if k.get("city") and ev.get("city") and k.get("city") != ev.get("city"):
                continue
            sim = tsim(k.get("title", ""), ev.get("title", ""))
            same_venue = (canon_venue(ev.get("locationName", ""), ev.get("title", "")) is not None
                          and canon_venue(ev.get("locationName", ""), ev.get("title", ""))
                              == canon_venue(k.get("locationName", ""), k.get("title", "")))
            # 會場鐵則：兩筆都有 locationName、且明顯是不同會場(非同一已知場館、字串也不相近)
            # = 同城市的不同場次(如兵庫的ピオレ姫路 vs イオンモール伊丹，標題幾乎相同)，不合併。
            ln_e, ln_k = ev.get("locationName", ""), k.get("locationName", "")
            if ln_e and ln_k and not same_venue and tsim(ln_e, ln_k) < 0.5:
                continue
            if (
                (ev.get("type") in SELLING_TYPES or k.get("type") in SELLING_TYPES)
                and (is_generic_dedup_location(ln_e) or is_generic_dedup_location(ln_k))
            ):
                continue
            same_city = ev.get("city") and ev.get("city") == k.get("city")
            # 日期區間一致性：兩筆都有開始日時，差距 >14 天 = 不同檔期，絕不合併
            # （即使標題完全相同，如同一場館的春檔 vs 秋檔巡迴）。差距 ≤3 天 = 區間一致。
            sa, sb = ev.get("startDate"), k.get("startDate")
            date_conflict = date_aligned = False
            if sa and sb:
                ga, gb = _days_ago_iso(sa), _days_ago_iso(sb)
                if ga is not None and gb is not None:
                    gap = abs(ga - gb)
                    date_conflict, date_aligned = gap > 14, gap <= 3
            if date_conflict:
                continue
            fuzzy_allowed = (
                ev.get("type", "") in ACTIVITY_TYPES
                and k.get("type", "") in ACTIVITY_TYPES
            )
            # 場館字串相似（即使不在 VENUE_CANON 清單）：用於「同城+同活動但媒體標題寫法差很多」
            venue_close = bool(ln_e and ln_k and tsim(ln_e, ln_k) >= 0.6)
            ea, eb = ev.get("endDate"), k.get("endDate")
            range_aligned = date_aligned and (not ea or not eb or ea == eb)
            # 同品牌+同一已知場館，且其中一筆完全沒日期 → 幾乎一定是同活動的較不完整版本
            # （兩個不同檔期通常各自都有日期，故「一邊全無日期」可避免誤併不同檔期）
            one_dateless = not ev.get("startDate") or not k.get("startDate")
            if fuzzy_allowed and (
               (same_venue and sim >= 0.4) or (same_venue and one_dateless and sim >= 0.2)
               or (same_city and venue_close and date_aligned)
               or (venue_close and range_aligned)
               or (same_city and sim >= 0.50) or sim >= 0.72):
                # 合併到較完整者，補空欄位
                base = k if completeness(k) >= completeness(ev) else ev
                other = ev if base is k else k
                for f in ("startDate", "endDate", "city", "locationName"):
                    if not base.get(f) and other.get(f):
                        base[f] = other[f]
                if base is ev:
                    result[result.index(k)] = ev
                removed += 1
                merged = True
                break
        if not merged:
            result.append(ev)

    return result, removed

def clean_events(events: list[dict]) -> tuple[list[dict], int, int]:
    """移除過期活動 + 去重。回傳（清理後, 移除過期數, 去重數）"""
    fresh = [e for e in events if not _is_past(e)]
    past_removed = len(events) - len(fresh)
    deduped, dup_removed = dedup_events(fresh)
    return deduped, past_removed, dup_removed

def _completeness(e: dict) -> int:
    score = sum(bool(e.get(f)) for f in ("startDate", "endDate", "city", "locationName"))
    if "google.com/search" not in e.get("sourceUrl", ""):
        score += 2  # 有真實來源連結者優先保留
    return score

def _ai_dedup_locations_compatible(group: list[dict]) -> bool:
    """AI dedup is allowed only when concrete locations look compatible."""
    for i, left in enumerate(group):
        for right in group[i + 1:]:
            left_loc, right_loc = left.get("locationName", ""), right.get("locationName", "")
            if not left_loc or not right_loc:
                continue
            left_chain = chain_campaign_key(left)
            right_chain = chain_campaign_key(right)
            if left_chain and left_chain == right_chain:
                continue
            if _norm(left_loc) == _norm(right_loc):
                continue
            left_canon = canon_venue(left_loc, left.get("title", ""))
            right_canon = canon_venue(right_loc, right.get("title", ""))
            if left_canon and left_canon == right_canon:
                continue
            if SequenceMatcher(None, _norm(left_loc), _norm(right_loc)).ratio() >= 0.55:
                continue
            return False
    return True

AI_DEDUP_PROMPT = """以下是已蒐集的角色周邊活動清單，每筆有編號。
請找出指向「同一個真實活動」的重複編號群組（不同媒體報導同一檔活動）。

判定為同一活動（必須同時成立）：
- 同一品牌
- 同一城市或同一場館
- 同一檔活動：同一個快閃店/特展/咖啡廳/週年慶典本身

⚠️ 下列情況屬於「不同活動」，絕對不要合併：
- 不同主題/不同聯名（例如「30週年慶典」 vs 「6月新品·初音未來聯名」是兩回事）
- 例行月度新品 vs 特別活動
- 不同檔期（開始日相差很多）、不同分店、不同城市
- 巡迴活動的不同城市場次

寧可漏合併，也不要把不同活動硬湊在一起。

清單：
{rows}

只回傳 JSON：{{"duplicates": [[編號, 編號, ...], ...]}}
每個子陣列是一組互為重複的編號；沒有任何重複就回 {{"duplicates": []}}。"""

def ai_dedup(events: list[dict], rotator: "KeyRotator") -> tuple[list[dict], int]:
    """用一次 AI 呼叫，把啟發式漏掉的「改寫標題但同一活動」群組合併。
    安全防呆：只合併同品牌、且城市相容（相同或一方留空）者。回傳（清理後, 合併數）。"""
    if len(events) < 2:
        return events, 0
    rows = "\n".join(
        f"[{i}] {e.get('brand','')} | {e.get('city') or '城市未定'} | "
        f"{(e.get('startDate') or 'NA')}~{(e.get('endDate') or 'NA')} | "
        f"{e.get('title','')} / {(e.get('sourceTitle') or '')[:40]}"
        for i, e in enumerate(events))
    try:
        raw = rotator.call(AI_DEDUP_PROMPT.format(rows=rows))
    except RateLimitError:
        print("    ⚠️  AI 去重略過（配額用盡）")
        return events, 0
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return events, 0
    try:
        groups = json.loads(m.group()).get("duplicates", [])
    except Exception:
        return events, 0

    removed_idx: set[int] = set()
    n = len(events)
    for group in groups:
        ids = [i for i in group if isinstance(i, int) and 0 <= i < n and i not in removed_idx]
        if len(ids) < 2:
            continue
        # 安全防呆：同品牌 + 城市相容（相同或一方空）才採信 AI 的判定
        brands = {events[i].get("brand") for i in ids}
        if len(brands) != 1:
            continue
        cities = {events[i].get("city") for i in ids if events[i].get("city")}
        if len(cities) > 1:
            continue
        if not _ai_dedup_locations_compatible([events[i] for i in ids]):
            print(f"    ⚠️  AI 提議合併但場館/店系不同，保留不合併：{[events[i].get('title') for i in ids]}")
            continue
        # 日期防呆：同一活動不可能開始日相差太遠（>21天視為不同檔期，整組不合併）
        starts = []
        for i in ids:
            sd = events[i].get("startDate")
            dt = _days_ago_iso(sd) if sd else None
            if dt is not None:
                starts.append(dt)
        if starts and (max(starts) - min(starts)) > 21:
            print(f"    ⚠️  AI 提議合併但開始日相差過大，保留不合併：{[events[i].get('title') for i in ids]}")
            continue
        keep = max(ids, key=lambda i: _completeness(events[i]))
        for i in ids:
            if i == keep:
                continue
            for f in ("startDate", "endDate", "city", "locationName"):
                if not events[keep].get(f) and events[i].get(f):
                    events[keep][f] = events[i][f]
            # 保留較好的真實來源連結
            if ("google.com/search" in events[keep].get("sourceUrl", "")
                    and "google.com/search" not in events[i].get("sourceUrl", "")):
                events[keep]["sourceUrl"] = events[i]["sourceUrl"]
            removed_idx.add(i)
    if not removed_idx:
        return events, 0
    return [e for i, e in enumerate(events) if i not in removed_idx], len(removed_idx)

# ── 萃取單筆 ───────────────────────────────────────────────────────────────────

def extract_event(rotator: "KeyRotator", brand: str, item: dict) -> dict | None:
    prompt = EXTRACT_PROMPT.format(
        brand=brand,
        brand_label=BRAND_LABELS[brand],
        title=item["title"],
        description=item["description"],
        source=item["source"],
        pub_date=item["pubDate"],
    )
    try:
        raw = rotator.call(prompt)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        if not data.get("relevant"):
            return None
        data.pop("relevant", None)
        data["brand"] = brand  # 強制用程式的小寫品牌，別信 AI 大小寫
        # 用地點關鍵字修正城市（AI 常把非目標城市硬塞成目標城市）
        fixed = correct_city(data.get("locationName"), item["title"], data.get("title"))
        if fixed:
            data["city"] = fixed
        data["id"]          = brand[:2] + "-" + uuid.uuid4().hex[:6]
        data["sourceTitle"] = item["title"]  # 原始日文標題（備用）
        data["sourceType"]  = "official_social"
        data["createdAt"]   = TODAY
        data.setdefault("tags", [])
        # 來源連結：優先解出真實文章 URL，並做兩道驗證才採用——
        #   1) 連得過去（非 403/404…）  2) 頁面內容真的提到該品牌（關聯性）
        # 任一不過，不入庫；讓隔天可重試，而不是存成 Google 搜尋 placeholder。
        gl = item["link"]
        # 官方來源（official_sources.py）的 link 已是真實 URL；只有 Google News 才需解碼
        real = decode_google_news_url(gl) if "news.google.com" in gl else (gl or None)
        source_html = ""
        if real and is_rejected_url(real):       # 黑名單來源：已確認的壞資料，整筆丟棄
            print(f"    ⛔ 來源在黑名單（壞資料），丟棄：{real}")
            return None
        if real:
            ok, code, html = check_url(real, return_text=True)
            if ok:
                source_html = html
            if ok and stale_by_year(html):       # 頁面年份過舊＝舊文復活，整筆丟棄
                print(f"    ⛔ 來源頁年份過舊（舊活動復活），丟棄：{real}")
                return None
            if not ok:
                print(f"    ⚠️  來源連不過（HTTP {code}），改用搜尋連結：{real}")
                real = None
            elif not page_mentions(html, BRAND_KEYWORDS.get(brand, [])):
                print(f"    ⚠️  來源頁未提到 {brand}（關聯性不足），改用搜尋連結：{real}")
                real = None
            else:
                # 來源是該品牌頁，再驗證「活動主題」真的出現在來源——
                # 否則是 AI 把無關報導（如休業公告）誤萃取成活動，整筆丟棄。
                toks = theme_tokens(data.get("title"), data.get("summaryZh"))
                if toks and not any(t in html for t in toks):
                    print(f"    ⚠️  來源未提到活動主題 {toks}，疑似誤萃取，整筆丟棄：{real}")
                    return None
                # 補抓日期：只從「可信網域」（官方/新聞稿/場館頁）的內文補，避免一般新聞
                # 內文夾雜公告日、巡迴各城市日期 → 抓錯。寧可日期未定，也不放錯的日期。
                # 官方/新聞稿頁面常很長（PR TIMES ~75K），活動期間在內文深處 → 放大掃描範圍；
                # 這類單一活動頁的第一個日期區間即為活動期間，誤判風險低。
                if is_trusted_date_source(real):
                    apply_extracted_dates(data, html, _pub_year(item["pubDate"]),
                                          is_html=True, scan_chars=90000)
                else:
                    apply_labeled_extracted_dates(data, html, _pub_year(item["pubDate"]),
                                                  is_html=True, scan_chars=90000)
        if is_venue_less_generic_new_product(
            data,
            source_title=item.get("title", ""),
            source=item.get("source", ""),
            source_url=real or "",
            page_text=source_html,
        ):
            print("    ⛔ 泛商品新聞且無實體店/會場訊號，丟棄")
            return None
        if is_apparel_new_product(
            data,
            source_title=item.get("title", ""),
            page_text=source_html,
        ):
            print("    ⛔ 服裝/衣服類新品，不收")
            return None
        if is_unstable_source_url(real or ""):
            print("    ⛔ 找不到穩定來源 URL，不入庫（保留隔天重試）")
            return {"_skipNoProcess": True}
        data["sourceUrl"]   = real
        return data
    except RateLimitError:
        raise  # 讓主程式接住、乾淨收工
    except Exception as e:
        print(f"    ⚠️  萃取失敗：{e}")
        return None

# ── 主程式 ────────────────────────────────────────────────────────────────────

def run(brands: list[str]):
    env = load_env()
    backend = detect_ai_backend(env)
    if not backend:
        print("❌  找不到 API Key。")
        print()
        print("請在 scraper/.env 填入以下其中一個：")
        print()
        print("  ── 免費方案（推薦）──────────────────────────────")
        print("  GEMINI_API_KEY=AIzaSy...")
        print("  申請：https://aistudio.google.com  → Get API key")
        print()
        print("  ── Anthropic Claude（新帳號有 $5 免費額度）───────")
        print("  ANTHROPIC_API_KEY=sk-ant-...")
        print("  申請：https://console.anthropic.com")
        sys.exit(1)

    kind, keys = backend
    rotator = KeyRotator(kind, keys)
    name = "Claude (Anthropic)" if kind == "anthropic" else "Gemini (Google)"
    print(f"🤖  AI 後端：{name}　·　{len(keys)} 把 key{'（自動輪替）' if len(keys) > 1 else ''}")

    events = load_events()
    previous_events = json.loads(json.dumps(events, ensure_ascii=False))
    baseline_date = load_last_updated_date()

    # ── 結構化官方來源（零 Gemini）：直接解析官方排程頁產生成品情報，每次跑都用官方最新版
    #    覆蓋同來源 URL 的舊資料；過期的由後面的 clean_events 自動移除。 ──────────────
    if "chiikawa" in brands:
        try:
            structured = (
                fetch_chiikawa_popups(correct_city=correct_city)
                + fetch_chiikawa_mogumogu(correct_city=correct_city)
                + fetch_chiikawa_movie_goods(correct_city=correct_city)
                + fetch_chiikawa_movie_popups(correct_city=correct_city)
            )
            if structured:
                surls = {e["sourceUrl"] for e in structured}
                events = [e for e in events if e.get("sourceUrl") not in surls] + structured
                print(f"🏛️  吉伊卡哇官方排程/店鋪（結構化，免 AI）→ {len(structured)} 筆現行")
                save_events(events)
        except Exception as e:
            print(f"    ⚠️  吉伊卡哇結構化來源失敗（略過）：{e}")
    if "pokemon" in brands:
        try:
            cafe = fetch_pokemon_cafe_events(correct_city=correct_city)
            if cafe:
                events = replace_in_place(
                    events,
                    cafe,
                    lambda e: (
                        e.get("brand") == "pokemon"
                        and "pokemon-cafe.jp/ja/cafe/news/" in e.get("sourceUrl", "")
                    ),
                )
                print(f"🏛️  Pokémon Cafe 官方公告（結構化，免 AI）→ {len(cafe)} 筆現行")
                save_events(events)
        except Exception as e:
            print(f"    ⚠️  Pokémon Cafe 官方公告來源失敗（略過）：{e}")
        try:
            poke = fetch_pokemon_popups(correct_city=correct_city)
            if poke:
                # 出張所以官方排程為準，但保留既有排序，避免每日產生只有順序變動的 diff。
                events = replace_in_place(
                    events,
                    poke,
                    lambda e: e.get("brand") == "pokemon" and "出張所" in e.get("title", ""),
                )
                print(f"🏛️  寶可夢出張所排程（結構化，免 AI）→ {len(poke)} 筆現行")
                save_events(events)
        except Exception as e:
            print(f"    ⚠️  寶可夢結構化來源失敗（略過）：{e}")
        try:
            poke_tw = fetch_pokemon_tw_goods(correct_city=correct_city)
            if poke_tw:
                events = replace_in_place(
                    events,
                    poke_tw,
                    lambda e: (
                        e.get("brand") == "pokemon"
                        and "tw.portal-pokemon.com/goods/" in e.get("sourceUrl", "")
                    ),
                )
                print(f"🏛️  台灣寶可夢官方商品（結構化，免 AI）→ {len(poke_tw)} 筆現行")
                save_events(events)
        except Exception as e:
            print(f"    ⚠️  台灣寶可夢官方商品來源失敗（略過）：{e}")
    if "miffy" in brands:
        try:
            mf = fetch_miffy_events(extract_dates, correct_city)
            if mf:
                surls = {e["sourceUrl"] for e in mf}
                events = [e for e in events if e.get("sourceUrl") not in surls] + mf
                print(f"🏛️  Miffy 官方活動（dickbruna，結構化，免 AI）→ {len(mf)} 筆現行")
                save_events(events)
        except Exception as e:
            print(f"    ⚠️  Miffy 結構化來源失敗（略過）：{e}")

    seen_ttls = {e.get("title", "") for e in events} | {e.get("sourceTitle", "") for e in events}
    seen_urls = {e.get("sourceUrl", "") for e in events}
    processed_cache = load_processed()  # 跑過的（採用或略過）原始標題，避免重複送 AI
    global _REJECTED
    _REJECTED = load_rejected()         # 壞資料黑名單（url/title 片段），防舊壞資料復活
    new_count = 0
    rate_limited = False

    for brand in brands:
        if rate_limited:
            break
        print(f"\n🔍  {BRAND_LABELS[brand]}")
        all_items: list[dict] = []

        # 官方優先：先抓 PR TIMES 等權威來源（網域可信、日期可靠），排在最前面處理
        official = fetch_official(brand)
        if official:
            print(f"    🏛️  官方來源 PR TIMES → {len(official)} 筆")
        all_items.extend(official)

        for query, is_tw in RSS_QUERIES[brand]:
            items = fetch_rss(query, is_tw)
            print(f"    「{query[:38]}」→ {len(items)} 筆")
            all_items.extend(items)

        # 去重
        seen_run: set[str] = set()
        unique = []
        for it in all_items:
            if it["title"] not in seen_run:
                seen_run.add(it["title"])
                unique.append(it)

        # 官方優先：把 PR TIMES／官方來源排到最前面先花配額（穩定排序保留原順序）
        unique.sort(key=lambda it: 0 if is_official_source(it.get("source", "")) else 1)

        kws = BRAND_KEYWORDS[brand]
        new_for_brand = 0
        processed = 0
        for item in unique:
            if processed >= MAX_PER_BRAND:
                print(f"    （已達單品牌處理上限 {MAX_PER_BRAND} 筆，其餘下次再抓）")
                break
            tl = item["title"].lower()
            if not any(k.lower() in tl for k in kws):
                continue
            if item["title"] in seen_ttls:
                continue
            if item["title"] in processed_cache:  # 之前已送 AI 判斷過，不重複花配額
                continue
            if is_noise(item["title"]):  # 事前過濾雜訊，不浪費 API 額度
                continue
            if is_sports_noise(item["title"], item.get("description", "")):  # 體育/路跑非購物
                continue
            if is_roundup_title(item["title"]):  # 多活動彙整/懶人包：略過（活動由單一來源/官方帶入）
                continue
            if is_rejected_title(item["title"]):  # 標題在黑名單（已確認壞資料）
                continue
            age = pubdate_age_days(item["pubDate"])  # 過舊新聞跳過（多半已結束）
            if age is not None and age > MAX_NEWS_AGE_DAYS:
                continue

            processed += 1
            print(f"    → {item['title'][:55]}", end=" … ")
            try:
                ev = extract_event(rotator, brand, item)
            except RateLimitError:
                print("⛔ 配額用盡")
                print("\n⚠️  所有 key 的當日免費配額都用完，停止本次抓取（已抓到的會保留）。")
                print("    明天會自動恢復，或再加一把新的 key。")
                rate_limited = True
                break
            time.sleep(4.5)  # 節流：免費版約 15 RPM，間隔 4.5s ≈ 13 RPM

            if ev is None:
                processed_cache.add(item["title"])
                print("略過")
                continue
            if ev.get("_skipNoProcess"):
                print("略過")
                continue
            if ev["sourceUrl"] in seen_urls:
                processed_cache.add(item["title"])
                print("重複")
                continue

            events.append(ev)
            seen_ttls.add(item["title"])
            seen_urls.add(ev["sourceUrl"])
            if "google.com/search" not in ev.get("sourceUrl", ""):
                processed_cache.add(item["title"])
            new_count += 1
            new_for_brand += 1
            save_events(events)  # 即時存檔：中途中斷也不會丟失
            print(f"✅ {ev['title']}")

        if new_for_brand == 0 and not rate_limited:
            print("    本次無新情報")

    save_processed(processed_cache)
    # 收尾：移除過期 + 啟發式去重
    events, past_removed, dup_removed = clean_events(events)
    # 再用一次 AI 群組去重，補抓改寫標題的同一活動（配額用盡則自動略過）
    ai_removed = 0
    if not rate_limited:
        events, ai_removed = ai_dedup(events, rotator)
    save_events(events)
    update_diff = save_update_diff(previous_events, events, baseline_date)

    status = "中途因配額停止" if rate_limited else "完成"
    print(f"\n✨  {status}！本次新增 {new_count} 筆")
    print(f"    今日新增檢視：相對前次版本新增 {update_diff['newEventCount']} 筆")
    if past_removed or dup_removed or ai_removed:
        print(f"    清理：移除過期 {past_removed} 筆、去重 {dup_removed + ai_removed} 筆"
              f"（其中 AI 去重 {ai_removed} 筆）")
    print(f"    總計 {len(events)} 筆，寫入：{EVENTS_JSON}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", choices=list(BRAND_LABELS.keys()))
    args = parser.parse_args()
    brands = [args.brand] if args.brand else DEFAULT_BRANDS
    print(f"角色情報雷達 scraper · {TODAY}")
    print(f"品牌：{', '.join(brands)}")
    run(brands)

if __name__ == "__main__":
    main()
