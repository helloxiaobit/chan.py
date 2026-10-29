# 已批准查单专用冷初始化的实施计划

本线程2026-10-28已批准[限定查单设计](../specs/2026-10-28-native-cold-query-only-design.md)，继续同一C0–C7 Goal，inline/solo/fake/TDD。前置进程源码与3.14的110项结果见[进程计划](2026-10-28-native-configured-process.md)；不是最终生产变化后的双版证据。

## 最终离线检查点（2026-10-30）

本计划的限定实现、负向矩阵、同库五fresh-worker恢复及适用双版完整所选回归已通过；[完整验收报告](../reports/2026-10-30-native-query-only-verification.md)列出原件、179源码map、环境与74批摘要。两版各7403 passed/2原skip，7405节点/状态逐项相同，24原始警告；query-only完整50项和独立进程4项均通过。双版12改动py compileall、diff与主线程review已验；原2793自然exit0，无活pytest后才编辑。实际Lore/普通push以Git交付结果核实，不把HEAD552f09e工作树上的旧矩阵伪称新提交重跑。

下文保留TDD/旧缺失与分批历史。它们不是当前仍待测试的指令；非Temp新代际已完成37/37＋37/37。其他冷变更管理、候选换代、OKX金额、跨实现历史迁移及C7不因本计划闭合而完成，Goal保持active。

## 修改前的复用与清理范围

1. **RED**：最小配置和原SQLite下，直接调用原RestoreOrders CLI；kill/缺candidate/unlock时应能读取原恢复集合。先保留当前exit1失败，再实现角色。已有独立进程失败原件继续保留，不重标为GREEN。
2. **原政策与Engine**（`Trade/SafetyPolicy.py`、`CCXTTradeEngine.py`）：复用原模式/路由/凭据结构规则，原普通builder/构造/候选和每单权限不放宽。新增冻结的查单专用政策角色，原`assert_order_allowed`接口在此角色永远拒绝；无可翻转enabled/permit配置字段。构造参数显式typed、默认false，不接受调用者政策/准入收据。保留原SDK/来源/金额/SQLite，无新SDK拦截。
3. **共用变更入口**（`Trade/TradeEngine.py`与原CCXT方法）：复用通用层分派，在add/cover/partial-close/poll和直接prepare/place/cancel之前检查此执行角色。默认通用实现不增加普通Engine权限条件；CCXT仅拒绝查单角色，保留原普通取消/减少风险语义。避免复制四个完整订单方法或另建引擎/状态机。
   原`Trade/NativePreparation.py`的实际函数闭包枚举也须包括新增角色检查方法，防止新调度点成为未核验的可替换回调；先原runtime reader替换该方法的RED，再增加同一原枚举，不另写一套完整性校验。
4. **原配置入口**（`Trade/Script/TradeRuntime.py`、`RestoreOrders.py`）：只由原RestoreOrders显式请求查单角色；MakeOpenTrade及其他管理CLI的既有调用不变。原dry-run/paper共用配置仍须回归，查单角色也不能借dry-run分支创建/撤销新单。
5. **GREEN/负向**：只用临时配置/真实原SQLite/原SDK底层fake。核普通构造原拒绝不变、角色不能靠恢复unlock或改配置变可发送、所有变更入口在新意图/外部写前拒绝；未知GET保留原事实并非零退出，正常GET恢复幂等。独立四mode/side用例扩为kill/撤candidate/unlock/profile和过期旧输入下的同库混合冷恢复。
6. **验收与发布**：按实际修改重跑适用safety、订单状态、原native默认/current/金额、配置/paper/cycle/notification组合；串行双CPython、GUID JUnit/源码身份、compileall/diff/本地文档链接、主线程review、Lore/普通push/远端SHA。无活pytest时才编辑/编译/启动下一检查；失败修复及实际范围不得用前置110项冒称最终全过。

## 不变量和剩余项

- 查询可经原writer记实际ack/累计回报，不是数据库零写；任何原账户/订单/L2/实现证据缺失仍拒绝，不把未知查询变成释放/重下。
- 源码变更改变实现身份；不重签或续期旧L2，不能承诺旧实现跨版本自动迁移。历史reader按原约束验证，若旧实现不兼容继续闭锁、单独记录迁移缺口。
- 无新依赖、实际配置/环境/交易授权、研究运行、绩效读取、子代理、OMX或第三SDK hook。OKX金额、候选换代、其他管理动作的独立冷角色及C7认证不由本项完成，整个Goal不关闭。

## TDD和当前验证（尚未发布）

- 原CLI最小RED：`chanpy-native-query-only-red-py314-35326777d30e4f069006dbedb24f5e0d.xml`，1 failed/CLI1.97s；原因是实际RestoreOrders在查原空集合前仍要求新风险许可。新增冻结QueryOnlyTradingSafetyPolicy后，同最小用例＋原SafetyPolicy14项共15 passed/CLI1.92s。
- 七个变更入口RED：`chanpy-native-query-only-mutations-red-py314-9f4f2025d00542a78a365c8e6ad5ac43.xml`，7 failed/13 passed、CLI2.52s。直接dry-run prepare/place/add/cancel和空poll未拒绝，cover/partial先检查记录而非角色。原通用四入口/CCXT三入口添加同一执行角色检查后，原四模块80 passed/CLI6.57s；没有删除断言或向调用者新增资金许可。
- 原runtime闭包RED：`chanpy-native-query-only-dispatch-red-py314-3de1c7206be14eb2954a3f425ad8186b.xml`，1 failed/CLI2.94s；替换新增角色检查为lambda未被原枚举拒绝。仅把该方法加入原枚举后，同四模块81 passed/CLI7.17s。
- 独立fake cold GREEN：`chanpy-native-query-only-cold-green-py314-f00e48d1a85f44459a71119fceddbf4c.xml`，1 passed/CLI78.75s；真实四独立子进程，后两步在kill、缺candidate/profile/unlock和过期输入下运行原RestoreOrders，未知查询非零保留、健康原GET恢复，无第二POST。不是测试网/实盘或时延认证。
- 扩三mode×七变更、paper server字节/账本不变、非配置角色选择后，新role44＋原safety/M6/crypto契约/paper-runtime五模块共136 passed/CLI28.94s，`chanpy-native-query-only-paper-unit-py314-eef03c503f7a4eb4af34346eda5f9cc9.xml`。尚不代表完整或双版验收。

当前代码仍WIP，最终范围继续加入独立四mode/side的第五个进程：故意损坏原L2 canonical字节后，查单角色必须拒绝且不得修补原证明/重下。之后冻结同源码，显式只收集tests顶层112个test_*.py（不递归研究/正式任务），`-m 'not network'`运行全组；先3.14原终态，再同源3.11，不并发/不活测编辑。原109模块证据仅作基线，不替代本次六生产文件变化后的验收。

### 2026-10-29原完整运行中断后的诊断安排

原3.14 `39ae88b467df43d19b04815a1d715dd1`于10-28 22:48:59开始，主观察句柄79500/PID38040。先后观察到独立process模块四个F；最后已观察进度约47%，并非完整结果。10-29 00:35复查时句柄unknown、原launcher28244/pytest38040及所有pytest/进程fixture均不存在，最终JUnit也未生成。保留原basetemp/HTTP轨迹，不能补造终态退出码、全组通过数或删除失败；旧lastfailed文件时间早于此运行，不用它冒充本次失败清单。停止原因尚未核得。源码179文件摘要仍`2a65aafada574a947724f437c04bc82130a7fd6837c9073fa2e9de3f015e3281`。

先在确认无活测试后最小复现原process失败，再核静态审查发现的公开policy替换疑点：当前角色检查只看可重新赋值的`engine.safety_policy`，须RED证明同一查单Engine不可因替换为普通policy而变可发送。如证实，用构造时持有的原查单角色独立于可变的公开policy做拒绝，仍复用原检查与原SDK；不加通用sender/权限开关/SDK hook。此次修改前计划已说明范围；原policy/env/config测试不删，新增替换测试不得拿既有GREEN代替。

实际最小复现`chanpy-query-policy-and-process-red-py314-71a861281af04eb6bad4d9b20686a4a7.xml`自然exit1，5 failed/CLI89.68s：替换公开policy后四入口未拒绝；process0在直接UPDATE原L2时得到`sqlite3.IntegrityError: native order boundaries are append-only`。前者为新行为缺口，构造时私有保存原冻结查单policy并由现有七入口检查，不再依据可变的公开policy分类；后者为故障注入不正确，不放宽生产append-only校验。测试先保留原UPDATE拒绝断言，再沿既有`test_native_order_transition`模式在单一临时DB事务里撤guard、注入损坏payload并按原SCHEMA恢复guard，子进程只在guard恢复后才运行；不得用于真实库、补签或修改历史生产证明。

最小GREEN：上述四policy替换＋原role全组＋process0坏L2和原SafetyPolicy共63 passed/CLI95.62s，`chanpy-query-policy-and-process-green-py314-3a54f9bc79324b8fa51bbbd169c351d8.xml` SHA `958700f4c0f270bed29a242a837350948f1ce88b5f2590e84d3837139a19a817`；5 failed原件SHA `8ce1b5991ee7c941513ff0f92abe4596c76a625f381310f1fcff6c6a48120e52`。未称全量或双版通过。普通builder在本次复用清理中新增两个共享配置检查helper，原runtime实际函数枚举亦须覆盖这两个真实依赖；先各替换helper的RED后接原枚举，不另造验证器。

两个共享helper替换RED为2 failed/CLI3.81s，接原枚举后role/safety/M6/crypto契约/paper-runtime五模块142 passed/CLI32.08s。全顶层collect-only实取7405 selected/1 network deselected，112模块。此前整组无最终JUnit，后续不启动同样的超长单进程：以双版实际collection生成固定、互斥、无遗漏的node清单，沿清单顺序分批串行，单批以旧软件JUnit时长估900s上界（只是分组估计，不是性能承诺），每批原stdout/log/完整JUnit与源码map摘要独立保留。分组/expected清单写系统Temp的本任务manifest，不新增产品依赖/测试跳过，不把旧未完成运行的点或F当新结果。先完整3.14、再同一清单3.11，最终核全7405唯一集合/状态及原2skip/1network排除，不冒称一次全仓进程通过。分批差异/失败或源码改变均需如实使相关证据失效和修复，不扩大研究/交易授权。

10-29已实际完成双版collect-only：均7405/7406（1个network deselected），顺序完全相等，无case重排/遗漏；node list canonical JSON SHA `01730cfe2ad2d346185431ee7a4779d38eb3bd79e82e61571746847acd629e6b`。系统Temp `chanpy-query-verification-20261029/manifest.json`文件SHA `c7b18b0b2b2c94fa12578f6eec18b00c34a5ebc31fa75fcbc3dbd2785f830280`，payload SHA `c11e7f6be7adf1ad1f70174d1104173bc198d40df53f654f560282c7f21b1b56`；共37批，所有batch nodes串接精确等于原collection，互斥且完整。

manifest保存179源码逐文件raw SHA并以POSIX相对path字典、sort_keys/ASCII/canonical JSON计算source-map SHA `1a44946c062ce07e602cd2704a684160a1e486329d555479eb14a37ac5f3c123`，这是新明确口径，不与此前PowerShell排序的LF列表摘要混称。每批前后重读实际全map，JUnit的每个node和状态必须重建为该批原清单、代码exit0才接受；任何缺JUnit、失败、重复、未知状态或源码漂移均保留不接受。不是绩效清单，没有任何正式研究执行或经济指标读取。此处仅冻结验收输入，尚无37批或双版全通过结论。

3.14第0批已自然exit0：400个预定node精确匹配，399 passed/1既有skip（4条既有小样本XGBoost AUC警告），CLI602.79s、外层604.682s；原件`chanpy-query-verification-20261029/py314-batch-00-72867327281543d1ae7ec09315b3ebbc.xml` SHA `938cbc0166ae3f7a709d512f5bdc45e3511c82d9f6abc8912630c056da318091`。source map前后均为上列1a44946c；无活pytest后双CPython十二个改动py的compileall、git diff --check通过。此结果只覆盖第0批，不是37批完整结果；失败运行仍保留，未提交/push。

后续同源3.14第1–3批逐一自然exit0，均400 passed/成员精确匹配/source unchanged；CLI分别220.33s、324.88s、111.25s，既有警告分别9/5/0条。系统Temp同目录原JUnit及SHA：

| batch | 原件 | SHA256 |
|---|---|---|
| 1 | `py314-batch-01-a52978209be14645b89fdbebf8cc37b7.xml` | `e729f1a48a80f07bc063968568a3a05ee3028eba10d04cbb40b262df81c8fd39` |
| 2 | `py314-batch-02-e53eeaf55e9541dab20f097750792cf7.xml` | `9b5dff86fd267d610f168b851cb917fb27401c553b2cac4fe6005b5e71b6da65` |
| 3 | `py314-batch-03-cc05e861bd834d4eaa8f2c35133c3d99.xml` | `e6e670df1bcc48bbffc51e9f737478eb62c7ea90269fe5b9a64f1108ffdbdfdb` |

当前仅0–3批验收：1599 passed/1既有skip（Binance income无isolated position cash channel）、18条既有模型/弃用警告。四批1600唯一node与原清单相应片段完全相同，原JUnit外部SHA重新核对无变，179源码map仍1a44946c。未做新增跳过/过滤、未并发/活测编辑，3.11实际用例尚未开始，完整37批/双版/发布尚未完成。

接续第4–6批也逐一自然exit0：各400 passed/0warning，CLI537.35s、802.31s、26.80s；原JUnit分别`py314-batch-04-fde3db9d3143468381e0086fb72483a1.xml` SHA `67af057ffd9101fab57d5ed040374c72f20c4010a4780731a8903c68022807e9`、`py314-batch-05-6e9bc2ffdb314543a87053f14c628358.xml` SHA `23c84fc74fa7040147b1bb837259c0bdc14a3978a031eb4539621b0b68e1da3d`、`py314-batch-06-0ca0df20bf3c4a29997f63a42dce730e.xml` SHA `190da6739d15ce4c11beae2120d920c19121324afd219490f4e39d317aae9c0f`，均在同一Temp验证目录。

第5批包含完整20项原配置CLI、4项新的独立进程矩阵（每项5个fresh worker＋原同一SQLite；坏L2拒绝且总POST=1）和相邻原生来源模块。至此0–6批合计2799 passed/1既有skip、2800唯一node。主线程独立重读全部七份原XML、外部SHA和result JSON，重建node/状态精确匹配原manifest且无重叠，当前179源码map与冻结map完全相等。新源码仍未提交，3.11尚未执行实际用例；不把七批当完整37批验收或真实认证。

随后第7/8批各400 passed/0warning，CLI20.33s/67.49s，自然exit0。原JUnit `py314-batch-07-6db7d60727d14d4f8724d3a07fffc67c.xml` SHA `b6653f57945cc341f8d68a3846379e1c48431f3f6b451c1ea845ecf5f69aea86`，`py314-batch-08-5d24193a4614494bacf4db63a61f7914.xml` SHA `cf9abea4292e29f8fb09883bc39e35845069535233c92735909539f04d51a398`。累计0–8批3599 passed/1既有skip、3600唯一node；九份XML独立重建case/state逐项符合原片段且无重复，源码map仍未变。下一步仍按冻结顺序运行9及之后的原金额claim/default-entry/SDK执行等剩余批次，不新增过滤/跳过；完整3.14和3.11及发布仍未完成。

第9/10批也按原顺序自然exit0：288 passed/58 passed、均0warning，CLI699.05s/688.32s，外层700.659s/689.520s。原件同在上述Temp验证目录：`py314-batch-09-b695435ddf374ac0bcd23a6c5a4f18fb.xml` SHA `f8ed2bb2f85e85b1d391202b2be6d198b4890fa22976b7562e734654b91e2895`，`py314-batch-10-e53268b547ac41a185b5fe0d61ccdecb.xml` SHA `3016e0b77db372d30f40ac42c9ac59c0048365ffa55c8f53c9ce473de25530b0`。主线程在确认原进程全部结束后，独立重读十一份原XML及result JSON，逐项重建node/state、核外部SHA、无重复且按序精确等于manifest前十一片段；当前179源码逐文件map仍完全相同。

截至该检查点，3.14仅完成0–10共11/37批，3945 passed/1既有skip、3946唯一node、18条既有警告。后续从第11批继续同一冻结清单，3.11实际用例尚未运行；未因慢用例添加跳过/缩减范围，未并发或活测编辑。本次只在无活pytest时登记文档，不改生产/测试源码，不冒称双版全量验收、C5/C6完成或本轮已提交/push。

第11/12批自然exit0：分别7 passed/6 passed、均0warning，CLI603.18s/642.51s，外层604.392s/643.669s。原件`py314-batch-11-4ece7673de5a4bb7ab20c4aa0e2f29b9.xml` SHA `877e0edb93bc32d2013737629ba3941198c55b6989c4a47e00e162dc313bf438`，`py314-batch-12-9c13fe76d0ed4b478df7f9a522aaa863.xml` SHA `1dd121f91c8b7d22a8663669acb26e291acdebd07a988fc0c34ffaac2ddd7b2d`；目录不变。完成原76226后确认无活pytest，独立重读十三份原XML与result JSON，原件SHA、node/state、顺序和互斥性均符合manifest前十三片段；179源码map仍为冻结值，HEAD仍552f09e。

该检查点累计3.14的0–12共13/37批，3958 passed/1既有skip、3959唯一node、18条既有警告。本轮覆盖原默认入口claim发送、成交后原生终态来源与账户对账、市价/限价回读等预定片段，不能据此宣布其整个模块或双版全量已过。下一步从第13批继续；3.11实际用例、本轮完整验收和提交/push尚未完成，Goal active。仅在无活pytest时补此记录，生产/测试源码和全部实际配置/交易/研究门禁均未改。

第13/14批自然exit0：7 passed/64 passed、均0warning，CLI640.05s/633.98s，外层641.191s/635.203s。原件`py314-batch-13-9b5788628e514297ac6845f6ee228430.xml` SHA `01dd0b6b242c5ca11b6996e712f0825009fa927c19fee3268076bfe390b8666b`，`py314-batch-14-a806f96110b849d7b43862a17737ce58.xml` SHA `d18579757d152f7b2cafedce799b3d918e01e74feb29904c467ddf4f26371205`；目录不变。原49313及pytest全部自然结束后，独立重读十五份XML/result JSON，外部SHA、实际node/state、顺序和互斥性精确符合manifest前十五片段，179源码map及HEAD552f09e未变。

累计3.14的0–14共15/37批，4029 passed/1既有skip、4030唯一node、18条既有警告。覆盖原已知成交不能被未确认查询替换、原profile预算和SDK提交事实发布/时间边界等预定片段；尚未宣布整个默认入口模块通过。本轮主线程只读复核独立进程helper，底层HTTP/时钟fake仍未替换原CLI/SDK/准入/CAS，子进程不重新播种账本或生成准入证明；不是外部端点或服务器锁额认证。仅无活pytest时更新这两份记录，源码/配置/门禁均不改；下一步第15及后续批次，3.11实际用例、完整验收及本轮提交/push仍未完成，Goal active。

第15/16批自然exit0：16 passed/23 passed、均0warning，CLI661.13s/660.03s，外层662.296s/661.266s。原件`py314-batch-15-4ef317bf8d9b4eea8ec012565e74be14.xml` SHA `c6e08b04c8263875bffbce7da1bc0e23e0a824580ef142ede4ab367f470c1e75`，`py314-batch-16-bb6f8e580fad49d88a5640483d2839a4.xml` SHA `e7a6336e3a1385b6642fce3dc8c9814a41863db57c8a69f1490892ac2882aec0`；目录不变。原82328及pytest全部自然结束后独立核十七份XML/result JSON，4069唯一node/state及顺序精确对应manifest前十七片段，原件SHA、179源码map及HEAD552f09e均未变。

累计3.14的0–16共17/37批，4068 passed/1既有skip、18条既有警告。额外按完整manifest筛出`tests/test_native_monetary_default_entry.py::`的94项，再从原XML重建实际94项及状态，逐项相等且全部passed，才记录该模块在3.14冻结所选清单内完整通过；不据此宣称3.11、整个Engine模块或C5/C6已过。原Engine的claim/基础数量、reduce-only准备与已有订单查询等片段仍按清单续验。仅无活pytest时补这两份文档，无源码/配置/门禁改动；下一步第17及后续批次，完整双版验收与本轮提交/push未完成，Goal active。

第17/18批自然exit0：85 passed/10 passed、均0warning，CLI645.65s/639.14s，外层646.822s/640.300s。原件`py314-batch-17-47db344c00394dd09abac7ac52be8bee.xml` SHA `2e35267fbc179b4060f56772746f0cd9d35d463101bb219295f3881d52217cee`，`py314-batch-18-2f960afdca6446b6b32158c9fdd5d77e.xml` SHA `40e4e35061aa230f4f9fc519e324aa5b2b079789819c138944f9336b52bf3af4`；目录不变。原98425及pytest全部自然结束后，十九份XML/result JSON独立重建4164唯一node/state及顺序，精确符合manifest前十九片段；原件SHA、179源码map及HEAD552f09e均未变。

累计3.14的0–18共19/37批，4163 passed/1既有skip、18条既有警告。另从完整manifest和原XML筛出`test_native_monetary_engine.py`的76项，成员/顺序精确相等且全部passed；默认金额入口94项也保持同样完整匹配。两个模块仅在3.14冻结所选清单内完整通过，不扩大为3.11、完整执行链或C5–C7验收；原金额意图→claim→同一次原SDK POST的执行参数矩阵仍继续分批。仅无活pytest时补文档，无代码/配置/门禁变更；下一步第19及后续批次，完整双版验收和本轮提交/push尚未完成，Goal active。

第19/20批自然exit0：12 passed/5 passed、均0warning，CLI603.88s/589.47s，外层605.028s/590.721s。原件`py314-batch-19-3ace2bf478864798be566d3f4d51533a.xml` SHA `e2cc06ac7f51afea6c2058a4a4141faffcea6e2d1f6c6c58c23b930944c87d53`，`py314-batch-20-50fc20cc865b4d9e8456c7e496d0bec4.xml` SHA `b8ce8b92d347e2e5eadcae74ae38e523a13f468fc633e6d9b7b531e23846a182`；目录不变。原69665及pytest全部自然结束后独立重读二十一份XML/result JSON，4181唯一node/state、顺序与互斥性精确对应manifest前二十一片段；原件SHA、179源码map及HEAD552f09e均未变。

累计3.14的0–20共21/37批，4180 passed/1既有skip、18条既有警告；默认金额入口94项和Engine76项仍分别完整匹配manifest且全passed。本轮继续覆盖原SDK（仅底层fake）提交、错误脱敏、部分成交、撤单、原生账户及冷重启的预定执行参数，不代表完整执行模块、C6数据/模型全链、3.11或外部认证已过。仅无活pytest时补这两份记录，无代码/配置/门禁变更；下一步第21及后续批次，完整双版验收与本轮提交/push仍未完成，Goal active。

第21/22批自然exit0：5 passed/12 passed、均0warning，CLI583.54s/635.84s，外层584.798s/637.136s。原件`py314-batch-21-548b96e9db234886a83728da05f08bd5.xml` SHA `2cc1e58e0064c0e9df16409a79d8e6133ac6ae2e0897acb9e7c4f62c6c6f5147`，`py314-batch-22-bea21c24362b4f39b46a0f055becc773.xml` SHA `77bea1576c44b22f70afe6685b0549ec0cc290242bd0581c900a33888a685200`；目录不变。原71282及pytest全部自然结束后独立核二十三份XML/result JSON，4198唯一node/state、顺序与互斥性精确匹配manifest前二十三片段；原件SHA、179源码map及HEAD552f09e均未变。

累计3.14的0–22共23/37批，4197 passed/1既有skip、18条既有警告；默认金额入口94项和Engine76项仍完整匹配各自所选清单且全部passed。本轮继续覆盖原SDK（底层fake）部分成交/撤单/账户/冷重启、取消错误保留未知状态、临时request恢复和fetch预处理会话切换等预定边界，不代表完整执行模块、3.11、C5–C7或真实交易认证通过。仅无活pytest时补两份记录，代码/配置/门禁未改；下一步第23及后续批次，完整双版验收与本轮提交/push尚未完成，Goal active。

第23/24批自然exit0：15 passed/13 passed、均0warning，CLI649.32s/636.60s，外层650.509s/637.838s。原件`py314-batch-23-34218d824be54870ae719205c3f715af.xml` SHA `2d74c63878cbeaa7d553c5e767e740b10e16a0f3e4a4875e7bb3e50fe9c27211`，`py314-batch-24-4545ac16ca4a43979422c1f74a55ed37.xml` SHA `143eb9765ecc05772fd47928304a85ff0a7d392362f98c1760edefc38c5c14d5`；目录不变。原36661及pytest全部自然结束后独立核二十五份XML/result JSON，4226唯一node/state、顺序与互斥性精确对应manifest前二十五片段；原件SHA、179源码map及HEAD552f09e均未变。当前分支仍full-version，工作树文件范围仍为本项已记录的六生产文件、测试及阶段文档，没有新增实际配置变更。

累计3.14的0–24共25/37批，4225 passed/1既有skip、18条既有警告；默认金额入口94项和Engine76项保持各自所选清单完整通过。本轮继续验证SDK等待期的会话/数据库owner、SQL前阻断、claim闭包、fetch恢复及完整桥接身份等预定边界，不代表3.11、完整执行模块、C5–C7或外部认证已过。仅无活pytest时补两份记录，代码/配置/门禁未改；下一步第25及后续批次，完整双版验收与本轮提交/push仍未完成，Goal active。

第25/26批自然exit0：10 passed/30 passed、均0warning，CLI620.44s/686.29s，外层621.603s/687.514s。原件`py314-batch-25-e0415d1c94bf4fffa265ceadae529d0f.xml` SHA `4e5937bda3e16195e50cfa8bb20b519679c0e06c540d1ebbd239f2e6f0c439fb`，`py314-batch-26-a9382504ddcd4481977e2b72cca03245.xml` SHA `e0b8542f44bd8ad10f5f2f55e4bf8d64a3a634082449f8b7085788719f68f517`；目录不变。原7058及pytest全部自然结束后独立核二十七份XML/result JSON，4266唯一node/state、顺序与互斥性精确匹配manifest前二十七片段；原件SHA、179源码map及HEAD552f09e均未变。

累计3.14的0–26共27/37批，4265 passed/1既有skip、18条既有警告。额外从完整manifest及原XML筛出`test_native_monetary_execution.py`的86项，成员/顺序精确一致且全部passed；默认金额入口94项和Engine76项仍保持各自所选清单完整通过。三个模块结论仅限3.14冻结所选清单，不代表完整3.14/3.11、其他HTTP边界、C5–C7或真实交易认证。本轮继续覆盖桥接复用、传输作用域、原HTTP adapter零重试、原窗口预算及profile漂移等预定边界；仅无活pytest时补两份文档，无代码/配置/门禁变更。下一步第27及后续批次，完整双版验收与本轮提交/push仍未完成，Goal active。

2026-10-29断点恢复时，原59386已报告第27批132 passed、第28批56 passed并自然exit0，但原隔离环境启动文件及Temp中的控制/JUnit/result文件均已缺失，独立核对无法完成，故不新增已验收批数或补造原件。当前179源码map、full-version/HEAD552f09e及原依赖表freeze SHA仍一致；全局包版本不同，禁止替代。按[环境与证据恢复计划](2026-10-29-native-verification-evidence-recovery.md)把新代际放到非Temp专用目录、恢复原固定版本、保持相同7405节点和37切分，并重新取得完整双版原件；此前27批计数仅为当时已核验的历史记录，不冒充当前可读取证据。产品代码、requirements、实际配置和门禁均未改，Goal active。

新代际a097f905的双版collect已自然exit0并独立核定相同112模块/7405节点/原37切分、179源码map；新manifest raw SHA a4e4d9ab、payload SHA396cb3a4，完整身份和固定依赖恢复证据见上述恢复计划。随后3.14第0–1批自然exit0，原8328全部结束后独立核800唯一node/state、两原JUnit外部SHA与前后源码/环境：799 passed/1原有skip、13既有警告，新验收仅2/37批；不混入此前已丢失的原件。主线程只读review未增加设计范围，两个分页fake移位AST完全不变。仅无活pytest时补记录，下一步3.14第2–36再完整3.11，仍未提交/push或改变任何实际配置/门禁，整个Goal active。
