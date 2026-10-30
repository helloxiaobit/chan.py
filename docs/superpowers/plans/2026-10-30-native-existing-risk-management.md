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

先在tests/test_native_management_attempts.py复用原capacity_case四模式/方向、management_case及raw recovery transport，验证冷开仓/冷关闭attempt与原累计历史；测试共享transport仅将固定示例orderId改为当前原raw row的ID，不替换SDK/查询/准入成功。关闭夹具只用原prepare/CAS/claim/ACK/report生成本地历史，再由真实原SDK GET读取底层fake原单，不宣称真实关闭POST。已有相同生产源码证据按身份复用，任何真实缺口先RED再最小修正。

其后第3步先独立观察原全账户ledger与原account/pending源码：复用原AccountReconcile数量/方向及NativePendingOwnership规则，不把caller JSON变成能力。按原record/leg精确核合计本地剩余和原生position、扣同账户原关闭在途量且消重；未知/跨账户/归属不清/超量拒绝，金额零默认容差。该观察仍不是管理CAS/发送许可；操作消费者必须在同调用自采并在原CAS和A/B里复验。每个新行为先见RED，原七入口锁保持；不以只读观察替代第4–6步。
