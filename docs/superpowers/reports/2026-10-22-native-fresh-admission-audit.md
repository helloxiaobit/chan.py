# 原生 fresh-admission：现状审计与已批实现方向

状态：**严格方向已获用户明确批准（2026-10-22）；实现/验收未完成，不是交易收据或生产授权。**

批准记录：用户对“独立原生 mark/book 与公共路由证据、显式年龄/观测跨度、金额零默认容差、原账户/账本及原 CAS 每单复验；仅 fake、保留全部门禁、不改实际配置”的确认问题答复“批准严格方案（推荐）”。
下文保留最初审计及建议的历史语境；不再将本方向视为待批。具体串行实施见 [原生准入实施计划](../plans/2026-10-22-native-fresh-admission.md)。候选换代设计仍单独待批；没有真实 I/O、配置/权限修改、自动解冻或实盘授权。

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
