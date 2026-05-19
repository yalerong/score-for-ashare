import unittest

import pandas as pd

from data_fetcher_tushare import DataFetcherTushare


class FakeTushareFetcher(DataFetcherTushare):
    def __init__(self):
        self.offline_mode = False
        self._spot_cache = {}
        self._trade_cal_cache = None
        self.trade_dates = ["20260511", "20260512", "20260513"]
        self.spot_by_date = {
            "20260511": pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
                    "pct_chg": [10.0, -1.0, 2.0],
                }
            ),
            "20260512": pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
                    "pct_chg": [3.0, 8.0, -2.0],
                }
            ),
            "20260513": pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "600000.SH"],
                    "pct_chg": [-1.0, 9.8, 1.0],
                }
            ),
        }

    def _get_trade_cal(self, years=6):
        return self.trade_dates

    def _get_spot(self, trade_date_yyyymmdd):
        return self.spot_by_date[trade_date_yyyymmdd]

    def get_index_data_range(self, symbol="000001", years=1):
        return pd.DataFrame(
            {
                "date": ["2026-05-11", "2026-05-12", "2026-05-13"],
                "change_pct": [0.1, 0.2, 0.3] if symbol == "000688" else [-0.1, -0.2, -0.3],
            }
        )


class DataFetcherTushareTests(unittest.TestCase):
    def test_cross_section_history_reuses_daily_spot_snapshots(self):
        history = FakeTushareFetcher().get_cross_sectional_state_history(years=1)

        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["source"], "tushare_cross_section")
        self.assertEqual(history[1]["previous_limit_up_return"], 3.0)
        self.assertAlmostEqual(history[1]["previous_limit_up_up_ratio"], 1.0)
        self.assertEqual(history[2]["limit_up_count"], 1)
        self.assertAlmostEqual(history[2]["style_spread"], 0.6)


if __name__ == "__main__":
    unittest.main()
