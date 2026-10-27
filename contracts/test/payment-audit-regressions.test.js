// SPDX-License-Identifier: MIT
/**
 * 从 archieve/contracts-2026-10/audit-poc.test.js 抽取的现行支付合约审计回归。
 *
 * [L-01]、[L-02] 与「非 operator」边界用例只依赖 PaymentAgent、
 * RewardSettlement 与 ExperimentalToken，因此即使旧 RTM/Bounty 审计文件归档，
 * 这些修复仍需在当前测试套件中持续验证。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');

const RTM = (n) => ethers.parseEther(String(n));

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

describe('支付合约审计回归：现行合约', function () {
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

  describe('边界证明：权限不可被外部触达', function () {
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
