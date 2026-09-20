# RTM 悬赏代币设计说明

> 对应合约：`contracts/RTMToken.sol`、`contracts/BountyVault.sol`
> 对应测试：`test/rtm.test.js`

本文说明攻击悬赏代币 REDTEAM（RTM）的发行规则，以及为什么即使某次攻击完全成功，也无法一次性掏空奖池。机制层面的完整构想见根目录《基于区块链攻击悬赏的RSI持续评估机制》。

## 1. 固定供应量

RTM 的总量固定为 **21,000,000 RTM**（`MAX_SUPPLY`），且**永不增发**：

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

## 3. 攻击者为什么无法一次性掏空奖池

单笔奖励的出口是 `BountyVault.settleClaim`，它必须同时穿过五道互相独立的约束：

| 约束 | 实现 | 攻击者能做什么 |
|---|---|---|
| **年度减半预算** | `RTMToken.mint` 校验当年剩余额度 | 无法跨年预支，也无法让某一年的支出超过该年预算 |
| **单笔认领上限** | `maxPerClaim`，配置与结算各校验一次 | 单笔收益封顶；调低上限后，此前超额配置的 claim 同样无法结算 |
| **认领一次性** | `settled` 标记 + 每 id 只可配置一次 | 同一笔奖励无法重复领取；已复核的认领不能被静默改写 |
| **仅独立评估者可配置/结算** | `onlyEvaluator` | 攻击者即使完全控制被评估的 RSI 智能体，也拿不到配置或结算权限 |
| **可暂停** | `Pausable`（`pause` / `unpause`，仅所有者） | 出现异常时可整体冻结配置与结算，已配置的认领保留、不作废 |

再加一层结构上的隔离：`BountyVault` 自身**不持有余额**，奖励在结算时按需铸造，因此不存在"金库被攻破即可转走存量"的路径，能铸造的上限永远等于发行表允许的上限。

由此得到的性质是：一次成功攻击最多拿到一笔 `<= maxPerClaim` 的奖励，且必然消耗当年预算；想拿到全年预算，就必须在该年内提交足够多的独立有效认领，而每一条都需要通过独立验证。

**预算耗尽时的行为**：若当年预算已花完，`rtm.mint` 会以 `YearBudgetExceeded` 回滚整个结算调用。认领保持“已配置、未结算”，但当前没有预算预留、取消或部分支付机制；若其金额大于后续年度减半后的预算，将可能一直无法整笔支付。不能保证所有奖励仅被延期，也不能向外承诺兑付。预算预留与认领生命周期属于后续独立改进。

**部署信任边界**：token 拒绝将零地址或 EOA 作为 minter，并在部署后锁定该地址；“有合约代码”不等于验证了 BountyVault 身份。部署者必须核对 vault 字节码和相互绑定，不能使用任意外部或可升级 minter。此实现尚未接入 Arena 判奖或真实资产。

## 4. BountyVault 在原研究构想中的位置

BountyVault 是研究构想中"独立验证与奖励"环节的链上落点，负责把一次已验证的攻击转化为一次支付：

```
攻击成功（反例可复现）
      ↓
独立验证通过（越权成立、可复现、非重复提交）
      ↓
evaluator 调用 configureClaim(id, attacker, amount)   ← 登记奖励依据
      ↓
evaluator 调用 settleClaim(id)                         ← 一次性结算
      ↓
BountyVault 调用 RTMToken.mint → RTM 铸造到攻击者账户
```

对应到构想文档中的角色边界：

- **铸造权只授予金库**：`RTMToken` 的 `minter` 指向 `BountyVault`，除此之外没有任何地址能增发。RSI 智能体、攻击者、代币所有者都不持有铸造权。
- **判奖权只在 evaluator**：只有 evaluator 能配置和结算 claim，而"是否越权"的判定由独立验证流程完成，不由被评估的 RSI 参与。链上记录的是结论，不宣称链上本身能判断攻击价值。
- **评估者可换 key**：`setEvaluator` 允许所有者在验证者轮换、密钥失效或流程升级时更换 evaluator。注意这是**热切换**：与 `RewardSettlement` 中不可变的 `evaluator` 相比，`BountyVault` 选择可轮换来换取运维弹性，代价是所有者成为该权限的信任点——研究阶段这一取舍是可接受的，主网部署前应改为两阶段移交或时间锁。
- **奖励上限即研究预算上限**：年度减半预算 + 单笔上限共同构成"攻击悬赏总支出"的硬上界。构想文档中"周期总奖池设定上限，避免无限提交带来无限增发"一条，在合约层就落成了 `yearBudget` 与 `maxPerClaim`。

## 5. 已知限制

- 链上只保证"支付不超过预算"和"同一认领不重复支付"，**不保证奖励发给了真正有价值的攻击**——这依赖 evaluator 与链下验证流程的诚实性。
- `BountyVault` 未使用 `ReentrancyGuard`：`settleClaim` 唯一的外部调用是对构造时固定、由宿主控制的 `RTMToken`，其 `mint` 不回调受益人；且状态在调用前已置为 `settled`（checks-effects-interactions），即使代币行为异常，重入也只会得到 `ClaimAlreadySettled`。若未来改为调用可升级或任意外部代币，必须补上重入锁。
- 年份按固定 365 天窗口计算，与日历年存在漂移；这是为了保持发行表的确定性，可预期性优先于日历对齐。
