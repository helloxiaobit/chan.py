# 原有风险管理：本次原生来源读取子步

日期：2026-10-30。基线full-version `e017e3da7d57b8b777c1708cead4ef136b0d7956`加本报告列明改动；依据[批准规格](../specs/2026-10-30-native-existing-risk-management-design.md)、[实施计划](../plans/2026-10-30-native-existing-risk-management.md)。基础角色/本地身份已先提交e017e3d；本次继续第2步的来源读取，不是管理执行完成。

## 改动与复用

- `Trade/NativeManagement.py`新增collect_native_management_sources：只接受原Engine/record/phase及显式完整来源政策、instrument和order年龄/跨度；本次自己读取原L2/scope、原SDK原单GET、当前instrument、账户position、完整regular/conditional挂单及两币mark/book。没有调用开仓candidate/模型输入或伪造unlock。
- 冷SDK沿原initialize_native_order_recovery_client构造；不接收caller缓存/源JSON，不刷新已有SDK或续旧L2。正向夹具实际删除自身临时配置/candidate后在kill下冷启动，仍从原GET重建；测试不访问或删除实际用户配置。
- 原SDK查询可以按原规则登记ACK/终态来源，但本函数不应用成交/释放占用。原生新累计量尚未由原report consumer记账即拒绝；本地剩余不是native可关闭能力。返回两个标志native_quantity_verified/operation_authorized始终false，JSON不成为CAS或发送capability。
- `Trade/NativePreparation.py`只扩原运行时枚举：guard为空时必须是构造保留的精确管理角色，并枚举真实管理policy，不借用普通开仓policy。普通guard/默认路径保持。原Entry核验器增加默认空tuple的声明来源入口参数，管理路径额外核实际GET Entry；没有第二SDK验证器、发送器、hook或新依赖。
- 固定原SDK/cache/路由/Session/request、配置、原数据库/连接/表、已选运行时与原记录历史；回调晚变在下一次原单GET前拒绝。instrument/order各自UTC与单调时钟年龄/跨度、总elapsed及原account/pending/market窗口在最终返回前核验，没有默认预算或容差。
- `tests/test_native_management_sources.py`共16个新用例。生产差异仅上述两文件；计划/本报告/台账另行记录，不改实际配置、普通/query-only门禁、金额A/P/F、研究或交易权限。

## 严格TDD原件

证据根：`C:/chanpy/verification/native-management-cold-20261030/`。五个原RED均自然exit1、error0，未删除或放宽断言。中间106/5/9/14/3项GREEN仅为各时点结果，不与最终624相加。

| 原RED JUnit | 原失败 | SHA256 |
|---|---|---|
| runtime-red-98e50eb6da4d4dc2b3e648752f11bb06.xml | 3 failed：原枚举仍读取不存在的开仓guard | 47f51f18acaec285ea6e3f5a63e1beb3cdd1932e001d3eda0e95cc081cd6cea6 |
| sources-red-57c45aaf76314afa89595e764879cbe6.xml | 2 failed/3 passed：缺owned来源collector | d1d049e4d51f385e60faf3e450556c32df54a20c45c613d9567c9fe78fd427ba |
| sources-owner-red-976e1f3e06f34864b43e28bd29516d29.xml | 2 failed：继承查单分派替换、instrument回调改原记录仍继续 | 0e147d77e57413bb73b99681ea2102ca81bd1af68cf8a16ba6fc056e283945ee |
| sources-tail-red-f86a7b78214b42d5a32ff45bc724d203.xml | 4 failed/2 passed：request/session/来源Entry晚替换及最终instrument年龄遗漏 | d927eb1e0f74129659b7730c5fccba8fb75a0d176b4c8b8c15be30184da35a58 |
| sources-elapsed-red-970166ecda80407fbb3c77a92444b5b3.xml | 2 failed：总elapsed尚合格、单个instrument/order预算已超限 | dbf08522ca7e6fd48709bf28d4aaf97959bce22c47edc8d4e53a0cd932023be4 |

## 双版实际验收

两版先分别实际collect相同9个显式模块、各624唯一节点，冻结后严格先完整3.14、再完整3.11；运行中无编辑、编译、并行pytest或重启。各自原进程自然exit0：

| 运行 | 实际结果 / CLI秒 / XML秒 | JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 624 passed /687.08 /686.971 | sources-acceptance-py314-fa49a9d242d04e75994405916a39c54b.xml /857f273c5ffe3f246cf68e8b4dfdcf5fa999485dc11d37656bd8b4bd193d9891 |
| CPython3.11.15 | 624 passed /792.64 /792.516 | sources-acceptance-py311-7f9fcbcf23be4b6d8ec622880adc56f5.xml /f2fd3b94832e88d10b0a1bc9a5d20f6aed87d0e0a029f5d767f6e7a2ad6baf5a |

各1条原native_preparation小样本XGBoost单类AUC警告，均无failure/error/skip；不是经济/模型质量验收。覆盖为sources16、role39、identity12、query-only50、safety14、preparation438、M6 10、state-machine13、configured-paper32，共624，不是新全仓7405矩阵。

独立复用原task-local verify_recovery.py的read_cases/check_cases/environment/sources纯读取函数，未修改该helper或其旧manifest、未重标旧成绩。helper SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`。重建两份XML全case/state，顺序/成员精确匹配各自真实collection，差异/重复/遗漏0；共同case/state SHA `fe851c96c5f27912ca535b50b5a0858b421c802a47642747082e1f825e24aadd`。

- Trade递归py+tests顶层py共183文件raw map SHA `359b4ebde9dd49036c99bd77347a150c11275bed6dca76d6222f7498bf9b1fd9`；前后逐项相同。两份sources-selection-py314/py311.json同时保留完整节点、源码map、原collect输出和真实runtime；文件SHA分别`c40bbe0e0583a7e696c4fc0950c17a4acff48b6dd97691d631c78c48870af1dd`、`3d68fc44bb13f75a26c0eb264ec342a8e6b4147314a30ad5070caca8debb7824`。
- 实际原full venv仍3.14/70包及3.11/71包，freeze SHA分别`6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`、`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`；metadata/导入前缀/user-site及两份requirements原SHA均重核，无新依赖/版本或全局环境修改。
- 两份sources-acceptance-py314/py311-tool-results.json保留本轮原终态与输出分块；collection/audit原工具结果同根。最终sources-final-audit-tool-result.json SHA `1a7a61dbf78f4fae5944814181baafa96f9482678cd1123f8cb9a429b0b097b8`，同时核五RED及双版原件、源码、环境；不是新HEAD或完整37批的重跑。
- 两版各3改动py的compileall与diff检查通过。真实optional-free core前缀仍34/35包；在任何产品导入前阻断socket/DNS后实际导入四原模块，yaml/pytest/ccxt/模型/GUI等11包真实不存在，均exit0/零网络。sources-core-import-tool-results.json SHA `30f2ac506ec9741cd7fbde59dbdcdb44c4c21d238e38b8bc168f5eb5f0ebe3d2`。不是缺CCXT时运行管理CLI或发送测试。

主线程solo review检查原角色/默认分支、同枚举/同SDK校验复用、记录和连接owner顺序、无成交应用/释放、各时钟尾检查和false标志；未发现阻断这个读取子步的新增已证实问题。不是全进程沙箱、服务器签名或完整管理能力审计。

## 剩余与下一步

当前正向新来源证据限于Binance one-way LONG既有开仓attempt，暖SDK与原冷SDK、两币完整来源；关闭attempt/hedged/多空、未知原单及其它venue的管理能力不由此外推。CPU/真实网络时延和生产可用性未认证，预算测试使用明确fake时钟。

继续第2步剩余角色/attempt覆盖，再第3步原local/native剩余与完整在途归属/消重，第4步原CAS/OrderAudit账户串行占用，第5步原SDK A/B管理使用点，第6步原三个CLI与混合fresh-worker执行。当前仍拒绝所有管理变更，未接任何管理CLI；不能以只读基础层替代批准的最终目标。旧证明不重签/迁移，OKX同等级能力、候选换代及C7外部认证均未完成。实际配置、资金、研究/测试网/实盘门禁不变，Goal保持active。
