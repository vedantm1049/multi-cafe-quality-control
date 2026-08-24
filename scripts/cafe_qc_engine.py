#!/usr/bin/env python3
"""
Cafe QC engine.

Loads an 8-sheet Cafe QC workbook, validates it against the locked data
contract, resolves store identity across the identifier systems used in
the refund / rating / sales / mapping sheets, and computes the scoring
outputs used by the cafe-qc plugin's slash commands.

The network is modeled as two regions (region_a, region_b) with
independent store master lists -- this mirrors a real multi-market retail
QC setup without naming any specific brand or geography.

Usage:
    python3 cafe_qc_engine.py validate   --file WORKBOOK.xlsx
    python3 cafe_qc_engine.py best       --file WORKBOOK.xlsx --region region_a --n 5
    python3 cafe_qc_engine.py worst      --file WORKBOOK.xlsx --region region_b --n 10
    python3 cafe_qc_engine.py worst-skus --file WORKBOOK.xlsx --region region_a --per-store-n 3
    python3 cafe_qc_engine.py action-points --file WORKBOOK.xlsx --region region_b --n 10
    python3 cafe_qc_engine.py dashboard  --file WORKBOOK.xlsx
    python3 cafe_qc_engine.py analysis   --file WORKBOOK.xlsx --region region_a

All commands accept optional --start / --end (YYYY-MM-DD) to restrict to a
sub-range of the uploaded period. All commands print a single JSON object
to stdout. Errors (missing sheet, missing column) are printed as
{"error": "..."} and exit code 1 -- surface these to the user rather than
guessing at a fix.
"""
import argparse
import ast
import json
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------
# Locked data contract
# ----------------------------------------------------------------------
SHEET_NAMES = {
    "region_a": {"refund": "refund_region_a", "rating": "rating_region_a",
                 "mapping": "mapping_region_a", "sales": "sales_region_a"},
    "region_b": {"refund": "refund_region_b", "rating": "rating_region_b",
                 "mapping": "mapping_region_b", "sales": "sales_region_b"},
}

CONTRACT = {
    "refund_region_a": ["order_nr", "adjustment_reason_code", "sku", "title", "amount",
                         "order_created_timestamp", "category", "ds_name"],
    "refund_region_b": ["order_nr", "adjustment_reason_code", "sku", "title", "amount",
                         "order_created_timestamp", "category", "ds_name"],
    "rating_region_a": ["order_nr", "all_sku", "brand_code", "comcat", "created_at",
                         "rating", "tags", "wh_code"],
    "rating_region_b": ["order_nr", "all_sku", "brand_code", "comcat", "created_at",
                         "rating", "tags", "wh_code"],
    "mapping_region_a": ["Wh code", "Lock code", "Store name", "Store alias"],
    "mapping_region_b": ["Wh code", "Lock code", "Store name", "Store alias", "DS code"],
    "sales_region_a": ["wh", "wh_name", "units_sold", "gmv"],
    "sales_region_b": ["wh", "wh_name", "units_sold", "gmv"],
}

# ----------------------------------------------------------------------
# Known alias corrections. Normalization (see norm()) handles
# case/hyphen/comma/whitespace differences on its own; this dict only
# covers pairs that are genuinely spelled/worded differently between
# sheets and would NOT resolve via normalization. Example pairs below are
# illustrative (this repo ships with synthetic demo data, not real store
# names) -- in production, populate from an audit of your own export.
# ----------------------------------------------------------------------
REGION_A_ALIAS_FIX = {
    "old mil": "old mill",
    "garden dist": "garden district",
}
REGION_B_ALIAS_FIX = {
    "north bridge": "northbridge",
    "sun set corner": "sunset corner",
    "fair view": "fairview",
}
# Known non-live locations that can appear in refund data but have no
# mapping row. Excluded outright, not reported as "unmatched".
REGION_B_EXCLUDE = {"pop-up kiosk", "test location"}
REGION_A_EXCLUDE = set()

# ----------------------------------------------------------------------
# Tag polarity taxonomy
# ----------------------------------------------------------------------
COMPLIMENT_TAGS = {"good_item_quality", "good_packaging", "good_assortment",
                    "fair_prices", "on_time_delivery", "rider_behavior_good"}
COMPLAINT_TAGS = {"quality_not_fresh", "damaged_item", "wrong_item", "missing_item",
                   "late_delivery", "rider_behavior_inappropriate", "expiry_item",
                   "item_cancelled", "marked_delivered_early"}
NEEDS_HUMAN_TAGS = {"other"}

# Refund adjustment_reason_code -> complaint tag it corresponds to, used
# only to compute the action-point "confirmed by customer feedback" flag.
# This correspondence is NOT guaranteed by the data contract; it is an
# inferred mapping between the two vocabularies observed in a sample
# export. Reason codes with no reasonable tag equivalent map to None and
# are always reported as "refund data only".
DEFECT_TAG_MAP = {
    "item_missing": "missing_item",
    "item_damaged": "damaged_item",
    "wrong_item": "wrong_item",
    "quality_not_fresh": "quality_not_fresh",
    "frozen_melted": "quality_not_fresh",
    "chilled_room_temperature": "quality_not_fresh",
    "temperature_not_right": "quality_not_fresh",
    "pest_infestation": "quality_not_fresh",
    "content_mismatch": "wrong_item",
    "open_package_received": "damaged_item",
    "ordernotdelivered": "late_delivery",
    "order_never_arrived": "late_delivery",
    "delivered_wrong_address_picked": "late_delivery",
    "return_request_accepted": None,
    "cs_exception": None,
}

MIN_RATED_ORDERS = 10
# Sample floor for best/worst rankings is based on sales volume, not refund
# count -- refund_rate is refund_events / units_sold, so a low-volume store
# can swing wildly on a couple of refunds either way. 1,200 units is
# calibrated for a full monthly period; a shorter sub-range will exclude
# more stores than intended since sales naturally scale down with the
# window -- flag that to the user if they run a sub-range best/worst.
MIN_UNITS_SOLD = 1200

# Busier stores handle more transactions and so have more chances to make a
# mistake -- a barista serving 30 drinks/hour at peak is operating very
# differently from one serving 5. This is implemented as a volume HANDICAP,
# not independent peer-group normalization: an earlier version min-max
# scaled refund badness separately within each volume tier, but that let the
# best store in a quiet tier score identically (badness=0) to the best store
# in a busy tier, even when the quiet store's raw refund rate was
# meaningfully worse -- "best of a weak group" isn't the same as "best of a
# strong group", and low-volume stores should have to clear a HIGHER bar,
# not just beat other quiet stores.
#
# Locked mechanism: assign each store a volume tier (Low/Medium/High, by
# units_sold terciles), multiply its refund_rate AND its rating-badness
# (5 - avg_rating, i.e. distance from a perfect score) by a per-tier
# handicap factor, then min-max normalize the ADJUSTED figures across every
# eligible store in the region on ONE combined scale (not per tier). A
# low-volume store's badness is inflated (harder to look good), a
# high-volume store's badness is discounted (credited for difficulty) --
# applied identically to refund rate and rating, so a low-volume store needs
# both a genuinely lower refund rate AND a genuinely higher rating than a
# busy store to rank near it, not just to be the best among other quiet
# stores. "Moderate" strength, an explicit locked decision:
#   Low volume tier:    x1.30 (30% worse)
#   Medium volume tier: x1.00 (baseline)
#   High volume tier:   x0.75 (25% better / credited)
#
# 3 tiers (Low/Medium/High, by units_sold terciles) balances tier
# granularity against sample size -- a small region's store count would
# leave too few stores per tier with more than 3. If a region has fewer
# eligible stores than VOLUME_TIER_COUNT, everyone falls into a single tier
# (multiplier still applies via that tier's assignment, but with only one
# tier present the ranking is effectively unhandicapped for that call).
VOLUME_TIER_COUNT = 3
VOLUME_TIER_LABELS = ["Low volume", "Medium volume", "High volume"]
VOLUME_TIER_MULTIPLIERS = [1.30, 1.00, 0.75]  # indexed by tier 0/1/2 (Low/Medium/High)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def norm(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = str(s).strip().lower()
    s = re.sub(r"[-,]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def parse_tags(raw):
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    if isinstance(raw, list):
        return raw
    try:
        val = ast.literal_eval(raw)
        return val if isinstance(val, list) else []
    except Exception:
        return []


def load_workbook(path):
    xl = pd.ExcelFile(path)
    missing_sheets = [s for s in CONTRACT if s not in xl.sheet_names]
    if missing_sheets:
        raise ValueError(f"Upload is missing expected sheet(s): {', '.join(missing_sheets)}. "
                          f"Expected sheets: {', '.join(CONTRACT)}.")
    sheets = {}
    col_issues = {}
    for name, cols in CONTRACT.items():
        df = xl.parse(name)
        missing_cols = [c for c in cols if c not in df.columns]
        if missing_cols:
            col_issues[name] = missing_cols
        sheets[name] = df
    if col_issues:
        detail = "; ".join(f"{s} missing {cols}" for s, cols in col_issues.items())
        raise ValueError(f"Upload's columns don't match the locked data contract: {detail}.")
    return sheets


def build_mapping_lookup(mapping_df):
    alias_cols = [c for c in ["Store name", "Store alias", "Store alias.1"] if c in mapping_df.columns]
    lookup = {}
    collisions = []
    for _, row in mapping_df.iterrows():
        wh = row["Wh code"]
        for col in alias_cols:
            val = row.get(col)
            key = norm(val)
            if key:
                if key in lookup and lookup[key] != wh:
                    collisions.append({"alias": key, "existing_wh": lookup[key], "new_wh": wh})
                else:
                    lookup.setdefault(key, wh)
    return lookup, collisions


def wh_display_name(mapping_df):
    disp = {}
    for _, row in mapping_df.iterrows():
        disp[row["Wh code"]] = row["Store name"]
    return disp


def resolve_store(raw_name, lookup, alias_fix, exclude_set):
    key = norm(raw_name)
    if key in exclude_set:
        return None, "excluded"
    if key in lookup:
        return lookup[key], "matched"
    fixed = alias_fix.get(key)
    if fixed and norm(fixed) in lookup:
        return lookup[norm(fixed)], "matched_via_fix"
    return None, "unmatched"


def load_region(sheets, region):
    """Resolve store identity and return a dict of cleaned per-region frames."""
    assert region in ("region_a", "region_b")
    names = SHEET_NAMES[region]
    refund = sheets[names["refund"]].copy()
    rating = sheets[names["rating"]].copy()
    sales = sheets[names["sales"]].copy()
    mapping = sheets[names["mapping"]].copy()

    alias_fix = REGION_A_ALIAS_FIX if region == "region_a" else REGION_B_ALIAS_FIX
    exclude_set = REGION_A_EXCLUDE if region == "region_a" else REGION_B_EXCLUDE

    lookup, collisions = build_mapping_lookup(mapping)
    wh_names = wh_display_name(mapping)
    wh_set = set(mapping["Wh code"])

    # --- refund: resolve via ds_name ---
    wh_col, status_col = [], []
    for v in refund["ds_name"]:
        wh, status = resolve_store(v, lookup, alias_fix, exclude_set)
        wh_col.append(wh)
        status_col.append(status)
    refund["wh_code"] = wh_col
    refund["_match_status"] = status_col
    refund_unmatched = sorted(set(refund.loc[refund["_match_status"] == "unmatched", "ds_name"]))
    refund_excluded = sorted(set(refund.loc[refund["_match_status"] == "excluded", "ds_name"]))
    refund_matched = refund[refund["wh_code"].notna()].copy()

    # --- rating: resolve via wh_code (exact match against mapping's Wh code) ---
    rating["_in_network"] = rating["wh_code"].isin(wh_set)
    rating_matched = rating[rating["_in_network"]].copy()
    rating_unmatched_codes = sorted(set(rating.loc[~rating["_in_network"], "wh_code"].dropna()))

    # --- sales: region_b via DS code, region_a via wh_name ---
    if region == "region_b":
        ds_lookup = {row["DS code"]: row["Wh code"] for _, row in mapping.iterrows()
                     if pd.notna(row.get("DS code"))}
        sales["wh_code"] = sales["wh"].map(ds_lookup)
        sales_unmatched = sorted(set(sales.loc[sales["wh_code"].isna(), "wh"]))
    else:
        wh_col2, status_col2 = [], []
        for v in sales["wh_name"]:
            wh, status = resolve_store(v, lookup, alias_fix, exclude_set)
            wh_col2.append(wh)
            status_col2.append(status)
        sales["wh_code"] = wh_col2
        sales["_match_status"] = status_col2
        sales_unmatched = sorted(set(sales.loc[sales["_match_status"] == "unmatched", "wh_name"]))
    sales_matched = sales[sales["wh_code"].notna()].copy()

    return {
        "mapping": mapping,
        "wh_names": wh_names,
        "refund": refund_matched,
        "rating": rating_matched,
        "sales": sales_matched,
        "diagnostics": {
            "region": region,
            "mapping_lookup_collisions": collisions,
            "refund_total_rows": int(len(refund)),
            "refund_matched_rows": int(len(refund_matched)),
            "refund_unmatched_store_names": refund_unmatched,
            "refund_excluded_store_names": refund_excluded,
            "rating_total_rows": int(len(rating)),
            "rating_matched_rows": int(len(rating_matched)),
            "rating_unmatched_wh_codes": rating_unmatched_codes,
            "sales_total_rows": int(len(sales)),
            "sales_matched_rows": int(len(sales_matched)),
            "sales_unmatched": sales_unmatched,
            "mapping_store_count": int(mapping["Wh code"].nunique()),
        },
    }


def apply_date_range(df, col, start, end):
    if df.empty:
        return df
    out = df
    if start:
        out = out[out[col] >= pd.Timestamp(start)]
    if end:
        out = out[out[col] < pd.Timestamp(end) + pd.Timedelta(days=1)]
    return out


def date_range_summary(sheets):
    ranges = {}
    for region, names in SHEET_NAMES.items():
        for kind, col in [("refund", "order_created_timestamp"), ("rating", "created_at")]:
            sheet = names[kind]
            s = sheets[sheet][col]
            if len(s):
                ranges[sheet] = {"min": str(s.min()), "max": str(s.max())}
    all_min = min(v["min"] for v in ranges.values())
    all_max = max(v["max"] for v in ranges.values())
    return {"by_sheet": ranges, "overall_min": all_min, "overall_max": all_max}


# ----------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------
def floor_applies(region, worst):
    """The minimum sample floor (>=10 rated orders, >=1,200 units sold) is
    applied asymmetrically, per an explicit locked decision:
      - region_a: never applied (best or worst) -- its master list is
        small, and low volume there is itself part of what's being
        investigated, not noise to filter out.
      - region_b best: applied -- crediting a store as "best" should
        require proven, consistent volume.
      - region_b worst: never applied -- a low-volume store having
        quality problems is exactly the kind of thing "worst" should
        surface, not hide.
    """
    if region == "region_a":
        return False
    return not worst  # region_b: floor only for "best"


def assign_volume_tiers(units_sold_series, n_tiers=VOLUME_TIER_COUNT):
    """Bucket stores into volume (units_sold) peer-group tiers, low to high.
    Falls back to a single tier (equivalent to the old region-wide
    normalization) if there aren't enough stores for n_tiers meaningful
    groups. Returns (tier_index_series, tier_bounds) where tier_bounds
    describes each tier's range and store count, for transparency in output.
    """
    n = len(units_sold_series)
    if n < n_tiers:
        tier = pd.Series(0, index=units_sold_series.index)
    else:
        try:
            tier = pd.qcut(units_sold_series, q=n_tiers, labels=False, duplicates="drop")
        except ValueError:
            tier = pd.Series(0, index=units_sold_series.index)

    bounds = []
    for t in sorted(tier.unique()):
        vals = units_sold_series[tier == t]
        label = VOLUME_TIER_LABELS[t] if t < len(VOLUME_TIER_LABELS) else f"Tier {t}"
        bounds.append({
            "tier": int(t),
            "label": label,
            "min_units_sold": float(vals.min()),
            "max_units_sold": float(vals.max()),
            "n_stores": int(len(vals)),
        })
    return tier, bounds


def compute_store_table(region_data, start=None, end=None, apply_floor=True):
    refund = apply_date_range(region_data["refund"], "order_created_timestamp", start, end)
    rating = apply_date_range(region_data["rating"], "created_at", start, end)
    sales = region_data["sales"]
    wh_names = region_data["wh_names"]

    refund_counts = refund.groupby("wh_code").size().rename("refund_events")
    units_sold = sales.groupby("wh_code")["units_sold"].sum().rename("units_sold")
    avg_rating = rating.groupby("wh_code")["rating"].mean().rename("avg_rating")
    rated_orders = rating.groupby("wh_code").size().rename("rated_orders")

    all_wh = sorted(set(wh_names.keys()))
    table = pd.DataFrame(index=all_wh)
    table["store_name"] = table.index.map(wh_names)
    table = table.join(refund_counts).join(units_sold).join(avg_rating).join(rated_orders)
    table["refund_events"] = table["refund_events"].fillna(0)
    table["rated_orders"] = table["rated_orders"].fillna(0)

    table["meets_sample_floor"] = (table["rated_orders"] >= MIN_RATED_ORDERS) & \
                                   (table["units_sold"].notna()) & (table["units_sold"] >= MIN_UNITS_SOLD)

    floor_mask = table["meets_sample_floor"] if apply_floor else pd.Series(True, index=table.index)

    eligible = table[floor_mask & table["units_sold"].notna() & (table["units_sold"] > 0)
                      & table["avg_rating"].notna()].copy()

    tier_bounds = []
    if len(eligible):
        eligible["refund_rate"] = eligible["refund_events"] / eligible["units_sold"]
        eligible["volume_tier"], tier_bounds = assign_volume_tiers(eligible["units_sold"])
        eligible["volume_tier_label"] = eligible["volume_tier"].map(
            lambda t: VOLUME_TIER_LABELS[t] if t < len(VOLUME_TIER_LABELS) else f"Tier {t}")
        eligible["volume_handicap_multiplier"] = eligible["volume_tier"].map(
            lambda t: VOLUME_TIER_MULTIPLIERS[t] if t < len(VOLUME_TIER_MULTIPLIERS) else 1.0)

        # Apply the volume handicap to the RAW inputs, then normalize once
        # across every eligible store on a single combined scale -- NOT per
        # tier. A low-volume store must clear a higher absolute bar (lower
        # adjusted refund rate, higher adjusted rating) to rank near a busy
        # store, rather than merely being the best among other quiet stores.
        eligible["adjusted_refund_rate"] = eligible["refund_rate"] * eligible["volume_handicap_multiplier"]
        rmin, rmax = eligible["adjusted_refund_rate"].min(), eligible["adjusted_refund_rate"].max()
        if rmax > rmin:
            eligible["normalized_refund_badness"] = (eligible["adjusted_refund_rate"] - rmin) / (rmax - rmin) * 100
        else:
            eligible["normalized_refund_badness"] = 50.0

        # Rating is converted to badness before weighting so both composite
        # inputs have the same direction: 0 = low risk, 100 = high risk.
        # Keep goodness as an output field because it is useful for display,
        # but never mix goodness with refund badness in the risk score.
        rating_badness_raw = (5 - eligible["avg_rating"]) / 4 * 100
        eligible["adjusted_rating_badness"] = rating_badness_raw * eligible["volume_handicap_multiplier"]
        eligible["normalized_rating_badness"] = eligible["adjusted_rating_badness"].clip(0, 100)
        eligible["normalized_rating_goodness"] = (100 - eligible["normalized_rating_badness"]).clip(0, 100)

        eligible["composite_score"] = 0.6 * eligible["normalized_refund_badness"] + \
                                       0.4 * eligible["normalized_rating_badness"]

    excluded = table[~table.index.isin(eligible.index)].copy()
    excluded_reason = []
    for wh, row in excluded.iterrows():
        reasons = []
        if apply_floor and not row["meets_sample_floor"]:
            units_str = "no matched sales data" if pd.isna(row["units_sold"]) else f"{row['units_sold']:.0f} units sold"
            reasons.append(f"below sample floor ({int(row['rated_orders'])} rated orders, "
                            f"{units_str}; need >={MIN_RATED_ORDERS} rated orders and >={MIN_UNITS_SOLD} units sold)")
        if pd.isna(row["units_sold"]) or row["units_sold"] == 0:
            reasons.append("no matched sales/units_sold data")
        if pd.isna(row["avg_rating"]):
            reasons.append("no matched rating data")
        excluded_reason.append("; ".join(reasons) if reasons else "insufficient data")
    excluded["exclusion_reason"] = excluded_reason

    return eligible, excluded, tier_bounds


def store_rows(df, sort_col, ascending, n):
    d = df.sort_values(sort_col, ascending=ascending).head(n)
    out = []
    for wh, row in d.iterrows():
        out.append({
            "wh_code": wh,
            "store_name": row["store_name"],
            "composite_score": round(float(row["composite_score"]), 2),
            # Refund count / units sold, the same ratio the composite score
            # is built on. Surfaced as a percentage (refund_rate_pct) for
            # display -- prefer this over the raw refund_events count when
            # presenting store tables, since it's normalized for store
            # volume and matches the scoring logic.
            "refund_rate": round(float(row["refund_rate"]), 5),
            "refund_rate_pct": round(float(row["refund_rate"]) * 100, 3),
            "refund_events": int(row["refund_events"]),
            "units_sold": float(row["units_sold"]),
            "avg_rating": round(float(row["avg_rating"]), 2),
            "rated_orders": int(row["rated_orders"]),
            # Volume handicap: this store's refund rate and rating are each
            # multiplied by volume_handicap_multiplier (>1 for low volume =
            # penalty, <1 for high volume = credit) before region-wide
            # normalization -- so a low-volume store needs genuinely better
            # absolute numbers, not just to beat other quiet stores.
            "volume_tier": row["volume_tier_label"],
            "volume_handicap_multiplier": round(float(row["volume_handicap_multiplier"]), 2),
            "normalized_refund_badness": round(float(row["normalized_refund_badness"]), 2),
            "normalized_rating_badness": round(float(row["normalized_rating_badness"]), 2),
            "normalized_rating_goodness": round(float(row["normalized_rating_goodness"]), 2),
        })
    return out


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------
def cmd_validate(args):
    sheets = load_workbook(args.file)
    result = {"status": "ok", "sheets": {}, "date_range": date_range_summary(sheets)}
    for region in ("region_a", "region_b"):
        rd = load_region(sheets, region)
        result["sheets"][region] = rd["diagnostics"]
    print(json.dumps(result, indent=2, default=str))


def cmd_best_worst(args, worst=False):
    sheets = load_workbook(args.file)
    rd = load_region(sheets, args.region)
    apply_floor = floor_applies(args.region, worst)
    eligible, excluded, tier_bounds = compute_store_table(rd, args.start, args.end, apply_floor=apply_floor)
    if eligible.empty:
        print(json.dumps({"error": "No stores have enough data (units sold + avg rating) to score for this period/region."}))
        return
    rows = store_rows(eligible, "composite_score", ascending=not worst, n=args.n)
    print(json.dumps({
        "region": args.region,
        "direction": "worst" if worst else "best",
        "n_requested": args.n,
        "sample_floor_applied": apply_floor,
        "n_eligible_stores": int(len(eligible)),
        "n_excluded_stores": int(len(excluded)),
        "excluded_stores": [{"store_name": r["store_name"], "wh_code": wh, "reason": r["exclusion_reason"]}
                             for wh, r in excluded.iterrows()],
        "volume_tiers": tier_bounds,
        "rows": rows,
    }, indent=2, default=str))


def cmd_worst_skus(args):
    sheets = load_workbook(args.file)
    rd = load_region(sheets, args.region)
    refund = apply_date_range(rd["refund"], "order_created_timestamp", args.start, args.end)
    wh_names = rd["wh_names"]

    if args.store:
        target = norm(args.store)
        matches = [wh for wh, name in wh_names.items() if norm(name) == target or norm(wh) == target]
        if not matches:
            print(json.dumps({"error": f"Store '{args.store}' not found in {args.region} mapping."}))
            return
        stores = matches
    else:
        stores = sorted(refund["wh_code"].dropna().unique())

    result = []
    for wh in stores:
        sub = refund[refund["wh_code"] == wh]
        if sub.empty:
            continue
        counts = sub.groupby(["sku", "title"]).size().rename("refund_count").reset_index()
        counts = counts.sort_values("refund_count", ascending=False).head(args.per_store_n)
        result.append({
            "wh_code": wh,
            "store_name": wh_names.get(wh, wh),
            "total_refund_events": int(len(sub)),
            "top_skus": [{"title": r["title"], "sku": r["sku"], "refund_count": int(r["refund_count"])}
                         for _, r in counts.iterrows()],
        })
    result.sort(key=lambda x: x["total_refund_events"], reverse=True)
    print(json.dumps({
        "region": args.region,
        "per_store_n": args.per_store_n,
        "stores": result,
    }, indent=2, default=str))


def cmd_action_points(args):
    sheets = load_workbook(args.file)
    rd = load_region(sheets, args.region)
    refund = apply_date_range(rd["refund"], "order_created_timestamp", args.start, args.end)
    rating = apply_date_range(rd["rating"], "created_at", args.start, args.end)
    sales = rd["sales"]
    wh_names = rd["wh_names"]

    units_sold = sales.groupby("wh_code")["units_sold"].sum()

    store_complaint_tags = {}
    for wh, sub in rating.groupby("wh_code"):
        tags_present = set()
        for taglist in sub["tags"]:
            tags_present.update(t for t in parse_tags(taglist) if t in COMPLAINT_TAGS)
        store_complaint_tags[wh] = tags_present

    grp = refund.groupby(["wh_code", "adjustment_reason_code"])
    rows = []
    for (wh, defect), sub in grp:
        if wh not in units_sold.index or units_sold.loc[wh] <= 0:
            continue
        instance_count = len(sub)
        refund_rate = instance_count / units_sold.loc[wh]
        severity = float(sub["amount"].abs().mean())
        impact_score = refund_rate * severity
        mapped_tag = DEFECT_TAG_MAP.get(norm(defect).replace(" ", "_"), None)
        if mapped_tag is None:
            mapped_tag = DEFECT_TAG_MAP.get(defect.lower(), None)
        confirmed = bool(mapped_tag and mapped_tag in store_complaint_tags.get(wh, set()))
        rows.append({
            "wh_code": wh,
            "store_name": wh_names.get(wh, wh),
            "defect_type": defect,
            "impact_score": impact_score,
            "refund_rate": refund_rate,
            "refund_rate_pct": refund_rate * 100,
            "severity_avg_refund_amount": severity,
            "instance_count": instance_count,
            "confirmed_by_customer_feedback": confirmed,
            "corroborating_tag": mapped_tag,
        })

    rows.sort(key=lambda r: (-r["impact_score"], -r["instance_count"]))
    top = rows[:args.n]
    for r in top:
        r["impact_score"] = round(r["impact_score"], 6)
        r["refund_rate"] = round(r["refund_rate"], 6)
        r["refund_rate_pct"] = round(r["refund_rate_pct"], 4)
        r["severity_avg_refund_amount"] = round(r["severity_avg_refund_amount"], 2)

    print(json.dumps({
        "region": args.region,
        "n_requested": args.n,
        "rows": top,
    }, indent=2, default=str))


def store_tag_breakdown(taglists):
    counts = {"compliment": 0, "complaint": 0, "needs_human_read": 0}
    complaint_detail = {}
    for taglist in taglists:
        for t in parse_tags(taglist):
            if t in COMPLIMENT_TAGS:
                counts["compliment"] += 1
            elif t in COMPLAINT_TAGS:
                counts["complaint"] += 1
                complaint_detail[t] = complaint_detail.get(t, 0) + 1
            elif t in NEEDS_HUMAN_TAGS:
                counts["needs_human_read"] += 1
    top_complaints = sorted(complaint_detail.items(), key=lambda kv: -kv[1])
    return counts, [{"tag": t, "count": n} for t, n in top_complaints]


def store_worst_skus(refund_sub, n=5):
    if refund_sub.empty:
        return []
    counts = refund_sub.groupby(["sku", "title"]).size().rename("refund_count").reset_index()
    counts = counts.sort_values("refund_count", ascending=False).head(n)
    return [{"title": r["title"], "sku": r["sku"], "refund_count": int(r["refund_count"])}
            for _, r in counts.iterrows()]


def build_store_detail_list(rd, refund, rating, sales, eligible, excluded, top_skus_n=5):
    """Per-store detail for every mapped store (eligible and excluded alike), used
    to power a location filter -- so a low-volume store can still be inspected even
    though it's left out of the best/worst rankings."""
    wh_names = rd["wh_names"]
    units_sold_s = sales.groupby("wh_code")["units_sold"].sum()
    gmv_s = sales.groupby("wh_code")["gmv"].sum()

    detail = []
    for wh in sorted(wh_names.keys()):
        is_eligible = wh in eligible.index
        row = eligible.loc[wh] if is_eligible else (excluded.loc[wh] if wh in excluded.index else None)
        refund_sub = refund[refund["wh_code"] == wh]
        rating_sub = rating[rating["wh_code"] == wh]
        units_sold = float(units_sold_s.get(wh)) if wh in units_sold_s.index and pd.notna(units_sold_s.get(wh)) else None
        gmv = float(gmv_s.get(wh)) if wh in gmv_s.index and pd.notna(gmv_s.get(wh)) else None
        refund_events = int(len(refund_sub))
        avg_rating = float(rating_sub["rating"].mean()) if len(rating_sub) else None
        rated_orders = int(len(rating_sub))
        refund_rate_pct = round(refund_events / units_sold * 100, 3) if units_sold else None
        tag_counts, top_complaints = store_tag_breakdown(rating_sub["tags"])
        meets_best_floor = bool(rated_orders >= MIN_RATED_ORDERS and units_sold is not None
                                 and units_sold >= MIN_UNITS_SOLD)

        detail.append({
            "wh_code": wh,
            "store_name": wh_names.get(wh, wh),
            "eligible": bool(is_eligible),
            "meets_best_floor": meets_best_floor,
            "exclusion_reason": (None if is_eligible else
                                  (row["exclusion_reason"] if row is not None and "exclusion_reason" in row else "no data")),
            "composite_score": round(float(row["composite_score"]), 2) if is_eligible else None,
            "volume_tier": row["volume_tier_label"] if is_eligible else None,
            "units_sold": units_sold,
            "gmv": gmv,
            "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
            "rated_orders": rated_orders,
            "refund_events": refund_events,
            "refund_rate_pct": refund_rate_pct,
            "worst_skus": store_worst_skus(refund_sub, top_skus_n),
            "tag_polarity_breakdown": tag_counts,
            "top_complaints": top_complaints,
        })
    detail.sort(key=lambda s: (s["composite_score"] is None, s["composite_score"] if s["composite_score"] is not None else 0))
    return detail


def cmd_dashboard(args):
    sheets = load_workbook(args.file)
    out = {"date_range": date_range_summary(sheets), "regions": {}}
    for region in ("region_a", "region_b"):
        rd = load_region(sheets, region)
        refund = apply_date_range(rd["refund"], "order_created_timestamp", args.start, args.end)
        rating = apply_date_range(rd["rating"], "created_at", args.start, args.end)
        sales = rd["sales"]
        eligible, excluded, tier_bounds = compute_store_table(rd, args.start, args.end, apply_floor=False)

        reason_breakdown = refund["adjustment_reason_code"].value_counts().to_dict()
        tag_counts, _ = store_tag_breakdown(rating["tags"])
        tag_detail = {}
        for taglist in rating["tags"]:
            for t in parse_tags(taglist):
                tag_detail[t] = tag_detail.get(t, 0) + 1

        category_breakdown = refund.groupby("category")["order_nr"].count().to_dict()

        out["regions"][region] = {
            "diagnostics": rd["diagnostics"],
            "store_count_eligible": int(len(eligible)),
            "store_count_excluded": int(len(excluded)),
            "stores": build_store_detail_list(rd, refund, rating, sales, eligible, excluded),
            "volume_tiers": tier_bounds,
            "refund_reason_breakdown": reason_breakdown,
            "category_breakdown": category_breakdown,
            "tag_polarity_breakdown": tag_counts,
            "tag_detail": tag_detail,
        }
    print(json.dumps(out, indent=2, default=str))


def cmd_analysis(args):
    sheets = load_workbook(args.file)
    rd = load_region(sheets, args.region)
    refund = apply_date_range(rd["refund"], "order_created_timestamp", args.start, args.end)
    rating = apply_date_range(rd["rating"], "created_at", args.start, args.end)

    refund_weekly = refund.set_index("order_created_timestamp").resample("W")["order_nr"].count()
    rating_weekly = rating.set_index("created_at")["rating"].resample("W").mean()

    out = {
        "region": args.region,
        "diagnostics": rd["diagnostics"],
        "refund_events_weekly": {str(k.date()): int(v) for k, v in refund_weekly.items()},
        "avg_rating_weekly": {str(k.date()): (round(float(v), 3) if pd.notna(v) else None)
                               for k, v in rating_weekly.items()},
        "category_breakdown": refund.groupby("category")["order_nr"].count().to_dict(),
        "reason_breakdown": refund["adjustment_reason_code"].value_counts().to_dict(),
        "refund_amount_total": float(refund["amount"].sum()),
        "refund_amount_by_category": refund.groupby("category")["amount"].sum().to_dict(),
    }
    print(json.dumps(out, indent=2, default=str))


# ----------------------------------------------------------------------
def add_common_args(p):
    p.add_argument("--file", required=True)
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate")
    p.add_argument("--file", required=True)

    p = sub.add_parser("best")
    add_common_args(p)
    p.add_argument("--region", required=True, choices=["region_a", "region_b"])
    p.add_argument("--n", type=int, required=True)

    p = sub.add_parser("worst")
    add_common_args(p)
    p.add_argument("--region", required=True, choices=["region_a", "region_b"])
    p.add_argument("--n", type=int, required=True)

    p = sub.add_parser("worst-skus")
    add_common_args(p)
    p.add_argument("--region", required=True, choices=["region_a", "region_b"])
    p.add_argument("--per-store-n", type=int, default=5)
    p.add_argument("--store", default=None)

    p = sub.add_parser("action-points")
    add_common_args(p)
    p.add_argument("--region", required=True, choices=["region_a", "region_b"])
    p.add_argument("--n", type=int, required=True)

    p = sub.add_parser("dashboard")
    add_common_args(p)

    p = sub.add_parser("analysis")
    add_common_args(p)
    p.add_argument("--region", required=True, choices=["region_a", "region_b"])

    args = parser.parse_args()
    try:
        if args.command == "validate":
            cmd_validate(args)
        elif args.command == "best":
            cmd_best_worst(args, worst=False)
        elif args.command == "worst":
            cmd_best_worst(args, worst=True)
        elif args.command == "worst-skus":
            cmd_worst_skus(args)
        elif args.command == "action-points":
            cmd_action_points(args)
        elif args.command == "dashboard":
            cmd_dashboard(args)
        elif args.command == "analysis":
            cmd_analysis(args)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
