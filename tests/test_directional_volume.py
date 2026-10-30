import unittest

import numpy as np
import pandas as pd

from sentiment_scoring import SentimentScorer
from sentiment_tracker import SentimentTracker


class DirectionalVolumeTests(unittest.TestCase):
    def setUp(self):
        self.tracker = SentimentTracker.__new__(SentimentTracker)
        self.tracker.scorer = SentimentScorer()
        self.history = pd.DataFrame(
            {
                "change_pct": [-0.2, 0.4, -0.7, 1.0, -1.3, 1.8],
                "amount_ratio": [1.0] * 6,
            }
        )

    def score(self, change, ratio, history=None):
        return self.tracker._score_volume(
            {"change_pct": change, "amount_ratio": ratio},
            self.history if history is None else history,
        )

    def test_up_day_more_volume_does_not_reduce_score(self):
        scores = [self.score(1.0, ratio)["score"] for ratio in [0.25, 0.75, 1.5, 2.0]]

        self.assertEqual(scores, sorted(scores))
        self.assertGreater(scores[0], 50.0)
        self.assertGreater(scores[-1], scores[0])

    def test_down_day_more_volume_does_not_raise_score(self):
        scores = [self.score(-1.0, ratio)["score"] for ratio in [0.25, 0.75, 1.5, 2.0]]

        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertLess(scores[0], 50.0)
        self.assertLess(scores[-1], scores[0])

    def test_equal_opposite_returns_are_symmetric_about_neutral(self):
        for ratio in [0.25, 0.75, 1.5, 2.0]:
            with self.subTest(ratio=ratio):
                bullish = self.score(1.0, ratio)
                bearish = self.score(-1.0, ratio)
                self.assertAlmostEqual(bullish["score"] + bearish["score"], 100.0)
                self.assertTrue(bullish["available"])
                self.assertTrue(bearish["available"])

    def test_flat_day_stays_neutral_even_with_high_volume(self):
        result = self.score(0.0, 5.0)

        self.assertEqual(result["score"], 50.0)
        self.assertTrue(result["available"])

    def test_insufficient_nonzero_history_stays_neutral(self):
        histories = [
            self.history.iloc[:4],
            pd.DataFrame({"change_pct": [0.0] * 10, "amount_ratio": [1.0] * 10}),
            pd.DataFrame(),
        ]
        for history in histories:
            for direction in [-1.0, 1.0]:
                with self.subTest(rows=len(history), direction=direction):
                    result = self.score(direction, 3.0, history)
                    self.assertEqual(result["score"], 50.0)
                    self.assertTrue(result["available"])

    def test_invalid_current_inputs_are_unavailable(self):
        for change, ratio in [
            (None, 1.0), (np.nan, 1.0), (np.inf, 1.0), (-np.inf, 1.0),
            (1.0, None), (1.0, np.nan), (1.0, np.inf), (1.0, -np.inf),
            (1.0, 0.0), (1.0, -1.0), (1e308, 1e308),
        ]:
            with self.subTest(change=change, ratio=ratio):
                result = self.score(change, ratio)
                self.assertEqual(result["score"], 50.0)
                self.assertFalse(result["available"])

    def test_invalid_or_zero_historical_pairs_do_not_change_score(self):
        invalid_rows = pd.DataFrame(
            {
                "change_pct": [0.0, np.nan, np.inf, 1.0, 1.0, 1.0, 1e308],
                "amount_ratio": [1.0, 1.0, 1.0, np.nan, 0.0, -1.0, 1e308],
            }
        )
        extended = pd.concat([self.history, invalid_rows], ignore_index=True)

        self.assertEqual(self.score(-1.0, 1.5)["score"], self.score(-1.0, 1.5, extended)["score"])

    def test_prepared_index_change_pct_controls_direction(self):
        index = pd.DataFrame(
            {
                "date": ["2026-10-29", "2026-10-30"],
                "close": [100.0, 99.0],
                "change_pct": [0.5, -1.0],
                "amount": [100.0, 200.0],
            }
        )
        prepared = self.tracker._prepare_index_features(index)
        latest = prepared.iloc[-1].copy()
        latest["amount_ratio"] = 2.0

        result = self.tracker._score_volume(latest, self.history)

        self.assertLess(result["score"], 50.0)


if __name__ == "__main__":
    unittest.main()
