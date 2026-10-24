# 原prepare活上下文内的Last采集

日期：2026-10-25，基线e623ea73225d52dfa1d57563cba9122eeaf4e239。继续原[完整金额接入计划](2026-10-24-binance-capacity-v1-integration.md)第4步必需的来源绑定。起草及本来源实施时[费用适用选择](../specs/2026-10-25-binance-standard-fee-applicability-choice.md)仍待批；本来源工作没有增加费用假设。用户随后已明确批准F，当前后续实施见[批准后的接入计划](2026-10-25-approved-standard-commission-integration.md)，不再将F视为待选。

## 范围与接口

在原 `Trade/NativePreparedIntent.py` 添加 `collect_prepared_binance_last_prices(engine, context, *, max_age_ms, max_observation_span_ms)`，复用原 `NativePreparation._PREPARED` 与原活句柄/owned read-view复核、原 `NativeInstrumentCurrent._cache_view`、原Last V2 collector/reader。只从原context身份的scope获取完整codes，从原Engine缓存提units，不接受caller markets/source/clock/receipt/PASS，不重做prepare、不写intent/claim/新表/绑定schema，也不把结果添加到已落库旧绑定。

固定原Engine/chan/DB/connection/table/SDK及registry entry（仅未绑定3项entry）。每次可能回调后先复核owner再查询；原prepare局部视图在原owned事务内复核，GET全部在事务外。采集前后须为同一实际scope/cache/client/配置/记录，返回原Last schema与原false flags，不创造可转让采集许可。被复制/重建/其他Engine/已落intent/已绑定的context拒绝。失败只抛原脱敏异常，不能谎称冻结未知库或改写外部变化。

时间预算必填typed非负int，local/native年龄沿Last原窗口，不续期旧源。末尾业务clock先于最后上下文/SDK/输入复核，核心monotonic向上整毫秒包含owned退出和终末核验成本。禁止改实际配置、候选、依赖、规则或触发真实I/O。后续完整funding acquire必须在自身控制流直接调用该helper、固定返回源与原CAS；本helper/JSON本身无资金/claim/default权。

## 验收

严格TDD，实际原prepare+原SDK路径、底层fake运输；全scope两币V2 GET，无写锁/新prepare/订单/账本写入。四种mode/方向，LIMIT与真正MARKET None；源/市场/SDK/上下文拒绝、弱引用生命周期、每次回调owner/记录/配置/SDK晚变异与末尾耗时。原source/上下文/CAS适用回归双版串行，独立GUID/JUnit、无活pytest编辑、compileall/diff、主线程review、Lore/普通push；全资金/执行/C7验收仍独立保留。

## 2026-10-25实施证据

本来源子层已实现；不是完整金额/CAS接入。原scope顺序与Last按ID排序不同，复用Last现有markets规范化，不能因同池排序不同误拒绝。view先核代码/原cache，再在原owned事务内重核原上下文，退出后核原owner/完整SDK；固定原opening guard、policy及guard时钟，防止末尾投影/代码检查/事务退出留下变异。末尾monotonic上界不延长源年龄。没有新registry、绑定schema、表、资金或claim权，原v2/v3路径不增加Last请求。

8项缺API RED、5项终末代码检查RED、7项cache/owner RED均真实观察；一次事务耗时测试误注入到内层退出，保留失败并改为只计最外层退出，未冒称生产漏洞。新增79项；CPython3.14.2/3.11.15同范围各522 passed、9 deselected、0failure/error/skip/warnings，唯一集合一致。范围为79新＋366原Last＋76原capacity prepare/CAS/current＋1无配置导入；9个冷启动专用用例不在本轮范围。源码/测试摘要跨双版不变，双版compileall及diff通过；详细JUnit与RED身份见[台账](../reports/2026-10-20-crypto-full-version-progress.md)。主线程review，无子代理/并发/真实I/O。

后续完整资金acquire仍必须直接控制该helper的调用与返回来源，并在原L0/L1/L2及全部消费者复验。费用适用性F现已单独获批，不是由A/P或本来源通过推定；后续已接原available到条件Cost的只读计算，尚未接完整金额CAS/全部消费者。原配置/交易门禁不改，旧源不重封，C5–C7与整个Goal未完成；本段522项属于原来源提交的验证范围，不改称本批金额路径的验收。
