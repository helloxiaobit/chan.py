# 同一金额意图进入原claim/L2与执行链

基线pushed/clean `436c011cda223da4f9970cbc1a6d5067dff0b646`。[消费者计划](2026-10-25-native-monetary-consumers.md)第2步终态释放及第3–4步仍未完成；继续[已批准账户协议](../specs/2026-10-23-native-per-order-admission-protocol.md)§4.3–4.4，不重问A/P/F，不改变C0–C7目标。上一轮是实际进展，Goal active。本轮严格主线程串行/fake，不用代理/OMX/新依赖，不改真实配置、权限、候选/研究/测试网/实盘门禁，不调用真实端点。

## 结果与非目标

同一个source-owned v4/client-order-v1由原Engine消费，经过原L1→原claim唯一增量→L2，再经锁外HTTP前的全部原来源、金额、SDK/runtime/输入/安全门槛复核。ACK/累计成交/查询/取消/恢复和完整原生观察仍走原状态机；未观察状态不能凭本地terminal/空pending/TTL释放。不是另做可丢弃诊断、第二资金/订单引擎或默认金额/预算。

旧v2/v3诊断不可借此升级，旧契约字节/原恢复仍保持。开发过程中先留原公开claim/send阻断；待全部消费者实现且fake联合矩阵可执行后，才在该完整变更中评估软件路径，不加caller PASS、permit/config开关或测试专用通路来绕过。无正式C7认证仍不能宣称测试网/生产就绪。

## 修改前复用/清理计划与依赖顺序

1. **真实主路径RED。** 新`tests/test_native_monetary_execution.py`复用非空双币原SQLite/原SDK准备夹具，底层Session同时处理已有GET与真实原SDK产生的POST。先实际acquire v4，再原Engine.place_order，期望原L2/原ACK/正确两单位HTTP和不重下；首次必须因现有资金消费者阻断而RED，不把替身passed helper或手写claim事件当成功证据。
2. **原current校验共享L1/L2。** `NativePreparedIntent`保留公开intent checker返回None/原限制，私有共享体按原transition提供的精确阶段/after hash重建；`NativePreparation._local_prepare_view`只在原验证过的persisted hash模式接精确created/submitting状态，普通pre-intent与旧API不放宽。所有当前列、原来源、完整monetary、实现/SDK/cache/guard/clock/部署/候选和typed monotonic尾预算仍核；不能从原hash排除本单或按任意caller expected包重封。
3. **原owned claim。** 只由实际Engine/同一owned DB重建的弱引用活上下文供原CChanDB.claim/_order_write/NativeOrderTransition消费；不接受JSON/root/checked_ms。原L1与全部records/history/source/check IDs原样比较，再原CAS、唯一原claim/event增量、精确L2和尾窗口。原prepare活上下文与post-intent上下文不能互用/复制/跨Engine/跨库；不新增表或schema修补历史。正常public无活上下文仍拒绝新契约。
4. **HTTP前与原Engine全部消费者。** 扩实际契约/账户/执行参数/服务端回报校验的共享分支，而不是只加schema白名单。原SDK调用前最后以原owned view读L2和完整硬门槛，HTTP不在writer锁内。晚漂移拒绝并沿原sticky/unknown语义；已claim失败保持submitting，不回滚成created/重新acquire/重发。将新使用的方法纳入原运行实现闭包。
5. **真正终态/完整已观察释放及默认入口。** 对原query/cancel/ACK与execution/account联合来源保留不可变原生证据，不用本地status或缺单推断。下一新风险仍自己重新自采，原available反映旧预占，不能二扣。再接原运行壳/直接新风险默认入口的明确政策与before来源；缺声明拒绝，不改实际配置。不为已有风险管理强制新模型/新风险资金许可。

第3步边界复核的最小清理补充：真实RED已证明`claim`的本地stamp之后仍可在替换连接上开启savepoint，来源回调后`SqliteDB.transaction`还会向替换连接执行rollback并覆盖原domain错误。先新增原事务回归，再仅将同一个manager的BEGIN/SAVEPOINT/COMMIT/ROLLBACK绑定到进入时的实际connection，退出前拒绝owner替换；原writer在stamp后/读取回调后复核同一活owner。不恢复或采纳外来连接、不新建事务引擎；旧嵌套/外层回滚语义必须保持。该修补属于原L2原子性/零foreign-SQL验收，不扩展任何发送权限。

同一相邻`intent` stamp边界也已由实际v4流水线RED证实。复用原`_PREPARED`弱注册表，附加原owners回调供原writer在BEGIN之前调用；不新增registry、JSON字段或owner-only放行参数。私有未绑定/已绑定元组分别由3/4项变为4/5项，原identity与binding字节不变；Last的“尚未绑定”检查随内部布局调整，原完整consume/finish仍必需。旧schema不升级、不重封。

## 验收与交付

先小型RED→GREEN；完整假交易矩阵包含one_way/hedged×long/short×LIMIT/MARKET/GTX，双币非空/partial/fee/funding、真实原prepare→intent→claim→SDK最底层POST→ACK/累计回报→原生pending/execution/account→冷重启。新实际L2只能由原writer形成，不手工插入或mock成passed。双连接跨记录/市场/table竞争只有一个未知意图，原L0/L1/L2精确计数；来源/金额/代码/SDK/cache/guard/配置/冻结/末尾时钟与owner各边界变异均无额外HTTP，替换库零SQL。超时/异常/歧义/取消/重复回报不重创、不释放。

修改共享体重验受影响原范围，未变的公式/数据/环境证据可复用但不冒称新运行。双CPython3.14.2/3.11.15、CCXT4.5.89，GUID basetemp/JUnit、相同用例集合/源码SHA、compileall/diff/链接、主线程review、Lore/普通push/远端SHA。禁止活pytest期间编辑；原句柄超时或截断不重启。仅全部必需联合验收通过才可称本执行子链完成；C5–C7/OKX/整个Goal继续按原范围，未完成时保持active且诚实记录WIP。

## 当前未完成状态（2026-10-25，未提交）

### 第4步接线顺序（在修改原Engine前固定）

先补真实已有风险管理，不用发送门禁或新资金预算妨碍恢复：原SDK GET/DELETE底层fake＋真实原L2，核原Engine查单/撤单、累计量/原生leg/post-only/reduce-only回报、原账户及由开仓契约派生的降风险条款。新client契约除严格v3共有字段外还须匹配原DB实际记录、原immutable transition/preparation-v4及完整monetary_basis，不能只加入schema白名单；诊断v2/v3继续拒绝。非提交管理按原intent时点重读原证据，不续期旧来源，不因新风险freeze/kill或过期资金点而丢失已知订单管理；原SDK仍须核同一实际账户。

随后扩实际已加载执行callables/SDK与原HTTP前L2尾复验，最后才接原默认资金入口与完整终态证据。完整默认发送RED必须保留到这些依赖都完成，不直接改常量、加测试许可或用私有绕行来假装整链已通。管理reader的正向测试只证明其原生命周期职责，不充作新风险/服务器准入通过。

2026-10-26相邻ACK边界补充：真实原Engine查单已证实HTTP回调与ACK本地stamp均可换库，不能只在HTTP后检查。先保留RED，再扩原`_order_write.owner`已有检查：同时绑定进入时实际DB/connection/table，原ACK在其stamp之后、调用writer之前核同一owner。复用原CAS/append-only journal及已pin的事务manager，不增加新回报令牌或第二writer；旧恢复/状态机联合回归必须包含。

2026-10-26冷管理补充：4项真实默认恢复RED显示空SDK缓存会走sapi currency/通用market加载。仅对实际原L2/client-v1且`Engine.exchange=None`的管理路径，复用原NativePreparedClient模块、实际factory、原公共instrument collector与pure parser/set_markets，自取该原scope的base市场并核原账户；原记录/transition/配置/owner须前后相等。此管理初始化不调用新风险输入/资金/Last、不给任何年龄默认值、不续期旧L1/L2，也不改变已初始化SDK缓存。初始化后原Engine仍逐次核冻结账户和单位；kill/资金点过期不阻断已有订单查撤，但仍不能新开风险。新风险cold initializer及原默认发送阻断保持。

- 真实原writer已能用同一实际Engine/owned view的活上下文核L1，发布唯一原claim增量/L2，完整重算原金额与尾窗口；公开intent checker仍只接受L1。原默认Engine尚未生成/消费该claim句柄，不能说默认发送链已接通。
- 59项新claim专项＋79 Last＋10原事务＋18旧prepare/capacity/model用例，共166个唯一ID。3.14一次166 passed/2既有AUC警告；3.11先162 passed/4夹具失败，再修正夹具补跑4 passed，两组通过集合与3.14精确一致。不是“两版各一次166全绿”。15模块1253 passed/2警告仅属于修改private prepare注册表布局之前的中间源码，不能冒称最终版全范围复验。
- 真正L2→原ACK→原SDK解析实际native NEW→原零量report→pending owned已验证；ACK单独仍unresolved，不伪造成交/金额锁/终态。资金公式、旧wire/历史均未改，所有真实配置与candidate/testnet/live门禁保持。
- `tests/test_native_monetary_execution.py`完整默认Engine用例仍是1项真实RED，当前明确停在CCXTTradeEngine.py:509；未加xfail/skip/permit或手写成功L2来隐藏。故本计划及完整C5未验收，当前diff不提交/推送。原Goal active。
- 继续第4–5步：原Engine契约/账户/参数/回报/查询/取消/恢复、加载实现闭包、原L2的锁外HTTP前完整复验、原生完整终态/已观察释放及默认入口；全部真实fake联合验收及完整回归后，才评估软件常量阻断并按原授权Lore/push。详细source/JUnit及失败原件见[最新WIP台账](../reports/2026-10-20-crypto-full-version-progress.md)。

### 2026-10-26续行状态（仍未提交）

- 第4步的**已有风险管理**已补原金额契约/同账户/单位/参数/回报、查询/撤单/累计report/降风险条款与原L2 cold SDK初始化；原ACK/stamp/writer owner、投影降级与同SDK状态漂移有真实RED→GREEN。新增76项管理测试＋原204项订单回归，冻结源码双版各280 passed/0warning，case集合差异0；两个最终句柄均exit0。
- 实际Engine/原writer/cold/factory与装饰器真实closure进入selected runtime检查，但完整SDK执行闭包未完成。已有风险管理不会续期L1/L2，也不授予新风险提交或观察后释放权。原schema及金额公式未改；没有真实端点、配置、规则或交易门禁变更。
- 完整默认发送再次真实1 RED，仍在Engine.py:509且未到POST。原Engine活claim接线、锁外HTTP前完整L2/金额/来源尾复验、原生终态完整证据持久化/观察后释放和默认新风险入口尚待；不能用当前280通过冒充这些范围或旧全组合已在当前源码通过。故计划/C5–C7仍未完成，diff不提交/推送，Goal active；证据与源码摘要详见WIP台账2026-10-26节。

### 后续SDK执行校验的修改前复用/清理计划

先给真实monetary acquire/current/管理路径补SDK变异RED。复用NativePreparation的`_codes`/AST/fresh-compile/defaults规则，将已有函数校验体共享给明确的SDK下单构造、查撤、精度、签名、request/fetch、原order解析函数；原生GET/POST/DELETE order Entry同时核实际descriptor、closure以及安装源码的path/api/method/config，不仅比共享reference对象。仅v4金额实际路径调用，不将旧v2/v3诊断升级。准备夹具去掉create_order高层替身，仍只允许其底层Session fake处理请求。

不增加表/schema、第二SDK/资金引擎、caller PASS或可转移许可；不改实际SDK安装、配置或交易门禁。函数自身属于原本地实现闭包，全部原SDK检查必须在来源I/O前及原current末尾复核。已有L2的冷管理仍不依赖新风险资金/候选状态。明确列出的SDK执行路径不是整个Python进程的可信执行证明，未覆盖动态依赖不得冒称完成；默认发送RED保留直到整个计划验收。

### SDK声明路径的已验证进展（2026-10-26，WIP）

提交前格式清理限定：结构检查另检出旧WIP的test_native_monetary_claim.py与test_native_monetary_engine.py各一个EOF空行；仅删除末尾空白，不改逻辑/语句/参数。先后以双CPython编译完整code object摘要比对相等，证据台账区分实际运行字节与最终格式字节，不重标旧JUnit为新运行。

- 复用原fresh-compile校验体，核28个明确SDK方法及5个order Entry路由、真实MethodType/closure和安装方法名；来源I/O前、原current/claim及管理cold尾部复核。准备夹具已下沉到原Session fake，无高层create_order替身；旧v2/v3不升级，金额公式及全部交易门禁不变。
- 36项SDK专项有RED→GREEN证据；另有真实金额prepare12/default cold4/旧v2诊断4，最终双版各56 passed/219 deselected/0warning，唯一case集合差异0、18个源码摘要保持。中间186范围为3.11的185通过＋旧writer注入夹具失败后补验1通过，3.14一次186通过；中间68/186和上轮280均不是当前最终源码的全回归。
- 主线程review发现并修复DTO元数据冒充与共享SDK原函数错绑名称；不宣称整个Python进程/所有动态依赖受信。当前完整默认发送再验仍在Engine.py:509真实1 RED，未到POST。计划/C5–C7未完成，WIP不commit/push，Goal active。
- 下一步仍是原Engine活claim接线、锁外HTTP前同一L2/完整金额/来源窗口尾复核、原生终态完整观察持久证据和默认新风险入口；必须通过原fake联合矩阵及适用完整回归后才能评估移除软件常量阻断，不能用子层PASS或永久拒绝替代最终功能。原件/哈希/真实失败见台账SDK节。

### HTTP前原L2核验的修改前复用/清理计划

先以真实原writer形成L2、底层Session fake证明HTTP前consumer缺失，再最小接原Engine.create_order之前的调用点；完整默认发送门槛仍保留至本计划整体验收。新增consumer只收实际Engine/record_id，拒绝caller root/check/clock/expected/PASS；既不claim、重采资金、改订单、续期来源，也不返回准入对象。

复用原current读取体：原intent/claim private接口保持返回document，内部共享体另保留其本次原窗口的纯数据，供事务退出后继续按原Capacity/AccountLimits窗口核算；不复制金额算法或从ledger排除自身。原L2完整核验→锁外原native账户/执行设置核对→同一owned DB重读精确L2/全ledger/全部来源/原金额→原连接退出→原SDK/owner与monotonic尾段窗口复核，HTTP不能持writer锁。包含最后一次本地读取与原事务退出耗时，严格typed monotonic，不能用最后业务时钟续期旧source。

来源异常沿原_publish_unavailable在同一可证明owned DB发布sticky失败；换owner/不能安全写原库时只拒绝，不触碰外库、不声称冻结。claim后失败仍为submitting/unknown，不能回created、清意图或重发。本步骤是点时核验，不宣称封锁外部机器人或服务器余额。正向测试显式60000ms合成政策只用于完整核验fixture，不改实际配置或生产默认；过龄/尾延时/类型/输入/来源/账本/SDK/配置/owner变异必须实际拒绝。

profile晚漂移RED补充：原_observe_account内mode/leverage两次GET之间需核同一活owner；复用其原校验和返回，新增仅用于附加失败检查的私有_assert_current回调（默认None保持旧调用），由HTTP consumer内部捕获原owner传入，不作为准入输入/放行条件。异常发布仅需核原DB归属，不要求已失败的SDK仍合格；不能因SDK漂移而漏掉可安全写入原库的sticky失败。

最后local view RED补充：原final_check先核ledger再调用本地输入读取，若该读取回调改本单/其他行仍可能成功。仅在原本地读取之后补一次原Transition._current完整重读及owner检查，不能只比opening_inputs/SDK或忽略本单；原owned事务内发现变异并回滚。

入口runtime RED补充：在首次调用current consumer之前即执行原已声明runtime/SDK fresh-compile检查；拿到真实L2后再比冻结runtime。不能等可变consumer自己执行后才检查它，也不接受caller runtime对象。

### HTTP前子边界的已验证进展（2026-10-26，仍为WIP）

- 新`assert_native_prepared_claim_before_http(engine, record_id)`只消费真实原writer的L2，复用原完整current/window/金额校验；锁外核同一原生账户和mode/leverage，再在原owned事务中核精确L2与全部ledger，事务退出后继续核原monotonic尾预算。只返回None，不生成许可、不claim/续期/释放；原create_order之前已设调用点，但默认发送阻断未移除。
- 真实RED分别修复profile返回后的SDK/凭据/Engine变更、mode与leverage之间缺检查、最后本地输入回调后账本可变，以及首次调用current consumer前尚未核其实际加载实现。复用原_observe_account附加失败检查、原Transition完整重读和selected runtime，不新增金额模型、表或schema。
- 31项新HTTP专项双CPython用例集合相同且均通过；最终3.11一次31 passed，3.14一次69 passed（31专项＋38共享原claim/current/v2/v3回归），全部0failure/error/skip/warning。3.11的38共享体在最后入口检查修补之前已通过，不冒称两版最终各69全绿；旧280/56/4246也不重标为本次完整回归。19个源码/测试/未改基线摘要在最终运行及收尾检查间一致，双版compileall/diff通过。
- 完整默认发送最终仍1项真实RED，现位于Engine.py:513原资金消费者阻断（因新增检查移动行号），未到POST。没有xfail/skip、手写成功L2或caller PASS。全部仍只用fake，60000ms是显式合成夹具预算，不是生产默认或可用时延证明。
- 下一步仍需原默认Engine活claim接线、真正原生完整终态/已观察释放和默认新风险来源，以及完整fake联合矩阵/适用回归。该点时检查不证明服务器锁额或整个Python/SDK动态依赖受信；本计划、C5–C7、OKX和Goal均未完成，整组WIP不commit/push。详见台账HTTP节的失败原件、源码及JUnit摘要。

### 原生终态持久来源的修改前复用/清理计划

原query返回terminal只足够管理回报，不是账户完整观察证据；先以实际原L2→原SDK GET→原ACK路径写RED。复用原OrderAudit append-only事件表与原Engine查询，不新增表、资金账本或caller证明入口。仅新monetary开仓契约的实际原query可追加显式native_terminal_observation事件：保留白名单原生字段、同账户/原contract/原attempt、请求观察窗口及由原生行独立复算的两单位累计量/均价/条款。DELETE/ACK/空pending/本地terminal均不生成此证据。完整查询校验、SDK/原owner与原ACK仍不可省略，HTTP仍锁外。

原journal reader重建该显式新事件的全部派生字段与source hash；原旧事件data hash/字节、投影与CAS形状保持。新事件hash覆盖原state及其完整观察document，不能因state未变而丢掉更新的原生累计量。读历史不需要资金点fresh或网络；后续原native account联合reader仍须校验原execution覆盖/累计量、前后账户与现金流水，再据此判定已观察。仅原query来源持久化不释放预留、不清sticky、不授予新风险；默认发送RED与整个联合验收门槛继续保留。

联合reader的真实零量终态RED已定位到原三项未观察原因。只由同一实际journal最新原生终态与当前原累计report精确相符、在本次pending源开始之前且无同原生ID/client冲突时，标为已观察订单；不靠terminal字面值删除预留。显式发布pending ownership v3、account interval pending v4、components/check v3，沿原完整source/前缀/ledger重建；旧输入仍发旧版本，不回写旧check。原区间execution覆盖、现金/手续费/资金费与前后账户全部必过，失败仍sticky；current消费者必须调用该完整reader，不以schema集合替代重算。未证明完整联合范围前保留默认发送阻断。

原history的coverage也必须与新来源相符：只含旧事件仍保持v1原字节，含显式native terminal事件才发布history v2。先保护实际查询的版本断言，再把原read_history/verify_history_prefix、原transition的手工header与原execution/account reader复用同一个按实际事件选header的纯函数；不改原L1/L2的切片历史、旧check前缀或表。既有原journal回归随共享体复验，不能把新native来源仍标成“只有本地意图/报告”。

原终态publisher的stamp边界补充：先用实际OrderAudit时钟回调换DB/连接的RED，要求stamp之后不执行INSERT、外库零SQL及原ACK回滚。原_append复用额外失败检查回调，在其SQL/本地时钟边界核原owned owner；仅实际query内部传入捕获的owner，不将caller回调、JSON或时间视为来源/放行权。原普通事件和历史字节保持，不增加第二writer。

终态stamp还须为真正int、位于原source完成之后且非未来；在同一原事务退出前按原history reader重读新事件，不能先提交一份冷重读会拒绝的来源再返回成功。先以bool/float/倒退/未来stamp写RED，原ACK和来源必须共同回滚。原生SDK查询异常同样只保留域错误，不暴露服务端私有正文；不改变旧契约错误兼容路径。

金额/均价交叉复核的三项真实RED补充：原生累计量×均价须精确等于该行cumQuote，无隐含舍入容差；本区间逐笔已覆盖该单全部累计成交量时，沿原Fraction核算同时累加逐笔名义额，与原生终态汇总交叉比较，矛盾必须mismatch并保留原sticky语义。不是新增费用/价格模型，不以数量相等掩盖价格差异。只断言所提供区间已覆盖的事实，不把较早的区间外均价重建冒称完成；完整历史、执行全链和C7范围仍独立验收。

### 原生终态子边界的当前验收与未完成范围

- 新26项＋8个原联合/兼容模块，CPython3.11.15与3.14.2各448 passed、1个原Binance isolated cash channel skip，449个唯一case ID完全相同；28个源码/夹具基线＋8个原验收测试SHA在两版及收尾间一致。双版Trade＋10个WIP测试/夹具compileall、diff检查通过；所有测试真实结束后才写文档，不用观察超时/输出截断重启。
- 复用原journal、原ACK、原execution与Fraction账户账本；按实际event选择history header的共享纯函数消除手工重复。新来源/覆盖显式版本化，旧事件、切片和旧check保持；没有新表/资金模型/caller证明权。私有正文、非法时间、换DB/连接、重哈希来源变异及原生/逐笔名义额矛盾均有失败原件和后续GREEN。
- 源真实性与完整性仍限定为实际原查询及所提供账户区间：不补造较早区间外均价史，不断言服务器锁额或完整Python/SDK传递依赖受信。合成60000ms窗口、均价精确恒等式及fake结果都不是实盘精度/时延/生产认证。
- 默认发送单项复验仍1真实RED（原Engine.py:513、POST前），没有xfail/skip/成功L2替身或常量门禁删除。其首次PowerShell参数错误导致0 tests/exit4已与真实RED分开记录，未把启动失败计作行为证据。
- 下一步仍为原默认Engine活claim/完整发送fake链、默认新风险source与显式freshness接线、SDK闭包及适用联合回归；原门禁继续保留。累计27个WIP＝15生产＋10测试/夹具＋2文档，尚无commit/push；C5–C7、OKX和Goal均未完成，Goal active。详细失败/最终JUnit/36个源码摘要见进度台账本节。

### 默认输入壳的同次原生intent路由：修改前复用/清理计划

发送前置依赖尚缺默认add_trade的同次金额source/CAS，先补此实际路径，不提前删除常量。将原CTradeEngine.add_trade中的quota/prepare/原acquire小段提为原方法，后续rate-limit/place/report/通知不复制；CCCXTTradeEngine在非dry-run swap且已有原COpeningInputs时覆盖该小段，使用guard原配置文件中的trade.native_admission完整数据，不信trade_info中的来源、PASS或profile。缺失/多字段/非法policy/before/budget拒绝且不降级。

profile-v1只声明已批准边界的显式数据：schema、before_id、account_scope、policy，以及instrument/capacity/last各max_age_ms和max_observation_span_ms；不含enable/send/PASS，不新增金额规则或默认年龄。before_id仅引用原库实际native snapshot，必须经原source/account/ledger重建，不可用caller包或最新时间排名代替。cold时复用原initialize_native_prepared_client的L0分支；warm不刷新cache。随后实际原acquire_binance_standard_prepared_intent自采完整来源并进原CAS，再从原L1恢复实际精度化数量/价格/client用于原发送链，不能调用第二次legacy prepare或acquire。

先复用非空双币bottom-Session fake写RED：默认add_trade应落原v4/client-order-v1、完整L1/原金额来源，随后仍在原发送门禁拒绝、POST=0；缺profile/单字段预算/虚假before/caller profile均不产生新意图。原无OpeningInputs的旧v3兼容路径本子步不冒称已统一；所有直接新风险入口的最终无guard拒绝及其历史fixture迁移仍是发送门禁解除前的必做项。dry-run/spot/原已有风险管理不借此强制新profile。把新增实际方法纳入既有selected runtime/fresh compile，不新增第二engine/ledger；完整闭包仍独立核验。

### 带guard路由的当前验收（仍为整链WIP）

- 60个新用例覆盖warm/cold四组mode/side的默认LIMIT实际source/acquire/L1、完整profile及原before、quota与L1后读取owner、加载依赖和原风险/分数元数据；均经原SQLite/SDK与底层Session fake。复用原add_trade发送/报告段、原L0 initializer和金额acquire，不新增表/资金模型/年龄默认/许可开关。
- 真实RED→GREEN修复cold在before核验前GET、quota回调换owner的外SQL、已在事务的外库被L1后读取借用、public/private acquire及initializer未在首次调用前核实现，以及v4把原risk_multiplier覆成1。风险元数据沿原before精确核对，quota与V1金额公式不变；旧v2/v3保持原语义，score保持原COALESCE/已验证assessment，不补签旧来源。
- 六模块254个唯一ID：3.11完整首次253 passed/1旧注入断言失败，只修改该一条断言强化首次拒绝并补验4 passed；其余函数raw compile对象双版不变。3.14最终一次254 passed；3.11通过集合并集与3.14精确相等，不称双版在最终同一测试字节各一次全绿。失败原件/源码与JUnit SHA见台账本节，双版compileall及diff通过。
- 默认完整发送仍1真实RED，现位于原Engine.py:612、POST前，无xfail/skip/成功L2替身；原常量仍在。累计30个WIP＝16生产＋12测试/夹具＋2文档，无commit/push，Goal active。
- 下一步先完成无guard/旧v3直接新风险入口拒绝及历史fixture迁移，再原Engine活claim→真正原SDK POST/ACK→完整终态/冷恢复矩阵、SDK闭包与适用全回归。不得以本带guard子路径代替所有入口或完整C5；OKX/C6/C7/整个Goal未完成，实际配置及交易/研究门禁不变。

### 无guard/旧v3直接新风险入口：修改前复用/清理计划

先以当前原public旧v3链在完全fake的Binance/OKX、one_way/hedged、cross/isolated、long/short生成16份固定时钟的完整记录/history/结果/native request参考SHA，作为历史夹具的独立golden；不从将要实现的历史构造器自证expected。新RED同时要求无guard的默认swap入口在quota/SDK前拒绝，以及已有普通v3 created意图不能经public place_order取得新claim/POST。原新金额发送常量、所有candidate/testnet/live门禁保持。

历史兼容只迁移测试数据构造：复用原base prepare/intent、原CChanDB claim/ACK/累计report writer及原单位/参数/回报reader，server返回仅来自已有COfflineExchange/CVenueExchange fake。该测试辅助函数仅接旧v3、无guard、非dry-run swap及实际fake对象，不可用于新金额或伪造成功L2，不改生产校验、不增加permit/enable/config绕行。先与16份原public参考完整字节对照，再改历史测试的初始化调用；这些历史事实不再被称作当前新风险准入成功。

生产只收口CCCXTTradeEngine的原入口：guard缺失不再降级；原sqlite/journal无新金额原始lineage的open/swap意图不能发送。spot/dry-run和原旧单查询、撤单、原生归属、reduce-only/平仓仍用原验证链，不重新实现订单/资金引擎或升级旧wire。保留原v4常量直到全部入口/消费者/完整fake发送矩阵/SDK闭包验收，不以本拒绝子层代替完整功能。每项行为先RED，历史golden/共享体回归、双版及源码/JUnit证据后再记进度。

paper边界修补的修改前清理计划：顶层离线运行在原配置paper生命周期及双币周期实际RED，原因是新限制放进了原paper/native共用的`_validated_persisted_intent`。只把新增后端/无金额lineage拒绝移到原`place_order`已分离的真实非dry-run分支，原共有身份/单位/旧native诊断阻断不变；不用`not self.dry_run`临时放宽共享validator，不增加caller bypass参数。补原native调用中途变更dry_run仍拒绝的回归，保留现有paper真实失败，再最小修补与联合复验。后续命令显式枚举顶层测试文件，禁止递归研究目录。

报价旧夹具的修改前清理计划：108个顶层模块完整JUnit为7,125通过/4失败/2跳过，四失败仅属`test_opening_quotes`中报价guard→普通v3直接发送的旧假设。只改该测试：用原base prepare/SQLite intent写入明确的旧数据，核完整quote/provenance和真实CCXT纯请求builder的张数/价格；原public发送必须拒绝且无claim/POST，随后原writer仅构造历史claim并直接验证原报价reader的fresh/expired分支。该历史测试不授予新准入，不扩无guard历史helper、不补造原生L2、不放宽生产代码；真正默认金额链仍由独立原SDK/底层fake用例验收。完整旧失败原件保留，修改后核未改源码身份并只将适用补验结果合并，不冒称最终测试字节一次全绿。

### 原Engine真实发送接线：修改前复用/清理计划

无guard/旧v3收口回归已验：3.14一次7129通过/2跳过；3.11完整失败后仅四参数旧quote夹具迁移并补验54通过，适用pass/skip集合相等。源码/JUnit身份见台账，原完整发送仍在Engine.py:613实际RED。现在继续同一已批准完整执行目标，不把永久拒绝当交付。

先扩底层Session fake的真实公开Engine正向矩阵（one_way/hedged×long/short，LIMIT/MARKET/GTX），保持原L1→原CAS唯一claim→原L2→锁外原HTTP尾复验→真实SDK POST/ACK。正向夹具显式60000ms仅为合成预算，非生产默认或实际时延认证；旧v2/v3、无guard/错后端、过龄/漂移与未知状态门禁继续拒绝。观察RED后只在原`place_order`调用原私有claim上下文并传原writer；不复制第二writer、金额算法、表或许可对象。

原`_assert_persisted_monetary_contract`已完整按submitting选择原L1或L2，复用它，不另做schema白名单。只有原binding-v4完整current校验后的新金额路径可进入提交期单位检查；旧v2/v3继续原拒绝。新实际调用的claim/capture/finish函数须在首次调用前纳入fresh runtime检查。claim与HTTP之间只用原完整尾复验，HTTP不得持writer锁；提交之后任何失败仍submitting/unknown，不回created或重发。原Engine ACK路径复用已有owner pin，保留原账户身份、原单位及累计回报/恢复；用真实POST之后的owner/回报/断线变异继续TDD，未覆盖矩阵/消费者全部通过前不提交或宣称C5完成。

意图读取owner的修改前修补计划：真实公开发送矩阵12通过、POST后两项故障通过、默认入口与旧契约拒绝100通过后，先新增原`get_order_intent`返回时切换Engine DB/底层connection的两个变异；必须在任何外库SQL/claim/POST之前拒绝且保留原L1。若RED证实，复用`NativeOrderBoundary._database/_same_database`在原共享元数据读取边界pin实际SQLite owner，不新增caller permit或第二reader，不修改MySQL/spot/paper能力声明；保留原参数、单位、事务与paper语义并跑对应短回归。不能因为后续full-current最终会拒绝，就忽略之前已借用外库的读取。

提交前profile相邻读取的修改前修补计划：原HTTP前consumer已用`_observe_account(...,_assert_current=owner)`逐GET核owner；新公开提交进入的`_read_order_contract(submitting=True)`仍须单独证明同一性质。先在实际SDK mode GET返回后只修改fake API key，记录其后全部请求；要求无后续GET/POST/claim且保留原L1。若RED证实，只将该金额路径已有owner传给同一个原`_observe_account`失败检查回调，旧v3/spot/paper调用形状不变，不新增账户reader/预算/许可。

原生提交错误的修改前修补计划：3.14的122项连接矩阵完成后，原`place_order`通用异常仍会拼接SDK原始正文，而原生查询已脱敏。先用真实SDK解析底层fake HTTP400（含敏感占位正文）写RED，要求对外异常及格式化traceback无正文、原claim仍submitting/unknown且不能重发。若证实，仅金额提交的异常分支改为同错误码的固定脱敏消息并抑制原异常链；不改变旧订单契约、其他执行语义、风险释放规则或调用真实端点。

订单路由重试的修改前修补计划：错误脱敏后的157文件SHA `5bc906b26d0b097ee0cf8ef929004aebdaf3adfe2d6e5cd85ed10c80f9f77a93`，3.11的123项已实际exit0。只读复核本机CCXT4.5.89发现fetch2可独立读取options.order的maxRetriesOnFailure/defaultMaxRetriesOnFailure；原来源GET的零重试校验不当然覆盖此POST路由。先用实际公开Engine与底层fake的“接单后丢响应”验证第二POST，并补独立配置/实际helper变异RED。若证实，复用原SDK option reader，在原新金额自采入口、任何来源I/O与intent之前要求真正int零；把实际使用的三个option helper纳入已有fresh-compile声明路径。原options全摘要继续保护L1/L2后的漂移，不复制SDK选项算法、不改实际配置、不创建第二sender或caller许可，不以新风险设置阻断已有订单管理。此项不冒称已覆盖SDK限流/签名之后的完整使用时点或所有Python动态依赖；完整fake矩阵/适用回归与主线程review仍必需。

该重试RED已实际观察同一SDK调用2 POST，7项配置/helper变异也均真实失败；原自采入口与三个已加载helper的最小修补后8专项＋1管理回归通过。完整168项冻结双版及原claim/current/HTTP/终态适用回归仍待，不因子层通过提交或宣布计划完成；实际原件和源码身份见台账对应节。

后续同源168项已双版各一次完整passed：3.11原32280与3.14原18265均自然exit0，case/pass集合差异0；157源码在两版全程保持`f08b5758dabd774dd5594cde9a4a8b75a999955bcbe5065beb32f0ca0b8a8068`，双版compileall/diff通过。仅该发送/入口/旧wire拒绝/SDK组合已验，未将旧全组合冒称最新完整验收；整计划及C5–C7仍未完成，WIP不commit/push，Goal active。

下一边界按原严格鲜活性继续：先以原SDK的限流/等待与底层fake时钟写真实使用时点RED，验证SDK调用前已通过的窗口是否能在实际POST之前过龄；只根据实测根因最小修补，保留原L2、锁外HTTP、原账本/金额和已批准门禁，不添加可转移JSON/PASS或隐式扩大预算。随后补真正POST开始的非零部分成交、取消/终态、原联合观察及冷恢复，再做对应原共享体回归。此为尚未实现/验证的后续工作，不是已批准一种新sender/SDK hook设计，更不是实盘或服务器原子性承诺。

SDK等待已真实RED，新的逐调用传输设计待确认；仅暂停依赖该新机制的生产实现，不暂停独立授权工作。连贯矩阵的修改前复用/清理计划：原terminal fixture的非空账户/逐笔/手续费/资金费数据已具备旧回归保护，将其raw账户更新部分提为测试专用`set_native_filled_account`，原`apply_observed_native_fill`仍先原claim再调用同一数据更新与原query/apply/source流程，行为不变。新execution测试则从真实公开place_order的底层POST响应捕获原生row，随后走原query部分成交→原DELETE取消→原GET终态→原report→原完整components/check→重开原SQLite并冷建SDK/重复回报/再次完整观察；不得调用claimed_order或手写L2。先单case定位，再四种mode/side与原terminal回归。该独立矩阵即使通过也不掩盖当前SDK等待RED，不构成整组提交/发布许可。

连贯矩阵3.11四方向＋原非空账户8项已实际12 passed（原60151 exit0）。撤单错误修改前复用/清理计划：提取该已验证测试的真实POST/捕获原响应/安装已有恢复transport小段为测试专用`submit_for_recovery`，不改生产sender或添加手工claim/L2，原整链继续调用同一小段。再以真实SDK的底层DELETE HTTP400敏感占位正文写RED，要求异常及traceback无私有正文、原记录/history不变、仍只能原GET确认；若证实，仅client-order-v1的原cancel异常分支改为同CANDEL_ORDER_FAIL码固定消息和from None，旧契约兼容错误路径不扩展。SDK等待RED及待批设计保持，不用此独立修补冒称全C6日志已审计。

方案A已获用户明确“批准方案A（推荐）”。修改前复用/清理计划：将原HTTP前完整body提为私有共享reader，额外保留其实际document/binding/原window及捕获owner/失败发布闭包，原公开assert仍None；原Engine仅在原create_order调用外使用私有逐调用context，sender保持一个。context的普通factory及共享reader进入原selected runtime，内部生成的stdlib contextmanager/body不接受caller数据，不新增注册表/表/JSON证明。仅原Session本调用相关POST委托前，锁内原完整L2/ledger/source/current重读、锁外原旧window末尾核验；不再GET、不重采/重签或续预算。按原capture owner安全发布失败，finally只恢复自己仍拥有的原request覆盖状态，不覆写外来替换；单次委托、wrong-thread自身订单、重入和所有owner/窗口变异继续TDD。先将61000ms实际等待RED转GREEN并保留1 POST正向，再补生命周期/实现与旧管理回归，不能因新的元数据/包装器假设放宽已批准范围。

A实施后，纠正测试setup的monotonic覆盖后9项实际通过；重复/重入/错线程3项通过。但原SDK等待期间换Session/request的两项真实RED表明A可被重新寻址绕过，外来fake request先执行后才拒绝。新增第二处同调用fetch入口hook须单独确认，见[设计§6](../specs/2026-10-27-native-sdk-transport-use-point.md)；未获批不实现，也不把A批准误写成失效或重问已有A/P/F。当前继续独立适用回归及结构检查，保留原RED与整组WIP不发布；原Goal active，不因新子边界缺口缩小C0–C7范围。

底层重定向验证的修改前范围：先在原execution夹具中恢复真正Requests.Session.request/send，fake仅下沉到该原Session已有HTTPAdapter.send，全部GET仍转原raw fixture，原SDK/原CAS/L2/尾窗口不替换。保留无redirect的真实Requests正向控制，再以同源307及跨host308检验一笔原SDK调用会否产生额外实际adapter POST；不让高层Session替身替Requests判断redirect，不启真实网络。只新增行为证据，不实施待批B；如果RED证实，则只评估在A已有的受控本单POST请求参数上禁止自动redirect，不修改Session/adapter/实际配置、不新增hook或sender、不重签/重建订单/扩大预算，不影响GET/DELETE/旧契约。原SDK等待换owner的2项RED继续独立保留。

该RED已实际证明同源307/跨host308各2次adapter POST，无redirect控制为1次并通过。最小修补只在A已有guard确认本调用本单POST/URL/verify后，为这次原request的kwargs设allow_redirects=False；放在完整原owner/L2/current及旧monotonic尾核验之前，参数设置耗时也纳入旧窗口，不增加最后时钟或caller数据。URL/headers/body/原SDK签名与订单参数均保持，Session/adapter全局配置不改，其他请求不进入此分支。仍需实际GREEN/双版/相邻生命周期；SDK等待换Session/request的两个RED和待批B不因此解除，adapter自身retry仍独立未验。

重定向专项已同源双版各3项通过；3.14当前联合14项为12 passed/2 owner failed，原26138 exit1，未跳过已知失败。源码157文件前后均7955570748a6a01c7c194d9928b7d091e7c1ce973f392baa9cf81951cb37fdf8，双版编译与diff/本地结构检查通过。B仍待明确批准/未实施，其他完整验收、adapter retry、C5–C7/OKX均不由这3项子层验收替代；整组WIP不commit/push，原Goal保持active。

adapter retry的修改前验证范围：原Requests.request/send、HTTPAdapter.send及urllib3.urlopen/Retry均不替换，只把原pool的_make_request发送边界下沉为raw fixture，并加实际socket创建失败哨兵；全局其他Session的no_http继续保留。先zero-total成功/丢响应两个控制，再在隔离fake Session上给实际adapter配置允许POST read retry的Retry(total=1)，验证原SDK一次调用在“已接单后丢响应”时是否再次进入底层发送点；不启动网络或改实际配置。若RED证实，只评估在原金额自采前与A原本单使用点只读要求实际adapter为明确total=0，未知/非零拒绝而不是重置；不加第二hook/重签/重采/新sender，不用新风险政策妨碍原L2已有订单查撤。待批B和两个owner RED继续独立保留。

实际重试RED为1 failed/2控制通过，原urllib3在同一SDK调用中再次进入POST发送边界；前置资格另9 failed/2兼容控制通过。最小实现复用NativePreparation._function_identity：私有必要条件reader先核标准Session/OrderedDict键、原get_adapter descriptor及实际bound method/fresh源码，再用同一原selector选实际fapiPrivate/order adapter；只接受标准HTTPAdapter与明确Retry.total整数0，不把无关mount的重试配置当本单风险，不调用可变selector后才核代码。reader在金额自采前首次执行前校验自身身份，在原HTTP owner检查中复用并进入selected runtime；不返回许可、不新增表/schema/配置/第二hook，GET/DELETE/已有L2管理不因这个新风险必要条件被阻断。该范围只验证选定route的正常重试配置，不证明全部Requests/urllib3实现或poolmanager未被任意进程内篡改，也不覆盖待批B的Session/request绕行。

上述16项已在3.11实际通过，先保护其行为再做测试夹具最小复用：仅给同一个真实pool发送测试增加during_wait参数，原三个控制保持False；新增在原SDK POST throttle点把原adapter改为read retry=1的case，须在真正发送前拒绝，不能只证明自采入口检查。测试不新增生产拦截，不更改等待时钟/来源/签名；随后将该4项与资格/依赖/原Requests redirect合为20项冻结双版验证，B仍待批准。

最终同源20项已双版各passed、case/status差异0，157源码bffb43f47f4a7c0864e918257b6e530c2e76068fbf2e7a17a9408b7ccf0d2dbe；包括晚SDK等待改adapter为非零时0 POST、无关route与已有L2查询仍可用。相同源码下B的两项owner重验原49240 exit1，仍实际调用外来fake request，未藏入skip/xfail。双版编译、diff/本地链接检查与主线程有限review仅证明所列子范围；完整SDK/claim/current/HTTP/终态/旧状态机和C5–C7/OKX不由这20项替代，整组仍未发布、Goal active。B没有人类批准，不实施第二hook。

扩展回归继续使用同一冻结源码，不因B待批停止独立验证：三个完整模块SDK57＋HTTP33＋claim59在3.11原42843自然exit0，共149 passed/0failure/error/skip，XML1775.028s，源码启动/中途/结束均bffb43f47f4a7c0864e918257b6e530c2e76068fbf2e7a17a9408b7ccf0d2dbe。原件与SHA见台账；这是完整模块的3.11证据，不是双版149项或完整终态/旧状态机验收。下一步仅同源3.14串行复验，活测试期间不编辑、不编译、不重启；B两个RED仍保留，不实施/提交/推送第二hook或整组WIP。

后续3.14原17339也自然exit0，149 passed/0failure/error/skip，XML1599.564s；两版149项case/status差异0，源码始终bffb43f47f4a7c0864e918257b6e530c2e76068fbf2e7a17a9408b7ccf0d2dbe。原SDK/HTTP/claim模块的双版扩展已验，但不替代整个C5。继续相同源码的execution＋terminal_observation两个完整模块，包含已知B的两项真实RED、不skip/xfail/-x遮蔽其后用例；原完整POST/部分成交/撤单/终态/原生联合观察/冷恢复必须实际回归。仅记录结果，B未批准不实现，未完成时整组不commit/push。

该完整批次3.11原79299已自然exit1：原JUnit实际收集69项，execution为41 passed/2 failed，terminal_observation为26 passed，总67 passed/2 failed/0error/skip，XML2965.985s（CLI2966.06s）。两项失败精确为SDK等待后换Session/request，各进入外来fake request一次后才报错；整组不能验收。其余结果包含四组真实POST→非零部分成交→DELETE→终态GET→完整原生联合观察→冷重启及全部26终态专项，但终态专项的原claim/CAS夹具不混称真实POST整链。原件/SHA和69个唯一case/status身份见台账，以当次JUnit为准，不拿含旧用例的pytest缓存计数。157源码在原批次启动、中途和结束后均为同一bffb43f摘要；无活pytest后才更新本计划/台账，无代码、依赖、实际配置或门禁变化，整组未commit/push。下一步仅同源码、相同两个完整模块3.14串行复验，保留两个失败，不实施待批B；完整默认入口/旧状态机、更广C5–C7/OKX仍不由这次局部回归替代，Goal active。

后续3.14原75229自然exit1，69项同为67 passed/2 failed/0error/skip，XML2510.802s（CLI2510.87s）；两版逐项case/status差异0，157源码始终为bffb43f47f4a7c0864e918257b6e530c2e76068fbf2e7a17a9408b7ccf0d2dbe。原件/SHA见台账。此处双版同状态包含真实失败，不是整组通过；当前确认无活pytest后再继续下列独立测试范围。

### 完整订单类型整链矩阵补充：修改前复用／清理计划

主线程按消费者计划第4步复核发现：当前四条完整POST→部分成交→终态GET→账户联合观察→冷重启都固定LIMIT/100/非post-only；MARKET/GTX只有发送与claim起点管理的分段证据。不能把两类用例的并集说成十二条完整整链。上述双版69项中的四条LIMIT链及26项终态专项提供本次测试夹具清理前的实际基线，B两项失败保留且不依赖本补充修复。

只改`tests/test_native_monetary_execution.py`和`tests/test_native_monetary_terminal_observation.py`，不新增sender/管理流程、生产API、依赖、金额公式、年龄或配置；所有实际SDK、SQLite/CAS/L2、查询/回报与账户reader继续真实执行，fake仍仅位于已有底层传输/原生数据夹具。

1. 复用`submit_for_recovery`，仅加price=100/post_only=False的可选参数并传给已有prepare与原Engine.place_order；原无参数调用的LIMIT行为不变。该helper只有整链与撤单错误两个消费者，不复制第二段发送/恢复实现。
2. 整链测试使用已有三组(kind,post_only)：LIMIT/False、MARKET/False、LIMIT/True，与原四组mode/side组合为十二条。直接核实际POST的MARKET/LIMIT及GTX/GTC参数，不以测试标签代替真实发送；原非零partial、DELETE不发布终态、终态GET、完整账户观察、kill-switch保持YES的冷查询、重复回报和一次POST断言全部保留。
3. 原通用fill夹具默认maker=False，不能直接给GTX改标签。仅为既有`set_native_filled_account`增加maker=False选项，GTX使用既有原生commissionRate夹具的maker=0.0002，普通LIMIT/MARKET沿原taker=0.0004；对应raw maker、成交费用、现金流水和原生账户余额一起构造，原默认false的数据/语义保持。通用fill helper、生产费用模型与F/P假设不改；额外核固定0.02@100场景的实际raw费用，避免两份同错夹具自证。此为合成软件场景，不声称服务器成交/费率保证。
4. 改后串行验证十二条整链、原`test_actual_native_cancel_error_keeps_unknown_state_without_private_body_or_resubmission`及原`test_coherent_native_order_average_cannot_contradict_all_of_its_observed_fills`，目标为14个实际收集用例，双CPython各用独立GUID basetemp/JUnit、同测试源码与逐项结果核对；新增maker场景及原默认消费者都须覆盖。只在无活pytest时编辑/编译/开始下一批；先编译两个修改测试文件并做diff/空白检查。

本补充是对已实现行为的集成覆盖扩展和受基线保护的测试夹具复用，不是生产行为修复；不伪造缺参数TypeError或错造来源作为生产RED，不为制造RED删除正确生产实现。若真实生产路径暴露新失败，保留原件并先诊断，再在既有权限内按RED→最小修复→GREEN；触及新机制仍保留审批。记录修改前后逐文件摘要，旧bffb43f双版69项不能被重标为新测试文件身份下的新全量结果。14项即使通过也不消除B的两项绕行失败，不替代默认入口/旧状态机及完整C5–C7/OKX验收；整组WIP仍不commit/push，Goal active。

以上测试复用已按计划落地，尚不预称通过：十二条整链直接核原SDK POST type/timeInForce及实际raw maker/0.02@100费用；原默认LIMIT/非maker仍沿同一helper，原所有查询/账本/账户/cold断言保持。修改前后157个源码逐文件比较仅两个上述测试文件变化，生产文件变化0；新聚合摘要`19bcee1a72cc4816491de3c3e4e1d40f2145c6e37adfbcaac2da03c7641f582b`。两个修改测试文件的双版compileall、diff与空白检查通过，期间无活pytest。下一步仅先启动3.11的上述14项，再串行3.14；新结果待原任务产生，原B两项失败和整体未验收状态保留。

3.11原20377已自然exit0：14 passed/0failure/error/skip、CLI无warning，XML1363.719s（CLI1363.76s）；JUnit逐项确认为capacity_case0..3各LIMIT/False、MARKET/False、LIMIT/True十二条，加原撤单错误/完整成交均价矛盾两个默认消费者。原capacity fixture的四项确为one_way/hedged×True/False方向，非仅比较总数。157源码启动/中途/终态后始终19bcee1a72cc4816491de3c3e4e1d40f2145c6e37adfbcaac2da03c7641f582b，原件与case/status SHA见台账。此处记录原时点仅3.11通过，随后3.14原件结果及新B批准见下，不重标原运行。

后续原93608句柄在上下文恢复后已不存在，两个已知进程亦终态、无活pytest；找回同一个原JUnit（未重启测试）确认3.14为14 passed/0failure/error/skip，XML1147.715s。原件SHA a29650ec7efee6e6d19c7e9d96752e7b37c126b0381834be35c51ca46bdc6e71，两版14个唯一case/status逐项相等、SHA ba7f98097f50b593e0065218038b1847be52a56cefe7135d2c03d7ba93c83730；157源码仍19bcee1a72cc4816491de3c3e4e1d40f2145c6e37adfbcaac2da03c7641f582b。因原工具句柄缺失，不补造该进程exit code/CLI警告结论。只证明所列14项，不消除B原2项失败。

### 方案B已批准：修改前复用／清理计划

用户对原问题call_150a21c7f5a94431aca1b1ef382aaef2明确答复“批准方案B：增加同调用fetch入口owner复核（推荐）”。现只推进设计§6所列fake实现；A/P/F、资金、配置及所有交易门禁不变。先收完原93608、核原件和无活pytest后才记录批准/编辑。

1. 复用已保留的两个原SDK等待后Session/request绕行RED，不改断言、skip/xfail或伪造通过；在当前19bcee源码先独立复验两项作为B实施基线。
2. 仅扩原私有逐调用HTTP上下文，捕获原bound fetch、实际owner与instance override。入口先核同一活线程、Engine/SDK/Session/request、原DB/连接/table和唯一L2，再委托原fetch；A继续完整current/ledger/source与同一个旧monotonic窗口，不重采、重签或增预算。
3. 复用原fresh-compile校验：普通SDK入口不接受任意wrapper/metadata；上下文内部必须验证实际bridge code/closure及捕获的原bound fetch，所有既有SDK声明仍完整核验。无caller PASS/expected、第二registry/表或sender。
4. 两处临时覆盖分别只恢复自己仍拥有的状态，安装/退出失败仍无ACK、未知不重发/释放。补原fetch及bridge伪装、晚owner/依赖、单次委托/重入/线程/恢复和旧窗口测试，再跑适用双版集成/旧管理回归；未经联合验收不commit/push、不宣称C5–C7或整个Goal完成。

B首次最小6项已通过；闭包替换的后续2项真实RED后加强实际回调检查，扩展14项出现9 failed/5 passed。原报告明确根因是共享`_function_node`只检直接body，不能解析原reader的try内owner，finally漏出StopIteration；不是应永久拒绝的正常输入，也未通过放宽检查修补。修改前复用/清理补充：先以小型AST夹具保护try/if/with与同名嵌套函数隔离、缺失及重复定义拒绝，再仅将原查找器改为同一词法层的控制流遍历，禁止跨另一个function/class作用域选同名节点；所有原SDK/本地fresh-compile/default检查保留。旧SDK完整模块基线适用作改动前参考，新源码须重验受影响范围，当前9项失败不改标为通过。

词法修补后5项AST＋1项正常真实SDK/fetch恢复共6 passed。另一个真实RED确认：复制实际bridge的code/globals/closure并重绑自引用cell时，原路径仍成功发送，未按预期拒绝。修改前最小归属修补：在原生成器的普通局部变量保存本次实际安装的fetch对象，不从可重绑的self-reference cell反推owner；同一私有frame只读核该对象，finally也仅恢复这个实际对象。该局部值不是新registry/持久许可/caller参数，原bound SDK完整fresh检查、实际门禁及全部失败原件保持。

生命周期10项实际7 passed/3 failed/1线程警告：复制重绑已拒绝；失效/重复使用各多写原风险状态1次，错线程落入SQLite失败发布。修改前最小修补：活性/原线程/单次消费先作纯拒绝，实际bridge与闭包身份核验也须先于任何失败发布；只有已证明属本次原调用的current来源核验失败才保留原source_failure。不是取消真实来源失效的sticky行为、开放重试或释放未知订单；无效旧句柄/副本不取得账本写入权限。先重验这3项原RED，再连同正向发送、旧窗口及SDK完整检查作双版联合验证，保留全部失败原件与警告。

当前B/A相邻38项在3.14原88851实际exit0，38 passed/0failure/error/skip/CLI无warning，源157文件启动/结束均`dab2304e4bf8c4c7cd38339452a933f42e6b5fe386e29683c41d7de41cb1f215`；逐项范围、JUnit及SHA见设计§6.4与台账，不冒称双版或全部C5。尚须先独立验证原fetch在入口后、Session前调用的四个预处理方法是否可晚换Session绕过A，再做最终相同源码的双版/完整受影响回归；若新RED证实，只扩既有SDK fresh-compile/实际输入闭包，不顺带新加第三hook、金融规则或配置。默认POST直接FILLED的原GET终态来源/完整账户/恢复仍是后续必做，不靠扩大恢复SQL或DTO终态放行凑通过。

预处理只读复核进一步确认四个直接方法还调用set_headers/value_is_defined，并可执行八个camel/snake proxy callback及旧proxy callable。修改前验证/复用计划：沿用同一原SDK真实POST throttle、原claim/L2与底层Session fake，分别晚替换这六个方法或九个回调，要求在任何未证明预处理/外来request之前拒绝；不以高层fetch替身代替。若RED证实，仅把实际方法加入原SDK fresh-compile清单，把不具原生来源声明的SDK代理回调拒绝在原新风险读取前，并将实际标量proxy别名纳入原client binding；不调用/猜测/自动配置回调、不扩大金融模型或再加hook。已有订单管理不得被当作新的资金准入，静态代理路由仍按原精确URL/配置身份门禁，不借此承诺代理/整个Python环境认证。

预处理15项已实际全RED；另20项为11 failed/9管理对照passed：新风险9种回调未拒绝、L1后2种代表回调current仍通过；已有查询9种回调全部维持原行为。实施前按事实收窄不必要的内部改写：不把callable或弱presence摘要加入client binding；允许值仅None，故在所有新风险采集/current/HTTP边界直接静态读取、检查该闭合不变量，并把实际检查函数纳入原fresh runtime。这样既拒绝L1后变化，也不把新风险规则加到历史管理或重封旧SHA；标量proxy别名的另项指纹扩展不在本15项修复中顺带改写。新增私有只读资格函数不是hook/许可，使用getattr_static避免先执行未知descriptor；仅新风险冷初始化接此必要条件，恢复initializer保持原职责。六个实际预处理方法沿原SDK核验循环补齐，不跳过原bound fetch或其余声明。

上述临时“仅新风险”放置方案在第一次GREEN前复核纠正：原冻结要求区分来源实现完整性与新资金/年龄许可。未知proxy callback实际在SDK fetch内执行，已有query还可能发布原生终态证据；维持该未知执行不能被当作“保留管理功能”。前20项中的9个正向是旧行为观察，不是已获批准的callback支持承诺，原件保持不重标；改为9个明确来源拒绝RED后，将资格检查并入共享实际SDK身份检查。它不读资金、候选、年龄或kill-switch；正常原SDK的GET/DELETE/降风险和冷恢复继续按原测试保护。删除刚写但未验收的分散新风险接线，避免同一来源规则在不同边界不一致；不改任何真实配置或扩大门禁。若未来要支持自定义代理回调，须另有实际来源契约，不能从本次旧行为PASS推定认证。

共享修补后的3.14原91689完成9项smoke，9 passed/0failure/error/skip/CLI无warning；正常一笔原SDK POST及正常SDK在过龄/kill/freeze条件下查询/撤单均通过。源码157文件`15b03c645c72e0d036b0f55998988a5963002271c56500d19843cbd231765c66`，双版Trade＋两个修改测试compileall/diff通过；这不是旧38项在新源码的全量重跑。下一步先冻结该源码，三个顶层完整模块SDK、execution、HTTP串行回归，保留其中全部失败而不筛除；之后相同源码的另一解释器/其余适用范围及默认FILLED整链继续原目标，不以smoke或前期38项替代。

后续验收还须核原始POST直接返回FILLED的入口回报：当前原生发送fixture固定NEW，已有FILLED专项从claim/query开始，不能替代add_trade即时消费已成交回报的证据。先完成本14项双版及适用默认/管理回归，再核已有证据并在原批准fake范围补齐；不得把本地FILLED/POST DTO当原生终态持久来源或自动解锁，完整GET/执行/现金/账户与旧门禁保留。此处仅记录需求缺口，未修改生产行为或启动新矩阵。

后续当前157源码`15b03c645c72e0d036b0f55998988a5963002271c56500d19843cbd231765c66`的3.14原35968完整三模块已自然exit0：209 passed（SDK90/execution86/HTTP33），0failure/error/skip，逐项及原件SHA见[开发验收台账](../reports/2026-10-20-crypto-full-version-progress.md)对应209项节。确认无活pytest后才记录；下一步保持同一源码串行验证3.11相同case，不把本次3.14结果或此前双版14项外推为B/全部默认入口/整个执行子链已验收。未改源码或金融规则，未commit/push，Goal仍active。

后续原21347也自然exit0，3.11完整209 passed/0failure/error/skip；两版各209个唯一case/status逐项差异0，同157源码15b03c，原件/摘要见台账双版209项节。确认无活pytest后进入下一小步；这只是完整三模块证据，不把直接FILLED默认链、其他必需联合回归或C5–C7提前称为完成。

### POST直接FILLED默认链：修改前夹具复用／清理与TDD计划

1. 以上双版209项中的十二条实际POST→partial→cancel→原生账户→cold组合保护已有fill夹具。先仅从`tests/test_native_monetary_terminal_observation.py:set_native_filled_account`提取原raw成交/费用/钱包/持仓行的纯数据更新，返回原positionRisk四字段；原helper参数、默认值、金额算术与随后安装的原fake wrapper保持，生产代码不动。不在POST调用中替换Session/request/SDK，不重复一套资金夹具。
2. 在已有default-entry测试复用原profile、last、recovery与order transport，所有底层fake回调在原add_trade之前一次安装。真实原SDK产生POST后只修改合成venue数据及Response为FILLED/0.1@100；不得手工claim/L2、mock sender/query/账本或改变原配置门禁。先用单一小fixture观察正确RED：已有原报告确已应用0.1，而原GET终态来源缺失；不把导入/参数/错owner的夹具错误当作行为RED。
3. 只有真实RED确认后，才评估在原native终态POST路径复用已有managed query；原POST已知累计量/均价不能被陈旧或矛盾GET覆盖，GET不可用仍保留原claim/未知状态，不重发、不释放、不将POST DTO充当终态来源。不扩大全部opened记录的恢复SQL，不新增hook、表、许可、预算、金额模型或caller证明。
4. GREEN须形成原默认source→L1→claim/L2→唯一SDK POST→原GET终态→原报告→完整executions/fee/funding/account→cold幂等管理；后续补陈旧/矛盾/丢查询等真实RED及适用方向/订单类型。最终受影响claim/terminal/default/旧状态机与双版验收仍必需；不为未改范围反复构造相同基线，也不把这一步的小集GREEN当作整组验收或发布许可。

首个真实RED已确认缺GET终态来源，原partial/cancel/account/cold基线passed，原件见台账。修改前测试夹具复用补充：把新正向用例中已验证的profile/last/recovery/order与预安装filled-venue小段提为同文件测试helper，返回原state/posts，不改变fake金额或生产API；正向完整断言保持。三个独立负向参数仅在调用前的底层GET回调设置陈旧NEW/0、FILLED均价矛盾、请求超时，要求默认入口拒绝且原claim/submitting/0本地成交保留、第二次入口无额外POST。先看DID NOT RAISE等真实缺行为RED，再最小生产修复；不得在运行中的POST/GET替换Session，不以这些测试支持自动释放未知意图。

四项真实RED后最小原查询复用，原13823五项GREEN及source/JUnit摘要已记台账；尚非联合验收。下一小步仅将正向测试的single_case换为既有capacity_case四参数，不改变金额/时钟/源数据公式或生产实现；原完整source→POST→GET→report→账户→cold断言不删。先3.14再相同源码3.11，观察真实结果；不得把有限组合通过外推为所有入口、订单类型、OKX或C7认证。

首轮八项2 failed/6 passed，已由原失败库只读核实为fake误用CAS前signal的BOTH生成hedged成交；原订单/契约已正确LONG/SHORT，生产对账拒绝正确。修改前修正范围：只在现有filled-venue里用实际SDK POST Response的side/positionSide生成fake成交所需两字段，不改initial信号、不预写DB leg、不动生产或金额公式；加成交行/实际POST/持久化leg的精确一致性断言，原全部断言保留，再完整八项及双版验证。混合原件保留，不能据此删除hedged组合或放宽原position-side检查。

修正后3.14原69839完整八项passed，case ID与混合轮差异0，源157为422701808991483a88beb1e5e907adb7919f5de685f7b2d4a0749fc3e04f5d7a，生产76a781c5不变；原件与case/status摘要见台账。下一步同源同八项3.11严格串行，原失败不重标，未覆盖的入口/订单类型/旧状态机/OKX与C7仍按完整计划验收，不提前发布整组WIP。

原63106同源3.11八项也全部passed，两版case/status差异0，原件/摘要见台账；该双版基线为下面测试内非行为提取提供保护，不冒称其他订单类型或全部前序回归已完成。

### 完整终态的MARKET／GTX覆盖：修改前测试复用／清理计划

只改已有default-entry测试模块，不动生产。将当前已双版保护的底层FILLED Response/positionRisk小段提为同文件helper，默认LIMIT仍按原profile→add_trade；将其完整POST/GET/账户/cold断言段提为共享测试验证函数，原断言保留，不复制第二组账本/来源构造器。fake side/leg始终来自实际SDK POST，GTX maker仅按实际timeInForce生成，复用原raw updater的已冻结maker/taker金额公式，不增加金融假设、年龄默认或caller PASS。

新增MARKET与GTX各四种mode/side，复用原prepare_for_engine的真实原生自采/L1、原place_order唯一claim/POST和原_apply_order_report；所有底层fake均在相应原SDK调用前安装，不在调用中换owner，不手写L2。断言实际POST type/timeInForce、maker/精确费用，再复用相同原GET终态/完整账户与cold幂等验证。默认LIMIT原四项、原三异常查询及原partial基线均保留，总计16项先3.14再同源3.11。此步是既有已批准能力的覆盖扩展；若暴露真实失败，先保留并诊断，不为制造RED删除正确生产实现，也不把小集通过外推为C5–C7/OKX完成。最终前序trade safety/state-machine及当前原生联合回归仍必需。

原86968完整3.14十六项已自然exit0，16 passed且无failure/error/skip；原八项全部保留、新增八项，157源码启动/结束均aecad0c9，生产76a781c5未变，原件与case/status SHA见台账。确认无活pytest后才记入；下一步仍按本节冻结顺序以同源同16项串行3.11，运行期间不编辑源码/测试/文档或再起pytest，不将观察句柄过期/输出截断当作测试终止。

双版16项后尚需C6已批准中断条件的一项实际TDD复核：完整POST已知累计量/均价在第一次GET不可用后，重启并收到陈旧/矛盾GET时是否仍守恒。只读代码显示原ACK仅记id，当前六字段保护限同一次调用；这不是行为RED或修复结论。先复用本文件底层filled-venue与原冷SDK/真实SQLite，单变量构造该原中断链、观察restore与原report真实结果；若失败先保留原件并追根因，不凭猜测扩恢复SQL、新增账本/表/hook、改变任何金融规则或把POST DTO升级为终态释放证据。原完整GET/账户/预留与未知不重发门槛保持，整组仍须原联合验收与Lore/push条件。

原70758的3.11十六项同样全部passed，两版唯一case/status差异0、共同摘要0013adf8，源码aecad0c9/生产76a781c5全程一致；原件与精确摘要见台账。无活pytest后才推进下一TDD：只添加stale/average两个原冷恢复中断参数，warm首次GET超时、cold原SDK/SQLite恢复时投影和历史不得接受矛盾；正常GET后仍须精确恢复一次并通过完整账户读链。复用原helper，不改其金额公式/原断言，不改生产直到实际RED，原联合验收与交易门禁继续保持。

首轮原2460两项failed位于mixed fixture的旧ALT→generic cold SDK初始化，缺SAPI/完整metadata fake，并未到目标TEST查单；明确不是所需行为RED。修改前仅修此新测试的底层venue：覆盖原load_markets实际读的货币/空spot和inverse目录及旧ALT响应，不改SDK/options/cache/config，不删旧记录或mock恢复列表。正确断言应要求矛盾时只恢复旧ALT、正常后恢复ALT与TEST、重复时仍只恢复ALT；同时精确保留ALT量/均价/尝试和目标原投影/历史。先将完整混合路径真实跑到目标缺行为，不因该夹具失败扩大生产范围。

第二轮原87585仍在缺margin列表的fake处失败，不算行为RED。已核实际SDK describe的fetchMargins=True和完整metadata分支；只补cross/isolated目录空列表，SDK原选项/缓存/配置不改。两轮原件和源码摘要保留在台账；完整mixed恢复及目标原生GET断言保持，不靠删除旧ALT或预制缓存越过此测试准备缺口。

### 已复现的POST累计回报守恒：修改前复用／清理计划

原76648已到达目标并两项真实RED：完整POST 0.1@100、首GET超时后，原冷restore在stale/average下均返回目标id3；原失败库分别成为零量open回报或0.1@99，旧ALT id2原量/均价保持。完整原件/source/实际查询证明见台账，生产尚未改。不是前三次生产修补失败：前两轮仅是fake缺目录、未触及生产；本轮首次证明目标缺行为。

1. 复用原append-only OrderAudit与原owner-pinned事务，把实际原SDK已通过原身份/条款/数值校验的完整POST累计回报作为不可变的已知响应事实保存，必须在后续GET前完成。不是原生终态释放证明或新增许可；保留原ACK在缺字段/回报不完整时的订单号与未知语义，不将资金模型、limit价格或caller数据推导成已成交事实。
2. 原query/cold restore在追加终态来源或应用累计报告前，从同一原attempt重读这项事实并精确核id/client/请求量/累计量/均价/终态，矛盾仍LIST_ORDER_FAIL、保留未知、不重发。原同次六字段保护复用同一核对逻辑，避免只保留一个调用栈内的临时result。旧ALT及普通旧wire继续原恢复，不删记录、不扩恢复SQL。
3. 只复用既有journal writer与源/owner检查；若共享原ACK/来源发布的小段，先保护现有回滚、stamp、零foreign-SQL和原query行为，再提取一个内部共享体。不加第二writer/表/SDK hook、公开caller回报证明或新的金融/年龄默认值。新增历史事实须显式版本/覆盖声明，旧历史字节和L1/L2前缀保持；后续原query终态、execution/现金/完整账户及预留释放条件一律不因POST事实而放宽。
4. 两项原冷中断RED须先GREEN并执行后半段：正常真实GET后精确0.1@100恢复一次、重复不重记、完整mixed账户匹配，过龄/kill=YES下旧管理仍可用。补持久事实/历史派生字段变异、发布失败回滚及必要owner边界，不能把新JSON字段或schema白名单当验证。随后当前受影响原生/默认/终态/旧状态机联合与适用双版验收、main review和原Lore/push门槛仍必需；未验收不发布整组WIP。

具体表示沿原journal新增`sdk_submission_report`事件与六字段规范化字符串，不保存任意SDK blob或增加独立凭据；只有实际原POST已通过原解析后内部写入。所有完整native POST（含NEW/部分成交）均保留已知事实：终态六字段精确一致，非终态沿原累计语义核id/client/请求量、量不回退、同量不改均价，允许后续合法进度，不把NEW强制成永远相等。新增实际格式化/比较/历史reader沿原fresh-compile清单核验。

history v3显式区分只有SDK事实与SDK加原query来源；原v1/v2字节及L1/L2前缀不变。SDK事实不应用成交、不是`native_terminal_observation`，原pending/账户reader只认后者及完整执行/现金观察才可释放。原ACK缺字段/未知路径不变；新事实经同一原owner-pinned事务与原append writer发布并重读，query在追加原终态来源之前核已知事实。先有24项缺函数RED，格式化小步12 passed/12缺比较函数RED，后续快速旧历史兼容与真实冷恢复分别验证，不以单位小集替代原SDK联合验收。

当前最小实现已获24快速＋35旧历史的双版59项，以及原88680实际SDK四项3.14 GREEN；两项冷中断的正常恢复/重复/完整账户后半段确实执行，原完整成交/native冷初始化和原NEW入口各一组保留通过。启动/结束源码fdbd5548与原件见台账。下一步先冻结同源同四项3.11；此后仍须持久事实派生/身份/版本变异、失败回滚与stamp/owner边界，再做当前源码适用原生/默认/终态/旧状态机联合及双版/main review。SDK事实不是原生原始JSON或服务器签名，哈希不证明整库伪造安全，也不授予释放/交易权限；未联合验收不提交整组WIP。

原49252同源四项3.11也全部passed，两版逐case/status差异0，原件/源码见台账。现在仅追加上述已列验证，不改生产/现有测试体；准备及失败断言只供新增测试共享，继续原SDK/SQLite与底层fake。优先核SDK事实无终态释放权、规范化/身份/contract/kind/header及旧前缀，随后SQL/stamp/foreign-owner回滚与新helper晚改。失败先诊断，不将新增测试的首次GREEN伪称新的TDD RED，也不为制造RED删掉正确实现。任一活pytest期间不编辑/compile/另起pytest，整组WIP仍不提交。

后续原69392新增12项3.14已自然exit0、全部passed，SOURCE 9ac5e0bd启动/结束一致；只有测试追加，生产同双版四项的fdbd基线不变。SDK-only不释放、8变异循环/旧前缀、SQL及4非法stamp回滚、DB/连接零foreign-SQL、3晚依赖零替身执行均实际完成，原件见台账。先同源同12项3.11，再继续完整受影响native/SDK/default/terminal/claim/旧状态机及必需联合回归/main review，不把首次GREEN称新RED，不发布尚未联合验收的WIP。

续行复核原11713：观察句柄已失效，但原进程/UUID均不在运行，原完整JUnit证明3.11十二项全部passed、0failure/error/skip；不虚构未观察到的原shell退出码。当前157源码仍9ac5e0bd，两版各12个唯一case/status摘要完全相同，原件见台账。下一次联合验收显式枚举全部109个顶层test_*.py、排除已有network标记，不递归research；包含全部10个monetary模块（包括既有consumers/prepared_intent）、其余native基础及全部既有trade safety/state-machine，不再插入重复的小集。先3.14、后相同冻结源码/用例的3.11，任何活pytest期间不编辑或compile，结果尚未产生不得提前宣称通过；全部必需联合验收和主线程review前仍不commit/push整组WIP。

### 2026-10-28完整联合结果与修改前测试清理计划

原94299已自然exit1：3.14完整109顶层模块为7327 passed/2 failed/2 skipped/1既有network deselected/24 warnings，7331个唯一case，157源码启动/终态均9ac5e0bd；全部10个monetary模块653项passed。失败仅为`test_native_prepared_current`同一测试的Binance/OKX参数，原27494单独重跑也2 failed，排除了跨测试污染；原件与摘要见台账。不能把该混合结果称作全绿或发布许可。

根因已沿实际夹具和原Engine分支核对：夹具`acquire_native_prepared_diagnostic_intent`冻结binding-v2；原`_validated_persisted_intent`只对binding-v4调用金额current consumer，否则直接拒绝。该分支符合本计划“旧v2/v3诊断不可升级”；旧测试仍用spy要求先消费current，失败的是过时调用顺序，不是需要放宽的资金门槛。

仅修改该测试的预先清理范围：移除高层current spy和内部调用次数预期，改名明确“诊断current不授予Engine金额权限”；先验证真实v2/stage/非准入字段，再在原owned transaction调用真实current reader，并精确保留全records/history/transition、原source trace及SQL total_changes；原私有验证、公开place_order和原claim均须拒绝且不产生写入或新请求。不改任何生产文件、原v2/v3字节、资金公式、配置、交易门禁、SDK hook或其他测试体；不以修改生产去满足旧spy，也不删负向或加skip/xfail。

之后验证整个改动测试模块及相关入口边界，保存两旧ID到两新ID的一一映射。3.14原完整失败记录保留；仅在确认其余源码/测试未变及全模块补验通过后，复用适用旧通过证据，不冒称最终测试字节一次全绿。3.11仍执行全部109顶层模块的最终冻结源码，核对最终唯一case/状态集合、编译、diff及主线程review；未满足联合门槛前不commit/push，C0–C7 Goal不关闭。

上述测试对齐已在原92455的3.14完整模块补验中通过：70 passed/0failure/error/skip，自然exit0，CLI230.57s、XML230.504s，08:20:46至08:24:37。只改`tests/test_native_prepared_current.py`，其SHA变为`64b1fc315668483ac52201e0e4f0f55ad5900189efb5beb34e5e093785fc6848`；157源码启动/结束均`8e5a7bb821aafdd4d1e95951173e2fba51a1af4a5df2bafce06510f87c7f80dc`。把此单文件摘要换回d101b8e6可精确重建原9ac5e0bd，证明其余156个源码不变；三生产文件摘要也与原完整运行一致。移除高层spy，复用真实owned reader、原Engine验证/公开send/原claim和原完整records/history/transition比较；不改生产、SDK hook、实际配置或交易门禁。

旧`test_original_engine_consumes_local_reconstitution_but_still_refuses_unfunded_intent[binance|okx]`分别映射为新`test_diagnostic_current_view_cannot_become_engine_monetary_permission[binance|okx]`；除此两项名称外，模块70个唯一case集合差异0。原7331项扣除此模块、合入同模块补验后为7329 passed/2原skip，排序case/status SHA `5ce273b8438483a08aaee90c029213e12343557e0306377ab640e5450ebaefe4`；这是带精确身份和映射的组合证据，不是最终树一次完整3.14全绿，不抹掉原失败/警告/排除。双版Trade/tests compileall均exit0。原件/SHA见台账；下一步仅启动相同最终源码的3.11完整109模块，期间全部源码/测试/文档冻结，终态后再写验收记录。主线程review及联合门槛仍未完成，整组不commit/push，Goal active。

### 2026-10-28原执行/恢复子链联合验收（整体Goal未完成）

原12028从08:26:13至14:34:44自然exit0：CPython3.11.15完整109顶层模块7329 passed/2既有skip/1既有network deselected/24既有warning，CLI22108.34s、XML22107.026s。157源码启动、连续只读复核及终态均8e5a7bb8；原进程持续执行，不因观察超时/无新输出重启，活pytest期间没有源文件/测试/文档编辑、编译或另起测试。原JUnit与SHA、完整矩阵和残余风险记入[台账](../reports/2026-10-20-crypto-full-version-progress.md)。

3.11完整7331个唯一case/status与上述有身份/ID映射的3.14组合证据逐项差异0，共同SHA5ce273b8；改动模块70项子集SHA4629c6d0也完全相同。原3.14完整失败及24警告不改写，不能称两版各一次最终树全绿。十个金额模块653项均在两版完整运行中passed；旧单位/历史构造只使用明确的legacy fake helper和原reader/writer，不作为新风险准入证明，新风险另由实际原SDK/底层fake的完整矩阵保护。

主线程按本计划与已批准A/B完成变更审查：同一原prepare/CAS/claim/L2和owner-pinned writer；默认swap拒绝无guard、旧诊断和未验后端降级；原SDK唯一发送、临时hook及旧窗口；SDK已知六字段不充作终态/执行/账户释放；完整原生观察、未知状态、cold混合历史、原GET/DELETE/reduce-only管理保持各自职责。复用原事务/journal和共享current/history主体，未引入第二资金账本/订单引擎、配置许可、依赖或金融默认值。未发现阻断此已测软件子链阶段交付的新增已证实问题；这不是完整Python依赖、服务器或全部C5–C7认证。

联合软件门槛现已满足，下一交付步骤为文档结构/差异复核及已授权Lore普通push到`origin/full-version`，不合并main、不强推、不更改真实交易配置或解锁门禁。此处只结束本执行/恢复子链的WIP状态；C5/C6其余项、OKX同等级原生金额路径、实际容量/时延/舍入/通知与C7外部认证仍须按主计划继续，原C0–C7 Goal保持active。
