# 原生冷恢复的查单专用初始化（已批准）

2026-10-28用户在本线程明确批准“限定查单方案”；此批准只适用于下述角色，不包含实际端点/配置/交易授权，也无须再次恢复已active的Goal。

2026-10-30限定实现与列明双版本离线验收已完成，见[原件/源码报告](../reports/2026-10-30-native-query-only-verification.md)。以下批准边界不变；前置失败是历史实证，不由新GREEN删除或重标。其他冷管理变更角色及C5–C7仍未完成。

继续[主计划](../plans/2026-10-20-crypto-full-version-completion.md)C6与[进程验证计划](../plans/2026-10-28-native-configured-process.md)。A/B同调用守卫、账户串行协议和金额A/P/F已批准，不重问；本文不改变这些设计，也没有授予真实交易/端点/配置权限。

## 实证与缺口

当前基线`552f09e83bd4ba21a0209452e1dedaf844fd7d2b`。独立fake开仓子进程已产生一次实际原SDK POST、持久化原v4/L2/SDK事实；第二独立开仓子进程不重下且原历史不变。继而在同一临时配置去掉新风险profile/candidate路径、测试环境撤去unlock并启用kill，第三进程运行原`RunTradeStage→RestoreOrders`，得到exit1、`original account/order evidence unavailable`，HTTP轨迹仅boot、没有GET。

原JUnit `C:\Users\yangj\AppData\Local\Temp\chanpy-native-process-recovery-py314-e086bb3b843e4902ac717e59dea8d549.xml`，1 failed，CLI69.06s，自然exit1；SHA256 `626b82e77c90f1bdf9db6db3307c8dd63dcab0cb99962c82a06916b6b9515ec8`。失败不是未知GET处理、SDK冷缓存或金额链失败：`configured_trade_engine`创建原Engine，构造体调用`build_trading_safety_policy`，它在实际query前强制candidate/模式unlock/kill检查。旧暖Engine先创建再撤许可的用例不能证明此冷启动边界。

## 提议：限定查单初始化，不放宽新风险

1. 原Engine/原SafetyPolicy增加显式、默认关闭的**查单专用**初始化语义，仅供原`RestoreOrders`调用。不是用户配置开关、通用ready标志、来源收据或可发送资格。
2. 查单模式保留显式venue/market/mode、生产/测试环境路由与凭据结构校验；原SDK和原持久化order/client/account/contract/L2/implementation全部仍验证。缺证据/未知GET仍失败，不能猜测成交、改账户、重签或释放未知意图。
3. 仅新风险candidate/profile/unlock/kill不阻止**读取已持久化订单**。查单结果仍经原状态机/SQLite写实际ack/累计回报，故“查单专用”不是SQLite零写入；不新增账本、表或资金推断。
4. 查单专用Engine必须拒绝其原公开提交、创建意图、撤单、改单/重试及降风险发单路径，且在任何相关网络写或新意图之前拒绝。它不成为取消/平仓的额外许可；此处也不解决现有其他管理CLI的冷初始化。不能通过构造后恢复unlock、改配置或重用该Engine切换为可下单对象。
5. 普通Engine构造、MakeOpenTrade、逐单来源/金额/claim/L2/SDK A/B与全部现有权限检查保持原逻辑；无实际配置修改、真实账户请求或自动解锁。开发只用fake，资金假设不扩展。

角色约束作用于原Engine操作入口，复用原SDK，不是任意Python代码或直接持有SDK对象后的权限沙箱；没有额外SDK transport hook。明确调用原SDK绕过Engine仍不在授权范围，也不能作为查单角色的合法用法。

## 备选与代价

- 维持现状：最少改动，但kill/撤去candidate后独立冷恢复也不可用，C6相关要求继续未完成。
- 推荐上述限定查单路径：可在新风险关闭时核原已存在订单，但增加明确的执行角色；必须测试角色不可升级及全部变更入口拒绝。不是笼统让所有Engine跳过初始化权限。
- 不采用“延迟所有全局权限到发送时”或“管理时临时补candidate/unlock”：前者改变普通构造语义，后者伪造/扩大许可。

## 批准后实施与验收

先保留/扩当前失败为严格RED，原source/SDK/SQL writer不得mock PASS；最小修改原Engine/SafetyPolicy/TradeRuntime/RestoreOrders。双解释器覆盖：cold query在kill/缺candidate/缺profile/撤unlock及过期输入时代下仍核原两标的混合历史；未知GET保留原L2和SDK已知事实、退出非零、零新POST，健康GET幂等恢复；原全部变更入口在其副作用之前拒绝；普通构造/入口原负向矩阵不变。再做适用native/default/current、safety、配置/paper/cycle/notification组合，compileall/diff、主线程review、Lore/普通push与远端身份验证。

批准前的提案阶段未实施上述生产改动；随后按[实施计划](../plans/2026-10-28-native-cold-query-only.md)严格RED→GREEN并取得上述最终双版证据。此前仅许可完整时的fake进程GREEN不曾证明此缺口；新验收也不等于C6全部完成。
