import unittest
from datetime import datetime
from unittest.mock import patch

import daily_sentiment_report


class FakeFetcher:
    pass


def make_result(**overrides):
    result = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "sentiment_score": 58.42,
        "sentiment_level": "中性",
        "coverage": 1.0,
        "component_availability": {"market_breadth": True, "cross_section": True},
    }
    result.update(overrides)
    return result


class FakeTracker:
    result = make_result()

    def __init__(self, fetcher=None):
        self.fetcher = fetcher

    def run(self):
        return self.result


class DailySentimentReportTests(unittest.TestCase):
    def run_report(self, result):
        FakeTracker.result = result
        with (
            patch("daily_sentiment_report._is_a_share_trading_day", return_value=True),
            patch("data_fetcher_tushare.DataFetcherTushare", FakeFetcher),
            patch("sentiment_tracker.SentimentTracker", FakeTracker),
            patch("sentiment_email_sender.main", return_value=False) as email_main,
            patch("sentiment_wechat_mp_sender.main", return_value=True) as wechat_main,
        ):
            sent = daily_sentiment_report.run_daily_report()
        return sent, email_main, wechat_main

    def test_daily_report_attempts_wechat_mp_after_email(self):
        sent, email_main, wechat_main = self.run_report(make_result())

        self.assertTrue(sent)
        email_main.assert_called_once()
        wechat_main.assert_called_once()

    def test_stale_result_is_not_sent(self):
        sent, email_main, wechat_main = self.run_report(make_result(date="2000-01-03"))

        self.assertFalse(sent)
        email_main.assert_not_called()
        wechat_main.assert_not_called()

    def test_missing_stock_snapshot_is_not_sent(self):
        availability = {"market_breadth": False, "cross_section": False}
        sent, email_main, wechat_main = self.run_report(make_result(component_availability=availability))

        self.assertFalse(sent)
        email_main.assert_not_called()
        wechat_main.assert_not_called()


if __name__ == "__main__":
    unittest.main()
