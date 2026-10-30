# 原SDK同调用路由快照清理

日期：2026-10-30。基线full-version `18f761b097a0ed5095fbfc2791120ace645ad28a`加本轮工作树；该基线的[数量读取子步](2026-10-30-native-management-quantity.md)已Lore/普通push且远端精确一致。继续[限定管理计划](../plans/2026-10-30-native-existing-risk-management.md)，本轮不是管理CAS/撤单/关闭或C5–C7完成。

## 文件、简化及不变边界

唯一生产文件`Trade/NativePreparation.py`、唯一生产函数`_assert_execution_sdk`：同次调用以局部path→(原始source bytes, AST)字典复用路由树；原5个执行Entry及9个管理source Entry仍逐个核descriptor/type、声明字段、Entry闭包和真实bound method。返回前重读全部所用路由文件，任何字节变化拒绝；下一调用重新read/parse，无跨调用缓存或SDK副本。不删原实际SDK/A/B检查，不新增hook、sender、金额公式、表、依赖、配置或许可。

`tests/test_native_sdk_route_snapshot.py`新增17项：5/14-entry两路径每次恰好1次parse/2次读取，连续两调用各自fresh；源字节漂移拒绝；14个Entry逐个在来源读取后晚变（含最后source Entry）仍拒绝。只观测Path读取和阻断底层网络，不mock SDK验证成功或改已安装文件。原数量/来源/角色生产代码及普通/query-only门禁未改。其余改动为本计划、台账和报告；实施前已写清理计划，严格RED→GREEN。

## TDD原件

原件根`C:/chanpy/verification/native-management-cold-20261030/`。两轮RED均原进程自然exit1、3 failed/14 passed/error0：原实际5/14次重复读取，以及只追加注释的源漂移未被拒绝。第二轮将观测兼容原text读取及目标raw读取后再次复现，不是fixture或缺函数错误。

- route-red-289aafdbe1ad456c8d2b96ab75a09c30.xml，SHA `5f28ee192721695c0c38c85b8459b398a7230b3dfcfffbb3c1a8b56f72ff43c2`。
- route-raw-red-5521220603544fc58d70dadfe4f2464d.xml，SHA `6a5915be05f3f8843281420d22e3a6ce61a53e504e13981abe4a074892730dd9`。
- 最小修改后focused原进程自然exit0，17 passed/7.94秒；route-green-d390213f28f54698a609863944f1e23c.xml及route-green-tool-result.json保留，不叠加进最终254项。两轮RED原工具分块/终态分别存route-red-tool-results.json、route-raw-red-tool-results.json；无重标、重试掩盖或安装源写入。

## 最终双版同清单验收

先双版collect同一完整7模块，再冻结route-selection.json，SHA `32f7120640ea2d61dc5734b0b3679e35f702726ea5dafebaf0a560de777aac4b`。其后原3.14、原3.11严格串行；活pytest期间无编辑/编译、另起pytest、跳过或重启慢例。两原进程均自然exit0、254 passed/0skip/0failure/error/0warning：

| 运行 | CLI秒 / XML秒 | 原JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 1965.90 /1965.783 | route-acceptance-py314-a3d53f9475dc463bbb02026d579ce642.xml /29c2e68c2a11f7ed0eb6e1ca86acd46726796466ee496a97eb61b38d5e4397a6 |
| CPython3.11.15 | 2142.62 /2142.522 | route-acceptance-py311-235d47b6248e4b0db34bede24938fb27.xml /1af3c65015bfb6af57234a70bac32708ad92fa8b94c90ad3865b466847551159 |

精确完整模块：新snapshot17、原native_monetary_sdk90、原native_monetary_http_boundary33、管理sources17/attempts8/role39、query_only_runtime50。254节点无重复/遗漏/重排，两版case/state SHA `dd4c99c4473a6db3bcb15f667a91b475b0aea13e18ed217b4f36f3e30036e74b`。不称全仓、新7405或上轮478再次运行。

186文件（Trade递归py+tests顶层py）raw map前后不变，SHA `3b56c04495454c4b214607aeb82954b2e0a9478e748e9ace8f099f5086149301`。实际完整环境仍3.14/70包、3.11/71包，freeze SHA分别`6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`、`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`；真实metadata/前缀/user-site及两份requirements fresh核对未变。

本轮task-local runner verify_route_snapshot.py SHA `ade7e4e0e1731f296e96f6f462e3bc09d906720c22099d7580511a742f758815`；唯一GUID stdout.log/JUnit、route-py314/py311.started/result.json保留真实原returncode、完整cases、前后source/runtime和外部hash。两个原result SHA分别`269cb59b473ab17108f776d972f8f15c0531d084f27a4d2b5d881bb50a685a98`、`1107c93dd65c4e47cc8f3b5c3fa342a77c7478952d4e812140cbccc04a2aac34`；终态工具fc9887/ff03fb均exit0，展示tail被工具截短不等于丢弃完整日志。

独立audit_route_snapshot.py只复用原verify_recovery.py纯canonical/read_cases/check_cases/environment/sources reader，原SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`。不调用旧代际build/run或改旧证明，重核hash、schema/精确成员/状态、实际source/runtime及suite计数均通过；route-independent-audit.json SHA `bf4a1d273b86454679d47517f29af2eb291cb59353983ab5f2e7f6e6ecce0118`。

无活pytest后双版两改动py compileall与diff检查通过。真实optional-free core前缀3.14/34包、3.11/35包投影metadata一致；yaml/pytest/ccxt等11包确实缺失，stdlib ssl后、产品/第三方导入前阻断socket/DNS，实际导入SafetyPolicy/CCXTTradeEngine/NativePreparation/NativeManagement均exit0/零连接。route_core_imports.py及route-core-tool-results.json保留；不是无CCXT执行交易CLI。

## 成本观察、review及剩余要求

清理前一次本机3.14纯SDK verifier观察0.7296秒；清理后3次0.4493/0.3568/0.3503秒，3.11三次0.4692/0.4214/0.3962秒，均零网络，原件route-timing-tool-results.json。确定的改进是同次parse由5/14次降至1且增加末尾字节核对；少量本机计时不是collector整体、网络SLA或实盘预算认证。未延长预算或自动重采过关。

主线程solo review核对先清理计划、最小单函数diff、逐Entry/闭包未删、源字节尾守卫/无跨调用状态、14项晚变、原A/B/query-only/管理角色及实际无可选依赖导入，未发现阻断本局部清理的已证实问题。不称整个Python进程/SDK依赖沙箱、跨实现旧L2迁移或新HEAD重跑。

下一步仍是完整原区间/外部往返成交归属、动作专用同次上下文、请求量/原SDK精度及只关闭语义、原账户串行CAS/OrderAudit、管理A/B及原三CLI/fresh-worker闭环。净数量和本次成本清理不是最终撤单/关闭功能。OKX同等级、C7外部认证和真实预算未完成；实际配置/凭据/候选/资金、研究、测试网/实盘授权不改，整个C0–C7 Goal active。
