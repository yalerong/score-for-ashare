import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from data_fetcher_v2 import DataFetcherV2, _env_int


class DataFetcherCacheTests(unittest.TestCase):
    def test_akshare_frame_cache_avoids_repeated_fetches(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetcher = DataFetcherV2()
            fetcher.cache_dir = Path(tmp_dir)
            calls = {"count": 0}

            def fetch_frame():
                calls["count"] += 1
                return pd.DataFrame({"value": [1.0]})

            first = fetcher._fetch_akshare_frame_cached("sample", fetch_frame, ttl_seconds=3600)
            second = fetcher._fetch_akshare_frame_cached("sample", fetch_frame, ttl_seconds=3600)

            self.assertEqual(calls["count"], 1)
            self.assertEqual(first.to_dict("records"), [{"value": 1.0}])
            self.assertEqual(second.to_dict("records"), [{"value": 1.0}])

    def test_akshare_frame_cache_uses_stale_data_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetcher = DataFetcherV2()
            fetcher.cache_dir = Path(tmp_dir)
            fetcher._write_cache(
                "sample",
                fetcher._frame_to_cache_data(pd.DataFrame({"value": [2.0]})),
            )

            def fail_fetch():
                raise RuntimeError("limited")

            result = fetcher._fetch_akshare_frame_cached("sample", fail_fetch, ttl_seconds=-1)

            self.assertEqual(result.to_dict("records"), [{"value": 2.0}])

    def test_index_range_cache_returns_copies(self):
        class CountingFetcher(DataFetcherV2):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def get_index_data_eastmoney(self, symbol="000001", days=30):
                self.calls += 1
                return pd.DataFrame(
                    {
                        "date": ["2026-05-11"],
                        "open": [1.0],
                        "close": [2.0],
                        "high": [2.0],
                        "low": [1.0],
                        "amount": [100.0],
                        "volume": [50.0],
                        "amplitude": [1.0],
                        "change_pct": [0.5],
                        "change": [1.0],
                        "turnover": [1.0],
                    }
                )

        fetcher = CountingFetcher()
        first = fetcher.get_index_data_range("000001", years=1)
        first.loc[0, "close"] = 99.0
        second = fetcher.get_index_data_range("000001", years=1)

        self.assertEqual(fetcher.calls, 1)
        self.assertEqual(second.loc[0, "close"], 2.0)

    def test_eastmoney_kline_maps_volume_and_amount_fields(self):
        fetcher = DataFetcherV2()
        record = fetcher._parse_eastmoney_kline(
            [
                "2026-05-12",
                "4229.28",
                "4210.26",
                "4230.18",
                "4199.34",
                "563610614",
                "1152331476571.70",
                "0.73",
                "-0.35",
                "-14.76",
                "1.17",
            ]
        )

        self.assertEqual(record["volume"], 563610614.0)
        self.assertEqual(record["amount"], 1152331476571.70)

    def test_invalid_ttl_environment_uses_default(self):
        with patch.dict("os.environ", {"SCORE_SPOT_CACHE_TTL_SECONDS": "bad"}):
            self.assertEqual(_env_int("SCORE_SPOT_CACHE_TTL_SECONDS", 60), 60)

    def test_eastmoney_spot_cache_avoids_repeated_fetches(self):
        class CountingFetcher(DataFetcherV2):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def _fetch_market_spot_snapshot(self, page_size=100):
                self.calls += 1
                return ([{"f3": "1.2"}], 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            fetcher = CountingFetcher()
            fetcher.cache_dir = Path(tmp_dir)

            first = fetcher._get_cached_spot_snapshot(ttl=0)
            fetcher._spot_cache = None
            second = fetcher._get_cached_spot_snapshot(ttl=0)

            self.assertEqual(fetcher.calls, 1)
            self.assertEqual(first, ([{"f3": "1.2"}], 1))
            self.assertEqual(second, ([{"f3": "1.2"}], 1))

    def test_sina_spot_cache_uses_stale_rows_after_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fetcher = DataFetcherV2()
            fetcher.cache_dir = Path(tmp_dir)
            fetcher._write_rows_cache("sina_market_spot", [{"changepercent": "0.8"}], 1)

            with patch("data_fetcher_v2.std_requests.get", side_effect=RuntimeError("limited")):
                rows, total = fetcher._fetch_sina_market_snapshot()

            self.assertEqual(rows, [{"changepercent": "0.8"}])
            self.assertEqual(total, 1)

    def test_cross_section_uses_sina_when_eastmoney_spot_missing(self):
        class SinaFallbackFetcher(DataFetcherV2):
            def _get_cached_spot_snapshot(self, ttl=60):
                return None, None

            def _fetch_sina_market_snapshot(self):
                return (
                    [
                        {"changepercent": "1.0"},
                        {"changepercent": "-2.0"},
                        {"changepercent": "0.5"},
                    ],
                    3,
                )

            def _fetch_limit_pool_snapshot(self, date_str):
                return None, None, None

            def _fetch_style_snapshot(self, date=None):
                return {"microcap_change": None, "largecap_change": None}

        result = SinaFallbackFetcher().get_cross_sectional_state("2026-05-12")

        self.assertEqual(result["source"], "sina_cross_section")
        self.assertEqual(result["sample_size"], 3)
        self.assertEqual(result["universe_size"], 3)
        self.assertAlmostEqual(result["up_ratio"], 2 / 3 * 100)


if __name__ == "__main__":
    unittest.main()
