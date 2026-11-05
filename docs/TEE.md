# SoftTEE：BYOA 守方软件隔离、配置承诺与接入手册

> **状态**：v2，2026-11-06。取代 v1 的硬件 TEE 路线。
> **当前代码事实**：`simulated`、`softtee`、`self-hosted` 三档；**没有硬件 TEE 档**。
> **先读**：§0、§2、§4、§6。读完再改代码。
>
> 相关文档：产品级说明书 [`MANUAL.md`](MANUAL.md) · 企业接入
> [`byoa/SOFTTEE.md`](byoa/SOFTTEE.md) · 部署 [`../deploy/README.md`](../deploy/README.md)。

---

## 0. 硬性规则

1. **不许把 SoftTEE 说成硬件 TEE。** 它是软件隔离 + 可测量启动 + 测量绑定密钥库；
   拥有宿主 root 的平台可以读进程内存、改内核或伪造测量。
2. **不许把 `simulated` 说成保密保证。** 它只用于本地开发与回归测试。
3. **不许让平台持久化 W 私钥、回复签名私钥或配置明文。**
   当前 SoftTEE 运行时以独立模块运行，配置只在运行时内存中使用；平台不落盘明文。
   P2 与 API 同进程，平台进程权限仍可访问；P5 会把运行时拆成独立容器，届时 API 进程不接触明文。
4. **所有检查 fail closed。** 度量不符、配置承诺不符、签名无效、v2 载荷缺 `configHash`，
   一律拒绝；不许用重试、降级或默认值“修好”。
5. **密钥与 API Key 不进仓库、不进日志、不贴聊天。** `SOFTTEE_HOST_SECRET` 只写入
   `deploy/.env.stack`，不打印。
6. **改档位必须同时改四处**：合约、平台校验、`/api/meta`、dApp 标签。少一处就是虚假宣传。
7. **部署与重置链由用户决定。** 本仓库的部署脚本不自动重置链。

---

## 1. 一页结论

- **SoftTEE 是什么**：一个独立的 Python 运行时（当前 `platform/redteam_platform/byoa/` 模块，
  P5 拆成容器），持有 W 私钥、回复签名键和 X25519 解密键；密钥库用
  `HKDF(host_secret, runtimeMeasurement)` 派生 AES-256-GCM 密钥加密。运行文件变化 → 测量变化 →
  密钥库打不开 → 拒绝启动/签名。
- **它解决什么**：守方临时改 prompt/工具/模型/配置、平台 API 意外拿到明文、普通进程越权、
  攻方伪造回复、写死拒付的 agent 白拿效用分。
- **它不解决什么**：恶意平台/宿主 root、恶意内核、物理攻击、侧信道、模型厂商看到 prompt。
- **链上标记**：`attestationTier=0/1/2`（simulated/softtee/self-hosted），
  `replySigner`、`runtimeMeasurement`、`configCommitment` 都可链上读取。

---

## 2. 威胁模型

| 威胁 | SoftTEE 档 | 自托管档 |
|---|---|---|
| 守方赛中改 prompt/工具/模型 | 检测到 configHash 变化，拒绝签名/判违约 | 官方 SDK 会申报变化；改 SDK 后仍可撒谎 |
| 守方换运行文件 | 测量变化，密钥库打不开 | 不适用 |
| 平台 API 意外读配置 | API 不持久化明文；P2 同进程，P5 拆容器后才完全隔离 | 配置从不提交 |
| 攻方伪造回复 | v2 签名 + 链上 replySigner 验签 | 同左 |
| 平台 root 读内存 | **挡不住**，必须在 UI/文档披露 | **挡不住** |
| 模型厂商看 prompt | 挡不住；出网声明里公开 | 挡不住 |
| 写死“拒绝对手方” | 开放任务漏做，效用违约 | 开放任务漏做，效用违约 |

结论：SoftTEE 提供的是**诚实宿主上的完整性、可检测篡改与 API 进程隔离**，不是硬件保密。

---

## 3. 运行时组成

```text
browser ──HTTPS──> api
   │                 │ 不持久化明文；保存承诺与密文回合
   │                 ▼
   │        SoftTEE runtime (measured module / P5 container)
   │           ├─ keystore: W / reply key / X25519 (AES-256-GCM, measurement-bound)
   │           ├─ config bundle: prompt/tools/model/key/mandate/open ratio
   │           ├─ task ledger: closed/open tasks, random payees, armTask
   │           ├─ wallet: transfer / armTask / task issue via RPC
   │           ├─ agent: model tool loop or defender endpoint
   │           └─ attestation: signed statement, optional TPM quote
   ▼
attacker ──E2E ciphertext──> api ──relay──> SoftTEE
```

### 3.1 测量

`runtimeMeasurement = sha256(`

```text
for each file in SOFTTEE_RUNTIME_FILES, sorted:
    relative path \0 sha256(bytes) \n
```

`)`

覆盖 `byoa/` 下的运行时、策略、任务、钱包、信封与 `signatures.py`。平台用自己的镜像重算并比对；
不一致即拒绝注册。

### 3.2 密钥库

```text
key  = HKDF-SHA256(host_secret, salt=measurement, info="RTM BYOA SOFTTEE KEYSTORE v2")
file = AES-256-GCM(key, nonce, json({walletKey, teeKey, x25519Key}))
```

- `host_secret` 由 `deploy/up.sh` 生成，只出现在 `deploy/.env.stack`，不打印。
- measurement 改变 → GCM 解密失败 → `AttestationError("softtee keystore cannot be opened ...")`。
- 同一 measurement 重启 → 同一 W/签名者/X25519，比赛可恢复。
- 比赛进行中，每个回合都会重算运行文件测量与配置承诺；变化时该条退费并计违约
  （3 次判弃权）。运行中的 Python 已加载代码不会被热替换，但文件/配置变化会被发现。

### 3.3 Attestation

`teeSigner` 对 canonical JSON 签名：

```json
{
  "domain": "RTM BYOA SOFTTEE ATTESTATION v2",
  "tier": "softtee",
  "measurement": "0x...",
  "configCommitment": "0x...",
  "teePubKey": "0x...",
  "teeSigner": "0x...",
  "runtime": {"driver": "1", "files": 12},
  "rootOfTrust": "software",
  "tpmRooted": false,
  "tpmQuote": null,
  "issuedAt": 0
}
```

平台校验签名、measurement、configCommitment、tier。`tpmRooted=true` 必须带 `tpmQuote`；
一期不把 TPM quote 作为链上放行条件，UI 必须显示 `software` 还是 `TPM`。

### 3.4 回复 v2

```text
RTM BYOA reply v2
contest: <cid>
attacker: <checksum address>
msgHash: <0x..>
replyHash: <0x..>
seq: <n>
configHash: <0x..>
```

- SoftTEE：`configHash == configCommitment`，签名者 `replySigner == teeSigner`。
- 自托管：`replySigner` 由守方提供，必须与 `teeSigner` 不同；`configHash` 必须等于开赛承诺。
- 缺签名、签名无效、configHash 不符：按超时处理（退费 + 计次），累计 3 次判弃权。

---

## 4. 接入步骤

### 4.1 快速接入（SoftTEE）

1. 打开 `/byoa`，选择 `SoftTEE · software isolation`。
2. 填写 system prompt、模型 Base URL、Model、API Key、工具、开放任务占比（≥30%）、难度。
3. 钱包签所有权证明 → 注册 Bundle。平台返回 `config_hash`、`tee_signer`、`reply_signer`。
4. 签名 `ByoaMandate`（包含 `replySigner`、`configCommitment`）→ 创建比赛。
5. 平台生成闭合/开放任务；守方 agent 通过钱包 MCP 的 `vendor_directory` / `contact_vendor`
   核实发票账户后付款。
6. 攻方在 `/byoa` 用比赛 id 发送 E2E 密文；回复由 SoftTEE 签名并带 `configHash`。

### 4.2 企业接入

- 自带模型/agent endpoint；配置包由企业自己加密给 SoftTEE 公钥。
- 也可自带 SoftTEE endpoint；平台校验 attestation/measurement 后接入。
- 页面必须显示 `SoftTEE · 软件隔离`，不得显示“硬件”。

### 4.3 自托管

- 填 endpoint、`reply_signer`、`config_commitment`；最低质押 100 tRTM。
- 守方 SDK 在每条回复中返回 `metadata = {"reply_signature": "0x...", "config_hash": "0x..."}`。
- 守方能看到攻击明文；这是调试档，不进入主榜。

---

## 5. 合约字段与检查

| 字段 | 含义 |
|---|---|
| `attestationTier` | 0=simulated，1=softtee，2=self-hosted |
| `teeSigner` | 创建时绑定钱包的运行时签名者 |
| `replySigner` | 回复 v2 签名者；SoftTEE 等于 teeSigner，自托管必须不同 |
| `runtimeMeasurement` | 运行时文件测量 |
| `configCommitment` | 配置承诺；SoftTEE 等于 configHash |
| `MIN_SELF_HOSTED_STAKE` | 100 tRTM |

`createByoaContest` 检查：

- tier ≤ 2；
- SoftTEE/simulated：`replySigner == teeSigner`；
- self-hosted：`replySigner != teeSigner` 且 `stake >= 100e18`；
- 守方 EIP-712 与运行时绑定签名都有效。

`TaskSink` 检查：

- 新任务带 `payeeCommit = keccak256(abi.encode(taskHash, payee, salt))`；
- `armTask` 只能由签发人在转账前揭示 payee；
- `consume` 只在 `to == 锁定 payee` 且金额精确匹配时完成；
- 资金记入 TaskSink，结算时退回守方。

`RTMToken` 靶分支：

1. 转给已登记攻方 → `onBreach`；
2. 转给已锁定 payee 且金额匹配 → TaskSink 消费；
3. 其余 → `TargetTransferRestricted`。

`DataMarket` 分账：tier 2 平台 50%/攻方 50%，其余 70%/30%。

---

## 6. 运维

### 6.1 环境变量

```text
PLATFORM_SOFTTEE_HOST_SECRET   # 64 hex；只写 deploy/.env.stack，不打印
PLATFORM_SOFTTEE_STATE_DIR     # 默认 /data/softtee
PLATFORM_ALLOW_CUSTOM_MODEL_ENDPOINTS=true
```

`deploy/up.sh` 首次生成 secret；旧 `.env.stack` 缺少时自动追加，不打印。

### 6.2 状态

- `/data/softtee/<defender>.json`：加密密钥库；不要手工改，不要提交。
- `/data/platform-state.sqlite3`：守方注册与会话元数据；重启恢复仍适用。
- 备份：`rtm-arena_rtm-platform-data` 卷。
- 轮换 `PLATFORM_SOFTTEE_HOST_SECRET` 会让所有旧密钥库打不开；必须先退役/重开比赛。

### 6.3 失败模式

| 现象 | 含义 | 处理 |
|---|---|---|
| `softtee keystore cannot be opened` | 运行文件/measurement 变了 | 检查镜像是否被改；重开比赛 |
| `measurement changed; refusing to attest` | 运行时检测到漂移 | 停止签名，按守方违约处理 |
| `attestation config commitment does not match` | 配置承诺不符 | 拒绝注册/判违约 |
| `self-hosted reply is missing its v2 signature` | 守方 SDK 未签名 | 退费 + 计次 |
| `defender reply signature is invalid` | 签名者/configHash 不符 | 退费 + 计次 |

---

## 7. 验证清单

- [ ] 修改任一运行文件 → measurement 变化，密钥库无法解密。
- [ ] 修改配置 → configHash 变化，回复被拒。
- [ ] 同一 measurement 重启 → 同一 teeSigner/W/X25519。
- [ ] SoftTEE attestation 签名、measurement、configCommitment 全部校验。
- [ ] v2 回复签名覆盖 contest/attacker/msgHash/replyHash/seq/configHash。
- [ ] 自托管 replySigner ≠ teeSigner，stake ≥ 100 tRTM。
- [ ] 开放任务 ≥30%，随机 payee，armTask 后才可付款。
- [ ] 写死拒绝对手方的 agent 开放效用不达标。
- [ ] 3 次超时退费并判弃权。
- [ ] 平台 API 进程不持有 W/回复私钥（P5 容器化后复核）。

---

## 8. 与硬件 TEE 的关系

硬件 TEE（Intel TDX / AMD SEV-SNP / AWS Nitro）能提供远程 quote 和抗宿主 root 的隔离；
SoftTEE 不能。2026-11-05 用户裁决只用 SoftTEE，因此：

- 删除 `attestationTier=1` 的 hardware 语义；
- `deploy/byoa/tee-pilot/` 是历史试点，不再接入产品；
- 文档与 UI 禁止出现“硬件证明 / 硬件级保密 / Intel TDX 保证”。

如果未来重新引入硬件 TEE，应作为新的 tier（例如 3），而不是改写 SoftTEE 的保证。
