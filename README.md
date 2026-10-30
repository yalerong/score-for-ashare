# A股情绪指标追踪器

A股市场情绪量化追踪系统，输出 0-100 连续分数作为风险偏好参考框架。

## 核心设计

当前模型版本为 `2.0-directional-volume`。情绪总分由 6 个维度加权合成，缺失组件自动降权，不使用随机值补满。以下是基础相对权重（合计 0.85），计算时按实际可用组件归一化。

| 维度 | 权重 | 数据源 | 说明 |
|------|------|--------|------|
| market_breadth | 0.25 | tushare `pro.daily` 全市场 | 全市场涨跌广度、涨停跌停数 |
| cross_section | 0.15 | tushare `pro.daily` (spot 阈值) | 涨停生态、强势池、风格差 |
| volume_change | 0.15 | tushare `pro.index_daily` | 量价确认：上涨放量加分，下跌放量减分 |
| volatility | 0.15 | tushare `pro.index_daily` | 20日实现波动率（反向） |
| margin_trading | 0.10 | tushare `pro.margin` (SSE+SZSE+BSE) | 两融净变化相对余额强弱 |
| trend | 0.05 | tushare `pro.index_daily` | 涨跌幅、20日动量、均线偏离 |

量价确认强度为 `abs(当日涨跌幅) × (成交额 / 20日成交额中位数)`，在目标日最近365个自然日的有效非零强度中计算百分位 `P`，量价分为 `50 + sign(涨跌幅) × P / 2`。平盘固定50；有效非零历史不足5条时中性处理。相同历史下，涨时放量不降分、跌时放量不升分；经验百分位有台阶，不保证每次总分都随指数同向变动。

`north_money` 的现行定义无法核验为日度净流入，已退出总分，输出字段保留为不可用，显示“不参与评分”。六项齐全时，归一化权重约为广度29.41%、横截面/量价/波动各17.65%、两融11.76%、趋势5.88%。

结果记录 `model_version`、`component_weights` 与 `effective_weights`。历史评估拒绝混用不同版本或手动/自动口径；使用新公式时须按同一版本重算研究区间，不能直接拼接旧分数。下方等级分界沿用原定义，尚未校准成上涨概率或反转阈值。

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

实时和历史评分均使用截至目标交易日、包含当日的最近 365 个自然日作为校准窗口，指数指标额外加载预热数据。回填会同步保存横截面历史；结果写入失败时会抛出异常，阻止日报继续发送。

- 历史回填走 `pro.daily(trade_date=...)` 逐日抓取，~3 年约 4 分钟（受默认限速 200/min）
- 手动录入也按涨跌方向处理成交，但使用绝对值映射，版本标记为 `2.0-directional-volume-manual`，不与自动百分位分直接比较

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

只重算指定日期范围（包含起止日，跳过非交易日）：

```bash
python -c "from sentiment_tracker import SentimentTracker; SentimentTracker().backfill_history(start_date='2026-09-01', end_date='2026-10-30')"
```

`days` 表示截至 `end_date`（默认今天）的自然日数量，仅更新请求范围内的评分。尚未发布日线的交易日不会生成分数；结果中的 `component_availability` 标明各分项是否可用，缺失分项不参与加权。

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

- 北向披露自2024-08调整，Tushare原始字段构造尚无法由现行说明核验；当前版本排除该代理项，不将其当作日度净流入
- 涨停判定使用 spot `pct_chg >= 9.5%` 阈值近似，对创业板/科创板 20% 涨停存在低估（约 2-5% 误差）
- 分数映射混用百分位与有界线性，详见各模块方法文档
