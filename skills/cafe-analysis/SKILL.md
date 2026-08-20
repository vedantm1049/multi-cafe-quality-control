---
name: cafe-analysis
description: >
  This skill should be used when the user runs "/cafe-analysis" or asks
  an open-ended question about store trends, categories, or freeform
  patterns — e.g. "why did refunds spike in week 3", "how does a category
  compare over time", "any interesting patterns in the data" — that isn't
  already covered by cafe-dashboard, cafe-worst-skus, cafe-action-points,
  cafe-best, or cafe-worst.
metadata:
  version: "0.1.0"
---

# /cafe-analysis — open-ended trend and category analysis

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md`
(locate workbook, run `validate`, note unmatched stores and the date
range) before doing anything below.

This command is deliberately open-ended — don't force the user's question
into the shape of `/cafe-best`, `/cafe-worst`, `/cafe-worst-skus`, or
`/cafe-action-points`. If their question is actually one of those
(e.g. "what's our worst store"), say so and point them at the right
command instead of improvising a parallel answer here.

## Elicit inputs

Ask for **region** (region_a or region_b — never combined) if not already
implied by the question. Timeframe defaults to the full uploaded range
unless the user's question implies otherwise (e.g. "in week 3" — work out
the actual dates from `validate`'s date range and pass them as
`--start`/`--end`).

## Data source

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py analysis \
  --file "<workbook path>" --region <region_a|region_b> \
  [--start YYYY-MM-DD --end YYYY-MM-DD]
```

Returns weekly refund-event counts, weekly average rating, category
breakdown, refund-reason breakdown, and refund amount totals/by-category
for the period. Use this as a starting point — feel free to re-slice the
underlying data yourself (via pandas in the sandbox, reading the same
workbook) for angles the `analysis` subcommand doesn't already cover
(e.g. day-of-week patterns, specific store deep-dives, correlating a
particular tag with a particular category). When you do, apply the same
store-identity resolution and alias corrections described in
`${CLAUDE_PLUGIN_ROOT}/references/data-contract-and-scoring.md` — don't
join on raw `ds_name`/`wh_code` without going through the engine's
resolution logic, or you'll silently drop or misattribute rows.

## Present

Output: **conversational**, in prose, with charts as needed (only when a
visual genuinely clarifies a trend — a single number doesn't need a
chart). Answer the specific question asked; don't pad with an unrelated
standard report structure.
