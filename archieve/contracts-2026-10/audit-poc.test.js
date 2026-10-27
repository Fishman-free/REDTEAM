// SPDX-License-Identifier: MIT
/**
 * 审计 PoC：漏洞复现与修复回归
 *
 * 每个用例对应审计报告中的一项发现。命名前缀即报告编号：
 *   [H-01] 高危 —— renounceOwnership 可把 BountyVault 永久变砖
 *   [M-01] 中危 —— 评估者可在无累计上限下铸造整个年度预算
 *   [M-02] 中危 —— 年度绑定的索赔在年结后失效，赏金得主无法兑付
 *   [L-01] 低危 —— operation id 与 invoice id 共用命名空间，可烧掉发票
 *   [L-02] 低危 —— 构造函数未校验零值参数
 *   [L-03] 低危 —— initializeRtm 缺失事件
 *   [L-04] 低危 —— 事件在外部调用之后发出（Slither reentrancy-events）
 *   [I-01] 信息 —— 减半排程总量不变式
 *
 * 「复现」用例描述被修复前的攻击路径；「修复后」用例断言当前代码已阻断该路径，
 * 因此这些用例在旧代码上会失败（红），在修复后的代码上通过（绿）。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

const YEAR = 365 * 24 * 60 * 60;
const RTM = (n) => ethers.parseEther(String(n));

async function deployVault() {
  const [owner, evaluator, beneficiary, outsider] = await ethers.getSigners();
  const vault = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
  const start = await time.latest();
  const rtm = await (await ethers.getContractFactory('RTMToken'))
    .deploy(owner.address, vault.target, start);
  await vault.initializeRtm(rtm.target);
  await vault.connect(owner).setEvaluator(evaluator.address);
  await vault.connect(owner).setMaxPerClaim(RTM(1000));
  return { vault, rtm, owner, evaluator, beneficiary, outsider };
}

async function deployPayments() {
  const [host, merchant, participant, evaluator, outsider] = await ethers.getSigners();
  const token = await (await ethers.getContractFactory('ExperimentalToken'))
    .deploy(RTM(1000));
  const pay = await (await ethers.getContractFactory('PaymentAgent'))
    .deploy(token, RTM(100));
  const reward = await (await ethers.getContractFactory('RewardSettlement'))
    .deploy(token, RTM(50));
  await pay.setAllowlisted(merchant.address, true);
  await pay.setAllowlisted(participant.address, true);
  // 预存资金：PaymentAgent 与 RewardSettlement 各自持有独立余额（见合约设计），
  // 构造函数不转账，必须由部署方另行注资。
  await token.transfer(pay.target, RTM(100));
  await token.transfer(reward.target, RTM(50));
  return { token, pay, reward, host, merchant, participant, evaluator, outsider };
}

describe('审计 PoC：漏洞复现与修复回归', function () {
  describe('[H-01] renounceOwnership 可把 BountyVault 永久变砖', function () {
    it('修复后：所有权不可放弃，避免永久冻结结算能力', async () => {
      const { vault, owner } = await deployVault();
      await expect(vault.connect(owner).renounceOwnership())
        .to.be.revertedWithCustomError(vault, 'RenunciationDisabled');
      expect(await vault.owner()).to.equal(owner.address);
    });

    it('修复后：暂停状态不存在通往永久冻结的路径', async () => {
      // 攻击者（或误操作）的设想路径：pause() → renounceOwnership() → 无人能 unpause()
      // → 全部索赔永久无法结算，赏金得主永远拿不到钱。
      const { vault, owner, evaluator, beneficiary } = await deployVault();
      const id = ethers.id('h01-frozen');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(10));
      await vault.connect(owner).pause();

      await expect(vault.connect(owner).renounceOwnership())
        .to.be.revertedWithCustomError(vault, 'RenunciationDisabled');

      await vault.connect(owner).unpause();
      await vault.connect(evaluator).settleClaim(id);
      expect(await vault.totalSettled()).to.equal(RTM(10));
    });
  });

  describe('[M-01] 评估者可铸造整个年度预算（原无累计上限）', function () {
    it('复现：单笔索赔即可耗尽当年全部减半预算', async () => {
      const { vault, rtm, owner, evaluator, beneficiary } = await deployVault();
      const yearBudget = await rtm.yearBudget(await rtm.currentYear());
      await vault.connect(owner).setMaxPerClaim(yearBudget);
      const id = ethers.id('m01-drain');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, yearBudget);
      await vault.connect(evaluator).settleClaim(id);

      // 攻击结果：评估者把当年 10,500,000 RTM 全部铸给自己控制的地址，
      // 合法赏金得主当年一无所获。约束只剩减半排程本身。
      expect(await rtm.balanceOf(beneficiary.address)).to.equal(yearBudget);
      expect(await rtm.totalSupply()).to.equal(yearBudget);
    });

    it('修复后：maxTotalSettled 阻断评估者的累计铸造', async () => {
      const { vault, rtm, owner, evaluator, beneficiary } = await deployVault();
      const yearBudget = await rtm.yearBudget(await rtm.currentYear());
      await vault.connect(owner).setMaxTotalSettled(RTM(100));

      const id = ethers.id('m01-capped');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(100));
      await vault.connect(evaluator).settleClaim(id);

      const id2 = ethers.id('m01-capped-2');
      await vault.connect(evaluator).configureClaim(id2, beneficiary.address, RTM(1));
      await expect(vault.connect(evaluator).settleClaim(id2))
        .to.be.revertedWithCustomError(vault, 'TotalSettledCapExceeded')
        .withArgs(RTM(101), RTM(100));

      expect(await rtm.totalSupply()).to.equal(RTM(100));
      expect(await vault.totalSettled()).to.equal(RTM(100));
      expect(yearBudget).to.be.gt(RTM(100));
    });

    it('修复后：累计上限由 owner 管理，评估者无法自行提高', async () => {
      const { vault, owner, evaluator } = await deployVault();
      await expect(vault.connect(evaluator).setMaxTotalSettled(RTM(1)))
        .to.be.revertedWithCustomError(vault, 'OwnableUnauthorizedAccount');
      await expect(vault.connect(owner).setMaxTotalSettled(0))
        .to.be.revertedWithCustomError(vault, 'ZeroAmount');
      await vault.connect(owner).setMaxTotalSettled(RTM(1));
      expect(await vault.maxTotalSettled()).to.equal(RTM(1));
    });
  });

  describe('[M-02] 年度绑定的索赔在年结后失效，赏金得主无法兑付', function () {
    it('复现：跨年后 settleClaim 被拒，合法赏金得主拿不到钱', async () => {
      const { vault, rtm, evaluator, beneficiary } = await deployVault();
      const id = ethers.id('m02-strand');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(50));
      await time.increase(YEAR + 1);

      await expect(vault.connect(evaluator).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'ClaimYearExpired').withArgs(0n, 1n);
      expect(await rtm.balanceOf(beneficiary.address)).to.equal(0n);
    });

    it('复现：取消后在新年度未必还有预算，赏金可能彻底落空', async () => {
      const { vault, rtm, evaluator, beneficiary, owner } = await deployVault();
      const id = ethers.id('m02-lost');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(50));
      await time.increase(YEAR + 1);

      // 新年度预算被别的索赔占满后，重新配置也救不回来
      const budget1 = await rtm.yearBudget(1n);
      await vault.connect(owner).setMaxPerClaim(budget1);
      await vault.connect(evaluator).cancelClaim(id);
      const hog = ethers.id('m02-hog');
      await vault.connect(evaluator).configureClaim(hog, beneficiary.address, budget1);

      await expect(vault.connect(evaluator).configureClaim(ethers.id('m02-retry'), beneficiary.address, RTM(50)))
        .to.be.revertedWithCustomError(vault, 'YearBudgetUnavailable')
        .withArgs(1n, RTM(50), 0n);
    });

    it('修复后：renewClaim 把过期索赔重新绑定到当前年度并成功兑付', async () => {
      const { vault, rtm, evaluator, beneficiary } = await deployVault();
      const id = ethers.id('m02-renew');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(50));
      await time.increase(YEAR + 1);

      await expect(vault.connect(evaluator).renewClaim(id))
        .to.emit(vault, 'ClaimRenewed')
        .withArgs(id, beneficiary.address, RTM(50), 0n, 1n);

      await vault.connect(evaluator).settleClaim(id);
      expect(await rtm.balanceOf(beneficiary.address)).to.equal(RTM(50));
      expect(await vault.reservedByYear(0n)).to.equal(0n);
      expect(await vault.reservedByYear(1n)).to.equal(0n);
    });

    it('修复后：renewClaim 不授予额外权限，仍受当前年度预算与角色约束', async () => {
      const { vault, evaluator, beneficiary, outsider } = await deployVault();
      const id = ethers.id('m02-guard');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(50));
      await time.increase(YEAR + 1);

      await expect(vault.connect(outsider).renewClaim(id))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
      // 未过期的索赔不能续期（否则等于绕过年预算检查）
      const live = ethers.id('m02-live');
      await vault.connect(evaluator).configureClaim(live, beneficiary.address, RTM(1));
      await expect(vault.connect(evaluator).renewClaim(live))
        .to.be.revertedWithCustomError(vault, 'ClaimNotExpired').withArgs(1n, 1n);
    });
  });

  describe('[L-01] operation id 与 invoice id 共用命名空间，可烧掉发票', function () {
    it('复现：把发票 id 当作 operation id 会让该发票永远无法支付', async () => {
      const { token, pay, merchant, participant } = await deployPayments();
      const invA = ethers.id('INV-A');
      const invB = ethers.id('INV-B');
      const amount = RTM(10);
      await pay.configureInvoice(invA, merchant.address, participant.address, amount);
      await pay.configureInvoice(invB, merchant.address, participant.address, amount);

      // 攻击/失误路径：用 invA 作为 operation id 去支付 invB
      await pay.pay(invA, invB, merchant.address, participant.address, amount);

      // 修复前：used[invA] 已被置位，invA 这张发票永远无法兑付（永久拒绝服务）
      // 修复后：命名空间隔离，invA 仍然可以正常支付
      await pay.pay(ethers.id('op-1'), invA, merchant.address, participant.address, amount);
      expect(await token.balanceOf(participant.address)).to.equal(amount * 2n);
    });

    it('修复后：同一 id 仍不能被重复使用（重放保护未削弱）', async () => {
      const { pay, merchant, participant } = await deployPayments();
      const inv = ethers.id('INV-R');
      const amount = RTM(10);
      await pay.configureInvoice(inv, merchant.address, participant.address, amount);
      await pay.pay(ethers.id('op-1'), inv, merchant.address, participant.address, amount);
      await expect(pay.pay(ethers.id('op-2'), inv, merchant.address, participant.address, amount))
        .to.be.revertedWith('duplicate');
      await expect(pay.pay(ethers.id('op-1'), inv, merchant.address, participant.address, amount))
        .to.be.revertedWith('duplicate');
    });
  });

  describe('[L-02] 构造函数未校验零值参数', function () {
    it('修复后：PaymentAgent 拒绝零地址代币与零上限', async () => {
      await expect(
        (await ethers.getContractFactory('PaymentAgent')).deploy(ethers.ZeroAddress, RTM(1))
      ).to.be.revertedWith('zero token');
      const { token } = await deployPayments();
      await expect(
        (await ethers.getContractFactory('PaymentAgent')).deploy(token, 0)
      ).to.be.revertedWith('zero cap');
    });

    it('修复后：RewardSettlement 拒绝零地址代币与零上限', async () => {
      await expect(
        (await ethers.getContractFactory('RewardSettlement')).deploy(ethers.ZeroAddress, RTM(1))
      ).to.be.revertedWith('zero token');
      const { token } = await deployPayments();
      await expect(
        (await ethers.getContractFactory('RewardSettlement')).deploy(token, 0)
      ).to.be.revertedWith('zero cap');
    });

    it('修复后：ExperimentalToken 拒绝零发行量', async () => {
      await expect(
        (await ethers.getContractFactory('ExperimentalToken')).deploy(0)
      ).to.be.revertedWith('zero supply');
    });
  });

  describe('[L-03] initializeRtm 缺失事件', function () {
    it('修复后：绑定代币时发出 RtmInitialized，便于链下审计', async () => {
      const [owner] = await ethers.getSigners();
      const vault = await (await ethers.getContractFactory('BountyVault')).deploy(owner.address);
      const start = await time.latest();
      const rtm = await (await ethers.getContractFactory('RTMToken'))
        .deploy(owner.address, vault.target, start);
      await expect(vault.initializeRtm(rtm.target))
        .to.emit(vault, 'RtmInitialized').withArgs(rtm.target);
    });
  });

  describe('[L-04] 事件在外部调用之后发出（Slither reentrancy-events）', function () {
    it('修复后：ClaimSettled 日志先于代币铸造事件，调用方看不到半更新状态', async () => {
      const { vault, rtm, evaluator, beneficiary } = await deployVault();
      const id = ethers.id('l04-order');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(10));
      const receipt = await (await vault.connect(evaluator).settleClaim(id)).wait();

      const vaultIface = vault.interface;
      const rtmIface = rtm.interface;
      const claimIdx = receipt.logs.findIndex(
        (l) => l.address.toLowerCase() === vault.target.toLowerCase()
          && vaultIface.parseLog(l)?.name === 'ClaimSettled'
      );
      const mintIdx = receipt.logs.findIndex(
        (l) => l.address.toLowerCase() === rtm.target.toLowerCase()
          && rtmIface.parseLog(l)?.name === 'Transfer'
      );
      expect(claimIdx).to.be.gte(0);
      expect(mintIdx).to.be.gte(0);
      expect(claimIdx).to.be.lt(mintIdx);
    });
  });

  describe('[I-01] 减半排程总量不变式', function () {
    it('每年预算逐年减半，且总和严格小于 MAX_SUPPLY', async () => {
      const { rtm } = await deployVault();
      const MAX_SUPPLY = await rtm.MAX_SUPPLY();
      const year0 = await rtm.YEAR0_BUDGET();
      expect(year0).to.equal(MAX_SUPPLY / 2n);

      let sum = 0n;
      for (let y = 0; y < 256; y += 1) {
        const b = await rtm.yearBudget(y);
        expect(b).to.equal(year0 >> BigInt(y));
        sum += b;
      }
      expect(await rtm.yearBudget(256)).to.equal(0n);
      expect(sum).to.be.lt(MAX_SUPPLY);
      // 文档给出的闭式：2 * YEAR0_BUDGET - popcount(YEAR0_BUDGET)
      expect(MAX_SUPPLY - sum).to.equal(38n);
    });
  });

  describe('边界证明：铸造与结算权限不可被外部触达', function () {
    it('非 minter 不能直接铸造 RTM，非评估者不能结算或配置', async () => {
      const { vault, rtm, owner, evaluator, beneficiary, outsider } = await deployVault();
      await expect(rtm.connect(outsider).mint(beneficiary.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      await expect(rtm.connect(owner).mint(beneficiary.address, 1n))
        .to.be.revertedWithCustomError(rtm, 'NotMinter');
      // 资金受益人本人同样不能自行放款
      const id = ethers.id('boundary');
      await vault.connect(evaluator).configureClaim(id, beneficiary.address, RTM(1));
      await expect(vault.connect(beneficiary).settleClaim(id))
        .to.be.revertedWithCustomError(vault, 'NotEvaluator');
    });

    it('非 operator 不能配置发票或发起支付', async () => {
      const { pay, merchant, participant, outsider } = await deployPayments();
      await expect(
        pay.connect(outsider).configureInvoice(ethers.id('x'), merchant.address, participant.address, 1)
      ).to.be.revertedWith('not operator');
      await expect(
        pay.connect(outsider).pay(ethers.id('x'), ethers.id('y'), merchant.address, participant.address, 1)
      ).to.be.revertedWith('not operator');
    });
  });
});
