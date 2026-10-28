# 原Binance条件金额路径进入配置CLI/运行壳

2026-10-28，基线`3a8dc558324f1ff5f633cc980f1ed24f6b91022b`已Lore/普通push且远端一致。继续[主C0–C7计划](2026-10-20-crypto-full-version-completion.md)C6及[已批准原生接入计划](2026-10-22-native-fresh-admission.md)S4；不是新的金额假设或交易授权。上一子链联合验收见[台账](../reports/2026-10-20-crypto-full-version-progress.md)。

## 已确认缺口

原Engine的Binance v4来源/金额/claim/L2/SDK执行及恢复已fake联验，但`MakeOpenTrade.main`仍对全部非dry-run无条件拒绝；`RunTradeCycle`也在调用原开仓CLI前保留`native_fresh_admission_not_integrated`常量。不能把库入口通过误称配置运行壳已接通，也不能永久保留占位拒绝替代完整版交付。

## 修改前复用/清理范围

- 严格主线程串行、fake、TDD；无活pytest才编辑/编译/启动下一测试，原运行观察超时不重启。无新依赖、实际配置/权限/研究/交易门禁修改，不请求真实端点。
- 只改原`Trade/Script/MakeOpenTrade.py`、`RunTradeCycle.py`及受影响测试/本文/台账；优先新增`tests/test_native_configured_entry.py`复用已有原SQLite、原SDK及底层传输夹具，不另造资金或订单引擎。
- 先测试原MakeOpenTrade CLI使用完整显式fake配置、原输入时代、真实quote producer、原configured engine工厂及cold原SDK；源/资金/claim函数不得mock为PASS，不把手造L2或替换engine作为整链证据。RED须因为原占位拒绝，没有到达原路径；夹具/来源错误与行为RED分开。
- CLI仅将支持的Binance/binanceusdm swap配置路由到既有`_native_entry_profile`校验，先核原完整profile/before，再读报价；每笔实际add_trade仍重新进入原guard/prepare/source/金额/CAS/SDK全部检查。配置路由或CLI返回码不成为准入收据；不新增enabled/permit/预算默认值或更改SafetyPolicy。
- 运行壳仅识别显式支持的原profile入口，随后仍调用同一个原MakeOpenTrade子进程；缺profile/不支持venue或market保持闭锁并继续原管理。格式或证据不完整最终由原CLI/Engine拒绝，不以父进程布尔值替代逐单来源。配置/输入时代漂移和报告写入失败继续阻断；不把新风险资金条件加给restore/query/cancel/reduce-only。
- 原dry-run/paper/股票行为、OS单实例锁、通知状态、失败/异常脱敏与原CYCLE输入摘要保留。测试配置与fake环境只位于独立临时目录/monkeypatch，绝不读取或写入用户私有配置/真实密钥。

## 验收顺序

1. 原CLI实际同次路径RED→最小GREEN：至少一个cold Binance long正向，实际POST=1、原v4/L1/L2/已知SDK事实、原输入quote字节可重读；重复CLI不重下。再扩long/short、缺profile/坏before/坏预算/缺候选或环境/kill/报价过期等失败，核无不当intent/POST/外来写入。
2. 原运行壳路由RED→GREEN：完整显式支持配置能调用原open stage；缺profile/unsupported维持拒绝，child失败仍执行全部原management，配置/输入/报告失败无open。fake command只验证编排，不冒称原SDK执行；实际CLI证据单独列明。
3. 适用既有`trade_cycle`、opening inputs/quotes、configured paper/runtime、notification及原native默认入口/原金额受影响范围串行验证；原不变源码的完整联合证据按身份复用，不能重标为新全仓运行。双CPython、独立GUID JUnit/源码身份、compileall/diff/文档链接、主线程review、Lore/普通push/远端SHA后才交付本子步。

本计划不批准候选换代/重新武装、OKX新金额/价格/费用模型、人工解冻或C7实际外部认证；这些不被本次CLI接通隐含解决，原整个Goal继续active。

## 首个原CLI边界与测试复用补充

原CLI测试先1 failed（返回1、未到达逐单链），只替换旧常量为原完整profile/before校验后1 passed，原SDK/原工厂/原writer未mock。下一步只将该测试已使用的临时CEnv/CYCLE摘要装配提为本文件测试helper，以供配置负向变异后重新冻结真实输入时代；正向断言不删。此前真实正向为测试清理基线，避免用故意不更新CYCLE摘要的夹具错误自证拒绝。

新非dry-run入口不能继承旧CLI的bench_price=1000默认；先用缺该显式金额且零quote/intent/POST的负向RED保护，再让原dry-run保留原默认、非dry-run缺值直接拒绝。候选/环境/kill/profile/before/budget负向也核全原账本保持；只在独立临时配置与fake环境中变异。父进程的完整或仅schema路由标识均不证明资金；fake command编排结果必须仍标native_admission_verified=false，真正CLI/每单Engine另行核全profile。

新增原父壳→原CLI输入时代交接用例：只把外部阶段传输作为fake command，open stage实际调用原CLI并消费父壳生成的完整child environment；实际SDK/来源/金额/CAS仍只fake最底层HTTP。既有闭合行情fixture不重做更新/信号计算，未真实启动独立子进程，不能将此用例称整个原生进程级闭环；须明确保留该范围。四mode/side CLI正向及负向已形成19项小集GREEN，再补此交接后进行双版适用组合。

## 当前证据与联合验收范围（尚未提交）

- 原CLI占位RED：1 failed，CLI2.78s，原JUnit `chanpy-native-configured-cli-red-py314-828c7d2ea8e44eccb3a67802afba28dc.xml` SHA `7d3afe81682984547e6e64570fc4bc49f4d18a098cb592c7d49fcf9a2cbd5617`。最小CLI接线后同一测试1 passed，CLI62.44s，`chanpy-native-configured-cli-step-py314-f7ff4ed5d58647e191dbb87fb8690c63.xml` SHA `8c1f6af98e1b788f31cba8e05cbeb0d9850b62affa705a9d219095ca16287197`，自然exit0。仅真实CLI变化消除原失败，不改原SDK或资金消费者。
- 新负向/父壳RED：6 passed/2 failed/1正向deselected，CLI66.39s，`chanpy-native-cli-policy-cycle-red-py314-2fc7230c69734ef9a3dedb4accbedc00.xml` SHA `9b466a4ece5bb1bd65882cc1f45242b1a5730472b1cfc50fcf7e69d1233f2823`。缺显式bench_price实际沿旧1000默认产生9.9数量fake订单并返回0；父壳完整声明入口仍被常量阻断。故只修改非dry-run金额缺省和原父壳路由，原dry-run默认、SafetyPolicy与真实配置不动。后续原两模块47 passed，CLI76.79s，`chanpy-native-cli-cycle-green-py314-b87ed77d96e6462593f6c85033a7696d.xml` SHA `982b03481b21642fb01a21fd0c943fa882f249fd2d586fcb19cd2ada4f52d44e`。
- 扩四mode/side、九种配置/权限缺口、父壳路由/失败继续管理、四种epoch/quote缺口的19项3.14小集全部passed，CLI257.30s，`chanpy-native-configured-matrix-py314-8671f37538984511b9035ec78a0d4b61.xml` SHA `80a9056218e92263cd1b98bb19f6a344433d89d6e2c694f6cea7663b0022767c`；父壳交接补验1 passed，CLI64.60s，`chanpy-native-parent-cli-handoff-py314-19a0ee3e1acf40f6995f9a5b8c91e7b6.xml` SHA `c5f56b6905e51d605257a42273504188de629cbbdd0135397b21eb2027c34d37`。原件均在`C:\Users\yangj\AppData\Local\Temp\`，终态后才改文件。
- 当前生产只有MakeOpenTrade/RunTradeCycle两脚本改变。原`OpeningInputs._evaluator_identity`已把这两脚本计入输入身份，因此旧输入时代不能补签续用；不把旧157顶层摘要相同冒称嵌套脚本未变。新组合必须保护原epoch/quote、paper配置/进程路径、通知/失败管理和native current。
- 双版明确运行同10模块：新native_configured_entry、trade_cycle、opening_inputs、opening_quotes、configured_paper_runtime/workflow/portfolio、notification_stage/observation、native_prepared_current，预期319项，以实际JUnit为准。使用同完整文件身份、GUID basetemp/JUnit、无并发或活测试编辑。先3.14，再3.11，结束后比唯一case/status、compileall/diff/主线程review及Lore/普通push；不称全仓再次运行，不重跑正式研究。

## 双版联合结果与主线程审查

上述同10模块在最终生产/测试字节下各319 passed/0failure/error/skip/deselection、4条既有XGBoost小合成AUC警告；新增native_configured_entry实际20项。两次均自然exit0，期间无编辑/并发测试/编译，未重启原进程。Trade递归全部py＋tests顶层py共175文件的SHA在两版启动、结束及联合复核始终`e11ea739a9cd5e98c4bae3aa61a606291c3cc1d5273a239855443e848218353e`，明确包含此次修改的嵌套脚本。

| 解释器 | CLI / XML秒 | 原JUnit（系统Temp目录） | 文件SHA256 |
|---|---|---|---|
| CPython3.14.2 | 1026.14 / 1026.032 | `chanpy-native-configured-joint-py314-1360739c872342768eb4e4d14de04d54.xml` | `579d656971eb16376ba24785ed20a038e44ef3a7bd7bf80d73aec8446b2cfc2f` |
| CPython3.11.15 | 1132.12 / 1132.000 | `chanpy-native-configured-joint-py311-6fd4f322f892428a807ef831699b8e67.xml` | `79e2b43285c21a3cdf5b242fe148cea8f82fcb4093a3707705ee08decf59111c` |

每份319个唯一case key；排序`classname::name|state`字节SHA均`0c499a8f694e28ecf84dc9e56566d8b1237b2c674ceb82a6bfa03bab67349a44`，逐项差异0。组合包含cycle38、inputs42、quotes54、paper runtime32/workflow8/portfolio12、notification stage16/observation27、native current70、新CLI20；原基线完整7329项属于上一子链，只按未变范围复用，不重标为这次全仓验收。

主线程按实际两脚本差异审查：父壳只作支持入口路由，完整或残缺schema都不能成为准入，实际child/Engine仍核候选、环境/kill、完整profile/before/预算、quote/input时代及逐单来源/金额/CAS；缺非dry-run显式notional现在在报价/SDK前失败。原dry-run默认、OS锁/阶段失败和全部管理finally路径不变；新代码复用原profile reader、原configured工厂及原开仓链，不增加权限开关、hook、表、金融公式/默认值或sender。双版三文件compileall及工作树diff检查通过，证据适用于同一未改源码。

本次软件子步达到适用验收门槛，可进入已授权Lore/普通push，但此文不预称Git发布成功。实际新CLI正向是四mode/side的fake live标签；父壳与实际CLI交接在同一进程中验证，外部update/signal/management阶段传输仍fake，并非独立原生子进程或真实testnet/live/端点认证。旧输入时代/未提交意图不能因新evaluator摘要被补签续期，已有L2管理仍读原历史来源。OKX同等级原生金额、显式候选换代/重新武装、完整C5/C6其余项及C7真实外部验收不由本子步完成，整个Goal保持active。
