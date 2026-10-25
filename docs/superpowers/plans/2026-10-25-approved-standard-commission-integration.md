# 已批准F：标准佣金输入与完整金额接原账户/CAS

2026-10-25，基线pushed/clean `4476e07952e6f6feea3ec964f783b56bae3e9146`。[F已批准](../specs/2026-10-25-binance-standard-fee-applicability-choice.md)，A/P与账户级串行协议不重问。按writing-plans→executing-plans/TDD→verification-before-completion，主线程严格串行，无代理/新依赖/真实端点/实际配置或交易门禁修改。此实施拆分不是额外审批或替代C0–C7目标。

## 结果与兼容边界

完整结果必须从原Engine的实际prepare/同次原SDK采集进入原account check，原native available/equity、全账户/挂单/档位与实际候选重算Cost，再由原L0/L1/L2及claim/HTTP/default/恢复消费者逐单核验。F仅改变费用适用假设；不能以来源或只读金额报告代替完整交付。

旧capacity v1、旧public API/文档字节/投影语义与订单绑定不重封。新路径仅消费fresh原生采集的closed-field capacity v2；不把v1丢弃未知字段后的文档补marker后升级。来源仍fee_currency=None、economics/admission=false，不能声称原生完整费用/资金已经证明。纯NativeOrderCost原V1输出与公式不改，外层单列F假设来源及未核原生范围。

## 顺序与文件

1. **保留未知扩展的拒绝信息，不静默投影掉。** 在`Trade/NativeCapacityEvidence.py`复用原SDK/21个GET/精确正文/身份/时窗/reader主体，增加显式`collect_binance_standard_capacity_evidence`、`verify_binance_standard_capacity_evidence`。新schema `chan-binance-capacity-evidence-v2` 在每个原始object/单行array及每个bracket tier进入`_raw`前检查字段全集：feeBurn、commission（RPI费率仅作为原始可选字段）、symbol config和bracket原契约范围。任何未知键均在本次采集拒绝，绝不打印未知值/字段名；成功观测带经检查得出的`uninterpreted_paths=[]`与固定closed-field policy。空marker不代表不存在所有额外费用，只表示这些实际响应未包含未解释字段；公共reader重做闭合形状检查。v1允许白名单投影及隐私脱敏行为保持。先小型原SDK+底层fake证明新API缺失RED，再做嵌套/known-extra-fee/unknown/旧源/重封/尾时钟拒绝。修改共享collector前保护原186项回归，不能复制第二份请求循环。
2. **原check到F/Cost。** 在原`NativeAccountLimits`的共享owned/L0/source读取体添加显式`observe_binance_account_order_capacity_v1`，与原V1 price入口同一签名，候选仍9项，Last/market/完整book/模式/SDK/账户必须相同。新报告schema为`chan-binance-account-order-capacity-client-v1`，status为`within_model_capacity`或`exceeds_model_capacity`，原source/economics/admission flags保持false；它是原金额acquire的必要输入计算，不是独立资金许可。原reconcile status及native USDT single-asset/cross约束必须通过，feeBurn=false、候选symbol实际maker/taker费率只从v2取；未知扩展、BNB/foreign/isolated/不支持模式/订单/coef拒绝。F manifest固定`binance-standard-usdt-commission-client-v1`、日期2026-10-25、币种basis=client_assumption；`native_fee_currency_verified=false`和`native_extra_charges_complete_verified=false`不得省略。以原`_sources_snapshot`中的余额/权益调用原Cost计算体，不读caller金额/预封Cost/PASS、不再扣旧book IM。沿原leverage/order-margin共享体核完整池原生限额；仅该F入口对私有共享limits计算体选择v2 reader，旧public API不默默放宽来源schema。
3. **实际来源/原金额CAS。** 原受控acquire必须自己调用原prepare、同一SDK的v2 capacity、原prepare Last helper及原components，再直接重算第2步金额。将候选、F/P、模型/源码/来源/窗口、实际Cost/原check及原L0绑定到新完整金额契约，未知账户单在途不释放。不能让调用者传入来源或将旧v3/Last JSON后贴成执行能力。全部source自采及原CAS失败必须沿原sticky unavailable/回滚语义，不触碰替换库。
4. **所有消费者同时闭合。** 对`NativePreparedClient`、current components/admission、`NativeOrderTransition`、`CCXTTradeEngine`、pending/execution/account、claim/HTTP/default/恢复按实际依赖接新契约的条件金额验证。任何缺假设/来源/窗口/原行/账本/自有唯一增量不得靠schema白名单放行；旧v2/v3保持诊断不可执行。新可执行schema只能在全部消费者与端到端fake矩阵通过后启用，无实际candidate/testnet/live/config改动。

## 验收和交付

每个行为真实RED→最小GREEN；旧版足够覆盖不重造。新金额入口的参考从raw输入独立复算全Cost/原available，不把生产结果当oracle；验证六种订单路径、非空one_way/hedged多币、真实LIMIT/MARKET None/post-only、原已预占不二扣、单币/全池cap、恰界/微小不足、模式/费用/未知输入、时窗/原owner/晚真实CAS、L1/L2唯一增量及最终HTTP参数。

双CPython3.14.2/3.11.15、固定CCXT4.5.89，GUID basetemp/JUnit，禁止活pytest期间编辑；同用例集合/源码SHA、compileall/diff/相关链接、主线程review、Lore与普通push。按未变实现/依赖/环境复用适用证据，不把未跑冷启动/全仓称为重跑；每次报告子项与完整资金链/C5–C7的差异。F已批准不等于外部认证/资金锁额/实盘许可，不以小报告关闭原完整Goal。

## 本批结果（2026-10-25，仅第1–2步）

第1步复用同一SDK/GET循环和reader主体，v2在原响应投影前拒绝任何未解释字段，包含零值额外费用/未知费用币声明与bracket嵌套字段；成功marker来自实际检查。旧v1隐私投影、旧public API及纯Cost/Envelope的公式与canonical输出不变。共同collector和reader补齐末尾文档变异检查，直接核原对象exact types而不经JSON归一化；v2公共reader另把最后业务钟/canonical检查成本纳入typed monotonic年龄上界。v1历史as-of不续期，也不增加新的caller clock。

第2步新增原check只读金额计算，直接取原balance source的USDT availableBalance/marginBalance、实际费率/配置和完整book；不再扣旧预占，不接caller余额、币种、Cost或PASS。外层显式保留F的client_assumption与未原生核验费用币/额外收费范围，只有完整Cost与全池限额都满足才报告within_model_capacity。9字段候选仍需第3步证明来自同次实际prepare；本报告不授予来源拥有权或下单能力。

真实RED包含缺API、40项原响应未知扩展、4项collector尾端改写、12项reader尾钟/耗时漏洞，以及原金额入口缺失；金额矩阵首次14fail中12项为缺显式currency字段、2项为夹具错误：原生L实际为3，不能把非终止Fraction成本截成十进制以制造恰界。只将实际prepare的数量改为可精确抵消L的0.3，另保留非终止成本的独立Fraction参考，未修改公式/精度/容差。失败原件完整保留。

新增166来源＋38原账户金额测试。最终双版各1769 passed/0failure/error/skip/warnings，唯一用例集合差异0；包含完整85项原capacity prepare/CAS/current/cold及79项原prepare Last，这次没有排除9个冷启动用例。全部源码/测试摘要跨最终两版不变，双版compileall/diff通过。具体JUnit、RED和SHA见[台账](../reports/2026-10-20-crypto-full-version-progress.md)与[审计§39](../reports/2026-10-22-native-fresh-admission-audit.md)。主线程review通过此有限子层，完整资金/生产就绪仍否。

第3–4步未完成。下一实际acquire必须自行采v2 capacity、原prepare Last和原components，精确绑定原prepare的候选/金额及原L0；明确将NativeOrderCost、NativeLastPrice及实际执行依赖纳入新实现身份闭包，不能沿旧_FILES漏掉新依赖。原组件投影也不能被用来掩盖已观察的费用/模式反证；发现未知渠道须按F拒绝。reader/校验和只能核结构与本地一致性，不能认证完全自造或补marker重封的JSON曾经发生I/O。所有L1/L2/claim/恢复/HTTP/default消费者通过前，不启用新可执行契约。旧v2/v3继续诊断不可执行，实际配置与交易门禁不变。

F不再是待批业务阻点。用户已明确答复恢复原Goal自动串行执行，工具已实查active；没有创建替代Goal或缩小目标，不因本批通过宣称整体已完成。实际配置、资金使用和交易门禁不变。

提交前复核补项：JSON round-trip会把tuple/list子类和int/str子类归一化，掩盖原reader的exact type拒绝。原SDK/fake合法来源仅改Python类型且canonical字节相等，v1/v2原观察列表、档位、request/clock/raw标量及v2 marker共32项观察DID NOT RAISE。最小修复删除类型归一化：原验证主体直接检查传入对象，保留起始canonical字节及终末不变检查，不引入deepcopy的caller hook、递归类型框架或第二份领域验证体。32 RED后同三模块390 GREEN，再冻结源码做双版1769最终回归。修复前双版1737只是中间身份，不能作为提交代码的最终证据；全部JUnit保留、不改标签。

## 后续第3步结果；第4步继续未完成

按[同次金额原CAS计划](2026-10-25-owned-monetary-cas.md)，原受控入口已自行拥有prepare/同SDK capacity v2/components/Last，从原cash/完整book计算原Cost/限额，直接进入原intent CAS，绑定同一最终v4/完整monetary与client-order-v1金额摘要。原intent/历史/current/cold子层已验证，不是另建可丢弃诊断；原claim/全reader/HTTP/default仍拒绝。旧源/旧v2/v3不升级，不重封旧证明；源/额度/算法未原生证明范围保持false。

原reader/book/Cost主体复用，无新公式/账本/依赖；RED修正初次Cost计时、current snapshot/instrument末尾预算、完整实现闭包及cold owner遗漏，未扩大预算。新增78项与扩展原状态机回归，双版各3886唯一用例、0failure/error/skip，集合差异0，各3条既有小样本AUC警告；CCXT4.5.89，源码/测试跨最终运行一致，双版compileall/diff通过。完整范围、环境差异与原件见[台账](../reports/2026-10-20-crypto-full-version-progress.md)及[审计§40](../reports/2026-10-22-native-fresh-admission-audit.md)。

第4步必须继续同一binding，把完整金额及原L1/L2接所有claim/HTTP前/pending/execution/account/恢复/default消费者后再评估软件阻断，不能只扩schema；created/submitting/unknown不自动释放，历史管理不借旧点作fresh admission。C5–C7、OKX金额及完整Goal未完成，原Goal active；不因此再问A/P/F或缩小目标，不改实际配置/交易/研究门禁。
