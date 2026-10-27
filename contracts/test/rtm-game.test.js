// SPDX-License-Identifier: MIT
/**
 * RTMToken 靶钱包转账策略单测（任务 3）。
 *
 * 本文件在任务 3 只验证代币层策略；任务 4 会用真 Arena 替换 ArenaStub，
 * 并在本文件扩展比赛生命周期端到端用例。
 */
const { expect } = require('chai');
const { ethers } = require('hardhat');

const RTM = (n) => ethers.parseEther(String(n));

describe('RTMToken 靶钱包转账策略', function () {
  let owner, defender, attacker, outsider, bystander;
  let stub, rtm;
  let contestId;

  beforeEach(async () => {
    [owner, defender, attacker, outsider, bystander] = await ethers.getSigners();
    stub = await (await ethers.getContractFactory('ArenaStub')).deploy();
    rtm = await (await ethers.getContractFactory('RTMToken')).deploy(owner.address, stub.target);
    contestId = ethers.id('contest-1');
  });

  it('无靶注册时是普通 ERC-20：转账与授权不受限', async () => {
    await stub.mint(rtm.target, owner.address, RTM(100));
    expect(await rtm.isTarget(owner.address)).to.equal(false);

    await expect(rtm.connect(owner).transfer(bystander.address, RTM(40)))
      .to.emit(rtm, 'Transfer')
      .withArgs(owner.address, bystander.address, RTM(40));
    await rtm.connect(owner).approve(outsider.address, RTM(25));
    expect(await rtm.allowance(owner.address, outsider.address)).to.equal(RTM(25));
    await rtm.connect(outsider).transferFrom(owner.address, bystander.address, RTM(25));

    expect(await rtm.balanceOf(bystander.address)).to.equal(RTM(65));
    expect(await rtm.balanceOf(owner.address)).to.equal(RTM(35));
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('活跃靶转 outsider 或未登记攻方都 revert TargetTransferRestricted', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await expect(stub.registerTarget(rtm.target, defender.address, contestId))
      .to.emit(rtm, 'TargetRegistered')
      .withArgs(defender.address, contestId);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.targetContest(defender.address)).to.equal(contestId);

    await expect(rtm.connect(defender).transfer(outsider.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, outsider.address);

    // 攻方必须登记在"本场"比赛：登记在另一场不算。
    await stub.setAttacker(ethers.id('contest-2'), attacker.address, true);
    await expect(rtm.connect(defender).transfer(attacker.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, attacker.address);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('allowance 不构成靶的转出出口：transferFrom 仍 revert', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);
    await rtm.connect(defender).approve(outsider.address, RTM(30));
    expect(await rtm.allowance(defender.address, outsider.address)).to.equal(RTM(30));

    await expect(rtm.connect(outsider).transferFrom(defender.address, outsider.address, RTM(10)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, outsider.address);

    expect(await rtm.allowance(defender.address, outsider.address)).to.equal(RTM(30));
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(outsider.address)).to.equal(0n);
    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('不同比赛的靶钱包之间互转 revert（靶转靶不是合法出口）', async () => {
    const contestB = ethers.id('contest-2');
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.mint(rtm.target, bystander.address, RTM(50));
    await stub.registerTarget(rtm.target, defender.address, contestId);
    await stub.registerTarget(rtm.target, bystander.address, contestB);

    // 收款方即使是另一场的靶，也不是本场注册攻方，不能作为出口。
    await expect(rtm.connect(defender).transfer(bystander.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, bystander.address);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.isTarget(bystander.address)).to.equal(true);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(bystander.address)).to.equal(RTM(50));
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('registerTarget 拒绝 bytes32(0) 的 contestId', async () => {
    await expect(stub.registerTarget(rtm.target, defender.address, ethers.ZeroHash))
      .to.be.revertedWithCustomError(rtm, 'InvalidContestId');
    expect(await rtm.isTarget(defender.address)).to.equal(false);
  });

  it('靶向已登记攻方转账即攻破：到账、注销、Breach 事件与 onBreach 回调各一次', async () => {
    await stub.setAttacker(contestId, attacker.address, true);
    await stub.registerTarget(rtm.target, defender.address, contestId);
    // 注册后转入靶钱包不受限。
    await stub.mint(rtm.target, defender.address, RTM(100));

    const tx = await rtm.connect(defender).transfer(attacker.address, RTM(30));
    await expect(tx)
      .to.emit(rtm, 'TargetUnregistered')
      .withArgs(defender.address, contestId);
    await expect(tx)
      .to.emit(rtm, 'Breach')
      .withArgs(contestId, attacker.address, RTM(30));

    expect(await rtm.balanceOf(attacker.address)).to.equal(RTM(30));
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(70));
    expect(await rtm.isTarget(defender.address)).to.equal(false);
    expect(await rtm.targetContest(defender.address)).to.equal(ethers.ZeroHash);
    expect(await stub.lastBreachContest()).to.equal(contestId);
    expect(await stub.lastBreachWinner()).to.equal(attacker.address);
    expect(await stub.breachCalls()).to.equal(1n);
  });

  it('靶向任何地址（含已登记攻方）转账零金额都 revert，不触发攻破', async () => {
    await stub.setAttacker(contestId, attacker.address, true);
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);

    await expect(rtm.connect(defender).transfer(attacker.address, 0))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, attacker.address);
    await expect(rtm.connect(defender).transfer(outsider.address, 0))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, outsider.address);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.targetContest(defender.address)).to.equal(contestId);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(attacker.address)).to.equal(0n);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('onBreach 回调 revert 时整笔交易回滚，靶保持注册', async () => {
    await stub.setAttacker(contestId, attacker.address, true);
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);
    await stub.setRevertOnBreach(true);

    await expect(rtm.connect(defender).transfer(attacker.address, RTM(10)))
      .to.be.revertedWith('ArenaStub: breach reverted');

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.targetContest(defender.address)).to.equal(contestId);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(attacker.address)).to.equal(0n);
    expect(await stub.breachCalls()).to.equal(0n);
    expect(await stub.lastBreachWinner()).to.equal(ethers.ZeroAddress);
  });

  it('靶直接向 Arena 地址转账也 revert（不能绕过 controllerTransfer）', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);

    await expect(rtm.connect(defender).transfer(stub.target, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, stub.target);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(stub.target)).to.equal(0n);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('Arena 即使被误登记为该场攻方，也永远不是靶的合法收款方', async () => {
    await stub.setAttacker(contestId, stub.target, true);
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);

    await expect(rtm.connect(defender).transfer(stub.target, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'TargetTransferRestricted')
      .withArgs(defender.address, stub.target);

    expect(await rtm.isTarget(defender.address)).to.equal(true);
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(100));
    expect(await rtm.balanceOf(stub.target)).to.equal(0n);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('controllerTransfer 无需 allowance 即可划转、注销靶且不触发攻破', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);
    expect(await rtm.allowance(defender.address, stub.target)).to.equal(0n);

    const tx = await stub.controllerSend(rtm.target, defender.address, outsider.address, RTM(40));
    await expect(tx)
      .to.emit(rtm, 'TargetUnregistered')
      .withArgs(defender.address, contestId);
    await expect(tx).to.not.emit(rtm, 'Breach');

    expect(await rtm.balanceOf(outsider.address)).to.equal(RTM(40));
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(60));
    expect(await rtm.isTarget(defender.address)).to.equal(false);
    expect(await rtm.allowance(defender.address, stub.target)).to.equal(0n);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('controllerTransfer 拒绝零地址 from，不能借 OZ mint 路径绕过 MiningMinted', async () => {
    await stub.mint(rtm.target, owner.address, RTM(5));
    const supplyBefore = await rtm.totalSupply();

    await expect(stub.controllerSend(rtm.target, ethers.ZeroAddress, outsider.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'ZeroAddress');

    expect(await rtm.totalSupply()).to.equal(supplyBefore);
    expect(await rtm.balanceOf(outsider.address)).to.equal(0n);
  });

  it('controllerTransfer 划转给已登记攻方不触发 onBreach，但仍注销靶', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);
    await stub.setAttacker(contestId, attacker.address, true);

    const tx = await stub.controllerSend(rtm.target, defender.address, attacker.address, RTM(40));
    await expect(tx)
      .to.emit(rtm, 'TargetUnregistered')
      .withArgs(defender.address, contestId);
    await expect(tx).to.not.emit(rtm, 'Breach');

    expect(await rtm.balanceOf(attacker.address)).to.equal(RTM(40));
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(60));
    expect(await rtm.isTarget(defender.address)).to.equal(false);
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('注销后靶恢复普通钱包，可向任意第三方转账', async () => {
    await stub.mint(rtm.target, defender.address, RTM(100));
    await stub.registerTarget(rtm.target, defender.address, contestId);

    await expect(stub.unregisterTarget(rtm.target, defender.address))
      .to.emit(rtm, 'TargetUnregistered')
      .withArgs(defender.address, contestId);
    expect(await rtm.isTarget(defender.address)).to.equal(false);

    await expect(rtm.connect(defender).transfer(outsider.address, RTM(10)))
      .to.emit(rtm, 'Transfer')
      .withArgs(defender.address, outsider.address, RTM(10));
    expect(await rtm.balanceOf(outsider.address)).to.equal(RTM(10));
    expect(await rtm.balanceOf(defender.address)).to.equal(RTM(90));
    expect(await stub.breachCalls()).to.equal(0n);
  });

  it('仅 Arena 可铸币、注册/注销靶与控制器划转', async () => {
    await expect(rtm.connect(owner).mint(owner.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'NotMinter');
    await expect(rtm.connect(owner).registerTarget(defender.address, contestId))
      .to.be.revertedWithCustomError(rtm, 'NotArena');
    await expect(rtm.connect(owner).unregisterTarget(defender.address))
      .to.be.revertedWithCustomError(rtm, 'NotArena');
    await expect(rtm.connect(owner).controllerTransfer(defender.address, outsider.address, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'NotArena');
  });

  it('mint 发出 MiningMinted 事件并增加总供给', async () => {
    await expect(stub.mint(rtm.target, outsider.address, RTM(12)))
      .to.emit(rtm, 'MiningMinted')
      .withArgs(outsider.address, RTM(12));

    expect(await rtm.balanceOf(outsider.address)).to.equal(RTM(12));
    expect(await rtm.totalSupply()).to.equal(RTM(12));
  });

  it('minter 侧参数校验：拒绝零地址与零金额', async () => {
    await expect(stub.mint(rtm.target, ethers.ZeroAddress, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
    await expect(stub.mint(rtm.target, attacker.address, 0))
      .to.be.revertedWithCustomError(rtm, 'ZeroAmount');
    await expect(stub.registerTarget(rtm.target, ethers.ZeroAddress, contestId))
      .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
    await expect(stub.controllerSend(rtm.target, defender.address, ethers.ZeroAddress, RTM(1)))
      .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
  });

  it('构造器：无预铸、元数据正确、绑定 Arena 为 minter', async () => {
    expect(await rtm.totalSupply()).to.equal(0n);
    expect(await rtm.name()).to.equal('REDTEAM');
    expect(await rtm.symbol()).to.equal('RTM');
    expect(await rtm.minter()).to.equal(stub.target);
    expect(await rtm.arena()).to.equal(stub.target);
    expect(await rtm.owner()).to.equal(owner.address);
  });

  it('构造器拒绝零地址与无代码 minter', async () => {
    const Factory = await ethers.getContractFactory('RTMToken');
    await expect(Factory.deploy(owner.address, ethers.ZeroAddress))
      .to.be.revertedWithCustomError(rtm, 'ZeroAddress');
    await expect(Factory.deploy(owner.address, outsider.address))
      .to.be.revertedWithCustomError(rtm, 'InvalidMinter');
  });
});
