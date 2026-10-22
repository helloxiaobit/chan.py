# C6 Python 安装矩阵验收

范围：批准计划第 9 节的 Python 3.11 与当前运行版本、核心/完整声明依赖安装。起始代码 `37bc07504f47e7c3e4774ddd428660ee06ab949f`；股票、MySQL/Futu/COS 可选后端暂不因此认证，C5/C6/C7 整体仍未完成。

## 实施与边界

- 使用已安装 CPython 3.11.15 和 3.14.2，逐个创建独立临时 venv；不激活或修改全局 Python，不使用 system-site-packages，不修改 requirements/用户配置/规则/权限。
- 实际声明位于 `Script/requirements.txt` 和 `Script/requirements_full.txt`，不存在根目录 requirements-core/dev 文件。只安装这些文件及其解析出的依赖；不引入新用途的依赖。
- 用已安装 uv，忽略其配置文件、明确公开 PyPI 与关闭 keyring，清除当前安装子进程的额外 index/find-links 继承；先尝试 wheel-only，避免静默源代码构建。包下载不是行情/账户/通知 I/O。
- 核心环境先验证声明包导入、真实已收盘合成 CChan/API 和可选包确实缺失；不安装 pytest 来冒充最小核心。随后同一隔离环境升级到完整声明依赖，执行真实离线测试，按新 basetemp 严格串行，活进程期间不编辑源码/测试/文档。
- 检查环境前缀、user-site、依赖一致性、实际版本与运行结果。保留真实失败，不能把安装失败或跳过改称成功，也不能用核心 smoke 替代完整依赖结果。
- 全程不读实际交易密钥、不连接行情/私有账户/通知，不执行冻结研究、正式搜索或绩效读取。若只是验证通过则仅提交证据；若发现行为缺陷，先观察相关 RED 再最小修复并重新验证。

## 当前矩阵

| Python | 核心声明依赖 | 完整声明依赖 |
|---|---|---|
| CPython 3.11.15 | 安装/导入/合成结构与 API/pip check 通过；35 包 | 安装/导入/pip check 通过；71 包；1581 passed / 8 skipped / 1 deselected / 18 warnings，829.95s |
| CPython 3.14.2 | 安装/导入/合成结构与 API/pip check 通过；34 包 | 安装/导入/pip check 通过；70 包；1581 passed / 8 skipped / 1 deselected / 18 warnings，765.70s |

本次四单元均已通过。既有 optional-free smoke 和全局 3.14 环境回归仅作为历史基线，没有拿来代替本报告的干净安装结果；本轮业务源码、测试和 requirements 均未修改。

## 当前证据

- 两个 venv 均确认 `sys.prefix != sys.base_prefix`、user-site=false；核心阶段 yaml/pytest/ccxt/sklearn/xgboost/lightgbm/optuna 七项实际 find_spec 均为 false，不使用 import mock 冒充包缺失。六个基础声明包逐个真实导入，CChan/FeatureEngine/PaperState/运行壳/阶段入口的核心导入通过。
- 核心功能使用 96 根固定整数形状、明确 UTC/source 的合成小时 K，执行真实 trigger_load 与 v2 导出，核对条数/结束时钟/非空笔和完整 canonical payload SHA。Python socket connect/DNS 路径在此 smoke 内主动禁止；不读用户配置，不训练模型或读取历史策略输出。
- 两个核心单元及 3.11 完整依赖阶段的该 fixture API payload SHA 均为 `05860e040f5f4d29059d1a7fe421f9282804bf4b09663a3179ca531dd3b65a64`；只证明该固定 smoke，不外推为所有理论结构/策略一致或外部认证。
- 核心解析版本：baostock 0.9.4、IPython 9.17.1、matplotlib 3.11.2、pandas 3.0.6、requests 2.34.2；3.11 使用 NumPy 2.4.6/contourpy 1.3.3，3.14 使用 NumPy 2.5.4/contourpy 1.4.0。35/34 包差异也包含 3.11 的 typing_extensions。`uv pip check` 均明确 exit=0。
- 3.11 完整阶段：PyYAML 6.0.3、pytest 9.1.1、CCXT 4.5.89、scikit-learn 1.9.1、XGBoost 3.2.0、LightGBM 4.7.0、Optuna 5.0.0、SciPy 1.17.1，合计 71 包。升级中 resolver 将 charset-normalizer 3.5.2→3.4.7、idna 3.20→3.18；这是声明依赖的闭合解析，不是 ad hoc pin 或全局环境修改。完整七个可选模块真实导入通过。
- 首次安装命令在包安装之前因空 `UV_CONFIG_FILE` 被 uv CLI 拒绝；PowerShell Process 环境赋 null 在该调用中留下空值。改为只从安装子进程的 Env: 删除已列明 index/config 继承项后通过；没有安装失败被记为 PASS，也没有改用户配置。
- 声明输入 SHA256：`Script/requirements.txt`=`4320078f59de5d7b9edcdee19890af1ee9a8d6271679fbdf6cd27d0c14669841`；`Script/requirements_full.txt`=`045d3f8de451efbe07fc30a349d1b31283ee400b6070f9afba10cd0bfc9c275d`。
- 首次 3.11 完整测试曾观察至 86% 无失败；后续轮询明确返回 Unknown process id 95559，实际进程检查也无 Python 活进程，但最终退出结果未取得。该轮不计 PASS，不以临时目录时间或进度条代替终态。确认停止后在新 basetemp 重跑并输出 JUnit XML 以保留可核验终局证据；不因单次观察超时而并发重启。
- 3.11 复验命令：隔离解释器执行 `-m pytest tests -m 'not network' --basetemp <new-temp>/pytest311-full-reverified --junitxml <new-temp>/pytest311-full-result.xml -q --tb=short -p no:cacheprovider`；明确终态 exit=0，1581 passed / 8 skipped / 1 deselected / 18 warnings，829.95s。运行全程无源码/测试/文档编辑。警告均为小样本 AUC、MLP 未收敛和 LibSVM 文本弃用，没有隐藏或因换环境放宽用例。
- 3.11 JUnit 独立读取确认 tests=1589、failures=0、errors=0、skipped=8，实际 testcase 节点 1589；XML SHA256=`728e2a261e00e6cb7294a40067bae22618ca42eb3d87e4f279cc1b7c2e904d59`。deselected=1 由终端 pytest 汇总确认，不从 XML 推造。
- 3.14 完整阶段使用 XGBoost 3.4.1、SciPy 1.18.1、NumPy 2.5.4/contourpy 1.4.0；其余直接声明库版本与上列 3.11 相同。70 包（3.11 的 coincurve 在此环境没有安装），真实导入和 `uv pip check` exit=0；同 96 根 fixture 的 API SHA 不变。不同解析版本必须各自跑完整测试，不用核心一致性代替模型/账户/脚本验收。
- 3.14 完整测试使用同一命令结构及独立 pytest314-full basetemp/JUnit，明确终态 exit=0，1581 passed / 8 skipped / 1 deselected / 18 warnings，765.70s。100% 输出后仍等到真实进程退出才补本记录。JUnit 独立读取 tests=1589、failures=0、errors=0、skipped=8、1589 个 testcase，XML SHA256=`0e426d627bff023eff2704c47d3ef437d9606c0d376f150438c0b8d386d167fe`。两个环境测试期间均无源码/测试/文档编辑、没有并发长任务。
- 八项 skip 的实际原因一致：六项需要外部正式研究/市场输入（未提供、未执行），一项未安装可选 PyQt6，另一项 Binance income 缺 isolated position cash channel。不是忽略安装失败；PyQt6 GUI、外部研究和 native isolated 财务仍未认证。网络用例 1 项由 marker 明确排除，不能据离线回归宣称真实网络或交易所通过。
- 只读检查确认两个 pyvenv.cfg 均为 include-system-site-packages=false，且没有 UV_CONSTRAINT/UV_BUILD_CONSTRAINT/UV_OVERRIDE/UV_EXCLUDE/PIP_CONSTRAINT/PIP_BUILD_CONSTRAINT/PYTHONHOME 继承。实际模型、paper、恢复及 CLI 的子进程测试使用 sys.executable；PS1/SH 失败传播使用各自明确的 fake python，不从全局 Python 借模型包。

## 验收结论与剩余边界

- 批准计划 C6 的 Windows CPython 3.11 与当前版本（3.14.2）核心/完整声明依赖安装项，在上述代码/依赖/环境身份和测试范围内通过。核心阶段不额外装 pytest，复用真实结构/API smoke；完整阶段串行跑全离线套件，不为通过测试临时固定或放宽版本。
- 这是安装/功能兼容性证据，不是所有 Python 3.11+、其他 OS/CPU、全部允许的未来依赖组合或供应链安全认证。requirements 保持原声明范围，不变成全版本兼容承诺；复现模型和部署时仍须绑定其实际运行库/代码身份，旧模型/部署/paper 不可重封或自动迁移。
- 本轮仅新增本报告并同步 README/进度台账，没有业务重构、新依赖、用户配置/权限/规则变更或真实市场/账户/通知 I/O，没有启动正式搜索/研究/绩效读取。主代理串行自审，不称独立审计。临时隔离环境、缓存和 JUnit 保留在专用 Temp 目录，未递归清理用户目录或卸载全局包。
- C5 原生鲜活账户/mark/book 语义、C6 候选换代（仍待用户确认）/容量/迁移/更广 E2E、C7 外部认证等继续未完成，整体 Goal active。完成本安装项不授予 testnet/live、candidate 或经济采用。
- 文档发布检查：分别在两隔离解释器解析本报告的完整包表，与实际 metadata 71/70 包逐项相等并重算 freeze SHA；两份 JUnit 计数/文件 SHA 和两份 requirements SHA 都匹配，README/台账相对链接和 Markdown fence 平衡通过。Git 排除这三份文档后与 37bc075 的 diff 为空；不为文档-only 提交重复运行未改变的完整业务套件，精确提交后复核文档及相同源码身份。

## 复现命令结构

先创建新的专用临时目录；`<python311>`/`<python314>` 指已安装解释器的真实路径，`<venv>` 必须是新的子目录。运行时不依赖 shell 激活：

```powershell
uv --no-config --no-progress venv --no-project --no-python-downloads --python <python> <venv>
uv --no-config --no-progress --cache-dir <temp-cache> pip install --python <venv>/Scripts/python.exe --default-index https://pypi.org/simple --keyring-provider disabled --only-binary :all: --link-mode copy -r Script/requirements.txt
uv --no-config --no-progress pip check --python <venv>/Scripts/python.exe
# 完成核心 smoke 和缺包验证后，再升级同一个隔离环境：
uv --no-config --no-progress --cache-dir <temp-cache> pip install --python <venv>/Scripts/python.exe --default-index https://pypi.org/simple --keyring-provider disabled --only-binary :all: --link-mode copy -r Script/requirements_full.txt
uv --no-config --no-progress pip check --python <venv>/Scripts/python.exe
& <venv>/Scripts/python.exe -m pytest tests -m 'not network' --basetemp <new-test-temp> --junitxml <new-result.xml> -q --tb=short -p no:cacheprovider
```

本次 uv=0.11.6，Windows x86-64；对子进程设置 PYTHONNOUSERSITE=1、清空 PYTHONPATH，安装前仅在该进程移除 UV_INDEX/UV_INDEX_URL/UV_EXTRA_INDEX_URL/UV_FIND_LINKS/UV_CONFIG_FILE 和对应 PIP_INDEX_URL/PIP_EXTRA_INDEX_URL/PIP_FIND_LINKS/PIP_CONFIG_FILE 继承。临时环境不使用 `--system-site-packages`，未改系统或用户配置；未将解析版本写回依赖声明。

## 完整依赖实际解析快照

下表只记录本次环境，不改依赖声明。包名转为小写、连续的 `-_.` 归一化为 `-` 后排序；对各列存在项逐行拼接 `name==version` 和 LF，得到以下 freeze SHA256：

- 3.11.15（71 包）：`9ecd5154df77cd493b78017557e20a9d8ba32396eaf7c51bc6bbfe24e70b426e`。
- 3.14.2（70 包）：`6716047f5510731a16d36dce1ff731828c9cdaf3513a7b42bb389d5d4d6570f7`。

| package | 3.11.15 | 3.14.2 |
|---|---|---|
| aiohappyeyeballs | 2.7.1 | 2.7.1 |
| aiohttp | 3.14.5 | 3.14.5 |
| aiohttp-fast-zlib | 0.3.0 | 0.3.0 |
| aiosignal | 1.4.0 | 1.4.0 |
| alembic | 1.20.1 | 1.20.1 |
| asttokens | 3.0.2 | 3.0.2 |
| attrs | 26.1.0 | 26.1.0 |
| baostock | 0.9.4 | 0.9.4 |
| ccxt | 4.5.89 | 4.5.89 |
| certifi | 2026.10.19 | 2026.10.19 |
| cffi | 2.0.0 | 2.0.0 |
| charset-normalizer | 3.4.7 | 3.4.7 |
| cloudpickle | 3.1.2 | 3.1.2 |
| coincurve | 21.0.0 | 未安装 |
| colorama | 0.4.6 | 0.4.6 |
| colorlog | 6.12.0 | 6.12.0 |
| contourpy | 1.3.3 | 1.4.0 |
| cryptography | 50.0.2 | 50.0.2 |
| cycler | 0.12.1 | 0.12.1 |
| executing | 2.3.0 | 2.3.0 |
| fonttools | 4.67.0 | 4.67.0 |
| frozenlist | 1.8.0 | 1.8.0 |
| idna | 3.18 | 3.18 |
| iniconfig | 2.3.1 | 2.3.1 |
| ipython | 9.17.1 | 9.17.1 |
| ipython-pygments-lexers | 1.1.1 | 1.1.1 |
| jedi | 0.20.1 | 0.20.1 |
| joblib | 1.6.0 | 1.6.0 |
| kiwisolver | 1.5.1 | 1.5.1 |
| lightgbm | 4.7.0 | 4.7.0 |
| mako | 1.4.3 | 1.4.3 |
| markupsafe | 3.0.4 | 3.0.4 |
| matplotlib | 3.11.2 | 3.11.2 |
| matplotlib-inline | 0.2.2 | 0.2.2 |
| multidict | 6.9.1 | 6.9.1 |
| narwhals | 2.27.1 | 2.27.1 |
| numpy | 2.4.6 | 2.5.4 |
| optuna | 5.0.0 | 5.0.0 |
| orjson | 3.13.0 | 3.13.0 |
| packaging | 26.3 | 26.3 |
| pandas | 3.0.6 | 3.0.6 |
| parso | 0.8.7 | 0.8.7 |
| pillow | 13.0.0 | 13.0.0 |
| pluggy | 1.7.0 | 1.7.0 |
| prompt-toolkit | 3.0.53 | 3.0.53 |
| propcache | 0.5.2 | 0.5.2 |
| psutil | 7.2.2 | 7.2.2 |
| pure-eval | 0.2.4 | 0.2.4 |
| pycparser | 3.0 | 3.0 |
| pygments | 2.21.0 | 2.21.0 |
| pyparsing | 3.3.3 | 3.3.3 |
| pytest | 9.1.1 | 9.1.1 |
| python-dateutil | 3.0.0 | 3.0.0 |
| pyyaml | 6.0.3 | 6.0.3 |
| requests | 2.34.2 | 2.34.2 |
| scikit-learn | 1.9.1 | 1.9.1 |
| scipy | 1.17.1 | 1.18.1 |
| six | 1.17.0 | 1.17.0 |
| sqlalchemy | 2.1.6 | 2.1.6 |
| stack-data | 0.6.3 | 0.6.3 |
| threadpoolctl | 3.7.0 | 3.7.0 |
| tqdm | 4.70.1 | 4.70.1 |
| traitlets | 5.16.1 | 5.16.1 |
| typing-extensions | 4.16.0 | 4.16.0 |
| tzdata | 2026.5 | 2026.5 |
| urllib3 | 2.8.0 | 2.8.0 |
| wcwidth | 0.9.3 | 0.9.3 |
| winloop | 0.6.3 | 0.6.3 |
| xgboost | 3.2.0 | 3.4.1 |
| yarl | 1.25.1 | 1.25.1 |
| zlib-ng | 1.0.0 | 1.0.0 |
