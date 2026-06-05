# Daily Agent Verification SOP

This is the fixed workflow for the Codex automation that runs after the normal
Python scraper. The scraper collects candidates; the agent performs the
language-level judgement that Python/Gemini cannot safely do.

Core rule: accuracy over coverage. It is better to remove a doubtful record than
to keep a wrong, duplicate, expired, or out-of-scope record.

Sanrio is paused for now to save verification time. The active brands are
Pokemon, Miffy, and Chiikawa. Do not add Sanrio records back during the daily
automation unless a human explicitly re-enables the brand.

## Schedule

- Run daily at 16:30 Asia/Taipei, after `scraper/run_daily.ps1` finishes its
  16:00 scrape and push.
- Work in `C:\Users\USER\Documents\claude\chara-radar`.
- Do not use Gemini or `scraper/.env`; use Codex web search/fetch capability.

## Inputs

Read these before editing:

1. `CODEX_HANDOFF.md`, especially section 5.
2. `scraper/RULES.md`.
3. Preflight and data lint:

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\agent_preflight.py
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\data_lint.py
```

Stop if preflight or lint fails; report the reason instead of editing old or
dirty data.

4. Candidate list:

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\agent_verify_candidates.py --format markdown
```

The candidate script is only a triage tool. It does not prove correctness and it
does not replace web verification.

## Verification Loop

For each high-risk candidate:

1. Search with the suggested query, then refine with the venue, Japanese brand
   name, and original source title when needed.
2. Prefer official/authoritative pages: brand official pages, `prtimes.jp`,
   venue, department store, mall, outlet, or single-event pages.
3. Fetch the original page. If blocked by 403/503/429 or the page is JS-only,
   fetch `https://r.jina.ai/<original URL>` before deciding.
4. Extract only the main event/sale period. Never use the news publication date,
   page footer year, unrelated stamp-rally dates, or search-result snippets.
5. Confirm all of these:
   - Brand is one of Pokemon, Miffy, Chiikawa.
   - Location is in Japan or Taiwan.
   - It is one of the accepted four classes: popup/store event, physical-store
     new product sale, event-limited goods, or limited cafe/menu.
   - The record is not expired on the run date.
   - It is not a duplicate of an existing event with the same brand, venue, and
     event period.

Remove records that are expired, old-year traps, unverifiable, out of scope,
duplicate, vague roundup/new-product summaries, meet-and-greet/photo-op/live
show only, sports events, convenience/drugstore/mass-retail items, capsule toys,
food/drink shelf launches, online-only sales, resale news, or non-Japan/Taiwan
items.

When a removed record is likely to come back tomorrow because the source article
is still fresh and the problem is type/source quality rather than ordinary
expiry, add a stable URL fragment to `scraper/rejected.json` under
`url_contains`.

## Edits

- Edit only the necessary files, usually `data/events.json` and
  `scraper/rejected.json`.
- Preserve event field names and JSON formatting.
- Do not modify the structured official-source pipeline for Chiikawa, Pokemon,
  or Miffy unless a separate task explicitly asks for it.
- Write a local daily audit note to
  `scraper/logs/agent-verify-YYYY-MM-DD.md`. This directory is gitignored, so do
  not stage the log. Include:
  - candidates reviewed;
  - sources checked;
  - dates corrected;
  - records removed and exact reasons;
  - rejected fragments added;
  - uncertainties left for human review.

## Validation

After edits:

```powershell
$env:PYTHONIOENCODING='utf-8'
Set-Location scraper
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' smoke_test.py
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' data_lint.py
```

Run `python verify_links.py` if any `sourceUrl` is changed.

If files changed and tests pass, commit and push:

```powershell
git add data/events.json scraper/rejected.json
git commit -m "agent verify events YYYY-MM-DD"
git push origin main
```

If nothing changed, leave the repo clean and summarize the checked candidates in
the automation result.
