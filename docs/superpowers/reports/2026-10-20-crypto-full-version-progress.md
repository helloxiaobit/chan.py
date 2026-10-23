# 虚拟货币完整版开发验收台账

用户在 2026-10-20 批准按 [C0–C7 计划](../plans/2026-10-20-crypto-full-version-completion.md) 开发并向 `helloxiaobit/chan.py full-version` 提交、推送。按阶段串行验证；Goal 仅在全部要求有结果后关闭。

## 交付身份与归属

- 开始时远端：`895fc700705e48013019a4054645e016a6e08d0e`。
- 开始时本地：`22a5a56ed1b38c2145106230c70256d4b7bc7bb5`，领先远端 44 提交。远端为本地祖先，可快进，不重写历史。
- 通用安全实现：`b04d2a6` 至 `5a0d25a` 的模式门禁、持久化意图、累计成交、恢复与离线安全验收继续复用，随后文档/验收提交保留。
- 已在本分支的研究模块及拒绝证据随既有历史保留，不重新执行、不修改冻结资产；其他研究 worktree 不合并。
- 配置迁移：默认仍为 dry-run，股票与旧库配置读取保持兼容；新 C6 配置开仓需本文列出的显式 CCXT 报价/年龄策略。C1 行情身份迁移需显式声明旧库来源；C5 订单数据库升级需保留旧表及恢复语义。

## 支持矩阵（初始状态，不等于验收通过）

| 能力/范围 | 实现入口 | 现有证据 | 待验收/范围 |
|---|---|---|---|
| 已收盘 15m/1h/4h、多级别结构 | `DataAPI/ccxt.py`、`OfflineDataAPI.py`、`Chan.py` | `test_m5_data`、`test_multilv`、`test_consistency` | C1 时间/finality/来源；C2 因果发布 |
| Binance USDT 线性永续 | CCXT 行情与 `Trade/CCXTTradeEngine.py` | fake exchange 安全/状态机测试 | 第一交付目标；合约单位/真实环境未认证 |
| OKX USDT 线性永续 | 同上 | 原参数/恢复 fake 证据与独立来源/真实模型/默认 CLI 软件 paper E2E | 第二目标；one-way 单 instrument 合成场景，非原生测试环境认证 |
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
| C5 | 进行中 | 单位/原生恢复/历史/来源、区间核对与持久冻结已离线验收；cross/lot paper 已接原状态机与显式持久恢复；鲜活准入链、原生同义模型及外部认证仍待 |
| C6 | 进行中（仍未完成） | 配置运行壳/失败传播/OS 锁、输入/报价、API、显式软件 paper 进程级路径、通知摘要/脱敏与 Windows 3.11/3.14 核心/完整安装已验；原生账户/mark/book 证明、信号显式换代、更广 E2E、迁移和外部通知送达仍待 |
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

### C6 开仓报价实施/清理计划：原来源和时钟保留到实际发送边界

- 前轮 48e6df0506946914284f1a18286c6834241c09f4 已推送，精确提交 97 项复验通过；本轮起始 clean，属于有效进展。按批准计划 C6 输入失效阻断继续，不修改用户配置、依赖、规则或冻结研究。AccountReconcile/AccountRiskStore 的 matched_observations 只有区间观察，mark 生成时间仍未知，不能把无冻结或一次相等变成原生账户准入。
- 实际缺口：CCCXTSnapshot 的普通 dict 丢失 ticker 时间/来源，MakeOpenTrade 进一步压为裸价格；此前只能拒绝 NaN/非法价格，不能证明报价新鲜或同市场。本轮先补实际开仓路径这个依赖，不把组件通过当整个鲜活账户准入完成。
- 复用 exchange_source_identity、UTC/finite canonical、COpeningInputs 和原 CAS/journal；保留旧 query/裸 price_map 的兼容库路径。新增严格 quote batch 只记录实际 ticker symbol/last/timestamp 与请求起止时间、实际 exchange/options 来源，不保留 raw info/凭据或把接收时间补成交易所时间。ticker 时间不冒称 bid/ask、mark 生成时钟或服务器签名。
- 配置运行开仓须显式提供正整数 trade.quote_max_age_ms，不发明固定秒数，不修改默认配置文件。实际 configured CLI 只接 CCXT 同源完整报价，先冻结一次，再在意图前、频控后、claim 后/真实发送前重验年龄/来源/原价格；过期只阻断新增风险，原单 query/cancel/reduce 不依赖新报价。
- 新输入证明显式 v2 携带原 quote batch 与年龄策略，v1 历史原样保留；实际 journal reader 重验 finite/摘要/来源/信号/原价/时钟，不能将新报价重标到旧意图。不重新实现订单状态机或替换原 native_account 门禁。
- 先 RED 缺严格 producer/reader，再小 fake exchange 的真实来源/时钟、失效/重封/错误脱敏、部分/缺失批次；接真实 SQLite 意图/发送边界和完整 paper/实际小模型函数。现有低层兼容检查保留，完整离线/compileall/diff/双 Python 核心 smoke/Lore/精确提交复验通过才推送。原生完整账户/未知外部订单、信号换代、进程级 paper E2E、通知/安装矩阵与 C7 仍为后续，Goal 不关闭。

### C6 开仓报价离线证据（仅该输入子项，不是原生账户准入）

- 严格 producer/reader 缺失的 23 RED→GREEN；原数据/快照组合 81 passed/1 network deselected，但一次未指定 basetemp 的调用尾部出现既有 pytest-current 清理 PermissionError，不删除共享 Temp 路径、不算 pristine。后续每次独立 basetemp，真实 guard/意图/旧恢复组合 71 passed，无该清理问题。
- 默认 CLI 的 7 项实际 RED：原入口会读取裸价、接受缺失/非法 age policy 和 sina。改为有本轮候选时必须显式 ccxt/quote_max_age_ms，保留无候选不查询；读取/绑定一份原批次，COpeningInputs 与 journal 显式 v2，旧 v1 原样可读。旧 notional CLI 测试缺新策略而失败，补临时配置与实际 fake ticker transport，未放宽正整数/来源要求；112 项运行/开仓组合通过。
- 后续真实 RED→GREEN：调用方放大固定年龄上限、最后一次检查扫描期间报价已过期却仍发送、paper 检查结束后先 claim 再拒绝，以及损坏 version 导致原始 TypeError。按实际请求链补结束时钟重验、paper pre-claim、类型检查；raw ticker 时间从未以本地接收时间代替。另两项 RED 证明 journal 投影的 lv/bstype 可脱离原 signal，v2 reader 现在与原 C2 信号匹配。
- 当前 52 项新报价用例含原来源/年龄/hash/重封、写一次/不重标、真实 SQLite 在 before-intent/after-intent/after-claim 的失败边界、过期后 query/cancel/reduce、完整 paper 含费成功及零成交失败。Binance/OKX 实际 CCXT 原生参数构造器＋fake private I/O 的 4 项新检查通过；临时 fake candidate 仅为软件门禁夹具，非正式候选或真实测试网证明，native_admission_verified 始终 false。
- 将真实小模型的成功与意图后损坏两条集成路径接入报价 v2，不 mock reader/评分/订单账本。最终关键组合 actual opening/CLI/cycle/deployment/history/units/native parameters/recovery/sticky freeze/paper：407 passed / 3 existing model warnings，94.19s。复用已有 source/UTC/canonical/C2/C3/CAS/journal，只加一次 quote adapter/reader，没有第二套订单状态机；删除未使用的新 property，保持差异可审阅。
- 按 code-review 清单主代理串行自审，非独立审计。检查和网络发送仍无全局原子性；ticker 时间不是盘口/mark 生成时钟，REST/account 完整通道、native 舍入/isolated、信号显式换代、进程级纸面恢复、容量/安装/通知与 C7 仍未验收。未连接真实行情/账户，未触碰冻结研究、用户配置/规则/权限或新增依赖。
- compileall/diff 通过。CPython 3.14.2/3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 后，实际 strict quote producer/reader（仅 fake 公开 transport）、过期拒绝、缺配置闭锁与交易/输入模块核心导入均 PASS；不是完整依赖安装矩阵认证。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1454 passed / 8 expected skipped / 1 network deselected / 14 existing model warnings，577.16s。整个运行没有源码/测试/文档编辑，明确 exit=0 后只补本数字与阶段状态，不冒称既有清理提示那次 pristine 或将离线结果升格为外部认证。Lore 后精确提交短组合须通过才快进推送，并核验远端/clean；Goal 保持 active。
- 文件范围：新增 Common/MarketQuote.py、tests/test_opening_quotes.py；接入 DataAPI/SnapshotAPI/CCXTSnapshot.py、Trade/Script/OpeningInputs.py、MakeOpenTrade.py、Trade/TradeEngine.py、CCXTTradeEngine.py、OrderAudit.py；补 tests/test_opening_inputs.py、test_deployment_workflow.py 与 README_FULL.md/本台账。旧 quote/price_map 库调用、v1 历史和原管理路径保留；默认配置文件不变，配置 CLI 的新风险现在需要用户显式声明报价年龄策略。新的 Common/输入工作流指纹要求重生成模型/部署，不修改旧清单来迁就。

### C6 进程级 paper 演练实施/清理计划

- 前轮已推送 d318137cc48a5b4bcfd2ac6c5a4bc6e4b14cebaa，1454 全离线、精确提交后 127 项通过；本轮起始 clean 且无 Python 测试进程，属于有效进展。继续批准 C6 第 6 项，完整离线演练不是 native 账户准入或外部认证。
- 现有 paper 仅保留同一 CSimExchangeState 句柄，进程退出即丢服务器订单与账户，不满足重启验收。本轮先让实际 server 状态可恢复，再接真实数据/策略/模型演练；不复制撮合、C4 财务或交易 DB 状态机。
- 清理范围：把 verify_linear_paper_report 的原重放体提为实际账户 restorer，原 verify 仍返回相同报告；把 paper 查询的累计 fill 核验提为可复用纯检查，供原查询和持久化 reader 共用。既有完整 paper/手算/重复收费测试保留，先观察新 restorer/持久接口缺失 RED，再最小实现。
- 新持久化只接显式软件 paper，有限 canonical JSON/checksum、原 account effects 与订单/remaining plan；不使用 pickle。原状态通过重放/单位/原始 fills 校验后恢复，绑定实际 SQLite 数据库/服务器身份和代码；v2 paper 意图指明原 store，旧内存 v1 不自动升级。
- 单个 server 文件持 OS 生命周期锁，进程退出释放；已有文件拒绝重新创建，open 缺失/坏文件/错代码/错 DB 拒绝，不猜测或默认新建。更新用临时兄弟文件 flush/fsync 后原子替换，替换前验证旧字节；服务器接受/部分成交/撤单状态必须在本地 ACK 前保存，未落盘的变异不得继续被当作服务器事实。
- 只有显式 store 才接持久化，旧内存/股票行为保留。新增风险继续输入/模式/kill-switch/native 门禁；恢复只是查询/记账，不重发。真实子进程在意图前后、服务器接受未 ACK、部分成交、撤单未确认处退出，再由新进程读取原文件与 DB；核对逐事件/费用/funding/持仓，不只最终余额。不把单写入器/同机文件原子性当作多进程撮合、网络或物理掉电认证。
- 不修改用户配置/依赖/规则、冻结资产或执行真实行情/账户 I/O。适用组合/完整离线、core optional-free、compileall/diff、主代理自审、Lore/精确提交/快进远端核验后才进入下一边界；C6 数据→模型完整演练和 C5/C7 其余项未满足前 Goal 不关闭。

#### 离线入口的固定实施范围

- 在新的显式输出目录生成 1000 根固定 seed 的合成小时 K，仅前 600 根形成真实策略样本并训练 2 轮小 XGB；阈值为演示常量，不搜索/挑收益。后 400 根只向前寻找首个实际候选，并逐字节对照前缀 reader 与在线喂入的完整评分证据。
- 复用 CDeployment/COpeningInputs 报价 v2、原 SQLite 意图/CAS、同一经济 paper 与新持久化 reader。三个串行子进程分别部分入场、恢复后资金费及部分退出、再次恢复完全退出；每个阶段保存原 effects/history，最终以原 restorer 对逐事件 canonical 账本核验，不只比较终值。
- 入口不接受真实 symbol、配置、密钥、模式或历史绩效参数，不导入测试 helpers，不调用 CCXT transport。所有配置仅写新演示目录；已有目录拒绝覆盖，失败不发布完成报告。完整 crash 注入由实际子进程回归覆盖，正常演示不声称突然断电、多写入器或交易所认证。

#### 本边界离线证据

- 最初 missing restorer/store/演练模块 RED 后实现；原核算重放体只提取返回实际账户，原 reader 字节不改，原 paper 累计 fill 检查由 reader 与 codec 共享。首次 codec 不能 introspect opaque count（CPython 3.14 TypeError），改为仅显式持久 server 的透明整数 sequence，不使用 pickle 或改旧内存 iterator。
- 真实 os._exit 子进程覆盖意图前/意图后/服务器接受未 ACK/partial/撤单未本地确认；原状态重新打开，无重复订单/费用，未知意图不自动重下。保存失败在 replace 前后分别注入；replace 后抛错曾被清理不存在临时文件掩盖，独立 RED 后修正，重开采用磁盘真实旧/新状态，不猜测。
- 3 个独立 RED 证实游标可回退、账户可有无 server 归属的合法金融 fill、旧空快照可绕过已平仓 DB ACK。现在每 fill 要归属原订单/游标，bind 复用 AccountRiskStore 的跨表 OrderAudit reader，在同一 SQLite 事务核对全部实际 ACK/terminal 历史；server 领先本地丢 ACK 可恢复，落后已知事实拒绝，两个文件同时回滚仍无外部锚点。
- 31 项持久测试包含重封现金/数量/均价/计划/角色/重复/计数/store/未知字段/孤儿成交、错 DB/路径/运行时/活字节/活内存/缺文件与真实第二进程锁。自审发现 close 能在活动操作中释放 writer，先观察 RED，再共用同一 mutex 拒绝提前关闭。生命周期锁不是跨主机或敌对文件系统认证。
- 固定合成演练缺模块 RED→真实模型/数据/三个进程 GREEN；DB 数量依次 0.01/0.02/0，1/2/2 个订单，完整 effects 前缀相同，C4 逐事件复算相同，funding 仅记一次。坏模型实际子进程拒绝且零 attempt；配置重封加入未知字段曾被接受，独立 RED 后要求完整固定配置形状，禁止以 SHA 自证。已有目录及 CLI 非零失败不覆盖文件，不发布完成报告。
- 最后适用 paper/opening/quote/cycle/deployment/history/contract/recovery/CAS/safety/transaction 组合 479 passed / 6 小样本模型 warnings（139.75s）；其中 3 条新 warning 是固定演示验证段单类 AUC 不可用，未隐藏、不宣称经济有效。按审查清单主代理自审（受串行规则，不是独立审计）；没有第二套撮合/财务/意图状态机。
- CPython 3.14.2 与实际 3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 后，真实 SQLite/显式 paper partial fill→关闭句柄→原检查点恢复 full fill→退出→逐事件核对均 PASS；演练模块核心导入也通过。完整模型演练需要现有完整依赖，本结果不是 3.11 完整依赖安装矩阵认证。
- 文件范围：新增 Trade/PaperState.py、Trade/Script/PaperRehearsal.py、tests/test_persistent_paper_state.py、tests/test_paper_rehearsal.py；接 Trade/CCXTTradeEngine.py、LinearPaperAccount.py、OrderAudit.py、Script/OpeningInputs.py；更新 README_FULL.md 与本台账。不修改用户配置/规则/权限/依赖或冻结研究资产，无真实行情/账户 I/O。默认壳接入、鲜活 native/mark/book 准入、信号换代/通知、更广 E2E/安装矩阵及 C7 未完成，Goal active。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1490 passed / 8 expected skipped / 1 network deselected / 17 model warnings，629.12s。其中 14 条为既有模型/LibSVM 告警，3 条来自新固定演示的单类 AUC；没有隐藏警告或把合成模型当经济有效。运行期间无源码、测试或文档编辑，收到明确 exit=0 后才补本数字。
- compileall/diff 与双运行时核心检查通过；Lore 前核实际 staged diff。精确提交后须复验持久化、原 paper 引擎和演练，再快进推送并核远端 SHA/clean；本轮不关闭 C5/C6/C7 或整个 Goal。

### C6 默认脚本持久 paper 接入实施/清理计划

- 上轮 b7ed92579702b39cb38028d01fec94eaf696a74c 已推送且 clean，1490 完整离线、精确提交后 71 项为有效进展；当前无遗留 Python 进程。继续执行批准的完整目标，不把独立演练替代默认工作流验收。
- 已查明 RestoreOrders/ClosePreErrorOpen/RealTimeTracker/RetradeCoverOrder 每次新建内存引擎，且 tracker 对完整 paper 调 set_sim_price。集中到一个 context-managed 配置工厂，显式 paper profile 只 open 原服务器，绝不自动 create/fallback；原程序库和未声明 profile 的兼容路径保留。
- profile 明确原 server、软件行情文件及正整数年龄策略；不发明生产阈值、不改用户配置。有限 canonical 软件报价声明 synthetic_only，给出全部账户 market 的独立 bid/ask/mark/last 与 UTC，校验 source/单位/tick/时钟/摘要；不能当作交易所原生数据认证或从 ticker last 补造 mark。
- 每次脚本冻结一个原行情批次，后续 use 边界重验文件、原 account quote 与年龄；失效拒绝新开仓/新模拟 fill/新退出成交，原已知累计回报仍可查询、原单仍可撤。读不到报价不得回到无成本/裸价模拟。报价和模型的缺失不能导致已有订单被新建或转移。
- 开仓与四个管理/恢复入口共用工厂并显式关闭 store/DB；纸面 tracker 使用经过 reader 验证的 last 作触发，真实执行仍只按独立 bid/ask。检查失败或 unresolved 必须给非零、脱敏原因；原 native 门禁不变，非 dry-run 新风险仍锁定。
- 先 missing-reader/factory RED，再真实 SQLite/部分成交、年龄/改文件/跨账户拒绝、缺行情查询/撤单、实际脚本 main/新子进程接同一 server RED→GREEN；再以真实模型+配置运行壳验证默认流程（仅公共更新传输 fake）。不重写 CAS、C4 核算、已有信号/模型发布，不新增依赖或研究变更。完整适用组合/离线/双 Python 核心/compileall/diff/主代理自审/Lore/精确提交/快进核验后交付；C5/C6/C7 剩余项仍须继续。
- 实际重复整轮 RED 发现原 SQL 去重只查 watching，开仓后相同冻结信号可再次插入并下单。修复沿用原 code/level/方向/target K 键，冻结 C2 信号在同一 SQLite 事务全生命周期去重；Monitor 对已有记录仍逐字节比较完整冻结证据，不忽略时钟/评分或覆盖旧行。旧无冻结信号的 unwatch 后重新入库行为保留；不同新观察或部署的显式换代仍另行验收。
- 显式 paper 风控参数使用运行配置内联 open_para，不读取仓库私有 OpenConfig.yaml；旧未声明 profile 的文件配置路径保留。软件报价使用独立 schema/explicit_software_clock/synthetic_only，不沿用 exchange_ticker_timestamp；非 paper guard 与非 paper DB 意图均拒绝该来源。

#### 本边界实现与离线证据

- 先缺工厂/reader RED，再软件输入 canonical/source/all-markets/tick/有限值/单批次/开始结束时钟 GREEN。过期/改文件/缺失仍会推进 fill 的 3 RED、venue 不符 RED、意图后/实际 fill 前过期 RED、调用方放宽策略 RED 均修复；已知查询/撤单保留，新成交与新风险拒绝。依旧没有文件/SQLite/检查后动作的全局原子性证明。
- actual subprocess 的恢复/错误修复/跟踪/重试 main 缺失或原内存状态失败 RED→GREEN；统一工厂只 open 原 store，关闭资源且按 unresolved/issue 非零。tracker 不再用 last 补造 paper mark；后验 main 同样使用内联参数、不读私有文件。现有旧库/未声明 profile 配置兼容，未升级为完整 paper 证明。
- 软件时钟误标为 exchange ticker 的 RED 后新增独立输入 schema；非 paper guard 和非 paper DB 意图两个语义 RED→GREEN。v3 paper 合约固定原软件年龄上限，codec/history 验证字段；drop reader 或恢复时放宽当前年龄的两个真实默认流程 RED、库调用的同类 RED 均修复，旧 v1/v2 不变。
- 真实小模型＋配置壳的首次开仓及相同输入重跑通过；第一次重跑曾重复创建第二个订单，RED 后复用原机会键/SQLite BEGIN IMMEDIATE 全生命周期去重，仍严格保留原完整字节。旧无冻结信号回归保持，观察时钟/部署变化未忽略，也未冒称完成显式换代。
- 真实默认整轮在模型损坏后停止新开仓，管理链仍减少原仓位至零；只有公共 OHLCV 更新传输 fake，脚本、模型/策略/输入 reader、SQLite 与进程实际执行。另一个 RED 修复了错误开仓修复器跳过已确认 canceled 的部分平仓余量；未确认/提交中请求仍只交恢复，不重下。
- 最后修改后 kernel/来源/安全/事务组合 87 passed；此前默认流程/部署/历史/恢复组合 330 passed / 4 合成模型 warnings（190.25s），后补后验 main 和临近 fill 重验，不把早期结果冒称最终树。仅主代理依审查清单串行自审，非独立审计。
- 新增 Trade/PaperInputs.py、Trade/Script/TradeRuntime.py 与 tests/test_configured_paper_{runtime,workflow}.py；接 Common/MarketQuote.py、Trade/{CCXTTradeEngine,OrderAudit,PaperState,db_util}.py、开仓/恢复/后验/修复/跟踪/重试/SignalMonitor、OpenConfig/OpeningInputs/Deployment 和对应回归；README/本台账记录协议。无依赖、用户配置/权限/规则、冻结研究或真实 I/O 变更。Common/工作流指纹变化须重生成模型/部署；旧 paper 代码身份不允许重封，跨版本迁移仍待验收。C5/C6/C7 与 Goal 未完成。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1529 passed / 8 expected skipped / 1 network deselected / 18 model/LibSVM warnings，741.18s，明确 exit=0。其中新增默认流程小模型的单类 AUC 告警未隐藏；不将软件功能测试当作经济有效。全程没有源码、测试或文档编辑，收到退出结果后仅补本证据。
- CPython 3.14.2 与实际 3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 后，实际临时 SQLite/软件 reader/v3 paper 部分成交→原 server 重开→无 reader 不推进→有效 reader 恢复完整成交→退出→原 C4 账本复核均 PASS；TradeRuntime/OpenConfig 核心导入通过。不是完整依赖安装矩阵或交易所认证。compileall/diff 通过；原核算、CAS/恢复与已有报价工具继续复用，没有第二套撮合/财务公式。
- Lore 后精确提交须复验默认 reader/真实整轮/报价再快进推送，并核对远端完整 SHA 与 clean；外部认证、信号显式换代、通知、容量、更广 E2E、完整安装和迁移仍待，不关闭整体 Goal。

### C6 信号失效作用域修复实施/清理计划

- 前轮 af09793edb591db3c2433835580cfe7caa4e6d43 已推送且 clean；1529 全离线和精确提交后 120 项为有效进展。当前无存活测试进程，继续串行 TDD；已有模型/行情/订单门禁不变。
- 当前 SignalMonitor 的清理集合只有 target K 字符串，未包含方向和级别，并扫描该 code 全部 watching 行。先真实 SQLite＋合成已收盘 CChan fixture 证明：同目标反向候选不能保留旧方向；只扫描一个交易级别时不能使其他级别失效。按现有 SQL 机会键和本次实际 trade_lv 约束修复，不改冻结决策字节、模型阈值、旧订单/段算法或添加生命周期表。
- 复用现有发布/原去重/失效写入，先观察行为 RED，再最小 GREEN；适用信号/输入/默认工作流回归、编译/差异、串行自审和 Lore 后精确提交核验才推送。用户尚未确认的候选换代/重臂方案不依此自动实现；保留全生命周期去重，不让已消费机会重新交易。外部认证与整体 Goal 仍未完成。
- 前三项 RED→GREEN 后组合 98 passed。新增真实 SQLite 的第四项 RED 证明：同 code 第二候选原字节冲突时，第一候选已提交并计 added。后续清理仅提取既有信号写入/相同字节复用/失效循环，使整个 code 批次共用原 SQLite transaction；成功提交后才合并统计，异常回滚且保留旧观察。复用现有嵌套 savepoint，不增加表、恢复协议或第二套 CAS；MySQL 保留兼容但不宣称同级原子验收。
- 四项行为 RED 均已 GREEN；最新信号/不可变发布/输入组合 71 passed（9.23s）。扩大真实默认流程/管理 CLI/三模型部署/运行壳/多级别/订单历史/事务组合 250 passed / 4 已有小样本模型 warnings（240.34s），明确 exit=0，期间无代码/测试/文档编辑。一次误用不存在的 test_order_history.py 导致 0 tests，随后按 rg 找到 test_order_audit_history.py 再运行；该命令错误不是验收结果。
- CPython 3.14.2/3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml 后，真实临时 SQLite 与实际信号 writer 的方向失效、未扫描级别不变、整批回滚均 PASS，核心导入通过；不是完整安装矩阵。compileall/diff 通过；主代理按审查清单串行自审，不称独立审计。没有 schema/用户配置/权限/依赖/冻结研究或真实 I/O 变更。
- 文件范围仅 Trade/Script/SignalMonitor.py、tests/test_signal_lifecycle.py、README_FULL.md 和本台账。提取原写入循环是为统一事务和提交后统计，未引入新模型/账户/订单状态机。原生撮合、C4 核算等未变代码沿用 af09793 的 1529 项完整离线基线；不把基线数字冒称当前树的新全仓结果。SignalMonitor 代码身份变化须重生成部署；不得重封旧清单。
- 下一步仍有候选显式换代的设计确认、通知失败脱敏/运行壳观测、容量/安装/迁移、更广 E2E 和 C5/C7 外部验收。换代建议仅限从未有订单意图的候选追加新观察并失效旧候选；没有用户确认前不实施。已下单/已消费机会不自动重臂，所有真实交易与研究门禁保持，Goal active。Lore 后在精确提交复验适用信号/事务组合再快进推送并核远端/clean。

### C6 通知失败与脱敏观测实施/清理计划

- 起始 ec3fee4090e849b11d47d7273b028fa16cb471e2 已推送/clean，前轮 250 适用组合与精确提交后 112 项有效；无遗留测试进程。仅执行已批准 C6 的通知可观测和日志脱敏，不代替待确认的候选换代，也不发送真实通知/交易或读实际凭据。
- 已定位原 send_msg 将传输异常全文 traceback 打印，HTTP 失败仅返回 False，未知 backend 会降级 none 并冒称成功；SMTP 未设 timeout/忽略拒收，HTTP 后端只看 status 不看逻辑 ACK。先以真实派发器＋fake HTTP/SMTP 传输观察 RED，保留原懒加载后端/布尔接口，不新增依赖、不重写通知服务。
- 清理范围：删除任意异常文本输出，只输出固定 backend/outcome/reason；按明确 ACK 类型判定软件返回，缺失/非法/逻辑拒绝均失败，不重试或切换其他后端。none 保留显式本地输出语义，不宣称外部送达。网络失败不得改变已提交的订单/账户状态。
- 随后 TDD 增加仅在内存汇总的固定白名单计数和每个运行子阶段的 canonical 观测摘要；复用 RunTradeCycle 原运行 ID、阶段与 journal，不采集任意子进程 stdout/stderr、标题/正文/地址/凭据。摘要缺失/坏字节须标 unknown，不能补造零失败。通知失败作为观测而非订单失败；适用实际子进程/账本/运行壳组合与双 Python 核心、编译/差异、自审/Lore/精确提交后推送。MySQL/外部送达/全安装和 C5–C7 其余门禁未完成。
- 官方响应参考：[Telegram Boolean ok](https://core.telegram.org/bots/api#making-requests)、[Python SMTP 拒收映射与 timeout](https://docs.python.org/3.11/library/smtplib.html)、[Gotify message API](https://gotify.net/docs/pushmsg)、[钉钉自定义机器人入口](https://open.dingtalk.com/document/robots/custom-robot-access)。企业微信官方入口本次无法读取；不因此宣称真实后端认证，使用严格整数 errcode=0 的显式软件契约，其他形状拒绝。

#### 本边界实施与完整离线证据

- 初始真实派发器 16 RED/4 controls PASS：HTTP/SMTP 只 fake 传输，未 fake 派发器或账户。最小 ACK/脱敏修复后 30 pass；再观察缺 scoped observer 与配置失败冒称 none 的 3 RED。ContextVar 只记固定计数、不存消息/凭据，嵌套恢复、返回副本和 KeyboardInterrupt 未完成尝试均验证。
- canonical 摘要 publisher/reader 缺函数 RED 后复用原 write_json_once；有限 payload/SHA、严格 schema/类型/计数、固定 run/stage/module、16 KiB 上界、existing 拒绝。漏文件/坏字节不补零，未完成尝试仍 incomplete。真实新进程空摘要＋阶段/传输组合 70 passed。
- 默认真实 paper 整轮的摘要断言先 RED，测试运输再接实际 RunTradeStage（仅时钟/公共更新传输为 fake），随后 77 passed / 1 小样本 AUC warning（93.18s），原 partial→恢复→重复不重下→模型坏仍退出保持。实际 paper 成交遇通知失败仍记录唯一订单/费用，通知失败不是金融回滚或重试依据。
- 故障注入另外观察：临时清理 OSError 会跳过管理链，诊断 stderr 损坏会覆盖原阶段 0/37 退出码；各先 RED 再最小保护。最新通知/阶段/运行壳/原交易组合 88 passed（15.23s）。后续显式 notify=list/null/string 原被 CEnv 容错降级 none 的 3 RED，局部严格检查仅通知段，不改通用配置或默认值。
- 父进程不捕获任意子进程日志；每阶段独立原运行 ID/新 stage ID 与临时路径，读取后仅将白名单观察并入原 JSONL。未知模块不能经新入口执行，继承来的报告路径会被覆盖/移除；摘要/通知/清理失败不改原阶段状态，原交易/输入失败仍非零。Deployment/OpeningInputs 工作流指纹包含新增代码，旧部署不可重封。
- 文件范围：Common/send_msg_cmd.py、新 Common/NotificationStatus.py、Trade/Script/RunTradeCycle.py、新 RunTradeStage.py、Deployment/OpeningInputs、两通知测试与原 cycle/真实 paper 流程测试、README/本台账。主代理串行审查，非独立审计；无新依赖、用户配置/规则/权限/冻结研究变更，未发真实通知/市场/账户 I/O。外部送达、并发收集、完整安装、迁移、更广 E2E 和 C5/C7 仍未验收，Goal active。
- 三项显式配置 RED 修复后，当前通知/阶段/运行壳组合 81 passed（13.64s）。CPython 3.14.2 与实际 3.11.15 主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml/requests 后，实际缺显式配置的脱敏拒绝、scoped counter、canonical write-once 摘要/reader、原恢复模块失败退出码保留均 PASS；Stage/Cycle 核心导入通过。没有伪造缺失配置的成功路径，不是完整依赖安装矩阵。compileall/diff 通过。
- 最终完整命令 python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -q --tb=short -p no:cacheprovider：1581 passed / 8 expected skipped / 1 network deselected / 18 model/LibSVM warnings，745.88s，明确 exit=0。运行中没有源码/测试/文档编辑；收到结果后仅补本文数字和主线程范围说明。不隐藏小样本 AUC/MLP 告警，不把完整软件功能回归提升为经济采用或外部认证。
- Lore 后在精确提交复验通知/阶段/运行壳及真实默认 paper 流程，再快进推送并核远端完整 SHA/clean。仅删除旧异常全文输出，复用原通知后端、原 write_json_once、原 JSONL 和财务/订单状态机；没有另建消息队列、撮合或金融模型，不自动重试。C6 候选换代待确认，其他软件与 C7 外部要求继续按原 Goal 推进。

### C6 Python 核心/完整依赖安装矩阵（2026-10-22）

- 前轮 37bc07504f47e7c3e4774ddd428660ee06ab949f 已推送/clean；本轮仅文档验收，业务代码、测试和 requirements 未改。详细实施、终局结果、命令和实际 71/70 包解析快照见 [安装矩阵报告](2026-10-22-python-install-matrix.md)。无全局包或用户配置/规则/权限修改。
- 新建两个隔离 venv，关闭 system/user site，先仅装 Script/requirements.txt：3.11.15 核心 35 包、3.14.2 核心 34 包，各自真实导入、96 根合成结构/API、七项可选包缺失和 uv pip check 通过，API payload SHA 完全一致。安装只从公开 PyPI 下载已有声明依赖，wheel-only/no keyring/no 配置继承，无实际市场/账户/通知 I/O。
- 随后原环境升级到 Script/requirements_full.txt：3.11 使用 XGBoost 3.2.0/SciPy 1.17.1/NumPy 2.4.6，3.14 使用 3.4.1/1.18.1/2.5.4；均真实导入/依赖一致性通过，各自完整离线 1581 passed / 8 skipped / 1 network deselected / 18 existing warnings，分别 829.95s / 765.70s，明确 exit=0。运行期间无文件编辑、无并发长任务。
- 3.11 首次句柄丢失且无最终结果的那轮不计 PASS；确认无存活 Python 后才新 basetemp＋JUnit 复验。两个终局 JUnit 各自确认 1589 tests、0 failures/errors、8 skipped，并记录 SHA。skip 仍有外部正式研究、可选 PyQt GUI 和 native isolated 缺通道，不升格认证，不执行正式数据/绩效。
- 本轮无行为清理/重构，复用现有全部测试与真实程序，不为文档变更发明 RED，也不为通过验收 pin/放宽依赖或加入新包。仅新增安装报告并同步 README/本台账；主代理串行自审。测试范围不外推到所有未来依赖/其他 OS/旧产物迁移。此 C6 安装子项完成不关闭 C5/C6/C7 或 Goal，剩余候选换代设计确认、原生准入、容量/迁移/更广 E2E 和外部验收继续保留；Lore 后依精确文档提交复核并快进推送。

### C6 双 venue 默认软件 paper E2E 验收/测试清理计划

- 起始 928fecfdc4245ec19d760ea6bd56f27ddc98e591 已推送/clean；两套隔离完整环境各 1581 pass 有效，当前无活测试进程。继续 Binance 优先、OKX 第二的批准范围，仅合成数据/软件 paper，不接真实交易所/通知或冻结研究。
- 现有默认流程 fixture 只训练 Binance 来源模型。复用实际 1000 根合成行情、前 600 根样本/2 轮 XGB、C2/C3 发布、原运行壳/CLI/PersistentPaperState/C4 核算；给 OKX 单独建库并从样本开始训练，不修改已发布模型/部署的 source 字段，不复制第二套交易/财务逻辑。
- 清理仅把现有 deployment_model 的搭建体提取成带显式 source 的测试 contextmanager，默认 Binance fixture 仍走同一代码；future_candidate 使用该 fixture 原 source。新默认整轮矩阵分别 Binance/OKX，检查独立来源、market id、contractSize≠1、partial/restart/repeat/model-corruption management 及原始账本/历史，不只看最终数量；仅公共 OHLCV 更新传输/合成时钟为 fake，其余真实执行。
- 先核现有行为的适用回归，再扩展验证。若通用路径直接通过，按已存在功能记录，不虚构 RED 或增加无必要生产参数；若新 fixture 发现真实缺陷，先观察失败再最小修复。报价错 venue/掉 reader/放宽原年龄仍须拒绝，不扩大模式/账户准入。
- 测试活进程期间不编辑文件；终局需 JUnit＋明确 exit，适用三模型部署/默认流程/quotes/账户/历史回归、编译/差异、主代理串行自审、Lore/精确提交/快进远端核验。候选换代仍待确认，真实 ACK/mark/book/路由/资金费规则等 C5/C7 外部认证未满足，不以 OKX 软件 PASS 移除门禁或关闭 Goal。
- 通用现有路径直接 GREEN：双 venue 默认整轮＋原部署 44 passed / 5 existing warnings（216.62s），没有生产缺陷或生产代码修复，不伪称 RED。再补逐事件账本/历史与重封错 venue 报价拒绝后，当前默认流程 8 passed / 2 small-model AUC warnings（194.10s），均明确 exit=0。每 venue 独立训练/发布来源，合约大小 0.01、0.03 币=3 张；原 effects 前缀和 C4 全账本重放一致，错 source 保持零 intent/零订单/原账户不变。当前只验 synthetic one_way 单 instrument，不外推全部策略/多币/双向/原生交易所规则。
- 已在前轮隔离 CPython 3.11.15/XGBoost 3.2.0 环境复验同一完整双 venue 默认流程：8 passed / 2 small-model AUC warnings（180.20s），明确 exit=0。原库存量/完整历史/手续费/账户 effects 均核验，无真实 API/候选授权；相同观察重跑的幂等不外推到未获批准的候选换代。
- 最新隔离 CPython 3.14.2/XGBoost 3.4.1 的受影响组合：双 venue 默认流程、原三模型部署、评估绑定、runtime、输入/报价、持久 paper/原 C4、运行壳、历史/事务及 signal lifecycle，364 passed / 6 existing model warnings（295.02s），明确 exit=0。全程无源/测试/文档编辑、无并发长任务，JUnit 保留终局。
- 只提取现有 deployment_model 测试搭建体为 source 显式的 contextmanager，默认 Binance fixture 不变；future_candidate 沿同一实际 source，未增生产 feature/模型/账户/订单接口。两 venue 从 raw source 重新建样本与模型，没有重标旧产物、mock reader/评分/SQLite 或另造财务公式。旧核心代码/依赖/环境保持，前轮两套 1581 完整基线适用于未变代码，不将其冒称当前新增测试后的全仓计数。
- 文件范围为 tests/test_deployment_workflow.py、tests/test_configured_paper_workflow.py、README_FULL.md 与本台账；无生产源码/依赖/配置/权限/规则/冻结研究变更，也不增加可选包。独立 PaperRehearsal 仍固定 Binance，当前通过只扩充默认软件路径的实际适用证据。主代理串行审查，不称独立审计；编译/差异/精确提交后复验与远端核验通过才推送。
- C5 原生完整账户/mark/book/交易所语义、C6 多币/更多策略/双向完整整轮、候选换代（待确认）/容量/迁移，以及 C7 外部认证均保留未完成，Goal active；不因软件通用路径直接通过而降低真实账户门槛。
- 终局 JUnit 复核：3.14 适用组合 364 tests、3.11 双 venue 8 tests，均 failures=errors=skipped=0；XML SHA 分别 `8cbecd5b2c01f00366ebc87da2b05438b0dc2a7f649148536aeb35ca6fee64ed` / `f54af4bbb11985f0332c379d91abe440c48a616e606c6c89541864c51053f916`。两解释器 compileall 与 git diff --check 通过，生产目录与 928fecf 的 diff 为空；本轮没有改变模型/部署代码指纹，不需为了测试复用重封或迁移旧资产。

### C6 全历史输入有界内存核验：实施与清理计划

- 起始 dc5a7c9e12b611ecdb8abdede5b52fef9843a72b 已推送/clean，无活测试进程。确认 inspect_quality 先 query_klines 全量列表、再 closed 列表，inspect_opening_inputs 随后再次全量加载；本轮只去掉这些重复常驻历史列表，不缩短历史、采样或跳过任何字段。
- 复用 CKLineDB 原 SQL 排序/区间和 validate_ohlcv_page 单行＋previous_open 验证；新增可关闭的逐行 cursor，旧 query_klines 仍返回同样的 list。质量收据形状、来源/停牌/缺口/陈旧优先级、UTC 月/周线与完整尾 K 判定保留。
- 输入摘要仍在同一只读 SQLite 事务扫描全部 closed raw rows，用现有 canonical_bytes 逐行加原数组括号/逗号送入 SHA256，必须逐字节等于旧 canonical 整数组摘要，原 count/latest_close/scope/receipt 不变。不新增通用 JSON 框架、依赖、配置预算或缓存；代码身份正常变化，旧模型/部署不得重封伪装兼容。
- 先以真实临时 SQLite 观察缺 iterator/拒绝 bulk query 的 RED，再最小改动；固定小夹具对照旧算法的质量与整份输入摘要，覆盖区间、全部 OHLCV 字段、月线闰年/跨年、partial tail、历史坏行与来源。以合成大历史的实际 tracemalloc 增量约束防止 list(iterator) 回归，不以墙钟耗时作不稳定门槛。
- 适用数据/输入/报价/调度与真实默认 paper 回归、双解释器、compileall/diff、主代理串行自审、Lore/精确提交/快进远端核验；测试活进程不编辑任何文件。不接真实行情/账户/通知、冻结研究或用户配置。原生准入、待批候选换代和 C7 仍保持门禁，完成本子项不关闭 Goal。
- 已观察 15 个预期 RED（缺 iter_klines；旧核验调用整历史 query_klines 被明确拒绝），不是环境失败。最小实现保留旧 list API，质量逐行复用原验证器；摘要只加原 canonical 数组括号/逗号，无第二套 JSON 编码或金融公式。
- 新增 22 项真实 SQLite 回归：原区间排序/提前关闭；ready/no_data/gap/stale/unknown_source/inactive 与坏价/非有限量/错位/partial 的旧收据全字节相同；小时跨日、周/月闰年和跨年、原始 nullable volume 均与旧整数组摘要相等；所有 OHLCV 列的历史修改仍必漂移。WAL 并发修订发生在质量与摘要之间时，同一只读事务不混入后来的值。
- 首轮 3.14 数据/输入/调度组合 148 passed（24.21s）；随后 3.11.15 同组合加原 M5 数据路径 160 passed / 1 network deselected（24.45s），均明确 exit=0。后者 JUnit 160 tests、0 failures/errors/skipped；24→50,000 行实际 tracemalloc 峰值 448810→448909 bytes，增长 99 bytes，旧列表最低会占数 MiB。此数字只覆盖 Python 输入核验分配，不代表 SQLite native cache、整引擎 RAM 或时延预算；大历史早期坏行依旧拒绝，未截历史。
- 最后隔离 CPython 3.14.2 完整命令 `python -m pytest tests -m 'not network' --basetemp <new-temp-directory> -p no:cacheprovider --junitxml <temp-report.xml> -q --tb=short`：1608 passed / 8 skipped / 1 network deselected / 19 existing model/LibSVM warnings，867.95s，明确 exit=0。运行中无源/测试/文档编辑、无并发长任务；包含 Binance/OKX 实际默认 CLI/模型/paper 重启路径与原 C4 账本，并未执行正式研究或真实交易所 I/O。
- 完整 JUnit 确认 1616 tests、0 failures/errors、8 skipped，SHA `3ddedbe7de15c8b215ef29e7f9c58ebc013d5ea3e71ce2cec45050aa6becbc03`；3.11 组合 XML SHA `2d56f44dccff908cf488221985318bead0f6a51375ac550e5dcdbe0931d7e220`。3.14 同一容量断言峰值 572193→572316 bytes，仅增长 123 bytes；不同解释器/测试上下文的绝对常量不作横向性能比较。8 skip 为六项外部正式研究、未安装可选 PyQt 和 Binance isolated 缺原生现金通道，仍不提升为认证。
- 两解释器主动屏蔽 ccxt/xgboost/lightgbm/sklearn/optuna/yaml/PyQt6 后，核心导入与真实内存 SQLite iterator/quality 均 PASS。文件范围仅 OfflineData/offline_data_util.py、Trade/Script/OpeningInputs.py、tests/test_streaming_opening_inputs.py、README_FULL.md 与本台账；没有用户配置/规则/权限/依赖或冻结研究变更。主代理按清单串行自审，不称独立审计；原状态机/账本/公式不变，无缓存/历史裁剪，C5/C6/C7 尚未整体完成，Goal active。

### C6 多市场默认流程：实施与测试清理计划

- 前轮为有效进展：7000eb84749129fb6f26dd9f68fbb44739653e45 已快进推送/clean，完整 1608 pass、精确提交后 72 pass；本轮确认同 HEAD 且无活 Python。继续批准的 C5/C6 软件组合验收，不用历史账户检查或单币默认流程替代原生准入。
- 清理仅扩展原 deployment_model_data 测试搭建体为显式 code pool；默认单币保持原 seed/1000 根数据/前 600 根样本/2 轮 XGB。第二币种使用独立 symbol 与确定性价格倍数，从 raw DB 重建样本/模型/部署，不修改既有已发布身份。复用原候选前向喂入体为同边界多币观察，默认 future_candidate 保留单币调用；只找第一个真实共同候选，不优化收益或改变策略公式。
- 新组合分别 Binance/OKX、one_way/hedged，同 venue 原 C4 cross 账户承载两个不同 contractSize/tick/报价的市场；实际运行壳和 CLI 新进程执行两轮部分成交→重启补齐、逐记录原意图/历史/数量/合约单位核验、费用/effects 前缀和完整 C4 重算。只 fake 公共 OHLCV 更新传输及显式合成时钟，不 fake reader/评分/订单/DB。
- 通过显式软件 funding API 分别给两个市场一次正/负费率，重启后相同来源不重复记账；这不是新增自动 funding 调度器。单市场原 record 减仓不得消耗另一市场 lots，模型损坏后默认管理关闭剩余旧仓且不得新开风险。缺第二市场或重封重复报价时，两市场都不得新 intent/fill，不以第一个市场有效就部分放行全账户。
- 先观察既有组合路径：直接通过如实记为现有行为验收，不虚构 RED 或为凑测试新增生产接口；若出现缺陷，先保留失败证据并最小修复。适用原部署/默认流程/paper/runtime/历史与双解释器回归、compileall/diff、自审、Lore/精确提交/远端核验。活测试期间不编辑；候选换代待批、原生账户/真实交易所、冻结研究和 C7 均不放行。
- 初始两次夹具失败来自测试预期而非业务缺陷：部署 code_list 按 canonical 排序，订单 market 保存标准化 precision/limits 而非原账户配置形状。systematic-debugging 对照 _scope/_paper_market_definition 后修正为原契约精确全字段比较，没有改生产代码/放宽字段，也不把它们记作缺功能 RED。随后 Binance one_way 单场景 1 passed / 1 small-model warning（55.38s）。
- 当前 CPython 3.14.2/XGBoost 3.4.1 适用组合（新增矩阵、原双 venue 默认流程、部署/评估绑定、runtime、输入/报价、C4/paper 持久化、调度及订单历史/事务/lifecycle）376 passed / 8 existing model warnings（540.39s），明确 exit=0；JUnit 376 tests、0 failures/errors/skipped。新增 12 个 case 覆盖两 venue × 两模式的部分成交/恢复/funding/减仓/坏模型，以及缺市场/重复市场的整批拒绝。模型池 artifact IDs 也在 JUnit 按 venue/mode 记录，Binance/OKX 是独立来源的不同模型身份。
- 单市场减仓后，另一市场的完整 DB record 和 C4 lots 字节保持原值，之后坏模型管理仍沿原记录将剩余量归零；每阶段原 effects 前缀与完整 C4 report 重建一致，资金费分市场独立手算而非仅比较总现金。只覆盖两个市场各一条原候选的组合，hedged 标签不提升为同 symbol 同时双腿的默认 CLI 全覆盖。显式 funding API 不是自动调度器。主代理按审查清单串行自审，不称独立审计；未发现需修复的生产缺陷。
- CPython 3.11.15/XGBoost 3.2.0 新矩阵＋原部署（含真实 XGB/LGBM/MLP 单币评分）50 passed / 5 existing model warnings（304.13s），明确 exit=0；新增 12 case 在两解释器均通过。两份终局 JUnit 的 failures/errors/skipped 均为 0，SHA 分别为 3.14 `cc9c39703d96744e87cc271796d949fd3883e012bc9fe4cebb08c6392749fb07` / 3.11 `48a3e5cccc80c73faf9aa4e7da08ae35ab0d2546da0293a6b98efe32a1bca177`。活测试期间没有任何文件编辑；没有真实行情/账户/通知 I/O。
- 本轮只有 tests/test_deployment_workflow.py、tests/test_configured_paper_portfolio.py、README_FULL.md、本台账四文件；只提取/扩展原搭建与候选喂入体，未另建金融/撮合/意图状态机或改生产代码/依赖/用户配置。7000eb8 的完整 1608 pass 对未变生产代码仍适用，本轮不冒称重跑全仓或累加为一次新全量结果。模型多币组合目前 custom＋XGB，其他策略/模型、同币双腿整轮和长时间容量/迁移仍未据此验收。
- 原生 fresh-admission 仍未集成、candidate 未授权、候选换代仍待批，C5/C6/C7 尚未整体完成；已补齐的软件组合证据不能关闭 Goal 或开启测试网/实盘。双解释器编译、差异、主线程审查与精确提交核验后仅按授权快进推送 full-version，不新建 PR/子代理/工作树。

### C5/C6 原生 fresh-admission 关键路径审计与待批方向

- 前轮 ab02e5b50dae50f781887c95e60e47628d952b32 为有效进展，已推送/clean，376＋50 与精确提交后 6 项证据保留。本轮不继续用相似软件组合替代已知原生缺口；读取当前代码并查询官方技术文档，没有请求行情/账户或使用密钥。
- 已核实常量阻断、历史 risk 状态 false、账户 mark_ms=None、ticker 无独立 mark/book，以及 v3 原单冻结/身份检查与 fresh-admission 的区别。context 的 private_routes 不含 Binance fapiPublic；OKX rest 共用基址已有保护，但不等于独立市场来源证据，不能误报完全无保护。新增 [原生准入审计草案](2026-10-22-native-fresh-admission-audit.md) 逐项定位当前证据、缺口、官方字段/时钟含义、拟复用文件与分步验收。
- brainstorming 识别出必须先冻结的材料决策：显式来源年龄/观测跨度/时差、独立公共路由证明、新证明如何在原 CAS/HTTP 边界消费及原生未决预留一致性。已向用户提出一次严格方案确认；未收到答复前仅审计，不将 silence 解释为批准，不修改依赖设计的准入实现或用户配置。旧候选换代审批保持独立。
- 本机 CCXT 4.5.89 仅构造无凭据客户端并检查方法/参考路由；Binance/binanceusdm 的 mark/book 方法、OKX mark/books 方法存在，live/sandbox 属性分别可读，未执行任何 API 方法。SDK 参考 URL 不是交易所可用性证明，不更改 TLS/URL/代理或升级 SDK 来隐藏差异。
- 既有常量门禁、账户身份/快照、持久冻结和输入报价短回归 154 passed（18.64s），明确 exit=0；没有源码/测试/依赖/实际配置改动，不重跑无关模型或捏造 RED。本轮只交付审计/建议与原行为新鲜证据，尚无设计批准或新准入实现，Goal active。
- JUnit 154 tests、0 failures/errors/skipped，SHA `979105764da300cdbc9669d1e812ff8bdef69cdf15c6b725a8a0cfe519c28c3a`。审计的本地引用、DRAFT 状态/批准边界、源代码事实和文档差异核验后，按既有发布授权作 Lore 文档提交；原生准入方向与候选换代的待批状态不得因提交草案被改成已批准。

### C6 可选图床配置/异常边界：实施与清理计划

- 起始 54adad6b580c90fc339fd5a51a94458959b57f1d 已推送/clean，无活测试。上一轮审计为有效进展，原生设计确认仍未收到，不以 Goal 自动续行当批准；本轮处理不依赖该设计的 C6 第 7 项现有接口缺陷。
- Plot.CosApi.upload_file 使用 conf or get_cos_conf：显式空 dict/其他 falsey 值会转读全局配置，可能意外启用远程写；SDK 构造/请求异常未经统一脱敏直接外抛。先用真实 dispatcher/后端加 fake SDK 的最底层运输复现，不装新包、不读实际用户配置或发远程请求。
- 清理范围仅为原图床 dispatcher：只有 conf is None 才走既有配置加载；显式无效/未启用配置在 SDK 前固定 CONFIG_ERROR。沿原 minio/txcos 后端，成功 URL 原样返回，SDK 异常用固定 CChanException 隐去原因链和原文，保持失败可见，不自动重试/换后端或推断远端没写入。
- 不修改原上传 SDK 调用/默认配置/权限/依赖，也不改 PlotDriver、绘图算法、财务/订单/CAS 或通知摘要协议；不把图床接入默认交易阶段或新增 Notion。当前二者不在默认 TradeCycle 调用链，本子项不是可选输出的全部集成/外部认证。
- 真正 RED→最小 GREEN，覆盖显式空配置、坏类型/后端子配置、配置加载失败、两 SDK 构造/请求/签名 URL 分支故障、成功 URL/原文件不变及 KeyboardInterrupt 不吞掉。双解释器适用回归/核心懒加载、编译/差异、自审、Lore/精确提交/远端核验后推送；活测试期间不编辑文件。原生准入/候选换代/C7 门禁不变，Goal active。
- TDD 保留三组真实失败：起初显式空配置两项及 SDK 原异常四项共 6 RED；缺/空/错误类型签名 URL 三项 RED 后才检查 URL 返回类型；主线程审查发现缺 SDK 原 CONFIG_ERROR 不应改成 PLOT_ERR，又先观察两项错误码 RED，再保留 typed CONFIG_ERROR 并脱敏其原文。最终新增文件 40 case，无空跑/条件假通过；Minio 专用分支用 indirect 参数而非另一后端无操作。
- 原串行回归句柄 20424 已不存在且没有匹配活进程；两份终局 XML 均完整记录 136 pass/1 skip，但最终退出输出丢失，未据此推断退出成功。对同一未编辑源码补跑串行双解释器组合，33116 明确 exit=0：3.14.2 为 136 passed / 1 skipped（70.24s），3.11.15 同数（72.56s）；跳过仍仅为既有可选 GUI。JUnit 各 137 tests、0 failures/errors，SHA 分别 `d6ebd0a60eec92ead6fdaae9816a09a6f7d3c2e1041ddaa142a9f50ffcb36506`、`3997234ae03466b7967ae7348c76f1d12a5be7691434256365d93d23dd25b952`，路径为临时目录 chanpy-cos-confirm-py314/py311-54adad6.xml。
- 两解释器阻断 minio/qcloud_cos/ccxt/模型/yaml/PyQt 导入，核心 Cos 模块仍可导入，缺 SDK 固定 CONFIG_ERROR，compileall/diff 均通过。只改 dispatcher、40-case 测试、README 与本台账，不修改原后端 SDK 参数/默认配置、通知协议、账本/CAS、依赖或用户规则。主代理串行自审，不称独立审计；真实图床、SDK 自身日志/内部重试、Notion/默认阶段集成均未认证，不外推 C6/C7 完成。新的原生设计明确批准单独记录并实施，不混入该修复。

### C5/C6 原生严格方向已批准：S1 开始

- 前一回合为有效进展：图床修复 `134b4d7ebd92b67bc64534d9fdf0b0d5040eaeb1` 已推送且精确提交后 40 passed（0.29s）/exit=0/clean。现已收到直接人类答复“批准严格方案（推荐）”，对应独立 mark/book/公共路由、显式年龄/跨度、零默认金额容差、原账户/账本及 CAS 每单复验；不重复请求同一设计批准。
- 采用 executing-plans/TDD，并用 writing-plans 保存 [串行原生实施计划](../plans/2026-10-22-native-fresh-admission.md)。不重写历史审计证据；其顶部已更新批准状态。本轮先独立来源 S1，再按依赖推进 S2/S3/S4；候选换代仍待批，既有发送和研究/C7 门禁不变。
- S1 清理/复用边界：新增来源模块和测试，不改现有上下文/账户表/状态机/运行配置；复用原市场/Decimal/finite canonical 和环境校验。先观察缺函数 RED，再按端点 raw/时钟/单位/路由 mutation 夹具实现；不以局部来源通过宣称鲜活账户准入。
- 实际 TDD：缺模块 collection RED 后首批 6 场景 GREEN；扩展夹具观察 8 RED（ID 在请求中漂移未拒绝四项、未来来源虽然最终拒绝但继续读取四项），再最小补每次 ID/类与即时窗口检查，133 passed。随后元数据 8 RED→修复；主线程对本机 CCXT 原实现自审发现整数位数模式允许负/零值，原先将 zero-significant/负 digits 都视坏值的夹具/实现过窄，明确纠正而非把它们称上游 bug。新增实际 8 RED（浮点位数类型两项、错误拒绝合法整数位数六项）后对齐 SDK：整数位数原样保留，tick 必须正，limits 非负且不倒置。没有新量化/财务公式。
- 独立 `chan-native-market-evidence-v1`：原 market 8 个单位字段＋precision_mode/precision/limits 全部保存；两来源端点/params/raw/各自本地窗口/独立时钟、公共环境与 SDK MRO 源文件及边界代码 SHA。Binance fapiPublic 与 OKX rest/hostname/header 逐请求前后复验，无 private GET；OKX book 不回显 instId，明确 request_only。来源 timestamp 相同但内容/窗口不同仍有不同 payload ID，不用 timestamp 去重，也不以 last/software 代 mark/book。
- 原严格 Decimal50/Inexact 边界转换 Binance base 与 OKX contracts 双单位；不能整除时拒绝，不默默舍入。空/交叉/零量书保留事实并 tradeable=false，不修复为可交易。stored reader 重算全部派生字段/单位/请求/时间/finite canonical，拒绝重封但不自洽的变异；SHA/SDK 本地源码仅描述身份，不能认证调用者或服务器，也不是交易/新风险通行证。显式 SDK source call 上限沿原 128，不外推为 SDK 内部 HTTP 请求/重试控制。
- CPython 3.14.2 适用组合（来源、账户身份/来源/快照/持久化/对账/冻结、execution、合约订单/恢复/审计/安全、运行壳与输入/报价）734 passed / 1 skipped（70.69s），3.11.15 同组合 734 passed / 1 skipped（69.83s），均明确 exit=0；活测试期间无文件编辑。跳过是原 Binance income 缺 isolated position cash channel，不是 GUI，不提升其支持等级。JUnit 各 735 tests，0 failures/errors，SHA 分别 `609b195fad260de1e4504da57e12a347249a7ae87d5edb7917f67349a1bae4dd`、`725dbeda61c7398019085103c11424e4780d8fd5c42485d7b595218653ed28a7`。
- 随后仅新增 3 个验收用例，未改源码：不能整除的单位转换拒绝、两 venue 的已存真实 fake-transport 收据经新子进程屏蔽 ccxt/全部模型/yaml/GUI/图床依赖仍可完整读取。两解释器最终 focused 各 166 passed（3.22s/3.64s），明确 exit=0，无 skip，compileall 均通过；JUnit SHA `cf9ad7b01979644af420357f09e444d697a98bb724144ad90f717ead2fcd2be3` / `400eb97a2f2219a2439bacb751faf0137e805fa1f68fd4a8c946e97b02e2faf9`。不将这些与旧组合相加冒充一次新全量仓库测试。
- 本轮 6 个文件：新增 NativeMarketEvidence/对应测试/批准后的实施计划，更新原审计、README、本台账。无原账户 context/表/公式/CAS/入口或实际配置/权限/依赖改动；只复用原 raw、market、Decimal、canonical 和环境校验。主代理串行自审，不称独立审核。S1 离线来源层通过；下一步 S2 显式年龄/跨度/时差政策与全账户关联，再 S3 原意图/CAS 每单使用，完整 E2E 后才考虑有条件替换常量阻断。候选换代仍待批，C5/C6/C7 与 Goal 未完成。

### C5/C6 S2a 显式鲜活性政策与原来源使用检查：实施/复用计划

- 前轮为有效进展：`1f22cd390f1b306bd268875e2df77fd9a6f01b55` 已推送，精确提交两解释器各 166 passed/exit=0，本轮核实同 HEAD/clean 且无活 pytest。不把 S1 的非准入观察改成全账户通过。
- 沿 executing-plans/TDD 固定 [S2a 字段与时钟规格](../plans/2026-10-22-native-fresh-admission.md)：年龄/跨度/时差显式整毫秒、所有未来必需角色也必须完整给出，不给任何年龄或容差默认。只新增政策 reader 与账户/市场观察断言，不另建账户/撮合/意图状态机或调整现有来源经济字段。
- 源/测试编辑前先记录复用范围：原 AccountSources raw 重算/typed account context、S1 metadata/路由/SDK/代码校验、原严格 Decimal；沿原真实 collectors 生成 synthetic 证据，只 fake native GET 和时钟，不 fake reader/身份/政策结果。断言成功仅返回 None；剩余 wallet/execution/native pending/reservation/全账本/CAS 不会被隐含接受，原 runtime 常量门禁不动。
- 政策 TDD：54 例因缺模块的明确断言 RED，随后最小 reader GREEN；不把 collection import error 当断言通过。schema/完整角色/精确非负 int/零/坏别名/金额容差与 caller-ready 字段均固定。然后实际观察来源使用 API 缺函数断言 RED（-x 第一项），再接原 AccountSources/AccountIdentity/S1 校验；8 个两 venue×两环境标签×单双向持仓的真实 collector 用例 GREEN，均无真实 I/O。
- 新增故障用例复现一个确实存在的 TOCTOU RED：当前身份 GET 回调可改变已核验的 summary 字节而断言未拒绝。修复为固定并复制整个政策/市场/账户/来源 packet，使用前后检查原字节未变；raw/metadata/account cash/policy/不可交易书共 12 个变异回归通过。两次原 typed profile 及公共环境/SDK 核验包围绑定；不能只信重封的 context/环境或 schema。进一步两项真实 RED 证明最后输入序列化耗时尚未计入年龄，最小改为最终字节核验后取时；测试只推进合成时钟，canonical serializer/来源 readers 真实运行不替换返回值。
- 每个年龄/跨度/时差边界覆盖恰等通过、少 1ms 拒绝、显式零不回退；账户从 started 而非 finished 计龄，mark/book 同时核 native source clock 与 request started，total 延续至本次使用完成（含身份读取/等待/最后字节核验）。旧 asset/position mutation 时间不伪造成 mark 或观测时钟。source skew 是提供的不同 Unix 时钟 spread，不称全局相同生成时刻/原子快照。
- 同时覆盖所有市场（不只首候选）、真实持仓被移出 metadata 池的 explicit unsupported，以及 Binance account 独立 position channel 留存、risk channel 隐藏该市场时拒绝；None 不等于数量/PnL/保证金正确。末次 profile 后 public route/SDK/native account/客户端 ID/时钟改变均拒绝，身份延迟不冻结起始使用时刻；网络失败脱敏、不重试/重采金融来源，重验不缓存旧结果。`binanceusdm` 用独立真实无凭据 SDK 类＋原 fake raw 响应，未改 id 标签假装 alias。测试子进程屏蔽全部可选依赖时，政策 reader 可用、真正触发 ccxt 缺失后使用检查固定拒绝，不能报告 readiness。
- 控制台明确 exit=0：CPython 3.14.2 适用组合 886 passed / 1 skipped（74.24s），3.11.15 同组合 886 passed / 1 skipped（74.44s）；均包含新增 149 项、S1 来源、原账户/持久冻结/对账、execution、订单契约/恢复/审计/安全、运行壳与输入报价。JUnit 各 887 tests、0 failures/errors；唯一 skip 仍为 Binance income 缺 isolated position cash channel。SHA 分别 `cd20c18b1111c25f36376fd9f544d892be9941bc81112cbf85971f327b10cb6f`、`ea88da5d43462235ade0c5e1a21f0eb973064720cefa4e32370a31166b331697`；未声称重跑无关模型/全仓。源码与测试在两个活长测试期间均未编辑，双解释器 compileall/diff 通过。
- 文件范围仅新增 Trade/NativeAdmission.py、149-case tests/test_native_admission_freshness.py，更新 README/实施计划/审计/本台账。原来源/账户表/经济公式/ledger/CAS/配置/规则/权限/依赖均未修改，没有证明发布器或 ready=true 接口。主代理串行自审，不称独立审核；最后只澄清 helper 无法检测调用者外部 DB 写锁，调用者必须保证 GET 锁外，这不是已实现事务集成。S2a 子边界完成，完整 S2/S3/S4、当前金融与预占/冻结闭合、C5/C6/C7 仍待，保持 Goal active。
- 文档澄清后未改可执行逻辑，当前树两解释器来源＋政策 focused 各 315 passed（6.86s / 7.52s）、明确 exit=0，compileall 复验通过。主线程核对旧 ModelContract.feature_code_identity、Deployment._workflow_identity、OpeningInputs._evaluator_identity 与 PaperState._runtime 的真实路径列表，新模块不在旧身份里、旧路径未改；不存在自动重封旧部署/模型/纸状态。S3 接入必须显式给新消费者/依赖建立版本化身份；不能因为已有旧 SHA 就声称新准入代码已受保护。

### C5/C6 S2b1 原持久区间与扫描时钟：实施/复用计划

- 前轮为有效进展：`2ed2728d86dd746dfd535254d2477286f4bd7ee2` 已推送且精确提交两解释器各 149 passed；本轮核实同 HEAD/clean、无活 pytest。继续 executing-plans/TDD，保留全部当前门禁。
- 当前核对发现必须直接用 ExecutionStore 原 manifest 中 native_account 的 started/finished；原报告只有 observed_ms=finished，DB 扫描行的 observed_ms 只是导入时间，scan.start/end 又是历史事件覆盖区间，均不能猜成 started。旧 manifest 不改字段、不回填；原 financial v1 仍只是 observed_account_interval/flags=false。
- 按实施计划 S2b1 新增 DB-only 使用断言：只沿原 check ID 重读原来源、原所有 trade-shaped 历史/投影和 sticky freeze，在原 transaction/savepoint 下拒绝当前视图漂移；不新增 passed/report override 或证明/状态机。先记录纯时间检查的最小提取计划，沿原 149 用例保护，原函数行为不扩大；两个 source scope 的年龄/跨度合并检查而非分别 PASS 后绕过全批限制。

### C5/C6 S2b1 原持久区间来源使用检查：离线子边界实现

- 本轮文件范围：Trade/NativeAdmission.py、原 tests/test_native_admission_freshness.py 的兼容 fixture 参数、新 tests/test_native_admission_interval.py；同步 README_FULL、实施计划、审计与本台账。实际配置、规则、权限、依赖、研究输入、原 DB schema/收据/金融公式/状态机/CAS/运行壳均未修改；主代理串行自审，不称独立审核。
- 真实 TDD：先缺 persisted API 的明确断言 RED，再原 collector/store/完整原订单历史的两币非空仓（contractSize .01/.1、单双向）GREEN。钱包与逐市场 execution 仍须原报告完整覆盖 [before.started, after.finished+1)，扫描事实无区间新增交易但原持仓来自真实 fake 订单状态机；不是手填 matched 或 patch reader。after、wallet、execution 原 native observation 和 S1 原市场来源一起按显式政策检查，DB 较晚首次导入不能刷新 execution 年龄；before 是历史锚点，不错算当前源。
- 两项实际 RED 暴露最终年龄检查漏算原事务释放耗时；最小移到所拥有的 transaction/savepoint 退出及最后输入字节核验之后，零行写入仍成立。原库重启、嵌套 savepoint、不结束调用者事务、WAL 下其他连接写入被原 BEGIN IMMEDIATE 阻止、释放后新变更必须再查、期间输入字节变更均有真实 DB fixture。只读断言不会发布新的财务失败，完整调用者仍须沿原 reconcile_account 持久冻结，不能 catch 此异常后继续开仓。
- 补充 8 项真实 DID NOT RAISE RED：TTL 内即使账本不变，已有新 snapshot（未组成 report / 已重新原对账两类）、同 finished 的不同完整 snapshot、未选入原 report 的受损索引都不能被旧检查忽略。沿原 AccountStore.read_evidence 全行校验后用原 stable account_key 关联，拒绝过期 current 点和同钟歧义，不按 SHA/导入顺序选优，也不自动选最新 report。原 matched check 仍可作为历史读取，risk_state 无冻结不等于当前可用。
- 固定精确金额边界：非零持仓的原 mark 与独立 S1 mark 复用原 Fraction helper 比较，不加 epsilon/容差或另写盈亏/保证金公式。当前整份 histories/projections 必须等于原 check；另一 trade-shaped 表、后来原 intent、投影改变、缺任一覆盖和跨连接 sticky freeze 均拒绝。原 v1 unresolved_attempt 仍 incomplete，None/历史 matched/economics_complete=false 都不升级。
- 夹具诊断与行为 RED 分开记账：补测试 AccountStore 合成时钟，修正 fake 配额/满成交不一致，以实际原 acquire_open_intent 生成后续未决历史；第二段扫描的 end-exclusive 边界先推进 1ms，避免 fixture 误向未来查询。这些失败不冒称产品行为缺陷。子进程可选依赖失败根因是旧 CChanDB 构造器尝试默认 YAML 路径；父/子测试显式注入无文件路径环境后全部禁依赖断言保留，不改旧构造器/用户配置。默认 pytest 临时根 cleanup 遇既有 pytest-current 的 WinError 5，未删除/改权限；后续在经检查未存在的唯一 --basetemp 重跑，保留真实失败记录，不将清理异常冒称产品 RED 或旧运行 PASS。
- CPython 3.14.2 聚焦 205 passed（23.54s）；之后扩展适用组合 1103 passed / 1 skipped（110.01s），CPython 3.11.15 同组合 1103 passed / 1 skipped（110.64s），均明确 exit=0。两次活测试期间均无文件编辑。组合覆盖新 56 项、原 149 项、S1、账户/来源/冻结/对账、execution 原存储/归属/绑定、原合约/账户/venue 参数/恢复/审计、安全、运行壳与输入/报价；不是新全仓结果。唯一 skip 仍为 Binance income 缺 isolated position cash channel。
- JUnit 各 1104 tests / 0 failures / 0 errors / 1 skipped：`chanpy-native-interval-regression-py314-2ed2728-5de7.xml` SHA256 `648acf02d5f8b683858b74dc6e896243fd9035e4d51997a365b4b3acec8f2a56`；`chanpy-native-interval-regression-py311-2ed2728-a631.xml` SHA256 `94905a17bd8dd4a51124872328c530fa52efa38864d3fd714fa202d3492da795`。文件均位于 C:\Users\yangj\AppData\Local\Temp。真实补充 RED 为同目录 `chanpy-native-interval-red-2ed2728-68d0.xml`（8 个预期行为失败）。没有抹掉旧失败或把后来 PASS 重新贴给旧树。
- 简化仅为提取已有纯时间检查、复用原 readers/ledger/Fraction/事务；未引入新 financial engine、预占表或本地授权 receipt。仍欠完整当前金融消费者、原生未决单/余额预占协议、原 CAS/HTTP 每单使用与默认入口 E2E；全历史重读容量尚未验证，不借仅无区间新增成交的 fixture 缩减主计划。保持 native_fresh_admission_not_integrated、候选换代待批和所有外部/研究门禁，S2/S3/S4、C5/C6/C7 与 Goal 尚未完成。

### C5/C6 S2b2 原生未决来源：离线来源层通过

- 从 3aad746 clean 验证进展后续接，新增 NativePendingOrders 与 251 项来源测试；原 AccountSources/旧收据、金融/订单状态机及配置未改。使用原完整 market/严格 Decimal、typed account/environment、finite canonical；新观察独立版本，核心 reader 不依赖 CCXT/模型/YAML/GUI/图床，也无 DB 或网络 I/O。
- TDD 从明确缺 module/API 断言开始；初始 fixture setup error 不冒称产品 RED。随后 24 个 bool 空 client/复杂原生条款 RED、6 个算法类别 RED、36 个零 ID/缺失或倒退 mutation 时间/部分成交矛盾/含混 bool 或模式 RED、4 个 Binance 跨 symbol 同 ID 正向 RED 均最小修复。最后 focused 251 passed（14.04s）。Binance orderId/algoId 依据官方文档按 symbol 自增，去重键已包含市场，未放宽同市场重复。
- 来源按账户全列表读取：Binance 普通和 conditional，OKX 普通加八类算法；无 symbol/instType 等候选池过滤，原 ID after 分页直到短页，重复/错类/失败/预算耗尽不发部分结果。每页两次真实 typed profile fake GET 计入 128 显式 SDK 预算，42 页为 126 调用，下一页前拒绝。仍不认证 SDK 内部重试、bot/copy/其他账户域或全局原子不存在。
- 保留原字段/附件/父子单 ID 与请求时钟；普通量沿 contractSize 精确保留 base/contracts/累计/剩余，未知市场和 algo 条件数量不赋零。异常/额外私密 free-text 不持久或回显；route/account/SDK/metadata/clock 漂移及重封不一致均拒绝。观察 flags=false，不提供准入或预占结论。
- CPython 3.14.2 / 3.11.15 串行适用组合各 779 passed（39.47s / 40.48s），明确 exit=0；包含新来源、S1、原身份/账户来源/快照、execution facts、S2a/S2b1。两版 compileall 与 diff check 通过。此前 3aad746 的未改变原状态机/冻结/运行壳 1103 pass/1 skip 证据沿用，不冒称此轮全仓重跑；测试活跃期间无文件编辑。
- JUnit：Temp/chanpy-pending-regression-py314-3aad746-b2f6.xml，SHA256 2899d5b71b9772611b25f1da9f4d1af5a9a2b9b585eeb073746b4ce92b1e64bf；py311 对应 chanpy-pending-regression-py311-3aad746-3e4c.xml，SHA256 3c5c25ad811173ca280a56fdfb70b8fe8452ec155dba0a2204e7f7d871d96ea5。Temp 为 C:\Users\yangj\AppData\Local\Temp；两份均 779 tests/0 failures/errors/skips。
- 主线程审查，未用子代理或真实服务。仅来源层完成：原意图/归属/预占、独立 native 余额与保证金观察、当前金融闭合、原 CAS/HTTP、默认多市场 E2E、容量与 C7 仍待。Goal 保持 active。

### C5/C6 S2b2 原始 intent 与未决数量归属：离线子边界通过

- 从已推送 clean 的 30150e6 继续，新增 Trade/NativePendingOwnership.py 与 95-case 测试，更新 README、原生计划/审计和本台账。没有改旧金融/订单状态机、schema/历史、规则、权限、实际配置或依赖。主线程串行执行和审查，无子代理、真实行情/账户/订单请求或研究任务。
- 沿原 AccountRiskStore._ledger、OrderAudit reader 和 transaction/savepoint 核验所有 trade-shaped 表；原账户/市场/side/leg/server/client/intent 归属直接复用 ExecutionReconcile，执行设置和限额复用原 CCCXTTradeEngine 的纯检查。剩余 quantity/contractSize 是单位核验，不另建金融引擎。每个同账户非终态 attempt 保留 requested-minus-filled 的双单位，native_margin_amount=None，不能解释成零冻结金额。
- 初始缺 API 的 18 项真实 RED 后最小 GREEN；原生 IOC/GTC 条款一项真实失败后补精确 TIF。扩展的 16 个无效单位/数量/名义量/杠杆/模式/账户观测/post-only 原契约都出现 DID NOT RAISE，再复用原校验补齐。后续 4 项真实 RED 证明本地事件时钟倒退或晚于 pending 来源 finished 也必须拒绝。夹具漏传 expected_attempt、复制旧 created_ms、子进程缺合成时钟和事务 spy 未恢复等设置失败分别修正，未算业务 RED，未放宽原契约/时间/无 SDK 断言。
- 原真实 fake 订单引擎覆盖 Binance/OKX × one_way/hedged × 多空 × partial open/close、不同 contractSize 的两币、重启、同市场/跨表原 ID 歧义、Binance 跨市场同 ID、可证明的其他账户、原投影损坏、缺历史/单位、环境漂移和复杂/算法/未知市场。实际 fake HTTP 接单后丢响应的原 submitting 不补 ACK/不重下；empty native lists 不释放原剩余请求。嵌套事务/来源并发变更以及屏蔽 SDK/模型/YAML/GUI 的真实 DB 子进程验证零写入、无实际配置读取。
- 两解释器串行适用组合各 1299 passed / 1 skipped（CPython 3.14.2 131.00s；3.11.15 131.70s），均明确 exit=0。组合含当时新增 91 项与原 pending/mark/账户/金融/冻结/execution/原单契约/恢复/审计/安全/输入门禁。随后只新增 market/post-only 四个正向 case，无生产行为修改；两版各 4 passed（2.61s / 2.94s）。95-case 文件的精确提交复验为后续显式发布检查。两版 compileall、差异检查通过；适用原未改完整回归证据沿用，不冒称新全仓测试或独立审计。
- JUnit 各 1300 tests、0 failures/errors、1 skipped（仍为 Binance isolated position cash channel）：Temp/chanpy-ownership-regression-py314-30150e6-1cc0755c1b4c40d6be378c681045a904.xml，SHA256 6ec9b195e6b60ccabdf272b7944a57a42e59bf44bd43eba4807a035849156f48；py311 对应 chanpy-ownership-regression-py311-30150e6-0897b2930bec4468acda35460554565b.xml，SHA256 7b9635b6b584682473bbf7d14a811fd4f376bdf0f9f6ed9bd0da29b50ebe75a8。Temp 为 C:\Users\yangj\AppData\Local\Temp，活测试期间没有编辑文件。
- 新报告两个 flags=false；只能关联本次来源字节与所读 ledger，不能认证当前客户端/来源真实性/新鲜度、余额或 native margin。S2b2 后续仍须独立原生余额/挂单保证金/账户模式观察及原金融核算复用，再接原 CAS/HTTP 和默认入口。native_fresh_admission_not_integrated 与全部候选/测试网/实盘/C7 门禁保留，Goal active。

### C5/C6 S2b2 原生余额预占来源：独立离线来源层通过

- 941a59a7f60950dec484c256a37a5ba35555d84b 已推送、远端 SHA 相同且 clean；精确提交后两版各 95 passed（30.03s / 29.51s）。在其后新增 NativeBalanceReservations 和 66-case 测试；变更仅为这两文件及 README/原生计划/审计/台账，旧金融/账户/订单/CAS/运行入口、依赖与实际配置未改。
- 先冻结来源接口/字段/请求顺序并得到 7 项缺 module 的明确 RED，再实现最小 GREEN。扩展金额/币种/原字段重封/配置/环境/异常和核心 reader 后 65 passed。主线程审查补出 OKX 显式 configuration 响应 UID 与周围 typed profile 不同却通过的 1 项 DID NOT RAISE；随后采集时核响应 UID 摘要，逐观察保存 hash 与全局账户关联，不持久原 uid/私密配置。66 passed（4.17s），不是将 caller 的自封 SHA 当服务端认证。
- 固定 configuration_before→balance→configuration_after；Binance native accountConfig/V3 account、OKX account/config/balance，不加候选池或币种过滤。每段前后原 typed profile、当前 route/TLS/SDK/客户端守卫共 9 次显式 GET，无重试/降级或 partial receipt。两份允许的配置须相同；允许的原 mutation 时钟和请求窗口分别命名，不用 Binance reserved config.updateTime 或 asset updateTime 代替 fresh 时钟。
- 复用原 AccountIdentity、AccountSources 原 raw allowlist 部分、ExecutionFacts 严格 Decimal 和 NativeMarketEvidence SDK 身份边界；只扩展新 schema，不修改旧允许字段或重封旧来源。Binance position/open-order initial margin、OKX ordFrozen/frozenBal/iso/借贷/策略/copy 分项、全部返回币种及 Binance 原 account positions 保留。空/缺项为 None，负余额不删/归零；USD 总额不换算进结算现金，不新增保证金公式/每单预占分摊。两个 flags=false。
- 串行两版适用组合各 940 passed（CPython 3.14.2 72.71s；3.11.15 73.26s），明确 exit=0、0 failures/errors/skips；包含新 66 项、归属 95、pending 来源、mark/book、typed identity、原账户/执行来源与 S2a/S2b1。此前原状态机/冻结/金融等 1299 pass/1 skip 对未变实现沿用，不声称新全仓结果。活测试期间没有编辑文件；两版 compileall 和 diff check 通过，主线程串行审查，无独立审计或真实服务。
- JUnit：Temp/chanpy-balance-regression-py314-941a59a-3667500d5c81409491cc0031c43a7799.xml，SHA256 101768046ad0f0a032ef5ba165970ffede63c7ae18fed7385ef1deef559322ea；py311 为 chanpy-balance-regression-py311-941a59a-dd9b918e314940f6934f3a1000b075db.xml，SHA256 c7891cde90e33b992ae275f0ac91224097bf067a83f5110797530b18712c3c52。Temp 为 C:\Users\yangj\AppData\Local\Temp，两份各 940 tests。
- 下一依赖是原金融核算复用下的当前余额/预占与 positions/wallet/executions/完整 ledger 闭合，再接原持久失败/冻结、源当前使用与原 CAS/HTTP/默认入口。观察到字段不等于完成经济证明；SDK 内部重试、真实端点/长期容量、候选换代与 C7 均未据此验收。S2/S3/S4、C5/C6/C7 和 Goal 仍未完成。

### C5/C6 S2b3 原金融共享体与 native 未决/余额组件：观察闭合

- 起始 2ee0345242af127dd5a0ea1c808dce724974dde4 已推送/clean；本轮串行推进。新增 NativeAccountReconcile、59-case tests/test_native_account_components.py；对原 AccountReconcile 共享体作最小版本分支，原 interval fixture 仅增加可选 source/market hooks，默认行为不变。同步 README/实施计划/审计/台账；未改订单/CAS、旧 schema、配置、依赖、规则、权限或研究输入。
- 新公开 pending-v2 builder 只接受 raw pending，与所给同一原 histories/projections 重建归属，不接受 caller 的 qualified/PASS 集合或删除旧报告的问题。原公开 v1 不扩展参数、仍遇非终态 incomplete；其钱包链、native position/UPL、费用/已实现/funding、pooled entry 和 DB current_qty 全部共用原实现。独立 v2 输入摘要含重建的 pending 身份，新报告不重封成旧 v1。
- 夹具保留一次原状态机拒绝：同一记录开单仍 open 时不能取得平仓意图。未绕过 CAS；最终用 TEST 部分平仓＋ALT（contractSize .1）部分开仓未决，原执行扫描/现金流水覆盖两币全部区间变化，实际费用/实现收益/资金费与原持仓逐项相符。fake exchange 三次 create，native aggregate order margin 非零；非新造金融/订单状态机。旧 helper 参数名和时钟等设置失败不记作业务 RED。
- 实际 RED→GREEN：8 项缺组件 API RED；外币隐藏 margin 2 项、available/IMR/MMR 覆盖 4 项、同市场原 ID 重复 2 项、独立 balance 仓位/空列表仍有 margin 7 项、早期 crossWallet/crossUnPnl/availEq 覆盖最终快照 3 项均有真实失败后再最小实现。Binance 跨市场同 ID、额外外币现金但无外币 margin、native 额外限制使 available 低于上界均正向通过，没有用更窄的空仓/单币/零预占夹具代替目标。
- `observe_native_account_components` 按原持久 before/after/wallet/execution IDs，原同一 SQLite transaction/savepoint 读取全 ledger、原来源与所有旧 checks 的 sticky freeze；余额/pending 新来源需先于最终 after 且 identity/全部市场对应。各币现金/权益/UPL与共同字段、原账户腿、native margin/available约束核验；美元总额不换汇，挂单 margin 不分摊每单、OKX IMR 不重复扣 ordFrozen。reported_available 是原生观察，不可携带授权；金额未知不填零。
- v1 一次性兼容性检查：对这两 venue 的相同双币输入，加载 Git 已接受 2ee0345 的 AccountReconcile 纯实现，与当前公开 v1 输出 canonical bytes 完全相等，2 passed（2.41s）。不虚构不改变行为的 RED；检查保留 JUnit，避免把 Git/历史对象依赖引入常规单测。生产 v1 分支之后未改，适用原证据仍可复用。
- CPython 3.14.2 广组合 1416 passed / 1 skipped（158.60s）；其后只增加新组件的跨来源核验与 12 个变异/正向 case，共享原 v1 核算体不再修改。最终关键组合（59 新组件＋原区间/冻结＋归属/余额来源）299 passed / 1 skipped（84.16s）。CPython 3.11.15 对最终树广组合 1428 passed / 1 skipped（171.03s）。所有命令明确 exit=0；唯一 skip 始终为既有 Binance isolated position cash channel。旧未变代码验证复用，不把重叠组合相加为一次全仓结果。活测试期间没有编辑文件。
- 广组合 JUnit：Temp/chanpy-components-regression-py314-2ee0345-2eea348093514b2cb34b0ada81dd0b35.xml（1417 tests）SHA256 13288896d7ec5aec9ddaeb17915fc4af3d89ffccab50895af8737db62393c652；py311 对应 chanpy-components-regression-py311-2ee0345-20ec240169644c6285ea158a850710fb.xml（1429 tests）SHA256 2df9b0d6ad5f119ff0d5f02753074cef6c6fe32ebb3e70b12ea2da9283f78e2d。最终 py314 关键组合 chanpy-native-components-final-py314-4a6df9e62ff24533a6e7bcd51ee4730d.xml（300 tests）SHA256 897c64953148080698adfa3ed71dd15a69251398d9b797725a174284ab6c855b；兼容性 2 项 chanpy-native-components-v1-compat-04f7557593a64c44be2d9a75e709e7c5.xml SHA256 f9a327f8f08d0aecb2a12a80be8a488c7045e2a06fa6912ca1c97c581a3536d8。Temp 为 C:\Users\yangj\AppData\Local\Temp。
- 双解释器 compileall/diff 通过，主线程审查，无独立审计或真实交易所 I/O。新增夹具与核心子进程显式无文件 CEnv；原单测仍可能沿仓库 demo 路径解析，已确认无实际 Config/config.yaml 或 CHANPY_CONFIG，不写配置。新金融模块及共享 v2 不在旧 workflow/input/paper 指纹覆盖内，S3 必须明确版本绑定，不能重封旧模型/部署/订单。
- 下一步仍须新来源版本化持久化、复用原 append-only check/sticky freeze 发布并可重建失败，以及全部当前来源政策/独立 mark/book/原 CAS/HTTP/默认入口；本步只返回两个 flags=false 的观察报告，matched_components 不是 native admission。SDK 内部重试、长期容量、isolated/借贷/portfolio 等未覆盖域与 C7 外部认证不据此放行，Goal active。

### C5/C6 S2b4 原生 pending/balance 版本化存储子层

- 1120378fa1ae186b4f419e760600f65195bc6191 已推送，提交后两版各 59 passed（30.61s/30.13s），远端 exact SHA/clean 已核；一次 PowerShell junit 参数拼接错误导致 no tests ran，修正为显式变量后才产生上述验证，不记业务 RED。随后从 clean 1120378 串行继续。
- 新增 Trade/NativeAccountStore.py、tests/test_native_account_observation_store.py；Trade/SqliteDB.py 只增加新 schema 原子初始化及保留名，Trade/db_util.py 增加三个显式原生来源存取接口。沿用旧 AccountStore codec、AccountRiskStore stable key、原 schema validator/事务，未改旧表 SQL/schema/历史文档或复制金融/订单算法；未加依赖、规则或实际配置。
- 真实缺模块 API RED（1 failed）后实现来源层，首轮 63 passed；补充独立 raw/derived 金额、未来 observed_ms、旧来源不重封、缺触发器、坏 ID、MySQL fail-closed 后共 85 新测试。两 venue、两 source 逐字节重启/幂等；UPDATE/DELETE/REPLACE 拒绝，索引篡改先验后筛；插入异常固定脱敏且零文档/检查/订单变化，source 入锁前冻结，读结果不缓存，外层事务/savepoint 不被提交；外来同名表不采用且旧 schema 写入回滚。
- source ID 为完整 canonical document SHA，重读调用原 native verifier 重算 raw→derived/代码与类型化账户/窗口，核完全部列；账户列表用稳定 native key，不把 route/scope 当账户。核心子进程阻断 ccxt/yaml/model/GUI 仍能重启读验且零写入，显式空 CEnv，未接真实服务或认证原始来源。
- CPython 3.14.2 广组合 1519 passed / 1 skipped（217.82s）；3.11.15 相同组合 1519 passed / 1 skipped（210.57s），两者明确 exit=0。包含全部新 85、原 59 组件、pending/balance/归属/market/current interval、原钱包/执行/身份/订单/冻结及 SQLite transaction。唯一 skip 仍为既有 Binance isolated position cash channel；不把覆盖重叠相加为全仓结果。全程严格串行，pytest 活进程期间未编辑文件。
- JUnit：Temp/chanpy-native-store-regression-py314-fe62b0b4a1144b188613440a072d2c64.xml SHA256 384ab694946a023c3cbb4a3d71efeb3ece1cc7da271c463d40942090a50c4aeb；py311 为 chanpy-native-store-regression-py311-19d6fd80c699406b8762f36fdb21ab29.xml SHA256 46c68dc46b02f201a8e83692dc6d099016c528d864948f110a84a38172662714，两份各 1520 tests / 0 failures / 0 errors / 1 skip。Temp 为 C:\Users\yangj\AppData\Local\Temp。
- 本步只保存来源，不发 PASS、不发布失败/冻结、不自动 ACK、不发订单，两个原生 flags=false。新组件 check 重建/原 sticky failure 发布、全部来源当前性与 collector-owned、mark/book 和原 CAS/HTTP/源码版本绑定仍待；旧候选身份不得自动重封或重新武装。长期容量/真实端点与 C7 未认证，Goal active。

### C5/C6 S2b4 原 checks 表的新组件重建/失败冻结子层

- c70bc4d9eab6c122bce4b93761e060b80bb6be66 已快进推送且远端 exact SHA/clean 核验，提交后两版各 85 passed（35.91s/35.98s）。随后串行继续本子层，活 pytest 期间未编辑文件。
- 新增 NativeAccountCheck.py、37-case tests/test_native_account_component_checks.py；AccountRiskStore 只抽出共用 append-only publisher 与显式新 schema reader dispatch，旧表 SQL/v1 document 不改。NativeAccountReconcile 抽出纯组件共享体，DB observer 另合并当前 sticky freeze；db_util 增加只接受六类持久 source IDs 的 reconcile_native_account。无第二套金融/撮合/订单/冻结状态机，无 caller matched/qualified 输入、配置/权限/规则/依赖改动。
- 真实缺 API RED（1 failed）后最小实现。首组合 117 passed/2 failed：负例重复运行同一交易 fixture 触发原 execution source 身份冲突，属于夹具错误而非新业务 RED；保留原约束，改为同一 fake account 的第二次原 collector 余额响应，未重下单或重封派生输入，随后 32 focused passed；补跨连接/核心 reader/完整 journal proof 后 37 focused passed（22.38s）。
- 新 `chan-native-account-check-v1` 与旧 v1 共用 chanpy_account_checks/原 stable-key sticky freeze。报告 wrapper 只将 matched_components 映射为 matched_observations，并显式 historical_native_components_only、economics_complete=false/native_admission_verified=false；不是经济完整或当前准入。缺 source/金融分歧/投影漂移发布原固定 failure 或组件问题；发布/schema 异常仍拒绝并回滚，不能为保存冻结绕过 DB 完整性。后来的匹配不能删除任何原/native 失败。
- 历史 inputs 保存当时全 histories/projections 与原 journal explicit event_id 前缀的全 attempt/event 行摘要；reader 重读精确持久源、原 prefix 字节链、全部 key/事件数后重算同一组件数学，不读当前 projection 作旧结论。未使用隐含 rowid；删去零成交撤销尝试与对应 projection，再新算 matched report 并重封全部 check SHA 仍被原完整前缀拒绝。后来真实部分减仓/新 journal 事件不改变旧 check，历史匹配也不变成当前验证。
- 两 venue × 两模式 × 多空非空 pending/真实部分假流水匹配，旧 v1 unresolved failure 与 native matched 共存仍冻结；缺来源/金额/当前 qty、原 UPDATE/DELETE/REPLACE、错误发布/嵌套 savepoint、重启/核心无 ccxt/yaml/model/GUI 皆验证。另一连接在原 claim 后/HTTP 前发布 native failure 阻止原 create，submitting 不自动重试；原已证明减仓继续，测试没有实际订单服务。
- CPython 3.14.2 广组合 1662 passed / 1 skipped / 6 warnings（273.83s）；3.11.15 同组合 1662 passed / 1 skipped / 6 warnings（278.40s），两者 exit=0。包含当前 37＋85＋59、完整 native/current-source 基础和原金融/订单/冻结/SQLite/来源回归，并额外纳入 model deployment contract、deployment workflow、persistent paper state；不是全仓/外部认证。唯一 skip 为既有 Binance isolated cash channel；4 个小样本 MLP 最大 60 轮未收敛及 2 个 xgboost 单类 AUC 警告照实保留，非训练绩效采用结果。
- JUnit：Temp/chanpy-native-check-regression-py314-a5eb1a5991a84f129c46bc93d69eda10.xml SHA256 876b967328e3a559e00b76e8caa1cd90a89dcefad8df7dec84f6b7631eadc11e；py311 为 chanpy-native-check-regression-py311-5d00370d14f64bf287553671e4c5491b.xml SHA256 67c4560806632a9b47a248514cf9e8f47441d5b413b28974606f791c141b0b77。每份 1663 tests / 0 failures / 0 errors / 1 skip，Temp 为 C:\Users\yangj\AppData\Local\Temp。
- 下一依赖是完整 current consumer：新 pending/balance 年龄/观测跨度/最新来源与当前 client、独立 mark/book/全市场池/真实 ledger 关联，之后原 CAS/HTTP 每单复验与默认入口。原 workflow 指纹会检测 db_util/SqliteDB 改动，但仍未覆盖所有新增 native 模块，S3 须完整版本绑定；禁止重封旧候选或自动重新武装。常量阻断及全部 candidate/testnet/live gates 保留，长期容量/真实端点/外部 C7 未认证，S2/C5/C6/C7 和 Goal 仍未完成。

### C5/C6 S2b5 组件来源统一当前使用政策/断言

- 从远端一致/clean db75c5eaecba543bc9cd51671c59999c8fbc8987 串行继续；该提交后两版各 37 passed（21.30s/21.20s）及 exact push 已核。新增 Trade/NativeCurrentComponents.py、107-case tests/test_native_current_components.py；NativeAdmission 抽出原共用 DB 区间体并仅向内部窗口 helper 增加默认空的 additional 角色，原公共入口/旧政策/报告字节不拓宽；同步 README/计划/审计/本台账。未改实际配置、规则、权限、依赖、模型、订单状态机、研究输入或已冻结证据。
- 新政策 chan-native-component-freshness-policy-v1 显式新增 balance age/span，其他 age/span/skew 原冻结形状复用 v1 验证，bool/float/string/缺项/别名/额外 passed/容差均拒绝；0 是严格零。旧 policy reader 拒绝新版本，不能从 account 预算回填 balance，也没有默认配置入口。
- assert_native_components_current 只读匹配的 native check、原完整 ledger/冻结与 source IDs，在两个 SQLite 视图之间复查当前 typed account/public route/SDK/声明完整 market pool，并将 account/mark/book/wallet/execution/open_orders/balance 角色统一计算年龄/跨度/skew。私有读取始终位于 writer lock 外，调用者已有事务则立即拒绝；DB 退出/提交延迟、profile 延迟、输入 packet/其他连接 current_qty 或 freeze 改动均不会漏入早期 PASS。成功仅 None，无发布/订单/authorization receipt。
- 所有 known snapshots/wallet/executions/native pending/balance 原字节/元数据先验证，再按 stable account/角色看最新；较新或同 finished 不同字节且未整合的 source 拒绝，无 SHA 排名。自洽但 native source SDK version/file hashes 不对应当前市场/SDK 的旧包拒绝。年龄恰等/少 1ms、真实 fake pending/balance 非零请求跨度、统一 total/skew、路由/账户/市场/version、未选中新 source 索引损坏、无 SDK/Config 的纯政策导入均覆盖。
- 真实缺模块政策 RED（1 failed）→22 政策 pass；独立缺 joint API RED（1 failed）后实现。首联合组合 227 passed/8 failed，trace 指向账户年龄：旧组件夹具原账户使用历史 fake clock，execution association 使用晚约 10s 的墙钟，2s 预算正确拒绝。只把原执行 collector/association 接到同一现有 fake clock，不扩大预算或生产容差；之后 30 pass、边界扩充 72 pass。再出现 94 pass/2 failed 的 fixture 假设错误：重复相同 execution packet 只会原幂等返回同 ID，不生成新观察；改为新查询窗口并另加幂等不刷新年龄回归，不改旧 store。随后 303 focused 组合 pass，最后索引/core 补充形成 107 新用例。
- 正向使用原双市场、两 venue × 两模式 × 多空的非空持仓/部分成交、费用/funding、原 wallet/execution、非零普通 pending/aggregate margin 和独立 mark/book，不以空仓/无未决/零预占替代。fake 原订单 create 始终 3 笔，断言无新写入/检查/冻结发布或自动 retry。原 _current_interval_snapshot 重构沿用旧 56 区间与 149 政策回归保护，未复制金融/订单逻辑。
- CPython 3.14.2 适用广组合 1663 passed/1 skipped（263.74s）；3.11.15 1663 passed/1 skipped（264.16s），均 exit=0、0 failures/errors/warnings。包含当前107、native check/store/components/pending/balance/ownership、原区间/政策/来源/订单/冻结/SQLite。未变模型/deployment/persistent paper 仍沿用 db75c5e 两版各 1662 pass/1 skip/6 小样本模型警告证据，不误报本次全仓覆盖。唯一 skip 仍为既有 Binance isolated cash channel。
- JUnit：Temp/chanpy-native-current-regression-py314-10d6fa7052f246c9859b216e8a9a18a9.xml SHA256 bf15028167f9b2de07d5d2819dfa86ec738a86d4318186567ad623e9aa34270b；py311 为 chanpy-native-current-regression-py311-a1d8cbee7353485fbb7a4d7922cffd49.xml SHA256 bc5d34da1b1bfeae8b2cb361d4b6b0ef9cde241fc0b16dc885487608800d5c47，两份各 1664 tests/0 failures/0 errors/1 skip；Temp 为 C:\Users\yangj\AppData\Local\Temp。py311 命令误重复传入一个 pending 测试路径，实际 pytest 未重复 collection；XML 每份 unique classname/name=1664，完整集合差异=0，不增加覆盖计数。全程无并发 pytest/子代理，活测试无文件编辑。
- 此步是完整组件来源的使用断言，不是 collector-owned 来源真实性、交易所服务器原子快照、实际 instrument metadata 当前性或新风险能力；原 C4/economics_complete=false 不提升。下一步须固定顺序自采来源/原失败发布，再与原 market/intent/CAS/HTTP 每单直接消费、版本身份及默认入口绑定。实际配置/候选换代/重新武装仍无批准，SDK 内部重试/容量/真实服务和外部 C7 未认证，常量阻断与 Goal active 保留。

### S2b5 推送前已知事实覆盖纠正

- 12ab104 已 Lore 提交，精确提交后两版各 107 passed（52.87s/52.22s），但本次未立即推送。主线程复核识别到 source latest 只按观察结束时间不足以证明已知事实完整；因此先保留本地提交，补 RED 后再发布纠正，不把先前 GREEN 当最终接受。
- 真实 fixture 先暴露 wallet 旧 clock 倒退使既有来源被判未来、execution 两项 DID NOT RAISE；只恢复 wallet 发布/读验的正常 use clock后，两 venue × 两 source 都确认 DID NOT RAISE RED。扩展为12边界：区间内和 after endpoint 的已知额外零净额转账/成交往返共8 RED、before baseline共4正确 positive，全部原 raw collectors/store，不改 DB 以冒充测试结果。
- 修复仅 Trade/NativeCurrentComponents.py 增加共用 canonical fact coverage 与两个调用点，tests/test_native_current_components.py 新增12项；原金融、schema/store、NativeAdmission、其他消费者与依赖均未再修改。已知区间事实须逐条包含；已知终点后的事实使该账户点 stale；基线前事实仍不误拒绝。没有净额化/最佳匹配/排名或金额容差。
- 修复后当前119 passed（62.33s）；最终关键组合含119 current＋37 native check＋56原 interval＋149原 policy，两版各361 passed（3.14.2 101.72s；3.11.15 100.93s），均 exit=0、0 failures/errors/skips/warnings。12ab104 两版1663 pass/1 skip广组合仅对未变代码/依赖/配置/环境继续复用，不称作最终全仓结果；rg确认新 current module尚无默认 production调用。实际 Config/config.yaml 与 CHANPY_CONFIG均不存在（只查布尔），新夹具用空 CEnv，不写配置。
- 最终 JUnit：Temp/chanpy-native-known-final-py314-5a97d8f3091f49729a96270f10e9a6ef.xml SHA256 cb267480474aa799981de1be24bef27c9717ee284821c1c72565d9f93a2f1c1f；py311 为 chanpy-native-known-final-py311-ced4b8ceea3c42ad982241eb1df3f47e.xml SHA256 8797f329ec5ed0fd6d8ff64c081a1c6cff8ccf98f4a4592a40bcece676f4ce57，各361 tests、0 failure/error/skip，Temp 为 C:\Users\yangj\AppData\Local\Temp。两版 compileall/diff通过，活 pytest 时未编辑文件。
- 12ab104 与本纠正按 Lore 记录并在验证后快进一起推送，禁止 amend/重封旧证明或省略失败证据。当前性断言仍 None/无授权；下一依赖 collector-owned固定顺序采集/原失败发布、实际 market/intent/CAS/HTTP 与完整版本身份/默认入口，原 candidate/testnet/live gates及常量阻断不变。未做真实交易/容量/外部C7，完整Goal仍 active。

### C5/C6 S2b6 固定顺序本地自采与原失败发布

- 从 origin/full-version 一致/clean 的 3db889433a5466cd848a1d9b0d29eefc207008a4 串行继续。新增 Trade/NativeComponentCollector.py、78-case tests/test_native_component_collector.py；NativeAccountCheck 仅增加沿原 publisher 的固定 unavailable 私有入口。同步计划/README/审计/台账；无原 collector/schema/金融/订单状态机/实际配置/权限/规则/依赖/研究输入变化。
- collect_and_check_native_components 固定 pending→balance→额外 typed profile→after snapshot→每市场 execution＋真实前后账户观察→全账户 wallet→独立 mark/book→原子存源/native check→联合 current。基线/全 ledger/冻结来自初始原 SQLite 视图，source GET 均在 writer lock 外，发布前再验同一 ledger/DB/输入与源码文件。接口不接 receipts/PASS/check_id，原 before 市场顺序保持，执行/市场来源规范排序。成功只生成本地诊断包装，source/check IDs、显式 policy、代码文件/DB 位置摘要及两个 flags=false，不创建订单/ACK，不提供 transferable admission。
- 真实缺 API RED 后最初27项出现10 failed/17 passed；回溯为原 before 市场顺序 TEST→ALT 与 after 规范化 ALT→TEST 不一致。仅在新自采层将 after 按原 before 排列，不改旧核算/schema/锚点，之后原27项全过（上一测试 session 已失效时从完整 JUnit 确认27/0/0）。新增 scope RED 确认 None 到第23次 private调用才拒绝；沿原 account_scope predicate 提前验证后14项零I/O通过。
- 提交失败注入先因测试错误预期 mismatch 而失败（原归属漂移实际为 incomplete），修正该中间预期后观察真正两 venue RED：check 随提交回滚，risk.frozen仍false。增加 published 标记，仅成功退出原事务才认为精确失败已保存，4项GREEN。连接替换另有两 venue 真实 RED：fallback向另一合法SQLite写了失败；提取同一连接/位置检查用于正常和失败路径后拒绝错库写入，保留无持久冻结声明。未删除失败证据或用最后PASS掩盖根因。
- 其余回归覆盖7阶段异常且只尝试一次、无新订单/原三笔fake创建不变；source插入/check发布失败整批回滚，原库可写时独立失败持久冻结、check表不可写时拒绝但不假称冻结；精确失败一次提交/重启/后续零I/O；其他连接账本/冻结写入保留、原DB/连接/table/政策/市场/源码变化拒绝、不写替换库；入口缺policy/before/完整市场/非法mode/外部PASS均零I/O；无SDK/Config的核心子进程可导入。
- 保守显式 SDK 上界 Binance 276+132N / OKX 274+132N，完整市场N为1..64；两市场正向实测39/58，与最底层fake调用计数相等，固定阶段N+6。沿原单collector128次限额，不包装SDK方法在生产中假称全流程128cap；不sleep/伪造时钟或重试，不认证SDK内部HTTP重试或真实长期容量。
- CPython 3.14.2 适用广组合1753 passed/1既有 skipped（325.24s）；3.11.15 同为1753 passed/1既有 skipped（322.96s），均exit=0，0 failure/error/warnings，1754 unique classname/name用例集合差异0，含全部78新用例。唯一skip仍为Binance income未提供isolated position cash channel。包含原来源/账户/金融/订单/冻结/SQLite；未变model/deployment/persistent paper继续沿用db75c5e既有适用证据，不称本次全仓回归。两版compileall及diff通过；无活测试期间编辑/并发pytest/子代理。
- JUnit：Temp/chanpy-native-owned-regression-py314-23137e086d10461fad4a8bd18a738937.xml SHA256 e41d3e07dc2cbd2b3ca47627d09d6dd098b41726bb70591bc066b24adb8a1410；py311为chanpy-native-owned-regression-py311-49159ff8dd9648e3a487bc609183d334.xml SHA256 4870d26596a67a09a4717407e6d1ae37b6773c5d9a0a187d930112e4c21281ee。Temp为C:\Users\yangj\AppData\Local\Temp。实际Config/config.yaml与CHANPY_CONFIG仍不存在（只查布尔），没有配置文件改动。
- 主线程按计划/代码/异常/兼容性复核，无独立审计声明。后续S3必须绑定实际instrument metadata、候选/部署/配置、DB/加载runtime及原每单intent/CAS/HTTP并冻结预占规则；source文件SHA不等于全部运行时身份，原生available/margin不能自行分摊或套用软件杠杆公式。新collector尚无默认生产调用，未变旧candidate/testnet/live门禁/常量阻断，未做真实端点/外部C7，S2/C5/C6/C7/完整Goal仍active。验证后的Lore提交及精确身份推送不改变这些边界。

### S3 接入前详细预留协议复核（设计审查点，未实施 CAS）

- 起点242d36ea5715093fbece5368f3e1f6e1ad78becf已推送/clean；提交后两版自采各78 passed（49.01s/50.94s），远端SHA与HEAD/origin相同。此次原代码核对发现：原 acquire/claim 是record级竞争，native current完整ledger在合法自身intent/claim后也会改变；v3显式契约分支同时存在Engine、NativePendingOwnership、AccountReconcile、ExecutionReconcile，不能只改一个schema集合。
- 只读取公开官方文档及本机CCXT4.5.89源码，没有交易所数据/账户/订单请求。Binance test-order文档说明不进入撮合，不能由此推导本地账户资金锁；OKX order-precheck文档适用于Multi-currency/Portfolio而非当前acctLv2，不能切换模式或借用其PASS。OKX max-size是候选原生数量观察，不是跨venue通用资金模型。OKX全文因工具页面大小限制未读，模式/权限/端点条件由官方定向检索核对，细节和来源链接见草案，不冒称全面外部验收。
- 实际SDK的load_markets默认命中cache，reload=True可能先fetch_currencies；两venue默认fetch_markets还有跨产品读取。拒绝简单全局reload补丁作为“原生metadata已当前”的证明；后续须限制明确原生public endpoint/目标池及观测身份，不改用户配置以绕过。
- 新增specs/2026-10-23-native-per-order-admission-protocol.md并在S3计划关联：建议对尚未被原生观察的新风险意图做账户级原CAS串行化，L0→本单唯一intent增量L1→唯一claim增量L2逐项校验，unknown不释放；完整已观察多币种持仓/挂单不被裁成空仓。逐单资金能力仍独立硬门槛，缺规格不发明金额/费用/档位或admission=true。该账户级并发语义尚待用户审查确认；不重问已批准的来源/鲜活性方向，也未依其修改runtime、订单、配置、权限、依赖或常量阻断。
- 本轮仅文档/证据收敛，采用相对链接/存在性与diff结构检查，无虚构RED或把旧测试称本轮新跑；242d36e代码、依赖和环境未变，沿用其适用回归。完整Goal保持active，详细预留协议审查不等于C5/C6/C7完成或任何真实I/O/候选授权。

### S3a 原生 instrument 允许字段来源（详细 CAS 协议仍待审）

- 从762ceb73abbec7638bd5043ec3ec409282ec5bc6与origin一致/clean继续；未收到对详细账户级串行协议的批准，未修改其pending状态。独立新增Trade/NativeInstrumentEvidence.py、tests/test_native_instrument_evidence.py及相应计划/README/审计/台账。旧source/schema/hash、金融/原订单状态机/default Engine、配置/规则/权限/依赖/候选均不改。
- API collect_native_instrument_evidence(exchange,codes,mode)只收1..64完整目标code；一次固定public GET：binance/binanceusdm fapiPublicGetExchangeInfo({})，OKX publicGetPublicInstruments(instType=SWAP)。读取前后实际public环境、SDK与边界代码，raw_rows允许字段重建完整执行metadata/原生state/active/raw_index，并保留SDK解释basis，不宣称其缺省contractSize是原生显式报告。当前无默认production调用，不接CAS，也不写库/订单/冻结。reader用对应credential-free SDK的纯parse_market及原_markets/_number/_raw验证，不复制大解析器或资金公式；核心import不导入可选SDK/Config，显式reader则需要SDK，缺失不降级。
- clock_kind=local_request_window_only、source_ms=None；exchangeInfo.serverTime/上架/到期/即将生效时间不冒充来源生成时钟。复核Binance官方fapi文档明确忽略该serverTime；OKX字段与纯parser核对使用官方定向内容和安装版SDK源码，未执行真实端点。精度digit先界于原_MONEY.Emax=100防SDK在覆盖filter前构造超长字符串；这是解析资源界，非新资金/年龄/容差/策略默认值。
- 最初缺模块出现在fixture setup（1 error），随后添加直接API测试并确认1 failed的真实缺API RED。首7项4 failed/3 passed，根因是新归一化把SDK的1.0写成1而旧Engine保留1.0；只改新投影的字符串保持方式，不放宽旧字节契约，7项通过。接着16真实RED证明目标池变异/缺tick-lot时SDK小数位数补值/ctType矛盾，12 RED证明币种推断覆盖及未投影numeric未校验，6 RED证明bool/int环境别名，6 RED证明state坏类型，12 RED证明分数毫秒/缺必要原条件字段；均最小修复在新模块，未改SDK或原helpers。
- 首适用组合1110 passed（195.79s）后主线程审查另加请求边界与错误envelope：6项证实路由在begin读时变更却仍调一次GET，4项证实Binance错误码+残留有效rows被接受，OKX对应2项已正确拒绝。前GET再次核环境、拒绝错误envelope后422全部通过（8.11s），保留这些失败证据，不将首次GREEN冒称最终版本接受。
- 新422参数化用例含binance/binanceusdm/OKX×live/testnet的两市场、cache投毒与原cache/options不变、原Engine逐字节投影、64目标恰界/65拒绝、raw/派生/重封/类型/缺重复symbol/单位/SDK/源码/路由/时间/输入变异、非交易状态保留、异常脱敏与无重试。fake最底层之外统一封住实际HTTP；无CEnv初始化/实际配置写入。约束/即将变更字段保存不等于所有平台规则已执行，active不等于新风险准入，两个flags=false。
- 最终CPython3.14.2/3.11.15各1122 passed（188.22s/188.25s），0failure/error/skip/warning；各422新来源＋700原市场/自采/联合当前性/核算/政策/订单单位用例，unique=1122且集合差异0。其余未变代码的242d36e两版1753pass/1既有skip等证据按原适用范围复用，不称本轮全仓重跑。两版compileall与diff通过；全程串行、活测试不编辑、主线程复核，无子代理/独立审计声明。
- JUnit：Temp/chanpy-native-instrument-final-py314-1f7fbe1aca35431e9afd59c55681e6df.xml SHA256 f83c603f5cd4e5ffb0f08bebdb16590350c721a49b6e24d582b8b842765019f1；py311为chanpy-native-instrument-final-py311-0c910867b4f34ab8ab50af78b1d5bc3e.xml SHA256 6bb1f512b0850a950e96ec8fa2f223f0f32bbde2c28f83b48c1e84b20eaa9586，Temp为C:\Users\yangj\AppData\Local\Temp。
- 仍缺新来源实际per-order/currentSDKcache/加载runtime/完整版本指纹/原CAS与默认全入口消费；独立source不替代逐单资金能力或详细预留协议。未经批准不实施账户级并发语义，不把可用汇总分摊/名义额÷杠杆/测试单PASS当资金锁，不改旧证明或自动解冻。所有candidate/testnet/live门禁及常量阻断保留；真实服务、SDK内部HTTP重试/容量、C7未认证，S3/C5/C6/C7和完整Goal未完成。
