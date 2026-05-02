#!/usr/bin/env python3
"""
Evaluate whether the sentiment score has predictive power for future index returns.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config import DATA_DIR
from data_fetcher_v2 import DataFetcherV2
from sentiment_scoring import build_forward_return_frame, evaluate_signal_against_returns


def load_sentiment_history(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    data = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(data)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    frame["sentiment_score"] = pd.to_numeric(frame["sentiment_score"], errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def main():
    history_path = Path(DATA_DIR) / "sentiment_history.json"
    sentiment = load_sentiment_history(history_path)
    if sentiment.empty:
        print("No sentiment history found.")
        return

    fetcher = DataFetcherV2()
    years = max(1, int((len(sentiment) / 240) + 1))
    index_df = fetcher.get_index_data_range("000001", years=years)
    if index_df is None or index_df.empty:
        print("Unable to fetch index history for evaluation.")
        return

    price_frame = index_df[["date", "close"]].copy()
    price_frame = build_forward_return_frame(price_frame, price_col="close", horizons=(5, 10, 20))

    merged = sentiment.merge(price_frame, on="date", how="inner")
    report = evaluate_signal_against_returns(
        merged,
        signal_col="sentiment_score",
        return_cols=["forward_return_5d", "forward_return_10d", "forward_return_20d"],
        buckets=5,
    )

    print("Rank IC")
    for key, value in report["rank_ic"].items():
        print(f"  {key}: {value}")

    print("\nBucket Mean Returns")
    for key, rows in report["bucket_summary"].items():
        print(f"  {key}")
        for row in rows:
            print(
                f"    bucket {int(row['bucket'])}: "
                f"mean={row['mean']:.4f}, median={row['median']:.4f}, count={int(row['count'])}"
            )


if __name__ == "__main__":
    main()
