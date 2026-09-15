const { expect } = require('chai');
const { ethers } = require('hardhat');

describe('local Ethereum layer', function () {
  let token, pay, reward, owner, merchant, participant, outsider;
  const b = n => '0x' + n.repeat(64);

  beforeEach(async () => {
    [owner, merchant, participant, outsider] = await ethers.getSigners();
    token = await (await ethers.getContractFactory('ExperimentalToken')).deploy(ethers.parseEther('1000'));
    pay = await (await ethers.getContractFactory('PaymentAgent')).deploy(token, ethers.parseEther('100'));
    reward = await (await ethers.getContractFactory('RewardSettlement')).deploy(token, ethers.parseEther('50'));
    await pay.setAllowlisted(merchant.address, true);
    await pay.setAllowlisted(participant.address, true);
    await token.transfer(pay.target, ethers.parseEther('100'));
    await token.transfer(reward.target, ethers.parseEther('50'));
  });

  it('pays only an exact configured invoice', async () => {
    const id = b('2'); const op = b('1'); const amount = ethers.parseEther('10');
    await pay.configureInvoice(id, merchant.address, participant.address, amount);
    await expect(pay.pay(op, id, merchant.address, participant.address, amount)).to.emit(pay, 'Payment');
    expect(await token.balanceOf(participant.address)).eq(amount);
  });

  it('rejects invoice mismatches and unauthorized configuration', async () => {
    const id = b('2');
    await expect(pay.connect(outsider).configureInvoice(id, merchant.address, participant.address, 1))
      .revertedWith('not operator');
    await pay.configureInvoice(id, merchant.address, participant.address, 10);
    await expect(pay.pay(b('1'), id, merchant.address, outsider.address, 10)).revertedWith('invoice mismatch');
    await expect(pay.pay(b('3'), b('4'), merchant.address, participant.address, 1)).revertedWith('invoice mismatch');
  });

  it('settles only an exact configured reward', async () => {
    const id = b('3'); const amount = 7;
    await reward.configureSettlement(id, participant.address, amount);
    await expect(reward.settle(b('3'), participant.address, amount)).to.emit(reward, 'Reward');
    await expect(reward.settle(b('3'), participant.address, amount)).revertedWith('already settled');
  });

  it('rejects settlement outsider, zero, and mismatches', async () => {
    await expect(reward.connect(outsider).configureSettlement(b('4'), participant.address, 1))
      .revertedWith('not evaluator');
    await expect(reward.configureSettlement(b('0'), participant.address, 1)).revertedWith('zero address');
    await reward.configureSettlement(b('4'), participant.address, 1);
    await expect(reward.settle(b('4'), merchant.address, 1)).revertedWith('settlement mismatch');
    await expect(reward.settle(b('4'), participant.address, 2)).revertedWith('settlement mismatch');
  });
});
