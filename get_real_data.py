#!/usr/bin/env python3
"""
强制获取真实数据脚本
绕过网络检测，直接尝试获取
"""

import os
import sys
import time

# 设置环境变量禁用代理（有时代理会干扰）
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,eastmoney.com'

def get_real_data():
    """尝试获取真实数据"""
    print("=" * 60)
    print("强制获取真实A股数据")
    print("=" * 60)
    
    try:
        import akshare as ak
        from datetime import datetime
        
        today = datetime.now().strftime('%Y%m%d')
        print(f"\n今日日期: {today}")
        print("正在获取上证指数数据...")
        
        # 尝试获取今日数据
        df = ak.index_zh_a_hist(
            symbol='000001', 
            period='daily',
            start_date=today,
            end_date=today
        )
        
        if df is not None and len(df) > 0:
            row = df.iloc[0]
            print(f"\n✅ 成功获取真实数据！")
            print(f"日期: {row['日期']}")
            print(f"收盘: {row['收盘']}")
            print(f"涨跌: {row['涨跌幅']}%")
            print(f"成交额: {row['成交额']/1e8:.0f}亿")
            return True
        else:
            print("\n❌ 未获取到今日数据")
            return False
            
    except Exception as e:
        print(f"\n❌ 获取失败: {e}")
        return False

def get_with_retry():
    """带重试的获取"""
    for i in range(3):
        print(f"\n第 {i+1} 次尝试...")
        if get_real_data():
            return True
        time.sleep(2)
    return False

if __name__ == '__main__':
    success = get_with_retry()
    
    if not success:
        print("\n" + "=" * 60)
        print("无法直接获取真实数据")
        print("=" * 60)
        print("\n可能的原因：")
        print("1. 当前网络环境限制了访问")
        print("2. 需要通过代理服务器")
        print("3. 防火墙拦截了连接")
        print("\n建议方案：")
        print("- 更换网络环境（如使用手机热点）")
        print("- 配置代理服务器")
        print("- 在其他电脑上获取后复制数据文件")
