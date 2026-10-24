# 原生 fresh-admission 串行实施计划

日期：2026-10-22（Asia/Shanghai）。用户已明确批准严格方向；无需重复询问执行模式。
主计划仍是 [虚拟货币完整版 C0–C7](2026-10-20-crypto-full-version-completion.md)，本计划不缩减其完成条件。
依据：[原生准入审计](../reports/2026-10-22-native-fresh-admission-audit.md)。起始代码为 full-version `134b4d7ebd92b67bc64534d9fdf0b0d5040eaeb1`。

## 边界和复用/清理计划

- 单线程/串行、真实 RED→最小 GREEN、主线程审查及 Lore/快进推送；活测试期间不改文件。
- 只用合成 market/raw/account/SQLite 与 fake SDK 传输；禁止实际行情/账户/订单请求、用户配置/权限/规则变更、新依赖、正式研究和绩效读取。
- 复用 `ExecutionFacts._market/_number/_time/_string/_MONEY`、finite canonical、原账户环境校验、C4 账本和原意图/CAS。不得改旧 v1/v2/v3 证明字节或另建撮合/金融/订单状态机。
- 先新增独立版本来源；只在完整消费者/每单路径证明后有条件替换运行壳常量阻断。观察本身始终 `native_admission_verified=false`；历史 matched、无冻结、调用者布尔值或自封 SHA 不构成新准入。
- 用户批准不包含候选换代/重新武装、默认年龄/金额容差、人工解冻、真实测试网/实盘或 C7 认证。

## S1 独立原生市场来源（已实现，限离线来源层）

文件：新增 `Trade/NativeMarketEvidence.py`、`tests/test_native_market_evidence.py`，文档/台账；不接发送路径、不动实际配置。

1. `collect_native_market_evidence(exchange, markets, *, mode)`：读 Binance premiumIndex/bookTicker 或 OKX public mark-price/market books；每个显式市场各两次 GET，无重试/降级，不借用 ticker/软件报价。输入沿原 `_market_contract` 完整定义（8 个单位身份字段及 precision_mode/precision/limits），不丢弃执行 metadata；上界复用原 128 次来源请求预算，超量整批拒绝而非截市场。
2. 只保存 allowlisted raw 字段，市场完整 metadata、查询参数/固定端点、每请求及全批本地起止、独立原生时钟、公共环境与 SDK/源码身份。OKX books 不回显 instrument 时保留 request-only 绑定，不发明响应字段。
3. 公共环境在每次 GET 前后核对参考客户端；Binance 检查 fapiPublic，OKX 检查共用 rest/hostname/模拟 header，复用既有 TLS/private-environment 校验但不修改旧 context。SDK 是客户端身份证据，不是服务端签名。
4. Binance book 数量为 base，OKX swap book 数量为 contracts；用原精确 Decimal 边界同时保留两单位。mark 的原生 time、OKX REST mark 的 data-return time、book generation/transaction time 各自命名；不把 local finished 当来源时间。
5. `verify_native_market_evidence(receipt)`：有限 canonical/SHA、精确 shape、raw→derived 重算、请求/市场覆盖/顺序/时钟/单位/版本核验。保留完整 allowlisted 内容和窗口取 ID，不按时间戳去重。空/交叉/零量 book 可保留观察，但 tradeable=false，绝不生成准入。
6. 验收：两 venue、binanceusdm、live/testnet 标签的 fake transport；两市场/不同 contractSize；原始/派生/重封篡改、路由/hostname/TLS/header 前后漂移、错单位/标的/响应、缺/重复市场、非有限/未来/倒退时间、异常脱敏、无重试、可选依赖核心导入。逐步 RED，适用双解释器回归及精确提交核验。

实施证据：两解释器各 166 来源用例、734 pass/1 既有 isolated 通道 skip 的适用组合，详见台账。请求上界计显式 SDK 方法调用，不声称控制 SDK 内部 HTTP 重试。stored reader 只校验自洽性/当前边界代码，不认证来源真实性或当前客户端；这些必须由 S2/S3 的实际采集/每单使用路径绑定，而非信任外部传入收据。

## S2 当前使用政策与原账户/账本关联

文件：新增 `Trade/NativeAdmission.py` 及对应测试；最小扩展原 AccountSources/Store/Reconcile/RiskStore 与 OpeningInputs。

- 部署显式给每来源 max-age、账户及全批 max-observation-span、跨来源 max-skew；没有隐含数字，不借 ticker 的年龄，不把账户 mutation 时间当新鲜快照时间。字段规格在本步 TDD 前固定；零金额/数量默认容差，不发明 FX/舍入修正。
- 关联同 typed account/mode、原 DB 全 trade-shaped 历史、snapshots/wallet/executions、独立 mark/book 和全部实际持仓，不只核候选/空仓/单币。缺腿、unsupported 或来源不全 fail closed，已有冻结继续 sticky。
- 先明确原生未决单/余额预占与本地 reservation 归属协议；缺证明不能当可用，unknown 不清空。完整账户公式仍沿原 C4/对账组件，原 economics_complete=false 不升级。
- 测试边界包含每一来源年龄/跨度/时差、全部市场/持仓、确切金融差异和原历史/配置/DB 身份 mutation；consumer 未完整时仍无 admission=true。

### S2a 政策与账户/市场来源使用断言（已实现，完整 S2 未完成）

- 新增 `Trade/NativeAdmission.py` 与 `tests/test_native_admission_freshness.py`，先不接发送路径、DB 表或运行配置；复用原 AccountSources/AccountIdentity/NativeMarketEvidence，不扩展旧收据字段，也不复制财务公式。
- 政策 schema `chan-native-freshness-policy-v1`：精确字段 `schema`、`max_age_ms`、`max_observation_span_ms`、`max_source_skew_ms`。年龄键精确为 account/mark/book/wallet/execution/open_orders；跨度键精确为 account/market/wallet/execution/open_orders/total。所有值显式非负 int 毫秒（不接受 bool/float/string，0 是显式的严格零，不是默认）。缺任何角色或多余别名一律拒绝；没有 ticker 年龄、全局配置或隐含秒数回退。此政策没有金额容差旋钮。
- `read_native_freshness_policy` 只验证/复制全部显式字段；没有批准或更新用户实际配置。
- `assert_native_account_market_freshness` 只核给定账户/市场观察的身份、完整市场池与当前客户端、年龄/跨度/时差；成功返回 None，不生成 receipt/ready/admission=true。wallet/execution/open_orders/全账本/reservations 尚未纳入此断言，不能把其未检查的角色解释成通过。完整 S2 仍须实际采集和完整消费者。
- 账户年龄以整段采集开始计至本次使用完成，不能用较晚 finished 掩盖最早读取；mark/book 同时检查原来源时间与各自请求开始时间。account/market 自身跨度分别为 finished-started，total 则为本次使用完成时刻减本组最早 started（包含身份读取及等待，不在最后一次来源 GET 就提前截断）。时差是来源提供的 Unix 时钟与账户观察开始的最大 spread，不宣称它们是相同生成时钟或全局原子快照；原 position/asset mutation 时间不作新鲜度替代。
- 原账户快照仍 raw 重算且 context 与当前 profile 相同；完整执行 metadata 与当前显式 market pool/S1 原观察精确相等，账户中的实际/unsupported 持仓不得靠删市场隐藏。当前公共路由与 SDK/源码身份必须匹配原观察；检查前后时钟、账户环境/公共环境漂移均拒绝。不重发/改写来源、不缓存旧结果。
- 先政策缺函数/字段 RED，再用真实旧账户/S1 collectors＋最底层 fake 两 venue/模式/多市场用例观察断言缺函数 RED；补年龄/跨度/时差恰等/超 1ms、缺市场/单位/metadata/context/route/SDK/旧源篡改回归。最终双解释器、原账户/订单门禁适用回归、Lore/精确提交/推送。全账户金融/未决预占/原 CAS 尚未通过前，常量阻断保持不变。

实现说明：本次输入先固定完整 canonical 字节、复制校验，最终再次核原输入字节；最终序列化/核验完成后才读使用时刻，不把 CPU 核验耗时漏在预算外。以两次当前 profile 与前后公共环境/SDK 检查包围绑定核验，仍不是服务器原子证明；调用者必须保证 GET 位于 DB 写锁外，helper 无法检查其外部事务。实际 149 新用例、两版适用组合各 886 pass/1 既有 isolated 通道 skip，详见台账。

下一依赖仍是 S2b：原 wallet/execution 的观察窗口与覆盖、全 trade-shaped 历史/持久冻结及当前账户经济闭合、原生未决单/预占归属；不得把 S2a 的 None 或完整政策格式代替这些证据。之后才是 S3 原 CAS 每单消费与 S4 默认入口 E2E。

### S2b1 原持久区间来源的使用检查（已实现，限 DB-only 子边界）

- 在原 NativeAdmission 内新增 `assert_native_persisted_interval(chan, *, account_context, check_id, market_evidence, policy)`，只接受原持久 check ID，不接受 caller 的 passed/report 或换写 source IDs。成功仍返回 None，不发布新证明，也不写冻结/订单/账本；完整失败发布继续由原 reconcile_account 负责，不能将此 helper 作为完整消费者接入。
- 复用 AccountRiskStore.read_check/risk_state/_ledger 和 ExecutionStore.read_scan_with_account；沿原 SQLite transaction/savepoint，在同一个 DB 视图核原报告 raw 重算、原来源/完整历史、当前所有 trade-shaped 表及 sticky freeze。原报告必须 matched_observations；当前整份 histories/projections 与所选原 check 不同就失效，不能靠旧 PASS 覆盖后来变更。其他账户活动可能使该全 DB 证明失效，需要重新对账，不自动排除未知归属。
- 账户当前点为 after；before 是已验证历史锚点，不把其历史年龄、扫描历史 start/end 或 DB 导入 observed_ms 当成当前来源时钟。wallet 年龄/跨度取原 receipt.started/finished，execution 取原 manifest.native_account.started/finished，缺 native observation 不回填。两种扫描仍须按原报告覆盖完整 [before.started, after.finished+1) 及所有市场，不能只核候选。
- 当前 after/market/wallet/execution 的年龄、自身跨度、联合使用跨度及来源时差使用同一显式政策；mark/book 同时核原 native 时钟和请求开始。原持仓非零时，其 after mark 与独立 mark 要精确相等，不提供容差或修改原 mark_ms=None。环境共用字段、venue/mode/完整市场单位保持原身份；实际当前 SDK/profile 仍由锁外 S2a 与未来每单消费核验，此 DB-only 检查绝不做网络。
- 清理/复用计划：把 S2a 已有纯时间/盘口使用检查最小提取为私有 helper，S2a 明确传空 wallet/execution（不宣称检查它们），S2b1 必须传原 check 中完整扫描；不复制 raw/金融公式、不改旧 schema/字段/交易或失败发布语义。149 项现有使用回归保护非行为提取，新增 DB-only 阶段先缺函数 RED。
- 用原真实 collectors、原订单状态机和 SQLite 构造两币非空仓位（contractSize .01/.1、单双向），扫描事实区间无新增交易但覆盖真实历史锚点；并验证源窗口缺失/原生观察缺失、DB 导入不能刷新年龄、当前表/历史/跨连接冻结、重启、嵌套事务、零行写入、核心无 SDK及原门禁。原金融 v1 对未决单的 incomplete 保持不变；原生未决单/预占及新消费者还未完成，不能把本步骤包装成它们通过。
- 补充当前性回归：TTL 内旧检查也不能覆盖同一稳定原生账户已持久保存的更新 snapshot；更新来源即使尚未组成 report 也要失效旧检查。同一 finished 时刻存在不同完整 snapshot 字节时拒绝歧义，不按 SHA 或导入顺序择优；不自动选择/批准最新检查。沿原 AccountStore reader 校验完整行后再按原 account_key 关联，不能只筛可能被篡改的索引。更晚/同钟证据的测试沿实际 collectors/store/reconcile，未变经济值也不能续用旧 current 点。
- 测试复用计划：最小提取已有 fixture 的执行/钱包真实采集管线用于第二段区间，原用例继续保护；为父/子测试进程显式注入无文件的 CEnv 路径环境，避免旧 CChanDB 构造器尝试默认 YAML，不修改原构造器或任何实际配置，也不放宽无 SDK/可选依赖的断言。

实施证据：原缺函数 RED→最小实现；两项真实事务释放延时 RED→将最终时间/字节检查移到所拥有的 transaction/savepoint 退出后。随后 8 项真实 RED 证明 TTL 内新 snapshot（含未组成报告者）、同 finished 时刻的不同 snapshot 及受损索引不能被旧检查忽略，补原 AccountStore reader 的完整校验后 GREEN。新增 56 项＋149 原政策/使用项共 205 passed；CPython 3.14.2 / 3.11.15 的扩展适用组合各 1103 passed / 1 既有 isolated 通道 skip，详见台账。不声称全仓重跑或独立审核。后续仍须原生未决单/预占、完整当前金融消费者、原 CAS/HTTP 与默认入口，不能围绕此无未决成交的区间 fixture 缩减主计划。

### S2b2 未决原生单、归属与余额预占（实施顺序；尚未完成）

- 先新增独立 `Trade/NativePendingOrders.py` / 对应测试，不能扩展旧 AccountSources v1 的 allowlist 并重封旧快照。使用原 `_markets`/`_market`/严格 Decimal、typed account profile 和原环境守卫；不复制订单或金融状态机。旧来源、原报告 unresolved_attempt/incomplete、CAS 与 runtime 常量阻断均保留。
- 第一依赖为有明确覆盖范围的原生未决观察：Binance fapi 普通单与独立 conditional algo 两通道，不传 symbol/algoId 等缩小范围的过滤；OKX 普通 pending 加 conditional/oco/chase/trigger/move_order_stop/iceberg/twap/smart_iceberg 八种 algo 通道，不传 instType/instId/instFamily 或 state 过滤。OKX 按原 native ordId/algoId 逐页 after、limit=100，到短页才闭合；严格拒绝游标不前进/跨页重复/错类型/失败响应，不以时间截断或统一 CCXT 列表代替原分页。
- 每页保留请求、允许的原字段、原订单修改时间和完整本地采集窗口；修改时间不是鲜活性时间，不发明全列表 server timestamp。每页原 typed profile 前后相同、路由/TLS/SDK/客户端身份稳定才发布。最多沿原 128 次显式 SDK 调用预算，profile 读取也计入；预算耗尽整批拒绝，无重试、自动降级或部分 PASS。SDK 内部 HTTP 重试仍未认证。
- 原字段按完整允许形状保存，含附件/父子单 ID、触发/数量/reduceOnly/方向/持仓腿与交易类型；额外私密 free-text 不回显。各声明通道返回的所有行均保留，不因不在候选池而丢弃。已知 regular 市场沿原 contractSize 精确保留 native/base/contracts 三单位和剩余量；未知市场、非 SWAP、algo 的条件数量/closeFraction 不猜单位、填零或据此放行。算法单留作未证归属来源，不冒称已有普通单状态机能执行/管理它。
- 来源 schema 只描述所列 fapi / OKX trade 通道：`economics_complete=false`、`native_admission_verified=false`，不能声称服务器签名、全账户原子不存在证明、其他 bot/copy/子账户/组合保证金通道或余额预占已覆盖。已知未覆盖项目要显式披露，不能将 empty 普通单转换为完整账户 ready；后续完整消费者仍必须处理其适用性，主目标不因来源层通过而缩小。
- 后续依赖：在原同一 SQLite 视图按 typed account、原 intent/contract/server/client ID、phase、原累计成交、剩余量、方向/腿/执行设置核对真实未决来源和所有 trade-shaped 本地 reservation；unknown/claimed 不能当未发送或释放。原 v1 快照未保留完整 native 预占分项，需独立版本的原生经济观察和原公式复用，不用零补齐或自行加减 USD/USDT。只有完整当前金融闭合与后续 S3/S4 通过，才考虑替换新风险常量阻断。
- 本步只用无凭据真实 SDK 类和 fake 最底层 native 运输。先缺函数断言 RED，再两 venue/模式、多市场不同 contractSize、非空 regular/partial/algo/外国市场、原分页/路由/预算/脱敏/重封变异与无 SDK reader；实际网络、用户配置/权限/依赖、研究输出不在范围。

接口依据（仅技术文档，不是实际端点验收）：[Binance fapi Trade](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)、[OKX native order/algo list](https://my.okx.com/docs-v5/en/)。本机 CCXT 4.5.89 确认普通与算法列表是不同 raw 方法；其 unified fetch_open_orders 默认不会同时证明两类覆盖。

来源层已完成离线实现：新增 251 项通过，CPython 3.14.2 / 3.11.15 的来源/账户/原鲜活性组合各 779 passed。Binance 普通和算法 ID 都按 symbol 自增，重复检测使用通道类型＋symbol＋ID；不同市场同号保留，同市场重复拒绝。原生类别、必需时钟、部分成交状态/累计量及 bool/模式字段矛盾不发布。详见台账；此阶段没有未决归属、余额预占或准入消费者，S2b2 整体仍未完成。

归属实施接口：新增 DB-only `observe_native_pending_ownership(chan, *, pending_orders)`，沿原 transaction/savepoint 和 AccountRiskStore._ledger 读取所有 trade-shaped 表/完整 attempt/events；不接受调用者提供 histories/owned 标志，不写订单/ACK 或释放 reservation。复用 ExecutionReconcile 的原契约/账户/市场/side/leg/请求量归属检查，再核本次原始订单 created_ms、完整 server/client ID、普通类型/限价/post-only、原累计成交、reduce-only 与模式。缺 ACK/created/submitting/unknown 不因列表出现/消失就修复；每个本地非终态保留原 requested-minus-filled 双单位和是否真实匹配，孤儿/复杂单、缺原历史、跨市场/环境/账户歧义均显式记录。这里的 reservation 仅是原意图未成交数量，不虚构交易所冻结金额；新 native 经济观察和完整消费者仍是后续依赖。成功报告仍两个 flags=false，无开仓授权。先用原 fake 订单引擎/SQLite、多市场 partial/close/restart 与原 native collector 的非空夹具 RED，再实现；不复制 financial engine 或修改原状态机。

归属层离线实现已落地：仅可证明的不同 stable account 排除；同账户/市场多个原 server ID 候选拒绝歧义，不能靠 client ID 选优。原 CCCXTTradeEngine 的纯执行设置/限额检查直接复用，单位与 requested/contractSize 精确核验；post-only/market 原条款独立匹配。读取来源期间输入变化、历史投影篡改、事件时钟倒退或晚于本次来源 finished 均拒绝。原报告不表示最新或来源真实，未来消费者仍须自己采集、检查年龄与范围并在原 CAS 内重读。native_margin_amount=None 不是零，未查资金余额/原生 margin 字段，S2b2 整体仍未完成。

下一来源接口为独立 `Trade/NativeBalanceReservations.py`：`collect_native_balance_reservations(exchange, *, mode)` / `verify_native_balance_reservations(document)`。固定三段 configuration_before → balance → configuration_after；Binance 使用 accountConfig 和 V3 account，OKX 使用 account/config 和 account/balance，均不传币种/标的过滤。每段包围原 typed profile、路由/TLS/SDK/客户端身份，记录完整本地窗口，计入原 128 次显式调用预算；无重试。两次允许的配置必须相同，不能把中途模式变更混为同账户快照。

新 schema 原样保留原生账户/各币种的余额、可用、position/open-order initial margin、冻结额、iso/借贷/策略/copy 等允许原字段；USD 总额和币种金额分别命名，不换汇、不分摊到每个订单。空/缺省原字段以 None 保留，绝不补 0；已有数值必须沿原 Decimal finite 边界。Binance config.updateTime 为上游保留字段，不当来源时钟；balance/asset mutation 时钟也不冒称快照/mark 生成时刻。原 AccountSources/收据和金融公式不变；新来源两个 flags=false，不做 DB 写入。后续完整消费者必须结合原 positions、wallet/executions、归属和余额预占闭合，不以来源层子集代替主目标。

技术依据（仅文档/SDK 方法核验、无实际 API）：[Binance Account/Config/V3](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)、[OKX balance/config](https://my.okx.com/docs-v5/en/)。先明确缺 API RED，再 fake 传输核非零挂单保证金、两币种和单双向/环境、遗漏/空字段、原币/USD 区分、模式/路由/账户漂移、原字节重封/派生变异及核心无 SDK reader；之后才做新金融消费者。

余额来源层已实现并离线验证：66 项；两版适用组合各 940 passed。存储 reader 逐段重算 raw/派生、窗口、固定请求与计数、当前代码和身份形状，不加载 SDK，也不认证原始来源。显式 OKX configuration 的 UID 在采集当时另核与当前 typed account 相等，观察仅保存 identifier SHA；不能只核周围 profile 而忽略配置响应自己的 UID。旧来源/金融/订单/CAS/配置未改。当前金融消费者仍未完成，不能把“已观察原生预占字段”改称“已完成预占/可用资金闭合”。

### S2b3 原金融核算复用与非空未决单观察闭合（实施中）

清理/复用计划：只在 AccountReconcile 的共享纯核算体增加内部 pending 分支，默认 v1 输入/输出字节和 unresolved_attempt 语义不变；新公开 builder 必须自行验证原始 pending 来源并从同一 histories/projections 重建归属，不能接受 caller 的 matched/qualified 集合或过滤旧 report 的 issue 后假装通过。新路径使用独立 v2 schema 和 pending 身份入摘要，其余钱包链、费用/PnL、funding、pooled entry、native mark 与 DB/current_qty 仍共用原实现，不写第二套金融/订单状态机。现有 v1 回归是行为清理保护；新非空 pending 行为先 RED。

新增 DB-only NativeAccountReconcile.observe_native_account_components：按原 before/after/wallet/execution IDs 重读原来源、同视图全 trade-shaped ledger 和 sticky freeze，验证新 balance/pending 原字节，再合并 pending-aware 区间和 native 组件问题。两份新观察须先于最终 after snapshot；其各币现金/未实现/权益/原可用及 margin 公共字段、账户和全部市场/实际腿须与 after 对应。Binance single-asset cross 的 total/asset 原 IMR position/open 分项精确对齐；OKX 只使用明确币种的 native availEq/ordFrozen 等字段，不用 USD 总额换算，不假设 imr 已排除挂单而再扣一次。只检验声明组件和原核算恒等关系，不估算交易所 tier/逐单冻结额或引入金额容差。

报告仍两个 flags=false，matched_components 只是所给观察的经济一致性，不能携带授权、忽略年龄或绕过原 CAS；失败持久发布/新来源存储与完整当前消费是后续明确依赖，禁止借本步删除常量阻断。测试沿原 collector/store/真实 fake 原订单流：非空仓位、区间实际部分平仓、费用/已实现/资金费和非零普通未决单；新增双市场/双腿、源缺失/变异/跨账户、原冻结/跨表与嵌套事务、重启、无 SDK/无写入及 v1 不变检查。全部 fake、串行、无配置/依赖修改。

本子边界已实现观察闭合，完整 S2 仍未完成。59 个新用例覆盖两 venue × 两模式 × 多空的双币原流水；同记录开单未终结时原 CAS 不允许取得平仓意图，故使用原合法顺序：TEST 已部分平仓，ALT 有实际部分开仓未决单，不放宽原状态机。新路径按账户＋市场限定历史 server ID 唯一性；即使零成交撤销也不能最佳匹配，Binance 跨市场同号保留。独立 balance 中的 account position/公共 raw 金额须与最终 after 相容，早期 availEq/cross 值不得覆盖新终点；未知/非 USDT 保证金和来源通道缺口仍 incomplete。

可用额只使用原币 native 字段并检查覆盖约束，不反算交易所 tier/逐单保证金，不把 OKX ordFrozen 再从可能已含其的 imr 扣一遍；原生更低可用额照实保留。新来源和当前组件报告尚未写入新持久 check，不能借旧 v1 matched check 为此路径发放准入；下一步应将新来源版本化持久保存、复用原 append-only check/sticky freeze 做失败发布和重建，再合并显式当前来源政策、独立 mark/book 和原 CAS/HTTP。新金融模块/共享 v2 的源码身份必须在 S3 明确绑定，旧 workflow SHA 不包含它们。

### S2b4 新来源版本化保存与原冻结发布（实施中）

先独立保存 native pending/balance 观察，不拓宽 AccountStore 的旧 kind/schema，也不重封旧证据。新增 append-only 原生观察表，单份 ID 为完整 canonical document SHA；读取重新验证来源 raw→derived、代码/账户/窗口与全部索引字段。ID 读取与账户列举使用同一 SQLite view；列举先验证所有行再按 stable native account 筛选，禁止损坏索引隐藏较新来源。初始化须沿原 SQLite 原子 schema/保留表名检查；外来同名表不采用，失败回滚，不改旧历史。公开接口只显式存取已采集字节，事务内不采集或加载 SDK，不写订单/ACK/PASS/冻结。

行为边界先以两 venue/两 source 的 RED→GREEN 保护：原字节重启/幂等、UPDATE/DELETE/REPLACE 拒绝、篡改 raw/derived/metadata 拒绝、失败零写入、外层 savepoint 所有权、reader 无 SDK/实际配置。旧 AccountStore/风险检查/订单回归复用并补跑受影响范围。其后再复用原 append-only check/sticky freeze 发布新组件检查：历史输入按原 journal prefix 证明，不能用现时 ledger 伪造旧结果，matched 永不抹掉旧失败；纯组件重建须避免 risk_state 递归。完整 freshness/current-client/mark/book、CAS 与源码绑定仍是后续依赖，不得由 source store 隐式放行。

来源存储子层已实现：NativeAccountStore 复用旧 canonical codec、账户 stable key、schema validation 和 SQLite transaction/savepoint；新增表及保留名纳入原原子初始化，旧表 SQL/字节不变。85 个新测试、CPython 3.14.2/3.11.15 广组合各 1519 passed / 1 既有 skip，全部串行且活测试不编辑文件。显式接入仅三项存取接口，无隐式采集、SDK/config 读取、金融重算或新风险授权；check 发布/重建及 sticky failure 接入尚未完成。

原检查发布/重建子层也已实现：NativeAccountCheck 从六类持久 source IDs 和同一视图全 ledger 加原 journal 前缀生成 `chan-native-account-check-v1`，复用原 `chanpy_account_checks` schema/append-only publisher 和 stable-key sticky freeze，不新建冻结/订单状态机。NativeAccountReconcile 抽出纯共享核验体，原 DB-only observer 仍额外返回当时 sticky freeze；历史重建不调用 risk_state，避免递归，也不让后来金融匹配清除旧失败。新 wrapper 的 matched_observations 只映射 matched_components 历史观察，两个 flags=false，不能升为 native admission。

前缀以原显式 INTEGER PRIMARY KEY event_id 固定并摘要覆盖其全部 attempt/event 原行，再与保存 histories 的全部 key/事件数量及原 prefix bytes 校验；不使用可被 SQLite 压缩重排的隐含 rowid，不从当前可变 projection 重建过去，也不能删掉零成交终态尝试后重算一个匹配 report 就过关。来源错误固定 failure 发布；发布/schema 失败则拒绝/回滚，不写新订单。37 项新测试、两版各 1662 pass/1 既有 skip/6 小样本模型警告，含旧部署契约/工作流/persistent paper；两 venue/模式/方向、原 v1 失败共存、跨连接 claim→HTTP 冻结与原减仓、无 SDK 重启均验证。此步完成来源存储和历史失败机制，不等于完整 S2；下一步为新 pending/balance 的显式年龄/跨度/当前来源与现客户端、独立 mark/book/完整市场池关联，再接原 CAS/HTTP、默认入口与新源码身份。旧部署指纹含 db_util/SqliteDB，但不含所有新增 native 模块，不能借旧 receipt 自动重封或重新武装。

### S2b5 完整组件来源的当前使用断言（实施中）

新政策 `chan-native-component-freshness-policy-v1` 保留原显式 age/span/skew 字段并为 age/span 各新增必填 balance 角色；旧政策/schema/默认值不改，不将 account 的预算暗用为 balance。纯读/断言接口不返回 proof/ready/admission，不写账户检查或订单，collector-owned 与原 CAS 消费仍是后续必要边界。

复用/清理计划：把 NativeAdmission 原 DB 当前区间核验体提为共用内部函数，旧 public 入口保留同样验证与 None 结果，原 56 项适用回归保护。原 use-time helper 仅增加可选的额外窗口角色，旧默认路径不变；新模块复用其 account/mark/book/wallet/execution 窗口并纳入 open_orders/balance，完成时间包含 DB 退出和 private profile 的全部耗时，不用 update/mutation 时钟或后来的导入时间刷新 source。

新断言先读匹配的 native check/原全 ledger、sticky freeze、最新已知 snapshot/wallet/execution/pending/balance 与完整市场/mark 绑定，在 SQLite 事务外复查当前 typed account/public route/SDK/市场定义，再重读相同 DB 当前状态。新版源与市场 SDK 身份须对应；任何较新或同 finished 不同字节的未整合来源、跨账户/模式、缺域、账本变化、原冻结、全组 skew/age/span 超界都拒绝。禁止在调用者已有事务内发 private I/O。来源原字节与输入包最终再验，金额无容差、未知不填零。

先真实缺 API RED，再用原 collectors＋双币实际部分成交/未决 ledger、原持久 check/独立 mark/book 的两 venue/模式/方向夹具，测试各角色精确边界/超 1ms、来源 mutation、latest 源索引、当前 client/路由/SDK、profile 期间其他连接写入、DB 退出耗时与输入变化。此步不把外部传入自洽 receipt 当采集权或订单能力；旧候选/全部交易 gates/常量阻断不变。

此只读子层已实现，107 新用例、两版适用组合各 1663 passed/1 既有 skipped，源年龄/跨度/全组 skew 含新 pending/balance 和最终 DB 退出耗时；正向是两币非空持仓/实际部分假成交/非零未决保证金，不缩成空仓证明。原 DB 当前区间体抽为 _current_interval_snapshot 供两入口复用；原 policy/public API 不改返回值或拓宽字段，金额核算仍为原共享实现。源码/环境/原字节异常脱敏拒绝，无 SDK/配置的子进程可单独导入/读新政策。

latest 检查会验证全部元数据后才按 stable account/角色过滤；新或同 clock 不同字节的 snapshot/wallet/execution/pending/balance 未整合即拒绝，不按 SHA 排名。执行收据的相同事实/相同查询窗口重导入仍是同一 ID，保留首次原账户窗口，不能刷新年龄；新查询窗口才形成可被识别的新观察。只读断言仍不是来源真实性、exchange 服务器原子快照、当前真实 instrument metadata 或交易授权；原 C4/economics_complete=false 不被提升。下一依赖为固定顺序的 collector-owned 来源采集/失败发布，与原每单 market/intent/CAS/HTTP 路径直接绑定，禁止从 caller receipt/None 推导 native_admission_verified=true。

S2b5 推送前复核纠正：latest 时钟不代表事实完整。新增真实 8 RED/4 positive，证明旧的已知 wallet/execution 包含区间内或终点后的额外零净额事实时必须拒绝，不能只因其观察时间较早便忽略；基线前事实则不误拒绝。只增加一个共用 canonical fact coverage 检查，不重算净额或改原资金/存储引擎。现 119 新用例，最终关键组合两版各 361 passed，其余未变代码沿用先前广组合；12ab104 与纠正提交验证后一起推送，不把初版 107 项或给定观察的匹配冒称完整准入。

### S2b6 固定顺序自采与原失败发布（已实现，限本地诊断子层）

新增 NativeComponentCollector，仅接收原 CChanDB、实际 SDK client、完整声明市场、已存 before snapshot ID、显式 account_scope 和新鲜度政策；不接 raw receipt/check/通过布尔值。顺序固定为 pending→balance→after snapshot→逐市场 execution（真实 typed profile 前后包围）→全账户 wallet→独立 mark/book→原来源原子发布及 native check→联合 current 断言。基线/原 ledger/旧冻结在初始 DB 视图中读取，所有 GET 位于 writer lock 外；pub 事务只调用既有 store/reconciler，不写订单或 ACK。

复用/清理计划：不改原 collectors 的请求/分页/schema/身份哈希，不新建金融或冻结表。只在 NativeAccountCheck 增加内部 unavailable publisher，沿已有 inputs=None＋固定 failure/schema/append-only publisher；自采、当前性或发布错误在独立事务保存原账户失败（发布本身失败则拒绝，不能假称已冻结）。部分 source 发布须原子回滚；原失败不会被后来匹配清除。政策/非法模式/无有效基线/调用者已有事务的入口错误在 I/O 前拒绝。

每 collector 保留其现有 128 次 SDK 上界，不修改或包装共享 SDK 方法来假称限制内部重试。自采阶段数 N+6；观测计数根据各实际 receipt 及原代码固定 profile 次数生成。余额与 after snapshot 之间增加一次实际 typed profile 读取，核当前账户并保留严格毫秒端点分离；不伪造时间或 sleep/poll。组合保守上界为 Binance 276+132N / OKX 274+132N（N为1..64），不是128次全流程 cap，更不认证 SDK 内部 HTTP 重试；实测/长期容量留作后续。输出仅 collector-owned 本地观察包装、source/check IDs、完整新 policy、源码/DB位置摘要和操作计数，仍两个 flags=false，不可作为 transferable admission。

先缺 API RED，原真实 SDK/fake 最底层方法、双市场非零仓位/partial/pending/费用资金费的8正向及分阶段异常、入锁拒绝/指针/输入变异、源发布回滚、旧冻结、并发 ledger/freeze、无重试/无新订单验证。S3仍须将实际 market metadata、候选/策略/配置、DB及本地自采调用直接与原每单 CAS/HTTP 绑定，禁止接 caller 自封 wrapper 或重封旧候选；本步不解除任何 gate。

S2b6 故障注入修正/清理计划：先证明核验结果随提交回滚时不能跳过独立失败发布，再仅以事务成功退出标记判定已持久化。连接替换 RED 证明 failure fallback 也必须验证原 DB；将连接/位置断言提成同一局部函数供正常和失败路径复用，身份不确定时不向替换库写入且不声称已冻结。原 27 项正向/阶段失败回归及新事务/连接用例保护行为；不改旧 collector/金融/SQLite schema 或状态机。

实现/验证：78 项自采用例均沿真实 SDK 类型和原完整 fake/raw/SQLite 管线；两 venue × 单双向 × 多空保留两币非空持仓、实际部分成交/未决、费用/funding，实测显式 SDK 次数 Binance 39 / OKX 58。after snapshot 保留原 before 市场排列，执行与市场来源仍规范排序，不修改旧证据或旧顺序契约。非法 account_scope 按原 predicate 在 I/O 前拒绝；source/check 写入失败原子回滚，提交回滚不误认冻结已保存；替换连接/位置不向其他库发布失败。正常/失败路径共用原 DB 身份检查，无新金融或冻结表。

CPython 3.14.2/3.11.15 各 1753 passed / 1 既有 isolated cash channel skip，1754 个唯一用例集合相等，包含原来源/账户/订单/冻结/SQLite；两版 compileall 和 diff 通过，详细失败轨迹与 JUnit 身份见台账。仅主线程复核、串行测试，活测试期间不编辑。输出的源码文件/DB 位置摘要及本地调用归属不是服务端签名、已加载代码完整证明或每单授权；两个 flags=false，默认交易路径未接新 collector，S2/S3/S4 与 C5/C6/C7/完整 Goal 仍未完成。

## S3 原 intent/CAS 与 HTTP 每单消费

文件：CCXTTradeEngine、OrderAudit、db_util 及对应原状态机回归。

2026-10-23 接入前复核：原 CAS 仅约束单 record，且旧 check 的完整 ledger 在合法 intent/claim 后也会变化；不能直接复用 None 或忽略自身新行。详细 [账户级预留/原 CAS 协议](../specs/2026-10-23-native-per-order-admission-protocol.md) 记录当前代码、公开官方接口与 SDK 证据。用户现已专门批准每稳定账户尚未被原生观察的新风险意图串行化，按 S3c 实施，不再等待同一设计确认；逐单资金能力仍是独立硬门槛，不将此批准扩展为新增金融公式、实际配置或任何交易权限。

- 新证明版本绑定账户/模式、DB、候选/部署/配置/代码、role/qty/price 与全部 source IDs；持久化原 intent 引用。
- 新增 NativeAdmission/NativeMarketEvidence 目前未纳入旧模型/部署/输入/paper 的指纹列表，也未被默认入口消费；S3 必须显式版本化并绑定新消费者及依赖源码，不能假设旧 workflow SHA 已覆盖它们，更不能重封旧模型/部署/订单来续用旧授权。
- 网络在 SQLite 写锁外；原事务内复核历史/投影/reservation/年龄，原 claim 和 HTTP 前再核 route/account/kill/candidate/freeze/实际意图。
- 跨连接并发、claim 前后漂移、超龄、原生未决预占不一致不发送；已 claim/unknown/submitted 不退回可重创，不重封旧契约。
- 旧恢复/查询/撤单/降风险路径继续按原门禁工作，不要求补造已消费模型。

### S3a 原生 instrument 来源（已实现，限独立来源子层；不实施待审 CAS 协议）

文件范围：新增 NativeInstrumentEvidence 与专用 raw/fake 测试，不改旧 NativeMarketEvidence/账户来源的 schema、源码身份或旧证据，不接默认发送/准入。固定 API `collect_native_instrument_evidence(exchange, codes, *, mode)` / `verify_native_instrument_evidence(document)`；codes 为完整显式 USDT swap 目标池（1..64），不接受 caller market metadata/PASS。只调用一次明确公共 GET：Binance/binanceusdm fapi exchangeInfo `{}`；OKX public instruments `instType=SWAP`，不调用 load_markets/fetch_markets/fetch_currencies、私有接口或自动重试，也不修改实际 client cache/options/配置。

schema `chan-native-instrument-evidence-v1` 固定保存 venue/mode/codes、endpoint/params、public environment、SDK/边界源码、完整允许字段 raw_rows、每 code 的 canonical 执行 market/原生状态/active/raw_index、单次请求与总批次的本地起止。沿原 _raw/finite/单位/完整 metadata validator，并复用当前 credential-free SDK 的纯 parse_market（不复制解析器/金融公式）；显式 SDK 版本/源码须对应重建使用的版本。raw rows 保留允许的 contract/precision/filter/状态/已知即将变更字段，忽略任意未允许字段，不将 SDK 默认解释伪称原生显式报告。

不将 exchangeInfo.serverTime、上架/到期/更新/未来生效时间充当新鲜时钟；clock_kind=local_request_window_only、source_ms=None，未来消费者须显式配置 instrument age/span，当前不给隐含默认。完整字段下的非交易状态可保留为 active=false；缺失身份、重复/遗漏目标、错误产品/单位、非有限或不完整执行 metadata 则拒绝整批。输出 economics_complete=false/native_admission_verified=false，仅陈述允许字段覆盖，不代表全部平台交易规则或资金能力已经证明。

先观察缺 API RED，再用真实 SDK 类型＋最底层 fake 单端点的两市场、binance/binanceusdm/OKX × live/testnet 验证：缓存投毒不影响原始来源，原 cache/options 不被改写；原 Engine 的 metadata 投影逐字节对齐；raw/派生/重封变异、路由/SDK/源时钟/输入漂移、重复/缺市场、错误类型与异常脱敏、核心无可选 SDK 导入。未完成原 per-order 消费前不把这一子层宣称 S3 或完整 Goal 完成。

实现证据：422 项新用例，最终 CPython 3.14.2/3.11.15 各 1122 passed（422 新来源＋700 原来源/核算/订单用例），0 failure/error/skip/warning，集合一致。先用真实 RED 阻止 SDK 默认小数位数替代缺失 tick/lot filter、OKX underlying 推断掩盖显式币种/ctType 矛盾、bool/int 环境别名、缺必需原约束字段/分数毫秒、请求开始后路由变更仍发 GET、错误 envelope 残留 rows 被接受；不通过放宽原 schema/核算处理。数字字段沿原 _MONEY；SDK 会先构造备用精度字符串，因此 precision digit count 仅允许原数值指数范围 0..100，属于解析/分配边界而非资金/搜索/鲜活性默认值。

字段依据为 [Binance Exchange Information](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data#exchange-information) 和 [OKX instruments](https://www.okx.com/docs-v5/en/#public-data-rest-api-get-instruments) 及本机 SDK 4.5.89 的原 parse_market；未调用实际端点。reader 显式重建需要对应 SDK，不做无 SDK 解析降级；核心 import 无可选依赖。原 cache/default prepare 路径未改，新来源尚未接逐单消费者/原 CAS/源码指纹闭包，未证明全部平台过滤规则或资金能力。详细协议仍待审，两个 flags=false、全部 gates 与完整 Goal active 保留。

### S3b 原 Engine 当前 instrument 使用边界（已实现，限独立消费子层）

范围只新增 NativeInstrumentCurrent 及 fake/SQLite 回归，不改旧 source schema/哈希、Engine、金融或 CAS。复用原 `_market_contract` 完整投影，不复制 metadata/parser，也不自动 reload/set_markets；原 Engine、现有 SQLite 连接和已初始化 SDK cache 都须明确存在且无调用者事务。固定入口 `collect_native_instruments_for_engine(engine, codes, *, max_age_ms, max_observation_span_ms)` 自行调用 S3a 公共来源，不接受 caller receipt/PASS；实际 Engine 的 mode/swap/非 dry-run、SDK 路由/类型与原方法、完整 cache/options/目标池及 DB 连接/位置在调用前后必须不变。

两个预算均显式必填非负整数毫秒（bool 不算），不借 account 默认；age 为最终全部复核完成时刻减 source.started_ms，span 为 source.finished_ms-source.started_ms，恰界允许、超 1ms 拒绝。没有原生生成时间，不能伪造 server skew。当前实际 Engine 投影、active 和原生状态必须逐字节匹配新采来源；缓存空缺/不完整、受替换方法、来源或输入/DB/client 漂移均拒绝，不尝试刷新补救。返回原来源字节，两个 flags 仍 false，不产生新授权包装或持久写入。

先缺 API RED，再以真实 Engine 方法、SDK 类型及底层 fake 公共 endpoint 验证双币/三 SDK × 两模式的匹配与过期缓存、全部单位/精度/限额/状态字段、严格时钟/预算、方法替换与 cache/DB/input 漂移及失败零 I/O/零写入。固定 GET 只在无 writer lock 时运行；主线程串行，活 pytest 不编辑。此子边界不接默认发送，不证明资金、服务器原子性或已加载 runtime 完整性；账户级 CAS 协议已按 S3c 获批，逐单资金规格仍独立待补。

实现结果：先直接缺 API 测试观察 1 failed，再最小实现；首组 133 passed，保护性补查后 398、最终 446 项专项用例全部通过。已初始化的 markets/markets_by_id 和原 bound methods 才可调用原 `_market_contract`；空缓存或受替换 loader 不运行，完整缓存/options/公域路由/SDK/DB 身份前后相同，并比较原投影、typed active、native state。年龄包括来源 reader、最终 DB 位置及全部解析复核耗时，跨度不误用年龄；零预算无隐含宽限。返回原 `chan-native-instrument-evidence-v1`，不另封 ready/PASS。

CPython 3.14.2/3.11.15 关键组合各 1568 passed（446 新消费者＋422 原 instrument 来源＋700 原来源/账户/订单用例），0 failure/error/skip/warning，1568 个唯一用例集合一致；两版 compileall 和 diff 通过。新代码独立于旧 Engine/source，未改其 schema/文件/部署指纹；本地代码字节前后核验仍非加载 runtime 完整证明。S3 默认消费者/账户级原 CAS/逐单资金能力/完整新指纹闭包与 C7 仍待，不能从这一步或 inactive 匹配推导准入。

### S3c 已批准的账户级原 CAS 协议（实施中）

用户已对专门的详细问题答复“批准上述账户级串行协议（推荐）”，见 [协议批准记录](../specs/2026-10-23-native-per-order-admission-protocol.md)。不再以该设计待批阻塞实施；逐单资金规格、候选换代与真实服务/配置门禁保持独立。

先实现原事务可重读的 L0：新增 NativeOrderBoundary，复用 NativeCurrentComponents 的 DB-only 当前快照、原 native check/ledger/journal prefix/risk state、显式完整 policy 与时间核验。capture 在自有 SQLite 视图中生成有限版本基线，assert 只在原 SQLite 事务中重读原数据；拒绝账本/前缀、来源、冻结、DB 位置、源码/输入/窗口漂移及孤立无事件尝试。输出两个 flags=false，不写原订单/冻结或产生资金/发送许可，暂不改旧 v1/v2/v3 字节、表或默认入口。

L0 清理/修复计划：16 项故障注入 RED 已证明最终源码核验后的连接替换缺口。仅在新模块提取同一 DB/连接/table/事务所有权守卫，capture/assert 的最终源码与字节核验后复用；DB 位置查询前后都验证原连接，不查询替换库。复用已通过的 L0/原 CAS/来源回归，不重构旧金融、来源或 SQLite 实现。

随后在同一原 `_order_write`/journal 中消费 L0，只允许具体本单的确定 intent 增量 L1、claim 增量 L2并持久引用；跨记录/市场/表争抢和 unknown 不释放必须用真实原 CAS/双连接证明。不得把独立 L0 helper 或其测试声称完整账户串行协议已完成，也不得通过忽略自身/重封 ledger 通过差异核验。金融规则未完整时继续禁止默认新风险。

L0 子边界已离线实现：153 新用例，双币非空/partial/pending/fee/funding，Binance/OKX × one_way/hedged × 多空；原事务内手动组合 L0 断言＋原 CAS 的双连接/跨记录/市场/表实验只允许一个沿同一 L0 成功，旧 L0 不能自行重采或清除 submitting 无 ACK 尝试。该实验不是默认入口自动消费，也未实现本单 L1/L2 例外。最终 CPython3.14.2/3.11.15 各 493 passed、0 failure/error/skip/warning、集合相等，含原 current/核算/check/冻结/历史/事务回归；两版 compileall/diff 通过。16 项连接切换真实 RED 经共用最终 DB 所有权守卫修复，替换库零 query/write，原源码/表/证明未修改。

L1/L2 实施与复用计划（该持久增量子边界已完成下述离线验收，完整 S3 未完成）：新增 NativeOrderTransition 的 append-only 原事务引用，指向原 intent/claim journal 的确切事件；只给新显式 `native_boundary` 调用增加版本引用，不更改旧 v1/v2/v3 契约或历史字节。原 `acquire_open_intent` 负责原 CAS 和实际参数，原 claim 自动检测该意图的持久引用，不能省略参数绕过；不另建资金/订单状态机。新表只保存两次不可变边界事实，不提供释放/重置/额度接口。

最小重构范围为 NativeAdmission/NativeCurrentComponents 的 DB-only 来源读取与原全账本断言分离：旧公开入口仍必须检查原 L0 全账本；新消费者先核持久 L1/L2 的完整原 ledger、journal 前缀与整行摘要，再复用相同来源/冻结/时间检查，不能接 caller 传入 expected ledger。OrderAudit 仅对新意图追加版本引用；旧无引用字节不变。db_util 只在原事务包围本单原 CAS，SqliteDB 仅按既有原子 schema/保留名模式初始化新引用表。

整行复核复用 AccountRiskStore 原 trade-shaped 表发现逻辑，最小提取 `_trade_tables` 供原 `_ledger` 与新边界共同使用，不改变旧账本选行/顺序/内容。L1/L2 附带这些表全部行的摘要，第三方字段或未成交信号的增删也不能在持久引用后被悄悄忽略；不把含任意快照/文本的整行复制进新公开证据。

TDD 先用真实 fake/SQLite 的双币非空 fixture 观察缺 API RED；正向须原 intent→重启→原 claim→L2，核整行允许字段、恰好本单一个 attempt/intent 和一个 claim event。反向覆盖不同记录/市场/表/连接争抢、第三方或本单任意其他字段/历史/来源/冻结漂移、引用缺失/重封/表损坏、事务回滚与 claim 未知不释放，均不得额外 HTTP。新 reader/断言两个 flags=false，仅是并发/字节一致性；资金规格、完整准备身份、新契约消费者/指纹及默认 HTTP/CLI 接入仍待，常量阻断保留。完成适用双解释器回归、compileall/diff 与主线程审查后才记录本子项完成。

主线程复核/简化计划：先用额外 RED 验证旧直接 Engine 不得将新一致性引用当成资金许可、最终检查前后连接替换不得查询替换库；只给带新原 journal 引用的开仓添加显式拒绝，不改变旧无引用 v3 或恢复/减仓语义。已有 249 项保护后，删除 finish 中重复的整份 ledger 组装，改为复用从原检查＋本单已核验 immutable attempt 重建的历史增量；保留实际参数/整行/journal 数量的独立核验，不共享一个 caller expected ledger。

旧程序兼容性补查：新诊断意图须使用独立 `chan-native-cas-order-v1`，它保留本次实际条款，但不是可执行的新资金/交易契约；现有严格 Engine reader（包括不认识新 journal 标记的旧版本）必须拒绝它。不把新增引用挂在普通 v3 上后仅靠新运行时限制，更不重封任何已经保存的 v1/v2/v3。新 schema 缺 L0 或原引用拒绝，旧恢复/减仓用例保持原契约；最终可执行新版本及全部消费者仍需后续单独验收。另核 typed/canonical 数字、原 SQL 允许更新字段精确集合，防止内部调用把任意新增字段声明为合法增量。

最终时间核验位于新引用 INSERT 与完整回读之后；32 项 RED 证明早期检查会漏掉写入/回读晚 1ms。只移动新 finish 的原 current 断言到最后，不改旧消费者或原时间公式。事务内尚未提交的 CAS/引用一起回滚；已提交 submitting/unknown 后的外部失败不退回 created。该 owned-view 检查仍不代替后续 HTTP 前/事务退出后的实际使用边界。

旧接口兼容修正：原 writer 已核验的 history 只作为内部 hook 分流信息；无原生引用的旧 intent/claim 不套用新 native-only 精确 CChanDB 类型限制。新原生分支仍要求原 owned DB、独立重读并逐字节核历史，不接受 public caller 的 expected/PASS。真实子类旧 CAS 的 1 项 RED 保护这一范围，不放宽原生所有权。

最终证据：381项新测试，CPython3.14.2/3.11.15相同54模块各3688 passed/1既有isolated-channel skip/13小样本训练警告，0failure/error、3689个唯一用例集合一致。包含原native来源/核算/check/freeze、执行/订单/SQLite/恢复、safety/state-machine、opening inputs、部署和配置化/持久paper；两版compileall/diff通过。只用fake/合成/临时SQLite，主线程串行且活pytest不编辑。原金融公式与旧契约/schema字节不改，新增引用表由原SQLite原子初始化并保留表/trigger名，foreign同名表拒绝且原初始化回滚；旧程序严格契约reader不能执行新诊断schema。

接续顺序：先把实际准备身份（信号/候选/部署/输入、完整instrument自采及component自采调用、显式政策、配置/代码/加载runtime、role/两单位/价格/post-only）冻结为新的非可执行prepare绑定，并将其原L0/原CAS引用贯穿；逐单资金规则不足时仍拒绝。之后才是新可执行版本的全reader/ownership/源指纹与原HTTP前最终复验、默认多市场S4。不得把本诊断schema更名为可执行或将资金缺口跳过；没有完整资金证据/默认全入口/外部C7不去除阻断，不关闭完整版Goal。

### S3d 实际 prepare 身份（本地身份子层已实现；完整自采/CAS接入未完成）

先新增 `Trade/NativePreparation.py` 的 `capture_native_prepare_identity(engine, record_id, amount, price, *, post_only=False, entry_assessment=None)`，必须自行从原DB读取实际信号、用原COpeningInputs核配置/完整行情epoch/信号/部署，并在原prepare_order前后重读candidate与原门禁。冻结实际Engine/DB/配置摘要、完整执行条款及两单位、原opening stamp、candidate文件身份、策略/部署/entry（适用时）身份与选定关键已加载callable；不接受caller receipt/check/PASS，不写订单、资金或新冻结，不返回可执行授权。该子层还不是本次instrument/component采集权，后续须在同一准备调用内直接采集再接L0/CAS，禁止转交此JSON当准入。

复用/简化范围：复用原SafetyPolicy的candidate和kill/env门禁、原COpeningInputs与entry verifier、原Engine执行/精度/限额，不复制财务/解析或改旧v1/v2/v3。新增加载边界只用stdlib AST/compile读本机当前Python源码，不执行源码、不安装依赖；对选定实际bound methods/输入检查方法验证fresh code及默认参数，实例/类替换均拒绝，前后快照一致。明确这是selected prepare callables覆盖，不宣称整个解释器/插件/服务器可信；完整加载闭包仍属后续接入验收。配置/原candidate只读，不回写旧证明。

先缺API RED；合成配置/行情DB与原fake Engine测两venue×单双向×多空及原信号/执行条款，前后改原行/配置/行情/candidate/门禁/方法/DB/实际参数无新订单；异常脱敏、无caller收据、typed有限数、事务锁内不发I/O、core-only导入。已有S3c双版3688通过证据对未变范围复用；本子层及实际受影响输入/原契约适用回归逐项执行。后续自采/逐单资金/默认HTTP/S4/C7不因本模块通过而省略。

本子层清理/修复计划：282项已通过保护下，80项故障注入RED显示非法开始时钟须在private prepare前拒绝、最终源码检查回调能更换Engine owner/config/kill。只在新模块提取同一owner检查供前后使用；最终序列化/代码检查后再复用同一实际输入/candidate/门禁读取（不再触发重复文件实现回调），不复制第二套校验，不改旧消费者/DB/资金。scope变异8RED和末尾记录/config/candidate与get_exchange替换32RED已修复，仍不宣称全局原子快照。

实际结果：438项新用例；CPython3.14.2/3.11.15相同10模块各754 passed、0failure/error/skip、7小样本模型警告，唯一集合无差异。真实小合成模型/原部署的entry通过、缺失、篡改与加载verifier替换均验收；普通信号夹具覆盖两venue×one_way/hedged×多空，但不是完整非空账户自采→CAS E2E。后续48项真实RED补齐env/scope property、静态限额及三个数量/契约helper；9项真实RED补齐同code不同globals及原entry verifier替换；8项真实RED要求缺现有client时在原Engine自动创建会话前拒绝。复制函数夹具初次遗漏原__class__闭包的8项构造错误已单独修正，不计生产RED。

选定callable同时核绑定owner、原模块globals、fresh-compiled code和默认参数；不执行源码，不把磁盘hash当整个加载闭包证明。开始/完成时钟只是本地prepare身份采样，非新鲜native来源窗口、完整调用耗时上界或跨线程/服务端原子快照。所有实际配置/candidate只读、原v1/v2/v3和默认入口未改，无新依赖。下一步在同一受控调用内直接取得instrument/component来源并绑定L0/原CAS，不能消费此JSON作为可转交准入；逐单资金/新执行版本与所有reader/指纹/HTTP/default/S4/C7仍待，两个flags=false。

### S3e 受控 prepare 与原生自采组装（实施中）

联合验收先新增独立的原生单位夹具，不改变旧fixtures或已经发布的来源/订单。Binance由raw exchangeInfo解析contractSize=1，OKX保留原生ctVal；在创建任何历史前固定完整metadata，用原Engine/SQLite产生双币非空持仓、部分平仓、非零未决单/保证金、fee/funding原事实。原生snapshot/执行/wallet/pending/balance及独立mark/book均从同一fake账户运输读取，实际prepare使用原SDK缓存/解析，禁止真实网络；不以重封旧.01历史、空仓或caller PASS替代联合证明。

随后固定同一调用中的实际输入/prepare→instrument自采→原component自采及失败发布→实际输入/条款复核→L0/原CAS引用顺序；最终使用时须包含组装和原事务耗时，任何源、账户、市场、信号/候选/配置/runtime或第三方ledger变化拒绝。复用已有collector/current/账本和原CAS，不复制financial/parser/state-machine，不使用隐含预算/金额公式或自动重采；需要抽取旧内部核验体时先写具体清理计划并保护旧回归。完整准备引用须版本化并被原事务实际消费，不能只堆叠可转交wrapper；资金能力仍是独立硬门槛，诊断链通过也不解除默认阻断。

联合夹具清理计划：8项真实SDK/原生单位正向已通过后，删除临时异常context展开，只在测试中提取一次手动组件组合供故障注入，显式先actual prepare稳定SDK options再采instrument。测试helper不是生产受控入口/授权；旧fixture、生产解析器/金融/来源/CAS不改。补现金/资金费/未决/metadata/候选漂移，按原核算检查exact fraction和非零原生预占，再推进生产身份断言复用及真正持久CAS引用。

该联合前置验收现有22项：两venue×one_way/hedged×多空8正向，12项来源/候选变异和2项自采期间候选漂移。原生metadata先固定后才创建原历史；钱包差额精确0、TEST当前量1/25、未实现4/5、原生聚合未决保证金10，不推导每单可分配额。校读另以2项RED修正raw instrument和SDK info共享引用、8项RED显式清零初始margin/available及统一OKX汇总；均是新fixture问题，不计生产缺陷。最终两版22 passed/0警告，未变1115项复用此前两版5模块1137 passed/1小样本警告，非最终1137整组重跑。旧fixture/生产文件/实际配置未改；完整S3e仍未完成。

下一生产清理计划：先把NativePreparation的现有current核验体提为共用本地视图，保留原capture接口、原prepare执行和438项时钟/owner/变异保护；新增的锁内当前性断言不得调用prepare_order或任何private/public GET。然后接同一次受控自采及版本化原CAS持久引用，不能仅返回wrapper或消费caller自封JSON。first prepare的SDK杠杆读取可能加载bracket并改options，实际次序/最终cache及所有源使用时刻必须检验，不把bracket缓存当资金证明；完整加载闭包、逐单资金、HTTP/default/S4/C7继续独立验收。

本地断言实现细化：原capture仍返回相同非可执行JSON；内部_capture_native_prepare_context运行同一实际prepare并保留原owner/输入检查闭包，生成不可由JSON恢复的进程内上下文。弱引用关联只保存该活调用的本地绑定，不是资金/订单状态或持久授权；复制、另造对象、传入dict/bytes/PASS均不能代替本次上下文。assert_native_prepare_context_current只能在原SQLite owned事务、该实际Engine、原signal未取intent时执行，重读同一本地视图/entry/原冻结及已观察client cache/route，返回None、不GET、不重prepare或写表。此阶段不声称已经支持合法L1/L2后的同一signal全行hash变化，后续必须由版本化原CAS原事件独立重建。全部flags/default阻断不变；先缺API RED，再检查网络/prepare零调用、上下文/owner/原始数据/缓存/门禁变异及原438回归。

2026-10-24 本地上下文子层已实现：313项新用例，原JSON接口通过同一内部capture返回副本；实际检查闭包仅一份，不复制金融/输入/订单校验。owned断言前后重读，原freeze检查置于最后本地重读前；1项缺API、72项使用时钟/末尾变异和24项risk-reader尾部变异RED分别修复。8项原CAS测试首次用错参数只修测试，不计生产RED。raw BEGIN、外部JSON/复制/新对象、借用Engine、原模型/entry损坏、原冻结、signal/候选/配置/runtime/client缓存变化拒绝；8项非空双venue/模式/方向证明锁内零GET，GC不释放或改写原created订单。

双解释器相同12模块各1089 passed/0failure/error/skip/7既有小样本模型警告（433.36s/455.12s），唯一集合相同；双版compileall/diff通过。活句柄不是密码学隔离、服务器证明或持久授权，不抵御任意改写模块globals的宿主；没有新增来源年龄预算，不能把本地未变当native账户当前/资金充分。下一步继续同一次受控prepare/instrument/component自采与原L0/版本化CAS持久引用；该pre-intent断言不忽略本单合法增量、不自动适配claim或重启，完整S3e/S3/S4及C5/C6/C7仍未完成。

同次自采/原intent引用实施与复用计划（2026-10-24）：新增NativePreparedIntent.acquire_native_prepared_diagnostic_intent，入口只接实际Engine、record/两单位前请求、before ID、account_scope、完整显式component policy、显式instrument age/span和client ID，池/模式从真实输入取。初始原owned视图固定before/完整trade-shaped行与journal；锁外实际prepare→独立instrument→原component collector，最后用同一活上下文/L0在原CAS内复核，不能接受caller receipt/check/PASS。沿现有弱键注册表关联本次自采的冻结包，不增加资金/订单生命周期或新表。

原writer只添加可选native_preparation活上下文；NativeOrderTransition新增chan-native-order-transition-v2，root仅多preparation绑定，原v1读取分支和既有字段不改。原intent/attempt/journal与完整引用同事务；stored reader从原check/attempt和raw instrument独立核两单位/信号/来源/窗口/执行条款，不以重封摘要替代事实。v2仍沿不可执行chan-native-cas-order-v1，原Engine/旧严格reader继续拒绝；在合法L1/L2后的完整本地状态重建及资金消费者完成前，v2 claim须在原SQL前明确拒绝，不默认继承v1 claim或丢prepare标记。旧v1诊断/原v1-v3恢复继续回归。

复用/清理限定：保留NativePreparation原三项tuple位置及旧JSON接口，只允许受控调用追加内部源绑定，原断言读取前三项；复用原ledger/records/prefix、source raw readers、component失败publisher和原CAS更新集合，不复制金融/metadata parser或并行订单引擎。准备源年龄包含最终original引用INSERT/回读；source异常沿原sticky发布，本地参数/候选早拒绝不假称冻结。先缺API RED，再双venue/模式/方向非空联跑、来源/候选/metadata/账本/引用变异、原事务失败回滚及绕过/claim拒绝、重启历史读取；适用双版本/主线程审查/Lore后再记有限子层结果。完整S3e、资金、HTTP/default/S4/C7不因该诊断引用通过关闭。

原CAS后局部检查的有界复用：只由原finish_transition独立核验的完整expected after-row进入内部闭包；每次先严格比较DB实际整行等于该expected，再用冻结原signal读取原输入/候选/模型。公开pre-intent断言仍不接受expected参数、合法intent后仍拒绝；不暴露caller record排除/更新字段豁免。原journal、全部trade-shaped整行/ledger验证仍负责其唯一增量；本地检查之后须再核原完整transition，不能漏掉模型/风险读取期间第三方行变化。9项初次正向已过后删除测试临时context展开，仅用正常异常边界继续故障验证。

2026-10-24 同次自采/原intent引用子层已实现：72项新用例，两个venue×one_way/hedged×多空非空账户及两个真实小合成模型正向。原capture闭包只增加原writer专用expected整行分支，原三项tuple位置/公开JSON和pre-intent断言保留；v2只在现有append-only表的root增加preparation，原v1形状与旧契约不重封。失败原子回滚intent/attempt/journal/引用，原raw观察可保留；来源异常沿原sticky publisher，已知冻结在任何新GET前拒绝。最终年龄包括原引用INSERT/回读及全部本地复核耗时。

真实RED/GREEN保护缺API、after-CAS本地回调晚改第三方行、开始前实现固定、已知冻结/非法时钟提前拒绝、独立stored链接/严格字段及policy别名、组件字段/操作顺序。原Binance合法client ID字符保留。初期时钟、CChanDB contextmanager及错误venue方法名仅修夹具；真实模型的原1h候选有效期不扩大，只把历史放在先前4h边界并在close+15m调用。另明确测试：对应GET之后未被再次观察的服务器变化不能被本地历史证明发现，诊断引用一致也不允许claim；不将这个限制伪装成检测能力。

CPython3.14.2/3.11.15相同24模块各1841 passed、0failure/error/skip、9warnings（983.66s/1019.22s），1841个唯一用例集合差异0；双版compileall/diff通过。范围包含原381项transition、313项context、438项prepare、22项联合及原状态机/SQLite/报告CAS/恢复/账户/冻结/执行、安全、opening、模型部署、持久paper/trade-cycle，非全仓验收。5个小样本XGB AUC与4个MLP收敛警告如实保留，全部fake/合成/临时SQLite、主线程审查，无真实I/O或独立代理审计。

当前仍为不可执行诊断：v2 claim即使重启也在原SQL前拒绝；stored reader从原check/attempt/raw instrument核历史，但不是重新准入或服务端签名，需对应SDK而不需要client/GET。完整L1/L2后的fresh本地重建、全部可执行reader/指纹、逐单资金能力、HTTP/default/S4/C7及宿主完整可信仍待；不得扩大为完整S3e完成或解除常量阻断。源码变更不允许重封旧模型/部署/candidate；主Goal保持active。

S3e后续本地重建/清理计划（基线67e72ef）：从原持久v2 intent与不可变attempt/event取得精确after-record/full-ledger hash，不尝试从旧before hash反解记录、保存任意opaque before快照或把本单从账本删除。新增assert_native_prepared_intent_current(engine,record_id)仅在原owned视图重读实际Engine/guard/候选/输入/entry/selected runtime、缓存metadata及本地public/private路由；整行须匹配原事件绑定的after hash，来源/冻结/明确窗口仍用原current检查。成功仅None，不产生新收据、资金许可、claim或GET；可跨同代码重启重新建立本地视图，不把活handle序列化或重新prepare旧单。

先RED缺API，再最小提取NativePreparation原current的本地读取体（保留旧signal/expected整行分支和全部公开语义）；NativeInstrumentCurrent的原缓存投影只提取为共用只读体，原collector owner/时钟/GET次序不变，防止复制metadata/金融规则。新路径的expected after hash只能由原持久行/事件取得，公开API不接document/hash/phase/PASS。前后核owner、client本地状态、当前字段和完整原transition，最后来源预算包含本次检查耗时。实际原Engine遇v2意图时消费该核验后仍在原资金阻断处拒绝，v1原诊断路径不附加新要求；不提前接发送或放行v2 claim。小夹具先验证重启/非空账户/零GET零prepare及信号/候选/配置/metadata/路由/账本/时钟/冻结变异，再适用双版回归；完整加载闭包、每单资金与HTTP门禁不因本地重建通过而关闭。

后续RED细化：原绑定没有持久保存SDK/cache/options/凭据的本地基线，仅检查本次核验前后相同不能证明与原调用相同。新写入的preparation binding升级为chan-native-prepared-intent-binding-v2，仅增加client_binding_sha256；摘要覆盖原cache/route和实际SDK apiKey/secret/password，绝不保存明文或以此替代原native账户身份。原capture identity/来源schema不变；旧binding-v1保持历史解码、claim继续拒绝，不补摘要/重封或用当前client替代旧基线。新增stored严格字段/摘要形状及legacy-shaped历史兼容单测；新原Engine检查仅在具有完整新基线的v2绑定上可成功，资金/发送原拒绝仍独立保留。

本轮有限子层结果：70项新用例，缺API先1/11项RED；8项SDK先前漂移、2项原Engine未消费真实RED，补原调用摘要与真实消费者后GREEN。11项初组、21项基线组、134项联合和8项末尾回调/隐私专项依次通过。原current读取体与缓存投影各仅一份，新helper纳入selected runtime；从原事件after hash核实际完整行，不反解before、不忽略本单，公开API不接JSON/hash/phase/PASS。原Engine在v2分支原owned事务中调用后仍拒绝资金/claim/发送；没有新表、金融规则、默认参数或自动解冻。

最终CPython3.14.2/3.11.15相同26模块各2357 passed、0failure/error/skip、9warnings（1184.74s/1235.38s），唯一集合差异0；双版compileall/diff通过。含70新、72上步绑定、381原transition、313原context、438原prepare、22原联合、446原instrument消费者及615原订单/来源/模型/paper等，非全仓或外部认证。旧67e72ef两venue原测试库在副本上以同合成时钟读取等于原文档，claim拒绝、原文件SHA不变；首轮真实墙钟小于fixture未来时间而拒绝，仅修诊断调用时钟、不改产品reader或旧事实。新Engine/guard/连接重建复核已测但仍复用相同SDK缓存，不声称冷启动新SDK完整初始化或整个宿主可信；源过期、配置/SDK/缓存/输入时代变更均拒绝。后续继续冷启动/完整L1-L2及新执行reader/HTTP/default集成；逐单资金、S4/C7和整个S3e/C5/C6/C7仍未完成，主Goal保持active。

### S3e接续：显式新SDK冷启动（e65d0f9之后，离线子层已验收）

新增initialize_native_prepared_client(engine,record_id,*,instrument_max_age_ms,instrument_max_observation_span_ms)，只在原Engine.exchange为None、无外层事务且原配置/信号/候选/门禁有效时工作。复用原get_exchange/create_exchange建立新对象，自己取得单一instrument公共来源、用原纯parse_market和set_markets初始化该新对象的声明池，再用原_execution_settings/_observe_account和原native账户身份GET核设置。不得调用load_markets的缺缓存分支、fetch_markets/currencies、set_leverage或prepare_order；不从旧来源伪造新观察，不修改已有client或实际配置。显式年龄/跨度沿原规则，无默认预算。

signal可为后续原受控prepare提供已初始化SDK，但成功只None、不写订单/收据；已有完整binding-v2的created诊断意图须额外在原owned视图按原L1完整记录/ledger、原client摘要和旧来源窗口核验，新的instrument/设置GET不能延长旧证明或补造旧binding-v1摘要。冷启动只重建新进程的SDK缓存，完整原摘要不匹配就拒绝；不复制任意options、旧cache或凭据到输出。失败仅清掉本入口实际新建且仍由该Engine持有的client，不覆盖外部替换对象/连接，不改原订单和未知状态。原Engine/默认资金、claim与HTTP阻断保留；source失败沿可验证原库/账户的现有失败publisher（若具备原L1），不假称未知库已冻结。

先API缺失RED，再真实create_exchange/SDK类与底层fake native transport完成新client→初始signal→原自采intent→销毁client→冷启动新SDK→原L1检查；双venue/持仓模式/多空、raw metadata/账户/设置/原配置/缓存/来源时间/DB变化拒绝，额外产品/实际HTTP/资金变更/下单硬拒绝。先有这些证据再主线程复核，复用适用未变回归；旧来源/订单/manifest不重封，完整加载闭包、资金、L2/HTTP与外部C7仍独立未完成。

冷启动末尾收束清理：8类正常原路径已有GREEN后，将新模块重复的本地视图调用提为一份owned closure；6项最后时钟变异和2项SDK摘要收尾耗时RED已观察，最后读取时钟之后再次用同一原view核原完整行/候选/配置及完整ledger/前缀，再以其guard完成时刻覆盖本地核验耗时。不得删除SDK原摘要或放宽budget，不把时钟移到GET之前伪造年轻来源；原L1另保留原current/source窗口核验。

有限结果：54项新用例，双venue×one_way/hedged×多空新SDK→原intent→销毁SDK→重建原L1，另有两个fresh Python子进程从原配置/原临时库与fake原生wire packets重建，不传markets/options/cache。source/account/settings/超龄失败不改原订单、清理自有新client；已有client、caller事务/替代cache或receipt/缺预算拒绝。开始前已冻结或旧来源过期时不创建SDK、不GET。源码指纹增加本冷启动模块和实际DataAPI/ccxt.py factory，旧订单/来源不重封；完整原摘要不可重建就拒绝。

最终CPython3.14.2/3.11.15相同8模块各368 passed、0failure/error/skip、2既有小样本XGB警告（411.46s/433.15s），368唯一用例集合差异0；双版compileall/diff通过。组成54新＋70原current＋72原intent＋22原联合来源＋47venue＋26account＋63recovery＋14safety；未变更的其余2357基线证据只在原范围复用，不冒称本轮全跑。主线程按review模板串行复核，无代理/实际HTTP。源码hash不证明整个宿主可信，fake新SDK不认证真实服务；新GET不续旧来源，未完整重建的外部options/cache拒绝，不自动刷新或补造旧绑定。此入口不接默认发送，不计算资金；L2/HTTP、全执行reader/加载闭包、逐单资金与S4/C7及整个Goal仍未完成。

### S3e冷启动收尾复查（6ce2c92之后，24项补充回归已离线验收）

资金方向尚待新的专门确认，不写其依赖代码。独立复查已批准的冷启动边界：最后_client_binding之后仍有clock/local_view回调，owners只核SDK凭据等所有权，可能遗漏晚options/cache变化。先以双venue、signal/原L1真实SDK与底层fake运输注入最后时钟变异，观察应拒绝却返回的RED；若复现，只补末尾完整原SDK身份核验并保留最终来源年龄、原完整行/账本和原owned约束。不为该修复重采来源、续期原L1、增加资金许可/重试或另造状态机；适用原54及current/intent回归后再记录结果。若假设未证实，不凭静态猜测修改产品。

4项options晚变异已真实RED（DID NOT RAISE），最小追加原SDK摘要核验后4 GREEN。再扩完整SDK字段回归，并单独RED验证新增尾段核验耗时：不能仅将一个hash移到最后却仍以它之前的clock作为完成时间。拟以核心库单调纳秒差覆盖最后clock/local_view/完整SDK/原owned退出及终末owner的尾段，向上换算毫秒加到最后typed guard检查时间，作为保守使用时刻上界；不生成新来源时间、不设新budget/容差、不再调用可变业务时钟。上界可能比实际完成更晚而更早拒绝，不能延长旧来源或放宽年龄；typed/倒退与整毫秒/正1ns边界须有回归。只有这些证据GREEN后接受本修复，不扩资金设计范围。

实际结果：末尾SDK检查新增耗时未纳入原budget，另有2项真实DID NOT RAISE RED；补核心库monotonic_ns尾段上界后14项SDK/耗时GREEN，再加10项typed/倒退/恰界/正1ns GREEN。24新增组成双venue×signal/原L1×options/markets/public-route晚变异12、尾段SDK耗时2、恰界与1ns超界4、非法/倒退单调钟6；原订单/引用不改、不释放未知状态。没有新增helper/状态机/依赖、资金模型或政策参数，只复用原摘要与本地视图。

最终CPython3.14.2/3.11.15相同8模块各392 passed、0failure/error/skip、2既有小样本XGB警告（445.47s/467.88s），392唯一用例集合一致。78冷启动（原54＋24新增）＋70current＋72intent＋22sources＋47venue＋26account＋63recovery＋14safety；双版compileall/diff通过。两活pytest均确认exit0后才编辑，源码/测试摘要在两版期间一致。金融设计仍待本次单独确认，源/旧绑定不重封，完整加载闭包、L2/HTTP/资金/全reader/default/S4/C7与完整Goal仍未完成；主线程复核、全部fake，非独立审计或真实服务认证。

### S3e资金方向批准后的首个输入子层（2026-10-24）

用户已直接批准“本地模型＋原生额度”方向，见[资金设计§3/§6](../specs/2026-10-24-native-per-order-capacity-design.md)。不再将该方向标为待批；原完整Goal工具仍blocked，不能自行改为active/新建缩小Goal，但本轮授权的工作继续。完整金额公式、价格/费用币/档位支持契约仍须先冻结再实现，不能借方向批准补默认值或按notional/leverage、全额抵押代替。

独立新增NativeCapacityEvidence只解决Binance feeBurn、当前commission、symbolConfig、完整raw brackets的自采输入。复用原AccountIdentity/ExecutionFacts/NativeMarketEvidence，不增金融/订单状态机、原表/schema/reader迁移或默认配置；GET逐项由原账户身份前后包围，typed显式age/span、固定预算。原SDK的原始HTTP正文在后续身份GET前立即重读并严格核decoded对应，标准库保留小数token、拒绝重复键/缺正文/漂移；不是str(float)、cache补缺或服务端签名。选定SDK路径/环境/有效零retry检查只为此输入子层，不认证整个宿主。

缺API先RED；原SDK两venue类×live离线fake运输正向，另保留默认testnet签名NotSupported。未改demo/disableFuturesSandboxWarning或原factory，不能把原fake native方法的testnet PASS当真实签名路径PASS。首次组合92项失败源于这项夹具的未验证假设，查明后仅修支持预期、不放宽SDK阻断；不计作产品缺陷RED。另10项真实RED证明effective validateServerSsl及初始非法clock须在任何GET前拒绝，最小修复后GREEN。

另两项真实RED证实末尾typed clock必须在加单调差之前核验，防止bool被Python算术转为int绕过类型检查；复用原_window前置后GREEN。最终186新用例，双版同六模块各903 passed/0failure/error/skip/0warnings，唯一集合差异0；双版compileall/diff及主线程review通过，详细JUnit/身份见台账。两个flags=false、fee_currency=None、coef未应用，本层不核额度、持仓/pending的金额占用或全部档位覆盖。后续依然依次冻结完整算术→独立非空账户参考复算→原受控来源/prepare/L0/L1/L2绑定→全部reader/发送/default/S4/C7；旧intent/claim资金拒绝保持，整个Goal未完成。

### S3e必要book算术与尚未选择的价格政策（2026-10-24）

Goal续行已active，完整C0–C7不变。[算术规格](../specs/2026-10-24-binance-capacity-arithmetic.md)分开第1节可直接计算的持仓/挂单/候选包络，以及第2节需单独确认的FAQ价格假设P。只实施第1节，不借已批准A方向静默加入0.15%/费用估价，也不将文档当作服务端执行上界。P/N问题已提出，未答复时保持原严格边界；继续所有不依赖该选择的授权工作。

NativeMarginEnvelope只读已提供数据；复用原精确数字、AccountReconcile._ratio、NativePendingOrders._order及NativeCapacityEvidence配置解释。signed q×mark与全部residual LIMIT值分别形成每symbol/leg的max端点，hedge先分腿后求和；不跨symbol净额或移除RO/关闭方向挂单。候选仅显式双单位/valuation的数学投影，不造future native orderId/ACK。Fraction保留1/3、1/7、1/21，统一末端ratio序列化；GREEN56项后先写局部清理计划，再删除重复端点公式。逐symbol暴露显式汇总；数字ID仅按symbol比较语义别名，不改变原raw/历史。

RED/GREEN：缺API双symbol2项，缺symbol总暴露2项，11/00011重复计量2项DID NOT RAISE；最小修复后79新全GREEN。双版同六模块各721 passed/1既有skip/0failure/error/0warnings，722唯一用例集合一致，compileall/diff通过。已有skip为Binance income无isolated position现金通道，新79项全执行；中间719+1只是修复数字ID前证据，不标为最终代码。详细身份见台账。

后续仍须完整冻结/验证价格、费用币/费率、档位与余额算术，再接同次受控来源/原L0/L1/L2、全reader/HTTP/default和S4/C7。当前结果两个flags=false、input hash和zero margin delta不构成资金通过；原配置/门禁/订单/未知状态不改，不因book子层通过结束整个Goal。

### S3e原生杠杆与名义限额：不依赖待选估价的必要子项

从clean已推送e189821266d8b77bf744e21bacb84a7089640241继续，Goal仍active。P/N尚未答复，按executing-plans只暂停估价依赖；先在原算术规格§4冻结同一capacity source自己的markets/config与完整raw档位检查。新NativeLeverageLimits不收caller封好的book/markets/config，复用原margin envelope与原reader/精确数字/ratio；两条cap独立精确比较每symbol before/after暴露。要求连续完整档位/不增加的最大L；非中性coef语义未核则拒绝，不二次乘或忽略调整，也不假定维持公式已证。

TDD：4缺API、36拓扑/coef、4无兼容L的0-cap、4序列化耗时、20核心钟/正1ns真实RED逐步GREEN。169新增含非空双币one_way/hedged、独立顶点与手算、原生L、恰界1e-30、非候选币已有超限、源重封/末尾输入变异；无兼容L给None+明确违规，输入不全不补0。沿原_window与核心monotonic保守上界覆盖全计算，不给年龄/跨度隐含裕量。

双解释器同三模块各434 passed/0failure/error/skip/0warnings（169新＋79原book＋186原来源），唯一集合差异0、双版compileall/diff通过，主线程按review模板复核；其余未变原721/903等证据仅按原范围复用。所有活pytest34932/37384已exit0才更新文档，生产/测试SHA保持一致，详见台账。未修改旧代码/表/来源schema/执行状态机或实际配置。

输出coverage仅provided_book_against_observed_limits_only，book_origin_verified及两个资金/admission flags=false；within_observed_limits不是实际全书、资金或原CAS许可。本子项尚未把原account check/pending/mark绑定到该数学输入，不能隐去该缺口。后续继续原受控prepare/同账户全书与来源skew、完整价格/费用/余额、L0/L1/L2及所有reader/HTTP/default、OKX/S4/C7；不另建缩小Goal或关闭C5–C7。

### S3e原持久check到book适配：必要关联，不是自采/资金许可

从已推送clean的47d9f0c87c7b28336ff3bac94556e08a69280cf9继续。按原算术规格§6先冻结输入/只读/时间/owner边界，新增NativeAccountLimits；复用原_sources_snapshot/capture+assert L0、完整ledger/journal/冻结/最新来源、原限额计算和窗口核验，不改旧函数/表/schema或默认入口，不另建状态机。调用者只给source/check标识、假设候选和显式政策；book的signed持仓/regular pending来自原check、mark来自独立market、模式来自原组件结果，所有配置/市场/SDK须相符。

先4行为缺API RED→4 GREEN；28独立合法但跨来源不一致/联合过界RED→32 GREEN；末尾clock/input/owner/真实CAS 16 RED与校正后正1ns 4 RED→52 GREEN；追加回归93 GREEN；source实现/内部clone漂移8 RED→8 GREEN；reader回调触碰替换库8 RED→16专项GREEN。最初fixture setup4 error与漏接原L0合成时钟4 fail只作夹具/诊断记录，未改预算/产品reader；不是产品缺陷RED。最终109新＋原169限额/79book/186capacity/153 L0同五模块，双版各696 passed/0failure/error/skip/0warnings，唯一集合相等、compileall/diff通过，主线程review，无代理。

所有测试串行，17430/74660均exit0后才写文档；源码/测试SHA跨双版不变，详细JUnit/失败证据见台账。简化为新模块直接委托原_sources_snapshot而非复制execution观察选择；原生费用/档位/钱包/准入状态机未复制。合成历史capacity reader数据不声称当前SDK testnet签名通过，原collector的底层fake SDK覆盖/真实签名拒绝单独保留；没有实际账户/行情/订单请求、研究绩效或真实配置/权限/规则变更。

book_bound_to_original_check仅是最终原owned视图的关联；source_collection_owned/book_origin_verified/economics_complete/native_admission_verified仍false，不保证视图释放后无新并发/服务器变更。下一步接实际Engine/受控prepare的自采所有权及完整金额，再原L0/L1/L2/全执行reader/HTTP/default逐单消费，保留P/N待选与所有原阻断。没有将此只读关联提升为完整S3e/C5/C6/C7或缩小/关闭Goal。

## S4 默认 CLI 多市场合成 E2E 与发布

沿真实 RunTradeCycle/RunTradeStage，fake 最底层原生运输，验证 Binance/OKX × one_way/hedged × 多市场的账户/准入/意图/恢复链。只有全部新风险入口不可绕过消费者后，才有条件替换原常量阻断。
完成适用完整/双解释器回归、源码/迁移/支持矩阵、Lore/精确提交/远端身份核验；缺外部认证仍 disabled，C7 和完整版 Goal 不因 S1 或某个场景 PASS 而关闭。
