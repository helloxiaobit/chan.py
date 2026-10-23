# 逐单资金能力：依据、设计选择与待冻结项

日期：2026-10-24（Asia/Shanghai）。基线：已推送且clean的 `97e91a0cee8bc7c3ba1580721a1252bce57dafbe`。

状态：**设计选择待用户确认；没有批准或实现新的金额公式**。此稿不修改实际配置、既有政策、候选、来源/订单历史或任何交易门禁；不宣称资金充分、原生锁额、真实接受或C7认证。

主Goal仍按[完整版计划](../plans/2026-10-20-crypto-full-version-completion.md)完成C0–C7，Binance USDT线性永续优先、OKX随后、股票延期。[账户级串行/原CAS协议](2026-10-23-native-per-order-admission-protocol.md)已经批准，不再请求同一批准。本稿只处理该协议明确另留的“逐单资金能力”设计决定。

## 1. 当前代码证明到哪里

- `NativeAccountReconcile._margin` 返回原币原生可用额、汇总挂单预占及 `per_order_allocation=not_inferred`，不输出本单可分配金额。初始原生组件支持明确的cross账户；未知账户模式、外币保证金/借贷等不因本稿放行。
- `NativePendingOwnership`/原完整账本能证明既有订单归属；已批准的原CAS限制同一稳定账户仅一个未被原生完整观察的新风险意图。这解决本地重复占用，不会把账户汇总额变成某单的资金证明。
- `NativePreparedIntent`/`NativePreparedClient` 已绑定同次自采、原L1和完整SDK/输入基线；新GET不续旧来源，仍是不可执行诊断。`CCXTTradeEngine` 的原资金拒绝及v2 claim阻断均保留。
- 本机CCXT为4.5.89：`binance.load_leverage_brackets(reload=False)` 可以直接使用options缓存；保存的投影只有floor/maintenance ratio，不能从它补造fresh的完整cap/initialLeverage证据。Binance/OKX通用fee方法也可能在缺markets时调用loader并按类型选择路由，不能直接视为本轮固定产品的自采协议。
- 已实现的执行历史commission说明过去成交实际费用，不等于拟提交单当前费率；`maxWithdrawAmount`亦不是本单可下单金额。原C4/paper的明确软件资金模型不能冒称交易所原生规则。

## 2. 本次核对的官方依据及其限制

仅阅读公开文档和本机SDK源文件，没有调用行情、账户或订单端点。

1. [Binance开仓成本说明](https://www.binance.com/en/support/faq/detail/87fa7ee33b574f7084d42bd2ce2e463b) 将初始保证金与开仓损失列为成本项，区分方向及限价/市价，并列出assumed-price示例。页面标注2026-07-08更新，同时声明教育用途且信息可能过时。因此不能把示例中的0.15%偷偷设为全市场/全订单永久默认值，或只保留“名义额÷杠杆”便宣称完整资金能力。
2. [Binance保证金说明](https://www.binance.com/en/support/faq/detail/4f83b65d83654b5e933f85ef12bf769d) 区分one-way/hedge、已有持仓与挂单，另列订单后名义额/杠杆限制。条件单的触发语义不能按普通挂单机械套用；本次不同地区页面摘要对检查时机的表述不同，不能凭搜索摘要定版。该FAQ也有可能过时的声明。
3. [Binance账户API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account#user-commission-rate) 提供symbol级费率GET；同页symbolConfig提供当前杠杆/名义额上限，leverageBracket包含账户调整相关字段。这些是不同用途的观察，费率或名义额上限都不等于本单可支付额，缓存bracket也不能代替fresh raw来源。
4. [OKX最大下单数量](https://www.okx.com/docs-v5/en/#trading-account-rest-api-get-maximum-order-quantity) 提供Read权限GET `/api/v5/account/max-size`；衍生品返回合约张数而非USDT金额。多标的查询会忽略px，省略价格有平台默认行为；必须将单一标的、明确px、杠杆、tdMode、账户/方向与本单绑定，不能套到Binance。该观察仍不是资金锁。全页open因超过工具大小限制失败，本次通过官方定向检索核对上述片段，未声称全文验收。

结论是证明范围的判断，而不是“所有平台都没有某接口”：目前核对的Binance资料尚未提供可直接绑定原CAS的只读本单资金锁/完整数量额度契约；如果后续找到权威接口，须另核字段、单位、覆盖及原子性，不能从搜索未命中推断不存在。

## 3. 需要用户确认的一项新设计选择

### A. 明确本地金额模型＋适用的原生数量额度（推荐方向）

允许平台专用、版本固定、可独立复算的**客户端资金风险模型**作为资金门槛的一部分；有适用原生本单数量额度时再交叉核对，不强行把两个平台归成一个简化公式。保持Binance优先，而不是为了已有OKX接口跳过Binance。

采用此方向，后续必须先冻结完整算术与输入契约，再做依赖它的TDD。模型至少交代本单两单位数量、role/方向/持仓模式、限价或有证据的价格假设、开仓损失、当前费率及费用币、杠杆/档位/订单后暴露、已有持仓与挂单的覆盖。无已证明的价格上界/适用费率/档位或未知组合时拒绝；不把缺项设0、用返佣增加可用额、按比例猜分旧预占，或将已反映在native available中的旧挂单再扣一次。

“模型足够”只指**给定版本与已核输入下**通过本地资金规则，不改称服务器锁额、服务器必接单或对未来价格/费用/资金费无条件保证。价格假设、风险缓冲或模型支持范围中的实质新选择须明确展示，不得借本方向批准自行增加默认系数或放宽原规格。当前尚未冻结具体价格/费用/档位算术，本稿不是可直接编程的资金公式。

### B. 仅接受交易所原生本单额度

不允许本地金额模型作为资金门槛的充分组成部分，只接受可与本单完整绑定的原生数量/金额额度，并继续原账户/账本/时效与原CAS核验。不能把测试单POST、预检查成功、maxWithdraw或汇总available替代成额度。

这更少依赖本地金额假设，但当前尚未取得Binance对应的完整契约；其新风险资金门槛将继续拒绝，不能改成OKX先完成后关闭原Goal。若没有后续权威来源或外部选择，此路线不能承诺现有Binance范围何时开放。

两种路线均不审批真实I/O、配置/权限变更、资金使用、candidate重臂、解除默认阻断或C7。人工额度/固定杠杆/全额抵押、fee默认0和宽松epsilon不作为第三条替代路线。

## 4. 方向确认后的实现与验收边界

以下为依赖顺序，不是已有实现或完成证明。

1. **冻结金额或原生额度契约。** 按平台/模式列每一输入的原生字段、单位、来源与不可推断项；列方向/订单类型/持仓与挂单的完整算术、舍入、恰界及不支持分支。明确本地模型与平台规则之间的证明限制，不把FAQ示例当全部平台保证。
2. **原生来源。** 在现有模块结构中确定最小新增文件，不提前搭空壳。若选A，预计需要Binance fresh fee/bracket/symbol settings及必要价格来源；OKX仅在适用时取得单标的明确参数的max-size。复用环境/SDK/finite/canonical边界，所有GET锁外、必填age/span/skew、无自动重采或loader/旧cache补缺；观察仍不输出准入。
3. **纯计算/独立复算。** 复用已有精确数值及单位工具，不引入依赖或第二套账户/订单状态机；手算非空两币夹具与独立参考计算逐项比对，不只同函数生成expected/actual。不足、恰界、费用币/符号、价格假设、档位两边界、partial/pending/unknown、one-way/hedged/方向与缺项均先RED再最小GREEN。禁止为得到可过用例而退回空仓/单币/零费用。
4. **同次受控绑定。** 原prepare→来源→完整对账→资金评估→L0→原intent；结果必须携带实际本单与全部依赖身份，不能消费caller自封金额/receipt/PASS。原L1/L2依照唯一合法整行增量重核，不排除自身或第三方行，新GET不能续原证明。
5. **完整消费后才讨论新执行版本。** 新契约的query/ACK/累计成交/pending归属/恢复/reduce-only及源码/加载runtime指纹逐项接原共享核算体；在完整HTTP前复验/default全入口和离线CLI E2E之前，原v2 claim/默认阻断保持。失败和未知不释放、重创或补ACK。
6. **交付。** 双解释器适用回归、原实际产物兼容、compileall/diff、主线程审查、Lore/精确提交/非强推/远端身份核对。C7仍依赖必要外部授权，fake PASS不能替代；S3/C5/C6/C7及完整Goal不因资金子层通过提前结束。

## 5. 本次交付的实际范围

本次只形成上述代码/官方证据审查和设计选择，未新增任何资金代码、测试伪PASS、政策默认值或可执行契约。验收使用文档链接/路径、内容边界、diff与精确Git身份检查；生产代码与依赖未变，复用97e91a0已记录的适用测试证据，不冒称本轮重跑368项或完成资金TDD。
