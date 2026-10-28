# redteam-platform（任务 10 骨架 + 任务 11 BYOK + 任务 12 runner + 任务 13 indexer）

REDTEAM 平台后端的配置、加密托管、链绑定、BYOK 模型客户端与智能体 runner。本阶段包含：

- `redteam_platform.config`：从环境变量与 `contracts/deploy/addresses.json` 读取并校验配置；
- `redteam_platform.custody`：AES-256-GCM + scrypt 的本地加密 vault（W 私钥、守方 BYOK Key）；
- `redteam_platform.custody_audit`：custody 访问的薄审计包装（只记录元数据）；
- `redteam_platform.chain`：加载五合约 ABI / 校验地址与 chainId 的只读 web3.py 绑定；
- `redteam_platform.byok`：守方自带 Key 的白名单模型客户端（provider/base_url/model 由平台固定，调用方只传 api_key）；
- `redteam_platform.runner`：每赛一个智能体会话，攻方隔离线程、资格测试、预算与停服；
- `redteam_platform.agent_tools`：固定工具面 `get_balance` / `transfer_rtm`，W 私钥真实签名；
- `redteam_platform.transcripts`：按 join 时 `dataConsent` 决定是否落盘；
- `redteam_platform.indexer`：链事件 → SQLite → 攻方/守方/矿工/挖矿榜（含烟测排除与 runner 停服回调）。

> 包名是 **`redteam_platform`**，不是 `platform`：Python 标准库自带 `platform`
> 模块，使用同名顶层包会在 `import platform` 时冲突。目录名 `platform/` 仅作为
> 仓库顶层组件，安装后的导入名始终是 `redteam_platform`。

## 环境要求

- Python 3.11+（当前在 Python 3.14 上验证）
- 已部署的 Besu 测试网（RPC `http://127.0.0.1:8546`）与 R4 新地址
- 先编译合约以生成 ABI：`cd contracts && npx hardhat compile`

## 安装

```bash
cd platform
python -m venv .venv
.venv/Scripts/activate        # Windows（Git Bash 可用 source .venv/Scripts/activate）
pip install -e ".[dev]"
```

`.venv/` 不提交。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `PLATFORM_MASTER_KEY` | 无（必需，仅 Custody 使用） | 32 字节 hex 主密钥；**不要写入仓库** |
| `PLATFORM_ADDRESSES_PATH` | `contracts/deploy/addresses.json` | 地址登记文件 |
| `PLATFORM_ARTIFACTS_DIR` | `contracts/artifacts` | Hardhat artifacts 根目录 |
| `PLATFORM_VAULT` | `platform/vault.json` | vault 文件路径（gitignored） |
| `CHAIN_RPC` | 地址文件 `rpc`，再回退 `http://127.0.0.1:8546` | 仅接受 http(s) |
| `CHAIN_ID` | 地址文件 `chainId`（当前 `48850`） | 正整数，支持 `0x` 前缀 |
| `CHAIN_TIMEOUT` | `15` | RPC 超时秒数 |
| `OPERATOR_KEY_ENTRY` | `operator` | keystore **条目名**，不是密钥 |
| `FAUCET_SIGNER_ENTRY` | `faucet-signer` | keystore **条目名**，不是密钥 |
| `MODEL_ALLOWLIST_JSON` | `{}` | 模型白名单 JSON object；构造 `ByokClient` 时读取（见下） |

生成主密钥（只在本机保存，例如密码管理器/密钥管理系统）：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```bash
export PLATFORM_MASTER_KEY=<上一步输出>
export CHAIN_RPC=http://127.0.0.1:8546
```

vault 文件不会自动创建；首次 `Custody.store()` 会以临时文件 + fsync +
`os.replace` 原子写入（文件 0600，best effort）。只有 Custody **新建**的目录才会
尝试 chmod 0700；默认路径的父目录 `platform/` 在仓库中已存在，Custody 不会
修改它的权限。`platform/vault.json` 已在 `.gitignore` 中，禁止提交。丢失主密钥
将无法恢复 vault 内容。`Custody` 提供 `store(entry_id, secret)`、
`load(entry_id)` 与 `delete(entry_id)`；删除只移除条目，不实现密钥轮换。

## 合约地址与 ABI

- 唯一有效地址：`contracts/deploy/addresses.json`（R4）。旧地址已作废。
- ABI 读取自 `contracts/artifacts/src/<Name>.sol/<Name>.json`，合约映射为
  `RTMToken`、`Arena`、`Faucet`、`DataMarket`、`Treasury`。
- 缺少 ABI 时会提示先在 `contracts/` 运行 `npx hardhat compile`。
- 本模块不读取私钥、不发交易；`ChainClient` 构造只做本地文件 I/O，
  `verify_chain()` 才访问 RPC。

```python
from redteam_platform.config import load_settings
from redteam_platform.chain import ChainClient
from redteam_platform.custody import Custody

settings = load_settings()
client = ChainClient(settings)
client.verify_chain()          # 校验 RPC chainId == settings.chain_id
arena = client.contracts["Arena"]

custody = Custody(settings.vault_path)   # 从 PLATFORM_MASTER_KEY 读取主密钥
```

## BYOK 模型客户端

`ByokClient(provider, api_key)` 只接受 provider 与 API key；`base_url` 与 `model`
必须来自 `MODEL_ALLOWLIST_JSON`，构造器不接受覆盖。allowlist 在**构造时**读取，
因此不存在 import 时缓存；API key 由调用方从 Custody 取出，只保留在实例内，
不写入 URL/请求体/磁盘，也不会出现在 repr 或错误消息中。

```bash
export MODEL_ALLOWLIST_JSON='{
  "glm": {"base_url": "https://glm.example.com/v1", "model": "glm-5.3"},
  "qwen-local": {"base_url": "http://127.0.0.1:18081/v1", "model": "Qwen/Qwen3-4B-Instruct-2507"}
}'
```

校验规则：allowlist 条目只允许 `base_url` 与 `model` 两个字段，其他字段（尤其
`api_key`）一律拒绝，返回的配置只保留这两个安全字段；若 `Settings.model_allowlist`
里混入额外字段，传入 `ByokClient` 会在构造时失败。`provider`、`base_url`、`model`
非空；`base_url` 在 strip 前按原始值校验，只接受可见 ASCII（0x21–0x7E），拒绝
C0/C1/DEL、空白、非 ASCII、反斜杠、userinfo、query 与 fragment；允许 path（如
`/v1`）；非 loopback 的 http 拒绝，loopback（`localhost`、`127.0.0.0/8`、`::1`）
可用 http。`base_url` 尾斜杠会被移除；`base_url`/`model` 以只读 property 暴露，
构造后不能覆盖。客户端固定 POST `{base_url}/chat/completions`，请求体含
`model/messages/tools/parallel_tool_calls=false/temperature=0/max_tokens`。

错误分两类：HTTP 401/402/403/429/5xx、transport/timeout/connection、
`RemoteDisconnected`/`IncompleteRead` 为 `ModelError.kind == "infrastructure"`；
3xx、其余 4xx、坏 JSON/schema、空 choices、响应模型不匹配、响应超过 2 MB、
`BadStatusLine`/`LineTooLong`/`IllegalHeader`、JSON 递归过深/NaN/Infinity 为
`"agent_protocol"`。具体异常均为 `ModelUnavailable(ModelError)`；客户端不重试，
重试/弃权由 runner 处理。

安全边界：客户端使用 no-redirect opener，3xx 不跟随，不会把
`Authorization: Bearer <key>` 发往重定向目标。**BYOK 默认直连，不使用
`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`**：opener 使用空 ProxyHandler，避免 key
被环境代理截获；若未来确需代理，必须由平台显式配置，并明确记录 key 会经过代理。
api_key 只接受可见 ASCII 0x20–0x7E；CR/LF/NUL、其他控制字符或非 ASCII 均在
构造时以 `ValueError` 拒绝，错误消息不回显 key。

```python
from redteam_platform.byok import ByokClient, ModelError
from redteam_platform.custody import Custody

custody = Custody(settings.vault_path)
api_key = custody.load("defender-byok:<entry>")   # 条目名由调用方决定
client = ByokClient("glm", api_key)
try:
    result = client.complete(messages, tools, max_tokens=1200, timeout=60)
    message, usage = result["message"], result["usage"]
except ModelError as exc:
    if exc.kind == "infrastructure":
        pass  # 守方基础设施故障：上层按弃权/罚没策略处理
    else:
        pass  # 模型输出/协议错误：不等于基础设施故障
```

## Runner（任务 12）

`runner.AgentSession` 为一场比赛持有一个守方智能体会话：

- 系统提示词只来自 `benchmark.interface.load_version(name).system_prompt(...)`；
  工具面固定为 `benchmark.harness.TOOL_DEFINITIONS`（只有 `get_balance` /
  `transfer_rtm`，没有 reply 工具）。
- 预算沿用 benchmark/payassist：每轮最多 10 步、120 秒、200k 上下文、单条攻方
  消息 1–1000 字符、每个模型回复最多 4 个工具调用、每个攻方最多 40 轮。
- 每个攻方地址有独立消息线程；`channel=external_dialogue` 与 `claimed_sender`
  由平台注入，永不从文本解析，且 external 永不携带 `owner_requests_execution`。
- `qualification(test_address)` 走 `verified_owner` 渠道，要求模型真实调用
  `transfer_rtm` 把 1 wei 转到平台测试地址；必须在 `createContest` 之前、W 尚未
  注册为靶且 W 至少有 1 wei 时调用。挖矿会话不跑资格测试。
- `attacker_turn(attacker, content, data_consent=...)`：普通赛必须显式传入 join
  时的链上同意值且不可撤回；挖矿会话强制 `True`。
- `stop(reason)` / `stop_for_mining(reason)`：停服并立即拒绝新消息；进行中的轮次
  在下一次模型调用或工具执行前停止。indexer 在 `Breach` / `MiningSettled` /
  `MiningRetired` 时必须调用（任务 13/14 接线）。
- 模型 `infrastructure` 错误返回 `defender_fault=True` 与 `fault_path`：挖矿为
  `retireMining`，普通赛为 `reportDefenderFault`。runner 自身不发 operator 交易。
- 工具失败（参数错误、revert、RPC 异常、非成功 receipt）统一返回
  `{"status":"failed","reason":"transfer failed"}`，不泄露
  `TargetTransferRestricted` 等 revert 原因（规格 §7.3）。
- 工具异常转为通用失败回执并继续会话，避免遗留未响应的 tool_call；未知工具、
  畸形模型输出按 `agent_protocol` 结束本轮。

数据持久化按 `transcripts.TranscriptStore`：

| 场景 | 落盘 | 标记 |
|---|---|---|
| 普通赛 `data_consent=true` | snapshot + 每轮消息/回复/工具轨迹 | `purpose=defender_dataset` |
| 普通赛 `data_consent=false` | 不创建任何文件/目录 | 仅内存 |
| 挖矿（强制同意） | 无条件落盘 | `purpose=rsi`、`rsi_only=true` |

runner 不写日志；`dataConsent=false` 的对话只存在内存。`transcript_root` 由调用方
指定，建议 `platform/data/transcripts`（已在 `.gitignore`）。挖矿数据只允许 RSI
导出使用，不得进入 DataMarket。

W 私钥必须通过 `agent_tools.WalletTools.from_custody(...)` 从
`custody_audit.AuditedCustody` 读取；每次 `Custody.load/store/delete` 都写
`{ts, action, entry_id, result, context}` JSONL 审计，只含元数据（purpose /
contest_id / runner_id / wallet_address；水龙头签票另含 recipient / chain_id /
ticket_count），绝不含 secret、攻方消息或工具轨迹。审计写入失败时成功操作也抛
`CustodyAuditError`（失败闭合）；v1 不提供审计查询 API。`entry_id` 必须是
标识符，不得把 secret 当 entry_id。

```python
from pathlib import Path

from benchmark.interface import load_version
from redteam_platform.agent_tools import WalletTools
from redteam_platform.byok import ByokClient
from redteam_platform.chain import ChainClient
from redteam_platform.config import load_settings
from redteam_platform.custody import Custody
from redteam_platform.custody_audit import AuditedCustody
from redteam_platform.runner import AgentSession

settings = load_settings()
chain = ChainClient(settings)
audited = AuditedCustody(Custody(settings.vault_path), Path("data/custody-audit.jsonl"))
tools = WalletTools.from_custody(
    audited,
    entry_id="wallet:<contest>",
    context={"purpose": "runner", "contest_id": contest_id, "wallet_address": wallet},
    w3=chain.w3,
    rtm_contract=chain.contracts["RTMToken"],
    wallet_address=wallet,
)
session = AgentSession(
    load_version("v0_demo"),
    ByokClient("glm", api_key),
    tools,
    wallet_address=wallet,
    mandate=mandate,
    contest_id=contest_id,
    transcript_root=Path("data/transcripts"),
    is_mining=False,
)
```

运行/导入路径：runner 依赖 `benchmark`（其又依赖 `payassist_agent`）。以仓库根为
工作目录并让以下两个路径可导入（POSIX 用 `:`，Windows 用 `;`）：

```bash
PYTHONPATH=".:rsi4safety/payment_agents" python -m ...
# Windows（Git Bash）示例：
PYTHONPATH="..;../rsi4safety/payment_agents" .venv/Scripts/python -m ...
```

`join(bytes32,uint256,bool)` 与 `joinMining(bytes32,bool)` 由任务 14 的 API 调用；
runner 不引用 `approveSale` 或旧 `accrue`。runner 信任调用方已完成链上
join/consent/AttackPaid 校验。

## Indexer 与排行榜（任务 13）

`indexer.EventIndexer` 把链事件幂等写入 SQLite（主键 `(block_number, log_index)`），
并从 Arena / RTMToken / DataMarket 事件维护聚合：

| 榜 | 字段 |
|---|---|
| 攻方 | `wins`、`rtm_won`（Breach + ContestSettled rest）、`difficulty`（攻破时该赛付费消息数）、`current_streak`/`longest_streak` |
| 守方 | `contests_survived`（仅 Expired）、`msgs_withstood`（Expired 赛的付费消息数）、`net_income = penalties - breach_loss`、`longest_survival`（秒） |
| 矿工 | `joined`、`decided_joined`（settled+retired）、`wins`、`rtm_won_fixed`、`difficulty`、`breach_rate = wins/decided_joined` |
| 挖矿 | `created/settled/retired/decided`、全局 `breach_rate`、`total_fixed_reward`、`active_versions`、`history` |

- **烟测排除**：构造时传 `excluded_contest_ids={addresses["smokeContestId"]}`；
  该类赛的原始事件仍以 `excluded=1` 入库，但不进入任何聚合/榜/回调。
- **部署注水 mint 排除**：不索引 `MiningMinted`；发行量只看已纳入比赛的
  `MiningSettled.reward`，因此 Faucet 1,000,000、Treasury 3、烟测补铸 1 都不计入。
- **唯一链事件源**：`ChainEventSource.from_chain_client(...)` 按 R4 ABI 拉取
  Arena 的 17 个事件、RTMToken 的 `Breach`、DataMarket 的发布/售出事件，并按
  `(block, log)` 排序；缺失 ABI 事件会报错，不会静默漏索引。
- **幂等同步**：`process_block_range(source, start, end)` 可重复执行；`last_block`
  只在整段成功后推进，重放不会重复计数。
- **停服回调**：构造时传 `on_mining_ended=(contest_id, event_name)->None`，在
  挖矿 `Breach`/`MiningSettled`/`MiningRetired` **首次**入库时触发；任务 14 用它
  调 `AgentSession.stop_for_mining`。回调抛错会回滚该事件，便于重试。
- **范围**：只索引公开链数据，不读私钥、不写 custody 审计、不提供 HTTP。
- **已知边界**：不处理链重组；SQLite 单写进程（进程内 RLock）；`MiningMinted`
  不进入原始事件表。`msgs_withstood`/`contests_survived` 采用“守到到期”口径，
  `breach_rate` 采用“已决挖矿赛”口径（见模块 docstring）。

```python
import json
from pathlib import Path

from redteam_platform.config import load_settings
from redteam_platform.chain import ChainClient
from redteam_platform.indexer import ChainEventSource, EventIndexer

settings = load_settings()
addresses = json.loads(settings.addresses_path.read_text(encoding="utf-8"))
smoke = addresses.get("smokeContestId")
chain = ChainClient(settings)
source = ChainEventSource.from_chain_client(chain)

with EventIndexer(
    Path("data/index.sqlite3"),
    network=addresses["network"],
    excluded_contest_ids=({smoke} if smoke else set()),
    on_mining_ended=lambda contest_id, name: ...,  # task 14: runners[contest_id].stop_for_mining(name)
) as index:
    index.process_block_range(source, 0, source.latest_block)
    boards = index.leaderboards()
```

`leaderboards()` 返回 `{"network", "attackers": {addr: {...}}, "defenders": {...},
"miners": {...}, "mining": {...}}`；`contest(id)`、`contest_attackers(id)`、
`data_consent(id, addr)` 供任务 14 数据服务使用。金额一律为十进制 wei 字符串，
避免 JS 精度与 SQLite 64 位整数溢出。

## 测试

```bash
cd platform
.venv/Scripts/python -m pytest tests -q    # Windows
# 或：python -m pytest tests -q
```

测试不联网：chain 的 `verify_chain` 用假 provider 注入；custody 使用临时目录和
较低的 scrypt 参数（`scrypt_n=2**14`，仅测试；生产默认 `2**15`）；BYOK 测试拦截
低层 socket/`HTTPConnection.connect` 并注入假 transport / 假 HTTPS 响应；runner
用脚本化模型、假钱包工具与假链，覆盖资格测试、线程隔离、预算、数据同意、
停服、弃权分流和 ABI 形状断言；indexer 用合成事件覆盖普通/挖矿/退役/到期/
弃权/罚款/同意、烟测排除、部署注水排除、幂等重放、停服回调、链事件源与 ABI
形状断言。当前全套 **320 passed**（config 30 / custody 16 / chain 18 / BYOK 138 /
runner 相关 96 / indexer 22）。

## 安全约定

- 不提交 vault、`.venv`、私钥或任何真实 API Key。
- 不提交 `platform/data/`（transcript、custody 审计日志、后续索引库）；攻方/矿工
  数据不得进入仓库。
- 错误信息与日志不得包含 secret；custody 与审计包装已按此实现。
- 本阶段不实现密钥轮换/多主密钥，也不实现 FastAPI/uvicorn（任务 14）；
  custody 审计已由任务 12 的 `custody_audit` 落盘，v1 无审计查询接口。
