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
