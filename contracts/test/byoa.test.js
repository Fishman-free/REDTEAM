// SPDX-License-Identifier: MIT
/**
 * BYOA 合约测试：EIP-712 创建、TaskSink 精确匹配、过期、结算、replyHash。
 *
 * 覆盖规格 §10：
 * - createByoaContest 必须同时通过守方委托签名与 TEE 钱包绑定签名；
 * - 任务完成判定在 RTMToken._update 中原子发生，一笔转账只消费一个任务；
 * - TaskSink 资金在结算时退回守方；
 * - BYOA 的 markDelivered 必须携带 replyHash。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');

const {
  RTM,
  HOUR,
  DURATION,
  STAKE,
  BPS,
  deployGame,
  makeContest,
  joinAs,
  msgHash,
  findEvent
} = require('./arena.helpers');

const ATTESTATION_SIMULATED = 0;
const MANDATE_TYPES = {
  ByoaMandate: [
    { name: 'defender', type: 'address' },
    { name: 'wallet', type: 'address' },
    { name: 'teeSigner', type: 'address' },
    { name: 'stake', type: 'uint256' },
    { name: 'duration', type: 'uint64' },
    { name: 'stakeBps', type: 'uint32' },
    { name: 'configCommitment', type: 'bytes32' },
    { name: 'runtimeMeasurement', type: 'bytes32' },
    { name: 'teePubKey', type: 'bytes32' },
    { name: 'attestationTier', type: 'uint8' },
    { name: 'defenderDataConsent', type: 'bool' },
    { name: 'utilityMissThreshold', type: 'uint16' },
    { name: 'utilityPenaltyBps', type: 'uint16' },
    { name: 'nonce', type: 'uint64' },
    { name: 'deadline', type: 'uint64' }
  ]
};
const BINDING_TYPES = {
  TeeWalletBinding: [
    { name: 'defender', type: 'address' },
    { name: 'wallet', type: 'address' },
    { name: 'configCommitment', type: 'bytes32' },
    { name: 'runtimeMeasurement', type: 'bytes32' },
    { name: 'teePubKey', type: 'bytes32' },
    { name: 'nonce', type: 'uint64' },
    { name: 'deadline', type: 'uint64' }
  ]
};

async function domainFor(game) {
  const network = await ethers.provider.getNetwork();
  return {
    name: 'RTM Arena',
    version: '1',
    chainId: network.chainId,
    verifyingContract: game.arena.target
  };
}

async function byoaMessage(game, overrides = {}) {
  const now = BigInt(await time.latest());
  const teeSigner = overrides.teeSigner ?? game.signers[7];
  const message = {
    defender: game.defender.address,
    wallet: overrides.wallet ?? game.w.address,
    teeSigner: teeSigner.address,
    stake: overrides.stake ?? STAKE,
    duration: overrides.duration ?? DURATION,
    stakeBps: overrides.stakeBps ?? BPS,
    configCommitment: overrides.configCommitment ?? ethers.id('config-v1'),
    runtimeMeasurement: overrides.runtimeMeasurement ?? ethers.id('measurement-v1'),
    teePubKey: overrides.teePubKey ?? ethers.id('tee-pubkey-v1'),
    attestationTier: overrides.attestationTier ?? ATTESTATION_SIMULATED,
    defenderDataConsent: overrides.defenderDataConsent ?? false,
    utilityMissThreshold: overrides.utilityMissThreshold ?? 0,
    utilityPenaltyBps: overrides.utilityPenaltyBps ?? 1000,
    nonce: overrides.nonce ?? (await game.arena.byoaNonce(game.defender.address)),
    deadline: overrides.deadline ?? now + 3600n
  };
  return { message, teeSigner };
}

async function signByoa(game, overrides = {}) {
  const { message, teeSigner } = await byoaMessage(game, overrides);
  const domain = await domainFor(game);
  const defenderSignature = await game.defender.signTypedData(
    domain,
    MANDATE_TYPES,
    message
  );
  const teeMessage = {
    defender: message.defender,
    wallet: message.wallet,
    configCommitment: message.configCommitment,
    runtimeMeasurement: message.runtimeMeasurement,
    teePubKey: message.teePubKey,
    nonce: message.nonce,
    deadline: message.deadline
  };
  const teeSignature = await teeSigner.signTypedData(
    domain,
    BINDING_TYPES,
    teeMessage
  );
  return { message, defenderSignature, teeSignature };
}

async function createByoa(game, overrides = {}) {
  const signed = await signByoa(game, overrides);
  await game.rtm
    .connect(game.defender)
    .approve(game.arena.target, signed.message.stake);
  const tx = await game.arena
    .connect(game.operator)
    .createByoaContest(signed.message, signed.defenderSignature, signed.teeSignature);
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.arena, 'ByoaContestCreated');
  return { ...signed, id: ev.args.id, receipt };
}

async function issueTask(game, id, amount, deadline, label, signer) {
  const tx = await game.taskSink
    .connect(signer ?? game.operator)
    .issueTask(id, amount, deadline, ethers.id(label));
  const receipt = await tx.wait();
  const ev = findEvent(receipt, game.taskSink, 'TaskIssued');
  return { taskId: ev.args.taskId, receipt };
}

describe('BYOA contracts', function () {
  beforeEach(async function () {
    this.game = await deployGame();
  });

  describe('createByoaContest', function () {
    it('records signed runtime metadata and registers W', async function () {
      const game = this.game;
      const created = await createByoa(game);

      const info = await game.arena.contestInfo(created.id);
      expect(info.isByoa).to.equal(true);
      expect(info.defender).to.equal(game.defender.address);
      expect(info.wallet).to.equal(game.w.address);
      expect(info.defenseHash).to.equal(created.message.configCommitment);

      const byoa = await game.arena.byoaContestInfo(created.id);
      expect(byoa.isByoa).to.equal(true);
      expect(byoa.teeSigner).to.equal(created.message.teeSigner);
      expect(byoa.teePubKey).to.equal(created.message.teePubKey);
      expect(byoa.runtimeMeasurement).to.equal(created.message.runtimeMeasurement);
      expect(byoa.attestationTier).to.equal(ATTESTATION_SIMULATED);
      expect(byoa.defenderDataConsent).to.equal(false);

      expect(await game.rtm.targetContest(game.w.address)).to.equal(created.id);
      expect(await game.rtm.balanceOf(game.w.address)).to.equal(STAKE);
      expect(await game.arena.byoaNonce(game.defender.address)).to.equal(1n);
    });

    it('rejects a forged defender signature', async function () {
      const game = this.game;
      const { message } = await signByoa(game);
      const domain = await domainFor(game);
      const forged = await game.attackerA.signTypedData(
        domain,
        MANDATE_TYPES,
        message
      );
      const { teeSignature } = await signByoa(game);
      await game.rtm.connect(game.defender).approve(game.arena.target, STAKE);
      await expect(
        game.arena
          .connect(game.operator)
          .createByoaContest(message, forged, teeSignature)
      ).to.be.revertedWithCustomError(game.arena, 'BadSignature');
    });

    it('rejects a forged TEE wallet binding', async function () {
      const game = this.game;
      const { message, defenderSignature } = await signByoa(game);
      const domain = await domainFor(game);
      const forged = await game.attackerA.signTypedData(
        domain,
        BINDING_TYPES,
        {
          defender: message.defender,
          wallet: message.wallet,
          configCommitment: message.configCommitment,
          runtimeMeasurement: message.runtimeMeasurement,
          teePubKey: message.teePubKey,
          nonce: message.nonce,
          deadline: message.deadline
        }
      );
      await game.rtm.connect(game.defender).approve(game.arena.target, STAKE);
      await expect(
        game.arena
          .connect(game.operator)
          .createByoaContest(message, defenderSignature, forged)
      ).to.be.revertedWithCustomError(game.arena, 'BadSignature');
    });

    it('rejects expired mandates and wrong nonces', async function () {
      const game = this.game;
      const past = BigInt(await time.latest()) - 1n;
      const expired = await signByoa(game, { deadline: past });
      await game.rtm.connect(game.defender).approve(game.arena.target, STAKE);
      await expect(
        game.arena
          .connect(game.operator)
          .createByoaContest(
            expired.message,
            expired.defenderSignature,
            expired.teeSignature
          )
      ).to.be.revertedWithCustomError(game.arena, 'SignatureExpired');

      const wrong = await signByoa(game, { nonce: 1n });
      await expect(
        game.arena
          .connect(game.operator)
          .createByoaContest(wrong.message, wrong.defenderSignature, wrong.teeSignature)
      ).to.be.revertedWithCustomError(game.arena, 'BadNonce');
    });

    it('blocks replay after a successful creation', async function () {
      const game = this.game;
      const created = await createByoa(game);
      await expect(
        game.arena
          .connect(game.operator)
          .createByoaContest(
            created.message,
            created.defenderSignature,
            created.teeSignature
          )
      ).to.be.revertedWithCustomError(game.arena, 'BadNonce');
    });

    it('is operator-only and requires the TaskSink wiring', async function () {
      const game = this.game;
      const signed = await signByoa(game);
      await game.rtm.connect(game.defender).approve(game.arena.target, STAKE);
      await expect(
        game.arena
          .connect(game.attackerA)
          .createByoaContest(
            signed.message,
            signed.defenderSignature,
            signed.teeSignature
          )
      ).to.be.revertedWithCustomError(game.arena, 'NotOperator');
    });
  });

  describe('TaskSink', function () {
    it('consumes exactly one earliest-deadline task per transfer', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;
      const later = await issueTask(game, created.id, RTM(5), end - 100n, 'later');
      const sooner = await issueTask(game, created.id, RTM(5), end - 1000n, 'sooner');

      const tx = await game.rtm
        .connect(game.w)
        .transfer(game.taskSink.target, RTM(5));
      const receipt = await tx.wait();
      const completed = findEvent(receipt, game.taskSink, 'TaskCompleted');
      expect(completed.args.taskId).to.equal(sooner.taskId);

      const soonerInfo = await game.taskSink.taskInfo(created.id, sooner.taskId);
      expect(soonerInfo.completed).to.equal(true);
      expect(soonerInfo.open).to.equal(false);
      const laterInfo = await game.taskSink.taskInfo(created.id, later.taskId);
      expect(laterInfo.open).to.equal(true);

      expect(await game.taskSink.openTaskCount(created.id)).to.equal(1n);
      expect(await game.taskSink.held(created.id)).to.equal(RTM(5));
      expect(await game.rtm.balanceOf(game.taskSink.target)).to.equal(RTM(5));
    });

    it('rejects wrong amounts and transfers without an open task', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;
      await issueTask(game, created.id, RTM(5), end - 100n, 'only-task');

      await expect(
        game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(4))
      ).to.be.revertedWithCustomError(game.rtm, 'TargetTransferRestricted');

      await game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(5));
      await expect(
        game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(5))
      ).to.be.revertedWithCustomError(game.rtm, 'TargetTransferRestricted');
    });

    it('only lets the operator or the contest TEE signer issue tasks', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;

      await expect(
        issueTask(game, created.id, RTM(1), end - 100n, 'outsider', game.outsider)
      ).to.be.revertedWithCustomError(game.taskSink, 'NotIssuer');

      await issueTask(
        game,
        created.id,
        RTM(1),
        end - 100n,
        'tee-task',
        game.signers[7]
      );
      expect(await game.taskSink.openTaskCount(created.id)).to.equal(1n);
    });

    it('expires tasks publicly and counts misses', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;
      const deadline = BigInt(await time.latest()) + 60n;
      const task = await issueTask(game, created.id, RTM(2), deadline, 'expire-me');

      await time.increase(61);
      const tx = await game.taskSink
        .connect(game.outsider)
        .expireTask(created.id, task.taskId);
      const receipt = await tx.wait();
      findEvent(receipt, game.taskSink, 'TaskExpired');

      expect(await game.taskSink.expiredTaskCount(created.id)).to.equal(1n);
      expect(await game.taskSink.openTaskCount(created.id)).to.equal(0n);
      await expect(
        game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(2))
      ).to.be.revertedWithCustomError(game.rtm, 'TargetTransferRestricted');
      expect(end).to.be.greaterThan(deadline);
    });

    it('returns held task funds to the defender on expiry', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;
      await issueTask(game, created.id, RTM(10), end - 100n, 'paid');
      await game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(10));

      const before = await game.rtm.balanceOf(game.defender.address);
      await time.increaseTo(end);
      await game.arena.connect(game.outsider).expire(created.id);
      const after = await game.rtm.balanceOf(game.defender.address);

      expect(after - before).to.equal(STAKE);
      expect(await game.taskSink.held(created.id)).to.equal(0n);
      expect(await game.rtm.balanceOf(game.taskSink.target)).to.equal(0n);
    });

    it('returns held task funds to the defender on breach', async function () {
      const game = this.game;
      const created = await createByoa(game);
      const end = (await game.arena.contestInfo(created.id)).end;
      await joinAs(game, game.attackerA, created.id);
      await issueTask(game, created.id, RTM(10), end - 100n, 'breach-paid');
      await game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(10));

      const defenderBefore = await game.rtm.balanceOf(game.defender.address);
      const attackerBefore = await game.rtm.balanceOf(game.attackerA.address);

      await game.rtm.connect(game.w).transfer(game.attackerA.address, RTM(90));

      expect(
        (await game.rtm.balanceOf(game.defender.address)) - defenderBefore
      ).to.equal(RTM(10));
      expect(
        (await game.rtm.balanceOf(game.attackerA.address)) - attackerBefore
      ).to.equal(RTM(90));
      expect(await game.arena.contestState(created.id)).to.equal(2n);
    });

    it('rejects target transfers to the sink in non-BYOA contests', async function () {
      const game = this.game;
      await makeContest(game);
      await expect(
        game.rtm.connect(game.w).transfer(game.taskSink.target, RTM(1))
      ).to.be.revertedWithCustomError(game.rtm, 'TargetTransferRestricted');
    });

    it('penalizes a utility breach on-chain', async function () {
      const game = this.game;
      const created = await createByoa(game, {
        utilityMissThreshold: 0,
        utilityPenaltyBps: 1000
      });
      const end = (await game.arena.contestInfo(created.id)).end;
      const deadline = BigInt(await time.latest()) + 60n;
      const task = await issueTask(
        game,
        created.id,
        RTM(2),
        deadline,
        'missed-invoice'
      );
      await time.increase(61);
      await game.taskSink
        .connect(game.outsider)
        .expireTask(created.id, task.taskId);

      const treasuryBefore = await game.rtm.balanceOf(game.treasury.target);
      const defenderBefore = await game.rtm.balanceOf(game.defender.address);

      await expect(
        game.arena.connect(game.operator).reportByoaUtilityBreach(created.id)
      )
        .to.emit(game.arena, 'ByoaUtilityBreach')
        .withArgs(created.id, 1n, RTM(10));

      expect(await game.arena.contestState(created.id)).to.equal(2n);
      expect(
        (await game.rtm.balanceOf(game.defender.address)) - defenderBefore
      ).to.equal(RTM(90));
      expect(
        (await game.rtm.balanceOf(game.treasury.target)) - treasuryBefore
      ).to.equal(RTM(10));
      expect(end).to.be.greaterThan(deadline);
    });

    it('rejects a utility breach at or below the threshold', async function () {
      const game = this.game;
      const created = await createByoa(game, {
        utilityMissThreshold: 1,
        utilityPenaltyBps: 1000
      });
      await expect(
        game.arena.connect(game.operator).reportByoaUtilityBreach(created.id)
      ).to.be.revertedWithCustomError(game.arena, 'UtilitySatisfied');
    });

    it('can only be bound once', async function () {
      const game = this.game;
      await expect(
        game.arena.setTaskSink(game.taskSink.target)
      ).to.be.revertedWithCustomError(game.arena, 'TaskSinkAlreadySet');
    });
  });

  describe('replyHash', function () {
    it('requires a reply hash for BYOA deliveries and records it', async function () {
      const game = this.game;
      const created = await createByoa(game);
      await joinAs(game, game.attackerA, created.id);
      const hash = msgHash('byoa-message');
      await game.arena.connect(game.attackerA).attack(created.id, hash);

      await expect(
        game.arena
          .connect(game.operator)
          ['markDelivered(bytes32,address,bytes32)'](
            created.id,
            game.attackerA.address,
            hash
          )
      ).to.be.revertedWithCustomError(game.arena, 'ReplyHashRequired');

      const replyHash = ethers.id('encrypted-reply');
      const tx = await game.arena
        .connect(game.operator)
        ['markDelivered(bytes32,address,bytes32,bytes32)'](
          created.id,
          game.attackerA.address,
          hash,
          replyHash
        );
      const receipt = await tx.wait();
      const ev = findEvent(receipt, game.arena, 'MarkDelivered');
      expect(ev.args.replyHash).to.equal(replyHash);
      expect(
        await game.arena.replyHashOf(created.id, game.attackerA.address, hash)
      ).to.equal(replyHash);
    });

    it('keeps the legacy three-argument delivery for normal contests', async function () {
      const game = this.game;
      const { id } = await makeContest(game);
      await joinAs(game, game.attackerA, id);
      const hash = msgHash('normal-message');
      await game.arena.connect(game.attackerA).attack(id, hash);

      const tx = await game.arena
        .connect(game.operator)
        .markDelivered(id, game.attackerA.address, hash);
      const receipt = await tx.wait();
      const ev = findEvent(receipt, game.arena, 'MarkDelivered');
      expect(ev.args.replyHash).to.equal(ethers.ZeroHash);
    });
  });
});
