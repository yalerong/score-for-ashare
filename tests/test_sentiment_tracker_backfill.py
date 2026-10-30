import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

from sentiment_scoring import summarize_cross_section_state
from sentiment_tracker import SentimentTracker


class FakeHistoryFetcher:
    offline_mode = False

    def __init__(self):
        self.cross_section_history_called = False
        self.dates = pd.date_range("2026-05-01", periods=8, freq="D").strftime("%Y-%m-%d").tolist()

    def get_index_data_range(self, symbol="000001", years=1):
        return pd.DataFrame(
            {
                "date": self.dates,
                "close": [100, 101, 102, 103, 104, 105, 106, 107],
                "amount": [1_000_000_000 + i * 10_000_000 for i in range(len(self.dates))],
                "change_pct": [-1.0, -0.5, 0.0, 0.4, 0.8, 1.0, 1.2, 1.5],
            }
        )

    def get_market_breadth_history(self, years=1):
        return [
            {
                "date": date,
                "up_ratio": 40.0 + i,
                "median_change": -0.5 + i * 0.1,
                "breadth_thrust": -10.0 + i,
                "source": "test_breadth",
            }
            for i, date in enumerate(self.dates)
        ]

    def get_cross_sectional_state_history(self, years=1):
        self.cross_section_history_called = True
        return [
            summarize_cross_section_state(
                date=date,
                spot_changes=[-1.0, 0.5 + i * 0.1, 1.0 + i * 0.1, 2.0],
                universe_size=4,
                limit_up_count=i,
                strong_pool_count=2,
                microcap_change=0.1 * i,
                largecap_change=0.0,
                source="test_cross_section",
            )
            for i, date in enumerate(self.dates)
        ]

    def get_north_flow_historical(self, years=1):
        return [
            {"date": date, "net_flow": 1_000_000 + i * 1_000, "source": "test_north"}
            for i, date in enumerate(self.dates)
        ]

    def get_margin_trading_historical(self, years=1):
        return [
            {
                "date": date,
                "margin_balance": 1_000_000_000,
                "net_change": 1_000_000 + i * 1_000,
                "source": "test_margin",
            }
            for i, date in enumerate(self.dates)
        ]

    def get_market_breadth(self, date=None):
        return next(item for item in self.get_market_breadth_history() if item["date"] == date)

    def get_cross_sectional_state(self, date=None):
        return next(item for item in self.get_cross_sectional_state_history() if item["date"] == date)

    def get_north_flow(self):
        return self.get_north_flow_historical()[-1]

    def get_margin_trading(self):
        return self.get_margin_trading_historical()[-1]


class SentimentTrackerBackfillTests(unittest.TestCase):
    def test_default_tracker_can_save_history_without_tushare_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"TUSHARE_TOKEN": ""}), patch("sentiment_tracker.DATA_DIR", tmp_dir):
                tracker = SentimentTracker()
                tracker.save_result(
                    {
                        "date": "2026-05-01",
                        "timestamp": "2026-05-01 15:00:00",
                        "sentiment_score": 50.0,
                        "sentiment_level": "neutral",
                    }
                )

                self.assertIsNone(tracker.fetcher)
                self.assertEqual(len(tracker.history), 1)

    def test_backfill_uses_cross_section_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)

            results = tracker.backfill_history(days=8, end_date=fetcher.dates[-1])

            self.assertTrue(fetcher.cross_section_history_called)
            self.assertEqual(len(results), 8)
            self.assertTrue(
                all(item["raw_data"]["cross_section_source"] == "test_cross_section" for item in results)
            )

    def test_backfill_and_daily_run_agree_for_same_inputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)

            with patch("sentiment_tracker.datetime") as clock:
                clock.now.return_value = datetime(2026, 5, 8, 17)
                historical = tracker.backfill_history(days=8)[-1]
            daily = tracker.run()

            self.assertEqual(historical["date"], daily["date"])
            self.assertEqual(historical["components"], daily["components"])
            self.assertEqual(historical["sentiment_score"], daily["sentiment_score"])
            with open(tracker.cross_section_file, encoding="utf-8") as handle:
                cached = json.load(handle)
            self.assertEqual(len(cached), len(fetcher.dates))

    def test_backfill_only_updates_requested_calendar_days(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)
            original = {"date": fetcher.dates[0], "sentiment_score": 12.34}
            tracker.save_result(original)

            with patch("sentiment_tracker.datetime") as clock:
                clock.now.return_value = datetime(2026, 5, 8, 17)
                results = tracker.backfill_history(days=3)

            self.assertEqual([item["date"] for item in results], fetcher.dates[-3:])
            self.assertEqual(tracker.history[0], original)
            self.assertEqual(len(tracker.history), 4)
            with open(tracker.cross_section_file, encoding="utf-8") as handle:
                cached = json.load(handle)
            # The clock's current day may still be incomplete and is not persisted.
            self.assertEqual([item["date"] for item in cached], fetcher.dates[:-1])

    def test_daily_and_backfill_calibration_agree_after_nontrading_days(self):
        class WeekendFetcher(FakeHistoryFetcher):
            def __init__(self):
                super().__init__()
                self.dates = ["2025-10-31", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]

            def recent(self, rows, years):
                cutoff = (pd.Timestamp("2026-11-02") - pd.Timedelta(days=365 * years)).strftime("%Y-%m-%d")
                return [item for item in rows if item["date"] >= cutoff]

            def get_market_breadth_history(self, years=1):
                rows = [{"date": date, "up_ratio": value, "source": "test"} for date, value in zip(self.dates, [20, 60, 60, 60, 60, 60, 60, 50])]
                return self.recent(rows, years)

            def get_cross_sectional_state_history(self, years=1):
                return [dict(row, microcap_change=0.0, largecap_change=0.0) for row in self.get_market_breadth_history(years)]

            def get_north_flow_historical(self, years=1):
                return self.recent(super().get_north_flow_historical(years), years)

            def get_margin_trading_historical(self, years=1):
                return self.recent(super().get_margin_trading_historical(years), years)

        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir), patch("sentiment_tracker.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, 2, 17)
            tracker = SentimentTracker(fetcher=WeekendFetcher())

            historical = tracker.backfill_history(start_date="2026-10-30", end_date="2026-10-30")[-1]
            daily = tracker.run()

            self.assertEqual(historical["components"], daily["components"])
            self.assertEqual(historical["sentiment_score"], daily["sentiment_score"])

    def test_backfill_accepts_explicit_date_range(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)

            results = tracker.backfill_history(start_date="2026-05-03", end_date="2026-05-05")

            self.assertEqual([item["date"] for item in results], fetcher.dates[2:5])

    @patch.dict("sentiment_tracker.SENTIMENT_WEIGHTS", {"north_flow": 0.15})
    def test_funding_components_require_matching_known_dates(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)
            frame = tracker._prepare_index_features(fetcher.get_index_data_range())
            arguments = dict(date_str=fetcher.dates[-1], index_row=frame.iloc[-1], history_frame=frame)
            missing = tracker.calculate_sentiment_for_date(**arguments)

            for date_field in ("date", "timestamp"):
                with self.subTest(north_date_field=date_field):
                    north = {"net_flow": 1_000_000, date_field: "2026-05-07" if date_field == "date" else "2026-05-07 15:00:00", "source": "test"}
                    # Same-day margin is not public at the close; day T must use T-1.
                    margin = {"margin_balance": 1_000_000_000, "net_change": 1_000_000, "date": "2026-05-08", "source": "test"}
                    stale = tracker.calculate_sentiment_for_date(**arguments, north_flow=north, margin_data=margin)

                    self.assertFalse(stale["component_availability"]["north_flow"])
                    self.assertFalse(stale["component_availability"]["margin_trading"])
                    self.assertEqual(stale["coverage"], missing["coverage"])
                    self.assertEqual(stale["sentiment_score"], missing["sentiment_score"])
                    self.assertEqual(stale["raw_data"]["north_date"], "2026-05-07")
                    self.assertEqual(stale["raw_data"]["margin_date"], "2026-05-08")

                    north[date_field] = "2026-05-08" if date_field == "date" else "2026-05-08 15:00:00"
                    margin["date"] = "2026-05-07"
                    current = tracker.calculate_sentiment_for_date(**arguments, north_flow=north, margin_data=margin)
                    self.assertTrue(current["component_availability"]["north_flow"])
                    self.assertTrue(current["component_availability"]["margin_trading"])

                    del north[date_field]
                    del margin["date"]
                    undated = tracker.calculate_sentiment_for_date(**arguments, north_flow=north, margin_data=margin)
                    self.assertTrue(undated["component_availability"]["north_flow"])
                    self.assertTrue(undated["component_availability"]["margin_trading"])

    def test_daily_and_backfill_agree_when_funding_data_is_delayed(self):
        class DelayedFundingFetcher(FakeHistoryFetcher):
            def get_north_flow_historical(self, years=1):
                return super().get_north_flow_historical(years)[:-1]

            def get_margin_trading_historical(self, years=1):
                return super().get_margin_trading_historical(years)[:-1]

        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = DelayedFundingFetcher()
            tracker = SentimentTracker(fetcher=fetcher)

            historical = tracker.backfill_history(days=1, end_date=fetcher.dates[-1])[-1]
            daily = tracker.run()

            self.assertEqual(historical["component_availability"], daily["component_availability"])
            self.assertEqual(historical["coverage"], daily["coverage"])
            self.assertEqual(historical["sentiment_score"], daily["sentiment_score"])
            self.assertEqual(daily["raw_data"]["north_date"], fetcher.dates[-2])
            self.assertEqual(daily["raw_data"]["margin_date"], fetcher.dates[-2])

    def test_scoring_excludes_future_and_older_than_one_year_data(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            tracker = SentimentTracker(fetcher=object())
            dates = ["2024-05-08", "2026-05-01", "2026-05-04", "2026-05-05", "2026-05-06", "2026-05-07", "2026-05-08", "2026-05-11"]
            frame = pd.DataFrame({
                "date": dates,
                "amount": [100.0] * 8,
                "amount_ma20": [100.0] * 8,
                "amount_ratio": [99.0, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 99.0],
                "volatility_20d": [99.0, 10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 99.0],
                "change_pct": [99.0, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 99.0],
                "momentum_20d": [99.0, .01, .02, .03, .04, .05, .06, 99.0],
            })
            states = [{"date": date, "up_ratio": value, "source": "test"} for date, value in zip(dates, [99, 40, 41, 42, 43, 44, 45, 99])]
            margin = {date: {"margin_balance": 1000.0, "net_change": value, "source": "test"} for date, value in zip(dates, [99, 1, 2, 3, 4, 5, 6, 99])}
            north = {date: {"net_flow": value, "source": "test"} for date, value in zip(dates, [99, 1, 2, 3, 4, 5, 6, 99])}
            arguments = dict(date_str="2026-05-08", index_row=frame.iloc[-2], breadth_data=states[-2], cross_section_data=states[-2], north_flow=north[dates[-2]], margin_data=margin[dates[-2]])

            expected = tracker.calculate_sentiment_for_date(**arguments, history_frame=frame.iloc[1:-1], breadth_history=states[1:-1], cross_section_history=states[1:-1], margin_lookup={date: margin[date] for date in dates[1:-1]}, north_lookup={date: north[date] for date in dates[1:-1]})
            actual = tracker.calculate_sentiment_for_date(**arguments, history_frame=frame, breadth_history=states, cross_section_history=states, margin_lookup=margin, north_lookup=north)

            self.assertEqual(actual["components"], expected["components"])
            self.assertEqual(actual["sentiment_score"], expected["sentiment_score"])

    def test_margin_lags_one_trading_day_in_daily_and_backfill(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)

            historical = tracker.backfill_history(days=1, end_date=fetcher.dates[-1])[-1]
            daily = tracker.run()

            for result in (historical, daily):
                self.assertTrue(result["component_availability"]["margin_trading"])
                self.assertEqual(result["raw_data"]["margin_date"], fetcher.dates[-2])
            self.assertEqual(historical["components"], daily["components"])

    def test_margin_unavailable_when_previous_day_missing(self):
        class MissingPreviousMarginFetcher(FakeHistoryFetcher):
            def get_margin_trading_historical(self, years=1):
                rows = super().get_margin_trading_historical(years)
                return [row for row in rows if row["date"] != self.dates[-2]]

        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            tracker = SentimentTracker(fetcher=MissingPreviousMarginFetcher())
            daily = tracker.run()

            self.assertFalse(daily["component_availability"]["margin_trading"])
            self.assertIsNone(daily["components"]["margin_trading"])

    def test_daily_run_fetches_only_uncached_days(self):
        class CountingFetcher(FakeHistoryFetcher):
            def __init__(self):
                super().__init__()
                self.calls = []

            def get_market_breadth_history(self, years=1):
                self.calls.append("breadth_bulk")
                return super().get_market_breadth_history(years)

            def get_cross_sectional_state_history(self, years=1):
                self.calls.append("cross_section_bulk")
                return super().get_cross_sectional_state_history(years)

            def get_market_breadth(self, date=None):
                self.calls.append(("breadth", date))
                return next(item for item in FakeHistoryFetcher.get_market_breadth_history(self) if item["date"] == date)

            def get_cross_sectional_state(self, date=None):
                self.calls.append(("cross_section", date))
                return next(item for item in FakeHistoryFetcher.get_cross_sectional_state_history(self) if item["date"] == date)

        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir), patch("sentiment_tracker.datetime") as clock:
            fetcher = CountingFetcher()
            tracker = SentimentTracker(fetcher=fetcher)
            clock.now.return_value = datetime(2026, 5, 8, 17)
            first = tracker.run()

            clock.now.return_value = datetime(2026, 5, 9, 9)
            fetcher.calls.clear()
            second = tracker.run()

            # Only 2026-05-08 was still "today" on the first run, so only it is refetched.
            self.assertEqual(fetcher.calls, [("breadth", "2026-05-08"), ("cross_section", "2026-05-08")])
            self.assertEqual(first["components"], second["components"])
            with open(tracker.breadth_file, encoding="utf-8") as handle:
                self.assertEqual([item["date"] for item in json.load(handle)], fetcher.dates)

    def test_cached_cross_section_without_style_is_refetched(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)
            stale = dict(fetcher.get_cross_sectional_state(date=fetcher.dates[3]), microcap_change=None, style_spread=None)
            tracker._save_cross_section_history(fetcher.get_cross_sectional_state_history())
            tracker._save_cross_section_history([stale])

            requested = []
            original = fetcher.get_cross_sectional_state
            fetcher.get_cross_sectional_state = lambda date=None: requested.append(date) or original(date=date)
            data = tracker.fetch_all_data()

            self.assertIn(fetcher.dates[3], requested)
            row = next(item for item in data["cross_section_history"] if item["date"] == fetcher.dates[3])
            self.assertIsNotNone(row["style_spread"])

    def test_current_cross_section_fetched_without_bulk_history(self):
        class NoBulkFetcher:
            offline_mode = False

            def __init__(self):
                self.inner = FakeHistoryFetcher()
                self.dates = self.inner.dates

            def __getattr__(self, name):
                if name == "get_cross_sectional_state_history":
                    raise AttributeError(name)
                return getattr(self.inner, name)

        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir), patch("sentiment_tracker.INCREMENTAL_FETCH_LIMIT", 0):
            fetcher = NoBulkFetcher()
            self.assertFalse(hasattr(fetcher, "get_cross_sectional_state_history"))
            data = SentimentTracker(fetcher=fetcher).fetch_all_data()

            self.assertIsNotNone(data["cross_section"])
            self.assertEqual(data["cross_section"]["date"], fetcher.dates[-1])

    def test_incremental_history_matches_bulk_history(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            fetcher = FakeHistoryFetcher()
            tracker = SentimentTracker(fetcher=fetcher)
            with patch("sentiment_tracker.INCREMENTAL_FETCH_LIMIT", 0):
                bulk = tracker.fetch_all_data()
            with patch("sentiment_tracker.INCREMENTAL_FETCH_LIMIT", 100):
                incremental = SentimentTracker(fetcher=fetcher).fetch_all_data()

            for key in ("breadth", "breadth_history", "cross_section", "cross_section_history"):
                self.assertEqual(bulk[key], incremental[key])

    def test_save_result_propagates_write_failures(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            tracker = SentimentTracker(fetcher=object())
            with patch("builtins.open", side_effect=PermissionError("write denied")):
                with self.assertRaises(PermissionError):
                    tracker.save_result({"date": "2026-05-08", "sentiment_score": 50.0})

    def test_cross_section_save_propagates_replace_failures(self):
        with tempfile.TemporaryDirectory() as tmp_dir, patch("sentiment_tracker.DATA_DIR", tmp_dir):
            tracker = SentimentTracker(fetcher=object())
            with patch("sentiment_tracker.os.replace", side_effect=PermissionError("replace denied")):
                with self.assertRaises(PermissionError):
                    tracker._save_cross_section({"date": "2026-05-08", "up_ratio": 50.0})


if __name__ == "__main__":
    unittest.main()
