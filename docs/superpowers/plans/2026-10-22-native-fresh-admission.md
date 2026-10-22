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

## S3 原 intent/CAS 与 HTTP 每单消费

文件：CCXTTradeEngine、OrderAudit、db_util 及对应原状态机回归。

- 新证明版本绑定账户/模式、DB、候选/部署/配置/代码、role/qty/price 与全部 source IDs；持久化原 intent 引用。
- 新增 NativeAdmission/NativeMarketEvidence 目前未纳入旧模型/部署/输入/paper 的指纹列表，也未被默认入口消费；S3 必须显式版本化并绑定新消费者及依赖源码，不能假设旧 workflow SHA 已覆盖它们，更不能重封旧模型/部署/订单来续用旧授权。
- 网络在 SQLite 写锁外；原事务内复核历史/投影/reservation/年龄，原 claim 和 HTTP 前再核 route/account/kill/candidate/freeze/实际意图。
- 跨连接并发、claim 前后漂移、超龄、原生未决预占不一致不发送；已 claim/unknown/submitted 不退回可重创，不重封旧契约。
- 旧恢复/查询/撤单/降风险路径继续按原门禁工作，不要求补造已消费模型。

## S4 默认 CLI 多市场合成 E2E 与发布

沿真实 RunTradeCycle/RunTradeStage，fake 最底层原生运输，验证 Binance/OKX × one_way/hedged × 多市场的账户/准入/意图/恢复链。只有全部新风险入口不可绕过消费者后，才有条件替换原常量阻断。
完成适用完整/双解释器回归、源码/迁移/支持矩阵、Lore/精确提交/远端身份核验；缺外部认证仍 disabled，C7 和完整版 Goal 不因 S1 或某个场景 PASS 而关闭。
