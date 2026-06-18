# 角色情報雷達 — 篩選與去重規則總覽

> 給接手者的快速地圖。規則本體都在 `scrape.py`，本檔只做集中索引與說明，
> 改規則時兩邊一起更新。核心原則：**準確 > 覆蓋**——寧可漏，不可錯／重複／過期。

目前涵蓋品牌：Pokémon（寶可夢）、Miffy（米飛兔）、Chiikawa（吉伊卡哇）。
Sanrio（三麗鷗）先暫停，因無結構化來源、新聞/Gemini 污染最高，會消耗最多 agent 驗證時間。
地區：日本 + 台灣。

---

## 1. 資料來源（兩條管線）

| 管線 | 來源 | 是否用 AI | 程式位置 |
| -- | -- | -- | -- |
| 結構化官方頁（零 Gemini） | 吉伊卡哇 `chiikawa-info.jp/pus.html`＋`chiikawa-info.jp/` 首頁卡片＋`chiikawa-info.jp/p26/mck_scpus/index.html` 電影 POP UP 多會場頁＋`chiikawamogumogu.jp` 店鋪頁、寶可夢 `oneheart65.net` 出張所排程＋`pokemon-cafe.jp` 官方 café news＋台灣官方商品頁 `tw.portal-pokemon.com/goods/`、Miffy `dickbruna.jp/event/`＋`dickbruna.jp/news/` 指定活動＋Kiddy Land / miffy style 站內搜尋 | 否，regex + 模板 | `official_sources.py` |
| 官方新聞稿 + 一般新聞 | PR TIMES 關鍵字、Google News RSS（日文 + 中文） | 是，Gemini 萃取 | `scrape.py` |

- 結構化來源每次跑都以官方最新清單覆蓋同來源 URL 的舊資料（過期由 `clean_events` 移除）。
- `data/today_updates.json` 是前端「今日更新」的依據：每日 scraper 會用跑前的公開資料與跑後資料比對，只列出前次版本沒有的新情報；`createdAt` 不能直接當作今日新增，因為結構化來源重建、修正或來源替換也可能寫成今天。
- 吉伊卡哇除了 POP UP STORE 排程，也抓官方首頁上的活動/店鋪卡片、`p26/mck_scpus/index.html` 電影 POP UP 多會場頁與 `chiikawamogumogu.jp` 專門店頁；這類官方子頁、常設店開幕、限定餐飲與原創周邊不一定會進 Google News/RSS，需走結構化解析。
- `scraper/audit_chiikawa_subpages.py` 會巡覽 `chiikawa-info.jp/index.html` 連出的 `p26/.../index.html` 子頁，對照 `data/events.json` 標記 `parsed` / `ignored` / `needs_review`。`needs_review` 只是稽核提示，不會自動入庫；有明確會場＋日期＋商品/店鋪訊號的 high risk 頁面，應優先補結構化 parser 或人工標成不收。
- `scraper/audit_official_coverage.py` 會稽核 Pokémon / Miffy 官方入口（Pokémon Cafe、台灣 Pokémon goods、Pokemon Center 店鋪 news/events、Dick Bruna event/news、Kiddy Land/miffy style 搜尋），標記 `parsed` / `ignored` / `needs_review`。每天 agent 需看 high/medium risk；不是自動入庫，而是用來防「官方有但 parser 沒接」。
- oneheart65 的 Pokémon Center 出張所不是品牌官方站，但本專案以結構化方式解析其排程，日期已列入可信日期來源；完整起訖日的出張所不再進每日 agent 高風險候選。
- 台灣寶可夢官方商品頁會解析 Next.js embedded data，只收「內頁明確寫 Pokémon Center TAIPEI 登場／販售」的近期商品；例外是官方頁明確列出 `POP UP Promotion`、活動期間與台灣實體活動店鋪者（例如 K.UNO / U-TREASURE）可收為 `popup`。LINE 貼圖/主題、卡牌、遊戲、純線上授權商品一律過濾。Instagram 僅作 agent/人工驗證輔助，不納入純 Python 抓取主來源。
- 台灣 Pokémon Center 新品若只出現在 NOWnews / Pokemon Hubs 等二手來源，需列入 agent 高風險候選；但若內文明確寫台灣寶可夢中心 / Pokémon Center TAIPEI、實體店開賣日、商品內容，且沒有官方或其他來源反證，可暫留，不因官方商品頁查無同筆就直接刪除。
- 這類二手來源 URL 不可只因「沒有官方 goods 頁」加入 `rejected.json`。只有確認為錯誤、重複、過期、不符類型或被官方反證時，才可加入黑名單。
- Pokémon Cafe 官方 news（`pokemon-cafe.jp/ja/cafe/news/`）屬結構化官方來源；日本橋／心齋橋 café 重新開張、店內翻新、新菜單與 show 更新可收為 `store` 型情報，沒有明確結束日不可硬填 endDate。
- Miffy 另補 Kiddy Land / miffy style 站內搜尋（`kiddyland.co.jp/?s=miffy`），抓近期官方店頭活動與新品，避免 Google News/RSS 漏掉官方店鋪消息。
- Kiddy Land / Dick Bruna 頁面常把「最新記事／関連記事」放在本文後方；日期擷取必須先切出主文章，不能讓側欄或相關文章的日期污染活動期間。
- Miffy 公開顯示欄位（`title` / `locationName` / `summaryZh` / `tags`）若出現 `フラワーミッフィー`，統一轉成 `Flower Miffy`；`sourceTitle` 保留原文，方便回查來源。
- 三麗鷗無可解析的結構化官方頁（`sanrio.co.jp` 503／JS 動態／REST 空），目前暫停預設抓取與前端顯示。
- 抓取被擋（403/429/503）時自動改走 reader 代理 `r.jina.ai`，不放棄（`verify_links.fetch_html` / `check_url`）。

### 非官方來源信譽

- 非官方來源不是一律排除；它們先進候選與每日 agent 驗證，通過後才留在正式資料。
- `data/source_reputation.json` 記錄來源信譽，`scraper/source_reputation.py` 負責查詢與回寫。
- 信譽不只看網域，也要看品牌、類型、國家：同一來源可能在 `pokemon` / `TW` / `new_product` 準，但在其他品牌或活動型態仍是未驗證。
- 候選清單會顯示來源分數、tier、需要幾個獨立佐證來源。高分來源可降低驗證摩擦，但不能免除原文檢查；低分或未驗證來源需要更多佐證。
- IG / Threads 等社群來源以帳號 handle 追蹤，不以整個平台追蹤。合作方官方、商場官方、品牌官方社群可作強佐證；一般分享帳只能作輔助佐證。
- 每次 agent 判斷後，用 `source_reputation.py record` 回寫 `confirmed` / `rejected` / `uncertain`，讓來源分數隨歷史表現變動。
- 不手動把 NOWnews / Pokemon Hubs 等二手來源整站升為可信官方；若多次驗證準確，讓它們自然升為特定品牌/類型/地區的高分來源。

---

## 2. 採用的四類情報（AI 判斷，`EXTRACT_PROMPT`）

只收「值得專程去現場、買得到限定商品」的：

1. 快閃店 / POP UP STORE / 期間限定店
2. 新商品發售（實體門市／官方店舖開賣的周邊）
3. 活動限定商品（特展、聯名、週年慶現場的限定販售）
4. 限定餐飲（主題咖啡廳、限定菜單／甜點）

且必須是該品牌、地點在日本或台灣。

---

## 3. 雜訊過濾（送 AI 前先擋，省額度）

| 規則 | 函式 | 說明 |
| -- | -- | -- |
| 一般雜訊關鍵字 | `is_noise` / `NOISE_KEYWORDS` | 超商／百元店／量販、食品飲料聯名、媒體動畫手遊、扭蛋盲盒夾娃娃、廣泛通路一番賞、文具小物、海外 |
| 體育／路跑 | `is_sports_noise` / `SPORTS_NOISE` | 棒球主題日、始球式、路跑、馬拉松等體驗非購物（比對標題＋摘要＋內文） |
| 彙整／懶人包 | `is_roundup_title` / `ROUNDUP_KEYWORDS` | 「懶人包／總整理／行事曆／整理包」——多活動雜揉、無單一檔期。詞彙刻意收斂，**不**含「攻略／整理／一次看」以免誤殺單一活動攻略文 |
| 壞資料黑名單 | `is_rejected_url` / `is_rejected_title` + `rejected.json` | 已確認移除的，再抓到自動擋，防復活 |
| 泛商品無實體地點 | `is_venue_less_generic_new_product` | 非可信來源的 `new_product` 若標題很泛、缺少實體店/會場訊號，且 `locationName` 空白或像媒體/出版社名 → 入庫前丟棄 |
| 服裝類新品 | `is_apparel_new_product` | `new_product` 若只是衣服／服飾／アパレル／Tシャツ等新品發售 → 丟棄；只保留真正的快閃、展覽、咖啡廳等現場活動 |
| 不穩定來源 URL | `is_unstable_source_url` | Google Search / Google News placeholder 不進正式資料；不寫 processed，隔天可重試找穩定原文 |
| 新聞過舊 | `pubdate_age_days` > `MAX_NEWS_AGE_DAYS`(45) | 發布超過 45 天多半已結束 |
| 已處理過 | `processed.json` | 跑過的原始標題不再重送 AI |

萃取後還有兩道把關（`extract_event`）：
- **舊文復活**：來源頁前段最大年份 < 今年 → 丟（`stale_by_year`）。
- **誤萃取**：來源頁未提到品牌關鍵字、或未出現活動主題詞 → 丟（`page_mentions` / `theme_tokens`）。
- **非官方泛商品防線**：`new_product` 來自非可信來源時，若沒有 `店頭` / `店舗` / `POP UP` / `Pokémon Center TAIPEI` / `ちいかわらんど` / 百貨商場等實體訊號，且地點像媒體名（例如電視台、新聞社）或空白，直接丟棄。這條規則刻意收窄，不會擋明確寫實體店開賣日與商品內容的 NOWnews / Pokemon Hubs 類型來源。
- **服裝新品防線**：衣服／服飾／アパレル／Tシャツ等單純 `new_product` 不收；若是快閃店、展覽、咖啡廳或週年活動現場販售服裝周邊，仍以活動本身判斷。
- **穩定來源要求**：若 Google News 解不出真實原文，或原文不可達/不含品牌而只能退回 Google 搜尋連結，該筆不入庫，也不標記 processed；避免把搜尋摘要日期或錯誤 placeholder 當正式資料。

---

## 4. 日期規則

- AI 只能填「內文明確寫出的活動日期」，**絕不可**把新聞發布日當活動日期；不明留空。
- 程式補抓日期（`extract_dates` + `apply_extracted_dates`）**只限可信網域**（`TRUSTED_DATE_DOMAINS`：官方／新聞稿／場館百貨頁），一般新聞內文常夾雜公告日、巡迴各城市日期 → 不自動補。
- 非可信媒體若原文附近明確標示 `活動期間` / `開催期間` / `会期` / `期間`，可用 `apply_labeled_extracted_dates` 只補完整起訖日；若既有 `startDate` 和標籤起日不一致，不可硬補。
- `popup` / `cafe` / `campaign` 這類限時活動若有 `startDate` 但沒有 `endDate`，每日 agent 驗證仍要檢查活動頁是否其實有期間；即使來源是結構化官方頁也不能直接略過。
- 防呆：補抓的起始日不早於約 400 天前；結束日不早於開始日則丟棄 endDate。
- 城市修正：`correct_city` / `AREA_TO_CITY` 用地點關鍵字校正 AI 猜錯的城市；判不出留空，不亂猜。

---

## 5. 去重規則（`dedup_events`）

兩階段：先用精確鍵（URL／標題／品牌+城市+開始日／日文主題詞／地點）合併，再用模糊比對收尾。
合併時保留資料較完整者，並補上對方的非空欄位。

**鐵則（不可違反）：**

1. **城市鐵則**：兩筆城市都有值且不同 → 不同活動，即使同來源 URL 也不併
   （巡迴排程頁多城市共用一個 URL，如各地出張所）。
2. **日期鐵則**：兩筆都有開始日且差距 **>14 天** → 不同檔期，不併
   （同場館春檔／秋檔巡迴標題常完全相同，只能靠日期區分）。
   *例外*：同一真實來源 URL 視為同篇報導，不套此否決。
3. **會場鐵則**：兩筆都有地點、非同一已知場館、字串相似度 < 0.5 → 同城不同場次，不併。
4. **商品保守規則**：`new_product` / `lottery` / `reservation` 不用「同城同日」或 fuzzy similarity 合併；同一天同店、同一泛用店名（如台北寶可夢中心／Pokémon Center TAIPEI／各店）可能開賣多個不同系列。只用相同 URL、相同標題等強訊號合併。

**應併條件（任一成立）：**

- 同一已知場館（`VENUE_CANON`）且標題相似度 ≥ 0.4（一邊無日期時放寬到 ≥ 0.2）。
- **同城 + 場館字串相似(≥0.6) + 日期區間一致(差距 ≤3 天)** ← 多家媒體報導同一檔活動。
- **場館字串相似(≥0.6) + 完整日期區間一致** ← 即使其中一筆 city 空白，也應視為同活動；常見於官方頁標題被誤放進 `locationName`。
- 同城且標題相似度 ≥ 0.50。
- 標題相似度 ≥ 0.72。

`VENUE_CANON`：知名場館別名統一代號（豪斯登堡／彩虹樂園／晴空塔／高雄夢時代／華山／松菸／駁二／勤美／台南新光…），讓同場館不同寫法能去重。

**多店同步同活動**（如 CACO 布丁狗全台 4 店）→ 列一筆，地點寫「全台 N 店同步」，city 留空。

**AI 群組去重**（`ai_dedup`，配額足時收尾跑）：補抓改寫標題的同一活動；安全防呆＝只合併同品牌、城市相容、開始日相差 ≤21 天者。

---

## 6. 過期判定（`_is_past`）

- 有結束日且已過今天 → 過期。
- 無結束日：
  - 活動型（`popup` / `cafe` / `campaign`）完全無日期 → 過期；有開始日且距今 >30 天 → 過期。
  - 商品型（`new_product` / `lottery` / `reservation`）完全無日期 → 過期；有開始日且距今 >60 天 → 過期。
  - 常設 `store` 等其他類型沿用寬鬆規則：有開始日且距今 >90 天 → 過期；完全無日期保留。
- 未來日期一律不算過期。

Agent 每日驗證另有固定 SOP：`scraper/AGENT_VERIFY.md`；候選清單可用
`python scraper/agent_verify_candidates.py --format markdown` 產生。
資料 schema 與暫停品牌檢查可用 `python scraper/data_lint.py`。

---

## 7. 測試

改任何規則前後都跑離線煙霧測試（不打網路、不花額度）：

```bash
cd scraper
set PYTHONIOENCODING=utf-8
python smoke_test.py     # exit 0=全過
```

涵蓋：`correct_city`、`canon_venue`、`stale_by_year`、`is_roundup_title`、`extract_dates`、
`_is_past`、`dedup_events`（含不同城/不同檔期不可併、同活動多媒體應併、泛用店名不同新品不可併、實際資料不誤併）。

新增／調整規則時，**同步在 `smoke_test.py` 補一個正例與一個「不可誤殺」反例**。
