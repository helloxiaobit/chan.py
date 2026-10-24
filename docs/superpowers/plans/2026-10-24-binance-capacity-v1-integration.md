# Binance 客户端 V1 完整金额模型接入原 CAS

日期：2026-10-24。起点：已推送、干净的 `11867fcbf3deb897352aa902bcbaf44d96f3990b`。

本计划执行已批准的[资金方向](../specs/2026-10-24-native-per-order-capacity-design.md)、[路线 P 算术](../specs/2026-10-24-binance-capacity-arithmetic.md)及原账户级串行协议，不重问 A/P。使用 executing-plans、TDD、verification-before-completion，主线程严格串行。计划是现有授权内的实施拆分，不新增审批或替代完整 C0–C7 Goal。

## 结果与边界

目标是将真实受控 prepare 的 Last/mark/BBO、当前账户/费用/配置/档位与实际单量连到具名 V1 成本，再由原 L0/L1/L2、完整账本与所有当前消费者逐单复核。不是再用一个 diagnostic PASS 代替完整资金交付。

alpha 固定 `3/2000`，不能调用者覆盖、搜索或当作原生成交上界。所有 LIMIT 的 Loss 均沿原通用限价公式使用实际 limit，包括 post-only；post-only 只选择 maker 费用估计，**不引入 Loss=0 豁免**。[官方开仓成本 FAQ](https://www.binance.com/en/support/faq/detail/87fa7ee33b574f7084d42bd2ce2e463b)更新 2026-07-08，未单列 post-only 损失豁免。金额与中间乘除全部 Fraction，原输入数字继续用 ExecutionFacts 的严格边界，不猜精度/epsilon、释放额或费用币。

全程合成/fake，不触发实际市场/账户/订单端点，不改实际配置、预算、候选、研究/绩效产物或旧来源。软件提交/普通推送已获授权；C7、测试网/实盘、资金使用和策略经济采用仍独立门禁。旧绑定、订单、来源不重封续期。

## 依赖顺序与文件

1. **完整单笔成本算术。** 新增 `Trade/NativeOrderCost.py`、`tests/test_native_order_cost.py`：严格实际候选形状/币数张数、模式/方向、LIMIT/MARKET/post-only、实际 L/Mark/Last/BBO、签名费率、明确 USDT 与 feeBurn=false；给出 R、Loss、IM、Fee、Cost 与 native available 的精确比较。每一项必须显式输入，不接受预算好的 Cost 或调用者 alpha。没有证明输入来源/费用适用性的纯函数保持 authority/economics flags=false；这不是本步已核费用币或资金许可。独立手算/参考覆盖六种订单路径、非终止分数、负费率不抵扣、恰界及最小超界，不二扣旧预占。
2. **受控 fresh Last。** 新增单一小型 Last 来源，复用原 SDK/环境/精确正文/数字工具；显式单 symbol `GET /fapi/v2/ticker/price`，核 `fapiPublicV2` 原路由，不调用旧 `fetch_ticker`/cache。保留 transaction-time 与本地 request 两种时钟；显式年龄/跨度/联合 skew，含末尾核验成本。底层 fake transport 测实际 SDK 请求，不以自封 JSON 得采集所有权。
3. **原 check 到完整成本/全书限额。** 沿 `NativeAccountLimits`、`NativeLeverageLimits`、`NativeMarginEnvelope` 复用原 SQLite/原 L0/原来源读取，不另造账户或第二套 pending/ledger。若为候选 R 复用包络计算体，先写清理计划并保护原 79/169/109 项适用回归；计算出的 Fraction 不转 float/截短小数，也不扩大原公开输入边界。feeBurn=false 不是单独的币种证明；需核标准 USDT、single-asset/cross、费用适用范围及原生资产/账户事实，BNFCR/外币/借贷/isolated/未知税费继续拒绝。原 available 已含旧预占，不再扣全书 IM。不得消费调用者已算好的账本/限额/金额。
4. **实际 prepare/CAS 全链。** 沿 `NativePreparedIntent` 原 owned prepare 获取并绑定上述源/模型；新可执行契约只能在 `NativePreparedClient`、原 current components/admission、`NativeOrderTransition`、`CCXTTradeEngine`、pending/execution/account/恢复/HTTP/default 全消费者明确实现之后启用。原账户级单在途/unknown、client SDK/数据/配置/原连接、每单参数、来源联合窗口和 L0/L1/L2 不放宽。不能只把新 schema 加入白名单或让汇总资金 PASS 绕过 claim。

## 验收与交付

- 各行为先实际 RED，再最小 GREEN；缺函数应为测试体的预期断言失败，不把 setup/import 环境错误算作 RED。每个新边界含晚变异、typed/nonfinite、单位、同源关联、原输入不变和失败无发单/无许可用例。
- 完整金额独立参考必须从输入重算，不读取生产 Cost 当 oracle；后续 E2E 必须从实际 prepare 一直到原 CAS/最终消费者，不能用传入 bool/预封结果代替。
- 双 CPython 3.14.2/3.11.15，串行、独立 GUID basetemp/JUnit；不在活 pytest 时编辑。源/测试 SHA 和唯一用例集合绑定结果；未改动的 11867fc 双版 2059 项证据仅按原范围复用，有实质影响才重跑。
- 主线程 review、双版 compileall、diff、相关本地链接和门禁检查后，更新开发台账；Lore commit，普通 push，核 HEAD/origin/remote 一致。阶段结果与剩余全链/C5–C7 分开报告；不因算术或 fake 通过关闭 Goal。

## 已核来源与尚未核项

- [Last V2 官方接口](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Price-Ticker-v2)：`time` 为交易时间，不能用请求结束时间冒充 fresh Last；使用 V2 专用原路由。
- [官方费用说明](https://www.binance.com/en/support/faq/detail/98488a516eb84e3eb34605683dffd554)与[费用计算](https://www.binance.com/en/support/faq/detail/360033544231)：原生当前费率仍须关联实际账户/标的，负返佣不给信用。FAQ 不是原生锁额/成交承诺。
- [官方费用币说明](https://www.binance.com/en/academy/articles/how-to-calculate-transaction-fees-on-binance)与[BNFCR 模式](https://www.binance.com/en/support/faq/detail/0e857c392a2d47cebde0af762d9255ae)：一般 margin-asset 规则不能覆盖 credit-mode/所有费用或司法辖区。第 1 步的显式币种只是数学输入；第 3–4 步未核适用事实前不开放新风险。

实施状态：第1步条件算术与第2步独立来源已完成本地 fake/TDD 验证，527新增；双解释器同七模块各1141 passed、0failure/error/skip/0warnings。第3–4步尚未完成，Last 尚未绑定原 prepare，显式费用币仍只是数学输入，不是原生费用适用性证明。原包络如何接收内部精确 Fraction 仍须按第3步先保护回归，不能通过截短 R 接上。具体失败/产物/代码身份见[台账](../reports/2026-10-20-crypto-full-version-progress.md)及[审计§36](../reports/2026-10-22-native-fresh-admission-audit.md)。完整 Goal active，C5–C7 未完成。
