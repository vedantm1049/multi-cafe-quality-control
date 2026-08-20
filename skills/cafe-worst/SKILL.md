---
name: cafe-worst
description: >
  This skill should be used when the user runs "/cafe-worst" or asks to
  "show the worst Cafe QC stores", "which stores are underperforming",
  "bottom coffee stores", or wants a ranked list of the worst-performing
  stores by refund and rating quality for region_a or region_b, from an
  uploaded Cafe QC data export.
metadata:
  version: "0.1.0"
---

# /cafe-worst — worst-performing stores

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md`
(locate workbook, run `validate`, note unmatched stores and the date
range) before doing anything below.

## Elicit inputs

Ask (via `AskUserQuestion`, skipping anything already given):

1. **Region**: region_a or region_b.
2. **How many stores**: region_a → 3 or 5. region_b → 5, 10, or 20.
3. **Timeframe**: confirm the auto-detected full range, or a sub-range —
   see the shared workflow doc.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py worst \
  --file "<workbook path>" --region <region_a|region_b> --n <N> \
  [--start YYYY-MM-DD --end YYYY-MM-DD]
```

## Present

Output: **inline ranked table** in chat (plus offer to export to a sheet
if the user wants one — use the xlsx skill for that if requested).

Columns: rank, store name, composite score, avg rating, **refund %**
(`refund_rate_pct` from the engine — refund count ÷ units sold,
expressed as a percentage), units sold, **volume tier** (`volume_tier`
— Low/Medium/High volume). Show refund % rather than the raw refund
event count — it's the normalized figure the composite score is
actually built on, so it's more comparable across stores of different
volume. Higher composite score = worse; note that explicitly. Treat this
as a list to investigate, not a scoreboard to shame — frame it as
"stores to prioritize" in your summary.

**Low-volume stores get a handicap, not a free pass.** Stores are
bucketed into 3 volume tiers by units sold (terciles — `volume_tiers` in
the response gives each tier's units-sold range and store count):
Low/Medium/High. Before scoring, each store's refund rate and
rating-badness are both multiplied by its tier's handicap
(`volume_handicap_multiplier` — Low ×1.30, Medium ×1.00, High ×0.75),
then every eligible store in the region is normalized together on one
scale. In practice this means a quiet store's raw refund %/rating gets
scaled to look worse for scoring purposes, so it takes genuinely poor
performance — not just being small — to land on the worst list; a busy
store's raw numbers get scaled to look better, so it takes genuinely
worse performance for a busy store to appear here too. Worth a line in
your summary if the ranking order looks surprising next to the raw
refund % column, since the score isn't the raw number.

**`/cafe-worst` has no sample floor in either region** — a low-volume
store having quality problems is exactly what "worst" should surface,
not hide. `excluded_stores` will normally only list stores with
literally no matched sales/rating data (unscoreable), not a floor
cutoff. (Note the asymmetry: `/cafe-best` for region_b *does* apply a
floor of ≥10 rated orders / ≥1,200 units sold — so a store can appear in
`/cafe-worst` without being eligible for `/cafe-best`. That's expected;
mention it if a user asks why a store's on one list but not the other.)
If fewer stores are eligible than the requested count `N`, the table
will just have fewer rows than asked for.

Full scoring formula is in `${CLAUDE_PLUGIN_ROOT}/references/data-contract-and-scoring.md`
if the user asks how the score is computed.
