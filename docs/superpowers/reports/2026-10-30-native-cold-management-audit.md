# 新风险关闭后的原有订单管理：当前行为审计

日期：2026-10-30。基线full-version `2d12571464bc39c4de15d1be8bd52b97d291ec90`；[主计划](../plans/2026-10-20-crypto-full-version-completion.md)C5/C6要求新风险阻断时仍可管理已有订单/仓位。[已发布查单角色](2026-10-30-native-query-only-verification.md)只允许查原单，不含撤单、重试或降风险发单；本审计不扩大该批准。

## 当前源码与实际结果

| 边界 | 当前实现 | 已核事实 | 缺口 |
|---|---|---|---|
| 冷管理CLI | ClosePreErrorOpen、RealTimeTracker、RetradeCoverOrder均调用普通configured_trade_engine | 缺candidate/unlock或kill时原构造拒绝；即使空恢复集合也非零退出、零HTTP | 不能把父壳finally调了管理脚本当作管理成功 |
| 已创建普通Engine撤原单 | cancel_order读取唯一原持久意图、契约及账户，不调用新风险policy | Binance/OKX合成旧v3暖对象在kill后仍可调用原撤单，DB未据此应用终态/释放 | 暖对象不证明冷初始化可用；不是当前金额L2的新证明 |
| 已创建普通Engine降风险 | prepare_order与place_order仍多次调用无动作参数的assert_order_allowed | 已有原合成成交后，kill下reduce_only prepare在任何新意图/SDK写之前拒绝 | 仅跳过构造不足，不能改成通用policy无条件PASS |
| 已批准query-only Engine | 构造角色持有独立冻结policy，七变更入口先拒绝 | 前轮双版完整50项角色测试保留 | 正确边界，不应升级为管理执行对象 |
| 账户设置读取 | _observe_account读取position mode及leverage/margin设置 | 源码没有在该函数中核原生当前position quantity或全部在途减仓量 | 设置相等不是可关闭数量或没有其他关闭单的证明 |
| 旧契约owner | _monetary_consumer_owner对非金额旧契约返回原noop | 新减仓单通常为原v3路径，不自动取得金额open L2的owner/HTTP使用点检查 | 新角色必须显式覆盖原操作依赖，不能只靠reduce_only布尔值 |

RunTradeCycle已在finally串行调用原管理列表；本轮不改父壳或把失败返回0。RestoreOrders当前只核原已存在订单，不创建补偿订单。

## 精确诊断范围

外部诊断根（不进Git、不加入上一轮112模块清单）：`C:/chanpy/verification/native-management-cold-20261030/`。`test_current_management_diagnostic.py` SHA256 `7fe89fb85356b35537a3912afab4e8e38fa246d754ad6f0868162a301f8b2bb3`。

- 冷CLI三模块×三条件共9项：缺许可、其他许可齐但kill、许可齐且kill关闭的空集合对照；仅最后一组返回0，全部零HTTP。
- 暖降风险2项：Binance/OKX各一，原合成旧v3历史有已成交仓位后启kill，prepare拒绝且原记录/历史/SDK提交数/SQL变化不变。
- 暖撤单2项：Binance/OKX各一，原合成部分成交订单在kill下仍可原撤单；DB不据取消响应猜终态，不生成另一提交。

后四项复用明确标注legacy的原单位/参数fixture，只定位原policy与操作路径，不冒充新金额链、真实服务、完整仓位能力或新管理角色验收。前9项使用真实原CLI/工厂/SQLite、显式临时配置及纯路径CEnv，Requests底层阻断；没有读取用户实际YAML、私有退出参数或真实密钥。

| 解释器 | 终态 | 原JUnit | SHA256 | CLI/XML秒 |
|---|---|---|---|---|
| CPython3.14.2 | 13 passed，零failure/error/skip/warning，exit0 | py314-c5fbd5ea106047fd93dfbf73153502cc.xml | 1412d7704d90f9f7be2e547d48a428b700f03788182005fa14a163f6fa3efa6c | 1.93 / 1.874 |
| CPython3.11.15 | 同13 passed，exit0 | py311-90d6bf527bad43f29ca5bc369a81b280.xml | 08f89e61ab777ca253a0be28dc236fa00c07382361b60fae66f66bf597dd06f4 | 2.11 / 2.072 |

独立重读两份原XML：相同13个唯一classname/name/state，canonical sorted/ASCII JSON SHA256 `ae7fa3e289d9370811d08e9c9ebeb1eefaade92db5bf404ce8515ba7ebadae25`。没有改变生产代码、仓内测试、依赖、实际配置或门禁；179文件raw source-map仍为前轮 `1a44946c062ce07e602cd2704a684160a1e486329d555479eb14a37ac5f3c123`，原完整矩阵仅在不变范围继续适用。

这13项是**当前行为刻画**，不是尚未批准功能的RED/GREEN，也不加到前轮7405节点或改其manifest。批准后仍先写期望冷管理成功且所有越权路径拒绝的真实RED，再实施。

## 文档核对与推论边界

2026-10-30仅浏览官方文档，没有访问交易/行情/私有API。Binance原New/Cancel Order文档已重定向到[USDⓈ-M Trade](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)：常规下单的Hedge Mode不接受reduceOnly字段；撤单是带订单身份的独立变更请求。因此不能把内部reduce_only=True或“查单权限”当成原生减仓/撤单授权。

[OKX Place order](https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-place-order)分别规定side/posSide的关闭组合及net/long-short模式的reduce-only适用方式。它支持按模式验证关闭语义，不支持从“方向相反”推断所有市场都只减仓。文档说明不等于真实账户或并发服务器行为认证。

独立核验后的工程推论：新增角色需要原订单归属、原持仓/在途数量、原CAS及实际SDK使用点共同约束；现有全局policy或旧L2都不单独证明新关闭单的权限。建议见[待批设计](../specs/2026-10-30-native-existing-risk-management-design.md)。

## 状态

本轮仅审计、诊断与设计文档；没有实现新增角色，也不宣称C5/C6完成。提案获批前不能把管理CLI接成可绕过candidate/unlock/kill的执行对象，或把query-only升级。A/B、账户协议与A/P/F不重问；实际运行、候选换代、OKX新风险金额及C7仍独立受门禁约束。
