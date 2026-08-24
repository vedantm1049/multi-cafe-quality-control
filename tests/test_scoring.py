import unittest

import pandas as pd

from scripts.cafe_qc_engine import compute_store_table, store_rows


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


if __name__ == "__main__":
    unittest.main()
