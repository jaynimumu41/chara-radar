"""角色情報雷達 — 離線煙霧測試（安全網）

不打網路、不花 AI 額度，純測 scrape.py 的決定性函式：
  - correct_city / canon_venue（城市與場館判定）
  - stale_by_year（舊文年份過濾）
  - extract_dates（日期區間擷取）
  - _is_past（過期判定）
  - dedup_events（去重三鐵則 + 目標案例：同城同館同檔期應併、不同城/不同會場不可併）

用法：
  cd scraper
  set PYTHONIOENCODING=utf-8   (Windows)
  python smoke_test.py

每次改去重/過濾規則前後都跑一次，確保不破壞已通過的行為。
回傳 exit code 0=全過，非 0=有失敗（方便 CI / 排程串接）。
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scrape
import official_sources
import audit_chiikawa_subpages
import audit_official_coverage
import agent_verify_candidates
import source_reputation
import verify_links

_passed = 0
_failed = 0


def check(name: str, got, want):
    global _passed, _failed
    if got == want:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}\n          得到={got!r}\n          預期={want!r}")


def ev(**kw):
    """產生最小 event dict（補上 dedup 會用到的欄位預設值）。"""
    base = {"brand": "", "title": "", "type": "popup", "country": "JP",
            "city": "", "locationName": "", "startDate": "", "endDate": "",
            "summaryZh": "", "sourceUrl": "", "sourceType": "official_social"}
    base.update(kw)
    return base


# ── correct_city ──────────────────────────────────────────────────────────────
print("\n[correct_city] 城市判定")
check("豪斯登堡→Nagasaki", scrape.correct_city("豪斯登堡"), "Nagasaki")
check("夢時代→Kaohsiung", scrape.correct_city("高雄夢時代"), "Kaohsiung")
check("羽生→Saitama", scrape.correct_city("イオンモール羽生"), "Saitama")
check("KOBE PORT TOWER→Hyogo",
      scrape.correct_city("KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront"),
      "Hyogo")
check("無關鍵字→None", scrape.correct_city("某不知名地點"), None)

# ── canon_venue ───────────────────────────────────────────────────────────────
print("\n[canon_venue] 場館統一代號")
check("統一夢時代→kaohsiung-dreammall",
      scrape.canon_venue("統一夢時代", ""), "kaohsiung-dreammall")
check("ハウステンボス→huistenbosch",
      scrape.canon_venue("ハウステンボス", ""), "huistenbosch")
check("未知場館→None", scrape.canon_venue("某百貨", ""), None)

# ── stale_by_year ─────────────────────────────────────────────────────────────
print("\n[stale_by_year] 舊文年份過濾")
check("2016年→stale", scrape.stale_by_year("活動於2016年4月19日舉行"), True)
check("今年→不stale", scrape.stale_by_year("活動於2026年6月1日舉行"), False)
check("無年份→不stale", scrape.stale_by_year("活動日期未定"), False)

# ── is_roundup_title ──────────────────────────────────────────────────────────
print("\n[is_roundup_title] 彙整/懶人包過濾（不可誤殺單一活動攻略文）")
check("全台活動懶人包→彙整",
      scrape.is_roundup_title("「布丁狗30週年」全台活動時間＋地點懶人包！"), True)
check("活動總整理→彙整",
      scrape.is_roundup_title("布丁狗 30 週年慶祝活動總整理！曬黑三麗鷗主題日"), True)
check("特展攻略票價整理→不誤殺",
      scrape.is_roundup_title("2026吉伊卡哇台北特展攻略！CHIIKAWA DAYS時間、地點、票價整理"), False)
check("快閃一次看→不誤殺",
      scrape.is_roundup_title("全台只有4間！30週年「布丁狗主題店」快閃登場，限定周邊一次看"), False)
check("單一快閃新品文→不誤殺",
      scrape.is_roundup_title("三麗鷗花茶舞會快閃店插旗台中！Hello Kitty 水果裝新品開賣"), False)

# ── is_noise（藥妝/超商等非專程目標）──────────────────────────────────────────
print("\n[is_noise] 藥妝/超商過濾")
check("スギ薬局聯名→雜訊",
      scrape.is_noise("【クロミ×plus eau】スギ薬局限定で新登場！"), True)
check("マツキヨ→雜訊", scrape.is_noise("サンリオ×マツキヨ コラボグッズ"), True)
check("一番賞廣泛通路→雜訊",
      scrape.is_noise("一番くじ Pokemon 30th ANNIVERSARY vol.1"), True)
check("正當快閃→不誤殺",
      scrape.is_noise("吉伊卡哇 POP UP STORE キャナルシティオーパ"), False)
check("Pokémon GO→雜訊",
      scrape.is_noise("Pokémon GO Fest 2026：全球 心中山登場"), True)

# ── is_venue_less_generic_new_product ────────────────────────────────────────
print("\n[is_venue_less_generic_new_product] 泛商品無實體地點過濾")
check("媒體名被當地點的 Chiikawa 泛商品→擋",
      scrape.is_venue_less_generic_new_product(
          ev(brand="chiikawa", type="new_product", title="Chiikawa 新商品登場",
             locationName="千葉テレビ放送株式会社",
             summaryZh="ちいかわ雜貨新商品發售。"),
          source_title="「ちいかわ」エコバッグにビーサン、ナップザック、トート…雑貨が目白押し♪ 新商品が登場",
          source="チバテレ＋プラス - 千葉テレビ放送株式会社",
          source_url="https://www.chiba-tv.com/plus/detail/2026061740471",
          page_text="ちいかわ エコバッグ ビーサン ナップザック トート 雑貨 新商品 発売"),
      True)
check("NOWnews 明確台灣寶可夢中心店頭新品→不擋",
      scrape.is_venue_less_generic_new_product(
          ev(brand="pokemon", type="new_product", title="台灣寶可夢中心6月新品與初音未來聯名",
             locationName="台灣寶可夢中心",
             summaryZh="台灣寶可夢中心推出新品並於實體店開賣。"),
          source_title="台灣寶可夢中心6月新品與初音未來聯名 6/6開賣",
          source="NOWnews 今日新聞",
          source_url="https://www.nownews.com/news/6842060",
          page_text="Pokémon Center TAIPEI 台灣寶可夢中心 店頭 開賣 商品"),
      False)
check("可信官方商品來源→不套非官方泛商品擋法",
      scrape.is_venue_less_generic_new_product(
          ev(brand="pokemon", type="new_product", title="寶可夢新商品登場",
             locationName="", summaryZh="ポケモンセンター新商品。"),
          source_title="ポケモンセンター 新商品登場",
          source="ポケットモンスターオフィシャルサイト",
          source_url="https://www.pokemon.co.jp/goods/2026/05/260522_to01.html",
          page_text=""),
      False)
check("服裝類新品→擋",
      scrape.is_apparel_new_product(
          ev(brand="miffy", type="new_product", title="Miffy 新商品發售",
             locationName="フェリシモ（Felissimo）",
             summaryZh="日本フェリシモ將發售共19款Miffy新周邊商品。"),
          source_title="ミッフィー限定アイテムを含む新商品19点を発売開始",
          page_text="ミッフィー Tシャツ ワンピース ファッション アパレル"),
      True)
check("非服裝實體店新品→不擋",
      scrape.is_apparel_new_product(
          ev(brand="pokemon", type="new_product", title="寶可夢中心夯品再到貨",
             locationName="台灣寶可夢中心",
             summaryZh="店頭販售娃娃與周邊新品。"),
          source_title="台灣寶可夢中心 6/13 開賣",
          page_text="Pokémon Center TAIPEI 店頭 販售 娃娃 周邊"),
      False)

# ── is_trusted_date_source ────────────────────────────────────────────────────
print("\n[is_trusted_date_source] 可信日期網域（hostname 精準比對）")
check("PR TIMES→可信",
      scrape.is_trusted_date_source("https://www.prtimes.jp/main/html/rd/p/000000001.html"), True)
check("晴空塔子網域→可信",
      scrape.is_trusted_date_source("https://event.tokyo-skytree.jp/news/abc"), True)
check("Kiddy Land→可信",
      scrape.is_trusted_date_source("https://www.kiddyland.co.jp/event/miffystyle_birthday2026/"), True)
check("Dick Bruna 官方→可信",
      scrape.is_trusted_date_source("https://dickbruna.jp/news/202605/46308/"), True)
check("Miffy KOBE 官方標題場館抽取",
      official_sources._miffy_venue_from_title(
          "「KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront」～Night Time～開催",
          "KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront",
      ),
      "KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront")
check("Miffy KOBE 官方標題顯示名",
      official_sources._miffy_display_name(
          "「KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront」～Night Time～開催",
          "KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront",
      ),
      "神戶港塔 Night Time 聯名活動")
check("Collabo Cafe→可信",
      scrape.is_trusted_date_source("https://collabo-cafe.com/events/collabo/chiikawa-obakenomori-odaiba2026/"), True)
check("台灣寶可夢官方→可信",
      scrape.is_trusted_date_source("https://tw.portal-pokemon.com/goods/post-5343/"), True)
check("Pokémon Cafe 官方→可信",
      scrape.is_trusted_date_source("https://www.pokemon-cafe.jp/ja/cafe/news/260529_3377.html"), True)
check("寶可夢出張所結構化排程→可信",
      scrape.is_trusted_date_source("https://oneheart65.net/pokemoncenterbranch_schedule_2/"), True)
check("吉伊卡哇もぐもぐ本舗→可信",
      scrape.is_trusted_date_source("https://www.chiikawamogumogu.jp/stores/castella/"), True)
check("網址參數提到 prtimes.jp→不誤信",
      scrape.is_trusted_date_source("https://example.com/read?src=prtimes.jp"), False)
check("Google 搜尋 placeholder→不穩定來源",
      scrape.is_unstable_source_url("https://www.google.com/search?q=Pokemon+Center+Kagawa"), True)
check("Google News placeholder→不穩定來源",
      scrape.is_unstable_source_url("https://news.google.com/rss/articles/ABC"), True)
check("NOWnews 真實 URL→穩定來源",
      scrape.is_unstable_source_url("https://www.nownews.com/news/6842060"), False)
check("last_updated 含 BOM 仍可讀日期",
      scrape.parse_last_updated_date('\ufeff{ "updatedAt": "2026-06-22T16:04:27+08:00" }'),
      "2026-06-22")
flower_event = ev(
    brand="miffy",
    title="フラワーミッフィー限定活動",
    locationName="フラワーミッフィー 浅草店",
    summaryZh="フラワーミッフィー店舖限定商品",
    tags=["フラワーミッフィー", "淺草店"],
)
scrape.normalize_display_terms(flower_event)
check("Miffy フラワーミッフィー公開顯示→Flower Miffy",
      (flower_event["title"], flower_event["locationName"], flower_event["summaryZh"], flower_event["tags"]),
      ("Flower Miffy限定活動", "Flower Miffy 浅草店", "Flower Miffy店舖限定商品", ["Flower Miffy", "淺草店"]))
check("連結驗證網路 URL 去掉 fragment",
      verify_links._network_url("https://chiikawa-info.jp/p26/mck_scpus/index.html#abc123"),
      "https://chiikawa-info.jp/p26/mck_scpus/index.html")
check("Chiikawa p26 連結驗證優先走 reader proxy",
      verify_links._prefer_reader_proxy("https://chiikawa-info.jp/p26/mck_scpus/index.html"),
      True)
sample_chiikawa_home = """
<a href="/p26/foo/index.html">Foo <span>Store</span></a>
<a href="https://chiikawa-info.jp/p26/bar/">Bar</a>
[Movie](https://chiikawa-info.jp/p26/mck_scpus/index.html#abc123)
<a href="https://example.com/p26/nope/index.html">Nope</a>
"""
chiikawa_links = audit_chiikawa_subpages.extract_p26_links(sample_chiikawa_home)
check("吉伊卡哇首頁 p26 子頁連結正規化",
      [(l.url, l.title) for l in chiikawa_links],
      [
          ("https://chiikawa-info.jp/p26/bar/index.html", "Bar"),
          ("https://chiikawa-info.jp/p26/foo/index.html", "Foo Store"),
          ("https://chiikawa-info.jp/p26/mck_scpus/index.html", "Movie"),
      ])
audit_rows = audit_chiikawa_subpages.audit_links(
    chiikawa_links,
    parsed_pages={"https://chiikawa-info.jp/p26/foo/index.html": ["ch-test"]},
    ignored_pages={"https://chiikawa-info.jp/p26/bar/index.html": "test ignore"},
    details_by_url={
        "https://chiikawa-info.jp/p26/mck_scpus/index.html":
            "映画ちいかわ POP UP STORE 会場 イオンモール "
            "2026年7月10日(金)～7月20日(月祝) 限定グッズ",
    },
)
check("吉伊卡哇首頁 p26 子頁稽核分類",
      [(r.url.rsplit("/p26/", 1)[1], r.status, r.risk, r.event_ids) for r in audit_rows],
      [
          ("bar/index.html", "ignored", "-", ()),
          ("foo/index.html", "parsed", "-", ("ch-test",)),
          ("mck_scpus/index.html", "needs_review", "high", ()),
      ])
check("吉伊卡哇首頁 p26 子頁高風險訊號",
      audit_rows[2].signals.labels,
      ["date", "date_range", "collectible", "venue"])

sample_official_links = """
<a href="/ja/cafe/news/260529_3377.html">ポケモンカフェ TOKYO は店内がリニューアル</a>
<a href="https://www.kiddyland.co.jp/event/miffy_20260606/">miffy style先行発売</a>
<a href="https://example.com/event/miffy/">Nope</a>
"""
official_links = audit_official_coverage.extract_links(
    sample_official_links, "https://www.pokemon-cafe.jp/ja/cafe/news/")
check("官方覆蓋稽核 URL 正規化",
      official_links,
      [
          ("https://www.pokemon-cafe.jp/ja/cafe/news/260529_3377.html",
           "ポケモンカフェ TOKYO は店内がリニューアル"),
          ("https://www.kiddyland.co.jp/event/miffy_20260606/", "miffy style先行発売"),
      ])
official_candidates = [
    audit_official_coverage.OfficialCandidate(
        "pokemon", "pokemon-cafe-news",
        "https://www.pokemon-cafe.jp/ja/cafe/news/260529_3377.html",
        "ポケモンカフェ TOKYO は店内がリニューアル"),
    audit_official_coverage.OfficialCandidate(
        "miffy", "miffy-kiddyland-search",
        "https://www.kiddyland.co.jp/event/miffy_20260606/",
        "2026年6月6日(土)より開催miffy’s Birthday Fair2026"),
    audit_official_coverage.OfficialCandidate(
        "pokemon", "pokemon-store-events",
        "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-kagawa/events/202606/000001.html",
        "6月28日（日）、ヒトカゲとピカチュウに会えるグリーティング"),
    audit_official_coverage.OfficialCandidate(
        "miffy", "miffy-dickbruna-news",
        "https://dickbruna.jp/news/202606/46926/",
        "ミッフィー LINE公式アカウントがオープン"),
    audit_official_coverage.OfficialCandidate(
        "miffy", "miffy-dickbruna-news",
        "https://dickbruna.jp/news/202606/46921/",
        "ユニクロよりディック・ブルーナPEACE FOR ALL Tシャツ発売"),
]
official_audit_rows = audit_official_coverage.audit_candidates(
    official_candidates,
    parsed_pages={"https://www.pokemon-cafe.jp/ja/cafe/news/260529_3377.html": ["po-test"]},
    details_by_url={
        "https://www.kiddyland.co.jp/event/miffy_20260606/":
            "2026年6月6日(土)より開催 miffy style 店舗限定グッズ 発売 フェア",
        "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-kagawa/events/202606/000001.html":
            "6月28日（日）、ヒトカゲとピカチュウに会えるグリーティング",
    },
)
check("官方覆蓋稽核 parsed / needs_review / ignored",
      [(r.status, r.risk, r.event_ids) for r in official_audit_rows],
      [
          ("parsed", "-", ("po-test",)),
          ("needs_review", "high", ()),
          ("ignored", "-", ()),
          ("ignored", "-", ()),
          ("ignored", "-", ()),
      ])
kiddy_birthday_title = "2026年6月6日(土)より開催miffy’s Birthday Fair2026"
kiddy_birthday_page = (
    f"<h1>{kiddy_birthday_title}</h1>"
    "<p>期間 2026年6月6日（土）～6月30日（火）</p>"
    "<p>miffy style 店舗限定グッズとノベルティ。</p>"
    "<h2>最新の記事</h2><p>2026年6月27日（土）～7月7日（火）別記事</p>"
)
kiddy_main = official_sources._main_article_text(kiddy_birthday_page, kiddy_birthday_title)
check("Kiddy Land 本文切片排除最新記事日期污染",
      ("6月30日" in kiddy_main, "7月7日" in kiddy_main),
      (True, False))
check("Kiddy Land Birthday Fair 期間解析",
      official_sources._kiddy_period(kiddy_birthday_title, kiddy_main, scrape.extract_dates),
      ("2026-06-06", "2026-06-30"))
check("Kiddy Land ノベルティデイ ～スタート 不補同日結束",
      official_sources._kiddy_period(
          "2026年7月4日(土)～スタート!miffy style 各店ノベルティデイ",
          "※なくなり次第終了となりますのでご了承くださいませ。",
          scrape.extract_dates,
      ),
      ("2026-07-04", ""))
check("Kiddy Land 東京駅店 location",
      official_sources._kiddy_location("2026年7月4日(土)発売予定!miffy style東京駅店限定 駅長さんミッフィー"),
      ("miffy style 東京駅店", "Tokyo"))
same_day_kiddy = official_sources._drop_same_day_kiddy_product_details([
    ev(brand="miffy", type="campaign", title="Miffy miffy style 各店ノベルティデイ",
       startDate="2026-07-04", locationName="miffy style 各店＋キデイランド対象店",
       sourceUrl="https://www.kiddyland.co.jp/event/miffy_nove202607/"),
    ev(brand="miffy", type="new_product", title="Miffy miffy style東京駅店限定 駅長さんミッフィー",
       startDate="2026-07-04", locationName="miffy style 東京駅店",
       sourceUrl="https://www.kiddyland.co.jp/event/miffy_tokyo20260704/"),
    ev(brand="miffy", type="new_product", title="Miffy miffy style大阪梅田店限定商品",
       startDate="2026-07-11", locationName="miffy style 大阪梅田店",
       sourceUrl="https://www.kiddyland.co.jp/event/miffy_osaka20260711/"),
])
check("Kiddy Land同日活動已有campaign→單品頁不另列",
      [e["sourceUrl"] for e in same_day_kiddy],
      [
          "https://www.kiddyland.co.jp/event/miffy_nove202607/",
          "https://www.kiddyland.co.jp/event/miffy_osaka20260711/",
      ])

sample_otaru_info = (
    "### [ちいかわベビーカステラ](https://www.chiikawamogumogu.jp/stores/castella/) "
    "2026年7月18日(土)～ ちいかわもぐもぐ本舗 小樽店にオープン！"
)
sample_otaru_shop = (
    "ちいかわベビーカステラは店内で焼き上げたふわふわベビーカステラや"
    "ここだけのオリジナルグッズが楽しめるテイクアウトショップです。"
    "現在、ご入店には事前予約が必要となります。住所：北海道小樽市堺町6-1"
)
otaru = official_sources._chiikawa_otaru_castella_event(
    sample_otaru_info, sample_otaru_shop, correct_city=scrape.correct_city)
check("吉伊卡哇小樽ベビーカステラ店鋪情報解析",
      (otaru["type"], otaru["city"], otaru["startDate"], otaru["endDate"],
       otaru["needReservation"], otaru["hasLimitedGoods"], otaru["sourceUrl"]),
      ("store", "Hokkaido", "2026-07-18", "", True, True,
       "https://www.chiikawamogumogu.jp/stores/castella/"))
sample_movie_popup = (
    "[イオンモール新潟亀田インター 1F スカイコート](https://www.aeon.jp/sc/niigatakameda-inter/) "
    "2026年7月10日(金)～7月20日(月祝) "
    "華山1914文創園區 藝術西街 2026年7月10日(金)～8月30日(日) "
    "[イオンモールKYOTO Sakura館1階 センターコート](https://kyoto.aeonmall.com/) "
    "2026年8月21日(金)～9月6日(日)"
)
movie_events = official_sources._chiikawa_movie_popup_events_from_text(
    sample_movie_popup, correct_city=scrape.correct_city)
check("電影吉伊卡哇 POP UP 多會場解析數量",
      len(movie_events), 3)
check("電影吉伊卡哇 POP UP 解析城市與國家",
      [(e["city"], e["country"], e["startDate"], e["endDate"]) for e in movie_events],
      [("Niigata", "JP", "2026-07-10", "2026-07-20"),
       ("Kyoto", "JP", "2026-08-21", "2026-09-06"),
       ("Taipei", "TW", "2026-07-10", "2026-08-30")])
check("電影吉伊卡哇 POP UP 每場 sourceUrl 不共用",
      len({e["sourceUrl"] for e in movie_events}), 3)
sample_movie_goods = (
    "映画ちいかわ POPUP in TOHOシネマズ "
    "＜2026年7月10日(金)～8月31日(月)＞ "
    "TOHOシネマズ南大沢 TOHOシネマズ仙台 "
    "フジテレビ グッズ取扱い店舗 "
    "＜2026年7月25日(土)～8月23日(日)＞ "
    "お台場ファンライジング ちいかわお台場商店 22階店 "
    "お台場ファンライジング ちいかわお台場商店 1階フジテレビ モール店"
)
movie_goods = official_sources._chiikawa_movie_goods_events_from_text(
    sample_movie_goods, correct_city=scrape.correct_city)
check("電影吉伊卡哇グッズ取扱店 高信心區塊解析數量",
      len(movie_goods), 2)
check("電影吉伊卡哇グッズ取扱店 解析類型城市日期",
      [(e["type"], e["city"], e["startDate"], e["endDate"]) for e in movie_goods],
      [("new_product", "", "2026-07-10", "2026-08-31"),
       ("new_product", "Tokyo", "2026-07-25", "2026-08-23")])
check("電影吉伊卡哇グッズ取扱店 sourceUrl 不共用",
      len({e["sourceUrl"] for e in movie_goods}), 2)

# ── agent_verify_candidates ─────────────────────────────────────────────────
print("\n[agent_verify_candidates] 每日驗證候選")
check("結構化官方活動缺 endDate→仍進候選",
      "structured_activity_missing_endDate" in agent_verify_candidates.verification_reasons(
          ev(type="campaign", sourceType="official_site",
             sourceUrl="https://www.kiddyland.co.jp/event/miffystyle_birthday2026/",
             startDate="2026-06-06", endDate="")),
      True)
check("結構化官方活動日期完整→略過",
      agent_verify_candidates.verification_reasons(
          ev(type="campaign", sourceType="official_site",
             sourceUrl="https://www.kiddyland.co.jp/event/miffystyle_birthday2026/",
             startDate="2026-06-06", endDate="2026-06-30")),
      [])
check("oneheart65 出張所日期完整→略過",
      agent_verify_candidates.verification_reasons(
          ev(brand="pokemon", type="popup", sourceType="official_social",
             sourceUrl="https://oneheart65.net/pokemoncenterbranch_schedule_2/",
             startDate="2026-06-05", endDate="2026-07-22")),
      [])
check("吉伊卡哇もぐもぐ本舗常設店無 endDate→略過",
      agent_verify_candidates.verification_reasons(
          ev(brand="chiikawa", type="store", sourceType="official_site",
             sourceUrl="https://www.chiikawamogumogu.jp/stores/castella/",
             startDate="2026-07-18", endDate="")),
      [])

# ── source_reputation ────────────────────────────────────────────────────────
print("\n[source_reputation] source trust memory")
check("NOWnews domain identity",
      source_reputation.source_identity("https://www.nownews.com/news/6811629")["id"],
      "domain:nownews.com")
check("Instagram handle identity",
      source_reputation.source_identity("https://www.instagram.com/pokemon_taiwan/p/ABC123/")["id"],
      "instagram:pokemon_taiwan")
check("Instagram post URL can use title handle",
      source_reputation.source_identity("https://www.instagram.com/p/ABC123/", "@pokemon_taiwan announcement")["id"],
      "instagram:pokemon_taiwan")
check("Threads handle identity",
      source_reputation.source_identity("https://www.threads.net/@kawaii_news/post/ABC123")["id"],
      "threads:kawaii_news")
rep_data = source_reputation.new_reputation_data()
for idx in range(3):
    source_reputation.record_outcome(
        rep_data,
        url="https://example-verification.invalid/post",
        outcome="confirmed",
        brand="pokemon",
        event_type="new_product",
        country="TW",
        event_id=f"po-test-{idx}",
        evidence_count=2,
    )
rep_summary = source_reputation.summarize_source(rep_data, ev(
    brand="pokemon", type="new_product", country="TW",
    sourceUrl="https://example-verification.invalid/post"))
check("Repeated confirmations promote source", rep_summary["tier"], "trusted")
placeholder_summary = source_reputation.summarize_source(
    rep_data, ev(sourceUrl="https://www.google.com/search?q=Pokemon+Center"))
placeholder_policy = source_reputation.evidence_policy(
    placeholder_summary, trusted_date_source=False, structured_source=False)
check("Google placeholder must be replaced", placeholder_policy["label"], "find stable source")
candidates = agent_verify_candidates.build_candidates([
    ev(brand="pokemon", type="new_product", country="TW",
       sourceUrl="https://untracked-source.invalid/post",
       startDate="2026-06-13", endDate="",
       locationName="Pokemon Center TAIPEI")
])
check("Candidate includes evidence requirement", candidates[0]["minIndependentSources"], 2)

# ── extract_dates ─────────────────────────────────────────────────────────────
print("\n[extract_dates] 日期區間擷取")
check("日文範圍含年", scrape.extract_dates("2026年5月27日（水）〜6月14日（日）", is_html=False),
      ("2026-05-27", "2026-06-14"))
check("中文至/到（只結束日）",
      scrape.extract_dates("即日起至6月8日", ref_year=2026, is_html=False),
      ("", "2026-06-08"))
check("日文から/まで範圍",
      scrape.extract_dates("2026年7月11日（土）から 7月28日（火）まで、松坂屋静岡店にて開催", ref_year=2026, is_html=False),
      ("2026-07-11", "2026-07-28"))
check("中文星期括號活動期間",
      scrape.extract_dates("【百變怪抱枕獲得方式】活動期間：6/16（二）-7/27（一）", ref_year=2026, is_html=False),
      ("2026-06-16", "2026-07-27"))
label_event = ev(startDate="2026-06-16", endDate="")
label_changed = scrape.apply_labeled_extracted_dates(
    label_event,
    "【寶可夢卡牌特典卡包獲得方式】活動期間：6/16（二）-7/27（一）",
    ref_year=2026,
    is_html=False,
)
check("非可信來源明確活動期間可補 endDate", (label_changed, label_event["endDate"]),
      (True, "2026-07-27"))
mismatch_event = ev(startDate="2026-06-17", endDate="")
mismatch_changed = scrape.apply_labeled_extracted_dates(
    mismatch_event,
    "活動期間：6/16（二）-7/27（一）",
    ref_year=2026,
    is_html=False,
)
check("活動期間起日不符時不可硬補", (mismatch_changed, mismatch_event["endDate"]),
      (False, ""))
check("台灣寶可夢官方商品店頭發售日",
      official_sources._tw_store_sale_date("即將於3月14日(六)在Pokémon Center TAIPEI登場！", "2026-02-27"),
      "2026-03-14")
tw_popup = official_sources._tw_partner_popup_event(
    {
        "title": "≪K.UNO × U-TREASURE POP UP Promotion≫開展！",
        "url": "https://tw.portal-pokemon.com/goods/post-5267/",
    },
    "≪K.UNO × U-TREASURE POP UP Promotion≫ ＜活動期間＞2026年2月1日(日)～2026年12月31日(四) "
    "＜活動店鋪＞ ・K.UNO台北忠孝旗艦店 ・K.UNO新光三越南西店 ・K.UNO新光三越台南新天地西門店",
    correct_city=scrape.correct_city,
)
check("台灣寶可夢官方 K.UNO POP UP 解析",
      (tw_popup["id"], tw_popup["type"], tw_popup["country"], tw_popup["startDate"],
       tw_popup["endDate"], tw_popup["hasLimitedGoods"], tw_popup["sourceUrl"]),
      ("po-e4c3bc", "popup", "TW", "2026-02-01", "2026-12-31", True,
       "https://tw.portal-pokemon.com/goods/post-5267/"))
sample_tw_next = (
    r'\"item\":{\"postId\":5937,\"slug\":\"post-5937\",\"region\":\"TAIWAN\",'
    r'\"model\":\"GOODS\",\"title\":\"克萊希寶可夢系列2026・全新上市\",'
    r'\"startDateTime\":\"2026-06-05T04:00:00.000Z\",'
    r'\"category\":{\"categoryName\":\"衣服、飾品類\"}}'
)
check("台灣寶可夢官方 Next.js 商品列表解析",
      official_sources._tw_goods_entries_from_next_html(sample_tw_next),
      [{
          "url": "https://tw.portal-pokemon.com/goods/post-5937/",
          "title": "克萊希寶可夢系列2026・全新上市",
          "category": "衣服、飾品類",
          "published": "2026-06-05",
      }])
pokemon_cafe = official_sources._pokemon_cafe_tokyo_renewal_event_from_text(
    "2026.05.29 ポケモンカフェのメニューやショーが新しくなるよ！"
    "「ポケモンカフェ TOKYO」は、店内がリニューアル！ "
    "6月17日（水）、ポケモンカフェのメニューやショーが新しくなるよ！",
    "https://www.pokemon-cafe.jp/ja/cafe/news/260529_3377.html",
    correct_city=scrape.correct_city,
)
check("Pokémon Cafe TOKYO 日本橋翻新公告解析",
      (pokemon_cafe["id"], pokemon_cafe["type"], pokemon_cafe["city"],
       pokemon_cafe["startDate"], pokemon_cafe["endDate"], pokemon_cafe["needReservation"]),
      ("po-d0b8f9", "store", "Tokyo", "2026-06-17", "", True))

# ── _is_past ──────────────────────────────────────────────────────────────────
print("\n[_is_past] 過期判定（含無結束日補洞）")
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
def _iso_ago(days):  # 產生 N 天前的 ISO 日期
    return (_dt.now(_tz.utc) - _td(days=days)).strftime("%Y-%m-%d")
check("結束日已過→past", scrape._is_past(ev(endDate="2000-01-01")), True)
check("結束日未到→不past", scrape._is_past(ev(endDate=_iso_ago(-30))), False)
check("活動型無結束日+起始40天前→past",
      scrape._is_past(ev(type="popup", startDate=_iso_ago(40))), True)
check("活動型無結束日+起始10天前→不past",
      scrape._is_past(ev(type="popup", startDate=_iso_ago(10))), False)
check("活動型完全無日期→past（無法確認現行）",
      scrape._is_past(ev(type="cafe")), True)
check("商品型完全無日期→past",
      scrape._is_past(ev(type="new_product")), True)
check("商品型起始40天前→不past（<60）",
      scrape._is_past(ev(type="new_product", startDate=_iso_ago(40))), False)
check("商品型起始70天前→past（>60）",
      scrape._is_past(ev(type="new_product", startDate=_iso_ago(70))), True)
check("未來活動→不past",
      scrape._is_past(ev(type="popup", startDate=_iso_ago(-15))), False)
check("常設store無日期→不past",
      scrape._is_past(ev(type="store")), False)

# ── dedup_events ──────────────────────────────────────────────────────────────
print("\n[dedup_events] 去重")

# 鐵則1：同來源 URL 但不同城市（巡迴排程頁）= 不同活動，不可併
url = "https://oneheart65.net/pokemoncenterbranch_schedule_2/"
out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="Pokemon Center 出張所 in イオンモール羽生", city="Saitama",
       startDate="2026-06-19", endDate="2026-08-22",
       locationName="イオンモール羽生", sourceUrl=url),
    ev(brand="pokemon", title="Pokemon Center 出張所 in イオンモール今治新都市", city="Ehime",
       startDate="2026-06-12", endDate="2026-08-31",
       locationName="イオンモール今治新都市", sourceUrl=url),
])
check("不同城市同URL→不併（2筆）", len(out), 2)

# 鐵則2：同城同館、一邊 dateless = 同活動的較不完整版本，應併
out, _ = scrape.dedup_events([
    ev(brand="chiikawa", title="吉伊卡哇 POP UP STORE キャナルシティオーパ", city="Fukuoka",
       startDate="2026-05-16", endDate="2026-06-28",
       locationName="キャナルシティオーパ センターウォークB1F"),
    ev(brand="chiikawa", title="吉伊卡哇快閃 キャナルシティ", city="Fukuoka",
       locationName="キャナルシティオーパ"),
])
check("同城同館dateless→併（1筆）", len(out), 1)

# 目標案例（建議1）：同城＋同活動的多家媒體報導，靠 場館相似＋日期區間一致 應併成1
out, _ = scrape.dedup_events([
    ev(brand="sanrio", title="三麗鷗遊樂園快閃 高雄登場", city="Kaohsiung",
       startDate="2026-05-29", endDate="2026-06-30", locationName="高雄夢時代",
       sourceUrl="https://a.example/1"),
    ev(brand="sanrio", title="三麗鷗遊樂園主題店快閃高雄 近40款新品", city="Kaohsiung",
       startDate="2026-05-29", endDate="2026-06-30", locationName="統一夢時代",
       sourceUrl="https://b.example/2"),
    ev(brand="sanrio", title="三麗鷗高雄夢時代限定店 酷洛米大耳狗", city="Kaohsiung",
       startDate="2026-05-29", endDate="2026-06-30", locationName="夢時代",
       sourceUrl="https://c.example/3"),
])
check("同城同活動3媒體→併（1筆）", len(out), 1)

# 一筆官方資料 city 空白、locationName 含活動標題時，仍應和同場館同檔期的 PR TIMES 合併
out, _ = scrape.dedup_events([
    ev(brand="miffy", title="Miffy 神戶港塔聯名主題咖啡廳", type="cafe", city="Hyogo",
       startDate="2026-07-30", endDate="2026-09-30",
       locationName="KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront",
       sourceType="official_social", sourceUrl="https://prtimes.jp/example"),
    ev(brand="miffy",
       title="Miffy KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront　「KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront」～Night Time～開催",
       type="cafe", city="", startDate="2026-07-30", endDate="2026-09-30",
       locationName="「KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront」～Night Time～開催",
       sourceType="official_site", sourceUrl="https://dickbruna.jp/news/202606/46792/"),
])
check("同場館同完整區間 city 缺漏→併（1筆）", len(out), 1)

out, _ = scrape.dedup_events([
    ev(brand="miffy", title="Miffy生日與Flower Miffy淺草店7週年慶活動", type="campaign", city="Tokyo",
       startDate="2026-06-19", locationName="Flower Miffy 浅草店",
       summaryZh="為慶祝Miffy生日與淺草店7週年，將於6月19日起舉辦限定活動。",
       sourceType="official_social", sourceUrl="https://prtimes.jp/main/html/rd/p/000002086.000022901.html"),
    ev(brand="miffy", title="Miffy Flower Miffy バースデーキャンペーン", type="campaign", city="",
       startDate="2026-06-19",
       locationName="全国のフラワーミッフィー、フラワーミッフィーオンラインショップ",
       summaryZh="為慶祝 Miffy 生日與 Flower Miffy 浅草店 7 週年，Flower Miffy 全門市與線上商店推出生日活動。",
       sourceType="official_site", sourceUrl="https://dickbruna.jp/news/202606/46872/"),
])
check("Flower Miffy生日活動官方替換→併且保留全店官方頁",
      (len(out), out[0]["sourceType"], out[0].get("city", "")),
      (1, "official_site", ""))
check("更新差異：同來源不同城市仍是不同情報",
      scrape.is_same_event_for_update_diff(
          ev(brand="pokemon", title="Pokemon Center 出張所 in A", type="popup", city="Hyogo",
             startDate="2026-06-05", endDate="2026-07-22",
             locationName="イオンモール神戸北", sourceUrl="https://oneheart65.net/pokemoncenterbranch_schedule_2/"),
          ev(brand="pokemon", title="Pokemon Center 出張所 in B", type="popup", city="Ehime",
             startDate="2026-06-12", endDate="2026-08-31",
             locationName="イオンモール今治新都市", sourceUrl="https://oneheart65.net/pokemoncenterbranch_schedule_2/"),
      ),
      False)
kobe_diff = scrape.build_update_diff(
    [ev(id="old-kobe", brand="miffy", title="Miffy 神戶港塔聯名主題咖啡廳", type="cafe", city="Hyogo",
        startDate="2026-07-30", endDate="2026-09-30",
        locationName="KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront")],
    [
        ev(id="new-kobe", brand="miffy", title="Miffy 神戶港塔 Night Time 聯名活動", type="cafe", city="Hyogo",
           startDate="2026-07-30", endDate="2026-09-30",
           locationName="KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront"),
        ev(id="new-real", brand="miffy", title="Miffy 新活動", type="campaign", city="Tokyo",
           startDate="2026-08-01", endDate="2026-08-10", locationName="Flower Miffy"),
    ],
    date="2026-06-17",
    baseline_date="2026-06-16",
)
check("更新差異：同活動來源替換不算今日新增",
      (kobe_diff["newEventIds"], kobe_diff["countsByBrand"]["miffy"], kobe_diff["replacements"]),
      (["new-real"], 1, [{"from": "old-kobe", "to": "new-kobe"}]))
flower_diff = scrape.build_update_diff(
    [ev(id="old-flower", brand="miffy", title="Miffy生日與Flower Miffy淺草店7週年慶活動",
        type="campaign", city="Tokyo", startDate="2026-06-19",
        locationName="Flower Miffy 浅草店",
        summaryZh="為慶祝Miffy生日與淺草店7週年，將於6月19日起舉辦限定活動。")],
    [ev(id="new-flower", brand="miffy", title="Miffy Flower Miffy バースデーキャンペーン",
        type="campaign", city="", startDate="2026-06-19",
        locationName="全国のフラワーミッフィー、フラワーミッフィーオンラインショップ",
        summaryZh="為慶祝 Miffy 生日與 Flower Miffy 浅草店 7 週年，Flower Miffy 全門市與線上商店推出生日活動。")],
    date="2026-06-18",
    baseline_date="2026-06-17",
)
check("更新差異：Flower Miffy官方頁替換不算今日新增",
      (flower_diff["newEventIds"], flower_diff["countsByBrand"]["miffy"], flower_diff["replacements"]),
      ([], 0, [{"from": "old-flower", "to": "new-flower"}]))

# 反例（建議1 不可誤殺）：同城同場館但「不同檔期」(日期區間差很多) = 不同活動，不可併
out, _ = scrape.dedup_events([
    ev(brand="chiikawa", title="吉伊卡哇 POP UP STORE 某百貨", city="Osaka",
       startDate="2026-05-01", endDate="2026-05-20", locationName="某百貨 5階",
       sourceUrl="https://a.example/x"),
    ev(brand="chiikawa", title="吉伊卡哇 POP UP STORE 某百貨", city="Osaka",
       startDate="2026-08-01", endDate="2026-08-20", locationName="某百貨 5階",
       sourceUrl="https://b.example/y"),
])
check("同館不同檔期→不併（2筆）", len(out), 2)

# 連鎖/各店販售點不能只靠 locationName 去重：同一家寶可夢中心可能連續推出不同新品
out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="Pokémon accessory 系列新品發售", type="new_product",
       startDate="2026-05-16", locationName="ポケモンセンター各店",
       sourceUrl="https://www.famitsu.com/article/202605/74739"),
    ev(brand="pokemon", title="寶可夢「もぐもぐウォッチング！」新商品", type="new_product",
       startDate="2026-05-30", locationName="ポケモンセンター各店",
       sourceUrl="https://www.pokemon.co.jp/goods/2026/05/260522_to01.html"),
])
check("泛用各店地點不同新品→不併（2筆）", len(out), 2)

# 同城同開始日對活動型可輔助去重，但不能套到新品：同一天可能有多個不同系列開賣
out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="台北寶可夢中心 Pikachu's Sweet Delivery", type="new_product",
       city="Taipei", startDate="2026-05-16", locationName="台北寶可夢中心",
       sourceUrl="https://a.example/pikachu"),
    ev(brand="pokemon", title="台北寶可夢中心 婚禮皮卡丘新品", type="new_product",
       city="Taipei", startDate="2026-05-16", locationName="台北寶可夢中心",
       sourceUrl="https://b.example/wedding"),
])
check("同城同日不同新品→不併（2筆）", len(out), 2)

# 同城同泛用店名、日期不同的新品也不可被第二階段模糊去重併掉。
out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="台北寶可夢中心 母親節新品", type="new_product",
       city="Taipei", startDate="2026-05-09", locationName="台北寶可夢中心",
       sourceUrl="https://a.example/mothers-day"),
    ev(brand="pokemon", title="台北寶可夢中心 城都地區新品", type="new_product",
       city="Taipei", startDate="2026-05-23", locationName="台北寶可夢中心",
       sourceUrl="https://b.example/johto"),
])
check("同城泛用店名不同日期新品→不併（2筆）", len(out), 2)

flower_birthday = ev(
    brand="miffy", title="Miffy Flower Miffy バースデーキャンペーン",
    type="campaign", startDate="2026-06-19",
    locationName="全国のフラワーミッフィー、フラワーミッフィーオンラインショップ",
)
kiddy_birthday = ev(
    brand="miffy", title="Miffy miffy’s Birthday 2026",
    type="campaign", startDate="2026-06-06", endDate="2026-06-30",
    locationName="miffy style 各店＋キデイランド対象店",
)
flower_pr = ev(
    brand="miffy", title="Miffy生日與Flower Miffy淺草店7週年慶活動",
    type="campaign", city="Tokyo", startDate="2026-06-19",
    locationName="Flower Miffy 浅草店",
)
check("AI去重防呆：不同店系生日活動不可併",
      scrape._ai_dedup_locations_compatible([flower_birthday, kiddy_birthday]),
      False)
check("AI去重防呆：同Flower Miffy活動可併",
      scrape._ai_dedup_locations_compatible([flower_pr, flower_birthday]),
      True)

# 不破壞現況：實際線上 events.json 不應被誤併（筆數不變）
try:
    real = scrape.load_events()
    deduped, removed = scrape.dedup_events([dict(e) for e in real])
    check(f"線上 events.json 去重無誤併（{len(real)}筆）", len(deduped), len(real))
except Exception as e:
    print(f"  SKIP  線上 events.json 測試（讀取失敗：{e}）")

# ── replace_in_place ──────────────────────────────────────────────────────────
print("\n[replace_in_place] 結構化來源原地更新")
old = [
    ev(id="keep", brand="miffy", title="既有資料"),
    ev(id="po-1", brand="pokemon", title="Pokemon Center 出張所 in A", endDate="2026-06-30"),
    ev(id="stale", brand="pokemon", title="Pokemon Center 出張所 in OLD"),
    ev(id="other", brand="pokemon", title="Pokémon 常設新品"),
]
fresh = [
    ev(id="po-1", brand="pokemon", title="Pokemon Center 出張所 in A", endDate="2026-07-31"),
    ev(id="po-2", brand="pokemon", title="Pokemon Center 出張所 in B"),
]
out = scrape.replace_in_place(
    old,
    fresh,
    lambda e: e.get("brand") == "pokemon" and "出張所" in e.get("title", ""),
)
check("同id原地更新、舊資料移除、新資料append",
      [(e["id"], e.get("endDate", "")) for e in out],
      [("keep", ""), ("po-1", "2026-07-31"), ("other", ""), ("po-2", "")])

# ── 結語 ──────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 40}\n結果：{_passed} 通過、{_failed} 失敗")
sys.exit(1 if _failed else 0)
