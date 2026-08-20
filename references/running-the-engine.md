# Running the Cafe QC engine — shared workflow

Every `cafe-*` skill follows this same setup before doing its
command-specific work.

## 1. Locate the workbook

Find the most recently uploaded/attached `.xlsx` file that looks like a
Cafe QC export (8 sheets matching the data contract — see
`data-contract-and-scoring.md`). If the user hasn't attached one in this
conversation and none is available, ask them to upload the Cafe QC data
export before proceeding. Don't reuse a workbook from an earlier,
unrelated conversation without confirming it's the right one.

## 2. Validate

Run, in the sandbox shell:

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py validate --file "<path to workbook>"
```

- If this errors (missing sheet / missing column), show the user the
  error message directly and stop — don't try to guess a fix or silently
  drop a sheet.
- If it succeeds, note the `refund_unmatched_store_names`,
  `sales_unmatched`, and `rating_unmatched_wh_codes` for each region. If
  any are non-empty, flag them to the user as stores that couldn't be
  resolved this period (new store, new spelling variant) rather than
  silently excluding them.
- Note `date_range.overall_min` / `overall_max` — this is the
  auto-detected timeframe.

## 3. Elicit command inputs

Use `AskUserQuestion` (not free-text) for the choices each command needs,
per its own SKILL.md. Two elements are shared across every command:

- **Region**: region_a or region_b. Rankings/analysis are always run
  separately — never ask for or produce a combined region_a+region_b view.
- **Timeframe**: state the auto-detected date range back to the user
  (from `validate`'s `date_range`) and confirm it's the period they want.
  Only ask for a manual sub-range if they want less than the full
  uploaded period. If they give a sub-range, pass it as `--start
  YYYY-MM-DD --end YYYY-MM-DD` to the engine.

Skip an `AskUserQuestion` call for anything the user already specified in
their request (e.g. "run cafe-best for region_b, top 10" needs no further
elicitation).

## 4. Run the command and format output

Run the relevant engine subcommand (see each skill's SKILL.md for exact
flags) and format its JSON output per that command's specified output
type. Do not recompute or override any number the engine returns — it
implements the locked scoring formulas exactly; if a number looks
surprising, say so and show the underlying `refund_events` /
`units_sold` / `avg_rating` / `instance_count` fields so the user can see
why, rather than adjusting the figure yourself.

## Notes on interpreting the engine's JSON

- `wh_code` is the internal store identifier; always display `store_name`
  to the user, never the raw code (except as a secondary reference if
  helpful for cross-checking against the source file).
- Monetary `amount` values in the refund sheet are negative (they're
  refund/adjustment amounts). The engine's `severity_avg_refund_amount`
  and SKU-level figures are already reported as positive magnitudes.
- All dates in the workbook are naive timestamps in the store's local
  time; no timezone conversion is applied.
