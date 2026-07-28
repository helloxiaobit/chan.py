# chan.py 五阶段最终验收与实盘前检查表

## 发布决定

**research/dry-run accepted; testnet/live not approved**

本报告只批准研究复现和离线 dry-run。它不是测试网或实盘授权，不创建
`status=candidate` 收据，也不代表策略已达到目标。当前真实交易必须保持锁定。

## 冻结结论

| 项目 | 冻结值 |
|---|---:|
| 数据窗口 | 半开区间 `2021-01-01` 至 `2026-01-01` |
| 执行口径 | `conservative-v2` |
| 策略 | `freeze_v5_candidate_v1` |
| 选择风险 | `0.005` |
| BTC CAGR | `31.957%` |
| BTC 最大回撤 | `19.807%` |
| BTC Calmar | `1.613` |
| BTC 门槛 | `Calmar >= 2.0` |
| 状态 | `rejected`（`btc_full_calmar`） |

BTC 门失败后流程按预登记规则停止。ETH、SOL、BNB、共享组合和 OOS 层均未
打开；本轮没有生成或读取新的 2026 OOS 结果。冻结依据：

- `ModelStrategy/research/configs/freeze_v5_candidate_v1.json`
- `ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json`
- v5 spec hash:
  `ddf429b93fa67110bb8c80b544d746cb7c1c07215807c62a4311bd03a9dd2dfb`

## 五阶段证据链

1. 研究工程化：版本化规范、schema、输入清单、哈希和 OOS 边界已进入仓库；
   外置大型数据保持只读且不入 Git。
2. 回测可信度：freeze-v4 在 UTC 校正 `conservative-v2` 下为 risk 0.005、
   CAGR 30.076%、回撤 20.733%、Calmar 1.451；历史时间错位结果已失效。
3. v5 重认证：BTC IS 为 31.957% / 19.807% / 1.613，门槛失败并冻结为
   `rejected`，未继续稳健性、组合或 OOS 层。
4. 实盘安全：显式 `dry_run | testnet | live`、候选收据门禁、逐单 kill
   switch、真实累计成交状态机、客户端订单号恢复、撤单确认后剩余量重试已完成；
   离线 SQLite 验收禁止创建交易所会话。
5. 最终验收：文档数字由冻结 JSON 测试约束；最终参考复现、完整离线回归、
   编译与独立审查结果记录在下文。

## 可复现命令

外置根目录在运行时显式传入，必须位于仓库外且只读；本报告不保存个人绝对路径。

```powershell
$env:RESEARCH_ROOT = "<external-research-root>"
$env:MARKET_DATA_ROOT = "<external-market-data-root>"

python -m ModelStrategy.research.cli baseline --spec ModelStrategy/research/configs/freeze_v4_legacy_v1.json --research-root $env:RESEARCH_ROOT --reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json --output backtest_output/research/final-freeze-v4-legacy.json

python -m ModelStrategy.research.cli compare --spec ModelStrategy/research/configs/freeze_v4_conservative_v2.json --research-root $env:RESEARCH_ROOT --market-data-root $env:MARKET_DATA_ROOT --legacy-reference ModelStrategy/research/baselines/freeze_v4_legacy_v1.json --conservative-reference ModelStrategy/research/baselines/freeze_v4_conservative_v2.json --output backtest_output/research/final-freeze-v4-conservative.json

python -m ModelStrategy.research.cli certify-v5-btc-is --spec ModelStrategy/research/configs/freeze_v5_candidate_v1.json --research-root $env:RESEARCH_ROOT --market-data-root $env:MARKET_DATA_ROOT --freeze-v4-reference ModelStrategy/research/baselines/freeze_v4_conservative_v2.json --candidate-reference ModelStrategy/research/baselines/freeze_v5_candidate_v1_is.json --output backtest_output/research/final-freeze-v5-btc-is.json

pytest tests/test_final_acceptance.py tests/research tests/test_trade_safety.py tests/test_trade_state_machine.py tests/test_m6_trade.py -q
pytest -m "not network" -q
python -m compileall -q Common Config DataAPI Trade ModelStrategy tests
git diff --check
```

## 验收环境与结果

- OS：Windows；时区：Asia/Shanghai；Python 3.14（仓库最低目标仍为 3.11+）。
- Stage 4 合入前完整离线回归：284 passed、7 skipped、1 deselected。
- 唯一已知测试警告：xgboost 3.1+ 弃用 libsvm 文本 URI 输入；不影响本轮结论。
- Stage 5 clean-commit 参考复现与最终测试结果：完成后在本节追加。
- 所有研究命令只允许查询 `2026-01-01` 之前的正式 IS 输入；输出目录已被
  Git 忽略，不作为新的冻结参考提交。

## 已知限制与剩余风险

- 尚未对 Binance、OKX 等交易所逐一验证 sandbox 端点、市场映射、最小数量、
  精度和限频；沙盒启用失败会 fail closed。
- `clientOrderId` 历史查询窗口、分页、最终一致性及交易所断线语义仍需测试网证据。
- post-only、reduce-only、`positionSide`、单向/双向持仓和杠杆参数存在交易所差异。
- MySQL 新建 schema 已静态校验，但旧库在线迁移和故障切换尚未在真实实例演练。
- Futu 是可选接口，不属于本轮加密货币测试网认证范围。
- 当前没有通过认证的策略；即使交易层安全测试通过，也没有可部署标的。

## 测试网外部检查表（全部完成前不得启用）

- [ ] 新策略按同一规范获得真实 `status=candidate` 收据，编号和 spec hash 与配置一致。
- [ ] 使用独立测试网 API 凭据；关闭提币权限，限制 IP，不在日志或仓库保存密钥。
- [ ] 证明 `set_sandbox_mode(True)` 成功且 REST/订单查询均指向测试端点。
- [ ] 对每个交易所/市场验证 symbol、精度、最小数量、post-only、reduce-only、
  `positionSide`、杠杆和单向/双向模式。
- [ ] 演练零成交、部分成交、撤单竞态、订单拒绝、超时、限频、断线和进程重启。
- [ ] 证明按交易所订单号和客户端订单号恢复不会重复下单或重复累计成交。
- [ ] 验证 `CHANPY_KILL_SWITCH=1` 在下一张订单前生效，并保留取消/只读对账能力。
- [ ] 连续运行观察期内，数据库仓位、交易所仓位、余额、费用和资金费逐笔一致。

测试网仅在进程内显式设置 `CHANPY_ENABLE_TESTNET=YES`；没有该值时必须拒绝。

## 实盘独立检查表（测试网通过也不会自动授权）

- [ ] 测试网证据由人工复核并签署，所有交易所差异和已知限制已有处置方案。
- [ ] 重新确认 candidate 收据、Git 提交、配置 hash、数据截止日和风险上限完全一致。
- [ ] 设置账户级最大损失、单笔/总杠杆、并发、熔断、告警和人工停机流程。
- [ ] 完成数据库备份恢复、时钟同步、网络中断、凭据轮换和事故响应演练。
- [ ] 首次仅使用可承受损失的小额资金，并有独立仓位/余额对账监控。
- [ ] 由账户所有者在运行时单独设置
  `CHANPY_LIVE_TRADING_UNLOCK=I_ACCEPT_REAL_ORDERS`；不得写入配置文件或脚本。

任何时候设置 `CHANPY_KILL_SWITCH=1` 都必须阻止新的非 dry-run 订单。上述清单
未全部完成且未产生新的人工授权前，`mode` 保持 `dry_run`。
