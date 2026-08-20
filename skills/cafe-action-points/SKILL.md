---
name: cafe-action-points
description: >
  This skill should be used when the user runs "/cafe-action-points" or
  asks "what should stores fix first", "biggest refund cost drivers",
  "action points for ops", "prioritized store fixes", or wants a ranked
  list of store × defect-type combinations to address for region_a or
  region_b, from an uploaded Cafe QC data export.
metadata:
  version: "0.1.0"
---

# /cafe-action-points — prioritized store × defect fixes

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md`
(locate workbook, run `validate`, note unmatched stores and the date
range) before doing anything below.

## Elicit inputs

Ask (via `AskUserQuestion`, skipping anything already given):

1. **Region**: region_a or region_b.
2. **How many action points**: region_a → 5 or 10. region_b → 5, 10, or 20.
3. **Timeframe**: confirm the auto-detected full range, or a sub-range.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py action-points \
  --file "<workbook path>" --region <region_a|region_b> --n <N> \
  [--start YYYY-MM-DD --end YYYY-MM-DD]
```

## Present

Output: **inline ranked table** in chat, plus offer an export if the user
wants one.

One row per store × defect-type combo:

- Store, defect type, impact score, instance count
- Confirmation: "Confirmed by customer feedback" if
  `confirmed_by_customer_feedback` is true, otherwise "Refund data only"
- A one-line suggested fix you write based on the defect type (e.g.
  `frozen_melted` → check freezer/chiller temps and delivery bag icing;
  `wrong_item` → spot-check picking accuracy at that store;
  `item_missing` → audit packing checklist). Keep it concrete and
  specific to the defect type and store, not generic advice.

If a top-ranked row has a low `instance_count` (e.g. 1-2), say so
explicitly next to it — `impact_score` has no minimum-instance floor, so
a single expensive refund can outrank a more systemic but cheaper issue.
Don't silently present it as equally reliable.

Formula and the (inferred, not brief-specified) defect→tag correspondence
used for the confirmation flag are documented in
`${CLAUDE_PLUGIN_ROOT}/references/data-contract-and-scoring.md` — mention
that inference if a user asks how "confirmed" is determined.
