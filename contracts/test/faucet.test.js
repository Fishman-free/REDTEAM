// SPDX-License-Identifier: MIT
/**
 * Faucet 测试网水龙头单测（任务 7）。
 *
 * 票据模型：后端用 ticketSigner 私钥签 EIP-712 Ticket(to, nonce, deadline)；
 * claim 必须由 ticket.to 本人提交，nonce 严格递增，deadline 含当秒，
 * 同一地址两次领取之间至少间隔 24h。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const { deployGame, RTM } = require('./arena.helpers');

const DAY = 86400n;
const DRIP = RTM(100);

const TICKET_TYPES = {
  Ticket: [
    { name: 'to', type: 'address' },
    { name: 'nonce', type: 'uint256' },
    { name: 'deadline', type: 'uint64' }
  ]
};

function ticket(to, nonce, deadline) {
  return { to, nonce, deadline };
}

describe('Faucet 水龙头', function () {
  let game;
  let faucet;
  let domain;
  let claimer;

  beforeEach(async function () {
    game = await deployGame();
    const Faucet = await ethers.getContractFactory('Faucet');
    faucet = await Faucet.deploy(
      game.owner.address,
      game.rtm.target,
      game.signers[7].address,
      DRIP
    );
    // 测试网由 Arena.mintForTest 预充；Faucet 只负责按票据付出。
    await game.arena.mintForTest(faucet.target, RTM(10000));

    const { chainId } = await ethers.provider.getNetwork();
    domain = {
      name: 'RTM Faucet',
      version: '1',
      chainId,
      verifyingContract: faucet.target
    };
    claimer = game.attackerA;
  });

  async function sign(t) {
    return game.signers[7].signTypedData(domain, TICKET_TYPES, t);
  }

  it('正常领取：事件、Faucet 余额减少、领取者增加、nonce/lastClaim 记账', async function () {
    const now = BigInt(await time.latest());
    const t = ticket(claimer.address, 1n, now + 600n);
    const sig = await sign(t);

    const faucetBefore = await game.rtm.balanceOf(faucet.target);
    const claimerBefore = await game.rtm.balanceOf(claimer.address);

    const tx = await faucet.connect(claimer).claim(t, sig);
    const receipt = await tx.wait();
    const block = await ethers.provider.getBlock(receipt.blockNumber);

    await expect(tx)
      .to.emit(faucet, 'Claimed')
      .withArgs(claimer.address, 1n, DRIP);

    expect(await game.rtm.balanceOf(faucet.target)).to.equal(faucetBefore - DRIP);
    expect(await game.rtm.balanceOf(claimer.address)).to.equal(claimerBefore + DRIP);
    expect(await faucet.nonces(claimer.address)).to.equal(1n);
    expect(await faucet.lastClaim(claimer.address)).to.equal(block.timestamp);
  });

  it('同一票据重放 revert NonceUsed', async function () {
    const now = BigInt(await time.latest());
    const t = ticket(claimer.address, 1n, now + 600n);
    const sig = await sign(t);

    await faucet.connect(claimer).claim(t, sig);
    await expect(faucet.connect(claimer).claim(t, sig))
      .to.be.revertedWithCustomError(faucet, 'NonceUsed');
  });

  it('nonce=0 默认无效 -> NonceUsed；过期票据 -> Expired', async function () {
    const now = BigInt(await time.latest());

    const zeroNonce = ticket(claimer.address, 0n, now + 600n);
    await expect(faucet.connect(claimer).claim(zeroNonce, await sign(zeroNonce)))
      .to.be.revertedWithCustomError(faucet, 'NonceUsed');

    const expired = ticket(claimer.address, 1n, now - 1n);
    await expect(faucet.connect(claimer).claim(expired, await sign(expired)))
      .to.be.revertedWithCustomError(faucet, 'Expired');
  });

  it('24h 冷却：立即二次领取 Cooldown，满 24h 后新 nonce 可领', async function () {
    const now = BigInt(await time.latest());
    const deadline = now + 2n * DAY;

    const first = ticket(claimer.address, 1n, deadline);
    await faucet.connect(claimer).claim(first, await sign(first));

    const second = ticket(claimer.address, 2n, deadline);
    const secondSig = await sign(second);
    await expect(faucet.connect(claimer).claim(second, secondSig))
      .to.be.revertedWithCustomError(faucet, 'Cooldown');

    await time.increase(DAY);
    await expect(faucet.connect(claimer).claim(second, secondSig))
      .to.emit(faucet, 'Claimed')
      .withArgs(claimer.address, 2n, DRIP);
    expect(await faucet.nonces(claimer.address)).to.equal(2n);
  });

  it('错误签名者 -> InvalidSigner', async function () {
    const now = BigInt(await time.latest());
    const t = ticket(claimer.address, 1n, now + 600n);
    // 用非 ticketSigner 的账户签名。
    const sig = await game.outsider.signTypedData(domain, TICKET_TYPES, t);

    await expect(faucet.connect(claimer).claim(t, sig))
      .to.be.revertedWithCustomError(faucet, 'InvalidSigner');
  });

  it('ticket.to 与调用者不一致 -> NotTicketHolder', async function () {
    const now = BigInt(await time.latest());
    const t = ticket(claimer.address, 1n, now + 600n);
    const sig = await sign(t);

    await expect(faucet.connect(game.outsider).claim(t, sig))
      .to.be.revertedWithCustomError(faucet, 'NotTicketHolder');
  });

  it('构造参数校验：零地址与零 drip 拒绝', async function () {
    const Faucet = await ethers.getContractFactory('Faucet');

    await expect(
      Faucet.deploy(game.owner.address, ethers.ZeroAddress, game.signers[7].address, DRIP)
    ).to.be.revertedWithCustomError(Faucet, 'ZeroAddress');

    await expect(
      Faucet.deploy(game.owner.address, game.rtm.target, ethers.ZeroAddress, DRIP)
    ).to.be.revertedWithCustomError(Faucet, 'ZeroAddress');

    await expect(
      Faucet.deploy(game.owner.address, game.rtm.target, game.signers[7].address, 0n)
    ).to.be.revertedWithCustomError(Faucet, 'BadParams');
  });
});
