# S3 原生逐单准入：已批准的账户预留与原 CAS 协议

日期：2026-10-23（Asia/Shanghai）。状态：**账户级串行协议已获用户明确批准；尚未完成实现/验收，不是已批准的资金公式或运行权限**。

批准记录：用户对本文件的专门确认问题答复“批准上述账户级串行协议（推荐）”。同一稳定账户跨市场仅允许一个尚未被原生来源完整观察的新风险意图；原 CAS 内精确验证本单 intent/claim 的唯一增量，未知不释放；逐单资金能力仍独立 fail closed。不得据此修改实际配置、候选、交易门禁或执行真实 I/O。该详细方向不再待批，下文保留审查时的方案语境。

主目标仍为 [C0–C7 完整版](../plans/2026-10-20-crypto-full-version-completion.md)；已批准的来源/鲜活性方向及实施边界见 [原生准入计划](../plans/2026-10-22-native-fresh-admission.md)。本次代码基线为已推送、clean 的 `242d36ea5715093fbece5368f3e1f6e1ad78becf`。S2b6 的本地自采已完成，完整 S2/S3/S4、C5/C6/C7 均未完成。

## 1. 已批准的设计范围

此前批准解决了独立来源、显式鲜活性、零默认容差及原 CAS 每单复验的方向，但未固定**账户级同时在途的新风险意图如何占用可用资金**。原审计 §4.3 已要求该详细协议在集成前审查。

推荐确认以下并发协议：同一稳定原生账户、全部市场共享一个“尚未被原生来源完整观察的新风险意图”边界；原 intent/CAS 一次只能取得一个这样的在途位置。未知提交、未在 native pending/执行中证明的本地意图不自动释放，不按 TTL 过期或网络异常重新创建。已完整归属的原生未决单以及已有多币种持仓可以继续存在，不把目标改成空仓、单币或无挂单。

这会影响不同 symbol 同时提交的行为，故不能视为普通函数拆分细节。它不代表 native_available>0 就足以支付任意新订单，也不证明该订单一定被交易所接受。**逐单资金能力仍是独立硬门槛**：需要按确定的 order role/方向/数量/价格/费用与账户规则取得可复核的额度或明确冻结的金额模型；未补全该规格前，不产生 admission=true、不接默认新风险发送、不解除常量阻断。

上述“账户级原 CAS 串行化未观察意图＋资金能力独立硬门槛”的详细方向已获批准，按本文件逐项 TDD 实施；不重复征求同一批准，也不扩展为真实 I/O、配置、资金公式或候选权限。

## 2. 已核对的当前代码事实

| 原边界 | 当前实现 | S3 必须补足 |
|---|---|---|
| `CCXTTradeEngine._market_contract` | `load_markets()` 默认可返回 SDK cache，再读完整执行 metadata | 新风险使用实际原生 instrument 来源；不能把 cache 当作一次新观察 |
| `TradeEngine.add_trade` | prepare 后写原 intent，再调用 place_order | 冻结具体单、候选/输入、当前来源、runtime 与 DB 身份，原事务复核后才能取得新风险意图 |
| `CChanDB._order_write` | 原 SQLite 事务内核历史、更新投影、写原 journal；v3 intent/claim 检查 sticky freeze | 在相同事务中验证完整账户基线及本单唯一允许的增量，而非仅同 record_id 的竞争 |
| `acquire_open_intent` / `claim_order_submission` | WHERE 约束各自记录/原状态 | 不同信号行/不同市场之间需要账户级一致性；不能各自沿用同一份早期可用额 |
| `NativeCurrentComponents` | 所选 check 的全 ledger 必须与当前完全一致 | intent/claim 正常追加后旧 check 必然不同；必须识别本单的精确允许增量，不能直接忽略自身或全部新记录 |
| `NativePendingOwnership` / `AccountReconcile` / `ExecutionReconcile` | 原生契约分支明确只接受 v3 | 新版本须显式接入这些原 reader/共享核算体；只扩 Engine 或把新 schema 加到宽松集合不足以证明兼容 |
| 当前余额/预占 | native 账户汇总保证金、可用额与原挂单剩余数量可以复核 | `per_order_allocation=not_inferred` / `native_margin_amount=None` 不是可分配的新单额度 |

原 v1/v2/v3 契约、来源和 journal 不重封、不自动迁移。旧查询/恢复/撤单/降风险继续原已验证路径。新风险的版本升级不能把旧候选或旧运行时证明自动重新武装。

## 3. 官方接口与本机 SDK 证据

这里只阅读公开文档和本机 CCXT 4.5.89 源码，没有调用任何行情、账户或订单端点。

- [Binance Test Order](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade#test-order-trade) 声明 `/fapi/v1/order/test` 不进入撮合。当前文档给出测试订单响应字段，但没有据此给本地 CAS 提供账户资金锁/预占身份的契约。因此不能将其回执当作真实订单 ACK、资金锁或逐单资金充分证明。这是对文档证明范围的限制，不推断服务器未公开的全部校验行为。
- [OKX Order precheck](https://www.okx.com/docs-v5/en/#order-book-trading-trade-post-order-precheck) 文档限定 Multi-currency/Portfolio margin，且为 Trade 权限 POST。当前已支持/观察的是 `acctLv=2` Futures mode，不能为复用该接口而切换用户账户模式，或把它放进现有只读 GET 自采协议。全页读取被工具的页面大小上限拒绝；上述条件由官方页面的定向检索内容核对，未将未读部分冒称完成验证。
- [OKX Maximum order quantity](https://my.okx.com/docs-v5/#trading-account-rest-api-get-maximum-order-quantity) 的 `/api/v5/account/max-size` 是原生订单数量候选来源，导数单位为 contracts；该数量观察不是账户资金锁，也不能移用为 Binance 的金额模型。若后续采用，必须绑定单一标的/明确价格与账户/模式/观测窗口，而非采用省略价格后的原生默认价作本地指定价格的证明。
- 本机 `ccxt.Exchange.load_markets(reload=False, params={})` 在已有 markets 时直接返回 cache；`reload=True` 可能先执行 `fetch_currencies`。Binance 默认 `fetch_markets` 还可能读取 spot/linear/inverse，OKX 默认覆盖多种 instrument type。因此不采用“在所有旧调用上加 reload=True”这一未经范围约束的修复；它不能证明只读取本轮 USDT linear 所需的原生 metadata。

后续 native instrument 来源应限制为明确公共 endpoint（Binance fapi exchangeInfo / OKX public instruments SWAP）和明确目标池，复用环境/SDK/finite/单位边界，不修改实际 SDK/用户配置或借旧 cache 补缺。具体 schema/时钟/预算在其 TDD 前冻结；此草案不提前认定其已实现。

## 4. 已批准的原事务协议（分阶段实施）

### 4.1 prepare：本次自采与执行身份

1. 以原 CChanDB/原连接和完整声明池读取有效 before、全 ledger、原冻结，固定 typed account/mode、DB 位置和本次调用身份。
2. 锁外取得实际 instrument metadata，再直接调用本地原生自采。不能接受 caller 的 wrapper/check/PASS 作为“本次已采集”。独立 mark/book、pending/balance、全部实际持仓及执行/wallet 来源仍完整核验。
3. 冻结实际候选/部署/模型/输入、显式政策、配置的脱敏身份、依赖源码与加载 runtime，冻结 order role/方向/两单位数量/价格/post-only/执行设置。新文件不自动包含在旧 opening/model/deployment 指纹内；版本化记录，不回写旧产物以制造新证据。
4. 取得原始基线 `L0`（原 journal 显式边界、全部 history/projection 和 source IDs），并确定拟提交单的完整身份。逐单资金能力规格缺失时，此步仍不能产生有效新风险证明。

### 4.2 acquire intent：同一原 CAS 验证账户基线

1. 进入原 `CChanDB._order_write` 所属 SQLite 事务，重读 `L0`、sticky freeze、来源身份/时间、实际信号与候选/运行条件；必须与锁外自采的原基线一致。
2. 对全部 trade-shaped 表/同稳定账户核未被原生完整观察的本地新风险意图。未知/无可验证归属者不能按零金额排除；不得仅按当前 symbol/table 筛选。
3. 原 CAS 成功后，仍由原 `record_transition` 写意图。形成 `L1` 时只允许**这一具体单**的确定 intent/journal/projection 增量。原子核对/持久引用与意图一起提交，不另建撮合/订单引擎或可重置资金表。
4. 两个进程以同一 `L0` 争抢不同信号时，只能一个取得这个未观察意图；另一个拒绝，不自动重采/刷新为重试。不同稳定账户的排除必须由可验证 typed identity 支持，不能按 caller account_scope 名称排除。

### 4.3 claim 与 HTTP 前：不把自身增量当全部差异豁免

1. 原 claim 事务内校验 `L1` 和所有硬门槛；仅允许该单的原 claim 追加形成 `L2`。不能只把自身从 ledger 删掉后比较余项，也不能重封任意新 ledger 作为 expected。
2. HTTP 前在锁外复查当前 route/account/metadata/runtime/候选/kill 等，最后重读同一原 DB、`L2`、全部引用来源和预算。任何其他连接写入/来源或政策漂移均拒绝；网络不进入 writer lock。
3. claim 后失败继续原 submitting/unknown 边界，只允许按原 ID 查询/恢复，不退回 created、删除意图、补假 ACK 或自动重发。来源异常仍沿原失败发布；无可写原库/身份不确定时拒绝且不声称已冻结。
4. server 响应、真实订单归属、原 ACK/累计成交/恢复始终使用原状态机。完整新来源能力未纳入默认壳与全部直接新风险入口前，原常量阻断不移除。

### 4.4 预留何时变为已观察

- 本地 created/submitting/unknown 不能因一次 pending 空列表或时间推移释放。
- 原生 pending 必须与原单 ID/账户/市场/方向/条款/两单位累计量完整对应，或者有原 native execution/终态和原状态机的完整证据；不凭原生测试单回执放行。
- 已完整观察的旧未决单由原 native available/aggregate margin 反映，不能再按猜测分摊金额或重复扣 ordFrozen/IMR。下一新风险单仍须重新自采，不能复用其更早的账户点。
- 账户级串行协议不是全账户服务器锁，也不能阻止用户/外部机器人或交易所状态在观察后变化；实际来源覆盖、单级资金能力、外部容量/持续运行和 C7 仍独立验收。

## 5. TDD 与兼容验收（分项实施，整体未通过）

当前实施记录：独立 instrument 来源/原缓存消费已在 bb3aa29/f678ece 离线验收；L0 前置基线及原事务断言已完成153项专项。新增 NativeOrderTransition 已将显式本单 L1/L2 引用接入原 intent/claim 事务，381项新测试与两版54模块各3688 passed/1既有skip/13小样本模型警告；只有不可执行的 `chan-native-cas-order-v1` 诊断意图可使用新引用，旧 v1/v2/v3 字节不重封。该子层不是完整4.1 prepare/4.3 HTTP 消费或资金协议验收；完整实际候选/加载runtime/来源调用绑定、新可执行契约及全部reader、额度规则和默认入口仍未完成，不得把下列各项全部标为通过。细节见主验收台账和实施计划 S3c。

2026-10-24补充实施状态：NativePreparedIntent已把同次实际本地prepare、instrument与原component自采接到原intent CAS；v2引用在原事务内核完整原行/账本、唯一intent增量和最终来源窗口，未新增表/金额模型。仅原writer内部可在精确expected after-row核对后复用冻结signal，公开pre-intent断言仍不适用于L1之后。72项新增及原兼容24模块，两版各1841 passed、0failure/error/skip、9模型警告，集合一致。v2历史可在无client/GET时用对应SDK重读，但v2 claim在原SQL前明确拒绝；原v1诊断claim/旧v1-v3恢复仍沿原路径。完整4.3的L1/L2后本地重建、HTTP/新执行版本全reader/default、逐单资金及完整加载闭包尚未通过；多次来源读取不证明服务器原子性，以下完整联合验收仍不能标为完成。实施详见S3e及审计§27，不改变已批准协议或任一真实交易门禁。

2026-10-24再次补充：原L1的持久本地重建已形成有限子层，由原Engine在资金拒绝前实际消费；原after hash/全ledger和immutable event仍是精确基线，不接受caller JSON或自身排除。新binding-v2仅增加原SDK/cache/route/凭据的摘要，旧binding-v1不补造或重封，原来源/identity schema保留；所有claim/发送门禁不变。70新用例及双版26模块各2357 passed/0failure/error/skip/9模型警告，旧实际测试库副本历史字节相等且claim拒绝。只有已有匹配缓存、代码/配置/输入时代与来源窗口时才能本地复核；冷启动新SDK完整初始化、L2/HTTP/资金/全部reader和正式C7仍未通过，不能把下面完整验收全部标为完成。详见S3e和审计§28。

2026-10-24冷启动子层补充：新增显式initialize_native_prepared_client，仅在原Engine.exchange=None时沿实际factory创建新SDK，自取公共instrument并用原纯parser初始化该新缓存，再GET核原账户设置/身份。原L1复核仍须匹配完整旧SDK摘要/账本/旧时钟，新观察不能续期、重封或释放未知状态；已有client不刷新，本入口成功仅None。54新用例含两venue全新Python进程；双版8模块各368 passed/0failure/error/skip/2既有模型警告，全部fake transport，非真实服务认证。未自动接默认发送，资金/claim/HTTP、全部执行reader与完整加载闭包继续阻断或未验收；原协议及以下整体要求不变，详见审计§29。

冷启动收尾复查：最后业务时钟/本地视图之后再次核原SDK摘要，并以monotonic_ns尾段差向上换算毫秒形成保守使用时刻上界，包含尾段核验与原owned退出耗时；不改变native时间、显式budget、资金规则或原schema。近边界可能更早拒绝，不能解释为允许额外1ms。24新增回归，双版8模块各392 passed/0failure/error/skip/2既有模型警告，原claim/default仍拒绝；金融方向选择尚未确认，以下完整验收仍未通过。详见审计§30。

随后用户已明确批准[本地金额模型＋原生额度方向](2026-10-24-native-per-order-capacity-design.md)，不再待批。首个独立Binance参数来源已补feeBurn/当前commission/symbolConfig/完整raw brackets，186新、双版同六模块各903 passed/0failure/error/skip/0warnings；只输出flags=false的输入，不计算资金或接原CAS/默认发送。实际SDK默认testnet签名拒绝保持，未切demo或改配置。完整金额算术/独立非空账户复算、以下整体验收及C7继续未完成，详见审计§31；原Goal工具仍blocked，不冒称已恢复active。

续行后Goal工具已恢复active；新增独立book包络核算，非空双币/hedge四腿/partial/关闭方向挂单逐项保留，hypothetical候选无native ID/ACK或资金许可。79新，双版各721 passed/1既有skip，未应用新的价格/费用/档位政策，原资金/claim/default阻断不变。完整算术中的价格P/N为另一项明示选择，不重问既有A/原CAS协议；未确认不编码FAQ估价或改变严格界限，详见[算术规格](2026-10-24-binance-capacity-arithmetic.md)与审计§32。

随后新增provided-book对原生杠杆/名义cap的必要检查，169新、双版同三模块各434 passed/0failure/error/skip/0warnings；不是原协议的资金通过或账户来源绑定。其book_origin_verified/economics_complete/native_admission_verified均false，非中性coef/不完整档位继续拒绝；原L0/L1/L2、claim及HTTP/default阻断不变，P/N待答复只暂停估价依赖，不重复既有协议批准。完整受控prepare→资金→原CAS及下列整体验收仍未完成，见审计§33。

再接原check只读适配NativeAccountLimits，直接派生signed持仓/完整pending/独立mark/模式并前后assert同一原L0，109新、双版同五模块各696 passed/0failure/error/skip/0warnings。book_bound_to_original_check=true不是受控自采/资金/CAS许可，source_collection_owned及原资金/admission flags仍false；最后时钟后的真实原CAS变更会拒绝旧book，created意图保留不自动释放。原prepare所有权、完整金额、原L1/L2消费/HTTP/default与C7仍待，详见审计§34和[算术规格§6–7](2026-10-24-binance-capacity-arithmetic.md)。

2026-10-24接续：按[raw绑定规格](2026-10-24-native-capacity-prepare-binding.md)将实际prepare同一SDK的capacity自采接到原intent CAS，显式新入口写binding-v3，旧入口v2不新增GET。完整raw源/显式policy与原账户/配置/SDK/联合窗口绑定，历史as-of不续期current，末尾source回调后原client/本地/账本及monotonic预算复验，失败不落intent；仍没有完整金额或可执行contract。85新增、双版同15模块各2059 passed/0failure/error/skip/3既有AUC警告，详见审计§35/台账。用户已另批准算术§2路线P，仅允许具名客户端V1估价，不是原生执行上界/资金锁或交易授权。完整金额、原L1/L2资金消费、全reader/HTTP/default、OKX/S4/C7及整个Goal继续待，既有账户级唯一未知意图协议和全部门禁不变。

1. 单独证明已加载 SDK cache 不构成新 instrument 读取；fake 最底层原生方法返回新 tick/contract/status/limits 时应拒绝旧 metadata。拒绝错路由、额外私有/跨产品请求、缺/重复市场、非有限/未来/倒退时钟；不为恢复旧单强制获取新模型。
2. 用已有两币非空/partial/pending/fee/funding fixture 扩展完整 prepare→原 intent→claim→HTTP；用真实原 SQLite/CAS，而非 mock 一个 passed helper。
3. 同账户不同记录/市场/表的双连接竞争，以及 acquire/claim/HTTP 前各边界的输入、冻结、来源、runtime/配置变化，均不得产生两个未观察新风险意图或额外 HTTP。
4. 本单唯一合法 intent/claim 增量可验证，任意零成交遗失尝试、第三方记录/字段/事件变化仍拒绝；不能以忽略自身/全部新行来消除 RED。
5. claim 后断连/拒绝/未知返回不重创，pending 消失不释放；原 v1/v2/v3 恢复/撤单/reduce-only/累计成交和 append-only 历史回归保持。
6. 逐单资金能力须有单独的不足/恰界/费用/方向/档位/已有挂单/并发占用与来源缺失夹具。没有明确可证明输入或公式时维持拒绝，不把本并发协议的 PASS 替代它。
7. 新版本 reader/源码指纹/default 全入口 E2E、双解释器适用回归、源码/迁移/支持矩阵、Lore/精确提交/远端核对后，才按原批准范围评估是否移除壳常量阻断。没有正式 C7 证据仍不得宣称测试网/实盘认证或关闭主 Goal。

## 6. 明确不做

不修改实际配置/权限/规则/依赖；不创建真实会话或实际请求；不重封旧候选、模型、部署、证明或订单；不引入隐含年龄、epsilon、手续费/档位/汇率、名义额÷杠杆或全额抵押替代规则；不自动解冻；不把股票/Spot/Portfolio/借贷/未知账户模式并入初始支持范围。
