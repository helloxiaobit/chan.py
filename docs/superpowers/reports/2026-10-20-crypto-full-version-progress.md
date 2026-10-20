# 虚拟货币完整版开发验收台账

用户在 2026-10-20 批准按 [C0–C7 计划](../plans/2026-10-20-crypto-full-version-completion.md) 开发并向 `helloxiaobit/chan.py full-version` 提交、推送。按阶段串行验证；Goal 仅在全部要求有结果后关闭。

## 交付身份与归属

- 开始时远端：`895fc700705e48013019a4054645e016a6e08d0e`。
- 开始时本地：`22a5a56ed1b38c2145106230c70256d4b7bc7bb5`，领先远端 44 提交。远端为本地祖先，可快进，不重写历史。
- 通用安全实现：`b04d2a6` 至 `5a0d25a` 的模式门禁、持久化意图、累计成交、恢复与离线安全验收继续复用，随后文档/验收提交保留。
- 已在本分支的研究模块及拒绝证据随既有历史保留，不重新执行、不修改冻结资产；其他研究 worktree 不合并。
- 配置迁移：默认仍为 dry-run，股票与现有用户配置保持兼容。C1 行情身份迁移需显式声明旧库来源；C5 订单数据库升级需保留旧表及恢复语义。

## 支持矩阵（初始状态，不等于验收通过）

| 能力/范围 | 实现入口 | 现有证据 | 待验收/范围 |
|---|---|---|---|
| 已收盘 15m/1h/4h、多级别结构 | `DataAPI/ccxt.py`、`OfflineDataAPI.py`、`Chan.py` | `test_m5_data`、`test_multilv`、`test_consistency` | C1 时间/finality/来源；C2 因果发布 |
| Binance USDT 线性永续 | CCXT 行情与 `Trade/CCXTTradeEngine.py` | fake exchange 安全/状态机测试 | 第一交付目标；合约单位/真实环境未认证 |
| OKX USDT 线性永续 | 同上 | 通用 fake exchange 路径 | 第二目标；交易所参数映射、测试环境未认证 |
| 现货 | 原有 CCXT/SQLite 路径 | M5/M6 离线回归 | 保留兼容回归；不与永续混库 |
| XGB | `ModelStrategy/models/Xgboost`、`ChanModel/XGBModel.py` | M3 小样本训练/评分 | C3 meta、时序切分、在线产物契约 |
| LGBM/MLP | `ModelStrategy/models/lightGBM`、`deepModel`、`ChanModel/GeneratorModel.py` | M3 小样本训练；C3 三类模型存取、统一部署/实际候选和入场评分 | 离线软件路径；非经济采用或实盘认证 |
| SQLite | `OfflineData/offline_data_util.py`、`Trade/SqliteDB.py` | M5/M6、安全/状态机 | 默认验收后端；来源/迁移/对账继续补齐 |
| MySQL | `Trade/MysqlDB.py` | 离线 SQL 适配测试 | 可选，真实连接/迁移未验收 |
| dry-run | `SafetyPolicy.py`、`TradeEngine.py` | safety/state-machine | 默认模式；C5/C6 补账户/E2E |
| testnet/live | `SafetyPolicy.py` | 拒绝/解锁边界单测 | 受既有 candidate/环境/kill-switch 门禁；无真实认证 |
| 股票/Futu/股票 GUI | 保留原模块 | 原有回归 | 暂缓；不阻塞币圈链路 |
| 反向合约/期权 | 无本次认证 | 无 | 不支持本次交付 |

## 阶段与验收记录

| 阶段 | 状态 | 证据/剩余项 |
|---|---|---|
| C0 | 已完成范围冻结 | 本台账、README/DEV_PLAN 与批准计划对齐；远端身份新鲜核验 |
| C1 | 已完成离线实现与验收 | UTC 日/周/月边界、finality、尾 K 修订、分页/完整性、来源绑定、显式备份迁移、质量状态；见下方记录 |
| C2 | 已完成离线实现与验收 | 父 K/原始关系发布边界、不可变决策、完整身份对账、真实三层策略 future/prefix 变异；非外部认证 |
| C3 | 已完成离线实现与验收 | UTC purge/unknown、三模型身份、write-once 部署、三阶段评分与 SQLite 版本链；非实盘/外部认证 |
| C4 | 已完成离线实现与验收 | 有界实际样本→三模型→搜索/独立验证→部署→全 trial 重放；93 项组合、608 项全仓离线通过，非经济采用 |
| C5 | 待开发 | 合约适配/恢复/对账 |
| C6 | 待开发 | 调度/API/离线 E2E |
| C7 | 待前置验收 | 公共行情与有准入后的外部认证；代码发布按阶段进行 |

基线：前一审计在完全相同 `22a5a56`、依赖和环境上执行的所选离线功能集合为 116 passed / 1 skipped / 1 deselected，带一个 XGBoost 弃用警告和 pytest 临时目录清理提示；该证据仅覆盖列明集合，不称全仓或真实交易所验收。行为修改后补跑对应回归。

本阶段只调整交付说明，不做运行时代码简化；代码开发优先复用现有实现，不新增依赖。

C1 收尾清理计划：迁移校验由两份全表内存列表改为有序逐行比较，保留备份和全内容不变检查；复用已通过的迁移回归测试，不改变迁移授权或来源契约。线上/离线转换共用 `Common/KLineTime.py`，删除重复转换逻辑，保留股票 reader 行为。

## C1 证据（2026-10-20）

- RED：首组 14 failed / 3 passed，明确看到在线/离线时间不等、缺时钟注入和 finality；后续组分别证实尾 K/来源/分页、CSV/迁移/质量、provisional/深拷贝边界。重复页 fixture 设调用上限，避免旧代码无限循环。
- GREEN：新增契约覆盖 UTC 跨日/闰月/跨年、closed boundary、两种 reader、snapshot、尾 K 修订/幂等、有限 OHLCV/周期对齐/缺口/重复/乱序、断线续传、来源隔离、备份完整性、质量状态和复制。
- 全仓离线：`python -m pytest tests -m "not network" --basetemp <new-unique-temp> -q --tb=short --durations=8 -p no:cacheprovider`，330 passed / 7 skipped / 1 deselected / 1 XGBoost 文本输入弃用警告，169.01s。采用新独立临时目录后未再出现旧 pytest-current 清理告警。
- 其后仅补 CSV 两项回归并将迁移列表比较改为逐行比较；再次核验相关契约集合，结果记入提交的 Tested trailer。未改变冻结研究资产、配置默认值或段算法核心，未使用网络/密钥。
- C2 仍须解决“已收盘历史父 K 在更早子 K 决策中被提前读取”；C1 的全局 finality 不替代逐决策可用时间证明。

## 发布记录与 C2 实施边界

- 远端已通过 `git push --porcelain origin HEAD:refs/heads/full-version` 快进至 `d93b24cbad5fb0fb20419057f3ae9fa64e78087e`，随后 `git ls-remote` 身份相等；C0 为 `3a6b917`。
- C2 在调度/特征访问边界修复：父 K 延迟进入结构计算，直到子 K 的决策时间达到父 K 收盘边界；同边界按大级别先发布。递归结束仍完成父 K 自身计算，保留最终图形/结构。
- 跨级特征选择决策时已完成的父 K，不能从当前包含关系直接读取尚未可用的最终 OHLC。保留真实父子关系用于结构和绘图，不改段算法。
- 先验证小夹具的边界与未来变异，再跑已有多级别一致性；若出现行为差异，先定位原因，不放宽因果性测试来恢复旧信号数量。

### C2 第一子边界（仍未完成整个 C2）

- 已观察 RED：两级初始测试 2 failed/1 passed，三级测试进一步发现中间父 K 时钟仍会提前发布祖先。按递归数据流追踪后，发布触发改为最低级别实际时刻及本级递归完成时刻。
- 通过小夹具：未来父 K OHLC 变异、previous completed parent、prefix/suffix、两/三级同边界大级别先发布、跨午夜 interval 对齐、非法区间拒绝、only-last 不允许父级别时间超前。
- 兼容性首轮 58 passed/1 failed：失败项是“任意合成行情中 intrabar 必须与 close-only 产生不同交易”的假设，ensemble 与两个独立运行仍逐笔完全相等。已增加确定触价夹具，实测 close-only 保持持仓而 intrabar 因 stop_loss 平仓；保留原逐笔等价和参数传播检查。
- 剩余：低级别独立增量/最高级别最后收盘后尾部数据、不可变决策证据、多级别按身份对齐。完成这些之前不宣称 C2 已完成，也不推进正式经济研究。
- 本子边界全仓复验：341 passed / 7 skipped / 1 deselected / 1 既有 XGBoost 弃用警告，167.23s；跳过项为六个显式要求外部研究资产的集成测试和缺少 PyQt6 的股票 GUI，排除项为真实 CCXT 网络测试。无需设置研究根目录来消除这些预期跳过。
- 本子边界已推送并核验远端为 `b06c40cabd7fdcf316c5a361a19912773c27063a`。

### C2 第二子边界：低级别尾部与分批喂入

- RED 证实：根级别没有新 K 时，新的 1h/15m 留在队列未处理；prefix 缺少未来父 K 时只有 4 条决策，而 full 路径有 6 条。
- 增加低级别尾部处理，继续使用最后已发布父级别作特征上下文；真实父 K 到达时补齐包含关系，不伪造“前一根父 K 包含这些尾部子 K”的关系。
- 三级逐 15m 喂入、完整批量输入的每级 canonical 观测与最终父子关系相等；`load`、`step_load`、`trigger_load` 均覆盖尾部，深拷贝尾部后可以等价续传。
- 新失败测试发现：晚到父 K 可能读到更晚子级别状态，现对所有其他级别检查时刻；调度器持有自己的去重状态，代理/ensemble 不会因此对旧父 K 重判。
- 当前专注组合 61 passed（44 data contracts + 17 causal publication），全仓复验后在 Lore trailer 记录。C2 仍剩不可变真实决策/退出/信号证据及按身份对账，不能仅凭观测策略测试宣称整个 C2 完成。
- 全仓复验：349 passed / 7 skipped / 1 deselected / 1 既有 XGBoost 弃用警告，166.75s；跳过和排除范围与第一子边界相同。下一步从真实 CStrategy/CCustomBSP 的开仓/退出不可变记录 RED 开始，再接 FeatureReconciliation 的多级别身份对账。

### C2 第三子边界实施计划：真实决策与身份对账

- 第二子边界已推送并核验 `4d6f5a2bab72c8e5bf85812bee82eba07b3e9cbc`。上一 Goal turn 属于有效进展；本轮开始工作树干净。
- 冻结 finite canonical JSON bytes，事件身份包含 instrument、level、decision_ms、kind、方向、类型、anchor、parent event 与序号。特征/分数/初始止损属于 payload，不混入身份；同一身份 payload 改变必须报告漂移。
- CStrategy 在模型准入后冻结开仓，CCustomBSP 在每次实际退出时冻结该动作；同 K 线即时退出保留 entry-before-that-exit，旧仓退出仍先于新仓开仓。历史特征、追踪止损、结构对象后续变化不得改写已发布字节。
- 信号由显式 publish 入口冻结，不额外调用用户 bsp_signal 回调来改变默认策略行为；ensemble 的记录和去重状态跟随所选默认变体。
- 清理计划：FeatureReconciliation 用多级别身份索引、时序和完整 payload 检查替换 zip 对比；保留原单级别调用兼容，增加缺失/额外/重复/乱序/非有限/字段变异的单变异测试。先证明现有正确回归和新增失败，再移除旧比较逻辑。
- 新增 RED 发现单靠 code/level 仍会把 Binance 和 OKX 的相同决策归成同一身份。把 C1 已验证来源传到 bar 和事件身份；复用原来源校验，集中 updater/online 的实际来源提取，深拷贝不共享可变来源字典。无市场信息的历史/合成单元保留显式 null，不伪装成已验证交易所数据。
- 追加开仓来源笔/段状态与类型快照，拒绝超过决策时刻的目标结构；退出只能引用真实开仓。收尾清理用本批新增身份 delta 校验重复/先后依赖，移除逐条复制全历史字典的开销，继续复用已建立的批次原子性和重放测试。
- 已完成真实 CStrategy/CCustomBSP/CCloseAction/CSignal 的不可变记录、同 K 线即时退出顺序、深拷贝回调隔离、重复身份漂移拒绝；SignalMonitor 使用整批发布并在失败时保留原 watching。信号决策时刻取最新已发布时刻，锚点仍为本级 bar。
- RED/GREEN：25 个快照/真实生命周期用例（含初始 11 RED、批次/身份 6 RED、来源 3 RED、来源结构 3 RED及实际 Monitor 的 2 RED）；46 个数据契约回归。真实笔/段类型后续改写不会改变已发布 origin 字节。
- 全仓：376 passed / 7 expected skipped / 1 network deselected / 1 既有 XGBoost 弃用警告，181.02s。C2 尚未完成：下一步必须替换 FeatureReconciliation 的 zip 比较，并证明多级别完整身份/时序/字段的单变异检测。

### C2 第四子边界：完整身份对账与原始关系发布

- 第三子边界已推送并核验 `8eac03c6ca8b97cc2a6ee402e61431154b3b1956`。本批未修改冻结研究资产、段算法或交易授权。
- RED 证明：虽然父结构延迟计算，原始 `sup_kl` 仍可暴露未来父 K；已发布前驱的 `next` 也可暴露未来 K。连接父子/相邻指针推迟到真实发布边界，且保留区间校验、最终图形关系、单独到达的边界子 K 和低级别尾部补链。
- 删除 FeatureReconciliation 的最终 cbsp zip 对比。新路径按完整 event identity 核对开仓、部分/最终退出、观察信号的完整 payload；缺失/额外/重复/回绕/同刻乱序/坏 canonical/非有限值/缺开仓依赖/退出跳号均拒绝。默认零容差；显式浮点特征容差不能产生 `is_exact`。
- 三次独立读取：批量 load、按真实收盘时刻合并后 trigger、无历史信号回调的控制 load。逐级输入 count/SHA 包含完整 OHLC、量能、时钟和来源；无交易时也不能绕过输入核验。控制路径仍记录逐时刻结构/去重检查点，避免“回调临时改写后恢复”的两条被观察路径自证。
- 检查点对列明公开状态作 finite canonical 内容承诺：原始关系图、合并 K、笔/段/段段、中枢/段中枢、买卖点及特征、确认状态、去重状态。不以舍入/剔除虚结构消除差异；历史决策的形成锚点、当时确认状态与实际可用/决策时刻分开保留。原始结构允许后续合法重建，已发布决策字节不回写。
- 真实 CCustomStrategy/CMultiLevelStrategy、4h/1h/15m、有非空特征的 long/short/exit：prefix-only、full 后截取、未收盘父 K 及未来 suffix 变异三路径历史字节相等，来源端点重建已实际发生。夹具 census 确认 CustomStrategy 同时覆盖 sure/virtual 来源，多级别策略只从 sure 来源接受；未强行要求后一策略接受 virtual。
- 验证：原有整合 100 passed；新增真实策略/驱动/单变异组合 31 passed；审查补强前全仓 410 passed / 7 expected skipped / 1 network deselected / 1 既有 XGBoost warning（300.84s）。随后新增临时结构副作用的 RED，最小修复后 49 focused passed；提交前再次复验最新完整工作树。
- 复核按 requesting-code-review 的质量/架构/边界清单串行进行，未启动子代理，不能冒称独立审计。诊断会做三次读取与完整结构承诺，当前三层 80×4h 小夹具约 75s（控制路径补强前），不宣称已完成大规模性能优化或交易所认证。
- 审查补强后的最新完整树：411 passed / 7 expected skipped / 1 network deselected / 1 既有 XGBoost 文本输入弃用 warning，350.80s；三层实际策略诊断 109.70s。compileall 与 diff 检查随 Lore 提交核验。上述证据完成 C2 的离线软件门槛；C3–C7、任何真实交易所认证和策略经济采用仍未完成。

## C3 实施与清理计划（2026-10-21）

- C2 已推送并核验 `7c2d9eaea42a1ed5788111da4bb68cb893241cc6`。只使用小合成 fixture、既有离线回归与模型库，不读取冻结绩效/运行正式研究，不新增依赖。
- 先写 unknown→0、多币种数组切分、预测 meta 乱序三类 RED。样本特征和身份复用 C2 已接受的开仓字节；记录 decision_ms、feature_available_at_ms、每标签 label_end_ms、primary label 与已知/未知训练行映射。unknown 保留并统计，不能训练成负例。
- 既有终局结构标签不假造更早确认时刻：`bsp_hold` 是输入窗口终局状态，`next_bsp`/`seg_confirm` 若只由终局结构观察，结束时刻保守取窗口末端；不确定的 segment/未触达 barrier/未完成 ret_N 保留 unknown。不得把端点时刻冒充确认时刻。以终局标签跨入验证段时必须 purge，可能导致无可训练样本并明确失败。
- 清理旧的特征遍历编号和按数组切分路径，复用现有 libsvm + feature.meta 格式并增加版本化时序 manifest；按全局 UTC train/validation/test 边界分组，边界前后同刻多币种不能拆开，label_end 穿越边界清除。缺时序证据的旧样本不能伪称新契约训练通过。
- 模型 meta 与模型 SHA/特征名称顺序/缺失策略/标签定义/窗口/代码配置摘要绑定；预测先加载训练 meta，再按输入 meta 名称映射，不能让同维乱序静默换列。随后接通 XGB/LGBM/MLP 在线适配和同一部署清单；阶段完成仍需真实脚本/失效门禁及完整回归。

### C3 第一子边界：样本、切分与共用评分（尚未完成 C3）

- RED：首组 8 failed，实际列乱序模型返回 23 而不是 32；随后观察到未连接真实 split、标签依赖可变开仓对象、缺少三种模型 artifact/在线入口、旧样本公式重标与缺来源字段、源输入摘要缺失等失败。未靠只比较最终维度或打印告警放行。
- 样本从 C2 的已接受开仓字节取特征/初始价格/方向，按 UTC、instrument、event_id 稳定排序；全量说明与已知训练行一一映射。未知主标签保留并计数，终局结构使用保守的实际窗口结束时间，ret_N/barrier 用实际观察 bar，穿越分段末端即 purge。
- 删除按币种数组位置切分、样本 meta 覆盖模型 meta 的路径。全池边界先冻结，再分桶；三种模型均分 train/validation/holdout，训练只接收前两段。默认 folder_thred 仍为训练比例，其余时刻均分验证/最终留出；支持显式 UTC 边界。终局标签导致空分段时明确拒绝，不偷填。
- 新的 `.contract.json` 绑定模型/meta/样本文件/标签参数/源输入 count+SHA、特征与训练代码、配置、运行库、窗口、必需/条件列；三种在线模型复用原 generator 的 estimator/缺失策略，XGB 删去重复评分实现。无新契约的旧模型不自动获准在线使用。
- 兼容回归揭示 feature engine 会省略尚无历史的条件列。以 train 段始终存在的列作为必需列并写入清单，其余按原缺失策略处理；没有把全部缺列默认放行。实际 Chan+XGB 路径再次通过。模型错误还暴露 CSV 迭代器未关闭；增加确定性 RED，finally 显式关闭活动 source 后不再占用测试文件。
- 43 focused（之后补源输入摘要的第 26 个新契约测试，最新合计见提交前验证）；已知警告：合成 MLP 60 步未收敛、既有 XGB libsvm 弃用、因真实 purge 后验证标签单类而 AUC 未定义。测试只证明功能，不宣称统计或经济有效性。
- 仍待：统一部署清单、signal/intent/后验记录的版本贯通、候选与实际突破评分语义、CheckOpenScore 正确周期及非最新行；未把本子边界或三种模型测试称作 C3 全部完成。
- 补强：unknown 的完整 features 保留在样本说明供推理；仅训练读取排除 unknown，predictAll 不丢掉未标注样本。确定夹具 50 known + 1 unknown 验证训练输入 50、推理输出 51；通用合成夹具并不保证其最后一次交易落在标签未完成窗口，未用错误的“所有合成数据必含 unknown”假设替代确定夹具。
- 新增已观察的 RED：单类训练集和 NaN 预测原本也会发布 artifact；现在在持久化之前校验二元训练类别、预测行数/有限概率。非法非数字特征整批拒绝，失败前不创建样本文件。新契约当前 30 focused passed（2 个合成 MLP 未收敛警告）；最新完整树提交前串行复验。
- 执行事件：一次全仓进程尚在运行时误启动了短 focused 进程并修改了测试文件，违反本计划串行排程。短进程结束后只等待原 handle 至完成，原结果为 437 passed/7 skipped/1 deselected（290.33s），明确不作之后新树的完整证明；后续所有测试严格串行，最终以最新完整树的独立运行作为提交依据。
- 最新完整树独立串行复验：441 passed / 7 expected skipped / 1 network deselected / 4 warnings，292.31s；警告为 libsvm 文本输入弃用、purge 后验证单类的 AUC 未定义、两次小 MLP 未收敛。新契约 30 项、此前样本/三模型回归全部通过；compileall/diff 检查通过。跳过项仍为 6 个需外部研究资产的测试和缺 PyQt6 的股票 GUI，未为消除跳过而启用研究或网络任务。

### C3 第二子边界计划：统一部署与三阶段评分

- 第一子边界已推送并核验 `19ba317e26a95ba44bc028ddfe59d783885f9f35`，本轮起始工作树干净；上一 Goal turn 为有效进展。继续 Inline 串行 TDD，不启动研究、网络下单或子代理。
- 发布 write-once finite canonical 部署清单，绑定训练生成的实际策略/级别/来源配置、模型 artifact、特征代码与三个评分阈值；模型缺失、来源或配置漂移时 fail closed。它只是软件部署身份，不是 candidate、测试网或实盘授权。
- 三阶段语义固定：candidate 用已收盘上下文与候选突破阈值作假设入场价；entry 在实际报价突破时重新确认最新已收盘候选上下文，用当时已观察报价作假设入场价，不修改已收盘 OHLC 或添加 provisional bar；post 仅在开仓对应周期完成后用该前缀重算。价格/上下文变化可使分数不同，不能承诺三个阶段同分；同一输入上下文则必须离线/在线一致。
- 清理/复用：复用 `model_version`、既有订单意图 CAS 与 before/after 快照；只添加确需独立保存的部署/信号证据与时钟字段，不重建订单状态机。替换 CheckOpenScore 取全库最后一行和配置首级别的旧路径。SQLite 采用可重复、非破坏性补列；MySQL 未做真实迁移前继续不声明同级验收。
- 每一步先用小型真实 SQLite/生产策略 fixture 观察 RED，分别核对清单、信号 DB、意图快照、重启和后验具体 bar；旧无模型 dry-run 用例保留兼容，但不得称为已获部署认证。完成所有 C3 接线和完整回归后才更新阶段状态。

### C3 第二子边界证据与范围

- 统一 write-once 部署绑定真实训练的 source/config/levels/策略、模型 artifact 与阶段阈值，默认 Statics/SignalMonitor/MakeOpenTrade/CheckOpenScore 共用；原始候选字节、版本和路径写入 SQLite，入场评分在既有意图 CAS 前验证。模型或清单缺失、版本/市场/冻结字段漂移拒绝新风险，未改 SafetyPolicy 授权和订单恢复。
- 已观察清单/字段/入场评分缺失 RED，以及 3 项负时钟/零报价/空 bar 评分上下文拒绝 RED。UTC 周/月/4h 六项先因缺 helper 失败；补 helper 后暴露测试误用仅支持传统格式的 parser，改用标准 ISO parser 后通过。两项后验 RED 证明“缓存只存已收盘行”时旧逻辑提前报错，现先按 UTC 预期周期等待，再查 exact open 行。
- 三阶段分数可不同；清单不提供策略经济采用/测试网/实盘授权。当前对应周期明确基于 entry 报价观察时间而非交易所成交回报时间；C5 仍须处理真实成交延迟、contractSize、账户和订单对账。后验使用记录原清单，不随全局新模型切换，重复后验不回写证据。
- 实际三级 CMultiLevelStrategy 合成 fixture：先只写训练前缀、训练模型，再追加未来数据；固定未来首个候选的批量重建与在线输入评分 canonical 字节相等，真实交易级别为中间 1h。XGB/LGBM/MLP 均经真实样本训练/持久化/加载并完成候选和 entry 同 artifact 验证；不是收益筛选。
- 收尾回归：100 项 workflow/model/M6/state-machine/safety passed；随后 LGBM/MLP 两项部署通过。测试中曾误用不支持 context-manager 的 CChanDB，改为既有 try/finally close；没有为 fixture 改写生产 DB API。最新完整树另行串行验证后再提交。
- 最新完整树严格串行复验：476 passed / 7 expected skipped / 1 network deselected / 7 warnings，378.81s。警告为小夹具的单类 validation AUC 未定义、三次 MLP 60 步未收敛与既有 libsvm 文本输入弃用；不以这些功能夹具证明模型质量。跳过项仍为六个需外部研究资产的测试及缺 PyQt6 的股票 GUI。C3 离线软件门槛完成；C4–C7 与外部交易所、正式策略研究仍未完成。

## C4 实施与清理计划

- C3 已推送并 fresh ls-remote 核验 `b4eaf329f2239105661fa32a2604fc93480d53e0`，起始工作树干净。继续执行已批准的原计划，无新依赖、无子代理、无正式策略/绩效任务。
- 先以确定性 eval stub 复现所有算法忽略/超过预算、零 trial、grid 边界、重复运行累积、NaN/Infinity 和默认覆盖活动配置等问题。复用现有 CParaAutoML，删除重复/不受限循环；`pbt` 保留兼容别名，准确命名为参数种群扰动，不声称 checkpoint 继承。失败不生成可部署产物。
- 逐笔 eval_strategy 保留原百分比统计属性，明确百分点/单位名义口径；旧 portfolio_eval 保留兼容回归，但不作为资金费/mark/部分退出的完整账户实现。已审查 research/conservative.py 的即时费用、按剩余名义资金费与 marked equity 思路；该实现依赖研究专用 ExecutionTrade、只支持最终平仓/固定 mark 对齐，不能直接作为 spot/部分退出/未平仓生产接口，且不改其冻结实现。
- 新的通用账户入口接受显式成交/mark/funding 事件，以 USDT 与币数量分别记账，覆盖 long/short、费用、滑点、部分退出、未平仓、杠杆/保证金边界与幂等事件；保留逐事件现金/持仓/权益证据，不从最终百分比反推资金曲线。只验合成数据；交易所真实强平/手续费细则不冒称认证。
- AutoML 搜索窗口/允许参数/目标/seed 和代码身份与验证窗口分别冻结。搜索结果、验证报告和部署建议分开 write-once；不默认覆盖活动 OpenConfig 或当前模型。多周期验证接入训练 API，脚本失败传播和完整调度验收留在 C6；完整 C4 验收后才更新阶段状态。

### C4 第一子边界：有限预算与无覆盖参数建议（C4 仍未完成）

- 已观察 RED：31 项预算/重复运行/非法空间/非有限分数/产物失败，8 项默认活动配置/写覆盖/reader 漂移/单位失败；另 1 项证明 trial=2 仍会构造 10^12 长网格轴。大轴测试使用 checked_range 在分配前失败，不实际耗尽内存。
- 原有 CParaAutoML 原位修复，未新增第二个搜索器：所有算法 budget 上限、每次 seed/state 重置、有限 trial 与拒绝原因、int 轴上下界/去重、轴构造预算约束、种群兼容别名与准确命名。删除默认覆盖活动配置、无元数据 max 读取、重复不受限循环及直接 JSON Infinity 发布路径。
- 复用同一个独立 reader 核验 canonical/代码/预算/参数/状态，供建议导出和 legacy verify；write-once 原子发布只写显式新路径。逐笔属性兼容，JSON 明示百分比单位和 undefined ratio。legacy verify 的窗口隔离明确未证明，不能假称完整 C4 闭环。
- 适用验收：41 新契约 + 8 原 M4 + 8 原 portfolio = 57 passed（17.12s）；C3 及其他未变代码的 476 全仓证据保留为前一树证据，不重标成本次完整树。编译/diff 随 Lore 核验。账户事件、多窗口/目标/数据身份、训练流程整合仍待后续 C4 子边界。

### C4 第二子边界：显式资金账户（C4 仍未完成）

- 第一子边界已推送并核验 `05280e806cab650beeb59a3522d96bbfa15c22d5`。账户模块先观察缺模块 RED，按合成手算逐项实现 spot 自有现金 long、linear swap long/short、费用/不利滑点、partial exit、funding ownership、mark 未平仓、保证金和幂等；不从逐笔百分比反推资金，也没有导入/修改冻结 research 实现。
- 补强 RED 证实调用方 Decimal 精度会改变快照，现所有计算固定 50 位；补 5 项 RED 定位同刻新 lot 即时退出、换 id 重复资金费、缺现金流明细、非法 mark 字段与空 base symbol，逐项最小修复。补 6 项 reader RED，窗口变异暴露短窗口年化 null 的间接证明不足，增加完整报告摘要。补 2 项同刻退出顺序 RED，使用明确 sequence 而非字典序假装真实顺序。
- 每事件保留 execution_price、cash/fee/realized/funding 增量与完整快照；保留历史字节、reject 原子性、exact duplicate 幂等、remaining quantity funding。固定顺序为 mark→旧仓 funding→旧仓 exit→open→新 lot 即时 exit。同 symbol/时刻 funding 唯一，同 lot 同刻退出 sequence 唯一递增。
- 净值指标以实际有界窗口计算；未平仓保持 mark，不伪造强平/期末成交。软件 cross 保证金状态不是交易所认证，spot 无借贷不能做空，quantity 为币数而非张数。replay reader 核对每事件/指标/代码身份；这是实现内自校验，独立手算夹具才是公式证据。
- 28 账户契约 + 57 搜索/M4/旧 portfolio 回归为本子边界适用证据；C4 仍剩实际数据/策略/模型/目标/窗口绑定与多周期训练闭环，C5–C7 未完成。旧 portfolio 行为不改，仅删除误导性的完整/唯一记分牌声明。

### C4 第三子边界：实际策略/来源/模型与执行桥接（C4 仍未完成）

- 账户子边界已推送并核验 `1cff2149355b6a87c274473cd4c51f7c35382378`。先观察 crypto_evaluate 缺模块 RED，随后接实际 contract/mark/funding 不可变数据包和原生策略，不用任意闭包声称已执行正确窗口。行情连续性、mark 对齐、资金费独立日程完整性和来源均显式检查。
- confirmed-decision→next-real-base-open 固定执行口径，一律 taker/不利滑点；不使用同一 K 线内事后才可知的策略参考价倒填成交。保留原策略决策和对应真正执行参考价；固定 USDT 名义，不做隐含仓位参数搜索。结构可预热，账户平仓起步，交易级别在起点前不接受持仓；原生类型/参数和 adapter 代码共同绑定。
- 模型绑定测试观察到 3 RED（缺 artifact 字段、错交易所、改训练前缀仍接受）；补强验证原始训练 count/SHA、来源、级别、策略参数及标签可用边界，错误在策略执行前拒绝。原始训练前缀应完整出现在同一明确数据包内，不给缺证据旧模型补贴身份。
- 三级 fixture 发现 trigger API 每批需要包含空根级别键，复用既有 FeatureReconciliation 的空列表约定修正，不改 Chan 调度。原生三级 long/short/exit 的完整早期报告在尚未收盘父 K body 及未来 suffix 变异后相等；末尾未完成 base K 也仅保留真实已观察 open，不能用其后 high/low/close。
- 适用组合为 15 新桥接 + 28 账户 + 57 AutoML/M4/portfolio = 100 passed（24.09s，1 个小 XGB validation 单类警告）；随后只补数据 manifest 可审查计数并复验 bridge。C4 仍剩明确目标与不重叠多窗口、搜索/验证/部署建议隔离和训练流程；未运行正式参数搜索、冻结绩效或真实网络订单。

### C4 第四子边界：冻结多窗口实验与全 trial 重放（C4 仍未完成）

- 桥接已推送并核验 `7f90de5234db1ab13d0a1cec2079430f754c9be4`。先观察 account_experiment 缺模块 RED，复用原 CParaAutoML + 真实账户评估，不另造搜索器；固定目标、允许参数、seed、budget、搜索/验证窗口、数据/配置/代码身份，禁止窗口重叠、倒序、无验证或无效参数。搜索结束只选择一次，后续原样验证不反选。
- 各阶段内存完成并逐事件重放后，才创建独立新运行目录的 search/validation/proposal/receipt 四文件；不修改活动配置或模型。注入发布中断已证实仅清理本运行新目录，既有运行字节完全不动。receipt 是 offline_window_checks_passed 且 candidate_authorized=false，不是正式经济采用。
- 额外 RED 证明途中 liquidation_required 后恢复不能当可部署建议，现按全历史状态拒绝；另一 RED 证明仅重放最优项会放过重新计算 SHA 的非最优伪造，现每个 trial 完整重放，所有 cashflow/account/指标/窗口/模型数据身份必须相等。实际数据变异和单文件变异均拒绝。
- 初始组合 113 passed（41.12s，1 小 XGB 单类 warning）；随后 bayes 与 pbt 各两次固定小任务的四文件逐字节复现通过。下一步全仓最新树串行复验，之后 Lore 发布。C4 尚余样本→模型→账户多窗口接口在训练入口的实际编排；C5–C7 均未完成，不改变 Goal 总范围。
- 最新完整工作树严格串行复验：575 passed / 7 expected skipped / 1 network deselected / 8 warnings，346.57s。8 警告为合成 XGB validation 单类 AUC、三次 MLP 60 步未收敛和既有 libsvm 文本输入弃用；跳过仍为六个需外部研究资产的测试及缺 PyQt6 的股票 GUI。未设置研究路径来消除跳过，未运行正式参数搜索/绩效或外部订单。
- 下轮可执行起点：训练 API 先 TDD 接受显式 bounded data 的真实 sample reader，复用 C3 的 run_backtest/三 generator/contract，再在训练标签已知之后的 search+validation 窗口使用本接口；选定模型/feature.meta/策略/输入/评估器/阈值构成清单，导出后重读并 replay。不得把任意测试闭包或现有 PS1/SH 的退出 0 当成该条完成；脚本失败传播及核心/完整环境矩阵留 C6。整个 C0–C7 Goal 仍 active。

### C4 第五子边界实施与清理计划：实际训练入口

- 前一轮为有效进展；本轮起始 `361ca0fc5e8436027a444188a4582d543b37a822` 干净。先用缺 `source_data` API 的 RED，扩展既有 run_backtest 为显式完整来源数据包的限定窗口 reader；保留默认 reader 兼容，不接受任意假 producer 回调来构造已验证证据，不复制样本/标签/训练器逻辑。
- 训练窗口、后续搜索窗口和验证窗口预先固定且不重叠。只复用三种现有 generator，显式新目录、固定标签与模型超参；已训练 artifact/特征 meta/输入/策略/执行器/三个阶段阈值与实验收据合成清单，导出重读及账户 replay 后才发布。模型失败或验证失败不得把旧 artifact 当作新产物。
- 临时制品只在本运行独有 staging 目录内生成，最终路径不得覆盖；所有引用须可迁移，不把临时绝对路径写成部署依赖。默认训练脚本改为调用同一个有界入口，不再在 PS1/SH 分别拼不同样本窗口或模型训练程序；完整脚本故障注入/锁/进度和环境矩阵仍在 C6 验收。
- 该改动会更新已绑定的样本/特征代码身份，旧模型须按 C3 规则重生成，不能修改旧 contract 续用。验证仅小合成数据与临时库，无正式研究、网络订单、配置权限变更或新依赖。

### C4 第五子边界证据：有界训练、可迁移制品与失败零发布

- RED 已观察：缺 source_data API、缺训练模块/CLI、PS1 未传递 native 非零码、SH 错拼 Windows 绝对 spec、临时模型绝对路径导致移目录失效、重算摘要后篡改 training window/model/label/search window/thresholds 仍被接受、零轮/bool 预算及非法 split 未在样本前拒绝。逐项修复，不用测试闭包伪装生产路径。
- run_backtest 复用原标签/样本实现，额外接受显式 CCryptoEvaluationData 的 UTC 限定 reader；只消费 training 起止内已收盘数据，不查默认环境。future suffix 和未收盘末尾变异不改训练文件。样本、模型 contract、元参数、实际 UTC 切分/必需列、源 count/SHA、账户所有 trial/窗口、部署阈值与最终收据交叉核验；仅 hash 自洽不算通过。
- 新 training_pipeline 单入口从全新 staging 目录训练指定 XGB/LGBM/MLP，再做后续不重叠窗口的搜索与验证、部署导出重读和全 trial 重放，全部完成才 rename 到新目标。已有目标拒绝；训练或后段验证失败整包不发布。proposal 使用模型文件名/内容身份，部署使用相对路径，移动最终目录后仍能重读/重放。删除 PS1/SH 内各自拼训练流程与静默复用旧模型的入口，不新增训练器/搜索器/账户实现。
- 真实三级 CMultiLevelStrategy 流水线首先暴露训练交集错误地把 SMC 多头 FVG 详情当永久必需列；确认缺失字段后，三模型最小 fixture 均观察同样 RED。现在仅 FVG/OB 已声明的数量零状态允许缺详情，数量缺失/负数/分数/bool、正数量缺详情、零数量附带详情或普通必需列缺失仍拒绝。训练、批量推理与在线评分共用同一 presence 校验；未删列、跳过 guard 或换成易通过数据。三级 4h/1h/15m 真训练中间级别、搜索、验证、重读重放通过。
- 当前组合严格串行：93 passed / 9 warnings，177.49s。包括 25 pipeline、16 binding、37 model、15 experiment；警告仅小 XGB validation 单类 AUC 与四次 MLP 60 步未收敛。曾误拼不存在的测试文件名，pytest 明确 no tests ran，修正真实文件名后独立运行本结果；未把失败命令算通过。完整最新树复验另记，不沿用 575 旧树结果。
- 限定：candidate/post 阈值是用户显式冻结值，本阶段不宣称在线三阶段价格相同或限价撮合等价。搜索额度仍属账户/建议口径，C5 绑定真实合约单位和在线额度；C6 验收完整调度/锁/环境矩阵。所有结果 candidate_authorized=false；C5–C7、交易所外部认证与正式经济采用未完成，Goal 保持 active。
- 最新完整代码树独立串行复验：608 passed / 7 expected skipped / 1 network deselected / 14 warnings，487.51s。14 警告为八次小 XGB validation 单类 AUC、五次 MLP 60 步未收敛及既有 libsvm 文本输入弃用；跳过仍为六项外部研究资产及缺 PyQt6 的股票 GUI。不设置研究路径、不使用网络订单来消除跳过。compileall 与 diff 检查通过；后续只更新本台账的状态/结果，不修改通过验证的运行时代码。
- C4 离线验收完成；进入 C5 时仍以币数量/合约张数、精度化后的持久化意图一致、exchange 参数与累计成交/重启对账为先，不重建状态机。C6 还需 fresh checkout 行尾、Python 3.11/当前版本核心与完整安装矩阵、调度锁/故障管理/在线式 E2E；当前 608 项通过不是这些外部/跨环境门槛的替代。
