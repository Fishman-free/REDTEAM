# RSI4Safety / Arena

本目录收纳支付智能体安全评测和持续修复子系统。合约与链上执行在同级 [contracts/](../contracts/README.md)，项目总研究方案见 [docs/RESEARCH_PLAN.md](../docs/RESEARCH_PLAN.md)。

## 目录

```text
rsi4safety/
├── README.md
├── payment_agents/               被测支付智能体框架
│   ├── paygate/                   策略检查层与确定性漏洞靶标
│   ├── payassist/                 对话、发票、工具返回中的授权边界
│   └── paychain/                  采购、审批、支付三角色离线原型
├── execution/
│   ├── src/rsi4safety/             CLI、Arena、策略与研究实验
│   ├── agents/                    attacker / defender / judge 的指令和 MCP
│   ├── docker/                    角色容器与模型网关
│   └── tests/                     宿主、Arena 与研究实验测试
├── docs/
│   ├── INDEX.md                   RSI 资料导航
│   └── references/                PDF、规格、预注册和实验记录
├── pyproject.toml
└── requirements-dev.txt
```

执行主链从 [CLI](execution/src/rsi4safety/cli.py) 进入 [orchestrator](execution/src/rsi4safety/arena/orchestrator.py)，经 [SUT 驱动](execution/src/rsi4safety/arena/sut_driver.py)、[可信执行器](execution/src/rsi4safety/arena/trusted_execution.py)、[裁决](execution/src/rsi4safety/arena/constitution.py)、[评分](execution/src/rsi4safety/arena/scoring.py)和[版本库](execution/src/rsi4safety/arena/versions.py)完成闭环。

`execution/src/rsi4safety/` 同时保留策略级 `core/learning/runner/campaign`、[rsi_eval](execution/src/rsi4safety/rsi_eval/) 和 [engineering](execution/src/rsi4safety/arena/engineering.py)。这些是不同研究原型，源码和测试均为活动内容。PayChain 在线容器与候选门禁、rsi_eval 的未见族分母等已知问题统一记录在总方案。

## 安装与运行

以下从本目录执行。已有 `.venv` 和 `.env` 可继续使用。

```bash
python3 -m venv .venv              # 已有环境可跳过
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q               # 仅 RSI 子系统

python -m rsi4safety demo --state-dir .rsi4safety/demo-check --rounds 2 --json
python -m rsi4safety arena run --campaign arena-check --rounds 2 --dry-run
python -m rsi4safety arena verify --campaign arena-check
python -m rsi4safety arena bench --campaign bench-check --system A01 --seed-id A01-B01
```

三个 `payment_agents/*` 的顶层包都叫 `app`，应分别测试；完整命令见[根 README](../README.md)。RSI 默认状态、`.env` 和运行资产从本子系统定位，显式相对路径按调用工作目录解释。使用新 campaign 名获得独立起点；同名已完成战役可能复用结果，旧状态受路径和运行时指纹约束。

`dry-run` 使用 stub 和本地 HTTP 子进程，不调用模型；编排完成不等于修复成功。在线模式需要在本目录安装 `python -m pip install -e '.[arena]'`、配置 Docker 与模型凭据。非 dry-run Arena、`arena smoke`、`probe`、`experiment`、`repair-check` 会调用模型；SUT 模型决策需显式指定 `--sut-llm-mode llm`。

## 评测口径与资料

同时观察越权尝试、实际模拟付款、正常任务完成和攻击下合法任务完成。`guarded` 拦截落账不能证明目标已经修好；全部拒付不能作为支付任务的合格修复。

注册表当前有 43 条规格/7 类系统，其中 22 条有支付适配路径，21 条未支持；它与修复晋级仍是独立入口。benchmark 区分 `passed / failed / error / unsupported`，退出码分别为全过 `0`、明确失败 `1`、错误或未支持 `2`。规格数、支持数和通过数不能混用。

支付 PDF、RSI 研究计划、技术规格、修复者预注册与实验记录均在 [docs/INDEX.md](docs/INDEX.md)。完整能力评估与后续验收只维护在[总研究方案](../docs/RESEARCH_PLAN.md)，测试结果维护在[根 README](../README.md)。
