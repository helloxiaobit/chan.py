# 虚拟货币完整版功能复核

日期：2026-10-20（Asia/Shanghai）

结论：核心框架已完成大量自研补齐，但尚不能判定为“虚拟货币完整版已完整验收”。主要缺口已经不是目录数量，而是行情时序、因果特征、模型部署、合约单位和运行编排。股票功能按用户本轮要求暂缓，不计入当前币圈版本的阻塞项。

配套开发计划：[虚拟货币完整版开发计划](../plans/2026-10-20-crypto-full-version-completion.md)。

## 1. 审计对象与证据边界

| 对象 | 本轮核实的身份 | 用途 |
|---|---|---|
| 上游 `Vespa314/chan.py main` | `429d6ed3043e27c93a003ba2b10e70a05575e1f5` | 公开 README 的功能说明、目录与接口基准 |
| 用户 GitHub `helloxiaobit/chan.py full-version` | `895fc700705e48013019a4054645e016a6e08d0e` | 用户链接实际交付版本 |
| 本地 `C:\chanpy\chan.py full-version` | `22a5a56ed1b38c2145106230c70256d4b7bc7bb5` | 本轮代码阅读和测试版本，领先远端 44 个提交 |
| 研究 worktree | `feature/v21-causal-futures` 等独立分支 | 不纳入通用完整版的已交付能力；本轮未执行研究命令 |

三个远端分支身份通过 `git ls-remote` 新鲜核验，本地身份通过 `git rev-parse HEAD` 核验；审计开始及测试后工作树均干净。GitHub commits 页面未能由网页工具展开，因此提交差异以远端 refs 和本地 Git 对象为依据，不把网页读取失败解释为仓库不存在。

上游明确说明公开仓库不包含部分策略、特征、模型、AutoML 和交易引擎实现，README 描述的是其完整版。本 fork 可验收的是对公开规格的独立实现；没有上游私有代码、测试集和完整特征公式，不能宣称与原作者私有实现逐项等价。来源：[上游 README](https://github.com/Vespa314/chan.py#readme)。

本轮仅做审计、短小离线诊断、已有测试和文档产出。未改业务代码、配置、规则、冻结规范；未运行正式回测、搜索、V29 preflight、全历史诊断或正式绩效读取；未连交易所下单。

## 2. 需求范围

当前目标是虚拟货币使用场景下的完整链路：

`行情采集 → 已收盘多级别缠论 → 策略/特征 → 样本/模型/评估 → 在线信号 → 风控/订单 → 恢复/对账/监控`

- 第一落地市场建议沿用现有研究方向：Binance USDT 线性永续；OKX USDT 线性永续作为第二适配目标。
- 保留现货功能，但现货、永续、不同交易所的数据和订单单位必须明确隔离。
- A 股、港股、美股、ETF、Futu、股票市值与复权维护暂缓。
- Notion、更多图床/通知后端属于可选集成，不作为币圈主链路完成条件。
- “功能完成”“某交易所测试网验收”“策略收益达标”“真实交易授权”是不同结论，分别出具证据。

## 3. 模块覆盖矩阵

“已实现”表示有实际逻辑；“部分实现”表示存在链路或语义缺口；“待外部验收”表示代码/离线测试不能证明真实服务兼容性。

| 功能 | 当前可确认能力 | 结论 / 待补边界 |
|---|---|---|
| 缠论核心与绘图 | 笔、段、中枢、bsp、多级别、静态/回放图形；保留上游结构 | 基础能力已实现，不修改段算法核心 |
| 完整版配置与扩展 | `CChanConfig` 扩展、方向/级别后缀、`extra_kl`、策略调度、`toJson` | 已实现；API 输出还缺版本化契约 |
| cbsp 策略框架 | `CStrategy`、Custom/Seg/多级别策略、开平仓、信号对象、模型过滤 | 框架已实现；在线信号与回测策略行为未形成完整等价验收 |
| 特征与标签 | `FeatureEngine`、注册表、离群点、500+ 特征测试、五种自定义标签 | 部分实现；父级别可用时间、标签缺失处理有缺口 |
| 模型训练 | XGB/LGBM/MLP、样本文件、训练/预测/持久化、AUC、条件分桶 | 已有可运行基础；跨币种时序切分和预测 schema 有错误 |
| 在线模型接入 | `CCommModel`、`CXGBModel` 可接入策略 | 部分实现；默认交易例行未接模型加载/前后验打分，LGBM/MLP 训练能力不等于已有默认在线适配 |
| 回测与 AutoML | 样本生成、策略交易统计、grid/bayes/PBT、参数导出、多周期函数 | 功能存在；通用评估不是永续资金账户核算，默认训练脚本也未串完全部环节 |
| CCXT 行情与离线库 | 分页、成交量、SQLite、增量、CSV、快照 | 部分实现；时间转换不一致、尾 K 修订丢失、缺少多交易所市场身份隔离 |
| 特征对账 | 单级别 load/trigger 特征比对、多级别最终结构一致性测试 | 已实现部分检查；不能据此证明不存在未来信息 |
| 交易引擎 | 本地版有持久化意图、累计成交、恢复、reduce-only、显式模式与 kill switch | 本地离线边界较完整；远端未包含这些后续修复；合约单位/交易所差异仍需处理 |
| 数据库 | SQLite 实际生命周期；MySQL SQL 适配与 schema | SQLite 已测；MySQL 真实连接、旧表迁移/事务能力未验收 |
| 交易调度 | SignalMonitor、MakeOpenTrade、CheckOpenScore、RealTimeTracker、恢复相关脚本 | 部分实现；默认脚本硬编码标的且未在前序失败时阻断后续交易 |
| 周边功能 | 通知、图床接口、试题、GUI 保留 | 存在实现；外部服务未实际验证，股票相关暂缓 |

没有把文件名差异直接算作功能缺失。例如上游目录称 `SinaSnapshot.py`，本项目通过 `SinaAPI.py` 和注册器提供对应入口。

## 4. 已确认的关键问题

### G01 / P0：公开分支与本地安全能力不一致

远端 `895fc70` 的 `Trade/CCXTTradeEngine.py` 仍按是否存在 API key 推导 dry-run；`Trade/TradeEngine.py` 的开仓落库使用 `order.filled or quota`，零成交会被当成整笔数量。其订单重试/恢复也不是本地后续持久化状态机。

本地 44 个提交中包含 `SafetyPolicy.py`、成交状态机、重启恢复和测试，不能把这些算作 GitHub 已发布功能。先决定并冻结正式交付分支，做有范围的集成/发布，不能机械把研究分支全部合并。

### G02 / P0：在线/离线同一根 K 线时间不一致

- `DataAPI/ccxt.py:114`：直接将交易所开盘时间构造成 `CTime`。
- `DataAPI/OfflineDataAPI.py:37`：对日内 K 线加上周期，转换为结束时间。
- `Chan.py:284` 附近的多级别调度按结束时间建立父子关系。

本轮同一根 UTC 2024-01-01 00:00 的 1h OHLCV，在线时间为 00:00、离线时间为 01:00，相差 **3600 秒**。这会改变多级别对齐和决策时间。

### G03 / P0：增量更新不能修订已经落库的最新 K 线

`OfflineData/ccxt_update.py:43` 起以 `last_ts + 1` 开始下一轮抓取，当前返回数据直接入库，没有已收盘过滤或尾部重取。

本轮 FakeExchange + SQLite 内存库复现：第一次 close=100 入库；同一个 open_ms 的最终 close 改为 105；第二次请求跳过该 open_ms，库内仍为 **100**。

CCXT 文档明确指出当前最后一根 K 线在收盘前可能不完整，这不是可以忽略的输入假设。来源：[CCXT Manual，OHLCV](https://raw.githubusercontent.com/ccxt/ccxt/master/wiki/Manual.md)。

同时，`OfflineData/offline_data_util.py:54` 的唯一键只有 `(symbol, lv, ts)`。同一库混用不同交易所或不同市场类型时，没有来源身份可供隔离和核验。

### G04 / P0：父级别未收盘信息进入子级别特征

`Chan.py:306` 先放入完整父 K 线再递归处理子 K 线；`ChanModel/FeatureEngine.py:431` 直接读取 `sup_kl.close > sup_kl.open`，没有判断父 K 线在子级别决策时是否已经收盘。

本轮用真实 `CChan.trigger_load` 配合观察策略，在 UTC 01:00 子 K 线和其历史不变时，仅将 UTC 04:00 才结束的父 K close 从 120 改成 80；子级别 `sup_lv_klu_is_up` 从 **true 变为 false**。

这是明确的可用时间漏洞。修复应在数据发布/特征访问边界限制可读信息，保留结构回放能力；不需要重写段算法。一次性 load 与逐根 trigger 如果都先注入完整父 K，即使结果相等，也不能排除共同使用未来信息。

### G05 / P0：训练/预测数据契约不可靠

1. `ModelStrategy/backtest.py` 按 `code_list` 逐币拼接样本；`ModelStrategy/ModelGenerator.py:215` 直接按数组比例切分。
   - 本轮两币各四个月、切分比 0.5：训练最晚时间 **2024-04-01**，测试最早时间 **2024-01-01**。
   - 单币顺序成立不能推出跨币种全局时间顺序成立；还缺标签观察区间与验证窗口重叠的隔离。
2. `PredictProcess` / `predictAllProcess` 使用输入样本目录的 meta，没有强制重排到模型训练时保存的 meta。
   - 本轮训练顺序 `[a,b]`、输入顺序 `[b,a]`，正确向量 `[10,20]` 实际成为 **[20,10]**。
   - `CXGBModel.predict(cbsp)` 按名称映射的路径较好，但不能替代上述两个批量预测入口的修复。
3. `ModelStrategy/backtest.py:134` 将缺失主标签默认为 0；对于未来窗口尚未完整的尾部样本，缺标签不能默认为负例。

### G06 / P1：默认在线例行尚未接通模型闭环

- `Trade/Script/StaticsChanConfig.py` 默认配置没有从部署产物加载模型。
- CustomStrategy / MultiLevelStrategy 生成 `CSignal` 时未设置 score；该字段默认 None。
- `MakeOpenTrade` 检查已有 `model_score_before`，没有重建突破时的特征和打分。
- `CheckOpenScore.py:55` 只有显式注入 `score_func` 才进行复查；默认命令入口未注入。
- `get_last_closed_kline_close` 只取库内最后一行，未验证其收盘时间和订单应对应的后验周期。
- 默认 `RealTimeTracker` 覆盖价格止损/止盈/峰值回撤，但没有把回测中的全部结构性退出作为统一事件接入。

结果：模型类可单独运行，不代表“训练产物 → 在线开仓评分 → 后验评分 → 策略退出”已经打通。

### G07 / P1：合约数量与交易所能力不能泛化

`Trade/OpenQuotaGen.py:25` 按 `bench_price / price` 得出币数量；`Trade/CCXTTradeEngine.py` 将其精度化后直接交给下单接口，未读取 `contractSize` 做明确的币数/张数转换。

代码对合约统一传 `positionSide`、`reduceOnly`、`postOnly`，没有逐交易所的能力和参数映射；按客户端编号恢复只遍历一次 `fetch_orders(code)`，缺少明确的历史分页/时间窗口约束。

CCXT 明确区分合约张数与标的币数量，线性合约需要结合 contractSize 换算。来源：[CCXT Manual，createOrder / contractSize](https://raw.githubusercontent.com/ccxt/ccxt/master/wiki/Manual.md)。

现有 fake exchange 验证了状态机部分语义，未证明 Binance/OKX 真实适配。计划应先补纯离线契约测试，再在单独授权且满足原门禁后做测试网验收。

### G08 / P1：默认调度和训练流水线未形成可验收闭环

- `Trade/Script/update_data_signal.ps1` / `.sh` 硬编码 BTC/ETH 与三个周期，未完全使用运行配置。
- PS1 没有逐命令判断 `$LASTEXITCODE`；SH 没有失败退出控制。数据更新失败后仍可能继续计算信号/开仓。
- `run_train_pipeline.ps1` 目前只生成样本并调用三种模型训练；未串联稳定性验证、AutoML、模型部署清单、线上配置与特征对账。
- 没有统一的运行记录、单实例锁、行情新鲜度门禁、阶段恢复点和“失败不生成可部署结果”的契约。

注意：禁止新开仓与继续管理已有仓位应分别处理；不能通过“任何失败一律退出全部例行”使已有止损/撤单失去管理。

### G09 / P1：评估口径与证明范围不足

- `parameterEvaluate/eval_strategy.py:95` 累加逐笔百分比收益；回撤按平仓收益累加曲线计算。它是交易统计器，不是手续费/滑点/资金费/保证金/逐时盯市齐全的永续账户回放。
- 仓库另有 portfolio/research 能力；不能认为默认 AutoML/模型路径已经自动使用这些核算器，应明确复用与路由。
- `FeatureReconciliation` 目前只支持单个 lv、按列表 zip 比较特征；未严格按决策身份对齐，也未覆盖全部在线开平仓事件。
- `toJson` 输出基本 klu/bi/seg/zs/bsp/cbsp，尚未输出 segseg/segzs/线段 bsp 等全部内部结构，也缺少版本、时间语义与有限 JSON 契约。
- README_FULL 的“全部对齐”“一致性保证无未来函数”表述超出当前证据，需要在实现验收后按支持矩阵更新。

## 5. 已有测试与本轮复现证据

运行环境：Windows，CPython 3.14.2。

执行：

```powershell
python -m pytest tests/test_env_config.py tests/test_consistency.py tests/test_m1_cbsp.py tests/test_m2_features.py tests/test_m3_model.py tests/test_m4_eval.py tests/test_m5_data.py tests/test_m6_trade.py tests/test_m7_final.py tests/test_regression.py tests/test_ctime_timezone.py tests/test_trade_safety.py tests/test_trade_state_machine.py -m "not network" -q -ra
```

结果：**116 passed, 1 skipped, 1 deselected, 1 warning，52.75 秒，退出码 0**。

- 跳过：股票 GUI 的 PyQt6 缺失，符合本轮股票暂缓范围。
- 排除：真实 CCXT 联网数据测试。
- 警告：XGBoost 文本格式输入弃用提示。
- 进程退出时另有 pytest 临时目录 `pytest-current` 清理 `WinError 5`，不能称为完全无告警退出；它没有改变测试退出码，也不证明业务缺陷。
- 本次是明确列出的功能回归集合，不是整个仓库全量回归，也不是跨交易所验收。

额外执行五个不联网诊断，未修改业务源码：

| 诊断 | 输入 | 实测结果 |
|---|---|---|
| 在线/离线时间 | 同一 UTC 1h OHLCV | 相差 3600 秒 |
| 尾 K 修订 | 相同 open_ms，close 100→105 | 库内仍 100 |
| 多币种切分 | BTC/ETH 各 1–4 月、比例 0.5 | train_max=4月，test_min=1月 |
| 父级别未来信息 | 同一 01:00 子 K，04:00 父 K close 120→80 | 父级方向特征 true→false |
| 预测列序 | 训练 `[a,b]`，输入 `[b,a]` | 实际 `[20,10]`，期望 `[10,20]` |

前两项使用真实 reader / update 函数和 SQLite 内存库；父级别项使用真实 CChan 调度与最小观察策略；模型列序项隔离模型算法，仅验证批量预测的公共特征路由。它们证明边界存在错误，不代表已经测出策略收益影响。

## 6. 暂缓项与本轮交付

暂缓：A/H/US/ETF 数据适配、股票统计缓存 `OfflineData/stockInfo/`、Futu 历史数据/交易认证、股票 GUI 操作验收、股票复权及交易日历。其现有覆盖不足继续留档，不伪装为已完整实现。

可选：Notion 同步（当前未找到 `Script/Notion/DB_sync_Notion.py`）、MySQL 实例认证、更多通知/图床服务、面向股票的试题扩展。可视化核心和现有 SQLite 不受此暂缓影响。

本轮只新增本报告与配套开发计划；未简化或修改运行时代码，未提交或推送 Git。下一步建议从数据时间与因果特征边界开始，按计划先补能稳定失败的测试，再最小实现修复。
