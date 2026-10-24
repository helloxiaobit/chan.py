# 逐单资金能力：依据、设计选择与待冻结项

日期：2026-10-24（Asia/Shanghai）。基线：已推送且clean的 `97e91a0cee8bc7c3ba1580721a1252bce57dafbe`。

状态：**用户已明确批准A“本地模型＋原生额度”方向，并于2026-10-24另批准[算术§2](2026-10-24-binance-capacity-arithmetic.md)路线P“接受明确的V1价格假设”；完整输入/金额模型尚待冻结、实现和验收**。两项已有批准不再重问；P只允许文中具名0.15%及明确费用估价，不包含隐藏缓冲、默认费率或运行权限。本稿不修改实际配置、既有政策、候选、来源/订单历史或任何交易门禁；不宣称资金充分、原生锁额、真实接受或C7认证。

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

## 3. 已确认的设计选择及未选路线

### A. 明确本地金额模型＋适用的原生数量额度（已批准）

允许平台专用、版本固定、可独立复算的**客户端资金风险模型**作为资金门槛的一部分；有适用原生本单数量额度时再交叉核对，不强行把两个平台归成一个简化公式。保持Binance优先，而不是为了已有OKX接口跳过Binance。

采用此方向，后续必须先冻结完整算术与输入契约，再做依赖它的TDD。模型至少交代本单两单位数量、role/方向/持仓模式、限价或有证据的价格假设、开仓损失、当前费率及费用币、杠杆/档位/订单后暴露、已有持仓与挂单的覆盖。无已批准的具名价格政策或原生依据、缺适用费率/档位或未知组合时拒绝；不把缺项设0、用返佣增加可用额、按比例猜分旧预占，或将已反映在native available中的旧挂单再扣一次。

“模型足够”只指**给定版本与已核输入下**通过本地资金规则，不改称服务器锁额、服务器必接单或对未来价格/费用/资金费无条件保证。价格假设、风险缓冲或模型支持范围中的实质新选择须明确展示，不得借本方向批准自行增加默认系数或放宽原规格。A批准时尚未冻结具体价格/费用算术；其后路线P已单独批准算术§2的具名估价，完整输入/费用币/余额及原CAS消费仍需实现验收，本稿自身不是完整资金公式。

### B. 仅接受交易所原生本单额度（未选，保留决策背景）

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

## 5. 原选择稿交付的实际范围（历史）

本次只形成上述代码/官方证据审查和设计选择，未新增任何资金代码、测试伪PASS、政策默认值或可执行契约。验收使用文档链接/路径、内容边界、diff与精确Git身份检查；生产代码与依赖未变，复用97e91a0已记录的适用测试证据，不冒称本轮重跑368项或完成资金TDD。

## 6. 批准后首个独立输入子层：Binance原始资金参数（实施前冻结）

从clean的4d31915a39944df956665c3303ee8ed04d778fec继续。先补金额模型必需而现有来源缺少的输入，不提前定义或计算资金充分、assumed-price/缓冲、返佣收益、费用币转换、档位系数应用或本单占额。完整金额算术仍须先冻结再实现；本输入子层不替代它。该输入层交付时原Goal工具仍为blocked，未代用户改为active或另建缩小Goal；当轮直接批准的范围内工作继续。

最小文件范围为Trade/NativeCapacityEvidence.py与对应测试，不修改原来源/订单schema、原状态机或默认入口。复用AccountIdentity原私有环境/账户身份、ExecutionFacts精确数字边界及NativeMarketEvidence的声明池/SDK身份。没有适合复用的原始JSON数字token读取体时，仅在新来源内处理该传输差异，不从训练流水线引入金融依赖。

- API：collect_binance_capacity_evidence(exchange,markets,*,mode,max_age_ms,max_observation_span_ms)及verify_binance_capacity_evidence(document,*,max_age_ms,max_observation_span_ms)。两个预算均必填typed非负int，无默认值；以最早started_ms计年龄，采集整窗计跨度，最终reader/本地核验成本另外包含在使用年龄内。恰界允许、超1ms拒绝。独立reader只重算/检时，不GET、改client或写库；调用者重封的字节不构成自采/准入能力。
- 仅binance/binanceusdm、声明池USDT线性swap；明确模式与原实际SDK类/私有路由/TLS。固定顺序为feeBurn一次，然后按声明池排序逐symbol的commissionRate、symbolConfig、leverageBracket。每项GET均由原账户身份GET前后包围且全部身份相同，总调用数为3×(1+3N)，超过原MAX_REQUESTS=128在任何GET前拒绝。无POST/修改账户/加载metadata或bracket cache补缺；不将SDK返回成功当服务器认证。
- 以[当前官方账户API](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account)和本机CCXT4.5.89为解释依据：只保留feeBurn；symbol及maker/taker与可选rpi费率；symbol/marginType/isAutoAddMargin/leverage/maxNotionalValue；symbol/可选notionalCoef及每档完整bracket/initialLeverage/notionalFloor/notionalCap/maintMarginRatio/cum。缺必需字段、错symbol、重复/额外响应行、非有限/布尔金额拒绝。可选RPI或coef缺失保留缺失，不补0或1。负费率原样记录，不将其作为可用资金。
- Python版CCXT原JSON解析可能将原生小数token转成float；不能str(float)冒称精确原始金额。因此在同一原生调用返回后、任何后续GET前读取其保留的原始HTTP正文，用标准库parse_float=str保留token；与该SDK实际返回对象重新解析比较，重复JSON键/非有限数/不匹配/缺正文/禁用正文保留均拒绝。只发布白名单字段，不存完整正文、原生账户标识、签名、headers、凭据或错误体；浮点金额不得直接进入原精确数字helper。
- collector限定原SDK对应native方法及所选request/fetch/JSON解释路径，fake仅替换最底层session.request；读取后再核原环境/选定client身份。SDK内部重试有效值必须为0，不替用户修改options；这是选定路径检查，不是整个宿主/传输库可信证明。原生参数无生成时间，source_ms=None、clock_kind=local_request_window_only，不能用本地GET时间伪装服务器更新时间；多项观察不原子，后续CAS仍必须自采绑定并核跨来源时差。
- 输出只为chan-binance-capacity-evidence-v1，economics_complete/native_admission_verified均false；fee_currency与可分配金额未知，不应用notionalCoef、不推断feeBurn关闭即费用充分。纯模型、独立复算、原L0/L1/L2、全部执行reader和HTTP/default接入仍是后续独立验收；旧资金/claim阻断不变。

TDD先观察缺API失败，再实际原SDK＋底层fake的非空两symbol响应逐字段验收；覆盖精确数字token、原生列表/对象、缺项/错币/多行、费率/档位/开关、全私有路由/原账户变化、显式预算/最终reader耗时、原始正文不匹配和异常脱敏。测试不访问真实交易所，不以空仓/零费用或新配置代替缺失金额契约。

### 6.1 本输入子层离线结果与限制

186项新测试，双解释器同六模块各903 passed/0failure/error/skip/0warnings，用例集合差异0，compileall/diff通过，具体身份见[开发台账](../reports/2026-10-20-crypto-full-version-progress.md)。复用原数字/账户/声明池边界；JSON额外保护限制正文1MiB、每symbol最多128个完整档位，不悄悄截断。原始档位系数只保留，不乘入cap、floor或cum；本层也不证明全部档位连续覆盖或任何金额足够，后续纯模型仍须按冻结算术独立核验。

真实原SDK签名/HTTP解析路径＋fake session运输发现：本机CCXT4.5.89默认Binance Futures testnet/sandbox签名在运输前NotSupported；正向只覆盖live模式的离线fake，没有真实live请求。另两项测试保留默认testnet拒绝，不写disableFuturesSandboxWarning、不切demo、不改现有工厂或配置。该SDK限制不等于交易所所有测试环境不存在，也不把旧fake-native-method PASS改称签名/真实服务认证。

完整金额算术/独立非空持仓及partial/pending复算、受控prepare→原CAS自采绑定、L2/发送/所有reader/default、OKX与C7仍未完成。本文件方向批准已记录，不再标为待批；完整Goal没有因此完成或被替换，该输入层交付时未代为恢复blocked状态。

## 7. Goal续行后的book算术与新的价格选择

用户续行后原工具已为active，原C0–C7目标与全部门禁保留。新的[算术规格](2026-10-24-binance-capacity-arithmetic.md)第1节已给出并实现全部已提供持仓/普通挂单的带符号腿包络及候选投影，79新、双版同六模块各721 passed/1既有skip/0failure/error/0warnings；只用精确Fraction及原解析体，不计算可支付额。第2节另明确P/N价格差别：P会接受具名FAQ估价而不是原生执行上界，必须专门确认；方向A不是这项放宽的批准。未回复不编码alpha/费用估价或放宽原边界。完整费用/档位/余额判断与受控CAS绑定仍未完成，不能把book增量为0当成资金免费或Goal完成。

接续只实施不依赖价格放宽的[限额必要检查§4–5](2026-10-24-binance-capacity-arithmetic.md)：原capacity reader前后复核，源自己的markets/config→原book计算→native配置cap及当前L兼容cap两条约束，完整档位不排序补洞，非中性coef继续拒绝。169新，双版同三模块各434 passed/0failure/error/skip/0warnings；这是provided-book限额诊断，book_origin_verified及两个资金/admission flags均false，无新的费用、价格假设、维持保证金、原生额度锁定或账户/CAS绑定。完整价格/费用币/余额和原受控入口仍待，不从此子项结束完整A路线或Goal，详见审计§33。

## 8. 原持久check到计算输入的只读关联

已按[算术规格§6–7](2026-10-24-binance-capacity-arithmetic.md)新增NativeAccountLimits，调用者不再提供positions/pending/mark/mode/config，改从被原L0前后复验的原SQLite check及独立market派生，并用同一total/skew政策校验capacity整窗。109新增、双版同五模块各696 passed/0failure/error/skip/0warnings，见审计§34。这是必要的数据适配，不是资金闭环：source_collection_owned/book_origin_verified/economics_complete/native_admission_verified均false，未接原prepare自采/真实本单、完整费用/余额/价格或原CAS金额消费。合成历史reader输入不认证真实SDK采集/服务，P/N未答复不写估价；原默认资金/claim/HTTP与C7门禁保留，完整Goal继续active。

## 9. 当前：P已专门批准，原prepare只完成raw自采绑定

用户已明确答复“批准路线P：接受明确的V1价格假设”，当前状态以首段及算术§2为准，旧分段的“P未答复”只是当时记录。无需重问A或P/N；允许按具名V1固定0.15%及已列费用估价，不获得服务器价格上界/资金锁/实盘许可。

显式新受控入口现从原prepare同一SDK自采capacity，并在原SQLite CAS写binding-v3；原v2不新增GET。历史as-of、当前年龄/联合窗口、末尾完整owner/client/原ledger核验分开，85新增及双版同15模块各2059 passed/0failure/error/skip/3既有AUC警告。见[绑定规格](2026-10-24-native-capacity-prepare-binding.md)、审计§35/台账。参数自采不是完整本单成本：raw费用币/coef仍不应用，economics_complete/native_admission_verified=false，原资金/claim/默认阻断不变。下一步整合fresh Last/费用币依据、V1成本及独立复算、原L1/L2和全部执行reader，不以更多独立诊断替代这条完整路径；OKX/S4/C7与整个Goal仍未完成。
