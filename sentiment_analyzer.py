#!/usr/bin/env python3
"""
A股情绪指标分析器
提供历史数据分析、统计报告生成等功能
支持3年历史数据
"""

import json
import logging
import os
from datetime import datetime, timedelta

try:
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    MATPLOTLIB_AVAILABLE = True
    plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False
except ImportError:
    MATPLOTLIB_AVAILABLE = False

import numpy as np
import pandas as pd

from config import DATA_DIR, SENTIMENT_LEVELS

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """情绪指标分析器"""
    
    def __init__(self):
        self.data_file = os.path.join(DATA_DIR, 'sentiment_history.json')
        self.data = self.load_data()
    
    def load_data(self):
        """加载历史数据"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载数据失败: {e}")
        return []
    
    def get_dataframe(self):
        """将数据转换为DataFrame"""
        if not self.data:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.data)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['date'] = pd.to_datetime(df['timestamp']).dt.date
        elif 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date']).dt.date
        return df
    
    def show_summary(self):
        """显示数据摘要"""
        print("\n" + "=" * 60)
        print("A股情绪指标数据分析")
        print("=" * 60)
        
        df = self.get_dataframe()
        
        if df.empty:
            print("\n暂无数据，请先运行情绪追踪器或回溯历史数据")
            return
        
        print(f"\n[数据统计]")
        print(f"   总记录数: {len(df)}")
        print(f"   数据范围: {df['date'].min()} 至 {df['date'].max()}")
        
        # 计算时间跨度
        days_span = (df['date'].max() - df['date'].min()).days
        print(f"   时间跨度: {days_span}天 (约{days_span/365:.1f}年)")
        
        print(f"\n[情绪分数统计]")
        print(f"   平均值: {df['sentiment_score'].mean():.2f}")
        print(f"   最大值: {df['sentiment_score'].max():.2f}")
        print(f"   最小值: {df['sentiment_score'].min():.2f}")
        print(f"   标准差: {df['sentiment_score'].std():.2f}")
        
        # 分年度统计
        df['year'] = pd.to_datetime(df['date']).dt.year
        print(f"\n[年度统计]")
        for year in sorted(df['year'].unique()):
            year_data = df[df['year'] == year]
            print(f"   {year}年: {len(year_data)}条, 平均{year_data['sentiment_score'].mean():.1f}分")
        
        # 情绪等级分布
        print(f"\n[情绪等级分布]")
        level_counts = df['sentiment_level'].value_counts()
        for level, count in level_counts.items():
            pct = count / len(df) * 100
            bar = '#' * int(pct / 2)
            print(f"   {level:10s}: {bar} {count:4d}次 ({pct:5.1f}%)")
        
        # 最近记录
        print(f"\n[最近5条记录]")
        recent = df.tail(5)
        if 'timestamp' in recent.columns:
            recent_display = recent[['timestamp', 'sentiment_score', 'sentiment_level']]
        else:
            recent_display = recent[['date', 'sentiment_score', 'sentiment_level']]
        for _, row in recent_display.iterrows():
            time_val = row.get('timestamp') or row.get('date')
            print(f"   {time_val}: {row['sentiment_score']:.1f}分 - {row['sentiment_level']}")
        
        # 显示菜单
        self._show_analysis_menu()
    
    def _show_analysis_menu(self):
        """显示分析菜单"""
        print("\n" + "-" * 40)
        print("分析选项:")
        print("1. 生成详细报告")
        print("2. 查看趋势分析")
        print("3. 年度对比分析")
        print("4. 导出数据到CSV")
        print("5. 生成图表")
        print("6. 返回主菜单")
        
        choice = input("\n请选择 (1-6): ").strip()
        
        if choice == '1':
            self.generate_report()
        elif choice == '2':
            self.analyze_trend()
        elif choice == '3':
            self.analyze_yearly()
        elif choice == '4':
            self.export_csv()
        elif choice == '5':
            self.generate_charts()
        elif choice == '6':
            return
        else:
            print("无效选项")
    
    def generate_report(self):
        """生成详细报告"""
        df = self.get_dataframe()
        
        if df.empty:
            print("暂无数据")
            return
        
        report_path = os.path.join(DATA_DIR, f'report_{datetime.now().strftime("%Y%m%d")}.txt')
        
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 70 + "\n")
            f.write("A股情绪指标分析报告\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 70 + "\n\n")
            
            # 数据概览
            f.write("【数据概览】\n")
            f.write(f"统计周期: {df['date'].min()} 至 {df['date'].max()}\n")
            days_span = (df['date'].max() - df['date'].min()).days
            f.write(f"时间跨度: {days_span}天 (约{days_span/365:.1f}年)\n")
            f.write(f"总记录数: {len(df)}\n\n")
            
            # 情绪分数统计
            f.write("【情绪分数统计】\n")
            f.write(f"平均值: {df['sentiment_score'].mean():.2f}\n")
            f.write(f"中位数: {df['sentiment_score'].median():.2f}\n")
            f.write(f"最大值: {df['sentiment_score'].max():.2f}\n")
            f.write(f"最小值: {df['sentiment_score'].min():.2f}\n")
            f.write(f"标准差: {df['sentiment_score'].std():.2f}\n\n")
            
            # 情绪等级分布
            f.write("【情绪等级分布】\n")
            level_counts = df['sentiment_level'].value_counts()
            for level, count in level_counts.items():
                pct = count / len(df) * 100
                bar = '#' * int(pct / 2)
                f.write(f"{level:10s}: {bar} {count:4d}次 ({pct:5.1f}%)\n")
            f.write("\n")
            
            # 年度统计
            df['year'] = pd.to_datetime(df['date']).dt.year
            f.write("【年度统计】\n")
            for year in sorted(df['year'].unique()):
                year_data = df[df['year'] == year]
                f.write(f"\n{year}年:\n")
                f.write(f"  数据条数: {len(year_data)}\n")
                f.write(f"  平均分: {year_data['sentiment_score'].mean():.2f}\n")
                f.write(f"  最高分: {year_data['sentiment_score'].max():.2f}\n")
                f.write(f"  最低分: {year_data['sentiment_score'].min():.2f}\n")
                f.write(f"  标准差: {year_data['sentiment_score'].std():.2f}\n")
            
            # 极值分析
            f.write("\n【极值记录】\n")
            max_idx = df['sentiment_score'].idxmax()
            min_idx = df['sentiment_score'].idxmin()
            f.write(f"最高情绪: {df.loc[max_idx, 'sentiment_score']:.1f}分 ({df.loc[max_idx, 'date']})\n")
            f.write(f"最低情绪: {df.loc[min_idx, 'sentiment_score']:.1f}分 ({df.loc[min_idx, 'date']})\n")
        
        print(f"\n报告已生成: {report_path}")
    
    def analyze_trend(self):
        """趋势分析"""
        df = self.get_dataframe()
        
        if len(df) < 5:
            print("数据不足，需要至少5条记录")
            return
        
        print("\n" + "=" * 60)
        print("趋势分析")
        print("=" * 60)
        
        df = df.sort_values('date' if 'date' in df.columns else 'timestamp')
        
        # 计算移动平均线
        df['ma5'] = df['sentiment_score'].rolling(window=5).mean()
        df['ma20'] = df['sentiment_score'].rolling(window=20).mean()
        df['ma60'] = df['sentiment_score'].rolling(window=60).mean()
        
        # 当前趋势
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        print(f"\n[当前趋势]")
        
        # 与昨日比较
        change = current['sentiment_score'] - prev['sentiment_score']
        trend = "上升" if change > 0 else "下降" if change < 0 else "持平"
        print(f"   较昨日: {change:+.1f}分 ({trend})")
        
        # 均线判断
        if 'ma5' in current and pd.notna(current['ma5']):
            if current['sentiment_score'] > current['ma5']:
                print(f"   短期趋势: 情绪在5日均线上方，偏乐观")
            else:
                print(f"   短期趋势: 情绪在5日均线下方，偏谨慎")
        
        if 'ma20' in current and pd.notna(current['ma20']):
            if current['ma5'] > current['ma20'] if 'ma5' in current and pd.notna(current['ma5']) else False:
                print(f"   中期趋势: 5日均线上穿20日均线，趋势向好")
            else:
                print(f"   中期趋势: 5日均线下穿20日均线，趋势转弱")
        
        # 波动分析
        recent_volatility = df['sentiment_score'].tail(20).std()
        if recent_volatility < 5:
            print(f"   波动状态: 低波动 (σ={recent_volatility:.1f})")
        elif recent_volatility < 15:
            print(f"   波动状态: 中等波动 (σ={recent_volatility:.1f})")
        else:
            print(f"   波动状态: 高波动 (σ={recent_volatility:.1f})")
        
        # 长期趋势
        if len(df) >= 60:
            print(f"\n[长期趋势 (60日)]")
            ma60_current = df['ma60'].iloc[-1]
            ma60_prev = df['ma60'].iloc[-20] if len(df) >= 80 else df['ma60'].iloc[-10]
            if pd.notna(ma60_current) and pd.notna(ma60_prev):
                if ma60_current > ma60_prev:
                    print(f"   60日均线上升，长期情绪向好")
                else:
                    print(f"   60日均线下降，长期情绪偏弱")
    
    def analyze_yearly(self):
        """年度对比分析"""
        df = self.get_dataframe()
        
        if df.empty:
            print("暂无数据")
            return
        
        df['year'] = pd.to_datetime(df['date']).dt.year
        
        print("\n" + "=" * 60)
        print("年度对比分析")
        print("=" * 60)
        
        years = sorted(df['year'].unique())
        
        print(f"\n{'年份':<8}{'平均':<10}{'最高':<10}{'最低':<10}{'标准差':<10}{'天数':<8}")
        print("-" * 60)
        
        for year in years:
            year_data = df[df['year'] == year]
            print(f"{year:<8}{year_data['sentiment_score'].mean():<10.1f}"
                  f"{year_data['sentiment_score'].max():<10.1f}"
                  f"{year_data['sentiment_score'].min():<10.1f}"
                  f"{year_data['sentiment_score'].std():<10.1f}"
                  f"{len(year_data):<8d}")
        
        # 年份间比较
        if len(years) >= 2:
            print(f"\n[年度对比]")
            latest_year = years[-1]
            prev_year = years[-2]
            
            latest_mean = df[df['year'] == latest_year]['sentiment_score'].mean()
            prev_mean = df[df['year'] == prev_year]['sentiment_score'].mean()
            
            change = latest_mean - prev_mean
            direction = "提升" if change > 0 else "下降"
            print(f"   {latest_year}年较{prev_year}年情绪平均{direction}{abs(change):.1f}分")
    
    def export_csv(self):
        """导出数据到CSV"""
        df = self.get_dataframe()
        
        if df.empty:
            print("暂无数据")
            return
        
        csv_path = os.path.join(DATA_DIR, f'sentiment_data_{datetime.now().strftime("%Y%m%d")}.csv')
        
        # 展开components列
        if 'components' in df.columns:
            comp_df = df['components'].apply(pd.Series)
            df_export = pd.concat([df.drop('components', axis=1), comp_df], axis=1)
        else:
            df_export = df
        
        df_export.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n数据已导出: {csv_path}")
        print(f"   共 {len(df_export)} 条记录")
    
    def generate_charts(self):
        """生成图表"""
        if not MATPLOTLIB_AVAILABLE:
            print("matplotlib 未安装，无法生成图表")
            return
            
        df = self.get_dataframe()
        
        if len(df) < 2:
            print("数据不足")
            return
        
        df = df.sort_values('date' if 'date' in df.columns else 'timestamp')
        
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        fig.suptitle('A股情绪指标分析报告', fontsize=16, fontweight='bold')
        
        date_col = 'date' if 'date' in df.columns else 'timestamp'
        
        # 1. 趋势图
        ax1 = axes[0, 0]
        ax1.plot(df[date_col], df['sentiment_score'], linewidth=1.5, alpha=0.7, label='情绪分数')
        
        # 添加移动平均线
        if len(df) >= 20:
            df['ma20'] = df['sentiment_score'].rolling(window=20).mean()
            ax1.plot(df[date_col], df['ma20'], '--', alpha=0.8, label='MA20')
        if len(df) >= 60:
            df['ma60'] = df['sentiment_score'].rolling(window=60).mean()
            ax1.plot(df[date_col], df['ma60'], '--', alpha=0.8, label='MA60')
        
        ax1.axhline(y=50, color='gray', linestyle='--', alpha=0.5)
        ax1.fill_between(df[date_col], 50, df['sentiment_score'], 
                         where=(df['sentiment_score'] >= 50), alpha=0.3, color='green')
        ax1.fill_between(df[date_col], 50, df['sentiment_score'], 
                         where=(df['sentiment_score'] < 50), alpha=0.3, color='red')
        ax1.set_ylim(0, 100)
        ax1.set_ylabel('情绪分数')
        ax1.set_title('情绪趋势 (全部历史)')
        ax1.legend()
        ax1.tick_params(axis='x', rotation=45)
        
        # 2. 情绪等级分布饼图
        ax2 = axes[0, 1]
        level_counts = df['sentiment_level'].value_counts()
        colors = ['#d32f2f', '#ff9800', '#ffc107', '#8bc34a', '#4caf50']
        ax2.pie(level_counts.values, labels=level_counts.index, autopct='%1.1f%%',
                colors=colors[:len(level_counts)], startangle=90)
        ax2.set_title('情绪等级分布')
        
        # 3. 月度热力图
        ax3 = axes[1, 0]
        df['year_month'] = pd.to_datetime(df[date_col]).dt.to_period('M')
        monthly_avg = df.groupby('year_month')['sentiment_score'].mean()
        
        # 绘制月度趋势
        monthly_avg.plot(kind='bar', ax=ax3, color='steelblue', alpha=0.8)
        ax3.axhline(y=50, color='gray', linestyle='--', alpha=0.5)
        ax3.set_ylabel('平均情绪分数')
        ax3.set_title('月度平均情绪')
        ax3.tick_params(axis='x', rotation=45)
        
        # 只显示部分x轴标签避免拥挤
        n_bars = len(monthly_avg)
        if n_bars > 12:
            step = n_bars // 12
            ax3.set_xticks(range(0, n_bars, step))
        
        # 4. 年度对比柱状图
        ax4 = axes[1, 1]
        df['year'] = pd.to_datetime(df[date_col]).dt.year
        yearly_stats = df.groupby('year')['sentiment_score'].agg(['mean', 'min', 'max'])
        
        x = range(len(yearly_stats))
        width = 0.25
        
        ax4.bar([i - width for i in x], yearly_stats['mean'], width, label='平均', alpha=0.8)
        ax4.bar(x, yearly_stats['min'], width, label='最低', alpha=0.8)
        ax4.bar([i + width for i in x], yearly_stats['max'], width, label='最高', alpha=0.8)
        
        ax4.set_ylabel('情绪分数')
        ax4.set_title('年度统计对比')
        ax4.set_xticks(x)
        ax4.set_xticklabels(yearly_stats.index)
        ax4.legend()
        ax4.set_ylim(0, 100)
        
        plt.tight_layout()
        
        chart_path = os.path.join(DATA_DIR, f'analysis_{datetime.now().strftime("%Y%m%d")}.png')
        plt.savefig(chart_path, dpi=150, bbox_inches='tight')
        print(f"\n图表已保存: {chart_path}")
        
        plt.show()


if __name__ == '__main__':
    analyzer = SentimentAnalyzer()
    analyzer.show_summary()
