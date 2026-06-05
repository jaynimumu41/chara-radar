# Codex 交接：把每日資料驗證自動化（agent 級多方驗證）

> 寫給接手的 coding agent（codex）。你是冷啟動，沒有先前對話記憶，本檔自足。
> 全程目標品牌：Pokémon / Miffy / Chiikawa / Sanrio，地區：日本＋台灣。
> **最高原則：準確 > 覆蓋。寧可漏，不可放錯／重複／過期／不符類型的資料。**

---

## 0. 你的任務（一句話）

建立一個**每天自動執行的 agent 驗證流程**，對 `data/events.json` 做「手動級多方查證」——
補日期、剔除已過期、合併重複、刪掉不符類型（見面會／純展覽／量販上架）——
**取代目前純 Python 排程做不到的語言級判斷**。重點戰場是「新聞段」資料，尤其三麗鷗。

為什麼需要你：見第 4 節。你要複製的驗證演算法：見第 5 節（最重要）。

---

## 1. 專案概況

- **目的**：自動蒐集四品牌在日本＋台灣的快閃／特展／新品／限定餐飲情報，翻成中文，每天更新。
- **線上**：https://jaynimumu41.github.io/chara-radar/ （GitHub Pages，手機可看）
- **Repo**：`jaynimumu41/chara-radar`（**公開**，main 為 Pages 來源）
- **本機路徑**：`C:\Users\USER\Documents\claude\chara-radar`
- **目前狀態**：`data/events.json` 共 54 筆；最新 commit `55fa7bc`。

---

## 2. 架構與資料流

兩條資料管線匯入 `data/events.json`：

| 管線 | 來源 | 用 AI? | 品質 | 程式 |
| -- | -- | -- | -- | -- |
| **結構化官方頁** | 吉伊卡哇 `chiikawa-info.jp/pus.html`、寶可夢 `oneheart65.net` 出張所排程、Miffy `dickbruna.jp/event/` | 否（regex+模板） | **已達手動品質** | `scraper/official_sources.py` |
| **新聞段** | PR TIMES 關鍵字、Google News RSS（日＋中） | 是（Gemini 萃取） | **品質不穩，你的主戰場** | `scraper/scrape.py` |

- 三麗鷗**沒有**可解析的結構化官方頁（`sanrio.co.jp` 503／JS 動態／REST 空，已確認不可行，**別再嘗試**），所以**全靠新聞段＋Gemini**，是品質最弱的一塊。
- 前端純靜態：`index.html` + `js/app.js` + `css/app.css`，讀 `data/events.json`、`data/stores.json`（常設店手動清單）、`data/last_updated.json`（心跳）。
- **每日排程**：Windows 工作排程 `CharaRadar-DailyScrape` 每天 16:00 → `scraper/run_daily.ps1` → `python scrape.py` → 寫心跳 → git commit+push → GitHub Pages 自動重建。

---

## 3. 今天（2026-06-05）已完成 / 現況

- 去重已加**日期鐵則**（兩筆都有開始日且差 >14 天＝不同檔期不併）＋「同城+場館相似+日期一致」應併規則。
- 新增**彙整文過濾**（`is_roundup_title`：懶人包／總整理／行事曆／整理包）。
- 新增**藥妝雜訊**（`NOISE_KEYWORDS` 加 薬局/スギ薬局/マツキヨ/屈臣氏…）。
- **修了過期漏洞**（`_is_past`）：無 endDate 的活動原本永遠清不掉→現在依類型＋起始日自動判過期：
  活動型(popup/cafe/campaign) 起始日>30天或完全無日期＝過期；商品型(new_product/lottery/reservation)>60天或無日期＝過期；常設 store 保留。
- **離線測試** `scraper/smoke_test.py`：35 項全過，改規則前後必跑。
- 今天用手動多方驗證移除 8 筆問題資料（過期殘留／重複／見面會型／藥妝／籠統新品）。

⚠️ **但這正是問題所在**：上述「手動多方驗證」是「我（agent）用 WebSearch/WebFetch 一筆筆查」做的，**沒有進到每日排程**。明天排程又會抓進新的無日期／過期／重複資料。**你的任務就是把它自動化。**

---

## 4. 核心問題（為何純 Python 排程不夠）

- `scrape.py` 在排程裡是**純 Python**，只能呼叫 Gemini 萃取（看標題＋摘要）＋ regex 抓日期。
- Gemini **無法**：抓原頁跨來源交叉比對、判斷「這是去年舊活動」、判斷「見面會型不符四類」、判斷「跟既有某筆是同一活動」。
- 結果：新聞段（尤其三麗鷗）持續產生 →
  1. **無日期殘留**：來源是一般新聞（非可信網域）→ 程式不補日期 → 無 endDate → 過期也清不掉（過期規則已緩解，但「現行但缺日期」仍無價值）。
  2. **過期混入**：搜尋摘要把舊活動講成今年（年份陷阱）。
  3. **重複**：同活動多家媒體不同標題，啟發式去重漏網。
  4. **類型不符**：見面會／握手會／LIVE SHOW／純展覽無商品被當活動收。
  5. **籠統低質**：「新商品續々登場」這類無地點無檔期綜述。

**注意**：結構化 3 品牌（吉伊卡哇/寶可夢/Miffy 官方排程）已達手動品質，**不是你的重點**。
重點是 `sourceType == "official_social"` 且來源網域**非**可信清單的新聞段資料，**三麗鷗最需要**。

---

## 5. 你要複製的「人工驗證演算法」（核心，最重要）

每天排程跑完後（建議 16:30），對 `data/events.json` 跑這套：

### 5.1 先挑出「需要驗證」的筆（其餘可略過省成本）
符合任一即需驗證：
- `endDate` 為空（無結束日）— 最高風險。
- `startDate` 與 `endDate` 都為空。
- 來源網域**不在**可信清單 `TRUSTED_DATE_DOMAINS`（見 `scrape.py`；日期沒被程式驗證過）。
- `type == "campaign"`（最容易混入展覽／見面會）。
- 標題籠統（含「新商品登場」「新作グッズ」「續々」「大集合」等無檔期訊號）。
- 結構化來源（`sourceType=="official_site"` 且來源是 chiikawa-info/oneheart65/dickbruna）→ **可信，略過**。

### 5.2 對每一筆，用 WebSearch + WebFetch 多方查證
1. **搜尋**：用「場館名 + 活動名 + 品牌日文名」當 query（品牌日文：ポケモン／ミッフィー／ちいかわ／サンリオ）。撈 2–3 個來源。
2. **優先信官方網域**：`sanrio.co.jp`、`prtimes.jp`、品牌官網、場館／百貨／outlet 單一活動頁。一般新聞當輔證。
3. **抓開催期間**：WebFetch 抓原頁，問「開催／販售期間的起訖日、地點、是否販售限定商品」。
   - 一頁常有多個日期（發布日、集章日、開催期間）→ **只取主活動的開催／販售期間**那個區間。
4. **判定並改寫 events.json**：
   - 抓到明確起訖 → 補 `startDate`/`endDate`。
   - `endDate < 今天` → **已過期，移除**。
   - **查無此活動 / 是去年舊活動**（⚠️年份陷阱，見 5.3）→ 移除。
   - **見面會／握手會／LIVE SHOW／純展覽無商品販售 / 量販藥妝上架** → 不符四類（見 6.2）→ 移除。
   - **與既有某筆同一活動**（同品牌＋同場館＋同檔期）→ 合併（保留資料較完整者），刪重複。
5. **防復活**：移除「未來才開始、新聞稿會一直被抓到」的筆時，把其來源 URL 的可辨識片段加進 `scraper/rejected.json` 的 `url_contains`（見該檔格式），否則明天又被抓回。
   - 注意：純「過期」的不用加（freshness 45 天會自然擋）；「未來見面會型／壞站」才要加。

### 5.3 ⚠️ 年份陷阱（務必）
搜尋摘要常把**舊活動講成今年**（例：福岡某咖啡廳 2016 舊頁被講成 2026）。
**一定要抓原頁看明確發布日／活動年份**，別信摘要年份。頁尾 ©2026 是當前年非活動年。
X(twitter) 貼文用 snowflake ID 可推發文年。

### 5.4 ⚠️ 403／被擋不可放棄
官方站常擋資料中心 IP（403/503）。被擋時改用 reader 代理 `https://r.jina.ai/<原URL>`（回純文字 markdown，含標題/內文/日期，足夠判讀）。`scraper/verify_links.py` 的 `check_url`/`fetch_html` 已內建此 fallback，可參考。

---

## 6. 現有守則（不可破壞）

### 6.1 去重鐵則（`scrape.py` 的 `dedup_events`）
- **城市鐵則**：兩筆城市都有值且不同 → 不同活動，即使同 URL 也不併。
- **日期鐵則**：兩筆都有開始日且差 >14 天 → 不同檔期不併（同一真實 URL 為例外）。
- **會場鐵則**：兩筆都有地點、非同一已知場館、字串相似度 <0.5 → 不同場次不併。
- **多店同步同活動**（如全台4店）→ 列一筆，`city` 留空，`locationName` 寫「全台N店同步（…）」。

### 6.2 採用的四類（其餘一律不收）
1. 快閃店／POP UP　2. 新商品發售（實體店）　3. 活動限定商品（特展/聯名/週年慶現場販售）　4. 限定餐飲（主題咖啡廳/限定菜單）。
**一律不收**：體育賽事/路跑/棒球主題日、見面會/握手會/拍照打卡/LIVE SHOW/遊行本身、懶人包總整理、超商/藥妝/百元店/量販聯名小商品、食品飲料上架、扭蛋盲盒、媒體動畫聲優手遊消息、純線上/再販、海外（非日台）。

### 6.3 日期政策
- 只填「內文明確寫出的活動日期」，**絕不可拿新聞發布日當活動日**；不明留空。
- 程式自動補日期只限可信網域（`TRUSTED_DATE_DOMAINS`）——**你（agent）可以突破這限制**，因為你會抓原頁多方查證；但同樣要遵守「年份陷阱」「只取主活動區間」。

### 6.4 events.json 欄位格式（每筆）
`brand`(小寫) / `title`(品牌名留英文其餘繁中) / `type`(popup|new_product|campaign|store|cafe|lottery|reservation) / `country`(JP|TW) / `city`(英文如 Tokyo/Osaka/Taipei，不確定留空) / `locationName` / `startDate`(YYYY-MM-DD) / `endDate` / `summaryZh`(繁中) / `needReservation` / `hasLimitedGoods` / `tags` / `id` / `sourceType` / `createdAt` / `sourceUrl` / `sourceTitle`。

---

## 7. 建議實作（agent 版排程）

- **觸發**：每天 16:30（純 Python 排程 16:00 跑完之後）。可用 codex 自己的排程/cron 機制。
- **流程**：讀 `data/events.json` → 跑第 5 節演算法 → 改寫 events.json →
  跑 `python scraper/smoke_test.py` 確認不破壞（exit 0）→ `git add data/events.json scraper/rejected.json` → commit → `git push origin main`。
- **產出 log**：記錄每筆「驗證了什麼、補了什麼日期、移除了什麼及原因」，方便人工事後抽查。
- **保守**：不確定的筆**寧可移除也不放錯**（準確>覆蓋）。合併時別把不同活動硬湊（過度合併和重複一樣糟）。
- **commit 訊息**結尾不必加 Claude 署名（你是 codex）；但**保留人類可讀的中文說明**。

---

## 8. 測試（每次改動必跑）

```bash
cd scraper
set PYTHONIOENCODING=utf-8
python smoke_test.py      # 目前 35 項，exit 0 = 全過
```
涵蓋：城市/場館/年份/彙整/日期擷取/過期判定/去重。
**你新增任何規則，務必同步補一個正例＋一個「不可誤殺」反例。**
另有 `python verify_links.py` 可稽核所有 sourceUrl 連得過去（不花配額）。

---

## 9. 環境 / 雷區

- **無 node**；Python 3.14：`C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe`。
- 終端 cp950，跑 py 前設 `PYTHONIOENCODING=utf-8`，否則中文輸出爆。
- **金鑰**：`scraper/.env` 有 3 把 Gemini key（`GEMINI_API_KEY` / `_2` / `_3`）。**已 gitignore，repo 公開，絕不可 commit `.env`**。
- Gemini 免費版每模型每天配額極低（~20 req/day/key），靠多 key 輪替；你的 agent 驗證**不該用 Gemini**，用你自己的搜尋/抓取能力。
- `scraper/run_daily.ps1` **必須 ASCII-only**（PowerShell 5.1 編碼雷，非 ASCII 會 ParserError 靜默失敗）。
- `git push` 的 stderr 進度訊息是正常雜訊，看末行 `old..new main -> main` 才是真結果。
- git remote 內嵌 PAT 在本機 `.git/config`（非公開）。

---

## 10. 不要做的方向

- **不要**對 `sanrio.co.jp` 做結構化解析（503／JS／REST 空，已確認死路）。
- **不要**在 403/503 時就放棄或下「資料不存在」結論 → 用 `r.jina.ai` 代理。
- **不要**信搜尋摘要的年份 → 抓原頁看明確發布日。
- **不要**放寬去重門檻硬合併（過度合併＝和重複一樣違反準確）。
- **不要**動結構化 3 品牌的既有流程（已達手動品質）——聚焦新聞段／三麗鷗。
- **不要**把「新聞發布日」當活動日期。

---

## 11. 關鍵檔案地圖

- `scraper/scrape.py` — 主程式（RSS、Gemini 萃取、去重、過期、結構化整合、所有守則）。
- `scraper/official_sources.py` — 結構化官方頁解析（零 AI）＋ PR TIMES。
- `scraper/verify_links.py` — 連結驗證＋reader 代理 fallback（`check_url`/`fetch_html`）。
- `scraper/rejected.json` — 壞資料黑名單（`url_contains`/`title_contains`）。
- `scraper/processed.json` — 已送 AI 的標題（省配額，自動維護）。
- `scraper/run_daily.ps1` — 每日排程腳本（ASCII-only）。
- `scraper/smoke_test.py` — 離線回歸測試。
- `scraper/RULES.md` — 篩選與去重規則總覽（人類可讀版）。
- `data/events.json` — 主資料（你讀寫的對象）。
- `data/stores.json` — 常設店手動清單（不經爬蟲）。
