# 原SDK内部等待后的逐单传输使用时点

日期：2026-10-27（Asia/Shanghai），验收更新：2026-10-28。**状态：用户已明确批准方案A和§6方案B（“批准方案B：增加同调用fetch入口owner复核（推荐）”）。A/B已纳入原执行/恢复子链的fake联合验收，结果与限制见§9；原owner、闭包及其他RED均保留。下文分层记录描述各自历史时点，不代表当前仍待审批，也不等于C5–C7或真实交易认证。**

本文件只审查原金额订单从SDK入口到原Session实际调用之间的缺口，不重问已批准的来源、账户级串行、A/P/F或Goal续行，不改变任何实际配置、资金、候选、研究、测试网或实盘门禁。主目标仍是C0–C7；本设计不是服务器资金锁或实盘认证。

## 1. 当前证据

当前原Engine在`SDK.create_order`之前调用完整L2/来源/金额/current/profile检查，末尾沿原monotonic窗口覆盖核验和原事务退出。CCXT4.5.89的原`fetch2`随后才执行`throttle`、签名和`Session.request`；此前的使用时点未包含这段等待。

`test_original_sdk_wait_cannot_send_after_the_original_source_window_expires`使用真实原SDK/原SQLite/原claim/L2，只fake底层transport、sleep和时钟。SDK真实POST限流到达注入点，模拟等待61000ms；原来源预算仍60000ms，没有刷新来源或扩大预算，结果仍出现1 POST。原句柄86153正常exit1，1 failed/0error，XML49.475s；原件`chanpy-native-sdk-wait-use-point-red-9094d7afab6245cba966fea0bed47323.xml`，SHA256 `39dff9041d866c05ab7a79b1ad4433ab930e7fca7b13a2d432ef93d7e37c5866`。

这不推翻此前冻结源码f08b5758下双版各168项的实际结果，但证明该范围不足以关闭真正使用时点。新增RED不xfail/skip，不以旧全绿代替。

## 2. 推荐方案A：原调用内的临时传输尾守卫

这是新的运行时拦截机制，已获本文件专门确认；不是再次批准既有经济/来源协议或整个Goal完成。实际配置、真实I/O与全部交易门禁仍不变。

1. 原Engine、原SDK的`create_order`仍是唯一sender；不另造HTTP请求、签名、价格或下单算法，不更换SDK类、安装或持久配置。
2. 将现有完整HTTP前检查的私有共享体保留其本次实际L2、原来源数据、monotonic起点及捕获owner；原公开assert API仍仅返回None。数据只存当前原Engine调用的私有活上下文，不写表/JSON，不接受caller PASS/root/clock，不作为可转移准入凭据。
3. 仅在这一笔原SDK调用期间，临时包住该原Session的`request`。原SDK完成限流/签名/序列化后，本调用线程的原订单POST在委托原request前，必须再次核同一Engine/SDK/Session/原DB连接/table/原L2/完整账本/冻结与实际加载检查，并沿**同一个旧窗口**作最终纯预算核验。原预算不得被新UTC读取、重新采集或重新签名续期。
4. 尾段不得重新GET账户、重采资金或重新构造/签名订单；所有本地读取/检查/原事务退出耗时仍包含在尾窗口内。委托原HTTP时没有writer锁；不把SQLite事务伸入网络。
5. 这只是本调用到原transport交接点的检查，不声称服务器接收时原子性、服务器锁额，或整个Python进程/所有传递依赖受信。Requests自身的实际传输/重试范围须独立核实，不因新守卫就宣称全部动态依赖闭合。

## 3. 生存期、兼容和失败语义

- 守卫由实际原Engine创建/消费，不新增可配置enable/permit，不支持caller手工expected包或复制上下文。原SDK所有已声明callable及新增实际调用依赖在首次使用前fresh-check。
- 同一调用只可把这一笔POST委托给原transport一次；验证失败不委托。重复消费、重入、错线程冒用同一上下文、换Session/DB/connection/table、late ledger/input/freeze/SDK变化均拒绝。不能用自身增量排除或新hash重封L2。
- 仅本次调用线程的相关POST受此新窗口约束；不把新风险预算强加给其他已有单GET/DELETE/reduce-only管理。其他线程不获得此上下文的准入权；共享SDK的并发行为仍须以测试和明确支持范围约束，不擅自加账户/全局管理锁。
- finally只恢复被本调用实际捕获且仍由它拥有的原Session/request状态，包括原本无instance override的情况；不覆盖外来替换对象，不向外库执行SQL。退出/恢复异常必须显式失败，不伪造ACK。
- claim后验证失败仍保留submitting/unknown；来源不可用按原可证明owned DB的失败发布语义，换库时只拒绝且不声称冻结。真正HTTP已经委托后的异常仍不释放、不退created、不重下；原ACK/累计回报/恢复完全保留。
- 原v2/v3、旧历史和公开assert返回值不升级、不补签、不重封。已有L2管理不要求新资金窗口。

## 4. 其他路线及取舍

- SDK子类/重新生成请求并签名：会改既有精确SDK类型、执行身份及sender路径，范围明显更大，当前不推荐。
- 只提前限流、增加预算或仅在SDK返回后检查：不能拒绝本次已经过龄的POST，不满足已批准严格方向。
- 暂不批准A：继续保留该边界为未完成，整组发送WIP不发布；继续独立的非零成交/终态/联合观察/恢复测试。不能把永久拒绝当完整Goal完成。

## 5. 实施前验收清单

按已获批准A先写修改前复用/清理计划，再按TDD分层实施：

- 现有61000ms等待RED转GREEN：0 POST、原唯一L2保留、无ACK/重下；普通未过龄真实SDK链仍可1 POST。
- 等待/签名/序列化期间的晚输入、freeze、其他记录、owner/Session/SDK变化；原pure窗口typed monotonic、恰界/反向/bool、原事务退出延时；不新增隐含容差。
- 单次消费/重入/错线程/重复POST、finally正常和异常恢复、原无override恢复、外来Session/DB零SQL；公开API无caller证明入口。
- 原SDK/底层fake的one_way/hedged×long/short×LIMIT/MARKET/GTX，丢ACK、原查撤/reduce-only和cold管理；原claim/current/HTTP/终态与paper/旧状态机回归。
- 双CPython3.11.15/3.14.2、CCXT4.5.89、同源同case，compileall/diff/链接、主线程review；无活pytest时才改文件/另启测试。整组满足原计划后才能Lore/push；C5–C7/OKX仍按完整范围验收。

本文件不规定新的年龄、观测跨度、金融假设、线程全局权限或实际连接地址。确认A不等于确认实现已完成，也不等于解除任何真实交易门禁。

可用性限制：末尾本地核验会消耗已经生成的SDK签名有效时间；不据此重签或扩大recvWindow/来源窗口。必须测试并诚实保留可能的拒收/未知状态，不把fake合成预算解释为真实端点时延保证。

## 6. A实施后的owner绕行与新增方案B（已批准，最终fake验收见§9）

### 6.1 实际结果和根因

A的旧窗口两种时钟、四种request有无override及正常/丢响应恢复、cleanup不覆写外来request、两个新增实际依赖首次调用前校验共9项已通过；同一活上下文的重复/重入/错线程另外3项通过。均为原SDK/原CAS及底层fake，不是服务器认证或整个A验收。

新的`test_sdk_wait_transport_replacement_is_rejected_before_foreign_request[session/request]`在原SDK throttle的sleep点，分别替换exchange.session或原session.request。两项均实际进入外来fake request之后才被finally/owner拒绝，违反“外来transport不得先执行”的预期。原89632 exit1，2 failed/3 passed/0error/skip，XML248.496s（CLI248.53s）；`chanpy-native-http-use-ownership-e55b0f20e6184b5fa8d8ee810a724f67.xml` SHA `4c279cce619f178393b1950acb6146b8a8ad55b847a58b36c1158015d7ac0884`。不改断言、不skip、不用事后报错或此前9项通过替代此RED。

本机CCXT4.5.89的原fetch2在throttle、sign之后调用原fetch；fetch随后重新读取self.session.request。A仅包住捕获的原request，因此被换走的Session/request不再经过该守卫。原profile GET后换Session已能前置拒绝，但不能证明SDK内部等待后的重新寻址也受保护。根因不是年龄预算不足，不能靠增加预算、重采、重签或事后复验修复。

### 6.2 推荐B：在同一调用加原SDK fetch入口owner复核

这是**第二处临时运行时拦截**，不在原A“仅包住原Session.request”范围内。用户现已对本节专门明确批准；批准仅授权本节fake实现，不等于实现已完成、发送链验收或任何真实交易授权。下文此前“待确认/未获批”的运行记录保留其历史时点，不代表当前审批状态。

路径为：原fetch2等待/签名 → **同调用fetch入口owner复核** → 原fetch → A的Session.request原L2/旧窗口尾复验 → 原request。原SDK仍生成并发送唯一原订单，不复制HTTP/签名/资金算法、不换SDK类、不动实际配置。

1. 原Engine创建A的同一个私有活上下文时，额外捕获并临时包住该实际SDK实例的原bound fetch。新增入口只核原Engine/SDK/Session/request、原DB/连接/table、活调用线程及当前唯一L2；等待/签名后发现owner变更时，必须在原fetch及任何外来request执行之前拒绝。
2. 原fetch由捕获的原bound方法执行一次；其URL/headers/body/方法参数不重建、不重签。A仍负责最终L2/全ledger/来源/金额与原monotonic窗口检查，不以新入口重新建立预算。
3. 实际SDK校验不能因为存在hook就跳过fetch或相信标志/metadata。须fresh-compile核新增factory/bridge实际code、完整活closure的原owner及原bound fetch的已安装源码/descriptor；只有该原调用内部可认定自己的临时包装，原普通入口、伪包装、metadata冒充、过期/跨Engine/跨线程上下文一律拒绝。不能新增caller expected/PASS、可持久许可或第二registry/表。
4. 两处finally分别只恢复自己仍拥有的原instance override状态；外来替换不覆盖，安装/退出异常不伪造ACK。旧L2、submitting/unknown、原失败发布与查撤/降风险语义保留。
5. B必须同时保留原SDK已声明路径的完整fresh检查。不能把B的入口复核说成整个Python进程、所有SDK/Requests传递依赖或任意线程篡改的原子隔离；原fetch内部预处理/Requests重试与重定向仍须按真实路径独立审查。任何继续被实测证实的必要绕行仍阻断验收，不以缩窄断言消除。

### 6.3 取舍和验收

- 推荐B是针对已复现的SDK等待后重新寻址缺口，新增侵入面为该SDK实例一次调用期间的fetch包装及其完整身份核验；不是类级/全局patch、第二sender或自动解冻。
- 仅保留A并在返回后报错会保留已观察到的先执行外来request，不能视为修复。全局修改Requests/SDK类或新建隔离发送进程是不同且更大设计，不在B中顺带实施。
- 若不批准B，继续保留2项真实RED及WIP未发布，可继续不依赖B的测试/审查，不把永久拒绝当完整Goal交付。
- B获批后，先把当前2项RED转GREEN且外来调用为0；然后签名/等待后的DB/连接/table/ledger/输入/freeze/凭据/SDK变异，原fetch/bridge身份伪装、单次委托/重入/线程/安装恢复，原四方向×LIMIT/MARKET/GTX及旧窗口/终态/旧状态机均须适用验证。双版同源验收、主线程review及原发布门槛不变。

确认B只授权上述新增局部机制的fake开发，不重复A/P/F、来源或账户协议审批，不改变实际配置、资金、研究/候选/测试网/实盘门禁，也不等于确认方案已完成。

### 6.4 B的分层WIP记录（当时未联合验收，最终结果见§9）

用户批准后原两项owner绕行在当前源码再次真实RED，随后最小B与原request恢复共6项通过。新增闭包替换、复制并重绑自引用、失效/重复/错线程复用均先保留真实RED，未用元数据或放宽SDK检查掩盖。原fresh AST查找器不能定位try内owner的实现缺陷也单列为9 failed/5 passed，再经5项小型词法作用域RED→GREEN修正；原失败/线程警告没有被重标为通过。

实现仍为同一次原SDK调用：私有活生成器frame绑定实际安装的fetch对象与原owner，fresh-compile核bridge、实际嵌套current/owners/failure及原bound fetch，原31个SDK声明和5个Entry继续完整核验。独立普通局部变量保存实际安装对象，不能靠重绑自引用cell把副本变成本次owner；失效/重复/错线程先纯拒绝，不调用失败writer，只有已证明本次归属的current来源失败沿原语义发布。原Session尾守卫继续核完整L2及旧monotonic窗口，未重采、重签、增加默认预算、registry、表或sender；两处finally只恢复自己仍拥有的状态。

CPython3.14原88851自然exit0，38 passed/0failure/error/skip、CLI无warning，XML1450.639s（CLI1450.70s）。原件`chanpy-native-fetch-joint-py314-1b61f84d0267401c927344715c980f0e.xml` SHA `9747bcd9847e61b416dc343a391a9a644178e27f536df48997060bb6047e71a6`；38个唯一case/status SHA `2ba64017ffad8deeb6ee2abdc66aef53d39a1f22c6b415264791a73df9cbf364`。157个Trade/顶层tests源码启动/终态均`dab2304e4bf8c4c7cd38339452a933f42e6b5fe386e29683c41d7de41cb1f215`，确认无活pytest后才落盘。

该38项覆盖等待换Session/request、四种DB归属变更且原/外SQL均0、三个实际闭包替换、四种fetch恢复/过期拒绝、六种SDK/bridge伪装、三种fetch复用、依赖首次检查、五种AST，以及原A的request恢复/cleanup/重入/线程/旧窗口。它仅为所列源码3.14结果，另一解释器、完整SDK/HTTP/claim/终态/default/旧状态机、原fetch内部预处理及实际Requests传递路径仍需适用验收；不据此发布WIP或宣称A/B、C5–C7、OKX及整个Goal完成。

### 6.5 原fetch内实际预处理的继续审查

随后15项真实RED确认六个未覆盖的方法及八个camel/snake代理回调、旧proxy callable均先执行才拒绝。六个方法为prepare_request_headers、set_headers、check_proxy_url_settings、check_proxy_settings、check_conflicting_proxies、value_is_defined。不是另加第三hook，修补只将它们纳入原SDK fresh-compile循环，现为37个方法＋原5个Entry，原bound fetch/bridge检查仍完整。

共享SDK来源资格同时静态读取上述九个回调入口，仅接受None；不调用未知callback/descriptor以判断是否“安全”，不将callable或presence摘要包装成来源授权。它只校验实际加载的来源实现，不读资金、年龄、候选或kill-switch。该源码资格也适用于可能发布原生终态证据的已有订单查询；正常原SDK的过龄/kill/freeze查询与撤单必须继续工作。未验收的分散新风险接线已删除，恢复initializer没有被加新资金许可或年龄预算；自定义代理回调不由旧行为PASS推定支持/认证。

原47518为20项11 failed/9旧行为控制passed，原45152为明确查询来源拒绝9 failed＋正常管理3 passed，均保留原件。共享修补后原91689实际9 passed/0failure/error/skip/CLI无warning，XML250.013s（CLI250.07s）；原件`chanpy-native-fetch-source-smoke-a8a8d740e06344c2b57d3f9deb3b9071.xml` SHA `56958c9bd183acc098d279d0da2f374f4f079ee058f390d2951576478b95825d`，157源码`15b03c645c72e0d036b0f55998988a5963002271c56500d19843cbd231765c66`。范围含正常1 POST、方法/回调变异拒绝、读取前及L1后回调拒绝、正常过龄/kill/freeze管理；仅smoke，不是全部15/20项、新整模块或双版验收。完整SDK/execution/HTTP、claim/terminal/default/旧状态机与C7仍待，WIP不发布。

## 7. 原单POST的Requests自动重定向（A内最小修补；本节为B获批前记录）

独立验证保留原SDK和真正Requests.Session.request/send，只在该隔离Session已有HTTPAdapter.send返回fake；共享fixture对其他Session的全局no_http保持，测试专用trust_env=False不读取用户netrc/proxy。无redirect正向控制先实际通过，随后同源307、跨host308均真实产生2次adapter POST，说明A的单次request委托不能自动限制Requests内部send。错误的首轮夹具没有进入POST，已与有效RED分开保留，不能混作重定向证据。

最小修补只在A现有guard确认本调用线程、本单POST、原URL与verify后，给该次原request的kwargs设置allow_redirects=False；其后仍完整核原owner/L2/current和旧monotonic窗口，URL/headers/body/签名/订单参数不变。没有第二hook、Session/adapter/真实配置修改；非本单管理请求及旧契约不进入此分支。不把redirect响应当ACK，原claim/submitting未知边界和不得重下继续保持。

有效RED原8755 exit1，2 failed，各2 POST；`chanpy-native-requests-redirect-behavior-red-ee84b2af2cd749f2b349601ad246c51d.xml` SHA `2b01315f3894e6c2b82d26d536346b65a025179988cb0bde23d541d8f4d4fde2`。修补后原44947 exit0，3 passed/0error/skip，XML154.908s，`chanpy-native-requests-redirect-green-py311-911edf46e7074cf9bd51d7f1c8227498.xml` SHA `6423cb592d72a05b40721afa75cfa91a8a15131d14b8ea81d59a8e8302f1e25f`；该原件仅3.11专项，后续同源3.14联合见下，不是完整执行计划验收。两环境均Requests2.34.2/urllib3 2.8.0/CCXT4.5.89，未安装或更新依赖。

后续原26138自然exit1：3.14联合14项中12 passed/2 failed/0error/skip（9项相邻生命周期与实际依赖、3项Requests、2项§6 owner绕行），XML504.020s、CLI504.08s；`chanpy-native-requests-lifecycle-current-py314-d0842aa276264692be40ee9857f99ed6.xml` SHA `80f37282c28343085c7af624c9df7d1f67cf8f7863b4988d806d8bf8a413fc88`。Requests三个case两版ID/通过状态差异0；157源码前后均`7955570748a6a01c7c194d9928b7d091e7c1ce973f392baa9cf81951cb37fdf8`。两个owner RED在当前代码重新确认，不能说整体全绿；双版编译和diff检查只证明对应结构范围。

§6的Session/request重新寻址绕行没有被本修补覆盖，B仍未获批/未实现；当时adapter自身retry仍独立待验，后续正常重试配置的必要条件见§8，不等于全部传递依赖已验。不得以本3项通过宣布A、整个执行计划、C5–C7或Goal完成，不提交/推送整组WIP。

## 8. 实际order adapter的零重试必要条件（无新增hook）

原Requests/HTTPAdapter.send及urllib3.urlopen/Retry均真实执行，只fake pool._make_request并设置socket创建失败哨兵。两个total=0的成功/丢响应控制先通过；隔离Session的实际adapter允许POST read retry后，原SDK同一次调用再次进入底层fake发送点，共2 POST。原24521 exit1，1 failed/2 passed；另6种不合格配置、两个selector变异及一个实际依赖变异共9项前置拒绝RED，两个无关route/已有L2查询控制通过。不是新增SDK自动重试，也不是重定向；不伪称真实端点或真实网络包。

最小必要条件reader仅消费当前原SDK的Session，核标准Session、OrderedDict键及get_adapter descriptor/实际bound method，复用现有fresh-compile校验后才调用原selector选实际fapiPrivate/order adapter。只接受标准HTTPAdapter、真实Retry对象且total为真正整数0；未知/None/负数/bool/裸0拒绝，不设置、清零或替换用户adapter。无关route的非零配置不误伤本单。

reader在原金额自采入口首次调用前先核自身身份，并进入原selected runtime；A原HTTP owner检查持续复用它，含SDK等待后进入原request之前的使用点。没有第二hook、可转移许可、表/schema/资金模型/默认年龄或配置修改；仅返回None。已有L2管理不调用这项新风险必要条件，原GET/DELETE/恢复语义保留。

同源20项双CPython3.11.15/3.14.2各passed/0failure/error/skip，逐项ID与通过状态差异0：4项真实pool发送（含原SDK等待时晚改adapter而0 POST）、3项Requests重定向、6项不合格配置、2项selector代码/owner变异、无关route及已有L2管理2项、3项实际依赖首次调用前变异。源码157文件均`bffb43f47f4a7c0864e918257b6e530c2e76068fbf2e7a17a9408b7ccf0d2dbe`；完整原件与SHA见主台账。依赖版本未改。

必要配置条件不证明所有HTTPAdapter.send、poolmanager、连接实现或任意进程内修改受信，也不是服务器接收/锁额证明。B仍未获批/未实现；当前同源原49240重验两项owner RED仍各进入外来fake request一次后才报错，2 failed/0error/skip。新必要条件不能替代该绕行修补或完整C5–C7/OKX验收；整组WIP仍不commit/push，Goal active。

## 9. 2026-10-28原执行/恢复子链的fake联合验收

§7–8末尾的“B仍未获批/未实现”保留其历史证据时点；当前审批和实现状态以本节及文件首部为准。A/B不是单独另造sender：原Engine、原SDK、原SQLite/CAS/journal及原查撤/恢复消费者仍是唯一软件路径。两处临时hook只作用于已批准的同调用使用点，原bound fetch/实际闭包、37个声明方法、5个Entry、旧L2和旧monotonic窗口均继续核验；没有重采、重签、默认年龄、第三hook或实际配置修改。

最终157源码为`8e5a7bb821aafdd4d1e95951173e2fba51a1af4a5df2bafce06510f87c7f80dc`。CPython3.11.15完整109顶层测试模块自然exit0：7329 passed/2既有skip/1既有network deselected/24既有warning，7331个唯一case，CLI22108.34s。CPython3.14.2原完整运行的7327 passed/2旧诊断spy失败/2 skip原件保留；只对齐该单一旧测试模块并补验70 passed，其余156源码精确不变。两旧ID到两新ID的一一映射后，3.14组合证据与3.11完整运行逐case/status差异0，共同SHA `5ce273b8438483a08aaee90c029213e12343557e0306377ab640e5450ebaefe4`；不称两版最终树各一次全绿。十个金额模块共653项在两版完整运行中均passed，涵盖原claim/SDK/HTTP/终态/default及旧状态机兼容；原件、摘要、跳过/警告和整模块补验详见[开发验收台账](../reports/2026-10-20-crypto-full-version-progress.md)。

该结果支持本Binance条件金额软件子链的阶段交付，不支持真实端点、服务器锁额、实际价格/费用上界、全Python/Requests传递依赖信任或同SDK任意并发管理认证。已有风险管理仍沿原L2及实际账户/单位/SDK核验，不用新的资金年龄/candidate许可替代历史管理；未知状态仍保留预留，不因本地terminal或空pending释放。所有真实配置及candidate/testnet/live/研究门禁不变；OKX同等级原生金额路径、完整C5/C6和C7外部认证继续属于原Goal，未因本节完成而关闭。
