#!/usr/bin/env python3
"""
Run daily sentiment calculation and then send the email report.
"""

from __future__ import annotations

import sys
from datetime import datetime


def _is_a_share_trading_day():
    from data_fetcher_tushare import ensure_token, get_pro_api

    ensure_token()
    today = datetime.now().strftime("%Y%m%d")
    df = get_pro_api().trade_cal(exchange="SSE", start_date=today, end_date=today)
    if df.empty:
        return True
    return int(df.iloc[0]["is_open"]) == 1


def run_daily_report():
    print("=" * 70)
    print("A股情绪指标 - 每日报告")
    print("=" * 70)
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        if not _is_a_share_trading_day():
            print("\n[SKIP] 今天不是 A 股交易日(节假日/调休),跳过")
            return False
    except Exception as exc:
        print(f"[WARN] 交易日检查失败,继续按原流程跑: {exc}")

    try:
        from data_fetcher_tushare import DataFetcherTushare
        from sentiment_tracker import SentimentTracker

        print("\n[1/3] 计算情绪指标")
        tracker = SentimentTracker(fetcher=DataFetcherTushare())
        result = tracker.run()
        print(f"总分: {result['sentiment_score']:.2f}")
        print(f"等级: {result['sentiment_level']}")
        print(f"覆盖度: {result.get('coverage', 0):.2f}")
    except Exception as exc:
        print(f"[FAIL] 情绪计算失败: {exc}")
        return False

    sent = False

    try:
        from sentiment_email_sender import main as send_email_main

        print("\n[2/3] 发送邮件")
        sent = bool(send_email_main()) or sent
    except Exception as exc:
        print(f"[FAIL] 邮件发送失败: {exc}")

    try:
        from sentiment_wechat_mp_sender import main as send_wechat_mp_main

        print("\n[3/3] 微信公众号草稿/发布")
        sent = bool(send_wechat_mp_main()) or sent
    except Exception as exc:
        print(f"[FAIL] 微信公众号发送失败: {exc}")

    return sent


if __name__ == "__main__":
    raise SystemExit(0 if run_daily_report() else 1)
