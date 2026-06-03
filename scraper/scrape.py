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

import requests

from verify_links import check_url, page_mentions  # 存檔前驗證來源連結：連得過去 + 內容與品牌相關
from official_sources import fetch_official         # 官方優先：先抓 PR TIMES 等權威來源

# Windows 終端機 UTF-8 輸出 + 關閉緩衝（即時看到進度）
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

EVENTS_JSON = Path(__file__).parent.parent / "data" / "events.json"
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
    "Kyoto":    ["京都", "河原町", "嵐山", "四条"],
    "Fukuoka":  ["福岡", "博多", "天神", "キャナルシティ", "キャナル"],
    "Nagoya":   ["名古屋", "栄", "ラシック", "名駅", "大須"],
    "Nagasaki": ["長崎", "ハウステンボス", "豪斯登堡", "Huis Ten Bosch", "佐世保"],
    "Saitama":  ["埼玉", "羽生", "Hanyu", "大宮", "Omiya", "越谷", "Koshigaya",
                 "レイクタウン", "Laketown", "川越"],
    "Hokkaido": ["北海道", "札幌", "小樽", "函館"],
    "Okinawa":  ["沖縄", "沖繩", "那覇"],
    "Kanagawa": ["神奈川", "横浜", "横濱", "橫濱", "川崎", "みなとみらい", "ワールドポーターズ"],
    "Hyogo":    ["兵庫", "神戸", "神戶", "西宮", "三宮"],
    "Hiroshima":["広島", "廣島", "Hiroshima"],
    "Mie":      ["三重", "四日市"],
    "Miyagi":   ["仙台", "宮城"],
    "Chiba":    ["千葉", "舞浜", "幕張"],
    "Aomori":   ["青森", "Aomori", "弘前"],
    "Aichi":    ["愛知", "豊田"],
    "Kochi":    ["高知", "Kochi"],
    "Ishikawa": ["石川", "金沢", "金澤", "香林坊"],
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

# 預設抓取的品牌與順序
DEFAULT_BRANDS = ["miffy", "pokemon", "chiikawa", "sanrio"]

# 標題含這些字 → 在打 AI 之前就先丟掉（明顯不是「專程去逛」的目標，省 API 額度）
NOISE_KEYWORDS = [
    # 超商 / 量販 / 百元店
    "セブン", "ローソン", "ファミマ", "ファミリーマート", "ドンキ", "ドン・キホーテ",
    "驚安", "唐吉訶德", "唐企鵝", "DAISO", "ダイソー", "ダイソ", "セリア", "キャンドゥ",
    "100円", "100均", "百円", "百元", "全家", "7-11", "統一超",
    # 食品 / 飲料 / 零食
    "グミ", "ヨーグルト", "ボトル", "ドリンク", "醤油", "しょうゆ", "キャンディ",
    "チョコ", "お菓子", "リポビタン", "ポカリ", "ビール", "カステラ", "焼き", "本舗",
    "ベーカリー", "むちゃうま", "ソフビ",
    # 媒體 / 動畫 / 手遊
    "映画", "予告", "声優", "主題歌", "アプリ", "ぽけっと", "ゲーム",
    "劇場版", "預告", "聲優", "手遊", "動畫", "電影",
    # 隨機販售 / 開箱 / 夾娃娃機景品（非「去逛買」目標）
    "ガチャ", "カプセル", "扭蛋", "轉蛋", "盲盒", "開箱", "レビュー", "ガチレビュー",
    "付録", "レポ", "夾娃娃機", "ナムコ", "景品", "プライズ", "クレーンゲーム",
    "アミューズメント", "UFOキャッチャー",
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
    "pokemon.co.jp", "pokemon.com.tw", "sanrio.co.jp", "sanrio.com.tw",
    "chiikawa-info.jp", "chiikawa-market.com", "benelic.com", "kiddyland.co.jp",
    "miffykitchenbakery.jp",
    # 場館 / 百貨 / 商場 / Outlet（單一活動頁，日期通常只有該活動）
    "tokyo-skytree.jp", "sunshinecity.jp", "parco.jp", "lucua.jp", "aeonmall.com",
    "mitsui-shopping-park.com", "lalaport", "takashimaya", "isetan", "mistore",
    "hankyu", "hankyu", "daimaru", "matsuzakaya", "sogo-seibu", "lumine",
    "0101.co.jp", "marui", "tobu", "keio", "odakyu", "hep-five", "grandfront",
    "huistenbosch", "leafkyoto.net", "store.tsite.jp", "the-outlets",
]

def is_trusted_date_source(url: str) -> bool:
    u = (url or "").lower()
    if not u or "google.com/search" in u:
        return False
    return any(d in u for d in TRUSTED_DATE_DOMAINS)

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
_START_CUE = (r"\s*日?\s*[（(]?[日月火水木金土]*[)）]?\s*"
              r"(?:から|スタート|開始|より|開幕|開催|販売|発売|登場|オープン|"
              r"起|開跑|開展|開賣|起跑|～|〜|~|－|—|–|-|至|到)")

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
    sep = r"\s*日?\s*[（(]?[日月火水木金土]*[)）]?\s*[～〜~\-−–—－至到]{1,2}\s*"
    # 範圍：[年]M月D日 〜 [年]M月D日
    m = re.search(ymd + sep + ymd + r"\s*日?", text)
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

def save_events(events: list[dict]):
    EVENTS_JSON.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")

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

# 知名場館別名 → 統一代號（讓同場館不同寫法能去重）
VENUE_CANON = [
    (["ハウステンボス", "huistenbosch", "豪斯登堡", "huistenbo"], "huistenbosch"),
    (["ピューロランド", "puroland", "彩虹樂園", "三麗鷗樂園", "サンリオピューロランド"], "puroland"),
    (["スカイツリー", "晴空塔", "ソラマチ", "skytree", "そらまち"], "skytree"),
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

def _is_past(ev: dict) -> bool:
    """活動是否已結束：有結束日且已過；或有開始日、無結束日、且開始日距今超過 90 天"""
    if ev.get("endDate") and ev["endDate"] < TODAY:
        return True
    sd = ev.get("startDate")
    if sd and not ev.get("endDate"):
        age = _days_ago_iso(sd)
        if age is not None and age > 90:
            return True
    return False

def dedup_events(events: list[dict]) -> tuple[list[dict], int]:
    """合併同一活動的重複條目。回傳（清理後清單, 移除數量）"""
    kept: list[dict] = []
    title_keys: dict[str, int] = {}     # (brand, norm_title) -> kept index
    loc_keys: dict[str, int] = {}       # (brand, norm_location) -> kept index
    url_keys: dict[str, int] = {}       # 真實來源 URL -> kept index
    date_keys: dict[str, int] = {}      # (brand, city, startDate) -> kept index
    theme_keys: dict[str, int] = {}     # (brand, 日文主題詞) -> kept index
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
        lkey = (b + "|" + _norm(loc)) if loc and len(_norm(loc)) >= 3 else None
        ukey = direct_url(ev)
        city, sd = ev.get("city", ""), ev.get("startDate", "")
        dkey = (b + "|" + city + "|" + sd) if (city and sd) else None  # 同品牌同城同開始日
        thkeys = [b + "|" + t for t in theme_tokens(ev.get("title"), ev.get("summaryZh"))]

        hit = None
        if ukey and ukey in url_keys:        # 相同真實來源 = 同一活動
            hit = url_keys[ukey]
        elif tkey in title_keys:
            hit = title_keys[tkey]
        elif dkey and dkey in date_keys:     # 同品牌+同城市+同開始日 = 同一活動
            hit = date_keys[dkey]
        elif any(tk in theme_keys for tk in thkeys):  # 同品牌+相同日文主題詞 = 同一活動
            hit = theme_keys[next(tk for tk in thkeys if tk in theme_keys)]
        elif lkey and lkey in loc_keys:
            hit = loc_keys[lkey]

        if hit is not None:
            # 視為重複：保留資料較完整的那筆
            removed += 1
            if completeness(ev) > completeness(kept[hit]):
                # 用新的取代，但補上舊的非空欄位
                for f in ("startDate", "endDate", "city", "locationName"):
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
            sim = tsim(k.get("title", ""), ev.get("title", ""))
            same_venue = (canon_venue(ev.get("locationName", ""), ev.get("title", "")) is not None
                          and canon_venue(ev.get("locationName", ""), ev.get("title", ""))
                              == canon_venue(k.get("locationName", ""), k.get("title", "")))
            same_city = ev.get("city") and ev.get("city") == k.get("city")
            if (same_venue and sim >= 0.4) or (same_city and sim >= 0.50) or sim >= 0.72:
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
        # 任一不過，一律退回保證可開、且必定相關的「地點+品牌」搜尋連結。
        gl = item["link"]
        # 官方來源（official_sources.py）的 link 已是真實 URL；只有 Google News 才需解碼
        real = decode_google_news_url(gl) if "news.google.com" in gl else (gl or None)
        if real:
            ok, code, html = check_url(real, return_text=True)
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
        data["sourceUrl"]   = real if real else search_url(best_search_query(data))
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

    events    = load_events()
    seen_ttls = {e.get("title", "") for e in events} | {e.get("sourceTitle", "") for e in events}
    seen_urls = {e.get("sourceUrl", "") for e in events}
    processed_cache = load_processed()  # 跑過的（採用或略過）原始標題，避免重複送 AI
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
            age = pubdate_age_days(item["pubDate"])  # 過舊新聞跳過（多半已結束）
            if age is not None and age > MAX_NEWS_AGE_DAYS:
                continue

            processed += 1
            print(f"    → {item['title'][:55]}", end=" … ")
            try:
                ev = extract_event(rotator, brand, item)
                processed_cache.add(item["title"])  # 記錄已處理（不論結果）
            except RateLimitError:
                print("⛔ 配額用盡")
                print("\n⚠️  所有 key 的當日免費配額都用完，停止本次抓取（已抓到的會保留）。")
                print("    明天會自動恢復，或再加一把新的 key。")
                rate_limited = True
                break
            time.sleep(4.5)  # 節流：免費版約 15 RPM，間隔 4.5s ≈ 13 RPM

            if ev is None:
                print("略過")
                continue
            if ev["sourceUrl"] in seen_urls:
                print("重複")
                continue

            events.append(ev)
            seen_ttls.add(item["title"])
            seen_urls.add(ev["sourceUrl"])
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

    status = "中途因配額停止" if rate_limited else "完成"
    print(f"\n✨  {status}！本次新增 {new_count} 筆")
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
