# TEE 可信执行环境：概念、必要性、接入操作手册

> **状态**：v1，2026-10-31
> **当前代码事实**：线上与仓库只有 `simulated` 档；`hardware` 档**未实现、未验收**。
> **读者**：下一个接手 RTM Arena / BYOA 的 agent 或工程师。
> **先读**：§0、§3、§4、§10。读完再改代码。

---

## 0. 硬性规则（先读，违反任意一条都算事故）

1. **不许把 `simulated` 说成 TEE，也不许说成保密保证。** 模拟器只验证协议流程。
2. **没有真实硬件 quote 与外部验签，不许写 `attestationTier=1` 或 `hardware`。**
3. **不许让平台进程重新拿到以下任何一项**：W 私钥、TEE 签名私钥、X25519 解密私钥、攻方明文、守方配置明文。
4. **所有证明检查 fail closed。** 字段缺失、验签失败、nonce 过期、compose hash 不一致，一律拒绝；不许用重试、降级或默认值“修好”。
5. **租用付费云资源、部署、重置链，必须先得到用户明确同意。** 本仓库的部署由用户自己执行。
6. **API Key、私钥、钱包密钥不进仓库、不进日志、不贴聊天。** Phala Key 放本地环境变量或未跟踪的 `.env`。
7. **改档位必须同时改四处**：后端校验、`/api/meta`、dApp 标签、本文档。少一处就是对外虚假宣传。
8. **未经用户要求不要 commit / push。**（本文件创建时也未提交。）

---

## 1. 一页结论

- **TEE 是什么**：CPU 提供的一块硬件隔离执行区，配合“远程证明（remote attestation）”，让外部验证者能确认**某段代码、某个配置**确实运行在**真实硬件**里，并且应用可以把新鲜数据绑进硬件签名。
- **这个项目为什么需要**：BYOA 的核心卖点是“三方保密”——守方的 prompt/代码/密钥不能被平台看到，攻方的数据不能被守方看到，平台不能伪造攻破或代签。谁运行 agent，谁就能看到输入；因此 agent 必须跑在平台和守方都不完全控制的中立机密环境里。
- **怎么接**：没有捷径。顺序是 **P0 硬件试点（代码已写，未跑）→ P1 平台验签与运行时抽象 → P2 CVM 内服务化（driver/wallet/egress）→ P3 配置加密与 KMS → P4 生产加固**。在 P2 完成前，平台仍然能解密或代签，不能宣称硬件档。

---

## 2. TEE 是什么

### 2.1 一句话定义

TEE（Trusted Execution Environment，可信执行环境）是 CPU 内部的一块隔离区域。操作系统、Hypervisor、云厂商管理员即使拥有 root，也不能读取这块区域内的内存或注入代码。CPU 还能为这块区域签发**远程证明**，让远端验证者确认里面跑的到底是什么。

对区块链/agent 场景，真正有用的不是“隔离”本身，而是 **隔离 + 可验证的身份**：

> 我能证明：这段密文只会被一份哈希为 X 的代码、在一台真实的 TDX 机器上解密；运行它的云厂商看不到明文，也换不掉代码。

### 2.2 五个必须分清的概念

| 概念 | 含义 | 在本项目里的对应物 |
|---|---|---|
| **Measurement（度量值）** | 对代码、配置、启动过程的密码学哈希。换一个字节，值就变。 | dstack 的 `compose_hash`（整个 compose 的哈希）；链上字段 `runtimeMeasurement` |
| **Quote（证明报告）** | CPU 私钥签名的二进制报告，内含度量值、`report_data`、TCB 版本等。 | `/attestation` 返回的 `quote`（hex） |
| **report_data** | quote 里 64 字节的“应用自定义区”。硬件保证它不可篡改，但**不保证它有意义**——意义由验证者定义。 | 试点：`nonce(32B) || sha256(binding)(32B)` |
| **Attestation（远程证明）** | 用厂商根证书链验证 quote 的过程，例如 Intel DCAP、AWS Nitro attestation。 | `verify_pilot.py` 调 Phala API；生产建议 `dcap-qvl` 本地验签 |
| **Sealed key / KMS** | 只有度量值匹配时才释放或派生密钥，重启后密钥可恢复。 | dstack `DstackClient.get_key()`；当前**未使用**，试点密钥是启动时随机生成、重启即丢 |

### 2.3 一次远程证明的时序

```text
验证者                           CVM（TEE 内）                      CPU / 厂商
  │                                  │                                  │
  │ 1. 生成随机 nonce ──────────────▶│                                  │
  │                                  │ 2. 读自身 compose_hash            │
  │                                  │ 3. 组装 binding，算 sha256        │
  │                                  │ 4. report_data = nonce||digest    │
  │                                  │ 5. get_quote(report_data) ───────▶│ 签名
  │                                  │◀──────────── quote ──────────────│
  │◀── 6. quote + binding + 签名 ────│                                  │
  │ 7. 验证 quote 链、report_data、   │                                  │
  │    compose hash、binding 签名     │                                  │
  │ 8. 通过 → 记录 hardware           │                                  │
```

关键点：

- **nonce 必须由验证者生成，一次性，短有效期。** 否则旧的 quote 可以重放。
- **binding 必须包含验证者关心的全部身份**：守方地址、链 ID、合约地址、镜像 digest、compose hash、TEE 公钥、钱包地址。否则攻击者可以把 A 的 quote 嫁接到 B 的注册上。
- **quote 里的度量值和 `report_data` 都由硬件签名。** 应用自己返回的 `measurement`、`verified: true` 字段都不可信，必须从 quote 解出来。
- **compose hash 不等于镜像 digest。** compose 里引用 `image@sha256:...`；验证者要同时核对 event log 里的 compose hash 和 compose 里的镜像 digest。

### 2.4 技术选型

| 平台 | 优点 | 注意 |
|---|---|---|
| **Intel TDX** | 虚拟机级隔离，适合多容器 compose；Phala dstack 生态成熟 | 需要 TDX 机型；TDX 模块/固件版本会影响 quote 验证 |
| Intel SGX | 进程级，成熟度高 | 内存受限，容器化改造大，已不是主流新项目首选 |
| AMD SEV-SNP | VM 级，云上可用 | 证明格式与工具链不同，需要另一套验签 |
| AWS Nitro Enclaves | 与 AWS 集成好 | 绑定 AWS，无通用 compose 语义 |
| ARM CCA | 新 | 生态与云可用性仍在早期 |

**当前试点选 Phala Cloud 的 dstack + TDX CVM**，理由是：compose 直接变成可证明的部署单元、`compose_hash` 天然适合作为链上 `bytes32` 度量值、按分钟计费适合验证。**这不是最终决定**，见 §11。

本机（Intel Core Ultra 9 275HX）**不支持 TDX**，普通 VPS 也不支持。真实证明必须租用机密机型，或由用户提供现成 CVM URL。

### 2.5 TEE 能证明什么、不能证明什么

**能证明：**

1. 某段代码/配置（度量值 X）确实在真实 TEE 硬件里运行；
2. 某段 `report_data` 由该硬件签名，因而与新鲜 nonce 绑定；
3. 密钥只在匹配度量值的环境里可用（前提是正确使用 KMS）；
4. 宿主管理员无法直接读 TEE 内存或替换被测代码；
5. 配置中途被换会改变度量值，从而被发现。

**不能证明：**

1. **应用逻辑正确。** 代码被证明“是这份代码”，不代表它没漏洞、没后门。
2. **模型厂商保密。** 出网白名单里的第三方模型仍然看得到 prompt（见 §3.4）。
3. **守方端点诚实。** 端点是不是“与守方无关”，技术上无法证明，只能声明 + 审核。
4. **侧信道。** 时序、缓存、功耗等侧信道不在远程证明范围内。
5. **可用性。** 宿主可以拒绝服务、关机、限流；TEE 不保证在线。
6. **供应链上游。** 镜像构建前被投毒，度量值只会忠实记录“被投毒的镜像”。
7. **用户设备。** 攻方浏览器被入侵，TEE 无能为力。
8. **GPU 推理。** 除非使用支持机密计算的 GPU；一期不使用 GPU TEE。

---

## 3. 为什么这个项目需要 TEE

### 3.1 BYOA 的三方保密需求

规格 `docs/superpowers/specs/2026-10-29-byoa-defender-design.md` §3 定义了 R1–R5：

| 编号 | 要求 |
|---|---|
| R1 | 守方配置对攻方和平台都不可见：prompt、harness、代码、工具、模型 key、策略 |
| R2 | 攻击数据对守方不可见，只能通过数据市场、按攻方同意购买 |
| R3 | 普通攻方自己选择平台能否看到攻击数据；挖矿层规则不变 |
| R4 | 四种守方接入方式全部支持：MCP/skills、A2A、webhook、MCP 拉取 |
| R5 | “三方保密”是技术保证，不是政策承诺；测试网可用模拟器但必须标注 |

矛盾在于：

- agent 跑在守方那边 → 平台看不到配置（满足 R1），但守方能看攻方消息（违反 R2）；
- agent 跑在平台那边 → 平台能看到一切（违反 R1），攻方数据也暴露（违反 R2/R3）；
- 只有跑在**平台和守方都不完全控制**的中立机密环境里，R1、R2、R3、R5 才能同时成立。

这就是 TEE 的位置：守方的东西只解密给匹配的度量值，攻方的消息只加密给 TEE 公钥，平台只做密文中继。

### 3.2 它顺带关闭的三个真实缺口

以当前 `simulated` 档为准，平台进程同时持有 W 私钥、TEE 签名私钥、X25519 解密私钥（`platform/redteam_platform/byoa/sealed.py:237`）。因此：

1. **平台可以伪造攻破。** W 私钥在平台手里，平台可以绕过守方 agent，直接构造“守方付错钱”的交易，再声称是攻方攻破。
2. **平台可以读守方配置与攻方明文。** 模拟档下 `sealed_turn` 直接在平台进程解密（`service.py:576` 起），再把明文转发给守方端点。
3. **守方可以赛中换配置。** 没有硬件度量值，链上的 `runtimeMeasurement` 只是守方自己填的哈希，平台无法验证端点真的跑那个镜像；守方可以在比赛开始后换 prompt 或“写死不付款”。

TEE 档要解决的是这三点，而不是“加一层加密”。

### 3.3 硬件档必须能证明的具体命题

下一代实现验收时，必须能对每条命题给出证据（不能只写“已支持”）：

| 编号 | 命题 |
|---|---|
| C1 | 守方 bundle 注册时，平台验证了真实 TDX quote，且 quote 的 `report_data` 绑定了本次 nonce 与 bundle 身份 |
| C2 | quote 的 compose hash 与 bundle 的 `runtimeMeasurement` 一致，compose 内的镜像 digest 与 `image_digest` 一致 |
| C3 | `teeSigner`、`wallet`、`teePubKey` 由 CVM 内生成，平台从未持有其私钥 |
| C4 | 攻方密文只在 CVM 内解密；平台 API 与数据库无明文路径 |
| C5 | 回复由 CVM 内 TEE 密钥签名，签名可在链上 `teeSigner` 处验证 |
| C6 | 比赛中更换配置会改变度量值，且平台能在结算前发现并拒绝/罚没 |

### 3.4 必须向参与者披露的残余风险

- **TEE 厂商与管理栈**：2026-10 Phala dstack 披露过 guest-agent 漏洞，导致客户日志和环境变量泄露（硬件密钥本身未受影响）。TEE 不是“无漏洞”的同义词。
- **模型厂商**：出网白名单里的模型端点能看到 prompt 和对话。守方必须在出网声明里公开这些端点，攻方据此判断泄漏风险。
- **端点归属**：白名单端点是否真的与守方无关，只能靠声明 + 平台审核。
- **可用性**：CVM 可以被宿主停掉；比赛结算需要超时与争议路径。
- **一期链上不验签**：quote 在链下验证，链上只记录 tier 和原始 quote 的哈希/位置；复验依赖平台公开的原始 quote。二期才考虑链上 DCAP。

---

## 4. 当前实现状态（诚实基线）

| 组件 | 现状 | 证据 |
|---|---|---|
| 运行时 | 只有 `SimulatedSealedRuntime`，W/TEE/解密键都在平台进程内 | `platform/redteam_platform/byoa/sealed.py:237` |
| 模拟证明 | `tier="simulated"`，`quote` 字段实际是 EIP-191 签名，不是硬件 quote | `sealed.py:171` |
| 度量值 | `compute_measurement()` 对文件名 + 内容做 SHA-256，**是 dstack compose_hash 的占位实现** | `sealed.py:117` |
| 硬件校验 | `verify_attestation()` 遇到 `tier="hardware"` 且没有 verifier 时直接抛错 | `sealed.py:202` |
| 注册入口 | `register_bundle()` 对非 `simulated` 返回 422 | `service.py:171` |
| 服务装配 | `ByoaService(...)` 未传 `runtime_factory` / `hardware_verifier` | `platform/redteam_platform/api.py:1934` |
| `/api/meta` | 硬编码 `"attestationTiers": ["simulated"]` | `api.py:1860` |
| 链上字段 | `attestationTier`（uint8）、`teeSigner`、`teePubKey`、`runtimeMeasurement`、`configCommitment` 已存在 | `chain_gateway.py:546`、合约 `Arena`、`dapp/src/pages/Byoa.tsx:214` |
| dApp | 已显示 simulated/hardware 徽章，并明确 simulated 不提供隔离保证 | `Byoa.tsx:592`、`Docs.tsx` |
| 部署模板 | `deploy/byoa/compose.simulator.yaml` 四服务布局是模板，driver/wallet 镜像未构建 | `deploy/byoa/README.md` |
| 硬件试点 | `deploy/byoa/tee-pilot/` 已写：CVM 证明服务、外部验证器、compose、Dockerfile、14 个离线测试 | 本目录；**尚未在真实 TDX 上运行，未提交** |
| KMS / 配置加密 / 链上 DCAP | 全部未实现 | — |

**今天能证明的：**

- 模拟档下 BYOA 全流程（注册 → 创建 → 任务 → 密文回合 → 回复验签）能跑通；
- 信封使用 X25519 + HKDF-SHA256 + AES-256-GCM，`msgHash=keccak256(ct)` 与链上绑定；
- 验证器逻辑会对篡改 fail closed（14 个离线测试）。

**今天不能证明的：**

- 任何硬件隔离；
- 平台看不到明文；
- 平台不能代签；
- 守方端点真的运行了登记的镜像；
- 比赛中无法更换配置。

---

## 5. 目标架构与数据流

### 5.1 架构

```text
攻方浏览器 ──E2E 密文──▶ BFF/API（只看到密文与 hash）
                              │
                              ▼
        ┌──────────── Sealed Runtime（TEE CVM，有 quote）────────────┐
        │  arena-driver       解密、签发主人任务、驱动回合、签名回复   │
        │  defender container 守方 harness/代码/工具（不透明镜像）     │
        │  wallet sidecar     W 私钥 + L3 策略 + MCP 钱包工具          │
        │  egress proxy       出网白名单（模型、结构化 oracle）        │
        │  transcript sealer  按同意规则封存/丢弃                      │
        └────────────────────────────────────────────────────────────┘
                │ W 签名的交易              │ 密封信封
                ▼                           ▼
        Besu 链（Arena/RTMToken/TaskSink）  平台存储（只有密文/hash）
```

### 5.2 启动时序（硬件档）

1. CVM 启动，dstack guest agent 就绪；
2. 从 KMS 派生/获取 TEE 签名键、W 私钥、X25519 私钥（**不落盘、不进环境变量**）；
3. 读取自身 `tcb_info.app_compose`，算 compose hash；读取 compose 内镜像 digest；
4. 平台生成一次性 nonce（绑定守方地址与过期时间）；
5. CVM 组 binding → `report_data = nonce || sha256(binding)` → `get_quote()`；
6. CVM 返回 quote、event log、binding、binding 签名；
7. 平台（或独立验证者）验 quote 链、`report_data`、compose hash、镜像 digest、签名；
8. 通过后，CVM 用 TEE 键签 `TeeWalletBinding`，平台提交 `createByoaContest`，链上 tier=1；
9. 平台保存原始 quote 与验证记录，提供公开复验接口。

### 5.3 一个回合（硬件档）

1. 攻方从**链上**读取 `teePubKey`、`teeSigner`、`runtimeMeasurement`（不信任平台 API 返回值）；
2. 攻方加密到 `teePubKey`，链上 `attack(cid, keccak256(ct))` 付款；
3. 平台校验付款事件、成员身份、同意状态、重放（现有逻辑保留），把密文转发给 CVM driver；
4. driver **自己**校验链上付款与成员身份（不能只信平台），解密、运行守方 agent；
5. driver 用攻方公钥封装回复，用 TEE 键签名，返回 `{reply_envelope, reply_signature, seq}`；
6. 平台 `markDelivered(..., replyHash)`，把信封转给攻方；
7. 攻方本地解密，用**链上** `teeSigner` 验签。

### 5.4 不可破坏的不变量

| 不变量 | 检查方式 |
|---|---|
| 平台无 W 私钥 | 硬件 runtime 不提供 `wallet_key_for_tools()`；签名在 CVM 内完成 |
| 平台无解密私钥 | `sealed_turn` 只转发密文，不在平台调用 `open_attack()` |
| 平台无 TEE 签名私钥 | `sign_typed_data` / `sign_reply` 都是 CVM 远程调用 |
| CVM 只签它能独立重建的结构 | CVM 用自己的度量值、公钥、地址重建 binding；不签平台给的任意 message |
| 一个 nonce 只能用一次 | 挑战存储：单次消费 + TTL（建议 600s）+ 绑定 defender |
| 旧 quote 不能重放 | nonce 新鲜性 + binding 内含 defender/chainId/arena |
| 平台不能把 A 的证明嫁接到 B | binding 覆盖 defender、imageDigest、composeHash、keys |
| 档位不虚标 | `tier=hardware` 只在全部检查通过后写入；UI/API 同步 |

---

## 6. 接入路线（按顺序做，不要跳）

### P0：跑通最小硬件试点（代码已就绪）

**目标**：回答“我们的代码能否在真实 TDX 里生成可验证 quote，并把签名键 + 钱包地址 + 新鲜 nonce 绑上去”。

**产物**：`deploy/byoa/tee-pilot/`

- `cvm/pilot_app.py`：CVM 内 HTTP 服务，启动时生成 signer 与 wallet，`/attestation?nonce=` 返回 quote 与签名；
- `binding.py`：canonical JSON、binding hash、签名文本；
- `verify_pilot.py`：外部验证器，检查 binding 签名、`report_data`、TDX quote、compose hash；
- `test_verify_pilot.py`：14 个离线测试；
- `compose.yaml`、`cvm/Dockerfile`、`README.md`。

**DoD**：

1. `python -m unittest -v test_verify_pilot.py` 全绿；
2. 真实 CVM 上 `verify_pilot.py --url ...` 输出 `{"ok": true, ...}`；
3. 保存完整输出作为证据文件（建议 `docs/evidence/tee-pilot-YYYY-MM-DD.json`）；
4. 立即销毁 CVM，停止计费；
5. 明确记录：试点密钥是**启动时随机生成、重启丢失**的，不能用于生产。

**成本**：`tdx.small`（1 vCPU / 2 GB）约 $0.058/h，20 GB 磁盘约 $0.0028/h，合计约 **$0.061/h**；3 小时约 **$0.18**。

### P1：平台侧硬件证明与运行时抽象

**目标**：平台能验证硬件 quote，并把“本地模拟运行时”替换成“远程 CVM 客户端”，但**不改变**已上线的 simulated 行为。

**代码改动**：

1. 新增 `platform/redteam_platform/byoa/attestation.py`
   - `AttestationChallengeStore`：单次 nonce、TTL、绑定 defender；
   - `HardwareAttestationVerifier`：DCAP 本地验签（推荐 `dcap-qvl`）或 Phala API 兜底；
   - `verify_hardware_attestation(attestation, expected_bundle) -> VerifiedAttestation`。
2. 扩展 `sealed.py`
   - 保留 `Attestation` 兼容 simulated；
   - 新增 `HardwareAttestation` 字段：`nonce`、`report_data`、`event_log`、`compose_hash`、`image_digest`、`wallet`、`expires_at`；
   - `verify_attestation()` 的 hardware 分支必须由真正的 verifier 实现，且返回可审计记录。
3. 新增 `sealed.py::HardwareSealedRuntime`
   - 实现与 `SimulatedSealedRuntime` 相同的方法签名；
   - `attest()` 走 CVM `/attestation`；
   - `sign_typed_data()`、`open_attack()`、`seal_reply()`、`sign_reply()` 全部是 CVM 远程调用；
   - **不得**实现 `wallet_key_for_tools()`，或实现为直接抛 `NotImplementedError`。
4. 新增 API
   - `POST /byoa/attestation/challenges`：认证后返回 `{nonce, expires_at}`；
   - `POST /byoa/bundles` 请求体新增 `attestation` 对象；
   - `GET /byoa/bundles/{bundle_id}/attestation`：公开返回原始 quote、event log、验证时间、验证器版本（便于任何人复验）。
5. 修改 `service.py::register_bundle`
   - `hardware` 档不再直接 422；先消费 challenge、验 quote、验 compose hash/镜像 digest、验签名，再写 tier；
   - 任何一步失败 → 422/403，且不落库。
6. 修改 `api.py`
   - `/api/meta.attestationTiers` 按配置返回 `["simulated", "hardware"]`，不能硬编码；
   - `ByoaService` 注入 `runtime_factory` 与 `hardware_verifier`。
7. dApp
   - `attestationTier=1` 时才显示“硬件证明”，并提供“复验 quote”入口；
   - simulated 文案不变。

**建议的 attestation JSON**（P1 设计，未实现）：

```json
{
  "tier": "hardware",
  "nonce": "<hex64>",
  "issuedAt": 1760000000,
  "teeSigner": "0x...",
  "wallet": "0x...",
  "teePubKey": "0x...",
  "measurement": "0x...",
  "imageDigest": "sha256:...",
  "reportData": "<128 hex>",
  "bindingHash": "0x...",
  "binding": { "...": "..." },
  "bindingSignature": "0x...",
  "quote": "<hex>",
  "eventLog": [ ... ]
}
```

> 字段名以上是试点/链上习惯的 camelCase；平台现有 API 用 snake_case（如 `attestation_tier`）。实现时以 `platform/redteam_platform/api.py` 的请求模型为准，但**binding 的 canonical JSON 必须固定一套命名并写进版本号**，否则哈希对不上。

**binding 必须覆盖**：`domain`（版本化，如 `RTM BYOA ATTESTATION v2`）、`defender`、`chainId`、`arena`、`imageDigest`、`composeHash`、`teeSigner`、`wallet`、`teePubKey`、`nonce`、`issuedAt`。CVM 自己填度量值和密钥，平台只填 defender/chainId/arena/nonce。

**验证顺序（必须按这个顺序，任何一步失败即拒绝）**：

1. challenge 存在、未过期、未消费、defender 匹配；
2. 重算 canonical binding → SHA-256；
3. `report_data[0:32] == nonce` 且 `report_data[32:64] == digest`；
4. quote 通过 DCAP（Intel 根链）或 Phala 验签，且 quote 内 `report_data` 与上面一致；
5. event log 中 `compose-hash` 的 payload == `measurement` == `tcb_info.app_compose` 的 SHA-256；
6. compose 中镜像 digest == bundle 的 `image_digest`；
7. `bindingSignature` 由 `teeSigner` 签出，且 binding 内字段与请求一致；
8. `teePubKey`、`wallet`、`teeSigner` 与 CVM `/info` 一致；
9. 全部通过后，标记 challenge 已消费，写 tier=hardware，保存原始 quote 与验证器版本。

**DoD**：

- 正向：真实 CVM 注册成功，链上 tier=1；
- 反向：篡改 nonce / wallet / report_data / quote / compose hash / 镜像 digest / 签名，逐一被拒；
- 重放：同一个 challenge 第二次注册被拒；
- 跨守方：A 的 quote 注册到 B 的 bundle 被拒；
- 回归：`pytest` 全绿，simulated 流程不受影响。

### P2：CVM 内服务化（driver / wallet / egress）

**目标**：平台不再解密、不再持有 W 私钥、不再能代签。

**代码改动**：

1. 把 `deploy/byoa/compose.simulator.yaml` 变成真实 `compose.yaml`：
   - 镜像按 digest 固定；
   - `defender` 只连 `sealed` 内网；
   - 只有 `egress` 连外网；
   - wallet 私钥只在 wallet sidecar 内，不通过环境变量导出。
2. driver 暴露 CVM 内部/受控端点：`/attestation`、`/info`、`/turn`、`/binding-sign`；
3. `service.py::sealed_turn` 在硬件档改为：
   - 平台做完付款/成员/重放检查后，把密文 POST 给 driver；
   - driver 自己读链确认 `AttackPaid` 与成员身份（不能只信平台），再解密并运行；
   - 平台只接收 `reply_envelope`、`reply_signature`、`seq`，不接触明文；
4. `create_contest` 的 `sign_typed_data` 改为向 driver 请求签名；driver 只签它自己能重建的 `TeeWalletBinding`；
5. wallet 路径：把 `PLATFORM_BYOA_WALLET_URL` 指向 CVM 内 wallet MCP；平台只持有会话 token；
6. 删除或禁用 `wallet_key_for_tools()` 的硬件路径，并加测试防止回归。

**DoD**：

- 抓包/日志检查：平台进程内无明文、无私钥；
- 用平台自己的日志和数据库导出，证明没有 prompt、回复明文、W 私钥；
- 故意停掉 driver，平台应返回 502，而不是本地降级解密；
- 重放同一 `msgHash` 仍被拒（现有 `_delivered_turns` + 链上 `deliveredMsg` 保留）。

### P3：配置加密与 KMS

**目标**：守方配置（system prompt、模型 key、工具配置、L1 规则）只释放给匹配的度量值。

**代码改动**：

1. 定义加密配置包格式（版本、算法、KDF、密文、接收者度量值）；
2. 平台只存储密文包与 hash；CVM 通过 dstack KMS `get_key()` 或按度量值释放的密钥解密；
3. 配置包与 `configCommitment` 绑定；
4. 密钥轮换与撤销流程；
5. 日志/异常路径脱敏测试。

**DoD**：

- 平台数据库、日志、API 响应中搜索不到配置明文；
- 换 compose/镜像后，旧配置包无法解密；
- 配置包被篡改时 fail closed。

### P4：生产加固

- 镜像可复现构建 + CI provenance + 固定 digest；
- 多宿主/多区域与故障转移；
- 证明过期、TCB 降级、固件漏洞的响应流程；
- 监控：attestation 失败率、quote 过期、CVM 重启、度量值变化；
- 争议与仲裁：CVM 不可用时的退款/延期路径；
- 二期可选：链上 DCAP 验证、GPU TEE 机密推理；
- 安全审计与渗透测试，尤其是 quote 解析、nonce 存储、并发消费。

---

## 7. 操作手册：跑通最小硬件验证

> 以下命令与 `deploy/byoa/tee-pilot/README.md` 一致。执行前确认用户同意产生费用。

### 7.1 前置条件

1. Phala Cloud 账号与 API Key（`phak_...`），放本地环境变量或 `~/.phala`，**不要贴聊天、不要提交**；
2. Docker Desktop 已启动，能构建 `linux/amd64`；
3. 一个镜像仓库（Docker Hub / GHCR；私有仓库用 `DSTACK_DOCKER_USERNAME` / `DSTACK_DOCKER_PASSWORD`）；
4. 本机验证器依赖：`eth-account`、`eth-utils`（项目 `platform/.venv` 已有）；
5. `npm install -g phala`。

### 7.2 构建并推送镜像

```bash
cd deploy/byoa/tee-pilot
docker build --platform linux/amd64 -f cvm/Dockerfile \
  -t <registry>/rtm-tee-pilot:0.1 .
docker push <registry>/rtm-tee-pilot:0.1
```

部署时优先使用 digest（`@sha256:...`），compose hash 才稳定。

### 7.3 部署 TDX CVM

```bash
export TEE_PILOT_IMAGE='<registry>/rtm-tee-pilot@sha256:...'
phala login            # 交互登录；不要回显或提交 Key
phala deploy -n rtm-tee-pilot -c compose.yaml -t tdx.small --disk-size 20G --wait
phala cvms get rtm-tee-pilot
```

如果 CLI 没读到 `TEE_PILOT_IMAGE`，在 `deploy/byoa/tee-pilot/.env` 写入（该文件已被 `.gitignore` 忽略）。

### 7.4 外部验证

```bash
cd deploy/byoa/tee-pilot
../../../platform/.venv/Scripts/python.exe verify_pilot.py --url https://<cvm-public-url>
```

成功输出示例：

```json
{
  "ok": true,
  "binding": {"nonce": "...", "signer": "0x...", "wallet": "0x...", "bindingHash": "0x..."},
  "hardware": {"verified": true, "teeTcbSvn": "..."},
  "compose": {"composeHash": "..."},
  "appId": "app_...",
  "instanceId": "..."
}
```

失败输出 `{"ok": false, "error": "..."}` 并非零退出。

### 7.5 常见失败

| 现象 | 原因 | 处理 |
|---|---|---|
| `docker version` 连不上 npipe | Docker Desktop 未启动 | 启动 Docker Desktop；不要伪造构建成功 |
| `/attestation` 返回 503 | 容器内没有 `/var/run/dstack.sock` | 检查 compose volume 挂载 |
| quote 验签 API 返回 403 | 当前出口 IP 被 Cloudflare 拦截 | 换网络，或改用 `dcap-qvl` 本地验证；**不能把“请求没发出去”当通过** |
| compose hash mismatch | `/info.app_compose` 与 event log 不一致，或镜像非 digest 固定 | 用 digest 重新部署 |
| 验证器报 `hardware report_data differs` | binding 与 quote 不一致 | 检查 nonce 与 canonical JSON 是否一致 |
| 重启后 signer/wallet 变了 | 试点密钥是启动时随机生成 | 试点预期行为；生产必须用 KMS 派生 |

### 7.6 停止计费

验证完成后立即在 Phala 控制台停止并删除 CVM。停止只收磁盘费，删除后停止全部计费。

### 7.7 本地离线测试（无需 TEE）

```bash
cd deploy/byoa/tee-pilot
../../../platform/.venv/Scripts/python.exe -m unittest -v test_verify_pilot.py
```

这些测试用合成 quote，只证明验证器会拒绝篡改，**不构成硬件证明**。

---

## 8. 证据与验收矩阵

| 要证明的结论 | 需要的证据 | 谁来复验 |
|---|---|---|
| 运行在真实 TDX | DCAP 验证通过的 quote + TCB 信息 | 任何人用 Intel 根链 / `dcap-qvl` |
| 代码/配置未被替换 | quote 内 compose hash + event log + 镜像 digest | 对照 compose 文件重算 |
| 绑定是新鲜的 | 验证者生成的 nonce 在 `report_data` 前 32 字节 | 重算并比对 |
| 密钥属于这次注册 | binding 签名由 `teeSigner` 签出 | `ecrecover` |
| 平台看不到明文 | 平台日志/数据库/抓包无明文；`sealed_turn` 无本地解密路径 | 代码审查 + 运行时检查 |
| 平台不能代签 | 平台进程无私钥；签名请求只在 CVM 内完成 | 代码审查 + 密钥扫描 |
| 回复来自 TEE | 链上 `teeSigner` 验签通过 | 攻方浏览器独立验签 |
| 换配置会被发现 | 度量值变化 + 平台结算前检查 | 负向测试 |

**反模式（出现即拒绝验收）：**

1. 直接信任 CVM 返回的 `verified: true`；
2. 用 `/info` 的 `report_data` 代替 quote 内的 `report_data`；
3. 只验签名，不验 quote 链；
4. 只验 compose hash，不验镜像 digest；
5. nonce 复用、无 TTL、不绑定 defender；
6. 验证失败后自动降级到 simulated 并继续注册；
7. 把平台数据库里的 `runtime_measurement` 当成硬件事实；
8. 在平台进程保留 `wallet_key_for_tools()` 的硬件调用路径；
9. 把“试点的合成 quote 测试通过”写成“硬件已验证”。

---

## 9. 代码地图

| 路径 | 作用 | 硬件档要改什么 |
|---|---|---|
| `platform/redteam_platform/byoa/sealed.py` | 承诺、度量、证明、模拟运行时 | 新增 `HardwareSealedRuntime`、硬件证明类型与验签入口 |
| `platform/redteam_platform/byoa/service.py` | bundle 注册、创建比赛、回合、结算 | 放开硬件档、接入 challenge/verifier、`sealed_turn` 改为远程转发 |
| `platform/redteam_platform/byoa/wallet.py` | L3 钱包策略与会话 | 硬件档只保留会话 token，签名在 CVM |
| `platform/redteam_platform/byoa/envelope.py` | X25519 + HKDF + AES-GCM 信封 | 不变（已与 dApp 互通） |
| `platform/redteam_platform/byoa/adapters.py` | 四种接入适配 | driver 在 CVM 内调用，平台不接触明文 |
| `platform/redteam_platform/byoa/egress.py` | 出网声明校验 | 与 CVM 内 Envoy 配置一致性检查 |
| `platform/redteam_platform/api.py` | `/byoa/*`、`/api/meta` | 新增 challenge/attestation 端点；meta 不再硬编码 |
| `platform/redteam_platform/chain_gateway.py` | `createByoaContest` 参数 | tier=1 只在验签后传入 |
| `contracts/` | `Arena` / `TaskSink` / `TeeWalletBinding` | 已支持字段；二期再考虑链上 DCAP |
| `dapp/src/pages/Byoa.tsx` | 档位徽章、注册向导、加密聊天 | 增加“复验 quote”入口 |
| `dapp/src/pages/Docs.tsx` | 用户文档 | 硬件档上线后更新文案 |
| `deploy/byoa/compose.simulator.yaml` | 四服务模板 | 变成真实 compose，固定 digest |
| `deploy/byoa/egress.yaml` | Envoy 白名单 | 按 bundle 声明渲染 |
| `deploy/byoa/tee-pilot/` | 最小 TDX 试点 | 先跑通，再抽取到平台 |

---

## 10. 下一个 agent 的执行清单

### 开始前

1. 读本文 §0、§3、§4、§10；
2. 读规格 `docs/superpowers/specs/2026-10-29-byoa-defender-design.md` §3、§4、§15；
3. 跑 `platform` 现有测试，确认 simulated 基线是绿的；
4. 查当前线上 `/api/meta` 的 `attestationTiers`，确认没有擅自上线 hardware；
5. 确认用户是否已授权租用/部署。

### 做的时候

1. 先做 P0，拿到真实 quote 证据；没有证据不写 P1；
2. P1 的所有校验写负向测试（篡改、重放、跨守方、过期）；
3. 硬件 runtime 不实现 `wallet_key_for_tools()`；
4. `sealed_turn` 的硬件路径不允许本地解密；
5. 每次改档位，同步 `/api/meta`、dApp 标签、本文档；
6. 日志里不打印 quote 以外的敏感字段，不打印任何私钥/Key/明文。

### 完成后

1. 附证据文件（真实 quote 验证输出、负向测试结果）；
2. 跑 `pytest`、`npm run build`、合约测试；
3. 更新 `docs/INDEX.md`；
4. 更新 `deploy/byoa/README.md` 与 dApp 文档；
5. 明确写出仍未完成的部分，不夸大。

### 永远不要

1. 自动重部署、自动重置链；
2. 未经授权租用付费算力；
3. 把 API Key、私钥、钱包密钥贴到聊天或提交到仓库；
4. 在没有硬件 quote 的情况下标记 hardware；
5. 用“测试通过”代替“硬件已验证”；
6. 为了让流程跑通而放宽验签或跳过 nonce 检查。

---

## 11. 开放问题（需要用户/架构决策）

1. **托管方**：Phala Cloud、GCP/Azure TDX、AWS Nitro，还是自建 TDX 集群？决定 quote 格式、验签工具与成本模型。
2. **链上验证**：一期链下验签 + 公开原始 quote 已够，还是必须链上 DCAP？后者 gas 与合约复杂度显著上升。
3. **密钥持久化**：dstack KMS 派生是否满足“重启不丢、跨镜像不串”？需要在真实 CVM 上验证路径与释放策略。
4. **driver 的链上信任**：driver 是否直连 Besu RPC 自行验证付款，还是接受平台签名声明？前者更安全，后者更简单。
5. **升级策略**：比赛进行中允许升级 CVM 吗？升级会改变度量值，是否需要暂停/迁移/重签绑定？
6. **多租户**：一台 CVM 跑一个守方，还是多个守方共享？共享需要更强的进程级隔离与密钥隔离。
7. **GPU 推理**：二期是否要求模型在 GPU TEE 内运行？成本与可用性需评估。
8. **证明有效期**：quote 多久过期？到期后比赛是否继续？需要链上/平台规则。
9. **争议路径**：CVM 不可用、证明失败、度量值变化时，质押与结算如何仲裁。

---

## 12. 术语表

| 术语 | 解释 |
|---|---|
| CVM | Confidential VM，机密虚拟机 |
| TDX | Intel Trust Domain Extensions，Intel 的 VM 级 TEE |
| DCAP | Intel 的 quote 验签基础设施与规范 |
| Quote | CPU 签名的证明报告 |
| report_data | quote 内 64 字节应用自定义区 |
| Measurement | 代码/配置的密码学哈希 |
| compose_hash | dstack 对整个 compose 计算的哈希 |
| Remote attestation | 远端验证 quote 的过程 |
| Sealed storage / KMS | 按度量值释放或派生密钥的机制 |
| BYOA | Bring Your Own Agent，守方自带 agent |
| W | BYOA 中由 TEE 生成并托管的热钱包地址/密钥 |
| TeeWalletBinding | 链上绑定 defender、wallet、度量值、TEE 公钥的 EIP-712 结构 |
| simulated | 当前唯一的证明档位，无硬件隔离，仅验证流程 |
| hardware | 目标档位，需要真实 quote 与外部验签，尚未实现 |

---

## 13. 参考

- 规格：`docs/superpowers/specs/2026-10-29-byoa-defender-design.md`（§3 信任模型、§4 架构、§15 未决问题）
- 交接：`docs/superpowers/HANDOFF-2026-10-29.md`（§16 BYOA 实现记录）
- 运行模板：`deploy/byoa/README.md`
- 硬件试点：`deploy/byoa/tee-pilot/README.md`
- 试点验证器：`deploy/byoa/tee-pilot/verify_pilot.py`
- 试点测试：`deploy/byoa/tee-pilot/test_verify_pilot.py`
- 当前运行时：`platform/redteam_platform/byoa/sealed.py`
- 当前服务：`platform/redteam_platform/byoa/service.py`
- 用户文档中的档位说明：`dapp/src/pages/Docs.tsx` 第 08 节
