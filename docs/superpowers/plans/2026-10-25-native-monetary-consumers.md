# 同一金额binding的原消费者闭合

2026-10-25，基线pushed/clean `2921a379e348aa1f0c54dfb93fc8265e05e8576e`。继续[已批准接入计划](2026-10-25-approved-standard-commission-integration.md)第4步、[同次金额CAS](2026-10-25-owned-monetary-cas.md)和[账户串行协议](../specs/2026-10-23-native-per-order-admission-protocol.md)，不是另选金额假设或新审批。上一Goal turn为实际进展：原金额intent已实现、双版各3886通过并推送；C5–C7/完整Goal未完成，保持active。主线程严格串行、fake、无新依赖/真实端点/实际配置或交易/研究门禁改动。

## 结果与关键依赖

只延续同一binding-v4/client-order-v1完整monetary。最终必须进入原claim/L2及HTTP前、原pending/execution/account/恢复、原默认入口；全部消费者和fake E2E验收前，不启用新schema的claim/发送软件路径。旧v2/v3诊断与旧源不补签、重封或迁移。F/P的未原生证明范围保持false，不把本地通过当服务器锁额或成交/费用上界。

历史归属用于观察和管理已存在的风险，不要求原资金点仍fresh；新风险则必须在原owned事务中按当前来源/实际加载runtime/账户单未观察意图和完整金额重验。原AccountRiskStore._ledger同时用于原L0/L1/L2确定增量，不能加入会递归读取尚未发布transition的新字段。原CAS的账本形状、表和唯一事件增量不改。

## 修改前的复用/清理计划与顺序

1. **原transition历史读取与pending真实消费。** NativeOrderTransition._read的原验证循环抽为按实际不可变attempt读取的私有共享体；必须先从原ATTEMPTS/EVENTS重读并逐字节比较，不能接受caller attempt/root作为权威，不能只取当前槽。原公开reader继续走同一主体。为实际ledger中的client-order-v1从原DB加载完整原root/monetary，重用已有历史as-of/金额/事件/来源校验；不调用current、不刷新来源、不产生新凭证/表或改变原ledger。
   NativePendingOwnership实际observer在同一原SQLite视图加载这些原引用；_build及ExecutionReconcile的共享条款/身份检查以显式只读引用参数支持新契约，不能仅扩schema。旧输入/输出保持；涉及新client的ownership输出显式v2，只增加来自实际原引用的target/摘要/stage，所有资金/准入flags仍false，不能由caller输入refs/PASS。created/submitting/unknown必须仍保留未观察预留；没有原L2不能将native pending或trade判为本系统已提交。新client的仅本地terminal状态也不能靠pending空列表释放，完整终态/执行归属后续由实际combined reader提供，不猜测已终结。
2. **execution/account闭合。** 沿上述同一原引用共享体接ExecutionReconcile、NativeAccountReconcile/Check和原AccountReconcile；原持久check若需记录新输入则显式版本化，只为新wire增加原引用，旧check字节和原CAS raw ledger保持。rebuild必须重读原DB/原source/完整histories、核引用对应原事件，不能信调用者status/hash。为旧check在后续ACK后仍可重建，复用OrderAudit.verify_history_prefix；历史读取主体显式接受该实际不可变前缀，只取该前缀已有intent/claim，不能读未来L2来追认早期归属。原Prepared金额/来源验证主体下沉为同一原SQLite reader，保留原chan入口包装；仅消除对当前Engine/槽的依赖，不续期、不换公式、不合成CChanDB/上下文。手续费/资金费/原native available及旧预占不二扣。完整native pending/执行/终态证据才可解除相应已观察意图，不按TTL/缺单或本地status释放。
   主线程复核补项（先于修复）：原instrument/capacity/完整monetary reader返回后若连接被替换，必须在下一条SQL前拒绝；只检查入口和最终owner不够。直接捕获同一原connection并在原共享体的来源→SQL边界复核，不引入第二个DB/proxy/查询实现。实际execution消费者遇到损坏的原transition JSON或shape时统一隐私域错误，不泄漏底层对象/异常；保留失败原件，前一轮44模块结果仅为中间身份，不能充作修复后最终证据。
3. **原claim/L2和HTTP。** 复用原Transition确定增量及PreparedIntent的完整金额/current体；为原Engine实际加载/owned本地重建建立内部活句柄，原DB claim只消费真实句柄，不能接caller JSON或bare schema。原writer逐项核L1→唯一claim增量→L2，源预算/末尾typed monotonic、SDK/DB/guard/政策/实现均须覆盖。HTTP锁外，在actual create_order前再次重读原L2和所有硬门槛；晚变化拒绝，claim后失败保持submitting/unknown，不退回created、不重建意图或自动重发。
4. **原Engine管理/默认入口与联验。** 逐个接CCXTTradeEngine的契约/账户/参数、查询/取消/ACK/累计回报、恢复，以及TradeEngine/原运行壳受控采集入口。减少风险不借旧源作新风险准入；模型/candidate/kill/testnet/live保持独立。只有两币非空/partial和全mode/方向、LIMIT/MARKET/GTX从实际prepare→原intent→原claim→最底层fake HTTP→原回报/原生pending/execution/account→重启不重下全部通过，才评估移除新schema软件阻断；不以首个reader或单条happy path宣称完成。

## 验证边界

每个行为先真实RED，再最小GREEN。第一步先证明当前observer将新合法原金额意图丢为unidentified且缺预留；修复后新client原身份可追溯，但仍是未观察预留，无新增intent/claim/ACK/HTTP。核无L2、伪造/错DB/错target/错原事件/错monetary、额外caller refs、旧诊断伪升级、原源过龄历史与当前拒绝、terminal无原生证据、全table/稳定账户范围，以及替换库零SQL/无写入。不可从测试手工制造新schema成功claim来冒称原路径已完成。

复用未变源码/依赖/数据/环境的既有证据；共享读取/计算体和各消费者受影响回归必须重验，原订单状态机/冻结/恢复及旧byte语义保留。双CPython3.14.2/3.11.15、CCXT4.5.89，GUID basetemp/JUnit、相同用例集合与源码摘要、compileall/diff/链接、主线程review、Lore和普通push/远端SHA。禁止活pytest期间编辑；观察超时只重查原handle，不重启。各小层报告实际范围，保持第2–4步/全C5与C7外部认证未完成，不缩小或关闭原Goal。

## 本批结果：历史观察子层，不是完整第4步

原pending/execution/account实际DB入口已重载同一v4/monetary的完整原transition、不可变attempt/前缀和原来源/金额。共享原历史读取与计算体，不建立新DB/proxy、资金公式、账本或预留算法。原CAS raw ledger形状保持，原execution查询保留空信号历史字节，同时扩展同标的跨trade table读取。纯builder的显式roots只是已验证DB输入，不是采集/准入能力；实际public DB入口不接受caller roots/PASS。

新client才发显式观察版本/引用；普通与native持久check仅新版本增加完整client_roots/journal_prefix，冷重建重读原DB，不信重封hash。新意图仍是未观察预留；本地ACK/相同native trade行缺L2仍unowned，仅本地terminal或pending空集不释放。旧schema/无新client的文档字节、导入路径及原Cost/Envelope不升级。来源过龄和后续ACK不使历史检查漂移，也不把历史点续期成current。

主线程review补齐来源→SQL连接连续性与损坏引用域错误，3个尾部连接替换和2个坏原引用先5 RED再5 GREEN。此前4241 passed/1 skipped/3 warnings为修复前中间身份，保留原件，不当最终证据。最终双版同44模块各4246 passed/1 skipped/3 warnings、0failure/error/deselection，4247唯一用例集合相同；新增47项全通过，完整85 capacity prepare/CAS/current/cold与79 prepare Last包含。唯一skip为原Binance income不适用的isolated position cash channel，不算PASS；3条既有AUC小样本警告未隐藏。源码/测试SHA跨双版不变，双版compileall/diff通过，pytest进程0后才更新文档。原件与摘要见[台账](../reports/2026-10-20-crypto-full-version-progress.md)及[审计§41](../reports/2026-10-22-native-fresh-admission-audit.md)。

第2步真正原生terminal/已观察释放仍未完成；第3–4步原owned claim/L2/HTTP前、Engine查询/取消/回报/恢复与默认入口全链矩阵必须继续，不能以永久拒绝替代完整开发。全消费者和fake E2E闭合前，新金额schema的claim/send阻断保留，旧v2/v3诊断不升级，不得手造成功L2当原路径证据。C5–C7/OKX金额/完整Goal未完成，Goal active；A/P/F不重问，实际配置、权限与交易/研究门禁不变，无真实端点、正式绩效或外部认证。
