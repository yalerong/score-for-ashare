# A股情绪指标追踪器

A股市场情绪量化追踪系统，输出 0-100 连续分数作为风险偏好参考框架。

## 核心设计

情绪总分由 7 个维度加权合成，缺失组件自动降权，不使用随机值补满。

| 维度 | 权重 | 数据源 | 说明 |
|------|------|--------|------|
| market_breadth | 0.25 | Eastmoney / Sina / 指数代理 | 全市场涨跌广度、涨停跌停数 |
| cross_section | 0.15 | akshare 涨停池 | 涨停生态、强势池、风格差 |
| volume_change | 0.15 | 指数K线 | 成交额相对历史中位水平 |
| volatility | 0.15 | 指数K线 | 20日实现波动率（反向） |
| north_flow | 0.15 | Eastmoney / akshare | 北向资金相对成交额强弱 |
| margin_trading | 0.10 | SSE + SZSE | 两融净变化相对余额强弱 |
| trend | 0.05 | 指数K线 | 涨跌幅、20日动量、均线偏离 |

## 结果解释

| 分数区间 | 等级 | 含义 |
|----------|------|------|
| 0-20 | 极度恐慌 | 情绪收缩，市场极度谨慎 |
| 20-40 | 偏谨慎 | 风险偏好较弱 |
| 40-60 | 中性 | 适合作为环境过滤参考 |
| 60-80 | 偏乐观 | 风险偏好在扩张 |
| 80-100 | 过热 | 追高冲动较高 |

**适合的用法**：判断市场风险偏好扩张/收缩期，作为仓位、节奏、风格的参考。
**不建议**：直接当买卖触发器，或单独依赖短线1-5日预测。

## 数据源与容错

三级 fallback 确保数据可用性：

```
Eastmoney 全市场 → Sina 全市场 (5511只) → 6指数代理 → 标记缺失
```

- 实时运行时若任何组件为 mock 数据，**拒绝保存到历史库**，防止污染回测
- 离线模式禁止历史回填（`backfill_history` 会直接抛异常）
- 手动录入模式已接入评分引擎，产出与主流程可比分数

## 快速开始

```bash
pip install -r requirements.txt
```

计算当日情绪：

```bash
python run_today.py
```

回填历史（约 3 年）：

```bash
python -c "from sentiment_tracker import SentimentTracker; SentimentTracker().backfill_history(days=1100)"
```

历史有效性评估：

```bash
python market_sentiment_evaluator.py
```

发送邮件报告：

```bash
python sentiment_email_sender.py
```

手动录入（网络受限时）：

```bash
python manual_input.py
```

## 邮件配置

优先读取环境变量，其次读取 `data/email_config.local.json`：

| 环境变量 | 说明 |
|----------|------|
| `SENDER_EMAIL` | 发件人邮箱 |
| `SENDER_PASSWORD` | 邮箱授权码 |
| `RECEIVER_EMAILS` | 收件人（逗号分隔） |
| `SMTP_SERVER` | SMTP 服务器（默认 smtp.163.com） |
| `SMTP_PORT` | SMTP 端口（默认 465） |
| `SMTP_USE_SSL` | 是否 SSL（默认 true） |

## 定时任务

Windows Task Scheduler：

```bash
python setup_email_scheduler.py
```

已修复：定时任务使用完整 Python 路径（非 bare `python`），工作日 17:00 运行，失败自动重试 3 次。

## 文件结构

```
├── config.py                    # 全局配置、权重、阈值
├── data_fetcher_v2.py           # 数据抓取（Eastmoney / Sina / akshare）
├── sentiment_scoring.py         # 核心评分算法（百分位/线性/组合）
├── sentiment_tracker.py         # 主流程编排、历史回填
├── market_sentiment_evaluator.py # 回测：Rank IC + 分桶收益
├── sentiment_email_sender.py     # 邮件模板与发送
├── sentiment_analyzer.py         # 历史数据可视化与报告
├── manual_input.py               # 手动录入（已接入评分引擎）
├── start.py / run_today.py       # 入口脚本
├── setup_scheduler.py            # 系统定时任务配置
├── setup_email_scheduler.py      # 邮件定时任务配置
├── daily_sentiment_report.py     # 每日报告（计算+邮件）
├── network_config.py             # 网络/代理配置
├── requirements.txt              # Python 依赖
├── data/                         # 历史数据与缓存
│   ├── sentiment_history.json        # 情绪历史库
│   └── cross_section_history.json    # 横截面历史缓存
└── tests/                        # 单元测试
```

## 已知边界

- 横截面历史缓存日级积累中，回测期 cross_section 无历史数据（实时为 7 维，回测为 6 维）
- 历史两融仅 SSE 口径（实时为 SSE+SZSE 合并）
- 分数映射混用百分位与有界线性，详见各模块方法文档
- Eastmoney clist API 偶发限流，自动 fallback 到 Sina 全市场数据
