# Besu QBFT 测试网（单验证者，零 gas）

本地单验证者 Hyperledger Besu QBFT 测试链，供 RTM 红队游戏合约部署与联调使用。

- **chainId**：`48850`（十六进制 **`0xbed2`**；注意不是 `0xbeb2`）
- **共识**：QBFT，1 个验证者，出块间隔 2 秒
- **费用**：零 gas（`zeroBaseFee:true` + `min-gas-price=0` + 关闭 tx-pool 余额检查）
- **EVM**：Cancun（`shanghaiTime:0` / `cancunTime:0`，匹配 Hardhat `evmVersion: "cancun"`）
- **RPC 暴露**：只绑定 `127.0.0.1`，默认 `8545`；P2P 默认 `30303`
- **镜像**：运行时默认 `hyperledger/besu:25.10.0`；生成 genesis 默认 `hyperledger/besu:24.5.1`

## 目录与生成物

```
infra/besu-testnet/
├── genesis.json        # 源模板：不含 extraData，会被 generate.sh 包裹
├── config.toml         # 节点配置（data/genesis/key/RPC/零 gas）
├── docker-compose.yml  # 单验证者，localhost 端口
├── generate.sh         # 生成 validator key + 带 extraData 的 genesis
├── README.md
├── qbftConfig.json     # generate.sh 生成（gitignored）
├── networkFiles/       # generate.sh 生成：genesis.json + keys/<address>/key|key.pub（gitignored）
├── keydir/             # key、key.pub、address（gitignored，私钥绝不入库）
└── data/               # Besu 链数据（gitignored）
```

`networkFiles/genesis.json` 才是带 `extraData` 的可用 genesis；源模板 `genesis.json`
故意保持无 `extraData`，不要直接把它挂给容器。

## 前置

- Docker Desktop 已启动，`docker info` 可用。
- Bash（Windows 用 Git Bash）。`generate.sh` 会自动处理 Git Bash 的 `pwd -W`
  与 `MSYS_NO_PATHCONV`，不需要硬编码 Windows 路径。
- macOS 自带 Bash 3.2 可直接运行；脚本用 POSIX glob 取唯一 key 目录，不依赖
  Bash 4+ 的 `mapfile`。
- 默认端口 `8545` / `30303` 空闲。若被其他项目占用，用环境变量换 host 端口
  （见下文），容器内端口不变。

## 首次生成

```bash
cd infra/besu-testnet
bash generate.sh          # 或 ./generate.sh
```

脚本会：

1. 检查 Docker 可用；若 `networkFiles/`/`keydir/` 已存在，或 `data/` 存在且
   非空，则拒绝（空 `data/` 允许）；
2. 用 here-doc 把 `genesis.json` 包成 `qbftConfig.json`（不依赖 jq）；
3. 运行
   `besu operator generate-blockchain-config --config-file=/work/qbftConfig.json --to=/work/networkFiles --private-key-file-name=key`；
4. 断言 `networkFiles/genesis.json` 存在且 `extraData` 非空；
5. 把唯一 key 复制为 `keydir/key`、`keydir/key.pub`，并把地址写入
   `keydir/address`（`chmod 600 keydir/key`）。

**默认拒绝覆盖**：若 `networkFiles/` 或 `keydir/` 已存在，或 `data/` 存在且非空，
脚本会退出并提示先备份（空 `data/` 允许）。不要直接删除用户数据；确认要重置时
手动执行：

```bash
rm -rf networkFiles keydir data qbftConfig.json
bash generate.sh
```

生成结果的 validator 地址以 `keydir/address` 为准。重新生成会得到新 key 和新
genesis，旧 `data/` 必须删除，否则链数据与 genesis 不匹配。

> 版本说明：`generate.sh` 默认用 24.5.1 的 operator。25.10.0 的 operator 在
> 本机 Windows bind mount 下会写完 `networkFiles/` 后仍以
> `Output directory already exists` 退出（退出码 1），所以不作为生成默认；
> 其产物可被 25.10.0 运行时正常读取。可用 `BESU_IMAGE=... bash generate.sh` 覆盖，
> 但需自行确认输出完整。

## 启动

```bash
cd infra/besu-testnet
docker compose up -d
```

等待 5–10 秒。容器名固定为 `rtm-besu-validator`，`docker compose ps` 应显示
`Up ... (healthy)`。

**端口冲突**：如果本机 `8545`/`30303` 已被其他项目占用，不要停别人的容器；
换 host 端口即可：

```bash
BESU_RPC_PORT=8546 docker compose up -d
# RPC 变成 http://127.0.0.1:8546，后续所有 curl / Hardhat 都用这个地址
```

compose 默认仍是 `127.0.0.1:8545:8545` 与 `127.0.0.1:30303:30303`，且始终只绑
本机回环地址。

查看日志：

```bash
docker compose logs --tail=100
# 换过端口时也带上 BESU_RPC_PORT=8546，保持命令环境一致
```

日志中应出现 `Produced empty block #N`，每 2 秒左右一个。

## 验证

以下以默认端口 8545 为例；若使用 8546，把 `RPC` 改掉即可。

```bash
RPC=http://127.0.0.1:8545
rpc() {
  curl -s -X POST -H 'Content-Type: application/json' \
    --data "{\"jsonrpc\":\"2.0\",\"method\":\"$1\",\"params\":${2:-[]},\"id\":1}" "$RPC"
}
```

### 1. chainId

```bash
rpc eth_chainId
# {"jsonrpc":"2.0","id":1,"result":"0xbed2"}
```

`0xbed2` = 48850。**不是 `0xbeb2`。**

### 2. 连续出块

```bash
rpc eth_blockNumber; sleep 5; rpc eth_blockNumber
# 两次结果应增长约 2–3（QBFT 2s 出块）
```

### 3. 零 gas

```bash
rpc eth_gasPrice
# {"jsonrpc":"2.0","id":1,"result":"0x0"}
```

### 4. QBFT 验证者

```bash
rpc qbft_getValidatorsByBlockNumber '["latest"]'
# {"result":["0x...."]}
cat keydir/address
# 必须与上面的地址一致
```

### 5. 容器与日志

```bash
docker compose ps
docker compose logs --tail=100
```

## 零 gas 配置说明

零 gas 需要同时满足：

- genesis `config.zeroBaseFee: true`；
- 每个节点 `min-gas-price=0`（本 compose 在 `config.toml` 和 command 中都设置）；
- 每个节点 `tx-pool-enable-balance-check=false`；
- **不要**设置 `tx-pool-price-bump`（zero base fee 下 Besu 会把 price bump 强制为 0）；
- genesis `config.qbft.pertxgaslimit: 0`（当前 24.5.1 operator 与 25.10.0 runtime 均接受；
  Arena 部署远低于默认单交易上限。若未来镜像拒绝该字段，删除它即可，不影响零 gas）；
- Hardhat `besu-testnet` 网络：`chainId: 48850`、`gasPrice: 0`、最大 `gas`、`timeout: 120000`。

提示：Besu 25.10.0 的 `--tx-pool-enable-balance-check` 是 25.10.0 才引入的选项，
24.5.1 没有任何对应 CLI/TOML 键，所以**运行时镜像必须用 25.10.0 或更新版本**。
启动日志出现以下 warning 是正常的（说明零 gas 已生效）：

```
Forcing price bump for transaction replacement to 0, since we are on a zero basefee network
Forcing price bump for transaction replacement to 0, since min-gas-price is set to 0
Forcing tx-pool-min-gas-price=0, since it cannot be greater than the value of min-gas-price
```

实测：零余额账户以 `gasPrice: 0` 部署合约成功（`effectiveGasPrice` 为 0）。

### Hardhat 网络

`contracts/hardhat.config.js` 已增加：

```js
'besu-testnet': {
  url: process.env.BESU_TESTNET_RPC || 'http://127.0.0.1:8545',
  accounts: process.env.BESU_TESTNET_KEY ? [process.env.BESU_TESTNET_KEY] : [],
  chainId: 48850,
  gasPrice: 0,
  gas: 0x1ffffffffffffe, // 数值字面量；Hardhat 不接受带引号的十六进制字符串
  timeout: 120000
}
```

用法：

```bash
cd contracts
BESU_TESTNET_RPC=http://127.0.0.1:8545 \
BESU_TESTNET_KEY="$(tr -d '\r\n' < ../infra/besu-testnet/keydir/key)" \
npx hardhat run <script> --network besu-testnet
```

`npm test` 仍只跑内置 `hardhat` 网络，不依赖测试链。读操作可以不带
`BESU_TESTNET_KEY`（`accounts` 为空）。

## Cancun 与 EVM 匹配

- `shanghaiTime: 0` / `cancunTime: 0` 必须与合约编译的 `evmVersion: "cancun"`
  一致，否则合约交易可能 revert（Besu issue #8954）。
- `contractSizeLimit: 2147483647`，避免大合约部署被 24KB 限制挡住。
- 启动后每块可能看到：

  ```
  ERROR | SystemCallProcessor | Invalid system call address: 0x000f3df6d732807ef1319fb7b8bb8522d0beac02
  WARN  | CancunPreExecutionProcessor | Invalid system call address: ...
  ```

  这是 Cancun 的 EIP-4788 beacon-roots 系统调用；本测试网 `alloc` 为空，所以
  Besu 记录该日志，但空块/合约交易均正常（已实测部署）。不是出块失败的信号。

## 密钥与数据保管

- `keydir/`、`networkFiles/`、`data/`、`qbftConfig.json` 都被根 `.gitignore` 忽略；
  **绝不提交 validator 私钥或链数据**。
- 备份 `keydir/`（至少 `key`、`key.pub`、`address`）和 `networkFiles/genesis.json`。
- 私钥仅用于本测试网，不要复用到主网或任何有价值的环境。
- 丢失 key 或重新运行 `generate.sh` 会生成不同 validator/genesis；必须删除
  `data/` 后从新 genesis 重来，旧链上的合约/状态不会保留。
- 容器只读挂载 `keydir/key`。Windows/Git Bash 下 `chmod 600` 可能不生效，但
  `keydir/` 已 gitignore 且以只读方式挂载；仍不要把该目录提交或共享。Docker
  bind mount 不是硬件安全模块；生产主网验证者应离线生成并加密存档。

## RPC 安全

- compose **只**把端口绑在 `127.0.0.1`，不要在路由器/公网直接暴露。
- 如需公网访问，必须前置 Nginx（或专用代理）做 TLS + `limit_req` 限流；
  免费 gas 链尤其要防 spam。
- 不要公网暴露 `DEBUG`、`QBFT` 管理 API。本配置为本地联调开启了
  `ETH,NET,WEB3,QBFT,DEBUG`；公网部署应裁剪为最小 API 集合。
- `--host-allowlist=*` 与 `--rpc-http-cors-origins=all` 仅因本地开发需要；
  公网前置网关后再收紧。

## 停止与重置

停止（保留链数据，下次 `up -d` 继续）：

```bash
docker compose down
```

重置（会丢弃所有链上状态）：

```bash
docker compose down
rm -rf data keydir networkFiles qbftConfig.json
bash generate.sh
docker compose up -d
```

重置前先备份 `keydir/` 和 `networkFiles/genesis.json`；删除后无法恢复旧链。
`generate.sh` 会拒绝非空 `data/`，所以重置必须先删除它再重新生成。

## 故障排查

- **容器反复重启**：`docker compose logs`。若是
  `Unknown option in TOML configuration file: tx-pool-enable-balance-check`，
  说明运行时镜像太旧（该键需要 25.10.0+），把 `BESU_IMAGE` 换成
  `hyperledger/besu:25.10.0` 或更新版本。
- **正常启动但没有出块**：
  - 日志是否出现 `Loaded public key ...` 和 `Node address 0x...`；
  - `keydir/address` 是否出现在 genesis 的 `extraData` 中；
  - 挂载的是否是 `networkFiles/genesis.json`（不是源模板）；
  - `qbft_getValidatorsByBlockNumber` 是否能查到验证者（需要 `QBFT` API）；
  - 是否有旧 `data/` 与新 genesis 不匹配（清空 `data/` 重来）。
- **零 gas 交易被丢**：
  - 确认 `min-gas-price=0` 与 `tx-pool-enable-balance-check=false` 同时生效；
  - 确认 genesis `zeroBaseFee:true`；
  - 不要设置 `tx-pool-price-bump`；
  - 查看 `docker compose logs` 中的 txpool 相关日志。
- **chainId 不是 `0xbed2`**：挂错 genesis、连到别的链，或 `data/` 还是旧链；
  核对 `eth_chainId`，清 data 后重启。
- **8545 被占用**：`BESU_RPC_PORT=8546 docker compose up -d`，并把
  `BESU_TESTNET_RPC` 指到 8546。不要为此停掉其他项目的容器。
- **Windows/Git Bash 路径问题**：使用 Git Bash 运行 `generate.sh`；脚本已用
  `pwd -W` 和 `MSYS_NO_PATHCONV=1` 处理 bind mount，不要手动写死 `C:\` 路径。
- **EIP-4788 `Invalid system call address` 日志**：见上文，当前配置下属正常现象。

## 已验证记录（2026-10-27，本机）

- 生成：`networkFiles/genesis.json` 含非空 `extraData`；validator 地址以
  `keydir/address` 为准。
- `eth_chainId` → `0xbed2`（48850）。
- `eth_blockNumber` 连续两次 `0x5` → `0x8`（2s QBFT）。
- `eth_gasPrice` → `0x0`；最新块 `baseFeePerGas` 为 `0x0`。
- `qbft_getValidatorsByBlockNumber(["latest"])` 与 `keydir/address` 一致。
- 零余额账户、`gasPrice: 0` 部署最小合约成功（tx type 0，`effectiveGasPrice` 为 0）。
- Hardhat `besu-testnet` 网络实测：chainId `48850`、signer 从 `BESU_TESTNET_KEY` 加载、
  `gasPrice: 0` 交易上链成功。
- `cd contracts && npx hardhat compile && npm test` → **322 passing**。
- 本机 8545 被其他项目占用，实际用 `BESU_RPC_PORT=8546` 启动；compose 默认仍为 8545。
