# 原生查单验证环境与证据恢复计划

继续[已批准查单计划](2026-10-28-native-cold-query-only.md)和[币圈完整版主计划](2026-10-20-crypto-full-version-completion.md)，保持原C0–C7 Goal、solo/严格串行/fake-only及全部实际配置和交易门禁。此项是验证基础设施恢复，不是新的交易设计、权限或金额假设。

## 最终恢复验收（2026-10-30）

原2793续跑3.11第17–36批已自然exit0，末批171 passed/1原skip；最后全部原进程退出后，独立核定两版各37/37完整原件、7403 passed/2原skip、7405唯一节点/同一case-state SHA、24原始警告。两个collection stdout重新核定7405/7406及原1个network排除，全部74 XML suite计数/实际节点/状态、raw SHA、canonical封装、source/runtime/helper/requirements/配置身份均通过。无旧丢失成绩或partial节点加入；双版12改动py compileall和diff通过，主线程review无新已证实阻断项。

[最终报告](../reports/2026-10-30-native-query-only-verification.md)记录全74批XML/result/stdout外部摘要、两collection、179源码及完整环境身份。两版artifact-index SHA分别b02dc53fe0fcd0b28e2848575093afc963ca79ad9371284215c308324df4aadb、824aaaf87d4ecf5e3a51dc64dcedf5df82f892e98b6d829b6cf04232a2ba4ec9；共同case-state SHA 16ac9fffe85f2c9cc4dfe3a06e6e970bc6e061f19ad498c3c45f5784b0c92ccd。原verify_recovery.py和manifest不变，不以收尾探针修改原证明格式。

下文中断/旧检查点继续保留，不覆盖为成功。最终补充只读探针曾误取batch.nodes字段、并误把绝对路径index按basename计算，两个exit1原因已定位并按原格式纠正，重读后exit0；未修改原件或放松接受条件。完整恢复只支持列明离线软件验收，不关闭C5/C6/C7或整个Goal，也未附GitHub全量原始复现包；Lore/普通push以实际Git结果另核。

## 已观察事实与失败保留

- 原59386终态报告：3.14第27批132 passed/CLI717.88s，原XML SHA `a5e3a4e5462f690736a8f66dcc7e1edb39faf89d5f1cfbb66f63c95e0d437bce`；第28批56 passed/CLI644.14s，原XML SHA `c2198343bbeb1165336a7c2dcca8eba4e99fbe8a6a004cab33ddb608ce540bd7`；均报告exit0/source_unchanged/membership_exact。恢复观察时原会话已退出、无活pytest。
- 2026-10-29 16时许实际调用原固定3.14虚拟环境失败：`Scripts/python.exe`不再存在；3.11虚拟环境同样缺启动文件。原验证目录中manifest、verify.py、result JSON及JUnit均不在，顶层文件数0，递归只读检查也未找到保留文件；目录本身仍在且不是重解析链接。目录修改时间位于当天12:48–13:02，不能由此断言清理者或删除机制。
- 因而第27/28批仅保留上述原终端报告，不补造原件、不把未完成的独立XML/manifest核对标为通过，也不据此新增已验收批数。原0–26的4265 passed/1 skip、27/37批仍是当时已经独立核验的历史记录；不将已丢失原件冒充当前可读取证据。
- 当前full-version/HEAD `552f09e83bd4ba21a0209452e1dedaf844fd7d2b`未变，工作树仍是本项原有六生产文件、测试与阶段文档。用现存解释器仅执行stdlib只读重算：179源码map仍`1a44946c062ce07e602cd2704a684160a1e486329d555479eb14a37ac5f3c123`，顶层测试模块仍112。
- 已安装基础CPython仍是3.14.2与3.11.15，uv仍0.11.6。全局3.14包却是pytest9.0.3/CCXT4.5.43/Requests2.32.5/urllib3 2.6.3等，不等于原隔离环境，禁止借全局包伪装原环境继续验收。
- [安装矩阵报告](../reports/2026-10-22-python-install-matrix.md)的71/70包完整快照已重新解析并核其原freeze SHA：3.11为`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`，3.14为`6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`。两份requirements SHA也与该报告一致。首个只读解析探针误计表头，已排除表头后按原SHA核对成功；不是包版本漂移被忽略。

## 修改前范围与复用

1. 不修产品代码，不改现有requirements、用户配置、规则、权限、SDK/资金门禁或研究资产。文件缺失发生在原环境和证据层，不把它当生产行为RED，也不以新的更宽环境掩盖缺失。
2. 新建独占的`C:/chanpy/verification/native-query-20261029-recovery/`，置于System Temp之外；旧目录不覆盖、不删除。新隔离venv、安装缓存、原stdout/JUnit/result及控制清单均放在此根内，使用新GUID，不复用旧原件路径或旧SHA。
3. 复用原已声明依赖与安装矩阵固定版本，在专用隔离venv恢复3.14.2/70包、3.11.15/71包。先检查已有缓存，安装仍只来自原声明用途；必要包下载仅公开PyPI、禁keyring/配置继承，wheel-only，不安装或更新全局包。某固定版本不可恢复时必须停止并报告，不能默换版本或放宽声明。
4. 复用原task-local verifier的stdlib/原pytest调用、前后源码map、原JUnit独立解析、exit0及精确成员/状态检查。恢复helper不是产品依赖或第二交易验证器。原控制文件不可复原时建立新的恢复代际清单，旧manifest SHA只作为历史引用，不伪造相同payload。

## 新代际必须保持的完整范围

- 仍为全部112个顶层`tests/test_*.py`、原`-m "not network"`；完整collect应为7405 selected/7406 total、仅原1个network deselected。两版实际node ID顺序必须完全相等，canonical JSON node list SHA必须仍为`01730cfe2ad2d346185431ee7a4779d38eb3bd79e82e61571746847acd629e6b`。
- 源码map必须仍为上列179文件冻结值；不为恢复修改任何断言、跳过项、数据来源或历史证明。
- 原37批切分尺寸来自此前已捕获控制输出，保持原顺序：`400,400,400,400,400,400,400,400,400,288,58,7,6,7,64,16,23,85,10,12,5,5,12,15,13,10,30,132,56,400,400,400,400,379,400,400,172`。切片串接必须精确等于完整7405节点，互斥且无遗漏。旧原件丢失，不用历史时长反向猜造原manifest。
- 环境和原件恢复后，本代际重新运行完整3.14，再完整3.11；新验收从0计数，不将旧已核记录或第27/28终端报告混入新原件集合。各批新日志/JUnit/result write-once，失败保留且停止后续；没有活pytest时才改文件/编译/启动另一个检查。
- 在新清单记录基础解释器、实际依赖版本、隔离前缀及新证据根身份；恢复后不能声称新venv就是原已丢失环境，也不能因版本名称相同省略实际验证。

## 验收与交付

2026-10-29恢复实测：先尝试离线恢复3.14时，原固定`aiohappyeyeballs==2.7.1`不在缓存，安装exit1，保留原工具结果；随后仅从公开PyPI恢复原精确版本，3.14/70包与3.11/71包均安装终态exit0。实际metadata逐包等于上列快照、两freeze SHA精确相同，`uv pip check`均exit0，真实CCXT/Requests/urllib3/pytest导入均在新隔离前缀内，user-site=false；没有使用全局包或更改依赖声明。安装/验证工具原结果保存在新根`setup/`，它们不是产品测试验收。

task-local `verify_recovery.py`使用stdlib复用原节点/分批/源码/JUnit记账模式；其控制测试先观察10项缺实现RED，再GREEN，补充manifest封装、双版实际环境探针和节点状态校验的3项RED→GREEN，CLI入口1项RED→GREEN，总14项控制自检通过。这14项不属于原7405业务节点、不增加产品通过数。新manifest必须由接下来的双版实际collect生成，不以单元测试或缺失历史原件代替。

双版各14项控制自检随后均exit0；两版实际`--collect-only -q -m "not network"`严格串行自然exit0，独立重读原stdout确认各7405 selected/7406 total、仅原1个network deselected，112模块节点顺序完全相等，原node SHA与179源码map SHA不变。新的代际为`a097f90545eb420e8eef7058133085da`，manifest raw SHA `a4e4d9ab8277389949a5f66f0ecb4243c43a79c10e6b0241c6679ccc2b0fffb3`、payload SHA `396cb3a4fe9d66f71b9264efbc1c4872b84ca4c1d25b0685bb404dcf9943b7fb`；原清单SHA只作历史引用，没有伪造为相同新原件。正式产品验收数此时仍0，新一轮从3.14第0批开始，之后完整3.11。

先核固定依赖快照、requirements、独立前缀/user-site与pip check，再双版collect/清单/源码身份检查；按新清单严格串行取得各批终态。完整双版原件齐全后，独立重建全节点/状态及原跳过原因，核代码/依赖/环境身份与适用compileall、文档链接、diff及主线程review，才允许本项Lore/普通push/远端SHA复核。旧失败、旧中断及本次环境/原件缺失保留为事实，不删除或重标。

本恢复项不授予真实市场、私有账户或通知调用，不运行正式研究/preflight/绩效，不宣称服务器锁额、跨实现历史迁移或C5/C6/C7完成；整个Goal保持active。

## 新代际实测断点（仅当前已验范围）

2026-10-29第0–1批3.14都已自然exit0，原8328及其pytest均终止后独立重读新manifest/result/JUnit/stdout：800唯一node/state按序精确等于前两片段，0failure/0error，源码map179文件仍为1a44946c，环境前后身份等于新清单；799 passed/1原有skip、13条既有模型/收敛警告。原skip仍为`Binance income has no isolated position cash channel`，没有新增跳过或排除。

| batch | 新原件（均在新非Temp根） | SHA256 | CLI/外层秒 |
|---|---|---|---|
| 0 | `py314-batch-00-4e4274c34b9642168d03be2982ebb89c.xml` | `e87732597cdbc24d97338e34d55d48f98291a4da8fb2a59843211fb084bd7233` | 696.64 / 700.942182 |
| 1 | `py314-batch-01-0ef131b2181146569285b33c62cc12a0.xml` | `9991416b0199fc5493ea79e931913a2d711a770c54ec9f683d1c2f8606814928` | 220.62 / 225.597148 |

无活pytest时补此断点；产品代码、测试、依赖声明和实际配置没有修改。期间主线程只读复核六生产diff、查单与五fresh-worker测试及两个分页fake类：新共享类与HEAD原类的AST完全相等（NativeSources d837b67f、AccountSourceIO 54bd6603），复用原SDK/SQLite、没有新发送器或账本；该复核不替代剩余测试。下一步严格按清单继续3.14第2–36批，再3.11第0–36批。仍仅新代际2/37批3.14，不计入旧成绩；未提交/push，C5/C6/C7和整个Goal仍未完成。

### 第34批不完整中断后的续跑边界

2026-10-29 22:18（14:18 UTC）重新观察时，原工具句柄44921已不存在；两次系统进程只读检查未发现Python/pytest/uv，不能把此前“仍运行”的观察沿用到现在。磁盘实际保留新代际第0–33批完整result/JUnit/stdout；主线程独立重读其canonical封装、exit0、XML/log外部SHA、全部节点/状态/顺序、无重复、179源码map、helper/requirements/pytest配置及两版真实环境，均匹配原新清单。当前仅此34/37批3.14可验收：6432 passed/1原有skip、6433唯一节点、19条原始警告；第32批另有1条警告已计入，不把“无失败”写成“无警告”。完整所选native monetary execution 86/86、Engine 76/76、default entry 94/94、claim 59/59和cold process 4/4在3.14已核对通过；query-only runtime所选50项尚未进入已验收片段，仍不得宣称完整查单验收或3.11已过。

| batch | passed / skipped | 本代际原件 | SHA256 | 外层秒 |
|---|---|---|---|---|
| 21 | 5 / 0 | `py314-batch-21-21e6f0977e4a4fbb999ff17935ac72b2.xml` | `1ff9a78e6ea8567caa09569b22e2e2320ce8c79dde0c4632e78cf6ba23388406` | 591.151363 |
| 22 | 12 / 0 | `py314-batch-22-7e199fc051ca4325979055d99b12c96f.xml` | `b8aa61fa68d932fe347007b3cd67a833f79af425ed5c0823eba5a1b68551776b` | 597.887900 |
| 23 | 15 / 0 | `py314-batch-23-738eee17f7784b1990c57e7f426213d1.xml` | `eff5a81e89dd4b70ad8a8a76fcb6fe7e4e042890ce0d9c1c3a54c14aff9e0c55` | 635.094791 |
| 24 | 13 / 0 | `py314-batch-24-369e5ad6f42944f4b6f4f4ec9158763c.xml` | `d2eb7abf765433bdc51469280a8ea374783b71b23564939916cd64bbcc34100c` | 596.397550 |
| 25 | 10 / 0 | `py314-batch-25-452b4d475f8b49efbad8bd2f34ad721e.xml` | `c2074e5b9d249a0a42574b0c5ace45c8f2b1ab63897ce64bd73afb22054bbc3b` | 586.626276 |
| 26 | 30 / 0 | `py314-batch-26-74e8e85cf08e440cb92cdd127dda26b5.xml` | `8cbdcfe080fdc04df1583080cb95b7bd6a263928d420d67ce139dc5992682b11` | 647.230949 |
| 27 | 132 / 0 | `py314-batch-27-2ec45168b97f4b6e9a74a7541b95f55d.xml` | `3b3b9533207a9f9728eb99f38f28ec619d0320e3d570abf49e79a0968ac2fa92` | 702.546041 |
| 28 | 56 / 0 | `py314-batch-28-b9e2dd66c482435d84b11be21079cb9c.xml` | `7b2bffa3ca6880fe6724902086cbcd6c98cd979e6ebe7d908ae707dc93216a15` | 644.077301 |
| 29 | 400 / 0 | `py314-batch-29-846c4c3290654491a5bf6c60314b34da.xml` | `54012c5a029ed2ada99c594caebc8313fbc750f28755ca9178f72553e0095df7` | 456.865270 |
| 30 | 400 / 0 | `py314-batch-30-bd31a70118f443488dd915b08bd043cf.xml` | `eed23a3572834577096d558c710eccff0420086277a721f04e663fe95fa79209` | 319.646750 |
| 31 | 400 / 0 | `py314-batch-31-4cfebf14f4ca4705850431917f06dfcc.xml` | `ec770c6ccd8a2af214e36aea00ad24d3a7353c6e3e476afb34c34969efd8ca6d` | 110.492721 |
| 32 | 400 / 0 | `py314-batch-32-3a82e45cf8d4423fb6eebb3e85e68cd6.xml` | `6d6c2c5a292cfe65547fc2fa30f19626e5f618fe57db0f22fd371362c45ee06f` | 243.947255 |
| 33 | 379 / 0 | `py314-batch-33-6a257e24d6b94337b32553244c230d06.xml` | `7e6f021150726a4114227ee20d6db42d8b7fc3f3c8b61fa547f272b46f5398d1` | 722.651420 |

第34批原起始标记`py314-batch-34.started.json` SHA `b47940c3e7d9eafefa0a1bebd20cc5405a6a387a8f6af01b97134d50de9cb11d`、原400节点args SHA `e63b5597109b1c832d7365a9059d30197d1ad88331dc19ac0f6d592e4a797027`；原390字节partial stdout SHA `5ca5be4886e78e762388c39dce8cb543fee173dbaa772555c8238c6144b40f34`。无XML、无result，原退出码与中断原因未核得；不推断失败/成功/清理者，不计partial节点。逐项观察和前缀审计保存在证据根`interruption-20261029T141809Z.json`。

仅在确认无活任务后，把该已停尝试的起始标记原字节移动保留为`py314-batch-34.interrupted-20261029T141809Z.started.json`，不改原partial stdout、args或basetemp；这是可逆的本项验证工件归档，不删除原件。随后复用SHA不变的原verify_recovery.py完整重跑第34批400节点到全新GUID路径，再第35–36批，然后完整3.11第0–36批。新result仍按原封装/成员/身份门槛，不能用旧partial代替，不换证明格式或重算清单，不改产品/测试/依赖/实际配置/交易门禁。其余已核前缀原件和适用证据保持可用，不因一次中断从头重复已验收不变范围。

### 2026-10-30 01:13：3.14完整原件与3.11第17批中断续接

原78007句柄已不存在，两次系统只读检查均无Python/pytest/uv进程。不是观察超时后的推断：3.11第16批有完整canonical result/JUnit/stdout、exit0和23 passed（CLI769.99秒/外层773秒）；第17批仅有原85节点args、started标记及20字节partial stdout，无JUnit/result，原退出码与中断原因未知。partial不计成绩，不把本次进程消失推断成产品失败或成功。

主线程独立重读新代际全部37份3.14与0–16共17份3.11原件：核canonical封装、exit0、实际XML/log SHA、完整node/state/顺序/无重复、manifest、179源码map、helper/requirements/pytest配置与两版完整runtime metadata，均匹配冻结身份。3.14完整范围为7403 passed/2原有skip、7405节点、24条原始警告，case-state SHA `16ac9fffe85f2c9cc4dfe3a06e6e970bc6e061f19ad498c3c45f5784b0c92ccd`；3.11当前为4068 passed/1原有skip、4069节点、18条原始警告，case-state SHA `1c2a88a40fff48a0fec4276d3042f4373971ec522006d337a02a28d7df180633`，逐项等于3.14对应前缀。原skip仍是Binance isolated cash channel未提供，以及3.14原股票GUI缺PyQt6；没有新增跳过。默认金额入口94/94及独立cold-process4/4已双版通过，3.11的Engine仅32/76、query-only runtime仅0/50，不能据此前缀宣称完整查单、C5/C6/C7或真实交易验收。

第16批XML `py311-batch-16-120d974b8ae44974bf24241e37656aff.xml` SHA `365657505797e119089dedf321eb73730bb90c235abd9d4feccc39226e315aae`，result SHA `71932c17d1de9c2d5cdb8ce4273a1c7b7d6527e3b4f4c1ec708334b771a6475e`。第17批原started SHA `9bc6c62aa909339e181a51738b75d4c422e98f12a4677a8f46a2db400958ab15`、args SHA `ff810dac7b2762d01e4f67b075c487603d9030667c5d2bb7e2990e099b664e99`、partial log SHA `5ed321bce1f0091ed4b438161637abb3bc8b8e8e4e459d07f3a64593ea0e5b2c`；完整观察保存于证据根`interruption-20261029T171352Z.json`，独立审计工具bc47e2自然exit0。

无活任务时，仅将第17批原started原字节可逆归档为`py311-batch-17.interrupted-20261029T171352Z.started.json`，保留原args/partial stdout/basetemp。用不变的原helper（SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`）完整重跑第17批85节点至新GUID，再串行第18–36批。原manifest/37切分、源码/测试/依赖/配置/权限/研究与交易门禁不变；不重跑已核完整不变范围、不改变原result格式、不补造终态。剩余双版验收与本项Lore/普通push仍未完成，Goal active。
