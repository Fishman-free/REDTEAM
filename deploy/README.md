# RTM Arena · 一键 Docker 栈

面向本地演示和单机公网部署的完整栈：Besu QBFT 测试网、五份合约、平台 API（内置自动索引器）、Web BFF、演示模型。

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
- 运营入口：<http://localhost:3000/ops>（管理密钥在 `deploy/.env.stack`）
- API 健康检查（只绑回环）：<http://127.0.0.1:8080/health>
- 链 RPC（只绑回环）：`http://127.0.0.1:8546`

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
- `/api/mining/contests` 与 `/api/data/:id/publish` 需要 `X-Admin-Key`。
- `mock-model:18081` 与 API 共享网络命名空间，只监听 `127.0.0.1`，不对外暴露。
- API 只启动 **1 个 worker**：runner session、索引器、vault 与 faucet nonce 都是单进程状态。

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

### 重置

**会删除链、合约地址、vault、索引与下载数据。**确认后再执行：

```bash
bash deploy/down.sh -v
bash deploy/up.sh
```

如果只重置链而保留旧的 addresses.json，API 会连到错误的合约；所以必须同时删除 `rtm-registry`（`down -v` 会做）。

### 常见问题

- **端口冲突**：编辑 `deploy/.env.stack` 的 `BESU_RPC_PORT` / `API_PORT` / `WEB_PORT`。
- **contracts 容器失败**：`docker compose ... logs contracts`。首次构建要下载 Solidity 编译器。
- **Web 显示 API 离线**：`docker compose ... logs api`，检查 vault/contracts 是否完成。
- **Windows**：在 Git Bash 中运行 `bash deploy/up.sh`，确保 Docker Desktop 已启动。
- **重新构建前端**：`docker compose ... up -d --build web`。
