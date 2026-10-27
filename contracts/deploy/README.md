# 测试网部署 runbook（R4 新 ABI）

`deploy-testnet.js` 在 Besu QBFT 测试网（chainId **48850 / 0xbed2**，零 gas）一次性部署
Treasury、Arena、RTMToken、Faucet、DataMarket 五个合约，完成新挖矿 ABI 的 wiring、
注资与固定 **1 RTM** 挖矿结算烟测，把地址写入同目录的 `addresses.json`，并在写文件前
断言全部关键状态。

> **旧地址（R4 前）全部作废**：
> Treasury `0x4B6648955b5938F9BE2bc35d3dD9300a4062f611`、
> Arena `0x3a8df899d27801D0b37db9dF8A29Aa27B6610111`、
> RTMToken `0xF08F681A58aB71E9FaC4B9E55DE4b29e309C46d7`、
> Faucet `0x042Bc6dfbc08ECe0Db7901b1d2D65a1F9ede35b3`、
> DataMarket `0x9446F32556dE6E053F6E22205d7300f0ED1d28Fb`。
> 它们绑定旧 ABI（`accrue`/`miningRate`/`approveSale`），不得再用于新挖矿/数据市场接口。
> 以 R4 重新生成的 `contracts/deploy/addresses.json` 为准。

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

默认端口 8545 的环境（`BESU_TESTNET_RPC` 可省略，Hardhat 配置默认 8545）：

```bash
cd contracts
BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
npx hardhat run deploy/deploy-testnet.js --network besu-testnet
```

- `contracts/deploy/addresses.json` 已存在时，脚本默认拒绝重部署；上面命令带
  `DEPLOY_ALLOW_REDEPLOY=1` 是因为本仓库已有登记文件，且 R4 明确作废旧部署。
  首次部署不需要该变量。
- Hardhat 的 `accounts` 接受带或不带 `0x` 前缀的私钥；`keydir/key` 本身已带 `0x`，
  直接 `tr -d '\r\n'` 注入即可。**不要 echo/tee 私钥，不要把 key 写进任何文件。**
- 零 gas 网络，部署账户余额为 0 也能成功（`gasPrice: 0`）。
- 读操作（如之后查 `rtm.minter()`）可不带 `BESU_TESTNET_KEY`。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PLATFORM_ADDRESS` | deployer | 非零；若 != deployer，注资/烟测完成后把五个 Ownable 的 ownership 转给它 |
| `OPERATOR_ADDRESS` | deployer | Arena/DataMarket 的 operator；执行烟测时必须 == deployer（脚本只有一把 key） |
| `FAUCET_SIGNER_ADDRESS` | deployer | Faucet EIP-712 票据签名地址 |
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

## 新 ABI 口径（R2/R3/R4）

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
  `Arena.dataConsent`，`publish` 拒绝 mining。ABI 中不存在任何 `accrue`/`miningRate` 路径。

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

## 脚本内断言（失败即退出码 1）

- chainId 守卫：`provider.getNetwork().chainId == 48850`；网络名必须为 `besu-testnet`。
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
`treasury`、`arena`、`rtm`、`faucet`、`dataMarket`、`faucetDrip`、`faucetFunding`、
`treasuryMiningFund`、`refundAllowance`、`miningReward`、`miningFeeBps`、
`totalSupply`、`smokeMining`、`smokeDefenseHash`、`deployedAt`（ISO 8601）。

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
  "smokeDefenseHash": "0x…"
}
```

- `smokeMining`：本次部署是否执行真实挖矿烟测；`smokeDefenseHash` 为烟测使用的
  hash（未执行时为 `null`）。
- 金额为十进制 RTM 字符串；`miningFeeBps` 为数字。
- 该文件用于后端/dApp 对齐地址，**不包含任何私钥**，随仓库提交。

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
- **owner 断言失败**：`PLATFORM_ADDRESS` 配置与预期不符；脚本会先完成注资/烟测
  再转移 ownership，失败时以日志中的具体断言为准。
- **TREASURY_MINING_FUND must equal 3 RTM**：工作资金固定为
  `MINING_REWARD × MAX_ACTIVE_MINING`，不要按旧口径改成 1M。

## 安全

- `infra/besu-testnet/keydir/`、`networkFiles/`、`data/` 均被 gitignore；
  **绝不提交、复制或打印 validator/deployer 私钥**。
- 烟测 W 的私钥只在部署进程内存中，不打印、不写文件；进程结束后不可恢复，
  仅用于一次性真实结算验证。
- 该 key 仅用于本地测试网，不可复用到主网或有价值的环境。
