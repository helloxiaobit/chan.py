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
| C5 | 进行中 | 单位/原生恢复/历史/来源、区间核对与持久冻结已离线验收；显式 cross/lot paper 接入原状态机，鲜活准入链、原生同义模型及进程级 E2E 仍待 |
| C6 | 进行中（仍未完成） | 配置运行壳/失败传播/管理/OS 锁与逐笔输入版本重验、版本化 API 已离线验收；原生账户/报价鲜活准入、离线进程级 E2E 与安装矩阵待完成 |
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

## C5 实施与清理计划：单位契约优先，保留唯一订单状态机

- 起始 HEAD `41155d683f14cf62d4e9e491868b19fca5ad85cb`、工作树干净，上一 Goal turn 为有效进展。本轮沿用已批准计划和 Inline 严格串行；不创建子代理、不运行正式研究或真实下单。
- 本机 CCXT 4.5.43 与 [官方 FAQ](https://github.com/ccxt/ccxt/wiki/FAQ) 明确：线性合约 create_order 的 amount/累计 filled 为张数，币数量=张数×contractSize。[官方手册](https://github.com/ccxt/ccxt/wiki/Manual) 区分 precision 与 limits。现有 quota_gen 返回币数，但引擎直接当 CCXT amount，且在 DB CAS 之后才舍入；该问题先用真实 CCXT precision + fake I/O + SQLite 重现。
- 内部 quota/current_qty/requested/filled 统一保留**币数量**，名义为 quote/USDT；仅 CCXT 边界转换张数。用原生 amount_to_precision/price_to_precision，舍入后重新检查非零、amount/price/cost limits，禁止向上增加币数；无来源/不支持的 inverse、非 USDT 线性永续等明确拒绝，不猜 contractSize=1。
- 文件范围：TradeEngine 增加默认兼容的预处理 hook；CCXTTradeEngine 复用现有 place/query/restore 路径做单位转换。SQLite 只非破坏性补 open/cover order contract 字段并在同一 intent CAS 持久化精度化后的 spec；db_util 保持累计成交逻辑原位不变。MySQL 新契约写入在迁移/事务验收前 fail closed，保留旧接口，不冒称同级认证。
- 清理/复用：删除 CAS 后的二次数量舍入；规格记录 market 身份、contractSize/precision/limits、币数/张数/价格及摘要。提交前重核规格，恢复按已持久化单位转换；缺规格的旧合约在途订单不自动贴单位，保留查询失败与撤单能力，不能重新下单。股票默认 hook 不改变已有行为，现有无 metadata 的 dry-run 仅保留兼容，完整模拟合约账户另按 C5 验收。
- 严格 RED→GREEN：先 contractSize≠1、舍入零/最小名义/精度、真实 DB 意图与请求、partial/重启/重复回报和 metadata 漂移；再做 Binance/OKX mode/margin/reduce/post/client-id 适配、查单分页、双向逐腿持仓和余额对账冻结新风险、含费用/funding/mark 的模拟账户。不得以第一子边界通过代替整个 C5。

### C5 第一子边界：精度化前置、单位入库与冻结单位恢复（C5 未完成）

- 先观察 RED：首轮 fake Exchange 的基类覆盖了 id 导致夹具错误，补真实 id 后重跑，得到 14 项有效失败。币数 0.037 被直接传为 contracts 导致精度拒绝；限额/无效 metadata 失败发生在 DB 已变 submitted 后；持仓 3 contracts 被读成 3 币而不是 0.03；现货 DB requested 也与实际舍入量不一致。
- 沿用同一 CTradeEngine/CChanDB 状态机，prepare_order 在 CAS 前把显式币数转换、精度化并检查完整 limits/数值可重读性。只在 CCXT 边界转张数，返回累计成交转回币数。open/cover contract 在同一 SQLite CAS 保存，原候选报价/模型 snapshot 不被精度化限价覆盖。删除提交之后再次改 amount 的路径，没有第二套订单循环。
- 完整真实 CCXT precision + fake I/O + SQLite 验证 partial、直接 order-id 查单、缺返回 client-id、重启/重复回报、全部退出、市价参考不冒充限价、spot 不套 contractSize、双向净持仓币数。底层 schema 非破坏性补列，旧行保持 null、不编造单位；重新打开 SQLite 后完整记录不变。MySQL 仅更新 fresh schema 说明，未验收新契约写入保持拒绝。
- 补强 RED：调用方 Decimal 精度实际改变 filled/position；错误 side/type/已知 id 原本被接受；市场在 CAS 后停用仍会提交，单纯 tick/limits 更新却阻断旧单恢复；极细数值在 DB/CCXT float 边界被静默改写；未知单位旧仓被自动平仓。逐项最小修复，Decimal 固定 50 位，已知订单身份不替换，新提交严格核当前规格/active，旧单按冻结单位但非新 limits 记账，无法数值往返或旧单位无证据时在 CAS 前拒绝。
- 原安全夹具的手动合约 close intent 缺单位证据；改为显式 prepare+持久化实际 spec，保留原参数、模式与 CAS 断言，而不是放宽运行时 guard。旧无 metadata dry-run 与股票默认 hook 保持兼容，未知真实合约记录不自动迁移；取消接口未移除。
- 运行时代码组合：104 passed / 3 expected small-model warnings（39.83s），含所有新增单位测试、trade safety/state-machine/M6、C3 真实部署/评分/intent 版本链。之后仅补 long/short/flat、SQLite 重开和 migration null、MySQL disabled 结构/回归测试，最新适用集合 73 passed（10.05s，无警告）。C4 的 608 全仓证据仅复用于未变区域，未重标成本次完整树证明；整个 C5 完成时再完整验收。编译/diff 与 Lore 提交单独核验。
- C5 仍未完成：当前尚不是交易所参数/模式认证；客户端号分页、逐腿对账/持久化冻结、完整模拟账户和在线额度部署接线继续按原计划推进。C6/C7、真实测试网及实盘仍保持各自门禁，Goal active。

### C5 第二子边界实施与清理计划：显式 venue 参数与只读账户核验

- 起始 clean `149f20e8c4f54383cacb4b7a50b009f43f8b7e70`，上一轮为有效进展。按本机 CCXT 4.5.43 原生 request builder 与 [Binance 新订单](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order)、[OKX 官方订单说明](https://www.okx.com/docs-v5/trick_en/) 核验，不实际调用账户/订单 API。
- 删除混用所有平台的 positionSide/reduceOnly/set_leverage 路径。Binance hedge 用明确 LONG/SHORT + 相反 side 平仓，不发送禁止的 reduceOnly；OKX 用 cash/cross/isolated tdMode、net/long/short posSide，net 退出才带 reduceOnly；post-only 使用原生 CCXT builder 映射，spot market 显式保持 base quantity。非法方向/不支持组合在 CAS/提交前拒绝。
- 非 dry-run swap 必须显式声明 position_mode=one_way/hedged、margin_mode=cross/isolated；leverage 是正整数且不容 bool/截断。只读 fetch_position_mode/fetch_leverage 核对真实账户/标的/腿，不在每张订单前隐式改全账户 mode、margin 或 leverage。设置不匹配拒绝新风险；有单位和执行证据的旧仓平仓按原 leg/margin 管理，不因后来全局配置或仅 leverage 漂移而阻断降风险。
- 新规格 v2 冻结 execution 设置和读到账户观测；v1 保留只读恢复、不允许以缺执行证据的旧意图重新提交。复用现有 JSON 字段，不加第二套状态机/后端。客户端号复用原 deterministic seed，生成 <=32 位字母数字，满足 OKX 和 Binance 的共同约束；拒绝手工非法号，不裁剪旧 id 导致恢复错配。
- 文件范围：CCXTTradeEngine、TradeEngine 的现有预处理/客户端号 hook，相关 native-builder/fake I/O tests 和文档；不改用户 Config/config.yaml 或默认 dry-run。用实际 ccxt.binance/okx 的 create_order_request 验证线缆字段，fake 仅截断 I/O；再回归 C5 单位、状态机、安全与模型 entry 版本链。这里只验软件协议，不称测试网认证，分页/账户对账/模拟账户仍需继续。

### C5 第二子边界证据：平台请求参数与执行规格 v2（C5 未完成）

- Native-builder 夹具首轮缺 Binance info.orderTypes，补全真实 metadata 后重新观察 26 项有效 RED：所有模式共用 positionSide/set_leverage、hedged 信号仍落 BOTH、账户 mode/margin/leverage 不核验、OKX 客户端号含不合法连字符。按既有状态机补最小 venue 映射，没有另建订单器。
- 覆盖 Binance/OKX × one_way/hedged × cross/isolated × long/short 的实际 open/close 请求体；hedge 只保留原 leg+相反 side，不发送非法 reduceOnly，one-way 退出明确带 reduceOnly。spot 市价 base 数量与 post-only native 字段也由真实 CCXT 4.5.43 builder 验证，不只断言 fake 收到参数。
- 执行前只读 fetch_position_mode/fetch_leverage，移除每单隐式 set_leverage。swap 要求显式模式/保证金和整数杠杆；相应账户证据缺失/冲突/读取异常时不取得新风险意图或提交权。有执行证据的旧仓按原设置降风险，不因后续全局配置或仅 leverage 变化切换 leg/margin。
- v2 在原 JSON 列冻结 execution、account observation、post_only。6 项 RED 证实只核 SHA 会放过缺 leg/bool leverage/未知模式/错观测/v1 自动补设置；现在只读恢复也检完整语义，v1 仅保留读单位、不自动提交。post-only 变更的独立 RED 后纳入 spec；客户端号复用原确定性身份生成共同支持的短字母数字 id，查询不改旧号。
- 新增只读核验后再观察 6 项权限时序 RED：准备、只读核验或 claim 期间 kill-switch/解锁撤销原本仍会占用意图或发送。现准备结束、claim 前及实际发送前重新复查原 SafetyPolicy；未改权限规则本身，也不因读取账户成功绕过撤销。
- 最新适用组合：155 passed / 3 expected small-model warnings，40.94s；包括 47 venue、36 unit、全部 trade safety/state-machine/M6 与 35 C3 deployment 工作流。三警告仅两个小 XGB validation 单类 AUC 与一个小 MLP 60 步未收敛。compileall/diff/Lore 另行核验；不把 C4 的 608 旧树证据重标为本次全仓。
- 剩余 C5：真实 ACK 后补查、按 client-id 的原生查询及历史分页、服务端 leg/成交回报和逐腿持仓/余额对账、持久化冻结新风险但保留可证降风险、完整费用/funding/mark 模拟账本与在线额度绑定。当前只证明离线请求/拒绝协议，不是完整服务器生命周期或交易所认证；Goal 仍 active。

### C5 第三子边界实施与清理计划：ACK、原生查单与有界历史恢复

- 起始 clean `6741acdbcb5eac6851173fcde70c372f96eab335`。沿用一个 intent/CAS/累计成交状态机；只增加 ACK 的已知订单号持久化，不把缺少 filled/status 的 ACK 伪装成零成交/open。补查失败仍 submitting，重启查原 id/client，不重下。
- 删除客户端号的单页通用 fetch_orders 路径。先用 Binance origClientOrderId / OKX clOrdId 原生 fetch_order；只有明确 OrderNotFound/NotSupported 才进入历史补查，网络/鉴权/限频失败不触发旁路扫描。SQLite 同一意图 CAS 增加 UTC 毫秒边界，旧本地无时区字符串不猜 UTC、不回填历史时间。
- Binance 历史按小于 7 日的固定窗口和递增 orderId 分页；OKX pending 与 archive filled/canceled 按递减 ordId 分页，使用本机 CCXT 实际 request/parser 验证。固定页数预算、游标无进展、时间/身份冲突和多单同 client 均 fail closed；空结果不是未接单证明，更不是重下许可。
- 测试先覆盖真实 CCXT ACK/parser、受理后响应丢失、原生 client 查询、第二页/窗口/取消历史、重复/冲突与预算、重启和两进程原 intent 争抢。所有 I/O 为 fake；不变的 C4/C5 既有证据仅按原树复用，提交前串行回归适用组合。逐腿账户、冻结新风险及完整模拟账本仍是后续 C5，不提前宣称阶段完成。

### C5 第三子边界证据：ACK、原生查询、分页与不抹零余量（C5 未完成）

- 首批 16 RED 证明 ACK id 未落库、响应丢失无法原生 client 查询、第二页不可恢复和缺 UTC 边界。复用原提交权 CAS，在补查之前保存 ACK id，未知 filled/status 仍 submitting；完整报告后才记账。已知 id 不能被后续 submission 回报覆盖，query 也不能绑定另一张订单。
- Binance/OKX 实际 fetch_order builder/parser + fake 私有端点，覆盖 open/close 的 ACK 即时成功、补查网络失败后新 DB 连接恢复、受理后超时丢响应、重复恢复、订单号查询。只有 OrderNotFound/NotSupported 才进入历史；网络/鉴权/限频不旁路重扫。时钟缺失/早于本意图和缺 client echo 不能作 client-only 证据，旧 UTC null 重开不回填。
- 新增 6 项 server leg/margin/post-only RED、4 项限价/已知 id 覆盖 RED。完整回报校验服务器原生字段，不靠请求体自证执行语义。旧单 v1 仍只读单位，不升级授权；不把这些 fake 回报认证冒称真实服务器验收。
- 复核 [Binance All Orders](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/All-Orders) 时发现无 orderId 默认取最近页；独立 RED 证明会漏老单，现每个 6 日窗口显式从正整数 id 起步、max+1 前进。OKX 用 pending + archive filled/canceled 与递减 after；本机 fetch_canceled_orders 不支持 archive，使用经实际 builder 核验的 fetch_closed_orders state override。每页 1000/100、总 32 页、90 日回溯预算，覆盖第二页、跨窗、取消部分成交、重复/歧义/页预算/空结果。测试中有一项 OKX 预算夹具误含 after 本身，按官方排他游标纠正，未把该夹具错误算作生产 RED。
- 完整部分平仓撤单测试另暴露真实 DB 浮点余量缺陷：0.03−0.02 被写成 0.009999999999999998，无法再转成一个 contract。3 项精确数量/小余量 RED 与 2 项超出数值范围 RED 后，数量 delta/remaining/total 在固定 Decimal 上下文计算；不可精确通过 DB 边界或发生 Inexact 时先拒绝，不向上补量。删除 1e-12 自动清仓阈值，1e-13 真实仓位保留。旧汇总均价仍是 legacy float，不把数量修复宣传成完整现金流对账。
- 两个短 SQLite 子进程只在同一提交权 CAS 同时争抢，实际一个 true、一个 false；没有并发测试套件或子代理。它不证明所有跨进程累计回报的事务性。代码复核发现 fill 的 read→write 仍需乐观 CAS/绑定当前 client attempt，终态旧回报也需独立覆盖；此项列为下一 C5 子边界，未宣称完整并发恢复验收。
- 最新关键组合 218 passed / 3 expected small-model warnings（53.08s），覆盖 63 recovery、36 units、47 venues、trade state/safety/M6、35 deployment。完整离线回归 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：754 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，494.26s。运行期间未改源码、未启动第二套测试；最后只补充本记录及文档措辞，未重标旧树结果。
- 文件：`Trade/CCXTTradeEngine.py`、`Trade/db_util.py`、`Trade/SqliteDB.py`、`tests/test_crypto_order_recovery.py`、`tests/test_crypto_order_contract.py`、`tests/test_trade_safety.py`、`README_FULL.md` 与本台账。清理掉单页通用查单、重复身份校验及 epsilon 抹零，未加新依赖/第二套订单状态机，未改配置或冻结研究资产。
- 下一 C5 子边界先保护跨进程累计成交：raw report 绑定当前 client attempt/id，fill 的 read→write 增加乐观 CAS，旧终态回报不得回绕；用确定性交错与双 DB 连接先观察 RED，拒绝冲突且保留已知仓位。之后继续逐腿账户/持久化风险冻结/模拟账本。C6/C7 与真实交易所认证仍未完成，Goal active。

### C5 第四子边界实施与清理计划：绑定回报与原子成交 CAS

- 起始 clean `8fdc5233f1aac127b01bff46ff6bcaa97e5e9978`；上一 Goal turn 为有效进展。继续 Inline 串行，无外部账户、无正式研究、无新依赖。
- 用两条真实 SQLite 连接在 fill 的 read→write 间插入更晚回报，先复现丢失更新和终态回绕；再复现旧 close client/id 回报污染下一次 close intent，以及开仓重复回报重置部分退出后的仓位。不以提交权 CAS 的单赢家替代成交事务证明。
- 沿用现有 apply_open_fill/apply_close_fill 公式和生命周期。新合约回报必须携带原 client/id；在同一 SQL UPDATE 内提交 server id、raw status、累计成交及仓位，WHERE 比较原意图和关键账本快照。冲突不重下、不重算到另一个尝试，保留赢家。ACK 也绑定原 client，不能在查询期间换到后来 close attempt。
- 清理 CTradeEngine 的多处 record_submission→apply 两次写入，所有实际下单/恢复/撤单确认用一个绑定 helper；旧无 contract 的股票/兼容 DB API 不冒称新合约认证。已处理终态的重复回报不能恢复成 active，重复 opening 回报不能抹掉真实退出；同量均价变异拒绝，不默默重写已知成交。
- 先短小确定性交错 RED/GREEN，再覆盖真实 CCXT/fake I/O 的进程重启、取消/重试和安全/部署链。同一测试未结束前不编辑源码或启动其他测试；完成适用组合、compileall/diff/Lore 与授权快进推送后，仍继续账户/风险冻结和模拟账本，不关闭整个 Goal。

### C5 第四子边界证据：同一尝试的原子成交和单调终态（C5 未完成）

- 首组 9 RED：两条实际 SQLite 连接在 read→write 间插入更晚 fill/terminal，旧数据会覆盖赢家；已处理终态又被 open 重开；opening 重复回报把真实 partial exit 的 current_qty 从 6 恢复为 10；同量不同均价可重写。最小 CAS/终态修复后 32 项通过，再接身份与实际运行路径，不把单线程顺序幂等称作跨进程证明。
- 新合约 apply/ACK/submission 写入均要求原 client/attempt/id；普通 TradeEngine 调用一个绑定 helper，删除各处 status→fill 的两次提交。fill 单 SQL 比较关键账本与双方尝试快照，连 id/status/数量一起提交；失配抛 LIST_ORDER_FAIL，restore/poll 保留赢家而不重下。旧 raw open 不能回绕已应用终态，opening 重复不改退出后仓位，full fill 后的晚到终态只补状态、不重置数量。
- 两项真实 Native GET 交错 RED 证实旧 ACK 会附到新的 close attempt；再加同 client 重用的 ABA RED。ACK 比较 source attempt，即使 client 相同也不能串单。平仓准备前/中有另一次 zero-fill 尝试完成的 RED 后，输入 snapshot 与 intent CAS 都绑定 previous_attempt。旧手工 mark_open/mark_cover_order/mark_cover_done 对新规格记录在任何写入前拒绝；旧无规格兼容行为保留，未据此认证股票或 MySQL。
- canonical 状态控制的 4 RED：DB 已知 canceled 时，旧 REST open 原本仍触发失败的重复撤单，阻断剩余仓位退出；现从已应用的同尝试 DB 状态决策。另 4 Native + 2 DB RED 证实 closed/不足量矛盾会被接收，现拒绝且不重试。6 项 NaN/Inf/bool 均价 RED 在写入前拒绝；已知单量不允许静默改价。
- review 清单串行自审发现未持久化的 order-id 提示可绕过 discovery 证据；4 RED 后统一要求 client echo 与 UTC 创建时间，两个正例保留有完整证据的提示号恢复。按用户要求没有审查子代理，不能冒称独立审计。原有 maker 手动 intent 夹具补明确 previous_attempt；新市价重试夹具曾把 None 误编码成字面字符串，按实际原生数值修正，仅为夹具修复、不计生产 RED。
- 最新适用组合：271 passed / 3 expected small-model warnings，58.73s；其中 53 新 report CAS、63 recovery、36 units、47 venue、trade state/safety/M6 与 35 deployment 全部通过。当前完整离线回归 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：807 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，498.97s。同一进程结束前未改源码或启动第二套回归；此后仅补本文验收数字。
- 文件范围：`Trade/db_util.py`、`Trade/TradeEngine.py`、`Trade/CCXTTradeEngine.py`、`tests/test_order_report_cas.py`、三处既有交易夹具、`README_FULL.md` 与本台账。没有新依赖或 schema，复用已有 counters/状态和 apply 公式，合并兼容 submission 实现并删除分步写入/旧 raw 状态决策。费用/资金费逐笔来源、每个历史 attempt 的持久证据、逐腿账户对账/风险冻结、完整模拟账户仍是后续 C5；不据此关闭整个 Goal。
- 后续先检查 C4 `CCryptoAccount` 的可复用范围：它是独立成交 lot、固定费率/不利滑点的模拟账户，不能把已经执行的真实价再套一次滑点或把缺 fee 当 0。逐笔真实 trade/fee/funding 与每个历史 attempt 的不可变证据必须先落地，不能靠当前最后一个 cover 槽和 legacy 汇总均价完成现金流证明；旧来源不全时 fail closed，保留可证明的管理路径。仍未连接任何真实交易账户。

### C5 第五子边界实施与清理计划：不可变尝试历史和事务性证据

- 起始 clean `3b8de16144aa24cd6cb962f455c4846720d726f4`，上一轮为有效进展。继续串行、SQLite/fake I/O，不调用真实账户或正式研究。
- 先为 SQLite 显式事务、内层 savepoint 和失败回滚写 RED。已有 execute 的单语句提交保持兼容；事务内不得提前 commit，日志追加失败时投影与历史一同回滚。将既有交错夹具放在实际 read→transaction 边界，不在已持写锁的 SQL 内伪造另一个同步写者。
- 增加只记录事实的 order attempt/event 历史，而非第二套生命周期。新 intent 与不可变身份在同一事务登记，client 在整个历史中唯一；claim、ACK、已应用回报随当前投影原子追加。finite canonical、SHA/链、重复幂等及只追加约束由实际 SQLite 验证，读取时重新核验，不依赖 Python 缓存。
- 历史只允许指定白名单字段，不记录密钥/请求头/任意错误响应。旧记录不回填“过去创建”事件；首次有合法观察或在覆盖前保存为 legacy_snapshot，保留未知时间/单位，不声称历史完整。所有 counter 的缺项和 legacy 来源在 reader 中显式暴露。这里仍无真实 trade/fee/funding 证明，不计算或开放正式研究绩效。
- 替换 close 槽覆盖前的证据丢失，保留现有 intent/CAS/apply 公式和 MySQL disabled 边界；完成短夹具、原 trade/recovery/部署回归及 Lore 推送后，再接逐笔经济来源、逐腿账户、风险冻结和完整模拟账户。C5/C6/C7 未完成，Goal active。

### C5 第五子边界证据：追加式尝试历史和同事务投影（C5 未完成）

- SQLite 事务首轮 5 RED / 1 compatibility PASS：缺 transaction，以及失败单语句留下悬挂事务。显式 BEGIN IMMEDIATE、嵌套 savepoint、失败 rollback 后 6 GREEN；原单语句 execute 仍提交。初始化把原表补列与新增历史 schema 放在同一事务，同名异构表失败不遗留半次迁移，也不改动外来表。
- 历史层首批 19 RED：覆盖 intent/claim/ACK/report、重复/失败 CAS 无追加、历史 client 跨 phase/attempt 重用、追加失败回滚投影、旧快照/缺项、重启和只追加约束。新增 OrderAudit 只记录白名单事实，依附原状态机而非第二套决策；新意图与不可变身份同时登记，旧 close 被覆盖前归档。当前执行查询仍只返回当前 intent，不把历史单当新单恢复入口。
- 完整性追加测试确认并修复两个 RED：最后一条回报被离线删除、当前 client 被改写后，单看 SHA/尝试链不足；现同时核对历史尾部、当前身份和投影。串行自审再用 RED 证明下一回报会掩盖已有投影损坏，写入事务先验证原历史/投影，再执行 CAS。只追加 UPDATE/DELETE/REPLACE、canonical/链/序号损坏、规格漂移、不缓存返回对象、非有限值失败和双连接不可见性均有实际 SQLite 检查。哈希不冒称交易所签名或整体文件重写防护。
- 真实 CCXT/fake I/O 的 Binance/OKX 部分平仓→终态→下一尝试保留完整旧规格与回报；新增两项 RED 找到白名单遗漏 CCXT precision.base/quote/cost 的显式 null，补齐后与完整 v2 字节一致。first-seen 时间与原 intent_ms 分开，旧 null 不猜 UTC；未知规格只保留安全字段/原 SHA 与 contract_complete=false。任意错误响应与 snapshot 不复制入历史，费用/资金费尚未接入，economics_complete 始终 false。
- 两个既有“旧单”夹具原本在新意图已持久后原地清时钟/降 v1，现在准确视为身份损坏。改用共享临时 helper：仅复制旧主表且没有历史表，实际走迁移；验证旧时钟仍 null、已知 server id 可只读恢复、缺 v2 执行证据仍不能自动平仓。未为这项夹具修正计生产 RED，也未放宽新单身份。双进程 claim 检查只产生一条 claim 事件；原 CAS 交错移到 read→transaction 边界，避免在持写锁时伪造同步写者。
- 最新定向验证：151 passed（20.37s），覆盖全部 35 history、6 transaction、63 recovery、47 venues。最终 trade/state/safety/recovery/部署组合 312 passed / 3 existing small-model warnings，60.40s。完整离线回归 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：848 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，517.96s。此前 38 history/transaction（5.21s）适用于补写入前检查之前，未当作当前组合验收；一次错误部署测试文件名导致 0 tests，仅为命令错误。运行中未改源码、未启动第二套测试；之后只补本文数字和 README 迁移语义。
- 文件范围：`Trade/OrderAudit.py`（新增）、`Trade/SqliteDB.py`、`Trade/db_util.py`，新增 `tests/test_order_audit_history.py` / `tests/test_trade_sqlite_transaction.py`，以及 `tests/test_order_report_cas.py`、`tests/test_crypto_order_contract.py`、`tests/test_crypto_order_recovery.py`、`tests/test_crypto_venue_parameters.py`、`README_FULL.md` 与本台账。复用一处事务写入入口和一个旧库复制夹具，不新增订单状态机或依赖；旧 binary 不维护新历史，回退先停写，禁止新旧写者混跑。
- 本次仍没有真实 trade/fee/funding、逐腿账户对账/新风险持久冻结或完整 dry-run 账户，也没有真实交易所调用、正式研究/绩效读取。后续 C5 从每笔成交/手续费/资金费的独立来源接入和对账开始，再处理风险冻结/模拟链；C6/C7 与外部认证仍未完成。无新依赖、配置/权限/研究修改；按串行约束由主代理自审，不冒称独立审计。

### C5 第六子边界实施与清理计划：逐笔经济来源和幂等存储

- 起始 clean `0004721876838403bc7ddbfa0a44d4167db530b5`；上一轮已快进推送且完整离线 848 通过，属于有效进展。继续主代理 Inline 串行，不运行真实账户/正式研究。沿用 executing-plans/TDD/verification，不建立第二套订单生命周期。
- 核对本机 CCXT 4.5.43 与官方 [Binance userTrades](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List)、[income](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Income-History)、[OKX fills-history/bills](https://my.okx.com/docs-v5/en/#order-book-trading-trade-get-transaction-details-last-3-months)。分别实现只读原生来源；Binance 时间窗饱和时拆分，禁止 fromId+time 非法组合；OKX 以 billId 排他 after，不误用 tradeId。固定传输预算/90 日上界，饱和毫秒、无进展或预算耗尽均为 unknown，不当缺交易证明。实际保留期/余额完整性仍需后续独立对账，空页不证明零资金费。
- 使用原生数值字符串做固定 Decimal 精确转换，保存张数/币数、成交价、已实现损益、费用币种及有符号费用现金流；OKX 扣费/返佣符号不取绝对值。funding 保留实际现金流与原生 ID/时间，不拿费率估算、不在缺腿身份时猜归属。只保留白名单，无密钥/请求头/任意异常正文。普通订单 avg/filled 不能替代来源。
- SQLite 增加独立只追加 execution facts/scan，复用同事务、有限 canonical/SHA、重复同值幂等/同 ID 变值拒绝与原子升级模式；不改原订单投影。显式非秘密 account_scope 只是调用者命名空间，不冒充已认证服务器 UID。默认引擎入口仅在显式调用时读现有会话，dry_run 不创建真实会话，MySQL 不认证。
- 先 raw fixture RED/GREEN，覆盖两平台真实本地 CCXT parser 对照、页/窗/同毫秒、符号/重复/缺费/缺时间/原生错误；再 SQLite rollback/重启/冲突/只追加和引擎不重下。逐腿余额/mark、完整 cashflow reconciliation、持久化冻结与含费模拟仍是后续 C5；不得把本次 observed facts 宣传成完整账户验收。

### C5 第六子边界证据：原生逐笔来源与去重导入（C5 未完成）

- 先观察缺 ExecutionFacts 模块的 RED，再最小原生 reader；32 初始 GREEN。追加三项真实 RED：OKX 近期成交错误依赖 archive、reseal 后浮点 timestamp 与整数字段被 Python equality 混同、formatted exception chain 暴露原始响应。现按近期/归档分路、canonical 字节比较、公共错误 suppress raw cause。没有真实账户 HTTP 调用。
- 复核原生文档/本机 parser 后，8 项单位 RED 证明首次统一 contracts×size 会把 Binance 原生币数再乘一次；现 Binance qty→币数、币数/size→张数，OKX fillSz→张数、张数×size→币数。两种来源不是同一字段单位，保留 native_quantity_unit / pnl_currency。缺费用/NaN/错误标的/腿/时间、费用返佣、BNB fee 不转 USDT PnL、重复变值均有覆盖。仅为本机 parser/fake 协议证明，不认证真实 market/交易所。
- 另外两项时钟/channel RED：OKX ts 是生成时钟，缺 fillTime 不再伪装成真实成交；资金费额、额外 fee、钱包和逐仓变动分开，不发明相加或按净量分腿。funding 只记实际来源与货币，缺字段不补 0；funding 归属和账户闭合依然未证明。四项白名单类型/枚举 RED 后，非法 maker、marginAsset、clOrdId/execType 在落库前拒绝，不复制任意响应。
- ExecutionStore 首组 15 RED→GREEN：实际 SQLite、两币所来源重启可读、重复导入去重、scan 失败全组回滚、native fee 变异冲突、UPDATE/DELETE/REPLACE 禁止、foreign schema 不自动采用、显式引擎调用不产生订单、dry-run 不造真实会话。scans 存 manifest 链接事实而非反复复制大 payload；读回重新查字节/SHA、身份/市场单位并重建原收据，不使用缓存。
- 两项 review RED 修复：OKX billId 对整个账户跨 kind 唯一，不能同时支付为 trade 与 funding；Binance funding tranId 不能换标的，冲突整组 rollback 并转为明确 CChanException，不触发重下。另四项持久化损坏/伪造 economics_complete=true 检查通过。
- 适用组合 385 passed / 3 existing small-model warnings，61.40s，包含当时 52 source / 21 store / 35 history / 6 transaction、原 CAS/recovery/venue/safety/deployment。之前 383 为补跨 kind 唯一约束前结果，未当作最终源树。第一轮完整离线 921 passed / 7 skipped / 1 network deselected / 14 existing warnings，519.08s。自审在该进程结束后补 RED，证明缺 CCXT 时 except tuple 会触发 UnboundLocalError；将原 lazy import 移到 try 之前，未把它改成核心必需依赖。修正后 115 source/store/history/transaction passed（6.44s），另以新解释器屏蔽 ccxt 完成 SQLite 核心构造 smoke；第二轮完整离线 922 passed / 7 skipped / 1 network deselected / 14 existing warnings，522.71s。没有把这些旧树结果重标为最终修正的执行。
- 最后一个发布边界 RED：真实 SQLite 第一次 INSERT 后改变调用者第二条原生事实，原实现返回成功但扫描根摘要已经与事实不符。现在 CChanDB 在取得写锁前用既有 finite canonical helper 冻结自有输入对象；相同交错后原收据、facts 和 manifest 均保持校验前的字节，116 focused passed（6.52s，53 source / 22 store / 35 history / 6 transaction）。仅做一处快照，不加新 publisher/订单状态机。最终完整离线 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：923 passed / 7 expected skipped / 1 network deselected / 14 existing warnings，521.13s。每次前一进程终止后才编辑，始终只跑一套测试；最后仅补本文数字和钱包范围说明。
- 文件范围：新增 `Trade/ExecutionFacts.py`、`Trade/ExecutionStore.py`、`tests/test_execution_facts.py`、`tests/test_execution_store.py`；修改 `Trade/CCXTTradeEngine.py`、`Trade/db_util.py`、`Trade/SqliteDB.py`、`Trade/OrderAudit.py`、`README_FULL.md` 与本台账。只复用 schema validator 的可选 schema、既有 SQLite 事务和 canonical helper；无依赖/配置/权限/研究改动，没有第二个订单生命周期。
- 下一步前置缺口：现有 intent/order_contract 只冻结 venue/执行参数，尚未冻结服务器账户 UID/环境；account_scope 是调用者标签，不能仅按 order_id 跨账户绑定历史。C5 先加入原生只读账户身份与新意图的同事务冻结，再用真实历史 client/id/attempt 证明归属，处理遗留缺项；随后才独立重建逐腿 cashflow/mark/余额、设置持久化新风险冻结、补完整 dry-run 账户。完整钱包还需转账/转换/利息/强平附加费用等独立流水，不能把 funding-only 当全账户现金流或余额差当收益。不得把本次 flags=false 源收据改作账户 PASS。C6/C7 仍未完成，外部认证/正式研究/真实订单门禁不变，Goal active。

### C5 第七子边界实施与清理计划：原生账户和环境绑定

- 起始 clean `aa85fae98ebe75a8f28f7208bb3b31ea4388f63f`；继续主代理串行、TDD、fake 私有 I/O。复用现有 intent/CAS/追加式历史，不另建订单状态机，不迁移或补造旧授权。
- 核对官方只读接口及本地 CCXT 路由：Binance USDT 永续 balance 的 `accountAlias` 是原生唯一账户别名，OKX account/config 的 `uid` 是账户标识；分别冻结 typed identifier 的摘要，不把 Spot UID、API key、调用者 account_scope 冒充永续身份。上一节笼统的 UID 在此细化为平台原生标识类型。
- 先测试缺模块/错 sandbox/私有路由/模拟盘请求头/缺失或冲突身份/原始错误脱敏；仅在实际客户端环境与本地无凭据 CCXT 标准路由一致后读取账户标识。摘要收据不包含原生标识明文、余额或任意响应，也不声称服务器签名/外部认证。
- 新 swap 契约使用 v3，把账户上下文冻结到原有 order_contract 和同事务 journal；提交、恢复、取消及降风险时重新核对已冻结身份。v1/v2 保留明确的只读历史兼容，不因重启获得 v3 身份；缺原始账户证据的旧 swap 不能自动新建 reduce 意图，显式关联证明留待后续归属边界。Spot v2 不受新 swap 身份语义改写。
- 清理仅为让 v2/v3 共用现有执行参数/回报检查和 journal 白名单；先有回归，再删除仅 v2 的误分支，不改成交公式。fake 客户端显式带合法 sandbox 路由及原生身份响应，仍拦截全部真实 HTTP。
- 短组合、核心可选依赖隔离、完整离线/compileall/diff 与 Lore 快进推送后继续 C5：原生逐笔归属、逐腿钱包/mark 重建、持久冻结、含费模拟仍未完成。不得提升旧 observed_execution_facts 的 flags，也不关闭 Goal。

### C5 第七子边界证据：新永续意图的原生账户/环境身份（C5 未完成）

- AccountIdentity 先观察缺模块 RED，再用真实无凭据 CCXT 路由和 fake 原生账户 GET 实现最小 GREEN：Binance/binanceusdm 使用 Futures balance V3 的唯一 accountAlias，OKX account/config 使用 uid。两者 typed digest 分开，环境保留 testnet/live、sandbox、有效私有路由、OKX hostname/模拟盘头；不保存原生 ID 明文/余额/任意响应。不存在 Spot UID 回退、隐式账户模式修改或真实 HTTP。
- 新 swap 契约 v3 将上下文并入原 finite canonical contract_id 和 SQLite 同事务 journal，Spot 保持 v2、dry-run 无账户会话。v2/v3 共用旧执行/回报检查，journal 只扩展既有白名单，无新表/迁移或第二套订单生命周期。CChanDB 的旧 v1/v2 字节不补字段，旧 history origin 也不改写。
- 实际 RED 证明旧实现会先请求错环境的 private settings、接受 mid-prepare 账户变化、在意图后换账户仍 claim/submit、跨账户 query/ack/cancel 和把 v2 视为足够的 reduce 授权。修正后私有读取前检查 sandbox/TLS/全部相关私有路由/模拟盘头；准备末、claim 前和响应后重新读原生身份。首次 legacy fixture 错用未支持的 context manager，改为 try/finally 后再次观察两项真实 DID NOT RAISE RED，不把 fixture 错误当行为证明。
- 追加两组 race RED：提交响应期间换账户，原来仍保存 ACK，现保持同次 submitting/无 ACK/无 fill，未知不补单；检查原开仓与准备平仓之间换账户，原来会产生新账户的 close contract，现与原 frozen context 再比对，准备即失败。未知服务器 id 撤单也先拒绝，不发私有动作。
- 旧 v1/v2 swap 保留历史单位/回报的兼容读取，但没有历史账户证明，不能自动新提交、取消或新建 reduce 意图；不是既有资金管理的外部认证，人工/显式关联迁移仍待后续边界。v3 同账户重启后能够继续 query、累积 fill 和取消原单；后续全局 mode/margin 或 leverage 变化的已知 leg 降风险仍通过前序回归。
- 初始交易组合 387 passed（41.04s）；补充 guard/重启回归与 safety/state-machine/部署组合 176 passed / 6 existing model warnings（41.01s）。最终新测试为 41 identity + 26 SQLite binding，均由后续完整树包含。独立新解释器屏蔽 ccxt，核心 identity/引擎导入、SQLite 与 dry-run 构造 PASS，不新增核心依赖。
- 完整串行离线命令 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：990 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，553.29s。前一 pytest 明确 exit 0 后才补本节；compileall/diff 已通过，提交前再核 staged diff。按主代理串行自审，不冒称独立审计。
- 文件范围：新增 `Trade/AccountIdentity.py`、`tests/test_account_identity.py`、`tests/test_crypto_account_binding.py`；修改 `Trade/CCXTTradeEngine.py`、`Trade/OrderAudit.py`、`tests/test_crypto_order_contract.py`、`tests/test_crypto_venue_parameters.py`、`tests/test_trade_safety.py`、`README_FULL.md` 与本台账。fake 私有 I/O 和真实本地 request builder 不变，没有依赖/配置/权限/冻结研究改动。
- 范围与下一步：观察到客户端上下文不是服务器签名/全局客户端锁，未真实验证测试网路由、区域 endpoint 或频率/延时预算。后续先把新扫描的前后原生上下文与原 scan hash 独立关联，再用历史 attempt/client/server id/单位/时钟核实逐笔归属，不能仅凭 identifier_sha256 忽略 venue+mode，也不能给旧扫描补造身份或提升 `account_scope_verified=false` / `economics_complete=false`。钱包转账/转换/利息/强平等流水、逐腿 mark/余额重建、持久风险冻结、含费模拟与 C6/C7 仍待，Goal active，所有研究/真实订单/外部认证门禁保留。

### C5 第八子边界实施与清理计划：扫描身份关联及历史尝试归属

- 起始 clean、已推送 `9a914c2aac6ed53bb232c8de20f924a59083cad3`；上一轮完整离线 990、提交后 67 项通过为有效进展。继续复用 executing-plans/TDD/verification，主代理串行，不连接真实账户，不触碰冻结研究。
- 不新增一套 publisher/订单逻辑或补造旧身份。复用 execution_scans 的不可变 manifest，增加明确 v2 形状：原 source receipt/hash 不变，额外关联本次扫描前后的相同原生 account_context 与观察时间。只有新扫描首次原子导入能绑定；已持久化的 v1 无关联扫描不允许事后补证。原 source reader 仍返回原 bytes/flags=false。
- 相同 account_scope+venue+mode 已有关联时，后续扫描不能静默切换 account_context；同 namespace 的旧未关联来源保留未关联，不能因名称相同获得当前身份。重复相同 source/context 幂等保留首次观察；冲突、扫描中换账户、关联发布失败均整组不写 facts/scan，不影响订单状态。
- 增加独立逐笔归属观察入口，在同一 SQLite 快照读取 source、关联与完整历史 attempts；按原账户/venue/mode/market、实际 server/client id、attempt、方向/leg、真实成交时钟和精确数量检查，不从当前最后一个 close 槽、名称标签或净持仓猜来源。无 id、缺时钟、外部/遗留来源、歧义和超请求量须显式 records，不排名选择。
- 归属仅覆盖该已关联扫描内实际观察的 trade，不证明无遗漏/完整现金流；缺资金费 leg 时明确 unallocated，不按净量分配，不以零条记录放行新风险。本边界不更新 qty/PnL、不解除冻结、不把 coverage 写成完整账户 PASS。独立钱包来源与逐腿余额/mark 对账、持久冻结、含费模拟继续属于必须完成的后续 C5。
- 先 manifest/绑定失败 RED→GREEN、native engine 前后观察与 SQLite rollback/重复/重启；再真实历史多次 partial-close attempt 夹具及单变异归属 TDD。最后适用前序交易/源/部署回归、完整离线、核心可选依赖 smoke、compileall/diff/Lore 与已授权的快进推送；Goal 保持 active。

### C5 第八子边界证据：有原生观察的扫描与完整历史尝试（C5 未完成）

- 17 项初始 RED：缺 account_observation 写入/读取接口，以及扫描中切换账户仍会写入。最小实现保留 source v1 的原始有限字节/SHA/flags=false，既有 scans manifest v2 只额外记录相同前后 account_context 与 UTC 观察边界，不新增 SQL 表/迁移或 publisher。首次 facts/manifest 同事务发布，输入 receipt+observation 在写锁前一次自有快照；profile 读取发生在 DB 锁外。
- account_scope+venue+mode 已有 native context 后拒绝静默换上下文或新增 unbound 来源；已有 v1 不允许事后关联，重复 v2 保留首次观察，不剥离关联。不同仪器的同一命名空间仍约束原账户，已有未关联扫描不会因后来同名绑定而改 flags。scope 仍不是服务器认证。两只原有表的 append-only/foreign schema/原子失败语义不变。
- ExecutionReconcile 先观察缺模块 RED；数据库入口在同一 SQLite 快照核验来源、关联及该标的全部已验证历史 attempts。原生交易按完整账户/venue/mode/market、已记录 server id、回显 client id、phase/attempt、方向/leg、真实 fill 时钟和精确数量归属；不用当前最后一个 close 槽，也不从 native fill 猜补 ACK。输出绑定 source/account/history SHA，仅为 observed_scan_facts_only，economics_complete=false。
- 两平台真实 SQLite 夹具执行 open→partial-close-canceled→second-close，覆盖 long/short 与 one-way/hedged，三笔分别引用 open1/close1/close2，重启逐字相同且不改 qty/PnL。错 order/client/side/leg/time/account/单位、legacy、歧义及逐笔或合计超请求量均给出 unowned records；另一账户同号的 server id 不混淆。缺 ACK 先 unrecorded，只有原状态机查单恢复取得原 id 后才 owned，仍只有一次下单。
- 提交前自审的 RED：9 种重算 SHA 后的 manifest/fact 缺字段或错误对象曾泄漏 KeyError/TypeError；在解析入口先验证形状，统一 CChan 失败，不隐藏或修复损坏源。另两项冻结 contract_id/contract SHA RED 后，损坏指纹不能授权 owned；一个 Decimal Emax/Emin/Subnormal trap RED 后，数量核算使用固定 50 位有界精确 Context，不继承调用者 traps，不用容差擦小仓。
- 适用源/归属/历史/事务最终组合 187 passed（21.54s）；更早交易/恢复/部署组合 559 passed / 6 existing model warnings（96.31s）是补指纹/固定 Decimal 前的树，没有当作最终树证据。完整命令 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：1061 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，538.99s。每个先前 pytest 均在明确 exit 后才编辑；未同时启动第二套长任务。
- 新解释器屏蔽 ccxt，ownership/store/交易核心导入与 SQLite/dry-run 构造 smoke PASS；compileall/diff 已通过，提交前再核 staged diff。主代理按串行约束自审，不声称独立审计；没有真实账户 I/O、正式研究/绩效、依赖/配置/权限修改。
- 文件范围：新增 `Trade/ExecutionReconcile.py`、`tests/test_execution_account_binding.py`、`tests/test_execution_ownership.py`；修改 `Trade/ExecutionStore.py`、`Trade/CCXTTradeEngine.py`、`Trade/db_util.py`、`README_FULL.md` 和本台账。复用原 manifest、事务、source normalization、history verifier 和 canonical helper，删除旧重复的 manifest 发布/字段检查分支；没有第二套订单生命周期。
- 下一步仍为 C5 必需工作：独立 account-wide 钱包流水（含非 funding 的转账/转换/利息/强平等，不与 trade fee/PnL 双记）、带原生来源/时钟的逐腿持仓与 mark/余额观察、对账差异和持久化新风险冻结，保留已证明的取消/降风险，及完整含费模拟账户。当前 funding 缺 native leg 明确 unallocated；扫描局部/空页/零异常不能证明无遗漏或完整现金流。全账户现金流与逐腿资金费分配是不同证据，不能为凑 PASS 猜分配；实际限频/锁时延预算和外部平台仍未认证。C6/C7、Goal 与所有交易/研究门禁保持原状态。

### C5 第九子边界实施与清理计划：独立全类型钱包和逐腿账户来源

- 第八子边界已 Lore 提交并推送 `97bfa85e99e0d6f3b68f2914d34ee32cd181901b`，精确提交后 71 项复验、远端一致且 clean，为有效进展。继续 Inline 串行、fake native GET、TDD；不调用真实账户，不放宽候选/测试网/实盘/研究门禁。
- Binance 全账户 income 不传 symbol/incomeType；原生唯一键是 (incomeType, tranId)，不同收入类型不能仅按 tranId 去重。OKX 全账户 bills 不传 instId/instType/ccy/type 等过滤，保留 account 与 isolated-position 的现金/余额 channel，不把 pnl+fee 再加到 balChg，不把 trading-account 流水冒称 funding-account 钱包。逐币保留，不能把 BNB/美元总资产误当 USDT。
- 逐腿 snapshot 使用原生账户资产、position risk/positions、市场单位及原生 margin/mode 证据，明确币数与张数、long/short、mark、entry、reported unrealized、初始/维持保证金与时间。多空同时存在不得净额抹除；零数量且有 isolated 余额的记录不丢弃；不支持或未提供市场 metadata 的持仓保留显式 unsupported 证据，不猜单位。
- 输入前后复用原生账户/环境绑定；钱数字符串复用现有固定 Decimal 边界、canonical/SHA，不复制 raw 私有标识/任意响应。分页/时间窗/限额只是协议预算，饱和或无进展 fail closed，空页不认证经济完整；snapshot 是一个观察区间，不把 updateTime 伪称 mark 生成时间，也不保证两个 REST 响应原子同一时刻。
- 使用小型真实协议夹具先 RED→GREEN，再同一 SQLite append-only 证据表原子保存账户级文档，独立于按 instrument 的 execution facts；复用原 schema/事务校验器，不造另一套订单生命周期。旧库非破坏性增加独立表，不给旧扫描/订单补原始资产。引擎显式 sync 入口无订单/配置副作用，dry-run 不建会话。
- 本轮完成独立钱包/资产/逐腿来源及存储后，继续用两端可信观察与全类型现金流做钱包闭合、DB/原生成交逐腿数量/mark 对账，再接持久风险冻结及含费模拟；这些缺口仍是 C5 必需验收，来源 receipt 一律不提供 PASS/放行接口。短组合、核心缺依赖、完整离线与 Lore 快进推送后继续 Goal，不将本子边界当 C5 完成。

### C5 第九子边界证据：全类型钱包、逐腿快照与独立持久来源（C5 未完成）

- AccountSources 先观察缺模块 RED；全账户钱包不传 instrument/type/currency 过滤，Binance income 采用 (incomeType, tranId)，OKX bills-archive 用 billId 排他 after。复用原 ExecutionFacts 的固定 50 位 native decimal/ID/currency 边界和原生身份前后观察；保留真实 account/position cash 与余额 channel、原币 fee/pnl/interest，不将分量二次加进余额，不把陌生原生类型猜为收益。原生 notes/info、余额接口附带私有 ID、任意响应和异常正文均不复制；无真实 HTTP。
- 钱包 fixture 覆盖两平台 transfer/funding/保险或未知类型、BNB 原币、相同 tranId 不同 incomeType、独立 fee/pnl 与 isolated channel、时间窗拆分/饱和毫秒/请求预算/停滞游标、错误格式/缺现金/冲突/重算摘要及脱敏。首次 bool-time 两项未触发是 fake server 提前把坏行过滤掉；纠正 fixture 为直接返回坏 wire row 后验证原解析器确实拒绝，没有放宽类型约束来凑 GREEN。
- Snapshot API 缺函数 RED 后，原生 account/balance、positions/positionRisk、Binance symbolConfig/multi-assets margin 形成可复核有限文档；Binance 原生数量是币数，OKX 是张数，再按显式 metadata 转双单位。long/short 不净额，零数量有 isolated 资金的返回记录保留；未知市场持仓明确 unsupported，不能猜单位。多币余额、reported realized/unrealized、entry/mark/初始/维持保证金与原生 update time 独立保留，USD 总值不标 USDT，未提供的字段保持 null。mark_ms 明确 null，不把账户更新时间假称 mark 生成时间，不冒称多 REST 响应原子一致。
- 自审四项真实 RED 后，独立 Binance account leg 重复、该响应内非有限金额、unsupported position 内 NaN 和未来时钟也拒绝；不能用 unsupported 标签跳过来源验证。账户切换/原生异常、重算摘要后的 summary 或 mark 时钟变异、低精度与 Subnormal 调用者 context 均有回归。
- AccountStore/DB/engine 首组 20 RED→GREEN：单一新增只追加 chanpy_account_evidence，重用 SQLite 事务、schema 精确核验和有限 canonical；同文档幂等、原生流水同 context/ID 变值拒绝、不同账户 ID 不混同、失败回滚、重启重读、UPDATE/DELETE/REPLACE 拦截、foreign schema 整体升级失败原样保留。导入前取一次自有文档快照；网络发生在写锁外，dry-run 不建真实会话，三种源入口共用既有会话门禁，订单生命周期/qty/PnL 不改。
- 适用来源/存储/历史/事务先 211 passed（23.62s）；交易/恢复/部署组合 586 passed / 6 existing small-model warnings（92.58s）；首轮完整离线 1138 passed / 7 skipped / 1 network deselected / 14 existing warnings，541.67s。该进程明确终止后才做后述窗口修正，没有将 1138 当最终修正树结果。
- 收尾审查发现 OKX 文档未明确 begin/end 的包含语义；钱包 2 项 RED、旧 ExecutionFacts 2 项 RED 在严格 filter 模型下证明旧换算会静默漏目标首尾毫秒（不声称已经真实认证服务端语义）。现在原生钱包、成交及 funding 都在目标外读取邻接整数毫秒，校验所有返回 wire 身份/冲突，再本地严格过滤到原 [start,end)。recent/archive 各 lane 仍精确 end-exclusive，另外 2 项切换 fixture 证明无重算/漏 cutoff。Binance 已明示 inclusive 的参数不改，旧收据 bytes/validator/flags 不升级，没有修改冻结 research。
- 最终来源/账户/历史/事务组合 270 passed（23.64s），包含新 29 wallet / 30 snapshot / 20 store 及原 57 execution source 等。最终完整命令 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider`：1144 passed / 7 expected skipped / 1 network deselected / 14 existing model warnings，540.98s。始终只运行一套测试，结束后才补台账；compileall/diff 已通过，Lore 前核 staged diff。ccxt 被新解释器屏蔽时 native source/store/交易核心导入、SQLite 与 dry-run 构造 smoke PASS。
- 文件范围：新增 Trade/AccountSources.py、Trade/AccountStore.py 及 tests/test_native_account_{sources,snapshot,store}.py；修改 Trade/CCXTTradeEngine.py、Trade/ExecutionFacts.py、Trade/SqliteDB.py、Trade/db_util.py、tests/test_execution_facts.py、README_FULL.md 和本台账。没有新依赖、用户配置/权限/规则或研究变更；只共享旧转换/事务/校验/会话 guard，不建立第二套订单引擎。按串行约束主代理自审，非独立审计。
- 继续 C5 的真实缺口：需要可信观察区间与全类型账单的逐币钱包闭合，独立重建 DB/原生成交的逐腿数量/mark/PnL 并处理 native 精度/未知，接同事务持久新风险冻结、保留可证明的取消/降风险，再完善含费/资金费/不利路径模拟。全历史钱包文档校验容量、数据保留/同步时延和限频、区域端点与实际交易所均未认证；unknown/empty/source import 本身不能当账户 PASS。C6/C7 未完成，Goal active，候选/测试网/实盘/正式研究门禁保持。

### C5 第十子边界实施与清理计划：观察区间对账与持久新风险冻结

- 起始 clean、已推送 a55337462ea5d439e81d3006c77074e32a3b6891，上一轮 1144 完整离线与提交后 136 项为有效进展。复用 executing-plans/TDD/verification；主代理串行、fake I/O，无依赖/用户配置/权限/研究更改。
- 对账在同一 SQLite 快照加载原始两个账户文档、全类型钱包覆盖、已关联 execution scans、完整 histories 与当前 projection。逐币检查 before + 原生 account_cash_delta = after，不再次加费用/PnL，不把 position_cash_delta 乱摊腿。快照观察区间内有现金流/成交、窗口缺口/晚到、缺资产/单位/时钟或未归属来源均明确 incomplete，不据空页/净量或一个最终余额产生放行证明。
- 按真实成交来源和 v3 attempt 构造每腿 pooled basis/数量变化；用 Fraction 精确表示无法有限展开的均价，严禁把调用者 Decimal context 或任意 epsilon 当交易所舍入规则。比较 DB before/after quantity、每 attempt 增量、原生最终 legs/entry/mark/UPnL、资产级 UPnL 与独立原生现金流分量。native 已舍入值不匹配时如实留记录，支持精度的正式外部验证不在 fake PASS 中暗补。
- 明确单位：OKX position IMR/总 notional 是 USD，不与 USDT PnL/币数量直接相加；钱包闭合与资金费逐腿分配分别披露。unsupported/legacy/外部来源不排名择优。原 source flags=false 不改，新的 matched_observations 仅是给定区间/来源的数学核对，不是全账户/平台/策略认证。
- 新增只追加对账/冻结记录，原生身份以 venue+mode+typed identifier 为稳定冻结键，不靠调用者标签或可切换的路由 context id 清锁。差异或缺证据在同一事务持久冻结；重启/另一个连接/自定义 trade table 不能绕过。后续成功观察不得自动解冻，本轮不提供接受任意 passed/report/布尔值的解锁 API。
- 新风险 prepare、intent/claim 与最终发送前核对持久冻结；intent/claim 的 DB 检查与原 CAS 在同一事务，避免 check-then-claim 窗口。close/cancel/query 的既有原账户证据与全局交易门禁不弱化，账户冻结本身只阻断新增风险；先获 claim 后出现冻结的 in-flight 仍保持未知并由恢复管理，不声称能撤回已发送网络请求。
- 不重做订单状态机；复用现有 source/history verifier、canonical/schema/事务。先纯数学 RED→GREEN，再 SQLite 冻结、两连接竞态、legacy/缺证据、原账户取消/降风险、篡改/重启 RED→GREEN；完成适用交易/部署和完整离线、compileall/diff/Lore 后快进推送。C5 的 native 精度实际验证、缺失情况下的准入链与完整模拟以及 C6/C7 仍须逐项验收，不能因本子边界关闭 Goal。

### C5 第十子边界证据（2026-10-22）：观察区间核对与持久失败闭锁，C5 未完成

- 起始 clean、远端一致 a55337462ea5d439e81d3006c77074e32a3b6891。先观察 AccountReconcile 缺模块 RED，再真实 native parser/SQLite attempts 夹具 GREEN。首次实现后的失败含旧 fixture 残留权益与 OKX 未来模拟时钟，修正夹具自洽性而没有放宽生产检查；随后“原生总值与有效明细矛盾”有独立 RED→GREEN。Binance/OKX、long/short、one-way/hedged、部分平仓、费用及 exact-ms funding 均有正例，原订单数量/损益不因检查被改写。
- 两个不重叠观察区间、钱包/每 market execution guard 窗口、相同原生 account/context/market、逐币 before + account_cash_delta = after，以及原生余额链/费用/PnL/funding 分量分别核对。窗口缺口、快照内事件、时钟倒退/迟到、缺资产、unowned/legacy/未终结 attempt、unsupported/isolated/借贷通道均显式记录，不能把空扫描或最终余额当完整账户证明。重叠来源按原生 ID 去重，不重复加 fee/PnL，不按净量分 funding。
- 原生每腿 pooled basis 按真实 fills 重建，独立对照两端 DB/native 数量、每 attempt 累计增量、entry、mark UPnL、资产 UPnL/equity 和 Binance 独立 account/positionRisk/USDT totals；不沿用虚拟单条记录的剩余成本。两平台真实多条策略记录的部分平仓 fixture 得到均价 401/4；循环均价 704/7 保留 Fraction，原生舍入报告明确 mismatch，不能用 epsilon 接受。低精度/Subnormal 调用者 context 不改变结果。
- OKX trade delta 与正确 fee/PnL 却可调平终值、funding pnl 与 account delta 不一致两项真实 RED 后，分量交叉检查也拒绝。OKX position IMR/MMR/notional 的 USD 与 USDT 不相加；原生 mark 生成时间仍未知，funding 仍 account-only/native-leg-missing。来源 flags=false 与本地 observed 范围不升级。
- 11 项 DB API 缺失 RED 后新增单一只追加 chanpy_account_checks，原始 source IDs、当时历史/数量和确定性 report 同事务发布。缺文件、坏来源或坏 projection 保存脱敏 evidence_unavailable，而不是因异常回滚掉该冻结；发布失败则整笔回滚并抛错，原订单不变。只用历史任一非 matched 状态的 OR 形成 sticky freeze，不维护第二份可变冻结状态/订单状态机。
- 冻结键是 venue+mode+typed native identifier，跨重启、第二连接和自定义 trade table；不能靠 scope/路由 context id 或下一次 matched 解除。新 swap v3 prepare、open intent/claim 同事务、最终发送前核验；claim 后另一连接冻结则不发送、不重置 created、不自动重下，原账户 cancel/query/reduction 保留。已经发送网络请求的不可撤回 race 不冒称被消除。
- 收尾自审两项 RED：仅修改 account_key 索引列曾隐藏检查；仅重算 check/report 摘要曾改写旧 event 时间。现在过滤前核验所有元数据，并复用 OrderAudit 验证旧快照是原不可变 journal 前缀；后来合法退出不使旧快照随 projection 重写。另有两项 disabled PRAGMA RED→GREEN；关闭 foreign_keys/recursive_triggers 时闭锁而不暗中修配置。UPDATE/DELETE/REPLACE、foreign schema 整体升级失败原样保留、发布失败、缺证据、源摘要变异、两连接 CAS 与发送后边界均有测试。按串行约束主代理自审，非独立审计。
- 适用交易/恢复/部署组合 531 passed / 1 expected skipped / 6 existing warnings（109.38s）；该结果在最后两个明确时钟记录补齐前取得，不伪称最终树。最终 account/source/ownership/history/transaction 组合 178 passed / 1 expected skipped（43.00s）。完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1223 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，570.17s；新增 skip 仅是 Binance income 不提供 OKX isolated position cash 字段的 N/A fixture。所有 pytest 均明确 exit 后才编辑，没有并发长任务。
- compileall/diff 已通过；新解释器屏蔽 ccxt 的账户模块/SQLite schema/不建会话 dry-run smoke 验收。提交前核 staged diff，Lore 后在精确提交复验再快进推送；无新依赖、真实私有 I/O、用户配置/权限/规则或冻结研究变更。
- 文件范围：新增 Trade/AccountReconcile.py、Trade/AccountRiskStore.py、tests/test_account_reconciliation.py、tests/test_account_risk_freeze.py；接入 Trade/CCXTTradeEngine.py、Trade/db_util.py、Trade/SqliteDB.py、Trade/OrderAudit.py；更新 README_FULL.md 与本台账。复用既有 native normalization、scan manifest、history reader、canonical/schema/事务与 CAS；冻结由检查历史的失败 OR 计算，不维护第二份可变状态，也没有第二套订单引擎。
- 仍未完成：matched_observations 仅是给定来源区间的精确数学检查，economics_complete=false；admission_verified 恒为 false。缺检查/未冻结不是准入，强制鲜活来源与失败阻断必须继续接入 C6，不得用本 guard 绕过对账。实际 REST 跨响应漂移/mark 时钟/原生舍入、isolated/借贷/资金费分腿与全部资产通道、完整含费/资金费不利模拟、历史检查重验容量/锁时延和 C6/C7 均有真实缺口。C5 与 Goal 继续 active；候选/测试网/实盘及正式研究门禁不变，不宣称生产就绪或关闭 Goal。

### C5 第十一子边界实施与清理计划：显式 paper 账户进入原订单恢复路径

- 前轮是有效进展：19b81a172a32efbd8d27e72f5b13fd485bb72d59 已推送，1223 全离线与精确提交后 178 项通过；本轮起始 clean。继续主代理串行、TDD/fake、既有门禁，不修改默认配置/依赖/冻结研究，也不建立真实会话。
- 复用 C4 CCryptoAccount 的有限 Decimal、手续费、mark、exact-ms funding、费后保证金与 liquidation_required 口径；不另写一套经济公式。完整 paper 是显式选择的新适配，旧 spot/简化模拟保留兼容但不用于完整验收；paper 身份不伪装原生账户，也不生成 candidate。
- paper 交易所状态继续使用 CSimExchangeState/既有 orders、fill plan、COrderResult 和 DB intent→claim→report/恢复，不增加第二套订单生命周期。冻结显式市场单位/步长/tick、软件 cross/leverage/费用参数、账户身份和行情时钟。无 metadata/quote/mark/持久意图、数量不合法或费后保证金不足时拒绝，不从 symbol 或密钥猜模式。
- 当前 C4 是明确的 per-fill lot 账户，paper 同样保留 lot，不把它冒称交易所 pooled 原生账户；record 的部分退出按固定 FIFO 分配到其真实已成交 lots。原生 pooled 逐腿核对继续由上一边界独立负责。C6 比较实际相同 execution events，不拿模型不同的中间 PnL 硬称相等；原生 cash/PnL 模拟若未达到同一模型，必须保留未验收项。
- 新 quote 明确 bid/ask/mark/UTC；taker 走不利侧与显式滑点，limit 不得越限，resting/post-only 的触价模型明确非 queue/交易所撮合认证。按当前真实 quote 推进 partial fills，累计价/量单调；query/cancel/restart 不能重复扣费用或 funding；hedged 两腿不净额抹除。资金费只收时点之前的旧 lots，明确同刻处理与重复身份。
- 首先真实 RED→GREEN 验证共享账户核算/单位；随后接入引擎并以 SQLite 路径覆盖 lost ACK、partial/cancel/retry、双腿、费后拒绝、mark loss/liquidation_required 可降风险、幂等/restart 和时间/身份错误。适用旧交易/评估组合、核心无 ccxt、完整离线、compileall/diff/Lore 与快进推送后继续 C5/C6，不因模拟 PASS 关闭 Goal。

### C5 第十一子边界证据：显式含费 paper 账户与原订单恢复路径，C5 未完成

- 新增 Trade/LinearPaperAccount.py 与两个测试文件；接入 Trade/CCXTTradeEngine.py，OrderAudit 仅扩展 paper_account 身份白名单，更新 README_FULL.md 与本台账。默认简化模拟、Spot 与非 dry-run 路径不改配置；完整模型须显式 CSimExchangeState(paper_account=...)，只接受同一 venue 的 USDT linear swap、明确 contracts/base 步长、tick、费用、软件 cross/leverage 和 UTC quote。没有原生账户会话、candidate、真实私有 I/O 或研究运行。
- 复用未修改的 C4 CCryptoAccount 核算与原有 SQLite intent/CAS/ACK/restore 状态机，不维护第二套经济公式或订单生命周期。输入实际不利成交价后底层 slippage 固定为零，避免双扣；record 按真实 fill lots FIFO 退出，明确不是交易所 pooled basis。单次事件先在候选状态完整计算/校验，成功才原子替换内存账户，返回值不共享可变内部对象。
- 真实 RED 包括缺适配模块/引擎参数、原生 wire parser 与 Python float 的边界、重封契约的单位/腿/margin/未知字段、费后保证金、非法 bool/funding 数字/quote tick、低价退出与 dust reduce、累计 fill plan、跨 venue/重用账户身份、代码指纹重封、共享状态丢失和 DB 数量漂移。只修 paper 边界，不放宽 native reader；两处错误手算 fixture 按已有真实成交与事件数修正，不把夹具错误当生产 RED。各阶段均等 pytest 明确退出后再编辑。
- 当前 bid/ask 与显式滑点/tick 形成不利 taker 成交，limit 不越限；resting/post-only 只做明确的触价模型。每个 partial 使用当时 quote 与费后保证金，费用/funding 不重复；旧 lots 才拥有同刻 funding。hedged gross/margin 保留两腿，不用净量归零掩盖暴露。压力状态可按实际持仓减仓，不捏造零价/自动原生强平；软件 min_notional 不阻止合法步长的 dust reduction，不声称平台有同样豁免。
- 冻结账户、市场、C4 evaluator、paper 适配与撮合源码身份，fresh reader 重算代码指纹，单纯重封 manifest 不能冒称另一执行实现。累计订单平均价是现有 binary64 API 字段，原始逐笔/费用保留 Decimal50。new-risk 在创建意图前核对同账户 DB/历史、实际 lot 与待处理服务器单，丢失同名服务器状态或数量漂移时闭锁，不猜测恢复。已有持久意图与原 server 的 lost ACK/query/cancel/retry 仍由旧恢复流程处理。
- 最终短组合 356 passed（47.69s）取得于最后模块说明/type annotation/清理 unused test import 与文档修改前，不冒称该结果覆盖后续字节。随后完整串行离线命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1283 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，570.06s。完整运行期间未编辑源代码、测试或文档。
- compileall 与 git diff --check 通过。完整测试明确 exit=0 后，独立新解释器用 import finder 屏蔽 ccxt，实际临时 SQLite signal→intent→不利 fill→含费账本→重放 reader PASS；engine.exchange 为 None，ccxt 未导入，数据库随 TemporaryDirectory 回收。按串行约束由主代理自审，非独立审计。提交后须在精确提交复验短组合，通过才快进推送。
- 剩余边界不隐藏：目前仅单 executor、保留同一 CSimExchangeState 的引擎重建；不是进程级服务器状态持久恢复或多进程 matcher 认证。pending orders 保证金预留、队列/深度/延迟、原生 pooled/isolated/保险/强平规则与实际费率均未认证；费用/成交拒绝不等于真实成交保证。C5 尚有 native 精度/所有账户通道与准入边界，C6 鲜活强制准入/配置/端到端与 C7 仍未完成，Goal 保持 active，不升级实盘/外部认证或触碰冻结研究绩效。

### C5/C6 运行入口集成计划：失败传播先于新增风险

- 前轮有效进展已在 clean/远端一致的 0c61e9693fb0dcb42bdc746d31fedeb1b24831c6：1283 全离线及精确提交后 356 项通过。继续串行，不重跑未变更 C5 数学/订单公式，不改真实账户、配置默认值、依赖、规则或冻结研究。
- 按计划逐项核对 C5：合约单位/参数见 test_crypto_order_contract/test_crypto_venue_parameters；原生 ID/分页/失联 ACK/两进程 claim/撤单竞态见 test_crypto_order_recovery；区间钱包/逐腿核对与冻结见 test_account_reconciliation/test_account_risk_freeze；含费不利模拟见两个 linear_paper 测试。已有软件组件证据不补造外部认证，也不把 retained server state 视作进程级 E2E。后续运行入口鲜活准入未接通，整体 C5/C6 暂不关闭。
- 清理范围仅调度壳：用一个配置驱动 Python 运行入口取代两个 shell 重复的 BTC/ETH/周期清单和无退出码检查命令链。复用 CEnv、CDeployment、C1 inspect_quality、已有交易脚本及恢复状态机；不重新实现模型、行情更新或订单生命周期。显式配置/报告路径，无 demo 配置回退；沿用仓库相对路径规则，子进程继承相同 CHANPY_CONFIG 与既有环境门禁。
- 先 RED：缺运行入口、任一更新/质量/信号失败后不能开新仓但仍尝试原订单恢复/后验/降风险、管理阶段之间失败隔离、配置漂移、报告脱敏、运行锁以及两套 wrapper 的真实失败退出码。合成 SQLite 行情与 fake 子进程验证，不启动真实更新/下单。增加专用恢复 CLI 只调用旧 restore，未知保持未知，不重下。
- 每次运行有唯一 ID、阶段结果/退出原因、来源/水位和模型身份；增量 JSONL 记录并 flush/fsync，报告已存在即拒绝。按交易 SQLite 路径持单实例 OS 锁，不能换报告路径绕过；不把这一入口的锁冒称覆盖所有旧单脚本或跨主机。配置指纹漂移时不把新配置用于旧账户管理。
- 本子边界首先开放明确 dry-run 的软件调度；非 dry-run 新风险须在后续强制鲜活账户准入接通后再验收，目前显式阻断，不以不存在冻结当准入。原账户的查单/撤单/降风险仍保留既有 candidate/模式/环境/kill-switch 检查；不会为了管理成功而绕过这些门禁。C6 的模型/行情再验证、进程级 paper E2E、API schema 和双 Python 环境仍须完成。

### C5/C6 第一运行壳子边界证据（整体验收仍未完成）

- 先观察 RunTradeCycle 缺模块 RED；首组 13 项在真实配置/合成 SQLite 与 fake 子进程边界 GREEN。再观察四项行为 RED：成功 CLI 错误返回 1、SignalMonitor 明确报告计算失败却退出 0、PowerShell 吞掉原生命令失败、Bash 继续执行八条命令。分别在原入口修正；RestoreOrders 缺模块 RED 后只复用旧 engine.restore，区分已知 partial 与 unresolved，不添加订单重试/第二状态机。
- 后续明确 RED→GREEN：报告磁盘失败须保留已有仓位管理，开仓 stage_started 落盘失败不得继续发送；300 秒子进程超时须闭锁且不得将异常原文/凭据落日志；坏 YAML 的 ParserError 不得回显配置行；质量观察不得为错误 SQLite 文件创建 kline 表；报告路径不得占用尚不存在的交易库；PowerShell Set-Location 与进程 cwd 不同也必须解析到调用者路径。只在对应传输/文件边界注入故障，不 mock 数据质量、模型 reader 或订单核算。
- 新入口复用 CEnv/CDeployment 的 symbol/level/策略和模型版本，运行 ID、配置指纹、C1 的来源/质量/水位、阶段退出码逐步写 finite canonical JSONL 并 fsync。报告只描述命令完成，不是账户准入或发布证书；未落完成事件与报告 I/O 故障不得当成功。保留首个失败原因，独立尝试所有管理阶段；配置漂移则停用后续所有动作，不将新配置用于旧账户。默认 transport 不持久化任意 stdout/stderr，固定 300 秒超时不是研究参数。
- 新增只读 CKLineDB 选项，使用 SQLite mode=ro/query_only 且不初始化 schema，默认写入行为不变。两套 update_data_signal 壳只剩显式参数、路径解析与一个 checked Python 命令；训练壳继续沿用原入口。单实例锁按实际交易 SQLite 路径：同进程重入及另一个真实 Python 进程换报告路径均拒绝；完成后 OS 句柄释放，后续运行可正常取得，不依赖 lock 文件的存在。POSIX fcntl 路径尚未在本 Windows 主机执行，不冒称 Linux 认证。
- 适用数据/交易/训练组合 126 passed / 5 existing model warnings（138.55s）；后续新增实际 C3 部署范围/模型损坏和恢复 CLI 正例后，运行壳/恢复/部署组合 69 passed / 3 existing model warnings（36.05s）。实际模型只从小合成夹具生成，复制到独立临时目录后变异，未修改共享或历史模型。两套 wrapper 使用假的 python；未执行真实更新/快照/私有请求。
- compileall、git diff --check、bash -n 通过。两个独立解释器 CPython 3.14.2 与 3.11.15 在主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 时，运行壳/恢复模块导入、实际临时 SQLite 只读质量及无会话 dry-run 空恢复 smoke PASS。py -3.11 的 launcher 别名不可用，按 py -0p 所列真实 3.11 路径验证；该解释器无 pytest/YAML/模型包，不能把 stdlib smoke 冒称完整依赖安装矩阵。
- 按串行约束由主代理使用 code-review 清单自审，非独立审计。新风险 native_fresh_admission_not_integrated 保持显式闭锁，native_admission_verified 恒 false；完整纸面交易进程级服务器状态、输入到订单的强制鲜活准入、API schema、通知失败观测/安装矩阵/真实外部认证仍待后续。当前锁不覆盖旧单独脚本、跨主机或硬链接别名。C5/C6 与 Goal 不关闭；完整离线与精确提交验收后才快进推送。
- 最终完整串行离线命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1317 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，575.49s。运行期间源码、测试与文档均未编辑；明确 exit=0 后仅补本记录与目录前提说明，提交前无其他行为变更。新旧 C5 的状态机/安全/单位/原生来源/核对/含费 paper 回归均包含在内，不将命令完成或 mock PASS 提升为外部认证。
- 文件范围：新增 Trade/Script/RunTradeCycle.py、Trade/Script/RestoreOrders.py、tests/test_trade_cycle.py、tests/test_restore_orders_cli.py；接入 OfflineData/offline_data_util.py 的显式只读选项、SignalMonitor CLI 退出码与两套 update_data_signal 壳；补 tests/test_deployment_workflow.py，更新 README_FULL.md/本台账。无新依赖、用户配置/规则/权限变更、真实行情/私有 I/O、正式研究或绩效读取。Lore 后在精确提交复验适用短组合，再快进推送并核验远端/clean。

### C6 第二运行边界实施/清理计划：输入时代绑定到每次真实新增风险

- 前轮已推送且本轮起始 clean/HEAD=4a2e1abf0ea2cfb438f52d68ae1859a6b94e141d；1317 全离线、精确提交后 138 项通过，是有效进展。本轮不重新实现 C4 账户、C5 订单状态机，不改用户配置/依赖/规则/冻结研究，继续主代理串行与 RED→GREEN。
- 已确认剩余孔洞：RunTradeCycle 只在 SignalMonitor 前观察质量；信号计算期间行情变旧、出现缺口/修订或模型变化后，旧观察仍可进入 MakeOpenTrade。仅子进程成功不能证明输入仍有效。先用真实合成 SQLite 与可变时钟/传输边界变异观察 RED，不能用 mock ready/passed 代替实际 reader。
- 清理限于把现有 scope/只读质量逻辑提取为一个共享 OpeningInputs 模块，供运行壳与开仓 CLI/引擎调用，避免两份不同门槛。一次只读 SQLite 事务核对全部配置周期，并对实际 closed rows（含 volume）形成固定输入时代摘要；配置/模型/scope 同样重读。只记录观察到的状态，不冒称跨市场库、交易库与网络发送之间存在全局原子锁。
- 父周期在信号前冻结配置/scope/输入时代，在信号后、开仓前重新验证；子进程携带同一摘要而非任意 passed 布尔值。每笔开仓在准备、意图前及发送边界重新验证，检查真实 DB/engine 来源、配置池/交易级别、C2 信号字节/已收盘原始 bar 与 C3 模型身份。输入失败停止新增风险，不重置/重下已取得意图；已有订单 query/cancel/reduce 路径不应用该新增风险门槛。
- 新增仅是行情/模型/信号输入检查，绝不是原生账户鲜活准入。运行壳与默认开仓 CLI 的非 dry-run 新风险继续闭锁；保留 candidate/环境/kill-switch 与原账户身份检查。ticker 本身的年龄证明、原生完整账户通道、进程级 paper E2E、API/安装矩阵仍为后续要求，不用本子边界替换整体验收。
- 保留旧直接库调用与股票扩展默认行为；配置驱动 CLI 绑定显式检查。原订单 journal 可按新增可选 identity 字段冻结输入检查摘要，旧无该字段的历史字节原样读取，不能补造过去的输入证明。补字段篡改/来源错配/失效后管理仍可用与 full paper 实际函数接通测试，再做适用组合/全离线/compileall/diff/Lore/精确提交/快进推送。

### C6 第二运行边界证据：逐笔开仓输入版本（整体 C6 未完成）

- 首先四项真实 RED 证明 signal 子进程返回 0 后，缺 K、来源漂移、时钟过期、仅 volume 修订仍会开仓。随后 OpeningInputs 缺模块 RED→GREEN；共享 CEnv/C1 只读事务/C3 reader/原 C2 decision，而不是两份 ready 布尔值。scope 增加实际 trade_lv 和 evaluator 身份，复用 feature_code_identity 绑定真实策略/特征与输入/订单工作流及 Python。数据水位一样但内容不同仍变摘要，public env/scope/snapshot 返回独立副本。
- 低层引擎新增参数缺失 RED 后，检查接入原 add_trade 准备前、意图前、频控后和 CCXT/paper/配置模拟的发送边界。SQLite 原 CAS/journal 冻结 opening_inputs 检查；旧无此字段的历史不补写/升级。实际 RED 覆盖意图前/后及 claim 后失效、另一 engine 来源、移除/改写 stamp、新检查器重标旧意图、低层 qty/direction/price/leg 与原意图不符。无新订单状态机，未知原样留 created/submitting，由旧 restore/query/cancel/reduce 管理，不自动重下。
- 实际 MakeOpenTrade 缺 failures/main RED 后，配置 CLI 需要原运行元数据、明确 dry-run 和配置 notional；不再从无上下文命令调用开仓。每笔源输入失败和缺失/bool/NaN/Infinity/负价格产生脱敏失败，CLI 非零，既有直接库调用/股票默认行为保留。完整 paper 使用显式原 UTC/bid/ask/mark，实际函数成功形成含费 fill；不把 last quote 当 mark。原真实账户门禁未弱化，非 dry-run 新风险仍 closed，native_admission_verified 恒 false。
- SignalMonitor 同 SQL 目标但完整 frozen bytes 不同曾被当 existed，独立 RED 后改为显式失败/保留旧记录，不放宽比较。初次回归夹具用了 1970 UTC，触发 CChan 1980 起始时钟，先将该测试唯一 bar 改用已有 2024 fixture，再观察真实失败，不改生产时钟。完全相同重复仍幂等；不同模型观察时刻等造成的新候选内容需要后续显式换代/失效工作流，不隐藏为已验收。只读检查与发送之间的跨库/网络竞态、全历史重验容量、ticker 年龄与原生账户准入仍待。
- 句柄 4966 后来明确 missing，额外检查无存活 Python 后才重跑，不把缺失输出算通过。取得的实际组合为 209 passed（40.67s）；补原请求/旧意图重标后组合 152 passed（21.10s）；补策略代码身份后 observer+cycle 73 passed（14.96s）。最终实际小模型部署/损坏后不发送正反例 2 passed（8.41s）；随后 opening/cycle/deployment/history/safety/units/native recovery/freeze/paper 组合 369 passed / 3 existing model warnings（84.96s）。所有 pytest 均明确退出后才编辑，无并行长任务。
- 使用 code-review 清单由主代理串行自审，非独立审计；优先复用已有 canonical/source/model/history/CAS，删除 RunTradeCycle 中重复的 scope/quality 分支。无新依赖、真实 I/O、用户配置/权限/规则或冻结研究/绩效变更；完整离线/compileall/diff、可选依赖隔离与精确提交后复验通过才快进推送。C5/C6/C7 与 Goal 均未关闭。
- compileall/diff 通过。独立 CPython 3.14.2/3.11.15 在主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 时，新增模块与代码身份读取、缺运行元数据时 CLI 明确拒绝、实际只读 SQLite/无会话恢复 smoke 均 PASS；这不是缺少 YAML/模型包的 3.11 完整配置/依赖安装认证。调用未建立行情/私有会话，临时库按测试自身生命周期回收。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1363 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，568.50s。整个完整运行期间没有编辑源码、测试或文档，明确 exit=0 后才补本最终数字。此前 369 项组合对应同一行为代码，仅后续文档变更；不把旧结果重标为新运行。
- 文件范围：新增 Trade/Script/OpeningInputs.py 与 tests/test_opening_inputs.py；接入 Trade/TradeEngine.py、Trade/CCXTTradeEngine.py、Trade/OrderAudit.py、MakeOpenTrade/RunTradeCycle/SignalMonitor；补 cycle/实际 model deployment 集成测试与 README/本台账。无 schema 重写、第二订单引擎或新依赖。冻结数据/策略/外部资产不变；提交前核对 staged 范围，Lore 后精确提交再复验并快进推送。Goal 保持 active，后续按原 C0–C7 目标继续。

### C6 API 子边界实施与清理计划：明确快照与历史事件，兼容旧调用

- 上轮 ccf42e7e046e406d8f998136c8bb3d46d9054123 已推送，1363 全离线与精确提交后 146 项通过；本轮起始 clean，属于有效进展。继续按批准 C6 第 5 项，主代理串行、真实 RED→GREEN、原模式/研究门禁；不新增 Web 产品/依赖或修改段理论、配置默认值。
- CChan.toJson() 无参保留原 level→klu/bi/seg/zs/bsp/cbsp 形状；显式 schema_version=1 等价。对所有公开版本拒绝 NaN/Infinity/不可序列化值，不以字符串或 null 悄悄替代坏数字。新 schema_version=2 由单一 Common/ChanExport.py 适配器输出 chan-api-v2、完整 finite canonical payload 与 SHA，不移动或重写结构计算。
- v2 明确支持 klu/klc（含分型）/bi/seg/segseg/zs/segzs/bsp/segbsp/cbsp 当前结构视图，保留层级索引/起止引用、source、UTC 已收盘 clock、交易量/特征/退出动作等声明字段。结构的 is_sure 只是当前算法标志，不等于已记录的因果确认时刻；未记录时 available_at_ms=null 并明确 not_recorded，不能用端点时间补造发布时钟。
- 不可变 C2 decision_records 单独作为每级 decisions ledger，保留完整原 identity/payload/digest，不在导出时从可变 cbsp 重算过去。明确 available_at_ms=已记录 decision_ms 仅适用于完整 UTC bar clock；旧 CSV/股票未声明时钟/来源时保留未知，不猜 UTC/交易所。检查 event code/level/顺序/重复/退出父事件与边界，旧无发布能力的自定义策略不得伪装成完整空 ledger。
- 先测试缺新版本入口与旧非有限泄漏 RED，再最小实现、原 toJson/多级别/绘图回归；小合成 crypto 夹具逐字段对照真实结构，已返回对象和旧事件不被未来输入/外部修改改写。测试 unknown/partial/mixed source、坏 clock、空数据、非法版本/数字和完整 4h/1h/15m load/trigger 对齐。所有复杂化仅为契约/可重放验证，不复制策略/研究实现；完整离线、核心 optional 隔离、compileall/diff、自审/Lore/精确提交后才快进推送。
- API 是当前结构观察与原发布证据的适配器，不授予交易/账户准入，也不提供“历史某时刻当前结构”的伪 cutoff。C6 其余鲜活准入、信号换代、持久纸面 E2E/通知/安装与 C7 保留未完成，不因 API 子项通过关闭 Goal。

### C6 API 子边界离线证据（仅本子项，不是完整 C6）

- 先缺显式版本与旧 NaN/Infinity 泄漏 RED，再实现独立 Common/ChanExport 适配器；v1 默认形状不改，v2 十一类数组覆盖当前 KLC/笔/段/段段/中枢/买卖点/CBSP 与完整原 C2 ledger。未记录的结构确认时间始终 not_recorded/null；仅真实完整 UTC 原事件披露已记录发布时刻，不发明 endpoint→confirmation 或 cutoff 语义。
- 原事件源/边界/父链与 cbsp 发布链接的五项真实 RED→GREEN；随后四项真实 RED 证实跨 venue 快照 ID 碰撞、残缺 UTC signal 被降级为 legacy、悬空父引用和 bool raw index。补来源上下文摘要、完整时钟要求、实际对象归属和双向父子检查。后续真实 RED 覆盖跨级来源混用、整个当前市场重标却保留原事件、KLC 错误归属/bool index 与仍自洽但不对齐 UTC 的时钟；复用已有 C1 时间/来源与 C2 canonical/reader，不复制算法。
- 三级 full load/逐 15m feed 最初差异是测试把同一配置字典传入会消费它的 CChanConfig，第二路丢失策略/参数；改为独立配置副本后完整 payload 逐字节相等，未删字段或修改算法。两处非法 fixture 先修正（未对齐的 foreign 4h 时间、只读 klc property 改用已有 setter）再观察生产失败，不把测试错误当修复证据。先前一次输出丢失，检查无存活 Python 后重新取得明确 5 failed；不把丢失输出算通过。
- 当前已明确终止的实际组合：39 API + 原 decision/causal/M1/三级策略，115 passed（93.59s）。覆盖真实带特征 multi_lv、全原事件逐字节、未来输入不改旧发布、返回值隔离、有限数值与 unknown/partial source、legacy clock/empty levels。主代理沿 code-review 清单串行自审，非独立审计；README 给出字段/时钟/迁移与非全局快照 ID 契约。
- 文件范围限 Chan.py、新 Common/ChanExport.py、新 tests/test_chan_api_contract.py、README_FULL.md 与本台账；不改段算法、配置、规则、依赖、冻结资产或交易状态机。Chan/Common 参与已有模型指纹，旧模型须重生成并重新部署，不能重封旧契约。C5/C6/C7 与 Goal 保持未完成。
- compileall 与 git diff --check 通过。独立 CPython 3.14.2/3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 后，实际已收盘合成行情的 v1/v2 导出、完整 SHA 与非有限拒绝均 PASS；不读取配置或网络。这是核心 optional-free smoke，不是 3.11 完整依赖安装认证。当前结构对象须由调用者串行使用；没有跨线程原子快照、全历史输出容量或历史首次结构确认时钟认证。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1402 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，571.61s。运行期间源码、测试、文档均未编辑；明确 exit=0 后仅补本最终数字与状态，不冒称旧输出丢失时的结果。按 Lore 提交后，精确提交短组合须通过才快进推送并核验远端与 clean；不将 mock/离线通过提高为交易所外部认证。
