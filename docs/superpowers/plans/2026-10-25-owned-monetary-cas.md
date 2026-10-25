# 同次受控金额采集与原CAS闭合

2026-10-25，基线pushed/clean `612e0a062e83c6f52ce0fce95d003a010a597114`。继续[已批准F接入计划](2026-10-25-approved-standard-commission-integration.md)第3–4步和[账户串行协议](../specs/2026-10-23-native-per-order-admission-protocol.md)，不是新的批准问题或缩小目标。A/P/F已批准，原Goal active。严格主线程串行、fake、原配置/交易与研究门禁不变，无新依赖。

## 最终线与分阶段边界

原受控入口 `acquire_binance_standard_prepared_intent` 沿现有acquire共享体自行执行：原prepare→instrument→同一SDK closed-field capacity v2→原components/check→原prepare活句柄Last→原持久check派生完整book/Cost→原L0→原intent CAS。显式instrument/capacity/Last age/span均必填；不接受caller source/check/Cost/fee currency/PASS或时钟。候选九字段只能从实际prepare contract与原信号方向派生。

沿原prepared binding新增v4，固定原identity/instruments/components/SDK/policy/基线、capacity源/policy、Last源/policy及完整monetary文档。monetary包含实际候选、原check/source/市场/book摘要、原限额报告、Cost、F适用假设与native cash basis；所有原native/economics权限flags保持false。新契约 `chan-native-client-order-v1` 仅在原v3完整执行字段上增加 `monetary_basis_sha256`，由v4完整monetary文档计算，再计算contract_id；原intent journal与Root绑定同一内容，无第二账本或余额分配表。

这是同一最终金额binding，不另建将来废弃的diagnostic。第3步可验证持久意图、历史与当前金额重算，但第4步未完成前新契约在claim/Engine/默认发送仍拒绝。旧native-cas契约及binding v1–v3维持原诊断/拒绝语义，不重封、迁移或追加金额凭证；未来启用消费者也不能把历史未知提交释放或重做意图。

## 修改前的复用/清理计划

1. `NativeLastPrice` 仅将原reader主体提为私有as-of入口，公共签名/当前钟/预算不变；历史只可用原intent时间验证旧窗，不能续期current。`NativeLeverageLimits`私有计算体增加同类checked_ms，公共API不收该参数；历史仍重算同一数学体，不复制reader/金额公式。先RED证明缺私有入口/旧时点重算失败，并保留原366 Last、186 capacity、169/16 limits适用回归。
2. `NativeAccountLimits`把原saved check派生book与standard limits/Cost选择提为小型共享私有体，原公开结果字节/clock与DB owner行为不变。原109/68 account、38 standard money、79/66 book与161 Cost继续保护；独立Fraction参考从raw输入计算，不使用生产Cost作oracle。原check仍是唯一cash来源，旧预占不二扣。
3. `NativePreparedIntent`复用一个acquire主体；新v4实现闭包额外包含Last/OrderCost及其实际依赖，旧路径不新增GET或默认值。历史reader用原immutable attempt的方向/quantity/intent_ms独立重算monetary，当前与原CAS用当前来源核验及包含全部末尾工作/事务退出的monotonic上界。每个可能回调后先核原DB/连接/table/SDK/guard/policy/clock，再查询/写入；replacement库零SQL，失败沿原sticky unavailable及回滚，不声称冻结未知库。
4. `OrderAudit`仅保留新金额摘要字段，原root/attempt完整比较不豁免。`db_util`新契约必须同时有原L0与原活prepare，不能裸传schema；`NativeOrderTransition`在原writer内验证同一v4/monetary/真实候选后才允许intent，L1仅本单原增量。历史/current均须完整新金额，而非仅接受schema。
5. 第4步依赖以上同一最终binding：`NativePreparedClient`、current/admission、Transition claim/L2、Engine HTTP前、pending/execution/account/恢复以及原默认入口逐个接全量验证。持有旧源的历史读取与管理已有风险，不伪装为新风险fresh-admission；新风险每次仍须完整当前金额/原唯一增量/账户级单未观察意图。仅全部消费者与fake E2E完成才解除新schema对应的软件阻断，candidate/testnet/live等独立门禁不变。

## 验收和状态

先观察新入口缺失RED，再最小实现；六种订单/两种模式、两币非空/partial、原cash恰界/微不足/非候选cap、已知额外收费/未知模式、Last/cap错误/缺失/过期、晚真实竞争CAS、源码/owner/资金计算末尾变异均拒绝且无错误intent或HTTP。历史超过age仍可按原intent读，但当前/claim不得借旧时点；原source和模型/假设全部重算匹配，错误/缺字段不得只信status或hash。

双CPython3.14.2/3.11.15、CCXT4.5.89，GUID basetemp/JUnit；禁止活pytest期间编辑。复用未变身份/依赖/环境的适用证据，有影响的共享体及原CAS/current/cold组合重新验证，记录准确范围/用例集合/源码摘要、compileall/diff、本地链接和主线程review。Lore提交/普通push/远端SHA核对后记录子项，完整金额链/C5–C7与原Goal未完成就不关闭。

## 本批结果：同次来源/金额原 intent 子层（第3步）

实现的仍是上文同一最终binding，而不是另一个将来替换的只读诊断。原受控入口自行执行实际prepare、同一SDK的closed-field capacity v2、原components/check和未消费prepare的Last；从原native cash与完整book计算原V1 Cost及原生限额，在原intent SQL/journal/L0/L1中绑定完整monetary。新contract为chan-native-client-order-v1，仅增加monetary_basis_sha256；claim仍在原writer内拒绝，Engine/全部执行reader/default没有扩白名单或解除阻断。旧v2/v3不新增请求、不重封。

NativeLastPrice/NativeLeverageLimits仅增加私有as-of共用体，公共API不收checked_ms。历史按原immutable intent时间重算原Source/Cost/F和所有摘要，不借当前钟续期；current及原CAS继续按当前窗口重算。NativeAccountLimits抽出原book/standard Cost共享体；不新增公式、依赖、余额分配表或订单状态机。v4实现闭包包含Last/Cost及实际依赖，current/原CAS末尾、冷启动owner均核完整闭包。

真实RED包含缺API/历史入口8项、初次Cost计时遗漏1项、金额末尾完整实现闭包2项、cold闭包1项、current snapshot耗时和末尾instrument年龄2项。修复只复用原窗口和typed monotonic上界，正纳秒向上取整，不增加预算、epsilon或新源时间。另有76项中75pass/1fail属于测试未复原故意实现变异便要求历史可读；该已变更实现时代的历史应拒绝，故修正测试恢复步骤后再核原历史未改，未放宽产品校验，原件保留。

最终新增78项：四种mode/方向×LIMIT/GTX/真实MARKET None、原生余额恰界及差1e-40、全池非候选cap、费用/缺来源不降级、原SQL/reference回滚、真实晚竞争CAS、替换库零SQL、完整body重封拒绝、历史过龄/current拒绝及原SDK冷重建。CPython3.14.2为同一冻结源码的78项专项＋36模块3808项回归，3.11.15为37模块3886项完整运行；各3886唯一用例、0failure/error/skip、无deselection，集合差异0。两版各3条既有小样本XGBoost AUC警告，不隐藏或称零警告。CCXT均4.5.89、pytest均9.1.1；原环境中XGBoost分别3.4.1/3.2.0、NumPy2.5.4/2.4.6、pandas均3.0.6，未安装/升级依赖，不冒称所有依赖版本相同。

受影响37模块清单（tests/前缀、.py后缀）：

```text
test_account_risk_freeze test_crypto_order_contract test_crypto_order_recovery test_execution_store test_m6_trade test_native_account_limits test_native_admission_freshness test_native_admission_interval test_native_capacity_evidence test_native_capacity_prepared_intent test_native_last_price test_native_leverage_limits test_native_margin_envelope test_native_market_evidence test_native_monetary_prepared_intent test_native_order_boundary test_native_order_cost test_native_order_transition test_native_preparation test_native_preparation_sources test_native_prepare_context test_native_prepared_client test_native_prepared_current test_native_prepared_intent test_native_prepared_last test_native_standard_capacity test_native_standard_order_capacity test_native_v1_account_limits test_native_v1_leverage_limits test_native_v1_margin_envelope test_order_audit_history test_order_report_cas test_restore_orders_cli test_trade_cycle test_trade_safety test_trade_sqlite_transaction test_trade_state_machine
```

双版compileall Trade与新测试、Git diff检查通过，源码/测试SHA跨最终运行一致；确认相关pytest进程0后才编辑本记录。精确JUnit/RED/源码摘要见[验收台账](../reports/2026-10-20-crypto-full-version-progress.md)和[审计§40](../reports/2026-10-22-native-fresh-admission-audit.md)。主线程按review模板复核，无代理/工作树/OMX。原Cost和Envelope身份不变，真实配置/规则/权限/候选/旧产物/研究不改，无真实端点或正式绩效读取。

第4步仍未完成：同一v4/金额契约必须继续进入原claim/L2、HTTP前、pending/execution/account/恢复及默认入口，不能仅扩schema集合；历史管理和新风险鲜活性不得混同。现存created/submitting/unknown不自动释放，不为旧证明补新实现摘要。全部消费者和fake E2E通过前不启用新schema的软件发送路径；C5–C7、OKX金额链和完整Goal继续未完成，原Goal active，不替换、缩小或关闭。
