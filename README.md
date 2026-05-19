# A股情绪指标追踪器

A股市场情绪量化追踪系统，输出 0-100 连续分数作为风险偏好参考框架。

## 核心设计

情绪总分由 7 个维度加权合成，缺失组件自动降权，不使用随机值补满。

| 维度 | 权重 | 数据源 | 说明 |
|------|------|--------|------|
| market_breadth | 0.25 | tushare `pro.daily` 全市场 | 全市场涨跌广度、涨停跌停数 |
| cross_section | 0.15 | tushare `pro.daily` (spot 阈值) | 涨停生态、强势池、风格差 |
| volume_change | 0.15 | tushare `pro.index_daily` | 成交额相对历史中位水平 |
| volatility | 0.15 | tushare `pro.index_daily` | 20日实现波动率（反向） |
| north_flow | 0.15 | tushare `pro.moneyflow_hsgt` | 北向资金相对成交额强弱 |
| margin_trading | 0.10 | tushare `pro.margin` (SSE+SZSE+BSE) | 两融净变化相对余额强弱 |
| trend | 0.05 | tushare `pro.index_daily` | 涨跌幅、20日动量、均线偏离 |

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

## 数据源与配置

全部数据通过 [tushare pro](https://tushare.pro) 接口获取。Token 加载顺序：

1. 环境变量 `TUSHARE_TOKEN`
2. 项目根目录的 `.env`：
   ```
   TUSHARE_TOKEN=your_token_here
   ```

实时与回测使用相同口径（per-stock 全市场 snapshot），不存在"实时维度 ≠ 历史维度"的不对齐问题。

- 历史回填走 `pro.daily(trade_date=...)` 逐日抓取，~3 年约 4 分钟（受默认限速 200/min）
- 手动录入模式已接入评分引擎，产出与主流程可比分数

## 取数口径校验

- tushare `pro.daily` 全市场快照覆盖所有 .SH/.SZ 个股；A 股活跃股本一般 5000+，单次返回够用，无需分页
- tushare 接口默认限速 200 次/分钟，可通过环境变量 `TUSHARE_RATE_LIMIT_PER_MIN` 调整
- 邮件发送脚本只读取已保存的评分结果生成内容；需要只验证不发送时，可直接运行 `SentimentTracker().run()` 并临时替换保存函数

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

## 微信公众号配置

个人订阅号可用于每天自动生成一篇短日报。默认行为是创建公众号草稿；如果账号接口权限允许，可通过开关继续尝试发布或群发。

| 环境变量 | 说明 |
|----------|------|
| `WECHAT_MP_APPID` | 公众号 AppID |
| `WECHAT_MP_SECRET` | 公众号 AppSecret，只放本地 `.env`，不要提交 |
| `WECHAT_MP_AUTHOR` | 作者名，默认 `持志堂` |
| `WECHAT_MP_THUMB_MEDIA_ID` | 已上传的永久封面素材 media_id，可选 |
| `WECHAT_MP_COVER_IMAGE` | 本地封面图路径，可选；未设置时会自动生成默认封面并上传 |
| `WECHAT_MP_CONTENT_SOURCE_URL` | 原文链接，可选 |
| `WECHAT_MP_AUTO_PUBLISH` | 是否创建草稿后调用发布接口，默认 `false` |
| `WECHAT_MP_AUTO_MASS_SEND` | 是否继续尝试群发接口，默认 `false` |

单独创建草稿：

```bash
python sentiment_wechat_mp_sender.py
```

## 定时任务

Windows Task Scheduler：

```bash
python setup_email_scheduler.py
```

已修复：定时任务使用完整 Python 路径（非 bare `python`），工作日 17:00 运行，失败自动重试 3 次。

## 文件结构

```
├── config.py                    # 全局配置、权重、阈值
├── data_fetcher_tushare.py      # 数据抓取（tushare pro API）
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

- 北向资金沪深港通日度数据 2024-08 起官方口径变化（看起来已从净流入变为 gross turnover）；保留 tushare 原始值参与百分位评分，相对排名仍有意义
- 涨停判定使用 spot `pct_chg >= 9.5%` 阈值近似，对创业板/科创板 20% 涨停存在低估（约 2-5% 误差）
- 分数映射混用百分位与有界线性，详见各模块方法文档
