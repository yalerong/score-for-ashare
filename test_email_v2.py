#!/usr/bin/env python3
"""
测试邮件发送（使用3月30日的数据，包含数据源信息）
"""

import json
from datetime import datetime
from sentiment_email_sender import generate_email_content, send_email

def test_email():
    """测试发送邮件"""
    print("=" * 60)
    print("📧 测试邮件发送（带数据源标注）")
    print("=" * 60)
    
    # 加载3月30日的数据
    with open('data/sentiment_history.json', 'r', encoding='utf-8') as f:
        history = json.load(f)
    
    # 查找3月30日的数据
    target_date = "2026-03-30"
    data = None
    for record in history:
        if record.get('date') == target_date:
            data = record
            break
    
    if not data:
        print(f"❌ 未找到 {target_date} 的数据")
        return
    
    print(f"\n📅 使用日期: {target_date}")
    print(f"📊 情绪分数: {data['sentiment_score']:.2f}分")
    print(f"📈 情绪等级: {data['sentiment_level']}")
    
    # 添加数据源信息到raw_data
    if 'raw_data' not in data:
        data['raw_data'] = {}
    
    # 设置各指标的数据源
    data['raw_data']['breadth_source'] = 'eastmoney_indices'
    data['raw_data']['volume_source'] = 'real'
    data['raw_data']['volatility_source'] = 'real'
    data['raw_data']['north_source'] = 'eastmoney'
    data['raw_data']['margin_source'] = data['raw_data'].get('margin_source', 'akshare')
    
    print(f"\n📊 数据源信息:")
    print(f"  市场涨跌广度: {data['raw_data']['breadth_source']}")
    print(f"  成交量变化: {data['raw_data']['volume_source']}")
    print(f"  波动率: {data['raw_data']['volatility_source']}")
    print(f"  北向资金流: {data['raw_data']['north_source']}")
    print(f"  融资融券: {data['raw_data']['margin_source']}")
    
    # 生成邮件内容
    print("\n📝 生成邮件内容...")
    html_content, text_content = generate_email_content(data)
    
    # 查找图表文件
    import os
    chart_path = None
    for file in os.listdir('data'):
        if 'sentiment_20260330' in file and file.endswith('.png'):
            chart_path = os.path.join('data', file)
            break
    
    if chart_path:
        print(f"📎 找到图表: {chart_path}")
    
    # 发送邮件
    print("\n📤 正在发送邮件...")
    print("  发件人: 18201900134@163.com")
    print("  收件人: 18201900134@163.com, ylb6475164@qq.com")
    
    success = send_email(html_content, text_content, target_date, chart_path)
    
    if success:
        print("\n" + "=" * 60)
        print("✅ 邮件发送成功！")
        print("=" * 60)
        print("\n请检查邮箱:")
        print("  - 18201900134@163.com")
        print("  - ylb6475164@qq.com")
        print("\n邮件主题: [A股情绪指标] 2026-03-30 情绪中性")
    else:
        print("\n" + "=" * 60)
        print("❌ 邮件发送失败")
        print("=" * 60)


if __name__ == '__main__':
    test_email()
