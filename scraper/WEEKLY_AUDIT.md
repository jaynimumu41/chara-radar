# Weekly Deep Coverage Audit

This Sunday audit complements the daily scraper. It looks back seven days for
items delayed by API limits, missed by RSS, or published in a new official page
layout. Accuracy remains more important than coverage.

## Scope

- Active brands: Pokemon, Miffy, and Chiikawa.
- Countries: Japan and Taiwan only.
- Accepted classes: physical popup/store activity, physical-store product
  launch, event-limited goods, and limited cafe/menu.
- Sanrio remains paused.
- Do not use Gemini or `scraper/.env`. Use Codex web search/fetch and the
  deterministic official audits.

## Workflow

1. Run `agent_preflight.py` and `data_lint.py`. Stop on stale/dirty/failed data.
2. Read `data/health.json` and report pending articles, retryable extraction
   failures, source failures, key rotations, and brands that reached the cap.
3. Search the previous seven calendar days in Japanese and Traditional Chinese
   for each active brand. Prefer official brand, venue, mall, department-store,
   and PR TIMES pages. Search secondary media only as discovery evidence.
4. Run all official event and permanent-store audits with
   `--fail-on-review`. Use `audit_similar_events.py --fail-on-review` before and
   after edits.
5. Compare every proposed addition with current events by brand, concrete
   venue, overlapping period, product/concept, and source URL. A rewritten
   headline or different media type is not a separate event.
6. Do not add uncertain rows. Record unresolved evidence in the weekly task
   report and leave formal data unchanged.
7. If public data changes, run `smoke_test.py`, the similarity gate,
   `write_health.py`, `data_lint.py`, and `verify_links.py` when URLs changed.
   Commit and push `main`, then require `verify_publish.py` to print
   `publish_ok=true`.
8. If nothing changes, leave the repository clean and report the exact sources,
   date range, and health/backlog values checked.

The audit must not increase `MAX_PER_BRAND` or mark deferred article titles as
processed merely to clear a backlog. Deferred and transiently failed items stay
eligible for later daily runs.
