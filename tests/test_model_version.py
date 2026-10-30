import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import config
from sentiment_tracker import SentimentTracker


class ModelVersionTests(unittest.TestCase):
    def arguments(self, tracker):
        dates = pd.bdate_range("2026-08-03", periods=40).strftime("%Y-%m-%d").tolist()
        frame = tracker._prepare_index_features(pd.DataFrame({
            "date": dates,
            "close": [100 + i * .1 for i in range(40)],
            "amount": [1e11 + i * 1e8 for i in range(40)],
            "change_pct": [(-1 if i % 2 else 1) * (i + 1) / 100 for i in range(40)],
        }))
        return dict(date_str=dates[-1], index_row=frame.iloc[-1], history_frame=frame,
                    north_lookup={date: {"net_flow": float(i + 1)} for i, date in enumerate(dates)})

    def test_unverified_north_proxy_is_excluded_from_scoring(self):
        with tempfile.TemporaryDirectory() as directory, patch("sentiment_tracker.DATA_DIR", directory):
            tracker = SentimentTracker(fetcher=object())
            arguments = self.arguments(tracker)
            high = tracker.calculate_sentiment_for_date(**arguments, north_flow={"date": arguments["date_str"], "net_flow": 1e15, "source": "tushare"})
            low = tracker.calculate_sentiment_for_date(**arguments, north_flow={"date": arguments["date_str"], "net_flow": -1e15, "source": "tushare"})

        self.assertEqual(high["sentiment_score"], low["sentiment_score"])
        self.assertFalse(high["component_availability"]["north_flow"])
        self.assertIsNone(high["components"]["north_flow"])
        self.assertNotIn("north_flow", high["component_weights"])
        self.assertNotIn("north_flow", high["effective_weights"])

    def test_results_record_model_and_effective_weights(self):
        with tempfile.TemporaryDirectory() as directory, patch("sentiment_tracker.DATA_DIR", directory):
            tracker = SentimentTracker(fetcher=object())
            result = tracker.calculate_sentiment_for_date(**self.arguments(tracker))

        self.assertEqual(result["model_version"], config.MODEL_VERSION)
        self.assertAlmostEqual(sum(result["effective_weights"].values()), 1.0)
        self.assertEqual(sum(weight > 0 for weight in result["effective_weights"].values()), result["available_components"])
        reconstructed = sum(result["components"][key] * weight for key, weight in result["effective_weights"].items() if weight > 0)
        self.assertAlmostEqual(result["sentiment_score"], reconstructed, delta=.011)


if __name__ == "__main__":
    unittest.main()
