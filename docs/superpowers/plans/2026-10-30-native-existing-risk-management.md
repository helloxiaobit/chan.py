# 已批准原有风险管理角色：串行实施计划

依据：[2026-10-30已批准规格](../specs/2026-10-30-native-existing-risk-management-design.md)。起点full-version `7d7e639e78ff2d817eb22a85e3ffdc5f327c5e9d`，实际配置/凭据、candidate、新风险账户协议、金额A/P/F、研究及测试网/实盘门禁不改。Inline/solo/fake-only，无新依赖、SDK第三hook或新资金账本/表。

## 目标、复用与清理前计划

完成原三个管理CLI在新风险关闭时按原单/原剩余执行撤单或关闭，同时永远拒绝新增风险、未知不释放。复用原SafetyPolicy、Engine七入口、原SDK/SQLite/CAS/OrderAudit、已有native来源/ownership/current和原A/B两位置；不复制整套Engine/来源/财务状态机。先保护行为再消除重复；仅按明确任务提取共用配置/角色校验，不做无关格式化。

1. **冻结角色和拒绝基础（先RED）**。`tests/test_native_management_role.py`使用原SQLite及显式fake配置，先观察构造缺management-only语义失败，再在`Trade/SafetyPolicy.py`/`CCXTTradeEngine.py`最小加typed、互斥、默认关闭的冻结管理角色；一般发送断言与无证明的七变更入口仍全部拒绝，public policy替换不可升级。复用原查询路由检查，不引入new enabled/permit开关。此步不接CLI，不宣称撤单/关闭可用。
2. **原单身份与源窗口**。复用`NativePreparedClient`、原query/contract/history reader、`NativeAccount*`/`NativePending*`和明确原age/span。给原实例建立只在当前调用有效的管理上下文，先验证原账户、instrument/leg、唯一record/attempt、原订单实际GET与原SDK/DB/route/实现。原旧契约缺证据拒绝。测试错账户/单位/未知/损坏L2/来源过龄/owner晚变及实际原cold SDK；不依赖warm fake成功外推。
3. **剩余量/在途能力**。独立读原journal累计与原native position/full pending，精确转换并消重本地/native同一订单；按原记录剩余、原生剩余、已占关闭量的共同能力拒绝过量/反向/跨leg/跨策略。设置mode/leverage不充当quantity。缺策略预算拒绝、不发明默认容差。原报价/退出条件不得回退私有文件或过期行情。Binance先，OKX逐项后验，Spot/反向/期权不隐含纳入。
4. **原CAS账户级串行与审计**。沿原`db_util.acquire_close_intent`/claim及`OrderAudit`现有表登记管理目的/attempt/来源/取消未知，显式版本化兼容；同一稳定账户跨币只准一个未被原生完整观察的管理变更。旧新风险unknown保持，不被cancel响应自动释放。原CAS内核同一记录/已知历史与源窗口，两连接/两进程竞争及失败回滚先RED→GREEN；无另一ledger/table。
5. **原SDK A/B使用点**。在原fetch和Session.request两位置复用同调用owner守卫并扩管理上下文，复核动作/attempt/数量/来源/窗口与CAS；只委托原SDK、严格恢复、不重采或重签。测试等候过龄、替换fetch/session/request/DB/SDK、原cancel response/GET终态、提交未知、重复报告及晚变参数；任何实际变更前必须已获本调用完整验证。
6. **原CLI接入/独立进程**。前五步完整GREEN后，才在`Trade/Script/TradeRuntime.py`及原ClosePreErrorOpen/RealTimeTracker/RetradeCoverOrder显式选新角色；RestoreOrders保持query-only、MakeOpenTrade保持普通。真实RED证明冷空集合/已知非空管理可用，而原越权/普通门禁仍拒绝。复用mixed两币库五worker helper扩GET/DELETE/关闭POST轨迹，不重播DB、mint证据或mock成功；处理cancel→终态GET→剩余关闭及冷未知恢复。
7. **验收与交付**。适用新/旧safety、状态机、native/current/default/SDK/终态、query-only、配置/paper/cycle/notification双版串行；冻结源码/清单，原GUID日志/JUnit/result与精确成员/状态、源码和runtime身份独立审查。无活pytest才编辑/编译；必要compileall/diff/链接/solo review后Lore/普通push/远端SHA。原完整7405矩阵按未变身份复用，受影响范围不得借旧成绩覆盖；模块/组合通过不等于全部C0–C7完成。

## 阶段状态与不可越界事项

2026-10-30已完成第1步和第2步的本地身份子层，见[基础子步证据](../reports/2026-10-30-native-management-foundation.md)：角色39项、身份12项及适用回归，双版各608个唯一节点通过，已Lore/普通push为e017e3d。随后完成第2步的[本次原生来源读取子步](../reports/2026-10-30-native-management-sources.md)：原SDK/原单GET、instrument/account/pending/mark-book、真实冷启动缺夹具配置/candidate、同调用owner及最终UTC/单调窗口；16新项连同原回归，双版各624唯一节点通过。读取结果仍不是native数量/操作能力，正向源证据限Binance one-way LONG既有开仓attempt；不是完整第2步或管理执行GREEN。已有13项当前行为刻画也不重标。下一步继续第2步剩余attempt/模式覆盖，再第3–6步；三个管理CLI尚未接新角色。中间阶段只有适用测试/审查通过才能交付并明确未闭合项，最终角色支持必须满足第2–6步所有条件，不能用“仍拒绝所有写”替代批准的最终管理能力。

一币未知管理可能按已批准账户串行协议阻断其他币自动管理，原只读查询仍可用。原生数量/身份或服务器关闭语义缺证据时保持拒绝并列明未完成；不默加价格/费用假设、应急越权或按leg并行。旧历史跨实现迁移、候选换代及C7外部认证仍独立受门禁，Goal保持active。

后续本轮[模式/attempt及数量读取验收](../reports/2026-10-30-native-management-quantity.md)：原金额L2 scope下的Binance四模式/方向冷open/close attempt共8项、27项独立数量/完整性检查及同次source-v2接线已验证；最终同一185源码、14完整模块加原Engine三个明确组共478节点，双版各477 passed/1原有isolated skip、零warning，原件/成员/状态/环境精确配对。尚未完成整个第2/3步：旧v3冷scope/迁移、外部往返成交与其它通道的完整原区间/执行归属、请求量/原SDK精度化及动作专用同次上下文仍需实证，不能只凭净数量或JSON放行。之后第4–6步原账户串行CAS/journal、管理A/B、三CLI/fresh-worker仍未接通；新风险/实际交易许可不变。

## f9588c8后续执行细化

先在tests/test_native_management_attempts.py复用原capacity_case四模式/方向、management_case及raw recovery transport，验证冷开仓/冷关闭attempt与原累计历史；测试共享transport使用独立的请求端期望orderId（旧默认123456，关闭夹具显式789123），不能让被刻意损坏的响应raw row改写请求端断言；不替换SDK/查询/准入成功。关闭夹具只用原prepare/CAS/claim/ACK/report生成本地历史，再由真实原SDK GET读取底层fake原单，不宣称真实关闭POST。已有相同生产源码证据按身份复用，任何真实缺口先RED再最小修正。

其后第3步先独立观察原全账户ledger与原account/pending源码：复用原AccountReconcile数量/方向及NativePendingOwnership规则，不把caller JSON变成能力。按原record/leg精确核合计本地剩余和原生position、扣同账户原关闭在途量且消重；未知/跨账户/归属不清/超量拒绝，金额零默认容差。该观察仍不是管理CAS/发送许可；操作消费者必须在同调用自采并在原CAS和A/B里复验。每个新行为先见RED，原七入口锁保持；不以只读观察替代第4–6步。

## 18f761b后使用点成本清理计划（先保护行为）

数量读取子步已普通push为18f761b，原双版证据对应185文件；以下是其后的独立工作，不回写旧验收。源码核对发现NativePreparation._assert_execution_sdk在同一次调用中为5个执行Entry加9个管理source Entry逐个读取并parse同一ccxt.abstract路由文件；3.14本地纯检查一次约0.73秒，无端点调用。这不是实盘延迟认证，也不许可延长或绕过原来源窗口。

先写离线TDD：原SDK/Entry、零网络，证明每次调用每个路由文件只解析一次且必须在返回前重新读取核字节；第二次调用必须重新读/parse，任一Entry（含最后source Entry）晚变或源字节漂移仍拒绝。观察原重复读取/未核字节变化的RED后，唯一生产修改限该函数，使用仅存于本次调用的path→source/tree字典，逐Entry原验证不删，末尾重新read比较；不增加跨调用缓存、SDK副本、hook、依赖或权限。复用适用SDK负向/管理来源/原A/B回归，双版串行冻结成员与源码后验收，原管理仍未接通。随后回到完整区间归属、动作参数、原CAS/A/B和CLI主线，不能把此成本清理称为管理能力完成。

该局部清理已完成严格RED/GREEN及[双版254节点审查](../reports/2026-10-30-native-sdk-route-snapshot.md)，186源码/70与71包环境精确配对；同次parse由5/14降到1，末尾重新读原字节，下一调用仍fresh，无新权限或窗口放宽。它不是最终管理能力，不把旧7405或上轮478节点重标为当前再次运行。下一实施优先复用AccountReconcile.build_account_reconciliation_with_pending的原完整区间/执行归属：基线必须来自原已验证root/check，不发明lookback；owned pending须在after endpoint之前读取，wallet/execution覆盖原before.started到after.finished+1的完整区间并绑定全部原市场/账户/ledger。先用相同净仓位但存在unowned往返成交的RED证明不能凭净数量通过，再接动作数量/精度、原CAS和A/B。原新风险collector含冻结/资金前置条件，不能直接让其通用PASS充当管理许可或借管理路径解冻。

## 0c3a9a9后完整区间接线与复用前计划

先在tests/test_native_management_interval.py用原claimed_order/management_case和底层raw HTTP fake，补齐该fake venue新增成交的真实userTrades字段（显式零佣金，原现金不变），不mock对账/准入成功。先见缺入口RED；clean原两币区间应闭合，加入价格/费用均相抵但无原attempt归属的往返成交后，净position和钱包不变仍拒绝。再测缺失/重复/时间缺口、来源/DB/函数别名晚变及最终窗口，保留原件。

唯一生产模块仍NativeManagement。抽取现有collector主体为私有共享实现，原v2诊断入口显式保留原采集顺序/结果，不给它新增授权；新增collect_native_management_interval入口才走完整区间路径。复用原runtime/owner/窗口尾检查，扩展枚举实际新增collector/builder与被调用别名，不复制SDK/账户/金额对账器。基线选原已验证L2 root所引check中已接受after账户快照，完整区间从该快照started_ms起到本次after.finished_ms+1；不得用任意caller baseline或短lookback。

完整路径一次planned采集pending→after账户→各市场execution（前后原账户身份）→wallet→market，原Ledger/完整journal前后一致，调用原build_account_reconciliation_with_pending而非新风险余额容量PASS；不更改风险冻结或发布解冻。所有原窗口仍从本调用开始计时、不自动重采，不把JSON或matched_observations视为动作capability。原v2回归、区间/ownership及新入口适用双版串行验收后Lore/push；此步仍不代替请求精度、账户CAS、管理A/B或三CLI的后续实现。

该完整区间观察子步现已[双版同442精确节点验收](../reports/2026-10-30-native-management-interval.md)：各441 passed/1原有isolated skip/零warning，新52项全通过；187源码map、成员/顺序/状态、原环境及raw工件独立配对一致。原基线/全市场execution+wallet、已知事实防抹除/末尾入库竞态、先账户后执行及独立单调预算均有RED/GREEN；整数ms端点相等通过原identity GET分隔，不改原严格规则。中间诊断一次错误假设调用次数也保留，未计入终验成绩。原source-v2沿私有共享主体保留诊断顺序；v3结果仍不是动作许可，未更新配置或表/资金/门禁。

下一实施点是第3步剩余的实际请求与原SDK精度化/只关闭语义、当前调用不可转交context；然后第4–6步CAS账户占用、管理A/B和三CLI/fresh-worker。cancel不应借新风险余额或要求可关闭余量大于零，但close须原单终态及当前可证实余量。继续沿原intent/claim/journal，不创建新sender/表，真实通道完整性与实际网络预算不凭fake通过；整个Goal仍active。

## dd9cc5e后请求绑定与共享算术计划（修改前）

先在tests/test_native_management_request.py写缺入口RED：同一原claimed订单经原cancel/GET/report确证终态后，管理采集器用当前真实可证实余量向下精度化，原SDK create_order_request构造相同原标的、反向side、原leg和下一close client号的limit/post-only与market正文；活跃open/close、超余量/错误模式或参数晚变仍拒绝。仅底层HTTP fake，不mock准入/CAS或精度成功，结果仍不允许发送。市价必须用原NativeLastPrice V2且额外年龄/跨度显式提供，不依赖缓存或caller quote；保留原最小名义金额检查，不添加close豁免。

为避免复制单位算术，先在Trade/CCXTTradeEngine.py把原prepare中contractSize/amount/price precision、reference和limits小块抽成私有共享terms函数；普通入口前后所有原门禁、返回float精确重读不变。沿Trade/NativePreparation.py原函数枚举绑定新helper，不改SDK/依赖/配置。管理入口在NativeManagement原collector内、最终来源/ledger/window尾核验前调用该helper及原_venue_params/create_order_request，逐次外调前后复核owner，枚举新增Last/原client-ID实际依赖；不另写sender或用通用policy PASS。

本轮冻结的是实际请求身份基础，不能据SDK形状声称服务器锁仓/必接单或C7已认证。紧接着将该同次数据封在原上下文模式的不可转交live handle，在原CAS/OrderAudit消费并于已批准A/B使用点复核；未有完整消费者前仍禁止发送。源/参数/实现晚变、独立单调预算及真实optional-free导入作为回归；无活pytest才改/编译，适用双版及精确原件后Lore/普通push。

## 请求绑定终验：3.11中断恢复记录（2026-10-31）

原3.14进程28416自然exit0，731精确节点为730 passed/1原有isolated cash-channel skip、零warning，CLI7625.62秒；原JUnit `request-acceptance-py314-8b8bf2a3d90e451b84cddc9e171790da.xml` SHA `4acabe1d00f0a36245a3d25fe6d5119f9405777a144ed61e53e7b93c33f1576f`，result SHA `a641ceedaa3541eb1d507301f79e4b53d4dc775c6cf633259fb6a462a22629b9`，case-state SHA `a5c11731370622bfc86faa64f982c09cc90f4bcc15f6f133b059ddc8993408a5`。控制器accepted=true后才串行启动3.11，不将此单版结果称为双版验收或管理执行完成。

03:13（19:13 UTC）续接时，原3.11句柄62803已不存在；两次系统只读检查均无Python/pytest/uv。该尝试仅保留started、731节点args和17458字节partial stdout，无JUnit/result，退出码及中断机制未知。日志110个通过精确对应原清单前缀，但均不计终验；新增请求54项与区间52项曾在该partial中通过的观察不替代完整终态。

本次原件根为 `C:/chanpy/verification/native-management-request-20261030/`。原started SHA `efdf8dea65c1e5857b23bffd9ef794340640b3bd335af8cc36fe0f205f5397ad`，原args SHA `2041decde19d51fdb61986464c1f8dff9361ad1adc577cfbeb2a4068aea3330e`，partial log SHA `283a6e51f1f52ba880b6f6ec746b16d8e7b012a480a9f44e0a1948e7c14d90c1`；观察及完整环境复核保存在 `request-interruption-20261030T191322Z.json`。源码188文件map仍 `4339b35d337b0d98131b713598da65054af68cf46e95dc0fee9df1642ada00c4`，manifest raw SHA仍 `5985f2c13fb7cfc285bbf8f64a739b0f169d9ca797fae1c3cd937f815b517596`，两版真实metadata/前缀/user-site、requirements、原HEAD dd9cc5e和3.14终态原件全部复核一致。

沿既有中断恢复规程，仅在确认无活任务后，把该已停started原字节可逆归档为 `request-py311.interrupted-20261030T191322Z.started.json`，不改原args、partial log或basetemp。使用SHA不变的 `verify_request_binding.py`（`81d92be4b5e5ebbcfc6b699acdace2002e71f0b710221acd972e4ec921f800d4`）将原731节点完整重跑到新GUID；保持原清单/顺序/封装/环境，不叠加partial、重标失败或缩小范围，不重复已完整接受且身份未变的3.14。双版终态独立审计、当前编译/import检查、Lore/普通push及后续CAS/A-B/CLI仍待完成，Goal active；产品/测试/依赖/实际配置和交易门禁不变。

### 恢复终态与本观察子步验收

原恢复句柄54698自然exit0，3.11完整731节点为730 passed/1原有skip/零warning，CLI8504.41秒；新JUnit `request-acceptance-py311-8198072c00be47aa96be90ed19ffb407.xml` SHA `030892f54aea5426ed549f8044119b40414a0104acd91d505bf89c100f5497b8`，result SHA `12625be080f7742ac6c1ce2b52a5d1d77593720acf42ae48dac6042ef585971d`。与3.14完整成员/顺序/状态逐项相同，case-state仍a5c11731；188源码map、真实70/71包环境及原manifest/verifier未变。独立审计exit0、双版四改动py编译和真实optional-free导入均通过，14中间JUnit/64工具副本、初始DB断言错误/Decimal误用和两项Last尾RED均保留，见[本请求绑定报告](../reports/2026-10-31-native-management-request.md)。此观察子步具备相应Lore/普通push门槛，实际Git身份另核；不称整个第3–6步或C5/C6/C7完成。

## 下一步动作上下文与原journal接线（修改前计划）

先在原SQLite/SDK fake夹具写缺私有动作handle的RED：JSON/复制体/新造同型对象不能消费，跨Engine/连接/线程不能转交；源、参数、实现、全库ledger晚变或原窗口过龄必须在外来SQL/transport之前拒绝。沿原WeakKeyDictionary上下文模式封存本次自采closure和请求，不接受caller PASS/baseline/时钟，不复制来源/金额/发送状态机；public source-v4仍只导出非授权JSON。

随后沿原`_order_write`/`acquire_close_intent`/claim与`OrderAudit`消费同一动作、原intent/claim唯一增量和全账户占用；先验证两连接/两进程、已有未知/created/submitting、回滚、重复报告及原生终态才释放。NativeOrderTransition表的phase=open CHECK不得改或塞close/cancel；在原append-only OrderAudit事件中显式版本化管理绑定/增量，严格reader核新增字段digest/类型/前缀，不新建第二ledger/table、不补签旧open L2。

最后接已批准A/B原fetch和Session.request两位置：同call核实际动作/client/leg/数量/来源/owner/CAS，严格恢复，不重采/重签/第三hook；再接原三CLI与fresh-worker。通用管理发送断言仍拒绝，只允许逐动作完整消费者执行批准范围，不能停在永久全拒绝。cancel不借新风险余额或可关闭量>0，close保留原终态/余量及服务器只关闭证据门槛。逐步真实RED/GREEN、适用串行回归和Lore，不改实际配置或真实交易授权。

### 1a2a147后私有上下文实现与待验范围

请求绑定已Lore/普通push为`1a2a147bd9de2a08c7cd271dd8b79e6d7d488fcc`，远端完整SHA相同，交付时工作树干净，188源码仍与原731双版清单相等，未声称新HEAD重跑。其后唯一生产修改为NativeManagement：原WeakKeyDictionary空handle模式、当前with作用域/Engine/线程，退出即撤销该内存上下文；JSON无授权。复用同一close采集主体及原owner/full-ledger/known-source检查，在原拥有事务中重核，不重采，不更新原窗口。窗口块抽成同次closure供采集和使用复用，没有第二SDK/账本/发送器或实际配置修改。

先缺入口RED，再原SQLite/SDK底层fake的4项GREEN。其间自己漏导入store导致1failure/3setup error；补导入后的另一次因共享pytest-current权限错误退出，保留原件，不删除旧目录或计通过；之后用既有GUID独立basetemp规程得到4项正确缺入口RED。新增guard晚变RED证明4个外来callable先执行才被拒绝，随后在任何调用前核同次函数对象/code/defaults，并将实际Boundary/implementation依赖纳入原枚举。当前9项GREEN（746.58秒、exit0）：真实原事务、复制/JSON/异Engine/异线程、七类owner替换零外来SQL/transport、四守卫、原50ms钱包/UTC倒退、另一记录/参数及cold market Last/异常失效。原件位于`C:/chanpy/verification/native-management-context-20261031/`，本段仍不是双版终验。

主线程依显式solo要求复核，无委派；当前仅pre-intent活视图，不允许合法CAS增量、占用释放或管理发送。后续第4–6步仍必须完成，不能将此handle或None当许可。适用验收冻结全部8个管理模块（新9＋原209，共218节点）及189源码、原3.14/3.11完整环境，严格串行至真实终态；未改且无NativeManagement依赖的原522节点只按适用身份复用，不改称本轮再次执行。无活pytest才编译/改文档，独立审查完整成员/工件后才Lore/push本上下文子步。

该基础子步现已[双版终验及独立审计](../reports/2026-10-31-native-management-context.md)：同一218精确节点各218 passed/零skip/warning，原进程自然exit0，189源码map仍dd5b02c5；完整成员/顺序/状态相等，真实70/71包环境不变。3.14接受后才启动3.11，原123次观察和中间错误保留；当前编译、实际optional-free导入也通过。不重标未改522或旧7405为本轮重跑，不称整个第3–6步/C5/C6/C7完成。

后续接线前仍按修改前计划：先RED覆盖原writer及其实际SQL/回调依赖晚换，拒绝发生在外来SQL/transport之前；再原CAS唯一intent/claim增量和稳定账户跨币占用。用原OrderAudit显式版本化管理字段，并纳入data_sha/digest/reader/header，不能在原NativeOrderTransition塞close/cancel。当前活视图只接受写前全等，写后必须独立核确定义的唯一增量，不能增添任意ignore/allow-pass参数。随后管理A/B与三CLI，保持未知/ACK不释放和实际门禁；不以当前仍无发送能力作为最终交付。
