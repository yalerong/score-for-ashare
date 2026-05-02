#!/usr/bin/env python3
"""
网络配置模块
处理代理设置和网络连接
"""

import os

# 代理设置
# 如果您需要通过代理访问网络，请取消下面注释并填写代理地址
PROXY_CONFIG = {
    'http': None,   # 例如: 'http://127.0.0.1:7890'
    'https': None,  # 例如: 'https://127.0.0.1:7890'
}

# 从环境变量读取代理（如果设置的话）
if os.environ.get('HTTP_PROXY'):
    PROXY_CONFIG['http'] = os.environ.get('HTTP_PROXY')
if os.environ.get('HTTPS_PROXY'):
    PROXY_CONFIG['https'] = os.environ.get('HTTPS_PROXY')

# 请求超时设置（秒）
REQUEST_TIMEOUT = 30

# 重试次数
MAX_RETRIES = 3

# 数据源URL
DATA_SOURCES = {
    'eastmoney': 'https://push2.eastmoney.com',
    'akshare': 'https://www.akshare.xyz',
}

# 离线模式（无法联网时使用模拟数据）
OFFLINE_MODE = False
