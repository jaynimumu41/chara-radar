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
# 爬完若 events.json 有變動就 commit + push，GitHub Pages 自動更新。
$repo = "C:\Users\USER\Documents\claude\chara-radar"
$gitStatus = & git -C $repo status --porcelain data/events.json
if ($gitStatus) {
  "部署：events.json 有更新，推送到 GitHub Pages..." | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo add data/events.json 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo commit -m ("資料更新 " + (Get-Date -Format 'yyyy-MM-dd')) 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo push origin main 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
} else {
  "部署：events.json 無變動，略過推送。" | Out-File -FilePath $log -Append -Encoding utf8
}

"========== 結束 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8

# 只保留最近 14 天 log
Get-ChildItem $logDir -Filter "scrape-*.log" | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 14 | Remove-Item -Force -ErrorAction SilentlyContinue
