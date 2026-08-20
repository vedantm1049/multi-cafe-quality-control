---
name: cafe-dashboard
description: >
  This skill should be used when the user runs "/cafe-dashboard" or asks
  for a "Cafe QC dashboard", "store overview with complaint breakdown", or
  an interactive view of store-level refund and rating quality with a
  region toggle, from an uploaded Cafe QC data export.
metadata:
  version: "0.1.0"
---

# /cafe-dashboard — store-level + complaint-type dashboard

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md`
(locate workbook, run `validate`, note unmatched stores and the date
range) before doing anything below. Unlike the other commands, the
dashboard always covers **both regions** (with a toggle), so region is
not something to elicit here.

## Elicit inputs

Ask only about timeframe (via `AskUserQuestion`): confirm the
auto-detected full range, or a sub-range.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py dashboard \
  --file "<workbook path>" [--start YYYY-MM-DD --end YYYY-MM-DD]
```

This returns one JSON payload with a `regions.region_a` and
`regions.region_b` block. Each block's `stores` array covers **every
mapped store that has any scoreable data** (the dashboard runs with no
sample floor in either region — see
`${CLAUDE_PLUGIN_ROOT}/references/data-contract-and-scoring.md` for the
full best/worst floor rule, which is asymmetric and enforced only inside
`/cafe-best`/`/cafe-worst`, not here). Each store entry carries
`eligible` (has enough data to compute a score at all), `meets_best_floor`
(informational — would this store also qualify for region_b's
`/cafe-best` floor of ≥10 rated orders/≥1,200 units sold; not meaningful
for region_a since region_a never has a floor), `exclusion_reason`,
`composite_score` (null if not eligible), `volume_tier` (Low/Medium/High
volume, by units-sold terciles), `volume_handicap_multiplier` (the
per-tier scoring adjustment applied to this store's refund rate and
rating before normalization — Low ×1.30, Medium ×1.00, High ×0.75; null
if not eligible), `units_sold`, `gmv`, `avg_rating`, `rated_orders`,
`refund_events`, `refund_rate_pct`, a `worst_skus` list (top 5 by refund
count), `tag_polarity_breakdown`, and `top_complaints` (complaint tags
ranked by count) — plus the region-level `refund_reason_breakdown`,
`category_breakdown`, `tag_polarity_breakdown`, and `volume_tiers` (each
tier's units-sold range and store count).

## Build the dashboard

Output: **interactive HTML** (single self-contained file, following the
plugin's normal artifact/file-creation conventions — no external
dependencies beyond what's already permitted).

Include, with a region_a/region_b toggle control:

- A store-level table or bar chart sorted by composite score, covering
  every `eligible` store (label clearly that lower = better), including
  refund % (`refund_rate_pct` — refund count ÷ units sold, not the raw
  refund event count), units sold, avg rating, and **volume tier**
  (`volume_tier`) per store. Note in the table/copy that low-volume
  stores get a scoring handicap, not a free pass: each store's refund
  rate and rating-badness are multiplied by its tier's
  `volume_handicap_multiplier` (Low ×1.30, Medium ×1.00, High ×0.75)
  before every eligible store is normalized together on one scale — a
  quiet store needs genuinely better raw numbers than a busy store to
  earn the same score, not just to be the best within its own tier. For
  region_b, visually mark stores where `meets_best_floor` is false (e.g.
  a small marker/footnote) so it's clear which stores would be excluded
  from `/cafe-best` specifically even though they're shown here —
  region_a needs no such marker since it never has a floor.
- A complaint-type breakdown: bar or donut chart of tag polarity
  (compliment/complaint/needs-human-read) and a table of the individual
  complaint tags by frequency.
- A refund-reason breakdown (`adjustment_reason_code` counts), and a
  category breakdown.
- The confirmed date range covered, and a note listing any
  unmatched/excluded stores from `validate` so the dashboard is
  transparent about data coverage.
- **A location filter section**, separate from the ranked table above,
  covering every mapped store (including ones with no scoreable data at
  all — label those clearly rather than hiding them). On selecting a
  store, surface:
  1. Top metrics: units sold, GMV, avg rating, refund events, refund %.
  2. Worst SKUs by refund count (`worst_skus`, already sorted).
  3. Top complaint types (`top_complaints`, already sorted by count).

  For region_b, also note whether the selected store meets the
  `/cafe-best` floor (`meets_best_floor`), and show its volume tier
  (`volume_tier`) and handicap multiplier (`volume_handicap_multiplier`)
  if eligible so the user can see how its refund rate and rating were
  adjusted before scoring.

  Build the store picker as a `<select>` (or a searchable equivalent) —
  don't require the user to scroll a long table to find a store. Keep
  this section driven by client-side JS filtering over the embedded
  `stores` array; no server/backend calls.

After building the file, present it to the user rather than just
describing it.

## Live demo

This repo's `docs/dashboard.html` is a static, pre-baked version of this
exact skill's output, built from the bundled synthetic sample data and
hosted via GitHub Pages — useful as a working reference for the expected
layout/interactions, though it has no upload/re-run capability since
it's a fixed demo rather than a live engine run.
