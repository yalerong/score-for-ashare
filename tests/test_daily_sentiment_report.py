import unittest
from unittest.mock import patch

import daily_sentiment_report


class FakeFetcher:
    pass


class FakeTracker:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher

    def run(self):
        return {
            "sentiment_score": 58.42,
            "sentiment_level": "中性",
            "coverage": 0.85,
        }


class DailySentimentReportTests(unittest.TestCase):
    def test_daily_report_attempts_wechat_mp_after_email(self):
        with (
            patch("data_fetcher_tushare.DataFetcherTushare", FakeFetcher),
            patch("sentiment_tracker.SentimentTracker", FakeTracker),
            patch("sentiment_email_sender.main", return_value=False) as email_main,
            patch("sentiment_wechat_mp_sender.main", return_value=True) as wechat_main,
        ):
            result = daily_sentiment_report.run_daily_report()

        self.assertTrue(result)
        email_main.assert_called_once()
        wechat_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
