#!/usr/bin/env python3
"""
Data fetching utilities for the A-share sentiment tracker.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests as std_requests

try:
    import curl_cffi.requests as requests

    USE_CURL = True
except ImportError:
    import requests

    USE_CURL = False

from config import DATA_DIR
from sentiment_scoring import summarize_cross_section_state


logger = logging.getLogger(__name__)

BREADTH_INDEX_CODES = [
    "000001",
    "399001",
    "399006",
    "000300",
    "000905",
    "000688",
]

STYLE_INDEX_CODES = {
    "microcap": "000688",
    "largecap": "000300",
}


def _env_int(name, default):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%r, using %s", name, raw_value, default)
        return default


class DataFetcherV2:
    """Fetches market data and builds breadth proxies."""

    def __init__(self):
        self.request_delay = 0.5
        self.session = requests.Session() if USE_CURL else requests
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        self._spot_cache = None
        self._spot_cache_ts = 0.0
        self._index_cache = {}
        self.cache_dir = Path(os.environ.get("SCORE_FETCH_CACHE_DIR", os.path.join(DATA_DIR, "fetch_cache")))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.akshare_cache_ttl = _env_int("SCORE_AKSHARE_CACHE_TTL_SECONDS", 21600)
        self.akshare_history_cache_ttl = _env_int("SCORE_AKSHARE_HISTORY_CACHE_TTL_SECONDS", 86400)
        self.spot_cache_ttl = _env_int("SCORE_SPOT_CACHE_TTL_SECONDS", 60)
        self.akshare_enabled = os.environ.get("SCORE_AKSHARE_ENABLED", "1").lower() not in {"0", "false", "no"}
        self.offline_mode = False

    def _cache_path(self, cache_key):
        safe_key = "".join(char if char.isalnum() or char in "._-" else "_" for char in cache_key)
        return self.cache_dir / f"{safe_key}.json"

    def _read_cache(self, cache_key, max_age=None, allow_stale=False):
        path = self._cache_path(cache_key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            cached_at = float(payload.get("cached_at", 0))
            if max_age is not None and time.time() - cached_at > max_age and not allow_stale:
                return None
            return payload.get("data")
        except Exception as exc:
            logger.warning("Failed to read cache %s: %s", path, exc)
            return None

    def _write_cache(self, cache_key, data):
        path = self._cache_path(cache_key)
        try:
            tmp_path = path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump({"cached_at": time.time(), "data": data}, handle, ensure_ascii=False)
            os.replace(tmp_path, path)
        except Exception as exc:
            logger.warning("Failed to write cache %s: %s", path, exc)

    def _frame_to_cache_data(self, frame):
        if frame is None:
            return None
        clean = frame.astype(object).where(pd.notna(frame), None)
        records = json.loads(clean.to_json(orient="records", date_format="iso", force_ascii=False))
        return {"columns": list(clean.columns), "records": records}

    def _cache_data_to_frame(self, data):
        if data is None:
            return None
        return pd.DataFrame(data.get("records", []), columns=data.get("columns"))

    def _read_rows_cache(self, cache_key, max_age=None, allow_stale=False):
        cached = self._read_cache(cache_key, max_age=max_age, allow_stale=allow_stale)
        if cached is None:
            return None, None
        return cached.get("rows") or [], cached.get("total")

    def _write_rows_cache(self, cache_key, rows, total):
        if rows:
            self._write_cache(cache_key, {"rows": rows, "total": total})

    def _fetch_akshare_frame_cached(self, cache_key, fetch_func, ttl_seconds):
        cached = self._read_cache(cache_key, max_age=ttl_seconds)
        if cached is not None:
            return self._cache_data_to_frame(cached)

        if not self.akshare_enabled:
            stale = self._read_cache(cache_key, allow_stale=True)
            return self._cache_data_to_frame(stale)

        try:
            frame = fetch_func()
            self._write_cache(cache_key, self._frame_to_cache_data(frame))
            return frame
        except Exception as exc:
            stale = self._read_cache(cache_key, allow_stale=True)
            if stale is not None:
                logger.warning("Using stale akshare cache for %s after fetch failure: %s", cache_key, exc)
                return self._cache_data_to_frame(stale)
            raise

    def _make_request(self, url, params=None, headers=None, timeout=15):
        req_headers = headers or self.headers
        if USE_CURL:
            return self.session.get(
                url,
                params=params,
                headers=req_headers,
                timeout=timeout,
                impersonate="chrome120",
            )
        return requests.get(url, params=params, headers=req_headers, timeout=timeout)

    def _symbol_to_secid(self, symbol: str) -> str:
        market = "1" if symbol in {"000001", "000300", "000905", "000688"} else "0"
        return f"{market}.{symbol}"

    def get_index_data_range(self, symbol="000001", years=1):
        days = years * 365
        cache_key = (symbol, days, self.offline_mode)
        cached = self._index_cache.get(cache_key)
        if cached is not None:
            return cached.copy()
        if self.offline_mode:
            result = self._generate_mock_index_data(days)
            self._index_cache[cache_key] = result.copy()
            return result
        result = self.get_index_data_eastmoney(symbol, days=days)
        if result is not None and not result.empty:
            self._index_cache[cache_key] = result.copy()
            return result
        logger.warning("Real index data unavailable, falling back to mock data")
        result = self._generate_mock_index_data(days)
        self._index_cache[cache_key] = result.copy()
        return result

    def _generate_mock_index_data(self, days=365):
        logger.info("Generating %d days of mock index data", days)
        end_date = datetime.now()
        dates = []
        current = end_date - timedelta(days=days)
        while current <= end_date:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)

        price = 3000.0
        records = []
        for d in dates:
            change_pct = np.random.normal(0, 1.5)
            close = price * (1 + change_pct / 100)
            open_p = price * (1 + np.random.normal(0, 0.003))
            high = max(open_p, close) * (1 + abs(np.random.normal(0, 0.005)))
            low = min(open_p, close) * (1 - abs(np.random.normal(0, 0.005)))
            amount = np.random.uniform(1.5e11, 4e11)
            records.append({
                "date": d.strftime("%Y-%m-%d"),
                "open": round(open_p, 2),
                "close": round(close, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "amount": amount,
                "volume": amount / close,
                "amplitude": abs(change_pct) * 2,
                "change_pct": round(change_pct, 2),
                "change": round(close - open_p, 2),
                "turnover": np.random.uniform(0.5, 3.0),
            })
            price = close

        frame = pd.DataFrame(records)
        frame.attrs["source"] = "mock"
        logger.info("Generated %d mock index rows", len(frame))
        return frame

    def get_index_data_eastmoney(self, symbol="000001", days=30):
        try:
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            params = {
                "secid": self._symbol_to_secid(symbol),
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",
                "fqt": "0",
                "end": "20500101",
                "lmt": str(days),
                "_": str(int(time.time() * 1000)),
            }
            headers = {**self.headers, "Referer": "https://quote.eastmoney.com/"}

            response = self._make_request(url, params=params, headers=headers, timeout=20)
            payload = response.json()
            if not payload.get("data") or not payload["data"].get("klines"):
                return None

            records = []
            for raw in payload["data"]["klines"]:
                parts = raw.split(",")
                record = self._parse_eastmoney_kline(parts)
                if record:
                    records.append(record)

            frame = pd.DataFrame(records)
            if frame.empty:
                return None

            frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
            logger.info("Fetched %s index rows for %s", len(frame), symbol)
            return frame
        except Exception as exc:
            logger.error("Failed to fetch index data for %s: %s", symbol, exc)
            return None

    def _parse_eastmoney_kline(self, parts):
        if len(parts) < 11:
            return None
        return {
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
            "amount": float(parts[6]),
            "amplitude": float(parts[7]),
            "change_pct": float(parts[8]),
            "change": float(parts[9]),
            "turnover": float(parts[10]),
        }

    def get_index_data_sina(self, symbol="000001"):
        try:
            code = f"sh{symbol}" if symbol.startswith("0") else f"sz{symbol}"
            url = f"https://hq.sinajs.cn/list={code}"
            headers = {**self.headers, "Referer": "https://finance.sina.com.cn"}
            response = self._make_request(url, headers=headers, timeout=10)
            text = response.text
            raw = text.split('"')
            if len(raw) < 2:
                return None
            parts = raw[1].split(",")
            if len(parts) < 31:
                return None
            return {
                "name": parts[0],
                "open": float(parts[1]),
                "close": float(parts[3]),
                "high": float(parts[4]),
                "low": float(parts[5]),
                "volume": float(parts[8]),
                "date": parts[30],
            }
        except Exception as exc:
            logger.error("Failed to fetch Sina index data for %s: %s", symbol, exc)
            return None

    def get_index_data_tencent(self, symbol="000001"):
        try:
            code = f"sh{symbol}" if symbol.startswith("0") else f"sz{symbol}"
            url = f"https://qt.gtimg.cn/q={code}"
            headers = {**self.headers, "Referer": "https://stock.qq.com"}
            response = self._make_request(url, headers=headers, timeout=10)
            text = response.text
            raw = text.split('"')
            if len(raw) < 2:
                return None
            parts = raw[1].split("~")
            if len(parts) < 37:
                return None
            return {
                "name": parts[1],
                "code": parts[2],
                "price": float(parts[3]),
                "prev_close": float(parts[4]),
                "open": float(parts[5]),
                "high": float(parts[33]),
                "low": float(parts[34]),
                "volume": float(parts[36]),
                "change_pct": float(parts[32]),
                "datetime": parts[30],
            }
        except Exception as exc:
            logger.error("Failed to fetch Tencent index data for %s: %s", symbol, exc)
            return None

    def _build_breadth_snapshot(self, date: str, change_values, source: str):
        changes = pd.Series(change_values, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
        if changes.empty:
            return None
        return {
            "date": date,
            "up_ratio": float((changes > 0).mean() * 100),
            "median_change": float(changes.median()),
            "breadth_thrust": float((changes > 1).mean() * 100 - (changes < -1).mean() * 100),
            "dispersion": float(changes.std(ddof=0)) if len(changes) > 1 else 0.0,
            "sample_size": int(len(changes)),
            "source": source,
        }

    def _fetch_market_spot_snapshot(self, page_size=100):
        url = "https://82.push2.eastmoney.com/api/qt/clist/get"
        fields = (
            "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,"
            "f21,f23,f24,f25,f22,f11,f62,f128,f136,f115,f152"
        )
        fs = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
        page = 1
        all_rows = []
        total_count = None
        max_pages = 200
        while page <= max_pages:
            params = {
                "pn": str(page),
                "pz": str(page_size),
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": fs,
                "fields": fields,
            }
            try:
                response = self._make_request(url, params=params, headers=self.headers, timeout=20)
            except Exception:
                response = std_requests.get(
                    url, params=params, headers=self.headers, timeout=20,
                    proxies={"http": None, "https": None},
                )
            payload = response.json()
            diff = ((payload or {}).get("data") or {}).get("diff") or []
            if not diff:
                break
            all_rows.extend(diff)
            total = int(((payload or {}).get("data") or {}).get("total") or 0)
            total_count = total_count or total
            if total and len(all_rows) >= total:
                break
            page += 1
            time.sleep(0.2)
        return all_rows, total_count

    def _fetch_sina_market_snapshot(self):
        """Fallback: fetch all A-share stocks from Sina (different server, no Eastmoney rate limit)."""
        cached_rows, cached_total = self._read_rows_cache("sina_market_spot", max_age=self.spot_cache_ttl)
        if cached_rows is not None:
            return cached_rows, cached_total

        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        headers = {
            "User-Agent": self.headers["User-Agent"],
            "Referer": "https://vip.stock.finance.sina.com.cn/",
        }
        page = 1
        all_rows = []
        max_pages = 100
        while page <= max_pages:
            params = {
                "page": str(page),
                "num": "100",
                "sort": "symbol",
                "asc": "1",
                "node": "hs_a",
                "symbol": "",
                "_s_r_a": "init",
            }
            try:
                response = std_requests.get(
                    url, params=params, headers=headers, timeout=20,
                    proxies={"http": None, "https": None},
                )
                batch = response.json()
            except Exception as exc:
                logger.warning("Sina market snapshot page %d failed: %s", page, exc)
                stale_rows, stale_total = self._read_rows_cache("sina_market_spot", allow_stale=True)
                if stale_rows is not None:
                    return stale_rows, stale_total
                break

            if not batch or not isinstance(batch, list):
                break
            all_rows.extend(batch)
            if len(batch) < 100:
                break
            page += 1
            time.sleep(0.1)

        if not all_rows:
            return None, None
        self._write_rows_cache("sina_market_spot", all_rows, len(all_rows))
        return all_rows, len(all_rows)

    def _fetch_limit_pool_snapshot(self, date_str):
        try:
            import akshare as ak
        except ImportError:
            logger.warning("akshare not available for limit pool data")
            return None, None, None

        try:
            limit_up = self._fetch_akshare_frame_cached(
                f"ak_limit_up_{date_str}",
                lambda: ak.stock_zt_pool_em(date=date_str),
                self.akshare_cache_ttl,
            )
        except Exception as exc:
            logger.warning("Failed to fetch limit-up pool for %s: %s", date_str, exc)
            limit_up = None

        try:
            previous_limit = self._fetch_akshare_frame_cached(
                f"ak_previous_limit_{date_str}",
                lambda: ak.stock_zt_pool_previous_em(date=date_str),
                self.akshare_cache_ttl,
            )
        except Exception as exc:
            logger.warning("Failed to fetch previous limit-up pool for %s: %s", date_str, exc)
            previous_limit = None

        try:
            strong_pool = self._fetch_akshare_frame_cached(
                f"ak_strong_pool_{date_str}",
                lambda: ak.stock_zt_pool_strong_em(date=date_str),
                self.akshare_cache_ttl,
            )
        except Exception as exc:
            logger.warning("Failed to fetch strong pool for %s: %s", date_str, exc)
            strong_pool = None

        return limit_up, previous_limit, strong_pool

    def _fetch_style_snapshot(self, date=None):
        date = date or datetime.now().strftime("%Y-%m-%d")
        try:
            micro_df = self.get_index_data_range(STYLE_INDEX_CODES["microcap"], years=1)
            large_df = self.get_index_data_range(STYLE_INDEX_CODES["largecap"], years=1)
            micro_row = None
            large_row = None
            if micro_df is not None and not micro_df.empty:
                micro_subset = micro_df[micro_df["date"] <= date]
                if not micro_subset.empty:
                    micro_row = micro_subset.iloc[-1]
            if large_df is not None and not large_df.empty:
                large_subset = large_df[large_df["date"] <= date]
                if not large_subset.empty:
                    large_row = large_subset.iloc[-1]
            return {
                "microcap_change": float(micro_row["change_pct"]) if micro_row is not None else None,
                "largecap_change": float(large_row["change_pct"]) if large_row is not None else None,
            }
        except Exception as exc:
            logger.warning("Failed to fetch style snapshot for %s: %s", date, exc)
            return {"microcap_change": None, "largecap_change": None}

    def _get_cached_spot_snapshot(self, ttl=60):
        now = time.time()
        if self._spot_cache is not None and (now - self._spot_cache_ts) < ttl:
            return self._spot_cache

        cached_rows, cached_total = self._read_rows_cache("eastmoney_market_spot", max_age=self.spot_cache_ttl)
        if cached_rows is not None:
            self._spot_cache = (cached_rows, cached_total)
            self._spot_cache_ts = now
            return self._spot_cache

        try:
            rows, total = self._fetch_market_spot_snapshot()
        except Exception as exc:
            logger.warning("Failed to fetch market spot snapshot: %s", exc)
            rows, total = None, None

        self._write_rows_cache("eastmoney_market_spot", rows, total)
        self._spot_cache = (rows, total)
        self._spot_cache_ts = now
        return self._spot_cache

    def enable_offline_mode(self):
        self.offline_mode = True
        logger.warning("已启用离线模式，将使用模拟数据")

    def get_market_breadth(self, date=None):
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        if self.offline_mode:
            return self._generate_mock_breadth(date)

        spot_rows, _universe = self._get_cached_spot_snapshot()
        if spot_rows:
            changes = []
            for item in spot_rows:
                raw = item.get("f3")
                if raw is None or raw == "" or raw == "-":
                    continue
                changes.append(float(raw))

            if changes:
                changes_series = pd.Series(changes, dtype="float64")
                up_count = int((changes_series > 0).sum())
                down_count = int((changes_series < 0).sum())
                flat_count = int((changes_series == 0).sum())
                limit_up = int((changes_series >= 9.5).sum())
                limit_down = int((changes_series <= -9.5).sum())
                total = len(changes_series)

                return {
                    "date": date,
                    "up_ratio": float(up_count / total * 100) if total else 0.0,
                    "median_change": float(changes_series.median()),
                    "breadth_thrust": float(
                        (changes_series > 1).mean() * 100 - (changes_series < -1).mean() * 100
                    ),
                    "dispersion": float(changes_series.std(ddof=0)) if total > 1 else 0.0,
                    "sample_size": total,
                    "up_count": up_count,
                    "down_count": down_count,
                    "flat_count": flat_count,
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                    "source": "eastmoney_spot",
                }

        sina_rows, _sina_total = self._fetch_sina_market_snapshot()
        if sina_rows:
            changes = []
            for item in sina_rows:
                raw = item.get("changepercent")
                if raw is None or raw == "" or raw == "-":
                    continue
                changes.append(float(raw))

            if changes:
                changes_series = pd.Series(changes, dtype="float64")
                up_count = int((changes_series > 0).sum())
                down_count = int((changes_series < 0).sum())
                flat_count = int((changes_series == 0).sum())
                limit_up = int((changes_series >= 9.5).sum())
                limit_down = int((changes_series <= -9.5).sum())
                total = len(changes_series)

                return {
                    "date": date,
                    "up_ratio": float(up_count / total * 100) if total else 0.0,
                    "median_change": float(changes_series.median()),
                    "breadth_thrust": float(
                        (changes_series > 1).mean() * 100 - (changes_series < -1).mean() * 100
                    ),
                    "dispersion": float(changes_series.std(ddof=0)) if total > 1 else 0.0,
                    "sample_size": total,
                    "up_count": up_count,
                    "down_count": down_count,
                    "flat_count": flat_count,
                    "limit_up": limit_up,
                    "limit_down": limit_down,
                    "source": "sina_spot",
                }

        try:
            url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
            params = {
                "fltt": "2",
                "invt": "2",
                "fields": "f2,f3,f12,f14",
                "secids": "0.399006,0.399001,1.000001,1.000300,1.000905,1.000688",
                "_": str(int(time.time() * 1000)),
            }
            headers = {**self.headers, "Referer": "https://quote.eastmoney.com/"}

            response = self._make_request(url, params=params, headers=headers, timeout=10)
            payload = response.json()
            diff = (payload.get("data") or {}).get("diff") or []
            changes = [float(item["f3"]) for item in diff if item.get("f3") not in (None, "")]
            if changes:
                return self._build_breadth_snapshot(date, changes, "eastmoney_indices")
        except Exception as exc:
            logger.warning("Failed to fetch realtime breadth proxy: %s", exc)

        return self._generate_mock_breadth(date)

    def get_cross_sectional_state(self, date=None):
        trade_date = date or datetime.now().strftime("%Y-%m-%d")
        ak_date = trade_date.replace("-", "")

        spot_changes = []
        limit_up_count = None
        strong_pool_count = None
        previous_limit_up_return = None
        previous_limit_up_up_ratio = None
        universe_size = None
        source = "realtime_cross_section"

        spot_rows, universe_size = self._get_cached_spot_snapshot()
        if spot_rows:
            spot_changes = [
                float(item["f3"])
                for item in spot_rows
                if item.get("f3") not in (None, "", "-")
            ]
        if not spot_changes:
            sina_rows, sina_total = self._fetch_sina_market_snapshot()
            if sina_rows:
                spot_changes = [
                    float(item["changepercent"])
                    for item in sina_rows
                    if item.get("changepercent") not in (None, "", "-")
                ]
                universe_size = sina_total
                source = "sina_cross_section"

        limit_up, previous_limit, strong_pool = self._fetch_limit_pool_snapshot(ak_date)
        if limit_up is not None:
            limit_up_count = int(len(limit_up))
        if strong_pool is not None:
            strong_pool_count = int(len(strong_pool))
        if previous_limit is not None and not previous_limit.empty:
            returns = pd.to_numeric(previous_limit["涨跌幅"], errors="coerce").dropna()
            if not returns.empty:
                previous_limit_up_return = float(returns.mean())
                previous_limit_up_up_ratio = float((returns > 0).mean())

        style_data = self._fetch_style_snapshot(trade_date)
        if not spot_changes and limit_up_count is None and style_data["microcap_change"] is None:
            return None

        return summarize_cross_section_state(
            date=trade_date,
            spot_changes=spot_changes,
            limit_up_count=limit_up_count,
            strong_pool_count=strong_pool_count,
            previous_limit_up_return=previous_limit_up_return,
            previous_limit_up_up_ratio=previous_limit_up_up_ratio,
            microcap_change=style_data["microcap_change"],
            largecap_change=style_data["largecap_change"],
            source=source,
            universe_size=universe_size,
        )

    def get_market_breadth_history(self, years=3):
        panel = []
        for code in BREADTH_INDEX_CODES:
            frame = self.get_index_data_range(code, years=years)
            if frame is None or frame.empty:
                continue
            subset = frame[["date", "change_pct"]].copy()
            subset = subset.rename(columns={"change_pct": code})
            panel.append(subset)
            time.sleep(self.request_delay)

        if not panel:
            return []

        merged = panel[0]
        for subset in panel[1:]:
            merged = merged.merge(subset, on="date", how="outer")

        merged = merged.sort_values("date").reset_index(drop=True)
        value_columns = [col for col in merged.columns if col != "date"]
        results = []
        for _, row in merged.iterrows():
            changes = pd.to_numeric(row[value_columns], errors="coerce").dropna()
            snapshot = self._build_breadth_snapshot(row["date"], changes.tolist(), "index_panel")
            if snapshot:
                results.append(snapshot)
        return results

    def _generate_mock_breadth(self, date=None):
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        simulated_changes = np.random.normal(loc=0.0, scale=1.2, size=len(BREADTH_INDEX_CODES))
        return self._build_breadth_snapshot(date, simulated_changes, "mock")

    def get_north_flow(self):
        if self.offline_mode:
            return {
                "net_flow": float(np.random.normal(loc=0.0, scale=5e9)),
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "mock",
            }

        try:
            url = "https://push2.eastmoney.com/api/qt/kamt.rtmin/get"
            params = {
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
                "_": str(int(time.time() * 1000)),
            }
            headers = {**self.headers, "Referer": "https://quote.eastmoney.com/"}

            response = self._make_request(url, params=params, headers=headers, timeout=10)
            payload = response.json()
            s2n = (payload.get("data") or {}).get("s2n") or []
            for item in reversed(s2n):
                if not isinstance(item, str):
                    continue
                parts = item.split(",")
                if len(parts) >= 3 and parts[2] != "-":
                    net_flow = float(parts[2])
                    logger.info("North flow realtime: raw=%.2f亿", net_flow / 1e8)
                    return {
                        "net_flow": net_flow,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "source": "eastmoney",
                    }
        except Exception as exc:
            logger.warning("Failed to fetch realtime north flow from Eastmoney: %s", exc)

        try:
            import akshare as ak

            frame = self._fetch_akshare_frame_cached(
                "ak_north_flow_history_latest",
                lambda: ak.stock_hsgt_hist_em(symbol="北向资金"),
                self.akshare_history_cache_ttl,
            )
            if frame is not None and not frame.empty:
                latest = frame.iloc[-1]
                net_flow = float(latest.iloc[1]) * 1e8 if len(latest) > 1 else 0.0
                logger.info("North flow from akshare backup: %.2f亿", net_flow / 1e8)
                return {
                    "net_flow": net_flow,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "source": "akshare",
                }
        except Exception as exc:
            logger.warning("Failed to fetch north flow from akshare backup: %s", exc)

        return {
            "net_flow": float(np.random.normal(loc=0.0, scale=5e9)),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "mock",
        }

    def _fetch_margin_sse(self, begin_date, end_date):
        try:
            url = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
            params = {
                "isPagination": "true",
                "beginDate": begin_date,
                "endDate": end_date,
                "tabType": "",
                "stockCode": "",
                "pageHelp.pageSize": "5000",
                "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1",
                "pageHelp.cacheSize": "1",
                "pageHelp.endPage": "5",
            }
            headers = {
                "Referer": "https://www.sse.com.cn/",
                "User-Agent": self.headers["User-Agent"],
            }
            response = requests.get(url, params=params, headers=headers, timeout=20)
            payload = response.json()
            result = payload.get("result") or []

            rows = []
            for item in result:
                balance = float(item.get("rzye", 0))
                trade_date = item.get("opDate", "")
                if balance > 0 and trade_date:
                    rows.append({"date": trade_date, "balance": balance})
            rows.sort(key=lambda row: row["date"])
            return rows
        except Exception as exc:
            logger.error("Failed to fetch SSE margin data: %s", exc)
            return []

    def _fetch_margin_szse(self, date):
        try:
            url = "https://www.szse.cn/api/report/ShowReport/data"
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": "1837_xxpl",
                "txtDate": "-".join([date[:4], date[4:6], date[6:]]),
                "tab1PAGENO": "1",
                "random": str(np.random.random()),
            }
            headers = {
                "Referer": "https://www.szse.cn/disclosure/margin/object/index.html",
                "User-Agent": self.headers["User-Agent"],
            }
            response = requests.get(url, params=params, headers=headers, timeout=20)
            payload = response.json()
            data = payload[0].get("data") if payload else None
            if not data:
                return None
            balance = float(str(data[0].get("jrrzye", "0")).replace(",", ""))
            return {"date": date, "balance": balance}
        except Exception as exc:
            logger.error("Failed to fetch SZSE margin data for %s: %s", date, exc)
            return None

    def get_margin_trading(self):
        if self.offline_mode:
            return {
                "margin_balance": None,
                "net_change": None,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "offline",
            }

        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        sse_rows = self._fetch_margin_sse(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"))
        if not sse_rows or len(sse_rows) < 2:
            return {
                "margin_balance": None,
                "net_change": None,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "missing",
            }

        latest = sse_rows[-1]
        previous = sse_rows[-2]
        szse = self._fetch_margin_szse(latest["date"])
        szse_balance = (szse["balance"] * 1e8) if szse else 0.0
        total_balance = latest["balance"] + szse_balance
        net_change = latest["balance"] - previous["balance"]

        return {
            "margin_balance": total_balance,
            "net_change": net_change,
            "sse_balance": latest["balance"],
            "szse_balance": szse_balance,
            "date": f"{latest['date'][:4]}-{latest['date'][4:6]}-{latest['date'][6:]}",
            "source": "sse_plus_szse" if szse else "sse",
        }

    def get_north_flow_historical(self, years=3):
        try:
            import akshare as ak

            end_date = datetime.now()
            start_date = end_date - timedelta(days=years * 365)
            frame = self._fetch_akshare_frame_cached(
                "ak_north_flow_history_latest",
                lambda: ak.stock_hsgt_hist_em(symbol="北向资金"),
                self.akshare_history_cache_ttl,
            )
            if frame is None or frame.empty:
                return []

            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame.iloc[:, 0]).dt.strftime("%Y-%m-%d")
            frame["net_flow"] = pd.to_numeric(frame.iloc[:, 1], errors="coerce") * 1e8
            frame = frame.dropna(subset=["net_flow"])
            frame = frame[(frame["date"] >= start_date.strftime("%Y-%m-%d")) & (frame["date"] <= end_date.strftime("%Y-%m-%d"))]
            frame = frame.sort_values("date")

            return [
                {"date": row.date, "flow": float(row.net_flow), "net_flow": float(row.net_flow), "source": "akshare"}
                for row in frame.itertuples(index=False)
            ]
        except Exception as exc:
            logger.error("Failed to fetch north flow history: %s", exc)
            return []

    def get_margin_trading_historical(self, years=3):
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years * 365)
        sse_rows = self._fetch_margin_sse(start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d"))
        if not sse_rows:
            return []

        results = []
        previous_balance = None
        for row in sse_rows:
            balance = float(row["balance"])
            net_change = balance - previous_balance if previous_balance is not None else 0.0
            results.append(
                {
                    "date": f"{row['date'][:4]}-{row['date'][4:6]}-{row['date'][6:]}",
                    "margin_balance": balance,
                    "net_change": net_change,
                    "source": "sse",
                }
            )
            previous_balance = balance
        return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetcher = DataFetcherV2()
    print(fetcher.get_index_data_eastmoney("000001", days=5).tail())
    print(fetcher.get_market_breadth())
    print(fetcher.get_north_flow())
    print(fetcher.get_margin_trading())
