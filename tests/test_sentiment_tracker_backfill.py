import os
import tempfile
import unittest
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

            results = tracker.backfill_history(days=8)

            self.assertTrue(fetcher.cross_section_history_called)
            self.assertEqual(len(results), 8)
            self.assertTrue(
                all(item["raw_data"]["cross_section_source"] == "test_cross_section" for item in results)
            )


if __name__ == "__main__":
    unittest.main()
