# Codex 交接：把每日資料驗證自動化（agent 級多方驗證）

> 寫給接手的 coding agent（codex）。你是冷啟動，沒有先前對話記憶，本檔自足。
> 目前目標品牌：Pokémon / Miffy / Chiikawa，地區：日本＋台灣。Sanrio 暫停，見第 13 節。
> **最高原則：準確 > 覆蓋。寧可漏，不可放錯／重複／過期／不符類型的資料。**

---

## 0. 你的任務（一句話）

建立一個**每天自動執行的 agent 驗證流程**，對 `data/events.json` 做「手動級多方查證」——
補日期、剔除已過期、合併重複、刪掉不符類型（見面會／純展覽／量販上架）——
**取代目前純 Python 排程做不到的語言級判斷**。Sanrio 暫停後，重點戰場是剩餘三品牌的「新聞段」資料。

為什麼需要你：見第 4 節。你要複製的驗證演算法：見第 5 節（最重要）。

---

## 1. 專案概況

- **目的**：自動蒐集 Pokémon／Miffy／Chiikawa 在日本＋台灣的快閃／特展／新品／限定餐飲情報，翻成中文，每天更新。
- **線上**：https://jaynimumu41.github.io/chara-radar/ （GitHub Pages，手機可看）
- **Repo**：`jaynimumu41/chara-radar`（**公開**，main 為 Pages 來源）
- **本機路徑**：`C:\Users\USER\Documents\claude\chara-radar`
- **目前狀態**：Sanrio 暫停後 `data/events.json` 共 39 筆（2026-06-10 修復後）。

---

## 2. 架構與資料流

兩條資料管線匯入 `data/events.json`：

| 管線 | 來源 | 用 AI? | 品質 | 程式 |
| -- | -- | -- | -- | -- |
| **結構化官方頁** | 吉伊卡哇 `chiikawa-info.jp/pus.html`、寶可夢 `oneheart65.net` 出張所排程＋台灣官方商品頁 `tw.portal-pokemon.com/goods/`、Miffy `dickbruna.jp/event/`＋Kiddy Land / miffy style 站內搜尋 | 否（regex+模板） | **已達手動品質** | `scraper/official_sources.py` |
| **新聞段** | PR TIMES 關鍵字、Google News RSS（日＋中） | 是（Gemini 萃取） | **品質不穩，你的主戰場** | `scraper/scrape.py` |

- 三麗鷗**沒有**可解析的結構化官方頁（`sanrio.co.jp` 503／JS 動態／REST 空，已確認不可行），且全靠新聞段＋Gemini，品質最弱；目前已暫停預設抓取與前端顯示。
- 前端純靜態：`index.html` + `js/app.js` + `css/app.css`，讀 `data/events.json`、`data/stores.json`（常設店手動清單）、`data/last_updated.json`（心跳）。
- **每日排程**：Windows 工作排程 `CharaRadar-DailyScrape` 每天 16:00 → `scraper/run_daily.ps1` → `python scrape.py` → 寫心跳 → git commit+push → GitHub Pages 自動重建。
- **Miffy 補漏**：`dickbruna.jp/event/` 不含所有 miffy style / Kiddy Land 店頭新品，已新增 `kiddyland.co.jp/?s=miffy` 結構化解析，零 Gemini 抓官方店頭活動。
- **台灣寶可夢補漏**：`tw.portal-pokemon.com/goods/` 已新增結構化解析，僅收內頁明確寫 `Pokémon Center TAIPEI` 登場／販售的近期商品；LINE 貼圖/主題、卡牌、遊戲、純線上授權商品過濾。官方 Instagram `pokemon_taiwan` 適合 agent 驗證輔助，不適合純 Python 每日抓取主來源。

---

## 3. 今天（2026-06-05）已完成 / 現況

- 去重已加**日期鐵則**（兩筆都有開始日且差 >14 天＝不同檔期不併）＋「同城+場館相似+日期一致」應併規則。
- 新增**彙整文過濾**（`is_roundup_title`：懶人包／總整理／行事曆／整理包）。
- 新增**藥妝雜訊**（`NOISE_KEYWORDS` 加 薬局/スギ薬局/マツキヨ/屈臣氏…）。
- **修了過期漏洞**（`_is_past`）：無 endDate 的活動原本永遠清不掉→現在依類型＋起始日自動判過期：
  活動型(popup/cafe/campaign) 起始日>30天或完全無日期＝過期；商品型(new_product/lottery/reservation)>60天或無日期＝過期；常設 store 保留。
- **離線測試** `scraper/smoke_test.py`：53 項全過，改規則前後必跑。
- 今天用手動多方驗證移除 8 筆問題資料（過期殘留／重複／見面會型／藥妝／籠統新品）。

⚠️ **但這正是問題所在**：上述「手動多方驗證」是「我（agent）用 WebSearch/WebFetch 一筆筆查」做的，**沒有進到每日排程**。明天排程又會抓進新的無日期／過期／重複資料。**你的任務就是把它自動化。**

---

## 4. 核心問題（為何純 Python 排程不夠）

- `scrape.py` 在排程裡是**純 Python**，只能呼叫 Gemini 萃取（看標題＋摘要）＋ regex 抓日期。
- Gemini **無法**：抓原頁跨來源交叉比對、判斷「這是去年舊活動」、判斷「見面會型不符四類」、判斷「跟既有某筆是同一活動」。
- 結果：新聞段曾持續產生 →
  1. **無日期殘留**：來源是一般新聞（非可信網域）→ 程式不補日期 → 無 endDate → 過期也清不掉（過期規則已緩解，但「現行但缺日期」仍無價值）。
  2. **過期混入**：搜尋摘要把舊活動講成今年（年份陷阱）。
  3. **重複**：同活動多家媒體不同標題，啟發式去重漏網。
  4. **類型不符**：見面會／握手會／LIVE SHOW／純展覽無商品被當活動收。
  5. **籠統低質**：「新商品續々登場」這類無地點無檔期綜述。

**注意**：結構化 3 品牌（吉伊卡哇/寶可夢/Miffy 官方排程）已達手動品質。
每日 agent 重點是剩餘 `sourceType == "official_social"` 且來源網域**非**可信清單的新聞段資料。

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
- 結構化來源（chiikawa-info / oneheart65 / tw.portal-pokemon / dickbruna / kiddyland）若日期完整 → **可信，略過**。
- 例外：`popup` / `cafe` / `campaign` 若有 `startDate` 但沒有 `endDate`，即使是結構化官方來源，也要進驗證隊列查是否其實有明確期間。

### 5.2 對每一筆，用 WebSearch + WebFetch 多方查證
1. **搜尋**：用「場館名 + 活動名 + 品牌日文名」當 query（品牌日文：ポケモン／ミッフィー／ちいかわ）。撈 2–3 個來源。
2. **優先信官方網域**：`prtimes.jp`、品牌官網、場館／百貨／outlet 單一活動頁。一般新聞當輔證。
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
python smoke_test.py      # 目前 53 項，exit 0 = 全過
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
- `git push` 已改用 `--porcelain --no-progress` 降低 PowerShell 5.1 把正常 push 訊息寫成 `NativeCommandError` 的 log 雜訊；若仍看到 push 訊息，先看是否有 `old..new main -> main`。
- git remote 內嵌 PAT 在本機 `.git/config`（非公開）。

---

## 10. 不要做的方向

- **不要**對 `sanrio.co.jp` 做結構化解析（503／JS／REST 空，已確認死路）；Sanrio 目前也不要重新加入預設抓取。
- **不要**在 403/503 時就放棄或下「資料不存在」結論 → 用 `r.jina.ai` 代理。
- **不要**信搜尋摘要的年份 → 抓原頁看明確發布日。
- **不要**放寬去重門檻硬合併（過度合併＝和重複一樣違反準確）。
- **不要**動結構化 3 品牌的既有流程（已達手動品質）——聚焦剩餘新聞段；Sanrio 先保持暫停。
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

---

## 12. Codex agent 驗證自動化（已建立）

- Codex app automation：`chararadar-agent-verify-daily`
- 名稱：`CharaRadar Agent Verify Daily`
- 觸發：每天 16:30（台灣時間語境），在 16:00 Windows/Python 爬蟲之後。
- 工作目錄：`C:\Users\USER\Documents\claude\chara-radar`
- 固定 SOP：`scraper/AGENT_VERIFY.md`
- 候選清單工具：`python scraper/agent_verify_candidates.py --format markdown`
- 每日 agent log：`scraper/logs/agent-verify-YYYY-MM-DD.md`（`scraper/logs/` 已 gitignore，不進公開 repo）

automation 的職責不是再跑一次爬蟲，而是依第 5 節對高風險筆做 WebSearch/WebFetch 多方查證，必要時修改
`data/events.json`、更新 `scraper/rejected.json` 防復活，跑 `smoke_test.py`，通過後 commit + push。

---

## 13. Sanrio 暫停狀態

- 2026-06-05 起 Sanrio 暫停，目的是節省 Gemini 與 agent 驗證時間，避免新聞段再污染。
- `scraper/scrape.py` 的 `DEFAULT_BRANDS` 只保留 `miffy`, `pokemon`, `chiikawa`。
- 前端品牌 filter 與 manifest 已移除 Sanrio；`data/events.json` 與 `data/stores.json` 也不保留 Sanrio 資料。
- `scraper/data_lint.py` 會把 Sanrio 殘留視為錯誤，避免排程或人工誤加回來。
- 如要恢復 Sanrio，需明確重開：恢復前端 filter、stores、`DEFAULT_BRANDS`，並先解決新聞段驗證成本。

---

## 14. 2026-06-05 Miffy 補源與排序修正

- 問題：使用者在社群/網站看到 Miffy 新活動，但 16:00 自動更新後網站未出現。原因是現有 Miffy 結構化來源只抓 `dickbruna.jp/event/`，而 Kiddy Land / miffy style 官方站內活動不一定會進 Google News RSS。
- 修正：`official_sources.fetch_miffy_events()` 追加 `fetch_kiddyland_miffy_events()`，解析 `https://www.kiddyland.co.jp/?s=miffy` 前 3 筆近期官方結果。新增來源會抓店頭新品、生日 Fair、原宿店受注商品；不花 Gemini。
- 防脆弱：Kiddy Land 先直抓 HTML，失敗再走 `r.jina.ai` reader；即使 `dickbruna.jp` 抓取失敗，也會繼續跑 Kiddy Land。
- 本次新增：Miffy `miffy style先行発売 マスコットビーンズコレクション`、`TENSHODO x miffy` ナインチェウォッチ、`miffy’s Birthday Fair2026`、`ミッフィーzakkaフェスタ 大丸札幌店`。
- 前端排序：`js/app.js` 改為有 `endDate` 的活動仍按最快結束排序；沒有 `endDate` 的活動排在後段，並依 `startDate` 排序，避免 Pokémon 等開始日資料亂跳。

## 15. 2026-06-09 Miffy 大阪フェルメール展誤刪修復

- 問題：`mi-53a257`「米飛兔擔任《真珠の耳飾りの少女》展大使」在 2026-06-07 agent 驗證被移除，理由是被判成純展覽大使新聞。
- 查證：Dick Bruna 官方頁 `https://dickbruna.jp/news/202605/46308/` 明確寫有展覽原創「真珠の耳飾りのミッフィー」玩偶與吊飾，符合「特展現場販售活動限定商品」。
- 修正：恢復 `mi-53a257`，改標題為 `Miffy x《真珠の耳飾りの少女》展原創商品`，`hasLimitedGoods=true`，來源改為 Dick Bruna 官方頁。
- 規則補強：`TRUSTED_DATE_DOMAINS` 加入 `dickbruna.jp`，`smoke_test.py` 加 Dick Bruna 官方可信日期來源測試。

## 16. 2026-06-10 Pokémon 台灣新品漏資料修復

- 問題：2026-06-10 自動流程跑完後，Pokémon 只剩 4 筆；使用者回報「之前還有其他 Pokémon 情報，少了好幾筆」。
- 查到原因：
  - 16:05 Python 抓取有跑完，16:36 agent 驗證也有跑完，但 agent 對台灣 Pokémon Center 新品採「找不到官方商品頁就刪」過嚴。
  - `scraper/scrape.py` 的 `processed.json` 快取曾把來源落到 Google 搜尋 placeholder 的標題也標記已處理，導致隔天不會重試。
  - `dedup_events` 第二階段 fuzzy 去重會把同一泛用店名（例如台北寶可夢中心）的不同日期新品誤併。
- 已恢復 5 筆台灣 Pokémon Center 新品：
  - `po-7a20f0`：台灣寶可夢中心6月新品與初音未來聯名（NOWnews，2026-06-06 開賣）
  - `po-4eaa69`：台北寶可夢中心 城都地區寶可夢大集結（NOWnews AMP，2026-05-23 開賣）
  - `po-481cb8`：台北寶可夢中心 Pikachu's Sweet Delivery、婚禮系列新品（Pokemon Hubs，2026-05-16 開賣）
  - `po-b32bd3`：寶可夢中心母親節新品開賣（NOWnews，2026-05-09 開賣）
  - `po-e6f4e9`：台北寶可夢中心 勞動節新品（NOWnews，2026-05-01 開賣）
- 已保留不恢復：
  - Pokopia 5 月商品：官方 Pokopia 活動期與 5 月商品說法不一致，待確認。
  - LoveChrome 聯名梳：官方為 EC / 授權通路，非明確 Pokémon Center 現場限定或門市新品。
  - 卡牌、遊戲、LINE 貼圖／主題、Pokemon GO、廣泛通路一番賞或食玩：仍不收。
- 規則修正：
  - `official_sources.py`：台灣 Pokémon 官方商品頁改為解析 Next.js embedded data；目前官方商品頁可讀，但近期頁面未提供上述 5 筆 Pokémon Center TAIPEI 新品。
  - `scrape.py`：若萃取結果的 `sourceUrl` 是 Google search placeholder，不再永久加入 `processed.json`；讓隔天可重試。
  - `scrape.py`：`new_product` / `lottery` / `reservation` 且地點是泛用店名時，不走第二階段 fuzzy 合併，避免不同系列新品誤併。
  - `rejected.json`：移除 `www.nownews.com/news/6811629`，避免已恢復資料再被黑名單擋掉。
- 驗證結果：`smoke_test.py` 53 項全過、`data_lint.py` 0 error / 0 warning、`verify_links.py` 39/39 OK。
- 之後 agent 判斷原則：
  - 台灣 Pokémon Center 新品若來源不是官方，但內文明確寫 `Pokémon Center TAIPEI` / 台灣寶可夢中心、實體店開賣日與商品內容，且沒有官方來源或其他來源反證，可暫留並列入高風險候選，不要只因官方商品頁找不到就刪。
  - 仍必須排除卡牌、遊戲、LINE、Pokemon GO、純線上、廣泛通路與非現場販售商品。
