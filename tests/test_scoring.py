import unittest

import pandas as pd

from scripts.cafe_qc_engine import compute_store_table, sales_for_period, store_rows


class ScoringDirectionTests(unittest.TestCase):
    @staticmethod
    def region_data(*, ratings, refund_counts):
        wh_codes = ["A", "B"]

        refund_rows = []
        order_nr = 1
        for wh in wh_codes:
            for _ in range(refund_counts[wh]):
                refund_rows.append({
                    "wh_code": wh,
                    "order_created_timestamp": pd.Timestamp("2026-08-01"),
                    "order_nr": order_nr,
                })
                order_nr += 1

        rating_rows = [
            {
                "wh_code": wh,
                "rating": ratings[wh],
                "created_at": pd.Timestamp("2026-08-01"),
            }
            for wh in wh_codes
        ]

        sales_rows = [
            {"wh_code": "A", "units_sold": 1000},
            {"wh_code": "B", "units_sold": 1000},
        ]

        return {
            "wh_names": {"A": "Store A", "B": "Store B"},
            "refund": pd.DataFrame(refund_rows),
            "rating": pd.DataFrame(rating_rows),
            "sales": pd.DataFrame(sales_rows),
        }

    def test_better_rating_reduces_qc_risk_score(self):
        data = self.region_data(
            ratings={"A": 5.0, "B": 1.0},
            refund_counts={"A": 1, "B": 1},
        )

        eligible, _, _ = compute_store_table(data, apply_floor=False)

        self.assertLess(eligible.loc["A", "composite_score"], eligible.loc["B", "composite_score"])
        self.assertEqual(eligible.loc["A", "normalized_rating_badness"], 0)
        self.assertEqual(eligible.loc["B", "normalized_rating_badness"], 100)

    def test_more_refunds_increase_qc_risk_score_when_rating_is_equal(self):
        data = self.region_data(
            ratings={"A": 4.0, "B": 4.0},
            refund_counts={"A": 1, "B": 4},
        )

        eligible, _, _ = compute_store_table(data, apply_floor=False)

        self.assertLess(eligible.loc["A", "composite_score"], eligible.loc["B", "composite_score"])
        self.assertLess(eligible.loc["A", "normalized_refund_badness"], eligible.loc["B", "normalized_refund_badness"])

    def test_best_and_worst_sort_in_opposite_risk_directions(self):
        data = self.region_data(
            ratings={"A": 5.0, "B": 1.0},
            refund_counts={"A": 1, "B": 1},
        )
        eligible, _, _ = compute_store_table(data, apply_floor=False)

        best = store_rows(eligible, "composite_score", ascending=True, n=1)
        worst = store_rows(eligible, "composite_score", ascending=False, n=1)

        self.assertEqual(best[0]["wh_code"], "A")
        self.assertEqual(worst[0]["wh_code"], "B")


class PeriodSalesTests(unittest.TestCase):
    """A sub-period's refunds must be divided by that period's sales, not the
    whole workbook's. Sales carry no dates, so they are scaled by the share of
    the workbook's days the period covers."""

    @staticmethod
    def region_data():
        # 14 days of data, 2026-08-01 to 2026-08-14; one refund per day at store A.
        days = pd.date_range("2026-08-01", periods=14, freq="D")
        return {
            "wh_names": {"A": "Store A"},
            "refund": pd.DataFrame({"wh_code": "A", "order_created_timestamp": days, "order_nr": range(14)}),
            "rating": pd.DataFrame({"wh_code": "A", "rating": 4.5, "created_at": days}),
            "sales": pd.DataFrame([{"wh_code": "A", "units_sold": 1400, "gmv": 28000}]),
        }

    def test_whole_workbook_uses_all_sales(self):
        eligible, _, _ = compute_store_table(self.region_data(), apply_floor=False)
        self.assertAlmostEqual(eligible.loc["A", "refund_rate"], 14 / 1400)

    def test_first_week_uses_half_the_sales(self):
        eligible, _, _ = compute_store_table(self.region_data(), "2026-08-01", "2026-08-07", apply_floor=False)
        self.assertEqual(eligible.loc["A", "units_sold"], 700)
        # 7 refunds over 700 units, the same rate as the whole workbook, not 7 over 1,400.
        self.assertAlmostEqual(eligible.loc["A", "refund_rate"], 7 / 700)

    def test_period_outside_the_data_has_no_sales(self):
        scaled = sales_for_period(self.region_data(), "2026-09-01", "2026-09-07")
        self.assertEqual(scaled["units_sold"].iloc[0], 0)

    def test_gmv_scales_with_units(self):
        scaled = sales_for_period(self.region_data(), "2026-08-08", None)
        self.assertEqual(scaled["gmv"].iloc[0], 14000)


if __name__ == "__main__":
    unittest.main()
