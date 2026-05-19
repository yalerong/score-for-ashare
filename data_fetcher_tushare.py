#!/usr/bin/env python3
"""
Tushare-backed data fetcher for the A-share sentiment tracker.

公开方法对齐旧的 DataFetcherV2，sentiment_tracker 直接 import 即可。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import tushare as ts

try:
    from dotenv import load_dotenv
    load_dotenv()
    _extra_env = os.getenv("SENTIMENT_TUSHARE_ENV")
    if _extra_env and os.path.isfile(_extra_env):
        load_dotenv(_extra_env)
except ImportError:
    pass


_TOKEN_LOCK = threading.Lock()
_PRO_API: Optional["ts.pro_api"] = None


def ensure_token() -> None:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN 未配置。请在项目根目录创建 .env 文件并填入：\n"
            "    TUSHARE_TOKEN=your_token_here\n"
            "或设置同名环境变量。Token 申请：https://tushare.pro/user/token"
        )
    ts.set_token(token)


def get_pro_api():
    global _PRO_API
    if _PRO_API is not None:
        return _PRO_API
    with _TOKEN_LOCK:
        if _PRO_API is None:
            ensure_token()
            _PRO_API = ts.pro_api()
    return _PRO_API


from sentiment_scoring import summarize_cross_section_state  # noqa: E402


_RATE_LIMIT_PER_MIN = int(os.getenv("TUSHARE_RATE_LIMIT_PER_MIN", "200"))
_RATE_WINDOW_SEC = 60.0
_RATE_LOCK = threading.Lock()
_CALL_TIMES: deque[float] = deque()


def _shared_rate_limit() -> None:
    while True:
        with _RATE_LOCK:
            now = time.time()
            while _CALL_TIMES and now - _CALL_TIMES[0] > _RATE_WINDOW_SEC:
                _CALL_TIMES.popleft()
            if len(_CALL_TIMES) < _RATE_LIMIT_PER_MIN:
                _CALL_TIMES.append(now)
                return
            sleep_for = _CALL_TIMES[0] + _RATE_WINDOW_SEC - now
        if sleep_for > 0:
            time.sleep(min(sleep_for, 1.0))


logger = logging.getLogger(__name__)


INDEX_TS_CODES = {
    "000001": "000001.SH",
    "399001": "399001.SZ",
    "399006": "399006.SZ",
    "000300": "000300.SH",
    "000905": "000905.SH",
    "000688": "000688.SH",
}

BREADTH_INDEX_CODES = list(INDEX_TS_CODES.keys())

STYLE_INDEX_CODES = {
    "microcap": "000688",
    "largecap": "000300",
}


def _to_ts_index(symbol: str) -> str:
    if "." in symbol:
        return symbol
    return INDEX_TS_CODES.get(symbol, f"{symbol}.SH")


def _yyyymmdd(date_str: str) -> str:
    return str(date_str).replace("-", "")


def _iso(date_str: str) -> str:
    s = str(date_str)
    if "-" in s:
        return s
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


class DataFetcherTushare:
    """Tushare-backed fetcher mirroring DataFetcherV2's public surface."""

    def __init__(self):
        self.pro = get_pro_api()
        self.offline_mode = False
        self._spot_cache: dict[str, pd.DataFrame] = {}
        self._trade_cal_cache: list[str] | None = None

    def enable_offline_mode(self):
        logger.warning("offline_mode not supported on Tushare fetcher; ignoring.")

    def _get_trade_cal(self, years: int = 6) -> list[str]:
        if self._trade_cal_cache:
            return self._trade_cal_cache
        end = datetime.now()
        start = end - timedelta(days=years * 365 + 30)
        _shared_rate_limit()
        df = self.pro.trade_cal(
            exchange="SSE",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            is_open="1",
        )
        if df is None or df.empty:
            self._trade_cal_cache = []
            return []
        self._trade_cal_cache = sorted(df["cal_date"].tolist())
        return self._trade_cal_cache

    def _latest_trade_date(self) -> str:
        cal = self._get_trade_cal()
        today = datetime.now().strftime("%Y%m%d")
        for d in reversed(cal):
            if d <= today:
                return d
        return cal[-1] if cal else today

    def _latest_trade_date_iso(self) -> str:
        return _iso(self._latest_trade_date())

    def _previous_trade_date(self, date_yyyymmdd: str) -> Optional[str]:
        cal = self._get_trade_cal()
        for d in reversed(cal):
            if d < date_yyyymmdd:
                return d
        return None

    def get_index_data_range(self, symbol: str = "000001", years: int = 1):
        ts_code = _to_ts_index(symbol)
        end = datetime.now()
        start = end - timedelta(days=years * 365 + 30)
        _shared_rate_limit()
        df = self.pro.index_daily(
            ts_code=ts_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            logger.error("Tushare index_daily empty for %s", ts_code)
            return None

        df = df.copy()
        df["date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        for col in ("open", "high", "low", "close", "pre_close", "pct_chg", "vol", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.rename(columns={"vol": "volume", "pct_chg": "change_pct"})
        df["amount"] = df["amount"] * 1000.0
        df["amplitude"] = (df["high"] - df["low"]) / df["pre_close"] * 100
        df["change"] = df["close"] - df["pre_close"]
        df["turnover"] = np.nan
        df = df.sort_values("date").reset_index(drop=True)
        df.attrs["source"] = "tushare"
        return df[
            ["date", "open", "close", "high", "low", "amount", "volume",
             "amplitude", "change_pct", "change", "turnover"]
        ]

    def _get_spot(self, trade_date_yyyymmdd: str) -> Optional[pd.DataFrame]:
        if trade_date_yyyymmdd in self._spot_cache:
            cached = self._spot_cache[trade_date_yyyymmdd]
            return cached if not cached.empty else None
        _shared_rate_limit()
        df = self.pro.daily(trade_date=trade_date_yyyymmdd)
        if df is None or df.empty:
            self._spot_cache[trade_date_yyyymmdd] = pd.DataFrame()
            return None
        df = df.copy()
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
        df = df[df["ts_code"].str.endswith((".SH", ".SZ"))]
        self._spot_cache[trade_date_yyyymmdd] = df
        return df

    def _breadth_from_spot(self, spot: pd.DataFrame, date_iso: str) -> dict:
        changes = spot["pct_chg"].dropna()
        total = int(len(changes))
        return {
            "date": date_iso,
            "up_ratio": float((changes > 0).mean() * 100) if total else 0.0,
            "median_change": float(changes.median()) if total else 0.0,
            "breadth_thrust": float(
                (changes > 1).mean() * 100 - (changes < -1).mean() * 100
            ) if total else 0.0,
            "dispersion": float(changes.std(ddof=0)) if total > 1 else 0.0,
            "sample_size": total,
            "up_count": int((changes > 0).sum()),
            "down_count": int((changes < 0).sum()),
            "flat_count": int((changes == 0).sum()),
            "limit_up": int((changes >= 9.5).sum()),
            "limit_down": int((changes <= -9.5).sum()),
            "source": "tushare",
        }

    def get_market_breadth(self, date: Optional[str] = None):
        date_iso = date or self._latest_trade_date_iso()
        yyyymmdd = _yyyymmdd(date_iso)
        spot = self._get_spot(yyyymmdd)
        if spot is None or spot.empty:
            return None
        return self._breadth_from_spot(spot, _iso(yyyymmdd))

    def get_market_breadth_history(self, years: int = 3):
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        cal = self._get_trade_cal()
        start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        dates = [d for d in cal if start_s <= d <= end_s]
        logger.info("Fetching breadth history for %d trade dates", len(dates))

        results = []
        for i, d in enumerate(dates):
            spot = self._get_spot(d)
            if spot is None or spot.empty:
                continue
            results.append(self._breadth_from_spot(spot, _iso(d)))
            if (i + 1) % 50 == 0:
                logger.info("Breadth history: %d/%d", i + 1, len(dates))
        return results

    def _style_from_frames(
        self,
        date_iso: str,
        micro_df: Optional[pd.DataFrame],
        large_df: Optional[pd.DataFrame],
    ):
        def _pick(frame: Optional[pd.DataFrame]) -> Optional[float]:
            if frame is None or frame.empty:
                return None
            sub = frame[frame["date"] <= date_iso]
            if sub.empty:
                return None
            return float(sub.iloc[-1]["change_pct"])

        return {
            "microcap_change": _pick(micro_df),
            "largecap_change": _pick(large_df),
        }

    def _fetch_style_snapshot(self, date_iso: str):
        try:
            micro_df = self.get_index_data_range(STYLE_INDEX_CODES["microcap"], years=1)
            large_df = self.get_index_data_range(STYLE_INDEX_CODES["largecap"], years=1)
        except Exception as exc:
            logger.warning("style snapshot failed: %s", exc)
            return {"microcap_change": None, "largecap_change": None}

        return self._style_from_frames(date_iso, micro_df, large_df)

    def _cross_section_from_spot(
        self,
        date_iso: str,
        spot: pd.DataFrame,
        previous_spot: Optional[pd.DataFrame] = None,
        style: Optional[dict] = None,
    ):
        spot_changes = spot["pct_chg"].dropna().tolist()
        universe_size = int(len(spot))
        s = spot["pct_chg"]
        limit_up_count = int((s >= 9.5).sum())
        strong_pool_count = int(((s >= 7.0) & (s < 9.5)).sum())

        previous_limit_up_return = None
        previous_limit_up_up_ratio = None
        if previous_spot is not None and not previous_spot.empty:
            prev_limit_codes = previous_spot[previous_spot["pct_chg"] >= 9.5]["ts_code"]
            if not prev_limit_codes.empty:
                today_perf = spot[spot["ts_code"].isin(prev_limit_codes)]["pct_chg"].dropna()
                if not today_perf.empty:
                    previous_limit_up_return = float(today_perf.mean())
                    previous_limit_up_up_ratio = float((today_perf > 0).mean())

        style = style or {"microcap_change": None, "largecap_change": None}
        return summarize_cross_section_state(
            date=date_iso,
            spot_changes=spot_changes,
            universe_size=universe_size,
            limit_up_count=limit_up_count,
            strong_pool_count=strong_pool_count,
            previous_limit_up_return=previous_limit_up_return,
            previous_limit_up_up_ratio=previous_limit_up_up_ratio,
            microcap_change=style["microcap_change"],
            largecap_change=style["largecap_change"],
            source="tushare_cross_section",
        )

    def get_cross_sectional_state(self, date: Optional[str] = None):
        date_iso = date or self._latest_trade_date_iso()
        yyyymmdd = _yyyymmdd(date_iso)

        spot = self._get_spot(yyyymmdd)
        if spot is None or spot.empty:
            return None

        prev = self._previous_trade_date(yyyymmdd)
        prev_spot = None
        if prev:
            prev_spot = self._get_spot(prev)

        style = self._fetch_style_snapshot(date_iso)
        return self._cross_section_from_spot(date_iso, spot, prev_spot, style)

    def get_cross_sectional_state_history(self, years: int = 3):
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        cal = self._get_trade_cal()
        start_s, end_s = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")
        dates = [d for d in cal if start_s <= d <= end_s]
        logger.info("Fetching cross-section history for %d trade dates", len(dates))

        try:
            micro_df = self.get_index_data_range(STYLE_INDEX_CODES["microcap"], years=years)
            large_df = self.get_index_data_range(STYLE_INDEX_CODES["largecap"], years=years)
        except Exception as exc:
            logger.warning("style history failed: %s", exc)
            micro_df = None
            large_df = None

        results = []
        for i, d in enumerate(dates):
            spot = self._get_spot(d)
            if spot is None or spot.empty:
                continue
            prev_spot = self._get_spot(dates[i - 1]) if i > 0 else None
            style = self._style_from_frames(_iso(d), micro_df, large_df)
            results.append(self._cross_section_from_spot(_iso(d), spot, prev_spot, style))
            if (i + 1) % 50 == 0:
                logger.info("Cross-section history: %d/%d", i + 1, len(dates))
        return results

    def get_north_flow(self):
        try:
            latest = self._latest_trade_date()
            _shared_rate_limit()
            df = self.pro.moneyflow_hsgt(trade_date=latest)
            if df is None or df.empty:
                start = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
                _shared_rate_limit()
                df = self.pro.moneyflow_hsgt(start_date=start, end_date=latest)
                if df is None or df.empty:
                    return None
                df = df.sort_values("trade_date")
            row = df.iloc[-1] if "trade_date" in df.columns and len(df) > 1 else df.iloc[0]
            net = row.get("north_money")
            if net is None or pd.isna(net):
                return None
            return {
                "net_flow": float(net),
                "timestamp": _iso(row["trade_date"]) + " 15:00:00",
                "source": "tushare",
            }
        except Exception as exc:
            logger.error("Failed to fetch north flow: %s", exc)
            return None

    def get_north_flow_historical(self, years: int = 3):
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        try:
            _shared_rate_limit()
            df = self.pro.moneyflow_hsgt(
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
            )
        except Exception as exc:
            logger.error("north flow history failed: %s", exc)
            return []
        if df is None or df.empty:
            return []
        df = df.copy()
        df["date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        df["net_flow"] = pd.to_numeric(df["north_money"], errors="coerce")
        df = df.dropna(subset=["net_flow"]).sort_values("date")
        return [
            {"date": row.date, "flow": float(row.net_flow),
             "net_flow": float(row.net_flow), "source": "tushare"}
            for row in df.itertuples(index=False)
        ]

    def get_margin_trading(self):
        try:
            latest = self._latest_trade_date()
            window_start = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
            _shared_rate_limit()
            df = self.pro.margin(start_date=window_start, end_date=latest)
            if df is None or df.empty:
                return None
            df["rzye"] = pd.to_numeric(df["rzye"], errors="coerce")
            exch_counts = df.groupby("trade_date")["exchange_id"].nunique()
            full_dates = sorted(exch_counts[exch_counts >= 2].index)
            if len(full_dates) < 2:
                return None
            latest_date = full_dates[-1]
            prev_date = full_dates[-2]
            latest_bal = float(df[df["trade_date"] == latest_date]["rzye"].sum())
            prev_bal = float(df[df["trade_date"] == prev_date]["rzye"].sum())
            sse_bal = float(df[(df["trade_date"] == latest_date) & (df["exchange_id"] == "SSE")]["rzye"].sum())
            szse_bal = float(df[(df["trade_date"] == latest_date) & (df["exchange_id"] == "SZSE")]["rzye"].sum())
            return {
                "margin_balance": latest_bal,
                "net_change": latest_bal - prev_bal,
                "sse_balance": sse_bal,
                "szse_balance": szse_bal,
                "date": _iso(latest_date),
                "source": "tushare",
            }
        except Exception as exc:
            logger.error("Failed to fetch margin: %s", exc)
            return None

    def get_margin_trading_historical(self, years: int = 3):
        end = datetime.now()
        start = end - timedelta(days=years * 365)
        rows: list[pd.DataFrame] = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(end, chunk_start + timedelta(days=365))
            try:
                _shared_rate_limit()
                df = self.pro.margin(
                    start_date=chunk_start.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                )
            except Exception as exc:
                logger.warning("margin chunk %s-%s failed: %s",
                               chunk_start, chunk_end, exc)
                df = None
            if df is not None and not df.empty:
                rows.append(df)
            chunk_start = chunk_end + timedelta(days=1)

        if not rows:
            return []
        full = pd.concat(rows, ignore_index=True)
        full["rzye"] = pd.to_numeric(full["rzye"], errors="coerce")
        agg = full.groupby("trade_date")["rzye"].sum().sort_index()

        results = []
        prev_balance = None
        for trade_date, balance in agg.items():
            balance = float(balance)
            net_change = balance - prev_balance if prev_balance is not None else 0.0
            results.append({
                "date": _iso(trade_date),
                "margin_balance": balance,
                "net_change": net_change,
                "source": "tushare",
            })
            prev_balance = balance
        return results


DataFetcher = DataFetcherTushare


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetcher = DataFetcherTushare()
    idx = fetcher.get_index_data_range("000001", years=1)
    print("index tail:")
    print(idx.tail())
    print("breadth:", fetcher.get_market_breadth())
    print("north:", fetcher.get_north_flow())
    print("margin:", fetcher.get_margin_trading())
    print("cross_section:", fetcher.get_cross_sectional_state())
