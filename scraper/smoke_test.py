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
import agent_verify_candidates

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
check("Collabo Cafe→可信",
      scrape.is_trusted_date_source("https://collabo-cafe.com/events/collabo/chiikawa-obakenomori-odaiba2026/"), True)
check("台灣寶可夢官方→可信",
      scrape.is_trusted_date_source("https://tw.portal-pokemon.com/goods/post-5343/"), True)
check("寶可夢出張所結構化排程→可信",
      scrape.is_trusted_date_source("https://oneheart65.net/pokemoncenterbranch_schedule_2/"), True)
check("網址參數提到 prtimes.jp→不誤信",
      scrape.is_trusted_date_source("https://example.com/read?src=prtimes.jp"), False)

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

# ── extract_dates ─────────────────────────────────────────────────────────────
print("\n[extract_dates] 日期區間擷取")
check("日文範圍含年", scrape.extract_dates("2026年5月27日（水）〜6月14日（日）", is_html=False),
      ("2026-05-27", "2026-06-14"))
check("中文至/到（只結束日）",
      scrape.extract_dates("即日起至6月8日", ref_year=2026, is_html=False),
      ("", "2026-06-08"))
check("台灣寶可夢官方商品店頭發售日",
      official_sources._tw_store_sale_date("即將於3月14日(六)在Pokémon Center TAIPEI登場！", "2026-02-27"),
      "2026-03-14")
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
