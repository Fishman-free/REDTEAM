# 测试网部署 runbook

`deploy-testnet.js` 在 Besu QBFT 测试网（chainId **48850 / 0xbed2**，零 gas）一次性部署
Treasury、Arena、RTMToken、Faucet、DataMarket 五个合约，完成 wiring、注水与授权，
把地址写入同目录的 `addresses.json`，并在写文件前断言全部关键状态。

## 前置

- Besu 节点已启动且 healthy（见 `infra/besu-testnet/README.md`）。
- 在 `contracts/` 目录执行；依赖已 `npm install`。
- 本机 **8545 被其他项目（Anvil）占用**，RTM 测试网实际映射在 **8546**；
  其他环境若 8545 空闲可直接用 8545。

## 部署命令

当前本机（RPC 8546，key 从 `keydir/key` 注入且不打印）：

```bash
cd contracts
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

- Hardhat 的 `accounts` 接受带或不带 `0x` 前缀的私钥；`keydir/key` 本身已带 `0x`，
  直接 `tr -d '\r\n'` 注入即可。**不要 echo/tee 私钥，不要把 key 写进任何文件。**
- 零 gas 网络，部署账户余额为 0 也能成功（`gasPrice: 0`）。
- 读操作（如之后查 `rtm.minter()`）可不带 `BESU_TESTNET_KEY`。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `PLATFORM_ADDRESS` | deployer | 非零；若 != deployer，wiring 完成后把五个 Ownable 的 ownership 转给它 |
| `OPERATOR_ADDRESS` | deployer | Arena/DataMarket 的 operator |
| `FAUCET_SIGNER_ADDRESS` | deployer | Faucet EIP-712 票据签名地址 |
| `FAUCET_DRIP_RTM` | `200` | 单次领取额度（RTM，`parseEther`，必须 > 0） |
| `FAUCET_FUND_RTM` | `1000000` | Faucet 预充额度（RTM，必须 > 0） |
| `TREASURY_ALLOWANCE_RTM` | `1000000` | Treasury 授权 Arena 的额度（RTM，必须 > 0），供 `refundUnserved` |
| `DEPLOY_ALLOW_REDEPLOY` | 未设置 | `=1` 才允许覆盖已存在的 `addresses.json` |

地址均经 `ethers.getAddress` 校验且拒绝零地址；金额经 `parseEther` 解析且拒绝 0。

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
10. `treasury.approveSpender(rtm, arena, treasuryAllowance)`
11. 可选：`platform != deployer` 时，逐一 `transferOwnership(platform)` 并等待

每个 `deploy()` 都 `waitForDeployment()`，每笔 tx 都 `wait()`。

## 脚本内断言（失败即退出码 1）

- chainId 守卫：`provider.getNetwork().chainId == 48850`，任何部署前检查，防止误连 Anvil 8545。
- `rtm.minter()==arena`、`rtm.arena()==arena`、`arena.rtm()==rtm`、`arena.testnet()==true`
- `arena.operator()==operator`、`market.operator()==operator`
- `faucet.ticketSigner()==ticketSigner`、`faucet.dripAmount()==drip`
- 五个合约的 `owner()==platform`
- `rtm.balanceOf(faucet)==faucetFunding`、`rtm.totalSupply()==faucetFunding`
- `rtm.allowance(treasury, arena)>=treasuryAllowance`
- `arena.activeMiningCount()==0`

## addresses.json

全部断言通过后才写入（覆盖前先通过重部署保护）。字段：

`network`、`chainId`、`rpc`、`deployer`、`platform`、`operator`、`ticketSigner`、
`treasury`、`arena`、`rtm`、`faucet`、`dataMarket`、`faucetDrip`、`faucetFunding`、
`treasuryAllowance`、`deployedAt`（ISO 8601）。

该文件用于后端/dApp 对齐地址，**不包含任何私钥**，随仓库提交。

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
- **refusing to redeploy**：`addresses.json` 已存在；确认要换新地址再加
  `DEPLOY_ALLOW_REDEPLOY=1`。
- **no signer available**：`BESU_TESTNET_KEY` 未注入或格式错误（不要打印它）。
- **owner 断言失败**：`PLATFORM_ADDRESS` 配置与预期不符；脚本会先完成 wiring
  再转移 ownership，失败时以日志中的具体断言为准。

## 安全

- `infra/besu-testnet/keydir/`、`networkFiles/`、`data/` 均被 gitignore；
  **绝不提交、复制或打印 validator/deployer 私钥**。
- 该 key 仅用于本地测试网，不可复用到主网或有价值的环境。
