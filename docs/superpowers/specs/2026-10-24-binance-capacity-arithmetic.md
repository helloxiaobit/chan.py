# Binance逐单资金算术：已知包络与已批准V1价格假设

日期：2026-10-24。基线2d95f4665127a0115a2ba62b41f86153a06477ff，full-version已推送且clean。

[本地模型＋适用原生额度方向](2026-10-24-native-per-order-capacity-design.md)已批准，不重新审批。原完整C0–C7 Goal现由用户续行恢复active；先前blocked状态保留为历史。本稿不改配置、规则、候选、资金或交易门禁，开发仅合成/fake。

## 1. 可以直接实施的必要算术子层

这一层只计算已提供数据下的持仓/普通挂单及假设新单的保证金包络，不判断余额足够、订单准入或服务端接受。不引入新的价格缓冲、费率、档位系数或资金政策；不是完整资金模型的替代完成条件。

依据[Binance保证金说明](https://www.binance.com/en/support/faq/detail/4f83b65d83654b5e933f85ef12bf769d)的one-way与hedge公式：每symbol、每positionSide独立令Q为**带符号币数**、M为已提供mark、P=Q×M；B/A为该腿所有普通未决LIMIT单的剩余币数×各自limit price的买/卖总值。filled部分只在已有实际持仓中出现，不再次作为pending计量。

```
H = max(abs(P+B), abs(P-A))
IM = H / 当前该symbol原生leverage
```

one_way仅BOTH；hedged分别LONG(Q>=0)、SHORT(Q<=0)，先按带符号Q求两腿，再相加，不先净额合并或把SHORT取正。不同symbol只在同一已声明USDT单位下求和；标的暴露也分别保留，不跨币净额。普通reduce-only/hedge关闭方向的挂单仍保留，不假定它们会被自动取消、释放预占或立即减仓。条件/算法/复杂/无法重建的订单、未终结MARKET与其他未知组合拒绝；不从pending空/消失推断本地unknown已释放。

另计算同腿剩余币数的端点包络乘M，并与H取较大值作为**本地标的暴露诊断**；hedge两腿相加，不把该量冒称平台已核的最终档位或可下单额度。hypothetical候选只增加一个显式币数/张数/valuation_price的买或卖值，不伪造未来native orderId/ACK/pending行。valuation_price仅是调用者给定的数学输入，本层没有证明其是已批准的assumed-price或服务器上界。

文件范围：Trade/NativeMarginEnvelope.py、对应测试与状态文档。API calculate_binance_margin_envelope(*,markets,positions,pending_orders,mark_prices,symbol_configs,position_mode,candidate)。markets复用原声明池；positions取原生positionRisk行的symbol/positionSide/positionAmt/保证金币；pending_orders取原regular raw，直接复用NativePendingOrders._order的字段/partial/复杂条款/双单位检查；settings复用NativeCapacityEvidence原配置解释。候选必须显式instrument_id/position_side/side/base_quantity/contracts/valuation_price，开新风险只允许BOTH双向、LONG BUY、SHORT SELL；不通过该API给降风险增加新权限。

Fraction只来自原ExecutionFacts精确数值边界；沿AccountReconcile._ratio输出约分后的numerator/denominator，不把1/3、1/7或1/21截成50位小数，也不猜USDT/手续费舍入量子。输入克隆/确定排序，拒绝重复腿/orderId、错市场/模式、非正mark/leverage、币数张数不等和非有限/bool/float金额；不修改原输入/DB/SDK。空提供列表只表示算术求和空集，不是实际账户空仓/原生缺单证明。输出flags=false，实际完整性/身份/当前性与原账本仍由原受控消费者证明。

验收：手算非空双symbol、one_way正/负持仓、hedged四腿、多笔部分成交与关闭方向挂单；before/after/差额逐项精确。测试另用所有挂单成交/不成交顶点枚举求max，独立于生产端点公式。包含非终止分数、wrong leg/side/币数单位、缺标的mark/settings、重复/复杂/未知、输入不变与零SDK/配置导入。严格先RED再最小GREEN，双解释器适用回归、compileall/diff/Lore后才能记录该子层完成。

GREEN后的局部清理计划：已有56项hand/vertex/拒绝回归保护原输出。新增标的双腿暴露汇总已先观察2项缺字段RED；将内部_frame保留Fraction到统一序列化处，由同一frame计算体汇总IM/暴露，删除第二份端点公式，不通过读取自己刚输出的ratio字典来重新做金融计算。原公开字段/数值不变，只增加显式标的汇总；继续用上述回归及新增手算检查，不改旧源码/账本。

## 2. 完整金额模型V1价格/费用估价：路线P已专门批准

2026-10-24，用户在本节对应的专门问题中明确答复“批准路线P：接受明确的V1价格假设”。不再重问A或P/N；以下alpha=0.0015、方向/订单类型的R/Loss和费用估价可按具名客户端V1继续冻结输入契约并TDD实现。批准不自动补齐fresh Last/BBO/fee币路径、完整账户/档位/原CAS消费，也不是服务器成交界限、锁额/必接单或真实I/O许可；尚未完成的模型与全部门禁保留。下文历史结果中的“P未批准”描述对应当时状态，不是当前阻塞。

新增的实质选择是**是否把文档assumed-price当作具名客户端估计**，而非服务端最大成交价证明。[开仓成本FAQ](https://www.binance.com/en/support/faq/detail/87fa7ee33b574f7084d42bd2ce2e463b)当前给出0.15%的assumed-price示例，并标注信息可能过时；这不是执行上界。只读instrument里的marketTakeBound、报价或limit price也不能未经规则证明就改称所有订单/未来时刻的最大成交价。

### 路线P：明确命名的FAQ价格假设V1（本次已批准）

若接受该客户端估计，版本必须明记alpha=0.0015及引用/更新日期，不将其称为平台永久规则、可配置搜索参数、原生上界或服务承诺。实际L/Mark/Last/BBO、maker/taker费率仍全部从受控fresh来源取得；不得使用旧SDK ticker/fees缓存。价格改变不能回封旧证明。

建议完整价格/新单成本如下，均为**条件于该估计**的本地规则：

- 限价BUY：R=实际limit；限价SELL：R=max(Last×(1+alpha),Mark,limit)。MARKET双向R=Last×(1+alpha)。所有LIMIT（含post-only）的开仓损失沿通用限价公式以limit计算，不额外豁免为0；MARKET以R计算：Loss=q×max(0,side×(X-Mark))，side为BUY=+1/SELL=-1。post-only只改变下述费用角色，未改变价格上界或资金门禁；实施衔接见[完整接入计划](../plans/2026-10-24-binance-capacity-v1-integration.md)。
- 新单initial=q×R/L；**不因为相反持仓/关闭挂单而提前拿释放额抵扣**。现有native available中的旧挂单/持仓预占不再扣一次；第1节包络仍逐symbol/腿校验并记录，不可因此跳过账户、完整pending归属或订单后杠杆/档位上限。

R由原native decimal输入精确计算后可能超过50位输入精度；计算结果不是新的native输入，不得截短或转float再塞回旧API。现有[精确桥接](../plans/2026-10-25-binance-v1-price-book-bridge.md)复用同一book计算体、单独内部rational wire及原check/L0；旧公开decimal入口/schema不变，仍无资金准入。
- 新单费用估计：post-only按limit且rate=max(0,maker)；MARKET按max(R,Mark,Bid,Ask)且rate=max(0,taker)；其他LIMIT按max(R,Mark,Bid,Ask,limit)且rate=max(0,maker,taker)。Fee=q×费用估计价×rate。不给负费率返佣信用。此费用价格同样不是实际成交上界，须连同R一起获批，不能隐藏在实现中。
- Cost=initial+Loss+Fee，以精确Fraction比较已核USDT native available>=Cost，恰界允许，无epsilon/钱数舍入；不是单独用notional/leverage充当完整能力。不能猜费用币；初始V1仅在feeBurn=false、USDT原生费用路径已核时产生该币种成本。BNB开启、外币/借贷/isolated/未知税费或费率适用性缺失均继续拒绝，不能改用户开关来制造可过输入。[官方费用说明](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554)描述BNB支付及不足时回落USDT，但不据此猜转换价或折扣后本单原币额度。
- 完整模型另须用实际symbolConfig.maxNotionalValue、完整档位/当前L及全book订单后暴露核限额；notionalCoef的effective范围若未核，不二次乘/忽略调整而放行。实际余额/权益、资金/fees/wallet、完整账本/unknown、模式/标的池、所有源年龄/跨度/skew和唯一原CAS占用全部保留。具体档位选择/账户绑定实现仍须独立证据；上述成本提案不是免检它们。

该路线降低“必须有服务端执行界限证明”的要求，因此由本次独立批准授权，不从上一轮A方向暗推。通过只指该版本、价格假设和已核输入下的本地条件；不保证真实成交费用/保证金、未来价格/资金费、锁额或必接单。代码须明示版本/假设，不能把新批准迁移为旧证明续期或自动接入claim/HTTP/default。

### 路线N：继续只接受有原生执行界限依据的价格（未选，保留背景）

仍允许已批准的本地金额模型，不退回“只接受原生资金锁”。但不采用上述0.15%/费用估价；只有取得适用于本单类型/方向的原生价格界限或更明确的用户授权价格政策后才做其资金判断。目前无法核实的类型继续拒绝，不能凭实现方便改成仅空仓/post-only后宣称完整Goal完成。第1节真实book算术和其他不依赖该选择的授权工作继续。

两条路线均保留全部candidate/testnet/live、配置、C7及原资金/claim/default门禁；不触发真实I/O。此处只需确认P/N这项新的价格假设差别，不重问A方向或已批准的账户级原CAS串行协议。

## 3. 第1节独立算术子层离线结果

本节为当时的分段结果，P目前已专门批准，见第2节；不将旧待批状态继续作为当前阻塞。

已实现第1节，未实现/批准第2节P。新增79项测试，双解释器相同六模块各721 passed、1既有skip、0failure/error/0warnings，722个唯一用例集合一致；compileall/diff通过，详细身份见[开发台账](../reports/2026-10-20-crypto-full-version-progress.md)。既有skip来自Binance income没有isolated position cash-channel，不是新测试跳过、费用缺项默认为0或模型已验收。

实际复用原数字、ratio、pending与symbol-config解释；按预写计划保留一份Fraction计算体，统一末端序列化/汇总，未复制保证金端点公式。缺API/双symbol算术2 RED、缺标的暴露汇总2 RED、numeric native ID别名重复计量2真实DID NOT RAISE RED，均先观察后最小修复。去重只比较同一symbol的数字native ID，不改raw或持久ID；不同symbol同ID仍独立。

非空手算例：one_way前2102/21、后4939/42；hedged四腿前6467/42、后3601/21；同向候选的额外IM均35/2。另有相反候选使额外IM为0的例子，但flags仍false，不能因此免除开仓损失/费用/余额/原账本或声称零成本。标的暴露按腿汇总，未跨币净额；调用者价格仍标明provided_untrusted_reference，不因算术测试通过而升级为native价格上界/已批准价格政策。

P/N问题已单独向用户提出；未回复时严格原价格依据边界不变，不将默认选择视为答复。本子层/输入hash/候选投影不可作资金许可，不接原intent/claim/default，不重封旧来源/订单，也未选择新的执行schema。完整金额模型、跨来源/L0/L1/L2/全reader/HTTP/default、OKX与C7仍待，完整Goal保持active而非完成。

## 4. 原生杠杆/名义限额的必要检查（实施前冻结）

这一子项不依赖P/N：只比较第1节的**已提供book投影**与同一原生capacity来源中的限额。不是完整资金能力，也不证明这些持仓/pending/mark属于该账户或当前真实全书；受控prepare/原check/L0/L1/L2绑定仍须随后完成。保留全部原阻断，不新增价格/费用估计。

依据[官方账户API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)：symbolConfig给当前leverage/maxNotionalValue；每档initialLeverage为该档最大初始杠杆，notionalFloor/Cap为名义门槛/上限。coef仅描述为用户档位倍数，尚无已核证据说明返回区间是否已调整。因此非中性notionalCoef继续拒绝计算，不忽略或二次乘；缺coef只使用原样返回的区间，不写入猜测的1。显式精确等于1时无需变换。此处不使用maintMarginRatio/cum计算维持保证金或宣称维持公式已核。

文件为Trade/NativeLeverageLimits.py及对应测试。API evaluate_binance_leverage_limits(capacity_evidence,*,positions,pending_orders,mark_prices,position_mode,candidate,max_age_ms,max_observation_span_ms)。预算必填；用原reader在计算前后核完整来源/SDK/源码/窗口，来源字节与全部输入须不变。声明池和当前配置**只从该来源取**，不另收caller的markets/configs或封好的book结果；直接复用原calculate_binance_margin_envelope从raw重算，不复制端点/单位/partial公式。

完整raw档位按返回顺序核数值编号1..N、首floor=0、前cap=后floor、cap递增、initialLeverage不增加；不排序补洞或截断表。对该symbol实际L，取所有initialLeverage>=L档位的最大reported cap为compatible cap；没有这样的档位则记录leverage_unsupported。分别精确比较订单前/后symbol暴露<=symbolConfig.maxNotionalValue及compatible cap，两条独立约束都要满足，恰界允许、超过任意正分数拒绝。这里比较上限而不分配边界所属维持档位；不假设config cap必等于bracket cap。hedge暴露沿原包络先分腿再相加，不跨币净额。

输出有限canonical文档，列来源完整SHA、原account_context、重算book、每标的原L/两个cap/前后暴露和确定性违规记录；status仅within_observed_limits/exceeds_observed_limits。coverage明确provided_book_against_observed_limits_only，book_origin_verified/economics_complete/native_admission_verified均false。有效输入上的超限返回可审查记录，结构/源/系数歧义拒绝，不通过默认0或无限额制造可过结果。零GET/零DB/零订单/零配置写入；来源hash不是自采、真实当前性或发送能力。

验收先缺API行为RED；非空双symbol、one_way/hedged/不同native L、partial/关闭方向pending，独立顶点参考核暴露；当前cap和兼容cap分别恰界/极小超界、旧书已超限、无兼容L、非候选币超限、四腿不可净额。缺档/重排/断层/overlap/递增L/coef歧义、caller重封来源、过期/计算耗时/输入末尾变异均拒绝。复用原来源及book回归，双解释器验证、compileall/diff、主线程review与Lore后仅记录本子项完成。

## 5. 第4节限额检查的离线结果

已实现NativeLeverageLimits及169新增用例。双解释器同三模块各434 passed/0failure/error/skip/0warnings，434唯一用例集合一致；双版compileall/diff通过。组成169新＋79原book＋186原capacity输入；原未变账户/归属/CAS等证据按原范围复用，不冒称本轮全跑。所有pytest结束后才更新文档，未修改被测生产代码或测试身份；完整SHA/JUnit/RED产物见[台账](../reports/2026-10-20-crypto-full-version-progress.md)。

TDD先4项缺API RED，36项完整档位/系数DID NOT RAISE RED，4项无兼容L却伪造数值0-cap的RED，4项序列化后age遗漏RED，20项业务时钟不前进时的正1ns/非法或倒退核心钟RED；逐项修复后GREEN，非用失败结果重标PASS。未增加新的时间容差：沿原_window，在typed业务时刻基础上以整个计算的核心monotonic差向上取整毫秒作保守使用时刻上界，同时保留计算前后原reader。恰界+零耗时可过，正1ns不能被截为0。

非空手算TEST订单后暴露one_way=325、hedged=275+201.5=476.5；两个独立cap均验证恰界及1e-30两侧。五个原生L边界验证1000/5000/10000兼容cap，完全不兼容时cap=None并显式leverage_unsupported，不填0/无限额。ALT原book超限即使候选属于TEST也返回before/after违规；原输入/来源与限额记录均有限canonical，不写库/SDK或续期旧源。

本层仍无真实全书来源/模式/原账户check绑定，book_origin_verified=false；source SHA/within_observed_limits不是自采能力、资金充分或服务端锁额。既有source reader核SDK/源码与时间只说明有限数据契约，非整个宿主/真实服务器认证。没有P批准、价格/费用估计、维持保证金/coef应用、原CAS接入或默认发送；旧schema/证明/订单不重封。下一步沿原依赖接实际账户/pending/mark及受控prepare，再完成明确价格依据、费用/余额、原L0/L1/L2与全部reader/default；C5–C7及原完整Goal继续active未完成。

## 6. 原持久检查到book的只读适配（实施前冻结）

文件Trade/NativeAccountLimits.py及tests/test_native_account_limits.py。API observe_binance_account_limits(chan,*,check_id,capacity_evidence,market_evidence,candidate,policy,max_age_ms,max_observation_span_ms)。只接原CChanDB与source文档/本单假设/显式预算，不接caller的positions/pending/marks/position_mode/config或已计算book；本步不做GET、原intent/claim/HTTP及资金充分判断，原L0/L1/L2/default保持阻断。

先以原capacity/market reader核严格来源，capacity context与原check相同、完整市场/SDK身份相等。用原capture_native_order_boundary捕获原持久L0，再在同一原owned SQLite视图读取原check并assert该L0；计算后再次在原owned视图assert同一L0。复用原数据库/连接/table所有权守卫，不查询替换库，不以新采基线覆盖旧L0或排除第三方账本。原最新来源/冻结/全ledger/journal完整性检查保持原义；不增表或变更旧schema/证明。

book仅由所读check.inputs.after.raw.positions的signed positionRisk行、check.inputs.pending.payload.orders的全部regular raw行、独立market observations的mark.price及check.report.components.margin.position_mode重建。每个声明symbol的旧account symbolConfig与本次capacity config须核原字段（symbol/marginType/isAutoAddMargin、精确native leverage）；额外未使用的account配置不当作新市场权限。声明池严格相等、仅cross USDT；条件/算法/未知/未决非LIMIT仍拒绝，不用norm quantity替换signed raw、不移除关闭方向或用余额/pending为空释放unknown。候选价格仍provided_untrusted_reference，只进入原共享限额计算。

总时间政策沿原component policy：仅为委托原_assert_current_windows构建局部副本，将两个必填capacity age/span预算加入capacity角色，不改原policy字节或旧reader契约。把capacity整窗及其finish端点加入additional，复用同一total span和max_source_skew_ms，使较晚的资金参数不能与旧book各自过关却逃过联合时差。仍用本地request窗口，不伪称native生成时刻；最终覆盖本次全部读取/核算/序列化与owned退出耗时，typed业务钟及核心monotonic向上界无新容差。

输出chan-binance-account-limits-v1，只引用实际check/source/L0身份、派生book输入SHA及原共享限额结果。book_bound_to_original_check=true仅表示从原持久数据派生且两次原L0一致；source_collection_owned/book_origin_verified/economics_complete/native_admission_verified均false。文档来源在本入口前已取得，本步没有原prepare的collector所有权，所以一致JSON/哈希/本报告不能获得新风险权限，失败也不凭未知DB宣称已冻结。后续受控prepare必须自己取得/绑定来源，再按原CAS逐单复验；此只读适配不是该整链已完成。

先用真实原SQLite/CAS/费用/资金费/partial非空两币check做缺API RED，再核从原source逐项派生、重启可复算、零GET/零写入与四种one_way/hedged/多空；复用原book四腿和限额独立参考回归。绑定reader测试用全新合成历史capacity文档，不冒充当前SDK testnet采集成功，不改disableFuturesSandboxWarning/路由或既有收据。原capacity collector的真实SDK＋fake底层/签名拒绝证据单独保留，不以结构reader测试替代。

反向须先保护：错账户/环境/SDK/池/配置/mark，过期/联合skew或total span，missing/dirty/frozen/较新未整合来源、全账本/前缀变更、外层事务/替换DB、最终输入/来源/连接变异均拒绝且不写订单/冻结/许可。合成counterexample必须让每个source单独fresh却联合过界，不能只测reader本来会拒绝的坏SHA。适用双解释器组合、compileall/diff/主线程review/Lore后才记录本适配完成，完整价格/费用/余额、受控prepare/L0/L1/L2/全reader/default及C7仍待。

局部读取调整计划：已有4个原库/重启GREEN及28个联合身份/时间真实RED。仅把新模块里的直接read_check替换为原NativeCurrentComponents._sources_snapshot，在同一owned视图复用原check和真实execution observation窗口，不复制时间选择或执行读者。旧生产函数/表/schema不改；后续联合时间核验直接委托原_assert_current_windows，保留相同ledger与原L0前后复验。

## 7. 第6节原持久check适配的离线结果

新增NativeAccountLimits与109测试；双解释器同五模块各696 passed/0failure/error/skip/0warnings，696唯一用例集合差异0，双版compileall/diff通过。组成109新＋169限额＋79book＋186capacity＋153原L0，完整SHA/JUnit/失败证据见[台账](../reports/2026-10-20-crypto-full-version-progress.md)。新生产代码/测试在两版间摘要不变，17430/74660均exit0后才更新文档。原组件/状态机/schema/默认入口代码未改，未跑的其他旧验收不记为新结果。

原生模式/当前L、signed positionRisk和全部regular raw pending从实际原check读取，mark从独立market；原snapshot校验及L0断言始终使用原DB/连接/table。两组各自fresh但联合total/skew过界的8项反例曾真实返回，连同杠杆/auto-add/metadata/SDK不一致20项，均先28 RED后修复。重启复算相同字节；非空两币、partial/费用/资金费的真实原SQLite夹具，独立顶点参考沿原book实现分离；四腿同账的金额参考由本次重跑的原79/169组覆盖，不把新适配四种模式/方向误称为其本身的四腿执行E2E。

收尾16项RED证实时钟读后输入、DB或真实原CAS可变化；将最后业务时刻移到最终原L0复验前，并用核心monotonic整段向上毫秒界覆盖退出/核算成本。4项正1ns RED先明确零成本baseline通过再注入成本，避免被另一个skew规则提前拒绝而伪GREEN。8项计算后source实现/内部clone漂移RED补末尾原reader与双向字节核验；再8项证明reader回调可触碰替换库，入口先固定原owner、每个reader后复用原守卫，替换库含BEGIN/PRAGMA的SQL trace变为零。无新预算/容差/状态机，不通过重采或忽略本单释放unknown。

book_bound_to_original_check=true仅说明最终原owned视图中的数据关联，不承诺释放读视图后服务器/其他连接不会变化，更不提供可转让CAS能力。source_collection_owned/book_origin_verified和资金/admission flags仍false；source文档是本入口前的数据，未变成受控prepare所有权。后续必须以实际Engine自采/准备身份绑定该适配与明确完整金额模型，再在原L0/L1/L2及HTTP/default每单重验。P未批准、无价格/费用放宽，无真实请求/配置/规则/候选或旧产物变更；C5–C7和完整Goal仍未完成。
