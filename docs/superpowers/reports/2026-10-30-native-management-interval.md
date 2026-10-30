# 限定管理：原完整区间来源与归属观察验收

日期：2026-10-30。基线full-version `0c3a9a95672a2cc7364a54b78d605049d2277f18`加本轮工作树。继续[已批准限定管理规格](../specs/2026-10-30-native-existing-risk-management-design.md)及[串行实施计划](../plans/2026-10-30-native-existing-risk-management.md)。本轮是原来源/归属观察，不是管理CAS、撤单/关闭发送、三CLI接线或C5–C7完成。

## 改动与复用

唯一生产文件`Trade/NativeManagement.py`：新增`collect_native_management_interval`，返回source-v3和内层interval-v1；原`collect_native_management_sources`保留v2诊断顺序与schema。两入口复用私有collector主体、原SDK/owner/窗口尾检查，不复制Engine、SDK或财务对账器，不新增hook、表、账本、配置字段、依赖或许可。新增`tests/test_native_management_interval.py`；其余为计划、台账和本报告。实施前已记录复用/清理计划。

完整路径必须从原已验证L2 root的check取已接受after快照作before基线；拒绝caller指定基线、短lookback、收据或时钟。原单instrument/GET之后，按planned次序采原账户identity→pending→identity→after账户→逐原市场execution（账户identity前后核验）→wallet→market。额外identity是真实原GET，解决整数毫秒端点相等；没有sleep、伪造时钟或放宽原严格先后约束。

原完整ledger、journal prefix/attempt数、原client roots与原check前后固定，沿原`AccountReconcile.build_account_reconciliation_with_pending`核原before.started至本次after.finished+1的完整半开区间。逐成交归属、实际价格、费用/已实现现金、原仓位/累计状态按原零默认容差规则检查；不会把新风险availableBalance/资金容量PASS借作管理许可。外来账户在成交端点前即拒绝，而不是事后才发现。

已知原来源也不能被较新空响应抹去：通过原AccountStore/ExecutionStore验证reader、原`_known_facts`/`_latest`规则读取同账户已入库事实与观测；相同平台/模式而无原生账户绑定的scan不能凭namespace假设属于另一账户。原known-source fingerprint在采集前、对账和最后行情后重复核验，期间新入库事实不被更早区间悄悄采用。没有发布来源、重新冻结/解冻或更新旧check。

新增account、pending、各execution、wallet和market各自的单调时钟年龄/跨度窗口，最后使用点独立核对，保留原UTC/instrument/order/total检查；宽总预算不能掩盖窄单项预算。新增实际collector、builder及导入别名都纳入原runtime函数/SDK Entry闭包核验。返回`native_quantity_verified`、`operation_authorized`仍均false，JSON可复制不代表动作能力；原查询只可追加原本允许的真实ACK/终态观察，不猜累计成交。

## TDD与诊断原件（不叠加为终验成绩）

原件根`C:/chanpy/verification/native-management-interval-20261030/`。独立审计清点18份中间JUnit，完整文件名、外部SHA、实际case状态见`interval-independent-audit.json`。主要原件如下：

| 原件 | 真实结果 / 原因 | SHA256 |
|---|---|---|
| red-5056abc5064f4827ab39c4cf9e5011db.xml | 3 failure，缺新入口 | 9f54de1567fbe410e8ac500dfc528b9b5419ba915eba9c83a69e0f71b3ce366f |
| green-c652a981016643dfb28aca212d5f9c2e.xml | 文件虽名green，实际3 failure，pending/after严格端点不满足 | ce9e621a200bdbcdf195a587b0b610b8feaac264f3d2883d30fcb3554f617670 |
| account-red-f61db4d6fa7745fe89e93ecc00cab819.xml | 1 failure，外来执行账户被过晚拒绝 | d8da22bb2b765079500006ef504a873b6041320c02df95454b3b3a7910899e2c |
| snapshot-red-fd2c0ea6d8f84cf8a5fd2f3e991d8f6d.xml | 1 failure，内部一致的外来账户快照在执行读取后才拒绝 | 4d72f7c5324451325f4c9da588ac69f4b0f6bcb458f8426730f33de11f29cd5d |
| tail-6fc10076ac3e439c8f4bcacc93173409.xml | 3 passed/1 failure，零余额正向暴露原终态GET与pending起点相等 | 1765f9d93a1c308a599242f090ff11f96327eca914238185fc8b2e299bfad5d9 |
| monotonic-red-8ee1eed9028a462b993d2ba928e3f8ed.xml | 4 failure，单项51ms越过50ms而总2s/UTC未变仍未拒绝 | 08d146d5a8d79b439b21f094a0b0433960f849c60f885121dcaea3a851c06d2b |
| known-red-19520f539f0e446898856c97e005a492.xml | 3 failure，已知零净额事实被隐藏及无账户绑定scan未拒绝 | 933b27371d12bc38094500358bde64eb5fa180610c7906a44e5375c54d67730d |

保留一项诊断错误：`window-diagnostic-be5e356a818b475e82a119c53047b8ad.xml`实际1 failure（SHA `57c49ae86f2ef43f4b13e6bc553d0233d9ce67d2cbf7e8559037cd6c0433c142`），错误地期望builder只被调用一次，实际原历史重建123次；诊断的直接market元数据比较也不是原归一化比较。没有把诊断错误重标成产品RED。trace/terminal-diagnostic/terminal-boundary三个“pass”只证明当时实际拒绝及严格相等端点，不是功能GREEN；不加入终验节点。

修正后分别有ordered3、focused19、冷模式8、zero-balance1、monotonic4、known5、extra21等实际通过原件；不把相互重叠的中间用例相加。最终新52项包含四模式/方向×open/close冷SDK、未归属零净额往返、缺成交/错价/冲突重复、caller输入拒绝、20项实际reader/别名绑定、UTC/独立单调窗口、其它记录晚变、零新风险余额、已知事实防抹除、未绑定scan及末尾入库竞态。

中间运行的退出码以原工具消息为据，不从JUnit推造CLI退出码；续行工具缓存已不可用的副本请求在`interval-original-tool-results.json`明确列为unavailable，不伪造原输出。下面终验的真实returncode、原stdout和完整封装均在磁盘可独立读取。

## 双版同清单终验

两版先collect同一12完整模块，共442唯一节点，冻结`interval-selection.json` SHA `056e29ba4a0aa93335ac9dc94204b5d7aaa4f007817c7d23868aa2ef31837cf5`。原3.14结束并核验accepted后才启动3.11；活pytest期间无文件编辑、编译、另起pytest、跳过/重启慢例或更改证明格式。两次自然exit0，各441 passed/1原有skip/0failure/error/0warning：

| 环境 | pytest秒 / XML秒 / controller秒 | 原JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 2635.89 /2635.743 /2639.3731 | interval-acceptance-py314-83f7524e4fbe4470b23a7dd52646b190.xml /f986e4e44435f76baa4dc974efd82f5c593f1ae886dddbeb3cea20e54e8bec9a |
| CPython3.11.15 | 2908.67 /2908.512 /2911.9690 | interval-acceptance-py311-45959a3285ea477482b6fd5a4ec9f747.xml /50f72acc79106867d9934fe7bd8990862dd2bd1662b84d6b14a7d9a985b73307 |

完整模块：新增interval52、原sources17、attempts8、quantity27、identity12、role39、account_reconciliation52、execution_ownership38、native_pending_ownership95、order_audit_history35、query_only_runtime50、sdk_route_snapshot17。唯一skip为原`isolated_channel-position_cash_channel_unallocated-binance`，原因“Binance income has no isolated position cash channel”；不是新增跳过。成员/顺序/状态双版逐项相等，case-state SHA `38e77db296fe41befb9b7950957ce3ba075fdec504135c5460a8a48f59cfdef9`。

187文件（Trade递归py及tests顶层py）raw map前后不变，canonical map SHA `ae2a5a0cf67afc1a231698f3789e87ed977de4d326f527e33f03f4e7cd04f62f`。完整原环境仍3.14/70包、3.11/71包，freeze SHA各`6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`及`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`；真实metadata、前缀/user-site、requirements前后精确核验。未安装/更新依赖。

task-local runner `verify_interval_sources.py` SHA `e9e07030cbaff74650c2c0f00a9d41163c157ace75fa8d0af5050a72820fe358`；每次唯一GUID args/stdout/JUnit及started/result封装保留。两个result raw SHA为3.14 `d69ec9c6e9b256dbb8782b0f159935a7f1ba8639b30951df8a0c830ddbbf44d2`、3.11 `ea78fc24d45fd35f37579553205ba561a96fe718aab8818baddc30c07c7b9f88`。原终态工具50750f/3c1e1e均exit0。

`audit_interval_sources.py` SHA `950c48d8466e7b5344bfd4370a13d07b9905fb36471aab15880624e1ff871dcd`独立重读所有raw XML/log/args/result/canonical/外部SHA及当前source/runtime，对比精确完整成员、skip原因、suite计数、stdout状态顺序与双版collection。只复用原`verify_recovery.py`纯reader（SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`），不调用旧代际build/run或改旧证明。审计exit0，`interval-independent-audit.json` SHA `b0efdc80b8b37ee30910514455d83d3b2ee79cd1fc0f9f6bd3063da1d1645d10`。

两原进程终止后双版编译两改动py通过。实际optional-free core前缀3.14/34包、3.11/35包metadata投影一致，11可选包确实缺失；stdlib ssl后、产品/第三方导入前阻断全部socket/DNS，再实际导入SafetyPolicy、CCXTTradeEngine、NativePreparation及当前NativeManagement，均exit0/零连接。复用未变`route_core_imports.py`，当前工具原输出及编译结果在`interval-current-auxiliary-tools.json`（SHA `f76893a129b5f5410d1100f8bac0752865d96e4231ef07b59b1a455940e13855`）；不是无CCXT下执行交易CLI或新环境安装。diff检查及三文档50个本地链接通过，solo review见下文；不重标旧7405/478/254成绩为本轮全仓重跑。

## Review、未完成与下一步

主线程solo核对共享v2/v3路径、实际别名枚举、原基线/全库ledger/known-source指纹、严格endpoint与半开覆盖、先查账户后执行、末尾UTC及逐来源单调预算、零余额正向及负向数据库副作用；未发现阻断本观察子步交付的已证实问题。函数/JSON校验不是任意Python进程沙箱，读到的matched_observations仍明确`provided_observations_only_not_trading_admission`。原费用、舍入、通道完整性披露没有删除。

实际CPU/网络下窗口可用性、bot/copy等原生全部通道的原子完整性尚未认证，不能据fake时钟SLA通过；不扩大预算或自动重采。旧v3冷scope/跨实现迁移仍需单独闭合。下一步落实请求量/原SDK向下精度化及venue只关闭语义绑定、不可转交的动作同次上下文，再原账户串行CAS/OrderAudit占用、已批准管理A/B和三个CLI/fresh-worker。不能用永久拒绝所有变更或本轮只读观察替代已批准最终能力。OKX同等级、完整C5/C6和C7外部认证仍未完成；实际配置/凭据/候选/资金、研究/测试网/实盘授权不变，Goal保持active。
