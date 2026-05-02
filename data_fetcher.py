#!/usr/bin/env python3
"""
数据获取模块 - 使用curl_cffi获取A股数据
支持3年历史数据回溯

DEPRECATED: 此模块已弃用，请使用 data_fetcher_v2.py。
保留此文件仅为向后兼容，新代码请导入 DataFetcherV2。
"""

import warnings

warnings.warn(
    "data_fetcher.py is deprecated, use data_fetcher_v2.DataFetcherV2 instead",
    DeprecationWarning,
    stacklevel=2,
)

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import time
import random

# 尝试导入curl_cffi，如果失败则使用requests
try:
    import curl_cffi.requests as requests
    USE_CURL = True
except ImportError:
    import requests
    USE_CURL = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 尝试导入网络配置
try:
    from network_config import PROXY_CONFIG, REQUEST_TIMEOUT, MAX_RETRIES, OFFLINE_MODE
except ImportError:
    PROXY_CONFIG = {'http': None, 'https': None}
    REQUEST_TIMEOUT = 30
    MAX_RETRIES = 3
    OFFLINE_MODE = False


class DataFetcher:
    """A股数据获取器"""
    
    def __init__(self):
        self.data_cache = {}
        self.request_delay = 0.5
        self.offline_mode = OFFLINE_MODE
        self._network_checked = False
        self._network_available = False
        self.session = requests.Session() if USE_CURL else requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://quote.eastmoney.com/'
        }
        
    def check_network(self):
        """检查网络连接状态"""
        if self._network_checked:
            return self._network_available
            
        try:
            # 测试连接东方财富
            if USE_CURL:
                response = self.session.get(
                    'https://push2.eastmoney.com', 
                    timeout=10
                )
            else:
                response = requests.get(
                    'https://push2.eastmoney.com', 
                    timeout=10,
                    proxies=PROXY_CONFIG if PROXY_CONFIG.get('https') else None
                )
            self._network_available = response.status_code == 200
            self._network_checked = True
            return self._network_available
        except Exception as e:
            logger.warning(f"网络连接测试失败: {e}")
            self._network_available = False
            self._network_checked = True
            return False
    
    def set_proxy(self, http_proxy=None, https_proxy=None):
        """设置代理"""
        if http_proxy:
            PROXY_CONFIG['http'] = http_proxy
        if https_proxy:
            PROXY_CONFIG['https'] = https_proxy
        logger.info(f"代理已设置: HTTP={http_proxy}, HTTPS={https_proxy}")
    
    def enable_offline_mode(self):
        """启用离线模式（使用模拟数据）"""
        self.offline_mode = True
        self._network_checked = True
        self._network_available = False
        logger.warning("已启用离线模式，将使用模拟数据")
    
    def _make_request(self, url, params=None, timeout=15):
        """发送HTTP请求"""
        try:
            if USE_CURL:
                return self.session.get(url, params=params, headers=self.headers, 
                                       timeout=timeout, impersonate='chrome120')
            else:
                return requests.get(url, params=params, headers=self.headers,
                                  timeout=timeout, 
                                  proxies=PROXY_CONFIG if PROXY_CONFIG.get('https') else None)
        except Exception as e:
            logger.error(f"请求失败: {e}")
            raise
    
    def get_index_data_range(self, symbol='000001', years=3):
        """
        获取指数多年数据（支持3年回溯）
        """
        try:
            if self.offline_mode:
                logger.info("离线模式：生成模拟指数数据")
                return self._generate_mock_index_data(years)
            
            logger.info(f"获取 {symbol} {years}年历史数据...")
            
            # 使用东方财富API获取历史数据
            url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
            
            # 市场代码: 1=上海, 0=深圳
            market = '1' if symbol.startswith('0') else '0'
            secid = f"{market}.{symbol}"
            
            params = {
                'secid': secid,
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                'klt': '101',  # 日K
                'fqt': '0',
                'end': '20500101',
                'lmt': str(years * 365),
                '_': str(int(time.time() * 1000))
            }
            
            r = self._make_request(url, params=params, timeout=20)
            data = r.json()
            
            if data.get('data') and data['data'].get('klines'):
                klines = data['data']['klines']
                
                # 解析K线数据
                records = []
                for kline in klines:
                    # 格式: 日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
                    parts = kline.split(',')
                    if len(parts) >= 10:
                        records.append({
                            '日期': parts[0],
                            '开盘': float(parts[1]),
                            '收盘': float(parts[2]),
                            '最高': float(parts[3]),
                            '最低': float(parts[4]),
                            '成交量': float(parts[5]),
                            '成交额': float(parts[6]),
                            '振幅': float(parts[7]),
                            '涨跌幅': float(parts[8]),
                            '涨跌额': float(parts[9]),
                            '换手率': float(parts[10]) if len(parts) > 10 else 0
                        })
                
                df = pd.DataFrame(records)
                logger.info(f"成功获取 {symbol} {len(df)} 条历史数据")
                return df
            else:
                logger.warning(f"未获取到 {symbol} 数据，使用模拟数据")
                return self._generate_mock_index_data(years)
            
        except Exception as e:
            logger.error(f"获取历史数据失败: {e}")
            logger.warning("切换到模拟数据模式")
            return self._generate_mock_index_data(years)
    
    def _generate_mock_index_data(self, years=3):
        """生成模拟指数数据（离线模式使用）"""
        logger.info(f"生成{years}年模拟指数数据...")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=years*365)
        
        # 生成交易日（排除周末）
        dates = []
        current = start_date
        base_price = 3000
        
        while current < end_date:
            if current.weekday() < 5:  # 周一到周五
                dates.append(current)
            current += timedelta(days=1)
        
        # 生成随机游走价格数据
        data = []
        price = base_price
        
        for i, date in enumerate(dates):
            # 随机涨跌幅 -2% 到 +2%
            change_pct = random.gauss(0, 1.5)
            
            open_price = price * (1 + random.gauss(0, 0.005))
            close_price = price * (1 + change_pct / 100)
            high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, 0.005)))
            low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, 0.005)))
            volume = random.randint(200000000000, 800000000000)  # 2000亿-8000亿
            
            data.append({
                '日期': date.strftime('%Y-%m-%d'),
                '开盘': round(open_price, 2),
                '收盘': round(close_price, 2),
                '最高': round(high_price, 2),
                '最低': round(low_price, 2),
                '成交量': volume,
                '成交额': volume * close_price,
                '振幅': abs(change_pct) * 2,
                '涨跌幅': change_pct,
                '涨跌额': close_price - open_price,
                '换手率': random.uniform(0.5, 3.0)
            })
            
            price = close_price
        
        df = pd.DataFrame(data)
        logger.info(f"生成模拟数据 {len(df)} 条")
        return df
    
    def get_market_breadth(self, date=None):
        """获取市场涨跌广度数据"""
        try:
            if self.offline_mode:
                return self._generate_mock_breadth(date)
            
            if date is None:
                date = datetime.now().strftime('%Y%m%d')
            
            # 使用东方财富API获取A股列表
            url = 'https://push2.eastmoney.com/api/qt/clist/get'
            params = {
                'pn': '1',
                'pz': '5000',
                'po': '1',
                'np': '1',
                'ut': 'bd1d9ddb04089700cf9c27f6f7426281',
                'fltt': '2',
                'invt': '2',
                'fid': 'f20',
                'fs': 'm:0+t:6,m:0+t:13,m:1+t:2,m:1+t:23',
                'fields': 'f2,f3,f12,f14',
                '_': str(int(time.time() * 1000))
            }
            
            r = self._make_request(url, params=params, timeout=20)
            data = r.json()
            
            if data.get('data') and data['data'].get('diff'):
                stocks = data['data']['diff']
                
                up_count = sum(1 for s in stocks if s.get('f3') and float(s['f3']) > 0)
                down_count = sum(1 for s in stocks if s.get('f3') and float(s['f3']) < 0)
                flat_count = sum(1 for s in stocks if s.get('f3') and float(s['f3']) == 0)
                limit_up = sum(1 for s in stocks if s.get('f3') and float(s['f3']) >= 9.5)
                limit_down = sum(1 for s in stocks if s.get('f3') and float(s['f3']) <= -9.5)
                
                total = up_count + down_count + flat_count
                
                result = {
                    'up_count': up_count,
                    'down_count': down_count,
                    'flat_count': flat_count,
                    'limit_up': limit_up,
                    'limit_down': limit_down,
                    'total': up_count + down_count + flat_count,
                    'up_ratio': up_count / total * 100 if total > 0 else 0,
                    'date': date
                }
                
                logger.info(f"涨跌统计 - 涨:{up_count} 跌:{down_count} 平:{flat_count}")
                return result
            else:
                logger.warning("未获取到市场广度数据")
                return self._generate_mock_breadth(date)
            
        except Exception as e:
            logger.error(f"获取市场广度数据失败: {e}")
            return self._generate_mock_breadth(date)
    
    def _generate_mock_breadth(self, date=None):
        """生成模拟市场广度数据"""
        if date is None:
            date = datetime.now().strftime('%Y%m%d')
        
        up_ratio = random.gauss(50, 15)  # 均值50%，标准差15%
        up_ratio = max(10, min(90, up_ratio))
        
        total = 5000
        up_count = int(total * up_ratio / 100)
        down_count = int(total * (100 - up_ratio) / 100 * 0.9)
        flat_count = total - up_count - down_count
        
        result = {
            'up_count': up_count,
            'down_count': down_count,
            'flat_count': flat_count,
            'limit_up': random.randint(20, 100),
            'limit_down': random.randint(10, 50),
            'total': total,
            'up_ratio': up_ratio,
            'date': date
        }
        
        logger.info(f"模拟涨跌统计 - 涨:{up_count} 跌:{down_count} 平:{flat_count}")
        return result
    
    def get_north_flow(self):
        """获取北向资金流向"""
        try:
            if self.offline_mode:
                return self._generate_mock_north_flow()
            
            url = 'https://push2.eastmoney.com/api/qt/kamt.rtmin/get'
            params = {
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'fields1': 'f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58',
                '_': str(int(time.time() * 1000))
            }
            
            r = self._make_request(url, params=params, timeout=10)
            data = r.json()
            
            if data.get('data'):
                d = data['data']
                # 获取当日累计净流入
                net_flow = 0
                if d.get('s2n'):
                    s2n = d['s2n']
                    if isinstance(s2n, str):
                        parts = s2n.split(',')
                        if len(parts) >= 3:
                            net_flow = float(parts[2])
                    elif isinstance(s2n, list) and len(s2n) > 0:
                        # 如果是列表，取最后一个时间点的数据
                        last = s2n[-1]
                        if isinstance(last, str):
                            parts = last.split(',')
                            if len(parts) >= 3:
                                net_flow = float(parts[2])
                
                result = {
                    'net_flow': net_flow,
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                logger.info(f"北向资金净流入: {net_flow/1e8:.2f}亿")
                return result
            else:
                logger.warning("未获取到北向资金数据")
                return self._generate_mock_north_flow()
            
        except Exception as e:
            logger.error(f"获取北向资金数据失败: {e}")
            return self._generate_mock_north_flow()
    
    def _generate_mock_north_flow(self):
        """生成模拟北向资金数据"""
        net_flow = random.gauss(0, 5e9)  # 均值0，标准差5亿
        result = {
            'net_flow': net_flow,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        logger.info(f"模拟北向资金净流入: {net_flow/1e8:.2f}亿")
        return result
    
    def get_margin_trading(self):
        """获取融资融券数据"""
        try:
            if self.offline_mode:
                return self._generate_mock_margin()
            
            # 融资融券数据API
            url = 'https://datacenter-web.eastmoney.com/api/data/v1/get'
            params = {
                'sortColumns': 'TRADE_DATE',
                'sortTypes': '-1',
                'pageSize': '10',
                'pageNumber': '1',
                'reportName': 'RPTA_WEB_RZRQ_GGMX',
                'columns': 'ALL',
                'source': 'WEB',
                'client': 'WEB',
                '_': str(int(time.time() * 1000))
            }
            
            r = self._make_request(url, params=params, timeout=10)
            data = r.json()
            
            if data.get('result') and data['result'].get('data'):
                records = data['result']['data']
                total_balance = sum(float(r.get('FIN_BALANCE', 0)) for r in records[:5])
                
                result = {
                    'margin_balance': total_balance,
                    'date': datetime.now().strftime('%Y-%m-%d')
                }
                
                logger.info(f"融资余额: {total_balance/1e8:.2f}亿")
                return result
            else:
                logger.warning("未获取到融资融券数据")
                return self._generate_mock_margin()
            
        except Exception as e:
            logger.error(f"获取融资融券数据失败: {e}")
            return self._generate_mock_margin()
    
    def _generate_mock_margin(self):
        """生成模拟融资融券数据"""
        margin_balance = random.uniform(1.5e12, 1.8e12)  # 1.5-1.8万亿
        result = {
            'margin_balance': margin_balance,
            'date': datetime.now().strftime('%Y-%m-%d')
        }
        logger.info(f"模拟融资余额: {margin_balance/1e8:.2f}亿")
        return result
