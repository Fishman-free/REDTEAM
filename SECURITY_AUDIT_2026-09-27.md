# 智能合约安全审计报告

**项目**：REDTEAM —— 基于区块链攻击悬赏的 RSI 持续评估机制
**审计对象**：`contracts/` 下全部 5 份 Solidity 合约 + `test/` 审计 PoC
**审计师**：区块链安全审计师
**审计日期**：2026-09-27
**代码基线**：`main` @ `f97b37e`（审计前）
**编译器**：Solidity 0.8.24（evm target paris）
**依赖**：`@openzeppelin/contracts` 5.6.1
**审计提交**：见文末「变更记录」

---

## 一、执行摘要

本次审计对 REDTEAM 项目的链上结算层做了完整的人工逐行评审与自动化静态分析。在审范围共 **5 份合约、约 1,150 行 Solidity**，覆盖两类资金路径：

1. **RTM 发行路径**（`RTMToken` + `BountyVault`）——按比特币式逐年减半排程铸造攻击悬赏；
2. **实验支付路径**（`PaymentAgent` + `RewardSettlement` + `ExperimentalToken`）——本地 RSI 攻防实验中的付款与赏金发放。

**总体结论**：合约的核心安全边界设计是扎实的。铸造权限链（`minter` 不可变 → `BountyVault` → `evaluator`）不可被外部触达，减半排程有数学上的双保险（排程总和本身严格小于 `MAX_SUPPLY`，另有一道 `MAX_SUPPLY` 检查），`settleClaim` 的状态更新在外部调用之前且失败原子回滚。**未发现可直接盗取资金的 Critical 漏洞。**

审计共识别 **14 项发现**：

| 严重程度 | 数量 | 已修复 | 已确认（不改） |
|---|---|---|---|
| Critical | 0 | — | — |
| High | 1 | 1 | 0 |
| Medium | 3 | 2 | 1 |
| Low | 4 | 4 | 0 |
| Informational | 6 | 1 | 5 |
| **合计** | **14** | **8** | **6** |

修复后回归结果：**Hardhat 74/74 全绿**（含 19 个新增 PoC 用例）、**Python 80/80 通过**、Slither 报告项由 4 降至 2（剩余 2 项为设计内时间戳依赖）。

---

## 二、审计范围

| 合约 | 行数 | 角色 | 资金性质 |
|---|---|---|---|
| `RTMToken.sol` | 146 | RTM（REDTEAM）减半发行代币 | 铸造，无预挖 |
| `BountyVault.sol` | 262 | 悬赏配置/预留/结算/取消 | 铸造出口 |
| `PaymentAgent.sol` | 165 | 实验付款执行权 | 预存 ERC-20 |
| `RewardSettlement.sol` | 114 | 实验赏金发放权 | 预存 ERC-20 |
| `ExperimentalToken.sol` | 20 | 实验合成资产（XEXP） | 铸造一次 |

**信任模型**（审计基线）：

- `owner`：可轮换 evaluator、调整 `maxPerClaim` / `maxTotalSettled`、绑定代币、暂停/恢复。**不可铸造。**
- `evaluator`：独立判别攻击是否成功并配置/结算悬赏。**不可改上限与授权。**
- `operator`（`PaymentAgent`）：配置发票与发起付款，受 `maxPayment` 累计上限约束。
- `minter`：`RTMToken` 构造时**不可变**绑定为 `BountyVault`，事后无法替换。
- 外部参与者（攻击方）：**无任何写权限**，仅能提交攻击内容给链下智能体。

---

## 三、发现明细

### [H-01] `renounceOwnership` 可把 BountyVault 永久变砖

**严重程度**：High
**状态**：✅ 已修复
**位置**：`BountyVault.sol`（继承自 `Ownable.renounceOwnership`）

**描述**：
`BountyVault` 的 `initializeRtm` / `setEvaluator` / `setMaxPerClaim` / `pause` / `unpause` 全部由 `onlyOwner` 保护，但合约未限制 `Ownable.renounceOwnership()`。一旦 owner 放弃所有权，上述函数将**永久不可调用**。

**影响**：
- 若在 `initializeRtm` 之前放弃 → 该金库永远无法绑定 RTM，**整个悬赏结算能力永久作废**（部署即废）；
- 若在 `pause()` 之后放弃 → **无人能 `unpause()`**，全部索赔永久无法结算，合法赏金得主永远拿不到钱；
- 该操作不可逆，无任何恢复路径。

按严重程度定义，「协议可被管理员变砖」属 High。

**PoC**：`test/audit-poc.test.js` → `[H-01] renounceOwnership 可把 BountyVault 永久变砖`
```javascript
// 攻击者/误操作的设想路径：pause() → renounceOwnership() → 无人能 unpause()
await vault.connect(owner).pause();
await expect(vault.connect(owner).renounceOwnership())
  .to.be.revertedWithCustomError(vault, 'RenunciationDisabled');
await vault.connect(owner).unpause();          // 恢复路径完好
await vault.connect(evaluator).settleClaim(id); // 结算正常
```

**建议（已实施）**：
覆写 `renounceOwnership()` 使其恒定 revert，并保留 `transferOwnership` 作为交接手段：
```solidity
function renounceOwnership() public view override onlyOwner {
    revert RenunciationDisabled();
}
```

---

### [M-01] 评估者无累计铸造上限，可耗尽整个年度预算

**严重程度**：Medium
**状态**：✅ 已修复
**位置**：`BountyVault.sol#settleClaim`、`BountyVault.sol#configureClaim`

**描述**：
`maxPerClaim` 只约束**单笔**索赔金额，`totalSettled` 仅作累计记录、从不作为上限校验。因此被攻陷的 evaluator 只要把 `maxPerClaim` 调高（由 owner 设定，但 evaluator 可用多笔小额索赔绕过单笔限制），即可在**同一年度内**通过 N 笔索赔铸走 `yearBudget(year)` 的全部额度（year 0 为 10,500,000 RTM），合法赏金得主当年一无所获。

**影响**：
在 evaluator 密钥泄漏或作恶的前提下，当年减半预算可被**全额**铸给攻击者地址。约束只剩减半排程本身——这正是设计文档所说的「外层边界」，但缺少第二道闸门。

**PoC**：`test/audit-poc.test.js` → `[M-01]`
```javascript
const yearBudget = await rtm.yearBudget(await rtm.currentYear());
await vault.connect(evaluator).configureClaim(id, beneficiary, yearBudget);
await vault.connect(evaluator).settleClaim(id);
expect(await rtm.totalSupply()).to.equal(yearBudget);  // 当年预算被一笔吃光
```

**建议（已实施）**：
新增 owner 可调的**累计结算上限** `maxTotalSettled`（默认 `type(uint256).max`，即不改变既有行为），与 `maxPerClaim` 构成双闸门：
```solidity
uint256 public maxTotalSettled = type(uint256).max;
// settleClaim 内：
if (settledTotal + c.amount > maxTotalSettled) revert TotalSettledCapExceeded(...);
```
owner 可在 evaluator 通过考验后收紧该上限。回归用例证明：上限生效后第二笔结算被拒，`totalSupply` 不再增长。

---

### [M-02] 年度绑定的索赔在年结后失效，赏金得主可能无法兑付

**严重程度**：Medium
**状态**：✅ 已修复（新增 `renewClaim`，不改变既有语义）
**位置**：`BountyVault.sol#settleClaim`（`ClaimYearExpired`）

**描述**：
索赔在**配置当年**必须结算或取消：`settleClaim` 强制 `c.emissionYear == rtm.currentYear()`。因此若 evaluator 在年末配置了索赔、未能在跨年前结算，该索赔即告失效。

**影响**：
这是对**合法赏金得主**的公平性风险，而非攻击者收益：
1. 跨年后 `settleClaim` 直接 revert `ClaimYearExpired`，得主拿不到钱；
2. evaluator 只能 `cancelClaim` 后在新年度重新配置；
3. 若新年度预算已被其它索赔占满，重新配置会 revert `YearBudgetUnavailable`，**赏金彻底落空**。

该语义是被现有测试显式锁定的**设计决定**（`rejects settlement at rollover...`），因此本次不改变 `settleClaim` 的行为，而是补充一条明确的补救路径。

**PoC**：`test/audit-poc.test.js` → `[M-02]`（三例：跨年失效 / 取消后预算被占导致落空 / `renewClaim` 补救）

**建议（已实施）**：
新增 `renewClaim(bytes32 id)`（仅 evaluator）：把过期索赔的预留从旧年度释放、重新绑定到当前年度，前提是当前年度仍有额度。它**不改变受益人与金额**，等价于 evaluator 自行 cancel + 重新配置，不授予任何额外权限：
```solidity
function renewClaim(bytes32 id) external onlyEvaluator whenNotPaused {
    ...
    if (oldYear == year) revert ClaimNotExpired(oldYear, year);   // 未过期不能续
    if (c.amount > available) revert YearBudgetUnavailable(...);   // 仍受当年预算约束
    reservedByYear[oldYear] = reserved - c.amount;
    c.emissionYear = year;
    reservedByYear[year] += c.amount;
    emit ClaimRenewed(id, c.beneficiary, c.amount, oldYear, year);
}
```
回归用例证明：续期后可正常兑付，且续期本身仍受角色与预算约束。

---

### [M-03] 付款/赏金合约缺少应急开关，权威密钥泄漏即被全额提走

**严重程度**：Medium
**状态**：⚠️ 已确认（不改动，建议进入 v2）
**位置**：`PaymentAgent.sol`、`RewardSettlement.sol`

**描述**：
`PaymentAgent.operator` 与 `RewardSettlement.evaluator` 均为**不可轮换**的权威（前者构造时绑定 `msg.sender`，后者为 `immutable`），且两者**均无 `pause` 或任何紧急制动**。一旦权威私钥泄漏，攻击者可按既有合法流程把预存余额提空（受 `maxPayment` / `cap` 累计上限约束），协议侧**无任何缓解手段**。

**影响**：
有条件的资金损失，损失上限 = 预存余额与累计上限二者取小。需要「权威私钥泄漏」这一前置状态，故定 Medium 而非 High。

**PoC**：属流程滥用而非逻辑缺陷，无独立复现用例；边界证明见 `test/audit-poc.test.js` → `边界证明`（确认外部账户无法触达这些函数）。

**建议**（未实施，因改动会触及既有设计声明）：
合约文档明确声明「授权面不可重新指派」是**刻意设计**，新增 owner/pause 会改变这一信任模型。建议在 v2 中二选一：
1. 引入独立的应急 signer（多签或时间锁）持有 `pause` 权限，与操作权分离；
2. 将权威改为可轮换 + 时间锁，使私钥泄漏后存在恢复路径。
在 v2 之前，**运维上应把这两个地址置于多签或硬件隔离之下**，并把累计上限设为实际需要的最小值。

---

### [L-01] operation id 与 invoice id 共用 `used` 命名空间，可烧掉发票

**严重程度**：Low
**状态**：✅ 已修复
**位置**：`PaymentAgent.sol#pay`

**描述**：
`pay()` 用同一个 `mapping(bytes32 => bool) used` 同时记录 operation id 与 invoice id。若某个 operation id 恰好等于某张**未使用**发票的 id，该发票会被 `used[invoice] = true` 顺带置位，此后永远无法支付（revert `duplicate`）。

**影响**：
可让一笔合法付款**永久拒绝服务**。由于只有 operator 能调用 `pay`，攻击者无法主动触发，故定 Low 而非 Medium；但它同时也是一个会让 operator 误操作烧掉发票的正确性缺陷。

**PoC**：`test/audit-poc.test.js` → `[L-01]`
```javascript
await pay.pay(invA, invB, merchant, participant, amount);   // 用 invA 当 operation id
// 修复前：used[invA] 已置位 → 下行 revert 'duplicate'，发票 A 永久报废
await pay.pay(op1, invA, merchant, participant, amount);    // 修复后：正常支付
```

**建议（已实施）**：
拆分为两个命名空间，重放保护语义不变（revert 字符串仍为 `"duplicate"`）：
```solidity
mapping(bytes32 => bool) public usedOps;
mapping(bytes32 => bool) public usedInvoices;
// pay(): require(!usedOps[op] && !usedInvoices[invoice], "duplicate");
```

---

### [L-02] 构造函数未校验零值参数

**严重程度**：Low
**状态**：✅ 已修复
**位置**：`PaymentAgent.sol`、`RewardSettlement.sol`、`ExperimentalToken.sol` 构造函数

**描述**：
三份合约的构造函数均不校验入参：`PaymentAgent`/`RewardSettlement` 允许零地址代币与零上限，`ExperimentalToken` 允许零发行量。零地址代币会在首次 `safeTransfer` 时以难懂的方式失败（OZ `Address.functionCall` 报 call to non-contract），零上限则使合约自始不可用。

**影响**：
部署误配置会导致合约不可用或报错难以定位，属运维 footgun，无资金损失路径。

**PoC**：`test/audit-poc.test.js` → `[L-02]`

**建议（已实施）**：
```solidity
require(address(t) != address(0), "zero token");
require(cap > 0, "zero cap");          // PaymentAgent / RewardSettlement
require(supply > 0, "zero supply");    // ExperimentalToken
```
新增 revert 字符串均为**新增**检查，不与任何既有断言冲突（已全量回归验证）。

---

### [L-03] `initializeRtm` 缺失事件

**严重程度**：Low
**状态**：✅ 已修复
**位置**：`BountyVault.sol#initializeRtm`

**描述**：
金库与 RTM 代币的绑定是**一次性且不可逆**的关键状态变更，却没有任何事件发出，链下无法审计「何时、绑定了哪个代币」。

**建议（已实施）**：
```solidity
event RtmInitialized(address indexed rtm);
// initializeRtm 内：emit RtmInitialized(address(rtm_));
```

---

### [L-04] `settleClaim` 的事件在外部调用之后发出

**严重程度**：Low
**状态**：✅ 已修复
**位置**：`BountyVault.sol#settleClaim`

**描述**：
Slither `reentrancy-events` 检出：`emit ClaimSettled(...)` 位于 `rtm.mint(...)` 这一外部调用之后。虽然 `rtm` 是不可变绑定的 `RTMToken`，其 `_mint` 不含回调，实际不可利用，但「日志在交互之后」违反 checks-effects-interactions 的日志侧最佳实践，且若未来 `rtm` 实现发生变化，索引方会看到不一致的顺序。

**建议（已实施）**：
把 `emit` 移到 `rtm.mint` 之前（revert 语义下日志同样回滚，行为不变）。回归用例断言 `ClaimSettled` 日志索引严格早于 RTM `Transfer` 铸造事件。

---

### [I-01] `currentYear()` 在 `emissionStart` 之前会 panic 0x11

**严重程度**：Informational
**状态**：⚠️ 设计内，不改动

`RTMToken.currentYear()` 计算 `(block.timestamp - emissionStart) / 365 days`，在 `emissionStart` 之前会因下溢 revert（`Panic(0x11)`），进而使 `mint`、`availableCurrentYearBudget`、`configureClaim` 一并失败。这是**被测试显式断言**的既定行为（`does not promise a claim before RTM emission starts`），且避免了「排程起点不确定」的问题。
**建议**：文档已说明；如需更友好，可加 `require(block.timestamp >= emissionStart)` 转为自定义错误。鉴于测试已锁定 `Panic(0x11)`，本次不动。

### [I-02] `initializeRtm` 用 `ZeroAddress` 表达「minter 不匹配」

**严重程度**：Informational
**状态**：⚠️ 被测试锁定，不改动

`if (address(rtm_) == address(0) || rtm_.minter() != address(this)) revert ZeroAddress();` —— 当传入的代币并未把本金库设为 minter 时，报的是 `ZeroAddress`，语义误导。应使用独立的 `InvalidRtm()`。
**建议**：现有测试断言了 `ZeroAddress`（`requires owner initialization and rejects rebinding`），改名会破坏契约；建议在 v2 中统一替换。

### [I-03] `RTMToken` 继承 `Ownable` 但没有任何 owner 权限函数

**严重程度**：Informational
**状态**：⚠️ 不改动（避免 ABI 变更）

`RTMToken` 的 `owner` 是**惰性角色**：合约内不存在 `onlyOwner` 函数，owner 既不能铸造也不能改参数。这会让集成方误以为 owner 有控制权。
**建议**：v2 中移除 `Ownable` 继承，或在文档中明确「owner 无任何权限」。本次保留以免改变 ABI/部署脚本。

### [I-04] 权威不可轮换（`operator` / `evaluator`）

**严重程度**：Informational
**状态**：部分采纳（`operator` 改 `immutable`）

`PaymentAgent.operator` 原本声明为可写存储但从未被再赋值，Slither `immutable-states` 检出。已改为 `address public immutable operator`（ABI 不变、gas 降低、且编译期封死事后改写）。`RewardSettlement.evaluator` 本就是 `immutable`。
不可轮换是文档声明的设计（见 [M-03] 的风险与建议）。

### [I-05] 未声明代币行为假设（转账收费/通缩/重基）

**严重程度**：Informational
**状态**：⚠️ 建议补充文档

`totalPaid` / `paid` 按**请求额**而非**到账额**累计。若 `token` 为 fee-on-transfer 或 rebasing 代币，账面累计值会与实际到账不符。当前 `token` 为无回调的实验代币 `ExperimentalToken`，不触发该问题。
**建议**：在合约文档中显式声明「仅支持标准 ERC-20（无转账税/无重基/无回调）」，或改用 `balanceOf` 前后差值记账。

### [I-06] 年度推导依赖 `block.timestamp`

**严重程度**：Informational
**状态**：⚠️ 设计内，不改动

Slither `timestamp` 检出 `RTMToken.mint` / `remainingThisYear` 使用时间戳比较。减半排程以时间为基础是**设计本身**；验证者对时间戳的操纵幅度约 ±12–15 秒，相对 365 天的年度窗口影响可忽略（约 5e-7）。
**建议**：保持现状；若要更严格，可把年度窗口改为区块高度。

### [I-07] `ExperimentalToken` 无发行上限

**严重程度**：Informational
**状态**：⚠️ 设计内，不改动

`ExperimentalToken` 在构造时一次性铸造 `supply` 给部署者，无上限、无增发函数。它是**仅在本地实验链内使用的合成资产**（文档已声明「在进程内链之外无任何价值」），不构成风险。

---

## 四、已验证的安全性质（未发现漏洞）

以下性质经人工评审 + PoC 负向断言共同确认**不成立**为漏洞：

| 性质 | 验证方式 |
|---|---|
| 外部账户无法铸造 RTM | `NotMinter`，含 owner 也无法铸造 |
| 铸造总量不可能超过 `MAX_SUPPLY` | 减半排程闭式总和 = `MAX_SUPPLY - 38` wei（PoC 断言精确值 38），另有一道 `MaxSupplyExceeded` |
| 预留不会超卖年度预算 | 不变式 `reserved <= remaining` 在 configure/settle/cancel 三处均维持 |
| `settleClaim` 不存在重入 | 状态更新在前、`rtm.mint` 无回调、`c.settled` 已置位；Slither `reentrancy-eth` / `reentrancy-no-eth` 零结果 |
| 结算失败原子回滚 | `rtm.mint` revert 时索赔状态、预留、`totalSettled`、铸造效果全部回滚（既有测试覆盖） |
| 支付不存在重放 | operation id 与 invoice id 双重单次消费，且 `onlyOperator` 阻断回调重入 |
| 受益人无法自行放款 | `onlyEvaluator` / `onlyOperator` 负向断言 |
| 暂停不是扣押机制 | `pause` 保留索赔与预留，`unpause` 后照常结算（既有测试覆盖） |

---

## 五、验证矩阵

| 命令 | 范围 | 结果 |
|---|---|---|
| `npm test` | Hardhat 全量（含 19 个审计 PoC） | **74/74 通过**（24s） |
| `npx hardhat test test/evm.test.js test/agent-e2e.test.js test/hardening.test.js` | 既有 legacy 用例 | 全绿，零回归 |
| `python -m pytest -q` | Python 侧（redteam/） | **80 passed, 27 subtests** |
| `npx hardhat compile` | 全部 5 份合约 | 编译通过（paris） |
| `python -m slither . --detect reentrancy-eth,reentrancy-no-eth,arbitrary-send-eth,suicidal,controlled-delegatecall,uninitialized-state,unchecked-transfer,locked-ether` | 高置信度检测器 | **0 result(s)** |
| `python -m slither .` | 全量 102 检测器 | 4 → **2**（剩余 2 项为 I-06 时间戳，设计内） |

**环境说明**：审计在 Windows / PowerShell 5.1 上执行，Slither 0.11.6 + solc-select 0.8.24。

---

## 六、上线前建议

**必须落实（本次已修复，需复核）**：
1. 部署时把 `BountyVault.owner` 置于多签或时间锁之下（H-01 的残余风险由 owner 权限集中度决定）；
2. 部署后立即 `setMaxTotalSettled` 为实际需要的最小值（M-01 的第二道闸门默认是关闭的）；
3. `setMaxPerClaim` 设为单笔悬赏的真实上限，不要为省事设成巨大值。

**建议 v2 落实**：
4. 为 `PaymentAgent` / `RewardSettlement` 增加与操作权分离的应急 `pause`（M-03）；
5. `initializeRtm` 的 `ZeroAddress` 改为 `InvalidRtm`，`RTMToken` 移除惰性 `Ownable`（I-02 / I-03）；
6. 文档显式声明支持的代币行为（I-05）。

**残余风险**：
- evaluator 密钥安全是整个悬赏层的信任根，链上无法替代；
- 时间戳依赖（I-06）不可完全消除，但影响可忽略；
- 本审计覆盖链上结算层，**不覆盖**链下智能体（攻击环/防御环/判别器）与 A2A 支付协议层——那部分见 `ATTACK_INTERFACE_DESIGN.md` 与 `SECURITY_REVIEW_2026-09-18.md`。

---

## 七、变更记录

本次审计的代码变更（均为增量式修改，**保留全部既有 revert 字符串与语义**）：

| 文件 | 变更 |
|---|---|
| `contracts/BountyVault.sol` | 新增 `maxTotalSettled` + `setMaxTotalSettled`、`renewClaim`、`RtmInitialized` / `ClaimRenewed` / `MaxTotalSettledUpdated` 事件、禁用 `renounceOwnership`；`settleClaim` 补累计上限检查并把日志移到外部调用之前 |
| `contracts/PaymentAgent.sol` | `operator` 改 `immutable`；`used` 拆为 `usedOps` / `usedInvoices`；构造函数零值校验 |
| `contracts/RewardSettlement.sol` | 构造函数零值校验 |
| `contracts/ExperimentalToken.sol` | 构造函数零发行量校验 |
| `test/audit-poc.test.js` | **新增**，19 个 PoC / 回归用例，覆盖全部已修复发现 |

**兼容性**：既有 55 个测试全部原样通过；既有 `revertedWith('...')` 字符串与 `revertedWithCustomError(...)` 自定义错误名均未改动。唯一 ABI 变更为 `PaymentAgent.used` → `usedOps` / `usedInvoices`（公开 getter，经全仓库检索无外部引用）。
