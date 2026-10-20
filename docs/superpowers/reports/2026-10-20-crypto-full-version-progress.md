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
| LGBM/MLP | `ModelStrategy/models/lightGBM`、`deepModel` | M3 小样本训练 | 现阶段仅离线，不声明默认在线部署 |
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
| C2 | 进行中 | 先固定父 K 最终值变异、发布边界和 prefix/suffix 决策快照测试 |
| C3 | 待开发 | 时序切分/标签/meta/部署 |
| C4 | 待开发 | 账户评估/AutoML 产物 |
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
