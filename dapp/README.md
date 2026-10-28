# REDTEAM dApp（任务 16）

Vite + React + TypeScript + wagmi/viem。页面：概览、守方中心、攻方中心、挖矿中心、
排行榜、水龙头、数据市场。视觉复用静态研究站的暗色/coral/mono 语言。

## 运行

```bash
cd dapp
npm install
cp .env.example .env.local     # 填入本地 PLATFORM_API_TOKEN
npm run dev                    # http://127.0.0.1:5173
```

Vite dev server 把 `/api` 代理到 `http://127.0.0.1:8080`（FastAPI 由任务 15 提供）。
后端启动示例见 `platform/README.md`；indexer 需要另行同步，否则消息/交付会提示
“未索引”。

```bash
npm run build                  # tsc --noEmit && vite build
```

## 链与环境变量

- 链：Besu 测试网 `chainId=48850`，RPC 默认 `http://127.0.0.1:8546`（**不是 8545**）。
- 地址：R4 `contracts/deploy/addresses.json`（`src/lib/contracts.ts`）。
- `VITE_API_URL`：默认 `/api`；构建静态站时设为 API 源或由反向代理托管。
- `VITE_API_TOKEN`：**只用于本地开发**。Vite 会把它打进前端 bundle；生产必须改用
  BFF/会话/短期 token，不能把 operator/生产 token 放进 dApp。
- `VITE_RPC_URL`：可覆盖 RPC。

## 关键交互

- **守方**：BYOK Key + DefensePackage.system_prompt + mandate → `POST /defenders/register`
  （平台生成 W、跑资格测试）→ approve 质押 → `POST /contests`（operator 建赛）。
  一次注册只能建一个普通比赛；比赛详情不展示攻击过程。
- **攻方**：join 表单必须给出 `dataConsent` 选择（勾选=可留存/可售，不勾选=仅内存）；
  签名前 approve 质押，再 `join(id,maxStake,dataConsent)`。每条消息先 approve
  0.5% 费用，再 `attack`，然后轮询 `POST /contests/{id}/messages` 直到 indexer 确认。
- **矿工**：加入前必须阅读并同意强制数据条款，只调用 `joinMining(id,true)`；无质押，
  每条消息 0.005 RTM；固定 1 RTM，攻破后 hash 永久退役。**没有 accrue 按钮**。
- **数据市场**：先由 operator 发布数据集（`POST /data/{id}/publish`），守方可买己方
  或 `dataConsent=true` 的攻方数据；购买后用 `DataSold` tx 调
  `POST /data/{id}/deliver` 拿一次性下载 token。挖矿数据不展示、不可售；没有
  `approveSale`。
- **水龙头**：`POST /faucet/ticket` 签 EIP-712 票据 → `Faucet.claim`；票据与 to
  绑定，只有本人可领。

## 边界

- dApp 不包含 RSI 导出页面；RSI 是平台内部安全数据。
- 单 API token 是任务 15 v1 限制；不要把 token 提交到仓库（`.env*` 已 gitignored，
  `.env.example` 仅占位）。
- 测试网资产无价值；所有攻防仅用于防御研究。
