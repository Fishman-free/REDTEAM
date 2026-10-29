# BYOA 守方接入：运行与部署

## 本地模拟器

S1/S2 的实现可以在平台进程内跑完整流程（注册 bundle → 签名创建 BYOA 赛 →
下发 owner 任务 → 对手方回合 → 结算）。此模式使用
`redteam_platform.byoa.sealed.SimulatedSealedRuntime`，它：

- 在内存中生成 W 私钥和 TEE 签名密钥；
- 生成 **模拟证明**（tier=`simulated`），只能验证流程，不提供任何保密保证；
- 平台只拿到 W 地址、TEE 地址、`teePubKey`、测量值和承诺 hash。

启动平台后可用以下接口（都需要平台 API token）：

```bash
# 1. 注册 bundle（守方先对 canonical_challenge 做 EIP-191 签名）
curl -X POST http://127.0.0.1:8000/byoa/bundles -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @bundle.json

# 2. 创建 BYOA 赛（守方对 ByoaMandate 做 EIP-712 签名）
curl -X POST http://127.0.0.1:8000/byoa/contests -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d @contest.json

# 3. 下发 owner 任务（同时上链到 TaskSink）
curl -X POST http://127.0.0.1:8000/byoa/contests/$CID/tasks -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"text":"支付 ACME 发票 INV-7","amount":"2","deadline":1760000000}'

# 4. 对手方回合（只接受 E2E 密文信封；明文请求会 422）
#    先链上 attack(cid, keccak(ct))，再提交：
#    {tx_hash, attacker, ciphertext:{v,suite,epk,nonce,ct,ctx}, attacker_pubkey,
#     key_signature, key_deadline, kind, metadata}
curl -X POST http://127.0.0.1:8000/byoa/contests/$CID/turns -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d @sealed_turn.json

# 5. 结算与效用报告
curl -X POST http://127.0.0.1:8000/byoa/contests/$CID/finalize -H "Authorization: Bearer $TOKEN"
```

钱包 MCP 在本地挂在 `/byoa/wallet/mcp`，只接受每个会话随机生成的
`Authorization: Bearer <wallet-token>`。该 token 只注入给守方容器，不进入
dApp 或平台存储。mcp-pull 的驱动端在 `/byoa/contests/{id}/pull/next_message`
与 `/reply`，使用创建比赛时返回的一次性 `pull_token`（`X-BYOA-Pull-Token`），
不使用平台 API token。

## 密封运行时模板

`compose.simulator.yaml` 是 dstack 模拟器布局：driver、wallet、egress、
defender 四个服务；defender 只连接 `sealed` 内网，唯一出网路径是 egress
代理。driver/wallet 镜像由 S5 的 SDK 构建；defender 镜像是守方提供的 digest。
`egress.yaml` 是 Envoy 允许列表示例，`egress-policy.example.json` 是对外公开的
出网声明。

真实 TEE 阶段：

1. 把 compose 的 hash 作为 `runtimeMeasurement` 写进链上；
2. 由 CVM 内 TEE 密钥签 `TeeWalletBinding`，平台不能代签；
3. `attestation_tier` 记为 `hardware`，并保存原始 quote 供任何人复验；
4. 钱包 sidecar 的 L3 策略和 W 私钥都不离开 CVM。

**模拟器没有任何保密保证。** UI 和 API 都必须显示 `simulated`，不能把它当作
TEE 证明。
