# 私有管理上下文基础：双版离线验收

日期：2026-10-31。基线 `full-version` / `1a2a147bd9de2a08c7cd271dd8b79e6d7d488fcc` 加本次明确工作树。依据[批准规格](../specs/2026-10-30-native-existing-risk-management-design.md)及[实施计划](../plans/2026-10-30-native-existing-risk-management.md)。本步只建立同次采集的 pre-intent 活视图，不是管理写授权、原 writer/CAS 接通或 C5–C7 完成。

## 改动、复用与边界

- `Trade/NativeManagement.py`：原弱引用空 handle 模式，`_native_management_close_context` 只在当前 `with` 内有效；绑定原 Engine/线程，正常及异常退出均移除内存项，不释放订单或账户占用。
- public `collect_native_management_close_request` 与私有 scope 共用 `_collect_native_management_close_request` 和原完整区间采集。JSON、复制/深复制体、同型新对象、异 Engine/线程不能用于活视图检查。
- `_assert_native_management_context_current` 只允许原拥有事务，复核原 owner、完整 ledger/journal、原 baseline 和 known sources；不重采 SDK、不写 intent/claim/journal、不回填资金证明。检查成功的 None 不授权发送。
- 原窗口块提为本次 closure，供采集尾部及使用时复用；所有原起点/年龄/跨度不刷新，另拒绝 UTC/单调时钟倒退。市价仍只用同次原 Last V2。
- 同次保存四个实际来源守卫的函数对象、code 和默认参数，调用前拒绝晚替换；原枚举增加实际 Boundary/implementation 及新 helper，未新增全局源码缓存或另一 verifier。
- `tests/test_native_management_context.py`：9 个节点，真实原 SQLite/history、原 SDK/precision；fake 仅底层 transport/时钟。其余改动是本报告、计划和台账。

正向包含原事务内无重采/写入的重核及 cold market Last；负向覆盖复制/JSON/异 Engine/线程、七类 owner 替换、四个守卫晚变、原钱包50ms/UTC倒退、参数和另一记录晚变、退出后失效。七类 owner 测试对原/外来 SQL 及 transport 计数，未执行外来操作。所有 source-v4 授权标志仍 false，一般发送断言仍拒绝。

简化是复用原采集/单位/账本及窗口逻辑，不复制 source、SDK、Engine 或财务状态机；无新依赖、表、资金账本、第三 SDK hook、实际配置/凭据/环境开关变更。

## TDD 与保留的失败

原件根：`C:/chanpy/verification/native-management-context-20261031/`。下列中间成绩不叠加进终验：

| 原 JUnit | 实际结果 | SHA256 |
|---|---|---|
| context-api-red-a76e8a1ea32a462f83d44b1bb5b93245.xml | 1 failure，缺上下文入口 | 4dd860555291637ee8108b158b5ec4365c92b67ab8526da86e30ea8a40fb1225 |
| context-first-red-55e5f46f9abf44ad8a75926055474b8b.xml | 1 failure/3 setup error，自己漏导入原 store | 0aa5664a818e02d9bb720d645e4a4e784b0c8dc513194f6d0ab5465dc16de8be |
| context-owned-red-3a42d8c0e90648f18c62306ddbba91dd.xml | XML 4 failure；另有共享 pytest-current 清理权限错误，非验收 | dbd160ef7623ec3bba73477fb4453f9ef0ad932e1ba5e9c61b653580be27fbf1 |
| context-owned-red-b6c4557cf042443087e0909eb47918e4.xml | 独立 GUID basetemp，4 项正确缺入口 RED | 3f88554a078dde9483c42ee19e6b4a0a980ea94f055eedda1e838ea135b3c1c1 |
| context-first-green-e57d71dd7f0947c1b4b1bbaa2cd31d19.xml | 4 passed，267.55秒 | 931362a9cfdaa6a24f9e97677282ce5bd67c466cd1db72375d6ffb7eb96e64c8 |
| context-late-guard-red-c003897c8f49418b8430fe6a0ccd0e7b.xml | 1 failure，四个外来 callable 先执行才被拒绝 | 8be7c952f03ac21717921c203e68b07728836a9a6388047395b12761f040cb85 |
| context-hardened-green-36428ed9aa414d3da94b9b11036d9181.xml | 9 passed，746.58秒 | d585bad00f528625427afc62ddb569cd801a584255b8162e1e5cc2ec07c91c63 |

只修复缺失 fixture 导入，未替换原业务成功；共享临时目录问题沿既有独立 GUID 规程隔离，未删除旧目录或改 pytest 配置。四守卫 RED 后，修在调用前的身份核验，不把最终报错当作零外来执行。原工具副本 `context-tdd-tools.json` SHA `3e6fcfc2dba990167c421cc8ddb61a69b8587d77837d6681fdfa7fcf00a50b8d`。

观察脚本初次有 JS 键名引号错误，解析阶段即停止，未触及 pytest；纠正后仅观察原句柄。3.11 的123份实际观察与终态副本在 `context-py311-observations.json`，SHA `2b9cdb7b3f90574e15fe79c4799a661565a14503db49ab40df9a4c6cce2443a7`，缺失副本0。安静输出/观察超时均未当作停止、未重启或跳慢例。

## 精确双版终态

全部8个完整管理模块：context9、request54、interval52、sources17、attempts8、quantity27、identity12、role39，共218唯一节点。两版实际 collection 顺序相同，原 `-m not network`；新9与中间 GREEN 不叠加，原522个未受影响节点不重标本轮再次执行。

| 环境 | pytest / XML / controller 秒 | 原 JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 5691.01 / 5690.903 / 5694.029007 | context-acceptance-py314-d674f173dbd64f52afc3502863f9dfd8.xml / fb6fc6319218627b526f52b280aeb809f2ddf7b5da394da2cb7ad1f27d8ffb76 |
| CPython3.11.15 | 6512.90 / 6512.777 / 6516.408743 | context-acceptance-py311-9cb551abebef4ac2b36ee39407114e91.xml / 0fc09e74c3c662b758a8167aa24df6c3392e28e8efd16e9178911bfb61aaf602 |

各218 passed/0 skip/failure/error/测试warning，真实exit0，原终态工具89a343/1f956c；3.14接受后才启动3.11。完整node/state逐项相等，case-state SHA `1f1e859f69c0f01dd57129543698f481e149f9ca481f1664e73e8c1a978ca887`。有活pytest时未改文件、编译或并发跑测试。

`context-selection.json` SHA `13b6dfdc66754e6855cc0519c8d6a996223318d8e868369ebb3b6c690eac8b9c`。189文件raw map前后相同，map SHA `dd5b02c5d66c5ff031e6ac3a12e908f687f6c2b1f0505f65bd935f8e6b6b0ccd`；其中NativeManagement SHA `7a0fff940548891e20d3dc2f15ca8c38cba862bb2b59032338ff12fa21b8839d`，新测试SHA `2f7bdaa69f3433700dab47eab6f694e81dc20d33b4cc925dd3d922c107b3be64`。对上轮188源码，仅该生产文件改变并新增该测试，其余原件/依赖未变。

真实完整环境仍为3.14/70包、3.11/71包，解释器/prefix/pyvenv/user-site/包版本及源码前后匹配冻结清单；freeze SHA仍各 `6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`、`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`。requirements未改，无安装/更新依赖。

runner `verify_management_context.py` SHA `5b641482ea0ea9282d8001d50e8eb796cdd6a802e4305bcba24bc0159330d327`，未改上轮runner/证明；两份result SHA为 `f994783da772aca27d3067a5076ddb84d3f6270a7e53c7e8ee35db034e390f97` 与 `605416390e2d9d4ef93dd2b2d620d5dbfc7d2df6ee6081b1f3de4e847b3cf505`。

独立 `audit_management_context.py` 只复用原 `verify_recovery.py` 纯reader（SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`），不调用旧build/run或重写旧证明。重读canonical/seal、真实退出码、raw XML/log/args、完整成员/顺序/无重复/状态、源码/真实环境、两份终态工具、中间失败和未变范围；d74c13 exit0。审计脚本SHA `a72e8038cbadfa24ab4ae07b1ca95e429344ca2b52afd5a21502abd1deec5671`，`context-independent-audit.json` SHA `ca2f18a84a35cfedc6c02602da18a292e5ec1ef04c6b33981c26a4334e959324`。

确认无活任务后，两版当前两改动py compileall均exit0；实际optional-free 3.14/34包和3.11/35包中11个可选包确实缺失，先阻断socket/DNS后导入当前四模块，均exit0/network_attempts=0，四源SHA匹配当前map。复用未改原probe，未冒称无SDK的管理执行证明。辅助工具 `context-auxiliary-tools.json` SHA `e7dcad38345038e832df8f7367986a03054c5fb840a154535683d2a8d515db25`。diff检查通过，Git既有LF/CRLF提示不是测试warning。

## Review、剩余项与交付

依显式solo规则主线程复核调用生命周期、当前原事务/完整ledger/known sources、窗口原锚、public JSON兼容和四守卫的调用前拒绝。只声明上述列举范围，不声称全依赖、任意Python/SQLite回调沙箱或实际网络/CPU预算认证。

[USDⓈ-M官方字段文档](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)仍支持positionSide/reduceOnly字段限制，但本轮未取得更强的hedge服务器只关闭/竞态保证；FAQ/Portfolio Margin或社区材料未替代该证据，未扩大已批准金额A/P/F假设。没有访问实际账户或交易端点。

原writer/CAS、逐单合法增量、其驱动/回调依赖、跨币账户占用/未知不释放、取消上下文、原A/B消费者及三CLI/fresh-worker尚待。下一步必须用原OrderAudit版本化字段/digest/header核唯一intent/claim增量，先验证两连接/进程与回滚；不得把当前pre-intent全等检查当作写后许可、忽略字段、复用JSON或重签旧L2。NativeOrderTransition的phase=open CHECK不改，不新建ledger/table；ACK/DELETE响应不释放未知占用。

OKX同等级、候选换代/旧证明迁移、更广E2E及C7外部认证仍未完成，实际配置/资金/研究/测试网/实盘门禁不变，整个Goal active。验收对应父HEAD1a2a147加本次明确源码；Lore/普通push及远端SHA另按实际Git记录，不谎称新HEAD重跑此清单。
