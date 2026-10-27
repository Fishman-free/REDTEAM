# redteam-platform（任务 10 骨架）

REDTEAM 平台后端的配置、加密托管与链绑定骨架。本阶段只包含：

- `redteam_platform.config`：从环境变量与 `contracts/deploy/addresses.json` 读取并校验配置；
- `redteam_platform.custody`：AES-256-GCM + scrypt 的本地加密 vault（W 私钥、守方 BYOK Key）；
- `redteam_platform.chain`：加载五合约 ABI / 校验地址与 chainId 的只读 web3.py 绑定。

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
| `MODEL_ALLOWLIST_JSON` | `{}` | JSON object；任务 11 再填供应商 |

生成主密钥（只在本机保存，例如密码管理器/密钥管理系统）：

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

```bash
export PLATFORM_MASTER_KEY=<上一步输出>
export CHAIN_RPC=http://127.0.0.1:8546
```

vault 文件不会自动创建；首次 `Custody.store()` 会创建目录（0700，best effort）
并以临时文件 + fsync + `os.replace` 原子写入（0600，best effort）。
`platform/vault.json` 已在 `.gitignore` 中，禁止提交。丢失主密钥将无法恢复
vault 内容。

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

## 测试

```bash
cd platform
.venv/Scripts/python -m pytest tests -q    # Windows
# 或：python -m pytest tests -q
```

测试不联网：chain 的 `verify_chain` 用假 provider 注入；custody 使用临时目录和
较低的 scrypt 参数（`scrypt_n=2**14`，仅测试；生产默认 `2**15`）。

## 安全约定

- 不提交 vault、`.venv`、私钥或任何真实 API Key。
- 错误信息与日志不得包含 secret；custody 已按此实现。
- 本阶段不实现密钥轮换/多主密钥，也不实现 FastAPI/uvicorn（后续任务）。
