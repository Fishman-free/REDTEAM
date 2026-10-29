# 测试网部署 runbook（R4 新 ABI）

`deploy-testnet.js` 在 Besu QBFT 测试网（chainId **48850 / 0xbed2**，零 gas）一次性部署
Treasury、Arena、RTMToken、Faucet、DataMarket 五个核心合约，以及 BYOA 的 TaskSink，完成新挖矿 ABI 的 wiring、
注资与固定 **1 RTM** 挖矿结算烟测，把地址写入同目录的 `addresses.json`，并在写文件前
断言全部关键状态。

> **旧地址（R4 前）全部作废**：
> Treasury `0x4B6648955b5938F9BE2bc35d3dD9300a4062f611`、
> Arena `0x3a8df899d27801D0b37db9dF8A29Aa27B6610111`、
> RTMToken `0xF08F681A58aB71E9FaC4B9E55DE4b29e309C46d7`、
> Faucet `0x042Bc6dfbc08ECe0Db7901b1d2D65a1F9ede35b3`、
> DataMarket `0x9446F32556dE6E053F6E22205d7300f0ED1d28Fb`。
> 它们绑定旧 ABI（`accrue`/`miningRate`/`approveSale`），不得再用于新挖矿/数据市场接口。

> **地址的唯一来源（2026-10-29 起）**：运行中的栈只读 `rtm-registry` 卷里的
> `/registry/addresses.json`，并通过 `GET /api/meta` 对外提供。仓库里的
> `contracts/deploy/addresses.json` **不再提交**（已 gitignore）：每台机器的 `deploy/up.sh`
> 都会用新生成的 key 部署，地址天然各不相同。它只是 `deploy/sync-registry.sh` 写出的
> 本机副本，供本地工具和测试读取。字段结构参见 `addresses.example.json`（占位地址，不可发交易）。

> **R4 审查修复（2026-10-28）**：本轮只加固部署脚本/runbook 并补充登记字段，
> **未重新部署**。链上地址、`totalSupply=1,000,004`、Treasury 3 RTM、
> 烟测 contest/hash/tx 均保持不变。

## 前置

- Besu 节点已启动且 healthy（见 `infra/besu-testnet/README.md`）。
- 在 `contracts/` 目录执行；依赖已 `npm install`，合约已 `npx hardhat compile`。
- 本机 **8545 被其他项目（Anvil）占用**，RTM 测试网实际映射在 **8546**；
  其他环境若 8545 空闲可直接用 8545。

## 部署命令

当前本机（RPC 8546，key 从 `keydir/key` 注入且不打印）：

```bash
cd contracts
DEPLOY_ALLOW_REDEPLOY=1 \
BESU_TESTNET_RPC=http://127.0.0.1:8546 \
BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
npx hardhat run deploy/deploy-testnet.js --network besu-testnet
```

默认端口 8545 的环境（显式设置 RPC；烟测的独立 provider 在未设置
`BESU_TESTNET_RPC` 时回退 8546，因此跑烟测时必须显式指定 8545）：

```bash
cd contracts
DEPLOY_ALLOW_REDEPLOY=1 \
BESU_TESTNET_RPC=http://127.0.0.1:8545 \
BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
npx hardhat run deploy/deploy-testnet.js --network besu-testnet
```

- 如果本机已有 `contracts/deploy/addresses.json`（例如运行过 `deploy/sync-registry.sh`），
  再次部署必须显式设置 `DEPLOY_ALLOW_REDEPLOY=1`（或先删除该文件）。脚本在该文件存在
  且未显式允许时会直接拒绝，不会覆盖旧登记。
- Hardhat 的 `accounts` 接受带或不带 `0x` 前缀的私钥；`keydir/key` 本身已带 `0x`，
  直接 `tr -d '\r\n'` 注入即可。**不要 echo/tee 私钥，不要把 key 写进任何文件。**
- 零 gas 网络，部署账户余额为 0 也能成功（`gasPrice: 0`）。
- 读操作（如之后查 `rtm.minter()`）可不带 `BESU_TESTNET_KEY`。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PLATFORM_ADDRESS` | deployer | 非零；若 != deployer，注资/烟测完成后把五个 Ownable 的 ownership 转给它 |
| `OPERATOR_ADDRESS` | deployer | Arena/DataMarket 的 operator；执行烟测时必须 == deployer（脚本只有一把 key） |
| `FAUCET_SIGNER_ADDRESS` | deployer | Faucet EIP-712 票据签名地址（合约内不可变）。仅测试网便利默认 deployer；**生产环境、或 `PLATFORM_ADDRESS != deployer` 时必须显式设置**，否则签票权永久留在 deployer |
| `FAUCET_DRIP_RTM` | `200` | 单次领取额度（RTM，`parseEther`，必须 > 0） |
| `FAUCET_FUND_RTM` | `1000000` | Faucet 预充额度（RTM，必须 > 0） |
| `TREASURY_MINING_FUND` | `3` | Treasury 挖矿工作资金；必须等于 `MINING_REWARD × MAX_ACTIVE_MINING`（1 × 3 = 3 RTM） |
| `TREASURY_ALLOWANCE_RTM` | `0` | `refundAllowance`：Treasury 授权 Arena `refundUnserved` 的额度。**默认 0，只是权限、不是独立资金**；退款只用 Treasury 已收手续费，owner 按需提高 |
| `RUN_MINING_SMOKE` | `1` | `=1` 执行真实 1 RTM 结算烟测；`=0` 跳过（地址文件 `smokeMining=false`） |
| `DEPLOY_ALLOW_REDEPLOY` | 未设置 | `=1` 才允许覆盖已存在的 `addresses.json` |

地址均经 `ethers.getAddress` 校验且拒绝零地址；金额经 `parseEther` 解析；
正数金额拒绝 0，`TREASURY_ALLOWANCE_RTM` 允许 0。

**不再有 `TREASURY_ALLOWANCE_RTM=1000000` 的默认值**，也不再有额外 mint 1M 给 Treasury。
旧脚本的挖矿 allowance / 1M Treasury 注资口径已作废。

`PLATFORM_ADDRESS != deployer` 且未显式设置 `FAUCET_SIGNER_ADDRESS` 时，脚本会打印
醒目 WARNING：`Faucet.ticketSigner` 不可变，签票权会保留在 deployer。生产部署必须
显式传入独立签票地址。

## 部署顺序与 wiring

1. `Treasury(owner=deployer)`
2. `Arena(owner=deployer, treasury, testnet=true)`
3. `RTMToken(owner=deployer, minter=arena)`
4. `arena.initialize(rtm)`
5. `arena.setOperator(operator)`
6. `Faucet(owner=deployer, rtm, ticketSigner, drip)`
7. `DataMarket(owner=deployer, rtm, arena, treasury)`
8. `market.setOperator(operator)`
9. `arena.mintForTest(faucet, faucetFunding)`（仅 testnet=true 可用）
10. `arena.mintForTest(treasury, 3 RTM)`（K=3 挖矿工作资金，**不是 1M**）
11. `treasury.approveSpender(rtm, arena, refundAllowance)`（默认 0；仅退款权限）
12. 可选：`RUN_MINING_SMOKE=1` 时执行固定 1 RTM 真实结算烟测（见下）
13. 可选：`platform != deployer` 时，逐一 `transferOwnership(platform)` 并等待

每个 `deploy()` 都 `waitForDeployment()`，每笔 tx 都 `wait()`。
ownership 在全部注资/烟测完成后才转移，避免提前转移导致 deployer 无法配置。

**Ownership 转移注意**：转移后的断言只能证明链上 owner 等于传入的
`PLATFORM_ADDRESS`，**不能证明该地址本身正确**（拼写错误但可接收的地址同样会通过）。
转移前必须二次确认目标地址（多签/硬件钱包/团队交叉核对）；生产环境建议使用
two-step ownership（`Ownable2Step`）或由多签确认接收。当前五合约为单步 `Ownable`，
一旦转错不可回滚。

## 新 ABI 口径（R2/R3/R4/BYOA）

- TaskSink：`issueTask`（operator 或该场 TEE signer）、`expireTask`（任何人）、
  `consume`（仅 RTMToken 在 `_update` 靶分支调用）；Arena `setTaskSink` 只能设置一次。
- Arena：`createByoaContest(ByoaParams,bytes defenderSig,bytes teeSig)`、
  `markDelivered(cid,attacker,msgHash,replyHash)`、`byoaContestInfo(cid)`。
- Arena：`createMiningContest(address wallet, bytes32 defenseHash)`、
  `joinMining(bytes32 id, bool acceptData)`、`join(bytes32 id, uint256 maxStake, bool dataConsent)`、
  `retireMining(bytes32 id)`、`dataConsent(bytes32 id, address who)`。
- 挖矿固定奖励 `MINING_REWARD = 1 RTM`；矿工无质押、无罚款；挖矿消息费
  `MINING_FEE_BPS = 50` → 0.005 RTM/条。
- `createMiningContest` **不拉 Treasury、不消耗 allowance**；W 必须由 Treasury owner
  预先 `treasury.withdraw(rtm, W, 1 RTM)` 打款，operator 只调用 create。
- 攻破后 Token 只转本次 `value`，Arena 扫尾 W 剩余余额给 winner，再补铸 1 RTM 回
  Treasury；`defenseHash` 永久 retired。
- DataMarket：**没有 `approveSale`/`saleApproved`**；`buyFromAttacker` 读取
  `Arena.dataConsent`，`publish` 拒绝 mining。
- ABI 中**无旧挖矿 `accrue`/线性发行**路径，也不存在 `miningRate`/`E_rate`；
  `accruedPenalties` 仅是普通赛罚款的只读视图，与挖矿无关。

## 挖矿烟测（默认执行）

脚本用 `ethers.Wallet.createRandom()` 在进程内生成全新 W，**私钥不打印、不落盘，
用后随进程丢弃**；W 攻破后成为 `isControlledWallet` 且 hash 永久退役，不可复用。
烟测走真实结算路径：

1. Treasury owner（deployer）`treasury.withdraw(rtm, W, 1 RTM)` 预打款；断言 W 余额 = 1 RTM。
2. `defenseHash = ethers.id('rtm-mining-smoke-v1')`；operator
   `arena.createMiningContest(W, defenseHash)`；断言 `activeMiningCount=1`、W 已注册为靶、
   `contestInfo.isMining=true` 且 `defenseHash` 正确。
3. deployer `arena.joinMining(id, true)`；断言 `stake=0`、`base=1 RTM`、
   `dataConsent=true`，并解析 `MiningJoined`。
4. W 向 deployer 转 1 RTM，触发 Token `Breach` → Arena `onBreach`；断言：
   deployer +1 RTM、W=0、Treasury 恢复 3 RTM、totalSupply 增加 1、
   比赛 Ended、`activeMiningCount=0`、`retiredDefenseHash=true`、
   `activeDefenseHash=0`，并解析 `MiningSettled(reward=1 RTM)` 与 Token `MiningMinted(1 RTM→Treasury)`。

默认参数下总供给：`1,000,000 (Faucet) + 3 (Treasury) = 1,000,003`；
烟测补铸后 **1,000,004**。`RUN_MINING_SMOKE=0` 时保持 **1,000,003**。

**烟测覆盖边界**：本次部署态烟测让 W 全额转出 1 RTM，因此 `onBreach` 时
W 的剩余余额 `rest=0`，没有实际执行 `controllerTransfer` 扫尾；也未在部署态
跑第二场 `retireMining` 正常退役路径（避免再占用一条 1 RTM 工作资金）。
`rest>0` 的部分转账扫尾、未攻破 `retireMining` 退回不铸均由 R2 单元测试覆盖；
任务 17 的 e2e 需再补部署态双路径。

烟测的 `contestId`/`txHash`/`defenseHash` 会写入 `addresses.json`（见下）。
**任务 13（indexer/排行榜）与任务 17（e2e）必须排除该烟测赛和部署注水 mint**
（Faucet 1,000,000 + Treasury 3，以及烟测补铸的 1），不得计入生产挖矿/发行统计。

## 烟测失败与回收

- 任何失败都会以非零退出码结束，且**不会写入/覆盖 `addresses.json`**。若该文件
  此前已存在，其中已登记的上一套地址仍然有效；不要手工写入半成品地址，也不要
  使用本次失败产生的孤儿合约。
- 预打款后的自动回收（脚本 catch）：
  - `createMiningContest` 已成功且比赛仍 Live：operator（烟测要求 operator==deployer）
    调用 `retireMining(id)`，把 W 的 1 RTM 退回 Treasury，hash 退役、不铸造。
  - create 未成功（W 尚未注册为靶）：脚本用内存中的 W 私钥把 W 余额普通
    `transfer` 回 Treasury；W 私钥随进程退出丢弃。
  - 比赛已 Ended（攻破已结算）：奖励/补铸已落链，无需回收；该孤儿部署仍不可登记。
  - 回收失败只打印 warning，脚本继续抛出原始异常，不掩盖根因。
- 进程异常中断、未来得及自动回收时：
  - 若孤儿 Arena 上该 smoke hash 仍活跃（`activeDefenseHash(hash) != 0`、
    `contestState(id) == 1` 且 `contestInfo(id).isMining == true`），由 operator
    调用 `retireMining(id)` 退回 W 余额。
  - 若 create 从未成功且进程已退出，W 私钥已丢失，W 中的 1 RTM 在测试网无法找回；
    这是测试网可接受的损失。不要为此复用或伪造地址。
  - 修好问题后重新部署；此前 `addresses.json` 指向的上一套部署仍可继续使用，
    直到新部署全部断言通过并覆盖登记为止。

## 脚本内断言（失败即退出码 1）

- chainId 守卫：主 provider 与烟测独立 provider 的 `getNetwork().chainId` 都必须为
  `48850`；网络名必须为 `besu-testnet`。
- `rtm.minter()==arena`、`rtm.arena()==arena`、`arena.rtm()==rtm`、`arena.testnet()==true`
- `arena.operator()==operator`、`market.operator()==operator`
- `faucet.ticketSigner()==ticketSigner`、`faucet.dripAmount()==drip`
- 五个合约的 `owner()==platform`
- `rtm.balanceOf(faucet)==faucetFunding`
- `rtm.balanceOf(treasury)==3 RTM`（烟测前 3、预打款后 2、攻破补铸后恢复 3）
- `rtm.allowance(treasury, arena)==refundAllowance`（默认 0，精确相等）
- `rtm.totalSupply()==faucetFunding + 3 RTM (+ 1 RTM 若烟测执行)`
- `arena.activeMiningCount()==0`
- 烟测内：`MiningJoined`、`Breach`、`MiningMinted`、`MiningSettled` 事件字段、
  `retiredDefenseHash(hash)==true`、`activeDefenseHash(hash)==0`、
  `rtm.isControlledWallet(W)==true`。

## addresses.json

全部断言通过后才写入（覆盖前先通过重部署保护）。字段：

`network`、`chainId`、`rpc`、`deployer`、`platform`、`operator`、`ticketSigner`、
`treasury`、`arena`、`rtm`、`faucet`、`dataMarket`、`taskSink`、`faucetDrip`、`faucetFunding`、
`treasuryMiningFund`、`refundAllowance`、`miningReward`、`miningFeeBps`、
`totalSupply`、`smokeMining`、`smokeDefenseHash`、`smokeContestId`、`smokeTxHash`、
`deployedAt`（ISO 8601）。

R4 默认值示例：

```json
{
  "faucetDrip": "200",
  "faucetFunding": "1000000",
  "treasuryMiningFund": "3",
  "refundAllowance": "0",
  "miningReward": "1",
  "miningFeeBps": 50,
  "totalSupply": "1000004",
  "smokeMining": true,
  "smokeDefenseHash": "0xba7ca5938e79b4ebfaef41cf78ea37e51130cab361de418b2cf5b938a2df7ebb",
  "smokeContestId": "0x2996addb6e64517f520227e4dd5f7e222430c534affa0f90c23dd61336a55b29",
  "smokeTxHash": "0x1c6e764019472148cf5627596e669f92d03e01e5fb6abd856750691a660e9f39"
}
```

- `smokeMining`：本次部署是否执行真实挖矿烟测。
- `smokeDefenseHash`：烟测使用的 defenseHash；未执行时为 `null`。
- `smokeContestId`：烟测比赛的 id；未执行时为 `null`。
- `smokeTxHash`：烟测结算（W 转账触发 onBreach）的 tx hash；未执行时为 `null`。
- 后端/dApp/indexer 读取地址时不得把这三项误当业务数据；任务 13/17 需排除该
  烟测赛与部署注水 mint。
- 金额为十进制 RTM 字符串；`miningFeeBps` 为数字。
- 该文件**不包含任何私钥**，但也**不随仓库提交**：Docker 栈中由 `deploy-contracts.sh`
  复制到 `rtm-registry` 卷，API 与 dApp 都只认这一份（dApp 经 `/api/meta`）。
  registry 已存在时，`deploy/check-registry.mjs` 会核对 chainId 和核心 5 个地址（以及存在时的 `taskSink`）上的合约代码，
  不一致就拒绝启动，不会自动重部署。

## 重部署保护

`deploy/addresses.json` 已存在时脚本在部署前直接报错。确需重新部署（旧合约作废）
才显式覆盖：

```bash
DEPLOY_ALLOW_REDEPLOY=1 \
BESU_TESTNET_RPC=http://127.0.0.1:8546 \
BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
npx hardhat run deploy/deploy-testnet.js --network besu-testnet
```

## 排错

- **chainId guard failed**：RPC 指到了别的链（本机 8545 常是 Anvil）；改
  `BESU_TESTNET_RPC` 到 8546，不要停其他项目。
- **network guard failed**：没有用 `--network besu-testnet`。
- **refusing to redeploy**：`addresses.json` 已存在；确认要换新地址再加
  `DEPLOY_ALLOW_REDEPLOY=1`。
- **no signer available**：`BESU_TESTNET_KEY` 未注入或格式错误（不要打印它）。
- **RUN_MINING_SMOKE=1 requires OPERATOR_ADDRESS == deployer**：单 key 脚本无法以
  外部 operator 发起 `createMiningContest`；换用 deployer operator 或
  `RUN_MINING_SMOKE=0` 跳过。
- **owner 断言失败**：通常是 transferOwnership 交易失败、节点异常，或
  `PLATFORM_ADDRESS` 不是你以为的账户。注意：脚本断言只验证链上 owner 等于传入的
  `PLATFORM_ADDRESS`，**同一变量无法验证该地址本身是否正确**——拼写错误但可接收的
  地址也会通过断言。转移前请二次确认；生产建议 two-step ownership / 多签确认。
- **TREASURY_MINING_FUND must equal 3 RTM**：工作资金固定为
  `MINING_REWARD × MAX_ACTIVE_MINING`，不要按旧口径改成 1M。

## 安全

- `infra/besu-testnet/keydir/`、`networkFiles/`、`data/` 均被 gitignore；
  **绝不提交、复制或打印 validator/deployer 私钥**。
- 烟测 W 的私钥只在部署进程内存中，不打印、不写文件；进程结束后不可恢复，
  仅用于一次性真实结算验证。
- 该 key 仅用于本地测试网，不可复用到主网或有价值的环境。
