# redteam-platform（任务 10–14：骨架 / BYOK / runner / indexer / 数据服务）

REDTEAM 平台后端的配置、加密托管、链绑定、BYOK 模型客户端与智能体 runner。本阶段包含：

- `redteam_platform.config`：从环境变量与 `contracts/deploy/addresses.json` 读取并校验配置；
- `redteam_platform.custody`：AES-256-GCM + scrypt 的本地加密 vault（W 私钥、守方 BYOK Key）；
- `redteam_platform.custody_audit`：custody 访问的薄审计包装（只记录元数据）；
- `redteam_platform.chain`：加载五合约 ABI / 校验地址与 chainId 的只读 web3.py 绑定；
- `redteam_platform.byok`：守方自带 Key 的白名单模型客户端（provider/base_url/model 由平台固定，调用方只传 api_key）；
- `redteam_platform.runner`：每赛一个智能体会话，攻方隔离线程、资格测试、预算与停服；
- `redteam_platform.agent_tools`：固定工具面 `get_balance` / `transfer_rtm`，W 私钥真实签名；
- `redteam_platform.transcripts`：按 join 时 `dataConsent` 决定是否落盘；
- `redteam_platform.indexer`：链事件 → SQLite → 攻方/守方/矿工/挖矿榜（含烟测排除与 runner 停服回调）；
- `redteam_platform.faucet_signer`：Faucet EIP-712 票据签发（audited key、nonce、captcha）；
- `redteam_platform.data_service`：consent-aware 数据集 bundle / operator publish / 切片交付；
- `redteam_platform.rsi_export`：挖矿攻破 → RSI findings（仅 `rsi_only` 数据，不进 DataMarket）。

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

## Faucet 票据（任务 14）

`faucet_signer.FaucetSigner` 签 `Faucet.sol` 的 EIP-712 票据：

- 域：`name="RTM Faucet"`、`version="1"`、`chainId`、`verifyingContract=faucet`；
  类型：`Ticket(address to,uint256 nonce,uint64 deadline)`；`TICKET_TYPEHASH` 与合约一致。
- `to`、`nonce`、`deadline` 绑定；nonce 取 `max(链上 nonces(to), 本进程已签发)+1`，
  也可显式传入（必须更大）；deadline 默认 `now + ticket_ttl`，限制在 `max_ttl` 内。
- 每次签名都通过 `AuditedCustody.load(signer_entry)` 取 key，context 为
  `{purpose:"faucet_ticket", recipient, chain_id, ticket_count:"1"}`；key 不缓存在
  实例、不写日志、错误/repr 不含 key。
- `captcha_required=True` 时构造器必须拿到 `captcha_verifier`，否则拒绝启动；
  每次 `sign` 必须提供 verifier 接受的 token。开发模式显式传 `False`。
- 可选 `expected_signer` 校验 key 派生地址与部署的 `ticketSigner` 一致。

```python
from eth_account import Account
from redteam_platform.faucet_signer import FaucetSigner

signer = FaucetSigner(
    custody=audited,
    signer_entry="faucet-signer",
    faucet_address=addresses["faucet"],
    chain_id=addresses["chainId"],
    nonce_lookup=lambda to: chain.contracts["Faucet"].functions.nonces(to).call(),
    captcha_required=True,
    captcha_verifier=verify_hcaptcha,   # sync callable(token)->bool
    expected_signer=addresses["ticketSigner"],
)
ticket = signer.sign(user_address, captcha_token=token)
# 前端把 ticket.to/nonce/deadline/signature 交给 Faucet.claim
```

**边界**：`_last_issued` 只在进程内；重启或多进程签发可能重复给出同一个未领取
nonce（合约仍禁止二次领取，但后一张票据作废）。任务 15/运维需单进程签发或加
持久化 nonce 存储。本次测试用 `recover_message` 验证签名与合约 EIP-712 摘要一致，
并用 ABI 断言 tuple 字段；未部署 Faucet 到 eth-tester（依赖未安装），真链 claim
留给任务 17 e2e。

## 数据服务（任务 14）

`data_service.DataService`：

- `bundle(contest_id)` 只打包**普通赛**且 `dataConsent=true` 的攻方 transcript +
  守方自有文件（`defender/contest.json`、可选 `defender/session.json`）。即使磁盘
  上存在 opt-out 或 `rsi_only` 文件，也会按 indexer 同意与记录字段过滤；矿工数据
  永不进入 bundle。未结束/挖矿/被排除（烟测）比赛直接拒绝。
- 根 = 排序文件 `sha256` 拼接后再 `sha256`（规格允许的简化）；`manifest.json`
  列出每个文件的路径/哈希/大小与排除统计（只含地址，不含内容），manifest 本身
  不进入根。买家可用 manifest 的叶子重算根并与链上 `datasetRoot` 比对。
- `publish(contest_id)` 只对已结束普通赛，先查链上根未发布，再由
  `ChainDataMarketWriter` 用 operator key 调 `DataMarket.publish`。operator key
  每次经 `AuditedCustody` 读取，context `{purpose:"data_publish", contest_id}`，
  不缓存、不记录 secret。
- `deliver_own(contest_id, buyer)` / `deliver_attacker(contest_id, buyer, attacker)`：
  只允许该场 defender；分别交付守方文件或该攻方 transcript 的 ZIP 切片，附完整
  manifest；返回一次性 `Delivery`（token、zip 路径、root、过期时间）。token 只在
  进程内保存，默认 600s；任务 15 负责鉴权、按 `DataSold` 事件调用与下载服务。
- 交付前会核对 bundle 根与链上已发布根一致；数据在发布后变化则拒绝交付。

```python
from redteam_platform.data_service import ChainDataMarketWriter, DataService

writer = ChainDataMarketWriter(
    chain.w3, chain.contracts["DataMarket"], audited,
    settings.operator_key_entry, settings.chain_id,
)
service = DataService(
    indexer, Path("data/transcripts"), Path("data/bundles"), writer=writer,
)
result = service.publish(contest_id)
own = service.deliver_own(contest_id, defender)
attacker = service.deliver_attacker(contest_id, defender, attacker_address)
```

**边界**：bundle 与交付 token 缓存在进程内；重启后重建 bundle 必须与链上根一致。
简化根不含 Merkle 证明，切片靠完整 manifest 校验；task 15 不要向未购买者返回
manifest 之外的他人内容。ZIP 通过 `Deliverable.token` 由 API 鉴权后提供，不要
把 token 写入日志。

## RSI 导出（任务 14）

`rsi_export.RsiExporter.export_breach(contest_id)` 只读挖矿赛
`purpose=rsi` / `rsi_only=true` 的矿工 transcript 与 session snapshot，输出：

- `case_id`/`contest_id`、`attacker`、`attack_goal`；
- `turns`：每轮 miner message、agent reply、tool_calls、error；
- `evaluation`：`outcome=breach`、`breach_classes`（含 `wrong_recipient`，
  有成功转账再加 `successful_transfer`）、observed transfers、固定奖励、忽略记录数；
- `snapshot`：session、扁平 messages、turns、链上 contest/breach。

只允许已 settled 的挖矿赛；普通赛、未结算、缺 snapshot/transcript、非 RSI 记录、
重复 turn 一律拒绝。导出文件写到调用方指定的输出目录（建议
`platform/data/rsi/<cid>.json`，gitignored），**不得上传 DataMarket**；其中包含
矿工消息与智能体回复，按敏感 RSI 数据处理。导出后由人工/离线修复流程进入
campaign_repair，本模块不自动触发修复。

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
形状断言；task 14 覆盖 EIP-712 票据恢复/captcha/nonce、consent-aware bundle/
publish/切片交付/下载 token/篡改检测、RSI 导出过滤与 schema、operator key 审计。
当前全套 **348 passed**（config 30 / custody 16 / chain 18 / BYOK 138 / runner 相关
96 / indexer 22 / faucet 10 / data 11 / rsi 7）。

## 安全约定

- 不提交 vault、`.venv`、私钥或任何真实 API Key。
- 不提交 `platform/data/`（transcript、bundle、RSI 导出、custody 审计日志、索引库）；
  攻方/矿工数据不得进入仓库。
- 错误信息与日志不得包含 secret；custody 与审计包装已按此实现。Faucet 票据与
  下载 token 是能力凭证，不写日志；RSI 导出含矿工消息与智能体回复，不得上传
  DataMarket。
- 本阶段不实现密钥轮换/多主密钥，也不实现 FastAPI/uvicorn（任务 15）；
  custody 审计已由任务 12 的 `custody_audit` 落盘，v1 无审计查询接口。
