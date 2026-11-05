# SoftTEE 接入指南与保证说明

> 面向：要接入 BYOA 的支付公司、企业安全团队、自托管开发者。  
> 完整产品说明见 [`../MANUAL.md`](../MANUAL.md)；技术手册见 [`../TEE.md`](../TEE.md)。

---

## 1. 一句话

SoftTEE 把守方的 W 私钥、回复签名键、X25519 解密键和解密后的配置放进一个**可测量、测量绑定密钥库**的软件运行时；平台不持久化配置明文，只记录承诺、密文回合和签名。它是软件隔离，不是硬件 TEE。当前运行时与 API 同进程（P5 拆独立容器）。

---

## 2. 能证明什么、不能证明什么

### 能证明（诚实宿主上）

1. 运行文件变化 → `runtimeMeasurement` 变化 → 密钥库打不开 → 拒绝启动/签名；
2. 配置变化 → `configHash` 变化 → 回复签名/承诺不一致 → 平台拒绝并计违约；
3. 每条回复由 `replySigner` 签名，覆盖 contest/attacker/msgHash/replyHash/seq/configHash；
4. 平台不持久化配置明文；P2 与 API 同进程，P5 容器化后 API 进程不接触明文；
5. 攻击原文只在运行时内解密；中继只看到密文与 hash。

### 不能证明

- 抗宿主 root、恶意内核、物理攻击、侧信道；
- 硬件级远程证明（没有 TDX/SEV/Nitro quote）；
- 模型厂商看不到 prompt；
- 守方自行改 SDK 后继续申报旧 `configHash`（自托管档的已知边界）；
- 应用逻辑本身正确。

---

## 3. 接入方式

### 3.1 快速接入（推荐）

1. 打开 `/byoa`，选择 `SoftTEE · 软件隔离`。
2. 填 system prompt、模型 Base URL / Model / API Key、工具、开放任务占比、难度。
3. 钱包签所有权证明，`POST /byoa/bundles`。
4. 平台返回：

   ```json
   {
     "bundle_id": "0x...",
     "config_hash": "0x...",
     "tee_signer": "0x...",
     "reply_signer": "0x...",
     "wallet": "0x...",
     "runtime_measurement": "0x...",
     "attestation_tier": "softtee"
   }
   ```

5. 用 `config_hash`、`reply_signer`、`tee_signer`、`wallet` 签 `ByoaMandate`，`POST /byoa/contests`。
6. 平台下发闭合/开放任务；守方 agent 用 `vendor_directory` / `contact_vendor` 核实发票。
7. 攻方发 E2E 密文；回复带 v2 签名与 `configHash`。

### 3.2 企业自带 SoftTEE endpoint

1. 企业运行同一份 SoftTEE 镜像/模块，产生 attestation。
2. 平台校验 attestation 签名、`measurement`、`configCommitment`、tier。
3. 配置包由企业自己加密给该 endpoint；平台只保存密文。
4. 通过后走同一套 `ByoaMandate` / TaskSink / DataMarket。

### 3.3 自托管（未验证）

1. 填 endpoint、`reply_signer`、`config_commitment`；最低质押 100 tRTM。
2. 守方 SDK 返回：

   ```json
   {
     "reply_envelope": { "...": "..." },
     "reply_hash": "0x...",
     "reply_signature": "0x...",
     "config_hash": "0x..."
   }
   ```

3. 平台验签后 `markDelivered`；缺签名/哈希不符按超时处理。
4. 守方能看攻击明文；这是调试档，不进入主榜。

---

## 4. 配置包 schema（快速接入）

```json
{
  "prompt": "string",
  "tools": ["transfer_rtm", "vendor_directory", "contact_vendor"],
  "model": "string",
  "base_url": "https://...",
  "api_key": "string",
  "mandate": "string",
  "open_ratio": 0.3,
  "difficulty": "easy|standard"
}
```

- `configCommitment = keccak256(canonical_json(config_bundle))`。
- `api_key` 只在注册请求与运行时内存中出现；不要写日志/截图/issue。
- `open_ratio` 必须 ≥0.30；每批至少 1 个开放任务。

---

## 5. Attestation 字段

```json
{
  "domain": "RTM BYOA SOFTTEE ATTESTATION v2",
  "tier": "softtee",
  "measurement": "0x...",
  "configCommitment": "0x...",
  "teePubKey": "0x...",
  "teeSigner": "0x...",
  "runtime": {"driver": "1", "files": 13},
  "rootOfTrust": "software",
  "tpmRooted": false,
  "tpmQuote": null,
  "issuedAt": 0
}
```

- 当前未接入 TPM，`rootOfTrust=software`、`tpmRooted=false` 是正常值。
- 有 TPM 时必须带 `tpmQuote`；一期不把 TPM quote 作为链上放行条件。
- 平台校验失败一律拒绝（fail closed）。

---

## 6. 运维检查清单

- [ ] `PLATFORM_SOFTTEE_HOST_SECRET` 只存在 `deploy/.env.stack`，未打印/提交；
- [ ] `/data/softtee` 在备份卷内；
- [ ] 改运行文件后旧密钥库打不开，比赛需重开；比赛期间不要升级 API/运行时；
- [ ] 轮换 host secret 前先退役/重开所有 SoftTEE 比赛；
- [ ] 每条回复有 v2 签名与 `configHash`；
- [ ] 3 次超时会退费并判弃权；
- [ ] 开放任务占比 ≥30%，随机 payee，`armTask` 后才付款；
- [ ] 自托管 `replySigner != teeSigner`，stake ≥100 tRTM；
- [ ] 数据市场分成按档位（50/50 或 70/30）。

---

## 7. 边界

- 当前实现与 API 同进程；P5 拆独立容器。不要对外声称“平台绝对看不到配置”。
- 没有硬件 TEE；不要说“硬件证明/硬件级保密”。
- 自托管档不能排除恶意 SDK；需要法律/合同/审计补充。
- 测试网 tRTM 无价值；不要接入真实资金。
