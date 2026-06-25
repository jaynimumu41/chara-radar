# Daily auto-scrape (called by Windows Task Scheduler).
# NOTE: keep this file ASCII-only. Non-ASCII text here breaks parsing under
# Windows PowerShell 5.1 (wrong encoding -> ParserError -> task fails silently).
$ErrorActionPreference = "Continue"
$dir = "C:\Users\USER\Documents\claude\chara-radar\scraper"
$py  = "C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe"

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom
& "$env:SystemRoot\System32\chcp.com" 65001 > $null

$logDir = Join-Path $dir "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("scrape-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
Set-Location $dir

"" | Out-File -FilePath $log -Append -Encoding utf8
"========== START $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8
& $py scrape.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
# Capture python's real exit code (Out-File is a cmdlet, does not touch $LASTEXITCODE).
# The later 'git push' writes progress to stderr which would otherwise make the task
# report failure (result=1) even on success; we report python's code instead.
$pyCode = $LASTEXITCODE
if ($null -eq $pyCode) { $pyCode = 0 }
("SCRAPE EXIT CODE: " + $pyCode) | Out-File -FilePath $log -Append -Encoding utf8
if ($pyCode -ne 0) {
  "DEPLOY: scrape failed, skip commit and push." | Out-File -FilePath $log -Append -Encoding utf8
  "========== END $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8
  exit $pyCode
}

# ---- Auto-deploy to GitHub Pages (viewable on phone) ----------------------
# Every run writes last_updated.json (heartbeat: even if data is unchanged, the
# frontend can still show "last updated time"). Commit + push together with any
# changed events.json; GitHub Pages rebuilds automatically.
$repo = "C:\Users\USER\Documents\claude\chara-radar"

# Write last-updated timestamp (ISO 8601 with timezone; frontend shows local time)
$nowIso = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
'{ "updatedAt": "' + $nowIso + '" }' | Out-File -FilePath (Join-Path $repo "data\last_updated.json") -Encoding utf8 -NoNewline

& git -C $repo add data/events.json data/today_updates.json data/last_updated.json 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$staged = & git -C $repo diff --cached --name-only
if ($staged) {
  "DEPLOY: pushing to GitHub Pages ($($staged -join ', '))..." | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo commit -m ("data update " + (Get-Date -Format 'yyyy-MM-dd HH:mm')) 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo push --porcelain --no-progress origin main 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
} else {
  "DEPLOY: nothing changed, skip push." | Out-File -FilePath $log -Append -Encoding utf8
}

"========== END $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8

# Keep only the latest 14 daily logs
Get-ChildItem $logDir -Filter "scrape-*.log" | Sort-Object LastWriteTime -Descending |
  Select-Object -Skip 14 | Remove-Item -Force -ErrorAction SilentlyContinue

# Report python's exit code as the task result (ignore git-push stderr noise),
# so result=0 means a real success and non-zero means a real scrape failure.
exit $pyCode
