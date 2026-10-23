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

Windows x86-64 的 CPython 3.11.15 与 3.14.2 已分别在无全局包的隔离环境验证核心/完整声明依赖；
两个完整环境各通过 1581 项离线测试（8 skipped、1 网络测试排除、18 条既有模型/弃用告警）。
实际版本、复现命令与边界见 [Python 安装矩阵](docs/superpowers/reports/2026-10-22-python-install-matrix.md)。
例如两环境 XGBoost 为 3.2.0/3.4.1；这不是全部未来依赖组合、其他 OS 或旧部署跨版本迁移保证。

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

该入口拒绝覆盖备份，保留全部原表，逐行比较备份与原库后才绑定来源；发现错误需更换独立库，不能改写已有来源。`CKLineDB.inspect_quality(..., now_ms=...)` 会返回 `ready/no_data/stale/gap/inactive/unknown_source` 等状态；下文 `RunTradeCycle` 已用显式只读连接接入运行壳，完整 C6 准入/E2E 仍未完成。

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
PS1/SH 共用一个 Python 调用并传递非零退出码；交易运行壳与单实例锁见下文。两版 Python 安装验收见上文；完整调度与更广跨环境验收仍在 C6。
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
账户与真实合约规格撮合验收，不能作为真实账户认证。需要经济核算时显式选择下文的
`CLinearPaperAccount`；现有配置默认值不改变。

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

显式 `mode: dry_run` 的配置驱动运行壳（不是无网络 E2E 演练）如下。
更新器会访问公共行情，快照是否联网由 `snapshot_engine` 决定；dry-run 下单侧不建立交易所会话。
以下仅为使用示例，本开发验收没有运行真实更新或下单：

```bash
# 显式配置；报告及交易库父目录预先存在，每轮报告文件名必须从未存在。
python -m Trade.Script.RunTradeCycle --config Config/config.yaml --report runs/cycle-001.jsonl
# 两个壳只转发同一个 Python 入口和真实退出码，参数可以包含空格。
bash Trade/Script/update_data_signal.sh Config/config.yaml runs/cycle-002.jsonl
pwsh -File Trade/Script/update_data_signal.ps1 Config/config.yaml runs/cycle-003.jsonl
```

此入口不回退 demo 配置或内置 BTC/ETH 池，要求显式 SQLite `db.sqlite_path`、
`offline_data.sqlite_path/source_identity` 与一致的 `ccxt.exchange/default_type/mode`。
未配置模型时必须明确 `trade.code_list`、`lv_list`（或单一 `lv`）、`strategy`；
配置 `trade.deployment_manifest` 时复用 C3 的真实模型/部署 reader，其冻结 symbol/level/策略优先，
同时核对行情来源。要求模型却没有部署，或模型/清单损坏时不继续生成新订单。

顺序为原订单恢复→配置/模型→逐 symbol 更新→只读来源/缺 K/水位检查→信号→输入重验→新开仓。
任一输入失败就停止新增风险，但分别尝试后验、错误仓位关闭、止损跟踪、平仓查单/重试；
这些操作仍受原账户/订单证据、candidate、模式、环境与 kill-switch 约束，不保证操作一定成功。
未知恢复结果退出非零，不能猜测重下；SignalMonitor 的部分计算失败也会返回非零。
管理阶段本身失败不跳过后续管理。配置指纹改变属于账户/目录授权漂移，后续动作全部停止，
不会将新配置用于旧仓管理。

运行壳与实际开仓共用 `Trade/Script/OpeningInputs.py`，不再仅信任信号子进程返回 0。
同一次 SQLite 只读事务检查全部配置 symbol/level 的 closed rows，并对完整 OHLCV（含 volume）、
scope、配置、策略/输入检查代码与 Python 身份生成摘要；相同水位但数据已修订也必须拒绝复用。
信号生成后再次核验，开仓子进程必须接收原运行的三个摘要，不能以新有效数据替换旧批次的输入。

开仓输入的质量检查和 raw OHLCV 摘要使用逐行 SQLite cursor；旧 `query_klines` 仍返回列表，
新 `iter_klines` 保留相同排序及 `[begin_ts,end_ts)` 区间，提前停止时调用 `close()`。
核验仍扫描全部历史，不截断、缓存或只比较水位；每个 closed row 的 canonical 字节加原数组分隔符
增量送入 SHA256，结果必须与旧整数组摘要完全相同，同一只读事务内保持质量/摘要快照一致。
仅该输入核验的常驻 Python 内存不随行数增长；不是全引擎、完整账本重验或运行时延的容量认证。
本次检查代码身份改变，旧模型/部署须按原发布流程评估兼容性，不能重封旧产物冒充原身份。

`MakeOpenTrade` 命令入口现在要求运行壳元数据，不再支持无上下文的独立命令开仓；
程序库的原直接调用与股票路径保留兼容，但没有检查器就不能宣称已通过本输入检查。

显式 `COpeningInputs(config_path, ...)` 可绑定为 `CCCXTTradeEngine(..., opening_inputs=guard)`。
每笔检查实际 DB 路径/engine 来源、配置池/交易级别、C2 冻结信号与原始已收盘 bar，以及 C3 模型身份；
在准备前、意图前、等待频控后与发送边界重验。`snapshot_before.opening_inputs` 和原订单 journal identity
保存当时检查，之后不得移除、重标为新输入版本或复用到另一信号。意图后失效保持 created/submitting 的
实际未知边界，不自动重置或重下；query/cancel/reduce 不使用这个新增风险检查。
缺行情、非有限/非正价格、模型损坏或检查失败令配置开仓 CLI 非零退出，不再把拒绝表现为成功的空结果。
明确提供完整 paper 时沿用调用者的 UTC/bid/ask/mark，不用单一 last price 补造 mark。

配置开仓 CLI 有待开信号时，还要求用户配置 `snapshot_engine: ccxt`，并为
`trade.quote_max_age_ms` 明确指定正整数毫秒上限；没有默认秒数，缺失/非法即阻断新风险。
不会修改用户配置或退回 sina/裸价格读取；无本轮标的/级别信号时不请求新风险报价。
旧库调用的 `price_map` 与旧 `CCCXTSnapshot.query` 保持兼容，但不能据此声称报价有来源/年龄证明。

`CCCXTSnapshot.query_quotes(codes)` 保留实际 exchange/options 来源、请求起止 UTC 毫秒、
ticker 的原 symbol/last/timestamp，形成有限 canonical `chan-market-quotes-v1` 与 payload SHA。
未知/缺失/未来时钟、错 symbol、非正或非有限价格、来源变化和不完整批次全部拒绝，
不把接收时间补成交易所时间，不保留 raw info、凭据或任意网络异常正文。
`Common.MarketQuote.read_quote_batch(..., source=..., symbols=..., now_ms=..., max_age_ms=...)`
按调用时钟重新核验，摘要/曾经读过/ready 标志不能代替当前年龄检查。

程序库可显式 `prices = guard.bind_quotes(batch, max_age_ms=policy)`，然后用该 `prices`
调用实际开仓。每个 guard 只绑定一份原批次；已声明的配置年龄策略不能被调用方放宽。
v2 `snapshot_before.opening_inputs` 同时保存原 batch 与年龄策略，原 v1 历史仍原样读取，不补造过去报价。
已有 v2 意图的数据库必须保留支持 v2 的恢复 reader；不能为回退旧代码而删除证明或改写为 v1。
原始价格必须与本次信号使用的报价相等；限价/张数仍由已有 precision 契约处理，实际成交价格不作保证。
意图前、等待后、claim 前/后及发送前继续重验，且在重读行情/模型/历史**结束后**再读当前时钟，
避免把检查开始时仍有效的旧报价当作检查结束时仍新鲜。新 guard/报价不能重标已取得的意图；
过期时只保留 created/submitting 的实际边界，不自动重下，原单 query/cancel/reduce 不受新报价年龄限制。
原 journal reader 会再验来源、信号身份/级别/类型、原价、策略与时钟，不能只重封 JSON SHA。

这个时间仅是 `clock_kind=exchange_ticker_timestamp`；不声称它是 bid/ask 或 mark 的生成时间，
也不是服务器签名、完整盘口、账户风险准入或交易所真实性认证。Common/输入检查代码身份改变后，
旧模型须重生成并重新部署；不能重封旧模型契约。本开发只运行合成数据/fake I/O。

SignalMonitor 仅在重复信号的完整 frozen bytes 相等时记录为 existed；同一 SQL 目标却内容不同则
报告失败并保留原记录，不忽略时间/评分字段来制造一致。重复观察产生新候选时钟等内容时仍会闭锁，
后续显式信号换代/失效工作流尚待验收。此输入版本检查会全量重读相关已收盘历史与文件身份，容量未认证；
行情库、交易库和网络没有全局原子事务，检查后的外部变异/in-flight 不能声称已被消除。
上述 ticker 来源/年龄检查不是完整原生账户或 mark/book 时钟证明；原生账户鲜活准入与 C6 其余要求仍待。
显式单写入器 paper 的进程级演练入口见下文，不自动接管默认运行壳或真实交易。

同一交易 SQLite 路径使用 OS 单实例锁，换报告名不能绕过；句柄退出即释放，残留 lock 文件不是运行证明。
此锁尚不覆盖直接运行旧单脚本、跨主机或物理库的硬链接别名。JSONL 逐阶段写唯一运行 ID、
退出码/脱敏原因、行情来源/水位及模型身份，并 flush/fsync；中断时保留已写前缀，缺少完成事件不能视作成功。
报告已存在或误指交易库时启动前拒绝。报告 I/O 失败阻断新风险，但仍尝试原账户管理；
磁盘故障可能使最终事件无法落盘，须以非零退出码与原 DB/订单恢复核验，不能把日志当准入收据。
子进程每阶段最多 300 秒，超时视作未知/失败而非“没有成交”，不回显可能包含凭据的任意子进程日志。

通知失败现在独立于交易阶段结果可观测。默认运输使用内部 `RunTradeStage` 执行固定白名单模块，
只在该子进程内收集 `send_msg` 的后端、attempted/accepted/failed/local_only 计数，
以绑定 run_id/stage_id/module 的有限 canonical、SHA、write-once 临时摘要交给父进程。
父进程限 16 KiB 读取，复核字段、计数与身份后写入原 JSONL 的 `notifications` 事件及最终结果，
不采集任意 stdout/stderr，也不存消息标题/正文、收件人、URL 或凭据。
空的有效摘要才说明该阶段未调用通知；缺失/坏摘要是 `unavailable`、counts=null，中断尝试是 `incomplete`，
均不能解释成零失败。自定义 command 运输若不发布摘要也会明确标 unavailable。

`send_msg` 仍返回 bool，失败只输出固定后端/原因，不打印异常或响应全文；未知/损坏配置不再降级成功的 none。
HTTP 后端必须取得本软件规定的类型化 ACK，不能只看 HTTP 200；SMTP 拒收或异常返回失败，连接有 30 秒上限。
accepted 仅表示收到本次成功 ACK，不证明外部送达/已读；failed 也可能是远端已处理但 ACK 丢失，**不自动重试或换后端**。
显式 none 仍作本地输出、计 local_only，不算外部 accepted；调用者主动提供的本地消息仍会显示，但不进入阶段摘要。
通知/摘要写入/临时清理/固定诊断输出失败不重写原阶段退出码或回滚、重下订单；原输入/订单失败仍保持非零。
这些是串行主线程的软件观测，自建后台线程收集未验收，不是通知服务或交易所认证。
工作流指纹已包含新入口和通知代码，部署需重新发布；
旧 paper 代码身份不能重封，跨版本迁移仍须另行验收。

现有 `Plot.CosApi.upload_file` 的显式空/无效配置不会回退读取全局图床配置；只有 `conf=None` 保留原加载行为。
minio/txcos SDK 或签名 URL 失败会抛固定脱敏异常，缺可选依赖仍为 CONFIG_ERROR，成功 URL 和原图文件不变。
失败不证明远端未保存对象；dispatcher 不自动重试或切换后端。两版解释器各 136 passed / 1 既有 GUI skip，
涵盖真实 dispatcher/后端与 fake SDK、通知及调度回归；不包含真实图床服务、SDK 自身日志/内部重试认证。
图床目前仅由绘图上传接口调用，不在默认 TradeCycle 阶段；Notion 尚未集成，不能将此子项称为全部可选输出完成。

当前运行壳对非 dry-run 新风险明确返回 `native_fresh_admission_not_integrated`，
`native_admission_verified` 恒为 false；历史上没有冻结并不等于鲜活账户准入。
已有仓位管理仍可按原门禁尝试。独立 paper 与默认脚本的显式软件 profile 已接进程级状态绑定；
通知固定摘要/脱敏及上述两版 Python 安装项已验；强制原生鲜活账户准入、更广 E2E 仍待 C6。
原生准入的当前缺口、官方来源和已获明确批准的严格方向见
[fresh-admission 审计](docs/superpowers/reports/2026-10-22-native-fresh-admission-audit.md) 与
[串行实施计划](docs/superpowers/plans/2026-10-22-native-fresh-admission.md)；仅 fake 开发，尚未替代上述门禁或授权真实请求。
独立 `Trade.NativeMarketEvidence` 来源层现已实现：完整 market metadata、分别读取的 raw mark/BBO、各自来源时钟与本地窗口、
每次 GET 前后公共路由/客户端环境核验，以及 allowlisted raw→派生值重算。金额单位沿原严格 Decimal 边界，无 epsilon/舍入补救；
空/交叉/零量盘口保留为不可交易观察。SDK/源码摘要只描述本地采集身份，`requests` 计显式 SDK 来源调用而非全部底层 HTTP 尝试，
本层不认证服务器/SDK 内部重试、不能证明账户或持仓齐全；自封 SHA 也不是准入能力。
两版 Python 各 166 个来源用例通过；适用原账户/冻结/订单恢复/壳/报价组合各 734 passed / 1 既有 isolated 通道 skip。
来源观察始终 `native_admission_verified=false`，不提供隐含 max-age；下述政策/使用子边界也不替代全账户关联与原 CAS 消费。
现有 `Trade.NativeAdmission.read_native_freshness_policy` 要求所有来源年龄/跨度与时差字段显式给出整毫秒，
不接受 bool/float/字符串或 ticker 回退；0 按严格零处理，没有金额容差开关，也没有修改现有运行配置。
`assert_native_account_market_freshness` 已将原账户与 S1 原观察按完整市场池、当前 typed profile/公共环境/SDK 绑定，
以最早读取、原来源时间及使用完成时间核验年龄/跨度/时差，并阻止检查期间输入字节变异；成功仅返回 None。
它不验证钱包/成交覆盖、全账本与历史冻结、原生未决单/保证金预占或原 CAS，不能当成准入/解冻接口。
调用者须保证只读身份 GET 在 DB 写锁外，不能把 helper 没有创建事务理解成它能检测外部持有的锁。
新增 149 项政策/使用用例，连同来源及原账户/订单/壳/报价适用组合，两版 Python 各 886 passed / 1 既有 isolated 通道 skip；
真实 I/O、C7 认证及完整 S2/S3/S4 尚未完成，默认非 dry-run 开仓阻断仍保留。
后续 `assert_native_persisted_interval` 只按原持久 check ID，在原 SQLite transaction/savepoint 内重读原来源、
全部 trade-shaped 历史/投影及 sticky freeze；已有更新账户快照或同钟不同快照时，旧检查失效，不按 SHA 选择来源。
当前 after、wallet 原采集窗口与 execution 原 manifest 的 native observation 共同计龄，不用历史覆盖区间或较晚 DB 导入时间刷新来源。
独立 mark 必须与非零原持仓 mark 精确相等；事务释放/最终字节核验耗时也在使用预算内。
新增 56 项，两版适用回归各 1103 passed / 1 既有 isolated 通道 skip；这是 DB-only 检查，不做网络或新写入、仍仅返回 None。
未决原生单/余额预占、完整当前金融闭合、每单原 CAS/HTTP 消费和容量验证仍待，不能将其当成 fresh-admission 或用来删除常量阻断。
`Trade.NativePendingOrders` 已提供独立未决来源观察：Binance 普通/conditional 两通道，OKX 普通及八种算法通道，
不按候选市场过滤，OKX 按 native ID 分页至短页。每页带前后 typed profile、请求窗口、原字段与 SDK/路由身份；
128 次显式调用预算包含 profile，耗尽则拒绝整批。Binance 的 ID 重复检测包含 symbol，避免跨币对误冲突。
普通单同时保留原单位、币数/张数/累计及剩余量；算法条件数量、未知市场和附带复杂条款保留为未证实项目，不能当零风险。
两版 Python 各 251 项新用例、779 项适用组合通过。来源仍 flags=false，不证明 bot/copy 等未观察通道、原子不存在或余额预占，
尚未接入原 intent/CAS；无实际交易所请求，也未改变配置或任何候选/测试网/实盘门禁。
`Trade.NativePendingOwnership.observe_native_pending_ownership` 已沿原 SQLite transaction/savepoint 核验全 trade-shaped
历史、原契约与普通挂单，保留每个本地非终态请求的剩余币数/张数；列表出现或消失均不会补 ACK、重下或释放预留。
同账户同市场订单号歧义、原契约/累计量/条款不符、复杂单和历史缺口会明确拒绝或保留问题；仅可证明的其他账户可排除。
原执行设置/限额检查直接复用，事件时钟倒退或晚于观察也拒绝。报告中的 native_margin_amount 仍为 None，两个 flags=false；
原生冻结余额/保证金、完整金融闭合和 CAS 消费仍是后续依赖。验证范围及双解释器记录见开发验收台账。
`Trade.NativeBalanceReservations` 进一步保留原生余额/预占分项：固定配置→账户余额→配置三段 GET，
每段核原 typed profile/环境与 SDK，共 9 次显式调用。Binance position/open-order initial margin、
OKX ordFrozen/frozenBal/借贷/策略与 copy 分项按原币保存，USD 总额单列；缺失或不适用金额为 None，未换汇或逐单分摊。
显式 OKX 配置响应 UID 也必须匹配前后账户，只持久摘要。新增 66 项、两版各 940 项适用回归通过；
该独立来源仍两个 flags=false，完整金融闭合、来源当前使用和原 CAS/HTTP 尚未集成。
`Trade.NativeAccountReconcile.observe_native_account_components` 已能按原持久来源 ID、全账本与已有冻结状态，
重建两币种实际部分平仓/未决开仓的观察闭合。原区间核算共享体增加独立 pending-v2 路径；v1 保留原非终态规则和报告字节，
新路径只能从原始 pending 和同一 ledger 重建归属。各币现金、费用/资金费、pooled entry、独立余额响应中的仓位及 margin 分项一并核验，
拒绝旧可用额覆盖最终快照、同市场历史 ID 歧义、外币未解释保证金及空列表下非零挂单保证金。
新增 59 项；精确验证范围见台账。matched_components 仍非准入，两个 flags=false；持久化/失败发布的后续进展见下文，全部来源当前性与 CAS/HTTP 接入仍待。
`Trade.NativeAccountStore` 现已独立 append-only 保存原生 pending/balance，CChanDB 显式存取/账户列举接口可重启重验，
不修改旧 AccountStore schema 或重封旧证据。85 项新测试、两版各 1519 pass/1 既有 skip；来源存储不发布 PASS/冻结或写订单，
完整 freshness 与 CAS/HTTP 门禁不变。
`CChanDB.reconcile_native_account` 现可从持久 source IDs 与完整原账本构造独立版本检查，保存在原 append-only 检查表；
重读按显式 event-id 前缀与全部尝试重建，不用现时投影改写旧结果，新旧失败共享原 sticky freeze，后来的匹配不会解冻。
新增 37 项；两版各 1662 pass/1 既有 skip（另 6 条小样本模型警告）。复用原金融/发布/风险门禁，报告仍历史观察、两个 flags=false，
并非完整当前准入或测试网/实盘授权；全部来源 freshness、collector-owned、独立 mark/book 与每单 CAS/HTTP 消费及 C7 仍待。
`Trade.NativeCurrentComponents` 新增联合只读使用断言，将匹配的 native check、原全账本/冻结、最新已知来源和独立 mark/book，
与事务外当前账户/公共路由/SDK 复查及最终统一 use-time 预算关联。独立政策版本显式新增 balance age/span，旧政策不加默认值。
107 项新测试、两版适用组合各 1663 pass/1 既有 skip；复用原区间/时间核验，不写 PASS/订单，None 不代表授权。
collector-owned 采集进展见下文；完整运行时身份、原 CAS/HTTP 每单消费与外部 C7 仍待，常量阻断和全部交易 gates 保留。
提交前复核另补了已知事实覆盖：较旧的 wallet/execution 来源也不能遗漏区间事实，零净额往返亦不能净掉；
任何已知终点后事实会使该账户点过期，基线前历史仍可忽略。新增 12 项后当前 119 项，最终关键组合两版各 361 passed；
其余未变模块沿用上述广回归，不能把来源时间较新等同事实较完整。
`Trade.NativeComponentCollector` 进一步固定 pending→balance→after→逐市场 execution→全账户 wallet→独立市场→原子发布/check→current 的本地自采路径。
接口只收 SDK、原 CChanDB、before ID、完整市场与显式 scope/policy，不收 caller receipt/check/PASS；全部 GET 在 SQLite writer lock 外。
沿原 store/核算/失败发布复用，提交失败不把内存中的失败结果当持久冻结，连接替换不向另一库写失败；来源写入失败完整回滚，缺可写原库时拒绝但不声称已冻结。
78 项新用例、两版 Python 适用广组合各 1753 passed / 1 既有 skip。两市场 fake 实测显式 SDK 调用为 Binance 39 / OKX 58，
上界分别为 276+132N / 274+132N（N 为完整市场数，最多 64）；不保证 SDK 内部 HTTP 重试或真实容量。
该本地诊断包装仍 economics_complete=false/native_admission_verified=false；并非可转交的下单许可或完整运行时身份，尚未接每单 intent/CAS/HTTP，不能删除常量阻断或重新武装旧候选。
`Trade.NativeInstrumentEvidence` 新增独立 instrument 来源：只调用一次明确公共 endpoint（Binance/binanceusdm fapi exchangeInfo；OKX public instruments SWAP），
按完整显式目标池保存允许字段、原生状态、请求窗口、SDK/代码和执行 metadata，不读取或刷新调用者 SDK cache，不调用 currencies/跨产品 loader。
重建复用当前 credential-free SDK 纯 parser 和已有完整单位/metadata 验证；tick/lot 缺失不借小数位数补齐，显式原生币种/类型矛盾不由 SDK 推断覆盖。
exchangeInfo.serverTime、上架/到期/未来生效时间均不作新鲜时钟，source_ms=None；0..100 精度位数仅是原 wire-number 指数范围内的解析资源边界。
422 项新用例、两版各 1122 项适用组合通过；核心 import 无可选依赖，显式 reader 则需要相同 SDK 重建，缺失时拒绝。
这仍是来源层，不是全部平台交易规则、逐单额度/资金锁、默认 Engine fresh metadata 接入或原 CAS 授权；两个 flags=false，账户级串行协议已获批准，资金能力及 C7 门禁仍保留。
`Trade.NativeInstrumentCurrent.collect_native_instruments_for_engine` 再提供显式本地消费边界：自行采一次新 instrument 来源，
与实际原 Engine 的完整 metadata/active/原生状态比对，并前后核现有 SDK cache/options、public route、方法与 SQLite 身份。
只复用原投影的已初始化缓存分支；缺缓存/旧规格/受替换方法拒绝，不 reload、不 set_markets、不写 DB/订单。
两个 age/span 整毫秒预算必填，无默认宽限；年龄包含最终解析和 DB 复核耗时。446 项新用例、两版关键组合各 1568 passed，集合一致。
返回的仍是原来源字节、两个 flags=false，不是可转交授权；原默认 prepare/发送及常量阻断未改，完整 CAS/逐单资金/新版本指纹和 C7 仍未完成。
账户级串行协议已获专门批准；`Trade.NativeOrderBoundary` 先实现 DB-only L0：从原持久 native check、完整 ledger/journal、来源、冻结与显式政策捕获基线，
只在原 SQLite 自有事务内严格重读；没有 SDK I/O、资金公式、新订单表或授权结果。153 项新用例、两版适用组合各 493 passed，集合一致。
在此前置层之上，`Trade.NativeOrderTransition` 已给原 intent/claim CAS 增加显式本单 L1/L2 持久引用：原事务只允许实际参数的确定整行变化、一个原 intent/attempt 与一个原 claim event，重启后的 claim 自行读取原 L1，不接受 caller expected ledger。
引用表 append-only、指向原 journal；完整 trade-shaped 整行摘要及来源/冻结/预算一起核验，unknown 不因时间或 pending 空列表释放。381 项新用例，CPython3.14.2/3.11.15 的54模块适用组合各3688 passed/1既有skip/13小样本模型警告，唯一集合相等。
新诊断意图显式使用不可执行的 `chan-native-cas-order-v1`；当前与旧严格 Engine reader 均拒绝它，原 v1/v2/v3 的已存字节不重封。它只证明原 CAS 增量一致性，两个 flags=false，没有资金能力或 HTTP 许可；逐单资金、完整 prepare/runtime/新指纹、默认自采消费与 S4/C7 仍待，不能默认发送或重臂旧候选。迁移与完整证据见开发台账 S3c 记录。
`Trade.NativePreparation.capture_native_prepare_identity` 已补本地身份前置层：自行重读原信号、配置、候选与行情输入，调用原 Engine prepare/精度/限额；适用时核原部署和真实 entry 评分，并检查选定加载函数的 code、defaults、globals 与 owner。
它不接受 caller receipt/check/PASS，不写意图或资金，不调用下单；缺现有client时在创建会话前拒绝。输出 `chan-native-prepare-identity-v1`，两个 flags=false。438 项新用例，两解释器各754项适用组合通过（7个小样本模型警告）；源码检查不是整个解释器可信证明，身份采样不是当前来源窗口，JSON不能转交当准入。完整instrument/component自采→原CAS/HTTP、逐单资金、默认入口和C7仍未完成。
版本化 API 见下文，本入口的命令完成状态不是完整验收或生产授权。
先前22项原生单位联合夹具验证实际SDK prepare、双币非空账户自采及L0：Binance contractSize=1、OKX保留ctVal，原历史含部分平仓、未决单、fee/funding和非零预占；最终双解释器通过。这22项手动组合本身不证明生产入口、持久CAS绑定或逐单资金能力；后续受控调用见下段，详见台账S3e。
`assert_native_prepare_context_current` 已可在原SQLite自有事务内复核实际prepare的活上下文，重用原输入/候选/模型和冻结检查，不调用SDK/prepare、不写表、不接受JSON或复制对象，成功仅返回None。313项新用例，双版12模块各1089通过（7个已知模型警告）；上下文回收不释放原订单。该公开断言仍仅适用于intent前本地一致性，不是跨重启凭证或当前原生资金证明。
`Trade.NativePreparedIntent.acquire_native_prepared_diagnostic_intent` 现将同次实际prepare→instrument自采→原component自采→L0→原intent CAS绑定起来；不收caller receipt/check/PASS。原writer在同一事务保存 `chan-native-order-transition-v2` 的完整preparation引用，严格核本单整行唯一增量、全账本/原journal，并在引用INSERT/回读及本地回调后再核全部来源预算。只复用原核验体和现有引用表，没有第二套资金/订单状态机。
72项新增用例覆盖双venue/持仓模式/多空非空账户、真实小合成模型、来源/引用变异、原事务回滚与重启读取；CPython3.14.2/3.11.15相同24模块各1841 passed、0failure/error/skip、9个模型警告，非全仓或外部认证。历史v2 reader需对应SDK纯解析、无需client/GET；原v1不受此新增要求影响。v2仍使用不可执行 `chan-native-cas-order-v1`，claim在原SQL前明确拒绝，两个flags=false；完整L1/L2后本地重建、逐单资金、新执行版本全reader、HTTP/default/S4/C7仍未完成。多次GET不是服务器原子快照，本地handle/源码摘要不认证整个宿主；不得据此解除门禁或重臂旧候选。
在此基础上，`assert_native_prepared_intent_current(engine,record_id)` 已可从原持久L1/不可变事件取得完整after-row和全账本基线，在原owned视图复核实际输入/候选/模型/选定runtime、原SDK缓存和本地路由，不GET、不prepare、不写表，只返回None。原Engine消费该检查后仍执行原资金拒绝；没有放行claim或发送。
新写入的preparation binding为 `chan-native-prepared-intent-binding-v2`，仅增加原调用的client_binding_sha256（缓存/route/SDK凭据摘要，不保存明文）；原capture identity和来源schema不变。旧binding-v1可历史读取，但不会补摘要、重封或获得新当前性。70项新用例、双版相同26模块各2357 passed/0failure/error/skip/9模型警告，实际旧库副本保持原字节且claim拒绝。该步的新Engine/guard/连接复核复用了已有缓存；冷启动后续见下段，L2/HTTP前消费、逐单资金/全部执行reader/default/S4/C7仍待。代码/配置/输入时代与原来源窗口必须匹配，整个S3e和完整版仍未完成。
显式 `Trade.NativePreparedClient.initialize_native_prepared_client` 现可在原Engine无client时，沿原factory、原生instrument GET、原SDK纯parser/set_markets及账户设置/身份GET建立新SDK缓存；已有client一律不刷新、不清除。原L1须完整匹配原SDK摘要、全部账本和旧来源窗口，新GET不能续期、重封或提供发送权；失败只清理本入口仍持有的新client，原订单/未知状态不释放。首轮54项新用例含两个全新Python进程重建；双版8模块各368 passed、0failure/error/skip、2个既有模型警告。全部为fake底层运输，不证明真实签名/网络、完整加载闭包或资金能力；该入口未自动接入默认发送，v2 claim与资金拒绝保持，详见审计§29。
后续收尾校正增加24项回归：在最后业务时钟/本地回调后再核原SDK摘要，并以单调纳秒差形成覆盖尾段核验/原事务退出的保守使用时刻上界。它不改原生来源时间，不放宽age/span；近边界可能更早拒绝，正1ns向上计1ms不是额外容差。最终双版8模块各392 passed、0failure/error/skip、2个既有模型警告，详见审计§30。资金设计仍未确认，原claim/default及整个S3e/C5/C6/C7门禁不变。

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

SQLite 只做非破坏性补列，不为旧记录虚构单位或 UTC 意图时间。缺单位规格的旧合约在途单禁止重下，
单位未知的已有仓位也不能自动平仓；须先显式核验来源/单位，当前没有自动迁移放行入口。
原账户/环境有 v3 证据且仍匹配时保留原订单的取消/管理；旧 swap 缺账户证据时，不能仅按服务器 id
自动取消另一账户可能同号的订单，须先显式核验归属，当前没有自动补证放行入口。
MySQL 新订单契约写入在真实迁移/事务验收前 disabled，旧接口不自动升级。

C5 仍在开发：订单恢复及观察区间核对/持久冻结的离线边界见下；
完整鲜活准入链、隔离资金通道和含费用/资金费的模拟账户尚未完成；mock/SQLite 验收不替代
C7 真实环境授权与认证。

#### C5 平台参数与执行规格 v2

Binance/OKX 的原生 request builder 已分别做离线验证。授权的非 dry-run swap 还必须
显式给 `ccxt.position_mode: one_way` 或 `hedged`、`ccxt.margin_mode: cross` 或 `isolated`，
以及 1–125 范围的整数 `leverage`（实际可用上限仍由市场/账户决定）。默认 dry-run 与用户配置文件不变。
下单前只读核对真实账户的 position mode、margin mode 和相应 leg 的 leverage，
设置不一致就拒绝新风险；普通下单不再自动调用 set_leverage/set_margin_mode/set_position_mode。
账户设置应在独立授权的准备流程中完成，不由订单代码悄悄切换。

- `one_way` 使用 `BOTH`，`hedged` 新信号从方向确定 `LONG/SHORT`，并冻结到 intent。
- Binance hedge 不发送被禁止的 reduceOnly，退出用相反 side 和原 positionSide；one-way 退出才带 reduceOnly。
- OKX 使用自己的 tdMode/posSide；hedge 退出也不带 reduceOnly。现货显式 cash，市价数量使用 base_ccy，禁止服务端自动改量。
- post-only 使用实际 CCXT 映射到 Binance GTX/现货 maker 或 OKX post_only；该 bool 也写入规格，不允许提交时临时改变。
- 新客户端号是确定性、最多 32 位字母数字；旧 id 不截断、不重写，恢复继续使用 DB 原号。

`chan-ccxt-order-v2` 同时绑定单位、execution 设置、只读账户观测和 post-only，读取时
验证完整字段/类型/关联关系，不只检查 SHA。原有已知 leg/margin 的降风险订单继续使用
开仓时的设置；后来全局配置切换或仅 leverage 漂移不应把它切成另一条腿。
v1 单位规格仍可只读兼容查单，v2 的执行设置读取也保留；这些旧规格不因此获得历史账户归属证明。
在准备结束、提交权 CAS 前和实际发送前均复查既有 kill-switch/解锁条件。

#### C5 新永续订单的账户/环境规格 v3（离线协议验收）

新 swap 意图使用 `chan-ccxt-order-v3`，沿用单位/执行参数/成交状态机，并在同一 SQLite
意图与追加式 attempt 历史中冻结 `account_context`。Spot 继续使用 v2，dry-run 不创建账户会话。
账户上下文保存 typed identifier 的 SHA256，不保存原生标识明文、余额、任意响应或密钥：

- Binance 使用永续 `GET /fapi/v3/balance` 的唯一 `accountAlias`，类型为 `futures_account_alias`；
  不借用 Spot UID 或调用者 account_scope。[接口定义](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Futures-Account-Balance-V3)
- OKX 使用 `GET /api/v5/account/config` 的 `uid`；缺失、多项或矛盾响应拒绝。
  [接口定义](https://my.okx.com/docs-v5/en/#trading-account-rest-api-get-account-configuration)
- 私有读取前核对实际 CCXT sandbox 标志、TLS 校验、有效私有路由，以及 OKX 模拟盘请求头和 hostname。
  路由以安装的无凭据 CCXT 标准客户端为基准；不允许自定义私有端点静默混用环境，区域端点不在本次支持范围。

提交权 CAS 前、读取/提交响应后重新核对原账户。漂移或读取未知即拒绝记账/新提交；
响应期间漂移的已发送订单保留未知状态，不推断失败再补单。重启和降风险继续使用原账户/leg，
不能因当前配置变化把新平仓意图冻结到另一账户。取消也要求唯一持久化订单和原账户匹配。
旧 v1/v2 swap 不补造账户证明，故不自动新提交、取消或新建 reduce 意图；原有历史单位/回报的
兼容读取不等于账户审计通过，显式历史关联/迁移尚待后续 C5。

这是请求前后的客户端/原生身份观察，不是服务器签名、对并发修改客户端的全局锁或 C7 外部认证；
标准路由能否连接当前测试网也未实际验证。逐笔来源的 `account_scope_verified=false`、
`economics_complete=false` 不会因此升级。区间核对/持久冻结见下文，不等于完整鲜活准入或含费模拟验收。

#### C5 ACK 与有界历史恢复（离线协议验收）

create_order 的 ACK 不等于成交报告。引擎先保存已验证的交易所订单号，
不把未知 filled/status 写成零成交或 open，再按该 id 补查。补查失败保留订单字段
`*_order_status=submitting`（生命周期仍为 submitted/closing），
恢复继续查询原意图，不自动补单。完整报告必须匹配冻结限价、数量、方向、单位与服务器
leg；v2/v3 还核对原生 post-only、one-way reduce-only，以及 OKX 的 tdMode/posSide。

原生查询先用已知 id，其次用 Binance origClientOrderId / OKX clOrdId。
只有明确 OrderNotFound/NotSupported 才扫描历史；网络、鉴权和限频异常直接保持未知。
客户端号可能在交易所终态后重用，因此 client-only 匹配还必须有本意图之后的 UTC 创建时刻。
`open_intent_ms`/`cover_intent_ms` 与新意图同一 SQLite CAS 写入；旧行保持 null，
不会把本地无时区日期猜成 UTC。旧行有已知交易所 id 时仍可核验；缺时间的客户端号恢复需先人工核实。

- Binance USDT 永续：固定 6 日窗口（小于官方 7 日限制），每窗显式从正整数 orderId 开始、
  以最大 id+1 前进，每页最多 1000；不使用会默认取“最近一页”的无游标起步。
- OKX：pending 及 archive filled/canceled 三条只读路径，每页最多 100，以 after=最小 ordId 向更早记录前进。
  使用实际 CCXT 4.5.43 archive builder；不依赖不支持的通用 fetch_orders。
- 一次历史补查最多 32 页、最多回溯 90 日；这些是传输预算，不是交易所历史可见性的保证。
  保留期更短、空结果、重复/不前进游标、多单同客户端号或矛盾回报都维持未知，不能据此重下。

依据：[Binance All Orders](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/All-Orders)、
[OKX 订单 API](https://www.okx.com/docs-v5/en/)。上述请求和原生解析器均只在 fake I/O 中验证，未连真实账户。
部分平仓的剩余数量用固定 Decimal 计算后精确经过 DB 数值边界；无法表示则拒绝写入，
不向上补量，也不使用 epsilon 把小仓位抹成零。

#### C5 绑定成交 CAS 与终态管理（离线子边界）

实际 add/restore/partial-exit/poll 路径现以一次 SQL CAS 同时提交 server id、订单状态、
累计成交和仓位，不再先写 raw status 再写 fill。比较当前 client、尝试次数、server id 与关键账本快照；
其他连接已改行时保留赢家、重新查询，不把旧回报重算到后来尝试上。相同累计量不能改均价，
开仓重复回报不能恢复已经退出的仓位，迟到的 open 不能回绕已处理终态。
撤单/重试依据同一尝试的已应用 DB 状态，不用已被更晚证据淘汰的网络快照驱动订单。

新合约记录的底层 `apply_open_fill/apply_close_fill`、ACK 和兼容 submission API 必须显式携带
原 `client_order_id`、`order_id`、`expected_attempt`；ACK 的订单号仍是原有位置参数。
准备平仓后调用 `acquire_close_intent` 还须给准备时的 `previous_attempt`，首次为 0。
过期 snapshot 不能自动刷新成下一次平仓；即使客户端号被重用，查询期间的 attempt 切换也不能让旧 ACK 串单。
普通用户继续使用 `CTradeEngine` 入口，由它传递原意图；不要自行拼接或读取更新后的 counter 贴给旧报告。

旧无规格的股票/兼容 DB API 保留，但不作为新 crypto 认证。已有 `order_contract` 的记录禁用
`mark_open/mark_cover_order/mark_cover_done` 手工猜量接口。非有限/布尔成交均价、closed 与未完成请求量矛盾时拒绝记账和重试。
尚未写入 DB 的订单号只是查询提示，仍须通过 client echo 与 UTC 创建时间发现校验；有完整证据的提示号可正常恢复。

提交权的双进程争抢、成交的双 SQLite 连接确定性交错及原生 CCXT/fake I/O 验证均为离线证明，
不是完整交易所认证。区间核对/持久冻结与显式含费 paper 见下文；完整准入和进程级 E2E、C6/C7 仍待完成。

#### C5 追加式尝试历史（SQLite 离线子边界）

SQLite 增加 `chanpy_order_attempts` / `chanpy_order_events`，当前订单行仍是原有状态机的投影，
不是第二套撮合/生命周期。intent、claim、ACK、已应用累计回报与投影在同一事务提交；
追加失败则一同回滚，旧 close 槽覆盖前保存其真实可观察身份。客户端号在本库全部历史/阶段中唯一，
禁止重用；仍须传原 attempt，不能用新的历史接口把旧回报贴给当前订单。

`CChanDB.get_order_history(record_id)` 返回新解码的完整历史，重核 finite canonical 字节、SHA、
尝试内前序链、序号和当前投影；正常 UPDATE/DELETE/REPLACE 被只追加触发器拒绝。
新规格的单位/执行字段按白名单保留完整字节，未知字段只保留原规格 SHA 并明确
`contract_complete=false`，不复制任意错误响应/密钥/请求头。SHA 是本地完整性证据，不是交易所签名，
也不能证明被整体重写的数据库真实。查询使用短事务取得一致快照；有写者时可能等待或失败，不据此重下。

升级是同文件的原子、非破坏性建表/补列，不改写旧订单为“过去已授权”。建议部署前保留原库备份，
回退程序不会移除新增的历史表；旧版写者不维护历史，回退应先停写并保留库，不能新旧写者混跑。
同名异构表、缺失只追加触发器拒绝打开，不自动修复或删除。
真正旧库首次成功状态写入或覆盖前只保存 `legacy_snapshot`；未知 UTC、单位保持未知，
`gaps` 明示旧快照、缺少尝试或无法识别的旧单。无 client/counter 的旧单不造假身份；
`observed_ms` 只是本地观察时间，不是交易所成交时钟，也不用于推断资金费归属。
缺单位/执行证据仍遵守原有管理门禁。MySQL 未迁移/未认证，本次不扩张其支持范围。

这只是意图和已应用回报的历史，始终 `coverage=intents_and_applied_reports_only`、
`economics_complete=false`；订单均价不能代替逐笔实际 trade/fee/funding，缺费用不当 0。
观察区间现金流核对与持久冻结见下文；完整逐腿资金通道和模拟账户仍为后续 C5，真实测试网/实盘仍锁定。

#### C5 原生逐笔经济来源（离线子边界）

显式调用 `engine.sync_execution_facts(code, account_scope=..., start_ms=..., end_ms=...)`
可从已配置的非 dry-run 会话只读采集，再在 SQLite 同事务保存 `chanpy_execution_facts` 和
`chanpy_execution_scans`。本阶段仅用 fake 私有端点验证，**不是运行真实账户的授权**；
dry-run 不会创建真实会话，MySQL 尚未认证。`account_scope` 是稳定的非秘密调用者命名空间，
不是 API key、服务器 UID 或账户认证；`account_scope_verified=false`，不可据它释放风险。
SQLite 核心导入不需要 CCXT；显式真实来源采集仍需该既有可选依赖，缺包会清晰报错而不发请求。

来源使用 [Binance userTrades](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List)
和 [income](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Income-History)，
以及 [OKX fills/fills-history 与 bills-archive](https://my.okx.com/docs-v5/en/#order-book-trading-trade-get-transaction-details-last-3-months)。
原生 Binance qty 是币数，OKX fillSz 是张数；与合约大小一起精确转成双单位，保留 native_quantity_unit。
这是独立原生来源的单位边界，不从 COrderResult 的 rounded avg/filled 推导逐笔交易。
费用扣款/返佣有符号且保留原币，PnL 标明结算币，不偷偷做外币转换；缺 fee 不当 0。
数值按 50 位有界 Decimal 精确处理，非有限/超范围/需舍入时拒绝，不截尾。

调用窗口为 source timestamp 的 `[start_ms,end_ms)`。Binance 以最多 6 日窗口查询，满页继续二分，
不组合非法 fromId+time；单毫秒仍饱和即 unknown。OKX 近 3 日用 fills，较早用 fills-history，
分别以 billId 排他 after 分页；`ts` 是数据生成时间，不能代替 `fillTime`，缺成交时间保留 null。
OKX 成交/资金费也先读取目标窗口的邻接毫秒，再按每条 recent/archive lane 的 `[begin,end)` 本地过滤，避免依赖未明确的端点包含语义。
资金费保留原生 cash_delta；OKX 的 fee/wallet/position channels 独立保留，缺腿身份不猜分配。
每次来源扫描最多 128 个 GET、90 日传输上界，另有扫描前后两次账户身份 GET；
超界/游标停滞/来源冲突都失败；这些不是策略搜索参数，
也不保证交易所 3 个月保留期之外的数据可取。空页、导入成功均不证明资金费为零或账户完整。

`get_execution_facts(account_scope, code, venue=..., mode=...)` 读取已验证的去重事实，
`get_execution_scans(account_scope, code)` 重建原收据并核验 manifest→fact SHA、完整字段和单位。
同来源 ID 同值幂等、变值拒绝；OKX billId 跨 kind 全局唯一，Binance funding tranId 跨标的唯一。
只追加触发器与原子升级同前；取得写锁前冻结有限输入快照，调用者不能在校验后改写被发布内容。
扫描仅存摘要清单，避免每次重复存整批事实，失败不留半次导入。
不改当前订单/仓位，收据始终 `coverage=observed_execution_facts`、`economics_complete=false`。
SHA 不是服务器签名。新扫描的账户关联与历史 attempt 归属检查见下；
逐腿持仓/mark/钱包闭合、持久化新风险冻结和完整模拟账户仍待，现有净仓位接口不能替代双腿对账。
这两个来源流也不涵盖所有转账、转换、利息或强平附加费用；完整钱包对账必须另有流水证据，
不能把余额差猜成交易收益，或将 funding-only 列表当作全钱包现金流。

#### C5 扫描账户关联与历史尝试归属（离线子边界）

新 `sync_execution_facts` 在来源 GET 前后只读核对相同原生账户/环境；scan manifest v2 额外保存
这个观察及 UTC 边界，原 `chan-execution-scan-v1` 的内容、SHA 和 flags=false 不变。
复用现有只追加 scans 表，无新数据库表/迁移；facts 与关联在同一 SQLite 事务中首次发布。
相同 scope+venue+mode 已绑定后不能静默换账户/环境或新增无关联来源。
相同 scan/context 重复导入保留首次观察；旧 manifest v1 不允许事后补证，也不因同名 namespace 被新扫描认证。

- `db.get_execution_scan_account(scan_id)`：重新核验 source/fact/manifest 和 namespace，返回该扫描的原始关联，旧扫描返回 null；未知或损坏证据拒绝。
- `db.get_execution_ownership(scan_id)`：在同一 SQLite 快照读取关联和该标的完整历史 attempts，
  返回 `chan-execution-ownership-v1`，包含 source SHA、account context id、history SHA 和逐笔 records。
  按原账户/环境/market、服务器及已回显的客户端 id、历史 attempt、方向/leg、真实成交时间及精确数量匹配，
  不只看当前最后一个 close 槽。旧/外部订单、缺 ACK/成交时间、歧义、单位/指纹冲突或超请求量均明确 unowned，不能择优选一条。
- 缺 ACK 时不会从成交记录猜补 ACK/记账；仍须经过原来的查单恢复。资金费没有原生 leg 时明确 unallocated，不按净量摊给多空腿。

该报告只声明 `coverage=observed_scan_facts_only`、`economics_complete=false`。匹配到全部已观察成交、
空扫描或零条异常，都不证明未漏成交、钱包现金流完整、余额/mark/双腿闭合，不能释放新风险。
它不更新订单数量/PnL，也不是服务器签名、真实交易所认证或真实账户运行授权。

#### C5 独立账户级钱包与逐腿来源（离线子边界）

`engine.sync_wallet_cashflows(start_ms=..., end_ms=...)` 请求所有原生现金流类型和币种，
不使用 symbol/instrument/type/currency 过滤。Binance 使用 all-type income，唯一键为
`incomeType:tranId`；OKX 使用 trading-account bills-archive，唯一键为 billId，按排他 after 分页。
OKX 时间过滤在目标 `[start,end)` 外多读相邻毫秒，再本地严格过滤，避免依赖未明确的 begin/end 包含语义而漏掉首尾毫秒。
交易账户不等于 OKX 独立 funding account，不能把这份数据称为整个交易所账户资产。
保留原币、有符号 account/position cash delta、余额及原生 fee/pnl/interest 分量；
**分量已包含在原生余额变化中，不能再次相加记账**。未知流水类型保留原生字面值，不猜为交易收益。

`engine.sync_account_snapshot([code, ...])` 使用显式 market 单位以及原生 account/balance/positions
读取全部返回持仓。Binance 额外读取原生 symbol configuration 和 multi-assets mode；
long/short 不净额抹除，零仓位但有 isolated 资金的记录也保留。未提供或不支持的 market 持仓留在
`unsupported_positions`，不猜币数/张数；两平台统一输出双单位、方向、entry、mark、reported
unrealized/realized PnL（原生没有的仍为 null）、保证金、原币余额与来源时间。
OKX 的 totalEq 及 Binance multi-assets 总值明确为 USD，不当作 USDT；逐币资产不做暗中转换。
`update_ms` 是原生账户/持仓更新时间，不是 mark 生成时间，故 `mark_ms=null`；
两个 REST 响应也不宣称原子同一时刻。后续对账必须处理观察区间内的变化和未知字段。

这些调用在私有读取前后核对同一原生账户/环境，观察收据一律 `economics_complete=false`，
只代表 `observed_account_cashflows` 或 `observed_native_account`，不自动对账、解锁或下单。
钱包最多 128 次来源 GET、90 日传输上界，时间饱和/无进展/原生冲突均失败，另有前后身份 GET；
snapshot 使用 Binance 4 次或 OKX 2 次来源 GET，另有身份读取。空页、全字段相等均非外部认证。

SQLite 增加独立只追加 `chanpy_account_evidence`，`store_account_evidence(document)` 返回文档 SHA，
`get_account_evidence(evidence_id)` 重新核验 canonical 字节、完整来源/摘要、账户和列身份。
原生流水同 context/ID 变值拒绝，重复文档幂等；单表首次升级和发布失败均回滚，旧订单不补资产。
取得写锁前冻结输入，不在 DB 写锁内发网络请求。当前跨历史钱包文档校验成本、存储体积及限频延时
尚未做实际容量认证，C6/C7 需验证增量运行预算。MySQL disabled，dry-run 不创建真实会话。
来源接口本身不能用作放行证明；观察区间核对与冻结见下文，完整准入与含费模拟仍未完成。

#### C5 观察区间对账与持久新风险冻结（SQLite/fake 离线验收）

显式 `engine.reconcile_account_interval(before_id=..., after_id=..., wallet_ids=[...], execution_scan_ids=[...])`
使用原始持久来源 ID。引擎在 DB 写锁外先后核验当前原生账户/环境；
`CChanDB.reconcile_account(account_context=..., ...)` 在同一 SQLite 快照读取两端资产/持仓、
全类型钱包、已关联 scans、全部 trade-shaped 表的原 attempt 历史和当前数量，不能传入 passed 布尔值。

- 两个账户快照必须是无重叠观察区间。钱包及每个显式 market 的 execution windows 必须覆盖
  从第一观察开始到第二观察结束的完整整数毫秒窗口。覆盖仅指提供的来源窗口，不认证交易所无漏报。
  在任一快照区间内发生现金流/成交、缺窗口、缺资产、时钟不明/倒退、迟到来源、未终结订单、
  外部或 legacy 成交、unsupported position 等均不能匹配。不能用一个最终余额或净仓位放行。
- 逐币 `before cash + account_cash_delta = after cash`，不再次加 fee/pnl，也不将 position_cash_delta
  摊给多空腿；重叠来源按原生 ID 精确去重。原生 trade/funding 分量独立交叉检查，不能用调整最终余额掩盖分量冲突。
- 逐腿重建原生成交的 pooled basis、真实数量、已实现损益及 mark 未实现损益，核对 DB 两端和每 attempt 的增量；
  部分平仓不错误采用单条策略记录成本。`Fraction` 保留精确有理均价，输出 numerator/denominator 字符串，
  不继承调用者 Decimal context，不发明 epsilon 或交易所舍入公式；原生舍入差异明确报告，不能自动接受。
  Binance 独立 account/positionRisk、USDT 总值/资产明细也相互核对。
- [OKX positions 文档](https://my.okx.com/docs-v5/en/#trading-account-rest-api-get-positions) 的 position IMR/MMR
  及 notional 是 USD 口径，不当 USDT PnL 相加；USD 总值仅保留，不隐式换汇。
  非零 isolated-position 现金/余额通道、借贷/利息等尚未证明闭合时明确 incomplete。
  无原生 leg 的 funding 仍是 account-only；`mark_ms` 仍未知。原 source flags=false 不升级。

返回 `chan-account-check-v1`，文档 SHA 可供 `get_account_check(check_id)` 重新读取。
只追加 `chanpy_account_checks` 保存原始来源 ID、当时的已核历史/数量快照及确定性计算结果；旧快照要与
不可变 journal 前缀匹配，不随后来合法平仓被重写。缺文件/来源或历史损坏保存脱敏 incomplete，不默默消失；
发布失败整笔回滚并抛错。UPDATE/DELETE/REPLACE、缺 guard、损坏字节/列或关闭完整性 PRAGMA 均拒绝。

差异/incomplete 对 venue+mode+原生 typed identifier 形成**持久冻结**，跨连接、重启和自定义 trade table 生效；
不能靠 account_scope、路由 context id 或后续一次匹配清除。没有自动解冻/接受调用者“已修复”标志的接口。
新 swap v3 开仓的 prepare、intent/claim 同事务及最终 HTTP 前检查冻结；原账户可证明的取消/查单/降风险
仍保留既有候选/kill/账户门禁。claim 后出现冻结不会重置为 created 或重下；不能承诺撤回已经发送的网络请求。

`matched_observations` 只核对给定来源区间，**不是完整账户 PASS/准入**。
`get_account_risk_state(context)` 的 `admission_verified=false` 恒为 false；没有历史冻结也不等于通过鲜活对账。
调度仍需在 C6 串起强制的新鲜来源/失败阻断，不能把此 guard 当作跳过对账的通行证。
全历史检查重验的时延/存储容量、原生舍入与 isolated 通道、全账户 funding 分腿及 C6/C7 尚未完成。
摘要仅用于本地完整性检查，不是交易所签名或抗整库伪造证明；实际交易所/测试网/实盘未认证、未授权。

#### C5 显式经济核算 paper（软件 cross/lot，不是交易所等价撮合）

`Trade/LinearPaperAccount.py` 复用 C4 `CCryptoAccount`，而非另写手续费/权益公式。
仅在 dry-run 中显式提供 `CSimExchangeState(paper_account=...)` 启用；旧简化状态不能补造来源后升级。
只支持同一 venue 的 USDT linear swap，可有多个 symbol，`one_way/hedged` 明确指定；
不能跨 Binance/OKX 钱包共享 cross 保证金，也不猜未知 contractSize、步长或最小金额。

```python
from ModelStrategy.parameterEvaluate.crypto_account import CCryptoAccountConfig
from Trade.LinearPaperAccount import CLinearPaperAccount, verify_linear_paper_report
from Trade.CCXTTradeEngine import CCCXTTradeEngine, CSimExchangeState

# 仅为合成示例，不是 TESTUSDT 实际市场 metadata 或交易授权；db 是调用方的 SQLite CChanDB。
market = dict(exchange="binance", id="TESTUSDT", symbol="TEST/USDT:USDT", type="swap",
              base="TEST", quote="USDT", settle="USDT", contractSize="0.01",
              amount_step="1", price_tick="0.1", min_notional="1")
paper = CLinearPaperAccount(
    CCryptoAccountConfig(initial_equity="1000", leverage="3", taker_fee="0.001",
                        maker_fee="0.0002", taker_slippage="0.001"),
    markets=[market], position_mode="hedged", start_ms=1000)
state = CSimExchangeState(paper_account=paper)
engine = CCCXTTradeEngine(db, sim_state=state, ccxt_conf={"mode": "dry_run", "default_type": "swap"},
                         trade_conf={}, environ={}, push_msg=False)
engine.set_sim_quote(market["symbol"], at_ms=1001, bid="99.9", ask="100", mark_price="100")
# 继续使用 add_trade/cover_trade/restore，不直接改 DB 数量。
report = verify_linear_paper_report(engine.get_sim_account_report())
```

- 参数/市场/起始时钟/账户 seed、C4 evaluator、账户和撮合代码均冻结进身份；默认 seed 是新 UUID，
  可复现任务可显式传 `identity_seed`。seed 相同不等于原服务器状态存在；既有 DB 数量/在途订单不能
  与真实 fill lots 核对时拒绝新增风险，不据空内存重建一个“新有钱账户”。已知其他账户不能冒领原意图。
- `amount_step` 单位是张数，内部与 DB 始终币数。prepare 先向下精度化并检验 fee-after-margin；
  claim、ACK、累计报告、丢 ACK 的 client 查询、部分退出→撤单确认→剩余量新单，复用原状态机和 SQLite。
  不合法或非步长 fill plan 在 claim 前拒绝，不能把输入错误伪装成交易所拒单。
- `set_sim_quote` 必须带明确 UTC、bid/ask/mark；bid/ask 满足 tick，mark 独立。市价和每次新增 partial fill
  使用当时 quote 的不利侧、显式滑点与不利 tick 舍入，不沿用创建订单时的旧价。软件最小价格梯为一个正 tick，
  不产生零价退出；limit 不越限。resting/post-only 仅采用触价模型，post-only 即刻跨价拒绝，**不模拟 queue priority**。
- 费用立即入账，滑点只在实际成交价体现一次。`apply_sim_funding(code, at_ms=..., rate=..., mark_price=..., event_id=...)`
  需要同刻明确 quote/mark；只结算该时点之前的 lots，同 symbol/时点换 ID 不能重复收费。
  双腿 gross exposure、margin、mark UPnL 保留，不以净仓位为零抹除风险。
- 经济口径是 **C4 per-fill lot + record FIFO + software cross**：部分退出只能消耗原 record 的真实 lots，
  不吃掉另一策略/leg。它不是原生 pooled basis。COrderResult/旧 DB 均价仍是 binary64 API 编码，
  完整实际 fill 价格/费用/PnL 留在 Decimal50 账本；不得把舍入均价当原生精度证明。
- quote loss/funding 压力可进入 `liquidation_required`；不造强平价，不抹亏损，新风险拒绝，原记录真实减仓仍可入账。
  软件 reduce-only 可低于 min_notional，但仍必须符合币数/张数步长，不能用 epsilon 抹除小仓。非 Native 场景规则不冒称平台豁免。
- 报告保留有序 input effects、实际 C4 事件、现金流和完整快照；reader 按原 effect 顺序重放核验，不读取年度绩效，
  也不是独立经济公式或抗整份来源伪造证明。重复查询/恢复/资金费不重复记账，返回对象不回写原账本。

旧 `CSimExchangeState` 内存路径仍需原句柄，不能据此声称退出进程后可恢复。显式持久路径如下。

#### C6 单写入器持久 paper 与无需密钥的演练

```bash
python -m Trade.Script.PaperRehearsal --output <尚不存在的演示目录>
```

使用已有完整依赖，不下载行情，不读用户的交易配置/密钥，不连接交易所。
固定 seed 生成 1000 根 `DEMO/USDT:USDT` 合成小时 K，前 600 根通过真实策略/特征/样本 reader
训练 2 轮小 XGB；阈值为演示常量而非搜索结果。首个训练窗口后候选的前缀重建与在线喂入
完整评分证据逐字节一致后，才交给原 COpeningInputs 报价 v2 和 SQLite 意图/CAS。
三个串行新进程完成部分入场、恢复后 funding/部分退出、再次恢复完全退出；保存每阶段
`entry.json`、`exit.json`、`verify.json` 的原 effects/history，核验账户逐事件重放和重复恢复不重记费用。
盘口、mark、资金费和退出均是明确的合成事件，不冒称从 OHLCV 还原了真实盘口或成交概率。
只有全部通过才写有限 canonical `rehearsal.json`，其中 `candidate_authorized=false`、`exchange_certified=false`。
坏模型、配置变化、子进程失败或已有目录均拒绝；失败产物保留排查，不覆盖重试或清理用户文件。
这不是所有策略/周期、OKX、通知或默认调度壳的完整 E2E，更不是经济采用、测试网或实盘授权。

程序库可显式使用 `Trade.PaperState.CPersistentPaperState`：

```python
from Trade.PaperState import CPersistentPaperState

# db 已是实际 SQLite CChanDB；paper 由上方显式参数构造，且尚无 effects。
with CPersistentPaperState.create(server_path, account=paper, database=sqlite_path) as server:
    engine = CCCXTTradeEngine(db, sim_state=server.state,
        ccxt_conf={"mode": "dry_run", "default_type": "swap"}, trade_conf={}, environ={}, push_msg=False)
    # 使用原 set_sim_quote/add_trade/restore/cover_trade；返回前持久化。

# 之后在新进程打开原文件、原 SQLite 和相同代码/运行时，不重新 create。
with CPersistentPaperState.open(server_path, database=sqlite_path) as server:
    engine = CCCXTTradeEngine(db, sim_state=server.state,
        ccxt_conf={"mode": "dry_run", "default_type": "swap"}, trade_conf={}, environ={}, push_msg=False)
    engine.restore()  # 查原单/应用累计回报；未知订单不猜测重下。
```

检查点绑定实际服务器路径、store UUID、SQLite 文件身份、经济/撮合/codec/锁代码与 Python 版本；
原始订单、计划游标和账户 effects 经同一经济 restorer 复算，拒绝游标回退、无订单归属成交、
损坏/缺失文件、改内存以及落后于 DB 已确认记录的旧快照。v2 paper 意图保留原 store；
v1 内存历史不自动升级。代码/运行时变化须保留旧产物并评估迁移，不能重封摘要来冒称原服务器。
已有账户 effects 不允许当新服务器创建材料，关闭句柄不替未提交变异补保存。

服务器文件持 OS 生命周期锁；写操作及 close 共用互斥，另进程不能认领活动 writer。
临时兄弟文件 flush/fsync 后原子替换，接单必须在本地 ACK 前保存；保存失败令当前句柄闭锁，
重开原文件后再查原意图。真实子进程退出测试覆盖意图前后、接单未 ACK、部分成交、撤单未确认。
这只是同机、合作式单写入器的软件恢复，文件与 SQLite **没有全局原子事务**；不抗两个文件一起回滚/伪造，
不认证物理掉电、跨主机或恶意文件系统写入。全账本重验的容量/时延尚未认证。
并发撮合、queue/流动性、挂单保证金预占、原生 pooled/isolated/保险/强平与真实限频仍未认证；Goal 未完成。

#### 默认交易脚本使用同一软件 paper 服务器

`MakeOpenTrade`、`RestoreOrders`、`ClosePreErrorOpen`、`RealTimeTracker` 和 `RetradeCoverOrder`
现在共用 `Trade/Script/TradeRuntime.py` 的 context-managed 工厂。下列是**需自行填写的配置结构**，
不写入默认配置，也不会创建或替换原 server：

```yaml
trade:
  quote_max_age_ms: <last 报价允许年龄，正整数毫秒>
  paper:
    server_path: <已由 CPersistentPaperState.create 创建的原文件>
    quote_path: <当前软件行情文件>
    quote_max_age_ms: <bid/ask/mark 允许年龄，正整数毫秒>
  open_para:
    score_thred: null
    max_sl_rate: null
    max_profit_rate: null
    bsp_type_filter: null
```

同时需要显式 `ccxt.mode: dry_run`、`default_type: swap`、SQLite 和同源的 `offline_data.source_identity`。
profile 缺失/损坏或原 server 身份不匹配时不会回退成新内存账户。未声明 profile 的旧库调用仍兼容，
但旧简化模拟不是完整账户证明。显式 profile 的开仓/跟踪/后验只读内联 `trade.open_para`，
缺项是未启用该额外条件，不暗读仓库私有 `OpenConfig.yaml`；模型三个阶段阈值仍以部署清单为准。

软件行情是有限 canonical JSON（不是普通 pretty JSON）：

```python
payload = {
    "synthetic_only": True,
    "source": source_identity,
    "at_ms": explicit_utc_ms,
    "quotes": [{"symbol": symbol, "bid": "99.9", "ask": "100", "mark": "100", "last": 100.0}],
}
document = {"schema": "chan-software-paper-quotes-v1", "payload": payload,
            "payload_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest()}
```

生产者应为账户的**全部 market** 提供按 symbol 排序、无重复的行情；bid/ask/mark 为有限正数字符串，
盘口符合原 tick，mark 独立，last 为有限正数。这里只表达显式软件观察，不证明真实盘口或 mark 时钟。
生产者在各脚本运行前提供新文件/原子替换 `quote_path`，不得改 server 或交易库；receiver 不下载、
伪造或刷新报价。每个脚本冻结一次原批次，使用时复验文件、来源、账户报价及结束时钟，
行情变更/过期/缺失不产生新模拟 fill，已知累计回报与撤单仍可读取/执行；新减仓成交也须有有效报价。

这类新订单使用 `chan-paper-order-v3` 保存原 `software_quote_max_age_ms`，后续恢复/退出取历史与当前策略
更严格的上限；无 reader 的旧调用只能查已知状态，不能绕过该上限继续撮合。v1 内存/v2 持久历史不重标。
开仓 v2 输入证明携带独立 `chan-software-entry-quotes-v1`、`explicit_software_clock`、`synthetic_only=true`，
绝不将软件时钟伪称交易所 ticker 时间；非 paper guard/DB 意图拒绝它。原 native quote schema/bytes 保留。

原 SQL 机会键（code/level/方向/target K）对冻结信号贯穿整个生命周期，已开仓/已失效后不能因重跑再次下单。
SQLite 检查与插入共用原事务，已有冻结 bytes 必须完全相同才计 existed；观察时钟、评分或部署变化仍拒绝，
显式信号换代/重臂协议尚未完成。旧无冻结信号的 unwatch 后再插入行为保留，不当作新路径的证明。

`SignalMonitor` 的失效判断使用本轮实际交易级别、方向和 target K，不能因同目标出现反向候选而保留旧方向，
也不能用小时扫描使未扫描的 15m/其他级别失效。对同一 code，新增候选、原字节复用和失效清理共用原 SQLite
事务；任一候选冲突拒绝整批，回滚本批新记录，成功提交后才统计 added/existed/unwatched。原冻结证据不改写，
已有订单不重臂。MySQL 不据此宣称同等级原子发布认证；这也不是行情扫描与交易所发送的全局原子性证明。

管理 CLI 遇 unresolved/输入问题返回非零并释放 DB/store；确认终态的部分平仓撤单可继续减少剩余量，
未知/提交中的旧请求不能被重下。模型损坏阻断新开仓，但不要求原模型可读才能查询、撤销或减少原 paper 仓位。
原生非 dry-run 新风险仍然关闭。此 profile 只替换交易/报价路径，`RunTradeCycle` 的 OHLCV 更新阶段仍会调用
配置的更新器；完全无网络演练请用前面的 `PaperRehearsal`，不能把 profile 当作全局断网开关。
本轮默认整轮测试只 fake 公共更新传输，其余真实模型、SQLite、CLI 和新进程均实际执行。
Binance/OKX 的默认软件流程验证范围见下；它不是任何测试网/实盘认证。容量、外部通知送达、迁移及 C5–C7 其余项仍待。

#### Binance / OKX 默认软件流程的验收范围

同一份真实默认工作流断言已分别运行在明确 Binance 和 OKX 来源的新 SQLite/样本/小模型/部署上，
没有把 Binance 模型或清单改标签当作 OKX。每 venue 使用 1000 根合成小时 K、前 600 根形成样本和
2 轮小 XGB，实际策略/特征/评分、运行壳和 CLI 子进程均执行；只有公共 OHLCV 更新传输和演示时钟为 fake。
`PaperRehearsal` 独立入口仍是固定 Binance 合成演示，不暗加 venue/真实 symbol 或用户配置参数。

前述单币默认流程覆盖单 instrument、软件 one-way、contractSize=0.01（0.03 币=3 张）、部分入场 0.01→重启恢复 0.03、
相同观察重复仍只有原一张入场单，以及模型损坏后禁止新开仓、管理原仓位退出到零。逐阶段读取原订单历史无 gaps，
对完整 C4 账本重放、手续费和原 effects 前缀核对，不只看最终余额/数量。另一 venue 的报价即使重算 payload SHA
仍被拒绝，保持零新增 intent/订单和原账户字节；掉 reader/放宽原报价年龄也不推进成交。

双 venue 的 8 项真实默认流程在 CPython 3.11.15 和 3.14.2 都通过；较新 XGBoost 3.4.1 环境的
部署/输入/报价/评估绑定/账户/恢复/运行壳/历史适用组合 364 passed（6 条既有模型警告）。
这只是所列合成软件场景，不外推全部策略/多币组合/hedged、原生时钟/盘口/mark/资金费规则或真实交易所路由。
候选换代仍待确认；没有新 candidate、测试网或实盘授权。

#### 两市场共享软件账户的默认流程矩阵

新增 `tests/test_configured_paper_portfolio.py` 分别覆盖 Binance/OKX × one_way/hedged。
每 venue 从两个 symbol 的 1000 根合成小时 K、不同价格序列和前 600 根样本重新训练/发布模型池，
不重标旧模型；同一原 C4 cross 账户保存 contractSize=0.01/0.1、不同 tick、报价和逐记录 lots。
实际默认 CLI 两轮运行后，两市场部分成交均恢复到原请求量，仍各只有一张入场单。
显式软件 funding API 的正/负费率事件重启后不重复记账；只减第一市场不消耗第二市场 lots，
模型损坏后默认管理继续关闭剩余旧仓、不新增风险。完整账本/effects 前缀和无 gaps 的原历史逐阶段核验。
缺第二市场或重封重复市场的报价整批拒绝，两市场均零新 intent/订单，原账户不变。

这是 12 个固定软件场景，不是任意组合或同 symbol 同时多空腿的默认 CLI 完整覆盖；
资金费由明确合成事件注入，不代表已有自动 funding 调度或真实交易所费率/时序认证。
没有另写撮合/财务公式或修改生产配置，也未解除原生 fresh-admission 门禁。
CPython 3.14.2 适用组合 376 passed、3.11.15 新矩阵＋原部署 50 passed，既有模型告警保留。
当前多市场整轮使用 custom＋XGB，不外推全部策略/模型组合。执行证据见
[完整版进度台账](docs/superpowers/reports/2026-10-20-crypto-full-version-progress.md)。

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

### 版本化结构 API：当前视图与原发布证据分开

```python
legacy = chan.toJson()                  # 旧 level→klu/bi/seg/zs/bsp/cbsp 形状不变
assert legacy == chan.toJson(schema_version=1)
document = chan.toJson(schema_version=2)
assert document["schema"] == "chan-api-v2"
levels = document["payload"]["levels"]
```

只支持整数版本 1/2，不接受 bool/字符串或静默回退。两版所有输出都必须是有限 JSON；
NaN/Infinity/不可序列化字段抛 `CChanException`，不替换为字符串或 null。
v2 返回独立对象，修改返回值不改写通道/原事件；调用者须串行访问通道，不承诺跨线程原子快照。
不启动 Web 服务、行情更新、模型推理或交易。

v2 外层固定为 `schema/schema_version/payload/payload_sha256`。
`payload` 为 `code/level_order/structure_semantics/levels`，摘要是该完整 payload 的
UTF-8 canonical JSON（sort_keys=True、ensure_ascii=False、separators=(",", ":")、allow_nan=False）SHA256。
`level_order` 保留实际高→低级别顺序；所有索引仅在本 payload/对应级别内解析，不按日期字符串定位。

每级包含来源、观察水位及下列固定数组；无内容时为空数组：

| 数组 | 字段契约（公共快照标记之外） |
|---|---|
| `klu` | idx、显示 time、OHLC、trade_info、clock、source、klc_idx、parent/children `{level, klu_idx}` 引用 |
| `klc` | idx、dir、fx、low/high、klu_indices；分型是当前 KLC 状态，不另造历史分型事件 |
| `bi` | idx、dir、is_sure/used_to_be_sure、begin/end_klu_idx、begin/end_val、parent_seg_idx |
| `seg/segseg` | 同 line 字段，加 begin/end_line_idx 和 reason；seg 引用 bi，segseg 引用 seg |
| `zs/segzs` | begin/end_line_idx、begin/end_klu_idx、low/high/mid/peak_low/peak_high、is_sure、in/out_line_idx、sub_centers；分别引用 bi/seg |
| `bsp/segbsp` | klu_idx、显示 time、line_idx、is_buy、type、is_segbsp、features、relate_bsp1_klu_idx |
| `cbsp` | klu_idx、显示 time、方向/类型、open_price/sl_price/score/is_cover/profit/features、open_event_id、close_event_ids、close_actions `{price, quota, reason, klu_idx}` |
| `decisions` | ordinal、time_basis、available_at_ms、完整原 `chan-decision-v1` record（含 identity/event_id/payload/payload_sha256） |

除原始 `klu` 与原事件 `decisions` 外，各当前结构有 `snapshot_id`、
`availability="not_recorded"`、`available_at_ms=null`。`snapshot_id` 是 code/level、
本级来源状态及已知来源、kind/body 的内容摘要，不是一次历史发布事件，也不保证跨历史窗口全局唯一；
缓存/引用须同时携带 payload SHA。`is_sure`/`used_to_be_sure` 仅描述当前算法标志，
不能用端点时刻推算首次确认时间；当前结构可能随后续数据变化。`parent_seg_idx` 沿用原算法的
归属索引，末端未形成段时可能仅是候选位置，不应当作已有确认段。

来源状态为 `known/partial/unknown`；只有该级全部 KLU 声明同一合法来源才输出级别 `source`，
否则为 null，每根已知来源仍保留。任何级别间已知来源冲突、原事件与已知市场矛盾均拒绝；
不会为旧 CSV/股票/人工数据猜交易所。KLU clock 显式区分 `utc_closed_bar` 与 `legacy_unspecified`；
完整 UTC 周期记录 open_ms/close_ms/available_at_ms/is_final，非 final 不宣称可用；旧未声明时钟为 null。
仅本级所有 bar 的 UTC 时钟完整且 final 时，`observed_through_ms` 才是已记录 available_at_ms 的最大值，
它不是数据新鲜度或缺 K 认证。

`decisions` 保留原字节的解码内容与发布顺序，不从可变 cbsp 重新生成过去特征。
完整且对齐的 UTC 原 bar 时钟才允许 wrapper 的 `available_at_ms=identity.decision_ms`；
旧未声明时钟保留 `legacy_unspecified/null`，残缺 UTC 字段拒绝。重复/乱序、错误 code/level、
退出父事件/方向/市场不符、cbsp 与原事件链接不符、悬空/不互认的跨级引用和非法索引均拒绝。
无策略时 ledger 为空；自定义策略若缺少 `decision_records` 不能伪装成完整空 ledger。
这不是签名认证、全历史 cutoff 接口或订单/账户准入证明。

本次改动在现有模型绑定的 Chan/Common 代码范围内，旧模型/部署清单会被实际 reader 判为代码漂移；
须由新样本重生成模型并重新发布，不能修改旧契约摘要续用。C6 其余验收和 C7 外部认证仍未完成。

## A股与可选件

- A股研究:`DATA_SRC.BAO_STOCK`(联网)或 `OfflineData/bao_download.py` 落地后离线;GUI 见 `App/ashare_bsp_scanner_gui.py`
- futu 引擎/行情、pytdx、akshare、minio/腾讯COS 均为可选件,未安装时给出明确提示,不影响主流程
- `OfflineData/stockInfo/`(A股市值/交易信息缓存)未实现,选股市值过滤可用 `DataAPI/MarketValueFilter.py`
