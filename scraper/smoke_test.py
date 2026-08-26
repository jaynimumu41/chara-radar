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
import data_lint

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
check("柏高島屋→Chiba", scrape.correct_city("柏高島屋 本館地下2階 催会場"), "Chiba")
check("ららぽーと磐田→Shizuoka", scrape.correct_city("ららぽーと磐田 1F 中央広場"), "Shizuoka")
check("カワトク→Iwate", scrape.correct_city("パルクアベニュー・カワトク"), "Iwate")
check("高崎髙島屋→Gunma", scrape.correct_city("高崎髙島屋 6階 催会場"), "Gunma")
check("むさし村山→Tokyo", scrape.correct_city("イオンモールむさし村山"), "Tokyo")
check("イオンモール太田→Gunma", scrape.correct_city("イオンモール太田"), "Gunma")
check("イオンモール高岡→Toyama", scrape.correct_city("イオンモール高岡"), "Toyama")
check("北千住マルイ→Tokyo", scrape.correct_city("北千住マルイ"), "Tokyo")
check("グランデュオ蒲田→Tokyo", scrape.correct_city("グランデュオ蒲田"), "Tokyo")
check("アティ郡山→Fukushima", scrape.correct_city("アティ郡山"), "Fukushima")
check("KAGOSHIMA BAY→Kagoshima", scrape.correct_city("イオンモール KAGOSHIMA BAY"), "Kagoshima")
check("イオンモール新発田→Niigata", scrape.correct_city("イオンモール新発田"), "Niigata")
check("イオンモール秋田→Akita", scrape.correct_city("イオンモール秋田"), "Akita")
check("0%NAHA→Okinawa", scrape.correct_city("0%NAHA"), "Okinawa")
check("南風原→Okinawa", scrape.correct_city("イオン南風原店"), "Okinawa")
check("ショッピングシティベル→Fukui", scrape.correct_city("ショッピングシティベル"), "Fukui")
check("KOBE PORT TOWER→Hyogo",
      scrape.correct_city("KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront"),
      "Hyogo")
check("鹿児島市立美術館→Kagoshima", scrape.correct_city("鹿児島市立美術館"), "Kagoshima")
check("無關鍵字→None", scrape.correct_city("某不知名地點"), None)
check("具體秋田場館優先於標題中的東京品牌名",
      scrape.correct_city("秋田駅ビル トピコ", "Chiikawa x 東京ばな奈 快閃店"),
      "Akita")

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

saved_rejected = scrape._REJECTED
scrape._REJECTED = {
    "url_contains": ["topics.smt.docomo.ne.jp/amp/article/kisspress/region/kisspress-64774"],
    "title_contains": [],
}
check("黑名單URL正規化可攔截同文非AMP版本",
      scrape.is_rejected_url(
          "https://topics.smt.docomo.ne.jp/article/kisspress/region/kisspress-64774?x=1"),
      True)
scrape._REJECTED = saved_rejected

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
check("純網路福袋預購且無實體地點→擋",
      scrape.is_online_only_merchandise(
          ev(brand="chiikawa", type="reservation", title="吉伊卡哇羊年主題福袋預購",
             locationName="", summaryZh="官方網路商店開放福袋預購。"),
          source_title="ちいかわ ハッピーバッグ2027 予約開始",
          page_text="ちいかわ公式WEB SHOP ちいかわマーケットにて予約受付"),
      True)
check("實體店新品即使另有線上販售→不擋",
      scrape.is_online_only_merchandise(
          ev(brand="pokemon", type="new_product", title="寶可夢中心新品",
             locationName="Pokémon Center TAIPEI", summaryZh="台北實體店開賣。"),
          page_text="オンラインショップでも販売"),
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
check("Miffy 官方展覽場館抽取",
      official_sources._miffy_venue_from_title(
          "「誕生70周年記念　ミッフィー展」広島会場にて開催",
          "誕生70周年記念　ミッフィー展",
          "会場 公益財団法人 ひろしま美術館",
      ),
      "ひろしま美術館")
check("Miffy 官方展覽類型判定",
      official_sources._miffy_is_exhibition(
          "鹿児島市立美術館にて「美術館に行こう！」展開催",
          "美術館に行こう！",
      ),
      True)
check("Miffy 豪斯登堡官方場館抽取",
      official_sources._miffy_venue_from_title(
          "＜期間延長決定＞ハウステンボス「ミッフィーバースデーマンス」",
          "ミッフィーバースデーマンス",
      ),
      "ハウステンボス")
village_vanguard_title = "ヴィレッジヴァンガード「ミッフィーとつなぐ てがきのぬくもりフェア」開催"
village_vanguard_page = (
    f"<h1>{village_vanguard_title}</h1>"
    "<p>2026年7月31日（金）から8月31日（月）まで全国197店舗で開催。</p>"
    "<p>限定ノベルティを配布します。</p>"
    "<p>記事一覧へ戻る</p>"
    "<p>ハウステンボス「ミッフィーバースデーマンス」関連記事</p>"
)
village_vanguard_main = official_sources._main_article_text(
    village_vanguard_page, village_vanguard_title
)
check("Miffy官方正文切片排除相關文章場館",
      "ハウステンボス" in village_vanguard_main,
      False)
check("Miffy官方標題店系優先於抽獎與相關文章場館",
      official_sources._miffy_venue_from_title(
          village_vanguard_title,
          "ミッフィーとつなぐ てがきのぬくもりフェア",
          "抽獎景品為ハウステンボス住宿券",
      ),
      "全国のヴィレッジヴァンガード 197店舗")
check("Miffy官方フェア判定為campaign",
      official_sources._miffy_type(
          village_vanguard_title,
          "ミッフィーとつなぐ てがきのぬくもりフェア",
      ),
      "campaign")
cosme_kitchen_title = "「miffy × Cosme Kitchen 」コスメキッチンとミッフィーのコラボ第3弾登場"
check("Miffy Cosme Kitchen為實體店新品而非咖啡廳",
      official_sources._miffy_type(cosme_kitchen_title, "miffy × Cosme Kitchen"),
      "new_product")
check("Miffy Cosme Kitchen全國店鋪地點",
      official_sources._miffy_venue_from_title(cosme_kitchen_title, "miffy × Cosme Kitchen"),
      "全国のCosme Kitchen・Biople対象店舗")
check("Miffy 豪斯登堡期間延長解析",
      official_sources._miffy_period(
          "＜期間延長決定＞ハウステンボス「ミッフィーバースデーマンス」",
          "2026年8月30日（日）まで延長されることになりました。"
          "2026年5月29日（金）から6月28日（日）まで、長崎県のテーマパークリゾート「ハウステンボス」では開催されます。",
          2026,
          scrape.extract_dates,
      ),
      ("2026-05-29", "2026-08-30"))
check("Collabo Cafe轉載→不直接信任日期",
      scrape.is_trusted_date_source("https://collabo-cafe.com/events/collabo/chiikawa-obakenomori-odaiba2026/"), False)
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
published_events, published_date = scrape.parse_published_baseline(
    '[{"id":"public-a"},{"id":"public-b"}]',
    '\ufeff{ "updatedAt": "2026-08-04T16:04:58+08:00" }',
)
check("今日更新baseline使用Git公開快照而非執行中工作區",
      ([event["id"] for event in published_events], published_date),
      (["public-a", "public-b"], "2026-08-04"))
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
check("Kiddy Land 官方整站 403 視為防爬端點可達",
      verify_links._is_protected_official_block(
          "https://www.kiddyland.co.jp/event/miffy_nove202608/", 403),
      True)
check("Kiddy Land 404 不可被防爬例外放行",
      verify_links._is_protected_official_block(
          "https://www.kiddyland.co.jp/event/missing/", 404),
      False)
check("非 Kiddy Land 的 403 不可被放行",
      verify_links._is_protected_official_block("https://example.com/event", 403),
      False)
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
check("吉伊卡哇官方總表終了頁→不列現行待審",
      audit_chiikawa_subpages.is_ended_listing_title(
          "【終了】ちいかわPOP UP STORE イオンモール秋田"),
      True)
image_only_popup_page = """
<html><head><title>ちいかわPOP UP STORE イオンモール新小松(2026/8/5(水)～8/23(日))</title></head>
<body><img src="schedule.jpg"></body></html>
"""
check("吉伊卡哇全圖片子頁從 title 解析場地與日期",
      official_sources._chiikawa_popup_detail_fields(image_only_popup_page),
      ("イオンモール新小松", "2026-08-05", "2026-08-23"))
check("吉伊卡哇 POP UP 總表可解析相對與絕對子頁網址",
      official_sources._chiikawa_popup_detail_urls(
          '<a href="p26/pus_askm/index.html">A</a> '
          '[B](https://chiikawa-info.jp/p26/pus_asph/index.html)'),
      [
          "https://chiikawa-info.jp/p26/pus_askm/index.html",
          "https://chiikawa-info.jp/p26/pus_asph/index.html",
      ])
image_only_popup = official_sources._chiikawa_popup_event(
    "イオンモール新小松",
    "https://chiikawa-info.jp/p26/pus_askm/index.html",
    "2026-08-05",
    "2026-08-23",
    correct_city=scrape.correct_city,
)
check("吉伊卡哇全圖片子頁正確判定石川縣",
      (image_only_popup["city"], image_only_popup["locationName"]),
      ("Ishikawa", "イオンモール新小松"))
expired_popup_rows = audit_chiikawa_subpages.audit_links(
    [audit_chiikawa_subpages.ChiikawaLink(
        "https://chiikawa-info.jp/p26/pus_atko/index.html",
        "ちいかわPOP UP STORE")],
    details_by_url={
        "https://chiikawa-info.jp/p26/pus_atko/index.html":
            "<title>ちいかわPOP UP STORE イオンモール高岡(2026/7/10(金)～7/26(日))</title>"
    },
    today="2026-07-28",
)
check("吉伊卡哇已過期全圖片子頁自動忽略",
      (expired_popup_rows[0].status, expired_popup_rows[0].reason),
      ("ignored", "official event ended 2026-07-26"))

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
        "pokemon", "pokemon-store-events",
        "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-shibuya/events/202606/000368.html",
        "「ポケモンセンター なりきりサマー！」イベントカレンダー"),
    audit_official_coverage.OfficialCandidate(
        "pokemon", "pokemon-store-events",
        "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-skytreetown/events/202606/000370.html",
        "「ポケモンセンタースカイツリータウンわくわく大冒険 2026 in 東京ソラマチ®」が開催！"),
    audit_official_coverage.OfficialCandidate(
        "pokemon", "pokemon-store-events",
        "https://shop.pokemon.co.jp/ja/shop/pokemoncenter-tokyodx/events/202608/000472.html",
        "9月のイベントカレンダー公開！"),
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
          ("ignored", "-", ()),
          ("ignored", "-", ()),
          ("ignored", "-", ()),
      ])
holiday_range_signals = audit_official_coverage.detect_signals(
    "2026年8月11日（火・祝）から8月24日（月）まで、そごう千葉店で限定グッズを販売")
check("官方稽核可解析含祝日標記的日文日期區間",
      (holiday_range_signals.start_date, holiday_range_signals.end_date),
      ("2026-08-11", "2026-08-24"))
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

trusted_date_record = ev(
    brand="chiikawa",
    type="new_product",
    startDate="2026-11-22",
    endDate="",
)
check("可信來源日期可覆寫AI誤抓的公司沿革日期",
      scrape.apply_extracted_dates(
          trusted_date_record,
          "<h2>2026年8月1日(土)販売開始</h2><p>限定商品。</p>",
          2026,
          is_html=True,
      ),
      True)
check("可信來源日期覆寫結果",
      trusted_date_record["startDate"],
      "2026-08-01")
store_wrong_date = ev(
    brand="chiikawa", type="store", city="Osaka",
    title="全國初『ちいかわパークストア』",
    sourceTitle="全国初『ちいかわパークストア』 LUCUA SOUTH 第2期",
    startDate="2026-08-06", endDate="",
)
check("常設店不可誤用同頁預熱活動日期",
      scrape.clear_unsubstantiated_store_dates(
          store_wrong_date,
          "2026年11月開業 PICK UP SHOP ちいかわパークストア。"
          "開業前プロモーションのウォールアート開催期間：2026年8月6日～2027年夏頃。",
      ),
      True)
check("常設店誤抓日期清除結果", store_wrong_date["startDate"], "")
store_supported_date = ev(
    brand="chiikawa", type="store", city="Osaka",
    title="『ちいかわパークストア』",
    sourceTitle="『ちいかわパークストア』開業",
    startDate="2026-11-01", endDate="",
)
check("常設店日期有店名與開幕鄰近證據則保留",
      scrape.clear_unsubstantiated_store_dates(
          store_supported_date,
          "『ちいかわパークストア』は2026年11月1日にグランドオープンします。",
      ),
      False)
check("Kiddy Land ノベルティデイ ～スタート 不補同日結束",
      official_sources._kiddy_period(
          "2026年7月4日(土)～スタート!miffy style 各店ノベルティデイ",
          "※なくなり次第終了となりますのでご了承くださいませ。",
          scrape.extract_dates,
      ),
      ("2026-07-04", ""))
check("Kiddy Land 重複標題造成同日區間→仍視為送完為止",
      official_sources._kiddy_period(
          "2026年7月4日(土)～スタート!miffy style 各店ノベルティデイ",
          "2026年7月4日(土)～スタート!miffy style 各店ノベルティデイ "
          "※なくなり次第終了となりますのでご了承くださいませ。",
          scrape.extract_dates,
      ),
      ("2026-07-04", ""))
check("Kiddy Land標題日期優先，不受相關文章區間污染",
      official_sources._kiddy_period(
          "2026年8月15日(土)スタート!miffy style 神戸店/三宮店限定 ノベルティ",
          "関連記事 KOBE PORT TOWER 2026年7月30日～9月30日",
          scrape.extract_dates,
      ),
      ("2026-08-15", ""))
check("Kiddy Land神戶兩店location",
      official_sources._kiddy_location("miffy style 神戸店/三宮店限定 ノベルティ"),
      ("miffy style 神戸店・三宮店", "Hyogo"))
check("Kiddy Land標題移除スタート前綴",
      official_sources._kiddy_display_title(
          "2026年8月15日(土)スタート!miffy style 神戸店/三宮店限定 ノベルティ"),
      "miffy style 神戸店/三宮店限定 ノベルティ")
chainwide_kiddy, _ = scrape.dedup_events([
    ev(id="mi-chainwide", brand="miffy", type="campaign",
       title="Miffy miffy style 各店ノベルティデイ",
       startDate="2026-08-08", locationName="miffy style 各店＋キデイランド対象店"),
    ev(id="mi-kobe-shops", brand="miffy", type="campaign", city="Hyogo",
       title="Miffy miffy style 神戸店/三宮店限定 ノベルティ",
       startDate="2026-08-15", locationName="miffy style 神戸店・三宮店"),
])
check("Kiddy Land全店活動不可與指定分店活動模糊合併", len(chainwide_kiddy), 2)
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

sample_chiikawa_popups = (
    "[ちいかわPOP UP STORE 高崎髙島屋](https://chiikawa-info.jp/p26/pus_tkst/index.html) "
    "2099年7月29日(水)～8月17日(月) 高崎髙島屋 6階 催会場\n"
    "[ちいかわPOP UP STORE イオンモールむさし村山]"
    "(https://chiikawa-info.jp/p26/pus_amsm/index.html) "
    "2099年7月24日(金)～8月11日(火祝) イオンモールむさし村山 1F センターコート\n"
    "[ちいかわPOP UP STORE イオンモール太田](https://chiikawa-info.jp/p26/pus_aota/index.html) "
    "2099年7月17日(金)～8月2日(日) イオンモール太田 ウエストモール1F 無印良品前\n"
    "[ちいかわPOP UP STORE イオンモール高岡](https://chiikawa-info.jp/p26/pus_atko/index.html) "
    "2099年7月10日(金)～7月26日(日) イオンモール高岡 東館1F セントラルコート"
)
popup_events = official_sources._chiikawa_popup_events_from_text(
    sample_chiikawa_popups, correct_city=scrape.correct_city)
check("吉伊卡哇官方POP UP總表新增場次解析",
      [(e["city"], e["startDate"], e["endDate"]) for e in popup_events],
      [("Gunma", "2099-07-29", "2099-08-17"),
       ("Tokyo", "2099-07-24", "2099-08-11"),
       ("Gunma", "2099-07-17", "2099-08-02"),
       ("Toyama", "2099-07-10", "2099-07-26")])

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
    "2099年7月10日(金)～7月20日(月祝) "
    "華山1914文創園區 藝術西街 2026年7月10日(金)～8月30日(日) "
    "[イオンモールKYOTO Sakura館1階 センターコート](https://kyoto.aeonmall.com/) "
    "2026年8月21日(金)～9月6日(日)"
)
movie_events = official_sources._chiikawa_movie_popup_events_from_text(
    sample_movie_popup, correct_city=scrape.correct_city, today="2026-07-01")
check("電影吉伊卡哇 POP UP 多會場解析數量",
      len(movie_events), 3)
check("電影吉伊卡哇 POP UP 解析城市與國家",
      [(e["city"], e["country"], e["startDate"], e["endDate"]) for e in movie_events],
      [("Niigata", "JP", "2099-07-10", "2099-07-20"),
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
    sample_movie_goods, correct_city=scrape.correct_city, today="2026-07-01")
check("電影吉伊卡哇グッズ取扱店 高信心區塊解析數量",
      len(movie_goods), 2)
check("電影吉伊卡哇グッズ取扱店 解析類型城市日期",
      [(e["type"], e["city"], e["startDate"], e["endDate"]) for e in movie_goods],
      [("new_product", "", "2026-07-10", "2026-08-31"),
       ("new_product", "Tokyo", "2026-07-25", "2026-08-23")])
check("電影吉伊卡哇グッズ取扱店 sourceUrl 不共用",
      len({e["sourceUrl"] for e in movie_goods}), 2)
movie_goods_after_fuji = official_sources._chiikawa_movie_goods_events_from_text(
    sample_movie_goods, correct_city=scrape.correct_city, today="2026-08-24")
check("電影吉伊卡哇グッズ取扱店 過期場次依指定日期排除",
      [(e["startDate"], e["endDate"]) for e in movie_goods_after_fuji],
      [("2026-07-10", "2026-08-31")])

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
check("可信日期來源 campaign 日期完整→不因 campaign_type 進候選",
      agent_verify_candidates.verification_reasons(
          ev(brand="chiikawa", type="campaign", sourceType="official_social",
             sourceUrl="https://www.tokyo-skytree.jp/press/post/712/",
             locationName="東京スカイツリー",
             startDate="2026-07-10", endDate="2026-10-31")),
      [])
product_reasons = agent_verify_candidates.verification_reasons(
    ev(brand="pokemon", type="new_product", sourceType="official_social",
       sourceUrl="https://www.nownews.com/news/test",
       title="台灣寶可夢中心新商品",
       locationName="台灣寶可夢中心",
       startDate="2026-06-27", endDate=""))
check("新品開賣無 endDate→不標 missing_endDate",
      "missing_endDate" in product_reasons,
      False)
check("已確認過的非官方 event id→候選器可跳過",
      agent_verify_candidates.is_reviewed_candidate(
          ev(id="po-confirmed"),
          ["untrusted_date_domain:nownews.com", "generic_title"],
          {"po-confirmed"}),
      True)
check("已確認過的官方送完為止 event id→候選器可跳過",
      agent_verify_candidates.is_reviewed_candidate(
          ev(id="mi-confirmed"),
          ["missing_endDate", "structured_activity_missing_endDate", "campaign_type"],
          {"mi-confirmed"}),
      True)
check("已確認過且開幕日未定的常設店→候選器可跳過",
      agent_verify_candidates.is_reviewed_candidate(
          ev(id="reviewed-store", type="store"),
          ["missing_dates", "missing_endDate"],
          {"reviewed-store"}),
      True)

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
pokemon_latte = official_sources._pokemon_cafe_latte_event_from_text(
    "2026.07.03 「選べるポケモンラテ」に、メルタンとメルメタルが仲間入り！"
    "7月17日（金）、ポケモンカフェの「選べるポケモンラテ」に、メルタンとメルメタルが仲間入り！"
    "商品詳細 選べるポケモンラテ 販売店舗 ポケモンカフェ TOKYO ポケモンカフェ OSAKA 発売日 7月17日（金）",
    "https://www.pokemon-cafe.jp/ja/cafe/news/260703_3439.html",
    correct_city=scrape.correct_city,
)
check("Pokémon Cafe 選べるポケモンラテ新拉花解析",
      (pokemon_latte["id"], pokemon_latte["type"], pokemon_latte["locationName"],
       pokemon_latte["startDate"], pokemon_latte["endDate"], pokemon_latte["needReservation"]),
      ("po-4090c2", "cafe", "Pokémon Cafe TOKYO / OSAKA", "2026-07-17", "", True))

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
    ev(brand="sanrio", title="三麗鷗遊樂園快閃 高雄夢時代限定店", city="Kaohsiung",
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
    ev(id="mi-official-kobe", brand="miffy",
       title="Miffy 神戶港塔 Night Time 聯名活動", type="cafe", city="Hyogo",
       startDate="2026-07-30", endDate="2026-09-30",
       locationName="KOBE PORT TOWER×Dick Bruna TABLE in KOBE Waterfront",
       sourceType="official_site", sourceUrl="https://dickbruna.jp/news/202606/46792/"),
    ev(id="mi-media-kobe", brand="miffy",
       title="神戶港塔變身米飛兔主題", type="popup", city="Hyogo",
       startDate="2026-07-30", endDate="2026-09-30", locationName="神戶港塔",
       sourceTitle="神戸ポートタワーがまるごとミッフィーに グッズやフードを体験",
       sourceUrl="https://topics.smt.docomo.ne.jp/article/kisspress/region/kisspress-64774"),
])
check("Miffy神戶Waterfront官方頁與媒體體驗文去重",
      (len(out), out[0]["id"], out[0]["sourceType"]),
      (1, "mi-official-kobe", "official_site"))
check("Miffy神戶不同年度檔期不可誤併",
      scrape.strong_event_identity_key(ev(
          brand="miffy", title="神戶港塔米飛兔活動", type="popup", city="Hyogo",
          startDate="2027-07-30", locationName="神戶港塔"))
      == scrape.strong_event_identity_key(out[0]),
      False)

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
flower_miffy_title = "Flower Miffy フラワーミッフィー バースデーキャンペーン開催"
check("Miffy官方Flower生日活動→顯示名稱正規化",
      official_sources._miffy_display_name(flower_miffy_title, flower_miffy_title),
      "Flower Miffy バースデーキャンペーン")
check("Miffy官方Flower生日活動→地點正規化",
      official_sources._miffy_venue_from_title(flower_miffy_title, flower_miffy_title),
      "全国のフラワーミッフィー、フラワーミッフィーオンラインショップ")

out, _ = scrape.dedup_events([
    ev(id="mi-official-tokyo", brand="miffy",
       title="miffy style東京駅店限定 駅長さんミッフィーぬいぐるみ&マスコット&チャーム",
       type="new_product", city="Tokyo", startDate="2026-07-04",
       locationName="miffy style 東京駅店",
       sourceType="official_site", sourceUrl="https://www.kiddyland.co.jp/event/miffy_tokyo20260704/"),
    ev(id="mi-asahi-tokyo", brand="miffy",
       title="東京車站限定！站長米飛兔新玩偶發售",
       type="new_product", city="Tokyo", startDate="2026-07-04",
       locationName="東京車站",
       sourceTitle="今回も買えるといいな【東京駅限定】駅長さんミッフィーの新作ぬいぐるみが7/4より発売。当日は購入制限も - 朝日新聞",
       sourceType="official_social", sourceUrl="https://www.asahi.com/and/w/article/16698474"),
])
check("Miffy東京駅店限定玩偶媒體重複→保留官方",
      (len(out), out[0]["id"], out[0]["sourceType"]),
      (1, "mi-official-tokyo", "official_site"))

out, _ = scrape.dedup_events([
    ev(id="mi-official-handwriting", brand="miffy",
       title="Miffy ミッフィーとつなぐ てがきのぬくもりフェア",
       type="campaign", startDate="2026-07-31", endDate="2026-08-31",
       locationName="全国のヴィレッジヴァンガード 197店舗",
       sourceType="official_site", sourceUrl="https://dickbruna.jp/news/202607/47530/"),
    ev(id="mi-prtimes-handwriting", brand="miffy",
       title="米飛兔手寫溫度快閃店",
       type="popup", city="Tokyo", startDate="2026-07-31", endDate="2026-08-31",
       locationName="ヴィレッジヴァンガード",
       sourceTitle="ヴィレッジヴァンガードで『ミッフィーとつなぐ てがきのぬくもりフェア』開催",
       sourceType="official_social", sourceUrl="https://prtimes.jp/example"),
])
check("Miffy手寫溫度活動跨媒體與錯誤城市仍去重",
      (len(out), out[0]["id"], out[0]["sourceType"]),
      (1, "mi-official-handwriting", "official_site"))

out, _ = scrape.dedup_events([
    ev(brand="miffy", title="Miffy ミッフィーzakkaフェスタ そごう横浜店",
       type="popup", city="Kanagawa", startDate="2026-08-01", endDate="2026-08-17",
       locationName="そごう横浜店"),
    ev(brand="miffy", title="Miffy DICK BRUNA STAND BY MIIA 神奈川・そごう横浜店",
       type="popup", city="Kanagawa", startDate="2026-08-01", endDate="2026-08-17",
       locationName="神奈川・そごう横浜店"),
])
check("同館同日但不同主題的Miffy活動不可合併", len(out), 2)
check("今日更新比對不可把同館同日不同主題視為替換",
      scrape.is_same_event_for_update_diff(out[0], out[1]),
      False)

out, _ = scrape.dedup_events([
    ev(brand="chiikawa", title="Chiikawa x 東京ばな奈 聯名環保袋組",
       type="new_product", city="Tokyo", startDate="2026-08-01",
       locationName="東京ばな奈ワールド"),
    ev(brand="chiikawa", title="吉伊卡哇 x 東京香蕉 聯名周邊",
       type="new_product", city="Tokyo", startDate="2026-08-01",
       locationName="東京香蕉",
       sourceTitle="ちいかわ×東京ばな奈 エコバッグセット"),
])
check("Chiikawa東京香蕉環保袋跨媒體去重", len(out), 1)

out, _ = scrape.dedup_events([
    ev(id="ch-lucua-pr", brand="chiikawa", title="全國初『ちいかわパークストア』",
       type="store", city="Osaka", locationName="LUCUA SOUTH 11F",
       sourceTitle="全国初『ちいかわパークストア』 LUCUA SOUTH 第2期、21ブランドを先行公開",
       sourceUrl="https://prtimes.jp/main/html/rd/p/000000231.000014414.html"),
    ev(id="ch-lucua-crank", brand="chiikawa", title="大阪ちいかわパーク官方商店開幕",
       type="store", city="Osaka", locationName="ちいかわパーク",
       sourceTitle="全国初「ちいかわパーク」公式ショップが大阪に誕生へ",
       sourceUrl="https://www.crank-in.net/trend/trip/189151"),
    ev(id="ch-lucua-yahoo", brand="chiikawa", title="LUCUA SOUTH chiikawa全國初店",
       type="store", city="Osaka", locationName="LUCUA OSAKA 新館 LUCUA SOUTH",
       sourceTitle="LUCUA SOUTH キャラゾーン ちいかわ全国初店舗",
       sourceUrl="https://news.yahoo.co.jp/example"),
])
check("Chiikawa Park Store三媒體公告合併為官方PR一筆",
      (len(out), out[0]["id"], out[0]["sourceUrl"]),
      (1, "ch-lucua-pr", "https://prtimes.jp/main/html/rd/p/000000231.000014414.html"))
check("Chiikawa Park Store不同城市不可誤併",
      scrape.strong_event_identity_key(ev(
          brand="chiikawa", title="ちいかわパークストア", type="store",
          city="Tokyo", locationName="東京"))
      == scrape.strong_event_identity_key(out[0]),
      False)

out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="寶可夢 缶バッジコレクション〜ミアレ編〜登場",
       type="new_product", city="Tokyo", startDate="2026-08-01",
       locationName="ポケモンセンター"),
    ev(brand="pokemon", title="寶可夢中心 缶バッジコレクション ミアレ編 發售",
       type="new_product", city="Tokyo", startDate="2026-08-01",
       locationName="ポケモンセンター"),
])
check("Pokémonミアレ編徽章跨媒體去重", len(out), 1)

out, _ = scrape.dedup_events([
    ev(id="ch-official-haneda", brand="chiikawa",
       title="吉伊卡哇 POP UP STORE 羽田空港第1ターミナル",
       type="popup", startDate="2026-07-20", endDate="2026-08-17",
       locationName="羽田空港第1ターミナル 2F 出発ロビー HANEDA POPUP STORE",
       sourceType="official_site", sourceUrl="https://chiikawa-info.jp/p26/pus_hnds/index.html"),
    ev(id="ch-collabo-haneda", brand="chiikawa",
       title="吉伊卡哇快閃店與主題咖啡廳",
       type="popup", city="Tokyo", startDate="2026-07-20", endDate="2026-08-17",
       locationName="",
       sourceTitle="ちいかわ ポップアップストア in 東京 7月20日より開催! - コラボカフェ",
       sourceType="official_social", sourceUrl="https://collabo-cafe.com/events/collabo/chiikawa-popup-store-haneda-airport2026/"),
])
check("Chiikawa羽田官方與Collabo Cafe轉載→保留官方",
      (len(out), out[0]["id"], out[0]["sourceType"], out[0]["locationName"]),
      (1, "ch-official-haneda", "official_site", "羽田空港第1ターミナル 2F 出発ロビー HANEDA POPUP STORE"))
check("today_updates防呆：Miffy東京駅店媒體重複不可列新增",
      bool(data_lint.today_update_duplicate_errors([
          ev(id="mi-official-tokyo", brand="miffy",
             title="miffy style東京駅店限定 駅長さんミッフィーぬいぐるみ&マスコット&チャーム",
             type="new_product", city="Tokyo", startDate="2026-07-04",
             locationName="miffy style 東京駅店"),
          ev(id="mi-asahi-tokyo", brand="miffy",
             title="東京車站限定！站長米飛兔新玩偶發售",
             type="new_product", city="Tokyo", startDate="2026-07-04",
             locationName="東京車站",
             sourceTitle="今回も買えるといいな【東京駅限定】駅長さんミッフィーの新作ぬいぐるみが7/4より発売。当日は購入制限も - 朝日新聞"),
      ], ["mi-asahi-tokyo"])),
      True)
check("today_updates防呆：Chiikawa羽田轉載不可列新增",
      bool(data_lint.today_update_duplicate_errors([
          ev(id="ch-official-haneda", brand="chiikawa",
             title="吉伊卡哇 POP UP STORE 羽田空港第1ターミナル",
             type="popup", startDate="2026-07-20", endDate="2026-08-17",
             locationName="羽田空港第1ターミナル 2F 出発ロビー HANEDA POPUP STORE",
             sourceUrl="https://chiikawa-info.jp/p26/pus_hnds/index.html"),
          ev(id="ch-collabo-haneda", brand="chiikawa",
             title="吉伊卡哇快閃店與主題咖啡廳",
             type="popup", city="Tokyo", startDate="2026-07-20", endDate="2026-08-17",
             sourceTitle="ちいかわ ポップアップストア in 東京 7月20日より開催! - コラボカフェ",
             sourceUrl="https://collabo-cafe.com/events/collabo/chiikawa-popup-store-haneda-airport2026/"),
      ], ["ch-collabo-haneda"])),
      True)
check("today_updates防呆：currentEventCount與events.json不一致要報錯",
      data_lint.today_update_count_errors(
          [ev(id="a"), ev(id="b")],
          {"currentEventCount": 3, "newEventCount": 0},
          []),
      ["today_updates.json currentEventCount mismatch: expected 2, got 3"])
check("today_updates防呆：newEventCount與newEventIds不一致要報錯",
      data_lint.today_update_count_errors(
          [ev(id="a"), ev(id="b")],
          {"currentEventCount": 2, "newEventCount": 2},
          ["b"]),
      ["today_updates.json newEventCount mismatch: expected 1, got 2"])

out, _ = scrape.dedup_events([
    ev(brand="chiikawa", title="吉伊卡哇袋著走 台北快閃店", type="popup",
       city="Taipei", startDate="2026-05-22", endDate="2026-06-30",
       locationName="CHIIKAWA SHOP in TAIPEI 2F",
       sourceType="official_site",
       sourceUrl="https://chiikawa-info.jp/p26/chiikawa_pocket_taipei/index.html"),
    ev(brand="chiikawa", title="吉伊卡哇袋著走 台北快閃店", type="popup",
       city="Taipei", startDate="2026-05-22", locationName="台北快閃店",
       sourceType="official_social",
       sourceUrl="https://n.yam.com/Article/20260513924105"),
    ev(brand="chiikawa", title="吉伊卡哇袋著走快閃店", type="popup",
       city="Taipei", startDate="2026-05-22", locationName="SouNova 少女星",
       sourceType="official_social",
       sourceUrl="https://sounova.com/news/chiikawa-pocket-pop-up-store-in-taipei"),
])
check("Chiikawa袋著走台北媒體重複→保留官方完整資料",
      (len(out), out[0]["sourceType"], out[0]["endDate"]),
      (1, "official_site", "2026-06-30"))

out, _ = scrape.dedup_events([
    ev(brand="chiikawa", title="吉伊卡哇 CHIIKAWA DAYS 台北特展", type="popup",
       city="Taipei", startDate="2026-07-04", endDate="2026-09-27",
       locationName="華山1914文化創意產業園區 東2館",
       sourceUrl="https://supertaste.tvbs.com.tw/accessories/359723"),
    ev(brand="chiikawa", title="吉伊卡哇台北特展 CHIIKAWA DAYS", type="campaign",
       city="Taipei", startDate="2026-07-04", endDate="2026-09-27",
       locationName="台北",
       sourceUrl="https://www.4gamers.com.tw/news/detail/79182/chiikawa-days-taipei-2026-huashan1914"),
])
check("Chiikawa Days台北特展媒體重複→合併", len(out), 1)

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
chiikawa_diff = scrape.build_update_diff(
    [ev(id="old-pocket", brand="chiikawa", title="吉伊卡哇袋著走 台北快閃店",
        type="popup", city="Taipei", startDate="2026-05-22", endDate="2026-06-30",
        locationName="CHIIKAWA SHOP in TAIPEI 2F")],
    [ev(id="new-pocket", brand="chiikawa", title="吉伊卡哇袋著走快閃店",
        type="popup", city="Taipei", startDate="2026-05-22",
        locationName="SouNova 少女星",
        sourceUrl="https://sounova.com/news/chiikawa-pocket-pop-up-store-in-taipei")],
    date="2026-06-25",
    baseline_date="2026-06-24",
)
check("更新差異：Chiikawa台北重複媒體不算今日新增",
      (chiikawa_diff["newEventIds"], chiikawa_diff["countsByBrand"]["chiikawa"], chiikawa_diff["replacements"]),
      ([], 0, [{"from": "old-pocket", "to": "new-pocket"}]))

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

out, _ = scrape.dedup_events([
    ev(brand="miffy", title="Miffy 美術館に行こう！展", type="campaign", city="Kagoshima",
       startDate="2026-07-17", endDate="2026-08-30", locationName="鹿児島市立美術館",
       sourceUrl="https://dickbruna.jp/news/202606/46804/"),
    ev(brand="miffy", title="Miffy ミッフィーzakkaフェスタ", type="popup", city="Kagoshima",
       startDate="2026-07-17", endDate="2026-07-29", locationName="鹿児島・山形屋",
       sourceUrl="https://dickbruna.jp/news/202607/47282/"),
])
check("同品牌同城同日起日但明確不同場館→不併（2筆）", len(out), 2)

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

out, _ = scrape.dedup_events([
    ev(brand="pokemon", title="台灣寶可夢中心卡娜赫拉皮卡丘家族玩偶新品開賣", type="new_product",
       city="Taipei", startDate="2026-06-27", locationName="台灣寶可夢中心",
       summaryZh="台灣寶可夢中心將於6月27日開賣卡娜赫拉與皮卡丘家族系列新品玩偶。",
       sourceUrl="https://www.nownews.com/amp/news/6848992"),
    ev(brand="pokemon", title="寶可夢X卡娜赫拉 台北限定復刻", type="new_product",
       city="Taipei", startDate="2026-06-27", locationName="Pokémon Center TAIPEI",
       summaryZh="台北寶可夢中心將於6月27日在信義區門市復刻販售《Pokémon Yurutto》系列商品。",
       sourceUrl="https://www.marieclaire.com.tw/lifestyle/whats-hot/94241"),
])
check("寶可夢卡娜赫拉/Yurutto台北同日復刻→合併（1筆）", len(out), 1)

kanahei_diff = scrape.build_update_diff(
    [ev(id="old-kanahei", brand="pokemon", title="台灣寶可夢中心卡娜赫拉皮卡丘家族玩偶新品開賣",
        type="new_product", city="Taipei", startDate="2026-06-27", locationName="台灣寶可夢中心",
        summaryZh="台灣寶可夢中心將於6月27日開賣卡娜赫拉與皮卡丘家族系列新品玩偶。")],
    [ev(id="new-kanahei", brand="pokemon", title="寶可夢X卡娜赫拉 台北限定復刻",
        type="new_product", city="Taipei", startDate="2026-06-27", locationName="Pokémon Center TAIPEI",
        summaryZh="台北寶可夢中心將於6月27日在信義區門市復刻販售《Pokémon Yurutto》系列商品。")],
    date="2026-06-27",
    baseline_date="2026-06-26",
)
check("更新差異：寶可夢卡娜赫拉/Yurutto重複媒體不算今日新增",
      (kanahei_diff["newEventIds"], kanahei_diff["countsByBrand"]["pokemon"], kanahei_diff["replacements"]),
      ([], 0, [{"from": "old-kanahei", "to": "new-kanahei"}]))

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
check("AI去重防呆：缺場館的同城同日不同活動不可刪",
      scrape._ai_dedup_identity_supported([
          ev(brand="chiikawa", title="吉伊卡哇讀書書展", type="campaign",
             city="Tokyo", startDate="2026-07-17"),
          ev(brand="chiikawa", title="まじかるちいかわ POP UP STORE", type="popup",
             city="Tokyo", startDate="2026-07-17"),
      ]),
      False)
check("AI去重防呆：已通過確定規則的同活動可併",
      scrape._ai_dedup_identity_supported([flower_pr, flower_birthday]),
      True)

# ── 2026-08-21 cross-source duplicate regression ─────────────────────────────
print("\n[duplicate release gate] 跨來源活動身分與發布阻擋")
out, _ = scrape.dedup_events([
    ev(id="ch-kura-media", brand="chiikawa", title="吉伊卡哇 x 壽司郎限定合作",
       type="cafe", city="Osaka", startDate="2026-08-21", endDate="2026-09-30",
       locationName="くら寿司", sourceUrl="https://example.com/kura-media"),
    ev(id="ch-kura-official", brand="chiikawa", title="ちいかわ × くら寿司 コラボキャンペーン",
       type="campaign", city="Tokyo", startDate="2026-08-21", endDate="2026-09-30",
       locationName="くら寿司 全国店舗", sourceType="official_site",
       sourceUrl="https://www.kurasushi.co.jp/author/008384.html"),
])
check("藏壽司被媒體誤寫城市/類型仍只留官方一筆",
      (len(out), out[0]["id"]), (1, "ch-kura-official"))

out, _ = scrape.dedup_events([
    ev(id="mi-vermeer-existing", brand="miffy",
       title="Miffy x《真珠の耳飾りの少女》展原創商品", type="campaign",
       city="Osaka", startDate="2026-08-21", endDate="2026-09-27",
       locationName="大阪中之島美術館 5階展示室", sourceType="official_site",
       sourceUrl="https://dickbruna.jp/news/202605/46308/"),
    ev(id="mi-vermeer-new", brand="miffy",
       title="ミッフィーとフェルメール《真珠の耳飾りの少女》展 コラボグッズ",
       type="campaign", startDate="2026-08-21", endDate="2026-09-27",
       locationName="特設ショップ", sourceType="official_site",
       sourceUrl="https://dickbruna.jp/news/202608/47832/"),
    ev(id="mi-vermeer-media", brand="miffy", title="費爾梅爾展米飛限定周邊",
       type="campaign", city="Tokyo", startDate="2026-08-21", endDate="2026-09-27",
       locationName="東京都美術館", sourceUrl="https://example.com/vermeer-media"),
])
check("費爾梅爾展不同官方頁與錯誤城市媒體文合併為既有資料",
      (len(out), out[0]["id"]), (1, "mi-vermeer-existing"))

out, _ = scrape.dedup_events([
    ev(id="ch-centrair-media", brand="chiikawa", title="吉伊卡哇愛知快閃店",
       type="popup", city="Aichi", startDate="2026-09-08", endDate="2026-10-05",
       sourceUrl="https://collabo-cafe.com/events/chiikawa-pop-up-store-centrair-2026/"),
    ev(id="ch-centrair-official", brand="chiikawa", title="ちいかわ POP UP STORE 中部国際空港",
       type="popup", startDate="2026-09-08", endDate="2026-10-05",
       locationName="中部国際空港 第1ターミナル", sourceType="official_site",
       sourceUrl="https://chiikawa-info.jp/p26/pus_cbca/index.html"),
])
check("中部機場快閃媒體文與官方頁合併",
      (len(out), out[0]["id"]), (1, "ch-centrair-official"))

check("豪斯登堡生日季跨來源身分一致",
      scrape.strong_event_identity_key(ev(
          brand="miffy", title="豪斯登堡 Miffy 生日季", type="campaign",
          startDate="2026-05-29", sourceTitle="ミッフィーバースデーシーズン ハウステンボス")),
      "miffy|miffy-huis-ten-bosch-birthday-season|2026-05-29")
check("ぱたぱた玩偶跨來源身分一致",
      scrape.strong_event_identity_key(ev(
          brand="pokemon", title="ぱたぱたっ！ぬいぐるみ 寶可夢中心發售",
          type="new_product", startDate="2026-08-08")),
      "pokemon|pokemon-patapata-plush|2026-08-08")

out, _ = scrape.dedup_events([
    ev(id="mi-kobe-parent", brand="miffy", title="Miffy 神戶港塔 Night Time 聯名活動",
       type="campaign", city="Hyogo", startDate="2026-07-30", endDate="2026-09-30",
       locationName="KOBE PORT TOWER × Dick Bruna TABLE in KOBE Waterfront"),
    ev(id="mi-kobe-cruise", brand="miffy", title="米飛夏日限定聯名遊輪",
       type="cafe", city="Hyogo", startDate="2026-07-30", endDate="2026-09-30",
       locationName="神戸リゾートクルーズ boh boh KOBE"),
])
check("神戶母活動與獨立遊輪體驗不誤併", len(out), 2)

stable_errors = data_lint.stable_identity_duplicate_errors([
    ev(id="ch-kura-a", brand="chiikawa", title="ちいかわ くら寿司", type="campaign",
       startDate="2026-08-21"),
    ev(id="ch-kura-b", brand="chiikawa", title="藏壽司吉伊卡哇合作", type="cafe",
       startDate="2026-08-21"),
])
check("lint 將穩定身分重複視為錯誤", len(stable_errors), 1)
replacement_errors = data_lint.replacement_mapping_errors({"replacements": [
    {"from": "old-one", "to": "new-a"},
    {"from": "old-one", "to": "new-b"},
]})
check("lint 阻擋一筆舊資料被重複替換",
      replacement_errors,
      ["today_updates.json replacement source reused: old-one (2)"])

try:
    scrape.build_update_diff(
        [ev(id="old-one", brand="miffy", title="Miffy 限定活動",
            sourceUrl="https://example.com/same-event")],
        [
            ev(id="new-a", brand="miffy", title="Miffy 限定活動 A",
               sourceUrl="https://example.com/same-event"),
            ev(id="new-b", brand="miffy", title="Miffy 限定活動 B",
               sourceUrl="https://example.com/same-event"),
        ],
    )
    one_to_many_blocked = False
except ValueError:
    one_to_many_blocked = True
check("更新差異計算直接阻擋一對多基準配對", one_to_many_blocked, True)

hierarchy_events = [
    ev(id="mi-ea7f4f", brand="miffy", title="Miffy 神戶 Waterfront 母活動",
       type="campaign", city="Hyogo", startDate="2026-07-30", endDate="2026-09-30"),
    ev(id="mi-aa3188", brand="miffy", title="Miffy 神戶主題客房",
       type="reservation", city="Hyogo", startDate="2026-07-30", endDate="2026-09-30"),
    ev(id="mi-356f47", brand="miffy", title="Miffy 神戶聯名遊輪",
       type="cafe", city="Hyogo", startDate="2026-07-30", endDate="2026-09-30"),
]
scrape.apply_event_hierarchy(hierarchy_events)
check("母子活動規則附加 parentEventId",
      [event.get("parentEventId", "") for event in hierarchy_events],
      ["", "mi-ea7f4f", "mi-ea7f4f"])
check("有效母子活動通過 lint",
      data_lint.event_hierarchy_errors(hierarchy_events), [])
check("缺少母活動時 lint 阻擋",
      len(data_lint.event_hierarchy_errors([
          ev(id="child", brand="miffy", parentEventId="missing-parent")
      ])), 1)
check("跨品牌母子活動 lint 阻擋",
      len(data_lint.event_hierarchy_errors([
          ev(id="parent", brand="pokemon"),
          ev(id="child", brand="miffy", parentEventId="parent"),
      ])), 1)

class _BrokenRotator:
    def call(self, _prompt):
        raise RuntimeError("temporary 503")


retry_event = scrape.extract_event(_BrokenRotator(), "miffy", {
    "title": "ミッフィー期間限定イベント",
    "description": "",
    "source": "test",
    "pubDate": "",
    "link": "https://example.com/event",
})
check("暫時性AI萃取失敗→不寫入processed、隔天可重試",
      retry_event, {"_skipNoProcess": True})

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
