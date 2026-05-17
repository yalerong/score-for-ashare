#!/usr/bin/env python3
"""
Run daily sentiment calculation and then send the email report.
"""

from __future__ import annotations

import sys
from datetime import datetime


def run_daily_report():
    print("=" * 70)
    print("A股情绪指标 - 每日报告")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        from data_fetcher_tushare import DataFetcherTushare
        from sentiment_tracker import SentimentTracker

        print("\n[1/2] 计算情绪指标")
        tracker = SentimentTracker(fetcher=DataFetcherTushare())
        result = tracker.run()
        print(f"总分: {result['sentiment_score']:.2f}")
        print(f"等级: {result['sentiment_level']}")
        print(f"覆盖度: {result.get('coverage', 0):.2f}")
    except Exception as exc:
        print(f"[FAIL] 情绪计算失败: {exc}")
        return False

    try:
        from sentiment_email_sender import main as send_email_main

        print("\n[2/2] 发送邮件")
        return bool(send_email_main())
    except Exception as exc:
        print(f"[FAIL] 邮件发送失败: {exc}")
        return False


if __name__ == "__main__":
    raise SystemExit(0 if run_daily_report() else 1)
