# 已批准管理角色：锁定基础与本地原单身份子步

日期：2026-10-30。依据[已批准规格](../specs/2026-10-30-native-existing-risk-management-design.md)和[实施计划](../plans/2026-10-30-native-existing-risk-management.md)。本轮验证HEAD `7d7e639e78ff2d817eb22a85e3ffdc5f327c5e9d`加下列工作树；仅交付角色基础及本地身份读取，**不是管理执行全链完成**。

## 实现与简化

- SafetyPolicy新增冻结ManagementOnlyTradingSafetyPolicy，一般发送断言仍拒绝。复用原query-only builder的mode/route/凭据结构验证，不复制candidate/unlock检查、伪造许可或增加用户配置开关。
- 原CCXT Engine增加typed、默认false且与query-only互斥的management_only参数，构造时独立持有原角色。无本次操作证明时原七变更入口全部拒绝，包括dry-run、reduce-only；替换public policy或恢复环境不能升级。三个管理CLI尚未接新角色，普通Engine/原查单行为保持。
- NativePreparation原运行时枚举纳入两个已有风险角色builder，复用原fresh-compile检查；没有另写验证器或新SDK hook。
- 新NativeManagement.read_native_management_order_identity只从原SQLite/history/L2重建唯一原attempt、账户键、原contract及本地累计剩余量。复用原NativePendingOwnership契约检查、OrderAudit、NativeOrderTransition、稳定account_key、Decimal50和原数据库owner检查；没有新账本、表、发送器或资金公式。
- 原开仓/各关闭attempt最后累计量精确求和，分别核对原projection的open_filled_qty/cover_filled_qty/current_qty；缺历史、legacy snapshot、不可识别契约/账户、未claim金额L1、数量/投影矛盾均拒绝。关闭attempt的合成报告只经原writer/claim/ACK/report作为本地测试，不称真实关闭POST或原生持仓证明。
- 输出深拷贝finite canonical身份及原记录/历史摘要，native_quantity_verified与operation_authorized始终false。本地剩余量不是原生可关闭额度、跨调用能力或发送凭证；没有GET、写SQL、应用回报、释放或解冻。

## TDD与原失败保留

原件根：C:/chanpy/verification/native-management-cold-20261030/。以下原JUnit及工具终态均保留，未删除失败或伪称原13项现状刻画为新功能GREEN。

| RED | 实证 | JUnit / SHA256 |
|---|---|---|
| 角色缺失 | 1 failed，constructor不接受management_only；最小实现后新项+原query/safety共65 passed | role-red-py314-5725a0c5cf6e4cbf8b4f6456b75d5e09.xml / e40dba7cc4832283bd1fde7b8abebafcc1b9caa68b3ccd276ca08ff7e346b78c |
| builder闭包 | 2 failed/37 passed，替换两个builder未拒绝；只接原枚举后GREEN | role-closure-red-py314-85c8b261864343928ec977e169fc5c06.xml / 97c90f025a77e5ac9c7531260c41f854b9b6b2d2e2c53022b90d9b357be76ed5 |
| 原单reader缺失 | 1 failed，真实金额L2/原GET已到目标读取点，缺NativeManagement模块；最小reader后1 passed | identity-red-py314-0cf1b57698964ccda8ebb62c2b084433.xml / 6cdf42b8875e592647a657e522601fc5ed1153141c8fa074402e4f6151dfa8a6 |
| 连接晚替换 | 1 failed：在外来连接执行一次sqlite_master查询后才拒绝；将同一原owner检查前移到记录回读后、下个历史SQL之前后GREEN | identity-owner-red-py314-318f031c656f4dbe9d7bb3865a340f0b.xml / d0358bfb8e68aff100cc818534d973981b56b62cb28686da0b4da190fd47a70a |

## 双版验收：实际8模块608唯一节点

依次为角色基础组合541项、身份组合115项、原默认回归55项；前两组合重叠103项，去重后每版608项，而非相加711项。各lane严格串行、均自然exit0；3.14先于相同lane的3.11，无活pytest时才编辑或编译。

| 解释器 | 541项 / CLI秒 | 115项 / CLI秒 | 55项 / CLI秒 | 唯一结果 |
|---|---|---|---|---|
| CPython3.14.2 | 541 passed /186.62 | 115 passed /98.12 | 55 passed /25.00 | 608 passed，零failure/error/skip |
| CPython3.11.15 | 541 passed /199.90 | 115 passed /114.17 | 55 passed /27.07 | 同608 passed |

541组合两版各有1条原小样本XGBoost AUC警告；其余两lane无warning。实际覆盖：management role39、identity12、query-only50、trade safety14、native preparation438、M6 10、trade state machine13、configured paper runtime32。事后在同一不变源码/依赖上实际collect两版各608，顺序相同；独立从六份XML重建全部节点/状态、核suite计数/外部SHA、精确匹配该完整所选清单，去重和集合差异0。不是一次608项进程或新全仓7405矩阵，不把旧大矩阵当新源码全量重跑。

| lane | 原JUnit | SHA256 |
|---|---|---|
| py314/541 | role-closure-green-py314-3a1a28dfdee34b39b3350796edb4537f.xml | 7f01a196309f1469febeb1f37c2301cc11096f566e8e9c4515681a890c883ffe |
| py311/541 | role-closure-green-py311-8d2128606f43415b9788f62320ae0e84.xml | 4b2ab43971cafbc572ef97c2c8997fe9527dc4e48f58e7c0bfff372a0f1b58fe |
| py314/115 | identity-joint-final-py314-e3ce883dfd39480cb36fd9f26e0e79eb.xml | b0f786196354616e3eb408b8f5d395a3e1f4414cdb719ce3874048a5258cc029 |
| py311/115 | identity-joint-final-py311-8ca23d8672674a9c98aac832a5c154cc.xml | a596b7679cfa1536a1fb640a338f297ebcd5909df7d2d7cb1ad732fc36c5e7cb |
| py314/55 | default-regression-py314-3d2ffe9cb9db43639aa48a4c2c0eabb9.xml | 77a56fb3fd4b22967998bb8f6249c8eb8a9ea8a96965874ebdbc43775a8e2957 |
| py311/55 | default-regression-py311-301c51d86d18415fb5793c3f712f1514.xml | 88aa75209c075cd162cbe697c53a445c85f3bd21a825f4a8a83410ea91bc911e |

## 代码、环境与复核身份

- 角色组合180文件raw map SHA f23309c9f0b5af8b734060dbda42daaaf4045034adce69d53274002906068d8c；后续仅添加新reader/测试两个py，该180文件子集逐项不变，故按身份复用541项。最终Trade递归py+tests顶层py共182文件raw SHA map为a3aaa7ccd9aa6e75db6805b9a2aebd98fc62eebb386852fdc2fd86a933efd0d1。原frozen JSON保留在证据根，不混称之前179文件口径。
- 双版有序608节点/state共同SHA 9ab58f2468c76e3004ace39e50ed0a71bcb6257ed922de4129cbfcdabb6a6d16。collection-tool-result SHA分别803c43b011c7da117084f10f9a3e0ed51231fe065743a11dbc2e903f7763ecc1、f0c95b7178db2f1a641a36280f69d1c7380468384efe422a8f7bed04908593f9。
- 原完整依赖venv真实metadata复核：3.14/70包freeze SHA6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7，3.11/71包SHA9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e；无user-site，无新依赖/requirements修改。
- 六改动py在两版compileall通过，diff检查通过。另在两版真实缺yaml/pytest/ccxt/sklearn/xgboost/lightgbm/optuna的core前缀，先阻断socket/DNS再实际导入SafetyPolicy/Engine/NativePreparation/NativeManagement，均exit0、零连接；原件foundation-core-import-tool-results.json SHA d84e2f3083c86836d07504256b37f42ec6f30cdaff167f0631cd478281fc1872。不是在缺CCXT时执行管理CLI。
- 最终独立审计原结果foundation-local-final-audit-tool-result.json SHA954455f2c366190f84b4cb00f95e417a7de5f962d1de13b1a4976a0283d167c5。各测试stdout/退出在原工具记录，六份JUnit及后验collection/audit/frozen原件在非Temp根；没有伪装成本代际另一套原始37批完整verifier日志或新HEAD测试。

主线程solo review复核角色默认/互斥/普通分支等价、构造角色持有、七入口拒绝、原runtime builder pin、原history/L2/单位/累计量复用及DB owner前移；未发现阻断这个基础子步的新增已证实问题。缺项见下文，不能据本次测试外推整条管理链。

## 明确尚未完成

当前只完成实施计划第1步及第2步的本地身份子层。没有当前原生position/pending/报价的owned采集、可关闭量消重、账户级管理CAS/审计占用、管理A/B使用点、三CLI接线及对应fresh-process执行证据。管理角色仍拒绝所有变更；这不是批准目标的替代终点，必须继续完成后续步骤。OKX同等级金额、候选换代、跨实现旧证明迁移及C7仍未完成，Goal保持active。

未修改实际配置/凭据/环境、旧冻结研究/DB/绩效、SDK发送路径或普通交易许可；无真实端点、OMX、子代理、新依赖或表。旧证明不重封/补签；新增源码身份对旧模型/证明的影响仍由原reader检查，未验证跨实现自动迁移。推送只交付已验本基础层，不表示真实资金/测试网/实盘授权。
