const { expect } = require('chai');
const { ethers } = require('hardhat');

// The hardening pass added observability events to the existing contracts
// without changing their boundaries. These tests pin the new events and re-check
// that the payment path still behaves exactly as before.
describe('contract hardening events', function () {
  let token, pay, reward, owner, merchant, participant;

  beforeEach(async () => {
    [owner, merchant, participant] = await ethers.getSigners();
    token = await (await ethers.getContractFactory('ExperimentalToken')).deploy(ethers.parseEther('1000'));
    pay = await (await ethers.getContractFactory('PaymentAgent')).deploy(token, ethers.parseEther('100'));
    reward = await (await ethers.getContractFactory('RewardSettlement')).deploy(token, ethers.parseEther('50'));
  });

  it('emits AllowlistUpdated on every allowlist change', async () => {
    await expect(pay.setAllowlisted(merchant.address, true))
      .to.emit(pay, 'AllowlistUpdated').withArgs(merchant.address, true);
    expect(await pay.allowlisted(merchant.address)).to.equal(true);

    await expect(pay.setAllowlisted(merchant.address, false))
      .to.emit(pay, 'AllowlistUpdated').withArgs(merchant.address, false);
    expect(await pay.allowlisted(merchant.address)).to.equal(false);
  });

  it('emits InvoiceConfigured with the exact invoice terms', async () => {
    const id = ethers.id('INV-100');
    const amount = ethers.parseEther('40');
    await pay.setAllowlisted(merchant.address, true);
    await pay.setAllowlisted(participant.address, true);
    await expect(pay.configureInvoice(id, merchant.address, participant.address, amount))
      .to.emit(pay, 'InvoiceConfigured').withArgs(id, merchant.address, participant.address, amount);
  });

  it('emits SettlementConfigured with the exact bounty terms', async () => {
    const id = ethers.id('bounty-1');
    const amount = ethers.parseEther('5');
    await expect(reward.configureSettlement(id, participant.address, amount))
      .to.emit(reward, 'SettlementConfigured').withArgs(id, participant.address, amount);
  });

  it('still pays an exact configured invoice through SafeERC20', async () => {
    const id = ethers.id('INV-100');
    const op = ethers.id('op-1');
    const amount = ethers.parseEther('40');
    await pay.setAllowlisted(merchant.address, true);
    await pay.setAllowlisted(participant.address, true);
    await token.transfer(pay.target, ethers.parseEther('100'));
    await pay.configureInvoice(id, merchant.address, participant.address, amount);
    await expect(pay.pay(op, id, merchant.address, participant.address, amount))
      .to.emit(pay, 'Payment').withArgs(op, id, merchant.address, participant.address, amount);
    expect(await token.balanceOf(participant.address)).to.equal(amount);
    expect(await pay.totalPaid()).to.equal(amount);
  });
});
