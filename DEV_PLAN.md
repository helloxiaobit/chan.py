# chan.py 完整版开发计划(交接文档)

> 本文档由前期分析会话产出,供本地 Claude Code 接手开发使用。
> 配套文件:`CLAUDE.md`(项目级指令,Claude Code 自动加载)。
>
> **启动方式**:在仓库根目录运行 `claude`,然后说:"阅读 DEV_PLAN.md,从里程碑 M0 开始实施,每个里程碑完成后运行验收测试并单独 commit。"

---

## 0. 背景与目标

- 本仓库 fork 自 [Vespa314/chan.py](https://github.com/Vespa314/chan.py)(MIT 协议),供 fork 所有者自用。
- 原作者完整版约 22000 行,**开源版只放出约 7200 行的"静态计算"部分**;README.md 是按完整版写的,其中大量模块在仓库中并不存在(quick_guide.md 才对应开源版)。
- **本项目目标:按 README 描述的完整版功能规格,自研实现全部缺失模块**(不是获取原作者私有代码,是基于公开文档的重新实现,MIT 许可下合法合规)。
- **用户使用场景(优先级最高)**:加密货币 ccxt 实盘(Binance/OKX 等),7×24 运行;同时保留 A股(baostock/akshare)研究能力。原版的 Futu 交易引擎做成可选件即可,不必优先。
- 运行环境:python 3.11+,Windows 本地(注意路径分隔符,避免 hardcode `/`)。
- fork 相对上游的自有改动:`App/ashare_bsp_scanner_gui.py`(A股买点扫描器 GUI)及两个相关 commit,**开发时不得破坏**。

## 1. 现状盘点(开源版已有什么)

| 模块 | 文件 | 状态与要点 |
|---|---|---|
| 主入口 | `Chan.py` | CChan:`load/step_load/trigger_load/get_latest_bsp/chan_dump_pickle`。**缺** README 里的 `extra_kl` 参数与 `toJson()`;无 cbsp 策略调度 |
| 配置 | `ChanConfig.py` | 只有笔/段/中枢/bsp/指标配置。`ConfigWithCheck` 对未知 key 直接抛异常 → README 里完整版参数(model/cbsp_strategy/od_* 等)现在传入会报错 |
| 笔/段/中枢 | `Bi/ Seg/ ZS/` | 完整。`Seg/SegListComm.py` 是全项目最复杂文件,作者原话"不敢改",**禁止改动** |
| K线 | `KLine/` | `CKLine_List.cal_seg_and_zs()` 是每根K线后的统一计算入口(段→中枢→segseg→segzs→segbsp→bsp);`add_single_klu` 增量更新;`KLine_Unit.set_metric()` 是指标挂载点 |
| 买卖点 | `BuySellPoint/` | bsp 全类型(1,1p,2,2s,3a,3b)+线段买卖点均已实现;`CBS_Point.features` 已有(仅 1 个默认特征 bsp_bi_amp);**缺** `qjt_type()`(区间套) |
| 特征 | `ChanModel/Features.py` | 仅 CFeatures 字典容器,**缺** CommModel/FeatureDesc/XGBModel 及一切特征计算 |
| 数据 | `DataAPI/` | BaoStock/Akshare/csv/ccxt。**ccxt.py 很弱**:binance 硬编码、单次 fetch(≤1000根)不分页、丢弃成交量、无代理/限频/end_date 处理 |
| 指标 | `Math/` | MACD/BOLL/Demark/KDJ/RSI/TrendModel/TrendLine 全有,均为增量计算风格。**缺** OutlinerDetection(离群点) |
| 画图 | `Plot/` | matplotlib 静态+动画;`PlotDriver.DrawElement` 是绘制分发点(239行起)。**缺** draw_cbsp、CosApi |
| Demo | `Debug/strategy_demo1-6.py` | demo5/6 已演示"bsp特征→libsvm样本→XGB训练→实盘对齐预测"的最小闭环,**是 ModelStrategy 模块的种子代码,新框架的样本格式(libsvm+feature.meta)应与其兼容** |
| 通用 | `Common/` | CEnum/CTime/cache(make_cache 增量缓存装饰器)/func_util/ChanException。**缺** send_msg_cmd/tools/CommonThred/TradeUtil |
| 依赖 | `Script/requirements.txt` | 仅 baostock/ipython/matplotlib/numpy/pandas/requests |

完全缺失的顶层模块:`Config/`、`CustomBuySellPoint/`、`ModelStrategy/`、`Trade/`、`OfflineData/`、`ExamGenerator.py`、`DataAPI/SnapshotAPI/`。

## 2. 差距清单与接口规范(按 README 逐模块)

以下接口签名均摘自 README(完整版文档),实现时保持一致,保证 README 即用户手册。

### 2.1 Config/(全局配置体系)
```
Config/EnvConfig.py    # Env 类:读取 config.yaml,提供各模块配置访问
Config/config.yaml     # demo 配置(用户复制修改)
Config/config.sh       # shell 读取配置(调度脚本用;Windows 下提供 config.ps1 或跳过)
```
config.yaml 建议字段:`db`(type: sqlite/mysql + 连接参数/文件路径)、`offline_data`(数据根目录)、`snapshot_engine`(sina/futu/pytdx/ak/ccxt)、`notify`(telegram/dingtalk/email/gotify 的 token 等)、`ccxt`(exchange/api_key/secret/proxy/testnet)、`futu`(host/port,可选)、`cos`(可选)、`model`(模型文件目录)。所有含密钥文件加入 `.gitignore`,提供 `config_demo.yaml`。

### 2.2 CustomBuySellPoint/(动力学买卖点 cbsp,核心)
```
Strategy.py        # CStrategy 抽象父类
CustomStrategy.py  # CCustomStrategy demo策略1(README 配置示例所用)
SegBspStrategy.py  # CSegBspStrategy demo策略2
ExamStrategy.py    # 试题策略(cbsp分形完成即输出)
CustomBSP.py       # CCustomBSP:自定义买卖点
Signal.py          # CSignal:信号类
```
CStrategy 子类需实现(README 原文):
```python
def try_open(self, chan: CChan, lv: int) -> Optional[CCustomBSP]   # 判断当下是否开仓
def try_close(self, chan: CChan, lv: int) -> None                  # 对已开仓未平仓的 cbsp 决定是否平仓,平仓调 CCustomBSP.do_close(price, close_klu, reason, quota=None)
def bsp_signal(self, chan: CChan, lv: int) -> List[CSignal]        # 实盘信号(供 SignalMonitor 落库)
```
框架侧 `CStrategy.update(chan, lv)` 每根新K线被调用,内部调 try_open/try_close;策略实例持有 `cbsp_lst`,支持迭代(README 区间套示例中有 `for sub_bsp in sub_lv_data.cbsp_strategy`)与 `features` 访问。
CCustomBSP 关键成员:关联 bsp、klu、bs_type、is_buy、target_klc(突破目标)、open_price、sl_price(止损)、profit、is_open/is_cover、do_close()。
strategy_para 支持:`strict_open/use_qjt/short_shelling/judge_on_close/max_sl_rate/max_profit_rate`(默认 True/True/True/True/None/None)。
区间套(use_qjt):README「区间套策略示例」有 20 行参考实现,依赖 `chan[lv+1]`、`klu.sup_kl`、`CBS_Point.qjt_type()`(需在 BS_Point.py 补一个方法,返回区间套买卖点类型标记)。

### 2.3 CChanConfig 参数补齐(在 `conf.check()` 之前消费,否则抛 unknown para)
- 模型:`model`(默认 None)、`score_thred`(None)、`cal_feature`(False;model 或 cbsp_strategy 开启时强制 True)
- 策略:`cbsp_strategy`(None)、`strategy_para`({})、`only_judge_last`(False,海量选股加速)、`cal_cover`(True)、`cbsp_check_active`(True)、`print_inactive_reason`(False)、`stock_no_active_day`(30)、`stock_no_active_thred`(3)、`stock_distinct_price_thred`(25)
- 离群点:`od_win_width`(100)、`od_mean_thred`(3.0)、`od_max_zero_cnt`(None)、`od_skip_zero`(True)
- 精确后缀:现有 `-buy/-sell/-segbuy/-segsell/-seg` 机制需额外覆盖 `score_thred`、`strategy_para`(README「精确设置配置」列表)
- 注意:`print_err_time` 开源版默认 True 而 README 说 False、`gap_as_kl` 开源默认 False 而 README 说 True——保持开源版现状,不要为对齐文档改默认值

### 2.4 CChan 集成
- `__init__` 增加 `extra_kl=None` 参数(list → 单级别;dict{KL_TYPE: [CKLine_Unit]} → 多级别;作为额外 iter 挂到 `add_lv_iter`,用于离线数据+当日实时K线拼接)
- cbsp 调度:`do_init()` 时若 `conf.cbsp_strategy` 非 None,为每个级别实例化策略挂到 `CKLine_List.cbsp_strategy`;`load_iterator` 中每根K线完成(含次级别递归完成)后、以及 `trigger_load` 尾部,调用 `strategy.update(self, lv)`(从最低级别往最高级别,保证区间套拿到次级别最新状态)
- `toJson()`:输出各级别 klu/bi/seg/zs/bsp/cbsp 的 dict(服务化接口)
- `only_judge_last` 为 True 时的快速路径:只在最后一根K线做策略判断

### 2.5 ChanModel/(模型接入层)
```
CommModel.py    # CCommModel 抽象:__init__(path)->load(path); predict(cbsp)->float(读 cbsp.features 构造输入)
FeatureDesc.py  # 特征注册表:名称→描述/分组;提供"回测后列出未注册特征"的检查入口
XGBModel.py     # CXGBModel demo:加载 model.json + feature.meta(与 Debug/strategy_demo6.py 的 predict_bsp 逻辑一致)
Features.py     # 已有 CFeatures,保持兼容,可加 to_vector(meta) 工具方法
```
接入点:`score_thred` 配合 `CChanConfig.model`,在策略 try_open 产出 cbsp 时打分,低于阈值丢弃;分数存到 cbsp 上(画图/入库用)。

### 2.6 特征引擎(目标 500+ 特征)
所有特征在 bsp/cbsp 生成路径中计算并 `add_feat`,**只允许使用 bsp.klu 及其之前的数据(防未来函数)**。按特征族实现,每族一个函数,注册到 FeatureDesc:
1. 笔族:当前/前1/前2/前3笔的 amp/涨跌幅/K线数/klu数/斜率/MACD各算法值(peak/area/full_area/diff/slope/amp) × 买卖方向
2. 线段族:所在线段方向/笔数/amp/斜率/是否 is_sure/线段内位置比例;segseg 同理
3. 中枢族:最近N个中枢的高低区间/宽度/笔数/与当前价距离比;进出中枢笔的 MACD 比(背驰率本值);中枢个数(min_zs_cnt 相关)
4. 背驰族:divergence_rate 实际值、各 macd_algo 下的背驰比、MACD 回抽零轴计数
5. 买卖点族:bsp 类型 one-hot(1/1p/2/2s/3a/3b)、是否 segbsp、relate_bsp1 距离(K线数/涨跌幅)
6. K线族:开仓K线 open_klu_rate(demo5 已有)、上下影线比、近N日振幅/波动率、跳空缺口、limit_flag
7. 指标族:MACD(DIF/DEA/柱值/零轴位置)、BOLL(价格相对上中下轨位置)、RSI、KDJ、Demark(setup/countdown 值)、均线(mean_metrics 各周期价格偏离比)、通道(trend_metrics 上下轨距离)
8. 量能族:volume/turnover/turnrate 的近N笔均值比、离群点分数(OutlinerDetection)
9. 多级别族:次级别最近 bsp 类型/背驰率/中枢数(区间套强度)、父级别方向
10. 时间族:距上一同向 bsp 的K线数、笔持续时间
命名规范:`{族}_{对象}_{指标}`,如 `bi_pre1_macd_peak`、`zs_cnt_before_bsp`。数量靠"对象×指标×回看窗口"组合达成,宁多勿漏,模型侧自会筛选。

### 2.7 ModelStrategy/(训练/回测/评估/AutoML)
```
BacktestChanConfig.py   # 回测配置(股票池/时间段/级别/CChanConfig)
backtest.py             # 回放(trigger_step 或逐根 trigger_load)全池股票,产出特征样本文件(libsvm+meta,兼容 demo5 格式)与 label
FeatureReconciliation.py# 离线在线特征一致性校验(同一 code 两种模式跑,比对特征值)
ModelGenerator.py       # CModelGenerator 抽象父类 + CDataSet 抽象
models/Xgboost/XGBTrainModelGenerator.py + xgb_util.py + train_all_model.sh
models/lightGBM/LGBMModelGenerator.py + train_all_model.sh
models/deepModel/MLPModelGenerator.py + train_all_model.sh   # MLP 用 sklearn.MLPClassifier 实现,torch 可选
parameterEvaluate/eval_strategy.py        # 策略离线收益评估:输入(阈值/止盈止损/bsp类型过滤/股票池/时段),输出盈亏比/交易次数/最大回撤/平均收益/持仓成本/各票明细
parameterEvaluate/para_automl.py          # AutoML:贝叶斯(optuna)/PBT/暴力网格三种;参数空间+初始值+CalScore(eval_res) 打分函数
parameterEvaluate/parse_automl_result.py  # 最优参数 → Trade/Script/OpenConfig.yaml
parameterEvaluate/automl_verify.py, multi_cycle_test.py
```
CModelGenerator 六个抽象方法(README 原文):`train(train_set, test_set)`、`create_train_test_set(sample_iter)`、`save_model()`、`load_model()->int`、`predict(dataSet)->List[float]`、`create_data_set(feature_arr)->CDataSet`;外部接口:`trainProcess()`(按 is_buy/market/bsp_type 分桶训练+评估AUC)、`PredictProcess()`、`predictAllProcess()`。
CDataSet 三个抽象方法:`get_count/get_pos_count/get_label`,成员 data/tag。
label 体系(README"五种不同的标签",自研定义如下,均只用未来数据打标、训练用,不进特征):
1. `label_bsp_hold`:该位置最终仍是形态学 bsp(demo5 的 label,回放结束后校验)
2. `label_ret_N`:开仓后 N 根K线收益率是否 > x%(N,x 可配)
3. `label_next_bsp`:到下一个反向 bsp 出现时的收益率符号
4. `label_max_drawdown`:开仓后触及止损线(如 -y%)之前是否先达到 +x%
5. `label_seg_confirm`:所在线段方向最终被确认(is_sure)且未被反向破坏

### 2.8 Trade/(交易系统;ccxt 为第一优先)
```
db_util.py         # CChanDB():无参构造,自动读 config.yaml;封装信号/开仓/平仓/止损的增删改查
SqliteDB.py        # 默认后端(文件路径来自 config)
MysqlDB.py         # pymysql 实现,可选
TradeEngine.py     # CTradeEngine(market, chan_db):频控/交易时段判断 wait4MarketOpen(crypto 直通)/现场恢复/add_trade(trade_info, price)/平仓单/订单微调/轮询/推送
CCXTTradeEngine.py # 【新增,重点】ccxt 下单引擎:market/limit 下单、撤单、查余额持仓、testnet(set_sandbox_mode)、精度对齐(amount_to_precision)、restore 现场恢复
FutuTradeEngine.py # futu-api 可选依赖(import 失败给出提示即可,不必测试)
OpenQuotaGen.py    # COpenQuotaGen 仓位控制抽象;内置 bench_price_func(README 示例:凑最小手数使金额≥bench_price;crypto 按名义金额)
Script/
  StaticsChanConfig.py   # 线上缠论计算配置(单一来源)
  SignalMonitor.py       # 例行:全池计算 bsp_signal → 信号入库/失效清理/推送统计
  MakeOpenTrade.py       # 检查信号突破(实时价 Snapshot)→模型分数校验→开仓
  CheckOpenScore.py      # 后验:K线完成后复查突破与分数(model_score_after)
  ClosePreErrorOpen.py   # 修复错误开仓(open_err 记录尽快平)
  RealTimeTracker.py     # 实时跟踪止损/止盈/平仓 cbsp
  UpdatePeakPrice.py     # 峰值价更新(动态止损)
  RetradeCoverOrder.py   # 修复未成交平仓单
  OpenConfig.py + OpenConfig_demo.yaml  # 开仓参数(阈值/止损/bsp类型过滤等,automl 产物)
  update_data_signal.sh + run_train_pipeline.sh  # 调度脚本(附 Windows .ps1 版)
```
交易表结构:README「交易后端数据库」章节给出完整 SQL(id/add_date/stock_code/status/lv/bstype/is_buy/open_thred/sl_thred/target_klu_time/watching/model_score_before/after/is_open/open_price/quota/open_order_id/peak_price_after_open/cover_avg_price/cover_date/cover_reason/open_err/close_err/relate_cover_id/is_cover_record 等),照抄建表,sqlite/mysql 各写一份方言。
信号生命周期状态机:`signal → watching → open(突破+分数达标) → tracking(峰值/止损/止盈) → cover(平仓, 记 reason)`,任何环节可 `unwatch(记 reason)`;崩溃重启后从 DB 恢复现场,不重复开仓。

### 2.9 DataAPI 补齐
- `ccxt.py` 重构:exchange 可配置(config.yaml,默认 binance)、**since 分页循环拉全量**、写入 FIELD_VOLUME(ohlcv[5])、支持 end_date、`enableRateLimit=True`、代理配置、KL_TYPE 映射扩到 1m/3m/5m/15m/30m/1h/1d/1w/1M
- `OfflineDataAPI.py`:`CStockFileReader`(README data_src="custom:OfflineDataAPI.CStockFileReader")读本地落地数据(csv 或 sqlite)
- `ETFStockAPI.py`、`MarketValueFilter.py`(A股用,低优先)
- `FutuAPI.py`(可选依赖)
- `SnapshotAPI/`:`StockSnapshotAPI.priceQuery(codelist, engine, return_klu)` 分发;CommSnapshot 父类 + Sina/Pytdx/AkShare/Futu + **CCXTSnapshot(新增:fetch_tickers 批量)**;各类实现 `query(code_list, return_klu) -> Dict[code, CKLine_Unit|Dict|None]`(README 有精确规范)

### 2.10 OfflineData/(离线数据更新)
- `offline_data_util.py`(通用:增量合并/复权处理/存储层)、`bao_download.py`、`bao_update.py`、`ak_update.py`、`etf_download.py`、`futu_download.py`(可选)
- **`ccxt_update.py`(新增,重点)**:按 exchange+symbol+timeframe 增量拉取落 sqlite(表:symbol/lv/ts/o/h/l/c/v,唯一索引 symbol+lv+ts)
- `download_all_offline_data.sh`(+.ps1)、`stockInfo/`(CalTradeInfo/query_marketvalue,A股用,低优先)

### 2.11 其余
- `Math/OutlinerDetection.py`:滑窗均值离群检测(od_* 四参数),挂到 TradeInfo 指标;画图 tradeinfo 的 plot_outliner 已留了参数位
- `Common/send_msg_cmd.py`:统一 `send_msg(title, content, level, image_path=None)`,后端 Telegram(优先)/钉钉/企业微信/邮件/gotify,由 config.yaml 决定;`tools.py/CommonThred.py/TradeUtil.py` 按需最小实现
- `Plot/PlotDriver.py`:`DrawElement` 注册 `plot_cbsp → draw_cbsp`(虚线箭头、√标记、plot_cover 平仓连线、show_profit 收益率、only_segbsp、adjust_text);`PlotMeta` 增加 cbsp 元数据;`Plot/CosApi/`(minio/腾讯cos,可选)+ `CPlotDriver.Upload2COS(path=None)`
- `ExamGenerator.py`:CQuestion(area, begin_time, kl_type, _config) + QuestionGenerator(is_buy)/PlotTestFigure/PlotAnswerFigure(随机选股出题,基于 ExamStrategy)

## 3. 里程碑(每个独立可验收,建议在 feature 分支 `full-version` 上逐个 commit)

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| M0 | Config/ 体系、requirements 分层(base/full)、pytest 骨架 + 合成K线 fixture、tests/ 目录 | `pytest` 绿;`python main.py` 不回归 |
| M1 | CChanConfig 全参数 + CustomBuySellPoint/ 全模块 + CChan 调度 + BS_Point.qjt_type + Plot cbsp | demo 用 CCustomStrategy 跑 sz.000001(csv 离线数据),产出 cbsp 并画图含虚线箭头;strict_open/use_qjt/short_shelling 各开关生效 |
| M2 | 特征引擎(FeatureDesc + 10 特征族)+ OutlinerDetection + backtest.py 样本落地 | 单票回测产出 libsvm+meta,特征数 ≥500;FeatureDesc 检查无未注册特征 |
| M3 | ModelGenerator/CDataSet + XGB/LGBM/MLP 三个 Generator + CCommModel/CXGBModel 接入 | trainProcess 训练出模型(AUC 打印),CChanConfig.model+score_thred 生效过滤 cbsp;与 demo5/6 流程兼容 |
| M4 | eval_strategy + para_automl(optuna贝叶斯/网格/PBT) + parse_automl_result | demo 策略回测报告(盈亏比/回撤/胜率);一次小规模 automl 搜索产出 OpenConfig.yaml |
| M5 | ccxt.py 重构 + ccxt_update.py + OfflineDataAPI + SnapshotAPI(含 CCXTSnapshot) | BTC/USDT 1h 全历史增量更新到 sqlite;离线读取跑通缠论计算;断网时给出清晰报错 |
| M6 | CChanDB + 双后端 + TradeEngine + CCXTTradeEngine + Trade/Script 全套 + send_msg_cmd | testnet(或 dry-run 模拟撮合)完整走一遍:信号入库→突破→开仓→跟踪→止损平仓,DB 记录完整,重启恢复现场不重复开仓 |
| M7 | FeatureReconciliation + ExamGenerator + CosApi(可选) + 全量一致性测试 + README_FULL.md 使用文档 | 一致性测试绿(见 §4);文档含 crypto 快速上手 |

## 4. 测试与质量要求

1. **计算一致性**(quick_guide「一致性」章节):同一批K线,`一次性 load` vs `trigger_load 逐根投喂`,最终笔/段/中枢/bsp/cbsp 必须完全一致 → 写成 pytest 用例(用 csv fixture)
2. **防未来函数**:特征/策略只能使用当前 klu 及之前数据;label 只在回测打标时用未来数据
3. **回归**:`main.py`、`Debug/strategy_demo1-6.py`、`App/ashare_bsp_scanner_gui.py`(至少 import 与启动不崩)全部可跑
4. 新增重依赖全部**懒加载**(函数内 import:ccxt/xgboost/lightgbm/optuna/futu_api/pymysql),保证核心缠论计算零新增依赖
5. 网络类功能(ccxt/akshare/baostock)测试需可离线跳过(pytest mark)

## 5. 编码规范(与现有代码保持一致)

- 类名 `C` 前缀(CChan/CStrategy/CCustomBSP...);枚举全大写加入 `Common/CEnum.py`
- 异常统一 `CChanException + ErrCode`(新增错误码续在 CEnum/ChanException 后)
- 类型注解风格与现有一致(`List/Dict/Optional`);中文注释
- 增量计算优先(参考 Math/ 各指标),必要时用 `Common/cache.py` 的 make_cache
- **不改** `Seg/SegListComm.py` 及其子类的段算法逻辑;不改既有默认值
- 配置一律走 CChanConfig / config.yaml,禁止 hardcode 路径与密钥

## 6. 参考锚点(省去重找)

- 完整版功能总览:README §功能介绍;目录结构:README §目录结构(即本计划的文件清单来源)
- CChanConfig 全参数说明:README §CChanConfig 配置;策略参数:§自定义策略类相关
- cbsp/策略接口:README §cbsp 买卖点策略;区间套 20 行示例:§区间套策略示例
- 模型三件套:README §模型类(CModelGenerator/CDataSet/CCommModel 抽象原文)
- 交易表 SQL 原文:README §交易后端数据库;引擎能力:§交易引擎;流程:§典型流程
- Snapshot 规范:README §实时数据接入;数据接入:quick_guide §数据接入速成班
- ML 最小闭环参考实现:`Debug/strategy_demo5.py`(训练)/`strategy_demo6.py`(实盘对齐预测)
