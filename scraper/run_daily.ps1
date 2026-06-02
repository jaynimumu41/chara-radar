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
"========== 結束 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8

# 只保留最近 14 天 log
Get-ChildItem $logDir -Filter "scrape-*.log" | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 14 | Remove-Item -Force -ErrorAction SilentlyContinue
