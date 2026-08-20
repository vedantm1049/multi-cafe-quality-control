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
  match are not network locations and are dropped (this is expected —
  region_b in particular can have many non-network warehouse codes in the
  ratings feed).
- **Refund → mapping:** match `ds_name` against the mapping sheet's
  `Store name` / `Store alias` / `Store alias.1` columns, using
  case/hyphen/whitespace-insensitive normalization plus a small hardcoded
  list of known spelling corrections (see `REGION_A_ALIAS_FIX` /
  `REGION_B_ALIAS_FIX` in the engine — the pairs shipped here are
  illustrative examples for the bundled synthetic demo data; populate your
  own from an audit of your real export). A couple of known non-live
  locations can also appear in refund data with no mapping row — these are
  excluded outright via `REGION_A_EXCLUDE` / `REGION_B_EXCLUDE`, not
  reported as unmatched.
- **Sales → mapping:** region_b joins by `DS code` (exact). region_a joins
  by name (`wh_name` against `Store name`/`Store alias`, same
  normalization).

If a future upload introduces a new store or a new spelling variant that
the normalization + hardcoded fixes don't resolve, the engine reports it
under `refund_unmatched_store_names` / `sales_unmatched` /
`rating_unmatched_wh_codes` in the `validate` output rather than silently
guessing. **Always check these fields and flag them to the user** — don't
assume an unmatched name means zero refunds/sales for that store.

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

So region_a never has a floor for either ranking (illustrating a small
master-list market where low volume is itself part of what's under
investigation, not noise to filter out), and region_b only has one for
`/cafe-best` — `/cafe-worst` in region_b ranks every scoreable store,
including low-volume ones, on the theory that a low-volume store having
quality problems is exactly what "worst" should surface, not hide,
whereas crediting a store as "best" should require proven, consistent
volume. A store can therefore appear in region_b's worst list without
being eligible for region_b's best list; that's expected, not a bug.

The units-sold floor (not a refund-count floor) is deliberate where it
does apply: `refund_rate` is refund count ÷ units sold, so a low-volume
store can swing wildly on just a couple of refunds either way — flooring
by sales volume guards the denominator, not the numerator. The 1,200
threshold is calibrated for a full monthly period; a shorter sub-range
will exclude more region_b-best stores than intended since sales scale
down with the window — flag that to the user if they run a `/cafe-best`
sub-range for region_b.

Every engine call to `best`/`worst` returns `sample_floor_applied`
(true/false) so it's always explicit which rule was used. The engine
reports excluded stores with a reason in `excluded_stores` — when the
floor doesn't apply, that list will normally only contain stores with no
matched sales or rating data at all (nothing to score), not a floor
cutoff. This floor concept does **not** apply to `worst-skus` or
`action-points` in either region.

The dashboard (`cafe-dashboard`) shows the no-floor set for both regions
so nothing is hidden, and marks each region_b store with
`meets_best_floor` so the location filter/ranked table can note which
ones would additionally qualify for `/cafe-best`.

## Store-level composite score (drives `/cafe-best`, `/cafe-worst`)

```
score = 0.6 × normalized_refund_badness + 0.4 × normalized_rating_goodness

adjusted_refund_rate    = (refund count ÷ units_sold) × volume_handicap_multiplier
adjusted_rating_badness = ((5 − avg_rating) ÷ 4 × 100) × volume_handicap_multiplier

normalized_refund_badness  = min-max scale adjusted_refund_rate to 0–100 ACROSS ALL ELIGIBLE STORES IN THE REGION, higher = worse
normalized_rating_goodness = 100 − adjusted_rating_badness, clipped to [0,100], higher = better

Best  = lowest composite score
Worst = highest composite score
```

Normalized within each region separately — region_a and region_b are
never combined or compared side by side.

**Display note:** the engine returns both `refund_events` (raw count)
and `refund_rate_pct` (refund count ÷ units sold, as a percentage) for
every store. When presenting store-level tables (`cafe-best`,
`cafe-worst`, `cafe-dashboard`), show `refund_rate_pct` — it's the
normalized figure the composite score is built on and is comparable
across stores of different sales volume, whereas the raw count isn't.

### Volume handicap (locked decision)

Busier stores handle more transactions and so have more chances to make
a mistake, so raw performance isn't compared apples-to-apples across
very different-sized stores. The mechanism is a **multiplicative
handicap applied before one global normalization** — not independent
scoring within separate peer groups (an earlier version of this plugin
did that, and it had a real flaw: the best store *within* a small,
quiet tier could score identically to the best store *within* a large,
busy tier even when its raw refund rate was meaningfully worse. That
let a low-volume store with real quality gaps rank above a high-volume
store with better numbers, purely because each was "best of its own
group." The handicap approach below fixes that.)

- **Difficulty metric:** `units_sold` (same denominator `refund_rate`
  already uses).
- **Tier count:** `VOLUME_TIER_COUNT = 3` ("Low volume" / "Medium
  volume" / "High volume"), assigned by terciles of `units_sold` among
  the current call's eligible stores (`assign_volume_tiers()` in the
  engine). If a region/call has fewer eligible stores than the tier
  count, everyone falls into one tier — the handicap is then a no-op
  since every store gets the same multiplier.
- **Handicap strength — locked at "Moderate":**
  `VOLUME_TIER_MULTIPLIERS = [1.30, 1.00, 0.75]` for Low/Medium/High.
  Each store's raw refund rate and raw rating-badness
  (`(5 − avg_rating) ÷ 4 × 100`) are both multiplied by its tier's
  multiplier — Low-volume stores' numbers are scaled up (made to look
  worse), High-volume stores' numbers are scaled down (made to look
  better), before anyone is compared. **Applied to both refund rate and
  rating** — a low-volume store's high rating doesn't automatically
  buy it a pass either; it needs a genuinely higher rating than a busy
  store's, not just an equal one, to score as well.
- **Then ONE global min-max normalization**, across every eligible
  store in the region (not per-tier), turns the adjusted numbers into
  `normalized_refund_badness` / `normalized_rating_goodness` on a single
  0–100 scale. This is what makes scores comparable across tiers: a
  quiet store now needs adjusted numbers that are genuinely better than
  a busy store's adjusted numbers to out-rank it, not just to lead its
  own small group.
- **Worked example (bundled synthetic demo data, region_b):** "Eastgate"
  (Medium volume, 0.615% raw refund rate, 4.60 rating) and "Sunset
  Corner" (High volume, 0.692% raw refund rate, 4.55 rating) have close
  raw numbers, with Sunset Corner's raw refund rate slightly *worse*.
  Under the handicap: Eastgate's refund rate stays 0.615% × 1.00 =
  0.615%; Sunset Corner's is scaled down to 0.692% × 0.75 = 0.519% — a
  swing that reflects Sunset Corner doing the same job at meaningfully
  higher volume. Sunset Corner ends up scoring better (43.90 vs.
  Eastgate's 46.36, lower = better), correctly crediting it for
  difficulty despite the slightly worse raw refund rate.
- **Tiers are recomputed per call**, over whichever population is
  eligible for that specific call (region_a best, region_a worst,
  region_b best, and region_b worst each have their own eligible set per
  the asymmetric floor above, so tier boundaries and multipliers assigned
  will differ across calls, and from the dashboard's no-floor set).
  `best`/`worst` commands return a `volume_tiers` array (label,
  units-sold range, store count) alongside `rows`, and each row includes
  `volume_tier` and `volume_handicap_multiplier`; the dashboard returns
  the same per region.
- It should not be impossible for a low-volume store to make the best
  list, or for a high-volume store to land on the worst list — the
  handicap raises the bar for quiet stores and lowers it for busy ones,
  it doesn't exclude either from either list.

## Worst SKU (`/cafe-worst-skus`)

Ranked by **raw refund count** per SKU per store — not normalized by
sales, by design. Always display `title`, never the raw `sku` hash.

## Action points (`/cafe-action-points`)

Grain is one store × one defect type (`adjustment_reason_code`):

```
refund_rate  = refund count for that defect type ÷ units_sold at that store
severity     = average refund $ for that defect type at that store
impact_score = refund_rate × severity
```

Reads as "expected refund cost per unit sold, from this one failure
mode." Ranked by `impact_score` descending, ties broken toward higher
instance count.

Ratings feed in as a corroboration label, not a blended number: the
engine maps each `adjustment_reason_code` to the complaint tag it most
plausibly corresponds to (e.g. `item_missing` → `missing_item`,
`frozen_melted` → `quality_not_fresh`) and flags a row
`confirmed_by_customer_feedback: true` if that store has at least one
rated order carrying the matching complaint tag in the period; otherwise
`false` ("refund data only"). **This defect-code-to-tag correspondence is
an inference, not something specified in the original data contract** —
say so if a user asks how the confirmation flag is derived.

Because `impact_score` is refund_rate × severity with no minimum-instance
floor, a defect with a single high-dollar instance can rank very high.
The engine always includes `instance_count` in the output — call this out
when a top row has a low instance count so the user doesn't over-read a
single event.

## Tag polarity taxonomy

The rating sheet's `tags` field is a flat list per order (e.g.
`["on_time_delivery","rider_behavior_good"]`) with no built-in good/bad
marker:

- **Compliment:** `good_item_quality`, `good_packaging`,
  `good_assortment`, `fair_prices`, `on_time_delivery`,
  `rider_behavior_good`
- **Complaint:** `quality_not_fresh`, `damaged_item`, `wrong_item`,
  `missing_item`, `late_delivery`, `rider_behavior_inappropriate`,
  `expiry_item`, `item_cancelled`, `marked_delivered_early`
- **Needs a human read:** `other` — the `comment` field usually explains
  it, can't be auto-classified

## Category and rating scope

Refund analysis uses all categories present in each region's own file
(region_a and region_b are never restricted to a shared subset, since
they're never compared side by side). Ratings are used as-is,
whole-basket, not filtered by `brand_code` or `comcat`.

## About the bundled demo data

This repo ships with a small, entirely synthetic sample workbook (see
`docs/` for the live static demo built from it) — fabricated store names,
fabricated numbers, generated to exercise every code path (alias fixes,
an excluded location, a mapping collision, the asymmetric floor, all
three volume tiers). It is not derived from any real business's data.
Swap in your own export to use this against a real network.
