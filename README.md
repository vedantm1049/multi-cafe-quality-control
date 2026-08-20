# Cafe QC

Store-level refund and rating quality analysis for a multi-region coffee
retail network, built from a periodic 8-sheet QC data export.

**[Live demo](https://vedantm1049.github.io/cafe-qc/)** — a static,
pre-baked version of the dashboard, built from the synthetic sample data
bundled in this repo. See "Live demo & real data" below for what that
does and doesn't include.

## The problem, and what this automates

Store ops teams get a periodic QC export with hundreds to thousands of
refund events, ratings, and sales rows spread across 8 sheets — turning
that into "which stores need attention and why" used to mean a manual
pass in a spreadsheet every period: matching store aliases across three
different identifier systems, weighting for volume so a quiet store's one
bad week doesn't look worse than a busy store's genuine problem, and
reading through free-text complaints by hand.

This plugin turns that into a conversation. Upload the export, ask a
question in plain language or run a slash command, and it validates the
data, asks only for what it can't infer, runs the scoring engine, and
hands back a ranked table, a chart, or an exportable sheet — consistently,
using the same locked scoring rules every time.

## Installation

This is a [Claude Code](https://docs.claude.com/en/docs/claude-code) /
Cowork plugin. To install it from this repo:

```bash
git clone https://github.com/vedantm1049/cafe-qc.git
```

Then, in Claude Code or Cowork, add it as a plugin source pointing at the
cloned folder (or add this repo directly as a marketplace source, if
you're distributing it to a team). See the
[Claude Code plugin docs](https://docs.claude.com/en/docs/claude-code) for
the exact install flow, since it may change.

No real data is bundled with this repo — you supply your own QC workbook
export each time you use it (see Usage below). The `docs/` folder's
synthetic sample data exists only to power the live demo.

## Overview

Upload the Cafe QC workbook (`refund_region_a`, `refund_region_b`,
`rating_region_a`, `rating_region_b`, `mapping_region_a`,
`mapping_region_b`, `sales_region_a`, `sales_region_b`) and use any of the
six skills below. All 8 sheets are expected fresh each period — there's
no reliance on a prior upload.

## Components

| Skill | Trigger | Output |
|---|---|---|
| `cafe-dashboard` | `/cafe-dashboard` | Interactive HTML — store-level view + complaint-type breakdown, region_a/region_b toggle |
| `cafe-worst-skus` | `/cafe-worst-skus` | Exportable sheet — worst 3/5 SKUs per store, by raw refund count |
| `cafe-action-points` | `/cafe-action-points` | Inline ranked table (+ optional export) — top store×defect-type combos by impact score |
| `cafe-best` | `/cafe-best` | Inline ranked table (+ optional export) — top stores by composite score |
| `cafe-worst` | `/cafe-worst` | Inline ranked table (+ optional export) — bottom stores by composite score |
| `cafe-analysis` | `/cafe-analysis` | Conversational, open-ended trend/category analysis |

All six skills share one engine (`scripts/cafe_qc_engine.py`) for data
loading, store-identity resolution, and scoring, so results are
consistent across commands. Full data contract, store-identity
resolution logic, and scoring formulas are documented in
`references/data-contract-and-scoring.md`; the shared per-command
workflow (locate file → validate → elicit → run → present) is in
`references/running-the-engine.md`.

## How it works

Every skill follows the same agentic loop, defined once in
`references/running-the-engine.md` and reused by all six commands:

1. **Locate** — find the uploaded Cafe QC workbook in the conversation.
2. **Validate** — run the engine's `validate` command, surface any
   unmatched stores or data-contract issues before doing anything else.
3. **Elicit** — ask the user only for what can't be inferred from context
   (region, timeframe, count), skipping anything already given.
4. **Run** — call the shared Python engine (`cafe_qc_engine.py`) so every
   skill scores off the same logic.
5. **Present** — format the result per that command's spec (inline table,
   exportable sheet, interactive dashboard, or conversational analysis).

Keeping this loop identical across all six skills is what makes the
outputs comparable — a store's composite score means the same thing
whether you got there through `/cafe-best`, `/cafe-worst`, or a freeform
question.

## Setup

No external services or credentials required. Requires Python 3 with
`pandas`, `numpy`, and `openpyxl` available in the sandbox (already
present in Cowork's Linux sandbox).

## Usage

Upload the Cafe QC workbook in a Cowork conversation, then type any of
the slash commands above (or ask in natural language — e.g. "show me the
worst-performing stores in region_b this month"). Each skill will run
`cafe_qc_engine.py validate` first and surface any data-contract issues
(missing sheet/column, unmatched store name) before producing output.

## Live demo & real data

`docs/` is a static site (GitHub Pages) built from a small, entirely
synthetic sample workbook — fabricated store names, fabricated numbers,
generated by hand to exercise the engine's real code paths (alias fixes,
an excluded location, a mapping collision, the asymmetric sample floor,
all three volume tiers) without containing anyone's actual business data.
The scoring shown there uses the exact formulas in
`scripts/cafe_qc_engine.py` — nothing in the demo is fudged, only the
underlying inputs are made up.

It's a fixed snapshot, not a live engine: there's no upload button and no
backend, so it always shows the same sample period. To run this against
your own export, use the plugin inside Claude Code/Cowork as described
above.

**Future work:** a real interactive version — upload your own workbook in
the browser and get live rankings/action-points back, no Claude required
— would need a backend wrapping the engine plus a hosting account to run
it on. Not built yet; the static demo covers the "see what this looks
like" use case for now.

## Known design decisions worth knowing about

- **Low-volume stores are handicapped, not scored in an isolated peer
  group.** Busier stores handle more transactions and so have more
  chances to make a mistake, so stores are bucketed into 3 volume tiers
  by `units_sold` (terciles — Low/Medium/High), and each store's raw
  refund rate and raw rating-badness are multiplied by its tier's
  handicap (`VOLUME_TIER_MULTIPLIERS` — Low ×1.30, Medium ×1.00, High
  ×0.75, a "Moderate" strength) *before* everyone is normalized together
  on one scale. This is applied to both refund rate and rating, per an
  explicit locked decision — a low-volume store's rating has to be
  genuinely higher than a busy store's, not just equal, to score as
  well. An earlier version of this plugin normalized each tier
  independently instead, which let the best store in a small, quiet
  tier score identically to the best store in a large, busy tier even
  when its raw numbers were meaningfully worse — the handicap approach
  replaced it to fix exactly that gap. See `assign_volume_tiers()` and
  the scoring block in `compute_store_table()` in
  `scripts/cafe_qc_engine.py`, and the "Volume handicap" section of
  `references/data-contract-and-scoring.md` for the full mechanism and
  a worked example.
- **Minimum sample floor** (10 rated orders / 1,200 units sold per store)
  is applied **asymmetrically**, per an explicit locked decision:
  region_a never has a floor (best or worst); region_b applies it to
  `/cafe-best` only, not `/cafe-worst`. It never applies to
  `cafe-worst-skus` or `cafe-action-points` in either region. The floor
  is based on units sold, not refund count — `refund_rate` is refund
  count ÷ units sold, so flooring by sales volume protects the
  denominator instead of arbitrarily requiring a minimum number of
  refunds. 1,200 is calibrated for a full monthly period; a shorter
  sub-range will exclude more region_b best-list stores than intended.
  See `floor_applies()` in `scripts/cafe_qc_engine.py` and the "Minimum
  sample floor" section of `references/data-contract-and-scoring.md` for
  the full rule.
- **Store alias corrections** are hardcoded in `scripts/cafe_qc_engine.py`
  (`REGION_A_ALIAS_FIX` / `REGION_B_ALIAS_FIX`) — the pairs shipped here
  are illustrative examples for the bundled synthetic demo data. In a
  real deployment, populate these from a manual audit of your own export.
  If a future upload introduces a new spelling variant that isn't
  covered, `validate` will report it as unmatched rather than guess — at
  that point, add the new pair to the relevant dict.
- **Action-point confirmation flag** (`confirmed_by_customer_feedback`)
  relies on a defect-code → complaint-tag correspondence
  (`DEFECT_TAG_MAP` in the engine) that is *inferred* from two plausible
  vocabularies — it isn't guaranteed by the data contract itself. Revisit
  this mapping if new `adjustment_reason_code` values show up in a future
  upload that aren't in the dict (they'll just get
  `confirmed_by_customer_feedback: false` by default, which is a safe
  fallback but worth checking).

## License

MIT — see [LICENSE](LICENSE).
