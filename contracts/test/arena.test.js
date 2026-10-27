// SPDX-License-Identifier: MIT
/**
 * Arena + Treasury 比赛全生命周期单测（任务 4）。
 *
 * 信任模型：W 为平台托管、单场专用的靶钱包；守方只 approve S，
 * createContest 仅 operator 可调，因此守方不能把任意地址注册为靶。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const {
  time,
  impersonateAccount,
  setBalance,
  stopImpersonatingAccount
} = require('@nomicfoundation/hardhat-network-helpers');

const RTM = (n) => ethers.parseEther(String(n));
const HOUR = 3600n;
const DAY = 86400n;
const DURATION = 6n * HOUR;
const STAKE = RTM(100);
const BPS = 1000; // 10%
const PRECISION = 10n ** 18n;

function findEvent(receipt, contract, name) {
  for (const log of receipt.logs) {
    try {
      const parsed = contract.interface.parseLog(log);
      if (parsed && parsed.name === name) return parsed;
    } catch (_) {
      // 其他合约的日志忽略
    }
  }
  throw new Error(`event ${name} not found`);
}

/// 与 Solidity `_applyKeep` 相同的 1e18 定点平方-乘，用于精确断言。
function applyKeep(amount, k) {
  let base = (75n * PRECISION) / 100n;
  let factor = PRECISION;
  while (k > 0n) {
    if ((k & 1n) === 1n) factor = (factor * base) / PRECISION;
    base = (base * base) / PRECISION;
    k >>= 1n;
  }
  return (amount * factor) / PRECISION;
}

async function deployGame({ testnet = true } = {}) {
  const signers = await ethers.getSigners();
  const owner = signers[0];
  const operator = signers[1];
  const defender = signers[2];
  const attackerA = signers[3];
  const attackerB = signers[4];
  const outsider = signers[5];
  const treasuryOwner = signers[6];
  const walletSigner = signers[8];
  const wallet2Signer = signers[9];

  const treasury = await (await ethers.getContractFactory('Treasury')).deploy(
    treasuryOwner.address
  );
  const arena = await (await ethers.getContractFactory('Arena')).deploy(
    owner.address,
    treasury.target,
    testnet
  );
  const rtm = await (await ethers.getContractFactory('RTMToken')).deploy(
    owner.address,
    arena.target
  );
  await arena.initialize(rtm.target);
  await arena.setOperator(operator.address);

  if (testnet) {
    await arena.mintForTest(defender.address, RTM(10000));
    await arena.mintForTest(attackerA.address, RTM(1000));
    await arena.mintForTest(attackerB.address, RTM(1000));
    await arena.mintForTest(outsider.address, RTM(1000));
  }

  return {
    owner,
    operator,
    defender,
    attackerA,
    attackerB,
    outsider,
    treasuryOwner,
    walletSigner,
    wallet2Signer,
    treasury,
    arena,
    rtm
  };
}

async function makeContest(game, opts = {}) {
  const stake = opts.stake ?? STAKE;
  const duration = opts.duration ?? DURATION;
  const stakeBps = opts.stakeBps ?? BPS;
  const defenderSigner = opts.defenderSigner ?? game.defender;
  const wallet = opts.wallet ?? game.walletSigner.address;

  await game.rtm.connect(defenderSigner).approve(game.arena.target, stake);
  const tx = await game.arena
    .connect(game.operator)
    .createContest(defenderSigner.address, wallet, stake, duration, stakeBps);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ContestCreated');
  return { id: ev.args.id, end: ev.args.end, stake, duration, stakeBps, wallet, tx, receipt };
}

async function makeMining(game, opts = {}) {
  const wallet = opts.wallet ?? game.walletSigner.address;
  const rate = opts.rate ?? RTM(2);
  const stakeBps = opts.stakeBps ?? BPS;
  const tx = await game.arena
    .connect(game.operator)
    .createMiningContest(wallet, rate, stakeBps);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ContestCreated');
  return { id: ev.args.id, rate, stakeBps, wallet, tx, receipt };
}

async function joinAs(game, signer, id, approve = ethers.MaxUint256) {
  await game.rtm.connect(signer).approve(game.arena.target, approve);
  return game.arena.connect(signer).join(id);
}

async function createExpectRevert(game, params, error) {
  const { defender, operator, arena, rtm } = game;
  await rtm.connect(defender).approve(arena.target, params.stake ?? STAKE);
  const call = arena
    .connect(operator)
    .createContest(
      params.defender ?? defender.address,
      params.wallet ?? game.walletSigner.address,
      params.stake ?? STAKE,
      params.duration ?? DURATION,
      params.stakeBps ?? BPS
    );
  return expect(call).to.be.revertedWithCustomError(arena, error);
}

describe('Arena + Treasury', function () {
  let game;

  beforeEach(async function () {
    game = await deployGame();
  });

  // ==================================================================
  // 部署 / 初始化 / 权限
  // ==================================================================
  describe('部署与初始化', function () {
    it('构造器拒绝零 Treasury', async function () {
      const Arena = await ethers.getContractFactory('Arena');
      await expect(Arena.deploy(game.owner.address, ethers.ZeroAddress, true))
        .to.be.revertedWithCustomError(game.arena, 'ZeroAddress');
    });

    it('initialize 仅 owner 且只能一次，并校验 RTM 代码与 minter', async function () {
      const { arena, rtm, owner, outsider, treasury, walletSigner } = game;

      await expect(arena.initialize(rtm.target))
        .to.be.revertedWithCustomError(arena, 'AlreadyInitialized');
      await expect(arena.connect(outsider).initialize(rtm.target))
        .to.be.revertedWithCustomError(arena, 'OwnableUnauthorizedAccount');

      const stub = await (await ethers.getContractFactory('ArenaStub')).deploy();
      const wrongRtm = await (await ethers.getContractFactory('RTMToken')).deploy(
        owner.address,
        stub.target
      );
      const arena2 = await (await ethers.getContractFactory('Arena')).deploy(
        owner.address,
        treasury.target,
        true
      );
      await expect(arena2.initialize(wrongRtm.target))
        .to.be.revertedWithCustomError(arena2, 'InvalidRTM');
      await expect(arena2.initialize(walletSigner.address))
        .to.be.revertedWithCustomError(arena2, 'InvalidRTM');

      expect(await arena.rtm()).to.equal(rtm.target);
      expect(await arena.treasury()).to.equal(treasury.target);
    });

    it('setOperator 仅 owner、拒绝零地址并更新 operator', async function () {
      const { arena, owner, operator, outsider } = game;

      await expect(arena.connect(outsider).setOperator(outsider.address))
        .to.be.revertedWithCustomError(arena, 'OwnableUnauthorizedAccount');
      await expect(arena.setOperator(ethers.ZeroAddress))
        .to.be.revertedWithCustomError(arena, 'ZeroAddress');
      await expect(arena.connect(owner).setOperator(outsider.address))
        .to.emit(arena, 'OperatorUpdated')
        .withArgs(outsider.address);
      expect(await arena.operator()).to.equal(outsider.address);
      expect(await arena.operator()).to.not.equal(operator.address);
    });

    it('createContest / createMiningContest / mintForTest 仅对应权限角色', async function () {
      const { arena, rtm, defender, outsider, walletSigner } = game;

      await rtm.connect(defender).approve(arena.target, STAKE);
      await expect(
        arena
          .connect(defender)
          .createContest(defender.address, walletSigner.address, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'NotOperator');
      await expect(
        arena.connect(outsider).createMiningContest(walletSigner.address, RTM(1), BPS)
      ).to.be.revertedWithCustomError(arena, 'NotOperator');
      await expect(arena.connect(outsider).mintForTest(outsider.address, 1))
        .to.be.revertedWithCustomError(arena, 'OwnableUnauthorizedAccount');
    });

    it('testnet=false 时 mintForTest 被门禁，accrue 是唯一注水路径', async function () {
      const mainnet = await deployGame({ testnet: false });
      expect(await mainnet.arena.testnet()).to.equal(false);
      await expect(mainnet.arena.mintForTest(mainnet.defender.address, RTM(1)))
        .to.be.revertedWithCustomError(mainnet.arena, 'TestnetOnly');

      expect(await game.arena.testnet()).to.equal(true);
    });
  });

  // ==================================================================
  // 创建比赛
  // ==================================================================
  describe('createContest', function () {
    it('拒绝 defender / operator / treasury / arena / rtm / 零地址 / 已注册靶作为 W', async function () {
      const { arena, defender, operator, treasury, rtm } = game;
      const wallet = game.walletSigner.address;

      await expect(
        arena
          .connect(operator)
          .createContest(defender.address, defender.address, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createContest(defender.address, operator.address, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createContest(defender.address, treasury.target, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createContest(defender.address, arena.target, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createContest(defender.address, rtm.target, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createContest(defender.address, ethers.ZeroAddress, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'ZeroAddress');

      // 先正常创建，再尝试复用同一 W（仍是活跃靶）。
      await makeContest(game, { wallet });
      await expect(
        arena.connect(operator).createContest(defender.address, wallet, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
    });

    it('正常创建：S 直达 W、W 注册为靶、state=1、事件与 approve 消耗', async function () {
      const { arena, rtm, defender, operator, walletSigner } = game;
      const before = await rtm.balanceOf(defender.address);
      await rtm.connect(defender).approve(arena.target, STAKE);

      const tx = await arena
        .connect(operator)
        .createContest(defender.address, walletSigner.address, STAKE, DURATION, BPS);
      const receipt = await tx.wait();
      const ev = findEvent(receipt, arena, 'ContestCreated');
      const id = ev.args.id;

      expect(ev.args.defender).to.equal(defender.address);
      expect(ev.args.wallet).to.equal(walletSigner.address);
      expect(ev.args.stake).to.equal(STAKE);
      expect(ev.args.isMining).to.equal(false);
      const block = await ethers.provider.getBlock(receipt.blockNumber);
      expect(ev.args.end).to.equal(BigInt(block.timestamp) + DURATION);

      expect(await arena.contestWallet(id)).to.equal(walletSigner.address);
      expect(await arena.contestState(id)).to.equal(1n);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(STAKE);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(true);
      expect(await rtm.targetContest(walletSigner.address)).to.equal(id);
      expect(await rtm.balanceOf(defender.address)).to.equal(before - STAKE);
      expect(await arena.contestList(0)).to.equal(id);
      expect(await arena.contestState(ethers.id('missing'))).to.equal(0n);
    });

    it('duration / stakeBps / stake / defender 参数边界', async function () {
      const { arena, operator, defender, rtm } = game;

      await createExpectRevert(game, { duration: 6n * HOUR - 1n }, 'BadParams');
      await createExpectRevert(game, { duration: 7n * DAY + 1n }, 'BadParams');
      await createExpectRevert(game, { stakeBps: 199 }, 'BadParams');
      await createExpectRevert(game, { stakeBps: 2001 }, 'BadParams');
      await createExpectRevert(game, { stake: 0 }, 'BadParams');
      await createExpectRevert(game, { defender: ethers.ZeroAddress }, 'ZeroAddress');

      // 合法边界：6h / 7d、r=200 / 2000。
      const randomWallet = () => ethers.Wallet.createRandom().address;
      for (const params of [
        { duration: 6n * HOUR, stakeBps: 200 },
        { duration: 7n * DAY, stakeBps: 2000 },
        { duration: DURATION, stakeBps: 200 },
        { duration: DURATION, stakeBps: 2000 }
      ]) {
        await rtm.connect(defender).approve(arena.target, STAKE);
        const wallet = randomWallet();
        const tx = await arena
          .connect(operator)
          .createContest(
            defender.address,
            wallet,
            params.stake ?? STAKE,
            params.duration,
            params.stakeBps
          );
        const ev = findEvent(await tx.wait(), arena, 'ContestCreated');
        expect(ev.args.id).to.not.equal(ethers.ZeroHash);
      }
    });

    it('createMiningContest 钱包校验、参数校验与状态', async function () {
      const { arena, operator, treasury, rtm, walletSigner } = game;

      await expect(
        arena.connect(operator).createMiningContest(ethers.ZeroAddress, RTM(1), BPS)
      ).to.be.revertedWithCustomError(arena, 'ZeroAddress');
      for (const wallet of [treasury.target, arena.target, rtm.target, operator.address]) {
        await expect(arena.connect(operator).createMiningContest(wallet, RTM(1), BPS))
          .to.be.revertedWithCustomError(arena, 'InvalidWallet');
      }
      await expect(
        arena.connect(operator).createMiningContest(walletSigner.address, 0, BPS)
      ).to.be.revertedWithCustomError(arena, 'BadParams');
      await expect(
        arena.connect(operator).createMiningContest(walletSigner.address, RTM(1), 199)
      ).to.be.revertedWithCustomError(arena, 'BadParams');
      await expect(
        arena.connect(operator).createMiningContest(walletSigner.address, RTM(1), 2001)
      ).to.be.revertedWithCustomError(arena, 'BadParams');

      const tx = await arena
        .connect(operator)
        .createMiningContest(walletSigner.address, RTM(2), BPS);
      const ev = findEvent(await tx.wait(), arena, 'ContestCreated');
      const id = ev.args.id;
      expect(ev.args.defender).to.equal(treasury.target);
      expect(ev.args.wallet).to.equal(walletSigner.address);
      expect(ev.args.stake).to.equal(0n);
      expect(ev.args.end).to.equal(2n ** 64n - 1n);
      expect(ev.args.isMining).to.equal(true);
      expect(await arena.contestWallet(id)).to.equal(walletSigner.address);
      expect(await arena.contestState(id)).to.equal(1n);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(true);
    });

    it('W 不得复用：已注册靶在 createContest 与 createMiningContest 都被拒绝', async function () {
      const { arena, operator, defender, walletSigner } = game;
      const { id } = await makeContest(game, { wallet: walletSigner.address });
      expect(await arena.contestState(id)).to.equal(1n);

      await expect(
        arena
          .connect(operator)
          .createContest(defender.address, walletSigner.address, STAKE, DURATION, BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
      await expect(
        arena.connect(operator).createMiningContest(walletSigner.address, RTM(1), BPS)
      ).to.be.revertedWithCustomError(arena, 'InvalidWallet');
    });
  });

  // ==================================================================
  // 加入 / 付费消息 / pause
  // ==================================================================
  describe('join / attack / markDelivered', function () {
    it('join：质押进入 Arena、base 快照正确、重复加入拒绝', async function () {
      const { arena, rtm, attackerA } = game;
      const { id } = await makeContest(game);
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const before = await rtm.balanceOf(attackerA.address);

      await expect(joinAs(game, attackerA, id))
        .to.emit(arena, 'Joined')
        .withArgs(id, attackerA.address, s);

      const info = await arena.attackers(id, attackerA.address);
      expect(info.stake).to.equal(s);
      expect(info.base).to.equal(STAKE);
      expect(info.joined).to.equal(true);
      expect(await arena.isRegisteredAttacker(id, attackerA.address)).to.equal(true);
      expect(await arena.isRegisteredAttacker(id, game.attackerB.address)).to.equal(false);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(before - s);
      expect(await rtm.balanceOf(arena.target)).to.equal(s);

      await expect(arena.connect(attackerA).join(id))
        .to.be.revertedWithCustomError(arena, 'AlreadyJoined');
    });

    it('join：暂停中、已结束、mining 零余额均拒绝', async function () {
      const { arena, operator, attackerA, attackerB } = game;
      const { id, end } = await makeContest(game);

      await arena.connect(operator).pause(id);
      await expect(joinAs(game, attackerA, id))
        .to.be.revertedWithCustomError(arena, 'PausedNow')
        .withArgs(id);
      await arena.connect(operator).unpause(id);
      await joinAs(game, attackerA, id);

      await time.increaseTo(end);
      await arena.connect(game.outsider).expire(id);
      await expect(joinAs(game, attackerB, id))
        .to.be.revertedWithCustomError(arena, 'NotLive')
        .withArgs(id);

      await expect(arena.connect(attackerB).join(ethers.id('unknown')))
        .to.be.revertedWithCustomError(arena, 'NotLive');

      const mining = await makeMining(game, { wallet: game.wallet2Signer.address });
      await expect(joinAs(game, attackerB, mining.id))
        .to.be.revertedWithCustomError(arena, 'BaseZero');
    });

    it('攻击方上限 50：第 51 个 join 被拒绝', async function () {
      const { arena, rtm, owner } = game;
      expect(await arena.MAX_ATTACKERS()).to.equal(50n);
      const { id } = await makeContest(game, { stake: RTM(1), stakeBps: 200 });
      const s = (RTM(1) * 200n) / 10000n;
      const wallets = [];

      for (let i = 0; i < 50; i++) {
        const w = new ethers.Wallet(ethers.hexlify(ethers.randomBytes(32)), ethers.provider);
        wallets.push(w);
        await owner.sendTransaction({ to: w.address, value: ethers.parseEther('0.02') });
        await arena.mintForTest(w.address, s);
        await rtm.connect(w).approve(arena.target, s);
        await arena.connect(w).join(id);
      }

      expect(await arena.contestAttackers(id, 49)).to.equal(wallets[49].address);

      const w51 = new ethers.Wallet(ethers.hexlify(ethers.randomBytes(32)), ethers.provider);
      await owner.sendTransaction({ to: w51.address, value: ethers.parseEther('0.02') });
      await arena.mintForTest(w51.address, s);
      await rtm.connect(w51).approve(arena.target, s);
      await expect(arena.connect(w51).join(id))
        .to.be.revertedWithCustomError(arena, 'TooManyAttackers');
    });

    it('attack：费用到 Treasury、seq 递增、重复/零 hash/未加入拒绝', async function () {
      const { arena, rtm, treasury, attackerA, attackerB } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      const fee = (STAKE * 50n) / 10000n;
      const h1 = ethers.id('msg-1');
      const h2 = ethers.id('msg-2');

      const before = await rtm.balanceOf(treasury.target);
      await expect(arena.connect(attackerA).attack(id, h1))
        .to.emit(arena, 'AttackPaid')
        .withArgs(id, attackerA.address, h1, 1n, fee);
      expect(await rtm.balanceOf(treasury.target)).to.equal(before + fee);
      expect(await arena.paidFee(id, attackerA.address, h1)).to.equal(fee);

      await expect(arena.connect(attackerA).attack(id, h2))
        .to.emit(arena, 'AttackPaid')
        .withArgs(id, attackerA.address, h2, 2n, fee);
      expect((await arena.attackers(id, attackerA.address)).attackCount).to.equal(2n);

      await expect(arena.connect(attackerA).attack(id, h1))
        .to.be.revertedWithCustomError(arena, 'DuplicateMessage')
        .withArgs(h1);
      await expect(arena.connect(attackerA).attack(id, ethers.ZeroHash))
        .to.be.revertedWithCustomError(arena, 'BadParams');
      await expect(arena.connect(attackerB).attack(id, ethers.id('msg-3')))
        .to.be.revertedWithCustomError(arena, 'NotJoined');
    });

    it('attack：暂停中/结束后拒绝；fee 为 0 时拒绝', async function () {
      const { arena, operator, attackerA, outsider } = game;
      const { id, end } = await makeContest(game);
      await joinAs(game, attackerA, id);

      await arena.connect(operator).pause(id);
      await expect(arena.connect(attackerA).attack(id, ethers.id('paused')))
        .to.be.revertedWithCustomError(arena, 'PausedNow')
        .withArgs(id);
      await arena.connect(operator).unpause(id);

      await time.increaseTo(end);
      await arena.connect(outsider).expire(id);
      await expect(arena.connect(attackerA).attack(id, ethers.id('ended')))
        .to.be.revertedWithCustomError(arena, 'NotLive')
        .withArgs(id);

      // base=100 wei, r=200 => s=2 wei；fee=100*50/10000=0。
      const small = await makeContest(game, {
        stake: 100n,
        stakeBps: 200,
        wallet: game.wallet2Signer.address
      });
      await joinAs(game, attackerA, small.id, 10n);
      await expect(arena.connect(attackerA).attack(small.id, ethers.id('fee-zero')))
        .to.be.revertedWithCustomError(arena, 'FeeZero');
    });

    it('markDelivered：仅 operator、未加入/超出 attackCount 拒绝', async function () {
      const { arena, operator, attackerA, attackerB } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);

      await expect(arena.connect(operator).markDelivered(id, attackerB.address))
        .to.be.revertedWithCustomError(arena, 'NotJoined');
      await expect(arena.connect(operator).markDelivered(id, attackerA.address))
        .to.be.revertedWithCustomError(arena, 'NothingToMark');
      await expect(arena.connect(attackerA).markDelivered(id, attackerA.address))
        .to.be.revertedWithCustomError(arena, 'NotOperator');

      await arena.connect(attackerA).attack(id, ethers.id('d1'));
      await expect(arena.connect(operator).markDelivered(id, attackerA.address))
        .to.emit(arena, 'MarkDelivered')
        .withArgs(id, attackerA.address, 1n);
      expect((await arena.attackers(id, attackerA.address)).delivered).to.equal(1n);
      await expect(arena.connect(operator).markDelivered(id, attackerA.address))
        .to.be.revertedWithCustomError(arena, 'NothingToMark');

      await arena.connect(attackerA).attack(id, ethers.id('d2'));
      await expect(arena.connect(operator).markDelivered(id, attackerA.address))
        .to.emit(arena, 'MarkDelivered')
        .withArgs(id, attackerA.address, 2n);
      expect((await arena.attackers(id, attackerA.address)).delivered).to.equal(2n);
    });

    it('pause/unpause：仅 operator、重复 pause / 未暂停 unpause 拒绝', async function () {
      const { arena, operator, outsider } = game;
      const { id } = await makeContest(game);

      await expect(arena.connect(outsider).pause(id))
        .to.be.revertedWithCustomError(arena, 'NotOperator');
      await expect(arena.connect(operator).pause(id)).to.emit(arena, 'Paused').withArgs(id);
      await expect(arena.connect(operator).pause(id))
        .to.be.revertedWithCustomError(arena, 'PausedNow');
      await expect(arena.connect(operator).unpause(id))
        .to.emit(arena, 'Unpaused')
        .withArgs(id);
      await expect(arena.connect(operator).unpause(id))
        .to.be.revertedWithCustomError(arena, 'NotPaused');
      await expect(arena.connect(outsider).unpause(id))
        .to.be.revertedWithCustomError(arena, 'NotOperator');
    });
  });

  // ==================================================================
  // 惰性罚款
  // ==================================================================
  describe('惰性罚款', function () {
    it('2h 后 remaining=0.75s；collect 到 defender、重复 collect 只拉差额', async function () {
      const { arena, rtm, defender, outsider, attackerA } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      const s = (STAKE * BigInt(BPS)) / 10000n;

      expect(await arena.remainingStake(id, attackerA.address)).to.equal(s);
      expect(await arena.accruedPenalties(id, attackerA.address)).to.equal(0n);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      await time.increase(2n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(applyKeep(s, 1n));
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(7.5));
      expect(await arena.accruedPenalties(id, attackerA.address)).to.equal(RTM(2.5));
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(RTM(2.5));

      await expect(arena.connect(outsider).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NotDefender');
      await expect(arena.connect(defender).collectPenalties(ethers.ZeroHash))
        .to.be.revertedWithCustomError(arena, 'ContestUnknown');

      const before = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, RTM(2.5));
      expect(await rtm.balanceOf(defender.address)).to.equal(before + RTM(2.5));
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      // 进入第 3 个 epoch：accrued=4.375，已拉 2.5，差额 1.875。
      await time.increase(2n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(applyKeep(s, 2n));
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(5.625));
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(RTM(1.875));
      const before2 = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, RTM(1.875));
      expect(await rtm.balanceOf(defender.address)).to.equal(before2 + RTM(1.875));
    });

    it('pause 冻结罚款时钟，unpause 后继续累计', async function () {
      const { arena, operator, attackerA, attackerB } = game;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);
      const s = (STAKE * BigInt(BPS)) / 10000n;

      await time.increase(2n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(7.5));

      await arena.connect(operator).pause(id);
      await time.increase(2n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(7.5));
      expect(await arena.accruedPenalties(id, attackerA.address)).to.equal(RTM(2.5));
      await expect(joinAs(game, attackerB, id)).to.be.revertedWithCustomError(
        arena,
        'PausedNow'
      );

      await arena.connect(operator).unpause(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(7.5));
      await time.increase(2n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(5.625));
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(applyKeep(s, 2n));
    });

    it('暂停跨过 end：只扣除与比赛窗口重叠的暂停，不抹掉既有罚款', async function () {
      const { arena, rtm, defender, operator, outsider, attackerA } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      const s = (STAKE * BigInt(BPS)) / 10000n;

      await time.increase(4n * HOUR);
      await arena.connect(operator).pause(id);
      await time.increase(4n * HOUR); // now 已超过 end，暂停仍未解除
      await arena.connect(outsider).expire(id);

      // 有效时长 ≈ 4h，理论上 k=2。
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(applyKeep(s, 2n));
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(RTM(5.625));
      const due = await arena.penaltyDue(id, attackerA.address);
      expect(due).to.equal(RTM(4.375));

      const before = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, due);
      expect(await rtm.balanceOf(defender.address)).to.equal(before + due);
    });

    it('endedAt 冻结后时间旅行不再改变罚款，未拉取罚款仍可收', async function () {
      const { arena, rtm, defender, outsider, attackerA } = game;
      const { id, end } = await makeContest(game);
      await joinAs(game, attackerA, id);
      await time.increaseTo(end);

      const remAtEnd = await arena.remainingStake(id, attackerA.address);
      const dueAtEnd = await arena.penaltyDue(id, attackerA.address);
      expect(remAtEnd).to.be.greaterThan(0n);
      expect(dueAtEnd).to.be.greaterThan(0n);

      await arena.connect(outsider).expire(id);
      await time.increase(5n * DAY);

      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remAtEnd);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(dueAtEnd);

      const before = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, dueAtEnd);
      expect(await rtm.balanceOf(defender.address)).to.equal(before + dueAtEnd);
    });
  });

  // ==================================================================
  // 结算：攻破 / 到期 / 弃权
  // ==================================================================
  describe('结算', function () {
    it('攻破端到端：W 全额归 A，B 提剩余质押，state=2', async function () {
      const { arena, rtm, defender, attackerA, attackerB, walletSigner } = game;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);
      await joinAs(game, attackerB, id);
      const s = (STAKE * BigInt(BPS)) / 10000n;

      expect(await rtm.balanceOf(walletSigner.address)).to.equal(STAKE);
      const aBefore = await rtm.balanceOf(attackerA.address);
      const bBefore = await rtm.balanceOf(attackerB.address);

      const tx = await rtm.connect(walletSigner).transfer(attackerA.address, RTM(10));
      await expect(tx).to.emit(rtm, 'Breach').withArgs(id, attackerA.address, RTM(10));
      await expect(tx)
        .to.emit(rtm, 'TargetUnregistered')
        .withArgs(walletSigner.address, id);
      await expect(tx)
        .to.emit(arena, 'ContestSettled')
        .withArgs(id, attackerA.address, STAKE - RTM(10));

      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + STAKE);
      expect(await arena.contestState(id)).to.equal(2n);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(false);
      expect(await rtm.isControlledWallet(walletSigner.address)).to.equal(true);

      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, s);
      await expect(arena.connect(attackerB).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerB.address, s);

      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + STAKE + s);
      expect(await rtm.balanceOf(attackerB.address)).to.equal(bBefore + s);
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      expect(await rtm.balanceOf(defender.address)).to.equal(RTM(9900));
      await expect(arena.connect(game.outsider).onBreach(id, attackerA.address))
        .to.be.revertedWithCustomError(arena, 'OnlyToken');
    });

    it('W 全额转给攻方时 rest=0，Arena 跳过零额 controllerTransfer', async function () {
      const { arena, rtm, attackerA, walletSigner } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      const before = await rtm.balanceOf(attackerA.address);

      const tx = await rtm.connect(walletSigner).transfer(attackerA.address, STAKE);
      await expect(tx).to.emit(rtm, 'Breach').withArgs(id, attackerA.address, STAKE);
      await expect(tx).to.emit(arena, 'ContestSettled').withArgs(id, attackerA.address, 0n);

      expect(await rtm.balanceOf(attackerA.address)).to.equal(before + STAKE);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      expect(await arena.contestState(id)).to.equal(2n);

      await arena.connect(attackerA).withdrawStake(id);
    });

    it('到期未破：任何人 expire，W 归 defender，攻方提剩余，未拉取罚款仍可收', async function () {
      const { arena, rtm, defender, outsider, attackerA, attackerB, walletSigner } = game;
      const { id, end } = await makeContest(game);
      await joinAs(game, attackerA, id);
      await joinAs(game, attackerB, id);
      await time.increaseTo(end);

      const remA = await arena.remainingStake(id, attackerA.address);
      const remB = await arena.remainingStake(id, attackerB.address);
      const dueA = await arena.penaltyDue(id, attackerA.address);
      const dueB = await arena.penaltyDue(id, attackerB.address);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(STAKE);

      const defBefore = await rtm.balanceOf(defender.address);
      await expect(arena.connect(outsider).expire(id))
        .to.emit(arena, 'Expired')
        .withArgs(id, defender.address, STAKE);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore + STAKE);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      expect(await arena.contestState(id)).to.equal(2n);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(false);
      await expect(arena.connect(outsider).expire(id))
        .to.be.revertedWithCustomError(arena, 'NotLive');

      const aBefore = await rtm.balanceOf(attackerA.address);
      const bBefore = await rtm.balanceOf(attackerB.address);
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, remA);
      await expect(arena.connect(attackerB).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerB.address, remB);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + remA);
      expect(await rtm.balanceOf(attackerB.address)).to.equal(bBefore + remB);

      // 未拉取罚款留在 Arena，defender 事后仍可收。
      const defBefore2 = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, dueA + dueB);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore2 + dueA + dueB);
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);
    });

    it('到期后诱导 W 转账：整笔 revert ContestExpired，靶保持注册', async function () {
      const { arena, rtm, outsider, attackerA, walletSigner } = game;
      const { id, end } = await makeContest(game);
      await joinAs(game, attackerA, id);
      await time.increaseTo(end);

      const aBefore = await rtm.balanceOf(attackerA.address);
      await expect(rtm.connect(walletSigner).transfer(attackerA.address, RTM(1)))
        .to.be.revertedWithCustomError(arena, 'ContestExpired')
        .withArgs(id);

      expect(await rtm.isTarget(walletSigner.address)).to.equal(true);
      expect(await rtm.targetContest(walletSigner.address)).to.equal(id);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(STAKE);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore);
      expect(await arena.contestState(id)).to.equal(1n);

      await arena.connect(outsider).expire(id);
      expect(await arena.contestState(id)).to.equal(2n);
    });

    it('弃权：按 delivered 2:1 分 S、零 share 跳过、未拉取罚款豁免', async function () {
      const { arena, rtm, defender, operator, attackerA, attackerB, outsider } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      await joinAs(game, attackerB, id);
      await joinAs(game, outsider, id);

      await arena.connect(attackerA).attack(id, ethers.id('a1'));
      await arena.connect(attackerA).attack(id, ethers.id('a2'));
      await arena.connect(operator).markDelivered(id, attackerA.address);
      await arena.connect(operator).markDelivered(id, attackerA.address);
      await arena.connect(attackerB).attack(id, ethers.id('b1'));
      await arena.connect(operator).markDelivered(id, attackerB.address);

      // 先让罚款发生并拉走一部分，验证弃权后只退 stake - penaltyTaken。
      await time.increase(2n * HOUR);
      const dueA = await arena.penaltyDue(id, attackerA.address);
      const dueB = await arena.penaltyDue(id, attackerB.address);
      const dueC = await arena.penaltyDue(id, outsider.address);
      expect(dueA).to.equal(RTM(2.5));
      expect(dueB).to.equal(RTM(2.5));
      expect(dueC).to.equal(RTM(2.5));
      const defBeforeCollect = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, dueA + dueB + dueC);
      expect(await rtm.balanceOf(defender.address)).to.equal(
        defBeforeCollect + dueA + dueB + dueC
      );

      const shareA = (STAKE * 2n) / 3n;
      const shareB = STAKE - shareA;
      const aBefore = await rtm.balanceOf(attackerA.address);
      const bBefore = await rtm.balanceOf(attackerB.address);
      const cBefore = await rtm.balanceOf(outsider.address);
      const defBefore = await rtm.balanceOf(defender.address);

      await expect(arena.connect(operator).reportDefenderFault(id))
        .to.emit(arena, 'DefenderFault')
        .withArgs(id);

      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + shareA);
      expect(await rtm.balanceOf(attackerB.address)).to.equal(bBefore + shareB);
      expect(await rtm.balanceOf(outsider.address)).to.equal(cBefore); // delivered=0，零 share 跳过
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore);
      expect(await arena.contestState(id)).to.equal(2n);

      const infoA = await arena.attackers(id, attackerA.address);
      const infoB = await arena.attackers(id, attackerB.address);
      const infoC = await arena.attackers(id, outsider.address);
      expect(infoA.delivered).to.equal(2n);
      expect(infoB.delivered).to.equal(1n);
      expect(infoC.delivered).to.equal(0n);
      expect(infoA.waived).to.equal(true);
      expect(infoB.waived).to.equal(true);
      expect(infoC.waived).to.equal(true);
      expect(infoA.penaltyTaken).to.equal(RTM(2.5));
      expect(infoB.penaltyTaken).to.equal(RTM(2.5));
      expect(infoC.penaltyTaken).to.equal(RTM(2.5));
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);

      await time.increase(4n * HOUR);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      // 已拉走的 2.5 不退；未拉取罚款豁免。
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const stakeLeft = s - RTM(2.5);
      expect(stakeLeft).to.equal(RTM(7.5));
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, stakeLeft);
      await expect(arena.connect(attackerB).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerB.address, stakeLeft);
      await expect(arena.connect(outsider).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, outsider.address, stakeLeft);
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);
    });

    it('弃权无 delivered：W 余额全部退 defender', async function () {
      const { arena, rtm, defender, operator, attackerA } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);

      const defBefore = await rtm.balanceOf(defender.address);
      await arena.connect(operator).reportDefenderFault(id);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore + STAKE);
      expect(await rtm.balanceOf(game.walletSigner.address)).to.equal(0n);
      expect(await arena.contestState(id)).to.equal(2n);

      const s = (STAKE * BigInt(BPS)) / 10000n;
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, s);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');
    });

    it('弃权 mining：不分 S、不扫 W，攻方自行提质押', async function () {
      const { arena, rtm, operator, attackerA, walletSigner } = game;
      const { id } = await makeMining(game, { rate: RTM(2) });
      await time.increase(2n * HOUR);
      await arena.accrue(id);
      const wBefore = await rtm.balanceOf(walletSigner.address);
      expect(wBefore).to.equal(RTM(2));

      await joinAs(game, attackerA, id);
      const s = (RTM(2) * BigInt(BPS)) / 10000n;
      const aBefore = await rtm.balanceOf(attackerA.address);

      await arena.connect(operator).reportDefenderFault(id);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(wBefore);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore);
      expect(await arena.contestState(id)).to.equal(2n);

      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, s);
    });
  });

  // ==================================================================
  // 挖矿
  // ==================================================================
  describe('挖矿赛', function () {
    it('accrue 2h 铸 rate、重复 accrue 幂等、join base=W 余额、fee 用快照 base', async function () {
      const { arena, rtm, treasury, outsider, attackerA, walletSigner } = game;
      const { id, rate } = await makeMining(game, { rate: RTM(2) });

      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      await expect(arena.accrue(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      await time.increase(2n * HOUR);
      await expect(arena.connect(outsider).accrue(id))
        .to.emit(arena, 'MiningAccrued')
        .withArgs(id, walletSigner.address, rate);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(rate);
      await expect(arena.accrue(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      await joinAs(game, attackerA, id);
      const info = await arena.attackers(id, attackerA.address);
      expect(info.base).to.equal(rate);
      expect(info.stake).to.equal((rate * BigInt(BPS)) / 10000n);

      const fee = (rate * 50n) / 10000n;
      const feeBefore = await rtm.balanceOf(treasury.target);
      await expect(arena.connect(attackerA).attack(id, ethers.id('m1')))
        .to.emit(arena, 'AttackPaid')
        .withArgs(id, attackerA.address, ethers.id('m1'), 1n, fee);
      expect(await rtm.balanceOf(treasury.target)).to.equal(feeBefore + fee);

      // 再过一个 epoch：W 余额翻倍，但攻方 feeBase 保持 join 时快照。
      await time.increase(2n * HOUR);
      await expect(arena.accrue(id))
        .to.emit(arena, 'MiningAccrued')
        .withArgs(id, walletSigner.address, rate);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(rate * 2n);
      await expect(arena.connect(attackerA).attack(id, ethers.id('m2')))
        .to.emit(arena, 'AttackPaid')
        .withArgs(id, attackerA.address, ethers.id('m2'), 2n, fee);

      // mining 罚款任何人可拉，进入 Treasury。
      const due = await arena.penaltyDue(id, attackerA.address);
      expect(due).to.be.greaterThan(0n);
      const tBefore = await rtm.balanceOf(treasury.target);
      await expect(arena.connect(outsider).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, treasury.target, due);
      expect(await rtm.balanceOf(treasury.target)).to.equal(tBefore + due);
    });

    it('pause 冻结 accrue，unpause 后继续；breach 后结束且 W 清零', async function () {
      const { arena, rtm, operator, attackerA, walletSigner } = game;
      const { id, rate } = await makeMining(game, { rate: RTM(2) });

      await time.increase(2n * HOUR);
      await arena.accrue(id);
      await joinAs(game, attackerA, id);

      const remBefore = await arena.remainingStake(id, attackerA.address);
      const wBefore = await rtm.balanceOf(walletSigner.address);
      expect(wBefore).to.equal(rate);

      await arena.connect(operator).pause(id);
      await time.increase(2n * HOUR);
      await expect(arena.accrue(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remBefore);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(wBefore);

      await arena.connect(operator).unpause(id);
      await time.increase(2n * HOUR);
      await expect(arena.accrue(id))
        .to.emit(arena, 'MiningAccrued')
        .withArgs(id, walletSigner.address, rate);

      const wAtBreach = await rtm.balanceOf(walletSigner.address);
      expect(wAtBreach).to.equal(rate * 2n);
      const aBefore = await rtm.balanceOf(attackerA.address);
      const tx = await rtm.connect(walletSigner).transfer(attackerA.address, RTM(1));
      await expect(tx)
        .to.emit(arena, 'ContestSettled')
        .withArgs(id, attackerA.address, wAtBreach - RTM(1));

      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + wAtBreach);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      expect(await arena.contestState(id)).to.equal(2n);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(false);
      await expect(arena.accrue(id)).to.be.revertedWithCustomError(arena, 'NotLive');

      const rem = await arena.remainingStake(id, attackerA.address);
      expect(rem).to.be.greaterThan(0n);
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.emit(arena, 'StakeWithdrawn')
        .withArgs(id, attackerA.address, rem);
    });
  });

  // ==================================================================
  // refund / Treasury / 零额边界
  // ==================================================================
  describe('refund、Treasury 与零额边界', function () {
    it('refundUnserved：Treasury 需 approveSpender，按 paidFee 精确退且幂等', async function () {
      const { arena, rtm, treasury, treasuryOwner, operator, attackerA } = game;
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);
      const h1 = ethers.id('refund-me');
      await arena.connect(attackerA).attack(id, h1);
      const fee = (STAKE * 50n) / 10000n;

      await expect(arena.connect(operator).refundUnserved(id, attackerA.address, h1))
        .to.be.reverted; // Treasury 尚未授权 Arena

      await expect(treasury.connect(treasuryOwner).approveSpender(rtm.target, arena.target, fee))
        .to.emit(treasury, 'SpenderApproved')
        .withArgs(rtm.target, arena.target, fee);
      expect(await rtm.allowance(treasury.target, arena.target)).to.equal(fee);

      const aBefore = await rtm.balanceOf(attackerA.address);
      await expect(arena.connect(operator).refundUnserved(id, attackerA.address, h1))
        .to.emit(arena, 'RefundUnserved')
        .withArgs(id, attackerA.address, h1, fee);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(aBefore + fee);
      expect(await arena.paidFee(id, attackerA.address, h1)).to.equal(0n);
      expect(await rtm.allowance(treasury.target, arena.target)).to.equal(0n);

      await expect(arena.connect(operator).refundUnserved(id, attackerA.address, h1))
        .to.be.revertedWithCustomError(arena, 'NothingToRefund');
      await expect(arena.connect(attackerA).refundUnserved(id, attackerA.address, h1))
        .to.be.revertedWithCustomError(arena, 'NotOperator');
    });

    it('Treasury：withdraw / approveSpender 仅 owner，forceApprove 可覆盖额度', async function () {
      const { arena, rtm, treasury, treasuryOwner, outsider } = game;
      await arena.mintForTest(treasury.target, RTM(50));

      await expect(treasury.connect(outsider).withdraw(rtm.target, outsider.address, RTM(1)))
        .to.be.revertedWithCustomError(treasury, 'OwnableUnauthorizedAccount');
      await expect(treasury.connect(outsider).approveSpender(rtm.target, outsider.address, 1))
        .to.be.revertedWithCustomError(treasury, 'OwnableUnauthorizedAccount');

      const before = await rtm.balanceOf(outsider.address);
      await expect(
        treasury.connect(treasuryOwner).withdraw(rtm.target, outsider.address, RTM(10))
      )
        .to.emit(treasury, 'Withdrawn')
        .withArgs(rtm.target, outsider.address, RTM(10));
      expect(await rtm.balanceOf(outsider.address)).to.equal(before + RTM(10));

      await treasury.connect(treasuryOwner).approveSpender(rtm.target, outsider.address, 5);
      expect(await rtm.allowance(treasury.target, outsider.address)).to.equal(5n);
      await treasury.connect(treasuryOwner).approveSpender(rtm.target, outsider.address, 7);
      expect(await rtm.allowance(treasury.target, outsider.address)).to.equal(7n);
    });

    it('expire 零余额仍正常结束，且跳过零额 controllerTransfer', async function () {
      const { arena, rtm, defender, outsider, walletSigner } = game;
      const { id, end } = await makeContest(game);
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(STAKE);

      // 模拟 Arena 以 minter 身份提前清空 W（控制器划转），比赛仍为 Live。
      await impersonateAccount(arena.target);
      await setBalance(arena.target, ethers.parseEther('1'));
      try {
        const arenaSigner = await ethers.getSigner(arena.target);
        await rtm
          .connect(arenaSigner)
          .controllerTransfer(walletSigner.address, outsider.address, STAKE);
      } finally {
        await stopImpersonatingAccount(arena.target);
      }
      expect(await rtm.balanceOf(walletSigner.address)).to.equal(0n);
      expect(await rtm.isTarget(walletSigner.address)).to.equal(false);
      expect(await arena.contestState(id)).to.equal(1n);

      const defBefore = await rtm.balanceOf(defender.address);
      await time.increaseTo(end);
      await expect(arena.connect(outsider).expire(id))
        .to.emit(arena, 'Expired')
        .withArgs(id, defender.address, 0n);
      expect(await arena.contestState(id)).to.equal(2n);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore);
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);
    });
  });
});
