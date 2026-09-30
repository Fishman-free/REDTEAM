const { ethers } = require('hardhat');

async function main() {
  const [owner, merchant, participant] = await ethers.getSigners();
  const token = await (await ethers.getContractFactory('ExperimentalToken')).deploy(ethers.parseEther('1000'));
  const payment = await (await ethers.getContractFactory('PaymentAgent')).deploy(token, ethers.parseEther('100'));
  const reward = await (await ethers.getContractFactory('RewardSettlement')).deploy(token, ethers.parseEther('50'));
  await payment.setAllowlisted(merchant.address, true);
  await payment.setAllowlisted(participant.address, true);
  await token.transfer(payment.target, ethers.parseEther('100'));
  await token.transfer(reward.target, ethers.parseEther('50'));
  const invoice = ethers.id('INV-200');
  const operation = ethers.id('demo-operation');
  const amount = ethers.parseEther('10');
  await payment.configureInvoice(invoice, merchant.address, participant.address, amount);
  await payment.pay(operation, invoice, merchant.address, participant.address, amount);
  const settlement = ethers.id('demo-settlement');
  await reward.configureSettlement(settlement, participant.address, 5);
  await reward.settle(settlement, participant.address, 5);
  console.log(JSON.stringify({
    network: 'hardhat-in-process',
    token: token.target,
    paymentAgent: payment.target,
    rewardSettlement: reward.target,
    participantBalance: (await token.balanceOf(participant.address)).toString(),
    owner: owner.address
  }, null, 2));
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
