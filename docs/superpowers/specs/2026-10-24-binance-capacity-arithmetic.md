# Binance逐单资金算术：已知包络与待选价格假设

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

## 2. 完整金额模型V1提案：尚未确认，不实施依赖代码

新增的实质选择是**是否把文档assumed-price当作具名客户端估计**，而非服务端最大成交价证明。[开仓成本FAQ](https://www.binance.com/en/support/faq/detail/87fa7ee33b574f7084d42bd2ce2e463b)当前给出0.15%的assumed-price示例，并标注信息可能过时；这不是执行上界。只读instrument里的marketTakeBound、报价或limit price也不能未经规则证明就改称所有订单/未来时刻的最大成交价。

### 路线P：明确命名的FAQ价格假设V1（需此次专门确认）

若接受该客户端估计，版本必须明记alpha=0.0015及引用/更新日期，不将其称为平台永久规则、可配置搜索参数、原生上界或服务承诺。实际L/Mark/Last/BBO、maker/taker费率仍全部从受控fresh来源取得；不得使用旧SDK ticker/fees缓存。价格改变不能回封旧证明。

建议完整价格/新单成本如下，均为**条件于该估计**的本地规则：

- 限价BUY：R=实际limit；限价SELL：R=max(Last×(1+alpha),Mark,limit)。MARKET双向R=Last×(1+alpha)。非post-only限价的开仓损失以limit计算；MARKET以R计算：Loss=q×max(0,side×(X-Mark))，side为BUY=+1/SELL=-1。
- 新单initial=q×R/L；**不因为相反持仓/关闭挂单而提前拿释放额抵扣**。现有native available中的旧挂单/持仓预占不再扣一次；第1节包络仍逐symbol/腿校验并记录，不可因此跳过账户、完整pending归属或订单后杠杆/档位上限。
- 新单费用估计：post-only按limit且rate=max(0,maker)；MARKET按max(R,Mark,Bid,Ask)且rate=max(0,taker)；其他LIMIT按max(R,Mark,Bid,Ask,limit)且rate=max(0,maker,taker)。Fee=q×费用估计价×rate。不给负费率返佣信用。此费用价格同样不是实际成交上界，须连同R一起获批，不能隐藏在实现中。
- Cost=initial+Loss+Fee，以精确Fraction比较已核USDT native available>=Cost，恰界允许，无epsilon/钱数舍入；不是单独用notional/leverage充当完整能力。不能猜费用币；初始V1仅在feeBurn=false、USDT原生费用路径已核时产生该币种成本。BNB开启、外币/借贷/isolated/未知税费或费率适用性缺失均继续拒绝，不能改用户开关来制造可过输入。[官方费用说明](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554)描述BNB支付及不足时回落USDT，但不据此猜转换价或折扣后本单原币额度。
- 完整模型另须用实际symbolConfig.maxNotionalValue、完整档位/当前L及全book订单后暴露核限额；notionalCoef的effective范围若未核，不二次乘/忽略调整而放行。实际余额/权益、资金/fees/wallet、完整账本/unknown、模式/标的池、所有源年龄/跨度/skew和唯一原CAS占用全部保留。具体档位选择/账户绑定实现仍须独立证据；上述成本提案不是免检它们。

该路线降低“必须有服务端执行界限证明”的要求，因此不是上一轮方向批准自动涵盖的新默认值。通过只指该版本、价格假设和已核输入下的本地条件；不保证真实成交费用/保证金、未来价格/资金费、锁额或必接单。未经此次明确批准，不编码alpha、费用估计价或它们依赖的资金通过分支。

### 路线N：继续只接受有原生执行界限依据的价格

仍允许已批准的本地金额模型，不退回“只接受原生资金锁”。但不采用上述0.15%/费用估价；只有取得适用于本单类型/方向的原生价格界限或更明确的用户授权价格政策后才做其资金判断。目前无法核实的类型继续拒绝，不能凭实现方便改成仅空仓/post-only后宣称完整Goal完成。第1节真实book算术和其他不依赖该选择的授权工作继续。

两条路线均保留全部candidate/testnet/live、配置、C7及原资金/claim/default门禁；不触发真实I/O。此处只需确认P/N这项新的价格假设差别，不重问A方向或已批准的账户级原CAS串行协议。

## 3. 第1节独立算术子层离线结果

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
