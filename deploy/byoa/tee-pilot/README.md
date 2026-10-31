# BYOA TEE 最小验证（TDX + dstack）

> 完整背景、威胁模型与分阶段接入路线见 `docs/TEE.md`。本文只讲这个试点怎么跑。

这是一个**独立的试点**，不接入现有平台 API，也不改变 `attestation_tier=simulated` 的行为。目标是花最少的钱回答一个问题：

> 我们的代码能不能在真实 Intel TDX 机密虚拟机里生成可验证的远程证明，并把“签名键 + 钱包地址 + 新鲜 nonce”绑定到硬件 quote 上？

## 它验证什么

CVM 内启动时生成：

- 一个 EIP-191 签名键（`signer`）；
- 一个独立钱包键（`wallet`，不导出私钥）。

对每个验证请求：

1. 外部验证器生成 32 字节随机 nonce；
2. CVM 计算 `binding = {domain, nonce, signer, wallet}` 的 SHA-256；
3. 把 `nonce || bindingHash` 作为 64 字节 `report_data` 请求 TDX quote；
4. CVM 用 `signer` 对同一 binding 签名；
5. 外部验证器调用 Phala 验签 API 验证 quote，确认硬件 `report_data` 与 binding 一致；
6. 外部验证器比对 `/info` 的 `app_compose` 与 quote 事件日志里的 `compose-hash`。

任意一项缺失或不一致都会失败（fail closed）。

**它不能证明**：守方 agent 的保密性、配置加密、钱包 MCP、链上 `TeeWalletBinding`、生产级 KMS。它只是硬件可行性验证。

## 成本

以 Phala Cloud 官方定价（2026-10 查询）为准：

| 项目 | 单价 |
|---|---|
| `tdx.small` 1 vCPU / 2 GB | 约 **$0.058/小时**（按分钟计费） |
| 磁盘（最小 20 GB） | $0.000139/GB/小时 ≈ **$0.0028/小时** |

这个试点进程很小，`tdx.small` 足够。一次试点（1 台，20 GB 磁盘）约 **$0.061/小时**：

- 3 小时：约 **$0.18**
- 6 小时：约 **$0.36**
- 24 小时：约 **$1.46**

如果之后要跑完整 driver / wallet / defender 多容器，再换 `tdx.large`（4 vCPU / 8 GB，$0.232/小时）。

还需要一个能放镜像的 registry（Docker Hub / GHCR，公共镜像通常免费）。注册 Phala 账号时是否有最低充值/试用额度，以控制台为准。

## 前置条件

1. Phala Cloud 账号和 API Key（`phak_...`）。
2. Docker，可构建 `linux/amd64` 镜像。
3. 一个镜像仓库；私有仓库可通过 `DSTACK_DOCKER_USERNAME` / `DSTACK_DOCKER_PASSWORD` 传给 Phala。
4. 本机验证器依赖：`eth-account`、`eth-utils`（项目 `platform/.venv` 已具备）。
5. 安装 CLI：`npm install -g phala`。

## 部署步骤

### 1. 构建并推送镜像

```bash
cd deploy/byoa/tee-pilot
docker build --platform linux/amd64 -f cvm/Dockerfile \
  -t <registry>/rtm-tee-pilot:0.1 .
docker push <registry>/rtm-tee-pilot:0.1
```

建议部署时使用 digest（`@sha256:...`），这样 compose hash 更稳定。

### 2. 部署 TDX CVM

```bash
export TEE_PILOT_IMAGE='<registry>/rtm-tee-pilot@sha256:...'
phala login            # 交互登录；不要把 API Key 贴到聊天或提交到仓库
phala deploy -n rtm-tee-pilot -c compose.yaml -t tdx.small --disk-size 20G --wait
```

如果 CLI 没有读取 shell 里的 `TEE_PILOT_IMAGE`，在 `deploy/byoa/tee-pilot/` 下建一个 `.env`（不要提交）写入 `TEE_PILOT_IMAGE=...` 后重试。

查看公网地址：

```bash
phala cvms get rtm-tee-pilot
```

如果使用私有镜像，在 `phala deploy` 前设置 `DSTACK_DOCKER_USERNAME` / `DSTACK_DOCKER_PASSWORD`（或对应的 ECR 变量）。

### 3. 在 CVM 外部执行验证

```bash
cd deploy/byoa/tee-pilot
../../../platform/.venv/Scripts/python.exe verify_pilot.py --url https://<cvm-public-url>
```

（Linux/macOS 用 `python` 即可。）

成功时输出类似：

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

失败会输出 `{"ok": false, "error": "..."}` 并以非零状态退出。

验证器默认使用 Phala 的在线验签 API。如果所在网络访问该 API 返回 403（部分出口 IP 会被 Cloudflare 拦截），可以换网络执行，或改用 `dcap-qvl` 本地验证；当前脚本未内置 `dcap-qvl` 适配，使用本地验证时需要先扩展 `check_hardware`。不要把“请求没发出去”当成硬件验证通过。

### 4. 停止计费

验证完成后立即在 Phala 控制台停止并删除 CVM。停止后只收磁盘存储费；删除后停止全部计费。

## 本地离线测试（不需要 TEE）

```bash
cd deploy/byoa/tee-pilot
../../../platform/.venv/Scripts/python.exe -m unittest -v test_verify_pilot.py
```

这些测试使用合成 quote，只证明验证器逻辑会拒绝篡改；**不构成硬件证明**。

## 通过之后

如果这个试点通过，下一阶段才是把它接进平台：

1. 用 CVM 内的 `signer` 签 `TeeWalletBinding`，替代 `SimulatedSealedRuntime`；
2. 平台接受 `attestation_tier=hardware`，保存原始 quote 并做 DCAP 校验（可用 `dcap-qvl` 或 Phala API）；
3. 把 driver / wallet sidecar 做成可复现镜像，接入 `deploy/byoa/compose.simulator.yaml`；
4. 再实现配置加密包、bundle-loader 和 sealer。

在这些完成之前，线上 BYOA 仍然只能标注 `simulated`。
