#!/usr/bin/env python3
"""
一键启动脚本
"""

import os
import sys

def check_dependencies():
    """检查依赖"""
    try:
        import pandas  # noqa: F401
        import numpy  # noqa: F401
        import tushare  # noqa: F401
        print("[OK] 核心依赖已安装")
        return True
    except ImportError as e:
        print(f"[错误] 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        return False

def check_network():
    """检查网络连接 - 使用curl_cffi测试数据源"""
    try:
        print("\n[网络诊断] 正在检查网络连接...")
        
        # 尝试使用curl_cffi获取真实数据来测试
        try:
            import curl_cffi.requests as requests
            session = requests.Session()
            
            # 测试获取上证指数数据
            url = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
            params = {
                'secid': '1.000001',
                'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
                'fields1': 'f1,f2,f3,f4,f5,f6',
                'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
                'klt': '101',
                'fqt': '0',
                'end': '20500101',
                'lmt': '5',
                '_': '1234567890'
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'Referer': 'https://quote.eastmoney.com/'
            }
            
            r = session.get(url, params=params, headers=headers, timeout=10, impersonate='chrome120')
            data = r.json()
            
            if data.get('data') and data['data'].get('klines'):
                print("[OK] 东方财富数据源可访问，可以获取真实数据")
                return True
            else:
                print(f"[警告] 数据源返回异常")
                return False
                
        except ImportError:
            # 如果没有curl_cffi，使用普通requests
            import requests
            r = requests.get('https://push2.eastmoney.com', timeout=5)
            if r.status_code == 200:
                print("[OK] 东方财富数据源可访问")
                return True
            else:
                print(f"[警告] 东方财富返回状态码: {r.status_code}")
                return False
                
        except Exception as e:
            print(f"[警告] 无法获取真实数据")
            print(f"         错误: {str(e)[:60]}...")
            print("[提示] 系统将使用模拟数据模式")
            return False
            
    except Exception as e:
        print(f"[警告] 网络检查失败: {e}")
        return False

def main():
    print("=" * 70)
    print("A股情绪指数追踪器 - 一键启动")
    print("=" * 70)
    
    # 检查依赖
    if not check_dependencies():
        return
    
    # 检查网络
    network_ok = check_network()
    
    # 创建必要目录
    os.makedirs('data', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    # 根据网络状态显示菜单
    if network_ok:
        print("\n[网络状态] 在线 - 可获取真实数据")
        print("\n选择操作:")
        print("1. 计算今日情绪指标")
        print("2. 回溯历史数据(3年)")
        print("3. 数据分析工具")
        print("4. 设置定时任务")
        print("5. 实时情绪监控")
        print("6. 使用模拟数据运行（测试用）")
    else:
        print("\n[网络状态] 离线 - 无法获取真实数据，建议使用模拟模式")
        print("\n选择操作:")
        print("1. 使用模拟数据 - 计算今日情绪指标")
        print("2. 使用模拟数据 - 生成3年历史数据")
        print("3. 数据分析工具（查看已有数据）")
        print("4. 设置定时任务")
        print("5. 实时情绪监控（模拟模式）")
    
    choice = input("\n请选择: ").strip()
    
    # 处理选择
    if choice == '1':
        from sentiment_tracker import SentimentTracker
        from data_fetcher_tushare import DataFetcherTushare as DataFetcher
        
        fetcher = DataFetcher()
        if not network_ok:
            print("\n[提示] 网络受限，启用离线模拟模式")
            fetcher.enable_offline_mode()
        
        tracker = SentimentTracker(fetcher=fetcher)
        result = tracker.run()
        if result:
            print(f"\n执行成功: {result['sentiment_score']:.1f}分")
    
    elif choice == '2':
        from sentiment_tracker import SentimentTracker
        from data_fetcher_tushare import DataFetcherTushare as DataFetcher

        fetcher = DataFetcher()
        if not network_ok:
            print("\n[提示] 网络受限，启用离线模拟模式")
            fetcher.enable_offline_mode()

        tracker = SentimentTracker(fetcher=fetcher)
        tracker.backfill_history(days=1100)
    
    elif choice == '3':
        from sentiment_analyzer import SentimentAnalyzer
        analyzer = SentimentAnalyzer()
        analyzer.show_summary()
    
    elif choice == '4':
        import setup_scheduler
        setup_scheduler.main()
    
    elif choice == '5':
        from sentiment_tracker import SentimentTracker
        from data_fetcher_tushare import DataFetcherTushare as DataFetcher

        fetcher = DataFetcher()
        if not network_ok:
            fetcher.enable_offline_mode()

        tracker = SentimentTracker(fetcher=fetcher)
        tracker.realtime_monitor()
    
    elif choice == '6' and network_ok:
        # 在线模式下的模拟数据选项
        print("\n[模拟模式] 使用随机生成的模拟数据运行")
        from sentiment_tracker import SentimentTracker
        from data_fetcher_tushare import DataFetcherTushare as DataFetcher

        fetcher = DataFetcher()
        fetcher.enable_offline_mode()
        
        print("\n选择模拟操作:")
        print("1. 计算今日模拟情绪")
        print("2. 生成3年模拟历史数据")
        
        mock_choice = input("\n请选择 (1/2): ").strip()
        
        tracker = SentimentTracker(fetcher=fetcher)
        
        if mock_choice == '1':
            result = tracker.run()
            if result:
                print(f"\n模拟结果: {result['sentiment_score']:.1f}分")
        elif mock_choice == '2':
            tracker.backfill_history(days=1100)
        else:
            print("无效选项")
    
    else:
        print("无效选项")

if __name__ == '__main__':
    main()
