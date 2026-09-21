# RTM 悬赏代币设计说明

> 对应合约：`contracts/RTMToken.sol`、`contracts/BountyVault.sol`
> 对应测试：`test/rtm.test.js`

本文说明攻击悬赏代币 REDTEAM（RTM）的发行上限、当年预算预留及认领生命周期。年度预算不等于“全年额度不可被耗尽”或奖励真实性保证。完整构想见 [RSI 悬赏研究构想](RSI攻击悬赏与持续评估机制_研究构想.md)。

## 1. 固定供应量上限

RTM 的总供应量上限为 **21,000,000 RTM**（`MAX_SUPPLY`），实际供应量按发行计划从零增加，不能突破上限：

- 部署时**不预挖**，`totalSupply()` 从 0 开始，部署者不获得任何代币；
- 除 `mint` 之外没有任何增发路径，`mint` 只能由单一 `minter` 角色调用；
- 铸造权在部署时绑定到指定的 `BountyVault`，且 `RTMToken.minter` 为 `immutable`；没有 `setMinter`，所以 owner、evaluator 和任何旧权限都不能把 minter 改成直接铸币地址；
- 部署顺序是：先部署 `BountyVault(owner)`，再以 vault 地址部署 `RTMToken(owner, vault, emissionStart)`，最后由 vault owner 仅调用一次 `initializeRtm(token)` 完成反向绑定。初始化前 vault 不可配置或结算 claim。

因此代币供应量的上限是部署前就公开确定的，不随治理动作变化。

## 2. 比特币式年度减半发行

发行按固定长度的时间窗口（`365 days`）逐年递减，第 `n` 年的预算为：

```
yearBudget(n) = YEAR0_BUDGET >> n
YEAR0_BUDGET  = MAX_SUPPLY / 2 = 10,500,000 RTM
```

即第 0 年可发行上限的一半，此后每年减半：10,500,000 → 5,250,000 → 2,625,000 → …，第 256 年起预算为 0，发行序列有限。

限流发生在 `RTMToken.mint` 内部，且**年份由 `block.timestamp` 推导，不由调用方指定**，所以 minter 无法挑选一个更便宜的年份来增发。每笔铸造同时受两个独立上界约束：

1. 当年剩余预算：`mintedByYear[year] + amount <= yearBudget(year)`；
2. 剩余供应量：`totalSupply() + amount <= MAX_SUPPLY`。

**关于"逐年预算之和"**：整数逐次右移会丢弃余数，因此

```
sum(n>=0) yearBudget(n) = 2 * YEAR0_BUDGET - popcount(YEAR0_BUDGET)
                        = MAX_SUPPLY - 38 wei
```

38 是 `YEAR0_BUDGET` 的二进制 1 的个数。也就是说预算表之和**严格小于** `MAX_SUPPLY`（留有 38 wei 的余量），即使每一年都被铸造到最后一 wei 也无法触及上限——发行表本身就封死了无限增发的可能，`MAX_SUPPLY` 只是冗余的第二道边界，而不是唯一防线。（`test/rtm.test.js` 对 n = 0…255 求和并断言该等式。）

## 3. 年度预算与授权边界

奖励的登记、结算和取消由 `BountyVault` 管理，同时受以下约束：

| 约束 | 实现 | 攻击者能做什么 |
|---|---|---|
| **年度减半预算** | `RTMToken.mint` 校验当年剩余额度 | 无法跨年预支，也无法让某一年的支出超过该年预算 |
| **当年整笔预留** | `configureClaim` 固定 `emissionYear`，增加 `reservedByYear[year]` | 已铸造量与所有未终结认领的预留之和不超过当年预算，不能超额承诺 |
| **单笔认领上限** | `maxPerClaim`，配置与结算各校验一次 | 调低上限后，超额 claim 保留预留但无法结算；可显式取消，或在同年恢复上限后结算 |
| **认领一次性** | 每 id 只可配置一次；`settled` / `cancelled` 为不可逆终态 | 已支付或已取消的 id 均不能重配、再支付或再取消 |
| **仅独立评估者可配置/结算/取消** | 三个操作均为 `onlyEvaluator` | owner、受益人、外部地址若不是当前 evaluator，均不能进行这些操作 |
| **可暂停** | `Pausable`（`pause` / `unpause`，仅所有者） | 同时冻结配置、结算和取消；不释放预留，也不停止发行年份计时 |

再加一层结构上的隔离：`BountyVault` 自身**不持有余额**，奖励在结算时按需铸造，因此不存在"金库被攻破即可转走存量"的路径，能铸造的上限永远等于发行表允许的上限。

由此得到的性质是：每笔支付 `<= maxPerClaim`，并且登记时就消耗绑定年度的预留容量。若 owner 将 `maxPerClaim` 设为全年预算，一笔认领仍可以占用整个当年预算；合约不会验证不同 id 是否对应独立攻击，去重与有效性仍由 evaluator 负责。年度发行限制保护的是总量边界，并不是链上攻击价值判断。

### 3.1 当年预算预留

对每个发行年 `y`，在真实 RTMToken 与本 vault 的正常调用路径中保持：

```
R[y] = sum(amount of configured && !settled && !cancelled claims with emissionYear == y)
mintedByYear[y] + R[y] <= yearBudget(y)
remaining[y] = max(yearBudget(y) - mintedByYear[y], 0)
available[y] = max(remaining[y] - R[y], 0)
```

- `configureClaim(id, beneficiary, amount)` 读取 **RTM 当前发行年**，只允许 `amount <= available[currentYear]`，随后整笔预留并固定 `emissionYear`。caller 不能指定下一年、追溯旧年或只预留部分金额。
- `availableCurrentYearBudget()` 返回当前年尚未铸造、也未被其他 claim 预留的容量。与 `RTMToken.remainingThisYear()` 不同，它会扣除预留。分两次饱和相减避免下溢；未初始化时以 `RtmNotInitialized` 回滚，发行开始前沿用 `RTMToken.currentYear()` 的 arithmetic panic `0x11`。
- 预算不足在**配置阶段**以 `YearBudgetUnavailable(year, requested, available)` 拒绝；失败不会占用 id 或预留，也不会产生任何代币。
- 结算再次检查绑定年仍为当前年，且整笔金额不超过该年尚未铸造的预算。这里不再扣除自身预留：即使 `availableCurrentYearBudget() == 0`，已完整预留的 claim 仍可结算。
- 成功结算将该年预留减去 `amount`、置 `settled = true`、累加 `totalSettled`，然后调用 `rtm.mint`。mint 失败则上述状态及代币侧变化全部回滚，claim 仍 configured / unsettled / uncancelled，预留完整保留。

**预留只保护当年发行容量，不是实物托管或未来兑付保证**。取消在同一年释放可配置容量；成功结算把预留变为已铸造量，并不会创造额外的当年容量。

### 3.2 生命周期与跨年处理

| 操作/状态 | 条件与结果 |
|---|---|
| 未配置 → 已配置 | evaluator 在未暂停时配置；完整占用当前年可用容量，固定受益人、金额和年份 |
| 已配置 → 已结算 | evaluator 在同一发行年、未暂停、金额仍符合当前单笔上限时整笔结算；释放预留恰好一次 |
| 已配置 → 已取消 | evaluator 在未暂停时 `cancelClaim(id)`；标记 `cancelled` 并释放**绑定年度**预留恰好一次，不 mint、不增加 `totalSettled` |
| 发行年已切换、尚未终结 | 仍保留旧年预留及原 claim 数据；`settleClaim` 以 `ClaimYearExpired(claimYear, currentYear)` 拒绝，即使金额小到下一年也能负担 |
| 已结算/已取消 | `configured` 仍为 true，永久占用该 id；不允许重新配置或再次结算/取消 |

跨年后的未终结 claim **只能显式取消，不能自动迁移、部分支付或静默重定价**。取消只减少 `reservedByYear[oldYear]`，对新年的可用容量和预留没有影响。若后续仍决定发奖，必须由 evaluator 用**新 id**重新审核、按新一年的预算配置；不保证重新配置成功。暂停期间年份仍会前进，因此 unpause 后旧 claim 可能只能取消。

`cancelClaim` 不校验当前 `maxPerClaim` 或当前发行年，避免调低单笔上限或 rollover 使预留无法释放；但按照本地策略，暂停时取消也被阻止。evaluator 轮换不改 claim 或预留，新 evaluator 接手所有未终结 claim，旧 key 立即失去配置、结算和取消权限。

### 3.3 精确 API 与可观测性

`RTMToken` 的实现与 ABI 均未变；部署/初始化顺序仍沿用 main 的一次绑定和 immutable minter 语义。**本版本用于新建本地部署，不是原地升级**：Claim 的存储布局/getter 和配置事件 ABI 已改变，既有 vault/token 也不能通过重新绑定完成迁移。BountyVault 的主要 API 为：

- `claims(bytes32 id)` → `(address beneficiary, uint256 amount, uint256 emissionYear, bool configured, bool settled, bool cancelled)`；返回 tuple 顺序较旧版本有变化。
- `reservedByYear(uint256 year)` → `uint256`；包含该年全部未结算、未取消的认领，包括 rollover 后尚未显式取消的旧 claim。
- `availableCurrentYearBudget()` → `uint256`；只读，不是具备保留效力的报价，真正的检查发生在配置交易执行时。
- `configureClaim(bytes32 id, address beneficiary, uint256 amount)`、`settleClaim(bytes32 id)` 参数不变；新增 `cancelClaim(bytes32 id)`。三个写操作均为 evaluator-only + whenNotPaused。
- 配置事件变为 `ClaimConfigured(bytes32 indexed id, address indexed beneficiary, uint256 amount, uint256 indexed year)`，**事件签名已变**，旧事件消费者需更新。
- `ClaimSettled(bytes32 indexed id, address indexed beneficiary, uint256 amount, uint256 year)` 签名不变；新增同字段的 `ClaimCancelled`，其中 year 始终是被取消 claim 的旧绑定年份。
- 新错误为 `YearBudgetUnavailable(uint256 year, uint256 requested, uint256 available)`、`ClaimYearExpired(uint256 claimYear, uint256 currentYear)`、`ClaimAlreadyCancelled()`。`YearBudgetUnavailable` 在配置时的 available 已扣预留，在结算时表示尚未铸造的容量。
- 防御性错误 `ReservationInvariantBroken(uint256 year, uint256 reserved, uint256 required)` 防止释放预留时下溢；正常生命周期无法触发。原有授权、暂停、初始化、单笔上限和一次性错误继续使用，未用字符串替代。

**部署信任边界**：token 拒绝将零地址或 EOA 作为 minter，并在部署后锁定该地址；“有合约代码”不等于验证了 BountyVault 身份。部署者必须核对 vault 字节码和相互绑定，不能使用任意外部或可升级 minter。此实现尚未接入 Arena 判奖或真实资产。

## 4. BountyVault 在原研究构想中的位置

BountyVault 是研究构想中"独立验证与奖励"环节的链上落点，负责把一次已验证的攻击转化为一次支付：

```
攻击成功（反例可复现）
      ↓
独立验证通过（越权成立、可复现、非重复提交）
      ↓
evaluator 调用 configureClaim(id, attacker, amount)   ← 登记奖励依据并预留当前年容量
      ↓
 evaluator 调用 settleClaim(id)                         ← 同年一次性结算
      ↓
 BountyVault 调用 RTMToken.mint → RTM 铸造到攻击者账户

若发行年已经切换，evaluator 必须先调用 `cancelClaim(id)` 释放旧年预留；取消不会 mint，也不会把额度补回新年预算。若仍需奖励，须以新 id 重新审核并在新年配置。
```

对应到构想文档中的角色边界：

- **铸造权只授予金库**：`RTMToken` 的 `minter` 指向 `BountyVault`，除此之外没有任何地址能增发。RSI 智能体、攻击者、代币所有者都不持有铸造权。
- **判奖权只在 evaluator**：只有 evaluator 能配置、结算和取消 claim，而"是否越权"的判定由独立验证流程完成，不由被评估的 RSI 参与。链上记录的是结论，不宣称链上本身能判断攻击价值。
- **评估者可换 key**：`setEvaluator` 允许所有者在验证者轮换、密钥失效或流程升级时更换 evaluator。注意这是**热切换**：与 `RewardSettlement` 中不可变的 `evaluator` 相比，`BountyVault` 选择可轮换来换取运维弹性，代价是所有者成为该权限的信任点——研究阶段这一取舍是可接受的，主网部署前应改为两阶段移交或时间锁。
- **奖励上限即研究预算上限**：年度减半预算 + 单笔上限共同构成"攻击悬赏总支出"的硬上界。构想文档中"周期总奖池设定上限，避免无限提交带来无限增发"一条，在合约层就落成了 `yearBudget` 与 `maxPerClaim`。

## 5. 已知限制

- 链上只保证"支付不超过预算"和"同一认领不重复支付"，**不保证奖励发给了真正有价值的攻击**——这依赖 evaluator 与链下验证流程的诚实性。
- `BountyVault` 未使用 `ReentrancyGuard`：token 经 `initializeRtm` 一次绑定后不可替换，`settleClaim` 的外部交互只有该 RTMToken 的只读查询和 `mint`；真实 `mint` 不回调受益人。调用 mint 前已经标记 settled、释放预留并更新累计数，任何 mint revert 均原子回滚。这个论证以核验过的固定 RTMToken 为前提，不是对任意恶意/可升级 token 的通用保证。
- 年份按固定 365 天窗口计算，与日历年存在漂移；按交易被打包的 `block.timestamp` 绑定/核对年份，而不是签名时或客户端预览时的年份。预留不会延长生命周期，也没有未来年度兑付保证。
- 尚未接入 Arena 判奖、生产系统、主网或真实资产；本轮只针对本地合约与确定性测试。部署者仍须验证双方字节码及互相绑定。

## 6. 本地验证范围

`test/rtm.test.js` 覆盖：竞争性预留与 `minted + reserved <= budget`、已耗尽年度不能再配置、下一年减半、精确年度边界、旧年认领拒付/取消、成功结算与取消恰好释放一次、终态 id 不可复用、授权轮换、降低单笔上限、暂停三个写操作及暂停跨年、未来发行起点、零预算年份、初始化不可重绑，以及 mint 失败后的原子回滚。

故障测试只在 Hardhat 进程内进行：一项临时 impersonate vault 以模拟预算意外消耗，验证 vault 复检与饱和减法；另一项临时写入 RTM 的 ERC20 totalSupply 槽，让真实 `mint` 触发 `MaxSupplyExceeded`，检查 claim、预留、累计数和余额未变化，恢复槽值后再次正常结算。这不是生产入口或用户可用权限，不修改 RTM 代码/ABI，也不新增 mock 合约。

验证命令为 `npm test`、`npx hardhat compile`、`git diff --check`，另对本次修改做隐私/凭据模式扫描。不连接外部 RPC、不使用真实资金或远程 LLM。全套既有支付-agent 测试仍运行其本地离线 mock 路径，并非新增 RTM/Arena/生产集成。
