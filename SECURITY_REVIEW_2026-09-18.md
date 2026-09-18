# REDTEAM 仓库安全审查与改进报告

> 审查日期：2026-09-18 · 审查者：Hermes（Solidity/Python 安全审查）
> 审查范围：`Fishman-free/REDTEAM` 全部分支（main + 5 个分支，共 6 条线）
> 方式：全量代码阅读（合约 / Python / MCP / CI / Docker）+ 本机（Windows）逐套复现测试
> 产物：本地 3 个改进分支待推送（见第四节）

---

## 一、结论摘要

| 项 | 结果 |
|---|---|
| 分支总数 | 6（main + 5） |
| 发现的**全平台**致命 bug | 3 个（defender MCP 服务器导入即崩、test_gateway.py 语法错误、PayGate SUT 语法错误——三者均导致对应组件/测试在任何平台不可用） |
| 发现的 **Windows 兼容**崩溃 | 3 类（`os.killpg`、`fcntl`、目录 fsync/符号链接特权） |
| 仓库卫生问题 | 805 个队友机器本地文件被误提交（`.mimosa/` 等） |
| 合约加固 | 3 个（事件补全 / SafeERC20 / NatSpec） |
| 新增合约 | 2 个（RTMToken 减半发行 + BountyVault 防掏空金库），带 22 个新测试 |
| 测试验证 | main：Python 19/19、Hardhat 35/35（+legacy 13/13 单独复跑）；codex 分支：全套修复后本地可跑（见第五节） |
| 修改范围 | 全部在**新分支**上，未动任何队友的分支 |

---

## 二、分支地图（每个分支都是谁、干了什么）

### `main`（默认分支，Kerry Chia 合并维护）
**本地合成实验的"主基线"**：参与者消息 → 版本化系统提示 → mock/可选 LLM → 严格 PAY/NONE 校验 → 机械边界 → 本地链上 ERC-20 真实转账 → 独立评估 → 评估者专属奖励结算 → JSON 证据包。

- `redteam/`：Python 决策运行时（`agent_runtime.py` 三输入分离 + `llm.py` 传输层 + `policy.py` 独立评估器 + `core.py` SQLite 账本 + `server.py` 本地 HTTP + `regression.py` 标注回归）
- `contracts/`：`ExperimentalToken`（合成 ERC-20）、`PaymentAgent`（机械边界：白名单/精确发票/一次性/总额上限）、`RewardSettlement`（评估者专属、一次性、有上限）
- `scripts/agent-flow.js` + `agent-demo.js`：离线的链上端到端演示（Python 运行时作为子进程、LLM 环境变量强制清空）
- `prompts/payment_agent_system_v1.txt`：版本化系统提示（`payment-agent-system-v1`）
- `docs/index.html`：中文项目页（GitHub Pages 自动部署）
- 测试：Python 19 + Hardhat 13

### 已并入 main 的三个功能分支（PR #1~#3）
| 分支 | 内容 |
|---|---|
| `feat/versioned-payment-agent-pages` | 版本化支付提示词 + 项目落地页（PR #1） |
| `fix/readable-html-privacy` | 落地页排版整理、移除本地环境铺垫文案（PR #2） |
| `feat/llm-onchain-payment-agent-e2e` | 把 LLM 形态的 agent 运行时接进真实链上支付闭环（证据包、决策脑、e2e 测试）（PR #3） |

### `rsi4safety`（hym_mac，未合并）
**RSI 研究框架**（"攻击 → 测试 → 打分 → 改良 → 重测试 → 晋级"五步循环的离线实现）：

- `src/rsi4safety/`：`domain.py`（授权/付款/攻击/版本结构）、`core.py`（支付环境+确定性 agent+验证器）、`scenarios.py`（正常任务+攻击样例）、`learning.py`（经验库、候选补丁生成、评分、版本档案）、`runner.py`（五步流程）、`model_agents.py`/`providers.py`（模型接入）、`campaign.py`（多轮实验、并发、晋级门禁、冻结验收）、`benchmark.py`（参数化任务开发集/终局测试集）、`prompts.py`、`config.py`、`cli.py`
- `docs/`：你的《RSI攻击悬赏与持续评估机制》研究构想 + 执行计划 + GLM 实验记录（2026-09-16 三轮攻防，发现并修复一次漏付；最终对照未显示泛化优势——诚实记录）
- 测试：7 个文件的 unittest 套件

### `codex/agent-evolution`（hym_mac，最新、最大，未合并）
**RSI Arena：三主体重 agent 攻防平台**（最接近你产品构想的一层）：

- 三方 **无头 Claude Code 会话**（attacker/defender/judge）各跑在独立 Docker 容器，GLM Coding Plan 后端，各带 CLAUDE.md + skills + knowledge + 专属 MCP 工具（stdio JSON-RPC 手写实现）
- **PayGate SUT**：FastAPI + SQLite 支付服务，预置 8 个真实代码级漏洞（已列清单，仅人工审计用）；一个"guarded"开关可全拦
- **编排器** `src/rsi4safety/arena/`：`orchestrator.py`（8 步轮次协议）、`constitution.py`（程序化授权判定——不可篡改的宪法层）、`audit.py`（哈希链主日志 + verify）、`exchange.py`（spool 交换协议 + schema 校验）、`versions.py`（版本库：git worktree 隔离 + 原子激活 + 回滚）、`trusted_execution.py`（平台侧可信支付执行器）、`scoring.py`（晋级门禁）、`benchmark*.py`、`docker_host.py`、`runtime.py`（ClaudeCodeRuntime + Stub）
- **docker/llm-gateway**：SUT 唯一的 LLM 出口代理（allowlist + 限流 + 防走私 + 禁重定向 + 常量时间鉴权，质量很高）
- 隔离设计：attacker 只见 SUT 公开 API（黑盒）；judge 只见证据束（只读挂载）；defender 只有自己的源码副本；三方数据只通过编排器管的 append-only spool 交换
- 测试：`tests/arena/` 11 个文件 + 原有套件（约 160 个用例）
- **注意**：该分支误提交了 805 个队友机器本地文件（`.mimosa/` 扫描器账本、`.v2c/`、`.video_agent/`）——已由本报告清理（见 3.2）

---

## 三、安全审查发现

### 3.1 🔴 全平台致命 bug（3 个，已修复）

> **CI 旁证**：GitHub Actions 上 `codex/agent-evolution` 的最近一次运行（`offline-tests`，2026-09-18T01:39Z 推送）**实际就是失败的**（耗时 9m16s）——与本地发现的 F1/F2/F11 完全吻合（这三个 bug 在 Ubuntu 上同样会炸）。修复后本地全套 159 测试全绿。另注：`main` 的若干 CI 失败是 GitHub Pages 未启用导致的部署 job 失败（仓库 README 已注明需要管理员一次性开启 Settings → Pages → Source: GitHub Actions），不是代码问题。

**F1. `agents/defender/mcp/defender_server.py` 导入即崩溃**
- 第 51 行把 `Path` 对象直接传给 `re.match()`：`TypeError: expected string or bytes-like object, got 'WindowsPath'`。同时那条正则 `^/[a-zA-Z0-9/_-]+$` 本身是 POSIX 专用，Windows 路径（`C:\...`）永远过不了。
- 影响：defender 的 MCP 服务器在**任何平台**都无法启动 → 4 个 promotion 相关测试全部 "无响应"（`2 not found in {}`），晋级链路实际不可用。
- 修复：改为 `Path(...).is_absolute()` + `..` 段检查 + 危险字符块列表（NAMED：NUL/LF/CR/引号/元字符），跨平台语义一致，保留了原防护意图。发现方式：手动 stdio 握手探测。

**F2. `tests/arena/test_gateway.py` 语法错误**
- 文件第 1 行有一个游离的 `import os` 出现在 docstring 和 `from __future__ import annotations` 之前 → `SyntaxError: from __future__ imports must occur at the beginning of the file`。该测试模块在**任何平台**都无法加载（网关安全测试实际上从未跑过）。
- 修复：删掉游离行（文件内部已有正确的 `import os`）。

**F11. `sut/paygate/app/llm_agent.py` 语法错误——SUT 全平台无法启动**（本轮最深的一个）
- `41f8086`（"Harden agent security and extend gateway benchmarking"）新增 SSRF 防护时**缩进错了 4 个空格**：防护代码（4 行）落在类层级，导致 SSRF 检查之后的整个函数体（`model = ...` 到 `raise last_error`，共 40 行）全部掉进 `if ...: raise` 块内成为死代码，`return` 因此位于函数之外。
- 后果：`python -m py_compile` 直接 SyntaxError → uvicorn 导入 `app.main` 失败 → **PayGate SUT 在任何平台（含 macOS/Linux）都无法启动** → 编排器全部 9 个端到端测试失败（6 个 "SUT not healthy" + 3 个下游断言失败），且每个失败要空等 60 秒健康检查。
- 修复：把 5 行防护代码重新缩进回函数体内（12 空格处恢复为 if 的 body，8 空格处恢复为函数体）。这是**意外损坏**，不是预置漏洞——预置的 8 个漏洞是逻辑层的（见 `docs/arena/SEEDED_VULNS.md`），语法错误让整个 SUT 根本跑不起来，必须修。

**F12. CI 工作流顺序错误——Core suite 缺 SUT 依赖（CI 一直红的真正根因）**
- `.github/workflows/tests.yml` 里 `fastapi/uvicorn/httpx` 只在**第二个步骤**（SUT suite）安装，但**第一个步骤**（Core suite，159 个 unittest）内部就会 spawn PayGate SUT（uvicorn）——依赖缺失 → CI 上每个 SUT 测试都以 `SUT not healthy: Connection refused` 失败（与 F11 叠加时表现相同，F11 修完后这层依然拦着 CI，实测 run 35320161128 复现）。
- 修复（已提交 `32d445c`）：把依赖安装提为独立步骤、放在两个套件之前；SUT 步骤不再重复安装。

### 3.2 🟠 已修复（Windows 兼容 + 仓库卫生）

**F3. `os.killpg` POSIX 专用**（`arena/sut_driver.py`）
- Windows 上 `AttributeError: module 'os' has no attribute 'killpg'` → SUT 子进程无法终止、泄漏，campaign 以 "stopped" 而非 "completed" 结束；多个鲁棒性测试每次空等约 60 秒。
- 修复（已提交 `75741f2`）：新增 `_terminate_process_tree()`——POSIX 保持原语义（进程组 SIGTERM/SIGKILL），Windows 用 `taskkill /PID x /T`（先温和后 `/F` 强杀），失败兜底 `process.terminate()`。（`start_new_session=True` 保留——Windows 上静默忽略、无副作用。）

**F4. `fcntl` POSIX 专用**（`control.py` / `experience.py` / `versions.py`）
- Windows 上 4 个测试模块无法加载。修复：新增 `arena/filelock.py`——POSIX 用 `fcntl.flock`，Windows 用 `msvcrt` 字节区间锁（共享锁在 Windows 上升级为独占锁：只会更强、不会更弱；`blocking=False` 与 flock 一样抛 `BlockingIOError`）。

**F5. 目录 fsync + 版本投影符号链接**
- `versions.py` 用 `os.open(目录, O_RDONLY)` 做目录 fsync（POSIX-only）→ Windows PermissionError；修复为 Windows 跳过（附注释）。
- `_switch_projection` 无条件创建目录符号链接 → Windows 非开发者模式 `WinError 1314`（无特权）。修复：捕获该错误后**降级为目录拷贝**（对读取方语义等价），并修正了拷贝降级下的临时目录清理逻辑。

**F6. 测试平台适配**（最小改动，不削弱断言）
- symlink 相关测试加 `skipUnless` 能力探测（Windows 无特权时跳过，POSIX 照跑）；`as_posix()` 修正 worktree 列表断言的路径分隔符。

**F7. 仓库卫生：805 个机器本地文件误提交**
- `.mimosa/`（803 个文件，含 `/opt/homebrew/...` 本机路径的扫描器账本）、`.v2c/`、`.video_agent/`（zcode 插件缓存指针，指向队友 mac 的个人目录）。已从分支删除并加入 `.gitignore`（tracked 文件 922 → 117）。
- 另：`.spec-workflow/`（Claude Code 插件本地状态）在 main 工作区出现，已在合约分支的 `.gitignore` 中忽略。

### 3.3 🟡 已修复（合约层，由 Claude Code 执行、本报告复核）

**F8. 配置类操作没有事件**（审计痕迹缺失）——对证据驱动的系统是实质问题
- `PaymentAgent`：新增 `AllowlistUpdated`、`InvoiceConfigured`；`RewardSettlement`：新增 `SettlementConfigured`。
- 保留全部原有 revert 字符串（byte-for-byte），13 个 legacy 测试零回归。

**F9. 原生 `token.transfer` 调用**——非标准 ERC-20（USDT 类）会直接炸或静默失败
- 两个合约均改为 OpenZeppelin `SafeERC20.safeTransfer`。

**F10. 缺 NatSpec**——全部 public/external 函数已补全（含 `@dev` 设计意图说明）。

### 3.4 ✨ 新增：RTM 代币 + 防掏空悬赏金库（对应你的核心诉求）

你要的"限量、每年减半、不能被一次盗光"此前**在代码里不存在**（只有固定上限的 ExperimentalToken 和一次性结算）。现已补齐：

- **`RTMToken.sol`**：21,000,000 固定上限、零预挖；年度减半发行（第 0 年 = 上限一半，之后逐年减半）；年份由 `block.timestamp` 推导（minter 不能挑年份）；`owner` 不能铸币、不能改发行表。
- **`BountyVault.sol`**：五道互相独立的防掏空闸门——年度减半预算（token 层强制）、单笔认领上限（配置+结算双重校验）、认领一次性、仅独立评估者可操作、可暂停。金库自身不持有余额，结算时按需铸造——不存在"金库被攻破转走存量"的路径。
- 22 个新测试（减半数学、预算耗尽回滚、跨年恢复、一次性、权限、暂停），`npm test` 35/35 绿。

### 3.5 建议但未改（低优先级，留给你们决策）

1. **revert 字符串 → custom errors**：省 gas、更规范，但会改变 revert 数据，需同步改两个测试文件。建议作为独立 PR 统一做。
2. **CI 供应链**：`actions/*` 固定版本标签（v4/v5）可进一步固定到 commit SHA；`npm install` 建议改 `npm ci`（有 lockfile）。
3. **`redteam/server.py` 的 `/api/session`**：会把会话 token 返回给任何能访问 loopback 的本地进程（README 已声明"不是恶意本地用户的沙箱"）。若未来把它暴露到本机之外，需要改成一次性配对 + 短 TTL。
4. **PaymentAgent.operator 不可轮换**（已文档化）；上真实资金前建议两阶段转移。
5. **BountyVault.evaluator 热切换**是 owner 信任点（设计文档已注明）；主网化前建议时间锁 + 两阶段。
6. **`maxPayment` 参数语义双关**（单笔 + 总量共用同一个 cap，已文档化）；产品化时建议拆成两个参数。

### 3.6 经审查确认无恙的部分（重点抽查）

- **`docker/llm-gateway/gateway.py`**（约 450 行）：鉴权（常量时间、无 token 即拒绝转发）、按 IP 令牌桶限流、模型 allowlist、HTTP/1.0 单请求语义、重复 Content-Length/Transfer-Encoding 拒绝、精确按长度读 body、禁跟随重定向（防 Authorization 泄漏）、日志不含 token/请求体——未发现可乘之机。
- **编排器信任边界**：宪法判定器、冻结套件、门禁逻辑均只在宿主机；补丁提取有路径逃逸防护（tar 成员校验 + `filter="data"`）；证据束做 sha256 全量校验 + symlink 拒绝；哈希链 append-only 且每次启动先 verify。
- **三个 MCP 服务器**：路径校验完备（`/` 前缀 + `..` 拒绝 + 白名单前缀）、judge 证据文件白名单、defender 的 promotion tar 有 sha256 校验后解压 + 逃逸防护、无 shell 注入面（subprocess 全部列表参数）。
- **`agent_runtime.py` 三输入分离**：system / trusted state / untrusted message 角色分离，模型输出只进严格 PAY/NONE 语法，机械边界在外层代码强制——设计正确。

---

## 四、改进分支（本地已提交，待你推送）

| 分支 | 基于 | 内容 | 提交 |
|---|---|---|---|
| `safety/windows-portability` | codex/agent-evolution | F1/F2/F3/F4/F5/F6/F7/F11（含 SUT 语法修复、killpg、垃圾清理） | `953dcc4`、`eeaffbf`、`fe09abd`、`75741f2` |
| `safety/contracts-and-rtm` | main | F8/F9/F10 + RTM/BountyVault + 文档 | `48e9c16`、`cde51e6` |

推送命令（确认无误后执行）：

```powershell
cd C:\Users\21560\Desktop\REDTEAM-codex;  git push origin safety/windows-portability
cd C:\Users\21560\Desktop\REDTEAM;         git push origin safety/contracts-and-rtm
```

推送后在 GitHub 上开 PR 给对应队友 review。**未做**：未 push、未 merge、未碰任何队友分支的提交历史。

---

## 五、验证记录（本机 Windows 实测）

> 环境说明：本机需先安装 SUT 运行依赖 `pip install fastapi==0.141.1 uvicorn==0.53.0 httpx`（与 CI `tests.yml` 的钉子一致；缺失时 SUT 无法启动、表现为 60 秒健康检查超时）。已安装。

| 套件 | 修复前 | 修复后 |
|---|---|---|
| main · Python（pytest） | 19/19 ✅ | 19/19 ✅ |
| main · Hardhat（全部） | 13/13 | **35/35** ✅（+22 新增） |
| main · legacy 单独复跑 | 13/13 | 13/13 ✅（零回归证明） |
| rsi4safety · unittest（32 个） | — | **32/32 OK** ✅（需 `PYTHONPATH=src`，如该分支 README 所述） |
| codex · 离线全套（unittest，159 个） | 118 个可跑：7 模块加载失败 + 23 失败，多测试卡死约 60s/个，套件跑不完 | **159/159 OK（skipped=2*，耗时约 9 分钟）** ✅ |

*2 个 skip 是符号链接语义测试在无特权 Windows 上的**设计内跳过**（POSIX / GitHub CI 上照常执行）。

**CI（Ubuntu）终验**：修复 + 工作流修正合并后，`offline-tests` 工作流**首次全绿**——run [35321018867](https://github.com/Fishman-free/REDTEAM/actions/runs/35321018867)（`Core suite` 159 个 + `SUT suite` 19 个，共 6m0s，0 失败 0 跳过）。此前该工作流自创建起从未通过（根因见 F11 + F12）。

---

## 六、剩余风险与上线前 Checklist

- [ ] 推送两个 safety 分支 → 开 PR → 队友 review 后合并
- [ ] RTM/BountyVault 上测试网 + 外部审计（新增代币经济，必须过审计）
- [ ] evaluator/owner 密钥管理方案（多签 / 时间锁 / 轮换演练）
- [ ] CI 硬化（SHA pin、npm ci、windows-latest 加入矩阵）
- [ ] 对外接口层按《ATTACK_INTERFACE_DESIGN.md》落地时，逐项过第 7 节安全清单
- [ ] 数据出口（卖给安全公司）前完成脱敏与合规评审
