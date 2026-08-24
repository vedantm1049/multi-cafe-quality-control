from __future__ import annotations

from io import BytesIO
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def build_sample_workbook() -> bytes:
    """Return a deterministic synthetic 8-sheet QC workbook for the live demo."""
    rng = np.random.default_rng(42)

    stores_a = [
        ("A001", "LA001", "Harbor Point", "Harbor Pt", None, 4800, 4.72, 5, "quality_not_fresh"),
        ("A002", "LA002", "Old Mill", "Old Mill Cafe", None, 3100, 4.44, 9, "item_missing"),
        ("A003", "LA003", "Garden District", "Garden District", None, 1900, 3.82, 18, "quality_not_fresh"),
        ("A004", "LA004", "Creek Walk", "Creek Walk", None, 5200, 4.61, 8, "wrong_item"),
        ("A005", "LA005", "Central Market", "Central Mkt", None, 1400, 3.48, 24, "item_damaged"),
        ("A006", "LA006", "Marina Square", "Marina Sq", None, 6400, 4.79, 6, "item_missing"),
    ]
    stores_b = [
        ("B001", "LB001", "Northbridge", "Northbridge", "D001", 8200, 4.76, 7, "item_missing"),
        ("B002", "LB002", "Sunset Corner", "Sunset Corner", "D002", 5600, 4.42, 13, "quality_not_fresh"),
        ("B003", "LB003", "Fairview", "Fairview", "D003", 3300, 3.91, 22, "item_damaged"),
        ("B004", "LB004", "Palm Avenue", "Palm Ave", "D004", 7100, 4.63, 9, "wrong_item"),
        ("B005", "LB005", "City Gate", "City Gate", "D005", 2600, 3.66, 25, "quality_not_fresh"),
        ("B006", "LB006", "Canal Walk", "Canal Walk", "D006", 4300, 4.35, 15, "item_missing"),
        ("B007", "LB007", "Market Street", "Market St", "D007", 980, 3.52, 11, "wrong_item"),
        ("B008", "LB008", "Park Lane", "Park Lane", "D008", 6100, 4.69, 8, "item_damaged"),
        ("B009", "LB009", "South Quay", "South Quay", "D009", 1750, 4.08, 17, "quality_not_fresh"),
        ("B010", "LB010", "Lakeside", "Lakeside", "D010", 9000, 4.83, 5, "item_missing"),
    ]

    mapping_a = pd.DataFrame(
        [{"Wh code": wh, "Lock code": lock, "Store name": name, "Store alias": alias}
         for wh, lock, name, alias, _, *_ in stores_a]
    )
    mapping_b = pd.DataFrame(
        [{"Wh code": wh, "Lock code": lock, "Store name": name, "Store alias": alias, "DS code": ds}
         for wh, lock, name, alias, ds, *_ in stores_b]
    )

    sales_a = pd.DataFrame(
        [{"wh": wh, "wh_name": name, "units_sold": units, "gmv": round(units * (21.5 + i * 0.7), 2)}
         for i, (wh, _, name, _, _, units, *_rest) in enumerate(stores_a)]
    )
    sales_b = pd.DataFrame(
        [{"wh": ds, "wh_name": name, "units_sold": units, "gmv": round(units * (22.0 + i * 0.5), 2)}
         for i, (_wh, _lock, name, _alias, ds, units, *_rest) in enumerate(stores_b)]
    )

    refund_name_override = {
        "Old Mill": "Old Mil",
        "Garden District": "Garden Dist",
        "Northbridge": "North Bridge",
        "Sunset Corner": "Sun Set Corner",
        "Fairview": "Fair View",
    }

    products = [
        ("SKU-101", "Iced Spanish Latte", "Beverages"),
        ("SKU-102", "Mango Matcha Latte", "Beverages"),
        ("SKU-103", "Cold Brew", "Beverages"),
        ("SKU-104", "Protein Mocha", "Functional Drinks"),
        ("SKU-105", "Berry Slush", "Frozen Drinks"),
    ]
    defect_pool = ["quality_not_fresh", "item_missing", "item_damaged", "wrong_item", "temperature_not_right"]
    complaint_tag_for = {
        "quality_not_fresh": "quality_not_fresh",
        "item_missing": "missing_item",
        "item_damaged": "damaged_item",
        "wrong_item": "wrong_item",
        "temperature_not_right": "quality_not_fresh",
    }
    start = datetime(2026, 7, 1, 8, 0, 0)

    def make_refunds(stores, region_prefix):
        rows = []
        seq = 1
        for store_i, (wh, _lock, name, _alias, _ds, _units, _avg, refund_n, dominant_defect) in enumerate(stores):
            ds_name = refund_name_override.get(name, name)
            for j in range(refund_n):
                defect = dominant_defect if j < max(1, int(refund_n * 0.6)) else defect_pool[(j + store_i) % len(defect_pool)]
                sku, title, category = products[(j + store_i) % len(products)]
                rows.append({
                    "order_nr": f"{region_prefix}-R-{seq:05d}",
                    "adjustment_reason_code": defect,
                    "sku": sku,
                    "title": title,
                    "amount": -round(float(rng.uniform(12, 38)), 2),
                    "order_created_timestamp": start + timedelta(days=(j * 3 + store_i) % 28, hours=j % 9),
                    "category": category,
                    "ds_name": ds_name,
                })
                seq += 1
        if region_prefix == "B":
            rows.append({
                "order_nr": "B-R-EXCLUDED",
                "adjustment_reason_code": "item_missing",
                "sku": "SKU-101",
                "title": "Iced Spanish Latte",
                "amount": -18.0,
                "order_created_timestamp": start + timedelta(days=12),
                "category": "Beverages",
                "ds_name": "Pop-up Kiosk",
            })
        return pd.DataFrame(rows)

    def make_ratings(stores, region_prefix):
        rows = []
        seq = 1
        for store_i, (wh, _lock, _name, _alias, _ds, units, avg_target, _refund_n, dominant_defect) in enumerate(stores):
            n = max(14, min(70, int(units / 120)))
            complaint_tag = complaint_tag_for[dominant_defect]
            for j in range(n):
                rating = int(np.clip(np.rint(rng.normal(avg_target, 0.62)), 1, 5))
                if rating <= 2:
                    tags = [complaint_tag]
                elif rating == 3 and j % 3 == 0:
                    tags = [complaint_tag]
                elif rating >= 5:
                    tags = ["good_item_quality"]
                else:
                    tags = []
                sku, _title, _category = products[(j + store_i) % len(products)]
                rows.append({
                    "order_nr": f"{region_prefix}-T-{seq:05d}",
                    "all_sku": str([sku]),
                    "brand_code": "DEMO_CAFE",
                    "comcat": "fresh_beverages",
                    "created_at": start + timedelta(days=(j * 2 + store_i) % 28, hours=j % 10),
                    "rating": rating,
                    "tags": str(tags),
                    "wh_code": wh,
                })
                seq += 1
        return pd.DataFrame(rows)

    sheets = {
        "refund_region_a": make_refunds(stores_a, "A"),
        "refund_region_b": make_refunds(stores_b, "B"),
        "rating_region_a": make_ratings(stores_a, "A"),
        "rating_region_b": make_ratings(stores_b, "B"),
        "mapping_region_a": mapping_a,
        "mapping_region_b": mapping_b,
        "sales_region_a": sales_a,
        "sales_region_b": sales_b,
    }

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()
