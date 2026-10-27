# redteam-platform（任务 10 骨架 + 任务 11 BYOK）

REDTEAM 平台后端的配置、加密托管、链绑定与 BYOK 模型客户端。本阶段包含：

- `redteam_platform.config`：从环境变量与 `contracts/deploy/addresses.json` 读取并校验配置；
- `redteam_platform.custody`：AES-256-GCM + scrypt 的本地加密 vault（W 私钥、守方 BYOK Key）；
- `redteam_platform.chain`：加载五合约 ABI / 校验地址与 chainId 的只读 web3.py 绑定；
- `redteam_platform.byok`：守方自带 Key 的白名单模型客户端（provider/base_url/model 由平台固定，调用方只传 api_key）。

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

校验规则：`provider`、`base_url`、`model` 非空；`base_url` 仅接受 http(s)，
非 loopback 的 http 拒绝；loopback（`localhost`、`127.0.0.0/8`、`::1`）可用
http；允许 path（如 `/v1`），拒绝 userinfo、query 与 fragment。`base_url` 尾斜杠
会被移除。客户端固定 POST `{base_url}/chat/completions`，请求体含
`model/messages/tools/parallel_tool_calls=false/temperature=0/max_tokens`。

错误分两类：HTTP 401/402/403/429/5xx 与 transport/timeout/connection 为
`ModelError.kind == "infrastructure"`；3xx、其余 4xx、坏 JSON/schema、空 choices、
响应模型不匹配、响应超过 2 MB 为 `"agent_protocol"`。客户端使用 no-redirect
opener 拒绝跟随 3xx，因此不会把 `Authorization: Bearer <key>` 发往重定向目标。
含 CR/LF/NUL 或其他控制字符的 api_key 在构造时以 `ValueError` 拒绝，错误消息
不回显 key。具体异常均为 `ModelUnavailable(ModelError)`；客户端不重试，
重试/弃权由 runner 处理。

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

## 测试

```bash
cd platform
.venv/Scripts/python -m pytest tests -q    # Windows
# 或：python -m pytest tests -q
```

测试不联网：chain 的 `verify_chain` 用假 provider 注入；custody 使用临时目录和
较低的 scrypt 参数（`scrypt_n=2**14`，仅测试；生产默认 `2**15`）；BYOK 测试拦截
低层 socket/`HTTPConnection.connect` 并注入假 transport / 假 HTTPS 响应，覆盖
allowlist/URL 校验、请求体、错误分类、3xx 不跟随、api_key 控制字符、不重试与
密钥泄漏断言。当前全套 **173 passed**（config/custody/chain 64 + BYOK 109）。

## 安全约定

- 不提交 vault、`.venv`、私钥或任何真实 API Key。
- 错误信息与日志不得包含 secret；custody 已按此实现。
- 本阶段不实现密钥轮换/多主密钥、custody 访问审计，也不实现 FastAPI/uvicorn
  （审计落点见计划任务 12/14；均在后续任务）。
