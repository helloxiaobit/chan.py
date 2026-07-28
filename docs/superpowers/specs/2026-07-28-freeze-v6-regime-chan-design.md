# freeze-v6 BTC 单币种策略研究设计

日期：2026-07-28
状态：用户授权自主冻结并执行

## 1. 目标与结论边界

在不读取任何 `2026-01-01` 及之后策略结果的前提下，研究 BTC/USDT
单币种候选 `freeze_v6_regime_chan_v1`。正式研究口径保持
`conservative-v2`，目标为 2021–2025 全期：

- CAGR 严格大于 50%；
- Calmar 严格大于 2.0；
- 最大回撤严格小于 25%；
- A（2021–2023）、B（2024）、C（2025）三个分段 CAGR 均大于 0。

通过上述门槛只形成 IS 研究收据，不形成测试网、实盘或 OOS 授权。2026 OOS
继续封存；不得用 OOS 结果选择策略、参数或风险档位。

## 2. 研究原则

- 单币种：只研究 BTC/USDT。
- 现货约束：仅做多、最大 1x 暴露、最大一个仓位，不做空、不使用永续资金费收益。
- 不改变执行语义：逐根盯市、同柱不利顺序、maker 必须触价、maker/taker
  费用、止损滑点和缺失行情策略均沿用 `conservative-v2`。
- 不以统计口径达标：CAGR、最大回撤和 Calmar 使用现有冻结实现；旧基线不得覆盖。
- 不无界搜索：最多评估 24 个预登记参数组合，研究开始后不得扩网追逐全期指标。
- 不新增第三方依赖：复用仓库现有数据、指标和研究框架。
- 所有结果包含配置哈希、输入哈希、Git provenance、数据边界和有序门禁。

## 3. 候选路线

选择“缠论结构信号 + 多时间框架趋势状态 + 波动率风控”。它复用已经审计的
S1bz/S2py10 交易源，但只保留多头机会；日线负责主趋势，4H 负责趋势强度和
入场确认，ATR 与账户回撤负责退出和降风险。

未选择纯突破，因为震荡期假突破会显著增加 `conservative-v2` 下的回撤和
手续费；未选择纯均值回归，因为 BTC 长周期下跌状态中的接飞刀风险与 50% CAGR
目标冲突。

## 4. 策略规格

```yaml
Strategy:
  id: freeze_v6_regime_chan_v1
  core_logic: >
    只在 BTC 中长期上升状态中执行缠论多级别多头信号，用趋势强度和成交量
    确认入场，通过 ATR 跟踪止损、趋势失效退出和账户回撤降仓保护 Calmar。

Data:
  primary_symbol: BTC/USDT
  timeframe: 4h
  window:
    begin: 2021-01-01
    end_exclusive: 2026-01-01
  splits:
    A_train: 2021-01-01..2024-01-01
    B_validation: 2024-01-01..2025-01-01
    C_final_is: 2025-01-01..2026-01-01
  sealed_oos:
    begin: 2026-01-01
    status: unopened
  indicators:
    Chan: [S1bz_long, S2py10_long]
    EMA_daily: {period: 50, slope_lookback: 20}
    EMA_4h: {periods: [50, 200]}
    ADX_4h: {period: 14}
    RSI_4h: {period: 14}
    ATR_4h: {period: 14}
    Volume_SMA_4h: {period: 20}

Signal:
  entry_all:
    - S1bz_long OR S2py10_long
    - daily_close > daily_EMA50
    - daily_EMA50_slope_20 > 0
    - EMA50_4h > EMA200_4h
    - ADX14_4h >= adx_threshold
    - 45 <= RSI14_4h <= 75
    - volume_ratio_4h >= volume_ratio_threshold
  exit_any:
    - reverse_bsp
    - EMA50_4h trend loss confirmed for two bars
    - ATR trailing stop
    - hard stop
    - 30-day time stop without a new high
  schedule: every 4h
  warmup_policy: no signal until every required rolling value is causal and complete

Capital:
  initial_equity: 10000
  exposure:
    base_pct: 50
    strong_conviction_pct: 75
    maximum_pct: 100
  position_sizing: >
    min(conviction exposure cap, conviction risk budget / initial stop distance)
  max_positions: 1

Risk:
  base_risk_budget_pct: 4
  conviction:
    bs_type_1_mult: 1.0
    bs_type_1p_mult: 1.5
    other_stack_long_already_active_mult: 1.5
    mult_cap: 2.0
  effective_risk_budget: base risk budget * conviction multiplier
  atr_stop_multiplier_grid: [2.5, 3.0, 3.5]
  initial_stop: clamp(ATR multiplier distance, 8%, 12%)
  drawdown_de_risk:
    10pct: max_exposure_75pct
    15pct: max_exposure_50pct
    20pct: close_and_cooldown
  reject_at_drawdown_pct: 25

Execution:
  model: conservative-v2
  leverage: 1x
  position_side: long_only
  same_bar_policy: adverse_first
  maker_fee: 0.0002
  taker_fee: 0.0005
  stop_slippage: 0.0005
```

`other_stack_long_already_active` 按已审计来源交易的时间窗口判定：同一时间戳
先平后开；新信号成交时，另一信号栈至少一笔多头来源交易尚未到达其审计退出
时间才算共振。先过滤空头，再计算该乘数，避免空头来源改变现货仓位预算。

## 5. 预登记搜索预算

只允许下列离散维度，总评估数不得超过 24：

- `adx_threshold`: 18、22；
- `volume_ratio_threshold`: 0.8、1.0；
- `atr_stop_multiplier`: 2.5、3.0、3.5；
- `entry_source`: `S1_ONLY`、`S1_OR_S2`。

组合上限为 `2 × 2 × 3 × 2 = 24`。EMA 周期、RSI 区间、时间止损、回撤
降风险、费用和仓位规则不参与搜索。任何组合缺少所需的历史真 K 线时都记为无效，不回退到
更乐观的成交假设。

## 6. 串行研究协议

1. 锁定 v5 与 BTC 现货买入持有基线，证明指标定义和 2026 防护未漂移。
2. 用合成数据测试指标的因果性、时间对齐、长仓过滤、仓位上限、退出顺序和
   回撤降风险。
3. 仅在 A 段运行最多 24 个组合，按 Calmar 优先、CAGR 次优排序；没有组合可因
   全期结果补充或修改参数。
4. 将 A 段前 3 名在 B 段验证；只保留 B 段盈利、回撤低于 25%、Calmar 为正且
   至少一个单维相邻参数组合同样盈利的候选。
5. 最多一个候选在 C 段执行一次最终 IS 验证。
6. 用冻结参数重放 2021–2025 全期，依次检查 CAGR、Calmar、最大回撤和分段门槛。
7. 输出 `is-candidate`、`rejected` 或 `insufficient-data` 收据；始终保持 OOS 未打开。

若没有候选达到硬门槛，报告最优诚实结果和失败分解，不扩大搜索空间、不改变
成本假设、不读取 OOS。后续新研究必须使用新的策略编号和新的预登记设计。

## 7. 测试与验收

- 配置精确键、参数集合、24 次预算和半开时间窗口均由测试约束。
- 指标只使用决策时点已完成 K 线，禁止未来数据和跨段状态泄漏。
- 现货模式拒绝空头、超过 100% 暴露、资金费收益或杠杆大于 1。
- 研究 CLI 不提供 OOS 参数；输入清单遇到 2026 时间戳立即失败。
- 结果参考可字节或语义稳定重建，报告数字由冻结 JSON 一致性测试约束。
- 完成前运行聚焦测试、全部离线测试、编译检查、差异检查和凭据/大文件审计。

## 8. 停止条件

满足全部硬门槛即停止搜索并冻结收据。达到搜索预算、数据不足或所有候选失败时
同样停止，并保留拒绝证据。任何情况下都不自动打开 2026 OOS、测试网或实盘。
