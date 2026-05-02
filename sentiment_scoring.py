#!/usr/bin/env python3
"""
Core scoring and evaluation utilities for market sentiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence

import numpy as np
import pandas as pd


def _clean_series(values: Iterable[float]) -> pd.Series:
    series = pd.Series(list(values), dtype="float64")
    return series.replace([np.inf, -np.inf], np.nan).dropna()


@dataclass
class SentimentScorer:
    neutral_score: float = 50.0
    min_history: int = 5

    def percentile_score(self, value: float, history: Iterable[float], bullish: bool = True) -> float:
        if value is None or pd.isna(value):
            return self.neutral_score

        history_series = _clean_series(history)
        if len(history_series) < self.min_history:
            return self.neutral_score

        percentile = float((history_series <= float(value)).mean())
        score = percentile * 100.0
        if not bullish:
            score = 100.0 - score

        return float(np.clip(score, 0.0, 100.0))

    def bounded_linear_score(self, value: float, lower: float, upper: float, bullish: bool = True) -> float:
        if value is None or pd.isna(value) or lower == upper:
            return self.neutral_score

        clipped = float(np.clip(value, lower, upper))
        score = (clipped - lower) / (upper - lower) * 100.0
        if not bullish:
            score = 100.0 - score
        return float(np.clip(score, 0.0, 100.0))

    def combine_component_scores(
        self,
        components: Mapping[str, Mapping[str, float]],
        weights: Mapping[str, float],
    ) -> Dict[str, float]:
        weighted_score = 0.0
        active_weight = 0.0
        configured_weight = 0.0
        available_components = 0

        for name, weight in weights.items():
            configured_weight += float(weight)
            component = components.get(name) or {}
            if not component.get("available", True):
                continue

            score = component.get("score")
            if score is None or pd.isna(score):
                continue

            weighted_score += float(score) * float(weight)
            active_weight += float(weight)
            available_components += 1

        if active_weight == 0:
            return {
                "score": self.neutral_score,
                "coverage": 0.0,
                "available_components": 0,
            }

        return {
            "score": weighted_score / active_weight,
            "coverage": active_weight / configured_weight if configured_weight else 0.0,
            "available_components": available_components,
        }


def build_forward_return_frame(frame: pd.DataFrame, price_col: str = "close", horizons: Sequence[int] = (5, 10, 20)) -> pd.DataFrame:
    result = frame.copy()
    result = result.sort_values("date").reset_index(drop=True)

    prices = pd.to_numeric(result[price_col], errors="coerce")
    for horizon in horizons:
        future_price = prices.shift(-horizon)
        result[f"forward_return_{horizon}d"] = future_price / prices - 1.0

    return result


def _safe_rank_ic(signal: pd.Series, returns: pd.Series) -> float | None:
    aligned = pd.concat([signal, returns], axis=1).dropna()
    if len(aligned) < 5:
        return None

    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman")
    if pd.isna(corr):
        return None
    return float(corr)


def evaluate_signal_against_returns(
    frame: pd.DataFrame,
    signal_col: str,
    return_cols: Sequence[str],
    buckets: int = 5,
) -> Dict[str, object]:
    result: Dict[str, object] = {"rank_ic": {}, "bucket_summary": {}}
    signal = pd.to_numeric(frame[signal_col], errors="coerce")

    for return_col in return_cols:
        future_returns = pd.to_numeric(frame[return_col], errors="coerce")
        result["rank_ic"][return_col] = _safe_rank_ic(signal, future_returns)

        sample = pd.DataFrame({"signal": signal, "future_return": future_returns}).dropna()
        if len(sample) < buckets:
            result["bucket_summary"][return_col] = []
            continue

        ranked = sample["signal"].rank(method="first")
        sample["bucket"] = pd.qcut(ranked, buckets, labels=False) + 1
        grouped = sample.groupby("bucket")["future_return"].agg(["mean", "median", "count"])
        grouped = grouped.reset_index()
        result["bucket_summary"][return_col] = grouped.to_dict("records")

    return result


def summarize_cross_section_state(
    date: str,
    spot_changes: Sequence[float],
    universe_size: int | None = None,
    limit_up_count: int | None = None,
    strong_pool_count: int | None = None,
    previous_limit_up_return: float | None = None,
    previous_limit_up_up_ratio: float | None = None,
    microcap_change: float | None = None,
    largecap_change: float | None = None,
    source: str = "cross_section",
) -> Dict[str, object]:
    changes = _clean_series(spot_changes)
    sample_size = int(len(changes))
    effective_universe = int(universe_size) if universe_size else sample_size

    up_ratio = float((changes > 0).mean() * 100) if sample_size else None
    median_change = float(changes.median()) if sample_size else None
    dispersion = float(changes.std(ddof=0)) if sample_size > 1 else 0.0
    limit_up_density = (
        float(limit_up_count / effective_universe)
        if limit_up_count is not None and effective_universe
        else None
    )
    strong_ratio = (
        float(strong_pool_count / (strong_pool_count + limit_up_count))
        if strong_pool_count is not None and limit_up_count is not None and (strong_pool_count + limit_up_count) > 0
        else None
    )
    style_spread = (
        float(microcap_change - largecap_change)
        if microcap_change is not None and largecap_change is not None
        else None
    )

    return {
        "date": date,
        "up_ratio": up_ratio,
        "median_change": median_change,
        "dispersion": dispersion,
        "limit_up_count": limit_up_count,
        "limit_up_density": limit_up_density,
        "strong_pool_count": strong_pool_count,
        "strong_ratio": strong_ratio,
        "previous_limit_up_return": previous_limit_up_return,
        "previous_limit_up_up_ratio": previous_limit_up_up_ratio,
        "microcap_change": microcap_change,
        "largecap_change": largecap_change,
        "style_spread": style_spread,
        "sample_size": sample_size,
        "universe_size": effective_universe,
        "source": source,
    }
