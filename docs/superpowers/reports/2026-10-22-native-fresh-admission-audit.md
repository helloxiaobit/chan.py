# 原生 fresh-admission：现状审计与已批实现方向

状态：**严格方向已获用户明确批准（2026-10-22）；实现/验收未完成，不是交易收据或生产授权。**

批准记录：用户对“独立原生 mark/book 与公共路由证据、显式年龄/观测跨度、金额零默认容差、原账户/账本及原 CAS 每单复验；仅 fake、保留全部门禁、不改实际配置”的确认问题答复“批准严格方案（推荐）”。
下文保留最初审计及建议的历史语境；不再将本方向视为待批。具体串行实施见 [原生准入实施计划](../plans/2026-10-22-native-fresh-admission.md)。候选换代设计仍单独待批；没有真实 I/O、配置/权限修改、自动解冻或实盘授权。

2026-10-23 补充批准：用户已对 [账户级原 CAS 详细协议](../specs/2026-10-23-native-per-order-admission-protocol.md) 的专门问题答复“批准上述账户级串行协议（推荐）”。该详细方向不再是待批阻塞；下文早期“尚待确认”的记录保留为当时事实，实施进度见 §22。逐单资金公式/候选换代/真实服务/配置权限并未据此批准。

审计基线：`ab02e5b50dae50f781887c95e60e47628d952b32`，`full-version`。
前一 Goal 回合是有效进展：双币软件矩阵已推送；本轮不再以增加类似的 paper 用例代替原生缺口。
本报告不改变 C0–C7 的完整目标，不把 unsupported/未认证能力算作完成。

## 1. 结论

目前不能删掉 `native_fresh_admission_not_integrated`，也不能把历史对账、ticker 或软件 paper 的 PASS 升格。
已有来源、账本、意图/CAS 和冻结机制应继续复用；缺的是独立原生市场证据、明确的鲜活性政策及每单消费协议。
本轮只读核对代码、官方技术文档和本机 SDK 定义，没有调用行情/账户端点、使用凭据或修改实际配置。

## 2. 当前代码已经证明什么、没有证明什么

| 当前实现 | 现有证据 | 不能据此推导的结论 |
|---|---|---|
| [RunTradeCycle](../../../Trade/Script/RunTradeCycle.py)，`run_trade_cycle` | 非 dry-run 在 open 前明确阻断，结果的 native 标志为 false；管理阶段仍在 finally 中执行 | 删除阻断分支即可安全开仓 |
| [AccountRiskStore](../../../Trade/AccountRiskStore.py)，`risk_state` / `assert_new_risk_allowed` | 重读原证据、原历史前缀；历史异常持久冻结且后续匹配不自动解冻 | 无历史冻结、或某次 matched_observations，就是当前完整账户准入 |
| [AccountSources](../../../Trade/AccountSources.py)，`_position` / `collect_account_snapshot` | 原生数量、单位、账户资产和观测起止窗口；position update 时间与 mark 时间明确区分，`mark_ms=None` | 刚读到账户就拥有独立、带来源时间的 mark |
| [AccountReconcile](../../../Trade/AccountReconcile.py)，`_build` | 给定完整观察区间内的来源/原历史逐项核对；披露 economics_complete=false、mark 时钟未知 | 当前点账户准入、原生舍入/isolated/funding 分腿全部闭合 |
| [MarketQuote](../../../Common/MarketQuote.py)，`_validate` / `read_quote_batch` | 有界的原 ticker price 与时间、完整标的集、使用时年龄检查；软件 schema 分离 | 独立 bid/ask、盘口量、mark、保证金或成交可得性 |
| [AccountIdentity](../../../Trade/AccountIdentity.py)，`_environment` | 当前 SDK 参考客户端、TLS、mode、private_routes/账户 typed identity 前后检查；OKX 的 rest 是共用基址 | Binance fapiPublic 已覆盖、或 OKX 共用基址等于独立 mark/book 响应证据；参考 SDK 路由即外部认证 |
| [CCXTTradeEngine](../../../Trade/CCXTTradeEngine.py)，`_observe_account` / `place_order` | 每单 mode/margin/leverage、原持久意图、kill/candidate、原生账户身份和冻结检查 | mode/leverage observation 就是完整余额/持仓/市场 fresh-admission；历史冻结检查代替新证明 |

原 v3 意图和 [OrderAudit](../../../Trade/OrderAudit.py) 的输入检查不能被原地改名为新准入。
新证据须有独立版本/身份和消费边界；旧单恢复/查询/撤销/降风险不要求重新取得旧策略模型或被重发。

## 3. 官方来源与 SDK 核对

以下是采集接口依据，不是已执行的交易所验收，也不是可用性/可成交性保证。

- Binance 独立 mark 可取 `/fapi/v1/premiumIndex` 的 `markPrice` 与 `time`；BBO 可取 `/fapi/v1/ticker/bookTicker` 的价格、量和交易时间。后者不含 RPI 深度，不能称全盘口。[Binance 官方 Market Data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data)
- OKX mark 使用 `/api/v5/public/mark-price`；应保留其 `ts` 的“数据返回时间”含义，不冒称 position mark 的生成时间。[OKX Get mark price](https://my.okx.com/docs-v5/en/#public-data-rest-api-get-mark-price)
- OKX `/api/v5/market/books` 的盘口时间、序列和衍生品张数有独立语义；这是服务端缓存快照，预开盘可能交叉。不能用 HTTP 接收时间刷新旧盘口，或把交叉盘口判作可新开仓。[OKX GET / Order book](https://my.okx.com/docs-v5/en/#order-book-trading-market-data-get-order-book)
- WS mark 与 REST mark 不是同一种时钟/唯一性契约。官方还披露 WS 同时间戳可收到不同 mark 值；未来若做 WS，不能只用时间戳当内容不可变的原生事件 ID。[OKX Mark price channel](https://my.okx.com/docs-v5/en/#public-data-websocket-mark-price-channel)

本机隔离环境 CCXT 4.5.89 的只读构造/属性检查确认下列方法存在；没有执行这些方法：

| 客户端 | 候选方法 | 需要单独验证的实际公共路由 |
|---|---|---|
| binance / binanceusdm | `fapiPublicGetPremiumIndex`、`fapiPublicGetTickerBookTicker` | `fapiPublic`；本机 live 与 sandbox 参考 URL 不同 |
| okx | `publicGetPublicMarkPrice`、`publicGetMarketBooks` | `rest` 模板、实际 hostname、sandbox/模拟 header |

SDK 构造成功及方法可调用不代表服务器支持。不得为兼容而自动改 URL、TLS、代理或已冻结账户上下文；C7 才验证实际路由/模式。

## 4. 已批准的设计方向

### 4.1 证据层，而非新“信任 passed”接口

建议先新增独立原生市场观察模块，复用 finite canonical/SHA、原生 `_market` / 数值校验和实际 CCXT 调用风格。
每份观察绑定 venue/mode、原市场 metadata、实际公共路由、SDK/代码身份、请求起止时间与 allowlisted 原响应。
mark 与 book 保留各自的字段、单位、时钟类型和来源，不伪造统一原生生成时刻；不从 last 补 mark，也不让软件 schema 进入原生证明。
每个新观察按完整内容与请求窗口取身份，不以 timestamp 单独唯一；无 secret、原账户 ID 或任意异常全文。

公共路由在请求前后复核：Binance 补独立 fapiPublic，OKX 复用已经保护的 rest 基址/hostname/header 并绑定实际来源端点，不把它说成原来完全没有保护。
私有账户仍用原 typed identity，二者由准入消费者关联，不修改旧 context 字节。
保留原账户证据表/旧报告语义，不把原 economics_complete=false 改为 true；仅新增独立版本的来源/使用检查。

### 4.2 鲜活性政策必须由部署显式提供

建议要求每来源年龄上限、账户/整个采集观测跨度及允许的跨来源时间差；名字/格式在批准后的详细规格冻结。
不提供隐含秒数，不把原 ticker 或 software quote 的上限擅自用作账户/mark/book 上限。
缺政策、坏类型、未来时间、时钟倒退、来源缺失、重复标的、错误 market/单位、非有限或不可交易盘口均拒绝新增风险。
有效的原生交叉/空盘口可作为“观察到但不可准入”的事实保留，不能为了生成 PASS 自动修正。

金额/数量/来源/账本仍要求严格一致，无默认 epsilon、汇率或舍入纠正。无法证明的差异为 mismatch/incomplete，不据一次后续匹配自动解冻。
这些只是对所提供观察的检查，不宣称交易所全局原子快照、所有经济事件或平台风控公式已获证明。

### 4.3 原账户、原账本及每单边界

建议在同一账户命名空间关联原 snapshots/wallet/execution/全 trade-shaped 历史与独立市场证据。
全部支持市场及实际持仓均须有对应来源；不能只核候选 symbol，也不能靠只允许空仓、单币或忽略已有仓位绕过完整状态。
新源若只能提供有限观察，不得把旧 interval 的匹配状态当当前值；HTTP 观测窗口、数据 mutation 时间和来源返回时间分别处理。

复用 prepare → 原 intent/CAS → claim → HTTP 前的检查点，而不是只在运行壳检查一次。
证明应绑定实际账户/模式、DB、原候选/部署/配置/代码、order role/数量/价格和引用来源；持久意图必须记录原证明。
DB 锁内核对原历史/投影/预留身份及年龄，网络采集不置于 SQLite 写锁内；并发新意图、账户可用余额和原生未决单/预留归属需有明确一致性规则。
不能把缺少预留证明解释成“可用”，也不能清空未知状态后重下；该规则的详细协议必须在集成前审查。
HTTP 前再次核原来源/身份/kill/candidate/冻结和实际意图；失效仍保留未知/已提交边界，不回滚为可重新创建。

原 v1/v2/v3 记录只按已验证恢复路径管理，不能重封迁移。新风险证明使用新版本，不给 caller 一个布尔 ready、任意来源 ID 或自封 SHA 的放行接口。
股票、Spot、Portfolio/multi-asset、借贷/缺 channel/isolated、未知币种或无法闭合来源的组合不随初期 USDT linear cross 支持被暗中放行；未覆盖的完整目标仍记未完成。

## 5. 已批准的实施顺序与验收方向（不代表已实现）

1. 独立 mark/book 来源：原生 raw 夹具先 RED，finite/canonical/raw 重算/公共路由变异/时钟和单位 GREEN；此时 admission 仍为 false。
2. 当前使用检查：显式政策、完整市场集、账户/市场/原账本关联；不足来源一律不生成有效准入，不另写第二套财务公式。
3. 原意图/CAS 消费：跨连接修改历史、预留、配置/路由/账户、年龄失效与 claim 后漂移均拒绝新发送；原恢复/撤销/降风险回归。
4. 真实运行壳与 CLI：合成 native 运输做两 venue/模式/多市场端到端，证明没有绕过新消费者的入口；旧常量阻断只能在这条完整路径证据成立后有条件替换。
5. 适用回归、身份/迁移说明、Lore/精确提交/远端核验。真实公共/私有请求、候选、测试网、实盘及人工解冻均不是本次设计批准附带的权限，C7 保留独立前置条件。

拟新增源码/测试名称仅为审查占位：`Trade/NativeMarketEvidence.py`、`Trade/NativeAdmission.py` 及对应 tests；也可沿原 utils 最小扩展。
涉及接入的原文件为 AccountSources/Store/Reconcile/RiskStore、AccountIdentity、CCXTTradeEngine、OrderAudit、db_util、OpeningInputs/RunTradeCycle；具体 diff 在各步 TDD 前收窄。
不修改用户配置、AGENTS/CLAUDE、权限或依赖，不把本草案当作对旧冻结边界的覆盖指令。

## 6. 原确认问题与审批边界

是否批准以上“独立证据＋显式鲜活性政策＋原账户/账本＋原 CAS 每单复验”的严格方向，先仅用 fake 实施？
批准不包含任何真实 I/O、自动解冻、默认容差/年龄、候选换代或现有配置变更；这些授权保持独立。
该问题已获上述明确答复；在不扩展范围的前提下直接串行实施，不重复请求同一批准。

## 7. 审计轮（实现前）的验证状态

CPython 3.14.2 短回归：非 dry-run 新风险常量门禁、原生账户身份/快照、历史持久冻结和输入报价，154 passed（18.64s），明确 exit=0。
JUnit：154 tests，0 failures/errors/skipped；SHA256 `979105764da300cdbc9669d1e812ff8bdef69cdf15c6b725a8a0cfe519c28c3a`。
它验证旧边界仍在，不验证草案中的新功能；本报告没有新可执行行为，不虚构缺函数 RED 或以旧完整回归冒称新功能已实现。

## 8. 批准后的 S1 实施状态

独立 [NativeMarketEvidence](../../../Trade/NativeMarketEvidence.py) 与 [来源测试](../../../tests/test_native_market_evidence.py) 已实现并通过离线验收，两版 Python 各 166 项。原账户/冻结/订单恢复/壳/报价适用组合各 734 passed / 1 既有 Binance isolated 通道 skip；完整证据及限制见台账。
每个市场保留两来源 raw/查询/原时钟/本地窗口和完整执行 metadata；公共路由/客户端环境逐请求前后检查，边界及 SDK 源码带摘要。空/交叉盘口不修复，来源永不 admission=true。
这是 S1，不是完整 fresh-admission：交付时尚无显式政策/全账户消费者/CAS 集成，旧常量阻断不变；后续政策子边界见下一节。读取已存字节只能验证内容自洽，不验证调用者真实性；SDK 本地摘要也不是服务端签名或 SDK 内部 HTTP 次数保证。没有真实 I/O、配置/规则/权限/依赖修改，C7 未获认证，Goal active。

## 9. S2a 显式政策与账户/市场观察使用检查

[NativeAdmission](../../../Trade/NativeAdmission.py) 已实现完整显式毫秒政策 reader，以及原账户/S1 市场观察的当前身份/metadata/年龄/跨度/时差断言。测试仍沿原 collectors＋fake native 运输，不把 raw summary 的重封 SHA 当来源认证；输入在读取 profile 期间变化会拒绝，最终字节核验耗时也计入使用预算。
新增 149 项，两版 Python 的适用原账户/订单/门禁组合各 886 passed / 1 既有 Binance isolated 通道 skip。该断言只返回 None，未接入开仓，不验证 wallet/execution 覆盖、原全账本/冻结、未决原生预占或 CAS；需要由后续完整消费者自己采集/关联，不接受外部 passed 布尔值。旧常量门禁、原 evidence flags=false 与候选/实盘/研究审批均不变，Goal 尚未完成。

## 10. S2b1 原持久区间来源的 DB-only 使用检查

`assert_native_persisted_interval` 接受原 check ID，在原 SQLite transaction/savepoint 的同一视图重读 check/source/history 与完整当前 trade-shaped 投影，检查 sticky freeze；不信 caller 的 report/PASS，不增加表或改写原 v1 证据。扫描年龄来自 wallet 原采集起止与 execution 原 manifest.native_account，历史覆盖范围、导入时刻不能代替原生观察起点。before 仍为历史锚点，after 才是当前账户点；所有当前来源共同检查预算，非零持仓 mark 与独立 mark 使用原 Fraction 数值规则精确比较，无金额容差。

TTL 未过也不能重用被同一稳定原生账户的新 snapshot 取代的旧 current 点；尚未组成 report 的新来源也不能忽略。同 finished 的完整 snapshot 不同则歧义拒绝，不按 ID/导入顺序择优。原 reader 在完整行核验后才关联账户，受损索引不能隐藏新来源。事务释放及最终输入字节核验耗时计入预算；释放后数据库当然还可能变化，未来原 CAS 内必须重新校验，不能把本次 None 当可携带的授权。

新增 56 项离线用例，原政策/使用 149 项保持通过；两版解释器各 1103 passed / 1 既有 Binance isolated 通道 skip（适用组合，不是新全仓结果）。核心子进程屏蔽 ccxt/模型/yaml/GUI/图床依赖仍可读原持久检查；其路径环境为显式临时注入，不读取实际配置。无网络、订单或冻结新写入；金融失败仍须通过原 reconcile_account 持久发布。原报告对 unresolved_attempt 的 incomplete 与所有 flags=false 均不放宽；此步未认证原生未决单/余额预占、完整金融闭合、CAS/HTTP 或真实服务。全历史重读容量尚未验证，S2/S3/S4、C7 和 Goal 均未完成。

## 11. S2b2 原生未决来源（归属与预占仍待）

新增 NativePendingOrders，独立读取 Binance fapi 普通/conditional 与 OKX 普通/八种 algo 通道；后者精确 native ID after 分页，缺页、重复、不前进、预算耗尽整批失败。每页前后原 typed profile 与当前 route/TLS/SDK 相同，保留原响应允许字段、请求/本地窗口和订单 mutation 时间。数据不是原子全账户快照，普通单列表为空也不意味着无预占。

复用原市场/单位/Decimal/身份边界；普通单归一化数量，未知市场、算法 closeFraction/条件量与复杂原生条款不猜为普通已归属订单。Binance orderId/algoId 按 symbol 自增，必须保留市场维度，不能以全账户 ID 去重。具体覆盖及未认证 bot/copy、经济预占等保留在 schema disclosures，两个 flags 始终 false。251 项新测试、两解释器各 779 项适用组合通过；主线程串行审查，无独立审计或真实服务认证。下一步仍为原历史归属、独立 native 保证金/余额观察及原 CAS/HTTP 消费，不能删常量阻断。

## 12. S2b2 原挂单/预留数量归属（经济闭合仍待）

NativePendingOwnership 复用原完整历史 reader、原 typed account、原订单纯校验和 transaction/savepoint；不接受 caller 的历史/PASS，不写订单、ACK、冻结或余额。每个同账户本地非终态 attempt 保留 requested-minus-filled 的 base/contracts 数量及是否匹配 native 普通单。真实 fake 接单后丢响应仍保持 submitting，空列表也不释放剩余量；重启后读取相同，所有 trade-shaped 表都纳入。

同账户同市场的多原 attempt 拒绝最佳匹配；Binance 跨市场同号可独立归属，可证明的其他账户可排除，未知历史与环境漂移保留问题。原生量/累计量、方向/腿、reduce-only、限价/post-only/GTC 等条款核验；算法/附件/外国市场不会被普通记录认领。原 DB 投影/事件链、单位/执行设置错误与倒退/晚于来源的本地事件拒绝。

这仍是数量与身份观察。两个 flags=false、native_margin_amount=None、未接原 CAS/HTTP；没有可用资金或原生冻结保证金结论，也不能替代原 sticky freeze/current-state/freshness 检查。下一依赖为独立原生余额/保证金/账户模式来源与原金融核算复用；完整 S2/S3/S4、C5/C6/C7、外部容量和 Goal 均未通过本子边界完成。

## 13. S2b2 原生余额/预占分项来源（消费者仍待）

NativeBalanceReservations 固定 configuration_before→balance→configuration_after；每段原 typed profile 前后读取及环境/SDK/客户端守卫，共 9 次显式 GET。没有账户/币种/标的过滤、重试、DB 写入、余额推算或新的金融公式。原 AccountSources schema/收据保持原字节语义。

Binance 资产/总额/原账户腿的 position/open-order initial margin 与余额、OKX 每币 ordFrozen/frozenBal/借贷/iso/策略/copy 字段均按允许原字段保存；未知/空项为 None，原币与 USD 总额分别标记，金额不转汇或分配到订单。窗口与 mutation 时钟分别保留，Binance config 保留字段 updateTime 不充当 fresh 时钟。配置响应自己的 UID 须与前后原账户一致，只记录 hash。

66 个新 case、两版各 940 项适用回归通过；源码编译/差异和核心无 SDK reader 验证通过。两个 flags=false，未形成当前金融 PASS；账户模式适用性、余额/预占的独立核算、原 wallet/executions 与完整 ledger/positions 闭合、sticky failure 发布及 CAS/HTTP 消费仍须实施，真实端点/内部重试/容量与 C7 未认证。

## 14. S2b3 原区间核算与未决/保证金组件的观察闭合

新增 NativeAccountReconcile DB-only reader，按原 source IDs 重读完整来源、全 trade-shaped histories/projections 与 sticky freeze；不接受 caller 的账本或 matched 集合。AccountReconcile 共享核算体的新 pending-v2 builder 自行从 raw pending 重建同一 ledger 的归属；旧 v1 builder 不能传入豁免集合，仍保持原 unresolved_attempt/字节语义。没有复制钱包链/费用/PnL/funding/pooled-entry 金融算法或订单状态机。

来源时间与 identity/市场池须对应最终 after；余额分项、原币/Upl/equity、独立 account positions、native available/IMR/MMR 和 pending/全历史 ID 歧义逐项核验。Binance ID 以市场分组，OKX 错 client 的已撤销零填单也不能遮住重复原 ID。更早的 availEq/crossWallet/crossUnPnl 不覆盖最终快照。外币现金不加到 USDT，未解释的外币保证金、isolated/借贷/copy/策略资金、非零挂单 margin 却无 native 单均 incomplete。native IMR 只用一次，真实更低 available 允许保留，不发明容差/FX/逐单冻结金额。

59 项新用例沿原合法双币实际假流水（部分平仓、部分开仓未决、费用、已实现、funding）；同记录开单未终结的平仓仍被原 CAS 拒绝。两 venue/模式/方向，丢失来源、历史 ID/余额/仓位变异、原 sticky freeze、嵌套事务、重启及无可选 SDK/配置的子进程均有证据。v1 对相同双币输入与已接受 2ee0345 源码逐字节比较 2 项通过；该一次性 release 检查未成为常规单测的 Git 历史依赖。

最终精确测试范围和 XML 摘要见台账。matched_components 只描述所给观察，仍两个 flags=false、无源码重新武装或订单授权。新来源持久化/失败发布、完整 freshness/current-client/独立 mark 绑定、原 CAS/HTTP 与默认入口仍待；保持全部现有门禁与 Goal active，不声称完整 C5/C6/C7 或真实服务通过。

## 15. S2b4 原生来源持久化子层

NativeAccountStore 新表只收当前版本原始 pending/balance 文档，ID 为完整 canonical 字节摘要；重读重算 raw/派生与代码身份、窗口、稳定账户、context/venue/mode/kind/observed_ms。账户列举先读验全部行再过滤，不信索引能隐藏损坏/较新文档。原 AccountStore SQL 与两种旧 schema 未改，不把旧来源重封为新来源。

显式三接口沿原 SQLite transaction/savepoint，初始化/外来同名表失败原子回滚，append-only 含 REPLACE 防护，缺触发器和重封金额/标记均拒绝。85 项 fake 新测试、两版广组合各 1519 pass/1 既有 skip，包含原账户/订单/冻结与 SQLite 事务；核心子进程读验无可选 SDK/实际 YAML，主线程审查，未做真实端点/容量/外部独立认证。存储层不采集或写订单，不创建检查/冻结，不提供真实性或当前性证明。下一依赖仍是原 check 的新组件历史重建和 sticky failure 发布；S2/C5/C6/C7/Goal 未完成。

## 16. S2b4 原检查表的新组件重建与 sticky failure

NativeAccountCheck 已由持久 before/after/wallet/execution/pending/balance IDs 重读来源、同视图全 ledger，沿原 checks 表/publisher 写新版本检查；原 v1 document/schema/风险聚合保持，不另设 reset/冻结表。组件纯核验与 DB observer 共用，原 observer 另读当时冻结，历史 reader 不递归 risk_state、不采用当前投影替换旧输入。源不可读/核验错误形成固定脱敏 failure，后来的 matched_observations 只说明新一组历史组件匹配，不能清除任何旧 v1/native failure。

保存的原 event_id 前缀、全部 attempt/event 原行摘要及 key/事件数须与原不可变 journal 相符；原逐 attempt prefix verifier 仍核字节链。以显式 event_id 而非 attempts 隐含 rowid 标记版本，避免普通 SQLite compaction 重排造成伪身份。测试包含删掉零成交已撤销尝试及 projection、重新计算一个 matched report 并全重封 check 后仍拒绝；未来真实减仓推进 ledger 不改旧 check，重新启动可复核且无 SDK/配置或新写入。

37 项新测试、两版适用广组合各 1662 pass/1 既有 skip/6 小样本模型警告；包括旧冻结/金融/来源/订单、部署契约/工作流和持久 paper。跨连接 native failure 在原 claim 后、HTTP 前阻止发送，未知提交不自动重试，原减仓仍可执行；无真实 HTTP、长期容量或独立外部认证。新 check 明确两个 flags=false/历史组件观察，完整 freshness/current source/current client、独立 mark/book、每单 CAS/HTTP 和源码版本绑定仍待，不删除常量阻断或重封旧候选，Goal active。

## 17. S2b5 所有组件来源的联合使用断言

NativeCurrentComponents 新增独立完整政策版本，balance age/span 各自必填；旧 v1 不拓宽、不回填预算、不加金额/数量容差。复用 NativeAdmission 的原 DB 当前区间体和时间 helper，将匹配 native check 的全 ledger/冻结/原来源/独立 mark/book 与新的 pending/balance 窗口、当前 typed account/public route/SDK 和最终 use-time 联合复核。两次 DB 当前视图包围事务外 private profile，拒绝调用者已占有的事务；任何中途已知账本/冻结/来源/输入变化或超龄均拒绝。

较新或同 finished 不同字节的未整合来源不能用 SHA/排名选择，所有来源索引/原始派生均先验后按稳定账户过滤；native SDK 自洽但不对应当前市场/client 的历史包也不可代替绑定。各角色年龄、市场/全组跨度和 skew 恰等通过，少 1ms 拒绝；新 pending/balance 的非零采集跨度由真实 fake collector 固定 GET 计时验证，mutation/update 时钟不是新鲜度。相同 execution packet 重导入不刷新首次 native association，新查询窗口才是新 source。

107 项新测试，CPython 3.14.2/3.11.15 适用组合各 1663 pass/1 既有 skip，JUnit 用例集合完全相同；未变的模型/部署回归沿用 db75c5e 证据。严格串行、活测试不编辑、主线程审查、无真实服务。None 不表示 admission，也不替代 collector-owned、真实 instrument metadata/原 CAS/HTTP、总请求/SDK 内部重试/长期容量或 C7 外部认证；新风险常量阻断与所有 gates 不变，Goal active。

## 18. 推送前事实覆盖复核纠正

12ab104 尚未推送时，发现仅按 source finished 时间核 latest 仍会忽略较早观察包中的已知区间事实。真实两 venue × wallet/execution × 区间内/终点后 8 项出现错误接受；基线前 4 项按原范围通过。构造的是原 collectors/store 中可验证的零净额转入转出或买卖往返，并非直接改 caller 的 matched/count。wallet 首次 setup 因全局 clock 倒退而正确拒绝已有来源未来时间，恢复正常 use clock 后确认 8 项真正 DID NOT RAISE RED；保留该区别。

最小修复只对同一稳定账户/标的的所有已知原始规范事实检查覆盖：区间内每条 canonical fact 都须在所选输入内，终点后任何已知事实使点过期，基线前事实不误纳入；不净额比较、不拓宽容差、不复制金融核算。当前 119 项，最终两版关键组合各 361 passed；原广组合仅对未变代码继续有效，不把它改报为修复后的全仓验证。仍未接 collector-owned/CAS/HTTP，保持 disabled/Goal active。

## 19. S2b6 本地自采和原失败发布

NativeComponentCollector 已沿原 collectors 的固定顺序自取完整来源，再在同一原 SQLite 事务发布来源和新版本 check，最后执行联合 current 断言。入口不接 caller receipt/check/PASS，原 before/全 ledger/冻结先读；全部 GET 位于写锁外，原 raw/source schema、金融公式、订单/CAS 和配置均不变。after 的市场排列须沿原 before 保留，不能重封旧锚点以配合新的规范扫描顺序。

新增故障注入的主线程复核发现并 TDD 修正：①无效 account_scope 先前到 execution 才拒绝，已提前执行原同一 predicate；②核验结果随事务提交失败回滚后，不得误认为其冻结已持久保存，以成功退出事务为界；③失败路径也须核原连接/位置，不能因连接被替换而把失败写进另一库。普通 source/check 插入失败原子回滚，独立 failure publisher 只保存原 inputs=None 的固定不可用结果；若原库本身不可写/身份不确定，则拒绝且不作已冻结声明。已有精确失败只提交一次，重启仍冻结，后来调用不会自动重新采集/解冻。

78 项新测试：两 venue/两模式/多空/两币非空持仓及实际部分假成交、未决保证金、费用/资金费；阶段异常脱敏、不重试/不写订单；非法入口零 I/O；SQL 插入/提交回滚；并发 ledger/freeze、输入/源码/owner/连接变化；核心导入不触及 SDK/Config。两版适用广组合各 1753 passed/1 既有 skip，1754 个唯一用例集合相同；两版 compileall/diff，通过范围及 JUnit 摘要见开发验收台账。仅主线程审查，不称独立审计。

自采的本地文件 SHA、DB 位置和 source IDs 不构成服务器签名、已加载代码/真实 instrument metadata 完整身份或原每单授权。诊断输出两个 flags=false；计数只覆盖显式 SDK 调用（两市场实测39/58，保守界276+132N/274+132N），不认证 SDK 内部重试/容量。完整 S2、实际 instrument/候选/部署/配置/DB/runtime 与原 intent/CAS/HTTP 绑定、每单预占协议仍待；不得把原生可用额观察自行变成新单保证金公式、容差或授权。全部 candidate/testnet/live gates、原常量阻断及 Goal active 保留，未做真实 I/O/C7。

## 20. S3a 独立原生 instrument 来源

账户预留/CAS 详细协议尚待确认，不将自动 Goal 续行视为批准。其独立前置来源 NativeInstrumentEvidence 已实现：原生公共 GET 一次，固定 fapi exchangeInfo 或 public instruments SWAP，不通过 load_markets/reload/currencies loader、不改 client cache/options，也不接 caller metadata/PASS。全允许 raw_rows 保留重复/目标覆盖核验、精确请求/批次窗口、endpoint/参数/环境/SDK/代码；按当前 credential-free SDK 的纯 parser 重建，再沿原完整 metadata/单位验证，与原 Engine 投影字节一致，未复制 parser 或资金公式。

所保存的是允许字段覆盖，不是所有平台过滤条件已执行。Binance tick/lot 必须有真实 filter 及完整必要字段，不以 pricePrecision/quantityPrecision 补缺；OKX ctType/显式币种/合约价值币种不能被 underlying 的 SDK 推断掩盖。包括不参与最终投影的已知 numeric 字段也须有限，SDK 备用精度分配先限制在原 _MONEY 指数范围 0..100；日期/即将变更时间严格整数毫秒但不拿来刷新来源，未来变更只保留，不提前应用。缺/重复目标、同符号歧义、错误产品/单位/类型和异常均拒绝整批，不择优或回退缓存。

主线程复核先以10项实际RED证明：环境在请求开始读时变化后，不应仍发GET；Binance错误包即使带有效rows也不能接受。最小前置环境复查/错误envelope拒绝后绿色。其余真实RED包括目标池变异、缺filter时SDK补值、显式单位/有限数字/typed时间/环境bool别名与缺原约束字段。422项新用例覆盖三SDK类×live/testnet标签、两市场与64/65边界、cache投毒/不变、raw/派生/重封/SDK/环境/源码/时钟漂移、非交易状态、无HTTP及核心导入；最终双解释器各1122 passed，0 failure/error/skip/warning，集合一致，详情见台账。

两个 flags=false；source_ms=None/clock_kind=local_request_window_only，不提供服务端生成时间或原子性认证，显式reader需要对应SDK。未改旧账户/市场来源、金融、订单、配置、权限或依赖；现有 Engine cache 路径与默认壳阻断不变，新来源还须绑定实际 per-order/runtime/完整政策/原CAS。详细预留协议、逐单资金能力、原生实际吞吐/SDK内部重试与真实C7均未完成，不能重封旧候选/产物或关闭主Goal。

## 21. S3b 原 Engine 当前缓存与自采 instrument 对齐

新增独立 NativeInstrumentCurrent，不改已验 Engine/来源/金融/CAS。入口自己调用原 S3a 一次公共采集，只收原 Engine、显式目标池和必填非负整毫秒 age/span；不收 receipt/PASS。实际 SDK 缓存的完整 markets/markets_by_id/options/索引、public environment、SDK 及原 Engine/SQLite 连接/位置前后必须不变。只在现有缓存完整、原 bound methods 未替换时调用原 `_market_contract`，避免原 SDK loader 走 I/O 或 set_markets 分支；新鲜来源与原投影、typed active、native state 必须逐字节相等。不用自动刷新修补旧 cache，不重新实现 parser/metadata/资金公式。

原来源窗口以本地 started→finished 计算 span，age 则到消费方最后全部核验完成为止；reader 和最终 DB identity 费用不能刷新来源或从年龄里扣除，恰界允许、超 1ms 拒绝、bool/float/缺预算无默认。没有服务器生成时间，不制造 skew 证明。缺 owner/cache/方法或已有事务在 GET 前拒绝，采集期间的 cache/engine/code/SDK/route/input/DB 漂移在返回前拒绝；替换连接不查询或写入，失败无 DB/订单写入和重试。

先 1 failed 的直接缺 API RED，最小实现后 133 passed；保护性补查后 398、最终 446 专项通过。两版关键集合各 1568 passed（446 新＋422 原 instrument＋700 原市场/自采/current/核算/政策/订单），0 failure/error/skip/warning，JUnit 唯一集合差异 0；compileall/diff 通过。主线程审查、严格串行、测试活进程不编辑，无独立审计或真实服务声明。其余未变模块沿原证据适用范围复用，不冒称本轮全仓测试。

输出只保留原 S3a 来源 document，两个 flags=false；matching inactive 仍非许可。新消费者未被默认 prepare/CAS/HTTP 调用，未纳入旧模型/部署/输入/paper 指纹；不能重封旧产物、解除常量阻断或据文件/方法字节核验宣称加载 runtime 可信。账户级预留详细协议尚待确认，逐单资金能力独立缺口、全部平台规则/内部 HTTP 重试/真实容量和 C7 均保留，S3/C5/C6/C7 和完整 Goal 未完成。

## 22. 详细协议获批后的 L0 前置边界

新增 NativeOrderBoundary，只复用原 DB-only current snapshot、native check/全 ledger/journal-prefix/risk state、完整显式 policy/原时间核验。capture 从自有已提交视图产生版本化 L0，assert 必须在原 SQLite 所有权事务内重读，拒绝旧 ledger、来源、冻结、prefix/DB/代码/输入和窗口变化，另拒绝无任何 event 的孤立 attempt。两个 flags=false，不写订单/冻结，不计算资金公式、不做 SDK I/O，原 v1/v2/v3 字节、表和默认发送不改。

主线程故障注入发现新模块的最终代码核验后连接切换缺口：8 个 capture 已拒绝但查询了替换库，8 个 assert 未拒绝。先真实 16 RED，再共用原 DB/conn/table/事务所有权守卫，在最终代码检查后、位置查询前后执行；16 GREEN，替换库零 query/write。此前 fixture 的 positions 路径和 hedged 缺 record/leg 分别导致 8/16 失败，只修测试构造，不放宽原引擎；不把它们计为生产缺陷 RED。

153 新用例＋340 原 current/核算/检查/冻结/历史/事务用例，两版各 493 passed，0 failure/error/skip/warning，唯一集合一致；双解释器 compileall/diff 通过，均 fake/主线程串行。实验在同一真实事务中组合 L0 assert 和原 CAS，验证跨记录/市场/表/连接不能复用旧 L0，外层回滚仍归调用者；但这并非已接默认原 CAS，更没有已完成本单唯一 L1/L2 增量、持久引用或资金能力证明。后续继续这些已批准工作，不再重复要求账户级设计批准；全部真实服务/资金/候选门禁和完整版未完成状态保留。

## 23. S3c 原 intent/claim 精确增量与持久引用（限诊断子边界）

用户另已明确恢复原Goal自动串行执行；当前Goal工具已返回active，未创建替代目标或缩减C0–C7。以clean、已推送d839f5c为起点，新增NativeOrderTransition，在原 `_order_write` 所有权事务内核L0→本单一个intent/attempt→L1、原claim→本单一个claim event→L2。原journal追加新版本引用和独立整行delta摘要；新append-only表只引用对应显式event_id，并保存完整原ledger/全部trade-shaped行摘要及前缀，失败回滚原CAS与引用。claim从原持久行取L1，不接受caller expected ledger/PASS，不忽略自己或任意其他行；跨market/table/connection同L0仅一个成功。

原current来源核验与L0账本断言最小分离；所有旧公开入口仍强制L0完整账本，新增消费者必须重建原检查＋本单完整原attempt/事件的唯一差异后才能核来源/冻结/时间。重封后的投影/账本摘要不能代替原事件；孤立无event的attempt、后来的信号或任意其他整行字段/历史、原来源、sticky freeze或超预算均拒绝。最终时间检查在引用INSERT/回读之后，包含该耗时；仍非事务退出后/HTTP边界的完成证明。

主线程真实RED覆盖缺API、重封投影与孤立attempt16项、直接Engine lookup及代码回调换连接16项、版本/typed字节/原更新集合/SQLite分数56项、市场与leg16项、写入/回读晚1ms32项和旧无引用子类兼容1项，逐项GREEN。初组8失败为夹具订单时钟落后当前账户40ms，只统一fake时间、不放宽生产预算，未计为生产缺陷。删除重复finish ledger组装，复用原检查＋已核不可变事件重建；没有第二套资金/撮合/订单引擎。

新意图使用独立且不可执行的 `chan-native-cas-order-v1`，原已存v1/v2/v3不改。当前Engine在exchange lookup前拒绝新一致性引用；不认识新标记的旧严格contract reader也拒绝新schema，避免旧程序按普通v3执行。旧原生订单的query/ACK/累计报告/恢复/减仓和paper仍按原已验契约。新增表由原SQLite原子schema初始化/保留名保护；foreign同名表不收编，append-only UPDATE/DELETE/REPLACE不通过，删引用表不能降级原journal绑定。

381项新测试；最终CPython3.14.2/3.11.15各3688 passed/1既有skip/13小样本训练警告，54模块/3689唯一用例集合相等，0failure/error。包含原安全/状态机/账户/执行/冻结/native sources、opening/deployment和多市场配置化/持久paper；两版compileall/diff通过，详细JUnit身份见台账。测试全fake/合成/临时SQLite，串行且活测试不编辑；无独立代理审计或真实服务声明。

两个flags仍false。该层只完成原CAS精确增量与不可变引用，不完成来源本次调用权、实际信号/候选/部署/config/loaded-runtime prepare绑定、全新可执行版本与所有reader/ownership/指纹、逐单资金能力、HTTP/default全入口和S4/C7；真实容量/SDK内部重试/服务器原子性未证。旧模型/部署指纹受db_util/OrderAudit/CCXT等实际代码变更影响，不能重封旧产物继续用；无配置/权限/依赖/候选变更，常量阻断保留，完整版未完成。
