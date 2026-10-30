# 限定管理：原关闭请求绑定与共享精度离线验收

日期：2026-10-31。基线 `full-version` / `dd9cc5e17a630028ed419c2d4f7431893912ec79` 加本轮工作树。依据[已批准限定管理规格](../specs/2026-10-30-native-existing-risk-management-design.md)及[串行实施计划](../plans/2026-10-30-native-existing-risk-management.md)，继续 C5/C6。本轮只完成原请求身份观察，不是动作 handle、管理 CAS、A/B 发送消费者、三 CLI 或 C5–C7 完成。

## 改动与复用

- `Trade/CCXTTradeEngine.py`：原 prepare 提取私有 `_quantized_order_terms`，共用 contractSize、原 SDK amount/price precision、向下数量限制与原 limits；普通入口原门禁、ticker fallback、float 精确重读保持。
- `Trade/NativePreparation.py`：该实际 helper 纳入原函数身份枚举，不新增 verifier 或跨调用缓存。
- `Trade/NativeManagement.py`：新增 `collect_native_management_close_request`，从原记录选择实际 attempt，沿完整区间自采及原 `_venue_params` / `create_order_request` 构造下一关闭请求，输出 source-v4；v2/v3 原诊断用途不变。
- `tests/test_native_management_request.py`：54 项。原 SQLite/history、原 SDK/precision，fake 仅底层 transport/时钟。其余为计划、台账和本报告。

关闭请求须原单确证终态且有可证实余量，活跃 open/close、请求量超原可用量、精度归零及原最小名义金额不足均拒绝。正向包含 Binance one-way/hedged × long/short 的普通限价、post-only、市价；原方向/leg、client ID、实际精度数量与 wire 字段逐项绑定。one-way 保留 reduceOnly，hedged 不硬塞它。没有调用 create_order 或写 HTTP，JSON/`operation_authorized=false` 不是发送许可，`native_quantity_verified` 仍 false。

市价取原 NativeLastPrice V2，Last 年龄/跨度显式提供，不用 cached ticker 或 caller quote；限价不多采 Last。夹具将 raw fake Last 明确设为 300，使 0.019 请求满足原最小名义金额；没有 close 豁免。沿本次已验证 account 原 Symbol Config 的杠杆/保证金设置并独立 GET mode，不把设置当数量证明。

同次仍核原 Engine/SDK/Session/request、SQLite owner、全 ledger、known sources、实际函数/导入别名及 Entry；回调晚变须在下一实际 callable 前拒绝。最终 Last decoder/owner 工作移到统一 UTC/monotonic 尾采样之前，之后重核 Last 原交易时间年龄和独立单调年龄/跨度，不能用宽 Last/total 预算遮住窄 wallet/execution 预算。

原 GET 可追加它本来允许的已验证终态观察，不猜补累计成交、不建 intent/claim。简化为共享原单位/精度算术，没有第二 sender/Engine/财务状态机、新依赖/表/账本/第三 hook 或实际配置修改。

## TDD、诊断与原件（不叠加成绩）

原件根 `C:/chanpy/verification/native-management-request-20261030/`。独立审计清点 14 份中间 JUnit，完整路径/raw SHA/真实状态与秒数见 `request-independent-audit.json`。主要 RED 如下：

| 原件 | 真实 XML 结果 / 原因 | SHA256 |
|---|---|---|
| request-red-420b985fec3f422782d0a66129073a24.xml | 3 failure，缺新入口 | 22bb43b0f2a2e8a1c47a36390ca868da397726077d8a29ecd51769faf04a41f5 |
| request-first-9ecfa0996fb448f3b0e3d9170b1f1392.xml | 1 passed/2 failure；暖测试误要求零终态观察写入，冷 owner 拒绝 SDK cache 晚变 | 6992cf9299e771dceb86a961be46eb1293d4d916da1cc3dc3fcd7d94ce0a743c |
| request-cold-fix-db366c23b6744dbb8d7b8ebbbd74e041.xml | 1 passed/2 failure；自己的 Decimal/Fraction 类型误用 | 77b58bc8291937e78c1aeae168d3944a8aab8782d56afb82b152282c2ed19142 |
| request-last-red-a1634fd115364ceda183b2e947143a61.xml | 12 passed/1 failure；Last decoder 的51ms未计入wallet 50ms尾预算 | c110d5e6a867b608070a9e9738300d7fa5422e39f97f1d4bb9ed27d276dd08a8 |
| request-last-age-red-dc1380c6a46248cdbb71407fcbc404b9.xml | 1 failure；Last 原年龄1950ms，尾部再增60ms仍未按2000ms重核 | c233c783a95ec5a35bf1e8040a4ee246c139d0fe9a21253ce906b8d1e7d7b73c |
| request-alias-red-3f39562ff4c1421cb32135e33d4e245c.xml | 6 failure；实际 Last 导入别名未拒绝 | 779654333402696989ab7b8b097ab3e8cdfe08d224e9a531de9a7393f1d3ddbe |
| request-flags-red-7e9bb7f6f56a4a4a9998d5f99b63c7b3.xml | 3 failure；缺 full interval 产生 UnboundLocalError，两个整数flag被接受 | 084e0b21a8fa0f35e10db34e9bac7cbbd42c58ee3caa351c088faae1f3eb5377 |

两个外部 diagnostic pass 只证明当时拒绝/定位，不是功能 GREEN。cache diagnostic 明确抓到 cold fetch_leverage 将 options.leverageBrackets 从 None 填入 TEST/ALT 档位；未加缓存白名单、预热或改 SDK，改用当前已验证 account 原设置并独立 GET mode。修复中的 Decimal 整数检查纠正为原 Decimal 精确判定，不归咎平台。

暖测试初始假设也实证纠正：原 GET 合法追加一条 verified terminal observation。最终要求 records、identity、原 event 前缀、其他记录及 transition 不变，只准本记录准确增加该原观察，state/raw 原单一致；不是删失败或允许任意 DB 增量。

后续 3、17、28、26、29 项各自 GREEN 有原件，不相加：含12个cold请求、11个SDK/SQL前输入拒绝、三类晚callable、九新增依赖、六别名、三私有flag。中间集合重叠/选择性deselected不作终验清单。64份原工具副本在 `request-intermediate-tool-results.json`，unavailable=0；CLI退出码与focused deselected不从XML反推，旧failure不抹掉。

## 中断恢复

首个3.11句柄62803消失，两次系统观察无Python/pytest/uv，原XML/result缺失；终止原因/退出码未知。110个partial通过仅精确日志前缀，计入终验为0。原17458字节stdout SHA `283a6e51f1f52ba880b6f6ec746b16d8e7b012a480a9f44e0a1948e7c14d90c1`，args SHA `2041decde19d51fdb61986464c1f8dff9361ad1adc577cfbeb2a4068aea3330e`。

无活任务后，仅started原字节可逆归档为 `request-py311.interrupted-20261030T191322Z.started.json`，SHA `efdf8dea65c1e5857b23bffd9ef794340640b3bd335af8cc36fe0f205f5397ad`；原args/stdout/basetemp保留，无删除。观察 `request-interruption-20261030T191322Z.json` SHA `4632f16cd73ff6f5c05feee65ad5afaf374d6c4dbd8e4600877eb55c873c4ce6`，归档工具54d704 exit0。用未改verifier和同一731节点全量重跑至新GUID，不混partial，不重复已完整接受且身份未变的3.14。

## 双版终态与独立审计

两版实际collection顺序相同，17完整模块/731唯一节点，原 `-m not network`。`request-selection.json` raw SHA `5985f2c13fb7cfc285bbf8f64a739b0f169d9ca797fae1c3cd937f815b517596`。3.14 accepted后才运行3.11；活测试期间无文件编辑、编译、并发pytest、跳过/重启慢例，中断确证后才恢复。

| 环境 | pytest / XML / controller 秒 | 原JUnit / SHA256 |
|---|---|---|
| CPython3.14.2 | 7625.62 / 7625.388 / 7628.971576 | request-acceptance-py314-8b8bf2a3d90e451b84cddc9e171790da.xml / 4acabe1d00f0a36245a3d25fe6d5119f9405777a144ed61e53e7b93c33f1576f |
| CPython3.11.15完整恢复运行 | 8504.41 / 8504.141 / 8508.203000 | request-acceptance-py311-8198072c00be47aa96be90ed19ffb407.xml / 030892f54aea5426ed549f8044119b40414a0104acd91d505bf89c100f5497b8 |

各730 passed/1原有skip/0failure/error/0测试warning，自然exit0；原终态工具deb9f6/bcf22b。唯一skip仍是 `isolated_channel-position_cash_channel_unallocated-binance`，原因 `Binance income has no isolated position cash channel`，不是新skip或PASS。完整node/state逐项相同，canonical ordered case-state SHA `a5c11731370622bfc86faa64f982c09cc90f4bcc15f6f133b059ddc8993408a5`。

完整模块：request54、interval52、sources17、attempts8、quantity27、identity12、role39、account_reconciliation52、execution_ownership38、native_pending_ownership95、order_audit_history35、query_only_runtime50、sdk_route_snapshot17、crypto_order_contract36、native_monetary_engine76、native_monetary_sdk90、native_monetary_http_boundary33。不把旧7405/478/254/442重标当前全仓重跑。

Trade递归py + tests顶层py的188文件raw map前后相同，canonical map SHA `4339b35d337b0d98131b713598da65054af68cf46e95dc0fee9df1642ada00c4`。3.14/70包、3.11/71包实际metadata、前缀/user-site、解释器/pyvenv匹配原清单；freeze SHA各 `6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`、`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`。requirements未改，pytest.ini当前内容匹配父HEAD blob，无安装/更新依赖。

runner `verify_request_binding.py` SHA `81d92be4b5e5ebbcfc6b699acdace2002e71f0b710221acd972e4ec921f800d4`；result raw SHA为3.14 `a641ceedaa3541eb1d507301f79e4b53d4dc775c6cf633259fb6a462a22629b9`、3.11 `12625be080f7742ac6c1ce2b52a5d1d77593720acf42ae48dac6042ef585971d`。

新 `audit_request_binding.py` SHA `1aae5756b4cdd7f898ad8e5ea0b4f2a8fe5d82c9a04b0e20da5a2d6cce9ea163`，只复用原 `verify_recovery.py` 纯reader（SHA `46511317a42b6da4d3f2c1d995e7d5b8c1d77962944cdd34f8070b23ab1b7040`），不改旧证明/调用旧build/run。重读canonical封装、实际退出码、raw XML/log/args、suite数、精确成员顺序/状态/无重复、skip、前后source/真实环境、64工具副本与中断保留；17模块逐项对冻结数。ba2e5e exit0，`request-independent-audit.json` SHA `46c6b49de340264b2490129d2b397c19108bc203002dc53aba2191256e43c251`。

无活任务后双版四改动py compileall exit0；实际optional-free 3.14/34包、3.11/35包投影中11可选包真实缺失，stdlib ssl后先阻断全部socket/DNS，再导入当前SafetyPolicy/Engine/NativePreparation/NativeManagement，均exit0/network_attempts=0，四源SHA匹配验收map。复用未改 `route_core_imports.py`，不冒称无SDK的交易执行证明。辅助原工具 `request-current-auxiliary-tools.json` SHA `a5a81400204ffe48daa064a380d4c6d4d3cf8df90ada48848441418967282bd0`。diff检查通过，Git既有LF/CRLF提示不混称测试warning。

## Review、交付及未完成

按显式solo规则主线程复核原prepare前后门禁/float重读、v2/v3/v4共用主体、原GET副作用、ledger/known-source尾核、新别名/Entry、Last双时钟尾与四模式原wire，未发现阻断本观察子步的已证实问题。保留中间断言错误、类型误用及失败原件，不扩大为整个依赖栈或任意Python进程沙箱。

[USDⓈ-M官方下单字段说明](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/trade)与本轮hedge positionSide/reduceOnly形状一致；只支持字段约束，不证明任意竞态下服务器只关闭、必接单或锁仓。旧单页超时后的Portfolio Margin搜索结果未替代此证明。本轮无实际账户/交易端点；真实CPU/网络预算、全原生通道原子完整性、hedge服务器关闭约束及C7仍须独立证据。

下一步是当前调用不可转交动作handle、原CAS/OrderAudit版本化账户占用、未知不释放、原A/B两位置及三CLI/fresh-worker；不能用JSON或永久全拒绝替代批准最终能力。OKX同等级、候选换代/旧证明迁移、完整C5/C6/C7未完成。实际配置/凭据/资金、candidate/testnet/live和研究门禁不变，整个Goal active。

验收对应父HEAD dd9cc5e加本次明确源码，Lore/普通push与远端完整SHA以实际Git核实为准，不因提交声称在新HEAD重跑本清单。
