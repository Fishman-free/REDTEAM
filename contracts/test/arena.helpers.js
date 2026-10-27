// SPDX-License-Identifier: MIT
/**
 * Arena 共享测试 helper（任务 5/6 复用）。
 *
 * 设计约束：
 * - 不依赖 chai / mocha 等测试框架，可在脚本或其他套件中直接 require；
 * - 部署顺序固定为 Treasury -> Arena -> RTMToken -> initialize -> setOperator；
 * - createContest / createMiningContest 固定由 operator 调用；
 * - joinAs 自动 approve 无限额度，并默认传入精确应质押额作为 maxStake。
 */
const { ethers } = require('hardhat');

const RTM = (n) => ethers.parseEther(String(n));
const HOUR = 3600n;
const DAY = 86400n;
const EPOCH = 2n * HOUR;
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
      // 忽略其他合约的事件
    }
  }
  throw new Error(`event ${name} not found`);
}

/**
 * 部署一整套测试环境。
 * @param {{ testnet?: boolean, mint?: boolean }} [opts]
 * @returns {Promise<object>} 具名 signers、Treasury/Arena/RTMToken 合约实例
 */
async function deployGame({ testnet = true, mint = true } = {}) {
  const signers = await ethers.getSigners();
  const owner = signers[0];
  const operator = signers[1];
  const defender = signers[2];
  const attackerA = signers[3];
  const attackerB = signers[4];
  const outsider = signers[5];
  const treasuryOwner = signers[6];
  const w = signers[8];
  const w2 = signers[9];

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

  if (testnet && mint) {
    await arena.mintForTest(defender.address, RTM(10000));
    await arena.mintForTest(attackerA.address, RTM(1000));
    await arena.mintForTest(attackerB.address, RTM(1000));
    await arena.mintForTest(outsider.address, RTM(1000));
  }

  return {
    signers,
    owner,
    operator,
    defender,
    attackerA,
    attackerB,
    outsider,
    treasuryOwner,
    w,
    w2,
    // 与 arena.test.js 的旧命名保持兼容
    walletSigner: w,
    wallet2Signer: w2,
    treasury,
    arena,
    rtm
  };
}

function addressOf(walletOrAddress) {
  return typeof walletOrAddress === 'string' ? walletOrAddress : walletOrAddress.address;
}

/**
 * 由 operator 创建普通比赛；defender 自动 approve S。
 * opts: stake, duration, stakeBps, defenderSigner, wallet (signer 或 address)
 */
async function makeContest(game, opts = {}) {
  const stake = opts.stake ?? STAKE;
  const duration = opts.duration ?? DURATION;
  const stakeBps = opts.stakeBps ?? BPS;
  const defenderSigner = opts.defenderSigner ?? opts.defender ?? game.defender;
  const wallet = addressOf(opts.wallet ?? game.w);

  await game.rtm.connect(defenderSigner).approve(game.arena.target, stake);
  const tx = await game.arena
    .connect(game.operator)
    .createContest(defenderSigner.address, wallet, stake, duration, stakeBps);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ContestCreated');
  return {
    id: ev.args.id,
    end: ev.args.end,
    stake,
    duration,
    stakeBps,
    wallet,
    tx,
    receipt
  };
}

/**
 * 由 operator 创建挖矿赛。
 * opts: wallet (signer 或 address), rate, stakeBps
 */
async function makeMining(game, opts = {}) {
  const wallet = addressOf(opts.wallet ?? game.w);
  const rate = opts.rate ?? RTM(2);
  const stakeBps = opts.stakeBps ?? BPS;
  const tx = await game.arena
    .connect(game.operator)
    .createMiningContest(wallet, rate, stakeBps);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ContestCreated');
  return {
    id: ev.args.id,
    end: ev.args.end,
    rate,
    stakeBps,
    wallet,
    tx,
    receipt
  };
}

/**
 * 攻方加入：自动 approve，默认以精确应质押额作为 maxStake 滑点上限。
 * maxStake 显式传入时优先使用（用于测试滑点拒绝）。
 */
async function joinAs(game, signer, id, maxStake) {
  const info = await game.arena.contestInfo(id);
  const base = info.isMining ? await game.rtm.balanceOf(info.wallet) : info.stake;
  const expected = (base * BigInt(info.stakeBps)) / 10000n;
  const limit = maxStake === undefined ? expected : maxStake;
  await game.rtm.connect(signer).approve(game.arena.target, ethers.MaxUint256);
  return game.arena.connect(signer).join(id, limit);
}

/** 将字符串/bytes32 统一为 bytes32 消息 hash。 */
function msgHash(value) {
  if (typeof value === 'string' && ethers.isHexString(value, 32)) return value;
  return ethers.id(String(value));
}

/** 付费消息；msg 可为 bytes32 或任意标签字符串。返回 tx。 */
async function attack(game, signer, id, msg = 'msg') {
  return game.arena.connect(signer).attack(id, msgHash(msg));
}

module.exports = {
  RTM,
  HOUR,
  DAY,
  EPOCH,
  DURATION,
  STAKE,
  BPS,
  PRECISION,
  deployGame,
  makeContest,
  makeMining,
  joinAs,
  msgHash,
  attack,
  findEvent
};
