# chan.py 完整版使用文档

本仓库 fork 自 [Vespa314/chan.py](https://github.com/Vespa314/chan.py)(MIT)。原开源版主要提供静态缠论计算，`README.md` 描述作者私有完整版。本 fork 已独立实现 cbsp、特征、模型、AutoML、数据和交易模块；虚拟货币完整链路仍在按 [C0–C7 计划](docs/superpowers/plans/2026-10-20-crypto-full-version-completion.md) 开发验收。当前支持范围与证据见 [验收台账](docs/superpowers/reports/2026-10-20-crypto-full-version-progress.md)，股票功能暂缓。

- 原版 `README.md`:上游功能与接口说明；不表示本 fork 已与私有实现逐项等价
- `quick_guide.md`:缠论计算部分的快速入门
- 本文档:完整版的安装、配置与实战流程(以加密货币为主场景)

## 安装

```bash
pip install -r Script/requirements.txt        # 核心缠论计算(最小依赖)
pip install -r Script/requirements_full.txt   # 完整版(策略/模型/ccxt/automl)
```

可选依赖按需安装:`akshare`(A股)、`pymysql`(mysql 后端)、`futu-api`(futu 引擎)、`pytdx`、`minio`/`cos-python-sdk-v5`(图床)。所有重依赖均为懒加载,不装不影响其他功能。

## 配置

```bash
cp Config/config_demo.yaml Config/config.yaml   # 已 gitignore,密钥只进这里
```

关键配置段:

| 段 | 说明 |
|---|---|
| `db` | 交易库(sqlite 默认 / mysql) |
| `offline_data` | 离线K线落地目录与 sqlite 路径 |
| `snapshot_engine` | 实时快照引擎:`ccxt`/`sina`/`pytdx`/`ak`/`futu` |
| `ccxt` | 交易所/密钥/代理/testnet(**行情永远走生产环境,testnet 只影响交易**) |
| `notify` | 推送:telegram/dingtalk/wecom/email/gotify |
| `trade` | 监控标的池/信号级别/单笔名义金额 |
| `model` | 模型文件目录 |

## 加密货币快速上手

### 1. 落地历史K线(增量,可重复跑)

```bash
python -m OfflineData.ccxt_update BTC/USDT K_60M K_DAY
```

首次从指定起点获取历史，之后重取最后一根再续传；仅保存已收盘 K 线，修订会幂等覆盖。在线/离线 crypto reader 统一输出 UTC 收盘边界；日、周、月使用各自真实周期，`close_ms == available_at_ms`。ticker 快照标记 `is_final=False`，确认计算拒绝接收。

每个行情 SQLite 库绑定一个交易所/市场类型/结算币/价格类型；symbol 和 timeframe 继续在行级隔离。现货与永续、Binance 与 OKX、contract 与 mark 使用独立库。未声明来源的旧库不会自动贴上当前配置的标签。

旧库迁移前先停止所有写入器，并核实实际来源；以下是现货库示例，不能用于来源不明或冻结研究 DB：

```python
from OfflineData.offline_data_util import migrate_legacy_source
migrate_legacy_source(
    "OfflineData/data/kline.db",
    {"exchange": "binance", "market_type": "spot", "settle": "", "price_type": "contract"},
    "OfflineData/data/kline.before-crypto-c1.db",
)
```

该入口拒绝覆盖备份，保留全部原表，逐行比较备份与原库后才绑定来源；发现错误需更换独立库，不能改写已有来源。`CKLineDB.inspect_quality(..., now_ms=...)` 会返回 `ready/no_data/stale/gap/inactive/unknown_source` 等状态，C6 将把该结果接入开新仓门禁。

已有本地 csv 历史数据可先明确来源再灌库：

```python
from OfflineData.offline_data_util import CKLineDB, import_csv
from Common.CEnum import KL_TYPE
with CKLineDB() as db:
    db.bind_source({"exchange": "binance", "market_type": "spot", "settle": "", "price_type": "contract"})
    import_csv(db, "BTC/USDT", KL_TYPE.K_60M, r"C:\chanpy\data\btc\btc_1h.csv")
```

直接 CSV 回退还需在 `offline_data.source_identity` 显式声明同一来源。文件名保留 `BTC_USDT_60m.csv`；永续 `BTC/USDT:USDT` 使用 Windows 可用的 `BTC_USDT_USDT_60m.csv`。合约更新需使用交易所的统一合约 symbol 和匹配的 `ccxt.default_type`，不把现货 symbol 重新标成合约。

### 2. 离线数据跑缠论 + cbsp 策略

```python
from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, KL_TYPE
from CustomBuySellPoint.CustomStrategy import CCustomStrategy
from Plot.PlotDriver import CPlotDriver

config = CChanConfig({
    "divergence_rate": float("inf"),
    "min_zs_cnt": 0,
    "cbsp_strategy": CCustomStrategy,          # 开启 cbsp 策略
    "strategy_para": {"short_shelling": True},  # 支持做空
})
chan = CChan(
    code="BTC/USDT",
    begin_time="2024-01-01",
    data_src="custom:OfflineDataAPI.CStockFileReader",  # 读本地 sqlite,不走网络
    lv_list=[KL_TYPE.K_60M],
    config=config,
    autype=AUTYPE.NONE,
)
for cbsp in chan[0].cbsp_strategy:   # 全部自定义买卖点(含开平仓与收益)
    print(cbsp)
CPlotDriver(chan, plot_config={"plot_kline": True, "plot_bi": True, "plot_seg": True,
                               "plot_zs": True, "plot_bsp": True, "plot_cbsp": True},
            plot_para={"cbsp": {"plot_cover": True, "show_profit": True}}).save2img("btc.png")
```

### 3. 回测出样本 → 训练模型 → AutoML

```bash
python -m ModelStrategy.training_pipeline --spec path/to/training-spec.json
# 同一入口的脚本包装，必须显式给 spec：
bash Trade/Script/run_train_pipeline.sh path/to/training-spec.json
pwsh -File Trade/Script/run_train_pipeline.ps1 path/to/training-spec.json
```

该有界入口不读取默认行情目录、不下载数据、不复用旧模型。spec 使用
`chan-crypto-training-cli-v1`，明确给 `data_packet`、`output_dir`、`configuration`
和 `training`；文件路径相对 spec 目录解析。数据包用 `CCryptoEvaluationData.to_dict()`
导出，configuration 用 `CCryptoEvaluationConfig.to_dict()` 导出；reader 重验来源、周期、
OHLCV、mark 和 exact-ms funding 日程，不凭文件名猜市场。

Python API 为 `ModelStrategy.training_pipeline.run_crypto_training_pipeline(data, config, ...)`。
`training` 与 API 关键字相同，必须预先固定：

- `training_window`、`search_window`、`validation_windows`：升序不重叠的 UTC 毫秒半开窗口。
- `primary_label`、`label_parameters`、`model_type`（xgb/lgbm/mlp）、`model_options`：实际样本标签与训练超参。
- `thresholds={candidate, entry, post}`：显式概率阈值；只有 entry 可在事先声明的搜索空间内调整。
- `space`、`objective`、`n_trials`、`algorithm`、`seed`：本次固定搜索规格；可另给 `min_closed_positions` 和 `algorithm_parameters`。

训练后搜索只允许实际生效的 `entry_notional`、`score_thred`，不能换策略/特征参数后继续使用旧模型。
原始无模型策略的参数搜索仍通过下面独立的 account_experiment 接口完成。
先生成训练窗口内的真实样本、训练所选模型，再在后续窗口搜索与验证。
模型、feature.meta、样本、来源、策略配置、评估器和部署三个阈值绑定同一运行。
验证、导出重读和全部 trial 的逐事件重放完成后，才把本运行独有 staging 目录发布到显式新目录；
训练失败、验证失败或目标已存在时不留下新部署包、不覆盖旧产物。

输出包含 `samples/`、`model/`、`experiment/`、`deployment.json` 和最终 `receipt.json`。
`verify_crypto_training_pipeline(output_dir, data)` 从实际数据重放核验，目录移动后仍可验证，
不依赖已删除的 staging 绝对路径。状态为 `offline_training_and_window_checks_passed`，
始终 `candidate_authorized=false`；不是测试网、实盘或策略经济采用授权。
PS1/SH 共用一个 Python 调用并传递非零退出码；完整调度、单实例锁、安装矩阵和跨环境验收仍在 C6。
正式参数搜索继续受独立研究门禁约束，不能将本软件入口作为绕过入口。

低级接口继续兼容，用于单独检查样本、模型和逐笔统计；不能替代上述完整流水线收据：

```python
# 1) 回测落样本(libsvm + feature.meta + 五种标签,兼容 demo5 格式)
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
res = run_backtest(CBacktestConfig(code_list=["BTC/USDT"], data_src="custom:OfflineDataAPI.CStockFileReader",
                                   lv_list=[KL_TYPE.K_60M], chan_config={...}, output_dir="./bt_out",
                                   primary_label="label_ret_N"))

# 2) 训练(XGB/LGBM/MLP 三选一,自动打印 AUC)
from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
gen = CXGBTrainModelGenerator(model_tag="btc", is_buy=True)
gen.trainProcess("./bt_out")

# 3) 模型接入实时打分(score_thred 过滤低分 cbsp)
from ChanModel.XGBModel import CXGBModel
config = CChanConfig({"cbsp_strategy": CCustomStrategy,
                      "model": CXGBModel(gen.GetModelPath()), "score_thred": 0.6})

# 4) 逐笔统计与参数搜索；搜索结果只是独立建议，不覆盖活动配置
from ModelStrategy.parameterEvaluate.eval_strategy import CEvalConfig, eval_strategy
from ModelStrategy.parameterEvaluate.para_automl import CParaAutoML
from ModelStrategy.parameterEvaluate.parse_automl_result import parse_automl_result
```

`CParaAutoML.run(n_trials=...)` 对 grid、bayes 和种群参数扰动均强制正整数上限；grid 实际组合更少时提前结束。grid_num 至少 2，整数轴去重并包含完整网格的两端；大轴不会在小预算下整条分配。每次运行重置随机种子与 trial 状态。`pbt` 只是 `population-perturbation` 的兼容名称，没有模型 checkpoint 继承。

搜索 JSONL 是有限 canonical、write-once，记录空间、算法、seed、预算和代码身份；无有效分数不发布。NaN/Infinity trial 拒绝且保留原因，reader 再核验预算/参数/状态/身份。`parse_automl_result(result_path, output_path)` 必须显式指定**新建议文件**，不再默认写 `Trade/Script/OpenConfig.yaml`，现有文件拒绝覆盖；输出状态为 `unvalidated_parameter_proposal`，不是 candidate 或交易授权。旧 `automl_verify` 闭包无法证明数据窗口隔离，现明确返回 `window_isolation_verified=False`；需要真实数据窗口证明时用下述 account_experiment 或训练入口。

`eval_strategy` 的总收益是逐笔百分比之和，回撤是这条加法曲线的百分点回撤，不是组合净值/最大权益回撤。兼容数值属性保留，JSON 增加单位；无亏损时的盈亏比以 null 与显式 infinite 标志输出，不写 JSON Infinity。正式策略研究及参数搜索继续保留独立门禁。

`ModelStrategy.parameterEvaluate.crypto_account` 提供单独的 USDT 账户事件入口：`evaluate_crypto_account(events, config, start_ms=..., end_ms=...)`。事件为显式 `open/close/mark/funding`；时间用 UTC 毫秒，quantity 是**币数而不是合约张数**，成交 lot 的 `position_id` 不重复。现货只允许自有现金做多；USDT 线性永续支持 long/short、多 lot 和部分退出。追加成交使用新 lot；同毫秒的多次退出必须给不同且递增的 `sequence`，不能只换 id 重复扣减。

`CCryptoAccountConfig` 显式设初始资金、杠杆、maker/taker 手续费、不利 taker 滑点和软件维持保证金阈值。账户区分 USDT 现金、已实现损益、费用、资金费、未实现损益、总/净敞口及保证金；spot 买入占现金、swap 本金不重复扣款。mark/funding 价格是单独事件，不冒用合约收盘价。每个 symbol/时刻 funding 仅结算一次，收取对象为此前已经持有的剩余币数；同刻软件顺序为 mark→旧仓 funding→旧仓退出→新仓入场→该新 lot 即时退出。

报告保留每条输入、实际执行价、现金/费用/损益增量、完整余额快照、有限字符串 Decimal 指标以及 evaluator/事件/报告 SHA。`verify_crypto_account_report(report)` 从事件重放核对全部内容；它是实现内自校验，不是第二套独立经济公式。未平仓不强制平仓；极短窗口不可表示的年化明确为 null。费后保证金不足拒绝新风险；维持保证金触发仅标记 `liquidation_required`，没有真实成交证据时绝不虚构强平价或抹除亏损，真实减仓仍能记账。该 cross 保证金口径不是 Binance/OKX 强平认证，精确单位转换/交易所参数仍待 C5；行情新鲜度与完整调度门禁待 C6。

旧 `portfolio_eval` 继续保留历史平仓近似接口和回归，不再称“唯一合法记分牌”，也不改变冻结研究的原有核算或证据。

`crypto_evaluate.CCryptoEvaluationData` 将明确来源的 contract/mark OHLCV 和独立声明的 exact-ms funding 日程绑定成不可变数据包；不读取默认环境、不下载数据、不接触冻结研究。`evaluate_crypto_strategy(data, config, start_ms=..., end_ms=...)` 在真实 CCustomStrategy/CMultiLevelStrategy 上逐收盘喂入，保留结构预热，评估开始前不接受交易级别持仓。执行口径冻结为 **confirmed-decision-next-real-base-open-v1**：只能以确认时刻的下一真实 base open 作为成交参考，taker 费率与不利滑点，不能倒填决策 K 内的有利成交价；输入缺口、next open 或资金费缺失均拒绝，不用别的行替代。它不是线上限价单撮合等价证明。

配置显式指定固定每 lot USDT 名义和账户口径。报告记录真实不可变策略决策、逐事件账户和数据窗口/来源/count/SHA/配置/执行器代码。模型可选；若使用，必须验证 artifact、训练标签已知时间、原始训练前缀 count/SHA、策略/特征配置、币种/级别和来源完全匹配。不能把模型从 Binance 换贴 OKX，也不能换训练数据后只保留同一个文件名。窗口末尾未完成 K 的 high/low/close 不进入结构或输入证据，已观察到的 open 只用于执行；三级未来父 K 变异测试覆盖这一边界。

`account_experiment.run_account_experiment(...)` 进一步要求预先指定 `search_window`、升序且不重叠的 `validation_windows`、`space`、`objective`（total_return/cagr/calmar）、`n_trials`、算法、seed 和新 `output_dir`。允许搜索的实际生效参数当前为 entry_notional、max_sl_rate、max_profit_rate 和有模型时的 score_thred；不能搜索未使用的任意键，也不能修改策略上下文后沿用旧模型。目标按固定 Decimal 账户指标转换为有限 float 排序，至少一笔完整持仓，曾触发 liquidation_required/insolvent 的 trial 拒绝；这些是软件有效性条件，不是策略经济采用门槛。

只用搜索窗口选择一次参数，原样在全部验证窗口评估，不因验证收益重选。搜索每个 trial（包括非最优项）和验证窗口都逐事件重放；全部完成后才创建 `search.jsonl`、`validation.json`、`proposal.json` 和最终 `receipt.json`，失败不留参数建议，既有运行拒绝覆盖。`verify_account_experiment(output_dir, data, config)` 使用实际原数据和配置复算，不只是检查重新可算的文件 SHA。结果始终 `candidate_authorized=false`；即使三种算法小任务可复现，也不能越过正式研究、测试网或实盘门禁。训练 API 已将该多窗口接口接入；C5 再处理部署额度与真实合约单位，C6 再做完整在线式调度/限价撮合的对齐。

C3 新样本保留 `feature.meta` 的名称→索引格式，新增 `sample_manifest.json` 绑定文件、标签参数、输入 count/SHA、特征代码及配置。`sample_info.jsonl` 记录全部样本的 UTC 决策/特征可用/标签观察结束时刻；未知标签的 `training_row=null`，不作为 0 写入 libsvm。终局结构标签保守依赖窗口末端，未确认段不写负例。因而默认 `label_bsp_hold` 可能在时序 purge 后无训练样本；不能把这些标签回填进验证前的训练段。

三种 generator 都支持显式 `split_boundaries_ms={"train_end_ms": ..., "validation_end_ms": ..., "test_end_ms": ...}`；UTC 边界 end-exclusive，标签观察穿越分段末端会清除。未指定时按全池不同 UTC 时刻冻结 `folder_thred` 训练边界，其余时刻均分 validation/holdout，再按方向/市场分桶；旧 `test_cnt/test_auc` 字段是 validation 的兼容名称，独立 holdout 不传给训练器。

模型文件旁的同名 `.contract.json` 绑定模型/meta SHA、特征与训练代码、标签定义、样本清单、分段、配置及运行库身份。`CGeneratorModel(path)` 支持 XGB/LGBM/MLP，`CXGBModel(path)` 保留原 XGB 类名；复用 generator 的 estimator 与缺失策略。列按训练名称对齐；必需列缺失、非有限值、错误版本/摘要均拒绝。SMC FVG/OB 详情有显式数量依赖：仅数量为零时可缺详情；数量缺失/非法、数量大于零却缺详情或零数量附带详情均拒绝。该语义不取决于小训练集是否碰巧全都有 FVG/OB；其他列仍按冻结的必需/稀疏列契约处理。新公式身份须重生成模型，不能改旧 contract 续用。
旧 demo5 的无契约目录不自动升级为在线部署模型，须用新样本重建。

这些本地完整性摘要不是制品发布者签名；只加载可信来源的本地模型，尤其不要加载不可信 pickle。模型功能测试不代表收益或实盘授权。

#### 统一部署与三个评分时刻

`Trade.Script.Deployment.publish_deployment(path, model_path, candidate_score=..., entry_score=..., post_score=...)`
从真实训练 contract 导出 write-once `chan-deployment-v1` 清单。三个有限概率阈值必须显式给出，不按测试收益自动选择。
父目录须已存在；目标已存在、来源不完整、模型/meta/代码漂移时拒绝发布，不能为旧模型补写虚假来源。

在用户自己的配置中设置 `trade.deployment_manifest` 为该清单路径（相对配置目录或绝对路径）。清单是策略、标的、级别和阈值的唯一来源；`trade` 中旧的标的/级别不覆盖它，`chan_conf_extra` 的不一致覆盖会被拒绝。保留原 CCXT `mode`、市场类型与安全准入设置，行情库必须与训练来源匹配。该清单不是 candidate 收据，也不授予测试网或实盘权限。未配置清单的旧无模型 dry-run 路径保留；一旦要求/配置模型或清单，缺失和损坏不能回退成无评分开仓。

- `candidate`：最新已收盘上下文，以信号突破阈值作为假设入场价评分；冻结特征、结构来源和完整信号字节。
- `entry`：报价实际突破时重建当时已收盘前缀，重新确认候选仍有效，用观察到的报价评分；不改 OHLC，不将进行中 K 当已收盘。失败发生在订单意图 CAS 之前。
- `post`：只在该次入场观察所属周期收盘后重建并评分；交易记录的真实级别优先，不取全库最后一行，不被后来切换的全局部署替换。当前未收盘行还未入库时保持等待，已到期但缺行时明确失败。

三个阶段用同一 artifact/deployment，但价格和上下文不同可产生不同分数；同一决策时刻的三级批量与在线路径则要求完整评分字节相等。模型不能用于训练标签可用时间之前。SQLite 信号、订单 before 快照和 post 快照保存模型/部署身份及具体 bar；后验依据显式标为 `entry_observation`，不是交易所精确成交时钟，成交延迟与单位对账留给 C5。SQLite 自动非破坏性补列；MySQL 的部署新列尚未认证，拒绝模型部署写入但保留旧插入兼容。

修改被绑定的特征/训练代码后须重生成样本和模型；修改部署工作流代码后须重新发布到新清单路径。配置流水线和数据新鲜度总门禁仍待 C6，当前软件测试不代表真实交易所认证。

### 4. 可复现策略基线（仅样本内）

正式策略研究入口由仓库内 `ModelStrategy/research/` 维护。大型行情、SQLite
数据库和交易缓存继续放在仓库外，通过 `--research-root` 显式指定；规范文件中的
输入路径必须相对该根目录，不能写死某台机器的绝对路径。

当前已固化 corrected freeze-v4 的 `legacy-v1` 口径。Windows 示例：

```powershell
python -m ModelStrategy.research.cli baseline --spec ModelStrategy/research/configs/freeze_v4_legacy_v1.json --research-root C:\chanpy\research --reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json --output backtest_output/research/freeze_v4_legacy_v1.json
```

该命令只加载 2021-01-01 至 2026-01-01 的半开区间，无法通过参数开启 OOS。
即使 `btc_mlv.db` 含有 2026 数据，清单与计算也只查询边界前的逻辑 K 线。输出报告包含
Git commit/工作区状态、Python 环境、策略规范哈希、交易缓存哈希、分级 K 线逻辑哈希、
风险网格和 A/B/C 分段指标；任何参考指标漂移都会返回非零状态，且不会留下半成品报告。

当前参考结果为 `risk_pct=0.0075`、2021–2025 CAGR `46.917%`、最大回撤
`24.313%`。这是历史 `legacy-v1` 复现基线，不代表后续 `conservative-v2` 认证结果。

阶段 2 已冻结同一 freeze-v4 信号在 `conservative-v2` 下的独立参考。它使用完整真实 K 线窗口、真实首触成交时间、同 K 线不利止损、逐小时盯市、即时手续费、按当时标记价结算的资金费以及费后杠杆约束。历史交易缓存由 Asia/Shanghai 主机生成，规范显式声明 `source_timestamp_offset_seconds=28800`，在任何行情、资金费或分段判断前校正到 UTC；未来由 UTC crypto reader 生成的缓存不得沿用该偏移。资金费文件相对 `--market-data-root` 解析：

```powershell
python -m ModelStrategy.research.cli compare --spec ModelStrategy/research/configs/freeze_v4_conservative_v2.json --research-root C:\chanpy\research --market-data-root C:\chanpy\data --legacy-reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json --conservative-reference ModelStrategy/research/baselines/freeze_v4_conservative_v2.json --output backtest_output/research/freeze_v4_conservative_v2.json
```

保守口径只允许 `risk_pct=0.005` 通过 25% 回撤门槛：2021–2025 CAGR `30.076%`、最大回撤 `20.733%`、Calmar `1.451`。相对 legacy 口径，CAGR 下降 `16.842` 个百分点，最大回撤下降 `3.580` 个百分点。427 个信号意图中有 425 个成交（maker 394、taker 31），7 个按同 K 线不利顺序立即止损，2 个未成交；组合层最终接受 424 笔、因约束跳过 1 笔。

行情清单明确披露 8 段、共 29 根小时线缺口。缺口只按最后可用价格生成 `synthetic=true` 的盯市点，绝不参与成交或止损判断；任何成交耐心窗口中的真实 K 线缺口都会直接失败。以初始权益为 1，五年累计手续费为 `0.288132`，资金费净贡献为 `+0.113841`。这些数值说明旧口径明显高估了可认证收益；阶段 3 的 v5 认证必须沿用 UTC 校正后的 `conservative-v2`，不能再用 legacy 或失效的时间错位指标替代。

阶段 3 已按预登记顺序完成 BTC 样本内门禁。候选固定为 `S1bz + S2py10 + conviction#14 + z-limit(S2 非加仓) + z-exit`，迁移后的 UTC 候选输入使用 schema v2，并由来源哈希、原始/校正时间边界共同约束。复现命令为：

```powershell
python -m ModelStrategy.research.cli certify-v5-btc-is --spec ModelStrategy/research/configs/freeze_v5_candidate_v1.json --research-root C:\chanpy\research --market-data-root C:\chanpy\data --freeze-v4-reference ModelStrategy/research/baselines/freeze_v4_conservative_v2.json --candidate-reference ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json --output backtest_output/research/freeze_v5_candidate_v1_btc_is.json
```

正式结果为 `rejected`：25% 回撤门槛下只有 `risk_pct=0.005` 可选，BTC 2021–2025 CAGR `31.957%`、最大回撤 `19.807%`、Calmar `1.613`，未达到预登记的 `Calmar >= 2.0`。A/B/C CAGR 分别为 `32.532%`、`34.928%`、`27.259%`；425 个意图全部成交，组合接受 424 笔并跳过 1 笔。该失败按门禁终止阶段 3：没有解析 ETH/SOL/BNB 候选输入，没有运行共享组合，也没有新增或执行任何 2026 OOS 命令。紧凑拒绝参考见 `ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json`。

### 5. 7×24 交易例行(dry-run 起步)

交易模式只能由 `ccxt.mode` 显式选择，默认且推荐保持 `dry_run`。API
密钥本身永远不会打开测试网或实盘，`dry_run=False` 也不能绕过该配置。
dry-run 不创建 CCXT 会话；默认即时成交，测试时还可注入零成交/部分成交序列，
验证订单状态恢复而不连接交易所。这条旧模拟路径尚未完成 C5 的费用/funding/mark
账户与真实合约规格撮合验收，不能作为真实账户认证。

```yaml
ccxt:
  mode: dry_run                 # dry_run / testnet / live
  default_type: spot            # 当前新单位接口仅 spot / USDT linear swap；future 未验收并拒绝
  leverage: 1                   # 合约显式设置
  position_side: BOTH           # 合约 BOTH / LONG / SHORT
trade:
  strategy_receipt: ""          # 非 dry-run 必填
  strategy_id: ""               # 可选，与收据严格比对
  strategy_spec_hash: ""        # 可选，与收据严格比对
```

不使用行情网络的安全验收命令：

```powershell
pytest tests/test_trade_safety.py tests/test_trade_state_machine.py -q
```

日常例行仍可在 `mode: dry_run` 下运行；行情快照是否联网由
`snapshot_engine` 决定，但下单侧不会建立交易所会话：

```bash
# 单轮例行:更新数据→信号入库→突破开仓→后验→跟踪止损止盈(可放任务计划每小时跑)
bash Trade/Script/update_data_signal.sh    # Windows: pwsh Trade/Script/update_data_signal.ps1
```

非 dry-run 还必须同时满足以下门禁：

- 策略收据是有效 JSON，`status` 必须为 `candidate`，并包含非空
  `strategy_id` 与 64 位小写十六进制 `spec_hash`。配置了预期编号/哈希时必须
  精确相等。当前仓库内 v5 收据是 `rejected`，因此不能解锁测试网或实盘。
- 测试网要求 `mode: testnet`、`testnet: true`、API 凭据，并在进程环境中设置
  `CHANPY_ENABLE_TESTNET=YES`。
- 实盘要求 `mode: live`、`testnet: false`、API 凭据，并设置精确令牌
  `CHANPY_LIVE_TRADING_UNLOCK=I_ACCEPT_REAL_ORDERS`。
- `CHANPY_KILL_SWITCH=1`（也接受 true/yes 的大小写形式）会在每一张非
  dry-run 订单前重新检查并拒绝下单。取消和只读对账仍可执行，便于降风险。

状态机（库表见 `Trade/SqliteDB.py`）：

```
signal → submitted → partially_filled → open → closing → closed
              └────────── 0 成交时不产生仓位 ──────────┘
开仓 0 成交可终止为 canceled/rejected；部分开仓终止后按真实仓位进入 open。
平仓 canceled/rejected 且仍有仓位时回到 open，取得新意图后才可重试。
```

意图在提交交易所之前落库，客户端订单号由记录编号和尝试次数确定生成。
`CTradeEngine.restore()` 优先按交易所订单号、缺失时按客户端订单号恢复；只应用
单调增加的累计成交量。撤单只有在再次查单确认 `canceled/closed/rejected` 后，
才会以新客户端编号对剩余仓位提交 reduce-only 重试。

#### C5 订单单位契约（离线子边界，不是交易所认证）

内部 quota、requested/filled/current_qty 统一为**币数量**，名义金额为 quote 币（目标为 USDT）。
CCXT 线性合约接口的 amount/filled 则是**张数**，币数=张数×contractSize，见
[CCXT 官方说明](https://github.com/ccxt/ccxt/wiki/FAQ)。引擎从实际 market metadata 读取
contractSize、amount/price precision 和 limits，不从 symbol 猜 contractSize=1；现货不套用合约张数。
反向、非 USDT 线性永续及未适配的 future/option 组合拒绝。

非 dry-run 的 `prepare_order` 在 intent CAS **之前**完成数量/价格精度化、非零及
amount/price/cost 限额检查，且不向上扩大币数量；无法原样经过 DB/CCXT 数值边界时拒绝。
SQLite 在同一 CAS 保存精度化后的币数与 `open_order_contract`/`cover_order_contract`，
记录张数、价格/市价参考、market 身份/规格与摘要。原候选/入场报价仍留在评分快照中，
不把精度化限价冒称原观察报价。提交前重验，原有 CAS 后再次改数量的路径已移除。

累计成交回报先核对 symbol、请求量、方向、类型、客户端号和已有交易所订单号，再转回币数入账。
转换固定 Decimal 精度，不随调用方上下文改变。重启只查原订单并单调更新，不猜测重下；
单纯更改 tick/limits 或停用市场不会改变旧订单的冻结单位，新风险仍拒绝。
contractSize/交易所等单位身份漂移则明确失败，不能换算成另一个数量。

SQLite 自动只补两列，不为旧记录虚构单位。缺单位规格的旧合约在途单禁止重下，
单位未知的已有仓位也不能自动平仓；须先显式核验来源/单位，当前没有自动迁移放行入口。
取消原订单仍保留。MySQL 新订单契约写入在真实迁移/事务验收前 disabled，旧接口不自动升级。

C5 仍在开发：Binance/OKX 具体 position/margin/reduce/post/client-id 适配、完整分页查询、
逐腿持仓/余额对账与冻结新风险、含费用和资金费的模拟账户尚未完成；上述 mock/SQLite
验收不替代 C7 真实环境授权与认证。

当前只完成了离线可证明的安全边界，尚未完成交易所逐一测试网认证。待验证项包括：
沙盒支持与市场映射、客户端订单号历史查询窗口/分页、post-only/reduce-only/
positionSide 的交易所差异、单向/双向持仓模式、杠杆和最小下单量、部分成交后
撤单延迟、限频与断线恢复。在这些测试网缺口关闭且出现新的 `candidate` 收据前，
**真实交易保持锁定**。

五阶段的冻结数字、复现命令、已知限制和未完成的测试网/实盘检查项统一记录在
[最终验收与实盘前检查表](docs/superpowers/reports/2026-07-28-final-acceptance.md)。

## 三级联立策略(4H定方向 / 1H交易 / 15M区间套入场)

`CustomBuySellPoint/MultiLevelStrategy.py` 的 `CMultiLevelStrategy` 把形态学/动力学买卖点与多级别K线联立整合成一个策略:

```
4H(趋势级别) ──定方向──► 窗口内最新形态学bsp方向,否则最新确认线段方向
1H(交易级别) ──定交易──► 同向形态学bsp + 分型确认 + 突破分型极值 → 开仓
15M(入场级别)──定入场──► 区间套:1H bsp出现后 qjt_window 根内,15M出现同向1类
                          买卖点(动力学标记)才确认入场,并用15M分型收紧止损
```

```python
from CustomBuySellPoint.MultiLevelStrategy import CMultiLevelStrategy
config = CChanConfig({
    "cbsp_strategy": CMultiLevelStrategy,
    "strategy_para": {
        "trend_valid_bars": 60,      # 4H bsp 方向有效窗口
        "qjt_window": 8,             # 1H bsp 后多少根内接受15M确认
        "require_sub_confirm": True, # 必须15M区间套确认(交易类型带q前缀)
        "trade_bs_types": "1,1p,2,2s,3a,3b",
        "cover_on_trend_flip": True, # 4H方向翻转即平仓
        "max_sl_rate": 0.03, "max_profit_rate": 0.10,
    },
    "kl_data_check": False,          # crypto 跨日对齐无需检查
})
chan = CChan(code="BTC/USDT", data_src="custom:OfflineDataAPI.CStockFileReader",
             lv_list=[KL_TYPE.K_4H, KL_TYPE.K_60M, KL_TYPE.K_15M], config=config)
trades = list(chan[1].cbsp_strategy)   # 交易发生在中间的交易级别(lv_idx=1)
```

要点:

- **K线时间口径**:框架约定日内K线时间为**结束时间**,而交易所数据是开始时间;`CStockFileReader` 读取时自动 +周期 转换,这是 4H/1H/15M 父子对齐的前提
- 平仓条件:15M收紧后的分型止损 / 4H方向翻转(trend_flip)/ 1H反向bsp分型确认 / max_sl_rate/max_profit_rate 兜底
- 回测评估用 `CEvalConfig(..., lv_list=[K_4H,K_60M,K_15M], lv_idx=1)`;线上例行把 `config.yaml` trade 段设 `strategy: multi_lv` + `lv_list: [K_4H, K_60M, K_15M]` 即可
- 防未来:趋势判定只认当前4H K线**之前**确认的 bsp(回测引擎整根喂入父级别K线,不做此限制会看到未完成的4H分型)

## 模块总览(相对开源版新增)

| 模块 | 内容 |
|---|---|
| `Config/` | config.yaml 全局配置体系(CEnv) |
| `CustomBuySellPoint/` | CStrategy 抽象 + CCustomStrategy/CSegBspStrategy/CExamStrategy + CCustomBSP/CSignal;区间套(use_qjt) |
| `ChanModel/` | FeatureDesc 注册表、FeatureEngine 11特征族(540+,含SMC族)、CCommModel、XGB/LGBM/MLP 共用在线适配与版本化模型契约 |
| `Math/SmartMoney.py` | SMC检测器:FVG/订单块(笔结构定位)/流动性池+sweep/Premium-Discount位置 |
| `ModelStrategy/` | backtest 样本落地(五种标签)、CModelGenerator(XGB/LGBM/MLP)、eval_strategy、para_automl、FeatureReconciliation；`research/` 提供版本化规范、OOS 边界、输入清单和冻结基线复现 |
| `DataAPI/` | ccxt 重构(分页/volume/代理)、OfflineDataAPI、SnapshotAPI(sina/pytdx/ak/futu/ccxt)、ETFStockAPI、MarketValueFilter |
| `OfflineData/` | sqlite 落地层、ccxt_update/bao_download/bao_update/ak_update 等增量脚本 |
| `Trade/` | CChanDB(sqlite/mysql)、CTradeEngine/CCXTTradeEngine(dry-run)/FutuTradeEngine、OpenQuotaGen、Script 全套例行 |
| `Plot/` | draw_cbsp(虚线箭头/√/平仓连线/收益)、CosApi 图床、Upload2COS |
| 其他 | ExamGenerator 试题、send_msg_cmd 推送、CChan.extra_kl/toJson、CChanConfig 完整版全参数 |

## 测试

```bash
pytest                      # 全量(80+ 用例)
pytest -m "not network"     # 跳过联网用例
```

同一批K线的 load/trigger 结构与特征一致性仍是必需验收（`tests/test_consistency.py`、`tests/test_m7_final.py`）。因果性还需要发布时刻、未来父 K 变异、prefix/suffix 和低级别独立增量检查，不能仅由最终结果相同推出。

### 不可变策略决策记录

`CStrategy.decision_records` 返回只读的 canonical bytes 元组；`CCustomBSP.open_decision`、每次 `CCloseAction.decision` 保存首次发布时的特征、分数、初始止损、来源笔/段确认状态和退出动作。追踪止损、结构确认或类型后续改变不会改写这些字节。这些是策略决策证据，交易所实际成交/账户对账仍走独立交易层。

`strategy.publish_signals(chan, lv)` 是信号发布入口，SignalMonitor 已使用该入口；低层 `bsp_signal` 仍可查询。信号锚点为本级最后完成的 K 线，决策时刻为所有已发布级别的最新时刻。整批信号通过身份、有限数值、重复与时序检查后才进入记录，失败时不替换原 watching 集合。

`CustomBuySellPoint.Decision.read_decision(raw)` 重新验证版本、完整 canonical 字节、事件身份及 payload SHA。身份含来源市场、code、level、决策/锚点时刻、方向、类型、父事件和序号；内容变化不会伪装成另一个身份。历史或人工合成单元的市场来源为显式 null，不代表验证过交易所来源。

`feature_reconcile(..., lv_list=[KL_TYPE.K_4H, KL_TYPE.K_60M, KL_TYPE.K_15M])` 支持三级对账，原单级别 `lv=` 调用保留。它独立读取三次：批量 load、按收盘时刻分组的 trigger、无历史信号回调的控制路径；核对完整事件 payload、输入 count/SHA、每次策略更新时的结构和去重检查点。`report.is_exact and report.input_verified` 才表示本次精确路径对账通过；显式 `rel_tol` 只允许特征浮点容差，不把容差一致标为精确通过。缺证据、重复、乱序、无交易但输入不同，以及信号回调副作用均不能默认通过。

诊断输入仍须遵守 C1 的来源与 finality 契约。输入摘要相同不是交易所真实性认证，一致性也不代替独立的未来父 K/suffix 变异测试。诊断会完整读取并承诺结构内容，适合受控验证窗口，不自动启动全历史或冻结研究任务；`only_judge_last` 模式不能声明历史逐决策覆盖。

## A股与可选件

- A股研究:`DATA_SRC.BAO_STOCK`(联网)或 `OfflineData/bao_download.py` 落地后离线;GUI 见 `App/ashare_bsp_scanner_gui.py`
- futu 引擎/行情、pytdx、akshare、minio/腾讯COS 均为可选件,未安装时给出明确提示,不影响主流程
- `OfflineData/stockInfo/`(A股市值/交易信息缓存)未实现,选股市值过滤可用 `DataAPI/MarketValueFilter.py`
