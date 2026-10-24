# V1 价格到原完整 book 的精确桥接与局部清理

日期：2026-10-25，起点为 clean/pushed `cb0808b8b55074b115050773c8a789194b59aec1`。继续[原完整接入计划](2026-10-24-binance-capacity-v1-integration.md)第3步，不改变A/P或原账户串行协议。executing-plans + TDD，主线程串行，不新增依赖/配置/实际I/O/权限。

## 修改前的清理计划

- 现有161 cost与79 envelope回归已保护原算术、拒绝和wire语义；169 leverage及109原账户适配继续适用。先新增真实失败测试，证明V1 R超过50位时能够按原分数精确进入非空全book，不把该分数截短成可过的旧decimal输入。
- `Trade/NativeOrderCost.py`：仅将原候选/单位/模式及R、Loss basis解析提为一个私有计算体，原公开成本签名/字段/金额与假设不变。V1桥接复用该体，不复制alpha/方向公式。
- `Trade/NativeMarginEnvelope.py`：原公开入口保留原schema与严格decimal候选输入。原body提为一个私有实现体；内部精确投影使用单独显式rational schema，不暗中扩大旧公开输入。两路径使用同一持仓/pending解析和 `_frame`，不得复制端点公式、删除关闭方向挂单或取hedge净额。
- 新V1 book入口只接raw完整book、raw实际候选和每标的Last/Mark，自己算R，不消费caller已算Cost/book/PASS。所有provided inputs哈希、canonical结果、输入末尾不变检查保留。费用/cash缺项不填0或USDT，纯book不声称完整资金。
- 后续按原第3步把同一价格/完整限额路径接原持久check及Last联合窗口，再按第4步接实际prepare/L0/L1/L2/所有消费者。该拆分不是降低完整验收标准；在完整费用适用性和全链未核之前，原资金/claim/default继续拒绝。

## 验收

六种订单路径、one-way/hedge非空四腿、partial/closing pending、非候选币，独立全部顶点参考。高精度Last的R保持精确Fraction；旧API仍拒绝ratio/覆盖参数、输出原字节不变。重复/错误模式、单位、bool/float/nonfinite、Last池缺失、来源observations重排、末尾输入变化拒绝；纯价格dict键顺序不是交易时序。双解释器串行、独立GUID/JUnit、无活pytest编辑；适用旧回归、compileall/diff、主线程review/Lore/普通push后记录阶段结果，Goal保持active。

## 费用币事实补充，非准入证明

2026-10-25定向读取[官方BNFCR说明](https://www.binance.com/en/support/faq/detail/0e857c392a2d47cebde0af762d9255ae)的Margin and asset modes段：credits模式固定multi-assets且不能切换资产模式。因此两份原生multiAssetsMargin=false可用于排除该模式，不仅是猜测默认值；它仍不单独证明USDT全部费用/税费适用性、当前费率完整性或原账户单笔额度。本次不将此事实扩成费用0或自动启用资金门禁。

## 本轮结果

已完成精确桥接，并在原NativeLeverageLimits/NativeAccountLimits内复用私有计算体接原持久check；新入口 `observe_binance_account_order_limits_v1` 仍只读/flags=false。Last的完整池/SDK与capacity严格一致，本地全窗/finish端点/每个native transaction时刻进入同一total/skew政策；每次Last reader后先查原owner再碰SQL，最后复验原L0。新API不接caller书本/Cost/PASS、缺Last不降级；旧API不新增Last读取或公开参数，未重封旧源。

新增150项（66 bridge、16 limits、68原check），含从cb0808b旧实现提取的8个完整文档SHA golden，保护原cost和原book字节。双版同11模块各1400 passed；原prepare/CAS/current适用组另各76 passed/9 deselected（本轮未重跑冷启动专用9项，不以旧结果冒充新跑）。全部0failure/error/skip/pytest warning、集合一致、7源码/测试SHA不变；双版compileall通过，详情见[台账](../reports/2026-10-20-crypto-full-version-progress.md)及[审计§37](../reports/2026-10-22-native-fresh-admission-audit.md)。完整费用路径、available/equity到完整Cost、受控prepare采Last及原L1/L2金额消费/全部执行消费者仍待；原资金/claim/default、OKX/C5–C7门禁不变，Goal active。
