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
  const taskSink = await (await ethers.getContractFactory('TaskSink')).deploy(
    arena.target,
    rtm.target
  );
  await arena.setTaskSink(taskSink.target);

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
    rtm,
    taskSink
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
 * 由 operator 创建挖矿赛：先给全新 W 预置恰好 1 RTM（testnet mintForTest），
 * 再 createMiningContest(wallet, defenseHash)。返回 id/hash 等。
 * opts: wallet (signer 或 address), defenseHash
 */
async function makeMining(game, opts = {}) {
  const wallet = opts.wallet
    ? addressOf(opts.wallet)
    : ethers.Wallet.createRandom().address;
  const defenseHash =
    opts.defenseHash ?? ethers.hexlify(ethers.randomBytes(32));
  await game.arena.mintForTest(wallet, RTM(1));
  const tx = await game.arena
    .connect(game.operator)
    .createMiningContest(wallet, defenseHash);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ContestCreated');
  return {
    id: ev.args.id,
    end: ev.args.end,
    defenseHash,
    wallet,
    tx,
    receipt
  };
}

/**
 * 普通攻方加入：自动 approve，默认以精确应质押额作为 maxStake 滑点上限。
 * maxStake 显式传入时优先使用（用于测试滑点拒绝）；dataConsent 默认 true。
 */
async function joinAs(game, signer, id, maxStake, dataConsent = true) {
  const info = await game.arena.contestInfo(id);
  const expected = (info.stake * BigInt(info.stakeBps)) / 10000n;
  const limit = maxStake === undefined ? expected : maxStake;
  await game.rtm.connect(signer).approve(game.arena.target, ethers.MaxUint256);
  return game.arena.connect(signer).join(id, limit, dataConsent);
}

/** 矿工加入挖矿赛：无质押/无 approve，acceptData 默认 true。 */
async function joinMiningAs(game, signer, id, acceptData = true) {
  return game.arena.connect(signer).joinMining(id, acceptData);
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
  joinMiningAs,
  msgHash,
  attack,
  findEvent
};
