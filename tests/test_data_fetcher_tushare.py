import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
    def setUp(self):
        self.rate_limit = patch("data_fetcher_tushare._shared_rate_limit")
        self.rate_limit.start()
        self.addCleanup(self.rate_limit.stop)

    def make_fetcher(self, **api_methods):
        fetcher = DataFetcherTushare.__new__(DataFetcherTushare)
        fetcher.pro = SimpleNamespace(**api_methods)
        fetcher._spot_cache = {}
        fetcher._trade_cal_cache = None
        return fetcher

    def test_empty_spot_is_retried(self):
        daily = Mock(side_effect=[pd.DataFrame(), pd.DataFrame({
            "ts_code": ["000001.SZ"], "pct_chg": [1.0],
        })])
        fetcher = self.make_fetcher(daily=daily)
        self.assertIsNone(fetcher._get_spot("20260511"))
        self.assertIsNotNone(fetcher._get_spot("20260511"))
        self.assertEqual(daily.call_count, 2)

    def test_current_spot_is_refreshed_after_partial_response(self):
        today = datetime.now().strftime("%Y%m%d")
        daily = Mock(side_effect=[
            pd.DataFrame({"ts_code": ["000001.SZ"], "pct_chg": [1.0]}),
            pd.DataFrame({"ts_code": ["000001.SZ", "600000.SH"], "pct_chg": [1.0, 2.0]}),
        ])
        fetcher = self.make_fetcher(daily=daily)
        self.assertEqual(len(fetcher._get_spot(today)), 1)
        self.assertEqual(len(fetcher._get_spot(today)), 2)

    def test_calendar_refreshes_across_day_and_for_longer_range(self):
        class Clock(datetime):
            current = datetime(2026, 10, 29, 17)

            @classmethod
            def now(cls):
                return cls.current

        def calendar(**kwargs):
            dates = ["20261029", "20261030"]
            return pd.DataFrame({"cal_date": [d for d in dates if d <= kwargs["end_date"]]})

        trade_cal = Mock(side_effect=calendar)
        fetcher = self.make_fetcher(trade_cal=trade_cal)
        with patch("data_fetcher_tushare.datetime", Clock):
            self.assertEqual(fetcher._latest_trade_date(), "20261029")
            self.assertEqual(fetcher._latest_trade_date(), "20261029")
            self.assertEqual(trade_cal.call_count, 1)
            Clock.current = datetime(2026, 10, 30, 17)
            self.assertEqual(fetcher._latest_trade_date(), "20261030")
            fetcher._get_trade_cal(years=10)
        self.assertEqual(trade_cal.call_count, 3)

    def test_margin_requires_exchange_identity_in_live_and_history(self):
        rows = []
        for date, balances in [
            ("20260511", {"SSE": 100, "SZSE": 100, "BSE": 1}),
            ("20260512", {"SSE": 101, "SZSE": 100, "BSE": 1}),
            ("20260513", {"SSE": 102, "BSE": 1}),
        ]:
            rows.extend({"trade_date": date, "exchange_id": exchange, "rzye": balance}
                        for exchange, balance in balances.items())
        fetcher = self.make_fetcher(margin=Mock(return_value=pd.DataFrame(rows)))
        fetcher._get_trade_cal = lambda years=6: ["20260511", "20260512", "20260513"]
        fetcher._latest_trade_date = lambda: "20260513"
        current = fetcher.get_margin_trading()
        historical = fetcher.get_margin_trading_historical(years=1)
        self.assertEqual(current["date"], "2026-05-12")
        self.assertEqual(current["net_change"], 1.0)
        self.assertEqual([r["date"] for r in historical], ["2026-05-11", "2026-05-12"])
        self.assertIsNone(historical[0]["net_change"])

    def test_margin_does_not_bridge_incomplete_or_absent_trading_days(self):
        rows = []
        for date, markets in [
            ("20260511", ["SSE", "SZSE", "BSE"]),
            ("20260512", ["SSE", "SZSE"]),
            ("20260513", ["SSE", "SZSE", "BSE"]),
            ("20260515", ["SSE", "SZSE", "BSE"]),
        ]:
            rows.extend({"trade_date": date, "exchange_id": exchange, "rzye": 100}
                        for exchange in markets)
        fetcher = self.make_fetcher(margin=Mock(return_value=pd.DataFrame(rows)))
        fetcher._get_trade_cal = lambda years=6: [f"202605{day}" for day in range(11, 16)]
        history = fetcher.get_margin_trading_historical(years=1)
        self.assertEqual([r["date"] for r in history], ["2026-05-11", "2026-05-13", "2026-05-15"])
        self.assertTrue(all(r["net_change"] is None for r in history))

    def test_margin_accepts_history_before_bse_margin_launch(self):
        rows = [{"trade_date": date, "exchange_id": exchange, "rzye": balance}
                for date, balance in [("20230209", 100), ("20230210", 101)]
                for exchange in ["SSE", "SZSE"]]
        rows.extend({"trade_date": "20230213", "exchange_id": exchange, "rzye": 102}
                    for exchange in ["SSE", "SZSE", "BSE"])
        fetcher = self.make_fetcher(margin=Mock(return_value=pd.DataFrame(rows)))
        fetcher._get_trade_cal = lambda years=6: ["20230209", "20230210", "20230213"]
        history = fetcher.get_margin_trading_historical(years=1)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[1]["net_change"], 2.0)
        self.assertIsNone(history[2]["net_change"])

    def test_margin_rejects_modern_period_without_bse(self):
        rows = [{"trade_date": date, "exchange_id": exchange, "rzye": 100}
                for date in ["20260511", "20260512"]
                for exchange in ["SSE", "SZSE"]]
        fetcher = self.make_fetcher(margin=Mock(return_value=pd.DataFrame(rows)))
        fetcher._get_trade_cal = lambda years=6: ["20260511", "20260512"]
        fetcher._latest_trade_date = lambda: "20260512"
        self.assertIsNone(fetcher.get_margin_trading())
        self.assertEqual(fetcher.get_margin_trading_historical(years=1), [])

    def test_margin_rejects_missing_bse_before_first_complete_modern_date(self):
        rows = [{"trade_date": date, "exchange_id": exchange, "rzye": 100}
                for date in ["20260511", "20260512"]
                for exchange in ["SSE", "SZSE"]]
        rows.extend({"trade_date": "20260513", "exchange_id": exchange, "rzye": 101}
                    for exchange in ["SSE", "SZSE", "BSE"])
        fetcher = self.make_fetcher(margin=Mock(return_value=pd.DataFrame(rows)))
        fetcher._get_trade_cal = lambda years=6: ["20260511", "20260512", "20260513"]
        history = fetcher.get_margin_trading_historical(years=1)
        self.assertEqual([r["date"] for r in history], ["2026-05-13"])
        self.assertIsNone(history[0]["net_change"])

    def test_cross_section_history_reuses_daily_spot_snapshots(self):
        history = FakeTushareFetcher().get_cross_sectional_state_history(years=1)

        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["source"], "tushare_cross_section")
        self.assertEqual(history[1]["previous_limit_up_return"], 3.0)
        self.assertAlmostEqual(history[1]["previous_limit_up_up_ratio"], 1.0)
        self.assertEqual(history[2]["limit_up_count"], 1)
        self.assertAlmostEqual(history[2]["style_spread"], 0.6)


    def test_full_size_daily_reply_is_rejected_as_truncated(self):
        rows = pd.DataFrame({"ts_code": ["000001.SZ"] * 6000, "pct_chg": [1.0] * 6000})
        fetcher = self.make_fetcher(daily=Mock(return_value=rows))
        with self.assertRaises(RuntimeError):
            fetcher._get_spot("20260511")

    def test_history_calendar_covers_requested_years(self):
        trade_cal = Mock(return_value=pd.DataFrame({"cal_date": ["20260511"]}))
        fetcher = self.make_fetcher(trade_cal=trade_cal, daily=Mock(return_value=pd.DataFrame()))
        fetcher.get_market_breadth_history(years=8)
        start = datetime.strptime(trade_cal.call_args.kwargs["start_date"], "%Y%m%d")
        self.assertLessEqual(start, datetime.now() - pd.Timedelta(days=8 * 365))

if __name__ == "__main__":
    unittest.main()
