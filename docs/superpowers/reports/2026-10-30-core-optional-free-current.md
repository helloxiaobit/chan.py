# 当前发布代码的可选包缺失复验

日期：2026-10-30。验证时full-version HEAD a8557764dd3e8b03875e9fbbceac1944337a279b，产品/仓内测试/requirements/实际配置未改。继续[安装矩阵](2026-10-22-python-install-matrix.md)的C6核心导入要求；完整依赖验收复用[本轮双版7405节点证据](2026-10-30-native-query-only-verification.md)，不把本smoke当完整功能矩阵。

## 为什么补核

37bc075原核心安装验收之后，CCXTTradeEngine与TradeRuntime确有变化；完整全依赖环境通过不能证明缺CCXT/YAML/模型包时仍可导入。新增两个独占核心venv，不卸载/修改全局或原完整venv，不重新解析未来最新版本。

从已核完整环境metadata按requirements.txt六个基础包及其当前marker的递归闭包取原固定版本，34/35包；用uv0.11.6 --no-config、独立prefix、原本地缓存、--offline --only-binary :all: --link-mode copy --no-deps精确安装，随后实际pip check两版exit0。--no-deps只避免额外解析；每个实际依赖specifier/marker和完整metadata集合都另行核对，不拿它掩盖缺依赖。无新依赖、下载或全局安装。

这是完整环境版本的**新核心投影**，不是恢复旧核心快照：charset-normalizer3.4.7/idna3.18与原核心安装时3.5.2/3.20不同，正是原完整依赖已使用版本，不能伪称同一个旧core freeze。

## 实测结果

| 核心环境 | 实际包数 | 安装/pip check | 最终v2 smoke终态 | 外层秒 |
|---|---:|---|---|---:|
| CPython3.14.2 | 34 | 均exit0 | exit0，零stderr | 3.875 |
| CPython3.11.15 | 35 | 均exit0 | exit0，零stderr | 2.797 |

- 实际sys.prefix为各新venv、不同于base；isolated=1、user-site=false、include-system-site-packages=false；逐包metadata等于投影，六基础包真实导入路径均在该prefix。
- yaml/pytest/ccxt/sklearn/xgboost/lightgbm/optuna/PyQt6/pymysql/futu/minio共11模块find_spec真实为None，前后相同，没有import mock或装pytest冒充最小环境。
- 真实导入Chan、ChanConfig、FeatureEngine、DataAPI.ccxt、CCXTTradeEngine、PaperState、TradeRuntime、RunTradeStage、RunTradeCycle、RestoreOrders、MakeOpenTrade和三个管理CLI，共14入口；没有执行交易CLI、训练或策略绩效读取。
- 96根新的固定整数OHLCV合成1h K，明确UTC/finality与Binance swap来源，执行真实trigger_load→v2 API；核每根OHLCV/volume/完整clock/source、96根条数、末available时刻、非空bi，以及finite canonical payload SHA；legacy导出默认与v1一致。
- 缺CCXT的显式create_exchange调用必须ModuleNotFoundError(ccxt)；显式空临时YAML的CEnv读取须给出pyyaml缺失提示；query-only dry-run policy仍拒绝订单。没有读取用户实际配置或私有退出参数。
- 最终v2在任何第三方导入前安装Python socket connect/DNS阻断（先仅载stdlib ssl），两版network_attempts=0。此为该Python smoke的范围，不是全宿主流量、所有依赖供应链或C7认证。

## 原件及身份

原件根：C:/chanpy/verification/native-core-current-20261030/。两core环境/缓存引用/输出均保留，无递归清理。

- 两版新96根输入SHA b273390ccff5d2904f0b55008315ef01fb73f1d920014dacc9a6489295b0e97f，API payload SHA共同3a9b204974ccd708f1ff1d1c38a429e979b8932353d3c6fc0c8dd0930156528c。不是旧smoke输入，也不与旧05860e...摘要冒称相同fixture。
- 实际导入的86个仓内py原raw文件map SHA共同056a7a219638c12a9da1d766e2b7699d48a4d447e756fc1d549006d3cc762e3f；整体179个Trade递归/tests顶层源码map仍1a44946c062ce07e602cd2704a684160a1e486329d555479eb14a37ac5f3c123。
- py314新core freeze SHA295d329501c2e9a17932de052c5ba2519616748f00f72ea3a827c7d2006feaf0；py311 SHA1641704e4eed639e54c9c2b55d801cadd6bd9f2ef323cf5eeef84fcc900c8945。包名标准化/排序后name==version+LF。

| 原件 | SHA256 |
|---|---|
| projection.json | 89b17d155e876990e764fc5a8132cd2eb2b705c07e4627063d4d0f183f794d24 |
| core_smoke.py（首版保留） | 1ca943646743a5fb62b52257f4fb2323dc23814d47ba0934cc263017e09695b4 |
| core_smoke_v2.py | 2bc3d6ea44f0d9dc750477ad3ce47843a7f9dd4d71ae1ab92b8eade24503460a |
| 01-py314-install-tool-result.json | 17a68f1a81a9689ef295593dc52f76ea98dd3ad091f6bc58c79dcea8273a7eeb |
| 02-py311-install-tool-result.json | d8be136ea5694d28cc995a1447061b8a5a1d67ab2b0dfced2f12e5380e38f7e8 |
| 06-final-v2-pair-tool-result.json | 22a2b68ec1e6b94446dc2d8c1265e0e108cc7f17b24a8955606cd87a99c5dcbd |

首版两版smoke已通过但网络阻断装在六基础包导入后，不能用它证明整个第三方导入阶段的零连接；审查发现后保留首版/输出，只在外部v2前移阻断，再完整串行复验。工具更新后内存结果store缺失，第一次保存v2的操作在任何写/执行前明确失败；前置stdout仍保留在工具记录，随后用同一v2做显式capture两版并保存原结果，不伪造内存/原退出码。v2未改变产品或断言范围。

本项只补核心安装/导入/固定API行为证据，不认证缺YAML时执行配置CLI、不证明所有策略/理论结构、其他OS/依赖组合或真实交易。没有产品简化，复用现有模块；未加依赖、宽松mock或临时生产配置。C5/C6/C7仍未完成，管理角色现已获批准并另按TDD实施，不能拿本smoke当其GREEN。

## 当前核心投影完整包表

| package | py311 | py314 |
|---|---|---|
| asttokens | 3.0.2 | 3.0.2 |
| baostock | 0.9.4 | 0.9.4 |
| certifi | 2026.10.19 | 2026.10.19 |
| charset-normalizer | 3.4.7 | 3.4.7 |
| colorama | 0.4.6 | 0.4.6 |
| contourpy | 1.3.3 | 1.4.0 |
| cycler | 0.12.1 | 0.12.1 |
| executing | 2.3.0 | 2.3.0 |
| fonttools | 4.67.0 | 4.67.0 |
| idna | 3.18 | 3.18 |
| ipython | 9.17.1 | 9.17.1 |
| ipython-pygments-lexers | 1.1.1 | 1.1.1 |
| jedi | 0.20.1 | 0.20.1 |
| kiwisolver | 1.5.1 | 1.5.1 |
| matplotlib | 3.11.2 | 3.11.2 |
| matplotlib-inline | 0.2.2 | 0.2.2 |
| numpy | 2.4.6 | 2.5.4 |
| packaging | 26.3 | 26.3 |
| pandas | 3.0.6 | 3.0.6 |
| parso | 0.8.7 | 0.8.7 |
| pillow | 13.0.0 | 13.0.0 |
| prompt-toolkit | 3.0.53 | 3.0.53 |
| psutil | 7.2.2 | 7.2.2 |
| pure-eval | 0.2.4 | 0.2.4 |
| pygments | 2.21.0 | 2.21.0 |
| pyparsing | 3.3.3 | 3.3.3 |
| python-dateutil | 3.0.0 | 3.0.0 |
| requests | 2.34.2 | 2.34.2 |
| six | 1.17.0 | 1.17.0 |
| stack-data | 0.6.3 | 0.6.3 |
| traitlets | 5.16.1 | 5.16.1 |
| typing-extensions | 4.16.0 | 未安装 |
| tzdata | 2026.5 | 2026.5 |
| urllib3 | 2.8.0 | 2.8.0 |
| wcwidth | 0.9.3 | 0.9.3 |
