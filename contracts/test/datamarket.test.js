// SPDX-License-Identifier: MIT
/**
 * DataMarket 数据市场单测（任务 7）。
 *
 * 关键约束：
 * - 只有 platform operator 能 publish，且比赛必须 Ended、普通赛、root 非零、一次性；
 *   挖矿赛数据仅用于 RSI，永不发布；
 * - 价格与身份全部以 Arena 为准：buyOwn 用 S × dataPriceBps，
 *   buyFromAttacker 用全局 attackerDataPrice，买家不能传 stake；
 * - 只有 defender 能购买；攻方数据以 Arena.dataConsent（join 时一次性同意）
 *   为唯一事实源，不存在 approveSale/逐买家授权；
 * - 每份数据每人一次性；成交 70% Treasury / 30% 数据提供方。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');
const { time } = require('@nomicfoundation/hardhat-network-helpers');
const { deployGame, makeContest, makeMining, joinAs, RTM } = require('./arena.helpers');

const ROOT = ethers.id('dataset-root');
const ROOT2 = ethers.id('dataset-root-2');

describe('DataMarket 数据市场', function () {
  let game;
  let market;

  beforeEach(async function () {
    game = await deployGame();
    const DataMarket = await ethers.getContractFactory('DataMarket');
    market = await DataMarket.deploy(
      game.owner.address,
      game.rtm.target,
      game.arena.target,
      game.treasury.target
    );
    await market.connect(game.owner).setOperator(game.operator.address);
  });

  /** 建一场已结束的普通比赛，并让 attacker 注册为攻方（dataConsent 默认 true）。 */
  async function createEndedContest({ wallet, attacker = game.attackerA, dataConsent = true } = {}) {
    const contest = wallet ? await makeContest(game, { wallet }) : await makeContest(game);
    await joinAs(game, attacker, contest.id, undefined, dataConsent);
    await time.increaseTo(contest.end);
    await game.arena.expire(contest.id);
    return contest;
  }

  it('固定参数：platformShareBps = 7000；operator 可发布已结束比赛的数据根；无 approveSale 路径', async function () {
    expect(await market.platformShareBps()).to.equal(7000n);
    expect(market.approveSale).to.equal(undefined);
    expect(market.saleApproved).to.equal(undefined);

    const contest = await createEndedContest();
    await expect(market.connect(game.operator).publish(contest.id, ROOT))
      .to.emit(market, 'DatasetPublished')
      .withArgs(contest.id, ROOT);
    expect(await market.datasetRoot(contest.id)).to.equal(ROOT);
  });

  it('守方买己方数据：价格=10%×S，Treasury 70%、守方净付 70%，重复已购', async function () {
    const contest = await createEndedContest();
    await market.connect(game.operator).publish(contest.id, ROOT);

    const price = (contest.stake * 1000n) / 10000n;
    expect(price).to.equal(RTM(10));
    const platformCut = (price * 7000n) / 10000n;

    await game.rtm.connect(game.defender).approve(market.target, price);
    const defenderBefore = await game.rtm.balanceOf(game.defender.address);
    const treasuryBefore = await game.rtm.balanceOf(game.treasury.target);

    await expect(market.connect(game.defender).buyOwn(contest.id))
      .to.emit(market, 'DataSold')
      .withArgs(
        game.defender.address,
        game.defender.address,
        contest.id,
        price,
        platformCut
      );

    // 守方既是买家又是卖家：先付 price，30% 退回，净付 70%。
    expect(await game.rtm.balanceOf(game.defender.address))
      .to.equal(defenderBefore - platformCut);
    expect(await game.rtm.balanceOf(game.treasury.target))
      .to.equal(treasuryBefore + platformCut);
    expect(await game.rtm.balanceOf(market.target)).to.equal(0n);
    expect(await market.boughtOwn(contest.id, game.defender.address)).to.equal(true);

    await expect(market.connect(game.defender).buyOwn(contest.id))
      .to.be.revertedWithCustomError(market, 'AlreadyBought');
  });

  it('攻方数据：join 时 dataConsent=true 即可直接购买（无 approveSale），70/30 分账且一次性', async function () {
    const contest = await createEndedContest();
    await market.connect(game.operator).publish(contest.id, ROOT);
    expect(await game.arena.dataConsent(contest.id, game.attackerA.address)).to.equal(true);

    const price = await market.attackerDataPrice();
    expect(price).to.equal(RTM(1));
    const platformCut = (price * 7000n) / 10000n;

    await game.rtm.connect(game.defender).approve(market.target, price);
    const defenderBefore = await game.rtm.balanceOf(game.defender.address);
    const attackerBefore = await game.rtm.balanceOf(game.attackerA.address);
    const treasuryBefore = await game.rtm.balanceOf(game.treasury.target);

    await expect(
      market.connect(game.defender).buyFromAttacker(contest.id, game.attackerA.address)
    )
      .to.emit(market, 'DataSold')
      .withArgs(
        game.defender.address,
        game.attackerA.address,
        contest.id,
        price,
        platformCut
      );

    expect(await game.rtm.balanceOf(game.defender.address)).to.equal(defenderBefore - price);
    expect(await game.rtm.balanceOf(game.attackerA.address)).to.equal(attackerBefore + price - platformCut);
    expect(await game.rtm.balanceOf(game.treasury.target)).to.equal(treasuryBefore + platformCut);
    expect(
      await market.boughtAttacker(contest.id, game.attackerA.address, game.defender.address)
    ).to.equal(true);

    await expect(
      market.connect(game.defender).buyFromAttacker(contest.id, game.attackerA.address)
    ).to.be.revertedWithCustomError(market, 'AlreadyBought');
  });

  it('攻方数据：join 时 dataConsent=false -> NotConsented', async function () {
    const contest = await createEndedContest({ dataConsent: false });
    await market.connect(game.operator).publish(contest.id, ROOT);
    expect(await game.arena.dataConsent(contest.id, game.attackerA.address)).to.equal(false);

    await expect(
      market.connect(game.defender).buyFromAttacker(contest.id, game.attackerA.address)
    ).to.be.revertedWithCustomError(market, 'NotConsented');
    expect(
      await market.boughtAttacker(contest.id, game.attackerA.address, game.defender.address)
    ).to.equal(false);
  });

  it('非 defender 调 buyOwn/buyFromAttacker -> NotDefender', async function () {
    const contest = await createEndedContest();
    await market.connect(game.operator).publish(contest.id, ROOT);

    await expect(market.connect(game.attackerB).buyOwn(contest.id))
      .to.be.revertedWithCustomError(market, 'NotDefender');
    await expect(
      market.connect(game.attackerB).buyFromAttacker(contest.id, game.attackerA.address)
    ).to.be.revertedWithCustomError(market, 'NotDefender');
  });

  it('buyFromAttacker：未在该场注册的攻方 -> NotAttacker', async function () {
    const contest = await createEndedContest();
    await market.connect(game.operator).publish(contest.id, ROOT);

    // attackerB 未加入本场，即使 root 已发布也必须拒绝。
    await expect(
      market.connect(game.defender).buyFromAttacker(contest.id, game.attackerB.address)
    ).to.be.revertedWithCustomError(market, 'NotAttacker');
  });

  it('publish：非 operator、未结束、零 root、重复发布均拒绝', async function () {
    const live = await makeContest(game, { wallet: game.w2 });
    await expect(market.connect(game.defender).publish(live.id, ROOT))
      .to.be.revertedWithCustomError(market, 'NotOperator');
    await expect(market.connect(game.operator).publish(live.id, ROOT))
      .to.be.revertedWithCustomError(market, 'NotEnded');

    const ended = await createEndedContest();
    await expect(market.connect(game.operator).publish(ended.id, ethers.ZeroHash))
      .to.be.revertedWithCustomError(market, 'ZeroRoot');
    await market.connect(game.operator).publish(ended.id, ROOT);
    await expect(market.connect(game.operator).publish(ended.id, ROOT2))
      .to.be.revertedWithCustomError(market, 'AlreadyPublished');
  });

  it('publish：挖矿赛即使已结束（state=2）也拒绝 -> NotNormalContest', async function () {
    const mining = await makeMining(game);
    // 退役后 state=Ended，但仍是挖矿赛；数据仅用于 RSI，不得发布。
    await game.arena.connect(game.operator).retireMining(mining.id);
    const info = await game.arena.contestInfo(mining.id);
    expect(info.state).to.equal(2n);
    expect(info.isMining).to.equal(true);

    await expect(market.connect(game.operator).publish(mining.id, ROOT))
      .to.be.revertedWithCustomError(market, 'NotNormalContest');
    expect(await market.datasetRoot(mining.id)).to.equal(ethers.ZeroHash);
  });

  it('setOperator：非 owner 拒绝、零地址拒绝、轮换后权限随之转移', async function () {
    await expect(market.connect(game.outsider).setOperator(game.outsider.address))
      .to.be.revertedWithCustomError(market, 'OwnableUnauthorizedAccount');
    await expect(market.connect(game.owner).setOperator(ethers.ZeroAddress))
      .to.be.revertedWithCustomError(market, 'ZeroAddress');

    const previous = await market.operator();
    await expect(market.connect(game.owner).setOperator(game.outsider.address))
      .to.emit(market, 'OperatorUpdated')
      .withArgs(previous, game.outsider.address);
    expect(await market.operator()).to.equal(game.outsider.address);

    const contest = await createEndedContest();
    await expect(market.connect(game.operator).publish(contest.id, ROOT))
      .to.be.revertedWithCustomError(market, 'NotOperator');
    await expect(market.connect(game.outsider).publish(contest.id, ROOT))
      .to.emit(market, 'DatasetPublished')
      .withArgs(contest.id, ROOT);
  });

  it('价格参数：越界拒绝；owner 更新后 dataPriceBps/attackerDataPrice 生效', async function () {
    await expect(market.connect(game.outsider).setDataPriceBps(2000))
      .to.be.revertedWithCustomError(market, 'OwnableUnauthorizedAccount');
    await expect(market.connect(game.owner).setDataPriceBps(10001))
      .to.be.revertedWithCustomError(market, 'BadParams');
    await expect(market.connect(game.owner).setAttackerDataPrice(0))
      .to.be.revertedWithCustomError(market, 'BadParams');

    await expect(market.connect(game.owner).setDataPriceBps(2000))
      .to.emit(market, 'DataPriceUpdated')
      .withArgs(2000);
    await expect(market.connect(game.owner).setAttackerDataPrice(RTM(2)))
      .to.emit(market, 'AttackerDataPriceUpdated')
      .withArgs(RTM(2));

    const contest = await createEndedContest();
    await market.connect(game.operator).publish(contest.id, ROOT);

    // buyOwn 使用更新后的 20% × S。
    const ownPrice = (contest.stake * 2000n) / 10000n;
    expect(ownPrice).to.equal(RTM(20));
    await game.rtm.connect(game.defender).approve(market.target, ownPrice);
    const treasuryBefore = await game.rtm.balanceOf(game.treasury.target);
    await expect(market.connect(game.defender).buyOwn(contest.id))
      .to.emit(market, 'DataSold')
      .withArgs(
        game.defender.address,
        game.defender.address,
        contest.id,
        ownPrice,
        (ownPrice * 7000n) / 10000n
      );
    expect(await game.rtm.balanceOf(game.treasury.target))
      .to.equal(treasuryBefore + (ownPrice * 7000n) / 10000n);

    // buyFromAttacker 使用更新后的 2 RTM（attacker 已在 join 时同意）。
    await game.rtm.connect(game.defender).approve(market.target, RTM(2));
    const attackerBefore = await game.rtm.balanceOf(game.attackerA.address);
    await expect(
      market.connect(game.defender).buyFromAttacker(contest.id, game.attackerA.address)
    )
      .to.emit(market, 'DataSold')
      .withArgs(
        game.defender.address,
        game.attackerA.address,
        contest.id,
        RTM(2),
        (RTM(2) * 7000n) / 10000n
      );
    expect(await game.rtm.balanceOf(game.attackerA.address))
      .to.equal(attackerBefore + (RTM(2) * 3000n) / 10000n);
  });
});
