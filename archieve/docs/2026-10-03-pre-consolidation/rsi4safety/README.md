# RSI4Safety / Arena

本目录收纳支付智能体安全评测和持续修复子系统。合约与链上执行在同级 [contracts/](../contracts/README.md)，项目总研究方案见 [docs/RESEARCH_PLAN.md](../docs/RESEARCH_PLAN.md)。

## 目录

```text
rsi4safety/
├── README.md
├── payment_agents/               被测支付智能体框架
│   ├── README.md                  多轮 PayAssist 设计、研究依据与操作入口
│   ├── payassist_agent/           自主工具循环、服务与独立评判
│   ├── L0_readonly/               禁止出款：个人查询、核账、商家开票
│   ├── L1_single_payment/         一笔授权付款：个人购买、商家采购、查账恢复
│   ├── paygate/                   策略检查层与确定性漏洞靶标
│   ├── payassist/                 现有 Arena 单次付款计划基线
│   └── paychain/                  采购、审批、支付三角色离线原型
├── execution/
│   ├── src/rsi4safety/             CLI、Arena、策略与研究实验
│   ├── agents/                    attacker / defender / judge 的指令和 MCP
│   ├── docker/                    角色容器与模型网关
│   ├── scripts/                   Studio 模型 SSH 隧道管理
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

旧版 `paygate/payassist/paychain` 的顶层包都叫 `app`，应分别测试；新版 `payassist_agent` 已纳入根目录回归。完整命令见[根 README](../README.md)。RSI 默认状态、`.env` 和运行资产从本子系统定位，显式相对路径按调用工作目录解释。使用新 campaign 名获得独立起点；同名已完成战役可能复用结果，旧状态受路径和运行时指纹约束。

`dry-run` 使用 stub 和本地 HTTP 子进程，不调用模型；编排完成不等于修复成功。在线模式需要在本目录安装 `python -m pip install -e '.[arena]'`、配置 Docker 与模型凭据。非 dry-run Arena、`arena smoke`、`probe`、`experiment`、`repair-check` 会调用模型；SUT 模型决策需显式指定 `--sut-llm-mode llm`。

## 本地 Studio 4B 支付模型

已配置 SSH 别名 `studio`，经雷雳桥到 Studio 的本机模型服务。模型为 `Qwen/Qwen3-4B-Instruct-2507`；本机接口为 `http://127.0.0.1:18081/v1`，远端服务保持 `127.0.0.1:18080`。以下从本目录执行：

```bash
python3 execution/scripts/studio_model.py start
python3 execution/scripts/studio_model.py status
# 新版：L0 / L1 均为多轮对话，模型自主选择工具
.venv/bin/python -m payassist_agent chat --scenario l1_personal_purchase
.venv/bin/python -m payassist_agent bench --kind normal --repetitions 2
# 现有 Arena 单次付款计划基线
.venv/bin/python -m rsi4safety arena bench \
  --campaign studio-4b-check --sut-app payassist --sut-llm-mode llm \
  --system A01 --seed-id A01-B01
# 结束模型连接时；只关闭本项目 SSH 隧道
python3 execution/scripts/studio_model.py stop
```

`start` 使用现有 SSH key 与已知主机配置，可重复调用；开机或连接断开后重新执行即可。隧道控制文件在 `.rsi4safety/studio/`，不会提交 SSH key 或本地 `.env`。

本地 `.env` 中设置 `SUT_MODEL=Qwen/Qwen3-4B-Instruct-2507` 和 `SUT_BASE_URL=http://127.0.0.1:18081/v1`；Arena CLI 的 `--sut-model/--sut-base-url` 可覆盖，新版使用 `--model/--base-url`。该 Studio 服务当前不要求 key；将来若需要，可用专用 `SUT_API_KEY`。**所有非 payment agent 的模型角色统一为精确 `glm-5.3`**，包括 attacker、defender、可选 judge 和研究实验；其他模型配置会明确拒绝。`--sut-llm-mode llm` 对旧 PayAssist、PayGate 生效，PayChain 目前无 LLM 适配器；`--dry-run` 必须使用确定性模式。新版 CLI 始终调用真实 SUT 模型，离线验证走单元测试。

benchmark 可直接运行本地受信源码，不依赖 Docker。在线 `arena run/smoke` 仍需要 Docker 与角色模型凭据；网关将指定 SUT 模型路由到 `host.docker.internal:18081/v1`。**容器连接尚未实测**，本机 Docker daemon 在本次检查时未启动。

2026-10-01 旧版 A01：8/19 通过、11 失败、无执行错误，是原未修复靶标的基线，见[旧基线 JSON](docs/references/research/STUDIO_4B_BASELINE_2026-10-01.json)。新版已实现 6 场景、23 用例，两次重复共 46 次真实模型运行，正常任务严格通过 14/20；具体失败及攻击结果见[总方案 §3.3](../docs/RESEARCH_PLAN.md#33-多轮-payassist-l0l1当前开发基线2026-10-01)。两版提示词、执行与评分不同，不能直接比较通过率。新开发从 [payment_agents/README](payment_agents/README.md) 进入。

## 评测口径与资料

同时观察越权尝试、实际模拟付款、正常任务完成和攻击下合法任务完成。`guarded` 拦截落账不能证明目标已经修好；全部拒付不能作为支付任务的合格修复。

注册表当前有 43 条规格/7 类系统，其中 22 条有支付适配路径，21 条未支持；它与修复晋级仍是独立入口。benchmark 区分 `passed / failed / error / unsupported`，退出码分别为全过 `0`、明确失败 `1`、错误或未支持 `2`。规格数、支持数和通过数不能混用。

支付 PDF、RSI 研究计划、技术规格、修复者预注册与实验记录均在 [docs/INDEX.md](docs/INDEX.md)。完整能力评估与后续验收只维护在[总研究方案](../docs/RESEARCH_PLAN.md)，测试结果维护在[根 README](../README.md)。
