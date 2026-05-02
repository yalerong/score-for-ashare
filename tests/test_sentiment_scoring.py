import unittest

import pandas as pd

from sentiment_scoring import (
    SentimentScorer,
    build_forward_return_frame,
    evaluate_signal_against_returns,
    summarize_cross_section_state,
)


class SentimentScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = SentimentScorer()

    def test_percentile_score_is_continuous(self):
        history = pd.Series([10, 20, 30, 40, 50, 60, 70, 80])

        score = self.scorer.percentile_score(55, history, bullish=True)

        self.assertGreater(score, 60)
        self.assertLess(score, 80)

    def test_bearish_metric_flips_score_direction(self):
        history = pd.Series([10, 20, 30, 40, 50, 60, 70, 80])

        low_vol_score = self.scorer.percentile_score(20, history, bullish=False)
        high_vol_score = self.scorer.percentile_score(70, history, bullish=False)

        self.assertGreater(low_vol_score, high_vol_score)

    def test_composite_score_reweights_missing_components(self):
        components = {
            "breadth": {"score": 80.0, "available": True},
            "volume": {"score": 60.0, "available": True},
            "volatility": {"score": 50.0, "available": True},
            "north_flow": {"score": 90.0, "available": False},
        }
        weights = {
            "breadth": 0.4,
            "volume": 0.2,
            "volatility": 0.2,
            "north_flow": 0.2,
        }

        result = self.scorer.combine_component_scores(components, weights)

        self.assertAlmostEqual(result["score"], 67.5, places=4)
        self.assertAlmostEqual(result["coverage"], 0.8, places=4)
        self.assertEqual(result["available_components"], 3)


class SignalEvaluationTests(unittest.TestCase):
    def test_build_forward_return_frame(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=5, freq="D"),
                "close": [100, 101, 103, 102, 104],
            }
        )

        result = build_forward_return_frame(frame, horizons=(1, 2))

        self.assertIn("forward_return_1d", result.columns)
        self.assertIn("forward_return_2d", result.columns)
        self.assertAlmostEqual(result.loc[0, "forward_return_1d"], 0.01, places=6)
        self.assertAlmostEqual(result.loc[0, "forward_return_2d"], 0.03, places=6)

    def test_signal_evaluation_produces_bucket_statistics(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=8, freq="D"),
                "sentiment_score": [20, 30, 40, 50, 60, 70, 80, 90],
                "forward_return_3d": [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04],
            }
        )

        report = evaluate_signal_against_returns(
            frame,
            signal_col="sentiment_score",
            return_cols=["forward_return_3d"],
            buckets=4,
        )

        self.assertIn("rank_ic", report)
        self.assertIn("bucket_summary", report)
        self.assertGreater(report["rank_ic"]["forward_return_3d"], 0.9)
        self.assertEqual(len(report["bucket_summary"]["forward_return_3d"]), 4)


class CrossSectionStateTests(unittest.TestCase):
    def test_summarize_cross_section_state_combines_limit_and_style_data(self):
        snapshot = summarize_cross_section_state(
            date="2026-05-01",
            spot_changes=[2.0, 1.0, -1.0, -2.0, 0.5],
            universe_size=5000,
            limit_up_count=42,
            strong_pool_count=18,
            previous_limit_up_return=1.6,
            previous_limit_up_up_ratio=0.62,
            microcap_change=1.8,
            largecap_change=0.4,
            source="composite",
        )

        self.assertEqual(snapshot["date"], "2026-05-01")
        self.assertAlmostEqual(snapshot["up_ratio"], 60.0, places=6)
        self.assertAlmostEqual(snapshot["limit_up_density"], 0.0084, places=6)
        self.assertAlmostEqual(snapshot["strong_ratio"], 0.3, places=6)
        self.assertAlmostEqual(snapshot["style_spread"], 1.4, places=6)
        self.assertEqual(snapshot["source"], "composite")


if __name__ == "__main__":
    unittest.main()
