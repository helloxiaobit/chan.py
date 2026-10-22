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
