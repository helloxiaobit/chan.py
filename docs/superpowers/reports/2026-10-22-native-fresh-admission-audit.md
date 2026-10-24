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

## 24. S3d 实际本地 prepare 身份前置层（非完整自采/准入）

从已推送且clean的1cb330c继续；Goal保持active。新增NativePreparation，只接实际原Engine及record_id/数量/价格/post-only/适用entry assessment，不接caller收据、check或PASS。自行重读原信号及状态、原配置/完整行情epoch/scope、fresh candidate和kill/testnet/live门禁，调用原prepare_order取得完整v3执行条款与两单位；原部署/模型entry使用原verifier重建，不相信passed字段。前后核原DB/conn/table/Engine/guard/policy所有权、真实输入和候选字节，禁止writer事务内发private I/O。无订单、资金、冻结或配置写入；失败脱敏。

主线程审查按RED/GREEN补齐scope漂移、最终时钟回调改record/config/candidate、非法开始时钟和最终实现检查换owner/config/kill；同一owner检查与原输入读取复用，未复制金融或订单状态机。48项加载边界RED覆盖env/scope property、静态限额和数量/精确float/契约摘要helper；9项有效RED覆盖同code不同globals和entry verifier替换。末尾8项RED证明未初始化client会触发原Engine会话创建，现已在任何准备调用前拒绝。复制函数测试首次遗漏__class__闭包造成8项fixture构造错误，修正后才观察上述有效RED，未计为生产缺陷。

fresh AST/compile只读当前解释器源码，不exec、不加载第二份交易实现；选定函数核owner、模块globals、code与默认参数。源码与选定函数一致不代表全部传递依赖/解释器/SDK或服务端可信。started/finished为本地身份采样，不是native数据时间或完整耗时预算；最终重复检查也不是跨线程/服务端原子锁。JSON明确coverage=actual_local_prepare_identity_only，economics_complete/native_admission_verified均false，不能作为可转交令牌接原CAS。

438项新测试，CPython3.14.2和3.11.15相同10模块各754 passed/0failure/error/skip/7warnings（182.22s/191.57s），唯一用例集合无差异。覆盖原opening inputs/quotes/streaming、contract/venue/account binding、trade safety、model contract/deployment workflow；模型警告为3个小样本XGB AUC和4个MLP收敛。真实小合成模型/部署有正反例；普通prepare夹具不是完整非空账户instrument/component→CAS集成验收。先前1cb330c的54模块双版3688 passed证据仅用于未变旧代码，不冒称本轮重新全跑；先前两版746项是增加client前置拒绝前的中间结果，详尽最终JUnit身份见开发台账。

未修改旧生产文件/默认入口、旧契约或实际配置/规则/权限/依赖/candidate；没有真实交易所请求、订单或研究绩效读取。当前仅完成实际本地prepare身份前置层；同一调用内instrument/component自采绑定、原CAS/HTTP消费、逐单资金能力、可执行新版本全部reader/指纹及S4/C7继续未完成，常量阻断和所有候选/交易门禁保留。主线程复核，无独立代理审计声明。

## 25. S3e 原生单位、非空账户与实际SDK的联合前置验收

从clean且已推送1944a67继续。旧账户夹具的Binance合约大小为.01，不能直接接原生parser的1；本轮只新增tests/native_order_preparation_case.py、test_native_preparation_sources.py和文档，不改旧fixture、生产代码、已发布事实或订单。先从独立raw instrument构造实际SDK metadata，再由原Engine/SQLite生成TEST .06开仓→.02部分平仓、ALT .6请求→.3部分成交未决；两币实际持仓、手续费、资金费和原生预占均非零，原钱包与头寸引擎独立核算。

实际prepare用同一真实SDK client的原fetch_position_mode/fetch_leverage/precision方法，fake只在明确原生运输端点；HTTP和发送硬拒绝，所有GET均断言writer锁外。Binance首次杠杆查询会加载bracket并更新options，需先稳定prepare再采instrument；不将此缓存/测试金额转为资金能力。原组件自采、fresh候选前后读取及原L0/原事务断言手动组合可过，尚未实现生产受控入口或prepare持久CAS引用。

22项覆盖8个venue/模式/方向正向、12项metadata/candidate/pending/wallet/funding/cash拒绝与2项自采期间candidate变化。明确核钱包差额0、TEST quantity=1/25、unrealized=4/5、reported_available=988.969、aggregate_order_margin=10和一个原未决reservation；不是空仓证明，也不推导本单资金。来源错误沿原publisher形成sticky failure，早期metadata/candidate拒绝不冒称已发布账户冻结。

初始命令参数、合成与真实时钟混用、SDK未fake的leverage-bracket GET及1.0字符串预期均是夹具/命令构造问题，未修改原解析器或计生产RED。主线程末审2项fixture RED证明raw与SDK info同引用，改为创建缓存前deepcopy；8项fixture RED要求初始空账户margin=0/available=1000、OKX最终汇总与.8未实现及1000.969权益一致。未放宽任一生产规则。

最终CPython3.14.2/3.11.15各22 passed、0failure/error/skip/warning（27.15s/27.89s），唯一集合相同，compileall/diff通过。此前同5模块两版各1137 passed/1已知小样本XGB警告（318.79s/324.02s）；最后修正只影响22项新fixture，其余1115项代码/依赖/环境未变并复用该证据，不称最终1137整组重跑。JUnit身份见台账。下一步先复用本地prepare当前核验体形成无GET锁内断言，再接受控自采/版本化原CAS引用；完整S3/C5/C6/C7、每单资金/HTTP/default仍未完成，Goal保持active。

## 26. S3e 活prepare上下文与原owned视图无GET断言（2026-10-24，有限子层）

从clean且已推送9252545续行。NativePreparation原capture实现内部改名为_capture_native_prepare_context，公共capture仍返回原非可执行JSON副本；同一owner/current闭包同时服务原capture和后续owned断言，除显式owned状态外保留原读取/真实prepare/最终检查次序。新空handle仅通过WeakKeyDictionary关联原Engine、冻结JSON字节和实际核验闭包；没有资金/订单/释放/TTL状态、持久表或交易授权。dict/复制/另造handle/借用Engine不能通过；GC只回收本地内存，不修改原created/unknown意图。

assert_native_prepare_context_current仅允许原SQLite wrapper拥有的事务，拒绝raw BEGIN与锁外使用。前后重读原信号完整行、配置/输入epoch/scope、fresh candidate/环境门禁、选定loaded runtime和已初始化client缓存/route属性；适用时原entry verifier重新读真实模型。原freeze读取移到最终本地重读之前，原DB/conn/table/Engine/guard/policy/clock所有权始终保持；不调用prepare、market/load_markets、private/public GET或写表，返回None。实际SDK非空双币来源之后同样可核，不改旧source或金融公式。

TDD证据：缺API 1 RED；使用时钟倒退/非法类型与末尾clock变异72 RED→严格整数及前后本地重读；risk-reader回调最后改record/candidate/kill的24 RED→只移动原风险读取先后位置，复用同一current，不叠第二套校验。8项intent用例首跑误用snapshot_before参数及位置顺序，只改测试为原API，随后16项intent/freeze通过，不把构造错误算生产缺陷。原438项prepare和22项联合夹具继续保护公共行为；真实小合成部署对entry修改/模型文件损坏均拒绝，恢复的仅测试自有临时artifact。

313项新上下文用例；最终CPython3.14.2/3.11.15相同12模块各1089 passed、0failure/error/skip、7已知小样本警告（433.36s/455.12s），1089唯一用例集合一致。7警告是3个XGB AUC和4个MLP收敛；双版compileall/diff通过，JUnit身份见台账。全fake/临时SQLite，无SDK实际请求/下单、实际配置/权限/依赖/候选改变或研究绩效读取；主线程审查，无独立代理审计声明。

限制：handle并非可抵御宿主任意globals改写的能力隔离，更非服务器原子性或跨重启凭证；本地检查未变不证明native来源年龄/每单资金。新代码未接默认consumer，也未将prepare身份持久绑定至原CAS。当前仅intent前严格完整记录，合法intent后须拒绝而非忽略自身；L1/L2之后必须按新版本原事件独立重建和全部reader/指纹验收。完整同次自采→L0/CAS、HTTP前/默认全入口、逐单资金与S4/C7仍待，两个flags=false、常量阻断和完整Goal active保持。

## 27. S3e 同次prepare/自采与原intent持久绑定（2026-10-24，有限子层）

基线01d4c54已推送且clean，原Goal active。新增NativePreparedIntent，入口只取实际原Engine、原请求和完整显式政策/预算/before ID，不接caller receipt/check/PASS。首次owned视图先核原before/mode/sticky freeze、固定完整trade-shaped行与journal前缀；实现身份固定在任何来源读取前。锁外实际prepare、原instrument消费者及原component自采，然后用同一活上下文进入原L0/intent CAS。原writer同事务核精确整行/唯一intent增量、原attempt/journal和全ledger，并保存完整preparation引用；不新建表、金融公式、额度或订单状态机。

新文档schema=chan-native-order-transition-v2，仍在原append-only表，root只增加preparation；原v1形状/读取与旧v1-v3契约不重封。原NativePreparation三项关联/公开JSON保留，内部只为原writer已经独立验证的expected after-row增加分支：实际DB完整行必须恰等expected，随后才用冻结signal复核原输入/候选/entry。公开pre-intent断言不接受expected、intent后仍拒绝。最后本地回调后再次核原完整transition，来源窗口还包括原引用INSERT/回读时间，不能用自身记录排除来消除差异。

stored reader严格核schema/字段/typed请求、原attempt两单位/条款/输入、原check来源链接、instrument raw与组件metadata、policy及固定操作顺序/时钟；重启时无需client/GET/重新prepare，但raw instrument重建需要对应SDK。原v1没有这个新增SDK要求。失败回滚原intent/attempt/journal/引用，已采原始观察可保留；来源失败沿原sticky publisher，原库不可写或身份不明不冒称冻结，已知sticky在新GET前拒绝。

72项新用例涵盖两venue×one_way/hedged×多空非空历史、两个真实小合成模型、候选/现金/未决/第三方行变异、SQL/引用/晚1ms失败回滚、假上下文/重封字段、原合法Binance client ID、显式预算、第二未观察意图拒绝和核心无可选依赖import。真实RED后修复晚本地回调改第三方行、实现固定过晚、已知冻结/非法开始时钟到GET、独立stored字段/政策别名及组件字段/顺序。最初clock/contextmanager/venue方法名、模型fixture跨过原1h有效期仅修测试；未放宽政策。GET之后的未观察服务器现金变化另设限制用例：可以形成历史一致的诊断引用，但不能因此claim，不虚构服务器原子快照。

最终相同24模块两版各1841 passed、0failure/error/skip、9warnings；CPython3.14.2为983.66s、3.11.15为1019.22s，1841唯一用例集合一致。包含原381 transition/313 context/438 prepare/22联合、原状态机/SQLite/报告CAS/历史/恢复/账户绑定/冻结/执行、安全、opening/模型部署和持久paper/cycle；非全仓。警告为5个小样本XGB AUC与4个MLP收敛，双版compileall/diff通过，JUnit身份见台账。全fake/合成/临时SQLite，活pytest不编辑，主线程审查、无独立代理审计；实际Config/config.yaml与CHANPY_CONFIG仍不存在（仅查存在性），无真实I/O/订单/研究绩效读取或实际配置/权限/依赖/candidate改动。

当前v2 intent仍是不可执行chan-native-cas-order-v1；原Engine/旧严格reader不把它当v3，v2 claim即使重启也在原SQL前拒绝，原v1诊断claim不被新分支重写。两个flags=false，未知状态不自动释放。本地handle/源码指纹不抵御宿主任意globals改写或认证整个加载闭包；完整L1/L2后本地重建、新可执行版本全reader/指纹、逐单资金能力、HTTP/default/S4/C7与真实容量仍待，完整S3e/C5/C6/C7未完成，Goal保持active。不能重封旧模型/部署/candidate或移除任何默认阻断。

## 28. S3e 原L1本地重建与原SDK摘要基线（2026-10-24，资金/claim未开放）

从已推送clean的67e72ef继续，原Goal active。assert_native_prepared_intent_current只接实际Engine和record_id，必须在原owned SQLite视图从原持久transition、不可变attempt/event取得精确after-record/full-ledger基线，再复核实际guard/config/输入时代/候选/模型entry/selected runtime与本地SDK缓存/public-private route；不接受document/hash/expected record/PASS。它不是反解旧before hash或排除自身变化，实际整行仍须与原事件绑定的after hash一致。成功仅None，无GET/prepare/写表/新观察或资金许可；原Engine在v2意图上实际消费后仍执行原资金拒绝。

按事前清理计划，NativePreparation的原current本地读取体及NativeInstrumentCurrent的缓存投影各提取一份，旧capture identity/公开pre-intent断言、原collector owner/GET/时间顺序保留；新增共用helper纳入selected runtime。未复制financial/metadata parser或订单状态机。新写入的preparation binding-v2只增加client_binding_sha256，冻结原调用的完整已观察cache/options/route与实际apiKey/secret/password摘要，不保存明文或替代原native UID。旧binding-v1历史可读但不补摘要/重封，不将新会话的当前SDK状态冒称旧基线；原transition文档v1/v2、原来源schema/SQL表和旧v1-v3订单字节不改。

真实RED/GREEN：缺API 1/11项；初步11 GREEN后，8项“先前SDK/options/凭据已变但本次核验前后相同”以及2项“原Engine未消费检查”RED，补原摘要和真实原入口后21 GREEN。134项绑定/当前性联合、8项末尾risk回调和凭据不落明文专项通过。最终70新用例覆盖双venue/持仓模式/方向的非空L1、无活handle/new Engine/guard/connection、原缓存/路由/输入/候选/冻结/时钟/全部账本漂移、模型文件损坏与严格旧形状/新摘要字段。没有放宽任何源、预算或金融门槛。

额外使用67e72ef精确提交后72项回归留下的两venue原数据库，仅在新副本运行原历史reader，结果与原文档相等、claim拒绝，原文件SHA未变。首轮失败源于诊断未带原合成时钟：当前墙钟1792780882819小于fixture来源1800000000506；恢复同fixture的as-of后成功。不改产品“未来时间拒绝”，不重封旧数据，不计为产品缺陷RED。新Engine/guard/连接重建仍使用相同已初始化SDK缓存；未验证冷启动新SDK完整初始化，不称完整重启发送能力。

最终双解释器相同26模块各2357 passed、0failure/error/skip、9模型警告（1184.74s/1235.38s），2357唯一用例集合一致；覆盖原438 prepare/313 context/446 instrument current/381 transition及订单/恢复/SQLite/报告CAS/账户/冻结/执行/safety/opening/model/persistent-paper/cycle。5个小样本XGB AUC、4个MLP收敛如实保留，双版compileall/diff通过，JUnit及旧库SHA见台账，非全仓验收。全fake/合成/临时SQLite，活pytest不编辑；主线程按review模板复核，无独立代理审计。实际config/权限/依赖/candidate/研究数据和交易门禁未变，无真实交易所I/O或绩效读取。

结论：该非执行子层可提交，生产就绪=否。所有v2 claim仍在原SQL前拒绝、两个flags=false，旧v1诊断/原v1-v3恢复保持原分流。冷启动SDK重建、L2/HTTP前/全新执行reader与指纹、逐单资金能力、默认全入口/S4/C7和整个加载闭包仍未完成；源码/本地hash不是服务器签名、整个宿主可信或原子账户锁。C5/C6/C7和完整S3e保持未完成，原Goal active，不重封旧候选或解除默认阻断。

## 29. S3e 显式新SDK冷启动与原L1重建（2026-10-24，仅离线非执行子层）

基线e65d0f9d40851de0374e329bb47bb22d43de2b6d已推送且clean，原Goal active。新增NativePreparedClient显式入口，只接实际原Engine/record_id与必填instrument年龄/跨度；只允许exchange=None、原owned事务外、实际输入/候选/门禁和原库有效的冷启动。沿原get_exchange→DataAPI.ccxt.create_exchange创建新SDK，公共instrument采集选择原目标池允许字段，再用原纯parse_market和set_markets初始化该新对象；原_execution_settings/_observe_account及observe_account_context核账户。所有GET在writer锁外，不进入缺缓存load_markets、跨产品loader/费用猜测或set_leverage，不修改已有client或实际配置。

signal仅初始化以供原受控prepare使用；原intent另须在原owned视图核完整binding-v2、原after-record/full-ledger/journal、原SDK完整摘要及旧来源窗口。新instrument/设置GET不能续旧来源、替代原client基线或重封旧binding-v1。失败只清掉本入口新建且仍由Engine持有的client，不覆盖外部替换对象；原订单/引用/未知状态不释放。已知原L1账户且原库身份可核时沿原sticky失败publisher，原库未知/不可写不声称已冻结。该API不写订单/收据，不接默认sender、不产生PASS/权限或资金额度。

按事前清理计划，将重复本地核验提为同一owned closure，复用原local/cache/transition/ledger，而非新增parser、金融或订单状态机。真实RED包括缺API、6项最后时钟之后记录/候选/client变异、2项SDK摘要收尾耗时未计入instrument年龄，以及实际factory未纳入原preparation实现身份。最小修复后54 GREEN。原真实SDK的Entry.api为单元素list、缺password默认为None，最初fixture的路由映射/缺原component端点和凭据默认假设分别修正，不计为生产RED；调试命令曾遇默认pytest临时清理symlink WinError5，后续GUID basetemp通过，未删除或据此修改产品。

54新用例含Binance/OKX×one_way/hedged×多空新SDK→原intent→销毁→新SDK原L1、两个fresh Python进程仅从原配置/临时库和fake native wire packets重建（不传markets/options/cache）、source/account/settings/超龄失败、显式预算/已有client/caller事务/伪receipt拒绝、已知冻结在创建SDK/GET前拒绝、核心无SDK/Config/ML导入。最终双版8模块各368 passed、0failure/error/skip、2既有XGB小样本警告（411.46s/433.15s），唯一用例集合一致；双版compileall/diff通过，JUnit身份见台账。未变其余基线按原适用范围复用，不称本轮全仓或2357整组重跑；主线程按review模板复核，无独立代理审计，活pytest不编辑。

另取e65d0f9精确提交后两venue的实际binding-v2临时测试库，仅在新副本以原finished_ms+1000合成时钟用当前reader读取，原完整文档相等且claim拒绝，原文件SHA不变；旧implementation缺factory条目保持原样，不冒称当前/冷启动准入。这里只证明历史读取兼容，未延长旧来源或迁移旧绑定，详细路径/身份见台账。

结论：本显式冷初始化/原L1非执行子层可提交，生产就绪仍为否。成功依赖原完整SDK摘要可由当前允许的原生数据/配置重建；任意外部cache/options、代码/凭据/SDK/输入时代或旧来源超龄均拒绝，不自动刷新补造。fake运输未验证真实签名、HTTP、平台容量/内部重试或服务端原子性；本地源码hash不认证全部加载闭包/宿主。资金能力/可执行L2/HTTP/全部reader/default/S4/C7、完整S3e/C5/C6/C7和Goal仍未完成；两个flags=false、v2 claim/默认资金阻断不变，无实际配置/权限/依赖/规则/候选/研究数据改动或真实I/O。

## 30. 冷启动末尾SDK复验与尾段年龄上界（2026-10-24）

基线6ce2c92563e6af5c50817384ff601ab0bad4242a已推送且clean；其资金设计选择仍待用户确认，不将继续Goal解释为批准金额公式。本次独立修复已批准冷启动路径，不增加资金依赖代码或任何运行权限。

追溯发现最后一次_client_binding之后仍有业务clock/local_view回调，而owners只核凭据等所有权，不再核完整原SDK摘要。先在真实SDK/fake底层运输的双venue×signal/原L1上注入最后时钟改options：4项DID NOT RAISE真实RED；最小末尾SDK复验后4 GREEN，再扩markets/public route晚变异。随后2项真实RED证明新增末尾SDK核验本身的耗时仍可漏出原instrument age。最终使用核心库monotonic_ns覆盖最后业务时钟/本地视图/SDK核验、原事务退出及终末owner的完整尾段，不再在原SDK比较后调用另一个业务时钟。

使用时刻上界为最后typed guard检查时刻加ceil(尾段单调纳秒差/1,000,000)。这是保守本地完成界，不是原生来源时间或服务器时钟；因包含重叠尾段可能比实际完成更晚而更早拒绝。正1ns向上计入1ms不提供额外预算/epsilon；非法或倒退单调采样拒绝，原age/span参数与来源字节不改。继续复用原_client_binding/local_view/完整ledger，不新增helper、订单状态机、金额规则、schema或外部依赖。

24新增回归：12项双venue×signal/原L1×options/markets/public-route末尾变异、2项末尾SDK耗时、4项整毫秒恰界/正1ns超界、6项bool/倒退单调钟。最后两组手工控制精确纳秒差，正常原factory/parser/SQLite及allowlisted GET路径仍实际执行；失败不改订单/引用、不释放unknown，cleanup仍限自有新SDK。14项SDK/耗时GREEN及10项计时边界GREEN之后，双解释器相同8模块各392 passed、0failure/error/skip、2既有小样本XGB警告（445.47s/467.88s），唯一用例集合一致；双版compileall/diff通过，详情/身份见台账。未变其余证据按原范围复用，不冒称全仓回归。

主线程按review模板核原边界、计时单位、失败与原模型/历史/恢复分流；全部fake、无独立代理审计、无真实交易所I/O或研究绩效读取。源码hash/选定callable核验仍非整个加载闭包/宿主真实性证明，当前initializer只返回None而非资金或HTTP许可。两个flags=false、v2 claim/默认资金拒绝及实际配置/权限/candidate等门禁全部保留；金融方向待确认，完整S3e/C5/C6/C7/Goal未完成。

## 31. 资金方向已批准；Binance精确原生参数输入子层（2026-10-24）

起点4d31915a39944df956665c3303ee8ed04d778fec已推送且clean。用户对专门资金问题明确答复“批准本地模型＋原生额度方向（推荐）”，已更新原设计稿而非重问；此批准没有给出隐含价格/费率/费用币/档位公式、实际资金或运行权限。工具原Goal仍blocked，本轮未伪造active、另建Goal或关闭完整C0–C7。

新增Trade/NativeCapacityEvidence.py及186测试，仅采集Binance/binanceusdm原参数。固定feeBurn→按完整声明池排序逐symbol commission/config/brackets；各项由原native账户身份GET前后包围，总原SDK调用数3×(1+3N)，超过128在I/O前拒绝。保留所有档位字段与可选notionalCoef/RPI缺失，不补0/1、不应用coef/返佣、不计算可用金额，fee_currency=None、两个flags=false。复用原私有环境、账户context、精确数值、声明池和SDK身份，无新金融/订单状态机、表/旧schema迁移或default集成。

本机CCXT Python JSON会丢小数token精度，故同次native返回后立即读取原保留HTTP正文，用标准库parse_float=str，拒绝重复键/NaN/过大正文/decoded不符，再发布白名单投影；完整正文/凭据/headers/账户原标识/错误不持久。collector核原native/选定sign/request/fetch/JSON函数owner、有效retry=0、全部私有路由/两项TLS开关及调用前后输入/credential/options摘要；不修改这些对象。reader重构严格shape/数值/顺序/SDK/源码和显式年龄/跨度，零GET零写入。终末client核验成本用与原冷初始化相同的monotonic纳秒向上界计入age，无新增容差。它不认证服务器或全部宿主，观察仍非原子；reader接受数据不是caller可转让准入权。

TDD缺API真实RED后实现；首轮92失败/162通过的重复失败均为testnet夹具错误预期：实际SDK4.5.89默认私有签名在fake session前NotSupported。追溯实际sign分支，不替换/关警告、不切demo或改实际配置；正向改为live离线fake，并明确两项testnet零运输拒绝。另10项真实RED为effective TLS开关/非法初始时钟仍尝试GET，补原检查前置后10 GREEN。收尾再以合法合成零时刻证明末尾bool时钟先加整数会变int：2项DID NOT RAISE RED；复用原_window先核typed时刻再加单调差后2 GREEN。最终186新用例还覆盖精确数字不可从float恢复、两币完整原档位、缺项/多行/重复/错symbol、负费率/optional缺失、全身份/输入/SDK/route变异、显式budget与终末耗时、脱敏/核心导入。

双解释器同六模块各903 passed、0failure/error/skip/0warnings，唯一集合完全一致（py314 53.62s/JUnit53.551s；py311 53.51s/JUnit53.455s）。组合为186新＋41账户身份＋166独立mark/book＋422instrument＋66balance＋22原prepare/source；双版compileall/diff通过，产物身份见台账。修复末尾typed时钟前两版901 PASS只是中间证据，未替换为新代码证据。不复跑未改原订单/模型/冷启动全组，也不将可复用旧证据记为新跑；没有真实HTTP、研究/正式绩效读取或实际Config/config.yaml/CHANPY_CONFIG变化。

主线程按review模板逐项审查范围/类型/失败/兼容与预算，未发现本输入子层未解决阻断；可提交此有限层，生产就绪=否。整个金额模型/独立非空持仓及partial/pending复算、跨来源时差、原受控prepare/CAS绑定、全加载闭包/执行reader/HTTP/default、OKX后续及C7仍未完成。新模块故意不纳入旧proof重封或赋权；原资金/claim/发送阻断全部保留，不能以903 PASS关闭S3e/C5/C6/C7或完整Goal。

## 32. 已提供book的精确保证金包络（2026-10-24，非完整资金判断）

从已推送clean的2d95f4665127a0115a2ba62b41f86153a06477ff继续，原Goal工具已active。上一轮为实际进展，不重做输入来源；本轮没有收缩C0–C7。检查官方保证金/成本/费用说明与原Engine、NativeAccountReconcile、pending/account解析后，新[算术规格](../specs/2026-10-24-binance-capacity-arithmetic.md)将可独立实施的book公式与需要明确选择的价格估计P/N分开。A方向已批准，不重问；P会放宽原生执行上界要求，单独请求确认，未回复不当作批准或编码FAQ系数。

新增NativeMarginEnvelope及79测试。只在提供的数据上，按signed position q×mark、所有残余普通LIMIT买/卖值的两个端点取max；hedge分别LONG/SHORT再相加，不先净额；另保留按mark的币数端点、逐symbol双腿暴露汇总，候选只为无native ID/ACK的数学投影。已有filled不重计、关闭方向/RO不凭空移除，不能以pending为空释放本地unknown。缺市场/模式/mark/config、币数张数不等、foreign保证金币/非cross配置/算法/复杂/未决MARKET及非有限/float/bool金额拒绝。这里的空提供列表只是算术空集，不证实实际账户空仓/缺单或原生账户模式已核。

复用ExecutionFacts数字、AccountReconcile._ratio、NativePendingOrders._order和原配置解释，没有第二个账本、订单状态机、DB/SDK写入或source/旧schema迁移。精确Fraction一直保留到统一序列化，不发明钱数舍入量子。GREEN56后按预写清理计划让同一个frame计算体产生每腿、每symbol和全书IM，删除第二份端点公式；新增字段有先RED保护。结果两个flags=false、provided_untrusted_reference、无可用额/费用/档位通过；不接原intent/claim或默认sender。

TDD：双symbol缺API2 RED→56 GREEN；缺symbol暴露汇总2 RED→58 GREEN；手算/顶点枚举、符号越界、非终止分数、source输入变异等77 GREEN后，收尾确认11与00011会重复计量，2项DID NOT RAISE RED→最小按symbol＋int(native ID)比较后79 GREEN，不改原raw/ID。手算one_way前2102/21、后4939/42；hedged四腿前6467/42、后3601/21；还有额外IM=0但仍无资金许可的相反候选。独立测试枚举挂单所有none/full成交顶点，与生产端点公式分开；不是独立代理/外部认证。

最终双解释器相同六模块各721 passed、1既有skip、0failure/error/0warnings；722唯一用例集合一致（py314 93.08s/JUnit92.994s，py311 91.29s/JUnit91.203s）。组成79新＋186原capacity输入＋52原账户区间＋251原pending来源＋95原pending归属＋59原账户组件；其中skip为Binance income无isolated position现金通道，不是新用例或缺费用跳过。修复数字ID前719+1只作中间证据。双版compileall/diff通过，完整产物/源码身份见台账；未改其余代码证据按原范围复用，不冒称全仓/全金额验收。

主线程按review模板检查数学/单位/符号、边界/去重、字段/兼容和门禁；此独立子层可提交，生产就绪仍否。候选价格没有被证明或批准，完整Loss/Fee/档位/余额、原受控自采及L0/L1/L2/全reader/HTTP/default、OKX与C7继续待；只依赖已提供数据的hash和包络，不能当作身份、freshness或新风险权。没有实际配置/权限/规则/候选/旧产物/研究数据变更、真实请求或正式绩效读取。Goal保持active，不因此关闭S3e/C5/C6/C7或完整Goal。

## 33. 所提供book与观察到的原生杠杆/名义限额（2026-10-24）

基线e189821266d8b77bf744e21bacb84a7089640241已推送且clean，原Goal实际active、完整C0–C7不变。P/N未获新的答复，未重复A/账户协议审批或实现估价依赖。先读原生账户check/current/准备与book代码及官方账户API，确认symbolConfig当前L/maxNotionalValue和bracket最大初始L/floor/cap的角色；notionalCoef是否已应用的语义仍未核，不能重复乘或忽略而放行。按[算术规格§4–5](../specs/2026-10-24-binance-capacity-arithmetic.md)实施一个必要限额子项，不把它改称完整金额或准入。

新增Trade/NativeLeverageLimits.py及169测试。声明池/配置只取原capacity文档，原reader在计算前后验证完整shape/SDK/源码/账户context/时间；复用原book从raw positions/pending/mark重算，不接caller的预封book、配置或额外市场。按返回顺序核档位1..N、首floor0、完整相邻区间及最大L不增加，不排序填洞。精确比较before/after每symbol的全腿暴露与native配置cap、当前L兼容档位cap两条约束；无兼容L用None+leverage_unsupported，不伪造0或无限额。保留非候选币/关闭方向/partial与hedge双腿，不跨币净额。

复用原Fraction/ratio/精确数字与_window，无新依赖/账户或订单状态机、DB/HTTP/配置写入。结果仅provided_book_against_observed_limits_only，book_origin_verified/economics_complete/native_admission_verified均false；源自身context/hash不证明caller提供的book真实属于它或当前全书。未计算费用/余额、维持保证金或coef，不赋权原intent/claim/default，不变更旧来源/订单/reader字节。该模块未被伪装纳入旧proof的新版授权闭包。

RED/GREEN证据：缺API4失败；36个完整档位/coef变异DID NOT RAISE；4个无兼容L仍输出数值0-cap；4个末尾序列化耗时未计年龄；20个正1ns/非法或倒退核心钟未拒绝；均先观察后修复。修复完整生命周期耗时不增加政策：typed业务时刻＋monotonic差向上整毫秒为保守使用时刻，计算前后原reader仍保留。最后169新全GREEN；手算TEST post one_way325、hedge275+201.5=476.5，与顶点枚举一致，两条cap均检恰界和1e-30两侧；五个L边界、非候选币已有超限、重封源/末尾输入变异明确覆盖。

最终CPython3.14.2/3.11.15同三模块各434 passed、0failure/error/skip/0warnings，434唯一classname/name集合差异0（57.14s/JUnit57.089s；56.91s/JUnit56.871s）。组成169新＋79原book＋186原capacity；原未变账户/归属/CAS等证据按原范围复用，不冒称本轮整组或全仓运行。双版compileall/diff通过；生产/测试SHA在双版间不变，34932/37384皆exit0后才改文档。完整JUnit/失败证据身份见开发台账，未清理或重标任何失败产物。

主线程依review模板串行核架构/字段/精确比较/边界/拒绝/兼容/门禁：该有限检查无未解决提交阻断，可提交但生产就绪=否；没有子代理独立审计或真实服务认证。仍必须接实际原account check/来源与全book、受控prepare/原CAS，完成明确价格依据、费用币/余额、全部执行reader/HTTP/default、OKX/S4/C7。整个S3e/C5/C6/C7和完整Goal未完成、保持active；未读正式研究绩效或访问真实账户/市场/订单，实际配置/权限/规则/候选/旧产物均不改。

## 34. 原持久check到限额book的只读适配（2026-10-24）

上一轮47d9f0c87c7b28336ff3bac94556e08a69280cf9已推送且HEAD/origin/远端一致、clean，属于实际进展，原Goal仍active。继续原完整C0–C7，不重问A/原CAS或未回复的P/N；本轮不引入新的价格/费用假设。先冻结[算术规格§6](../specs/2026-10-24-binance-capacity-arithmetic.md)并新增Trade/NativeAccountLimits.py与109测试，解决caller任意提供book的关联缺口，不将其替代原prepare自采/完整资金闭环。

原capacity reader校验后，由原CChanDB/连接/table捕获L0，原owned视图内用_sources_snapshot读取真实持久check并assert，计算后再assert同一L0。signed positionRisk/regular raw pending来自原check，mark来自独立market，模式来自原margin组件；声明池/SDK/当前L及配置精确匹配，不跨币/腿净额、不遗漏非候选币/关闭方向、不复制旧金融/时间公式。capacity整窗及finish端点加入原窗口函数的局部政策副本，使用同一total span/skew，不改旧policy/schema字节或补默认值；无GET/逻辑DB写入/新表/状态机/依赖。

TDD：缺API最初位于fixture setup产生4 error，移到行为入口后才记录4 fail/0error RED；首次组装4 fail源于漏接原NativeOrderBoundary合成钟，按systematic-debugging仅输出嵌套异常帧，定位原age核验后只修fixture时钟，未扩大预算/改产品reader。28个各自合法但配置/SDK/metadata/联合total或skew冲突反例真实DID NOT RAISE，补共享绑定/窗口后GREEN。收尾16个clock后input/owner/真实CAS变更RED；正1ns测试先曾被其他skew拒绝，明确隔离该规则、证明零成本baseline通过后重跑4个真实RED，不能将原4个伪GREEN冒充成本覆盖。

另8项source实现/内部clone漂移RED补末尾原reader和原/clone双向字节核验；再8项reader回调RED证明替换库已被BEGIN/PRAGMA触碰，入口先固定原owner，每次reader后先复用原_same_database才进入SQL视图，替换库完整trace为零。最后业务钟在最终L0复验前取得，核心monotonic向上整毫秒上界覆盖核算、核验与owned退出，非法/倒退/bool钟拒绝，不加epsilon/budget。真实新CAS意图使旧book拒绝，created/unknown状态不重置或释放；这只是反向并发证明，不是观察器执行下单或金额占用。

最终CPython3.14.2/3.11.15相同五模块各696 passed/0failure/error/skip/0warnings（240.63s/JUnit240.546；238.79s/JUnit238.709），696唯一classname/name集合差异0；组成109新＋169限额＋79book＋186capacity＋153原L0，非全仓/全部CAS或外部认证。双版compileall/diff通过，生产/测试SHA跨两版相同，活pytest17430/74660确认exit0后才更新文档；完整身份/所有RED产物见台账，未删除/重标失败证据。其他未变模块只复用其适用旧证据，不记为本轮重跑。

主线程依review模板审查原库/窗口/字节/单位/错误/兼容/门禁，无该有限适配的未解决提交阻断，生产就绪仍否。新capacity文档在reader测试中是新合成历史输入，不伪造SDK testnet采集成功、不改警告/路由；collector原SDK＋fake运输及testnet拒绝另有本次重跑的186组。book_bound_to_original_check=true仅指最终owned视图的原数据关联；source_collection_owned/book_origin_verified/economics_complete/native_admission_verified仍false，不承诺读视图释放后无新并发/服务器变化，也不是调用者可传递的准入权。

实际Engine自采/prepare身份、完整价格/费用币/余额、原L0/L1/L2金额消费、全reader/HTTP/default、OKX/S4/C7仍未完成；原常量资金/claim/发送阻断保持。无真实交易所/账户请求、实际配置/权限/规则/候选/旧证明/研究数据改动或绩效读取；完整Goal保持active，不以本关联通过关闭C5–C7。

## 35. 原prepare同次自采capacity并绑定原诊断CAS（2026-10-24）

基线56af5077266e1243cb74b6f7276ddfb4a678e74e已推送且clean，原完整C0–C7 Goal保持active。工作开始时P未回复，续行中用户专门批准“批准路线P：接受明确的V1价格假设”，现已记录于算术§2，不重问A或P/N。本批按[绑定规格](../specs/2026-10-24-native-capacity-prepare-binding.md)只补raw来源所有权，不先写alpha/费用估价、金额通过或交易权限。

NativePreparedIntent新增显式acquire_binance_capacity_prepared_diagnostic_intent，与原入口委托同一实现体；原v2路径无额外capacity GET。新v3在instrument之后、原components之前由同一实际SDK采feeBurn及逐symbol commission/config/brackets（两币21个SDK GET），原L0/原intent CAS内保存完整raw源和显式age/span。账户context、SDK/完整市场池/配置与原check/market严格匹配，capacity整窗和finish端点纳入同一total/skew。容量采集后的DB/client owner先于组件复核，替换库SQL trace为零；缺source不能悄悄退v2。没有新表/订单状态机/金融公式/默认费率。

只由原weak prepare context证明同次本地所有权，不接caller receipt/PASS/client/clock。历史decoder内部按immutable attempt.intent_ms验当时窗，公开capacity reader仍只在末尾取真实当前钟；原current/CAS和cold不能借as-of续期。原v1/v2历史保留、old入口不补cap字段，码/SDK时代不匹配仍拒绝。新source/相关helper进入原implementation闭包；全部实际request.price（含MARKET None）、数量/原契约和原行/ledger/journal/CAS唯一增量保留，输出仍为不可执行native-cas-order-v1/transition-v2，claim/default继续拒绝。

收尾TDD还证明source reader末尾业务钟会留下client漂移缺口：在v3 measured尾段复用原caller完整检查后才采monotonic上界；原current两个local重建体提为一份闭包，前两次行为不变、v3尾段第三次复用，prepare/CAS复用原weak recheck及_current。正1ns向上整毫秒，typed/倒退钟拒绝；不加预算、epsilon或末尾业务clock。历史as-of与实际current用两条明确调用路径，不将readonly decoder返回值当资金权。

TDD证据包括8缺API、4历史过期、1current decoder耗时、2owner/替换库、1缺结果降级、5成本/非法钟、2末尾SDK等真实RED，均观察后最小修复。最初12个fixture setup error不是行为RED；MARKET缺fake ticker handler和cold warm cache的private_unused差异只按异常帧定位夹具。cold正向在绑定前由原初始化建立allowlisted SDK，绑定后不能删额外字段来重建；该拒绝另有保留用例，未忽略字段或改旧证明。

最终CPython3.14.2/3.11.15及CCXT4.5.89相同15模块各2059 passed、0failure/error/skip、3既有小样本XGB AUC警告（1680.11s/JUnit1679.813；1736.70s/JUnit1736.358）。2059唯一用例集合差异0，7个相关源码/测试SHA跨两版不变，双版compileall/diff通过；原句柄92841/33870均exit0、目标pytest进程数0后才写结果文档。85新增含4个原v2无额外GET回归、新v3四种模式/方向与LIMIT/MARKET、非空两币partial/费用/资金费、原SQLite CAS/引用回滚、重启/current/cold、源/配置/原行/SDK/owner/时钟/重封反例。完整模块/失败/产物身份见台账；不冒称全仓、独立代理审计或外部认证。

主线程依review模板核职责/旧兼容/源码与SDK闭包、原owner/nonce/行/完整账本、最终时间、错误脱敏与权限：raw有限子项可提交，生产就绪仍否。实际HTTP全部在底层fake session，live-mode仅隔离对象/临时配置/fake environ；默认SDK Futures testnet签名拒绝、candidate/testnet/live门禁不变。SDK调用路径及本地hash不是服务器签名认证、原子快照、锁额或必接单。没有真实账户/行情/订单、实际配置/规则/权限/candidate/旧产物或研究数据变更及正式绩效读取。

原参数自采现在已与实际prepare/原诊断CAS关联，但完整V1成本、fresh Last/费用币依据、余额与独立金额复算、原L1/L2金额消费、全执行reader/HTTP/default、OKX/S4/C7仍待；经济/admission flags仍false。本次P批准解除的是具名估价选择，不是上述验收或真实运行门禁。下一步整合完整资金路径，不以更多独立diagnostic替代它；完整S3e/C5/C6/C7与原Goal继续未完成、active。
