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
| 結構化官方頁（零 Gemini） | 吉伊卡哇 `chiikawa-info.jp/pus.html`、寶可夢 `oneheart65.net` 出張所排程＋台灣官方商品頁 `tw.portal-pokemon.com/goods/`、Miffy `dickbruna.jp/event/`＋Kiddy Land / miffy style 站內搜尋 | 否，regex + 模板 | `official_sources.py` |
| 官方新聞稿 + 一般新聞 | PR TIMES 關鍵字、Google News RSS（日文 + 中文） | 是，Gemini 萃取 | `scrape.py` |

- 結構化來源每次跑都以官方最新清單覆蓋同來源 URL 的舊資料（過期由 `clean_events` 移除）。
- 台灣寶可夢官方商品頁只收「內頁明確寫 Pokémon Center TAIPEI 登場／販售」的近期商品；LINE 貼圖/主題、卡牌、遊戲、純線上授權商品一律過濾。Instagram 僅作 agent/人工驗證輔助，不納入純 Python 抓取主來源。
- Miffy 另補 Kiddy Land / miffy style 站內搜尋（`kiddyland.co.jp/?s=miffy`），抓近期官方店頭活動與新品，避免 Google News/RSS 漏掉官方店鋪消息。
- 三麗鷗無可解析的結構化官方頁（`sanrio.co.jp` 503／JS 動態／REST 空），目前暫停預設抓取與前端顯示。
- 抓取被擋（403/429/503）時自動改走 reader 代理 `r.jina.ai`，不放棄（`verify_links.fetch_html` / `check_url`）。

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
| 新聞過舊 | `pubdate_age_days` > `MAX_NEWS_AGE_DAYS`(45) | 發布超過 45 天多半已結束 |
| 已處理過 | `processed.json` | 跑過的原始標題不再重送 AI |

萃取後還有兩道把關（`extract_event`）：
- **舊文復活**：來源頁前段最大年份 < 今年 → 丟（`stale_by_year`）。
- **誤萃取**：來源頁未提到品牌關鍵字、或未出現活動主題詞 → 丟（`page_mentions` / `theme_tokens`）。

---

## 4. 日期規則

- AI 只能填「內文明確寫出的活動日期」，**絕不可**把新聞發布日當活動日期；不明留空。
- 程式補抓日期（`extract_dates` + `apply_extracted_dates`）**只限可信網域**（`TRUSTED_DATE_DOMAINS`：官方／新聞稿／場館百貨頁），一般新聞內文常夾雜公告日、巡迴各城市日期 → 不自動補。
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
4. **商品保守規則**：`new_product` / `lottery` / `reservation` 不用「同城同日」或 fuzzy similarity 合併；同一天同店可能開賣多個不同系列。只用相同 URL、相同標題等強訊號合併。

**應併條件（任一成立）：**

- 同一已知場館（`VENUE_CANON`）且標題相似度 ≥ 0.4（一邊無日期時放寬到 ≥ 0.2）。
- **同城 + 場館字串相似(≥0.6) + 日期區間一致(差距 ≤3 天)** ← 多家媒體報導同一檔活動。
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
`_is_past`、`dedup_events`（含不同城/不同檔期不可併、同活動多媒體應併、線上 41 筆不誤併）。

新增／調整規則時，**同步在 `smoke_test.py` 補一個正例與一個「不可誤殺」反例**。
