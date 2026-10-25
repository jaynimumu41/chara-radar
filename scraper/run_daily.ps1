# Daily auto-scrape (called by Windows Task Scheduler).
# NOTE: keep this file ASCII-only. Non-ASCII text here breaks parsing under
# Windows PowerShell 5.1 (wrong encoding -> ParserError -> task fails silently).
$ErrorActionPreference = "Continue"
$dir = "C:\Users\USER\Documents\claude\chara-radar\scraper"
$repo = "C:\Users\USER\Documents\claude\chara-radar"
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

function Finish-Daily {
  param([int]$Code)
  ("DAILY EXIT CODE: " + $Code) | Out-File -FilePath $log -Append -Encoding utf8
  "========== END $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==========" | Out-File -FilePath $log -Append -Encoding utf8
  Get-ChildItem $logDir -Filter "scrape-*.log" | Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 | Remove-Item -Force -ErrorAction SilentlyContinue
  exit $Code
}

# Never mix an automated data commit with unfinished manual work or an
# out-of-date checkout. Fetch first so a different machine cannot be silently
# overwritten by this task.
$branch = (& git -C $repo branch --show-current 2>&1 | Out-String).Trim()
$gitCode = $LASTEXITCODE
if ($null -eq $gitCode) { $gitCode = 0 }
if ($gitCode -ne 0 -or $branch -ne "main") {
  ("PREFLIGHT: expected clean main branch, got '" + $branch + "'.") | Out-File -FilePath $log -Append -Encoding utf8
  Finish-Daily 1
}

$status = (& git -C $repo status --porcelain --untracked-files=no 2>&1 | Out-String).Trim()
$gitCode = $LASTEXITCODE
if ($null -eq $gitCode) { $gitCode = 0 }
if ($gitCode -ne 0 -or $status) {
  "PREFLIGHT: tracked worktree changes found; skip automated scrape." | Out-File -FilePath $log -Append -Encoding utf8
  if ($status) { $status | Out-File -FilePath $log -Append -Encoding utf8 }
  Finish-Daily 1
}

$fetchOutput = (& git -C $repo fetch --quiet origin main 2>&1 | Out-String).Trim()
$gitCode = $LASTEXITCODE
if ($null -eq $gitCode) { $gitCode = 0 }
if ($fetchOutput) { $fetchOutput | Out-File -FilePath $log -Append -Encoding utf8 }
if ($gitCode -ne 0) {
  "PREFLIGHT: git fetch failed." | Out-File -FilePath $log -Append -Encoding utf8
  Finish-Daily $gitCode
}

$head = (& git -C $repo rev-parse HEAD 2>&1 | Out-String).Trim()
$headCode = $LASTEXITCODE
$remote = (& git -C $repo rev-parse origin/main 2>&1 | Out-String).Trim()
$remoteCode = $LASTEXITCODE
if ($headCode -ne 0 -or $remoteCode -ne 0) {
  "PREFLIGHT: cannot resolve local or remote main." | Out-File -FilePath $log -Append -Encoding utf8
  Finish-Daily 1
}
if ($head -ne $remote) {
  $mergeBase = (& git -C $repo merge-base HEAD origin/main 2>&1 | Out-String).Trim()
  $gitCode = $LASTEXITCODE
  if ($gitCode -ne 0 -or $mergeBase -ne $head) {
    "PREFLIGHT: local main is ahead of or diverged from origin/main." | Out-File -FilePath $log -Append -Encoding utf8
    Finish-Daily 1
  }
  $mergeOutput = (& git -C $repo merge --ff-only origin/main 2>&1 | Out-String).Trim()
  $gitCode = $LASTEXITCODE
  if ($mergeOutput) { $mergeOutput | Out-File -FilePath $log -Append -Encoding utf8 }
  if ($gitCode -ne 0) {
    "PREFLIGHT: fast-forward to origin/main failed." | Out-File -FilePath $log -Append -Encoding utf8
    Finish-Daily $gitCode
  }
}
"PREFLIGHT: clean main synchronized with origin/main." | Out-File -FilePath $log -Append -Encoding utf8

# Keep the pre-run generated state. A failed scrape or validation must not
# poison tomorrow's run with partially written or invalid data.
$backupDir = Join-Path $env:TEMP ("chara-radar-" + [guid]::NewGuid().ToString("N"))
$stateBackups = @()
try {
  New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
  $stateFiles = @(
    (Join-Path $repo "data\events.json"),
    (Join-Path $repo "data\today_updates.json"),
    (Join-Path $dir "processed.json")
  )
  foreach ($path in $stateFiles) {
    $exists = Test-Path -LiteralPath $path
    $backup = Join-Path $backupDir ([IO.Path]::GetFileName($path))
    if ($exists) {
      Copy-Item -LiteralPath $path -Destination $backup -Force -ErrorAction Stop
    }
    $stateBackups += [PSCustomObject]@{ Path = $path; Backup = $backup; Existed = $exists }
  }
} catch {
  ("BACKUP: failed before scrape: " + $_.Exception.Message) | Out-File -FilePath $log -Append -Encoding utf8
  if (Test-Path -LiteralPath $backupDir) {
    Remove-Item -LiteralPath $backupDir -Recurse -Force -ErrorAction SilentlyContinue
  }
  Finish-Daily 1
}

function Clear-ScrapeBackups {
  foreach ($entry in $stateBackups) {
    Remove-Item -LiteralPath $entry.Backup -Force -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $backupDir -Force -ErrorAction SilentlyContinue
}

function Restore-ScrapeState {
  foreach ($entry in $stateBackups) {
    if ($entry.Existed) {
      Copy-Item -LiteralPath $entry.Backup -Destination $entry.Path -Force
    } else {
      Remove-Item -LiteralPath $entry.Path -Force -ErrorAction SilentlyContinue
    }
  }
  Clear-ScrapeBackups
  "ROLLBACK: restored pre-run generated files." | Out-File -FilePath $log -Append -Encoding utf8
}

& $py scrape.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
# Capture python's real exit code (Out-File is a cmdlet, does not touch $LASTEXITCODE).
# The later 'git push' writes progress to stderr which would otherwise make the task
# report failure (result=1) even on success; we report python's code instead.
$pyCode = $LASTEXITCODE
if ($null -eq $pyCode) { $pyCode = 0 }
("SCRAPE EXIT CODE: " + $pyCode) | Out-File -FilePath $log -Append -Encoding utf8
if ($pyCode -ne 0) {
  "DEPLOY: scrape failed, skip commit and push." | Out-File -FilePath $log -Append -Encoding utf8
  Restore-ScrapeState
  Finish-Daily $pyCode
}

# Block publication when deterministic regression or data checks fail.
foreach ($check in @("smoke_test.py", "data_lint.py")) {
  & $py $check 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  $checkCode = $LASTEXITCODE
  if ($null -eq $checkCode) { $checkCode = 0 }
  if ($checkCode -ne 0) {
    ("DEPLOY: " + $check + " failed, skip commit and push.") | Out-File -FilePath $log -Append -Encoding utf8
    Restore-ScrapeState
    Finish-Daily $checkCode
  }
}

Clear-ScrapeBackups

# ---- Auto-deploy to GitHub Pages (viewable on phone) ----------------------
# Every run writes last_updated.json (heartbeat: even if data is unchanged, the
# frontend can still show "last updated time"). Commit + push together with any
# changed events.json; GitHub Pages rebuilds automatically.
# Write last-updated timestamp (ISO 8601 with timezone; frontend shows local time)
$nowIso = Get-Date -Format "yyyy-MM-ddTHH:mm:sszzz"
$lastUpdatedJson = "{`n  `"updatedAt`": `"$nowIso`"`n}`n"
[IO.File]::WriteAllText((Join-Path $repo "data\last_updated.json"), $lastUpdatedJson, $utf8NoBom)

& git -C $repo add data/events.json data/today_updates.json data/last_updated.json 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
$gitCode = $LASTEXITCODE
if ($null -eq $gitCode) { $gitCode = 0 }
if ($gitCode -ne 0) {
  "DEPLOY: git add failed." | Out-File -FilePath $log -Append -Encoding utf8
  Finish-Daily $gitCode
}
$staged = & git -C $repo diff --cached --name-only
$gitCode = $LASTEXITCODE
if ($null -eq $gitCode) { $gitCode = 0 }
if ($gitCode -ne 0) {
  "DEPLOY: git diff failed." | Out-File -FilePath $log -Append -Encoding utf8
  Finish-Daily $gitCode
}
if ($staged) {
  "DEPLOY: pushing to GitHub Pages ($($staged -join ', '))..." | Out-File -FilePath $log -Append -Encoding utf8
  & git -C $repo commit -m ("data update " + (Get-Date -Format 'yyyy-MM-dd HH:mm')) 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  $gitCode = $LASTEXITCODE
  if ($null -eq $gitCode) { $gitCode = 0 }
  if ($gitCode -ne 0) {
    "DEPLOY: git commit failed." | Out-File -FilePath $log -Append -Encoding utf8
    Finish-Daily $gitCode
  }
  $gitCode = 1
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    ("DEPLOY: git push attempt " + $attempt + "/3.") | Out-File -FilePath $log -Append -Encoding utf8
    & git -C $repo push --porcelain --no-progress origin main 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    $gitCode = $LASTEXITCODE
    if ($null -eq $gitCode) { $gitCode = 0 }
    if ($gitCode -eq 0) { break }
    if ($attempt -lt 3) { Start-Sleep -Seconds 10 }
  }
  if ($gitCode -ne 0) {
    "DEPLOY: git push failed after 3 attempts." | Out-File -FilePath $log -Append -Encoding utf8
    Finish-Daily $gitCode
  }
  & $py verify_publish.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
  $publishCode = $LASTEXITCODE
  if ($null -eq $publishCode) { $publishCode = 0 }
  if ($publishCode -ne 0) {
    "DEPLOY: publish verification failed." | Out-File -FilePath $log -Append -Encoding utf8
    Finish-Daily $publishCode
  }
  "DEPLOY: publish verified." | Out-File -FilePath $log -Append -Encoding utf8
} else {
  "DEPLOY: nothing changed, skip push." | Out-File -FilePath $log -Append -Encoding utf8
}

# Every scrape, validation, git and publish step succeeded.
Finish-Daily 0
