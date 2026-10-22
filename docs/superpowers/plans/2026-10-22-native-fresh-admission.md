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

## S3 原 intent/CAS 与 HTTP 每单消费

文件：CCXTTradeEngine、OrderAudit、db_util 及对应原状态机回归。

- 新证明版本绑定账户/模式、DB、候选/部署/配置/代码、role/qty/price 与全部 source IDs；持久化原 intent 引用。
- 网络在 SQLite 写锁外；原事务内复核历史/投影/reservation/年龄，原 claim 和 HTTP 前再核 route/account/kill/candidate/freeze/实际意图。
- 跨连接并发、claim 前后漂移、超龄、原生未决预占不一致不发送；已 claim/unknown/submitted 不退回可重创，不重封旧契约。
- 旧恢复/查询/撤单/降风险路径继续按原门禁工作，不要求补造已消费模型。

## S4 默认 CLI 多市场合成 E2E 与发布

沿真实 RunTradeCycle/RunTradeStage，fake 最底层原生运输，验证 Binance/OKX × one_way/hedged × 多市场的账户/准入/意图/恢复链。只有全部新风险入口不可绕过消费者后，才有条件替换原常量阻断。
完成适用完整/双解释器回归、源码/迁移/支持矩阵、Lore/精确提交/远端身份核验；缺外部认证仍 disabled，C7 和完整版 Goal 不因 S1 或某个场景 PASS 而关闭。
