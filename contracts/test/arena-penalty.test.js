// SPDX-License-Identifier: MIT
/**
 * 任务 5：Arena 罚款曲线与 pause 时钟专项测试。
 *
 * 参考模型独立于 Solidity 的 `_applyKeep` 定点平方-乘：
 *   expected(k) = s * 75^k / 100^k   （BigInt 精确下取整）
 * 合约使用 1e18 定点，允许 ≤100 wei 误差（k=12、s=10/100 实测远小于此）。
 *
 * pause 语义按当前实现：攻击/加入在暂停中拒绝，markDelivered 未受 pause 门禁，
 * 本文件只记录现状，不修改合约逻辑。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const {
  RTM,
  HOUR,
  DAY,
  EPOCH,
  STAKE,
  BPS,
  deployGame,
  makeContest,
  makeMining,
  joinAs,
  joinMiningAs,
  attack,
  msgHash
} = require('./arena.helpers');

const TOL = 100n;

/** 独立参考：s*(3/4)^k 的精确整数结果，不复用合约的定点算法。 */
function expectedRemaining(stake, k) {
  return (stake * 75n ** k) / 100n ** k;
}

function expectClose(actual, expected, label = '') {
  const diff = actual >= expected ? actual - expected : expected - actual;
  expect(diff, `${label}: actual=${actual} expected=${expected} diff=${diff}`).to.be
    .lessThanOrEqual(TOL);
}

/** 断言 remainingStake 逼近独立参考，且 accrued + remaining 精确等于 stake。 */
async function assertRemaining(arena, id, who, stake, k, label = '') {
  const actual = await arena.remainingStake(id, who);
  expectClose(actual, expectedRemaining(stake, k), `${label} k=${k}`);
  expect(await arena.accruedPenalties(id, who)).to.equal(stake - actual);
  return actual;
}

describe('Arena 罚款曲线与 pause 时钟', function () {
  let game;

  beforeEach(async function () {
    game = await deployGame();
  });

  // ==================================================================
  // 1. 曲线：独立 BigInt 参考
  // ==================================================================
  describe('罚款曲线', function () {
    for (const sEth of [10n, 100n]) {
      it(`remainingStake ≈ s*(3/4)^k，k=0/1/3/5/12（s=${sEth} RTM）`, async function () {
        const s = RTM(sEth);
        const stake = (s * 10000n) / BigInt(BPS);
        const wallet = sEth === 10n ? game.w : game.w2;
        const { id } = await makeContest(game, {
          stake,
          stakeBps: BPS,
          duration: 2n * DAY,
          wallet
        });
        const attacker = game.attackerA;
        await joinAs(game, attacker, id);

        const info = await game.arena.attackers(id, attacker.address);
        expect(info.stake).to.equal(s);

        let prev = await assertRemaining(game.arena, id, attacker.address, s, 0n, 'k=0');
        expect(prev).to.equal(s);

        await time.increase(EPOCH);
        let rem = await assertRemaining(game.arena, id, attacker.address, s, 1n, 'k=1');
        expect(rem).to.be.lessThanOrEqual(prev);
        prev = rem;

        await time.increase(2n * EPOCH); // 共 3 epoch
        rem = await assertRemaining(game.arena, id, attacker.address, s, 3n, 'k=3');
        expect(rem).to.be.lessThanOrEqual(prev);
        prev = rem;

        await time.increase(2n * EPOCH); // 共 5 epoch
        rem = await assertRemaining(game.arena, id, attacker.address, s, 5n, 'k=5');
        expect(rem).to.be.lessThanOrEqual(prev);
        prev = rem;

        await time.increase(7n * EPOCH); // 共 12 epoch
        rem = await assertRemaining(game.arena, id, attacker.address, s, 12n, 'k=12');
        expect(rem).to.be.lessThanOrEqual(prev);
        expect(await game.arena.accruedPenalties(id, attacker.address)).to.equal(s - rem);
      });
    }
  });

  // ==================================================================
  // 2. collect 差分（仅普通赛；挖矿赛无罚款/无剩余质押提款）
  // ==================================================================
  describe('collect 差分', function () {
    it('2h 收 25%、重复 collect 拒绝、4h 只收新增差额、总额匹配参考', async function () {
      const { arena, rtm, defender, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n; // 10 RTM
      const { id } = await makeContest(game);
      await joinAs(game, attackerA, id);

      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      await time.increase(EPOCH);
      const accrued1 = await arena.accruedPenalties(id, attackerA.address);
      const ref1 = s - expectedRemaining(s, 1n);
      expectClose(accrued1, ref1, 'accrued@2h');
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(accrued1);

      const defBefore1 = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, accrued1);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore1 + accrued1);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NothingToWithdraw');

      await time.increase(EPOCH); // 共 4h => k=2
      const accrued2 = await arena.accruedPenalties(id, attackerA.address);
      const due2 = await arena.penaltyDue(id, attackerA.address);
      const ref2 = s - expectedRemaining(s, 2n);
      expectClose(accrued2, ref2, 'accrued@4h');
      expect(due2).to.equal(accrued2 - accrued1);
      expect(due2).to.equal(ref2 - ref1); // 25% of 期初 remaining (7.5 RTM)

      const defBefore2 = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, due2);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore2 + due2);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);

      const totalCollected = accrued1 + due2;
      expect(totalCollected).to.equal(accrued2);
      expectClose(totalCollected, ref2, 'total collected');
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(s - accrued2);
    });

  });

  // ==================================================================
  // 3. pause 冻结
  // ==================================================================
  describe('pause 冻结', function () {
    it('2h 前 pause 6h：remaining 不变，unpause 后再 2h 只增加 1 个 epoch', async function () {
      const { arena, operator, attackerA, attackerB } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);

      await time.increase(1n * HOUR); // k=0
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(s);

      await arena.connect(operator).pause(id);
      const frozen = await arena.remainingStake(id, attackerA.address);
      expect(frozen).to.equal(s);
      await expect(joinAs(game, attackerB, id)).to.be.revertedWithCustomError(
        arena,
        'PausedNow'
      );

      await time.increase(6n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(frozen);

      await arena.connect(operator).unpause(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(frozen);

      await time.increase(EPOCH);
      const after = await assertRemaining(
        arena,
        id,
        attackerA.address,
        s,
        1n,
        'unpause+2h'
      );
      expect(after).to.be.lessThan(frozen);
      expect(after).to.equal(expectedRemaining(s, 1n)); // 7.5 RTM
    });

    it('进行中暂停期间 remaining 不变，unpause 后继续累计', async function () {
      const { arena, operator, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);

      await time.increase(2n * EPOCH); // k=2
      const beforePause = await assertRemaining(
        arena,
        id,
        attackerA.address,
        s,
        2n,
        'before pause'
      );

      await arena.connect(operator).pause(id);
      await time.increase(6n * HOUR);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(beforePause);

      await arena.connect(operator).unpause(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(beforePause);

      await time.increase(EPOCH); // 有效时长 4h+2h => k=3
      const after = await assertRemaining(
        arena,
        id,
        attackerA.address,
        s,
        3n,
        'after unpause'
      );
      expect(after).to.be.lessThan(beforePause);
    });

    it('暂停跨过 end：只计到 end，不抹掉已累计罚款', async function () {
      const { arena, rtm, operator, defender, outsider, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game); // duration = 6h
      await joinAs(game, attackerA, id);

      await time.increase(2n * EPOCH); // 4h => k=2
      const beforePause = await assertRemaining(
        arena,
        id,
        attackerA.address,
        s,
        2n,
        'before pause'
      );

      await arena.connect(operator).pause(id);
      await time.increase(4n * HOUR); // now 越过 end，暂停仍未解除
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(beforePause);

      await arena.connect(outsider).expire(id);
      const remAfter = await arena.remainingStake(id, attackerA.address);
      expect(remAfter).to.equal(beforePause);
      expectClose(remAfter, expectedRemaining(s, 2n), 'expire while paused');

      const due = await arena.penaltyDue(id, attackerA.address);
      expect(due).to.be.greaterThan(0n);
      expect(due).to.equal(s - remAfter);

      const defBefore = await rtm.balanceOf(defender.address);
      await expect(arena.connect(defender).collectPenalties(id))
        .to.emit(arena, 'PenaltiesCollected')
        .withArgs(id, defender.address, due);
      expect(await rtm.balanceOf(defender.address)).to.equal(defBefore + due);
    });

    it('暂停后加入：pausedAtJoin 快照排除此前暂停时长', async function () {
      const { arena, operator, attackerA, attackerB } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);

      await time.increase(EPOCH); // A k=1

      await arena.connect(operator).pause(id);
      const pausedAt = BigInt(await time.latest());
      await time.increase(6n * HOUR);
      await arena.connect(operator).unpause(id);
      const pausedFor = BigInt(await time.latest()) - pausedAt;

      // B 在暂停结束后加入：pausedAtJoin 必须快照此前的全部暂停时长。
      await joinAs(game, attackerB, id);
      expect((await arena.attackers(id, attackerB.address)).pausedAtJoin).to.equal(
        pausedFor
      );

      await time.increase(EPOCH); // A 有效 4h => k=2；B 有效 2h => k=1
      const remA = await assertRemaining(arena, id, attackerA.address, s, 2n, 'A 跨暂停');
      const remB = await assertRemaining(
        arena,
        id,
        attackerB.address,
        s,
        1n,
        'B 暂停后加入'
      );
      expect(remA).to.equal(expectedRemaining(s, 2n)); // 5.625 RTM
      expect(remB).to.equal(expectedRemaining(s, 1n)); // 7.5 RTM
      expect(remA).to.be.lessThan(remB);
    });

    it('多轮暂停累加：有效时长扣除全部暂停（k=3）', async function () {
      const { arena, operator, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);

      // 第一段：有效 2h => k=1。
      await time.increase(EPOCH);
      const rem1 = await assertRemaining(arena, id, attackerA.address, s, 1n, '第一段后');
      expect(rem1).to.equal(expectedRemaining(s, 1n)); // 7.5 RTM

      await arena.connect(operator).pause(id);
      await time.increase(2n * HOUR); // 暂停 2h 不计入有效时长
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(rem1);
      await arena.connect(operator).unpause(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(rem1);

      // 第二段：有效累计 4h => k=2。
      await time.increase(EPOCH);
      const rem2 = await assertRemaining(arena, id, attackerA.address, s, 2n, '第二段后');
      expect(rem2).to.equal(expectedRemaining(s, 2n)); // 5.625 RTM
      expect(rem2).to.be.lessThan(rem1);

      await arena.connect(operator).pause(id);
      await time.increase(4n * HOUR); // 暂停 4h 不计入有效时长
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(rem2);
      await arena.connect(operator).unpause(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(rem2);

      // 第三段：有效累计 6h => k=3。
      await time.increase(EPOCH);
      const rem3 = await assertRemaining(arena, id, attackerA.address, s, 3n, '第三段后');
      expect(rem3).to.equal(expectedRemaining(s, 3n)); // 4.21875 RTM
      expect(rem3).to.be.lessThan(rem2);
    });
  });

  // ==================================================================
  // 4. endedAt 冻结
  // ==================================================================
  describe('endedAt 冻结', function () {
    it('expire 后时间旅行 7 天，remaining / penaltyDue 不变', async function () {
      const { arena, outsider, attackerA } = game;
      const { id, end } = await makeContest(game);
      await joinAs(game, attackerA, id);

      await time.increaseTo(end);
      const remAtEnd = await arena.remainingStake(id, attackerA.address);
      const dueAtEnd = await arena.penaltyDue(id, attackerA.address);
      expect(dueAtEnd).to.be.greaterThan(0n);

      await arena.connect(outsider).expire(id);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remAtEnd);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(dueAtEnd);

      await time.increase(7n * DAY);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remAtEnd);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(dueAtEnd);
    });

    it('breach 后时间旅行 7 天，remaining / penaltyDue 不变', async function () {
      const { arena, rtm, attackerA, w } = game;
      const { id } = await makeContest(game, { duration: DAY });
      await joinAs(game, attackerA, id);

      await time.increase(EPOCH);
      const remBefore = await arena.remainingStake(id, attackerA.address);
      const dueBefore = await arena.penaltyDue(id, attackerA.address);
      expect(dueBefore).to.be.greaterThan(0n);

      await rtm.connect(w).transfer(attackerA.address, RTM(1)); // 触发 onBreach
      expect(await arena.contestState(id)).to.equal(2n);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remBefore);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(dueBefore);

      await time.increase(7n * DAY);
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(remBefore);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(dueBefore);
    });
  });

  // ==================================================================
  // 5. 多攻方不同 joinedAt + 资金守恒
  // ==================================================================
  it('多攻方不同 joinedAt：k 不同、collect 求和、expire 后资金守恒', async function () {
    const { arena, rtm, defender, outsider, attackerA, attackerB, w } = game;
    const s = (STAKE * BigInt(BPS)) / 10000n;
    const { id, end } = await makeContest(game, { duration: 8n * HOUR });

    await joinAs(game, attackerA, id);
    await time.increase(EPOCH);
    await joinAs(game, attackerB, id);
    await time.increase(EPOCH);

    // A：2 个 epoch；B：刚满 1 个 epoch。
    const remA = await assertRemaining(arena, id, attackerA.address, s, 2n, 'A');
    const remB = await assertRemaining(arena, id, attackerB.address, s, 1n, 'B');
    expect(remA).to.be.lessThan(remB);

    const accruedA = await arena.accruedPenalties(id, attackerA.address);
    const accruedB = await arena.accruedPenalties(id, attackerB.address);
    expectClose(accruedA, s - expectedRemaining(s, 2n), 'A accrued');
    expectClose(accruedB, s - expectedRemaining(s, 1n), 'B accrued');

    // collect 前快照：守方已支付 S，两个攻方质押在 Arena，W 持有 S。
    const snap = {
      defender: await rtm.balanceOf(defender.address),
      a: await rtm.balanceOf(attackerA.address),
      b: await rtm.balanceOf(attackerB.address),
      w: await rtm.balanceOf(w.address),
      arena: await rtm.balanceOf(arena.target)
    };
    expect(snap.arena).to.equal(2n * s);
    expect(snap.w).to.equal(STAKE);

    const totalAccrued = accruedA + accruedB;
    await expect(arena.connect(defender).collectPenalties(id))
      .to.emit(arena, 'PenaltiesCollected')
      .withArgs(id, defender.address, totalAccrued);
    expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);
    expect(await arena.penaltyDue(id, attackerB.address)).to.equal(0n);
    // collect 不改变 remaining；同一 epoch 内视角不变。
    expect(await arena.remainingStake(id, attackerA.address)).to.equal(remA);
    expect(await arena.remainingStake(id, attackerB.address)).to.equal(remB);

    await time.increaseTo(end);
    const remAEnd = await arena.remainingStake(id, attackerA.address);
    const remBEnd = await arena.remainingStake(id, attackerB.address);
    expect(remAEnd).to.be.lessThanOrEqual(remA);
    expect(remBEnd).to.be.lessThanOrEqual(remB);
    expect(await arena.contestState(id)).to.equal(1n);

    await arena.connect(outsider).expire(id);
    const remAFinal = await arena.remainingStake(id, attackerA.address);
    const remBFinal = await arena.remainingStake(id, attackerB.address);
    const dueAFinal = await arena.penaltyDue(id, attackerA.address);
    const dueBFinal = await arena.penaltyDue(id, attackerB.address);
    expect(dueAFinal + dueBFinal).to.be.greaterThan(0n);

    await expect(arena.connect(attackerA).withdrawStake(id))
      .to.emit(arena, 'StakeWithdrawn')
      .withArgs(id, attackerA.address, remAFinal);
    await expect(arena.connect(attackerB).withdrawStake(id))
      .to.emit(arena, 'StakeWithdrawn')
      .withArgs(id, attackerB.address, remBFinal);

    const defenderBeforeFinalCollect = await rtm.balanceOf(defender.address);
    await expect(arena.connect(defender).collectPenalties(id))
      .to.emit(arena, 'PenaltiesCollected')
      .withArgs(id, defender.address, dueAFinal + dueBFinal);
    expect(await rtm.balanceOf(defender.address)).to.equal(
      defenderBeforeFinalCollect + dueAFinal + dueBFinal
    );

    // 资金守恒：Arena 归零，W 归零，三方增量之和 = S + sA + sB。
    expect(await rtm.balanceOf(arena.target)).to.equal(0n);
    expect(await rtm.balanceOf(w.address)).to.equal(0n);
    const defenderGain = (await rtm.balanceOf(defender.address)) - snap.defender;
    const aGain = (await rtm.balanceOf(attackerA.address)) - snap.a;
    const bGain = (await rtm.balanceOf(attackerB.address)) - snap.b;
    expect(aGain).to.equal(remAFinal);
    expect(bGain).to.equal(remBFinal);
    expect(defenderGain + aGain + bGain).to.equal(STAKE + 2n * s);
  });

  // ==================================================================
  // 6. 任务 4 审查缺口
  // ==================================================================
  describe('审查缺口回归', function () {
    it('普通赛 join 的 maxStake 拒绝且合约状态不变', async function () {
      const { arena, rtm, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id } = await makeContest(game);
      const balanceBefore = await rtm.balanceOf(attackerA.address);

      await expect(joinAs(game, attackerA, id, s - 1n))
        .to.be.revertedWithCustomError(arena, 'StakeTooHigh')
        .withArgs(s, s - 1n);

      expect(await arena.isRegisteredAttacker(id, attackerA.address)).to.equal(false);
      expect((await arena.attackers(id, attackerA.address)).joined).to.equal(false);
      expect((await arena.contestInfo(id)).attackerCount).to.equal(0n);
      expect(await rtm.balanceOf(attackerA.address)).to.equal(balanceBefore);
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);
      await expect(arena.contestAttackers(id, 0)).to.be.reverted;
    });

    it('普通赛 expire 不改变 activeMiningCount', async function () {
      const { arena, outsider, w, w2 } = game;
      await makeMining(game, { wallet: w });
      expect(await arena.activeMiningCount()).to.equal(1n);

      const { id, end } = await makeContest(game, { wallet: w2 });
      await time.increaseTo(end);
      await arena.connect(outsider).expire(id);

      expect(await arena.contestState(id)).to.equal(2n);
      expect(await arena.activeMiningCount()).to.equal(1n);
    });

    it('暂停中 mining breach / retire 释放名额，且 paused 复位', async function () {
      const { arena, rtm, operator, attackerA, w, w2 } = game;
      const c1 = await makeMining(game, { wallet: w });
      const c2 = await makeMining(game, { wallet: w2 });
      await makeMining(game);
      expect(await arena.activeMiningCount()).to.equal(3n);

      // breach 路径：暂停中仍可攻破，名额必须释放。
      await joinMiningAs(game, attackerA, c1.id);
      await arena.connect(operator).pause(c1.id);
      expect((await arena.contestInfo(c1.id)).paused).to.equal(true);

      await rtm.connect(w).transfer(attackerA.address, RTM(1));
      expect(await arena.contestState(c1.id)).to.equal(2n);
      expect(await arena.activeMiningCount()).to.equal(2n);
      expect((await arena.contestInfo(c1.id)).paused).to.equal(false);

      // retire 路径：暂停中主动退役，同样释放名额并清掉 pause 标记。
      // 挖矿赛没有 fault 路径（reportDefenderFault 仅普通赛）。
      await arena.connect(operator).pause(c2.id);
      expect((await arena.contestInfo(c2.id)).paused).to.equal(true);
      await arena.connect(operator).retireMining(c2.id);
      expect(await arena.contestState(c2.id)).to.equal(2n);
      expect(await arena.activeMiningCount()).to.equal(1n);
      expect((await arena.contestInfo(c2.id)).paused).to.equal(false);

      // 释放出的名额可立即复用。
      await makeMining(game);
      expect(await arena.activeMiningCount()).to.equal(2n);
    });

    it('initialize 拒绝 treasury 作为 RTM，失败后仍可正常初始化', async function () {
      const { owner, treasury } = game;
      const Arena = await ethers.getContractFactory('Arena');
      const arena2 = await Arena.deploy(owner.address, treasury.target, true);

      await expect(arena2.initialize(treasury.target))
        .to.be.revertedWithCustomError(arena2, 'InvalidRTM');
      expect(await arena2.rtm()).to.equal(ethers.ZeroAddress);

      const rtm2 = await (await ethers.getContractFactory('RTMToken')).deploy(
        owner.address,
        arena2.target
      );
      await arena2.initialize(rtm2.target);
      expect(await arena2.rtm()).to.equal(rtm2.target);
    });
  });

  // ==================================================================
  // 7. pause 语义（记录现状）
  // ==================================================================
  it('暂停中 attack 拒绝；markDelivered 按当前实现仍允许', async function () {
    const { arena, operator, attackerA } = game;
    const { id } = await makeContest(game);
    await joinAs(game, attackerA, id);

    const deliveredHash = msgHash('paused-delivery');
    await attack(game, attackerA, id, deliveredHash);
    await arena.connect(operator).pause(id);

    await expect(attack(game, attackerA, id, 'paused-attack'))
      .to.be.revertedWithCustomError(arena, 'PausedNow')
      .withArgs(id);

    // 当前 markDelivered 只检查 Live / end / 已付费，不检查 lastPauseAt。
    // 这里断言现状（暂停中允许记录送达），不修改合约。
    await expect(arena.connect(operator).markDelivered(id, attackerA.address, deliveredHash))
      .to.emit(arena, 'MarkDelivered')
      .withArgs(id, attackerA.address, deliveredHash, 1n, ethers.ZeroHash);
    expect((await arena.attackers(id, attackerA.address)).delivered).to.equal(1n);

    await arena.connect(operator).unpause(id);
    await expect(attack(game, attackerA, id, 'after-unpause')).to.emit(
      arena,
      'AttackPaid'
    );
  });

  // ==================================================================
  // 8. 罚没迭代上限 / D≤7d 不超时、不超 gas
  // ==================================================================
  describe('迭代上限与 gas 边界', function () {
    it('正常比赛 D=7d：到期最大实际 k=83，expire/withdraw/collect 均不超 gas 上限', async function () {
      const { arena, rtm, defender, outsider, attackerA } = game;
      const s = (STAKE * BigInt(BPS)) / 10000n;
      const { id, end } = await makeContest(game, { duration: 7n * DAY });
      await joinAs(game, attackerA, id);

      const joinedAt = (await arena.attackers(id, attackerA.address)).joinedAt;
      // join 所在的区块必然晚于 contest.start（Hardhat 每笔 tx 递增时间），
      // 因此 (end - joinedAt) 略小于 7d，向下取整最大实际 k = 83；
      // k=84 只在不现实的“join 与 start 同秒”时序下才可达。
      const maxK = (end - joinedAt) / EPOCH;
      expect(maxK).to.equal(83n);

      await time.increaseTo(end);
      const remAtExpiry = await assertRemaining(
        arena,
        id,
        attackerA.address,
        s,
        maxK,
        'D=7d 到期'
      );
      const due = await arena.penaltyDue(id, attackerA.address);
      expect(due).to.be.greaterThan(0n);
      expect(due).to.equal(s - remAtExpiry);

      const attackerBefore = await rtm.balanceOf(attackerA.address);
      const defenderBeforeExpire = await rtm.balanceOf(defender.address);

      const expireReceipt = await (await arena.connect(outsider).expire(id)).wait();
      expect(await arena.contestState(id)).to.equal(2n);
      // 到期时 S 从 W 退回 defender，作为后续罚款收入的基准。
      expect(await rtm.balanceOf(defender.address)).to.equal(
        defenderBeforeExpire + STAKE
      );

      const withdrawReceipt = await (await arena.connect(attackerA).withdrawStake(id))
        .wait();
      expect(await rtm.balanceOf(attackerA.address)).to.equal(
        attackerBefore + remAtExpiry
      );

      const defenderBeforeCollect = await rtm.balanceOf(defender.address);
      const collectReceipt = await (await arena.connect(defender).collectPenalties(id))
        .wait();
      expect(await rtm.balanceOf(defender.address)).to.equal(
        defenderBeforeCollect + due
      );
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);
      // Arena 收到 s，随后付出 remaining + due = s，余额归零。
      expect(await rtm.balanceOf(arena.target)).to.equal(0n);

      // 实测远低于区块 gas limit；上限留足余量，只约束迭代算法不出现病态开销。
      expect(expireReceipt.gasUsed).to.be.lessThan(200_000n);
      expect(withdrawReceipt.gasUsed).to.be.lessThan(200_000n);
      expect(collectReceipt.gasUsed).to.be.lessThan(500_000n);
    });

    it('挖矿赛 collectPenalties / withdrawStake 恒为 NotNormalContest', async function () {
      const { arena, attackerA } = game;
      const { id } = await makeMining(game);
      await joinMiningAs(game, attackerA, id);

      await expect(arena.connect(game.defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NotNormalContest');
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.be.revertedWithCustomError(arena, 'NotNormalContest');
      expect(await arena.remainingStake(id, attackerA.address)).to.equal(0n);
      expect(await arena.penaltyDue(id, attackerA.address)).to.equal(0n);

      await arena.connect(game.operator).retireMining(id);
      await expect(arena.connect(game.defender).collectPenalties(id))
        .to.be.revertedWithCustomError(arena, 'NotNormalContest');
      await expect(arena.connect(attackerA).withdrawStake(id))
        .to.be.revertedWithCustomError(arena, 'NotNormalContest');
    });
  });
});
