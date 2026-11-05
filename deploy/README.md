# RTM Arena · 一键 Docker 栈

面向本地演示和单机公网部署的完整栈：Besu QBFT 测试网、五份合约、平台 API（内置自动索引器）、Web BFF、演示模型。

> 角色入口、SoftTEE 使用、API 与排障见 **[《RTM Arena 完整说明书》](../docs/MANUAL.md)**；
> 本文只讲部署与运维。

## 一条命令

```bash
bash deploy/up.sh
```

首次启动会：

1. 生成 `deploy/.env.stack`（API token、管理密钥、vault 主密钥），不会打印密钥；
2. 生成 Besu validator key + genesis（Docker volume `rtm-arena_besu-data`）；
3. 启动单验证者 Besu（chainId `48850`，零 gas）；
4. 编译并用 validator key 部署 Treasury / Arena / RTM / Faucet / DataMarket；
5. 初始化平台 vault（operator / treasury-owner / faucet-signer / platform-model）；
6. 启动 API（自动跑事件索引器）、Web BFF 和演示模型。

启动后：

- dApp：<http://localhost:3000>
- 应用内文档：<http://localhost:3000/docs>
- 运营入口：<http://localhost:3000/ops>（管理密钥在 `deploy/.env.stack`）
- API 健康检查（只绑回环）：<http://127.0.0.1:8080/health>
- 链 RPC（只绑回环）：`http://127.0.0.1:8546` 与 `BESU_RPC_PORT`（默认都指向当前 Besu）
- 钱包推荐 RPC：`http://localhost:3000/rpc`（同源 BFF，始终指向本栈）

> 一键栈会把 `BESU_ALIAS_RPC_PORT`（与主 RPC 端口不同的兼容端口，通常是 `8546`）和 `BESU_RPC_PORT` 同时发布到同一个 Besu 容器，方便旧钱包配置继续连到当前链。不要同时运行其他占用这些端口、且 Chain ID 同为 48850 的旧本地栈。
>
> 水龙头已改为“用户签名、平台代发”：用户不需要发送钱包交易，也不依赖钱包 RPC；游戏内的质押/消息交易仍由钱包广播。
>
> 从本地栈切换到公开域名后，钱包里已有的 RTM Testnet 条目仍会保留旧的 `localhost:3000/rpc`。`wallet_switchEthereumChain` 只切换当前链，**不会改写已有条目的 RPC**；用户必须在钱包的网络设置里编辑 RPC，或删除该网络后重新添加。dApp 的“尝试修复网络”会再调用一次 `wallet_addEthereumChain`，但部分钱包对已存在的链会忽略它。
>
> Binance Wallet 插件的操作路径：右上角网络名称 → Switch Network → **Custom** 标签 → RTM Testnet 右侧 `⋯` → **Edit** → 修改 **RPC URL** → Save 并确认风险提示（Chain ID 不可编辑，应为 48850）。MetaMask：Settings → Networks → RTM Testnet → Edit。站内 `/docs#troubleshooting` 有分钱包的完整步骤。

停止：

```bash
bash deploy/down.sh
```

## 服务拓扑

```
browser ──> web:3000 (SPA + /api + /rpc BFF)
                │
                ├── /api  ──> api:8080 (FastAPI + indexer) ──> besu:8545
                └── /rpc  ──> besu:8545
```

- 浏览器永远拿不到 `PLATFORM_API_TOKEN`；BFF 在服务端注入。
- BYOA 模板在 `deploy/byoa/`（compose、出网允许列表、示例 bundle、runbook）。
  SoftTEE 档使用可测量运行时与测量绑定密钥库（`/data/softtee`），它是软件隔离，
  **不是硬件 TEE**；宿主 root 理论上能读取进程内存。`deploy/byoa/tee-pilot/` 是废弃的硬件试点。
- `PLATFORM_SOFTTEE_HOST_SECRET` 由 `deploy/up.sh` 生成到 `deploy/.env.stack`，不打印；
  轮换它会使旧 SoftTEE 密钥库无法解密。
- `/api/mining/contests` 与 `/api/data/:id/publish` 需要 `X-Admin-Key`。
  运营台的 RSI 修复闭环（`/api/rsi/export`、`/api/rsi/candidates`、
  `/verify`、`/promote`）同样需要该密钥。
- `mock-model:18081` 与 API 共享网络命名空间，只监听 `127.0.0.1`，不对外暴露。
- API 只启动 **1 个 worker**：runner session、索引器、vault 与 faucet nonce 都是单进程状态。
  重启后，`/data/platform-state.sqlite3` 会恢复守方注册、已处理付费交易与会话元数据；
  下一次付费消息会按需重建 agent 会话。会话内容是否保留取决于加入时的数据同意：
  同意（或挖矿赛）会完整恢复，opt-out 的攻方线程只恢复轮次预算、不恢复对话。
- RSI 修复产出的新版本写在 `REDTEAM_VERSIONS_DIR=/data/versions`，优先于镜像内
  `benchmark/versions` 加载，因此容器重建后仍然可以继续用新版开赛。

## 演示模型（重要）

默认 `MODEL_ALLOWLIST_JSON` 指向 `local-mock`，这是一个**故意可被攻破**的演示模型：

- 资格测试会完成 1 wei 转账；
- 外部消息要求转账时会真的调用 `transfer_rtm`；
- 用于演示加入、付费消息、攻破、数据市场与挖矿结算。

它不是真实守方模型，不能代表任何安全性。生产/研究使用请在 `deploy/docker-compose.yml` 中替换：

```yaml
MODEL_ALLOWLIST_JSON: '{"your-provider":{"base_url":"https://your-model.example/v1","model":"your-model"}}'
PLATFORM_MODEL_PROVIDER: your-provider
```

并在 `deploy/.env.stack` 设置 `PLATFORM_MODEL_KEY=...`，重新运行 `bash deploy/up.sh`（vault 会更新 `platform-model`）。允许的 `base_url` 必须是 HTTPS（loopback 的 HTTP 例外）。

守方也可以在前端 `/defend` 直接填写自己的 OpenAI 兼容 Base URL、Model 和 API Key；攻方在 `/attack` 的 Agent 模式可以填写同样的模型信息，或填写一个 A2A `message/send` 端点。两者都需要在 API 服务中启用：

```yaml
PLATFORM_ALLOW_CUSTOM_MODEL_ENDPOINTS: "true"
```

`docker-compose.yml` 的测试网默认已启用。HTTPS 端点直接可用；HTTP 只允许 loopback。平台不会持久化攻方 Agent 的 API Key，守方的 Key 仍进入加密 custody。

> 安全边界：允许自定义端点意味着平台会按用户提供的 URL 发起请求；这是测试网演示开关，不要在没有出站策略的生产环境直接开启。生产部署请使用 `MODEL_ALLOWLIST_JSON` 固定 provider。

## 公网部署

默认只把 **Web 端口绑到 127.0.0.1**，API、RPC、mock model 都不直接暴露。推荐在前面放 Caddy/Nginx：

```caddyfile
arena.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

然后：

- 只放行 80/443；不要暴露 8080、8546、3000 和 mock model。
- 备份 Docker volumes：`rtm-arena_besu-data`、`rtm-arena_rtm-registry`、`rtm-arena_rtm-platform-data`（vault、SQLite、transcripts）。
- 修改 `deploy/.env.stack` 的 `PLATFORM_ADMIN_KEY`，不要把管理密钥发给玩家。
- 当前链是单验证者测试网、零 gas，不是公链。要上公网测试网，需改用有 gas 的链并调整 `Web3ChainGateway` 的 gas 策略。
- 演示模型的输出不构成安全结论；真实资金场景不要使用。

## 运维

```bash
# 查看服务
docker compose --env-file deploy/.env.stack -f deploy/docker-compose.yml ps

# 日志
docker compose --env-file deploy/.env.stack -f deploy/docker-compose.yml logs -f api web

# 重启 Web（改完 API token 后）
docker compose --env-file deploy/.env.stack -f deploy/docker-compose.yml up -d --build web
```

### SoftTEE 合约迁移（不重置链）

2026-11-05 的 BYOA 合约改动需要一次重新部署。运行：

```bash
bash deploy/migrate-softtee.sh
```

脚本会：

1. 生成/追加 `PLATFORM_SOFTTEE_HOST_SECRET`（不打印）；
2. 备份当前 registry 为 `addresses.pre-softtee.json`；
3. 在**同一条** Besu 链上部署新的 Treasury / Arena / RTM / Faucet / DataMarket / TaskSink；
4. 把旧的 `index.sqlite3` / `platform-state.sqlite3` 归档为 `.pre-softtee`，
   让新 API 从新部署块重建索引；vault 与链数据不动；
5. 切换 registry，重建 api / web / mock-model；
6. 校验 `/api/meta` 含 `taskSink` 和 `softtee` 档位。

旧比赛仍留在旧合约上，不会被迁移；链本身、旧区块、transcripts 和 vault 都保留。
迁移前请备份 `rtm-arena_rtm-platform-data` 卷。不要用 `down -v` 代替这个脚本。
守方需要在迁移后重新注册（旧注册指向旧合约/UUID）。

### 重置

**会删除链、合约地址、vault、索引与下载数据。**确认后再执行：

```bash
bash deploy/down.sh -v
bash deploy/up.sh
```

如果只重置链而保留旧的 registry，`contracts` 容器的 `check-registry.mjs` 会发现 chainId 或合约代码不符，并拒绝启动（API 随之不会启动）；必须同时删除 `rtm-registry`（`down -v` 会做）。

### 地址从哪里来

- 运行中唯一来源：`rtm-registry` 卷的 `/registry/addresses.json`，经 `GET /api/meta` 提供给 dApp。dApp 不再内置任何后备地址，API 不可达时链上读写会暂停。
- `contracts/deploy/addresses.json` 是 gitignored 的本机副本，`up.sh` 结束时会通过 `bash deploy/sync-registry.sh` 自动刷新（`rpc` 改写为宿主机端口），也可以手动执行这条命令。
- 查看运行中的地址：`curl -s http://127.0.0.1:3200/api/meta`；registry 是扁平 JSON（没有 `.addresses` 这一层）。

### 常见问题

- **端口冲突**：编辑 `deploy/.env.stack` 的 `BESU_RPC_PORT` / `API_PORT` / `WEB_PORT`。
- **contracts 容器失败**：`docker compose ... logs contracts`。首次构建要下载 Solidity 编译器。
- **Web 显示 API 离线**：`docker compose ... logs api`，检查 vault/contracts 是否完成。
- **交易一直 Pending / 钱包超时**：水龙头不受影响，因为它由平台代发。游戏交易仍使用钱包，请确认站内网络提示已切换，并确认没有另一个占用 8546/自定义端口的旧本地栈。
- **Windows**：在 Git Bash 中运行 `bash deploy/up.sh`，确保 Docker Desktop 已启动。
- **重新构建前端**：`docker compose ... up -d --build web`。
