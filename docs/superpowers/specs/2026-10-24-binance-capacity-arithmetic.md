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
