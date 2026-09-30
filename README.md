# REDTEAM：区块链悬赏与智能体安全研究

研究范围包括链上悬赏与预算、可验证支付执行、外部反例、独立裁决和持续修复。支付智能体是首个场景，RSI4Safety / Arena 是评测与改进子系统。

项目维护两份核心文档：**本文**负责结构和运行入口；[总研究方案与实现评估](docs/RESEARCH_PLAN.md)负责完整研究闭环、已实现能力、PDF 对照、缺口与验收。原始总构想、RTM 设计、预注册和历史证据见[资料索引](docs/INDEX.md)。

## 目录

```text
REDTEAM/
├── README.md                      项目入口
├── docs/
│   ├── RESEARCH_PLAN.md            总研究方案与当前实现评估
│   ├── INDEX.md                    全项目资料索引
│   ├── references/                总构想、链上设计与跨模块记录
│   └── site/index.html            静态研究展示页
├── contracts/                     合约与本地链上支付实验
│   ├── README.md                  合约模块入口
│   ├── src/                       五份 Solidity 合约
│   ├── scripts/                   部署、执行、事件核验与演示
│   ├── redteam/                    支付决策、SQLite/HTTP、模型适配
│   ├── test/ / tests/              Solidity/JS 与支付 Python 测试
│   ├── scenarios/ / prompts/      可信场景、评估真相与提示词
│   └── package.json / hardhat.config.js
├── rsi4safety/                     RSI 子系统
│   ├── README.md                  子系统入口
│   ├── payment_agents/            PayGate / PayAssist / PayChain 框架与靶标
│   ├── execution/                 执行、攻防编排及测试
│   │   ├── src/rsi4safety/         CLI、Arena、策略与研究实验
│   │   ├── agents/ / docker/       角色、MCP、容器和模型网关
│   │   └── tests/                 RSI、Arena、独立实验测试
│   ├── docs/                      支付系统 PDF、RSI 规格及实验记录
│   └── pyproject.toml / requirements-dev.txt
├── archieve/                      明确被替代的版本与迁移清单
├── .github/                       CI 与受开关控制的 Pages 发布
├── .git/                          仓库历史
└── pytest.ini / requirements-dev.txt   全项目 Python 测试与安装入口
```

生成的依赖、构建产物与状态放在所属模块内并保持 Git 忽略：合约的 `node_modules/artifacts/cache` 在 `contracts/`；RSI 的 `.venv/.env/.rsi4safety` 在 `rsi4safety/`。

## 模块边界

| 模块 | 当前能力 | 入口 |
|---|---|---|
| 合约与支付实验 | `PaymentAgent` 约束付款；`RewardSettlement` 发放预充资实验奖励；`ExperimentalToken` 提供合成资产；Python/JS 执行并核验付款证据 | [contracts/README.md](contracts/README.md) |
| RTM 悬赏机制 | `RTMToken` 固定发行上限、年度减半与不可变 minter；`BountyVault` 管理 claim 预留、同年结算与取消 | [RTM 设计](docs/references/research/RTM_BOUNTY_DESIGN.md)、[合约源码](contracts/src/) |
| RSI4Safety / Arena | 攻击→可信执行→独立裁决→候选修复→回归→晋级/回滚；保留策略、rsi_eval、跨域 engineering 实验 | [rsi4safety/README.md](rsi4safety/README.md) |

Payment-agent 的 `PAY/NONE`、SQLite/EVM 账本与 Arena 的 `arena.payment-plan.v1`、宿主模拟账本分别维护。RTM 目前也是独立合约模块，尚未接入 Arena 判奖。各模块可运行不等于总研究闭环已连接完成。

## 安装与完整测试

需要 Python 3.11+；合约工具链使用 Node.js 22。以下从 REDTEAM 仓库根目录执行：

```bash
python3 -m venv rsi4safety/.venv       # 已有环境可直接使用
source rsi4safety/.venv/bin/activate   # Windows: rsi4safety\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q                  # 合约侧支付 Python + 完整 RSI 集合

(cd contracts && npm ci --no-audit --no-fund)
(cd contracts && npm test)
(cd contracts && npm run demo:agent)
(cd contracts && npm run demo:multiround)

# 三个靶标使用同名 app 包，分别在独立进程测试
(cd rsi4safety/payment_agents/paygate && ../../.venv/bin/python -m pytest tests -q)
(cd rsi4safety/payment_agents/payassist && ../../.venv/bin/python -m pytest tests -q)
(cd rsi4safety/payment_agents/paychain && ../../.venv/bin/python -m pytest tests -q)
```

未激活环境时，可在根目录用 `rsi4safety/.venv/bin/python -m pytest -q`。首次安装依赖或获取 Solidity 编译器可能需要网络；本地确定性实验不依赖模型或外部 RPC。

## 文档与归档

总研究构想与链上设计放根 `docs/`，RSI 专用材料放 `rsi4safety/docs/`；各模块 README 只提供本模块导航和运行命令。运行用的角色指令、技能和知识文件属于 `execution/agents/` 资产，不混入研究文档。

归档只接受有明确替代版本的内容。未接入、尚未完成、有缺陷或日期较早都不是归档依据。当前合约、支付代码、RSI 和独立实验全部保留；日期化报告作为研究证据保存，不能替代当前验证。具体替代关系见 [archieve/README.md](archieve/README.md)，原文件去向与 SHA-256 见[迁移清单](archieve/manifest.json)。

## 验证与 CI

CI 覆盖 Ubuntu/Windows 的支付 Python、RSI 和三个隔离靶标，以及 Ubuntu 的合约测试和两种支付演示。Pages 仍要求 main 测试成功且 `REDTEAM_PAGES_ENABLED=true`，只发布 `docs/site/index.html`。

2026-09-30，在最终目录下验证：

| 范围 | 结果 |
|---|---|
| RSI 完整回归（`rsi4safety/`） | **288 passed，163 subtests passed，1 skipped**（Windows 专用测试）；247.65 秒 |
| 合约侧支付 Python（`contracts/`） | **38 passed，25 subtests passed** |
| Solidity / EVM 测试（`contracts/`） | **55 passing**；单轮、多轮 demo 均通过 |
| 三个独立支付靶标 | PayGate **19**、PayAssist **16**、PayChain **7** 项通过 |
| 根目录入口 | 收集 **327** 项 Python 测试（326 项可在本机通过，1 项平台跳过）；路径回归、两轮 demo、A01-B01 benchmark 通过 |
| 文件保全与文档 | **191** 个原文件全部有去向；30 份当前指南/研究文档的 **142** 个本地链接有效；有效源码和研究方案未归档 |

本次移动仅改变目录、资源定位、包/测试/CI 配置及相应文档，不改变已有支付或判奖逻辑。旧 campaign 的运行时指纹会随源码布局变化；保留的历史状态不能默认跨布局恢复。


本地验证不代表真实模型实验、远端 CI 或链上—Arena 集成已经完成。本机 Hardhat 对 Node 25 有版本警告，CI 使用 Node 22；Python 环境有一项 Starlette/httpx 弃用警告。本次不执行在线模型、发布或部署。
