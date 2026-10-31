# 原SQL依赖保护：双版离线验收

日期：2026-10-31。父HEAD `99096e4f6e5aea1a79b5db6e899be4e06530cb4c`加本次明确工作树，依据[批准管理计划](../plans/2026-10-30-native-existing-risk-management.md)。本SQL依赖子步已完成下述双版验收，不是CAS/HTTP/CLI完成或C5–C7认证；历史暂停/恢复记录在后文保留。

## 改动和复用

唯一生产模块`Trade/NativeManagement.py`增加私有共享的原SQL绑定读取：CChanDB原record/history/writer/close-intent/claim及CSqliteDB原query/query_one/transaction/execute。复用原`NativePreparation._function_identity`从当前原源码fresh-compile核实际body；事务仍为原contextlib薄wrapper和原闭包，不复制SQL实现或安装hook。同次owner保存原descriptor/body/code/defaults，晚换在PRAGMA前拒绝。连接必须为原SQLite类型及原Row/str factories；不支持caller回调作为基线。

复用发生在原runtime枚举和同调用owner，没有新依赖、表、资金账本、sender或交易配置。一般变更入口及JSON授权标志仍不变；原writer尚未消费该上下文。本范围不覆盖任意Python、SQLite trace/authorizer或全部进程依赖，亦非实际网络/CPU预算认证。

## 原件和TDD

原件根`C:/chanpy/verification/native-management-cas-20261031/`。原SQLite/history和SDK不mock成功，只fake原transport/时钟。

| 原JUnit | 实际结果 | SHA256 |
|---|---|---|
| cas-sql-red-20b8128aad1c4bd4a1c70ec49f0ddf6e.xml | 1 failure，118.08秒，20类未先拒绝/外来调用或SQL | 55f8e247b5cbecdbe5474c00b4fa6b140ad0c92da17c68fc6da9667e32a48caa |
| cas-sql-green-f916c9c6b97242abb0b31a2682f9286e.xml | 1 passed，91.58秒 | b519db9fe770dba2cd1d7f171577ee2deec7cdf59c4ee46ed2ec83e77035af82 |
| cas-wrapper-red-610e3c05ea1948469ae6ce65e2597228.xml | 1 failure，91.82秒，标准wrapper先读外来__module__ | 41cb282034cafc513ed51e2eb9465c344aed4f98ea9005301413613be12a9915 |
| cas-sql-focused-28734f32937a4a77b663dd6d7f1b30f5.xml | 3 passed，218.42秒 | 0b67120a587d18c5396c097bdcd3ea3464bae45abd6207f377003e373ea8426c |

首条原失败的完整SQL诊断造成控制台截断，原XML约2.9MB完整保留；之后仅将诊断改为精确SQL计数/首项，零SQL断言不变，没有删除/改写失败。第二条先RED后将精确函数类型判断移到contextmanager元数据操作之前。当前3项覆盖21类晚换、20类采集前外来依赖及wrapper元数据回调，均保持原DB/原HTTP轨迹不变；中间RED/GREEN不叠加进下述终验。

主线程按solo约束使用审查清单核修改范围及闭包/来源/兼容边界，无委派。当前NativeManagement raw SHA `15d2ff55c1a0b762c8560d54db04d4df87ab648338322284cafa58f9a8a40cc1`，新`tests/test_native_management_cas.py` raw SHA `8d87671d3911f2aa0a15c464f895e4ec3129d1858e98a9a9ddd902a283393f6c`。两版当前两py编译exit0；实际optional-free环境3.14/34包、3.11/35包中11可选包缺失，原probe四模块导入exit0、network_attempts=0，四源SHA与当前文件相符，原件见sql-auxiliary-tools.json。没有新安装依赖。

## 双版完整终态与独立审计

同一9个完整管理模块，按原顺序为cas3、context9、request54、interval52、sources17、attempts8、quantity27、identity12、role39，共221唯一节点。两版各221 passed、零skip/failure/error/测试warning，实际subprocess退出码0；完整节点/顺序/状态逐项一致，case-state SHA `9a9c37af8d892f21bd85503020dd630ea202dc38dd6093c48723362c09e96c81`。原3.14接受后才启动3.11，未并发、重启或跳慢例；不把原522/旧7405或中间3项GREEN重标为本轮再次执行。

| 原运行 | pytest / XML / controller 秒 | 原JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 6143.20 / 6143.080 / 6146.389321 | sql-acceptance-py314-6f1f2b4d3de241dfa82b596464fff4c1.xml / e73690bcca67e8e70fce0008e575b9367a6197b4402d0794f63804374e1dbdca |
| CPython3.11.15 | 6950.83 / 6950.696 / 6955.537171 | sql-acceptance-py311-7d90c118c6954b35bd9178ba22bf0f2e.xml / 19a5e7741318d187303dea0439da4bce57b7aefd9e713b3af0be9fd35522185b |

原3.11句柄68572自然终态b26fd9 exit0，result SHA `a7c55e17551f55fd08185043907ea354a321caf88800ff426fc522c1e2067db4`，log SHA `338ad2e565751490be2a73abafc804041fa63e51c5c367cf4bcd5bde43bc791a`，两版args SHA同为`3d1312e2f9cd2acfcb21eadc57a14a71d8d467978e3caf7957a12bc6f7d02006`。该次105份实际poll工具副本和104份中间只读观察保存在sql-py311-observations.json（仅此连续monitor cell25，不冒称此前各turn完整观察），SHA `5ddf89a00dd9c8232d682293b84eb64d3ee2d0bfb64683332ce5aa6ee3c99c17`；终态工具副本SHA `d2c0e03f8f5562f5dcde2fc6c6b7f873dab023b5c6cd4ec18a07a25b2cd52fc3`。3.14终态工具返回缺口仍按下节如实保留，只核原controller/result和完整原件，不伪造返回。

190源码map前后仍`936bc8fba841951f32f280b3e0f255a9a5e8c8d5d8d0a6db5adae8627e374da9`，manifest仍`4542c46faa63ef21fa431ba4ed0cee8ff8fb057a2d67d2ae966854b472a9bbc6`，runner verify_management_sql.py仍`9f25798e46ce214cfcd6579a2388f517b8d44f6f99aa8aeb185935e71f28c5ec`。真实完整环境70/71包、解释器/prefix/pyvenv/user-site/包版本、requirements及源码前后完全匹配；对上轮189源码，仅NativeManagement改变并新增cas测试。无依赖安装或实际配置变更。

独立audit_management_sql_resumed.py仅复用原verify_recovery.py纯reader。首跑d824d3因审计脚本复制时残留verify_management_context.py旧文件名而失败，原工具副本保留；只修正该审计路径，不改manifest/runner/result/log/JUnit或核验条件。之后280c08 exit0，原canonical/seal、真实退出码、raw XML/log/args、完整成员/状态/无重复、源码/环境与上轮未变范围均独立核对通过。审计输出sql-independent-resumed-audit.json SHA `ce10444e6b71ae51e1b3535efe1d74a7df77d5d1f2009346ef014be59a98cab8`，审计脚本SHA `da1a157eef4c4489a5f90455ed4a92e8bbea577d4e6b07fa8a52ac00985be7f3`。原初版审计脚本保留，不回写旧证明。

此前同一两py双版compileall和实际optional-free导入原件仍适用：源码/环境未变，无理由重跑已成功检查。辅助工具SHA `e7e406a8e5cb141ab6a62635b15c623e6012277bc8d70a16779f7ab1ba11201d`，TDD工具副本SHA `40619736f65a9c6dcea4eebf52f59153897583eddbda6eb8827e06e4650a3ab3`。双版结束并确认无活pytest后才改本次文档；主线程solo review未发现本子步范围内未处理的阻断问题，但不能据此声称完整管理写或任意Python/SQLite沙箱。Lore/普通push以实际Git记录为准，验收对应父HEAD加冻结工作树，不冒称新HEAD重跑。

## 暂停、恢复与冻结历史（保留当时状态）

### 用户暂停和恢复：原3.14终态已核，3.11待验

原3.14句柄84556运行中，用户将Goal暂停；按请求终止只读observer cell204，不终止pytest、不改文件、不启动3.11，Goal工具返回paused。用户随后恢复active。恢复时原句柄已不存在，系统无活验证进程，但原runner完整result/JUnit/log均已发布：221 passed/零skip/failure/error/warning，CLI6143.20秒，controller6146.389321秒，实际subprocess退出码0。不是中断partial，也没有理由重跑此已接受清单。

原`sql-py314.result.json` SHA `6386748c78ca09429e34b303fd947447078c0859f6b5773542759a2ac729aa5c`；JUnit `sql-acceptance-py314-6f1f2b4d3de241dfa82b596464fff4c1.xml` SHA `e73690bcca67e8e70fce0008e575b9367a6197b4402d0794f63804374e1dbdca`；原log SHA `f94bcb2724fdd83739fc6c06936cf35435e93d890ac5685c67b440cdea01f000`；args SHA `3d1312e2f9cd2acfcb21eadc57a14a71d8d467978e3caf7957a12bc6f7d02006`。原终态工具返回未获得，不能伪造或把恢复查询exit0当作原句柄返回；原controller的实际退出码与完整工件独立验证，见`sql-py314-resume-observation.json`及`audit_sql_py314_resume.py`，afda4c exit0。恢复审查重读canonical/seal、原args/log/XML、完整221成员/顺序/状态、190源码/两版真实环境/requirements及精确Git，全部相等，case-state SHA `9a9c37af8d892f21bd85503020dd630ea202dc38dd6093c48723362c09e96c81`。

未修改原manifest、runner或result/log/JUnit，原审计脚本也保留；新增独立resumed审查明确记录终态工具缺口，消费固定SHA的恢复审查，不补造terminal工具。旧逐次观察的内存副本当前不可读，不伪称已导出完整副本；正式工件仍完整。恢复编排先有变量重名解析错误、随后文档context字符错误，分别在解析阶段/patch校验时停止，未触及pytest或原证据；检查实际文件后纠正，见sql-resume-script-notes.md。当前仅3.14接受，3.11将按原221完整清单串行运行；双版终态/独立审计及本SQL子步Lore/push仍待。

下一步冻结新增3项加原8完整管理模块218项，共9模块/221唯一节点、190源码及原70/71包完整环境；3.14接受后才启动3.11，保留原GUID args/log/JUnit/result并独立配对成员/状态/源码/环境。无活pytest才改文件，不重跑或重标原522/旧7405为本轮成绩。两版及独立审计接受前，本SQL子步不Lore/push。

上述freeze现已exit0：两版完整collection顺序/成员一致，模块计数3/9/54/52/17/8/27/12/39，`sql-selection.json` raw SHA `4542c46faa63ef21fa431ba4ed0cee8ff8fb057a2d67d2ae966854b472a9bbc6`，190源码map SHA `936bc8fba841951f32f280b3e0f255a9a5e8c8d5d8d0a6db5adae8627e374da9`。freeze不是执行通过，当前先启动原3.14完整221节点，3.11必须等其接受；没有把3项focused或原218混计为本轮终验。

之后继续原CAS的唯一intent/claim增量、版本化OrderAudit digest/reader/header、稳定账户跨币占用与未知不释放，继而原A/B两使用点及三CLI/fresh-worker。NativeOrderTransition的open-only表不改；不把当前全等/JSON当写后许可，不新建另一ledger/table，不重采/重签旧L2。OKX、迁移、更广E2E和C7仍未完成，整个Goal active，实际配置/凭据/资金/研究/测试网/实盘权限均未改。
