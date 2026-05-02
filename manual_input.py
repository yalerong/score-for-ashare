#!/usr/bin/env python3
"""
手动输入今日数据，用于网络受限时获取真实情绪指标。
分数通过 SentimentScorer.bounded_linear_score 计算，与主流程使用相同的权重和等级定义。
注意：手动分数基于绝对值映射（非历史百分位），与自动分数尺度不完全可比，保存时会标记 source='manual_input'。
"""

import os
from datetime import datetime

from config import DATA_DIR, SENTIMENT_LEVELS, SENTIMENT_WEIGHTS
from sentiment_scoring import SentimentScorer


def get_float_input(prompt, default=None):
    while True:
        try:
            value = input(prompt).strip()
            if value == "" and default is not None:
                return default
            return float(value)
        except ValueError:
            print("请输入有效数字")


def get_int_input(prompt, default=None):
    while True:
        try:
            value = input(prompt).strip()
            if value == "" and default is not None:
                return default
            return int(value)
        except ValueError:
            print("请输入有效整数")


def main():
    scorer = SentimentScorer()

    print("=" * 60)
    print("手动输入今日A股数据")
    print("=" * 60)
    print("\n请从您的股票软件或网站获取以下数据：")
    print("（东方财富、同花顺、雪球等）\n")

    print("--- 上证指数数据 ---")
    index_close = get_float_input("上证指数收盘点位 (如 3889.08): ")
    index_change = get_float_input("涨跌幅 % (如 +1.23 或 -0.56): ")
    volume = get_float_input("两市成交额（亿元） (如 12500): ")

    print("\n--- 市场涨跌统计 ---")
    up_count = get_int_input("上涨家数: ")
    down_count = get_int_input("下跌家数: ")
    limit_up = get_int_input("涨停家数: ")
    limit_down = get_int_input("跌停家数: ")

    print("\n--- 北向资金（沪深港通）---")
    north_flow = get_float_input("今日净流入（亿元，负数表示流出）: ")

    print("\n--- 融资融券（可选，直接回车跳过）---")
    margin_change_input = input("融资余额变化（亿元，负数表示减少）: ").strip()
    has_margin = margin_change_input != ""
    margin_change = float(margin_change_input) if has_margin else 0.0

    print("\n" + "=" * 60)
    print("计算情绪指标...")
    print("=" * 60)

    # ── 各维度用 bounded_linear_score 计算 ──

    # market_breadth: 上涨占比, 10%-90% 映射到 0-100
    total_stocks = up_count + down_count + 1
    up_ratio = up_count / total_stocks * 100
    breadth_score = scorer.bounded_linear_score(up_ratio, lower=10, upper=90, bullish=True)

    # volume_change: 成交额, 3000亿-20000亿 映射到 0-100
    volume_score = scorer.bounded_linear_score(volume, lower=3000, upper=20000, bullish=True)

    # volatility: 日振幅近似, 0%-40% 映射, bearish (越高分数越低)
    volatility = abs(index_change) * 2
    volatility_score = scorer.bounded_linear_score(volatility, lower=0, upper=40, bullish=False)

    # north_flow: 净流入 -100亿到+200亿, bullish
    north_score = scorer.bounded_linear_score(north_flow, lower=-100, upper=200, bullish=True)

    # margin_trading: 余额变化 -100亿到+100亿, bullish
    margin_score = scorer.bounded_linear_score(margin_change, lower=-100, upper=100, bullish=True)

    # trend: 指数涨跌 -5%到+5%, bullish
    trend_score = scorer.bounded_linear_score(index_change, lower=-5, upper=5, bullish=True)

    # ── 用 config.py 权重组合 ──
    components = {
        "market_breadth": {"score": breadth_score, "available": True},
        "cross_section": {"score": None, "available": False},
        "volume_change": {"score": volume_score, "available": True},
        "volatility": {"score": volatility_score, "available": True},
        "north_flow": {"score": north_score, "available": True},
        "margin_trading": {"score": margin_score, "available": has_margin},
        "trend": {"score": trend_score, "available": True},
    }

    composite = scorer.combine_component_scores(components, SENTIMENT_WEIGHTS)
    total_score = round(composite["score"], 2)
    coverage = round(composite["coverage"], 4)

    # ── 确定情绪等级 ──
    level = "中性"
    for level_name, (lo, hi) in SENTIMENT_LEVELS.items():
        if lo <= total_score <= hi:
            level = level_name
            break

    # ── 显示结果 ──
    print(f"\n[情绪指标] {total_score:.1f}分")
    print(f"[情绪等级] {level}")
    print(f"[覆盖度] {coverage:.0%} ({composite['available_components']} 组件)")
    print(f"\n[分项指标]")
    labels = {
        "market_breadth": ("市场涨跌广度", up_ratio),
        "volume_change": ("成交量活跃度", volume),
        "volatility": ("波动率", volatility),
        "north_flow": ("北向资金", north_flow),
        "margin_trading": ("融资融券", margin_change),
        "trend": ("指数涨跌", index_change),
    }
    units = {
        "market_breadth": "%",
        "volume_change": "亿",
        "volatility": "%",
        "north_flow": "亿",
        "trend": "%",
        "margin_trading": "亿",
    }
    for key, (label, raw_val) in labels.items():
        score_val = components[key]["score"]
        available = components[key]["available"]
        if available and score_val is not None:
            fmt = f"+{raw_val:.1f}" if raw_val > 0 else f"{raw_val:.1f}"
            print(f"   {label}: {score_val:.1f}分 ({fmt}{units.get(key, '')})")
        else:
            print(f"   {label}: -- (未输入)")

    # ── 保存数据 ──
    save = input("\n是否保存到历史数据？(y/n): ").strip().lower()
    if save == "y":
        date_str = datetime.now().strftime("%Y-%m-%d")

        result = {
            "timestamp": date_str + " 15:00:00",
            "date": date_str,
            "sentiment_score": total_score,
            "sentiment_level": level,
            "coverage": coverage,
            "available_components": composite["available_components"],
            "components": {
                "market_breadth": round(breadth_score, 2),
                "cross_section": 0,
                "volume_change": round(volume_score, 2),
                "volatility": round(volatility_score, 2),
                "north_flow": round(north_score, 2),
                "margin_trading": round(margin_score, 2),
                "index_change": round(trend_score, 2),
                "trend": round(trend_score, 2),
            },
            "raw_data": {
                "index_close": index_close,
                "index_change": index_change,
                "volume": volume * 1e8,
                "up_count": up_count,
                "down_count": down_count,
                "limit_up": limit_up,
                "limit_down": limit_down,
                "north_flow": north_flow * 1e8,
                "breadth_source": "manual_input",
                "cross_section_source": "manual_input",
                "north_source": "manual_input",
                "margin_source": "manual_input",
                "trend_source": "manual_input",
            },
        }

        from sentiment_tracker import SentimentTracker

        tracker = SentimentTracker()
        tracker.save_result(result)
        print(f"\n已保存到历史数据")
        print(f"   当前总记录数: {len(tracker.history)}")


if __name__ == "__main__":
    main()
