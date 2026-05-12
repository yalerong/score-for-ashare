#!/usr/bin/env python3
"""
Market sentiment tracker for A-share indices.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from config import DATA_DIR, LOG_CONFIG, SENTIMENT_LEVELS, SENTIMENT_WEIGHTS
from data_fetcher_v2 import DataFetcherV2 as DataFetcher
from sentiment_scoring import SentimentScorer


logger = logging.getLogger(__name__)


class SentimentTracker:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher if fetcher else DataFetcher()
        self.scorer = SentimentScorer()
        self.data_file = os.path.join(DATA_DIR, "sentiment_history.json")
        self.cross_section_file = os.path.join(DATA_DIR, "cross_section_history.json")
        self.history = self.load_history()

    def load_history(self):
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:
                logger.error("Failed to load sentiment history: %s", exc)
        return []

    def save_history(self):
        try:
            tmp_path = f"{self.data_file}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self.history, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.data_file)
        except Exception as exc:
            logger.error("Failed to save sentiment history: %s", exc)

    def _load_cross_section_history(self):
        if os.path.exists(self.cross_section_file):
            try:
                with open(self.cross_section_file, "r", encoding="utf-8") as handle:
                    return json.load(handle)
            except Exception as exc:
                logger.error("Failed to load cross_section history: %s", exc)
        return []

    def _save_cross_section(self, cross_section_data):
        if not cross_section_data:
            return
        history = self._load_cross_section_history()
        date_str = cross_section_data.get("date")
        if not date_str:
            return
        for idx, item in enumerate(history):
            if item.get("date") == date_str:
                history[idx] = cross_section_data
                break
        else:
            history.append(cross_section_data)
        history.sort(key=lambda item: item.get("date", ""))
        try:
            tmp_path = f"{self.cross_section_file}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(history, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.cross_section_file)
        except Exception as exc:
            logger.error("Failed to save cross_section history: %s", exc)

    def _normalize_weight_keys(self):
        weights = dict(SENTIMENT_WEIGHTS)
        if "index_change" in weights and "trend" not in weights:
            weights["trend"] = weights.pop("index_change")
        if "fear_greed_index" in weights and "trend" not in weights:
            weights["trend"] = weights.pop("fear_greed_index")
        return weights

    def _prepare_index_features(self, index_df: pd.DataFrame) -> pd.DataFrame:
        frame = index_df.copy()
        frame = frame.sort_values("date").reset_index(drop=True)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["amount"] = pd.to_numeric(frame["amount"], errors="coerce")
        frame["change_pct"] = pd.to_numeric(frame["change_pct"], errors="coerce")

        frame["daily_return"] = frame["close"].pct_change()
        frame["volatility_20d"] = frame["daily_return"].rolling(20).std() * np.sqrt(252) * 100
        frame["amount_ma20"] = frame["amount"].rolling(20).median()
        frame["amount_ratio"] = frame["amount"] / frame["amount_ma20"]
        frame["close_ma20"] = frame["close"].rolling(20).mean()
        frame["close_ma60"] = frame["close"].rolling(60).mean()
        frame["momentum_20d"] = frame["close"] / frame["close"].shift(20) - 1.0
        frame["distance_ma20"] = frame["close"] / frame["close_ma20"] - 1.0
        frame["distance_ma60"] = frame["close"] / frame["close_ma60"] - 1.0
        return frame

    def _build_history_lookup(self, rows, value_keys):
        lookup = {}
        for item in rows or []:
            date = item.get("date")
            if not date:
                continue
            payload = {key: item.get(key) for key in value_keys}
            payload["source"] = item.get("source", "unknown")
            lookup[date] = payload
        return lookup

    def _score_breadth(self, breadth_data, breadth_history):
        if not breadth_data:
            return {"score": 50.0, "available": False, "source": "missing"}

        scores = []
        if breadth_data.get("up_ratio") is not None:
            scores.append(
                self.scorer.percentile_score(
                    breadth_data["up_ratio"],
                    [row.get("up_ratio") for row in breadth_history],
                    bullish=True,
                )
            )
        if breadth_data.get("median_change") is not None:
            scores.append(
                self.scorer.percentile_score(
                    breadth_data["median_change"],
                    [row.get("median_change") for row in breadth_history],
                    bullish=True,
                )
            )
        if breadth_data.get("breadth_thrust") is not None:
            scores.append(
                self.scorer.percentile_score(
                    breadth_data["breadth_thrust"],
                    [row.get("breadth_thrust") for row in breadth_history],
                    bullish=True,
                )
            )

        score = float(np.mean(scores)) if scores else 50.0
        return {"score": score, "available": bool(scores), "source": breadth_data.get("source", "unknown")}

    def _score_cross_section(self, state_data, state_history):
        if not state_data:
            return {"score": 50.0, "available": False, "source": "missing"}

        history = state_history or []
        scores = []
        bullish_fields = {
            "up_ratio": (35.0, 65.0),
            "median_change": (-2.0, 2.0),
            "limit_up_density": (0.0, 0.03),
            "strong_ratio": (0.2, 0.8),
            "previous_limit_up_return": (-5.0, 5.0),
            "previous_limit_up_up_ratio": (0.2, 0.8),
            "style_spread": (-2.0, 2.0),
        }
        bearish_fields = {"dispersion": (0.5, 4.0)}

        for field, bounds in bullish_fields.items():
            value = state_data.get(field)
            if value is None:
                continue
            hist_values = [row.get(field) for row in history]
            hist_count = len(pd.Series(hist_values, dtype="float64").dropna()) if hist_values else 0
            if hist_count >= self.scorer.min_history:
                scores.append(
                    self.scorer.percentile_score(
                        value,
                        hist_values,
                        bullish=True,
                    )
                )
            else:
                scores.append(self.scorer.bounded_linear_score(value, bounds[0], bounds[1], bullish=True))
        for field, bounds in bearish_fields.items():
            value = state_data.get(field)
            if value is None:
                continue
            hist_values = [row.get(field) for row in history]
            hist_count = len(pd.Series(hist_values, dtype="float64").dropna()) if hist_values else 0
            if hist_count >= self.scorer.min_history:
                scores.append(
                    self.scorer.percentile_score(
                        value,
                        hist_values,
                        bullish=False,
                    )
                )
            else:
                scores.append(self.scorer.bounded_linear_score(value, bounds[0], bounds[1], bullish=False))

        score = float(np.mean(scores)) if scores else 50.0
        return {"score": score, "available": bool(scores), "source": state_data.get("source", "unknown")}

    def _score_volume(self, row, history_frame):
        amount_ratio = row.get("amount_ratio")
        score = self.scorer.percentile_score(amount_ratio, history_frame["amount_ratio"], bullish=True)
        return {"score": score, "available": pd.notna(amount_ratio), "value": amount_ratio}

    def _score_volatility(self, row, history_frame):
        realized_vol = row.get("volatility_20d")
        score = self.scorer.percentile_score(realized_vol, history_frame["volatility_20d"], bullish=False)
        return {"score": score, "available": pd.notna(realized_vol), "value": realized_vol}

    def _score_north_flow(self, north_data, history_frame, row, north_lookup=None):
        if not north_data or north_data.get("net_flow") is None:
            return {"score": 50.0, "available": False, "source": "missing"}

        denominator = row.get("amount_ma20") or row.get("amount") or 1.0
        normalized_flow = float(north_data["net_flow"]) / float(denominator)
        north_lookup = north_lookup or {}
        history_values = []
        for _, hist_row in history_frame.iterrows():
            hist_date = hist_row["date"]
            hist_amount = hist_row.get("amount_ma20") or hist_row.get("amount") or np.nan
            hist_flow = north_lookup.get(hist_date, {}).get("net_flow")
            if hist_flow is None or pd.isna(hist_amount) or not hist_amount:
                continue
            history_values.append(float(hist_flow) / float(hist_amount))

        score = self.scorer.percentile_score(normalized_flow, history_values, bullish=True)
        return {
            "score": score,
            "available": True,
            "source": north_data.get("source", "unknown"),
            "value": normalized_flow,
        }

    def _score_margin(self, margin_data, margin_lookup):
        if not margin_data or margin_data.get("net_change") is None:
            return {"score": 50.0, "available": False, "source": "missing"}

        balance = margin_data.get("margin_balance") or np.nan
        if pd.isna(balance) or not balance:
            return {"score": 50.0, "available": False, "source": margin_data.get("source", "unknown")}

        normalized_change = float(margin_data["net_change"]) / float(balance)
        history_values = []
        for item in margin_lookup.values():
            hist_balance = item.get("margin_balance") or np.nan
            hist_change = item.get("net_change")
            if hist_change is None or pd.isna(hist_balance) or not hist_balance:
                continue
            history_values.append(float(hist_change) / float(hist_balance))

        score = self.scorer.percentile_score(normalized_change, history_values, bullish=True)
        return {
            "score": score,
            "available": True,
            "source": margin_data.get("source", "unknown"),
            "value": normalized_change,
        }

    def _score_trend(self, row, history_frame):
        sub_scores = []

        daily_return = row.get("change_pct")
        sub_scores.append(
            self.scorer.percentile_score(daily_return, history_frame["change_pct"], bullish=True)
        )

        momentum_20d = row.get("momentum_20d")
        if pd.notna(momentum_20d):
            sub_scores.append(
                self.scorer.percentile_score(momentum_20d, history_frame["momentum_20d"], bullish=True)
            )

        if pd.notna(row.get("distance_ma20")):
            sub_scores.append(
                self.scorer.bounded_linear_score(row["distance_ma20"], -0.08, 0.08, bullish=True)
            )
        if pd.notna(row.get("distance_ma60")):
            sub_scores.append(
                self.scorer.bounded_linear_score(row["distance_ma60"], -0.12, 0.12, bullish=True)
            )

        score = float(np.mean(sub_scores)) if sub_scores else 50.0
        return {"score": score, "available": bool(sub_scores), "value": momentum_20d}

    def calculate_sentiment_for_date(
        self,
        date_str,
        index_row,
        breadth_data=None,
        cross_section_data=None,
        north_flow=None,
        margin_data=None,
        history_frame=None,
        breadth_history=None,
        cross_section_history=None,
        margin_lookup=None,
        north_lookup=None,
    ):
        history_frame = history_frame if history_frame is not None else pd.DataFrame()
        breadth_history = breadth_history or []
        cross_section_history = cross_section_history or []
        margin_lookup = margin_lookup or {}

        components = {
            "market_breadth": self._score_breadth(breadth_data, breadth_history),
            "cross_section": self._score_cross_section(cross_section_data, cross_section_history),
            "volume_change": self._score_volume(index_row, history_frame),
            "volatility": self._score_volatility(index_row, history_frame),
            "north_flow": self._score_north_flow(north_flow, history_frame, index_row, north_lookup),
            "margin_trading": self._score_margin(margin_data, margin_lookup),
            "trend": self._score_trend(index_row, history_frame),
        }

        weights = self._normalize_weight_keys()
        composite = self.scorer.combine_component_scores(components, weights)
        sentiment_score = round(composite["score"], 2)

        return {
            "timestamp": f"{date_str} 15:00:00",
            "date": date_str,
            "sentiment_score": sentiment_score,
            "sentiment_level": self.get_sentiment_level(sentiment_score),
            "coverage": round(composite["coverage"], 4),
            "available_components": composite["available_components"],
            "components": {
                "market_breadth": round(components["market_breadth"]["score"], 2),
                "cross_section": round(components["cross_section"]["score"], 2),
                "volume_change": round(components["volume_change"]["score"], 2),
                "volatility": round(components["volatility"]["score"], 2),
                "north_flow": round(components["north_flow"]["score"], 2),
                "margin_trading": round(components["margin_trading"]["score"], 2),
                "index_change": round(components["trend"]["score"], 2),
                "trend": round(components["trend"]["score"], 2),
            },
            "raw_data": {
                "index_close": float(index_row.get("close", 0) or 0),
                "index_change": float(index_row.get("change_pct", 0) or 0),
                "daily_return": float(index_row.get("daily_return", 0) or 0),
                "amount": float(index_row.get("amount", 0) or 0),
                "volume": float(index_row.get("amount", 0) or 0),
                "breadth_source": components["market_breadth"].get("source", "unknown"),
                "cross_section_source": components["cross_section"].get("source", "unknown"),
                "north_source": components["north_flow"].get("source", "unknown"),
                "margin_source": components["margin_trading"].get("source", "unknown"),
            },
        }

    def get_sentiment_level(self, score):
        score = max(0, min(100, score))
        for level, (min_val, max_val) in SENTIMENT_LEVELS.items():
            if min_val <= score <= max_val:
                return level
        return "中性"

    def backfill_history(self, days=1100, symbol="000001"):
        if self.fetcher.offline_mode:
            raise RuntimeError(
                "Backfill is disabled in offline/mock mode to prevent data contamination."
            )
        years = max(1, math.ceil(days / 365))
        index_df = self.fetcher.get_index_data_range(symbol, years=years)
        if index_df is None or index_df.empty:
            raise RuntimeError("Unable to fetch index history for backfill.")

        index_df = self._prepare_index_features(index_df)
        breadth_history = self.fetcher.get_market_breadth_history(years=years)
        breadth_lookup = {item["date"]: item for item in breadth_history}
        cross_section_history = []
        north_history = self.fetcher.get_north_flow_historical(years=years)
        north_lookup = self._build_history_lookup(north_history, ["flow", "net_flow"])
        margin_history = self.fetcher.get_margin_trading_historical(years=years)
        margin_lookup = self._build_history_lookup(margin_history, ["margin_balance", "net_change"])

        results = []
        for idx, row in index_df.iterrows():
            history_slice = index_df.iloc[: idx + 1].copy()
            date_str = row["date"]
            result = self.calculate_sentiment_for_date(
                date_str=date_str,
                index_row=row,
                breadth_data=breadth_lookup.get(date_str),
                cross_section_data=None,
                north_flow=north_lookup.get(date_str),
                margin_data=margin_lookup.get(date_str),
                history_frame=history_slice,
                breadth_history=[item for item in breadth_history if item["date"] <= date_str],
                cross_section_history=cross_section_history,
                margin_lookup={k: v for k, v in margin_lookup.items() if k <= date_str},
                north_lookup=north_lookup,
            )
            results.append(result)

        existing = {item.get("date"): item for item in self.history}
        for result in results:
            existing[result["date"]] = result
        self.history = [existing[key] for key in sorted(existing)]
        self.save_history()
        return results

    def fetch_all_data(self):
        index_df = self.fetcher.get_index_data_range("000001", years=1)
        if index_df is not None and not index_df.empty:
            index_df = self._prepare_index_features(index_df)
            latest_trade_date = index_df.iloc[-1]["date"]
        else:
            latest_trade_date = datetime.now().strftime("%Y-%m-%d")

        return {
            "breadth": self.fetcher.get_market_breadth(date=latest_trade_date),
            "breadth_history": self.fetcher.get_market_breadth_history(years=1),
            "cross_section": self.fetcher.get_cross_sectional_state(date=latest_trade_date),
            "cross_section_history": self._load_cross_section_history(),
            "index_data": index_df,
            "north": self.fetcher.get_north_flow(),
            "north_history": self.fetcher.get_north_flow_historical(years=1),
            "margin": self.fetcher.get_margin_trading(),
            "margin_history": self.fetcher.get_margin_trading_historical(years=1),
        }

    def calculate_sentiment(self):
        return self.run()

    def save_result(self, result):
        target_date = result["date"]
        for idx, item in enumerate(self.history):
            if item.get("date") == target_date:
                self.history[idx] = result
                break
        else:
            self.history.append(result)
        self.history.sort(key=lambda item: item.get("date", ""))
        self.save_history()

    def visualize(self, result, save_path=None, show=True):
        if not MATPLOTLIB_AVAILABLE:
            return None

        labels = ["广度", "横截面", "成交", "波动", "北向", "两融", "趋势"]
        values = [
            result["components"]["market_breadth"],
            result["components"].get("cross_section", 50.0),
            result["components"]["volume_change"],
            result["components"]["volatility"],
            result["components"]["north_flow"],
            result["components"]["margin_trading"],
            result["components"]["trend"],
        ]

        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(labels, values, color="#2b6cb0")
        ax.set_ylim(0, 100)
        ax.set_title(f"市场情绪得分 {result['sentiment_score']:.1f}")
        ax.axhline(result["sentiment_score"], color="#c53030", linestyle="--", label="总分")
        ax.legend()

        if save_path:
            fig.savefig(save_path, bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)
        return save_path

    def run(self):
        components = self.fetch_all_data()
        index_df = components["index_data"]
        if index_df is None or index_df.empty:
            raise RuntimeError("Unable to calculate sentiment without index data.")

        index_source = str(index_df.attrs.get("source", "") or "").lower()
        latest = index_df.iloc[-1]
        north_lookup = self._build_history_lookup(components["north_history"], ["flow", "net_flow"])
        margin_lookup = self._build_history_lookup(components["margin_history"], ["margin_balance", "net_change"])

        result = self.calculate_sentiment_for_date(
            date_str=latest["date"],
            index_row=latest,
            breadth_data=components["breadth"],
            cross_section_data=components["cross_section"],
            north_flow=components["north"],
            margin_data=components["margin"],
            history_frame=index_df,
            breadth_history=components["breadth_history"],
            cross_section_history=components["cross_section_history"],
            margin_lookup=margin_lookup,
            north_lookup=north_lookup,
        )
        raw = result.get("raw_data", {})
        raw["index_source"] = index_source if index_source else "real"
        mock_sources = [
            k for k, v in raw.items()
            if k.endswith("_source") and v == "mock"
        ]
        if mock_sources or index_source == "mock":
            logger.warning(
                "Not saving result – mock data in: %s",
                ", ".join(k.replace("_source", "") for k in mock_sources) + (" index" if index_source == "mock" and not mock_sources else ""),
            )
        else:
            self.save_result(result)
            self._save_cross_section(components["cross_section"])
        return result

    def realtime_monitor(self, iterations=None, sleep_seconds=300):
        count = 0
        while True:
            result = self.run()
            raw = result.get("raw_data", {})
            has_mock = any(
                v == "mock" for k, v in raw.items() if k.endswith("_source")
            )
            mock_tag = " [MOCK]" if has_mock else ""
            print(
                f"{result['timestamp']} | score={result['sentiment_score']:.1f} | "
                f"level={result['sentiment_level']} | coverage={result['coverage']:.2f}{mock_tag}"
            )
            count += 1
            if iterations is not None and count >= iterations:
                break
            time.sleep(sleep_seconds)


def configure_logging():
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=getattr(logging, LOG_CONFIG.get("level", "INFO")),
        format=LOG_CONFIG.get("format"),
    )


if __name__ == "__main__":
    configure_logging()
    tracker = SentimentTracker()
    result = tracker.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
