#!/usr/bin/env python3
"""
直接计算今日情绪指标（使用真实数据）
"""

import os
import sys

# 创建必要目录
os.makedirs('data', exist_ok=True)
os.makedirs('logs', exist_ok=True)

print("=" * 70)
print("A股情绪指数追踪器 - 计算今日情绪")
print("=" * 70)

from sentiment_tracker import SentimentTracker
from data_fetcher_tushare import DataFetcherTushare as DataFetcher

# 创建数据获取器（使用真实数据）
fetcher = DataFetcher()

# 创建情绪追踪器
tracker = SentimentTracker(fetcher=fetcher)

# 运行计算
result = tracker.run()

if result:
    print("\n" + "=" * 70)
    print(f"执行成功: {result['sentiment_score']:.1f}分")
    print("=" * 70)
else:
    print("\n执行失败")
