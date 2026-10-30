# 原有风险管理：模式/attempt与数量读取子步

日期：2026-10-30。本轮验证基线为full-version `f9588c8afd3b9158e126036cb085f6e6b6e96b75`加下列工作树。继续[已批准规格](../specs/2026-10-30-native-existing-risk-management-design.md)和[实施计划](../plans/2026-10-30-native-existing-risk-management.md)，不把读取子层当作管理执行或C5–C7完成。

## 改动、复用与边界

- 唯一生产改动`Trade/NativeManagement.py`：新增observe_native_management_quantity，复用原AccountRiskStore全库表发现/ledger/原金额roots、NativeAccountCheck journal prefix与完整历史核验、NativePendingOwnership归属及AccountReconcile原生position独立通道检查。没有新表、第二账本、资金公式、SDK hook或sender。
- 在原SQLite一致事务内按原record的open/close各attempt最后累计量独立重建剩余，精确核对projection和account/native leg；同leg不同记录/策略/表的数量不借用，one-way相反方向不以净额抵销。原native pending与本地同一关闭attempt消重，只扣一次；未知/缺失/错单位/错账户环境/归属不清拒绝。
- 绑定account/pending/原契约的同一unit池，拒绝contractSize漂移及symbol字典吞掉的alias。复用原完整journal证明并核总attempt数，无event的悬空attempt不能消失；后记录的成交不能被归给较早account端点。Decimal50沿用原Inexact trap，无默认数量/金额容差。
- observed_available_base_quantity为本记录未预占和该leg未预占能力的共同上限；存在活跃open/close attempt时新增关闭可用量为0。新风险availableBalance为0不被另造为关闭数量门槛。仍不做请求量/价格精度化、意图、claim、HTTP变更或占用释放。
- 原collect_native_management_sources在同次自采后调用这个观察器，显式升级为`chan-native-management-sources-v2`，保留原v1历史报告，不重封旧JSON。已选runtime枚举纳入实际数量依赖、直接使用的导入别名和冻结role mode；两个native_quantity_verified/operation_authorized标志仍false。纯reader接受的caller JSON只作观察，不能转交为操作capability。
- tests/test_native_management_sources.py的底层HTTP fake补齐该fake venue新增`.02`成交的position/account/full pending，原SDK/解析/归属/CAS未mock成功。新增tests/test_native_management_attempts.py冷one-way/hedged×long/short×open/close共8项；关闭setup仍只是原prepare/CAS/claim/ACK/report加底层fake GET，不称本管理角色已发送关闭POST。
- tests/test_native_monetary_engine.py共享raw fake只增加独立的请求端期望ID（旧默认123456，关闭夹具显式789123）；不能让坏响应里的orderId改写请求端断言。原坏取消响应RED先复现后修正，原21项明确测试组重新验证。tests/test_native_management_quantity.py共27项，包含跨表、预占、单位/时间/方向/历史及别名/mode负向。

## TDD与失败记录

原件根：`C:/chanpy/verification/native-management-cold-20261030/`。以下原XML均保留，pytest error计数均0；failed中含明确标注的fixture错误，不将它们全称为生产缺口。中间4/12/18/21/26/28项GREEN及25项联测不叠加为最终覆盖。

| 原JUnit | 实际结果/原因 | SHA256 |
|---|---|---|
| quantity-red-a0d22988fff74d4ca5994e31834c38b9.xml | 4 failed：缺数量观察器 | d12d5cff36f5858f0e48b56a21ca77497839a23e723136cebb9e1d0cbcc31ccd |
| quantity-units-red-986eec0f796346caab9fb3ccc291ea45.xml | 3 failed/9 passed：1项真实contractSize遗漏，2项fixture来源时间/原raw白名单问题 | 80931d335562f0d6f187dbeab50d23256ed74963ce9f8da61676ebad70dd3116 |
| quantity-chronology-red-1402d72c45c048af865d7c8080d532a9.xml | 1 failed/17 passed：未来本地成交被归给旧account端点 | 00f12e2e0950dabd37459659250ca79c3fae65846c8225bc6e3e97de45fe26fd |
| quantity-completeness-red-87953517d2f84f4db3f45da9ba106d4c.xml | 2 failed/19 passed：真实alias遗漏；orphan fixture先触发原client唯一约束 | 880de637d091d2c04cd33d4c81b5367c39ae3ffb8dc35870e19e05bdd0b5634d |
| quantity-orphan-red-cb1b4a66bfb34da999d15bf05880a48c.xml | 修正fixture唯一ID后真实1 failed：无event的attempt仍被漏掉 | 5994f703d4aa6cdb48f488ecb65cf9ff3b911f6b5a8f0d0b424e8996f839ebeb |
| quantity-owned-red-9207789d8a7e4c0587f21f8ab7106b3b.xml | 1 failed：同次source尚未绑定quantity/v2 | 2170320324b8a53636d351122a256aff72b2fcc587b1aa85106fd32d2c8c4e58 |
| quantity-alias-red-651426d11fd948ec840b803ce4dfbc04.xml | 5 failed：只核定义模块，未核实际使用别名 | 6aba3e16bdc505eb9017cff8ee042b5679bbbeb5a5912ba64a980add81dbeb68 |
| quantity-mode-red-cd625eae6273486eaaf1fbbe03f2b74e.xml | 1 failed：冻结管理role mode与engine mode可分离 | dafcb59c96d65b4bae3e030d0383c419ce6c4b063321482aa8228219af5f7490 |
| attempts-helper-red-9793a92f8163402c97f99e1a81739234.xml | 1 failed：共享fake随坏响应改变期望请求ID，提前AssertionError而非原SDK拒绝 | ec26a5089c9bf6b22b252b73dd2d70695c8ae2c2cbd8dd69925ad0915b55ec7e |

首轮实现误取history顶层record键的4项失败及随后定位诊断均保留。一次未指定独占basetemp的只读诊断还触发既有共享Temp pytest-current清理权限错误（原工具c83043），未修/删除共享Temp或伪称该诊断GREEN，随后统一显式GUID目录。关闭预占fixture另外真实抓到旧attempt时间和Binance币数/CCXT张数混用，修正fake原生字段，没有放宽生产归属规则。

早期attempts-first-6a6c702df2794fc5a0d4b22e610fb6d2.xml记录8 passed，SHA b22aac6691e1bf4a889cb96e4206ea70cbe338843998f9e152944406660b202f；恢复时原句柄缺失、系统已无pytest，故仅记XML，不补造原退出码。最终两套完整本轮原进程/JUnit已重新覆盖这8项，不借早期结果外推。

## 最终双版验收：同一185源码、478明确节点

实际先collect两版同一清单并冻结，再完整3.14、完整3.11，全部严格串行；运行中未编辑/编译或重启、跳过慢例。原进程均自然exit0：

| 运行 | 原终态 / CLI秒 / XML秒 | JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 477 passed/1 skipped/0warnings，1746.65/1746.478 | quantity-acceptance-py314-4ff134ddfb7b4b53b586621103cde42d.xml /264cc2b2b615eccc3a13ee2cedb838d5e12068d166cf9e727395b4c550a33076 |
| CPython3.11.15 | 477 passed/1 skipped/0warnings，2029.08/2028.896 | quantity-acceptance-py311-5087810650b243e5837dd8ff8b7a73fe.xml /e621e3ce40d8a16cb434bb168c58c25800cd7c3b4db2b853c7dc7af716e2f976 |

唯一skip是原`tests/test_account_reconciliation.py::test_cashflow_timing_ownership_and_channels_are_not_guessed[isolated_channel-position_cash_channel_unallocated-binance]`：Binance isolated现金通道未核，未补造来源或放宽门槛消除它。双版case/state SHA均`7d4271626a42087dab1039875b8da1014d3191dd661a2eee198e41f96177f5ff`，精确成员/顺序/状态差异0，无重复/遗漏。

14个完整模块：quantity27、sources17、attempts8、identity12、role39、native_pending_ownership95、account_reconciliation52、order_audit_history35、order_report_cas53、query_only_runtime50、trade_safety14、trade_state_machine13、M6 10、configured_paper_runtime32。另原native_monetary_engine仅3个明确测试组共21项：坏取消响应5、cancel→GET4、原查询三类型×四模式12；不称整个Engine模块或新全仓7405运行。

- 185文件（Trade递归py+tests顶层py）raw map SHA `effa7980f4b095270d556430fdc8afd2319b905dc86529ee9adab2117a11a079`，两版前后逐项相同。完整node/source/runtime/collect输出存quantity-selection-py314/py311.json，外部SHA分别`8dab1732693ab5801b91383e75de7bdbdf4b0601190275a589df6ba2460a0068`、`20430205bdaf9093973f063e851a88cda19375d091d8e28e2e7933c303e5f4ca`。
- 实际完整环境保持3.14/70包、3.11/71包，freeze SHA `6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`、`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`；真实metadata、导入前缀/user-site及两份requirements原SHA再次核对，无新依赖或版本更换。
- 独立复用原verify_recovery.py纯read_cases/check_cases/environment/sources函数，helper SHA仍`46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`，没有改旧helper/manifest或重标旧结果。最终quantity-final-audit-tool-result.json SHA `4d34649a6be8575546a3894cbfc31673ae946895596a9726291f48bc4e70e9d5`。quantity-acceptance-py314/py311-tool-results.json保留完整本轮原输出分块和终态，SHA分别`a86eee919a6dbd48416e60156a35da92e4607e0e650fd38eb715e92f9acca958`、`aee21779076acb1b92bf6f439c082850d884e636dcf8fe7eb05062f5fae04dac`。
- 5改动py双版compileall和diff通过。两套真实optional-free core前缀34/35包，产品导入前阻断socket/DNS；yaml/pytest/ccxt/模型/GUI等11包真实缺失，实际导入SafetyPolicy/CCXTTradeEngine/NativePreparation/NativeManagement均exit0/零连接。quantity-core-import-tool-results.json SHA `dc4e62bb6ae3c7f8cbd3efb08b1fdfbe51246be9c77dff054cae979a4e863716`。这不是无CCXT执行管理CLI。

主线程solo review核对独立累计/方向/单位、跨表完整prefix、单次预占、mode/别名枚举、v2接线、原角色锁、原坏响应真实拒绝及无新发送路径；未发现阻断本读取子步的新增已证实问题。验证属于基线加所列工作树，不伪称新HEAD重跑或完整C0–C7审计。

## 继续要求与未验范围

当前只新增必要数量观察，两个授权标志仍false，三管理CLI未接新角色，仍不能执行管理变更。纯reader的旧v3数量夹具不等于旧v3全历史冷自采/迁移已获验收；当前owned自采仍依赖原金额L2 scope。相同净仓位不证明期间无外部/跨策略往返成交，也不证明unobserved bot/copy等通道无单；完整原区间/执行归属、动作专用同次上下文、请求量与原SDK精度化/原生只关闭语义仍须完成，缺证据拒绝，不发明lookback或将JSON改成许可。

其后继续原CAS/OrderAudit账户串行管理占用、同调用原A/B使用点、原三个CLI和mixed fresh-worker闭环；取消动作不能把new-close可用量为0等同为取消许可，亦不能以资金/报价的无关新风险要求替代动作核验。原已知只读查询保持独立。以上均不是本次完成项。

实测CPU时长已如实保留，但窗口测试使用明确fake时钟，真实网络/CPU预算可用性尚未认证，不能靠延长默认预算或自动重采过关。OKX同等级能力、旧证明跨实现迁移、候选换代与外部C7仍未完成；股票暂缓。实际配置/凭据/候选、普通新风险门禁、资金、冻结研究/绩效、测试网/实盘授权均未改变，Goal保持active。
