# 原受控prepare自采capacity的诊断绑定

日期：2026-10-24。基线56af5077266e1243cb74b6f7276ddfb4a678e74e已推送且clean；原完整C0–C7 Goal保持active。沿已批准的[资金方向](2026-10-24-native-per-order-capacity-design.md)与[账户串行协议](2026-10-23-native-per-order-admission-protocol.md)实施，不重问已有批准。本步起始P/N未回复，续行中用户已批准P（见§4）；本raw绑定仍不增加价格、费用、余额或逐单资金规则，后续金额模型另验收。

## 1. 原入口与新诊断版本

新增显式acquire_binance_capacity_prepared_diagnostic_intent，与原acquire_native_prepared_diagnostic_intent共用原实现体；新入口另要求capacity_max_age_ms/capacity_max_observation_span_ms，typed非负int，无隐含预算。仅Binance USDT线性永续；原入口不新增GET，继续写binding-v2。新入口写chan-native-prepared-intent-binding-v3，仅在原字段上增加capacity_evidence及capacity_policy（max_age_ms/max_observation_span_ms）。不收caller source文档、book、PASS或client替代品。

实际顺序为原prepare身份→instrument自采→同一实际SDK的capacity自采→原components采集/持久check→原L0→原intent CAS。cap source由现有collector自己发GET/读精确正文，原SDK方法/零retry/环境/账户/输入/窗口检查保持。cap账户、SDK、完整市场池和配置与本次components/check必须一致；复用NativeAccountLimits配置/联合窗口核验，把cap整窗与finish加入同一total/skew政策。所有GET在SQL writer锁外，原账户全ledger/整行/前缀与唯一intent增量仍由原代码消费；不刷新旧基线或补ACK。

新版本只绑定raw资金参数与实际prepare量价身份，不把mark补成未知执行价，不输出本单金额/可支付额、source通过即金融通过或新可执行CCXT契约。LIMIT/MARKET原price/None保持原义；原chan-native-cas-order-v1及transition-v2沿用且非可执行，claim/HTTP/default继续拒绝。feeBurn/coef/缺项的raw事实不被应用为费用/档位充分条件，价格/金额缺口仍留给完整模型，不把本诊断步骤当其验收。

## 2. 历史、当前与原owned身份

同次所有权只由原Prepare._PREPARED活context和实际Engine/SDK/guard/DB维持，不由新增JSON布尔授予。v3的raw source及显式policy持久在原不可变intent事件/引用中；原client摘要、原真实request/contract/配置/候选/源码字段和L0引用均保留。原L1当前检查、冷SDK初始化与历史decoder认识v2/v3，不重写旧版本或变更表；旧v1历史支持保持。

capacity历史核验需要**以原journal intent_ms为时点**验证当时age/span及联合窗口，不以今天的时间把正常旧事件读成资金fresh。最小提取原capacity reader的内部at-time体；公开verify_binance_capacity_evidence接口仍只用真实当前钟，不接受caller checked_at，时钟采样仍在原reader末尾。历史体必须给明确checked_ms，所有实际current/CAS路径给真实当前时点；as-of只证明历史关联，绝不续期来源。旧source/订单字节不重封，SDK/码时代不支持继续拒绝；原v2历史不补造cap字段。

原windows和historical decoder从原check/scan关联取真实execution observation窗口，复用原AccountLimits联合规则。新cap collector/reader及共享绑定代码进入实际prepare implementation指纹；原当前性检查、L0/L1/L2都保留精确码/SDK/输入时代，码漂移不会因历史可读而自动可用。

## 3. 最小重构与TDD

先保护原入口与非空原SQLite fixture，按原TDD观察新入口缺失RED，再实现。重构限于：原acquire函数体提为一份私有共同体；旧包装不启用capacity，新包装显式启用；reader增加严格v3字段与原时间/身份链接，复用原数据/窗口，不复制金额公式或另建状态机。capacity reader仅提取末尾时间参数化的内部体，公开调用顺序与当前钟语义不变。v2/v3的cold/current消费者共用原身份/源码检查。

测试需真实原Engine、原CAS/不可变journal、非空两币partial/费用/资金费，LIMIT/MARKET与持仓模式/多空；正向的新capacity GET必须经过实际原SDK签名/HTTP/JSON与底层fake session，不用替换native getter伪造所有权。SDK默认Futures testnet签名拒绝保持，不改disableFuturesSandboxWarning或切demo。live模式正向仅为隔离fake对象/临时配置/显式fake环境字典，不改真实配置/os.environ，也不构成live授权或C7认证。

测试夹具扩展计划：给既有venue_engine/native_order_case增加仅测试使用的execution_mode参数，默认仍testnet；live分支在创建任何历史事件前明确使用fake live配置/解锁字典，完整历史同模式，不改已接受收据。新fixture把已声明raw数据供应器接到最底层HTTP，恢复SDK原native方法与fetch链，禁止所有额外URL/POST/实际运输。原testnet夹具/既有输入和行为回归保持。

反向覆盖缺预算/错误模式/外层事务、caller packets、原native方法/路由/预算/字段/身份/配置变化、源码/真实行/ledger/冻结/原CAS并发与事务回滚、失效/重封cap及历史as-of与当前区分。缺来源不写intent，已知账户失败沿原publisher保持sticky，不声称未知库已冻结；原record/unknown不释放。双解释器适用完整组合、旧实际产物/reader、compileall/diff、主线程review、Lore与精确提交/远端核对后，仅记录这一诊断绑定完成。

完整金额模型、原L1/L2金额消费、完整HTTP/default、OKX/S4/C7与整个Goal仍未完成；未经新的明确价格依据/授权不得用本raw诊断移除资金阻断。

## 4. 本轮续行与局部收尾计划

用户本轮已专门批准算术§2路线P；这是后续具名V1估价的授权，不把本raw诊断改为金额通过、原生价格上界或真实交易许可。该批准在价格/资金规格单独记录，不改变这里的新版本职责。

历史as-of与实际current必须分别调用内部明确时点体和公开末尾当前钟reader；当前联合校验另以typed monotonic向上整毫秒上界覆盖新增解码/绑定成本，无额外末尾业务clock回调、无epsilon或默认预算。5项成本/非法钟RED已有零成本同输入GREEN前置，不能用其他失效规则遮蔽。局部复用计划是让_capacity_links返回其已建立的单份window values，末尾只调用原AccountLimits._windows再次核scalar预算；不重复构造数据或金融模型。原v2路径不采capacity、不增加该新计时分支。

末尾source reader业务钟新增了回调边界，2项真实RED证明current/CAS会漏掉随后client漂移。修复/清理计划：只在v3 measured尾段追加原caller的完整本地/owned检查；原current两次local重建体提为一个闭包，前两次行为不变，新增尾段第三次复用它，不复制模型/配置/cache公式。prepare/CAS尾段直接复用原weak context recheck及原_current整账本检查；所有回调结束才取monotonic上界，不能在最后SDK比对后再添业务钟。未获授可执行契约，cold未建立SDK前的窗口读取仍只是来源检查。

## 5. 离线验收与剩余边界

最终CPython3.14.2/3.11.15相同15模块各2059 passed、0failure/error/skip、3既有小样本XGB AUC警告；2059唯一用例集合差异0，7个相关源码/测试文件跨两版SHA256不变，双版compileall/diff通过。全部目标pytest已exit0才写结果文档，无并发/代理。85新增含原v2真实SDK底层fake无capacity GET、v3 LIMIT/MARKET与单/双向多空、非空两币partial/费用/资金费、原SQLite实际CAS回滚、历史过期重启/current/cold不续期、源/配置/原行/owner/时钟与重封拒绝；详细失败/最终产物在开发台账和审计§35。

正向cold必须在绑定前由原受控初始化建立allowlisted SDK；故意带private_unused字段的旧warm cache不能被历史绑定后删字段重建，仍拒绝且不改旧证明。最初无fake ticker handler和cold基线差异仅作夹具定位，未放宽产品校验。SDK默认Futures testnet签名拒绝保持，live-mode仅隔离fake配置/对象/环境；本地SDK签名调用路径不等于服务端签名认证或C7。

主线程按review模板核原数据/码/SDK/身份/窗口/兼容/错误和权限，raw有限子项可提交，生产就绪=否。没有新表/金融公式/依赖，未改实际配置/权限/规则/candidate/旧产物或研究数据，未请求真实账户/市场/订单、未读正式绩效。完整V1资金与fee币/Last证据、原L1/L2金额消费、全部reader/HTTP/default、OKX/S4/C7继续待；原完整C0–C7 Goal保持active，不从本子项关闭或缩小。
