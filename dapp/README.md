# RTM Arena dApp

React 19 + TypeScript + Vite 7 + wagmi/viem 的 RTM 红队竞技场前端。

视觉方向是「战情室档案」：暖黑底、羊皮纸色文字、朱红与信号绿、衬线展示标题 +
等宽数据标签。页面包含总览、竞技场、战场详情/付费对话、守方计划、挖矿中心、
排行榜、数据市场、水龙头、应用内使用文档 `/docs`，以及独立的管理控制台 `/ops`。

界面支持中英文切换，**默认英文**，语言选择保存在浏览器 localStorage。

## 本地开发

前置：平台 API 在 `127.0.0.1:8080`，链 RPC 在 `127.0.0.1:8546`。

```bash
cd dapp
npm install
npm run dev        # http://127.0.0.1:5173
```

Vite dev proxy 会把 `/api` 转发到平台 API，并在**服务端**读取
`../platform/.env.local` 的 `PLATFORM_API_TOKEN` 注入 `Authorization`。
浏览器 bundle 里没有 API token，也没有 `VITE_API_TOKEN`。

`/api/meta` 和 `/api/status` 提供链地址、费用、限额、provider 与索引器状态；
前端用它们覆盖 `src/lib/contracts.ts` 里的 fallback 地址。

```bash
npm run build      # tsc --noEmit && vite build
npm run preview    # 仅预览静态构建，不含 /api 代理
```

## 生产运行（同源 BFF）

`server.mjs` 是生产用的最小 BFF：

- 托管 `dist/` 的 SPA（含 history fallback）；
- `/api/*` 反向代理到平台 API，并在服务端注入 `PLATFORM_API_TOKEN`；
- `/rpc` 反向代理到 Besu RPC，让浏览器只访问同源；
- `/api/mining/contests` 与 `/api/data/:id/publish` 需要 `X-Admin-Key`；
- 对水龙头与守方注册做简单的按 IP 限流；
- 永不把 `PLATFORM_ADMIN_KEY` 打进前端；`/ops` 页面只在 sessionStorage 保存用户输入的密钥。

```bash
npm run build
PLATFORM_API_TOKEN=... \
PLATFORM_ADMIN_KEY=... \
PLATFORM_API_URL=http://127.0.0.1:8080 \
PLATFORM_RPC_URL=http://127.0.0.1:8546 \
npm start          # http://127.0.0.1:3000
```

生产构建默认 `VITE_RPC_URL=/rpc`（Dockerfile 传入），浏览器走同源代理。若单独部署
静态站，请把 `VITE_RPC_URL` 指向公开 HTTPS RPC，并自行处理 CORS/鉴权。

## 一键 Docker

仓库根目录的完整栈：

```bash
bash deploy/up.sh
```

详见 `deploy/README.md`。默认包含一个**故意可被攻破**的 `local-mock` 演示模型，
用于跑通加入、付费消息、攻破、数据市场与挖矿结算；它不是真实守方模型。

## 关键交互

- **钱包/网络**：注入式钱包；自动检测错误网络并支持 `wallet_addEthereumChain`；
  每次写入前比较钱包 RPC 与本站 RPC 的区块哈希，避免把交易发到另一个同 Chain ID
  的本地链；顶部账户菜单展示 tRTM / Gas 余额、复制地址、切链和断开。
- **入门序列**：总览页四步检查（连接钱包 → 切测试网 → 领 tRTM → 选角色）。
- **竞技场**：状态筛选、搜索、排序、倒计时；战场详情包含加入/质押、数据同意确认、
  付费对话、到期 `expire`、攻方 `withdrawStake`、守方 `collectPenalties`。
- **付费对话**：一次授权最多 5 条消息费用；每条消息生成唯一 `msgHash`，
  approve → attack → 等索引 → `POST /messages`；上链但未送达的消息会在
  localStorage 保留，可「继续送达」或丢弃，避免重复付费。
- **守方**：BYOK 注册、资格测试结果、一次注册一场赛、质押建赛、罚款拉取、
  到期结算；注册摘要保存在本浏览器 localStorage。
- **挖矿**：无质押加入、强制数据条款、固定 1 tRTM 奖励、RSI-only 数据边界；
  挖矿赛没有固定结束时间，界面显示 OPEN-ENDED。
- **数据市场**：发布状态、守方自有数据、已同意攻方切片、已购状态、交付重试与
  下载；购买记录保存在本浏览器。
- **交易活动**：全局 Activity 抽屉与 toast，检查 receipt status；超时后区分“仍在等待打包”
  和“交易根本没到本站这条链”，并支持手动重新检查。
- **使用文档**：`/docs` 包含设计理念、快速开始、四种角色、默认规则、数据边界、
  钱包 RPC 排障与运营者说明，术语旁的可点击问号提供即时解释。

## 环境变量

| 变量 | 用途 |
| --- | --- |
| `VITE_API_URL` | 默认 `/api`；同源 BFF |
| `VITE_RPC_URL` | 浏览器 RPC；生产建议 `/rpc` 或 HTTPS RPC |
| `VITE_EXPLORER_URL` | 可选；有浏览器时生成地址/交易链接 |
| `PLATFORM_API_TOKEN` | 仅 dev proxy / `server.mjs` 读取，**不要加 `VITE_`** |
| `PLATFORM_ADMIN_KEY` | 仅 `server.mjs` 校验 `/ops` 操作 |
| `PLATFORM_API_URL` | `server.mjs` 的上游 API |
| `PLATFORM_RPC_URL` | `server.mjs` 的 `/rpc` 上游 |

`cp .env.example .env.local` 只用于覆盖公开的 `VITE_*`；不要写入服务端密钥。

## 安全边界

- 浏览器不包含平台 bearer token；开发与生产都由服务端代理注入。
- `/ops` 是独立路由，公开导航不展示；生产必须设置 `PLATFORM_ADMIN_KEY`。
- API 单 worker：runner session、索引器、vault、faucet nonce 都是进程内状态，
  不要横向扩容。
- 当前仍是测试网演示：单验证者零 gas Besu、共享 API token、无每用户会话；
  公网/主网部署前需要补 per-user auth、限流、captcha 与多验证者链。
- 测试网资产无价值；所有对话只用于防御性安全研究。
- 用户可见文案统一把测试币称为 `tRTM`；当前已部署合约的 ERC-20 symbol 仍为 `RTM`（历史命名），
  两者指同一个测试币，不代表真实资产。
