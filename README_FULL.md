# chan.py 完整版使用文档

本仓库 fork 自 [Vespa314/chan.py](https://github.com/Vespa314/chan.py)(MIT)。原开源版只包含"静态缠论计算"部分(约 7200 行),`README.md` 却是按作者私有完整版写的。本 fork **按 README 描述的功能规格自研补齐了全部缺失模块**:cbsp 策略框架、特征引擎(500+ 特征)、模型训练/评估/AutoML、ccxt 数据层与 7×24 加密货币交易系统。

- 原版 `README.md`:功能与接口的完整说明(本仓库已全部对齐实现)
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

首次全量(2017 至今约 8 万根 1h),之后每次只拉新增。已有本地 csv 历史数据可先灌库:

```python
from OfflineData.offline_data_util import CKLineDB, import_csv
from Common.CEnum import KL_TYPE
with CKLineDB() as db:
    import_csv(db, "BTC/USDT", KL_TYPE.K_60M, r"C:\chanpy\data\btc\btc_1h.csv")
```

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
bash Trade/Script/run_train_pipeline.sh    # Windows: pwsh Trade/Script/run_train_pipeline.ps1
```

等价的 python 流程:

```python
# 1) 回测落样本(libsvm + feature.meta + 五种标签,兼容 demo5 格式)
from ModelStrategy.BacktestChanConfig import CBacktestConfig
from ModelStrategy.backtest import run_backtest
res = run_backtest(CBacktestConfig(code_list=["BTC/USDT"], data_src="custom:OfflineDataAPI.CStockFileReader",
                                   lv_list=[KL_TYPE.K_60M], chan_config={...}, output_dir="./bt_out"))

# 2) 训练(XGB/LGBM/MLP 三选一,自动打印 AUC)
from ModelStrategy.models.Xgboost.XGBTrainModelGenerator import CXGBTrainModelGenerator
gen = CXGBTrainModelGenerator(model_tag="btc", is_buy=True)
gen.trainProcess("./bt_out")

# 3) 模型接入实时打分(score_thred 过滤低分 cbsp)
from ChanModel.XGBModel import CXGBModel
config = CChanConfig({"cbsp_strategy": CCustomStrategy,
                      "model": CXGBModel(gen.GetModelPath()), "score_thred": 0.6})

# 4) 策略评估 + AutoML 搜参(贝叶斯/网格/PBT)→ OpenConfig.yaml
from ModelStrategy.parameterEvaluate.eval_strategy import CEvalConfig, eval_strategy
from ModelStrategy.parameterEvaluate.para_automl import CParaAutoML
from ModelStrategy.parameterEvaluate.parse_automl_result import parse_automl_result
```

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

### 5. 7×24 交易例行(dry-run 起步)

`config.yaml` 不配置 `ccxt.api_key` 时,交易引擎自动进入 **dry-run 模拟撮合**(内存持仓,订单即时成交),可先完整演练;配置密钥 + `testnet: true` 走交易所测试网;确认无误后再上实盘。

```bash
# 单轮例行:更新数据→信号入库→突破开仓→后验→跟踪止损止盈(可放任务计划每小时跑)
bash Trade/Script/update_data_signal.sh    # Windows: pwsh Trade/Script/update_data_signal.ps1
```

信号生命周期(库表见 `Trade/SqliteDB.py`,与 README 的 SQL 一致):

```
signal → watching → open(突破+分数达标) → tracking(峰值/止损/止盈) → cover(平仓,记 reason)
                 ↘ unwatch(失效/被过滤,记 reason)
```

崩溃重启后 `CTradeEngine.restore()` 从 DB 恢复现场,不会重复开仓。

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
| `ChanModel/` | FeatureDesc 注册表、FeatureEngine 11特征族(540+,含SMC族)、CCommModel/CXGBModel |
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

一致性是最高验收:同一批K线,一次性 load 与 trigger_load 逐根投喂,笔/段/中枢/bsp/cbsp/特征值完全一致(见 `tests/test_consistency.py`、`tests/test_m7_final.py`);特征引擎防未来函数由该机制保证。

## A股与可选件

- A股研究:`DATA_SRC.BAO_STOCK`(联网)或 `OfflineData/bao_download.py` 落地后离线;GUI 见 `App/ashare_bsp_scanner_gui.py`
- futu 引擎/行情、pytdx、akshare、minio/腾讯COS 均为可选件,未安装时给出明确提示,不影响主流程
- `OfflineData/stockInfo/`(A股市值/交易信息缓存)未实现,选股市值过滤可用 `DataAPI/MarketValueFilter.py`
