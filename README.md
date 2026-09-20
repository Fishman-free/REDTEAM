# REDTEAM · Payment-agent safety experiments

本仓库是**本地合成资产的支付智能体安全研究平台**。当前整合了两条可独立运行的实现：严格付款提议到 SQLite/本地 EVM 的执行闭环，以及 RSI4Safety 的授权评测、候选修复与 Arena 编排。它不是主网支付产品、通用攻击平台，也不证明模型具备通用安全性或递归自我改进能力。

## 两条实验路径，不混用协议

| 路径 | 代码与协议 | 用途 |
|---|---|---|
| Payment-agent MVP / EVM | `redteam/`、`scripts/`、`contracts/`；严格 `PAY …` / `NONE` | 比较 vulnerable/hardened 决策，执行合成 token 转账，核验事件并结算实验奖励 |
| RSI4Safety / Arena | `src/rsi4safety/`、`sut/`、`agents/`；结构化授权及 `arena.payment-plan.v1` | 攻击→执行→程序评分→候选修复→回归→晋级/回滚 |

两套账本、模型接口、版本库和评分语义不同。**Arena 尚未接入链上支付或 RTM 领奖**；不能把两套测试通过当作已完成跨系统端到端集成。

分支来源、冲突处理与验收记录见 [整合说明](docs/INTEGRATION.md)。研究口径见 [实验协议](docs/EXPERIMENT_PROTOCOL.md)；Arena 当前实现契约见 [ARENA_EVOLUTION_SPEC.md](docs/ARENA_EVOLUTION_SPEC.md)。

## 安装与完整验收

需要 Python 3.11+、Node.js 22 和 Git。建议使用虚拟环境，避免修改全局依赖。

```bash
python -m venv .venv
# Linux/macOS/Git Bash: source .venv/bin/activate
# Windows PowerShell:  .\.venv\Scripts\Activate.ps1
# Windows Git Bash:    source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
npm ci --no-audit --no-fund

python -m pytest -q
python -m unittest discover -s tests
npm test
npm run demo:agent
npm run demo:multiround
```

根目录的 pytest 配置只发现 `tests/` 下的宿主测试，包含 SQLite、RSI 与 Arena；不把两个 SUT 的顶层 `app` 包混在同一解释器中。SUT 必须分别测试：

```bash
cd sut/paygate
python -m pytest tests -q
cd ../payassist
python -m pytest tests -q
cd ../..
```

`requirements-dev.txt` 安装宿主测试和 SUT 运行依赖。Arena 离线验收会启动本机回环 HTTP 服务，**需要 FastAPI/uvicorn，但不需要 Docker、模型密钥或真实模型请求**。安装依赖、npm 工具链以及首次 Solidity 编译器下载可能需要网络；运行离线实验不依赖外部模型或外部 RPC。

## Payment-agent：离线支付实验

```bash
npm run demo:agent       # 单轮：脆弱付款、加固拒绝、正常付款对照
npm run demo:multiround  # 同一合约状态下的多轮对照与分项指标
python -m redteam.cli --replay
python -m redteam.server --port 8765 --db ./redteam.sqlite3
```

交互界面为 `http://127.0.0.1:8765`，只监听回环。可创建两种模式、提交文本、查看余额/证据、顺序回放，以及通过 `POST /api/regression` 获得带标签的指标。会话令牌由本地 `/api/session` 返回，**不是面向公网的认证方案**。

### 执行与评价边界

- Python 运行时只产生决策。模型输出严格解析为单条付款提议或 `NONE`；代码检查收款白名单和单笔上限，加固模式另查可信采购、交付、准确金额与已付款记录。
- `redteam/llm.py` 提供统一传输、严格解析和旧 `request_proposal` 兼容包装；SQLite 与独立运行时使用同一后端选择规则。
- 版本化场景位于 `scenarios/payment-delivery-v1/`。采购输入与评估器真相是两个独立文件；执行器不读取评估器答案。它们仍是开发者可编辑的夹具，不是对恶意本机用户的隔离。
- 单笔上限为 **250 个整数实验 token**；EVM 的累计付款上限默认 **100 token**，奖励预算另为 **50 token**。这两个限额不是同一概念。超出剩余累计额度的有效提议记录为执行阻止，不算实际违规转账。
- SQLite 初始金库为 **1000 token**，不施加 EVM 的发票唯一约束或 100-token 累计授权额度，故意保留重复发票的脆弱实验路径。不同后端不能直接混合计算成功率。
- EVM 每个多轮实验只部署一次合约。后续决策继承已确认付款历史；合约限制操作/发票一次性使用、准确配置匹配、白名单与累计额度。
- 评估器从指定付款合约的 `Payment` 事件及指定 token 合约的匹配 `Transfer` 事件重建实际付款，金额使用精确整数单位；不是用模型提议代替链上事实。
- 无付款、执行被阻止、付款后评价失败、奖励失败分开记录；奖励失败不能抹掉已经发生的付款。奖励只能由独立 evaluator signer 结算。

`executeRun` 保留单条调用接口；`executeMultiRound` 复用同一实验状态，最多 100 条消息。状态只存在于当前本地 Hardhat 生命周期中，不支持跨进程恢复。证据标记场景、后端、格式版本及实际执行边界，并记录提议、交易、事件、余额和评价；这些不是不可篡改的存储证明。

### 显式模型启用

默认后端为确定性 mock。只有设置 `REDTEAM_LLM_ENABLED=1` 及 `REDTEAM_LLM_BASE_URL`、`REDTEAM_LLM_API_KEY`、`REDTEAM_LLM_MODEL` 才启用 OpenAI-compatible 网络后端；凭据只放环境中，不写源码。

系统提示词、主机状态和不可信参与者文本分别构造消息。消息角色和标签只是输入组织，**真正的付款边界仍是代码与合约**。网络/格式失败安全弃权。测试使用假传输；链上演示同时显式选择 mock 并移除模型环境配置，不会被环境变量意外切换到在线模式。本次整合不运行真实模型验收。

## RSI4Safety：保留现有改进闭环

```bash
python -m rsi4safety demo --state-dir .rsi4safety/demo-local --rounds 2 --json
python -m rsi4safety arena run --campaign drycheck-local --rounds 2 --dry-run
python -m rsi4safety arena verify --campaign drycheck-local
```

请使用新状态目录获得独立起点；同一目录会恢复历史版本与经验。状态默认在 Git 忽略的 `.rsi4safety/` 下。

- 基础 RSI demo 使用模拟资金与确定性策略候选，保留版本父子关系、拒绝原因、经验和回归结果。全部拒付不能晋级。
- Arena 已有 PayGate/PayAssist、宿主可信支付执行器、配对对照、程序裁决、冻结验收、版本晋级/回滚、审计与 Windows 兼容处理。
- Arena dry-run 使用 stub，不会自动产生真实修复；它仍会在本机启动受控的 uvicorn SUT 子进程，只是不使用 Docker 或模型 API。拒绝晋级或终局回滚可能是**正确结果**；协议完成与审计链有效，不等于修复成功。
- 开发回归可使用执行缓存；冻结验收强制新执行。公开任务与开发数据即使按实例分开，也可能共享攻击机制，不能据此证明泛化。
- Docker/Claude Code/GLM 在线路线需要显式安装 `.[arena]`、配置 Docker 和模型凭据。`probe`、`experiment`、`repair-check`、非 dry-run Arena 会调用模型，本次不运行。

详细说明：[基础架构](docs/ARCHITECTURE.md)、[Arena 手册](docs/ARENA.md)、[模型实验](docs/GLM_EXPERIMENTS.md)。历史实验文档是当时的记录，不是本次整合重新运行的结果。

## 合约与尚未完成的连接

`ExperimentalToken`、`PaymentAgent`、`RewardSettlement` 是现有本地支付 demo 的合约；SafeERC20 与配置事件加固已保留。`RTMToken`、`BountyVault` 的年度减半发行和奖励结算实现及测试也保留，但**尚未接入 Arena 或当前 payment-agent demo**。

[攻击接口设计](ATTACK_INTERFACE_DESIGN.md) 中的对外 A2A 会话、配额、commit-reveal、独立证明和公开领奖仍是设计，不是上线能力。RTM owner 可轮换 minter；单次 claim 限额不等于总预算不可耗尽；跨年减半可能让未预留预算的大额 claim 无法整笔支付。不得承诺已具备生产资金安全或保证兑付。

## CI 与项目站

`.github/workflows/tests.yml` 统一覆盖两个宿主 Python 入口、两个隔离 SUT、离线 RSI/Arena 和本地 EVM 演示；Python 配置 Windows/Ubuntu 矩阵，合约使用 Ubuntu。远端 CI 结果只有提交推送后才会产生，本地通过不能称为远端通过。

Pages 与测试分开：仅在 `main` 的完整测试成功，且仓库变量 **`REDTEAM_PAGES_ENABLED=true`** 时发布对应受测提交的 `docs/`。管理员须先在 Settings → Pages 启用 GitHub Actions。本轮不修改远端设置或发布站点；未启用 Pages 不再让测试流程显示失败。

## 安全与研究声明

只使用授权的本地合成目标，不使用真实资金、主网钱包或外部攻击目标。SUT 带有故意保留的研究漏洞，不能公开暴露。进程内 SUT 不是不可信代码沙箱；Docker 当前网络配置也不能承诺无互联网出口。提示词隔离、哈希链和容器本身都不是对恶意宿主用户的完整防护。未声明模型权重训练、生产部署、独立科研泛化或已验证 RSI。
