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

5. Chiikawa official homepage subpage audit:

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\audit_chiikawa_subpages.py --format markdown
```

Treat `needs_review` rows as official-source coverage gaps. A high-risk row
means the page appears to contain dates, venue/location signals, and collectible
or store/cafe signals, so check it before concluding the daily data is complete.
Do not add it automatically; either add a structured parser, mark it explicitly
out of scope in the auditor, or leave it as an open risk in the daily note.

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

Chiikawa official structured sources include `chiikawa-info.jp/pus.html`,
`chiikawa-info.jp/` homepage cards, `chiikawa-info.jp/p26/mck_scpus/index.html`
movie POP UP venue schedules, and `chiikawamogumogu.jp` shop pages.
Do not assume the Chiikawa official index is fully covered: use
`audit_chiikawa_subpages.py` to find any `p26/.../index.html` page not currently
represented by `events.json`, then audit whether `official_sources.py` already
parses it or add a structured parser.
Permanent or semi-permanent shop openings such as `ちいかわベビーカステラ` should
use `type=store`; an empty `endDate` is expected when the source presents an
opening date rather than a limited run.

Taiwan Pokemon Center goods need special handling. Official goods pages are
often incomplete for Taiwan, while the first public signal may be a news article
or an official social post. Do not remove a Taiwan Pokemon Center `new_product`
record only because `tw.portal-pokemon.com/goods/` has no matching page. Keep it
when the source text explicitly contains all of these:

- `台灣寶可夢中心`, `台北寶可夢中心`, or `Pokémon Center TAIPEI`;
- a concrete in-store sale/restock date;
- a concrete product line or product list;
- no conflicting official source and no out-of-scope category such as cards,
  games, LINE, Pokemon GO, online-only, or broad retail.

Such records remain high-risk if the source is secondary media, but high-risk
means "review again and record reputation", not "delete by default". Do not add
these source URLs to `scraper/rejected.json` unless the article itself is
wrong, duplicate, expired, out of scope, or contradicted.

Remove records that are expired, old-year traps, unverifiable, out of scope,
duplicate, vague roundup/new-product summaries, meet-and-greet/photo-op/live
show only, sports events, convenience/drugstore/mass-retail items, capsule toys,
food/drink shelf launches, online-only sales, resale news, or non-Japan/Taiwan
items.

## Source Reputation Feedback

`scraper/agent_verify_candidates.py` enriches each candidate with the source
reputation tier and the minimum corroboration needed. The reputation file is
`data/source_reputation.json`; it is intentionally separate from `events.json`.

After a candidate is verified, update the source memory:

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\source_reputation.py record `
  --url "https://example.com/source-article" `
  --outcome confirmed `
  --brand pokemon `
  --type new_product `
  --country TW `
  --event-id po-example `
  --evidence-count 2 `
  --notes "Matched original article plus one independent social/venue signal"
```

Use `confirmed` only when the source's claim is kept or corrected and kept.
Use `rejected` when the source claim caused a wrong, duplicate, expired, or
out-of-scope record. Use `uncertain` when the record is left pending or needs
human review. `evidence-count` means independent corroborating signals found
beyond the original source, not search snippets.

Do not promote a whole domain manually. Let repeated outcomes move it: a source
can become trusted for Pokemon/TW/new_product over time while staying unproven
for other brands or event types.

When a removed record is likely to come back tomorrow because the source article
is still fresh and the problem is type/source quality rather than ordinary
expiry, add a stable URL fragment to `scraper/rejected.json` under
`url_contains`.

## Edits

- Edit only the necessary files, usually `data/events.json` and
  `scraper/rejected.json`; when verification changes source trust, also edit
  `data/source_reputation.json` via `scraper/source_reputation.py record`.
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
Set-Location 'C:\Users\USER\Documents\claude\chara-radar'
git add data/events.json scraper/rejected.json data/source_reputation.json
git commit -m "agent verify events YYYY-MM-DD"
git push --porcelain --no-progress origin main
& 'C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe' scraper\verify_publish.py
```

Do not report success until `verify_publish.py` prints `publish_ok=true`. If the
remote HEAD differs from local HEAD, push again. If GitHub Pages is stale, keep
polling via `verify_publish.py`; report a publish failure only after the script
times out.

If nothing changed, leave the repo clean and summarize the checked candidates in
the automation result.
