#!/usr/bin/env python3
"""
Configuration for the A-share sentiment tracker.
"""

from __future__ import annotations

import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

DATA_SOURCES = {
    "index_codes": {
        "shanghai_composite": "000001.SH",
        "szse_component": "399001.SZ",
        "chinext": "399006.SZ",
        "csi300": "000300.SH",
        "csi500": "000905.SH",
        "star50": "000688.SH",
    }
}

SENTIMENT_WEIGHTS = {
    "market_breadth": 0.25,
    "cross_section": 0.15,
    "volume_change": 0.15,
    "volatility": 0.15,
    "north_flow": 0.15,
    "margin_trading": 0.10,
    "trend": 0.05,
}

SENTIMENT_LEVELS = {
    "极度恐慌": (0, 20),
    "偏谨慎": (20, 40),
    "中性": (40, 60),
    "偏乐观": (60, 80),
    "过热": (80, 100),
}

REFRESH_INTERVAL = 300
ENABLE_AUTO_CLEANUP = False
MAX_HISTORY_DAYS = 3650

LOG_CONFIG = {
    "level": "INFO",
    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    "file": os.path.join(LOGS_DIR, "sentiment.log"),
}
