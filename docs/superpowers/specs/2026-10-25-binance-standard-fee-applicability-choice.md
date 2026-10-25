# Binance标准费用适用性：路线F已批准

日期：2026-10-25。起草基线为 `e623ea73225d52dfa1d57563cba9122eeaf4e239`；批准后的实施从pushed/clean `4476e07952e6f6feea3ec964f783b56bae3e9146` 继续。用户明确答复“批准路线F：接受明确的标准佣金适用假设”。A（本地模型＋适用原生额度）、P（具名价格及费用估价）及账户级串行协议既有批准保留，不重问。此批准允许按下列条件模型开发，不修改规则/实际配置/交易门禁，也不等于完整资金链或外部认证已通过。

## 已核事实及缺口

- [官方User Commission Rate](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate)按账户及symbol提供maker/taker与可选RPI费率；[feeBurn](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-BNB-Burn-Status)给折扣开关，并未报告本单commissionAsset或“额外税费完整=0”。不能将文档未列某字段当成其数值为0。
- [官方费用币说明](https://www.binance.com/en/academy/articles/how-to-calculate-transaction-fees-on-binance)与[费用FAQ](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554)描述通常的保证金币扣费及BNB路径；[BNFCR资料](https://www.binance.com/en/support/faq/detail/0e857c392a2d47cebde0af762d9255ae)说明credits固定multi-assets。它们支持标准产品规则与排除条件，不是特定账户/本单全部费用的原生证明。
- 原check已核USDT single-asset/cross、原生available/equity和账本；capacity源仍明确fee_currency=None。只有数学函数的调用者提供USDT条件，不能据此接通新风险。

## 路线F：显式的标准佣金适用假设（已批准）

在已批准V1价格/费用估价外，另冻结 `binance-standard-usdt-commission-client-v1`：仅普通USDT线性永续、single-asset/cross、原生feeBurn=false、账户与symbol身份/模式一致、当时原生maker/taker费率、普通LIMIT/MARKET/GTX（非RPI），使用USDT标准佣金路径作为**客户端条件假设**。它不是native commissionAsset或“本单额外费用不存在”的证明。

关键放宽须明确：仅仅缺少原生本单费用币/完整额外税费声明时，不再自动阻断这一具名客户端条件模型；模型只覆盖标准佣金，不为未建模额外收费留默认0这一事实值。所有输出/未来契约必须保留此适用假设、来源/版本和未原生证明的范围，不能标为原生费用完整已核。已观察到非标准/额外税费、未知费用渠道/条款或模式/费率冲突，仍拒绝，不能用该假设覆盖已有反证。

BNB开启、外币/credits/借贷/isolated、未支持订单/费率、缺输入、非中性coef不明、余额不足、账本/unknown/窗口/原CAS不通过仍拒绝。源采集需保留适用检查所需信息及未知扩展标记，不能在白名单投影时丢掉已观察到的额外费用，再声称不存在；旧v1源不得重封为已证明费用适用。

本次批准允许据该**条件假设**把原available/equity及当前来源接入完整单笔Cost，并继续原prepare/L0/L1/L2/所有执行消费者的fake验收。本地模型通过仍不等于原生锁额、真实成交/费用上界、服务端必接单、C7认证或真实运行许可。实际配置/candidate/testnet/live门禁一律不改。

## 路线G：保留必须证明费用币及额外收费完整性的边界（未选，保留背景）

不增加上述适用假设；缺原生或等价明确适用证据继续拒绝新风险。本地算术、原账户/完整book及其他不依赖资金通过的授权开发继续。不能因为当前没有查到接口就断言平台永不提供；后续可补具体账户/产品的正式契约，但本轮未取得。

## 审批及验收

F已经由用户明确批准，不再把此选择作为当前阻点，也不重问A/P/F。实施前冻结完整source/模型/条件wire，严格TDD验证：所有事实来自受控原源，不能接caller PASS；未知扩展、非标准模式、旧源/重封、时窗/owner/CAS晚变异拒绝；原available不二扣旧预占；独立复算与双版适用回归。未通过完整金额/所有消费者前，不启用新可执行schema或默认发送。原Goal的自动续行状态由产品单独管理，不能用一个新Goal替换原完整目标。

当前实施见[接入计划及第1–2步结果](../plans/2026-10-25-approved-standard-commission-integration.md)：closed-field v2来源和原check条件金额已做fake验收，补齐原类型拒绝回归后双版各1769项通过。原Goal已由用户明确恢复，工具实查active。实际来源拥有权、同次原金额CAS与所有执行消费者仍待，不把本报告标为原生费用完整或真实资金许可。

同日后续：按[原同次金额CAS计划](../plans/2026-10-25-owned-monetary-cas.md)已把实际prepare/同SDK v2/components/Last、原cash/完整book与V1 Cost直接接入原intent/L1；同一最终v4保存完整monetary，历史/current/cold重算完整body和实现闭包。新增78项及适用扩展回归双版各3886唯一用例通过，各3条既有AUC警告，完整范围/身份见[审计§40](../reports/2026-10-22-native-fresh-admission-audit.md)。这是第3步子层，不是全部资金链或交易许可；第4步claim/L2/全reader/HTTP/default继续拒绝。F的client_assumption及未原生证明范围不变，旧证明不升级/重封，原Goal active，C5–C7/完整Goal未完成。
