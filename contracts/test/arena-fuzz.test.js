// SPDX-License-Identifier: MIT
/**
 * 任务 6：Arena 普通赛资金守恒不变式 fuzz。
 *
 * 早期计划中的等式
 *   S + Σs = 守方罚款 + 攻方提款 + 获胜者所得 + Arena 残余 + Treasury 手续费
 * 把手续费放在右侧，却没有在左侧计入“手续费来自攻方余额（不属于质押 S/Σs）”，
 * 按字面实现会误报。本文件改用以下互相独立的不变式：
 *   1) 六个相关地址（defender/3 攻方/W/Arena/Treasury）余额总和逐轮守恒；
 *   2) totalWithdrawn + totalPenalties == totalStake，即所有质押要么提回、要么被罚没；
 *   3) Treasury 增量 == AttackPaid 手续费合计（本文件不触发 refundUnserved）；
 *   4) totalSupply 不变（普通赛没有增发路径）。
 *
 * 随机性：mulberry32(seed=1000+round)，链上时间由 Hardhat 确定性推进，
 * 相同 seed 完全可复现。所有交易/视图调用失败都会带 round/seed/step/action 上下文。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const {
  RTM,
  HOUR,
  DAY,
  EPOCH,
  deployGame,
  makeContest,
  joinAs,
  attack,
  msgHash,
  findEvent
} = require('./arena.helpers');

const ROUNDS = 25;
const DURATION = 3n * DAY;
const MIN_TIME_STEP = 15n * 60n; // 15 分钟
const MAX_TIME_STEP = 3n * HOUR; // 3 小时
const TIME_STEP_SPAN = MAX_TIME_STEP - MIN_TIME_STEP + 1n;

// ---------------------------------------------------------------------------
// 确定性 PRNG / 小工具
// ---------------------------------------------------------------------------

/** mulberry32：32 位确定性 PRNG，禁止 Math.random。 */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return (t ^ (t >>> 14)) >>> 0;
  };
}

function pick(rng, items) {
  if (items.length === 0) throw new Error('pick() from empty list');
  return items[rng() % items.length];
}

async function sumBalances(rtm, addresses) {
  let total = 0n;
  for (const address of addresses) total += await rtm.balanceOf(address);
  return total;
}

function trackedAddresses(game) {
  return [
    game.defender.address,
    game.attackerA.address,
    game.attackerB.address,
    game.outsider.address,
    game.w.address,
    game.arena.target,
    game.treasury.target
  ];
}

function tag(rs) {
  return `[round=${rs.round} seed=${rs.seed} step=${rs.ctx.step} action=${rs.ctx.action}]`;
}

function annotate(err, ctx) {
  const prefix = `[round=${ctx.round} seed=${ctx.seed} step=${ctx.step} action=${ctx.action}]`;
  if (err && typeof err === 'object' && !String(err.message).startsWith(prefix)) {
    err.message = `${prefix} ${err.message}`;
  }
  return err;
}

/** 设置失败上下文；捕获后只做标注并重新抛出，绝不吞掉错误。 */
async function withCtx(rs, step, action, fn) {
  rs.ctx.step = step;
  rs.ctx.action = action;
  try {
    return await fn();
  } catch (err) {
    throw annotate(err, rs.ctx);
  }
}

function expectEq(rs, actual, expected, label) {
  expect(actual, `${tag(rs)} ${label}: actual=${actual} expected=${expected}`).to.equal(
    expected
  );
}

function expectGt(rs, actual, bound, label) {
  expect(actual, `${tag(rs)} ${label}: actual=${actual} bound=${bound}`).to.be.greaterThan(
    bound
  );
}

// ---------------------------------------------------------------------------
// 单轮状态
// ---------------------------------------------------------------------------

function createRound(game, round) {
  const seed = 1000 + round;
  return {
    game,
    round,
    seed,
    rng: mulberry32(seed),
    ctx: { round, seed, step: 0, action: 'setup' },
    id: null,
    end: null,
    joined: [], // [{ signer, label }]
    paid: [], // [{ signer, label, hash, delivered }]
    attackSeq: 0,
    totalStake: 0n, // Joined 事件累计
    totalFees: 0n, // AttackPaid 事件累计
    totalWithdrawn: 0n, // StakeWithdrawn 事件累计
    totalPenalties: 0n, // PenaltiesCollected 事件累计（Live 随机收款 + 结算后清收）
    settlement: null, // expiry | breach | fault
    faultDelivered: null,
    breachWinner: null,
    attackers: [
      { signer: game.attackerA, label: 'A' },
      { signer: game.attackerB, label: 'B' },
      { signer: game.outsider, label: 'O' }
    ],
    coverage: {
      join: 0,
      attack: 0,
      deliver: 0,
      collect: 0,
      collectLive: 0,
      collectCleanup: 0,
      pause: 0,
      unpause: 0,
      increaseTime: 0,
      withdraw: 0,
      expiry: 0,
      breach: 0,
      fault: 0,
      faultSwept: 0,
      faultDistributed: 0,
      multiAttacker: 0
    }
  };
}

// ---------------------------------------------------------------------------
// 动作实现
// ---------------------------------------------------------------------------

async function execJoin(rs, entry) {
  const { game, id } = rs;
  const before = rs.joined.length;
  const receipt = await (await joinAs(game, entry.signer, id)).wait();
  const ev = findEvent(receipt, game.arena, 'Joined');
  expectEq(rs, ev.args.attacker, entry.signer.address, 'Joined.attacker');
  rs.totalStake += ev.args.stake;
  if (!rs.joined.some((e) => e.label === entry.label)) rs.joined.push(entry);
  if (before < 2 && rs.joined.length >= 2) rs.coverage.multiAttacker += 1;
  rs.coverage.join += 1;
  return ev;
}

async function execAttack(rs) {
  const { game, id } = rs;
  const entry = pick(rs.rng, rs.joined);
  // 每条消息全局唯一；seed 与 round 一一对应，step/seq 区分动作。
  const label = `arena-fuzz:${rs.seed}:${rs.ctx.step}:${rs.attackSeq}`;
  rs.attackSeq += 1;
  const hash = msgHash(label);
  const receipt = await (await attack(game, entry.signer, id, hash)).wait();
  const ev = findEvent(receipt, game.arena, 'AttackPaid');
  expectEq(rs, ev.args.msgHash, hash, 'AttackPaid.msgHash');
  rs.totalFees += ev.args.fee;
  rs.paid.push({ signer: entry.signer, label: entry.label, hash, delivered: false });
  rs.coverage.attack += 1;
  return ev;
}

async function execMarkDelivered(rs) {
  const { game, id } = rs;
  const pending = rs.paid.filter((p) => !p.delivered);
  if (pending.length === 0) throw new Error('markDelivered selected with no pending message');
  const p = pick(rs.rng, pending);
  const receipt = await (
    await game.arena.connect(game.operator).markDelivered(id, p.signer.address, p.hash)
  ).wait();
  const ev = findEvent(receipt, game.arena, 'MarkDelivered');
  expectEq(rs, ev.args.msgHash, p.hash, 'MarkDelivered.msgHash');
  p.delivered = true;
  rs.coverage.deliver += 1;
  return ev;
}

async function execCollect(rs, { live }) {
  const { game, id } = rs;
  const receipt = await (await game.arena.connect(game.defender).collectPenalties(id)).wait();
  const ev = findEvent(receipt, game.arena, 'PenaltiesCollected');
  expectEq(rs, ev.args.recipient, game.defender.address, 'PenaltiesCollected.recipient');
  rs.totalPenalties += ev.args.amount;
  rs.coverage.collect += 1;
  if (live) rs.coverage.collectLive += 1;
  else rs.coverage.collectCleanup += 1;
  return ev;
}

async function execPause(rs) {
  await (await rs.game.arena.connect(rs.game.operator).pause(rs.id)).wait();
  rs.coverage.pause += 1;
}

async function execUnpause(rs) {
  await (await rs.game.arena.connect(rs.game.operator).unpause(rs.id)).wait();
  rs.coverage.unpause += 1;
}

async function execIncreaseTime(rs) {
  const now = BigInt(await time.latest());
  const delta = MIN_TIME_STEP + BigInt(rs.rng() % Number(TIME_STEP_SPAN));
  // duration=3d，最多 15 步 × 3h + 固定 warmup/暂停推进，理论上不会越界；
  // 这里显式断言，避免把“时间越界导致结算前已过期”误当成随机行为。
  expect(
    now + delta,
    `${tag(rs)} increaseTime must stay before end: now=${now} delta=${delta} end=${rs.end}`
  ).to.be.lessThan(rs.end);
  await time.increase(delta);
  rs.coverage.increaseTime += 1;
  return delta;
}

async function executeAction(rs, action) {
  switch (action.name) {
    case 'join':
      return execJoin(rs, action.entry);
    case 'attack':
      return execAttack(rs);
    case 'markDelivered':
      return execMarkDelivered(rs);
    case 'collectPenalties':
      return execCollect(rs, { live: true });
    case 'pause':
      return execPause(rs);
    case 'unpause':
      return execUnpause(rs);
    case 'increaseTime':
      return execIncreaseTime(rs);
    default:
      throw new Error(`unknown action ${action.name}`);
  }
}

/**
 * 每一步都先读链上状态再构建可用动作，避免用 revert 当控制流。
 * markDelivered 的随机动作只在偶数轮提供：偶数轮 warmup 已送达一条，
 * 奇数轮的弃权结算因此稳定走“无 delivered → W 退回 defender”分支，
 * 从而确定性覆盖弃权的两条分配路径（不依赖随机性赌覆盖）。
 */
async function buildActions(rs) {
  const { game, id } = rs;
  const info = await game.arena.contestInfo(id);
  const now = BigInt(await time.latest());
  const live = info.state === 1n;
  const beforeEnd = now < info.end;
  const actions = [];
  const push = (weight, action) => {
    for (let i = 0; i < weight; i += 1) actions.push(action);
  };

  if (!live) return actions;

  if (beforeEnd && !info.paused) {
    for (const entry of rs.attackers) {
      const rec = await game.arena.attackers(id, entry.signer.address);
      if (!rec.joined) push(2, { name: 'join', entry });
    }
    if (rs.joined.length > 0) push(3, { name: 'attack' });
  }

  if (beforeEnd && rs.round % 2 === 0 && rs.paid.some((p) => !p.delivered)) {
    push(2, { name: 'markDelivered' });
  }

  let anyDue = false;
  for (const entry of rs.joined) {
    if ((await game.arena.penaltyDue(id, entry.signer.address)) > 0n) {
      anyDue = true;
      break;
    }
  }
  if (anyDue) push(2, { name: 'collectPenalties' }); // 暂停中也可收，按当前合约语义

  if (beforeEnd && !info.paused) push(1, { name: 'pause' });
  if (info.paused) push(1, { name: 'unpause' });
  if (beforeEnd) push(3, { name: 'increaseTime' });

  return actions;
}

// ---------------------------------------------------------------------------
// 固定覆盖：不靠随机性保证 join/collect/pause/unpause/多攻方至少发生一次
// ---------------------------------------------------------------------------

async function runForcedCoverage(rs) {
  const mod = rs.round % 5;

  if (mod === 0) {
    // 推进一个 epoch 后由 defender 收一次罚款，覆盖 Live collect。
    await withCtx(rs, 0, 'forcedIncreaseForCollect', () => time.increase(EPOCH));
    await withCtx(rs, 0, 'forcedCollect', async () => {
      const due = await rs.game.arena.penaltyDue(rs.id, rs.attackers[0].signer.address);
      expectGt(rs, due, 0n, 'forced collect requires penaltyDue > 0');
      await execCollect(rs, { live: true });
    });
  } else if (mod === 1) {
    // 固定一次 pause → 推进墙钟 → unpause。
    await withCtx(rs, 0, 'forcedPause', () => execPause(rs));
    await withCtx(rs, 0, 'forcedPauseElapse', () => time.increase(HOUR));
    await withCtx(rs, 0, 'forcedUnpause', () => execUnpause(rs));
  } else if (mod === 2) {
    await withCtx(rs, 0, 'forcedJoinB', () => execJoin(rs, rs.attackers[1]));
  } else if (mod === 3) {
    await withCtx(rs, 0, 'forcedJoinOutsider', () => execJoin(rs, rs.attackers[2]));
  }
}

// ---------------------------------------------------------------------------
// 结算
// ---------------------------------------------------------------------------

async function expireFallback(rs) {
  const { game, id } = rs;
  if (BigInt(await time.latest()) < rs.end) await time.increaseTo(rs.end);
  const receipt = await (await game.arena.connect(game.outsider).expire(id)).wait();
  findEvent(receipt, game.arena, 'Expired');
  rs.settlement = 'expiry';
  rs.coverage.expiry += 1;
}

async function settleRound(rs, mode) {
  const { game, id } = rs;
  const info = await game.arena.contestInfo(id);
  const now = BigInt(await time.latest());
  expectEq(rs, info.state, 1n, 'contest must still be Live before settlement');

  if (mode === 0) {
    // 到期：推进到 end，再由任意人 expire。
    if (now < info.end) await time.increaseTo(info.end);
    const receipt = await (await game.arena.connect(game.outsider).expire(id)).wait();
    findEvent(receipt, game.arena, 'Expired');
    rs.settlement = 'expiry';
    rs.coverage.expiry += 1;
  } else if (mode === 1) {
    // 攻破：把 W 全部余额转给一个已加入攻方，触发 Token -> onBreach。
    let settled = false;
    if (now < info.end && rs.joined.length > 0) {
      const wBal = await game.rtm.balanceOf(game.w.address);
      if (wBal > 0n) {
        const winner = pick(rs.rng, rs.joined);
        const receipt = await (await game.rtm.connect(game.w).transfer(winner.signer.address, wBal)).wait();
        findEvent(receipt, game.arena, 'ContestSettled');
        rs.breachWinner = winner;
        rs.settlement = 'breach';
        rs.coverage.breach += 1;
        settled = true;
      }
    }
    if (!settled) await expireFallback(rs);
  } else {
    // 弃权：operator 报告 fault；条件不满足则回退到期。
    let settled = false;
    if (now < info.end) {
      const receipt = await (
        await game.arena.connect(game.operator).reportDefenderFault(id)
      ).wait();
      findEvent(receipt, game.arena, 'DefenderFault');
      const delivered = rs.paid.filter((p) => p.delivered).length;
      rs.faultDelivered = delivered;
      rs.settlement = 'fault';
      rs.coverage.fault += 1;
      if (delivered === 0) rs.coverage.faultSwept += 1;
      else rs.coverage.faultDistributed += 1;
      settled = true;
    }
    if (!settled) await expireFallback(rs);
  }

  expectEq(rs, BigInt(await game.arena.contestState(id)), 2n, 'contestState after settlement');
  expectEq(rs, await game.rtm.balanceOf(game.w.address), 0n, 'W balance after settlement');
}

// ---------------------------------------------------------------------------
// 结算后清理与不变式断言
// ---------------------------------------------------------------------------

async function cleanupRound(rs) {
  const { game, id } = rs;
  const fault = rs.settlement === 'fault';
  let onchainStakeSum = 0n;

  for (const entry of rs.joined) {
    const a = await game.arena.attackers(id, entry.signer.address);
    onchainStakeSum += a.stake;
    expectEq(rs, a.joined, true, `${entry.label} joined flag`);
    expectEq(rs, a.waived, fault, `${entry.label} waived flag matches settlement`);

    let amount;
    if (a.waived) {
      amount = a.stake - a.penaltyTaken - a.stakeWithdrawn;
    } else {
      const remaining = await game.arena.remainingStake(id, entry.signer.address);
      amount = remaining > a.stakeWithdrawn ? remaining - a.stakeWithdrawn : 0n;
    }

    if (amount > 0n) {
      const receipt = await (await game.arena.connect(entry.signer).withdrawStake(id)).wait();
      const ev = findEvent(receipt, game.arena, 'StakeWithdrawn');
      expectEq(rs, ev.args.attacker, entry.signer.address, 'StakeWithdrawn.attacker');
      expectEq(rs, ev.args.amount, amount, `${entry.label} StakeWithdrawn amount`);
      rs.totalWithdrawn += ev.args.amount;
      rs.coverage.withdraw += 1;
    }
  }

  expectEq(rs, onchainStakeSum, rs.totalStake, 'on-chain stake sum == Joined events');

  if (!fault) {
    // 非 fault：清收剩余罚款（可能为 0，此时不调用，避免把 revert 当控制流）。
    let dueSum = 0n;
    for (const entry of rs.joined) {
      dueSum += await game.arena.penaltyDue(id, entry.signer.address);
    }
    if (dueSum > 0n) {
      const receipt = await (
        await game.arena.connect(game.defender).collectPenalties(id)
      ).wait();
      const ev = findEvent(receipt, game.arena, 'PenaltiesCollected');
      // 已结算，endedAt 冻结，dueSum 不会因区块时间前进而变化。
      expectEq(rs, ev.args.amount, dueSum, 'final PenaltiesCollected amount');
      rs.totalPenalties += ev.args.amount;
      rs.coverage.collect += 1;
      rs.coverage.collectCleanup += 1;
    }
  } else {
    // fault：全部 waived，penaltyDue 必须为 0，不调用 collectPenalties。
    for (const entry of rs.joined) {
      expectEq(
        rs,
        await game.arena.penaltyDue(id, entry.signer.address),
        0n,
        `${entry.label} penaltyDue after fault`
      );
    }
  }
}

async function assertRoundInvariants(rs) {
  const { game } = rs;
  const finalTotal = await sumBalances(game.rtm, trackedAddresses(game));

  expectEq(rs, finalTotal, rs.initialTotal, 'sum of tracked balances conserved');
  expectEq(rs, await game.rtm.balanceOf(game.arena.target), 0n, 'Arena balance drained');
  expectEq(rs, await game.rtm.balanceOf(game.w.address), 0n, 'W balance drained');
  expectEq(
    rs,
    rs.totalWithdrawn + rs.totalPenalties,
    rs.totalStake,
    'totalWithdrawn + totalPenalties == totalStake'
  );
  expectEq(
    rs,
    (await game.rtm.balanceOf(game.treasury.target)) - rs.initialTreasury,
    rs.totalFees,
    'Treasury delta == AttackPaid fees'
  );
  expectEq(rs, await game.rtm.totalSupply(), rs.initialSupply, 'totalSupply unchanged');
}

// ---------------------------------------------------------------------------
// 测试主体
// ---------------------------------------------------------------------------

describe('Arena 资金守恒不变式 fuzz', function () {
  it('25 轮随机生命周期始终满足资金守恒', async function () {
    this.timeout(180000);

    const aggregate = {
      join: 0,
      attack: 0,
      deliver: 0,
      collect: 0,
      collectLive: 0,
      collectCleanup: 0,
      pause: 0,
      unpause: 0,
      increaseTime: 0,
      withdraw: 0,
      expiry: 0,
      breach: 0,
      fault: 0,
      faultSwept: 0,
      faultDistributed: 0,
      multiAttacker: 0
    };
    const settlementCounts = { expiry: 0, breach: 0, fault: 0 };

    for (let round = 0; round < ROUNDS; round += 1) {
      const seed = 1000 + round;
      let game;
      try {
        game = await deployGame();
      } catch (err) {
        throw annotate(err, { round, seed, step: 0, action: 'deployGame' });
      }
      const rs = createRound(game, round);

      // 创建比赛前的资金快照。
      await withCtx(rs, 0, 'snapshot', async () => {
        rs.initialTotal = await sumBalances(game.rtm, trackedAddresses(game));
        rs.initialSupply = await game.rtm.totalSupply();
        rs.initialTreasury = await game.rtm.balanceOf(game.treasury.target);
      });

      await withCtx(rs, 0, 'createContest', async () => {
        const contest = await makeContest(game, { duration: DURATION });
        rs.id = contest.id;
        rs.end = contest.end;
        expectEq(rs, contest.stake, RTM(100), 'contest stake S');
        expectEq(rs, await game.rtm.balanceOf(game.w.address), RTM(100), 'W funded with S');
      });

      // Warmup：A join + 付费消息；偶数轮送达该消息。
      await withCtx(rs, 0, 'warmupJoinA', () => execJoin(rs, rs.attackers[0]));
      await withCtx(rs, 0, 'warmupAttackA', () => execAttack(rs));
      if (round % 2 === 0) {
        await withCtx(rs, 0, 'warmupMarkDelivered', () => execMarkDelivered(rs));
      }

      // 固定覆盖项（详见 runForcedCoverage）。
      await runForcedCoverage(rs);

      // 5–15 步随机动作，每步按链上状态筛选。
      const steps = 5 + (rs.rng() % 11);
      for (let step = 1; step <= steps; step += 1) {
        const actions = await withCtx(rs, step, 'buildActions', () => buildActions(rs));
        expectGt(rs, actions.length, 0, 'no available actions during Live contest');
        const action = pick(rs.rng, actions);
        await withCtx(rs, step, action.name, () => executeAction(rs, action));
      }

      // 按 round % 3 结算：到期 / 攻破 / 弃权。
      await withCtx(rs, steps + 1, 'settle', () => settleRound(rs, round % 3));
      settlementCounts[rs.settlement] += 1;

      // 清理：提款 + 剩余罚款清收。
      await withCtx(rs, steps + 2, 'cleanup', () => cleanupRound(rs));

      // 每轮关键断言。
      await withCtx(rs, steps + 3, 'assertRound', () => assertRoundInvariants(rs));

      for (const key of Object.keys(rs.coverage)) aggregate[key] += rs.coverage[key];
    }

    // 覆盖门槛：不依赖随机性，固定 warmup/forced 保证以下动作至少发生一次。
    const requiredCoverage = [
      'join',
      'attack',
      'deliver',
      'collectLive',
      'pause',
      'unpause',
      'expiry',
      'breach',
      'fault'
    ];
    for (const key of requiredCoverage) {
      expect(aggregate[key], `action coverage ${key}: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);
    }
    expect(aggregate.faultSwept, `fault sweep coverage: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);
    expect(
      aggregate.faultDistributed,
      `fault delivered-distribution coverage: ${JSON.stringify(aggregate)}`
    ).to.be.greaterThan(0);
    expect(aggregate.multiAttacker, `multi-attacker coverage: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);
    expect(aggregate.collectCleanup, `cleanup collect coverage: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);
    expect(aggregate.withdraw, `withdraw coverage: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);
    expect(aggregate.increaseTime, `increaseTime coverage: ${JSON.stringify(aggregate)}`).to.be.greaterThan(0);

    if (process.env.FUZZ_REPORT === '1') {
      // eslint-disable-next-line no-console
      console.log('[arena-fuzz] actions', JSON.stringify(aggregate));
      // eslint-disable-next-line no-console
      console.log('[arena-fuzz] settlements', JSON.stringify(settlementCounts));
    }
  });
});
