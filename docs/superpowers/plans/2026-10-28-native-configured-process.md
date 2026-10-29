# 原生配置入口的独立进程证据

基线：`552f09e83bd4ba21a0209452e1dedaf844fd7d2b`，已普通推送且远端一致。继续[完整版主计划](2026-10-20-crypto-full-version-completion.md)C6；[原CLI接线](2026-10-28-native-configured-cycle.md)的同进程交接不是独立进程证据，整个Goal仍active。

最终检查点2026-10-30：用户后续批准限定query-only，实际四mode/side各五fresh-worker、原同库混合历史与坏L2拒绝已在两版全部通过；准确范围及74批原件见[双版验收报告](../reports/2026-10-30-native-query-only-verification.md)。下列“待批/前置”均为当时事实，不是当前许可或完整C6结论。只fake底层运输/时钟，原CLI/SDK/CAS/SQLite实际执行；其他冷管理变更及外部认证仍待。

## 修改前的复用/清理计划

- 先只补测试装配和证据，不预设生产修复。复用原`native_capacity_prepare_case`的两标的混合旧历史及原配置/报价helper，父进程只创建一次SQLite历史；每个子进程不得重建/重播/补签该历史。
- 测试原始响应可导出到临时fake场景，严格只含合成原生GET响应和fake订单传输状态，不包含真实配置/密钥或可用于生产准入的替代收据。复用现有raw execution/wallet分页过滤，不增加资金公式、余额账本或第二个订单状态机。
- 独立Python进程先固定测试时钟与底层Requests fake，再执行原`Trade.Script.RunTradeStage`和目标CLI。保留原SDK工厂、方法、来源、金额、L1/L2/CAS和SQLite；不mock准入结果、engine、claim、source consumer或成功退出码。
- 出站仅允许明确的合成GET/本单POST路径，未覆盖路径直接失败；底层网络另设阻断。保留冷SDK的spot/inverse/货币元数据读取，不能靠删ALT旧单或改SDK加载选项掩盖混合恢复。
- 首先核独立开仓进程产生一次原SDK POST、持久化原L2和SDK事实，再由第二独立进程重复原CLI核零额外POST；扩原restore/query管理时仍保留旧部分成交单和历史字节，unknown不释放、不重下。
- 只有真实测试发现生产行为缺口时，才先保留可复现失败，再最小修复原边界；不为测试通过重签旧输入时代、延长来源预算、添加价格/费用假设、第三处hook或实际交易授权。

## 验收与交付

测试装配诊断已区分两项，不称生产行为RED：原2,000ms component预算遇到“UTC冻结、monotonic仍实际流逝”时正确拒绝；对齐子进程两类逻辑时钟而不放宽原预算。其后原SDK已到达底层delegate，fake对bytes请求体未解码导致TypeError，沿用原order transport已有解码方式修复。临时异常observer只诊断、不替换任何结果，定位后删除。

独立开仓/重复已经走通后，撤candidate/unlock+kill的冷RestoreOrders实证在初始化处被阻断、零GET。该项不是已修复：[新的查单专用设计](../specs/2026-10-28-native-cold-query-only-design.md)已提出，待用户批准，不修改SafetyPolicy/Engine。当前先验证仍有原candidate/unlock且无kill的冷恢复，即使新风险profile缺失、旧输入时代过期，也只读取同一原SQLite/L2/混合订单；不得将此窄范围GREEN覆盖前述RED或称全部C6通过。

为避免子进程导入测试文件时经`test_m6_trade`提前加载目标CLI，清理前范围补充：把`NativeSources`/`AccountSourceIO`两个现有纯raw分页类原样移到无生产/pytest依赖的`tests/native_source_io.py`，两原测试模块保留import重导出供所有旧引用继续使用；子进程直接复用新位置，不删除sys.modules、不屏蔽runpy警告、不新写财务规则。原execution_facts/account_sources的既有行为测试作为此搬移的回归保护，连同新进程测试双版验证。

主线程串行，无活pytest时才编辑/编译/启动下一运行；所有pytest保留GUID JUnit，超时观察不代表终态，不重启原测试。先小路径核原SDK/配置/进程身份和同SQLite结果，再按实际改动范围做双CPython组合、compileall/diff、主线程审查和Lore/普通push/远端身份验证。原未改代码适用证据可按身份复用，不冒称全仓再次运行。

## 前置fake进程结果

许可完整单场景先1 passed/CLI79.58s，原JUnit `chanpy-native-process-retained-permission-py314-0e9fc4940e834637bc247b1d57985625.xml` SHA `d17508c4ecae9471152f4cd6b93223471bb3e4622944b047f1597e0e4d0c0120`。四mode/side＋原raw来源及CLI同四模块的3.14组合于22:24:39自然exit0：110 passed/0failure/error/skip、无警告，CLI656.19s/XML656.126s；`chanpy-native-process-joint-py314-6852934034a046c79b7116e8ea9705d9.xml` SHA `add893a3420418fdec0e960cf1fa68711f46a4b74057cd9cfd6ced684264030e`，110唯一case/status SHA `34adc7a5bf13c1f6dab91792d7237d82f35a5099b92f03a0e9eea4f2f5981187`。

Trade递归py＋tests顶层py共178文件，按原PowerShell `Sort-Object -CaseSensitive`的`path sha` LF拼接口径，启动/终态均`925dc2120a39e51774176d07e6062abb3c042d106020f2490b8cca7f32b1d38f`。去掉三新测试py、还原两个搬移前文件后精确重建原175文件摘要`e11ea739a9cd5e98c4bae3aa61a606291c3cc1d5273a239855443e848218353e`；两raw分页类搬移前后AST完全相同，没有生产源码变化。单场景中父reader起先因父测试钟落后子进程的新来源而拒绝；已仅让同一个fake逻辑钟跨进程持久并同步父reader，未放宽生产未来时刻检查。

上述3.14结果只属未改生产的前置证据；此后用户批准查单专用设计，后续生产变更需重新做适用双版验收，不能以此单版结果提前发布整子链。

只操作临时fake配置/环境/数据；无实际端点、密钥、权限/配置变更、新依赖、子代理、OMX、研究运行、绩效读取或自动解锁。不将该子步称C5/C6全部完成；OKX同等级金额、候选换代/重新武装、完整原生数据模型周期和C7外部认证仍分别保留。
