# 每日自動抓取（Windows 工作排程器呼叫此檔）
$ErrorActionPreference = "Continue"
$dir = "C:\Users\USER\Documents\claude\chara-radar\scraper"
$py  = "C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe"

$logDir = Join-Path $dir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("scrape-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

$env:PYTHONIOENCODING = "utf-8"
Set-Location $dir

"" | Out-File -FilePath $log -Append -Encoding utf8
"========== 開始 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8
& $py scrape.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

# ── 自動部署到 GitHub Pages（手機可看）──────────────────────────────
# 每天跑完都寫入 last_updated.json（心跳：即使資料沒變，前端也能顯示「最後更新時間」），
# 連同有變動的 events.json 一起 commit + push，GitHub Pages 自動更新。
$repo = "C:\Users\USER\Documents\claude\chara-radar"

# 寫入最後更新時間（ISO 8601，含時區，前端用本地時間顯示）
$nowIso = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
'{ "updatedAt": "' + $nowIso + '" }' | Out-File -FilePath (Join-Path $repo "data\last_updated.json") -Encoding utf8 -NoNewline

& git -C $repo add data/events.json data/last_updated.json 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$staged = & git -C $repo diff --cached --name-only
if ($staged) {
  "部署：推送到 GitHub Pages（$($staged -join ', ')）..." | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo commit -m ("資料更新 " + (Get-Date -Format 'yyyy-MM-dd HH:mm')) 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo push origin main 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
} else {
  "部署：無任何變動，略過推送。" | Out-File -FilePath $log -Append -Encoding utf8
}

"========== 結束 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8

# 只保留最近 14 天 log
Get-ChildItem $logDir -Filter "scrape-*.log" | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 14 | Remove-Item -Force -ErrorAction SilentlyContinue
