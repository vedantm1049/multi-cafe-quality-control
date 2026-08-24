# Cafe QC data contract, store identity, and scoring formulas

This is the shared reference for every `cafe-*` skill in this plugin. All
of the logic below is implemented in `${CLAUDE_PLUGIN_ROOT}/scripts/cafe_qc_engine.py`
— skills should call that script rather than re-deriving any of this by
hand, so results stay consistent across commands and refreshes.

The network is modeled as two regions, `region_a` and `region_b`, each
with its own independent store master list, mapping sheet, and volume
profile — this mirrors how a real multi-market retail QC export is
usually shaped (two markets of very different size and store count) without
naming a specific brand or geography. Swap in your own region names/sheet
names if you adapt this for a real dataset.

## Locked data contract

Every upload must be an `.xlsx` workbook with these 8 sheets:

| Sheet | Key columns |
|---|---|
| `refund_region_a` / `refund_region_b` | `order_nr`, `adjustment_reason_code`, `sku`, `title`, `amount`, `order_created_timestamp`, `category`, `ds_name` |
| `rating_region_a` / `rating_region_b` | `order_nr`, `all_sku`, `brand_code`, `comcat`, `created_at`, `rating`, `tags`, `wh_code` |
| `mapping_region_a` / `mapping_region_b` | `Wh code`, `Lock code`, `Store name`, `Store alias` (+ `DS code`, `Store alias.1` for region_b only) |
| `sales_region_a` / `sales_region_b` | `wh`, `wh_name`, `units_sold`, `gmv` |

The engine's `validate` command checks the uploaded file against this
contract and returns a clear error (missing sheet / missing column) rather
than guessing. Always run `validate` first and surface any error to the
user verbatim — do not attempt to patch a malformed upload yourself.

All 8 sheets are expected to be re-uploaded fresh every time a command
runs (weekly or monthly) — there is no reliance on a prior period's
mapping or sales data.

## Store identity resolution

Three identifiers exist across the sheets: `ds_name` (refund), `wh_code`
(rating), and `DS code` (region_b sales only — region_a sales joins by
name). The mapping sheet bridges them. The engine resolves all three
automatically:

- **Ratings → mapping:** exact match on `wh_code` against the mapping
  sheet's `Wh code` column. Rating rows whose `wh_code` has no mapping
  match are not network locations and are dropped.
- **Refund → mapping:** match `ds_name` against the mapping sheet's
  `Store name` / `Store alias` / `Store alias.1` columns, using
  case/hyphen/whitespace-insensitive normalization plus a small hardcoded
  list of known spelling corrections. Known non-live locations can be
  excluded explicitly rather than silently treated as unmatched.
- **Sales → mapping:** region_b joins by `DS code` (exact). region_a joins
  by name (`wh_name` against `Store name`/`Store alias`, same
  normalization).

If a future upload introduces a new store or spelling variant that the
normalization + hardcoded fixes do not resolve, the engine reports it
under `refund_unmatched_store_names` / `sales_unmatched` /
`rating_unmatched_wh_codes` in the `validate` output rather than silently
guessing.

## Minimum sample floor — applied asymmetrically

The floor is fewer than 10 rated orders OR fewer than 1,200 units sold
in the period. It is **not** applied uniformly — this is a locked,
explicit decision (`floor_applies()` in the engine):

| | Floor applied? |
|---|---|
| region_a best | No |
| region_a worst | No |
| region_b best | **Yes** |
| region_b worst | No |

The units-sold floor is deliberate where it does apply: `refund_rate` is
refund count ÷ units sold, so a low-volume store can swing sharply on a
small number of events. Flooring by sales volume protects the denominator.
The 1,200 threshold is calibrated for a full monthly period; shorter
sub-ranges can exclude more region_b-best stores than intended.

Every `best`/`worst` call returns `sample_floor_applied` and the excluded
stores with a reason. The floor does not apply to `worst-skus` or
`action-points`.

## Store-level composite score (drives `/cafe-best`, `/cafe-worst`)

The score is a **risk score**. Both weighted components point in the same
direction: higher means worse.

```text
score = 0.6 × normalized_refund_badness + 0.4 × normalized_rating_badness

adjusted_refund_rate    = (refund count ÷ units_sold) × volume_handicap_multiplier
adjusted_rating_badness = ((5 − avg_rating) ÷ 4 × 100) × volume_handicap_multiplier

normalized_refund_badness = min-max scale adjusted_refund_rate to 0–100
normalized_rating_badness = adjusted_rating_badness clipped to [0,100]
normalized_rating_goodness = 100 − normalized_rating_badness   # display only

Best  = lowest composite score
Worst = highest composite score
```

This directionality is intentional and regression-tested. A higher rating
must never increase QC risk, and a higher refund rate must never reduce QC
risk when the other input is held constant.

Scores are calculated within each region separately; region_a and region_b
are never combined into one ranking.

**Display note:** the engine returns both `refund_events` (raw count) and
`refund_rate_pct` (refund count ÷ units sold, as a percentage) for every
store. Store-level views should prefer `refund_rate_pct` because it is
comparable across stores with different volume.

### Volume handicap (locked decision)

Busier stores handle more transactions and therefore have more
opportunities to generate refunds or low ratings. Raw performance is
therefore adjusted before stores are compared.

- **Difficulty metric:** `units_sold`.
- **Tier count:** 3 — Low, Medium and High volume — assigned by terciles
  of `units_sold` among the eligible stores for that call.
- **Handicap strength:** `VOLUME_TIER_MULTIPLIERS = [1.30, 1.00, 0.75]`
  for Low / Medium / High.
- The multiplier is applied to **both refund rate and rating badness**.
  Low-volume stores therefore need genuinely better absolute outcomes to
  outrank high-volume stores, rather than merely being best within a quiet
  peer group.
- Adjusted refund rates are then min-max normalized across all eligible
  stores in the region. Adjusted rating badness is clipped to the valid
  0–100 risk range.
- Tiers are recomputed per call because the eligible population can differ
  between best, worst and dashboard views.

It should remain possible for a low-volume store to make the best list or
for a high-volume store to land on the worst list; the handicap changes the
bar rather than hard-coding the outcome.

## Worst SKU (`/cafe-worst-skus`)

Ranked by **raw refund count** per SKU per store — not normalized by
sales, by design. Always display `title`, never only the raw `sku` hash.

## Action points (`/cafe-action-points`)

Grain is one store × one defect type (`adjustment_reason_code`):

```text
refund_rate  = refund count for that defect type ÷ units_sold at that store
severity     = average refund amount for that defect type at that store
impact_score = refund_rate × severity
```

Reads as "expected refund cost per unit sold, from this one failure
mode." Ranked by `impact_score` descending, ties broken toward higher
instance count.

Ratings feed in as a corroboration label rather than a blended number. The
engine maps each defect code to the complaint tag it most plausibly
corresponds to and sets `confirmed_by_customer_feedback: true` when that
store has at least one rated order carrying the matching complaint tag in
the period. This mapping is an inference between vocabularies, not part of
the source data contract.

Because `impact_score` has no minimum-instance floor, a single high-value
refund can rank highly. The engine therefore includes `instance_count` so
operators can distinguish a repeated failure mode from an isolated event.

## Tag polarity taxonomy

The rating sheet's `tags` field has no built-in good/bad marker. The engine
uses an explicit taxonomy:

- **Compliment:** `good_item_quality`, `good_packaging`, `good_assortment`,
  `fair_prices`, `on_time_delivery`, `rider_behavior_good`
- **Complaint:** `quality_not_fresh`, `damaged_item`, `wrong_item`,
  `missing_item`, `late_delivery`, `rider_behavior_inappropriate`,
  `expiry_item`, `item_cancelled`, `marked_delivered_early`
- **Needs a human read:** `other`

## Category and rating scope

Refund analysis uses all categories present in each region's own file.
Ratings are used as-is, whole-basket, rather than being filtered by
`brand_code` or `comcat`.

## About the bundled demo data

The repository ships with a small, entirely synthetic sample workbook to
exercise the full workflow: alias fixes, exclusions, mapping diagnostics,
the asymmetric sample floor and all three volume tiers. It is not derived
from a real business's data.
