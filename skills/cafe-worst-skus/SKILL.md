---
name: cafe-worst-skus
description: >
  This skill should be used when the user runs "/cafe-worst-skus" or asks
  "which products get refunded most", "worst SKUs per store", "top
  refunded items", or wants a per-store breakdown of the most-refunded
  menu items for region_a or region_b, from an uploaded Cafe QC data
  export.
metadata:
  version: "0.1.0"
---

# /cafe-worst-skus — most-refunded SKUs per store

Follow the shared setup in `${CLAUDE_PLUGIN_ROOT}/references/running-the-engine.md`
(locate workbook, run `validate`, note unmatched stores and the date
range) before doing anything below.

## Elicit inputs

Ask (via `AskUserQuestion`, skipping anything already given):

1. **Region**: region_a or region_b.
2. **How many SKUs per store**: 3 or 5.
3. **Scope**: all stores with refund events, or one specific store (ask
   for the store name if they want to narrow it).
4. **Timeframe**: confirm the auto-detected full range, or a sub-range.

## Run

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py worst-skus \
  --file "<workbook path>" --region <region_a|region_b> --per-store-n <3|5> \
  [--store "<store name>"] [--start YYYY-MM-DD --end YYYY-MM-DD]
```

## Present

Output: **exportable sheet** (build it with the xlsx skill) — one row per
store × SKU, columns: store name, product title, refund count, store's
total refund events (for context). Order stores by total refund events
descending (the engine already sorts this way), then SKUs within each
store by refund count descending.

Always display `title` (the product name), never the raw `sku` hash —
the engine already resolves this, just don't substitute the hash back in
if you're re-deriving anything.

Give a brief inline summary in chat (top 2-3 standout products/stores)
in addition to producing the file, so the user gets the headline without
having to open it.
