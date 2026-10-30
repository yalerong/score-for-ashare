# A股情绪指标追踪器

A股市场情绪量化追踪系统，输出 0-100 连续分数作为市场冷暖与风险偏好的参考。当前模型为 **V2.1 / `2.1-lagged-margin`**：上涨放量加分、下跌放量减分，北向原始字段代理不再参与总分；两融统一使用前一交易日数据。

广度与横截面使用沪深个股数据；量价、波动与趋势使用上证指数作为代理。分数不是上涨概率，也不是固定的见底或买卖阈值。

## 核心设计

当前模型版本为 `2.1-lagged-margin`。情绪总分由 6 个维度加权合成，缺失组件自动降权，不使用随机值补满。以下是基础相对权重（合计 0.85），计算时按实际可用组件归一化。

| 维度 | 基础相对权重 | 数据源 | 说明 |
|------|------|--------|------|
| market_breadth | 0.25 | tushare `pro.daily` 沪深个股 | 上涨占比、涨跌中位数、涨跌广度强度 |
| cross_section | 0.15 | tushare `pro.daily` 与指数日线 | 涨停生态近似、强势池、科创50相对沪深300的风格差 |
| volume_change | 0.15 | tushare `pro.index_daily` | 量价确认：上涨放量加分，下跌放量减分 |
| volatility | 0.15 | tushare `pro.index_daily` | 20日实现波动率（反向） |
| margin_trading | 0.10 | tushare `pro.margin` (SSE+SZSE+BSE) | **前一交易日** 融资余额 `rzye` 的相邻交易日变化 / 融资余额 |
| trend | 0.05 | tushare `pro.index_daily` | 涨跌幅、20日动量、均线偏离 |

量价确认按以下规则计算，`P` 的范围是0-100：

```text
成交额比率 = 当日成交额 / 20日成交额中位数
量价强度 = abs(当日涨跌幅) × 成交额比率
P = 当前强度在最近365个自然日有效非零历史强度中的百分位
量价分 = 50 + sign(当日涨跌幅) × P / 2
```

平盘固定50；有效非零历史不足5条时中性处理；当前涨跌幅或成交额比率无效时，该组件不参与评分。相同历史下，涨时放量不降分、跌时放量不升分。经验百分位有台阶；方向规则作用于量价分项，总分还受其他维度影响。

`north_money` 的现行定义无法核验为日度净流入，已退出总分，输出字段保留为不可用，显示“不参与评分”。六项齐全时，归一化权重约为广度29.41%、横截面/量价/波动各17.65%、两融11.76%、趋势5.88%。

结果记录 `model_version`、`component_weights` 与 `effective_weights`。历史评估拒绝混用不同版本或手动/自动口径；使用新公式时须按同一版本重算研究区间，不能直接拼接旧分数。下方等级分界沿用原定义，尚未校准成上涨概率或反转阈值。

## 结果解释

| 分数区间 | 等级 | 含义 |
|----------|------|------|
| 0 ≤ 分数 ≤ 20 | 极度恐慌 | 情绪收缩，市场极度谨慎 |
| 20 < 分数 ≤ 40 | 偏谨慎 | 风险偏好较弱 |
| 40 < 分数 ≤ 60 | 中性 | 适合作为环境过滤参考 |
| 60 < 分数 ≤ 80 | 偏乐观 | 风险偏好在扩张 |
| 80 < 分数 ≤ 100 | 过热 | 追高冲动较高 |

**适合的用法**：判断市场风险偏好扩张/收缩期，作为仓位、节奏、风格的参考。
**不建议**：直接当买卖触发器，或单独依赖短线1-5日预测。

## 数据源与配置

标准运行入口通过 [Tushare Pro](https://tushare.pro) 获取数据，需要具备相应接口权限。Token 优先读取环境变量 `TUSHARE_TOKEN`，未设置时由 `python-dotenv` 从项目 `.env` 加载：

1. 环境变量 `TUSHARE_TOKEN`
2. 项目根目录的 `.env`：
   ```
   TUSHARE_TOKEN=your_token_here
   ```

也可设置 `SENTIMENT_TUSHARE_ENV` 指向额外的本地 `.env` 文件；它只补充尚未设置的变量，不覆盖前面已加载的值。不要提交 Token、邮箱授权码或公众号密钥。

日常运行和历史回填均采用截至目标交易日、包含当日的最近365个自然日作为校准窗口，指数指标额外加载预热数据。回填会同步保存横截面历史；结果写入失败时抛出异常，日报流程不会继续发送。

- 初次回填通过 `pro.daily(trade_date=...)` 逐交易日抓取股票快照，耗时取决于区间、网络和账号限额
- 手动录入也按涨跌方向处理成交，但使用绝对值映射，版本标记为 `2.1-lagged-margin-manual`，不与自动百分位分直接比较

## 取数口径校验

- 当前广度和横截面股票池仅保留 `.SH`、`.SZ`，不包含 `.BJ`；融资汇总包含沪、深、北交易所，北交所自2023-02-13起要求完整
- 单日快照请求未实现分页；返回行数达到 `pro.daily` 单次6000行上限时直接报错，避免静默使用截断数据
- 程序本地节流默认200次/分钟，可通过 `TUSHARE_RATE_LIMIT_PER_MIN` 调整；账号权限与实际接口限额可能更严格
- 邮件及公众号脚本读取已保存结果；只计算并保存、无需发送时使用 `python run_today.py`

### 收盘数据与发布延迟

`run_today.py` 使用接口最新可用指数日线的日期。若当日日线尚未发布，结果可能属于上一个交易日，应以结果的 `date` 字段为准，不能把执行时间当成行情日期。标准入口没有自动切换到新浪或腾讯指数报价的兜底流程。

融资数据在T+1早上才发布，因此T日评分的两融分项固定使用T-1（前一交易日）的融资变化，日常运行与历史回填口径一致，T日收盘时已全部可知。融资记录带有已知日期且不是前一交易日时不计入；前一交易日融资缺失时该组件降权，不再往前找更旧的数据。V2北向已经排除。

`coverage` 是**可用组件基础权重 / 当前模型基础权重总和**，不是股票覆盖率、置信度或上涨概率。六项齐全时为100%；缺融资组件时为 `0.75 / 0.85 ≈ 88.24%`，其他五项重新归一化。

`2.0-directional-volume` 在日常运行时拿不到当日融资（只有5项），回填时却用当日融资（6项），两类记录混在一起；升级到2.1后须按新版本重新回填研究区间，评估脚本会拒绝新旧版本混用。

## 快速开始

```bash
git clone https://github.com/yalerong/score-for-ashare.git
cd score-for-ashare
pip install -r requirements.txt
```

先参考 `.env.example` 创建本地 `.env` 并填写 Token，再计算最新可用交易日情绪：

```bash
python run_today.py
```

程序将结果写入 `data/sentiment_history.json`，广度与横截面缓存分别写入 `data/breadth_history.json`、`data/cross_section_history.json`。日常运行复用缓存中已完成的交易日，只补拉缺失日期和当天（当天快照可能仍在入库，不落盘）；缺失超过20个交易日（首次运行或长时间未运行）时整段拉取近2年。修改广度/横截面特征定义后，需删除这两个缓存或重新回填。需要检查模型、日期、分项和覆盖率时可直接调用：

```python
from sentiment_tracker import SentimentTracker

result = SentimentTracker().run()
print(result["model_version"], result["date"], result["sentiment_score"])
print(result["component_availability"], result["effective_weights"])
```

回填历史（约 3 年）：

```bash
python -c "from sentiment_tracker import SentimentTracker; SentimentTracker().backfill_history(days=1100)"
```

只重算指定日期范围（包含起止日，跳过非交易日）：

```bash
python -c "from sentiment_tracker import SentimentTracker; SentimentTracker().backfill_history(start_date='2026-09-01', end_date='2026-10-30')"
```

`days` 表示截至 `end_date`（默认今天）的自然日数量，仅更新请求范围内的评分。尚未发布指数日线的交易日不会生成分数；结果中的 `component_availability` 标明各分项是否可用，缺失分项不参与加权。

### 从旧版历史迁移

先将原 `data/sentiment_history.json` 备份到不重复的 `.bak` 文件名，再移开原文件，让回填生成一个仅包含目标研究区间的新历史文件。保留旧备份，不覆盖旧记录的唯一副本。也可在独立检出目录完成以上步骤；新检出的仓库同样带有旧历史文件，仍需先处理。

**只重算局部日期不会自动清除区间外旧版记录。** 评估脚本读取整个历史文件，发现未标版本的旧记录、V2自动记录或手动记录混在一起时会拒绝评估。完成单版本回填后再运行：

```bash
python market_sentiment_evaluator.py
```

评估输出 Rank IC 和未来5/10/20个交易日的分桶收益。同分样本不会按日期强行拆桶；唯一分数不足时可能少于五桶，常量信号不输出分桶。它是历史观察工具，不代表已经验证未来预测能力。

### 报告与手动入口

计算后同时尝试邮件与公众号草稿：

```bash
python daily_sentiment_report.py
```

只发送已保存结果的邮件：

```bash
python sentiment_email_sender.py
```

手动录入（网络受限时）：

```bash
python manual_input.py
```

## 邮件配置

支持以下环境变量。建议使用同一种方式提供完整配置：

| 环境变量 | 说明 |
|----------|------|
| `SENDER_EMAIL` | 发件人邮箱 |
| `SENDER_PASSWORD` | 邮箱授权码 |
| `RECEIVER_EMAILS` | 收件人（逗号分隔） |
| `SMTP_SERVER` | SMTP 服务器（默认 smtp.163.com） |
| `SMTP_PORT` | SMTP 端口（默认 465） |
| `SMTP_USE_SSL` | 是否 SSL（默认 true） |

当环境变量未提供 `SENDER_PASSWORD` 时，程序尝试加载 `data/email_config.local.json`；该文件的非空字段会覆盖同名环境配置。单独运行邮件脚本不会主动加载 `.env`，请预先设置环境变量或使用本地JSON；日报流程会先由取数模块加载 `.env`。

`daily_sentiment_report.py` 在结果日期不是今天、或当日广度/横截面不可用（个股日线尚未入库）时不发送并返回非0退出码；单独运行邮件或公众号脚本时，读取器在当天没有记录时仍会回退最近历史记录，发送前请核对报告所示的数据日期。不可用分项在报告中显示为 N/A。

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

脚本使用完整 Python 路径创建工作日任务，可选择15:35、16:00、17:00或自定义本机时间。需要确保主机开机，并根据A股时区设置合适的执行时间。当前脚本未配置失败自动重试；如需重试，应在系统任务计划程序中另行设置。

`start.py` 的网络诊断探测东方财富，不能代表Tushare接口可用；日常使用建议直接运行 `run_today.py`。

## 验证

```bash
python -m unittest discover -s tests -v
```

当前67项测试覆盖量价方向单调性、正负对称、平盘与退化历史、北向排除、版本混用拒绝、日常/历史评分一致、日期对齐、融资完整性、缓存重试、保存失败和分桶等。已有验证还包括6个修改模块的类型检查及Ruff运行时错误检查；它们不构成投资预测能力验证。

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
│   ├── breadth_history.json          # 广度历史缓存（本地生成，不提交）
│   └── cross_section_history.json    # 横截面历史缓存
└── tests/                        # 单元测试
```

## 已知边界

- 北向披露自2024-08调整，Tushare原始字段构造尚无法由现行说明核验；当前版本排除该代理项，不将其当作日度净流入
- 涨停判定统一使用 `pct_chg >= 9.5%` 近似，未逐股处理板块、ST及上市阶段规则，不承诺固定误差比例
- 风格字段使用科创50与沪深300涨跌幅之差，不是真正的微盘股指数
- 波动、量价和趋势存在信息重叠；量价规则改正方向后，总分仍可能受其他分项影响
- 历史评分使用取得的完整日度记录，融资等数据可能延后披露；未保存历史发布时刻的版本不能作为严格的当时可交易信号回测
- 分数映射混用百分位与有界线性，详见各模块方法文档
