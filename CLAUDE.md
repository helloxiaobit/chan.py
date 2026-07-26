# CLAUDE.md

本仓库是 [Vespa314/chan.py](https://github.com/Vespa314/chan.py)(缠论量化框架,MIT)的 fork,目标是**按 README 描述的完整版规格,自研补齐开源版缺失的全部模块**(策略/特征/模型/AutoML/交易引擎/数据库等)。总体开发计划、差距清单、接口规范、里程碑与验收标准见 **`DEV_PLAN.md`**,一切开发以它为准。

## 关键背景

- `README.md` 是原作者**完整版**的文档,仓库里很多它提到的文件并不存在(那就是要补齐的部分);`quick_guide.md` 才对应开源版现状。
- 用户实盘场景:**加密货币 ccxt(Binance/OKX)**,7×24;A股(baostock/akshare)仅作研究。Futu 相关做成可选依赖,不必测试。
- 运行环境:python 3.11+,Windows(不要 hardcode `/` 路径;调度脚本 .sh 需配 .ps1 版)。
- `App/ashare_bsp_scanner_gui.py` 是 fork 所有者自己加的,不得破坏。

## 常用命令

```bash
python main.py                 # 基础 demo(baostock 数据,需联网)
python Debug/strategy_demo5.py # ML 训练最小闭环 demo
pytest tests/                  # 单测(M0 里程碑后可用)
```

## 架构速览(数据流)

```
DataAPI(数据源) → CChan(Chan.py, 多级别调度)
  → CKLine_List(KLine/KLine_List.py)
      add_single_klu() 逐根合并K线 → cal_seg_and_zs():
      笔(Bi) → 线段(Seg) → 中枢(ZS) → segseg/segzs → 线段买卖点 → 笔买卖点(bsp)
      → [待实现] cbsp 策略 update(try_open/try_close) → 特征 → 模型打分 → 交易
Plot/PlotDriver.py 负责全部绘图(DrawElement 为分发入口)
```

## 硬性规矩

1. **不改** `Seg/SegListComm.py` 及段算法子类的核心逻辑(作者标注过极难维护);不改既有配置默认值。
2. `CChanConfig` 用 `ConfigWithCheck`,未知 key 会抛异常 —— 新增配置必须在 `conf.check()` 前消费掉。
3. 类名 `C` 前缀、枚举进 `Common/CEnum.py`、异常用 `CChanException+ErrCode`、指标按增量计算风格写(参考 `Math/`)、中文注释。
4. 新增重依赖(ccxt/xgboost/lightgbm/optuna/pymysql/futu_api)一律**函数内懒加载**,核心缠论计算不新增任何依赖。
5. 特征与策略**严禁未来函数**:只能用当前 klu 及之前的数据;label 只在回测打标时允许看未来。
6. 每个里程碑(DEV_PLAN.md §3)完成后:跑验收标准 + `main.py`/`Debug/strategy_demo*.py` 回归 + 单独 commit(信息格式:`feat(M1): xxx`)。
7. 密钥/个人配置只进 `config.yaml`(已 gitignore),仓库只放 `config_demo.yaml`。
8. 一致性是最高验收:同一批K线,一次性 load 与 trigger_load 逐根投喂,最终笔/段/中枢/bsp 必须完全一致。

## 当前状态

- [x] 前期分析、差距清单、架构设计(见 DEV_PLAN.md)
- [x] M0 环境与配置体系(Config/、requirements 分层、tests/ 一致性测试)
- [x] M1 cbsp策略框架(CustomBuySellPoint/、CChan调度、extra_kl、toJson、Plot cbsp)
- [ ] M2 特征引擎
- [ ] M3 模型框架
- [ ] M4 回测+AutoML
- [ ] M5 ccxt数据层
- [ ] M6 交易系统
- [ ] M7 收尾
