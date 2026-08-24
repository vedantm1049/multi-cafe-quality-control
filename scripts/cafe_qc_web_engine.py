#!/usr/bin/env python3
"""Web/demo entrypoint for the Cafe QC engine.

This thin wrapper keeps the existing engine as the source of truth while
correcting the composite-score direction so both inputs are risk/badness
measures before they are combined. Lower composite score = better quality;
higher composite score = greater QC risk.
"""
from __future__ import annotations

import cafe_qc_engine as engine


_original_compute_store_table = engine.compute_store_table


def compute_store_table(region_data, start=None, end=None, apply_floor=True):
    eligible, excluded, tier_bounds = _original_compute_store_table(
        region_data, start=start, end=end, apply_floor=apply_floor
    )
    if not eligible.empty:
        eligible = eligible.copy()
        eligible["normalized_rating_badness"] = (100 - eligible["normalized_rating_goodness"]).clip(0, 100)
        eligible["composite_score"] = (
            0.6 * eligible["normalized_refund_badness"]
            + 0.4 * eligible["normalized_rating_badness"]
        )
    return eligible, excluded, tier_bounds


engine.compute_store_table = compute_store_table


if __name__ == "__main__":
    engine.main()
