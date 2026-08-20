---
name: cafe-best
description: >
  This skill should be used when the user runs "/cafe-best" or asks to
  "show the best Cafe QC stores", "which stores are performing best",
  "top performing coffee stores", or wants a ranked list of the
  best-performing stores by refund and rating quality for region_a or
  region_b, from an uploaded Cafe QC data export.
metadata:
  version: "0.1.0"
---

# /cafe-best — top-performing stores

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md` (locate
workbook, run `validate`, note unmatched stores and the date range)
before doing anything below.

## Elicit inputs

Ask (via `AskUserQuestion`, skipping anything already given):

1. **Region**: region_a or region_b.
2. **How many stores**: region_a → 3 or 5 (small master list).
   region_b → 5, 10, or 20.
3. **Timeframe**: confirm the auto-detected full range, or a sub-range —
   see the shared workflow doc.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py best \
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
volume. Lower composite score = better; note that explicitly since it
can read backwards.

**Low-volume stores get a handicap, not a free pass.** Stores are
bucketed into 3 volume tiers by units sold (terciles — `volume_tiers` in
the response gives each tier's units-sold range and store count):
Low/Medium/High. Before scoring, each store's refund rate and
rating-badness are both multiplied by its tier's handicap
(`volume_handicap_multiplier` — Low ×1.30, Medium ×1.00, High ×0.75),
then every eligible store in the region is normalized together on one
scale. A quiet store's refund rate/rating gets scaled to look worse and
a busy store's gets scaled to look better before comparison — so a
low-volume store needs a genuinely lower refund rate and higher rating
than a busy store to out-rank it, not just to be the best store within
its own small tier. Mention the store's volume tier in the table (or at
least footnote it) so it's clear the ranking already accounts for size.

**The sample floor (≥10 rated orders, ≥1,200 units sold) applies to
region_b best only — region_a best has no floor at all.** The engine's
`sample_floor_applied` field in the output tells you which applied for
this call; `excluded_stores` lists what was left out (for region_a that's
normally just stores with literally no matched sales/rating data, not a
floor cutoff). If fewer stores are eligible than the requested count
`N`, the table will just have fewer rows than asked for — say so
explicitly rather than padding it with ineligible stores.

Full scoring formula is in `${CLAUDE_PLUGIN_ROOT}/references/data-contract-and-scoring.md` if
the user asks how the score is computed.
